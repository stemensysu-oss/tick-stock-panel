"""Batch orchestration for the private calculation view; no shared result cache."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.convertibles_calculation import calculate_personal
from app.services.convertibles_calculation_config import ConvertibleCalculationSettings
from app.services.convertibles_math import calculate_metrics
from app.services.convertibles_models import ConvertibleItem
from app.services.convertibles_reference import ConvertibleReference, references
from app.services.convertibles_research import ConvertibleConflictError
from app.services.convertibles_sources import ConvertibleDataError


class ConvertibleCalculationSnapshot(BaseModel):
    revision: str
    as_of: str | None
    calculation_settings: ConvertibleCalculationSettings
    items: list[ConvertibleItem]
    references: list[ConvertibleReference] = Field(default_factory=list)
    attempts: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reference_status: str = 'available'


def calculation_snapshot(store, expected_revision, *, settings_override=None, code=None, research_override=None):
    snapshot = store.snapshot()
    if snapshot.revision != expected_revision:
        raise ConvertibleConflictError('清单或参数已改变，请重新载入后再计算')
    requested = snapshot.items
    if code is not None:
        requested = [item for item in requested if item.code.split('.')[0] == code.split('.')[0]]
        if not requested:
            raise ValueError('研究清单中未找到该转债')
    settings = settings_override if settings_override is not None else snapshot.calculation_settings
    warning, attempts, ref_items, ref_status = [], [], [], 'available'
    if snapshot.items:
        try:
            sourced = references([item.code for item in snapshot.items])
            ref_items, attempts, warning = sourced.items, sourced.attempts, list(sourced.warnings)
        except ConvertibleDataError:
            ref_status = 'unavailable'
            warning.append('公开参考本次不可用，已保存的人工资料仍可独立计算；未伪造缺失参数，请重试。')
    lookup = {item.code.split('.')[0]: item for item in ref_items}
    items = []
    for item in requested:
        if research_override is not None:
            item = calculate_metrics(item.model_copy(update={'research': research_override}), snapshot.as_of)
        # Automatic full-price treatment is confined to an explicitly fetched
        # CN convertible market list. Imported/manual prices require declaration.
        auto_full = (snapshot.source.startswith('市场清单') and item.quote_at is not None
                     and item.asset_type == 'convertible' and not item.code.startswith(('132', '117')))
        items.append(calculate_personal(item, snapshot.as_of, settings,
            lookup.get(item.code.split('.')[0]), market_quote_full=auto_full))
    if store.snapshot().revision != expected_revision:
        raise ConvertibleConflictError('计算期间清单或参数已改变，结果未采用，请重试')
    return ConvertibleCalculationSnapshot(revision=snapshot.revision, as_of=snapshot.as_of,
        calculation_settings=settings, items=items, references=ref_items,
        attempts=attempts, warnings=warning, reference_status=ref_status)
