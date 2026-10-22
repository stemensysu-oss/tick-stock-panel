"""Fund research data contract (dates: Beijing; percentages: percentage points)."""

from typing import Literal

from pydantic import BaseModel, Field

NavRange = Literal["week", "month", "tmonth", "hyear", "year", "twoyear", "tyear", "fyear"]
NAV_RANGES = frozenset({"week", "month", "tmonth", "hyear", "year", "twoyear", "tyear", "fyear"})


class FundStatus(BaseModel):
    provider: str = "fuyao"
    configured: bool
    primary_configured: bool = False
    permission_status: Literal["unverified"] = "unverified"
    capabilities: list[str] = Field(default_factory=lambda: ["profile", "nav", "holdings"])
    message: str


class FundSnapshot(BaseModel):
    ticker: str
    provider: str
    # Source snapshot/assembly time, NOT the NAV date or disclosure date.
    timestamp_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)
    attempts: list[dict] = Field(default_factory=list)


class FundProfile(BaseModel):
    fund_name: str | None = None
    mgmt_name: str | None = None
    manager_name: str | None = None
    established_date: str | None = None
    unit_nav: float | None = None
    fund_type: str | None = None
    series_kind: Literal['nav', 'money', 'unknown'] = 'unknown'


class FundProfileResponse(FundSnapshot):
    profile: FundProfile | None = None


class FundNavPoint(BaseModel):
    date: str
    unit_nav: float | None = None
    # Adjusted NAV is distinct from cumulative NAV; never substitute one for the other.
    adj_nav: float | None = None
    cumulative_nav: float | None = None
    income_per_10000: float | None = None  # CNY per 10,000 units per day
    seven_day_yield_pct: float | None = None  # published annualised percentage points


class FundNavResponse(FundSnapshot):
    range: NavRange
    series_kind: Literal['nav', 'money', 'unknown'] = 'nav'
    items: list[FundNavPoint] = Field(default_factory=list)


class FundHolding(BaseModel):
    ticker: str
    name: str | None = None
    asset_type: str
    weight_pct: float | None = None
    report_date: str | None = None
    publish_date: str | None = None


class FundHoldingsResponse(FundSnapshot):
    items: list[FundHolding] = Field(default_factory=list)
    stock_ratio_pct: float | None = None
    bond_ratio_pct: float | None = None
    fund_ratio_pct: float | None = None
    scope: str = 'source_disclosed'
    report_date: str | None = None


class FundDividend(BaseModel):
    per_ten_cash_before_tax: float | None = None
    registration_date: str | None = None
    ex_dividend_date: str | None = None
    payment_date: str | None = None
    publish_date: str | None = None
    progress: str | None = None


class FundDividendsResponse(FundSnapshot):
    items: list[FundDividend] = Field(default_factory=list)


class FundLimit(BaseModel):
    status: Literal['finite', 'unlimited', 'unknown'] = 'unknown'
    value: float | None = None
    unit: Literal['CNY', 'units']
    source_text: str | None = None


class FundTradingResponse(FundSnapshot):
    subscription_status: str | None = None
    redemption_status: str | None = None
    minimum_purchase: FundLimit = Field(default_factory=lambda: FundLimit(unit='CNY'))
    daily_purchase_limit: FundLimit = Field(default_factory=lambda: FundLimit(unit='CNY'))
    minimum_redemption: FundLimit = Field(default_factory=lambda: FundLimit(unit='units'))
    minimum_remaining: FundLimit = Field(default_factory=lambda: FundLimit(unit='units'))
    source_url: str
    effective_date: str | None = None
