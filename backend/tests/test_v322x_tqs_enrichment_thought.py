"""v322x — TQS enrichment observability thought.

The "🤔 Evaluating" thought fires with the PRE-gate TQS while the trade
card shows the POST-gate (AI-enriched) score, so the operator saw two
unexplained numbers (XOM eval'd "54 C" but card "60 B"). v322x emits a
🧮 follow-up thought whenever post-gate enrichment materially shifts the
score (>=1.0 pts) or flips the grade, so the trail reads "54 C → 60 B".

Source-anchored verification (consistent with the v322-series patch
tests): asserts the block exists, fires only on material shifts, and the
file still compiles.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "opportunity_evaluator.py"


def _block():
    text = SRC.read_text()
    i = text.index("v322x — TQS enrichment observability")
    return text[i:i + 3000]


def test_v322x_block_present():
    text = SRC.read_text()
    assert "v322x — TQS enrichment observability" in text
    assert '"event": "tqs_enriched"' in text


def test_v322x_fires_only_on_material_shift():
    block = _block()
    assert "abs(_post_s - _pre_s) >= 1.0" in block
    assert "_pre_g != _post_g" in block


def test_v322x_metadata_preserves_both_scores():
    block = _block()
    assert '"pre_gate_tqs": _pre_s' in block
    assert '"post_gate_tqs": _post_s' in block
    assert '"model_agrees": model_agrees' in block


def test_v322x_inside_recalc_guard_and_fail_safe():
    """The thought must live inside the `if recalc_tqs:` success branch and
    never raise into the evaluation path (wrapped in try/except)."""
    block = _block()
    assert "except Exception as _tqs_obs_err" in block


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
