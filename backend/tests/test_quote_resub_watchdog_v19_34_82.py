"""
v19.34.82 — Quote-Resubscribe Watchdog tests (REDESIGNED).

v82 replaces v80's reliance on position_manager._stale_resub_set with
independent source-of-truth comparison:
  * bot._open_trades symbols vs /rpc/subscriptions
  * /rpc/quote-snapshot per tracked symbol (catches pusher split-brain)
"""
import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest

from services.quote_resub_watchdog import (
    _State,
    _tick,
    _force_resub,
    quote_resub_watchdog_loop,
)


class _DummyTrade:
    def __init__(self, symbol):
        self.symbol = symbol


class _DummyBot:
    def __init__(self, symbols=None):
        self._open_trades = {
            f"trade-{i}": _DummyTrade(s)
            for i, s in enumerate(symbols or [])
        }
        self.db = _DummyDb()


class _DummyDb:
    def __init__(self):
        self.inserts = []

    def __getitem__(self, name):
        parent = self
        class _Coll:
            def insert_one(self, doc):
                parent.inserts.append((name, doc))
                return MagicMock()
        return _Coll()


@pytest.fixture
def mock_rpc():
    rpc = MagicMock()
    rpc.is_configured.return_value = True
    rpc.subscriptions.return_value = set()
    rpc.quote_snapshot.return_value = {"success": True, "quote": {"last": 100.0}}
    rpc.subscribe_symbols.return_value = {"success": True, "added": ["X"]}
    rpc.unsubscribe_symbols.return_value = {"success": True, "removed": ["X"]}
    with patch(
        "services.ib_pusher_rpc.get_pusher_rpc_client",
        return_value=rpc,
    ):
        yield rpc


def test_empty_open_trades_clears_prior_state(mock_rpc):
    state = _State()
    state.note_missing("PRIOR")
    bot = _DummyBot(symbols=[])
    summary = asyncio.run(_tick(state, bot, bot.db))
    assert summary["checked"] == 0
    assert summary["cleared"] == 1
    assert "PRIOR" not in state.snapshot()


def test_missing_from_subs_triggers_unsub_resub(mock_rpc):
    state = _State()
    bot = _DummyBot(symbols=["UAL"])
    mock_rpc.subscriptions.return_value = {"AAPL"}
    summary = asyncio.run(_tick(state, bot, bot.db))
    assert summary["checked"] == 1
    assert summary["missing_from_subs"] == 1
    assert summary["snapshot_failed"] == 0
    assert summary["resubscribed"] == 1
    assert summary["escalated"] == 0
    mock_rpc.unsubscribe_symbols.assert_called_once_with({"UAL"})
    mock_rpc.subscribe_symbols.assert_called_once_with({"UAL"})
    assert state.snapshot()["UAL"]["attempts"] == 1


def test_snapshot_failed_triggers_unsub_resub(mock_rpc):
    state = _State()
    bot = _DummyBot(symbols=["COR"])
    mock_rpc.subscriptions.return_value = {"COR"}
    mock_rpc.quote_snapshot.return_value = {
        "success": False, "symbol": "COR", "error": "symbol_not_subscribed",
    }
    summary = asyncio.run(_tick(state, bot, bot.db))
    assert summary["checked"] == 1
    assert summary["missing_from_subs"] == 0
    assert summary["snapshot_failed"] == 1
    assert summary["resubscribed"] == 1
    mock_rpc.unsubscribe_symbols.assert_called_once_with({"COR"})
    mock_rpc.subscribe_symbols.assert_called_once_with({"COR"})


def test_escalates_after_three_failed_cycles(mock_rpc):
    state = _State()
    bot = _DummyBot(symbols=["LIN"])
    mock_rpc.subscriptions.return_value = set()
    db = bot.db
    with patch.dict(os.environ, {"QUOTE_RESUB_WATCHDOG_ESCALATE_AFTER": "3"}):
        for _ in range(3):
            asyncio.run(_tick(state, bot, db))
    assert state.snapshot()["LIN"]["attempts"] == 3
    escalations = [r for (coll, r) in db.inserts
                   if coll == "quote_resub_watchdog_events"]
    assert len(escalations) == 1
    e = escalations[0]
    assert e["symbol"] == "LIN"
    assert e["attempts"] == 3
    assert e["severity"] == "high"
    assert e["divergence_kind"] == "missing_from_subs"
    assert e["version"] == "v19.34.82"


def test_recovery_clears_watchdog_state(mock_rpc):
    state = _State()
    bot = _DummyBot(symbols=["NVDA"])
    db = bot.db
    mock_rpc.subscriptions.return_value = set()
    asyncio.run(_tick(state, bot, db))
    assert state.snapshot()["NVDA"]["attempts"] == 1
    mock_rpc.subscriptions.return_value = {"NVDA"}
    mock_rpc.quote_snapshot.return_value = {"success": True, "quote": {"last": 1000.0}}
    summary = asyncio.run(_tick(state, bot, db))
    assert summary["cleared"] == 1
    assert "NVDA" not in state.snapshot()


def test_pusher_unreachable_safe_skip(mock_rpc):
    state = _State()
    bot = _DummyBot(symbols=["SPY"])
    mock_rpc.subscriptions.return_value = None
    summary = asyncio.run(_tick(state, bot, bot.db))
    assert summary["missing_from_subs"] == 0
    assert summary["snapshot_failed"] == 0
    assert summary["resubscribed"] == 0
    assert state.snapshot() == {}


def test_force_resub_handles_rpc_exception(mock_rpc):
    mock_rpc.unsubscribe_symbols.side_effect = RuntimeError("network down")
    ok = asyncio.run(_force_resub(mock_rpc, "TEST"))
    assert ok is False


def test_env_disable_exits_immediately():
    with patch.dict(os.environ, {"QUOTE_RESUB_WATCHDOG_ENABLED": "false"}):
        bot = MagicMock()
        bot._running = True
        asyncio.run(asyncio.wait_for(
            quote_resub_watchdog_loop(bot), timeout=2.0,
        ))
