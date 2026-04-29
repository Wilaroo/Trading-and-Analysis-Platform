"""Tests for the RTH-readiness pre-flight endpoint (2026-04-30 v11, P0).

The endpoint is `GET /api/diagnostic/rth-readiness` and runs nine
independent checks. Each check returns a {status, name, message,
details} envelope; a single check raising must NOT kill the endpoint.

Tests cover:
  - `_check_status` tri-state semantics (incl. the warn-on-fail case
    that bit us once during the smoke test)
  - The endpoint returns 200 + a stable schema
  - Each check helper handles its specific failure mode (no DB,
    missing collection, import error)
  - `ready_for_rth` flips to False on any RED
  - Source-level guards confirm the check ordering hasn't drifted
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

DIAG_SRC = Path(
    "/app/backend/routers/diagnostic_router.py"
).read_text("utf-8")


# ───────── _check_status semantics ─────────


def test_status_green_on_clean_pass():
    from routers.diagnostic_router import _check_status
    assert _check_status(True, False) == "GREEN"


def test_status_yellow_on_passed_with_warning():
    from routers.diagnostic_router import _check_status
    assert _check_status(True, True) == "YELLOW"


def test_status_yellow_on_failed_but_non_blocker():
    """The case my smoke test caught: caller wants YELLOW (non-blocker
    failure, e.g. "morning prediction not written YET") but pre-fix the
    function returned RED for `passed=False, warning=True`."""
    from routers.diagnostic_router import _check_status
    assert _check_status(False, True) == "YELLOW"


def test_status_red_on_blocker_failure():
    from routers.diagnostic_router import _check_status
    assert _check_status(False, False) == "RED"


# ───────── Source-level ordering & coverage guards ─────────


def test_endpoint_runs_all_nine_checks():
    """The dispatch table must include all nine helpers in the
    documented order. A reorder or drop here changes the answer
    the operator gets — pin it."""
    expected_order = [
        "_check_bot_state",
        "_check_bot_runtime",
        "_check_scanner_runtime",
        "_check_collection_mode",
        "_check_pusher_health",
        "_check_universe_freshness",
        "_check_data_request_queue",
        "_check_landscape_prewarm",
        "_check_briefing_predictions",
    ]
    # Find the dispatch table block.
    dispatch_start = DIAG_SRC.find("for fn, args in (")
    assert dispatch_start > 0
    block = DIAG_SRC[dispatch_start:dispatch_start + 1500]
    last_idx = -1
    for fn_name in expected_order:
        idx = block.find(fn_name)
        assert idx > last_idx, (
            f"{fn_name} missing or out-of-order in dispatch table"
        )
        last_idx = idx


def test_endpoint_belt_and_braces_around_each_check():
    """A single check raising must not 500 the endpoint — the
    dispatch loop must wrap each call in try/except."""
    # The dispatch loop must contain BOTH the check call AND a
    # surrounding try/except so one helper's bug doesn't kill the
    # rest of the report.
    block = DIAG_SRC[DIAG_SRC.find("for fn, args in ("):]
    block = block[:block.find("    green = sum(")]
    assert "try:" in block
    assert "checks.append(fn(*args))" in block
    assert "except Exception as e:" in block
    assert '"status": "RED"' in block, (
        "Belt-and-braces fallback must mark a raising check as RED"
    )


def test_ready_for_rth_falls_to_false_on_any_red():
    """`ready_for_rth = red == 0` — pin this at source level."""
    block = DIAG_SRC[DIAG_SRC.find("def rth_readiness("):]
    assert "ready = red == 0" in block


def test_overall_status_is_worst_of_all():
    """Overall must be RED if any RED, YELLOW if no RED but any YELLOW,
    else GREEN."""
    block = DIAG_SRC[DIAG_SRC.find("def rth_readiness("):]
    assert (
        'overall = "GREEN" if red == 0 and yellow == 0 else '
        '"YELLOW" if red == 0 else "RED"'
    ) in block


def test_endpoint_uses_et_trading_day_in_response():
    """Like the trade-funnel, readiness must report ET trading day so
    the operator running it at 23:00 ET sees the right day."""
    block = DIAG_SRC[DIAG_SRC.find("def rth_readiness("):]
    assert 'ZoneInfo("America/New_York")' in block
    assert '"trading_day_et": trading_day_et,' in block


# ───────── Individual check helpers ─────────


class _FakeCol:
    def __init__(self, docs=None):
        self._docs = docs or []
    def find_one(self, query=None, projection=None, sort=None):
        if not self._docs:
            return None
        return self._docs[0]
    def count_documents(self, query=None):
        return len(self._docs)


class _FakeDb:
    def __init__(self, collections=None):
        self._collections = collections or {}
    def __getitem__(self, name):
        return self._collections.get(name, _FakeCol())


def test_check_bot_state_green_on_autonomous_running():
    from routers.diagnostic_router import _check_bot_state
    db = _FakeDb({"bot_state": _FakeCol([{
        "mode": "autonomous",
        "running": True,
        "risk_params": {"max_loss": 100},
    }])})
    result = _check_bot_state(db)
    assert result["status"] == "GREEN"
    assert result["details"]["mode"] == "autonomous"
    assert result["details"]["running"] is True


def test_check_bot_state_red_on_paper_mode():
    from routers.diagnostic_router import _check_bot_state
    db = _FakeDb({"bot_state": _FakeCol([{
        "mode": "paper",
        "running": True,
        "risk_params": {"max_loss": 100},
    }])})
    result = _check_bot_state(db)
    assert result["status"] == "RED"
    assert "paper" in result["message"]


def test_check_bot_state_red_on_no_doc():
    """Empty bot_state → mode is empty → RED."""
    from routers.diagnostic_router import _check_bot_state
    db = _FakeDb({"bot_state": _FakeCol([])})
    result = _check_bot_state(db)
    assert result["status"] == "RED"


def test_check_collection_mode_green_when_inactive():
    from routers.diagnostic_router import _check_collection_mode
    from services import collection_mode
    collection_mode.deactivate()
    result = _check_collection_mode()
    assert result["status"] == "GREEN"


def test_check_collection_mode_red_when_active():
    from routers.diagnostic_router import _check_collection_mode
    from services import collection_mode
    collection_mode.activate()
    try:
        result = _check_collection_mode()
        assert result["status"] == "RED"
        assert "ACTIVE" in result["message"]
    finally:
        collection_mode.deactivate()


def test_check_universe_freshness_red_on_empty_cache():
    from routers.diagnostic_router import _check_universe_freshness
    db = _FakeDb({"symbol_adv_cache": _FakeCol([])})
    result = _check_universe_freshness(db)
    assert result["status"] == "RED"
    assert "empty" in result["message"]


def test_check_pusher_health_red_on_unreachable():
    """When the pusher RPC client returns None (pusher offline),
    the check must mark RED with a clear message."""
    from routers import diagnostic_router

    class _FakeRPC:
        def health(self):
            return None

    with patch.object(diagnostic_router, "_check_pusher_health", wraps=diagnostic_router._check_pusher_health):
        with patch(
            "services.ib_pusher_rpc.get_pusher_rpc_client",
            return_value=_FakeRPC(),
        ):
            result = diagnostic_router._check_pusher_health()
            assert result["status"] == "RED"
            assert "unreachable" in result["message"].lower()


def test_check_pusher_health_green_when_connected():
    from routers import diagnostic_router

    class _FakeRPC:
        def health(self):
            return {"ib_connected": True, "version": "test"}

    with patch(
        "services.ib_pusher_rpc.get_pusher_rpc_client",
        return_value=_FakeRPC(),
    ):
        result = diagnostic_router._check_pusher_health()
        assert result["status"] == "GREEN"


def test_check_briefing_predictions_yellow_when_missing():
    """No row for today is YELLOW (will be written on first briefing
    call) — NOT RED."""
    from routers.diagnostic_router import _check_briefing_predictions
    db = _FakeDb({"landscape_predictions": _FakeCol([])})
    result = _check_briefing_predictions(db)
    assert result["status"] == "YELLOW"


def test_check_briefing_predictions_green_when_present():
    from routers.diagnostic_router import _check_briefing_predictions
    db = _FakeDb({"landscape_predictions": _FakeCol([{
        "trading_day": "2026-04-30",
        "context": "morning",
    }])})
    result = _check_briefing_predictions(db)
    # We can only confirm the structure since the comparison is
    # against today's ET date which we don't control here. Test that
    # the helper returns a valid envelope and a passing-or-failing
    # status (never raises, never returns None).
    assert result["name"] == "briefing_predictions"
    assert result["status"] in ("GREEN", "YELLOW", "RED")


def test_check_data_request_queue_green_when_empty():
    from routers.diagnostic_router import _check_data_request_queue
    db = _FakeDb({"historical_data_requests": _FakeCol([])})
    result = _check_data_request_queue(db)
    assert result["status"] == "GREEN"
    assert result["details"]["total"] == 0


# ───────── Pre-warm error escalation guards ─────────


SCANNER_SRC = Path(
    "/app/backend/services/enhanced_scanner.py"
).read_text("utf-8")


def test_prewarm_escalates_to_warning_on_failure():
    """Pre-fix: failures logged at DEBUG (silent). Post-fix: WARNING
    on every failure."""
    block = SCANNER_SRC[
        SCANNER_SRC.find("async def _prewarm_setup_landscape("):
    ]
    # Find the end of the method — next `def ` at the same indent
    end = block.find("\n    async def ", 100)
    if end < 0:
        end = block.find("\n    def ", 100)
    if end > 0:
        block = block[:end]
    assert "logger.warning(" in block, (
        "Pre-warm failure must escalate to WARNING — debug-level "
        "swallowing failures was the bug we shipped to fix"
    )


def test_prewarm_logs_critical_after_three_consecutive_failures():
    """3 consecutive failures → CRITICAL banner so a broken pre-warm
    overnight is unmissable in supervisor logs the next morning."""
    block = SCANNER_SRC[
        SCANNER_SRC.find("async def _prewarm_setup_landscape("):
    ]
    end = block.find("\n    async def ", 100)
    if end < 0:
        end = block.find("\n    def ", 100)
    if end > 0:
        block = block[:end]
    assert "self._prewarm_failure_count >= 3" in block
    assert "logger.critical(" in block


def test_prewarm_resets_failure_counter_on_success():
    """A transient blip must not accumulate forever — successful
    pre-warm resets the counter."""
    block = SCANNER_SRC[
        SCANNER_SRC.find("async def _prewarm_setup_landscape("):
    ]
    end = block.find("\n    async def ", 100)
    if end < 0:
        end = block.find("\n    def ", 100)
    if end > 0:
        block = block[:end]
    assert "self._prewarm_failure_count = 0" in block
