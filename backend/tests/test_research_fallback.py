"""Fallback order, provenance, missing fields, bounded parsing and safe writes."""
import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.custom.funds.fallback import EastmoneyFundProvider, FallbackFundProvider
from app.custom.funds.models import FundNavPoint, FundNavResponse
from app.data_providers.research_market import (
    PUBLIC,
    SH,
    MarketBatch,
    MarketRow,
    PublicHTTP,
    ResearchMarketService,
    ResearchSourceError,
)
from app.services.convertibles_fallback import FallbackConvertibleProvider
from app.services.convertibles_models import ConvertibleItem
from app.services.convertibles_research import ConvertibleConflictError, ConvertibleService
from app.services.convertibles_sources import ConvertibleQuoteService

TIME = '2026-10-21T15:00:00+08:00'


def row(symbol='110001.SH', source='tickflow', price=110.0):
    return MarketRow(symbol, '合成测试资产', price, TIME, source)


class Provider:
    def __init__(self, name, value, calls):
        self.name, self.value, self.calls = name, value, calls

    def quotes(self, argument):
        self.calls.append((self.name, argument))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value

    market = quotes


def test_primary_success_never_calls_either_fallback():
    calls = []
    service = ResearchMarketService([Provider('tickflow', [row()], calls),
        Provider('fuyao', RuntimeError('secret'), calls), Provider(PUBLIC, [], calls)])
    result = service.fetch('quotes', ['110001.SH'])
    assert calls == [('tickflow', ['110001.SH'])]
    assert result.rows[0].source == 'tickflow'


def test_only_missing_symbols_progress_through_both_apis_then_public():
    calls = []
    service = ResearchMarketService([
        Provider('tickflow', [row()], calls), Provider('fuyao', [], calls),
        Provider(PUBLIC, [row('600001.SH', PUBLIC, 8)], calls)])
    result = service.fetch('quotes', ['110001.SH', '600001.SH'])
    assert calls == [('tickflow', ['110001.SH', '600001.SH']),
                     ('fuyao', ['600001.SH']), (PUBLIC, ['600001.SH'])]
    assert [a['status'] for a in result.attempts] == ['success', 'empty', 'success']
    assert result.rows[0].price == 110
    assert result.warnings


def test_failures_missing_configuration_and_unsupported_are_distinct_and_safe():
    calls = []
    service = ResearchMarketService([Provider('tickflow', PermissionError(), calls),
        Provider('fuyao', NotImplementedError(), calls), Provider(PUBLIC, [row(source=PUBLIC)], calls)])
    result = service.fetch('market', 'bonds')
    assert [a['status'] for a in result.attempts] == ['unconfigured', 'unsupported', 'success']
    with pytest.raises(ResearchSourceError, match='所有可用数据源'):
        ResearchMarketService([Provider('bad', RuntimeError('PRIVATE-KEY'), [])]).fetch('market', 'etf')


def test_empty_watchlist_refresh_populates_real_source_records_and_cas_protects_imports(tmp_path, monkeypatch):
    batch = MarketBatch([row(source=PUBLIC)], TIME, [])
    monkeypatch.setattr('app.services.convertibles_fallback.market_batch', lambda *a, **k: batch)
    store = ConvertibleService(tmp_path)
    result = ConvertibleQuoteService(FallbackConvertibleProvider()).refresh(store, expected_revision='0')
    assert result.items[0].bond_price == 110
    assert result.items[0].quote_source == PUBLIC
    assert result.items[0].stock_code is None
    assert result.items[0].maturity_date is None
    original = store.path.read_bytes()
    with pytest.raises(ConvertibleConflictError):
        store.initialize_market([ConvertibleItem(code='110002', name='其他')], '2026-10-21',
                                'test', expected_revision=result.revision)
    assert store.path.read_bytes() == original


def test_discovery_failure_preserves_empty_file_state(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ResearchSourceError('网络不可用')
    monkeypatch.setattr('app.services.convertibles_fallback.market_batch', fail)
    store = ConvertibleService(tmp_path)
    with pytest.raises(Exception, match='网络不可用'):
        ConvertibleQuoteService(FallbackConvertibleProvider()).refresh(store, expected_revision='0')
    assert not store.path.exists()


class FundHTTP:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        result = self.handler(url, params)
        return httpx.Response(200, json=result) if isinstance(result, dict) else httpx.Response(200, text=result)


def test_nav_follows_actual_twenty_row_pages_and_never_substitutes_cumulative_nav():
    today = datetime.now(SH).date().isoformat()
    def handler(url, params):
        page = params['pageIndex']
        # Synthetic dates are unique and in the requested range.
        from datetime import timedelta
        dates = [(datetime.now(SH).date() - timedelta(days=i)).isoformat() for i in range(21)]
        selected = dates[:20] if page == 1 else dates[20:]
        return {'ErrCode': 0, 'PageSize': 20, 'TotalCount': 21,
                'Data': {'LSJZList': [{'FSRQ': day, 'DWJZ': '1.2', 'LJJZ': '9.9'} for day in selected]}}
    http = FundHTTP(handler)
    result = EastmoneyFundProvider(http).nav('000001.OF', 'month')
    assert len(result.items) == 21
    assert len(http.calls) == 2
    assert all(point.adj_nav is None for point in result.items)
    assert result.items[-1].date == today


def test_partial_nav_pagination_fails_instead_of_silently_truncating():
    http = FundHTTP(lambda *a: {'ErrCode': 0, 'TotalCount': 21, 'Data': {'LSJZList': []}})
    with pytest.raises(Exception, match='分页不完整'):
        EastmoneyFundProvider(http).nav('000001.OF', 'month')


def test_holdings_uses_only_latest_table_and_preserves_unknown_publication_date():
    html = '<h4>报告</h4>截止至：<font>2026-06-30</font>'
    table = '<table><tr><th>股票代码</th><th>股票名称</th><th>占净值比例</th></tr>'
    html += table + '<tr><td><a href="//quote.eastmoney.com/unify/r/0.000001">000001</a></td><td>测试</td><td>0.12%</td></tr></table>'
    html += '截止至：<font>2026-03-31</font>' + table + '<tr><td>000002</td><td>旧报告</td><td>7%</td></tr></table>'
    http = FundHTTP(lambda *a: 'var apidata={content:' + json.dumps(html) + ',arryear:[2026]};')
    result = EastmoneyFundProvider(http).holdings('000001.OF')
    assert len(result.items) == 1
    assert result.items[0].ticker == '000001.SZ'
    assert result.items[0].weight_pct == 0.12
    assert result.items[0].report_date == '2026-06-30'
    assert result.items[0].publish_date is None
    assert result.stock_ratio_pct is None


@pytest.mark.parametrize('primary_state', ['success', 'empty', 'failed'])
def test_fund_dataset_fallback_only_after_empty_or_failed_primary(primary_state):
    calls = []
    def primary(*args):
        calls.append('fuyao')
        if primary_state == 'failed':
            raise ValueError('PRIVATE-KEY')
        return FundNavResponse(ticker='000001.OF', provider='fuyao', range='month',
                               items=[FundNavPoint(date='2026-10-21', unit_nav=1)] if primary_state == 'success' else [])
    def fallback(*args):
        calls.append(PUBLIC)
        return FundNavResponse(ticker='000001.OF', provider=PUBLIC, range='month', items=[])
    result = FallbackFundProvider(primary=SimpleNamespace(nav=primary),
        fallback=SimpleNamespace(nav=fallback), key_getter=lambda: '').nav('000001.OF', 'month')
    assert calls == (['fuyao'] if primary_state == 'success' else ['fuyao', PUBLIC])
    assert 'PRIVATE-KEY' not in result.model_dump_json()

def test_http_gzip_stream_is_not_decoded_twice_and_never_sends_authorization(monkeypatch):
    import gzip
    import io
    response = io.BytesIO(gzip.compress(b'{"ok":true}'))
    response.headers = {'Content-Encoding': 'gzip', 'Content-Type': 'application/json'}
    def open_public(request, timeout):
        assert not request.has_header('Authorization')
        assert not request.has_header('Cookie')
        assert request.full_url.startswith('https://push2.eastmoney.com/')
        return response
    monkeypatch.setattr('app.data_providers.research_market.build_opener',
                        lambda *args: SimpleNamespace(open=open_public))
    assert PublicHTTP().get('https://push2.eastmoney.com/api/qt/clist/get').json() == {'ok': True}


def test_public_requests_reject_unknown_hosts_before_opening_network():
    with pytest.raises(ResearchSourceError, match='不支持'):
        PublicHTTP().get('https://example.com/')


def test_market_snapshot_does_not_modify_imported_research(tmp_path, monkeypatch):
    from app.services import multi_asset_market
    from app.services.multi_asset import MultiAssetService
    store = MultiAssetService(tmp_path)
    csv = 'code,name,currency,source_name,as_of\nTEST,用户资料,CNY,手工,2026-10-21\n'
    store.import_csv('etf', csv, expected_revision='0')
    original = store.path.read_bytes()
    monkeypatch.setattr(multi_asset_market, 'market_batch', lambda *a, **k: MarketBatch([row(source=PUBLIC)], TIME, []))
    result = multi_asset_market.snapshot('etf')
    assert result['rows'][0]['data_status'] == 'market'
    assert result['rows'][0]['quote_at'] == TIME
    assert result['rows'][0]['nav'] is None
    assert result['rows'][0]['metrics']['nav_premium_pct'] is None
    assert store.path.read_bytes() == original
