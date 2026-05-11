"""
v19.34.78 — Zombie pending-trade cleanup regression
=====================================================

Background
----------
2026-05-12 deep feed showed NBIS, MU, COIN, CRCL, COHR, IONQ, NOK, CCL,
TEAM, CPNG, QCOM, LITE, NVD repeatedly hitting `rejection: pending
trade exists` 7+ minutes apart. Root-cause trace: v19.34.6's pre-submit
save (`trade_execution.py` L676) writes `status=PENDING` to Mongo
BEFORE the broker call. Refusal / veto / crash paths that don't write
the follow-up status flip leave a PENDING zombie row. Boot restore
(`bot_persistence.py` L298) reloads those rows into `_pending_trades`,
where the scan loop's `pending_trade_exists` gate
(`trading_bot_service.py:3192`) keeps rejecting fresh evaluations on
the same symbol forever.

Fix
---
Two-part:
1. **Boot-time filter** in `bot_persistence.py` — only restore PENDINGs
   younger than `STALE_PENDING_TTL_S` (default 1800s = 30 min). Stale
   rows are auto-rewritten in Mongo as `status=REJECTED` with
   `close_reason="stale_pending_v19_34_78"`.
2. **Operator escape hatch** — `POST /api/trading-bot/clear-stale-pending-trades`
   prunes `_pending_trades` WITHOUT a restart. Dry-run default.

Assertions
----------
A. Endpoint dry-run returns the candidates that WOULD be cleared,
   leaves `_pending_trades` untouched.
B. Endpoint with `dry_run=false` removes stale entries from
   `_pending_trades` and flips their Mongo status to REJECTED.
C. `older_than_s` filter respected: trades younger than threshold are
   left alone.
D. `symbols` filter narrows the candidate set.
E. Trades with NO `pre_submit_at` are treated as stale (safer to drop
   than to keep a zombie blocking re-evaluation).
F. Empty `_pending_trades` returns clean response.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "/app/backend")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _mk_trade(tid, symbol, age_seconds):
    """Build a SimpleNamespace pending trade with a `pre_submit_at`
    that's `age_seconds` old."""
    ts = _iso(_now() - timedelta(seconds=age_seconds))
    return SimpleNamespace(
        id=tid, symbol=symbol,
        pre_submit_at=ts, created_at=ts,
        status=SimpleNamespace(value="pending"),
        notes="", close_reason=None, closed_at=None,
    )


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot = tb._trading_bot
    bot = SimpleNamespace(
        _pending_trades={},
        _save_trade=AsyncMock(return_value=None),
    )
    tb._trading_bot = bot
    yield bot, tb.clear_stale_pending_trades, tb.ClearStalePendingRequest
    tb._trading_bot = orig_bot


@pytest.mark.asyncio
async def test_dry_run_reports_without_mutating(patched_app):
    bot, handler, Req = patched_app
    bot._pending_trades = {
        "old-nbis": _mk_trade("old-nbis", "NBIS", age_seconds=3600),
        "fresh-aapl": _mk_trade("fresh-aapl", "AAPL", age_seconds=60),
    }
    resp = await handler(Req(older_than_s=1800, dry_run=True))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert resp["removed_count"] == 1
    assert resp["removed"][0]["symbol"] == "NBIS"
    assert resp["still_pending"][0]["symbol"] == "AAPL"
    # Pending dict untouched.
    assert set(bot._pending_trades.keys()) == {"old-nbis", "fresh-aapl"}
    bot._save_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_removes_stale_and_persists_rejected(patched_app):
    bot, handler, Req = patched_app
    stale = _mk_trade("old-nbis", "NBIS", age_seconds=3600)
    bot._pending_trades = {"old-nbis": stale}
    resp = await handler(Req(older_than_s=1800, dry_run=False))
    assert resp["removed_count"] == 1
    # Pending dict pruned.
    assert "old-nbis" not in bot._pending_trades
    # _save_trade was called with the trade in REJECTED status.
    bot._save_trade.assert_awaited_once()
    awaited_arg = bot._save_trade.call_args[0][0]
    from services.trading_bot_service import TradeStatus
    assert awaited_arg.status == TradeStatus.REJECTED
    assert awaited_arg.close_reason == "stale_pending_cleared_v19_34_78"
    assert "STALE-PENDING-CLEARED-v19.34.78" in awaited_arg.notes


@pytest.mark.asyncio
async def test_older_than_threshold_respected(patched_app):
    bot, handler, Req = patched_app
    bot._pending_trades = {
        "10-min-old": _mk_trade("10-min-old", "XYZ", age_seconds=600),
    }
    # Threshold = 30 min → 10-min trade NOT stale.
    resp = await handler(Req(older_than_s=1800, dry_run=True))
    assert resp["removed_count"] == 0
    assert resp["still_pending"][0]["trade_id"] == "10-min-old"

    # Threshold = 5 min → now stale.
    resp = await handler(Req(older_than_s=300, dry_run=True))
    assert resp["removed_count"] == 1


@pytest.mark.asyncio
async def test_symbols_filter_narrows_candidates(patched_app):
    bot, handler, Req = patched_app
    bot._pending_trades = {
        "nbis-id": _mk_trade("nbis-id", "NBIS", age_seconds=3600),
        "mu-id": _mk_trade("mu-id", "MU", age_seconds=3600),
        "coin-id": _mk_trade("coin-id", "COIN", age_seconds=3600),
    }
    resp = await handler(Req(
        older_than_s=1800, dry_run=True,
        symbols=["NBIS", "MU"],
    ))
    syms_removed = sorted(c["symbol"] for c in resp["removed"])
    assert syms_removed == ["MU", "NBIS"]
    # COIN ignored because symbol filter excluded it.
    assert all(c["symbol"] != "COIN" for c in resp["removed"])


@pytest.mark.asyncio
async def test_trade_with_no_timestamp_is_treated_as_stale(patched_app):
    """Safer to drop a zombie with no timestamp than keep it blocking
    re-evaluation forever."""
    bot, handler, Req = patched_app
    no_ts = SimpleNamespace(
        id="ghost", symbol="GHOST",
        pre_submit_at=None, created_at=None,
        status=SimpleNamespace(value="pending"),
        notes="", close_reason=None, closed_at=None,
    )
    bot._pending_trades = {"ghost": no_ts}
    resp = await handler(Req(older_than_s=99999, dry_run=True))
    assert resp["removed_count"] == 1
    assert resp["removed"][0]["age_s"] is None


@pytest.mark.asyncio
async def test_empty_pending_returns_clean(patched_app):
    bot, handler, Req = patched_app
    bot._pending_trades = {}
    resp = await handler(Req(older_than_s=1800, dry_run=False))
    assert resp["success"] is True
    assert resp["removed_count"] == 0
    assert resp["removed"] == []
    assert resp["still_pending"] == []


@pytest.mark.asyncio
async def test_apply_does_not_mutate_filtered_out_trades(patched_app):
    """Symbol-filtered-out trades + non-stale trades must remain in
    `_pending_trades` after a non-dry-run call."""
    bot, handler, Req = patched_app
    bot._pending_trades = {
        "nbis": _mk_trade("nbis", "NBIS", age_seconds=3600),
        "mu": _mk_trade("mu", "MU", age_seconds=3600),
        "fresh-aapl": _mk_trade("fresh-aapl", "AAPL", age_seconds=60),
    }
    await handler(Req(
        older_than_s=1800, dry_run=False,
        symbols=["NBIS"],
    ))
    # NBIS gone; MU and AAPL still there (MU was stale but not in filter).
    assert set(bot._pending_trades.keys()) == {"mu", "fresh-aapl"}
