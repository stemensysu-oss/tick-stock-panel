from types import SimpleNamespace

import pytest

from app.data_providers.research_market import MarketBatch, MarketRow
from app.services import multi_asset_market
from app.services.multi_asset import MultiAssetService
from app.services.multi_asset_models import AssetInput


@pytest.mark.parametrize('category', ['ah', 'dividends', 'ipo', 'qdii'])
def test_dataset_snapshot_preserves_event_evidence_and_import_isolation(category, tmp_path, monkeypatch):
    row = AssetInput(code='TEST', name='测试事件', currency='CNY',
                     source_name='测试已获取来源', source_url='https://example.test/data',
                     as_of='2026-10-22', event_date='2026-10-23')
    batch = SimpleNamespace(rows=[row], fetched_at='2026-10-22T16:00:00+08:00',
                            attempts=[{'provider': 'test', 'status': 'success'}],
                            warnings=['测试覆盖范围'], metadata=[{'source_id': 'test',
                            'event_source_date': '2026-10-21', 'price': 99, 'metrics': {}}])
    monkeypatch.setattr(multi_asset_market, '_specialized_batch', lambda *a: batch)
    result = multi_asset_market.snapshot(category, force=True)
    assert result['data_status'] == 'market'
    output = result['rows'][0]
    assert output['data_status'] == 'market' and output['source_id'] == 'test'
    assert output['event_date'] == '2026-10-23' and output['price'] is None
    assert output['metrics']['ah_premium_pct'] is None
    assert 'quote_at' not in output  # An event date is not a quote timestamp.
    assert result['warnings'] == ['测试覆盖范围']
    store = MultiAssetService(tmp_path)
    assert not store.path.exists() and store.snapshot(category)['data_status'] == 'empty'


def test_hong_kong_snapshot_uses_hkd_and_canonical_code(monkeypatch):
    quote = MarketRow('00700.HK', '腾讯控股', 600.0, '2026-10-22T16:08:00+08:00',
                      'tencent_public', change_pct=2.0, extra={'currency': 'HKD'})
    batch = MarketBatch([quote], '2026-10-22T16:10:00+08:00', [])
    monkeypatch.setattr(multi_asset_market, 'market_batch', lambda *a, **k: batch)
    result = multi_asset_market.snapshot('hk')
    row = result['rows'][0]
    assert row['code'] == '00700.HK' and row['currency'] == 'HKD'
    assert row['change_pct'] == 2.0 and row['price'] == 600
    assert row['source_url'] == 'https://quote.eastmoney.com/hk/00700.html'
    assert row['quote_at'] == quote.quote_at


def test_unsupported_event_category_is_not_replaced_with_stock_quotes(monkeypatch):
    monkeypatch.setattr(multi_asset_market, 'market_batch', lambda *a, **k: pytest.fail('wrong dataset'))
    result = multi_asset_market.snapshot('arbitrage')
    assert result['data_status'] == 'empty' and result['live_status'] == 'unavailable'
