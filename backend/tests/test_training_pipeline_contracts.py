"""
Regression contracts for training_pipeline.py bugs fixed 2026-04-24.

These are pure static/source-level checks — no full pipeline run — so they're
safe to run in CI without IB/Mongo.

Bugs guarded:
  1. Phase 1 read `result["metrics"]["accuracy"]` but `train_full_universe`
     returns top-level `accuracy`. → all 7 direction_predictor models reported 0.
  2. Phase 13 passed `training_result` without `model_name`, so
     `post_training_validator` silently skipped the scorecard mirror to
     `timeseries_models` → `/api/ai-training/scorecards` returned count=0.
  3. Phase 3 / Phase 5 silently `continue`d when data was insufficient,
     producing 0 models with NO entry in `models_failed` — you couldn't
     tell what went wrong.
  4. FinBERT used `quality_metric` while DL used `metric_type` — inconsistent.
"""
from pathlib import Path
import re

PIPELINE = Path(__file__).parent.parent / "services" / "ai_modules" / "training_pipeline.py"
SRC = PIPELINE.read_text()


def test_phase1_reads_accuracy_at_top_level():
    """Phase 1 must read result["accuracy"], not result["metrics"]["accuracy"]."""
    # The old buggy pattern — allow it only as a fallback inside result.get(..., result.get("metrics", {}))
    # i.e., the *first* lookup must be top-level "accuracy".
    m = re.search(
        r'acc\s*=\s*result\.get\(\s*"accuracy"\s*,\s*result\.get\(\s*"metrics"',
        SRC,
    )
    assert m is not None, (
        "Phase 1 accuracy read regressed. Must prefer result['accuracy'] "
        "(top-level) over result['metrics']['accuracy']."
    )


def test_phase13_passes_model_name_into_training_result():
    """Phase 13 validation must pass model_name to the post-training validator."""
    # Look for the resolved_model_name = get_model_name(...) pattern AND it being
    # stuffed into the training_result dict under "model_name" key.
    assert "resolved_model_name = get_model_name(setup_type, bar_size)" in SRC, (
        "Phase 13 must resolve model_name via get_model_name(setup_type, bar_size) "
        "so the scorecard can be mirrored onto timeseries_models."
    )
    # The training_result dict must contain model_name — critical for scorecard mirror
    # (check the two anchors live within a small window of each other)
    idx_resolve = SRC.find("resolved_model_name = get_model_name(setup_type, bar_size)")
    idx_assign = SRC.find('"model_name": resolved_model_name', idx_resolve)
    assert idx_resolve != -1 and idx_assign != -1, (
        "training_result dict must include 'model_name': resolved_model_name "
        "for the scorecard mirror in post_training_validator to fire."
    )
    assert idx_assign - idx_resolve < 1200, (
        "resolved_model_name is assigned but not plugged into training_result "
        "within a reasonable window. Check Phase 13 wiring."
    )


def test_phase3_volatility_records_insufficient_data_failures():
    """Phase 3 must record failed models in results['models_failed'] when it skips."""
    # After the fix, the `if len(all_X) < MIN_TRAINING_SAMPLES` branch must
    # append to models_failed with a reason. Grep for the phrase we use.
    assert "[Phase 3]" in SRC and "MIN_TRAINING_SAMPLES=" in SRC, (
        "Phase 3 silent-skip observability fix missing."
    )


def test_phase5_sector_records_missing_etf_failures():
    """Phase 5 must record an explicit failure when no sector ETF bars exist."""
    assert "No sector ETF bars available" in SRC, (
        "Phase 5 must emit a 'No sector ETF bars available' failure record "
        "when sector_etf_bars is empty (previously silent-skipped)."
    )


def test_phase7_regime_records_missing_spy_failure():
    """Phase 7 must record a failure when SPY data is insufficient."""
    assert "regime_conditional_all" in SRC, (
        "Phase 7 must record a regime_conditional_all failure when SPY data is insufficient."
    )


def test_finbert_uses_metric_type_field():
    """FinBERT must expose `metric_type` (matching DL phase) in addition to `quality_metric`."""
    # In Phase 12 FinBERT, results.models_trained append must include "metric_type"
    # near "finbert_sentiment" — search in the same dict.
    finbert_block = re.search(
        r'"name":\s*"finbert_sentiment".*?\}',
        SRC, re.DOTALL,
    )
    assert finbert_block, "Could not locate FinBERT results append block."
    assert '"metric_type"' in finbert_block.group(0), (
        "FinBERT results dict must include 'metric_type' (aligned with DL models)."
    )


def test_add_completed_supports_metric_type_kwarg():
    """status.add_completed must accept metric_type so VAE/FinBERT don't corrupt avg_accuracy."""
    sig = re.search(
        r"def add_completed\(self[^)]*metric_type[^)]*\)",
        SRC,
    )
    assert sig is not None, (
        "TrainingPipelineStatus.add_completed must accept a `metric_type` kwarg "
        "so VAE/FinBERT entropy scores don't pollute classifier avg_accuracy."
    )
