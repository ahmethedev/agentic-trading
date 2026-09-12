"""The supported strategy template and the rules a draft may change.

A trader's idea becomes a draft by editing ONE field of a saved version, chosen
from the catalogue below (PRODUCT.md §6). That restriction is what makes the
result of an experiment attributable: if two rules move at once, the comparison
cannot say which one mattered.

Nothing here executes anything. A version is a validated parameter document;
what it produces is a readable rule card and, through `simulate.py`, a simulated
run. Free text never becomes code: an unsupported request is refused by name,
never quietly mapped onto a neighbouring field.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ..risk.sizing import (
    BREAKEVEN_R,
    RUNNER_FRACTION,
    TP1_FRACTION,
    TP1_R,
    TP2_FRACTION,
    TP2_R,
)
from ..strategy.setup import SetupParams

TEMPLATE = "reclaim_v1"
BASELINE_LABEL = "hackathon_aggressive_v1"

# Time cap on the runner leg. The live plan has no time stop: it holds the
# remainder until the stop is hit. A simulation cannot hold a position open for
# ever -- the leg's single concurrency slot would never free up and the run would
# report one trade regardless of the rule under test -- so both legs of every
# experiment carry the same declared cap, and it is shown in the assumptions.
DEFAULT_MAX_HOLD_BARS = 48


def baseline_params() -> dict[str, Any]:
    """The rules the live worker is running today, as an editable document."""
    setup = SetupParams()
    return {
        "template": TEMPLATE,
        "universe": [
            "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT",
            "DOGE-USDT", "SUI-USDT", "LINK-USDT", "AVAX-USDT",
        ],
        "timeframes": {"context": "15m", "setup": "5m", "flow": "60s"},
        "entry": {
            "min_rvol": float(setup.min_rvol),
            "min_flow_imbalance": float(setup.min_flow_imbalance),
            "min_close_position": float(setup.min_close_position),
            "min_pullback_atr": float(setup.min_pullback_atr),
            "max_extension_atr": float(setup.max_extension_atr),
            "min_stop_distance_atr": float(setup.min_stop_distance_atr),
        },
        "exit": {
            # None means "never move the stop to entry", which is exactly the
            # first experiment PRODUCT.md §8 asks for.
            "breakeven_r": float(BREAKEVEN_R),
            "tp1_r": float(TP1_R),
            "tp1_fraction": float(TP1_FRACTION),
            "tp2_r": float(TP2_R),
            "tp2_fraction": float(TP2_FRACTION),
            "runner_fraction": float(RUNNER_FRACTION),
            "max_hold_bars": DEFAULT_MAX_HOLD_BARS,
        },
        "risk": {
            "risk_fraction": 0.02,
            "max_concurrent_positions": 4,
            "max_position_fraction": 0.25,
        },
    }


@dataclass(frozen=True)
class Field:
    key: str                 # "exit.breakeven_r"
    label: str
    help: str
    unit: str
    minimum: float | None
    maximum: float | None
    step: float
    nullable: bool = False   # may be cleared, meaning "this rule is switched off"
    null_label: str = ""
    integer: bool = False

    @property
    def section(self) -> str:
        return self.key.split(".", 1)[0]


# The editable surface. Anything not listed here cannot be changed by a draft,
# and the UI offers exactly this list rather than a free-form JSON editor.
FIELDS: tuple[Field, ...] = (
    Field(
        "exit.breakeven_r",
        "Başabaş kuralı",
        "Stop, kaç R kârda gerçek giriş fiyatına çekilsin?",
        "R",
        0.25,
        3.0,
        0.25,
        nullable=True,
        null_label="Stop başabaşa çekilmez",
    ),
    Field("exit.tp1_r", "İlk hedef mesafesi", "İlk kısmi satışın R hedefi.", "R", 0.5, 6.0, 0.25),
    Field(
        "exit.tp1_fraction",
        "İlk hedefte satılan oran",
        "İlk hedefte ilk miktarın ne kadarı satılsın?",
        "oran",
        0.05,
        0.9,
        0.05,
    ),
    Field(
        "exit.tp2_r", "İkinci hedef mesafesi", "İkinci kısmi satışın R hedefi.", "R", 0.5, 8.0, 0.25
    ),
    Field(
        "exit.tp2_fraction",
        "İkinci hedefte satılan oran",
        "İkinci hedefte ilk miktarın ne kadarı satılsın?",
        "oran",
        0.05,
        0.9,
        0.05,
    ),
    Field(
        "exit.max_hold_bars",
        "Azami tutma süresi",
        "Runner kaç 5 dakikalık mum sonunda kapatılsın? (simülasyon varsayımı)",
        "mum",
        6,
        288,
        6,
        integer=True,
    ),
    Field(
        "entry.min_rvol",
        "Göreli hacim eşiği",
        "Teyit için gereken göreli hacim.",
        "×",
        0.5,
        5.0,
        0.05,
    ),
    Field(
        "entry.min_flow_imbalance",
        "Alıcı baskısı eşiği",
        "Teyit için gereken alıcı/satıcı dengesizliği.",
        "",
        -0.5,
        0.95,
        0.05,
    ),
    Field(
        "entry.min_close_position",
        "Kapanış konumu eşiği",
        "Tetik mumunun kendi aralığında nerede kapandığı.",
        "",
        0.0,
        1.0,
        0.05,
    ),
    Field(
        "entry.max_extension_atr",
        "Seviyeden azami uzaklaşma",
        "Seviyenin kaç ATR üstüne kadar giriş kabul edilsin?",
        "ATR",
        0.1,
        4.0,
        0.1,
    ),
    Field(
        "entry.min_pullback_atr",
        "Asgari geri çekilme derinliği",
        "Kurulum sayılması için gereken geri çekilme derinliği.",
        "ATR",
        0.0,
        3.0,
        0.1,
    ),
    Field(
        "entry.min_stop_distance_atr",
        "Asgari stop mesafesi",
        "Bundan dar stop mesafeleri elenir.",
        "ATR",
        0.0,
        3.0,
        0.05,
    ),
)
BY_KEY = {f.key: f for f in FIELDS}


class DraftRejected(Exception):
    """A draft that cannot be saved, with the reason shown to the user."""


def get_value(params: dict[str, Any], key: str) -> Any:
    section, name = key.split(".", 1)
    return params.get(section, {}).get(name)


def _coerce(field: Field, value: Any) -> Any:
    if value is None or value == "":
        if not field.nullable:
            raise DraftRejected(f"{field.label} boş bırakılamaz.")
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DraftRejected(f"{field.label} sayısal bir değer olmalı.") from exc
    if field.integer and number != number.to_integral_value():
        raise DraftRejected(f"{field.label} tam sayı olmalı.")
    if field.minimum is not None and number < Decimal(str(field.minimum)):
        raise DraftRejected(f"{field.label} en az {format_value(field, field.minimum)} olabilir.")
    if field.maximum is not None and number > Decimal(str(field.maximum)):
        raise DraftRejected(
            f"{field.label} en fazla {format_value(field, field.maximum)} olabilir."
        )
    return int(number) if field.integer else float(number)


def apply_change(parent: dict[str, Any], key: str, value: Any) -> tuple[dict[str, Any], Any]:
    """Copy `parent` with exactly one catalogued field replaced.

    Returns the new params and the coerced value. The caller keeps the parent
    row untouched: a version that a run points at is never edited in place.
    """
    field = BY_KEY.get(key)
    if field is None:
        raise DraftRejected(
            f"“{key}” bu şablonda düzenlenebilir bir kural değil. "
            "Desteklenen kurallar listesinden birini seç."
        )
    coerced = _coerce(field, value)
    if coerced == get_value(parent, key):
        raise DraftRejected(f"{field.label} zaten bu değerde; deney için farklı bir değer seç.")
    section, name = key.split(".", 1)
    params = {
        **parent,
        section: {**parent[section], name: coerced},
    }
    validate(params)
    return params, coerced


def validate(params: dict[str, Any]) -> None:
    """Cross-field checks the per-field bounds cannot express."""
    exit_rules = params["exit"]
    sold = Decimal(str(exit_rules["tp1_fraction"])) + Decimal(str(exit_rules["tp2_fraction"]))
    if sold >= 1:
        raise DraftRejected(
            "İki hedefte satılan toplam oran %100'e ulaşamaz; runner için pay kalmalı."
        )
    if exit_rules["tp2_r"] <= exit_rules["tp1_r"]:
        raise DraftRejected("İkinci hedef, ilk hedeften uzakta olmalı.")
    breakeven = exit_rules["breakeven_r"]
    if breakeven is not None and breakeven >= exit_rules["tp1_r"]:
        raise DraftRejected("Başabaş tetiği ilk hedeften önce gelmeli.")
    params["exit"]["runner_fraction"] = float(1 - sold)


def format_value(field: Field, value: Any) -> str:
    if value is None:
        return field.null_label or "kapalı"
    if field.integer:
        return f"{int(value)} {field.unit}".strip()
    if field.unit == "oran":
        return f"%{Decimal(str(value)) * 100:.0f}".replace(".", ",")
    text = f"{Decimal(str(value)).normalize():f}".replace(".", ",")
    return f"{text} {field.unit}".strip()


def describe(params: dict[str, Any]) -> list[str]:
    """The version's rules in Turkish, generated from the parameters.

    The card and the diff both read from here, so a saved rule and the sentence
    shown for it cannot drift apart.
    """
    entry, exit_rules = params["entry"], params["exit"]
    breakeven = exit_rules["breakeven_r"]
    return [
        "15 dakikalık bağlamda fiyat ortalama üzerinde veya eğim sert biçimde negatif değil.",
        "5 dakikalık kapanış, önceden onaylanan pivot seviyesini geri kazanır.",
        f"Göreli hacim ≥ {_num(entry['min_rvol'])}; akış dengesizliği ≥ "
        f"{_num(entry['min_flow_imbalance'])}; kapanış konumu ≥ "
        f"{_num(entry['min_close_position'])}.",
        f"Geri çekilme derinliği ≥ {_num(entry['min_pullback_atr'])} ATR; seviyeden uzaklaşma "
        f"≤ {_num(entry['max_extension_atr'])} ATR; stop mesafesi ≥ "
        f"{_num(entry['min_stop_distance_atr'])} ATR.",
        "Stop, geri çekilmenin en düşük fiyatında.",
        (
            f"+{_num(breakeven)}R'da stop gerçek giriş fiyatına çekilir."
            if breakeven is not None
            else "Stop başabaşa çekilmez; ilk yapısal stop yerinde kalır."
        ),
        f"+{_num(exit_rules['tp1_r'])}R'da ilk miktarın %{_pct(exit_rules['tp1_fraction'])}'i, "
        f"+{_num(exit_rules['tp2_r'])}R'da %{_pct(exit_rules['tp2_fraction'])}'i satılır; "
        f"kalan %{_pct(exit_rules['runner_fraction'])} runner.",
    ]


def diff(parent: dict[str, Any], child: dict[str, Any]) -> list[dict[str, str]]:
    """Every catalogued field whose value differs, for the rule-diff card."""
    out = []
    for field in FIELDS:
        before, after = get_value(parent, field.key), get_value(child, field.key)
        if before != after:
            out.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "before": format_value(field, before),
                    "after": format_value(field, after),
                }
            )
    return out


def catalogue(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The editable rules with their current values, for the draft form."""
    return [
        {
            "key": f.key,
            "label": f.label,
            "help": f.help,
            "unit": f.unit,
            "section": "Çıkış kuralı" if f.section == "exit" else "Giriş kuralı",
            "minimum": f.minimum,
            "maximum": f.maximum,
            "step": f.step,
            "nullable": f.nullable,
            "null_label": f.null_label,
            "integer": f.integer,
            "current": get_value(params, f.key),
            "current_label": format_value(f, get_value(params, f.key)),
        }
        for f in FIELDS
    ]


def _num(value: Any) -> str:
    return f"{Decimal(str(value)).normalize():f}".replace(".", ",")


def _pct(value: Any) -> str:
    return f"{Decimal(str(value)) * 100:.0f}"
