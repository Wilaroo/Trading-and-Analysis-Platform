"""v19.34.152 — position-memory disagreement + EOD-event persistence regression.

Pins the 2026-05-13 incident fix:
  1. `eod_auto_close` event is persisted on EVERY EOD path, even the
     early-return ones (so postmortem can distinguish "loop didn't
     run" from "loop ran but found empty open_trades").
  2. `check_position_memory_disagreement` fires a CRITICAL stream
     alarm when IB has open positions the bot's `_open_trades` dict
     doesn't know about AND that aren't a known swing trade.
  3. The alarm is dedup'd per-day-per-symbol to avoid stream flooding.
  4. Swing trades (close_at_eod=False) recorded in `bot_trades` are
     correctly excluded from the alarm.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _StubTrade:
    def __init__(self, symbol="X", shares=100, close_at_eod=True):
        self.id = f"t-{symbol}"
        self.symbol = symbol
        self.shares = shares
        self.remaining_shares = shares
        self.realized_pnl = 0.0
        self.close_at_eod = close_at_eod
        self.direction = SimpleNamespace(value="long")


class _StubBot:
    def __init__(self, trades=None, db=None):
        self._open_trades = {t.id: t for t in (trades or [])}
        self._db = db
        self._eod_close_enabled = True
        self._last_eod_check_date = None
        self._eod_close_executed_today = False
        self._eod_close_hour = 15
        self._eod_close_minute = 55
        self._broadcast_event = AsyncMock()


class _StubMongoFind:
    """Stub for the `db.bot_trades.find(...)` call used by the disagreement check."""
    def __init__(self, rows):
        self._rows = rows
    def __call__(self, *args, **kwargs):
        return self
    def __iter__(self):
        return iter(self._rows)


def _make_stub_db(swing_rows=None):
    """db.bot_trades.find({...}, projection) → returns swing_rows."""
    db = MagicMock()
    db.bot_trades.find = MagicMock(
        return_value=list(swing_rows or [])
    )
    db.bot_events.insert_one = MagicMock()
    return db


# ────────────────────────────────────────────────────────────────────
# 1. Position-memory disagreement classifier
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disagreement_fires_when_ib_has_positions_bot_doesnt(monkeypatch):
    """The 2026-05-13 incident: IB has 14 positions, bot has 0.
    Alarm MUST fire with all 14 listed."""
    from services.position_manager import PositionManager

    ib_positions_fixture = [
        {"symbol": "SMR", "position": 171},
        {"symbol": "ONON", "position": 117},
        {"symbol": "KMB", "position": -55},
    ]

    # No swing trades in Mongo → all 3 are TRUE disagreements.
    db = _make_stub_db(swing_rows=[])

    pm = PositionManager()
    bot = _StubBot(trades=[], db=db)

    monkeypatch.setattr(
        pm, "_ib_position_snapshot_safe",
        lambda: ib_positions_fixture,
    )

    emitted = []

    async def _capture_emit(event):
        emitted.append(event)

    with patch("services.sentcom_service.emit_stream_event", new=_capture_emit):
        await pm.check_position_memory_disagreement(bot)

    assert len(emitted) == 1
    e = emitted[0]
    assert e["event"] == "position_memory_disagreement"
    assert e["metadata"]["severity"] == "CRITICAL"
    assert set(e["metadata"]["symbols"]) == {"SMR", "ONON", "KMB"}


@pytest.mark.asyncio
async def test_disagreement_skips_known_swing_trades(monkeypatch):
    """Swing trades recorded in bot_trades with close_at_eod=False
    are NOT alarm-worthy — they're intentionally held overnight."""
    from services.position_manager import PositionManager

    ib_positions_fixture = [
        {"symbol": "SMR", "position": 171},   # unknown → alarm
        {"symbol": "ITT", "position": 132},   # in DB as swing → skip
    ]
    db = _make_stub_db(swing_rows=[
        {"symbol": "ITT", "close_at_eod": False},
    ])

    pm = PositionManager()
    bot = _StubBot(trades=[], db=db)

    monkeypatch.setattr(
        pm, "_ib_position_snapshot_safe",
        lambda: ib_positions_fixture,
    )

    emitted = []

    async def _capture_emit(event):
        emitted.append(event)

    with patch("services.sentcom_service.emit_stream_event", new=_capture_emit):
        await pm.check_position_memory_disagreement(bot)

    assert len(emitted) == 1
    assert emitted[0]["metadata"]["symbols"] == ["SMR"]  # ITT correctly suppressed


@pytest.mark.asyncio
async def test_disagreement_suppressed_when_bot_already_tracks(monkeypatch):
    """If `_open_trades` already has the symbol, no alarm."""
    from services.position_manager import PositionManager

    ib_positions_fixture = [{"symbol": "AAPL", "position": 100}]
    pm = PositionManager()
    bot = _StubBot(trades=[_StubTrade("AAPL")], db=_make_stub_db())

    monkeypatch.setattr(
        pm, "_ib_position_snapshot_safe",
        lambda: ib_positions_fixture,
    )

    emitted = []

    async def _capture_emit(event):
        emitted.append(event)

    with patch("services.sentcom_service.emit_stream_event", new=_capture_emit):
        await pm.check_position_memory_disagreement(bot)

    assert emitted == []


@pytest.mark.asyncio
async def test_disagreement_dedup_per_day(monkeypatch):
    """Alarm must NOT re-fire for the same symbol on the same day."""
    from services.position_manager import PositionManager

    ib_positions_fixture = [{"symbol": "SMR", "position": 100}]
    pm = PositionManager()
    bot = _StubBot(trades=[], db=_make_stub_db())

    monkeypatch.setattr(
        pm, "_ib_position_snapshot_safe",
        lambda: ib_positions_fixture,
    )

    emitted = []

    async def _capture_emit(event):
        emitted.append(event)

    with patch("services.sentcom_service.emit_stream_event", new=_capture_emit):
        await pm.check_position_memory_disagreement(bot)
        await pm.check_position_memory_disagreement(bot)
        await pm.check_position_memory_disagreement(bot)

    assert len(emitted) == 1  # only ONE alarm despite 3 calls


@pytest.mark.asyncio
async def test_disagreement_skips_zero_qty_ghosts(monkeypatch):
    """`_ib_position_snapshot_safe` already filters position==0; verify
    no false alarms when only ghosts are present."""
    from services.position_manager import PositionManager

    pm = PositionManager()
    bot = _StubBot(trades=[], db=_make_stub_db())

    # Ghosts already excluded by the snapshot helper — simulate empty list.
    monkeypatch.setattr(pm, "_ib_position_snapshot_safe", lambda: [])

    emitted = []

    async def _capture_emit(event):
        emitted.append(event)

    with patch("services.sentcom_service.emit_stream_event", new=_capture_emit):
        await pm.check_position_memory_disagreement(bot)

    assert emitted == []


@pytest.mark.asyncio
async def test_ib_snapshot_safe_excludes_zero_qty_rows():
    """Position rows with position==0 (intraday ghosts) MUST be excluded."""
    from services.position_manager import PositionManager

    pm = PositionManager()
    with patch("routers.ib._pushed_ib_data", {
        "positions": [
            {"symbol": "LIVE", "position": 100},
            {"symbol": "GHOST", "position": 0},
            {"symbol": "GHOST2", "position": 0.0},
        ]
    }):
        snap = pm._ib_position_snapshot_safe()
    assert len(snap) == 1
    assert snap[0]["symbol"] == "LIVE"


# ────────────────────────────────────────────────────────────────────
# 2. EOD event persistence on early-return paths
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eod_event_persisted_when_open_trades_empty():
    """When _open_trades is empty at 3:55 PM, the event MUST still be
    written to bot_events so postmortem can confirm the loop ran."""
    from services.position_manager import PositionManager

    pm = PositionManager()
    db = MagicMock()
    db.bot_events.insert_one = MagicMock()
    bot = _StubBot(trades=[], db=db)

    now_et = datetime(2026, 5, 13, 16, 0, 0)
    await pm._persist_eod_event(
        bot, "2026-05-13", now_et,
        closed=0, failed=[], total_pnl=0.0,
        is_half_day=False,
        early_exit_reason="open_trades_empty",
        ib_position_count=14,
    )
    assert db.bot_events.insert_one.called
    inserted = db.bot_events.insert_one.call_args[0][0]
    assert inserted["event_type"] == "eod_auto_close"
    assert inserted["positions_closed"] == 0
    assert inserted["early_exit_reason"] == "open_trades_empty"
    assert inserted["ib_position_count"] == 14


@pytest.mark.asyncio
async def test_eod_event_persisted_when_all_swing():
    from services.position_manager import PositionManager

    pm = PositionManager()
    db = MagicMock()
    db.bot_events.insert_one = MagicMock()
    bot = _StubBot(trades=[], db=db)

    now_et = datetime(2026, 5, 13, 16, 0, 0)
    await pm._persist_eod_event(
        bot, "2026-05-13", now_et,
        closed=0, failed=[], total_pnl=0.0,
        is_half_day=False,
        early_exit_reason="all_swing_or_position",
        ib_position_count=5,
    )
    inserted = db.bot_events.insert_one.call_args[0][0]
    assert inserted["early_exit_reason"] == "all_swing_or_position"


@pytest.mark.asyncio
async def test_eod_event_persistence_gracefully_handles_db_failure():
    """A DB write exception must NOT raise — the manage loop relies on
    `_persist_eod_event` being best-effort."""
    from services.position_manager import PositionManager

    pm = PositionManager()
    db = MagicMock()
    db.bot_events.insert_one = MagicMock(side_effect=Exception("mongo down"))
    bot = _StubBot(trades=[], db=db)

    # Should not raise.
    await pm._persist_eod_event(
        bot, "2026-05-13", datetime(2026, 5, 13, 16, 0, 0),
        closed=0, failed=[], total_pnl=0.0,
        is_half_day=False,
        early_exit_reason="open_trades_empty",
        ib_position_count=14,
    )
