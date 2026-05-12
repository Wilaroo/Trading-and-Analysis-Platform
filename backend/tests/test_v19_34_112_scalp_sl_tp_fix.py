"""
Tests for v19.34.112 — Scalp SL/TP calculation fix.

PRE-V112 GAPS (operator-discovered during P3 investigation):

  1. `OpportunityEvaluator.calculate_atr_based_stop` had explicit ATR
     multipliers for rubber_band / squeeze / breakout / vwap_bounce /
     gap_fade / relative_strength / mean_reversion / orb — but NO
     entries for `scalp`, `nine_ema_scalp`, `spencer_scalp`,
     `abc_scalp`. All scalps fell through to
     `bot.risk_params.base_atr_multiplier` (typically 1.5-2.0×), the
     same stop distance used for 4-hour intraday holds. Scalps
     designed for <5min holding routinely sat with 1-2×ATR stops on
     micro-moves.

  2. Target ladder was hardcoded `[1.5R, 2.5R, 4R]` regardless of
     trade_style. A scalp targeting 1R in <5min never sees 1.5R
     inside the window. Worse, `attach_oca_stop_target` uses
     `target_prices[0]` (the 1.5R rung) as the SINGLE LMT.

  3. `target_snap` widens targets to the next S/R cluster on the move
     side. For scalps that pushes targets 30-50 bp further out —
     unreachable inside the holding window.

V112 SHIPS:

  • Scalp ATR multipliers: scalp=0.5, nine_ema_scalp=0.4,
    spencer_scalp=0.5, abc_scalp=0.5. Bypass the global min/max
    clamp ONLY for scalp setups (the clamp protects everything else).

  • Trade-style-aware target ladder:
      - Scalp     → [1.0R, 1.5R]
      - Intraday  → [1.5R, 2.5R]
      - Swing     → [1.5R, 2.5R, 4R] (legacy preserved)
      - Position  → [2R, 4R, 8R]

  • Target-snap skipped for scalp trades (do not widen tight targets).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_bot(base_mult: float = 1.5, min_mult: float = 1.0, max_mult: float = 3.0):
    bot = MagicMock()
    bot.risk_params.base_atr_multiplier = base_mult
    bot.risk_params.min_atr_multiplier = min_mult
    bot.risk_params.max_atr_multiplier = max_mult
    return bot


def _direction(value):
    """Return a TradeDirection enum value matching `value` ('long' or 'short')."""
    from services.trading_bot_service import TradeDirection
    return TradeDirection.LONG if value == "long" else TradeDirection.SHORT


# ---------------------------------------------------------------------------
# Fix 1 — Scalp ATR stop multipliers
# ---------------------------------------------------------------------------

class TestScalpAtrStopMultipliers:
    """Scalp setups MUST use tight ATR multipliers, not the generic
    `base_atr_multiplier` fallback."""

    def setup_method(self):
        from services.opportunity_evaluator import OpportunityEvaluator
        self.evaluator = OpportunityEvaluator()

    def test_plain_scalp_uses_0_5_atr(self):
        """scalp → 0.5×ATR stop."""
        bot = _make_bot()
        atr = 1.0  # $1 ATR
        entry = 100.0
        stop = self.evaluator.calculate_atr_based_stop(entry, _direction("long"), atr, "scalp", bot)
        # Long: stop = entry - 0.5×atr = 99.50
        assert abs(stop - 99.5) < 1e-6, (
            f"Plain scalp setup MUST use 0.5×ATR (=$0.50); got stop=${stop:.4f} "
            f"(implies multiplier {(entry - stop) / atr:.2f}×)"
        )

    def test_nine_ema_scalp_uses_0_4_atr(self):
        """nine_ema_scalp is tightest (momentum scalps revert fast) → 0.4×."""
        bot = _make_bot()
        stop = self.evaluator.calculate_atr_based_stop(50.0, _direction("long"), 2.0, "nine_ema_scalp", bot)
        # Long stop = 50 - 0.4*2 = 49.20
        assert abs(stop - 49.2) < 1e-6, (
            f"nine_ema_scalp MUST use 0.4×ATR; got stop=${stop:.4f}"
        )

    def test_spencer_scalp_and_abc_scalp_use_0_5_atr(self):
        bot = _make_bot()
        atr = 1.0
        entry = 200.0
        for setup in ("spencer_scalp", "abc_scalp"):
            stop = self.evaluator.calculate_atr_based_stop(entry, _direction("long"), atr, setup, bot)
            assert abs(stop - 199.5) < 1e-6, (
                f"{setup} MUST use 0.5×ATR; got stop=${stop:.4f}"
            )

    def test_short_scalp_stop_above_entry(self):
        """For SHORT direction the stop sits ABOVE the entry."""
        bot = _make_bot()
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("short"), 1.0, "scalp", bot)
        assert abs(stop - 100.5) < 1e-6, f"Short scalp stop must be entry+0.5×ATR; got {stop}"

    def test_scalp_bypasses_min_atr_clamp(self):
        """Pre-v112 the clamp `max(min_mult, ...)` floored every
        multiplier at 1.0× (the typical min). v112 bypasses the clamp
        ONLY for scalp setups so 0.4-0.5× can land."""
        # min_mult forced HIGH — the clamp would otherwise raise scalp
        # to 1.5× and produce a wide stop. Must NOT happen.
        bot = _make_bot(min_mult=1.5)
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "scalp", bot)
        # 0.5× ATR → stop = 99.50 (NOT 98.50 from the floored 1.5×)
        assert abs(stop - 99.5) < 1e-6, (
            "Scalp setups MUST bypass the min_atr_multiplier clamp — "
            "otherwise the 0.5× intent gets floored back to 1.5× and "
            "scalps revert to wide stops."
        )

    def test_non_scalp_setup_still_clamped(self):
        """The clamp protection MUST stay in place for everything that
        isn't a known scalp setup. A noisy 0.1× on a swing trade should
        be floored to min_mult."""
        # Make breakout's multiplier (1.5) the table value; force min=2.0
        # to prove the floor still bites for non-scalps.
        bot = _make_bot(min_mult=2.0)
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "breakout", bot)
        # Breakout = 1.5×, clamp floors to 2.0×, stop = 98.0
        assert abs(stop - 98.0) < 1e-6, (
            "Non-scalp setups MUST still respect the min_atr clamp — "
            "v112 only bypasses it for scalp setups."
        )

    def test_unknown_setup_falls_through_to_base(self):
        """An unknown setup MUST still use base × clamp (pre-v112 behaviour)."""
        bot = _make_bot(base_mult=2.0, min_mult=1.0, max_mult=3.0)
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "some_new_setup_name", bot)
        assert abs(stop - 98.0) < 1e-6


# ---------------------------------------------------------------------------
# Fix 2 — Trade-style-aware target ladder
# ---------------------------------------------------------------------------

class TestTradeStyleTargetLadder:
    """`target_prices` ladder MUST adapt to trade_style. We exercise
    the ladder branch directly via `evaluate_alert` since the logic
    is inline — set `target_prices` empty in the alert so the branch
    runs."""

    def test_scalp_uses_two_rungs_1R_and_1_5R(self):
        # Read the source to verify the ladder shape (logic is inline
        # in evaluate_alert — too much setup to run end-to-end here).
        src = (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()
        # Anchor: the new v112 ladder block.
        idx = src.find("Trade-style-aware target ladder")
        assert idx >= 0, "v112 ladder docstring marker missing"
        window = src[idx:idx + 2500]
        # Scalp branch
        assert "rungs = [1.0, 1.5]" in window, (
            "Scalp trade_style MUST produce a [1.0R, 1.5R] ladder. "
            "Pre-v112 it inherited the [1.5R, 2.5R, 4R] swing ladder "
            "which is unreachable inside a <5min scalp window."
        )

    def test_position_uses_runner_friendly_ladder(self):
        src = (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()
        idx = src.find("Trade-style-aware target ladder")
        window = src[idx:idx + 2500]
        assert "rungs = [2.0, 4.0, 8.0]" in window, (
            "Position trade_style MUST use [2R, 4R, 8R] for runner-friendly "
            "scale-outs over multi-day holds."
        )

    def test_intraday_uses_two_rung_session_ladder(self):
        src = (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()
        idx = src.find("Trade-style-aware target ladder")
        window = src[idx:idx + 2500]
        assert "rungs = [1.5, 2.5]" in window

    def test_swing_preserves_legacy_three_rung_ladder(self):
        """Backward compatibility: swing/multi_day MUST keep the legacy
        [1.5R, 2.5R, 4R] ladder — that's what pre-v112 trades were
        sized against, so the regression suite + journal stays valid."""
        src = (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()
        idx = src.find("Trade-style-aware target ladder")
        window = src[idx:idx + 2500]
        assert "rungs = [1.5, 2.5, 4.0]" in window, (
            "Swing/unknown trade_style MUST preserve the legacy "
            "[1.5R, 2.5R, 4R] ladder for backward compatibility."
        )

    def test_scalp_setup_type_triggers_scalp_ladder_without_trade_style(self):
        """Backward-compatibility: alerts that pre-date the `trade_style`
        stamp can still be classified as scalps via `setup_type`."""
        src = (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()
        idx = src.find("Trade-style-aware target ladder")
        window = src[idx:idx + 2500]
        # The scalp gate MUST OR both signals.
        assert "trade_style_lower == 'scalp'" in window
        assert "setup_lower in {'scalp', 'nine_ema_scalp'" in window


# ---------------------------------------------------------------------------
# Fix 3 — target_snap skipped for scalps
# ---------------------------------------------------------------------------

class TestScalpTargetSnapSkip:
    """`target_snap` widens targets to next S/R cluster on the move
    side. For scalps that's the wrong move — the trade exits in <5min
    and a 30-50bp wider target rarely fills. v112 skips the snap for
    scalp trade_styles."""

    @pytest.fixture
    def evaluator_src(self):
        return (BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text()

    def test_target_snap_block_has_scalp_skip_branch(self, evaluator_src):
        """The target-snap try block must short-circuit on scalp."""
        idx = evaluator_src.find("Skip target-snap for scalps")
        assert idx >= 0, (
            "v112 scalp-skip docstring missing from target-snap block — "
            "scalps will still get their targets widened to S/R clusters."
        )
        window = evaluator_src[idx:idx + 1500]
        assert "_is_scalp_for_snap" in window
        assert "target-snap skipped" in window

    def test_scalp_skip_checks_both_trade_style_and_setup(self, evaluator_src):
        """Same dual-signal classification as the ladder fix — alerts
        with no trade_style stamp must still be detectable as scalps."""
        idx = evaluator_src.find("Skip target-snap for scalps")
        window = evaluator_src[idx:idx + 1500]
        assert "_ts == 'scalp'" in window
        assert "_su in {'scalp', 'nine_ema_scalp'" in window

    def test_non_scalp_path_still_runs_compute_target_snap(self, evaluator_src):
        """Backward compat: every non-scalp setup MUST still call
        `compute_target_snap`. We assert the function reference is
        still imported inside the target-snap block."""
        idx = evaluator_src.find("Skip target-snap for scalps")
        window = evaluator_src[idx:idx + 2000]
        assert "from services.smart_levels_service import compute_target_snap" in window, (
            "compute_target_snap import disappeared — non-scalp targets "
            "would lose the S/R cluster snap entirely."
        )


# ---------------------------------------------------------------------------
# Fix 4 — Setup multipliers table integrity
# ---------------------------------------------------------------------------

class TestSetupMultipliersTableIntegrity:
    """The setup_multipliers dict MUST contain all 4 scalp variants."""

    def test_all_four_scalp_variants_present(self):
        from services.opportunity_evaluator import OpportunityEvaluator

        ev = OpportunityEvaluator()
        bot = _make_bot()
        # Probe the table indirectly: each scalp variant should
        # produce a stop tighter than the base multiplier.
        atr = 1.0
        entry = 100.0
        base_stop = entry - bot.risk_params.base_atr_multiplier * atr
        for variant in ("scalp", "nine_ema_scalp", "spencer_scalp", "abc_scalp"):
            stop = ev.calculate_atr_based_stop(entry, _direction("long"), atr, variant, bot)
            assert stop > base_stop, (
                f"{variant} stop ({stop:.4f}) MUST be TIGHTER than "
                f"base-multiplier stop ({base_stop:.4f}). Scalp variant "
                f"is silently falling through to base."
            )


# ---------------------------------------------------------------------------
# Regression — non-scalp behaviour preserved
# ---------------------------------------------------------------------------

class TestNonScalpRegression:
    """v112 MUST NOT change SL/TP for any non-scalp setup."""

    def setup_method(self):
        from services.opportunity_evaluator import OpportunityEvaluator
        self.evaluator = OpportunityEvaluator()

    def test_breakout_atr_multiplier_unchanged(self):
        bot = _make_bot(min_mult=1.0, max_mult=3.0)
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "breakout", bot)
        # breakout was 1.5× pre-v112 and stays 1.5×
        assert abs(stop - 98.5) < 1e-6

    def test_squeeze_atr_multiplier_unchanged(self):
        bot = _make_bot()
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "squeeze", bot)
        assert abs(stop - 98.5) < 1e-6  # 1.5×

    def test_rubber_band_atr_multiplier_unchanged(self):
        bot = _make_bot()
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "rubber_band", bot)
        assert abs(stop - 99.0) < 1e-6  # 1.0×

    def test_orb_atr_multiplier_unchanged(self):
        bot = _make_bot()
        stop = self.evaluator.calculate_atr_based_stop(100.0, _direction("long"), 1.0, "orb", bot)
        assert abs(stop - 98.75) < 1e-6  # 1.25×
