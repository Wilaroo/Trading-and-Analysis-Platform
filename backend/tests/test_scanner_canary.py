"""
Scanner & bot CANARY tests
==========================
Catch the "silent regression" failure mode that already bit us twice
this quarter:

  • 2026-04-17 — `_symbol_adv_cache` rename to `_adv_cache` collapsed
    the universe to a hardcoded 14-symbol ETF watchlist. The scanner
    kept running, kept producing alerts (RS-only), nobody noticed for
    2 weeks until the operator complained about strategy diversity.

  • 2026-04-27 — `bot_persistence` was overwriting `_enabled_setups`
    defaults with a stale Mongo state, silently filtering 7 strategies.
    Symptom: "the scanner is finding setups but the bot ignores them."

These canaries are intentionally small, fast, and assert on the
*contract* of the scanner's vital signs — not implementation details.
If a future PR breaks any of them, CI will fail on that commit
instead of letting the regression sleep until the operator notices in
production.

Naming convention: every test starts with `test_canary_*` so they're
easy to run as a quick health check:
    pytest tests/test_scanner_canary.py -k canary -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# -------------------- _enabled_setups defaults ----------------------

def test_canary_scanner_enabled_setups_is_non_empty():
    """Hard floor — if anything ever ships an empty default set, the
    bot has 0 tradeable strategies. Catches accidental wipe."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    s = EnhancedBackgroundScanner()
    assert isinstance(s._enabled_setups, set)
    # 2026-04-28: 25+ defaults today; safety floor at 15.
    assert len(s._enabled_setups) >= 15, (
        f"Default _enabled_setups dropped below 15 — "
        f"now {len(s._enabled_setups)}: {sorted(s._enabled_setups)}"
    )


def test_canary_scanner_pillar_setups_have_checkers():
    """Every "pillar" setup must have an actual checker method
    registered — i.e. the setup name in _enabled_setups isn't just
    a string nobody routes to. This catches the 2026-04-17 regression
    pattern: a setup is "enabled" but the dispatch table forgot it."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    s = EnhancedBackgroundScanner()
    pillars = {
        "rubber_band",
        "vwap_bounce",
        "squeeze",
        "relative_strength",
        "opening_drive",
        "orb",
        "breakout",
        "gap_fade",
        "9_ema_scalp",
        "spencer_scalp",
    }
    missing_from_enabled = pillars - s._enabled_setups
    assert not missing_from_enabled, (
        f"Pillar setups missing from _enabled_setups defaults: "
        f"{sorted(missing_from_enabled)}"
    )

    # Pull the dispatch map from _check_setup. We rebuild it locally
    # from the source rather than calling the async method.
    import inspect
    src = inspect.getsource(s._check_setup)
    for pillar in pillars:
        assert f'"{pillar}"' in src, (
            f"Pillar setup `{pillar}` is enabled but `_check_setup` has "
            f"no dispatch entry for it — alerts will silently drop on "
            f"the floor (regression of the 2026-04-17 pattern)."
        )


def test_canary_trading_bot_enabled_setups_covers_scanner_bases():
    """The bot's `_enabled_setups` is the filter that decides whether
    a scanner alert reaches `predict_for_setup`. If the bot's list
    doesn't cover the scanner's families, we get the 2026-04-27 bug:
    scanner fires, bot silently rejects, operator wonders why."""
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()
    assert isinstance(bot._enabled_setups, list)
    # 2026-04-28: ~30 entries today; safety floor at 20.
    assert len(bot._enabled_setups) >= 20, (
        f"Bot's _enabled_setups dropped below 20: {bot._enabled_setups}"
    )
    # Critical scanner bases that MUST be on the bot's allow-list — we
    # explicitly went through the operator-flagged 2026-04-24 regression
    # to add these. Locking them prevents an accidental rollback.
    must_include = {
        "rubber_band",
        "rubber_band_scalp",
        "vwap_bounce",
        "vwap_fade",
        "vwap_reclaim",       # SHORT_VWAP routing (2026-04-24)
        "vwap_rejection",     # SHORT_VWAP routing (2026-04-24)
        "reversal",            # SHORT_REVERSAL routing (2026-04-24)
        "halfback_reversal",   # SHORT_REVERSAL routing (2026-04-24)
        "squeeze",
        "relative_strength",
        "relative_strength_leader",
        "relative_strength_laggard",
        "orb",
        "opening_drive",
        "breakout",
        "gap_fade",
    }
    missing = must_include - set(bot._enabled_setups)
    assert not missing, (
        f"Bot _enabled_setups regressed — these scanner bases are "
        f"now silently filtered: {sorted(missing)}. See "
        f"CHANGELOG 2026-04-24 'Paper-Mode Enablement for the 3 "
        f"Promoted Shorts' for why each was added."
    )


# -------------------- universe selection contract -------------------

def test_canary_safety_watchlist_is_minimum_14():
    """If MongoDB is unavailable, the scanner must still return SOME
    symbols (the ETF safety list). Empty = scanner does nothing."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    s = EnhancedBackgroundScanner()
    safety = s._get_safety_watchlist()
    assert isinstance(safety, list)
    assert len(safety) >= 10, (
        f"Safety watchlist shrunk below 10 symbols: {safety}"
    )
    # Must include the indices — they're the regime read.
    for must_have in ("SPY", "QQQ", "IWM"):
        assert must_have in safety, (
            f"Safety watchlist missing index {must_have}: {safety}"
        )


def test_canary_canonical_universe_returns_100_plus_when_cache_seeded():
    """The 2026-04-17 regression: `_symbol_adv_cache` → `_adv_cache`
    silently fell back to the 14-symbol ETF list. This canary asserts
    that with a seeded `symbol_adv_cache` collection, the scanner pulls
    the full intraday tier (≥ 100 symbols) — not the ETF fallback."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    # Build a fake DB whose `symbol_adv_cache` has 200 canonical symbols
    # ranked above the $50M ADV intraday threshold.
    big_universe = [f"SYM{i:04d}" for i in range(200)]

    s = EnhancedBackgroundScanner()
    fake_db = MagicMock()
    s.db = fake_db

    with patch(
        "services.symbol_universe.get_universe",
        return_value=big_universe,
    ) as mock_get_universe:
        s._refresh_watchlist_from_canonical_universe()

    mock_get_universe.assert_called_once()
    assert len(s._watchlist) >= 100, (
        f"Scanner watchlist did NOT pull from canonical universe — "
        f"got only {len(s._watchlist)} symbols. This is the 2026-04-17 "
        f"regression pattern (cache variable rename → silent fallback "
        f"to 14-symbol ETF list)."
    )


def test_canary_canonical_universe_falls_back_to_safety_when_empty():
    """Mirror canary — when canonical universe IS empty (e.g. the
    ADV pre-calc job hasn't run yet), we must fall back to the safety
    watchlist, NOT crash and NOT leave _watchlist empty."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    s = EnhancedBackgroundScanner()
    fake_db = MagicMock()
    s.db = fake_db

    with patch("services.symbol_universe.get_universe", return_value=[]):
        s._refresh_watchlist_from_canonical_universe()

    assert len(s._watchlist) >= 10, (
        f"Empty canonical universe should fall back to ETF safety "
        f"list (≥10), got {len(s._watchlist)}: {s._watchlist}"
    )


# -------------------- wave scanner batch contract -------------------

@pytest.mark.asyncio
async def test_canary_wave_scanner_batch_is_not_empty():
    """`get_scan_batch` must return at least one symbol (Tier 1 / 2 / 3
    combined). Returning empty would mean the scan loop ticks but
    scans nothing — 0 alerts forever."""
    from services.wave_scanner import WaveScanner

    ws = WaveScanner()
    # Stub the watchlist + DB pools — we just want to confirm the
    # method returns the right shape and merges all 3 tiers.
    ws._watchlist = MagicMock()
    ws._watchlist.get_symbols = MagicMock(return_value=["SPY", "QQQ"])
    ws._tier2_pool = ["AAPL", "NVDA"]
    ws._tier3_roster = [f"SYM{i}" for i in range(500)]
    ws._last_tier2_refresh = MagicMock()  # bypass refresh
    # Patch the refresh to no-op (we already pre-seeded the pools).
    ws._refresh_universe_pools_if_needed = lambda: None  # type: ignore

    batch = await ws.get_scan_batch()
    assert isinstance(batch, dict)
    total = (
        len(batch.get("tier1_watchlist", []))
        + len(batch.get("tier2_high_rvol", []))
        + len(batch.get("tier3_wave", []))
    )
    assert total >= 1, f"Wave scanner returned empty batch: {batch}"
    # The progress tracker must reflect non-zero tier2/tier3.
    assert batch["universe_progress"]["tier2_pool_size"] == 2
    assert batch["universe_progress"]["tier3_roster_size"] == 500


# -------------------- bot_persistence merge contract ----------------

@pytest.mark.asyncio
async def test_canary_bot_persistence_merges_defaults_and_saved():
    """The 2026-04-27 regression: restore_state OVERWROTE bot defaults
    with whatever was in Mongo, dropping 7 strategies that hadn't been
    saved yet. Fix was to MERGE (union) defaults with saved — this
    canary asserts the merge stays intact."""
    from services.bot_persistence import BotPersistence

    # Fake bot with a small "default" enabled list. The merge is gated
    # on len(saved_setups) > 10, so the saved list also has to be big
    # enough to trigger the path we want to assert on.
    bot = SimpleNamespace(
        _enabled_setups=[
            "alpha", "bravo", "charlie", "delta", "echo",
            "foxtrot", "golf", "hotel", "india", "juliet",
            "kilo", "lima",
        ],
        _db=MagicMock(),
        _mode=None,
        _watchlist=[],
        risk_params=SimpleNamespace(
            max_risk_per_trade=0,
            max_daily_loss=0,
            max_daily_loss_pct=0,
        ),
    )
    saved_setups = [
        "alpha", "bravo", "mike", "november", "oscar",
        "papa", "quebec", "romeo", "sierra", "tango",
        "uniform", "victor",
    ]
    fake_state = {
        "running": False,
        "mode": "confirmation",
        "watchlist": ["AAPL"],
        "enabled_setups": saved_setups,
        "risk_params": {},
    }
    bot._db.bot_state.find_one = MagicMock(return_value=fake_state)

    svc = BotPersistence()
    await svc.restore_state(bot)

    merged = set(bot._enabled_setups)
    # All 12 originals must survive — 2026-04-27 regression test.
    for must_keep in (
        "alpha", "bravo", "charlie", "delta", "echo",
        "foxtrot", "golf", "hotel", "india", "juliet",
        "kilo", "lima",
    ):
        assert must_keep in merged, (
            f"Default setup `{must_keep}` was DROPPED by bot_persistence "
            f"— this is the 2026-04-27 regression pattern."
        )
    # And the new ones from Mongo must be added.
    for must_add in ("mike", "november", "oscar"):
        assert must_add in merged, (
            f"Saved setup `{must_add}` must be merged IN, not ignored."
        )


# -------------------- Phase 4: Alpaca retirement canaries -----------

def test_canary_alpaca_fallback_default_is_false():
    """Phase 4 retirement contract — `ENABLE_ALPACA_FALLBACK` MUST
    default to "false" in server.py so a fresh deploy doesn't
    accidentally re-enable the legacy Alpaca path."""
    src = open("server.py").read()
    assert '"ENABLE_ALPACA_FALLBACK", "false"' in src, (
        "server.py default for ENABLE_ALPACA_FALLBACK regressed away "
        "from 'false'. Phase 4 retirement requires the legacy Alpaca "
        "fallback stays OFF by default."
    )


def test_canary_alpaca_consumers_tolerate_none():
    """When ENABLE_ALPACA_FALLBACK=false (the default), consumers
    receive `alpaca_service=None`. This must be a no-op / tolerated
    code path in every wired consumer — NOT an AttributeError on the
    next quote fetch."""
    from services.stock_data import StockDataService
    from services.hybrid_data_service import HybridDataService

    # Both wired consumers must accept None without raising. Their
    # set_alpaca_service is a deprecation stub today (Alpaca path is
    # already removed) but the canary locks the contract: future
    # PRs cannot reintroduce a mandatory non-None requirement.
    stock = StockDataService()
    stock.set_alpaca_service(None)  # must not raise

    hybrid = HybridDataService()
    hybrid.set_alpaca_service(None)  # must not raise

