"""
Tests for the multi-timeframe regime classifier (pure logic).
Covers lane scoring, intraday blend, context classification, per-direction
mode mapping, tf_alignment, and the assembled build_multi_tf output — including
the operator's exact scenario (daily uptrend + intraday selloff = PULLBACK).
"""
from services.multi_tf_regime import (
    score_long_lane, score_intraday_lane, blend_intraday, classify_context,
    mode_for_direction, tf_alignment, lane_bias, build_multi_tf,
    weighted_blend, score_internals, combine_internals,
    apply_internals_adjustment, index_divergence,
)


def _ramp(start, step, n, vol=1000):
    """n bars trending by `step` each bar (uptrend if +, downtrend if -)."""
    bars = []
    px = start
    for _ in range(n):
        o = px
        c = px + step
        hi = max(o, c) + abs(step) * 0.2
        lo = min(o, c) - abs(step) * 0.2
        bars.append({"open": o, "high": hi, "low": lo, "close": c, "volume": vol})
        px = c
    return bars


# --- lane_bias --------------------------------------------------------------
def test_lane_bias_thresholds():
    assert lane_bias(75) == "UP"
    assert lane_bias(60) == "UP"
    assert lane_bias(50) == "NEUTRAL"
    assert lane_bias(40) == "DOWN"
    assert lane_bias(None) == "UNKNOWN"


# --- long lane (daily, 20 SMA) ----------------------------------------------
def test_long_lane_uptrend_scores_high():
    bars = _ramp(100, 0.5, 220)  # steady daily uptrend, > 200 bars
    s = score_long_lane(bars)
    assert s is not None and s >= 70, s
    assert lane_bias(s) == "UP"


def test_long_lane_downtrend_scores_low():
    bars = _ramp(200, -0.5, 220)
    s = score_long_lane(bars)
    assert s is not None and s <= 40, s
    assert lane_bias(s) == "DOWN"


def test_long_lane_insufficient_bars_returns_none():
    assert score_long_lane(_ramp(100, 0.5, 10)) is None


# --- intraday lanes (EMA 9/21) ----------------------------------------------
def test_intraday_lane_uptrend_and_downtrend():
    up = score_intraday_lane(_ramp(100, 0.3, 60), fast=9, slow=21)
    dn = score_intraday_lane(_ramp(100, -0.3, 60), fast=9, slow=21)
    assert lane_bias(up) == "UP"
    assert lane_bias(dn) == "DOWN"


def test_intraday_lane_insufficient_returns_none():
    assert score_intraday_lane(_ramp(100, 0.3, 10), slow=21) is None


def test_intraday_lane_vwap_uptrend_and_downtrend():
    # With VWAP enabled (short/micro spec), a rising tape ends above its
    # rolling VWAP -> UP; a falling tape ends below -> DOWN.
    up = score_intraday_lane(_ramp(100, 0.3, 60), fast=9, slow=21, use_vwap=True)
    dn = score_intraday_lane(_ramp(100, -0.3, 60), fast=9, slow=21, use_vwap=True)
    assert lane_bias(up) == "UP"
    assert lane_bias(dn) == "DOWN"


# --- intraday blend ---------------------------------------------------------
def test_blend_intraday_weights_and_renorm():
    # mid 0.5, short 0.3, micro 0.2
    assert blend_intraday(80, 80, 80) == 80.0
    # micro missing -> renormalize over mid+short
    b = blend_intraday(60, 40, None)
    assert b == round((60 * 0.5 + 40 * 0.3) / 0.8, 1)
    assert blend_intraday(None, None, None) is None


# --- context classification -------------------------------------------------
def test_classify_all_contexts():
    assert classify_context(70, 70) == "ALIGNED_UP"
    assert classify_context(25, 25) == "ALIGNED_DOWN"
    assert classify_context(70, 30) == "PULLBACK_IN_UPTREND"   # operator's tape
    assert classify_context(30, 70) == "BOUNCE_IN_DOWNTREND"
    assert classify_context(50, 50) == "MIXED"
    assert classify_context(None, 70) == "UNKNOWN"
    # no intraday read -> fall back to anchor
    assert classify_context(70, None) == "ALIGNED_UP"
    assert classify_context(25, None) == "ALIGNED_DOWN"


# --- per-direction mode mapping ---------------------------------------------
def test_mode_for_direction_full_table():
    # ALIGNED_UP: strong long -> aggressive, short -> defensive
    assert mode_for_direction("ALIGNED_UP", "long", 75) == "aggressive"
    assert mode_for_direction("ALIGNED_UP", "long", 62) == "normal"
    assert mode_for_direction("ALIGNED_UP", "short", 75) == "defensive"
    # PULLBACK: long normal (buy dip), short cautious
    assert mode_for_direction("PULLBACK_IN_UPTREND", "long", 68) == "normal"
    assert mode_for_direction("PULLBACK_IN_UPTREND", "short", 68) == "cautious"
    # BOUNCE: long cautious, short normal
    assert mode_for_direction("BOUNCE_IN_DOWNTREND", "long", 30) == "cautious"
    assert mode_for_direction("BOUNCE_IN_DOWNTREND", "short", 30) == "normal"
    # ALIGNED_DOWN: strong short -> aggressive, long -> defensive
    assert mode_for_direction("ALIGNED_DOWN", "short", 25) == "aggressive"
    assert mode_for_direction("ALIGNED_DOWN", "short", 38) == "normal"
    assert mode_for_direction("ALIGNED_DOWN", "long", 25) == "defensive"
    # MIXED -> cautious both
    assert mode_for_direction("MIXED", "long", 50) == "cautious"
    assert mode_for_direction("MIXED", "short", 50) == "cautious"


# --- tf_alignment -----------------------------------------------------------
def test_tf_alignment_counts():
    a = tf_alignment([70, 65, 30, 25])  # 2 up, 2 down
    assert a["lanes_counted"] == 4
    assert a["up"] == 2 and a["down"] == 2
    b = tf_alignment([70, 65, 62, 25])  # 3 up dominant
    assert b["dominant"] == "UP" and b["ratio"] == 0.75
    c = tf_alignment([None, None, None, None])
    assert c["dominant"] == "UNKNOWN"


# --- assembled output: operator's exact scenario ----------------------------
def test_build_multi_tf_pullback_scenario():
    """Daily UP (67.8), intraday all DOWN — must be PULLBACK with long=normal."""
    out = build_multi_tf(long_score=67.8, mid_score=41, short_score=30, micro_score=25)
    assert out["context"] == "PULLBACK_IN_UPTREND"
    assert out["intraday_bias"] == "DOWN"
    assert out["modes"]["long"] == "normal"   # buy-the-dip, NOT cautious
    assert out["modes"]["short"] == "cautious"
    assert out["lanes"]["long"]["bias"] == "UP"
    assert "buy the dip" in out["recommendation"].lower()


def test_build_multi_tf_aligned_down_favors_shorts():
    out = build_multi_tf(long_score=28, mid_score=30, short_score=25, micro_score=20)
    assert out["context"] == "ALIGNED_DOWN"
    assert out["modes"]["short"] == "aggressive"
    assert out["modes"]["long"] == "defensive"


# ---------------------------------------------------------------------------
# v316d — multi-index blend + TICK internals + divergence
# ---------------------------------------------------------------------------
def _tick_bars(level, n=30, hi=None, lo=None):
    """n 1-min TICK bars centered near `level`; optional extreme hi/lo on last bar."""
    bars = [{"open": level, "high": level + 80, "low": level - 80,
             "close": level, "volume": 0} for _ in range(n)]
    if hi is not None:
        bars[-1]["high"] = hi
    if lo is not None:
        bars[-1]["low"] = lo
    return bars


def test_weighted_blend_renormalizes():
    assert weighted_blend({"SPY": 60, "QQQ": 40, "IWM": 50}, {"SPY": 0.5, "QQQ": 0.3, "IWM": 0.2}) == 52.0
    # QQQ missing -> renormalize over SPY+IWM
    assert weighted_blend({"SPY": 60, "QQQ": None, "IWM": 50}, {"SPY": 0.5, "QQQ": 0.3, "IWM": 0.2}) == round((60*0.5+50*0.2)/0.7, 1)
    assert weighted_blend({"SPY": None}, {"SPY": 0.5}) is None


def test_score_internals_bias_and_climax():
    up = score_internals(_tick_bars(400), "NYSE")
    dn = score_internals(_tick_bars(-400), "NYSE")
    assert up["bias"] == "UP" and dn["bias"] == "DOWN"
    # NYSE buy climax at +1000 on the recent window
    clim = score_internals(_tick_bars(100, hi=1050), "NYSE")
    assert clim["climax"] and clim["climax_dir"] == "BUY_CLIMAX"
    # Nasdaq needs +/-1200; +1050 should NOT trip on NASD
    nq = score_internals(_tick_bars(100, hi=1050), "NASD")
    assert not nq["climax"]


def test_combine_internals_weights_nyse_heavier():
    nyse = score_internals(_tick_bars(400), "NYSE")   # UP
    nasd = score_internals(_tick_bars(-400), "NASD")  # DOWN
    c = combine_internals(nyse, nasd)
    # 0.7*~100 + 0.3*~0 -> leans UP
    assert c["score"] > 55 and c["bias"] == "UP"


def test_apply_internals_contradict_pulls_to_neutral():
    # price bearish (30) but internals bullish -> pull UP toward neutral
    up_int = {"score": 90}
    adj = apply_internals_adjustment(30.0, up_int)
    assert adj > 30.0
    # price bullish (70) but internals bearish -> pull DOWN
    dn_int = {"score": 10}
    adj2 = apply_internals_adjustment(70.0, dn_int)
    assert adj2 < 70.0
    # agreement -> mild reinforcement (bearish + bearish -> slightly lower)
    adj3 = apply_internals_adjustment(30.0, {"score": 10})
    assert adj3 <= 30.0


def test_index_divergence_flags():
    assert "TECH_WEAK" in index_divergence(60, 40, 58)       # QQQ << SPY
    assert "SMALLCAP_WEAK" in index_divergence(60, 58, 40)   # IWM << SPY
    assert "TECH_STRONG" in index_divergence(40, 60, 42)
    assert index_divergence(50, 50, 50) == []


def test_build_multi_tf_internals_contradict_softens_pullback():
    # Daily UP, intraday DOWN, but internals strongly UP (selloff not broad).
    internals = {"score": 95, "bias": "UP", "climax": False, "climax_dir": None}
    out = build_multi_tf(67.0, 41, 30, 25, internals=internals,
                         divergence=["TECH_WEAK"])
    assert out["intraday_score"] > out["intraday_score_raw"]  # pulled toward neutral
    assert out["internals"]["score"] == 95
    assert out["divergence"] == ["TECH_WEAK"]


def test_build_multi_tf_buy_climax_caps_aggressive_long():
    # Strong aligned-up (long would be aggressive) + buy climax -> capped to normal.
    internals = {"score": 80, "bias": "UP", "climax": True, "climax_dir": "BUY_CLIMAX"}
    out = build_multi_tf(85, 80, 78, 75, internals=internals)
    assert out["context"] == "ALIGNED_UP"
    assert out["modes"]["long"] == "normal"   # capped from aggressive
    assert out["caution"] and "climax" in out["caution"].lower()
