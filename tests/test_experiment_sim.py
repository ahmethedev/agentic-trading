"""Simulation invariants for the experiment lab.

No database: the engine is pure, and these are the properties a comparison shown
to a trader has to hold (PRODUCT.md §8). Prices are chosen so every threshold is
crossed exactly on purpose, never by rounding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_trade.product import templates
from agentic_trade.product.simulate import (
    Assumptions,
    Candidate,
    Candle,
    entries_for,
    qualifies,
    run_leg,
    simulate_trade,
    summarize_backtest,
    verdict,
)
from agentic_trade.product.templates import DraftRejected

START = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
RISK = Decimal("10")
# Entry 100, stop 90 -> 1R = 10 price units. tp1 = 120, tp2 = 125, breakeven = 110.
ENTRY, STOP = Decimal("100"), Decimal("90")


def candidate(offset_bars: int = 0, episode: str = "e1", **evidence) -> Candidate:
    base = {
        "rvol": 1.5,
        "flow_imbalance": 0.4,
        "close_position": 0.9,
        "pullback_depth_atr": 0.8,
        "extension_atr": 0.2,
        "stop_distance_atr": 1.0,
    }
    base.update(evidence)
    at = START + timedelta(minutes=5 * offset_bars)
    return Candidate(
        decision_id=1000 + offset_bars,
        run_id=1,
        inst_id="TEST-USDT",
        episode_id=episode,
        decided_at=at + timedelta(minutes=1),
        candle_open_time=at,
        entry_reference=ENTRY,
        structural_stop=STOP,
        evidence=base,
    )


def bars(*rows: tuple[str, str, str], start_bars: int = 1) -> list[Candle]:
    """Candles after the trigger candle, as (high, low, close) strings."""
    out = []
    for i, (high, low, close) in enumerate(rows):
        open_time = START + timedelta(minutes=5 * (start_bars + i))
        out.append(
            Candle(open_time, Decimal(close), Decimal(high), Decimal(low), Decimal(close))
        )
    return out


def exits(**overrides):
    plan = dict(templates.baseline_params()["exit"])
    plan.update(overrides)
    return plan


FREE = Assumptions(taker_fee_rate=Decimal(0))  # fees off, so R reads as price progress


def test_stop_hit_loses_exactly_one_r():
    trade = simulate_trade(candidate(), bars(("101", "89", "92")), exits(), FREE, RISK)
    assert trade.status == "CLOSED"
    assert [leg.reason for leg in trade.legs] == ["stop"]
    assert trade.legs[0].r_multiple == pytest.approx(-1.0)
    assert trade.net_quote == pytest.approx(Decimal(-10))


def test_target_and_stop_in_one_candle_takes_the_stop_and_says_so():
    """The order inside a candle is not in the data, so it is not invented."""
    trade = simulate_trade(candidate(), bars(("121", "89", "120")), exits(), FREE, RISK)
    assert trade.ambiguous is True
    assert [leg.reason for leg in trade.legs] == ["stop_ambiguous"]
    assert trade.legs[0].r_multiple == pytest.approx(-1.0)


def test_breakeven_takes_effect_only_on_the_following_candle():
    """A move to breakeven and a pullback to it inside one candle cannot be ordered."""
    plan = exits(breakeven_r=1.0, tp1_r=5.0, tp2_r=6.0)
    # Bar 1 reaches 110 (breakeven trigger) and dips to 95 -- below entry, above
    # the original stop. The stop must still be 90 there, so the trade survives.
    trade = simulate_trade(candidate(), bars(("110", "95", "108"), ("109", "99", "99")), plan,
                           FREE, RISK)
    assert trade.breakeven_applied is True
    assert trade.status == "CLOSED"
    assert [leg.reason for leg in trade.legs] == ["stop"]
    # Exited at the moved stop = entry, not at the original stop.
    assert trade.legs[0].px == ENTRY
    assert trade.legs[0].r_multiple == pytest.approx(0.0)


def test_partial_ladder_then_time_exit_keeps_fractions_of_initial_qty():
    plan = exits(breakeven_r=None, tp1_r=2.0, tp1_fraction=0.3, tp2_r=2.5, tp2_fraction=0.6,
                 max_hold_bars=3)
    trade = simulate_trade(
        candidate(), bars(("121", "100", "120"), ("122", "118", "121"), ("123", "119", "122")),
        plan, FREE, RISK,
    )
    assert [leg.reason for leg in trade.legs] == ["tp1", "time"]
    tp1, time_exit = trade.legs
    assert tp1.qty == trade.qty * Decimal("0.3")
    assert time_exit.qty == trade.qty * Decimal("0.7")   # tp2 never triggered
    assert trade.status == "CLOSED"


def test_unresolved_trade_reports_no_result_at_all():
    trade = simulate_trade(candidate(), bars(("105", "95", "104")), exits(), FREE, RISK)
    assert trade.status == "OPEN"
    payload = trade.as_dict(RISK)
    assert payload["net_r"] is None and payload["net_quote"] is None
    assert payload["banked_r_so_far"] == 0.0


def test_threshold_change_admits_a_candidate_the_live_rules_rejected():
    weak = candidate(rvol=1.1)
    assert qualifies(weak, {"min_rvol": 1.3}) == ["RVOL_TOO_LOW"]
    assert qualifies(weak, {"min_rvol": 1.0}) == []


def test_missing_measurement_never_passes_its_gate():
    blind = candidate(flow_imbalance=None)
    assert qualifies(blind, {"min_flow_imbalance": 0.15}) == ["FLOW_NOT_BUY_DOMINANT_UNKNOWN"]


def test_one_episode_enters_once_on_its_first_qualifying_bar():
    repeats = [candidate(0, rvol=1.0), candidate(1, rvol=1.4), candidate(2, rvol=1.9)]
    chosen = entries_for(repeats, {"min_rvol": 1.3})
    assert [c.decision_id for c in chosen] == [1001]


def test_a_busy_leg_skips_candidates_and_the_skip_is_counted():
    """One concurrency slot: the second setup arrives while the first is open."""
    params = templates.baseline_params()
    params["exit"] = exits(breakeven_r=None, max_hold_bars=12)
    params["risk"]["max_concurrent_positions"] = 1
    candles = bars(*[("101", "99", "100")] * 12)
    result = run_leg([candidate(0, episode="a"), candidate(1, episode="b")],
                     {"TEST-USDT": candles}, params, FREE)
    assert result["entries_qualified"] == 2
    assert result["entries_taken"] == 1
    assert result["entries_skipped_busy"] == 1
    assert result["skipped"][0]["reason"] == "CONCURRENCY_LIMIT"


def test_fees_are_charged_on_entry_and_on_every_exit_leg():
    paid = Assumptions(taker_fee_rate=Decimal("0.001"))
    trade = simulate_trade(candidate(), bars(("101", "89", "92")), exits(), paid, RISK)
    # qty = 10 / 10 = 1; entry 100 + exit 90 at 10 bps each.
    assert trade.fees_quote == pytest.approx(Decimal("0.19"))
    assert trade.net_quote == pytest.approx(Decimal("-10.19"))


def test_simulation_respects_per_position_allocation_cap():
    trade = simulate_trade(
        candidate(), bars(("101", "89", "92")), exits(), FREE, RISK,
        max_position_fraction=Decimal("0.25"),
    )
    assert trade.qty * trade.entry_px <= FREE.equity_quote * Decimal("0.25")


def test_backtest_summary_reports_return_drawdown_and_profit_factor():
    result = {
        "trades": [
            {"status": "CLOSED", "closed_at": START, "net_quote": "20", "net_r": 2},
            {
                "status": "CLOSED",
                "closed_at": START + timedelta(minutes=5),
                "net_quote": "-10",
                "net_r": -1,
            },
        ],
        "open_trades": 0,
        "net_r": 1,
        "fees_r": 0.1,
    }
    metrics = summarize_backtest(result, Decimal("1000"))
    assert metrics["net_return_pct"] == 1.0
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["max_drawdown_pct"] == pytest.approx(10 / 1020 * 100, rel=1e-3)


def test_small_sample_is_reported_as_insufficient_evidence():
    leg = {"closed_trades": 3, "net_r": 1.0, "trades": []}
    other = {"closed_trades": 3, "net_r": 2.0, "trades": []}
    assert verdict(leg, other)["state"] == "insufficient_evidence"


def test_draft_must_change_exactly_one_supported_rule():
    base = templates.baseline_params()
    params, value = templates.apply_change(base, "exit.breakeven_r", None)
    assert value is None
    assert base["exit"]["breakeven_r"] == 1.0          # parent untouched
    assert [d["key"] for d in templates.diff(base, params)] == ["exit.breakeven_r"]
    with pytest.raises(DraftRejected):
        templates.apply_change(base, "exit.magic_number", 3)
    with pytest.raises(DraftRejected):
        templates.apply_change(base, "entry.min_rvol", 99)     # out of bounds
    with pytest.raises(DraftRejected):
        templates.apply_change(base, "exit.breakeven_r", 1.0)  # unchanged
