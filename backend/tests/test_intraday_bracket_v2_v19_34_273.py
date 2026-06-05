"""
test_intraday_bracket_v2_v19_34_273.py — Issue 2

Locks INTRADAY_BRACKET_V2: smart_stop bracket geometry is driven by the SSOT
exit_archetype (runner / target / swing_hold / position_hold), and the scale-out
plan leaves a trailing runner only for runner-class archetypes. Pure logic.
"""
import importlib
import os

import pytest


def _svc():
    import services.smart_stop_service as ss
    importlib.reload(ss)
    return ss


def test_runner_archetype_for_momentum(monkeypatch):
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "1")
    ss = _svc()
    svc = ss.SmartStopService()
    # tidal_wave (m8) → momentum/runner; fading_bounce → fade/target
    assert svc._get_setup_rules("tidal_wave").setup_type == "runner"
    assert svc._get_setup_rules("fading_bounce").setup_type == "target"
    assert svc._get_setup_rules("breakout").setup_type == "runner"
    assert svc._get_setup_rules("vwap_fade_long").setup_type == "target"


def test_runner_plan_reserves_trailing_remainder(monkeypatch):
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "1")
    ss = _svc()
    svc = ss.SmartStopService()
    rules = svc._get_setup_rules("tidal_wave")  # runner
    plan = svc._create_scale_out_plan(entry=100.0, direction="long", atr=1.0,
                                      rules=rules, position_size=1000)
    # last leg must be a trailing runner with no fixed target
    runner = plan[-1]
    assert runner.get("runner") is True
    assert runner["target_price"] is None
    assert runner["exit_pct"] == 0.25
    # exit fractions sum to 1.0
    assert round(sum(p["exit_pct"] for p in plan), 4) == 1.0


def test_target_plan_full_exit_no_runner(monkeypatch):
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "1")
    ss = _svc()
    svc = ss.SmartStopService()
    rules = svc._get_setup_rules("fading_bounce")  # target
    plan = svc._create_scale_out_plan(entry=50.0, direction="short", atr=0.5,
                                      rules=rules, position_size=400)
    assert not any(p.get("runner") for p in plan)        # no runner
    assert all(p["target_price"] is not None for p in plan)  # every leg has a fixed target
    assert len(plan) == 2                                  # 2-wave bracket
    assert round(sum(p["exit_pct"] for p in plan), 4) == 1.0  # full exit


def test_legacy_fallback_when_disabled(monkeypatch):
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "0")
    ss = _svc()
    svc = ss.SmartStopService()
    # flag off → legacy substring map; "momentum" matches the legacy momentum rule
    r = svc._get_setup_rules("momentum")
    assert r.setup_type == "momentum"
    # legacy plan never reserves a runner
    plan = svc._create_scale_out_plan(100.0, "long", 1.0, r, 1000)
    assert not any(p.get("runner") for p in plan)


def test_legacy_plan_unchanged_for_zero_runner(monkeypatch):
    """Backward-compat: a rule with leave_runner_pct=0 keeps the old plan shape."""
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "0")
    ss = _svc()
    svc = ss.SmartStopService()
    r = svc.setup_rules["breakout"]  # legacy rule, leave_runner_pct defaults 0
    plan = svc._create_scale_out_plan(100.0, "long", 1.0, r, 1000)
    # 3 targets → 0.25, 0.25, 0.50 (final takes remainder), full exit, no runner
    assert [p["exit_pct"] for p in plan] == [0.25, 0.25, 0.5]
    assert round(sum(p["exit_pct"] for p in plan), 4) == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
