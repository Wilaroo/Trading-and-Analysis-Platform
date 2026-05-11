"""
v19.34.71 — Two-tick external-close confirmation regression
=============================================================

Background
----------
2026-05-11: bot recorded a phantom realized loss (~$326) on NBIS when
both IB sources (pusher + direct) briefly read zero shares mid-fill.
v19.34.52's pusher+direct cross-check passed, the reconciler entered
the `zero_external_close` branch, and the bot wrote off the trade.

The position was NOT actually closed at IB — a fill notification was
in flight, and the snapshot caught a race window where both sources
saw the pre-fill state. By the next scan, IB was back to non-zero, but
the bot had already recorded `external_close_v19_34_15b` and the local
P&L was permanently wrong.

Fix
---
Require TWO consecutive scans showing IB=0 (or partial) for the SAME
`(symbol, bot_trade_id_set)` before recording the accounting event.
First sighting → stash, no close. Next scan: if state still matches,
confirm and close. If the symbol recovered to non-zero in between, drop
the pending confirmation so a future zero starts a fresh two-tick window.

This unit-tests the gate function `_confirm_external_close_two_tick`
directly, since the full reconciler scan loop requires a live bot +
IB pusher.

Assertions
----------
1. First sighting returns `(False, "first_sighting_v19_34_71")` and
   stashes a pending entry.
2. Second sighting with SAME trade-id set returns
   `(True, "confirmed_two_tick_v19_34_71")` and clears the pending
   entry (a re-occurrence requires a fresh two-tick cycle).
3. Second sighting with DIFFERENT trade-id set returns
   `(False, "trade_set_changed_v19_34_71")` and restarts the window.
4. Pending entry past TTL is treated as a new first sighting.
5. `_clear_pending_external_close(symbol)` removes the pending entry.
6. Pending entries are keyed by uppercased symbol — case insensitive.
7. Zero and partial drift kinds share the same key (so a symbol that
   was pending zero then flips to partial doesn't get a free confirm,
   but the SAME (symbol, trade-set) still confirms across two ticks
   even if drift_kind changed — the trade-set check is the authoritative
   guard).
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "/app/backend")


def _fresh_reconciler():
    """Construct a PositionReconciler without touching real Mongo."""
    from services.position_reconciler import PositionReconciler
    return PositionReconciler(db=None)


def test_first_sighting_does_not_confirm():
    rec = _fresh_reconciler()
    confirmed, reason = rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1", "trade-2"},
        drift_kind="zero",
    )
    assert confirmed is False
    assert reason == "first_sighting_v19_34_71"
    # Pending entry is stashed.
    assert "NBIS" in rec._pending_external_close


def test_second_sighting_same_trade_set_confirms():
    rec = _fresh_reconciler()
    rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1", "trade-2"},
        drift_kind="zero",
    )
    # Second tick, same set.
    confirmed, reason = rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1", "trade-2"},
        drift_kind="zero",
    )
    assert confirmed is True
    assert reason == "confirmed_two_tick_v19_34_71"
    # After confirmation, pending is cleared — re-occurrence needs
    # another fresh two-tick window.
    assert "NBIS" not in rec._pending_external_close


def test_second_sighting_different_trade_set_resets_window():
    """If bot opened or closed trades for this symbol between scans,
    we can't trust either reading — restart the confirmation window."""
    rec = _fresh_reconciler()
    rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1", "trade-2"},
        drift_kind="zero",
    )
    confirmed, reason = rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1", "trade-2", "trade-3"},  # new trade appeared
        drift_kind="zero",
    )
    assert confirmed is False
    assert reason == "trade_set_changed_v19_34_71"
    # Window restarted — pending entry now reflects the new set.
    pending = rec._pending_external_close["NBIS"]
    assert pending["bot_trade_ids"] == {"trade-1", "trade-2", "trade-3"}


def test_pending_entry_expires_after_ttl():
    """If the second scan doesn't arrive within TTL, treat as new
    first sighting (don't auto-confirm stale pending entries)."""
    # Force a short TTL so the test is fast.
    os.environ["PENDING_EXTERNAL_CLOSE_TTL_S"] = "0.05"
    try:
        rec = _fresh_reconciler()
        rec._confirm_external_close_two_tick(
            symbol="NBIS",
            bot_trade_ids={"trade-1"},
            drift_kind="zero",
        )
        time.sleep(0.1)  # exceed TTL
        confirmed, reason = rec._confirm_external_close_two_tick(
            symbol="NBIS",
            bot_trade_ids={"trade-1"},
            drift_kind="zero",
        )
        assert confirmed is False
        assert reason == "first_sighting_v19_34_71"
    finally:
        os.environ.pop("PENDING_EXTERNAL_CLOSE_TTL_S", None)


def test_clear_pending_external_close_removes_entry():
    rec = _fresh_reconciler()
    rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1"},
        drift_kind="zero",
    )
    assert "NBIS" in rec._pending_external_close
    rec._clear_pending_external_close("NBIS")
    assert "NBIS" not in rec._pending_external_close


def test_symbol_lookup_is_case_insensitive():
    rec = _fresh_reconciler()
    rec._confirm_external_close_two_tick(
        symbol="nbis",   # lowercase
        bot_trade_ids={"trade-1"},
        drift_kind="zero",
    )
    confirmed, _ = rec._confirm_external_close_two_tick(
        symbol="NBIS",   # uppercase
        bot_trade_ids={"trade-1"},
        drift_kind="zero",
    )
    assert confirmed is True


def test_two_tick_gate_independent_per_symbol():
    """Confirmation state for one symbol must not leak to another."""
    rec = _fresh_reconciler()
    rec._confirm_external_close_two_tick(
        symbol="NBIS",
        bot_trade_ids={"trade-1"},
        drift_kind="zero",
    )
    # Different symbol's first sighting must NOT confirm.
    confirmed, reason = rec._confirm_external_close_two_tick(
        symbol="AAPL",
        bot_trade_ids={"trade-1"},
        drift_kind="zero",
    )
    assert confirmed is False
    assert reason == "first_sighting_v19_34_71"
    # NBIS is still pending its own second tick.
    assert "NBIS" in rec._pending_external_close
    assert "AAPL" in rec._pending_external_close
