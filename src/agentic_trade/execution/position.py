"""Position opening and exit-ladder management.

The R basis is frozen when the entry resolves and never recomputed: moving the
stop to breakeven or banking a partial does NOT shrink the denominator used for
reporting (AGENT.md §5).

Protection is sized to the quantity we ACTUALLY own, not the quantity we asked
for, and every exit leg is bounded by remaining inventory so competing exits can
never sell the same base twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import structlog

from ..db import pool
from ..risk.sizing import ExitPlan, InstrumentSpec, build_exit_plan
from .ids import new_client_order_id
from .venue import Venue, VenueRejected, VenueUnknown

log = structlog.get_logger(__name__)


@dataclass
class OpenedPosition:
    position_id: int
    plan: ExitPlan
    algo_id: str | None
    protection_error: str | None = None


async def open_position(
    venue: Venue,
    *,
    run_id: int,
    intent_id: int,
    inst_id: str,
    filled_qty: Decimal,
    avg_entry_px: Decimal,
    structural_stop: Decimal,
    spec: InstrumentSpec,
    est_cost_per_unit: Decimal,
    policy_version: str,
    fees_paid: Decimal = Decimal(0),
) -> OpenedPosition:
    """Record the position from real fills, then attach venue-side protection."""
    if filled_qty <= 0:
        raise ValueError("cannot open a position with zero filled quantity")

    plan = build_exit_plan(
        initial_qty=filled_qty,
        avg_entry_px=avg_entry_px,
        initial_stop_px=structural_stop,
        spec=spec,
        est_cost_per_unit=est_cost_per_unit,
    )

    async with pool.ledger().acquire() as con:
        position_id = await con.fetchval(
            """INSERT INTO positions (run_id, intent_id, inst_id, status,
                   initial_qty, avg_entry_px, initial_stop_px, frozen_risk_amount,
                   price_r_distance, qty_open, current_stop_px, fees_paid,
                   policy_version, entry_fees)
               VALUES ($1,$2,$3,'OPEN',$4,$5,$6,$7,$8,$4,$6,$9,$10,$9)
               RETURNING position_id""",
            run_id, intent_id, inst_id, filled_qty, avg_entry_px,
            plan.initial_stop_px, plan.frozen_risk_amount, plan.price_r_distance,
            fees_paid, policy_version,
        )

    # Protection goes on immediately, sized to actual inventory. A failure here
    # is loud: an unprotected position is an incident, not a detail.
    algo_id: str | None = None
    protection_error: str | None = None
    cid = new_client_order_id(intent_id, "STOP")
    try:
        algo_id = await venue.place_oco(
            inst_id, filled_qty, plan.tp2_trigger_px, plan.initial_stop_px, cid
        )
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                       inst_id, algo_id, purpose, side, ord_type, qty_requested,
                       status, sent_at, acked_at)
                   VALUES ($1,$2,$3,'okx-tr',$4,$5,'STOP','sell','oco',$6,'live',
                           now(),now())""",
                cid, intent_id, run_id, inst_id, algo_id, filled_qty,
            )
    except (VenueUnknown, VenueRejected) as exc:
        protection_error = str(exc)[:300]
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO ops_events (run_id, severity, kind, inst_id, detail)
                   VALUES ($1,'error','protection_failed',$2,$3)""",
                run_id, inst_id, json.dumps({
                    "position_id": position_id,
                    "error": protection_error,
                    "impact": "position is OPEN without venue-side protection",
                }),
            )
        log.error("position.unprotected", position_id=position_id,
                  err=protection_error)

    log.info("position.opened", position_id=position_id, inst=inst_id,
             qty=str(filled_qty), entry=str(avg_entry_px),
             stop=str(plan.initial_stop_px), protected=algo_id is not None)
    return OpenedPosition(position_id, plan, algo_id, protection_error)


async def sellable_qty(position_id: int) -> Decimal:
    """Base quantity still available to sell for this position.

    Bounded by what remains open, so two exit legs racing cannot oversell.
    """
    async with pool.ledger().acquire() as con:
        row = await con.fetchrow(
            "SELECT qty_open FROM positions WHERE position_id=$1", position_id)
    return Decimal(row["qty_open"]) if row else Decimal(0)


async def apply_breakeven(position_id: int, avg_entry_px: Decimal) -> bool:
    """Move the stop to the real average entry, once, at +1R.

    Returns True only if this call performed the move, so a repeated +1R trigger
    cannot re-apply it.
    """
    async with pool.ledger().acquire() as con:
        moved = await con.fetchval(
            """UPDATE positions SET current_stop_px=$2, breakeven_moved=TRUE
               WHERE position_id=$1 AND breakeven_moved=FALSE AND status='OPEN'
               RETURNING position_id""",
            position_id, avg_entry_px)
    return moved is not None


async def claim_tp_stage(position_id: int, stage: str) -> Decimal | None:
    """Atomically claim one take-profit stage.

    Returns the quantity to sell, or None if the stage was already taken. The
    UPDATE ... WHERE <flag> IS FALSE makes a repeated +2R trigger a no-op rather
    than a second sale.
    """
    if stage not in {"tp1", "tp2"}:
        raise ValueError(stage)
    flag = f"{stage}_done"
    fraction = Decimal("0.30") if stage == "tp1" else Decimal("0.60")
    async with pool.ledger().acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                f"""UPDATE positions SET {flag}=TRUE
                    WHERE position_id=$1 AND {flag}=FALSE AND status='OPEN'
                    RETURNING initial_qty, qty_open""",
                position_id)
            if row is None:
                return None
            want = Decimal(row["initial_qty"]) * fraction
            # Never sell more than is actually left.
            return min(want, Decimal(row["qty_open"]))


async def record_exit_fill(
    position_id: int, qty: Decimal, px: Decimal, fee: Decimal,
    avg_entry_px: Decimal,
) -> None:
    """Reduce inventory and accrue realised NET PnL from a real exit fill.

    Net means net of BOTH sides: the exit fee, plus this slice's pro-rata share
    of the entry fee. Counting only exit fees overstates realised R by the entry
    cost, which is exactly the number the R report is meant to be honest about.
    """
    async with pool.ledger().acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                """SELECT initial_qty, entry_fees FROM positions
                   WHERE position_id=$1 FOR UPDATE""", position_id)
            if row is None:
                raise ValueError(f"unknown position {position_id}")
            initial = Decimal(row["initial_qty"])
            entry_fee_share = (
                Decimal(row["entry_fees"]) * qty / initial if initial > 0
                else Decimal(0)
            )
            pnl = (px - avg_entry_px) * qty - fee - entry_fee_share
            await con.execute(
                """UPDATE positions
                   SET qty_open = greatest(qty_open - $2, 0),
                       realized_pnl = realized_pnl + $3,
                       fees_paid = fees_paid + $4,
                       status = CASE WHEN qty_open - $2 <= 0 THEN 'CLOSED'
                                     ELSE status END,
                       closed_at = CASE WHEN qty_open - $2 <= 0 THEN now()
                                        ELSE closed_at END
                   WHERE position_id=$1""",
                position_id, qty, pnl, fee)
