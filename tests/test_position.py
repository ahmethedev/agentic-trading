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
    sweep_protection,
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
                fees: dict | None = None):
    intent_id = await _intent(run_id, decision_id)
    # A protective sell needs base to sell: give the venue the inventory the
    # entry would have credited, less any base-denominated fee.
    base_fee = (fees or {}).get("BTC", Decimal(0))
    venue = venue or PaperVenue(balances={"BTC": qty - base_fee})
    return await open_position(
        venue, run_id=run_id, intent_id=intent_id,
        inst_id="BTC-USDT", filled_qty=qty, avg_entry_px=D("100"),
        structural_stop=D("98"), spec=SPEC, est_cost_per_unit=D("0"),
        policy_version="t", fees=fees)


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

    p = await _open(run_id, decision_id,
                    venue=NoProtect(balances={"BTC": DEFAULT_QTY}))
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
    p = await _open(run_id, decision_id, fees={"USDT": D("2")})  # 2 to get in
    await record_exit_fill(p.position_id, D("10"), D("104"), D("1"), D("100"))
    r = await _row(p.position_id)
    # gross (104-100)*10 = 40, minus 1 exit fee, minus the full 2 entry fee
    assert r["realized_pnl"] == D("37")


async def test_entry_fee_is_amortised_pro_rata_on_partial_exits(run_id, decision_id):
    p = await _open(run_id, decision_id, fees={"USDT": D("2")})
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


# ------------------------------------------------ base-denominated entry fee --
async def test_protection_is_sized_to_base_actually_credited(run_id, decision_id):
    """OKX takes the spot BUY fee out of the base you receive.

    Sizing the OCO to the filled quantity therefore asks the venue to sell base
    it never credited, and it refuses -- which is how a live SOL position sat
    without a stop for two and a half hours on 12 Sep 2026.
    """
    fee = D("0.01")                       # 0.1% of a 10-unit fill, paid in BTC
    venue = PaperVenue(balances={"BTC": DEFAULT_QTY - fee})
    p = await _open(run_id, decision_id, venue=venue, fees={"BTC": fee})

    assert p.algo_id is not None, p.protection_error
    r = await _row(p.position_id)
    # The position owns what was credited, not what was matched.
    assert r["initial_qty"] == DEFAULT_QTY - fee
    assert r["qty_open"] == DEFAULT_QTY - fee
    # ... and the order that protects it is sized the same way.
    async with pool.ledger().acquire() as con:
        stop = await con.fetchrow(
            """SELECT qty_requested FROM orders
               WHERE run_id=$1 AND purpose='STOP'
               ORDER BY created_at DESC LIMIT 1""", run_id)
    assert stop["qty_requested"] == DEFAULT_QTY - fee


async def test_base_fee_is_booked_as_a_quote_cost(run_id, decision_id):
    """A fee paid in BTC still has to appear in the PnL denominated in USDT."""
    p = await _open(run_id, decision_id, fees={"BTC": D("0.01")})
    r = await _row(p.position_id)
    assert r["entry_fees"] == D("0.01") * D("100")     # valued at the entry px


async def test_unprotected_position_is_repaired_by_the_sweep(run_id, decision_id):
    """Finding a naked position and only logging it is not a fix."""
    class NoProtect(PaperVenue):
        fail = True

        async def place_oco(self, *a, **k):
            if self.fail:
                raise VenueRejected("ALGO_FAILED", "venue refused")
            return await PaperVenue.place_oco(self, *a, **k)

    venue = NoProtect(balances={"BTC": DEFAULT_QTY})
    p = await _open(run_id, decision_id, venue=venue)
    assert p.algo_id is None

    venue.fail = False
    sweep = await sweep_protection(venue, run_id)
    assert sweep.repaired == [p.position_id]
    assert await venue.get_algo_orders("BTC-USDT")

    # A second pass must not stack a second stop on the same inventory.
    again = await sweep_protection(venue, run_id)
    assert again.repaired == []
    assert again.already_protected == [p.position_id]


async def test_sweep_protects_at_the_breakeven_stop_not_the_original(run_id, decision_id):
    """A repaired stop must be where the position stands now, not where it began."""
    class NoProtect(PaperVenue):
        fail = True

        async def place_oco(self, inst_id, qty, tp, sl, cid):
            if self.fail:
                raise VenueRejected("ALGO_FAILED", "venue refused")
            self.last_sl = sl
            return await PaperVenue.place_oco(self, inst_id, qty, tp, sl, cid)

    venue = NoProtect(balances={"BTC": DEFAULT_QTY})
    p = await _open(run_id, decision_id, venue=venue)
    assert await apply_breakeven(p.position_id, D("100")) is True

    venue.fail = False
    await sweep_protection(venue, run_id)
    assert venue.last_sl == D("100"), "re-armed at the stale initial stop"


async def test_sweep_clamps_to_what_the_venue_holds(run_id, decision_id):
    """The ledger can be ahead of reality; the order must not be."""
    class Recording(PaperVenue):
        fail = True

        async def place_oco(self, inst_id, qty, tp, sl, cid):
            if self.fail:
                raise VenueRejected("ALGO_FAILED", "venue refused")
            self.last_qty = qty
            return await PaperVenue.place_oco(self, inst_id, qty, tp, sl, cid)

    # Ledger thinks 10; the account holds 9.5 (an un-netted fee, say).
    venue = Recording(balances={"BTC": DEFAULT_QTY})
    p = await _open(run_id, decision_id, venue=venue)
    venue.balances["BTC"] = D("9.5")
    venue.fail = False

    sweep = await sweep_protection(venue, run_id)
    assert sweep.repaired == [p.position_id]
    assert venue.last_qty == D("9.5")


async def test_unsellable_dust_closes_instead_of_holding_the_slot(run_id, decision_id):
    """Base below the venue minimum can never be sold, so it is not a position.

    Left OPEN it would hold the only concurrency slot forever and silently stop
    the system trading.
    """
    class NoProtect(PaperVenue):
        async def place_oco(self, *a, **k):
            raise VenueRejected("ALGO_FAILED", "venue refused")

    venue = NoProtect(balances={"BTC": DEFAULT_QTY})
    p = await _open(run_id, decision_id, venue=venue)
    venue.balances["BTC"] = D("0.000001")      # below the 0.00001 minimum

    sweep = await sweep_protection(venue, run_id)
    assert sweep.dust_closed == [p.position_id]
    r = await _row(p.position_id)
    assert r["status"] == "CLOSED"
    assert r["qty_open"] == 0
