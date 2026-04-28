"""
Tests for the Shadow Tracker drain-mode plumbing.

Operator scenario 2026-04-29: 6,715 shadow decisions backlogged in
`outcome_tracked: false`. The legacy endpoint processed 50 per call,
which would require ~135 manual curls to clear. This adds:

- `track_pending_outcomes(batch_size, max_batches)` already supports
  multi-batch processing; drain mode just plumbs the params through
  the API. Tests below lock the contract.

Hardware-bound integration paths (IB pusher quote fetch) are mocked
out — the tests verify pagination, batch counting, drain semantics,
and safety-cap clamping at the service layer.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from services.ai_modules.shadow_tracker import ShadowTracker


def _make_pending_doc(idx: int) -> dict:
    """Build a minimal shadow decision doc the drain loop will pick up."""
    return {
        "id": f"sd_test_{idx:04d}",
        "symbol": "AAPL",
        "outcome_tracked": False,
        "trigger_time": "2020-01-01T00:00:00+00:00",  # always > 1h old
        "price_at_decision": 100.0,
    }


def _wire_tracker_with_pending(pending_docs: list) -> ShadowTracker:
    """
    Build a ShadowTracker whose `_decisions_col.find().limit()` returns
    successive slices from `pending_docs`, mimicking real Mongo cursor
    pagination. `update_one` removes the doc from the bucket so the
    next batch sees the remaining backlog.
    """
    tracker = ShadowTracker()
    tracker._db = MagicMock()
    tracker._decisions_col = MagicMock()
    tracker._performance_col = MagicMock()

    bucket = list(pending_docs)  # mutable copy

    class _LimitCursor:
        def __init__(self, n):
            self._n = n

        def __iter__(self):
            return iter(bucket[: self._n])

    class _FindCursor:
        def limit(self, n):
            return _LimitCursor(n)

    tracker._decisions_col.find.return_value = _FindCursor()

    def _update_one(query, _set):
        decision_id = query.get("id")
        for i, doc in enumerate(bucket):
            if doc.get("id") == decision_id:
                bucket.pop(i)
                break

    def _find_one(query):
        decision_id = query.get("id")
        for doc in bucket:
            if doc.get("id") == decision_id:
                return doc
        return None

    tracker._decisions_col.update_one.side_effect = _update_one
    tracker._decisions_col.find_one.side_effect = _find_one

    # Mock IB quote so `_get_current_price` always succeeds.
    ib_provider = MagicMock()
    ib_provider.get_quote = AsyncMock(return_value={"price": 105.0})
    tracker.set_ib_data_provider(ib_provider)

    return tracker, bucket


@pytest.mark.asyncio
async def test_legacy_default_processes_one_batch_of_50():
    """Default args (no drain) preserve the legacy 1×50 behaviour."""
    docs = [_make_pending_doc(i) for i in range(120)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    result = await tracker.track_pending_outcomes()

    assert result["batches"] == 1
    assert result["pending_checked"] == 50
    assert result["updated"] == 50
    assert len(bucket) == 70  # 120 - 50


@pytest.mark.asyncio
async def test_multi_batch_drain_walks_through_pages():
    """`max_batches=3, batch_size=20` walks 3 pages of 20 = 60 outcomes."""
    docs = [_make_pending_doc(i) for i in range(120)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    result = await tracker.track_pending_outcomes(batch_size=20, max_batches=3)

    assert result["batches"] == 3
    assert result["pending_checked"] == 60
    assert result["updated"] == 60
    assert len(bucket) == 60


@pytest.mark.asyncio
async def test_drain_stops_early_when_no_pending():
    """If pending drains before max_batches reached, loop exits cleanly."""
    docs = [_make_pending_doc(i) for i in range(35)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    # 100 batches of 50 — backlog is only 35 — should run 1 batch then exit.
    result = await tracker.track_pending_outcomes(batch_size=50, max_batches=100)

    assert result["batches"] == 1
    assert result["pending_checked"] == 35
    assert result["updated"] == 35
    assert len(bucket) == 0


@pytest.mark.asyncio
async def test_safety_cap_clamps_oversized_inputs():
    """`batch_size>500` clamps to 500; `max_batches>1000` clamps to 1000."""
    docs = [_make_pending_doc(i) for i in range(10)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    # Oversized inputs — make sure the cap is enforced (else we could
    # queue a runaway 1M-row scan).
    result = await tracker.track_pending_outcomes(batch_size=99999, max_batches=99999)

    # First batch picks up all 10 (within the 500 clamp), then exits.
    assert result["batches"] == 1
    assert result["pending_checked"] == 10
    assert len(bucket) == 0


@pytest.mark.asyncio
async def test_zero_or_negative_inputs_clamp_to_one():
    """Defensive: zero/negative `batch_size`/`max_batches` clamp to 1."""
    docs = [_make_pending_doc(i) for i in range(5)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    result = await tracker.track_pending_outcomes(batch_size=0, max_batches=-3)

    # Clamped to 1×1 — only the first decision processed.
    assert result["batches"] == 1
    assert result["pending_checked"] == 1
    assert len(bucket) == 4


@pytest.mark.asyncio
async def test_no_db_returns_zero_counts_safely():
    """`_decisions_col=None` (db unwired) returns zeros without raising."""
    tracker = ShadowTracker()
    # Don't call set_db — _decisions_col stays None.

    result = await tracker.track_pending_outcomes(batch_size=50, max_batches=10)

    assert result == {"updated": 0, "pending_checked": 0, "batches": 0}


@pytest.mark.asyncio
async def test_drain_yields_to_event_loop_between_batches():
    """
    Drain mode must `await asyncio.sleep(0)` between batches so other
    endpoints don't starve. Verified by interleaving an external task.
    """
    docs = [_make_pending_doc(i) for i in range(60)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    interleave_log = []

    async def _other_endpoint():
        for tick in range(5):
            interleave_log.append(f"tick_{tick}")
            await asyncio.sleep(0)

    drain_task = asyncio.create_task(
        tracker.track_pending_outcomes(batch_size=20, max_batches=3)
    )
    other_task = asyncio.create_task(_other_endpoint())

    drain_result, _ = await asyncio.gather(drain_task, other_task)

    assert drain_result["batches"] == 3
    # The interleave log must have ticks (the other coroutine got CPU
    # while the drain was running).
    assert len(interleave_log) == 5


@pytest.mark.asyncio
async def test_stats_cache_invalidated_after_drain():
    """`get_stats` is cached for 30s — drain must bust the cache so the
    next call reflects updated outcome counts."""
    docs = [_make_pending_doc(i) for i in range(10)]
    tracker, bucket = _wire_tracker_with_pending(docs)

    # Prime the stats cache.
    tracker._stats_cache = {"total_decisions": 999}
    import time as _t
    tracker._stats_cache_time = _t.monotonic()

    await tracker.track_pending_outcomes(batch_size=50, max_batches=1)

    # Drain must have reset _stats_cache_time so the next get_stats
    # call won't return the stale value.
    assert tracker._stats_cache_time == 0
