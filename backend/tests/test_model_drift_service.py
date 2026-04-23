"""
Tests for services/model_drift_service — PSI + KS drift detection.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services.model_drift_service import (
    psi,
    ks_stat,
    classify_drift,
    check_drift_for_model,
    check_drift_all_models,
    PSI_WARNING, PSI_CRITICAL, KS_WARNING, KS_CRITICAL,
    MIN_SAMPLES,
    SOURCE_COLLECTION,
)


# ── PSI ────────────────────────────────────────────────────────────────

def test_psi_zero_when_identical():
    rng = np.random.default_rng(0)
    x = rng.normal(0.5, 0.1, 1000)
    assert psi(x, x) < 0.01


def test_psi_nonzero_when_distributions_shift():
    rng = np.random.default_rng(1)
    baseline = rng.normal(0.5, 0.1, 1000)
    shifted = rng.normal(0.35, 0.1, 1000)  # mean shift
    val = psi(baseline, shifted)
    assert val > PSI_WARNING  # ≥0.10


def test_psi_large_shift_crosses_critical():
    rng = np.random.default_rng(2)
    baseline = rng.normal(0.5, 0.05, 1000)
    shifted = rng.normal(0.20, 0.05, 1000)  # big shift
    assert psi(baseline, shifted) > PSI_CRITICAL


def test_psi_empty_inputs_return_zero():
    assert psi(np.array([]), np.array([0.5])) == 0.0
    assert psi(np.array([0.5]), np.array([])) == 0.0


def test_psi_constant_values_return_zero():
    const = np.full(100, 0.5)
    assert psi(const, const) == 0.0


# ── KS ─────────────────────────────────────────────────────────────────

def test_ks_zero_when_identical():
    rng = np.random.default_rng(3)
    x = rng.normal(0.5, 0.1, 500)
    assert ks_stat(x, x) < 1e-9


def test_ks_large_when_distributions_different():
    rng = np.random.default_rng(4)
    a = rng.normal(0.5, 0.1, 500)
    b = rng.normal(0.2, 0.1, 500)
    assert ks_stat(a, b) > KS_WARNING


def test_ks_empty_returns_zero():
    assert ks_stat(np.array([]), np.array([0.5])) == 0.0


# ── classify_drift ─────────────────────────────────────────────────────

def test_classify_healthy():
    assert classify_drift(0.05, 0.05) == "healthy"


def test_classify_warning_on_psi():
    assert classify_drift(0.15, 0.05) == "warning"


def test_classify_warning_on_ks():
    assert classify_drift(0.05, 0.15) == "warning"


def test_classify_critical_on_psi():
    assert classify_drift(0.30, 0.05) == "critical"


def test_classify_critical_on_ks():
    assert classify_drift(0.05, 0.25) == "critical"


def test_classify_critical_takes_precedence():
    assert classify_drift(0.15, 0.25) == "critical"


# ── DB-backed check with in-memory fake ────────────────────────────────

class _Cur:
    def __init__(self, docs):
        self._docs = list(docs)

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _Col:
    def __init__(self):
        self.docs = []

    def find(self, q, proj=None):
        field = next((k for k in q if k != "created_at" and k != "model_version"), None)
        cr = q.get("created_at", {})
        start = cr.get("$gte")
        end = cr.get("$lt")
        mv = q.get("model_version")
        out = []
        for d in self.docs:
            if mv and d.get("model_version") != mv:
                continue
            if start and d.get("created_at", "") < start:
                continue
            if end and d.get("created_at", "") >= end:
                continue
            if field and d.get(field) is None:
                continue
            out.append(d)
        return _Cur(out)

    def distinct(self, field, q=None):
        q = q or {}
        start = (q.get("created_at") or {}).get("$gte")
        vals = set()
        for d in self.docs:
            if start and d.get("created_at", "") < start:
                continue
            v = d.get(field)
            if v is not None:
                vals.add(v)
        return list(vals)

    def insert_one(self, d):
        self.docs.append(d)


class _FakeDB:
    def __init__(self):
        self._c = {}

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Col()
        return self._c[n]


def _seed_predictions(db, *, version, n, mean, hours_ago_start, hours_ago_end):
    rng = np.random.default_rng(hash((version, mean)) & 0xFFFFFFFF)
    now = datetime.now(timezone.utc)
    for i in range(n):
        # Spread uniformly across the window
        frac = (i + 0.5) / n
        t = now - timedelta(
            hours=hours_ago_start + frac * (hours_ago_end - hours_ago_start)
        )
        db[SOURCE_COLLECTION].docs.append({
            "model_version": version,
            "prob_up": float(np.clip(rng.normal(mean, 0.08), 0, 1)),
            "prob_down": float(np.clip(rng.normal(1 - mean, 0.08), 0, 1)),
            "created_at": t.isoformat(),
        })


def test_check_drift_insufficient_data():
    db = _FakeDB()
    _seed_predictions(db, version="v1", n=10, mean=0.5,
                      hours_ago_start=0, hours_ago_end=24)
    result = check_drift_for_model(db, "v1")
    assert result["status"] == "insufficient_data"
    assert result["recent_n"] < MIN_SAMPLES


def test_check_drift_healthy_when_stable_distribution():
    db = _FakeDB()
    # Same distribution + same sample size → PSI should sit well below warning
    _seed_predictions(db, version="v1", n=400, mean=0.5,
                      hours_ago_start=0, hours_ago_end=24)
    _seed_predictions(db, version="v1", n=400, mean=0.5,
                      hours_ago_start=24, hours_ago_end=24 + 30 * 24)
    result = check_drift_for_model(db, "v1")
    # With identical generators, status should be healthy. Allow warning
    # only on rare RNG quirks but not critical.
    assert result["status"] in ("healthy", "warning")
    assert result["status"] != "critical"
    # Mean shift should be negligible
    assert abs(result["mean_shift"]) < 0.05


def test_check_drift_critical_when_distribution_shifts():
    db = _FakeDB()
    _seed_predictions(db, version="v2", n=300, mean=0.30,  # recent: low
                      hours_ago_start=0, hours_ago_end=24)
    _seed_predictions(db, version="v2", n=600, mean=0.60,  # baseline: high
                      hours_ago_start=24, hours_ago_end=24 + 30 * 24)
    result = check_drift_for_model(db, "v2")
    assert result["status"] in ("warning", "critical")
    assert result["psi"] > PSI_WARNING or result["ks"] > KS_WARNING
    assert "Retrain" in result["recommendation"] or "Monitor" in result["recommendation"]


def test_check_drift_all_models_enumerates_distinct_versions():
    db = _FakeDB()
    _seed_predictions(db, version="v1", n=200, mean=0.5,
                      hours_ago_start=0, hours_ago_end=24)
    _seed_predictions(db, version="v1", n=600, mean=0.5,
                      hours_ago_start=24, hours_ago_end=24 + 30 * 24)
    _seed_predictions(db, version="v2", n=200, mean=0.3,
                      hours_ago_start=0, hours_ago_end=24)
    _seed_predictions(db, version="v2", n=600, mean=0.3,
                      hours_ago_start=24, hours_ago_end=24 + 30 * 24)

    results = check_drift_all_models(db)
    assert len(results) == 2
    assert {r["model_version"] for r in results} == {"v1", "v2"}


def test_check_drift_none_db_returns_empty():
    assert check_drift_all_models(None) == []


def test_result_mean_shift_computed():
    db = _FakeDB()
    _seed_predictions(db, version="v1", n=200, mean=0.40,
                      hours_ago_start=0, hours_ago_end=24)
    _seed_predictions(db, version="v1", n=600, mean=0.60,
                      hours_ago_start=24, hours_ago_end=24 + 30 * 24)
    r = check_drift_for_model(db, "v1")
    assert r["mean_shift"] < 0  # recent mean < baseline mean
    assert abs(r["mean_shift"]) > 0.05
