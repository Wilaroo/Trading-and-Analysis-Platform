"""
v19.34.27 — BOT_ORDER_PATH=shadow mode tests for the trade executor.

Pre-fix the Direct IB service (clientId=11) was built (v19.34.25) but
not wired into the executor. Post-fix `BOT_ORDER_PATH=shadow` enables
passive observation: after every successful pusher submit, an async
task queries the direct IB socket's positions and warns on divergence.
Counters track agreements + divergences for UI surfacing.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.trade_executor_service import TradeExecutorService


def _reset_counters():
    for k in TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS:
        TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS[k] = 0


def _mk_trade(symbol="UPS", direction="long", shares=100, trade_id="t1"):
    t = MagicMock()
    t.id = trade_id
    t.symbol = symbol
    t.shares = shares
    t.direction = MagicMock()
    t.direction.value = direction
    return t


def test_order_path_default_pusher(monkeypatch):
    monkeypatch.delenv("BOT_ORDER_PATH", raising=False)
    assert TradeExecutorService()._order_path_mode() == "pusher"


def test_order_path_invalid_falls_back_to_pusher(monkeypatch):
    monkeypatch.setenv("BOT_ORDER_PATH", "garbage")
    assert TradeExecutorService()._order_path_mode() == "pusher"


def test_order_path_recognized_modes(monkeypatch):
    for mode in ("pusher", "shadow", "direct", "SHADOW", " shadow "):
        monkeypatch.setenv("BOT_ORDER_PATH", mode)
        assert TradeExecutorService()._order_path_mode() == mode.strip().lower()


def test_shadow_stats_returns_snapshot(monkeypatch):
    _reset_counters()
    monkeypatch.setenv("BOT_ORDER_PATH", "shadow")
    stats = TradeExecutorService.shadow_stats()
    assert stats["order_path"] == "shadow"
    assert "missing_at_ib" in stats["counters"]
    assert "observed_ok" in stats["counters"]


def test_maybe_schedule_skips_when_pusher_mode(monkeypatch):
    _reset_counters()
    monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
    ex = TradeExecutorService()
    trade = _mk_trade()
    # Schedule must be a no-op in pusher mode — no asyncio task created,
    # no exception raised.
    ex._maybe_schedule_shadow_observe(
        trade, {"success": True}, action="BUY", intent="bracket",
        expected_signed_delta=100,
    )
    # No counter movement expected (no shadow ran).
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["observed_ok"] == 0


def test_maybe_schedule_skips_when_primary_failed(monkeypatch):
    _reset_counters()
    monkeypatch.setenv("BOT_ORDER_PATH", "shadow")
    ex = TradeExecutorService()
    trade = _mk_trade()
    ex._maybe_schedule_shadow_observe(
        trade, {"success": False, "error": "rejected"},
        action="BUY", intent="bracket", expected_signed_delta=100,
    )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["observed_ok"] == 0


@pytest.mark.asyncio
async def test_shadow_observe_socket_down_bumps_skipped(monkeypatch):
    _reset_counters()
    monkeypatch.setattr(TradeExecutorService, "_SHADOW_OBSERVE_DELAY_S", 0)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = False
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        ex = TradeExecutorService()
        await ex._shadow_observe(
            symbol="UPS", trade_id="t1", action="BUY", intent="bracket",
            expected_signed_delta=100,
            primary_result={"success": True, "status": "filled"},
        )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["skipped_socket_down"] == 1


@pytest.mark.asyncio
async def test_shadow_observe_auth_lost_bumps_counter(monkeypatch):
    _reset_counters()
    monkeypatch.setattr(TradeExecutorService, "_SHADOW_OBSERVE_DELAY_S", 0)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.is_authorized_to_trade.return_value = False
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        ex = TradeExecutorService()
        await ex._shadow_observe(
            symbol="UPS", trade_id="t1", action="BUY", intent="bracket",
            expected_signed_delta=100,
            primary_result={"success": True, "status": "filled"},
        )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["auth_lost"] == 1


@pytest.mark.asyncio
async def test_shadow_observe_divergence_when_ib_zero(monkeypatch):
    """The v19.34.15a fingerprint: pusher said filled, IB shows 0."""
    _reset_counters()
    monkeypatch.setattr(TradeExecutorService, "_SHADOW_OBSERVE_DELAY_S", 0)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.is_authorized_to_trade.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "AAPL", "position": 50.0},  # no UPS
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        ex = TradeExecutorService()
        await ex._shadow_observe(
            symbol="UPS", trade_id="t1", action="BUY", intent="bracket",
            expected_signed_delta=100,
            primary_result={"success": True, "status": "filled"},
        )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["missing_at_ib"] == 1


@pytest.mark.asyncio
async def test_shadow_observe_direction_mismatch(monkeypatch):
    _reset_counters()
    monkeypatch.setattr(TradeExecutorService, "_SHADOW_OBSERVE_DELAY_S", 0)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.is_authorized_to_trade.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "UPS", "position": -100.0},  # short, but BUY went long
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        ex = TradeExecutorService()
        await ex._shadow_observe(
            symbol="UPS", trade_id="t1", action="BUY", intent="bracket",
            expected_signed_delta=100,
            primary_result={"success": True, "status": "filled"},
        )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["direction_mismatch"] == 1


@pytest.mark.asyncio
async def test_shadow_observe_agrees_bumps_observed_ok(monkeypatch):
    _reset_counters()
    monkeypatch.setattr(TradeExecutorService, "_SHADOW_OBSERVE_DELAY_S", 0)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.is_authorized_to_trade.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "UPS", "position": 100.0},  # matches expected
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        ex = TradeExecutorService()
        await ex._shadow_observe(
            symbol="UPS", trade_id="t1", action="BUY", intent="bracket",
            expected_signed_delta=100,
            primary_result={"success": True, "status": "filled"},
        )
    assert TradeExecutorService._SHADOW_DIVERGENCE_COUNTERS["observed_ok"] == 1
