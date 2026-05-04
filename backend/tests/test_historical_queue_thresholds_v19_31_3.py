"""
v19.31.3 (2026-05-04) — regression pin for the historical_queue threshold
rebalance + new info-level banner.

The bug:
  Operator hit "Some subsystems are degraded" giant orange banner the
  moment they kicked off a backfill (20,222 pending · 0 failed). Old
  thresholds yellow'd at 5,000 pending — but a deep queue with zero
  failures is by-design backfill, not a degraded subsystem. The amber
  banner ate ~200px of dashboard real estate at market open.

The fix:
  1. Failures are the real signal, not pending depth alone:
     - yellow at >=25 failed OR >=50,000 pending
     - red at >=100 failed OR >=100,000 pending
  2. Surface "deep queue, no failures" via a metric flag so the banner
     can render a thin info-level pill instead of alarming.

These tests pin the new thresholds + the deep_queue_no_failures flag.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake Mongo collection ───────────────────────────────────────


class _FakeColl:
    def __init__(self, pending=0, failed=0):
        self._pending = pending
        self._failed = failed

    def count_documents(self, query):
        status = query.get("status")
        if isinstance(status, dict) and status.get("$in") == ["pending", "in_progress"]:
            return self._pending
        if status == "failed":
            return self._failed
        return 0


class _FakeDB:
    def __init__(self, pending=0, failed=0):
        self._coll = _FakeColl(pending, failed)

    def __getitem__(self, name):
        return self._coll


# ─── _check_historical_queue ─────────────────────────────────────


def test_threshold_constants_are_the_expected_values():
    from services import system_health_service as shs
    assert shs.HIST_QUEUE_INFO == 5_000
    assert shs.HIST_QUEUE_YELLOW == 50_000
    assert shs.HIST_QUEUE_RED == 100_000
    assert shs.HIST_QUEUE_FAIL_YELLOW == 25
    assert shs.HIST_QUEUE_FAIL_RED == 100


def test_zero_pending_zero_failed_is_green():
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(0, 0))
    assert res.status == "green"
    assert res.metrics["deep_queue_no_failures"] is False


def test_4k_pending_zero_failed_is_green_no_info():
    """Below info threshold — green, no flag."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(4_000, 0))
    assert res.status == "green"
    assert res.metrics["deep_queue_no_failures"] is False


def test_20k_pending_zero_failed_is_green_with_info_flag():
    """The exact operator scenario — 20,222 pending, 0 failed.
    OLD behavior: yellow + amber banner. NEW: green + info flag."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(20_222, 0))
    assert res.status == "green"
    assert res.metrics["deep_queue_no_failures"] is True
    assert res.metrics["pending"] == 20_222
    assert res.metrics["failed"] == 0


def test_50k_pending_zero_failed_escalates_to_yellow():
    """Right at the new yellow line — IB pacing genuinely underwater."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(50_000, 0))
    assert res.status == "yellow"
    assert res.metrics["deep_queue_no_failures"] is False


def test_100k_pending_zero_failed_escalates_to_red():
    """Pipeline can't drain in a session."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(100_000, 0))
    assert res.status == "red"


def test_25_failures_escalates_to_yellow_even_with_low_pending():
    """Failures are the leading indicator — even a small pending queue
    with 25 failures is a real problem."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(100, 25))
    assert res.status == "yellow"


def test_100_failures_escalates_to_red():
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(100, 100))
    assert res.status == "red"


def test_deep_queue_with_failures_is_NOT_info():
    """Even at 20k pending, if anything failed, surface as warning
    not info — the operator needs to see the failures."""
    from services.system_health_service import _check_historical_queue
    res = _check_historical_queue(_FakeDB(20_000, 5))
    assert res.status == "green"  # 5 < FAIL_YELLOW threshold
    # But the info flag should be False — there ARE failures
    assert res.metrics["deep_queue_no_failures"] is False


# ─── /api/system/banner integration ──────────────────────────────


@pytest.mark.asyncio
async def test_banner_returns_info_level_for_deep_queue_no_failures():
    """Deep backfill queue with 0 failures must produce a level=info
    banner (blue strip), not warning (orange) or null."""
    from routers import system_banner as sb

    fake_snapshot = {
        "overall": "green",
        "as_of": "2026-05-04T15:00:00Z",
        "subsystems": [
            {
                "name": "historical_queue",
                "status": "green",
                "detail": "20,222 pending · 0 failed",
                "metrics": {
                    "pending": 20_222,
                    "failed": 0,
                    "deep_queue_no_failures": True,
                },
            },
            {
                "name": "pusher_rpc",
                "status": "green",
                "detail": "OK",
                "metrics": {
                    "consecutive_failures": 0,
                    "push_age_s": 5.0,
                    "push_fresh": True,
                },
            },
        ],
    }

    import services.system_health_service as shs
    original = shs.build_health
    try:
        shs.build_health = lambda _db: fake_snapshot
        result = await sb.get_system_banner()
    finally:
        shs.build_health = original

    assert result["level"] == "info"
    assert "20,222 pending" in result["message"]
    assert result["subsystem"] == "historical_queue"
    # No "action" — informational only
    assert result["action"] is None


@pytest.mark.asyncio
async def test_banner_returns_no_level_when_all_clean_and_no_deep_queue():
    """Truly clean state — no info, no warning, no critical."""
    from routers import system_banner as sb

    fake_snapshot = {
        "overall": "green",
        "as_of": "2026-05-04T15:00:00Z",
        "subsystems": [
            {
                "name": "historical_queue",
                "status": "green",
                "detail": "0 pending · 0 failed",
                "metrics": {
                    "pending": 0,
                    "failed": 0,
                    "deep_queue_no_failures": False,
                },
            },
            {
                "name": "pusher_rpc",
                "status": "green",
                "detail": "OK",
                "metrics": {
                    "consecutive_failures": 0,
                    "push_age_s": 5.0,
                    "push_fresh": True,
                },
            },
        ],
    }

    import services.system_health_service as shs
    original = shs.build_health
    try:
        shs.build_health = lambda _db: fake_snapshot
        result = await sb.get_system_banner()
    finally:
        shs.build_health = original

    assert result["level"] is None
    assert result["message"] is None


@pytest.mark.asyncio
async def test_banner_warning_takes_precedence_over_info():
    """If overall is yellow (some other subsystem degraded), the
    warning fires — the info-level deep-queue should NOT preempt it."""
    from routers import system_banner as sb

    fake_snapshot = {
        "overall": "yellow",
        "as_of": "2026-05-04T15:00:00Z",
        "subsystems": [
            {
                "name": "historical_queue",
                "status": "green",
                "detail": "20,222 pending · 0 failed",
                "metrics": {
                    "pending": 20_222,
                    "failed": 0,
                    "deep_queue_no_failures": True,
                },
            },
            {
                "name": "ai_training",
                "status": "yellow",
                "detail": "training stalled",
                "metrics": {},
            },
            {
                "name": "pusher_rpc",
                "status": "green",
                "detail": "OK",
                "metrics": {
                    "consecutive_failures": 0,
                    "push_age_s": 5.0,
                    "push_fresh": True,
                },
            },
        ],
    }

    import services.system_health_service as shs
    original = shs.build_health
    try:
        shs.build_health = lambda _db: fake_snapshot
        result = await sb.get_system_banner()
    finally:
        shs.build_health = original

    # Warning wins, not info
    assert result["level"] == "warning"
    assert result["message"] == "Some subsystems are degraded"
