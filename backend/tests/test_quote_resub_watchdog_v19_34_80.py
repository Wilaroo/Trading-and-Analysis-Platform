"""
v19.34.80 — Quote-Resubscribe Watchdog tests.

Validates the watchdog correctly:
  1. No-ops when nothing is stale (and clears prior attempts).
  2. Detects "RPC said success but pusher subs missing" mismatch,
     fires unsub+resub.
  3. After N failed cycles, escalates by writing a `state_integrity_events`
     row with severity=high.
  4. Recovers — when a previously-missing symbol shows up in the live
     subs set, watchdog state for that symbol is cleared.
  5. Pusher unreachable (subscriptions() returns None) → safely skips
     tick, no escalation, no attempt counter bump.
  6. Env-disable: QUOTE_RESUB_WATCHDOG_ENABLED=false → loop early-exits.
"""
import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest

from services.quote_resub_watchdog import (
    _State,
    _tick,
    quote_resub_watchdog_loop,
)


# ─────────────────────── Test scaffolding ───────────────────────


class _DummyPosMgr:
    def __init__(self, stale_set=None):
        self._stale_resub_set = stale_set or set()


class _DummyDb:
    """Captures inserts so tests can assert on what was written."""

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
    """Patch get_pusher_rpc_client. Returns the MagicMock for assertions."""
    rpc = MagicMock()
    rpc.is_configured.return_value = True
    rpc.subscriptions.return_value = set()
    rpc.subscribe_symbols.return_value = {"success": True}
    rpc.unsubscribe_symbols.return_value = {"success": True}
    with patch(
        "services.ib_pusher_rpc.get_pusher_rpc_client",
        return_value=rpc,
    ):
        yield rpc


# ─────────────────────── Test 1: empty stale set no-op + clears ────


def test_no_stale_set_clears_prior_attempts(mock_rpc):
    state = _State()
    # Seed a prior attempt that should be cleared.
    state.note_missing("ADBE")
    assert "ADBE" in state.snapshot()

    pm = _DummyPosMgr(stale_set=set())
    summary = asyncio.run(_tick(state, pm, _DummyDb()))

    assert summary["checked"] == 0
    assert summary["cleared"] == 1
    assert "ADBE" not in state.snapshot()


# ─────────────────────── Test 2: missing → unsub+resub ─────────────


def test_missing_from_pusher_subs_triggers_unsub_resub(mock_rpc):
    # Position manager says GM is stale. Pusher claims subs = {AAPL}
    # (GM is missing). Expect unsub+resub for GM.
    state = _State()
    pm = _DummyPosMgr(stale_set={"GM"})
    mock_rpc.subscriptions.return_value = {"AAPL"}

    summary = asyncio.run(_tick(state, pm, _DummyDb()))

    assert summary["checked"] == 1
    assert summary["missing"] == 1
    assert summary["resubscribed"] == 1
    assert summary["escalated"] == 0
    # Verify the actual RPC calls.
    mock_rpc.unsubscribe_symbols.assert_called_once_with({"GM"})
    mock_rpc.subscribe_symbols.assert_called_once_with({"GM"})
    assert state.snapshot()["GM"]["attempts"] == 1


# ─────────────────────── Test 3: 3 failed cycles → escalation ──────


def test_escalates_after_three_failed_cycles(mock_rpc):
    state = _State()
    pm = _DummyPosMgr(stale_set={"LIN"})
    mock_rpc.subscriptions.return_value = set()  # always missing
    db = _DummyDb()

    # Set the env so the default 3 applies even if a prior test mutated.
    with patch.dict(os.environ, {"QUOTE_RESUB_WATCHDOG_ESCALATE_AFTER": "3"}):
        for _ in range(3):
            asyncio.run(_tick(state, pm, db))

    # Only the third tick should escalate (attempts reaches threshold).
    assert state.snapshot()["LIN"]["attempts"] == 3
    escalations = [r for (coll, r) in db.inserts
                   if coll == "quote_resub_watchdog_events"]
    assert len(escalations) == 1
    e = escalations[0]
    assert e["symbol"] == "LIN"
    assert e["attempts"] == 3
    assert e["severity"] == "high"
    assert e["event"] == "quote_resub_watchdog_escalated"


# ─────────────────────── Test 4: recovery clears state ─────────────


def test_recovery_clears_watchdog_state(mock_rpc):
    state = _State()
    pm = _DummyPosMgr(stale_set={"NVDA"})
    db = _DummyDb()

    # Tick 1: missing → counter bumps.
    mock_rpc.subscriptions.return_value = set()
    asyncio.run(_tick(state, pm, db))
    assert state.snapshot()["NVDA"]["attempts"] == 1

    # Tick 2: NVDA is now in the live set AND still in stale_set
    # (manage loop hasn't cleared it yet). Watchdog should clear state.
    mock_rpc.subscriptions.return_value = {"NVDA"}
    summary = asyncio.run(_tick(state, pm, db))
    assert summary["cleared"] == 1
    assert "NVDA" not in state.snapshot()


# ─────────────────────── Test 5: pusher unreachable, safe skip ─────


def test_pusher_unreachable_safe_skip(mock_rpc):
    state = _State()
    pm = _DummyPosMgr(stale_set={"SPY"})
    mock_rpc.subscriptions.return_value = None  # pusher down

    summary = asyncio.run(_tick(state, pm, _DummyDb()))

    assert summary["missing"] == 0
    assert summary["resubscribed"] == 0
    # No attempt counter increment when pusher is down.
    assert state.snapshot() == {}


# ─────────────────────── Test 6: env disable ───────────────────────


def test_env_disable_exits_immediately():
    with patch.dict(os.environ, {"QUOTE_RESUB_WATCHDOG_ENABLED": "false"}):
        # Loop should return without spawning any work. We pass an
        # always-True _running flag — if the loop honored env it
        # returns instantly.
        bot = MagicMock()
        bot._running = True
        # If env is honored, this completes instantly. If it isn't,
        # the loop would sleep for the interval and block the test.
        asyncio.run(asyncio.wait_for(
            quote_resub_watchdog_loop(bot), timeout=2.0,
        ))
