"""
v19.34.227 — Open-position quote-PIN tests for the quote-resub watchdog.

Validates the new behavior that proactively pins every held position into the
pusher quote universe so an open name never goes mark-less (root cause of the
v226 CRM current_price=0 → fake -$18,897 kill-switch trip), plus that the
watchdog no longer early-returns when there are positions to pin even if the
stale set is empty.
"""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from services.quote_resub_watchdog import _State, _tick


class _DummyPosMgr:
    def __init__(self, stale_set=None):
        self._stale_resub_set = stale_set or set()


@pytest.fixture
def mock_rpc():
    rpc = MagicMock()
    rpc.is_configured.return_value = True
    rpc.subscriptions.return_value = set()
    rpc.subscribe_symbols.return_value = {"success": True}
    rpc.unsubscribe_symbols.return_value = {"success": True}
    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=rpc):
        yield rpc


def test_held_position_missing_gets_pinned(mock_rpc):
    """CRM is an open position absent from the pusher subs → it must be
    subscribed (pinned) even though it's NOT in the stale set."""
    state = _State()
    pm = _DummyPosMgr(stale_set=set())          # nothing stale
    mock_rpc.subscriptions.return_value = {"AAPL"}  # CRM missing

    summary = asyncio.run(_tick(state, pm, None,
                                open_position_symbols={"CRM"}))

    assert summary["pinned"] == 1
    mock_rpc.subscribe_symbols.assert_called_once_with({"CRM"})


def test_held_position_already_subscribed_not_pinned(mock_rpc):
    state = _State()
    pm = _DummyPosMgr(stale_set=set())
    mock_rpc.subscriptions.return_value = {"CRM", "AAPL"}  # already present

    summary = asyncio.run(_tick(state, pm, None,
                                open_position_symbols={"CRM"}))

    assert summary["pinned"] == 0
    mock_rpc.subscribe_symbols.assert_not_called()


def test_no_stale_but_open_positions_does_not_early_return(mock_rpc):
    """With an empty stale set but live positions, the tick must still run
    (fetch pusher subs + pin) rather than short-circuit."""
    state = _State()
    pm = _DummyPosMgr(stale_set=set())
    mock_rpc.subscriptions.return_value = set()

    summary = asyncio.run(_tick(state, pm, None,
                                open_position_symbols={"CRM", "NVDA"}))

    assert summary["pinned"] == 2
    mock_rpc.subscriptions.assert_called()  # proves it didn't early-return


def test_nothing_to_do_still_early_returns(mock_rpc):
    """No stale set AND no open positions → original early-return path."""
    state = _State()
    state.note_missing("OLD")
    pm = _DummyPosMgr(stale_set=set())

    summary = asyncio.run(_tick(state, pm, None, open_position_symbols=set()))

    assert summary["checked"] == 0
    assert summary["cleared"] == 1
    mock_rpc.subscriptions.assert_not_called()


def test_stale_and_pin_combined(mock_rpc):
    """A stale name (GM) is force-resubbed AND a held position (CRM) is
    pinned in the same tick."""
    state = _State()
    pm = _DummyPosMgr(stale_set={"GM"})
    mock_rpc.subscriptions.return_value = {"AAPL"}  # both GM and CRM missing

    summary = asyncio.run(_tick(state, pm, None,
                                open_position_symbols={"CRM"}))

    assert summary["missing"] == 1        # GM
    assert summary["resubscribed"] == 1   # GM unsub+resub
    assert summary["pinned"] == 1         # CRM pinned
    mock_rpc.subscribe_symbols.assert_any_call({"CRM"})
