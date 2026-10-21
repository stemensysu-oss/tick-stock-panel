from __future__ import annotations

import math

import pytest

from app.services.convertibles_math import calculate_metrics, dated_irr
from app.services.convertibles_models import ConvertibleInput, ConvertibleResearch, DatedCashFlow


def cash(day: str, amount: float) -> DatedCashFlow:
    return DatedCashFlow(date=day, amount=amount)


def test_dated_irr_uses_actual_dates_and_handles_yields_outside_old_solver_ranges():
    assert dated_irr(100, [cash("2027-01-01", 110)], "2026-01-01") == pytest.approx(0.1)
    low = dated_irr(200, [cash("2026-01-31", 100)], "2026-01-01")
    assert low == pytest.approx(0.5 ** (365 / 30) - 1)
    assert -1 < low < -0.95
    high = dated_irr(10, [cash("2027-01-01", 150)], "2026-01-01")
    assert high == pytest.approx(14)


def test_complete_cashflows_do_not_add_the_final_coupon_twice():
    item = ConvertibleInput(
        code="110001", name="研究债", bond_price=100.0, maturity_date="2027-01-01",
        research=ConvertibleResearch(cash_flows=[cash("2027-01-01", 110)],
                                     cash_flows_complete=True, discount_rate_pct=5.0,
                                     price_basis="full"),
    )
    result = calculate_metrics(item, "2026-01-01")
    assert result.ytm_pct == pytest.approx(10)
    assert result.pure_bond_value == pytest.approx(110 / 1.05, abs=1e-6)
    assert result.option_value is None
    incomplete = item.model_copy(update={"research": ConvertibleResearch(
        cash_flows=[cash("2027-01-01", 110)], discount_rate_pct=5.0,
    )})
    assert calculate_metrics(incomplete, "2026-01-01").ytm_pct is None


def test_simplified_option_is_scaled_to_100_face_and_has_explicit_inputs():
    result = calculate_metrics(ConvertibleInput(
        code="110001", name="研究债", stock_price=10.0, conversion_price=10.0,
        maturity_date="2027-01-01", stock_volatility_pct=20.0,
        research=ConvertibleResearch(risk_free_rate_pct=0.0, dividend_yield_pct=0.0),
    ), "2026-01-01")
    expected = 100 * (math.erf(0.1 / math.sqrt(2)))
    assert result.option_value == pytest.approx(expected, abs=1e-6)
    assert result.pure_bond_value is None
    no_input = calculate_metrics(ConvertibleInput(
        code="110002", name="缺参数", stock_price=10.0, conversion_price=10.0,
        maturity_date="2027-01-01",
    ), "2026-01-01")
    assert no_input.option_value is None


def test_future_conversion_price_or_stock_quote_is_not_used_for_past_analysis():
    item = ConvertibleInput(
        code="110001", name="研究债", bond_price=100.0, stock_price=12.0,
        conversion_price=10.0, conversion_price_effective_date="2026-02-01",
    )
    assert calculate_metrics(item, "2026-01-01").conversion_value is None
    assert calculate_metrics(item, "2026-02-01").conversion_value == 120


def test_condition_requires_complete_trading_window_and_is_not_execution_status():
    raw = {
        "observations_as_of": "2026-01-07",
        "call_clause": {"window_days": 3, "required_days": 2, "trigger_ratio_pct": 130,
                        "start_date": "2026-01-01", "observations_complete": True},
        "observations": [
            {"date": "2026-01-05", "stock_close": 13.0, "conversion_price": 10.0},
            {"date": "2026-01-06", "stock_close": 12.0, "conversion_price": 10.0},
            {"date": "2026-01-07", "stock_close": 14.0, "conversion_price": 10.0},
            {"date": "2026-01-08", "stock_close": 15.0, "conversion_price": 10.0},
        ],
    }
    item = ConvertibleInput(code="110001", name="研究债", research=ConvertibleResearch(**raw))
    result = calculate_metrics(item, "2026-01-07")
    assert result.call_progress.state == "met"
    assert result.call_progress.hit_days == 2
    assert result.call_progress.observed_days == 3
    assert result.redemption_status is None
    assert "不等于" in result.call_progress.note
    raw["call_clause"]["observations_complete"] = False
    unknown = calculate_metrics(item.model_copy(update={
        "research": ConvertibleResearch(**raw),
    }), "2026-01-07")
    assert unknown.call_progress.state == "unknown"


def test_clause_pause_and_consecutive_observation_do_not_use_calendar_day_counts():
    research = ConvertibleResearch(
        observations_as_of="2026-01-07",
        put_clause={"window_days": 3, "required_days": 3, "trigger_ratio_pct": 70,
                    "consecutive": True, "start_date": "2026-01-01",
                    "observations_complete": True},
        call_clause={"window_days": 3, "required_days": 2, "trigger_ratio_pct": 130,
                     "paused_until": "2026-01-07", "observations_complete": True},
        observations=[
            {"date": "2026-01-02", "stock_close": 6.0, "conversion_price": 10.0},
            {"date": "2026-01-05", "stock_close": 7.0, "conversion_price": 10.0},
            {"date": "2026-01-06", "stock_close": 6.0, "conversion_price": 10.0},
            {"date": "2026-01-07", "stock_close": 6.0, "conversion_price": 10.0},
        ],
    )
    result = calculate_metrics(ConvertibleInput(code="110001", name="研究债", research=research),
                               "2026-01-07")
    assert result.put_progress.state == "observing"
    assert result.put_progress.hit_days == 2
    assert result.call_progress.state == "not_applicable"


def test_stale_observation_confirmation_is_not_current_trigger_state():
    research = ConvertibleResearch(
        observations_as_of="2026-01-05",
        call_clause={"window_days": 1, "required_days": 1, "trigger_ratio_pct": 130,
                     "start_date": "2026-01-01", "observations_complete": True},
        observations=[{"date": "2026-01-05", "stock_close": 13, "conversion_price": 10}],
    )
    item = ConvertibleInput(code="110001", name="研究债", research=research)
    assert calculate_metrics(item, "2026-01-05").call_progress.state == "met"
    later = calculate_metrics(item, "2026-01-07")
    assert later.call_progress.state == "unknown"
    assert "2026-01-05" in later.call_progress.note


def test_clean_price_adds_interest_once_and_missing_basis_stays_unknown():
    base = ConvertibleInput(
        code="110001", name="研究债", bond_price=99, maturity_date="2027-01-01",
        research=ConvertibleResearch(
            cash_flows=[cash("2027-01-01", 110)], cash_flows_complete=True,
            discount_rate_pct=-50, price_basis="clean", accrued_interest=1,
        ),
    )
    result = calculate_metrics(base, "2026-01-01")
    assert result.ytm_pct == 10
    assert result.pure_bond_value == 220
    unknown = base.model_copy(update={"research": base.research.model_copy(update={"price_basis": None})})
    assert calculate_metrics(unknown, "2026-01-01").ytm_pct is None
    full = base.model_copy(update={"research": base.research.model_copy(update={"price_basis": "full"})})
    assert calculate_metrics(full, "2026-01-01").ytm_pct == pytest.approx((110 / 99 - 1) * 100, abs=1e-6)


def test_price_condition_cannot_trigger_before_conversion_period():
    item = ConvertibleInput(
        code="110001", name="研究债", conversion_start_date="2026-02-01",
        research=ConvertibleResearch(
            observations_as_of="2026-01-05",
            call_clause={"window_days": 1, "required_days": 1, "trigger_ratio_pct": 130,
                         "start_date": "2026-01-01", "observations_complete": True},
            observations=[{"date": "2026-01-05", "stock_close": 14, "conversion_price": 10}],
        ),
    )
    assert calculate_metrics(item, "2026-01-05").call_progress.state == "not_applicable"


@pytest.mark.parametrize(("kind", "stock_close", "ratio"), [("call", 14, 130), ("put", 6, 70)])
def test_matured_bond_does_not_show_current_price_condition_met(kind, stock_close, ratio):
    research = ConvertibleResearch(**{
        "observations_as_of": "2026-10-21",
        f"{kind}_clause": {
            "window_days": 1, "required_days": 1, "trigger_ratio_pct": ratio,
            "start_date": "2026-01-01", "observations_complete": True,
        },
        "observations": [{"date": "2026-10-21", "stock_close": stock_close, "conversion_price": 10}],
    })
    result = calculate_metrics(ConvertibleInput(
        code="110001", name="到期债", maturity_date="2026-10-20", research=research,
    ), "2026-10-21")
    assert getattr(result, f"{kind}_progress").state == "not_applicable"
    assert result.remaining_years == 0
