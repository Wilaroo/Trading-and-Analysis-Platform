"""v19.34.X (Feb 2026) — Sizer ↔ Execution Guardrail sync regression.

Operator-observed bug: the position sizer in `opportunity_evaluator.py`
clamped by `max_notional_per_trade` (operator-facing hard ceiling) and
`max_position_pct × starting_capital`, but DID NOT clamp by the
execution_guardrails ceiling (`MAX_POSITION_NOTIONAL_PCT × live equity`,
default 40%). When the operator's hard cap was disabled (=0) or set
above that pct-ceiling, the sizer happily produced a $105k notional
on a $250k account → `check_max_position_notional` vetoed every trade
with `notional_over_cap`. Bot logs all day, $0 fills.

Fix:
  1. `opportunity_evaluator.py`: pre-clamp shares to
     `(MAX_POSITION_NOTIONAL_PCT × starting_capital × (1 + tol))/price`.
  2. `execution_guardrails.py`: add a 0.5% tolerance band so integer-share
     rounding doesn't trip the veto when the sizer DOES respect the cap.

User-approved approach: tolerance band (option B), default 0.5%.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest


# ---------------------------------------------------------------------------
# Minimal bot stand-in
# ---------------------------------------------------------------------------

@dataclass
class _RP:
    max_risk_per_trade: float = 5_000.0
    starting_capital: float = 250_000.0
    max_position_pct: float = 80.0     # capital clamp = $200k (loose)
    max_notional_per_trade: float = 0  # operator hard cap DISABLED
    use_volatility_sizing: bool = False
    volatility_scale_factor: float = 1.0


class _Bot:
    def __init__(self, rp: _RP):
        self.risk_params = rp
        self._current_regime = None
        self._regime_position_multipliers = {}
        self._db = None


def _direction_long():
    from services.trading_bot_service import TradeDirection
    return TradeDirection.LONG


def _make_evaluator():
    from services.opportunity_evaluator import OpportunityEvaluator
    return OpportunityEvaluator()


# ---------------------------------------------------------------------------
# 1. Sizer respects the execution_guardrail ceiling even when
#    max_notional_per_trade is disabled
# ---------------------------------------------------------------------------

def test_sizer_clamps_to_execution_guardrail_when_hard_cap_disabled(monkeypatch):
    """Without the sync, sizer would pick $200k notional (capital clamp).
    Execution guardrail caps at 40% × $250k = $100k → bot vetoes all day.
    With the sync, sizer must produce ≤ $100k × (1 + 0.5% tol) notional.
    """
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    monkeypatch.setenv("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", "0.005")
    monkeypatch.setenv("SAFETY_MAX_SYMBOL_EXPOSURE_USD", "500000")
    # Force module-level constants to re-read the env.
    import importlib
    from services import execution_guardrails as eg
    from services import safety_guardrails as sg
    importlib.reload(eg)
    importlib.reload(sg)

    rp = _RP()
    bot = _Bot(rp)
    ev = _make_evaluator()

    # $10 stock, $0.10 stop distance → 100 shares per $1k risk budget.
    # max_shares_by_risk = $5000 / $0.10 = 50,000 → $500k notional (loose)
    # max_shares_by_capital = 80% × $250k / $10 = 20,000 → $200k (loose)
    # GUARDRAIL clamp = 40% × $250k × 1.005 / $10 = 10,050 → $100.5k
    shares, _risk = ev.calculate_position_size(
        entry_price=10.0,
        stop_price=9.90,
        direction=_direction_long(),
        bot=bot,
    )
    notional = shares * 10.0
    # Must NOT exceed cap by more than the configured tolerance.
    assert notional <= 100_000 * 1.005 + 1e-6, (
        f"Sizer overshot the execution-guardrail cap: shares={shares}, "
        f"notional=${notional:,.2f} > ${100_000 * 1.005:,.2f}"
    )
    # And must produce a non-trivial size (not vetoed/zero).
    assert shares >= 9_900, (
        f"Sizer under-allocated when the guard cap should allow ~10,000 "
        f"shares: shares={shares}"
    )


# ---------------------------------------------------------------------------
# 2. Operator hard cap still wins when STRICTER than guardrail
# ---------------------------------------------------------------------------

def test_sizer_uses_stricter_of_hard_cap_and_guardrail(monkeypatch):
    """Operator sets max_notional_per_trade=$50k; guardrail allows $100k.
    Sizer must use the stricter $50k cap.
    """
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    monkeypatch.setenv("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", "0.005")
    monkeypatch.setenv("SAFETY_MAX_SYMBOL_EXPOSURE_USD", "500000")
    import importlib
    from services import execution_guardrails as eg
    from services import safety_guardrails as sg
    importlib.reload(eg)
    importlib.reload(sg)

    rp = _RP(max_notional_per_trade=50_000.0)
    bot = _Bot(rp)
    ev = _make_evaluator()

    shares, _ = ev.calculate_position_size(
        entry_price=10.0, stop_price=9.90, direction=_direction_long(), bot=bot,
    )
    notional = shares * 10.0
    assert notional <= 50_000, (
        f"Operator hard cap should beat guardrail: notional=${notional:,.2f}"
    )


# ---------------------------------------------------------------------------
# 3. Guardrail tolerance allows tiny overshoots (was vetoing them)
# ---------------------------------------------------------------------------

def test_guardrail_tolerance_allows_small_overshoot(monkeypatch):
    """A $99,950 cap (40% × $249,875) vs a $100,000 sizer-output notional
    is 0.05% over — well within the 0.5% tolerance. Guardrail must allow.
    """
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    monkeypatch.setenv("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", "0.005")
    import importlib
    from services import execution_guardrails as eg
    importlib.reload(eg)

    # cap = 0.40 × $249,875 = $99,950; tolerance window goes to $100,449.75.
    result = eg.check_max_position_notional(
        entry_price=10.0, shares=10_000, account_equity=249_875.0,
    )
    assert result.allow, f"Guardrail vetoed within tolerance: {result.reason}"


def test_guardrail_blocks_outside_tolerance(monkeypatch):
    """A 2% overshoot blows past the tolerance and MUST still be blocked."""
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    monkeypatch.setenv("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", "0.005")
    import importlib
    from services import execution_guardrails as eg
    importlib.reload(eg)

    # cap = 0.40 × $250k = $100k; notional 102k = +2% > 0.5% tol.
    result = eg.check_max_position_notional(
        entry_price=10.0, shares=10_200, account_equity=250_000.0,
    )
    assert not result.allow, "Guardrail must veto a 2% overshoot"
    assert "notional_over_cap" in result.reason


# ---------------------------------------------------------------------------
# 4. effective_notional_cap is the shared source of truth
# ---------------------------------------------------------------------------

def test_effective_notional_cap_matches_guardrail_math(monkeypatch):
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0.40")
    import importlib
    from services import execution_guardrails as eg
    importlib.reload(eg)

    assert eg.effective_notional_cap(250_000.0) == pytest.approx(100_000.0)
    assert eg.effective_notional_cap(0) == 0.0
    assert eg.effective_notional_cap(250_000.0, max_pct=0) == 0.0
