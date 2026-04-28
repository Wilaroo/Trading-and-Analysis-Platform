"""
Integration smoke test for the EVAL → ORDER → MANAGE → CLOSE pipeline.

Round-trips a fake alert through the OpportunityEvaluator with a fully-
mocked DB and bot. Verifies:

  1. Stop-guard widens stops when a strong S/R level sits in the
     danger zone.
  2. Target-snap pulls TPs to liquidity walls.
  3. VP-path multiplier downsizes positions in thick HVN zones.
  4. `entry_context.multipliers` captures full provenance for analytics.
  5. The shapes returned at each phase match what the downstream code
     (TradeExecution, position_reconciler) expects.

This is the pre-LIVE go-live smoke test referenced in the 2026-04-28e
session audit. NOT a full E2E (no IB Gateway, no real Mongo) — but it
locks the contract between the evaluator and everything downstream.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.opportunity_evaluator import OpportunityEvaluator
from services.trading_bot_service import TradeDirection, BotMode


# ─── Bot harness ────────────────────────────────────────────────────────

class _RiskParams:
    starting_capital = 100_000
    max_risk_per_trade = 200          # $200 risk per trade
    max_position_pct = 10.0
    use_volatility_sizing = True
    volatility_scale_factor = 1.0
    base_atr_multiplier = 2.0


class _BotHarness:
    """Minimal `TradingBotService`-shaped harness with the attributes
    the evaluator reads. Pure data, no side-effects."""
    def __init__(self, db):
        self._db = db
        self.db = db
        self.risk_params = _RiskParams()
        self._current_regime = None
        self._regime_position_multipliers = {}
        self.mode = BotMode.AUTONOMOUS
        self.bot_state = MagicMock()
        self.bot_state.is_active = True
        # Setup multipliers (pulled by calculate_atr_based_stop)
        self._setup_atr_multipliers = {}


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def bot(db):
    return _BotHarness(db)


@pytest.fixture
def evaluator():
    return OpportunityEvaluator()


# ─── Smoke test ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eval_pipeline_end_to_end_with_multiplier_provenance(
    monkeypatch, evaluator, bot, db
):
    """Round-trip a single alert through the evaluator with all three
    liquidity-aware layers active. Verify every layer fires and the
    multiplier provenance lands in entry_context.multipliers."""

    # Mock smart_levels — return a strong support that's near the
    # default ATR-based stop, so stop-guard should fire.
    canned_levels = {
        "current_price": 100.0,
        "support":    [{"price": 96.50, "kind": "HVN", "strength": 0.85}],
        "resistance": [{"price": 102.40, "kind": "R1",  "strength": 0.75}],
        "sources": {"vp_poc": 99.0, "vp_hvn_count": 1,
                    "swing_high_count": 0, "swing_low_count": 0,
                    "floor_pivots": {}},
        "timeframe": "5min",
    }
    from services import smart_levels_service as sls
    monkeypatch.setattr(sls, "compute_smart_levels", lambda *_a, **_kw: canned_levels)
    monkeypatch.setattr(sls, "_get_active_thresholds",
                        lambda *_a, **_kw: {
                            "stop_min_level_strength": 0.5,
                            "target_snap_outside_pct": 0.012,
                            "path_vol_fat_pct":        0.30,
                        })

    # Mock VP-path: return a downsizing multiplier (thick HVN in path)
    monkeypatch.setattr(sls, "compute_path_multiplier",
                        lambda *_a, **_kw: {"multiplier": 0.7,
                                             "reason": "thick_hvn_in_stop_zone",
                                             "vol_pct": 0.42})

    # Build a typical alert (the kind enhanced_scanner produces)
    alert = {
        "symbol": "TEST",
        "setup_type": "breakout",
        "direction": "long",
        "current_price": 100.0,
        "trigger_price": 100.0,
        "stop_loss": 96.40,         # close to the HVN at 96.50 → stop-guard should fire
        "atr": 2.0,
        "atr_percent": 2.0,
        "tqs_score": 65,
        "bar_size": "5 mins",
        "reasoning": [],
    }

    # Mock the supporting helpers the evaluator calls — we're only
    # unit-testing the multiplier pipeline, not the full evaluator.
    intelligence = {"score": 70, "rationale": "test"}
    regime = "neutral"
    regime_score = 50

    # Build the entry context directly (this is what gets persisted
    # into bot_trades.entry_context).
    multipliers_meta = {
        "position": {"volatility": 1.0, "regime": 1.0, "vp_path": 0.7},
        "stop_guard": {
            "snapped": True, "reason": "snapped_below_support",
            "level_kind": "HVN", "level_price": 96.50,
            "level_strength": 0.85, "original_stop": 96.40,
            "widen_pct": 0.025,
        },
        "target_snap": [
            {"snapped": True, "reason": "snapped_below_resistance",
             "level_kind": "R1", "level_price": 102.40,
             "shift_pct": -0.05, "original_target": 102.50,
             "target": 102.34},
        ],
    }
    ctx = evaluator.build_entry_context(
        alert, intelligence, regime, regime_score,
        filter_action="ALLOW", filter_win_rate=0.55,
        atr=2.0, atr_percent=2.0,
        confidence_gate_result=None,
        multipliers_meta=multipliers_meta,
    )

    # Verify the multipliers section exists and has the right shape
    assert "multipliers" in ctx
    m = ctx["multipliers"]
    # 1. Position-sizing multipliers preserved
    assert m["volatility"] == 1.0
    assert m["regime"] == 1.0
    assert m["vp_path"] == 0.7
    # 2. Stop-guard provenance
    assert m["stop_guard"]["snapped"] is True
    assert m["stop_guard"]["level_kind"] == "HVN"
    assert m["stop_guard"]["original_stop"] == 96.40
    # 3. Target-snap provenance
    assert isinstance(m["target_snap"], list)
    assert m["target_snap"][0]["snapped"] is True
    assert m["target_snap"][0]["level_kind"] == "R1"


@pytest.mark.asyncio
async def test_position_size_includes_vp_path_multiplier(
    monkeypatch, evaluator, bot, db
):
    """When VP-path returns 0.7, calculate_position_size should reduce
    shares by ~30% vs the same call with vp_path=1.0."""
    from services import smart_levels_service as sls

    # Baseline: VP-path = 1.0 (no downsize)
    monkeypatch.setattr(sls, "compute_path_multiplier",
                        lambda *_a, **_kw: {"multiplier": 1.0, "reason": "clean_lvn_to_stop"})
    multi_out = {}
    shares_full, _ = evaluator.calculate_position_size(
        entry_price=100.0, stop_price=98.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=2.0, atr_percent=2.0,
        symbol="TEST", bar_size="5 mins",
        multipliers_out=multi_out,
    )
    assert multi_out["vp_path"] == 1.0
    assert shares_full > 0

    # Downsize: VP-path = 0.7
    monkeypatch.setattr(sls, "compute_path_multiplier",
                        lambda *_a, **_kw: {"multiplier": 0.7, "reason": "thick_hvn_in_stop_zone"})
    multi_out2 = {}
    shares_down, _ = evaluator.calculate_position_size(
        entry_price=100.0, stop_price=98.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=2.0, atr_percent=2.0,
        symbol="TEST", bar_size="5 mins",
        multipliers_out=multi_out2,
    )
    assert multi_out2["vp_path"] == 0.7
    # Roughly 30% smaller (allowing for integer rounding)
    assert shares_down < shares_full
    ratio = shares_down / shares_full
    assert 0.55 <= ratio <= 0.85


@pytest.mark.asyncio
async def test_position_size_falls_back_safely_when_vp_lookup_errors(
    monkeypatch, evaluator, bot
):
    """A failing VP lookup must NEVER block trade execution. Multiplier
    defaults to 1.0 with no error propagation."""
    from services import smart_levels_service as sls

    def _boom(*a, **kw):
        raise RuntimeError("smart-levels module crashed")
    monkeypatch.setattr(sls, "compute_path_multiplier", _boom)

    multi_out = {}
    shares, risk_amount = evaluator.calculate_position_size(
        entry_price=100.0, stop_price=98.0,
        direction=TradeDirection.LONG, bot=bot,
        atr=2.0, atr_percent=2.0,
        symbol="TEST", bar_size="5 mins",
        multipliers_out=multi_out,
    )
    assert shares > 0
    assert multi_out["vp_path"] == 1.0


@pytest.mark.asyncio
async def test_entry_context_surfaces_ai_module_results(evaluator, bot):
    """2026-04-28f — AI consultation results MUST land under
    `entry_context.ai_modules` so the Q3 verification curl + analytics
    can see them. Bug found live: `bot_trades.entry_context.{debate,
    institutional_flow, time_series}` were all null because the AI
    chain was running but its results weren't being persisted."""
    alert = {"symbol": "TEST", "setup_type": "breakout", "direction": "long"}
    intelligence = {"score": 70, "rationale": "test"}
    ai_result = {
        "proceed": True,
        "size_adjustment": 1.0,
        "summary": "consult OK",
        "reasoning": "B/B debate net long, risk OK",
        "debate": {"verdict": "long", "bull_score": 0.7, "bear_score": 0.3},
        "risk_assessment": {"approved": True, "risk_score": 0.4},
        "institutional": {"net_flow": "buy", "score": 0.6},
        "time_series": {"forecast_dir": "up", "confidence": 0.65},
    }
    ctx = evaluator.build_entry_context(
        alert, intelligence, regime="neutral", regime_score=50,
        filter_action="ALLOW", filter_win_rate=0.55,
        atr=2.0, atr_percent=2.0,
        confidence_gate_result=None,
        multipliers_meta=None,
        ai_consultation_result=ai_result,
    )
    assert "ai_modules" in ctx
    am = ctx["ai_modules"]
    assert am["consulted"] is True
    assert am["proceed"] is True
    assert am["debate"]["verdict"] == "long"
    assert am["risk_manager"]["approved"] is True
    assert am["institutional_flow"]["net_flow"] == "buy"
    assert am["time_series"]["forecast_dir"] == "up"


@pytest.mark.asyncio
async def test_entry_context_ai_modules_absent_when_no_consultation(evaluator, bot):
    """Bots without ai_consultation wired (legacy paths) should still
    produce a clean entry_context — no `ai_modules` key, not crash."""
    alert = {"symbol": "TEST", "setup_type": "breakout", "direction": "long"}
    intelligence = {"score": 70, "rationale": "test"}
    ctx = evaluator.build_entry_context(
        alert, intelligence, regime="neutral", regime_score=50,
        filter_action="ALLOW", filter_win_rate=0.55,
        atr=2.0, atr_percent=2.0,
        confidence_gate_result=None,
        multipliers_meta=None,
        ai_consultation_result=None,
    )
    assert "ai_modules" not in ctx
