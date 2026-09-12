"""Feature computation from stored market data.

Every feature carries its own validity flag. A feature that could not be
computed from sufficient data is INVALID, never silently zero or neutral --
missing aggressive-sell data must not read as "buyers in control"
(AGENT.md §4).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..db import pool

VENUE = "okx-tr"

# Relative volume compares the closed candle against the median of the previous
# N closed candles. The candle under test is excluded from its own denominator.
RVOL_LOOKBACK = 20
# Order-flow window. 60s is the starting draft from AGENT.md §4, not a tuned value.
FLOW_WINDOW_S = 60
# Newest print may be no older than this, otherwise the poller is considered
# stalled. Sized against the trade poll interval (15s), not the flow window.
MAX_FLOW_STALENESS_S = 45.0
# An imbalance computed from a handful of prints is noise, not confirmation:
# 4 trades can read as imbalance 1.0 purely by chance. Thin books therefore
# yield NO flow signal rather than a maximally confident one.
MIN_FLOW_TRADES = 20
# ATR period on the context timeframe.
ATR_PERIOD = 14


@dataclass
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    vol_base: Decimal
    vol_quote: Decimal


@dataclass
class FlowFeature:
    valid: bool
    imbalance: float | None          # (B - S) / (B + S)
    buy_notional: Decimal
    sell_notional: Decimal
    trade_count: int
    coverage_s: float
    reason: str | None = None


@dataclass
class FeatureSnapshot:
    inst_id: str
    computed_at: datetime
    candle_open_time: datetime | None
    close: Decimal | None
    close_position: float | None      # (close - low) / (high - low)
    rvol: float | None                # quote vol / median of previous N
    atr: Decimal | None
    trend_slope_atr: float | None     # MA slope normalised by ATR
    above_ma: bool | None
    flow: FlowFeature | None
    data_age_s: float | None
    # Stable machine-readable codes, safe to aggregate in the funnel.
    invalid_codes: list[str] = field(default_factory=list)
    # Human-readable detail for the same problems; never aggregated as a code.
    invalid_reasons: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.invalid_codes


async def load_closed_candles(inst_id: str, bar: str, limit: int = 60) -> list[Candle]:
    """Most recent CLOSED candles, oldest first."""
    async with pool.market().acquire() as con:
        rows = await con.fetch(
            """
            SELECT open_time, open, high, low, close, vol_base, vol_quote
            FROM candles
            WHERE venue=$1 AND inst_id=$2 AND bar=$3 AND confirm
            ORDER BY open_time DESC LIMIT $4
            """,
            VENUE, inst_id, bar, limit,
        )
    return [Candle(**dict(r)) for r in reversed(rows)]


def close_position(c: Candle) -> float | None:
    """Where the close sits inside the bar's range. Zero-range bars are undefined."""
    rng = c.high - c.low
    if rng <= 0:
        return None
    return float((c.close - c.low) / rng)


def relative_volume(candles: list[Candle], lookback: int = RVOL_LOOKBACK) -> float | None:
    """Latest closed candle's quote volume vs the median of the previous `lookback`.

    The candle under test is excluded from the denominator.
    """
    if len(candles) < lookback + 1:
        return None
    prior = [float(c.vol_quote) for c in candles[-(lookback + 1):-1]]
    med = statistics.median(prior)
    if med <= 0:
        return None
    return float(candles[-1].vol_quote) / med


def atr(candles: list[Candle], period: int = ATR_PERIOD) -> Decimal | None:
    """Wilder-style true range average (simple mean over `period`)."""
    if len(candles) < period + 1:
        return None
    trs: list[Decimal] = []
    for prev, cur in zip(candles[-(period + 1):-1], candles[-period:], strict=True):
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        trs.append(tr)
    return sum(trs) / Decimal(len(trs))


def trend_context(
    candles: list[Candle], ma_period: int = 20, slope_lookback: int = 5
) -> tuple[bool | None, float | None]:
    """Simple auditable trend context: price vs MA, plus ATR-normalised MA slope.

    Deliberately plain (AGENT.md §4): a weak slope is reported as weak, never
    reclassified as "range".
    """
    if len(candles) < ma_period + slope_lookback:
        return None, None
    closes = [float(c.close) for c in candles]

    def ma_at(end: int) -> float:
        return sum(closes[end - ma_period:end]) / ma_period

    ma_now = ma_at(len(closes))
    ma_prev = ma_at(len(closes) - slope_lookback)
    a = atr(candles)
    if a is None or a <= 0:
        return closes[-1] > ma_now, None
    slope_per_bar = (ma_now - ma_prev) / slope_lookback
    return closes[-1] > ma_now, slope_per_bar / float(a)


async def compute_flow(
    inst_id: str, window_s: int = FLOW_WINDOW_S, max_staleness_s: float = MAX_FLOW_STALENESS_S
) -> FlowFeature:
    """Taker buy/sell imbalance over the trailing window, from stored prints.

    flow_imbalance = (B - S) / (B + S), B/S = taker buy/sell quote notional.

    Window completeness and data freshness are measured SEPARATELY. The window
    is anchored on the newest stored print, not on wall-clock `now`: with REST
    polling the newest print is always a few seconds old, so anchoring on `now`
    would permanently report a partial window and block every entry. Staleness
    is then checked on its own, so a stalled poller is still caught.
    """
    now = datetime.now(UTC)
    async with pool.market().acquire() as con:
        bounds = await con.fetchrow(
            """
            SELECT max(ts) AS last_ts, min(ts) AS first_ts
            FROM market_trades WHERE venue=$1 AND inst_id=$2
            """,
            VENUE, inst_id,
        )
    if not bounds or bounds["last_ts"] is None:
        return FlowFeature(False, None, Decimal(0), Decimal(0), 0, 0.0,
                           "no trades stored for instrument")

    last_ts = bounds["last_ts"]
    first_ts = bounds["first_ts"]

    # Freshness: is the poller keeping up at all?
    staleness = (now - last_ts).total_seconds()
    if staleness > max_staleness_s:
        return FlowFeature(False, None, Decimal(0), Decimal(0), 0, 0.0,
                           f"flow data stale: newest print {staleness:.0f}s old")

    window_start = last_ts - timedelta(seconds=window_s)

    # Integrity: a recorded gap overlapping this window means prints inside it
    # were never observed. A venue sweep can emit 1000+ micro-prints in seconds
    # and blow through the 500-print REST page, so this is not hypothetical --
    # an imbalance computed over a holed window is simply wrong, not merely
    # noisy, because the missing prints are all on one side of the sweep.
    async with pool.market().acquire() as con:
        holed = await con.fetchval(
            """
            SELECT coalesce(sum(missing_count),0) FROM data_gaps
            WHERE venue=$1 AND inst_id=$2 AND stream='trades'
              AND gap_to > $3 AND gap_from < $4
            """,
            VENUE, inst_id, window_start, last_ts,
        )
    if holed:
        return FlowFeature(False, None, Decimal(0), Decimal(0), 0, 0.0,
                           f"flow window contains a data gap ({holed} prints missing)")

    # Completeness: our history must reach back past the window start, otherwise
    # we are still warming up and a partial window would understate one side.
    if first_ts > window_start:
        covered = (last_ts - first_ts).total_seconds()
        return FlowFeature(False, None, Decimal(0), Decimal(0), 0, covered,
                           f"warming up: only {covered:.0f}s of {window_s}s history")

    async with pool.market().acquire() as con:
        rows = await con.fetch(
            """
            SELECT side, sum(px * sz) AS notional, count(*) AS n
            FROM market_trades
            WHERE venue=$1 AND inst_id=$2 AND ts > $3 AND ts <= $4
            GROUP BY side
            """,
            VENUE, inst_id, window_start, last_ts,
        )
    buy = sell = Decimal(0)
    count = 0
    for r in rows:
        if r["side"] == "buy":
            buy = r["notional"] or Decimal(0)
        else:
            sell = r["notional"] or Decimal(0)
        count += r["n"]

    if count == 0:
        return FlowFeature(False, None, buy, sell, 0, float(window_s),
                           "no prints inside the flow window")
    if count < MIN_FLOW_TRADES:
        return FlowFeature(False, None, buy, sell, count, float(window_s),
                           f"insufficient sample: {count} prints < {MIN_FLOW_TRADES} "
                           "(instrument too thin for a flow read)")

    total = buy + sell
    if total <= 0:
        return FlowFeature(False, None, buy, sell, count, float(window_s),
                           "zero notional in window")
    return FlowFeature(True, float((buy - sell) / total), buy, sell, count,
                       float(window_s))


async def compute_snapshot(
    inst_id: str, *, setup_bar: str = "5m", context_bar: str = "15m"
) -> FeatureSnapshot:
    """Full feature snapshot for one instrument."""
    now = datetime.now(UTC)
    setup = await load_closed_candles(inst_id, setup_bar)
    context = await load_closed_candles(inst_id, context_bar)
    reasons: list[str] = []

    codes: list[str] = []
    if not setup:
        return FeatureSnapshot(
            inst_id, now, None, None, None, None, None, None, None, None, None,
            ["NO_SETUP_CANDLES"], ["no closed setup candles"],
        )

    last = setup[-1]
    bar_s = {"1m": 60, "5m": 300, "15m": 900}.get(setup_bar, 300)
    # Age is measured from the bar's CLOSE, not its open.
    age = (now - (last.open_time + timedelta(seconds=bar_s))).total_seconds()
    if age > bar_s * 2:
        codes.append("STALE_SETUP_CANDLE")
        reasons.append(f"setup candle stale ({age:.0f}s past close)")

    rvol = relative_volume(setup)
    if rvol is None:
        codes.append("NO_RVOL_HISTORY")
        reasons.append("insufficient history for relative volume")

    a = atr(context)
    if a is None:
        codes.append("NO_ATR_HISTORY")
        reasons.append("insufficient history for ATR")

    above, slope = trend_context(context)
    if above is None:
        codes.append("NO_TREND_HISTORY")
        reasons.append("insufficient history for trend context")

    flow = await compute_flow(inst_id)
    if not flow.valid:
        codes.append("FLOW_INVALID")
        reasons.append(f"flow invalid: {flow.reason}")

    return FeatureSnapshot(
        inst_id=inst_id, computed_at=now, candle_open_time=last.open_time,
        close=last.close, close_position=close_position(last), rvol=rvol, atr=a,
        trend_slope_atr=slope, above_ma=above, flow=flow, data_age_s=age,
        invalid_codes=codes, invalid_reasons=reasons,
    )
