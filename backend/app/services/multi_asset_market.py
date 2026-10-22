"""Network snapshots are independent of the imported research file."""
from app.data_providers.research_market import FILTERS, LABELS, PUBLIC, market_batch
from app.services.multi_asset import _present, category_spec
from app.services.multi_asset_models import AssetInput

LIVE_CATEGORIES = frozenset(FILTERS) | {'hk', 'dividends', 'ipo', 'ah', 'qdii'}


def _specialized_batch(category, force):
    if category in {'dividends', 'ipo'}:
        from app.data_providers.research_events import event_batch
        return event_batch(category, force=force)
    if category == 'ah':
        from app.data_providers.research_ah import ah_batch
        return ah_batch(force=force)
    from app.data_providers.research_qdii import qdii_batch
    return qdii_batch(force=force)


def _specialized_snapshot(category, *, force):
    batch = _specialized_batch(category, force)
    rows = [row if isinstance(row, AssetInput) else AssetInput.model_validate(row)
            for row in batch.rows]
    result = _present(category, rows, mode='market', revision='market', updated_at=batch.fetched_at)
    result.update(data_status='market' if rows else 'empty', live_status='available',
                  attempts=batch.attempts, warnings=batch.warnings)
    metadata = getattr(batch, 'metadata', [{} for _ in rows])
    if len(metadata) != len(rows):
        raise ValueError('数据来源明细与行数不一致')
    for output, evidence in zip(result['rows'], metadata, strict=True):
        # Metadata may add evidence, but cannot overwrite validated prices,
        # calculated metrics or source labels from the dataset contract.
        output.update({key: value for key, value in evidence.items() if key not in output})
        output.update(data_status='market', fetched_at=batch.fetched_at)
    return result


def snapshot(category, *, force=False):
    category_spec(category)
    if category in {'dividends', 'ipo', 'ah', 'qdii'}:
        return _specialized_snapshot(category, force=force)
    if category not in LIVE_CATEGORIES:
        return dict(schema_version=1, category=category, mode='market', revision='market',
                    updated_at=None, data_status='empty', live_status='unavailable', rows=[],
                    attempts=[], warnings=['本类别尚无已集成且可靠的事件/配对数据集。请切换“我的导入数据”维护研究；不会用普通股票行情冒充套利事件、A/H 配对或申购公告。'])
    batch = market_batch(category, force=force)
    rows = []
    for row in batch.rows:
        extra = {'change_pct': row.change_pct} if category in {'indices', 'hk'} else {}
        rows.append(AssetInput(
            code=row.symbol, name=row.name, currency='HKD' if row.symbol.endswith('.HK') else 'CNY',
            source_name=LABELS.get(row.source, row.source),
            source_url=(f'https://quote.eastmoney.com/hk/{row.symbol[:-3]}.html' if row.symbol.endswith('.HK') else
                        f'https://quote.eastmoney.com/{row.symbol[-2:].lower()}{row.symbol[:6]}.html'
                        if row.source == PUBLIC else
                        f'https://qt.gtimg.cn/q={row.symbol[-2:].lower()}{row.symbol[:6]}'
                        if row.source == 'tencent_public' else 'https://docs.tickflow.org/zh-Hans'),
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
        if raw.extra.get('currency_source'):
            output.update(quote_currency_source=raw.extra['currency_source'],
                          quote_currency_at=raw.extra.get('currency_quote_at'))
    return result
