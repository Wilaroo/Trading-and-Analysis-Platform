"""
v19.34.183 regression — stop geometry sanity.

Part 1 (squeeze detector, REAL function): a squeeze whose price has already
   broken out and run past the band must produce a consistent entry/stop/
   target (long: stop < entry < target; short: target < entry < stop), with
   the entry clamped to current price instead of the stale band level.

Part 2 (evaluator guards, mirrored logic): the wrong-side stop guard recomputes
   an inverted detector stop; the position/investment stop-cap tightens an
   over-wide detector stop to 5% of entry. (The guards are inline in the large
   evaluate_opportunity method; the helpers below mirror the exact shipped
   logic, per the DGX no-integration-test constraint.)
"""
import asyncio
from types import SimpleNamespace

from services.enhanced_scanner import EnhancedBackgroundScanner


# ─── Part 1: real squeeze detector geometry ──────────────────────────────
def _scanner():
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._market_regime = SimpleNamespace(value="neutral")
    s._get_current_time_window = lambda: SimpleNamespace(value="midday")
    return s


def _snap(current_price, bb_upper, bb_lower, atr, squeeze_fire=1.0):
    return SimpleNamespace(
        squeeze_on=True, rvol=1.6, squeeze_fire=squeeze_fire, bb_width=2.6,
        bb_lower=bb_lower, bb_upper=bb_upper, current_price=current_price,
        atr=atr, rsi_14=70,
    )


def _tape():
    return SimpleNamespace(
        confirmation_for_long=False, confirmation_for_short=False,
        overall_signal=SimpleNamespace(value="neutral"), tape_score=0.2,
    )


def test_squeeze_long_ran_past_band_stop_below_entry():
    """The DIA case: cp=510.9 already above bb_upper=501.63."""
    s = _scanner()
    snap = _snap(current_price=510.9, bb_upper=501.63, bb_lower=495.0, atr=5.1)
    alert = asyncio.run(s._check_squeeze("DIA", snap, _tape()))
    assert alert is not None and alert.direction == "long"
    assert alert.trigger_price >= 510.9 - 0.01, "entry should clamp to current price"
    assert alert.stop_loss < alert.trigger_price, "long stop must be BELOW entry"
    assert alert.target > alert.trigger_price, "long target must be ABOVE entry"


def test_squeeze_long_normal_entry_is_bb_upper():
    """Normal pre-breakout: cp below bb_upper → entry stays at the band."""
    s = _scanner()
    snap = _snap(current_price=100.0, bb_upper=101.0, bb_lower=98.0, atr=1.0)
    alert = asyncio.run(s._check_squeeze("AAA", snap, _tape()))
    assert alert is not None
    assert abs(alert.trigger_price - 101.0) < 0.01, "entry = bb_upper in normal case"
    assert alert.stop_loss < alert.trigger_price


def test_squeeze_short_ran_past_band_stop_above_entry():
    s = _scanner()
    snap = _snap(current_price=50.0, bb_upper=56.0, bb_lower=54.0, atr=1.5, squeeze_fire=-1.0)
    alert = asyncio.run(s._check_squeeze("BBB", snap, _tape()))
    assert alert is not None and alert.direction == "short"
    assert alert.trigger_price <= 50.0 + 0.01, "entry should clamp to current price"
    assert alert.stop_loss > alert.trigger_price, "short stop must be ABOVE entry"
    assert alert.target < alert.trigger_price, "short target must be BELOW entry"


# ─── Part 2: evaluator guard logic (mirrors shipped source) ──────────────
def _wrong_side_recompute(entry, stop, is_long, recomputed):
    """Mirror of the v183 wrong-side guard in opportunity_evaluator."""
    wrong = (is_long and stop >= entry) or ((not is_long) and stop <= entry)
    return recomputed if (stop and entry and wrong) else stop


def _position_stop_cap(entry, stop, style, is_long, cap_pct=0.05):
    """Mirror of the v183 detector-stop position/investment cap."""
    if style in ("position", "investment") and stop and entry:
        dist = abs(entry - stop)
        cap_dist = entry * cap_pct
        if cap_pct and cap_dist > 0 and dist > cap_dist:
            return (entry - cap_dist) if is_long else (entry + cap_dist)
    return stop


def test_wrong_side_long_inverted_stop_recomputed():
    # DIA: entry 501.63, inverted stop 505.82 (long) → recompute to below entry
    out = _wrong_side_recompute(501.63, 505.82, is_long=True, recomputed=496.5)
    assert out == 496.5
    assert out < 501.63


def test_wrong_side_short_inverted_stop_recomputed():
    out = _wrong_side_recompute(50.0, 49.0, is_long=False, recomputed=51.5)
    assert out == 51.5 and out > 50.0


def test_correct_side_stop_left_untouched():
    assert _wrong_side_recompute(100.0, 98.0, is_long=True, recomputed=95.0) == 98.0
    assert _wrong_side_recompute(100.0, 102.0, is_long=False, recomputed=105.0) == 102.0


def test_position_stop_cap_tightens_wide_detector_stop():
    # BMO: entry 161.84, 16.8% structural stop 134.61, position style
    out = _position_stop_cap(161.84, 134.61, "position", is_long=True)
    assert abs(out - 161.84 * 0.95) < 1e-6
    assert out > 134.61, "cap must TIGHTEN (raise) a too-wide long stop"


def test_position_cap_does_not_loosen_tight_stop():
    # already within 5% — unchanged
    out = _position_stop_cap(161.84, 156.0, "position", is_long=True)
    assert out == 156.0


def test_swing_and_intraday_styles_not_capped():
    # BOXX is swing — the position cap must not touch it
    assert _position_stop_cap(116.85, 110.0, "swing", is_long=True) == 110.0
    assert _position_stop_cap(100.0, 80.0, "intraday", is_long=True) == 80.0


def test_investment_cap_short_side():
    out = _position_stop_cap(100.0, 120.0, "investment", is_long=False)
    assert abs(out - 105.0) < 1e-6  # entry + 5%
    assert out < 120.0
