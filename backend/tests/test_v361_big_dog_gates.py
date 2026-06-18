"""
test_v361_big_dog_gates.py — Big Dog min-price + min-stop gates (v361).

Verifies the v361 tighten of EnhancedBackgroundScanner._check_big_dog:
  • price floor   : current_price < $10            -> None (drop illiquid)
  • min-stop floor: ATR-floored stop < 1.0% of cp  -> None (kill tight-stop blow-throughs)
  • a clean, liquid, real-stop coil near HOD        -> fires a big_dog LONG alert
  • the original gates still apply (rvol < 1.2 -> None)

Rationale: 180d/300-sym 5-min replay (diag_v361_big_dog_replay.py) showed the live
trigger@HOD model is breakeven (winsorAvg -0.009R) but flips to +0.097R (win 53%, medR
+0.132, n=268) once tight-stop blow-throughs on low-priced/illiquid names are excluded.
Ground truth (n=5 real fills) was avgR -2.0 — every loss a sub-1% stop on a <$30 name that
gapped through. Tightening the coil alone did NOT help; the stop/price floor is the lever.

Run on DGX:  pytest backend/tests/test_v361_big_dog_gates.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _self():
    return SimpleNamespace(
        _atr_floored_stop=EnhancedBackgroundScanner._atr_floored_stop.__get__(object()),
        _get_current_time_window=lambda: SimpleNamespace(value="open"),
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _tape():
    return SimpleNamespace(overall_signal=SimpleNamespace(value="buy"))


def _run(self_obj, snap):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_big_dog(self_obj, "TEST", snap, _tape()))


def _snap(**kw):
    base = dict(daily_range_pct=1.5, above_vwap=True, above_ema9=True, rvol=1.5,
                current_price=100.0, high_of_day=100.5, ema_9=98.0, atr=2.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_price_floor_blocks_illiquid():
    s = _snap(current_price=8.0, high_of_day=8.04, ema_9=7.8, atr=0.2)
    assert _run(_self(), s) is None, "big_dog must reject current_price < $10 (v361 price floor)"


def test_min_stop_floor_blocks_tight_stop():
    # ema_9 just below price + tiny ATR -> ATR-floored stop is < 1% of price
    s = _snap(current_price=100.0, high_of_day=100.5, ema_9=99.9, atr=0.1)
    assert _run(_self(), s) is None, "big_dog must reject sub-1% stops (v361 min-stop floor)"


def test_clean_liquid_coil_fires():
    s = _snap(current_price=100.0, high_of_day=100.5, ema_9=98.0, atr=2.0)
    alert = _run(_self(), s)
    assert alert is not None and alert.setup_type == "big_dog" and alert.direction == "long"
    stop_pct = (s.current_price - alert.stop_loss) / s.current_price * 100
    assert stop_pct >= 1.0, f"surviving fire must have a >=1% stop, got {stop_pct:.2f}%"


def test_original_rvol_gate_still_applies():
    s = _snap(rvol=1.0)
    assert _run(_self(), s) is None, "original rvol>=1.2 gate must still block"
