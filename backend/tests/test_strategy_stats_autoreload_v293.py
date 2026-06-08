"""
v19.34.293 P2-A' — EV-gate freshness: strategy_stats auto-reload.

Audit Phase 2: the EV gate reads the scanner's in-memory `_strategy_stats`, which
was loaded only at startup (+ a manual endpoint). pnl_compute upserts realized EV to
the `strategy_stats` collection on every close, so intra-session the gate decided on
as-of-last-restart expectancy. `_load_strategy_stats` now refreshes per-key from the
DB, and the scan loop calls it on a throttle (SCANNER_STATS_RELOAD_SEC, default 300).

This test proves `_load_strategy_stats` REFRESHES in-memory stats from the DB
(repeated calls pick up new EV), which is the substance of the fix.
"""
import mongomock

from services.enhanced_scanner import EnhancedBackgroundScanner


def _scanner_with_db():
    # Bypass the heavy __init__; wire only what _load_strategy_stats needs.
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._strategy_stats = {}
    s.stats_collection = mongomock.MongoClient()["t"]["strategy_stats"]
    return s


def test_load_strategy_stats_hydrates_ev():
    s = _scanner_with_db()
    s.stats_collection.insert_one({
        "setup_type": "vwap_bounce", "alerts_triggered": 25, "alerts_won": 15,
        "win_rate": 0.6, "expected_value_r": 0.20, "r_outcomes": [0.5, -1, 1.2],
        "avg_win_r": 1.0, "avg_loss_r": 1.0,
    })
    s._load_strategy_stats()
    assert "vwap_bounce" in s._strategy_stats
    assert s._strategy_stats["vwap_bounce"].expected_value_r == 0.20
    assert s._strategy_stats["vwap_bounce"].alerts_triggered == 25


def test_reload_refreshes_changed_ev():
    s = _scanner_with_db()
    s.stats_collection.insert_one({
        "setup_type": "rubber_band", "alerts_triggered": 30, "expected_value_r": 0.05,
    })
    s._load_strategy_stats()
    assert s._strategy_stats["rubber_band"].expected_value_r == 0.05

    # Simulate pnl_compute upserting a new realized EV after fresh closes.
    s.stats_collection.update_one(
        {"setup_type": "rubber_band"},
        {"$set": {"expected_value_r": 0.18, "alerts_triggered": 42}},
    )
    # Before reload, in-memory is still stale (proves the gate WOULD use old EV).
    assert s._strategy_stats["rubber_band"].expected_value_r == 0.05
    # The periodic reload (what the scan loop now calls) refreshes it.
    s._load_strategy_stats()
    assert s._strategy_stats["rubber_band"].expected_value_r == 0.18
    assert s._strategy_stats["rubber_band"].alerts_triggered == 42


def test_reload_preserves_other_keys():
    s = _scanner_with_db()
    # A pre-registered in-memory-only setup not yet in the DB must survive a reload.
    from services.enhanced_scanner import StrategyStats
    s._strategy_stats["preregistered"] = StrategyStats(setup_type="preregistered")
    s.stats_collection.insert_one({"setup_type": "vwap_bounce", "expected_value_r": 0.1})
    s._load_strategy_stats()
    assert "preregistered" in s._strategy_stats  # not wiped
    assert "vwap_bounce" in s._strategy_stats
