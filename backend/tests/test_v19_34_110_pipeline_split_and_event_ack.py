"""
Tests for v19.34.110 — Pipeline tile split + event-driven pusher ACK.

Two parallel changes ship under v110:

1. P3-A — `order_pipeline.ib_pending` now reaches the V5 HUD via
   `SentComStatus`, fixing a latent typo (pre-v110 read of
   `pending_count` / `executing_count` / `filled_today` which never
   matched the real `get_queue_status` keys) and adding the new
   `ib_pending` field introduced by v19.34.109.

2. P3-B — `ib_data_pusher.py`:
   - Replaces the two 30s blocking poll loops (single-order +
     bracket-parent) with `trade.statusEvent` subscriptions.
   - Removes the "still pending after 30s" branch.
   - The executor synchronously ACKs Spark with `pending+ib_order_id`
     after `placeOrder` (Spark's v109 translation → IB_PENDING) and
     returns immediately. Terminal states (Filled / Cancelled /
     Inactive) flow back via the event handler.

The pusher tests stub `ib_insync` types since CI doesn't have the
package. They drive `_on_trade_status_change` directly with fake
`trade.orderStatus` objects to verify the dedup, status-mapping, and
field-forwarding contract.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PUSHER_DIR = BACKEND_DIR.parent / "documents" / "scripts"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# P3-A — SentComStatus.to_dict() surfaces ib_pending in order_pipeline
# ---------------------------------------------------------------------------

class TestSentComStatusIbPendingField:
    """SentComStatus → order_pipeline must expose `ib_pending` so the
    V5 HUD can render the `5q + 3@ib` split."""

    def test_to_dict_exposes_ib_pending(self):
        from services.sentcom_service import SentComStatus

        s = SentComStatus(
            connected=True,
            state="active",
            pending_orders=5,
            executing_orders=0,
            filled_orders=12,
            ib_pending_orders=3,
        )
        out = s.to_dict()
        assert "order_pipeline" in out
        op = out["order_pipeline"]
        assert op["pending"] == 5
        assert op["executing"] == 0
        assert op["filled"] == 12
        assert op["ib_pending"] == 3, (
            "ib_pending MUST be a top-level key under order_pipeline so "
            "the V5 HUD's derivePipelineCounts can split the tile."
        )

    def test_ib_pending_defaults_to_zero(self):
        from services.sentcom_service import SentComStatus

        s = SentComStatus(connected=False, state="offline")
        out = s.to_dict()
        assert out["order_pipeline"]["ib_pending"] == 0

    def test_legacy_router_fallback_includes_ib_pending(self):
        """The exception fallback in routers/sentcom.py must also expose
        ib_pending so the frontend never reads `undefined`."""
        router_path = BACKEND_DIR / "routers" / "sentcom.py"
        text = router_path.read_text()
        # Find the fallback block
        assert '"ib_pending": 0' in text, (
            "Exception fallback in routers/sentcom.py MUST include "
            "`ib_pending: 0` in order_pipeline so the V5 HUD never sees "
            "an undefined field on the error path."
        )


# ---------------------------------------------------------------------------
# P3-A — sentcom_service reads the correct queue_status keys
# ---------------------------------------------------------------------------

class TestSentComServiceQueueKeyMapping:
    """Pre-v110 the service read `pending_count` / `executing_count` /
    `filled_today` from `get_queue_status`, but the real method returns
    `pending` / `executing` / `filled` / `ib_pending`. v110 fixes the
    mapping and adds the ib_pending read."""

    def test_uses_correct_queue_status_keys(self):
        src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()
        # The fix must read the new keys
        assert 'queue_status.get("pending"' in src
        assert 'queue_status.get("executing"' in src
        assert 'queue_status.get("filled"' in src
        assert 'queue_status.get("ib_pending"' in src

    def test_ib_pending_orders_in_status_payload(self):
        """End-to-end: a SentComStatus constructed with non-zero
        ib_pending_orders surfaces correctly in to_dict."""
        from services.sentcom_service import SentComStatus

        s = SentComStatus(
            connected=True,
            state="active",
            ib_pending_orders=7,
        )
        assert s.ib_pending_orders == 7
        assert s.to_dict()["order_pipeline"]["ib_pending"] == 7


# ---------------------------------------------------------------------------
# P3-B — pusher event-driven ACK handler
# ---------------------------------------------------------------------------

class _StubExecutor:
    """Minimal stand-in for IBDataPusher that exposes the v110 event
    methods. We test them in isolation without importing ib_insync."""

    def __init__(self):
        self._terminal_reported = {}
        self.reports = []

    def _report_order_result(self, order_id, status, **kwargs):
        # Match the production signature loosely
        self.reports.append({"order_id": order_id, "status": status, **kwargs})


def _load_pusher_handlers():
    """Hot-load the two v110 methods from ib_data_pusher.py without
    importing the whole module (which depends on ib_insync)."""
    pusher_path = PUSHER_DIR / "ib_data_pusher.py"
    src = pusher_path.read_text()

    # Extract `_on_trade_status_change` + `_attach_status_event` source
    # via simple sentinel parsing.
    start = src.index("def _on_trade_status_change")
    end = src.index("\n    # ====", start)
    # Walk backwards to method-def line
    body = src[start:end]
    # Replace `def ` with `def ` (already there) and dedent 4 spaces
    # since they're class methods.
    lines = body.splitlines()
    dedented = "\n".join(l[4:] if l.startswith("    ") else l for l in lines)
    # Compile in a fresh namespace
    ns = {"Optional": __import__("typing").Optional, "partial": __import__("functools").partial, "logger": __import__("logging").getLogger("test")}
    exec(dedented, ns)
    return ns["_on_trade_status_change"], ns["_attach_status_event"]


class TestEventDrivenAckMapping:
    """`_on_trade_status_change` translates IB orderStatus.status into
    Spark-side terminal ACKs (filled / cancelled / rejected) and dedups
    so a second event for the same order_id is a no-op."""

    def setup_method(self):
        on_status, _ = _load_pusher_handlers()
        self._on_status = on_status
        self.pusher = _StubExecutor()

    def _trade(self, status, avg_fill=None, filled=0, ib_order_id=999, why_held=""):
        return SimpleNamespace(
            orderStatus=SimpleNamespace(
                status=status,
                avgFillPrice=avg_fill,
                filled=filled,
                whyHeld=why_held,
            ),
            order=SimpleNamespace(orderId=ib_order_id),
        )

    def test_filled_event_reports_filled(self):
        t = self._trade("Filled", avg_fill=42.5, filled=100, ib_order_id=555)
        self._on_status(self.pusher, "ord-1", "oca-A", 88, [77], t)
        assert len(self.pusher.reports) == 1
        r = self.pusher.reports[0]
        assert r["status"] == "filled"
        assert r["fill_price"] == 42.5
        assert r["filled_qty"] == 100
        assert r["ib_order_id"] == 555
        assert r["oca_group"] == "oca-A"
        assert r["stop_order_id"] == 88
        assert r["target_order_ids"] == [77]

    def test_cancelled_event_reports_cancelled(self):
        t = self._trade("Cancelled")
        self._on_status(self.pusher, "ord-2", None, None, None, t)
        assert self.pusher.reports[0]["status"] == "cancelled"

    def test_api_cancelled_treated_as_cancelled(self):
        t = self._trade("ApiCancelled")
        self._on_status(self.pusher, "ord-3", None, None, None, t)
        assert self.pusher.reports[0]["status"] == "cancelled"

    def test_inactive_event_reports_rejected_with_why_held(self):
        t = self._trade("Inactive", why_held="insufficient buying power")
        self._on_status(self.pusher, "ord-4", None, None, None, t)
        r = self.pusher.reports[0]
        assert r["status"] == "rejected"
        assert "insufficient buying power" in (r.get("error") or "")

    def test_transient_states_are_no_op(self):
        """Submitted / PreSubmitted / PendingSubmit / PendingCancel MUST
        NOT trigger an ACK — the executor has already sent the
        `pending+ib_order_id` ACK that flips Spark to IB_PENDING."""
        for s in ("Submitted", "PreSubmitted", "PendingSubmit", "PendingCancel"):
            t = self._trade(s)
            self._on_status(self.pusher, f"ord-tr-{s}", None, None, None, t)
        assert self.pusher.reports == [], (
            "Transient IB states MUST NOT generate ACKs — Spark already "
            "holds the row in IB_PENDING via the synchronous submit ACK."
        )

    def test_terminal_ack_is_idempotent(self):
        """ib_insync fires statusEvent on every transition. Once we've
        reported a terminal state for an order_id, repeat invocations
        must be silent."""
        t = self._trade("Filled", avg_fill=10.0, filled=1)
        self._on_status(self.pusher, "ord-x", None, None, None, t)
        self._on_status(self.pusher, "ord-x", None, None, None, t)
        self._on_status(self.pusher, "ord-x", None, None, None, t)
        assert len(self.pusher.reports) == 1


class TestEventDrivenAckSourceContract:
    """Source-level assertions that the v110 refactor actually removed
    the blocking-poll branches and the 'still pending after 30s' string."""

    @pytest.fixture
    def pusher_src(self):
        return (PUSHER_DIR / "ib_data_pusher.py").read_text()

    def test_no_more_30s_blocking_poll_for_orders(self, pusher_src):
        """The single-order executor previously did:
            max_wait = 30; start_time = time.time(); while time.time() - start_time < max_wait: self.ib.sleep(0.5)
        Both loops must be gone in v110."""
        # The "Wait for fill (with timeout)" comment was the marker for
        # the single-order poll. The "Wait for parent fill" comment was
        # the marker for the bracket poll. Both should be removed.
        assert "Wait for fill (with timeout)" not in pusher_src
        assert "Wait for parent fill (children sit GTC on the book)." not in pusher_src

    def test_no_still_pending_branch(self, pusher_src):
        """The 'Order still pending after 30s' / 'parent still pending
        after 30s' fallback ACKs are gone — IB_PENDING is now reached
        via the synchronous submit ACK, not via timeout."""
        assert "still pending after {max_wait}s" not in pusher_src
        assert "parent still pending after" not in pusher_src

    def test_attach_status_event_called_for_single_order(self, pusher_src):
        """The single-order placement path must subscribe statusEvent."""
        # Find the single-order branch (after `trade = self.ib.placeOrder(contract, ib_order)`)
        anchor = "trade = self.ib.placeOrder(contract, ib_order)"
        assert anchor in pusher_src
        # The next ~30 lines must reference _attach_status_event
        idx = pusher_src.index(anchor)
        window = pusher_src[idx:idx + 1500]
        assert "_attach_status_event(trade, order_id)" in window

    def test_attach_status_event_called_for_bracket(self, pusher_src):
        """The bracket placement path must subscribe statusEvent on the
        parent and forward stop_order_id / target_order_ids / oca_group."""
        anchor = "parent_trade = self.ib.placeOrder(contract, parent_ib)"
        assert anchor in pusher_src
        idx = pusher_src.index(anchor)
        window = pusher_src[idx:idx + 2500]
        assert "_attach_status_event(" in window
        assert "parent_trade" in window
        assert "oca_group=oca_group" in window
        assert "stop_order_id=int(stp_ib.orderId)" in window
        assert "target_order_ids=target_ids" in window

    def test_synchronous_pending_ack_after_submit(self, pusher_src):
        """Executor must ACK Spark `pending+ib_order_id` synchronously
        after placeOrder so Spark's v109 translation moves the row to
        IB_PENDING (not plain pending, which would re-trigger polling)."""
        assert "Submitted to IB — awaiting terminal event" in pusher_src


# ---------------------------------------------------------------------------
# P3-A — V5 frontend wiring (read-only source checks)
# ---------------------------------------------------------------------------

class TestV5FrontendWiring:
    """The V5 frontend reads `order_pipeline.ib_pending` and passes a
    structured `orderSplit` prop into PipelineHUDV5. Smoke-check the
    JSX source for the contract."""

    @pytest.fixture
    def v5_src(self):
        return (BACKEND_DIR.parent / "frontend" / "src" / "components" /
                "sentcom" / "SentComV5View.jsx").read_text()

    @pytest.fixture
    def hud_src(self):
        return (BACKEND_DIR.parent / "frontend" / "src" / "components" /
                "sentcom" / "panels" / "PipelineHUDV5.jsx").read_text()

    def test_v5_view_reads_ib_pending(self, v5_src):
        assert "pipeline.ib_pending" in v5_src
        assert "order_split" in v5_src

    def test_v5_view_passes_order_split_prop(self, v5_src):
        assert "orderSplit={counts.order_split}" in v5_src

    def test_hud_accepts_order_split_prop(self, hud_src):
        assert "orderSplit," in hud_src
        # Stage component must consume it
        assert "splitCount={orderSplit}" in hud_src

    def test_hud_renders_split_with_q_and_at_ib_labels(self, hud_src):
        """When orderSplit.ibPending > 0, the tile renders something
        like `5q + 3@ib`. Verify the labels are present."""
        assert ">q<" in hud_src
        assert ">@ib<" in hud_src

    def test_hud_falls_back_to_flat_count_when_no_ib_pending(self, hud_src):
        """If `ibPending === 0` (no orders sitting at IB), render the
        original flat count instead of `5q + 0@ib`."""
        assert "splitCount.ibPending ?? 0) > 0" in hud_src
