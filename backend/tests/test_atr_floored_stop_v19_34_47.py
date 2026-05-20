"""v19.34.47 -- ATR-floored stop helper regression suite."""
from __future__ import annotations
import os, sys, unittest

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)


class TestAtrFlooredStop(unittest.TestCase):
    def _h(self, *args, **kwargs):
        from services.enhanced_scanner import EnhancedBackgroundScanner
        inst = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
        return inst._atr_floored_stop(*args, **kwargs)

    def test_xly_long_widened(self):
        # XLY: entry 115.10, raw 115.07, ATR 2.30, 0.5x → 113.95
        self.assertEqual(self._h(115.10, 115.07, 2.30, "long", 0.5), 113.95)

    def test_mu_short_widened(self):
        # MU: entry 722.64, raw 722.66, ATR 14.4528, 0.5x → 729.87
        self.assertAlmostEqual(self._h(722.64, 722.66, 14.4528, "short", 0.5), 729.87, places=2)

    def test_anchor_preserved_when_safe(self):
        self.assertEqual(self._h(115.10, 112.00, 2.30, "long", 0.5), 112.00)
        self.assertEqual(self._h(722.64, 740.00, 14.4528, "short", 0.5), 740.00)

    def test_no_atr_fail_open(self):
        self.assertEqual(self._h(115.10, 115.07, None, "long"), 115.07)
        self.assertEqual(self._h(115.10, 115.07, 0.0, "long"), 115.07)

    def test_custom_mult(self):
        # 1.0x ATR floor → entry-2.30 = 112.80
        self.assertEqual(self._h(115.10, 115.07, 2.30, "long", 1.0), 112.80)

    def test_zero_entry_returns_raw(self):
        self.assertEqual(self._h(0, 100.0, 2.0, "long"), 100.0)


class TestV19_34_48_TradeSetupCoverage(unittest.TestCase):
    """v19.34.48 swept 6 actual-trade setups. Verify each uses helper."""
    def _src(self):
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "services" / "enhanced_scanner.py"
        return p.read_text()

    def _assert_setup_uses_helper(self, setup):
        src = self._src()
        i = src.index(f'setup_type="{setup}"')
        try:
            j = src.index("setup_type=", i + 1)
        except ValueError:
            j = len(src)
        self.assertIn("_atr_floored_stop", src[i:j],
                      f"{setup} missing helper call")

    def test_hitchhiker_uses_helper(self):       self._assert_setup_uses_helper("hitchhiker")
    def test_gap_give_go_uses_helper(self):      self._assert_setup_uses_helper("gap_give_go")
    def test_backside_uses_helper(self):         self._assert_setup_uses_helper("backside")
    def test_off_sides_short_uses_helper(self):  self._assert_setup_uses_helper("off_sides_short")
    def test_big_dog_uses_helper(self):          self._assert_setup_uses_helper("big_dog")
    def test_9_ema_scalp_uses_helper(self):      self._assert_setup_uses_helper("9_ema_scalp")

    def test_no_hardcoded_stops_in_trade_setups(self):
        import re
        src = self._src()
        pat = re.compile(r"stop_loss=round\(snapshot\.\w+ [+-] 0\.0[12], 2\)")
        for trade in ("hitchhiker","gap_give_go","backside",
                      "off_sides_short","big_dog","9_ema_scalp"):
            i = src.index(f'setup_type="{trade}"')
            try: j = src.index("setup_type=", i + 1)
            except ValueError: j = len(src)
            self.assertFalse(pat.search(src[i:j]),
                             f"{trade} regressed to hardcoded stop")


if __name__ == "__main__":
    unittest.main()
