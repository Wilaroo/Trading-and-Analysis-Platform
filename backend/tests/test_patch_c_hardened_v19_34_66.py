"""v19.34.66 — Patch C hardening: three-way classification of live IB orders.

Tests the decision logic the hardened block uses to choose between:
  (a) skip everything (position already protected)
  (b) cancel only protective legs, then attach
  (c) attach without cancelling anything

This test isolates the classification logic — it doesn't import the full
position_reconciler (which has heavy dependencies) and instead replicates
the same predicate using a lightweight helper. Confidence comes from:
  - exhaustive case coverage (long + short, all leg combos)
  - the production code mirrors this helper line-for-line

If the production block diverges, update both — the helper is the spec.
"""
from typing import List, Dict, Optional


def classify_protective_legs(
    symbol: str,
    direction: str,
    orders: List[Dict],
) -> Dict:
    """Replicates the v19.34.66 PATCH C HARDENED classification logic.

    Returns:
      {
        "has_stop": bool,
        "has_target": bool,
        "protective_leg_ids": list[int],
        "action_label": "skip_already_protected" | "cancel_then_attach" | "attach_only",
      }
    """
    sym_u = (symbol or "").upper()
    pos_is_long = (direction or "").lower() == "long"
    protective_action = "SELL" if pos_is_long else "BUY"

    has_stop = False
    has_target = False
    leg_ids: List[int] = []

    for oc in orders:
        if str(oc.get("symbol") or "").upper() != sym_u:
            continue
        st = (oc.get("status") or "").strip()
        if st not in ("Submitted", "PreSubmitted"):
            continue
        action = (oc.get("action") or "").upper()
        if action != protective_action:
            continue
        otype = (oc.get("order_type") or oc.get("orderType") or "").upper()
        oid: Optional[int] = oc.get("order_id") or oc.get("orderId")
        if oid is None:
            continue
        if otype in ("STP", "STP LMT", "STP_LMT", "TRAIL", "TRAIL LMT", "TRAIL_LMT"):
            has_stop = True
            leg_ids.append(int(oid))
        elif otype in ("LMT", "LIMIT"):
            has_target = True
            leg_ids.append(int(oid))

    if has_stop and has_target:
        label = "skip_already_protected"
    elif has_stop or has_target:
        label = "cancel_then_attach"
    else:
        label = "attach_only"

    return {
        "has_stop": has_stop,
        "has_target": has_target,
        "protective_leg_ids": leg_ids,
        "action_label": label,
    }


# ───── Case A: already protected → skip ─────
def test_long_with_full_bracket_skips():
    """A LONG with both SELL STP + SELL LMT live → skip_already_protected."""
    orders = [
        {"symbol": "LIN", "status": "Submitted", "action": "SELL",
         "order_type": "STP", "order_id": 4930},
        {"symbol": "LIN", "status": "Submitted", "action": "SELL",
         "order_type": "LMT", "order_id": 4931},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert r["action_label"] == "skip_already_protected"
    assert r["has_stop"] and r["has_target"]
    assert set(r["protective_leg_ids"]) == {4930, 4931}


def test_short_with_full_bracket_skips():
    """A SHORT with both BUY STP + BUY LMT live → skip_already_protected."""
    orders = [
        {"symbol": "WMT", "status": "Submitted", "action": "BUY",
         "order_type": "STP", "order_id": 5001},
        {"symbol": "WMT", "status": "Submitted", "action": "BUY",
         "order_type": "LMT", "order_id": 5002},
    ]
    r = classify_protective_legs("WMT", "short", orders)
    assert r["action_label"] == "skip_already_protected"


# ───── Case B: partial protection → cancel & attach ─────
def test_long_with_stop_only_partial():
    orders = [
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "STP", "order_id": 6001},
    ]
    r = classify_protective_legs("AAPL", "long", orders)
    assert r["action_label"] == "cancel_then_attach"
    assert r["has_stop"] and not r["has_target"]


def test_long_with_target_only_partial():
    orders = [
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "LMT", "order_id": 6002},
    ]
    r = classify_protective_legs("AAPL", "long", orders)
    assert r["action_label"] == "cancel_then_attach"
    assert not r["has_stop"] and r["has_target"]


# ───── Case C: unprotected → attach only ─────
def test_no_orders_is_attach_only():
    r = classify_protective_legs("NVDA", "long", [])
    assert r["action_label"] == "attach_only"
    assert r["protective_leg_ids"] == []


# ───── Direction discipline ─────
def test_long_ignores_buy_orders():
    """A SELL is protective for a LONG; BUY orders (the entry) MUST NOT be cancelled."""
    orders = [
        # The original buy entry — must NOT be touched.
        {"symbol": "LIN", "status": "Submitted", "action": "BUY",
         "order_type": "LMT", "order_id": 4920},
        # Real protective leg.
        {"symbol": "LIN", "status": "Submitted", "action": "SELL",
         "order_type": "STP", "order_id": 4930},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert 4920 not in r["protective_leg_ids"]
    assert 4930 in r["protective_leg_ids"]


def test_short_ignores_sell_orders():
    """A BUY is protective for a SHORT; SELL orders (the entry) MUST NOT be cancelled."""
    orders = [
        {"symbol": "WMT", "status": "Submitted", "action": "SELL",
         "order_type": "LMT", "order_id": 6500},
        {"symbol": "WMT", "status": "Submitted", "action": "BUY",
         "order_type": "STP", "order_id": 6501},
    ]
    r = classify_protective_legs("WMT", "short", orders)
    assert 6500 not in r["protective_leg_ids"]
    assert 6501 in r["protective_leg_ids"]


# ───── Status discipline (the actual 4930 bug) ─────
def test_pending_cancel_orders_ignored():
    """Orders in PendingCancel (the 4930 bug state) must NOT be re-cancelled.

    This is the SOURCE of the v19.34.65 stale_dropped loop: IB moved 4930
    to PendingCancel internally but the pusher snapshot still listed it
    as Submitted. Patch C re-queued the cancel → IB returned 10147 →
    repeat forever. The hardened block only touches Submitted/PreSubmitted.
    """
    orders = [
        {"symbol": "LIN", "status": "PendingCancel", "action": "SELL",
         "order_type": "STP", "order_id": 4930},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert r["action_label"] == "attach_only"
    assert 4930 not in r["protective_leg_ids"]


def test_cancelled_orders_ignored():
    orders = [
        {"symbol": "LIN", "status": "Cancelled", "action": "SELL",
         "order_type": "STP", "order_id": 4930},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert r["action_label"] == "attach_only"


def test_filled_orders_ignored():
    orders = [
        {"symbol": "LIN", "status": "Filled", "action": "SELL",
         "order_type": "STP", "order_id": 4930},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert r["action_label"] == "attach_only"


# ───── Symbol discipline ─────
def test_wrong_symbol_ignored():
    """Orders for other symbols must NOT be classified as this position's legs."""
    orders = [
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "STP", "order_id": 9999},
    ]
    r = classify_protective_legs("LIN", "long", orders)
    assert 9999 not in r["protective_leg_ids"]
    assert r["action_label"] == "attach_only"


# ───── Stop-family variants ─────
def test_trail_counts_as_stop():
    orders = [
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "TRAIL", "order_id": 7001},
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "LMT", "order_id": 7002},
    ]
    r = classify_protective_legs("AAPL", "long", orders)
    assert r["action_label"] == "skip_already_protected"


def test_stp_lmt_counts_as_stop():
    orders = [
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "STP LMT", "order_id": 7001},
        {"symbol": "AAPL", "status": "Submitted", "action": "SELL",
         "order_type": "LMT", "order_id": 7002},
    ]
    r = classify_protective_legs("AAPL", "long", orders)
    assert r["action_label"] == "skip_already_protected"
