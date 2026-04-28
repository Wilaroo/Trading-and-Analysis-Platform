"""
Regression tests for the threshold-proximity audit shipped 2026-04-29
(afternoon-15b).

The afternoon-15 audit revealed 12 silent detectors with 0 hits across
101 evaluations each. To answer "how far off are these thresholds vs
reality?" without code-reading, the scanner now records gating values
on every evaluation and the `/api/scanner/setup-coverage` endpoint
includes a `threshold_proximity` block per silent detector showing
min/max/mean of those values vs threshold + a human-readable verdict.

Tests cover:
  - `_PROXIMITY_FIELDS` registry maps each silent detector to its
    gating dimensions (catches typos when adding a new detector).
  - `_sample_proximity_for_setup` records bounded samples (max 200).
  - `get_proximity_audit` produces verdict strings with the right
    semantics for `abs_gt` / `lt` / `gt` comparators.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def scanner():
    """Lightweight fixture — instantiate the real scanner without
    pulling in the full FastAPI app. We only exercise the in-memory
    proximity machinery here; no DB / IB / network involved.
    """
    from services.enhanced_scanner import EnhancedBackgroundScanner
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._detector_proximity = {}
    s._PROXIMITY_MAX_SAMPLES = 200
    return s


def _snap(**kw):
    """Convenience: build a minimal snapshot stub for the sampler."""
    defaults = dict(
        dist_from_vwap=0.0, dist_from_ema9=0.0, dist_from_ema20=0.0,
        rsi_14=50.0, rvol=1.0, current_price=100.0, resistance=105.0,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ─── registry coverage ─────────────────────────────────────────────────

def test_proximity_fields_covers_silent_twelve():
    """All 12 silent detectors flagged in the afternoon-15 audit MUST
    have at least one proximity field registered. Active detectors
    (`relative_strength`, `second_chance`) are deliberately omitted to
    keep memory bounded.
    """
    from services.enhanced_scanner import EnhancedBackgroundScanner
    silent = {
        "vwap_fade", "vwap_bounce", "rubber_band", "tidal_wave",
        "mean_reversion", "squeeze", "breakout", "gap_fade",
        "hod_breakout", "range_break", "volume_capitulation",
        "chart_pattern",
    }
    registered = set(EnhancedBackgroundScanner._PROXIMITY_FIELDS.keys())
    assert silent <= registered, (
        f"Missing proximity registration for: {silent - registered}"
    )


# ─── sampling ────────────────────────────────────────────────────────────

def test_sample_records_bounded_ring_buffer(scanner):
    """The proximity buffer for any single setup must never exceed
    `_PROXIMITY_MAX_SAMPLES` — bound on memory regardless of scan rate.
    """
    for i in range(scanner._PROXIMITY_MAX_SAMPLES + 50):
        scanner._sample_proximity_for_setup(
            "vwap_fade", _snap(dist_from_vwap=float(i % 4), rsi_14=40.0)
        )
    assert len(scanner._detector_proximity["vwap_fade"]) == scanner._PROXIMITY_MAX_SAMPLES


def test_sample_skips_unregistered_setup_silently(scanner):
    """Setups not in `_PROXIMITY_FIELDS` (e.g. active detectors)
    are no-ops — must not crash, must not allocate a bucket.
    """
    scanner._sample_proximity_for_setup("relative_strength", _snap())
    assert "relative_strength" not in scanner._detector_proximity


def test_sample_handles_missing_attrs_gracefully(scanner):
    """If a snapshot is missing a registered attribute (e.g. ATR not
    computed yet), the sampler must skip that field but still record
    the others.
    """
    snap = SimpleNamespace(dist_from_vwap=2.0)  # rsi_14 missing
    scanner._sample_proximity_for_setup("vwap_fade", snap)
    bucket = scanner._detector_proximity.get("vwap_fade", [])
    assert len(bucket) == 1
    s = bucket[0]
    assert "abs_dist_from_vwap" in s
    assert "rsi_14" not in s


# ─── audit verdicts ─────────────────────────────────────────────────────

def test_audit_verdict_reports_unmet_abs_gt_threshold(scanner):
    """If max |value| < threshold for an `abs_gt` comparator, the
    verdict MUST say "threshold never reached — max X < Y".
    """
    for v in (0.5, 1.2, 1.8, 0.9):  # max |.| = 1.8, threshold = 2.5
        scanner._sample_proximity_for_setup(
            "vwap_fade", _snap(dist_from_vwap=v, rsi_14=40.0)
        )
    audit = scanner.get_proximity_audit("vwap_fade")
    field = next(f for f in audit["fields"] if f["label"] == "abs_dist_from_vwap")
    assert field["max"] == 1.8
    assert field["samples_meeting"] == 0
    assert "never reached" in field["verdict"]
    assert "1.8" in field["verdict"] and "2.5" in field["verdict"]


def test_audit_verdict_reports_met_threshold(scanner):
    """If at least one sample meets the threshold, verdict reports
    `threshold met N/M times`.
    """
    for v in (3.0, 1.0, 2.6, 0.5, 4.1):  # 3 of 5 meet 2.5
        scanner._sample_proximity_for_setup(
            "vwap_fade", _snap(dist_from_vwap=v, rsi_14=40.0)
        )
    audit = scanner.get_proximity_audit("vwap_fade")
    field = next(f for f in audit["fields"] if f["label"] == "abs_dist_from_vwap")
    assert field["samples_meeting"] == 3
    assert "met 3/5" in field["verdict"]


def test_audit_verdict_for_lt_comparator(scanner):
    """RSI<threshold uses `lt` comparator. Verdict logic flips:
    verdict reports `threshold never reached — min X > Y` when no
    sample is BELOW the threshold.
    """
    # mean_reversion's RSI threshold is 30. All samples > 30 → no meet.
    for v in (45, 50, 55, 60, 38):
        scanner._sample_proximity_for_setup(
            "mean_reversion", _snap(rsi_14=float(v), dist_from_ema20=4.0)
        )
    audit = scanner.get_proximity_audit("mean_reversion")
    rsi_field = next(f for f in audit["fields"] if f["label"] == "rsi_14_oversold")
    assert rsi_field["samples_meeting"] == 0
    assert rsi_field["min"] == 38
    assert "never reached" in rsi_field["verdict"]
    assert "38" in rsi_field["verdict"] and "30" in rsi_field["verdict"]


def test_audit_returns_none_when_no_samples(scanner):
    """A setup with no recorded samples returns None (caller's
    contract: don't include `threshold_proximity` in response).
    """
    assert scanner.get_proximity_audit("vwap_fade") is None
