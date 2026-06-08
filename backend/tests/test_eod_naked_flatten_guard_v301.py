"""
v19.34.301 — pusher-independent EOD naked-flatten guard.

CONTEXT: when the IB pusher goes stale at EOD, `_naked_position_sweep` skips out
(PATCH E: pusher snapshot >45s stale; PATCH F: blind to ib_direct brackets in
direct mode), so naked positions can't be re-bracketed at exactly the wrong time.
The guard reads ib_direct DIRECTLY (pusher-independent) and, in the 15:45–16:00
ET window, flattens any IB position with no protective stop — including untracked
orphans the tracked-only EOD close would miss (the MA 2026-06-08 class).

These tests pin the pure naked-detection predicate `_ib_position_is_naked`,
which decides whether a position is unprotected at IB.
"""
from services.position_manager import _ib_position_is_naked


def _order(symbol, action, order_type=None, stop_price=None):
    return {"symbol": symbol, "action": action, "order_type": order_type, "stop_price": stop_price}


# ───────────────── long positions ─────────────────

def test_long_with_sell_stop_is_protected():
    orders = [_order("MA", "SELL", "STP", 470.0)]
    assert _ib_position_is_naked(100, "MA", orders) is False


def test_long_with_no_orders_is_naked():
    assert _ib_position_is_naked(100, "MA", []) is True


def test_long_with_only_sell_limit_target_is_naked():
    # A plain limit target is NOT downside protection.
    orders = [_order("MA", "SELL", "LMT", None)]
    assert _ib_position_is_naked(100, "MA", orders) is True


def test_long_with_buy_stop_is_naked():
    # A BUY stop does not protect a long.
    orders = [_order("MA", "BUY", "STP", 490.0)]
    assert _ib_position_is_naked(100, "MA", orders) is True


def test_long_protected_by_trail_stop():
    orders = [_order("MA", "SELL", "TRAIL", 5.0)]
    assert _ib_position_is_naked(100, "MA", orders) is False


def test_stop_price_present_counts_even_if_type_unlabeled():
    orders = [_order("MA", "SELL", None, 470.0)]
    assert _ib_position_is_naked(100, "MA", orders) is False


# ───────────────── short positions ─────────────────

def test_short_with_buy_stop_is_protected():
    orders = [_order("MA", "BUY", "STP", 490.0)]
    assert _ib_position_is_naked(-100, "MA", orders) is False


def test_short_with_no_orders_is_naked():
    assert _ib_position_is_naked(-100, "MA", []) is True


def test_short_with_sell_stop_is_naked():
    # SELL stop does not protect a short.
    orders = [_order("MA", "SELL", "STP", 470.0)]
    assert _ib_position_is_naked(-100, "MA", orders) is True


# ───────────────── edges ─────────────────

def test_flat_position_not_naked():
    assert _ib_position_is_naked(0, "MA", []) is False


def test_other_symbol_orders_ignored():
    orders = [_order("AAPL", "SELL", "STP", 200.0)]
    assert _ib_position_is_naked(100, "MA", orders) is True


def test_symbol_case_insensitive():
    orders = [_order("ma", "SELL", "STP", 470.0)]
    assert _ib_position_is_naked(100, "MA", orders) is False
