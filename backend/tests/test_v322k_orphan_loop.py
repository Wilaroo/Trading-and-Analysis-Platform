"""
test_v322k_orphan_loop.py — regression tests for the 2026-06-11 UNP/USB
cancel↔re-issue loop.

Incident chain: a backend restart seconds after two entries filled left the
positions to generic orphan adoption; the naked-sweep attached ADOPT-OCA
brackets; the orphan-GTC classifier could not see TODAY's bot_trades rows
(unsorted limit(2000) returned the OLDEST 30-day rows) so it auto-cancelled
the fresh brackets as `orphan_no_trade`; the naked-sweep re-issued; repeat
every ~60s, leaving positions naked between cycles.

Guards:
  1. Classifier matches an order to its bot trade via the ADOPT-OCA group
     token even when order-id fields in the snapshot are stale.
  2. Genuine orphans (no id match, no OCA token) still classify as
     orphan_no_trade — the fallback must not over-match.
  3. Short tokens / symbol fragments in OCA groups never false-match.
  4. The Mongo snapshot sorts newest-first before the row cap.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.orphan_gtc_reconciler import classify_open_orders  # noqa: E402


def _order(oid, sym="UNP", oca="", action="SELL", qty=69, otype="STP"):
    return {
        "ib_order_id": oid, "symbol": sym, "action": action,
        "quantity": qty, "order_type": otype, "limit_price": None,
        "stop_price": 262.20, "time_in_force": "DAY", "status": "Submitted",
        "oca_group": oca,
    }


POSITIONS = [{"symbol": "UNP", "position": 69.0}]


def test_oca_group_token_rescues_stale_snapshot():
    """Trade row has STALE order ids (the incident state) — the ADOPT-OCA
    group token must still prove ownership → tracked, not orphan."""
    trades = [{"id": "3faaf3a1", "symbol": "UNP", "status": "open",
               "remaining_shares": 69,
               "stop_order_id": 353611, "target_order_id": 353612}]  # stale
    verdicts = classify_open_orders(
        ib_open_orders=[_order(355455, oca="ADOPT-OCA-UNP-3faaf3a1-2dc509")],
        ib_positions=POSITIONS,
        bot_trades=trades,
        only_gtc=False,
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.verdict == "tracked", (v.verdict, v.reasons)
    assert v.bot_trade_id == "3faaf3a1"


def test_genuine_orphan_still_flagged():
    trades = [{"id": "deadbeef", "symbol": "UNP", "status": "open",
               "remaining_shares": 69, "stop_order_id": 111}]
    verdicts = classify_open_orders(
        ib_open_orders=[_order(354657, oca="")],   # the real boot orphans
        ib_positions=POSITIONS,
        bot_trades=trades,
        only_gtc=False,
    )
    assert verdicts[0].verdict == "orphan_no_trade", verdicts[0].reasons


def test_short_tokens_never_false_match():
    """Symbol fragments / 6-char nonces in the OCA group must not match a
    trade id (we require >= 8 chars)."""
    trades = [{"id": "2dc509", "symbol": "UNP", "status": "open",   # 6 chars
               "remaining_shares": 69, "stop_order_id": 111}]
    verdicts = classify_open_orders(
        ib_open_orders=[_order(355455, oca="ADOPT-OCA-UNP-aaaaaaaa-2dc509")],
        ib_positions=POSITIONS,
        bot_trades=trades,
        only_gtc=False,
    )
    assert verdicts[0].verdict == "orphan_no_trade", (
        "6-char OCA nonce must not satisfy the trade-id fallback")


def test_order_id_match_still_first_class():
    trades = [{"id": "3faaf3a1", "symbol": "UNP", "status": "open",
               "remaining_shares": 69, "stop_order_id": 355455}]
    verdicts = classify_open_orders(
        ib_open_orders=[_order(355455, oca="")],
        ib_positions=POSITIONS,
        bot_trades=trades,
        only_gtc=False,
    )
    assert verdicts[0].verdict == "tracked"


def test_snapshot_sorts_newest_first():
    src = (ROOT / "services" / "orphan_gtc_reconciler.py").read_text()
    assert '.sort("executed_at", -1).limit(2000)' in src, (
        "bot_trades snapshot must sort newest-first before the cap — "
        "unsorted limit drops TODAY's trades once 30d window > 2000 rows")
