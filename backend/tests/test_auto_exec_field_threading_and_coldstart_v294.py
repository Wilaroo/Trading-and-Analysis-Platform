"""
v19.34.294 — Audit Phase 3 (Take/Deny) regression tests.

Covers two fixes shipped together:

  T1 — auto-exec field threading: the scanner→bot trade-submission boundary
       must carry the REAL LiveAlert decision inputs (tqs_grade, tqs_score,
       trade_style, atr, priority, …) instead of fabricating score=80 and
       letting the evaluator fall back to D-grade / synthetic-ATR defaults.

  P2-B — cold-start size haircut: setups with < COLD_START_MIN_OUTCOMES proven
       outcomes are sized at COLD_START_SIZE_MULT (default 0.33x). Only applies
       when `proven_outcomes` is supplied (auto-exec path); manual/legacy
       callers (None) are unaffected.
"""
import asyncio
import os
import types

import pytest

from services.opportunity_evaluator import (
    OpportunityEvaluator,
    _resolve_grade_multiplier,
)
from services.scanner_integration import ScannerIntegration


# ─────────────────────────── helpers / fakes ───────────────────────────

class _RiskParams:
    def __init__(self):
        self.max_risk_per_trade = 1000.0
        self.use_volatility_sizing = False
        self.volatility_scale_factor = 1.0
        self.starting_capital = 1_000_000.0
        self.max_position_pct = 100.0
        self.max_notional_per_trade = 0


class _FakeBot:
    """Minimal bot stub for calculate_position_size (no DB, no IB)."""
    def __init__(self):
        self.risk_params = _RiskParams()
        self._current_regime = None
        self._regime_position_multipliers = {}
        self._open_trades = {}
        self._db = None
        self.db = None


@pytest.fixture(autouse=True)
def _neutralize_safety_cap(monkeypatch):
    """Disable the downstream safety max_symbol_exposure clamp so the tests
    isolate the cold-start math (cap=0 → clamp skipped per the sizer)."""
    cfg = types.SimpleNamespace(max_symbol_exposure_usd=0)
    guard = types.SimpleNamespace(config=cfg)
    monkeypatch.setattr(
        "services.safety_guardrails.get_safety_guardrails",
        lambda: guard,
        raising=False,
    )
    # Keep the guardrail %-pre-clamp out of the way too.
    monkeypatch.delenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", raising=False)
    monkeypatch.setenv("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", "0")


def _size(proven_outcomes, *, grade="A", monkeyenv=None):
    ev = OpportunityEvaluator()
    from services.trading_bot_service import TradeDirection
    bot = _FakeBot()
    # entry/stop chosen so risk_per_share = 1.0 and no cap binds.
    shares, risk = ev.calculate_position_size(
        entry_price=100.0, stop_price=99.0, direction=TradeDirection.LONG,
        bot=bot, atr=2.0, atr_percent=2.0,
        symbol=None,  # None → VP + MR lookups skip cleanly
        grade=grade,
        proven_outcomes=proven_outcomes,
    )
    return shares


# ─────────────────────────── P2-B cold-start ───────────────────────────

def test_cold_start_haircut_default_third(monkeypatch):
    """< 20 proven outcomes → ~0.33x the full size."""
    monkeypatch.delenv("COLD_START_SIZE_MULT", raising=False)
    monkeypatch.delenv("COLD_START_MIN_OUTCOMES", raising=False)
    full = _size(proven_outcomes=50)     # proven → full size
    cold = _size(proven_outcomes=5)      # unproven → haircut
    assert full == 1000
    assert cold == pytest.approx(330, abs=2)
    assert cold / full == pytest.approx(0.33, abs=0.01)


def test_cold_start_not_applied_when_proven(monkeypatch):
    """>= threshold → no haircut (equals the None/legacy baseline)."""
    monkeypatch.delenv("COLD_START_SIZE_MULT", raising=False)
    monkeypatch.delenv("COLD_START_MIN_OUTCOMES", raising=False)
    assert _size(proven_outcomes=20) == _size(proven_outcomes=None)


def test_cold_start_skipped_for_legacy_callers():
    """proven_outcomes=None (manual/legacy) → never haircut."""
    assert _size(proven_outcomes=None) == 1000


def test_cold_start_env_override(monkeypatch):
    """COLD_START_SIZE_MULT + COLD_START_MIN_OUTCOMES are honoured."""
    monkeypatch.setenv("COLD_START_SIZE_MULT", "0.5")
    monkeypatch.setenv("COLD_START_MIN_OUTCOMES", "10")
    assert _size(proven_outcomes=3) == pytest.approx(500, abs=2)   # 0.5x
    assert _size(proven_outcomes=15) == 1000                       # >=10 → full


def test_cold_start_disabled_when_mult_one(monkeypatch):
    monkeypatch.setenv("COLD_START_SIZE_MULT", "1.0")
    assert _size(proven_outcomes=1) == 1000


def test_multipliers_out_records_cold_start(monkeypatch):
    monkeypatch.delenv("COLD_START_SIZE_MULT", raising=False)
    ev = OpportunityEvaluator()
    from services.trading_bot_service import TradeDirection
    out = {}
    ev.calculate_position_size(
        100.0, 99.0, TradeDirection.LONG, _FakeBot(), atr=2.0, atr_percent=2.0,
        symbol=None, grade="A", multipliers_out=out, proven_outcomes=5,
    )
    assert out["cold_start_applied"] is True
    assert out["cold_start_multiplier"] == pytest.approx(0.33, abs=0.01)
    assert out["proven_outcomes"] == 5


# ─────────────────────── T1: grade-default regression ───────────────────

def test_missing_grade_defaults_to_D_015():
    """Documents the bug T1 fixes: a missing grade sizes as D (0.15x).
    Threading the real grade (next test) is what avoids this on auto-exec."""
    mult_none, norm_none = _resolve_grade_multiplier(None)
    assert norm_none == "D"
    assert mult_none == pytest.approx(0.15, abs=0.001)


def test_threaded_A_grade_full_size():
    mult_a, norm_a = _resolve_grade_multiplier("A")
    assert norm_a == "A"
    assert mult_a == pytest.approx(1.0, abs=0.001)
    # A-grade sizes ~6.7x a D-grade — the exact distortion T1 removes.
    assert _size(proven_outcomes=None, grade="A") > _size(proven_outcomes=None, grade="D")


# ───────────────── T1: scanner_integration field threading ───────────────

def test_submit_trade_threads_real_fields():
    """submit_trade_from_scanner must pass the rich fields into the alert
    dict the evaluator reads — not the old fabricated score=80 stub."""
    captured = {}

    class _CaptureBot:
        from services.trading_bot_service import BotMode as _BM
        _mode = None

        async def _evaluate_opportunity(self, alert):
            captured.update(alert)
            return None  # short-circuit before execution

    bot = _CaptureBot()
    si = ScannerIntegration()
    trade_request = {
        "symbol": "NVDA", "direction": "long", "setup_type": "vwap_bounce_long",
        "entry_price": 120.0, "stop_loss": 118.0, "target": 126.0,
        "alert_id": "abc", "source": "scanner_auto_execute",
        "tqs_grade": "A", "tqs_score": 88.0, "tape_score": 8.0,
        "tape_confirmation": True, "risk_reward": 3.0, "priority": "high",
        "atr": 1.9, "atr_percent": 1.6, "trade_style": "intraday",
        "smb_grade": "A", "proven_outcomes": 7,
    }
    asyncio.get_event_loop().run_until_complete(
        si.submit_trade_from_scanner(trade_request, bot)
    )
    # Real values threaded (not the legacy synthetic 80):
    assert captured["score"] == 88           # int(tqs_score), not 80
    assert captured["tqs_grade"] == "A"
    assert captured["trade_style"] == "intraday"
    assert captured["atr"] == 1.9
    assert captured["priority"] == "high"
    assert captured["proven_outcomes"] == 7


def test_submit_trade_falls_back_to_80_when_no_tqs():
    """Legacy/manual callers without tqs_score keep the score=80 stub."""
    captured = {}

    class _CaptureBot:
        _mode = None

        async def _evaluate_opportunity(self, alert):
            captured.update(alert)
            return None

    si = ScannerIntegration()
    asyncio.get_event_loop().run_until_complete(
        si.submit_trade_from_scanner(
            {"symbol": "F", "direction": "long", "setup_type": "x",
             "entry_price": 10.0, "stop_loss": 9.5, "target": 11.0,
             "alert_id": "z"},
            _CaptureBot(),
        )
    )
    assert captured["score"] == 80
    assert captured.get("tqs_grade") in (None, "")
    assert captured.get("proven_outcomes") is None
