"""
Strategy Mix Endpoint Tests
============================
Validates GET /api/scanner/strategy-mix:
- Aggregates the last N `live_alerts` by `setup_type`.
- Strips `_long` / `_short` suffix so paired strategies pool together.
- Surfaces a `concentration_warning` when one strategy ≥ 70% of total.
- Counts STRONG_EDGE alerts per bucket.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import mongomock
import pytest


def _build_router_with_db(db):
    """Wire a fake scanner_service that exposes `db` so the router has data."""
    from routers import scanner as scanner_router

    fake_svc = MagicMock()
    fake_svc.db = db
    scanner_router._scanner_service = fake_svc
    return scanner_router


def test_strategy_mix_returns_empty_when_no_alerts():
    db = mongomock.MongoClient().db
    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    assert out["success"] is True
    assert out["total"] == 0
    assert out["buckets"] == []


def test_strategy_mix_aggregates_long_and_short_into_same_bucket():
    """orb_long + orb_short must collapse into one `orb` bucket."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_many([
        {"setup_type": "orb_long", "direction": "long", "created_at": now_iso},
        {"setup_type": "orb_short", "direction": "short", "created_at": now_iso},
        {"setup_type": "orb_long", "direction": "long", "created_at": now_iso},
    ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    assert out["total"] == 3
    assert len(out["buckets"]) == 1
    assert out["buckets"][0]["setup_type"] == "orb"
    assert out["buckets"][0]["count"] == 3
    assert out["buckets"][0]["pct"] == pytest.approx(100.0, abs=0.1)


def test_strategy_mix_concentration_warning_triggers_at_70pct():
    """If one strategy is ≥70% of last N, surface a red-flag."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    # 8x relative_strength + 2x breakout = 80/20
    db["live_alerts"].insert_many([
        {"setup_type": "relative_strength_leader", "created_at": now_iso}
        for _ in range(8)
    ] + [
        {"setup_type": "breakout", "created_at": now_iso}
        for _ in range(2)
    ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    assert out["total"] == 10
    assert out["concentration_warning"] is True
    assert out["top_strategy_pct"] == pytest.approx(80.0, abs=0.1)
    # Top bucket should be relative_strength_leader
    assert out["buckets"][0]["setup_type"] == "relative_strength_leader"


def test_strategy_mix_no_warning_when_balanced():
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    # 4 different strategies, each 25%
    for st in ("orb_long", "breakout", "vwap_bounce", "mean_reversion"):
        db["live_alerts"].insert_many([
            {"setup_type": st, "created_at": now_iso} for _ in range(3)
        ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    assert out["total"] == 12
    assert out["concentration_warning"] is False
    assert out["top_strategy_pct"] == pytest.approx(25.0, abs=0.1)
    assert len(out["buckets"]) == 4


def test_strategy_mix_counts_strong_edge_per_bucket():
    """STRONG_EDGE alerts must be counted separately per setup_type."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_many([
        {"setup_type": "breakout", "ai_edge_label": "STRONG_EDGE", "created_at": now_iso},
        {"setup_type": "breakout", "ai_edge_label": "STRONG_EDGE", "created_at": now_iso},
        {"setup_type": "breakout", "ai_edge_label": "AT_BASELINE", "created_at": now_iso},
        {"setup_type": "orb_long", "ai_edge_label": "STRONG_EDGE", "created_at": now_iso},
        {"setup_type": "orb_long", "ai_edge_label": "INSUFFICIENT_DATA", "created_at": now_iso},
    ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    by_st = {b["setup_type"]: b for b in out["buckets"]}
    assert by_st["breakout"]["count"] == 3
    assert by_st["breakout"]["strong_edge_count"] == 2
    assert by_st["orb"]["count"] == 2
    assert by_st["orb"]["strong_edge_count"] == 1


def test_strategy_mix_respects_n_param_clamps():
    """n must clamp to [10, 500] for safety."""
    db = mongomock.MongoClient().db
    router = _build_router_with_db(db)
    # All return success without aggregation errors regardless of input
    for n in (1, 5, 10000, 0, -1, None):
        out = router.get_strategy_mix(n=n)
        assert out["success"] is True


def test_strategy_mix_returns_zero_when_scanner_service_missing():
    from routers import scanner as scanner_router
    scanner_router._scanner_service = None
    out = scanner_router.get_strategy_mix(n=100)
    assert out["total"] == 0
    assert out["buckets"] == []


# =====================================================================
# P&L attribution tests (alert_outcomes JOIN)
# =====================================================================

def test_strategy_mix_attaches_avg_r_and_win_rate_per_bucket():
    """Buckets must carry avg_r_multiple, win_rate_pct, outcomes_count
    sourced from alert_outcomes (last 30 days, grouped by setup_type)."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    # Alerts (frequency)
    db["live_alerts"].insert_many([
        {"setup_type": "breakout", "created_at": now_iso} for _ in range(5)
    ] + [
        {"setup_type": "vwap_bounce", "created_at": now_iso} for _ in range(3)
    ])
    # Outcomes (P&L) — breakout averages -0.3R, vwap_bounce averages +1.2R
    db["alert_outcomes"].insert_many([
        {"setup_type": "breakout", "r_multiple": -0.5, "timestamp": now_iso},
        {"setup_type": "breakout", "r_multiple": -0.4, "timestamp": now_iso},
        {"setup_type": "breakout", "r_multiple": 0.0, "timestamp": now_iso},
        {"setup_type": "vwap_bounce", "r_multiple": 1.5, "timestamp": now_iso},
        {"setup_type": "vwap_bounce", "r_multiple": 0.9, "timestamp": now_iso},
    ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    by_st = {b["setup_type"]: b for b in out["buckets"]}

    assert by_st["breakout"]["outcomes_count"] == 3
    assert by_st["breakout"]["avg_r_multiple"] == pytest.approx(-0.3, abs=0.01)
    assert by_st["breakout"]["win_rate_pct"] == pytest.approx(0.0, abs=0.1)
    assert by_st["breakout"]["total_r_30d"] == pytest.approx(-0.9, abs=0.01)

    assert by_st["vwap_bounce"]["outcomes_count"] == 2
    assert by_st["vwap_bounce"]["avg_r_multiple"] == pytest.approx(1.2, abs=0.01)
    assert by_st["vwap_bounce"]["win_rate_pct"] == pytest.approx(100.0, abs=0.1)


def test_strategy_mix_pnl_merges_long_and_short_variants():
    """orb_long + orb_short outcomes must collapse into a single `orb`
    bucket with combined avg_r and win_rate."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_many([
        {"setup_type": "orb_long", "created_at": now_iso} for _ in range(2)
    ] + [
        {"setup_type": "orb_short", "created_at": now_iso} for _ in range(2)
    ])
    db["alert_outcomes"].insert_many([
        {"setup_type": "orb_long", "r_multiple": 1.0, "timestamp": now_iso},
        {"setup_type": "orb_long", "r_multiple": 1.0, "timestamp": now_iso},
        {"setup_type": "orb_short", "r_multiple": -0.5, "timestamp": now_iso},
        {"setup_type": "orb_short", "r_multiple": -0.5, "timestamp": now_iso},
    ])

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    by_st = {b["setup_type"]: b for b in out["buckets"]}

    assert "orb" in by_st
    # 4 outcomes total, mean = (1.0 + 1.0 - 0.5 - 0.5) / 4 = 0.25
    assert by_st["orb"]["outcomes_count"] == 4
    assert by_st["orb"]["avg_r_multiple"] == pytest.approx(0.25, abs=0.01)
    # 2 wins / 4 = 50%
    assert by_st["orb"]["win_rate_pct"] == pytest.approx(50.0, abs=0.1)


def test_strategy_mix_pnl_excludes_outcomes_older_than_30d():
    """alert_outcomes older than 30 days must NOT contribute to avg_r."""
    db = mongomock.MongoClient().db
    now = datetime.now(timezone.utc)
    db["live_alerts"].insert_one({"setup_type": "breakout", "created_at": now.isoformat()})
    # 1 in-window: +2.0R
    db["alert_outcomes"].insert_one({
        "setup_type": "breakout",
        "r_multiple": 2.0,
        "timestamp": now.isoformat(),
    })
    # 1 out-of-window: -10.0R (must be excluded)
    db["alert_outcomes"].insert_one({
        "setup_type": "breakout",
        "r_multiple": -10.0,
        "timestamp": (now - timedelta(days=45)).isoformat(),
    })

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    by_st = {b["setup_type"]: b for b in out["buckets"]}
    assert by_st["breakout"]["outcomes_count"] == 1
    assert by_st["breakout"]["avg_r_multiple"] == pytest.approx(2.0, abs=0.01)


def test_strategy_mix_buckets_with_no_outcomes_get_null_pnl_fields():
    """A bucket that has alerts but no resolved outcomes should carry
    None for outcomes_count / avg_r_multiple / win_rate_pct so the UI
    can render '—'."""
    db = mongomock.MongoClient().db
    now_iso = datetime.now(timezone.utc).isoformat()
    db["live_alerts"].insert_one({"setup_type": "squeeze", "created_at": now_iso})
    # No alert_outcomes for squeeze.

    router = _build_router_with_db(db)
    out = router.get_strategy_mix(n=100)
    by_st = {b["setup_type"]: b for b in out["buckets"]}
    assert by_st["squeeze"]["outcomes_count"] is None
    assert by_st["squeeze"]["avg_r_multiple"] is None
    assert by_st["squeeze"]["win_rate_pct"] is None
    assert by_st["squeeze"]["total_r_30d"] is None
