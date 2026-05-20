"""v19.34.47 -- ATR-floored stop helper regression suite.

Source: `enhanced_scanner.EnhancedScanner._atr_floored_stop`.

The vwap_fade audit (5/2026-02-XX) showed 50/64 = 78% of
`pre_exec_guardrail_veto` drops came from `_check_vwap_fade` emitting
`low_of_day - 0.02` stops — a flat $0.02 offset that collapses to
noise distance whenever current price sits near LoD/HoD. The helper
keeps the LoD/HoD structural anchor where it has room to breathe and
widens to `min_atr_mult × ATR` otherwise.
"""
from __future__ import annotations
import os
import sys
import unittest
from unittest.mock import MagicMock

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestAtrFlooredStop(unittest.TestCase):
    """Smoke-test the helper without booting the full scanner."""

    def _helper(self, *args, **kwargs):
        """Bind the helper as an unbound method so we don't have to
        spin up the (heavy) EnhancedScanner constructor."""
        from services.enhanced_scanner import EnhancedBackgroundScanner
        # Synthesize an instance shell — the helper only needs `self`.
        instance = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
        return instance._atr_floored_stop(*args, **kwargs)

    def test_xly_long_widened_from_lod(self):
        # XLY-like sample: entry $115.10, raw_stop (LoD-0.02) = $115.07,
        # ATR = $2.30. floor_distance = 0.5×$2.30 = $1.15. Helper picks
        # the LOWER of $115.07 and ($115.10 - $1.15)=$113.95 → $113.95.
        stop = self._helper(115.10, 115.07, 2.30, "long", 0.5)
        self.assertEqual(stop, 113.95)

    def test_mu_short_widened_from_hod(self):
        # MU-like: entry $722.64, raw_stop (HoD+0.02) = $722.66,
        # ATR = $14.45. floor_distance = 0.5×$14.45 = $7.225. Helper picks
        # the HIGHER of $722.66 and ($722.64 + $7.225)=$729.865 → $729.87.
        stop = self._helper(722.64, 722.66, 14.4528, "short", 0.5)
        self.assertAlmostEqual(stop, 729.87, places=2)

    def test_anchor_preserved_when_already_safe(self):
        # If LoD already gives a wide stop, helper must NOT tighten it.
        # entry $115.10, raw_stop $112.00 (Δ=$3.10), ATR $2.30 → floor
        # only requires Δ=$1.15. Anchor wins.
        stop = self._helper(115.10, 112.00, 2.30, "long", 0.5)
        self.assertEqual(stop, 112.00)

    def test_short_anchor_preserved_when_already_safe(self):
        stop = self._helper(722.64, 740.00, 14.4528, "short", 0.5)
        self.assertEqual(stop, 740.00)

    def test_no_atr_falls_back_to_raw(self):
        # ATR=None or 0 → helper returns raw_stop unchanged (fail-OPEN,
        # evaluator's v19.34.45 still catches the floor breach).
        self.assertEqual(self._helper(115.10, 115.07, None, "long"), 115.07)
        self.assertEqual(self._helper(115.10, 115.07, 0.0, "long"), 115.07)

    def test_custom_multiplier(self):
        # Tighten the multiplier to 1.0× ATR for setups that want more room.
        # entry $115.10, raw_stop $115.07, ATR $2.30 → floor $2.30 →
        # widened to $112.80.
        stop = self._helper(115.10, 115.07, 2.30, "long", 1.0)
        self.assertEqual(stop, 112.80)

    def test_zero_entry_returns_raw(self):
        # Defensive: entry=0 (impossible but cheap to guard).
        self.assertEqual(self._helper(0, 100.0, 2.0, "long"), 100.0)


class TestV19_34_48_TradeSetupCoverage(unittest.TestCase):
    """v19.34.48 swept 6 actual-trade setups to use _atr_floored_stop.
    Verify each LiveAlert dispatch in the scanner calls the helper.
    This is a SOURCE-SCAN regression — it doesn't run the scanner
    (heavy), just greps for the wiring."""

    def _src(self):
        import os
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "services" / "enhanced_scanner.py"
        return p.read_text()

    def test_hitchhiker_uses_helper(self):
        src = self._src()
        # Block from `setup_type="hitchhiker"` to next `setup_type=`.
        i = src.index('setup_type="hitchhiker"')
        j = src.index('setup_type=', i + 1)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_gap_give_go_uses_helper(self):
        src = self._src()
        i = src.index('setup_type="gap_give_go"')
        j = src.index('setup_type=', i + 1)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_backside_uses_helper(self):
        src = self._src()
        i = src.index('setup_type="backside"')
        j = src.index('setup_type=', i + 1)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_off_sides_short_uses_helper(self):
        src = self._src()
        i = src.index('setup_type="off_sides_short"')
        j = src.index('setup_type=', i + 1)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_big_dog_uses_helper(self):
        src = self._src()
        i = src.index('setup_type="big_dog"')
        j = src.index('setup_type=', i + 1)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_9_ema_scalp_uses_helper(self):
        src = self._src()
        i = src.index('setup_type="9_ema_scalp"')
        # 9_ema_scalp may be the last setup in the file — guard for that.
        try:
            j = src.index('setup_type=', i + 1)
        except ValueError:
            j = len(src)
        self.assertIn("_atr_floored_stop", src[i:j])

    def test_no_hardcoded_stops_in_trade_setups(self):
        """Failsafe: ensure none of the 6 trade setups regressed to
        the old `stop_loss=round(snapshot.<x> ± 0.0N, 2)` pattern."""
        import re
        src = self._src()
        pattern = re.compile(r'stop_loss=round\(snapshot\.\w+ [+-] 0\.0[12], 2\)')
        for trade in ("hitchhiker", "gap_give_go", "backside",
                      "off_sides_short", "big_dog", "9_ema_scalp"):
            i = src.index(f'setup_type="{trade}"')
            try:
                j = src.index("setup_type=", i + 1)
            except ValueError:
                j = len(src)
            self.assertFalse(
                pattern.search(src[i:j]),
                f"setup_type={trade!r} regressed to hardcoded stop",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
