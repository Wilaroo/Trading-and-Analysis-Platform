"""
v19.4 — Position-sizer absolute-notional clamp tests (2026-04-30)

Why this exists: with `starting_capital=$1.07M` and `max_position_pct=50%`,
the position sizer was producing ~$267k notional per trade — the safety
guardrail rejected ALL of them on `symbol_exposure: $267k exceeds cap`.
Even after lowering `starting_capital` to $250k, the sizer's cap floats
with equity (50% of $250k = $125k; if the account compounds to $500k,
50% = $250k again). Operator wants a HARD absolute ceiling, decoupled
from equity.

`max_notional_per_trade` (default $100,000) is the new third clamp:
  shares = min(max_shares_by_risk, max_shares_by_capital,
               max_shares_by_notional)

When set to 0, the clamp is disabled and the sizer falls back to the
prior two-clamp behaviour (so existing setups don't suddenly tighten).
"""
from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------
# Minimal stand-ins so we can call the sizer without the full bot service.
# --------------------------------------------------------------------------

@dataclass
class _RP:
    max_risk_per_trade: float = 2000.0
    starting_capital: float = 250000.0
    max_position_pct: float = 40.0
    max_notional_per_trade: float = 100000.0
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


# --------------------------------------------------------------------------
# 1. Dataclass exposes the new field with the expected default
# --------------------------------------------------------------------------

def test_risk_parameters_exposes_max_notional_per_trade():
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    assert hasattr(rp, "max_notional_per_trade")
    assert rp.max_notional_per_trade == 100000.0, (
        "Default max_notional_per_trade should be $100,000 — the "
        "operator-stated per-trade ceiling."
    )


# --------------------------------------------------------------------------
# 2. Sizer applies the clamp when it would otherwise produce a fatter notional
# --------------------------------------------------------------------------

def test_clamp_caps_oversized_notional():
    """Setup: $1 stock, $0.005 stop distance.
    - max_shares_by_risk = $2000 / $0.005 = 400,000 shares = $400k notional
    - max_shares_by_capital = (40% × $250k) / $1 = 100,000 shares = $100k
    - max_shares_by_notional = $100k / $1 = 100,000 shares
    With $250k equity + 40% pct, the capital clamp ALSO sits at $100k —
    so we'd get the right answer either way. To prove the notional clamp
    is doing the work, we bump pct to 80% (so capital cap = $200k) and
    verify the $100k notional clamp wins."""
    rp = _RP(max_position_pct=80.0)  # capital cap = $200k
    bot = _Bot(rp)
    evaluator = _make_evaluator()

    shares, risk_amount = evaluator.calculate_position_size(
        entry_price=1.00,
        stop_price=0.995,  # $0.005 risk per share
        direction=_direction_long(),
        bot=bot,
    )
    notional = shares * 1.00
    assert notional <= 100000.0 + 1.0, (
        f"Notional clamp failed: shares={shares} → notional=${notional:,.0f} "
        f"(should be ≤ $100,000)"
    )
    # Should be EXACTLY at the notional clamp (~100k), not floor of capital
    assert 99000.0 <= notional <= 100000.0, (
        f"Expected notional clamp to bind at ~$100k; got ${notional:,.0f}"
    )


# --------------------------------------------------------------------------
# 3. Risk clamp still wins when stop is wide
# --------------------------------------------------------------------------

def test_risk_clamp_wins_when_stop_is_wide():
    """Stop is $5 away → risk_per_share=$5 → max_shares_by_risk = $2000/$5 = 400.
    Notional = 400 × $50 = $20,000 (well under $100k). Risk clamp wins."""
    rp = _RP()
    bot = _Bot(rp)
    evaluator = _make_evaluator()

    shares, risk_amount = evaluator.calculate_position_size(
        entry_price=50.0,
        stop_price=45.0,  # $5 risk per share
        direction=_direction_long(),
        bot=bot,
    )
    assert shares == 400, f"Expected 400 shares; got {shares}"
    assert risk_amount == 2000.0


# --------------------------------------------------------------------------
# 4. Disabling the clamp (set to 0) restores prior two-clamp behaviour
# --------------------------------------------------------------------------

def test_clamp_disabled_when_zero():
    """When max_notional_per_trade=0, the sizer falls back to the older
    risk + capital two-clamp logic, so legacy setups don't unexpectedly
    tighten."""
    rp = _RP(max_notional_per_trade=0.0, max_position_pct=80.0)  # capital cap $200k
    bot = _Bot(rp)
    evaluator = _make_evaluator()

    shares, _ = evaluator.calculate_position_size(
        entry_price=1.00,
        stop_price=0.995,
        direction=_direction_long(),
        bot=bot,
    )
    notional = shares * 1.00
    # Without the clamp, capital cap of $200k binds (or risk cap of $400k)
    # → notional should be ~$200k, NOT $100k.
    assert notional > 150000.0, (
        f"With clamp disabled, notional should not be capped at $100k; "
        f"got ${notional:,.0f}"
    )


# --------------------------------------------------------------------------
# 5. Source-level guard: the clamp line is in the sizer
# --------------------------------------------------------------------------

def test_sizer_source_contains_notional_clamp():
    import inspect
    from services import opportunity_evaluator
    src = inspect.getsource(opportunity_evaluator)
    assert "max_notional_per_trade" in src, (
        "🚨 v19.4 REGRESSION: `max_notional_per_trade` reference missing "
        "from opportunity_evaluator.py. The notional clamp was removed."
    )
    assert "max_shares_by_notional" in src, (
        "🚨 v19.4 REGRESSION: `max_shares_by_notional` clamp missing from "
        "the position sizer. The third clamp is no longer enforced."
    )


# --------------------------------------------------------------------------
# 6. Persistence round-trip — Mongo save/load includes the new field
# --------------------------------------------------------------------------

def test_persistence_round_trip_includes_max_notional():
    import inspect
    from services import bot_persistence
    src = inspect.getsource(bot_persistence)
    # Save side
    assert '"max_notional_per_trade": bot.risk_params.max_notional_per_trade' in src, (
        "Persistence save path doesn't write max_notional_per_trade."
    )
    # Restore side
    assert 'if "max_notional_per_trade" in saved_risk_params' in src, (
        "Persistence restore path doesn't read max_notional_per_trade."
    )


# --------------------------------------------------------------------------
# 7. API surface: RiskParamsUpdate accepts the field
# --------------------------------------------------------------------------

def test_riskparamsupdate_pydantic_model_accepts_max_notional():
    from routers.trading_bot import RiskParamsUpdate
    instance = RiskParamsUpdate(max_notional_per_trade=75000.0)
    dumped = instance.model_dump(exclude_none=True)
    assert dumped == {"max_notional_per_trade": 75000.0}
