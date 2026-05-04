"""
v19.31 (2026-05-04) — regression pin for the externally-closed phantom
sweep fix in position_manager.py.

The bug:
  Operator's LITE trade (62 sh short, OCA bracket with target $961.26)
  hit the OCA target on IB. IB closed the position via the bracket,
  realizedPNL $112.66, position 0 shares. But the bot's `_open_trades`
  cache still had the trade with remaining_shares=62. Result: dashboard
  kept drawing LITE as a live position the bot was managing.

  The v19.27 0sh-leftover phantom sweep didn't fire because
  remaining_shares was 62, not 0. The v19.29 wrong-direction phantom
  sweep didn't fire because IB has zero shares in BOTH directions
  (not just the opposite direction).

The fix:
  Add a third sweep case: bot tracks shares > 0 AND IB has zero shares
  in BOTH directions AND trade is older than 30s → mark CLOSED with
  `oca_closed_externally_v19_31` reason.

These tests pin the exact LITE scenario + adjacent edge cases.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest

# Make backend importable without running the full server.py module.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Lightweight test doubles ─────────────────────────────────────────


class _FakeStatus:
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"


class _FakeDirection:
    def __init__(self, value: str):
        self.value = value

    def __str__(self):
        return self.value


@dataclass
class _FakeTrade:
    id: str
    symbol: str
    direction: Any
    status: Any = _FakeStatus.OPEN
    remaining_shares: int = 0
    shares: int = 0
    entry_price: float = 0.0
    fill_price: float = 0.0
    stop_price: float = 0.0
    target_prices: List[float] = field(default_factory=list)
    executed_at: Optional[str] = None
    close_reason: Optional[str] = None
    closed_at: Optional[str] = None
    risk_amount: float = 0.0


class _FakeBot:
    def __init__(self):
        self._open_trades: Dict[str, _FakeTrade] = {}
        self._closed_trades: List[_FakeTrade] = []
        self._db = None
        self._trade_executor = MagicMock()
        # Capture persist calls so tests can assert on them.
        self.persisted: List[_FakeTrade] = []

    def _persist_trade(self, trade):
        self.persisted.append(trade)

    def _apply_commission(self, *args, **kwargs):
        return 0.0


def _ago(seconds: float) -> str:
    """Helper: ISO-format timestamp seconds in the past."""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_bot():
    return _FakeBot()


@pytest.fixture(autouse=True)
def _patch_trade_status_and_direction():
    """The phantom-sweep block does `from services.trading_bot_service import
    TradeStatus as _TS` inside the function — patch the module so the
    test can use our fake enum."""
    fake_module = MagicMock()
    fake_module.TradeStatus = _FakeStatus
    fake_module.TradeDirection = _FakeDirection
    fake_module.BotTrade = _FakeTrade

    # `from services.trading_bot_service import TradeDirection, TradeStatus`
    # at the top of `update_open_positions` resolves the names at
    # call-time. We just need the module attribute to be set.
    with patch.dict(sys.modules, {"services.trading_bot_service": fake_module}):
        yield


@pytest.fixture
def patch_pusher(monkeypatch):
    """Configure the pusher's _pushed_ib_data + is_pusher_connected stub.
    Returns a setter so each test can drive the IB position list."""

    state = {"positions": [], "connected": True, "quotes": {}}

    fake_routers_ib = MagicMock()
    fake_routers_ib._pushed_ib_data = state
    fake_routers_ib.is_pusher_connected = lambda: state["connected"]
    fake_routers_ib.get_pushed_quotes = lambda: state.get("quotes", {})

    monkeypatch.setitem(sys.modules, "routers.ib", fake_routers_ib)

    def set_ib_positions(positions):
        state["positions"] = positions

    def set_connected(v):
        state["connected"] = v

    return type("_PusherCtl", (), {
        "set_positions": staticmethod(set_ib_positions),
        "set_connected": staticmethod(set_connected),
        "state": state,
    })


@pytest.fixture
def patch_emit_stream(monkeypatch):
    captured = []

    async def _fake_emit(event):
        captured.append(event)

    fake_sentcom = MagicMock()
    fake_sentcom.emit_stream_event = _fake_emit
    monkeypatch.setitem(sys.modules, "services.sentcom_service", fake_sentcom)
    return captured


@pytest.fixture
def patch_position_reconciler(monkeypatch):
    fake_recon = MagicMock()
    fake_recon.record_ib_direction_observation = MagicMock()
    monkeypatch.setitem(sys.modules, "services.position_reconciler", fake_recon)
    return fake_recon


# ─── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_externally_closed_phantom_swept_when_ib_has_zero_both_directions(
    fake_bot, patch_pusher, patch_emit_stream, patch_position_reconciler
):
    """LITE scenario: bot tracks 62 sh short, IB has 0 sh both directions,
    trade is >30s old → must be swept with oca_closed_externally reason."""
    # Arrange: bot has a LITE short with remaining 62sh, executed 5 min ago
    trade = _FakeTrade(
        id="lite-trade-1",
        symbol="LITE",
        direction=_FakeDirection("short"),
        status=_FakeStatus.OPEN,
        remaining_shares=62,
        shares=62,
        executed_at=_ago(300),  # 5 min ago, well past the 30s grace
        fill_price=992.37,
        stop_price=993.86,
        target_prices=[961.26],
    )
    fake_bot._open_trades[trade.id] = trade

    # IB has no positions for LITE (closed externally via OCA)
    patch_pusher.set_positions([])

    # Act
    from services.position_manager import PositionManager
    pm = PositionManager()
    await pm.update_open_positions(fake_bot)

    # Assert
    assert trade.id not in fake_bot._open_trades, "Trade should be removed from open_trades"
    assert trade in fake_bot._closed_trades, "Trade should be appended to closed_trades"
    assert trade.status == _FakeStatus.CLOSED
    assert trade.close_reason == "oca_closed_externally_v19_31"
    assert trade.closed_at is not None
    assert trade.remaining_shares == 0
    assert trade in fake_bot.persisted, "Trade should be persisted"
    # Stream event emitted
    assert any(
        e.get("event") == "oca_closed_externally_swept" and e.get("symbol") == "LITE"
        for e in patch_emit_stream
    )


@pytest.mark.asyncio
async def test_externally_closed_phantom_NOT_swept_within_30s_grace(
    fake_bot, patch_pusher, patch_emit_stream, patch_position_reconciler
):
    """Brand-new fill IB hasn't reported yet must NOT be swept."""
    trade = _FakeTrade(
        id="fresh-trade",
        symbol="ABC",
        direction=_FakeDirection("long"),
        status=_FakeStatus.OPEN,
        remaining_shares=100,
        executed_at=_ago(5),  # only 5s ago
    )
    fake_bot._open_trades[trade.id] = trade
    patch_pusher.set_positions([])

    from services.position_manager import PositionManager
    pm = PositionManager()
    await pm.update_open_positions(fake_bot)

    assert trade.id in fake_bot._open_trades, "Recent trade must NOT be swept"
    assert trade.status == _FakeStatus.OPEN


@pytest.mark.asyncio
async def test_externally_closed_phantom_NOT_swept_when_ib_still_has_shares(
    fake_bot, patch_pusher, patch_emit_stream, patch_position_reconciler
):
    """If IB still shows the position (any shares same direction), don't sweep."""
    trade = _FakeTrade(
        id="held-trade",
        symbol="APH",
        direction=_FakeDirection("long"),
        status=_FakeStatus.OPEN,
        remaining_shares=588,
        executed_at=_ago(120),
    )
    fake_bot._open_trades[trade.id] = trade

    # IB still has 588 long
    patch_pusher.set_positions([
        {"symbol": "APH", "position": 588.0},
    ])

    from services.position_manager import PositionManager
    pm = PositionManager()
    await pm.update_open_positions(fake_bot)

    assert trade.id in fake_bot._open_trades
    assert trade.status == _FakeStatus.OPEN
    assert trade.close_reason is None


@pytest.mark.asyncio
async def test_wrong_direction_sweep_still_takes_precedence(
    fake_bot, patch_pusher, patch_emit_stream, patch_position_reconciler
):
    """If bot is LONG but IB only has SHORT, the v19.29 wrong-direction
    sweep must still fire (different reason code)."""
    trade = _FakeTrade(
        id="wrong-dir",
        symbol="SOFI",
        direction=_FakeDirection("short"),
        status=_FakeStatus.OPEN,
        remaining_shares=500,
        executed_at=_ago(60),
    )
    fake_bot._open_trades[trade.id] = trade
    # IB has 1000 LONG (opposite of bot's SHORT)
    patch_pusher.set_positions([
        {"symbol": "SOFI", "position": 1000.0},
    ])

    from services.position_manager import PositionManager
    pm = PositionManager()
    await pm.update_open_positions(fake_bot)

    assert trade.id not in fake_bot._open_trades
    assert trade.close_reason == "wrong_direction_phantom_swept_v19_29"


@pytest.mark.asyncio
async def test_zero_share_leftover_sweep_still_works(
    fake_bot, patch_pusher, patch_emit_stream, patch_position_reconciler
):
    """v19.27 0-share leftover sweep: rem == 0, IB has 0, must fire."""
    trade = _FakeTrade(
        id="leftover",
        symbol="OKLO",
        direction=_FakeDirection("short"),
        status=_FakeStatus.OPEN,
        remaining_shares=0,  # already scaled out fully
        executed_at=_ago(60),
    )
    fake_bot._open_trades[trade.id] = trade
    patch_pusher.set_positions([])

    from services.position_manager import PositionManager
    pm = PositionManager()
    await pm.update_open_positions(fake_bot)

    assert trade.id not in fake_bot._open_trades
    assert trade.close_reason == "phantom_auto_swept_v19_27"


def test_v19_31_external_close_block_present_in_source():
    """Source-level pin: catch a future refactor that drops the v19.31 fix."""
    import inspect
    from services import position_manager as pm_mod
    src = inspect.getsource(pm_mod.PositionManager.update_open_positions)
    # The new branch must reference both the reason code and the
    # both-directions-zero condition in close proximity.
    assert "oca_closed_externally_v19_31" in src
    assert "ib_qty_my_dir == 0" in src and "ib_qty_opp_dir == 0" in src
