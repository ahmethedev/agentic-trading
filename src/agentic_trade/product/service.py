"""Bounded, run-scoped evidence for ThatsMyQuant's first product slice.

All data comes from the existing store. No model invents risk or trade history.
The first question interface is explicitly a limited deterministic reader, not
an LLM integration. A future harness can call these same service functions.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..db import pool
from ..strategy.setup import SetupParams

REASONS = {
    "NO_RECLAIM_CLOSE": "Seviye üzerinde kapanış bekleniyor",
    "NO_PIVOT_LEVEL": "Onaylanmış referans seviye yok",
    "REGIME_BELOW_MA": "Fiyat bağlam ortalamasının altında",
    "REGIME_SLOPE_WEAK": "Trend eğimi yeterli değil",
    "RVOL_TOO_LOW": "Göreli hacim onayı yetersiz",
    "FLOW_NOT_BUY_DOMINANT": "Alıcı baskısı onayı yetersiz",
    "FLOW_INVALID": "Akış verisi güvenilir ölçüm için yetersiz",
    "WEAK_CLOSE_POSITION": "Mum üst yarıda kapanmadı",
    "TOO_EXTENDED": "Fiyat giriş seviyesinden fazla uzaklaştı",
    "STOP_TOO_TIGHT": "Yapısal stop mesafesi çok dar",
    "RECLAIM_CONFIRMED": "Kurulum onaylandı",
    "CONCURRENCY_LIMIT": "Açık pozisyon veya bekleyen giriş limiti dolu",
    "ENTRY_BUDGET_EXHAUSTED": "Bu çalışmanın giriş hakkı kullanıldı",
    "INSTRUMENT_NOT_ARMED": "Bu paritede giriş etkin değil",
    "DATA_STALE": "İşlem verisi eski",
    "DAILY_LOSS_LIMIT": "Günlük zarar limiti",
    "RECONCILE_INCOMPLETE": "Emir ve hesap mutabakatı tamamlanmadı",
    "OBSERVE_MODE_NO_ORDERS": "Gözlem modu emir göndermez",
    "BELOW_MIN_SIZE": "Risk bütçesine sığan miktar borsanın minimum işlem boyutunun altında",
    "BELOW_MIN_SIZE_RISK": "Borsanın minimum işlem boyutu bile risk tavanını aşıyor",
    "BELOW_MIN_SIZE_BALANCE": "Borsanın minimum işlem boyutunu alacak serbest bakiye yok",
    "NO_EQUITY": "Kullanılabilir sermaye yok",
    "EQUITY_NOT_VERIFIED": "Sermaye doğrulanmadı",
    "ENTRY_FILLED": "Giriş emri gerçekleşti",
    "ENTRY_NOT_FILLED": "Giriş denemesinde fill oluşmadı",
}


def unpack(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def explain_codes(codes):
    ordered = sorted(codes, key=lambda code: code == "RECLAIM_CONFIRMED")
    return [REASONS.get(code, code) for code in ordered]


def strategy():
    return {
        "name": "Reclaim · başlangıç stratejisi",
        "version": "retail_baseline_v1",
        "template": "reclaim_v1",
        "source": "Bu kod sürümündeki referans; eski run'larda tam config snapshot yok.",
        "timeframes": {"context": "15m", "setup": "5m", "flow": "60s"},
        "params": asdict(SetupParams()),
        "rules": [
            "15 dakikalık bağlamda fiyat 20 mumluk ortalamanın üzerinde, eğim pozitif.",
            "5 dakikalık kapanış, önceden onaylanan pivot seviyesini geri kazanır.",
            "Göreli hacim ≥ 1,30; alıcı/satıcı akış dengesizliği ≥ 0,15; kapanış üst yarıda.",
            "Seviyeden uzaklaşma ≤ 1 ATR; stop geri çekilmenin en düşük fiyatında.",
        ],
        "risk": "Referans: işlem başına %1, operasyonel üst sınır %2. "
        "Aktif run'ın tam risk config'i henüz sürümlenmiş değil.",
        "execution": "Mevcut canlı yol: limit IOC giriş; tüm miktara yapısal stop ve +2,5R OCO.",
        "exit_reference": "+1R başabaş, +2R %30, +2,5R %60 ve %10 runner referans plandır; "
        "canlı worker'da kademeli çıkış döngüsü henüz bağlı değil.",
    }


async def market_overview():
    async with pool.market().acquire() as con:
        async with con.transaction(readonly=True):
            rows = await con.fetch("""
                SELECT i.inst_id, i.tick_sz, t.ts, t.px,
                       b.ts book_ts, b.bids, b.asks
                FROM instruments i
                LEFT JOIN LATERAL (
                    SELECT ts, px FROM market_trades WHERE venue=i.venue AND inst_id=i.inst_id
                    ORDER BY ts DESC LIMIT 1
                ) t ON true
                LEFT JOIN LATERAL (
                    SELECT ts, bids, asks FROM book_snapshots
                    WHERE venue=i.venue AND inst_id=i.inst_id ORDER BY ts DESC LIMIT 1
                ) b ON true
                WHERE i.venue='okx-tr' ORDER BY i.inst_id LIMIT 20
            """)
            # Only production worker decisions, never paper demos/test rows.
            decisions = await con.fetch("""
                SELECT DISTINCT ON (d.inst_id) d.inst_id, d.decided_at, d.features,
                       d.data_quality, d.stage_reached, d.reason_codes, d.decision_id,
                       d.run_id, d.candle_open_time
                FROM decisions d WHERE d.run_id=(
                    SELECT run_id FROM runs WHERE code_version IS NOT NULL
                    AND mode IN ('live','observe') ORDER BY run_id DESC LIMIT 1)
                ORDER BY d.inst_id, d.decided_at DESC LIMIT 20
            """)
    latest = {r["inst_id"]: dict(r) for r in decisions}
    now = datetime.now(UTC)
    out = []
    for row in rows:
        r = dict(row)
        d = latest.get(r["inst_id"], {})
        f = {
            k: v
            for k, v in unpack(d.get("features")).items()
            if k
            in (
                "close",
                "atr",
                "rvol",
                "above_ma",
                "trend_slope_atr",
                "flow_imbalance",
                "flow_valid",
                "flow_trades",
                "setup",
                "close_position",
            )
        }
        quality = unpack(d.get("data_quality"))
        # Public discovery exposes setup evidence, never account/risk-gate state.
        if d:
            d["reason_codes"] = [
                code
                for code in d.get("reason_codes", [])
                if code.startswith(
                    (
                        "NO_RECLAIM",
                        "NO_PIVOT",
                        "REGIME_",
                        "RVOL_",
                        "FLOW_",
                        "WEAK_CLOSE",
                        "TOO_EXTENDED",
                        "STOP_TOO_TIGHT",
                        "RECLAIM_CONFIRMED",
                    )
                )
            ]
        bids, asks = unpack(r.pop("bids")), unpack(r.pop("asks"))
        spread = None
        if bids and asks:
            bid, ask = Decimal(bids[0][0]), Decimal(asks[0][0])
            if ask >= bid > 0:
                spread = (ask - bid) / ((ask + bid) / 2) * 10000
        age = (now - r["ts"]).total_seconds() if r["ts"] else None
        decision_age = (now - d["decided_at"]).total_seconds() if d else None
        regime = "Belirsiz"
        if f.get("above_ma") and (f.get("trend_slope_atr") or 0) > 0:
            regime = "Yükseliş bağlamı"
        elif f.get("above_ma") is False:
            regime = "Ortalama altında"
        r.update(
            {
                "age_s": age,
                "stale": age is None or age > 45,
                "decision_stale": decision_age is None or decision_age > 90,
                "spread_bps": str(spread) if spread is not None else None,
                "book_stale": not r["book_ts"] or (now - r["book_ts"]).total_seconds() > 45,
                "regime": regime,
                "features": f,
                "data_quality": quality,
                "decision": {k: v for k, v in d.items() if k not in ("features", "data_quality")},
                "reasons": explain_codes(d.get("reason_codes", [])),
            }
        )
        out.append(r)
    return {"as_of": now, "source": "OKX TR · ATK → PostgreSQL", "instruments": out}


async def workspace(hours: int = 6, inst_id: str | None = None):
    now = datetime.now(UTC)
    async with pool.ledger().acquire() as con:
        async with con.transaction(isolation="repeatable_read", readonly=True):
            run = await con.fetchrow("""SELECT run_id, mode, site, demo, started_at, stopped_at,
                policy_version, notes FROM runs WHERE code_version IS NOT NULL
                AND mode IN ('live','observe') ORDER BY run_id DESC LIMIT 1""")
            if not run:
                return {
                    "as_of": now,
                    "run": None,
                    "strategy": strategy(),
                    "decisions": [],
                    "funnel": None,
                    "ledger": None,
                    "connection": None,
                }
            rid = run["run_id"]
            since = max(now - timedelta(hours=hours), run["started_at"])
            stats = await con.fetchrow(
                """SELECT count(*) evaluations,
                count(DISTINCT (inst_id,candle_open_time))
                    FILTER (WHERE candle_open_time IS NOT NULL) unique_candles,
                count(DISTINCT episode_id) episodes,
                count(*) FILTER (WHERE stage_reached='CONFIRMED') confirmed,
                min(decided_at) first_decision, max(decided_at) last_decision
                FROM decisions WHERE run_id=$1 AND decided_at >= $2
                AND ($3::text IS NULL OR inst_id=$3)""",
                rid,
                since,
                inst_id,
            )
            codes = await con.fetch(
                """SELECT code, count(*) evaluations
                FROM decisions CROSS JOIN LATERAL unnest(reason_codes) AS code
                WHERE run_id=$1 AND decided_at >= $2 AND ($3::text IS NULL OR inst_id=$3)
                GROUP BY code ORDER BY 2 DESC LIMIT 20""",
                rid,
                since,
                inst_id,
            )
            decisions = await con.fetch(
                """SELECT decision_id,run_id,inst_id,decided_at,
                candle_open_time,stage_reached,action,reason_codes,features,data_quality
                FROM decisions WHERE run_id=$1 AND ($2::text IS NULL OR inst_id=$2)
                ORDER BY decided_at DESC LIMIT 12""",
                rid,
                inst_id,
            )
            # Same execution mode across restarts; all financial rows exclude paper.
            positions = await con.fetch(
                """SELECT p.* FROM positions p JOIN runs r USING(run_id)
                WHERE r.code_version IS NOT NULL AND r.mode=$1
                ORDER BY opened_at DESC LIMIT 100""",
                run["mode"],
            )
            pending = await con.fetchval(
                """SELECT coalesce(sum(i.risk_budget),0)
                FROM intents i JOIN runs r USING(run_id) WHERE r.code_version IS NOT NULL
                AND r.mode=$1 AND i.status NOT IN
                ('FILLED','CANCELLED','REJECTED','EXPIRED','RECONCILED')""",
                run["mode"],
            )
            fees = await con.fetch(
                """SELECT f.fee_ccy, sum(f.fee) amount
                FROM fills f JOIN runs r USING(run_id) WHERE r.code_version IS NOT NULL
                AND r.mode=$1 GROUP BY f.fee_ccy""",
                run["mode"],
            )
            fills = await con.fetch(
                """SELECT f.inst_id,f.side,f.px,f.qty,f.fee,f.fee_ccy,f.ts,
                f.run_id,o.intent_id,i.decision_id,d.reason_codes,d.features decision_features
                FROM fills f JOIN runs r USING(run_id)
                LEFT JOIN orders o USING(client_order_id) LEFT JOIN intents i USING(intent_id)
                LEFT JOIN decisions d ON d.decision_id=i.decision_id
                WHERE r.code_version IS NOT NULL AND r.mode=$1 ORDER BY f.ts DESC LIMIT 20
                """,
                run["mode"],
            )
            recon = await con.fetchrow(
                """SELECT ts, detail FROM ops_events
                WHERE run_id=$1 AND kind='startup_reconcile' ORDER BY ts DESC LIMIT 1""",
                rid,
            )
    notes = unpack(run["notes"])
    safe_run = {k: v for k, v in dict(run).items() if k != "notes"}
    safe_run["entry_budget"] = notes.get("max_entries_per_run")
    safe_run["entry_instruments"] = notes.get("entry_instruments")
    safe_run["last_decision"] = stats["last_decision"]
    safe_run["health"] = (
        "stopped"
        if run["stopped_at"]
        else "recent_decisions"
        if stats["last_decision"] and (now - stats["last_decision"]).total_seconds() <= 90
        else "unknown"
    )
    result = []
    for row in decisions:
        d = dict(row)
        d["features"] = unpack(d["features"])
        d["data_quality"] = unpack(d["data_quality"])
        d["reasons"] = explain_codes(d["reason_codes"])
        result.append(d)
    opened = [p for p in positions if p["status"] != "CLOSED"]
    closed = [p for p in positions if p["status"] == "CLOSED"]
    return {
        "as_of": now,
        "run": safe_run,
        "strategy": strategy(),
        "decisions": result,
        "funnel": {
            **dict(stats),
            "since": since,
            "until": now,
            "inst_id": inst_id,
            "codes": [
                {
                    "code": c["code"],
                    "label": REASONS.get(c["code"], c["code"]),
                    "evaluations": c["evaluations"],
                }
                for c in codes
            ],
        },
        "ledger": {
            "mode": run["mode"],
            "scope": "Aynı moddaki worker kayıtları; son 100 pozisyon",
            "open_positions": len(opened),
            "closed_positions": len(closed),
            "open_risk_quote": str(
                sum(
                    (
                        p["frozen_risk_amount"] * p["qty_open"] / p["initial_qty"]
                        for p in opened
                        if p["initial_qty"]
                    ),
                    Decimal(0),
                )
            ),
            "pending_risk_quote": str(pending),
            "realized_net_quote": str(sum((p["realized_pnl"] for p in closed), Decimal(0))),
            "fees": [dict(f) for f in fees],
            "fills": [dict(f) for f in fills],
            "positions": [
                {
                    k: p[k]
                    for k in (
                        "position_id",
                        "inst_id",
                        "status",
                        "qty_open",
                        "avg_entry_px",
                        "current_stop_px",
                        "run_id",
                    )
                }
                for p in positions
            ],
            "limitation": "Açık risk, kalan miktarın ilk risk bazıdır; güncel stop riski değildir. "
            "Canlı çıkışlar çalışma sırasında henüz uzlaştırılmıyor; "
            "ledger sonucu borsanın güncel sonucu olarak kabul edilmemeli.",
        },
        "connection": {
            "alias": "Yapılandırılmış operatör hesabı",
            "configured": notes.get("authenticated", False),
            "last_check": recon["ts"] if recon else None,
            "reconciled_at_start": unpack(recon["detail"]).get("clean") if recon else None,
            "permissions": "Trade / withdrawal izinleri bağımsız doğrulanmadı",
            "storage": "Mevcut kurulum: sunucuda plaintext env dosyası; ATK alt sürecine "
            "environment ile aktarılır. Şifreli kasa / ATK profil geçişi uygulanmadı.",
        },
    }


def route_question(message: str) -> str:
    text = message.casefold().replace("ı", "i").replace("i̇", "i")
    if any(
        w in text
        for w in (
            "kopyala",
            "değiştir",
            "degistir",
            "başlat",
            "baslat",
            "oluştur",
            "olustur",
            "satın",
            "satin",
            "emir ver",
            "gölge",
            "golge",
        )
    ):
        return "unsupported"
    if any(w in text for w in ("son işlem", "son islem", "fill")):
        return "last_trade"
    if any(w in text for w in ("neden", "niye", "açmad", "acmad", "bekli", "kurulum")):
        return "explain_wait"
    if any(w in text for w in ("risk", "maliyet", "ücret", "ucret", "kazanç", "kazanc", "pnl")):
        return "get_risk_summary"
    if any(w in text for w in ("son işlem", "son islem", "fill")):
        return "last_trade"
    if any(w in text for w in ("strateji", "kural", "nasıl çalış", "nasil calis")):
        return "get_strategy"
    if any(
        w in text for w in ("piyasa", "fotoğraf", "fotograf", "hacim", "spread", "fiyat", "trend")
    ):
        return "get_market_overview"
    return "unsupported"


def number(value, digits=3):
    if value is None:
        return "—"
    return f"{Decimal(str(value)):.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


async def answer_question(message: str, inst_id: str | None, hours: int):
    tool = route_question(message)
    explicit = re.search(r"\b(BTC|ETH|SOL)(?:-USDT)?\b", message.upper())
    if explicit:
        inst_id = explicit.group(1) + "-USDT"
    elif any(word in message.casefold() for word in ("pariteler", "piyasa")):
        inst_id = None
    started = datetime.now(UTC)
    data = None
    if tool == "get_market_overview":
        data = await market_overview()
        rows = [r for r in data["instruments"] if not inst_id or r["inst_id"] == inst_id]
        text = (
            "\n".join(
                f"{r['inst_id']}: {r['regime']}. "
                f"Göreli hacim {number(r['features'].get('rvol'))}; "
                f"{'veri eski' if r['stale'] or r['decision_stale'] else 'veri güncel'}."
                for r in rows
            )
            or "Bu kapsamda piyasa kaydı yok."
        )
        text += "\nBağlam 15m, kurulum 5m; yalnız izlenen OKX TR paritelerini kapsar."
    elif tool == "get_strategy":
        data = strategy()
        text = "\n".join(data["rules"]) + "\n" + data["execution"] + "\n" + data["exit_reference"]
    elif tool != "unsupported":
        data = await workspace(hours, inst_id)
        f = data.get("funnel")
        if not data["run"]:
            text = "Henüz gerçek worker çalışması kaydedilmemiş."
        elif tool == "explain_wait":
            text = (
                f"Run #{data['run']['run_id']}: seçilen dönemde {f['evaluations']} değerlendirme, "
                f"{f['unique_candles']} farklı parite/mum, {f['episodes']} kurulum bölümü var. "
                f"{f['confirmed']} değerlendirme sinyal onayına ulaşmış."
            )
            if not f["evaluations"]:
                text += (
                    "\nBu dönemde karar kaydı yok; bunu piyasa seçiciliği olarak yorumlayamayız."
                )
            elif not f["confirmed"]:
                text += "\nSinyal onayı olmadığı için risk ve emir aşamasına geçilmemiş."
            recent = data.get("decisions", [])
            if recent:
                last = recent[0]
                text += (
                    f"\nSon kayıt: {last['inst_id']}, göreli hacim "
                    f"{number(last['features'].get('rvol'))} (eşik 1,30). "
                    + "; ".join(last.get("reasons", []))
                )
            if f["confirmed"]:
                blocked = [
                    c
                    for c in f["codes"]
                    if c["code"]
                    in {
                        "CONCURRENCY_LIMIT",
                        "ENTRY_BUDGET_EXHAUSTED",
                        "DAILY_LOSS_LIMIT",
                        "RECONCILE_INCOMPLETE",
                        "DATA_STALE",
                        "INSTRUMENT_NOT_ARMED",
                        "ENTRY_NOT_FILLED",
                        "UNRESOLVED_ORDER",
                    }
                ]
                if blocked:
                    text += "\nOnaydan sonraki engeller: " + "; ".join(
                        f"{c['label']} ({c['evaluations']})" for c in blocked
                    )
            matching_fills = [
                fill
                for fill in data.get("ledger", {}).get("fills", [])
                if (not inst_id or fill["inst_id"] == inst_id)
                and fill["run_id"] == data["run"]["run_id"]
            ]
            if matching_fills:
                text += "\nBu çalışma kapsamında gerçekleşmiş fill var; hiç işlem yok değil."
            text += "\n" + "\n".join(
                f"{c['label']}: {c['evaluations']} değerlendirme" for c in f["codes"][:4]
            )
            text += (
                "\nAynı mum tekrar değerlendirilebilir; neden sayıları bağımsız fırsat değildir."
            )
        elif tool == "get_risk_summary":
            ledger = data["ledger"]
            text = (
                f"Ledger: {ledger['open_positions']} açık pozisyon. İlk risk bazında açık risk "
                f"{number(ledger['open_risk_quote'])} USDT; bekleyen risk "
                f"{number(ledger['pending_risk_quote'])} USDT. "
                "Kapalı pozisyonların kayıtlı net sonucu "
                f"{number(ledger['realized_net_quote'])} USDT.\n"
                + ledger["scope"]
                + ".\n"
                + ledger["limitation"]
            )
        else:
            fills = data["ledger"]["fills"]
            fill = next((f for f in fills if not inst_id or f["inst_id"] == inst_id), None)
            text = (
                f"Son kayıtlı fill: {fill['inst_id']} · {fill['side']} · "
                f"{number(fill['qty'], 8)} @ {number(fill['px'])}. Karar #{fill['decision_id']}, "
                f"intent #{fill['intent_id']}, run #{fill['run_id']}."
                if fill
                else "Bu kapsamda gerçekleşmiş işlem kaydı yok; gerekçe üretemem."
            )
            if fill:
                frozen = unpack(fill.get("decision_features"))
                evidence = frozen.get("setup", frozen)
                text += (
                    f"\nKarar anında: hacim {number(evidence.get('rvol'))}; "
                    f"akış {number(evidence.get('flow_imbalance'))}; "
                    f"seviye {number(evidence.get('level'))} USDT; "
                    f"uzaklaşma {number(evidence.get('extension_atr'))} ATR."
                )
                reasons = explain_codes(fill.get("reason_codes") or [])
                text += "\nO kararda kaydedilen gerekçe: " + ("; ".join(reasons) or "Kaydedilmemiş")
                text += (
                    "\nBu açıklama giriş kararının kaydına dayanır; bugünkü grafikten üretilmez."
                )
    else:
        text = (
            "Bu ilk sürüm piyasa, strateji kuralları, bekleme nedenleri, risk ve son fill "
            "sorularını destekler. Taslak oluşturma ve gölge başlatma henüz bağlı değil. "
            "Örneğin “Neden işlem açmadık?” diye sorabilirsiniz."
        )
    return {
        "text": text,
        "tool": tool,
        "data": data,
        "as_of": datetime.now(UTC),
        "duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000),
        "engine": "deterministic_reader_v1",
        "notice": "Sınırlı sorgu asistanı · LLM bağlı değil · geçmiş bu oturumda tutulur",
    }
