"""
Deferred tape-confirmation (JIT Level-2) — 2026-06-26.

Verifies:
  • `_tape_verdict` pure logic (L2 adverse/confirm, no-L2 adverse/confirm/neutral,
    long & short symmetry).
  • `_apply_tape_gate` DEFAULT (both flags OFF) == LEGACY behavior exactly
    (eligible iff passes_else AND tape_confirmation when tape is required;
    == passes_else when tape not required).
  • DEFERRED ON: neutral-no-L2 scalp/intraday alert is held `tape_pending`
    (NOT eligible, NOT recorded as a drop); adverse → not eligible; L2 confirm
    → eligible.
  • NON-ADVERSE gate (deferred OFF): neutral passes, adverse blocks — no pending.

Uses a bare instance (ES.__new__) with the handful of attrs the gate reads, so
no DB / IB / symbol-universe import is needed.
"""
from types import SimpleNamespace

from services.enhanced_scanner import EnhancedBackgroundScanner as ES, TapeSignal


# ── helpers ─────────────────────────────────────────────────────────

def _alert(direction="long", style="intraday", tape_confirmation=False):
    return SimpleNamespace(
        symbol="TEST", setup_type="vwap_continuation", direction=direction,
        trade_style=style, tape_confirmation=tape_confirmation,
        tape_pending=False, tape_pending_since=None, tape_verdict="",
        tape_l2_confirmed=False, auto_execute_eligible=False,
        priority=SimpleNamespace(value="high"), tqs_score=70.0, status="active",
    )


def _tape(l2_available=False, l2_imbalance=0.0, tape_score=0.0):
    return SimpleNamespace(
        l2_available=l2_available, l2_imbalance=l2_imbalance, tape_score=tape_score)


def _bare_scanner(deferred=False, nonadverse=False, mode="router"):
    s = ES.__new__(ES)
    s._tape_confirm_scalp_intraday_only = False
    s._tape_confirm_deferred = deferred
    s._tape_nonadverse_gate = nonadverse
    s._tape_confirm_mode = mode
    s._tape_adverse_score = 0.3
    s._tape_adverse_l2_imb = 0.25
    s._tape_pending = {}
    s._tape_confirm_stats = {"pending_total": 0}
    return s


# ── _tape_verdict pure logic ────────────────────────────────────────

def test_verdict_l2_confirm_long_neutral_depth():
    assert ES._tape_verdict("long", True, 0.0, 0.0, 0.3, 0.25) == "confirm"
    assert ES._tape_verdict("long", True, 0.5, 0.0, 0.3, 0.25) == "confirm"


def test_verdict_l2_adverse_long():
    # strong asks against a long
    assert ES._tape_verdict("long", True, -0.4, 0.0, 0.3, 0.25) == "adverse"


def test_verdict_l2_adverse_short():
    # strong bids against a short
    assert ES._tape_verdict("short", True, 0.4, 0.0, 0.3, 0.25) == "adverse"
    assert ES._tape_verdict("short", True, -0.4, 0.0, 0.3, 0.25) == "confirm"


def test_verdict_no_l2_neutral_is_deferrable():
    # no depth, flat tape → neither for nor against
    assert ES._tape_verdict("long", False, 0.0, 0.0, 0.3, 0.25) == "neutral_no_l2"
    assert ES._tape_verdict("short", False, 0.0, 0.0, 0.3, 0.25) == "neutral_no_l2"


def test_verdict_no_l2_adverse_and_confirm_long():
    assert ES._tape_verdict("long", False, 0.0, -0.5, 0.3, 0.25) == "adverse"
    assert ES._tape_verdict("long", False, 0.0, 0.3, 0.3, 0.25) == "confirm"


def test_verdict_no_l2_adverse_and_confirm_short():
    assert ES._tape_verdict("short", False, 0.0, 0.5, 0.3, 0.25) == "adverse"
    assert ES._tape_verdict("short", False, 0.0, -0.3, 0.3, 0.25) == "confirm"


# ── _apply_tape_gate — LEGACY (both flags OFF) ──────────────────────

def test_gate_legacy_requires_tape_confirmation():
    s = _bare_scanner(deferred=False, nonadverse=False)
    # tape required (intraday) + no tape_confirmation → NOT eligible even if passes_else
    a = _alert(style="intraday", tape_confirmation=False)
    assert s._apply_tape_gate(a, _tape(), passes_else=True) is False
    assert a.auto_execute_eligible is False
    # with tape_confirmation True → eligible
    a2 = _alert(style="intraday", tape_confirmation=True)
    assert s._apply_tape_gate(a2, _tape(), passes_else=True) is True
    assert a2.auto_execute_eligible is True
    # passes_else False → never eligible
    a3 = _alert(style="intraday", tape_confirmation=True)
    assert s._apply_tape_gate(a3, _tape(), passes_else=False) is False


def test_gate_legacy_not_required_for_swing():
    s = _bare_scanner(deferred=False, nonadverse=False)
    s._tape_confirm_scalp_intraday_only = True  # swing no longer requires tape
    a = _alert(style="swing", tape_confirmation=False)
    assert s._apply_tape_gate(a, _tape(), passes_else=True) is True
    assert a.auto_execute_eligible is True


def test_gate_legacy_no_pending_registered():
    s = _bare_scanner(deferred=False, nonadverse=False)
    a = _alert(style="intraday", tape_confirmation=False)
    s._apply_tape_gate(a, _tape(), passes_else=True)
    assert s._tape_pending == {}
    assert a.tape_pending is False


# ── _apply_tape_gate — DEFERRED ON ──────────────────────────────────

def test_gate_deferred_neutral_holds_pending():
    s = _bare_scanner(deferred=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(l2_available=False, tape_score=0.0), passes_else=True)
    assert fired is False
    assert a.auto_execute_eligible is False
    assert a.tape_pending is True
    assert len(s._tape_pending) == 1
    assert a.tape_verdict == "neutral_no_l2"


def test_gate_deferred_adverse_rejects_no_pending():
    s = _bare_scanner(deferred=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(l2_available=True, l2_imbalance=-0.5), passes_else=True)
    assert fired is False
    assert a.auto_execute_eligible is False
    assert a.tape_pending is False
    assert s._tape_pending == {}
    assert a.tape_verdict == "adverse"


def test_gate_deferred_l2_confirm_fires_now():
    s = _bare_scanner(deferred=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(l2_available=True, l2_imbalance=0.3), passes_else=True)
    assert fired is True
    assert a.auto_execute_eligible is True
    assert a.tape_l2_confirmed is True
    assert s._tape_pending == {}


def test_gate_deferred_passes_else_false_no_pending():
    s = _bare_scanner(deferred=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(), passes_else=False)
    assert fired is False
    assert s._tape_pending == {}  # don't hold L2 slots for non-qualifying alerts


# ── _apply_tape_gate — NON-ADVERSE gate (deferred OFF) ──────────────

def test_gate_nonadverse_neutral_passes_no_pending():
    s = _bare_scanner(deferred=False, nonadverse=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(l2_available=False, tape_score=0.0), passes_else=True)
    assert fired is True
    assert a.auto_execute_eligible is True
    assert s._tape_pending == {}  # not deferred → no JIT hold


def test_gate_nonadverse_adverse_blocks():
    s = _bare_scanner(deferred=False, nonadverse=True)
    a = _alert(style="intraday")
    fired = s._apply_tape_gate(a, _tape(l2_available=False, tape_score=-0.5), passes_else=True)
    assert fired is False
    assert a.auto_execute_eligible is False
