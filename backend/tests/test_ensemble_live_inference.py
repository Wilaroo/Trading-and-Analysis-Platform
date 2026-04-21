"""Tests for Phase 8 ensemble meta-labeler live inference & bet-sizing (2026-04-21).

The live inference module is heavy (imports training_pipeline, runs XGBoost
predictions against DB-loaded models), so most tests mock the DB. The bet-sizing
helper is a pure function and is exercised directly.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Bet-sizing pure function ──────────────────────────────────────────────

from services.ai_modules.ensemble_live_inference import (
    SCANNER_TO_ENSEMBLE_KEY, bet_size_multiplier_from_p_win, predict_meta_label_p_win,
    clear_model_cache, _cached_gbm_load, _MODEL_CACHE, MODEL_CACHE_TTL_S,
)


def test_bet_size_forces_zero_below_50_pct():
    """P(win) < 0.5 must force skip (multiplier = 0)."""
    assert bet_size_multiplier_from_p_win(0.0) == 0.0
    assert bet_size_multiplier_from_p_win(0.25) == 0.0
    assert bet_size_multiplier_from_p_win(0.49) == 0.0
    # Boundary: exactly 0.50 is NOT a skip — gets the half-size rung
    assert bet_size_multiplier_from_p_win(0.50) == 0.50


def test_bet_size_monotonic_ramp():
    """Multiplier must be non-decreasing across p_win."""
    levels = [0.50, 0.54, 0.55, 0.63, 0.65, 0.70, 0.75, 0.80, 0.95]
    mults = [bet_size_multiplier_from_p_win(p) for p in levels]
    assert mults == sorted(mults), "Bet-size multiplier must not decrease with higher p_win"


def test_bet_size_specific_rungs():
    """Verify the exact tiered ramp."""
    assert bet_size_multiplier_from_p_win(0.50) == 0.50
    assert bet_size_multiplier_from_p_win(0.54) == 0.50
    assert bet_size_multiplier_from_p_win(0.55) == 1.00
    assert bet_size_multiplier_from_p_win(0.64) == 1.00
    assert bet_size_multiplier_from_p_win(0.65) == 1.25
    assert bet_size_multiplier_from_p_win(0.74) == 1.25
    assert bet_size_multiplier_from_p_win(0.75) == 1.50
    assert bet_size_multiplier_from_p_win(0.99) == 1.50


def test_bet_size_never_exceeds_cap():
    """No overflow above the cap (prevents runaway leverage on near-perfect predictions)."""
    for p in np.linspace(0.0, 1.0, 101):
        assert bet_size_multiplier_from_p_win(float(p)) <= 1.50


# ── Scanner-to-ensemble mapping coverage ──────────────────────────────────

def test_scanner_map_covers_all_major_setup_families():
    """Every Tier-1 scanner setup must route to a valid ensemble key."""
    from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS
    valid_keys = set(ENSEMBLE_MODEL_CONFIGS.keys())

    # Sanity: must have the core trading families mapped
    required_scanners = [
        "VWAP_BOUNCE", "SQUEEZE", "BREAKOUT_CONFIRMED", "HOD_BREAKOUT",
        "RUBBER_BAND", "MEAN_REVERSION", "OPENING_DRIVE", "ORB_LONG_CONFIRMED",
        "GAP_GIVE_GO", "9_EMA_SCALP", "BIG_DOG", "VOLUME_CAPITULATION",
        "TREND_CONTINUATION", "BACKSIDE",
    ]
    for scanner in required_scanners:
        assert scanner in SCANNER_TO_ENSEMBLE_KEY, f"Scanner {scanner} not mapped"
        ens_key = SCANNER_TO_ENSEMBLE_KEY[scanner]
        assert ens_key in valid_keys, (
            f"{scanner} maps to {ens_key} which is not a valid ENSEMBLE_MODEL_CONFIG key"
        )


# ── Live inference degrades gracefully ────────────────────────────────────

def test_predict_returns_miss_on_null_db():
    result = predict_meta_label_p_win(db=None, symbol="AAPL", setup_type="BREAKOUT")
    assert result["has_prediction"] is False
    assert result["reason_if_missing"] == "no_db"


def test_predict_returns_miss_on_unmapped_setup():
    db = MagicMock()
    result = predict_meta_label_p_win(db=db, symbol="AAPL", setup_type="UNKNOWN_SETUP")
    assert result["has_prediction"] is False
    assert result["reason_if_missing"].startswith("unmapped_setup:")


def test_predict_returns_miss_when_ensemble_not_trained():
    db = MagicMock()
    # find_one returns None — ensemble doc missing
    db["timeseries_models"].find_one.return_value = None
    result = predict_meta_label_p_win(db=db, symbol="AAPL", setup_type="BREAKOUT_CONFIRMED")
    assert result["has_prediction"] is False
    assert "ensemble_not_trained" in result["reason_if_missing"]


def test_predict_returns_miss_when_ensemble_not_binary():
    """Legacy 3-class ensembles (pre-Phase-8-fix) must be filtered out."""
    db = MagicMock()
    db["timeseries_models"].find_one.return_value = {
        "label_scheme": "triple_barrier_3class",  # legacy
        "metrics": {"accuracy": 0.45},
    }
    result = predict_meta_label_p_win(db=db, symbol="AAPL", setup_type="BREAKOUT_CONFIRMED")
    assert result["has_prediction"] is False
    assert "ensemble_not_binary" in result["reason_if_missing"]


# ── Full inference path (mocked models) ───────────────────────────────────

def test_predict_full_path_returns_p_win_in_0_1():
    """Stitch mocks together and verify we extract a valid p_win."""
    db = MagicMock()
    # Return a valid ensemble doc
    db["timeseries_models"].find_one.return_value = {
        "label_scheme": "meta_label_binary",
        "metrics": {"accuracy": 0.66},
    }

    # Mock TimeSeriesGBM to return predictable predictions
    # Patch at the source (imported lazily inside predict_meta_label_p_win)
    with patch(
        "services.ai_modules.timeseries_gbm.TimeSeriesGBM"
    ) as mock_gbm_cls, patch(
        "services.ai_modules.ensemble_live_inference._fetch_bars"
    ) as mock_fetch:
        mock_fetch.return_value = [{"close": 100.0, "open": 99.0, "high": 101.0,
                                     "low": 98.5, "volume": 1_000_000,
                                     "date": "2026-04-01"}] * 100

        # Each GBM gets a sane _model + _feature_names + predict
        def _make_mock_gbm(model_name=None, forecast_horizon=None):
            m = MagicMock()
            m._model = MagicMock()
            m._feature_names = [f"f{i}" for i in range(18)]

            if "ensemble_" in (model_name or ""):
                # Meta-labeler Booster: return scalar p_win batch
                m._model.predict.return_value = np.array([0.72], dtype=np.float32)
            else:
                # Sub-model / setup-model: returns a Prediction object from .predict()
                from services.ai_modules.timeseries_gbm import Prediction
                pred = Prediction(
                    symbol="AAPL",
                    direction="up",
                    probability_up=0.6,
                    probability_down=0.3,
                    confidence=0.6,
                    model_version="v1",
                    timestamp="2026-04-01",
                )
                m.predict.return_value = pred
            return m

        mock_gbm_cls.side_effect = _make_mock_gbm

        result = predict_meta_label_p_win(db=db, symbol="AAPL", setup_type="BREAKOUT_CONFIRMED")

    assert result["has_prediction"] is True, f"Expected has_prediction, got {result}"
    assert 0.0 <= result["p_win"] <= 1.0
    assert abs(result["p_win"] - 0.72) < 1e-5
    assert result["ensemble_name"] == "ensemble_breakout"
    assert result["setup_direction"] == "up"
    assert "sub_timeframes_used" in result


# ── Model cache tests ─────────────────────────────────────────────────────

def test_cache_stores_loaded_model_and_reuses_it():
    """Second call with same model_name must NOT construct a new TimeSeriesGBM."""
    clear_model_cache()
    db = MagicMock()
    construction_count = {"n": 0}

    def _make_mock_gbm(model_name=None, forecast_horizon=None):
        construction_count["n"] += 1
        m = MagicMock()
        m._model = MagicMock()
        m._feature_names = ["f0", "f1"]
        return m

    with patch("services.ai_modules.timeseries_gbm.TimeSeriesGBM", side_effect=_make_mock_gbm):
        g1 = _cached_gbm_load(db, "direction_predictor_daily", 5)
        g2 = _cached_gbm_load(db, "direction_predictor_daily", 5)
        g3 = _cached_gbm_load(db, "direction_predictor_daily", 5)

    assert g1 is g2 is g3, "Cache must return the same object"
    assert construction_count["n"] == 1, (
        f"Expected 1 construction, got {construction_count['n']} (cache miss)"
    )
    clear_model_cache()


def test_cache_returns_none_on_missing_model_and_does_not_cache():
    """If the Booster doesn't load (no doc in Mongo), cache must NOT poison itself."""
    clear_model_cache()
    db = MagicMock()

    def _make_broken_gbm(model_name=None, forecast_horizon=None):
        m = MagicMock()
        m._model = None  # simulate failed load
        m._feature_names = []
        return m

    with patch("services.ai_modules.timeseries_gbm.TimeSeriesGBM", side_effect=_make_broken_gbm):
        g = _cached_gbm_load(db, "never_trained_model", 5)

    assert g is None
    assert "never_trained_model" not in _MODEL_CACHE, (
        "Cache must not store None — next retrain must have a clean slot to fill"
    )


def test_clear_model_cache_empties_all_entries():
    clear_model_cache()
    db = MagicMock()
    with patch("services.ai_modules.timeseries_gbm.TimeSeriesGBM") as cls:
        cls.side_effect = lambda model_name=None, forecast_horizon=None: type(
            "G", (), {"_model": object(), "_feature_names": [], "set_db": lambda self, d: None}
        )()
        _cached_gbm_load(db, "m1", 5)
        _cached_gbm_load(db, "m2", 5)

    assert len(_MODEL_CACHE) == 2
    evicted = clear_model_cache()
    assert evicted == 2
    assert len(_MODEL_CACHE) == 0


def test_cache_ttl_is_ten_minutes():
    """Lock in the 10-minute TTL as a stable contract."""
    assert MODEL_CACHE_TTL_S == 600
