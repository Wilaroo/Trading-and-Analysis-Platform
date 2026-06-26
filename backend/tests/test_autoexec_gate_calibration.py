"""
Auto-exec gate calibration (#3 tape scoping + #4 per-style EV floors).

Verifies the env-gated helpers added to EnhancedScanner are correct AND that
the DEFAULT (flags OFF) reproduces legacy behavior exactly:
  #3  _alert_requires_tape  — OFF: tape required for all; ON: scalp/intraday only.
  #4  _resolve_min_ev_r     — OFF: scalar floor; ON: per-style override.
Pure class/static helpers — no scanner instantiation (and no IB/DB) needed.
"""
from types import SimpleNamespace
from services.enhanced_scanner import EnhancedBackgroundScanner as ES


def _alert(style):
    return SimpleNamespace(trade_style=style)


# ── #3 — tape-confirmation scoping ──

def test_tape_required_for_all_when_flag_off():
    for style in ("scalp", "intraday", "swing", "multi_day", "position", "investment", None, ""):
        assert ES._alert_requires_tape(_alert(style), False) is True


def test_tape_required_only_for_scalp_intraday_when_flag_on():
    assert ES._alert_requires_tape(_alert("scalp"), True) is True
    assert ES._alert_requires_tape(_alert("intraday"), True) is True
    assert ES._alert_requires_tape(_alert("INTRADAY"), True) is True  # case-insensitive
    for style in ("swing", "multi_day", "position", "investment", "", None):
        assert ES._alert_requires_tape(_alert(style), True) is False


def test_style_of_normalizes():
    assert ES._style_of(_alert("  SWING ")) == "swing"
    assert ES._style_of(SimpleNamespace()) == ""


# ── #4 — per-style auto-exec EV-R floor ──

_OVR = {"scalp": 0.15, "intraday": 0.12, "multi_day": 0.05,
        "swing": 0.05, "position": 0.03, "investment": 0.03}


def test_ev_floor_is_scalar_when_flag_off():
    for style in _OVR:
        assert ES._resolve_min_ev_r(style, 0.10, False, _OVR) == 0.10


def test_ev_floor_per_style_when_flag_on():
    assert ES._resolve_min_ev_r("scalp", 0.10, True, _OVR) == 0.15
    assert ES._resolve_min_ev_r("intraday", 0.10, True, _OVR) == 0.12
    assert ES._resolve_min_ev_r("swing", 0.10, True, _OVR) == 0.05
    assert ES._resolve_min_ev_r("position", 0.10, True, _OVR) == 0.03


def test_ev_floor_unknown_style_falls_back_to_base():
    assert ES._resolve_min_ev_r("not_a_style", 0.10, True, _OVR) == 0.10
    assert ES._resolve_min_ev_r(None, 0.10, True, _OVR) == 0.10


# ── env helpers ──

def test_env_flag(monkeypatch):
    monkeypatch.setenv("X_FLAG", "on")
    assert ES._env_flag("X_FLAG", False) is True
    monkeypatch.setenv("X_FLAG", "0")
    assert ES._env_flag("X_FLAG", True) is False
    monkeypatch.delenv("X_FLAG", raising=False)
    assert ES._env_flag("X_FLAG", False) is False


def test_env_float(monkeypatch):
    monkeypatch.setenv("X_F", "0.22")
    assert ES._env_float("X_F", 0.1) == 0.22
    monkeypatch.setenv("X_F", "garbage")
    assert ES._env_float("X_F", 0.1) == 0.1
    monkeypatch.delenv("X_F", raising=False)
    assert ES._env_float("X_F", 0.1) == 0.1
