"""
Diagnose LONG setup model collapse — Phase 13 v2 forensics.

CONTEXT
-------
Phase 13 v2 rejected 10/10 LONG setups with `trades=0`, while 3 SHORT setups
promoted with 400–500 trades each. All LONG setup profiles declare
num_classes=3 triple_barrier_3class, and `revalidate_all.py` loads ONE model
(`direction_predictor_5min`) for AI filtering across every setup.

This script tells us which collapse mode we're in:

  MODE A — 2-class regression:
     direction_predictor_5min is saved binary (num_classes=2), so class-balance
     is a no-op and the model outputs ~0.5 on every bar.

  MODE B — 3-class but UP never wins argmax:
     Model is 3-class but softmax collapses to DOWN/FLAT majority on every bar.
     Even with argmax direction rule, UP is never the top class → trades=0.

  MODE C — 3-class, UP wins argmax rarely (<5% of bars):
     Technically predicting UP but at very low confidence. Backtest threshold
     (default 0.5) filters those out → trades=0.

  MODE D — train_full_universe missing class-balance (CODE INSPECTION):
     direction_predictor_5min is trained by train_full_universe in
     services/ai_modules/timeseries_service.py (~line 1111-1139). That path
     builds DMatrix WITHOUT sample weights and calls xgb.train() with vanilla
     params — it bypasses TimeSeriesGBM.train_from_features (which DOES apply
     class-balance). This means the generic directional model never gets the
     2026-04-20 class-balance fix; only setup-specific models do.

OUTPUT
------
/tmp/long_model_collapse_report.md — human-readable forensic report
/tmp/long_model_collapse_report.json — machine-readable raw data

USAGE (on Spark)
----------------
  cd ~/Trading-and-Analysis-Platform
  git pull
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
      backend/scripts/diagnose_long_model_collapse.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure we can import the backend package layout
HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Load .env like revalidate_all.py does so MONGO_URL / DB_NAME are picked up
# automatically when run from the repo root.
try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv(BACKEND_ROOT / ".env")
except Exception:
    pass

from services.ai_modules.setup_training_config import (  # noqa: E402
    SETUP_TRAINING_PROFILES,
    get_model_name,
)
from services.ai_modules.timeseries_gbm import TimeSeriesGBM  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "META", "GOOGL",
    "AMZN", "TSLA", "NFLX", "BA", "JPM", "XOM", "CVX", "JNJ",
    "UNH", "V", "MA", "DIS",
]
LOOKBACK_BARS_PER_PRED = 60       # what model.predict() needs as history
PREDICTIONS_PER_SYMBOL = 120       # rolling-window predictions per symbol
UP_PROB_THRESHOLD = 0.55           # confidence gate used live
MARKDOWN_REPORT = "/tmp/long_model_collapse_report.md"
JSON_REPORT = "/tmp/long_model_collapse_report.json"

LONG_ONLY_SETUPS = [
    name for name, profiles in SETUP_TRAINING_PROFILES.items()
    if not name.startswith("SHORT_")
    and not any(p.get("direction") == "short" for p in profiles)
]

# Always include the generic direction predictor (that's what revalidate_all.py
# actually uses). We'll also probe setup-specific long models for comparison.
GENERIC_MODEL = "direction_predictor_5min"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("diagnose_long")


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_bars(db, symbol: str, bar_size: str, max_bars: int) -> list[dict]:
    """Fetch most-recent `max_bars` for (symbol, bar_size) in chronological order."""
    try:
        cursor = db["ib_historical_data"].find(
            {"symbol": symbol, "bar_size": bar_size},
            {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1,
             "low": 1, "close": 1, "volume": 1},
        ).sort("date", -1).limit(max_bars)
        rows = await cursor.to_list(length=max_bars)
        rows.reverse()  # chronological
        for r in rows:
            if "date" in r:
                r["timestamp"] = r.pop("date")
        return rows or []
    except Exception as e:
        logger.warning(f"  bars fetch failed for {symbol}/{bar_size}: {e}")
        return []


def _get_model_metadata(db, model_name: str) -> dict:
    """Grab the saved model metadata fields relevant to collapse diagnosis."""
    doc = db["timeseries_models"].find_one(
        {"name": model_name},
        {"_id": 0, "num_classes": 1, "label_scheme": 1, "feature_names": 1,
         "version": 1, "saved_at": 1, "metrics.accuracy": 1,
         "class_weights": 1, "apply_class_balance": 1, "sample_weight_mean": 1},
    )
    if not doc:
        return {"found": False}
    metrics = doc.get("metrics") or {}
    return {
        "found": True,
        "num_classes": doc.get("num_classes"),
        "label_scheme": doc.get("label_scheme"),
        "feature_count": len(doc.get("feature_names") or []),
        "version": doc.get("version"),
        "saved_at": (doc.get("saved_at").isoformat() if doc.get("saved_at")
                     and hasattr(doc["saved_at"], "isoformat")
                     else str(doc.get("saved_at"))),
        "training_accuracy": metrics.get("accuracy"),
        "class_weights": doc.get("class_weights"),
        "apply_class_balance": doc.get("apply_class_balance"),
        "sample_weight_mean": doc.get("sample_weight_mean"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prediction sampling
# ─────────────────────────────────────────────────────────────────────────────

def _sample_predictions(model: TimeSeriesGBM, bars: list[dict], symbol: str) -> list[dict]:
    """Run model.predict over rolling windows. Returns list of prediction dicts."""
    out = []
    if len(bars) < LOOKBACK_BARS_PER_PRED + 5:
        return out
    # Step size so we get ~PREDICTIONS_PER_SYMBOL predictions across available bars
    total = len(bars) - LOOKBACK_BARS_PER_PRED
    step = max(1, total // PREDICTIONS_PER_SYMBOL)
    for i in range(LOOKBACK_BARS_PER_PRED, len(bars), step):
        window = list(reversed(bars[i - LOOKBACK_BARS_PER_PRED:i]))  # predict expects newest-first
        try:
            pred = model.predict(window, symbol=symbol)
        except Exception as e:
            logger.debug(f"  predict err {symbol} @ {i}: {e}")
            continue
        if pred is None:
            continue
        out.append({
            "direction": pred.direction,
            "p_up": float(pred.probability_up),
            "p_down": float(pred.probability_down),
            "confidence": float(pred.confidence),
        })
    return out


def _extract_up_threshold(metadata: dict) -> float:
    """Read the model's calibrated UP threshold from stored metrics.

    Falls back to the global UP_PROB_THRESHOLD (0.55) for legacy models
    that predate the calibration fields. Bounded to [0.45, 0.60] to stay
    inside the configured safety band.
    """
    metrics = (metadata or {}).get("metrics") or {}
    v = metrics.get("calibrated_up_threshold")
    if v is None:
        return UP_PROB_THRESHOLD
    try:
        vf = float(v)
    except (TypeError, ValueError):
        return UP_PROB_THRESHOLD
    if vf <= 0:
        return UP_PROB_THRESHOLD
    return max(0.45, min(0.60, vf))


def _tally(samples: list[dict], up_threshold: float = UP_PROB_THRESHOLD) -> dict:
    """Aggregate directional + probability stats from prediction samples."""
    if not samples:
        return {"n": 0, "error": "no samples"}
    n = len(samples)
    dirs = [s["direction"] for s in samples]
    p_up = np.array([s["p_up"] for s in samples])
    p_down = np.array([s["p_down"] for s in samples])
    return {
        "n": n,
        "pct_up":    round(100 * dirs.count("up")   / n, 1),
        "pct_down":  round(100 * dirs.count("down") / n, 1),
        "pct_flat":  round(100 * dirs.count("flat") / n, 1),
        "p_up_mean":      round(float(p_up.mean()), 4),
        "p_up_p50":       round(float(np.percentile(p_up, 50)), 4),
        "p_up_p95":       round(float(np.percentile(p_up, 95)), 4),
        "p_up_max":       round(float(p_up.max()), 4),
        "p_down_mean":    round(float(p_down.mean()), 4),
        "effective_up_threshold": round(float(up_threshold), 4),
        "pct_up_above_threshold": round(
            100 * float(np.mean(p_up >= up_threshold)), 1
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Classifier — which collapse mode are we in?
# ─────────────────────────────────────────────────────────────────────────────

def _classify(metadata: dict, tally: dict) -> tuple[str, str]:
    """Return (mode_label, human_explanation) for a given model + tally."""
    if not metadata.get("found"):
        return ("MODEL MISSING", "Model not found in timeseries_models.")
    nc = metadata.get("num_classes")
    if nc is not None and int(nc) < 3:
        return (
            "MODE A · 2-class regression",
            f"Model is binary (num_classes={nc}). Class-balance fix does not "
            "address binary class collapse. Rewire path through "
            "train_from_features(num_classes=3).",
        )
    if tally.get("n", 0) == 0:
        return ("NO DATA", "No prediction samples generated — insufficient bars.")
    pct_up = tally["pct_up"]
    pct_up_thr = tally["pct_up_above_threshold"]
    p_up_p95 = tally["p_up_p95"]

    if pct_up < 1.0:
        return (
            "MODE B · 3-class UP never wins argmax",
            f"Only {pct_up}% of predictions have UP as argmax. Softmax "
            f"collapsed to DOWN/FLAT majority. P(up) p95={p_up_p95} — model "
            "barely sees UP class. Likely root cause: generic direction "
            "predictor path (train_full_universe) NEVER applies class-balance "
            "(bypass of train_from_features). This is MODE D at the code "
            "level and MODE B at the behavioural level.",
        )
    if pct_up_thr < 5.0:
        eff_thr = tally.get("effective_up_threshold", UP_PROB_THRESHOLD)
        return (
            "MODE C · Argmax UP but below threshold",
            f"UP argmax {pct_up}% of bars, but only {pct_up_thr}% cross the "
            f"{eff_thr} confidence threshold. Decision gate filters "
            "them out. Fix: calibrate threshold per model or lower to 0.50.",
        )
    return (
        "HEALTHY",
        f"UP argmax {pct_up}% · above-threshold {pct_up_thr}% · p95 P(up)={p_up_p95}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        logger.error("MONGO_URL not set in environment.")
        sys.exit(2)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    logger.info(f"Connected to MongoDB: {db_name}")

    # Build the list of models we want to probe:
    # 1. The GENERIC direction_predictor_5min — what revalidate_all.py actually uses
    # 2. Every LONG setup-specific 5-min model — to compare vs generic
    probe_models: list[tuple[str, str, str]] = [("__GENERIC__", "5 mins", GENERIC_MODEL)]
    for setup in LONG_ONLY_SETUPS:
        for profile in SETUP_TRAINING_PROFILES[setup]:
            bs = profile["bar_size"]
            if bs not in ("5 mins", "1 min"):
                continue  # keep intraday for speed
            probe_models.append((setup, bs, get_model_name(setup, bs)))

    logger.info(f"Probing {len(probe_models)} models across "
                f"{len(DEFAULT_SYMBOLS)} symbols (~{PREDICTIONS_PER_SYMBOL} "
                f"predictions each).")

    # Collect bars once per (symbol, bar_size) combo
    needed_bars: dict[tuple[str, str], list[dict]] = {}
    unique_bar_sizes = {bs for _, bs, _ in probe_models}
    for bs in unique_bar_sizes:
        max_bars = max(
            LOOKBACK_BARS_PER_PRED + PREDICTIONS_PER_SYMBOL * 5,
            600,
        )
        for sym in DEFAULT_SYMBOLS:
            bars = await _get_bars(db, sym, bs, max_bars)
            needed_bars[(sym, bs)] = bars
    bar_counts = {k: len(v) for k, v in needed_bars.items()}
    total_bars = sum(bar_counts.values())
    logger.info(f"Loaded {total_bars:,} bars across {len(bar_counts)} (symbol,bar_size) combos.")

    # For each model: load, probe, tally, classify
    all_results: list[dict] = []
    sync_db = client.delegate[db_name] if hasattr(client, "delegate") else None
    # Use sync-style DB access for timeseries model metadata + loading (GBM
    # expects a sync pymongo-like interface).
    import pymongo
    sync_client = pymongo.MongoClient(mongo_url)
    sync_db = sync_client[db_name]

    for setup_label, bar_size, model_name in probe_models:
        logger.info(f"--- {setup_label} / {bar_size}  → {model_name}")
        meta = _get_model_metadata(sync_db, model_name)
        if not meta["found"]:
            # Known SMB setups that intentionally fall back to the generic
            # direction_predictor_5min until explicitly trained.
            FALLBACK_SETUPS = {"OPENING_DRIVE", "SECOND_CHANCE", "BIG_DOG"}
            if setup_label in FALLBACK_SETUPS:
                logger.info("  ⓘ not in timeseries_models — falls back to generic predictor")
                all_results.append({
                    "setup": setup_label, "bar_size": bar_size, "model": model_name,
                    "metadata": meta, "tally": {"n": 0},
                    "mode": "FALLBACK TO GENERIC",
                    "explanation": "No setup-specific model — live bot uses "
                                   "direction_predictor_5min via predict_for_setup fallback.",
                })
            else:
                logger.info("  ⚠ not in timeseries_models")
                all_results.append({
                    "setup": setup_label, "bar_size": bar_size, "model": model_name,
                    "metadata": meta, "tally": {"n": 0}, "mode": "MODEL MISSING",
                    "explanation": "Model not in DB.",
                })
            continue

        try:
            model = TimeSeriesGBM(model_name=model_name)
            model.set_db(sync_db)
        except Exception as e:
            logger.warning(f"  load failed: {e}")
            all_results.append({
                "setup": setup_label, "bar_size": bar_size, "model": model_name,
                "metadata": meta, "tally": {"n": 0}, "mode": "LOAD FAILED",
                "explanation": str(e),
            })
            continue

        if getattr(model, "_model", None) is None:
            logger.info("  ⚠ model deserialized to None")
            all_results.append({
                "setup": setup_label, "bar_size": bar_size, "model": model_name,
                "metadata": meta, "tally": {"n": 0}, "mode": "LOAD FAILED",
                "explanation": "deserialized to None",
            })
            continue

        # Sample predictions
        all_samples: list[dict] = []
        for sym in DEFAULT_SYMBOLS:
            bars = needed_bars.get((sym, bar_size)) or []
            if len(bars) < LOOKBACK_BARS_PER_PRED + 5:
                continue
            all_samples.extend(_sample_predictions(model, bars, sym))

        tally = _tally(all_samples, up_threshold=_extract_up_threshold(meta))
        mode, explanation = _classify(meta, tally)
        logger.info(
            f"  n={tally.get('n', 0)} up={tally.get('pct_up','-')}%  "
            f"flat={tally.get('pct_flat','-')}%  down={tally.get('pct_down','-')}%  "
            f"p_up_p95={tally.get('p_up_p95','-')}  → {mode}"
        )
        all_results.append({
            "setup": setup_label, "bar_size": bar_size, "model": model_name,
            "metadata": meta, "tally": tally,
            "mode": mode, "explanation": explanation,
        })

    # ── Write reports ────────────────────────────────────────────────
    json_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols_probed": DEFAULT_SYMBOLS,
        "lookback_bars_per_prediction": LOOKBACK_BARS_PER_PRED,
        "target_predictions_per_symbol": PREDICTIONS_PER_SYMBOL,
        "up_prob_threshold": UP_PROB_THRESHOLD,
        "results": all_results,
    }
    Path(JSON_REPORT).write_text(json.dumps(json_out, indent=2, default=str))

    # Markdown
    lines: list[str] = []
    lines.append("# LONG model collapse diagnosis — Phase 13 v2")
    lines.append("")
    lines.append(f"Generated: `{json_out['generated_at']}`  ")
    lines.append(f"Symbols: {', '.join(DEFAULT_SYMBOLS)}  ")
    lines.append(f"Predictions/symbol: ~{PREDICTIONS_PER_SYMBOL} · "
                 f"lookback: {LOOKBACK_BARS_PER_PRED} bars · "
                 f"threshold: {UP_PROB_THRESHOLD}")
    lines.append("")
    lines.append("## Top-level verdict")
    # Highlight the generic direction predictor
    generic = next((r for r in all_results if r["setup"] == "__GENERIC__"), None)
    if generic:
        lines.append(f"**`direction_predictor_5min` mode: {generic['mode']}**  ")
        lines.append(f"> {generic['explanation']}")
        lines.append("")
        lines.append("This is the model `revalidate_all.py` uses for the AI filter. "
                     "If it collapses, every LONG setup shows trades=0 in Phase 1 "
                     "regardless of how well setup-specific long models were "
                     "trained.")
    lines.append("")
    lines.append("## Per-model table")
    lines.append("")
    lines.append("| Setup | Bar | Model | num_classes | label_scheme | "
                 "train_acc | n | %UP | %FLAT | %DOWN | p_up_p95 | "
                 "%UP≥thr | Mode |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in all_results:
        m = r["metadata"]
        t = r["tally"]
        acc = m.get("training_accuracy")
        acc_s = f"{acc*100:.1f}%" if isinstance(acc, (int, float)) else "-"
        lines.append(
            f"| {r['setup']} | {r['bar_size']} | `{r['model']}` | "
            f"{m.get('num_classes','-')} | {m.get('label_scheme','-')} | "
            f"{acc_s} | {t.get('n', 0)} | "
            f"{t.get('pct_up','-')}% | {t.get('pct_flat','-')}% | "
            f"{t.get('pct_down','-')}% | {t.get('p_up_p95','-')} | "
            f"{t.get('pct_up_above_threshold','-')}% | **{r['mode']}** |"
        )
    lines.append("")
    lines.append("## Code-level root cause (already identified)")
    lines.append("")
    lines.append(
        "`train_full_universe` in `services/ai_modules/timeseries_service.py` "
        "(~L1111–L1139) trains `direction_predictor_{bar_size}` by calling "
        "`xgb.train()` directly with a DMatrix that has **no `weight=` "
        "parameter**. This bypasses `TimeSeriesGBM.train_from_features()`, which "
        "IS where the 2026-04-20 class-balance fix was applied. Consequence: "
        "the generic directional model — the one actually used by "
        "`revalidate_all.py` — never gets per-class sample weights, collapses "
        "to the bearish-majority class, and zeroes out every LONG setup's "
        "Phase 1 trade count.")
    lines.append("")
    lines.append("## Recommended fix (Step 2)")
    lines.append("")
    lines.append(
        "Apply `compute_per_sample_class_weights(y, num_classes=3, "
        "clip_ratio=5.0)` inside `train_full_universe`, stack with any "
        "existing sample weights, and pass `weight=` to `xgb.DMatrix`. After "
        "retrain, rerun `revalidate_all.py` — expect LONG setups to show "
        "non-zero Phase 1 trade counts.")
    lines.append("")

    Path(MARKDOWN_REPORT).write_text("\n".join(lines))

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"Markdown report: {MARKDOWN_REPORT}")
    logger.info(f"JSON report:     {JSON_REPORT}")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
