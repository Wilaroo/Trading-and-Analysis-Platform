"""v335 — EVERY EOD path selects victims via the policy authority
(should_close_at_eod), not the stale per-trade `close_at_eod` attribute.

Probe evidence (diag_eod_pusher, 2026-06-12): the 15:45 v162 main pass
(policy-based since v334b) correctly held multi_day positions, but the
15:47 T-2 force-MKT escalation read `getattr(t, "close_at_eod", True)`
and flattened ORCL (multi_day/opening_drive) and SMCI
(multi_day/fashionably_late) anyway. Same stale-attr bug class in the
T-1 alert, the EOD status endpoint, and morning readiness.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "position_manager.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services.position_manager import PositionManager  # noqa: E402


def _t(symbol, style, setup=None):
    # close_at_eod=True on EVERY trade — the stale attr the old code read.
    # Policy must override it for long-horizon styles/setups.
    return SimpleNamespace(symbol=symbol, trade_style=style, setup_type=setup,
                           setup_variant=None, timeframe=None,
                           close_at_eod=True, direction=None)


def _bot(trades):
    async def _broadcast(_evt):
        pass
    return SimpleNamespace(
        _open_trades={f"tid_{t.symbol}": t for t in trades},
        _db=None,
        _broadcast_event=_broadcast,
        _eod_t_minus_2_fired_today=None,
        _eod_t_minus_1_alerted_today=None,
    )


MIXED = [
    _t("ORCL", "multi_day", "opening_drive"),        # explicit hold (06-12 victim)
    _t("SMCI", "multi_day", "fashionably_late"),     # explicit hold (06-12 victim)
    _t("CRS", "trade_2_hold", "daily_breakout"),     # v334b setup-horizon hold
    _t("AAL", "intraday", "fashionably_late"),       # legit close
    _t("CZR", "trade_2_hold", "orb"),                # legit close (orb→intraday)
]


# ── 1. T-2 force-MKT escalation ──────────────────────────────────────────

def test_t2_escalate_skips_policy_holds():
    pm = PositionManager.__new__(PositionManager)
    closed = []

    async def _close(tid, bot, reason=None, **kw):
        closed.append(bot._open_trades[tid].symbol)
        return True
    pm.close_trade = _close

    bot = _bot(MIXED)
    res = asyncio.run(pm._eod_t_minus_2_escalate(bot))
    assert sorted(closed) == ["AAL", "CZR"], closed
    assert sorted(res["escalated"]) == ["AAL", "CZR"]
    assert res["errors"] == []


def test_t2_escalate_noop_when_only_holds():
    pm = PositionManager.__new__(PositionManager)

    async def _close(tid, bot, reason=None, **kw):
        raise AssertionError("close_trade must not be called for holds")
    pm.close_trade = _close

    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),
                _t("CRS", "trade_2_hold", "daily_breakout")])
    res = asyncio.run(pm._eod_t_minus_2_escalate(bot))
    assert res.get("noop") is True
    assert res["escalated"] == []


def test_t2_escalate_idempotent_per_day():
    pm = PositionManager.__new__(PositionManager)
    calls = []

    async def _close(tid, bot, reason=None, **kw):
        calls.append(tid)
        return True
    pm.close_trade = _close

    bot = _bot([_t("AAL", "intraday")])
    asyncio.run(pm._eod_t_minus_2_escalate(bot))
    res2 = asyncio.run(pm._eod_t_minus_2_escalate(bot))
    assert res2.get("noop") is True
    assert len(calls) == 1


# ── 2. T-1 alert ─────────────────────────────────────────────────────────

def test_t1_alert_silent_when_only_holds():
    pm = PositionManager.__new__(PositionManager)
    pm._ib_position_snapshot_safe = lambda: []

    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),
                _t("CRS", "trade_2_hold", "stage_2_breakout")])
    broadcasts = []

    async def _broadcast(evt):
        broadcasts.append(evt)
    bot._broadcast_event = _broadcast

    asyncio.run(pm._eod_t_minus_1_alert(bot))
    assert broadcasts == []          # no false CRITICAL for legit holds
    assert bot._eod_t_minus_1_alerted_today is not None


def test_t1_alert_fires_for_intraday_straggler():
    pm = PositionManager.__new__(PositionManager)
    pm._ib_position_snapshot_safe = lambda: []

    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),
                _t("AAL", "intraday")])
    broadcasts = []

    async def _broadcast(evt):
        broadcasts.append(evt)
    bot._broadcast_event = _broadcast

    asyncio.run(pm._eod_t_minus_1_alert(bot))
    assert len(broadcasts) == 1
    assert broadcasts[0]["tracked_open"] == ["AAL"]   # holds excluded


# ── 3. morning readiness — holds carried overnight are NOT "stuck" ──────

def test_morning_readiness_holds_not_stuck():
    from services.morning_readiness_service import _check_open_positions_clean
    holds = [_t("CPB", "multi_day", "daily_breakout"),
             _t("PENN", "multi_day", "daily_breakout"),
             _t("DKNG", "multi_day", "squeeze")]
    for h in holds:
        h.opened_at = "2026-06-12T15:00:00+00:00"   # opened YESTERDAY
    bot = _bot(holds)
    res = _check_open_positions_clean(None, bot=bot)
    assert res["status"] != "red", res
    assert not res.get("stuck_positions"), res


# ── 4. source-level: no stale-attr selection left at the 4 sites ─────────

def test_no_stale_attr_selection_in_eod_paths():
    pm_src = (ROOT / "backend/services/position_manager.py").read_text()
    assert 'if getattr(t, "close_at_eod", True)' not in pm_src
    rt_src = (ROOT / "backend/routers/trading_bot.py").read_text()
    assert "_scae_status" in rt_src
    mr_src = (ROOT / "backend/services/morning_readiness_service.py").read_text()
    assert "_scae_morning" in mr_src
    assert 'close_at_eod = getattr(trade, "close_at_eod", True)' not in mr_src
