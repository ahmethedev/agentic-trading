"""asyncpg connection pools.

Two separate pools so that bulk market-data writes and dashboard queries can
never starve the financial-ledger work (AGENT.md §7): a stuck analytics query
must not delay a stop-loss write.

A third, optional pool serves the product tables (strategy versions and
simulated experiment runs). The API opens `ledger` and `market` read-only at the
database level -- the dashboard and the chat model cannot write to the ledger,
by the server's own transaction setting rather than by our care -- and that
property is worth keeping. So writes for the experiment lab go through their own
pool instead of relaxing those two. Its write access is bounded by which SQL
this application sends, not by a database grant; see docs/PRODUCT_PROGRESS.md.
"""

from __future__ import annotations

import asyncpg

_ledger_pool: asyncpg.Pool | None = None
_market_pool: asyncpg.Pool | None = None
_product_pool: asyncpg.Pool | None = None


async def init_pools(dsn: str, *, read_only: bool = False, product: bool = False) -> None:
    global _ledger_pool, _market_pool, _product_pool
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
    if product and _product_pool is None:
        _product_pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=4,
            command_timeout=20,
            server_settings={
                "search_path": "at,public",
                "application_name": "at-product",
            },
        )


async def close_pools() -> None:
    global _ledger_pool, _market_pool, _product_pool
    for pool in (_ledger_pool, _market_pool, _product_pool):
        if pool is not None:
            await pool.close()
    _ledger_pool = None
    _market_pool = None
    _product_pool = None


def ledger() -> asyncpg.Pool:
    if _ledger_pool is None:
        raise RuntimeError("pools not initialised; call init_pools() first")
    return _ledger_pool


def market() -> asyncpg.Pool:
    if _market_pool is None:
        raise RuntimeError("pools not initialised; call init_pools() first")
    return _market_pool


def product() -> asyncpg.Pool:
    """Writable pool for the strategy/experiment tables only."""
    if _product_pool is None:
        raise RuntimeError("product pool not initialised; call init_pools(product=True)")
    return _product_pool


def product_available() -> bool:
    return _product_pool is not None
