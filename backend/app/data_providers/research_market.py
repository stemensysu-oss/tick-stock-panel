"""Bounded research feeds. TickFlow -> Fuyao -> public Eastmoney, per capability.

This is separate from the A-share trading/depth contract. No cookies, user
sessions, Jisilu endpoints, executable JavaScript, or synthetic price defaults.
"""
from __future__ import annotations

import gzip
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

import httpx

SH = ZoneInfo('Asia/Shanghai')
logger = logging.getLogger(__name__)
PUBLIC = 'eastmoney_public'
FILTERS = {
    'bonds': 'b:MK0354',
    'etf': 'b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827',
    'lof': 'b:MK0404,b:MK0405,b:MK0406,b:MK0407',
    'cash': 'b:MK0401',
    'reits': 'm:1 t:9 e:97,m:0 t:10 e:97',
    'indices': 'm:1 t:1,m:0 t:5',
    'hk': 'm:128 t:3,m:128 t:4',
}
UNIVERSES = {'bonds': 'CN_Bond', 'etf': 'CN_ETF', 'indices': 'CN_Index', 'hk': 'HK_Equity'}
LABELS = {'tickflow': 'TickFlow', 'fuyao': '扶摇', PUBLIC: '东方财富公开补充源',
          'tencent_public': '腾讯公开补充行情', 'sina_tencent_public': '公开备用目录与行情'}
DISCLOSURE = '公开网页补充源可能延迟或中断；报价时间不等于抓取时间。未提供的净值、条款、收益率和公告保持未知。'
_HTTP_LOCK = threading.Lock()
_HTTP_NEXT: dict[str, float] = {}


class ResearchSourceError(ValueError):
    pass


@dataclass(frozen=True)
class MarketRow:
    symbol: str
    name: str
    price: float | None
    quote_at: str
    source: str
    change_pct: float | None = None  # percentage points
    amount: float | None = None  # CNY
    turnover_pct: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class MarketBatch:
    rows: list[MarketRow]
    fetched_at: str
    attempts: list[dict]
    warnings: list[str] = field(default_factory=list)


def number(value, *, positive=False):
    if value in (None, '', '-'):
        return None
    if isinstance(value, bool):
        raise ResearchSourceError('补充源数值格式异常')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ResearchSourceError('补充源数值格式异常') from None
    if not math.isfinite(result) or abs(result) > 1e18:
        raise ResearchSourceError('补充源数值越界')
    return result if not positive or result > 0 else None


def quote_time(value, *, milliseconds=False):
    value = number(value, positive=True)
    if value is None:
        raise ResearchSourceError('数据源缺少报价时间，未采用此行情')
    try:
        dt = datetime.fromtimestamp(value / (1000 if milliseconds else 1), SH)
    except (ValueError, OSError, OverflowError):
        raise ResearchSourceError('数据源报价时间异常') from None
    if dt.year < 1990 or dt > datetime.now(SH) + timedelta(minutes=10):
        raise ResearchSourceError('数据源报价时间异常')
    return dt.isoformat(timespec='seconds')


class PublicHTTP:
    """Fixed public hosts only; no inherited authentication or credential logs."""
    hosts = frozenset({'query1.finance.yahoo.com', 'push2.eastmoney.com', 'api.fund.eastmoney.com',
                       'fundf10.eastmoney.com', 'datacenter-web.eastmoney.com', 'datacenter.eastmoney.com',
                       'vip.stock.finance.sina.com.cn', 'qt.gtimg.cn',
                       'www.aastocks.com', 'query.sse.com.cn',
                       'smartbox.gtimg.cn', 'suggest3.sinajs.cn', 'web.ifzq.gtimg.cn'})

    def get(self, url, params=None):
        for attempt in range(2):
            try:
                return self._once(url, params)
            except ResearchSourceError as exc:
                if attempt or not getattr(exc, 'retryable', False):
                    raise
                time.sleep(0.35)

    def _once(self, url, params=None):
        host = httpx.URL(url).host
        if host not in self.hosts:
            raise ResearchSourceError('不支持的补充源地址')
        # One process-wide queue per public host: at most ~3 requests/second,
        # including pagination and concurrent fund queries. Do not hammer feeds.
        with _HTTP_LOCK:
            delay = max(0, _HTTP_NEXT.get(host, 0) - time.monotonic())
            _HTTP_NEXT[host] = time.monotonic() + delay + 0.35
        if delay:
            time.sleep(delay)
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        try:
            target = url + ('?' + urlencode(params) if params else '')
            request = Request(target, headers={
                'User-Agent': 'TSP/0.3.20 personal-research' if host == 'query1.finance.yahoo.com' else 'Mozilla/5.0', 'Accept-Encoding': 'identity',
                'Referer': ('https://finance.yahoo.com/' if host == 'query1.finance.yahoo.com' else
                            'https://finance.sina.com.cn/' if host == 'suggest3.sinajs.cn' else
                            'https://www.sse.com.cn/' if host == 'query.sse.com.cn' else
                            'https://quote.eastmoney.com/' if host == 'push2.eastmoney.com' else
                            'https://fundf10.eastmoney.com/'),
            })
            # urllib's HTTP/1.1 transport is compatible with this public feed;
            # the default httpx transport can be disconnected by its servers.
            with build_opener(NoRedirect()).open(request, timeout=12) as response:
                stream = (gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding') == 'gzip'
                          else response)
                content = stream.read(8 * 1024 * 1024 + 1)
                if len(content) > 8 * 1024 * 1024:
                    raise ResearchSourceError('补充源响应超过大小限制')
                return httpx.Response(200, content=content,
                                      headers={'Content-Type': response.headers.get('Content-Type', 'application/json')})
        except (TimeoutError, HTTPError, URLError, OSError) as exc:
            status = exc.code if isinstance(exc, HTTPError) else None
            problem = f'HTTP {status}' if status else type(exc).__name__
            error = ResearchSourceError(f'公开补充源暂时不可用（{problem}），请稍后重试')
            error.retryable = (status is None or status in {429, 500, 502, 503, 504}) and not (host == 'query1.finance.yahoo.com' and status in {401,403,429})
            raise error from None



class EastmoneyMarketProvider:
    name = PUBLIC

    def __init__(self, http=None):
        self.http = http or PublicHTTP()

    @staticmethod
    def _row(raw):
        exchange = {0: 'SZ', 1: 'SH'}.get(raw.get('f13'))
        code, name = raw.get('f12'), raw.get('f14')
        if not exchange or not isinstance(code, str) or not re.fullmatch(r'\d{6,8}', code):
            raise ResearchSourceError('补充源证券市场或代码异常')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ResearchSourceError('补充源证券名称异常')
        return MarketRow(
            f'{code}.{exchange}', name.strip(), number(raw.get('f2'), positive=True),
            quote_time(raw.get('f124')), PUBLIC, number(raw.get('f3')),
            number(raw.get('f6')), number(raw.get('f8')),
            {key: raw.get(key) for key in ('f232', 'f234', 'f235')},
        )

    def _list(self, params):
        output, total = [], None
        started = time.monotonic()
        for page in range(1, 22):  # 2,000 rows, plus an explicit truncation check.
            if time.monotonic() - started > 45:
                raise ResearchSourceError('市场分页取数超时，原数据已保留')
            payload = self.http.get('https://push2.eastmoney.com/api/qt/clist/get', {
                'pn': page, 'pz': 100, 'po': 0, 'np': 1, 'fltt': 2, 'invt': 2,
                'fid': 'f12', **params,
                'fields': 'f2,f3,f6,f8,f12,f13,f14,f124,f232,f234,f235',
                # Public website client identifier, not an account credential.
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            }).json()
            data = payload.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('diff'), list):
                raise ResearchSourceError('补充源清单为空或格式异常')
            if total is None:
                total = int(data.get('total') or 0)
                if total > 2000:
                    raise ResearchSourceError('市场清单超过 2000 条，请缩小类别范围')
            rows = data['diff']
            output.extend(self._row(row) for row in rows)
            if len(output) >= total:
                break
            if not rows:
                raise ResearchSourceError('补充源清单分页不完整')
        if not output or len(output) != total or len({r.symbol for r in output}) != len(output):
            raise ResearchSourceError('补充源清单为空、不完整或含重复代码')
        return output

    def market(self, category):
        if category not in FILTERS or category == 'hk':
            # The integrated clist schema has no verified quote currency for HK counters.
            raise NotImplementedError
        return self._list({'fs': FILTERS[category]})

    def quotes(self, symbols):
        result = []
        # Explicit symbol batches avoid a stock-universe download or code-role guessing.
        for offset in range(0, len(symbols), 50):
            chunk = symbols[offset:offset + 50]
            secids = ','.join(f'{1 if s.endswith(".SH") else 0}.{s[:6]}' for s in chunk
                              if re.fullmatch(r'\d{6}\.(SH|SZ)', s))
            if not secids:
                continue
            payload = self.http.get('https://push2.eastmoney.com/api/qt/ulist.np/get', {
                'secids': secids, 'fltt': 2, 'invt': 2,
                'fields': 'f2,f3,f6,f8,f12,f13,f14,f124',
            }).json()
            raw = (payload.get('data') or {}).get('diff') or []
            for row in raw:
                item = self._row(row)
                if item.symbol not in chunk:
                    raise ResearchSourceError('补充源返回未请求代码')
                result.append(item)
        return result


class TickFlowResearchProvider:
    name = 'tickflow'

    def _fetch(self, **kwargs):
        self.metadata_attempts = []
        from tickflow import TickFlow

        from app import secrets_store

        key = secrets_store.get_tickflow_key()
        if not key:
            raise PermissionError
        client = TickFlow(api_key=key, base_url=secrets_store.load().get('tickflow_base_url') or None, timeout=8, max_retries=0)
        try:
            raw = client.quotes.get(**kwargs)
        finally:
            client.close()
        if not isinstance(raw, list) or len(raw) > (6000 if kwargs.get('universes') == ['HK_Equity'] else 2000):
            raise ResearchSourceError('TickFlow 清单为空或超限')
        if kwargs.get('universes') == ['HK_Equity']:
            # Bound metadata requests before fetching any missing currency data.
            raw = sorted(raw, key=lambda r: number(r.get('amount')) or 0, reverse=True)[:500]
        currency_metadata = {}
        missing_currency = [r['symbol'] for r in raw
                            if re.fullmatch(r'\d{5}\.HK', r.get('symbol', ''))
                            and not (r.get('currency') or (r.get('ext') or {}).get('currency'))]
        if missing_currency:
            from app.data_providers.research_public_backup import PublicBackupProvider
            self.metadata_attempts = [
                {'provider': p, 'dataset': 'quote_currency', 'status': 'unsupported'}
                for p in ('tickflow', 'fuyao')]
            try:
                currency_metadata = {r.symbol: r for r in PublicBackupProvider().quotes(missing_currency)}
                self.metadata_attempts.append({'provider': 'tencent_public', 'dataset': 'quote_currency',
                    'status': 'success' if currency_metadata else 'empty', 'rows': len(currency_metadata)})
            except (ResearchSourceError, UnicodeError, ValueError):
                # Unknown currency is not permission to relabel a RMB dual counter.
                self.metadata_attempts.append({'provider': 'tencent_public', 'dataset': 'quote_currency', 'status': 'failed'})
        rows = []
        for row in raw:
            symbol = row.get('symbol', '')
            if not re.fullmatch(r'(?:\d{6}\.(SH|SZ)|\d{5}\.HK)', symbol):
                continue
            ext = row.get('ext') or {}
            currency = row.get('currency') or ext.get('currency')
            currency_info = currency_metadata.get(symbol)
            if not currency and currency_info:
                currency = currency_info.extra.get('currency')
            if symbol.endswith('.HK') and currency != 'HKD':
                # SDK quote schema does not promise a currency. RMB dual counters
                # exist: never infer HKD from the .HK suffix.
                continue
            price = number(row.get('last_price'), positive=True)
            ext = row.get('ext') or {}
            change = number(ext.get('change_pct'))
            turnover = number(ext.get('turnover_rate'))
            extra = {'currency': currency} if symbol.endswith('.HK') else {}
            if currency_info:
                extra.update(currency_source=currency_info.source, currency_quote_at=currency_info.quote_at,
                             coverage_note='主 API 价格与报价时间保持不变；缺失的港股币种由公开来源当次明确提供，未采用补充源价格。')
            rows.append(MarketRow(symbol, row.get('name') or ext.get('name') or symbol, price,
                                  quote_time(row.get('timestamp'), milliseconds=True), self.name,
                                  change * 100 if change is not None else None,
                                  number(row.get('amount')),
                                  turnover * 100 if turnover is not None else None,
                                  extra))
        return rows

    def market(self, category):
        if category not in UNIVERSES:
            raise NotImplementedError
        rows = self._fetch(universes=[UNIVERSES[category]])
        if category == 'hk':
            from dataclasses import replace
            rows = [replace(row, extra={**row.extra, 'coverage_note':
                    '港股展示主接口按成交额排序的前 500 条有效港元报价；非全港股，非人民币双柜台。' + row.extra.get('coverage_note', '')})
                    for row in sorted(rows, key=lambda r: r.amount or 0, reverse=True)[:500]]
        return rows

    def quotes(self, symbols):
        return self._fetch(symbols=symbols)


class FuyaoResearchProvider:
    name = 'fuyao'

    def market(self, category):
        # No documented complete bond/fund catalog in the integrated Fuyao contract.
        raise NotImplementedError

    def quotes(self, symbols):
        from app.plugins.fuyao.client import FuyaoClient
        from app.plugins.fuyao.provider import get_api_key
        stocks = [s for s in symbols if re.fullmatch(
            r'(?:(?:600|601|603|605|688|689)\d{3}\.SH|(?:000|001|002|003|300|301)\d{3}\.SZ)', s)]
        if not stocks:
            raise NotImplementedError
        key = get_api_key()
        if not key:
            raise PermissionError
        client = FuyaoClient(key, timeout=8)
        try:
            data = client._get('/api/a-share/prices/snapshot', {'thscodes': ','.join(stocks)})
        finally:
            client.close()
        rows = []
        for row in data.get('item') or []:
            symbol = row.get('thscode')
            if symbol not in stocks:
                continue
            price = number(row.get('last_price'), positive=True)
            # Fuyao snapshot price_change_ratio_pct is percentage points.
            rows.append(MarketRow(symbol, row.get('name') or symbol, price,
                                  quote_time(row.get('timestamp') or data.get('timestamp'), milliseconds=True),
                                  self.name, number(row.get('price_change_ratio_pct')),
                                  number(row.get('turnover'))))
        return rows


class ResearchMarketService:
    def __init__(self, providers=None):
        from app.data_providers.research_public_backup import PublicBackupProvider

        self.providers = providers if providers is not None else [
            TickFlowResearchProvider(), FuyaoResearchProvider(), EastmoneyMarketProvider(),
            PublicBackupProvider()]

    def fetch(self, operation, argument):
        attempts, found = [], {}
        requested = set(argument) if operation == 'quotes' else None
        for provider in self.providers:
            if requested is not None and not requested - found.keys():
                break
            try:
                value = sorted(requested - found.keys()) if requested is not None else argument
                rows = getattr(provider, operation)(value)
                valid = [r for r in rows if r.price is not None
                         and (requested is None or r.symbol in requested)]
                attempts.append({'provider': provider.name,
                                 'status': 'success' if valid else 'empty', 'rows': len(valid)})
                attempts.extend(getattr(provider, 'metadata_attempts', []))
                # Never replace a successful primary quote with a public fallback quote.
                for row in valid:
                    found.setdefault(row.symbol, row)
                if operation == 'market' and valid:
                    break
            except NotImplementedError:
                attempts.append({'provider': provider.name, 'status': 'unsupported'})
            except PermissionError:
                attempts.append({'provider': provider.name, 'status': 'unconfigured'})
            except Exception as exc:  # noqa: BLE001 -- supplier exceptions/URLs can include keys
                attempts.append({'provider': provider.name, 'status': 'failed'})
                reason = str(exc) if isinstance(exc, ResearchSourceError) else type(exc).__name__
                logger.warning('Research source failed: provider=%s operation=%s reason=%s',
                               provider.name, operation, reason)
        if not found:
            raise ResearchSourceError('所有可用数据源均未返回有效行情；原数据已保留，请稍后重试或检查主 API 权限')
        warnings = [DISCLOSURE] if any(r.source in {PUBLIC, 'tencent_public'}
                     or r.extra.get('currency_source') == 'tencent_public' for r in found.values()) else []
        warnings.extend(sorted({r.extra['coverage_note'] for r in found.values()
                                if r.extra.get('currency_source') and r.extra.get('coverage_note')}))
        if operation == 'market' and argument != 'hk' and any(r.source == 'tencent_public' for r in found.values()):
            warnings.append('公开备用行情只保留最近 30 天有来源时点的记录；现金管理仅两只代表货币 ETF，指数仅六只代表指数，均非全市场目录。')
            warnings.extend(sorted({r.extra['coverage_note'] for r in found.values()
                                    if r.extra.get('coverage_note')}))
        if operation == 'market' and argument == 'hk':
            warnings.extend(sorted({r.extra['coverage_note'] for r in found.values()
                                    if r.extra.get('coverage_note')}))
        if requested is not None and requested - found.keys():
            warnings.append(f'{len(requested - found.keys())} 个标的未返回有效报价，未伪造价格。')
        return MarketBatch(list(found.values()), datetime.now(SH).isoformat(timespec='seconds'), attempts, list(dict.fromkeys(warnings)))


_CACHE, _LOCK = {}, threading.Lock()


def market_batch(category, *, force=False):
    # In-memory public/primary snapshots are separate from user imports. A failed
    # refresh never writes a cache entry or advances the successful fetch time.
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(category)
    if cached and not force and now - cached[0] < 60:
        return cached[1]
    result = ResearchMarketService().fetch('market', category)
    with _LOCK:
        _CACHE[category] = (time.monotonic(), result)
    return result
