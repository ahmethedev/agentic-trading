"""Read-only dashboard API.

The dashboard reads the same persistent store the worker writes; it never
recomputes PnL or risk (AGENT.md §9). Closing the dashboard cannot affect the
bot, and no endpoint here can place or cancel an order.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from ..db import pool

VENUE = "okx-tr"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.init_pools(get_settings().database_url)
    yield
    await pool.close_pools()


app = FastAPI(title="Agentic Trade", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"], allow_headers=["*"],
)


def _j(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


@app.get("/api/status")
async def status() -> dict[str, Any]:
    """Top status strip: mode, data health, credentials, run info."""
    s = get_settings()
    async with pool.ledger().acquire() as con:
        run = await con.fetchrow(
            "SELECT * FROM runs ORDER BY run_id DESC LIMIT 1"
        )
        gaps = await con.fetchval(
            "SELECT count(*) FROM data_gaps WHERE detected_at > now() - interval '1 hour'"
        )
        ops = await con.fetch(
            """SELECT ts, severity, kind, inst_id, detail FROM ops_events
               ORDER BY ts DESC LIMIT 20"""
        )
    async with pool.market().acquire() as con:
        freshness = await con.fetch(
            """SELECT inst_id,
                      max(ts) AS last_trade_ts,
                      EXTRACT(EPOCH FROM (now() - max(ts))) AS age_s,
                      count(*) FILTER (WHERE ts > now() - interval '60 seconds') AS trades_60s
               FROM market_trades WHERE venue=$1 GROUP BY inst_id ORDER BY inst_id""",
            VENUE,
        )
    return {
        "mode": s.mode,
        "site": s.okx_site,
        "demo": s.okx_demo,
        "authenticated": s.has_credentials,
        "missing_credentials": s.missing_credentials(),
        "policy_version": run["policy_version"] if run else None,
        "run_id": run["run_id"] if run else None,
        "run_started_at": run["started_at"].isoformat() if run else None,
        "run_stopped_at": (
            run["stopped_at"].isoformat() if run and run["stopped_at"] else None
        ),
        "risk_fraction": str(s.risk_fraction),
        "risk_fraction_max": str(s.risk_fraction_max),
        "gaps_last_hour": gaps,
        "data_freshness": [
            {
                "inst_id": r["inst_id"],
                "last_trade_ts": r["last_trade_ts"].isoformat(),
                "age_s": round(float(r["age_s"]), 1),
                "trades_60s": r["trades_60s"],
            }
            for r in freshness
        ],
        "ops_events": [
            {"ts": r["ts"].isoformat(), "severity": r["severity"], "kind": r["kind"],
             "inst_id": r["inst_id"], "detail": _j(r["detail"])}
            for r in ops
        ],
    }


@app.get("/api/decisions")
async def decisions(
    inst_id: str | None = None, limit: int = Query(50, le=500)
) -> list[dict[str, Any]]:
    """Latest decision cards, including every WAIT and its reason."""
    async with pool.ledger().acquire() as con:
        rows = await con.fetch(
            """SELECT decision_id, inst_id, decided_at, candle_open_time, episode_id,
                      action, setup_id, reason_codes, stage_reached, features,
                      policy_version, data_quality
               FROM decisions
               WHERE ($1::text IS NULL OR inst_id = $1)
               ORDER BY decided_at DESC LIMIT $2""",
            inst_id, limit,
        )
    return [
        {
            "decision_id": r["decision_id"], "inst_id": r["inst_id"],
            "decided_at": r["decided_at"].isoformat(),
            "candle_open_time": (
                r["candle_open_time"].isoformat() if r["candle_open_time"] else None
            ),
            "episode_id": r["episode_id"], "action": r["action"],
            "setup_id": r["setup_id"], "reason_codes": list(r["reason_codes"]),
            "stage_reached": r["stage_reached"], "features": _j(r["features"]),
            "policy_version": r["policy_version"], "data_quality": _j(r["data_quality"]),
        }
        for r in rows
    ]


@app.get("/api/funnel")
async def funnel(hours: int = Query(6, le=48)) -> dict[str, Any]:
    """Opportunity funnel.

    Counts DISTINCT episodes, not evaluations: one setup seen on ten consecutive
    bars is one opportunity, not ten (AGENT.md §2).
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with pool.ledger().acquire() as con:
        stages = await con.fetch(
            """SELECT stage_reached, count(*) AS evaluations,
                      count(DISTINCT episode_id) FILTER (WHERE episode_id IS NOT NULL)
                        AS episodes
               FROM decisions WHERE decided_at >= $1
               GROUP BY stage_reached ORDER BY 2 DESC""",
            since,
        )
        codes = await con.fetch(
            """SELECT unnest(reason_codes) AS code, count(*) AS n
               FROM decisions WHERE decided_at >= $1
               GROUP BY 1 ORDER BY 2 DESC LIMIT 15""",
            since,
        )
        last_candidate = await con.fetchrow(
            """SELECT decided_at, inst_id FROM decisions
               WHERE stage_reached = 'CONFIRMED'
               ORDER BY decided_at DESC LIMIT 1"""
        )
    return {
        "window_hours": hours,
        "stages": [
            {"stage": r["stage_reached"], "evaluations": r["evaluations"],
             "episodes": r["episodes"]}
            for r in stages
        ],
        "reason_codes": [{"code": r["code"], "count": r["n"]} for r in codes],
        "last_confirmed": (
            {"decided_at": last_candidate["decided_at"].isoformat(),
             "inst_id": last_candidate["inst_id"]}
            if last_candidate else None
        ),
        "seconds_since_last_confirmed": (
            round((datetime.now(UTC) - last_candidate["decided_at"]).total_seconds())
            if last_candidate else None
        ),
    }


@app.get("/api/candles")
async def candles(
    inst_id: str, bar: str = "5m", limit: int = Query(200, le=1000)
) -> list[dict[str, Any]]:
    async with pool.market().acquire() as con:
        rows = await con.fetch(
            """SELECT open_time, open, high, low, close, vol_quote, confirm
               FROM candles WHERE venue=$1 AND inst_id=$2 AND bar=$3
               ORDER BY open_time DESC LIMIT $4""",
            VENUE, inst_id, bar, limit,
        )
    return [
        {"time": int(r["open_time"].timestamp()), "open": float(r["open"]),
         "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]),
         "volume": float(r["vol_quote"]), "confirm": r["confirm"]}
        for r in reversed(rows)
    ]


@app.get("/api/flow")
async def flow(inst_id: str, minutes: int = Query(30, le=240)) -> list[dict[str, Any]]:
    """Per-minute taker buy/sell notional, for the flow panel."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    async with pool.market().acquire() as con:
        rows = await con.fetch(
            """SELECT date_trunc('minute', ts) AS m,
                      sum(px*sz) FILTER (WHERE side='buy')  AS buy,
                      sum(px*sz) FILTER (WHERE side='sell') AS sell,
                      count(*) AS n
               FROM market_trades WHERE venue=$1 AND inst_id=$2 AND ts >= $3
               GROUP BY 1 ORDER BY 1""",
            VENUE, inst_id, since,
        )
    out = []
    for r in rows:
        buy = float(r["buy"] or 0)
        sell = float(r["sell"] or 0)
        total = buy + sell
        out.append({
            "time": int(r["m"].timestamp()), "buy": buy, "sell": sell,
            "trades": r["n"],
            "imbalance": (buy - sell) / total if total > 0 else None,
        })
    return out


@app.get("/api/positions")
async def positions() -> dict[str, Any]:
    """Open and recent positions with their frozen R basis and exit progress."""
    async with pool.ledger().acquire() as con:
        rows = await con.fetch(
            """SELECT p.*, i.qty_requested,
                      (SELECT count(*) FROM orders o
                        WHERE o.intent_id=p.intent_id AND o.purpose='STOP'
                          AND o.algo_id IS NOT NULL) AS protection_orders
               FROM positions p LEFT JOIN intents i USING (intent_id)
               ORDER BY p.opened_at DESC LIMIT 25"""
        )
        orders = await con.fetch(
            """SELECT client_order_id, inst_id, purpose, side, ord_type, status,
                      qty_requested, qty_filled, avg_px, px_limit, algo_id,
                      sent_at, terminal_at
               FROM orders ORDER BY created_at DESC LIMIT 25"""
        )
    def pos(r):
        initial = r["initial_qty"] or 0
        closed = (initial - (r["qty_open"] or 0))
        realised_r = (
            float(r["realized_pnl"]) / float(r["frozen_risk_amount"])
            if r["frozen_risk_amount"] else None
        )
        return {
            "position_id": r["position_id"], "inst_id": r["inst_id"],
            "status": r["status"], "opened_at": r["opened_at"].isoformat(),
            "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
            "initial_qty": str(initial), "qty_open": str(r["qty_open"]),
            "qty_closed": str(closed),
            "avg_entry_px": str(r["avg_entry_px"]),
            "initial_stop_px": str(r["initial_stop_px"]),
            "current_stop_px": (
                str(r["current_stop_px"]) if r["current_stop_px"] else None),
            # The R denominator is frozen at entry and never rebased.
            "frozen_risk_amount": str(r["frozen_risk_amount"]),
            "price_r_distance": str(r["price_r_distance"]),
            "realized_pnl": str(r["realized_pnl"]),
            "realized_r": round(realised_r, 3) if realised_r is not None else None,
            "fees_paid": str(r["fees_paid"]),
            "breakeven_moved": r["breakeven_moved"],
            "tp1_done": r["tp1_done"], "tp2_done": r["tp2_done"],
            "protected": r["protection_orders"] > 0,
            "policy_version": r["policy_version"],
        }
    return {
        "positions": [pos(r) for r in rows],
        "orders": [
            {"client_order_id": o["client_order_id"], "inst_id": o["inst_id"],
             "purpose": o["purpose"], "side": o["side"], "ord_type": o["ord_type"],
             "status": o["status"], "qty_requested": str(o["qty_requested"]),
             "qty_filled": str(o["qty_filled"]),
             "avg_px": str(o["avg_px"]) if o["avg_px"] else None,
             "algo_id": o["algo_id"],
             "sent_at": o["sent_at"].isoformat() if o["sent_at"] else None,
             "terminal": o["terminal_at"] is not None}
            for o in orders
        ],
    }


@app.get("/api/instruments")
async def instruments() -> list[dict[str, Any]]:
    async with pool.ledger().acquire() as con:
        rows = await con.fetch(
            "SELECT inst_id, tick_sz, lot_sz, min_sz, state FROM instruments "
            "WHERE venue=$1 ORDER BY inst_id", VENUE
        )
    return [
        {"inst_id": r["inst_id"], "tick_sz": str(r["tick_sz"]),
         "lot_sz": str(r["lot_sz"]), "min_sz": str(r["min_sz"]), "state": r["state"]}
        for r in rows
    ]
