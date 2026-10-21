"""Fund research data contract (dates: Beijing; percentages: percentage points)."""

from typing import Literal

from pydantic import BaseModel, Field

NavRange = Literal["week", "month", "tmonth", "hyear", "year", "twoyear", "tyear", "fyear"]
NAV_RANGES = frozenset({"week", "month", "tmonth", "hyear", "year", "twoyear", "tyear", "fyear"})


class FundStatus(BaseModel):
    provider: str = "fuyao"
    configured: bool
    permission_status: Literal["unverified"] = "unverified"
    capabilities: list[str] = Field(default_factory=lambda: ["profile", "nav", "holdings"])
    message: str


class FundSnapshot(BaseModel):
    ticker: str
    provider: str
    # Source snapshot/assembly time, NOT the NAV date or disclosure date.
    timestamp_ms: int | None = None


class FundProfile(BaseModel):
    fund_name: str | None = None
    mgmt_name: str | None = None
    manager_name: str | None = None
    established_date: str | None = None
    unit_nav: float | None = None


class FundProfileResponse(FundSnapshot):
    profile: FundProfile | None = None


class FundNavPoint(BaseModel):
    date: str
    unit_nav: float | None = None
    # Adjusted NAV is distinct from cumulative NAV; never substitute one for the other.
    adj_nav: float | None = None


class FundNavResponse(FundSnapshot):
    range: NavRange
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
