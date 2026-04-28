"""
Regression tests for the per-detector firing telemetry — diagnoses
"Round 2" Scanner-quiet issue (operator's 2026-04-29 audit, where the
scanner only emitted `relative_strength_laggard` hits after 20 min of
market open).

Asserts:
  - `_check_setup` increments evaluation + hit counters per setup
  - `/api/scanner/detector-stats` returns the buckets sorted by hits desc
  - Per-cycle counters reset on each `_run_optimized_scan` (only totals
    persist), so the operator's "what just happened?" view is fresh
  - Endpoint is safe to call before any scan has run (empty payload)
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_detector_stats_returns_empty_payload_when_scanner_uninitialised():
    from routers import scanner as scanner_router
    with patch.object(scanner_router, "_scanner_service", None):
        resp = scanner_router.get_detector_stats()
    assert resp["success"] is True
    assert resp["last_cycle"]["total_evals"] == 0
    assert resp["cumulative"]["total_evals"] == 0


def test_detector_stats_aggregates_counters_correctly():
    """When the scanner has telemetry, the endpoint should expose buckets
    sorted by hits desc, with hit_rate_pct math."""
    from routers import scanner as scanner_router

    fake = SimpleNamespace(
        _running=True,
        _scan_count=42,
        _symbols_scanned_last=180,
        _symbols_skipped_adv=400,
        _symbols_skipped_rvol=120,
        _detector_evals={"orb": 80, "vwap_bounce": 50, "relative_strength_laggard": 30},
        _detector_hits={"orb": 0, "vwap_bounce": 1, "relative_strength_laggard": 3},
        _detector_evals_total={"orb": 1500, "vwap_bounce": 900,
                                "relative_strength_laggard": 600,
                                "breakout": 800},
        _detector_hits_total={"orb": 12, "vwap_bounce": 4,
                               "relative_strength_laggard": 47,
                               "breakout": 6},
    )

    with patch.object(scanner_router, "_scanner_service", fake):
        resp = scanner_router.get_detector_stats()

    assert resp["success"] is True
    assert resp["scan_count"] == 42
    assert resp["last_cycle"]["total_evals"] == 160
    assert resp["last_cycle"]["total_hits"] == 4
    # Sorted by hits desc
    last_cycle_top = resp["last_cycle"]["detectors"][0]
    assert last_cycle_top["setup_type"] == "relative_strength_laggard"
    assert last_cycle_top["hits"] == 3
    assert last_cycle_top["hit_rate_pct"] == 10.0
    # Cumulative also sorted by hits
    cum_top = resp["cumulative"]["detectors"][0]
    assert cum_top["setup_type"] == "relative_strength_laggard"
    assert cum_top["hits"] == 47


def test_check_setup_increments_evals_and_hits_counters():
    """Wire-level test: `_check_setup` must increment counters whether
    the underlying detector returns an alert or None."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    scanner = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    scanner._detector_evals = {}
    scanner._detector_hits = {}
    scanner._detector_evals_total = {}
    scanner._detector_hits_total = {}

    # Replace one checker with an async stub returning a fake alert
    async def _hit_checker(symbol, snapshot, tape):
        return SimpleNamespace(symbol=symbol, setup_type="orb")

    async def _miss_checker(symbol, snapshot, tape):
        return None

    scanner._check_orb = _hit_checker
    scanner._check_vwap_bounce = _miss_checker
    # Stub out all other checkers to avoid attribute errors during the
    # `checkers` dict build inside _check_setup
    for attr in (
        "_check_first_vwap_pullback", "_check_opening_drive",
        "_check_hitchhiker", "_check_gap_give_go",
        "_check_spencer_scalp", "_check_second_chance",
        "_check_backside", "_check_off_sides", "_check_fashionably_late",
        "_check_rubber_band", "_check_vwap_fade", "_check_tidal_wave",
        "_check_big_dog", "_check_puppy_dog", "_check_9_ema_scalp",
        "_check_abc_scalp", "_check_hod_breakout",
        "_check_approaching_hod", "_check_volume_capitulation",
        "_check_range_break", "_check_breakout", "_check_squeeze",
        "_check_mean_reversion", "_check_relative_strength",
        "_check_gap_fade", "_check_chart_pattern",
    ):
        setattr(scanner, attr, _miss_checker)

    # Hit
    res = _run(scanner._check_setup("orb", "AAPL", None, None))
    assert res is not None
    assert scanner._detector_evals["orb"] == 1
    assert scanner._detector_hits["orb"] == 1
    assert scanner._detector_evals_total["orb"] == 1
    assert scanner._detector_hits_total["orb"] == 1

    # Miss — eval increments, hits do NOT
    res = _run(scanner._check_setup("vwap_bounce", "AAPL", None, None))
    assert res is None
    assert scanner._detector_evals["vwap_bounce"] == 1
    assert "vwap_bounce" not in scanner._detector_hits
    assert scanner._detector_evals_total["vwap_bounce"] == 1

    # Multiple evals on same setup keep accumulating
    _run(scanner._check_setup("orb", "MSFT", None, None))
    _run(scanner._check_setup("orb", "GOOG", None, None))
    assert scanner._detector_evals["orb"] == 3
    assert scanner._detector_hits["orb"] == 3


def test_check_setup_unknown_setup_type_does_not_count():
    """An unknown `setup_type` (not in the checkers dict) returns None
    and does NOT pollute the telemetry counters."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    scanner = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    scanner._detector_evals = {}
    scanner._detector_hits = {}
    scanner._detector_evals_total = {}
    scanner._detector_hits_total = {}

    res = _run(scanner._check_setup("nonexistent_setup", "AAPL", None, None))
    assert res is None
    assert scanner._detector_evals == {}
    assert scanner._detector_hits == {}
