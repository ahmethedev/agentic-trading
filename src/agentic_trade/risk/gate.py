"""Pre-trade risk gate.

Deterministic checks that run BEFORE any sizing or reservation. Every rejection
carries a stable code so the dashboard funnel can show exactly what stopped a
trade. The agent cannot bypass or soften any of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..db import pool


@dataclass
class GateResult:
    allowed: bool
    codes: list[str]
    detail: dict[str, object]


@dataclass
class GateLimits:
    max_concurrent_positions: int = 1
    # Entries this run may open in total. 0 = unlimited. Set to 1 to arm exactly
    # one supervised entry: once it is reserved, the gate stops authorising new
    # ones. This caps OPENINGS only -- exits and protection are never gated.
    max_entries_per_run: int = 0
    # Instruments entries are allowed on. None = no restriction. Narrowing this
    # gates OPENINGS only; data collection and exits are untouched.
    armed_instruments: frozenset[str] | None = None
    # Daily realised-loss budget as a fraction of the session's opening equity.
    daily_loss_fraction: Decimal = Decimal("0.03")
    max_data_age_s: float = 45.0
    # Stop opening new entries this long before the competition cutoff.
    entry_cutoff_buffer_min: int = 45


async def evaluate(
    inst_id: str,
    *,
    mode: str,
    equity: Decimal,
    equity_is_real: bool,
    run_id: int,
    reconciled: bool = False,
    limits: GateLimits | None = None,
    now: datetime | None = None,
    cutoff: datetime | None = None,
) -> GateResult:
    """Run all pre-trade checks. Collects every reason, not just the first."""
    limits = limits or GateLimits()
    now = now or datetime.now(UTC)
    codes: list[str] = []
    detail: dict[str, object] = {}

    if mode == "observe":
        codes.append("OBSERVE_MODE_NO_ORDERS")

    # No entry may be opened until startup reconciliation has agreed the ledger
    # with the venue. A restart mid-order otherwise risks a duplicate position.
    if not reconciled:
        codes.append("RECONCILE_INCOMPLETE")

    if not equity_is_real:
        codes.append("EQUITY_NOT_VERIFIED")
    if equity <= 0:
        codes.append("NO_EQUITY")

    async with pool.ledger().acquire() as con:
        open_positions = await con.fetchval(
            "SELECT count(*) FROM positions WHERE status <> 'CLOSED'")
        pending = await con.fetchval(
            """SELECT count(*) FROM intents WHERE status NOT IN
               ('FILLED','CANCELLED','REJECTED','EXPIRED','RECONCILED')""")
        # An UNKNOWN order is unresolved exposure: never start a new entry while
        # one exists (AGENT.md §5).
        unknown = await con.fetchval(
            "SELECT count(*) FROM intents WHERE status = 'UNKNOWN'")
        # Entries this run has already claimed, whatever became of them. A
        # rejected or unfilled attempt still spends the budget: the point is to
        # cap how many real orders leave the process, not how many worked.
        entries_this_run = await con.fetchval(
            "SELECT count(*) FROM intents WHERE run_id=$1 AND side='buy'", run_id)
        realised_today = await con.fetchval(
            """SELECT coalesce(sum(realized_pnl),0) FROM positions
               WHERE run_id=$1 AND closed_at::date = $2::date""",
            run_id, now)
        fees_today = await con.fetchval(
            """SELECT coalesce(sum(fee),0) FROM fills
               WHERE run_id=$1 AND ts::date = $2::date""", run_id, now)

    detail["open_positions"] = open_positions
    detail["pending_intents"] = pending
    detail["unknown_intents"] = unknown

    if unknown:
        codes.append("UNRESOLVED_ORDER")
    if open_positions + pending >= limits.max_concurrent_positions:
        codes.append("CONCURRENCY_LIMIT")

    if limits.armed_instruments is not None and inst_id not in limits.armed_instruments:
        detail["armed_instruments"] = sorted(limits.armed_instruments)
        codes.append("INSTRUMENT_NOT_ARMED")

    detail["entries_this_run"] = entries_this_run
    if limits.max_entries_per_run:
        detail["entry_budget"] = limits.max_entries_per_run
        if entries_this_run >= limits.max_entries_per_run:
            codes.append("ENTRY_BUDGET_EXHAUSTED")

    # Realised PnL is net of fees; both count against the daily budget.
    day_pnl = Decimal(realised_today) - Decimal(fees_today)
    detail["day_net_pnl"] = str(day_pnl)
    if equity > 0:
        budget = equity * limits.daily_loss_fraction
        detail["daily_loss_budget"] = str(budget)
        if day_pnl <= -budget:
            codes.append("DAILY_LOSS_LIMIT")

    # Data health: a stale feed must block entries but never block exits.
    async with pool.market().acquire() as con:
        age = await con.fetchval(
            """SELECT EXTRACT(EPOCH FROM (now() - max(ts)))
               FROM market_trades WHERE inst_id=$1""", inst_id)
    detail["data_age_s"] = float(age) if age is not None else None
    if age is None or float(age) > limits.max_data_age_s:
        codes.append("DATA_STALE")

    if cutoff is not None:
        minutes_left = (cutoff - now).total_seconds() / 60
        detail["minutes_to_cutoff"] = round(minutes_left, 1)
        if minutes_left <= limits.entry_cutoff_buffer_min:
            codes.append("PAST_ENTRY_CUTOFF")

    return GateResult(allowed=not codes, codes=codes, detail=detail)
