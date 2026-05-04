"""
v19.31.5 (2026-05-04) — regression pin for the Trail Explorer empty
thoughts bug.

The bugs:
  1. `build_decision_trail` filtered `sentcom_thoughts` by
     `symbol == symbol.upper()` — but `_persist_thought` did NOT
     normalize symbol on write. Lowercase-emitted thoughts (a few
     legacy code paths) never matched.
  2. Empty/None content rows persisted as dedup sentinels rendered
     as blank lines in the Trail Explorer drilldown.
  3. Anchor preferred `created_at` over `executed_at`. For trades
     fired after a multi-second AI consultation, the window centered
     on consultation start, not the actual decision moment.

The fixes:
  - Persist normalizes `symbol.upper()`.
  - Persist skips empty content.
  - Read uses `$in: [upper, lower, original]` for legacy-row
    compatibility AND `$nin: ["", None]` to exclude sentinels.
  - Anchor prefers `executed_at` first.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake Mongo ─────────────────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])
        self.inserted: List[dict] = []

    def _matches(self, doc, query):
        for k, v in query.items():
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$lte" in v and not (actual is not None and actual <= v["$lte"]):
                    return False
                if "$in" in v and actual not in v["$in"]:
                    return False
                if "$nin" in v and actual in v["$nin"]:
                    return False
            else:
                if actual != v:
                    return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if (query is None or self._matches(d, query))]
        if sort:
            for k, direction in reversed(sort):
                rows.sort(key=lambda r: r.get(k, ""), reverse=direction == -1)
        if limit:
            rows = rows[:limit]
        return iter(rows)

    def find_one(self, query, projection=None):
        rows = list(self.find(query, projection))
        return rows[0] if rows else None

    def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.shadow_decisions = _FakeColl()
        self.sentcom_thoughts = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── Trail Explorer read-side: case + content + anchor ──────────────


def _build_trade(trade_id, symbol, executed_at, created_at=None):
    return {
        "id": trade_id,
        "symbol": symbol,
        "executed_at": executed_at,
        "created_at": created_at or executed_at,
        "alert_id": f"alert_{trade_id}",
    }


def test_trail_finds_uppercase_persisted_thoughts():
    from services.decision_trail import build_decision_trail
    db = _FakeDB()
    exec_at = datetime.now(timezone.utc).isoformat()
    db.bot_trades.docs = [_build_trade("t1", "LITE", exec_at)]
    # New thoughts — uppercase as v19.31.5 enforces
    db.sentcom_thoughts.docs = [
        {"symbol": "LITE", "timestamp": exec_at, "content": "Live alert: LITE squeeze", "kind": "info"},
    ]
    res = build_decision_trail(db, "t1")
    assert res is not None
    assert len(res["thoughts"]) == 1
    assert "LITE squeeze" in res["thoughts"][0]["content"]


def test_trail_finds_legacy_lowercase_thoughts():
    """Legacy rows persisted before v19.31.5 may have lowercase symbol.
    Read should still find them."""
    from services.decision_trail import build_decision_trail
    db = _FakeDB()
    exec_at = datetime.now(timezone.utc).isoformat()
    db.bot_trades.docs = [_build_trade("t1", "LITE", exec_at)]
    db.sentcom_thoughts.docs = [
        {"symbol": "lite", "timestamp": exec_at, "content": "legacy lowercase",
         "kind": "info"},
    ]
    res = build_decision_trail(db, "t1")
    assert res is not None
    assert len(res["thoughts"]) == 1
    assert res["thoughts"][0]["content"] == "legacy lowercase"


def test_trail_excludes_empty_content_thoughts():
    from services.decision_trail import build_decision_trail
    db = _FakeDB()
    exec_at = datetime.now(timezone.utc).isoformat()
    db.bot_trades.docs = [_build_trade("t1", "LITE", exec_at)]
    db.sentcom_thoughts.docs = [
        {"symbol": "LITE", "timestamp": exec_at, "content": "real thought", "kind": "info"},
        {"symbol": "LITE", "timestamp": exec_at, "content": "", "kind": "info"},  # blank
        {"symbol": "LITE", "timestamp": exec_at, "content": None, "kind": "info"},  # null
    ]
    res = build_decision_trail(db, "t1")
    assert len(res["thoughts"]) == 1
    assert res["thoughts"][0]["content"] == "real thought"


def test_trail_anchors_on_executed_at_not_created_at():
    """Trade fired at 10:30 (executed_at) but row created at 10:25
    (created_at) during AI consult. Anchor should be 10:30 so we catch
    thoughts up to 12:30 — covers the post-fill manage period."""
    from services.decision_trail import build_decision_trail
    db = _FakeDB()
    created = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    executed = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=55)).isoformat()
    db.bot_trades.docs = [_build_trade("t1", "LITE", executed_at=executed,
                                       created_at=created)]
    # Thought that landed 90 min AFTER executed_at — should be in window
    # (executed_at + 120 min) but NOT in window if anchored at created_at
    # (which would only see +120 min from created = +1h25m from executed,
    # so a 90-min-post-executed thought would land at +95m post-created.
    # Hmm — actually 95m IS within the 120m window even from created_at.
    # Let me restructure: thought landing 119m after executed (so just
    # inside executed-anchored window) is 124m after created (just OUTSIDE
    # created-anchored window).
    far_thought_ts = (datetime.fromisoformat(executed) + timedelta(minutes=119)).isoformat()
    db.sentcom_thoughts.docs = [
        {"symbol": "LITE", "timestamp": far_thought_ts,
         "content": "Late manage thought", "kind": "info"},
    ]
    res = build_decision_trail(db, "t1")
    # With executed_at anchor → in window, found. With created_at anchor → NOT found.
    contents = [t["content"] for t in res["thoughts"]]
    assert "Late manage thought" in contents


# ─── Persist-side: normalize on write ────────────────────────────────


@pytest.mark.asyncio
async def test_persist_thought_normalizes_symbol_to_upper():
    """v19.31.5 — _persist_thought writes symbol.upper() so reads are
    deterministic going forward."""
    import services.sentcom_service as ss
    from services.sentcom_service import _persist_thought, SentComMessage

    fake_db = _FakeDB()
    orig_get_db = ss._get_db
    ss._get_db = lambda: fake_db
    orig_indexes = ss._ensure_thoughts_indexes
    ss._ensure_thoughts_indexes = lambda: None

    try:
        msg = SentComMessage(
            id="msg1",
            type="info",
            content="LITE squeeze long",
            timestamp=datetime.now(timezone.utc).isoformat(),
            confidence=80,
            symbol="lite",  # lowercase on input
            action_type="evaluation",
            metadata={},
        )
        await _persist_thought(msg)
    finally:
        ss._get_db = orig_get_db
        ss._ensure_thoughts_indexes = orig_indexes

    inserted = fake_db.sentcom_thoughts.inserted
    assert len(inserted) == 1
    assert inserted[0]["symbol"] == "LITE"  # upper-cased


@pytest.mark.asyncio
async def test_persist_thought_skips_empty_content():
    """v19.31.5 — empty / whitespace-only content shouldn't even hit
    Mongo."""
    import services.sentcom_service as ss
    from services.sentcom_service import _persist_thought, SentComMessage

    fake_db = _FakeDB()
    orig_get_db = ss._get_db
    ss._get_db = lambda: fake_db

    try:
        for empty in ("", "   ", "\n\t", None):
            msg = SentComMessage(
                id=f"msg_{empty!r}",
                type="info",
                content=empty,
                timestamp=datetime.now(timezone.utc).isoformat(),
                confidence=None,
                symbol="LITE",
                action_type=None,
                metadata={},
            )
            await _persist_thought(msg)
    finally:
        ss._get_db = orig_get_db

    assert fake_db.sentcom_thoughts.inserted == []


@pytest.mark.asyncio
async def test_persist_thought_writes_real_content_normally():
    import services.sentcom_service as ss
    from services.sentcom_service import _persist_thought, SentComMessage

    fake_db = _FakeDB()
    orig_get_db = ss._get_db
    ss._get_db = lambda: fake_db
    orig_indexes = ss._ensure_thoughts_indexes
    ss._ensure_thoughts_indexes = lambda: None

    try:
        msg = SentComMessage(
            id="msg1",
            type="info",
            content="real content here",
            timestamp=datetime.now(timezone.utc).isoformat(),
            confidence=60,
            symbol="STX",
            action_type="evaluation",
            metadata={"k": "v"},
        )
        await _persist_thought(msg)
    finally:
        ss._get_db = orig_get_db
        ss._ensure_thoughts_indexes = orig_indexes

    assert len(fake_db.sentcom_thoughts.inserted) == 1
    inserted = fake_db.sentcom_thoughts.inserted[0]
    assert inserted["content"] == "real content here"
    assert inserted["symbol"] == "STX"


# ─── Source-level pin ────────────────────────────────────────────────


def test_source_pin_trail_uses_in_query_for_symbol():
    """Catch a future regression that drops the case-insensitive lookup."""
    import inspect
    from services.decision_trail import build_decision_trail
    src = inspect.getsource(build_decision_trail)
    assert "$in" in src and "sym_upper" in src and "sym_lower" in src
    # And the empty-content guard
    assert '"$nin"' in src or "$nin" in src
    # Anchor prefers executed_at — pin the specific anchor_iso assignment.
    # Scope to a single block (~200 chars) so we don't false-positive on
    # other executed_at refs elsewhere in the function.
    anchor_idx = src.index("anchor_iso = (")
    anchor_block = src[anchor_idx:anchor_idx + 300]
    assert anchor_block.index("executed_at") < anchor_block.index("created_at"), (
        f"executed_at must come before created_at in the anchor block:\n{anchor_block}"
    )
