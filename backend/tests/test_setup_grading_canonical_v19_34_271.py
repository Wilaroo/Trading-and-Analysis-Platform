"""
test_setup_grading_canonical_v19_34_271.py — m5 + Issue 3

Locks the canonical roll-up + artifact exclusion + median-R grade + sub-$1
risk clamp behaviour for the grading / EV / corrected-store changes. Pure
logic — no DB, no IB, no network.
"""
import os
import importlib

import pytest


# ── grading SSOT bucket key ────────────────────────────────────────────────
def test_canonical_grade_key_collapses_variants(monkeypatch):
    monkeypatch.setenv("GRADING_CANONICAL_ROLLUP", "1")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    assert sg._canonical_grade_key("vwap_fade_long") == "vwap_fade"
    assert sg._canonical_grade_key("vwap_fade_short") == "vwap_fade"
    assert sg._canonical_grade_key("breakout_confirmed") == "breakout"


def test_canonical_grade_key_excludes_artifacts(monkeypatch):
    monkeypatch.setenv("GRADING_CANONICAL_ROLLUP", "1")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    assert sg._canonical_grade_key("reconciled_excess_v19_34_15b") is None
    assert sg._canonical_grade_key("imported_from_ib") is None
    assert sg._canonical_grade_key("approaching_breakout") is None


def test_canonical_grade_key_flag_off_passes_raw(monkeypatch):
    monkeypatch.setenv("GRADING_CANONICAL_ROLLUP", "0")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    assert sg._canonical_grade_key("vwap_fade_long") == "vwap_fade_long"


# ── median-R grade vs legacy mean-R grade ──────────────────────────────────
def _trades(rs, risk=100.0):
    return [{"r_multiple": r, "risk_amount": risk, "realized_pnl": r * risk}
            for r in rs]


def test_daily_grade_uses_median_not_mean(monkeypatch):
    monkeypatch.setenv("GRADING_USE_MEDIAN", "1")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    svc = sg.SetupGradingService(db=None)
    # 5x +0.1R and one +10R outlier: mean ≈ 1.75 (A+), median = 0.1 (C).
    stats = svc._compute_daily_stats("vwap_fade", "2026-06-10",
                                     _trades([0.1, 0.1, 0.1, 0.1, 0.1, 10.0]))
    assert stats is not None
    assert stats.grade == "C"          # median-driven, outlier ignored
    assert stats.canonical_setup == "vwap_fade"


def test_daily_grade_legacy_mean_when_flag_off(monkeypatch):
    monkeypatch.setenv("GRADING_USE_MEDIAN", "0")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    svc = sg.SetupGradingService(db=None)
    stats = svc._compute_daily_stats("vwap_fade", "2026-06-10",
                                     _trades([0.1, 0.1, 0.1, 0.1, 0.1, 10.0]))
    assert stats.grade == "A+"          # mean-driven, outlier inflates


# ── sub-$1 risk clamp ──────────────────────────────────────────────────────
def test_micro_risk_rows_dropped(monkeypatch):
    monkeypatch.setenv("GRADING_MIN_RISK_AMOUNT", "1.0")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    svc = sg.SetupGradingService(db=None)
    rows = _trades([0.5, 0.5, 0.5, 0.5, 0.5], risk=100.0)
    # one poison row: $0.20 risk basis, absurd +80R
    rows.append({"r_multiple": 80.0, "risk_amount": 0.20, "realized_pnl": 16.0})
    stats = svc._compute_daily_stats("orb", "2026-06-10", rows)
    assert stats.trades_count == 5      # poison row excluded
    assert stats.best_r == 0.5


# ── rolling weighted-median grade ──────────────────────────────────────────
def test_rollup_weighted_median(monkeypatch):
    monkeypatch.setenv("GRADING_USE_MEDIAN", "1")
    import services.setup_grading_service as sg
    importlib.reload(sg)
    svc = sg.SetupGradingService(db=None)
    rows = [
        {"trades_count": 10, "wins": 10, "losses": 0, "total_r": 100.0,
         "median_r": 0.1, "avg_mfe_r": 0, "avg_mae_r": 0, "avg_hold_seconds": 0,
         "total_realized_pnl": 0, "worst_r": 0.1, "best_r": 50.0,
         "trading_date": "2026-06-10"},
    ]
    rolling = svc._rollup("vwap_fade", 30, rows)
    # avg_r = 10.0 (would be A+), but median-weighted = 0.1 → C
    assert rolling.grade == "C"


# ── EV canonical roll-up + artifact exclusion ──────────────────────────────
def test_ev_canon_collapses_and_excludes(monkeypatch):
    monkeypatch.setenv("EV_CANONICAL_ROLLUP", "1")
    import services.ev_tracking_service as ev
    importlib.reload(ev)
    assert ev.EVTrackingService._canon_for_ev("vwap_fade_long") == "vwap_fade"
    assert ev.EVTrackingService._canon_for_ev("imported_from_ib") is None
    assert ev.EVTrackingService._canon_for_ev("reconciled_excess_x") is None


def test_ev_record_skips_artifact(monkeypatch):
    monkeypatch.setenv("EV_CANONICAL_ROLLUP", "1")
    import services.ev_tracking_service as ev
    importlib.reload(ev)
    svc = ev.EVTrackingService(db=None)
    before = set(svc._ev_records.keys())
    svc.record_trade_outcome("imported_from_ib", 1.5, grade="A", outcome="won")
    # artifact must not create a new EV bucket
    assert "imported_from_ib" not in (set(svc._ev_records.keys()) - before)
    svc.record_trade_outcome("vwap_fade_long", 1.5, grade="A", outcome="won")
    assert "vwap_fade" in svc._ev_records  # collapsed to canonical


# ── TQS corrected-store base key (lockstep with learning_loop rebuild) ──────
def test_setup_quality_canonical_base(monkeypatch):
    monkeypatch.setenv("LEARNING_CANONICAL_BASE", "1")
    import services.tqs.setup_quality as sq
    importlib.reload(sq)
    assert sq._canonical_base_setup("vwap_fade_long") == "vwap_fade"
    assert sq._canonical_base_setup("breakout_confirmed") == "breakout"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
