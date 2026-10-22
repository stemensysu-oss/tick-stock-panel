"""Network snapshots are independent of the imported research file."""
from app.data_providers.research_market import FILTERS, LABELS, PUBLIC, market_batch
from app.services.multi_asset import _present, category_spec
from app.services.multi_asset_models import AssetInput


def snapshot(category, *, force=False):
    category_spec(category)
    if category not in FILTERS:
        return dict(schema_version=1, category=category, mode='market', revision='market',
                    updated_at=None, data_status='empty', live_status='unavailable', rows=[],
                    attempts=[], warnings=['本类别尚无已集成且可靠的事件/配对数据集。请切换“我的导入数据”维护研究；不会用普通股票行情冒充套利事件、A/H 配对或申购公告。'])
    batch = market_batch(category, force=force)
    rows = []
    for row in batch.rows:
        extra = {'change_pct': row.change_pct} if category == 'indices' else {}
        rows.append(AssetInput(
            code=row.symbol, name=row.name, currency='CNY',
            source_name=LABELS.get(row.source, row.source),
            source_url=(f'https://quote.eastmoney.com/{row.symbol[-2:].lower()}{row.symbol[:6]}.html'
                        if row.source == PUBLIC else 'https://docs.tickflow.org/zh-Hans'),
            as_of=row.quote_at[:10], price=row.price, price_as_of=row.quote_at[:10],
            notes=('当前债券市场清单仅覆盖沪深可转债，不是全债市。' if category == 'bonds'
                   else '仅场内货币 ETF 价格，不是收益率。' if category == 'cash'
                   else '市场行情快照；净值、事件与财务字段需独立数据集。'), **extra))
    result = _present(category, rows, mode='market', revision='market', updated_at=batch.fetched_at)
    result.update(data_status='market', live_status='available', attempts=batch.attempts,
                  warnings=batch.warnings)
    for output, raw in zip(result['rows'], batch.rows, strict=True):
        output.update(data_status='market', quote_at=raw.quote_at, fetched_at=batch.fetched_at,
                      source_id=raw.source)
    return result
