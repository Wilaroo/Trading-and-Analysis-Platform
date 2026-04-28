"""
Regression tests for `multiplier_analytics_service`.

Verifies that the bucketing logic correctly assigns each trade to the
"fired" vs "not_fired" cohort across the three liquidity-aware layers,
and that the per-cohort summary stats (mean R, win rate, total PnL,
count) compute correctly.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from services import multiplier_analytics_service as mas


def _trade(r=1.0, pnl=100.0, status="closed", days_ago=1, *,
           stop_guard_snapped=False, target_snap_snapped=False,
           vp_path=1.0):
    """Build a synthetic bot_trades document."""
    ec = {"multipliers": {"vp_path": vp_path}}
    if stop_guard_snapped:
        ec["multipliers"]["stop_guard"] = {"snapped": True, "level_kind": "HVN"}
    if target_snap_snapped:
        ec["multipliers"]["target_snap"] = [{"snapped": True, "level_kind": "R1"}]
    return {
        "id": f"trade_{r}_{pnl}_{stop_guard_snapped}",
        "symbol": "TEST",
        "status": status,
        "realized_r_multiple": r,
        "realized_pnl": pnl,
        "entry_context": ec,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }


def _make_db_with_trades(trades):
    """Mock that returns `trades` for any find() query."""
    db = MagicMock()
    coll = MagicMock()
    coll.find.return_value = iter(list(trades))
    db.__getitem__.return_value = coll
    return db


# ─── _bucket_summary ────────────────────────────────────────────────────

def test_bucket_summary_empty_cohort():
    s = mas._bucket_summary([])
    assert s["count"] == 0
    assert s["mean_r"] is None and s["win_rate"] is None


def test_bucket_summary_mean_and_win_rate():
    trades = [_trade(r=2.0), _trade(r=-1.0), _trade(r=1.5), _trade(r=-0.5)]
    s = mas._bucket_summary(trades)
    assert s["count"] == 4
    assert s["mean_r"] == round((2.0 - 1.0 + 1.5 - 0.5) / 4, 3)
    assert s["win_rate"] == round(2 / 4, 3)


def test_bucket_summary_handles_nan_r():
    trades = [_trade(r=2.0), _trade(r=float("nan")), _trade(r=1.0)]
    s = mas._bucket_summary(trades)
    # NaN row should be filtered out
    assert s["count"] == 3   # count is total trades
    assert s["mean_r"] == round(1.5, 3)


# ─── compute_multiplier_analytics ───────────────────────────────────────

def test_compute_multiplier_analytics_buckets_correctly():
    trades = [
        # Stop-guard fired, R=2.0
        _trade(r=2.0,  stop_guard_snapped=True),
        # Stop-guard fired, R=1.5
        _trade(r=1.5,  stop_guard_snapped=True),
        # No snap, R=-1.0
        _trade(r=-1.0),
        # Target-snap fired, R=2.5
        _trade(r=2.5,  target_snap_snapped=True),
        # VP path downsized, R=1.0
        _trade(r=1.0,  vp_path=0.7),
    ]
    db = _make_db_with_trades(trades)
    out = mas.compute_multiplier_analytics(db, days_back=30)
    assert out["total_trades"] == 5
    assert out["stop_guard"]["fired"]["count"] == 2
    assert out["stop_guard"]["not_fired"]["count"] == 3
    assert out["stop_guard"]["fired"]["mean_r"] == round((2.0 + 1.5) / 2, 3)
    assert out["target_snap"]["fired"]["count"] == 1
    assert out["target_snap"]["not_fired"]["count"] == 4
    assert out["vp_path"]["downsized"]["count"] == 1
    assert out["vp_path"]["full_size"]["count"] == 4


def test_compute_multiplier_analytics_handles_no_db():
    out = mas.compute_multiplier_analytics(None, days_back=30)
    assert out["error"] == "db not available"
    assert out["total_trades"] == 0


def test_compute_multiplier_analytics_handles_query_exception():
    db = MagicMock()
    coll = MagicMock()
    coll.find.side_effect = RuntimeError("mongo down")
    db.__getitem__.return_value = coll
    out = mas.compute_multiplier_analytics(db, days_back=30)
    assert "error" in out
    assert out["total_trades"] == 0


def test_compute_multiplier_analytics_skips_trades_missing_multipliers():
    """A trade with no `multipliers` key in entry_context should be
    bucketed as 'not fired' for every layer (no error)."""
    trades = [
        {"status": "closed", "realized_r_multiple": 1.0,
         "realized_pnl": 50.0, "entry_context": {},
         "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    ]
    db = _make_db_with_trades(trades)
    out = mas.compute_multiplier_analytics(db, days_back=30)
    assert out["total_trades"] == 1
    assert out["stop_guard"]["fired"]["count"] == 0
    assert out["stop_guard"]["not_fired"]["count"] == 1
    assert out["target_snap"]["fired"]["count"] == 0
    assert out["vp_path"]["downsized"]["count"] == 0


def test_compute_multiplier_analytics_skips_open_trades_when_only_closed():
    trades = [
        _trade(r=2.0, status="open", stop_guard_snapped=True),
        _trade(r=1.0, status="closed"),
    ]
    db = _make_db_with_trades(trades)
    out = mas.compute_multiplier_analytics(db, days_back=30, only_closed=True)
    # The mock doesn't actually filter by status — but the `query` dict
    # passed to find() must include status:closed. Verify via the mock.
    db.__getitem__.return_value.find.assert_called_once()
    args, _kw = db.__getitem__.return_value.find.call_args
    assert args[0].get("status") == "closed"
