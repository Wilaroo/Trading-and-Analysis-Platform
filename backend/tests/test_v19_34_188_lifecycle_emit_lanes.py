"""
v19.34.188 — Mission Control lifecycle-emit lane contract.

Locks the lane/severity classification for the new lifecycle events emitted by
this patch so a future stream_bus refactor can't silently re-route them:
  • order_submitted / partial_fill  → execution lane
  • trailing_stop_moved             → position lane (stop_to_breakeven covered in v184)

These events are fired fire-and-forget from stop_manager / trade_execution /
trade_executor_service; the only thing worth unit-testing (no IB/loop) is that
the bus puts them in the operator's expected column.
"""
from services.stream_bus import classify_lane, severity_of


def test_partial_fill_lands_in_execution():
    assert classify_lane("partial_fill", "info", "trade_executor_service") == "execution"


def test_order_submitted_lands_in_execution():
    assert classify_lane("order_submitted", "info", "trade_executor_service") == "execution"


def test_trailing_stop_moved_lands_in_position():
    assert classify_lane("trailing_stop_moved", "info", "position_manager") == "position"


def test_stop_to_breakeven_lands_in_position_and_is_success():
    assert classify_lane("stop_to_breakeven", "info", "position_manager") == "position"
    assert severity_of("info", "stop_to_breakeven") == "success"
