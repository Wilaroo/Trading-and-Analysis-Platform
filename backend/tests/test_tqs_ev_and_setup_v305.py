"""
v19.34.305 regression tests for the TQS trust fixes:

  1. EV unification — `StrategyStats.expected_value_r` must equal the realized
     mean of its r_outcomes (no decomposed-formula / sample-mismatch artifact).
  2. Setup-pillar rebalance — the win-rate cliff is gone (a 40%-win setup no
     longer scores 0 on the win-rate sub-component) and EV now carries the most
     sub-weight, so a negative-EV setup is graded below a positive-EV one.

These are pure-Python unit checks (no IB / Mongo) so they run anywhere.
"""
import asyncio
import math

from services.enhanced_scanner import StrategyStats
from services.tqs.setup_quality import get_setup_quality_service


def test_ev_equals_realized_mean():
    s = StrategyStats(setup_type="unit_test")
    # mixed sample: 4 wins, 6 losses → 40% win, but +2R wins vs -1R losses
    r = [2.0, 2.0, 2.0, 2.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0]
    s.r_outcomes = list(r)
    s.win_rate = 0.40  # intentionally also set the (separate) counter
    s._calculate_expected_value()
    realized_mean = sum(r) / len(r)  # (8 - 6)/10 = +0.20R
    assert math.isclose(s.expected_value_r, realized_mean, abs_tol=1e-9), (
        f"EV {s.expected_value_r} != realized mean {realized_mean}")
    assert s.expected_value_r > 0, "40%-win / +2R setup must show POSITIVE EV"


def test_setup_win_rate_no_cliff_and_ev_authority():
    svc = get_setup_quality_service()

    async def _score(win_rate, ev_r):
        return await svc.calculate_score(
            setup_type="breakout", symbol="TEST",
            tape_score=6.0, tape_confirmation=True,
            smb_grade="C", smb_5var_score=25, risk_reward=2.0,
            alert_priority="medium",
            win_rate_override=win_rate, ev_r_override=ev_r)

    # 40%-win but POSITIVE EV (+0.8R) — must NOT be auto-zeroed on win rate.
    pos = asyncio.get_event_loop().run_until_complete(_score(0.40, 0.8))
    assert pos.win_rate_score > 0, "40% win must not score 0 (cliff removed)"

    # Same setup, NEGATIVE EV (-0.5R) — EV authority must grade it lower.
    neg = asyncio.get_event_loop().run_until_complete(_score(0.40, -0.5))
    assert neg.score < pos.score, (
        f"negative-EV setup ({neg.score:.1f}) should grade below "
        f"positive-EV ({pos.score:.1f})")


if __name__ == "__main__":
    test_ev_equals_realized_mean()
    test_setup_win_rate_no_cliff_and_ev_authority()
    print("v305 TQS EV/setup regression: ALL PASS")
