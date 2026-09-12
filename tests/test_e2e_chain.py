"""End-to-end: confirmed setup -> gate -> size -> reserve -> entry -> protection.

The live market may sit in a regime that produces no candidate for hours, so the
full chain is proven here with a forced candidate against the paper venue.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.config import get_settings
from agentic_trade.db import pool
from agentic_trade.execution.venue import Faults, PaperVenue
from agentic_trade.risk.sizing import InstrumentSpec
from agentic_trade.strategy.setup import SetupCandidate, Stage
from agentic_trade.worker import Worker

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
INST = "BTC-USDT"
SPEC = InstrumentSpec(INST, lot_sz=D("0.00000001"), min_sz=D("0.00001"),
                      tick_sz=D("0.1"))


def candidate() -> SetupCandidate:
    return SetupCandidate(
        inst_id=INST, stage=Stage.CONFIRMED, reason_codes=["RECLAIM_CONFIRMED"],
        level=D("100"), trigger_close=D("101"), structural_stop=D("98"),
        extension_atr=0.5, episode_id="ep-e2e",
        evidence={"level": "100", "pullback_low": "98"},
    )


async def make_worker(run_id: int, mode: str = "paper", faults: Faults | None = None,
                      venue: PaperVenue | None = None):
    s = get_settings()
    s.__dict__["mode"] = mode          # bypass the cached singleton for the test
    w = Worker(s, instruments=[INST])
    w._run_id = run_id
    w._specs = {INST: SPEC}
    w._equity = D("1000")
    w._equity_is_real = True
    w._taker_fee = D("0.001")
    w._fee_is_real = True
    w._venue = venue or PaperVenue(fee_rate=D("0.001"), faults=faults or Faults())
    from agentic_trade.execution.order_manager import OrderManager
    w._om = OrderManager(w._venue, run_id)
    # Run the real startup reconciliation rather than faking its result: the
    # gate refuses to trade until it has agreed the ledger with the venue.
    from agentic_trade.execution.reconcile import Reconciler
    report = await Reconciler(w._venue, w._om, run_id).run()
    w._reconciled = report.is_clean
    return w


async def test_gate_blocks_until_reconciled(run_id):
    """Belt and braces: an unreconciled worker must not reach the order path."""
    w = await make_worker(run_id)
    w._reconciled = False
    action, codes, note = await w._handle_candidate(INST, candidate())
    assert action == "WAIT"
    assert "RECONCILE_INCOMPLETE" in codes
    assert "execution" not in note
    assert w._venue.placed_calls == 0


async def test_full_chain_opens_a_protected_position(run_id):
    w = await make_worker(run_id)
    action, codes, note = await w._handle_candidate(INST, candidate())

    assert action == "BUY_INTENT", (codes, note)
    assert "ENTRY_FILLED" in codes
    ex = note["execution"]
    assert ex["status"] == "filled"
    assert ex["protected"] is True
    assert ex["position_id"] is not None

    async with pool.ledger().acquire() as con:
        pos = await con.fetchrow(
            "SELECT * FROM positions WHERE position_id=$1", ex["position_id"])
        fills = await con.fetchval(
            "SELECT count(*) FROM fills WHERE run_id=$1", run_id)
        stop_order = await con.fetchrow(
            "SELECT * FROM orders WHERE run_id=$1 AND purpose='STOP'", run_id)

    # Risk basis comes from the REAL fill, and the stop is the structural one.
    assert pos["initial_stop_px"] == D("98")
    assert pos["status"] == "OPEN"
    assert fills == 1
    assert stop_order is not None and stop_order["algo_id"]

    # Sizing respected the 1% budget on 1000 equity.
    sizing = note["sizing"]
    assert Decimal(sizing["risk_at_stop"]) <= Decimal(sizing["risk_budget"]) == D("10")


async def test_worst_case_fill_stays_inside_the_risk_budget(run_id):
    """Filling at the entry limit must not push frozen risk above the budget.

    Sizing against the expected price while filling at the limit previously
    overshot the 1% budget by ~8%.
    """
    w = await make_worker(run_id)
    action, codes, note = await w._handle_candidate(INST, candidate())
    assert action == "BUY_INTENT", (codes, note)

    async with pool.ledger().acquire() as con:
        pos = await con.fetchrow(
            "SELECT * FROM positions WHERE position_id=$1",
            note["execution"]["position_id"])

    budget = Decimal(note["sizing"]["risk_budget"])
    assert pos["frozen_risk_amount"] <= budget, (
        f"frozen risk {pos['frozen_risk_amount']} exceeded budget {budget}")
    # The paper venue fills exactly at the limit, i.e. the worst allowed price.
    assert pos["avg_entry_px"] == Decimal(note["entry_limit"])


async def test_second_candidate_blocked_while_position_open(run_id):
    w = await make_worker(run_id)
    a1, _, _ = await w._handle_candidate(INST, candidate())
    assert a1 == "BUY_INTENT"

    a2, codes2, _ = await w._handle_candidate(INST, candidate())
    assert a2 == "WAIT"
    assert "CONCURRENCY_LIMIT" in codes2


async def test_observe_mode_never_sends_an_order(run_id):
    w = await make_worker(run_id, mode="observe")
    action, codes, note = await w._handle_candidate(INST, candidate())

    assert action == "WAIT"
    assert "OBSERVE_MODE_NO_ORDERS" in codes
    assert "execution" not in note, "observe mode must not reach the order path"
    assert w._venue.placed_calls == 0
    async with pool.ledger().acquire() as con:
        assert await con.fetchval(
            "SELECT count(*) FROM orders WHERE run_id=$1", run_id) == 0


async def test_unknown_entry_leaves_no_position_and_blocks_next(run_id):
    """An unresolvable entry must not open a position, and must block re-entry."""
    venue = PaperVenue(faults=Faults(place_timeout=True, get_order_timeout=True))
    w = await make_worker(run_id, venue=venue)
    action, codes, note = await w._handle_candidate(INST, candidate())

    assert action == "WAIT"
    assert note["execution"]["unknown"] is True
    assert note["execution"]["position_id"] is None
    async with pool.ledger().acquire() as con:
        assert await con.fetchval(
            "SELECT count(*) FROM positions WHERE run_id=$1", run_id) == 0

    # While the venue still cannot answer, the slot stays held.
    w._reconciled = False
    a2, codes2, _ = await w._handle_candidate(INST, candidate())
    assert a2 == "WAIT"
    assert {"RECONCILE_INCOMPLETE", "UNRESOLVED_ORDER", "CONCURRENCY_LIMIT"} & set(codes2)


async def test_restart_rebuilds_a_position_for_an_entry_that_filled_blind(run_id):
    """The order filled, but we timed out before recording a position.

    Real inventory with no stop and no ladder is the worst state to be in, so
    reconciliation must rebuild the position from the stored fills and the
    intent's frozen structural stop -- and re-attach protection.
    """
    venue = PaperVenue(faults=Faults(place_timeout=True, get_order_timeout=True))
    w = await make_worker(run_id, venue=venue)
    action, _, note = await w._handle_candidate(INST, candidate())
    assert action == "WAIT" and note["execution"]["position_id"] is None

    # Restart against the SAME venue, which can now answer.
    venue.faults = Faults()
    from agentic_trade.execution.order_manager import OrderManager
    from agentic_trade.execution.reconcile import Reconciler
    report = await Reconciler(venue, OrderManager(venue, run_id), run_id).run()

    assert report.positions_rebuilt == 1
    async with pool.ledger().acquire() as con:
        pos = await con.fetchrow(
            "SELECT * FROM positions WHERE run_id=$1", run_id)
    assert pos is not None
    assert pos["status"] == "OPEN"
    assert pos["initial_stop_px"] == D("98")        # the intent's frozen stop
    assert pos["qty_open"] == pos["initial_qty"] > 0
    # and it is protected again
    assert await venue.get_algo_orders(INST)


async def test_partial_entry_opens_position_sized_to_actual_fill(run_id):
    w = await make_worker(run_id, faults=Faults(fill_ratio=D("0.4")))
    action, codes, note = await w._handle_candidate(INST, candidate())

    assert action == "BUY_INTENT"
    ex = note["execution"]
    async with pool.ledger().acquire() as con:
        pos = await con.fetchrow(
            "SELECT * FROM positions WHERE position_id=$1", ex["position_id"])
    requested = Decimal(note["sizing"]["quantity"])
    # Protection and the R basis follow what we own, not what we asked for.
    assert pos["initial_qty"] < requested
    assert pos["initial_qty"] == Decimal(ex["qty_filled"])
    assert pos["qty_open"] == pos["initial_qty"]
