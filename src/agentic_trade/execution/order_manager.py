"""Order lifecycle: intent -> reservation -> order -> fill -> reconcile.

The rules this class exists to enforce (AGENT.md §5):

  1. A durable intent + reservation is written BEFORE anything is sent, so a
     crash between send and ack is always recoverable.
  2. A timeout is UNKNOWN, never "did not happen". The only resolution is to ask
     the venue about our client order id -- never a blind resend.
  3. A fill may arrive before the ack, and a late ack must not rewind a terminal
     state. The same fill is never counted twice.
  4. Partial fills take effect immediately; protection is sized to what we
     actually own.
  5. Spot sells are bounded by base actually held. Competing exits cannot spend
     the same inventory twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import asyncpg
import structlog

from ..db import pool
from .ids import new_client_order_id
from .venue import (
    TERMINAL,
    OrderState,
    OrdStatus,
    Venue,
    VenueRejected,
    VenueUnknown,
)

log = structlog.get_logger(__name__)

VENUE = "okx-tr"


class ReservationDenied(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class EntryOutcome:
    client_order_id: str
    status: OrdStatus
    qty_filled: Decimal
    avg_px: Decimal | None
    fees: Decimal
    unknown: bool = False


class OrderManager:
    """Single owner of the order path. One instance per worker."""

    def __init__(self, venue: Venue, run_id: int) -> None:
        self._venue = venue
        self._run_id = run_id

    # ------------------------------------------------------- reservation ----
    async def reserve(
        self, *, decision_id: int, inst_id: str, side: str,
        equity_at_decision: Decimal, risk_fraction: Decimal, risk_budget: Decimal,
        entry_reference: Decimal, structural_stop: Decimal,
        price_r_distance: Decimal, qty: Decimal, est_cost_per_unit: Decimal,
        policy_version: str, max_concurrent: int = 1,
    ) -> int:
        """Persist an intent and claim the position slot, atomically.

        The concurrency check and the insert happen in ONE transaction under a
        lock, so two candidates evaluated at the same moment cannot both believe
        they own the only allowed position.
        """
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                # Serialise all reservation attempts for this run.
                await con.execute("SELECT pg_advisory_xact_lock($1)", self._run_id)

                open_positions = await con.fetchval(
                    "SELECT count(*) FROM positions WHERE status <> 'CLOSED'"
                )
                pending = await con.fetchval(
                    """SELECT count(*) FROM intents
                       WHERE status NOT IN
                         ('FILLED','CANCELLED','REJECTED','EXPIRED','RECONCILED')"""
                )
                # Pending entries consume the budget just like open positions do.
                if open_positions + pending >= max_concurrent:
                    raise ReservationDenied(
                        "CONCURRENCY_LIMIT",
                        f"{open_positions} open + {pending} pending >= {max_concurrent}",
                    )

                intent_id = await con.fetchval(
                    """INSERT INTO intents (decision_id, run_id, inst_id, side, status,
                           equity_at_decision, risk_fraction, risk_budget,
                           entry_reference, structural_stop, price_r_distance,
                           qty_requested, est_cost_per_unit, policy_version)
                       VALUES ($1,$2,$3,$4,'RESERVED',$5,$6,$7,$8,$9,$10,$11,$12,$13)
                       RETURNING intent_id""",
                    decision_id, self._run_id, inst_id, side, equity_at_decision,
                    risk_fraction, risk_budget, entry_reference, structural_stop,
                    price_r_distance, qty, est_cost_per_unit, policy_version,
                )
        log.info("order.reserved", intent_id=intent_id, inst=inst_id, qty=str(qty))
        return intent_id

    # ------------------------------------------------------------- entry ----
    async def submit_entry(
        self, intent_id: int, inst_id: str, qty: Decimal, px_limit: Decimal
    ) -> EntryOutcome:
        """Send a marketable limit IOC entry and record the outcome durably."""
        cid = new_client_order_id(intent_id, "ENTRY")

        # Durable BEFORE the wire: if we crash now, recovery finds this row and
        # asks the venue about `cid` instead of assuming nothing was sent.
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                           inst_id, purpose, side, ord_type, px_limit, qty_requested,
                           status, sent_at)
                       VALUES ($1,$2,$3,$4,$5,'ENTRY','buy','ioc',$6,$7,'SENDING',now())""",
                    cid, intent_id, self._run_id, VENUE, inst_id, px_limit, qty,
                )
                await con.execute(
                    "UPDATE intents SET status='SENT' WHERE intent_id=$1", intent_id
                )

        try:
            state = await self._venue.place_limit_ioc(
                inst_id, "buy", qty, px_limit, cid
            )
        except VenueUnknown as exc:
            await self._mark_unknown(cid, intent_id, str(exc))
            resolved = await self.resolve_unknown(cid, inst_id, intent_id)
            return resolved
        except VenueRejected as exc:
            await self._mark_rejected(cid, intent_id, exc.code, exc.message)
            return EntryOutcome(cid, OrdStatus.REJECTED, Decimal(0), None, Decimal(0))

        await self._record_state(cid, state, event="ACK")
        fees = await self._ingest_fills(inst_id, cid)
        fresh = await self._venue.get_order(inst_id, cid)
        await self._record_state(cid, fresh, event="POLL")
        await self._sync_intent(intent_id, fresh)
        return EntryOutcome(cid, fresh.status, fresh.qty_filled, fresh.avg_px, fees)

    # --------------------------------------------------------- reconcile ----
    async def resolve_unknown(
        self, cid: str, inst_id: str, intent_id: int
    ) -> EntryOutcome:
        """Resolve an UNKNOWN outcome by asking the venue about our client id.

        This never resends. Either the venue knows the id -- in which case its
        answer is the truth -- or it does not, and the intent is closed out as
        never-placed only because the venue said so.
        """
        try:
            state = await self._venue.get_order(inst_id, cid)
        except VenueUnknown as exc:
            # Still unknown: leave the intent UNKNOWN and block new entries.
            log.error("order.unresolved", cid=cid, err=str(exc)[:200])
            await self._ops("error", "order_unresolved", inst_id,
                            {"client_order_id": cid, "error": str(exc)[:300]})
            return EntryOutcome(cid, OrdStatus.UNKNOWN, Decimal(0), None,
                                Decimal(0), unknown=True)

        if state.status is OrdStatus.UNKNOWN:
            # The venue has no such order: it genuinely never landed.
            await self._record_state(cid, state, event="RECONCILE_NOT_FOUND")
            async with pool.ledger().acquire() as con:
                await con.execute(
                    "UPDATE orders SET status='NOT_PLACED', terminal_at=now(), "
                    "last_reconciled_at=now() WHERE client_order_id=$1", cid)
                await con.execute(
                    "UPDATE intents SET status='RECONCILED' WHERE intent_id=$1",
                    intent_id)
            log.warning("order.never_placed", cid=cid)
            return EntryOutcome(cid, OrdStatus.CANCELED, Decimal(0), None, Decimal(0))

        await self._record_state(cid, state, event="RECONCILE")
        fees = await self._ingest_fills(inst_id, cid)
        await self._sync_intent(intent_id, state)
        log.info("order.reconciled", cid=cid, status=str(state.status),
                 filled=str(state.qty_filled))
        return EntryOutcome(cid, state.status, state.qty_filled, state.avg_px, fees)

    # ------------------------------------------------------------- fills ----
    async def _ingest_fills(self, inst_id: str, cid: str) -> Decimal:
        """Store fills idempotently; return total fee for THIS ingest call.

        Deduplication is by the venue fill id, enforced by the primary key, so a
        fill seen from both polling and reconciliation is counted exactly once.
        """
        try:
            fills = await self._venue.get_fills(inst_id, cid)
        except VenueUnknown as exc:
            log.warning("order.fills_unavailable", cid=cid, err=str(exc)[:150])
            return Decimal(0)

        total_fee = Decimal(0)
        async with pool.ledger().acquire() as con:
            for f in fills:
                inserted = await con.fetchval(
                    """INSERT INTO fills (venue, fill_id, client_order_id,
                           exchange_order_id, inst_id, side, px, qty, fee, fee_ccy,
                           liquidity, ts, run_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                       ON CONFLICT (venue, fill_id) DO NOTHING
                       RETURNING fill_id""",
                    VENUE, f.fill_id, f.client_order_id, f.exchange_order_id,
                    f.inst_id, f.side, f.px, f.qty, f.fee, f.fee_ccy,
                    f.liquidity, f.ts, self._run_id,
                )
                if inserted is not None:
                    total_fee += f.fee
        return total_fee

    async def filled_totals(self, cid: str) -> tuple[Decimal, Decimal, Decimal]:
        """(qty, weighted avg px, fees) computed from STORED fills only."""
        async with pool.ledger().acquire() as con:
            row = await con.fetchrow(
                """SELECT coalesce(sum(qty),0) AS q,
                          coalesce(sum(px*qty),0) AS notional,
                          coalesce(sum(fee),0) AS fee
                   FROM fills WHERE client_order_id=$1""", cid)
        q = Decimal(row["q"])
        avg = (Decimal(row["notional"]) / q) if q > 0 else Decimal(0)
        return q, avg, Decimal(row["fee"])

    # ------------------------------------------------------------ helpers ---
    async def _record_state(self, cid: str, state: OrderState, *, event: str) -> None:
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """INSERT INTO order_events (client_order_id, event_type, payload)
                       VALUES ($1,$2,$3)""",
                    cid, event, json.dumps({
                        "status": str(state.status),
                        "qty_filled": str(state.qty_filled),
                        "avg_px": str(state.avg_px) if state.avg_px else None,
                        "exchange_order_id": state.exchange_order_id,
                    }),
                )
                # A late ack must never rewind a terminal state, and filled
                # quantity must never move backwards.
                await con.execute(
                    """UPDATE orders SET
                           exchange_order_id = coalesce(orders.exchange_order_id, $2),
                           status = CASE WHEN orders.terminal_at IS NOT NULL
                                         THEN orders.status ELSE $3 END,
                           qty_filled = greatest(orders.qty_filled, $4),
                           avg_px = coalesce($5, orders.avg_px),
                           acked_at = coalesce(orders.acked_at, now()),
                           terminal_at = CASE
                               WHEN orders.terminal_at IS NOT NULL THEN orders.terminal_at
                               WHEN $6 THEN now() ELSE NULL END,
                           last_reconciled_at = now()
                       WHERE client_order_id = $1""",
                    cid, state.exchange_order_id, str(state.status),
                    state.qty_filled, state.avg_px, state.status in TERMINAL,
                )

    async def _sync_intent(self, intent_id: int, state: OrderState) -> None:
        mapping = {
            OrdStatus.FILLED: "FILLED",
            OrdStatus.PARTIALLY_FILLED: "PARTIAL",
            OrdStatus.CANCELED: "CANCELLED",
            OrdStatus.REJECTED: "REJECTED",
            OrdStatus.LIVE: "ACKED",
            OrdStatus.UNKNOWN: "UNKNOWN",
        }
        # A partly-filled IOC ends CANCELED at the venue but is a real position.
        status = mapping[state.status]
        if state.status is OrdStatus.CANCELED and state.qty_filled > 0:
            status = "PARTIAL"
        async with pool.ledger().acquire() as con:
            await con.execute(
                "UPDATE intents SET status=$2 WHERE intent_id=$1", intent_id, status)

    async def _mark_unknown(self, cid: str, intent_id: int, detail: str) -> None:
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    "UPDATE orders SET status='UNKNOWN' WHERE client_order_id=$1", cid)
                await con.execute(
                    "UPDATE intents SET status='UNKNOWN' WHERE intent_id=$1", intent_id)
                await con.execute(
                    """INSERT INTO order_events (client_order_id, event_type, payload)
                       VALUES ($1,'TIMEOUT',$2)""",
                    cid, json.dumps({"detail": detail[:500]}))
        log.warning("order.unknown", cid=cid, detail=detail[:200])

    async def _mark_rejected(
        self, cid: str, intent_id: int, code: str, message: str
    ) -> None:
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """UPDATE orders SET status='REJECTED', terminal_at=now()
                       WHERE client_order_id=$1""", cid)
                await con.execute(
                    "UPDATE intents SET status='REJECTED' WHERE intent_id=$1", intent_id)
                await con.execute(
                    """INSERT INTO order_events (client_order_id, event_type, payload)
                       VALUES ($1,'REJECTED',$2)""",
                    cid, json.dumps({"code": code, "message": message[:500]}))
        log.warning("order.rejected", cid=cid, code=code)

    async def _ops(self, severity: str, kind: str, inst_id: str | None,
                   detail: dict) -> None:
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO ops_events (run_id, severity, kind, inst_id, detail)
                   VALUES ($1,$2,$3,$4,$5)""",
                self._run_id, severity, kind, inst_id, json.dumps(detail))


async def open_exposure(con: asyncpg.Connection) -> dict:
    """Current open/pending exposure, for the risk gate and the dashboard."""
    row = await con.fetchrow(
        """SELECT
             (SELECT count(*) FROM positions WHERE status <> 'CLOSED') AS open_positions,
             (SELECT count(*) FROM intents WHERE status NOT IN
                ('FILLED','CANCELLED','REJECTED','EXPIRED','RECONCILED')) AS pending,
             (SELECT coalesce(sum(frozen_risk_amount),0) FROM positions
                WHERE status <> 'CLOSED') AS open_risk"""
    )
    return dict(row)
