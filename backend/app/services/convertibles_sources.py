"""Source-independent quote refresh for the convertible research extension.

The existing stock Provider contract deliberately excludes bonds. This small
boundary supplies only raw CNY prices, percentage points and quote timestamps;
conversion terms and disclosures remain independently maintained research data.

TickFlow contract checked against the installed SDK and official documentation:
https://docs.tickflow.org/zh-hans/api-reference/实时行情/查询实时行情
https://docs.tickflow.org/zh-Hans/faq
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.services.convertibles_research import (
    ConvertibleConflictError,
    ConvertibleService,
    ConvertibleSnapshot,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SYMBOL = re.compile(r"^(\d{6})(?:\.(SH|SZ|BJ))?$")
_MAX_SYMBOLS = 4000  # At most 2,000 bonds and their explicitly supplied stocks.
KEY_SETUP_HINT = "请在设置 → 数据源中配置具有所需实时行情权限的 TickFlow API Key。"


class ConvertibleDataError(Exception):
    """Only safe, fixed messages cross the API boundary."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ConvertibleQuote:
    symbol: str
    price: float | None
    change_pct: float | None
    turnover_amount: float | None
    turnover_rate_pct: float | None
    quote_at: str


@dataclass(frozen=True)
class ConvertibleQuoteBatch:
    quotes: dict[str, ConvertibleQuote]
    fetched_at: str


class ConvertibleQuoteProvider(Protocol):
    """Percentages are percentage points (20 = 20%); amount and prices are CNY.

    Only explicitly requested symbols may be returned. A missing symbol or field
    is unknown, never a zero/face-price fallback. Timestamps are ISO 8601 with a
    timezone. ``configured`` checks configuration, not network availability or
    entitlement. Providers raise ConvertibleDataError on contract/source errors.
    """

    name: str

    def configured(self) -> bool: ...

    def quotes(self, symbols: list[str]) -> ConvertibleQuoteBatch: ...


class ConvertibleSourceCapabilities(BaseModel):
    # These indicate implemented data capabilities, not tested account rights.
    quotes: bool = True
    terms: Literal[False] = False
    announcements: Literal[False] = False


class ConvertibleSourceStatus(BaseModel):
    provider: str
    configured: bool
    mode: Literal["realtime", "unconfigured"]
    message: str
    capabilities: ConvertibleSourceCapabilities
    last_refresh_at: str | None


def get_api_key() -> str:
    from app import secrets_store

    return secrets_store.get_tickflow_key()


def _new_client(api_key: str):
    # Reuse the application's key/endpoint settings. A dedicated short-lived SDK
    # client keeps this interactive request bounded and does not mutate the
    # shared stock client or accidentally switch to the historical free server.
    from tickflow import TickFlow

    from app import secrets_store

    endpoint = secrets_store.load().get("tickflow_base_url") or None
    return TickFlow(api_key=api_key, base_url=endpoint, timeout=20.0, max_retries=0)


def normalize_symbol(code: str, *, kind: Literal["bond", "stock"]) -> str:
    """Normalize the market for an already explicitly identified asset role.

    This validates supported code families; it does not claim the security is
    listed, that the source covers it, or infer a bond's underlying stock.
    """
    match = _SYMBOL.fullmatch(code.strip().upper())
    if not match:
        raise ConvertibleDataError(422, "行情代码须为六位数字及市场后缀，例如 110001.SH")
    digits, supplied_exchange = match.groups()
    exchange = None
    if kind == "bond":
        if digits.startswith(("110", "111", "113", "118", "132")):
            exchange = "SH"
        elif digits.startswith(("117", "123", "127", "128")):
            exchange = "SZ"
    elif digits.startswith(("600", "601", "603", "605", "688", "689")):
        exchange = "SH"
    elif digits.startswith(("000", "001", "002", "003", "300", "301")):
        exchange = "SZ"
    elif digits.startswith(("43", "83", "87", "92")):
        exchange = "BJ"
    if exchange is None or (supplied_exchange and supplied_exchange != exchange):
        role = "转债" if kind == "bond" else "正股"
        raise ConvertibleDataError(422, f"{role}代码或市场后缀不在当前支持范围，请核对导入清单")
    return f"{digits}.{exchange}"


def _malformed() -> ConvertibleDataError:
    return ConvertibleDataError(502, "行情数据源返回的数据格式或单位异常，本次未更新清单")


def _number(value: object, *, nonnegative: bool = False) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _malformed()
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _malformed() from None
    if not math.isfinite(result) or abs(result) > 1e18 or (nonnegative and result < 0):
        raise _malformed()
    return result


def _timestamp(value: object, fetched_at: datetime) -> str:
    number = _number(value, nonnegative=True)
    if number is None or not number.is_integer():
        raise _malformed()
    try:
        timestamp = datetime.fromtimestamp(number / 1000, tz=_SHANGHAI)
    except (OverflowError, OSError, ValueError):
        raise _malformed() from None
    # Reject seconds passed as milliseconds and materially future timestamps.
    if timestamp.year < 1990 or timestamp > fetched_at + timedelta(minutes=10):
        raise _malformed()
    return timestamp.isoformat(timespec="seconds")


def _safe_error(exc: Exception) -> ConvertibleDataError:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return ConvertibleDataError(403, "TickFlow API Key 无效或已失效，请更新数据源设置")
    if status == 403:
        return ConvertibleDataError(403, "当前 TickFlow API Key 无权访问所请求的实时行情")
    if status == 429:
        return ConvertibleDataError(429, "行情接口请求过于频繁，请稍后再试")
    if status in {400, 422}:
        return ConvertibleDataError(422, "行情接口不接受本次代码或批量参数，请检查清单及账号限制")
    if status == 404:
        return ConvertibleDataError(404, "行情数据源未找到所请求的标的，请核对代码和市场")
    return ConvertibleDataError(502, "行情数据源暂时不可用或请求超时，请稍后再试；原清单已保留")


class TickFlowConvertibleProvider:
    name = "tickflow"

    def __init__(
        self,
        *,
        api_key_getter: Callable[[], str] | None = None,
        client_factory: Callable | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key_getter = api_key_getter or get_api_key
        self._client_factory = client_factory or _new_client
        self._clock = clock or (lambda: datetime.now(_SHANGHAI))

    def configured(self) -> bool:
        return bool(self._api_key_getter())

    def quotes(self, symbols: list[str]) -> ConvertibleQuoteBatch:
        api_key = self._api_key_getter()
        if not api_key:
            raise ConvertibleDataError(503, f"尚未配置实时行情数据源。{KEY_SETUP_HINT}")
        requested = sorted(set(symbols))
        if not requested or len(requested) > _MAX_SYMBOLS:
            raise ConvertibleDataError(422, "行情请求须包含 1 至 4000 个明确标的")
        client = None
        try:
            client = self._client_factory(api_key)
            raw = client.quotes.get(symbols=requested)
        except Exception as exc:  # noqa: BLE001 -- supplier messages can contain credentials
            raise _safe_error(exc) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception as exc:  # noqa: BLE001 -- keep supplier cleanup errors private
                    raise _safe_error(exc) from None
        fetched_at = self._clock().astimezone(_SHANGHAI)
        if not isinstance(raw, list) or len(raw) > len(requested):
            raise _malformed()
        requested_set = set(requested)
        normalized: dict[str, ConvertibleQuote] = {}
        for row in raw:
            if not isinstance(row, dict):
                raise _malformed()
            symbol = row.get("symbol")
            if (
                not isinstance(symbol, str) or symbol not in requested_set
                or symbol in normalized or row.get("region", "CN") != "CN"
            ):
                raise _malformed()
            ext = row.get("ext")
            if ext is None:
                ext = {}
            if not isinstance(ext, dict):
                raise _malformed()
            price = _number(row.get("last_price"), nonnegative=True)
            if price == 0:
                price = None
            if price is not None and not 0.00000001 <= price <= 1_000_000_000:
                raise _malformed()
            prev_close = _number(row.get("prev_close"), nonnegative=True)
            change = _number(ext.get("change_pct"))
            if price is None:
                change = None
            elif change is None and prev_close:
                change = price / prev_close - 1
            turnover = _number(ext.get("turnover_rate"), nonnegative=True)
            if (
                (change is not None and abs(change * 100) > 1e12)
                or (turnover is not None and turnover * 100 > 1e18)
            ):
                raise _malformed()
            normalized[symbol] = ConvertibleQuote(
                symbol=symbol,
                price=price,
                change_pct=round(change * 100, 10) if change is not None else None,
                turnover_amount=_number(row.get("amount"), nonnegative=True),
                turnover_rate_pct=round(turnover * 100, 10) if turnover is not None else None,
                quote_at=_timestamp(row.get("timestamp"), fetched_at),
            )
        return ConvertibleQuoteBatch(
            quotes=normalized, fetched_at=fetched_at.isoformat(timespec="seconds"),
        )


class ConvertibleQuoteService:
    """Fetch outside the snapshot lock, then compare-and-swap a complete update."""

    def __init__(self, provider: ConvertibleQuoteProvider) -> None:
        self.provider = provider

    def status(self, snapshot: ConvertibleSnapshot) -> ConvertibleSourceStatus:
        configured = self.provider.configured()
        refreshes = [
            item.fetched_at for item in snapshot.items
            if item.fetched_at and item.quote_source == self.provider.name
        ]
        return ConvertibleSourceStatus(
            provider=self.provider.name,
            configured=configured,
            mode="realtime" if configured else "unconfigured",
            message=(
                "已配置行情 Key；连接和标的权限将在刷新时验证。条款与公告仍需独立提供。"
                if configured else f"尚未配置实时行情数据源。{KEY_SETUP_HINT}"
            ),
            capabilities=ConvertibleSourceCapabilities(),
            last_refresh_at=max(refreshes, key=datetime.fromisoformat) if refreshes else None,
        )

    def refresh(
        self, store: ConvertibleService, *, expected_revision: str,
    ) -> ConvertibleSnapshot:
        current = store.snapshot()
        if current.revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请刷新清单后再请求行情")
        if not current.items:
            raise ConvertibleDataError(422, "请先导入研究清单，再刷新其中转债及正股的行情")
        mapped = {
            item.code: (
                normalize_symbol(item.code, kind="bond"),
                normalize_symbol(item.stock_code, kind="stock") if item.stock_code else None,
            )
            for item in current.items
        }
        symbols = sorted({symbol for pair in mapped.values() for symbol in pair if symbol})
        batch = self.provider.quotes(symbols)
        # No successful bond price is not a new snapshot. Partial success below
        # explicitly clears absent quote fields, rather than mixing old/new data.
        if not any(
            (quote := batch.quotes.get(pair[0])) is not None and quote.price is not None
            for pair in mapped.values()
        ):
            raise ConvertibleDataError(404, "行情数据源未返回可用转债价格，原清单已保留")
        updates: dict[str, dict] = {}
        quote_dates: list[str] = []
        for item in current.items:
            bond_symbol, stock_symbol = mapped[item.code]
            bond = batch.quotes.get(bond_symbol)
            stock = batch.quotes.get(stock_symbol) if stock_symbol else None
            for quote, previous_time in ((bond, item.quote_at), (stock, item.stock_quote_at)):
                if quote:
                    if (
                        previous_time
                        and datetime.fromisoformat(quote.quote_at)
                        < datetime.fromisoformat(previous_time)
                    ):
                        raise ConvertibleDataError(502, "数据源返回较旧行情，已停止更新并保留原清单")
                    quote_dates.append(
                        datetime.fromisoformat(quote.quote_at).astimezone(_SHANGHAI).date().isoformat()
                    )
            updates[item.code] = {
                "bond_price": bond.price if bond else None,
                "bond_change_pct": bond.change_pct if bond else None,
                "turnover_amount": bond.turnover_amount if bond else None,
                "turnover_rate_pct": bond.turnover_rate_pct if bond else None,
                "quote_at": bond.quote_at if bond else None,
                "stock_price": stock.price if stock else None,
                "stock_change_pct": stock.change_pct if stock else None,
                "stock_quote_at": stock.quote_at if stock else None,
                "fetched_at": batch.fetched_at,
                "quote_source": self.provider.name,
            }
        label = "TickFlow" if self.provider.name == "tickflow" else self.provider.name
        try:
            return store.merge_quotes(
                updates, expected_revision=expected_revision, as_of=max(quote_dates),
                source=f"用户导入 + {label} 行情",
            )
        except ConvertibleConflictError:
            raise
        except ValueError:
            raise ConvertibleDataError(
                502, "新行情未通过日期或字段校验，原清单已保留；请核对清单日期与数据源返回时点",
            ) from None
