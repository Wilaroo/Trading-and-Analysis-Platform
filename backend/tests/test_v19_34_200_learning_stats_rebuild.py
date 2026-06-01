"""
v19.34.200 — learning_stats rebuild aggregation.

`_compute_learning_stats` is the pure-dict aggregator shared by the nightly
scheduled rebuild (`rebuild_learning_stats_from_all_outcomes`) and the manual
backfill script. It reads outcome dicts directly because the stored docs are
flatter than `TradeOutcome.from_dict` expects (which silently zeroes stats).
"""
from services.learning_loop_service import _compute_learning_stats


def _o(setup, outcome, r, pnl):
    return {"setup_type": setup, "outcome": outcome, "actual_r": r, "pnl": pnl}


def test_basic_win_rate_and_ev():
    outs = [
        _o("squeeze", "won", 2.0, 200),
        _o("squeeze", "won", 1.0, 100),
        _o("squeeze", "lost", -1.0, -100),
    ]
    s = _compute_learning_stats("squeeze", outs)
    assert s["total_trades"] == 3
    assert s["wins"] == 2 and s["losses"] == 1
    assert round(s["win_rate"], 3) == 0.667
    assert s["context_key"] == "squeeze" and s["setup_type"] == "squeeze"
    # PF = 300 / 100 = 3.0
    assert s["profit_factor"] == 3.0
    # EV = 0.667*1.5 - 0.333*1.0 = 0.667
    assert round(s["expected_value_r"], 2) == 0.67


def test_all_losses():
    outs = [_o("daily_breakout", "lost", -1.0, -100) for _ in range(5)]
    s = _compute_learning_stats("daily_breakout", outs)
    assert s["total_trades"] == 5
    assert s["win_rate"] == 0.0
    assert s["profit_factor"] == 0.0
    assert s["expected_value_r"] == -1.0  # win_rate 0 → -avg_loss_r(1.0)


def test_breakeven_excluded_from_winrate_denominator():
    outs = [
        _o("x", "won", 1.0, 100),
        _o("x", "lost", -1.0, -100),
        _o("x", "breakeven", 0.0, 0),
    ]
    s = _compute_learning_stats("x", outs)
    assert s["total_trades"] == 3
    assert s["breakeven"] == 1
    assert s["win_rate"] == 0.5  # 1 win / (1 win + 1 loss); breakeven excluded


def test_empty():
    s = _compute_learning_stats("x", [])
    assert s["total_trades"] == 0
    assert s["win_rate"] == 0.0
    assert s["avg_r_per_trade"] == 0.0


def test_handles_missing_or_bad_fields():
    outs = [
        {"setup_type": "y", "outcome": "won"},            # no actual_r/pnl
        {"setup_type": "y", "outcome": "lost", "actual_r": "bad", "pnl": None},
    ]
    s = _compute_learning_stats("y", outs)
    assert s["total_trades"] == 2
    assert s["win_rate"] == 0.5
