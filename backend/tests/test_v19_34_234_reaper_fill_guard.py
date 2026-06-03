"""
v19.34.234 — reaper fill-race guard tests.

Verifies `_reaper_should_skip_filled`: the pending-reaper must NOT reap a
stale `pending` row whose symbol still shows a live IB position the bot isn't
tracking as open (the unattributed-fill race that orphaned SOXX/LRCX/ALAB/
ASTS on 2026-06-03). It MUST still reap genuinely dead pendings.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.trading_bot_service import _reaper_should_skip_filled  # noqa: E402


def test_skip_when_ib_holds_and_bot_not_open():
    # IB has SOXX, bot has no open SOXX trade -> likely unattributed fill -> SKIP
    assert _reaper_should_skip_filled("SOXX", {"SOXX"}, set()) is True


def test_reap_when_no_ib_position():
    # Genuinely dead pending -> IB flat on the symbol -> REAP as normal
    assert _reaper_should_skip_filled("SOXX", set(), set()) is False


def test_reap_when_bot_already_tracks_open():
    # IB holds it AND the bot already has an open trade for it -> that open
    # trade owns the shares; this pending is a separate dead row -> REAP.
    assert _reaper_should_skip_filled("SOXX", {"SOXX"}, {"SOXX"}) is False


def test_case_insensitive_and_blank():
    assert _reaper_should_skip_filled("soxx", {"SOXX"}, set()) is True
    assert _reaper_should_skip_filled("", {"SOXX"}, set()) is False
    assert _reaper_should_skip_filled(None, {"SOXX"}, set()) is False


def test_other_symbol_position_does_not_protect():
    # IB holds LRCX, the stale pending is for NXPI -> NXPI must still reap.
    assert _reaper_should_skip_filled("NXPI", {"LRCX"}, set()) is False


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
