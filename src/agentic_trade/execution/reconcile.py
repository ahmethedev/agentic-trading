"""Startup reconciliation.

AGENT.md §5 rule 7: after a restart, no new entry may be opened until the local
ledger, the venue's open orders, its fill history and the account balance agree.

The hard rule here is that SILENCE IS NOT RESOLUTION. An order we cannot ask
about stays unresolved and keeps the system blocked; it is never assumed dead
because asking failed. The only thing that closes out an intent is the venue
telling us what happened to it.

What this resolves, in order:
  1. Intents reserved but never sent    -> released (no order row exists)
  2. Orders in flight / UNKNOWN         -> queried by client order id
  3. Fills we missed while down         -> ingested idempotently
  4. Entries that filled without a position row -> position rebuilt and protected
  5. Open positions                     -> checked against real base balance
  6. Protection for open positions      -> verified still live at the venue
  7. Inventory we hold but cannot explain -> surfaced, never silently adopted
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from ..db import pool
from .order_manager import OrderManager
from .venue import TERMINAL, OrdStatus, Venue, VenueUnknown

log = structlog.get_logger(__name__)

VENUE = "okx-tr"
# Ledger states that still hold the position slot.
LIVE_INTENT_STATES = ("RESERVED", "SENT", "UNKNOWN", "ACKED", "PARTIAL")


@dataclass
class ReconcileReport:
    released_intents: int = 0
    resolved_orders: int = 0
    adopted_orders: int = 0
    fills_ingested: int = 0
    positions_rebuilt: int = 0
    positions_checked: int = 0
    positions_closed_externally: int = 0
    unprotected_positions: list[int] = field(default_factory=list)
    unexplained_balances: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True only when nothing is left ambiguous.

        Unprotected positions do NOT block: an open position without venue-side
        protection needs attention, but refusing to run would also refuse to
        manage it. Unresolved orders DO block -- their size is unknown.
        """
        return not self.unresolved

    def summary(self) -> dict[str, object]:
        return {
            "released_intents": self.released_intents,
            "resolved_orders": self.resolved_orders,
            "adopted_orders": self.adopted_orders,
            "fills_ingested": self.fills_ingested,
            "positions_rebuilt": self.positions_rebuilt,
            "positions_checked": self.positions_checked,
            "positions_closed_externally": self.positions_closed_externally,
            "unprotected_positions": self.unprotected_positions,
            "unexplained_balances": self.unexplained_balances,
            "unresolved": self.unresolved,
            "clean": self.is_clean,
        }


class Reconciler:
    def __init__(self, venue: Venue, order_manager: OrderManager, run_id: int) -> None:
        self._venue = venue
        self._om = order_manager
        self._run_id = run_id

    async def run(self) -> ReconcileReport:
        report = ReconcileReport()
        await self._release_unsent_intents(report)
        await self._resolve_in_flight_orders(report)
        await self._rebuild_missing_positions(report)
        await self._check_positions(report)
        await self._check_unexplained_inventory(report)

        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO ops_events (run_id, severity, kind, detail)
                   VALUES ($1,$2,'startup_reconcile',$3)""",
                self._run_id,
                "info" if report.is_clean else "error",
                json.dumps(report.summary()),
            )
        log.info("reconcile.done", **report.summary())
        return report

    # ---------------------------------------------------------- step 1 ------
    async def _release_unsent_intents(self, report: ReconcileReport) -> None:
        """An intent with no order row never reached the wire, so it is safe
        to release. The absence of an order row is OUR record, written before
        the send, so this is not an assumption about the venue."""
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT intent_id FROM intents i
                   WHERE i.status = ANY($1::text[])
                     AND NOT EXISTS (
                       SELECT 1 FROM orders o WHERE o.intent_id = i.intent_id)""",
                list(LIVE_INTENT_STATES),
            )
            for r in rows:
                await con.execute(
                    """UPDATE intents SET status='RECONCILED' WHERE intent_id=$1""",
                    r["intent_id"])
        report.released_intents = len(rows)
        if rows:
            log.info("reconcile.released_unsent", count=len(rows))

    # ---------------------------------------------------------- step 2 ------
    async def _resolve_in_flight_orders(self, report: ReconcileReport) -> None:
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT o.client_order_id, o.inst_id, o.intent_id, o.status,
                          o.purpose
                   FROM orders o
                   WHERE o.terminal_at IS NULL
                   ORDER BY o.created_at"""
            )
        for r in rows:
            cid = r["client_order_id"]
            inst = r["inst_id"]
            try:
                state = await self._venue.get_order(inst, cid)
            except VenueUnknown as exc:
                # Could not ask. This stays unresolved and blocks new entries.
                report.unresolved.append(cid)
                log.error("reconcile.unreachable", cid=cid, err=str(exc)[:160])
                await self._ops("error", "reconcile_unreachable", inst,
                                {"client_order_id": cid, "error": str(exc)[:300]})
                continue

            if state.status is OrdStatus.UNKNOWN:
                # The venue has no record. For an ENTRY this means it never
                # landed; for protection it means the algo is gone.
                await self._mark_not_placed(cid, r["intent_id"])
                report.resolved_orders += 1
                continue

            await self._om._record_state(cid, state, event="STARTUP_RECONCILE")
            fee = await self._om._ingest_fills(inst, cid)
            if fee > 0:
                report.fills_ingested += 1
            if state.status in TERMINAL:
                report.resolved_orders += 1
            else:
                # Still working at the venue: adopt it rather than duplicating.
                report.adopted_orders += 1
                log.info("reconcile.adopted", cid=cid, status=str(state.status))
            await self._om._sync_intent(r["intent_id"], state)

    async def _mark_not_placed(self, cid: str, intent_id: int) -> None:
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """UPDATE orders SET status='NOT_PLACED', terminal_at=now(),
                           last_reconciled_at=now()
                       WHERE client_order_id=$1 AND terminal_at IS NULL""", cid)
                await con.execute(
                    """UPDATE intents SET status='RECONCILED'
                       WHERE intent_id=$1 AND status = ANY($2::text[])""",
                    intent_id, list(LIVE_INTENT_STATES))
                await con.execute(
                    """INSERT INTO order_events (client_order_id, event_type, payload)
                       VALUES ($1,'RECONCILE_NOT_FOUND','{}')""", cid)
        log.warning("reconcile.not_found_at_venue", cid=cid)

    # ---------------------------------------------------------- step 4 ------
    async def _rebuild_missing_positions(self, report: ReconcileReport) -> None:
        """Rebuild a position for an entry that filled but was never recorded.

        A crash between the fill and the position insert leaves real inventory
        with no stop and no exit ladder. This is NOT inventing a position: the
        intent row already holds the frozen structural stop and policy version,
        and the quantity and average price come from actual stored fills.
        """
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT i.intent_id, i.inst_id, i.structural_stop,
                          i.est_cost_per_unit, i.policy_version,
                          o.client_order_id
                   FROM intents i
                   JOIN orders o ON o.intent_id = i.intent_id
                                AND o.purpose = 'ENTRY'
                   WHERE o.qty_filled > 0
                     AND NOT EXISTS (SELECT 1 FROM positions p
                                     WHERE p.intent_id = i.intent_id)"""
            )
        if not rows:
            return

        from ..risk.sizing import InstrumentSpec
        from .position import open_position

        for r in rows:
            qty, avg, fees = await self._om.filled_totals(r["client_order_id"])
            if qty <= 0:
                continue
            async with pool.ledger().acquire() as con:
                spec_row = await con.fetchrow(
                    """SELECT lot_sz, min_sz, tick_sz FROM instruments
                       WHERE venue=$1 AND inst_id=$2""", VENUE, r["inst_id"])
            if spec_row is None:
                report.unresolved.append(f"no instrument spec for {r['inst_id']}")
                continue
            spec = InstrumentSpec(
                r["inst_id"], Decimal(spec_row["lot_sz"]),
                Decimal(spec_row["min_sz"]), Decimal(spec_row["tick_sz"]))
            await open_position(
                self._venue, run_id=self._run_id, intent_id=r["intent_id"],
                inst_id=r["inst_id"], filled_qty=qty, avg_entry_px=avg,
                structural_stop=Decimal(r["structural_stop"]), spec=spec,
                est_cost_per_unit=Decimal(r["est_cost_per_unit"]),
                policy_version=r["policy_version"], fees_paid=fees,
            )
            report.positions_rebuilt += 1
            await self._ops("warn", "position_rebuilt", r["inst_id"], {
                "intent_id": r["intent_id"], "qty": str(qty), "avg_px": str(avg),
                "detail": "entry had filled but no position row existed; rebuilt "
                          "from stored fills and the intent's frozen stop",
            })
            log.warning("reconcile.position_rebuilt", intent_id=r["intent_id"],
                        qty=str(qty))

    # ---------------------------------------------------------- step 5 ------
    async def _check_positions(self, report: ReconcileReport) -> None:
        async with pool.ledger().acquire() as con:
            positions = await con.fetch(
                """SELECT position_id, inst_id, qty_open, intent_id
                   FROM positions WHERE status <> 'CLOSED'"""
            )
        if not positions:
            return
        try:
            balances = await self._venue.get_balances()
        except VenueUnknown as exc:
            report.unresolved.append("balances")
            log.error("reconcile.balances_unreachable", err=str(exc)[:160])
            return

        for p in positions:
            report.positions_checked += 1
            base = p["inst_id"].split("-")[0]
            held = balances.get(base, Decimal(0))
            expected = Decimal(p["qty_open"])

            if held <= 0 < expected:
                # We think we hold inventory; the venue says we hold none. The
                # position was closed while we were down (stop or TP filled).
                await self._close_externally(p["position_id"], p["inst_id"])
                report.positions_closed_externally += 1
                continue

            # Protection must still exist, or the position is naked.
            try:
                algos = await self._venue.get_algo_orders(p["inst_id"])
            except VenueUnknown:
                algos = []
            if not any(a.get("state") in ("live", "pause", "effective")
                       for a in algos):
                report.unprotected_positions.append(p["position_id"])
                await self._ops("error", "reconcile_unprotected", p["inst_id"], {
                    "position_id": p["position_id"],
                    "qty_open": str(expected),
                    "impact": "open position has no live venue-side protection",
                })
                log.error("reconcile.unprotected", position_id=p["position_id"])

    async def _close_externally(self, position_id: int, inst_id: str) -> None:
        async with pool.ledger().acquire() as con:
            await con.execute(
                """UPDATE positions SET status='CLOSED', closed_at=now(),
                       qty_open=0
                   WHERE position_id=$1""", position_id)
        await self._ops("warn", "position_closed_externally", inst_id, {
            "position_id": position_id,
            "detail": "venue reports no base balance; position closed while down. "
                      "Realised PnL is reconstructed from ingested fills.",
        })
        log.warning("reconcile.closed_externally", position_id=position_id)

    # ---------------------------------------------------------- step 7 ------
    async def _check_unexplained_inventory(self, report: ReconcileReport) -> None:
        """Base currency we hold that no open position accounts for.

        Reported, never adopted: silently treating stray inventory as a position
        would invent an entry price and an R basis that never existed.
        """
        try:
            balances = await self._venue.get_balances()
        except VenueUnknown:
            return
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT split_part(inst_id,'-',1) AS base,
                          coalesce(sum(qty_open),0) AS qty
                   FROM positions WHERE status <> 'CLOSED' GROUP BY 1"""
            )
            known_quotes = await con.fetchval(
                "SELECT array_agg(DISTINCT split_part(inst_id,'-',2)) FROM instruments"
            )
        accounted = {r["base"]: Decimal(r["qty"]) for r in rows}
        quotes = set(known_quotes or ["USDT"])
        for ccy, amount in balances.items():
            if ccy in quotes or amount <= 0:
                continue
            diff = amount - accounted.get(ccy, Decimal(0))
            # Ignore dust below any plausible minimum order size.
            if diff > Decimal("0.00000001"):
                report.unexplained_balances[ccy] = str(diff)
        if report.unexplained_balances:
            await self._ops("warn", "reconcile_unexplained_inventory", None,
                            {"balances": report.unexplained_balances,
                             "detail": "held base currency not covered by an open "
                                       "position; not adopted automatically"})
            log.warning("reconcile.unexplained_inventory",
                        balances=report.unexplained_balances)

    async def _ops(self, severity: str, kind: str, inst_id: str | None,
                   detail: dict) -> None:
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO ops_events (run_id, severity, kind, inst_id, detail)
                   VALUES ($1,$2,$3,$4,$5)""",
                self._run_id, severity, kind, inst_id, json.dumps(detail))
