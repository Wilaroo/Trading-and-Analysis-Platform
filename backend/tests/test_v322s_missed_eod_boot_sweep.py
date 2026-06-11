"""
test_v322s_missed_eod_boot_sweep.py — regression tests for the ACMR
2026-05-29 weekend-carry fix.

Findings the fix closes:
  1. A close_at_eod position filled 15:38 ET Friday; the backend went DOWN
     before the 15:45 EOD pass (zero heartbeats, no eod_auto_close event)
     → the position carried the WEEKEND on its GTC stop and gapped through
     it at Monday's open. Every in-session guard requires the process to
     be running in the window.
     → v322s: boot-time missed-EOD sweep — tracked open close_at_eod
       trades whose fill date is a previous ET session get flattened at
       boot (market open) or at the next open (premarket/weekend boots).
  2. BotTrade.created_at defaulted to "" — rows constructed without it
     persisted an empty string and were invisible to every date-windowed
     query (the e11450ca forensics miss).
     → v322s: default_factory now-ISO + repair_created_at_backfill.py.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.position_manager import PositionManager  # noqa: E402

ET = ZoneInfo("America/New_York")

# 2026-06-09 is a Tuesday; 2026-06-08 (Monday) is the "previous session".
RTH_NOW = datetime(2026, 6, 9, 10, 0, tzinfo=ET)
PREMARKET_NOW = datetime(2026, 6, 9, 8, 0, tzinfo=ET)
SATURDAY_NOW = datetime(2026, 6, 13, 11, 0, tzinfo=ET)
YESTERDAY_FILL = "2026-06-08T18:30:00+00:00"   # Mon 14:30 ET
TODAY_FILL = "2026-06-09T13:45:00+00:00"       # Tue 09:45 ET


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _trade(tid="t1", style="intraday", status="open", executed=YESTERDAY_FILL,
           symbol="ACMR"):
    return SimpleNamespace(id=tid, symbol=symbol, status=status,
                           trade_style=style, executed_at=executed)


def _fakes(trades, close_ok=True):
    """(fake PositionManager self, fake bot) with a close_trade recorder."""
    closes = []

    async def close_trade(tid, bot, reason=None):
        closes.append((tid, reason))
        return close_ok

    fs = SimpleNamespace(close_trade=close_trade, closes=closes)
    bot = SimpleNamespace(_open_trades={t.id: t for t in trades}, _db=None)
    return fs, bot


def _sweep(fs, bot, now_et):
    return _run(PositionManager.missed_eod_boot_sweep(fs, bot, now_et=now_et))


# ── 1. the ACMR shape: stale intraday fill, market open → flatten ──────────

def test_stale_intraday_flattened_in_rth():
    fs, bot = _fakes([_trade()])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["stale"] == 1 and res["flattened"] == 1
    assert res["waiting_for_open"] is False
    assert fs.closes == [("t1", "missed_eod_boot_flatten")]


def test_filled_today_not_touched():
    fs, bot = _fakes([_trade(executed=TODAY_FILL)])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["stale"] == 0 and fs.closes == []


def test_swing_hold_exempt():
    """Genuine overnight styles (policy close_at_eod=False) are not ours."""
    fs, bot = _fakes([_trade(style="swing")])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["stale"] == 0 and fs.closes == []


def test_non_open_status_skipped():
    fs, bot = _fakes([_trade(status="closed"), _trade(tid="t2", status="rejected")])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["checked"] == 0 and fs.closes == []


def test_unparseable_executed_at_skipped():
    fs, bot = _fakes([_trade(executed=""), _trade(tid="t2", executed=None)])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["stale"] == 0 and fs.closes == []


# ── 2. premarket / weekend boots: alarm now, flatten at the open ───────────

def test_premarket_waits_for_open():
    fs, bot = _fakes([_trade()])
    res = _sweep(fs, bot, PREMARKET_NOW)
    assert res["stale"] == 1 and res["alarmed"] == 1
    assert res["waiting_for_open"] is True and fs.closes == []


def test_weekend_boot_waits_for_open():
    fs, bot = _fakes([_trade(executed="2026-06-12T19:00:00+00:00")])  # Fri fill
    res = _sweep(fs, bot, SATURDAY_NOW)
    assert res["stale"] == 1 and res["waiting_for_open"] is True
    assert fs.closes == []


def test_alarm_dedupes_across_passes():
    """The caller re-runs every 2 min until the open — only ONE alarm."""
    fs, bot = _fakes([_trade()])
    r1 = _sweep(fs, bot, PREMARKET_NOW)
    r2 = _sweep(fs, bot, PREMARKET_NOW)
    assert r1["alarmed"] == 1 and r2["alarmed"] == 0
    # then the open arrives → flatten fires on the next pass
    r3 = _sweep(fs, bot, RTH_NOW)
    assert r3["flattened"] == 1 and fs.closes == [("t1", "missed_eod_boot_flatten")]


# ── 3. kill switch ──────────────────────────────────────────────────────────

def test_env_kill_switch(monkeypatch):
    monkeypatch.setenv("MISSED_EOD_BOOT_SWEEP_ENABLED", "0")
    fs, bot = _fakes([_trade()])
    res = _sweep(fs, bot, RTH_NOW)
    assert res["skipped_reason"] == "disabled" and fs.closes == []


# ── 4. close failure is reported, not raised ────────────────────────────────

def test_close_failure_counted_not_raised():
    fs, bot = _fakes([_trade()], close_ok=False)
    res = _sweep(fs, bot, RTH_NOW)
    assert res["stale"] == 1 and res["flattened"] == 0


# ── 5. BotTrade.created_at default ──────────────────────────────────────────

def test_bottrade_created_at_defaults_to_now_iso():
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus)
    t = BotTrade(
        id="x", symbol="ACMR", direction=TradeDirection.LONG,
        status=TradeStatus.PENDING, setup_type="rs_leader_break",
        timeframe="intraday", quality_score=60, quality_grade="B",
        entry_price=87.85, current_price=87.85, stop_price=83.54,
        target_prices=[120.47], shares=49, risk_amount=216.86,
        potential_reward=1598.36, risk_reward_ratio=7.57,
    )
    assert t.created_at  # not "" any more
    # parseable ISO timestamp
    datetime.fromisoformat(t.created_at.replace("Z", "+00:00"))
