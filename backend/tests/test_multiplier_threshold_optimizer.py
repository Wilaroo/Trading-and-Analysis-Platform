"""
Regression tests for `multiplier_threshold_optimizer`.

Verifies the optimizer correctly proposes step adjustments based on
cohort lift, respects the min-N gate, hard clamps, and persists+
invalidates the runtime cache only when changes are applied.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services import multiplier_threshold_optimizer as opt
from services import smart_levels_service as sls


# ─── Helpers ────────────────────────────────────────────────────────────

def _trade_with_layer(layer: str, r: float, fired: bool, *, days_ago: int = 1):
    """Build a synthetic bot_trades doc with the right multiplier shape."""
    ec = {"multipliers": {"vp_path": 1.0}}
    if layer == "stop_guard":
        if fired:
            ec["multipliers"]["stop_guard"] = {"snapped": True, "level_kind": "HVN"}
    elif layer == "target_snap":
        if fired:
            ec["multipliers"]["target_snap"] = [{"snapped": True}]
    elif layer == "vp_path":
        if fired:
            ec["multipliers"]["vp_path"] = 0.7
    return {
        "id": f"t_{layer}_{r}_{fired}",
        "status": "closed",
        "realized_r_multiple": r,
        "realized_pnl": r * 100,
        "entry_context": ec,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }


def _make_db_with(trades, history=None):
    db = MagicMock()
    coll_trades = MagicMock()
    coll_trades.find.return_value = iter(list(trades))
    coll_history = MagicMock()
    coll_history.insert_one = MagicMock()
    if history:
        coll_history.find_one.return_value = history
    else:
        coll_history.find_one.return_value = None

    def _getitem(name):
        if name == "bot_trades":
            return coll_trades
        if name == "multiplier_threshold_history":
            return coll_history
        return MagicMock()
    db.__getitem__.side_effect = _getitem
    return db, coll_history


# ─── _propose_step ──────────────────────────────────────────────────────

def test_propose_step_tightens_on_negative_lift():
    """`stop_min_level_strength` direction = +1: negative lift → push UP."""
    out = opt._propose_step("stop_min_level_strength", lift=-0.50, current=0.50)
    assert out["new"] > 0.50
    assert out["reason"] == "tighten_for_negative_lift"


def test_propose_step_loosens_on_positive_lift():
    """`stop_min_level_strength` direction = +1: positive lift → push DOWN."""
    out = opt._propose_step("stop_min_level_strength", lift=+0.50, current=0.50)
    assert out["new"] < 0.50
    assert out["reason"] == "loosen_for_positive_lift"


def test_propose_step_stays_within_band():
    out = opt._propose_step("stop_min_level_strength", lift=0.05, current=0.50)
    assert out["new"] == 0.50
    assert out["reason"] == "lift_within_band"


def test_propose_step_clamps_to_max():
    """Sustained negative lift can't push above hard max."""
    out = opt._propose_step("stop_min_level_strength", lift=-1.0, current=0.84)
    assert out["new"] <= 0.85   # hard max


def test_propose_step_clamps_to_min():
    out = opt._propose_step("stop_min_level_strength", lift=+1.0, current=0.31)
    assert out["new"] >= 0.30   # hard min


def test_propose_step_handles_missing_lift():
    out = opt._propose_step("stop_min_level_strength", lift=None, current=0.50)
    assert out["new"] == 0.50
    assert out["reason"] == "insufficient_data"


# ─── run_optimization end-to-end ────────────────────────────────────────

def test_run_optimization_tightens_threshold_on_negative_lift():
    """Stop-guard fires often but with bad mean R → optimizer tightens."""
    trades = []
    # 30 fired stop-guard trades, all losing -1R
    for _ in range(30):
        trades.append(_trade_with_layer("stop_guard", r=-1.0, fired=True))
    # 30 not-fired trades, all winning +1R
    for _ in range(30):
        trades.append(_trade_with_layer("stop_guard", r=+1.0, fired=False))
    db, hist_coll = _make_db_with(trades)

    out = opt.run_optimization(db, days_back=30, dry_run=True)
    sg_prop = out["proposals"]["stop_min_level_strength"]
    assert sg_prop["lift"] == -2.0
    assert sg_prop["proposed"] > sg_prop["current"]   # tightened
    assert sg_prop["reason"] == "tighten_for_negative_lift"


def test_run_optimization_skips_layers_with_insufficient_data():
    """Layers with fewer than _MIN_COHORT_N trades in either cohort
    should not produce a threshold change."""
    trades = [_trade_with_layer("stop_guard", r=2.0, fired=True)]   # 1 trade only
    db, _ = _make_db_with(trades)
    out = opt.run_optimization(db, days_back=30, dry_run=True)
    sg = out["proposals"]["stop_min_level_strength"]
    assert sg["proposed"] == sg["current"]
    assert sg["reason"] == "insufficient_data"
    # And the optimizer should note the skip
    assert any("insufficient data" in n for n in out["notes"])


def test_run_optimization_dry_run_does_not_persist():
    trades = [_trade_with_layer("stop_guard", r=-1.0, fired=True) for _ in range(30)]
    trades += [_trade_with_layer("stop_guard", r=1.0, fired=False) for _ in range(30)]
    db, hist_coll = _make_db_with(trades)
    out = opt.run_optimization(db, days_back=30, dry_run=True)
    assert out["dry_run"] is True
    assert out["applied"] is False
    hist_coll.insert_one.assert_not_called()


def test_run_optimization_persists_and_invalidates_cache_when_applied():
    trades = [_trade_with_layer("stop_guard", r=-1.0, fired=True) for _ in range(30)]
    trades += [_trade_with_layer("stop_guard", r=1.0, fired=False) for _ in range(30)]
    db, hist_coll = _make_db_with(trades)

    # Pre-populate the smart_levels cache so we can verify it gets blown.
    sls._THRESHOLD_CACHE.update({"ts": 9.99e9, "values": {"stop_min_level_strength": 0.99,
                                                          "target_snap_outside_pct": 0.99,
                                                          "path_vol_fat_pct": 0.99}})
    out = opt.run_optimization(db, days_back=30, dry_run=False)
    assert out["applied"] is True
    hist_coll.insert_one.assert_called_once()
    assert sls._THRESHOLD_CACHE["values"] is None   # cache invalidated


def test_run_optimization_no_change_does_not_persist():
    """When all proposed thresholds equal current, nothing is written."""
    # Empty trade set → all layers insufficient_data → no changes.
    db, hist_coll = _make_db_with([])
    out = opt.run_optimization(db, days_back=30, dry_run=False)
    assert out["applied"] is False
    hist_coll.insert_one.assert_not_called()


# ─── runtime cache helper ───────────────────────────────────────────────

def test_get_active_thresholds_returns_defaults_when_no_db():
    sls.invalidate_threshold_cache()
    out = sls._get_active_thresholds(None)
    assert out["stop_min_level_strength"] == sls._STOP_MIN_LEVEL_STRENGTH
    assert out["target_snap_outside_pct"] == sls._TARGET_SNAP_OUTSIDE_PCT
    assert out["path_vol_fat_pct"] == sls._PATH_VOL_FAT_PCT


def test_get_active_thresholds_reads_latest_applied_doc():
    sls.invalidate_threshold_cache()
    db = MagicMock()
    coll = MagicMock()
    coll.find_one.return_value = {
        "thresholds_after": {
            "stop_min_level_strength": 0.65,
            "target_snap_outside_pct": 0.018,
            "path_vol_fat_pct": 0.32,
        },
    }
    db.__getitem__.return_value = coll
    out = sls._get_active_thresholds(db)
    assert out["stop_min_level_strength"] == 0.65
    assert out["target_snap_outside_pct"] == 0.018
    assert out["path_vol_fat_pct"] == 0.32


def test_get_active_thresholds_falls_back_when_doc_missing():
    sls.invalidate_threshold_cache()
    db = MagicMock()
    coll = MagicMock()
    coll.find_one.return_value = None
    db.__getitem__.return_value = coll
    out = sls._get_active_thresholds(db)
    assert out["stop_min_level_strength"] == sls._STOP_MIN_LEVEL_STRENGTH


def test_get_active_thresholds_fails_open_on_db_exception():
    sls.invalidate_threshold_cache()
    db = MagicMock()
    coll = MagicMock()
    coll.find_one.side_effect = RuntimeError("mongo down")
    db.__getitem__.return_value = coll
    out = sls._get_active_thresholds(db)
    assert out["stop_min_level_strength"] == sls._STOP_MIN_LEVEL_STRENGTH
