"""
v19.31.14 (2026-05-04) — tests for the small operator-feedback bundle:

1. Backfill Readiness diagnostic copy fix — distinguish the three
   real failure modes ("cache truly empty" vs "cache full but below
   ADV threshold" vs "cache full but all unqualifiable") instead of
   the old one-liner that always said "symbol_adv_cache empty?".

2. Reset script stale-snapshot warning — surface `as_of` age when
   the pusher snapshot is older than 30s so the operator knows to
   confirm pusher is alive before --commit'ing a reset.

3. RTH-aware collector throttle — `_rth_throttle_decision()` returns
   `max_concurrent_workers=1` during 9:30-15:55 ET weekdays, otherwise
   4. Surfaced as `GET /api/ib-collector/throttle-policy` and as a
   server-side cap on `GET /api/historical-data/pending`.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Lightweight fakes ─────────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs: Optional[List[dict]] = None):
        self.docs = list(docs or [])

    def _matches(self, doc, query):
        if not query:
            return True
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$ne" in v:
                    if actual == v["$ne"]:
                        return False
                if "$gte" in v:
                    if actual is None or actual < v["$gte"]:
                        return False
                if "$exists" in v:
                    if (k in doc) != v["$exists"]:
                        return False
            else:
                if actual != v:
                    return False
        return True

    def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if self._matches(d, query or {}):
                return dict(d)
        return None

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if self._matches(d, query or {})]
        if isinstance(limit, int):
            rows = rows[:limit]
        return iter(rows)

    def count_documents(self, query=None):
        return sum(1 for _ in self.find(query or {}))


class _FakeDB:
    def __init__(self):
        self.symbol_adv_cache = _FakeColl()
        self.ib_live_snapshot = _FakeColl()
        self.bot_trades = _FakeColl()
        self.bot_trades_reset_log = _FakeColl()
        self.ib_historical_data = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── Backfill Readiness diagnostic copy fix ────────────────────────


def test_backfill_freshness_detail_when_cache_truly_empty():
    """When `symbol_adv_cache.count_documents({}) == 0`, detail must say
    'is empty' — not the misleading 'empty?' question."""
    from services import backfill_readiness_service as svc
    db = _FakeDB()
    db.symbol_adv_cache.docs = []  # truly empty
    res = svc._check_overall_freshness(db)
    assert res["status"] == "yellow"
    assert "is empty" in res["detail"]
    assert "rebuild-adv-from-ib" in res["detail"]
    assert res["adv_cache_total"] == 0


def test_backfill_freshness_detail_when_cache_full_but_below_threshold():
    """Cache has rows but all below intraday ADV → message points to
    rebuild-adv-from-ib, NOT 'cache empty?'."""
    from services import backfill_readiness_service as svc
    db = _FakeDB()
    # 100 symbols, all with low avg_dollar_volume (below intraday tier)
    db.symbol_adv_cache.docs = [
        {"symbol": f"S{i}", "avg_dollar_volume": 1_000_000}  # well below threshold
        for i in range(100)
    ]
    res = svc._check_overall_freshness(db)
    assert res["status"] == "yellow"
    assert res["adv_cache_total"] == 100
    assert res["adv_cache_above_intraday_thr"] == 0
    assert "100" in res["detail"] and "below" not in res["detail"].lower() or "none meet" in res["detail"].lower()
    # The fix should mention threshold + rebuild.
    assert "threshold" in res["detail"].lower()


def test_backfill_freshness_detail_when_cache_full_but_all_unqualifiable():
    """Cache has high-ADV rows but all marked unqualifiable=True → the
    detail must call out the unqualifiable filter, NOT the cache size."""
    from services import backfill_readiness_service as svc
    db = _FakeDB()
    # Rows above threshold but all unqualifiable
    db.symbol_adv_cache.docs = [
        {"symbol": f"S{i}", "avg_dollar_volume": 100_000_000_000, "unqualifiable": True}
        for i in range(50)
    ]
    res = svc._check_overall_freshness(db)
    assert res["status"] == "yellow"
    assert res["adv_cache_total"] == 50
    assert res["adv_cache_qualified"] == 0
    assert "unqualifiable" in res["detail"].lower()


# ─── Reset script stale-snapshot warning ───────────────────────────


def test_reset_script_emits_stale_snapshot_warning(capsys):
    """When ib_live_snapshot.as_of is >30s old, reset script must:
    - keep using the cached positions (survival guard still works)
    - set `result['ib_snapshot_stale'] = True`
    - print a WARN line
    """
    from scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    stale_iso = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat()
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "as_of": stale_iso,
        "positions": [
            {"symbol": "AAPL", "position": 100},
        ],
    }]
    db.bot_trades.docs = [{
        "trade_id": "t1", "symbol": "AAPL", "direction": "long",
        "status": "open", "shares": 100, "remaining_shares": 100,
    }]

    res = reset_open_trades(db=db, symbols=None, dry_run=True, force=False)
    assert res["ib_snapshot_available"] is True
    assert res["ib_snapshot_stale"] is True
    assert res["ib_snapshot_age_s"] is not None
    assert res["ib_snapshot_age_s"] > 30
    captured = capsys.readouterr()
    assert "WARN" in captured.out
    assert "old" in captured.out


def test_reset_script_no_warn_when_snapshot_fresh(capsys):
    from scripts.reset_bot_open_trades import reset_open_trades
    db = _FakeDB()
    fresh_iso = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    db.ib_live_snapshot.docs = [{
        "_id": "current", "as_of": fresh_iso, "positions": [],
    }]
    db.bot_trades.docs = [{
        "trade_id": "t1", "symbol": "AAPL", "direction": "long",
        "status": "open", "shares": 100, "remaining_shares": 100,
    }]
    res = reset_open_trades(db=db, symbols=None, dry_run=True, force=False)
    assert res["ib_snapshot_stale"] is False
    captured = capsys.readouterr()
    assert "WARN" not in captured.out


def test_reset_script_handles_missing_as_of_gracefully():
    """Snapshot without as_of → age=None, stale=False (can't tell, don't warn)."""
    from scripts.reset_bot_open_trades import reset_open_trades
    db = _FakeDB()
    db.ib_live_snapshot.docs = [{
        "_id": "current", "positions": [],
    }]
    db.bot_trades.docs = []
    res = reset_open_trades(db=db, symbols=None, dry_run=True, force=False)
    assert res["ib_snapshot_age_s"] is None
    assert res["ib_snapshot_stale"] is False


def test_reset_script_summary_includes_stale_warning():
    from scripts.reset_bot_open_trades import reset_open_trades, render_summary
    db = _FakeDB()
    stale_iso = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat()
    db.ib_live_snapshot.docs = [{
        "_id": "current", "as_of": stale_iso,
        "positions": [{"symbol": "AAPL", "position": 100}],
    }]
    db.bot_trades.docs = []
    res = reset_open_trades(db=db, symbols=None, dry_run=True, force=False)
    summary = render_summary(res)
    assert "STALE" in summary
    assert "old" in summary


# ─── RTH-aware collector throttle ──────────────────────────────────


def test_rth_throttle_during_rth_returns_1_worker():
    """Tuesday 11:00 ET → max_concurrent_workers=1, recommended_limit=1."""
    from routers.ib_collector_router import _rth_throttle_decision
    # 2026-05-05 (Tuesday) 11:00 ET = 15:00 UTC (during EDT)
    rth_dt = datetime(2026, 5, 5, 15, 0, 0, tzinfo=timezone.utc)
    res = _rth_throttle_decision(now=rth_dt)
    assert res["rth_active"] is True
    assert res["max_concurrent_workers"] == 1
    assert res["recommended_pending_request_limit"] == 1
    assert "RTH active" in res["reason"]


def test_rth_throttle_premarket_returns_4_workers():
    """Tuesday 8:00 ET → outside RTH → 4 workers."""
    from routers.ib_collector_router import _rth_throttle_decision
    pre_dt = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)  # 8:00 ET EDT
    res = _rth_throttle_decision(now=pre_dt)
    assert res["rth_active"] is False
    assert res["max_concurrent_workers"] == 4
    assert res["recommended_pending_request_limit"] == 10


def test_rth_throttle_after_close_returns_4_workers():
    """Tuesday 16:30 ET → outside RTH (post-close) → 4 workers."""
    from routers.ib_collector_router import _rth_throttle_decision
    post_dt = datetime(2026, 5, 5, 20, 30, 0, tzinfo=timezone.utc)  # 16:30 ET EDT
    res = _rth_throttle_decision(now=post_dt)
    assert res["rth_active"] is False
    assert res["max_concurrent_workers"] == 4


def test_rth_throttle_weekend_returns_4_workers():
    """Saturday 11:00 ET → off-hours/weekend → 4 workers."""
    from routers.ib_collector_router import _rth_throttle_decision
    sat_dt = datetime(2026, 5, 9, 15, 0, 0, tzinfo=timezone.utc)  # Saturday 11:00 ET EDT
    res = _rth_throttle_decision(now=sat_dt)
    assert res["rth_active"] is False
    assert res["max_concurrent_workers"] == 4


def test_rth_throttle_at_open_minute_is_active():
    """9:30:00 ET sharp → throttle ON (boundary inclusive)."""
    from routers.ib_collector_router import _rth_throttle_decision
    open_dt = datetime(2026, 5, 5, 13, 30, 0, tzinfo=timezone.utc)  # 9:30 ET EDT
    res = _rth_throttle_decision(now=open_dt)
    assert res["rth_active"] is True


def test_rth_throttle_at_close_cushion_is_off():
    """15:55:00 ET → throttle OFF (5min cushion before 16:00 close)."""
    from routers.ib_collector_router import _rth_throttle_decision
    close_dt = datetime(2026, 5, 5, 19, 55, 0, tzinfo=timezone.utc)  # 15:55 ET EDT
    res = _rth_throttle_decision(now=close_dt)
    assert res["rth_active"] is False


@pytest.mark.asyncio
async def test_throttle_policy_endpoint_returns_payload():
    from routers.ib_collector_router import get_collector_throttle_policy
    res = await get_collector_throttle_policy()
    assert "max_concurrent_workers" in res
    assert "rth_active" in res
    assert "reason" in res
    assert "recommended_pending_request_limit" in res
    # Must be one of the two valid values.
    assert res["max_concurrent_workers"] in (1, 4)


def test_live_pending_route_applies_throttle():
    """The live /api/ib/historical-data/pending route must lookup
    `_rth_throttle_decision()` and cap `limit` when RTH is active."""
    src = Path("/app/backend/routers/ib.py").read_text()
    # The function `get_pending_historical_data_requests` should now
    # reference _rth_throttle_decision and rth_active.
    assert "_rth_throttle_decision" in src
    assert "rth_active" in src
    assert "throttle_limit" in src


# ─── PreMarket banner classifier ───────────────────────────────────


def test_premarket_banner_module_exists():
    """The frontend banner component must exist and export the
    classifier so we can document the time windows here."""
    p = Path("/app/frontend/src/components/sentcom/v5/PreMarketModeBanner.jsx")
    assert p.exists(), "PreMarketModeBanner.jsx must exist"
    content = p.read_text()
    assert "classifyEtMinute" in content
    assert "premarket" in content
    assert "rth" in content
    assert "v19.31.14" in content
    # Must be wired into ScannerCardsV5
    sc = Path("/app/frontend/src/components/sentcom/v5/ScannerCardsV5.jsx").read_text()
    assert "PreMarketModeBanner" in sc
