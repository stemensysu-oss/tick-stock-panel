"""Personal CB calculations with explicit inputs and reused financial math.

Public reference snapshots and persisted manual research remain separate. This
service builds a read-only presentation; only settings/research save via CAS.
"""
from __future__ import annotations

import math
from datetime import date

from app.services.convertibles_calculation_config import (
    FORMULAS,
    INPUTS,
    ConvertibleCalculationSettings,
)
from app.services.convertibles_expression import FormulaError, MissingInputError, evaluate_formulas
from app.services.convertibles_math import (
    _quote_date,
    conversion_option_value,
    dated_irr,
    discounted_value,
)
from app.services.convertibles_models import ConvertibleItem, DatedCashFlow


def calculate_personal(item: ConvertibleItem, as_of: str | None,
                       settings: ConvertibleCalculationSettings | None = None,
                       reference=None, *, market_quote_full=False):
    global_settings = settings or ConvertibleCalculationSettings()
    research = item.research
    personal = research.calculation_settings if research else None
    layers = [config for config in (global_settings, personal) if config and config.enabled]
    formulas = {key: definition[2] for key, definition in FORMULAS.items()}
    parameters, price_basis, cashflow_source = {}, 'auto', 'auto'
    for config in layers:
        formulas.update(config.formulas)
        parameters.update(config.parameters)
        price_basis = config.price_basis or price_basis
        cashflow_source = config.cashflow_source or cashflow_source
    ref = reference
    def value(name):
        return getattr(ref, name, None) if ref is not None else None
    maturity = item.maturity_date or value('maturity_date')
    remaining_days = (date.fromisoformat(maturity) - date.fromisoformat(as_of)).days if maturity and as_of else None
    context = dict.fromkeys(INPUTS)
    context.update(
        bond_price=item.bond_price, purchase_price=None, stock_price=item.stock_price, day_count_basis=365.0,
        conversion_price=item.conversion_price, face_value=item.face_value,
        remaining_days=remaining_days, float_market_cap=item.float_market_cap if item.float_market_cap is not None else value('float_market_cap'),
        outstanding_units=value('outstanding_units'), provided_outstanding_amount=item.outstanding_amount,
        source_stock_pb=item.stock_pb if item.stock_pb is not None else value('stock_pb'),
        source_stock_volatility_pct=item.stock_volatility_pct,
        source_fund_holding_pct=item.fund_holding_pct,
        source_call_trigger_price=value('call_trigger_price'), source_put_trigger_price=value('put_trigger_price'),
        call_trigger_ratio_pct=(research.call_clause.trigger_ratio_pct if research and research.call_clause else item.call_trigger_ratio_pct),
        put_trigger_ratio_pct=(research.put_clause.trigger_ratio_pct if research and research.put_clause else item.put_trigger_ratio_pct),
    )
    if research:
        for key in ('discount_rate_pct', 'risk_free_rate_pct', 'dividend_yield_pct', 'accrued_interest'):
            current = getattr(research, key)
            if current is not None:
                context[key] = current
    # Global defaults yield to saved single-bond parameters; a personal config
    # can override its own legacy fields explicitly.
    legacy = {key: context[key] for key in ('discount_rate_pct', 'risk_free_rate_pct', 'dividend_yield_pct', 'accrued_interest') if context[key] is not None}
    context.update(parameters)
    for key, current in legacy.items():
        if not (personal and personal.enabled and key in personal.parameters):
            context[key] = current
    warnings = list(item.analysis_warnings)
    for key, stamp in (('bond_price', item.quote_at), ('stock_price', item.stock_quote_at)):
        if as_of and stamp and _quote_date(stamp) > as_of and key not in parameters:
            context[key] = None
            warnings.append('含计算日之后的报价，相关公式未采用该输入。')
    if price_basis == 'auto':
        price_basis = research.price_basis if research and research.price_basis else 'full' if market_quote_full else None
    purchase = context['purchase_price'] if context['purchase_price'] is not None else context['bond_price']
    price_missing = None
    if price_basis == 'full':
        context['full_price'] = purchase
    elif price_basis == 'clean' and context['accrued_interest'] is not None and purchase is not None:
        context['full_price'] = purchase + context['accrued_interest']
    else:
        price_missing = 'accrued_interest' if price_basis == 'clean' else 'price_basis'
    plan = value('cashflow_plan') or {}
    manual_present = bool(research and research.cash_flows)
    use_manual = cashflow_source == 'manual' or (cashflow_source == 'auto' and manual_present)
    if use_manual:
        flows = list(research.cash_flows) if research else []
        complete = bool(research and research.cash_flows_complete and flows and maturity and max(f.date for f in flows) == maturity)
        basis = '手工确认现金流' if complete else '人工现金流未确认完整'
        flow_missing = ['cash_flows_complete']
    else:
        flows = [DatedCashFlow.model_validate(f) for f in plan.get('cash_flows', [])]
        complete = plan.get('status') == 'available' and bool(flows)
        basis = plan.get('basis', '合同计划现金流未取得')
        flow_missing = ['contract_cash_flows']
        if complete:
            warnings.extend(plan.get('warnings', []))
    if not as_of:
        complete = False
        flow_missing.append('as_of')
    def require_flows():
        if not complete:
            raise MissingInputError(flow_missing)
    def checked_basis(basis):
        if not 1 <= basis <= 366:
            raise FormulaError('年计息天数须为1至366')
        return basis
    def pv(discount, day_basis=365):
        require_flows()
        checked_basis(day_basis)
        if discount <= -100:
            raise FormulaError('年有效折现率必须大于-100%')
        annual_365 = math.expm1(math.log1p(discount / 100) * 365 / day_basis) * 100
        result = discounted_value(flows, as_of, annual_365)
        if result is None:
            raise FormulaError('折现率或未来现金流不适用')
        return result
    def irr(price, day_basis=365):
        require_flows()
        checked_basis(day_basis)
        if price_missing:
            raise MissingInputError([price_missing])
        result = dated_irr(price, flows, as_of)
        if result is None:
            raise FormulaError('缺少未来收款或收益率超出可表达范围')
        return math.expm1(math.log1p(result) * day_basis / 365)
    def put_irr(price, day_basis=365):
        checked_basis(day_basis)
        if not (research and research.put_cash_flows_complete and research.put_cash_flows and as_of):
            raise MissingInputError(['put_cash_flows_complete'])
        if maturity and max(f.date for f in research.put_cash_flows) > maturity:
            raise FormulaError('回售现金流不能晚于到期日')
        if price_missing:
            raise MissingInputError([price_missing])
        result = dated_irr(price, research.put_cash_flows, as_of)
        if result is None:
            raise FormulaError('回售情景无法计算')
        return math.expm1(math.log1p(result) * day_basis / 365)
    def future_flows():
        require_flows()
        return sorted((flow for flow in flows if flow.date > as_of), key=lambda f: f.date)
    def indexed_flow(index):
        ordered = future_flows()
        if not index.is_integer() or not 1 <= index <= len(ordered):
            raise MissingInputError([f'cash_flow_{index:g}'])
        return ordered[int(index) - 1]
    def bs(stock, strike, years, volatility, rate, dividend, face):
        result = conversion_option_value(stock_price=stock, conversion_price=strike, years=years,
            volatility_pct=volatility, risk_free_rate_pct=rate, dividend_yield_pct=dividend, face_value=face)
        if result is None:
            raise FormulaError('期权参数不在适用范围')
        return result
    details = evaluate_formulas(formulas, context, {'pv': pv, 'irr': irr, 'put_irr': put_irr, 'bs_call': bs,
        'cf_count': lambda: len(future_flows()), 'cf_amount': lambda i: indexed_flow(i).amount,
        'cf_days': lambda i: (date.fromisoformat(indexed_flow(i).date) - date.fromisoformat(as_of)).days})
    updates, invalid = {}, set()
    for key, detail in details.items():
        label, unit, default = FORMULAS[key]
        custom = formulas[key] != default
        detail.update(label=label, unit=unit, custom=custom,
            source='个人公式' if custom else '默认公式', cashflow_basis=basis if key in {'pure_bond_value', 'ytm_pct'} else None)
        result = detail['result']
        bad_dependencies = [name for name in detail['inputs'] if name in invalid]
        if bad_dependencies:
            detail.update(result=None, status='missing', missing=bad_dependencies)
            result = None
        if result is not None and key in {'stock_volatility_pct', 'outstanding_amount', 'pure_bond_value', 'option_value', 'remaining_years'} and result < 0:
            detail.update(result=None, status='error', error='该指标不能为负数')
        if result is not None and key == 'fund_holding_pct' and not 0 <= result <= 100:
            detail.update(result=None, status='error', error='持仓比例须为0至100的百分数')
        if detail['status'] != 'ok':
            invalid.add(key)
        if key in {'ytm_pct', 'put_yield_pct'} and detail['status'] == 'missing' and price_missing:
            detail['missing'] = sorted(set(detail['missing'] + [price_missing]))
        updates[key] = detail['result']
    if ref is not None:
        updates.update(maturity_date=maturity, credit_rating=item.credit_rating or value('credit_rating'),
            float_market_cap=context['float_market_cap'], conversion_start_date=item.conversion_start_date or value('conversion_start_date'))
    if parameters or any(d['custom'] for d in details.values()):
        warnings.append('包含个人参数或自定义公式，只代表个人研究情景，不修改机构评级或供应商原始资料。')
    if not use_manual and complete:
        warnings.append('到期收益按合同计划、税前全额收款情景计算；不保证持有期间不会转股、提前赎回或出现违约。')
    if any(stamp and as_of and stamp[:10] != as_of for stamp in (value('stock_metrics_quote_at'), value('valuation_date'))):
        warnings.append('公开参考指标日期与清单计算日可能不同，当前快照不能作为历史时点可得数据。')
    return item.model_copy(update={**updates, 'calculation_details': details, 'calculation_basis': basis,
        'personal_rating': research.personal_rating if research else None,
        'analysis_warnings': list(dict.fromkeys(warnings))})
