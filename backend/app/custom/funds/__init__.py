"""Optional fund research routes registered through the stable extension API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.custom.funds.models import (
    FundHoldingsResponse,
    FundNavResponse,
    FundProfileResponse,
    FundStatus,
    NavRange,
)
from app.custom.funds.provider import FUND_KEY_SETUP_HINT, FuyaoFundProvider, get_api_key
from app.custom.funds.service import FundDataError, FundResearchService
from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "stemensysu.funds"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION

router = APIRouter(prefix="/api/ext/funds", tags=["fund-research"])


def get_service() -> FundResearchService:
    # Read credentials per request so changing the existing setting takes effect immediately.
    return FundResearchService(FuyaoFundProvider(get_api_key()))


@router.get("/status", response_model=FundStatus)
def status() -> FundStatus:
    configured = bool(get_api_key())
    return FundStatus(
        configured=configured,
        message=(
            "已配置扶摇 API Key；各基金接口权限将在查询时验证"
            if configured else FUND_KEY_SETUP_HINT
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
