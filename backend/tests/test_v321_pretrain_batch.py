"""
v321 — Pre-retrain batch: Tier 2b (frozen hold-out) + Tier 3b (PBO gate,
shadow) + Tier 3a-lite (feature baselines).

Synthetic pinning tests — container/DGX-safe: no real DB, no IB, no GPU.

Pins:
  1. frozen_holdout: env knob, cutoff math, ISO + IB-compact timestamp parsing,
     filtering, disabled mode, model-doc stamp.
  2. Cache identity: NVMe bar/feature paths and the Mongo feature-cache key
     embed the hold-out setting (auto-invalidation).
  3. pbo_gate_check: pass / shadow_block / block / off / no-CPCV-data.
  4. _save_model end-to-end with a fake DB: shadow mode logs + stamps but
     still promotes; enforce mode returns rejected_pbo_gate and never writes
     the live collection; passing models promote with frozen_holdout +
     feature_baseline stamps in the doc.
  5. compute_feature_baseline: stats/bins correctness, env off, bad input.

Run (DGX, from backend/):  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_v321_pretrain_batch.py -v
Run (container):           cd /app/backend && python -m pytest tests/test_v321_pretrain_batch.py -v
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ai_modules.frozen_holdout import (  # noqa: E402
    _bar_day,
    apply_frozen_holdout,
    frozen_holdout_stamp,
    holdout_cutoff_iso,
    holdout_days,
)
from services.ai_modules.feature_baseline import compute_feature_baseline  # noqa: E402
from services.ai_modules.timeseries_gbm import (  # noqa: E402
    ModelMetrics,
    TimeSeriesGBM,
    pbo_gate_check,
)
from services.ai_modules import training_pipeline as tp  # noqa: E402


# ── 1. frozen hold-out ───────────────────────────────────────────────────────

def test_holdout_days_env(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "60")
    assert holdout_days() == 60
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "0")
    assert holdout_days() == 0
    assert holdout_cutoff_iso() is None
    assert frozen_holdout_stamp() is None
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "garbage")
    assert holdout_days() == 45  # default on bad input


def test_bar_day_parses_both_formats():
    assert _bar_day("2026-06-11T15:30:00") == "2026-06-11"
    assert _bar_day("2026-06-11") == "2026-06-11"
    assert _bar_day("20260611 15:30:00") == "2026-06-11"
    assert _bar_day("20260611") == "2026-06-11"
    assert _bar_day(None) == ""


def _mk_bars(n_old, n_recent, key="timestamp", fmt="iso"):
    now = datetime.now(timezone.utc)
    bars = []
    for k in range(n_old):
        d = now - timedelta(days=400 - k)
        ts = d.strftime("%Y-%m-%dT10:00:00") if fmt == "iso" else d.strftime("%Y%m%d 10:00:00")
        bars.append({key: ts, "close": 100.0 + k})
    for k in range(n_recent):
        d = now - timedelta(days=n_recent - 1 - k)  # the last n_recent days
        ts = d.strftime("%Y-%m-%dT10:00:00") if fmt == "iso" else d.strftime("%Y%m%d 10:00:00")
        bars.append({key: ts, "close": 200.0 + k})
    return bars


def test_apply_frozen_holdout_filters_recent(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    bars = _mk_bars(n_old=100, n_recent=10)
    kept = apply_frozen_holdout(bars, "TEST", "1 day")
    assert len(kept) == 100, "the 10 most-recent bars must be frozen out"
    assert all(b["close"] < 200 for b in kept)


def test_apply_frozen_holdout_handles_date_key_and_ib_format(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    bars = _mk_bars(50, 5, key="date", fmt="ib")
    kept = apply_frozen_holdout(bars, "TEST", "5 mins")
    assert len(kept) == 50


def test_apply_frozen_holdout_disabled(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "0")
    bars = _mk_bars(10, 10)
    assert apply_frozen_holdout(bars, "TEST", "1 day") is bars  # untouched
    assert apply_frozen_holdout(None) is None
    assert apply_frozen_holdout([]) == []


def test_frozen_holdout_stamp(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    stamp = frozen_holdout_stamp()
    assert stamp["days"] == 45
    expected = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    assert stamp["cutoff"] == expected


# ── 2. cache identity embeds the hold-out setting ────────────────────────────

def test_nvme_cache_paths_embed_holdout(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    assert "_fh45.pkl" in tp._bar_cache_path("AAPL", "1 day")
    assert "_fh45.npy" in tp._feature_cache_path("AAPL", "1 day")
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "30")
    assert "_fh30.pkl" in tp._bar_cache_path("AAPL", "1 day")
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "0")
    assert "_fh0.pkl" in tp._bar_cache_path("AAPL", "1 day")


def test_mongo_feature_cache_key_embeds_holdout(monkeypatch):
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    m = TimeSeriesGBM(model_name="t_cachekey", forecast_horizon=5)
    key = m._get_feature_cache_key("AAPL", "1 day")
    assert key.endswith("_fh45")
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "60")
    assert m._get_feature_cache_key("AAPL", "1 day").endswith("_fh60")


# ── 3. PBO gate verdicts ─────────────────────────────────────────────────────

GOOD = {"cpcv_n_folds": 14, "cpcv_pbo": 0.07, "cpcv_edge_mean": 0.08}
BAD = {"cpcv_n_folds": 14, "cpcv_pbo": 0.64, "cpcv_edge_mean": -0.01}


def test_pbo_gate_pass(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "shadow")
    verdict, reason = pbo_gate_check(GOOD, "m")
    assert verdict == "pass"
    assert "PBO 0.07" in reason


def test_pbo_gate_shadow_block(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "shadow")
    verdict, reason = pbo_gate_check(BAD, "m")
    assert verdict == "shadow_block"
    assert "PBO 0.64" in reason and "edge" in reason


def test_pbo_gate_enforce_block(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "enforce")
    verdict, _ = pbo_gate_check(BAD, "m")
    assert verdict == "block"
    verdict, _ = pbo_gate_check(GOOD, "m")
    assert verdict == "pass"


def test_pbo_gate_off_and_no_cpcv(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "off")
    assert pbo_gate_check(BAD, "m")[0] == "pass"
    monkeypatch.setenv("TB_PBO_GATE", "enforce")
    assert pbo_gate_check({"cpcv_n_folds": 0}, "m")[0] == "pass"  # nothing to judge


def test_pbo_gate_custom_thresholds(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "enforce")
    monkeypatch.setenv("TB_PBO_MAX", "0.70")
    monkeypatch.setenv("TB_CPCV_MIN_EDGE", "-0.05")
    assert pbo_gate_check(BAD, "m")[0] == "pass"  # loosened thresholds


# ── 4. _save_model end-to-end with a fake DB ─────────────────────────────────

class _FakeCol:
    def __init__(self):
        self.docs = []

    def insert_one(self, d):
        self.docs.append(dict(d))

    def update_one(self, q, u, upsert=False):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in q.items()):
                doc.update(u.get("$set", {}))
                return
        if upsert:
            self.docs.append({**q, **u.get("$set", {})})

    def find_one(self, q, proj=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in q.items()):
                return doc
        return None


class _FakeDB:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _FakeCol())


def _trained_model(monkeypatch, cpcv_overrides=None):
    """Train a tiny healthy model, then override its CPCV report card."""
    monkeypatch.setenv("TB_GBM_CPCV", "0")  # keep the fit fast; we inject CPCV
    rng = np.random.default_rng(5)
    X = rng.normal(size=(900, 8)).astype(np.float32)
    latent = X[:, 0] + 0.5 * X[:, 1]
    y = np.where(latent > 0.4, 2, np.where(latent < -0.4, 0, 1)).astype(np.int64)
    m = TimeSeriesGBM(model_name="t_gate_v321", forecast_horizon=5)
    m.params["device"] = "cpu"
    m.train_from_features(
        X, y, [f"f{i}" for i in range(8)], skip_save=True,
        num_boost_round=30, early_stopping_rounds=10, num_classes=3,
    )
    for k, v in (cpcv_overrides or {}).items():
        setattr(m._metrics, k, v)
    m._db = _FakeDB()
    m._version = "v0.9.9"
    return m


def test_save_model_shadow_mode_still_promotes(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "shadow")
    monkeypatch.delenv("GBM_FORCE_PROMOTE", raising=False)
    m = _trained_model(monkeypatch, {"cpcv_n_folds": 14, "cpcv_pbo": 0.9, "cpcv_edge_mean": -0.02})
    result = m._save_model()
    assert result == "promoted", "shadow mode must never block"
    archive = m._db[m.MODEL_ARCHIVE_COLLECTION].docs
    assert any(d.get("pbo_gate", {}).get("verdict") == "shadow_block" for d in archive), \
        "archive doc must carry the shadow verdict stamp"
    active = m._db[m.MODEL_COLLECTION].find_one({"name": "t_gate_v321"})
    assert active is not None


def test_save_model_enforce_mode_blocks(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "enforce")
    monkeypatch.delenv("GBM_FORCE_PROMOTE", raising=False)
    m = _trained_model(monkeypatch, {"cpcv_n_folds": 14, "cpcv_pbo": 0.9, "cpcv_edge_mean": -0.02})
    result = m._save_model()
    assert result == "rejected_pbo_gate"
    assert m._db[m.MODEL_COLLECTION].find_one({"name": "t_gate_v321"}) is None, \
        "blocked model must NOT reach the live collection"
    archive = m._db[m.MODEL_ARCHIVE_COLLECTION].docs
    assert any(d.get("rejected_reason") == "pbo_gate" for d in archive)


def test_save_model_passing_model_promotes_with_stamps(monkeypatch):
    monkeypatch.setenv("TB_PBO_GATE", "enforce")
    monkeypatch.setenv("TB_FROZEN_HOLDOUT_DAYS", "45")
    m = _trained_model(monkeypatch, {"cpcv_n_folds": 14, "cpcv_pbo": 0.0, "cpcv_edge_mean": 0.12})
    m._feature_baseline = {"n_bins": 10, "features": {"f0": {"mean": 0.0}}}
    result = m._save_model()
    assert result == "promoted"
    doc = m._db[m.MODEL_COLLECTION].find_one({"name": "t_gate_v321"})
    assert doc["frozen_holdout"]["days"] == 45
    assert doc["feature_baseline"]["n_bins"] == 10
    assert doc["metrics"]["cpcv_pbo"] == 0.0


# ── 5. feature baselines ─────────────────────────────────────────────────────

def test_feature_baseline_basic():
    rng = np.random.default_rng(1)
    X = rng.normal(loc=2.0, scale=3.0, size=(5000, 3)).astype(np.float32)
    fb = compute_feature_baseline(X, ["a", "b.dotted", "c"])
    assert fb is not None
    assert fb["n_samples_used"] == 5000
    assert "b_dotted" in fb["features"], "Mongo-unsafe keys must be sanitized"
    a = fb["features"]["a"]
    assert abs(a["mean"] - 2.0) < 0.2
    assert abs(a["std"] - 3.0) < 0.2
    assert len(a["bin_edges"]) == 11  # deciles
    assert sum(a["bin_fracs"]) == pytest.approx(1.0, abs=1e-6)


def test_feature_baseline_subsamples_large_input():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(60000, 2)).astype(np.float32)
    fb = compute_feature_baseline(X, ["a", "b"], max_rows=50000)
    assert fb["n_samples_total"] == 60000
    assert fb["n_samples_used"] == 50000


def test_feature_baseline_disabled_and_bad_input(monkeypatch):
    monkeypatch.setenv("TB_FEATURE_BASELINE", "0")
    assert compute_feature_baseline(np.zeros((10, 2)), ["a", "b"]) is None
    monkeypatch.setenv("TB_FEATURE_BASELINE", "1")
    assert compute_feature_baseline(np.zeros((0, 2)), ["a", "b"]) is None
    assert compute_feature_baseline(np.zeros((10, 2)), ["only_one_name"]) is None  # shape mismatch


def test_train_from_features_captures_baseline(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV", "0")  # speed
    rng = np.random.default_rng(9)
    X = rng.normal(size=(600, 6)).astype(np.float32)
    y = (X[:, 0] > 0).astype(np.int64)
    m = TimeSeriesGBM(model_name="t_baseline_v321", forecast_horizon=5)
    m.params["device"] = "cpu"
    m.train_from_features(
        X, y, [f"f{i}" for i in range(6)], skip_save=True,
        num_boost_round=20, early_stopping_rounds=5, num_classes=2,
    )
    fb = getattr(m, "_feature_baseline", None)
    assert fb is not None
    assert set(fb["features"].keys()) == {f"f{i}" for i in range(6)}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
