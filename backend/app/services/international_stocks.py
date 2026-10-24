"""Historical international analysis and memory-only watchlist projections."""

from __future__ import annotations

import hashlib
import threading
import time
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from app.data_providers import international as provider
from app.indicators.levels import compute_levels
from app.indicators.pipeline import compute_indicators
from app.services.hk_stock_analysis import INDICATORS
from app.services.stock_analysis_series import _build_series

_CACHE = {}
_QUOTES = {}
_LOCK = threading.Lock()


def snapshot(symbol, force=False):
    from app import secrets_store

    kind, currency, zone = provider.market(symbol)
    identity = hashlib.sha256(
        (
            secrets_store.get_tickflow_key()
            + "\0"
            + secrets_store.get_env_backed_secret("jquants_api_key", "JQUANTS_API_KEY")
            + "\0"
            + str(secrets_store.load().get("tickflow_base_url") or "")
        ).encode()
    ).hexdigest()
    key = (symbol, identity)
    with _LOCK:
        cached = _CACHE.get(key)
    if cached and not force and time.monotonic() - cached[0] < 300:
        return deepcopy(cached[1])
    daily = provider.fetch_daily(symbol)
    frame = compute_indicators(
        pl.DataFrame(daily["rows"]).with_columns(pl.col("date").str.to_date()), needed=INDICATORS
    ).tail(250)
    levels = compute_levels(frame)
    levels["sr"] = []
    rows = frame.with_columns(pl.col("date").dt.strftime("%Y-%m-%d")).to_dicts()
    import math

    rows = [
        {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in row.items()}
        for row in rows
    ]
    label = "美股" if kind == "us" else "日股"
    source = {
        "tickflow": "TickFlow",
        "tickflow_public": "TickFlow公开历史日K",
        "jquants": "JPX J-Quants",
        "yahoo_public": "Yahoo全球公开补充日K",
    }[daily["source"]]
    basis = daily.get("price_basis", "unadjusted")
    warnings = [
        "历史收盘数据，不是实时行情；以交易所当地交易日期为准。",
        "来源未说明复权口径；不推算分红或拆合股收益。"
        if basis == "source_unspecified"
        else "使用不复权价格；分红、拆合股可能造成跳空，不代表实际收益。",
        "财务、新闻、历史换手率与筹码分布尚未接入；不使用A股交易规则替代。",
    ]
    if daily["source"] == "jquants":
        warnings.append("J-Quants免费计划延迟12周；其他计划按账户权限提供日终数据，不是实时行情。")
    if daily["source"] == "yahoo_public":
        warnings.append(
            "Yahoo全球非正式公开接口，仅供个人研究；自动使用许可适用范围未确认，不代表正式数据授权。东京报价按20分钟延迟标记，历史日K只使用今天之前的日期。"
        )
    close = rows[-1]["close"]
    quote = dict(
        symbol=symbol,
        name=provider.NAMES.get(symbol, symbol),
        asset_type=kind,
        currency=currency,
        close=close,
        change_pct=None,
        quote_at=rows[-1]["date"],
        quote_source=source,
        quote_status="historical",
        quote_warnings=warnings,
    )
    metadata = daily.get("metadata") or {}
    if daily["source"] == "yahoo_public" and metadata.get("price"):
        quote.update(
            name=metadata.get("name") or quote["name"],
            close=metadata["price"],
            quote_at=metadata["quote_at"],
            quote_status="delayed",
            quote_warnings=[
                *warnings,
                f"报价延迟标记：{metadata.get('delay_minutes')}分钟；以来源时点为准。",
            ],
        )
    value = dict(
        symbol=symbol,
        name=quote["name"],
        asset_type=kind,
        currency=currency,
        timezone=zone,
        market_label=label,
        price_basis=basis,
        volume_unit="source_native",
        rows=rows,
        levels=levels,
        series=_build_series(frame),
        dates=[r["date"] for r in rows],
        close=close,
        as_of=rows[-1]["date"],
        quote=quote,
        source=daily["source"],
        source_name=source,
        fetched_at=datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds"),
        warnings=warnings,
        attempts=daily["attempts"],
    )
    with _LOCK:
        if len(_CACHE) >= 128:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), deepcopy(value))
    return value


def cached_rows(symbols):
    # Hot paths never read credentials or fetch network data.
    with _LOCK:
        saved = {key[0]: value for key, value in _CACHE.items()}
    output = []
    for symbol in symbols:
        if not provider.is_international(symbol):
            continue
        kind, currency, _ = provider.market(symbol)
        item = saved.get(symbol)
        row = (
            deepcopy(item[1]["quote"])
            if item
            else dict(
                symbol=symbol,
                name=provider.NAMES.get(symbol, symbol),
                asset_type=kind,
                currency=currency,
                close=None,
                change_pct=None,
                quote_at=None,
                quote_source=None,
                quote_status="unavailable",
                quote_warnings=["数据尚未读取；请刷新以按原有API、公开补充源顺序获取。"],
            )
        )
        with _LOCK:
            latest = _QUOTES.get(symbol)
        if latest:
            row = deepcopy(latest[1])
            item = latest
        if item and time.monotonic() - item[0] >= 300:
            row["quote_status"] = "stale"
            row["quote_warnings"].append("数据尚未重新获取，请核对来源日期。")
        output.append(row)
    return output


def quote_snapshot(symbols, force=False):
    warnings = []
    for symbol in sorted(set(s for s in symbols if provider.is_international(s)))[:50]:
        try:
            latest = None
            if symbol.endswith(".US"):
                from app.data_providers.international import paid_quote

                latest = paid_quote(symbol)
                if latest:
                    with _LOCK:
                        _QUOTES[symbol] = (time.monotonic(), latest)
            if not latest:
                snapshot(symbol, force=force)
        except Exception:  # noqa: BLE001 -- isolate providers and never expose credential-bearing errors
            warnings.append(f"{symbol}未取得新数据，保留上次数据；请检查来源状态，公开补充接口也可能暂时不可用。")
    return dict(
        rows=cached_rows(symbols),
        attempts=[],
        warnings=warnings,
        fetched_at=None,
        status="historical",
    )
