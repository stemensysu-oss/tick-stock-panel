from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.convertibles_calculation import calculate_personal
from app.services.convertibles_calculation_config import ConvertibleCalculationSettings
from app.services.convertibles_models import ConvertibleItem, ConvertibleResearch


def item(**kwargs):
    return ConvertibleItem(code='113052.SH', name='合成样本', bond_price=100.0, stock_price=10.0,
                           conversion_price=10.0, maturity_date='2027-10-26', **kwargs)


def reference():
    return SimpleNamespace(maturity_date='2027-10-26', outstanding_units=10000000,
                           float_market_cap=5000000000, stock_pb=1.2,
                           cashflow_plan={'status': 'available', 'basis': '合同计划情景',
                               'cash_flows': [{'date': '2027-10-26', 'amount': 105.0}], 'warnings': []})


def test_editable_day_basis_and_expanded_cashflow_formula_match_present_value():
    config = ConvertibleCalculationSettings(parameters={'discount_rate_pct': 5.0, 'day_count_basis': 360.0})
    default = calculate_personal(item(), '2026-10-26', config, reference(), market_quote_full=True)
    expanded = config.model_copy(update={'formulas': {'pure_bond_value': 'CF_AMOUNT(1)/(1+discount_rate_pct/100)^(CF_DAYS(1)/day_count_basis)'}})
    custom = calculate_personal(item(), '2026-10-26', expanded, reference(), market_quote_full=True)
    assert custom.pure_bond_value == pytest.approx(105 / 1.05 ** (365 / 360))
    assert custom.pure_bond_value == pytest.approx(default.pure_bond_value)
    assert custom.ytm_pct == pytest.approx((1.05 ** (360 / 365) - 1) * 100)


def test_personal_credit_spread_changes_value_without_changing_rating():
    settings = ConvertibleCalculationSettings(parameters={'base_discount_rate_pct': 4.0, 'credit_spread_pct': 2.0},
        formulas={'pure_bond_value': 'PV(base_discount_rate_pct + credit_spread_pct)'})
    result = calculate_personal(item(credit_rating='AAA'), '2026-10-26', settings, reference())
    assert result.pure_bond_value == pytest.approx(105 / 1.06)
    assert result.credit_rating == 'AAA'


def test_contract_plan_populates_yield_without_manufacturing_discount_rate_or_volatility():
    row = calculate_personal(item(), '2026-10-26', reference=reference(), market_quote_full=True)
    assert row.ytm_pct == pytest.approx(5)
    assert row.outstanding_amount == 1000000000
    assert row.debt_to_float_cap_pct == 20
    assert row.pure_bond_value is None and row.option_value is None
    assert row.calculation_details['pure_bond_value']['missing'] == ['discount_rate_pct']
    assert row.calculation_basis == '合同计划情景'


def test_personal_parameters_and_formulas_recompute_dependents_and_preserve_official_rating():
    settings = ConvertibleCalculationSettings(parameters={'discount_rate_pct': 5.0},
        formulas={'conversion_premium_pct': '(bond_price / conversion_value - 1) * 100 + 2'})
    original = item(credit_rating='AAA', research=ConvertibleResearch(personal_rating='AA'))
    row = calculate_personal(original, '2026-10-26', settings, reference(), market_quote_full=True)
    assert row.pure_bond_value == pytest.approx(100)
    assert row.double_low == pytest.approx(102)
    assert row.credit_rating == 'AAA' and row.personal_rating == 'AA'
    assert original.pure_bond_value is None and original.research.personal_rating == 'AA'
    assert row.calculation_details['conversion_premium_pct']['custom']


def test_single_bond_override_wins_and_old_cashflows_remain_authoritative():
    global_settings = ConvertibleCalculationSettings(parameters={'discount_rate_pct': 4.0})
    research = ConvertibleResearch(cash_flows=[{'date': '2027-10-26', 'amount': 110.0}],
        cash_flows_complete=True, price_basis='full', discount_rate_pct=10.0,
        calculation_settings=ConvertibleCalculationSettings(formulas={'double_low': 'bond_price + 7'}))
    row = calculate_personal(item(research=research), '2026-10-26', global_settings, reference())
    assert row.pure_bond_value == pytest.approx(100)
    assert row.ytm_pct == pytest.approx(10)
    assert row.double_low == 107 and row.calculation_basis == '手工确认现金流'


def test_incomplete_manual_flows_are_not_silently_replaced_by_plan():
    r = ConvertibleResearch(cash_flows=[{'date': '2027-10-26', 'amount': 110.0}], price_basis='full')
    row = calculate_personal(item(research=r), '2026-10-26', reference=reference())
    assert row.ytm_pct is None
    assert 'cash_flows_complete' in row.calculation_details['ytm_pct']['missing']


def test_clean_price_requires_interest_and_custom_settings_are_validated():
    c = ConvertibleCalculationSettings(price_basis='clean')
    row = calculate_personal(item(), '2026-10-26', c, reference())
    assert row.ytm_pct is None
    assert 'accrued_interest' in row.calculation_details['ytm_pct']['missing']
    for kwargs in ({'formulas': {'double_low': 'double_low+1'}}, {'formulas': {'credit_rating': '1'}},
                   {'parameters': {'unknown': 1.0}}):
        with pytest.raises(ValidationError):
            ConvertibleCalculationSettings(**kwargs)


def test_invalid_metric_cannot_produce_a_plausible_dependent_ratio():
    c = ConvertibleCalculationSettings(formulas={'outstanding_amount': '-100'})
    row = calculate_personal(item(), '2026-10-26', c, reference())
    assert row.outstanding_amount is None and row.debt_to_float_cap_pct is None
