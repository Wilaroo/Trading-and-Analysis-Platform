"""T6 (fork 2026-06): data-driven per-setup×regime suppression.

Covers the pure math (banding, clean_R, recency weighting, table build) and the
suppression decision (hard/soft thresholds, MIN_EFF_N guard, direction fallback,
never-promote, gap_fade-style positive cells left alone). No DB required.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.ai_modules.regime_expectancy_calibrator import (
    band_of, clean_r, norm_direction, compute_table, decide_suppression,
    HARD_R, SOFT_R, MIN_EFF_N,
)

NOW = datetime(2026, 6, 8, tzinfo=timezone.utc)


def _trade(setup, direction, regime_score, pnl, risk, days_ago):
    return {
        "_id": f"{setup}-{direction}-{days_ago}",
        "setup_type": setup,
        "direction": direction,
        "regime_score": regime_score,
        "realized_pnl": pnl,
        "risk_amount": risk,
        "status": "closed",
        "closed_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


class TestPureHelpers:
    def test_band_of(self):
        assert band_of(75) == "BULL>60"
        assert band_of(61) == "BULL>60"
        assert band_of(60) == "NEUT46-60"
        assert band_of(46) == "NEUT46-60"
        assert band_of(45) == "BEAR<=45"
        assert band_of(None) is None

    def test_clean_r(self):
        assert clean_r(200, 100) == 2.0
        assert clean_r(-50, 100) == -0.5
        assert clean_r(100, 0) is None       # risk must be > 0
        assert clean_r(5000, 100) is None    # |R|>10 rejected
        assert clean_r(None, 100) is None

    def test_norm_direction(self):
        assert norm_direction("LONG") == "long"
        assert norm_direction("short") == "short"
        assert norm_direction("short_squeeze") == "short"
        assert norm_direction(None) == "long"


class TestTableBuild:
    def test_recency_weighting_pulls_mean_toward_recent(self):
        # Old trades won (+2R) long ago; recent trades lost (-2R) now. The
        # exp-weighted mean must lean negative even though raw mean is ~0.
        rows = [_trade("vwap_fade", "short", 75, 200, 100, 150) for _ in range(10)]
        rows += [_trade("vwap_fade", "short", 75, -200, 100, 1) for _ in range(10)]
        t = compute_table(rows, now=NOW)
        cell = t["cells"]["vwap_fade|short|BULL>60"]
        assert cell["raw_n"] == 20
        # raw all-time mean ~0, but weighted mean should be clearly negative
        assert cell["diag"]["r_all"] == pytest.approx(0.0, abs=0.01)
        assert cell["weighted_mean_r"] < -0.5

    def test_window_cap_excludes_ancient_trades(self):
        rows = [_trade("orb", "long", 75, -100, 100, 300) for _ in range(30)]
        t = compute_table(rows, now=NOW)
        assert "orb|long|BULL>60" not in t["cells"]  # all older than 180d window

    def test_fallback_cell_aggregates_both_directions(self):
        rows = [_trade("squeeze", "long", 75, 100, 100, 5) for _ in range(5)]
        rows += [_trade("squeeze", "short", 75, -100, 100, 5) for _ in range(5)]
        t = compute_table(rows, now=NOW)
        assert "squeeze|long|BULL>60" in t["cells"]
        assert "squeeze|short|BULL>60" in t["cells"]
        assert t["cells"]["squeeze|BULL>60"]["raw_n"] == 10  # direction-agnostic


class TestSuppressionDecision:
    def _cells_with(self, key, wr, eff_n):
        return {key: {"weighted_mean_r": wr, "eff_n": eff_n, "raw_n": int(eff_n)}}

    def test_hard_skip(self):
        cells = self._cells_with("vwap_fade|short|BULL>60", -0.80, 40)
        out = decide_suppression(cells, "vwap_fade", "short", "BULL>60")
        assert out["action"] == "SKIP"

    def test_soft_reduce(self):
        cells = self._cells_with("rubber_band|long|NEUT46-60", -0.25, 40)
        out = decide_suppression(cells, "rubber_band", "long", "NEUT46-60")
        assert out["action"] == "REDUCE"

    def test_positive_cell_not_suppressed(self):
        # gap_fade is +R in BULL — must be left alone (no hardcoded exception).
        cells = self._cells_with("gap_fade|short|BULL>60", 0.12, 40)
        out = decide_suppression(cells, "gap_fade", "short", "BULL>60")
        assert out["action"] == "NONE"

    def test_thin_sample_not_suppressed(self):
        cells = self._cells_with("vwap_fade|short|BULL>60", -0.90, MIN_EFF_N - 1)
        out = decide_suppression(cells, "vwap_fade", "short", "BULL>60")
        assert out["action"] == "NONE"

    def test_direction_fallback(self):
        # No direction-scoped cell, but the (setup|band) fallback is a deep bleeder.
        cells = self._cells_with("vwap_fade|BULL>60", -0.70, 40)
        out = decide_suppression(cells, "vwap_fade", "short", "BULL>60")
        assert out["action"] == "SKIP"
        assert out["matched_key"] == "vwap_fade|BULL>60"

    def test_direction_cell_preferred_over_fallback(self):
        cells = {
            "vwap_fade|short|BULL>60": {"weighted_mean_r": 0.20, "eff_n": 40, "raw_n": 40},
            "vwap_fade|BULL>60": {"weighted_mean_r": -0.90, "eff_n": 80, "raw_n": 80},
        }
        # short cell is positive -> NONE, must NOT fall through to the negative agg
        out = decide_suppression(cells, "vwap_fade", "short", "BULL>60")
        assert out["action"] == "NONE"
        assert out["matched_key"] == "vwap_fade|short|BULL>60"

    def test_no_band_or_empty(self):
        assert decide_suppression({}, "x", "long", "BULL>60")["action"] == "NONE"
        assert decide_suppression({"x|long|BULL>60": {"weighted_mean_r": -1, "eff_n": 99}},
                                  "x", "long", None)["action"] == "NONE"

    def test_boundary_hard_threshold_inclusive(self):
        cells = self._cells_with("s|long|BEAR<=45", HARD_R, 40)
        assert decide_suppression(cells, "s", "long", "BEAR<=45")["action"] == "SKIP"

    def test_boundary_soft_threshold_inclusive(self):
        cells = self._cells_with("s|long|BEAR<=45", SOFT_R, 40)
        assert decide_suppression(cells, "s", "long", "BEAR<=45")["action"] == "REDUCE"


class _FakeRegime:
    """Minimal regime_engine stub returning a strong-bull score."""
    async def get_current_regime(self):
        return {"state": "CONFIRMED_UP", "composite_score": 75}


def _gate_with_table(mode):
    from services.ai_modules.confidence_gate import ConfidenceGate
    g = ConfidenceGate(db=None)
    g._regime_expectancy = {
        "params": {"min_eff_n": MIN_EFF_N, "hard_r": HARD_R, "soft_r": SOFT_R},
        "cells": {
            "vwap_fade|short|BULL>60": {"weighted_mean_r": -0.85, "eff_n": 50, "raw_n": 50},
        },
    }
    g._regime_suppression_mode = mode
    return g


class TestGateIntegration:
    def test_active_mode_forces_skip(self):
        import asyncio
        g = _gate_with_table("active")
        res = asyncio.run(g.evaluate(
            symbol="TEST", setup_type="vwap_fade_short", direction="short",
            quality_score=95, regime_engine=_FakeRegime(),
        ))
        assert res["decision"] == "SKIP"
        assert res["position_multiplier"] == 0
        rs = res["regime_suppression"]
        assert rs["action"] == "SKIP" and rs["mode"] == "active"
        assert rs["canonical_setup"] == "vwap_fade" and rs["band"] == "BULL>60"

    def test_shadow_mode_records_but_does_not_force_skip(self):
        import asyncio
        g = _gate_with_table("shadow")
        res = asyncio.run(g.evaluate(
            symbol="TEST", setup_type="vwap_fade_short", direction="short",
            quality_score=95, regime_engine=_FakeRegime(),
        ))
        rs = res["regime_suppression"]
        # Shadow still computes the would-action and stamps it...
        assert rs["action"] == "SKIP" and rs["mode"] == "shadow"
        # ...and surfaces it in reasoning as a SHADOW note (not an active veto).
        assert any("[SHADOW]" in r for r in res["reasoning"])

    def test_no_table_no_suppression(self):
        import asyncio
        from services.ai_modules.confidence_gate import ConfidenceGate
        g = ConfidenceGate(db=None)  # no table loaded
        res = asyncio.run(g.evaluate(
            symbol="TEST", setup_type="vwap_fade_short", direction="short",
            quality_score=95, regime_engine=_FakeRegime(),
        ))
        assert res["regime_suppression"] is None
