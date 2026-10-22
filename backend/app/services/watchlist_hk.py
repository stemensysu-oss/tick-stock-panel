"""HK watchlist quotes are fetched separately from the A-share enriched hot path."""
from __future__ import annotations

import math
import re
import threading
import time
from copy import deepcopy

from app.data_providers.research_market import LABELS, ResearchMarketService, ResearchSourceError

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, ...], tuple[float, dict]] = {}
_GOOD: dict[str, tuple[float, dict]] = {}
TTL = 60
MAX_SYMBOLS = 500


def is_hk(symbol):
    return isinstance(symbol, str) and re.fullmatch(r'\d{5}\.HK', symbol) is not None


def placeholder(symbol):
    return dict(symbol=symbol, name=None, asset_type='hk', currency=None, close=None,
                change_pct=None, turnover_rate=None, amount=None, quote_at=None,
                quote_source=None, quote_fetched_at=None, quote_status='unavailable',
                quote_warnings=['港股报价尚未取得；不使用 A 股行情或指标替代。'])


def cached_rows(symbols):
    """Memory only. Must remain safe for every SSE/enriched refresh."""
    now = time.monotonic()
    with _LOCK:
        saved = {symbol: _GOOD.get(symbol) for symbol in symbols}
    output = []
    for symbol in symbols:
        item = saved[symbol]
        row = deepcopy(item[1]) if item else placeholder(symbol)
        if item and now - item[0] >= TTL:
            row['quote_status'] = 'stale'
            row['quote_warnings'] = [*row['quote_warnings'], '上次成功报价尚未刷新，以原来源时点为准。']
        output.append(row)
    return output


def quote_snapshot(symbols, *, force=False, service=None):
    requested = sorted({s for s in symbols if is_hk(s)})
    warnings = []
    if len(requested) > MAX_SYMBOLS:
        warnings.append('每次最多刷新500只港股，超出的标的保持原记录。')
        requested = requested[:MAX_SYMBOLS]
    if not requested:
        return dict(rows=[], attempts=[], warnings=[], fetched_at=None, status='empty')
    key = tuple(requested)
    with _LOCK:
        cached = _CACHE.get(key)
    if service is None and cached and not force and time.monotonic() - cached[0] < TTL:
        return deepcopy(cached[1])
    batch = (service or ResearchMarketService()).fetch('quotes', requested)
    rows, found = [], set()
    for quote in batch.rows:
        if (quote.symbol not in requested or quote.extra.get('currency') != 'HKD'
                or not isinstance(quote.price, (int, float)) or isinstance(quote.price, bool)
                or not math.isfinite(quote.price) or quote.price <= 0):
            continue
        found.add(quote.symbol)
        rows.append(dict(symbol=quote.symbol, name=quote.name, asset_type='hk', currency='HKD',
                         close=quote.price,
                         # The research contract is percentage points; watchlist is fractional.
                         change_pct=quote.change_pct / 100 if quote.change_pct is not None else None,
                         turnover_rate=None, amount=None, quote_at=quote.quote_at,
                         quote_source=LABELS.get(quote.source, quote.source), source_id=quote.source,
                         quote_fetched_at=batch.fetched_at, quote_status='available',
                         quote_warnings=list(dict.fromkeys([*batch.warnings,
                             '公开港股报价可能延迟约15分钟；未接入的技术指标、分时和历史K线保持未知。'])),
                         quote_currency_source=quote.extra.get('currency_source')))
    if not rows:
        raise ResearchSourceError('港股未取得带明确港元币种的有效报价；保留原数据，请稍后重试')
    now = time.monotonic()
    with _LOCK:
        _GOOD.update({row['symbol']: (now, deepcopy(row)) for row in rows})
    missing = [symbol for symbol in requested if symbol not in found]
    if missing:
        warnings.append(f'{len(missing)}只港股未取得新报价；旧报价保留并注明状态。')
        for row in cached_rows(missing):
            row['quote_status'] = 'stale' if row['close'] is not None else 'unavailable'
            row['quote_warnings'] = [*row['quote_warnings'], '本次刷新未取得此标的新报价。']
            rows.append(row)
    result = dict(rows=rows, attempts=batch.attempts, warnings=[*batch.warnings, *warnings],
                  fetched_at=batch.fetched_at, status='available')
    if service is None:
        with _LOCK:
            if len(_CACHE) >= 16:
                _CACHE.clear()
            _CACHE[key] = now, deepcopy(result)
    return result
