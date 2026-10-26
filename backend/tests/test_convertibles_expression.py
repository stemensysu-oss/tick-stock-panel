import pytest

from app.services.convertibles_expression import FormulaError, MissingInputError, evaluate_formulas


def test_custom_dependencies_are_recalculated_in_order():
    result = evaluate_formulas({'premium': '(price / value - 1) * 100',
                               'value': 'face * stock / strike', 'double_low': 'price + premium * 0.8'},
                              {'price': 110, 'face': 100, 'stock': 10, 'strike': 10})
    assert result['premium']['result'] == pytest.approx(10)
    assert result['double_low']['result'] == pytest.approx(118)
    assert result['value']['inputs'] == {'face': 100, 'stock': 10, 'strike': 10}
    assert result['double_low']['formula'] == 'price + premium * 0.8'


def test_missing_is_distinct_from_zero_and_dependency_error_is_visible():
    r = evaluate_formulas({'value': '100 * stock / strike', 'next': 'value + 1'}, {'stock': 0, 'strike': None})
    assert r['value']['result'] is None and r['value']['status'] == 'missing'
    assert r['value']['missing'] == ['strike']
    assert r['next']['result'] is None
    r = evaluate_formulas({'value': 'stock * 100'}, {'stock': 0})
    assert r['value']['result'] == 0


def test_conditional_is_lazy_and_power_uses_spreadsheet_notation():
    r = evaluate_formulas({'value': 'IF(stock > 0, 100 / stock, 0)', 'power': '2 ^ 3'}, {'stock': 0})
    assert r['value']['result'] == 0 and r['power']['result'] == 8


@pytest.mark.parametrize('expr', [
    '__import__("os").system("anything")', '(1).__class__', '[x for x in [1]]',
    '(lambda: 1)()', 'open("x")', 'stock[0]', 'sum(range(100))', 'unknown + 1',
])
def test_executable_or_undeclared_syntax_is_rejected(expr):
    with pytest.raises(FormulaError):
        evaluate_formulas({'value': expr}, {'stock': 1})


def test_cycles_rejected_without_fallback_to_old_result():
    with pytest.raises(FormulaError, match='循环'):
        evaluate_formulas({'a': 'b+1', 'b': 'a+1'}, {})


@pytest.mark.parametrize('expr', ['10 ** 10000000', '1e309', '1/0', '(-1) ** 0.5'])
def test_nonfinite_or_unbounded_calculation_is_a_visible_error(expr):
    r = evaluate_formulas({'value': expr}, {})
    assert r['value']['result'] is None and r['value']['status'] == 'error'


def test_financial_helpers_can_report_required_data_and_preview_is_pure():
    inputs = {'discount': 3}
    def pv(rate):
        raise MissingInputError(['cash_flows_complete'])
    r = evaluate_formulas({'value': 'PV(discount)'}, inputs, {'pv': pv})
    assert r['value']['status'] == 'missing'
    assert r['value']['missing'] == ['cash_flows_complete']
    assert inputs == {'discount': 3}


def test_length_and_ast_size_have_hard_limits():
    with pytest.raises(FormulaError):
        evaluate_formulas({'value': '1+' * 300 + '1'}, {})
