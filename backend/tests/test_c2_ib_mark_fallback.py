"""
test_c2_ib_mark_fallback.py — regression guard for the C2 IB-mark fallback
(PositionManager._apply_ib_position_marks).

Drives the REAL method with a bare PositionManager, a fake bot holding open
trades, and a monkeypatched IB positions push. Asserts: frozen marks get the IB
mark + correct UPL (long & short), already-moving marks are left alone, env-off
is a no-op, and no IB mark = no-op.

Run on DGX:
    .venv/bin/python -m pytest backend/tests/test_c2_ib_mark_fallback.py -q
"""
import os
from types import SimpleNamespace

import routers.ib as ib_mod
from services.position_manager import PositionManager
from services.trading_bot_service import TradeStatus, TradeDirection


def _trade(symbol, direction, fill, cur, shares=100):
    return SimpleNamespace(
        symbol=symbol, direction=direction, status=TradeStatus.OPEN,
        fill_price=fill, current_price=cur, remaining_shares=shares,
        original_shares=shares, realized_pnl=0.0, unrealized_pnl=0.0, pnl_pct=0.0,
    )


def _bot(trades):
    return SimpleNamespace(_open_trades={i: t for i, t in enumerate(trades)})


def _setup_ib(positions, connected=True):
    ib_mod._pushed_ib_data = {"positions": positions}
    ib_mod.is_pusher_connected = lambda: connected


def _pm():
    return PositionManager.__new__(PositionManager)


def test_frozen_long_gets_ib_mark_and_upl():
    os.environ.pop("POSITION_IB_MARK_FALLBACK", None)
    _setup_ib([{"symbol": "INTC", "position": 100, "marketPrice": 142.00}])
    t = _trade("INTC", TradeDirection.LONG, fill=140.88, cur=140.88)  # frozen at fill
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 1
    assert abs(t.current_price - 142.00) < 1e-9
    assert abs(t.unrealized_pnl - (142.00 - 140.88) * 100) < 1e-6  # +112.00


def test_frozen_short_gets_correct_upl():
    _setup_ib([{"symbol": "YINN", "position": -100, "marketPrice": 25.00}])
    t = _trade("YINN", TradeDirection.SHORT, fill=26.40, cur=26.40)
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 1
    assert abs(t.unrealized_pnl - (26.40 - 25.00) * 100) < 1e-6  # +140.00 (short profit)


def test_moving_mark_is_left_alone():
    _setup_ib([{"symbol": "MSTR", "position": -100, "marketPrice": 100.00}])
    t = _trade("MSTR", TradeDirection.SHORT, fill=126.62, cur=113.47)  # quote already moved it
    before = t.current_price
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 0 and t.current_price == before


def test_env_off_is_noop():
    os.environ["POSITION_IB_MARK_FALLBACK"] = "0"
    _setup_ib([{"symbol": "INTC", "position": 100, "marketPrice": 142.00}])
    t = _trade("INTC", TradeDirection.LONG, fill=140.88, cur=140.88)
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 0 and t.current_price == 140.88
    os.environ.pop("POSITION_IB_MARK_FALLBACK", None)


def test_no_ib_mark_is_noop():
    _setup_ib([])  # IB reports no positions
    t = _trade("INTC", TradeDirection.LONG, fill=140.88, cur=140.88)
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 0


def test_pusher_disconnected_is_noop():
    _setup_ib([{"symbol": "INTC", "position": 100, "marketPrice": 142.00}], connected=False)
    t = _trade("INTC", TradeDirection.LONG, fill=140.88, cur=140.88)
    n = _pm()._apply_ib_position_marks(_bot([t]))
    assert n == 0
