"""Local research snapshots, atomic category import and isolated fictional demos.

This phase deliberately has no remote provider. Inputs and source attribution are
user declarations; formulas never promote an imported record into verified data.
"""
from __future__ import annotations

import csv
import io
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.services.fs_utils import atomic_write_text
from app.services.multi_asset_catalog import CATEGORIES, NUMERIC
from app.services.multi_asset_models import MAX_ROWS, AssetInput, StoredWorkspace

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_STORED_BYTES = 16 * 1024 * 1024
_LOCK = threading.RLock()
_METRICS = ('nav_premium_pct', 'ah_premium_pct', 'deal_spread_pct', 'dividend_yield_pct')
_NAV_CATEGORIES = frozenset({'etf', 'closed_end', 'lof', 'qdii'})
_BASE_WARNING = '本模块尚无已核验实时 API；导入来源与日期由用户填写，计算结果未独立核验。'


class MultiAssetImportError(ValueError):
    pass


class MultiAssetConflictError(ValueError):
    pass


class MultiAssetStoreError(RuntimeError):
    pass


def category_spec(category: str) -> dict:
    if category not in CATEGORIES:
        raise MultiAssetImportError('未知资产类别，请刷新类别目录')
    return CATEGORIES[category]


def parse_csv(category: str, csv_text: str) -> list[AssetInput]:
    """One bad row rejects the whole file, without changing existing records."""
    spec = category_spec(category)
    if len(csv_text.encode('utf-8')) > MAX_CSV_BYTES:
        raise MultiAssetImportError('CSV 不能超过 2 MiB')
    if '\x00' in csv_text:
        raise MultiAssetImportError('CSV 不能包含空字节')
    reader = csv.reader(io.StringIO(csv_text.removeprefix('\ufeff'), newline=''), strict=True)
    rows = []
    seen = set()
    try:
        headers = [cell.strip() for cell in next(reader, [])]
        if len(headers) != len(set(headers)):
            raise MultiAssetImportError('表头存在重复列')
        if not {'code', 'name', 'currency', 'source_name', 'as_of'}.issubset(headers):
            raise MultiAssetImportError('表头须包含 code,name,currency,source_name,as_of')
        if set(headers) - set(spec['field_keys']):
            raise MultiAssetImportError('CSV 包含当前类别不支持的列；请使用本类别模板，不可导入数据状态或计算结果')
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise MultiAssetImportError(f'每次最多导入 {MAX_ROWS} 条记录')
            if len(cells) != len(headers):
                raise MultiAssetImportError(f'第 {reader.line_num} 行列数不匹配')
            values = {}
            for key, cell in zip(headers, cells, strict=True):
                cell = cell.strip()
                if not cell:
                    continue
                if key in NUMERIC:
                    try:
                        number = Decimal(cell)
                    except InvalidOperation as exc:
                        raise MultiAssetImportError(f'第 {reader.line_num} 行 {key} 须为数字') from exc
                    if not number.is_finite():
                        raise MultiAssetImportError(f'第 {reader.line_num} 行 {key} 须为有限数字')
                    values[key] = float(number)
                else:
                    values[key] = cell
            try:
                item = AssetInput.model_validate(values)
            except ValidationError as exc:
                error = exc.errors(include_input=False, include_url=False)[0]
                field = '.'.join(str(loc) for loc in error['loc'])
                raise MultiAssetImportError(
                    f'第 {reader.line_num} 行 {field} 无效：{error["msg"]}'
                ) from exc
            identity = item.code.upper()
            if identity in seen:
                raise MultiAssetImportError(f'第 {reader.line_num} 行代码重复')
            seen.add(identity)
            rows.append(item)
    except csv.Error as exc:
        raise MultiAssetImportError(f'CSV 格式错误（第 {reader.line_num} 行）') from exc
    if not rows:
        raise MultiAssetImportError('CSV 没有数据；为保护原记录，空文件不能覆盖已有类别')
    return rows


def _same_date(as_of: str, *values: str | None) -> bool:
    return all(value is not None and value == as_of for value in values)


def _trailing_year_start(end: date) -> date:
    try:
        previous = end.replace(year=end.year - 1)
    except ValueError:  # February 29 has no matching day in the previous year.
        previous = end.replace(year=end.year - 1, day=28)
    return previous + timedelta(days=1)


def calculate_metrics(category: str, row: AssetInput) -> tuple[dict, list[str]]:
    """All percentages are percentage points (5 means 5%), never fractions."""
    metrics = dict.fromkeys(_METRICS)
    warnings = []
    if category in _NAV_CATEGORIES:
        if (row.price is not None and row.nav is not None
                and row.nav_currency == row.currency
                and _same_date(row.as_of, row.price_as_of, row.nav_as_of)):
            metrics['nav_premium_pct'] = (row.price / row.nav - 1) * 100
        else:
            warnings.append('净值溢价未计算：需价格、净值、相同币种及一致的价格/净值/基准日期。')
    elif category == 'ah':
        if (row.price is not None and row.h_price is not None and row.fx_hkd_cny is not None
                and row.h_code and row.currency == 'CNY' and row.h_currency == 'HKD'
                and _same_date(row.as_of, row.price_as_of, row.h_price_as_of, row.fx_as_of)):
            metrics['ah_premium_pct'] = (row.price / (row.h_price * row.fx_hkd_cny) - 1) * 100
        else:
            warnings.append('A/H 溢价未计算：需人民币 A 股、港元 H 股及同日的每港元人民币汇率。')
    elif category == 'arbitrage':
        if (row.price is not None and row.deal_price is not None
                and row.deal_currency == row.currency
                and _same_date(row.as_of, row.price_as_of, row.deal_as_of)):
            metrics['deal_spread_pct'] = (row.deal_price / row.price - 1) * 100
        else:
            warnings.append('对价空间未计算：需现价、方案对价、相同币种及一致的对价/价格/基准日期。')
    elif category in {'dividends', 'reits'}:
        valid = (row.price is not None and row.dividend_per_share is not None
                 and row.dividend_currency == row.currency and row.dividend_period_start
                 and row.dividend_period_end and row.dividend_basis
                 and _same_date(row.as_of, row.price_as_of)
                 and row.dividend_period_end <= row.as_of)
        if valid and row.dividend_basis == 'trailing_12_months':
            end = date.fromisoformat(row.dividend_period_end)
            valid = (end.year > 1 and row.dividend_period_end == row.as_of
                     and row.dividend_period_start == _trailing_year_start(end).isoformat())
        if valid:
            metrics['dividend_yield_pct'] = row.dividend_per_share / row.price * 100
        else:
            warnings.append('股息率未计算：需同币种现金分红、价格日期和完整且不晚于基准日的分红期间。')
    if category == 'cash' and row.rate_pct is not None and not row.rate_basis:
        warnings.append('导入利率未注明口径，不可视作年化收益率。')
    if category == 'bonds' and row.yield_pct is not None and not row.yield_basis:
        warnings.append('导入收益率未注明口径，不可视作已核验的到期收益率。')
    return metrics, warnings


def _present(category, rows, *, mode, revision, updated_at):
    status = 'demo' if mode == 'demo' else 'imported' if rows else 'empty'
    output = []
    for row in rows:
        metrics, warnings = calculate_metrics(category, row)
        output.append({**row.model_dump(), 'data_status': status,
                       'metrics': metrics, 'warnings': warnings})
    return dict(schema_version=1, category=category, mode=mode, revision=revision,
                updated_at=updated_at, data_status=status, live_status='unavailable',
                rows=output, warnings=[
                    '虚构演示数据，仅展示操作与计算方式，不代表任何真实证券或投资机会。'
                    if mode == 'demo' else _BASE_WARNING,
                ])


def demo_rows(category: str) -> list[AssetInput]:
    spec = category_spec(category)
    common = dict(code=f'DEMO-{category.upper()}', name=f'虚构{spec["label"]}样本',
                  currency='CNY', source_name='内置虚构演示（非行情）',
                  as_of='2026-01-15', price=10.0, price_as_of='2026-01-15',
                  notes='完全虚构，不对应任何真实证券；不会写入导入数据。')
    extra = {}
    if category in _NAV_CATEGORIES:
        extra = dict(nav=10.5, nav_currency='CNY', nav_as_of='2026-01-15')
    elif category == 'arbitrage':
        extra = dict(event_type='虚构现金要约', deal_price=11.0, deal_currency='CNY', deal_as_of='2026-01-15',
                     event_date='2026-06-30')
    elif category == 'ah':
        extra = dict(h_code='DEMO-H', h_price=10.0, h_currency='HKD',
                     h_price_as_of='2026-01-15', fx_hkd_cny=0.88, fx_as_of='2026-01-15')
    elif category in {'dividends', 'reits'}:
        extra = dict(dividend_per_share=0.5, dividend_currency='CNY',
                     dividend_period_start='2025-01-16', dividend_period_end='2026-01-15',
                     dividend_basis='trailing_12_months')
    elif category == 'cash':
        extra = dict(rate_pct=1.5, rate_basis='虚构七日年化，仅作展示')
    elif category == 'ipo':
        extra = dict(issue_price=10.0, event_date='2026-02-01', subscription_status='虚构事件')
    elif category == 'bonds':
        extra = dict(yield_pct=2.5, yield_basis='虚构导入报价，未核验', maturity_date='2028-01-15')
    elif category == 'indices':
        extra = dict(change_pct=1.2, pe=12.0, pb=1.5)
    first = AssetInput(**common, **extra)
    alternative = {**common, **extra, 'code': f'DEMO-{category.upper()}-B',
                   'name': f'虚构{spec["label"]}对照', 'price': 8.0}
    if category in _NAV_CATEGORIES:
        alternative.update(nav=7.5)
    elif category == 'arbitrage':
        alternative.update(deal_price=7.0)
    elif category in {'dividends', 'reits'}:
        alternative.update(dividend_per_share=0.2)
    elif category == 'cash':
        alternative.update(rate_pct=2.1, income_per_10k=0.5)
    elif category == 'ipo':
        alternative.update(issue_price=12.0, event_date='2026-02-15')
    elif category == 'bonds':
        alternative.update(yield_pct=3.1)
    elif category == 'indices':
        alternative.update(change_pct=-0.8, pe=15.0)
    missing = {**common, 'code': f'DEMO-{category.upper()}-MISSING',
               'name': f'虚构{spec["label"]}待补全', 'price': None, 'price_as_of': None,
               'notes': '缺失输入保持空白；不会把缺失数值补成零或编造计算结果。'}
    return [first, AssetInput(**alternative), AssetInput(**missing)]


def _csv_output(category: str, rows: list[AssetInput]) -> str:
    fields = category_spec(category)['field_keys']
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(fields)
    for row in rows:
        cells = []
        for field in fields:
            value = getattr(row, field)
            # Spreadsheet applications execute formula-like text on CSV open.
            # Preserve actual numeric negatives while quoting untrusted text.
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            cells.append('' if value is None else value)
        writer.writerow(cells)
    return output.getvalue()


def csv_template(category: str) -> str:
    return _csv_output(category, [])


class MultiAssetService:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / 'multi_asset' / 'workspace.json'

    def _read(self) -> StoredWorkspace:
        try:
            if not self.path.exists():
                return StoredWorkspace(schema_version=1, revision='0')
            if self.path.stat().st_size > MAX_STORED_BYTES:
                raise ValueError('stored data exceeds limit')
            stored = StoredWorkspace.model_validate_json(self.path.read_text(encoding='utf-8'))
            if set(stored.categories) - set(CATEGORIES):
                raise ValueError('unknown stored category')
            for category, rows in stored.categories.items():
                codes = [row.code.upper() for row in rows]
                if len(codes) != len(set(codes)):
                    raise ValueError('duplicate stored identity')
                for row in rows:
                    if set(row.model_dump(exclude_none=True)) - set(CATEGORIES[category]['field_keys']):
                        raise ValueError('unexpected category field')
            return stored
        except (OSError, ValueError) as exc:
            raise MultiAssetStoreError('多资产存档不可读取或版本不兼容；已停止写入，请保留文件并检查备份。') from exc

    def snapshot(self, category: str, mode: str = 'imported') -> dict:
        category_spec(category)
        if mode == 'demo':
            return _present(category, demo_rows(category), mode=mode, revision='demo', updated_at=None)
        if mode != 'imported':
            raise MultiAssetImportError('数据模式须为 imported 或 demo')
        with _LOCK:
            stored = self._read()
        return _present(category, stored.categories.get(category, []), mode=mode,
                        revision=stored.revision, updated_at=stored.updated_at)

    def preview(self, category: str, csv_text: str, *, expected_revision: str) -> dict:
        rows = parse_csv(category, csv_text)
        with _LOCK:
            stored = self._read()
        if stored.revision != expected_revision:
            raise MultiAssetConflictError('资料已被其他操作更新，请刷新并重新预览导入。')
        result = _present(category, rows, mode='imported', revision=stored.revision,
                          updated_at=stored.updated_at)
        result['row_count'] = len(rows)
        result['warnings'].append('确认后将替换当前类别全部导入记录；其他类别保持原样。')
        return result

    def import_csv(self, category: str, csv_text: str, *, expected_revision: str) -> dict:
        rows = parse_csv(category, csv_text)
        with _LOCK:
            stored = self._read()
            if stored.revision != expected_revision:
                raise MultiAssetConflictError('资料已被其他操作更新，请刷新并重新预览导入。')
            categories = {**stored.categories, category: rows}
            updated = StoredWorkspace(schema_version=1, revision=str(uuid.uuid4()), categories=categories,
                                      updated_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
            text = updated.model_dump_json(indent=2)
            if len(text.encode('utf-8')) > MAX_STORED_BYTES:
                raise MultiAssetImportError('合并后的存档超过 16 MiB；请缩小导入清单。')
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(self.path, text)
            except OSError as exc:
                raise MultiAssetStoreError('保存失败；原存档保持不变，请检查磁盘空间与目录权限。') from exc
        return _present(category, rows, mode='imported', revision=updated.revision,
                        updated_at=updated.updated_at)

    def export_csv(self, category: str) -> str:
        category_spec(category)
        with _LOCK:
            stored = self._read()
        return _csv_output(category, stored.categories.get(category, []))
