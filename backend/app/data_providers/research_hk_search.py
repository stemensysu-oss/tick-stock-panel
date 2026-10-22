"""Global HK discovery, independent of the turnover-limited market snapshot.

TickFlow metadata/explicit quote has priority. Public suggestions supply only
identity, never a price, listing-status guarantee or assumed HKD currency.
"""
from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from urllib.parse import quote

from app.data_providers.research_market import (
    SH,
    PublicHTTP,
    ResearchMarketService,
    ResearchSourceError,
)

_QUERY_TTL = 60
_DIRECTORY_TTL = 3600
_LOCK = threading.Lock()
_QUERY_CACHE = OrderedDict()
_DIRECTORY_CACHE = OrderedDict()
_KNOWN_NAMES = OrderedDict()
_ALIAS = {'腾讯科技': '腾讯', '騰訊科技': '騰訊'}


def canonical_hk(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(?:HK)?(\d{5})(?:\.HK)?', value.strip().upper())
    return f'{match[1]}.HK' if match else None


def known_name(symbol):
    """Cache-only actual source name for watchlists; never triggers a request."""
    canonical = canonical_hk(symbol)
    with _LOCK:
        return _KNOWN_NAMES.get(canonical)


def _candidate(symbol, name, source):
    canonical = canonical_hk(symbol)
    if (canonical is None or not isinstance(name, str) or not name.strip()
            or name.strip().upper() in {canonical, canonical[:5] if canonical else '', str(symbol).upper()}
            or len(name) > 100 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name)):
        return None
    return dict(symbol=canonical, code=canonical[:5], name=name.strip(), asset_type='hk', source=source)


def _remember(results):
    with _LOCK:
        for row in results:
            _KNOWN_NAMES[row['symbol']] = row['name']
            _KNOWN_NAMES.move_to_end(row['symbol'])
        while len(_KNOWN_NAMES) > 1000:
            _KNOWN_NAMES.popitem(last=False)


def _tickflow_directory():
    from tickflow import TickFlow

    from app import secrets_store

    key = secrets_store.get_tickflow_key()
    if not key:
        raise PermissionError
    base = secrets_store.load().get('tickflow_base_url') or None
    identity = hashlib.sha256((key + '\0' + (base or '')).encode()).hexdigest()
    with _LOCK:
        cached = _DIRECTORY_CACHE.get(identity)
    if cached and time.monotonic() - cached[0] < _DIRECTORY_TTL:
        return cached[1]
    client = TickFlow(api_key=key, base_url=base, timeout=8, max_retries=0)
    try:
        # This is the documented SDK metadata method; no guessed search endpoint.
        raw = client.exchanges.get_instruments('HK', instrument_type='stock')
    finally:
        client.close()
    if not isinstance(raw, list) or len(raw) > 6000:
        raise ResearchSourceError('主 API 港股证券目录为空或超限')
    rows = [row for item in raw if isinstance(item, dict)
            and (row := _candidate(item.get('symbol'), item.get('name'), 'tickflow'))]
    with _LOCK:
        _DIRECTORY_CACHE[identity] = (time.monotonic(), rows)
        _DIRECTORY_CACHE.move_to_end(identity)
        while len(_DIRECTORY_CACHE) > 4:
            _DIRECTORY_CACHE.popitem(last=False)
    return rows


def _match_directory(rows, query, exact, limit):
    key = query.casefold()
    matches = [row for row in rows if row['symbol'] == exact or key in row['name'].casefold()
               or key in row['code'] or key in row['symbol'].casefold()]
    matches.sort(key=lambda row: (row['symbol'] != exact, row['name'].casefold() != key, row['symbol']))
    return matches[:limit]


def parse_tencent_suggestions(body):
    match = re.fullmatch(r'\s*v_hint="([^"\r\n]*)";?\s*', body)
    if not match:
        raise ResearchSourceError('公开港股搜索响应格式异常')
    # Decode only escaped Unicode text, never evaluate a script/JSONP callback.
    content = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), match[1])
    output = {}
    for entry in content.split('^')[:100]:
        fields = entry.split('~')
        if len(fields) < 5 or fields[0] != 'hk' or fields[4] != 'GP':
            continue  # Public suggestions also contain warrants and other markets.
        row = _candidate(fields[1], fields[2], 'tencent_public')
        if row:
            output.setdefault(row['symbol'], row)
    return list(output.values())


def parse_sina_suggestions(body):
    match = re.fullmatch(r'\s*var suggestvalue="([^"\r\n]*)";?\s*', body)
    if not match:
        raise ResearchSourceError('新浪公开港股搜索响应格式异常')
    output = {}
    for entry in match[1].split(';')[:100]:
        fields = entry.split(',')
        if len(fields) < 8 or fields[7] != 'HK' or not re.fullmatch(r'hk\d{5}', fields[0]):
            continue
        row = _candidate(fields[0], fields[4], 'sina_public')
        if row:
            output.setdefault(row['symbol'], row)
    return list(output.values())


def _public_tencent(query):
    response = PublicHTTP().get('https://smartbox.gtimg.cn/s3/',
                                {'v': 2, 't': 'hk', 'c': 1, 'q': query})
    return parse_tencent_suggestions(response.content.decode('gb18030'))


def _public_sina(query):
    response = PublicHTTP().get('https://suggest3.sinajs.cn/suggest/type=2&key=' +
                                quote(query))
    return parse_sina_suggestions(response.content.decode('gb18030'))


def _search(query, limit):
    attempts, warnings, results = [], [], []
    resolved = _ALIAS.get(query, query)
    if resolved != query:
        warnings.append(f'“{query}”按品牌简称“{resolved}”检索；返回名称以实际证券资料为准，不将品牌名写成证券名称。')
    exact = canonical_hk(query)
    if exact:
        try:
            batch = ResearchMarketService().fetch('quotes', [exact])
            attempts.extend({**a, 'dataset': a.get('dataset', 'hk_exact_quote')} for a in batch.attempts)
            for raw in batch.rows:
                if raw.symbol == exact and (row := _candidate(raw.symbol, raw.name, raw.source)):
                    results.append(row)
            warnings.extend(batch.warnings)
        except (ResearchSourceError, ValueError):
            attempts.append({'provider': 'quote_chain', 'dataset': 'hk_exact_quote', 'status': 'failed'})
    if not results:
        try:
            results = _match_directory(_tickflow_directory(), resolved, exact, limit)
            attempts.append({'provider': 'tickflow', 'dataset': 'hk_search',
                             'status': 'success' if results else 'empty', 'rows': len(results)})
        except PermissionError:
            attempts.append({'provider': 'tickflow', 'dataset': 'hk_search', 'status': 'unconfigured'})
        except Exception:  # noqa: BLE001 -- vendor exception text can contain account credentials.
            attempts.append({'provider': 'tickflow', 'dataset': 'hk_search', 'status': 'failed'})
    if not results:
        # Fuyao's published HK contract is IPO, not a stock directory/name search.
        attempts.append({'provider': 'fuyao', 'dataset': 'hk_search', 'status': 'unsupported'})
        for provider, fetch in [('tencent_public', _public_tencent), ('sina_public', _public_sina)]:
            try:
                results = fetch(exact[:5] if exact else resolved)[:limit]
                if exact:
                    results = [row for row in results if row['symbol'] == exact]
                attempts.append({'provider': provider, 'dataset': 'hk_search',
                                 'status': 'success' if results else 'empty', 'rows': len(results)})
                if results:
                    break
            except (ResearchSourceError, ValueError, UnicodeError):
                attempts.append({'provider': provider, 'dataset': 'hk_search', 'status': 'failed'})
    if not results:
        warnings.append('港股搜索暂未取得匹配结果；公开服务可能中断，可稍后按五位代码重试。' if any(a['status'] == 'failed' for a in attempts)
                        else '未找到匹配的港股名称或代码；本搜索不以成交额前 500 只清单为范围。')
    if any(row['source'] in {'tencent_public', 'sina_public'} for row in results):
        warnings.append('公开港股名称建议不受成交额前 500 只清单限制；建议结果只确认名称和代码，价格、币种和报价时间需单独查询。')
    _remember(results)
    return dict(query=query, resolved_query=resolved, results=results, attempts=attempts,
                warnings=list(dict.fromkeys(warnings)), fetched_at=datetime.now(SH).isoformat(timespec='seconds'))


def search_hk(query, limit=20):
    if (not isinstance(query, str) or not query.strip() or len(query.strip()) > 50
            or any(ord(c) < 32 or ord(c) == 127 for c in query)):
        raise ValueError('港股搜索关键词须为 1 至 50 个有效字符')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError('港股搜索条数须为 1 至 50')
    query = query.strip()
    key = (query, limit)
    with _LOCK:
        cached = _QUERY_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _QUERY_TTL:
        return copy.deepcopy(cached[1])
    result = _search(query, limit)
    # An empty/error response is not cached: a corrected connection can retry.
    if result['results']:
        with _LOCK:
            _QUERY_CACHE[key] = (time.monotonic(), copy.deepcopy(result))
            _QUERY_CACHE.move_to_end(key)
            while len(_QUERY_CACHE) > 128:
                _QUERY_CACHE.popitem(last=False)
    return result
