"""
v19.34.236 (Part A) — pending fill attribution matcher tests.

`match_pending_to_orphan` must re-attribute an unattributed live IB fill to the
correct original PENDING row (so it's promoted to OPEN instead of reaped +
re-adopted as a synthetic slice), without ever matching the wrong direction,
symbol, an in-flight (too-young) entry, an ancient pending, or an order too
small to have produced the fill.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pending_fill_attribution import (  # noqa: E402
    match_pending_to_orphan, build_promotion_update,
)

NOW = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)


def _p(pid, symbol, direction, shares, age_s):
    return {
        "id": pid, "symbol": symbol, "direction": direction, "shares": shares,
        "pre_submit_at": (NOW - timedelta(seconds=age_s)).isoformat(),
    }


def test_exact_match_promotes_the_pending():
    # The SOXX incident: IB long +43, original pending SOXX long 43 @ 120s old.
    rows = [_p("t1", "SOXX", "long", 43, 120)]
    assert match_pending_to_orphan("SOXX", 43, rows, NOW) == "t1"


def test_direction_must_match():
    rows = [_p("t1", "SOXX", "short", 43, 120)]
    assert match_pending_to_orphan("SOXX", 43, rows, NOW) is None  # orphan is long


def test_short_orphan_matches_short_pending():
    rows = [_p("t1", "TSLA", "short", 50, 200)]
    assert match_pending_to_orphan("TSLA", -50, rows, NOW) == "t1"


def test_symbol_must_match():
    rows = [_p("t1", "LRCX", "long", 43, 120)]
    assert match_pending_to_orphan("SOXX", 43, rows, NOW) is None


def test_too_young_is_skipped():
    # 10s old -> likely a normal in-flight fill; do NOT attribute (avoid racing).
    rows = [_p("t1", "SOXX", "long", 43, 10)]
    assert match_pending_to_orphan("SOXX", 43, rows, NOW) is None


def test_too_old_is_skipped():
    rows = [_p("t1", "SOXX", "long", 43, 7200)]  # 2h
    assert match_pending_to_orphan("SOXX", 43, rows, NOW) is None


def test_overfill_beyond_tolerance_is_skipped():
    # IB shows 100 but the order was only 43 -> 100 > 43*1.5 -> not this order.
    rows = [_p("t1", "SOXX", "long", 43, 120)]
    assert match_pending_to_orphan("SOXX", 100, rows, NOW) is None


def test_partial_fill_within_tolerance_matches():
    rows = [_p("t1", "SOXX", "long", 43, 120)]
    assert match_pending_to_orphan("SOXX", 40, rows, NOW) == "t1"


def test_closest_share_count_wins_then_oldest():
    rows = [
        _p("t_close", "SOXX", "long", 26, 100),
        _p("t_far", "SOXX", "long", 43, 300),
        _p("t_exact", "SOXX", "long", 25, 200),
    ]
    # orphan 25 -> exact 25 wins
    assert match_pending_to_orphan("SOXX", 25, rows, NOW) == "t_exact"


def test_tie_breaks_to_oldest():
    rows = [
        _p("newer", "SOXX", "long", 30, 60),
        _p("older", "SOXX", "long", 30, 300),
    ]
    assert match_pending_to_orphan("SOXX", 30, rows, NOW) == "older"


def test_zero_or_no_orphan_returns_none():
    rows = [_p("t1", "SOXX", "long", 43, 120)]
    assert match_pending_to_orphan("SOXX", 0, rows, NOW) is None
    assert match_pending_to_orphan("SOXX", 43, [], NOW) is None


def test_promotion_update_shape():
    upd = build_promotion_update(17, 612.71, NOW.isoformat())
    assert upd["status"] == "open"
    assert upd["remaining_shares"] == 17 and upd["original_shares"] == 17
    assert upd["shares"] == 17
    assert upd["fill_price"] == 612.71
    assert upd["close_reason"] is None and upd["reaped_at"] is None
    assert upd["executed_at"] == NOW.isoformat()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
