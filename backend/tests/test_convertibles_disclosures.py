import httpx
import pytest

from app.services.convertibles_disclosures import ConvertibleDisclosureProvider


def source(row):
    class HTTP:
        def get(self, url, params):
            rows = [row] if params['reportName'] == 'RPT_BOND_CB_LIST' else []
            return httpx.Response(200, json={'success': True, 'result': {'data': rows, 'count': len(rows)}})
    return ConvertibleDisclosureProvider(HTTP())


def base():
    return {'SECURITY_CODE': '113063', 'SECUCODE': '113063.SH', 'SECURITY_NAME_ABBR': '合成债券',
        'LISTING_DATE': '2022-11-24 00:00:00', 'PAR_VALUE': 100, 'IS_REDEEM': '是',
        'INTEREST_RATE_EXPLAIN': '第一年0.30%', 'COUPON_IR': 1.5, 'CASHFLOW_DATE': '2026-11-02 00:00:00'}


def test_clause_existence_never_means_call_implementation():
    result = source(base()).fetch('113063', today='2026-10-22')
    assert result.lifecycle == 'listed'
    assert result.call_state == 'unknown'
    assert not hasattr(result, 'cash_flows')
    assert [a['status'] for a in result.attempts] == ['unsupported', 'unsupported', 'success']


def test_terminated_bond_does_not_use_original_future_cashflows():
    row = {**base(), 'DELIST_DATE': '2024-02-23 00:00:00', 'NOTICE_DATE_SH': '2024-01-25 00:00:00',
        'EXECUTE_START_DATESH': '2024-02-23 00:00:00', 'EXECUTE_PRICE_SH': 100.155}
    result = source(row).fetch('113063', today='2026-10-22')
    assert result.lifecycle == 'terminated'
    assert result.call_state == 'historical_implementation'
    assert result.call_price == 100.155
    assert any('退市' in text for text in result.warnings)


def test_identity_mismatch_is_rejected():
    with pytest.raises(ValueError):
        source({**base(), 'SECUCODE': '113063.SZ'}).fetch('113063')


def test_optional_important_date_failure_is_explicit_and_never_leaks_supplier_error():
    class HTTP:
        def get(self, url, params):
            if params['reportName'] == 'RPT_CB_IMPORTANTDATE':
                raise RuntimeError('sensitive-supplier-details')
            return httpx.Response(200, json={'success': True,
                'result': {'data': [base()], 'count': 1}})

    result = ConvertibleDisclosureProvider(HTTP()).fetch('113063', today='2026-10-22')
    assert result.name == '合成债券'
    assert result.events == []
    assert any('重要日期接口' in warning for warning in result.warnings)
    assert 'sensitive-supplier-details' not in result.model_dump_json()


def test_disclosure_cache_is_bounded_by_time_and_isolates_callers(monkeypatch):
    from app.services import convertibles_disclosures as module

    calls = []
    original = ConvertibleDisclosureProvider.fetch

    def fetch(self, symbol):
        calls.append(symbol)
        return original(source(base()), symbol, today='2026-10-22')

    module._cached.cache_clear()
    monkeypatch.setattr(module.ConvertibleDisclosureProvider, 'fetch', fetch)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 3000)
    try:
        first = module.disclosures('113063')
        first.warnings.append('caller-owned edit')
        second = module.disclosures('113063')
        assert 'caller-owned edit' not in second.warnings
        assert calls == ['113063.SH']
        monkeypatch.setattr(module.time, 'monotonic', lambda: 3300)
        assert module.disclosures('113063').name == '合成债券'
        assert calls == ['113063.SH', '113063.SH']
    finally:
        module._cached.cache_clear()
