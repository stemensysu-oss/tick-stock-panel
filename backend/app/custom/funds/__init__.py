"""Optional fund research routes registered through the stable extension API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.custom.funds.fallback import FallbackFundProvider
from app.custom.funds.models import (
    FundHoldingsResponse,
    FundNavResponse,
    FundProfileResponse,
    FundStatus,
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
        message=(
            "基金资料、净值和持仓优先扶摇；无配置、失败或空结果时使用东方财富公开补充源。TickFlow 当前未集成这些基金数据集。"
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
) -> FundHoldingsResponse:
    try:
        return service.holdings(ticker)
    except FundDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)
