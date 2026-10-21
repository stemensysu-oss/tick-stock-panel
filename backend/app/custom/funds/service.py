"""Source-independent fund research boundary; does not mix fund and stock datasets."""

from __future__ import annotations

import re
from typing import Protocol

from app.custom.funds.models import (
    NAV_RANGES,
    FundHoldingsResponse,
    FundNavResponse,
    FundProfileResponse,
    NavRange,
)


class FundDataError(Exception):
    """Safe user-facing failure; raw provider messages must never reach the API."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class FundDataProvider(Protocol):
    """Canonical datasets; missing data is null/empty, unavailable capabilities raise.

    Dates are YYYY-MM-DD in Asia/Shanghai. Percent values are percentage points,
    so 0.12 is 0.12%. A snapshot timestamp must not replace a disclosure/NAV date.
    """

    def profile(self, ticker: str) -> FundProfileResponse: ...

    def nav(self, ticker: str, nav_range: NavRange) -> FundNavResponse: ...

    def holdings(self, ticker: str) -> FundHoldingsResponse: ...


def _validate_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[0-9]{6}\.(OF|SH|SZ)", normalized):
        raise FundDataError(422, "请使用完整基金代码及市场后缀，例如 025480.OF、510300.SH、161725.SZ")
    return normalized


class FundResearchService:
    def __init__(self, provider: FundDataProvider) -> None:
        self._provider = provider

    def profile(self, ticker: str) -> FundProfileResponse:
        return self._provider.profile(_validate_ticker(ticker))

    def nav(self, ticker: str, nav_range: NavRange) -> FundNavResponse:
        ticker = _validate_ticker(ticker)
        if nav_range not in NAV_RANGES:
            raise FundDataError(422, "净值区间不受支持，请选择一周至五年的预设区间")
        return self._provider.nav(ticker, nav_range)

    def holdings(self, ticker: str) -> FundHoldingsResponse:
        return self._provider.holdings(_validate_ticker(ticker))
