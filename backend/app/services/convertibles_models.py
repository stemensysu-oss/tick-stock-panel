"""Canonical convertible research inputs.

Prices and amounts are CNY, per-bond cash flows use a face value of 100 CNY.
Percent fields use percentage points: 20 means 20%, never the ratio 0.20.
These models describe user-supplied terms, not verified issuer disclosures.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.convertibles_calculation_config import ConvertibleCalculationSettings

MAX_ROWS = 2000
_CODE = re.compile(r"^[0-9]{6}(?:\.(?:SH|SZ|BJ))?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

PositivePrice = Annotated[
    float, Field(ge=0.00000001, le=1_000_000_000, allow_inf_nan=False, strict=True)
]
FiniteNumber = Annotated[
    float, Field(ge=-1e12, le=1e12, allow_inf_nan=False, strict=True)
]
NonnegativeAmount = Annotated[
    float, Field(ge=0, le=1e18, allow_inf_nan=False, strict=True)
]


def validate_date(value: str) -> str:
    if not _DATE.fullmatch(value):
        raise ValueError("日期须使用 YYYY-MM-DD 格式")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期不存在") from exc
    return value


def validate_text(value: str | None) -> str | None:
    if value is not None and any(ord(char) < 32 for char in value):
        raise ValueError("文字字段不能包含控制字符或换行")
    return value


def validate_url(value: str | None) -> str | None:
    if value is None:
        return None
    validate_text(value)
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("来源链接须为有效的 http 或 https 地址") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("来源链接须为不含登录凭据的 http 或 https 地址")
    return value


def validate_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("时间须为含时区的 ISO 格式，例如 2026-10-21T15:00:00+08:00") from exc
    if parsed.utcoffset() is None:
        raise ValueError("时间必须明确时区")
    try:
        parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    except (ValueError, OverflowError) as exc:
        raise ValueError("时间转换到北京时间后超出支持范围") from exc
    return parsed.isoformat(timespec="seconds")


class DatedCashFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    date: str
    amount: PositivePrice

    _date = field_validator("date")(validate_date)


class ConvertibleEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    date: str
    type: Literal["call", "put", "revision", "coupon", "maturity", "announcement"]
    title: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)

    _date = field_validator("date")(validate_date)
    _text = field_validator("title")(validate_text)
    _url = field_validator("source_url")(validate_url)

    @field_validator("note")
    @classmethod
    def multiline_note(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("公告说明不能包含换行、回车和制表符以外的控制字符")
        return value


class ConvertibleClause(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    window_days: int = Field(ge=1, le=260, strict=True)
    required_days: int = Field(ge=1, le=260, strict=True)
    trigger_ratio_pct: PositivePrice
    consecutive: bool = False
    start_date: str | None = None
    end_date: str | None = None
    paused_until: str | None = None
    observations_complete: bool = False

    @field_validator("start_date", "end_date", "paused_until")
    @classmethod
    def dates(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None

    @model_validator(mode="after")
    def coherent_window(self) -> ConvertibleClause:
        if self.required_days > self.window_days:
            raise ValueError("触发所需天数不能大于观察窗口")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("条款生效日期不能晚于结束日期")
        return self


class ConvertibleObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    date: str
    stock_close: PositivePrice
    conversion_price: PositivePrice

    _date = field_validator("date")(validate_date)


class ConvertibleResearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    calculation_settings: ConvertibleCalculationSettings | None = None
    personal_rating: str | None = Field(default=None, max_length=30)
    parameter_note: str | None = Field(default=None, max_length=500)
    fund_holding_report_date: str | None = None

    _personal_text = field_validator('personal_rating')(validate_text)
    @field_validator('parameter_note')
    @classmethod
    def parameter_text(cls, value):
        if value is not None and any(ord(char) < 32 and char not in '\n\r\t' for char in value):
            raise ValueError('参数说明含有非法控制字符')
        return value

    _personal_holding_date = field_validator('fund_holding_report_date')(
        lambda value: validate_date(value) if value is not None else None)
    cash_flows: list[DatedCashFlow] = Field(default_factory=list, max_length=30)
    put_cash_flows: list[DatedCashFlow] = Field(default_factory=list, max_length=30)
    cash_flows_complete: bool = False
    put_cash_flows_complete: bool = False
    price_basis: Literal["full", "clean"] | None = None
    accrued_interest: NonnegativeAmount | None = None
    discount_rate_pct: Annotated[
        float, Field(gt=-100, le=10000, allow_inf_nan=False, strict=True)
    ] | None = None
    risk_free_rate_pct: FiniteNumber | None = None
    dividend_yield_pct: FiniteNumber | None = None
    events: list[ConvertibleEvent] = Field(default_factory=list, max_length=100)
    call_clause: ConvertibleClause | None = None
    put_clause: ConvertibleClause | None = None
    observations: list[ConvertibleObservation] = Field(default_factory=list, max_length=260)
    observations_as_of: str | None = None

    @field_validator("observations_as_of")
    @classmethod
    def observations_date(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None

    @model_validator(mode="after")
    def unique_dates(self) -> ConvertibleResearch:
        for field in ("cash_flows", "put_cash_flows", "observations"):
            values = getattr(self, field)
            if len({value.date for value in values}) != len(values):
                raise ValueError(f"{field} 中日期重复；现金流请先合并同日应收款")
        return self


class ClauseProgress(BaseModel):
    state: Literal["unknown", "observing", "met", "not_applicable"] = "unknown"
    hit_days: int | None = None
    observed_days: int = 0
    window_days: int | None = None
    required_days: int | None = None
    as_of: str | None = None
    note: str = "尚未提供条款与连续交易日观察数据"


class ConvertibleInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str = Field(min_length=1, max_length=100)
    stock_code: str | None = None
    stock_name: str | None = Field(default=None, max_length=100)
    bond_price: PositivePrice | None = None
    stock_price: PositivePrice | None = None
    conversion_price: PositivePrice | None = None
    face_value: Literal[100] = 100
    maturity_date: str | None = None
    redemption_status: str | None = Field(default=None, max_length=200)
    bond_change_pct: FiniteNumber | None = None
    stock_change_pct: FiniteNumber | None = None
    stock_pb: FiniteNumber | None = None
    credit_rating: str | None = Field(default=None, max_length=30)
    industry: str | None = Field(default=None, max_length=100)
    concepts: str | None = Field(default=None, max_length=500)
    asset_type: Literal["convertible", "exchangeable"] = "convertible"
    listing_date: str | None = None
    outstanding_amount: NonnegativeAmount | None = None
    turnover_amount: NonnegativeAmount | None = None
    turnover_rate_pct: NonnegativeAmount | None = None
    float_market_cap: NonnegativeAmount | None = None
    fund_holding_pct: Annotated[
        float, Field(ge=0, le=100, allow_inf_nan=False, strict=True)
    ] | None = None
    fund_holding_report_date: str | None = None
    fund_holding_publish_date: str | None = None
    call_trigger_ratio_pct: PositivePrice | None = None
    put_trigger_ratio_pct: PositivePrice | None = None
    conversion_start_date: str | None = None
    conversion_price_effective_date: str | None = None
    stock_volatility_pct: NonnegativeAmount | None = None
    volatility_window_days: int | None = Field(default=None, ge=2, le=10000, strict=True)
    volatility_adjustment: Literal["none", "forward", "backward"] | None = None
    quote_at: str | None = None
    stock_quote_at: str | None = None
    fetched_at: str | None = None
    quote_source: str | None = Field(default=None, max_length=100)
    terms_source: str | None = Field(default=None, max_length=100)
    source_url: str | None = Field(default=None, max_length=2000)
    research: ConvertibleResearch | None = None

    @field_validator("face_value", mode="before")
    @classmethod
    def supported_face_value(cls, value: object) -> object:
        if value != 100 or isinstance(value, bool):
            raise ValueError("仅支持每张面值 100 元的人民币可转债，请勿混入其他面值")
        return value

    @field_validator("code", "stock_code")
    @classmethod
    def valid_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip().upper()
        if not _CODE.fullmatch(code):
            raise ValueError("代码须为六位数字，可带 .SH/.SZ/.BJ；请保留前导零")
        return code

    @field_validator(
        "maturity_date", "listing_date", "fund_holding_report_date", "fund_holding_publish_date",
        "conversion_start_date", "conversion_price_effective_date",
    )
    @classmethod
    def valid_dates(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None

    _text = field_validator(
        "name", "stock_name", "redemption_status", "credit_rating", "industry", "concepts",
        "quote_source", "terms_source",
    )(validate_text)
    _timestamps = field_validator("quote_at", "stock_quote_at", "fetched_at")(validate_timestamp)
    _url = field_validator("source_url")(validate_url)


class ConvertibleItem(ConvertibleInput):
    calculation_details: dict = Field(default_factory=dict)
    calculation_basis: str | None = None
    personal_rating: str | None = None
    conversion_value: float | None = None
    conversion_premium_pct: float | None = None
    double_low: float | None = None
    remaining_years: float | None = None
    call_trigger_price: float | None = None
    put_trigger_price: float | None = None
    debt_to_float_cap_pct: float | None = None
    pure_bond_value: float | None = None
    option_value: float | None = None
    ytm_pct: float | None = None
    put_yield_pct: float | None = None
    call_progress: ClauseProgress = Field(default_factory=ClauseProgress)
    put_progress: ClauseProgress = Field(default_factory=ClauseProgress)
    analysis_warnings: list[str] = Field(default_factory=list)


class ImportIssue(BaseModel):
    row: int
    field: str | None = None
    message: str


class ImportPreview(BaseModel):
    valid: bool
    total_rows: int
    items: list[ConvertibleItem]
    errors: list[ImportIssue]
    warnings: list[str]
    as_of: str
    base_revision: str = "0"


class ConvertibleSnapshot(BaseModel):
    # Additive fields retain schema 1; higher versions are intentionally rejected.
    schema_version: Literal[1] = 1
    revision: str = "0"
    as_of: str | None = None
    updated_at: str | None = None
    source: str = Field(default="用户导入", min_length=1, max_length=100)
    items: list[ConvertibleItem] = Field(default_factory=list, max_length=MAX_ROWS)
    calculation_settings: ConvertibleCalculationSettings = Field(default_factory=ConvertibleCalculationSettings)

    @field_validator("schema_version", mode="before")
    @classmethod
    def supported_schema(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("仅支持研究备份 schema_version=1")
        return value

    @field_validator("as_of")
    @classmethod
    def valid_as_of(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None

    _source = field_validator("source")(validate_text)
