"""
Tests for the unqualifiable strike-counter pipeline.

Operator scenario 2026-04-29: overnight backfill burned ~9,000 wasted
IB requests on dead symbols (PSTG, HOLX, CHAC, AL, GLDD, DAWN…)
because the historical collector never called the skip-symbol
endpoint, so `mark_unqualifiable` was never invoked. Verified on DGX:
0 unqualifiable / 0 striking despite thousands of Error 200 events.

Two fixes covered:

1. **Strike threshold lowered** from 3 → 1. The "No security
   definition" error is deterministic — no point waiting for 3
   confirmations of a permanent state.
2. **Helper test suite** locks in `mark_unqualifiable` semantics so
   future refactors don't regress the upsert / promotion path.
"""

from datetime import datetime, timezone

import mongomock
import pytest

from services.symbol_universe import (
    UNQUALIFIABLE_FAILURE_THRESHOLD,
    mark_unqualifiable,
)


@pytest.fixture
def db():
    """Fresh in-memory Mongo per test."""
    client = mongomock.MongoClient()
    return client["test_universe"]


def test_threshold_is_now_one():
    """Sanity: threshold should be 1 (was 3 pre-2026-04-29 fix).

    If anyone bumps this back to 3, the operator's overnight pacing
    pain returns. The CHANGELOG entry explains why.
    """
    assert UNQUALIFIABLE_FAILURE_THRESHOLD == 1


def test_first_strike_promotes_immediately(db):
    """With threshold=1, the first call promotes the symbol to
    `unqualifiable: true` in a single round-trip — no need to repeat."""
    state = mark_unqualifiable(db, "PSTG", reason="No security definition has been found")

    assert state["success"] is True
    assert state["promoted_now"] is True
    assert state["unqualifiable"] is True
    assert state["failure_count"] == 1

    doc = db.symbol_adv_cache.find_one({"symbol": "PSTG"}, {"_id": 0})
    assert doc["unqualifiable"] is True
    assert doc["unqualifiable_failure_count"] == 1
    assert doc["unqualifiable_reason"] == "No security definition has been found"
    assert "unqualifiable_marked_at" in doc


def test_second_strike_is_idempotent(db):
    """Repeated strikes after promotion increment the counter but
    don't re-promote (no double-stamp on `unqualifiable_marked_at`)."""
    first = mark_unqualifiable(db, "HOLX", reason="dead")
    assert first["promoted_now"] is True
    first_marked_at = db.symbol_adv_cache.find_one(
        {"symbol": "HOLX"}, {"_id": 0, "unqualifiable_marked_at": 1}
    )["unqualifiable_marked_at"]

    second = mark_unqualifiable(db, "HOLX", reason="dead again")
    assert second["promoted_now"] is False  # already promoted
    assert second["failure_count"] == 2
    assert second["unqualifiable"] is True
    second_marked_at = db.symbol_adv_cache.find_one(
        {"symbol": "HOLX"}, {"_id": 0, "unqualifiable_marked_at": 1}
    )["unqualifiable_marked_at"]
    assert first_marked_at == second_marked_at  # not re-stamped


def test_upsert_creates_doc_if_missing(db):
    """Symbol not yet in `symbol_adv_cache` (e.g. a delisted name that
    never got an ADV row) should still get tracked via upsert."""
    assert db.symbol_adv_cache.count_documents({"symbol": "GHOST"}) == 0

    state = mark_unqualifiable(db, "GHOST", reason="never existed")

    assert state["promoted_now"] is True
    doc = db.symbol_adv_cache.find_one({"symbol": "GHOST"}, {"_id": 0})
    assert doc is not None
    assert doc["symbol"] == "GHOST"
    assert doc["unqualifiable"] is True
    assert doc["first_seen_at"]  # set on insert


def test_uppercases_symbol(db):
    """Lowercase input should be normalised to uppercase to match the
    canonical symbol_adv_cache convention."""
    state = mark_unqualifiable(db, "ghost", reason="x")
    assert state["promoted_now"] is True

    # Stored under uppercase
    assert db.symbol_adv_cache.find_one({"symbol": "GHOST"}) is not None
    assert db.symbol_adv_cache.find_one({"symbol": "ghost"}) is None


def test_missing_db_returns_safe_error(db):
    """`db=None` returns a clean error response without raising."""
    state = mark_unqualifiable(None, "AAPL", reason="x")
    assert state["success"] is False
    assert "missing db" in state["error"]


def test_missing_symbol_returns_safe_error(db):
    """Empty symbol input returns clean error without writing."""
    state = mark_unqualifiable(db, "", reason="x")
    assert state["success"] is False
    assert db.symbol_adv_cache.count_documents({}) == 0


def test_consecutive_strikes_increment_counter(db):
    """Running 3 strikes in a row results in count=3 and a single
    promotion at strike #1."""
    for i in range(3):
        state = mark_unqualifiable(db, "DAWN", reason=f"strike {i + 1}")
        assert state["failure_count"] == i + 1
        # Promoted on strike #1 only — subsequent calls already-promoted.
        if i == 0:
            assert state["promoted_now"] is True
        else:
            assert state["promoted_now"] is False

    doc = db.symbol_adv_cache.find_one({"symbol": "DAWN"}, {"_id": 0})
    assert doc["unqualifiable_failure_count"] == 3
    assert doc["unqualifiable"] is True


def test_last_seen_at_updates_on_each_call(db):
    """`unqualifiable_last_seen_at` should refresh each strike — operator
    can use it to spot symbols still being requested by the planner
    despite being marked unqualifiable (= bug in selector logic)."""
    mark_unqualifiable(db, "CHAC", reason="x")
    first_seen = db.symbol_adv_cache.find_one(
        {"symbol": "CHAC"}, {"_id": 0, "unqualifiable_last_seen_at": 1}
    )["unqualifiable_last_seen_at"]

    # Sleep a tiny bit and re-strike
    import time as _t
    _t.sleep(0.01)
    mark_unqualifiable(db, "CHAC", reason="y")
    second_seen = db.symbol_adv_cache.find_one(
        {"symbol": "CHAC"}, {"_id": 0, "unqualifiable_last_seen_at": 1}
    )["unqualifiable_last_seen_at"]

    assert second_seen > first_seen
