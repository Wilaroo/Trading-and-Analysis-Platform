"""Regression: v19.34.57 — Stamp `trade_type` at BotTrade construction."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_min_trade(trade_type: str | None = None):
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    kwargs = dict(
        id="t-test", symbol="AAPL",
        direction=TradeDirection.LONG, status=TradeStatus.PENDING,
        setup_type="VWAP", timeframe="5m",
        quality_score=80, quality_grade="A",
        entry_price=100.0, current_price=100.0, stop_price=99.0,
        target_prices=[101.0, 102.0],
        shares=10, risk_amount=10.0, potential_reward=20.0, risk_reward_ratio=2.0,
    )
    if trade_type is not None:
        kwargs["trade_type"] = trade_type
    return BotTrade(**kwargs)


def test_post_init_stamps_paper_from_env(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    assert _build_min_trade().trade_type == "paper"


def test_post_init_stamps_live_from_env(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "live")
    assert _build_min_trade().trade_type == "live"


def test_post_init_env_unset_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("IB_ACCOUNT_ACTIVE", raising=False)
    assert _build_min_trade().trade_type == "paper"


def test_post_init_preserves_explicit_trade_type(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    assert _build_min_trade(trade_type="live").trade_type == "live"


def test_post_init_falls_back_to_unknown_on_account_guard_exception():
    with patch("services.account_guard.load_account_expectation",
               side_effect=RuntimeError("simulated env corruption")):
        assert _build_min_trade().trade_type == "unknown"


def test_post_init_invalid_env_value_normalizes_to_paper(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "garbage_mode")
    assert _build_min_trade().trade_type == "paper"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
