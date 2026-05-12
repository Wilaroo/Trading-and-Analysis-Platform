"""
Tests for v19.34.108 — Pusher PendingSubmit / PendingCancel status fix.

PRODUCTION INCIDENT 2026-02-12 (paper account):
  After v107 was deployed and the immediate bracket-ACK storm was
  flushed, the operator queried the order queue and found:

      "counts": { "filled": 501, "rejected": 3463, "total": 4405 }

  → 78% rejection rate. Drilling into the rejected orders revealed
  the error string:

      "error": "Unknown status: PendingSubmit"

  Root cause: `ib_data_pusher.py::_execute_order` placed an order at
  IB, polled for 30 seconds for it to transition to Filled/Cancelled/
  Inactive, then checked status against ONLY {Submitted, PreSubmitted}.
  `PendingSubmit` is IB's FIRST transient state. When the pusher's
  event loop was contended, orders frequently stayed in `PendingSubmit`
  past the 30-second timeout and got reported as `rejected: Unknown
  status: PendingSubmit`. Spark's reconciler interpreted those as
  "adoption failed, retry" and spawned new ADOPT-OCA wrappers.

v108 fix: include PendingSubmit AND PendingCancel in the "still
pending" branch so the pusher reported `pending` (not `rejected`).

v19.34.110 SUPERSEDES the polling architecture entirely:
  The 30-second `while time.time() < max_wait: ib.sleep(0.5)` loop and
  the "still pending after 30s" fallback branch are GONE. The pusher
  now subscribes to `trade.statusEvent` and never polls — terminal
  states (Filled / Cancelled / Inactive) flow back via the event
  callback, transient states (Submitted / PreSubmitted / PendingSubmit
  / PendingCancel) are a no-op in the handler (no spurious ACK to
  Spark). The semantic guarantee — `PendingSubmit must never be
  reported as rejected` — is now stronger: the unknown-status branch
  doesn't run at all under v110 because we never time-out a transient.

This file updates the v108 assertions to verify the v110 equivalent
behavior so the regression coverage stays meaningful.

Tests are source-grep based because the pusher module can't be
imported in the Linux test env (Windows ib_insync + Win32 imports).
"""
from __future__ import annotations

import pytest


PUSHER_PATH = "/app/documents/scripts/ib_data_pusher.py"


@pytest.fixture(scope="module")
def pusher_src():
    with open(PUSHER_PATH) as f:
        return f.read()


# IB-API transient order-status states that mean "the order is still
# working, don't conclude it failed." Under v110 these are all no-ops
# inside _on_trade_status_change (no ACK to Spark — the order remains
# in IB_PENDING via the synchronous submit ACK).
_TRANSIENT_STATES = (
    "Submitted",
    "PreSubmitted",
    "PendingSubmit",
    "PendingCancel",
)


class TestPendingSubmitNotRejected:

    def test_pending_submit_never_reaches_unknown_status_branch(self, pusher_src):
        """v108 baseline: ensure PendingSubmit is recognised somewhere
        in the pusher (we want the IB transient name on record).

        v110 superseded: the entire 30s timeout + unknown-status fall-
        through was removed. The compile-time guarantee is now stronger:
        we never time-out a transient, so we cannot report
        `Unknown status: PendingSubmit`. Assert the legacy
        `Unknown status:` branch is gone (or moved to the event handler
        with a clear comment), and PendingSubmit lives only in the
        statusEvent handler context.
        """
        # The legacy unknown-status string is removed under v110.
        assert "Unknown status:" not in pusher_src, (
            "The legacy `Unknown status: {state}` rejection fallback was "
            "removed by v110 — re-introducing it would re-introduce the "
            "v108 incident. Use the statusEvent listener instead."
        )

    def test_transient_states_handled_in_event_listener(self, pusher_src):
        """All 4 transient states must be acknowledged in the
        statusEvent handler so a future contributor doesn't accidentally
        treat one as terminal. We anchor on the v110 handler's
        transient-states comment block."""
        anchor = pusher_src.find("_on_trade_status_change")
        assert anchor >= 0, "v110 statusEvent handler missing"
        window = pusher_src[anchor : anchor + 5000]
        # The handler must enumerate the transient states explicitly in
        # the comment block (operator-readable contract).
        for state in _TRANSIENT_STATES:
            assert state in window, (
                f"Transient state `{state}` is not documented in the "
                f"v110 statusEvent handler — operator can't reason "
                f"about which IB states are passive no-ops."
            )

    def test_pending_ack_no_longer_includes_timeout_state_string(self, pusher_src):
        """Pre-v110 pending ACKs carried `(state=PendingSubmit)` in the
        error string so the operator could see why a 30s timeout fired.
        Under v110 there's no timeout — the pending ACK is fired
        synchronously after placeOrder with a clean status, and the
        v109 IB_PENDING translation drives the lifecycle from there."""
        # The pre-v110 substring should be gone.
        assert "Order still pending (state=" not in pusher_src, (
            "Pre-v110 `(state=...)` pending-error string still present — "
            "v110 should have replaced this with the synchronous "
            "`Submitted to IB — awaiting terminal event` ACK."
        )
        # And the v110 marker must be present.
        assert "Submitted to IB — awaiting terminal event" in pusher_src


class TestBackwardCompatibility:
    """v108's semantic guarantees (Filled / Cancelled / Inactive
    handling) must still hold under v110 — they just live in the event
    handler instead of the polling loop."""

    def test_filled_branch_in_event_handler(self, pusher_src):
        """v110: Filled detection moved from the polling loop to
        `_on_trade_status_change`. The terminal-ACK guarantee is
        preserved."""
        idx = pusher_src.find("_on_trade_status_change")
        assert idx >= 0
        window = pusher_src[idx : idx + 5000]
        assert 'if status == "Filled":' in window, (
            "Filled-branch ACK missing from v110 statusEvent handler — "
            "filled orders would never reach Spark."
        )

    def test_cancelled_branch_in_event_handler(self, pusher_src):
        """Cancelled / ApiCancelled remain terminal."""
        idx = pusher_src.find("_on_trade_status_change")
        window = pusher_src[idx : idx + 5000]
        assert 'status in ("Cancelled", "ApiCancelled")' in window, (
            "Cancelled-branch missing from v110 statusEvent handler."
        )

    def test_inactive_branch_in_event_handler(self, pusher_src):
        """Inactive = IB explicitly rejected. Must still be a hard reject."""
        idx = pusher_src.find("_on_trade_status_change")
        window = pusher_src[idx : idx + 5000]
        assert 'if status == "Inactive":' in window, (
            "Inactive-branch missing from v110 statusEvent handler — IB "
            "rejections would never reach Spark."
        )
