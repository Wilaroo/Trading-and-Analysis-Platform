"""
v19.34.181 regression — opening-volatility time gate + R:R auto-ladder fallback.

  Part 1 (scanner): swing/position/investment/multi-day setups only go live
                    after 10:15 ET; scalp/intraday run all day. Gated on the
                    alert's final trade_style.
  Part 2 (evaluator): when a detector-supplied target yields sub-threshold
                    R:R, re-derive the target from actual risk via the
                    trade-style R ladder, choosing the smallest rung that
                    clears the effective min R:R.

Pure-logic tests (no IB/GPU/live DB per DGX constraint). The gate/ladder
helpers below mirror the exact logic shipped in source.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

LATER_HORIZON_STYLES = {"swing", "position", "investment", "multi_day"}
LATER_HORIZON_START_ET = (10, 15)


# ─── Part 1: time-of-day gate ────────────────────────────────────────────
class _Alert:
    def __init__(self, trade_style):
        self.trade_style = trade_style


def _later_horizon_window_ok(alert, now_et):
    style = str(getattr(alert, "trade_style", "") or "").strip().lower()
    if style not in LATER_HORIZON_STYLES:
        return True
    if (now_et.hour, now_et.minute) < LATER_HORIZON_START_ET:
        return False
    return True


def _et(h, m):
    return datetime(2026, 5, 29, h, m, tzinfo=ZoneInfo("America/New_York"))


def test_scalp_intraday_pass_all_day():
    for style in ("scalp", "intraday"):
        assert _later_horizon_window_ok(_Alert(style), _et(9, 31)) is True
        assert _later_horizon_window_ok(_Alert(style), _et(15, 59)) is True


def test_longer_horizon_blocked_before_1015():
    for style in ("swing", "position", "investment", "multi_day"):
        assert _later_horizon_window_ok(_Alert(style), _et(9, 35)) is False
        assert _later_horizon_window_ok(_Alert(style), _et(10, 0)) is False
        assert _later_horizon_window_ok(_Alert(style), _et(10, 14)) is False


def test_longer_horizon_allowed_at_and_after_1015():
    for style in ("swing", "position", "investment", "multi_day"):
        assert _later_horizon_window_ok(_Alert(style), _et(10, 15)) is True
        assert _later_horizon_window_ok(_Alert(style), _et(11, 0)) is True


def test_unknown_style_passes():
    assert _later_horizon_window_ok(_Alert(""), _et(9, 40)) is True
    assert _later_horizon_window_ok(_Alert(None), _et(9, 40)) is True


# ─── Part 2: R:R auto-ladder fallback ────────────────────────────────────
def _target_ladder_rungs(trade_style, setup_type):
    ts = (trade_style or "").strip().lower()
    sl = (setup_type or "").strip().lower()
    if ts == "scalp" or sl in {"scalp", "nine_ema_scalp", "spencer_scalp", "abc_scalp"}:
        return [1.0, 1.5]
    if ts in {"position", "investment"}:
        return [2.0, 4.0, 8.0]
    if ts == "intraday":
        return [1.5, 2.5]
    return [1.5, 2.5, 4.0]


def _fallback_rr(entry, stop, shares, risk_amount, trade_style, setup_type,
                 eff_min, is_long=True):
    """Mirror of the v19.34.181 fallback math in opportunity_evaluator."""
    risk_ps = abs(entry - stop)
    rungs = _target_ladder_rungs(trade_style, setup_type)
    chosen = next((r for r in rungs if r >= eff_min), rungs[-1])
    ladder = [r for r in rungs if r >= chosen] or [chosen]
    targets = [entry + risk_ps * r for r in ladder] if is_long else [entry - risk_ps * r for r in ladder]
    primary = targets[0]
    reward = abs(primary - entry) * shares
    rr = reward / risk_amount if risk_amount > 0 else 0
    return rr, chosen, primary


def test_swing_ladder_picks_rung_that_clears_floor():
    # swing rungs [1.5,2.5,4]; eff_min 1.7 → smallest rung >= 1.7 is 2.5
    # entry 100, stop 90 (risk $10/sh), 100 shares → risk_amount $1000
    rr, chosen, primary = _fallback_rr(
        entry=100, stop=90, shares=100, risk_amount=1000,
        trade_style="swing", setup_type="three_week_tight", eff_min=1.7,
    )
    assert chosen == 2.5
    assert primary == 125.0          # 100 + 10*2.5
    assert rr == 2.5 and rr >= 1.7


def test_position_ladder_picks_2R():
    rr, chosen, primary = _fallback_rr(
        entry=88, stop=80, shares=10, risk_amount=80,
        trade_style="position", setup_type="stage_2_breakout", eff_min=1.7,
    )
    assert chosen == 2.0
    assert rr == 2.0 and rr >= 1.7


def test_fallback_rescues_subthreshold_detector_target():
    # Detector gave a too-close target → R:R 0.25; fallback must lift it.
    entry, stop, shares, risk_amount = 88.0, 80.0, 10, 80.0
    detector_target = 90.0  # only $2 vs $8 risk → 0.25 R:R
    detector_rr = (abs(detector_target - entry) * shares) / risk_amount
    assert detector_rr < 1.7
    rr, _, _ = _fallback_rr(entry, stop, shares, risk_amount,
                            "position", "stage_2_breakout", 1.7)
    assert rr >= 1.7


def test_short_direction_targets_below_entry():
    rr, chosen, primary = _fallback_rr(
        entry=100, stop=110, shares=50, risk_amount=500,
        trade_style="swing", setup_type="daily_squeeze", eff_min=1.7,
        is_long=False,
    )
    assert primary == 75.0           # 100 - 10*2.5
    assert rr >= 1.7
