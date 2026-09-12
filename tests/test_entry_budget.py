"""Entry-budget tests.

MAX_ENTRIES_PER_RUN arms a run for a fixed number of openings. It exists so a
first live entry can be watched end to end: the order goes out, and no second
one can follow while attention is elsewhere.

The budget is enforced twice on purpose -- in the gate, so the decision funnel
shows why a candidate was refused, and inside the reservation transaction, which
is the only check that cannot go stale between reading and inserting.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.db import pool
from agentic_trade.execution.order_manager import OrderManager, ReservationDenied
from agentic_trade.execution.venue import PaperVenue
from agentic_trade.risk import gate

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
INST = "BTC-USDT"


async def _reserve(om: OrderManager, decision_id: int, **over) -> int:
    """Reserve with concurrency deliberately wide, so only the budget can bite."""
    args = dict(
        decision_id=decision_id, inst_id=INST, side="buy",
        equity_at_decision=D("30"), risk_fraction=D("0.01"),
        risk_budget=D("0.3"), entry_reference=D("100"), structural_stop=D("98"),
        price_r_distance=D("2"), qty=D("0.01"), est_cost_per_unit=D("0.2"),
        policy_version="test_v1", max_concurrent=99,
    )
    args.update(over)
    return await om.reserve(**args)


async def _evaluate(run_id: int, budget: int):
    return await gate.evaluate(
        INST, mode="live", equity=D("30"), equity_is_real=True, run_id=run_id,
        reconciled=True,
        limits=gate.GateLimits(max_concurrent_positions=99,
                               max_entries_per_run=budget),
    )


# ------------------------------------------------------------ reservation ---
async def test_budget_of_one_allows_exactly_one_entry(run_id, decision_id):
    """The whole point: arm one entry, and the second attempt is refused."""
    om = OrderManager(PaperVenue(), run_id)
    await _reserve(om, decision_id, max_entries_per_run=1)
    with pytest.raises(ReservationDenied) as e:
        await _reserve(om, decision_id, max_entries_per_run=1)
    assert e.value.code == "ENTRY_BUDGET_EXHAUSTED"


async def test_budget_counts_attempts_not_fills(run_id, decision_id):
    """A rejected entry still spends the budget.

    The budget caps how many real orders leave the process. An attempt that the
    venue refused still reached the venue, so it counts -- otherwise a rejection
    loop could send unboundedly many orders while 'no entry has succeeded yet'.
    """
    om = OrderManager(PaperVenue(), run_id)
    intent_id = await _reserve(om, decision_id, max_entries_per_run=1)
    async with pool.ledger().acquire() as con:
        await con.execute(
            "UPDATE intents SET status='REJECTED' WHERE intent_id=$1", intent_id)
    with pytest.raises(ReservationDenied) as e:
        await _reserve(om, decision_id, max_entries_per_run=1)
    assert e.value.code == "ENTRY_BUDGET_EXHAUSTED"


async def test_zero_budget_means_unlimited(run_id, decision_id):
    """Default stays unlimited, so unarmed runs behave exactly as before."""
    om = OrderManager(PaperVenue(), run_id)
    for _ in range(3):
        await _reserve(om, decision_id, max_entries_per_run=0)
    async with pool.ledger().acquire() as con:
        count = await con.fetchval(
            "SELECT count(*) FROM intents WHERE run_id=$1", run_id)
    assert count == 3


async def test_budget_is_scoped_to_this_run(run_id, decision_id, db):
    """A spent budget must not leak across runs -- arming is per run."""
    om = OrderManager(PaperVenue(), run_id)
    await _reserve(om, decision_id, max_entries_per_run=1)
    async with pool.ledger().acquire() as con:
        other_run = await con.fetchval(
            """INSERT INTO runs (mode, site, demo, policy_version, notes)
               VALUES ('paper','tr',true,'test_v1','pytest-budget')
               RETURNING run_id""")
        other_decision = await con.fetchval(
            """INSERT INTO decisions (run_id, inst_id, action, setup_id,
                   reason_codes, stage_reached, features, policy_version,
                   data_quality)
               VALUES ($1,'BTC-USDT','BUY_INTENT','reclaim_v1','{}','CONFIRMED',
                       '{}','test_v1','{}')
               RETURNING decision_id""", other_run)
    try:
        om2 = OrderManager(PaperVenue(), other_run)
        assert await _reserve(om2, other_decision, max_entries_per_run=1)
    finally:
        async with pool.ledger().acquire() as con:
            await con.execute("DELETE FROM intents WHERE run_id=$1", other_run)
            await con.execute("DELETE FROM decisions WHERE run_id=$1", other_run)
            await con.execute("DELETE FROM runs WHERE run_id=$1", other_run)


# ------------------------------------------------------------------- gate ---
async def test_gate_reports_budget_exhausted(run_id, decision_id):
    """The funnel must say WHY, not silently stop producing entries."""
    before = await _evaluate(run_id, budget=1)
    assert "ENTRY_BUDGET_EXHAUSTED" not in before.codes

    await _reserve(OrderManager(PaperVenue(), run_id), decision_id,
                   max_entries_per_run=1)

    after = await _evaluate(run_id, budget=1)
    assert "ENTRY_BUDGET_EXHAUSTED" in after.codes
    assert after.allowed is False
    assert after.detail["entries_this_run"] == 1
    assert after.detail["entry_budget"] == 1


async def test_gate_unarmed_never_reports_budget(run_id, decision_id):
    await _reserve(OrderManager(PaperVenue(), run_id), decision_id,
                   max_entries_per_run=0)
    result = await _evaluate(run_id, budget=0)
    assert "ENTRY_BUDGET_EXHAUSTED" not in result.codes
    assert "entry_budget" not in result.detail


# ------------------------------------------------------- armed instruments ---
async def test_unarmed_instrument_is_refused(run_id):
    """Arming BTC must not let an ETH candidate through."""
    result = await gate.evaluate(
        "ETH-USDT", mode="live", equity=D("30"), equity_is_real=True,
        run_id=run_id, reconciled=True,
        limits=gate.GateLimits(max_concurrent_positions=99,
                               armed_instruments=frozenset({"BTC-USDT"})),
    )
    assert "INSTRUMENT_NOT_ARMED" in result.codes
    assert result.detail["armed_instruments"] == ["BTC-USDT"]


async def test_armed_instrument_is_not_refused(run_id):
    result = await gate.evaluate(
        INST, mode="live", equity=D("30"), equity_is_real=True, run_id=run_id,
        reconciled=True,
        limits=gate.GateLimits(max_concurrent_positions=99,
                               armed_instruments=frozenset({"BTC-USDT"})),
    )
    assert "INSTRUMENT_NOT_ARMED" not in result.codes


async def test_no_restriction_by_default(run_id):
    result = await gate.evaluate(
        "SOL-USDT", mode="live", equity=D("30"), equity_is_real=True,
        run_id=run_id, reconciled=True,
        limits=gate.GateLimits(max_concurrent_positions=99),
    )
    assert "INSTRUMENT_NOT_ARMED" not in result.codes
