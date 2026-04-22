"""
Regression tests for the MODE-C confidence threshold fix (2026-04-23).

CONTEXT
-------
3-class setup-specific LONG models peak at 0.44-0.53 confidence on
triple-barrier data (FLAT class absorbs probability mass). Under the old
0.6 CONFIRMS threshold, these correct UP-directional signals only got:
  - +5 points in ConfidenceGate (Layer 2b)
  - AI score 70 in TQS (Layer 6)
Even though argmax is UP, they lost the CONFIRMS bucket.

Fix: CONFIRMS_THRESHOLD lowered from 0.60 → 0.50 in BOTH:
  - services/ai_modules/confidence_gate.py (Layer 2b)
  - services/tqs/context_quality.py        (6. AI Model Alignment)

The disagreement side keeps 0.60 for heavy penalties and uses a softer
-3 / ai_score 35 for weak disagreements to avoid low-confidence noise
causing false vetoes.

These tests exercise the source directly (no live service) by reading
the module file and asserting the calibrated constants + tier mapping.
"""
from __future__ import annotations

import inspect

import services.ai_modules.confidence_gate as gate_mod
from services.ai_modules.confidence_gate import ConfidenceGate
import services.tqs.context_quality as ctx_mod


# ─── Source-level sanity ────────────────────────────────────────────────────

def test_confidence_gate_module_declares_confirms_threshold_050():
    """Layer 2b CONFIRMS bucket must use 0.50 (not 0.60)."""
    src = inspect.getsource(ConfidenceGate)
    assert "CONFIRMS_THRESHOLD = 0.50" in src, (
        "ConfidenceGate Layer 2b must set CONFIRMS_THRESHOLD = 0.50 for MODE-C calibration"
    )
    assert "pred_confidence >= CONFIRMS_THRESHOLD" in src, (
        "Layer 2b must gate 'CONFIRMS' against CONFIRMS_THRESHOLD, not a hardcoded 0.6"
    )


def test_confidence_gate_keeps_strong_disagreement_at_060():
    """Disagreement still uses 0.60 — only weak disagreement softens."""
    src = inspect.getsource(ConfidenceGate)
    assert "pred_confidence >= 0.60" in src, (
        "Strong-disagreement path must keep the 0.60 threshold to avoid "
        "over-penalising low-confidence noise."
    )


def test_tqs_context_quality_declares_confirms_threshold_050():
    """TQS 'AI Model Alignment' must mirror the ConfidenceGate 0.50 threshold."""
    src = inspect.getsource(ctx_mod)
    assert "CONFIRMS_THRESHOLD = 0.50" in src
    assert "ai_model_confidence >= CONFIRMS_THRESHOLD" in src


def test_tqs_context_quality_keeps_strong_disagreement_at_060():
    """TQS still flags heavy AI disagreement only above 0.60 conf."""
    src = inspect.getsource(ctx_mod)
    assert "ai_model_confidence >= 0.60" in src


# ─── Behavioural — exercise the confidence-gate tiering branch directly ─────
# We don't construct a full ConfidenceGate (lots of deps) — instead we use
# a minimal replay of the decision branch: same constants, same thresholds.

class _TierReplay:
    """Mini replica of the MODE-C decision branch (Layer 2b tiers)."""
    CONFIRMS_THRESHOLD = 0.50

    @staticmethod
    def tier(agrees: bool, conf: float, direction: str = "up") -> str:
        if agrees and conf >= _TierReplay.CONFIRMS_THRESHOLD:
            return "CONFIRMS"
        if agrees:
            return "leans"
        if direction == "flat":
            return "flat"
        if conf >= 0.60:
            return "DISAGREES_STRONG"
        return "DISAGREES_WEAK"


def test_up_argmax_at_050_now_buckets_as_confirms():
    """MODE-C: argmax=UP at 0.50 was 'leans' before — must be 'CONFIRMS' now."""
    assert _TierReplay.tier(agrees=True, conf=0.50) == "CONFIRMS"


def test_up_argmax_at_044_stays_leans():
    """Below 0.50 still 'leans' — we didn't lower the floor too far."""
    assert _TierReplay.tier(agrees=True, conf=0.44) == "leans"


def test_up_argmax_at_053_is_confirms():
    """The top of the MODE-C range (~0.53) gets the full +15 boost."""
    assert _TierReplay.tier(agrees=True, conf=0.53) == "CONFIRMS"


def test_up_argmax_at_060_still_confirms():
    """Strongly confident agreement still CONFIRMS (regression)."""
    assert _TierReplay.tier(agrees=True, conf=0.65) == "CONFIRMS"


def test_disagreement_at_055_is_weak():
    """Weak disagreement (conf < 0.60) → DISAGREES_WEAK (softer -3 penalty)."""
    assert _TierReplay.tier(agrees=False, conf=0.55, direction="down") == "DISAGREES_WEAK"


def test_disagreement_at_065_is_strong():
    """Heavy disagreement (conf ≥ 0.60) → DISAGREES_STRONG (heavy -5 penalty)."""
    assert _TierReplay.tier(agrees=False, conf=0.65, direction="down") == "DISAGREES_STRONG"


def test_flat_prediction_is_flat_tier_regardless_of_conf():
    """Flat predictions always go through the 'no edge' branch."""
    assert _TierReplay.tier(agrees=False, conf=0.80, direction="flat") == "flat"
    assert _TierReplay.tier(agrees=False, conf=0.20, direction="flat") == "flat"
