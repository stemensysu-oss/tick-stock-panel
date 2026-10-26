import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.convertibles_reference import ConvertibleReferenceProvider


class HTTP:
    def __init__(self, *, terms=True, value=97.25, bad_identity=False, terminated=False):
        self.terms, self.value, self.bad_identity, self.terminated = terms, value, bad_identity, terminated
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, params))
        if params.get('reportName'):
            if not self.terms:
                raise RuntimeError('private supplier details')
            rows = [{'SECURITY_CODE': '113052', 'SECUCODE': '113052.SH', 'SECURITY_NAME_ABBR': '合成样本',
                     'PAR_VALUE': 100, 'EXPIRE_DATE': '2027-12-27 00:00:00', 'LISTING_DATE': '2022-01-14 00:00:00',
                     'DELIST_DATE': '2024-02-23 00:00:00' if self.terminated else None, 'RATING': 'AAA'}]
        elif params.get('type'):
            rows = [{'DATE': '2026-10-23 00:00:00', 'ZCODE': '113052',
                     'SECUCODE': '113063.SH' if self.bad_identity else '113052.SH',
                     'PUREBONDVALUE': self.value, 'FCLOSE': 110, 'PUREBONDOR': 13.11}]
        else:
            raise RuntimeError('quote temporarily unavailable')
        return httpx.Response(200, json={'success': True, 'result': {'data': rows, 'count': len(rows)}})


def test_reference_keeps_value_date_separate_and_never_builds_manual_cash_flows():
    h = HTTP()
    result = ConvertibleReferenceProvider(h).fetch(['113052'], today='2026-10-25')
    item = result.items[0]
    assert item.pure_bond_value == 97.25 and item.valuation_date == '2026-10-23'
    assert item.maturity_date == '2027-12-27'
    assert not hasattr(item, 'cash_flows')
    assert all(a['status'] == 'unsupported' for a in result.attempts[:2])
    assert '2026-10-23' in h.calls[2][1]['filter']
    assert 'private supplier' not in result.model_dump_json()


@pytest.mark.parametrize('value', [None, 0, '-', float('nan'), float('inf')])
def test_invalid_values_never_become_par_value(value):
    item = ConvertibleReferenceProvider(HTTP(value=value)).fetch(['113052'], today='2026-10-25').items[0]
    assert item.pure_bond_value is None
    assert item.maturity_date == '2027-12-27'
    assert item.warnings


def test_terminated_end_date_is_not_original_maturity_or_current_valuation():
    item = ConvertibleReferenceProvider(HTTP(terminated=True)).fetch(['113052'], today='2026-10-25').items[0]
    assert item.lifecycle == 'terminated'
    assert item.maturity_date is None and item.pure_bond_value is None
    assert item.source_end_date == '2027-12-27'


def test_wrong_security_valuation_rejected_while_terms_survive():
    result = ConvertibleReferenceProvider(HTTP(bad_identity=True)).fetch(['113052'], today='2026-10-25')
    assert result.items[0].pure_bond_value is None
    assert any(a['dataset'] == 'valuation' and a['status'] == 'failed' for a in result.attempts)


def test_value_can_load_independently_if_terms_unavailable():
    result = ConvertibleReferenceProvider(HTTP(terms=False)).fetch(['113052'], today='2026-10-25')
    assert result.items[0].maturity_date is None
    assert result.items[0].pure_bond_value == 97.25
    assert 'private supplier' not in result.model_dump_json()


def test_route_is_read_only_and_validates_requested_codes(monkeypatch):
    from app.custom import convertibles
    app = FastAPI()
    result = ConvertibleReferenceProvider(HTTP()).fetch(['113052'], today='2026-10-25')
    monkeypatch.setattr(convertibles, 'references', lambda codes: result)
    class Registrar:
        def include_router(self, router):
            app.include_router(router)
    convertibles.setup(Registrar())
    client = TestClient(app)
    body = client.post('/api/ext/convertibles/references', json={'codes': ['113052']})
    assert body.status_code == 200 and body.json()['items'][0]['valuation_date'] == '2026-10-23'
    assert client.post('/api/ext/convertibles/references', json={'codes': []}).status_code == 422
    assert client.post('/api/ext/convertibles/references', json={'codes': ['113052'], 'url': 'https://elsewhere'}).status_code == 422


def test_cache_does_not_share_mutable_results(monkeypatch):
    from app.services import convertibles_reference as module
    module._cached.cache_clear()
    calls = []
    result = ConvertibleReferenceProvider(HTTP()).fetch(['113052'], today='2026-10-25')
    def fetch(self, symbols):
        calls.append(symbols)
        return result
    monkeypatch.setattr(module.ConvertibleReferenceProvider, 'fetch', fetch)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 3000)
    try:
        first = module.references(['113052'])
        first.items[0].maturity_date = None
        assert module.references(['113052.SH']).items[0].maturity_date == '2027-12-27'
        assert len(calls) == 1
    finally:
        module._cached.cache_clear()
