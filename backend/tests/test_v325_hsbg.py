"""v325 HSBG — Horizon-Scaled Bracket Geometry unit + static tests."""
import os
import sys
import py_compile
from pathlib import Path

import pytest


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services.opportunity_evaluator import OpportunityEvaluator  # noqa: E402

EV = OpportunityEvaluator()
SRC = (ROOT / "backend" / "services" / "opportunity_evaluator.py").read_text()


class _RiskParams:
    min_atr_multiplier = 1.0
    max_atr_multiplier = 3.0
    base_atr_multiplier = 1.5


class _Bot:
    risk_params = _RiskParams()
    _db = None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("HSBG_ENABLED", "HSBG_SCALP_FRAC", "HSBG_INTRADAY_FRAC",
              "HSBG_MIN_STOP_PCT_SCALP", "HSBG_MIN_STOP_PCT_INTRADAY",
              "SCALP_DECAY_MINUTES"):
        monkeypatch.delenv(k, raising=False)


# ── helpers ──────────────────────────────────────────────────────────

def test_frac_defaults():
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("scalp") - 0.39) < 1e-9
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("intraday") - 0.35) < 1e-9
    for s in ("swing", "multi_day", "position", "investment", ""):
        assert OpportunityEvaluator._hsbg_horizon_frac(s) == 1.0


def test_frac_env_override(monkeypatch):
    monkeypatch.setenv("HSBG_SCALP_FRAC", "0.5")
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("scalp") - 0.5) < 1e-9


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("HSBG_ENABLED", "0")
    assert OpportunityEvaluator._hsbg_horizon_frac("scalp") == 1.0
    assert OpportunityEvaluator._hsbg_horizon_frac("intraday") == 1.0


def test_hold_minutes_multiday():
    assert OpportunityEvaluator._hsbg_hold_minutes("swing") == 10 * 390.0
    assert OpportunityEvaluator._hsbg_hold_minutes("position") == 30 * 390.0
    assert OpportunityEvaluator._hsbg_hold_minutes("investment") == 90 * 390.0


def test_hold_minutes_scalp_capped():
    assert OpportunityEvaluator._hsbg_hold_minutes("scalp") <= 60.0


def test_reach_envelope_math():
    # Full-session intraday hold from a weekend perspective: hold could be
    # 390 (weekend/premarket) or less intraday — envelope must be
    # daily_atr * sqrt(hold/390) <= daily_atr for intraday.
    env = OpportunityEvaluator._hsbg_reach_envelope(2.0, "intraday")
    assert 0 < env <= 2.0
    # Scalp at <=60min: <= 2.0 * sqrt(60/390) ≈ 0.785
    env_s = OpportunityEvaluator._hsbg_reach_envelope(2.0, "scalp")
    assert env_s <= 2.0 * ((60.0 / 390.0) ** 0.5) + 1e-9
    # Swing: sqrt(10) ≈ 3.16x daily
    env_sw = OpportunityEvaluator._hsbg_reach_envelope(2.0, "swing")
    assert abs(env_sw - 2.0 * (10 ** 0.5)) < 1e-6


# ── style resolution ─────────────────────────────────────────────────

def test_style_scalp_setup_wins():
    assert OpportunityEvaluator._resolve_geometry_style({}, "nine_ema_scalp") == "scalp"
    assert OpportunityEvaluator._resolve_geometry_style(None, "scalp") == "scalp"


def test_style_explicit_multiday_kept():
    a = {"trade_style": "position"}
    assert OpportunityEvaluator._resolve_geometry_style(a, "stage_2_breakout") == "position"


def test_style_generic_defaults_intraday():
    assert OpportunityEvaluator._resolve_geometry_style({}, "no_such_setup_xyz") == "intraday"
    assert OpportunityEvaluator._resolve_geometry_style(
        {"trade_style": "trade_2_hold"}, "no_such_setup_xyz") == "intraday"


# ── stop math ────────────────────────────────────────────────────────

def test_scalp_stop_horizon_scaled():
    # atr=3, entry=100, 'scalp' mult=0.5 → raw Δ=1.5 → ×0.39 = 0.585
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0, "scalp", _Bot(),
                                       trade_style="scalp")
    assert abs(stop - (100.0 - 0.585)) < 1e-6


def test_intraday_stop_horizon_scaled():
    # vwap_continuation mult=1.25 → raw Δ=3.75 → ×0.35 = 1.3125
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0,
                                       "vwap_continuation", _Bot(),
                                       trade_style="intraday")
    assert abs(stop - (100.0 - 1.3125)) < 1e-6


def test_swing_stop_unchanged():
    # breakout mult=1.5 → Δ=4.5 regardless of HSBG
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0,
                                       "breakout", _Bot(), trade_style="swing")
    assert abs(stop - 95.5) < 1e-6


def test_legacy_callers_without_style_unchanged():
    # /retune-stop feeds a 5-min ATR and omits trade_style → exact old math.
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 2.0, "scalp", _Bot())
    assert abs(stop - 99.0) < 1e-6  # 0.5 × 2.0, no horizon scaling


def test_min_stop_pct_floor(monkeypatch):
    # Force a microscopic scaled stop; floor must catch it at 0.15%.
    monkeypatch.setenv("HSBG_SCALP_FRAC", "0.05")
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 0.5, "scalp", _Bot(),
                                       trade_style="scalp")
    # raw Δ = 0.25 → ×0.05 = 0.0125 < floor 0.15 → Δ = 0.15
    assert abs(stop - 99.85) < 1e-6


def test_kill_switch_restores_old_stop(monkeypatch):
    monkeypatch.setenv("HSBG_ENABLED", "0")
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0, "scalp", _Bot(),
                                       trade_style="scalp")
    assert abs(stop - 98.5) < 1e-6  # 0.5 × 3.0, unscaled


def _direction_long():
    from services.trading_bot_service import TradeDirection
    return TradeDirection.LONG


# ── static assertions ────────────────────────────────────────────────

def test_compiles():
    py_compile.compile(
        str(ROOT / "backend" / "services" / "opportunity_evaluator.py"), doraise=True)


def test_reach_gate_present():
    assert "hsbg_pt_unreachable" in SRC
    assert "HSBG_REACH_BLOCK_RATIO" in SRC
    assert "hsbg_reach_gate_block" in SRC
    assert '"hsbg": hsbg_meta' in SRC


def test_detector_cap_present():
    assert "HSBG_DETECTOR_STOP_CAP_MULT" in SRC
    assert "hsbg_stop_capped" in SRC


def test_stop_floor_scaled():
    assert "_floor_mult * float(atr) * (hsbg_frac or 1.0)" in SRC


def test_atr_basis_normalized():
    assert "symbol_adv_cache" in SRC
    assert "fallback_2pct" in SRC
