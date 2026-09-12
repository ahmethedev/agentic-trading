"""Deterministic simulation of one strategy version over recorded data.

Pure functions: recorded candidates and recorded candles in, a run result out.
No database, no venue, no model. The same inputs always produce the same result,
which is what lets a run be re-evaluated on demand instead of needing a process
of its own to tick.

What is honest here, and what is assumed, stated once (PRODUCT.md §8):

* Entries are RECORDED setup candidates from the worker's own decision log, with
  the evidence frozen at that moment. A changed threshold is re-applied to that
  evidence, so a looser rule can admit a candidate the live worker rejected and a
  tighter one can drop a candidate it took. Candles the worker discarded before
  the setup stage (regime or pivot) carry no frozen evidence and can never enter
  a run -- an experiment can re-judge recorded candidates, not discover new ones.
* Exits are walked over CLOSED candles at the setup resolution (5m). Anything
  that happened inside a candle is invisible.
* When one candle touches both the stop and a target, the order is unknowable.
  The stop is taken -- the conservative side -- and the trade is flagged
  ambiguous so the count is visible instead of buried in the total.
* A stop that moves (breakeven) takes effect from the NEXT candle.
* Each leg carries its own simulated inventory and cash. A leg that is holding a
  position skips the candidates that arrive while it is busy, exactly as the live
  concurrency limit does -- so two legs need not take the same trades.
* Trades still open when the data runs out are reported as open observations.
  They are never counted as a win, a loss, or a zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

BAR_SECONDS = 300  # setup timeframe, 5m
MIN_CLOSED_SAMPLE = 20  # below this a comparison reports "evidence insufficient"


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Candidate:
    """One recorded setup evaluation, with the evidence frozen at that moment."""

    decision_id: int
    run_id: int
    inst_id: str
    episode_id: str
    decided_at: datetime
    candle_open_time: datetime
    entry_reference: Decimal
    structural_stop: Decimal
    evidence: dict[str, Any]

    @property
    def entry_at(self) -> datetime:
        """The close of the trigger candle: the first moment an entry is possible."""
        return self.candle_open_time + timedelta(seconds=BAR_SECONDS)


@dataclass
class Assumptions:
    taker_fee_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal("0")
    equity_quote: Decimal = Decimal("1000")
    bar: str = "5m"

    def as_dict(self) -> dict[str, Any]:
        return {
            "taker_fee_rate": str(self.taker_fee_rate),
            "slippage_bps": str(self.slippage_bps),
            "equity_quote": str(self.equity_quote),
            "bar": self.bar,
            "resolution_note": "Çıkışlar kapanmış 5 dakikalık mumlarla yürütülür; "
            "mum içi sıralama görünmez.",
            "fee_note": "Giriş ve her çıkış bacağı taker ücretiyle yüklenir; "
            "OKX'in gerçek kademeli ücreti değil, sabit varsayımdır.",
            "window_note": "Giriş penceresi sabittir; açık kalan gözlemler yeni mumlar "
            "geldikçe çözülür ve o zamana kadar sonuç sayılmaz.",
        }


@dataclass
class ExitLeg:
    reason: str          # 'stop' | 'tp1' | 'tp2' | 'time' | 'stop_ambiguous'
    at: datetime
    px: Decimal
    qty: Decimal
    r_multiple: float


@dataclass
class Trade:
    candidate: Candidate
    entry_px: Decimal
    stop_px: Decimal
    price_r: Decimal
    qty: Decimal
    entry_fee: Decimal
    fee_rate: Decimal
    legs: list[ExitLeg] = field(default_factory=list)
    status: str = "OPEN"          # 'OPEN' | 'CLOSED'
    ambiguous: bool = False
    breakeven_applied: bool = False
    closed_at: datetime | None = None
    bars_held: int = 0

    @property
    def gross_quote(self) -> Decimal:
        return sum((leg.qty * (leg.px - self.entry_px) for leg in self.legs), Decimal(0))

    @property
    def fees_quote(self) -> Decimal:
        return self.entry_fee_realised + sum(
            (leg.qty * leg.px * self.fee_rate for leg in self.legs), Decimal(0)
        )

    @property
    def entry_fee_realised(self) -> Decimal:
        """Entry fee charged pro-rata to the quantity actually exited."""
        if not self.qty:
            return Decimal(0)
        exited = sum((leg.qty for leg in self.legs), Decimal(0))
        return self.entry_fee * exited / self.qty

    @property
    def net_quote(self) -> Decimal:
        return self.gross_quote - self.fees_quote

    def as_dict(self, risk_budget: Decimal) -> dict[str, Any]:
        def as_r(value: Decimal) -> float | None:
            return round(float(value / risk_budget), 3) if risk_budget else None

        return {
            "decision_id": self.candidate.decision_id,
            "run_id": self.candidate.run_id,
            "inst_id": self.candidate.inst_id,
            "episode_id": self.candidate.episode_id,
            "entry_at": self.candidate.entry_at,
            "entry_px": str(self.entry_px),
            "stop_px": str(self.stop_px),
            "price_r_distance": str(self.price_r),
            "qty": str(self.qty),
            "status": self.status,
            "ambiguous": self.ambiguous,
            "breakeven_applied": self.breakeven_applied,
            "bars_held": self.bars_held,
            "closed_at": self.closed_at,
            "legs": [
                {
                    "reason": leg.reason,
                    "at": leg.at,
                    "px": str(leg.px),
                    "qty": str(leg.qty),
                    "r_multiple": round(leg.r_multiple, 3),
                }
                for leg in self.legs
            ],
            # An unresolved trade has no result yet. Reporting the realised part
            # as its net would count a half-finished sample as a win, a loss or a
            # zero, which is exactly what PRODUCT.md §14 forbids -- so the result
            # fields stay empty and what HAS been banked is reported separately.
            "gross_r": as_r(self.gross_quote) if self.status == "CLOSED" else None,
            "net_r": as_r(self.net_quote) if self.status == "CLOSED" else None,
            "net_quote": (
                str(self.net_quote.quantize(Decimal("0.0001")))
                if self.status == "CLOSED"
                else None
            ),
            "banked_r_so_far": as_r(self.net_quote) if self.status != "CLOSED" else None,
            "fees_quote": str(self.fees_quote.quantize(Decimal("0.0001"))),
        }


GATES = (
    ("min_rvol", "rvol", "at_least", "RVOL_TOO_LOW"),
    ("min_flow_imbalance", "flow_imbalance", "at_least", "FLOW_NOT_BUY_DOMINANT"),
    ("min_close_position", "close_position", "at_least", "WEAK_CLOSE_POSITION"),
    ("min_pullback_atr", "pullback_depth_atr", "at_least", "PULLBACK_TOO_SHALLOW"),
    ("max_extension_atr", "extension_atr", "at_most", "TOO_EXTENDED"),
    ("min_stop_distance_atr", "stop_distance_atr", "at_least", "STOP_TOO_TIGHT"),
)


def qualifies(candidate: Candidate, entry_rules: dict[str, Any]) -> list[str]:
    """Re-apply this version's entry gates to frozen evidence.

    Returns the failing codes; empty means the candidate is an entry for this
    version. A missing measurement fails its gate -- absent flow data is not
    permission to enter.
    """
    failed: list[str] = []
    for param, measure, direction, code in GATES:
        threshold = entry_rules.get(param)
        if threshold is None:
            continue
        value = candidate.evidence.get(measure)
        if value is None:
            failed.append(code + "_UNKNOWN")
            continue
        value = Decimal(str(value))
        limit = Decimal(str(threshold))
        if direction == "at_least" and value < limit:
            failed.append(code)
        elif direction == "at_most" and value > limit:
            failed.append(code)
    return failed


def entries_for(candidates: list[Candidate], entry_rules: dict[str, Any]) -> list[Candidate]:
    """First qualifying evaluation per episode, chronologically.

    An episode is one setup, seen again on every bar while it lasts. The live
    worker enters on the first bar that confirms, so a version does the same --
    and a different threshold can make a different bar the first one.
    """
    per_episode: dict[str, Candidate] = {}
    for candidate in sorted(candidates, key=lambda c: (c.decided_at, c.decision_id)):
        if candidate.episode_id in per_episode:
            continue
        if not qualifies(candidate, entry_rules):
            per_episode[candidate.episode_id] = candidate
    return sorted(per_episode.values(), key=lambda c: c.entry_at)


def simulate_trade(
    candidate: Candidate,
    candles: list[Candle],
    exit_rules: dict[str, Any],
    assumptions: Assumptions,
    risk_budget: Decimal,
    max_position_fraction: Decimal = Decimal("1"),
) -> Trade:
    """Walk one entry forward through closed candles under this exit plan."""
    slip = assumptions.slippage_bps / Decimal(10000)
    entry_px = candidate.entry_reference * (1 + slip)
    stop_px = candidate.structural_stop
    price_r = entry_px - stop_px
    fee = assumptions.taker_fee_rate
    qty_by_risk = risk_budget / price_r if price_r > 0 else Decimal(0)
    allocation = assumptions.equity_quote * max_position_fraction
    qty_by_allocation = (
        allocation / (entry_px * (Decimal(1) + fee))
        if entry_px > 0
        else Decimal(0)
    )
    qty = min(qty_by_risk, qty_by_allocation)
    trade = Trade(
        candidate=candidate,
        entry_px=entry_px,
        stop_px=stop_px,
        price_r=price_r,
        qty=qty,
        entry_fee=qty * entry_px * fee,
        fee_rate=fee,
    )
    if qty <= 0:
        trade.status = "CLOSED"
        trade.closed_at = candidate.entry_at
        return trade

    tp1_qty = qty * Decimal(str(exit_rules["tp1_fraction"]))
    tp2_qty = qty * Decimal(str(exit_rules["tp2_fraction"]))
    ladder: list[tuple[Decimal, str, Decimal]] = [
        (entry_px + price_r * Decimal(str(exit_rules["tp1_r"])), "tp1", tp1_qty),
        (entry_px + price_r * Decimal(str(exit_rules["tp2_r"])), "tp2", tp2_qty),
    ]
    breakeven_r = exit_rules.get("breakeven_r")
    breakeven_px = (
        entry_px + price_r * Decimal(str(breakeven_r)) if breakeven_r is not None else None
    )
    done: set[str] = set()
    current_stop = stop_px
    open_qty = qty
    max_bars = int(exit_rules.get("max_hold_bars") or 0)

    def close_all(reason: str, at: datetime, px: Decimal) -> None:
        nonlocal open_qty
        exit_px = px * (1 - slip)
        trade.legs.append(
            ExitLeg(reason, at, exit_px, open_qty, float((exit_px - entry_px) / price_r))
        )
        open_qty = Decimal(0)
        trade.status = "CLOSED"
        trade.closed_at = at

    for candle in candles:
        if candle.open_time < candidate.entry_at:
            continue
        trade.bars_held += 1
        closed_at = candle.open_time + timedelta(seconds=BAR_SECONDS)
        stop_touched = candle.low <= current_stop
        reachable = [step for step in ladder if step[1] not in done and candle.high >= step[0]]
        breakeven_reachable = (
            breakeven_px is not None
            and not trade.breakeven_applied
            and candle.high >= breakeven_px
        )
        if stop_touched and (reachable or breakeven_reachable):
            # Both sides of the trade were touched inside one candle; the order
            # is not in the data. Take the stop and say so.
            trade.ambiguous = True
            close_all("stop_ambiguous", closed_at, current_stop)
            break
        if stop_touched:
            close_all("stop", closed_at, current_stop)
            break
        for target_px, name, target_qty in sorted(reachable):
            fill_qty = min(target_qty, open_qty)
            if fill_qty <= 0:
                continue
            exit_px = target_px * (1 - slip)
            trade.legs.append(
                ExitLeg(name, closed_at, exit_px, fill_qty, float((exit_px - entry_px) / price_r))
            )
            open_qty -= fill_qty
            done.add(name)
        if breakeven_reachable:
            # Effective from the next candle: within this one the order of the
            # move and a pullback to it is unknowable.
            current_stop = entry_px
            trade.breakeven_applied = True
        if open_qty <= 0:
            trade.status = "CLOSED"
            trade.closed_at = closed_at
            break
        if max_bars and trade.bars_held >= max_bars:
            close_all("time", closed_at, candle.close)
            break
    return trade


def run_leg(
    candidates: list[Candidate],
    candles: dict[str, list[Candle]],
    params: dict[str, Any],
    assumptions: Assumptions,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Simulate one version end to end, with its own inventory and cash."""
    now = now or datetime.now(UTC)
    risk_budget = assumptions.equity_quote * Decimal(str(params["risk"]["risk_fraction"]))
    max_position_fraction = Decimal(
        str(params["risk"].get("max_position_fraction") or 1)
    )
    entries = entries_for(candidates, params["entry"])
    max_concurrent = int(params["risk"].get("max_concurrent_positions") or 1)

    taken: list[Trade] = []
    skipped: list[dict[str, Any]] = []
    active_until: list[datetime] = []
    for candidate in entries:
        active_until = [closed_at for closed_at in active_until
                        if candidate.entry_at < closed_at]
        if len(active_until) >= max_concurrent:
            skipped.append(
                {
                    "decision_id": candidate.decision_id,
                    "inst_id": candidate.inst_id,
                    "entry_at": candidate.entry_at,
                    "reason": "CONCURRENCY_LIMIT",
                }
            )
            continue
        trade = simulate_trade(
            candidate,
            candles.get(candidate.inst_id, []),
            params["exit"],
            assumptions,
            risk_budget,
            max_position_fraction,
        )
        taken.append(trade)
        active_until.append(
            trade.closed_at
            if trade.status == "CLOSED"
            else datetime.max.replace(tzinfo=UTC)
        )

    closed = [t for t in taken if t.status == "CLOSED"]
    still_open = [t for t in taken if t.status != "CLOSED"]
    net_quote = sum((t.net_quote for t in closed), Decimal(0))
    gross_quote = sum((t.gross_quote for t in closed), Decimal(0))
    fees_quote = sum((t.fees_quote for t in closed), Decimal(0))
    return {
        "risk_budget_quote": str(risk_budget),
        "candidates_seen": len({c.episode_id for c in candidates}),
        "entries_qualified": len(entries),
        "entries_taken": len(taken),
        "entries_skipped_busy": len(skipped),
        "skipped": skipped[:10],
        "closed_trades": len(closed),
        "open_trades": len(still_open),
        "ambiguous_trades": sum(1 for t in closed if t.ambiguous),
        "winners": sum(1 for t in closed if t.net_quote > 0),
        "losers": sum(1 for t in closed if t.net_quote < 0),
        "gross_r": round(float(gross_quote / risk_budget), 3) if risk_budget else None,
        "fees_r": round(float(fees_quote / risk_budget), 3) if risk_budget else None,
        "net_r": round(float(net_quote / risk_budget), 3) if risk_budget else None,
        "net_quote": str(net_quote.quantize(Decimal("0.0001"))),
        "trades": [t.as_dict(risk_budget) for t in taken],
        "evaluated_at": now,
    }


def summarize_backtest(result: dict[str, Any], equity_quote: Decimal) -> dict[str, Any]:
    """Presentation metrics from closed simulated trades, in close-time order."""
    closed = sorted(
        (t for t in result["trades"] if t["status"] == "CLOSED"),
        key=lambda t: t["closed_at"],
    )
    net_values = [Decimal(str(t["net_quote"])) for t in closed]
    r_values = [Decimal(str(t["net_r"])) for t in closed]
    gains = sum((v for v in net_values if v > 0), Decimal(0))
    losses = -sum((v for v in net_values if v < 0), Decimal(0))

    running = Decimal(0)
    peak = equity_quote
    max_drawdown = Decimal(0)
    curve = []
    for trade, net in zip(closed, net_values, strict=True):
        running += net
        equity = equity_quote + running
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak > 0 else Decimal(0)
        max_drawdown = max(max_drawdown, drawdown)
        curve.append({
            "time": trade["closed_at"],
            "return_pct": round(float(running / equity_quote * 100), 4)
            if equity_quote else None,
        })

    trades = len(closed)
    winners = sum(1 for value in net_values if value > 0)
    return {
        "net_return_pct": round(
            float(sum(net_values, Decimal(0)) / equity_quote * 100), 4
        ) if equity_quote else None,
        "net_r": result["net_r"],
        "closed_trades": trades,
        "open_trades": result["open_trades"],
        "win_rate_pct": round(winners / trades * 100, 1) if trades else None,
        "profit_factor": round(float(gains / losses), 2) if losses else None,
        "profit_factor_infinite": bool(gains and not losses),
        "average_trade_r": round(float(sum(r_values, Decimal(0)) / trades), 3)
        if trades else None,
        "max_drawdown_pct": round(float(max_drawdown), 4),
        "fees_quote": result["fees_r"],
        "equity_curve": curve,
    }


def verdict(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """State what the two legs show -- including that they show nothing yet."""
    closed = min(baseline["closed_trades"], variant["closed_trades"])
    net_delta = (
        round(variant["net_r"] - baseline["net_r"], 3)
        if baseline["net_r"] is not None and variant["net_r"] is not None
        else None
    )
    base_ids = {t["decision_id"] for t in baseline["trades"]}
    variant_ids = {t["decision_id"] for t in variant["trades"]}
    if closed < MIN_CLOSED_SAMPLE:
        state, headline = (
            "insufficient_evidence",
            f"Kanıt yetersiz: karşılaştırma için kapanmış gözlem sayısı {closed}, "
            f"eşik {MIN_CLOSED_SAMPLE}. Bu fark tesadüfle açıklanabilir.",
        )
    elif net_delta is None or net_delta == 0:
        state, headline = "no_difference", "İki kol bu dönemde aynı net sonucu üretti."
    else:
        direction = "daha iyi" if net_delta > 0 else "daha kötü"
        state, headline = (
            "difference_observed",
            f"Alternatif bu dönemde {abs(net_delta):.3f} R {direction}. "
            "Tek dönemlik gözlemdir; kalıcı üstünlük kanıtı değildir.",
        )
    return {
        "state": state,
        "headline": headline,
        "net_r_delta": net_delta,
        "comparable_closed": closed,
        "min_closed_sample": MIN_CLOSED_SAMPLE,
        "only_baseline_entries": sorted(base_ids - variant_ids),
        "only_variant_entries": sorted(variant_ids - base_ids),
        "shared_entries": len(base_ids & variant_ids),
        "method": "Bağımsız simüle envanter: her kol kendi pozisyonunu, nakdini ve "
        "eşzamanlılık sınırını taşır. Farklı çıkış zamanı, sonraki adaylara katılımı "
        "da değiştirir; iki kolun girişleri aynı olmak zorunda değildir.",
        "limits": [
            "Simüle sonuçtur; gerçekleşmiş fill kesinliğinde değildir ve canlı ledger ile "
            "aynı toplamda birleştirilmez.",
            "Girişler yalnız kaydı bulunan kurulum adaylarından seçilir; rejim veya pivot "
            "aşamasında elenmiş mumlar için dondurulmuş kanıt yoktur.",
            "Aynı mumda hem stop hem hedef görülen işlemler muhafazakâr biçimde stop "
            "sayılır ve belirsiz olarak işaretlenir.",
        ],
    }
