"""Startup reconciliation: what a restart must resolve before trading again."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.db import pool
from agentic_trade.execution.order_manager import OrderManager
from agentic_trade.execution.reconcile import Reconciler
from agentic_trade.execution.venue import Faults, PaperVenue, VenueRejected
from agentic_trade.risk import gate

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
INST = "BTC-USDT"


async def _intent(run_id, decision_id, status="RESERVED") -> int:
    async with pool.ledger().acquire() as con:
        return await con.fetchval(
            """INSERT INTO intents (decision_id, run_id, inst_id, side, status,
                   equity_at_decision, risk_fraction, risk_budget, entry_reference,
                   structural_stop, price_r_distance, qty_requested, policy_version)
               VALUES ($1,$2,$3,'buy',$4,1000,0.01,10,100,98,2,0.01,'t')
               RETURNING intent_id""", decision_id, run_id, INST, status)


async def _status(intent_id) -> str:
    async with pool.ledger().acquire() as con:
        return await con.fetchval(
            "SELECT status FROM intents WHERE intent_id=$1", intent_id)


def _rec(venue, run_id) -> Reconciler:
    return Reconciler(venue, OrderManager(venue, run_id), run_id)


# ------------------------------------------------------- unsent intents -----
async def test_intent_with_no_order_row_is_released(run_id, decision_id):
    """This is the exact state a crash between reserve() and send() leaves."""
    intent_id = await _intent(run_id, decision_id, "RESERVED")
    report = await _rec(PaperVenue(), run_id).run()

    assert report.released_intents == 1
    assert await _status(intent_id) == "RECONCILED"
    assert report.is_clean


async def test_released_intent_frees_the_slot(run_id, decision_id):
    await _intent(run_id, decision_id, "SENT")
    await _rec(PaperVenue(), run_id).run()
    result = await gate.evaluate(INST, mode="paper", equity=D("30"),
                                 equity_is_real=True, run_id=run_id,
                                 reconciled=True)
    assert "CONCURRENCY_LIMIT" not in result.codes


# ------------------------------------------------------ in-flight orders ----
async def test_order_unknown_at_venue_is_marked_not_placed(run_id, decision_id):
    """We recorded an order before sending; the venue never saw it."""
    intent_id = await _intent(run_id, decision_id, "UNKNOWN")
    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                   inst_id, purpose, side, ord_type, qty_requested, status, sent_at)
               VALUES ('cidghost',$1,$2,'okx-tr',$3,'ENTRY','buy','ioc',0.01,
                       'UNKNOWN',now())""", intent_id, run_id, INST)

    report = await _rec(PaperVenue(), run_id).run()
    assert report.resolved_orders == 1
    assert await _status(intent_id) == "RECONCILED"
    async with pool.ledger().acquire() as con:
        row = await con.fetchrow(
            "SELECT status, terminal_at FROM orders WHERE client_order_id='cidghost'")
    assert row["status"] == "NOT_PLACED"
    assert row["terminal_at"] is not None


async def test_order_that_filled_while_down_is_ingested(run_id, decision_id):
    """A fill that landed during the outage must appear after reconciliation."""
    venue = PaperVenue()
    om = OrderManager(venue, run_id)
    intent_id = await _intent(run_id, decision_id, "SENT")
    # Order exists at the venue and filled, but our ledger never learned it.
    await venue.place_limit_ioc(INST, "buy", D("0.01"), D("100"), "cidfilled")
    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                   inst_id, purpose, side, ord_type, qty_requested, status, sent_at)
               VALUES ('cidfilled',$1,$2,'okx-tr',$3,'ENTRY','buy','ioc',0.01,
                       'SENDING',now())""", intent_id, run_id, INST)

    report = await Reconciler(venue, om, run_id).run()
    assert report.fills_ingested == 1
    totals = await om.filled_totals("cidfilled")
    assert totals.qty == D("0.01")
    assert totals.avg_px == D("100")
    assert await _status(intent_id) == "FILLED"


async def test_unreachable_venue_blocks_instead_of_assuming_dead(run_id, decision_id):
    """Failing to ask is not an answer. The system must stay blocked."""
    intent_id = await _intent(run_id, decision_id, "UNKNOWN")
    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                   inst_id, purpose, side, ord_type, qty_requested, status, sent_at)
               VALUES ('cidblind',$1,$2,'okx-tr',$3,'ENTRY','buy','ioc',0.01,
                       'UNKNOWN',now())""", intent_id, run_id, INST)

    venue = PaperVenue(faults=Faults(get_order_timeout=True))
    report = await _rec(venue, run_id).run()

    assert not report.is_clean
    assert "cidblind" in report.unresolved
    assert await _status(intent_id) == "UNKNOWN", "must not be resolved by silence"

    result = await gate.evaluate(INST, mode="paper", equity=D("30"),
                                 equity_is_real=True, run_id=run_id,
                                 reconciled=report.is_clean)
    assert "RECONCILE_INCOMPLETE" in result.codes


# ----------------------------------------------------------- positions -----
async def test_position_closed_while_down_is_detected(run_id, decision_id):
    """Ledger says we hold BTC; the venue says we hold none -> stop/TP filled."""
    intent_id = await _intent(run_id, decision_id, "FILLED")
    async with pool.ledger().acquire() as con:
        pid = await con.fetchval(
            """INSERT INTO positions (run_id, intent_id, inst_id, status,
                   initial_qty, avg_entry_px, initial_stop_px, frozen_risk_amount,
                   price_r_distance, qty_open, policy_version)
               VALUES ($1,$2,$3,'OPEN',0.01,100,98,0.02,2,0.01,'t')
               RETURNING position_id""", run_id, intent_id, INST)

    venue = PaperVenue(balances={"USDT": D("30")})   # no BTC held
    report = await _rec(venue, run_id).run()

    assert report.positions_closed_externally == 1
    async with pool.ledger().acquire() as con:
        row = await con.fetchrow(
            "SELECT status, qty_open FROM positions WHERE position_id=$1", pid)
    assert row["status"] == "CLOSED"
    assert row["qty_open"] == 0


async def _naked_position(run_id, decision_id) -> int:
    intent_id = await _intent(run_id, decision_id, "FILLED")
    async with pool.ledger().acquire() as con:
        return await con.fetchval(
            """INSERT INTO positions (run_id, intent_id, inst_id, status,
                   initial_qty, avg_entry_px, initial_stop_px, frozen_risk_amount,
                   price_r_distance, qty_open, policy_version)
               VALUES ($1,$2,$3,'OPEN',0.01,100,98,0.02,2,0.01,'t')
               RETURNING position_id""", run_id, intent_id, INST)


async def test_open_position_without_protection_is_re_armed(run_id, decision_id):
    """Reconciliation must RE-ARM a naked position, not just report it.

    Two consecutive live runs recorded `reconcile_unprotected` for the same
    position and then traded on around it. Detection without repair left real
    money exposed for two and a half hours.
    """
    pid = await _naked_position(run_id, decision_id)
    venue = PaperVenue(balances={"BTC": D("0.01"), "USDT": D("5")})
    report = await _rec(venue, run_id).run()

    assert report.protection_repaired == [pid]
    assert report.unprotected_positions == []
    assert report.is_clean
    assert await venue.get_algo_orders(INST), "no stop was actually placed"


async def test_position_that_cannot_be_re_armed_is_still_flagged(run_id, decision_id):
    """When the venue keeps refusing, the incident must survive the repair
    attempt rather than be swallowed by it."""
    class NoProtect(PaperVenue):
        async def place_oco(self, *a, **k):
            raise VenueRejected("ALGO_FAILED", "venue refused")

    pid = await _naked_position(run_id, decision_id)
    venue = NoProtect(balances={"BTC": D("0.01"), "USDT": D("5")})
    report = await _rec(venue, run_id).run()

    assert report.unprotected_positions == [pid]
    # It needs attention, but refusing to run would also refuse to manage it.
    assert report.is_clean
    async with pool.ledger().acquire() as con:
        n = await con.fetchval(
            """SELECT count(*) FROM ops_events
               WHERE run_id=$1 AND kind='reconcile_unprotected'""", run_id)
    assert n == 1


async def test_unexplained_inventory_is_reported_not_adopted(run_id, decision_id):
    """Stray base currency must never become a position with an invented entry."""
    venue = PaperVenue(balances={"BTC": D("0.5"), "USDT": D("30")})
    report = await _rec(venue, run_id).run()

    assert report.unexplained_balances.get("BTC") == "0.5"
    async with pool.ledger().acquire() as con:
        positions = await con.fetchval(
            "SELECT count(*) FROM positions WHERE run_id=$1", run_id)
    assert positions == 0, "stray balance was silently adopted as a position"


async def test_clean_slate_reconciles_clean(run_id):
    report = await _rec(PaperVenue(balances={"USDT": D("30")}), run_id).run()
    assert report.is_clean
    assert report.released_intents == 0
    assert report.unresolved == []
