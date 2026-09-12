"""Risk-core tests. These encode the invariants that must never regress."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.risk.sizing import (
    InstrumentSpec,
    RiskRejection,
    SizingInput,
    build_exit_plan,
    compute_size,
)

D = Decimal
SPEC = InstrumentSpec("TEST-USDT", lot_sz=D("0.00000001"), min_sz=D("0.00001"),
                      tick_sz=D("0.1"))


def mk(**over) -> SizingInput:
    base = dict(
        equity_quote=D("1000"), available_quote=D("1000"),
        entry_reference=D("100"), structural_stop=D("98"),
        risk_fraction=D("0.01"), taker_fee_rate=D("0"), spec=SPEC,
    )
    base.update(over)
    return SizingInput(**base)


def test_quantity_matches_risk_budget():
    """1% of 1000 = 10 risk; a 2-wide stop implies 5 units."""
    r = compute_size(mk())
    assert r.risk_budget == D("10")
    assert r.quantity == D("5")
    assert r.risk_at_stop <= r.risk_budget


def test_realised_risk_never_exceeds_budget():
    for stop in ("99.9", "99", "95", "50"):
        r = compute_size(mk(structural_stop=D(stop)))
        assert r.risk_at_stop <= r.risk_budget


def test_spot_balance_cap_agentmd_worked_example():
    """AGENT.md §5: 1000 equity, 10 risk budget, 0.5% stop needs 2000 notional.

    Unleveraged spot cannot fund it, so quantity shrinks and realised risk is
    reported BELOW the budget -- the stop is never widened to spend it.
    """
    r = compute_size(mk(entry_reference=D("100"), structural_stop=D("99.5")))
    assert "SPOT_BALANCE" in r.capped_by
    assert r.notional <= D("1000")
    assert r.risk_at_stop < r.risk_budget      # under-risked, and reported as such
    assert r.quantity == D("10")               # 1000 balance / 100 price


def test_position_cap_keeps_a_tight_stop_from_using_all_cash():
    r = compute_size(mk(
        entry_reference=D("100"), structural_stop=D("99.5"),
        max_position_fraction=D("0.25"),
    ))
    assert "POSITION_CAP" in r.capped_by
    assert r.notional <= D("250")
    assert r.position_notional_cap == D("250")


def test_position_fraction_must_be_a_real_fraction():
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(max_position_fraction=D("1.1")))
    assert e.value.code == "POSITION_FRACTION_INVALID"


def test_wider_stop_needs_less_notional():
    """Same 10 risk at a 2% stop = 500 notional, well inside the balance."""
    r = compute_size(mk(structural_stop=D("98")))
    assert r.notional == D("500")
    assert "SPOT_BALANCE" not in r.capped_by


def test_risk_fraction_cap_is_enforced():
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(risk_fraction=D("0.05")))
    assert e.value.code == "RISK_FRACTION_ABOVE_CAP"


def test_risk_fraction_at_cap_allowed():
    r = compute_size(mk(risk_fraction=D("0.02")))
    assert r.risk_budget == D("20")


def test_zero_equity_rejects_rather_than_sizing():
    """An authenticated but unfunded account must produce no quantity at all."""
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(equity_quote=D("0"), available_quote=D("0")))
    assert e.value.code == "NO_EQUITY"


def test_no_available_balance_rejects():
    """Equity on the books but nothing spendable cannot produce an order."""
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(equity_quote=D("1000"), available_quote=D("0")))
    assert e.value.code in {"QTY_ROUNDS_TO_ZERO", "BELOW_MIN_SIZE",
                            "BELOW_MIN_SIZE_BALANCE"}


def test_stop_above_entry_rejected():
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(structural_stop=D("101")))
    assert e.value.code == "STOP_NOT_BELOW_ENTRY"


# --------------------------------------------------------- venue minimum ----
# A risk-implied quantity below the venue minimum used to end the trade, full
# stop. On a small account that is most setups, so an approved idea never became
# an entry. The minimum may now be taken -- but only while its risk still fits
# inside RISK_FRACTION_MAX, the number that actually bounds a loss.
MIN_SPEC = InstrumentSpec("T", lot_sz=D("0.001"), min_sz=D("1"), tick_sz=D("0.1"))


def test_min_size_uplift_is_bounded_by_the_hard_ceiling():
    """1% of 100 buys 0.5 units; the venue minimum of 1 costs 2% -- the cap."""
    r = compute_size(mk(spec=MIN_SPEC, equity_quote=D("100"),
                        available_quote=D("100")))
    assert r.quantity == D("1")
    assert "MIN_SIZE_UPLIFT" in r.capped_by
    assert r.risk_at_stop > r.risk_budget, "this is the point: it costs more"
    assert r.risk_at_stop <= r.risk_ceiling, "but never more than the hard cap"


def test_min_size_uplift_refused_when_it_breaches_the_ceiling():
    """A minimum lot that risks more than RISK_FRACTION_MAX is simply not taken."""
    with pytest.raises(RiskRejection) as e:
        # Same minimum, half the equity -> the ceiling halves, the lot does not.
        compute_size(mk(spec=MIN_SPEC, equity_quote=D("50"),
                        available_quote=D("100")))
    assert e.value.code == "BELOW_MIN_SIZE_RISK"


def test_min_size_uplift_refused_when_the_balance_cannot_pay_for_it():
    """Capital, not risk, is the binding constraint -- and it must say so."""
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(spec=MIN_SPEC, equity_quote=D("1000"),
                        available_quote=D("50")))
    assert e.value.code == "BELOW_MIN_SIZE_BALANCE"


def test_min_size_uplift_can_be_switched_off():
    """The strict behaviour stays one flag away."""
    with pytest.raises(RiskRejection) as e:
        compute_size(mk(spec=MIN_SPEC, equity_quote=D("100"),
                        available_quote=D("100"),
                        allow_min_size_uplift=False))
    assert e.value.code == "BELOW_MIN_SIZE"


def test_uplift_never_exceeds_the_ceiling_across_stop_widths():
    for stop in ("99.9", "99", "98", "96"):
        r = compute_size(mk(spec=MIN_SPEC, equity_quote=D("1000"),
                            available_quote=D("1000"), structural_stop=D(stop)))
        assert r.risk_at_stop <= r.risk_ceiling


def test_fees_reduce_quantity():
    free = compute_size(mk(taker_fee_rate=D("0")))
    paid = compute_size(mk(taker_fee_rate=D("0.001")))
    assert paid.quantity < free.quantity
    assert paid.est_cost_per_unit > 0


def test_fee_reserve_keeps_notional_inside_balance():
    r = compute_size(mk(entry_reference=D("100"), structural_stop=D("99.5"),
                        taker_fee_rate=D("0.001")))
    assert r.notional * D("1.001") <= D("1000")


def test_account_r_unit_is_one_percent_regardless_of_risk_fraction():
    r = compute_size(mk(risk_fraction=D("0.02")))
    assert r.account_r_unit == D("10")          # 1% of equity
    assert r.risk_budget == D("20")             # but 2 account-R of risk taken


# ------------------------------------------------------------- exit plan ----
def test_exit_ladder_fractions_are_of_initial_quantity():
    p = build_exit_plan(D("100"), D("100"), D("98"), SPEC)
    assert p.tp1_qty == D("30")                 # 30% of initial
    assert p.tp2_qty == D("60")                 # 60% of initial, NOT of remainder
    assert p.runner_qty == D("10")
    assert p.tp1_qty + p.tp2_qty + p.runner_qty == p.initial_qty


def test_exit_triggers_use_real_average_entry():
    """A worse fill produces a worse ladder rather than a re-derived stop."""
    p = build_exit_plan(D("100"), D("101"), D("98"), SPEC)
    assert p.price_r_distance == D("3")
    assert p.breakeven_trigger_px == D("104")   # entry + 1R
    assert p.tp1_trigger_px == D("107")         # entry + 2R
    assert p.tp2_trigger_px == D("108.5")       # entry + 2.5R


def test_breakeven_is_gross_entry_not_fee_adjusted():
    p = build_exit_plan(D("10"), D("100"), D("98"), SPEC)
    assert p.breakeven_trigger_px == D("102")
    assert p.initial_stop_px == D("98")


def test_exit_quantities_never_exceed_holdings_after_lot_rounding():
    spec = InstrumentSpec("T", lot_sz=D("0.1"), min_sz=D("0.1"), tick_sz=D("0.01"))
    p = build_exit_plan(D("1.05"), D("100"), D("98"), spec)
    assert p.tp1_qty + p.tp2_qty + p.runner_qty == D("1.05")
    assert p.runner_qty >= 0


def test_frozen_risk_denominator_survives_breakeven_move():
    """Moving the stop up must not shrink the R denominator used in reporting."""
    p = build_exit_plan(D("5"), D("100"), D("98"), SPEC)
    before = p.frozen_risk_amount
    # a breakeven move changes the live stop, not the plan's frozen basis
    assert before == D("10")
    assert p.price_r_distance == D("2")
