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
