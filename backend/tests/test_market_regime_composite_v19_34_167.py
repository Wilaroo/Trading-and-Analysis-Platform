"""v19.34.167 — composite SPY/QQQ/IWM market regime classifier tests.

Rebuilds `_update_market_context` to vote across the three broad indexes
instead of using SPY in isolation. Tests cover:
  - Unanimous up / unanimous down / unanimous up + overbought
  - Majority up (small-cap divergence) → MOMENTUM (not STRONG_UPTREND)
  - Majority down → FADE (not STRONG_DOWNTREND)
  - VOLATILE wins over trend when any index > 2% daily range
  - Single-index degraded mode replays v166 logic
  - Metadata: agreement label, divergence flag, per-index breakdown,
    no spurious key explosions
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ── Minimal fake snapshot — mirrors only the fields the classifier reads
@dataclass
class FakeSnap:
    symbol: str
    trend: str = "sideways"
    above_vwap: bool = True
    above_ema9: bool = True
    rsi_14: float = 50.0
    daily_range_pct: float = 0.5
    dist_from_vwap: float = 0.1


def _classifier():
    """Return the bound classifier method. We construct the scanner via
    __new__ so we skip its full __init__ (which talks to IB / Mongo /
    threads). The classifier is a pure method, no I/O."""
    from services.enhanced_scanner import EnhancedBackgroundScanner
    inst = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    return inst._classify_market_regime


def _regime():
    from services.enhanced_scanner import MarketRegime
    return MarketRegime


# ─────────────────────────────────────────────────────────────────────
# Unanimous scenarios
# ─────────────────────────────────────────────────────────────────────
def test_unanimous_uptrend_clean_rsi_returns_strong_uptrend():
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=55)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=58)
    iwm = FakeSnap("IWM", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=53)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.STRONG_UPTREND, f"got {regime}"
    assert meta["index_agreement"] == "unanimous_up"
    assert meta["divergence_flag"] is False
    assert meta["uptrend_votes"] == 3
    assert meta["indices_valid"] == 3


def test_unanimous_up_with_overbought_spy_returns_momentum():
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=72)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=65)
    iwm = FakeSnap("IWM", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=68)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.MOMENTUM, f"got {regime}"
    assert meta["index_agreement"] == "unanimous_up"


def test_unanimous_downtrend_returns_strong_downtrend():
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=35)
    qqq = FakeSnap("QQQ", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=32)
    iwm = FakeSnap("IWM", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=28)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.STRONG_DOWNTREND, f"got {regime}"
    assert meta["index_agreement"] == "unanimous_down"
    assert meta["divergence_flag"] is False


# ─────────────────────────────────────────────────────────────────────
# Majority (divergence) scenarios — the whole point of v167
# ─────────────────────────────────────────────────────────────────────
def test_smallcap_divergence_downgrades_strong_uptrend_to_momentum():
    """SPY + QQQ uptrend but IWM downtrending → MOMENTUM, not STRONG_UPTREND."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=55)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=58)
    iwm = FakeSnap("IWM", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=38)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.MOMENTUM, f"got {regime}"
    assert meta["index_agreement"] == "majority_up"
    assert meta["divergence_flag"] is True
    assert meta["uptrend_votes"] == 2
    assert meta["downtrend_votes"] == 1


def test_techcap_divergence_majority_down_returns_fade():
    """SPY + IWM downtrend but QQQ holding → FADE (degraded conviction)."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=38)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=55)
    iwm = FakeSnap("IWM", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=32)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.FADE, f"got {regime}"
    assert meta["index_agreement"] == "majority_down"
    assert meta["divergence_flag"] is True


def test_one_each_no_majority_returns_range_bound():
    """1 up, 1 down, 1 sideways — no majority → RANGE_BOUND."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=55, dist_from_vwap=0.2)
    qqq = FakeSnap("QQQ", trend="downtrend", above_vwap=False, above_ema9=False, rsi_14=42)
    iwm = FakeSnap("IWM", trend="sideways", above_vwap=True, above_ema9=False, rsi_14=50)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.RANGE_BOUND, f"got {regime}"
    assert meta["index_agreement"] == "mixed"
    assert meta["divergence_flag"] is True


# ─────────────────────────────────────────────────────────────────────
# Volatility dominates
# ─────────────────────────────────────────────────────────────────────
def test_volatile_iwm_overrides_unanimous_uptrend():
    """Even if SPY+QQQ+IWM all uptrend, if IWM daily_range > 2% → VOLATILE."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=0.6)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=0.7)
    iwm = FakeSnap("IWM", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=2.4)
    regime, meta = classify(spy, qqq, iwm)
    assert regime == R.VOLATILE, f"got {regime}"
    assert meta["max_daily_range_pct"] == 2.4


def test_at_2pct_boundary_not_volatile():
    """daily_range exactly 2.0% should NOT trigger VOLATILE (strict >)."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=2.0)
    qqq = FakeSnap("QQQ", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=2.0)
    iwm = FakeSnap("IWM", trend="uptrend", above_vwap=True, above_ema9=True, daily_range_pct=2.0)
    regime, meta = classify(spy, qqq, iwm)
    assert regime != R.VOLATILE, f"got {regime}"


# ─────────────────────────────────────────────────────────────────────
# Single-index degraded mode — v166 fallback parity
# ─────────────────────────────────────────────────────────────────────
def test_qqq_iwm_unavailable_falls_back_to_spy_only_uptrend():
    """If only SPY is available, must replay v166 single-index logic."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=55)
    regime, meta = classify(spy, None, None)
    assert regime == R.STRONG_UPTREND
    assert meta["indices_valid"] == 1
    assert meta["per_index"]["qqq"] is None
    assert meta["per_index"]["iwm"] is None


def test_qqq_iwm_unavailable_overbought_falls_back_to_momentum():
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="uptrend", above_vwap=True, above_ema9=True, rsi_14=72)
    regime, _ = classify(spy, None, None)
    assert regime == R.MOMENTUM


def test_qqq_iwm_unavailable_quiet_extreme_rsi_returns_fade():
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="sideways", above_vwap=True, above_ema9=True,
                   rsi_14=70, dist_from_vwap=0.2, daily_range_pct=0.5)
    regime, _ = classify(spy, None, None)
    assert regime == R.FADE


# ─────────────────────────────────────────────────────────────────────
# Metadata sanity
# ─────────────────────────────────────────────────────────────────────
def test_metadata_per_index_has_all_three_keys_even_when_some_none():
    classify = _classifier()
    spy = FakeSnap("SPY", trend="uptrend", rsi_14=55)
    qqq = FakeSnap("QQQ", trend="uptrend", rsi_14=58)
    _, meta = classify(spy, qqq, None)
    assert set(meta["per_index"].keys()) == {"spy", "qqq", "iwm"}
    assert meta["per_index"]["iwm"] is None
    assert meta["per_index"]["spy"]["trend"] == "uptrend"


def test_metadata_no_data_returns_range_bound_with_error_marker():
    classify = _classifier()
    R = _regime()
    regime, meta = classify(None, None, None)
    assert regime == R.RANGE_BOUND
    assert "error" in meta


# ─────────────────────────────────────────────────────────────────────
# Regression — the v166 SPY case must STILL classify as sideways and
# the composite must not flip it to STRONG_DOWNTREND.
# ─────────────────────────────────────────────────────────────────────
def test_v166_audit_case_still_not_downtrend_under_v167():
    """SPY at 749.19 hugging EMAs in macro uptrend, QQQ same, IWM weak.
    Per v167: 2/3 sideways + 1/3 down → not unanimous down, not majority
    down — should be RANGE_BOUND, NEVER STRONG_DOWNTREND."""
    classify = _classifier()
    R = _regime()
    spy = FakeSnap("SPY", trend="sideways", above_vwap=False, above_ema9=False,
                   rsi_14=48, dist_from_vwap=-0.14, daily_range_pct=0.5)
    qqq = FakeSnap("QQQ", trend="sideways", above_vwap=False, above_ema9=False,
                   rsi_14=46, dist_from_vwap=-0.12, daily_range_pct=0.7)
    iwm = FakeSnap("IWM", trend="downtrend", above_vwap=False, above_ema9=False,
                   rsi_14=38, dist_from_vwap=-0.4, daily_range_pct=0.9)
    regime, _ = classify(spy, qqq, iwm)
    assert regime != R.STRONG_DOWNTREND, f"got {regime}"
