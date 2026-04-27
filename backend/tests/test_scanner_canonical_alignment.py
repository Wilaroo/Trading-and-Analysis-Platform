"""
Scanner Universe Alignment Audit (Feb 2026)
============================================
Verifies the wave scanner and enhanced background scanner both source
their symbol universe from `services.symbol_universe.get_universe()` —
the same source the AI training pipeline uses.

Before this refactor the wave scanner pulled from `index_universe.py`
(SPY/QQQ/IWM ETF constituents) and the background scanner had a
hardcoded ~250-symbol watchlist, both of which had no overlap guarantee
with the AI-trained universe.
"""
from __future__ import annotations

import os
import asyncio
from typing import Any, Dict, List

import mongomock
import pytest


# ---- Helpers ---------------------------------------------------------------

def _seed_adv_cache(db, symbols_with_adv: Dict[str, int]) -> None:
    db["symbol_adv_cache"].delete_many({})
    docs = [
        {"symbol": sym, "avg_dollar_volume": adv, "unqualifiable": False}
        for sym, adv in symbols_with_adv.items()
    ]
    if docs:
        db["symbol_adv_cache"].insert_many(docs)


# ---- Tests -----------------------------------------------------------------

def test_wave_scanner_pulls_tier2_and_tier3_from_canonical_universe():
    """Tier 2 = top-N intraday (≥$50M); Tier 3 = canonical swing roster (≥$10M)."""
    from services import wave_scanner as ws_module

    db = mongomock.MongoClient().db
    _seed_adv_cache(db, {
        "AAPL": 60_000_000_000,   # intraday
        "TSLA": 40_000_000_000,   # intraday
        "NVDA": 80_000_000_000,   # intraday
        "PLTR":  2_500_000_000,   # intraday
        "SOFI":     800_000_000,  # intraday
        "BABA":      80_000_000,  # intraday (just over $50M)
        "MIDCAP":    30_000_000,  # swing only
        "MIDCAP2":   12_000_000,  # swing only
        "TINY":       5_000_000,  # investment only — must NOT appear in tier3
    })

    # Fresh scanner with stub watchlist service so we don't depend on Smart Watchlist.
    class StubWatchlist:
        def get_symbols(self):
            return []

    scanner = ws_module.WaveScanner(watchlist_service=StubWatchlist(), db=db)
    batch = asyncio.run(scanner.get_scan_batch())

    # Tier 2 = intraday (≥$50M), ADV-ranked desc
    tier2 = batch["tier2_high_rvol"]
    assert tier2[0] == "NVDA", f"Tier 2 must be ADV-ranked desc, got {tier2[:3]}"
    assert "TINY" not in tier2 and "MIDCAP" not in tier2, (
        "Tier 2 must contain only intraday-tier symbols (≥$50M ADV)."
    )
    # Should contain all 6 intraday symbols from the seed.
    assert {"AAPL", "TSLA", "NVDA", "PLTR", "SOFI", "BABA"}.issubset(set(tier2))

    # Tier 3 = canonical swing roster (≥$10M); MIDCAP/MIDCAP2 must appear,
    # TINY must not.
    tier3 = batch["tier3_wave"]
    assert "TINY" not in tier3, (
        "Tier 3 must exclude investment-tier-only symbols (<$10M ADV)."
    )
    # MIDCAP/MIDCAP2 are swing-only and aren't in tier2 -> they must surface in tier3.
    assert "MIDCAP" in tier3 and "MIDCAP2" in tier3


def test_wave_scanner_excludes_unqualifiable_symbols():
    """Symbols flagged `unqualifiable=true` must never reach any tier."""
    from services import wave_scanner as ws_module

    db = mongomock.MongoClient().db
    db["symbol_adv_cache"].insert_many([
        {"symbol": "AAPL", "avg_dollar_volume": 60_000_000_000, "unqualifiable": False},
        {"symbol": "BAD",  "avg_dollar_volume": 60_000_000_000, "unqualifiable": True},
    ])

    class StubWatchlist:
        def get_symbols(self):
            return []

    scanner = ws_module.WaveScanner(watchlist_service=StubWatchlist(), db=db)
    batch = asyncio.run(scanner.get_scan_batch())

    all_symbols = (
        batch["tier1_watchlist"]
        + batch["tier2_high_rvol"]
        + batch["tier3_wave"]
    )
    assert "BAD" not in all_symbols, (
        "Unqualifiable symbols must never appear in any wave tier."
    )
    assert "AAPL" in all_symbols


def test_wave_scanner_no_alpaca_no_index_universe_imports():
    """The refactored wave_scanner must not import legacy ETF-universe or Alpaca."""
    src = open("/app/backend/services/wave_scanner.py").read()
    assert "from services.index_universe" not in src, (
        "wave_scanner must no longer depend on index_universe.py."
    )
    assert "from services.alpaca_service" not in src, (
        "wave_scanner must no longer depend on alpaca_service."
    )
    assert "from services.symbol_universe" in src, (
        "wave_scanner must source its universe from symbol_universe.py."
    )


def test_enhanced_scanner_watchlist_refreshes_from_canonical_universe():
    """EnhancedBackgroundScanner._watchlist must come from the canonical
    universe once db is wired."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    db = mongomock.MongoClient().db
    _seed_adv_cache(db, {
        "AAPL":  60_000_000_000,
        "NVDA":  80_000_000_000,
        "MIDCAP":   30_000_000,  # swing only — must NOT enter the scanner watchlist
        "TINY":      5_000_000,  # investment only
    })

    scanner = EnhancedBackgroundScanner(db=db)
    # _watchlist should now contain ONLY intraday-tier (≥$50M) symbols.
    assert "AAPL" in scanner._watchlist
    assert "NVDA" in scanner._watchlist
    assert "MIDCAP" not in scanner._watchlist, (
        "Scanner watchlist must be intraday-tier only — MIDCAP is swing-only."
    )
    assert "TINY" not in scanner._watchlist


def test_enhanced_scanner_falls_back_to_safety_list_when_universe_empty():
    """If canonical universe returns 0 symbols, fall back to ETF safety list."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    db = mongomock.MongoClient().db
    db["symbol_adv_cache"].delete_many({})  # empty cache

    scanner = EnhancedBackgroundScanner(db=db)
    # Safety list = market-context ETFs.
    assert "SPY" in scanner._watchlist
    assert "QQQ" in scanner._watchlist
    # Should be the small safety list, not the old hardcoded 250-symbol roster.
    assert len(scanner._watchlist) <= 20, (
        f"Empty universe should fall back to a tiny ETF safety list, "
        f"got {len(scanner._watchlist)} symbols."
    )
