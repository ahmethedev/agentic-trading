#!/usr/bin/env python
"""Book an exit that happened at the venue but never reached the ledger.

The worker now ingests venue-side exits on every protection sweep, but that only
helps positions it can still see. A position the sweep already closed as "dust"
-- because the stop had sold the base out from under it -- is CLOSED with a
realised PnL of zero and no sell fill anywhere, and nothing will ever revisit it.

This repairs one such position from the venue's own fill history. It is a
read-only call to the exchange and a write to our ledger: no order is placed,
amended or cancelled.

    python scripts/backfill_exit_fills.py --position 250          # dry run
    python scripts/backfill_exit_fills.py --position 250 --apply
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from agentic_trade.atk.client import AtkClient
from agentic_trade.config import get_settings
from agentic_trade.db import pool
from agentic_trade.execution.position import ingest_exit_fills
from agentic_trade.execution.venue import AtkVenue


async def _position(position_id: int):
    async with pool.ledger().acquire() as con:
        row = await con.fetchrow(
            """SELECT p.*, (SELECT count(*) FROM fills f
                            WHERE f.inst_id = p.inst_id AND f.side='sell'
                              AND f.ts >= p.opened_at) AS sells_known
               FROM positions p WHERE p.position_id=$1""", position_id)
    if row is None:
        raise SystemExit(f"no position {position_id}")
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--position", type=int, required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write to the ledger (default: report only)")
    ap.add_argument("--force", action="store_true",
                    help="proceed even though sells for this position are already "
                         "booked; only for a partial repair")
    args = ap.parse_args()

    s = get_settings()
    await pool.init_pools(s.database_url)
    atk = AtkClient(s.atk_dir, s.atk_env(), timeout_s=s.atk_timeout_s,
                    modules=s.atk_modules())
    await atk.start()
    try:
        p = await _position(args.position)
        print(f"position {p['position_id']}  {p['inst_id']}  {p['status']}")
        print(f"  opened      {p['opened_at']}  closed {p['closed_at']}")
        print(f"  qty         initial {p['initial_qty']}  open {p['qty_open']}")
        print(f"  entry       {p['avg_entry_px']}   entry_fees {p['entry_fees']}")
        print(f"  realised    {p['realized_pnl']}")
        print(f"  sells known to the ledger: {p['sells_known']}")

        if p["sells_known"] and not args.force:
            raise SystemExit("this position already has booked sells; --force to "
                             "repair anyway")

        venue = AtkVenue(atk)
        sells = [f for f in await venue.get_fills(p["inst_id"])
                 if f.side == "sell" and f.ts >= p["opened_at"]]
        if not sells:
            raise SystemExit("the venue reports no sell after this position opened; "
                             "nothing to repair")
        for f in sells:
            print(f"  venue sell  {f.ts}  {f.qty} @ {f.px}  fee {f.fee} {f.fee_ccy}"
                  f"  (ordId {f.exchange_order_id})")

        if not args.apply:
            print("\ndry run: nothing written. Re-run with --apply.")
            return

        # The exit is being booked long after the fact, so the position's own
        # close time is preserved: record_exit_fill stamps closed_at=now(), which
        # would move a September stop-out to whenever this script happened to run.
        closed_at = p["closed_at"]
        out = await ingest_exit_fills(
            venue, run_id=p["run_id"], position_id=p["position_id"],
            intent_id=p["intent_id"], inst_id=p["inst_id"],
            avg_entry_px=Decimal(p["avg_entry_px"]), opened_at=p["opened_at"],
            # The sweep zeroed qty_open when it closed the position as dust. The
            # exit has to be applied against the inventory that was really there.
            qty_open=Decimal(p["initial_qty"]) if p["qty_open"] == 0
                     else Decimal(p["qty_open"]),
        )
        if closed_at is not None:
            async with pool.ledger().acquire() as con:
                await con.execute(
                    "UPDATE positions SET closed_at=$2 WHERE position_id=$1",
                    p["position_id"], closed_at)

        after = await _position(args.position)
        print(f"\nbooked {out.stored} sell fill(s), {out.applied_qty} qty")
        print(f"realised PnL  {p['realized_pnl']}  ->  {after['realized_pnl']}")
        print(f"fees paid     {p['fees_paid']}  ->  {after['fees_paid']}")
    finally:
        await atk.stop()
        await pool.close_pools()


if __name__ == "__main__":
    asyncio.run(main())
