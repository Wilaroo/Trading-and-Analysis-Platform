"""
Regression tests for IBHistoricalCollector.smart_backfill

Covers the bug class that caused the last fork to crash:
  • class attributes (TIMEFRAMES_BY_TIER, MAX_DAYS_PER_REQUEST, DURATION_STRING)
    must live INSIDE the class (IndentationError if not).
  • _smart_backfill_sync / smart_backfill must be bound methods.
  • A dry_run against an empty DB must NOT block the event loop and must
    return a deterministic summary shape.

These tests run in-process against a fresh mongomock instance, so they do
NOT require IB Gateway, user's DGX Spark, or any network.
"""

import asyncio

import pytest


def _collector_with_empty_db():
    """Build a collector wired to an isolated mongomock DB."""
    import mongomock
    from services.ib_historical_collector import IBHistoricalCollector

    client = mongomock.MongoClient()
    db = client["test_smart_backfill"]
    c = IBHistoricalCollector()
    c.set_db(db)
    return c, db


def test_class_attributes_inside_class():
    """Regression: the smart_backfill tables were previously placed OUTSIDE
    the class definition — caused IndentationError on import."""
    from services.ib_historical_collector import IBHistoricalCollector

    assert hasattr(IBHistoricalCollector, "TIMEFRAMES_BY_TIER")
    assert hasattr(IBHistoricalCollector, "MAX_DAYS_PER_REQUEST")
    assert hasattr(IBHistoricalCollector, "DURATION_STRING")

    # Every tier's timeframes must appear in the per-bar-size durations.
    for tier, bars in IBHistoricalCollector.TIMEFRAMES_BY_TIER.items():
        for b in bars:
            assert b in IBHistoricalCollector.MAX_DAYS_PER_REQUEST, (tier, b)
            assert b in IBHistoricalCollector.DURATION_STRING, (tier, b)


def test_smart_backfill_methods_are_bound():
    from services.ib_historical_collector import IBHistoricalCollector
    c = IBHistoricalCollector()
    assert callable(getattr(c, "_smart_backfill_sync", None))
    assert callable(getattr(c, "smart_backfill", None))


def test_smart_backfill_empty_db_dry_run():
    c, _db = _collector_with_empty_db()
    res = asyncio.run(c.smart_backfill(dry_run=True))
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["tier_counts"] == {"intraday": 0, "swing": 0, "investment": 0}
    assert res["would_queue"] == 0
    assert res["skipped_fresh"] == 0
    assert res["skipped_already_queued"] == 0
    assert res["by_bar_size"] == {}


def test_smart_backfill_queues_for_new_symbol():
    """With a single intraday-tier symbol and no existing bars, smart_backfill
    must plan one chained request per timeframe for that tier."""
    c, db = _collector_with_empty_db()

    # Seed ADV cache: one symbol firmly in the intraday tier.
    db["symbol_adv_cache"].insert_one({
        "symbol": "TEST",
        "avg_volume": 10_000_000,
        "avg_dollar_volume": 1_000_000_000,
        "tier": "intraday",
    })

    res = asyncio.run(c.smart_backfill(dry_run=True, tier_filter="intraday"))
    assert res["success"] is True
    assert res["tier_counts"]["intraday"] == 1
    # Every intraday timeframe should get at least one planned request.
    planned = res["by_bar_size"]
    for tf in c.TIMEFRAMES_BY_TIER["intraday"]:
        assert planned.get(tf, 0) >= 1, (tf, planned)


def test_smart_backfill_skips_fresh_data():
    """When the newest bar for (symbol, bar_size) is within freshness_days,
    that pair must be skipped rather than re-queued."""
    from datetime import datetime, timezone

    c, db = _collector_with_empty_db()
    db["symbol_adv_cache"].insert_one({
        "symbol": "FRESH",
        "avg_volume": 10_000_000,
        "avg_dollar_volume": 1_000_000_000,
        "tier": "intraday",
    })
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Seed freshest possible bar for every intraday timeframe.
    for bs in c.TIMEFRAMES_BY_TIER["intraday"]:
        db["ib_historical_data"].insert_one({
            "symbol": "FRESH", "bar_size": bs, "date": today,
            "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0,
        })

    res = asyncio.run(c.smart_backfill(dry_run=True, tier_filter="intraday",
                                        freshness_days=2))
    assert res["success"] is True
    assert res["would_queue"] == 0
    assert res["skipped_fresh"] == len(c.TIMEFRAMES_BY_TIER["intraday"])


def test_smart_backfill_dedupes_against_queue():
    """If a pending queue entry already exists for (symbol, bar_size), it
    must not be re-queued."""
    c, db = _collector_with_empty_db()
    db["symbol_adv_cache"].insert_one({
        "symbol": "DUPE",
        "avg_volume": 10_000_000,
        "avg_dollar_volume": 1_000_000_000,
        "tier": "intraday",
    })
    for bs in c.TIMEFRAMES_BY_TIER["intraday"]:
        db["historical_data_requests"].insert_one({
            "request_id": f"pending_{bs}",
            "symbol": "DUPE", "bar_size": bs,
            "status": "pending",
        })

    res = asyncio.run(c.smart_backfill(dry_run=True, tier_filter="intraday"))
    assert res["success"] is True
    assert res["would_queue"] == 0
    assert res["skipped_already_queued"] == len(c.TIMEFRAMES_BY_TIER["intraday"])


def test_smart_backfill_persists_last_run_history():
    """Non-dry-run calls must write a summary into ib_smart_backfill_history
    so the NIA "Last Backfill" card has something to display."""
    c, db = _collector_with_empty_db()
    db["symbol_adv_cache"].insert_one({
        "symbol": "HIST",
        "avg_volume": 10_000_000,
        "avg_dollar_volume": 1_000_000_000,
        "tier": "intraday",
    })

    # Before first run: nothing.
    assert c.get_last_smart_backfill() == {"success": True, "last_run": None}

    res = asyncio.run(c.smart_backfill(dry_run=False, tier_filter="intraday"))
    assert res["success"] is True
    assert res.get("queued", 0) >= 1
    assert res.get("ran_at")

    last = c.get_last_smart_backfill()
    assert last["success"] is True
    run = last["last_run"]
    assert run is not None
    assert run["tier_filter"] == "intraday"
    assert run["queued"] == res["queued"]
    assert run["by_bar_size"] == res["by_bar_size"]


def test_dry_run_does_not_persist_history():
    """Dry-runs must not pollute the history collection."""
    c, db = _collector_with_empty_db()
    db["symbol_adv_cache"].insert_one({
        "symbol": "DRY",
        "avg_volume": 10_000_000,
        "avg_dollar_volume": 1_000_000_000,
        "tier": "intraday",
    })
    asyncio.run(c.smart_backfill(dry_run=True))
    assert c.get_last_smart_backfill() == {"success": True, "last_run": None}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
