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


if __name__ == "__main__":
    unittest.main()
