"""
Regression test for the GAP-5 outcome-label normalization fix (2026-06-10).

The bug: position_manager -> learning_loop_service.record_trade_outcome passes
"won"/"lost"/"breakeven" straight into ConfidenceGate.record_trade_outcome,
while gate_calibrator.calibrate() only counts "win"/"loss". The dominant feed
was bucketed as scratches, deflating every score bucket's win-rate and pushing
the auto-calibrated thresholds ABOVE the static defaults.

This test verifies the gate now canonicalizes outcome -> {win, loss, scratch}
regardless of caller vocabulary before persisting to confidence_gate_log.
"""
import asyncio
import pytest

from services.ai_modules.confidence_gate import ConfidenceGate


class _FakeCollection:
    """Minimal stand-in capturing the $set payload of find_one_and_update."""

    def __init__(self):
        self.last_set = None

    def find_one_and_update(self, query, update, sort=None):
        self.last_set = update["$set"]
        # Return a truthy "matched" doc so record_trade_outcome reports success.
        return {"decision": "GO", **update["$set"]}


class _FakeDB:
    def __init__(self):
        self._col = _FakeCollection()

    def __getitem__(self, name):
        assert name == "confidence_gate_log"
        return self._col


def _record(db, outcome):
    gate = ConfidenceGate.__new__(ConfidenceGate)  # bypass heavy __init__
    gate._db = db
    ok = asyncio.run(
        gate.record_trade_outcome("AAPL", "breakout", outcome=outcome, pnl=12.3)
    )
    assert ok is True
    return db._col.last_set["trade_outcome"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("won", "win"),
        ("win", "win"),
        ("WON", "win"),
        ("lost", "loss"),
        ("loss", "loss"),
        ("Lose", "loss"),
        ("breakeven", "scratch"),
        ("scratch", "scratch"),
        ("be", "scratch"),
        ("", "scratch"),
        (None, "scratch"),
    ],
)
def test_outcome_canonicalized(raw, expected):
    db = _FakeDB()
    assert _record(db, raw) == expected
