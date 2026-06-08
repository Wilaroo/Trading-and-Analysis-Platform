"""
v19.34.290 F1 — DATA-TRUST: time-of-day-adjusted RVOL.

Audit Phase 1 finding F1: RVOL was `today_partial_cumulative_volume / full_day_20d_avg`,
which is time-of-day naive — a genuine 5x mover read ~0.3 at 10:00 ET. RVOL gates
nearly every setup, so it under-fired movers early and over-fired late.

Fix: scale the baseline by the fraction of the RTH session elapsed
(`avg_volume * minutes_since_open/390`), mirroring ib_data_provider.calculate_rvol.
Guards: env kill-switch SCANNER_TOD_RVOL=false; and a STALE today-bar (not the
current ET session) is never scaled (returns fraction 1.0) so a complete prior-day
volume can't become a false-high RVOL.
"""
from datetime import datetime, timezone, timedelta

import mongomock

from services.realtime_technical_service import RealTimeTechnicalService


def _svc():
    s = RealTimeTechnicalService()
    s.set_db(mongomock.MongoClient()["t"])
    return s


def _daily_with_today_volume(today_vol, hist_vol=1_000_000, n_hist=21):
    """n_hist history bars (each hist_vol) + a final 'today' bar with today_vol.
    avg_volume (20d, bars[-21:-1]) == hist_vol."""
    bars = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n_hist):
        bars.append({
            "timestamp": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": hist_vol,
        })
    bars.append({
        "timestamp": (base + timedelta(days=n_hist)).strftime("%Y-%m-%d"),
        "open": 100, "high": 102, "low": 99, "close": 101.0, "volume": today_vol,
    })
    return bars


def _snap(s, daily):
    return s._calculate_snapshot(
        symbol="AAPL", current_price=101.0,
        intraday_bars=[
            {"timestamp": "2026-02-10 09:35:00", "open": 100, "high": 101,
             "low": 99.5, "close": 100.5, "volume": 5000} for _ in range(6)
        ],
        daily_bars=daily, quote={"price": 101.0}, spy_change_pct=0.0,
    )


def test_tod_rvol_scales_by_time_fraction(monkeypatch):
    s = _svc()
    # 25% of the session elapsed; today did 250k vs 1M full-day avg.
    monkeypatch.setattr(s, "_rth_time_fraction", lambda *a, **k: 0.25)
    snap = _snap(s, _daily_with_today_volume(250_000))
    # Naive would be 250k/1M = 0.25; TOD-adjusted = 250k/(1M*0.25) = 1.0.
    assert snap.rvol == 1.0


def test_tod_rvol_flags_real_mover(monkeypatch):
    s = _svc()
    # 10:00 ET ~= 30/390 of the session; a mover already at 0.5x full-day avg.
    monkeypatch.setattr(s, "_rth_time_fraction", lambda *a, **k: 30.0 / 390.0)
    snap = _snap(s, _daily_with_today_volume(500_000))
    # Naive = 0.5 (looks 'low'); TOD = 0.5 / (30/390) = 6.5 (clearly exceptional).
    assert snap.rvol > 6.0


def test_tod_rvol_disabled_via_env(monkeypatch):
    s = _svc()
    monkeypatch.setenv("SCANNER_TOD_RVOL", "false")
    # If disabled, _rth_time_fraction must not influence the result.
    monkeypatch.setattr(s, "_rth_time_fraction", lambda *a, **k: 0.25)
    snap = _snap(s, _daily_with_today_volume(250_000))
    assert snap.rvol == 0.25  # raw full-day ratio


def test_rth_time_fraction_stale_today_bar_returns_one():
    s = _svc()
    # A 'today' bar dated years ago -> never scaled (complete prior session).
    assert s._rth_time_fraction({"timestamp": "2020-01-02"}) == 1.0


def test_rth_time_fraction_bounds():
    s = _svc()
    tf = s._rth_time_fraction(None)
    assert isinstance(tf, float) and 0.0 < tf <= 1.0
