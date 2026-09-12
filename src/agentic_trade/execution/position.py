"""Position opening and exit-ladder management.

The R basis is frozen when the entry resolves and never recomputed: moving the
stop to breakeven or banking a partial does NOT shrink the denominator used for
reporting (AGENT.md §5).

Protection is sized to the quantity we ACTUALLY own, not the quantity we asked
for, and every exit leg is bounded by remaining inventory so competing exits can
never sell the same base twice.

"Actually own" is stricter than "filled". OKX charges the spot fee in the
currency you receive, so a buy pays it in BASE: a 0.293818 SOL fill leaves
0.293524 SOL in the account. Sizing protection to the filled quantity asks the
venue to sell base that was never credited, and the OCO is rejected -- which is
how a live position spent hours with no stop on 12 Sep 2026.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from ..db import pool
from ..risk.sizing import (
    TP2_R,
    ExitPlan,
    InstrumentSpec,
    _floor_to_step,
    build_exit_plan,
)
from .ids import new_client_order_id
from .venue import Venue, VenueRejected, VenueUnknown

log = structlog.get_logger(__name__)

VENUE = "okx-tr"


@dataclass
class OpenedPosition:
    position_id: int
    plan: ExitPlan
    algo_id: str | None
    protection_error: str | None = None


@dataclass
class ProtectionOutcome:
    """Result of one attempt to put a stop behind a position.

    `dust` separates the two reasons a position can end up unprotected: the
    venue refused (retry later, it may work), or there is less base left than
    the minimum order size, in which case no order can ever be placed and the
    remainder is not a position at all.
    """

    algo_id: str | None
    error: str | None = None
    dust: bool = False

    @property
    def ok(self) -> bool:
        return self.algo_id is not None


def owned_qty(
    filled_qty: Decimal, base_fee: Decimal, spec: InstrumentSpec
) -> Decimal:
    """Base we can actually sell: what filled, less the fee taken out of it.

    Floored to the lot step, because a quantity the venue cannot express is a
    quantity it will reject.
    """
    return _floor_to_step(max(filled_qty - base_fee, Decimal(0)), spec.lot_sz)


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
    fees: dict[str, Decimal] | None = None,
) -> OpenedPosition:
    """Record the position from real fills, then attach venue-side protection.

    `fees` is the per-currency fee map for the entry. The base-denominated part
    is subtracted from the filled quantity, because it is base the account never
    received: every later sell -- the protective OCO included -- is bounded by
    what the venue actually credited.
    """
    if filled_qty <= 0:
        raise ValueError("cannot open a position with zero filled quantity")

    fees = fees or {}
    base_ccy, quote_ccy = inst_id.split("-", 1)
    base_fee = fees.get(base_ccy, Decimal(0))
    qty = owned_qty(filled_qty, base_fee, spec)
    if qty <= 0:
        raise ValueError(
            f"entry fee consumed the whole fill: {filled_qty} - {base_fee}")
    # Entry cost in ONE currency, so realised PnL can amortise it pro-rata.
    entry_fees_quote = fees.get(quote_ccy, Decimal(0)) + base_fee * avg_entry_px

    plan = build_exit_plan(
        initial_qty=qty,
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
            run_id, intent_id, inst_id, qty, avg_entry_px,
            plan.initial_stop_px, plan.frozen_risk_amount, plan.price_r_distance,
            entry_fees_quote, policy_version,
        )
    if base_fee > 0:
        log.info("position.fee_netted", position_id=position_id,
                 filled=str(filled_qty), fee_ccy=base_ccy, fee=str(base_fee),
                 owned=str(qty))

    # Protection goes on immediately, sized to actual inventory. A failure here
    # is loud: an unprotected position is an incident, not a detail.
    protection = await ensure_protection(
        venue, run_id=run_id, position_id=position_id, intent_id=intent_id,
        inst_id=inst_id, qty=qty, tp_trigger=plan.tp2_trigger_px,
        sl_trigger=plan.initial_stop_px, spec=spec)

    log.info("position.opened", position_id=position_id, inst=inst_id,
             qty=str(qty), entry=str(avg_entry_px),
             stop=str(plan.initial_stop_px), protected=protection.ok)
    return OpenedPosition(position_id, plan, protection.algo_id, protection.error)


async def ensure_protection(
    venue: Venue,
    *,
    run_id: int,
    position_id: int,
    intent_id: int,
    inst_id: str,
    qty: Decimal,
    tp_trigger: Decimal,
    sl_trigger: Decimal,
    spec: InstrumentSpec,
) -> ProtectionOutcome:
    """Put a live OCO behind `qty`.

    Two things make this safe to call repeatedly, which is what lets it double as
    the repair path:

      * the size is clamped to the base the VENUE says is available, so a ledger
        quantity that drifted above reality (an un-netted fee, dust left by a
        partial exit) still produces a placeable order rather than a rejection;
      * every attempt is recorded, so a failure is an incident with a cause in
        the ledger rather than a log line that scrolls away.
    """
    placeable, clamp_note, dust = await _placeable_qty(venue, inst_id, qty, spec)
    if placeable <= 0:
        await _ops(run_id, "error" if not dust else "warn", "protection_failed",
                   inst_id, {
                       "position_id": position_id, "ledger_qty": str(qty),
                       "error": clamp_note, "dust": dust,
                       "impact": "no venue-side protection could be sized "
                                 "for this position",
                   })
        log.error("position.unprotected", position_id=position_id, err=clamp_note)
        return ProtectionOutcome(None, clamp_note, dust=dust)

    cid = new_client_order_id(intent_id, "STOP")
    try:
        algo_id = await venue.place_oco(
            inst_id, placeable, tp_trigger, sl_trigger, cid)
    except (VenueUnknown, VenueRejected) as exc:
        error = str(exc)[:300]
        await _ops(run_id, "error", "protection_failed", inst_id, {
            "position_id": position_id,
            "client_order_id": cid,
            "qty": str(placeable),
            "error": error,
            "impact": "position is OPEN without venue-side protection",
        })
        log.error("position.unprotected", position_id=position_id, err=error)
        return ProtectionOutcome(None, error)

    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO orders (client_order_id, intent_id, run_id, venue,
                   inst_id, algo_id, purpose, side, ord_type, qty_requested,
                   status, sent_at, acked_at)
               VALUES ($1,$2,$3,'okx-tr',$4,$5,'STOP','sell','oco',$6,'live',
                       now(),now())""",
            cid, intent_id, run_id, inst_id, algo_id, placeable,
        )
    if clamp_note:
        await _ops(run_id, "warn", "protection_clamped", inst_id, {
            "position_id": position_id, "ledger_qty": str(qty),
            "placed_qty": str(placeable), "detail": clamp_note,
        })
        log.warning("position.protection_clamped", position_id=position_id,
                    ledger=str(qty), placed=str(placeable))
    log.info("position.protected", position_id=position_id, algo_id=algo_id,
             qty=str(placeable), stop=str(sl_trigger))
    return ProtectionOutcome(algo_id)


async def _placeable_qty(
    venue: Venue, inst_id: str, qty: Decimal, spec: InstrumentSpec
) -> tuple[Decimal, str | None, bool]:
    """The largest protectable size, given what the venue says we hold.

    A balance read that fails is not treated as zero: we go ahead with the ledger
    quantity, because refusing to try would guarantee an unprotected position
    where trying might still succeed.
    """
    try:
        balances = await venue.get_balances()
    except VenueUnknown as exc:
        log.warning("position.balance_unavailable", inst=inst_id,
                    err=str(exc)[:150])
        return qty, None, False

    base = inst_id.split("-", 1)[0]
    held = _floor_to_step(balances.get(base, Decimal(0)), spec.lot_sz)
    if held >= qty:
        return qty, None, False
    if held < spec.min_sz:
        return Decimal(0), (
            f"venue holds {held} {base}, below the {spec.min_sz} minimum order "
            f"size; the remainder is dust and cannot be protected"), True
    return held, (
        f"ledger says {qty} {base}, venue holds {held}; protected the smaller"), False


async def _ops(run_id: int, severity: str, kind: str, inst_id: str | None,
               detail: dict) -> None:
    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO ops_events (run_id, severity, kind, inst_id, detail)
               VALUES ($1,$2,$3,$4,$5)""",
            run_id, severity, kind, inst_id, json.dumps(detail))


# ------------------------------------------------------------------ exits ----
@dataclass
class ExitIngest:
    """What one exit-fill sweep found for a single position."""

    stored: int = 0                      # sells that were new to the ledger
    applied_qty: Decimal = Decimal(0)    # inventory those sells retired
    closed: bool = False
    error: str | None = None


async def ingest_exit_fills(
    venue: Venue,
    *,
    run_id: int,
    position_id: int,
    intent_id: int | None,
    inst_id: str,
    avg_entry_px: Decimal,
    opened_at,
    qty_open: Decimal,
) -> ExitIngest:
    """Book the sells that happened at the VENUE but never reached the ledger.

    A protective OCO fills under an order id the venue generates when the algo
    triggers -- OKX reports the fill with `clOrdId` "O3916423678690419712" and no
    `algoClOrdId` at all -- so nothing that polls OUR client order ids can ever
    see it. Entry fills are ingested because we know their id; exits had no path
    in at all, and the sale was invisible three times over: no marker on the
    chart, no row in the trade list, and realised PnL frozen at zero while the
    protection sweep closed the position as "dust" because the base was gone
    (position 250, SOL-USDT, 12 Sep 2026: a real -0.11 USDT stop-out reported as
    a flat close).

    Attribution is by instrument and time rather than by order id, because the
    order id is not ours: a sell on this instrument after the position opened is
    this position's exit. That holds while only one position per instrument is
    open at a time, which is what the reservation lock already enforces.
    """
    try:
        fills = await venue.get_fills(inst_id)
    except VenueUnknown as exc:
        # Could not ask. Say nothing rather than conclude anything: the caller
        # must not read "no exit found" out of "the venue did not answer".
        log.warning("position.exit_fills_unavailable", position_id=position_id,
                    err=str(exc)[:150])
        return ExitIngest(error=str(exc)[:300])

    quote_ccy = inst_id.split("-", 1)[1]
    out = ExitIngest()
    remaining = qty_open
    sells = sorted(
        (f for f in fills if f.side == "sell" and f.ts >= opened_at),
        key=lambda f: f.ts,
    )
    for f in sells:
        async with pool.ledger().acquire() as con:
            # The venue's clOrdId for a triggered algo leg is not one of ours,
            # and fills.client_order_id is a foreign key: store the link only
            # when it resolves, never a fabricated one.
            known_cid = await con.fetchval(
                "SELECT client_order_id FROM orders WHERE client_order_id=$1",
                f.client_order_id)
            # The (venue, fill_id) primary key is the idempotency boundary for
            # the whole operation: a fill already stored was already applied to
            # the position, so a repeated sweep cannot double-count a sale.
            stored = await con.fetchval(
                """INSERT INTO fills (venue, fill_id, client_order_id,
                       exchange_order_id, inst_id, side, px, qty, fee, fee_ccy,
                       liquidity, ts, run_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                   ON CONFLICT (venue, fill_id) DO NOTHING
                   RETURNING fill_id""",
                VENUE, f.fill_id, known_cid, f.exchange_order_id, f.inst_id,
                f.side, f.px, f.qty, f.fee, f.fee_ccy, f.liquidity, f.ts, run_id,
            )
        if stored is None:
            continue
        out.stored += 1

        apply_qty = min(f.qty, remaining)
        if apply_qty <= 0:
            # Kept for the record -- it is a real trade and belongs on the chart
            # -- but there is no open inventory left for it to retire, and
            # applying it would invent realised PnL out of someone else's sale.
            await _ops(run_id, "warn", "exit_fill_unattributed", inst_id, {
                "position_id": position_id, "fill_id": f.fill_id,
                "qty": str(f.qty), "px": str(f.px),
                "detail": "sell fill stored but not applied: the position had no "
                          "open quantity left to retire",
            })
            continue

        fee = f.fee if f.fee_ccy == quote_ccy else Decimal(0)
        if f.fee_ccy != quote_ccy and f.fee > 0:
            await _ops(run_id, "warn", "fee_currency_unpriced", inst_id, {
                "position_id": position_id, "fill_id": f.fill_id,
                "fee": str(f.fee), "fee_ccy": f.fee_ccy,
                "detail": "exit fee is not quote-denominated and cannot be "
                          "valued without a rate; realised PnL excludes it",
            })
        if apply_qty < f.qty and f.qty > 0:
            fee = fee * apply_qty / f.qty

        await record_exit_fill(position_id, apply_qty, f.px, fee, avg_entry_px)
        remaining -= apply_qty
        out.applied_qty += apply_qty
        log.info("position.exit_recorded", position_id=position_id,
                 fill_id=f.fill_id, qty=str(apply_qty), px=str(f.px))

    if out.applied_qty <= 0:
        return out

    async with pool.ledger().acquire() as con:
        status = await con.fetchval(
            "SELECT status FROM positions WHERE position_id=$1", position_id)
    out.closed = status == "CLOSED"

    if out.closed and intent_id is not None:
        # The OCO that sold this is gone from the venue. Leaving its order row
        # "live" would have the next reconciliation call a triggered stop
        # NOT_PLACED -- the one status it certainly was not.
        async with pool.ledger().acquire() as con:
            async with con.transaction():
                cids = await con.fetch(
                    """UPDATE orders SET status='triggered', terminal_at=now(),
                           last_reconciled_at=now()
                       WHERE intent_id=$1 AND purpose='STOP' AND qty_filled=0
                         AND (terminal_at IS NULL OR status='NOT_PLACED')
                       RETURNING client_order_id""", intent_id)
                for row in cids:
                    await con.execute(
                        """INSERT INTO order_events (client_order_id, event_type,
                               payload) VALUES ($1,'EXIT_INGESTED',$2)""",
                        row["client_order_id"],
                        json.dumps({"position_id": position_id,
                                    "qty": str(out.applied_qty)}))

    await _ops(run_id, "warn", "position_exit_ingested", inst_id, {
        "position_id": position_id, "fills": out.stored,
        "qty": str(out.applied_qty), "closed": out.closed,
        "detail": "sells that filled at the venue under an id we did not issue "
                  "were booked against the position",
    })
    return out


# --------------------------------------------------------------- watchdog ----
LIVE_ALGO_STATES = ("live", "pause", "effective")


@dataclass
class ProtectionSweep:
    """What one pass of the watchdog found and did."""

    checked: int = 0
    already_protected: list[int] = field(default_factory=list)
    repaired: list[int] = field(default_factory=list)
    unprotected: list[int] = field(default_factory=list)
    dust_closed: list[int] = field(default_factory=list)
    exited: list[int] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "already_protected": self.already_protected,
            "repaired": self.repaired,
            "unprotected": self.unprotected,
            "dust_closed": self.dust_closed,
            "exited": self.exited,
        }


async def sweep_protection(venue: Venue, run_id: int) -> ProtectionSweep:
    """Verify every open position still has a live stop -- and re-place it if not.

    Detecting an unprotected position and only writing an ops event leaves the
    money exposed for as long as nobody reads the event. On 12 Sep 2026 that was
    two and a half hours across two restarts. So this REPAIRS: the same code path
    that arms protection at entry is re-run against the position's stored ladder.

    The stop used is `current_stop_px`, not the initial one, so a position that
    has already moved to breakeven is re-protected where it stands now.
    """
    sweep = ProtectionSweep()
    async with pool.ledger().acquire() as con:
        rows = await con.fetch(
            """SELECT p.position_id, p.intent_id, p.inst_id, p.qty_open,
                      p.avg_entry_px, p.price_r_distance, p.opened_at,
                      coalesce(p.current_stop_px, p.initial_stop_px) AS stop_px,
                      i.lot_sz, i.min_sz, i.tick_sz,
                      (SELECT o.algo_id FROM orders o
                       WHERE o.intent_id=p.intent_id AND o.purpose='STOP'
                       ORDER BY o.created_at DESC LIMIT 1) AS protection_algo_id,
                      (SELECT o.client_order_id FROM orders o
                       WHERE o.intent_id=p.intent_id AND o.purpose='STOP'
                       ORDER BY o.created_at DESC LIMIT 1) AS protection_cid
               FROM positions p
               LEFT JOIN instruments i
                      ON i.venue = 'okx-tr' AND i.inst_id = p.inst_id
               WHERE p.status <> 'CLOSED' AND p.qty_open > 0"""
        )

    for r in rows:
        sweep.checked += 1
        pid, inst = r["position_id"], r["inst_id"]

        # Book any venue-side exit BEFORE judging the position. A stop that has
        # already filled leaves zero base behind, which looks exactly like dust
        # -- and closing it as dust buries a real sale under a realised PnL of
        # zero. This is the difference between "we sold" and "we cannot sell".
        exited = await ingest_exit_fills(
            venue, run_id=run_id, position_id=pid, intent_id=r["intent_id"],
            inst_id=inst, avg_entry_px=Decimal(r["avg_entry_px"]),
            opened_at=r["opened_at"], qty_open=Decimal(r["qty_open"]))
        if exited.closed:
            sweep.exited.append(pid)
            continue
        qty_open = Decimal(r["qty_open"]) - exited.applied_qty

        if r["lot_sz"] is None:
            sweep.unprotected.append(pid)
            await _ops(run_id, "error", "protection_failed", inst, {
                "position_id": pid,
                "error": "no instrument spec; cannot size a protective order",
            })
            continue

        try:
            algos = await venue.get_algo_orders(inst)
        except VenueUnknown as exc:
            # We could not ask. Do NOT place a second stop on a guess: that risks
            # two live OCOs racing to sell the same base.
            log.warning("protection.check_unavailable", position_id=pid,
                        err=str(exc)[:150])
            sweep.unprotected.append(pid)
            continue
        # Protection belongs to a position, not merely to an instrument. Two
        # BTC positions can coexist; one live BTC OCO covers only its own size
        # and must not make every other BTC position look protected.
        mine = next(
            (
                a
                for a in algos
                if a.get("state") in LIVE_ALGO_STATES
                and (
                    (
                        r["protection_algo_id"]
                        and a.get("algoId") == r["protection_algo_id"]
                    )
                    or (
                        r["protection_cid"]
                        and a.get("algoClOrdId") == r["protection_cid"]
                    )
                )
            ),
            None,
        )
        if mine is not None:
            sweep.already_protected.append(pid)
            continue

        spec = InstrumentSpec(inst, Decimal(r["lot_sz"]), Decimal(r["min_sz"]),
                              Decimal(r["tick_sz"]))
        stop_px = Decimal(r["stop_px"])
        # Rebuild the take-profit leg from the frozen R distance rather than
        # re-deriving it from the current price: the ladder is part of the plan
        # the position was opened under and must not drift on a restart.
        tp_px = Decimal(r["avg_entry_px"]) + Decimal(r["price_r_distance"]) * TP2_R
        outcome = await ensure_protection(
            venue, run_id=run_id, position_id=pid, intent_id=r["intent_id"],
            inst_id=inst, qty=qty_open, tp_trigger=tp_px,
            sl_trigger=stop_px, spec=spec)

        if outcome.ok:
            sweep.repaired.append(pid)
            await _ops(run_id, "warn", "protection_repaired", inst, {
                "position_id": pid, "algo_id": outcome.algo_id,
                "stop_px": str(stop_px),
                "detail": "open position had no live venue-side protection; "
                          "a replacement OCO was placed from the stored ladder",
            })
        elif outcome.dust:
            # Less base left than the venue will trade. It cannot be protected,
            # cannot be sold, and must not keep holding the position slot.
            await _close_as_dust(pid, inst, run_id, outcome.error or "")
            sweep.dust_closed.append(pid)
        else:
            sweep.unprotected.append(pid)

    if sweep.repaired or sweep.unprotected or sweep.dust_closed or sweep.exited:
        log.warning("protection.sweep", **sweep.summary())
    return sweep


async def _close_as_dust(position_id: int, inst_id: str, run_id: int,
                         detail: str) -> None:
    async with pool.ledger().acquire() as con:
        await con.execute(
            """UPDATE positions SET status='CLOSED', closed_at=now(), qty_open=0
               WHERE position_id=$1 AND status <> 'CLOSED'""", position_id)
    await _ops(run_id, "warn", "position_closed_as_dust", inst_id, {
        "position_id": position_id, "detail": detail,
        "impact": "remaining base is below the venue minimum, so it can never be "
                  "sold; the position is closed to release the slot. Realised "
                  "PnL already reflects every fill that happened.",
    })
    log.warning("position.closed_as_dust", position_id=position_id)


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
