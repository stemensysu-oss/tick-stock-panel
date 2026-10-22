"""Fund-specific fallback; cumulative NAV is never labelled adjusted NAV."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

from app.custom.funds.models import (
    FundHolding,
    FundHoldingsResponse,
    FundNavPoint,
    FundNavResponse,
    FundProfile,
    FundProfileResponse,
)
from app.custom.funds.provider import FuyaoFundProvider, get_api_key
from app.custom.funds.service import FundDataError
from app.data_providers.research_market import PUBLIC, SH, PublicHTTP, number


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def text(html):
    parser = Text()
    parser.feed(html)
    return ' '.join(''.join(parser.parts).split())


class Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.links = [], [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in {'td', 'th'}:
            self.cell = []
            self.links = []
        elif tag == 'a' and self.cell is not None:
            self.links.append(dict(attrs).get('href', ''))

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append((' '.join(''.join(self.cell).split()), self.links))
            self.cell = None
        elif tag == 'tr' and self.row:
            self.rows.append(self.row)


class EastmoneyFundProvider:
    name = PUBLIC

    def __init__(self, http=None):
        self.http = http or PublicHTTP()

    @staticmethod
    def meta(ticker):
        return dict(ticker=ticker, provider=PUBLIC,
                    timestamp_ms=int(datetime.now(SH).timestamp() * 1000))

    def profile(self, ticker):
        html = self.http.get(f'https://fundf10.eastmoney.com/jbgk_{ticker[:6]}.html').text
        table = re.search(r'<table[^>]*class=["\']info w790["\'][^>]*>(.*?)</table>', html, re.S)
        if not table:
            raise FundDataError(502, '公开基金资料页面格式已变化，未采用本次结果')
        fields = {text(k): text(v) for k, v in re.findall(
            r'<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)(?=</td>|<th|</tr>)', table[1], re.S)}
        if not fields.get('基金代码', '').startswith(ticker[:6]) or not fields.get('基金全称'):
            raise FundDataError(404, '公开资料未找到所请求基金')
        established = re.search(r'(\d{4})年(\d{2})月(\d{2})日', fields.get('成立日期/规模', ''))
        return FundProfileResponse(**self.meta(ticker), profile=FundProfile(
            fund_name=fields['基金全称'], mgmt_name=fields.get('基金管理人'),
            manager_name=fields.get('基金经理人'),
            established_date='-'.join(established.groups()) if established else None,
        ), warnings=['公开资料补充源；资料更新日期未提供。净值另按实际公布日期展示。'])

    def nav(self, ticker, nav_range):
        days = {'week': 7, 'month': 31, 'tmonth': 93, 'hyear': 184, 'year': 366,
                'twoyear': 732, 'tyear': 1098, 'fyear': 1830}[nav_range]
        cutoff = (datetime.now(SH).date() - timedelta(days=days)).isoformat()
        items, seen = [], set()
        def fetch(page):
            return self.http.get('https://api.fund.eastmoney.com/f10/lsjz', {
                'fundCode': ticker[:6], 'pageIndex': page, 'pageSize': 20,
                'startDate': cutoff, 'endDate': datetime.now(SH).date().isoformat(),
            }).json()
        first = fetch(1)
        total = int(first.get('TotalCount') or 0)
        if total > 2000:
            raise FundDataError(502, '公开净值区间超出 2000 条限制，请缩小区间')
        # The server clamps PageSize to 20 even if 100/500 is requested.
        # Use its actual pagination, otherwise a year silently becomes 20 days.
        with ThreadPoolExecutor(max_workers=4) as pool:
            payloads = [first, *pool.map(fetch, range(2, (total + 19) // 20 + 1))]
        for payload in payloads:
            rows = (payload.get('Data') or {}).get('LSJZList')
            if payload.get('ErrCode') != 0 or not isinstance(rows, list):
                raise FundDataError(502, '公开净值源返回异常')
            for row in rows:
                day = row.get('FSRQ')
                date.fromisoformat(day)
                if day in seen or day < cutoff or day > datetime.now(SH).date().isoformat():
                    continue
                seen.add(day)
                items.append(FundNavPoint(date=day, unit_nav=number(row.get('DWJZ'), positive=True)))
        if len(seen) != total:
            raise FundDataError(502, '公开净值分页不完整，未采用截断结果')
        return FundNavResponse(**self.meta(ticker), range=nav_range,
                               items=sorted(items, key=lambda item: item.date),
                               warnings=['公开补充源仅提供单位净值；累计净值未冒充复权净值，复权口径保持未知。'])

    def holdings(self, ticker):
        raw = self.http.get('https://fundf10.eastmoney.com/FundArchivesDatas.aspx', {
            'type': 'jjcc', 'code': ticker[:6], 'topline': 10,
        }).text
        # Parse the quoted string as data; never eval this JavaScript response.
        match = re.search(r'content\s*:\s*("(?:\\.|[^"\\])*")', raw, re.S)
        if not match:
            raise FundDataError(502, '公开持仓页面格式已变化')
        html = json.loads(match[1])
        table = re.search(r'<table\b.*?</table>', html, re.S)
        if not table:
            return FundHoldingsResponse(**self.meta(ticker), warnings=['公开源尚未披露股票前十大持仓；不代表没有持仓。'])
        report = re.search(r'截止至[：:]\s*(?:<[^>]*>\s*)*(\d{4}-\d{2}-\d{2})', html[:table.start()])
        if not report:
            raise FundDataError(502, '公开持仓缺少报告期，未采用本次结果')
        date.fromisoformat(report[1])
        parser = Table()
        parser.feed(table[0])
        headers = [c[0] for c in parser.rows[0]]
        positions = [headers.index(k) for k in ('股票代码', '股票名称', '占净值比例')]
        items = []
        for row in parser.rows[1:11]:
            code, name, weight = (row[i][0] for i in positions)
            if not re.fullmatch(r'\d{6}', code):
                continue
            links = ' '.join(row[positions[0]][1])
            market = re.search(r'/unify/r/([01])\.' + code + r'\b', links)
            suffix = f'.{"SH" if market[1] == "1" else "SZ"}' if market else ''
            items.append(FundHolding(ticker=code + suffix, name=name, asset_type='stock',
                                     weight_pct=number(weight.removesuffix('%')),
                                     report_date=report[1]))
        return FundHoldingsResponse(**self.meta(ticker), items=items,
            warnings=['仅最近披露报告期的前十大股票；不是实时或完整持仓，公告日与资产配置比例未提供。'])


class FallbackFundProvider:
    """The integrated TickFlow contract has no fund profile/NAV/holdings dataset.

    Fuyao is attempted first for each supported dataset. Only an exception or
    empty usable dataset permits public fallback; primary success is untouched.
    """
    def __init__(self, primary=None, fallback=None, key_getter=None):
        self.key_getter = key_getter or get_api_key
        self.primary = primary
        self.fallback = fallback or EastmoneyFundProvider()

    def _call(self, operation, *args):
        attempts = [{'provider': 'tickflow', 'status': 'unsupported'}]
        key = self.key_getter()
        if key or self.primary is not None:
            try:
                result = getattr(self.primary or FuyaoFundProvider(key), operation)(*args)
                usable = (result.profile is not None and bool(result.profile.fund_name) if operation == 'profile'
                          else any(p.unit_nav is not None or p.adj_nav is not None for p in result.items) if operation == 'nav'
                          else bool(result.items))
                attempts.append({'provider': 'fuyao', 'status': 'success' if usable else 'empty'})
                if usable:
                    return result.model_copy(update={'attempts': attempts})
            except Exception:  # noqa: BLE001 -- redact supplier exceptions that can contain keys
                attempts.append({'provider': 'fuyao', 'status': 'failed'})
        else:
            attempts.append({'provider': 'fuyao', 'status': 'unconfigured'})
        try:
            result = getattr(self.fallback, operation)(*args)
            return result.model_copy(update={'attempts': [*attempts, {'provider': PUBLIC, 'status': 'success'}]})
        except Exception:  # noqa: BLE001 -- only a fixed safe message crosses the route boundary
            raise FundDataError(502, '主数据源与公开补充源均未返回可用基金数据，请稍后重试或检查基金代码及主 API 权限') from None

    def profile(self, ticker):
        return self._call('profile', ticker)

    def nav(self, ticker, nav_range):
        return self._call('nav', ticker, nav_range)

    def holdings(self, ticker):
        return self._call('holdings', ticker)
