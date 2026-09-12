"""Reclaim setup detection (retail_baseline_v1 hypothesis).

Hypothesis (AGENT.md §4): in an uptrend context, after a pullback below a level
that was defined by EARLIER closed candles, a close back above that level --
supported by relative volume and aggressive buying -- is a spot long candidate.

Three questions answered explicitly in code:
  * When are we buyers?   -> regime up AND reclaim close AND confirmation
  * Where is the idea wrong? -> below the pullback low (structural stop)
  * When do we not chase?  -> extension beyond `max_extension_atr` from the level

No-lookahead rule: the level is a pivot high confirmed by bars to its RIGHT that
have already closed, and the pivot is chosen only from bars strictly before the
trigger candle.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from ..features.compute import Candle, FeatureSnapshot


class Stage(StrEnum):
    """Opportunity funnel. Every candidate records how far it got."""

    SCANNED = "SCANNED"
    DATA_INVALID = "DATA_INVALID"
    REGIME_REJECTED = "REGIME_REJECTED"
    NO_SETUP = "NO_SETUP"
    SETUP_FORMED = "SETUP_FORMED"
    CONFIRM_REJECTED = "CONFIRM_REJECTED"
    EXTENSION_REJECTED = "EXTENSION_REJECTED"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True)
class SetupParams:
    """Starting config. These are recorded hypotheses, not tuned optima."""

    pivot_left: int = 2          # bars left of the pivot high
    pivot_right: int = 2         # bars right -- all must be CLOSED (no lookahead)
    lookback: int = 30           # how far back to search for the level
    min_slope_atr: float = 0.0   # regime: MA slope per bar, in ATR units
    min_rvol: float = 1.3        # confirmation: relative volume
    min_flow_imbalance: float = 0.15  # confirmation: taker buy dominance
    min_close_position: float = 0.5   # trigger candle should close in upper half
    # A pullback must be a real dip. Bars immediately after a pivot high always
    # close below it by construction, so depth -- not mere "closed below" -- is
    # what makes the setup meaningful.
    min_pullback_atr: float = 0.3
    max_extension_atr: float = 1.0    # don't chase far above the level
    min_stop_distance_atr: float = 0.25  # reject meaninglessly tight stops


DEFAULT_PARAMS = SetupParams()


@dataclass
class SetupCandidate:
    inst_id: str
    stage: Stage
    reason_codes: list[str]
    level: Decimal | None = None
    trigger_close: Decimal | None = None
    structural_stop: Decimal | None = None
    extension_atr: float | None = None
    episode_id: str | None = None
    # Values the checks were made against, for the decision card.
    evidence: dict[str, object] | None = None

    @property
    def is_candidate(self) -> bool:
        return self.stage is Stage.CONFIRMED


def find_pivot_high(
    candles: list[Candle], params: SetupParams, exclude_last: int = 1
) -> tuple[int, Decimal] | None:
    """Most recent confirmed pivot high among already-closed candles.

    A pivot at index i needs `pivot_right` closed bars after it, so it only
    becomes usable once those bars exist. `exclude_last` keeps the trigger bar
    itself out of level formation.
    """
    end = len(candles) - exclude_last
    lo = max(params.pivot_left, end - params.lookback)
    hi = end - params.pivot_right
    for i in range(hi - 1, lo - 1, -1):
        h = candles[i].high
        left = candles[i - params.pivot_left:i]
        right = candles[i + 1:i + 1 + params.pivot_right]
        if len(left) < params.pivot_left or len(right) < params.pivot_right:
            continue
        if all(h > c.high for c in left) and all(h > c.high for c in right):
            return i, h
    return None


def detect(
    inst_id: str,
    setup_candles: list[Candle],
    feats: FeatureSnapshot,
    params: SetupParams | None = None,
) -> SetupCandidate:
    """Evaluate the newest CLOSED setup candle for a reclaim entry."""
    params = params or DEFAULT_PARAMS
    codes: list[str] = []

    # --- gate 0: data quality ------------------------------------------------
    if not feats.is_valid:
        return SetupCandidate(inst_id, Stage.DATA_INVALID, list(feats.invalid_codes))
    if len(setup_candles) < params.lookback:
        return SetupCandidate(inst_id, Stage.DATA_INVALID, ["insufficient setup history"])
    if feats.atr is None or feats.atr <= 0:
        return SetupCandidate(inst_id, Stage.DATA_INVALID, ["atr unavailable"])

    trigger = setup_candles[-1]
    atr = feats.atr

    # --- gate 1: regime ------------------------------------------------------
    if not feats.above_ma:
        codes.append("REGIME_BELOW_MA")
    if feats.trend_slope_atr is None or feats.trend_slope_atr <= params.min_slope_atr:
        codes.append("REGIME_SLOPE_WEAK")
    if codes:
        return SetupCandidate(
            inst_id, Stage.REGIME_REJECTED, codes,
            evidence={"above_ma": feats.above_ma, "slope_atr": feats.trend_slope_atr},
        )

    # --- gate 2: level + pullback + reclaim ---------------------------------
    pivot = find_pivot_high(setup_candles, params)
    if pivot is None:
        return SetupCandidate(inst_id, Stage.NO_SETUP, ["NO_PIVOT_LEVEL"])
    pivot_idx, level = pivot

    after = setup_candles[pivot_idx + 1:-1]   # bars between the level and the trigger
    if not after:
        return SetupCandidate(inst_id, Stage.NO_SETUP, ["NO_BARS_AFTER_PIVOT"])

    if trigger.close <= level:
        return SetupCandidate(inst_id, Stage.NO_SETUP, ["NO_RECLAIM_CLOSE"])

    # Structural stop: below the pullback low. This is where the idea is wrong.
    pullback_low = min(c.low for c in after)
    structural_stop = pullback_low
    pullback_depth_atr = float((level - pullback_low) / atr)
    if pullback_depth_atr < params.min_pullback_atr:
        return SetupCandidate(
            inst_id, Stage.NO_SETUP, ["PULLBACK_TOO_SHALLOW"],
            evidence={"pullback_depth_atr": round(pullback_depth_atr, 3),
                      "min_pullback_atr": params.min_pullback_atr},
        )
    # Episode id ties repeats of the same setup together so the funnel cannot be
    # inflated by counting one opportunity once per bar.
    episode_id = f"{inst_id}:{setup_candles[pivot_idx].open_time.isoformat()}:{level}"

    extension_atr = float((trigger.close - level) / atr)
    stop_distance_atr = float((trigger.close - structural_stop) / atr)

    evidence = {
        "level": str(level),
        "trigger_close": str(trigger.close),
        "pullback_low": str(pullback_low),
        "pullback_depth_atr": round(pullback_depth_atr, 3),
        "extension_atr": round(extension_atr, 3),
        "stop_distance_atr": round(stop_distance_atr, 3),
        "rvol": feats.rvol,
        "flow_imbalance": feats.flow.imbalance if feats.flow else None,
        "close_position": feats.close_position,
        "bars_since_pivot": len(after) + 1,
    }
    base = dict(
        inst_id=inst_id, level=level, trigger_close=trigger.close,
        structural_stop=structural_stop, extension_atr=extension_atr,
        episode_id=episode_id, evidence=evidence,
    )

    if structural_stop >= trigger.close:
        return SetupCandidate(stage=Stage.NO_SETUP, reason_codes=["STOP_ABOVE_ENTRY"], **base)

    # --- gate 3: confirmation ------------------------------------------------
    if feats.rvol is None or feats.rvol < params.min_rvol:
        codes.append("RVOL_TOO_LOW")
    flow = feats.flow
    if flow is None or not flow.valid:
        codes.append("FLOW_UNAVAILABLE")
    elif flow.imbalance is None or flow.imbalance < params.min_flow_imbalance:
        codes.append("FLOW_NOT_BUY_DOMINANT")
    if feats.close_position is None or feats.close_position < params.min_close_position:
        codes.append("WEAK_CLOSE_POSITION")
    if codes:
        return SetupCandidate(stage=Stage.CONFIRM_REJECTED, reason_codes=codes, **base)

    # --- gate 4: don't chase, and require a meaningful stop ------------------
    if extension_atr > params.max_extension_atr:
        codes.append("TOO_EXTENDED")
    if stop_distance_atr < params.min_stop_distance_atr:
        codes.append("STOP_TOO_TIGHT")
    if codes:
        return SetupCandidate(stage=Stage.EXTENSION_REJECTED, reason_codes=codes, **base)

    return SetupCandidate(stage=Stage.CONFIRMED, reason_codes=["RECLAIM_CONFIRMED"], **base)
