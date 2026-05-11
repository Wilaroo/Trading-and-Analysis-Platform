"""
v19.34.70 — NBIS symbol-exposure-saturated cooldown regression
================================================================

Background
----------
2026-05-11 live session: operator observed the bot opening multiple
fragmented NBIS positions in rapid succession, with the per-symbol
exposure cap repeatedly being hit and the bot retrying with smaller
sizes — "death by a thousand cuts" fragmentation.

Root cause
----------
The sizer in `services/opportunity_evaluator.py::calculate_position_size`
clamps `shares` down to whatever fits under `max_symbol_exposure_usd`
(v19.20 fix from 2026-05-01). When existing exposure already equals or
exceeds the cap, the clamp produces `shares=0` and the caller logs the
rejection as `position_size_zero`. That reason code is NOT in
`STRUCTURAL_REJECTION_REASONS`, so the `rejection_cooldown` service
never engages — the bot loops every 30-60s producing fresh trade_ids
and squeezing one more tiny order in whenever it transiently saw a few
shares of headroom.

Fix
---
- `calculate_position_size` now writes `block_reason="symbol_exposure_saturated"`
  into the `multipliers_out` dict on the cap-saturated branch so the
  caller can distinguish it from generic sizing-zero.
- Caller routes that branch to `record_rejection(reason_code="symbol_exposure_saturated")`
  AND directly calls `rejection_cooldown.mark_rejection(...)` so the
  per-(symbol, setup_type) cooldown engages immediately.
- `rejection_cooldown_service.STRUCTURAL_REJECTION_REASONS` now includes
  `"symbol_exposure_saturated"` so any future producer firing this code
  also feeds the cooldown by default.
- `_compose_rejection_narrative` has a new branch so the Bot's Brain
  panel surfaces a human-readable "Cooling off on NBIS" message instead
  of looking silent.

Assertions
----------
1. `symbol_exposure_saturated` is classified as a STRUCTURAL rejection
   reason (so the cooldown engages on `mark_rejection`).
2. After a `symbol_exposure_saturated` rejection, the
   `(symbol, setup_type)` pair is in cooldown — subsequent
   `is_in_cooldown(...)` calls return a live cooldown.
3. The cooldown is keyed by symbol AND setup_type (different setup on
   the same symbol is unaffected; same setup on a different symbol is
   unaffected).
4. The narrative composer emits the cooldown-aware message for
   `reason_code="symbol_exposure_saturated"`.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, "/app/backend")


def test_symbol_exposure_saturated_is_structural():
    from services.rejection_cooldown_service import (
        is_structural_rejection, STRUCTURAL_REJECTION_REASONS,
    )
    assert "symbol_exposure_saturated" in STRUCTURAL_REJECTION_REASONS
    assert is_structural_rejection("symbol_exposure_saturated") is True


def test_mark_rejection_engages_cooldown_for_saturated_cap():
    """`mark_rejection(reason='symbol_exposure_saturated')` must put the
    (symbol, setup_type) into a live cooldown that future `is_in_cooldown`
    calls observe."""
    # Fresh singleton — patch the module-level instance directly.
    import services.rejection_cooldown_service as rcs
    rc = rcs.RejectionCooldown()  # fresh instance, not the singleton

    # Before: no cooldown active.
    assert rc.is_in_cooldown("NBIS", "breakout") is None

    rc.mark_rejection(
        symbol="NBIS", setup_type="breakout",
        reason="symbol_exposure_saturated",
    )

    # After: cooldown active for NBIS/breakout.
    cd = rc.is_in_cooldown("NBIS", "breakout")
    assert cd is not None
    assert cd.symbol == "NBIS"
    assert cd.setup_type == "breakout"
    assert cd.reason == "symbol_exposure_saturated"
    assert cd.rejection_count == 1
    assert cd.remaining_seconds() > 0


def test_cooldown_is_keyed_by_symbol_and_setup():
    """NBIS/breakout cooldown must NOT block NBIS/orb or AMD/breakout."""
    import services.rejection_cooldown_service as rcs
    rc = rcs.RejectionCooldown()

    rc.mark_rejection(
        symbol="NBIS", setup_type="breakout",
        reason="symbol_exposure_saturated",
    )

    # Same symbol, different setup → no cooldown.
    assert rc.is_in_cooldown("NBIS", "orb") is None
    # Different symbol, same setup → no cooldown.
    assert rc.is_in_cooldown("AMD", "breakout") is None
    # Original key → cooldown active.
    assert rc.is_in_cooldown("NBIS", "breakout") is not None


def test_narrative_emits_cooling_off_message():
    """`_compose_rejection_narrative` must produce a human-readable
    'Cooling off' message for `symbol_exposure_saturated`, so the
    Bot's Brain panel doesn't look silent after the cooldown engages."""
    # Import the method off the class without instantiating the full bot
    # (which requires Mongo). The composer is a pure method.
    from services.trading_bot_service import TradingBotService

    # Lightweight stand-in for self with the attributes the composer
    # actually reads. The composer is pure; it doesn't reach into bot
    # state for this reason_code.
    bot_stub = SimpleNamespace()
    narrative = TradingBotService._compose_rejection_narrative(
        bot_stub,
        symbol="NBIS",
        setup_type="breakout",
        direction="long",
        reason_code="symbol_exposure_saturated",
        ctx={
            "existing_sym_exposure_usd": 14_800.0,
            "safety_cap_usd": 15_000.0,
        },
    )
    assert "NBIS" in narrative
    assert "Cooling off" in narrative or "cooling off" in narrative.lower()
    assert "$14,800" in narrative
    assert "$15,000" in narrative
    # Operator-asked-for phrase that explains the WHY.
    assert "cooldown" in narrative.lower()


def test_repeat_rejection_extends_cooldown():
    """A second rejection within the cooldown window should extend (or at
    least not shorten) the cooldown — the bot's relentless re-evaluation
    must not accidentally clear its own gate."""
    import services.rejection_cooldown_service as rcs
    rc = rcs.RejectionCooldown()

    rc.mark_rejection(
        symbol="NBIS", setup_type="breakout",
        reason="symbol_exposure_saturated",
    )
    first = rc.is_in_cooldown("NBIS", "breakout")
    assert first is not None
    first_expiry = first.expires_at

    rc.mark_rejection(
        symbol="NBIS", setup_type="breakout",
        reason="symbol_exposure_saturated",
    )
    second = rc.is_in_cooldown("NBIS", "breakout")
    assert second is not None
    assert second.rejection_count == 2
    assert second.expires_at >= first_expiry
