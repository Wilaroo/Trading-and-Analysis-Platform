"""
v19.34.262 — bot-edge attribution helper tests.

Validates services.trade_outcome_hygiene.is_adopted_entry() — the single
shared definition used by the Mission Control P&L split and the offline
audit so the two always agree.
"""
from services.trade_outcome_hygiene import is_adopted_entry


def test_bot_fired_is_not_adopted():
    assert is_adopted_entry("bot_fired", "bot", "target_hit") is False
    assert is_adopted_entry("", "", "") is False  # legacy/unstamped -> treated as bot
    assert is_adopted_entry("strategy_entry_v123", "bot", "stop_loss") is False


def test_reconciled_and_external_are_adopted():
    assert is_adopted_entry("reconciled_external", "reconciler", "") is True
    assert is_adopted_entry("reconciled_excess_v19_34_15b", "", "") is True
    assert is_adopted_entry("bot_fired", "", "external_close_v19_34_15b") is True
    assert is_adopted_entry("", "ib_only", "") is True
    assert is_adopted_entry("imported_position", "", "") is True
    assert is_adopted_entry("", "", "operator_external_flatten") is True


def test_case_insensitive_and_none_safe():
    assert is_adopted_entry("RECONCILED_External", None, None) is True
    assert is_adopted_entry(None, None, None) is False


def test_realized_split_math():
    """End-to-end bucketing math the positions endpoint performs."""
    rows = [
        {"entered_by": "bot_fired", "source": "bot", "close_reason": "target_hit", "net_pnl": 100.0},
        {"entered_by": "bot_fired", "source": "bot", "close_reason": "stop_loss", "net_pnl": -40.0},
        {"entered_by": "reconciled_external", "source": "reconciler", "close_reason": "manual", "net_pnl": 5000.0},
        {"entered_by": "", "source": "ib_only", "close_reason": "external_close_v19_34_15b", "net_pnl": 250.0},
    ]
    bot = adopted = 0.0
    for t in rows:
        if is_adopted_entry(t["entered_by"], t["source"], t["close_reason"]):
            adopted += t["net_pnl"]
        else:
            bot += t["net_pnl"]
    assert bot == 60.0          # 100 - 40 (the bot's own edge)
    assert adopted == 5250.0    # 5000 + 250 (adopted positions)
