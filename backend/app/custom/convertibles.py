"""L2 extension for an explicitly imported convertible-bond research snapshot."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.services.convertibles_research import (
    CSV_TEMPLATE,
    MAX_CSV_BYTES,
    ConvertibleConflictError,
    ConvertibleImportError,
    ConvertibleService,
    ConvertibleSnapshot,
    ConvertibleStoreError,
    ImportPreview,
    validate_date,
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


def get_service() -> ConvertibleService:
    if _service is None:
        raise HTTPException(503, "可转债研究模块尚未就绪，请检查服务启动状态")
    return _service


ServiceDependency = Annotated[ConvertibleService, Depends(get_service)]


def setup(registrar: BackendExtensionRegistrar) -> None:
    router = APIRouter(prefix="/api/ext/convertibles", tags=["convertible-research"])

    @router.get("", response_model=ConvertibleSnapshot)
    def snapshot(service: ServiceDependency) -> ConvertibleSnapshot:
        try:
            return service.snapshot()
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

    registrar.include_router(router)


def startup(context: ExtensionContext) -> None:
    global _service
    _service = None
    service = ConvertibleService(context.data_dir)
    service.snapshot()
    _service = service
