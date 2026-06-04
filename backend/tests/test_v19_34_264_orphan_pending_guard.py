"""
v19.34.264 — orphan-vs-pending guard regression.

Reproduces the 2026-06-04 MRSH/CEG mis-adoption: the bot pre-submitted an entry
that filled at IB but lost fill attribution; ~218s later the orphan reconciler
adopted the position with a synthetic 2% bracket and the reaper then rejected
the real bot row. The v264 fix makes the reconciler consult the SAME
`match_pending_to_orphan` matcher the v236 promoter uses (now also scanning
`_pending_trades`) and SKIP adoption on a match.

These tests lock the matcher behavior the v264 reconciler-skip depends on, using
the real incident parameters, and verify the dict-shape the reconciler builds
from `_pending_trades` (enum-valued direction) feeds the matcher correctly.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pending_fill_attribution import match_pending_to_orphan  # noqa: E402

NOW = datetime(2026, 6, 4, 13, 50, 14, tzinfo=timezone.utc)


class _Dir(Enum):
    LONG = "long"
    SHORT = "short"


def _pending_row_like_reconciler(pid, symbol, direction_enum, shares, pre_submit_dt):
    """Build the row exactly as position_reconciler v264 builds it from a
    BotTrade in `_pending_trades` (direction is an enum with `.value`)."""
    return {
        "id": pid,
        "symbol": (symbol or "").upper(),
        "direction": (
            getattr(direction_enum, "value", None) or str(direction_enum)
        ).lower(),
        "shares": int(shares or 0),
        "pre_submit_at": pre_submit_dt.isoformat(),
    }


def test_mrsh_short_orphan_matches_pending_at_218s():
    # MRSH squeeze SHORT 12sh, pre_submit 13:46:36 -> orphan detected 13:50:14.
    pre = NOW - timedelta(seconds=218)
    rows = [_pending_row_like_reconciler("728a1bd3", "MRSH", _Dir.SHORT, 12, pre)]
    # IB orphan is short -> signed qty negative.
    assert match_pending_to_orphan("MRSH", -12, rows, NOW) == "728a1bd3"


def test_ceg_long_orphan_matches_pending_at_211s():
    # CEG gap_fade LONG 90sh, pre_submit 13:47:23 -> orphan detected 13:50:16.
    pre = NOW - timedelta(seconds=211)
    rows = [_pending_row_like_reconciler("e57af1cc", "CEG", _Dir.LONG, 90, pre)]
    assert match_pending_to_orphan("CEG", 90, rows, NOW) == "e57af1cc"


def test_wrong_direction_pending_does_not_match():
    # A long pending must NOT be claimed by a short IB orphan.
    pre = NOW - timedelta(seconds=218)
    rows = [_pending_row_like_reconciler("x", "MRSH", _Dir.LONG, 12, pre)]
    assert match_pending_to_orphan("MRSH", -12, rows, NOW) is None


def test_in_flight_pending_under_30s_is_not_claimed():
    # <30s old: a normal in-flight fill — leave it to confirm normally
    # (the v185 net handles the <60s window separately).
    pre = NOW - timedelta(seconds=15)
    rows = [_pending_row_like_reconciler("y", "CEG", _Dir.LONG, 90, pre)]
    assert match_pending_to_orphan("CEG", 90, rows, NOW) is None


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
