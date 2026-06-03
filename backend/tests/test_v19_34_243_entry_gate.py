"""
v19.34.243 — per-entry batch gate tests.

Validates the pure decision that halts a scan cycle's entry batch the moment the
operator pauses mid-cycle OR open+pending reaches the position cap. This is the
fix for the 2026-06-02 cap overshoot (27 vs cap 25) and the 2026-06-03
CEG-entered-while-paused incident.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.entry_gate import per_entry_gate_should_stop  # noqa: E402


# ── pause halts the batch immediately ──────────────────────────────────────
def test_paused_stops_even_under_cap():
    # 06-03 CEG case: plenty of headroom but operator paused mid-cycle.
    assert per_entry_gate_should_stop(3, 0, 25, paused=True) is True


def test_not_paused_under_cap_allows():
    assert per_entry_gate_should_stop(8, 0, 25, paused=False) is False


# ── cap counts open + pending (closes the batch-race overshoot) ────────────
def test_cap_hit_by_open_alone():
    assert per_entry_gate_should_stop(25, 0, 25, paused=False) is True


def test_cap_hit_by_open_plus_pending():
    # 24 open + 1 in-flight pending == cap 25 → must STOP (this is exactly the
    # overshoot that produced 27 when pending wasn't counted).
    assert per_entry_gate_should_stop(24, 1, 25, paused=False) is True


def test_one_below_cap_allows():
    assert per_entry_gate_should_stop(23, 1, 25, paused=False) is False


def test_over_cap_stops():
    assert per_entry_gate_should_stop(27, 0, 25, paused=False) is True


# ── fail-open on malformed inputs (never spuriously halt trading) ──────────
def test_malformed_counts_fail_open():
    assert per_entry_gate_should_stop(None, None, 25, paused=False) is False


def test_malformed_still_respects_pause():
    assert per_entry_gate_should_stop(None, None, 25, paused=True) is True
