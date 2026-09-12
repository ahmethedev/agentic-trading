"""Market data ingestion via ATK REST polling.

ATK 1.4.6 exposes no WebSocket (verified: no `wss://` in the bundle), so all
market data is polled. That is workable but only because trade ids are dense:
`market_get_trades` returns up to 500 prints, measured at ~283s of coverage on
BTC-USDT, and ids are contiguous. We therefore:

  * dedup on (venue, inst_id, trade_id) at the database level, and
  * detect loss by id continuity, not by wall-clock guessing.

A poll that cannot bridge from the last stored id is recorded as an explicit
gap. Missing flow data invalidates the flow feature; it is never read as "no
aggressive buying".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from ..atk.client import AtkClient, AtkError, AtkTimeout
from ..db import pool

log = structlog.get_logger(__name__)

VENUE = "okx-tr"
TRADES_LIMIT = 500


def _ts(ms: str | int) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


@dataclass
class TradePollResult:
    inserted: int
    fetched: int
    gap_detected: bool
    newest_id: int | None
    oldest_id: int | None
    coverage_s: float


class MarketIngestor:
    """Polls candles and trades for a set of instruments into PostgreSQL."""

    def __init__(self, atk: AtkClient, run_id: int, instruments: list[str]) -> None:
        self._atk = atk
        self._run_id = run_id
        self._instruments = instruments
        # highest trade_id durably stored, per instrument
        self._last_trade_id: dict[str, int] = {}
        self._last_trade_ts: dict[str, datetime] = {}
        # Polls that came back completely full are a saturation signal: the
        # window may not have reached back to what we already had.
        self._saturated_polls: dict[str, int] = {}

    # ------------------------------------------------------------- candles --
    async def poll_candles(self, inst_id: str, bar: str, limit: int = 100) -> int:
        """Fetch recent candles and upsert them.

        The in-progress candle (confirm=0) is stored too so the dashboard can
        show it, but strategy code must filter on confirm=true.
        """
        payload = await self._atk.call(
            "market_get_candles", {"instId": inst_id, "bar": bar, "limit": limit}
        )
        rows = payload["data"]["data"]
        records = []
        for r in rows:
            # [ts, o, h, l, c, volBase, volQuote, volCcyQuote, confirm]
            records.append((
                VENUE, inst_id, bar, _ts(r[0]),
                Decimal(r[1]), Decimal(r[2]), Decimal(r[3]), Decimal(r[4]),
                Decimal(r[5]), Decimal(r[6]), r[8] == "1", self._run_id,
            ))
        if not records:
            return 0
        async with pool.market().acquire() as con:
            await con.executemany(
                """
                INSERT INTO candles (venue, inst_id, bar, open_time, open, high, low,
                                     close, vol_base, vol_quote, confirm, run_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (venue, inst_id, bar, open_time) DO UPDATE SET
                    high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
                    vol_base = EXCLUDED.vol_base, vol_quote = EXCLUDED.vol_quote,
                    confirm = EXCLUDED.confirm, received_at = now()
                WHERE candles.confirm = FALSE
                """,
                records,
            )
        return len(records)

    # -------------------------------------------------------------- trades --
    async def poll_trades(self, inst_id: str) -> TradePollResult:
        payload = await self._atk.call(
            "market_get_trades", {"instId": inst_id, "limit": TRADES_LIMIT}
        )
        rows = payload["data"]["data"]
        if not rows:
            return TradePollResult(0, 0, False, None, None, 0.0)

        ids = [int(r["tradeId"]) for r in rows]
        times = [int(r["ts"]) for r in rows]
        newest, oldest = max(ids), min(ids)
        coverage = (max(times) - min(times)) / 1000

        # Gap check: the batch must reach back to what we already have. If the
        # oldest id in this batch is more than one past our last stored id, the
        # trades in between were never observed and are lost.
        last_seen = self._last_trade_id.get(inst_id)
        gap = False
        if last_seen is not None and oldest > last_seen + 1:
            gap = True
            missing = oldest - last_seen - 1
            oldest_ts = _ts(min(times))
            # Timestamps bound the unobserved interval so downstream features can
            # tell whether a gap overlaps the window they are about to compute.
            await self._record_gap(
                inst_id, "trades",
                first_missing_id=last_seen + 1,
                last_missing_id=oldest - 1,
                missing_count=missing,
                gap_from=self._last_trade_ts.get(inst_id),
                gap_to=oldest_ts,
                reason="trade id discontinuity between polls (venue burst exceeded "
                       "the 500-print window, or the poll interval was too slow)",
            )
            log.warning("ingest.trade_gap", inst_id=inst_id, missing=missing,
                        last_seen=last_seen, batch_oldest=oldest)

        records = [
            (VENUE, inst_id, int(r["tradeId"]), _ts(r["ts"]),
             Decimal(r["px"]), Decimal(r["sz"]), r["side"], self._run_id)
            for r in rows
        ]
        async with pool.market().acquire() as con:
            # ON CONFLICT DO NOTHING makes overlapping polls idempotent.
            result = await con.executemany(
                """
                INSERT INTO market_trades
                    (venue, inst_id, trade_id, ts, px, sz, side, run_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (venue, inst_id, trade_id) DO NOTHING
                """,
                records,
            )
        _ = result
        inserted = await self._count_new(inst_id, oldest, newest, last_seen)
        self._last_trade_id[inst_id] = newest
        self._last_trade_ts[inst_id] = _ts(max(times))
        if len(rows) >= TRADES_LIMIT:
            self._saturated_polls[inst_id] = self._saturated_polls.get(inst_id, 0) + 1
        return TradePollResult(inserted, len(rows), gap, newest, oldest, coverage)

    async def _count_new(
        self, inst_id: str, oldest: int, newest: int, last_seen: int | None
    ) -> int:
        if last_seen is None:
            return newest - oldest + 1
        return max(0, newest - last_seen)

    async def _record_gap(
        self, inst_id: str, stream: str, *, first_missing_id: int | None = None,
        last_missing_id: int | None = None, missing_count: int | None = None,
        gap_from: datetime | None = None, gap_to: datetime | None = None,
        reason: str,
    ) -> None:
        async with pool.market().acquire() as con:
            await con.execute(
                """
                INSERT INTO data_gaps (venue, inst_id, stream, first_missing_id,
                                       last_missing_id, missing_count, gap_from,
                                       gap_to, reason, run_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                VENUE, inst_id, stream, first_missing_id, last_missing_id,
                missing_count, gap_from, gap_to, reason, self._run_id,
            )

    async def prime_last_trade_id(self) -> None:
        """Restore per-instrument watermarks after a restart."""
        async with pool.market().acquire() as con:
            rows = await con.fetch(
                """
                SELECT inst_id, max(trade_id) AS mx, max(ts) AS mx_ts
                FROM market_trades
                WHERE venue = $1 AND inst_id = ANY($2::text[]) GROUP BY inst_id
                """,
                VENUE, self._instruments,
            )
        for r in rows:
            self._last_trade_id[r["inst_id"]] = int(r["mx"])
            if r["mx_ts"] is not None:
                self._last_trade_ts[r["inst_id"]] = r["mx_ts"]
        if rows:
            log.info("ingest.primed", watermarks=dict(self._last_trade_id))

    # ---------------------------------------------------------------- loop --
    async def run(self, *, trade_interval_s: float = 5.0,
                  candle_interval_s: float = 20.0,
                  bars: tuple[str, ...] = ("5m", "15m"),
                  stop: asyncio.Event | None = None) -> None:
        await self.prime_last_trade_id()
        stop = stop or asyncio.Event()
        tasks = [
            asyncio.create_task(self._trade_loop(i, trade_interval_s, stop))
            for i in self._instruments
        ]
        tasks += [
            asyncio.create_task(self._candle_loop(i, bars, candle_interval_s, stop))
            for i in self._instruments
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _trade_loop(self, inst_id: str, interval: float, stop: asyncio.Event) -> None:
        # Per-instrument isolation: one stuck symbol must not stall the others.
        while not stop.is_set():
            try:
                res = await self.poll_trades(inst_id)
                log.debug("ingest.trades", inst=inst_id, new=res.inserted,
                          coverage_s=round(res.coverage_s, 1), gap=res.gap_detected)
            except AtkTimeout:
                log.warning("ingest.trades.timeout", inst=inst_id)
            except AtkError as exc:
                log.error("ingest.trades.error", inst=inst_id, err=str(exc)[:200])
            except Exception as exc:  # noqa: BLE001
                log.exception("ingest.trades.unexpected", inst=inst_id, err=str(exc)[:200])
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def _candle_loop(
        self, inst_id: str, bars: tuple[str, ...], interval: float, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            for bar in bars:
                try:
                    n = await self.poll_candles(inst_id, bar)
                    log.debug("ingest.candles", inst=inst_id, bar=bar, rows=n)
                except AtkTimeout:
                    log.warning("ingest.candles.timeout", inst=inst_id, bar=bar)
                except AtkError as exc:
                    log.error("ingest.candles.error", inst=inst_id, bar=bar,
                              err=str(exc)[:200])
                except Exception as exc:  # noqa: BLE001
                    log.exception("ingest.candles.unexpected", inst=inst_id,
                                  err=str(exc)[:200])
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass
