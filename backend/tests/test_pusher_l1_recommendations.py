"""
Regression tests for `services.symbol_universe.get_pusher_l1_recommendations`
— the engine behind the env-var-driven L1 expansion shipped 2026-04-29
(afternoon-8). Operator approved expanding the pusher's hardcoded 14
quote-subs to up to 80 to give live freshness to a wider intraday
tier (within IB Gateway paper's 100-line streaming ceiling).

Asserts:
  - Top-N by avg_dollar_volume drives the bulk of the list
  - Always-on ETFs (sector + size + volatility) are appended, not lost
  - Operator-pinned `extra_priority` symbols always make the cut
  - `unqualifiable=True` symbols are excluded
  - `max_total` hard cap is honored
  - Endpoint returns a sane payload shape
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
import asyncio

import mongomock
import pytest


@pytest.fixture
def db_with_universe():
    """Mongomock seeded with a realistic-ish symbol_adv_cache."""
    db = mongomock.MongoClient().db
    rows = [
        # Mega-caps (very high ADV)
        {"symbol": "AAPL", "avg_dollar_volume": 5_000_000_000, "tier": "intraday"},
        {"symbol": "MSFT", "avg_dollar_volume": 4_500_000_000, "tier": "intraday"},
        {"symbol": "NVDA", "avg_dollar_volume": 4_200_000_000, "tier": "intraday"},
        {"symbol": "TSLA", "avg_dollar_volume": 3_800_000_000, "tier": "intraday"},
        {"symbol": "AMZN", "avg_dollar_volume": 3_500_000_000, "tier": "intraday"},
        {"symbol": "META", "avg_dollar_volume": 3_200_000_000, "tier": "intraday"},
        {"symbol": "GOOGL", "avg_dollar_volume": 2_800_000_000, "tier": "intraday"},
        # Mid-tier
        {"symbol": "AMD", "avg_dollar_volume": 1_800_000_000, "tier": "intraday"},
        {"symbol": "PLTR", "avg_dollar_volume": 900_000_000, "tier": "intraday"},
        # Sector ETFs at various ranks
        {"symbol": "XLK", "avg_dollar_volume": 1_200_000_000, "tier": "intraday"},
        {"symbol": "XLE", "avg_dollar_volume": 800_000_000, "tier": "intraday"},
        # Already-on context tape
        {"symbol": "SPY", "avg_dollar_volume": 35_000_000_000, "tier": "intraday"},
        {"symbol": "QQQ", "avg_dollar_volume": 12_000_000_000, "tier": "intraday"},
        {"symbol": "IWM", "avg_dollar_volume": 4_000_000_000, "tier": "intraday"},
        # Low-tier (won't make top 60 but shouldn't error)
        {"symbol": "ZZZZ", "avg_dollar_volume": 1_000_000, "tier": "investment"},
        # Unqualifiable — must be excluded
        {"symbol": "DEAD", "avg_dollar_volume": 9_000_000_000,
         "tier": "intraday", "unqualifiable": True},
    ]
    db["symbol_adv_cache"].insert_many(rows)
    return db


def test_top_n_drives_bulk_of_list(db_with_universe):
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(db_with_universe, top_n=5, max_total=80)
    assert rec["success"] is True
    # SPY first (highest ADV), then mega caps in order
    top5 = rec["top_n_by_adv"]
    assert top5[0] == "SPY"
    assert top5[1] == "QQQ"
    assert top5[2] == "AAPL"
    # All 5 made it into the final list
    for sym in top5:
        assert sym in rec["symbols"]


def test_etfs_always_included_even_when_outside_top_n(db_with_universe):
    """Even with top_n=2, the always-on ETFs (XLE, XLK, sectors) must
    end up in the list since they're appended after the top-N pass."""
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(db_with_universe, top_n=2, max_total=80)

    # Only top 2 by ADV (SPY, QQQ) made the ADV slice
    assert len(rec["top_n_by_adv"]) == 2
    # But sector ETFs are pulled in via the always-on list
    assert "XLE" in rec["symbols"]
    assert "XLK" in rec["symbols"]
    assert "XLF" in rec["symbols"]  # not in db but always-on default
    assert "VIX" in rec["symbols"]


def test_unqualifiable_symbols_excluded(db_with_universe):
    """`DEAD` has the highest ADV in the cache (excluding SPY/QQQ) but
    is marked unqualifiable=True — must NOT appear in the list."""
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(db_with_universe, top_n=80, max_total=80)
    assert "DEAD" not in rec["symbols"]
    assert "DEAD" not in rec["top_n_by_adv"]


def test_extra_priority_pins_overrides_top_n(db_with_universe):
    """Operator-pinned symbols always make the cut, even if they would
    otherwise rank too low for top-N inclusion."""
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(
        db_with_universe,
        top_n=5,
        extra_priority=["ZZZZ"],  # tiny ADV, would never make top 5
        max_total=80,
    )
    assert "ZZZZ" in rec["symbols"]
    # Pinned symbol comes first (priority pins inserted before top-N)
    assert rec["symbols"][0] == "ZZZZ"


def test_max_total_hard_cap_honored(db_with_universe):
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(db_with_universe, top_n=80, max_total=10)
    assert len(rec["symbols"]) == 10


def test_dedup_across_priority_topn_etfs(db_with_universe):
    """SPY appears in priority pins, top-N, AND always-on ETFs.
    Must appear exactly ONCE in the output."""
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(
        db_with_universe,
        top_n=10,
        extra_priority=["SPY"],
    )
    assert rec["symbols"].count("SPY") == 1


def test_handles_empty_db_gracefully():
    """Empty symbol_adv_cache → still returns the always-on ETF list."""
    from services.symbol_universe import get_pusher_l1_recommendations
    db = mongomock.MongoClient().db
    rec = get_pusher_l1_recommendations(db, top_n=60)
    assert rec["success"] is True
    assert rec["count"] > 0  # ETFs alone
    assert "SPY" in rec["symbols"]
    assert "XLE" in rec["symbols"]


def test_handles_db_none_safely():
    from services.symbol_universe import get_pusher_l1_recommendations
    rec = get_pusher_l1_recommendations(None, top_n=60)
    assert rec["success"] is False
    assert rec["error"] == "db_unavailable"
    assert rec["symbols"] == []


# ─── Endpoint integration test ──────────────────────────────────────

def test_router_endpoint_shape(db_with_universe):
    """Backfill router endpoint passes the args through correctly and
    returns the recommendation payload."""
    import services.ib_historical_collector as col_mod
    from routers import backfill_router

    class _FakeCollector:
        _db = db_with_universe

    with patch.object(col_mod, "get_ib_collector", return_value=_FakeCollector()), \
         patch("routers.backfill_router.get_ib_collector",
               return_value=_FakeCollector()):
        resp = asyncio.get_event_loop().run_until_complete(
            backfill_router.backfill_pusher_l1_recommendations(
                top_n=5, max_total=20
            )
        )

    assert resp["success"] is True
    assert resp["count"] <= 20
    assert "SPY" in resp["symbols"]
    assert "iso_ts" in resp
