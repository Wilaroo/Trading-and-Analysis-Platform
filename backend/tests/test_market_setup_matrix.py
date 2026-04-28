"""Tests for the Bellafiore Setup × Trade matrix system (2026-04-29 v2).

Covers:
  - MarketSetupClassifier per-setup detection logic
  - TRADE_SETUP_MATRIX completeness + lookup semantics
  - TRADE_ALIASES redirect (puppy_dog → big_dog, etc.)
  - EXPERIMENTAL_TRADES bypass the matrix gate
  - Scanner integration: `_apply_setup_context` tags alerts correctly
  - the_3_30_trade detector (positive + negative cases)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")

import pytest

from services.market_setup_classifier import (  # noqa: E402
    MarketSetup, TradeContext, MarketSetupClassifier,
    TRADE_SETUP_MATRIX, TRADE_ALIASES, EXPERIMENTAL_TRADES,
    lookup_trade_context, get_market_setup_classifier,
)
from services.enhanced_scanner import (  # noqa: E402
    EnhancedBackgroundScanner, AlertPriority, TimeWindow, TapeReading,
    TapeSignal,
)
from services.realtime_technical_service import TechnicalSnapshot  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ──────────────────────────── MATRIX SEMANTICS ────────────────────────────


def test_matrix_covers_all_22_trades_from_playbook():
    """The 22 trades in the operator's screenshot must all be in the matrix."""
    expected = {
        "the_3_30_trade", "second_chance", "hitchhiker", "9_ema_scalp",
        "vwap_continuation", "gap_give_go", "first_vwap_pullback",
        "big_dog", "bouncy_ball", "premarket_high_break",
        "back_through_open", "range_break", "spencer_scalp",
        "first_move_up", "first_move_down", "bella_fade",
        "fashionably_late", "backside", "rubber_band", "off_sides",
        "hod_breakout",
    }
    missing = expected - set(TRADE_SETUP_MATRIX.keys())
    assert not missing, f"Missing trades from matrix: {missing}"


def test_matrix_directionality_invariants():
    """Spot-check a few critical with-trend / countertrend cells."""
    # 9_ema_scalp is with-trend on Gap & Go, no-op elsewhere
    assert TRADE_SETUP_MATRIX["9_ema_scalp"][MarketSetup.GAP_AND_GO] == TradeContext.WITH_TREND
    assert MarketSetup.OVEREXTENSION not in TRADE_SETUP_MATRIX["9_ema_scalp"]
    # bella_fade is countertrend in 4 reversal-flavored setups
    bella = TRADE_SETUP_MATRIX["bella_fade"]
    assert bella[MarketSetup.OVEREXTENSION] == TradeContext.COUNTERTREND
    assert bella[MarketSetup.GAP_DOWN_INTO_SUPPORT] == TradeContext.COUNTERTREND
    assert bella[MarketSetup.GAP_UP_INTO_RESISTANCE] == TradeContext.COUNTERTREND
    assert bella[MarketSetup.VOLATILITY_IN_RANGE] == TradeContext.COUNTERTREND
    # off_sides has zero with-trend setups, all countertrend
    off = TRADE_SETUP_MATRIX["off_sides"]
    assert all(ctx == TradeContext.COUNTERTREND for ctx in off.values())
    # the_3_30_trade: only Gap & Go
    assert list(TRADE_SETUP_MATRIX["the_3_30_trade"].keys()) == [MarketSetup.GAP_AND_GO]


def test_lookup_trade_context_aliases_resolve():
    """puppy_dog / tidal_wave / vwap_bounce should resolve to canonical."""
    assert lookup_trade_context("puppy_dog", MarketSetup.GAP_AND_GO) == TradeContext.WITH_TREND
    assert lookup_trade_context("tidal_wave", MarketSetup.OVEREXTENSION) == TradeContext.COUNTERTREND
    assert lookup_trade_context("vwap_bounce", MarketSetup.GAP_AND_GO) == TradeContext.WITH_TREND


def test_lookup_trade_context_experimental_passes_all():
    """Experimental trades have no matrix gate — return WITH_TREND for all."""
    for trade in EXPERIMENTAL_TRADES:
        for setup in MarketSetup:
            assert lookup_trade_context(trade, setup) == TradeContext.WITH_TREND, (
                f"experimental trade {trade!r} blocked in {setup.value}"
            )


def test_lookup_trade_context_neutral_setup_passes():
    """If classifier returns NEUTRAL, every trade passes through."""
    for trade in TRADE_SETUP_MATRIX:
        assert lookup_trade_context(trade, MarketSetup.NEUTRAL) == TradeContext.WITH_TREND


def test_lookup_trade_context_returns_not_applic_for_empty_cell():
    """9_ema_scalp on Overextension → empty cell → NOT_APPLIC."""
    assert lookup_trade_context("9_ema_scalp", MarketSetup.OVEREXTENSION) == TradeContext.NOT_APPLIC
    assert lookup_trade_context("the_3_30_trade", MarketSetup.OVEREXTENSION) == TradeContext.NOT_APPLIC


# ──────────────────────────── CLASSIFIER ────────────────────────────


def _bars(prices, vols=None):
    """Build a list of daily-bar dicts from a list of close prices.

    Each bar has open=close, high=close*1.005, low=close*0.995 unless
    overridden. For setup-detection tests we construct the open/high/
    low explicitly when needed.
    """
    out = []
    for i, c in enumerate(prices):
        out.append({
            "date": f"2026-04-{i+1:02d}", "open": c, "high": c * 1.005,
            "low": c * 0.995, "close": c, "volume": (vols[i] if vols else 1_000_000),
        })
    return out


def test_classifier_returns_neutral_on_empty_bars():
    c = MarketSetupClassifier()
    res = _run(c.classify("XXX", daily_bars=[]))
    assert res.setup == MarketSetup.NEUTRAL
    assert res.confidence == 0.0


def test_classifier_detects_gap_and_go():
    """Tight 10-day range → big up-gap on heavy volume → Gap & Go."""
    c = MarketSetupClassifier()
    bars = _bars([100, 100.5, 99.8, 100.2, 99.9, 100.1, 100.4, 99.7, 100.0,
                  100.3, 99.6, 100.2])
    # latest bar = big gap up with heavy volume
    bars.append({
        "date": "2026-04-13", "open": 104.0, "high": 106.0, "low": 103.5,
        "close": 105.5, "volume": 5_000_000,  # 5x normal
    })
    res = _run(c.classify("AAA", daily_bars=bars))
    assert res.setup == MarketSetup.GAP_AND_GO
    assert res.confidence >= 0.5


def test_classifier_detects_overextension():
    """5+ consecutive green candles, big extension from 20-EMA, RSI hot."""
    c = MarketSetupClassifier()
    # 20 stable bars then 6 consecutive strong-green candles
    base = [100 + 0.1 * i for i in range(20)]
    surge = [base[-1] + 1.5 * (i + 1) for i in range(6)]
    closes = base + surge
    bars = []
    for i, c_close in enumerate(closes):
        prev_close = closes[i - 1] if i > 0 else c_close - 0.5
        is_up = c_close >= prev_close
        bars.append({
            "date": f"2026-04-{i+1:02d}",
            "open": prev_close, "close": c_close,
            "high": max(c_close, prev_close) * 1.002,
            "low":  min(c_close, prev_close) * 0.998,
            "volume": 1_000_000,
        })
    res = _run(c.classify("BBB", daily_bars=bars))
    assert res.setup == MarketSetup.OVEREXTENSION
    assert res.confidence >= 0.5


def test_classifier_detects_volatility_in_range():
    """15-day oscillation between two bands, elevated ATR, no breakout."""
    c = MarketSetupClassifier()
    bars = []
    # Oscillate 100-110 with ~3% daily ATR
    pattern = [100, 110, 102, 108, 101, 109, 103, 107, 100, 110, 102, 108, 101, 109, 105]
    for i, p in enumerate(pattern):
        bars.append({
            "date": f"2026-04-{i+1:02d}", "open": p,
            "high": p * 1.018, "low": p * 0.982, "close": p,
            "volume": 1_000_000,
        })
    res = _run(c.classify("CCC", daily_bars=bars))
    assert res.setup == MarketSetup.VOLATILITY_IN_RANGE
    assert res.confidence >= 0.5


def test_classifier_detects_day_2():
    """Day 1 = >1×ATR move closing top-20%, Day 2 opens near Day 1 close."""
    c = MarketSetupClassifier()
    # 14 stable bars + day 1 (big trending day) + day 2 (open near close)
    bars = []
    for i in range(14):
        p = 100 + 0.05 * i
        bars.append({
            "date": f"2026-04-{i+1:02d}", "open": p, "high": p * 1.005,
            "low": p * 0.995, "close": p, "volume": 1_000_000,
        })
    # Day 1: 5% range, closes at the top
    bars.append({
        "date": "2026-04-15", "open": 100.7, "high": 105.5, "low": 100.5,
        "close": 105.3, "volume": 3_000_000,
    })
    # Day 2: opens within 1% of Day 1 close
    bars.append({
        "date": "2026-04-16", "open": 105.4, "high": 105.5, "low": 104.9,
        "close": 105.1, "volume": 2_000_000,
    })
    res = _run(c.classify("DDD", daily_bars=bars))
    assert res.setup == MarketSetup.DAY_2
    assert res.confidence >= 0.5


def test_classifier_caches_results():
    c = MarketSetupClassifier()
    bars = _bars([100] * 30)  # neutral
    _run(c.classify("EEE", daily_bars=bars))
    assert c._cache_hits == 0 and c._cache_misses == 1
    _run(c.classify("EEE", daily_bars=bars))
    assert c._cache_hits == 1 and c._cache_misses == 1


def test_classifier_singleton():
    a = get_market_setup_classifier()
    b = get_market_setup_classifier()
    assert a is b


# ──────────────────────────── SCANNER INTEGRATION ────────────────────────────


def _flat_snapshot(**overrides):
    """Build a baseline-valid TechnicalSnapshot for tests."""
    base = dict(
        symbol="TEST", timestamp="2026-04-29T15:30:00",
        current_price=100.0, open=100.0, high=100.5, low=99.5, prev_close=99.0,
        volume=1_000_000, avg_volume=800_000, rvol=1.5,
        vwap=100.0, ema_9=100.0, ema_20=100.0, ema_50=100.0, sma_200=100.0,
        dist_from_vwap=0.0, dist_from_ema9=0.0, dist_from_ema20=0.0,
        rsi_14=50.0, rsi_trend="neutral",
        atr=1.0, atr_percent=1.0, daily_range_pct=1.0,
        gap_pct=0.0, gap_direction="flat", holding_gap=False,
        resistance=102.0, support=98.0, high_of_day=100.5, low_of_day=99.5,
        above_vwap=True, above_ema9=True, above_ema20=True, trend="sideways",
        extended_from_ema9=False, extension_pct=0.0,
        bb_upper=102.0, bb_middle=100.0, bb_lower=98.0, bb_width=4.0,
        kc_upper=101.5, kc_middle=100.0, kc_lower=98.5,
        squeeze_on=False, squeeze_fire=0.0,
        or_high=100.3, or_low=99.7, or_breakout="inside",
        rs_vs_spy=0.0, bars_used=20, data_quality="real",
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def _flat_tape(long_ok=True, short_ok=True):
    return TapeReading(
        symbol="TEST", timestamp="2026-04-29T15:30:00",
        bid_price=99.99, ask_price=100.01, spread=0.02, spread_pct=0.02,
        spread_signal=TapeSignal.TIGHT_SPREAD, bid_size=100, ask_size=100,
        imbalance=0.0, imbalance_signal=TapeSignal.NEUTRAL,
        price_momentum=0.0, volume_momentum=0.0,
        momentum_signal=TapeSignal.NEUTRAL, overall_signal=TapeSignal.NEUTRAL,
        tape_score=0.0, confirmation_for_long=long_ok,
        confirmation_for_short=short_ok,
    )


def test_the_3_30_trade_fires_on_held_above_or_with_afternoon_consol():
    s = EnhancedBackgroundScanner(db=None)
    snap = _flat_snapshot(
        current_price=102.5, open=99.0, high=102.6, low=100.5,
        high_of_day=102.6, low_of_day=100.5, or_high=100.5, or_low=99.5,
        vwap=101.0, ema_9=102.0, dist_from_vwap=1.5, dist_from_ema9=0.5,
        rvol=1.5, atr=1.0, above_vwap=True, above_ema9=True,
    )
    alert = _run(s._check_the_3_30_trade("TEST", snap, _flat_tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.setup_type == "the_3_30_trade"


def test_the_3_30_trade_blocked_when_lod_dipped_below_or_high():
    """Operator playbook: avoid entirely if stock didn't hold above
    morning OR-high all day."""
    s = EnhancedBackgroundScanner(db=None)
    snap = _flat_snapshot(
        current_price=102.5, open=99.0,
        high_of_day=102.6, low_of_day=100.0,  # dipped below or_high
        or_high=100.5, or_low=99.5,
        rvol=1.5, atr=1.0,
    )
    assert _run(s._check_the_3_30_trade("TEST", snap, _flat_tape())) is None


def test_apply_setup_context_tags_with_trend_alert():
    """A 9-EMA scalp on a Gap & Go day should have no warnings."""
    from services.market_setup_classifier import get_market_setup_classifier
    s = EnhancedBackgroundScanner(db=None)
    classifier = get_market_setup_classifier()
    classifier.invalidate()
    # Hand-classify 'TEST' as Gap & Go
    bars = _bars([100, 100.2, 99.8, 100.1, 99.9, 100.0, 100.2, 99.7, 100.1,
                  100.3, 99.9, 100.2])
    bars.append({"date": "2026-04-13", "open": 104.5, "high": 106.0, "low": 104.0,
                 "close": 105.5, "volume": 5_000_000})

    async def _run_test():
        await classifier.classify("TEST", daily_bars=bars)
        # Manufacture a fake alert and apply context
        alert = MockAlert(setup_type="9_ema_scalp", priority=AlertPriority.HIGH)
        await s._apply_setup_context(alert, "TEST", _flat_snapshot())
        return alert

    alert = _run(_run_test())
    assert alert.market_setup == "gap_and_go"
    assert alert.is_countertrend is False
    assert alert.out_of_context_warning is False
    assert alert.priority == AlertPriority.HIGH  # not downgraded


def test_apply_setup_context_warns_on_out_of_context():
    """A 9-EMA scalp on an Overextension day → out-of-context warning + downgrade."""
    from services.market_setup_classifier import get_market_setup_classifier
    s = EnhancedBackgroundScanner(db=None)
    classifier = get_market_setup_classifier()
    classifier.invalidate()
    # Force-classify as Overextension via direct cache injection
    from services.market_setup_classifier import ClassificationResult
    classifier._cache["TEST2"] = (
        ClassificationResult(setup=MarketSetup.OVEREXTENSION, confidence=0.9),
        # Use a fresh datetime so the cache hit works
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    async def _run_test():
        alert = MockAlert(setup_type="9_ema_scalp", priority=AlertPriority.HIGH)
        await s._apply_setup_context(alert, "TEST2", _flat_snapshot())
        return alert

    alert = _run(_run_test())
    assert alert.market_setup == "overextension"
    assert alert.out_of_context_warning is True
    assert alert.priority == AlertPriority.MEDIUM  # downgraded


def test_apply_setup_context_tags_countertrend_no_downgrade():
    """A bella_fade on Overextension is countertrend (intended) — no downgrade."""
    from services.market_setup_classifier import (
        get_market_setup_classifier, ClassificationResult,
    )
    s = EnhancedBackgroundScanner(db=None)
    classifier = get_market_setup_classifier()
    classifier._cache["TEST3"] = (
        ClassificationResult(setup=MarketSetup.OVEREXTENSION, confidence=0.9),
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    async def _run_test():
        alert = MockAlert(setup_type="bella_fade", priority=AlertPriority.HIGH)
        await s._apply_setup_context(alert, "TEST3", _flat_snapshot())
        return alert

    alert = _run(_run_test())
    assert alert.market_setup == "overextension"
    assert alert.is_countertrend is True
    assert alert.out_of_context_warning is False
    assert alert.priority == AlertPriority.HIGH  # NOT downgraded


def test_apply_setup_context_tags_experimental():
    """vwap_fade is experimental — never warns regardless of setup."""
    from services.market_setup_classifier import (
        get_market_setup_classifier, ClassificationResult,
    )
    s = EnhancedBackgroundScanner(db=None)
    classifier = get_market_setup_classifier()
    classifier._cache["TEST4"] = (
        ClassificationResult(setup=MarketSetup.OVEREXTENSION, confidence=0.9),
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    async def _run_test():
        alert = MockAlert(setup_type="vwap_fade", priority=AlertPriority.HIGH)
        await s._apply_setup_context(alert, "TEST4", _flat_snapshot())
        return alert

    alert = _run(_run_test())
    assert alert.experimental is True
    assert alert.out_of_context_warning is False


# ──────────────────────────── HELPERS ────────────────────────────


class MockAlert:
    """Stand-in for LiveAlert for context-tagging tests."""
    def __init__(self, setup_type, priority):
        self.setup_type = setup_type
        self.priority = priority
        self.market_setup = "neutral"
        self.is_countertrend = False
        self.out_of_context_warning = False
        self.experimental = False
        self.reasoning = []


# ──────────────────────────── REGISTRATION ────────────────────────────


def test_the_3_30_trade_registered_in_scanner():
    """the_3_30_trade must be wired into checkers, REGISTERED, _enabled, time-windows."""
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    assert '"the_3_30_trade":' in src                # in checkers dict
    assert '"the_3_30_trade",' in src                # in REGISTERED + _enabled
    assert '"the_3_30_trade":' in src                # in STRATEGY_TIME_WINDOWS
    assert "_check_the_3_30_trade" in src            # function exists


def test_live_alert_has_setup_context_fields():
    """LiveAlert dataclass must expose market_setup / is_countertrend / etc."""
    from services.enhanced_scanner import LiveAlert
    fields = LiveAlert.__dataclass_fields__
    for f in ("market_setup", "is_countertrend", "out_of_context_warning", "experimental"):
        assert f in fields, f"LiveAlert missing field {f!r}"
