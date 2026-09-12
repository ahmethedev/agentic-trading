"""Run the full order chain once in PAPER mode, against real market prices.

Creates a clearly-labelled paper run so the dashboard shows a complete
decision -> intent -> order -> fill -> position -> protection chain even when the
live regime is producing no candidates.

Paper results are never live results: the run row records mode='paper', and the
dashboard shows that label. Nothing here touches the exchange's order path.
"""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_trade.atk.client import AtkClient  # noqa: E402
from agentic_trade.config import get_settings  # noqa: E402
from agentic_trade.db import pool  # noqa: E402
from agentic_trade.execution.order_manager import OrderManager  # noqa: E402
from agentic_trade.execution.position import (  # noqa: E402
    apply_breakeven,
    claim_tp_stage,
    open_position,
    record_exit_fill,
)
from agentic_trade.execution.venue import PaperVenue  # noqa: E402
from agentic_trade.risk.sizing import InstrumentSpec, SizingInput, compute_size  # noqa: E402

INST = "BTC-USDT"
POLICY = "retail_baseline_v1"


async def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
    s = get_settings()
    await pool.init_pools(s.database_url)

    atk = AtkClient(s.atk_dir, s.atk_env(), timeout_s=s.atk_timeout_s,
                    modules=s.atk_modules())
    await atk.start()

    # Real price and real instrument spec -- only the venue fills are simulated.
    tick = await atk.call("market_get_ticker", {"instId": INST})
    last = Decimal(tick["data"]["data"][0]["last"])
    insts = await atk.call("market_get_instruments", {"instType": "SPOT"})
    row = next(r for r in insts["data"]["data"] if r["instId"] == INST)
    spec = InstrumentSpec(INST, Decimal(row["lotSz"]), Decimal(row["minSz"]),
                          Decimal(row["tickSz"]))
    print(f"live {INST} = {last}   lot={spec.lot_sz} min={spec.min_sz}")

    equity = Decimal("1000")
    entry = last
    stop = (last * Decimal("0.99")).quantize(spec.tick_sz)   # 1% structural stop
    # Size against the worst price we will pay, not the expected one.
    px_limit = (entry * Decimal("1.001")).quantize(spec.tick_sz)

    sized = compute_size(SizingInput(
        equity_quote=equity, available_quote=equity, entry_reference=px_limit,
        structural_stop=stop, risk_fraction=s.risk_fraction,
        risk_fraction_max=s.risk_fraction_max, taker_fee_rate=Decimal("0.001"),
        spec=spec,
    ))
    print(f"sized qty={sized.quantity} notional={sized.notional:.2f} "
          f"risk={sized.risk_at_stop:.2f} of budget {sized.risk_budget:.2f} "
          f"capped_by={sized.capped_by or 'none'}")

    async with pool.ledger().acquire() as con:
        run_id = await con.fetchval(
            """INSERT INTO runs (mode, site, demo, policy_version, code_version, notes)
               VALUES ('paper',$1,$2,$3,'paper-demo',$4) RETURNING run_id""",
            s.okx_site, s.okx_demo, POLICY,
            json.dumps({"purpose": "labelled paper demo of the full order chain"}))
        decision_id = await con.fetchval(
            """INSERT INTO decisions (run_id, inst_id, episode_id, action, setup_id,
                   reason_codes, stage_reached, features, policy_version, data_quality)
               VALUES ($1,$2,'paper-demo','BUY_INTENT','reclaim_v1',
                       ARRAY['RECLAIM_CONFIRMED'],'CONFIRMED',$3,$4,'{}')
               RETURNING decision_id""",
            run_id, INST,
            json.dumps({"level": str(entry), "note": "forced paper candidate"}),
            POLICY)

    venue = PaperVenue(fee_rate=Decimal("0.001"))
    om = OrderManager(venue, run_id)

    intent_id = await om.reserve(
        decision_id=decision_id, inst_id=INST, side="buy",
        equity_at_decision=equity, risk_fraction=s.risk_fraction,
        risk_budget=sized.risk_budget, entry_reference=px_limit,
        structural_stop=stop, price_r_distance=sized.price_r_distance,
        qty=sized.quantity, est_cost_per_unit=sized.est_cost_per_unit,
        policy_version=POLICY)

    outcome = await om.submit_entry(intent_id, INST, sized.quantity, px_limit)
    qty, avg, fees = await om.filled_totals(outcome.client_order_id)
    print(f"entry {outcome.status}: qty={qty} avg={avg} fees={fees:.4f}")

    pos = await open_position(
        venue, run_id=run_id, intent_id=intent_id, inst_id=INST,
        filled_qty=qty, avg_entry_px=avg, structural_stop=stop, spec=spec,
        est_cost_per_unit=sized.est_cost_per_unit, policy_version=POLICY,
        fees_paid=fees)
    p = pos.plan
    print(f"position {pos.position_id} protected={pos.algo_id is not None}")
    print(f"  ladder: BE@{p.breakeven_trigger_px} tp1@{p.tp1_trigger_px} "
          f"({p.tp1_qty}) tp2@{p.tp2_trigger_px} ({p.tp2_qty}) runner {p.runner_qty}")

    # Walk the ladder as if price advanced, to show the accounting.
    assert await apply_breakeven(pos.position_id, avg)
    q1 = await claim_tp_stage(pos.position_id, "tp1")
    await record_exit_fill(pos.position_id, q1, p.tp1_trigger_px,
                           q1 * p.tp1_trigger_px * Decimal("0.001"), avg)
    print(f"  +2R: sold {q1} at {p.tp1_trigger_px}")

    q2 = await claim_tp_stage(pos.position_id, "tp2")
    await record_exit_fill(pos.position_id, q2, p.tp2_trigger_px,
                           q2 * p.tp2_trigger_px * Decimal("0.001"), avg)
    print(f"  +2.5R: sold {q2} at {p.tp2_trigger_px}")

    # Close the runner so the demo leaves no open position behind. The risk gate
    # counts open positions ACROSS runs -- a position surviving a restart must
    # still block new entries -- so a parked demo position would block live work.
    async with pool.ledger().acquire() as con:
        remaining = Decimal(await con.fetchval(
            "SELECT qty_open FROM positions WHERE position_id=$1", pos.position_id))
    if remaining > 0:
        runner_px = p.tp2_trigger_px * Decimal("1.02")
        await record_exit_fill(pos.position_id, remaining, runner_px,
                               remaining * runner_px * Decimal("0.001"), avg)
        print(f"  runner: sold {remaining} at {runner_px}")

    async with pool.ledger().acquire() as con:
        r = await con.fetchrow(
            "SELECT * FROM positions WHERE position_id=$1", pos.position_id)
    realised_r = Decimal(r["realized_pnl"]) / Decimal(r["frozen_risk_amount"])
    print(f"  status={r['status']} open={r['qty_open']} "
          f"realized_pnl={r['realized_pnl']:.4f} = {realised_r:.3f}R "
          f"(denominator frozen at {r['frozen_risk_amount']:.4f})")
    print(f"\nrun_id={run_id} -- visible on the dashboard, labelled PAPER")

    await atk.stop()
    await pool.close_pools()


if __name__ == "__main__":
    asyncio.run(main())
