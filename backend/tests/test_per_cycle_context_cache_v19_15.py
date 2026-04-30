"""
v19.15 — Per-cycle context cache (2026-04-30).

Pre-v19.15: every alert's `_apply_setup_context` did 3 awaited
classifier calls (multi-index regime + sector regime + setup
classifier). The first two are market-wide so calling them per-alert
was pure overhead — they're TTL-cached internally but still pay
function-dispatch + await + lock overhead × 1,500 alerts/day.

v19.15: prefetch ONCE per scan cycle into `_cycle_context`; the
per-alert path becomes a dict lookup. The MarketSetup classifier
stays per-alert because it genuinely needs the per-symbol intraday
snapshot.

This test file pins:
  - The cycle cache is populated by `_refresh_cycle_context()`.
  - The cache TTL falls back to the per-alert path when stale.
  - The cache hit/miss counters increment correctly.
  - `_apply_setup_context` reads from the cache when fresh and falls
    back to per-alert classifier calls when missing/stale.
  - The contract that a cache miss does NOT crash the scanner — it
    silently degrades to the prior per-alert behaviour.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------
# Source-level guards — pin the v19.15 contract on `enhanced_scanner.py`
# --------------------------------------------------------------------------

def _read_scanner_src() -> str:
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "enhanced_scanner.py"
    )
    with open(src_path) as f:
        return f.read()


def test_scanner_init_declares_cycle_context_fields():
    """`__init__` must declare the v19.15 cycle-cache fields so the
    refresh helper has somewhere to write to.
    """
    src = _read_scanner_src()
    assert "self._cycle_context: Optional[Dict[str, Any]] = None" in src
    assert "self._cycle_context_at" in src
    assert "self._cycle_context_hits = 0" in src
    assert "self._cycle_context_misses = 0" in src
    assert "self._cycle_context_ttl_s" in src


def test_scanner_has_refresh_cycle_context_helper():
    """The module exposes the v19.15 prefetch helper."""
    src = _read_scanner_src()
    assert "async def _refresh_cycle_context" in src
    # Calls multi_index classifier exactly once per cycle:
    assert (
        "regime_res = await regime_classifier.classify()"
        in src
    )
    # Calls sector classify_all_sectors once per cycle (NOT per-alert):
    assert "await sector_classifier.classify_all_sectors()" in src


def test_run_optimized_scan_invokes_refresh():
    """`_run_optimized_scan` must call `_refresh_cycle_context()` BEFORE
    fanning out to per-symbol scans, otherwise alerts can race ahead of
    the cache and silently fall back to the per-alert path.
    """
    src = _read_scanner_src()
    # The two strings must appear in the file in this order — the
    # refresh BEFORE the symbol fanout (`_get_active_symbols`).
    refresh_idx = src.find("await self._refresh_cycle_context()")
    fanout_idx = src.find("await self._get_active_symbols()")
    assert refresh_idx > 0, "missing _refresh_cycle_context call"
    assert fanout_idx > 0, "missing _get_active_symbols call"
    assert refresh_idx < fanout_idx, (
        "refresh must run BEFORE the per-symbol fanout"
    )


def test_apply_setup_context_reads_from_cache_first():
    """The per-alert path reads from `_get_cycle_context()` and only
    falls back to per-alert classifier calls on miss. Pin the source
    pattern so a future refactor doesn't silently regress.
    """
    src = _read_scanner_src()
    assert "cycle_ctx = self._get_cycle_context()" in src
    # The cache hit branch reads multi_index_regime from the dict:
    assert 'cycle_ctx["multi_index_regime"]' in src
    # The cache hit branch also reads from the per-cycle sector map:
    assert "sector_regime_by_etf" in src


# --------------------------------------------------------------------------
# Behaviour tests — _get_cycle_context staleness gate
# --------------------------------------------------------------------------

def _make_scanner_stub():
    """Produce a `_get_cycle_context`/`_refresh_cycle_context` test
    fixture without instantiating the full scanner (which drags in
    Mongo, IB pusher, AI modules, etc).
    """
    from services.enhanced_scanner import EnhancedBackgroundScanner
    inst = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    inst._cycle_context = None
    inst._cycle_context_at = None
    inst._cycle_context_hits = 0
    inst._cycle_context_misses = 0
    inst._cycle_context_ttl_s = 60
    inst._scan_count = 0
    return inst


def test_get_cycle_context_returns_none_when_uninitialized():
    inst = _make_scanner_stub()
    assert inst._get_cycle_context() is None
    assert inst._cycle_context_misses == 1
    assert inst._cycle_context_hits == 0


def test_get_cycle_context_returns_fresh_payload_within_ttl():
    inst = _make_scanner_stub()
    inst._cycle_context = {
        "multi_index_regime": "risk_on_broad",
        "sector_regime_by_etf": {"XLK": "strong"},
        "captured_at_monotonic": time.monotonic(),
    }
    inst._cycle_context_at = inst._cycle_context["captured_at_monotonic"]
    out = inst._get_cycle_context()
    assert out is not None
    assert out["multi_index_regime"] == "risk_on_broad"
    assert inst._cycle_context_hits == 1
    assert inst._cycle_context_misses == 0


def test_get_cycle_context_returns_none_when_stale():
    """A cache more than `_cycle_context_ttl_s` seconds old must be
    treated as a miss so alerts fall back to the per-alert classifier
    call (which has its own 5-min TTL inside the classifier).
    """
    inst = _make_scanner_stub()
    inst._cycle_context_ttl_s = 60
    # Pretend the context was captured 90s ago.
    inst._cycle_context = {"multi_index_regime": "risk_on_broad"}
    inst._cycle_context_at = time.monotonic() - 90.0
    assert inst._get_cycle_context() is None
    assert inst._cycle_context_misses == 1


# --------------------------------------------------------------------------
# Behaviour tests — _refresh_cycle_context populates the cache
# --------------------------------------------------------------------------

class _FakeRegimeLabel:
    def __init__(self, value):
        self.value = value


class _FakeRegimeResult:
    def __init__(self, label="risk_on_broad", confidence=0.85):
        self.label = _FakeRegimeLabel(label)
        self.confidence = confidence


class _FakeSectorSnapshot:
    def __init__(self, regime_value):
        self.regime = _FakeRegimeLabel(regime_value)


class _FakeSectorResult:
    def __init__(self, sectors_map=None, spy_5d=0.7):
        self.sectors = sectors_map or {}
        self.spy_5d_return_pct = spy_5d


@pytest.mark.asyncio
async def test_refresh_cycle_context_populates_cache():
    inst = _make_scanner_stub()
    inst.db = MagicMock()

    fake_regime = _FakeRegimeResult(label="bullish_divergence", confidence=0.78)
    fake_regime_classifier = MagicMock()
    fake_regime_classifier.classify = AsyncMock(return_value=fake_regime)

    fake_sector_result = _FakeSectorResult(
        sectors_map={
            "XLK": _FakeSectorSnapshot("strong"),
            "XLE": _FakeSectorSnapshot("weak"),
        },
        spy_5d=1.4,
    )
    fake_sector_classifier = MagicMock()
    fake_sector_classifier.classify_all_sectors = AsyncMock(
        return_value=fake_sector_result
    )

    with patch(
        "services.multi_index_regime_classifier.get_multi_index_regime_classifier",
        return_value=fake_regime_classifier,
    ), patch(
        "services.sector_regime_classifier.get_sector_regime_classifier",
        return_value=fake_sector_classifier,
    ):
        await inst._refresh_cycle_context()

    assert inst._cycle_context is not None
    assert inst._cycle_context["multi_index_regime"] == "bullish_divergence"
    assert inst._cycle_context["multi_index_confidence"] == pytest.approx(0.78)
    assert inst._cycle_context["sector_regime_by_etf"]["XLK"] == "strong"
    assert inst._cycle_context["sector_regime_by_etf"]["XLE"] == "weak"
    assert inst._cycle_context["spy_5d_return_pct"] == pytest.approx(1.4)
    assert inst._cycle_context["fresh"] is True

    # Single classify call per cycle — the entire point of v19.15.
    fake_regime_classifier.classify.assert_awaited_once()
    fake_sector_classifier.classify_all_sectors.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_cycle_context_resilient_to_classifier_failure():
    """Failure in either classifier must not crash the scanner —
    we degrade to the per-alert fallback path inside
    `_apply_setup_context`.
    """
    inst = _make_scanner_stub()
    inst.db = MagicMock()

    # Multi-index throws; sector returns empty.
    crashing_regime_classifier = MagicMock()
    crashing_regime_classifier.classify = AsyncMock(
        side_effect=RuntimeError("Mongo unavailable")
    )
    fake_sector_classifier = MagicMock()
    fake_sector_classifier.classify_all_sectors = AsyncMock(
        return_value=_FakeSectorResult(sectors_map={}, spy_5d=0.0)
    )

    with patch(
        "services.multi_index_regime_classifier.get_multi_index_regime_classifier",
        return_value=crashing_regime_classifier,
    ), patch(
        "services.sector_regime_classifier.get_sector_regime_classifier",
        return_value=fake_sector_classifier,
    ):
        # Must not raise.
        await inst._refresh_cycle_context()

    # When the multi-index call fails, the cache still gets created
    # (with default unknown values) — the alerts will hit the
    # per-alert fallback at read time.
    assert inst._cycle_context is not None
    assert inst._cycle_context["multi_index_regime"] == "unknown"
    assert inst._cycle_context["fresh"] is True


# --------------------------------------------------------------------------
# Smoke — the cache key 'sector_regime_by_etf' is stable for 11 SPDR ETFs
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_covers_all_11_spdr_etfs_when_classifier_returns_them():
    inst = _make_scanner_stub()
    inst.db = MagicMock()

    SPDR_ETFS = ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP",
                 "XLI", "XLB", "XLRE", "XLU", "XLC"]
    sectors_map = {etf: _FakeSectorSnapshot("strong") for etf in SPDR_ETFS}
    fake_sector_result = _FakeSectorResult(sectors_map=sectors_map)
    fake_sector_classifier = MagicMock()
    fake_sector_classifier.classify_all_sectors = AsyncMock(
        return_value=fake_sector_result
    )

    fake_regime_classifier = MagicMock()
    fake_regime_classifier.classify = AsyncMock(return_value=_FakeRegimeResult())

    with patch(
        "services.multi_index_regime_classifier.get_multi_index_regime_classifier",
        return_value=fake_regime_classifier,
    ), patch(
        "services.sector_regime_classifier.get_sector_regime_classifier",
        return_value=fake_sector_classifier,
    ):
        await inst._refresh_cycle_context()

    cached_etfs = inst._cycle_context["sector_regime_by_etf"]
    for etf in SPDR_ETFS:
        assert etf in cached_etfs, f"missing ETF {etf} in cycle cache"
        assert cached_etfs[etf] == "strong"
