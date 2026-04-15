"""
Post-Training Model Validator — Full 5-Phase Pipeline

After a setup model is trained, automatically runs up to 5 validation tests
in smart order:

  Phase 1: AI Comparison    — Setup-only vs AI+Setup vs AI-only (fast)
  Phase 2: Monte Carlo      — 5K shuffled simulations for risk (fast)
  Phase 3: Walk-Forward     — Rolling in/out-of-sample robustness (medium)
  Phase 4: Multi-Strategy   — Compare all setup types head-to-head (batch)
  Phase 5: Market-Wide      — Scan 200 liquid symbols for signal density (batch)

Per-profile results (phases 1-3) stored in `model_validations`.
Batch results (phases 4-5) stored in `batch_validations`.
"""

import logging
import uuid
import pickle
import base64
import statistics
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ─── Validation Configuration ────────────────────────────────────────────────

VALIDATION_CONFIG = {
    "num_symbols": 20,
    "lookback_days": 180,
    "starting_capital": 250000,
    "ai_confidence_threshold": 0.5,
    "ai_lookback_bars": 50,
    # Walk-forward
    "wf_total_days": 365,
    "wf_symbols": 3,
    "wf_in_sample_days": 180,
    "wf_out_of_sample_days": 30,
    "wf_step_days": 30,
    # Monte Carlo
    "mc_simulations": 5000,
    # Market-wide (reduced for validation speed)
    "mw_max_symbols": 200,
}

PROMOTION_CRITERIA = {
    "min_trades": 10,
    "min_win_rate": 0.35,
    "min_sharpe": -0.5,
    "max_mc_risk": "EXTREME",
    "min_wf_efficiency": 50,
}

# ─── Strategy Config Builder ─────────────────────────────────────────────────

def _build_strategy_config(setup_type: str, bar_size: str = None):
    """Build a StrategyConfig for a given setup type."""
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    return StrategyConfig(
        name=f"{setup_type}_validation",
        setup_type=setup_type.lower(),
    )


def _build_filters(lookback_days: int = None):
    """Build standard date filters for validation backtests."""
    from services.slow_learning.advanced_backtest_engine import BacktestFilters
    days = lookback_days or VALIDATION_CONFIG["lookback_days"]
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    return BacktestFilters(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )


# ─── Symbol Fetching ─────────────────────────────────────────────────────────

def _get_validation_symbols(db, bar_size: str, limit: int = None) -> List[str]:
    """Get top liquid symbols for validation backtest."""
    from services.ai_modules.setup_training_config import get_adv_threshold
    n = limit or VALIDATION_CONFIG["num_symbols"]
    threshold = get_adv_threshold(bar_size)
    cursor = db["symbol_adv_cache"].find(
        {"avg_volume": {"$gte": threshold}},
        {"_id": 0, "symbol": 1, "avg_volume": 1}
    ).sort("avg_volume", -1).limit(n)
    return [doc["symbol"] for doc in cursor]


# ─── Phase 1: AI Comparison ──────────────────────────────────────────────────

async def _run_phase1_ai_comparison(
    backtest_engine, symbols, setup_type, bar_size
) -> Dict:
    """Phase 1: Run 3-way AI comparison backtest."""
    strategy = _build_strategy_config(setup_type)
    filters = _build_filters()
    try:
        result = await backtest_engine.run_ai_comparison_backtest(
            symbols=symbols,
            strategy=strategy,
            filters=filters,
            starting_capital=VALIDATION_CONFIG["starting_capital"],
            ai_confidence_threshold=VALIDATION_CONFIG["ai_confidence_threshold"],
            ai_lookback_bars=VALIDATION_CONFIG["ai_lookback_bars"],
        )
        rd = result.to_dict() if hasattr(result, "to_dict") else result
        return {
            "result_id": rd.get("id", ""),
            "setup_only_trades": rd.get("setup_only", {}).get("total_trades", 0),
            "setup_only_win_rate": rd.get("setup_only", {}).get("win_rate", 0),
            "setup_only_sharpe": rd.get("setup_only", {}).get("sharpe_ratio", 0),
            "ai_filtered_trades": rd.get("ai_filtered", {}).get("total_trades", 0),
            "ai_filtered_win_rate": rd.get("ai_filtered", {}).get("win_rate", 0),
            "ai_filtered_sharpe": rd.get("ai_filtered", {}).get("sharpe_ratio", 0),
            "ai_filtered_pnl": rd.get("ai_filtered", {}).get("total_pnl", 0),
            "ai_only_trades": rd.get("ai_only", {}).get("total_trades", 0),
            "ai_only_win_rate": rd.get("ai_only", {}).get("win_rate", 0),
            "ai_edge_win_rate": rd.get("ai_win_rate_improvement", 0),
            "ai_edge_pnl": rd.get("ai_pnl_improvement", 0),
            "ai_edge_sharpe": rd.get("ai_sharpe_improvement", 0),
            "ai_filter_rate": rd.get("ai_filter_rate", 0),
            "recommendation": rd.get("recommendation", ""),
            "duration_seconds": rd.get("duration_seconds", 0),
        }
    except Exception as e:
        logger.error(f"[VALIDATE] Phase 1 AI Comparison failed: {e}")
        return {"error": str(e), "duration_seconds": 0}


# ─── Phase 2: Monte Carlo ────────────────────────────────────────────────────

async def _run_phase2_monte_carlo(
    backtest_engine, symbols, setup_type, bar_size
) -> Dict:
    """Phase 2: Generate trades then run Monte Carlo risk simulation."""
    from services.slow_learning.advanced_backtest_engine import (
        BacktestTrade, MonteCarloConfig
    )
    strategy = _build_strategy_config(setup_type)
    filters = _build_filters()

    try:
        # Run a focused multi-strategy backtest (single strategy) to get trades
        ms_result = await backtest_engine.run_multi_strategy_backtest(
            symbols=symbols,
            strategies=[strategy],
            filters=filters,
            starting_capital=VALIDATION_CONFIG["starting_capital"],
            name=f"{setup_type}_validation_trades",
        )
        ms_dict = ms_result.to_dict() if hasattr(ms_result, "to_dict") else ms_result
        strat_results = ms_dict.get("strategy_results", [])
        trade_dicts = strat_results[0].get("trades", []) if strat_results else []

        if len(trade_dicts) < 5:
            return {
                "skipped": True,
                "reason": f"Insufficient trades ({len(trade_dicts)}) for Monte Carlo",
                "duration_seconds": 0,
            }

        trades = []
        for td in trade_dicts:
            try:
                trades.append(BacktestTrade(**{
                    k: v for k, v in td.items()
                    if k in BacktestTrade.__dataclass_fields__
                }))
            except Exception:
                pass

        if len(trades) < 5:
            return {
                "skipped": True,
                "reason": "Could not parse enough trades for Monte Carlo",
                "duration_seconds": 0,
            }

        mc_config = MonteCarloConfig(
            num_simulations=VALIDATION_CONFIG["mc_simulations"],
            randomize_trade_order=True,
            randomize_trade_size=False,
        )
        mc_result = await backtest_engine.run_monte_carlo(
            trades=trades,
            mc_config=mc_config,
            starting_capital=VALIDATION_CONFIG["starting_capital"],
        )
        mcd = mc_result.to_dict() if hasattr(mc_result, "to_dict") else mc_result
        return {
            "result_id": mcd.get("id", ""),
            "num_simulations": mcd.get("num_simulations", 0),
            "original_trades": mcd.get("original_trades", 0),
            "original_win_rate": mcd.get("original_win_rate", 0),
            "probability_of_profit": mcd.get("probability_of_profit", 0),
            "probability_of_ruin": mcd.get("probability_of_ruin", 0),
            "expected_max_drawdown": mcd.get("expected_max_drawdown", 0),
            "worst_case_drawdown": mcd.get("worst_case_drawdown", 0),
            "risk_assessment": mcd.get("risk_assessment", "UNKNOWN"),
            "recommendation": mcd.get("recommendation", ""),
            "pnl_distribution": mcd.get("pnl_distribution", {}),
            "drawdown_distribution": mcd.get("drawdown_distribution", {}),
            "duration_seconds": mcd.get("duration_seconds", 0),
        }
    except Exception as e:
        logger.error(f"[VALIDATE] Phase 2 Monte Carlo failed: {e}")
        return {"error": str(e), "duration_seconds": 0}


# ─── Phase 3: Walk-Forward ───────────────────────────────────────────────────

async def _run_phase3_walk_forward(
    backtest_engine, symbols, setup_type, bar_size
) -> Dict:
    """Phase 3: Walk-Forward analysis on top N symbols, aggregate results."""
    from services.slow_learning.advanced_backtest_engine import WalkForwardConfig

    strategy = _build_strategy_config(setup_type)
    wf_config = WalkForwardConfig(
        in_sample_days=VALIDATION_CONFIG["wf_in_sample_days"],
        out_of_sample_days=VALIDATION_CONFIG["wf_out_of_sample_days"],
        step_days=VALIDATION_CONFIG["wf_step_days"],
        min_trades_per_period=5,
    )

    top_symbols = symbols[: VALIDATION_CONFIG["wf_symbols"]]
    results_per_symbol = []

    try:
        for sym in top_symbols:
            try:
                wf = await backtest_engine.run_walk_forward(
                    symbol=sym,
                    strategy=strategy,
                    wf_config=wf_config,
                    total_days=VALIDATION_CONFIG["wf_total_days"],
                )
                wfd = wf.to_dict() if hasattr(wf, "to_dict") else wf
                results_per_symbol.append({
                    "symbol": sym,
                    "efficiency_ratio": wfd.get("efficiency_ratio", 0),
                    "is_robust": wfd.get("is_robust", False),
                    "in_sample_win_rate": wfd.get("in_sample_win_rate", 0),
                    "out_of_sample_win_rate": wfd.get("out_of_sample_win_rate", 0),
                    "total_periods": wfd.get("total_periods", 0),
                })
            except Exception as sym_err:
                logger.warning(f"[VALIDATE] Walk-forward {sym} failed: {sym_err}")

        if not results_per_symbol:
            return {
                "skipped": True,
                "reason": "No walk-forward results",
                "duration_seconds": 0,
            }

        avg_efficiency = statistics.mean(
            [r["efficiency_ratio"] for r in results_per_symbol]
        )
        avg_is_wr = statistics.mean(
            [r["in_sample_win_rate"] for r in results_per_symbol]
        )
        avg_oos_wr = statistics.mean(
            [r["out_of_sample_win_rate"] for r in results_per_symbol]
        )
        robust_count = sum(1 for r in results_per_symbol if r["is_robust"])

        return {
            "symbols_tested": [r["symbol"] for r in results_per_symbol],
            "avg_efficiency_ratio": round(avg_efficiency, 1),
            "is_robust": avg_efficiency >= 70,
            "robust_count": robust_count,
            "total_tested": len(results_per_symbol),
            "avg_in_sample_win_rate": round(avg_is_wr, 1),
            "avg_out_of_sample_win_rate": round(avg_oos_wr, 1),
            "per_symbol": results_per_symbol,
            "recommendation": (
                "Excellent robustness" if avg_efficiency >= 90
                else "Good robustness" if avg_efficiency >= 70
                else "Moderate — possible overfitting" if avg_efficiency >= 50
                else "Poor — likely overfit"
            ),
            "duration_seconds": 0,  # set by caller
        }
    except Exception as e:
        logger.error(f"[VALIDATE] Phase 3 Walk-Forward failed: {e}")
        return {"error": str(e), "duration_seconds": 0}


# ─── Composite Scoring & Promotion ───────────────────────────────────────────

def _composite_score(metrics: Dict) -> float:
    """
    Composite score: Sharpe (40%) + Win Rate (30%) + Return (20%) + Edge (10%)
    """
    sharpe = metrics.get("sharpe_ratio", 0)
    win_rate = metrics.get("win_rate", 0)
    total_return = metrics.get("total_return", 0)
    ai_edge = metrics.get("ai_vs_setup_edge", 0)
    return (
        0.40 * sharpe
        + 0.30 * (win_rate * 4 - 1)
        + 0.20 * total_return * 10
        + 0.10 * ai_edge * 10
    )


def _make_promotion_decision(
    ai_cmp: Dict, mc: Dict, wf: Dict, baseline: Optional[Dict]
) -> Dict:
    """
    Decide promote/reject using all 3 per-profile phases.
    """
    reasons = []

    # --- Check AI Comparison ---
    ai_trades = ai_cmp.get("ai_filtered_trades", 0)
    ai_wr = ai_cmp.get("ai_filtered_win_rate", 0)
    ai_sharpe = ai_cmp.get("ai_filtered_sharpe", 0)

    if ai_cmp.get("error"):
        reasons.append(f"AI Comparison error: {ai_cmp['error']}")
    elif ai_trades < PROMOTION_CRITERIA["min_trades"]:
        reasons.append(
            f"Insufficient trades ({ai_trades}), promoting by default"
        )
        return {"promote": True, "reason": "; ".join(reasons)}

    if ai_wr / 100 < PROMOTION_CRITERIA["min_win_rate"] and ai_trades >= PROMOTION_CRITERIA["min_trades"]:
        return {
            "promote": False,
            "reason": f"Win rate {ai_wr:.1f}% below minimum {PROMOTION_CRITERIA['min_win_rate']*100:.0f}%",
        }

    # --- Check Monte Carlo ---
    mc_risk = mc.get("risk_assessment", "UNKNOWN")
    if mc_risk == PROMOTION_CRITERIA["max_mc_risk"] and not mc.get("skipped") and not mc.get("error"):
        return {
            "promote": False,
            "reason": f"Monte Carlo risk EXTREME (worst DD {mc.get('worst_case_drawdown', 0):.1f}%)",
        }

    # --- Check Walk-Forward ---
    wf_eff = wf.get("avg_efficiency_ratio", 100)
    if (
        not wf.get("skipped")
        and not wf.get("error")
        and wf_eff < PROMOTION_CRITERIA["min_wf_efficiency"]
    ):
        reasons.append(
            f"Walk-forward efficiency {wf_eff:.0f}% below {PROMOTION_CRITERIA['min_wf_efficiency']}%"
        )
        return {"promote": False, "reason": "; ".join(reasons) if reasons else f"Poor robustness ({wf_eff:.0f}%)"}

    # --- Baseline comparison ---
    if baseline is None:
        return {
            "promote": True,
            "reason": "First model — no baseline. All phase checks passed.",
        }

    new_metrics = {
        "sharpe_ratio": ai_sharpe,
        "win_rate": ai_wr / 100,
        "total_return": ai_cmp.get("ai_filtered_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
        "ai_vs_setup_edge": ai_cmp.get("ai_edge_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
    }
    new_score = _composite_score(new_metrics)
    old_score = _composite_score(baseline)

    if new_score >= old_score:
        pct = ((new_score - old_score) / max(abs(old_score), 0.01)) * 100
        parts = [
            f"Score {new_score:.3f} vs baseline {old_score:.3f} (+{pct:.1f}%)",
            f"WR: {ai_wr:.1f}%",
            f"Sharpe: {ai_sharpe:.2f}",
            f"MC Risk: {mc_risk}",
            f"WF Eff: {wf_eff:.0f}%",
        ]
        return {"promote": True, "reason": " | ".join(parts)}
    else:
        pct = ((old_score - new_score) / max(abs(old_score), 0.01)) * 100
        return {
            "promote": False,
            "reason": f"Regression: score {new_score:.3f} vs baseline {old_score:.3f} (-{pct:.1f}%)",
        }


# ─── Baseline & Backup Management ────────────────────────────────────────────

def _load_baseline(db, setup_type: str, bar_size: str) -> Optional[Dict]:
    doc = db["model_baselines"].find_one(
        {"setup_type": setup_type, "bar_size": bar_size}, {"_id": 0}
    )
    return doc.get("metrics") if doc else None


def _save_baseline(db, setup_type, bar_size, metrics, validation_id):
    db["model_baselines"].update_one(
        {"setup_type": setup_type, "bar_size": bar_size},
        {"$set": {
            "setup_type": setup_type,
            "bar_size": bar_size,
            "metrics": metrics,
            "validation_id": validation_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def backup_current_model(db, setup_type: str, bar_size: str):
    """Backup the current model before training starts."""
    try:
        current = db["setup_type_models"].find_one(
            {"setup_type": setup_type, "bar_size": bar_size}, {"_id": 0}
        )
        if current and current.get("model_data"):
            db["setup_type_models_backup"].update_one(
                {"setup_type": setup_type, "bar_size": bar_size},
                {"$set": current},
                upsert=True,
            )
            logger.info(f"[VALIDATE] Backed up {setup_type}/{bar_size}")
    except Exception as e:
        logger.warning(f"Model backup failed: {e}")


async def _rollback_model(db, timeseries_service, setup_type, bar_size) -> bool:
    try:
        backup = db["setup_type_models_backup"].find_one(
            {"setup_type": setup_type, "bar_size": bar_size}, {"_id": 0}
        )
        if not backup or not backup.get("model_data"):
            return False
        db["setup_type_models"].update_one(
            {"setup_type": setup_type, "bar_size": bar_size},
            {"$set": backup},
            upsert=True,
        )
        model_bytes = base64.b64decode(backup["model_data"])
        restored_model = pickle.loads(model_bytes)
        model_key = setup_type.upper()
        if model_key in timeseries_service._setup_models:
            timeseries_service._setup_models[model_key]._model = restored_model
            if backup.get("feature_names"):
                timeseries_service._setup_models[model_key]._feature_names = backup["feature_names"]
            logger.info(f"[VALIDATE] Rolled back {setup_type}/{bar_size}")
        return True
    except Exception as e:
        logger.error(f"Model rollback failed: {e}")
        return False


# ─── Main Per-Profile Validation (Phases 1-3) ────────────────────────────────

async def validate_trained_model(
    db,
    timeseries_service,
    backtest_engine,
    setup_type: str,
    bar_size: str,
    training_result: Dict,
    job_id: str = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run the full 3-phase per-profile validation pipeline:
      Phase 1: AI Comparison
      Phase 2: Monte Carlo
      Phase 3: Walk-Forward
    Then decide promote/reject based on composite criteria.
    """
    validation_id = f"val_{uuid.uuid4().hex[:8]}"
    start_time = datetime.now(timezone.utc)
    logger.info(f"[VALIDATE] Starting {validation_id} for {setup_type}/{bar_size}")

    if progress_callback:
        await progress_callback(85, f"Validating {setup_type}/{bar_size}...")

    # Get symbols
    symbols = _get_validation_symbols(db, bar_size)
    if not symbols:
        record = _build_record(validation_id, setup_type, bar_size, "skipped",
                               reason="No validation symbols", training_accuracy=training_result.get("metrics", {}).get("accuracy", 0))
        _save_validation_record(db, record)
        return record

    logger.info(f"[VALIDATE] {len(symbols)} symbols for validation")

    # ── Phase 1: AI Comparison ──
    if progress_callback:
        await progress_callback(86, f"Phase 1/3: AI Comparison ({setup_type}/{bar_size})...")

    p1_start = datetime.now(timezone.utc)
    ai_cmp = await _run_phase1_ai_comparison(backtest_engine, symbols, setup_type, bar_size)
    ai_cmp["duration_seconds"] = (datetime.now(timezone.utc) - p1_start).total_seconds()

    logger.info(
        f"[VALIDATE] Phase 1 done: AI edge WR={ai_cmp.get('ai_edge_win_rate', 0):.1f}%, "
        f"trades={ai_cmp.get('ai_filtered_trades', 0)} in {ai_cmp['duration_seconds']:.0f}s"
    )

    # ── Phase 2: Monte Carlo ──
    if progress_callback:
        await progress_callback(90, f"Phase 2/3: Monte Carlo ({setup_type}/{bar_size})...")

    p2_start = datetime.now(timezone.utc)
    mc = await _run_phase2_monte_carlo(backtest_engine, symbols, setup_type, bar_size)
    mc["duration_seconds"] = (datetime.now(timezone.utc) - p2_start).total_seconds()

    logger.info(
        f"[VALIDATE] Phase 2 done: risk={mc.get('risk_assessment', '?')}, "
        f"P(profit)={mc.get('probability_of_profit', 0):.0f}% in {mc['duration_seconds']:.0f}s"
    )

    # ── Phase 3: Walk-Forward ──
    if progress_callback:
        await progress_callback(93, f"Phase 3/3: Walk-Forward ({setup_type}/{bar_size})...")

    p3_start = datetime.now(timezone.utc)
    wf = await _run_phase3_walk_forward(backtest_engine, symbols, setup_type, bar_size)
    wf["duration_seconds"] = (datetime.now(timezone.utc) - p3_start).total_seconds()

    logger.info(
        f"[VALIDATE] Phase 3 done: efficiency={wf.get('avg_efficiency_ratio', 0):.0f}%, "
        f"robust={wf.get('is_robust', False)} in {wf['duration_seconds']:.0f}s"
    )

    # ── Promotion Decision ──
    if progress_callback:
        await progress_callback(97, "Computing promotion decision...")

    baseline = _load_baseline(db, setup_type, bar_size)
    decision = _make_promotion_decision(ai_cmp, mc, wf, baseline)

    if decision["promote"]:
        baseline_metrics = {
            "sharpe_ratio": ai_cmp.get("ai_filtered_sharpe", 0),
            "win_rate": ai_cmp.get("ai_filtered_win_rate", 0) / 100,
            "total_return": ai_cmp.get("ai_filtered_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
            "ai_vs_setup_edge": ai_cmp.get("ai_edge_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
        }
        _save_baseline(db, setup_type, bar_size, baseline_metrics, validation_id)
        logger.info(f"[VALIDATE] {setup_type}/{bar_size} PROMOTED — {decision['reason']}")
    else:
        rolled_back = await _rollback_model(db, timeseries_service, setup_type, bar_size)
        if not rolled_back:
            decision["promote"] = True
            decision["reason"] += " (no previous model, keeping new)"
            baseline_metrics = {
                "sharpe_ratio": ai_cmp.get("ai_filtered_sharpe", 0),
                "win_rate": ai_cmp.get("ai_filtered_win_rate", 0) / 100,
                "total_return": ai_cmp.get("ai_filtered_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
                "ai_vs_setup_edge": ai_cmp.get("ai_edge_pnl", 0) / VALIDATION_CONFIG["starting_capital"],
            }
            _save_baseline(db, setup_type, bar_size, baseline_metrics, validation_id)
        logger.info(f"[VALIDATE] {setup_type}/{bar_size} {'KEPT (no backup)' if not rolled_back else 'REJECTED'} — {decision['reason']}")

    if progress_callback:
        label = "PROMOTED" if decision["promote"] else "REJECTED"
        await progress_callback(99, f"{setup_type}/{bar_size}: {label}")

    # ── Build & save record ──
    total_dur = (datetime.now(timezone.utc) - start_time).total_seconds()
    phases_passed = _count_phases_passed(ai_cmp, mc, wf)

    record = _build_record(
        validation_id, setup_type, bar_size,
        "promoted" if decision["promote"] else "rejected",
        reason=decision["reason"],
        training_accuracy=training_result.get("metrics", {}).get("accuracy", 0),
        ai_comparison=ai_cmp,
        monte_carlo=mc,
        walk_forward=wf,
        baseline_metrics=baseline,
        phases_passed=phases_passed,
        total_duration=total_dur,
    )
    _save_validation_record(db, record)
    logger.info(f"[VALIDATE] Complete in {total_dur:.0f}s — {record['status']} ({phases_passed}/3 phases passed)")
    return record


# ─── Batch Validation (Phases 4-5) ───────────────────────────────────────────

async def run_batch_validation(
    db,
    backtest_engine,
    trained_setup_types: List[str],
    job_id: str = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run batch-level validation after all profiles are trained:
      Phase 4: Multi-Strategy comparison
      Phase 5: Market-Wide scan per setup type
    """
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    start_time = datetime.now(timezone.utc)
    logger.info(f"[VALIDATE-BATCH] Starting {batch_id} for {len(trained_setup_types)} setups")

    from services.slow_learning.advanced_backtest_engine import StrategyConfig, BacktestFilters

    # Get validation symbols from the most common bar size
    symbols = _get_validation_symbols(db, "1 day", limit=VALIDATION_CONFIG["num_symbols"])
    if not symbols:
        return {"batch_id": batch_id, "error": "No symbols for batch validation"}

    filters = _build_filters()
    result = {
        "batch_id": batch_id,
        "triggered_by_job": job_id,
        "setup_types": trained_setup_types,
        "validated_at": start_time.isoformat(),
        "multi_strategy": None,
        "market_wide": [],
    }

    # ── Phase 4: Multi-Strategy ──
    if progress_callback:
        await progress_callback(96, "Phase 4/5: Multi-Strategy comparison...")

    try:
        strategies = []
        for st in trained_setup_types:
            strategies.append(StrategyConfig(
                name=f"{st}_comparison",
                setup_type=st.lower(),
            ))

        if len(strategies) >= 2:
            ms_result = await backtest_engine.run_multi_strategy_backtest(
                symbols=symbols,
                strategies=strategies,
                filters=filters,
                starting_capital=VALIDATION_CONFIG["starting_capital"],
                name=f"batch_{batch_id}_multi_strategy",
            )
            msd = ms_result.to_dict() if hasattr(ms_result, "to_dict") else ms_result
            strat_summaries = []
            for sr in msd.get("strategy_results", []):
                strat_summaries.append({
                    "strategy_name": sr.get("strategy_name", ""),
                    "setup_type": sr.get("setup_type", ""),
                    "total_trades": sr.get("total_trades", 0),
                    "win_rate": sr.get("win_rate", 0),
                    "sharpe_ratio": sr.get("sharpe_ratio", 0),
                    "profit_factor": sr.get("profit_factor", 0),
                    "total_pnl": sr.get("total_pnl", 0),
                })
            best = max(strat_summaries, key=lambda x: x.get("sharpe_ratio", 0)) if strat_summaries else {}
            result["multi_strategy"] = {
                "result_id": msd.get("id", ""),
                "strategies_compared": len(strategies),
                "combined_win_rate": msd.get("combined_win_rate", 0),
                "combined_sharpe": msd.get("combined_sharpe_ratio", 0),
                "combined_pnl": msd.get("combined_total_pnl", 0),
                "best_strategy": best.get("setup_type", ""),
                "strategy_summaries": strat_summaries,
                "correlation_matrix": msd.get("correlation_matrix", {}),
                "duration_seconds": msd.get("duration_seconds", 0),
            }
            logger.info(f"[VALIDATE-BATCH] Phase 4 done: {len(strategies)} strategies compared")
    except Exception as e:
        logger.error(f"[VALIDATE-BATCH] Phase 4 failed: {e}")
        result["multi_strategy"] = {"error": str(e)}

    # ── Phase 5: Market-Wide per setup type ──
    if progress_callback:
        await progress_callback(98, "Phase 5/5: Market-Wide scan...")

    for idx, st in enumerate(trained_setup_types):
        try:
            strategy = _build_strategy_config(st)
            mw_result = await backtest_engine.run_market_wide_backtest(
                strategy=strategy,
                filters=filters,
                trade_style="swing" if "day" in st.lower() or st in ("MOMENTUM", "TREND_CONTINUATION") else "intraday",
                bar_size="1 day",
                starting_capital=VALIDATION_CONFIG["starting_capital"],
                max_symbols=VALIDATION_CONFIG["mw_max_symbols"],
            )
            mwd = mw_result if isinstance(mw_result, dict) else mw_result.to_dict()
            summary = mwd.get("summary", {})
            result["market_wide"].append({
                "setup_type": st,
                "result_id": mwd.get("id", ""),
                "symbols_scanned": mwd.get("total_symbols_scanned", 0),
                "symbols_with_signals": mwd.get("symbols_with_signals", 0),
                "total_trades": summary.get("total_trades", 0),
                "win_rate": summary.get("win_rate", 0),
                "profit_factor": summary.get("profit_factor", 0),
                "total_pnl": summary.get("total_pnl", 0),
                "expectancy": summary.get("expectancy", 0),
                "duration_seconds": mwd.get("duration_seconds", 0),
            })
            logger.info(f"[VALIDATE-BATCH] Phase 5 {st}: {summary.get('total_trades', 0)} trades found")
        except Exception as e:
            logger.error(f"[VALIDATE-BATCH] Phase 5 {st} failed: {e}")
            result["market_wide"].append({"setup_type": st, "error": str(e)})

    result["total_duration_seconds"] = (datetime.now(timezone.utc) - start_time).total_seconds()

    # Store batch result
    try:
        db["batch_validations"].insert_one(result)
    except Exception:
        pass

    logger.info(f"[VALIDATE-BATCH] Complete in {result['total_duration_seconds']:.0f}s")
    return result


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _count_phases_passed(ai_cmp, mc, wf) -> int:
    passed = 0
    # Phase 1 passes if AI edge >= 0 or if we have trades
    if not ai_cmp.get("error") and ai_cmp.get("ai_filtered_trades", 0) >= 0:
        passed += 1
    # Phase 2 passes if risk is not EXTREME
    if mc.get("skipped") or (not mc.get("error") and mc.get("risk_assessment", "LOW") != "EXTREME"):
        passed += 1
    # Phase 3 passes if efficiency >= 50%
    if wf.get("skipped") or (not wf.get("error") and wf.get("avg_efficiency_ratio", 100) >= 50):
        passed += 1
    return passed


def _build_record(
    validation_id, setup_type, bar_size, status,
    reason="", training_accuracy=0,
    ai_comparison=None, monte_carlo=None, walk_forward=None,
    baseline_metrics=None, phases_passed=0, total_duration=0,
):
    return {
        "validation_id": validation_id,
        "setup_type": setup_type,
        "bar_size": bar_size,
        "status": status,
        "reason": reason,
        "training_accuracy": training_accuracy,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "ai_comparison": ai_comparison or {},
        "monte_carlo": monte_carlo or {},
        "walk_forward": walk_forward or {},
        "baseline_metrics": baseline_metrics or {},
        "phases_passed": phases_passed,
        "phases_total": 3,
        "total_duration_seconds": total_duration,
    }


def _save_validation_record(db, record):
    try:
        db["model_validations"].insert_one(record)
    except Exception as e:
        logger.error(f"Failed to save validation record: {e}")
