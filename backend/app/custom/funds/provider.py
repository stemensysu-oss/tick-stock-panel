"""Fuyao fund adapter, reusing the existing authenticated HTTP client.

Official contracts checked 2026-10-21:
https://fuyao.aicubes.cn/docs/api-reference/fund-profile/
https://fuyao.aicubes.cn/docs/api-reference/fund-performance/
https://fuyao.aicubes.cn/docs/api-reference/fund-holdings/

No fund dataset is routed through the A-share price/provider contract. Adding a
different source only requires the canonical FundDataProvider interface.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.custom.funds.models import (
    FundDividend,
    FundDividendsResponse,
    FundHolding,
    FundHoldingsResponse,
    FundNavPoint,
    FundNavResponse,
    FundProfile,
    FundProfileResponse,
    NavRange,
)
from app.custom.funds.service import FundDataError
from app.plugins.fuyao.client import FuyaoClient, FuyaoError

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_ROWS = 5000
FUND_KEY_SETUP_HINT = (
    "可在设置 → 数据源中配置同时具备 A 股和所需基金接口权限的扶摇 API Key；"
    "基金专用 Key 可通过 FUYAO_API_KEY 环境变量配置并重启后端。"
    "已在设置中保存的 Key 优先于环境变量。"
)


def get_api_key() -> str:
    # Lazy import keeps extension discovery free of configuration/probing side effects.
    from app.plugins.fuyao.provider import get_api_key as existing_get_api_key

    return existing_get_api_key()


def _malformed() -> FundDataError:
    return FundDataError(502, "基金数据源返回的数据格式异常，本次结果未采用")


def _number(value: object, *, nonnegative: bool = False) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _malformed()
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _malformed() from None
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise _malformed()
    return result


def _text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _malformed()
    return value


def _timestamp(value: object) -> int | None:
    number = _number(value)
    if number is None or number == 0:
        return None
    if number < 0 or not number.is_integer():
        raise _malformed()
    try:
        dt = datetime.fromtimestamp(number / 1000, tz=_SHANGHAI)
    except (ValueError, OverflowError, OSError):
        raise _malformed() from None
    # The documented contract is milliseconds; reject seconds and corrupt dates.
    if not 1990 <= dt.year <= 2100:
        raise _malformed()
    return int(number)


def _date(value: object) -> str | None:
    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=_SHANGHAI).date().isoformat()


def _rows(data: dict) -> list[dict]:
    rows = data.get("item")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise _malformed()
    if any(not isinstance(row, dict) for row in rows):
        raise _malformed()
    return rows


class FuyaoFundClient(FuyaoClient):
    def fund_request(self, path: str, params: dict) -> dict:
        return self._get(path, params)


class FuyaoFundProvider:
    def trading(self, ticker):
        # Profile trade_rule has no documented generic limit schema. QDII quota
        # is a different capability and must not be guessed into trading limits.
        raise NotImplementedError

    def dividends(self, ticker):
        data = self._request('/api/fund/corporate-actions/dividends', {'thscode': ticker})
        items = [FundDividend(
            per_ten_cash_before_tax=_number(row.get('per_ten_cash_before_tax'), nonnegative=True),
            registration_date=_date(row.get('registration_date_ms')),
            ex_dividend_date=_date(row.get('ex_dividend_date_ms')),
            payment_date=_date(row.get('payment_date_ms')),
            publish_date=_date(row.get('publish_date_ms')), progress=_text(row.get('progress')),
        ) for row in _rows(data)]
        return FundDividendsResponse(ticker=ticker, provider='fuyao',
            timestamp_ms=_timestamp(data.get('timestamp')), items=items,
            warnings=['现金分红单位为每10份；未据此拼接复权收益。'])

    def holdings_history(self, ticker, asset_type, report_date=None):
        if asset_type == 'stock' and not report_date:
            return self.holdings(ticker)
        if not report_date:
            data = self._request(f'/api/fund/portfolio/{asset_type}-report-dates',
                {'thscode': ticker, 'report_type': 'quarter'})
            dates = [value for row in _rows(data) if (value := _date(row.get('end_date_ms')))]
            if not dates:
                return FundHoldingsResponse(ticker=ticker, provider='fuyao')
            report_date = max(dates)
        data = self._request(f'/api/fund/portfolio/{asset_type}-history',
            {'thscode': ticker, 'report_type': 'quarter', 'end_date': report_date})
        items = []
        for row in _rows(data):
            code, period = _text(row.get('thscode')), _date(row.get('end_date_ms'))
            if not code or period != report_date or row.get('asset_type') != asset_type:
                raise _malformed()
            items.append(FundHolding(ticker=code, name=_text(row.get('name')), asset_type=asset_type,
                weight_pct=_number(row.get('hold_ratio')), report_date=period,
                publish_date=_date(row.get('publish_date_ms'))))
        return FundHoldingsResponse(ticker=ticker, provider='fuyao',
            timestamp_ms=_timestamp(data.get('timestamp')), items=items, report_date=report_date,
            warnings=['定期披露持仓，不是实时持仓；报告截止日不是公告日，源未提供公告日时保持未知。'])

    def __init__(
        self,
        api_key: str,
        *,
        client_factory: Callable[[str], FuyaoFundClient] = FuyaoFundClient,
    ) -> None:
        self._api_key = api_key
        self._client_factory = client_factory

    def _request(self, path: str, params: dict) -> dict:
        if not self._api_key:
            raise FundDataError(503, f"尚未配置扶摇 API Key。{FUND_KEY_SETUP_HINT}")
        client = self._client_factory(self._api_key)
        try:
            data = client.fund_request(path, params)
        except FuyaoError as exc:
            # Existing client exposes a textual error. Inspect only its fixed prefix,
            # never copy the supplier's message or authorization data into responses.
            code_match = re.match(r"扶摇接口错误 code=(\d+):", str(exc))
            http_match = re.match(r"HTTP (\d+):", str(exc))
            code = int(code_match[1]) if code_match else None
            status = int(http_match[1]) if http_match else None
            if code == 3002:
                return {"item": []}
            if code in {2001, 2002} or status == 401:
                raise FundDataError(
                    403, "扶摇 API Key 无效或已失效，请更新已保存的 Key，或更新环境变量后重启后端"
                ) from None
            if code == 2003 or status == 403:
                raise FundDataError(403, "当前扶摇 API Key 没有此基金接口的访问权限") from None
            if code == 3001:
                raise FundDataError(404, "数据源未找到该基金，请核对代码及市场后缀") from None
            if code == 3004:
                raise FundDataError(422, "该基金类型暂不支持此项查询") from None
            if code in {1001, 1002, 1003}:
                raise FundDataError(422, "数据源不接受该查询参数，请核对基金代码和区间") from None
            if code == 4001 or status == 429:
                raise FundDataError(429, "基金接口请求过于频繁，请稍后重试") from None
            raise FundDataError(502, "基金数据源暂时无法访问，请稍后重试") from None
        except (AttributeError, TypeError, ValueError):
            raise _malformed() from None
        finally:
            client.close()
        if not isinstance(data, dict):
            raise _malformed()
        return data

    def profile(self, ticker: str) -> FundProfileResponse:
        data = self._request("/api/fund/profile/detail", {"thscode": ticker})
        rows = _rows(data)
        profile = None
        if rows:
            if len(rows) != 1 or rows[0].get("thscode") != ticker:
                raise _malformed()
            row = rows[0]
            profile = FundProfile(
                fund_name=_text(row.get("fund_name")),
                mgmt_name=_text(row.get("mgmt_name")),
                manager_name=_text(row.get("manager_name")),
                established_date=_date(row.get("estab_date")),
                unit_nav=_number(row.get("unit_nav"), nonnegative=True),
            )
        return FundProfileResponse(
            ticker=ticker, provider="fuyao", timestamp_ms=_timestamp(data.get("timestamp")),
            profile=profile,
        )

    def nav(self, ticker: str, nav_range: NavRange) -> FundNavResponse:
        data = self._request(
            "/api/fund/performance/nav",
            {"thscode": ticker, "range": nav_range, "nav_type": "unit,adj"},
        )
        items = []
        dates: set[str] = set()
        for row in _rows(data):
            day = _date(row.get("nav_date"))
            if day is None or day in dates:
                raise _malformed()
            dates.add(day)
            items.append(FundNavPoint(
                date=day,
                unit_nav=_number(row.get("unit_nav"), nonnegative=True),
                adj_nav=_number(row.get("adj_nav"), nonnegative=True),
            ))
        return FundNavResponse(
            ticker=ticker, provider="fuyao", timestamp_ms=_timestamp(data.get("timestamp")),
            range=nav_range, items=sorted(items, key=lambda point: point.date),
        )

    def holdings(self, ticker: str) -> FundHoldingsResponse:
        data = self._request("/api/fund/portfolio/holdings", {"thscode": ticker})
        items = []
        for row in _rows(data):
            holding_ticker = _text(row.get("thscode"))
            if not holding_ticker:
                raise _malformed()
            items.append(FundHolding(
                ticker=holding_ticker,
                name=_text(row.get("stock_name")),
                asset_type=_text(row.get("asset_type")) or "unknown",
                weight_pct=_number(row.get("hold_ratio")),
                report_date=_date(row.get("end_date_ms")),
                publish_date=_date(row.get("publish_date_ms")),
            ))
        return FundHoldingsResponse(
            ticker=ticker, provider="fuyao", timestamp_ms=_timestamp(data.get("timestamp")),
            items=items,
            stock_ratio_pct=_number(data.get("total_stock_ratio_pct")),
            bond_ratio_pct=_number(data.get("total_bond_ratio_pct")),
            fund_ratio_pct=_number(data.get("total_fund_ratio_pct")),
        )
