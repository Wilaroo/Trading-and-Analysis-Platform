"""
test_kill_switch_persistence_v19_34_25.py — pins the kill-switch
persistence behavior shipped in v19.34.25.

Bug class: pre-fix the `SafetyGuardrails.state.kill_switch_active` latch
was in-memory only. The module docstring even acknowledged this:
    "State is in-memory; after a backend restart the kill-switch must
     be re-tripped organically..."
That assumption was wrong. Operator-discovered 2026-02-XX:
    12:28 PM  — operator clicks Flatten All; kill-switch trips
    ~1:20 PM  — backend restarted to deploy v19.34.24b
    ~1:20 PM  — kill-switch silently disarmed (in-memory state gone)
    1:25 PM   — bot opens 6 phantom trades from scanner setups before
                operator notices and re-trips manually. Saved only by
                IB Gateway being offline at the time, which prevented
                actual fills.

v19.34.25 fix: write the latch to Mongo `safety_state` collection on
every trip/reset, restore on boot. With this in place the same restart
sequence preserves the latch.

Tests below cover:
  - trip_kill_switch persists active=True to Mongo.
  - reset_kill_switch persists active=False (so a stale Mongo record
    can't re-trip the bot on next boot).
  - restore_kill_switch_from_db restores active=True + reason +
    tripped_at on boot.
  - restore returns False when no doc exists (fresh DB).
  - restore returns False when active=False in DB (operator already
    reset).
  - DB unavailable does NOT crash trip/reset (in-memory remains
    authoritative — defense in depth).
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.safety_guardrails import (  # noqa: E402
    SafetyGuardrails,
    SafetyConfig,
)


def _make_guard_with_mock_db(stored_doc=None):
    """Build a fresh guard whose persistence backend is a MagicMock so
    we can inspect calls without spinning a real Mongo."""
    g = SafetyGuardrails(SafetyConfig(enabled=True))
    fake_db = MagicMock()
    fake_db.safety_state.find_one.return_value = stored_doc
    return g, fake_db


# ─────────────────────────────────────────────────────────────────────
# 1. trip_kill_switch persists `active=True` to safety_state.
# ─────────────────────────────────────────────────────────────────────
def test_trip_kill_switch_persists_to_mongo():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.trip_kill_switch(reason="test_trip_v19_34_25")

    fake_db.safety_state.update_one.assert_called_once()
    args, kwargs = fake_db.safety_state.update_one.call_args
    filter_, update = args
    assert filter_ == {"_id": "kill_switch"}
    assert update["$set"]["active"] is True
    assert update["$set"]["reason"] == "test_trip_v19_34_25"
    assert update["$set"]["tripped_at"] is not None
    assert kwargs.get("upsert") is True

    # In-memory state mirrors persisted state.
    assert g.state.kill_switch_active is True
    assert g.state.kill_switch_reason == "test_trip_v19_34_25"


# ─────────────────────────────────────────────────────────────────────
# 2. reset_kill_switch persists `active=False` (so a stale Mongo record
#    can't re-trip the bot on next boot).
# ─────────────────────────────────────────────────────────────────────
def test_reset_kill_switch_persists_inactive_to_mongo():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.trip_kill_switch(reason="trip_first")
        fake_db.safety_state.update_one.reset_mock()
        g.reset_kill_switch()

    fake_db.safety_state.update_one.assert_called_once()
    _, args, _ = fake_db.safety_state.update_one.mock_calls[0]
    update = args[1]
    assert update["$set"]["active"] is False
    assert update["$set"]["reason"] is None
    assert update["$set"]["tripped_at"] is None

    assert g.state.kill_switch_active is False


# ─────────────────────────────────────────────────────────────────────
# 3. restore_kill_switch_from_db restores tripped state on boot — the
#    actual operator-discovered scenario this whole feature exists for.
# ─────────────────────────────────────────────────────────────────────
def test_restore_kill_switch_from_db_restores_tripped_state():
    stored = {
        "_id": "kill_switch",
        "active": True,
        "tripped_at": 1778088796.4860055,
        "reason": "overnight_safety_v19_34_24b",
        "updated_at": 1778088796.5,
    }
    g, fake_db = _make_guard_with_mock_db(stored_doc=stored)

    # Pre-boot: in-memory state defaults to clean (just-instantiated).
    assert g.state.kill_switch_active is False

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        restored = g.restore_kill_switch_from_db()

    assert restored is True
    assert g.state.kill_switch_active is True
    assert g.state.kill_switch_reason == "overnight_safety_v19_34_24b"
    assert g.state.kill_switch_tripped_at == 1778088796.4860055


# ─────────────────────────────────────────────────────────────────────
# 4. Fresh DB (no doc) → restore returns False, latch stays clean.
# ─────────────────────────────────────────────────────────────────────
def test_restore_returns_false_when_no_doc_exists():
    g, fake_db = _make_guard_with_mock_db(stored_doc=None)

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        restored = g.restore_kill_switch_from_db()

    assert restored is False
    assert g.state.kill_switch_active is False


# ─────────────────────────────────────────────────────────────────────
# 5. DB has the doc but `active=False` (operator reset before this
#    boot) → restore returns False, latch stays clean.
# ─────────────────────────────────────────────────────────────────────
def test_restore_returns_false_when_doc_says_inactive():
    g, fake_db = _make_guard_with_mock_db(
        stored_doc={"_id": "kill_switch", "active": False, "reason": None}
    )

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        restored = g.restore_kill_switch_from_db()

    assert restored is False
    assert g.state.kill_switch_active is False


# ─────────────────────────────────────────────────────────────────────
# 6. DB unavailable does NOT crash trip/reset — in-memory state
#    remains authoritative. Persistence is defense in depth, not a
#    hard dependency on the trade-eval critical path.
# ─────────────────────────────────────────────────────────────────────
def test_trip_does_not_crash_when_db_unavailable():
    g = SafetyGuardrails(SafetyConfig(enabled=True))

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=None):
        # Should NOT raise.
        g.trip_kill_switch(reason="db_offline_test")

    # In-memory state still flips even if persistence failed.
    assert g.state.kill_switch_active is True
    assert g.state.kill_switch_reason == "db_offline_test"


def test_restore_does_not_crash_when_db_unavailable():
    g = SafetyGuardrails(SafetyConfig(enabled=True))

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=None):
        restored = g.restore_kill_switch_from_db()

    assert restored is False
    assert g.state.kill_switch_active is False


# ─────────────────────────────────────────────────────────────────────
# 7. Idempotent trip: second trip does NOT write a second time
#    (matches in-memory idempotency contract).
# ─────────────────────────────────────────────────────────────────────
def test_trip_is_idempotent_in_persistence_too():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.trip_kill_switch(reason="first")
        g.trip_kill_switch(reason="second_should_be_ignored")

    # Only ONE write — the second trip should bail at the
    # `if self.state.kill_switch_active: return` guard.
    assert fake_db.safety_state.update_one.call_count == 1
    assert g.state.kill_switch_reason == "first"
