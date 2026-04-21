"""Ensemble Meta-Labeler live inference (2026-04-21).

Runs the full Phase 8 meta-labeling pipeline at trade-decision time:
  1. Loads directional sub-models for each stacked timeframe (5m/1h/1d).
  2. Loads the setup-specific 1-day sub-model (meta-labeler gating input).
  3. Loads the ensemble_<setup> meta-labeler Booster.
  4. Fetches recent bars for the symbol on each timeframe.
  5. Runs each sub-model to produce per-TF predictions.
  6. Extracts ensemble features (stacked probs + meta features).
  7. Predicts P(win) from the meta-labeler.

Returns a dict the confidence gate can consume for bet-sizing:
  {
      "has_prediction": True|False,
      "p_win": float,                    # 0.0 — 1.0
      "setup_direction": "up"|"down"|"flat",
      "setup_confidence": float,         # sub-model conviction
      "ensemble_name": str,              # e.g. "ensemble_breakout"
      "reason_if_missing": str,          # debugging
  }

Degrades gracefully — returns has_prediction=False whenever:
  - DB unavailable
  - Setup not mapped to any ensemble config
  - ensemble_<setup> model not trained
  - label_scheme != "meta_label_binary" (legacy 3-class ensembles)
  - Setup sub-model not trained
  - Insufficient bars
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import xgboost as xgb

logger = logging.getLogger(__name__)


# ── Scanner setup → ensemble config key (mirrors confidence_gate SETUP_TO_MODEL) ──
# Each scanner detection maps to ONE ensemble to query (first is primary).
SCANNER_TO_ENSEMBLE_KEY: Dict[str, str] = {
    # VWAP family
    "VWAP_BOUNCE": "VWAP", "FIRST_VWAP_PULLBACK": "VWAP", "VWAP_FADE": "VWAP",
    # Breakout family
    "SQUEEZE": "BREAKOUT", "BREAKOUT_CONFIRMED": "BREAKOUT",
    "HOD_BREAKOUT": "BREAKOUT", "APPROACHING_BREAKOUT": "BREAKOUT",
    "APPROACHING_HOD": "BREAKOUT", "APPROACHING_RANGE_BREAK": "RANGE",
    "RANGE_BREAK_CONFIRMED": "RANGE",
    "DAILY_SQUEEZE": "BREAKOUT", "DAILY_BREAKOUT": "BREAKOUT",
    "BASE_BREAKOUT": "BREAKOUT",
    # Mean-reversion
    "RUBBER_BAND": "MEAN_REVERSION", "MEAN_REVERSION": "MEAN_REVERSION",
    # Trend continuation
    "SECOND_CHANCE": "TREND_CONTINUATION", "FASHIONABLY_LATE": "TREND_CONTINUATION",
    "HITCHHIKER": "TREND_CONTINUATION", "TREND_CONTINUATION": "TREND_CONTINUATION",
    # ORB
    "OPENING_DRIVE": "ORB", "ORB_LONG_CONFIRMED": "ORB", "APPROACHING_ORB": "ORB",
    # Gap
    "GAP_GIVE_GO": "GAP_AND_GO", "GAP_FADE": "GAP_AND_GO", "GAP_FADE_DAILY": "GAP_AND_GO",
    # Scalp
    "9_EMA_SCALP": "SCALP", "ABC_SCALP": "SCALP", "SPENCER_SCALP": "SCALP",
    "PUPPY_DOG": "SCALP",
    # Momentum
    "BIG_DOG": "MOMENTUM", "TIDAL_WAVE": "MOMENTUM",
    "EARNINGS_MOMENTUM": "MOMENTUM", "SECTOR_ROTATION": "MOMENTUM",
    "RELATIVE_STRENGTH_POSITION": "MOMENTUM",
    # Reversal
    "VOLUME_CAPITULATION": "REVERSAL", "BACKSIDE": "REVERSAL",
    "ACCUMULATION_ENTRY": "REVERSAL", "SHORT_SQUEEZE_FADE": "REVERSAL",
    # Chart
    "CHART_PATTERN": "BREAKOUT",
    # Short-side (fall back to REVERSAL; ensembles are direction-agnostic WIN/LOSS)
    "OFF_SIDES_SHORT": "REVERSAL", "BREAKDOWN_CONFIRMED": "REVERSAL",
}


def _fetch_bars(db, symbol: str, bar_size: str, limit: int = 250) -> List[Dict]:
    """Fetch bars in chronological order (oldest → newest)."""
    cursor = db["ib_historical_data"].find(
        {"symbol": symbol, "bar_size": bar_size},
        {"_id": 0},
    ).sort("date", -1).limit(limit)
    bars = list(cursor)
    bars.reverse()
    return bars


def _canonical_direction_from_raw(raw_row: np.ndarray) -> Dict[str, Any]:
    """Convert a Booster prediction row to {direction, prob_up, prob_down, confidence}."""
    if raw_row.ndim >= 1 and raw_row.size >= 3:
        # 3-class [DOWN, FLAT, UP]
        pdn, pfl, pup = float(raw_row[0]), float(raw_row[1]), float(raw_row[2])
        cls = int(np.argmax([pdn, pfl, pup]))
        direction = ("down", "flat", "up")[cls]
        conf = (pdn, pfl, pup)[cls]
        return {"direction": direction, "prob_up": pup, "prob_down": pdn,
                "prob_flat": pfl, "confidence": conf}
    # Binary: scalar p_up
    pup = float(raw_row) if np.ndim(raw_row) == 0 else float(raw_row[0])
    pdn = 1.0 - pup
    if pup > 0.55:
        direction, conf = "up", pup
    elif pdn > 0.55:
        direction, conf = "down", pdn
    else:
        direction, conf = "flat", 0.5
    return {"direction": direction, "prob_up": pup, "prob_down": pdn,
            "prob_flat": 0.0, "confidence": conf}


def _predict_gbm(gbm, bars: List[Dict], symbol: str) -> Optional[Dict[str, Any]]:
    """Run TimeSeriesGBM.predict and return a plain dict (with raw probs)."""
    try:
        pred = gbm.predict(bars, symbol=symbol)
    except Exception as exc:
        logger.debug(f"[ensemble_live] sub-model predict crash for {symbol}: {exc}")
        return None
    if pred is None:
        return None
    return {
        "direction": pred.direction,
        "prob_up": float(pred.probability_up),
        "prob_down": float(pred.probability_down),
        "confidence": float(pred.confidence),
    }


def predict_meta_label_p_win(
    db,
    symbol: str,
    setup_type: str,
) -> Dict[str, Any]:
    """Run the ensemble meta-labeler for this symbol+setup.

    This is a SYNCHRONOUS function. Run inside asyncio.run_in_executor when
    called from async code (the confidence gate does this).
    """
    def miss(why):
        return {"has_prediction": False, "reason_if_missing": why}

    if db is None:
        return miss("no_db")

    # ── 1. Map scanner setup → ensemble config key ──
    base = setup_type.upper().replace("_LONG", "").replace("_SHORT", "")
    ens_key = SCANNER_TO_ENSEMBLE_KEY.get(base)
    if ens_key is None:
        # Pass-through: the caller may already be passing a canonical ensemble
        # config key (e.g. "REVERSAL", "BREAKOUT", "MEAN_REVERSION"). Accept it.
        try:
            from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS as _ens_cfg_check
            if base in _ens_cfg_check:
                ens_key = base
        except Exception:
            pass
    if ens_key is None:
        return miss(f"unmapped_setup:{base}")

    try:
        from services.ai_modules.ensemble_model import (
            ENSEMBLE_MODEL_CONFIGS, STACKED_TIMEFRAMES, extract_ensemble_features,
            ENSEMBLE_FEATURE_NAMES,
        )
        from services.ai_modules.setup_training_config import (
            get_model_name as _ens_model_name,
        )
        from services.ai_modules.timeseries_gbm import TimeSeriesGBM
        from services.ai_modules.training_pipeline import BAR_SIZE_CONFIGS
    except Exception as exc:
        return miss(f"import_error:{exc}")

    # Mirror the in-pipeline DIRECTIONAL_MODEL_NAMES map (defined inside
    # training_pipeline.run_pipeline, not importable from module scope).
    DIRECTIONAL_MODEL_NAMES = {
        "1 min": "direction_predictor_1min",
        "5 mins": "direction_predictor_5min",
        "15 mins": "direction_predictor_15min",
        "30 mins": "direction_predictor_30min",
        "1 hour": "direction_predictor_1hour",
        "1 day": "direction_predictor_daily",
        "1 week": "direction_predictor_weekly",
    }

    ens_cfg = ENSEMBLE_MODEL_CONFIGS.get(ens_key)
    if ens_cfg is None:
        return miss(f"no_ensemble_config:{ens_key}")

    ens_model_name = ens_cfg["model_name"]

    # ── 2. Load ensemble meta-labeler & verify binary ──
    ens_doc = db["timeseries_models"].find_one(
        {"name": ens_model_name},
        {"_id": 0, "label_scheme": 1, "metrics": 1},
    )
    if not ens_doc:
        return miss(f"ensemble_not_trained:{ens_model_name}")
    if ens_doc.get("label_scheme") != "meta_label_binary":
        return miss(f"ensemble_not_binary:{ens_model_name}")

    ens_gbm = TimeSeriesGBM(model_name=ens_model_name, forecast_horizon=5)
    ens_gbm.set_db(db)
    if ens_gbm._model is None:
        return miss(f"ensemble_load_failed:{ens_model_name}")

    # ── 3. Load directional sub-models ──
    sub_gbms: Dict[str, "TimeSeriesGBM"] = {}
    for tf in STACKED_TIMEFRAMES:
        sub_name = DIRECTIONAL_MODEL_NAMES.get(tf, f"direction_predictor_{tf.replace(' ', '_')}")
        sub_fh = BAR_SIZE_CONFIGS.get(tf, {}).get("forecast_horizon", 5)
        sub = TimeSeriesGBM(model_name=sub_name, forecast_horizon=sub_fh)
        sub.set_db(db)
        if sub._model is not None:
            sub_gbms[tf] = sub

    if not sub_gbms:
        return miss("no_sub_models_loaded")

    # ── 4. Load setup-specific 1-day sub-model ──
    setup_sub_name = _ens_model_name(ens_key, "1 day")
    setup_sub = TimeSeriesGBM(model_name=setup_sub_name, forecast_horizon=5)
    setup_sub.set_db(db)
    if setup_sub._model is None:
        return miss(f"setup_sub_not_trained:{setup_sub_name}")

    # ── 5. Run per-timeframe sub-model predictions ──
    sub_predictions: Dict[str, Dict[str, Any]] = {}
    for tf, sub in sub_gbms.items():
        bars = _fetch_bars(db, symbol, tf, limit=250)
        if len(bars) < 50:
            continue
        pred = _predict_gbm(sub, bars, symbol)
        if pred:
            sub_predictions[tf] = pred

    if not sub_predictions:
        return miss("no_sub_predictions_generated")

    # ── 6. Run setup sub-model on 1d bars ──
    daily_bars = _fetch_bars(db, symbol, "1 day", limit=250)
    if len(daily_bars) < 50:
        return miss("insufficient_daily_bars")
    setup_pred = _predict_gbm(setup_sub, daily_bars, symbol)
    if setup_pred is None:
        return miss("setup_predict_failed")

    # ── 7. Extract ensemble features ──
    feats = extract_ensemble_features(sub_predictions, setup_predictions=[setup_pred])

    # ── 8. Predict p_win ──
    ens_feat_names = list(ens_gbm._feature_names) if ens_gbm._feature_names else list(ENSEMBLE_FEATURE_NAMES)
    vec = np.array([[feats.get(f, 0.0) for f in ens_feat_names]], dtype=np.float32)
    dm = xgb.DMatrix(vec, feature_names=ens_feat_names)
    try:
        raw = ens_gbm._model.predict(dm)
    except Exception as exc:
        return miss(f"meta_predict_crash:{exc}")

    # Binary classifier → scalar p(WIN)
    if raw.ndim == 1:
        p_win = float(raw[0])
    elif raw.ndim == 2 and raw.shape[1] == 2:
        p_win = float(raw[0][1])  # column 1 = positive class
    else:
        return miss(f"meta_unexpected_shape:{raw.shape}")

    # Clamp
    p_win = float(max(0.0, min(1.0, p_win)))

    return {
        "has_prediction": True,
        "p_win": p_win,
        "ensemble_name": ens_model_name,
        "setup_direction": setup_pred["direction"],
        "setup_confidence": setup_pred["confidence"],
        "ensemble_accuracy": float((ens_doc.get("metrics") or {}).get("accuracy", 0.0)),
        "sub_timeframes_used": list(sub_predictions.keys()),
    }


# ── Bet-sizing helper (pure function, easy to unit-test) ───────────────────
def bet_size_multiplier_from_p_win(p_win: float) -> float:
    """Map P(win) to a position-size multiplier.

    Tiered ramp (Kelly-inspired, capped to prevent over-leveraging):
      p_win < 0.50          → 0.0   (force SKIP)
      0.50 ≤ p_win < 0.55   → 0.50  (half size — borderline edge)
      0.55 ≤ p_win < 0.65   → 1.00  (full size)
      0.65 ≤ p_win < 0.75   → 1.25  (confident — scale up)
      p_win ≥ 0.75          → 1.50  (max boost)
    """
    if p_win < 0.50:
        return 0.0
    if p_win < 0.55:
        return 0.50
    if p_win < 0.65:
        return 1.00
    if p_win < 0.75:
        return 1.25
    return 1.50
