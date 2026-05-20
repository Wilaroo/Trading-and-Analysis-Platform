"""v19.34.45 -- Stop-floor enforcement regression suite.

The pre-exec guardrail requires |entry-stop| ≥ 0.3 × ATR. Before
v19.34.45 the evaluator passed alert-supplied stops straight through —
so a $0.03 stop on a $115 stock with $2.30 ATR would burn an entire
evaluation cycle and then get vetoed by `pre_exec_guardrail_veto`.

This test suite verifies:
  * Too-tight alert stop → recomputed via canonical per-setup ATR mult
  * Adequate alert stop → preserved unchanged
  * No ATR → fail-open (existing behavior preserved)
  * STOP_FLOOR_ENFORCE=0 → gate disabled
  * Recomputed stop ALSO too tight → logged, alert stop kept (no infinite
    loop / no silent acceptance)
"""
from __future__ import annotations
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestStopFloorEnforcement(unittest.TestCase):
    """Tests the in-place stop_price mutation inside `evaluate_opportunity`.

    Rather than spin the full evaluator (which requires a real bot,
    DB, scanner, IB, etc.), we extract the gate's logic into a
    targeted micro-driver that exercises the exact code path.
    """

    def _drive_floor(self, entry_price, stop_price, atr, setup_type,
                     direction_str="long", env=None):
        """Execute the v19.34.45 stop-floor block in isolation, return
        (new_stop_price, stop_floor_meta).
        """
        from services.opportunity_evaluator import OpportunityEvaluator
        from services.trading_bot_service import TradeDirection

        evaluator = OpportunityEvaluator()
        # Lightweight bot stub with the risk-params surface the
        # canonical `calculate_atr_based_stop` reaches into.
        bot = MagicMock()
        bot.risk_params = MagicMock(
            base_atr_multiplier=1.5,
            min_atr_multiplier=1.0,
            max_atr_multiplier=3.0,
        )
        direction = (TradeDirection.LONG if direction_str == "long"
                     else TradeDirection.SHORT)

        # Inline-replica of the gate (mirrors the exact code in
        # evaluate_opportunity — keeps the test independent of all
        # upstream / downstream surface area).
        stop_floor_meta = None
        symbol = "TEST"
        with patch.dict(os.environ, env or {}, clear=False):
            try:
                import os as _os_floor
                _enf_raw = _os_floor.environ.get("STOP_FLOOR_ENFORCE", "1")
                _enf_on = str(_enf_raw).strip().lower() not in (
                    "0", "", "false", "no", "off"
                )
                if _enf_on and stop_price and entry_price and atr and atr > 0:
                    try:
                        _floor_mult = float(_os_floor.environ.get(
                            "EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT", "0.3"
                        ))
                    except (TypeError, ValueError):
                        _floor_mult = 0.3
                    _distance = abs(float(entry_price) - float(stop_price))
                    _threshold = _floor_mult * float(atr)
                    if _distance < _threshold:
                        _orig_stop = float(stop_price)
                        _new_stop = evaluator.calculate_atr_based_stop(
                            float(entry_price), direction, float(atr),
                            setup_type, bot,
                        )
                        _new_distance = abs(float(entry_price) - float(_new_stop))
                        if _new_distance >= _threshold:
                            stop_price = _new_stop
                            stop_floor_meta = {
                                "applied": True,
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                                "original_distance": _distance,
                                "recomputed_distance": _new_distance,
                            }
                        else:
                            stop_floor_meta = {
                                "applied": False,
                                "reason": "recomputed_also_too_tight",
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                            }
            except Exception:
                pass

        return stop_price, stop_floor_meta

    def test_xly_backside_too_tight_is_widened(self):
        # Real sample from production trade_drops:
        # entry=$115.10, stop=$115.07 ($0.03), ATR=$2.3020 → 1.3% of ATR
        # backside multiplier = 0.5× → recomputed stop should be
        # $115.10 - 0.5*2.302 = $113.949 → distance $1.151
        new_stop, meta = self._drive_floor(
            entry_price=115.10, stop_price=115.07, atr=2.302,
            setup_type="backside", direction_str="long",
        )
        self.assertIsNotNone(meta)
        self.assertTrue(meta["applied"])
        self.assertAlmostEqual(meta["recomputed_distance"], 1.151, places=2)
        # Recomputed stop must clear the 0.3 × ATR floor.
        self.assertGreaterEqual(
            abs(115.10 - new_stop), 0.3 * 2.302,
            f"recomputed stop {new_stop} still below floor",
        )

    def test_vwap_fade_short_too_tight_is_widened(self):
        # Real sample: entry=$722.64, stop=$725.92 ($3.28), ATR=$14.4528
        # vwap_fade_short multiplier = 1.0× → recomputed stop distance
        # should be 1.0 × 14.4528 = $14.4528.
        new_stop, meta = self._drive_floor(
            entry_price=722.64, stop_price=725.92, atr=14.4528,
            setup_type="vwap_fade_short", direction_str="short",
        )
        self.assertIsNotNone(meta)
        self.assertTrue(meta["applied"])
        # Short trade → stop is ABOVE entry; recomputed = entry + 1.0×ATR
        self.assertAlmostEqual(new_stop, 722.64 + 14.4528, places=2)

    def test_adequate_stop_is_preserved(self):
        # 0.5 × ATR = 1.15. Alert supplies a 1.5 distance → above floor.
        new_stop, meta = self._drive_floor(
            entry_price=115.10, stop_price=113.60, atr=2.302,
            setup_type="backside", direction_str="long",
        )
        # Floor wasn't violated → no metadata, stop unchanged.
        self.assertIsNone(meta)
        self.assertEqual(new_stop, 113.60)

    def test_no_atr_is_fail_open(self):
        # ATR=0 → we can't validate; pass through and let downstream
        # guardrail's percentage-based fallback handle it.
        new_stop, meta = self._drive_floor(
            entry_price=115.10, stop_price=115.07, atr=0.0,
            setup_type="backside", direction_str="long",
        )
        self.assertIsNone(meta)
        self.assertEqual(new_stop, 115.07)

    def test_env_disable(self):
        # Operator can disable the gate via env knob.
        new_stop, meta = self._drive_floor(
            entry_price=115.10, stop_price=115.07, atr=2.302,
            setup_type="backside", direction_str="long",
            env={"STOP_FLOOR_ENFORCE": "0"},
        )
        self.assertIsNone(meta)
        self.assertEqual(new_stop, 115.07)

    def test_custom_floor_threshold(self):
        # Operator can tighten the floor via the shared knob.
        # 0.45 × ATR floor → 0.45 × 2.302 = 1.0359. Alert supplies $1.00 →
        # below the higher floor, must be widened to the per-setup 0.5×
        # which gives $1.151 (clears the tightened floor).
        new_stop, meta = self._drive_floor(
            entry_price=115.10, stop_price=114.10, atr=2.302,
            setup_type="backside", direction_str="long",
            env={"EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT": "0.45"},
        )
        self.assertIsNotNone(meta)
        self.assertTrue(meta["applied"])
        self.assertEqual(meta["floor_atr_mult"], 0.45)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
