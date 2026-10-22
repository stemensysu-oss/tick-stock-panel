"""Strict import contract; provenance is assigned by the service, never by CSV."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ROWS = 2000
Currency = Literal['CNY', 'HKD', 'USD', 'EUR', 'JPY', 'GBP']
Price = Annotated[float, Field(ge=1e-8, le=1e9, allow_inf_nan=False)]
Amount = Annotated[float, Field(ge=0, le=1e15, allow_inf_nan=False)]
Percent = Annotated[float, Field(ge=-100, le=100000, allow_inf_nan=False)]


def valid_date(value: str | None) -> str | None:
    if value is not None:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('日期须为 YYYY-MM-DD')
        date.fromisoformat(value)
    return value


class AssetInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
    name: str = Field(min_length=1, max_length=100)
    currency: Currency
    source_name: str = Field(min_length=1, max_length=120)
    as_of: str
    source_url: str | None = Field(default=None, max_length=2000)
    price: Price | None = None
    price_as_of: str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    nav: Price | None = None
    nav_currency: Currency | None = None
    nav_as_of: str | None = None
    h_code: str | None = Field(default=None, max_length=32)
    h_price: Price | None = None
    h_currency: Currency | None = None
    h_price_as_of: str | None = None
    fx_hkd_cny: Price | None = None
    fx_as_of: str | None = None
    deal_price: Price | None = None
    deal_currency: Currency | None = None
    deal_as_of: str | None = None
    event_date: str | None = None
    event_type: str | None = Field(default=None, max_length=80)
    dividend_per_share: Amount | None = None
    dividend_currency: Currency | None = None
    dividend_period_start: str | None = None
    dividend_period_end: str | None = None
    dividend_basis: Literal['trailing_12_months', 'declared_period'] | None = None
    rate_pct: Percent | None = None
    income_per_10k: Amount | None = None
    rate_basis: str | None = Field(default=None, max_length=120)
    maturity_date: str | None = None
    subscription_status: str | None = Field(default=None, max_length=100)
    issue_price: Price | None = None
    pe: Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)] | None = None
    pb: Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)] | None = None
    change_pct: Percent | None = None
    yield_pct: Percent | None = None
    yield_basis: str | None = Field(default=None, max_length=120)

    _dates = field_validator('as_of', 'price_as_of', 'nav_as_of', 'h_price_as_of',
                            'fx_as_of', 'deal_as_of', 'event_date', 'dividend_period_start',
                            'dividend_period_end', 'maturity_date')(valid_date)

    @field_validator('*')
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('文字字段不能包含控制字符或换行')
        if isinstance(value, str) and not value.strip():
            raise ValueError('文字字段不能只含空白')
        return value

    @field_validator('source_url')
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme in {'http', 'https'} and parsed.hostname
                         and parsed.username is None and parsed.password is None)
                if not valid:
                    raise ValueError('来源链接须为不含登录凭据的 http/https 地址')
            except ValueError as exc:
                raise ValueError('来源链接须为不含登录凭据的 http/https 地址') from exc
        return value

    @model_validator(mode='after')
    def coherent_period(self):
        if (self.dividend_period_start and self.dividend_period_end
                and self.dividend_period_start > self.dividend_period_end):
            raise ValueError('股息期间开始日不能晚于结束日')
        return self


class StoredWorkspace(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1]
    revision: str = Field(min_length=1, max_length=64)
    updated_at: str | None = Field(default=None, max_length=64)
    categories: dict[str, Annotated[list[AssetInput], Field(max_length=MAX_ROWS)]] = Field(
        default_factory=dict)

    @field_validator('schema_version', mode='before')
    @classmethod
    def known_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('不兼容的存档版本')
        return value

    @field_validator('updated_at')
    @classmethod
    def timestamp_with_timezone(cls, value):
        if value is not None and datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError('存档更新时间必须包含时区')
        return value
