"""
v19.34.193 — scanner universe-coverage hardening.

Background: the weekly ADV scheduler (server.py, Sundays 10 PM ET) called the
legacy `scripts/recalculate_adv_cache.py`, which `delete_many()`'d
`symbol_adv_cache` and rewrote docs with ONLY `avg_volume` (share count) and
NO `avg_dollar_volume`. The wave-scanner ranks tiers 2/3 by
`avg_dollar_volume >= $50M / $10M`, so those pools collapsed to empty and the
scanner silently degraded to a 50-symbol ALPHABETICAL fallback watchlist —
every Friday trade was an A/B name, ignoring ~9,150 symbols.

Fixes locked here:
  1. WaveScanner._refresh_universe_pools_if_needed:
       a. healthy cache → tier2/tier3 populated, ADV-ranked desc
       b. broken cache (docs exist, none have avg_dollar_volume) → ALARM +
          NON-alphabetical avg_volume fallback (never empty/alphabetical)
       c. empty pools bypass the 10-min TTL (fast self-heal after a rebuild)
  2. scripts/recalculate_adv_cache.recalculate_adv_cache() is DISABLED (raises).
"""
import mongomock
import pytest
from datetime import datetime, timezone, timedelta

from services.wave_scanner import WaveScanner


class _FakeWatchlist:
    def get_symbols(self):
        return []


def _scanner(db):
    return WaveScanner(watchlist_service=_FakeWatchlist(), db=db)


def _seed_healthy(db):
    """Big-cap names with proper avg_dollar_volume (raw dollars)."""
    rows = [
        {"symbol": "AAPL", "avg_dollar_volume": 25_000_000_000, "avg_volume": 90_000_000},
        {"symbol": "NVDA", "avg_dollar_volume": 40_000_000_000, "avg_volume": 300_000_000},
        {"symbol": "ZM",   "avg_dollar_volume": 600_000_000,    "avg_volume": 8_000_000},   # tier3 only (>$10M, <$50M? actually >$50M) -> set below
        {"symbol": "XYZ",  "avg_dollar_volume": 12_000_000,     "avg_volume": 1_000_000},   # tier3 only
        {"symbol": "TINY", "avg_dollar_volume": 1_000_000,      "avg_volume": 200_000},     # neither
    ]
    db["symbol_adv_cache"].insert_many(rows)


def _seed_broken(db):
    """The wipe signature: docs exist with avg_volume but NO avg_dollar_volume."""
    rows = [
        {"symbol": "AAPL", "avg_volume": 90_000_000},
        {"symbol": "NVDA", "avg_volume": 300_000_000},
        {"symbol": "AMD",  "avg_volume": 50_000_000},
        {"symbol": "PENNY", "avg_volume": 100_000},  # below 500k floor → excluded
        {"symbol": "ZAPP", "avg_volume": 700_000},
    ]
    db["symbol_adv_cache"].insert_many(rows)


# ── 1a. healthy cache → ADV-ranked tiers ──────────────────────────────────
def test_healthy_cache_populates_tiers_adv_ranked():
    db = mongomock.MongoClient().db
    _seed_healthy(db)
    sc = _scanner(db)
    sc._refresh_universe_pools_if_needed()

    # tier3 = all >= $10M, ADV desc. TINY ($1M) excluded.
    assert sc._tier3_roster[:2] == ["NVDA", "AAPL"]  # ADV-ranked, not alphabetical
    assert "TINY" not in sc._tier3_roster
    assert "XYZ" in sc._tier3_roster
    # tier2 = top by ADV (>= $50M)
    assert sc._tier2_pool[:2] == ["NVDA", "AAPL"]


# ── 1b. broken cache → alarm + non-alphabetical avg_volume fallback ───────
def test_broken_cache_falls_back_to_volume_rank_not_alphabetical():
    db = mongomock.MongoClient().db
    _seed_broken(db)
    sc = _scanner(db)
    sc._refresh_universe_pools_if_needed()

    # Must NOT be empty (that's the bug) and must NOT be alphabetical.
    assert sc._tier3_roster, "fallback must populate tier3, never leave it empty"
    # avg_volume desc: NVDA(300M) > AMD(50M) > AAPL(90M)? -> NVDA, AAPL? wait
    # NVDA 300M, AAPL 90M, AMD 50M, ZAPP 0.7M ; PENNY 0.1M excluded (<500k)
    assert sc._tier3_roster[0] == "NVDA"        # highest volume first
    assert sc._tier3_roster[:3] == ["NVDA", "AAPL", "AMD"]
    assert "PENNY" not in sc._tier3_roster      # below 500k floor
    # Alphabetical order would have put AAPL/AMD first — prove we didn't.
    assert sc._tier3_roster != sorted(sc._tier3_roster)


# ── 1c. empty pools bypass the 10-min TTL ─────────────────────────────────
def test_empty_pools_bypass_ttl_for_fast_selfheal():
    db = mongomock.MongoClient().db
    sc = _scanner(db)
    # Simulate a refresh that just ran but left pools empty (broken-cache era).
    sc._last_tier2_refresh = datetime.now(timezone.utc)
    sc._tier2_pool = []
    sc._tier3_roster = []
    # Now the cache gets repaired:
    _seed_healthy(db)

    sc._refresh_universe_pools_if_needed()  # within TTL, but pools were empty
    assert sc._tier3_roster, "empty pools must re-query despite a fresh TTL stamp"


# ── 1c2. populated pools DO honor the TTL (no needless re-query) ──────────
def test_populated_pools_honor_ttl():
    db = mongomock.MongoClient().db
    _seed_healthy(db)
    sc = _scanner(db)
    sc._tier2_pool = ["CACHED"]
    sc._tier3_roster = ["CACHED"]
    sc._last_tier2_refresh = datetime.now(timezone.utc)
    sc._refresh_universe_pools_if_needed()
    assert sc._tier3_roster == ["CACHED"], "fresh TTL + populated pools = no re-query"


# ── 2. the footgun script is disabled ─────────────────────────────────────
def test_legacy_recalculate_adv_cache_is_disabled():
    from scripts.recalculate_adv_cache import recalculate_adv_cache
    db = mongomock.MongoClient().db
    db["symbol_adv_cache"].insert_one({"symbol": "AAPL", "avg_dollar_volume": 1e9})
    with pytest.raises(RuntimeError):
        recalculate_adv_cache(db, verbose=False)
    # Critically: it must NOT have wiped the collection.
    assert db["symbol_adv_cache"].count_documents({}) == 1
