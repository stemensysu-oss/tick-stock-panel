"""L2 routes for convertible research, calculations and optional quote refresh."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.services.convertibles_disclosures import ConvertibleDisclosures, disclosures
from app.services.convertibles_reference import ConvertibleReferences, references
from app.services.convertibles_fallback import FallbackConvertibleProvider
from app.services.convertibles_research import (
    CSV_TEMPLATE,
    MAX_CSV_BYTES,
    ConvertibleConflictError,
    ConvertibleImportError,
    ConvertibleItem,
    ConvertibleResearch,
    ConvertibleService,
    ConvertibleSnapshot,
    ConvertibleStoreError,
    ImportPreview,
    validate_date,
)
from app.services.convertibles_sources import (
    ConvertibleDataError,
    ConvertibleQuoteService,
    ConvertibleSourceStatus,
)

EXTENSION_ID = "research.convertibles"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
_service: ConvertibleService | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(max_length=MAX_CSV_BYTES)
    as_of: str

    @field_validator("as_of")
    @classmethod
    def valid_as_of(cls, value: str) -> str:
        return validate_date(value)


class ImportRequest(PreviewRequest):
    expected_revision: str = Field(min_length=1, max_length=64)
    confirmed: Literal[True]


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=64)


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[Annotated[str, Field(min_length=6, max_length=12)]] = Field(min_length=1, max_length=2000)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research: ConvertibleResearch
    expected_revision: str | None = Field(default=None, min_length=1, max_length=64)


class ResearchRequest(AnalysisRequest):
    expected_revision: str = Field(min_length=1, max_length=64)


class RestorePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: ConvertibleSnapshot


class RestoreRequest(RestorePreviewRequest):
    expected_revision: str = Field(min_length=1, max_length=64)
    confirmed: Literal[True]


def get_service() -> ConvertibleService:
    if _service is None:
        raise HTTPException(503, "可转债研究模块尚未就绪，请检查服务启动状态")
    return _service


ServiceDependency = Annotated[ConvertibleService, Depends(get_service)]


def get_quote_service() -> ConvertibleQuoteService:
    # Configuration is read per request so saving a new key takes effect without
    # reopening the extension, and status never performs a network probe.
    return ConvertibleQuoteService(FallbackConvertibleProvider())


QuoteServiceDependency = Annotated[ConvertibleQuoteService, Depends(get_quote_service)]


def setup(registrar: BackendExtensionRegistrar) -> None:
    router = APIRouter(prefix="/api/ext/convertibles", tags=["convertible-research"])

    @router.post('/references', response_model=ConvertibleReferences)
    def reference_data(body: ReferenceRequest):
        try:
            return references(body.codes)
        except ConvertibleDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None

    @router.get('/{code}/disclosures', response_model=ConvertibleDisclosures)
    def sourced_disclosures(code: str):
        try:
            return disclosures(code)
        except ConvertibleDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None

    @router.get("", response_model=ConvertibleSnapshot)
    def snapshot(service: ServiceDependency) -> ConvertibleSnapshot:
        try:
            return service.snapshot()
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/status", response_model=ConvertibleSourceStatus)
    def status(
        service: ServiceDependency, quotes: QuoteServiceDependency,
    ) -> ConvertibleSourceStatus:
        try:
            return quotes.status(service.snapshot())
        except ConvertibleDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/refresh", response_model=ConvertibleSnapshot)
    def refresh(
        body: RefreshRequest, service: ServiceDependency, quotes: QuoteServiceDependency,
    ) -> ConvertibleSnapshot:
        try:
            return quotes.refresh(service, expected_revision=body.expected_revision)
        except ConvertibleDataError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        except ConvertibleConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/template")
    def template() -> Response:
        return Response(
            "\ufeff" + CSV_TEMPLATE,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="convertibles-template.csv"'},
        )

    @router.post("/preview", response_model=ImportPreview)
    def preview(
        body: PreviewRequest, service: ServiceDependency,
    ) -> ImportPreview:
        try:
            return service.preview(body.csv_text, body.as_of)
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/import", response_model=ConvertibleSnapshot)
    def import_csv(
        body: ImportRequest, service: ServiceDependency,
    ) -> ConvertibleSnapshot:
        try:
            return service.import_csv(
                body.csv_text, body.as_of, expected_revision=body.expected_revision,
            )
        except ConvertibleImportError as exc:
            raise HTTPException(422, {
                "message": str(exc),
                "errors": [error.model_dump() for error in exc.preview.errors],
            }) from exc
        except ConvertibleConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/restore/preview", response_model=ImportPreview)
    def preview_restore(
        body: RestorePreviewRequest, service: ServiceDependency,
    ) -> ImportPreview:
        try:
            return service.preview_restore(body.snapshot)
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/restore", response_model=ConvertibleSnapshot)
    def restore(
        body: RestoreRequest, service: ServiceDependency,
    ) -> ConvertibleSnapshot:
        try:
            return service.restore_backup(
                body.snapshot, expected_revision=body.expected_revision,
            )
        except ConvertibleImportError as exc:
            raise HTTPException(422, {
                "message": str(exc),
                "errors": [error.model_dump() for error in exc.preview.errors],
            }) from exc
        except ConvertibleConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/{code}/analyze", response_model=ConvertibleItem)
    def analyze(
        code: str, body: AnalysisRequest, service: ServiceDependency,
    ) -> ConvertibleItem:
        try:
            return service.analyze_research(
                code, body.research, expected_revision=body.expected_revision,
            )
        except ConvertibleConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.put("/{code}/research", response_model=ConvertibleSnapshot)
    def save_research(
        code: str, body: ResearchRequest, service: ServiceDependency,
    ) -> ConvertibleSnapshot:
        try:
            return service.update_research(
                code, body.research, expected_revision=body.expected_revision,
            )
        except ConvertibleConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConvertibleStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    registrar.include_router(router)


def startup(context: ExtensionContext) -> None:
    global _service
    _service = None
    service = ConvertibleService(context.data_dir)
    service.snapshot()
    _service = service
