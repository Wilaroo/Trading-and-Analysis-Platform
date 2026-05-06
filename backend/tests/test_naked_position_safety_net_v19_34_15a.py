"""
v19.34.15a — Naked-position safety net tests.

Two separately-testable units:
1. `trade_executor_service.py` bracket-place ambiguous-status routing
2. `_poll_ib_for_silent_fill_v19_34_15a` post-rejection poll-back

Pre-fix bug: when the IB pusher returned a bracket-place response with
`status: 'unknown'` (or empty/missing), the bracket placement code at
`trade_executor_service.py:614` hard-rejected. Operator forensic
2026-05-06 found this caused 4879 unmanaged UPS shares — the parent
leg actually filled at IB but the bot wrote off the trade as failed,
leaving the IB position naked (no stop, no target).

Post-fix: ambiguous statuses route through the same TIMEOUT handler
that real timeouts already used, so v19.34.15b drift loop catches the
silent fill within ~30s. Additionally, a new poll-back task fires
after every rejection, polling IB position for 15s post-rejection
and emitting a `unbracketed_fill_detected_v19_34_15` stream event if
a silent fill is detected.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_executor_treats_unknown_status_as_timeout_v19_34_15a():
    """Static guard: the bracket-place path must route ambiguous statuses
    through the timeout handler instead of hard-rejecting."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "trade_executor_service.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()
    assert "v19.34.15a" in src, "v19.34.15a marker missing — patch reverted?"
    assert 'bracket_status_ambiguous_v19_34_15a' in src, (
        "v19.34.15a regression: ambiguous-status branch missing from "
        "place_bracket_order. Pre-fix path hard-rejected on status='unknown', "
        "leaving any silent fill orphaned at IB."
    )
    # Verify the routing is to status=timeout, NOT a hard reject.
    anchor = src.find("bracket_status_ambiguous_v19_34_15a")
    window = src[anchor: anchor + 800]
    assert '"status": "timeout"' in window, (
        "v19.34.15a regression: ambiguous status must return "
        '`status: "timeout"` so trade_execution.py treats it as a timeout.'
    )


def test_poll_back_helper_exists_v19_34_15a():
    """Static guard: post-rejection poll-back helper must exist."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "trade_execution.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()
    assert "_poll_ib_for_silent_fill_v19_34_15a" in src
    assert "unbracketed_fill_detected_v19_34_15" in src
    assert "pre_position_qty" in src, (
        "v19.34.15a regression: pre-submit IB position snapshot missing. "
        "Without it, the poll-back has no baseline to compare against."
    )


@pytest.mark.asyncio
async def test_poll_back_emits_event_on_silent_fill_v19_34_15a():
    """Simulate a silent fill: pre_qty=0, IB position becomes 100 mid-poll.
    Helper must emit unbracketed_fill_detected_v19_34_15 stream event."""
    from services.trade_execution import _poll_ib_for_silent_fill_v19_34_15a

    trade = SimpleNamespace(
        id="TID-1",
        symbol="UPS",
        shares=100,
        direction=SimpleNamespace(value="long"),
    )

    # Simulate the IB position changing on the 2nd poll tick.
    snapshots = [
        {"positions": [{"symbol": "UPS", "position": 0}]},   # tick 1: still 0
        {"positions": [{"symbol": "UPS", "position": 100}]}, # tick 2: filled!
    ]
    snap_i = {"i": 0}

    def get_pushed():
        i = snap_i["i"]
        snap_i["i"] = min(i + 1, len(snapshots) - 1)
        return snapshots[i]

    emitted = []

    async def fake_emit(payload):
        emitted.append(payload)

    # Patch the imports inside the helper.
    with patch("routers.ib._pushed_ib_data", new_callable=lambda: snapshots[0]) as _pd:
        # We need to mutate _pushed_ib_data each poll. The helper reads
        # `_pushed_ib_data` via `from routers.ib import _pushed_ib_data`,
        # which captures the reference at call time. So we patch by
        # mutating the dict's contents on each tick.
        with patch(
            "services.sentcom_service.emit_stream_event",
            new=fake_emit,
        ):
            # Drive 2 polls: simulate the position change between ticks.
            async def driver():
                # Mutate _pd contents to simulate the IB pusher writing
                # an updated position.
                await asyncio.sleep(0.5)
                _pd["positions"] = [{"symbol": "UPS", "position": 100}]

            await asyncio.gather(
                _poll_ib_for_silent_fill_v19_34_15a(
                    trade=trade,
                    pre_qty=0.0,
                    rejected_error="bracket_status_ambiguous_v19_34_15a",
                    poll_interval_s=0.2,
                    total_duration_s=2.0,
                ),
                driver(),
            )

    assert len(emitted) == 1, (
        "v19.34.15a regression: silent fill not emitted. "
        f"emitted={emitted}"
    )
    payload = emitted[0]
    assert payload["event"] == "unbracketed_fill_detected_v19_34_15"
    assert payload["symbol"] == "UPS"
    assert payload["kind"] == "warning"
    md = payload["metadata"]
    assert md["trade_id"] == "TID-1"
    assert md["ib_qty_before"] == 0.0
    assert md["ib_qty_after"] == 100.0
    assert md["delta"] == 100.0


@pytest.mark.asyncio
async def test_poll_back_no_event_when_clean_rejection_v19_34_15a():
    """Pre_qty=0, IB position never changes → no event emitted."""
    from services.trade_execution import _poll_ib_for_silent_fill_v19_34_15a

    trade = SimpleNamespace(
        id="TID-2",
        symbol="FDX",
        shares=50,
        direction=SimpleNamespace(value="long"),
    )

    pushed = {"positions": [{"symbol": "FDX", "position": 0}]}
    emitted = []

    async def fake_emit(payload):
        emitted.append(payload)

    with patch("routers.ib._pushed_ib_data", new=pushed):
        with patch("services.sentcom_service.emit_stream_event", new=fake_emit):
            await _poll_ib_for_silent_fill_v19_34_15a(
                trade=trade,
                pre_qty=0.0,
                rejected_error="size_too_small",
                poll_interval_s=0.1,
                total_duration_s=0.5,
            )
    assert emitted == [], (
        "v19.34.15a regression: clean rejection (no IB position change) "
        f"must NOT emit an event. emitted={emitted}"
    )


@pytest.mark.asyncio
async def test_poll_back_handles_missing_pushed_data_v19_34_15a():
    """If `_pushed_ib_data` returns no positions for the symbol, the
    helper must NOT crash and must NOT emit a false-positive."""
    from services.trade_execution import _poll_ib_for_silent_fill_v19_34_15a

    trade = SimpleNamespace(
        id="TID-3",
        symbol="VVNT",
        shares=10,
        direction=SimpleNamespace(value="short"),
    )

    pushed = {"positions": []}  # empty
    emitted = []

    async def fake_emit(payload):
        emitted.append(payload)

    with patch("routers.ib._pushed_ib_data", new=pushed):
        with patch("services.sentcom_service.emit_stream_event", new=fake_emit):
            # Should complete without raising, no events.
            await _poll_ib_for_silent_fill_v19_34_15a(
                trade=trade,
                pre_qty=0.0,
                rejected_error="no_data",
                poll_interval_s=0.1,
                total_duration_s=0.3,
            )
    assert emitted == []
