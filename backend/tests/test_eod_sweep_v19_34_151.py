"""v19.34.151 — EOD sweep regression suite.

Pins the post-2026-05-13 hardening:

  • `_run_eod_orphan_sweep` is invoked EVERY EOD tick, even when zero
    intraday positions closed (pre-fix bug: gated on `closed_count > 0`).
  • Pending DAY LMT entries for `close_at_eod=True` trades are
    cancelled at EOD by the sweep.
  • Swing / position trades (`close_at_eod=False`) are NEVER swept.
  • Sweep is idempotent: `_eod_sweep_executed_today` flag prevents
    re-firing.
  • `classify_intraday_entries_for_eod_sweep` produces the new
    VERDICT_EOD_INTRADAY_ENTRY which is in SAFE_TO_AUTO_CANCEL.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.orphan_gtc_reconciler import (
    SAFE_TO_AUTO_CANCEL,
    VERDICT_EOD_INTRADAY_ENTRY,
    classify_intraday_entries_for_eod_sweep,
)


# ────────────────────────────────────────────────────────────────────
# 1. Pure-classifier tests — no IB / Mongo needed
# ────────────────────────────────────────────────────────────────────

def test_pending_day_lmt_entry_for_intraday_setup_is_swept():
    """The exact case the operator hit 2026-05-13: a DAY LMT entry
    for a SCALP setup still alive at 3:55 PM. Must be flagged."""
    orders = [{
        "ib_order_id": 42, "symbol": "AAPL", "action": "BUY",
        "quantity": 100, "order_type": "LMT", "limit_price": 199.50,
        "time_in_force": "DAY", "status": "Submitted",
    }]
    trades = [{
        "id": "trade-abc", "symbol": "AAPL", "status": "pending",
        "entry_order_id": 42, "setup_type": "orb_long",
        "close_at_eod": True,
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    assert len(out) == 1
    assert out[0].verdict == VERDICT_EOD_INTRADAY_ENTRY
    assert out[0].symbol == "AAPL"
    assert out[0].bot_trade_id == "trade-abc"


def test_swing_trades_are_NOT_swept():
    """close_at_eod=False trades stay alive overnight."""
    orders = [{
        "ib_order_id": 50, "symbol": "NVDA", "action": "BUY",
        "quantity": 50, "order_type": "LMT", "limit_price": 800.0,
        "time_in_force": "DAY", "status": "Submitted",
    }]
    trades = [{
        "id": "swing-1", "symbol": "NVDA", "status": "pending",
        "entry_order_id": 50, "setup_type": "weekly_breakout",
        "close_at_eod": False,
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    assert out == []


def test_position_trades_are_NOT_swept():
    """Same as swing — position trades have close_at_eod=False."""
    orders = [{
        "ib_order_id": 51, "symbol": "MSFT", "action": "BUY",
        "quantity": 200, "order_type": "LMT", "limit_price": 350.0,
        "time_in_force": "DAY", "status": "Submitted",
    }]
    trades = [{
        "id": "pos-1", "symbol": "MSFT", "status": "pending",
        "entry_order_id": 51, "setup_type": "monthly_swing",
        "close_at_eod": False,
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    assert out == []


def test_already_filled_intraday_entries_NOT_swept():
    """If the entry order's parent trade is already OPEN, the order
    isn't pending — it's the existing stop/target leg. Skip it
    (those are handled by _cancel_ib_bracket_orders during close)."""
    orders = [{
        "ib_order_id": 100, "symbol": "TSLA", "action": "BUY",
        "quantity": 50, "order_type": "LMT", "limit_price": 200.0,
        "time_in_force": "DAY", "status": "Submitted",
    }]
    trades = [{
        "id": "active-1", "symbol": "TSLA", "status": "open",
        "entry_order_id": 100, "setup_type": "first_vwap_pullback",
        "close_at_eod": True,
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    assert out == []


def test_unmatched_DAY_entries_NOT_auto_cancelled():
    """Manual TWS-placed orders the bot doesn't know about must NOT
    be auto-swept — operator's external orders are sacred."""
    orders = [{
        "ib_order_id": 9999, "symbol": "MANUAL", "action": "BUY",
        "quantity": 100, "order_type": "LMT", "limit_price": 50.0,
        "time_in_force": "DAY", "status": "Submitted",
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=[],
    )
    assert out == []


def test_GTC_orders_NOT_in_intraday_entry_sweep():
    """GTC orders are the orphan-bracket case — covered by the
    existing classify_open_orders path. Don't double-handle them."""
    orders = [{
        "ib_order_id": 200, "symbol": "VALE", "action": "SELL",
        "quantity": 500, "order_type": "STP", "stop_price": 14.50,
        "time_in_force": "GTC", "status": "Submitted",
    }]
    trades = [{
        "id": "trd-x", "symbol": "VALE", "status": "pending",
        "entry_order_id": 200, "setup_type": "orb_short",
        "close_at_eod": True,
    }]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    assert out == []


def test_mixed_intraday_and_swing_classifier_correctly_filters():
    """5 mixed orders — only the 2 intraday DAY entries are flagged."""
    orders = [
        # intraday — flag
        {"ib_order_id": 1, "symbol": "AAA", "action": "BUY",
         "quantity": 10, "order_type": "LMT", "limit_price": 1.0,
         "time_in_force": "DAY", "status": "Submitted"},
        # swing — skip
        {"ib_order_id": 2, "symbol": "BBB", "action": "BUY",
         "quantity": 20, "order_type": "LMT", "limit_price": 2.0,
         "time_in_force": "DAY", "status": "Submitted"},
        # GTC — skip (orphan path)
        {"ib_order_id": 3, "symbol": "CCC", "action": "SELL",
         "quantity": 30, "order_type": "STP", "stop_price": 3.0,
         "time_in_force": "GTC", "status": "Submitted"},
        # intraday — flag
        {"ib_order_id": 4, "symbol": "DDD", "action": "SELL",
         "quantity": 40, "order_type": "STP", "stop_price": 4.0,
         "time_in_force": "DAY", "status": "Submitted"},
        # unmatched manual — skip
        {"ib_order_id": 5, "symbol": "EEE", "action": "BUY",
         "quantity": 50, "order_type": "LMT", "limit_price": 5.0,
         "time_in_force": "DAY", "status": "Submitted"},
    ]
    trades = [
        {"id": "t1", "symbol": "AAA", "status": "pending",
         "entry_order_id": 1, "close_at_eod": True},
        {"id": "t2", "symbol": "BBB", "status": "pending",
         "entry_order_id": 2, "close_at_eod": False},  # swing
        {"id": "t3", "symbol": "CCC", "status": "pending",
         "entry_order_id": 3, "close_at_eod": True},   # GTC excluded
        {"id": "t4", "symbol": "DDD", "status": "pending",
         "entry_order_id": 4, "close_at_eod": True},
    ]
    out = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    flagged = sorted(v.symbol for v in out)
    assert flagged == ["AAA", "DDD"]
    for v in out:
        assert v.verdict == VERDICT_EOD_INTRADAY_ENTRY


def test_eod_intraday_entry_verdict_is_in_safe_auto_cancel_set():
    """The new verdict MUST be honoured by cancel_orphan_gtc_orders."""
    assert VERDICT_EOD_INTRADAY_ENTRY in SAFE_TO_AUTO_CANCEL


# ────────────────────────────────────────────────────────────────────
# 2. End-to-end check_eod_close → sweep orchestration
# ────────────────────────────────────────────────────────────────────

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
    def __init__(self, trades=None):
        self._open_trades = {t.id: t for t in (trades or [])}
        self._eod_close_enabled = True
        self._last_eod_check_date = None
        self._eod_close_executed_today = False
        self._eod_close_hour = 15
        self._eod_close_minute = 55
        self._db = None
        self._broadcast_event = AsyncMock()


def _force_after_eod_window(monkeypatch):
    """Pin time so the EOD logic enters the close window."""
    from services import position_manager as pm_mod
    real_now = datetime.now

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return real_now()
            # 3:56 PM ET → after EOD threshold, before market_close
            from zoneinfo import ZoneInfo
            return datetime(2026, 5, 13, 15, 56, 0,
                            tzinfo=ZoneInfo("America/New_York"))

    monkeypatch.setattr(pm_mod, "datetime", _FakeDT)


@pytest.mark.asyncio
async def test_sweep_fires_even_with_zero_intraday_positions(monkeypatch):
    """v19.34.151 P0 — `_run_eod_orphan_sweep` must be called even
    when `_open_trades` is empty at EOD time (pre-fix bug)."""
    from services.position_manager import PositionManager

    _force_after_eod_window(monkeypatch)
    pm = PositionManager()
    bot = _StubBot(trades=[])

    sweep_called = {"n": 0}

    async def _fake_sweep(b):
        sweep_called["n"] += 1
        b._eod_sweep_executed_today = True

    monkeypatch.setattr(pm, "_run_eod_orphan_sweep", _fake_sweep)
    await pm.check_eod_close(bot)
    # Yield once so the create_task() coroutine actually runs.
    import asyncio
    await asyncio.sleep(0.01)
    assert sweep_called["n"] == 1, (
        "sweep MUST fire at EOD even with zero open trades — "
        "the pre-fix bug was a `closed_count > 0` gate that left "
        "stale DAY entries alive overnight."
    )


@pytest.mark.asyncio
async def test_sweep_fires_with_only_swing_trades(monkeypatch):
    """If every open trade is swing (close_at_eod=False), the close
    loop returns early but the sweep STILL needs to run to clean up
    any pending intraday DAY entries that came in earlier."""
    from services.position_manager import PositionManager

    _force_after_eod_window(monkeypatch)
    pm = PositionManager()
    bot = _StubBot(trades=[
        _StubTrade("SWING1", close_at_eod=False),
        _StubTrade("SWING2", close_at_eod=False),
    ])

    sweep_called = {"n": 0}

    async def _fake_sweep(b):
        sweep_called["n"] += 1
        b._eod_sweep_executed_today = True

    monkeypatch.setattr(pm, "_run_eod_orphan_sweep", _fake_sweep)
    await pm.check_eod_close(bot)
    import asyncio
    await asyncio.sleep(0.01)
    assert sweep_called["n"] == 1


@pytest.mark.asyncio
async def test_sweep_idempotent_via_executed_today_flag(monkeypatch):
    """Second call same day = no-op."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    bot = _StubBot()
    bot._eod_sweep_executed_today = True
    bot._last_eod_sweep_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Mock out asyncio.sleep so the test doesn't actually wait 8s.
    with patch("services.position_manager.asyncio.sleep", new=AsyncMock()):
        with patch(
            "services.orphan_gtc_reconciler.audit_orphan_gtc_orders",
            new=AsyncMock(),
        ) as mock_audit:
            await pm._run_eod_orphan_sweep(bot)
            mock_audit.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_resets_flag_on_new_day(monkeypatch):
    """Yesterday's flag must NOT block today's sweep."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    bot = _StubBot()
    bot._eod_sweep_executed_today = True
    bot._last_eod_sweep_date = "1999-01-01"  # ancient

    with patch("services.position_manager.asyncio.sleep", new=AsyncMock()):
        with patch(
            "services.orphan_gtc_reconciler.audit_orphan_gtc_orders",
            new=AsyncMock(return_value={"success": True, "verdicts": []}),
        ):
            with patch(
                "services.orphan_gtc_reconciler._fetch_ib_open_orders",
                new=AsyncMock(return_value=([], {})),
            ):
                with patch(
                    "services.orphan_gtc_reconciler._fetch_bot_trades",
                    return_value=([], {}),
                ):
                    await pm._run_eod_orphan_sweep(bot)
    # Flag should have been reset for today, then re-set to True.
    from zoneinfo import ZoneInfo
    today = datetime.now(timezone.utc).astimezone(
        ZoneInfo("America/New_York")
    ).strftime("%Y-%m-%d")
    assert bot._last_eod_sweep_date == today
    assert bot._eod_sweep_executed_today is True


@pytest.mark.asyncio
async def test_sweep_disabled_when_env_var_off(monkeypatch):
    """Operator kill-switch via AUTO_SWEEP_ORPHAN_GTC=false."""
    from services.position_manager import PositionManager
    monkeypatch.setenv("AUTO_SWEEP_ORPHAN_GTC", "false")
    pm = PositionManager()
    bot = _StubBot()
    bot._eod_sweep_executed_today = False
    bot._last_eod_sweep_date = None

    with patch("services.position_manager.asyncio.sleep", new=AsyncMock()):
        with patch(
            "services.orphan_gtc_reconciler.audit_orphan_gtc_orders",
            new=AsyncMock(),
        ) as mock_audit:
            await pm._run_eod_orphan_sweep(bot)
            mock_audit.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_combines_orphan_GTC_and_intraday_entries(monkeypatch):
    """The sweep must aggregate both verdict sources before firing
    the cancellation call. Idempotent dedupe by ib_order_id."""
    from services.position_manager import PositionManager
    from services.orphan_gtc_reconciler import (
        VERDICT_NAKED_NO_POSITION, OrderVerdict,
    )
    pm = PositionManager()
    bot = _StubBot()
    bot._eod_sweep_executed_today = False
    bot._last_eod_sweep_date = None

    naked_verdict_dict = {
        "ib_order_id": 1, "perm_id": None, "symbol": "NAKED",
        "action": "SELL", "quantity": 100, "order_type": "STP",
        "limit_price": None, "stop_price": 50.0,
        "time_in_force": "GTC", "status": "Submitted",
        "verdict": VERDICT_NAKED_NO_POSITION, "reasons": [],
        "bot_trade_id": None, "ib_position_size": 0.0,
        "submitted_at": None,
    }
    intraday_verdict = OrderVerdict(
        ib_order_id=2, perm_id=None, symbol="INTRA",
        action="BUY", quantity=50, order_type="LMT",
        limit_price=10.0, stop_price=None,
        time_in_force="DAY", status="Submitted",
        verdict=VERDICT_EOD_INTRADAY_ENTRY, reasons=["intraday entry"],
        bot_trade_id="t-intra",
    )

    captured_cancels: list = []

    async def _fake_cancel(*, verdicts_to_cancel):
        captured_cancels.extend(verdicts_to_cancel)
        return {"cancelled": [{"ib_order_id": v.ib_order_id} for v in verdicts_to_cancel],
                "errors": []}

    with patch("services.position_manager.asyncio.sleep", new=AsyncMock()):
        with patch(
            "services.orphan_gtc_reconciler.audit_orphan_gtc_orders",
            new=AsyncMock(return_value={
                "success": True, "verdicts": [naked_verdict_dict],
            }),
        ):
            with patch(
                "services.orphan_gtc_reconciler._fetch_ib_open_orders",
                new=AsyncMock(return_value=([], {})),
            ):
                with patch(
                    "services.orphan_gtc_reconciler._fetch_bot_trades",
                    return_value=([], {}),
                ):
                    with patch(
                        "services.orphan_gtc_reconciler.classify_intraday_entries_for_eod_sweep",
                        return_value=[intraday_verdict],
                    ):
                        with patch(
                            "services.orphan_gtc_reconciler.cancel_orphan_gtc_orders",
                            new=_fake_cancel,
                        ):
                            await pm._run_eod_orphan_sweep(bot)

    cancelled_oids = sorted(v.ib_order_id for v in captured_cancels)
    assert cancelled_oids == [1, 2], (
        f"sweep must cancel BOTH orphan brackets (1) AND pending "
        f"intraday entries (2); got {cancelled_oids}"
    )


# ────────────────────────────────────────────────────────────────────
# 3. G3 cleanup: _cancel_ib_bracket_orders has no dead try/pass
# ────────────────────────────────────────────────────────────────────

def test_dead_try_pass_removed_from_bracket_cancel():
    """Pre-fix this function had `try: pass / except: return` left
    over from a removed import guard. Confirm it's gone — the
    function should not have an unconditional early-return path."""
    import inspect
    from services.trade_executor_service import TradeExecutorService
    src = inspect.getsource(TradeExecutorService._cancel_ib_bracket_orders)
    # The dead pattern was:
    #     try:
    #         pass
    #     except Exception as e:
    #         logger.warning(...)
    #         return
    assert "try:\n            pass" not in src, (
        "Dead `try: pass` guard must be removed — it was a leftover "
        "from a removed import that no longer protects anything."
    )
