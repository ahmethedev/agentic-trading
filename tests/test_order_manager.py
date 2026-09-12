"""Order lifecycle integration tests.

Each test provokes one of the failure modes AGENT.md §11 requires the system to
survive, using the paper venue's deterministic fault injection.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.db import pool
from agentic_trade.execution.order_manager import (
    OrderManager,
    ReservationDenied,
)
from agentic_trade.execution.venue import Faults, OrdStatus, PaperVenue

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
INST = "BTC-USDT"
DEFAULT_QTY = D("0.01")


async def _reserve(om: OrderManager, decision_id: int,
                   qty: Decimal = DEFAULT_QTY) -> int:
    return await om.reserve(
        decision_id=decision_id, inst_id=INST, side="buy",
        equity_at_decision=D("1000"), risk_fraction=D("0.01"),
        risk_budget=D("10"), entry_reference=D("100"), structural_stop=D("98"),
        price_r_distance=D("2"), qty=qty, est_cost_per_unit=D("0.2"),
        policy_version="test_v1",
    )


async def _intent_status(intent_id: int) -> str:
    async with pool.ledger().acquire() as con:
        return await con.fetchval(
            "SELECT status FROM intents WHERE intent_id=$1", intent_id)


async def _order_row(cid: str):
    async with pool.ledger().acquire() as con:
        return await con.fetchrow(
            "SELECT * FROM orders WHERE client_order_id=$1", cid)


# ------------------------------------------------------------ reservation ---
async def test_second_reservation_is_denied_by_concurrency_limit(run_id, decision_id):
    """Two candidates must not both claim the single allowed position."""
    om = OrderManager(PaperVenue(), run_id)
    await _reserve(om, decision_id)
    with pytest.raises(ReservationDenied) as e:
        await _reserve(om, decision_id)
    assert e.value.code == "CONCURRENCY_LIMIT"


async def test_intent_is_durable_before_send(run_id, decision_id):
    intent_id = await _reserve(om := OrderManager(PaperVenue(), run_id), decision_id)
    assert await _intent_status(intent_id) == "RESERVED"
    assert om is not None


# ------------------------------------------------------------------ entry ---
async def test_clean_fill_records_order_fill_and_fees(run_id, decision_id):
    om = OrderManager(PaperVenue(), run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    assert out.status is OrdStatus.FILLED
    assert out.qty_filled == D("0.01")
    qty, avg, fee = await om.filled_totals(out.client_order_id)
    assert qty == D("0.01")
    assert avg == D("100")
    assert fee > 0
    assert await _intent_status(intent_id) == "FILLED"


async def test_partial_fill_is_a_real_position_not_a_cancellation(run_id, decision_id):
    """An IOC that half-fills ends CANCELED at the venue but we DO own inventory."""
    venue = PaperVenue(faults=Faults(fill_ratio=D("0.5")))
    om = OrderManager(venue, run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    assert out.qty_filled == D("0.005")
    qty, _, _ = await om.filled_totals(out.client_order_id)
    assert qty == D("0.005")
    assert await _intent_status(intent_id) == "PARTIAL"


# ---------------------------------------------------------------- unknown ---
async def test_timeout_is_resolved_by_query_not_by_resend(run_id, decision_id):
    """The order DID reach the venue; a blind resend would double the position."""
    venue = PaperVenue(faults=Faults(place_timeout=True))
    om = OrderManager(venue, run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    assert venue.placed_calls == 1, "must never resend after a timeout"
    assert out.status is OrdStatus.FILLED
    assert out.qty_filled == D("0.01")
    assert await _intent_status(intent_id) == "FILLED"

    async with pool.ledger().acquire() as con:
        orders = await con.fetchval(
            "SELECT count(*) FROM orders WHERE intent_id=$1", intent_id)
        events = await con.fetch(
            """SELECT event_type FROM order_events
               WHERE client_order_id=$1 ORDER BY event_id""", out.client_order_id)
    assert orders == 1, "a timeout must not create a second order row"
    assert [e["event_type"] for e in events][:2] == ["TIMEOUT", "RECONCILE"]


async def test_unresolvable_timeout_stays_unknown_and_blocks(run_id, decision_id):
    """If we cannot reach the venue at all, we must NOT assume the order failed."""
    venue = PaperVenue(faults=Faults(place_timeout=True, get_order_timeout=True))
    om = OrderManager(venue, run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    assert out.unknown is True
    assert out.status is OrdStatus.UNKNOWN
    assert await _intent_status(intent_id) == "UNKNOWN"
    # An UNKNOWN intent still consumes the slot, so no new entry can start.
    with pytest.raises(ReservationDenied):
        await _reserve(om, decision_id)


# ------------------------------------------------------------------ fills ---
async def test_duplicate_fills_are_counted_once(run_id, decision_id):
    """The same venue fill id reported twice must not double the position."""
    venue = PaperVenue(faults=Faults(duplicate_fills=True))
    om = OrderManager(venue, run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    qty, _, _ = await om.filled_totals(out.client_order_id)
    assert qty == D("0.01"), "duplicate fill inflated the position"
    async with pool.ledger().acquire() as con:
        n = await con.fetchval(
            "SELECT count(*) FROM fills WHERE client_order_id=$1", out.client_order_id)
    assert n == 1


async def test_repeated_ingest_is_idempotent(run_id, decision_id):
    om = OrderManager(PaperVenue(), run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))
    before, _, _ = await om.filled_totals(out.client_order_id)
    # Reconciling again (as a restart would) must change nothing.
    await om.resolve_unknown(out.client_order_id, INST, intent_id)
    after, _, _ = await om.filled_totals(out.client_order_id)
    assert before == after


# --------------------------------------------------------------- rejected ---
async def test_rejection_is_not_retried(run_id, decision_id):
    venue = PaperVenue(faults=Faults(place_reject="INSUFFICIENT_BALANCE"))
    om = OrderManager(venue, run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))

    assert out.status is OrdStatus.REJECTED
    assert out.qty_filled == 0
    assert venue.placed_calls == 1
    assert await _intent_status(intent_id) == "REJECTED"


async def test_rejected_intent_frees_the_slot(run_id, decision_id):
    """A definitively rejected entry must not hold the position slot forever."""
    om = OrderManager(PaperVenue(faults=Faults(place_reject="BAD_SIZE")), run_id)
    intent_id = await _reserve(om, decision_id)
    await om.submit_entry(intent_id, INST, D("0.01"), D("100"))
    assert await _intent_status(intent_id) == "REJECTED"
    await _reserve(OrderManager(PaperVenue(), run_id), decision_id)   # must not raise


# --------------------------------------------------------- terminal state ---
async def test_late_ack_cannot_rewind_terminal_state(run_id, decision_id):
    """A stale 'live' ack arriving after a fill must not reopen the order."""
    om = OrderManager(PaperVenue(), run_id)
    intent_id = await _reserve(om, decision_id)
    out = await om.submit_entry(intent_id, INST, D("0.01"), D("100"))
    row = await _order_row(out.client_order_id)
    assert row["terminal_at"] is not None

    from agentic_trade.execution.venue import OrderState
    stale = OrderState(out.client_order_id, "ordX", INST, "buy", OrdStatus.LIVE,
                       D("0.01"), D("0"), None)
    await om._record_state(out.client_order_id, stale, event="LATE_ACK")

    row2 = await _order_row(out.client_order_id)
    assert row2["status"] == str(OrdStatus.FILLED)
    assert row2["qty_filled"] == D("0.01"), "filled quantity moved backwards"
