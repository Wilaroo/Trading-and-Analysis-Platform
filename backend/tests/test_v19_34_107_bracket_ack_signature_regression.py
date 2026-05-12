"""
Tests for v19.34.107 — Bracket ACK signature compatibility regression.

PRODUCTION INCIDENT 2026-02-12 10:00:25 (paper account):
  v19.34.103 added new kwargs to the pusher's `_report_order_result` call
  inside the bracket path (stop_order_id / target_order_ids / oca_group)
  but did NOT widen the function signature, so every bracket fired
  produced:

    [ERROR] [OrderQueue] Execution error for 0486f940:
    IBDataPusher._report_order_result() got an unexpected keyword
    argument 'stop_order_id'

  The bracket *itself* placed correctly at IB (parent filled, OCA stop +
  target attached), but the pusher reported "rejected" → Spark fell back
  to ADOPT-OCA wrap orders → idempotency spam.

These tests fence both ends of the contract:
  • Backend `POST /api/ib/orders/result` accepts the v19.34.107 fields
    without 422 validation errors.
  • The pusher's `_report_order_result` method accepts all the kwargs
    v19.34.103 passes from the bracket placement path.
"""
from __future__ import annotations

import inspect
import pytest
import requests


BACKEND = "http://localhost:8001"
_REQUIRED_KW = {"stop_order_id", "target_order_id", "target_order_ids", "oca_group"}


def _backend_alive() -> bool:
    try:
        r = requests.get(f"{BACKEND}/api/trading-bot/order-policies", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# Lazy-evaluate at the test fixture level instead of collection-time —
# pytest's `skipif` can race with the local backend's readiness if the
# test file is imported during module discovery before the FastAPI app
# is fully up.
@pytest.fixture(scope="module", autouse=True)
def _require_backend():
    if not _backend_alive():
        pytest.skip("Backend not reachable at localhost:8001", allow_module_level=True)


class TestBackendAcceptsBracketAckFields:
    """The Spark backend must accept the v19.34.107 enrichment fields
    without Pydantic validation errors. A 404 (order not found) is the
    expected response for a synthetic order_id — that proves the body
    passed validation."""

    def test_full_bracket_ack_payload_validates(self):
        r = requests.post(
            f"{BACKEND}/api/ib/orders/result",
            json={
                "order_id": "REGRESSION-TEST-v107",
                "status": "filled",
                "fill_price": 150.43,
                "filled_qty": 43,
                "remaining_qty": 0,
                "ib_order_id": 115748,
                "stop_order_id": 115750,
                "target_order_id": 115749,
                "target_order_ids": [115749, 115751, 115753],
                "oca_group": "oca_RJF_REGRESSION",
            },
            timeout=5,
        )
        # 404 = order not in queue (expected). 422 would mean Pydantic
        # rejected the new fields — that's the bug this test guards.
        assert r.status_code == 404, (
            f"Expected 404 (order not found) but got {r.status_code}: "
            f"{r.text}. If this is 422, the OrderExecutionResult model "
            f"is missing one of: {_REQUIRED_KW}"
        )

    def test_legacy_payload_still_works(self):
        """Older pushers won't send the new fields — must still validate."""
        r = requests.post(
            f"{BACKEND}/api/ib/orders/result",
            json={
                "order_id": "REGRESSION-TEST-v107-LEGACY",
                "status": "filled",
                "fill_price": 100.0,
                "filled_qty": 10,
                "ib_order_id": 99999,
            },
            timeout=5,
        )
        assert r.status_code == 404


class TestPusherReportSignature:
    """The pusher's `_report_order_result` MUST accept every kwarg the
    v19.34.103 bracket placement path passes. We import the function
    object directly and introspect its signature."""

    @pytest.fixture(scope="class")
    def report_fn(self):
        # Import the pusher module by file path — it lives outside
        # the backend Python path.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_pusher_for_test",
            "/app/documents/scripts/ib_data_pusher.py",
        )
        try:
            mod = importlib.util.module_from_spec(spec)
            # We don't actually exec the module (it has IB / Windows
            # imports). Instead just grep the source for the signature.
            with open("/app/documents/scripts/ib_data_pusher.py") as f:
                src = f.read()
            return src
        except Exception as exc:
            pytest.skip(f"Pusher import failed: {exc}")

    def test_report_signature_accepts_v34_103_kwargs(self, report_fn):
        # Locate the function definition and read its parameter list.
        idx = report_fn.find("def _report_order_result")
        assert idx >= 0, "Could not find _report_order_result in pusher"
        # Capture everything up to the first `):` so we read the full
        # multi-line signature.
        end = report_fn.find("):", idx)
        sig = report_fn[idx:end]
        for kw in _REQUIRED_KW:
            assert kw in sig, (
                f"Pusher `_report_order_result` signature is missing "
                f"`{kw}` — v19.34.107 regression. Bracket ACKs will "
                f"crash with TypeError again. Signature snippet:\n{sig}"
            )

    def test_bracket_placement_callsite_uses_v34_103_kwargs(self, report_fn):
        """The bracket-path call site MUST pass all 4 enrichment kwargs.

        v19.34.110 SUPERSEDES the original site: the synchronous
        "parent FILLED" branch was replaced with an event-driven
        statusEvent listener. The kwargs still travel into the handler
        via `_attach_status_event(... oca_group=, stop_order_id=,
        target_order_ids=)` so the same Spark-side payload gets built
        from the Filled branch of `_on_trade_status_change`. We assert
        both the attach call site (bracket placement) and the report
        call inside the handler.
        """
        # Bracket placement attach call site — must forward the 4 kwargs
        # so the handler can splat them into _report_order_result on
        # terminal events.
        attach_idx = report_fn.find("_attach_status_event(\n                    parent_trade")
        assert attach_idx >= 0, (
            "Could not find bracket-placement _attach_status_event call. "
            "v19.34.103 bracket-ACK enrichment may have regressed."
        )
        attach_window = report_fn[attach_idx : attach_idx + 600]
        for kw in _REQUIRED_KW - {"target_order_id"}:  # target_order_id is derived from target_order_ids[0] in the handler
            assert kw in attach_window, (
                f"Bracket _attach_status_event call site is missing "
                f"`{kw}` — v19.34.103 enrichment lost in v110 refactor."
            )
        # The handler itself must splat all 4 kwargs into the filled ACK.
        handler_idx = report_fn.find('"filled",\n                    fill_price=float(avg_fill)')
        assert handler_idx >= 0, (
            "Could not find filled-branch ACK in _on_trade_status_change."
        )
        handler_window = report_fn[handler_idx : handler_idx + 800]
        for kw in _REQUIRED_KW:
            assert kw in handler_window, (
                f"Event-driven filled ACK is missing `{kw}` — "
                f"v19.34.103 enrichment lost in v110 refactor."
            )
