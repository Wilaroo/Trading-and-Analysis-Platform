"""v19.34.148 — Entry-price ↔ IB.avgCost sync regression.

Pinned tests for `services/entry_price_sync.py`. Walks every open
BotTrade, snaps its `entry_price` to IB's live `avgCost`, persists
the change to `bot_trades`. The fix targets the ICLN / CW / ITT /
DKS / DG drift class identified by v19.34.147 audit.

Contracts pinned by these tests:
  1. Read IB.avgCost from `routers.ib._pushed_ib_data["positions"]`
  2. No-op when |bot.entry - ib.avgCost| ≤ tolerance_per_share
  3. dry_run mode reports but does NOT mutate
  4. Mutates BOTH `entry_price` AND `fill_price` in lockstep
  5. Persists to MongoDB `bot_trades` with audit columns
     (entry_price_pre_sync, entry_price_synced_at,
     entry_price_sync_source)
  6. Skips zombie trades (remaining_shares == 0)
  7. Symbol filter limits scope without breaking the report shape
  8. Direction-aware implied_pnl_correction sign:
       LONG  → ib.avgCost > bot.entry → bot was OVER-stating (negative correction)
       SHORT → ib.avgCost > bot.entry → bot was UNDER-stating (positive correction)
  9. Returns `success=False` (with `reason`) when IB snapshot is empty
"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_trade(*, tid, symbol, qty, entry_price, direction="long",
                remaining=None):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.shares = qty
    t.remaining_shares = remaining if remaining is not None else qty
    t.entry_price = entry_price
    t.fill_price = entry_price
    direction_mock = MagicMock()
    direction_mock.value = direction
    t.direction = direction_mock
    return t


def _make_bot(*, open_trades, db=None):
    bot = MagicMock()
    bot._open_trades = open_trades
    bot._db = db
    return bot


def _patch_ib(monkeypatch, positions):
    fake_ib = type(sys)("routers.ib")
    fake_ib._pushed_ib_data = {"positions": positions}
    monkeypatch.setitem(sys.modules, "routers.ib", fake_ib)


def _make_db():
    """Async MongoDB-shaped mock with the `bot_trades` collection."""
    db = MagicMock()
    coll = MagicMock()
    coll.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    db.__getitem__ = MagicMock(return_value=coll)
    return db, coll


# ────────────────────────────────────────────────────────────────────
# 1. Happy path — ICLN, CW, ITT sync at once
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_icln_cw_itt_sync_live(monkeypatch):
    """The three drift offenders from the operator's live audit, all
    handled in one sync call. Persisted to db, mutated in memory."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "ICLN", "position": 3229, "avgCost": 21.975},
        {"symbol": "CW",   "position": 24,   "avgCost": 746.13},
        {"symbol": "ITT",  "position": -132, "avgCost": 204.97},
    ])
    t_icln = _make_trade(tid="t-icln", symbol="ICLN", qty=3229,
                         entry_price=21.96, direction="long")
    t_cw   = _make_trade(tid="t-cw",   symbol="CW",   qty=24,
                         entry_price=744.29, direction="long")
    t_itt  = _make_trade(tid="t-itt",  symbol="ITT",  qty=132,
                         entry_price=204.68, direction="short")
    db, coll = _make_db()
    bot = _make_bot(
        open_trades={"t-icln": t_icln, "t-cw": t_cw, "t-itt": t_itt},
        db=db,
    )

    report = await sync_entry_prices_to_ib_avg_cost(bot)

    assert report["success"] is True
    assert report["mode"] == "live"
    assert len(report["synced"]) == 3
    by_sym = {s["symbol"]: s for s in report["synced"]}

    # In-memory mutated to IB.avgCost.
    assert t_icln.entry_price == pytest.approx(21.975, abs=0.001)
    assert t_cw.entry_price == pytest.approx(746.13, abs=0.001)
    assert t_itt.entry_price == pytest.approx(204.97, abs=0.001)
    # fill_price kept in lockstep.
    assert t_icln.fill_price == pytest.approx(21.975, abs=0.001)
    assert t_cw.fill_price == pytest.approx(746.13, abs=0.001)

    # Per-row delta_per_share is signed (ib - bot).
    assert by_sym["ICLN"]["delta_per_share"] == pytest.approx(0.015, abs=0.001)
    assert by_sym["CW"]["delta_per_share"] == pytest.approx(1.84, abs=0.01)
    assert by_sym["ITT"]["delta_per_share"] == pytest.approx(0.29, abs=0.01)

    # LONG: ib.avgCost > bot.entry → NEGATIVE correction (bot was overstating).
    assert by_sym["ICLN"]["implied_pnl_correction"] < 0
    assert by_sym["CW"]["implied_pnl_correction"] < 0
    # SHORT: ib.avgCost > bot.entry → POSITIVE correction.
    assert by_sym["ITT"]["implied_pnl_correction"] > 0

    # Persistence: 3 update_one calls (one per synced trade).
    assert coll.update_one.await_count == 3
    # Each persists the audit columns.
    first_call_args = coll.update_one.await_args_list[0]
    set_block = first_call_args.args[1]["$set"]
    assert "entry_price_pre_sync" in set_block
    assert "entry_price_synced_at" in set_block
    assert set_block["entry_price_sync_source"] == "ib_avg_cost"
    assert report["persisted_to_db"] == 3


# ────────────────────────────────────────────────────────────────────
# 2. Tolerance gate
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sub_tolerance_drift_skipped(monkeypatch):
    """DG-style 0.003/sh drift falls inside default 0.01 tolerance →
    no sync, no DB write, no in-memory mutation."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "DG", "position": -317, "avgCost": 101.103},
    ])
    t_dg = _make_trade(tid="t-dg", symbol="DG", qty=317,
                       entry_price=101.10, direction="short")
    db, coll = _make_db()
    bot = _make_bot(open_trades={"t-dg": t_dg}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(bot)

    assert report["success"] is True
    assert len(report["synced"]) == 0
    assert len(report["skipped_within_tol"]) == 1
    assert report["skipped_within_tol"][0]["symbol"] == "DG"
    # No mutation.
    assert t_dg.entry_price == pytest.approx(101.10, abs=0.001)
    coll.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_tolerance_widens_skip(monkeypatch):
    """Tolerance 0.5/sh → CW (1.84/sh) still syncs; ITT (0.29/sh)
    drops to within tolerance and skips."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "CW",  "position": 24,   "avgCost": 746.13},
        {"symbol": "ITT", "position": -132, "avgCost": 204.97},
    ])
    t_cw  = _make_trade(tid="t-cw",  symbol="CW",  qty=24,
                        entry_price=744.29, direction="long")
    t_itt = _make_trade(tid="t-itt", symbol="ITT", qty=132,
                        entry_price=204.68, direction="short")
    db, _ = _make_db()
    bot = _make_bot(open_trades={"t-cw": t_cw, "t-itt": t_itt}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(
        bot, tolerance_per_share=0.5
    )

    synced_syms = {s["symbol"] for s in report["synced"]}
    skipped_syms = {s["symbol"] for s in report["skipped_within_tol"]}
    assert synced_syms == {"CW"}
    assert skipped_syms == {"ITT"}


# ────────────────────────────────────────────────────────────────────
# 3. Dry run
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_reports_but_does_not_mutate(monkeypatch):
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "ICLN", "position": 100, "avgCost": 28.95},
    ])
    t_icln = _make_trade(tid="t-icln", symbol="ICLN", qty=100,
                         entry_price=28.50, direction="long")
    db, coll = _make_db()
    bot = _make_bot(open_trades={"t-icln": t_icln}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(bot, dry_run=True)

    assert report["mode"] == "dry_run"
    assert len(report["synced"]) == 1
    assert report["synced"][0]["applied"] is False
    assert t_icln.entry_price == pytest.approx(28.50, abs=0.001)
    coll.update_one.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 4. Edge cases
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zombie_trade_skipped(monkeypatch):
    """A trade with remaining_shares=0 is on its way to closed and
    must NOT have its entry_price rewritten (could mask a real bug)."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "DEAD", "position": 100, "avgCost": 50.0},
    ])
    zombie = _make_trade(tid="z", symbol="DEAD", qty=100,
                         entry_price=45.0, remaining=0)
    db, coll = _make_db()
    bot = _make_bot(open_trades={"z": zombie}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(bot)
    assert len(report["synced"]) == 0
    assert report["candidates"] == 0
    coll.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_symbol_filter_limits_scope(monkeypatch):
    """`symbols=['ICLN']` skips CW even though it's drifting."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "ICLN", "position": 100, "avgCost": 28.95},
        {"symbol": "CW",   "position": 24,  "avgCost": 746.13},
    ])
    t_icln = _make_trade(tid="t-icln", symbol="ICLN", qty=100,
                         entry_price=28.50)
    t_cw   = _make_trade(tid="t-cw",   symbol="CW",   qty=24,
                         entry_price=744.29)
    db, _ = _make_db()
    bot = _make_bot(open_trades={"t-icln": t_icln, "t-cw": t_cw}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(
        bot, symbols=["ICLN"]
    )
    synced_syms = {s["symbol"] for s in report["synced"]}
    assert synced_syms == {"ICLN"}
    # CW untouched.
    assert t_cw.entry_price == pytest.approx(744.29, abs=0.001)


@pytest.mark.asyncio
async def test_no_ib_snapshot_returns_failure(monkeypatch):
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost
    _patch_ib(monkeypatch, [])  # empty positions
    t = _make_trade(tid="t1", symbol="ANY", qty=10, entry_price=100.0)
    db, _ = _make_db()
    bot = _make_bot(open_trades={"t1": t}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(bot)
    assert report["success"] is False
    assert report["reason"] == "no_ib_positions_in_pusher_snapshot"


@pytest.mark.asyncio
async def test_symbol_missing_from_ib_skipped_no_data(monkeypatch):
    """Bot tracks SOMEWAT — IB doesn't know about it (drift). Row
    goes to `skipped_no_ib_data`, not into sync."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "ICLN", "position": 100, "avgCost": 28.95},
    ])
    t_icln = _make_trade(tid="t-icln", symbol="ICLN", qty=100,
                         entry_price=28.50)
    t_orphan = _make_trade(tid="t-orph", symbol="SOMEWAT", qty=50,
                           entry_price=10.0)
    db, _ = _make_db()
    bot = _make_bot(
        open_trades={"t-icln": t_icln, "t-orph": t_orphan}, db=db
    )

    report = await sync_entry_prices_to_ib_avg_cost(bot)
    synced_syms = {s["symbol"] for s in report["synced"]}
    skipped_syms = {s["symbol"] for s in report["skipped_no_ib_data"]}
    assert synced_syms == {"ICLN"}
    assert skipped_syms == {"SOMEWAT"}


@pytest.mark.asyncio
async def test_zero_entry_price_skipped(monkeypatch):
    """A trade with entry_price=0 is broken — don't sync (we don't
    have a meaningful pre-sync value to record)."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost
    _patch_ib(monkeypatch, [
        {"symbol": "ZERO", "position": 10, "avgCost": 50.0},
    ])
    broken = _make_trade(tid="z", symbol="ZERO", qty=10, entry_price=0)
    db, _ = _make_db()
    bot = _make_bot(open_trades={"z": broken}, db=db)

    report = await sync_entry_prices_to_ib_avg_cost(bot)
    assert len(report["synced"]) == 0
    assert any(
        s.get("reason", "").startswith("bot_entry_price_missing")
        for s in report["skipped_no_ib_data"]
    )


# ────────────────────────────────────────────────────────────────────
# 5. Persistence error handling
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_persist_failure_does_not_block_other_syncs(monkeypatch):
    """If one trade's db update_one raises, the sync continues for
    the others and reports the failure in `persist_errors`."""
    from services.entry_price_sync import sync_entry_prices_to_ib_avg_cost

    _patch_ib(monkeypatch, [
        {"symbol": "GOOD", "position": 100, "avgCost": 50.0},
        {"symbol": "BAD",  "position": 100, "avgCost": 60.0},
    ])
    t_good = _make_trade(tid="g", symbol="GOOD", qty=100,
                         entry_price=49.0)
    t_bad  = _make_trade(tid="b", symbol="BAD",  qty=100,
                         entry_price=58.0)

    db = MagicMock()
    coll = MagicMock()
    # Fail only for "b".
    call_count = {"n": 0}

    async def _fake_update(filt, *_a, **_kw):
        call_count["n"] += 1
        if filt.get("id") == "b":
            raise RuntimeError("connection reset")
        return MagicMock(modified_count=1)
    coll.update_one = _fake_update
    db.__getitem__ = MagicMock(return_value=coll)

    bot = _make_bot(open_trades={"g": t_good, "b": t_bad}, db=db)
    report = await sync_entry_prices_to_ib_avg_cost(bot)

    # Both reported as synced (in-memory mutated successfully).
    assert len(report["synced"]) == 2
    # But persist_errors has the BAD one.
    err_syms = {e["symbol"] for e in report["persist_errors"]}
    assert err_syms == {"BAD"}
    # GOOD did persist.
    assert report["persisted_to_db"] == 1
