"""
Phase 2 / Phase 2.5 guardrail — combined_names length MUST equal X column count.

Root cause of the `expected 57, got 52` Phase 2 crash:
  - _extract_setup_long_worker augments base_matrix with 5 FFD cols when
    TB_USE_FFD_FEATURES=1 → X has 51 base + n_setup cols.
  - The outer pipeline built `combined_names = feature_engineer.get_feature_names()
    + setup_names` using the NON-augmented 46-name list → names len = 46 + n_setup.
  - XGBoost rejected the mismatch.

This test rebuilds the exact name list used in training_pipeline.py Phase 2/2.5
and asserts it matches the worker's X column count when FFD is enabled.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_phase2_combined_names_shape.py -v
"""
import numpy as np
import pytest


def _synthetic_bars(n: int = 600, seed: int = 7):
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    highs = closes + np.abs(rng.normal(0.3, 0.2, n))
    lows = closes - np.abs(rng.normal(0.3, 0.2, n))
    opens = closes + rng.normal(0, 0.1, n)
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)
    return [
        {
            "open": float(opens[i]),
            "high": float(max(highs[i], closes[i], opens[i])),
            "low": float(min(lows[i], closes[i], opens[i])),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "date": f"2026-03-{(i % 28) + 1:02d}",
        }
        for i in range(n)
    ]


@pytest.fixture
def bars():
    return _synthetic_bars()


@pytest.fixture
def ffd_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")


@pytest.fixture
def ffd_off(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")


def _phase2_long_combined_names(setup_type: str):
    """Mirror the exact combined_names construction from training_pipeline.py Phase 2."""
    from services.ai_modules.timeseries_features import get_feature_engineer
    from services.ai_modules.feature_augmentors import augmented_feature_names
    from services.ai_modules.setup_features import get_setup_feature_names

    fe = get_feature_engineer()
    base_names = augmented_feature_names(fe.get_feature_names())
    feat_names = get_setup_feature_names(setup_type)
    return base_names + [f"setup_{n}" for n in feat_names]


def _phase2_short_combined_names(setup_type: str):
    """Mirror the exact combined_names construction from training_pipeline.py Phase 2.5."""
    from services.ai_modules.timeseries_features import get_feature_engineer
    from services.ai_modules.feature_augmentors import augmented_feature_names
    from services.ai_modules.short_setup_features import get_short_setup_feature_names

    fe = get_feature_engineer()
    base_names = augmented_feature_names(fe.get_feature_names())
    feat_names = get_short_setup_feature_names(setup_type)
    return base_names + [f"short_{n}" for n in feat_names]


# ── Long setup: FFD ON ──────────────────────────────────────────────

def test_phase2_long_combined_names_match_worker_with_ffd(bars, ffd_on):
    from services.ai_modules.training_pipeline import _extract_setup_long_worker

    setup_type = "breakout"
    fh = 10
    results = _extract_setup_long_worker(("TEST", bars, [(setup_type, fh, 0.003)]))
    assert results is not None
    X, _y = results[(setup_type, fh)]

    combined_names = _phase2_long_combined_names(setup_type)
    assert len(combined_names) == X.shape[1], (
        f"Phase 2 mismatch: combined_names={len(combined_names)} vs X.shape[1]={X.shape[1]}. "
        f"This is exactly the XGBoost 'expected {X.shape[1]}, got {len(combined_names)}' crash."
    )


# ── Long setup: FFD OFF ─────────────────────────────────────────────

def test_phase2_long_combined_names_match_worker_without_ffd(bars, ffd_off):
    from services.ai_modules.training_pipeline import _extract_setup_long_worker

    setup_type = "breakout"
    fh = 10
    results = _extract_setup_long_worker(("TEST", bars, [(setup_type, fh, 0.003)]))
    assert results is not None
    X, _y = results[(setup_type, fh)]

    combined_names = _phase2_long_combined_names(setup_type)
    assert len(combined_names) == X.shape[1]


# ── Short setup: FFD ON ─────────────────────────────────────────────

def test_phase2_short_combined_names_match_worker_with_ffd(bars, ffd_on):
    from services.ai_modules.training_pipeline import _extract_setup_short_worker

    setup_type = "short_breakdown"
    fh = 10
    results = _extract_setup_short_worker(("TEST", bars, [(setup_type, fh, 0.003)]))
    assert results is not None
    X, _y = results[(setup_type, fh)]

    combined_names = _phase2_short_combined_names(setup_type)
    assert len(combined_names) == X.shape[1], (
        f"Phase 2.5 mismatch: combined_names={len(combined_names)} vs X.shape[1]={X.shape[1]}"
    )


# ── Short setup: FFD OFF ────────────────────────────────────────────

def test_phase2_short_combined_names_match_worker_without_ffd(bars, ffd_off):
    from services.ai_modules.training_pipeline import _extract_setup_short_worker

    setup_type = "short_breakdown"
    fh = 10
    results = _extract_setup_short_worker(("TEST", bars, [(setup_type, fh, 0.003)]))
    assert results is not None
    X, _y = results[(setup_type, fh)]

    combined_names = _phase2_short_combined_names(setup_type)
    assert len(combined_names) == X.shape[1]
