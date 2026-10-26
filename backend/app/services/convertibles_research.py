"""Convertible snapshot import, research updates and atomic quote replacement.

Source adapters normalize quotes before this boundary. Missing values remain
unknown, while every derived value is recomputed from the declared snapshot date.
"""
from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from datetime import datetime
from decimal import Decimal, DecimalException
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.services.convertibles_math import calculate_metrics as calculate_metrics
from app.services.convertibles_models import (
    MAX_ROWS as MAX_ROWS,
)
from app.services.convertibles_models import (
    ConvertibleInput as ConvertibleInput,
)
from app.services.convertibles_models import (
    ConvertibleItem as ConvertibleItem,
)
from app.services.convertibles_models import (
    ConvertibleResearch as ConvertibleResearch,
)
from app.services.convertibles_models import (
    ConvertibleSnapshot as ConvertibleSnapshot,
)
from app.services.convertibles_models import (
    ImportIssue as ImportIssue,
)
from app.services.convertibles_models import (
    ImportPreview as ImportPreview,
)
from app.services.convertibles_models import (
    validate_date as validate_date,
)
from app.services.fs_utils import atomic_write_text

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ERRORS = 100
MAX_STORED_BYTES = 32 * 1024 * 1024
_MISSING = frozenset({"", "-", "--", "n/a", "null"})
_IMPORT_LOCK = threading.RLock()
_INPUT_FIELDS = frozenset(ConvertibleInput.model_fields)
_QUOTE_FIELDS = frozenset({
    "bond_price", "stock_price", "bond_change_pct", "stock_change_pct",
    "turnover_amount", "turnover_rate_pct", "quote_at", "stock_quote_at",
    "fetched_at", "quote_source",
})
CSV_COLUMNS = (
    "code", "name", "bond_price", "stock_code", "stock_name", "stock_price",
    "conversion_price", "face_value", "maturity_date", "redemption_status",
    "bond_change_pct", "stock_change_pct", "stock_pb", "credit_rating", "industry",
    "concepts", "asset_type", "listing_date", "outstanding_amount", "turnover_amount",
    "turnover_rate_pct", "float_market_cap", "fund_holding_pct", "fund_holding_report_date",
    "fund_holding_publish_date", "call_trigger_ratio_pct", "put_trigger_ratio_pct",
    "conversion_start_date", "conversion_price_effective_date", "stock_volatility_pct",
    "volatility_window_days", "volatility_adjustment", "quote_at", "stock_quote_at",
    "fetched_at", "quote_source", "terms_source", "source_url",
)
CSV_TEMPLATE = ",".join(CSV_COLUMNS) + "\n"
_ALIASES = {
    "转债代码": "code", "债券代码": "code", "代码": "code",
    "转债名称": "name", "债券名称": "name", "转债简称": "name", "名称": "name",
    "现价": "bond_price", "转债价格": "bond_price", "转债现价": "bond_price",
    "最新价": "bond_price", "价格": "bond_price",
    "正股代码": "stock_code", "正股名称": "stock_name",
    "正股价": "stock_price", "正股价格": "stock_price",
    "转股价": "conversion_price", "转股价格": "conversion_price",
    "面值": "face_value", "到期日期": "maturity_date", "到期日": "maturity_date",
    "强赎状态": "redemption_status", "赎回状态": "redemption_status",
    "涨跌幅": "bond_change_pct", "涨跌幅(%)": "bond_change_pct",
    "正股涨跌幅": "stock_change_pct", "正股涨跌幅(%)": "stock_change_pct",
    "正股PB": "stock_pb", "正股pb": "stock_pb", "市净率": "stock_pb",
    "评级": "credit_rating", "信用评级": "credit_rating", "行业": "industry",
    "概念": "concepts", "证券类型": "asset_type", "上市日期": "listing_date",
    "剩余本金(元)": "outstanding_amount", "剩余规模(元)": "outstanding_amount",
    "成交额(元)": "turnover_amount", "换手率": "turnover_rate_pct",
    "换手率(%)": "turnover_rate_pct", "流通市值(元)": "float_market_cap",
    "基金持仓(%)": "fund_holding_pct", "基金持仓比例(%)": "fund_holding_pct",
    "基金持仓报告期": "fund_holding_report_date", "基金持仓公告日": "fund_holding_publish_date",
    "强赎触发比例(%)": "call_trigger_ratio_pct", "回售触发比例(%)": "put_trigger_ratio_pct",
    "转股起始日": "conversion_start_date", "转股价生效日": "conversion_price_effective_date",
    "正股波动率(%)": "stock_volatility_pct", "波动率窗口": "volatility_window_days",
    "波动率复权": "volatility_adjustment", "转债报价时间": "quote_at",
    "正股报价时间": "stock_quote_at", "抓取时间": "fetched_at", "行情来源": "quote_source",
    "条款来源": "terms_source", "来源链接": "source_url",
}
_UNIT_ALIASES = {
    "剩余规模(亿元)": ("outstanding_amount", Decimal(100_000_000)),
    "剩余规模(亿)": ("outstanding_amount", Decimal(100_000_000)),
    "成交额(万元)": ("turnover_amount", Decimal(10_000)),
    "成交额(万)": ("turnover_amount", Decimal(10_000)),
    "流通市值(亿元)": ("float_market_cap", Decimal(100_000_000)),
    "正股流通市值(亿元)": ("float_market_cap", Decimal(100_000_000)),
}
_NUMERIC = frozenset({
    "bond_price", "stock_price", "conversion_price", "face_value", "bond_change_pct",
    "stock_change_pct", "stock_pb", "outstanding_amount", "turnover_amount", "turnover_rate_pct",
    "float_market_cap", "fund_holding_pct", "call_trigger_ratio_pct", "put_trigger_ratio_pct",
    "stock_volatility_pct", "volatility_window_days",
})
_PRICES = frozenset({"bond_price", "stock_price", "conversion_price", "face_value"})


def _number(value: str | None, field: str, scale: Decimal = Decimal(1)) -> float | int | None:
    if value is None or value.lower() in _MISSING:
        return None
    if field.endswith("_pct") and value.endswith("%"):
        value = value[:-1].strip()
    try:
        number = Decimal(value) * scale
    except DecimalException as exc:
        raise ValueError("须为有限数字；未知值请留空，百分数字段 20 表示 20%") from exc
    if not number.is_finite():
        raise ValueError("须为有限数字；未知值请留空")
    if field in _PRICES and not Decimal("0.00000001") <= number <= 1_000_000_000:
        raise ValueError("价格须为 0.00000001 至 10 亿元之间的有限数字；未知值请留空")
    if field == "volatility_window_days":
        if number != number.to_integral_value():
            raise ValueError("波动率窗口必须为整数交易日")
        return int(number)
    return float(number)


def parse_csv(csv_text: str, as_of: str) -> ImportPreview:
    """Normalize CSV without writes. Any error blocks the entire import."""
    validate_date(as_of)
    items: list[ConvertibleItem] = []
    errors: list[ImportIssue] = []
    warnings: list[str] = []
    total_rows = 0
    default_face = False

    def issue(row: int, message: str, field: str | None = None) -> None:
        if len(errors) < MAX_ERRORS:
            errors.append(ImportIssue(row=row, field=field, message=message))

    def result() -> ImportPreview:
        if default_face:
            warnings.append("部分面值未填写，按每张 100 元计算；仅支持面值 100 元的人民币可转债。")
        if len(errors) == MAX_ERRORS:
            warnings.append("仅展示前 100 个错误，请修正后重新预览。")
        return ImportPreview(
            valid=not errors and bool(items), total_rows=total_rows, items=items,
            errors=errors, warnings=warnings, as_of=as_of,
        )

    if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        issue(0, "CSV 文件不能超过 2 MiB")
        return result()
    if "\x00" in csv_text:
        issue(0, "CSV 含有空字节，请另存为 UTF-8 CSV")
        return result()
    reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), strict=True)
    try:
        raw_headers = [h.strip().replace("（", "(").replace("）", ")") for h in next(reader, [])]
        headers: list[str] = []
        scales: dict[str, Decimal] = {}
        for header in raw_headers:
            if header in _UNIT_ALIASES:
                field, scale = _UNIT_ALIASES[header]
                headers.append(field)
                scales[field] = scale
                warnings.append(f"列“{header}”已按列名单位换算为元。")
            else:
                headers.append(_ALIASES.get(header, header.lower()))
        if not {"code", "name"}.issubset(headers):
            issue(1, "表头必须包含 code/name（或转债代码/转债名称）")
            return result()
        recognized = [header for header in headers if header in CSV_COLUMNS]
        if len(recognized) != len(set(recognized)):
            issue(1, "表头包含重复含义的列，例如同时出现现价和 bond_price")
            return result()
        unknown_count = sum(header not in CSV_COLUMNS for header in headers)
        if unknown_count:
            warnings.append(f"已忽略 {unknown_count} 列未识别字段；金融指标会根据原始输入重新计算。")
        seen_codes: set[str] = set()
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            total_rows += 1
            row = reader.line_num
            if total_rows > MAX_ROWS:
                issue(row, "最多导入 2000 条数据，请拆分或缩小清单")
                break
            if len(cells) != len(headers):
                issue(row, "本行列数与表头不一致；含逗号的文本须用双引号包围")
                continue
            raw = {
                header: cell.strip() for header, cell in zip(headers, cells, strict=True)
                if header in CSV_COLUMNS
            }
            values: dict[str, object] = dict(raw)
            row_errors = len(errors)
            for field in _NUMERIC:
                try:
                    parsed = _number(raw.get(field), field, scales.get(field, Decimal(1)))
                except (ValueError, OverflowError) as exc:
                    issue(row, str(exc), field)
                    parsed = None
                if field == "face_value" and parsed is None:
                    parsed = 100.0
                    default_face = True
                values[field] = parsed
            for field in CSV_COLUMNS:
                if (field not in _NUMERIC and field not in {"code", "name", "asset_type"}
                        and (not values.get(field) or str(values[field]).lower() in _MISSING)):
                    values[field] = None
            values["asset_type"] = {"可转债": "convertible", "可交换债": "exchangeable"}.get(
                str(raw.get("asset_type")), raw.get("asset_type") or "convertible",
            )
            if len(errors) != row_errors or len(errors) == MAX_ERRORS:
                continue
            try:
                item = ConvertibleInput.model_validate(values)
            except ValidationError as exc:
                for error in exc.errors(include_input=False, include_context=False):
                    field = str(error["loc"][0]) if error["loc"] else None
                    issue(row, error["msg"].removeprefix("Value error, "), field)
                continue
            identity = item.code.split(".", 1)[0]
            if identity in seen_codes:
                issue(row, "同一转债代码重复出现，请保留一行并确认数据日期", "code")
                continue
            seen_codes.add(identity)
            items.append(calculate_metrics(item, as_of))
    except csv.Error:
        issue(reader.line_num, "CSV 格式错误，请检查引号和分隔符")
    if not total_rows and not errors:
        issue(2, "CSV 没有数据行；不会用空文件覆盖已有清单")
    return result()


class ConvertibleImportError(ValueError):
    def __init__(self, preview: ImportPreview):
        super().__init__("导入校验失败，未保存任何数据")
        self.preview = preview


class ConvertibleConflictError(ValueError):
    pass


class ConvertibleStoreError(RuntimeError):
    pass


def _identity(code: str) -> str:
    return str(ConvertibleInput.valid_code(code)).split(".", 1)[0]


class ConvertibleService:
    """One bounded atomic snapshot, with optimistic concurrency and no stale cache.

    Price refresh changes only a whitelist of quote fields. Research is persisted
    beside the source inputs and survives quote refresh. CSV remains an explicit
    full replacement. The process-wide lock guards only the final CAS and write.
    """

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "custom" / "convertibles" / "snapshot.json"

    def _load(self) -> ConvertibleSnapshot:
        try:
            if not self.path.exists():
                return ConvertibleSnapshot()
            if self.path.stat().st_size > MAX_STORED_BYTES:
                raise ConvertibleStoreError("研究清单文件超出大小限制，请检查备份")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            required = {"schema_version", "revision", "as_of", "updated_at", "source", "items"}
            if not isinstance(raw, dict) or not required.issubset(raw):
                raise ConvertibleStoreError("研究清单格式异常，已停止覆盖；请检查备份")
            snapshot = ConvertibleSnapshot.model_validate(raw)
            identities = {_identity(item.code) for item in snapshot.items}
            if len(identities) != len(snapshot.items) or (
                snapshot.items and (snapshot.as_of is None or snapshot.revision == "0")
            ):
                raise ConvertibleStoreError("研究清单格式异常，已停止覆盖；请检查备份")
            return snapshot
        except (OSError, UnicodeError, ValidationError, json.JSONDecodeError) as exc:
            raise ConvertibleStoreError(
                "无法读取研究清单，数据可能损坏、版本不兼容或目录不可读；已停止覆盖"
            ) from exc

    def snapshot(self) -> ConvertibleSnapshot:
        snapshot = self._load()
        snapshot.items = [calculate_metrics(item, snapshot.as_of) for item in snapshot.items]
        return snapshot

    def initialize_market(self, items, as_of, source, *, expected_revision):
        # Only an empty snapshot can be seeded. Never replace imported research.
        current = self._load()
        if current.revision != expected_revision or current.items:
            raise ConvertibleConflictError("清单已变化，请重新读取；市场初始化不会覆盖已有研究")
        candidate = ConvertibleSnapshot(as_of=as_of, source=f"市场清单 · {source}",
                                        items=[calculate_metrics(item, as_of) for item in items],
                                        calculation_settings=current.calculation_settings)
        return self._commit(candidate, expected_revision)

    def preview(self, csv_text: str, as_of: str) -> ImportPreview:
        return self._preserve_research(parse_csv(csv_text, as_of), self._load())

    @staticmethod
    def _preserve_research(
        preview: ImportPreview, current: ConvertibleSnapshot,
    ) -> ImportPreview:
        existing = {_identity(item.code): item for item in current.items}
        items, errors = [], list(preview.errors)
        for index, item in enumerate(preview.items):
            previous = existing.get(_identity(item.code))
            if previous and previous.research is not None:
                has_research = bool(previous.research.model_dump(exclude_defaults=True))
                changed_stock = (
                    previous.stock_code is not None and item.stock_code is not None
                    and _identity(previous.stock_code) != _identity(item.stock_code)
                )
                if has_research and (changed_stock or previous.asset_type != item.asset_type):
                    errors.append(ImportIssue(
                        row=index + 2, field="stock_code" if changed_stock else "asset_type",
                        message=f"{item.code} 的正股绑定或证券类型改变，请先核对并清空该标的旧研究资料后再导入",
                    ))
                else:
                    item = calculate_metrics(
                        item.model_copy(update={"research": previous.research}), preview.as_of,
                    )
            items.append(item)
        warnings = list(preview.warnings)
        if current.items:
            warnings.append("本次替换行情与基础清单；同代码研究记录保留，清单外标的及其研究记录将移除。建议先下载完整 JSON 备份。")
        return preview.model_copy(update={
            "items": items, "errors": errors, "warnings": warnings,
            "valid": preview.valid and not errors, "base_revision": current.revision,
        })

    @staticmethod
    def _serialize_candidate(candidate: ConvertibleSnapshot) -> str:
        candidate.revision = uuid.uuid4().hex
        candidate.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        return json.dumps(candidate.model_dump(), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _check_payload_size(payload: str) -> None:
        if len(payload.encode("utf-8")) > MAX_STORED_BYTES:
            raise ConvertibleStoreError("研究资料超出 32 MiB 大小限制，原清单未被替换")

    def _commit(self, candidate: ConvertibleSnapshot, expected_revision: str) -> ConvertibleSnapshot:
        payload = self._serialize_candidate(candidate)
        self._check_payload_size(payload)
        with _IMPORT_LOCK:
            current = self._load()
            if current.revision != expected_revision:
                raise ConvertibleConflictError("清单已被另一操作更新，请重新读取或预览后再保存")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self.path, payload)
            except OSError as exc:
                raise ConvertibleStoreError("保存失败，原清单未被替换；请检查目录权限和磁盘空间") from exc
        return candidate

    def import_csv(
        self, csv_text: str, as_of: str, *, expected_revision: str,
    ) -> ConvertibleSnapshot:
        current = self._load()
        if current.revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请重新预览后再确认替换")
        preview = self._preserve_research(parse_csv(csv_text, as_of), current)
        if not preview.valid:
            raise ConvertibleImportError(preview)
        return self._commit(ConvertibleSnapshot(as_of=as_of, items=preview.items,
            calculation_settings=current.calculation_settings), expected_revision)

    def preview_restore(self, backup: ConvertibleSnapshot) -> ImportPreview:
        errors = []
        if not backup.items or backup.as_of is None:
            errors.append(ImportIssue(row=0, message="备份必须包含非空研究清单与数据日期"))
        identities = {_identity(item.code) for item in backup.items}
        if len(identities) != len(backup.items):
            errors.append(ImportIssue(row=0, field="code", message="备份中存在重复转债代码"))
        if len(backup.model_dump_json().encode("utf-8")) > MAX_STORED_BYTES:
            errors.append(ImportIssue(row=0, message="备份超过 32 MiB 大小限制"))
        items = [] if errors else [calculate_metrics(item, backup.as_of) for item in backup.items]
        if not errors:
            # Preview the same recomputed output, metadata and encoding used by
            # commit; otherwise a compact backup may pass but fail at save time.
            candidate = ConvertibleSnapshot(as_of=backup.as_of, source=backup.source, items=items,
                                            calculation_settings=backup.calculation_settings)
            try:
                self._check_payload_size(self._serialize_candidate(candidate))
            except ConvertibleStoreError:
                errors.append(ImportIssue(row=0, message="重算后的完整备份超过 32 MiB 大小限制"))
                items = []
        return ImportPreview(
            valid=not errors, total_rows=len(backup.items), items=items, errors=errors,
            warnings=["完整备份恢复会替换当前全部清单、现金流、条款与公告；金融指标将重新计算，保存版本重新生成。"],
            as_of=backup.as_of or "", base_revision=self._load().revision,
        )

    def restore_backup(
        self, backup: ConvertibleSnapshot, *, expected_revision: str,
    ) -> ConvertibleSnapshot:
        preview = self.preview_restore(backup)
        if not preview.valid:
            raise ConvertibleImportError(preview)
        if preview.base_revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请重新预览备份后再恢复")
        return self._commit(ConvertibleSnapshot(
            as_of=backup.as_of, source=backup.source, items=preview.items,
            calculation_settings=backup.calculation_settings,
        ), expected_revision)

    @staticmethod
    def _research_item(
        snapshot: ConvertibleSnapshot, code: str, research: ConvertibleResearch,
    ) -> tuple[int, ConvertibleItem]:
        identity = _identity(code)
        for index, item in enumerate(snapshot.items):
            if _identity(item.code) == identity:
                values = item.model_dump(include=_INPUT_FIELDS)
                values["research"] = research.model_dump()
                return index, calculate_metrics(ConvertibleInput.model_validate(values), snapshot.as_of)
        raise ValueError("研究清单中未找到该转债，请先导入其基础资料")

    def analyze_research(
        self, code: str, research: ConvertibleResearch, *, expected_revision: str | None = None,
    ) -> ConvertibleItem:
        snapshot = self._load()
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请重新打开详情后再试算")
        _, item = self._research_item(snapshot, code, research)
        return item

    def update_research(
        self, code: str, research: ConvertibleResearch, *, expected_revision: str,
    ) -> ConvertibleSnapshot:
        current = self.snapshot()
        if current.revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请重新读取后再保存研究资料")
        index, item = self._research_item(current, code, research)
        current.items[index] = item
        return self._commit(current, expected_revision)

    def merge_quotes(
        self, updates: dict[str, dict], *, expected_revision: str, as_of: str, source: str,
    ) -> ConvertibleSnapshot:
        validate_date(as_of)
        current = self._load()
        if current.revision != expected_revision:
            raise ConvertibleConflictError("清单已被另一操作更新，请重新读取后再刷新行情")
        if current.as_of and as_of < current.as_of:
            raise ValueError("行情日期早于现有清单日期，本次更新未采用")
        if not updates:
            raise ValueError("未收到可更新的行情，原清单已保留")
        normalized: dict[str, dict] = {}
        identities = {_identity(item.code) for item in current.items}
        for code, fields in updates.items():
            identity = _identity(code)
            if identity not in identities:
                raise ValueError("行情包含研究清单外的代码，本次更新未采用")
            if identity in normalized:
                raise ValueError("行情包含重复代码，本次更新未采用")
            if not isinstance(fields, dict) or not fields or set(fields) - _QUOTE_FIELDS:
                raise ValueError("行情更新含有不允许覆盖的字段，本次更新未采用")
            normalized[identity] = fields
        next_items = []
        for item in current.items:
            values = item.model_dump(include=_INPUT_FIELDS)
            fields = normalized.get(_identity(item.code))
            if fields:
                candidate = ConvertibleInput.model_validate({**values, **fields})
                for key in ("quote_at", "stock_quote_at"):
                    old_time, new_time = getattr(item, key), getattr(candidate, key)
                    if old_time and new_time and datetime.fromisoformat(new_time) < datetime.fromisoformat(old_time):
                        raise ValueError("行情时间早于已有报价，本次更新未采用")
                values = candidate.model_dump()
            next_items.append(calculate_metrics(ConvertibleInput.model_validate(values), as_of))
        candidate = ConvertibleSnapshot(
            as_of=as_of, source=source, items=next_items,
            calculation_settings=current.calculation_settings,
        )
        return self._commit(candidate, expected_revision)

    def update_calculation_settings(self, settings, *, expected_revision):
        current = self._load()
        if current.revision != expected_revision:
            raise ConvertibleConflictError('研究清单已更新，请重新载入后再保存公式与参数')
        current.calculation_settings = settings
        return self._commit(current, expected_revision)
