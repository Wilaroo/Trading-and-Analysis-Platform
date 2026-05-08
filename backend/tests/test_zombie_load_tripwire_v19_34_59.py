"""
v19.34.59 — Boot-time zombie tripwire + diagnostic endpoint tests.

Covers:
  * `bot_persistence.dict_to_trade` flags + logs zombies on load.
  * `bot_persistence.dict_to_trade` does NOT flag healthy / closed trades.
  * Zombie-tripwire is robust to malformed status fields.
"""
from __future__ import annotations

import logging

from services.bot_persistence import BotPersistence


def _zombie_doc(**overrides):
    base = {
        "id": "zombie-test-1",
        "symbol": "TEST",
        "direction": "long",
        "status": "open",
        "shares": 100,
        "original_shares": 100,
        "remaining_shares": 0,
        "fill_price": 50.0,
        "entered_by": "bot_fired",
        "trade_style": "trade_2_hold",
        "setup_type": "test",
        "timeframe": "intraday",
        "quality_score": 80,
        "quality_grade": "B",
        "entry_price": 50.0,
        "current_price": 51.0,
        "stop_price": 49.0,
        "target_prices": [52.0],
        "risk_amount": 100.0,
        "potential_reward": 200.0,
        "risk_reward_ratio": 2.0,
    }
    base.update(overrides)
    return base


def test_zombie_load_is_flagged_and_logged(caplog):
    caplog.set_level(logging.ERROR)
    trade = BotPersistence.dict_to_trade(_zombie_doc())
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is True
    matching = [r for r in caplog.records if "ZOMBIE-LOAD" in r.getMessage()]
    assert matching, "expected a v19.34.59 ZOMBIE-LOAD log line"
    assert "TEST" in matching[0].getMessage()


def test_healthy_open_trade_not_flagged():
    trade = BotPersistence.dict_to_trade(_zombie_doc(remaining_shares=100))
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is False


def test_closed_trade_not_flagged():
    trade = BotPersistence.dict_to_trade(
        _zombie_doc(status="closed", remaining_shares=0)
    )
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is False


def test_open_with_zero_original_not_flagged():
    """Edge case: malformed pre-fill record with shares=0. Don't flag —
    that's a different bug class (pending fill) and would generate noise."""
    trade = BotPersistence.dict_to_trade(
        _zombie_doc(remaining_shares=0, original_shares=0, shares=0)
    )
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is False


def test_short_zombie_also_flagged():
    trade = BotPersistence.dict_to_trade(_zombie_doc(direction="short"))
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is True


def test_pending_status_not_flagged():
    trade = BotPersistence.dict_to_trade(
        _zombie_doc(status="pending", remaining_shares=0)
    )
    assert trade is not None
    assert getattr(trade, "_loaded_as_zombie_v19_34_59", False) is False
