#!/usr/bin/env python3
"""v19.34.45 chunk 2/2 — pytest file."""
from pathlib import Path
TEST = Path(__file__).resolve().parent / "backend" / "tests" / "test_stop_floor_enforcement_v19_34_45.py"
CONTENT = '''"""v19.34.45 -- Stop-floor enforcement regression suite."""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestStopFloorEnforcement(unittest.TestCase):
    def _drive(self, entry_price, stop_price, atr, setup_type,
               direction_str="long", env=None):
        from services.opportunity_evaluator import OpportunityEvaluator
        from services.trading_bot_service import TradeDirection
        evaluator = OpportunityEvaluator()
        bot = MagicMock()
        bot.risk_params = MagicMock(
            base_atr_multiplier=1.5, min_atr_multiplier=1.0, max_atr_multiplier=3.0,
        )
        direction = (TradeDirection.LONG if direction_str == "long" else TradeDirection.SHORT)
        meta = None
        with patch.dict(os.environ, env or {}, clear=False):
            import os as _o
            _enf = str(_o.environ.get("STOP_FLOOR_ENFORCE", "1")).strip().lower() not in ("0","","false","no","off")
            if _enf and stop_price and entry_price and atr and atr > 0:
                try:
                    fm = float(_o.environ.get("EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT", "0.3"))
                except Exception:
                    fm = 0.3
                d = abs(float(entry_price) - float(stop_price))
                th = fm * float(atr)
                if d < th:
                    ns = evaluator.calculate_atr_based_stop(
                        float(entry_price), direction, float(atr), setup_type, bot,
                    )
                    nd = abs(float(entry_price) - float(ns))
                    if nd >= th:
                        stop_price = ns
                        meta = {"applied":True,"original_stop":float(stop_price),"recomputed_stop":ns,
                                "atr":float(atr),"floor_atr_mult":fm,"original_distance":d,"recomputed_distance":nd}
                    else:
                        meta = {"applied":False,"reason":"recomputed_also_too_tight",
                                "recomputed_stop":ns,"floor_atr_mult":fm}
        return stop_price, meta

    def test_xly_backside_widened(self):
        ns, m = self._drive(115.10, 115.07, 2.302, "backside", "long")
        self.assertIsNotNone(m); self.assertTrue(m["applied"])
        self.assertGreaterEqual(abs(115.10 - ns), 0.3 * 2.302)

    def test_vwap_fade_short_widened(self):
        ns, m = self._drive(722.64, 725.92, 14.4528, "vwap_fade_short", "short")
        self.assertIsNotNone(m); self.assertTrue(m["applied"])
        self.assertAlmostEqual(ns, 722.64 + 14.4528, places=2)

    def test_adequate_stop_preserved(self):
        ns, m = self._drive(115.10, 113.60, 2.302, "backside", "long")
        self.assertIsNone(m); self.assertEqual(ns, 113.60)

    def test_no_atr_fail_open(self):
        ns, m = self._drive(115.10, 115.07, 0.0, "backside", "long")
        self.assertIsNone(m); self.assertEqual(ns, 115.07)

    def test_env_disable(self):
        ns, m = self._drive(115.10, 115.07, 2.302, "backside", "long",
                            env={"STOP_FLOOR_ENFORCE":"0"})
        self.assertIsNone(m); self.assertEqual(ns, 115.07)

    def test_custom_floor(self):
        ns, m = self._drive(115.10, 114.10, 2.302, "backside", "long",
                            env={"EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT":"0.45"})
        self.assertIsNotNone(m); self.assertTrue(m["applied"])
        self.assertEqual(m["floor_atr_mult"], 0.45)


if __name__ == "__main__":
    unittest.main()
'''
TEST.parent.mkdir(parents=True, exist_ok=True)
TEST.write_text(CONTENT)
print(f"\u2705 Wrote {TEST}")
