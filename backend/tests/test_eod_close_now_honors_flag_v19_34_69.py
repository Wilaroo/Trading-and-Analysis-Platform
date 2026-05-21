"""v19.34.69 — `/eod-close-now` honors `close_at_eod` flag.

Bug fixed: the manual EOD-close-now endpoint iterated `_open_trades`
blind and closed EVERY position — including swing & position trades
flagged `close_at_eod=False` — silently overriding the operator's
intent to hold them overnight. The auto-EOD path
(`PositionManager.check_eod_close`) already filtered correctly via
`if getattr(t, 'close_at_eod', True)` (see position_manager.py:1120-1123);
the manual button did not. Operator caught the divergence 2026-05-12
after a manual EOD prematurely flattened a swing position.

These tests call the endpoint coroutine directly (no TestClient) to
sidestep httpx/starlette version drift and match the convention of
`test_eod_close_v19_14.py`. The endpoint reads the module-level
`_trading_bot` global, so we monkeypatch it in each test.
"""
import asyncio
import pytest

from routers import trading_bot as tb_module


# --------------------------------------------------------------------------
# Minimal fake trade + bot — same shape the live bot uses
# --------------------------------------------------------------------------
class _FakeTrade:
    def __init__(self, trade_id, symbol, close_at_eod=True,
                 remaining_shares=100, realized_pnl=0.0):
        self.id = trade_id
        self.symbol = symbol
        self.close_at_eod = close_at_eod
        self.remaining_shares = remaining_shares
        self.realized_pnl = realized_pnl


class _FakeBot:
    def __init__(self, trades=None, close_pnl_map=None):
        self._open_trades = {t.id: t for t in (trades or [])}
        # close_pnl_map: trade_id → (ok: bool, realized_pnl: float)
        self._close_pnl_map = close_pnl_map or {}

    async def close_trade(self, trade_id, reason="manual"):
        ok, pnl = self._close_pnl_map.get(trade_id, (True, 0.0))
        if ok and trade_id in self._open_trades:
            self._open_trades[trade_id].realized_pnl = pnl
        return ok


def _call(payload=None, bot=None, monkeypatch=None):
    """Patch the module global + call the endpoint coroutine."""
    monkeypatch.setattr(tb_module, "_trading_bot", bot)
    return asyncio.run(tb_module.trigger_eod_close_now(payload=payload))


# --------------------------------------------------------------------------
# Bug regression: swing trades preserved by default
# --------------------------------------------------------------------------
def test_swing_positions_not_closed_by_default(monkeypatch):
    """The exact bug. Mixed bag: 2 intraday + 2 swing. Default call
    closes only the 2 intraday and reports 2 swing held."""
    trades = [
        _FakeTrade("t1", "SPY",  close_at_eod=True),
        _FakeTrade("t2", "QQQ",  close_at_eod=True),
        _FakeTrade("t3", "AAPL", close_at_eod=False),  # MUST be held
        _FakeTrade("t4", "MSFT", close_at_eod=False),  # MUST be held
    ]
    bot = _FakeBot(trades, close_pnl_map={"t1": (True, 50.0), "t2": (True, -10.0)})
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)

    assert body["success"] is True
    assert body["closed_count"] == 2
    assert body["swing_held"] == 2
    assert set(body["swing_held_symbols"]) == {"AAPL", "MSFT"}
    assert body["include_swing"] is False
    assert body["total_pnl"] == 40.0  # 50 + (-10)


def test_only_swing_positions_default_closes_zero(monkeypatch):
    """All open trades are swing. Default call closes zero, returns a
    friendly explanation pointing the operator at `include_swing=true`."""
    trades = [
        _FakeTrade("t1", "AAPL", close_at_eod=False),
        _FakeTrade("t2", "MSFT", close_at_eod=False),
    ]
    bot = _FakeBot(trades)
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 0
    assert body["swing_held"] == 2
    assert "include_swing=true" in body["message"]


# --------------------------------------------------------------------------
# Escape hatch: explicit override
# --------------------------------------------------------------------------
def test_include_swing_true_flattens_everything(monkeypatch):
    """Operator emergency flatten — explicit `include_swing=true` closes
    swing positions too. Preserves the pre-fix "flatten all" behavior
    as an explicit OPT-IN."""
    trades = [
        _FakeTrade("t1", "SPY",  close_at_eod=True),
        _FakeTrade("t2", "AAPL", close_at_eod=False),
        _FakeTrade("t3", "MSFT", close_at_eod=False),
    ]
    bot = _FakeBot(trades, close_pnl_map={
        "t1": (True, 5.0), "t2": (True, 20.0), "t3": (True, -3.0),
    })
    body = _call(payload={"include_swing": True}, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 3
    assert body["swing_held"] == 0
    assert body["swing_held_symbols"] == []
    assert body["include_swing"] is True
    assert body["total_pnl"] == 22.0


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------
def test_no_open_positions_returns_zero(monkeypatch):
    bot = _FakeBot([])
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)
    assert body["success"] is True
    assert body["closed_count"] == 0
    assert body["swing_held"] == 0
    assert "No open positions" in body["message"]


def test_none_body_treated_as_default(monkeypatch):
    """Operator hits the button without a body — endpoint receives
    payload=None and should behave as `include_swing=false`."""
    trades = [
        _FakeTrade("t1", "SPY",  close_at_eod=True),
        _FakeTrade("t2", "AAPL", close_at_eod=False),
    ]
    bot = _FakeBot(trades, close_pnl_map={"t1": (True, 0.0)})
    body = _call(payload=None, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 1
    assert body["swing_held"] == 1
    assert "AAPL" in body["swing_held_symbols"]


def test_missing_close_at_eod_attr_defaults_to_true(monkeypatch):
    """A legacy trade missing `close_at_eod` attribute MUST be treated as
    intraday (default True) so we never silently skip an unflagged trade.
    Mirrors the auto-path safety default."""
    class _LegacyTrade:
        id = "t1"
        symbol = "OLD"
        remaining_shares = 50
        realized_pnl = 0.0
        # NO close_at_eod attribute

    bot = _FakeBot()
    bot._open_trades = {"t1": _LegacyTrade()}
    bot._close_pnl_map = {"t1": (True, 0.0)}
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 1
    assert body["swing_held"] == 0


def test_partial_failure_records_each_result(monkeypatch):
    """If one close_trade returns False, that trade is reported as
    failed but the others still succeed."""
    trades = [
        _FakeTrade("t1", "SPY", close_at_eod=True),
        _FakeTrade("t2", "QQQ", close_at_eod=True),
    ]
    bot = _FakeBot(trades, close_pnl_map={
        "t1": (True, 10.0),
        "t2": (False, 0.0),   # broker refused
    })
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 1
    statuses = {row["symbol"]: row["status"] for row in body["results"]}
    assert statuses == {"SPY": "closed", "QQQ": "failed"}


def test_close_trade_raises_recorded_as_error(monkeypatch):
    """If `close_trade` raises mid-flight, the error is recorded against
    that symbol and the loop continues."""
    trades = [
        _FakeTrade("t1", "SPY", close_at_eod=True),
        _FakeTrade("t2", "QQQ", close_at_eod=True),
    ]

    class _ExplodingBot(_FakeBot):
        async def close_trade(self, trade_id, reason="manual"):
            if trade_id == "t2":
                raise RuntimeError("IB connection lost")
            return True

    bot = _ExplodingBot(trades)
    body = _call(payload={}, bot=bot, monkeypatch=monkeypatch)
    assert body["closed_count"] == 1
    statuses = {row["symbol"]: row["status"] for row in body["results"]}
    assert statuses == {"SPY": "closed", "QQQ": "error"}
    qqq_row = next(row for row in body["results"] if row["symbol"] == "QQQ")
    assert "IB connection lost" in qqq_row["error"]


# --------------------------------------------------------------------------
# Response shape: every result row carries close_at_eod for audit
# --------------------------------------------------------------------------
def test_each_result_row_includes_close_at_eod(monkeypatch):
    trades = [
        _FakeTrade("t1", "SPY", close_at_eod=True),
        _FakeTrade("t2", "AAPL", close_at_eod=False),
    ]
    bot = _FakeBot(trades, close_pnl_map={
        "t1": (True, 0.0), "t2": (True, 0.0),
    })
    body = _call(payload={"include_swing": True}, bot=bot, monkeypatch=monkeypatch)
    flags = {row["symbol"]: row["close_at_eod"] for row in body["results"]}
    assert flags == {"SPY": True, "AAPL": False}


# --------------------------------------------------------------------------
# Service-503 path: no bot mounted
# --------------------------------------------------------------------------
def test_503_when_bot_not_initialized(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(tb_module, "_trading_bot", None)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(tb_module.trigger_eod_close_now(payload={}))
    assert excinfo.value.status_code == 503
