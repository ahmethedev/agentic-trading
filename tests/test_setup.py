"""Setup-detection tests: funnel stages, no-lookahead, stop placement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from agentic_trade.features.compute import Candle, FeatureSnapshot, FlowFeature
from agentic_trade.strategy.setup import SetupParams, Stage, detect, find_pivot_high

T0 = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
P = SetupParams()


def mk(i: int, o, h, low, c, vq=1000) -> Candle:
    d = Decimal
    return Candle(T0 + timedelta(minutes=5 * i), d(str(o)), d(str(h)), d(str(low)),
                  d(str(c)), d("1"), d(str(vq)))


def good_feats(**over) -> FeatureSnapshot:
    base = dict(
        inst_id="TEST-USDT", computed_at=T0, candle_open_time=T0, close=Decimal("105"),
        close_position=0.8, rvol=2.0, atr=Decimal("2"), trend_slope_atr=0.05,
        above_ma=True,
        flow=FlowFeature(True, 0.4, Decimal("1000"), Decimal("400"), 120, 60.0),
        data_age_s=10.0, invalid_codes=[], invalid_reasons=[],
    )
    base.update(over)
    return FeatureSnapshot(**base)


def reclaim_series() -> list[Candle]:
    """Flat base, pivot high at index 30, pullback below it, then a reclaim close."""
    cs = [mk(i, 100, 101, 99, 100) for i in range(30)]
    cs.append(mk(30, 100, 110, 100, 109))          # 30: pivot high = 110
    cs += [mk(31 + j, 105, 106, 103, 104) for j in range(4)]   # pullback below 110
    cs.append(mk(35, 105, 112, 104, 111.5))        # trigger: closes above 110
    return cs


def test_pivot_is_found_and_excludes_trigger_bar():
    cs = reclaim_series()
    got = find_pivot_high(cs, P)
    assert got is not None
    idx, level = got
    assert idx == 30 and level == Decimal("110")


def test_pivot_requires_right_side_confirmation_no_lookahead():
    """A pivot must not be usable until its right-side bars have closed."""
    cs = reclaim_series()
    # Truncate so the pivot at 30 has only 1 closed bar to its right (needs 2),
    # plus a trigger bar that is excluded from level formation.
    truncated = cs[:33]
    got = find_pivot_high(truncated, P)
    assert got is None or got[0] != 30


def test_confirmed_candidate_and_stop_below_pullback_low():
    cs = reclaim_series()
    r = detect("TEST-USDT", cs, good_feats())
    assert r.stage is Stage.CONFIRMED, r.reason_codes
    assert r.level == Decimal("110")
    assert r.structural_stop == Decimal("103")      # lowest low of the pullback
    assert r.structural_stop < r.trigger_close
    assert r.episode_id


def test_no_reclaim_when_trigger_closes_below_level():
    cs = reclaim_series()
    cs[-1] = mk(35, 105, 109, 104, 108)             # never regains 110
    r = detect("TEST-USDT", cs, good_feats())
    assert r.stage is Stage.NO_SETUP
    assert "NO_RECLAIM_CLOSE" in r.reason_codes


def test_shallow_pullback_is_rejected():
    """A dip of only a few ticks below the level is not a pullback."""
    cs = [mk(i, 100, 101, 99, 100) for i in range(30)]
    cs.append(mk(30, 100, 110, 100, 109))
    # ATR is 2 in good_feats(); a 0.2 dip is 0.1 ATR, under min_pullback_atr=0.3
    cs += [mk(31 + j, 109.9, 109.95, 109.8, 109.9) for j in range(4)]
    cs.append(mk(35, 109.9, 112, 109.8, 111.5))
    r = detect("TEST-USDT", cs, good_feats())
    assert r.stage is Stage.NO_SETUP
    assert "PULLBACK_TOO_SHALLOW" in r.reason_codes


def test_deep_enough_pullback_is_accepted():
    r = detect("TEST-USDT", reclaim_series(), good_feats())
    assert r.stage is Stage.CONFIRMED
    assert r.evidence["pullback_depth_atr"] >= 0.3


def test_regime_gate_blocks_downtrend():
    r = detect("TEST-USDT", reclaim_series(), good_feats(above_ma=False))
    assert r.stage is Stage.REGIME_REJECTED
    assert "REGIME_BELOW_MA" in r.reason_codes


def test_missing_flow_is_not_treated_as_neutral():
    """Absent order flow must reject, never pass as zero imbalance."""
    dead = FlowFeature(False, None, Decimal(0), Decimal(0), 0, 0.0, "no trades")
    r = detect("TEST-USDT", reclaim_series(), good_feats(flow=dead))
    assert r.stage is Stage.CONFIRM_REJECTED
    assert "FLOW_UNAVAILABLE" in r.reason_codes


def test_low_rvol_rejected_at_confirmation():
    r = detect("TEST-USDT", reclaim_series(), good_feats(rvol=0.4))
    assert r.stage is Stage.CONFIRM_REJECTED
    assert "RVOL_TOO_LOW" in r.reason_codes


def test_too_extended_is_not_chased():
    # ATR tiny -> the same reclaim distance becomes many ATRs above the level.
    r = detect("TEST-USDT", reclaim_series(), good_feats(atr=Decimal("0.5")))
    assert r.stage is Stage.EXTENSION_REJECTED
    assert "TOO_EXTENDED" in r.reason_codes


def test_invalid_data_short_circuits_before_strategy():
    f = good_feats(invalid_codes=["FLOW_INVALID"],
                   invalid_reasons=["flow invalid: stale"])
    r = detect("TEST-USDT", reclaim_series(), f)
    assert r.stage is Stage.DATA_INVALID
    # reason codes stay machine-readable; prose never becomes a "code"
    assert r.reason_codes == ["FLOW_INVALID"]


def test_episode_id_is_stable_across_repeat_bars():
    """The same setup seen on consecutive bars must reuse one episode id."""
    cs = reclaim_series()
    first = detect("TEST-USDT", cs, good_feats())
    cs2 = cs + [mk(36, 111.5, 113, 111, 112.5)]
    second = detect("TEST-USDT", cs2, good_feats())
    assert first.episode_id == second.episode_id
