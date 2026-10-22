from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import HTTPException
from test_watchlist_enriched_join import _FakeRepo, _make_request

from app.api import kline
from app.api import watchlist as api
from app.data_providers import research_hk_search as search
from app.data_providers.research_market import MarketBatch, MarketRow, ResearchSourceError
from app.services import watchlist_hk as hk


@pytest.fixture(autouse=True)
def caches():
    hk._CACHE.clear()
    hk._GOOD.clear()
    yield
    hk._CACHE.clear()
    hk._GOOD.clear()


def batch(price=512.5, currency='HKD', symbol='00700.HK'):
    return MarketBatch([MarketRow(symbol, '腾讯控股', price, '2026-10-22T15:55:00+08:00',
        'tencent_public', change_pct=1.25, extra={'currency': currency})],
        '2026-10-22T16:01:00+08:00', [{'provider': 'tencent_public', 'status': 'success'}])


class Service:
    def __init__(self, result=None):
        self.result = result or batch()
        self.calls = []

    def fetch(self, operation, symbols):
        self.calls.append((operation, symbols))
        return self.result


def test_fractional_change_and_provenance_no_mainland_indicators():
    service = Service()
    data = hk.quote_snapshot(['600000.SH', '00700.HK', '00700.HK'], service=service)
    assert service.calls == [('quotes', ['00700.HK'])]
    row = data['rows'][0]
    assert row['close'] == 512.5 and row['change_pct'] == .0125
    assert row['currency'] == 'HKD' and row['asset_type'] == 'hk'
    assert row['quote_at'] == '2026-10-22T15:55:00+08:00'
    assert row['quote_fetched_at'] != row['quote_at']
    assert row['turnover_rate'] is None and row['amount'] is None
    assert not {'rsi14', 'limit_up_price'} & row.keys()
    data['rows'][0]['close'] = 0
    assert hk.cached_rows(['00700.HK'])[0]['close'] == 512.5


@pytest.mark.parametrize('price,currency', [(0,'HKD'), (-1,'HKD'), (float('nan'),'HKD'),
    (float('inf'),'HKD'), (True,'HKD'), (1,'CNY'), (1,None)])
def test_invalid_price_or_unverified_currency_rejected(price,currency):
    with pytest.raises(ResearchSourceError):
        hk.quote_snapshot(['00700.HK'], service=Service(batch(price,currency)))
    assert hk.cached_rows(['00700.HK'])[0]['close'] is None


def test_cache_force_and_failure_preserve_last_good(monkeypatch):
    service = Service()
    monkeypatch.setattr(hk, 'ResearchMarketService', lambda: service)
    hk.quote_snapshot(['00700.HK'])
    hk.quote_snapshot(['00700.HK'])
    assert len(service.calls) == 1
    hk.quote_snapshot(['00700.HK'], force=True)
    assert len(service.calls) == 2
    monkeypatch.setattr(service, 'fetch', lambda *a: (_ for _ in ()).throw(ResearchSourceError('offline')))
    with pytest.raises(ResearchSourceError):
        hk.quote_snapshot(['00700.HK'], force=True)
    assert hk.cached_rows(['00700.HK'])[0]['close'] == 512.5


def test_partial_missing_retains_stale_quote():
    hk.quote_snapshot(['00700.HK'], service=Service())
    data = hk.quote_snapshot(['00700.HK','00480.HK'],service=Service(batch(1,'HKD','00480.HK')))
    old = next(r for r in data['rows'] if r['symbol'] == '00700.HK')
    assert old['close'] == 512.5 and old['quote_status'] == 'stale'
    assert data['warnings']


@pytest.mark.parametrize('query', ['00700', '00700.HK', 'hk00700'])
def test_explicit_hk_search_never_falls_back_to_a_share_substrings(monkeypatch,query):
    monkeypatch.setattr(search,'search_hk',lambda *a: {'results': [], 'warnings': ['offline']})
    repo = SimpleNamespace(get_instruments_asset=lambda *a: pytest.fail('must not query mainland cache'))
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))
    data = kline.search_instruments(req,q=query,limit=20,asset_types='stock,etf,index,hk')
    assert data['results'] == [] and data['warnings'] == ['offline']


def test_mainland_search_does_not_invoke_hk(monkeypatch):
    monkeypatch.setattr(search,'search_hk',lambda *a: pytest.fail('HK not requested'))
    repo=SimpleNamespace(get_instruments_asset=lambda *a: pl.DataFrame({'symbol':['600700.SH'],
         'code':['600700'],'name':['实际A股']}))
    req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))
    assert kline.search_instruments(req,q='600700',limit=20,asset_types='stock')['results'][0]['symbol']=='600700.SH'


def test_enriched_hk_is_memory_only_and_no_mainland_indicator_leak(monkeypatch):
    monkeypatch.setattr(api.watchlist,'list_symbols',lambda:[{'symbol':'00700.HK'}])
    monkeypatch.setattr(hk,'ResearchMarketService',lambda:pytest.fail('no network on enriched/SSE path'))
    repo=_FakeRepo(pl.DataFrame({'symbol':['00700.HK'],'close':[1.], 'rsi14':[99.]}),'2026-10-22')
    row=api.watchlist_enriched(_make_request(repo),ext_columns=None)['rows'][0]
    assert row['symbol']=='00700.HK' and row['asset_type']=='hk' and row['close'] is None
    assert row.get('rsi14') is None and row.get('limit_up_price') is None


def test_hk_endpoint_error_is_explicit_502(monkeypatch):
    monkeypatch.setattr(api.watchlist,'list_symbols',lambda:[{'symbol':'00700.HK'}])
    monkeypatch.setattr(hk,'quote_snapshot',lambda *a,**kw:(_ for _ in ()).throw(ResearchSourceError('offline')))
    with pytest.raises(HTTPException) as exc:
        api.hk_quotes(force=True)
    assert exc.value.status_code==502
