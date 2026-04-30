"""Pre-trade guard rails (2026-04-21).

Hard vetoes that run after the confidence gate but BEFORE any order hits the
broker. These stop known-bad trades before they become known-bad positions.

Rationale
---------
The 2026-04-21 audit showed the USO vwap_fade_short trades bled ~-261R per
trade because the risk distance was absurdly small ($0.03 on a $108 stock =
noise, not a stop). Even a perfect atomic bracket at IB can't save you from
stops so tight they're guaranteed to get hit on normal tick chop.

These rules are setup-agnostic and intentionally conservative. They live in a
pure module so we can unit-test without Mongo/IB.

2026-04-30 v19.12 — `MAX_POSITION_NOTIONAL_PCT` was 0.01 (1% of equity)
under the assumption "temporary ceiling while bracket migration is in
progress". Bracket migration shipped (IB_BRACKET_ORDER_MIGRATION.md
checked off Phase 3). For a $250k margin account where the operator
sized `max_notional_per_trade=$100,000` (40% of equity), the 1% cap
would VETO every trade with `notional_over_cap`. Default raised to 0.40
and made env-tunable via `EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT` so
future operators on different account sizes don't hit the same wall.
The position-sizer's `max_notional_per_trade` is now the primary cap
(belt-and-braces); this guardrail just catches accidents from the
sizer, not normal sizing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env_float(key: str, default: float) -> float:
    """Read float env var with default; ignore typos / blank."""
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# Defaults — tuneable but intentionally conservative.
# Stop must be ≥ this × ATR(14) from entry (or fallback %, if ATR unavailable).
MIN_STOP_DISTANCE_ATR_MULT = _env_float("EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT", 0.3)
MIN_STOP_DISTANCE_PCT = _env_float("EXECUTION_GUARDRAIL_MIN_STOP_PCT", 0.001)  # 10 bps
# 2026-04-30 v19.12 — was 0.01 (1%); raised to 0.40 (40%) and made env-
# tunable. Operator's `max_notional_per_trade` (RiskParameters) is now
# the primary per-trade notional cap; this guardrail catches sizer
# accidents, not normal sizing decisions.
MAX_POSITION_NOTIONAL_PCT = _env_float("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", 0.40)


@dataclass
class GuardrailResult:
    allow: bool
    reason: str  # "" when allow=True

    @property
    def skip(self) -> bool:
        return not self.allow


def check_min_stop_distance(
    entry_price: float,
    stop_price: float,
    atr_14: Optional[float] = None,
    atr_mult: float = MIN_STOP_DISTANCE_ATR_MULT,
    min_pct: float = MIN_STOP_DISTANCE_PCT,
) -> GuardrailResult:
    """Reject when stop is closer to entry than 0.3 × ATR or 10 bps (fallback).

    Pure function. atr_14 may be None (we fall back to percentage-of-price).
    """
    if not (entry_price and entry_price > 0 and stop_price and stop_price > 0):
        return GuardrailResult(False, "invalid_prices")
    distance = abs(entry_price - stop_price)
    if distance <= 0:
        return GuardrailResult(False, "zero_stop_distance")

    if atr_14 and atr_14 > 0:
        threshold = atr_mult * atr_14
        if distance < threshold:
            return GuardrailResult(
                False,
                f"stop_too_tight: |{entry_price}-{stop_price}|={distance:.4f} "
                f"< {atr_mult}×ATR({atr_14:.4f})={threshold:.4f}",
            )
    else:
        threshold_pct = min_pct * entry_price
        if distance < threshold_pct:
            return GuardrailResult(
                False,
                f"stop_too_tight_pct: distance={distance:.4f} < {min_pct*100:.2f}% "
                f"of entry ({threshold_pct:.4f}) — no ATR available",
            )
    return GuardrailResult(True, "")


def check_max_position_notional(
    entry_price: float,
    shares: int,
    account_equity: float,
    max_pct: Optional[float] = None,
) -> GuardrailResult:
    """Reject when position notional > `max_pct` of account equity.

    Small positions = small damage if a stop fails. Temporary ceiling while
    bracket migration is in progress.

    `max_pct=None` re-reads the env at call-time so a hot config tweak
    takes effect on the next trade without a backend restart.
    """
    # Re-read env on each call when caller didn't supply an explicit value.
    # `EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT` is the operator-facing knob.
    if max_pct is None:
        max_pct = _env_float("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", 0.40)
    if not (entry_price and entry_price > 0 and shares and shares > 0):
        return GuardrailResult(False, "invalid_size")
    if not (account_equity and account_equity > 0):
        # No equity info → allow (we don't want guardrail to silently block
        # everything if equity feed is flaky). The min-stop-distance rule
        # alone is enough protection in this case.
        return GuardrailResult(True, "")
    notional = entry_price * shares
    cap = max_pct * account_equity
    if notional > cap:
        return GuardrailResult(
            False,
            f"notional_over_cap: {notional:.0f} > {max_pct*100:.2f}%×equity "
            f"({cap:.0f})",
        )
    return GuardrailResult(True, "")


def run_all_guardrails(
    entry_price: float,
    stop_price: float,
    shares: int,
    atr_14: Optional[float] = None,
    account_equity: Optional[float] = None,
) -> GuardrailResult:
    """Run the full pre-trade veto suite. Returns first failure, or allow."""
    r1 = check_min_stop_distance(entry_price, stop_price, atr_14=atr_14)
    if r1.skip:
        return r1
    if account_equity is not None:
        r2 = check_max_position_notional(entry_price, shares, account_equity)
        if r2.skip:
            return r2
    return GuardrailResult(True, "")
