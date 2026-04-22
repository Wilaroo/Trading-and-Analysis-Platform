"""
Regression tests for train_full_universe class-balance fix (2026-04-22).

CONTEXT
-------
Phase 13 v2 showed 10/10 LONG setups with trades=0 despite class-balance
already being active in TimeSeriesGBM.train_from_features(). Root cause:
`train_full_universe` (which trains direction_predictor_{bar_size}) bypasses
train_from_features and calls xgb.train() directly on a DMatrix WITHOUT a
`weight=` parameter. The generic directional model therefore never got the
2026-04-20 class-balance fix — and revalidate_all.py uses exactly that model
for AI filtering.

This test suite locks in:
  1. The class-balance helpers still produce per-class weights proportional
     to inverse frequency (regression for dl_training_utils).
  2. Source-level guard: `train_full_universe` in timeseries_service.py
     must construct its training DMatrix with `weight=` (no regression back
     to uniform).
  3. Source-level guard: it must log `class_balanced` on the FULL UNIVERSE
     path (mirrors the token grep users do to verify fix on Spark).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from services.ai_modules.dl_training_utils import (
    compute_balanced_class_weights,
    compute_per_sample_class_weights,
)


SERVICE_FILE = (
    Path(__file__).resolve().parents[1]
    / "services" / "ai_modules" / "timeseries_service.py"
)


# ─── helper math regression ──────────────────────────────────────────────────

def test_per_sample_weights_match_phase13v2_skew():
    """
    Phase 13 v2 log showed class distribution roughly DOWN:FLAT:UP ≈ 45:35:20
    after triple-barrier labeling. Verify our per-sample weights give UP
    about 2-3× the weight of DOWN. Without this, argmax collapses to DOWN.
    """
    rng = np.random.default_rng(42)
    y = np.concatenate([
        np.zeros(4500, dtype=np.int64),   # DOWN
        np.ones(3500, dtype=np.int64),    # FLAT
        np.full(2000, 2, dtype=np.int64), # UP
    ])
    rng.shuffle(y)
    w = compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)

    assert len(w) == len(y)
    assert abs(float(w.mean()) - 1.0) < 1e-5  # normalized

    w_down = w[y == 0].mean()
    w_up = w[y == 2].mean()
    # UP must weigh strictly more than DOWN (class is rarer → higher weight)
    assert w_up > w_down
    # And not by a trivial factor
    assert w_up / w_down >= 2.0
    assert w_up / w_down <= 5.0 + 1e-6  # clip_ratio is respected


def test_per_sample_weights_clip_protects_extreme_minority():
    y = np.concatenate([
        np.zeros(9900, dtype=np.int64),
        np.full(100, 2, dtype=np.int64),  # 1% UP — would be 99x without clip
    ])
    w = compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)
    class_w = compute_balanced_class_weights(y, num_classes=3, clip_ratio=5.0)
    # clip_ratio=5 → max/min class weight ratio is exactly 5.0
    assert class_w.max() / class_w.min() == pytest.approx(5.0, rel=1e-3)
    # Per-sample normalized, so UP samples ≈ 5× DOWN samples (within rounding)
    assert w[y == 2].mean() / w[y == 0].mean() == pytest.approx(5.0, rel=1e-3)


# ─── source-level guards ─────────────────────────────────────────────────────

def _read_source() -> str:
    return SERVICE_FILE.read_text()


def test_train_full_universe_dmatrix_has_weight_argument():
    """
    train_full_universe must build DMatrix WITH weight=. If someone removes
    the weight kwarg the fix silently regresses (we wouldn't see a crash,
    just the same Phase 13 symptom).
    """
    src = _read_source()
    # Find the train_full_universe function body. Use heuristic: look within a
    # window starting from 'async def train_full_universe' to next 'async def '.
    m = re.search(
        r"async def train_full_universe\b.*?(?=\n    async def |\nclass )",
        src, re.DOTALL,
    )
    assert m, "Could not locate train_full_universe function in source."
    body = m.group(0)

    # Must have a DMatrix(..., weight=...) line
    assert re.search(r"xgb\.DMatrix\([^)]*weight\s*=", body, re.DOTALL), (
        "train_full_universe DMatrix construction no longer passes weight=. "
        "Phase 13 v2 class-balance fix regressed."
    )


def test_train_full_universe_logs_class_balanced_token():
    """
    User runs `grep class_balanced training_subprocess.log` to verify fix is
    live on Spark. The log string MUST continue to include 'class_balanced'
    in the FULL UNIVERSE path.
    """
    src = _read_source()
    m = re.search(
        r"async def train_full_universe\b.*?(?=\n    async def |\nclass )",
        src, re.DOTALL,
    )
    body = m.group(0)
    assert "class_balanced" in body, (
        "train_full_universe no longer logs 'class_balanced' — user grep "
        "check will silently miss the fix."
    )
    # And specifically the FULL UNIVERSE prefix so we don't confuse with the
    # setup-specific path logs
    assert "[FULL UNIVERSE] class_balanced" in body, (
        "class_balanced log line must be prefixed with [FULL UNIVERSE] so "
        "users can distinguish it from Phase 2/2.5 setup-specific training."
    )


def test_train_full_universe_imports_class_balance_helpers():
    """
    Guard against a future refactor that removes the dl_training_utils import
    in train_full_universe.
    """
    src = _read_source()
    m = re.search(
        r"async def train_full_universe\b.*?(?=\n    async def |\nclass )",
        src, re.DOTALL,
    )
    body = m.group(0)
    assert "compute_per_sample_class_weights" in body
    assert "compute_balanced_class_weights" in body


def test_train_full_universe_class_balance_is_non_fatal():
    """
    Any exception in the class-balance computation must not crash training —
    the try/except must fall back to uniform weights with a warning. This
    protects the 8.8hr retrain from dying mid-way.
    """
    src = _read_source()
    m = re.search(
        r"async def train_full_universe\b.*?(?=\n    async def |\nclass )",
        src, re.DOTALL,
    )
    body = m.group(0)
    # The class-balance block must be inside a try/except with a warning log
    # referring to 'class-balance skipped' fallback
    assert "class-balance skipped" in body, (
        "train_full_universe must gracefully fall back to uniform weights "
        "if class-balance helpers raise — don't crash an 8-hour retrain."
    )
