"""Route non-mainland watchlist assets without contaminating mainland indicators."""

from app.data_providers.international import is_international
from app.services import international_stocks, watchlist_hk


def is_external(symbol):
    return watchlist_hk.is_hk(symbol) or is_international(symbol)


def cached_rows(symbols):
    return watchlist_hk.cached_rows(
        [s for s in symbols if watchlist_hk.is_hk(s)]
    ) + international_stocks.cached_rows(symbols)


def quote_snapshot(symbols, force=False):
    if not any(is_international(s) for s in symbols):
        return watchlist_hk.quote_snapshot(symbols, force=force)
    result = international_stocks.quote_snapshot(symbols, force)
    hk = [s for s in symbols if watchlist_hk.is_hk(s)]
    if hk:
        try:
            other = watchlist_hk.quote_snapshot(hk, force=force)
            result["rows"] += other["rows"]
            result["attempts"] += other["attempts"]
            result["warnings"] += other["warnings"]
        except Exception:  # noqa: BLE001 -- isolate providers and never expose credential-bearing errors
            result["rows"] += watchlist_hk.cached_rows(hk)
            result["warnings"].append("港股本次刷新失败，原报价保留。")
    return result
