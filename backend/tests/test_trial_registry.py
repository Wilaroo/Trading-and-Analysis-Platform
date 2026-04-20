"""Tests for trial_registry round-trip + K counting.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_trial_registry.py -v
"""
import pytest

mongomock = pytest.importorskip("mongomock")

from services.ai_modules.trial_registry import (
    record_trial, get_trial_statistics, list_recent_trials, prune_old_trials,
)


def _db():
    return mongomock.MongoClient()["tradecommand"]


def test_record_and_retrieve():
    db = _db()
    t_id = record_trial(
        db, "BREAKOUT", "5 mins", "long", "breakout_5min_predictor",
        sharpe=1.2, sample_length=500, feature_names=["f1", "f2", "f3"],
        hyperparams={"lr": 0.1, "depth": 6}, pt_atr_mult=2.0, sl_atr_mult=1.0, max_bars=12,
    )
    assert t_id is not None
    trials = list_recent_trials(db, "BREAKOUT", "5 mins")
    assert len(trials) == 1
    assert trials[0]["sharpe"] == 1.2


def test_k_counts_unique_feature_hashes():
    db = _db()
    # 3 trials with 2 distinct feature sets
    record_trial(db, "VWAP", "1 day", "long", "m1", 0.8, 200, feature_names=["a", "b"])
    record_trial(db, "VWAP", "1 day", "long", "m2", 1.0, 200, feature_names=["a", "b"])
    record_trial(db, "VWAP", "1 day", "long", "m3", 1.1, 200, feature_names=["a", "b", "c"])
    stats = get_trial_statistics(db, "VWAP", "1 day", "long")
    assert stats["N_trials_total"] == 3
    assert stats["K_independent"] == 2
    assert stats["sharpe_variance"] > 0
    assert stats["sharpe_mean"] > 0


def test_empty_bucket_returns_k1():
    db = _db()
    stats = get_trial_statistics(db, "NONEXISTENT", "5 mins", "long")
    assert stats["N_trials_total"] == 0
    assert stats["K_independent"] == 1   # minimum


def test_prune_old_trials():
    db = _db()
    # Insert 2 "old" records manually
    from datetime import datetime, timezone, timedelta
    old_date = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    db["research_trials"].insert_one({
        "trial_id": "old1", "setup_type": "X", "bar_size": "1 day",
        "trade_side": "long", "model_name": "x", "sharpe": 0.5,
        "sample_length": 100, "feature_set_hash": "h1",
        "trained_at": old_date,
    })
    # Insert a fresh one
    record_trial(db, "X", "1 day", "long", "y", 0.7, 100, feature_names=["f"])
    n = prune_old_trials(db, keep_days=180)
    assert n == 1
    assert db["research_trials"].count_documents({}) == 1
