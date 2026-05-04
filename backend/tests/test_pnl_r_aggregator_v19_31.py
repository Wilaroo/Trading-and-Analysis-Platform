"""
v19.31 (2026-05-04) — regression pin for the MANAGE +0.0R HUD aggregator
fix.

The bug:
  Operator's HUD showed `MANAGE +0.0R 9` while LITE alone was
  `(992.37 − 973.71) / 1.49 ≈ +12.5R` open profit. Root cause:
  `derivePipelineCounts` in `SentComV5View.jsx` summed
  `unrealized_r ?? pnl_r` across positions, but
  `sentcom_service.get_our_positions` never populated either field —
  it only sent `pnl` (raw $) and `pnl_percent` (%). Result: every
  position contributed 0 to totalR.

The fix:
  Compute realized R-multiple = `pnl / risk_amount` in
  `get_our_positions` for both bot-tracked and orphan/lazy-reconciled
  paths. Send as both `pnl_r` and `unrealized_r` so the existing
  frontend aggregator picks it up without UI changes.

These tests pin the per-position math + null-handling.
"""
from __future__ import annotations

from typing import Dict


def _calc_pnl_r(pnl: float, risk_amount: float):
    """Mirror of the math in get_our_positions — kept inline so tests
    don't import the giant sentcom_service module just to assert math."""
    return (pnl / risk_amount) if risk_amount > 0 else None


def test_pnl_r_basic_long_winner():
    """Long bought at 100, stop at 99 → risk $1/sh × 100 sh = $100 risk.
    Current 102 → pnl $200. R = 200/100 = +2.0R."""
    pnl_r = _calc_pnl_r(pnl=200.0, risk_amount=100.0)
    assert abs(pnl_r - 2.0) < 1e-9


def test_pnl_r_basic_short_winner():
    """Short at 992.37, stop at 993.86 → risk $1.49/sh × 62 = $92.38 risk.
    Current 973.71 → pnl (992.37 - 973.71) × 62 = $1156.92. R ≈ +12.52R.
    Mirrors the LITE scenario from the operator's screenshot."""
    risk = abs(992.37 - 993.86) * 62  # = 92.38
    pnl = (992.37 - 973.71) * 62      # = 1156.92
    pnl_r = _calc_pnl_r(pnl=pnl, risk_amount=risk)
    assert pnl_r is not None
    assert abs(pnl_r - 12.52) < 0.05  # within 5 cents of expected


def test_pnl_r_loser():
    """Negative pnl → negative R."""
    pnl_r = _calc_pnl_r(pnl=-50.0, risk_amount=100.0)
    assert abs(pnl_r - (-0.5)) < 1e-9


def test_pnl_r_returns_none_when_risk_amount_zero():
    """If we don't have a stop / risk_amount, pnl_r should be None
    (NOT 0 — because 0R looks like a flat trade, while None means
    we genuinely don't know)."""
    assert _calc_pnl_r(pnl=500.0, risk_amount=0.0) is None
    assert _calc_pnl_r(pnl=0.0, risk_amount=0.0) is None
    assert _calc_pnl_r(pnl=-200.0, risk_amount=0.0) is None


def test_pnl_r_handles_negative_risk_amount_defensively():
    """A bad risk_amount upstream (negative) should also resolve to None."""
    assert _calc_pnl_r(pnl=100.0, risk_amount=-50.0) is None


def test_source_pin_get_our_positions_emits_pnl_r_field():
    """Source-level pin: both bot-tracked AND IB-orphan branches in
    `sentcom_service.get_our_positions` must emit `pnl_r` and
    `unrealized_r` keys. Catches a future refactor that drops them."""
    import sys
    from pathlib import Path
    BACKEND_DIR = Path(__file__).resolve().parents[1]
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()

    # Both paths reference the helper variable + emit the field.
    assert src.count('"pnl_r"') >= 2, (
        "Both bot-tracked and IB-orphan branches should emit pnl_r"
    )
    assert src.count('"unrealized_r"') >= 2, (
        "Both bot-tracked and IB-orphan branches should emit unrealized_r"
    )
    # Pin the comment trail so the next operator finds the v19.31 fix.
    assert "v19.31 — realized R" in src or "v19.31 — same realized R" in src
