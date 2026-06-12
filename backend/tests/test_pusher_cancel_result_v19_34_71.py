"""v19.34.71 — Pusher reports 10147 / fatal IB errors as `failed`,
never as `pending`.

Bug fixed (2026-05-21 incident root cause): the pusher's
`_execute_queued_cancellation` wait loop only inspected
`target_trade.orderStatus.status`. When IB rejected a cancel with
error 10147 ("OrderId not found"), the rejection arrived via the
async errorEvent callback and was routed by ib_insync into
`Trade.log[-1].errorCode` — but the orderStatus itself never
transitioned to a terminal state (IB rejected the cancel without
changing the order). After 5 seconds of no status change the pusher
reported `pending`, which the backend treated as "still trying" and
re-served on the next /cancellations/pending poll. After 3 polls the
v19.34.65b stale-drop poll-count guard silently dropped the entry,
leaving the bot with a tracked stop_order_id pointing at an order IB
had already cleaned up. Compounded across 21 positions on 2026-05-21
this resulted in every position being UNPROTECTED at IB while the bot
believed brackets were attached.

The fix scans `Trade.log` for new entries with non-zero `errorCode`
that arrive AFTER the cancel was sent. Any such entry is reported as
`failed` with `IB error {code}: {msg}` so the backend's
`_is_fatal_cancel_error()` immediately stale-drops the entry. The
wait window also bumped from 5s → 10s to reduce false-positive
"pending" reports on slow IB acks.

These tests use a minimal fake ib_insync Trade to drive each path.
They live OUTSIDE the backend/tests directory because they exercise
pusher code (documents/scripts/), but they're written in the same
pytest style and pinned alongside the rest of the v19.34.x suite for
easy CI inclusion.

Run from /app:
  python -m pytest backend/tests/test_pusher_cancel_result_v19_34_71.py -v
"""

# v322w — portable test paths: this file previously hardcoded "/app/..."
# (dev-container path) which crashes on the DGX. Auto-fixed by
# scripts/fix_test_paths_portable.py.
import pathlib as _pl
_REPO_ROOT = str(_pl.Path(__file__).resolve().parents[2])
import os
import sys
import time
import types
import importlib.util

import pytest


def _locate_pusher():
    """v19.34.71 — auto-locate ib_data_pusher.py regardless of which repo
    root the tests run from. Tries (in order):
      1. /app/documents/scripts/...  (Emergent workspace)
      2. <repo-root>/documents/scripts/...  (DGX/Windows checkouts)
      3. PUSHER_SCRIPT env override (for unusual layouts)
    Returns the first path that exists, else raises clearly."""
    candidates = []
    env_override = os.environ.get("PUSHER_SCRIPT")
    if env_override:
        candidates.append(env_override)
    # 1. Emergent workspace
    candidates.append((_REPO_ROOT + "/documents/scripts/ib_data_pusher.py"))
    # 2. Relative to this test file (backend/tests/ → ../../documents/scripts/)
    here = os.path.dirname(os.path.abspath(__file__))
    rel = os.path.normpath(os.path.join(
        here, "..", "..", "documents", "scripts", "ib_data_pusher.py"
    ))
    candidates.append(rel)
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        f"Could not locate ib_data_pusher.py. Tried: {candidates}. "
        f"Set PUSHER_SCRIPT env var to override."
    )


PUSHER_PATH = _locate_pusher()


# ---------------------------------------------------------------------
# Minimal fakes that match ib_insync's surface area used by the patch.
# ---------------------------------------------------------------------
class _FakeOrder:
    def __init__(self, orderId=4729):
        self.orderId = orderId


class _FakeOrderStatus:
    def __init__(self, status="Submitted"):
        self.status = status


class _FakeLogEntry:
    def __init__(self, status="", message="", errorCode=0):
        self.status = status
        self.message = message
        self.errorCode = errorCode


class _FakeTrade:
    """Replicates the slice of ib_insync.Trade the pusher reads:
       order, orderStatus, log."""
    def __init__(self, orderId=4729, status="Submitted", log=None):
        self.order = _FakeOrder(orderId)
        self.orderStatus = _FakeOrderStatus(status)
        self.log = log or []

    def push_error(self, errorCode, message):
        """Simulate IB's async errorEvent appending to the trade log."""
        self.log.append(_FakeLogEntry(
            status=self.orderStatus.status,
            message=message,
            errorCode=errorCode,
        ))

    def push_status(self, new_status):
        self.orderStatus.status = new_status
        self.log.append(_FakeLogEntry(status=new_status))


class _FakeIB:
    def __init__(self, trades, sleep_advance_callbacks=None):
        self._trades = trades
        self.cancel_called_for = []
        # `sleep_advance_callbacks`: list of callables, one popped each
        # time ib.sleep() is called — lets tests inject errors at
        # specific iterations of the wait loop.
        self._cb = list(sleep_advance_callbacks or [])

    def openTrades(self):
        return self._trades

    def cancelOrder(self, order):
        self.cancel_called_for.append(int(order.orderId))

    def sleep(self, seconds):
        # Don't actually sleep — instead let the harness inject events
        # at this point in the loop.
        if self._cb:
            cb = self._cb.pop(0)
            cb()


class _CapturingAPI:
    """Capture all post_safe() / get_safe() calls."""
    def __init__(self, claim_result=True):
        self.posts = []
        self.gets = []
        self._claim_result = claim_result

    def get_safe(self, path, timeout=None):
        self.gets.append({"path": path, "timeout": timeout})
        return None

    def post_safe(self, path, payload=None, timeout=None):
        self.posts.append({"path": path, "payload": payload})
        if "/claim/" in path:
            return self._claim_result
        return True


# ---------------------------------------------------------------------
# Build a minimal pusher instance carrying just the patched method
# ---------------------------------------------------------------------
def _make_pusher(ib, api):
    """Import the pusher module without running its main block, and
    return a thin instance with .ib and .api wired up.

    The pusher module imports a lot of stuff at module-load time
    (sqlite, requests, etc.). We can't import it directly under
    pytest because the working directory is /app, not the Windows path
    it expects, and ibapi may not be present. So we load just the
    method under test in isolation."""
    spec = importlib.util.spec_from_file_location("ib_data_pusher",
                                                  PUSHER_PATH)
    src = open(PUSHER_PATH).read()
    # Extract just the `_execute_queued_cancellation` + helper method
    # by exec-ing a stub class with those methods bound.
    import re
    # The two methods we test: _execute_queued_cancellation,
    # _report_cancellation_result. Pull them via regex.
    method_pattern = re.compile(
        r"    def (_execute_queued_cancellation|_report_cancellation_result)"
        r"\(self.*?\n(?=    def |\nclass |\n@)",
        re.DOTALL,
    )
    matches = method_pattern.findall(src)
    method_chunks = re.findall(
        r"(    def (?:_execute_queued_cancellation|"
        r"_report_cancellation_result)\(self.*?)(?=\n    def |\nclass |\n@router|\Z)",
        src,
        re.DOTALL,
    )
    assert len(method_chunks) >= 2, (
        f"Could not locate both patched methods in pusher; "
        f"found {len(method_chunks)}"
    )

    # Build a synthetic class with just those methods + a logger shim.
    # The methods reference `self.ib`, `self.api`, and the module-level
    # `logger` + `datetime`.
    import logging
    stub_logger = logging.getLogger("pusher_test_stub")
    from datetime import datetime

    method_src = "\n\n".join(method_chunks)
    class_src = (
        "from datetime import datetime\n"
        "class _Stub:\n"
        "    def __init__(self, ib, api, logger):\n"
        "        self.ib = ib\n"
        "        self.api = api\n"
        "        self._logger = logger\n"
        + method_src
    )
    # The patched code calls bare `logger.xxx`, not `self._logger`.
    # Inject `logger` as a module-level name in the exec namespace.
    ns = {"logger": stub_logger, "datetime": datetime}
    exec(class_src, ns)
    inst = ns["_Stub"](ib, api, stub_logger)
    return inst


# ---------------------------------------------------------------------
# 1. The 2026-05-21 bug regression: IB error 10147 → reported as failed
# ---------------------------------------------------------------------
def test_10147_error_reported_as_failed_not_pending():
    trade = _FakeTrade(orderId=4729, status="Submitted")
    # On the 2nd sleep iteration, IB pushes a 10147 error to the log.
    cbs = [
        lambda: None,                       # iter 1: nothing yet
        lambda: trade.push_error(10147, "Order Id 4729 that needs to be cancelled is not found."),
        lambda: None,                       # filler
    ]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI(claim_result=True)
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({
        "ib_order_id": 4729,
        "reason": "v19.34.71 pre-close",
    })

    # cancelOrder MUST have been issued
    assert ib.cancel_called_for == [4729]
    # Result POST MUST have been made with status="failed"
    result_posts = [p for p in api.posts if p["path"] == "/api/ib/cancellations/result"]
    assert len(result_posts) == 1, f"expected exactly 1 result POST, got {api.posts}"
    payload = result_posts[0]["payload"]
    assert payload["ib_order_id"] == 4729
    assert payload["status"] == "failed", (
        f"v19.34.71 bug regression: should have reported 'failed' not "
        f"{payload['status']!r} when IB errored with 10147"
    )
    assert "10147" in payload["error"], (
        f"error message must include the IB error code so backend's "
        f"_is_fatal_cancel_error() can detect it; got: {payload['error']!r}"
    )


def test_10148_error_also_reported_as_failed():
    """10148 = 'OrderId already filled/cancelled' — also fatal."""
    trade = _FakeTrade(orderId=5000)
    cbs = [lambda: trade.push_error(10148, "Already filled/cancelled.")]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 5000})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    assert result_posts[0]["payload"]["status"] == "failed"
    assert "10148" in result_posts[0]["payload"]["error"]


def test_200_no_security_def_reported_as_failed():
    """Error 200 ('No security definition') is also in the fatal list."""
    trade = _FakeTrade(orderId=6000)
    cbs = [lambda: trade.push_error(200, "No security definition has been found for the request.")]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 6000})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    assert result_posts[0]["payload"]["status"] == "failed"
    assert "200" in result_posts[0]["payload"]["error"]


# ---------------------------------------------------------------------
# 2. Happy path: cancel acked → reported as cancelled
# ---------------------------------------------------------------------
def test_normal_cancel_terminal_reported_as_cancelled():
    trade = _FakeTrade(orderId=100, status="Submitted")
    cbs = [
        lambda: None,
        lambda: trade.push_status("Cancelled"),
    ]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 100})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    assert result_posts[0]["payload"]["status"] == "cancelled"


# ---------------------------------------------------------------------
# 3. Filled-before-cancel race → reported as failed (unchanged behavior)
# ---------------------------------------------------------------------
def test_filled_before_cancel_reported_as_failed():
    trade = _FakeTrade(orderId=200, status="Submitted")
    cbs = [lambda: trade.push_status("Filled")]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 200})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    p = result_posts[0]["payload"]
    assert p["status"] == "failed"
    assert "filled before" in (p["error"] or "").lower()


# ---------------------------------------------------------------------
# 4. Timeout with NO terminal AND no errorCode → failed (was: pending)
# ---------------------------------------------------------------------
def test_timeout_no_signal_reported_as_failed_not_pending():
    """The pre-v19.34.71 path that caused the 2026-05-21 silent stale-
    drop chain. Now: report failed so backend's failure_count bumps,
    rather than pending which left the entry re-serveable."""
    trade = _FakeTrade(orderId=999, status="Submitted")
    # No callbacks → 20 iterations of nothing happens
    ib = _FakeIB([trade], sleep_advance_callbacks=[lambda: None] * 25)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 999})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    assert len(result_posts) == 1
    p = result_posts[0]["payload"]
    assert p["status"] == "failed", (
        f"v19.34.71 contract: timeout with no signal must be reported "
        f"as 'failed' (not 'pending') so backend's failure_count bumps; "
        f"got {p['status']!r}"
    )
    assert "cancel_timeout_no_terminal_no_errorcode" in p["error"]


# ---------------------------------------------------------------------
# 5. Pre-existing-error in log (before our cancel) is IGNORED
# ---------------------------------------------------------------------
def test_pre_existing_error_in_log_not_attributed_to_our_cancel():
    """If the trade already had an error in its log BEFORE we called
    cancelOrder, our baseline scan should ignore it. Only errors that
    appear AFTER our cancel count as a cancel rejection."""
    trade = _FakeTrade(orderId=300, status="Submitted")
    # Trade carries a stale 2104 ('market data farm OK') errorCode=0
    # in the log already — should be ignored regardless. Add a real
    # pre-existing error (e.g. 322) that's not from our cancel.
    trade.log.append(_FakeLogEntry(status="Submitted", message="some old warning", errorCode=322))

    # Then our cancel terminates cleanly — no new error.
    cbs = [
        lambda: None,
        lambda: trade.push_status("Cancelled"),
    ]
    ib = _FakeIB([trade], sleep_advance_callbacks=cbs)
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 300})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    assert result_posts[0]["payload"]["status"] == "cancelled", (
        f"pre-existing 322 error in log should NOT be attributed to our "
        f"cancel; expected 'cancelled' got {result_posts[0]['payload']!r}"
    )


# ---------------------------------------------------------------------
# 6. cancelOrder() raises → still reports failed (existing path, regression-locked)
# ---------------------------------------------------------------------
def test_cancel_order_raises_still_reports_failed():
    trade = _FakeTrade(orderId=400)

    class _ExplodingIB(_FakeIB):
        def cancelOrder(self, order):
            raise RuntimeError("ib_insync connection lost")

    ib = _ExplodingIB([trade])
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 400})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    p = result_posts[0]["payload"]
    assert p["status"] == "failed"
    assert "ib_insync connection lost" in p["error"]


# ---------------------------------------------------------------------
# 7. Order not in openTrades → reports not_found (existing path)
# ---------------------------------------------------------------------
def test_order_not_in_open_trades_reports_not_found():
    ib = _FakeIB([])  # empty openTrades
    api = _CapturingAPI()
    pusher = _make_pusher(ib, api)

    pusher._execute_queued_cancellation({"ib_order_id": 500})

    result_posts = [p for p in api.posts if "/result" in p["path"]]
    p = result_posts[0]["payload"]
    assert p["status"] == "not_found"
