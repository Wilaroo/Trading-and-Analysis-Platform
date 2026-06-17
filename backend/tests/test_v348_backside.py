"""
test_v348_backside.py — Back$ide VWAP-recovery snapback (v19.34.348).

Drives EnhancedScanner._check_backside directly with a fabricated `self`, 1-min bars,
snapshot and tape. Verifies:
  • FIRES a +EV snapback in the shallow [0.3%, 1.0%) dip band (target == VWAP, long).
  • DOES NOT fire at >= 1.0% dip (that is vwap_fade's band — zero overlap by construction).
  • DOES NOT fire when stop < 1.0% of entry (min-risk floor).
  • DOES NOT fire when RVOL < 1.2, when price is not above the 9-EMA, or after 2 fires/day.

Run on DGX:  pytest backend/tests/test_v348_backside.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

# backend/ on sys.path so `services.*` resolves regardless of pytest rootdir / PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedScanner


def _bar(o, h, l, c, v=10000):
    return {"date": "2026-06-01T13:30:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


def _fake_self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: bars),
        _strategy_stats={},
        _backside_daily_caps={},
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _market_regime=SimpleNamespace(value="uptrend"),
    )


def _snap(vwap, current, support, atr, rvol=1.5, above_ema9=True):
    return SimpleNamespace(vwap=vwap, current_price=current, support=support, atr=atr,
                           rvol=rvol, above_ema9=above_ema9)


def _tape(conf_long=True):
    return SimpleNamespace(confirmation_for_long=conf_long,
                           overall_signal=SimpleNamespace(value="buy"))


def _run(slf, snap, tape):
    return asyncio.get_event_loop().run_until_complete(
        EnhancedScanner._check_backside(slf, "TEST", snap, tape))


# Low-priced symbol so the 0.02 stop buffer + ~0.9% dip clears the 1.0% min-risk floor.
# vwap=10.0, LOD=9.91 -> dip=0.9% (in band); entry=9.99 (<vwap); stop=9.89 -> risk 1.0%.
FIRE_BARS = [
    _bar(9.95, 9.96, 9.93, 9.95),
    _bar(9.95, 9.97, 9.94, 9.96),
    _bar(9.96, 9.97, 9.95, 9.96),
    _bar(9.96, 9.97, 9.91, 9.93),   # idx3 = LOD bar (range 0.06 > 1.3*median)
    _bar(9.94, 9.99, 9.94, 9.98),   # idx4 = prior-high 9.99
    _bar(9.96, 10.01, 9.97, 10.00),  # idx5 = last: green, high 10.01 clears 9.99
]


def test_fires_in_shallow_band():
    a = _run(_fake_self(FIRE_BARS), _snap(10.0, 9.99, 20.0, 0.10), _tape())
    assert a is not None, "expected a backside snapback alert in 0.9% dip band"
    assert a.setup_type == "backside"
    assert a.direction == "long"
    assert abs(a.target - 10.0) < 0.001, "target must be VWAP"
    assert a.stop_loss < a.trigger_price <= 10.0


def test_no_fire_in_vwap_fade_band():
    # Push LOD to 9.80 -> dip 2.0% (>= DIP_CEIL) -> belongs to vwap_fade, backside must skip.
    bars = [dict(b) for b in FIRE_BARS]
    bars[3]["low"] = 9.80
    a = _run(_fake_self(bars), _snap(10.0, 9.99, 20.0, 0.10), _tape())
    assert a is None, "dip >= 1.0% is vwap_fade's band; backside must not double-fire"


def test_min_risk_floor_gate():
    # High-priced symbol: 0.5% dip -> stop barely below entry -> risk < 1.0% -> gated.
    bars = [
        _bar(199.5, 199.7, 199.3, 199.5),
        _bar(199.5, 199.8, 199.4, 199.6),
        _bar(199.6, 199.8, 199.5, 199.6),
        _bar(199.6, 199.8, 199.0, 199.2),   # LOD=199.0 -> dip 0.5%
        _bar(199.4, 199.9, 199.4, 199.8),   # prior high 199.9
        _bar(199.6, 200.1, 199.7, 200.0),   # last clears 199.9
    ]
    a = _run(_fake_self(bars), _snap(200.0, 199.9, 400.0, 0.5), _tape())
    assert a is None, "stop < 1.0% of entry must be gated by the min-risk floor"


def test_rvol_gate():
    a = _run(_fake_self(FIRE_BARS), _snap(10.0, 9.99, 20.0, 0.10, rvol=1.0), _tape())
    assert a is None, "RVOL < 1.2 must be gated"


def test_above_ema9_gate():
    a = _run(_fake_self(FIRE_BARS), _snap(10.0, 9.99, 20.0, 0.10, above_ema9=False), _tape())
    assert a is None, "must require price above the 9-EMA (recovery)"


def test_two_per_day_cap():
    slf = _fake_self(FIRE_BARS)
    slf._backside_daily_caps = {}
    snap, tape = _snap(10.0, 9.99, 20.0, 0.10), _tape()
    first = _run(slf, snap, tape)
    second = _run(slf, snap, tape)
    third = _run(slf, snap, tape)
    assert first is not None and second is not None
    assert third is None, "third fire on same symbol/day must be capped"
