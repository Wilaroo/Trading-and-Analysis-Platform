"""
v19.34.295 — per-setup size haircut (operator throttle) regression tests.

Audit Phase 5 found `squeeze` is the single biggest bleed (421 trades / 32% win /
−$24k). This adds an env-driven, DEFAULT-OFF size haircut so the operator can throttle
chronically underperforming setups WITHOUT removing them. Tests prove:
  - default (env unset) → NO haircut (deploy is behaviour-neutral / safe mid-session)
  - SETUP_SIZE_HAIRCUTS="squeeze:0.33" → squeeze sized at 0.33x, other setups untouched
  - base-keying: squeeze_long / squeeze_short both match "squeeze"
  - multiple setups + multipliers_out provenance
  - malformed env entries are ignored (never crash sizing)
"""
import types

import pytest

from services.opportunity_evaluator import OpportunityEvaluator


class _RiskParams:
    def __init__(self):
        self.max_risk_per_trade = 1000.0
        self.use_volatility_sizing = False
        self.volatility_scale_factor = 1.0
        self.starting_capital = 1_000_000.0
        self.max_position_pct = 100.0
        self.max_notional_per_trade = 0


class _FakeBot:
    def __init__(self):
        self.risk_params = _RiskParams()
        self._current_regime = None
        self._regime_position_multipliers = {}
        self._open_trades = {}
        self._db = None
        self.db = None


@pytest.fixture(autouse=True)
def _neutralize_safety_cap(monkeypatch):
    cfg = types.SimpleNamespace(max_symbol_exposure_usd=0)
    guard = types.SimpleNamespace(config=cfg)
    monkeypatch.setattr(
        "services.safety_guardrails.get_safety_guardrails",
        lambda: guard, raising=False,
    )
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0")
    # cold-start must not interfere: pass proven_outcomes=None so it never fires
    monkeypatch.delenv("COLD_START_SIZE_MULT", raising=False)


def _size(setup_type, out=None):
    from services.trading_bot_service import TradeDirection
    ev = OpportunityEvaluator()
    return ev.calculate_position_size(
        100.0, 99.0, TradeDirection.LONG, _FakeBot(), atr=2.0, atr_percent=2.0,
        symbol=None, grade="A", setup_type=setup_type, proven_outcomes=None,
        multipliers_out=out,
    )[0]


def test_default_off_no_haircut(monkeypatch):
    monkeypatch.delenv("SETUP_SIZE_HAIRCUTS", raising=False)
    assert _size("squeeze_long") == 1000  # full size, env unset → no-op


def test_squeeze_haircut_applied(monkeypatch):
    monkeypatch.setenv("SETUP_SIZE_HAIRCUTS", "squeeze:0.33")
    assert _size("squeeze_long") == pytest.approx(330, abs=2)
    assert _size("squeeze_short") == pytest.approx(330, abs=2)  # base-keying


def test_other_setups_untouched(monkeypatch):
    monkeypatch.setenv("SETUP_SIZE_HAIRCUTS", "squeeze:0.33")
    assert _size("daily_breakout") == 1000  # not in the map → full size


def test_multiple_setups(monkeypatch):
    monkeypatch.setenv("SETUP_SIZE_HAIRCUTS", "squeeze:0.33,vwap_fade:0.5")
    assert _size("squeeze_long") == pytest.approx(330, abs=2)
    assert _size("vwap_fade_short") == pytest.approx(500, abs=2)
    assert _size("gap_fade") == 1000


def test_multipliers_out_provenance(monkeypatch):
    monkeypatch.setenv("SETUP_SIZE_HAIRCUTS", "squeeze:0.33")
    out = {}
    _size("squeeze_long", out=out)
    assert out["setup_haircut_applied"] is True
    assert out["setup_haircut_multiplier"] == pytest.approx(0.33, abs=0.01)
    out2 = {}
    _size("daily_breakout", out=out2)
    assert out2["setup_haircut_applied"] is False
    assert out2["setup_haircut_multiplier"] == 1.0


def test_malformed_env_ignored(monkeypatch):
    # garbage entries, out-of-range, missing colon → ignored, never crash
    monkeypatch.setenv("SETUP_SIZE_HAIRCUTS", "garbage,squeeze:abc,foo:2.0,squeeze:0.5")
    assert _size("squeeze_long") == pytest.approx(500, abs=2)  # last valid wins
    assert _size("foo_long") == 1000  # 2.0 out of range → ignored
