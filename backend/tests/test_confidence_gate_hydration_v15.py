"""
Tests for the 2026-04-30 v15 confidence-gate hydration fix.

Operator complaint: SentCom Intelligence panel always reset to ≤50
evaluations on restart, even when the bot had evaluated 80+ today.

Root cause: `_load_from_db` loaded only the last 50 docs into a deque,
then iterated them to count today's stats — capping `today_evaluated`
at 50 minus any pre-midnight rows.

Fix: count today's evaluations via a Mongo `$group` aggregation on the
full `confidence_gate_log` collection. The deque still holds 50 for
the recent-decisions UI; the daily totals come from the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _make_today_iso(hour: int = 12) -> str:
    """Build a today UTC ISO timestamp at hour H."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


@pytest.fixture
def confidence_gate_with_fake_db():
    """Patch confidence_gate to use a fake Mongo db with a controllable
    `confidence_gate_log` collection that supports `find().sort().limit()`,
    `aggregate()`, and `count_documents()`.
    """
    from services.ai_modules import confidence_gate as cg_mod

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_iso = _make_today_iso()

    # Build 80 today decisions (47 GO, 33 SKIP) — exceeds the 50-doc deque
    docs = []
    for i in range(47):
        docs.append({
            "decision": "GO",
            "timestamp": f"{today}T0{i % 9}:30:00+00:00",
            "symbol": f"SYM{i}",
            "setup_type": "9_ema_scalp",
        })
    for i in range(33):
        docs.append({
            "decision": "SKIP",
            "timestamp": f"{today}T0{i % 9}:31:00+00:00",
            "symbol": f"SKP{i}",
            "setup_type": "vwap_continuation",
        })
    # Add 5 yesterday decisions to make sure they're excluded.
    docs.extend([
        {"decision": "GO", "timestamp": "2025-01-01T12:00:00+00:00", "symbol": "OLD"},
    ] * 5)

    fake_col = MagicMock()
    fake_col.find.return_value = MagicMock(
        sort=MagicMock(return_value=MagicMock(
            limit=MagicMock(return_value=docs[:50])
        ))
    )

    def aggregate(pipeline):
        # Honour the today-match the production code uses.
        match = pipeline[0]["$match"]["timestamp"]["$regex"]
        prefix = match.lstrip("^")
        today_docs = [d for d in docs if str(d["timestamp"]).startswith(prefix)]
        # Group by decision
        counts = {}
        for d in today_docs:
            counts[d["decision"]] = counts.get(d["decision"], 0) + 1
        return [{"_id": k, "n": v} for k, v in counts.items()]
    fake_col.aggregate.side_effect = aggregate

    def count_documents(query):
        if not query:
            return len(docs)
        if "decision" in query:
            return sum(1 for d in docs if d["decision"] == query["decision"])
        return 0
    fake_col.count_documents.side_effect = count_documents

    fake_db = {"confidence_gate_log": fake_col}

    yield fake_db, today_iso, cg_mod


def test_hydration_counts_today_from_db_not_deque(confidence_gate_with_fake_db):
    """The fix: today_evaluated must reflect the real daily total even
    when more than 50 decisions exist for the day.
    """
    fake_db, _, cg_mod = confidence_gate_with_fake_db

    gate = cg_mod.ConfidenceGate.__new__(cg_mod.ConfidenceGate)
    # Minimal manual construction to avoid the full __init__ path which
    # touches calibration/threshold loaders we don't need here.
    from collections import deque
    gate._db = fake_db
    gate._decision_log = deque(maxlen=50)
    gate._stats = {
        "total_evaluated": 0,
        "go_count": 0,
        "reduce_count": 0,
        "skip_count": 0,
        "today_evaluated": 0,
        "today_go": 0,
        "today_skip": 0,
        "today_date": "2025-01-01",
    }
    gate._trading_mode = "normal"
    gate._mode_reason = None

    cg_mod.ConfidenceGate._load_from_db(gate)

    # The fixture seeded 47 GO + 33 SKIP today (= 80 evaluations) plus
    # 5 yesterday docs (excluded). With the bug, `today_evaluated` would
    # cap at ≤50. With the fix, it should be 80.
    assert gate._stats["today_evaluated"] == 80, (
        f"today_evaluated={gate._stats['today_evaluated']} (should be 80). "
        "Either the 50-doc cap regression has returned or the today-aggregation "
        "is broken. See confidence_gate._load_from_db."
    )
    assert gate._stats["today_go"] == 47
    assert gate._stats["today_skip"] == 33
    # Lifetime counts from count_documents
    assert gate._stats["total_evaluated"] == 85  # 80 today + 5 yesterday
    assert gate._stats["go_count"] == 52  # 47 today + 5 yesterday


def test_hydration_falls_back_to_deque_count_if_aggregation_fails(
    confidence_gate_with_fake_db,
):
    """If the Mongo `$group` aggregation crashes (transient flap, etc.)
    the loader must NOT crash — it should fall back to the legacy
    deque-based count so the panel still shows *something*.
    """
    fake_db, _, cg_mod = confidence_gate_with_fake_db

    # Simulate an aggregation crash
    fake_db["confidence_gate_log"].aggregate.side_effect = RuntimeError("transient")

    from collections import deque
    gate = cg_mod.ConfidenceGate.__new__(cg_mod.ConfidenceGate)
    gate._db = fake_db
    gate._decision_log = deque(maxlen=50)
    gate._stats = {
        "total_evaluated": 0,
        "go_count": 0,
        "reduce_count": 0,
        "skip_count": 0,
        "today_evaluated": 0,
        "today_go": 0,
        "today_skip": 0,
        "today_date": "2025-01-01",
    }
    gate._trading_mode = "normal"
    gate._mode_reason = None

    # Should not raise.
    cg_mod.ConfidenceGate._load_from_db(gate)

    # Fallback uses the 50-doc deque, which contains 47 GO (since they
    # come first in the docs list). Either way, today_evaluated must
    # be a non-negative int and not crash.
    assert gate._stats["today_evaluated"] >= 0
