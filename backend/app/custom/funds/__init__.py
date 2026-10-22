"""Optional fund research routes registered through the stable extension API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.custom.funds.fallback import FallbackFundProvider
from app.custom.funds.models import (
    FundDividendsResponse,
    FundHoldingsResponse,
    FundNavResponse,
    FundProfileResponse,
    FundStatus,
    FundTradingResponse,
    NavRange,
)
from app.custom.funds.provider import get_api_key
from app.custom.funds.service import FundDataError, FundResearchService
from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "stemensysu.funds"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION

router = APIRouter(prefix="/api/ext/funds", tags=["fund-research"])


def get_service() -> FundResearchService:
    # Read credentials per request so changing the existing setting takes effect immediately.
    return FundResearchService(FallbackFundProvider())


@router.get("/status", response_model=FundStatus)
def status() -> FundStatus:
    configured = bool(get_api_key())
    return FundStatus(
        configured=True,
        primary_configured=configured,
        provider="fuyao_then_eastmoney",
        capabilities=['profile', 'nav', 'money_income', 'holdings', 'dividends', 'trading'],
        message=(
            "支持的资料、净值、分红和持仓接口优先扶摇；缺能力、无配置、失败或空结果时使用公开补充源。货币收益与通用申赎规则当前由公开披露补充。TickFlow 当前未集成这些基金数据集。"
        ),
    )


@router.get("/{ticker}/profile", response_model=FundProfileResponse)
def profile(
    ticker: str, service: Annotated[FundResearchService, Depends(get_service)],
) -> FundProfileResponse:
    try:
        return service.profile(ticker)
    except FundDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.get("/{ticker}/nav", response_model=FundNavResponse)
def nav(
    ticker: str,
    service: Annotated[FundResearchService, Depends(get_service)],
    nav_range: Annotated[NavRange, Query(alias="range")] = "year",
) -> FundNavResponse:
    try:
        return service.nav(ticker, nav_range)
    except FundDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.get("/{ticker}/holdings", response_model=FundHoldingsResponse)
def holdings(
    ticker: str, service: Annotated[FundResearchService, Depends(get_service)],
    asset_type: Literal['stock', 'bond'] | None = None,
    report_date: str | None = None,
) -> FundHoldingsResponse:
    try:
        return service.holdings(ticker, asset_type, report_date)
    except FundDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.get('/{ticker}/dividends', response_model=FundDividendsResponse)
def dividends(ticker: str, service: Annotated[FundResearchService, Depends(get_service)]):
    try:
        return service.dividends(ticker)
    except FundDataError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get('/{ticker}/trading', response_model=FundTradingResponse)
def trading(ticker: str, service: Annotated[FundResearchService, Depends(get_service)]):
    try:
        return service.trading(ticker)
    except FundDataError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)
