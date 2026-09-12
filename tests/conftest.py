"""Integration test fixtures.

These talk to the real PostgreSQL (via the SSH tunnel), because the invariants
under test -- idempotent fill insertion, atomic reservation, terminal-state
protection -- live in the schema and in transactions, not in Python.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from agentic_trade.db import pool

DSN = os.environ.get("DATABASE_URL")
requires_db = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db():
    """Session-scoped: the pools cross an SSH tunnel, so rebuilding them per
    test dominated the suite runtime."""
    if not DSN:
        pytest.skip("DATABASE_URL not set")
    await pool.init_pools(DSN)
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
