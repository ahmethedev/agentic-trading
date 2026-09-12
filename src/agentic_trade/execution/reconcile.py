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
  5. Exits that filled while we were down -> ingested and booked against the position
  6. Open positions                     -> checked against real base balance
  7. Protection for open positions      -> verified AND re-placed if missing
  8. Inventory we hold but cannot explain -> surfaced, never silently adopted
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from ..db import pool
from ..risk.sizing import InstrumentSpec
from .order_manager import OrderManager
from .position import (
    LIVE_ALGO_STATES,
    ingest_exit_fills,
    open_position,
    sweep_protection,
)
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
    exit_fills_ingested: int = 0
    positions_closed_by_exit: int = 0
    positions_rebuilt: int = 0
    positions_checked: int = 0
    positions_closed_externally: int = 0
    protection_repaired: list[int] = field(default_factory=list)
    positions_closed_as_dust: list[int] = field(default_factory=list)
    unprotected_positions: list[int] = field(default_factory=list)
    unexplained_balances: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True only when nothing is left ambiguous.

        Unprotected positions do NOT block: an open position without venue-side
        protection needs attention, but refusing to run would also refuse to
        manage it -- and step 7 has already tried to re-arm it. Unresolved orders
        DO block -- their size is unknown.
        """
        return not self.unresolved

    def summary(self) -> dict[str, object]:
        return {
            "released_intents": self.released_intents,
            "resolved_orders": self.resolved_orders,
            "adopted_orders": self.adopted_orders,
            "fills_ingested": self.fills_ingested,
            "exit_fills_ingested": self.exit_fills_ingested,
            "positions_closed_by_exit": self.positions_closed_by_exit,
            "positions_rebuilt": self.positions_rebuilt,
            "positions_checked": self.positions_checked,
            "positions_closed_externally": self.positions_closed_externally,
            "protection_repaired": self.protection_repaired,
            "positions_closed_as_dust": self.positions_closed_as_dust,
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
        await self._recover_terminal_entry_fills(report)
        await self._rebuild_missing_positions(report)
        await self._ingest_exits(report)
        await self._check_positions(report)
        await self._repair_protection(report)
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
                          o.purpose, o.ord_type, o.algo_id
                   FROM orders o
                   WHERE o.terminal_at IS NULL
                   ORDER BY o.created_at"""
            )
        for r in rows:
            cid = r["client_order_id"]
            inst = r["inst_id"]
            # An algo order is invisible to the regular order endpoint. Asking
            # about it there returns "no such order", which previously marked a
            # perfectly live OCO as NOT_PLACED -- the ledger then believed the
            # position had no protection while the venue was still holding one.
            if r["ord_type"] == "oco":
                await self._resolve_algo_order(r, report)
                continue
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
            report.fills_ingested += await self._om._ingest_fills(
                inst, cid, state.exchange_order_id
            )
            totals = await self._om.filled_totals(cid)
            if state.qty_filled > totals.qty:
                if cid not in report.unresolved:
                    report.unresolved.append(cid)
                await self._om._mark_fill_pending(cid, r["intent_id"], state, totals.qty)
                continue
            if state.status in TERMINAL:
                report.resolved_orders += 1
            else:
                # Still working at the venue: adopt it rather than duplicating.
                report.adopted_orders += 1
                log.info("reconcile.adopted", cid=cid, status=str(state.status))
            await self._om._sync_intent(r["intent_id"], state)

    async def _recover_terminal_entry_fills(self, report: ReconcileReport) -> None:
        """Repair fills missed after an order was already marked terminal.

        Terminal orders used to be skipped entirely at startup.  That made a
        short propagation delay permanent: the exchange said FILLED, while the
        ledger, chart and position table stayed empty forever.
        """
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT o.client_order_id, o.inst_id, o.intent_id,
                          o.qty_filled, o.exchange_order_id
                   FROM orders o
                   WHERE o.purpose='ENTRY' AND o.qty_filled > 0
                     AND o.qty_filled > coalesce(
                         (SELECT sum(f.qty) FROM fills f
                          WHERE f.client_order_id=o.client_order_id), 0)
                   ORDER BY o.created_at"""
            )
        for r in rows:
            cid, inst = r["client_order_id"], r["inst_id"]
            try:
                state = await self._venue.get_order(inst, cid)
            except VenueUnknown as exc:
                report.unresolved.append(cid)
                await self._ops(
                    "error",
                    "reconcile_terminal_fill_unreachable",
                    inst,
                    {"client_order_id": cid, "error": str(exc)[:300]},
                )
                continue
            if state.status is OrdStatus.UNKNOWN or state.qty_filled <= 0:
                report.unresolved.append(cid)
                await self._ops(
                    "error",
                    "reconcile_terminal_fill_unknown",
                    inst,
                    {"client_order_id": cid},
                )
                continue

            report.fills_ingested += await self._om._ingest_fills(
                inst, cid, state.exchange_order_id
            )
            totals = await self._om.filled_totals(cid)
            if state.qty_filled > totals.qty:
                if cid not in report.unresolved:
                    report.unresolved.append(cid)
                await self._om._mark_fill_pending(cid, r["intent_id"], state, totals.qty)
                continue
            report.unresolved = [item for item in report.unresolved if item != cid]
            await self._om._sync_intent(r["intent_id"], state)
            log.warning(
                "reconcile.terminal_fill_recovered",
                cid=cid,
                qty=str(totals.qty),
            )

    async def _resolve_algo_order(self, r, report: ReconcileReport) -> None:
        """Ask the ALGO endpoint about a protective order, by its client id."""
        cid, inst = r["client_order_id"], r["inst_id"]
        try:
            algos = await self._venue.get_algo_orders(inst)
        except VenueUnknown as exc:
            report.unresolved.append(cid)
            log.error("reconcile.unreachable", cid=cid, err=str(exc)[:160])
            await self._ops("error", "reconcile_unreachable", inst,
                            {"client_order_id": cid, "error": str(exc)[:300]})
            return

        mine = next(
            (a for a in algos
             if a.get("algoClOrdId") == cid
             or (r["algo_id"] and a.get("algoId") == r["algo_id"])),
            None,
        )
        if mine is None:
            # Gone from the venue: triggered, cancelled, or never accepted. The
            # protection sweep decides whether the position needs a new one.
            await self._mark_not_placed(cid, r["intent_id"])
            report.resolved_orders += 1
            return

        state = mine.get("state", "")
        if state in LIVE_ALGO_STATES:
            report.adopted_orders += 1
            async with pool.ledger().acquire() as con:
                await con.execute(
                    """UPDATE orders SET status=$2, last_reconciled_at=now()
                       WHERE client_order_id=$1""", cid, state)
            log.info("reconcile.adopted_algo", cid=cid, state=state)
            return

        async with pool.ledger().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """UPDATE orders SET status=$2, terminal_at=now(),
                           last_reconciled_at=now()
                       WHERE client_order_id=$1 AND terminal_at IS NULL""",
                    cid, state)
                await con.execute(
                    """INSERT INTO order_events (client_order_id, event_type, payload)
                       VALUES ($1,'RECONCILE_ALGO',$2)""",
                    cid, json.dumps({"state": state, "algo_id": mine.get("algoId")}))
        report.resolved_orders += 1
        log.info("reconcile.algo_terminal", cid=cid, state=state)

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
                """SELECT i.intent_id, i.run_id, i.inst_id, i.structural_stop,
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

        for r in rows:
            totals = await self._om.filled_totals(r["client_order_id"])
            if totals.qty <= 0:
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
                self._venue, run_id=r["run_id"], intent_id=r["intent_id"],
                inst_id=r["inst_id"], filled_qty=totals.qty,
                avg_entry_px=totals.avg_px,
                structural_stop=Decimal(r["structural_stop"]), spec=spec,
                est_cost_per_unit=Decimal(r["est_cost_per_unit"]),
                policy_version=r["policy_version"], fees=totals.fees,
            )
            report.positions_rebuilt += 1
            await self._ops("warn", "position_rebuilt", r["inst_id"], {
                "intent_id": r["intent_id"], "qty": str(totals.qty),
                "avg_px": str(totals.avg_px),
                "detail": "entry had filled but no position row existed; rebuilt "
                          "from stored fills and the intent's frozen stop",
            })
            log.warning("reconcile.position_rebuilt", intent_id=r["intent_id"],
                        qty=str(totals.qty))

    # ---------------------------------------------------------- step 5 ------
    async def _ingest_exits(self, report: ReconcileReport) -> None:
        """Book exits that filled at the venue while we were down.

        This runs BEFORE the balance check on purpose. A stop that triggered
        overnight leaves a position whose base balance is zero, and the balance
        check alone can only say "it is gone" -- it closes the position with no
        price, no fee and no realised PnL. The sale itself is sitting in the
        venue's fill history the whole time; it just never had a path into the
        ledger, because the triggered algo leg carries an order id we did not
        issue.
        """
        async with pool.ledger().acquire() as con:
            rows = await con.fetch(
                """SELECT position_id, intent_id, inst_id, qty_open,
                          avg_entry_px, opened_at
                   FROM positions WHERE status <> 'CLOSED' AND qty_open > 0"""
            )
        for p in rows:
            out = await ingest_exit_fills(
                self._venue, run_id=self._run_id, position_id=p["position_id"],
                intent_id=p["intent_id"], inst_id=p["inst_id"],
                avg_entry_px=Decimal(p["avg_entry_px"]),
                opened_at=p["opened_at"], qty_open=Decimal(p["qty_open"]))
            report.exit_fills_ingested += out.stored
            if out.closed:
                report.positions_closed_by_exit += 1
                log.warning("reconcile.closed_by_exit",
                            position_id=p["position_id"], qty=str(out.applied_qty))

    # ---------------------------------------------------------- step 6 ------
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
                # We think we hold inventory, the venue says we hold none, and
                # step 5 found no fill that explains where it went. Something
                # sold this base outside the system -- by hand, or before the
                # venue's fill history window. Close it, but say plainly that
                # the realised PnL is missing a leg.
                await self._close_externally(p["position_id"], p["inst_id"])
                report.positions_closed_externally += 1

    # ---------------------------------------------------------- step 7 ------
    async def _repair_protection(self, report: ReconcileReport) -> None:
        """Re-arm any open position that has no live stop at the venue.

        Reporting alone was not enough: run 587 and run 588 both recorded
        `reconcile_unprotected` for the same live position and then carried on
        trading around it. Finding a naked position and leaving it naked is not
        reconciliation.
        """
        sweep = await sweep_protection(self._venue, self._run_id)
        report.protection_repaired = sweep.repaired
        report.positions_closed_as_dust = sweep.dust_closed
        report.unprotected_positions = sweep.unprotected
        if sweep.repaired:
            await self._ops("warn", "reconcile_protection_repaired", None, {
                "positions": sweep.repaired,
                "detail": "open positions were found without venue-side "
                          "protection and re-armed from their stored ladder",
            })
        for pid in sweep.unprotected:
            await self._ops("error", "reconcile_unprotected", None, {
                "position_id": pid,
                "impact": "open position has no live venue-side protection and "
                          "re-arming it failed",
            })
            log.error("reconcile.unprotected", position_id=pid)

    async def _close_externally(self, position_id: int, inst_id: str) -> None:
        async with pool.ledger().acquire() as con:
            await con.execute(
                """UPDATE positions SET status='CLOSED', closed_at=now(),
                       qty_open=0
                   WHERE position_id=$1""", position_id)
        await self._ops("error", "position_closed_externally", inst_id, {
            "position_id": position_id,
            "detail": "venue reports no base balance and no sell fill explains it; "
                      "the position is closed to free the slot.",
            "impact": "realised PnL for this position has no exit leg and is "
                      "understated; the sale happened outside this system",
        })
        log.warning("reconcile.closed_externally", position_id=position_id)

    # ---------------------------------------------------------- step 8 ------
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
