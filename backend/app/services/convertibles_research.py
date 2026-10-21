"""User-imported convertible-bond snapshots; all prices are unadjusted CNY.

CSV is the only source in this initial extension. Only CNY bonds with a face
value of 100 per bond are supported, so double-low scores remain comparable.
``as_of`` is supplied by the
user, not inferred from the import time. Premium uses percentage points (20 is
20%), and double-low uses bond price + that percentage-point value. This is a
screening convention, not a valuation or recommendation.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.fs_utils import atomic_write_text

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_ERRORS = 100
MAX_STORED_BYTES = 8 * 1024 * 1024
_CODE = re.compile(r"^[0-9]{6}(?:\.(?:SH|SZ|BJ))?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_MISSING = frozenset({"", "-", "--", "n/a", "null"})
_METRICS = frozenset({"conversion_value", "conversion_premium_pct", "double_low"})
_IMPORT_LOCK = threading.RLock()

PositivePrice = Annotated[
    float, Field(ge=0.00000001, le=1_000_000_000, allow_inf_nan=False, strict=True)
]

CSV_COLUMNS = (
    "code", "name", "bond_price", "stock_code", "stock_name", "stock_price",
    "conversion_price", "face_value", "maturity_date", "redemption_status",
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
}


def validate_date(value: str) -> str:
    if not _DATE.fullmatch(value):
        raise ValueError("日期须使用 YYYY-MM-DD 格式")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期不存在") from exc
    return value


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

    @field_validator("face_value", mode="before")
    @classmethod
    def supported_face_value(cls, value: object) -> object:
        if value != 100 or isinstance(value, bool):
            raise ValueError("首版仅支持每张面值 100 元的人民币可转债，请勿混入其他面值")
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

    @field_validator("maturity_date")
    @classmethod
    def valid_maturity(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None

    @field_validator("name", "stock_name", "redemption_status")
    @classmethod
    def plain_text(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("文字字段不能包含控制字符或换行")
        return value


class ConvertibleItem(ConvertibleInput):
    conversion_value: float | None = None
    conversion_premium_pct: float | None = None
    double_low: float | None = None


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
    schema_version: Literal[1] = 1
    revision: str = "0"
    as_of: str | None = None
    updated_at: str | None = None
    source: Literal["用户导入"] = "用户导入"
    items: list[ConvertibleItem] = Field(default_factory=list, max_length=MAX_ROWS)

    @field_validator("as_of")
    @classmethod
    def valid_as_of(cls, value: str | None) -> str | None:
        return validate_date(value) if value is not None else None


def calculate_metrics(item: ConvertibleInput) -> ConvertibleItem:
    """Do not round conversion value before computing the premium."""
    value = premium = double_low = None
    if item.stock_price is not None and item.conversion_price is not None:
        value = (
            Decimal(str(item.face_value)) * Decimal(str(item.stock_price))
            / Decimal(str(item.conversion_price))
        )
        if item.bond_price is not None:
            premium = (Decimal(str(item.bond_price)) / value - 1) * 100
            double_low = Decimal(str(item.bond_price)) + premium
    return ConvertibleItem(
        **item.model_dump(),
        conversion_value=round(float(value), 6) if value is not None else None,
        conversion_premium_pct=round(float(premium), 6) if premium is not None else None,
        double_low=round(float(double_low), 6) if double_low is not None else None,
    )


def _price(value: str | None) -> float | None:
    if value is None or value.lower() in _MISSING:
        return None
    try:
        price = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("价格须为元单位的数字；未知值请留空") from exc
    if not price.is_finite() or not Decimal("0.00000001") <= price <= 1_000_000_000:
        raise ValueError("价格须为 0.00000001 至 10 亿元之间的有限数字；未知值请留空")
    return float(price)


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
            warnings.append("部分面值未填写，按每张 100 元计算；首版仅支持面值 100 元的人民币可转债。")
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
        raw_headers = next(reader, [])
        headers = [_ALIASES.get(h.strip(), h.strip().lower()) for h in raw_headers]
        if not {"code", "name"}.issubset(headers):
            issue(1, "表头必须包含 code/name（或转债代码/转债名称）")
            return result()
        recognized = [header for header in headers if header in CSV_COLUMNS]
        if len(recognized) != len(set(recognized)):
            issue(1, "表头包含重复含义的列，例如同时出现现价和 bond_price")
            return result()
        unknown_count = sum(header not in CSV_COLUMNS for header in headers)
        if unknown_count:
            warnings.append(f"已忽略 {unknown_count} 列未识别字段；金融指标会根据价格重新计算。")
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
            values: dict[str, str | float | None] = dict(raw)
            row_errors = len(errors)
            for field in ("bond_price", "stock_price", "conversion_price", "face_value"):
                try:
                    parsed = _price(raw.get(field))
                except ValueError as exc:
                    issue(row, str(exc), field)
                    parsed = None
                if field == "face_value" and parsed is None:
                    parsed = 100.0
                    default_face = True
                values[field] = parsed
            for field in ("stock_code", "stock_name", "maturity_date", "redemption_status"):
                if not values.get(field):
                    values[field] = None
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
            items.append(calculate_metrics(item))
    except csv.Error:
        issue(reader.line_num, "CSV 格式错误，请检查引号和分隔符")
    if not total_rows and not errors:
        issue(2, "CSV 没有数据行；不会用空文件覆盖已有清单")
    return result()


class ConvertibleImportError(ValueError):
    def __init__(self, preview: ImportPreview):
        super().__init__("CSV 校验失败，未保存任何数据")
        self.preview = preview


class ConvertibleConflictError(ValueError):
    pass


class ConvertibleStoreError(RuntimeError):
    pass


class ConvertibleService:
    """A bounded atomic snapshot, with optimistic concurrency and no stale cache.

    The application's single backend process serializes writes using a shared
    lock. Every read loads the persisted snapshot, so an import never requires
    a restart. Frontend callers invalidate only their convertible-list query.
    """

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "custom" / "convertibles" / "snapshot.json"

    def snapshot(self) -> ConvertibleSnapshot:
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
            identities = {item.code.split(".", 1)[0] for item in snapshot.items}
            if len(identities) != len(snapshot.items) or (
                snapshot.items and (snapshot.as_of is None or snapshot.revision == "0")
            ):
                raise ConvertibleStoreError("研究清单格式异常，已停止覆盖；请检查备份")
            snapshot.items = [
                calculate_metrics(ConvertibleInput.model_validate(item.model_dump(exclude=_METRICS)))
                for item in snapshot.items
            ]
            return snapshot
        except (OSError, UnicodeError, ValidationError, json.JSONDecodeError) as exc:
            raise ConvertibleStoreError(
                "无法读取研究清单，数据可能损坏、版本不兼容或目录不可读；已停止覆盖"
            ) from exc

    def preview(self, csv_text: str, as_of: str) -> ImportPreview:
        preview = parse_csv(csv_text, as_of)
        return preview.model_copy(update={"base_revision": self.snapshot().revision})

    def import_csv(
        self, csv_text: str, as_of: str, *, expected_revision: str,
    ) -> ConvertibleSnapshot:
        preview = parse_csv(csv_text, as_of)
        if not preview.valid:
            raise ConvertibleImportError(preview)
        candidate = ConvertibleSnapshot(
            revision=uuid.uuid4().hex,
            as_of=as_of,
            updated_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
            items=preview.items,
        )
        payload = json.dumps(candidate.model_dump(), ensure_ascii=False, allow_nan=False)
        with _IMPORT_LOCK:
            current = self.snapshot()
            if current.revision != expected_revision:
                raise ConvertibleConflictError("清单已被另一操作更新，请重新预览后再确认替换")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self.path, payload)
            except OSError as exc:
                raise ConvertibleStoreError("保存失败，原清单未被替换；请检查目录权限和磁盘空间") from exc
        return candidate
