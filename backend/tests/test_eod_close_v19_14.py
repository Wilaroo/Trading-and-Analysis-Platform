"""
v19.14 — EOD Close-stage hardening (2026-04-30).

Pins the 6 fixes shipped to `position_manager.check_eod_close`:

P0 #1 — close_trade returns a BOOL, not a dict. Pre-fix the loop
        called `result.get('success')` which raises AttributeError on
        a bool — silently failing every EOD close.
P0 #2 — closes run in PARALLEL via asyncio.gather (was serial; risked
        spilling past 4:00 PM bell with 25 open positions).
P0 #3 — `_eod_close_executed_today` only sets True when ALL closes
        succeed. Partial failure → leave False so manage-loop retries.
P0 #4 — Loud ERROR alarm + WS notify if positions are still open at/
        after market_close_hour (4:00 PM ET; 1:00 PM on half-days).
P1 #5 — Half-trading-day detection via env `EOD_HALF_DAY_TODAY=true`
        flips close window to 12:55 PM ET.
P1 #6 — WS-broadcast EOD start + completion events.

Plus the v19.14 default-time tightening:
  - Default close minute moved from :57 → :55 ET (extra 2 min cushion
    before 4:00 PM bell). Only applies to trades flagged
    `close_at_eod=True` (intraday/scalp/day); swing & position trades
    are explicitly held overnight.

Tests use direct-function-call style + minimal fakes so they don't
drag in the trading_bot_service / IB / pusher dependency tree.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


# --------------------------------------------------------------------------
# Minimal fakes — keep these small so a future BotTrade schema change
# doesn't require updating six tests.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Direction:
    value: str

LONG = _Direction("long")
SHORT = _Direction("short")


@dataclass
class _Trade:
    id: str = "T1"
    symbol: str = "AAPL"
    direction: Any = LONG
    fill_price: float = 100.0
    current_price: float = 100.0
    shares: int = 100
    remaining_shares: int = 100
    realized_pnl: float = 0.0
    close_at_eod: bool = True


@dataclass
class _Bot:
    """Minimal stand-in for TradingBotService that check_eod_close reads."""
    _eod_close_enabled: bool = True
    _eod_close_hour: int = 15
    _eod_close_minute: int = 55  # v19.14 default
    _eod_close_executed_today: bool = False
    _last_eod_check_date: Optional[str] = None
    _open_trades: Dict[str, _Trade] = field(default_factory=dict)
    _db: Any = None
    broadcast_calls: List[Dict] = field(default_factory=list)
    closed_calls: List[Dict] = field(default_factory=list)

    async def _broadcast_event(self, event: Dict):
        self.broadcast_calls.append(event)


# --------------------------------------------------------------------------
# Default time pin — v19.14 moved EOD from 3:57 → 3:55 PM
# --------------------------------------------------------------------------

def test_default_eod_close_minute_is_55():
    """v19.14 — default EOD close window is 3:55 PM ET (2-min earlier
    than the prior 3:57 default) so intraday closes complete a full
    5 min before the 4:00 PM bell.
    """
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "services",
                     "trading_bot_service.py")
    ).read()
    # Pin the new default; stop a future contributor from silently
    # nudging it back to :57 or beyond.
    assert "self._eod_close_minute = 55" in src, (
        "Default EOD close minute regressed away from 3:55 PM ET"
    )
    assert "self._eod_close_minute = 57" not in src, (
        "Old 3:57 default reappeared in trading_bot_service.py"
    )


def test_default_eod_close_hour_is_15():
    """Defensive — the hour shouldn't drift either."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "services",
                     "trading_bot_service.py")
    ).read()
    assert "self._eod_close_hour = 15" in src


def test_persistence_default_eod_close_minute_is_55():
    """v19.14 — bot_persistence's restore default also moved to :55.

    If a bot starts before any `eod_config` doc has been written, this
    is the value used; we don't want it to drift back to :57.
    """
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "services",
                     "bot_persistence.py")
    ).read()
    assert 'eod_config.get("close_minute", 55)' in src
    assert 'eod_config.get("close_minute", 57)' not in src


# --------------------------------------------------------------------------
# Helper — patches in a stub close_trade that returns the requested bool
# --------------------------------------------------------------------------

async def _run_check_eod_close(
    *,
    bot: _Bot,
    pm,
    fake_now_et: datetime,
    close_outcomes: Dict[str, bool],
):
    """Run check_eod_close with a stubbed close_trade.

    `close_outcomes` maps trade_id → True (success) / False (failure).
    """
    async def _stub_close(trade_id, _bot, reason="manual"):
        bot.closed_calls.append({"trade_id": trade_id, "reason": reason})
        return close_outcomes.get(trade_id, True)

    with patch.object(pm, "close_trade", _stub_close):
        # patch datetime inside position_manager so check_eod_close
        # sees `fake_now_et` whether it asks for ET or UTC. The
        # production function only calls `datetime.now(...)`, never
        # constructs new datetimes, so this is sufficient.
        with patch("services.position_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now_et
            await pm.check_eod_close(bot)


# --------------------------------------------------------------------------
# P0 #1 — close_trade returns a BOOL, not a dict
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_treats_close_trade_return_as_bool():
    """If close_trade returns True, we count success. If False, we
    count failure. We must NOT call `.get('success')` on the bool —
    that raised AttributeError pre-v19.14 silently failing every close.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    # Two intraday trades, both succeed.
    trades = {
        "T1": _Trade(id="T1", symbol="AAPL", close_at_eod=True),
        "T2": _Trade(id="T2", symbol="MSFT", close_at_eod=True),
    }
    bot = _Bot(_open_trades=trades)

    fake_now = datetime(2026, 5, 5, 15, 56)  # 3:56 PM Tuesday — past 3:55 trigger
    # Stub ZoneInfo conversion: datetime.now(ZoneInfo) → fake_now
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True, "T2": True},
    )

    assert bot._eod_close_executed_today is True, (
        "All closes succeeded — flag must flip True"
    )
    assert len(bot.closed_calls) == 2
    # P1 #6 — both start + complete WS notifies fired
    types = [e["type"] for e in bot.broadcast_calls]
    assert "eod_close_started" in types
    assert "eod_close_completed" in types
    completed = next(
        e for e in bot.broadcast_calls if e["type"] == "eod_close_completed"
    )
    assert completed["closed"] == 2
    assert completed["failed"] == 0
    assert completed["fully_done"] is True


# --------------------------------------------------------------------------
# P0 #3 — partial failure leaves _eod_close_executed_today=False so
#         manage loop retries on the next tick
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_partial_failure_keeps_flag_false_for_retry():
    """If 1 of 2 closes fail, the executed_today flag must remain False
    so the next manage-loop tick (~1-2s later) retries the failed
    symbol. Pre-v19.14 the flag flipped True regardless → broker
    carried the position overnight while books said it was closed."""
    from services.position_manager import PositionManager
    pm = PositionManager()

    trades = {
        "T1": _Trade(id="T1", symbol="AAPL", close_at_eod=True),
        "T2": _Trade(id="T2", symbol="MSFT", close_at_eod=True),
    }
    bot = _Bot(_open_trades=trades)

    fake_now = datetime(2026, 5, 5, 15, 56)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True, "T2": False},
    )

    assert bot._eod_close_executed_today is False, (
        "Partial failure must keep executed_today=False so next tick "
        "retries the failed close"
    )
    completed = next(
        e for e in bot.broadcast_calls if e["type"] == "eod_close_completed"
    )
    assert completed["failed"] == 1
    assert completed["closed"] == 1
    assert "MSFT" in completed["failed_symbols"]
    assert completed["fully_done"] is False


# --------------------------------------------------------------------------
# P0 #2 — closes run in parallel via asyncio.gather
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_closes_run_in_parallel_not_serial():
    """25 open positions × 2s/close serial = ~50s — risks spilling past
    4:00 PM bell. Parallelised, total wall-time ≈ single-trade latency
    (~2s). This test pins the contract: 5 closes that each sleep 200ms
    must complete in ~200ms total, not 1000ms.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    trades = {
        f"T{i}": _Trade(id=f"T{i}", symbol=f"S{i}", close_at_eod=True)
        for i in range(5)
    }
    bot = _Bot(_open_trades=trades)

    async def _slow_close(trade_id, _bot, reason="manual"):
        bot.closed_calls.append({"trade_id": trade_id, "reason": reason})
        await asyncio.sleep(0.2)
        return True

    fake_now = datetime(2026, 5, 5, 15, 56)
    with patch.object(pm, "close_trade", _slow_close):
        with patch("services.position_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            t0 = asyncio.get_event_loop().time()
            await pm.check_eod_close(bot)
            elapsed = asyncio.get_event_loop().time() - t0

    assert len(bot.closed_calls) == 5
    # Parallel: ~0.2s. Serial would be ~1.0s. Generous bound at 0.6s.
    assert elapsed < 0.6, (
        f"check_eod_close ran serially (took {elapsed:.2f}s for 5 × 200ms); "
        "must use asyncio.gather for parallel close"
    )


# --------------------------------------------------------------------------
# P0 #4 — alarm if positions still open past market close
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_alarms_if_positions_open_past_4pm():
    """Past 4:00 PM with positions still locally open is an EMERGENCY
    (IB may have auto-flat'd or operator may be carrying overnight).
    Must surface loudly via log + WS notify, not silently skip.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={"T1": _Trade(id="T1", symbol="AAPL")})
    # We pre-set executed_today=False so we can exercise the alarm
    # path independently of "did closes run".
    bot._eod_close_executed_today = False

    fake_now = datetime(2026, 5, 5, 16, 5)  # 4:05 PM — past close
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now, close_outcomes={},
    )

    types = [e["type"] for e in bot.broadcast_calls]
    assert "eod_after_close_alarm" in types, (
        "Past-close alarm must broadcast via WS so V5 HUD can render it"
    )
    alarm = next(
        e for e in bot.broadcast_calls if e["type"] == "eod_after_close_alarm"
    )
    assert alarm["open_positions"] == 1
    assert "et_clock" in alarm


# --------------------------------------------------------------------------
# P1 #5 — half-day detection
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_half_day_close_window_at_1255():
    """When `EOD_HALF_DAY_TODAY=true`, the close window flips to 12:55 PM
    ET (5 min before the 1:00 PM half-day close). Default 3:55 path
    must NOT fire on a half-day at 12:56 PM.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={"T1": _Trade(id="T1", close_at_eod=True)})

    fake_now = datetime(2026, 5, 5, 12, 56)  # 12:56 PM Tuesday
    with patch.dict(os.environ, {"EOD_HALF_DAY_TODAY": "true"}):
        await _run_check_eod_close(
            bot=bot, pm=pm, fake_now_et=fake_now,
            close_outcomes={"T1": True},
        )

    assert len(bot.closed_calls) == 1
    started = next(
        e for e in bot.broadcast_calls if e["type"] == "eod_close_started"
    )
    assert started["is_half_day"] is True
    assert started["eod_window_et"] == "12:55"


@pytest.mark.asyncio
async def test_eod_half_day_does_not_fire_before_window():
    """At 12:30 PM on a half-day, do NOT close. We're still inside RTH."""
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={"T1": _Trade(id="T1", close_at_eod=True)})
    fake_now = datetime(2026, 5, 5, 12, 30)
    with patch.dict(os.environ, {"EOD_HALF_DAY_TODAY": "true"}):
        await _run_check_eod_close(
            bot=bot, pm=pm, fake_now_et=fake_now,
            close_outcomes={"T1": True},
        )

    assert len(bot.closed_calls) == 0, (
        "Half-day window is 12:55 — must not fire at 12:30"
    )


# --------------------------------------------------------------------------
# Intraday-only — swing/position trades are skipped
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_only_closes_intraday_trades():
    """Operator's explicit requirement: EOD close ONLY applies to
    intraday trades (`close_at_eod=True`). Swing and position trades
    are explicitly held overnight.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={
        "T1": _Trade(id="T1", symbol="AAPL", close_at_eod=True),
        "T2": _Trade(id="T2", symbol="NVDA", close_at_eod=False),  # swing
        "T3": _Trade(id="T3", symbol="MSFT", close_at_eod=True),
    })

    fake_now = datetime(2026, 5, 5, 15, 56)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True, "T3": True},
    )

    closed_ids = {c["trade_id"] for c in bot.closed_calls}
    assert closed_ids == {"T1", "T3"}, (
        f"EOD must skip swing trade T2; closed: {closed_ids}"
    )
    started = next(
        e for e in bot.broadcast_calls if e["type"] == "eod_close_started"
    )
    assert started["positions_to_close"] == 2


@pytest.mark.asyncio
async def test_eod_skips_when_all_positions_are_swing():
    """If every open position is swing/position (close_at_eod=False),
    we should NOT broadcast eod_close_started; just mark executed and
    return early.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={
        "T1": _Trade(id="T1", symbol="AAPL", close_at_eod=False),
        "T2": _Trade(id="T2", symbol="NVDA", close_at_eod=False),
    })

    fake_now = datetime(2026, 5, 5, 15, 56)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now, close_outcomes={},
    )

    assert bot._eod_close_executed_today is True
    assert len(bot.closed_calls) == 0
    types = [e["type"] for e in bot.broadcast_calls]
    assert "eod_close_started" not in types
    assert "eod_close_completed" not in types


# --------------------------------------------------------------------------
# Non-trigger paths (fast-fail returns)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eod_does_not_fire_before_trigger_minute():
    """At 3:54 PM ET, we are still 1 min before the 3:55 trigger.
    Must not start any closes.
    """
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={"T1": _Trade(id="T1", close_at_eod=True)})
    fake_now = datetime(2026, 5, 5, 15, 54)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True},
    )
    assert len(bot.closed_calls) == 0


@pytest.mark.asyncio
async def test_eod_disabled_short_circuits():
    """Operator can globally disable EOD via `_eod_close_enabled=False`."""
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(
        _open_trades={"T1": _Trade(id="T1", close_at_eod=True)},
        _eod_close_enabled=False,
    )
    fake_now = datetime(2026, 5, 5, 15, 56)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True},
    )
    assert len(bot.closed_calls) == 0


@pytest.mark.asyncio
async def test_eod_does_not_fire_on_weekend():
    """Saturday at 3:56 PM — must not fire (weekday() >= 5)."""
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(_open_trades={"T1": _Trade(id="T1", close_at_eod=True)})
    saturday = datetime(2026, 5, 9, 15, 56)  # Saturday
    assert saturday.weekday() == 5
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=saturday,
        close_outcomes={"T1": True},
    )
    assert len(bot.closed_calls) == 0


@pytest.mark.asyncio
async def test_eod_does_not_redo_closes_on_same_day():
    """Once executed_today is True, subsequent ticks short-circuit."""
    from services.position_manager import PositionManager
    pm = PositionManager()

    bot = _Bot(
        _open_trades={"T1": _Trade(id="T1", close_at_eod=True)},
        _eod_close_executed_today=True,
        _last_eod_check_date="2026-05-05",
    )
    fake_now = datetime(2026, 5, 5, 15, 58)
    await _run_check_eod_close(
        bot=bot, pm=pm, fake_now_et=fake_now,
        close_outcomes={"T1": True},
    )
    assert len(bot.closed_calls) == 0
