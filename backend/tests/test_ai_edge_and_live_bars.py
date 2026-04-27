"""
AI Confidence Baseline + Live Bar Overlay Tests
================================================
Covers the Feb-2026 follow-up improvements to the scanner:
  1. `ai_confidence_baseline.py` rolling-30-day baseline + delta classification
  2. `realtime_technical_service` live-bar-overlay (live merges into Mongo
     historical bars when the IB pusher RPC is up).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import mongomock
import pytest


# =====================================================================
# Part A — AI Confidence Baseline Service
# =====================================================================

def test_baseline_returns_none_below_min_sample():
    from services.ai_confidence_baseline import AIConfidenceBaselineService

    db = mongomock.MongoClient().db
    # Only 3 alerts — below MIN_SAMPLE_FOR_BASELINE (5)
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_many([
        {"symbol": "AAPL", "direction": "long", "ai_confidence": 60.0, "created_at": now_iso},
        {"symbol": "AAPL", "direction": "long", "ai_confidence": 65.0, "created_at": now_iso},
        {"symbol": "AAPL", "direction": "long", "ai_confidence": 70.0, "created_at": now_iso},
    ])

    svc = AIConfidenceBaselineService()
    svc.set_db(db)
    baseline, sample = svc.get_baseline("AAPL", "long")
    assert baseline is None
    assert sample == 3


def test_baseline_computes_rolling_30d_mean():
    from services.ai_confidence_baseline import AIConfidenceBaselineService

    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    # 6 in-window alerts mean = (60+62+68+70+72+78)/6 = 68.33
    db["live_alerts"].insert_many([
        {"symbol": "AAPL", "direction": "long", "ai_confidence": v, "created_at": now_iso}
        for v in (60.0, 62.0, 68.0, 70.0, 72.0, 78.0)
    ])
    # Old alert (40 days ago) — must be excluded.
    old_iso = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    db["live_alerts"].insert_one(
        {"symbol": "AAPL", "direction": "long", "ai_confidence": 10.0, "created_at": old_iso}
    )

    svc = AIConfidenceBaselineService()
    svc.set_db(db)
    baseline, sample = svc.get_baseline("AAPL", "long")
    assert sample == 6
    assert baseline == pytest.approx(68.33, abs=0.05)


def test_compute_delta_label_thresholds():
    """Verify delta classification: STRONG_EDGE (≥+15), ABOVE (≥+5), AT, BELOW (≤−5)."""
    from services.ai_confidence_baseline import AIConfidenceBaselineService

    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    # Baseline = 60.0 (5 alerts, all 60)
    db["live_alerts"].insert_many([
        {"symbol": "AAPL", "direction": "long", "ai_confidence": 60.0, "created_at": now_iso}
        for _ in range(5)
    ])

    svc = AIConfidenceBaselineService()
    svc.set_db(db)

    # STRONG_EDGE: 60 + 16 = 76
    edge = svc.compute_delta("AAPL", "long", current_confidence=76.0)
    assert edge["ai_edge_label"] == "STRONG_EDGE"
    assert edge["ai_confidence_delta_pp"] == pytest.approx(16.0, abs=0.01)
    assert edge["ai_baseline_confidence"] == 60.0

    # ABOVE: 60 + 6 = 66
    edge = svc.compute_delta("AAPL", "long", current_confidence=66.0)
    assert edge["ai_edge_label"] == "ABOVE_BASELINE"

    # AT: 60 + 2 = 62 (within ±5pp)
    edge = svc.compute_delta("AAPL", "long", current_confidence=62.0)
    assert edge["ai_edge_label"] == "AT_BASELINE"

    # BELOW: 60 − 7 = 53
    edge = svc.compute_delta("AAPL", "long", current_confidence=53.0)
    assert edge["ai_edge_label"] == "BELOW_BASELINE"
    assert edge["ai_confidence_delta_pp"] == pytest.approx(-7.0, abs=0.01)


def test_compute_delta_returns_insufficient_when_no_history():
    from services.ai_confidence_baseline import AIConfidenceBaselineService

    db = mongomock.MongoClient().db  # empty live_alerts
    svc = AIConfidenceBaselineService()
    svc.set_db(db)

    edge = svc.compute_delta("ZZZZ", "long", current_confidence=80.0)
    assert edge["ai_edge_label"] == "INSUFFICIENT_DATA"
    assert edge["ai_baseline_confidence"] == 0.0
    assert edge["ai_confidence_delta_pp"] == 0.0
    assert edge["ai_baseline_sample"] == 0


def test_baseline_normalizes_direction_aliases():
    """`buy`/`bullish`/`long` must all collapse to the same baseline bucket."""
    from services.ai_confidence_baseline import AIConfidenceBaselineService

    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_many([
        {"symbol": "TSLA", "direction": "long", "ai_confidence": 50.0, "created_at": now_iso},
        {"symbol": "TSLA", "direction": "buy", "ai_confidence": 60.0, "created_at": now_iso},
        {"symbol": "TSLA", "direction": "bullish", "ai_confidence": 70.0, "created_at": now_iso},
        {"symbol": "TSLA", "direction": "up", "ai_confidence": 70.0, "created_at": now_iso},
        {"symbol": "TSLA", "direction": "long", "ai_confidence": 50.0, "created_at": now_iso},
    ])

    svc = AIConfidenceBaselineService()
    svc.set_db(db)

    # All 5 long-aliased alerts should pool together.
    for direction_alias in ("long", "buy", "bullish", "up"):
        baseline, sample = svc.get_baseline("TSLA", direction_alias)
        # 60 = mean(50, 60, 70, 70, 50)
        assert sample == 5, f"{direction_alias}: expected sample=5, got {sample}"
        assert baseline == pytest.approx(60.0, abs=0.01)
        svc.invalidate("TSLA")  # bypass cache for next assertion


# =====================================================================
# Part B — Live Bar Overlay in realtime_technical_service
# =====================================================================

def test_merge_live_into_history_overrides_overlapping_timestamps():
    """Live bars MUST overwrite Mongo bars on shared timestamps."""
    from services.realtime_technical_service import RealTimeTechnicalService

    mongo = [
        {"timestamp": "20260219 09:30:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        {"timestamp": "20260219 09:35:00", "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 1500},
    ]
    live = [
        # Same 09:35 bar but with a higher close → live should win.
        {"timestamp": "20260219 09:35:00", "open": 100.5, "high": 103, "low": 100, "close": 102.5, "volume": 1700},
        # New bar live-only.
        {"timestamp": "20260219 09:40:00", "open": 102.5, "high": 104, "low": 102, "close": 103.5, "volume": 2000},
    ]

    merged, source = RealTimeTechnicalService._merge_live_into_history(mongo, live)
    assert source == "live_extended"
    assert len(merged) == 3
    # 09:35 bar must be the LIVE version (close=102.5).
    bar_0935 = next(b for b in merged if str(b["timestamp"]) == "20260219 09:35:00")
    assert bar_0935["close"] == 102.5
    # 09:40 bar should be live-only.
    assert any(str(b["timestamp"]) == "20260219 09:40:00" for b in merged)


def test_merge_live_into_history_handles_missing_inputs():
    from services.realtime_technical_service import RealTimeTechnicalService

    out, src = RealTimeTechnicalService._merge_live_into_history(None, None)
    assert out is None and src == "mongo_only"

    live = [{"timestamp": "x", "close": 1, "open": 1, "high": 1, "low": 1, "volume": 0}]
    out, src = RealTimeTechnicalService._merge_live_into_history(None, live)
    assert out is live and src == "live_only"

    mongo = [{"timestamp": "y", "close": 2, "open": 2, "high": 2, "low": 2, "volume": 0}]
    out, src = RealTimeTechnicalService._merge_live_into_history(mongo, None)
    assert out is mongo and src == "mongo_only"


def test_get_live_intraday_bars_returns_none_when_rpc_disabled():
    """Kill-switch must short-circuit the live RPC path entirely."""
    from services.realtime_technical_service import RealTimeTechnicalService

    svc = RealTimeTechnicalService()

    # Patch the kill-switch reader to "disabled". The function must return
    # None without doing any network work.
    with patch("services.ib_pusher_rpc.is_live_bar_rpc_enabled", return_value=False):
        result = asyncio.run(svc._get_live_intraday_bars("AAPL", "5 mins"))
    assert result is None


def test_get_live_intraday_bars_returns_none_when_rpc_unconfigured():
    """When RPC URL is unset (cloud deploy), live path must skip cleanly."""
    from services.realtime_technical_service import RealTimeTechnicalService

    svc = RealTimeTechnicalService()

    fake_client = MagicMock()
    fake_client.is_configured.return_value = False

    with patch("services.ib_pusher_rpc.is_live_bar_rpc_enabled", return_value=True), \
         patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client):
        result = asyncio.run(svc._get_live_intraday_bars("AAPL", "5 mins"))
    assert result is None


def test_live_alert_dataclass_carries_baseline_fields():
    """The new edge fields must be on `LiveAlert` so to_dict() ships them."""
    from services.enhanced_scanner import LiveAlert, AlertPriority

    alert = LiveAlert(
        id="t1",
        symbol="AAPL",
        setup_type="orb",
        strategy_name="ORB",
        direction="long",
        priority=AlertPriority.MEDIUM,
        current_price=100.0,
        trigger_price=101.0,
        stop_loss=98.0,
        target=104.0,
        risk_reward=2.0,
        trigger_probability=0.7,
        win_probability=0.55,
        minutes_to_trigger=5,
        headline="ORB long",
        reasoning=[],
        time_window="opening_drive",
        market_regime="strong_uptrend",
    )
    d = alert.to_dict()
    assert "ai_baseline_confidence" in d
    assert "ai_confidence_delta_pp" in d
    assert "ai_edge_label" in d
    assert "ai_baseline_sample" in d
    # Defaults
    assert d["ai_edge_label"] == "INSUFFICIENT_DATA"
    assert d["ai_baseline_confidence"] == 0.0


def test_technical_snapshot_carries_data_source_field():
    """`TechnicalSnapshot.data_source` must default to 'mongo_only' so old
    callers still work, and must be settable to 'live_only' / 'live_extended'."""
    from services.realtime_technical_service import TechnicalSnapshot

    # Build with all required fields (use 0 placeholders for non-source fields).
    snap = TechnicalSnapshot(
        symbol="AAPL", timestamp="2026-02-19T00:00:00",
        current_price=100, open=100, high=101, low=99, prev_close=99.5,
        volume=1000, avg_volume=900, rvol=1.1,
        vwap=100, ema_9=100, ema_20=100, ema_50=100, sma_200=100,
        dist_from_vwap=0, dist_from_ema9=0, dist_from_ema20=0,
        rsi_14=50, rsi_trend="neutral",
        atr=1, atr_percent=1, daily_range_pct=2,
        gap_pct=0, gap_direction="flat", holding_gap=True,
        resistance=101, support=99, high_of_day=101, low_of_day=99,
        above_vwap=True, above_ema9=True, above_ema20=True, trend="sideways",
        extended_from_ema9=False, extension_pct=0,
        bb_upper=102, bb_middle=100, bb_lower=98, bb_width=4,
        kc_upper=102, kc_middle=100, kc_lower=98,
        squeeze_on=False, squeeze_fire=0,
        or_high=101, or_low=99, or_breakout="inside",
        rs_vs_spy=0, bars_used=78, data_quality="real",
    )
    # Default
    assert snap.data_source == "mongo_only"
    # Can be overridden after construction (matches scanner usage pattern)
    snap.data_source = "live_extended"
    assert snap.data_source == "live_extended"
