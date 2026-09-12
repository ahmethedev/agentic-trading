"""Position and exit-ladder invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.db import pool
from agentic_trade.execution.position import (
    apply_breakeven,
    claim_tp_stage,
    open_position,
    record_exit_fill,
    sellable_qty,
)
from agentic_trade.execution.venue import PaperVenue, VenueRejected
from agentic_trade.risk.sizing import InstrumentSpec

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
SPEC = InstrumentSpec("BTC-USDT", lot_sz=D("0.00000001"), min_sz=D("0.00001"),
                      tick_sz=D("0.1"))
DEFAULT_QTY = D("10")


async def _intent(run_id: int, decision_id: int) -> int:
    async with pool.ledger().acquire() as con:
        return await con.fetchval(
            """INSERT INTO intents (decision_id, run_id, inst_id, side, status,
                   equity_at_decision, risk_fraction, risk_budget, entry_reference,
                   structural_stop, price_r_distance, qty_requested, policy_version)
               VALUES ($1,$2,'BTC-USDT','buy','FILLED',1000,0.01,10,100,98,2,10,'t')
               RETURNING intent_id""", decision_id, run_id)


async def _open(run_id, decision_id, venue=None, qty: Decimal = DEFAULT_QTY,
                fees_paid: Decimal = Decimal(0)):
    intent_id = await _intent(run_id, decision_id)
    return await open_position(
        venue or PaperVenue(), run_id=run_id, intent_id=intent_id,
        inst_id="BTC-USDT", filled_qty=qty, avg_entry_px=D("100"),
        structural_stop=D("98"), spec=SPEC, est_cost_per_unit=D("0"),
        policy_version="t", fees_paid=fees_paid)


async def _row(pid):
    async with pool.ledger().acquire() as con:
        return await con.fetchrow(
            "SELECT * FROM positions WHERE position_id=$1", pid)


async def test_position_freezes_r_basis_from_real_fill(run_id, decision_id):
    p = await _open(run_id, decision_id)
    r = await _row(p.position_id)
    assert r["avg_entry_px"] == D("100")
    assert r["price_r_distance"] == D("2")
    assert r["frozen_risk_amount"] == D("20")      # 10 qty * 2 distance
    assert p.plan.tp1_trigger_px == D("104")       # +2R
    assert p.plan.tp2_trigger_px == D("105")       # +2.5R


async def test_protection_is_attached_on_open(run_id, decision_id):
    p = await _open(run_id, decision_id)
    assert p.algo_id is not None
    assert p.protection_error is None


async def test_failed_protection_is_recorded_as_an_incident(run_id, decision_id):
    class NoProtect(PaperVenue):
        async def place_oco(self, *a, **k):
            raise VenueRejected("ALGO_FAILED", "venue refused")

    p = await _open(run_id, decision_id, venue=NoProtect())
    assert p.algo_id is None
    assert p.protection_error is not None
    async with pool.ledger().acquire() as con:
        n = await con.fetchval(
            """SELECT count(*) FROM ops_events
               WHERE run_id=$1 AND kind='protection_failed'""", run_id)
    assert n == 1, "an unprotected position must raise an ops incident"


async def test_breakeven_moves_once_only(run_id, decision_id):
    p = await _open(run_id, decision_id)
    assert await apply_breakeven(p.position_id, D("100")) is True
    assert await apply_breakeven(p.position_id, D("100")) is False, "re-applied"
    r = await _row(p.position_id)
    assert r["current_stop_px"] == D("100")
    # The R denominator must be untouched by the breakeven move.
    assert r["frozen_risk_amount"] == D("20")
    assert r["price_r_distance"] == D("2")


async def test_tp_stage_claimed_once_despite_repeated_triggers(run_id, decision_id):
    p = await _open(run_id, decision_id)
    first = await claim_tp_stage(p.position_id, "tp1")
    second = await claim_tp_stage(p.position_id, "tp1")
    assert first == D("3")            # 30% of the initial 10
    assert second is None, "repeated +2R trigger produced a second sale"


async def test_tp_fractions_are_of_initial_not_remaining(run_id, decision_id):
    p = await _open(run_id, decision_id)
    q1 = await claim_tp_stage(p.position_id, "tp1")
    await record_exit_fill(p.position_id, q1, D("104"), D("0"), D("100"))
    q2 = await claim_tp_stage(p.position_id, "tp2")
    assert q1 == D("3")
    assert q2 == D("6"), "tp2 must be 60% of initial, not 60% of the remainder"
    assert q1 + q2 == D("9")          # leaving a 10% runner


async def test_exit_cannot_oversell_inventory(run_id, decision_id):
    """A stage claim is capped by what is actually left."""
    p = await _open(run_id, decision_id)
    # Something else already sold almost everything.
    await record_exit_fill(p.position_id, D("9.5"), D("104"), D("0"), D("100"))
    q = await claim_tp_stage(p.position_id, "tp2")
    assert q == D("0.5"), "claim exceeded remaining inventory"


async def test_realized_pnl_is_net_of_entry_and_exit_fees(run_id, decision_id):
    """Entry fees must be amortised in, not just exit fees."""
    p = await _open(run_id, decision_id, fees_paid=D("2"))   # 2 paid to get in
    await record_exit_fill(p.position_id, D("10"), D("104"), D("1"), D("100"))
    r = await _row(p.position_id)
    # gross (104-100)*10 = 40, minus 1 exit fee, minus the full 2 entry fee
    assert r["realized_pnl"] == D("37")


async def test_entry_fee_is_amortised_pro_rata_on_partial_exits(run_id, decision_id):
    p = await _open(run_id, decision_id, fees_paid=D("2"))
    await record_exit_fill(p.position_id, D("3"), D("104"), D("0"), D("100"))
    r = await _row(p.position_id)
    # gross (104-100)*3 = 12, minus 3/10 of the 2.0 entry fee = 0.6
    assert r["realized_pnl"] == D("11.4")


async def test_position_closes_when_inventory_reaches_zero(run_id, decision_id):
    p = await _open(run_id, decision_id)
    await record_exit_fill(p.position_id, D("10"), D("104"), D("1"), D("100"))
    r = await _row(p.position_id)
    assert r["status"] == "CLOSED"
    assert r["closed_at"] is not None
    assert r["qty_open"] == 0
    assert r["realized_pnl"] == D("39")       # (104-100)*10 - 1 exit fee, no entry fee


async def test_sellable_qty_tracks_remaining(run_id, decision_id):
    p = await _open(run_id, decision_id)
    assert await sellable_qty(p.position_id) == D("10")
    await record_exit_fill(p.position_id, D("4"), D("104"), D("0"), D("100"))
    assert await sellable_qty(p.position_id) == D("6")


async def test_runner_remains_after_both_stages(run_id, decision_id):
    p = await _open(run_id, decision_id)
    q1 = await claim_tp_stage(p.position_id, "tp1")
    await record_exit_fill(p.position_id, q1, D("104"), D("0"), D("100"))
    q2 = await claim_tp_stage(p.position_id, "tp2")
    await record_exit_fill(p.position_id, q2, D("105"), D("0"), D("100"))
    r = await _row(p.position_id)
    assert r["qty_open"] == D("1")            # the 10% runner
    assert r["status"] == "OPEN"
