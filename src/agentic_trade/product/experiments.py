"""The experiment lab: saved rule versions and the simulated runs that compare them.

This is the only module in the product layer that writes. What it writes is
narrow by construction: strategies, strategy versions, experiment runs and the
pairs that join two runs into one comparison. It cannot reach `orders`,
`intents`, `positions` or `fills`, and it never calls the venue -- a shadow run
is a walk over candles that are already in the archive (PRODUCT.md §3, §8).

Two properties the UI depends on:

* Starting the same experiment twice returns the SAME runs. The request key is
  derived from the versions and the mode, so a double click, a retried request
  or a reload cannot open a second run.
* A run's result is a snapshot of a deterministic replay, so it can be recomputed
  on demand rather than needing a ticking process. `evaluate` refreshes it when
  it is stale and persists what it found, which is also the run's heartbeat.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from ..db import pool
from . import templates
from .simulate import (
    Assumptions,
    Candidate,
    Candle,
    run_leg,
    summarize_backtest,
    verdict,
)
from .templates import DraftRejected

log = structlog.get_logger(__name__)

VENUE = "okx-tr"
SETUP_BAR = "5m"
# Stages whose decision record carries the frozen setup evidence a re-judgement
# needs. Earlier stages (regime, no pivot) recorded no level or stop.
EVIDENCE_STAGES = ("SETUP_FORMED", "CONFIRM_REJECTED", "EXTENSION_REJECTED", "CONFIRMED")
# How long an evaluation snapshot is served before it is recomputed. The
# dashboard polls every few seconds; the underlying candles close every 5m.
RESULT_TTL_S = 20
REPLAY_WINDOW_H = 48


def unpack(value: Any) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def _json(value: Any) -> str:
    def default(v: Any) -> Any:
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, datetime):
            return v.astimezone(UTC).isoformat()
        return str(v)

    return json.dumps(value, default=default, ensure_ascii=False)


# --- versions ----------------------------------------------------------------


async def ensure_baseline() -> dict[str, Any]:
    """The trader's current rules, saved as an immutable baseline version.

    Idempotent: the first call writes it, later calls read it back. The params
    come from the code the live worker is running, so the baseline leg of every
    experiment is the strategy as it actually stands today.
    """
    params = templates.baseline_params()
    async with pool.product().acquire() as con:
        async with con.transaction():
            strategy_id = await con.fetchval(
                """INSERT INTO strategies (slug, name, idea)
                   VALUES ('reclaim', 'Reclaim · başlangıç stratejisi',
                           'Yükseliş bağlamında geri çekilme sonrası seviyeyi geri kazanan '
                           'kapanışı hacim ve alıcı baskısıyla doğrula.')
                   ON CONFLICT (slug) DO UPDATE SET slug=EXCLUDED.slug
                   RETURNING strategy_id"""
            )
            row = await con.fetchrow(
                """SELECT * FROM strategy_versions
                   WHERE strategy_id=$1 AND is_baseline AND label=$2
                   ORDER BY version_id LIMIT 1""",
                strategy_id,
                templates.BASELINE_LABEL,
            )
            if row is None:
                row = await con.fetchrow(
                    """INSERT INTO strategy_versions
                       (strategy_id, label, template, params, is_baseline, change_note)
                       VALUES ($1,$2,$3,$4,TRUE,
                               'Canlı worker''ın bugün çalıştırdığı kurallar.')
                       RETURNING *""",
                    strategy_id,
                    templates.BASELINE_LABEL,
                    templates.TEMPLATE,
                    _json(params),
                )
    return version_dict(row)


def version_dict(row: Any) -> dict[str, Any]:
    params = unpack(row["params"])
    return {
        "version_id": row["version_id"],
        "parent_version_id": row["parent_version_id"],
        "label": row["label"],
        "template": row["template"],
        "params": params,
        "rules": templates.describe(params),
        "changed_field": row["changed_field"],
        "changed_from": row["changed_from"],
        "changed_to": row["changed_to"],
        "change_note": row["change_note"],
        "is_baseline": row["is_baseline"],
        "created_at": row["created_at"],
    }


async def create_draft(
    parent_version_id: int, key: str, value: Any, note: str = ""
) -> dict[str, Any]:
    """Clone a saved version with exactly one catalogued rule changed.

    The parent row is never touched, so a run already pointing at it keeps the
    rules it was measured under. Saving a draft starts nothing.
    """
    async with pool.product().acquire() as con:
        parent = await con.fetchrow(
            "SELECT * FROM strategy_versions WHERE version_id=$1", parent_version_id
        )
        if parent is None:
            raise DraftRejected("Kaynak strateji sürümü bulunamadı.")
        parent_params = unpack(parent["params"])
        params, coerced = templates.apply_change(parent_params, key, value)
        field = templates.BY_KEY[key]
        before = templates.format_value(field, templates.get_value(parent_params, key))
        after = templates.format_value(field, coerced)
        base_label = f"{field.label.lower()} · {after}"
        async with con.transaction():
            label = base_label
            for attempt in range(2, 12):
                exists = await con.fetchval(
                    "SELECT 1 FROM strategy_versions WHERE strategy_id=$1 AND label=$2",
                    parent["strategy_id"],
                    label,
                )
                if not exists:
                    break
                label = f"{base_label} ({attempt})"
            row = await con.fetchrow(
                """INSERT INTO strategy_versions
                   (strategy_id, parent_version_id, label, template, params,
                    changed_field, changed_from, changed_to, change_note)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
                parent["strategy_id"],
                parent["version_id"],
                label,
                parent["template"],
                _json(params),
                key,
                before,
                after,
                note[:280],
            )
    draft = version_dict(row)
    draft["diff"] = templates.diff(parent_params, params)
    return draft


# --- runs --------------------------------------------------------------------


def _assumptions() -> Assumptions:
    return Assumptions()


async def start_experiment(version_id: int, mode: str) -> dict[str, Any]:
    """Open (or return) one experiment: a baseline leg and a variant leg.

    Both legs are simulated over the same window with the same assumptions. The
    variant is never compared against the live ledger -- a simulated leg and a
    real one do not carry the same certainty (PRODUCT.md §8).
    """
    if mode not in ("SHADOW", "REPLAY"):
        raise DraftRejected("Çalışma modu SHADOW veya REPLAY olmalı.")
    now = datetime.now(UTC)
    async with pool.product().acquire() as con:
        variant = await con.fetchrow(
            "SELECT * FROM strategy_versions WHERE version_id=$1", version_id
        )
        if variant is None:
            raise DraftRejected("Strateji sürümü bulunamadı.")
        if variant["is_baseline"]:
            raise DraftRejected(
                "Deney için önce başlangıç stratejisini kopyalayıp bir kuralı değiştir."
            )
        baseline = await con.fetchrow(
            """SELECT * FROM strategy_versions
               WHERE strategy_id=$1 AND is_baseline AND label=$2
               ORDER BY version_id LIMIT 1""",
            variant["strategy_id"],
            templates.BASELINE_LABEL,
        )
        if baseline is None:
            raise DraftRejected("Başlangıç sürümü kayıtlı değil.")

        key = f"exp:{baseline['version_id']}:{version_id}:{mode}"
        window_from = now if mode == "SHADOW" else now - timedelta(hours=REPLAY_WINDOW_H)
        window_to = None if mode == "SHADOW" else now
        assumptions = _assumptions().as_dict()

        async with con.transaction():
            existing = await con.fetchrow(
                """SELECT e.*, b.window_from, b.window_to FROM experiments e
                   JOIN experiment_runs b ON b.exp_run_id=e.baseline_run_id
                   WHERE b.request_key=$1""",
                f"{key}:baseline",
            )
            if existing:
                return {"experiment_id": existing["experiment_id"], "created": False}
            baseline_run = await _open_run(
                con, baseline["version_id"], mode, f"{key}:baseline",
                window_from, window_to, assumptions,
            )
            variant_run = await _open_run(
                con, version_id, mode, f"{key}:variant",
                window_from, window_to, assumptions,
            )
            field = templates.BY_KEY.get(variant["changed_field"] or "")
            experiment_id = await con.fetchval(
                """INSERT INTO experiments
                   (title, baseline_run_id, variant_run_id, changed_field, method)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (baseline_run_id, variant_run_id) DO UPDATE SET title=EXCLUDED.title
                   RETURNING experiment_id""",
                f"{field.label if field else 'Kural'}: {variant['changed_from']} → "
                f"{variant['changed_to']}",
                baseline_run,
                variant_run,
                variant["changed_field"] or "",
                "independent_simulated_runs",
            )
    log.info("experiment_started", experiment_id=experiment_id, mode=mode, version_id=version_id)
    return {"experiment_id": experiment_id, "created": True}


async def _open_run(
    con: Any,
    version_id: int,
    mode: str,
    request_key: str,
    window_from: datetime,
    window_to: datetime | None,
    assumptions: dict[str, Any],
) -> int:
    """Insert a run, or return the one this request key already opened."""
    run_id = await con.fetchval(
        """INSERT INTO experiment_runs
           (version_id, mode, status, request_key, window_from, window_to, assumptions)
           VALUES ($1,$2,'RUNNING',$3,$4,$5,$6)
           ON CONFLICT (request_key) DO NOTHING RETURNING exp_run_id""",
        version_id, mode, request_key, window_from, window_to, _json(assumptions),
    )
    if run_id is None:
        run_id = await con.fetchval(
            "SELECT exp_run_id FROM experiment_runs WHERE request_key=$1", request_key
        )
    return run_id


async def stop_run(exp_run_id: int) -> dict[str, Any]:
    """End a shadow observation. It stops taking new candidates; nothing is closed
    at a venue, because nothing was ever opened at one."""
    now = datetime.now(UTC)
    async with pool.product().acquire() as con:
        row = await con.fetchrow(
            """UPDATE experiment_runs SET status='STOPPED', stopped_at=$2,
               window_to=coalesce(window_to,$2)
               WHERE exp_run_id=$1 AND status='RUNNING' RETURNING exp_run_id""",
            exp_run_id, now,
        )
    return {"stopped": bool(row), "exp_run_id": exp_run_id}


# --- evaluation ---------------------------------------------------------------


async def load_candidates(window_from: datetime, window_to: datetime | None) -> list[Candidate]:
    """Recorded setup candidates in the window, with their frozen evidence."""
    async with pool.ledger().acquire() as con:
        async with con.transaction(readonly=True):
            rows = await con.fetch(
                """SELECT d.decision_id, d.run_id, d.inst_id, d.episode_id, d.decided_at,
                          d.candle_open_time, d.features
                   FROM decisions d JOIN runs r USING (run_id)
                   WHERE r.code_version IS NOT NULL AND r.mode IN ('live','observe')
                     AND d.episode_id IS NOT NULL AND d.candle_open_time IS NOT NULL
                     AND d.stage_reached = ANY($3::text[])
                     AND d.decided_at >= $1
                     AND ($2::timestamptz IS NULL OR d.decided_at <= $2)
                   ORDER BY d.decided_at""",
                window_from, window_to, list(EVIDENCE_STAGES),
            )
    out: list[Candidate] = []
    for row in rows:
        features = unpack(row["features"])
        # Older records stored the setup evidence flat; newer ones nest it.
        evidence = features.get("setup") or features
        level, stop, trigger = (
            evidence.get("level"),
            evidence.get("pullback_low"),
            evidence.get("trigger_close"),
        )
        if not (level and stop and trigger):
            continue
        try:
            entry_px, stop_px = Decimal(str(trigger)), Decimal(str(stop))
        except (ArithmeticError, ValueError):
            continue
        if entry_px <= stop_px:
            continue
        out.append(
            Candidate(
                decision_id=row["decision_id"],
                run_id=row["run_id"],
                inst_id=row["inst_id"],
                episode_id=row["episode_id"],
                decided_at=row["decided_at"],
                candle_open_time=row["candle_open_time"],
                entry_reference=entry_px,
                structural_stop=stop_px,
                evidence={
                    "rvol": evidence.get("rvol"),
                    "flow_imbalance": evidence.get("flow_imbalance"),
                    "close_position": evidence.get("close_position"),
                    "pullback_depth_atr": evidence.get("pullback_depth_atr"),
                    "extension_atr": evidence.get("extension_atr"),
                    "stop_distance_atr": evidence.get("stop_distance_atr"),
                },
            )
        )
    return out


async def load_candles(inst_ids: list[str], since: datetime) -> dict[str, list[Candle]]:
    if not inst_ids:
        return {}
    async with pool.market().acquire() as con:
        async with con.transaction(readonly=True):
            rows = await con.fetch(
                """SELECT inst_id, open_time, open, high, low, close FROM candles
                   WHERE venue=$1 AND bar=$2 AND confirm AND inst_id = ANY($3::text[])
                     AND open_time >= $4 ORDER BY inst_id, open_time""",
                VENUE, SETUP_BAR, inst_ids, since,
            )
    out: dict[str, list[Candle]] = {}
    for row in rows:
        out.setdefault(row["inst_id"], []).append(
            Candle(row["open_time"], row["open"], row["high"], row["low"], row["close"])
        )
    return out


async def backtest(hours: int = REPLAY_WINDOW_H) -> dict[str, Any]:
    """Evaluate the current live profile over the recorded candidate archive."""
    now = datetime.now(UTC)
    window_from = now - timedelta(hours=hours)
    params = templates.baseline_params()
    assumptions = _assumptions()
    candidates = await load_candidates(window_from, now)
    inst_ids = sorted({candidate.inst_id for candidate in candidates})
    candles = await load_candles(inst_ids, window_from - timedelta(hours=1))
    result = run_leg(candidates, candles, params, assumptions, now=now)
    return {
        "generated_at": now,
        "policy_version": templates.BASELINE_LABEL,
        "window": {"from": window_from, "to": now, "hours": hours},
        "assumptions": assumptions.as_dict(),
        "metrics": summarize_backtest(result, assumptions.equity_quote),
        "result": result,
        "coverage": {
            "candidate_episodes": len({candidate.episode_id for candidate in candidates}),
            "instruments": inst_ids,
            "candles": sum(len(rows) for rows in candles.values()),
        },
        "limits": [
            "Sonuç simülasyondur; canlı fill değildir.",
            "Yalnız worker'ın o anda kaydettiği setup adayları yeniden değerlendirilir; "
            "aday aşamasına hiç ulaşmayan tarihsel mumlar kapsama girmez.",
            "Çıkış sırası 5 dakikalık mum içinde bilinmiyorsa stop varsayılır.",
        ],
    }


async def evaluate(exp_run_id: int, *, force: bool = False) -> dict[str, Any]:
    """Recompute a run's result if the snapshot is stale, and persist it."""
    now = datetime.now(UTC)
    async with pool.product().acquire() as con:
        row = await con.fetchrow(
            """SELECT r.*, v.params, v.label, v.changed_field, v.is_baseline
               FROM experiment_runs r JOIN strategy_versions v USING (version_id)
               WHERE r.exp_run_id=$1""",
            exp_run_id,
        )
    if row is None:
        raise DraftRejected("Çalışma bulunamadı.")
    fresh = (
        row["result"] is not None
        and row["last_evaluated_at"] is not None
        and (now - row["last_evaluated_at"]).total_seconds() < RESULT_TTL_S
    )
    if fresh and not force:
        return run_dict(row, unpack(row["result"]))

    params = unpack(row["params"])
    stored = unpack(row["assumptions"])
    assumptions = Assumptions(
        taker_fee_rate=Decimal(stored.get("taker_fee_rate", "0.001")),
        slippage_bps=Decimal(stored.get("slippage_bps", "0")),
        equity_quote=Decimal(stored.get("equity_quote", "1000")),
        bar=stored.get("bar", SETUP_BAR),
    )
    window_to = row["window_to"]
    candidates = await load_candidates(row["window_from"], window_to)
    candles = await load_candles(
        sorted({c.inst_id for c in candidates}), row["window_from"] - timedelta(hours=1)
    )
    result = run_leg(candidates, candles, params, assumptions, now=now)
    result["window"] = {"from": row["window_from"], "to": window_to}
    result["candle_coverage"] = {
        inst: {"bars": len(bars), "last_open_time": bars[-1].open_time if bars else None}
        for inst, bars in candles.items()
    }
    async with pool.product().acquire() as con:
        await con.execute(
            "UPDATE experiment_runs SET result=$2, last_evaluated_at=$3 WHERE exp_run_id=$1",
            exp_run_id, _json(result), now,
        )
    return run_dict(row, result)


def run_dict(row: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "exp_run_id": row["exp_run_id"],
        "version_id": row["version_id"],
        "version_label": row["label"],
        "is_baseline": row["is_baseline"],
        "mode": row["mode"],
        "status": row["status"],
        "window_from": row["window_from"],
        "window_to": row["window_to"],
        "assumptions": unpack(row["assumptions"]),
        "created_at": row["created_at"],
        "last_evaluated_at": row["last_evaluated_at"],
        "stopped_at": row["stopped_at"],
        "result": result,
    }


async def experiment_status(experiment_id: int, *, force: bool = False) -> dict[str, Any]:
    async with pool.product().acquire() as con:
        row = await con.fetchrow(
            "SELECT * FROM experiments WHERE experiment_id=$1", experiment_id
        )
    if row is None:
        raise DraftRejected("Deney bulunamadı.")
    baseline = await evaluate(row["baseline_run_id"], force=force)
    variant = await evaluate(row["variant_run_id"], force=force)
    return {
        "experiment_id": row["experiment_id"],
        "title": row["title"],
        "changed_field": row["changed_field"],
        "method": row["method"],
        "created_at": row["created_at"],
        "mode": baseline["mode"],
        "baseline": baseline,
        "variant": variant,
        "comparison": verdict(baseline["result"], variant["result"]),
    }


# --- read surface -------------------------------------------------------------


async def overview() -> dict[str, Any]:
    """Everything the Experiments screen renders: versions, drafts, experiments."""
    baseline = await ensure_baseline()
    async with pool.product().acquire() as con:
        versions = await con.fetch(
            """SELECT v.* FROM strategy_versions v
               WHERE v.strategy_id=(SELECT strategy_id FROM strategies WHERE slug='reclaim')
                 AND (v.version_id=$1 OR v.parent_version_id=$1)
               ORDER BY v.version_id DESC LIMIT 20""",
            baseline["version_id"],
        )
        experiments = await con.fetch(
            """SELECT e.*, b.mode, b.status baseline_status, b.last_evaluated_at,
                      vb.label baseline_label, vv.label variant_label,
                      b.exp_run_id baseline_run, v2.exp_run_id variant_run,
                      v2.status variant_status
               FROM experiments e
               JOIN experiment_runs b ON b.exp_run_id=e.baseline_run_id
               JOIN experiment_runs v2 ON v2.exp_run_id=e.variant_run_id
               JOIN strategy_versions vb ON vb.version_id=b.version_id
               JOIN strategy_versions vv ON vv.version_id=v2.version_id
               ORDER BY e.experiment_id DESC LIMIT 10"""
        )
    drafts = []
    for row in versions:
        version = version_dict(row)
        if not version["is_baseline"]:
            version["diff"] = templates.diff(baseline["params"], version["params"])
        drafts.append(version)
    return {
        "as_of": datetime.now(UTC),
        "baseline": baseline,
        "versions": drafts,
        "catalogue": templates.catalogue(baseline["params"]),
        "experiments": [
            {
                "experiment_id": e["experiment_id"],
                "title": e["title"],
                "changed_field": e["changed_field"],
                "mode": e["mode"],
                "created_at": e["created_at"],
                "last_evaluated_at": e["last_evaluated_at"],
                "baseline_run_id": e["baseline_run"],
                "variant_run_id": e["variant_run"],
                "baseline_label": e["baseline_label"],
                "variant_label": e["variant_label"],
                "baseline_status": e["baseline_status"],
                "variant_status": e["variant_status"],
            }
            for e in experiments
        ],
        "assumptions": _assumptions().as_dict(),
        "limits": [
            "Gölge ve replay çalışmaları simülasyondur: borsaya emir gönderilmez, "
            "canlı bakiye kullanılmaz.",
            "Girişler worker'ın kaydettiği kurulum adaylarından yeniden değerlendirilir.",
            "Sonuçlar canlı ledger sonuçlarıyla aynı toplamda birleştirilmez.",
        ],
    }
