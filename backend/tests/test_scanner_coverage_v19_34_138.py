"""
v19.34.138 — Scanner coverage diagnostic + mega-cap pin contract tests.
========================================================================

Covers:
  - MEGA_CAP_WATCHLIST contents (must include the user-flagged movers
    TSLA / NVDA / AMD / MU / SNDK + structural ETFs).
  - WaveScanner.get_scan_batch() injects every mega-cap name into
    Tier 1 regardless of `symbol_adv_cache` state.
  - `/api/diagnostic/scanner-coverage` correctly classifies each name
    (OK / UNQUALIFIABLE_FLAGGED / MISSING_FROM_CACHE / STALE_BARS).
  - `/api/diagnostic/clear-unqualifiable` flips the flag end-to-end.

These tests run pure-python with mock collections — no live IB, no
Mongo. Safe to run on the cloud dev sandbox.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest


# =============================================================================
# Mongo-mock plumbing (mirrors existing test_universe_canonical.py style)
# =============================================================================

def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Tiny Mongo $gte / $ne / $in query evaluator — enough for these tests."""
    for k, v in query.items():
        if isinstance(v, dict):
            for op, opv in v.items():
                actual = doc.get(k)
                if op == "$gte" and not (actual is not None and actual >= opv):
                    return False
                if op == "$ne" and actual == opv:
                    return False
                if op == "$in" and actual not in opv:
                    return False
                if op == "$gt" and not (actual is not None and actual > opv):
                    return False
        else:
            if doc.get(k) != v:
                return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._sort_key = None
        self._sort_dir = 1
        self._limit = None

    def sort(self, key, direction=1):
        self._sort_key = key
        self._sort_dir = direction
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __iter__(self):
        out = list(self._docs)
        if self._sort_key:
            out.sort(
                key=lambda d: d.get(self._sort_key) or 0,
                reverse=(self._sort_dir < 0),
            )
        if self._limit is not None:
            out = out[: self._limit]
        return iter(out)


class _Coll:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.updates: List[Dict[str, Any]] = []

    def find(self, query: Dict[str, Any], proj=None):
        return _Cursor(d for d in self.docs if _matches(d, query))

    def find_one(self, query: Dict[str, Any], proj=None, sort=None):
        candidates = [d for d in self.docs if _matches(d, query)]
        if sort:
            key, direction = sort[0]
            candidates.sort(
                key=lambda d: d.get(key) or 0, reverse=(direction < 0)
            )
        return dict(candidates[0]) if candidates else None

    def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                for op, payload in update.items():
                    if op == "$set":
                        d.update(payload)
                    elif op == "$inc":
                        for k, v in payload.items():
                            d[k] = d.get(k, 0) + v
                self.updates.append({"q": query, "u": update})
                return type("R", (), {"modified_count": 1})()
        if upsert:
            new_doc: Dict[str, Any] = {}
            new_doc.update({k: v for k, v in query.items()
                            if not isinstance(v, dict)})
            for op, payload in update.items():
                if op in ("$set", "$setOnInsert"):
                    new_doc.update(payload)
                elif op == "$inc":
                    for k, v in payload.items():
                        new_doc[k] = new_doc.get(k, 0) + v
            self.docs.append(new_doc)
            return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for d in self.docs if _matches(d, query))


class _DB:
    def __init__(self):
        self.symbol_adv_cache = _Coll()
        self.live_bar_cache = _Coll()
        self.pusher_config_cache = _Coll()
        self._colls = {
            "symbol_adv_cache": self.symbol_adv_cache,
            "live_bar_cache": self.live_bar_cache,
            "pusher_config_cache": self.pusher_config_cache,
        }

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _Coll()
        return self._colls[name]


# =============================================================================
# Mega-cap content tests
# =============================================================================

class TestMegaCapWatchlistContent:
    """The hardcoded list MUST contain the names the operator flagged
    as missing from scans, plus the structural ETFs."""

    def test_must_have_user_flagged_movers(self):
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST
        for sym in ("TSLA", "NVDA", "AMD", "MU", "SNDK"):
            assert sym in MEGA_CAP_WATCHLIST, (
                f"{sym} flagged by user as missing from scans but not "
                "pinned into MEGA_CAP_WATCHLIST"
            )

    def test_must_have_structural_etfs(self):
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST
        # VIXY is the tradable ETF proxy. VIX itself is an index — IB
        # cannot return a security definition for the bare ticker, so
        # it was removed in v19.34.140.
        for sym in ("SPY", "QQQ", "IWM", "DIA", "VIXY"):
            assert sym in MEGA_CAP_WATCHLIST
        assert "VIX" not in MEGA_CAP_WATCHLIST, (
            "VIX (the index) must NOT be in the mega-cap pin — IB can't "
            "qualify the bare ticker. Use VIXY (tradable proxy) instead."
        )

    def test_get_mega_cap_returns_fresh_copy(self):
        from data.mega_cap_watchlist import (
            MEGA_CAP_WATCHLIST,
            get_mega_cap_watchlist,
        )
        copy_a = get_mega_cap_watchlist()
        copy_a.append("ZZZ_FAKE")
        assert "ZZZ_FAKE" not in MEGA_CAP_WATCHLIST
        assert "ZZZ_FAKE" not in get_mega_cap_watchlist()

    def test_is_mega_cap_helper(self):
        from data.mega_cap_watchlist import is_mega_cap
        assert is_mega_cap("TSLA")
        assert is_mega_cap("tsla")     # case-insensitive
        assert is_mega_cap("  AMD  ")  # whitespace-tolerant
        assert not is_mega_cap("FOOBAR")
        assert not is_mega_cap("")
        assert not is_mega_cap(None)

    def test_list_size_is_sane(self):
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST
        # 50 ± a few. If this drifts, someone changed the curation
        # without updating the test — review needed.
        assert 40 <= len(MEGA_CAP_WATCHLIST) <= 70, (
            f"MEGA_CAP_WATCHLIST size = {len(MEGA_CAP_WATCHLIST)}; "
            "review curation."
        )
        # No duplicates.
        assert len(set(MEGA_CAP_WATCHLIST)) == len(MEGA_CAP_WATCHLIST)


# =============================================================================
# WaveScanner integration tests
# =============================================================================

class _StubWatchlist:
    """Minimal SmartWatchlistService stub — only what WaveScanner uses."""

    def __init__(self, symbols=None):
        self._symbols = list(symbols or [])

    def get_symbols(self):
        return list(self._symbols)


class TestWaveScannerMegaCapPin:
    @pytest.fixture
    def db(self):
        db = _DB()
        # Populate cache with a few low-rank symbols only — TSLA / NVDA
        # / MU / SNDK absent (simulates either stale cache OR they got
        # flagged unqualifiable). The mega-cap pin must rescue them.
        for sym, adv in [
            ("FOO", 800_000_000),
            ("BAR", 600_000_000),
            ("BAZ", 400_000_000),
        ]:
            db.symbol_adv_cache.docs.append({
                "symbol": sym,
                "avg_dollar_volume": adv,
                "tier": "intraday",
            })
        return db

    @pytest.mark.asyncio
    async def test_tier1_contains_every_mega_cap_name_even_when_cache_lacks_them(
        self, db
    ):
        from services.wave_scanner import WaveScanner
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST

        scanner = WaveScanner(watchlist_service=_StubWatchlist(), db=db)
        batch = await scanner.get_scan_batch()

        for sym in MEGA_CAP_WATCHLIST:
            assert sym in batch["tier1_watchlist"], (
                f"{sym} should be pinned into Tier 1 by mega-cap "
                "guard but was missing."
            )

    @pytest.mark.asyncio
    async def test_operator_watchlist_keeps_priority_within_tier1(self, db):
        """Operator-pinned names should come BEFORE mega-cap names
        in Tier 1 (preserves the existing priority contract)."""
        from services.wave_scanner import WaveScanner
        scanner = WaveScanner(
            watchlist_service=_StubWatchlist(["WIIN", "ZZTOP"]),
            db=db,
        )
        batch = await scanner.get_scan_batch()
        t1 = batch["tier1_watchlist"]
        assert t1.index("WIIN") < t1.index("TSLA"), (
            "operator-pinned WIIN should precede mega-cap TSLA in Tier 1"
        )
        assert t1.index("ZZTOP") < t1.index("NVDA")

    @pytest.mark.asyncio
    async def test_tier1_has_no_duplicates(self, db):
        from services.wave_scanner import WaveScanner
        scanner = WaveScanner(
            watchlist_service=_StubWatchlist(["TSLA", "NVDA"]),  # overlap!
            db=db,
        )
        batch = await scanner.get_scan_batch()
        t1 = batch["tier1_watchlist"]
        assert len(t1) == len(set(t1)), "Tier 1 must be deduplicated"


# =============================================================================
# /api/diagnostic/scanner-coverage endpoint tests
# =============================================================================

class TestScannerCoverageEndpoint:
    @pytest.fixture
    def patched_db(self, monkeypatch):
        db = _DB()
        # Populate ADV cache:
        #   TSLA — healthy ($10B ADV)
        #   NVDA — flagged unqualifiable (false-positive scenario)
        #   AMD  — healthy ($5B ADV)
        #   MU   — below tier2 cutoff ($30M)
        #   SNDK — completely absent from cache
        db.symbol_adv_cache.docs.extend([
            {"symbol": "TSLA", "avg_dollar_volume": 10_000_000_000,
             "tier": "intraday", "unqualifiable": False,
             "unqualifiable_failure_count": 0},
            {"symbol": "NVDA", "avg_dollar_volume": 12_000_000_000,
             "tier": "intraday", "unqualifiable": True,
             "unqualifiable_failure_count": 1,
             "unqualifiable_reason": "No security definition found",
             "unqualifiable_marked_at":
                 datetime.now(timezone.utc).isoformat()},
            {"symbol": "AMD", "avg_dollar_volume": 5_000_000_000,
             "tier": "intraday", "unqualifiable": False,
             "unqualifiable_failure_count": 0},
            {"symbol": "MU", "avg_dollar_volume": 30_000_000,
             "tier": "swing", "unqualifiable": False,
             "unqualifiable_failure_count": 0},
            # SNDK intentionally omitted.
            # Fill Tier 2 ranks with filler names so MU truly is below cutoff
            *[{"symbol": f"FILL{i}", "avg_dollar_volume": 200_000_000,
               "tier": "intraday", "unqualifiable": False}
              for i in range(250)],
        ])
        # Fresh bars for TSLA + AMD, stale for MU, none for SNDK.
        now = datetime.now(timezone.utc)
        db.live_bar_cache.docs.extend([
            {"symbol": "TSLA", "ts": now - timedelta(seconds=30)},
            {"symbol": "AMD", "ts": now - timedelta(seconds=45)},
            {"symbol": "MU", "ts": now - timedelta(minutes=30)},
            # SNDK has no bars at all.
        ])

        # Patch the router's _get_db hook to hand back our mock.
        from routers import diagnostic_router as dr
        monkeypatch.setattr(dr, "_get_db", lambda: db)
        return db

    def test_endpoint_classifies_each_symbol_correctly(self, patched_db):
        from routers.diagnostic_router import scanner_symbol_coverage
        resp = scanner_symbol_coverage(
            symbols="TSLA,NVDA,AMD,MU,SNDK",
            include_mega_cap=False,
        )
        assert resp["success"] is True
        by_symbol = {c["symbol"]: c for c in resp["coverage"]}

        # TSLA — healthy, in Tier 2 (rank may be high due to fillers but
        # within top-200). Bars fresh → OK verdict.
        assert by_symbol["TSLA"]["verdict"] == "OK"
        assert by_symbol["TSLA"]["in_adv_cache"] is True
        assert by_symbol["TSLA"]["unqualifiable"] is False

        # NVDA — flagged unqualifiable.
        assert by_symbol["NVDA"]["verdict"] == "UNQUALIFIABLE_FLAGGED"
        assert by_symbol["NVDA"]["unqualifiable"] is True
        assert by_symbol["NVDA"]["failure_count"] == 1

        # AMD — healthy.
        assert by_symbol["AMD"]["verdict"] == "OK"

        # MU — below Tier 2 ADV threshold; rank == None.
        assert by_symbol["MU"]["verdict"] == "BELOW_TIER2_THRESHOLD"
        assert by_symbol["MU"]["in_tier2_top_n"] is None

        # SNDK — absent from cache entirely.
        assert by_symbol["SNDK"]["verdict"] == "MISSING_FROM_CACHE"
        assert by_symbol["SNDK"]["in_adv_cache"] is False

    def test_endpoint_summary_aggregates_categories(self, patched_db):
        from routers.diagnostic_router import scanner_symbol_coverage
        resp = scanner_symbol_coverage(
            symbols="TSLA,NVDA,AMD,MU,SNDK",
            include_mega_cap=False,
        )
        s = resp["summary"]
        assert "SNDK" in s["missing_from_canonical"]
        assert "NVDA" in s["unqualifiable_flagged"]
        assert "MU" in s["missing_from_tier2"]

    def test_endpoint_recommends_actions_for_each_finding(self, patched_db):
        from routers.diagnostic_router import scanner_symbol_coverage
        resp = scanner_symbol_coverage(
            symbols="TSLA,NVDA,AMD,MU,SNDK",
            include_mega_cap=False,
        )
        joined = " | ".join(resp["actions"])
        # Should reference all three failure modes.
        assert "clear-unqualifiable" in joined.lower()
        assert "symbol_adv_cache" in joined or "rebuild_adv_from_ib" in joined
        assert "MEGA_CAP_WATCHLIST" in joined or "below the top" in joined

    def test_endpoint_includes_mega_cap_when_requested(self, patched_db):
        from routers.diagnostic_router import scanner_symbol_coverage
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST
        resp = scanner_symbol_coverage(symbols=None, include_mega_cap=True)
        audited = set(resp["audited_symbols"])
        for sym in MEGA_CAP_WATCHLIST:
            assert sym in audited

    def test_endpoint_marks_in_mega_cap_flag(self, patched_db):
        from routers.diagnostic_router import scanner_symbol_coverage
        resp = scanner_symbol_coverage(
            symbols="TSLA,WIIN_NOT_MEGA",
            include_mega_cap=False,
        )
        by_symbol = {c["symbol"]: c for c in resp["coverage"]}
        assert by_symbol["TSLA"]["in_mega_cap"] is True
        assert by_symbol["WIIN_NOT_MEGA"]["in_mega_cap"] is False


# =============================================================================
# /api/diagnostic/clear-unqualifiable endpoint tests
# =============================================================================

class TestClearUnqualifiableEndpoint:
    @pytest.fixture
    def patched_db(self, monkeypatch):
        db = _DB()
        db.symbol_adv_cache.docs.extend([
            {"symbol": "NVDA", "unqualifiable": True,
             "unqualifiable_failure_count": 1},
            {"symbol": "SNDK", "unqualifiable": True,
             "unqualifiable_failure_count": 1},
            {"symbol": "TSLA", "unqualifiable": False,
             "unqualifiable_failure_count": 0},
        ])
        from routers import diagnostic_router as dr
        monkeypatch.setattr(dr, "_get_db", lambda: db)
        # symbol_universe.reset_unqualifiable also touches the db directly.
        import services.symbol_universe as su

        def _patched_reset(_db, sym):
            for d in _db.symbol_adv_cache.docs:
                if d.get("symbol") == sym.upper() and d.get("unqualifiable"):
                    d["unqualifiable"] = False
                    d["unqualifiable_failure_count"] = 0
                    return True
            return False

        monkeypatch.setattr(su, "reset_unqualifiable", _patched_reset)
        # The endpoint imports inside the function, so patch the module
        # path it actually pulls from.
        monkeypatch.setitem(__import__("sys").modules,
                            "services.symbol_universe", su)
        return db

    def test_clear_specific_symbols(self, patched_db):
        from routers.diagnostic_router import (
            ClearUnqualifiableRequest,
            clear_unqualifiable,
        )
        resp = clear_unqualifiable(ClearUnqualifiableRequest(
            symbols=["NVDA", "SNDK"], reason="false positive rescue"
        ))
        assert resp["success"] is True
        assert resp["cleared"] == 2
        assert resp["no_op"] == 0

        # Confirm the flag is actually flipped in the mock db.
        nvda = next(d for d in patched_db.symbol_adv_cache.docs
                    if d["symbol"] == "NVDA")
        assert nvda["unqualifiable"] is False

    def test_clear_with_mega_cap_target_expands_to_full_list(self, patched_db):
        from routers.diagnostic_router import (
            ClearUnqualifiableRequest,
            clear_unqualifiable,
        )
        from data.mega_cap_watchlist import MEGA_CAP_WATCHLIST
        resp = clear_unqualifiable(ClearUnqualifiableRequest(target="mega_cap"))
        assert resp["success"] is True
        # NVDA + SNDK actually had the flag, the rest are no-ops.
        assert resp["cleared"] == 2
        assert resp["no_op"] == len(MEGA_CAP_WATCHLIST) - 2

    def test_clear_with_no_targets_returns_400(self, patched_db):
        from fastapi import HTTPException
        from routers.diagnostic_router import (
            ClearUnqualifiableRequest,
            clear_unqualifiable,
        )
        with pytest.raises(HTTPException) as exc_info:
            clear_unqualifiable(ClearUnqualifiableRequest())
        assert exc_info.value.status_code == 400
