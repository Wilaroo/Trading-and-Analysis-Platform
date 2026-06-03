"""
v19.34.251 — Shadow Tracker measurement-bug fix.

Three root-caused bugs (the fake "18pt gap" / 4,407 `would_have_r==0.00`):
  1. `would_have_r` was hardcoded 0.00 because `track_pending_outcomes` never
     passed a stop to `update_outcome` AND no stop was stored on the decision.
  2. `would_have_pnl` was direction-blind (`outcome_price - entry`) — a winning
     short scored as a loss.
  3. `was_executed` was set from the AI's "proceed" recommendation at log time
     (~100% true), not from a real fill.

These tests lock the fix: geometry is captured at log time, outcome math is
direction-aware and R is computed from the stored stop, and `mark_executed`
is the single source of truth for the execution flag.
"""

from unittest.mock import MagicMock

import pytest

from services.ai_modules.shadow_tracker import ShadowTracker, ShadowDecision


def _wire_tracker():
    """ShadowTracker backed by an in-memory dict store keyed by decision id."""
    tracker = ShadowTracker()
    tracker._db = MagicMock()
    col = MagicMock()
    store = {}

    def _insert_one(doc):
        store[doc["id"]] = dict(doc)

    def _find_one(query, *a, **k):
        return store.get(query.get("id"))

    def _update_one(query, update, *a, **k):
        did = query.get("id")
        if did in store:
            store[did].update(update.get("$set", {}))
            return MagicMock(matched_count=1)
        return MagicMock(matched_count=0)

    col.insert_one.side_effect = _insert_one
    col.find_one.side_effect = _find_one
    col.update_one.side_effect = _update_one
    tracker._decisions_col = col
    return tracker, store


@pytest.mark.asyncio
async def test_log_decision_persists_trade_geometry():
    """direction / stop_price / target_price are stored on the decision."""
    tracker, store = _wire_tracker()
    d = await tracker.log_decision(
        symbol="MU", trigger_type="trade_opportunity", price_at_decision=100.0,
        direction="short", stop_price=102.0, target_price=94.0,
        debate_result={"winner": "bear"}, combined_recommendation="proceed",
    )
    saved = store[d.id]
    assert saved["direction"] == "short"
    assert saved["stop_price"] == 102.0
    assert saved["target_price"] == 94.0
    # was_executed must NOT be set from the recommendation — defaults False.
    assert saved["was_executed"] is False


@pytest.mark.asyncio
async def test_log_decision_normalises_enum_direction():
    """A direction passed as an enum-like object resolves via `.value`."""
    tracker, store = _wire_tracker()

    class _Dir:
        value = "SHORT"

    d = await tracker.log_decision(
        symbol="AAPL", trigger_type="t", price_at_decision=50.0,
        direction=_Dir(), stop_price=49.0,
    )
    assert store[d.id]["direction"] == "short"


@pytest.mark.asyncio
async def test_update_outcome_long_uses_stored_stop_for_r():
    """LONG: entry 100, stop 98 (risk 2), exit 104 → +4 pnl, +2.0R."""
    tracker, store = _wire_tracker()
    d = await tracker.log_decision(
        symbol="AAPL", trigger_type="t", price_at_decision=100.0,
        direction="long", stop_price=98.0,
    )
    res = await tracker.update_outcome(decision_id=d.id, outcome_price=104.0)
    assert res["would_have_pnl"] == pytest.approx(4.0)
    assert res["would_have_r"] == pytest.approx(2.0)
    assert store[d.id]["outcome_tracked"] is True


@pytest.mark.asyncio
async def test_update_outcome_short_is_direction_aware():
    """SHORT: entry 100, stop 102 (risk 2), exit 96 → +4 pnl (win!), +2.0R.

    Pre-fix this scored -4 pnl (loss) and 0.00R — the core of the fake gap.
    """
    tracker, store = _wire_tracker()
    d = await tracker.log_decision(
        symbol="MU", trigger_type="t", price_at_decision=100.0,
        direction="short", stop_price=102.0,
    )
    res = await tracker.update_outcome(decision_id=d.id, outcome_price=96.0)
    assert res["would_have_pnl"] == pytest.approx(4.0)   # short profit
    assert res["would_have_r"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_update_outcome_no_stop_leaves_r_zero_but_pnl_directional():
    """No stop anywhere → R stays 0 (can't compute) but pnl is still
    direction-aware."""
    tracker, store = _wire_tracker()
    d = await tracker.log_decision(
        symbol="X", trigger_type="t", price_at_decision=100.0,
        direction="short", stop_price=0.0,
    )
    res = await tracker.update_outcome(decision_id=d.id, outcome_price=90.0)
    assert res["would_have_pnl"] == pytest.approx(10.0)  # short, price fell
    assert res["would_have_r"] == 0.0


@pytest.mark.asyncio
async def test_mark_executed_flips_flag_and_links_trade():
    """mark_executed is the single source of truth for was_executed."""
    tracker, store = _wire_tracker()
    d = await tracker.log_decision(
        symbol="AAPL", trigger_type="t", price_at_decision=100.0,
        direction="long", stop_price=98.0,
    )
    assert store[d.id]["was_executed"] is False
    res = await tracker.mark_executed(d.id, trade_id="bt_123")
    assert res["success"] is True
    assert store[d.id]["was_executed"] is True
    assert store[d.id]["trade_id"] == "bt_123"
    assert store[d.id]["execution_reason"] == "bot_fired"


@pytest.mark.asyncio
async def test_mark_executed_safe_on_missing_decision():
    """Unknown decision id → success False, no raise."""
    tracker, _ = _wire_tracker()
    res = await tracker.mark_executed("does_not_exist", trade_id="bt_x")
    assert res["success"] is False


def test_from_dict_tolerates_legacy_docs_without_geometry():
    """Old shadow docs (pre-fix, no direction/stop) deserialize with defaults."""
    legacy = {"id": "sd_old", "symbol": "AAPL", "price_at_decision": 100.0}
    d = ShadowDecision.from_dict(legacy)
    assert d.direction == "long"
    assert d.stop_price == 0.0
    assert d.target_price == 0.0
