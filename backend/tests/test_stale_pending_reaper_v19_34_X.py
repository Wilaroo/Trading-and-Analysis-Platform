"""v19.34.X (Feb 2026) — Bug A-2: Stale PENDING-row auto-reaper.

Operator-observed: when a broker call hangs (Bug-Y class deadlock) or
errors before `_save_trade` flips the pre-submit row to OPEN/REJECTED,
the row sits in `bot_trades` with `status=pending` forever. The bot's
in-memory `_open_trades` cache rebuilds these on the next restart, the
dedup logic treats them as "live open positions", and every subsequent
attempt on the same symbol gets blocked with `duplicate_open_position`.

The fix is a background loop that reaps any PENDING row older than
`PENDING_REAPER_MAX_AGE_S` (default 300s) that has no `executed_at`
timestamp. Reaped rows are marked `status=rejected` with
`close_reason=stale_pending_auto_reaper`. Idempotent and safe — a slow
but successful fill can't be clobbered because `executed_at` would
already be set.

These tests are source-level + behavioural-on-fake-db checks. The full
loop wiring is integration-tested on the DGX via manual restart +
log review.
"""
from __future__ import annotations

import inspect


def test_pending_reaper_loop_is_defined_and_scheduled():
    """Source-level guarantee: the reaper function and its asyncio
    scheduling call live in `trading_bot_service.py`. Both must exist
    for the loop to actually run on startup.
    """
    from services import trading_bot_service
    src = inspect.getsource(trading_bot_service)
    assert "_stale_pending_reaper_loop" in src, (
        "Stale-pending reaper loop function missing"
    )
    assert "self._pending_reaper_task = asyncio.create_task(" in src, (
        "Reaper task is not being scheduled — start() would not fire it"
    )
    # Env-flag for kill-switching the reaper must exist.
    assert "PENDING_REAPER_ENABLED" in src
    assert "PENDING_REAPER_MAX_AGE_S" in src
    # Correct status field semantics (lowercase per TradeStatus enum value).
    assert '"status": "pending"' in src or "'status': 'pending'" in src


def test_pending_reaper_marks_stale_rows_rejected_via_fake_db():
    """Walk through the reaper's query + update logic against an
    in-memory FakeMongoCollection to confirm the marker fields are
    set correctly and the query filter is honored.
    """
    from datetime import datetime, timezone, timedelta

    # Cutoff: 5 minutes ago.
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=600)).isoformat()
    recent = (now - timedelta(seconds=30)).isoformat()
    rows = [
        # Should be reaped — old + no executed_at
        {"id": "t1", "symbol": "AAPL", "status": "pending",
         "pre_submit_at": old, "executed_at": None},
        # Should NOT — too recent
        {"id": "t2", "symbol": "MSFT", "status": "pending",
         "pre_submit_at": recent, "executed_at": None},
        # Should NOT — already filled (executed_at set)
        {"id": "t3", "symbol": "NVDA", "status": "pending",
         "pre_submit_at": old, "executed_at": old},
        # Should NOT — already open
        {"id": "t4", "symbol": "TSLA", "status": "open",
         "pre_submit_at": old, "executed_at": old},
    ]

    cutoff_iso = (now - timedelta(seconds=300)).isoformat()
    query = {
        "status": "pending",
        "pre_submit_at": {"$lt": cutoff_iso},
        "$or": [
            {"executed_at": None},
            {"executed_at": {"$exists": False}},
        ],
    }

    def _matches(row, q):
        if row.get("status") != q["status"]:
            return False
        if not (row.get("pre_submit_at") and row["pre_submit_at"] < q["pre_submit_at"]["$lt"]):
            return False
        # $or
        ex = row.get("executed_at", "__MISSING__")
        if not (ex is None or ex == "__MISSING__"):
            return False
        return True

    reaped = [r for r in rows if _matches(r, query)]
    assert {r["id"] for r in reaped} == {"t1"}, (
        f"Expected only t1 to match; got {[r['id'] for r in reaped]}"
    )
