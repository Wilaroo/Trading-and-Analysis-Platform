"""
v19.34.233 (Phase D) — GamePlan realized open-session edge ranker tests.

Pure unit tests: the ranker is fed synthetic `trade_outcomes` dicts so no
Mongo / IB / hardware is needed. Verifies:
  • EV-R ranking orders winners above losers
  • cold-start falls back to TQS ordering
  • shrinkage walk drops to a coarser bucket when the fine one is empty
  • the MIN_SAMPLES gate forces a TQS fallback on thin buckets
  • regime-bias normalization bridges the two regime vocabularies
  • gap_bucket / regime_bias helpers
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gameplan_edge_ranker import (  # noqa: E402
    GamePlanEdgeRanker, regime_bias, gap_bucket, normalize_setup,
)


def _o(setup, outcome, r, regime="strong_uptrend", catalyst="", gap=0.0):
    return {
        "setup_type": setup, "outcome": outcome, "actual_r": r,
        "context": {"market_regime": regime},
        "catalyst_tag": catalyst, "gap_pct": gap,
    }


def _stock(setup, tqs=60, catalyst="", gap=0.0):
    # mimic the prettified gameplan setup_type ("Gap And Go")
    pretty = setup.replace("_", " ").title()
    return {"symbol": setup.upper()[:4], "setup_type": pretty,
            "tqs_score": tqs, "catalyst_tag": catalyst, "gap_pct": gap}


# ── helpers ────────────────────────────────────────────────────────────────
def test_regime_bias_bridges_vocabularies():
    assert regime_bias("CONFIRMED_UP") == "up"
    assert regime_bias("strong_uptrend") == "up"
    assert regime_bias("CONFIRMED_DOWN") == "down"
    assert regime_bias("weak_downtrend") == "down"
    assert regime_bias("HOLD") == "range"
    assert regime_bias("range_bound") == "range"
    assert regime_bias("volatile") == "range"
    assert regime_bias(None) == "range"


def test_gap_bucket_thresholds():
    assert gap_bucket(0.4) == "flat"
    assert gap_bucket(2.0) == "small"
    assert gap_bucket(-2.0) == "small"   # uses abs
    assert gap_bucket(4.5) == "medium"
    assert gap_bucket(9.0) == "large"


def test_normalize_setup_roundtrips_pretty():
    assert normalize_setup("Gap And Go") == "gap_and_go"
    assert normalize_setup("vwap_continuation") == "vwap_continuation"


# ── ranking behavior ───────────────────────────────────────────────────────
def test_ev_r_ranking_winner_above_loser():
    outcomes = []
    # high-EV setup: 8 wins @ +2R, 2 losses @ -1R  -> EV ≈ +1.4R
    outcomes += [_o("gap_and_go", "won", 2.0) for _ in range(8)]
    outcomes += [_o("gap_and_go", "lost", -1.0) for _ in range(2)]
    # low-EV setup: 3 wins @ +1R, 7 losses @ -1R  -> EV ≈ -0.4R
    outcomes += [_o("bella_fade", "won", 1.0) for _ in range(3)]
    outcomes += [_o("bella_fade", "lost", -1.0) for _ in range(7)]

    ranker = GamePlanEdgeRanker(outcomes)
    stocks = [_stock("bella_fade", tqs=60), _stock("gap_and_go", tqs=60)]
    ranker.rank(stocks, "CONFIRMED_UP")

    by_setup = {normalize_setup(s["setup_type"]): s for s in stocks}
    assert by_setup["gap_and_go"]["edge_rank"] == 1
    assert by_setup["bella_fade"]["edge_rank"] == 2
    assert by_setup["gap_and_go"]["edge_source"] == "realized"
    assert by_setup["gap_and_go"]["edge_ev_r"] > by_setup["bella_fade"]["edge_ev_r"]
    # sorted list order matches rank
    assert normalize_setup(stocks[0]["setup_type"]) == "gap_and_go"


def test_cold_start_falls_back_to_tqs():
    ranker = GamePlanEdgeRanker([])  # no history
    stocks = [_stock("gap_and_go", tqs=50), _stock("range_break", tqs=85)]
    ranker.rank(stocks, "HOLD")

    top = stocks[0]
    assert normalize_setup(top["setup_type"]) == "range_break"
    assert top["edge_rank"] == 1
    assert all(s["edge_source"] == "tqs_fallback" for s in stocks)
    assert all(s["edge_ev_r"] is None for s in stocks)


def test_shrinkage_walk_to_coarser_bucket():
    # History exists only at (setup, regime) granularity (catalyst="" / gap 0),
    # but the live stock has catalyst=earnings + a medium gap, so its fine L4/L3
    # keys are empty and the lookup must shrink to L2.
    outcomes = [_o("hod_breakout", "won", 1.5) for _ in range(6)]
    outcomes += [_o("hod_breakout", "lost", -1.0) for _ in range(2)]
    ranker = GamePlanEdgeRanker(outcomes)

    stock = _stock("hod_breakout", tqs=60, catalyst="earnings", gap=4.5)
    ranker.rank([stock], "strong_uptrend")

    assert stock["edge_source"] == "realized"
    assert stock["edge_bucket_level"] == "L2"
    assert stock["edge_sample_size"] == 8


def test_min_samples_gate_forces_fallback():
    # Only 4 decided trades -> below MIN_SAMPLES at every level -> TQS fallback.
    outcomes = [_o("rubber_band", "won", 2.0) for _ in range(2)]
    outcomes += [_o("rubber_band", "lost", -1.0) for _ in range(2)]
    ranker = GamePlanEdgeRanker(outcomes)

    stock = _stock("rubber_band", tqs=70)
    ranker.rank([stock], "CONFIRMED_UP")
    assert stock["edge_source"] == "tqs_fallback"
    assert stock["edge_sample_size"] == 0


def test_regime_specificity_separates_buckets():
    # Setup is great in uptrends, terrible in downtrends. A down-regime gameplan
    # must pick up the down-regime (negative) edge, not the blended L1.
    outcomes = []
    outcomes += [_o("first_move_up", "won", 2.0, regime="strong_uptrend") for _ in range(7)]
    outcomes += [_o("first_move_up", "lost", -1.0, regime="strong_uptrend") for _ in range(1)]
    outcomes += [_o("first_move_up", "won", 1.0, regime="strong_downtrend") for _ in range(1)]
    outcomes += [_o("first_move_up", "lost", -1.0, regime="strong_downtrend") for _ in range(7)]
    ranker = GamePlanEdgeRanker(outcomes)

    up_stock = _stock("first_move_up", tqs=60)
    ranker.rank([up_stock], "CONFIRMED_UP")
    down_stock = _stock("first_move_up", tqs=60)
    ranker.rank([down_stock], "CONFIRMED_DOWN")

    assert up_stock["edge_ev_r"] > 0
    assert down_stock["edge_ev_r"] < 0
    assert up_stock["edge_score"] > down_stock["edge_score"]


def test_catalyst_type_fallback_from_fundamentals():
    # Historical rows pre-v232 carry catalyst in context.fundamentals only.
    outcomes = []
    for _ in range(6):
        d = _o("gap_and_go", "won", 2.0)
        d.pop("catalyst_tag")
        d["context"]["fundamentals"] = {"catalyst_type": "earnings", "has_catalyst": True}
        outcomes.append(d)
    for _ in range(2):
        d = _o("gap_and_go", "lost", -1.0)
        d.pop("catalyst_tag")
        d["context"]["fundamentals"] = {"catalyst_type": "earnings", "has_catalyst": True}
        outcomes.append(d)
    ranker = GamePlanEdgeRanker(outcomes)

    # Live earnings gapper, flat gap so L4=(setup,earnings,flat,up) matches.
    stock = _stock("gap_and_go", tqs=60, catalyst="earnings", gap=0.5)
    ranker.rank([stock], "CONFIRMED_UP")
    assert stock["edge_source"] == "realized"
    assert stock["edge_bucket_level"] == "L4"


def test_empty_stocks_is_noop():
    ranker = GamePlanEdgeRanker([])
    assert ranker.rank([], "HOLD") == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
