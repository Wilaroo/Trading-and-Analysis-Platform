"""
v19.12 — Pre-execution guardrail max-notional cap (2026-04-30).

Why this exists: the post-mortem of yesterday's `safety_guardrail`
$15k vs $267k blocker uncovered a SIBLING blocker one stage
downstream. `services/execution_guardrails.py:MAX_POSITION_NOTIONAL_PCT`
was hard-coded at 0.01 (1% of equity). For the operator's $250k
account aiming at $100k max trade notional (40% of equity), every
trade would have been vetoed at `pre_exec_guardrail_veto` with
`notional_over_cap: 100000 > 1.00%×equity (2500)`.

The fix:
  • Default raised 0.01 → 0.40 (matches the operator's chosen sizing).
  • Made env-tunable via EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT.
  • `max_pct=None` re-reads env at call-time so a hot config tweak
    takes effect on the next trade without a backend restart.

These tests pin the new behaviour + guard against regression.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest


# --------------------------------------------------------------------------
# 1. New default lets a $100k notional through on a $250k account
# --------------------------------------------------------------------------

def test_default_allows_100k_notional_on_250k_account():
    """Operator's intended sizing must pass at the new default."""
    from services.execution_guardrails import check_max_position_notional
    # $108 stock × 925 shares ≈ $99,900 notional
    r = check_max_position_notional(
        entry_price=108.00,
        shares=925,
        account_equity=250_000.00,
    )
    assert r.skip is False, (
        f"v19.12 REGRESSION: $99,900 notional on a $250k account is "
        f"only ~40% of equity — should be allowed under the new "
        f"40% default. Got: {r.reason}"
    )


def test_default_blocks_obviously_oversized_notional():
    """A 60%+ notional should still be blocked at the 40% default."""
    from services.execution_guardrails import check_max_position_notional
    r = check_max_position_notional(
        entry_price=100.00,
        shares=2000,
        account_equity=250_000.00,  # 200k notional = 80% of equity
    )
    assert r.skip is True
    assert "notional_over_cap" in r.reason


# --------------------------------------------------------------------------
# 2. Env override picks up at call-time
# --------------------------------------------------------------------------

def test_env_override_relaxes_to_70_percent():
    """Operator on a different account size sets a higher cap via env;
    the next call respects it without a restart."""
    from services.execution_guardrails import check_max_position_notional
    # 60% notional should pass when cap raised to 70%
    with patch.dict(os.environ, {"EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT": "0.70"}):
        r = check_max_position_notional(
            entry_price=100.00,
            shares=1500,
            account_equity=250_000.00,  # 150k = 60% of equity
        )
        assert r.skip is False, f"Env override 0.70 should permit 60% notional; got: {r.reason}"


def test_env_override_tightens_to_5_percent():
    """Conservative operator can still tighten via env."""
    from services.execution_guardrails import check_max_position_notional
    with patch.dict(os.environ, {"EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT": "0.05"}):
        r = check_max_position_notional(
            entry_price=100.00,
            shares=200,
            account_equity=250_000.00,  # 20k = 8% > 5% cap
        )
        assert r.skip is True


def test_explicit_max_pct_arg_overrides_env():
    """Caller passing an explicit `max_pct` skips env lookup entirely."""
    from services.execution_guardrails import check_max_position_notional
    with patch.dict(os.environ, {"EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT": "0.01"}):
        r = check_max_position_notional(
            entry_price=100.00,
            shares=400,
            account_equity=250_000.00,  # 40k = 16% notional
            max_pct=0.50,                # explicit 50% override
        )
        assert r.skip is False, f"Explicit max_pct=0.50 must win over env; got: {r.reason}"


# --------------------------------------------------------------------------
# 3. Defensive paths unchanged
# --------------------------------------------------------------------------

def test_invalid_size_still_rejected():
    from services.execution_guardrails import check_max_position_notional
    r = check_max_position_notional(0, 100, 250_000)
    assert r.skip is True
    assert r.reason == "invalid_size"


def test_missing_equity_falls_back_to_allow():
    """No equity = allow (don't silently block on a flaky equity feed)."""
    from services.execution_guardrails import check_max_position_notional
    r = check_max_position_notional(100, 200, 0)
    assert r.skip is False


# --------------------------------------------------------------------------
# 4. Module-level constant pinned to new default (so a future "tighten"
#    is a deliberate decision, not silent drift)
# --------------------------------------------------------------------------

def test_module_default_is_40_percent():
    # Reload to pick up env-free default
    with patch.dict(os.environ, {"EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT": ""}, clear=False):
        # Remove env var entirely
        if "EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT" in os.environ:
            del os.environ["EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT"]
        import services.execution_guardrails as eg
        importlib.reload(eg)
        assert eg.MAX_POSITION_NOTIONAL_PCT == 0.40, (
            "v19.12 REGRESSION: the module-level default for "
            "MAX_POSITION_NOTIONAL_PCT must be 0.40 (40% of equity). "
            "If a future contributor tightens this, they must update "
            "the operator's 5-pre-flight-check too."
        )


# --------------------------------------------------------------------------
# 5. Min-stop-distance guardrail still does its job (sanity check —
#    we DIDN'T loosen the stop guardrail, only the notional one)
# --------------------------------------------------------------------------

def test_tight_stop_still_rejected():
    """The pathological $0.03-stop-on-$108-stock case from the
    original 2026-04-21 audit must still trigger a veto."""
    from services.execution_guardrails import check_min_stop_distance
    r = check_min_stop_distance(
        entry_price=108.00,
        stop_price=107.97,  # $0.03 risk per share = pathological
        atr_14=2.0,
    )
    assert r.skip is True, "Tight stop must still be rejected"


def test_run_all_guardrails_returns_first_failure():
    """Pipeline still returns first failure (stop-distance, then notional)."""
    from services.execution_guardrails import run_all_guardrails
    # Both fail: tight stop AND oversized notional
    r = run_all_guardrails(
        entry_price=100.00,
        stop_price=99.999,        # 0.001 risk per share — too tight
        shares=10000,             # $1M notional — too big
        atr_14=1.0,
        account_equity=250_000.00,
    )
    assert r.skip is True
    # First failure wins → expect stop-distance reason, not notional
    assert "stop" in r.reason.lower() or "atr" in r.reason.lower(), (
        f"Expected stop-distance failure first; got: {r.reason}"
    )
