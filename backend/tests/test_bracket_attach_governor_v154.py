"""Offline unit tests for v19.34.154 BracketAttachGovernor.

Verifies the three guard rails:
  1. Hard 3:45 ET cutoff (post-cutoff → block, pre-cutoff → allow).
  2. Permanent block on Error 201 (and 203, 110, etc.).
  3. Generic attempt cap (5 in 300s → block).

Plus operator override (`unblock`) and once-per-day log dedup
(`mark_logged`).

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_bracket_attach_governor_v154.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


@pytest.fixture(autouse=True)
def _fresh_governor():
    from services.bracket_attach_governor import reset_governor_for_tests
    reset_governor_for_tests()
    yield
    reset_governor_for_tests()


# ── 1. Hard 3:45 ET cutoff ───────────────────────────────────────────

def test_cutoff_blocks_after_345_et():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    after_cutoff = datetime(2026, 2, 10, 15, 50, 0, tzinfo=ZoneInfo("America/New_York"))
    ok, reason = gov.should_attempt_attach("AAPL", now_et=after_cutoff)
    assert ok is False
    assert reason == "past_regt_soft_edge_cutoff"


def test_cutoff_allows_before_345_et():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    before_cutoff = datetime(2026, 2, 10, 15, 44, 30, tzinfo=ZoneInfo("America/New_York"))
    ok, reason = gov.should_attempt_attach("AAPL", now_et=before_cutoff)
    assert ok is True
    assert reason == "ok"


def test_cutoff_at_exact_345_blocks():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    at_cutoff = datetime(2026, 2, 10, 15, 45, 0, tzinfo=ZoneInfo("America/New_York"))
    ok, reason = gov.should_attempt_attach("AAPL", now_et=at_cutoff)
    assert ok is False, "exactly 15:45 should already block (>=)"


def test_cutoff_does_not_apply_on_weekends():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    saturday_after_cutoff = datetime(2026, 2, 14, 15, 50, 0, tzinfo=ZoneInfo("America/New_York"))
    ok, reason = gov.should_attempt_attach("AAPL", now_et=saturday_after_cutoff)
    # Weekend → no Reg-T concern; we still expect "ok" (the bot likely
    # isn't trading but the governor shouldn't be the reason it can't).
    assert ok is True


# ── 2. Permanent block on Error 201 (and 203, 110) ──────────────────

def test_error_201_blocks_symbol_permanently_for_day():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    # Pre-failure: allowed
    ok, _ = gov.should_attempt_attach("BMNR", now_et=morning)
    assert ok is True
    # Failure with Error 201
    summary = gov.record_outcome(
        "BMNR",
        {"success": False, "permanent_failure": True,
         "stop_terminal_reject": False,
         "stop_error_code": None, "target_error_code": 201},
        now_et=morning,
    )
    assert summary["now_blocked"] is True
    assert "201" in summary["block_reason"]
    # Now blocked
    ok2, reason2 = gov.should_attempt_attach("BMNR", now_et=morning)
    assert ok2 is False
    assert "ib_error_201" in reason2
    # Other symbols still fine
    ok3, _ = gov.should_attempt_attach("AAPL", now_et=morning)
    assert ok3 is True


def test_error_203_blocks_symbol_for_htb_restriction():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    summary = gov.record_outcome(
        "HTB", {"success": False, "stop_error_code": 203},
        now_et=morning,
    )
    assert summary["now_blocked"] is True
    assert "ib_error_203" in summary["block_reason"]


def test_non_permanent_error_does_not_permablock_first_attempt():
    """IB Error 200 (no security definition) is transient — first
    attempt should NOT permanent-block."""
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    summary = gov.record_outcome(
        "TRAN", {"success": False, "stop_error_code": 200},
        now_et=morning,
    )
    assert summary["now_blocked"] is False
    ok, _ = gov.should_attempt_attach("TRAN", now_et=morning)
    assert ok is True


# ── 3. Generic attempt cap (5 in 300s) ──────────────────────────────

def test_attempt_cap_blocks_after_max_failures():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    # 4 failures — still allowed
    for _ in range(4):
        s = gov.record_outcome("RETRY", {"success": False}, now_et=morning)
        assert s["now_blocked"] is False
    # 5th failure → block
    s = gov.record_outcome("RETRY", {"success": False}, now_et=morning)
    assert s["now_blocked"] is True
    assert "max_attempts_exceeded" in s["block_reason"]
    ok, reason = gov.should_attempt_attach("RETRY", now_et=morning)
    assert ok is False


def test_successful_attempts_do_not_increment_block_threshold():
    """A successful attach should NOT contribute to the 'too many
    failures' block."""
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    # 5 successes in a row — should NOT block.
    for _ in range(5):
        s = gov.record_outcome("HEALTHY", {"success": True}, now_et=morning)
        assert s["now_blocked"] is False
    ok, _ = gov.should_attempt_attach("HEALTHY", now_et=morning)
    assert ok is True


# ── 4. Operator override (`unblock`) ────────────────────────────────

def test_unblock_lifts_permanent_block():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    gov.record_outcome("BMNR", {"stop_error_code": 201}, now_et=morning)
    assert gov.should_attempt_attach("BMNR", now_et=morning)[0] is False
    res = gov.unblock("BMNR", now_et=morning)
    assert res["unblocked"] is True
    assert gov.should_attempt_attach("BMNR", now_et=morning)[0] is True


def test_unblock_on_unblocked_symbol_is_noop():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    res = gov.unblock("AAPL")
    assert res["unblocked"] is False


# ── 5. `mark_logged` once-per-day dedup ─────────────────────────────

def test_mark_logged_is_idempotent_per_day():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    assert gov.mark_logged("AAPL") is True   # first call → True
    assert gov.mark_logged("AAPL") is False  # second call → False
    assert gov.mark_logged("MSFT") is True   # different symbol → True


# ── 6. get_state structure ──────────────────────────────────────────

def test_get_state_includes_blocks_and_attempts():
    from services.bracket_attach_governor import get_governor
    gov = get_governor()
    morning = datetime(2026, 2, 10, 10, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    gov.record_outcome("ATTEMPT_ONLY", {"success": False}, now_et=morning)
    gov.record_outcome("BMNR", {"stop_error_code": 201}, now_et=morning)
    state = gov.get_state(now_et=morning)
    assert "config" in state
    assert "blocks" in state
    assert "attempts" in state
    assert "BMNR" in state["blocks"]
    assert "ATTEMPT_ONLY" in state["attempts"]
    assert state["attempts"]["ATTEMPT_ONLY"]["total_today"] >= 1
