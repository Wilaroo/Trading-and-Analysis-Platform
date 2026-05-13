"""
v19.34.139 — Self-curating Smart Watchlist (auto-pin) tests.
============================================================

A symbol that fires ≥ AUTO_PIN_THRESHOLD distinct setup types in any
rolling window automatically promotes to `auto_pinned=true`. Auto-pinned
items:
  - Survive EOD expiry (gets the AUTO_PIN_EXPIRY_DAYS grace window
    instead of the intraday cutoff).
  - Are NOT removed by max-size enforcement.
  - Sort between operator-pinned (top) and ordinary scanner items.
  - Operator can still manually remove them (they're not sticky).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _build_service():
    """Build an in-memory SmartWatchlistService (no Mongo)."""
    from services.smart_watchlist_service import SmartWatchlistService
    return SmartWatchlistService(db=None)


class TestAutoPinPromotion:
    def test_fewer_than_threshold_distinct_setups_does_not_auto_pin(self):
        svc = _build_service()
        # Use 2 distinct setups (one below the threshold of 3).
        svc.add_scanner_hit("TSLA", "vwap_bounce", score=70)
        svc.add_scanner_hit("TSLA", "gap_and_go", score=72)
        item = svc.get_item("TSLA")
        assert item is not None
        assert len(item.strategies_matched) == 2
        assert item.auto_pinned is False, (
            "Should NOT auto-pin until distinct setups >= threshold"
        )

    def test_threshold_distinct_setups_promotes_to_auto_pin(self):
        svc = _build_service()
        # 3 distinct setups → crosses AUTO_PIN_THRESHOLD.
        svc.add_scanner_hit("NVDA", "vwap_bounce", score=70)
        svc.add_scanner_hit("NVDA", "gap_and_go", score=72)
        svc.add_scanner_hit("NVDA", "hod_breakout", score=80)
        item = svc.get_item("NVDA")
        assert item.auto_pinned is True
        assert item.auto_pinned_at is not None
        assert len(item.strategies_matched) >= svc.AUTO_PIN_THRESHOLD

    def test_repeated_same_setup_does_not_auto_pin(self):
        """Spamming ONE detector must not be enough — needs distinct setups."""
        svc = _build_service()
        for _ in range(10):
            svc.add_scanner_hit("FOO", "vwap_bounce", score=70)
        item = svc.get_item("FOO")
        assert item.signal_count >= 10
        assert len(item.strategies_matched) == 1
        assert item.auto_pinned is False, (
            "10 hits of the SAME setup should not promote — distinct is key"
        )

    def test_auto_pin_persists_after_subsequent_hits(self):
        """Once promoted, the flag stays True even if more hits come in."""
        svc = _build_service()
        for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
            svc.add_scanner_hit("AMD", s, score=70)
        first_pin_time = svc.get_item("AMD").auto_pinned_at
        # Subsequent hits — flag stays, timestamp does NOT regress.
        svc.add_scanner_hit("AMD", "midday_momentum", score=70)
        item = svc.get_item("AMD")
        assert item.auto_pinned is True
        assert item.auto_pinned_at == first_pin_time


class TestAutoPinExpiry:
    def test_intraday_auto_pin_survives_past_eod(self):
        """An auto-pinned intraday item must NOT expire at EOD — it gets
        the AUTO_PIN_EXPIRY_DAYS grace window."""
        svc = _build_service()
        for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
            svc.add_scanner_hit("MU", s, score=70)
        item = svc.get_item("MU")
        assert item.auto_pinned is True
        # Backdate the last_signal_at to yesterday (would normally expire
        # an intraday item).
        item.last_signal_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert svc._is_expired(item) is False, (
            "Auto-pinned items must survive yesterday → today rollover"
        )

    def test_auto_pin_expires_after_grace_window(self):
        """After AUTO_PIN_EXPIRY_DAYS of total silence the item DOES expire."""
        svc = _build_service()
        for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
            svc.add_scanner_hit("SNDK", s, score=70)
        item = svc.get_item("SNDK")
        # Backdate to one day BEYOND the grace window.
        item.last_signal_at = datetime.now(timezone.utc) - timedelta(
            days=svc.AUTO_PIN_EXPIRY_DAYS + 1
        )
        assert svc._is_expired(item) is True


class TestAutoPinMaxSizeProtection:
    def test_auto_pinned_not_dropped_by_max_size_enforcement(self):
        """Filling the watchlist past max with low-score items must not
        evict an auto-pinned name."""
        from services.smart_watchlist_service import SmartWatchlistService
        svc = SmartWatchlistService(db=None)
        # Auto-pin one name with low score.
        for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
            svc.add_scanner_hit("COIN", s, score=10)
        assert svc.get_item("COIN").auto_pinned is True

        # Now flood the watchlist with high-score one-off scanner hits.
        for i in range(svc.MAX_WATCHLIST_SIZE + 10):
            svc.add_scanner_hit(f"FILL{i}", "vwap_bounce", score=99)

        # COIN must survive.
        assert svc.is_in_watchlist("COIN"), (
            "Auto-pinned COIN must NOT be evicted by max-size enforcement"
        )


class TestAutoPinSortingAndStats:
    def test_get_watchlist_orders_sticky_then_auto_then_score(self):
        from services.smart_watchlist_service import SmartWatchlistService
        svc = SmartWatchlistService(db=None)
        # Plain scanner hit, low score.
        svc.add_scanner_hit("LOW", "vwap_bounce", score=30)
        # Auto-pinned (3 distinct setups, mid score).
        for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
            svc.add_scanner_hit("AUTO", s, score=50)
        # Operator-pinned.
        svc.add_manual("PIN")

        items = svc.get_watchlist()
        symbols_in_order = [i.symbol for i in items]
        assert symbols_in_order.index("PIN") < symbols_in_order.index("AUTO")
        assert symbols_in_order.index("AUTO") < symbols_in_order.index("LOW")

    def test_get_stats_reports_auto_pinned_count(self):
        svc = _build_service()
        # Two auto-pinned, one plain scanner, one manual.
        for sym in ("AAA", "BBB"):
            for s in ("vwap_bounce", "gap_and_go", "hod_breakout"):
                svc.add_scanner_hit(sym, s, score=50)
        svc.add_scanner_hit("CCC", "vwap_bounce", score=50)
        svc.add_manual("DDD")

        stats = svc.get_stats()
        assert stats["auto_pinned"] == 2
        assert stats["manual"] == 1
        assert stats["scanner"] == 1
        assert stats["auto_pin_threshold"] == svc.AUTO_PIN_THRESHOLD
        assert stats["auto_pin_expiry_days"] == svc.AUTO_PIN_EXPIRY_DAYS


class TestAutoPinSerialization:
    def test_to_dict_includes_auto_pin_fields(self):
        from services.smart_watchlist_service import WatchlistItem, StrategyTimeframe
        now = datetime.now(timezone.utc)
        item = WatchlistItem(
            symbol="ZZZ",
            source="scanner",
            added_at=now,
            timeframe=StrategyTimeframe.INTRADAY,
            auto_pinned=True,
            auto_pinned_at=now,
        )
        d = item.to_dict()
        assert d["auto_pinned"] is True
        assert d["auto_pinned_at"] is not None
        # Round-trip.
        from services.smart_watchlist_service import WatchlistItem as WI
        rebuilt = WI.from_dict(d)
        assert rebuilt.auto_pinned is True
        assert rebuilt.auto_pinned_at is not None

    def test_from_dict_handles_missing_auto_pin_fields(self):
        """Backwards-compat: pre-v19.34.139 documents without the
        auto_pinned key must hydrate as auto_pinned=False, not error."""
        from services.smart_watchlist_service import WatchlistItem
        now_iso = datetime.now(timezone.utc).isoformat()
        legacy = {
            "symbol": "OLD",
            "source": "scanner",
            "added_at": now_iso,
            "signal_count": 5,
            "strategies_matched": ["vwap_bounce"],
            "timeframe": "intraday",
            "is_sticky": False,
            "score": 50,
            "notes": "",
        }
        item = WatchlistItem.from_dict(legacy)
        assert item.auto_pinned is False
        assert item.auto_pinned_at is None
