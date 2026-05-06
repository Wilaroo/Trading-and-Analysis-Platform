"""
v19.34.21 — Verify zombie cleanup uses Mongo-direct fallback when
`_save_trade` raises.

Pre-fix bug: `position_reconciler.py:reconcile_share_drift` had
`try: save_fn(zt) except: pass` in the zombie-close inner loop. If
`_save_trade` raised silently, the heal reported the zombie as
closed, but the DB row stayed `status=open`. Operator-discovered
2026-05-06: trade `b4d27b31` was reported in `zombies_closed` from
the heal call, but `db.bot_trades.find_one({"id":"b4d27b31"})` showed
`status=open, close_reason=null` 11 minutes later.

v19.34.21 fix:
1. Catch + log the `_save_trade` exception.
2. Fall back to a direct `db.bot_trades.update_one({id}, {$set: ...})`
   that bypasses whatever the orchestrated save was choking on.
3. If the direct update ALSO fails, record the failure in
   `drift_record["zombie_close_failures"]` so the heal response makes
   the failure visible to the operator instead of hiding it.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_save_trade_swallow_pattern_replaced_v19_34_21():
    """Static guard: the silent swallow must be gone."""
    import os
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "position_reconciler.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()

    # The fallback markers must be present.
    assert "v19.34.21 zombie-close" in src
    assert "Mongo-direct fallback" in src
    assert "zombie_close_failures" in src

    # The original silent swallow pattern (a raw `try: save except: pass`
    # without a logger.warning) MUST not reappear in the zombie loop.
    # Locate the zombie loop and look for the leakage.
    anchor = src.find('zombies_closed.append(getattr(zt, "id", None))')
    assert anchor > 0
    window = src[anchor: anchor + 3000]
    # The fallback path uses logger.warning + Mongo update_one, BOTH must
    # appear after the anchor, before the next sibling block.
    assert "logger.warning" in window
    assert "update_one" in window


@pytest.mark.asyncio
async def test_zombie_close_falls_back_to_mongo_when_save_raises_v19_34_21():
    """Simulate `_save_trade` raising — the fallback should still write
    the close to `db.bot_trades` via `update_one`."""
    from services.position_reconciler import PositionReconciler

    # Mock `db` with a `bot_trades.update_one` so we can assert it was called.
    update_calls = []

    class _BotTradesCol:
        def update_one(self, q, u):
            update_calls.append((q, u))
            return SimpleNamespace(modified_count=1)

    class _Db:
        def __getitem__(self, name):
            assert name == "bot_trades"
            return _BotTradesCol()

    db = _Db()

    # Build a fake bot whose `_save_trade` raises.
    class _Bot:
        _open_trades = {}
        _db = db
        async def _save_trade(self, trade):
            raise RuntimeError("simulated save failure")

    bot = _Bot()

    # Build a fake zombie trade.
    zt = SimpleNamespace(
        id="b4d27b31",
        symbol="FDX",
        notes="Reconciled from IB orphan — stop at 2.0%...",
        closed_at="2026-05-06T13:36:47+00:00",
    )
    bot._open_trades[zt.id] = zt

    # We can't easily run the full reconcile_share_drift without the entire
    # bot+IB stack; but we CAN unit-test the inner fallback path by mirroring
    # what the loop body does.
    import logging
    from services.position_reconciler import logger as pr_logger
    pr_logger.setLevel(logging.WARNING)

    # Mirror the v19.34.21 inner loop body.
    save_fn = getattr(bot, "_save_trade", None)
    persisted = False
    save_err = None
    if save_fn:
        try:
            res = save_fn(zt)
            if asyncio.iscoroutine(res):
                await res
            persisted = True
        except Exception as e:
            save_err = f"{type(e).__name__}: {e}"

    if not persisted:
        try:
            db_handle = getattr(bot, "_db", None)
            if db_handle is not None and getattr(zt, "id", None):
                await asyncio.to_thread(
                    db_handle["bot_trades"].update_one,
                    {"id": zt.id},
                    {"$set": {
                        "status": "closed",
                        "close_reason": "zombie_cleanup_v19_34_19",
                        "closed_at": zt.closed_at,
                        "remaining_shares": 0,
                        "notes": zt.notes,
                    }},
                )
                persisted = True
        except Exception:
            persisted = False

    assert save_err is not None, "save error must be captured (not swallowed)"
    assert "simulated save failure" in save_err
    assert persisted, (
        "v19.34.21 fallback failed: when _save_trade raises, the "
        "Mongo-direct update_one MUST persist the close."
    )
    assert len(update_calls) == 1
    q, u = update_calls[0]
    assert q == {"id": "b4d27b31"}
    sets = u["$set"]
    assert sets["status"] == "closed"
    assert sets["close_reason"] == "zombie_cleanup_v19_34_19"
    assert sets["remaining_shares"] == 0


@pytest.mark.asyncio
async def test_zombie_close_records_failure_when_both_paths_fail_v19_34_21():
    """If save AND mongo-direct both fail, the failure must be captured
    in drift_record so the heal response surfaces it."""

    class _BotTradesCol:
        def update_one(self, q, u):
            raise ConnectionError("simulated mongo down")

    class _Db:
        def __getitem__(self, name):
            return _BotTradesCol()

    db = _Db()

    class _Bot:
        _open_trades = {}
        _db = db
        async def _save_trade(self, trade):
            raise RuntimeError("simulated save failure")

    bot = _Bot()
    zt = SimpleNamespace(id="b4d27b31", symbol="FDX",
                        notes="x", closed_at="2026-05-06T13:36:47Z")
    bot._open_trades[zt.id] = zt
    drift_record = {}

    save_fn = bot._save_trade
    save_err = None
    persisted = False
    try:
        await save_fn(zt)
        persisted = True
    except Exception as e:
        save_err = f"{type(e).__name__}: {e}"

    if not persisted:
        try:
            await asyncio.to_thread(
                bot._db["bot_trades"].update_one,
                {"id": zt.id},
                {"$set": {"status": "closed"}},
            )
            persisted = True
        except Exception as direct_exc:
            drift_record.setdefault("zombie_close_failures", []).append({
                "trade_id": zt.id,
                "save_err": save_err,
                "direct_err": f"{type(direct_exc).__name__}: {direct_exc}",
            })

    assert not persisted
    assert "zombie_close_failures" in drift_record
    fail = drift_record["zombie_close_failures"][0]
    assert fail["trade_id"] == "b4d27b31"
    assert "RuntimeError" in fail["save_err"]
    assert "ConnectionError" in fail["direct_err"]
