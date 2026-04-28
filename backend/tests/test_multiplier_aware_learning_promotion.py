"""
Regression tests for the multiplier-aware learning loop + strategy
promotion shipped 2026-04-28f.

Locks two contracts:
  1. `LearningLoopService.get_multiplier_aware_stats` correctly slices
     `bot_trades` into fired/not_fired cohorts per layer and computes
     lift_r as `mean_r_fired - mean_r_not_fired`.
  2. `StrategyPerformance.meets_requirements` flags multiplier-
     dependent edge: when win rate-with-multipliers is >20pp higher
     than win rate-without, an issue is added to the promotion
     check so that strategy can't auto-promote on inflated stats.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.learning_loop_service import LearningLoopService
from services.strategy_promotion_service import (
    StrategyPerformance, StrategyPhase, PhaseRequirements,
)


# ─── LearningLoopService.get_multiplier_aware_stats ─────────────────────

def _trade(*, r=1.0, sg=False, ts=False, vp=1.0, days_ago=1):
    """Build a synthetic bot_trades doc with the multiplier metadata
    we need."""
    ec = {"multipliers": {"vp_path": vp}}
    if sg:
        ec["multipliers"]["stop_guard"] = {"snapped": True}
    if ts:
        ec["multipliers"]["target_snap"] = [{"snapped": True}]
    return {
        "realized_r_multiple": r,
        "entry_context": ec,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }


def _make_loop(trades):
    loop = LearningLoopService.__new__(LearningLoopService)
    loop._trade_outcomes_col = MagicMock()
    db = MagicMock()
    db["bot_trades"].find = lambda *_a, **_kw: iter(list(trades))
    loop._db = db
    return loop


@pytest.mark.asyncio
async def test_multiplier_aware_stats_buckets_layers_correctly():
    trades = [
        _trade(r=2.0, sg=True),
        _trade(r=1.5, sg=True),
        _trade(r=-0.5),                      # no layers fired
        _trade(r=2.0, ts=True),
        _trade(r=0.5, vp=0.7),               # vp downsized
    ]
    loop = _make_loop(trades)
    out = await loop.get_multiplier_aware_stats(days_back=30)
    # stop_guard fired on 2 trades, mean R 1.75
    assert out["stop_guard"]["fired"]["n"] == 2
    assert out["stop_guard"]["fired"]["mean_r"] == 1.75
    # target_snap fired on 1
    assert out["target_snap"]["fired"]["n"] == 1
    # vp downsized on 1
    assert out["vp_path"]["downsized"]["n"] == 1
    # not-fired cohorts: stop_guard 3, target_snap 4, vp_path 4
    assert out["stop_guard"]["not_fired"]["n"] == 3
    assert out["target_snap"]["not_fired"]["n"] == 4
    assert out["vp_path"]["full_size"]["n"] == 4


@pytest.mark.asyncio
async def test_multiplier_aware_stats_computes_lift_r():
    trades = [
        _trade(r=2.0, sg=True), _trade(r=2.0, sg=True),
        _trade(r=0.0), _trade(r=0.0),
    ]
    loop = _make_loop(trades)
    out = await loop.get_multiplier_aware_stats(days_back=30)
    assert out["stop_guard"]["lift_r"] == 2.0   # 2.0 fired - 0.0 not


@pytest.mark.asyncio
async def test_multiplier_aware_stats_lift_none_when_one_cohort_empty():
    trades = [_trade(r=2.0, sg=True), _trade(r=1.5, sg=True)]
    loop = _make_loop(trades)
    out = await loop.get_multiplier_aware_stats(days_back=30)
    # No not-fired cohort → lift_r should remain None
    assert out["stop_guard"]["lift_r"] is None


@pytest.mark.asyncio
async def test_multiplier_aware_stats_skips_trades_with_no_r():
    trades = [_trade(r=None, sg=True), _trade(r=2.0, sg=True)]
    loop = _make_loop(trades)
    out = await loop.get_multiplier_aware_stats(days_back=30)
    assert out["stop_guard"]["fired"]["n"] == 1


@pytest.mark.asyncio
async def test_multiplier_aware_stats_no_db_returns_empty():
    loop = LearningLoopService.__new__(LearningLoopService)
    loop._db = None
    loop._trade_outcomes_col = None
    out = await loop.get_multiplier_aware_stats(days_back=30)
    assert out["stop_guard"]["fired"] is None


# ─── StrategyPerformance.meets_requirements multiplier-guard ────────────

def _strong_perf_with_cohorts(*, with_wins=20, with_n=20,
                              without_wins=4, without_n=10):
    """Build a StrategyPerformance that passes all the standard
    requirements but has the cohort split we want to test."""
    perf = StrategyPerformance(
        strategy_name="test_setup",
        phase=StrategyPhase.PAPER,
        total_trades=30,
        winning_trades=24,
        losing_trades=6,
        win_rate=0.80,
        avg_r_multiple=1.5,
        total_r=12.0,
        profit_factor=2.5,
        max_drawdown_pct=0.05,
        days_in_phase=10,
    )
    perf.multiplier_cohorts = {
        "with_multipliers":    {"n": with_n,    "wins": with_wins},
        "without_multipliers": {"n": without_n, "wins": without_wins},
    }
    return perf


def _basic_req():
    return PhaseRequirements(
        min_trades=10, min_win_rate=0.50, min_avg_r=0.5,
        min_profit_factor=1.5, max_drawdown_pct=0.20,
        min_days_in_phase=5,
    )


def test_meets_requirements_flags_multiplier_dependent_edge():
    """WR 100% with multipliers vs 40% without → 60pp gap → flag."""
    perf = _strong_perf_with_cohorts(with_wins=20, with_n=20,
                                      without_wins=4, without_n=10)
    ok, issues = perf.meets_requirements(_basic_req())
    assert ok is False
    assert any("Multiplier-dependent edge" in i for i in issues)


def test_meets_requirements_passes_when_cohorts_agree():
    """WR 80% with multipliers vs 70% without → 10pp gap → pass."""
    perf = _strong_perf_with_cohorts(with_wins=16, with_n=20,
                                      without_wins=7, without_n=10)
    ok, _ = perf.meets_requirements(_basic_req())
    assert ok is True


def test_meets_requirements_skips_check_when_without_cohort_too_small():
    """If `without_multipliers` cohort has < 5 trades, the guard is
    skipped — too noisy to act on."""
    perf = _strong_perf_with_cohorts(with_wins=20, with_n=20,
                                      without_wins=0, without_n=3)
    ok, issues = perf.meets_requirements(_basic_req())
    assert ok is True   # guard skipped
    assert not any("Multiplier-dependent edge" in i for i in issues)


def test_meets_requirements_handles_missing_cohorts():
    """Older strategies without the cohort field should pass cleanly."""
    perf = StrategyPerformance(
        strategy_name="legacy",
        phase=StrategyPhase.PAPER,
        total_trades=30, winning_trades=20, losing_trades=10,
        win_rate=0.67, avg_r_multiple=1.5, total_r=10,
        profit_factor=2.0, max_drawdown_pct=0.10, days_in_phase=10,
    )
    perf.multiplier_cohorts = {}
    ok, _ = perf.meets_requirements(_basic_req())
    assert ok is True
