"""
v19.34.191 regression tests — EOD supervisor crash hardening.

Covers:
  BUG 1 — PyMongo `bool(Database)` truthiness crash. We use a sentinel object
          whose __bool__ raises (mirroring PyMongo Database/Collection) to
          prove the *resolution expressions* the patch introduced never coerce
          the object to bool.
  BUG 2 — restored `TradingBotService._broadcast_event` shim correctly maps the
          legacy {"type", "timestamp", ...} payload onto emit_stream_event.

These are pure-logic tests — no IB / hardware bindings required.
"""
import asyncio

import pytest

from services.trading_bot_service import TradingBotService


class _NoBoolDB:
    """Mimics a PyMongo Database: raises if anyone calls bool()."""

    def __bool__(self):  # pragma: no cover - must never be hit
        raise NotImplementedError(
            "Database objects do not implement truth value testing"
        )


# ---------------------------------------------------------------------------
# BUG 1 — truthiness-safe resolution patterns
# ---------------------------------------------------------------------------
def test_or_pattern_resolution_never_calls_bool():
    """The `getattr(... ) if ... is not None else ...` ternary must resolve a
    Database-like object without invoking bool()."""
    class _Bot:
        _db = _NoBoolDB()
        db = None

    bot = _Bot()
    # mirrors the patched expression in position_manager / opportunity_evaluator
    db = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None
          else getattr(bot, "db", None))
    assert db is bot._db  # resolved without NotImplementedError


def test_if_is_not_none_pattern_never_calls_bool():
    """`if bot._db is not None:` must not raise on a no-bool Database."""
    class _Bot:
        _db = _NoBoolDB()

    bot = _Bot()
    hit = False
    if bot._db is not None:
        hit = True
    assert hit is True


def test_fallback_to_secondary_db_when_primary_none():
    class _Bot:
        _db = None
        db = _NoBoolDB()

    bot = _Bot()
    db = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None
          else getattr(bot, "db", None))
    assert db is bot.db


# ---------------------------------------------------------------------------
# BUG 2 — _broadcast_event shim mapping
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_broadcast_event_exists_and_async():
    import inspect
    assert hasattr(TradingBotService, "_broadcast_event")
    assert inspect.iscoroutinefunction(TradingBotService._broadcast_event)


def test_broadcast_event_maps_legacy_payload(monkeypatch):
    captured = {}

    async def _fake_emit(payload):
        captured.update(payload)
        return True

    import services.sentcom_service as scs
    monkeypatch.setattr(scs, "emit_stream_event", _fake_emit)

    bot = TradingBotService.__new__(TradingBotService)  # no __init__ side effects
    _run(bot._broadcast_event({
        "type": "eod_close_completed",
        "timestamp": "2026-02-01T20:00:00+00:00",
        "closed": 3,
        "failed": 0,
    }))

    assert captured.get("event") == "eod_close_completed"
    assert captured.get("kind") == "system"           # routine lifecycle
    assert "closed=3" in captured.get("text", "")     # auto-humanized line
    # extra fields preserved in metadata; control keys stripped
    assert captured["metadata"].get("closed") == 3
    assert "type" not in captured["metadata"]


def test_broadcast_event_critical_severity_is_alert(monkeypatch):
    captured = {}

    async def _fake_emit(payload):
        captured.update(payload)
        return True

    import services.sentcom_service as scs
    monkeypatch.setattr(scs, "emit_stream_event", _fake_emit)

    bot = TradingBotService.__new__(TradingBotService)
    _run(bot._broadcast_event({
        "type": "eod_after_close_alarm",
        "open_positions": 2,
        "severity": "CRITICAL",
    }))
    assert captured.get("kind") == "alert"            # alarm/critical → alert lane
    assert "open positions=2" in captured.get("text", "")


def test_broadcast_event_never_raises_on_bad_input():
    bot = TradingBotService.__new__(TradingBotService)
    # non-dict input must be swallowed, not raised
    _run(bot._broadcast_event(None))
    _run(bot._broadcast_event("not-a-dict"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
