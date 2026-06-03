"""
v19.34.237 (Phase D follow-up B) — direction-aware edge buckets + coverage audit.

A setup's realized edge differs long vs short, so `direction` is now a bucket
dimension. `coverage_summary()` reports how often each level is usable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gameplan_edge_ranker import (  # noqa: E402
    GamePlanEdgeRanker, normalize_direction, normalize_setup,
)


def _o(setup, outcome, r, direction="long", regime="strong_uptrend", catalyst="", gap=0.0):
    return {
        "setup_type": setup, "outcome": outcome, "actual_r": r,
        "direction": direction,
        "context": {"market_regime": regime},
        "catalyst_tag": catalyst, "gap_pct": gap,
    }


def _stock(setup, direction="long", tqs=60, catalyst="", gap=0.0):
    return {"symbol": setup.upper()[:4], "setup_type": setup.replace("_", " ").title(),
            "direction": direction, "tqs_score": tqs, "catalyst_tag": catalyst, "gap_pct": gap}


def test_normalize_direction():
    assert normalize_direction("short") == "short"
    assert normalize_direction("SELL") == "short"
    assert normalize_direction("long") == "long"
    assert normalize_direction("") == "long"      # unknown defaults long
    assert normalize_direction(None) == "long"


def test_direction_splits_edge():
    # Same setup: strong LONG edge, terrible SHORT edge.
    outcomes = []
    outcomes += [_o("orb", "won", 2.0, direction="long") for _ in range(7)]
    outcomes += [_o("orb", "lost", -1.0, direction="long") for _ in range(1)]
    outcomes += [_o("orb", "won", 1.0, direction="short") for _ in range(1)]
    outcomes += [_o("orb", "lost", -1.0, direction="short") for _ in range(7)]
    ranker = GamePlanEdgeRanker(outcomes)

    long_stock = _stock("orb", direction="long", tqs=60)
    short_stock = _stock("orb", direction="short", tqs=60)
    ranker.rank([long_stock], "CONFIRMED_UP")
    ranker.rank([short_stock], "CONFIRMED_UP")

    assert long_stock["edge_source"] == "realized"
    assert short_stock["edge_source"] == "realized"
    assert long_stock["edge_ev_r"] > 0
    assert short_stock["edge_ev_r"] < 0
    assert long_stock["edge_score"] > short_stock["edge_score"]


def test_long_outcomes_do_not_leak_into_short_bucket():
    # Only LONG history exists; a SHORT stock must NOT inherit the long edge.
    outcomes = [_o("vwap_reclaim", "won", 2.0, direction="long") for _ in range(8)]
    ranker = GamePlanEdgeRanker(outcomes)
    short_stock = _stock("vwap_reclaim", direction="short", tqs=55)
    ranker.rank([short_stock], "CONFIRMED_UP")
    assert short_stock["edge_source"] == "tqs_fallback"  # no short history -> cold start


def test_coverage_summary_counts_usable_buckets():
    outcomes = [_o("orb", "won", 1.5, direction="long") for _ in range(6)]
    outcomes += [_o("orb", "lost", -1.0, direction="long") for _ in range(2)]  # 8 decided
    ranker = GamePlanEdgeRanker(outcomes)
    cov = ranker.coverage_summary()
    # All four levels (L1..L4) get the single long/orb bucket, each with 8 >= MIN_SAMPLES.
    for lvl in ("L1", "L2", "L3", "L4"):
        assert cov[lvl]["total"] >= 1
        assert cov[lvl]["usable"] >= 1


def test_thin_bucket_not_usable_in_coverage():
    outcomes = [_o("orb", "won", 1.0, direction="long") for _ in range(2)]  # only 2 decided
    ranker = GamePlanEdgeRanker(outcomes)
    cov = ranker.coverage_summary()
    assert cov["L1"]["total"] == 1 and cov["L1"]["usable"] == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
