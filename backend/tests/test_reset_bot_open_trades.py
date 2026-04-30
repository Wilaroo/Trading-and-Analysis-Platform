"""
test_reset_bot_open_trades.py — unit tests for the morning-of bot reset
script (`backend/scripts/reset_bot_open_trades.py`).

Operator runs the script after flattening positions in TWS to wipe the
in-Mongo `bot_trades` open rows so the bot starts the day clean. These
tests prove the dry-run is observation-only, the commit path correctly
flips status, the symbol filter works, the audit log is written, and
the safety guard (--confirm RESET) blocks accidental commits.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "backend" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import reset_bot_open_trades as r  # noqa: E402


# ── tiny fake-mongo collection (covers the methods the script uses) ────
class _FakeColl:
    def __init__(self, name: str, docs: List[Dict[str, Any]] | None = None):
        self.name = name
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.indexes: List[tuple] = []
        self.last_inserted: List[Dict[str, Any]] = []

    def find(self, query: Dict[str, Any], projection: Dict[str, Any] | None = None):
        # ignore projection; just match query and return all keys
        return [d.copy() for d in self.docs if self._match(d, query)]

    def update_many(self, query: Dict[str, Any], update: Dict[str, Any]):
        modified = 0
        set_ops = update.get("$set") or {}
        for d in self.docs:
            if self._match(d, query):
                for k, v in set_ops.items():
                    d[k] = v
                modified += 1

        class _Result:
            pass
        res = _Result()
        res.modified_count = modified
        return res

    def insert_one(self, doc: Dict[str, Any]):
        self.last_inserted.append(doc)
        return None

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    @staticmethod
    def _match(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
        for k, v in q.items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _FakeDB:
    def __init__(self):
        self._colls: Dict[str, _FakeColl] = {}

    def __getitem__(self, name: str) -> _FakeColl:
        if name not in self._colls:
            self._colls[name] = _FakeColl(name)
        return self._colls[name]


@pytest.fixture
def db_with_phantoms():
    """Realistic Spark-side state from 2026-05-01 EOD."""
    db = _FakeDB()
    db["bot_trades"].docs = [
        {"trade_id": "62a8bf52", "symbol": "BP",   "direction": "long",  "shares": 315,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "93884f54", "symbol": "BP",   "direction": "long",  "shares": 450,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "bbbda607", "symbol": "BP",   "direction": "long",  "shares": 672,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "ef3d3533", "symbol": "SOFI", "direction": "short", "shares": 301,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "e6fc8d36", "symbol": "SOFI", "direction": "long",  "shares": 1636, "remaining_shares": 0, "status": "open"},
        {"trade_id": "e1d8d473", "symbol": "TMUS", "direction": "long",  "shares": 255,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "7434d56a", "symbol": "LITE", "direction": "long",  "shares": 12,   "remaining_shares": 0, "status": "open"},
        {"trade_id": "2e5ac321", "symbol": "CB",   "direction": "long",  "shares": 152,  "remaining_shares": 0, "status": "open"},
        {"trade_id": "a1743594", "symbol": "HOOD", "direction": "long",  "shares": 177,  "remaining_shares": 0, "status": "open"},
        # Already-closed rows must be left alone.
        {"trade_id": "old_001",  "symbol": "AAPL", "direction": "long",  "shares": 50,   "remaining_shares": 0, "status": "closed", "close_reason": "stop_hit"},
    ]
    return db


# ── dry-run: read-only ─────────────────────────────────────────────────
def test_dry_run_makes_no_modifications(db_with_phantoms):
    before = [d.copy() for d in db_with_phantoms["bot_trades"].docs]
    res = r.reset_open_trades(db=db_with_phantoms, dry_run=True)
    after = db_with_phantoms["bot_trades"].docs
    assert res["dry_run"] is True
    assert res["matched_count"] == 9
    assert res["modified_count"] == 0
    assert res["log_written"] is False
    assert before == after  # identical docs


def test_dry_run_lists_only_open_trades(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, dry_run=True)
    statuses = {(t.get("trade_id"), t.get("status")) for t in res["affected"]}
    # Closed AAPL must NOT be in the listing
    assert ("old_001", "closed") not in statuses
    assert len(res["affected"]) == 9


# ── commit path ────────────────────────────────────────────────────────
def test_commit_flips_status_and_stamps_close_reason(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, dry_run=False)
    assert res["matched_count"] == 9
    assert res["modified_count"] == 9
    assert res["log_written"] is True

    docs = db_with_phantoms["bot_trades"].docs
    open_after = [d for d in docs if d.get("status") == "open"]
    assert open_after == [], "no open rows should remain after commit"

    closed_by_us = [d for d in docs if d.get("close_reason") == r.CLOSE_REASON]
    assert len(closed_by_us) == 9
    for d in closed_by_us:
        assert d["status"] == "closed"
        assert d["closed_at"]  # ISO string set
        assert d["remaining_shares"] == 0


def test_commit_leaves_already_closed_rows_alone(db_with_phantoms):
    r.reset_open_trades(db=db_with_phantoms, dry_run=False)
    aapl = next(d for d in db_with_phantoms["bot_trades"].docs if d["trade_id"] == "old_001")
    assert aapl["close_reason"] == "stop_hit"  # unchanged
    assert aapl["status"] == "closed"


def test_commit_writes_audit_log(db_with_phantoms):
    r.reset_open_trades(db=db_with_phantoms, dry_run=False)
    log = db_with_phantoms[r.RESET_LOG_COLLECTION].last_inserted
    assert len(log) == 1
    entry = log[0]
    assert entry["count"] == 9
    assert entry["reason"] == r.CLOSE_REASON
    assert "old_001" not in entry["trade_ids"]  # only the 9 open ones logged
    assert len(entry["trade_ids"]) == 9


# ── symbol filter ──────────────────────────────────────────────────────
def test_symbol_filter_dry_run(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, symbols=["SOFI"], dry_run=True)
    assert res["matched_count"] == 2
    assert {t["trade_id"] for t in res["affected"]} == {"ef3d3533", "e6fc8d36"}


def test_symbol_filter_commit_only_touches_subset(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, symbols=["sofi", "lite"], dry_run=False)
    assert res["matched_count"] == 3  # 2 SOFI + 1 LITE
    assert res["modified_count"] == 3
    docs = db_with_phantoms["bot_trades"].docs
    bp_open = [d for d in docs if d["symbol"] == "BP" and d["status"] == "open"]
    assert len(bp_open) == 3, "BP rows must remain open when filter excludes them"


def test_symbol_filter_uppercases_input(db_with_phantoms):
    """Operator may pass lowercase symbols; query must still hit."""
    res = r.reset_open_trades(db=db_with_phantoms, symbols=["sofi"], dry_run=True)
    assert res["matched_count"] == 2


# ── empty / no-op cases ────────────────────────────────────────────────
def test_no_open_trades_returns_zero():
    db = _FakeDB()
    db["bot_trades"].docs = [
        {"trade_id": "x", "symbol": "AAPL", "status": "closed"}
    ]
    res = r.reset_open_trades(db=db, dry_run=False)
    assert res["matched_count"] == 0
    assert res["modified_count"] == 0
    assert res["log_written"] is False  # no log when nothing changes


def test_symbol_filter_with_no_matches_is_safe(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, symbols=["NOTREAL"], dry_run=False)
    assert res["matched_count"] == 0
    assert res["modified_count"] == 0
    open_count = sum(1 for d in db_with_phantoms["bot_trades"].docs if d["status"] == "open")
    assert open_count == 9, "real open trades untouched"


# ── CLI safety guard ───────────────────────────────────────────────────
def test_cli_aborts_without_confirm(capsys):
    """Without --dry-run AND without --confirm RESET, the CLI must abort."""
    rc = r.main(["--db", "tradecommand"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "ABORT" in captured.out


def test_cli_aborts_when_confirm_token_wrong(capsys):
    rc = r.main(["--confirm", "yes"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "ABORT" in captured.out


# ── render summary smoke ───────────────────────────────────────────────
def test_render_summary_dry_run_shows_dry_run_tag(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, dry_run=True)
    text = r.render_summary(res)
    assert "[DRY-RUN]" in text
    assert "matched: 9" in text
    assert "SOFI" in text
    assert "no changes written" in text


def test_render_summary_commit_shows_committed_tag(db_with_phantoms):
    res = r.reset_open_trades(db=db_with_phantoms, dry_run=False)
    text = r.render_summary(res)
    assert "[COMMITTED]" in text
    assert "modified: 9" in text
    assert "audit log written" in text


# ── query construction sanity ──────────────────────────────────────────
def test_build_query_no_symbols():
    assert r._build_query(None) == {"status": "open"}


def test_build_query_with_symbols_uppercases():
    q = r._build_query(["sofi", "BP", "Hood"])
    assert q["status"] == "open"
    assert q["symbol"]["$in"] == ["SOFI", "BP", "HOOD"]
