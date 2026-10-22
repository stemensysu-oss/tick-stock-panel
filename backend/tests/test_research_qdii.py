import json
from pathlib import Path

import pytest

from app.data_providers.research_market import MarketBatch, MarketRow, ResearchSourceError
from app.data_providers.research_qdii import QUERY, parse_directory, qdii_batch


class Http:
    def __init__(self, payload=None, fail=False):
        self.payload, self.fail = payload, fail

    def get(self, url, params):
        assert params == QUERY and params['SWING_TRADE'] == '是'
        if self.fail:
            raise TimeoutError
        return self

    def json(self):
        return self.payload


class Quotes:
    def fetch(self, operation, symbols):
        assert operation == 'quotes'
        self.symbols = symbols
        return MarketBatch([MarketRow(symbols[0], '测试跨境 ETF', 2.5,
                                     '2026-10-22T15:00:00+08:00', 'tickflow')],
                           '2026-10-22T15:01:00+08:00',
                           [{'provider': 'tickflow', 'status': 'success', 'rows': 1}])


def test_directory_uses_explicit_classification_not_names():
    rows = parse_directory({'result': [
        {'FUND_CODE': '513100', 'FUND_ABBR': '没有 QDII 关键词', 'CATEGORY': 'F131'},
        {'FUND_CODE': '510300', 'FUND_ABBR': 'QDII T+0 跨境', 'CATEGORY': 'F111'},
        {'FUND_CODE': '501225', 'FUND_ABBR': '跨境 LOF', 'CATEGORY': 'F214'},
    ]})
    assert [row['code'] for row in rows] == ['513100', '501225']


@pytest.mark.parametrize('result', [[], None, [
    {'FUND_CODE': 'bad', 'FUND_ABBR': '基金', 'CATEGORY': 'F131'}], [
    {'FUND_CODE': '513100', 'FUND_ABBR': '基金', 'CATEGORY': 'F131'},
    {'FUND_CODE': '513100', 'FUND_ABBR': '基金', 'CATEGORY': 'F131'}]])
def test_bad_directory_fails_closed(result):
    with pytest.raises(ResearchSourceError):
        parse_directory({'result': result})


def test_quotes_use_existing_priority_router_and_nav_stays_unknown():
    quotes = Quotes()
    batch = qdii_batch(http=Http({'result': [
        {'FUND_CODE': '513100', 'FUND_ABBR': '纳指ETF', 'CATEGORY': 'F131'}]}), service=quotes)
    assert quotes.symbols == ['513100.SH']
    assert batch.rows[0].price == 2.5
    assert batch.rows[0].nav is None and batch.rows[0].subscription_status is None
    assert batch.metadata[0]['source_id'] == 'tickflow'
    assert batch.metadata[0]['eligibility_status'] == 'exchange_listed'
    assert batch.attempts[-1]['provider'] == 'tickflow'
    assert '非全部沪深' in batch.warnings[-1]


def test_failed_directory_snapshot_is_disclosed_and_contains_no_saved_quotes():
    quotes = Quotes()
    batch = qdii_batch(http=Http(fail=True), service=quotes)
    assert batch.rows and len(quotes.symbols) == 142
    assert batch.metadata[0]['eligibility_status'] == 'snapshot_pending_verification'
    assert batch.metadata[0]['eligibility_as_of'] == '2026-10-22'
    assert '资格待复核' in batch.rows[0].notes
    assert '本次网络取数成功' in batch.warnings[-1]
    snapshot = json.loads((Path(__file__).parents[1] / 'app/data_providers/research_qdii_catalog.json').read_text(encoding='utf-8'))
    assert all(set(row) == {'code', 'name', 'category'} for row in snapshot['rows'])
