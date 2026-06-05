"""
v19.34.275 — tests for the strategy_stats hygiene rebuild.

Verifies that compute_clean_stats():
  • EXCLUDES reconciliation / phantom / imported artifact closes from setup
    win-rate / EV (the bug that poisoned the Smart Filter), and
  • computes win_rate / EV only from GENUINE strategy closes.

Run:  cd /app/backend && python -m pytest tests/test_strategy_stats_hygiene.py -q
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.rebuild_strategy_stats_clean import compute_clean_stats, _base_setup  # noqa: E402


def _trade(setup, close_reason, net_pnl, entered_by="bot_fired",
           risk=100.0, t="2026-06-05T14:00:00+00:00"):
    return {
        "setup_type": setup, "close_reason": close_reason, "net_pnl": net_pnl,
        "entered_by": entered_by, "risk_amount": risk, "direction": "long",
        "entry_price": 100.0, "exit_price": 100.0 + net_pnl / 1.0,
        "stop_price": 99.0, "target_prices": [102.0], "shares": 100,
        "quality_grade": "B", "closed_at": t,
    }


def test_artifact_setups_excluded():
    trades = [
        _trade("squeeze", "target", 150.0),
        _trade("squeeze", "stop_loss", -100.0),
        # artifact: phantom-swept squeeze must NOT count against squeeze
        _trade("squeeze", "wrong_direction_phantom_swept_v19_29", -50.0),
        # artifact: reconcile setup_type must not appear at all
        _trade("reconciled_excess_slice", "reconciled_v249", -30.0,
               entered_by="reconciled_excess_v19_34_15b"),
        _trade("reconciled_orphan", "reconcile_close", -20.0,
               entered_by="reconciled_external"),
    ]
    clean, excluded = compute_clean_stats(trades)

    assert set(clean.keys()) == {"squeeze"}, "only genuine setups survive"
    sq = clean["squeeze"]
    assert sq.alerts_triggered == 2  # the phantom one is dropped
    assert sq.alerts_won == 1 and sq.alerts_lost == 1
    assert abs(sq.win_rate - 0.5) < 1e-9
    # 3 artifacts excluded (1 phantom squeeze + 2 reconcile setups)
    assert sum(excluded.values()) == 3


def test_long_short_collapse_to_base():
    trades = [
        _trade("orb_long", "target", 200.0),
        _trade("orb_short", "stop_loss", -100.0),
    ]
    clean, _ = compute_clean_stats(trades)
    assert set(clean.keys()) == {"orb"}
    assert clean["orb"].alerts_triggered == 2


def test_realized_r_and_ev_signs():
    # 6 genuine trades so EV (needs >=5 r_outcomes) computes.
    trades = [_trade("backside", "target", 200.0) for _ in range(4)] + \
             [_trade("backside", "stop_loss", -100.0) for _ in range(2)]
    clean, _ = compute_clean_stats(trades)
    b = clean["backside"]
    assert b.alerts_triggered == 6
    assert abs(b.win_rate - (4 / 6)) < 1e-9
    # +2R wins, -1R losses, 66% win → strongly positive EV
    assert b.expected_value_r > 0


def test_base_setup_helper():
    assert _base_setup("vwap_fade_long") == "vwap_fade"
    assert _base_setup("rs_leader_break") == "rs_leader_break"
    assert _base_setup("") == ""
