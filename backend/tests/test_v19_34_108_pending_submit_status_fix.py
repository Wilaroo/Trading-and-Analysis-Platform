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
  `PendingSubmit` is IB's FIRST transient state (order transmitted but
  not yet ack'd by the order destination). When the pusher's event
  loop was contended (which v103/v107 made common because of the
  30-second bracket-fill wait), orders frequently stayed in
  `PendingSubmit` past the 30-second timeout, fell through to the
  `else` branch, and got reported as `rejected: Unknown status:
  PendingSubmit`.

  Spark's reconciler interpreted those rejections as "adoption
  failed, retry" and spawned new ADOPT-OCA wrappers on each pass.
  This was the SEPARATE engine driving the storm v107b had to clean
  up — v107 only fixed the bracket variant, v108 fixes the single-leg
  adoption variant.

The fix: include PendingSubmit AND PendingCancel in the "still
pending" branch so the pusher reports `pending` (not `rejected`) for
those transient states. Spark's `get_order_result` treats `pending`
as "keep polling" and the reconciler skips on next pass thanks to
`trade.stop_order_id` already being stamped.

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


# IB-API order-status states that mean "the order is still working,
# don't conclude it failed". Anything outside this set + the terminal
# {Filled, Cancelled, ApiCancelled, Inactive} means we genuinely don't
# know — but PendingSubmit / PendingCancel are normal transients and
# MUST be in the pending bucket, not rejected.
_PENDING_STATES = (
    "Submitted",
    "PreSubmitted",
    "PendingSubmit",
    "PendingCancel",
)


class TestPendingSubmitNotRejected:

    def test_pending_submit_treated_as_pending_not_rejected(self, pusher_src):
        """The pre-v108 bug was `if status == "Submitted" or status ==
        "PreSubmitted"`. The new code must check membership in a tuple/
        set that includes PendingSubmit."""
        # Anchor on v108's explicit code-comment marker — unique to the
        # single-leg pending-classification block (the bracket path has
        # its own separate pending log line).
        anchor = pusher_src.find("v19.34.108")
        assert anchor >= 0, "v108 fix comment marker missing from pusher"
        window = pusher_src[anchor: anchor + 1500]
        # Must NOT contain the old buggy form.
        assert (
            'status == "Submitted" or trade.orderStatus.status == "PreSubmitted"'
            not in window
        ), (
            "Pre-v108 buggy condition still present — PendingSubmit will "
            "be misclassified as rejected. See incident 2026-02-12."
        )
        # Must mention all 4 pending states.
        for state in _PENDING_STATES:
            assert state in window, (
                f"Pending-states tuple is missing `{state}` — v108 fix incomplete."
            )

    def test_unknown_status_branch_logs_state(self, pusher_src):
        """The else-branch should still exist for genuinely unknown
        statuses (so we don't accidentally swallow new IB states
        silently), and should log the actual state for diagnosis."""
        idx = pusher_src.find('"Unknown status:')
        assert idx >= 0, (
            "The `Unknown status:` else-branch was removed — we still "
            "want it as a diagnostic for genuinely-unknown IB statuses."
        )

    def test_pending_error_string_includes_state(self, pusher_src):
        """v108 enriches the `pending` error string with the actual
        state so the operator can see which transient was lingering."""
        idx = pusher_src.find("Order still pending (state=")
        assert idx >= 0, (
            "Pending-error string should include `(state=...)` so the "
            "operator can see whether it was PendingSubmit (IB hasn't "
            "ack'd) or PreSubmitted (IB ack'd, waiting for trigger)."
        )


class TestBackwardCompatibility:

    def test_filled_branch_unchanged(self, pusher_src):
        """v108 must NOT touch the Filled branch — that's the path
        v107 fixed with the new bracket-ACK kwargs."""
        assert 'if trade.orderStatus.status == "Filled":' in pusher_src

    def test_cancelled_branch_unchanged(self, pusher_src):
        """Cancelled / ApiCancelled detection is a separate concern."""
        assert (
            'trade.orderStatus.status in ["Cancelled", "ApiCancelled"]'
            in pusher_src
        )

    def test_inactive_branch_unchanged(self, pusher_src):
        """Inactive = IB explicitly rejected. Must still be a hard reject."""
        assert 'trade.orderStatus.status == "Inactive"' in pusher_src
