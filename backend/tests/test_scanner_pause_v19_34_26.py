"""
test_scanner_pause_v19_34_26.py — pins the scanner power toggle
(operator-requested soft brake) shipped in v19.34.26.

Operator's "water pump off" semantic:
    Pauses NEW alert intake into the eval pipeline. Does NOT disturb
    in-flight evaluations OR open-position management (stop trail-up,
    scale-out, close-on-stop). Lets you stop new ideas from entering
    without slamming the kill-switch and disrupting existing trade
    management. Persists across backend restarts via Mongo (same
    collection as the kill-switch latch, different `_id`).

Tests below cover:
  - pause_scanner / resume_scanner toggle in-memory state cleanly
  - State persists to Mongo on every change
  - restore_scanner_state_from_db restores paused state on boot
  - status() payload exposes scanner_paused fields
  - DB unavailable does NOT crash pause/resume (in-memory authoritative)
  - Idempotent pause (double-pause does not write twice)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.safety_guardrails import (  # noqa: E402
    SafetyGuardrails,
    SafetyConfig,
)


def _make_guard_with_mock_db(stored_doc=None):
    g = SafetyGuardrails(SafetyConfig(enabled=True))
    fake_db = MagicMock()
    fake_db.safety_state.find_one.return_value = stored_doc
    return g, fake_db


# ─────────────────────────────────────────────────────────────────────
# 1. pause_scanner toggles in-memory state + writes to Mongo.
# ─────────────────────────────────────────────────────────────────────
def test_pause_scanner_persists_to_mongo():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.pause_scanner(reason="end_of_day_v19_34_26")

    assert g.is_scanner_paused() is True
    assert g.state.scanner_paused_reason == "end_of_day_v19_34_26"

    fake_db.safety_state.update_one.assert_called_once()
    args, kwargs = fake_db.safety_state.update_one.call_args
    filter_, update = args
    assert filter_ == {"_id": "scanner_toggle"}   # different _id from kill_switch
    assert update["$set"]["paused"] is True
    assert update["$set"]["reason"] == "end_of_day_v19_34_26"
    assert kwargs.get("upsert") is True


# ─────────────────────────────────────────────────────────────────────
# 2. resume_scanner clears state + persists.
# ─────────────────────────────────────────────────────────────────────
def test_resume_scanner_clears_state():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.pause_scanner(reason="test")
        fake_db.safety_state.update_one.reset_mock()
        g.resume_scanner()

    assert g.is_scanner_paused() is False
    assert g.state.scanner_paused_reason is None
    fake_db.safety_state.update_one.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# 3. restore_scanner_state_from_db restores paused state on boot.
# ─────────────────────────────────────────────────────────────────────
def test_restore_paused_state_on_boot():
    stored = {
        "_id": "scanner_toggle",
        "paused": True,
        "paused_at": 1778100000.0,
        "reason": "overnight_v19_34_26",
        "updated_at": 1778100000.5,
    }
    g, fake_db = _make_guard_with_mock_db(stored_doc=stored)

    assert g.is_scanner_paused() is False  # pre-boot clean

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        restored = g.restore_scanner_state_from_db()

    assert restored is True
    assert g.is_scanner_paused() is True
    assert g.state.scanner_paused_reason == "overnight_v19_34_26"


# ─────────────────────────────────────────────────────────────────────
# 4. Fresh DB → restore returns False, in-memory stays clean.
# ─────────────────────────────────────────────────────────────────────
def test_restore_returns_false_when_no_doc():
    g, fake_db = _make_guard_with_mock_db(stored_doc=None)

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        restored = g.restore_scanner_state_from_db()

    assert restored is False
    assert g.is_scanner_paused() is False


# ─────────────────────────────────────────────────────────────────────
# 5. status() payload exposes scanner fields (UI keys off these).
# ─────────────────────────────────────────────────────────────────────
def test_status_payload_includes_scanner_fields():
    g, fake_db = _make_guard_with_mock_db()
    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.pause_scanner(reason="ui_smoke_test")

    s = g.status()["state"]
    assert "scanner_paused" in s
    assert "scanner_paused_at" in s
    assert "scanner_paused_reason" in s
    assert s["scanner_paused"] is True
    assert s["scanner_paused_reason"] == "ui_smoke_test"


# ─────────────────────────────────────────────────────────────────────
# 6. DB unavailable does NOT crash pause/resume (in-memory primary).
# ─────────────────────────────────────────────────────────────────────
def test_pause_does_not_crash_when_db_unavailable():
    g = SafetyGuardrails(SafetyConfig(enabled=True))

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=None):
        g.pause_scanner(reason="db_offline_test")

    assert g.is_scanner_paused() is True


# ─────────────────────────────────────────────────────────────────────
# 7. Idempotent pause — second call does NOT write twice.
# ─────────────────────────────────────────────────────────────────────
def test_pause_is_idempotent():
    g, fake_db = _make_guard_with_mock_db()

    with patch("services.safety_guardrails._get_sync_safety_db",
               return_value=fake_db):
        g.pause_scanner(reason="first")
        g.pause_scanner(reason="second_should_be_ignored")

    assert fake_db.safety_state.update_one.call_count == 1
    assert g.state.scanner_paused_reason == "first"
