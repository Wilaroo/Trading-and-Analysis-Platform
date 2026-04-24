"""
Phase 3 — Wire remaining surfaces to the live-data foundation.
Contract tests for the snapshot primitive, scanner top-up, briefing
snapshot, and trade-journal immutable close-price snapshot.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Phase-1/2 cache off so tests exercise the fall-through paths."""
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "false")
    monkeypatch.delenv("IB_PUSHER_RPC_URL", raising=False)
    from services import ib_pusher_rpc
    ib_pusher_rpc._client_instance = None
    yield


# ---------------------- snapshot primitive -------------------------------

@pytest.mark.asyncio
async def test_snapshot_returns_fail_shape_when_no_bars():
    """When pusher RPC is disabled + no cached bars exist, snapshot must
    return success=False with a stable shape (no exceptions, no 5xx)."""
    from services.live_symbol_snapshot import get_latest_snapshot
    snap = await get_latest_snapshot("SPY", "5 mins")
    assert snap["success"] is False
    # Shape must remain stable so frontend bindings don't crash
    for k in ("symbol", "latest_price", "latest_bar_time", "prev_close",
             "change_abs", "change_pct", "bar_size", "bar_count",
             "market_state", "source", "fetched_at", "error"):
        assert k in snap
    assert snap["symbol"] == "SPY"
    assert snap["bar_count"] == 0


@pytest.mark.asyncio
async def test_snapshot_bulk_bounded_to_20():
    """Bulk must cap at 20 symbols to prevent cache-stampede DoS."""
    from services.live_symbol_snapshot import get_snapshots_bulk
    many = [f"SYM{i:03d}" for i in range(50)]
    result = await get_snapshots_bulk(many, "5 mins")
    assert len(result) <= 20


@pytest.mark.asyncio
async def test_snapshot_computes_change_pct_correctly(monkeypatch):
    """Stub the underlying fetch to return known bars; verify math."""
    from services import hybrid_data_service
    svc = hybrid_data_service.get_hybrid_data_service()

    async def _fake_fetch(symbol, bar_size, *, active_view=False, use_rth=False):
        return {
            "success": True,
            "source": "cache",
            "market_state": "rth",
            "fetched_at": "2026-04-26T15:00:00Z",
            "bars": [
                {"date": "2026-04-26T14:55:00Z", "close": 100.00, "open": 99.5, "high": 100.5, "low": 99.0, "volume": 1000},
                {"date": "2026-04-26T15:00:00Z", "close": 101.00, "open": 100.0, "high": 101.5, "low": 99.8, "volume": 1500},
            ],
        }
    monkeypatch.setattr(svc, "fetch_latest_session_bars", _fake_fetch)

    from services.live_symbol_snapshot import get_latest_snapshot
    snap = await get_latest_snapshot("TEST", "5 mins")
    assert snap["success"] is True
    assert snap["latest_price"] == 101.00
    assert snap["prev_close"] == 100.00
    assert snap["change_abs"] == 1.00
    assert snap["change_pct"] == 1.0     # 1.00 / 100.00 = 1.0%
    assert snap["source"] == "cache"
    assert snap["market_state"] == "rth"


# ---------------------- scanner top-up wiring ----------------------------

def test_scanner_service_has_live_bars_topup():
    """market_scanner_service must call fetch_latest_session_bars for
    intraday scans (Phase 3 contract)."""
    src = Path("/app/backend/services/market_scanner_service.py").read_text(encoding="utf-8")
    assert "fetch_latest_session_bars" in src, (
        "Scanner must call fetch_latest_session_bars for intraday top-up"
    )
    assert "TradeStyle.INTRADAY" in src
    # Dedup merge must happen after the top-up to avoid duplicate bars
    assert "merged" in src and "sorted(" in src, (
        "Scanner top-up must dedup+sort merged bars by timestamp"
    )


def test_scanner_topup_does_not_break_non_intraday():
    """Swing / investment timeframe scans must not trigger the top-up."""
    src = Path("/app/backend/services/market_scanner_service.py").read_text(encoding="utf-8")
    # The guard "if filters.trade_style == TradeStyle.INTRADAY:" must wrap the fetch
    idx_guard = src.find("filters.trade_style == TradeStyle.INTRADAY")
    idx_fetch = src.find("fetch_latest_session_bars")
    # All top-up fetches must appear AFTER a trade-style intraday guard
    assert 0 < idx_guard < idx_fetch, (
        "fetch_latest_session_bars must be gated by TradeStyle.INTRADAY check"
    )


# ---------------------- trade journal immutable close --------------------

def test_trade_journal_captures_close_price_snapshot():
    src = Path("/app/backend/services/trade_journal.py").read_text(encoding="utf-8")
    assert "close_price_snapshot" in src, (
        "Trade journal must persist close_price_snapshot on close_trade"
    )
    assert "get_latest_snapshot" in src, (
        "Trade journal must call get_latest_snapshot at close-time"
    )
    # The snapshot must be captured INSIDE close_trade (not elsewhere)
    idx_method = src.find("async def close_trade")
    idx_snapshot = src.find("close_price_snapshot")
    assert 0 < idx_method < idx_snapshot, (
        "close_price_snapshot must be populated inside close_trade method"
    )


def test_trade_journal_snapshot_failure_does_not_abort_close():
    """Snapshot failure must be swallowed — a trade close must NEVER fail
    just because the live data service is unreachable."""
    src = Path("/app/backend/services/trade_journal.py").read_text(encoding="utf-8")
    # try/except around the snapshot call
    assert "except Exception as _snap_exc" in src or "snapshot_error" in src, (
        "close_trade must swallow snapshot exceptions so a live-data outage "
        "cannot block the trade from being marked closed"
    )


# ---------------------- router endpoints ---------------------------------

LIVE_ROUTER = Path("/app/backend/routers/live_data_router.py").read_text(encoding="utf-8")


def test_router_has_symbol_snapshot_endpoint():
    assert '"/symbol-snapshot/{symbol}"' in LIVE_ROUTER
    assert '"/symbol-snapshots"' in LIVE_ROUTER


def test_router_has_briefing_snapshot_endpoint():
    assert '"/briefing-snapshot"' in LIVE_ROUTER


def test_briefing_snapshot_ranks_by_change_pct():
    """Briefing must surface biggest movers first — key UX promise."""
    assert "sorted(" in LIVE_ROUTER and "change_pct" in LIVE_ROUTER
    # Failed snapshots must sort last
    assert "0 if s.get(\"success\") else 1" in LIVE_ROUTER


# ---------------------- HTTP smoke via in-process client -----------------

@pytest.mark.asyncio
async def test_symbol_snapshot_endpoint_never_500s(monkeypatch):
    """The endpoint must gracefully degrade to success=False on failure."""
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "false")
    from services import ib_pusher_rpc
    ib_pusher_rpc._client_instance = None
    from routers.live_data_router import symbol_snapshot
    resp = await symbol_snapshot("SPY")
    assert resp["success"] is False
    assert "error" in resp


@pytest.mark.asyncio
async def test_briefing_snapshot_endpoint_returns_ranked_list(monkeypatch):
    from services import hybrid_data_service
    svc = hybrid_data_service.get_hybrid_data_service()

    # Stub returns different change_pct per symbol so we can check ranking
    bar_template = lambda c1, c2: [
        {"date": "t1", "close": c1, "open": c1, "high": c1, "low": c1, "volume": 0},
        {"date": "t2", "close": c2, "open": c2, "high": c2, "low": c2, "volume": 0},
    ]
    prices_by_sym = {"AAA": (100, 105), "BBB": (100, 102), "CCC": (100, 110)}

    async def _fake(symbol, bar_size, *, active_view=False, use_rth=False):
        c1, c2 = prices_by_sym.get(symbol, (100, 100))
        return {
            "success": True,
            "source": "cache",
            "market_state": "rth",
            "fetched_at": "2026-04-26T15:00:00Z",
            "bars": bar_template(c1, c2),
        }
    monkeypatch.setattr(svc, "fetch_latest_session_bars", _fake)

    from routers.live_data_router import briefing_snapshot
    resp = await briefing_snapshot(symbols="AAA,BBB,CCC", bar_size="5 mins")
    assert resp["success"] is True
    assert resp["count"] == 3
    # CCC = +10%, AAA = +5%, BBB = +2% → sort biggest first
    syms = [s["symbol"] for s in resp["snapshots"]]
    assert syms == ["CCC", "AAA", "BBB"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
