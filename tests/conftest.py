"""Integration test fixtures.

These talk to a real PostgreSQL, because the invariants under test -- idempotent
fill insertion, atomic reservation, terminal-state protection -- live in the
schema and in transactions, not in Python.

They must NOT talk to the LIVE ledger. Reconciliation and the protection sweep
deliberately act on every open position regardless of which run opened it -- that
is what lets a restart adopt a position from a previous run -- so a test that
hands them a paper venue tells them the account holds nothing, and they close
real positions accordingly. That happened: a sweep test closed a live SOL
position (12 Sep 2026), and the ops event recording it was removed by this
file's own teardown. `live_ledger_guard` below makes that impossible.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from agentic_trade.db import pool

DSN = os.environ.get("DATABASE_URL")
requires_db = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")
ALLOW_LIVE = os.environ.get("ALLOW_TESTS_ON_LIVE_LEDGER") == "1"


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def live_ledger_guard():
    """Refuse to run against a database that holds live trading history.

    An error, not a skip: a silent skip of the whole suite would read as "the
    tests passed" on the one machine where it matters most.
    """
    if not DSN or ALLOW_LIVE:
        return
    await pool.init_pools(DSN)
    try:
        async with pool.ledger().acquire() as con:
            live = await con.fetchval(
                """SELECT count(*) FROM runs r
                   WHERE r.mode='live' AND r.code_version IS NOT NULL
                     AND (EXISTS (SELECT 1 FROM fills f WHERE f.run_id=r.run_id)
                       OR EXISTS (SELECT 1 FROM positions p WHERE p.run_id=r.run_id))"""
            )
    finally:
        await pool.close_pools()
    if live:
        pytest.exit(
            f"DATABASE_URL points at a LIVE ledger ({live} live run(s) with real "
            "positions or fills). These tests close positions and delete rows.\n"
            "Point DATABASE_URL at a scratch database:\n"
            "  createdb -h 127.0.0.1 -p 5433 -U agentic agentic_trade_test\n"
            "  psql ... -d agentic_trade_test < src/agentic_trade/db/schema.sql\n"
            "Set ALLOW_TESTS_ON_LIVE_LEDGER=1 only if you accept losing that data.",
            returncode=2,
        )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db(live_ledger_guard):
    """Session-scoped: the pools cross an SSH tunnel, so rebuilding them per
    test dominated the suite runtime."""
    if not DSN:
        pytest.skip("DATABASE_URL not set")
    await pool.init_pools(DSN)
    # The protection sweep sizes its order from the venue's instrument spec and
    # refuses to guess when there is none. A scratch database starts empty, so
    # seed the pair the suite trades.
    async with pool.ledger().acquire() as con:
        await con.execute(
            """INSERT INTO instruments (venue, inst_id, base_ccy, quote_ccy,
                   tick_sz, lot_sz, min_sz, state)
               VALUES ('okx-tr','BTC-USDT','BTC','USDT',0.1,0.00000001,0.00001,'live')
               ON CONFLICT (venue, inst_id) DO NOTHING""")
    yield pool
    await pool.close_pools()


@pytest_asyncio.fixture(loop_scope="session")
async def run_id(db):
    """A throwaway run, with all of its rows removed afterwards."""
    async with pool.ledger().acquire() as con:
        rid = await con.fetchval(
            """INSERT INTO runs (mode, site, demo, policy_version, notes)
               VALUES ('paper','tr',true,'test_v1','pytest') RETURNING run_id"""
        )
    yield rid
    async with pool.ledger().acquire() as con:
        await con.execute("DELETE FROM fills WHERE run_id=$1", rid)
        await con.execute(
            """DELETE FROM order_events WHERE client_order_id IN
               (SELECT client_order_id FROM orders WHERE run_id=$1)""", rid)
        await con.execute("DELETE FROM orders WHERE run_id=$1", rid)
        await con.execute("DELETE FROM positions WHERE run_id=$1", rid)
        await con.execute("DELETE FROM intents WHERE run_id=$1", rid)
        await con.execute("DELETE FROM decisions WHERE run_id=$1", rid)
        await con.execute("DELETE FROM ops_events WHERE run_id=$1", rid)
        await con.execute("DELETE FROM runs WHERE run_id=$1", rid)


@pytest_asyncio.fixture(loop_scope="session")
async def decision_id(run_id):
    async with pool.ledger().acquire() as con:
        did = await con.fetchval(
            """INSERT INTO decisions (run_id, inst_id, action, setup_id, reason_codes,
                   stage_reached, features, policy_version, data_quality)
               VALUES ($1,'BTC-USDT','BUY_INTENT','reclaim_v1','{}','CONFIRMED',
                       '{}','test_v1','{}')
               RETURNING decision_id""", run_id)
    return did
