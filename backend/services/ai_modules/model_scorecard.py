"""
Model Scorecard v2 — unified multi-metric evaluation.

Consolidates the "bundle" of trading metrics (Sortino/Calmar/turnover/DSR/etc.)
into ONE object that:
    • every trainer produces after validation
    • every consumer (NIA UI, promotion gate, chat, bot) reads
    • Mongo persists per model in `timeseries_models.scorecard` and
      `model_validations.scorecard`.

Reference: Perplexity/community "bundle evaluation" convention + López de Prado
DSR (ch. 14). Mlfinlab has piecewise functions we could import; we consolidate
into one dataclass here.

Composite scoring weights — tunable; each factor normalized to 0-1 and weighted:
    DSR   (25%)  — risk-adjusted, trial-deflated
    Sortino (20%) — downside-only risk
    Drawdown (15%) — 1 - dd/30% clamped
    AI edge (15%) — ai_vs_setup_edge_pp / 10
    Walk-forward robustness (10%) — efficiency / 1.0
    Profit factor (10%) — pf / 2.0
    Statistical significance (5%) — DSR p-value >= 0.95 → 1, else 0

Total = 100 → grade:
    A: >= 80   B: 65-79   C: 50-64   D: 35-49   F: < 35
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
import math
import numpy as np


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


@dataclass
class ModelScorecard:
    # Identity
    model_name: str = ""
    setup_type: str = ""
    bar_size: str = ""
    trade_side: str = "long"   # "long" | "short" | "both"
    version: str = ""
    validated_at: Optional[str] = None

    # Risk-adjusted returns
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    deflated_sharpe: float = 0.0

    # Return quality
    total_return_pct: float = 0.0
    profit_factor: float = 0.0
    hit_rate: float = 0.0
    avg_win_loss_ratio: float = 0.0

    # Risk
    max_drawdown_pct: float = 0.0
    expected_max_drawdown: float = 0.0
    worst_case_drawdown: float = 0.0
    prob_of_ruin: float = 0.0

    # Trading behavior
    num_trades: int = 0
    turnover_annual: float = 0.0
    avg_holding_bars: float = 0.0

    # Robustness
    walk_forward_efficiency: float = 0.0
    oos_sharpe: float = 0.0
    regime_stability: float = 0.0   # 1 / (1 + std across regime folds)
    cpcv_sharpe_mean: float = 0.0
    cpcv_sharpe_std: float = 0.0
    cpcv_negative_pct: float = 0.0

    # Edge vs baseline
    ai_vs_setup_edge_pp: float = 0.0   # percentage points

    # Trial-adjusted significance
    num_trials: int = 1
    dsr_p_value: float = 0.5
    is_statistically_significant: bool = False

    # Composite (the "bundle judge")
    composite_score: float = 0.0
    composite_grade: str = "F"

    # Flags / reasons (for UI & debugging)
    red_line_failures: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_composite(sc: ModelScorecard) -> tuple:
    """Return (score_0_100, grade)."""
    risk_adj  = 0.25 * _clamp(sc.deflated_sharpe / 2.0)
    downside  = 0.20 * _clamp(sc.sortino / 2.5)
    drawdown  = 0.15 * (1 - _clamp(sc.max_drawdown_pct / 30.0))
    edge      = 0.15 * _clamp(sc.ai_vs_setup_edge_pp / 10.0)
    robust    = 0.10 * _clamp(sc.walk_forward_efficiency / 1.0)
    quality   = 0.10 * _clamp(sc.profit_factor / 2.0)
    sig       = 0.05 * (1.0 if sc.is_statistically_significant else 0.0)
    score = 100.0 * (risk_adj + downside + drawdown + edge + robust + quality + sig)
    if score >= 80:
        g = "A"
    elif score >= 65:
        g = "B"
    elif score >= 50:
        g = "C"
    elif score >= 35:
        g = "D"
    else:
        g = "F"
    return float(score), g


def compute_red_lines(sc: ModelScorecard,
                      min_trades: int = 30,
                      max_dd: float = 50.0,
                      min_dsr_p: float = 0.90) -> list:
    """Hard fails that override composite grade."""
    fails = []
    if sc.num_trades < min_trades:
        fails.append(f"trades<{min_trades}")
    if sc.sortino < 0:
        fails.append("sortino<0")
    if sc.max_drawdown_pct > max_dd:
        fails.append(f"drawdown>{max_dd}%")
    if sc.dsr_p_value < min_dsr_p:
        fails.append(f"dsr_p<{min_dsr_p}")
    return fails


# ─────────── Metric calculators ───────────

def compute_sortino(returns: np.ndarray, target_return: float = 0.0, annualization: float = 252.0) -> float:
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    excess = r - target_return
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_std = float(np.sqrt((downside ** 2).mean()))
    if downside_std <= 0:
        return 0.0
    mean_excess = float(excess.mean())
    return mean_excess / downside_std * math.sqrt(annualization)


def compute_calmar(total_return_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct <= 0:
        return 0.0
    return float(total_return_pct) / float(max_drawdown_pct)


def compute_turnover(trades: list, capital: float, lookback_days: int = 252) -> float:
    """Annualized turnover = sum(abs(notional)) / capital / (lookback_days/252)."""
    if not trades or capital <= 0:
        return 0.0
    total_notional = 0.0
    for t in trades:
        qty = abs(float(t.get("qty", 0)))
        price = float(t.get("price", 0) or t.get("entry_price", 0))
        total_notional += qty * price
    return (total_notional / capital) * (252.0 / max(1, lookback_days))


def compute_regime_stability(regime_fold_sharpes: list) -> float:
    if not regime_fold_sharpes:
        return 0.0
    arr = np.asarray(regime_fold_sharpes, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return 0.0
    std = float(arr.std(ddof=1))
    return 1.0 / (1.0 + std)   # 1 when perfectly stable, → 0 as std grows


def scorecard_from_validator(
    validator_result: dict,
    setup_type: str = "",
    bar_size: str = "",
    trade_side: str = "long",
    model_name: str = "",
    version: str = "",
) -> ModelScorecard:
    """Build a scorecard from `post_training_validator` output + raw returns."""
    vm = validator_result or {}
    # Extract from the nested validator structure
    ai = vm.get("ai_filtered", {}) or {}
    mc = vm.get("monte_carlo", {}) or {}
    wf = vm.get("walk_forward", {}) or {}
    cmp_ = vm.get("setup_vs_ai_comparison", {}) or {}

    returns = np.asarray(ai.get("returns", []), dtype=np.float64) if ai.get("returns") else np.array([])
    sharpe = float(ai.get("sharpe", vm.get("sharpe_ratio", 0.0)))
    total_ret = float(ai.get("total_return_pct", vm.get("total_return_pct", 0.0)))
    max_dd = float(mc.get("worst_case_drawdown", mc.get("expected_max_drawdown", 0.0)))

    sortino = compute_sortino(returns) if len(returns) else 0.0
    calmar = compute_calmar(total_ret, max_dd)

    # Profit factor
    pf = float(ai.get("profit_factor", vm.get("profit_factor", 0.0)))

    # Average win/loss ratio
    wins = [r for r in returns if r > 0]
    losses = [abs(r) for r in returns if r < 0]
    awl = (float(np.mean(wins)) / float(np.mean(losses))) if (wins and losses) else 0.0

    sc = ModelScorecard(
        model_name=model_name,
        setup_type=setup_type.upper(),
        bar_size=bar_size,
        trade_side=trade_side.lower(),
        version=version,
        validated_at=vm.get("validated_at"),
        sharpe=sharpe,
        sortino=float(sortino),
        calmar=float(calmar),
        total_return_pct=total_ret,
        profit_factor=pf,
        hit_rate=float(ai.get("win_rate", 0.0)),
        avg_win_loss_ratio=float(awl),
        max_drawdown_pct=max_dd,
        expected_max_drawdown=float(mc.get("expected_max_drawdown", 0.0)),
        worst_case_drawdown=float(mc.get("worst_case_drawdown", 0.0)),
        prob_of_ruin=float(mc.get("probability_of_ruin", 0.0)),
        num_trades=int(ai.get("trades", vm.get("num_trades", 0))),
        walk_forward_efficiency=float(wf.get("efficiency", 0.0)),
        oos_sharpe=float(wf.get("oos_sharpe", 0.0)),
        ai_vs_setup_edge_pp=float(cmp_.get("ai_edge_pp", vm.get("ai_vs_setup_edge_pp", 0.0))),
    )
    return sc


def finalize_scorecard(sc: ModelScorecard) -> ModelScorecard:
    """Fill composite + red_lines after all metrics are populated."""
    score, grade = compute_composite(sc)
    sc.composite_score = round(score, 2)
    sc.composite_grade = grade
    sc.red_line_failures = compute_red_lines(sc)
    return sc
