import pytest

from app.services.convertibles_cashflows import contract_cash_flows


def terms():
    return {'VALUE_DATE': '2021-12-27', 'BOND_EXPIRE': '6', 'PAY_INTEREST_DAY': '12-27',
            'INTEREST_RATE_EXPLAIN': '第一年0.20%、第二年0.40%、第三年1.00%、第四年1.50%、第五年2.30%、第六年3.00%。',
            'REDEEM_CLAUSE': '到期赎回条款：按票面面值的109%(含最后一期利息)赎回。有条件赎回条款：130%。'}


def test_complete_plan_has_no_double_counted_final_coupon():
    plan = contract_cash_flows(terms(), '2027-12-27', 109, 'listed')
    assert plan['status'] == 'available'
    assert len(plan['cash_flows']) == 6
    assert plan['cash_flows'][-1] == {'date': '2027-12-27', 'amount': 109.0}
    assert plan['cash_flows'][4]['amount'] == 2.3
    assert '计划' in plan['basis']


@pytest.mark.parametrize('field,value', [
    ('INTEREST_RATE_EXPLAIN', '当前票面利率2.30%'),
    ('INTEREST_RATE_EXPLAIN', '第一年1%，第二年2%'),
    ('REDEEM_CLAUSE', '到期按照面值及利息支付'),
    ('REDEEM_CLAUSE', '按票面面值的112%(含最后一期利息)赎回'),
    ('PAY_INTEREST_DAY', '11-02'),
])
def test_incomplete_or_inconsistent_sources_do_not_invent_cashflows(field, value):
    row = {**terms(), field: value}
    plan = contract_cash_flows(row, '2027-12-27', 109, 'listed')
    assert plan['status'] == 'missing' and plan['cash_flows'] == [] and plan['reasons']


def test_terminated_or_announced_early_call_has_no_maturity_plan():
    assert contract_cash_flows(terms(), '2027-12-27', 109, 'terminated')['cash_flows'] == []
    row = {**terms(), 'NOTICE_DATE_SH': '2026-10-01', 'EXECUTE_START_DATESH': '2026-11-20'}
    assert contract_cash_flows(row, '2027-12-27', 109, 'listed')['cash_flows'] == []


def test_numeric_years_and_explicit_source_amount_are_supported():
    row = {**terms(), 'BOND_EXPIRE': '2', 'INTEREST_RATE_EXPLAIN': '第1年为0.5%，第2年为1.0%。',
           'REDEEM_CLAUSE': '到期赎回条款按面值的105%（含最后一期利息）赎回'}
    plan = contract_cash_flows(row, '2023-12-27', 105, 'listed')
    assert plan['status'] == 'available' and plan['cash_flows'][0]['amount'] == 0.5


def test_explicit_final_interest_year_wording_is_not_treated_as_missing():
    row = {**terms(), "REDEEM_CLAUSE": "到期以票面面值的109%(含最后一期计息年度利息)赎回"}
    assert contract_cash_flows(row, "2027-12-27", 109, "listed")["status"] == "available"
