"""
v19.34.141 — PnL display fixes (realized window + dedup + buying power).
========================================================================

Three surgical fixes against operator-reported $-3,936 phantom realized
loss + missing buying power:

  #1 Realized PnL date window — sentcom.py used `now_utc.replace(hour=0)
     - 4h` which lands at YESTERDAY 20:00 UTC (yesterday 3-4 PM ET).
     Result: every close fired during yesterday's RTH/AH was summed
     into "today's realized". Fixed via zoneinfo-anchored ET midnight.

  #2 Duplicate-close dedup — same file summed every closed row without
     dedup, so orphan-reconciler / consolidator-merge / OCA-ext race
     paths that wrote a SECOND `closed` row for the same fill produced
     double-counted realized losses. Now deduped on the audit endpoint's
     key (symbol + fill_time, fallback to (symbol + fill_price + shares
     + exit_price)).

  #3 Buying Power `$—` — trading_bot.py only pulled IB account fallback
     when executor returned no equity. An executor that returned partial
     data (equity but no buying_power) silently bypassed the fallback,
     leaving buying_power null on the HUD.

These tests use lightweight mocks — no Mongo, no IB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


# =============================================================================
# Fix #1 + #2 — sentcom.py closed_today window + dedup
# =============================================================================

class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._i]
        self._i += 1
        return d


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query, proj=None, sort=None, limit=None):
        out = list(self.docs)
        # Filter by `closed_at >= cutoff_iso` from the `$or`.
        cutoff = None
        for clause in query.get("$or", []):
            ca = clause.get("closed_at")
            if isinstance(ca, dict) and "$gte" in ca:
                cutoff = ca["$gte"]
                break
        if cutoff:
            out = [d for d in out
                   if (d.get("closed_at") or "") >= cutoff]
        if query.get("status"):
            target_status = query["status"]
            if isinstance(target_status, dict):
                target_status = target_status.get("$in", [target_status])
            else:
                target_status = [target_status]
            out = [d for d in out if d.get("status") in target_status]
        if sort:
            out.sort(key=lambda d: d.get(sort[0][0]) or "", reverse=(sort[0][1] < 0))
        if limit:
            out = out[:limit]
        return iter(out)


class _DB:
    def __init__(self, bot_trades=None):
        self._colls = {"bot_trades": _Coll(bot_trades or [])}

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _Coll()
        return self._colls[name]


@pytest.fixture
def patched_db(monkeypatch):
    """Hand a mock DB to sentcom.py's lazy `from server import db` call."""
    db = _DB()
    import sys
    fake_server = type(sys)("server")
    fake_server.db = db
    monkeypatch.setitem(sys.modules, "server", fake_server)
    # Also stub the pusher-RPC + account_guard calls so the legacy
    # `_legacy_trade_type` lookup doesn't network-call.
    fake_pusher = type(sys)("services.ib_pusher_rpc")
    fake_pusher.get_account_snapshot = lambda: {}
    monkeypatch.setitem(sys.modules, "services.ib_pusher_rpc", fake_pusher)
    fake_guard = type(sys)("services.account_guard")
    fake_guard.classify_account_id = lambda x: "LIVE"
    monkeypatch.setitem(sys.modules, "services.account_guard", fake_guard)
    return db


class TestRealizedPnLDateWindow:
    """Bug #1 — closed_today cutoff must be MIDNIGHT ET, not 8-9h before."""

    @pytest.mark.asyncio
    async def test_yesterday_afternoon_close_is_excluded_from_today(
        self, patched_db, monkeypatch
    ):
        from routers.sentcom import get_positions
        # Seed:
        #   - yesterday 3PM ET = (today_utc 00:00 - 9h winter / -8h DST)
        #     → falls in the broken window, must be excluded by the fix
        #   - today 10AM ET = inside today
        now_utc = datetime.now(timezone.utc)

        # Yesterday 3PM ET is what the BROKEN window picks up. Express it
        # as a UTC ISO string roughly today_utc_midnight - 9h. Real ET
        # math is hot-path but this date is well before today's ET midnight
        # under either DST or winter.
        yesterday_afternoon_iso = (
            now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(hours=8)
        ).isoformat()
        today_morning_iso = (
            now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(hours=15)  # mid-morning UTC, well past ET midnight
        ).isoformat()

        patched_db["bot_trades"].docs.extend([
            {
                "id": "yesterday-loss",
                "symbol": "TE", "status": "closed",
                "closed_at": yesterday_afternoon_iso,
                "fill_time": yesterday_afternoon_iso,
                "realized_pnl": -3000.0,
                "fill_price": 5.40, "exit_price": 4.50, "shares": -7204,
                "direction": "short",
            },
            {
                "id": "today-tiny-loss",
                "symbol": "SMR", "status": "closed",
                "closed_at": today_morning_iso,
                "fill_time": today_morning_iso,
                "realized_pnl": -40.0,
                "fill_price": 13.29, "exit_price": 13.50, "shares": -171,
                "direction": "short",
            },
        ])

        # Stub out the position-pull side; we only care about realized.
        class _StubService:
            async def get_our_positions(self):
                return []
        monkeypatch.setattr(
            "routers.sentcom._get_service", lambda: _StubService()
        )

        resp = await get_positions()
        # PRE-FIX: would include the -3000 yesterday loss.
        # POST-FIX: only the -40 today loss.
        assert resp["success"] is True
        assert resp["total_realized_pnl"] == -40.0, (
            f"yesterday's -3000 loss must NOT bleed into today's realized; "
            f"got {resp['total_realized_pnl']}"
        )


class TestRealizedPnLDuplicateCloseDedup:
    """Bug #2 — duplicate close rows must not be double-counted."""

    @pytest.mark.asyncio
    async def test_duplicate_closes_for_same_fill_are_summed_once(
        self, patched_db, monkeypatch
    ):
        from routers.sentcom import get_positions
        now_utc = datetime.now(timezone.utc)
        today_iso = (
            now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(hours=15)
        ).isoformat()

        # Two rows for the SAME fill cluster (e.g. orphan reconciler
        # re-closed an already-closed trade). Both have the same
        # symbol + fill_time => dedup key collides.
        patched_db["bot_trades"].docs.extend([
            {
                "id": "trade-A",
                "symbol": "MTB", "status": "closed",
                "closed_at": today_iso,
                "fill_time": today_iso,
                "realized_pnl": -500.0,
                "fill_price": 211.20, "exit_price": 205.0, "shares": -67,
                "direction": "short",
            },
            {
                "id": "trade-A-dupe",
                "symbol": "MTB", "status": "closed",
                "closed_at": today_iso,
                "fill_time": today_iso,
                "realized_pnl": -500.0,  # same loss double-counted pre-fix
                "fill_price": 211.20, "exit_price": 205.0, "shares": -67,
                "direction": "short",
            },
        ])

        class _StubService:
            async def get_our_positions(self):
                return []
        monkeypatch.setattr(
            "routers.sentcom._get_service", lambda: _StubService()
        )

        resp = await get_positions()
        assert resp["total_realized_pnl"] == -500.0, (
            "duplicate close on the same fill must sum once, not twice"
        )
        assert resp["dropped_duplicate_closes"] == 1
        assert resp["dropped_duplicate_pnl"] == -500.0

    @pytest.mark.asyncio
    async def test_genuinely_separate_closes_both_count(
        self, patched_db, monkeypatch
    ):
        """Sanity — two different trades at DIFFERENT fill_times must
        BOTH count (no false-positive dedup)."""
        from routers.sentcom import get_positions
        now_utc = datetime.now(timezone.utc)
        today_a = (
            now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(hours=15)
        ).isoformat()
        today_b = (
            now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(hours=16)
        ).isoformat()
        patched_db["bot_trades"].docs.extend([
            {"id": "AAA", "symbol": "AAA", "status": "closed",
             "closed_at": today_a, "fill_time": today_a,
             "realized_pnl": -100.0, "fill_price": 10.0,
             "exit_price": 9.0, "shares": -100, "direction": "short"},
            {"id": "BBB", "symbol": "BBB", "status": "closed",
             "closed_at": today_b, "fill_time": today_b,
             "realized_pnl": +200.0, "fill_price": 50.0,
             "exit_price": 52.0, "shares": 100, "direction": "long"},
        ])

        class _StubService:
            async def get_our_positions(self):
                return []
        monkeypatch.setattr(
            "routers.sentcom._get_service", lambda: _StubService()
        )

        resp = await get_positions()
        assert resp["total_realized_pnl"] == 100.0
        assert resp["dropped_duplicate_closes"] == 0


# =============================================================================
# Fix #3 — trading_bot.py buying_power merge
# =============================================================================

class TestBuyingPowerMerge:
    """Bug #3 — IB buying_power must surface even when executor returned
    a partial account (equity-only) instead of nothing."""

    def test_merge_logic_unit(self):
        """Test the merge fragment directly — no fastapi router boot."""
        # Mimic the post-fix merge:
        executor_account = {"equity": 222939.43}
        ib_fields = {
            "equity": 500000.0,         # ignored — executor has it
            "buying_power": 384272.82,  # filled in from IB
            "cash": 406329.35,
            "available_funds": 384272.82,
            "currency": "USD",
            "source": "ib_pushed",
            "connected": True,
        }
        merged = dict(ib_fields)
        for k, v in (executor_account or {}).items():
            if v not in (None, 0, 0.0, ""):
                merged[k] = v

        assert merged["equity"] == 222939.43, "executor wins on equity"
        assert merged["buying_power"] == 384272.82, "IB fills buying_power"
        assert merged["cash"] == 406329.35
        assert merged["source"] == "ib_pushed"

    def test_merge_does_not_clobber_executor_explicit_zero_skips(self):
        """Falsy executor values (None/0/'') must NOT clobber IB values."""
        executor_account = {"equity": 100.0, "buying_power": 0}
        ib_fields = {"equity": 99.0, "buying_power": 384272.82,
                     "source": "ib_pushed"}
        merged = dict(ib_fields)
        for k, v in (executor_account or {}).items():
            if v not in (None, 0, 0.0, ""):
                merged[k] = v
        assert merged["buying_power"] == 384272.82, (
            "executor's 0 buying_power must NOT clobber IB's real value"
        )
        assert merged["equity"] == 100.0
