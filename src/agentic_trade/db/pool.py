"""asyncpg connection pools.

Two separate pools so that bulk market-data writes and dashboard queries can
never starve the financial-ledger work (AGENT.md §7): a stuck analytics query
must not delay a stop-loss write.
"""

from __future__ import annotations

import asyncpg

_ledger_pool: asyncpg.Pool | None = None
_market_pool: asyncpg.Pool | None = None


async def init_pools(dsn: str, *, read_only: bool = False) -> None:
    global _ledger_pool, _market_pool
    settings = {"default_transaction_read_only": "on"} if read_only else {}
    if _ledger_pool is None:
        _ledger_pool = await asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=8,
            command_timeout=10,
            server_settings={
                **settings,
                "search_path": "at,public",
                "application_name": "at-ledger",
            },
        )
    if _market_pool is None:
        _market_pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=6,
            command_timeout=30,
            server_settings={
                **settings,
                "search_path": "at,public",
                "application_name": "at-market",
            },
        )


async def close_pools() -> None:
    global _ledger_pool, _market_pool
    for pool in (_ledger_pool, _market_pool):
        if pool is not None:
            await pool.close()
    _ledger_pool = None
    _market_pool = None


def ledger() -> asyncpg.Pool:
    if _ledger_pool is None:
        raise RuntimeError("pools not initialised; call init_pools() first")
    return _ledger_pool


def market() -> asyncpg.Pool:
    if _market_pool is None:
        raise RuntimeError("pools not initialised; call init_pools() first")
    return _market_pool
