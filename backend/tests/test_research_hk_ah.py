"""HK currency, independent A/H dates, priority and explicit directory contracts."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.data_providers import research_ah as ah
from app.data_providers import research_market as market
from app.data_providers.research_public_backup import PublicBackupProvider
from app.services.multi_asset import _present


class HTTP:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        value = self.body(url, params) if callable(self.body) else self.body
        return httpx.Response(200, content=value if isinstance(value, bytes) else value.encode())


def hk_quote(currency='HKD', *, symbol='00700', price='100', stamp=None):
    fields = [''] * 78
    fields[1:4] = ['合成港股', symbol, price]
    fields[30] = stamp or datetime.now(market.SH).strftime('%Y/%m/%d %H:%M:%S')
    fields[32], fields[75] = '1.25', currency
    return f'v_hk{symbol}="' + '~'.join(fields) + '";'


def test_hk_quote_requires_explicit_hkd_currency_and_preserves_source_time():
    provider = PublicBackupProvider(HTTP(hk_quote().encode('gb18030')))
    rows = provider.quotes(['00700.HK'])
    assert len(rows) == 1 and rows[0].price == 100
    assert rows[0].symbol == '00700.HK'
    assert rows[0].extra['currency'] == 'HKD'
    assert rows[0].change_pct == 1.25
    assert '15 分钟' in rows[0].extra['quote_delay_note']
    assert rows[0].amount is None  # Currency and amount unit not guessed.


@pytest.mark.parametrize('currency', ['CNY', 'USD', ''])
def test_hk_other_counter_currency_is_not_mislabeled(currency):
    assert PublicBackupProvider(HTTP(hk_quote(currency).encode('gb18030'))).quotes(['00700.HK']) == []


def test_hk_stale_time_or_wrong_symbol_is_not_filled():
    for body in [hk_quote(stamp='13:30:00'), hk_quote(symbol='00005'), hk_quote(price='0')]:
        assert PublicBackupProvider(HTTP(body.encode('gb18030'))).quotes(['00700.HK']) == []


def test_hk_catalog_uses_bounded_actual_directory_and_discloses_coverage():
    def get(url, params):
        return httpx.Response(200, json=[{'symbol': '00700'}, {'symbol': '80000'}, {'symbol': 'bad'}])
    provider = PublicBackupProvider(SimpleNamespace(get=get))
    assert provider.hk_catalog() == ['00700.HK', '80000.HK']
    assert '500' in provider.coverage_notes[0]


def test_tickflow_hk_is_not_silently_discarded_but_currency_is_required(monkeypatch):
    now = int(datetime.now(market.SH).timestamp() * 1000)
    raw = [dict(symbol='00700.HK', name='测试', last_price=100, timestamp=now,
                currency='HKD', ext={'change_pct': .01}),
           dict(symbol='80000.HK', last_price=10, timestamp=now, ext={})]
    client = SimpleNamespace(quotes=SimpleNamespace(get=lambda **kwargs: raw), close=lambda: None)
    monkeypatch.setattr('tickflow.TickFlow', lambda **kwargs: client)
    monkeypatch.setattr('app.secrets_store.get_tickflow_key', lambda: 'synthetic-test-key')
    monkeypatch.setattr('app.secrets_store.load', lambda: {})
    monkeypatch.setattr(PublicBackupProvider, 'quotes', lambda *args: [])
    rows = market.TickFlowResearchProvider().market('hk')
    assert [r.symbol for r in rows] == ['00700.HK']
    assert rows[0].extra['currency'] == 'HKD'
    assert rows[0].change_pct == 1.0


def fx_body(rate='0.85', *, pair='HKDCNY', day=None):
    day = day or datetime.now(market.SH).strftime('%Y-%m-%d')
    fields = [''] * 22
    fields[2], fields[3], fields[5], fields[21] = pair, rate, day.replace('-', '') + '120000', day
    return ('v_whHKDCNY="' + '~'.join(fields) + '";').encode()


def test_fx_direction_and_independent_date_are_explicit():
    data = ah.public_fx(HTTP(fx_body()))
    assert data['value'] == 0.85
    assert data['quote_at'].endswith('12:00:00+08:00')
    assert '人民币/港元' in data['source_name']


@pytest.mark.parametrize('body', [fx_body('8.5'), fx_body(pair='CNYHKD'), b'v_whHKDCNY="unknown";'])
def test_fx_bad_direction_missing_timestamp_or_wrong_pair_rejected(body):
    with pytest.raises((market.ResearchSourceError, ValueError)):
        ah.public_fx(HTTP(body))


def test_pair_directory_uses_explicit_link_codes_not_names_or_inferred_digits():
    body = ''.join(f'<tr><td><a title="{i:06d}.SH">a</a></td>'
                   f'<td><a title="{i:05d}.HK">h</a></td></tr>' for i in range(10, 20))
    assert len(ah.parse_pairs(body)) == 10
    with pytest.raises(market.ResearchSourceError):
        ah.parse_pairs('<tr><td>same name 600001</td><td>same name 00001</td></tr>')


def ah_service(monkeypatch, h_day=None, fx_day=None):
    today = datetime.now(market.SH).date().isoformat()
    h_day, fx_day = h_day or today, fx_day or today
    monkeypatch.setattr(ah, 'public_pairs', lambda _: ([('600001.SH', '00001.HK')], [], []))
    monkeypatch.setattr(ah, 'public_fx', lambda _: dict(value=.85, quote_at=fx_day+'T12:00:00+08:00',
        source='tencent_public', source_name='腾讯参考汇率', source_url=ah.FX_URL))
    batch = market.MarketBatch([
        market.MarketRow('600001.SH', '合成配对', 10., today+'T13:00:00+08:00', 'tickflow'),
        market.MarketRow('00001.HK', '合成配对', 10., h_day+'T12:45:00+08:00', 'tencent_public',
                         extra={'currency': 'HKD'}),
    ], today, [{'provider': 'tickflow', 'status': 'success', 'rows': 1},
               {'provider': 'fuyao', 'status': 'unsupported'},
               {'provider': 'tencent_public', 'status': 'success', 'rows': 1}], [])
    return ah.AHService(market=SimpleNamespace(fetch=lambda *args: batch), http=HTTP(b''))


def test_ah_valid_same_day_formula_and_separate_leg_provenance(monkeypatch):
    batch = ah_service(monkeypatch).fetch()
    result = _present('ah', batch.rows, mode='market', revision='market', updated_at=batch.fetched_at)
    assert result['rows'][0]['metrics']['ah_premium_pct'] == pytest.approx((10 / (10*.85)-1)*100)
    assert batch.metadata[0]['a_source_id'] == 'tickflow'
    assert batch.metadata[0]['h_source_id'] == 'tencent_public'
    assert batch.metadata[0]['fx_quote_at'] != batch.metadata[0]['quote_at']
    assert [a['provider'] for a in batch.attempts[-3:]] == ['tickflow', 'fuyao', 'tencent_public']


def test_ah_mismatched_date_preserves_legs_but_never_calculates_premium(monkeypatch):
    yesterday = (datetime.now(market.SH) - timedelta(days=1)).date().isoformat()
    batch = ah_service(monkeypatch, h_day=yesterday).fetch()
    result = _present('ah', batch.rows, mode='market', revision='market', updated_at=batch.fetched_at)
    assert result['rows'][0]['metrics']['ah_premium_pct'] is None
    assert batch.rows[0].h_price == 10
    assert batch.rows[0].h_price_as_of == yesterday
    assert batch.metadata[0]['comparison_status'] == 'unavailable'
    assert any('不一致' in w for w in batch.warnings)


def test_ah_fx_failure_does_not_discard_valid_two_market_prices(monkeypatch):
    service = ah_service(monkeypatch)
    monkeypatch.setattr(ah, 'public_fx', lambda _: (_ for _ in ()).throw(market.ResearchSourceError('offline')))
    batch = service.fetch()
    assert batch.rows[0].price == 10 and batch.rows[0].h_price == 10
    assert batch.rows[0].fx_hkd_cny is None
    assert batch.metadata[0]['comparison_status'] == 'unavailable'


def test_tickflow_successful_hk_price_is_retained_when_only_currency_needs_fallback(monkeypatch):
    now = datetime.now(market.SH)
    raw = [dict(symbol='00700.HK', last_price=123., timestamp=int(now.timestamp()*1000),
                ext={'name': '测试原价格'})]
    client = SimpleNamespace(quotes=SimpleNamespace(get=lambda **kwargs: raw), close=lambda: None)
    monkeypatch.setattr('tickflow.TickFlow', lambda **kwargs: client)
    monkeypatch.setattr('app.secrets_store.get_tickflow_key', lambda: 'synthetic-key')
    monkeypatch.setattr('app.secrets_store.load', lambda: {})
    currency_row = market.MarketRow('00700.HK', '公开报价', 99., now.isoformat(), 'tencent_public',
                                    extra={'currency': 'HKD'})
    monkeypatch.setattr(PublicBackupProvider, 'quotes', lambda *args: [currency_row])
    batch = market.ResearchMarketService().fetch('quotes', ['00700.HK'])
    assert batch.rows[0].price == 123.  # Public price 99 must never overwrite it.
    assert batch.rows[0].source == 'tickflow'
    assert batch.rows[0].extra['currency_source'] == 'tencent_public'
    assert batch.rows[0].name == '测试原价格'
    assert len([a for a in batch.attempts if a.get('dataset') == 'quote_currency']) == 3
    assert not any(a['provider'] == 'sina_tencent_public' for a in batch.attempts)
    assert any('未采用补充源价格' in w for w in batch.warnings)


def test_hk_directory_snapshot_supplies_codes_only_and_still_needs_live_quotes(monkeypatch):
    provider = PublicBackupProvider(HTTP(b''))
    monkeypatch.setattr(provider, '_live_hk_catalog', lambda: (_ for _ in ()).throw(market.ResearchSourceError('offline')))
    codes = provider.hk_catalog()
    assert len(codes) == 500 and all(__import__('re').fullmatch(r'\d{5}\.HK', c) for c in codes)
    assert any('2026-10-22' in w and '当次获取' in w for w in provider.coverage_notes)
    monkeypatch.setattr(provider, 'quotes', lambda *args: [])
    assert provider.market('hk') == []
