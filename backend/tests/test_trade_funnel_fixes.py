"""Tests for Trade Funnel Fixes (Bugs 1, 2, 3, 4a)
==================================================

Covers fixes shipped in commits 9-10 of the 2026-04-30 trade-funnel
investigation:

- Bug 1: tape_score boundary inclusive (was strict `>`, now `>=`).
- Bug 2: `LiveAlert` exposes `rvol`, `gap_pct`, `atr_percent`.
- Bug 3 (3c grace period): cold-start strategies with <20 graded
  outcomes use the auto-execute floor (0.55) as their synthetic
  win_rate so they can clear the eligibility check.
- Bug 4 (4a): `_check_relative_strength` priority thresholds
  tightened — HIGH at rs >= 5.0 (was 4.0), so the detector no longer
  dominates the HIGH bucket.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

from services.enhanced_scanner import (  # noqa: E402
    LiveAlert, AlertPriority, EnhancedBackgroundScanner,
)
from services.enhanced_scanner import StrategyStats  # noqa: E402


# ──────────────────────────── Bug 1: tape_score >= 0.2 inclusive ────────────────────────────


def test_tape_confirmation_inclusive_at_long_boundary():
    """tape_score == 0.20 must now produce confirmation_for_long=True
    (previous strict-`>` killed 25 of 42 HIGH alerts on Tuesday Apr 28).
    """
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    # The new code uses `>= 0.2` and `<= -0.2`
    assert "confirmation_for_long=tape_score >= 0.2" in src
    assert "confirmation_for_short=tape_score <= -0.2" in src
    # Ensure the strict-> shape is gone
    assert "confirmation_for_long=tape_score > 0.2," not in src
    assert "confirmation_for_short=tape_score < -0.2," not in src


# ──────────────────────────── Bug 2: rvol/gap_pct/atr_percent on LiveAlert ────────────────────────────


def test_live_alert_has_snapshot_signal_fields():
    fields = LiveAlert.__dataclass_fields__
    for name in ("rvol", "gap_pct", "atr_percent"):
        assert name in fields, f"LiveAlert missing {name!r}"
        # Defaults are 0.0 (so old alerts read as 0.0 not None)
        assert fields[name].default == 0.0


def test_scanner_stamps_snapshot_signals_on_alerts():
    """Source-level guard — `alert.rvol = float(...)` etc. must be in
    the scan-symbol path so future alerts carry these signals."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    assert "alert.rvol = float(getattr(snapshot," in src
    assert "alert.gap_pct = float(getattr(snapshot," in src
    assert "alert.atr_percent = float(getattr(snapshot," in src


# ──────────────────────────── Bug 3 (3c): grace-period win_rate ────────────────────────────


def test_scanner_init_exposes_grace_period_constant():
    s = EnhancedBackgroundScanner(db=None)
    assert hasattr(s, "_win_rate_grace_min_trades")
    assert s._win_rate_grace_min_trades == 20
    # Floor still 0.55
    assert s._auto_execute_min_win_rate == 0.55


def test_grace_period_uses_floor_for_cold_start_strategies():
    """Source-level guard: the conditional that swaps in the floor
    when `stats.alerts_triggered < self._win_rate_grace_min_trades`
    must be present in the alert-stamping block."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    assert "_win_rate_grace_min_trades" in src
    assert "stats.alerts_triggered < self._win_rate_grace_min_trades" in src
    assert "alert.strategy_win_rate = self._auto_execute_min_win_rate" in src


def test_grace_period_yields_to_real_rate_after_threshold():
    """Once stats.alerts_triggered >= grace threshold, real win_rate
    takes over. Tested via the source structure (else branch)."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    # The else branch must use stats.win_rate
    grace_block = src.split("_win_rate_grace_min_trades:")[1][:400]
    assert "alert.strategy_win_rate = stats.win_rate" in grace_block


# ──────────────────────────── Bug 4 (4a): RS detector priority tightened ────────────────────────────


def test_rs_detector_high_threshold_now_5_pct():
    """abs(rs) >= 5.0 → HIGH (was 4.0). Source-level + literal check."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    rs_block_start = src.find("async def _check_relative_strength")
    rs_block = src[rs_block_start:rs_block_start + 2500]
    assert "abs_rs >= 5.0" in rs_block
    assert "abs_rs >= 4.0" in rs_block
    # The old single-line ternary should be gone
    assert "AlertPriority.HIGH if rs >= 4.0 else AlertPriority.MEDIUM" not in rs_block
    assert "AlertPriority.HIGH if abs(rs) >= 4.0 else AlertPriority.MEDIUM" not in rs_block


def test_rs_detector_three_band_priority_map():
    """The new map: 2.0-3.99 → LOW, 4.0-4.99 → MEDIUM, ≥5.0 → HIGH."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    rs_block_start = src.find("async def _check_relative_strength")
    rs_block = src[rs_block_start:rs_block_start + 2500]
    # All three priorities must appear in the RS detector
    for prio in ("AlertPriority.HIGH", "AlertPriority.MEDIUM", "AlertPriority.LOW"):
        assert prio in rs_block, f"RS detector missing {prio}"


def test_rs_firing_condition_unchanged():
    """Detector still fires only when abs(rs) >= 2.0 AND rvol >= 1.0 —
    we tightened the *priority*, not the firing condition."""
    from pathlib import Path
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    rs_block_start = src.find("async def _check_relative_strength")
    rs_block = src[rs_block_start:rs_block_start + 1000]
    assert "abs(rs) < 2.0 or snapshot.rvol < 1.0" in rs_block
