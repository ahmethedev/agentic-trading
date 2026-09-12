"""Application tools the chat model may call.

Every tool is a thin, read-only projection of a service function the dashboard
already uses, so a chat answer and a card cannot disagree (PRODUCT.md §10).
Three properties hold by construction here:

* No tool writes. Nothing in this module can create a draft, start a run, place
  or cancel an order, or change a limit. The model has no path to the venue.
* No tool computes money. Risk, sizing and PnL arrive already calculated from
  the worker's records; the model only reads them out.
* No tool touches credentials. The payloads are built field by field, so a new
  secret appearing in an upstream record cannot ride along into the prompt.

Payloads are deliberately narrow: the model answers better from forty labelled
numbers than from a full table dump, and every token here is paid for twice
(once to send, once because a longer context invites invention).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .service import explain_codes, market_overview, strategy, unpack, workspace

PUBLIC = "public"
OPERATOR = "operator"


def encode(value: Any) -> str:
    """JSON for the model: Decimals as strings, timestamps as ISO-8601 UTC."""

    def default(v: Any) -> Any:
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, datetime):
            return v.astimezone(UTC).isoformat(timespec="seconds")
        return str(v)

    return json.dumps(value, default=default, ensure_ascii=False)


@dataclass
class Context:
    """One question's worth of data access.

    The model may call several tools in one turn, and most of them read the same
    workspace query. Memoising per question keeps that to a single round trip and
    guarantees every tool in one answer describes the same instant.
    """

    authorized: bool
    default_inst_id: str | None = None
    hours: int = 6

    def __post_init__(self) -> None:
        self._market: dict | None = None
        self._workspace: dict[tuple[int, str | None], dict] = {}

    async def market(self) -> dict:
        if self._market is None:
            self._market = await market_overview()
        return self._market

    async def workspace(self, hours: int, inst_id: str | None) -> dict:
        key = (hours, inst_id)
        if key not in self._workspace:
            self._workspace[key] = await workspace(hours, inst_id)
        return self._workspace[key]


# --- Tool implementations ---------------------------------------------------

FEATURE_KEYS = (
    "close",
    "atr",
    "rvol",
    "above_ma",
    "trend_slope_atr",
    "flow_imbalance",
    "flow_valid",
    "flow_trades",
    "close_position",
)


async def get_market_overview(ctx: Context, inst_id: str | None = None) -> dict:
    data = await ctx.market()
    rows = [r for r in data["instruments"] if not inst_id or r["inst_id"] == inst_id]
    return {
        "as_of": data["as_of"],
        "source": data["source"],
        "coverage": "Yalnız bu listede görünen OKX TR spot pariteleri izleniyor.",
        "timeframes": {"context": "15m", "setup": "5m", "flow": "60s"},
        "instruments": [
            {
                "inst_id": r["inst_id"],
                "last_px": r["px"],
                "last_trade_ts": r["ts"],
                "trade_age_s": round(r["age_s"]) if r["age_s"] is not None else None,
                "trade_data_stale": r["stale"],
                "spread_bps": r["spread_bps"],
                "book_stale": r["book_stale"],
                "regime_label": r["regime"],
                "features": {k: v for k, v in r["features"].items() if k in FEATURE_KEYS},
                "data_quality": r["data_quality"],
                "latest_evaluation": {
                    "decided_at": r["decision"].get("decided_at"),
                    "stage_reached": r["decision"].get("stage_reached"),
                    "stale": r["decision_stale"],
                    "setup_reasons": r["reasons"],
                },
            }
            for r in rows
        ],
        "note": "regime_label ölçüm değil, above_ma ve trend_slope_atr üzerinden türetilmiş "
        "kaba bir etikettir. Zayıf trend otomatik olarak range demek değildir. "
        "Alan tanımları: above_ma = 15m bağlamda 20 mumluk ortalamanın üstünde mi; "
        "trend_slope_atr = ATR'ye göre normalize edilmiş eğim; rvol = göreli hacim "
        "(1,0 = normal); flow_imbalance/flow_trades = 60 saniyelik akış penceresi; "
        "fiyatlar USDT. Burada yazmayan bir periyot veya eşik uydurma.",
    }


async def get_strategy(ctx: Context) -> dict:
    return strategy()


async def get_decision_funnel(ctx: Context, hours: int = 6, inst_id: str | None = None) -> dict:
    data = await ctx.workspace(hours, inst_id)
    if not data["run"]:
        return {"run": None, "note": "Kaydedilmiş gerçek worker çalışması yok."}
    f = data["funnel"]
    return {
        "run_id": data["run"]["run_id"],
        "mode": data["run"]["mode"],
        "window": {"since": f["since"], "until": f["until"], "inst_id": f["inst_id"]},
        "evaluations": f["evaluations"],
        "unique_candles": f["unique_candles"],
        "episodes": f["episodes"],
        "confirmed": f["confirmed"],
        "first_decision": f["first_decision"],
        "last_decision": f["last_decision"],
        "reason_counts": [
            {"code": c["code"], "label": c["label"], "evaluations": c["evaluations"]}
            for c in f["codes"]
        ],
        "recent_decisions": [
            {
                "decision_id": d["decision_id"],
                "inst_id": d["inst_id"],
                "decided_at": d["decided_at"],
                "candle_open_time": d["candle_open_time"],
                "stage_reached": d["stage_reached"],
                "action": d["action"],
                "reasons": d["reasons"],
                "features": {k: v for k, v in d["features"].items() if k in FEATURE_KEYS},
            }
            for d in data["decisions"][:6]
        ],
        "note": "Aynı mum birden çok kez değerlendirilir; reason_counts bağımsız fırsat "
        "sayısı değildir. evaluations ile unique_candles farkı bundan gelir.",
    }


async def get_risk_summary(ctx: Context, hours: int = 6) -> dict:
    data = await ctx.workspace(hours, None)
    if not data["run"]:
        return {"run": None, "note": "Kaydedilmiş gerçek worker çalışması yok."}
    ledger = data["ledger"]
    return {
        "run_id": data["run"]["run_id"],
        "mode": ledger["mode"],
        "scope": ledger["scope"],
        "open_positions": ledger["open_positions"],
        "closed_positions": ledger["closed_positions"],
        "open_risk_quote": ledger["open_risk_quote"],
        "pending_risk_quote": ledger["pending_risk_quote"],
        "realized_net_quote": ledger["realized_net_quote"],
        "quote_ccy": "USDT",
        "fees": ledger["fees"],
        "positions": ledger["positions"],
        "limitation": ledger["limitation"],
        "note": "Bu değerler ledger'da hesaplanmıştır. Yeniden hesaplama, toplama veya "
        "farklı para birimlerini birleştirme yapma.",
    }


async def get_recent_fills(ctx: Context, inst_id: str | None = None, hours: int = 6) -> dict:
    data = await ctx.workspace(hours, None)
    if not data["run"]:
        return {"run": None, "note": "Kaydedilmiş gerçek worker çalışması yok."}
    fills = [f for f in data["ledger"]["fills"] if not inst_id or f["inst_id"] == inst_id]
    evidence_keys = FEATURE_KEYS + ("level", "extension_atr", "stop_px")

    def frozen(row):
        features = unpack(row["decision_features"])
        setup = features.get("setup", features)
        return {k: v for k, v in setup.items() if k in evidence_keys}

    return {
        "count": len(fills),
        "fills": [
            {
                "inst_id": f["inst_id"],
                "side": f["side"],
                "px": f["px"],
                "qty": f["qty"],
                "fee": f["fee"],
                "fee_ccy": f["fee_ccy"],
                "ts": f["ts"],
                "run_id": f["run_id"],
                "intent_id": f["intent_id"],
                "decision_id": f["decision_id"],
                "decision_reasons": explain_codes(f["reason_codes"] or []),
                "decision_features": frozen(f),
            }
            for f in fills[:10]
        ],
        "note": "decision_features o karar anında dondurulmuş girdilerdir. Gerekçeyi "
        "yalnız bunlardan açıkla; bugünkü fiyattan geriye dönük hikâye kurma.",
    }


async def get_run_status(ctx: Context, hours: int = 6) -> dict:
    data = await ctx.workspace(hours, None)
    if not data["run"]:
        return {"run": None, "note": "Kaydedilmiş gerçek worker çalışması yok."}
    run, conn = data["run"], data["connection"]
    return {
        "run": {
            "run_id": run["run_id"],
            "mode": run["mode"],
            "site": run["site"],
            "demo": run["demo"],
            "started_at": run["started_at"],
            "stopped_at": run["stopped_at"],
            "health": run["health"],
            "last_decision": run["last_decision"],
            "entry_budget": run["entry_budget"],
            "entry_instruments": run["entry_instruments"],
            "policy_version": run["policy_version"],
        },
        "connection": {
            "alias": conn["alias"],
            "configured": conn["configured"],
            "last_check": conn["last_check"],
            "reconciled_at_start": conn["reconciled_at_start"],
            "permissions": conn["permissions"],
            "storage": conn["storage"],
        },
        "note": "health='unknown' worker'ın durduğu anlamına gelmez; yalnız son 90 saniyede "
        "karar kaydı görülmediğini söyler.",
    }


# --- Registry ---------------------------------------------------------------

INSTRUMENT_ARG = {
    "type": "string",
    "pattern": "^[A-Z0-9]{2,12}-USDT$",
    "description": "Tek parite ile sınırla, örn. BTC-USDT. Boş bırakılırsa hepsi.",
}
HOURS_ARG = {
    "type": "integer",
    "minimum": 1,
    "maximum": 48,
    "description": "Geriye dönük pencere (saat). Varsayılan 6.",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_market_overview",
        "scope": PUBLIC,
        "handler": get_market_overview,
        "stage": "Piyasa verileri alınıyor",
        "description": (
            "İzlenen OKX TR paritelerinin son fiyatı, veri yaşı, spread'i, göreli hacmi, "
            "trend/akış ölçümleri ve son kurulum değerlendirmesi. Piyasa durumu, hangi "
            "paritede kurulum oluştuğu ve veri tazeliği soruları için kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"inst_id": INSTRUMENT_ARG},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_strategy",
        "scope": PUBLIC,
        "handler": get_strategy,
        "stage": "Strateji sürümü okunuyor",
        "description": (
            "Aktif stratejinin sürümü, giriş/teyit/çıkış kuralları, eşik parametreleri, "
            "risk referansı ve execution yolu. Strateji nasıl çalışıyor sorularında kullan."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_decision_funnel",
        "scope": OPERATOR,
        "handler": get_decision_funnel,
        "stage": "Karar kayıtları sorgulanıyor",
        "description": (
            "Seçilen dönemde worker'ın değerlendirme sayısı, farklı parite/mum sayısı, "
            "onaya ulaşan kurulumlar, ret nedenlerinin dağılımı ve son kararların "
            "dondurulmuş girdileri. 'Neden işlem açmadık?' sorusunun kaynağıdır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"hours": HOURS_ARG, "inst_id": INSTRUMENT_ARG},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_risk_summary",
        "scope": OPERATOR,
        "handler": get_risk_summary,
        "stage": "Risk ve maliyet kayıtları okunuyor",
        "description": (
            "Ledger'dan açık/bekleyen risk, kapanmış pozisyonların net sonucu, ödenen "
            "fee'ler ve pozisyon listesi. Risk, maliyet ve sonuç sorularında kullan. "
            "Değerler hesaplanmış gelir; yeniden hesaplama."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"hours": HOURS_ARG},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recent_fills",
        "scope": OPERATOR,
        "handler": get_recent_fills,
        "stage": "Gerçekleşen işlemler açılıyor",
        "description": (
            "Gerçekleşmiş fill'ler: fiyat, miktar, fee, zaman ve bağlı intent/karar "
            "referansı ile o karar anında kaydedilmiş girdiler. 'Son işlemi neden aldık?' "
            "sorusunun kaynağıdır."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"inst_id": INSTRUMENT_ARG, "hours": HOURS_ARG},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_run_status",
        "scope": OPERATOR,
        "handler": get_run_status,
        "stage": "Çalışma durumu kontrol ediliyor",
        "description": (
            "Aktif run'ın kimliği, çalışma modu (LIVE/OBSERVE), başlangıcı, son karar "
            "zamanı, giriş bütçesi ve OKX bağlantı/mutabakat durumu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"hours": HOURS_ARG},
            "additionalProperties": False,
        },
    },
]

BY_NAME = {t["name"]: t for t in TOOLS}


def schemas(authorized: bool) -> list[dict[str, Any]]:
    """Tool definitions for the API call, narrowed to what this session may read.

    Operator tools are withheld rather than offered-and-refused: an unauthorised
    session should get an honest "hesap kayıtları kapalı" answer in one turn, not
    a round trip that ends in an error block.
    """
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        }
        for t in TOOLS
        if authorized or t["scope"] == PUBLIC
    ]


def stage_label(name: str) -> str:
    tool = BY_NAME.get(name)
    return tool["stage"] if tool else "Kayıtlar sorgulanıyor"


async def execute(ctx: Context, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Run one tool call. Returns (payload, is_error).

    The scope check repeats here on purpose. `schemas()` already hides operator
    tools from an unauthorised session, but a model can name a tool it was never
    offered, and the enforcement that protects account data must not live in the
    prompt.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        return f"Bilinmeyen araç: {name}. Yalnız tanımlı araçları çağır.", True
    if tool["scope"] == OPERATOR and not ctx.authorized:
        return (
            "Operatör oturumu açık değil, bu kayıt okunamaz. Kullanıcıya hesap "
            "kayıtları için operatör erişim kodunu girmesi gerektiğini söyle; "
            "piyasa ve strateji soruları oturumsuz da cevaplanabilir.",
            True,
        )
    allowed = set(tool["input_schema"].get("properties", {}))
    unknown = set(arguments) - allowed
    if unknown:
        return f"Geçersiz parametre: {sorted(unknown)}. İzinli alanlar: {sorted(allowed)}.", True
    try:
        result = await tool["handler"](ctx, **arguments)
    except TypeError as exc:
        return f"Parametre hatası: {exc}", True
    return encode(result), False
