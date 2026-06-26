"""2026-06-26 — strategy-autonomy recommender must NOT label negative/breakeven
expectancy as "healthy → ENABLE". Previously the (soft_r..0) band fell through to
ENABLE (e.g. backside -0.09R was recommended ENABLE). Now anything wmr < enable_r
(default 0.0) is WATCH."""

from services.strategy_autonomy import _classify

PARAMS = {"min_eff_n": 25.0, "hard_r": -0.50, "soft_r": -0.12}  # enable_r defaults to 0.0


def _cell(wmr, eff_n=30.0):
    return {"weighted_mean_r": wmr, "eff_n": eff_n}


def test_mild_bleeder_is_watch_not_enable():
    # backside-like: -0.09R, healthy sample
    rec, reason = _classify(_cell(-0.09), PARAMS, decaying=False)
    assert rec == "WATCH"
    assert "healthy" not in reason


def test_near_breakeven_negative_is_watch():
    # stage_2_breakout-like: -0.02R
    rec, _ = _classify(_cell(-0.02), PARAMS, decaying=False)
    assert rec == "WATCH"


def test_soft_hostile_still_watch():
    rec, reason = _classify(_cell(-0.20), PARAMS, decaying=False)
    assert rec == "WATCH"
    assert "soft-hostile" in reason


def test_hard_hostile_is_disable():
    rec, _ = _classify(_cell(-0.80), PARAMS, decaying=False)
    assert rec == "DISABLE"


def test_genuinely_positive_is_enable_healthy():
    rec, reason = _classify(_cell(0.15), PARAMS, decaying=False)
    assert rec == "ENABLE"
    assert "healthy" in reason


def test_positive_but_decaying_is_watch():
    rec, _ = _classify(_cell(0.15), PARAMS, decaying=True)
    assert rec == "WATCH"


def test_insufficient_sample_is_unknown():
    rec, _ = _classify(_cell(0.30, eff_n=5.0), PARAMS, decaying=False)
    assert rec == "UNKNOWN"
