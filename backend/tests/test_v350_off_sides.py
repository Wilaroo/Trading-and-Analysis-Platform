"""
test_v350_off_sides.py — Off Sides range-top fade SHORT snapback (v19.34.350).

Drives EnhancedBackgroundScanner._check_off_sides directly with a fabricated `self`, 1-min
bars, snapshot and tape. Verifies:
  • FIRES a SHORT with target == LOD (range low) when there's no VWAP room below entry.
  • FIRES a SHORT with target == VWAP when LOD < VWAP < entry (mean-reversion room).
  • DOES NOT fire outside RANGE_BOUND/FADE regime.
  • DOES NOT fire when price is not within 1% of HOD, or |dist_from_vwap| >= 1%.
  • DOES NOT fire when stop < 1.0% of entry (min-risk floor).
  • Caps at 2 fires/day per symbol.

Run on DGX:  pytest backend/tests/test_v350_off_sides.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner, MarketRegime


def _bar(o, h, l, c, v=10000):
    return {"date": "2026-06-01T13:30:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


def _fake_self(bars, regime=MarketRegime.RANGE_BOUND):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: bars),
        _strategy_stats={},
        _off_sides_daily_caps={},
        _market_regime=regime,
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
    )


def _snap(vwap, current, hod, lod, dist_vwap=0.3, range_pct=5.0):
    return SimpleNamespace(vwap=vwap, current_price=current, high_of_day=hod, low_of_day=lod,
                           dist_from_vwap=dist_vwap, daily_range_pct=range_pct)


def _tape(conf_short=True):
    return SimpleNamespace(confirmation_for_short=conf_short,
                           overall_signal=SimpleNamespace(value="sell"))


def _run(slf, snap, tape):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_off_sides(slf, "TEST", snap, tape))


# entry = min(prior-2 lows) = 10.10; last bar red, breaks below 10.10; stop = HOD+0.02.
# LOD=10.00 < VWAP=10.20 but VWAP > entry(10.10) -> use LOD target.
LOD_BARS = [
    _bar(10.20, 10.24, 10.19, 10.22),
    _bar(10.22, 10.26, 10.21, 10.24),
    _bar(10.24, 10.28, 10.23, 10.26),
    _bar(10.26, 10.29, 10.10, 10.12),   # low 10.10
    _bar(10.12, 10.20, 10.11, 10.18),   # low 10.11 -> entry 10.10
    _bar(10.16, 10.18, 10.05, 10.06),   # last: red, low 10.05 < 10.10, big range
]

# entry = 10.30; VWAP=10.25; LOD=10.00 -> LOD < VWAP < entry -> use VWAP target. HOD=10.50.
VWAP_BARS = [
    _bar(10.40, 10.44, 10.39, 10.42),
    _bar(10.42, 10.46, 10.41, 10.44),
    _bar(10.44, 10.48, 10.43, 10.46),
    _bar(10.46, 10.49, 10.30, 10.33),   # low 10.30
    _bar(10.33, 10.40, 10.31, 10.38),   # low 10.31 -> entry 10.30
    _bar(10.36, 10.38, 10.24, 10.26),   # last: red, low 10.24 < 10.30
]


def test_fires_lod_target():
    a = _run(_fake_self(LOD_BARS), _snap(10.20, 10.25, 10.30, 10.00), _tape())
    assert a is not None, "expected an off_sides short with LOD target"
    assert a.setup_type == "off_sides_short" and a.direction == "short"
    assert abs(a.target - 10.00) < 0.001, "target must be the range LOD"
    assert a.trigger_price < a.stop_loss


def test_fires_vwap_target():
    a = _run(_fake_self(VWAP_BARS), _snap(10.25, 10.45, 10.50, 10.00), _tape())
    assert a is not None, "expected an off_sides short with VWAP target"
    assert abs(a.target - 10.25) < 0.001, "target must be VWAP when LOD < VWAP < entry"


def test_no_fire_wrong_regime():
    a = _run(_fake_self(LOD_BARS, regime=MarketRegime.STRONG_UPTREND),
             _snap(10.20, 10.25, 10.30, 10.00), _tape())
    assert a is None, "off_sides fires only in RANGE_BOUND/FADE"


def test_no_fire_far_from_hod():
    a = _run(_fake_self(LOD_BARS), _snap(10.20, 10.00, 10.30, 10.00), _tape())
    assert a is None, "price >1% below HOD must not fire"


def test_no_fire_not_near_vwap():
    a = _run(_fake_self(LOD_BARS), _snap(10.20, 10.25, 10.30, 10.00, dist_vwap=2.0), _tape())
    assert a is None, "|dist_from_vwap| >= 1% is vwap_fade-short territory"


def test_min_risk_floor_gate():
    # High-priced symbol: stop barely above entry -> risk < 1.0% -> gated.
    bars = [
        _bar(200.4, 200.7, 200.3, 200.5),
        _bar(200.4, 200.6, 200.4, 200.5),
        _bar(200.4, 200.6, 200.4, 200.5),
        _bar(200.4, 200.5, 200.30, 200.35),  # low 200.30
        _bar(200.35, 200.45, 200.31, 200.40),  # low 200.31 -> entry 200.30
        _bar(200.38, 200.42, 200.20, 200.22),  # last: red, low 200.20
    ]
    a = _run(_fake_self(bars), _snap(200.25, 200.45, 200.50, 200.00), _tape())
    assert a is None, "stop < 1.0% of entry must be gated by the min-risk floor"


def test_two_per_day_cap():
    slf = _fake_self(LOD_BARS)
    slf._off_sides_daily_caps = {}
    snap, tape = _snap(10.20, 10.25, 10.30, 10.00), _tape()
    first = _run(slf, snap, tape)
    second = _run(slf, snap, tape)
    third = _run(slf, snap, tape)
    assert first is not None and second is not None
    assert third is None, "third fire on same symbol/day must be capped"
