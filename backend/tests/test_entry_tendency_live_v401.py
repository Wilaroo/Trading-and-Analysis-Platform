"""v401 — Entry Tendency live-derivation unit tests (DB-free).

Validates that _derive_live_execution_state extracts entry slippage / chase from
trade_outcomes.execution and that backfilled empty-execution closes are correctly
treated as no-data (not as perfect 0.0 fills).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.tqs.execution_quality import _derive_live_execution_state  # noqa: E402


def _oc(outcome, slip=None, rcap=None):
    ex = {}
    if slip is not None:
        ex["entry_slippage_percent"] = slip
    if rcap is not None:
        ex["r_capture_percent"] = rcap
    return {"outcome": outcome, "execution": ex}


def test_entry_slippage_avg_and_chase():
    outs = [_oc("won", slip=0.30), _oc("lost", slip=0.50), _oc("won", slip=0.10)]
    live = _derive_live_execution_state(outs)
    assert live["entry_sample"] == 3
    assert abs(live["avg_entry_slippage_pct"] - 0.30) < 1e-6
    assert live["tends_to_chase"] is True  # 0.30 > 0.2


def test_clean_entries_not_chasing():
    outs = [_oc("won", slip=0.05), _oc("won", slip=0.0), _oc("lost", slip=-0.10)]
    live = _derive_live_execution_state(outs)
    assert live["entry_sample"] == 3
    assert live["avg_entry_slippage_pct"] is not None
    assert live["tends_to_chase"] is False


def test_backfilled_empty_execution_is_no_data():
    # learning_reconciler writes execution={} for backfilled closes → must be
    # treated as ABSENT, not as a 0.0 perfect fill.
    outs = [{"outcome": "won", "execution": {}}, {"outcome": "lost", "execution": {}}]
    live = _derive_live_execution_state(outs)
    assert live["entry_sample"] == 0
    assert live["avg_entry_slippage_pct"] is None
    assert live["tends_to_chase"] is False


def test_zero_slippage_is_real_data():
    # A genuine perfect fill (0.0 with the key present) IS real data.
    outs = [_oc("won", slip=0.0)]
    live = _derive_live_execution_state(outs)
    assert live["entry_sample"] == 1
    assert live["avg_entry_slippage_pct"] == 0.0


if __name__ == "__main__":
    test_entry_slippage_avg_and_chase()
    test_clean_entries_not_chasing()
    test_backfilled_empty_execution_is_no_data()
    test_zero_slippage_is_real_data()
    print("PASS: all v401 entry-tendency live-derivation tests")
