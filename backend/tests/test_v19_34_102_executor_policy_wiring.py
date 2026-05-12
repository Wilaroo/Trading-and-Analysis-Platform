"""
Tests for v19.34.102 — executor reads order_policy_registry for parent
TIF + outside_rth (the bug: parent.time_in_force was hardcoded "DAY"
and parent.outside_rth was missing entirely, so a multi-day/swing/
investment/position parent LMT auto-cancelled at session close before
it could fill on a base-breakout setup).

Validates the bracket payload shape produced by
`TradeExecutorService._ib_bracket` for every trade style.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import patch, MagicMock

import pytest

from services.trade_executor_service import TradeExecutorService, ExecutorMode


# ─────────────────────────────────────────────────────────────────────
# Minimal stand-in for BotTrade (matches the attrs _ib_bracket reads)
# ─────────────────────────────────────────────────────────────────────
class _Direction:
    def __init__(self, value: str):
        self.value = value


@dataclass
class FakeTrade:
    id: str
    symbol: str
    direction: _Direction
    setup_type: str
    timeframe: str
    trade_style: str
    entry_price: float
    stop_price: float
    shares: int
    target_prices: List[float] = field(default_factory=list)


def _build_executor() -> TradeExecutorService:
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    return ex


def _capture_payload(monkeypatch):
    """Returns a (payload_holder, run) tuple. `run(trade)` invokes
    `_ib_bracket` with the queue/result calls stubbed and returns the
    captured payload."""
    captured = {}

    def fake_queue_order(payload):
        captured["payload"] = payload
        return "OID-TEST"

    def fake_get_order_result(order_id, timeout):
        return {
            "result": {
                "status": "working",
                "entry_order_id": 1, "stop_order_id": 2, "target_order_id": 3,
                "oca_group": "oca_TEST_abc",
            }
        }

    def fake_pusher_connected():
        return True

    monkeypatch.setattr("routers.ib.queue_order", fake_queue_order)
    monkeypatch.setattr("routers.ib.get_order_result", fake_get_order_result)
    monkeypatch.setattr("routers.ib.is_pusher_connected", fake_pusher_connected)

    async def _run(trade):
        ex = _build_executor()
        # Skip kill-switch + shadow-observe paths.
        ex._kill_switch_refusal = MagicMock(return_value=None)
        ex._maybe_schedule_shadow_observe = MagicMock(return_value=None)
        await ex._ib_bracket(trade)
        return captured["payload"]

    return _run


# ─────────────────────────────────────────────────────────────────────
class TestParentTifFromPolicy:
    def _mk(self, style: str, shares: int = 100) -> FakeTrade:
        return FakeTrade(
            id="T1", symbol="NVDA", direction=_Direction("long"),
            setup_type="ema_pullback", timeframe="5m", trade_style=style,
            entry_price=100.0, stop_price=95.0, shares=shares,
            target_prices=[],
        )

    def test_scalp_parent_is_day_inside_rth(self, monkeypatch):
        run = _capture_payload(monkeypatch)
        p = asyncio.run(run(self._mk("scalp")))
        assert p["parent"]["time_in_force"] == "DAY"
        assert p["parent"]["outside_rth"] is False
        assert p["stop"]["time_in_force"] == "DAY"
        assert p["target"]["time_in_force"] == "DAY"

    def test_intraday_parent_is_day_inside_rth(self, monkeypatch):
        run = _capture_payload(monkeypatch)
        p = asyncio.run(run(self._mk("intraday")))
        assert p["parent"]["time_in_force"] == "DAY"
        assert p["parent"]["outside_rth"] is False

    @pytest.mark.parametrize("style", ["multi_day", "swing", "investment", "position"])
    def test_long_horizon_parent_is_gtc_outside_rth(self, monkeypatch, style):
        run = _capture_payload(monkeypatch)
        p = asyncio.run(run(self._mk(style)))
        assert p["parent"]["time_in_force"] == "GTC", (
            f"{style} parent must be GTC so the entry order persists if "
            f"not filled in the first session"
        )
        assert p["parent"]["outside_rth"] is True
        assert p["stop"]["time_in_force"] == "GTC"
        assert p["stop"]["outside_rth"] is True
        assert p["target"]["time_in_force"] == "GTC"
        assert p["target"]["outside_rth"] is True

    def test_policy_audit_block_included(self, monkeypatch):
        run = _capture_payload(monkeypatch)
        p = asyncio.run(run(self._mk("position")))
        assert "policy" in p
        assert p["policy"]["style"] == "position"
        assert p["policy"]["stop_trail_anchor"] == "sma_150"
        assert p["policy"]["eod_sweep_eligible"] is False
        assert p["policy"]["horizon_label"]

    def test_unknown_style_falls_back_to_intraday_policy(self, monkeypatch):
        run = _capture_payload(monkeypatch)
        p = asyncio.run(run(self._mk("garbage_style")))
        # DEFAULT_POLICY = intraday → DAY, inside RTH
        assert p["parent"]["time_in_force"] == "DAY"
        assert p["parent"]["outside_rth"] is False
