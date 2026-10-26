"""Documented CB formulas and optional personal settings (no provider coupling)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.convertibles_expression import FormulaError, evaluate_formulas

# All percentages are percentage points; monetary inputs are CNY per 100 face.
FORMULAS = {
    'stock_pb': ('正股PB', '倍', 'source_stock_pb'),
    'stock_volatility_pct': ('正股波动率', '%', 'source_stock_volatility_pct'),
    'outstanding_amount': ('剩余本金规模', '元', 'COALESCE(provided_outstanding_amount, outstanding_units * face_value)'),
    'fund_holding_pct': ('基金持有比例', '%', 'source_fund_holding_pct'),
    'conversion_value': ('转股价值', '元/张', 'face_value * stock_price / conversion_price'),
    'conversion_premium_pct': ('转股溢价率', '%', '(bond_price / conversion_value - 1) * 100'),
    'double_low': ('双低', '点', 'bond_price + conversion_premium_pct'),
    'remaining_years': ('剩余年限', '年', 'MAX(remaining_days / day_count_basis, 0)'),
    'debt_to_float_cap_pct': ('本金/正股流通市值', '%', 'outstanding_amount / float_market_cap * 100'),
    'call_trigger_price': ('强赎触发价', '元', 'COALESCE(conversion_price * call_trigger_ratio_pct / 100, source_call_trigger_price)'),
    'put_trigger_price': ('回售触发价', '元', 'COALESCE(conversion_price * put_trigger_ratio_pct / 100, source_put_trigger_price)'),
    'pure_bond_value': ('个人纯债试算', '元/张', 'PV(discount_rate_pct, day_count_basis)'),
    'option_value': ('简化转股期权价值', '元/张', 'BS_CALL(stock_price, conversion_price, remaining_years, stock_volatility_pct, risk_free_rate_pct, dividend_yield_pct, face_value)'),
    'ytm_pct': ('到期税前收益率', '%', 'IRR(full_price, day_count_basis) * 100'),
    'put_yield_pct': ('回售情景收益率', '%', 'PUT_IRR(full_price, day_count_basis) * 100'),
}
INPUTS = {
    'bond_price': ('转债价格', '元/张'), 'purchase_price': ('个人买入价', '元/张'),
    'full_price': ('含息买入成本', '元/张'), 'accrued_interest': ('应计利息', '元/张'),
    'stock_price': ('正股价格', '元/股'), 'conversion_price': ('转股价', '元/股'),
    'face_value': ('面值', '元/张'), 'remaining_days': ('距到期自然日', '日'),
    'float_market_cap': ('正股流通市值', '元'), 'outstanding_units': ('转债存续张数', '张'),
    'provided_outstanding_amount': ('直接提供的剩余本金', '元'),
    'source_stock_pb': ('来源正股PB', '倍'),
    'source_stock_volatility_pct': ('来源或个人输入的年化波动率', '%'),
    'source_fund_holding_pct': ('带报告期的基金持有比例', '%'),
    'source_call_trigger_price': ('公开强赎触发参考价', '元/股'),
    'source_put_trigger_price': ('公开回售触发参考价', '元/股'),
    'call_trigger_ratio_pct': ('个人强赎触发比例', '%'),
    'put_trigger_ratio_pct': ('个人回售触发比例', '%'),
    'discount_rate_pct': ('年有效折现率', '%'),
    'base_discount_rate_pct': ('年有效基准折现率（个人）', '%'),
    'credit_spread_pct': ('年有效信用利差（个人，不改变机构评级）', '%'),
    'day_count_basis': ('年计息天数基准', '日/年'),
    'risk_free_rate_pct': ('连续年化无风险利率', '%'),
    'dividend_yield_pct': ('连续年化股息率', '%'),
    'book_value_per_share': ('个人每股净资产', '元/股'),
    'premium_weight': ('个人溢价权重', '倍'),
}
PARAMETERS = set(INPUTS) - {'full_price', 'face_value'}
FiniteParameter = Annotated[float, Field(ge=-1e18, le=1e18, allow_inf_nan=False, strict=True)]


class ConvertibleCalculationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool = True
    formulas: dict[str, Annotated[str, Field(min_length=1, max_length=512)]] = Field(default_factory=dict, max_length=32)
    parameters: dict[str, FiniteParameter] = Field(default_factory=dict, max_length=64)
    price_basis: Literal['auto', 'full', 'clean'] | None = None
    cashflow_source: Literal['auto', 'manual', 'contract'] | None = None

    @field_validator('formulas')
    @classmethod
    def supported_formulas(cls, values):
        if set(values) - FORMULAS.keys():
            raise ValueError('存在不支持修改的字段；机构评级及原始日期不是计算公式')
        return values

    @field_validator('parameters')
    @classmethod
    def supported_parameters(cls, values):
        if set(values) - PARAMETERS:
            raise ValueError('存在未声明的参数')
        for key, value in values.items():
            if key in {'bond_price', 'purchase_price', 'stock_price', 'conversion_price', 'call_trigger_ratio_pct', 'put_trigger_ratio_pct'} and value <= 0:
                raise ValueError(f'{INPUTS[key][0]}必须大于0')
            if key in {'accrued_interest', 'outstanding_units', 'provided_outstanding_amount', 'float_market_cap', 'source_stock_volatility_pct'} and value < 0:
                raise ValueError(f'{INPUTS[key][0]}不能为负数')
            if key == 'source_fund_holding_pct' and not 0 <= value <= 100:
                raise ValueError('基金持有比例须为0至100的百分数')
            if key == 'day_count_basis' and not 1 <= value <= 366:
                raise ValueError('年计息天数须为1至366')
            if key == 'discount_rate_pct' and value <= -100:
                raise ValueError('年有效折现率必须大于-100%')
        return values

    @model_validator(mode='after')
    def valid_formulas(self):
        formulas = {key: item[2] for key, item in FORMULAS.items()}
        formulas.update(self.formulas)
        try:
            # Unknown inputs and cycles are structural errors; missing values in
            # this validation context are expected and never a financial result.
            evaluate_formulas(formulas, dict.fromkeys(INPUTS))
        except FormulaError as exc:
            raise ValueError(str(exc)) from None
        return self


def calculation_catalog():
    return {
        'formulas': [{'id': key, 'label': label, 'unit': unit, 'formula': formula}
                     for key, (label, unit, formula) in FORMULAS.items()],
        'inputs': [{'id': key, 'label': label, 'unit': unit, 'editable': key in PARAMETERS}
                   for key, (label, unit) in INPUTS.items()],
        'functions': ['ABS', 'MIN', 'MAX', 'SQRT', 'LOG', 'EXP', 'ROUND', 'IF', 'COALESCE',
                      'PV', 'IRR', 'PUT_IRR', 'BS_CALL', 'CF_AMOUNT', 'CF_DAYS', 'CF_COUNT'],
        'function_docs': [
            {'name': 'PV(r, b=365)', 'formula': 'Σ CF_i / (1+r/100)^(d_i/b)',
             'note': '未来每张税前收款的折现和；r为年有效折现率百分数，b为年计息天数。'},
            {'name': 'IRR(P, b=365)', 'formula': '求 y，使 P = Σ CF_i/(1+y)^(d_i/b)',
             'note': '复用对数域二分根求解；返回小数收益率，显示百分数时乘100。'},
            {'name': 'CF_AMOUNT(i), CF_DAYS(i), CF_COUNT()',
             'formula': '未来现金流按日期升序排列，i从1开始',
             'note': '可将纯债公式展开为 CF_AMOUNT(1)/(1+discount_rate_pct/100)^(CF_DAYS(1)/day_count_basis)+…；越界不是零。'},
            {'name': 'BS_CALL(S,K,T,vol,r,q,F)',
             'formula': '(F/K)×[S×exp(-qT)×N(d1)-K×exp(-rT)×N(d2)]',
             'note': 'd1=[ln(S/K)+(r-q+vol²/2)T]/(vol√T)，d2=d1-vol√T；vol/r/q输入百分数，函数内部除100。'},
        ],
        'conventions': ['百分数20表示20%，金额为人民币元/张（面值100）或对应字段声明的单位。',
                        'PV按未来现金流、年有效折现率及ACT/365计算；IRR求含息买入成本等于未来现金流现值的年有效收益率。',
                        'BS_CALL为简化欧式转股期权，不含全部赎回、回售、下修及信用风险。LOG为自然对数。',
                        '机构评级是来源资料，不是报价计算结果；个人评级单独保存。',
                        '自定义公式仅影响个人研究显示，不改写供应商原始资料。'],
    }
