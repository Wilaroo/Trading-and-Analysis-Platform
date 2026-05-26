"""Offline unit tests for v19.34.156 (P3-A) — grade-based position
sizing scaler.

Verifies the pure helper `_resolve_grade_multiplier` and the end-to-end
behaviour of `OpportunityEvaluator.calculate_position_size` with a
minimal bot stub.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_grade_position_sizing_v19_34_156.py -v
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ── _resolve_grade_multiplier (pure helper) ─────────────────────────


def test_grade_a_returns_full_size():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("A")
    assert mult == 1.0
    assert norm == "A"


def test_grade_b_returns_70pct():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("B")
    assert mult == 0.7
    assert norm == "B"


def test_grade_c_returns_30pct():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("C")
    assert mult == 0.3
    assert norm == "C"


def test_grade_d_returns_10pct_not_zero():
    """Q1b: D is vanishingly small but NON-ZERO (real money for
    learning, not a skip)."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("D")
    assert mult == 0.1
    assert norm == "D"


def test_unknown_grade_treated_as_d():
    """Q2b: anything outside {A,B,C,D} → D (strict)."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("X")
    assert mult == 0.1
    assert norm == "D"


def test_none_grade_treated_as_d():
    """Q2b: missing grade NEVER silently defaults to B."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier(None)
    assert mult == 0.1
    assert norm == "D"


def test_empty_string_grade_treated_as_d():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("")
    assert mult == 0.1
    assert norm == "D"


def test_lowercase_normalized_to_upper():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    mult, norm = _resolve_grade_multiplier("a")
    assert mult == 1.0
    assert norm == "A"


def test_grade_suffixes_collapse_to_first_letter():
    """A+, A-, "A grade", "Aplus" all collapse to A — only first char
    is significant. This is intentional so the bot is robust to
    scanner output that may decorate the letter."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    assert _resolve_grade_multiplier("A+") == (1.0, "A")
    assert _resolve_grade_multiplier("A-") == (1.0, "A")
    assert _resolve_grade_multiplier("A grade") == (1.0, "A")


def test_non_string_grade_treated_as_d():
    """A numeric score / object / list passed where grade was
    expected falls back to D, not crash."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    assert _resolve_grade_multiplier(42)[1] == "D"
    assert _resolve_grade_multiplier([])[1] == "D"
    assert _resolve_grade_multiplier({})[1] == "D"


# ── Env override ────────────────────────────────────────────────────


def test_env_override_changes_multiplier(monkeypatch):
    """Operator can tune any tier via env without code edits."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    monkeypatch.setenv("POSITION_SIZE_GRADE_A_MULT", "1.5")
    monkeypatch.setenv("POSITION_SIZE_GRADE_C_MULT", "0.5")
    assert _resolve_grade_multiplier("A")[0] == 1.5
    assert _resolve_grade_multiplier("C")[0] == 0.5
    # B & D unchanged.
    assert _resolve_grade_multiplier("B")[0] == 0.7
    assert _resolve_grade_multiplier("D")[0] == 0.1


def test_env_override_bad_value_falls_to_default(monkeypatch):
    """Malformed env var (e.g. 'one') doesn't break sizing — falls to
    hardcoded default."""
    from services.opportunity_evaluator import _resolve_grade_multiplier
    monkeypatch.setenv("POSITION_SIZE_GRADE_A_MULT", "not_a_number")
    assert _resolve_grade_multiplier("A")[0] == 1.0


# ── End-to-end: calculate_position_size honours grade ───────────────


def _make_bot_stub():
    """Minimal bot that the sizer's many `bot.x.y` lookups need to
    pass through without exploding. NO Mongo, NO IB.

    `max_risk_per_trade` is intentionally small ($500) so the post-grade
    notional stays well below the safety-guardrail per-symbol cap
    ($15,000 default) — otherwise A/B would clamp at $15k and the
    grade scalar would be invisible above the cap.
    """
    risk_params = SimpleNamespace(
        max_risk_per_trade=500.0,        # Small enough to stay under $15k safety cap
        starting_capital=100_000.0,
        max_position_pct=50.0,
        use_volatility_sizing=False,    # Disable so volatility_multiplier=1.0
        volatility_scale_factor=1.0,
        max_notional_per_trade=0,       # Disable absolute notional clamp
    )
    return SimpleNamespace(
        risk_params=risk_params,
        _current_regime=None,           # Disable regime multiplier
        _regime_position_multipliers={},
        _open_trades={},
        _db=None,
        db=None,
    )


@pytest.fixture(autouse=True)
def _clear_grade_env(monkeypatch):
    """Each test starts with no env overrides."""
    for k in ("POSITION_SIZE_GRADE_A_MULT", "POSITION_SIZE_GRADE_B_MULT",
              "POSITION_SIZE_GRADE_C_MULT", "POSITION_SIZE_GRADE_D_MULT"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("grade,expected_mult,expected_norm", [
    ("A", 1.0, "A"),
    ("B", 0.7, "B"),
    ("C", 0.3, "C"),
    ("D", 0.1, "D"),
    (None, 0.1, "D"),
    ("X", 0.1, "D"),
])
def test_calculate_position_size_applies_grade(grade, expected_mult, expected_norm):
    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradeDirection

    bot = _make_bot_stub()
    ev = OpportunityEvaluator()
    multipliers_out: Dict[str, Any] = {}

    # Entry $10, stop $9 → risk_per_share=$1. With max_risk_per_trade=$500:
    #   A → 500 * 1.0 = 500 → 500 shares ($5,000 notional)
    #   B → 500 * 0.7 = 350 shares ($3,500 notional)
    #   C → 500 * 0.3 = 150 shares ($1,500 notional)
    #   D → 500 * 0.1 =  50 shares ($500 notional)
    # All stay below the safety-guardrail $15k symbol cap so the
    # grade scalar is the binding constraint.
    shares, risk = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=0.5, atr_percent=2.0,
        symbol=None,                # No VP lookup
        multipliers_out=multipliers_out,
        grade=grade,
    )
    assert multipliers_out["grade"] == expected_norm
    assert multipliers_out["grade_multiplier"] == expected_mult
    expected_shares = int(500 * expected_mult)
    assert abs(shares - expected_shares) <= 1, (
        f"grade={grade!r}: shares={shares}, expected≈{expected_shares}"
    )


def test_calculate_position_size_grade_none_treated_as_d_strict():
    """Belt-and-suspenders: a None grade passed explicitly must NOT
    silently default to B (Q2b)."""
    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradeDirection

    bot = _make_bot_stub()
    ev = OpportunityEvaluator()
    out: Dict[str, Any] = {}
    shares, _ = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=0.5, atr_percent=2.0,
        symbol=None, multipliers_out=out, grade=None,
    )
    # D-grade shares = 50 (not 350 if it had silently used B).
    assert 45 <= shares <= 55
    assert out["grade"] == "D"


def test_calculate_position_size_no_grade_kwarg_still_works_legacy():
    """Legacy callers that don't pass `grade=` at all must still
    produce a valid (D-graded, vanishingly small) size — never crash."""
    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradeDirection

    bot = _make_bot_stub()
    ev = OpportunityEvaluator()
    shares, risk = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=0.5, atr_percent=2.0,
    )
    # Default kwarg grade=None → D-multiplier → ~50 shares.
    assert 45 <= shares <= 55


def test_grade_multiplier_composes_with_other_multipliers(monkeypatch):
    """If volatility/regime/vp aren't 1.0, the grade scalar must apply
    ON TOP — not replace them. End-to-end sanity check."""
    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradeDirection

    bot = _make_bot_stub()
    # Turn on volatility sizing with a low ATR% so volatility_mult=1.3.
    bot.risk_params.use_volatility_sizing = True
    bot.risk_params.volatility_scale_factor = 1.0

    ev = OpportunityEvaluator()
    out_a: Dict[str, Any] = {}
    shares_a, _ = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=0.1, atr_percent=1.0,        # → volatility_mult = 1.3
        symbol=None, multipliers_out=out_a, grade="A",
    )
    out_c: Dict[str, Any] = {}
    shares_c, _ = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=0.1, atr_percent=1.0,
        symbol=None, multipliers_out=out_c, grade="C",
    )
    # C should be ~0.3× A (grade_mult ratio). Both share the same
    # volatility multiplier; difference comes entirely from grade.
    ratio = shares_c / max(shares_a, 1)
    assert 0.25 <= ratio <= 0.35
    assert out_a["volatility"] == 1.3
    assert out_c["volatility"] == 1.3
    assert out_a["grade_multiplier"] == 1.0
    assert out_c["grade_multiplier"] == 0.3
