"""Public backup contracts use synthetic securities; never execute feed scripts."""
import json
from datetime import datetime

import httpx
import pytest

from app.data_providers.research_market import SH, ResearchMarketService
from app.data_providers.research_public_backup import PublicBackupProvider, bond_metadata


def quote(symbol='sh110001', *, price='110.5', stamp=None):
    fields = [''] * 50
    fields[1], fields[2], fields[3] = 'Test Bond', symbol[2:], price
    fields[30] = stamp if stamp is not None else datetime.now(SH).strftime('%Y%m%d%H%M%S')
    fields[32], fields[37] = '0.12', '999'  # Amount units deliberately not assumed.
    return f'v_{symbol}="' + '~'.join(fields) + '";'


class HTTP:
    def __init__(self, callback):
        self.callback = callback

    def get(self, url, params=None):
        data = self.callback(url, params)
        if isinstance(data, bytes):
            return httpx.Response(200, content=data)
        return httpx.Response(200, json=data)


def test_tencent_keeps_explicit_date_percent_units_and_unknown_amount():
    http = HTTP(lambda *args: quote().encode('gb18030'))
    rows = PublicBackupProvider(http).quotes(['110001.SH'])
    assert len(rows) == 1
    assert rows[0].symbol == '110001.SH'
    assert rows[0].price == 110.5
    assert rows[0].change_pct == 0.12
    assert rows[0].amount is None
    assert rows[0].source == 'tencent_public'
    assert datetime.fromisoformat(rows[0].quote_at).utcoffset() is not None


@pytest.mark.parametrize('data', [quote(price='0'), quote(stamp='11:30:00'), quote('sh110002')])
def test_zero_price_missing_date_or_unrequested_symbol_is_never_filled(data):
    assert PublicBackupProvider(HTTP(lambda *args: data.encode())).quotes(['110001.SH']) == []


def test_gbk_names_decode_without_replacement():
    body = quote().replace('Test Bond', '合成转债').encode('gb18030')
    assert PublicBackupProvider(HTTP(lambda *args: body)).quotes(['110001.SH'])[0].name == '合成转债'


def test_catalog_count_mismatch_is_disclosed_and_no_time_is_invented():
    def response(url, params):
        return '3' if url.endswith('Count') else [
            {'symbol': 'sh110001', 'name': 'Test', 'ticktime': '11:30:00'},
            {'symbol': 'sz123001', 'name': 'Test', 'ticktime': '11:30:00'},
        ]
    provider = PublicBackupProvider(HTTP(response))
    assert provider._catalog('test') == ['110001.SH', '123001.SZ']
    assert '2 条' in provider.coverage_notes[0] and '3 条' in provider.coverage_notes[0]


def test_bond_catalog_excludes_unlisted_delisted_matured_and_unsupported_market():
    common = {'SECUCODE': '110001.SH', 'LISTING_DATE': '2020-01-01 00:00:00',
              'EXPIRE_DATE': '2099-01-01', 'DELIST_DATE': None,
              'CONVERT_STOCK_CODE': '600001', 'TRANSFER_PRICE': 9.5}
    rows = [common, {**common, 'SECUCODE': '110002.SH', 'LISTING_DATE': None},
            {**common, 'SECUCODE': '110003.SH', 'DELIST_DATE': '2020-01-01'},
            {**common, 'SECUCODE': '110004.SH', 'EXPIRE_DATE': '2020-01-01'},
            {**common, 'SECUCODE': '810001.BJ'}]
    data = bond_metadata(HTTP(lambda *args: {'result': {'pages': 1, 'data': rows}}))
    assert list(data) == ['110001.SH']
    assert data['110001.SH'] == {'f232': '600001', 'f234': None, 'f235': 9.5}


def test_primary_success_prevents_all_public_backup_requests(monkeypatch):
    from app.data_providers import research_market as sources
    expected = PublicBackupProvider(HTTP(lambda *args: quote().encode())).quotes(['110001.SH'])
    monkeypatch.setattr(sources.TickFlowResearchProvider, 'quotes', lambda *args: expected)
    monkeypatch.setattr(PublicBackupProvider, 'quotes', lambda *args: pytest.fail('must not call public backup'))
    monkeypatch.setattr(sources.EastmoneyMarketProvider, 'quotes', lambda *args: pytest.fail('must not call Eastmoney'))
    result = ResearchMarketService().fetch('quotes', ['110001.SH'])
    assert len(result.attempts) == 1
    assert result.attempts[0]['provider'] == 'tickflow'
    assert json.loads(json.dumps(result.attempts))[0]['status'] == 'success'
