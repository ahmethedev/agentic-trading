"""Observe-mode worker: ingest market data, evaluate setups, record decisions.

This is the Gate 1 loop (AGENT.md §11): see correctly, record everything, and
explain every WAIT. It places no orders -- MODE=observe is enforced here, and
the execution path is a separate, later component.

Every evaluation is persisted, including rejections, so the funnel
(scanned -> regime -> setup -> confirmation -> risk) is reconstructable from the
database alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
from decimal import Decimal

import structlog

from .atk.client import AtkClient, AtkError, AtkTimeout
from .config import Settings, get_settings
from .db import pool
from .execution.order_manager import OrderManager, ReservationDenied
from .execution.position import open_position
from .execution.reconcile import Reconciler
from .execution.venue import AtkVenue, PaperVenue, Venue
from .features.compute import compute_snapshot, load_closed_candles
from .ingest.market import VENUE, MarketIngestor
from .risk import gate
from .risk.sizing import InstrumentSpec, RiskRejection, SizingInput, compute_size
from .strategy.setup import SetupParams, Stage, detect

log = structlog.get_logger(__name__)

POLICY_VERSION = "retail_baseline_v1"
DEFAULT_INSTRUMENTS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
# Fallback fee used only while unauthenticated. The real account fee comes from
# account_get_trade_fee and must replace this before any live sizing.
ASSUMED_TAKER_FEE = Decimal("0.001")
# How far through the book a marketable-limit entry may reach. This is also the
# WORST price we can pay, so it -- not the expected price -- is what we size
# against: otherwise a fill at the limit puts realised risk above the budget.
ENTRY_SLIPPAGE_CAP = Decimal("0.001")


class Worker:
    def __init__(self, settings: Settings, instruments: list[str] | None = None) -> None:
        self._s = settings
        self._instruments = instruments or DEFAULT_INSTRUMENTS
        self._atk: AtkClient | None = None
        self._run_id: int | None = None
        self._stop = asyncio.Event()
        self._specs: dict[str, InstrumentSpec] = {}
        self._taker_fee = ASSUMED_TAKER_FEE
        self._fee_is_real = False
        self._equity = Decimal("1000")   # placeholder until account access exists
        self._equity_is_real = False
        self._venue: Venue | None = None
        self._om: OrderManager | None = None
        # Set only once startup reconciliation agrees the ledger with the venue.
        self._reconciled = False
        # One worker owns the order path; this serialises entry attempts.
        self._trade_lock = asyncio.Lock()

    # ------------------------------------------------------------- startup --
    async def start(self) -> None:
        s = self._s
        await pool.init_pools(s.database_url)
        self._atk = AtkClient(
            s.atk_dir, s.atk_env(), timeout_s=s.atk_timeout_s, modules=s.atk_modules()
        )
        await self._atk.start()

        async with pool.ledger().acquire() as con:
            self._run_id = await con.fetchval(
                """INSERT INTO runs (mode, site, demo, policy_version, code_version, notes)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING run_id""",
                s.mode, s.okx_site, s.okx_demo, POLICY_VERSION, "0.1.0",
                json.dumps({"instruments": self._instruments,
                            "authenticated": s.has_credentials,
                            "max_entries_per_run": s.max_entries_per_run,
                            "entry_instruments":
                                sorted(s.armed_instruments)
                                if s.armed_instruments else None}),
            )
        log.info("worker.run_started", run_id=self._run_id, mode=s.mode,
                 authenticated=s.has_credentials, instruments=self._instruments,
                 entry_budget=s.max_entries_per_run or "unlimited",
                 armed=sorted(s.armed_instruments) if s.armed_instruments else "all")

        await self._load_instrument_specs()
        await self._load_account_context()

        # Paper mode exercises the identical state machine against a simulated
        # venue, so the order path is proven before real money is involved.
        if s.mode == "live":
            self._venue = AtkVenue(self._atk)
        else:
            self._venue = PaperVenue(fee_rate=self._taker_fee)
        self._om = OrderManager(self._venue, self._run_id)

        # Reconcile before anything can trade. In observe mode we still run it,
        # so the dashboard shows the true state, but nothing would trade anyway.
        report = await Reconciler(self._venue, self._om, self._run_id).run()
        self._reconciled = report.is_clean
        if not report.is_clean:
            log.error("worker.reconcile_unclean", unresolved=report.unresolved,
                      detail="new entries are blocked until this is resolved")
        elif report.unprotected_positions:
            log.error("worker.unprotected_positions",
                      positions=report.unprotected_positions)

    async def _load_instrument_specs(self) -> None:
        """Lot/tick/min come from the venue, never from hardcoded constants."""
        assert self._atk
        payload = await self._atk.call("market_get_instruments", {"instType": "SPOT"})
        rows = payload["data"]["data"]
        wanted = set(self._instruments)
        records = []
        for r in rows:
            if r["instId"] not in wanted:
                continue
            spec = InstrumentSpec(
                inst_id=r["instId"], lot_sz=Decimal(r["lotSz"]),
                min_sz=Decimal(r["minSz"]), tick_sz=Decimal(r["tickSz"]),
            )
            self._specs[r["instId"]] = spec
            records.append((VENUE, r["instId"], r["baseCcy"], r["quoteCcy"],
                            spec.tick_sz, spec.lot_sz, spec.min_sz, r["state"]))
        if records:
            async with pool.ledger().acquire() as con:
                await con.executemany(
                    """INSERT INTO instruments (venue, inst_id, base_ccy, quote_ccy,
                           tick_sz, lot_sz, min_sz, state)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                       ON CONFLICT (venue, inst_id) DO UPDATE SET
                           tick_sz=EXCLUDED.tick_sz, lot_sz=EXCLUDED.lot_sz,
                           min_sz=EXCLUDED.min_sz, state=EXCLUDED.state,
                           updated_at=now()""",
                    records,
                )
        missing = wanted - set(self._specs)
        if missing:
            log.warning("worker.instruments_missing", missing=sorted(missing))
        log.info("worker.specs_loaded", count=len(self._specs))

    async def _load_account_context(self) -> None:
        """Real equity and fee rate, when credentials allow it."""
        assert self._atk
        if not self._s.has_credentials:
            await self._ops("warn", "no_credentials", detail={
                "missing": self._s.missing_credentials(),
                "impact": "equity and fee are placeholders; sizing is indicative only",
            })
            log.warning("worker.unauthenticated",
                        missing=self._s.missing_credentials())
            return
        try:
            bal = await self._atk.call("account_get_balance",
                                       {"ccy": self._s.quote_ccy})
            account = bal["data"]["data"][0]
            details = account.get("details") or []
            # A successful balance read is authoritative even when it reports
            # nothing: an authenticated but unfunded account must NOT silently
            # fall back to the placeholder equity and size against money that
            # does not exist. Absent currency detail means zero.
            self._equity = Decimal("0")
            self._equity_is_real = True
            for d in details:
                if d["ccy"] == self._s.quote_ccy:
                    self._equity = Decimal(d["eq"])
            if self._equity <= 0:
                await self._ops("warn", "account_unfunded", detail={
                    "quote_ccy": self._s.quote_ccy,
                    "total_eq": account.get("totalEq"),
                    "impact": "no entry can be sized until the account is funded",
                })
                log.warning("worker.account_unfunded",
                            quote_ccy=self._s.quote_ccy,
                            total_eq=account.get("totalEq"))
            fee = await self._atk.call("account_get_trade_fee",
                                       {"instType": "SPOT"})
            taker = fee["data"]["data"][0]["taker"]
            # OKX returns fee rates as negative strings (a cost).
            self._taker_fee = abs(Decimal(taker))
            self._fee_is_real = True
            log.info("worker.account_loaded", equity=str(self._equity),
                     taker_fee=str(self._taker_fee))
        except (AtkError, AtkTimeout, KeyError, IndexError) as exc:
            await self._ops("error", "account_load_failed",
                            detail={"error": str(exc)[:300]})
            log.error("worker.account_load_failed", err=str(exc)[:200])

    # ------------------------------------------------------------ decisions --
    async def evaluate(self, inst_id: str) -> None:
        """One evaluation pass for one instrument; always writes a decision row."""
        feats = await compute_snapshot(inst_id)
        candles = await load_closed_candles(inst_id, "5m", limit=60)
        result = detect(inst_id, candles, feats, SetupParams())

        action = "WAIT"
        reason_codes = list(result.reason_codes)
        sizing_note: dict[str, object] = {}

        if result.stage is Stage.CONFIRMED:
            action, extra_codes, sizing_note = await self._handle_candidate(
                inst_id, result
            )
            reason_codes.extend(extra_codes)

        await self._write_decision(inst_id, feats, result, action, reason_codes,
                                   sizing_note)

    async def _handle_candidate(
        self, inst_id: str, result
    ) -> tuple[str, list[str], dict[str, object]]:
        """Gate -> size -> reserve -> enter -> protect, for a confirmed setup."""
        codes: list[str] = []
        note: dict[str, object] = {}

        spec = self._specs.get(inst_id)
        if spec is None:
            return "WAIT", ["NO_INSTRUMENT_SPEC"], note

        gate_result = await gate.evaluate(
            inst_id, mode=self._s.mode, equity=self._equity,
            equity_is_real=self._equity_is_real, run_id=self._run_id,
            reconciled=self._reconciled,
            limits=gate.GateLimits(
                max_concurrent_positions=self._s.max_concurrent_positions,
                max_entries_per_run=self._s.max_entries_per_run,
                armed_instruments=self._s.armed_instruments),
        )
        note["gate"] = gate_result.detail

        # Size against the worst price we are willing to pay, so that a fill at
        # the limit still lands inside the risk budget rather than 8% above it.
        px_limit = self._entry_limit(result.trigger_close)
        note["entry_limit"] = str(px_limit)

        # Size regardless, so the decision card shows what WOULD have been taken.
        try:
            sized = compute_size(SizingInput(
                equity_quote=self._equity, available_quote=self._equity,
                entry_reference=px_limit,
                structural_stop=result.structural_stop,
                risk_fraction=self._s.risk_fraction,
                risk_fraction_max=self._s.risk_fraction_max,
                taker_fee_rate=self._taker_fee, spec=spec,
            ))
            note["sizing"] = {
                "quantity": str(sized.quantity), "notional": str(sized.notional),
                "risk_budget": str(sized.risk_budget),
                "risk_at_stop": str(sized.risk_at_stop),
                "price_r_distance": str(sized.price_r_distance),
                "capped_by": sized.capped_by,
                "equity_is_real": self._equity_is_real,
                "fee_is_real": self._fee_is_real,
            }
        except RiskRejection as rej:
            note["sizing"] = {"rejected": rej.code, "detail": rej.detail}
            return "WAIT", [rej.code], note

        if not gate_result.allowed:
            return "WAIT", gate_result.codes, note

        # Past this point an order will actually be sent.
        async with self._trade_lock:
            try:
                outcome, position = await self._enter(
                    inst_id, result, sized, spec, px_limit
                )
            except ReservationDenied as rej:
                return "WAIT", [rej.code], note

        note["execution"] = {
            "client_order_id": outcome.client_order_id,
            "status": str(outcome.status),
            "qty_filled": str(outcome.qty_filled),
            "avg_px": str(outcome.avg_px) if outcome.avg_px else None,
            "unknown": outcome.unknown,
            "position_id": position.position_id if position else None,
            "protected": bool(position and position.algo_id),
        }
        if outcome.qty_filled > 0:
            return "BUY_INTENT", ["ENTRY_FILLED"], note
        codes.append("ENTRY_NOT_FILLED")
        return "WAIT", codes, note

    @staticmethod
    def _entry_limit(reference: Decimal) -> Decimal:
        return reference * (Decimal(1) + ENTRY_SLIPPAGE_CAP)

    async def _enter(self, inst_id: str, result, sized, spec, px_limit: Decimal):
        """Reserve, send the entry, and attach protection to what actually filled."""
        assert self._om and self._venue and self._run_id
        decision_id = await self._pending_decision_id(inst_id, result)

        intent_id = await self._om.reserve(
            decision_id=decision_id, inst_id=inst_id, side="buy",
            equity_at_decision=self._equity,
            risk_fraction=self._s.risk_fraction,
            risk_budget=sized.risk_budget,
            entry_reference=px_limit,
            structural_stop=result.structural_stop,
            price_r_distance=sized.price_r_distance,
            qty=sized.quantity, est_cost_per_unit=sized.est_cost_per_unit,
            policy_version=POLICY_VERSION,
            max_concurrent=self._s.max_concurrent_positions,
            max_entries_per_run=self._s.max_entries_per_run,
        )

        outcome = await self._om.submit_entry(
            intent_id, inst_id, sized.quantity, px_limit)

        if outcome.qty_filled <= 0 or outcome.unknown:
            return outcome, None

        qty, avg_px, fees = await self._om.filled_totals(outcome.client_order_id)
        position = await open_position(
            self._venue, run_id=self._run_id, intent_id=intent_id,
            inst_id=inst_id, filled_qty=qty, avg_entry_px=avg_px,
            structural_stop=result.structural_stop, spec=spec,
            est_cost_per_unit=sized.est_cost_per_unit,
            policy_version=POLICY_VERSION, fees_paid=fees,
        )
        return outcome, position

    async def _pending_decision_id(self, inst_id: str, result) -> int:
        """Persist the decision that authorises this entry, and return its id."""
        async with pool.ledger().acquire() as con:
            return await con.fetchval(
                """INSERT INTO decisions (run_id, inst_id, episode_id, action,
                       setup_id, reason_codes, stage_reached, features,
                       policy_version, data_quality)
                   VALUES ($1,$2,$3,'BUY_INTENT','reclaim_v1',
                           ARRAY['RECLAIM_CONFIRMED'],'CONFIRMED',$4,$5,'{}')
                   RETURNING decision_id""",
                self._run_id, inst_id, result.episode_id,
                json.dumps(result.evidence or {}), POLICY_VERSION,
            )

    async def _write_decision(self, inst_id, feats, result, action, reason_codes,
                              sizing_note) -> None:
        features_json = {
            "close": str(feats.close) if feats.close is not None else None,
            "close_position": feats.close_position,
            "rvol": feats.rvol,
            "atr": str(feats.atr) if feats.atr is not None else None,
            "above_ma": feats.above_ma,
            "trend_slope_atr": feats.trend_slope_atr,
            "flow_imbalance": feats.flow.imbalance if feats.flow else None,
            "flow_valid": feats.flow.valid if feats.flow else None,
            "flow_trades": feats.flow.trade_count if feats.flow else None,
            "setup": result.evidence or {},
            "sizing": sizing_note,
        }
        data_quality = {
            "data_age_s": feats.data_age_s,
            "invalid_codes": feats.invalid_codes,
            "invalid_reasons": feats.invalid_reasons,
            "flow_coverage_s": feats.flow.coverage_s if feats.flow else None,
            "flow_reason": feats.flow.reason if feats.flow else None,
        }
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO decisions (run_id, inst_id, candle_open_time, episode_id,
                       action, setup_id, reason_codes, stage_reached, features,
                       policy_version, data_quality)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                self._run_id, inst_id, feats.candle_open_time, result.episode_id,
                action, "reclaim_v1" if result.is_candidate else None,
                reason_codes, str(result.stage), json.dumps(features_json),
                POLICY_VERSION, json.dumps(data_quality),
            )
        log.info("decision", inst=inst_id, action=action, stage=str(result.stage),
                 codes=reason_codes[:3])

    async def _ops(self, severity: str, kind: str, *, inst_id: str | None = None,
                   detail: dict | None = None) -> None:
        async with pool.ledger().acquire() as con:
            await con.execute(
                """INSERT INTO ops_events (run_id, severity, kind, inst_id, detail)
                   VALUES ($1,$2,$3,$4,$5)""",
                self._run_id, severity, kind, inst_id, json.dumps(detail or {}),
            )

    # ----------------------------------------------------------------- loop --
    async def run(self, decide_interval_s: float = 30.0) -> None:
        assert self._atk and self._run_id
        ingestor = MarketIngestor(self._atk, self._run_id, self._instruments)
        ingest_task = asyncio.create_task(ingestor.run(stop=self._stop))
        decide_task = asyncio.create_task(self._decide_loop(decide_interval_s))
        await self._stop.wait()
        for t in (ingest_task, decide_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t

    async def _decide_loop(self, interval: float) -> None:
        # Let the first ingest pass populate the flow window before deciding.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=20)
        while not self._stop.is_set():
            for inst in self._instruments:
                try:
                    await self.evaluate(inst)
                except Exception as exc:  # noqa: BLE001
                    log.exception("worker.evaluate_failed", inst=inst,
                                  err=str(exc)[:200])
                    await self._ops("error", "evaluate_failed", inst_id=inst,
                                    detail={"error": str(exc)[:300]})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)

    async def shutdown(self) -> None:
        self._stop.set()
        if self._run_id:
            async with pool.ledger().acquire() as con:
                await con.execute(
                    "UPDATE runs SET stopped_at = now() WHERE run_id = $1", self._run_id
                )
        if self._atk:
            await self._atk.stop()
        await pool.close_pools()
        log.info("worker.stopped", run_id=self._run_id)


async def main() -> None:
    settings = get_settings()
    worker = Worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker._stop.set)
    await worker.start()
    try:
        await worker.run()
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
    asyncio.run(main())
