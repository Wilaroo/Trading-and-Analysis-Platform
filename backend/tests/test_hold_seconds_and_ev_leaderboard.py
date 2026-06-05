"""
v19.34.274 — tests for:
  1. hold_seconds instrumentation (BotTrade.to_dict + _compute_hold_seconds)
  2. /api/scanner/ev-leaderboard merge endpoint

Run from /app/backend:  python -m pytest tests/test_hold_seconds_and_ev_leaderboard.py -q
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.trading_bot_service import (  # noqa: E402
    BotTrade, TradeDirection, TradeStatus, _compute_hold_seconds,
)


def _make_trade(**overrides):
    base = dict(
        id="t1", symbol="AAPL", direction=TradeDirection.LONG,
        status=TradeStatus.CLOSED, setup_type="orb", timeframe="intraday",
        quality_score=80, quality_grade="A", entry_price=100.0,
        current_price=101.0, stop_price=99.0, target_prices=[102.0],
        shares=100, risk_amount=100.0, potential_reward=200.0,
        risk_reward_ratio=2.0,
    )
    base.update(overrides)
    return BotTrade(**base)


# ── _compute_hold_seconds ───────────────────────────────────────────────

def test_compute_hold_seconds_basic():
    entry = "2026-06-04T13:00:00+00:00"
    close = "2026-06-04T13:30:00+00:00"
    assert _compute_hold_seconds(entry, close) == 1800.0


def test_compute_hold_seconds_naive_assumed_utc():
    entry = "2026-06-04T13:00:00"
    close = "2026-06-04T13:00:45"
    assert _compute_hold_seconds(entry, close) == 45.0


def test_compute_hold_seconds_z_suffix():
    entry = "2026-06-04T13:00:00Z"
    close = "2026-06-04T13:01:00Z"
    assert _compute_hold_seconds(entry, close) == 60.0


def test_compute_hold_seconds_missing_returns_none():
    assert _compute_hold_seconds(None, "2026-06-04T13:00:00Z") is None
    assert _compute_hold_seconds("2026-06-04T13:00:00Z", None) is None


def test_compute_hold_seconds_negative_returns_none():
    entry = "2026-06-04T13:30:00Z"
    close = "2026-06-04T13:00:00Z"
    assert _compute_hold_seconds(entry, close) is None


def test_compute_hold_seconds_datetime_objects():
    a = datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc)
    b = a + timedelta(seconds=120)
    assert _compute_hold_seconds(a, b) == 120.0


# ── BotTrade.to_dict stamps hold_seconds ────────────────────────────────

def test_to_dict_stamps_hold_seconds_on_close():
    t = _make_trade(
        executed_at="2026-06-04T13:00:00+00:00",
        closed_at="2026-06-04T13:10:00+00:00",
    )
    assert t.to_dict()["hold_seconds"] == 600.0


def test_to_dict_falls_back_to_created_at():
    t = _make_trade(
        created_at="2026-06-04T13:00:00+00:00",
        executed_at=None,
        closed_at="2026-06-04T13:05:00+00:00",
    )
    assert t.to_dict()["hold_seconds"] == 300.0


def test_to_dict_open_trade_hold_seconds_none():
    t = _make_trade(
        status=TradeStatus.OPEN,
        executed_at="2026-06-04T13:00:00+00:00",
        closed_at=None,
    )
    assert t.to_dict()["hold_seconds"] is None


# ── ev-leaderboard merge logic (pure-function shape check) ──────────────

def test_ev_leaderboard_endpoint_importable_and_shape(monkeypatch):
    """Exercise the merge/sort logic without a live DB by stubbing the
    two services the endpoint pulls from."""
    import routers.scanner as scanner_mod
    import services.ev_tracking_service as ev_mod
    import services.setup_grading_service as grade_mod

    class _FakeEV:
        def get_ev_report(self):
            return {
                "orb": {"expected_value_r": 1.8, "win_rate": 0.55,
                        "ev_gate": "B_TRADE", "profit_factor": 1.9,
                        "total_trades": 22, "min_sample_reached": True,
                        "ev_trend": [1.2, 1.5, 1.8], "ev_improving": True,
                        "recommendation": "B TRADE"},
                "vwap_fade": {"expected_value_r": -0.3, "win_rate": 0.4,
                              "ev_gate": "F_TRADE", "profit_factor": 0.8,
                              "total_trades": 15, "min_sample_reached": True,
                              "ev_trend": [], "ev_improving": False,
                              "recommendation": "F TRADE"},
            }

    class _Grade:
        def __init__(self, setup_type, grade, avg_r, total_r, trades_count,
                     win_rate, avg_hold_seconds):
            self.setup_type = setup_type
            self.grade = grade
            self.avg_r = avg_r
            self.total_r = total_r
            self.trades_count = trades_count
            self.win_rate = win_rate
            self.avg_hold_seconds = avg_hold_seconds

    class _FakeGrading:
        def get_all_rolling_grades(self, days=30):
            return [
                _Grade("orb", "A", 1.1, 24.2, 22, 0.55, 900.0),
                _Grade("backside", "C", 0.1, 1.0, 12, 0.5, 1200.0),
            ]

    monkeypatch.setattr(ev_mod, "get_ev_service", lambda db=None: _FakeEV())
    monkeypatch.setattr(grade_mod, "get_setup_grading_service", lambda: _FakeGrading())

    res = scanner_mod.get_ev_leaderboard(days=30)
    assert res["success"] is True
    lb = res["leaderboard"]
    setups = [r["setup_type"] for r in lb]
    # orb (EV 1.8) leads; vwap_fade (EV -0.3) above backside (no EV).
    assert setups[0] == "orb"
    assert "backside" in setups
    # orb merged grade fields in.
    orb = next(r for r in lb if r["setup_type"] == "orb")
    assert orb["grade"] == "A"
    assert orb["avg_r"] == 1.1
    # grade-only setup has no EV but appears.
    backside = next(r for r in lb if r["setup_type"] == "backside")
    assert backside["expected_value_r"] is None
    assert backside["grade"] == "C"
