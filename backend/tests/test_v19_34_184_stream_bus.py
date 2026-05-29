"""
v19.34.184 — Mission Control stream-bus unit tests (pure logic, no FastAPI).

Covers lane classification (the part most likely to drift), severity mapping,
the scanner firehose handling (aggregate vs raw), and per-connection filtering
at flush.
"""
import asyncio
from services.stream_bus import (
    classify_lane, severity_of, StreamBus, ALL_LANES, ALL_SEVERITIES,
)


# ── lane classification ──────────────────────────────────────────────
def test_scanner_lane():
    assert classify_lane("scanner_skip", "thought", "enhanced_scanner") == "scanner"
    assert classify_lane("scanner_trigger", "thought", None) == "scanner"
    assert classify_lane(None, "thought", "enhanced_scanner") == "scanner"


def test_gates_lane():
    for a in ("rejection_rr_below_min", "rejection_max_open_positions",
              "rejection_setup_grade_f_block", "evaluating_setup",
              "eod_no_new_entries_hard"):
        assert classify_lane(a, "rejection", None) == "gates", a
    assert classify_lane(None, "evaluation", None) == "gates"


def test_v183_guard_events_land_in_gates():
    assert classify_lane("wrong_side_stop_recomputed", "warning", "opportunity_evaluator") == "gates"
    assert classify_lane("position_stop_capped", "info", "opportunity_evaluator") == "gates"


def test_execution_lane():
    assert classify_lane("trade_filled", "fill", None) == "execution"
    assert classify_lane("bracket_attach_blocked", "alarm", None) == "execution"
    assert classify_lane("order_submitted", "info", None) == "execution"


def test_position_lane():
    assert classify_lane("wrong_direction_phantom_swept", "warning", "position_manager") == "position"
    assert classify_lane("stop_to_breakeven", "info", None) == "position"
    assert classify_lane(None, "info", "position_manager") == "position"


def test_reconciler_lane_wins_over_position_for_oca_sweep():
    # OCA-close sweep must be reconciler, not position (generic "swept")
    assert classify_lane("phantom_v19_31_oca_closed_swept", "info", "position_reconciler") == "reconciler"
    assert classify_lane("auto_orphan_reconcile", "info", None) == "reconciler"
    assert classify_lane("state_drift_detected_v19_34_10", "warning", None) == "reconciler"


def test_system_fallback():
    assert classify_lane("safety_block", "alert", None) == "system"
    assert classify_lane("totally_unknown_event", "thought", None) == "system"


# ── severity ─────────────────────────────────────────────────────────
def test_severity():
    assert severity_of("alarm", "eod_flatten_failed") == "alarm"
    assert severity_of("info", "safety_block") == "alarm"
    assert severity_of("rejection", "rejection_rr_below_min") == "warn"
    assert severity_of("fill", "trade_filled") == "success"
    assert severity_of("thought", "scanner_trigger") == "success"
    assert severity_of("info", "evaluating_setup") == "info"


# ── scanner firehose handling ────────────────────────────────────────
def _scan_skip():
    return {"action_type": "scanner_skip", "kind": "thought",
            "metadata": {"source": "enhanced_scanner", "kind": "skip"},
            "text": "skip", "timestamp": "t"}


def _scan_trigger():
    return {"action_type": "scanner_trigger", "kind": "thought",
            "metadata": {"source": "enhanced_scanner", "kind": "trigger"},
            "text": "trigger", "symbol": "DIA", "timestamp": "t"}


def test_skip_not_buffered_without_raw_subscriber_but_counted():
    bus = StreamBus()
    # no connections at all → still counts for the pulse, never buffers
    bus.publish(_scan_skip())
    assert bus._scan_window["skip"] == 1
    assert len(bus._buffer) == 0


def test_trigger_counted_but_not_buffered_without_connection():
    bus = StreamBus()
    bus.publish(_scan_trigger())
    assert bus._scan_window["trigger"] == 1
    assert len(bus._buffer) == 0  # no connections → nothing buffered


def test_skip_buffered_only_when_raw_subscriber_present():
    bus = StreamBus()

    class _FakeWS:
        async def send_json(self, m):
            pass

    conn = asyncio.run(bus.register(_FakeWS()))
    bus.update_sub(conn, mode="raw")
    bus.publish(_scan_skip())
    assert len(bus._buffer) == 1
    assert bus._buffer[0]["scan_kind"] == "skip"


def test_aggregate_subscriber_does_not_buffer_skips():
    bus = StreamBus()

    class _FakeWS:
        async def send_json(self, m):
            pass

    conn = asyncio.run(bus.register(_FakeWS()))  # default aggregate
    bus.publish(_scan_skip())
    assert len(bus._buffer) == 0          # not buffered
    assert bus._scan_window["skip"] == 1  # still counted for the pulse


# ── per-connection filter at flush ───────────────────────────────────
def test_flush_filters_by_lane_and_severity():
    bus = StreamBus()
    sent = []

    class _FakeWS:
        async def send_json(self, m):
            sent.append(m)

    conn = asyncio.run(bus.register(_FakeWS()))
    bus.update_sub(conn, lanes=["gates"], severities=list(ALL_SEVERITIES))
    # one gates event (kept), one execution event (filtered out)
    bus.publish({"action_type": "rejection_rr_below_min", "kind": "rejection",
                 "metadata": {}, "text": "rr too low", "symbol": "X", "timestamp": "t"})
    bus.publish({"action_type": "trade_filled", "kind": "fill",
                 "metadata": {}, "text": "filled", "symbol": "Y", "timestamp": "t"})
    asyncio.run(bus._flush_once())
    assert len(sent) == 1
    evs = sent[0]["events"]
    assert len(evs) == 1 and evs[0]["lane"] == "gates"


def test_scan_pulse_summary():
    bus = StreamBus()
    pulses = []

    class _FakeWS:
        async def send_json(self, m):
            pulses.append(m)

    conn = asyncio.run(bus.register(_FakeWS()))
    for _ in range(5):
        bus.publish(_scan_skip())
    bus.publish(_scan_trigger())
    asyncio.run(bus._emit_scan_pulse())
    assert len(pulses) == 1
    p = pulses[0]
    assert p["type"] == "scan_pulse" and p["skips"] == 5 and p["triggers"] == 1
    # window resets after pulse
    assert sum(bus._scan_window.values()) == 0
