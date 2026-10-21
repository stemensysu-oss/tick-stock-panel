"""Deterministic, source-independent convertible research calculations.

ACT/365 yields use dated, already combined, pre-tax cash flows. The optional
Black-Scholes estimate describes a European conversion option only, without
issuer call, put, downward revision, default or trading-friction assumptions.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.services.convertibles_models import (
    ClauseProgress,
    ConvertibleClause,
    ConvertibleInput,
    ConvertibleItem,
    ConvertibleObservation,
    DatedCashFlow,
    validate_date,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _future_flows(flows: list[DatedCashFlow], as_of: str) -> list[tuple[float, float]]:
    start = date.fromisoformat(as_of)
    return [
        ((date.fromisoformat(flow.date) - start).days / 365, flow.amount)
        for flow in flows if flow.date > as_of
    ]


def dated_irr(price: float, flows: list[DatedCashFlow], as_of: str) -> float | None:
    """Unique effective annual IRR for a purchase and positive future receipts.

    Search in log(1 + yield), not an arbitrarily truncated yield interval. A
    log-sum-exp objective prevents overflow near -100% and with short periods.
    Results that cannot be represented as a finite float above -1 stay unknown.
    """
    validate_date(as_of)
    future = _future_flows(flows, as_of)
    if not future or not math.isfinite(price) or price <= 0:
        return None
    log_price = math.log(price)

    def objective(log_yield: float) -> float:
        terms = [math.log(amount) - years * log_yield for years, amount in future]
        maximum = max(terms)
        return maximum + math.log(sum(math.exp(term - maximum) for term in terms)) - log_price

    low, high = -1.0, 1.0
    for _ in range(32):
        if objective(low) >= 0:
            break
        low *= 2
    else:
        return None
    for _ in range(32):
        if objective(high) <= 0:
            break
        high *= 2
    else:
        return None
    for _ in range(120):
        middle = (low + high) / 2
        if objective(middle) > 0:
            low = middle
        else:
            high = middle
    try:
        result = math.expm1((low + high) / 2)
    except OverflowError:
        return None
    return result if math.isfinite(result) and result > -1 else None


def discounted_value(
    flows: list[DatedCashFlow], as_of: str, discount_rate_pct: float,
) -> float | None:
    future = _future_flows(flows, as_of)
    if not future or discount_rate_pct <= -100:
        return None
    try:
        log_rate = math.log1p(discount_rate_pct / 100)
        value = sum(math.exp(math.log(amount) - years * log_rate) for years, amount in future)
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def conversion_option_value(
    *, stock_price: float, conversion_price: float, years: float,
    volatility_pct: float, risk_free_rate_pct: float, dividend_yield_pct: float,
    face_value: float = 100,
) -> float | None:
    if years <= 0 or volatility_pct < 0:
        return None
    sigma = volatility_pct / 100
    rate, dividend = risk_free_rate_pct / 100, dividend_yield_pct / 100
    try:
        stock_discounted = stock_price * math.exp(-dividend * years)
        strike_discounted = conversion_price * math.exp(-rate * years)
        if sigma == 0:
            call = max(stock_discounted - strike_discounted, 0)
        else:
            sigma_root_t = sigma * math.sqrt(years)
            d1 = (
                math.log(stock_price / conversion_price)
                + (rate - dividend + sigma * sigma / 2) * years
            ) / sigma_root_t
            d2 = d1 - sigma_root_t
            cdf1 = (1 + math.erf(d1 / math.sqrt(2))) / 2
            cdf2 = (1 + math.erf(d2 / math.sqrt(2))) / 2
            call = max(stock_discounted * cdf1 - strike_discounted * cdf2, 0)
        value = call * face_value / conversion_price
    except (ValueError, OverflowError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None


def clause_progress(
    clause: ConvertibleClause | None,
    observations: list[ConvertibleObservation],
    as_of: str | None,
    *, kind: str,
    conversion_start_date: str | None = None,
    observations_as_of: str | None = None,
    maturity_date: str | None = None,
) -> ClauseProgress:
    if clause is None or as_of is None:
        return ClauseProgress(as_of=as_of)
    base = dict(
        as_of=as_of, window_days=clause.window_days, required_days=clause.required_days,
    )
    if maturity_date and as_of >= maturity_date:
        return ClauseProgress(
            **base, state="not_applicable", note="已到期，不再将价格观察结果标记为当前强赎或回售条件",
        )
    starts = [day for day in (clause.start_date, conversion_start_date) if day]
    start_date = max(starts) if starts else None
    if (start_date and as_of < start_date) or (clause.end_date and as_of > clause.end_date):
        return ClauseProgress(**base, state="not_applicable", note="计算日不在条款适用期间")
    if clause.paused_until and as_of <= clause.paused_until:
        return ClauseProgress(**base, state="not_applicable", note="仍处于用户按条款填写的暂停观察期间；该设置在结束后重新计数")
    if start_date is None:
        return ClauseProgress(**base, note="尚未明确条款适用起始日，不能判断是否已进入观察期")
    eligible = [
        point for point in observations
        if start_date <= point.date <= as_of
        and (clause.paused_until is None or point.date > clause.paused_until)
    ]
    window = sorted(eligible, key=lambda point: point.date)[-clause.window_days:]
    if not window:
        return ClauseProgress(**base, note="尚无适用期内的交易日观察数据")
    hits = []
    for point in window:
        threshold = Decimal(str(point.conversion_price)) * Decimal(str(clause.trigger_ratio_pct)) / 100
        price = Decimal(str(point.stock_close))
        hits.append(price >= threshold if kind == "call" else price < threshold)
    if clause.consecutive:
        hit_days = 0
        for count, hit in enumerate(reversed(hits), start=1):
            if not hit:
                break
            hit_days = count
    else:
        hit_days = sum(hits)
    base.update(hit_days=hit_days, observed_days=len(window))
    if not clause.observations_complete:
        return ClauseProgress(
            **base, note="仅统计所提供样本；尚未确认连续实际交易日无遗漏，无法判断触发",
        )
    if observations_as_of != as_of:
        return ClauseProgress(
            **base, note=f"观察序列尚未确认覆盖至计算日；最后观察日 {window[-1].date}，不能判断当前触发",
        )
    if len(window) < clause.window_days:
        return ClauseProgress(
            **base, state="observing", note="观察样本尚未覆盖完整窗口，暂不确认触发",
        )
    met = hit_days >= clause.required_days
    return ClauseProgress(
        **base, state="met" if met else "observing",
        note=(("所提供窗口满足价格条件；不等于发行人已决定强赎或持有人已取得可执行回售权"
               if met else "所提供窗口尚未满足价格条件；其他条款与正式公告须分别核对")
              + f"。最后观察日 {window[-1].date}"
              + ("；已按用户设置从暂停观察结束后重新计数" if clause.paused_until else "")),
    )


def _quote_date(value: str | None) -> str | None:
    return (datetime.fromisoformat(value).astimezone(_SHANGHAI).date().isoformat()
            if value else None)


def _rounded(value: float | Decimal | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 6) if math.isfinite(number) else None


def calculate_metrics(item: ConvertibleInput, as_of: str | None = None) -> ConvertibleItem:
    """Recompute every derived field; stored/imported results are never trusted."""
    if as_of is not None:
        validate_date(as_of)
    inputs = item.model_dump(include=set(ConvertibleInput.model_fields))
    warnings: list[str] = []
    values: dict[str, float | Decimal | None] = {
        field: None for field in (
            "conversion_value", "conversion_premium_pct", "double_low", "remaining_years",
            "call_trigger_price", "put_trigger_price", "debt_to_float_cap_pct",
            "pure_bond_value", "option_value", "ytm_pct", "put_yield_pct",
        )
    }
    stock_date, bond_date = _quote_date(item.stock_quote_at), _quote_date(item.quote_at)
    valid_stock = not (as_of and stock_date and stock_date > as_of)
    valid_bond = not (as_of and bond_date and bond_date > as_of)
    valid_conversion = not (
        as_of and item.conversion_price_effective_date and item.conversion_price_effective_date > as_of
    )
    if not valid_stock or not valid_bond or not valid_conversion:
        warnings.append("含计算日之后才生效的价格或报价，相关金融指标未计算")
    if stock_date and bond_date and stock_date != bond_date:
        warnings.append("转债与正股报价日期不同，溢价与双低结果使用了不同日期的价格")
    if as_of and bond_date and bond_date < as_of:
        warnings.append("转债报价日期早于计算日，收益率使用该历史快照价格")
    if as_of and item.fund_holding_publish_date and item.fund_holding_publish_date > as_of:
        warnings.append("基金持仓公告晚于计算日，不能作为当时已知的持仓信息")
    if item.stock_price is not None and item.conversion_price is not None and valid_stock and valid_conversion:
        value = Decimal(str(item.face_value)) * Decimal(str(item.stock_price)) / Decimal(str(item.conversion_price))
        values["conversion_value"] = value
        if item.bond_price is not None and valid_bond:
            premium = (Decimal(str(item.bond_price)) / value - 1) * 100
            values["conversion_premium_pct"] = premium
            values["double_low"] = Decimal(str(item.bond_price)) + premium
    years = None
    if as_of and item.maturity_date:
        years = (date.fromisoformat(item.maturity_date) - date.fromisoformat(as_of)).days / 365
        values["remaining_years"] = max(years, 0)
    research = item.research
    for kind in ("call", "put"):
        clause = getattr(research, f"{kind}_clause") if research else None
        imported_ratio = getattr(item, f"{kind}_trigger_ratio_pct")
        ratio = clause.trigger_ratio_pct if clause else imported_ratio
        if clause and imported_ratio is not None and clause.trigger_ratio_pct != imported_ratio:
            warnings.append(f"{'强赎' if kind == 'call' else '回售'}阈值与基础资料不同，计算使用研究条款中的比例")
        if ratio is not None and item.conversion_price is not None and valid_conversion:
            values[f"{kind}_trigger_price"] = (
                Decimal(str(item.conversion_price)) * Decimal(str(ratio)) / 100
            )
    if item.outstanding_amount is not None and item.float_market_cap is not None and item.float_market_cap > 0:
        values["debt_to_float_cap_pct"] = item.outstanding_amount / item.float_market_cap * 100
    if research and as_of:
        price = None
        if item.bond_price is not None and valid_bond:
            if research.price_basis == "full":
                price = item.bond_price
                if research.accrued_interest:
                    warnings.append("当前选择全价，应计利息未再次计入买入成本")
            elif research.price_basis == "clean" and research.accrued_interest is not None:
                price = item.bond_price + research.accrued_interest
        if (research.cash_flows or research.put_cash_flows) and price is None:
            warnings.append("收益率需明确全价，或提供净价及每张应计利息")
        complete = (
            research.cash_flows_complete and bool(research.cash_flows) and item.maturity_date is not None
            and max(flow.date for flow in research.cash_flows) == item.maturity_date
        )
        if research.cash_flows and not complete:
            warnings.append("到期现金流尚未确认完整，或末笔日期与到期日不一致；到期收益率与纯债价值未计算")
        if complete:
            if price is not None:
                irr = dated_irr(price, research.cash_flows, as_of)
                values["ytm_pct"] = irr * 100 if irr is not None else None
                if irr is None:
                    warnings.append("到期收益率缺少未来现金流或超出有限数值范围")
            if research.discount_rate_pct is not None:
                values["pure_bond_value"] = discounted_value(
                    research.cash_flows, as_of, research.discount_rate_pct,
                )
        if research.put_cash_flows:
            if not research.put_cash_flows_complete:
                warnings.append("回售情景现金流尚未确认完整，回售情景收益率未计算")
            elif item.maturity_date and max(flow.date for flow in research.put_cash_flows) > item.maturity_date:
                warnings.append("回售情景现金流晚于到期日，回售情景收益率未计算")
            elif price is not None:
                irr = dated_irr(price, research.put_cash_flows, as_of)
                values["put_yield_pct"] = irr * 100 if irr is not None else None
            warnings.append("回售收益率是用户指定日期与现金流的情景值，不代表回售权已生效")
        if research.cash_flows or research.put_cash_flows:
            warnings.append("现金流金额按税前每张总应收款处理，不再自动加末息；仅使用计算日之后的现金流，年化为 ACT/365 复利 IRR")
        if (years is not None and years > 0 and item.stock_price is not None
                and item.conversion_price is not None and item.stock_volatility_pct is not None
                and research.risk_free_rate_pct is not None and research.dividend_yield_pct is not None
                and valid_stock and valid_conversion):
            values["option_value"] = conversion_option_value(
                stock_price=item.stock_price, conversion_price=item.conversion_price, years=years,
                volatility_pct=item.stock_volatility_pct, risk_free_rate_pct=research.risk_free_rate_pct,
                dividend_yield_pct=research.dividend_yield_pct, face_value=item.face_value,
            )
            warnings.append("期权价值为简化欧式转股期权模型；未纳入强赎、回售、下修、信用及交易成本，不能作为保底价值")
            if item.volatility_window_days is None or item.volatility_adjustment is None:
                warnings.append("波动率样本窗口或复权方式未提供，请核对模型输入口径")
    observations = research.observations if research else []
    rounded = {key: _rounded(value) for key, value in values.items()}
    for key in ("ytm_pct", "put_yield_pct"):
        if rounded[key] is not None and rounded[key] <= -100:
            # Keep representable precision near -100%, not a false exact endpoint.
            rounded[key] = float(values[key])
    return ConvertibleItem(
        **inputs, **rounded,
        call_progress=clause_progress(
            research.call_clause if research else None, observations, as_of,
            kind="call", conversion_start_date=item.conversion_start_date,
            observations_as_of=research.observations_as_of if research else None,
            maturity_date=item.maturity_date,
        ),
        put_progress=clause_progress(
            research.put_clause if research else None, observations, as_of,
            kind="put", conversion_start_date=None,
            observations_as_of=research.observations_as_of if research else None,
            maturity_date=item.maturity_date,
        ),
        analysis_warnings=warnings,
    )
