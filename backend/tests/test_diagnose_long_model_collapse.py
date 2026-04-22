"""
Tests for diagnose_long_model_collapse.py — classifier + tally semantics only.

We don't spin up Mongo or real models here. We probe the pure helpers:
  - _tally(samples)
  - _classify(metadata, tally)

These are the fragile bits that decide which collapse MODE the user sees.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "diagnose_long_model_collapse.py"


# Load the script as a module without running main()
@pytest.fixture(scope="module")
def diag_mod():
    spec = importlib.util.spec_from_file_location(
        "diag_long_collapse", str(SCRIPT)
    )
    mod = importlib.util.module_from_spec(spec)
    # Don't execute asyncio.run — the module has guard `if __name__ == "__main__"`
    spec.loader.exec_module(mod)
    return mod


# ─── _tally ──────────────────────────────────────────────────────────────────

def test_tally_empty(diag_mod):
    out = diag_mod._tally([])
    assert out == {"n": 0, "error": "no samples"}


def test_tally_all_flat(diag_mod):
    samples = [{"direction": "flat", "p_up": 0.33, "p_down": 0.33, "confidence": 0.33}
               for _ in range(50)]
    out = diag_mod._tally(samples)
    assert out["n"] == 50
    assert out["pct_up"] == 0.0
    assert out["pct_flat"] == 100.0
    assert out["pct_up_above_threshold"] == 0.0


def test_tally_all_up(diag_mod):
    samples = [{"direction": "up", "p_up": 0.70, "p_down": 0.15, "confidence": 0.70}
               for _ in range(20)]
    out = diag_mod._tally(samples)
    assert out["pct_up"] == 100.0
    assert out["pct_up_above_threshold"] == 100.0
    assert out["p_up_mean"] == pytest.approx(0.70, rel=1e-3)


def test_tally_mixed_above_and_below_threshold(diag_mod):
    samples = (
        [{"direction": "up", "p_up": 0.60, "p_down": 0.20, "confidence": 0.60}] * 5
        + [{"direction": "up", "p_up": 0.40, "p_down": 0.30, "confidence": 0.40}] * 5
    )
    out = diag_mod._tally(samples)
    assert out["n"] == 10
    assert out["pct_up"] == 100.0
    # Half cross 0.55, half don't
    assert out["pct_up_above_threshold"] == 50.0


# ─── _classify ───────────────────────────────────────────────────────────────

def test_classify_missing_model(diag_mod):
    mode, _msg = diag_mod._classify({"found": False}, {"n": 0})
    assert mode == "MODEL MISSING"


def test_classify_binary_regression_mode_a(diag_mod):
    meta = {"found": True, "num_classes": 2, "label_scheme": "binary"}
    mode, msg = diag_mod._classify(meta, {"n": 100, "pct_up": 50.0,
                                           "pct_up_above_threshold": 50.0,
                                           "p_up_p95": 0.5})
    assert mode.startswith("MODE A")
    assert "binary" in msg.lower()


def test_classify_mode_b_argmax_never_up(diag_mod):
    """UP argmax < 1% → MODE B."""
    meta = {"found": True, "num_classes": 3, "label_scheme": "triple_barrier_3class"}
    tally = {"n": 500, "pct_up": 0.2, "pct_flat": 30.0, "pct_down": 69.8,
             "p_up_p95": 0.28, "pct_up_above_threshold": 0.0}
    mode, msg = diag_mod._classify(meta, tally)
    assert mode.startswith("MODE B")
    assert "argmax" in msg.lower() or "never wins" in msg.lower() or "collapsed" in msg.lower()


def test_classify_mode_c_threshold_cutoff(diag_mod):
    """UP argmax 20%, but only 2% crosses threshold → MODE C."""
    meta = {"found": True, "num_classes": 3, "label_scheme": "triple_barrier_3class"}
    tally = {"n": 500, "pct_up": 20.0, "pct_flat": 40.0, "pct_down": 40.0,
             "p_up_p95": 0.50, "pct_up_above_threshold": 2.0}
    mode, msg = diag_mod._classify(meta, tally)
    assert mode.startswith("MODE C")
    assert "threshold" in msg.lower()


def test_classify_healthy(diag_mod):
    """UP argmax 25%, 15% crosses threshold → HEALTHY."""
    meta = {"found": True, "num_classes": 3, "label_scheme": "triple_barrier_3class"}
    tally = {"n": 500, "pct_up": 25.0, "pct_flat": 35.0, "pct_down": 40.0,
             "p_up_p95": 0.62, "pct_up_above_threshold": 15.0}
    mode, _ = diag_mod._classify(meta, tally)
    assert mode == "HEALTHY"


def test_classify_no_data(diag_mod):
    meta = {"found": True, "num_classes": 3, "label_scheme": "triple_barrier_3class"}
    mode, _ = diag_mod._classify(meta, {"n": 0})
    assert mode == "NO DATA"


def test_long_only_setups_excludes_shorts(diag_mod):
    """LONG_ONLY_SETUPS must not include any SHORT_ or direction=short profile."""
    for name in diag_mod.LONG_ONLY_SETUPS:
        assert not name.startswith("SHORT_"), f"{name} should be excluded"
    # Sanity: at least SCALP, MOMENTUM, etc., are present
    assert "SCALP" in diag_mod.LONG_ONLY_SETUPS
    assert "TREND_CONTINUATION" in diag_mod.LONG_ONLY_SETUPS
    # And none of the SHORT_ ones
    assert "SHORT_SCALP" not in diag_mod.LONG_ONLY_SETUPS
    assert "SHORT_REVERSAL" not in diag_mod.LONG_ONLY_SETUPS
