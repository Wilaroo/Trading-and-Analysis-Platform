"""
test_smart_backfill_per_bar_size.py — contract test for
`IBHistoricalCollector._smart_backfill_sync()`.

The bug we're guarding against (caught 2026-04-25 after the post-backfill
audit):

  smart-backfill ONLY refreshed the bar_sizes that the symbol's CURRENT
  tier required. So when GOOGL got reclassified from intraday → swing
  (because its avg_dollar_volume dipped below $50M/day for a week),
  smart-backfill stopped queuing GOOGL 1-min and 15-min refills — even
  though GOOGL ALREADY HAD that historical 1-min and 15-min data, and
  it was going stale. Result: GOOGL's 1-min latest bar got stuck at
  2026-03-17 for 39 days, blocking the readiness verdict.

  ~1,500 other intraday-tier symbols had the same problem.

The fix: for each symbol, the planner takes the UNION of:
  (a) bar_sizes the current tier requires (initial-collection rule), and
  (b) any bar_size the symbol already has data for (preserve-history rule).

This test asserts:
  1. A symbol classified as `swing` whose `avg_dollar_volume` puts it
     in swing tier, but which has existing 1-min and 15-min data,
     MUST get those bar_sizes refreshed if they're stale.
  2. A symbol with NO existing 1-min data only gets the tier-required
     bar_sizes (no over-collection).

If smart-backfill ever regresses to tier-only planning, this test fails.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make `services` importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_collector_with_fake_db(adv_docs, hist_docs, queue_docs=None):
    """Build an IBHistoricalCollector wired to in-memory fake collections
    that implement the minimum pymongo surface area smart_backfill uses."""
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

        def drop_index(self, *_a, **_k):
            return None

        def insert_many(self, docs, **_k):
            self.inserted.extend(docs)

    def _match(doc, filt):
        for k, v in filt.items():
            if isinstance(v, dict):
                # Support {"$gte": x}, {"$in": [...]}
                for op, arg in v.items():
                    dv = doc.get(k)
                    if op == "$gte" and not (dv is not None and dv >= arg):
                        return False
                    if op == "$in" and dv not in arg:
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
            # Auto-create empty fake collections for any name we haven't
            # explicitly stubbed — set_db() / set_data_col() touch a
            # bunch of housekeeping collections we don't care about for
            # this contract test.
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


def test_swing_tier_symbol_with_existing_1min_data_gets_refreshed():
    """The GOOGL regression: swing-tier symbol with existing 1-min
    history MUST get queued."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")

    # GOOGL_X is in swing tier (avg_dollar_volume = $30M, below $50M
    # intraday floor) but has existing 1-min + 15-min data that's gone
    # stale — exactly the GOOGL situation on 2026-04-25.
    adv = [
        {"symbol": "GOOGL_X", "avg_dollar_volume": 30_000_000, "tier": "swing"},
    ]
    hist = [
        # Swing-required timeframes — fresh, should NOT be queued.
        _bar("GOOGL_X", "5 mins",  fresh),
        _bar("GOOGL_X", "30 mins", fresh),
        _bar("GOOGL_X", "1 hour",  fresh),
        _bar("GOOGL_X", "1 day",   fresh),
        # Legacy intraday data — STALE, MUST be queued (the bug).
        _bar("GOOGL_X", "1 min",   stale),
        _bar("GOOGL_X", "15 mins", stale),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None, freshness_days=2)

    queued_bs = res.get("by_bar_size", {})
    assert "1 min" in queued_bs, (
        f"BUG: smart_backfill did NOT queue 1 min for swing-tier symbol with "
        f"existing 1-min history. by_bar_size={queued_bs}. "
        f"This is the GOOGL 2026-04-25 regression."
    )
    assert "15 mins" in queued_bs, (
        f"BUG: smart_backfill did NOT queue 15 mins for swing-tier symbol "
        f"with existing 15-min history. by_bar_size={queued_bs}."
    )
    # Tier-required-and-fresh bar_sizes should NOT be queued.
    assert "1 hour" not in queued_bs, queued_bs


def test_swing_tier_symbol_without_1min_history_skips_1min():
    """Inverse case: a brand-new swing symbol with NO 1-min history
    should NOT have 1-min queued (no over-collection)."""
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")

    adv = [
        {"symbol": "NEW_SWING", "avg_dollar_volume": 30_000_000, "tier": "swing"},
    ]
    hist = [
        # Only the tier-required bar_sizes have data; all stale.
        _bar("NEW_SWING", "5 mins",  stale),
        _bar("NEW_SWING", "30 mins", stale),
        _bar("NEW_SWING", "1 hour",  stale),
        _bar("NEW_SWING", "1 day",   stale),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None, freshness_days=2)

    queued_bs = res.get("by_bar_size", {})
    assert "1 min" not in queued_bs, (
        f"REGRESSION: smart_backfill queued 1 min for a swing symbol that "
        f"has no 1-min history. Over-collection bug. by_bar_size={queued_bs}"
    )
    # Stale tier-required bar_sizes SHOULD be queued.
    assert "5 mins" in queued_bs, queued_bs
    assert "1 hour" in queued_bs, queued_bs


def test_intraday_tier_symbol_gets_all_required_timeframes():
    """Sanity check: the historical happy path still works."""
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")

    adv = [
        {"symbol": "SPY_X", "avg_dollar_volume": 800_000_000, "tier": "intraday"},
    ]
    # Stale on every required timeframe — all 5 should be queued.
    hist = [
        _bar("SPY_X", "1 min",   stale),
        _bar("SPY_X", "5 mins",  stale),
        _bar("SPY_X", "15 mins", stale),
        _bar("SPY_X", "1 hour",  stale),
        _bar("SPY_X", "1 day",   stale),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None, freshness_days=2)

    queued_bs = res.get("by_bar_size", {})
    for bs in ("1 min", "5 mins", "15 mins", "1 hour", "1 day"):
        assert bs in queued_bs, (
            f"intraday symbol missing required {bs!r}: by_bar_size={queued_bs}"
        )


def test_freshness_skip_works_per_bar_size_not_per_symbol():
    """If only 1-min is stale and the other timeframes are fresh, ONLY
    1-min should be queued."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")

    adv = [
        {"symbol": "AAPL_X", "avg_dollar_volume": 800_000_000, "tier": "intraday"},
    ]
    hist = [
        _bar("AAPL_X", "1 min",   stale),   # stale — must queue
        _bar("AAPL_X", "5 mins",  fresh),
        _bar("AAPL_X", "15 mins", fresh),
        _bar("AAPL_X", "1 hour",  fresh),
        _bar("AAPL_X", "1 day",   fresh),
    ]
    c, _db = _make_collector_with_fake_db(adv, hist)
    res = c._smart_backfill_sync(dry_run=True, tier_filter=None, freshness_days=2)

    queued_bs = res.get("by_bar_size", {})
    assert queued_bs.get("1 min", 0) >= 1, (
        f"BUG: stale 1-min not queued. by_bar_size={queued_bs}"
    )
    # Fresh bar_sizes must not be re-queued.
    for bs in ("5 mins", "15 mins", "1 hour", "1 day"):
        assert queued_bs.get(bs, 0) == 0, (
            f"BUG: fresh {bs!r} was queued anyway. by_bar_size={queued_bs}"
        )
