"""Test for v19.34.159 — verify `build_entry_context` surfaces the
v156 grade-scaling + v157 MR-regime fields into
`entry_context.multipliers` so the "Why this size?" UI pill can render
the full sizing chain.

Pre-v159 `build_entry_context` only mirrored `volatility / regime /
vp_path` from `position_multipliers`. The grade / mr_* keys lived in
`position_multipliers` but never propagated forward, leaving the
frontend with no way to explain WHY a fill was sized the way it was.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_entry_context_multipliers_v19_34_159.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.opportunity_evaluator import OpportunityEvaluator


@pytest.fixture
def evaluator():
    # build_entry_context only reads `self`-bound state for AI-modules
    # and confidence-gate plumbing — neither used by the multiplier
    # surface. A bare instance is sufficient.
    return OpportunityEvaluator.__new__(OpportunityEvaluator)


def _ctx(evaluator, **position_mult_kw):
    """Helper: build entry_context with the given position multipliers."""
    return evaluator.build_entry_context(
        alert={"symbol": "TEST"},
        intelligence={},
        regime="neutral",
        regime_score=0.0,
        filter_action="proceed",
        filter_win_rate=0.5,
        atr=1.0,
        atr_percent=0.01,
        confidence_gate_result=None,
        multipliers_meta={"position": position_mult_kw},
        ai_consultation_result=None,
    )


def test_legacy_pre_v156_trade_only_surfaces_vol_regime_vp(evaluator):
    """Pre-v156 multipliers (vol/regime/vp_path only) still render
    cleanly and don't synthesise grade/MR fields."""
    ctx = _ctx(evaluator, volatility=1.1, regime=0.9, vp_path=1.0)
    m = ctx.get("multipliers") or {}
    assert m.get("volatility") == 1.1
    assert m.get("regime") == 0.9
    assert m.get("vp_path") == 1.0
    # v156/v157 keys NOT present → tooltip degrades gracefully on the
    # frontend (renders nothing for those rows).
    for k in ("grade", "grade_multiplier", "mr_regime", "mr_multiplier",
              "mr_hurst", "mr_half_life_bars", "mr_reason"):
        assert k not in m, f"unexpected key {k!r} bled into legacy ctx"


def test_grade_fields_propagate_v156(evaluator):
    """v156 fields (`grade`, `grade_multiplier`) must surface."""
    ctx = _ctx(
        evaluator,
        volatility=1.0, regime=1.0, vp_path=1.0,
        grade="B", grade_multiplier=0.7,
    )
    m = ctx["multipliers"]
    assert m["grade"] == "B"
    assert m["grade_multiplier"] == 0.7


def test_mr_fields_propagate_v157(evaluator):
    """v157 fields (`mr_*`) must surface in their entirety."""
    ctx = _ctx(
        evaluator,
        volatility=1.0, regime=1.0, vp_path=1.0,
        mr_regime="MR_STRONG",
        mr_multiplier=1.3,
        mr_hurst=0.42,
        mr_half_life_bars=8.3,
        mr_reason="family=mean_reversion|regime=MR_STRONG|mult=1.3",
    )
    m = ctx["multipliers"]
    assert m["mr_regime"] == "MR_STRONG"
    assert m["mr_multiplier"] == 1.3
    assert m["mr_hurst"] == pytest.approx(0.42)
    assert m["mr_half_life_bars"] == pytest.approx(8.3)
    assert "mean_reversion" in m["mr_reason"]


def test_full_chain_v156_plus_v157(evaluator):
    """All seven new keys present at once produce a complete chain."""
    ctx = _ctx(
        evaluator,
        volatility=1.0, regime=0.9, vp_path=1.05,
        grade="A", grade_multiplier=1.0,
        mr_regime="TRENDING",
        mr_multiplier=0.5,
        mr_hurst=0.61,
        mr_half_life_bars=None,  # trending → half-life intentionally null
        mr_reason="family=mean_reversion|regime=TRENDING|mult=0.5",
    )
    m = ctx["multipliers"]
    assert m["volatility"] == 1.0
    assert m["regime"] == 0.9
    assert m["vp_path"] == 1.05
    assert m["grade"] == "A"
    assert m["grade_multiplier"] == 1.0
    assert m["mr_regime"] == "TRENDING"
    assert m["mr_multiplier"] == 0.5
    # None values must NOT leak (filtered in the helper).
    assert "mr_half_life_bars" not in m


def test_none_values_are_filtered(evaluator):
    """None v156/v157 values must not pollute the surface — keeps
    the frontend's `mult != null` checks honest."""
    ctx = _ctx(
        evaluator,
        volatility=1.0, regime=1.0, vp_path=1.0,
        grade=None, grade_multiplier=None,
        mr_regime=None, mr_multiplier=None,
    )
    m = ctx["multipliers"]
    for k in ("grade", "grade_multiplier", "mr_regime", "mr_multiplier"):
        assert k not in m, f"{k} should be filtered when None"


def test_multipliers_key_only_present_when_data_exists(evaluator):
    """No position multipliers → no `multipliers` key emitted at all
    (legacy behavior preserved)."""
    ctx = evaluator.build_entry_context(
        alert={"symbol": "TEST"},
        intelligence={},
        regime="neutral",
        regime_score=0.0,
        filter_action="proceed",
        filter_win_rate=0.5,
        atr=1.0,
        atr_percent=0.01,
        confidence_gate_result=None,
        multipliers_meta=None,
        ai_consultation_result=None,
    )
    assert "multipliers" not in ctx
