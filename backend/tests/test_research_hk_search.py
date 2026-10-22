"""HK name/code discovery is global, bounded, source-aware and cache-safe."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.data_providers import research_hk_search as search
from app.data_providers.research_market import SH, MarketBatch, MarketRow, ResearchSourceError

_ORIGINAL_DIRECTORY = search._tickflow_directory


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    for cache in (search._QUERY_CACHE, search._DIRECTORY_CACHE, search._KNOWN_NAMES):
        cache.clear()
    monkeypatch.setattr(search, '_tickflow_directory', lambda: (_ for _ in ()).throw(PermissionError()))


def result(symbol='00700.HK', name='腾讯控股', source='tencent_public'):
    return dict(symbol=symbol, code=symbol[:5], name=name, asset_type='hk', source=source)


@pytest.mark.parametrize('value', ['00700', '00700.HK', 'hk00700', ' HK00700 '])
def test_exact_codes_use_primary_quote_chain_and_actual_name_without_suggestions(value, monkeypatch):
    now = datetime.now(SH).isoformat()
    row = MarketRow('00700.HK', '实际证券名称', 100., now, 'tickflow', extra={'currency': 'HKD'})
    batch = MarketBatch([row], now, [{'provider': 'tickflow', 'status': 'success', 'rows': 1}], [])
    calls = []
    class Primary:
        def fetch(self, operation, symbols):
            calls.append((operation, symbols))
            return batch
    monkeypatch.setattr(search, 'ResearchMarketService', Primary)
    monkeypatch.setattr(search, '_public_tencent', lambda *a: pytest.fail('primary succeeded'))
    data = search.search_hk(value)
    assert calls == [('quotes', ['00700.HK'])]
    assert data['results'][0] == result(name='实际证券名称', source='tickflow')
    assert 'price' not in data['results'][0] and 'currency' not in data['results'][0]
    assert search.known_name('hk00700') == '实际证券名称'


def test_primary_metadata_name_match_prevents_public_search(monkeypatch):
    monkeypatch.setattr(search, '_tickflow_directory', lambda: [result(source='tickflow')])
    monkeypatch.setattr(search, '_public_tencent', lambda *a: pytest.fail('metadata succeeded'))
    data = search.search_hk('腾讯')
    assert data['results'] == [result(source='tickflow')]
    assert [a['provider'] for a in data['attempts']] == ['tickflow']


def test_public_search_has_no_500_universe_limit(monkeypatch):
    outside = result('00480.HK', '香港兴业国际')
    monkeypatch.setattr(search, '_public_tencent', lambda q: [outside])
    data = search.search_hk('香港兴业')
    assert data['results'] == [outside]
    assert [a['provider'] for a in data['attempts']] == ['tickflow', 'fuyao', 'tencent_public']
    assert [a['status'] for a in data['attempts']] == ['unconfigured', 'unsupported', 'success']
    assert any('500' in w for w in data['warnings'])


def test_branded_alias_is_disclosed_but_actual_security_name_is_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(search, '_public_tencent', lambda q: calls.append(q) or [result()])
    data = search.search_hk('腾讯科技')
    assert calls == ['腾讯']
    assert data['resolved_query'] == '腾讯'
    assert data['results'][0]['name'] == '腾讯控股'
    assert any('品牌简称' in w and '实际证券资料' in w for w in data['warnings'])


def test_tencent_safe_unicode_parser_filters_other_markets_warrants_and_duplicates():
    body = r'v_hint="hk~00700~\u817e\u8baf\u63a7\u80a1~txkg~GP^hk~00700~duplicate~x~GP^hk~13000~权证~x~QZ^sh~600000~浦发银行~pfyh~GP"'
    assert search.parse_tencent_suggestions(body) == [result()]
    with pytest.raises(ResearchSourceError):
        search.parse_tencent_suggestions('v_hint="hk~00700~name~x~GP";malicious();')


def test_sina_parser_requires_actual_hk_code_and_market():
    body = 'var suggestvalue="hk00480,2,00480,hk00480,香港兴业国际,,29536,HK;sh600480,2,600480,sh600480,凌云股份,,432,A股";'
    assert search.parse_sina_suggestions(body) == [result('00480.HK', '香港兴业国际', 'sina_public')]
    with pytest.raises(ResearchSourceError):
        search.parse_sina_suggestions('eval("untrusted")')


def test_sina_runs_only_after_empty_or_failed_tencent(monkeypatch):
    monkeypatch.setattr(search, '_public_tencent', lambda q: (_ for _ in ()).throw(ResearchSourceError('offline')))
    monkeypatch.setattr(search, '_public_sina', lambda q: [result(source='sina_public')])
    data = search.search_hk('腾讯')
    assert data['results'][0]['source'] == 'sina_public'
    assert [a['status'] for a in data['attempts']][-2:] == ['failed', 'success']


def test_exact_quote_failure_can_still_discover_suspended_security_name(monkeypatch):
    monkeypatch.setattr(search, 'ResearchMarketService', lambda: SimpleNamespace(fetch=lambda *a: (_ for _ in ()).throw(ResearchSourceError('no quote'))))
    monkeypatch.setattr(search, '_public_tencent', lambda q: [result(), result('00701.HK', 'Other')])
    data = search.search_hk('00700')
    assert data['results'] == [result()]
    assert data['attempts'][0]['dataset'] == 'hk_exact_quote'


def test_success_cache_is_deepcopied_and_empty_results_are_retryable(monkeypatch):
    calls = []
    monkeypatch.setattr(search, '_public_tencent', lambda q: calls.append(q) or [result()])
    data = search.search_hk('腾讯')
    data['results'][0]['name'] = 'client mutation'
    assert search.search_hk('腾讯')['results'][0]['name'] == '腾讯控股'
    assert calls == ['腾讯']
    search._QUERY_CACHE.clear()
    monkeypatch.setattr(search, '_public_tencent', lambda q: [])
    monkeypatch.setattr(search, '_public_sina', lambda q: [])
    assert search.search_hk('NotFound')['results'] == []
    assert ('NotFound', 20) not in search._QUERY_CACHE


@pytest.mark.parametrize('query,limit', [('',20),('x'*51,20),('bad\nquery',20),('Tencent',0),('Tencent',51),('Tencent',True)])
def test_invalid_or_unbounded_inputs_rejected(query, limit):
    with pytest.raises(ValueError):
        search.search_hk(query,limit)


def test_query_cache_and_known_name_memory_are_bounded(monkeypatch):
    monkeypatch.setattr(search, '_public_tencent', lambda q: [result()])
    for i in range(140):
        search.search_hk(f'query{i}')
    assert len(search._QUERY_CACHE) == 128
    search._remember([result(f'{i:05d}.HK', f'Actual {i}') for i in range(1005)])
    assert len(search._KNOWN_NAMES) == 1000
    assert search.known_name('00000.HK') is None
    assert search.known_name('01004.HK') == 'Actual 1004'


def test_documented_tickflow_full_hk_metadata_api_is_cached_independent_of_500_list(monkeypatch):
    calls = []
    def load(exchange, instrument_type=None):
        calls.append((exchange, instrument_type))
        return [dict(symbol='00480.HK', name='香港兴业国际'),
                dict(symbol='00700.HK', name='腾讯控股')]
    client = SimpleNamespace(exchanges=SimpleNamespace(get_instruments=load), close=lambda: calls.append('closed'))
    monkeypatch.setattr('tickflow.TickFlow', lambda **kwargs: client)
    monkeypatch.setattr('app.secrets_store.get_tickflow_key', lambda: 'synthetic-key')
    monkeypatch.setattr('app.secrets_store.load', lambda: {})
    assert _ORIGINAL_DIRECTORY()[0] == result('00480.HK', '香港兴业国际', 'tickflow')
    assert len(_ORIGINAL_DIRECTORY()) == 2
    assert calls == [('HK', 'stock'), 'closed']


def test_empty_search_result_does_not_make_network_known_name_lookup(monkeypatch):
    monkeypatch.setattr(search, '_public_tencent', lambda *a: pytest.fail('cache lookup must not use network'))
    assert search.known_name('00480.HK') is None
