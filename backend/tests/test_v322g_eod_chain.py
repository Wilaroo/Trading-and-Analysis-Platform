"""
test_v322g_eod_chain.py — contract tests for the v322g EOD auto-chain.

The chain (all inside the backend's TradingScheduler, Mon-Fri ET):

    16:35  EOD Daily-Bar Top-Up   smart_backfill(bar_size_filter=["1 day"])
    17:10  ADV Cache Rebuild      rebuild_adv_from_ib_data()
    17:30  RS Leadership Compute  (pre-existing, v322)

What we guard here:
  1. `bar_size_filter=["1 day"]` queues ONLY daily-bar requests — never
     intraday refills — even when the symbol's 1-min/5-min history is
     stale. (The post-close queue must stay light so the Windows
     collectors land today's daily bars before the 5:30 PM RS compute.)
  2. With the filter, a symbol whose daily bar is already fresh queues
     NOTHING (skipped_fresh path still works through the filter).
  3. Without the filter, behaviour is unchanged (regression guard for
     the default smart-backfill path).
  4. The scheduler module wires the two new jobs + handlers, and the
     2:15 AM auto-resume imports a collector factory that actually
     exists (`get_ib_collector` — the old `get_historical_collector`
     import was a latent nightly ImportError).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make `services` importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_collector_with_fake_db(adv_docs, hist_docs, queue_docs=None):
    """In-memory fake collections implementing the minimum pymongo surface
    area smart_backfill uses (same harness as
    test_smart_backfill_per_bar_size.py)."""
    from services.ib_historical_collector import IBHistoricalCollector

    class _FakeCol:
        def __init__(self, docs):
            self.docs = list(docs)
            self.inserted = []

        def find(self, filt=None, proj=None):
            for d in self.docs:
                if not filt or _match(d, filt):
                    yield {k: v for k, v in d.items() if k != "_id"}

        def find_one(self, filt, proj=None, sort=None):
            matches = [d for d in self.docs if _match(d, filt)]
            if sort:
                key, direction = sort[0]
                matches.sort(key=lambda d: d.get(key, ""),
                             reverse=(direction == -1))
            return matches[0] if matches else None

        def distinct(self, field, filt=None):
            return list({d.get(field) for d in self.docs
                         if (not filt or _match(d, filt))
                         and d.get(field) is not None})

        def update_many(self, *_a, **_k):
            class _R:
                modified_count = 0
            return _R()

        def create_index(self, *_a, **_k):
            return None

        def insert_many(self, docs, **_k):
            self.inserted.extend(docs)

    def _match(doc, filt):
        for k, v in filt.items():
            if isinstance(v, dict):
                for op, arg in v.items():
                    dv = doc.get(k)
                    if op == "$gte" and not (dv is not None and dv >= arg):
                        return False
                    if op == "$in" and dv not in arg:
                        return False
                    if op == "$ne" and dv == arg:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    class _DB:
        def __init__(self):
            self._cols = {
                "symbol_adv_cache":          _FakeCol(adv_docs),
                "ib_historical_data":        _FakeCol(hist_docs),
                "historical_data_requests":  _FakeCol(queue_docs or []),
            }

        def __getitem__(self, name):
            if name not in self._cols:
                self._cols[name] = _FakeCol([])
            return self._cols[name]

    db = _DB()
    c = IBHistoricalCollector()
    c.set_db(db)
    return c, db


def _bar(symbol, bar_size, date_iso):
    return {"symbol": symbol, "bar_size": bar_size, "date": date_iso,
            "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}


def _stale():
    return (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")


def _fresh():
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def test_daily_filter_queues_only_daily_bars():
    """Symbol with EVERYTHING stale: the ["1 day"] filter must queue the
    daily bar and nothing else."""
    stale = _stale()
    adv = [{"symbol": "EOD_X", "avg_dollar_volume": 800_000_000, "tier": "intraday"}]
    hist = [
        _bar("EOD_X", "1 min",   stale),
        _bar("EOD_X", "5 mins",  stale),
        _bar("EOD_X", "15 mins", stale),
        _bar("EOD_X", "1 hour",  stale),
        _bar("EOD_X", "1 day",   stale),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None,
                                 freshness_days=2, bar_size_filter=["1 day"])
    queued_bs = res.get("by_bar_size", {})
    assert queued_bs.get("1 day", 0) >= 1, (
        f"BUG: stale daily bar not queued under filter. {queued_bs}")
    for bs in ("1 min", "5 mins", "15 mins", "1 hour"):
        assert queued_bs.get(bs, 0) == 0, (
            f"BUG: bar_size_filter leaked {bs!r} into the EOD queue. {queued_bs}")


def test_daily_filter_skips_fresh_daily():
    """Fresh daily bar + stale intraday: the filtered run queues NOTHING."""
    adv = [{"symbol": "FRESH_X", "avg_dollar_volume": 800_000_000, "tier": "intraday"}]
    hist = [
        _bar("FRESH_X", "1 min",  _stale()),
        _bar("FRESH_X", "1 day",  datetime.now(timezone.utc).strftime("%Y-%m-%d")),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None,
                                 freshness_days=2, bar_size_filter=["1 day"])
    assert res.get("would_queue", 0) == 0, (
        f"BUG: filtered run queued work for a daily-fresh symbol: {res}")


def test_no_filter_behaviour_unchanged():
    """Default path (no filter) still queues every stale required size."""
    stale = _stale()
    adv = [{"symbol": "REG_X", "avg_dollar_volume": 800_000_000, "tier": "intraday"}]
    hist = [
        _bar("REG_X", "1 min",   stale),
        _bar("REG_X", "5 mins",  stale),
        _bar("REG_X", "15 mins", stale),
        _bar("REG_X", "1 hour",  stale),
        _bar("REG_X", "1 day",   stale),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None, freshness_days=2)
    queued_bs = res.get("by_bar_size", {})
    for bs in ("1 min", "5 mins", "15 mins", "1 hour", "1 day"):
        assert bs in queued_bs, (
            f"REGRESSION: default path missing {bs!r}: {queued_bs}")


def test_scheduler_wires_v322g_jobs_and_fixed_import():
    """Source-level contract: the scheduler registers both v322g jobs,
    defines both handlers, and no longer imports the non-existent
    `get_historical_collector`."""
    src = (ROOT / "services" / "trading_scheduler.py").read_text()
    assert "id='eod_daily_topup'" in src, "eod_daily_topup job not registered"
    assert "id='adv_cache_rebuild'" in src, "adv_cache_rebuild job not registered"
    assert "async def _run_eod_daily_topup" in src, "missing top-up handler"
    assert "async def _run_adv_cache_rebuild" in src, "missing ADV rebuild handler"
    assert "get_historical_collector" not in src, (
        "latent ImportError: services.ib_historical_collector has no "
        "get_historical_collector — use get_ib_collector")
    assert 'bar_size_filter=["1 day"]' in src, (
        "EOD top-up must narrow smart_backfill to daily bars only")


def test_smart_backfill_async_signature_accepts_filter():
    """The async wrapper must pass bar_size_filter through to the sync impl."""
    import inspect
    from services.ib_historical_collector import IBHistoricalCollector
    sig = inspect.signature(IBHistoricalCollector.smart_backfill)
    assert "bar_size_filter" in sig.parameters, (
        "smart_backfill() missing bar_size_filter parameter")
