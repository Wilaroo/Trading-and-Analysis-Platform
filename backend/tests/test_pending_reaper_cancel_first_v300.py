"""
v19.34.300 — cancel-before-reap guard for the stale-pending reaper.

ROOT CAUSE (MA, 2026-06-08): the reaper marked a stale `pending` row `rejected`
(`stale_pending_auto_reaper`) and dropped tracking WITHOUT cancelling the still-
working entry order at IB. The order then filled AFTER the reap → the reconciler
adopted an unknown IB position as a synthetic, possibly-naked orphan. The v234
position guard only catches orders ALREADY filled at reap time — it is blind to a
fill that lands later (state_integrity 'reaper_skip_likely_filled' = 0 ever,
despite the MA orphan).

FIX: before reaping, if a WORKING order still exists at IB, cancel it; if it
can't be provably killed, KEEP tracking instead of abandoning it.

These tests pin the pure decision predicate `_reaper_order_still_working` and
re-confirm the existing `_reaper_should_skip_filled` guard is untouched.
"""
from services.trading_bot_service import (
    _reaper_order_still_working,
    _reaper_should_skip_filled,
)


# ───────────────── _reaper_order_still_working (the v300 predicate) ─────────────────

def test_working_order_matched_by_order_id():
    live = {12345: {"symbol": "MA"}}
    assert _reaper_order_still_working(12345, "MA", live, {"MA"}) is True
    # string order id is coerced
    assert _reaper_order_still_working("12345", "MA", live, {"MA"}) is True


def test_working_order_matched_by_symbol_when_orderid_missing():
    """entry_order_id=None race must still trip the guard (don't abandon)."""
    assert _reaper_order_still_working(None, "MA", {}, {"MA"}) is True
    assert _reaper_order_still_working("", "MA", {}, {"MA"}) is True
    assert _reaper_order_still_working(0, "MA", {}, {"MA"}) is True


def test_no_working_order_is_reapable():
    """No order id match AND no symbol match → genuinely dead → safe to reap."""
    assert _reaper_order_still_working(99999, "MA", {12345: {}}, {"AAPL"}) is False
    assert _reaper_order_still_working(None, "MA", {}, set()) is False


def test_order_id_mismatch_but_symbol_matches_still_live():
    # A different working order for the same symbol exists → conservative: live.
    assert _reaper_order_still_working(99999, "MA", {}, {"MA"}) is True


def test_malformed_order_id_falls_back_to_symbol():
    assert _reaper_order_still_working("not-an-int", "MA", {}, {"MA"}) is True
    assert _reaper_order_still_working("not-an-int", "MA", {}, set()) is False


def test_empty_inputs_safe():
    assert _reaper_order_still_working(None, "", {}, set()) is False
    assert _reaper_order_still_working(None, "MA", None, None) is False


# ───────────────── existing v234 guard — must remain intact ─────────────────

def test_skip_filled_guard_unchanged():
    # IB holds a position the bot isn't tracking → skip (likely unattributed fill).
    assert _reaper_should_skip_filled("MA", {"MA"}, set()) is True
    # Bot already tracks it as open → not an orphan → don't skip.
    assert _reaper_should_skip_filled("MA", {"MA"}, {"MA"}) is False
    # No IB position → nothing to protect → don't skip.
    assert _reaper_should_skip_filled("MA", set(), set()) is False
