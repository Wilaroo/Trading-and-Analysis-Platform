"""
test_v353_second_chance.py — Second Chance Scalp cheat-sheet rewrite (v19.34.353).

Drives EnhancedBackgroundScanner._check_second_chance directly with a fabricated `self`,
synthetic 1-min bars, snapshot and tape. Verifies the SMB 2nd Chance Scalp doctrine:
  • FIRES a LONG on a resistance break -> low-vol retest holding old resistance as new
    support -> confirmation candle, with STOP = .02 below the TURN-CANDLE LOW and
    TARGET = the rush high (high of the initial pullback), R:R gated to [1.5, 2.5].
  • DOES NOT fire when the confirmation candle does not close above the prior candle.
  • DOES NOT fire when the retest breaks back into range (turn low below support band).
  • DOES NOT fire when R:R falls outside the validated 1.5-2.5 band (rush high too far).
  • DOES NOT fire when the break has no volume expansion (break vol < 1.3x median).
  • Caps at 2 fires/day per symbol ("2 strikes and we're out").

Run on DGX:  pytest backend/tests/test_v353_second_chance.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _bar(o, h, l, c, v=1000):
    return {"date": "2026-06-01T14:30:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


def _fake_self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: bars),
        _strategy_stats={},
        _second_chance_daily_caps={},
        _market_regime=SimpleNamespace(value="momentum"),
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
    )


def _snap(current):
    return SimpleNamespace(current_price=current)


def _tape(conf_long=True):
    return SimpleNamespace(confirmation_for_long=conf_long,
                           overall_signal=SimpleNamespace(value="buy"))


def _run(slf, snap, tape):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_second_chance(slf, "TEST", snap, tape))


# 32 bars. With i=31: cons=bars[10:25] (resistance=100.00), rush=bars[25:31]
# (rush_high=100.60), ret=bars[27:31] (turn_low=100.00 at bar28). Last bar (31)
# is a green confirm that closes 100.20 above bar30 high 100.15.
#   entry 100.20, stop 99.98 (.02 below turn low), target 100.60 -> R:R ~1.82.
_FILLER = [_bar(99.5, 99.7, 99.3, 99.6) for _ in range(10)]          # 0..9
_CONS = [_bar(99.5, 100.00, 99.00, 99.5) for _ in range(15)]         # 10..24 (med vol 1000)
_RUSH = [
    _bar(99.95, 100.30, 99.95, 100.25, v=3000),   # 25 break (high vol)
    _bar(100.25, 100.60, 100.20, 100.55, v=2500), # 26 rush peak -> rush_high 100.60
    _bar(100.50, 100.40, 100.05, 100.10, v=500),  # 27 pullback (ret start, low vol)
    _bar(100.10, 100.15, 100.00, 100.08, v=400),  # 28 TURN low 100.00
    _bar(100.08, 100.18, 100.04, 100.14, v=450),  # 29
    _bar(100.12, 100.15, 100.06, 100.13, v=500),  # 30 prior bar (high 100.15)
]
_CONFIRM = [_bar(100.10, 100.28, 100.08, 100.20, v=900)]             # 31 confirm/entry
FIRE_BARS = _FILLER + _CONS + _RUSH + _CONFIRM


def test_fires_resistance_retest():
    a = _run(_fake_self(FIRE_BARS), _snap(100.20), _tape())
    assert a is not None, "expected a cheat-sheet second-chance long"
    assert a.setup_type == "second_chance" and a.direction == "long"
    assert abs(a.stop_loss - 99.98) < 0.001, "stop must be .02 below the turn-candle low (100.00)"
    assert abs(a.target - 100.60) < 0.001, "target must be the rush high (100.60)"
    assert abs(a.trigger_price - 100.20) < 0.001, "entry must be the confirm-bar close"
    assert 1.5 <= a.risk_reward <= 2.5, "R:R must be inside the validated 1.5-2.5 band"


def test_no_fire_without_confirmation():
    bars = [dict(b) for b in FIRE_BARS]
    bars[-1]["close"] = 100.10   # closes BELOW prior bar high 100.15 -> no confirmation
    a = _run(_fake_self(bars), _snap(100.10), _tape())
    assert a is None, "no confirmation candle (close <= prior high) must not fire"


def test_no_fire_when_support_breaks():
    bars = [dict(b) for b in FIRE_BARS]
    bars[28]["low"] = 99.50      # turn low falls back into range (below support band)
    a = _run(_fake_self(bars), _snap(100.20), _tape())
    assert a is None, "retest breaking back into range must not fire"


def test_no_fire_rr_above_band():
    bars = [dict(b) for b in FIRE_BARS]
    bars[26]["high"] = 101.50    # rush high too far -> R:R > 2.5 (outside +EV slice)
    a = _run(_fake_self(bars), _snap(100.20), _tape())
    assert a is None, "R:R above 2.5 (dead band) must not fire"


def test_no_fire_without_volume_expansion():
    bars = [dict(b) for b in FIRE_BARS]
    bars[25]["volume"] = 1000    # break vol now == median (no expansion)
    bars[26]["volume"] = 1000
    a = _run(_fake_self(bars), _snap(100.20), _tape())
    assert a is None, "break without volume expansion (>=1.3x median) must not fire"


def test_two_strikes_cap():
    slf = _fake_self(FIRE_BARS)
    snap, tape = _snap(100.20), _tape()
    first = _run(slf, snap, tape)
    second = _run(slf, snap, tape)
    third = _run(slf, snap, tape)
    assert first is not None and second is not None
    assert third is None, "max 2 attempts/day/symbol: third fire must be capped"
