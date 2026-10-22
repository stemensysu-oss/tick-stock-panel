"""L2 extension for local multi-asset research; existing workspaces are untouched."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.services.multi_asset import (
    MAX_CSV_BYTES,
    MultiAssetConflictError,
    MultiAssetImportError,
    MultiAssetService,
    MultiAssetStoreError,
    csv_template,
)
from app.services.multi_asset_catalog import catalog

EXTENSION_ID = 'research.multi_asset'
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
_service: MultiAssetService | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    category: str = Field(min_length=1, max_length=32)
    csv_text: str = Field(min_length=1, max_length=MAX_CSV_BYTES)
    expected_revision: str = Field(min_length=1, max_length=64)


class ImportRequest(PreviewRequest):
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('确认导入须明确填写 confirmed: true')
        return value


def get_service() -> MultiAssetService:
    if _service is None:
        raise HTTPException(503, '多资产工作台尚未就绪，请检查服务启动状态。')
    return _service


ServiceDependency = Annotated[MultiAssetService, Depends(get_service)]
CategoryQuery = Annotated[str, Query(min_length=1, max_length=32)]


def _call(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except MultiAssetConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MultiAssetImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    except MultiAssetStoreError as exc:
        raise HTTPException(503, str(exc)) from exc


def _download(csv_text, filename):
    return Response('\ufeff' + csv_text, media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


def setup(registrar: BackendExtensionRegistrar) -> None:
    router = APIRouter(prefix='/api/multi-asset', tags=['multi-asset-research'])

    @router.get('/catalog')
    def get_catalog():
        return catalog()

    @router.get('/snapshot')
    def snapshot(category: CategoryQuery, service: ServiceDependency,
                 mode: Literal['imported', 'demo'] = 'imported'):
        return _call(service.snapshot, category, mode)

    @router.post('/import/preview')
    def preview(body: PreviewRequest, service: ServiceDependency):
        return _call(service.preview, body.category, body.csv_text,
                     expected_revision=body.expected_revision)

    @router.post('/import')
    def import_csv(body: ImportRequest, service: ServiceDependency):
        return _call(service.import_csv, body.category, body.csv_text,
                     expected_revision=body.expected_revision)

    @router.get('/template')
    def template(category: CategoryQuery):
        return _download(_call(csv_template, category), f'multi-asset-{category}-template.csv')

    @router.get('/export')
    def export(category: CategoryQuery, service: ServiceDependency):
        return _download(_call(service.export_csv, category), f'multi-asset-{category}.csv')

    registrar.include_router(router)


def startup(context: ExtensionContext) -> None:
    global _service
    # Corrupt imported data remains a per-request error; catalog and isolated
    # demos continue to work and no existing module is affected.
    _service = MultiAssetService(context.data_dir)
