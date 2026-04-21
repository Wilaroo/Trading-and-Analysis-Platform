"""Unit tests for TradeAutopsy.summarize_trade_outcome (2026-04-21).

The full `autopsy()` method requires Mongo — tested by integration elsewhere.
Here we lock down the pure math/verdict logic.
"""
from services.trade_autopsy import summarize_trade_outcome


def test_long_winner():
    t = {"entry_price": 100, "stop_price": 98, "exit_price": 104, "direction": "long"}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "win"
    assert r["realized_R"] == 2.0


def test_short_loser_stop_honored():
    t = {"entry_price": 100, "stop_price": 102, "exit_price": 102, "direction": "short",
         "stop_honored": True}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "loss"
    assert r["realized_R"] == -1.0
    assert r["slippage_R"] is None  # stop honored → no slippage


def test_short_loser_stop_not_honored_yields_slippage():
    """USO-style: short 108.28, stop 108.31 (risk 0.03), exit 116.12 → R ≈ -261, slippage ≈ 260.33."""
    t = {"entry_price": 108.28, "stop_price": 108.31, "exit_price": 116.12,
         "direction": "short", "stop_honored": False}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "loss"
    assert r["realized_R"] < -100
    assert r["slippage_R"] is not None and r["slippage_R"] > 100


def test_scratch_when_near_zero():
    t = {"entry_price": 100, "stop_price": 99, "exit_price": 100.05, "direction": "long"}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "scratch"


def test_missing_inputs_returns_unknown():
    r = summarize_trade_outcome({"direction": "long"})
    assert r["verdict"] == "unknown"
    assert r["realized_R"] is None


def test_pnl_only_fallback_when_exit_price_missing():
    """imported_from_ib trades can have exit_price=0 but realized_pnl set.
    Autopsy must still surface a verdict instead of 'unknown'."""
    t = {"entry_price": 7.305, "stop_price": 7.0, "exit_price": 0,
         "direction": "long", "realized_pnl": -7294.18}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "loss"
    assert r["pnl_usd"] == -7294.18


def test_pnl_only_positive_is_win():
    t = {"exit_price": 0, "realized_pnl": 1250.50}
    r = summarize_trade_outcome(t)
    assert r["verdict"] == "win"


def test_uses_explicit_r_multiple_when_present():
    """If r_multiple is already on the trade doc, use it directly."""
    t = {"entry_price": 100, "stop_price": 98, "exit_price": 104,
         "direction": "long", "r_multiple": -0.5}
    r = summarize_trade_outcome(t)
    assert r["realized_R"] == -0.5
    assert r["verdict"] == "loss"
