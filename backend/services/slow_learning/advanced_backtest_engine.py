"""
Advanced Backtest Engine - Enhanced Backtesting System
======================================================

Features:
1. Multi-Strategy Backtesting - Compare multiple strategies side-by-side
2. Walk-Forward Optimization - Prevent overfitting with rolling validation
3. Monte Carlo Simulation - Understand range of possible outcomes
4. Custom Date Range Selection - Filter by date, regime, time of day

Optimizations:
- Data caching in MongoDB for fast repeat runs
- Background job processing for long-running backtests
- Progress tracking
- Parallel execution where possible
"""

import logging
import asyncio
import random
import statistics
from typing import Optional, Dict, Any, List, Tuple, Callable
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid
import math

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

class MarketRegimeFilter(str, Enum):
    """Market regime filters for backtesting"""
    ALL = "all"
    BULL = "bull"           # SPY > 200 SMA
    BEAR = "bear"           # SPY < 200 SMA
    HIGH_VOL = "high_vol"   # VIX > 25
    LOW_VOL = "low_vol"     # VIX < 15
    TRENDING = "trending"   # ADX > 25
    RANGING = "ranging"     # ADX < 20


class TimeFilter(str, Enum):
    """Time of day filters"""
    ALL_DAY = "all_day"
    FIRST_HOUR = "first_hour"      # 9:30-10:30
    MORNING = "morning"            # 9:30-12:00
    MIDDAY = "midday"              # 11:00-14:00
    POWER_HOUR = "power_hour"      # 15:00-16:00
    REGULAR_HOURS = "regular_hours" # 9:30-16:00


@dataclass
class BacktestFilters:
    """Filters for custom date range selection"""
    start_date: str = None
    end_date: str = None
    market_regimes: List[str] = field(default_factory=lambda: ["all"])
    time_filters: List[str] = field(default_factory=lambda: ["all_day"])
    days_of_week: List[int] = field(default_factory=lambda: [0,1,2,3,4])  # Mon-Fri
    exclude_earnings_days: bool = False
    min_volume_percentile: float = 0  # 0 = no filter
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StrategyConfig:
    """Configuration for a single strategy"""
    name: str
    setup_type: str  # ORB, VWAP_BOUNCE, GAP_AND_GO, etc.
    
    # Entry
    min_tqs_score: float = 60.0
    entry_signal_fn: str = None  # Name of custom entry function
    
    # Exit
    stop_pct: float = 2.0
    target_pct: float = 4.0
    use_trailing_stop: bool = False
    trailing_stop_pct: float = 1.5
    max_bars_to_hold: int = 20
    
    # Position sizing
    position_size_pct: float = 10.0  # % of capital per trade
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d.pop('entry_signal_fn', None)  # Remove non-serializable
        return d


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward optimization"""
    in_sample_days: int = 180       # Training period (6 months)
    out_of_sample_days: int = 30    # Testing period (1 month)
    step_days: int = 30             # Move forward by 1 month
    min_trades_per_period: int = 10  # Skip periods with too few trades
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation"""
    num_simulations: int = 10000
    confidence_levels: List[float] = field(default_factory=lambda: [0.05, 0.25, 0.50, 0.75, 0.95])
    randomize_trade_order: bool = True
    randomize_trade_size: bool = False  # Optional: vary position sizes
    size_variation_pct: float = 20.0    # +/- 20% if randomize_trade_size
    # BOOTSTRAP: sample trades with replacement (default on). Without this, shuffling
    # trade order alone leaves the sum of P&L unchanged — producing a degenerate
    # distribution where every percentile is identical. Bootstrap simulates
    # "what if I had experienced a different mix of these same trades?" and
    # gives a real P&L distribution. Drawdowns still vary from order too.
    bootstrap: bool = True
    bootstrap_sample_size: Optional[int] = None  # None => same as len(trades)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BacktestTrade:
    """A single trade in the backtest"""
    id: str = ""
    symbol: str = ""
    strategy_name: str = ""
    setup_type: str = ""
    direction: str = "long"
    entry_date: str = ""
    entry_time: str = ""
    entry_price: float = 0.0
    exit_date: str = ""
    exit_time: str = ""
    exit_price: float = 0.0
    shares: int = 0
    stop_price: float = 0.0
    target_price: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    tqs_score: float = 0.0
    market_regime: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StrategyResult:
    """Results for a single strategy"""
    strategy_name: str = ""
    setup_type: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_r: float = 0.0
    avg_r: float = 0.0
    expectancy: float = 0.0
    avg_bars_held: float = 0.0
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MultiStrategyResult:
    """Results for multi-strategy backtest"""
    id: str = ""
    name: str = ""
    symbols: List[str] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    filters: Dict = field(default_factory=dict)
    
    # Per-strategy results
    strategy_results: List[Dict] = field(default_factory=list)
    
    # Combined results
    combined_total_trades: int = 0
    combined_win_rate: float = 0.0
    combined_total_pnl: float = 0.0
    combined_profit_factor: float = 0.0
    combined_sharpe_ratio: float = 0.0
    combined_max_drawdown_pct: float = 0.0
    
    # Correlation matrix (strategy vs strategy)
    correlation_matrix: Dict = field(default_factory=dict)
    
    # Metadata
    created_at: str = ""
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WalkForwardResult:
    """Results for walk-forward optimization"""
    id: str = ""
    strategy_name: str = ""
    symbol: str = ""
    total_periods: int = 0
    
    # In-sample vs out-of-sample comparison
    in_sample_win_rate: float = 0.0
    out_of_sample_win_rate: float = 0.0
    in_sample_profit_factor: float = 0.0
    out_of_sample_profit_factor: float = 0.0
    
    # Efficiency ratio (out-of-sample / in-sample)
    efficiency_ratio: float = 0.0
    
    # Period-by-period results
    periods: List[Dict] = field(default_factory=list)
    
    # Verdict
    is_robust: bool = False  # True if efficiency > 70%
    recommendation: str = ""
    
    # Metadata
    created_at: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MonteCarloResult:
    """Results for Monte Carlo simulation"""
    id: str = ""
    strategy_name: str = ""
    num_simulations: int = 0
    original_trades: int = 0
    
    # Original backtest metrics
    original_total_pnl: float = 0.0
    original_max_drawdown: float = 0.0
    original_win_rate: float = 0.0
    
    # Distribution of outcomes
    pnl_distribution: Dict = field(default_factory=dict)        # percentiles
    drawdown_distribution: Dict = field(default_factory=dict)   # percentiles
    win_streak_distribution: Dict = field(default_factory=dict)
    lose_streak_distribution: Dict = field(default_factory=dict)
    
    # Risk metrics
    probability_of_profit: float = 0.0     # % of sims with positive P&L
    probability_of_ruin: float = 0.0       # % of sims with >50% drawdown
    expected_max_drawdown: float = 0.0     # 50th percentile DD
    worst_case_drawdown: float = 0.0       # 95th percentile DD
    
    # Recommendation
    risk_assessment: str = ""  # LOW, MEDIUM, HIGH, EXTREME
    recommendation: str = ""
    
    # Metadata
    created_at: str = ""
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BacktestJob:
    """Background job for long-running backtests"""
    id: str = ""
    job_type: str = ""  # single, multi_strategy, walk_forward, monte_carlo
    status: str = "pending"  # pending, running, completed, failed
    progress: float = 0.0  # 0-100
    progress_message: str = ""
    
    # Configuration
    config: Dict = field(default_factory=dict)
    
    # Results (populated when complete)
    result_id: str = ""
    result: Dict = None
    error: str = ""
    
    # Timing
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AIComparisonResult:
    """Result of an AI vs Setup comparison backtest"""
    id: str = ""
    created_at: str = ""
    duration_seconds: float = 0.0
    
    # Configuration
    symbols: List[str] = field(default_factory=list)
    strategy_name: str = ""
    setup_type: str = ""
    date_range: str = ""
    ai_model_version: str = ""
    ai_confidence_threshold: float = 0.5
    
    # Mode results
    setup_only: Dict = field(default_factory=dict)     # Traditional setup signals
    ai_filtered: Dict = field(default_factory=dict)    # Setup + AI confirmation
    ai_only: Dict = field(default_factory=dict)        # AI predictions only
    gate_filtered: Dict = field(default_factory=dict)  # Full confidence gate (10 signals)
    gate_stats: Dict = field(default_factory=dict)     # Gate decision breakdown (GO/REDUCE/SKIP counts)
    
    # Comparison metrics
    ai_trades_filtered: int = 0           # How many setup trades AI blocked
    ai_filter_rate: float = 0.0           # % of setup trades AI filtered out
    ai_win_rate_improvement: float = 0.0  # Win rate delta: AI+Setup vs Setup-only
    ai_pnl_improvement: float = 0.0       # PnL delta: AI+Setup vs Setup-only
    ai_sharpe_improvement: float = 0.0    # Sharpe delta
    
    # Per-symbol breakdown
    symbol_results: List[Dict] = field(default_factory=list)
    
    # AI signal analysis
    ai_signal_accuracy: float = 0.0       # % of AI "up" signals that were correct
    ai_rejection_accuracy: float = 0.0    # % of AI "skip" signals that avoided losses
    
    recommendation: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# Advanced Backtest Engine
# ============================================================================

class AdvancedBacktestEngine:
    """
    Advanced backtesting engine with multi-strategy, walk-forward,
    Monte Carlo, AI comparison, and custom date range capabilities.
    """
    
    def __init__(self):
        self._db = None
        self._backtest_results_col = None
        self._backtest_cache_col = None
        self._backtest_jobs_col = None
        self._historical_data_service = None
        self._alpaca_service = None
        self._tqs_engine = None
        self._hybrid_data_service = None  # IB + Alpaca hybrid data
        self._timeseries_model = None     # LightGBM time-series predictor
        self._confidence_gate = None      # Full 10-signal confidence gate
        
        # Background jobs
        self._running_jobs: Dict[str, BacktestJob] = {}
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._backtest_results_col = db['advanced_backtest_results']
            self._backtest_cache_col = db['backtest_data_cache']
            self._backtest_jobs_col = db['backtest_jobs']
            
            # Create indexes for performance
            self._backtest_cache_col.create_index([("symbol", 1), ("timeframe", 1), ("date", 1)])
            
            # Clean up orphaned jobs from previous server sessions
            self._cleanup_stale_jobs()
            
    def set_services(self, historical_data_service=None, alpaca_service=None, tqs_engine=None):
        """Set required services"""
        self._historical_data_service = historical_data_service
        self._alpaca_service = alpaca_service
        self._tqs_engine = tqs_engine
    
    def set_hybrid_data_service(self, hybrid_data_service):
        """Set hybrid data service (IB + Alpaca fallback)"""
        self._hybrid_data_service = hybrid_data_service
        logger.info("Advanced Backtest Engine: Hybrid data service connected")
    
    def set_timeseries_model(self, model):
        """Set the LightGBM time-series model for AI-enhanced backtesting"""
        self._timeseries_model = model
        logger.info("Advanced Backtest Engine: Time-series AI model connected")

    def set_confidence_gate(self, gate):
        """Set the full confidence gate for gate-filtered backtesting"""
        self._confidence_gate = gate
        logger.info("Advanced Backtest Engine: Confidence gate connected")

    def _cleanup_stale_jobs(self):
        """Mark orphaned pending/running jobs as cancelled on startup.
        These are jobs from previous server sessions that never completed."""
        if self._backtest_jobs_col is None:
            return
        try:
            result = self._backtest_jobs_col.update_many(
                {"status": {"$in": ["pending", "running"]}},
                {"$set": {
                    "status": "cancelled",
                    "error": "Server restarted before job completed. Re-submit to retry.",
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            if result.modified_count > 0:
                logger.info(f"[BACKTEST] Cleaned up {result.modified_count} orphaned jobs from previous session")
        except Exception as e:
            logger.warning(f"[BACKTEST] Failed to cleanup stale jobs: {e}")

    def clear_stale_results(self):
        """Remove empty backtest results (0 trades), cancelled jobs, and empty validations."""
        removed_results = 0
        removed_jobs = 0
        removed_validations = 0
        removed_batch_validations = 0
        if self._backtest_results_col is not None:
            try:
                r = self._backtest_results_col.delete_many({"total_trades": {"$in": [0, None]}})
                removed_results = r.deleted_count
            except Exception:
                pass
        if self._backtest_jobs_col is not None:
            try:
                r = self._backtest_jobs_col.delete_many({"status": "cancelled"})
                removed_jobs = r.deleted_count
            except Exception:
                pass
        # Clean empty validations (0% accuracy, auto-promoted without real data)
        if self._db is not None:
            try:
                r = self._db["model_validations"].delete_many({"training_accuracy": 0})
                removed_validations = r.deleted_count
            except Exception:
                pass
            try:
                r = self._db["batch_validations"].delete_many({"total_tests": {"$in": [0, None]}})
                removed_batch_validations = r.deleted_count
            except Exception:
                pass
        return {
            "removed_results": removed_results,
            "removed_jobs": removed_jobs,
            "removed_validations": removed_validations,
            "removed_batch_validations": removed_batch_validations,
        }

    # ========================================================================
    # Multi-Strategy Backtesting
    # ========================================================================
    
    async def run_multi_strategy_backtest(
        self,
        symbols: List[str],
        strategies: List[StrategyConfig],
        filters: BacktestFilters = None,
        starting_capital: float = 100000.0,
        name: str = None,
        job_id: str = None
    ) -> MultiStrategyResult:
        """
        Run multiple strategies on multiple symbols and compare results.
        
        Args:
            symbols: List of stock symbols
            strategies: List of strategy configurations
            filters: Date range and market filters
            starting_capital: Starting capital per strategy
            name: Name for this backtest
            job_id: Optional job ID for progress tracking
            
        Returns:
            MultiStrategyResult with comparison data
        """
        start_time = datetime.now(timezone.utc)
        
        if filters is None:
            filters = BacktestFilters()
            
        result = MultiStrategyResult(
            id=f"mbt_{uuid.uuid4().hex[:12]}",
            name=name or "Multi-Strategy Backtest",
            symbols=symbols,
            filters=filters.to_dict(),
            created_at=start_time.isoformat()
        )
        
        total_tasks = len(symbols) * len(strategies)
        completed_tasks = 0
        
        strategy_results: List[StrategyResult] = []
        all_trades: List[BacktestTrade] = []
        
        # Run each strategy on each symbol
        for strategy in strategies:
            strategy_result = StrategyResult(
                strategy_name=strategy.name,
                setup_type=strategy.setup_type
            )
            strategy_trades: List[BacktestTrade] = []
            strategy_equity = starting_capital
            equity_curve = []
            
            for symbol in symbols:
                # Update progress
                if job_id:
                    self._update_job_progress(
                        job_id,
                        (completed_tasks / total_tasks) * 100,
                        f"Running {strategy.name} on {symbol}..."
                    )
                
                # Get cached or fresh data
                bars = await self._get_cached_bars(
                    symbol, "1Day", 
                    filters.start_date, 
                    filters.end_date
                )
                
                if not bars:
                    completed_tasks += 1
                    continue
                    
                # Filter bars by criteria
                filtered_bars = self._apply_filters(bars, filters)
                
                if not filtered_bars:
                    completed_tasks += 1
                    continue
                
                # Run simulation for this symbol
                trades, curve = await self._simulate_strategy(
                    symbol, filtered_bars, strategy, strategy_equity
                )
                
                strategy_trades.extend(trades)
                all_trades.extend(trades)
                
                # Update equity from last curve point
                if curve:
                    strategy_equity = curve[-1]["equity"]
                    equity_curve.extend(curve)
                
                completed_tasks += 1
            
            # Calculate metrics for this strategy
            strategy_result = self._calculate_strategy_metrics(
                strategy_result, strategy_trades, equity_curve, starting_capital
            )
            strategy_results.append(strategy_result)
        
        # Store results
        result.strategy_results = [sr.to_dict() for sr in strategy_results]
        
        # Calculate combined metrics
        result = self._calculate_combined_metrics(result, strategy_results, all_trades)
        
        # Calculate correlation matrix
        result.correlation_matrix = self._calculate_correlation_matrix(strategy_results)
        
        # Set date range from actual data
        if all_trades:
            dates = [t.entry_date for t in all_trades if t.entry_date]
            if dates:
                result.start_date = min(dates)
                result.end_date = max(dates)
        
        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Store in MongoDB
        if self._backtest_results_col is not None:
            self._backtest_results_col.insert_one(result.to_dict())
        
        return result

    # ========================================================================
    # Walk-Forward Optimization
    # ========================================================================
    
    async def run_walk_forward(
        self,
        symbol: str,
        strategy: StrategyConfig,
        wf_config: WalkForwardConfig = None,
        total_days: int = 365,
        end_date: str = None,
        job_id: str = None
    ) -> WalkForwardResult:
        """
        Run walk-forward optimization to test strategy robustness.
        
        The process:
        1. Split data into in-sample (training) and out-of-sample (testing) periods
        2. Optimize/test on in-sample, validate on out-of-sample
        3. Roll forward and repeat
        4. Compare in-sample vs out-of-sample performance
        
        Args:
            symbol: Stock symbol
            strategy: Strategy configuration
            wf_config: Walk-forward configuration
            total_days: Total days of data to use
            end_date: End date (defaults to today)
            job_id: Optional job ID for progress tracking
            
        Returns:
            WalkForwardResult with robustness analysis
        """
        start_time = datetime.now(timezone.utc)
        
        if wf_config is None:
            wf_config = WalkForwardConfig()
            
        result = WalkForwardResult(
            id=f"wf_{uuid.uuid4().hex[:12]}",
            strategy_name=strategy.name,
            symbol=symbol.upper(),
            created_at=start_time.isoformat()
        )
        
        # Calculate date range
        if end_date is None:
            end_dt = datetime.now(timezone.utc)
        else:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            
        start_dt = end_dt - timedelta(days=total_days)
        
        # Get all bars for the period
        all_bars = await self._get_cached_bars(
            symbol, "1Day",
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d")
        )
        
        if not all_bars:
            result.recommendation = "Insufficient data for walk-forward analysis"
            return result
        
        # Calculate number of periods
        period_length = wf_config.in_sample_days + wf_config.out_of_sample_days
        num_periods = (total_days - period_length) // wf_config.step_days + 1
        
        result.total_periods = num_periods
        
        periods = []
        all_in_sample_trades = []
        all_out_sample_trades = []
        
        current_start = 0
        
        for period_num in range(num_periods):
            # Update progress
            if job_id:
                self._update_job_progress(
                    job_id,
                    (period_num / num_periods) * 100,
                    f"Walk-forward period {period_num + 1}/{num_periods}..."
                )
            
            # Calculate period boundaries (in bar indices)
            in_sample_end = current_start + wf_config.in_sample_days
            out_sample_end = in_sample_end + wf_config.out_of_sample_days
            
            if out_sample_end > len(all_bars):
                break
                
            # Split bars
            in_sample_bars = all_bars[current_start:in_sample_end]
            out_sample_bars = all_bars[in_sample_end:out_sample_end]
            
            # Run strategy on in-sample
            in_trades, _ = await self._simulate_strategy(
                symbol, in_sample_bars, strategy, 100000
            )
            
            # Run strategy on out-of-sample
            out_trades, _ = await self._simulate_strategy(
                symbol, out_sample_bars, strategy, 100000
            )
            
            # Skip periods with too few trades
            if len(in_trades) < wf_config.min_trades_per_period:
                current_start += wf_config.step_days
                continue
            
            all_in_sample_trades.extend(in_trades)
            all_out_sample_trades.extend(out_trades)
            
            # Calculate period metrics
            in_win_rate = len([t for t in in_trades if t.pnl > 0]) / len(in_trades) if in_trades else 0
            out_win_rate = len([t for t in out_trades if t.pnl > 0]) / len(out_trades) if out_trades else 0
            
            period_data = {
                "period": period_num + 1,
                "in_sample_start": in_sample_bars[0]["timestamp"][:10] if in_sample_bars else "",
                "in_sample_end": in_sample_bars[-1]["timestamp"][:10] if in_sample_bars else "",
                "out_sample_start": out_sample_bars[0]["timestamp"][:10] if out_sample_bars else "",
                "out_sample_end": out_sample_bars[-1]["timestamp"][:10] if out_sample_bars else "",
                "in_sample_trades": len(in_trades),
                "out_sample_trades": len(out_trades),
                "in_sample_win_rate": round(in_win_rate * 100, 1),
                "out_sample_win_rate": round(out_win_rate * 100, 1),
                "in_sample_pnl": sum(t.pnl for t in in_trades),
                "out_sample_pnl": sum(t.pnl for t in out_trades)
            }
            periods.append(period_data)
            
            # Move to next period
            current_start += wf_config.step_days
        
        result.periods = periods
        
        # Calculate overall metrics
        if all_in_sample_trades:
            result.in_sample_win_rate = len([t for t in all_in_sample_trades if t.pnl > 0]) / len(all_in_sample_trades) * 100
            in_winners = sum(t.pnl for t in all_in_sample_trades if t.pnl > 0)
            in_losers = abs(sum(t.pnl for t in all_in_sample_trades if t.pnl < 0))
            result.in_sample_profit_factor = in_winners / in_losers if in_losers > 0 else 0
            
        if all_out_sample_trades:
            result.out_of_sample_win_rate = len([t for t in all_out_sample_trades if t.pnl > 0]) / len(all_out_sample_trades) * 100
            out_winners = sum(t.pnl for t in all_out_sample_trades if t.pnl > 0)
            out_losers = abs(sum(t.pnl for t in all_out_sample_trades if t.pnl < 0))
            result.out_of_sample_profit_factor = out_winners / out_losers if out_losers > 0 else 0
        
        # Calculate efficiency ratio
        if result.in_sample_win_rate > 0:
            result.efficiency_ratio = (result.out_of_sample_win_rate / result.in_sample_win_rate) * 100
        
        # Determine robustness
        result.is_robust = result.efficiency_ratio >= 70
        
        if result.efficiency_ratio >= 90:
            result.recommendation = "Excellent robustness! Strategy performs consistently in unseen data."
        elif result.efficiency_ratio >= 70:
            result.recommendation = "Good robustness. Strategy is likely not overfit."
        elif result.efficiency_ratio >= 50:
            result.recommendation = "Moderate robustness. Some overfitting may be present. Consider simplifying rules."
        else:
            result.recommendation = "Poor robustness. Strategy is likely overfit to historical data. Do not trade live."
        
        # Store result
        if self._backtest_results_col is not None:
            self._backtest_results_col.insert_one(result.to_dict())
        
        return result

    # ========================================================================
    # Monte Carlo Simulation
    # ========================================================================
    
    async def run_monte_carlo(
        self,
        trades: List[BacktestTrade] = None,
        backtest_id: str = None,
        mc_config: MonteCarloConfig = None,
        starting_capital: float = 100000.0,
        job_id: str = None
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation on backtest trades to understand
        the range of possible outcomes.
        
        Args:
            trades: List of trades to simulate (or provide backtest_id)
            backtest_id: ID of existing backtest to load trades from
            mc_config: Monte Carlo configuration
            starting_capital: Starting capital for simulations
            job_id: Optional job ID for progress tracking
            
        Returns:
            MonteCarloResult with distribution analysis
        """
        start_time = datetime.now(timezone.utc)
        
        if mc_config is None:
            mc_config = MonteCarloConfig()
            
        result = MonteCarloResult(
            id=f"mc_{uuid.uuid4().hex[:12]}",
            num_simulations=mc_config.num_simulations,
            created_at=start_time.isoformat()
        )
        
        # Load trades if backtest_id provided
        if trades is None and backtest_id:
            stored = await self.get_backtest_result(backtest_id)
            if stored and "trades" in stored:
                trades = [BacktestTrade(**t) for t in stored["trades"]]
                result.strategy_name = stored.get("name", "")
        
        if not trades or len(trades) < 5:
            result.recommendation = "Insufficient trades for Monte Carlo simulation (need at least 5)"
            return result
        
        result.original_trades = len(trades)
        result.original_total_pnl = sum(t.pnl for t in trades)
        result.original_win_rate = len([t for t in trades if t.pnl > 0]) / len(trades) * 100
        
        # Calculate original max drawdown
        equity = starting_capital
        peak = equity
        max_dd = 0
        for trade in trades:
            equity += trade.pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
        result.original_max_drawdown = max_dd
        
        # Run simulations
        pnl_results = []
        drawdown_results = []
        win_streak_results = []
        lose_streak_results = []
        
        for sim_num in range(mc_config.num_simulations):
            # Update progress periodically
            if job_id and sim_num % 1000 == 0:
                self._update_job_progress(
                    job_id,
                    (sim_num / mc_config.num_simulations) * 100,
                    f"Running simulation {sim_num + 1}/{mc_config.num_simulations}..."
                )

            # Build the trade sequence for this simulation
            if mc_config.bootstrap:
                # Bootstrap: sample with replacement — produces a REAL distribution
                # of P&L outcomes (simulates "a different run of N trades from the
                # same underlying edge"). Without this, total P&L is deterministic
                # and every percentile collapses to the same value.
                sample_size = mc_config.bootstrap_sample_size or len(trades)
                sim_trades = [random.choice(trades) for _ in range(sample_size)]
                # Make fresh copies so randomize_trade_size mutations don't leak
                # back into the original trade list.
                sim_trades = [BacktestTrade(**{**t.__dict__}) for t in sim_trades]
            else:
                # Legacy shuffle-only behavior (note: pnl_distribution will be
                # degenerate unless randomize_trade_size is enabled).
                sim_trades = trades.copy()
                if mc_config.randomize_trade_order:
                    random.shuffle(sim_trades)

            # Optionally randomize trade sizes
            if mc_config.randomize_trade_size:
                variation = mc_config.size_variation_pct / 100
                for t in sim_trades:
                    factor = 1 + random.uniform(-variation, variation)
                    t.pnl *= factor
            
            # Calculate simulation metrics
            equity = starting_capital
            peak = equity
            max_dd = 0
            current_streak = 0
            max_win_streak = 0
            max_lose_streak = 0
            
            for trade in sim_trades:
                equity += trade.pnl
                peak = max(peak, equity)
                dd = (peak - equity) / peak * 100
                max_dd = max(max_dd, dd)
                
                # Track streaks
                if trade.pnl > 0:
                    if current_streak > 0:
                        current_streak += 1
                    else:
                        max_lose_streak = max(max_lose_streak, abs(current_streak))
                        current_streak = 1
                    max_win_streak = max(max_win_streak, current_streak)
                else:
                    if current_streak < 0:
                        current_streak -= 1
                    else:
                        max_win_streak = max(max_win_streak, current_streak)
                        current_streak = -1
                    max_lose_streak = max(max_lose_streak, abs(current_streak))
            
            final_pnl = equity - starting_capital
            pnl_results.append(final_pnl)
            drawdown_results.append(max_dd)
            win_streak_results.append(max_win_streak)
            lose_streak_results.append(max_lose_streak)
        
        # Calculate distributions
        pnl_results.sort()
        drawdown_results.sort()
        
        result.pnl_distribution = self._calculate_percentiles(
            pnl_results, mc_config.confidence_levels
        )
        result.drawdown_distribution = self._calculate_percentiles(
            drawdown_results, mc_config.confidence_levels
        )
        result.win_streak_distribution = {
            "min": min(win_streak_results),
            "max": max(win_streak_results),
            "avg": statistics.mean(win_streak_results),
            "median": statistics.median(win_streak_results)
        }
        result.lose_streak_distribution = {
            "min": min(lose_streak_results),
            "max": max(lose_streak_results),
            "avg": statistics.mean(lose_streak_results),
            "median": statistics.median(lose_streak_results)
        }
        
        # Risk metrics
        result.probability_of_profit = len([p for p in pnl_results if p > 0]) / len(pnl_results) * 100
        result.probability_of_ruin = len([d for d in drawdown_results if d > 50]) / len(drawdown_results) * 100
        result.expected_max_drawdown = result.drawdown_distribution.get("50", 0)
        result.worst_case_drawdown = result.drawdown_distribution.get("95", 0)
        
        # Risk assessment
        if result.worst_case_drawdown <= 15:
            result.risk_assessment = "LOW"
            result.recommendation = "Risk is well-controlled. Strategy shows consistent performance across simulations."
        elif result.worst_case_drawdown <= 25:
            result.risk_assessment = "MEDIUM"
            result.recommendation = "Moderate risk. Consider reducing position sizes by 20-30% to limit drawdowns."
        elif result.worst_case_drawdown <= 40:
            result.risk_assessment = "HIGH"
            result.recommendation = "High risk. Reduce position sizes significantly or add filters to improve consistency."
        else:
            result.risk_assessment = "EXTREME"
            result.recommendation = "Extreme risk! Strategy shows potential for catastrophic drawdowns. Do not trade without major modifications."
        
        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Store result
        if self._backtest_results_col is not None:
            self._backtest_results_col.insert_one(result.to_dict())
        
        return result
    
    def _calculate_percentiles(self, values: List[float], levels: List[float]) -> Dict:
        """Calculate percentiles for a list of values"""
        result = {}
        n = len(values)
        for level in levels:
            idx = int(level * n)
            idx = max(0, min(idx, n - 1))
            percentile_key = str(int(level * 100))
            result[percentile_key] = round(values[idx], 2)
        return result

    # ========================================================================
    # AI Comparison Backtest
    # ========================================================================
    
    async def run_ai_comparison_backtest(
        self,
        symbols: List[str],
        strategy: StrategyConfig,
        filters: BacktestFilters = None,
        starting_capital: float = 100000.0,
        ai_confidence_threshold: float = 0.5,
        ai_lookback_bars: int = 50,
        job_id: str = None
    ) -> AIComparisonResult:
        """
        Run a three-way comparison backtest:
        1. Setup-only: Traditional entry signals (no AI)
        2. AI+Setup: Entry requires both setup signal AND AI confirmation
        3. AI-only: Only enter when AI predicts "up" (ignore setup signals)
        
        This answers: "Does the AI actually improve trading results?"
        """
        start_time = datetime.now(timezone.utc)
        
        if filters is None:
            filters = BacktestFilters(
                start_date=(datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d"),
                end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
        
        result = AIComparisonResult(
            id=f"ai_cmp_{uuid.uuid4().hex[:12]}",
            created_at=start_time.isoformat(),
            symbols=symbols,
            strategy_name=strategy.name,
            setup_type=strategy.setup_type,
            date_range=f"{filters.start_date} to {filters.end_date}",
            ai_model_version=getattr(self._timeseries_model, '_version', 'unknown') if self._timeseries_model else 'none',
            ai_confidence_threshold=ai_confidence_threshold
        )
        
        has_ai = self._timeseries_model is not None and getattr(self._timeseries_model, '_model', None) is not None
        has_gate = self._confidence_gate is not None
        
        # Aggregate trades across all symbols for each mode
        all_setup_trades = []
        all_ai_filtered_trades = []
        all_ai_only_trades = []
        all_gate_filtered_trades = []
        all_setup_equity = []
        all_ai_filtered_equity = []
        all_ai_only_equity = []
        all_gate_filtered_equity = []
        symbol_details = []
        gate_aggregate_stats = {"evaluated": 0, "go": 0, "reduce": 0, "skip": 0}
        
        total_ai_signals_correct = 0
        total_ai_signals = 0
        total_ai_rejections_correct = 0
        total_ai_rejections = 0
        
        for sym_idx, symbol in enumerate(symbols):
            if job_id:
                self._update_job_progress(
                    job_id,
                    (sym_idx / len(symbols)) * 100,
                    f"Processing {symbol} ({sym_idx + 1}/{len(symbols)})..."
                )
            
            # Get historical bars
            bars = await self._get_cached_bars(
                symbol, "1Day",
                filters.start_date,
                filters.end_date
            )
            
            if not bars or len(bars) < ai_lookback_bars + 10:
                continue
            
            filtered_bars = self._apply_filters(bars, filters)
            if not filtered_bars or len(filtered_bars) < ai_lookback_bars + 10:
                continue
            
            # --- MODE 1: Setup-only ---
            setup_trades, setup_equity = await self._simulate_strategy(
                symbol, filtered_bars, strategy, starting_capital
            )
            
            # --- MODE 2: AI+Setup (AI filters setup signals) ---
            ai_filtered_trades = []
            ai_only_trades = []
            
            if has_ai:
                ai_filtered_trades, ai_filtered_equity_curve = await self._simulate_strategy_with_ai(
                    symbol, filtered_bars, strategy, starting_capital,
                    ai_mode="filter",
                    confidence_threshold=ai_confidence_threshold,
                    lookback_bars=ai_lookback_bars
                )
                
                # --- MODE 3: AI-only (ignore setup, use AI predictions) ---
                ai_only_trades, ai_only_equity_curve = await self._simulate_strategy_with_ai(
                    symbol, filtered_bars, strategy, starting_capital,
                    ai_mode="standalone",
                    confidence_threshold=ai_confidence_threshold,
                    lookback_bars=ai_lookback_bars
                )
            else:
                ai_filtered_trades = setup_trades  # Same as setup if no AI
                ai_filtered_equity_curve = setup_equity
                ai_only_trades = []
                ai_only_equity_curve = []
            
            # --- MODE 4: Gate-Filtered (full 10-signal confidence gate) ---
            gate_trades = []
            gate_equity_curve = []
            if has_gate:
                gate_trades, gate_equity_curve, gate_stats = await self._simulate_strategy_with_gate(
                    symbol, filtered_bars, strategy, starting_capital,
                    lookback_bars=ai_lookback_bars
                )
                for k in gate_aggregate_stats:
                    gate_aggregate_stats[k] += gate_stats.get(k, 0)
            
            # Track per-symbol results
            setup_pnl = sum(t.pnl for t in setup_trades)
            ai_filt_pnl = sum(t.pnl for t in ai_filtered_trades)
            ai_only_pnl = sum(t.pnl for t in ai_only_trades)
            gate_pnl = sum(t.pnl for t in gate_trades)
            
            setup_wr = (len([t for t in setup_trades if t.pnl > 0]) / len(setup_trades) * 100) if setup_trades else 0
            ai_filt_wr = (len([t for t in ai_filtered_trades if t.pnl > 0]) / len(ai_filtered_trades) * 100) if ai_filtered_trades else 0
            ai_only_wr = (len([t for t in ai_only_trades if t.pnl > 0]) / len(ai_only_trades) * 100) if ai_only_trades else 0
            gate_wr = (len([t for t in gate_trades if t.pnl > 0]) / len(gate_trades) * 100) if gate_trades else 0
            
            symbol_details.append({
                "symbol": symbol,
                "setup_only": {"trades": len(setup_trades), "pnl": round(setup_pnl, 2), "win_rate": round(setup_wr, 1)},
                "ai_filtered": {"trades": len(ai_filtered_trades), "pnl": round(ai_filt_pnl, 2), "win_rate": round(ai_filt_wr, 1)},
                "ai_only": {"trades": len(ai_only_trades), "pnl": round(ai_only_pnl, 2), "win_rate": round(ai_only_wr, 1)},
                "gate_filtered": {"trades": len(gate_trades), "pnl": round(gate_pnl, 2), "win_rate": round(gate_wr, 1)},
            })
            
            all_setup_trades.extend(setup_trades)
            all_ai_filtered_trades.extend(ai_filtered_trades)
            all_ai_only_trades.extend(ai_only_trades)
            all_gate_filtered_trades.extend(gate_trades)
            all_setup_equity.extend(setup_equity)
            all_ai_filtered_equity.extend(ai_filtered_equity_curve if has_ai else setup_equity)
            all_ai_only_equity.extend(ai_only_equity_curve if has_ai else [])
            all_gate_filtered_equity.extend(gate_equity_curve)
        
        # Calculate aggregate metrics for each mode
        result.setup_only = self._compute_mode_metrics(all_setup_trades, starting_capital)
        result.ai_filtered = self._compute_mode_metrics(all_ai_filtered_trades, starting_capital) if has_ai else result.setup_only
        result.ai_only = self._compute_mode_metrics(all_ai_only_trades, starting_capital) if has_ai else {}
        result.gate_filtered = self._compute_mode_metrics(all_gate_filtered_trades, starting_capital) if has_gate else {}
        result.gate_stats = gate_aggregate_stats if has_gate else {}
        
        # Comparison metrics
        if has_ai and all_setup_trades:
            result.ai_trades_filtered = len(all_setup_trades) - len(all_ai_filtered_trades)
            result.ai_filter_rate = round(result.ai_trades_filtered / len(all_setup_trades) * 100, 1) if all_setup_trades else 0
            result.ai_win_rate_improvement = round(
                result.ai_filtered.get("win_rate", 0) - result.setup_only.get("win_rate", 0), 2
            )
            result.ai_pnl_improvement = round(
                result.ai_filtered.get("total_pnl", 0) - result.setup_only.get("total_pnl", 0), 2
            )
            result.ai_sharpe_improvement = round(
                result.ai_filtered.get("sharpe_ratio", 0) - result.setup_only.get("sharpe_ratio", 0), 3
            )
        
        result.symbol_results = symbol_details
        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Generate recommendation
        if not has_ai:
            result.recommendation = "No AI model available. Train the time-series model first to enable AI comparison."
        elif result.ai_win_rate_improvement > 5:
            result.recommendation = f"AI filter significantly improves results (+{result.ai_win_rate_improvement:.1f}% win rate). Consider enabling AI confirmation for live trading."
        elif result.ai_win_rate_improvement > 0:
            result.recommendation = f"AI filter shows modest improvement (+{result.ai_win_rate_improvement:.1f}% win rate). AI adds marginal edge."
        elif result.ai_win_rate_improvement > -3:
            result.recommendation = f"AI filter has minimal impact ({result.ai_win_rate_improvement:+.1f}% win rate). Setup signals are already well-calibrated."
        else:
            result.recommendation = f"AI filter reduces performance ({result.ai_win_rate_improvement:+.1f}% win rate). The model may need retraining or the threshold should be adjusted."
        
        # Store result
        if self._backtest_results_col is not None:
            await asyncio.to_thread(self._backtest_results_col.insert_one, result.to_dict())
        
        if job_id:
            self._update_job_progress(job_id, 100, "AI comparison complete")
        
        return result
    
    async def _simulate_strategy_with_ai(
        self,
        symbol: str,
        bars: List[Dict],
        strategy: StrategyConfig,
        starting_capital: float,
        ai_mode: str = "filter",
        confidence_threshold: float = 0.5,
        lookback_bars: int = 50
    ) -> Tuple[List[BacktestTrade], List[Dict]]:
        """
        Simulate a strategy with AI predictions integrated.

        ai_mode:
          "filter"     - Only enter when BOTH setup signal AND AI agrees with strategy direction
          "standalone" - Enter whenever AI predicts in strategy direction with sufficient confidence

        Note: Honors the strategy's direction. For SHORT_ setups, entry requires
        AI prediction "down" (not "up"), stop/target/P&L flip accordingly.
        Previously hardcoded to long-only, which silently rejected ~99% of short
        signals because AI predictions for shorts were "down" but filter checked "up".
        """
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []

        capital = starting_capital
        in_position = False
        current_trade: BacktestTrade = None

        # Determine strategy direction ONCE (all trades in this call share it)
        is_short = strategy.setup_type.lower().startswith("short_")
        trade_direction = "short" if is_short else "long"
        required_ai_direction = "down" if is_short else "up"

        for i, bar in enumerate(bars):
            current_price = bar.get("close", bar.get("c", 0))
            timestamp = bar.get("timestamp", "")
            high = bar.get("high", bar.get("h", current_price))
            low = bar.get("low", bar.get("l", current_price))

            # Track equity — P&L direction-aware
            equity = capital
            if in_position and current_trade:
                if is_short:
                    unrealized_pnl = (current_trade.entry_price - current_price) * current_trade.shares
                else:
                    unrealized_pnl = (current_price - current_trade.entry_price) * current_trade.shares
                equity = capital + unrealized_pnl

                if unrealized_pnl > current_trade.max_favorable_excursion:
                    current_trade.max_favorable_excursion = unrealized_pnl
                if unrealized_pnl < current_trade.max_adverse_excursion:
                    current_trade.max_adverse_excursion = unrealized_pnl
            
            equity_curve.append({"timestamp": timestamp, "equity": equity, "price": current_price})
            
            if in_position and current_trade:
                current_trade.bars_held += 1

                # Exit logic — direction-aware
                exit_price = None
                exit_reason = ""

                if is_short:
                    # Short: stop is ABOVE entry, target is BELOW entry
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = current_price
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = current_price
                        exit_reason = "end_of_data"
                else:
                    # Long: stop is BELOW entry, target is ABOVE entry
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = current_price
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = current_price
                        exit_reason = "end_of_data"

                if exit_price:
                    current_trade.exit_price = exit_price
                    current_trade.exit_date = timestamp[:10]
                    current_trade.exit_time = timestamp[11:19] if len(timestamp) > 10 else ""
                    current_trade.exit_reason = exit_reason

                    # P&L direction-aware
                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100
                        risk = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100
                        risk = current_trade.entry_price - current_trade.stop_price

                    if risk > 0:
                        current_trade.r_multiple = current_trade.pnl / (risk * current_trade.shares)

                    trades.append(current_trade)
                    capital += current_trade.pnl
                    in_position = False
                    current_trade = None

            else:
                # Entry decision depends on mode
                enter = False

                if ai_mode == "filter":
                    # Require setup signal AND AI confirmation IN THE STRATEGY'S DIRECTION
                    setup_signal = self._check_entry_signal(bar, strategy, bars[:i+1])
                    if setup_signal and i >= lookback_bars:
                        ai_prediction = self._get_ai_prediction(bars[:i+1], symbol, lookback_bars)
                        if (ai_prediction
                            and ai_prediction.direction == required_ai_direction
                            and ai_prediction.confidence >= confidence_threshold):
                            enter = True

                elif ai_mode == "standalone":
                    # Only use AI prediction (ignore setup signals) — again honoring direction
                    if i >= lookback_bars:
                        ai_prediction = self._get_ai_prediction(bars[:i+1], symbol, lookback_bars)
                        if (ai_prediction
                            and ai_prediction.direction == required_ai_direction
                            and ai_prediction.confidence >= confidence_threshold):
                            # Basic price/volume filters still apply
                            volume = bar.get("volume", bar.get("v", 0))
                            if volume >= 100000 and 5.0 <= current_price <= 500.0:
                                enter = True

                if enter:
                    position_value = capital * (strategy.position_size_pct / 100)
                    shares = int(position_value / current_price)

                    if shares > 0:
                        # Direction-aware stop/target
                        if is_short:
                            stop_price = current_price * (1 + strategy.stop_pct / 100)
                            target_price = current_price * (1 - strategy.target_pct / 100)
                        else:
                            stop_price = current_price * (1 - strategy.stop_pct / 100)
                            target_price = current_price * (1 + strategy.target_pct / 100)

                        current_trade = BacktestTrade(
                            id=f"t_{uuid.uuid4().hex[:8]}",
                            symbol=symbol,
                            strategy_name=strategy.name,
                            setup_type=strategy.setup_type,
                            direction=trade_direction,
                            entry_date=timestamp[:10],
                            entry_time=timestamp[11:19] if len(timestamp) > 10 else "",
                            entry_price=current_price,
                            shares=shares,
                            stop_price=stop_price,
                            target_price=target_price,
                            bars_held=0
                        )
                        in_position = True

        return trades, equity_curve
    
    def _get_ai_prediction(self, bars_up_to_now: List[Dict], symbol: str, lookback: int):
        """Get AI prediction for the current bar using lookback window of historical bars"""
        if self._timeseries_model is None:
            return None
        
        try:
            # The model expects bars in most-recent-first order
            recent_bars = list(reversed(bars_up_to_now[-lookback:]))
            prediction = self._timeseries_model.predict(recent_bars, symbol=symbol)
            return prediction
        except Exception as e:
            logger.debug(f"AI prediction error for {symbol}: {e}")
            return None

    async def _simulate_strategy_with_gate(
        self,
        symbol: str,
        bars: List[Dict],
        strategy: StrategyConfig,
        starting_capital: float,
        lookback_bars: int = 50
    ) -> Tuple[List[BacktestTrade], List[Dict]]:
        """
        Simulate a strategy with the full 10-signal confidence gate.
        Only enters trades when setup signal fires AND the gate returns GO or REDUCE.
        Position size is adjusted by the gate's position_multiplier.
        
        This is the most realistic backtest mode — matches live trading behavior.

        Direction-aware as of 2026-04-22 (P1 fix for "simulated exit ignores
        stops on SHORT setups"). Previously long-only: SHORT setups got stops
        computed BELOW entry (impossible to hit), targets ABOVE entry (also
        impossible), and P&L math was unsigned — so every SHORT revalidation
        either time-exited at break-even or mis-reported P&L. Now branches
        on `strategy.setup_type.startswith("short_")` at entry + exit + P&L.
        """
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []

        capital = starting_capital
        in_position = False
        current_trade: BacktestTrade = None
        gate = self._confidence_gate

        gate_stats = {"evaluated": 0, "go": 0, "reduce": 0, "skip": 0}

        # ── Direction resolved ONCE per strategy — mirrors _simulate_strategy_with_ai
        is_short = strategy.setup_type.lower().startswith("short_")
        trade_direction = "short" if is_short else "long"

        for i, bar in enumerate(bars):
            current_price = bar.get("close", bar.get("c", 0))
            timestamp = bar.get("timestamp", "")
            high = bar.get("high", bar.get("h", current_price))
            low = bar.get("low", bar.get("l", current_price))

            # Track equity — direction-aware unrealized P&L
            equity = capital
            if in_position and current_trade:
                if is_short:
                    unrealized_pnl = (current_trade.entry_price - current_price) * current_trade.shares
                else:
                    unrealized_pnl = (current_price - current_trade.entry_price) * current_trade.shares
                equity = capital + unrealized_pnl

                if unrealized_pnl > current_trade.max_favorable_excursion:
                    current_trade.max_favorable_excursion = unrealized_pnl
                if unrealized_pnl < current_trade.max_adverse_excursion:
                    current_trade.max_adverse_excursion = unrealized_pnl

            equity_curve.append({"timestamp": timestamp, "equity": equity, "price": current_price})

            if in_position and current_trade:
                current_trade.bars_held += 1

                # Exit logic — direction-aware (bug fix 2026-04-22)
                exit_price = None
                exit_reason = ""

                if is_short:
                    # SHORT: stop ABOVE entry (hit when high rises), target BELOW (hit when low falls)
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                else:
                    # LONG: stop BELOW entry (hit when low falls), target ABOVE (hit when high rises)
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"

                # Time / end-of-data exits apply to both directions
                if exit_price is None and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = current_price
                    exit_reason = "time"
                elif exit_price is None and i == len(bars) - 1:
                    exit_price = current_price
                    exit_reason = "end_of_data"

                if exit_price:
                    current_trade.exit_price = exit_price
                    current_trade.exit_date = timestamp[:10]
                    current_trade.exit_time = timestamp[11:19] if len(timestamp) > 10 else ""
                    current_trade.exit_reason = exit_reason

                    # P&L direction-aware
                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.entry_price - current_trade.stop_price

                    if risk_per_share > 0:
                        current_trade.r_multiple = current_trade.pnl / (risk_per_share * current_trade.shares)

                    trades.append(current_trade)
                    capital += current_trade.pnl
                    in_position = False
                    current_trade = None

            else:
                # Check setup signal first
                setup_signal = self._check_entry_signal(bar, strategy, bars[:i+1])
                if setup_signal and i >= lookback_bars:
                    # Run the full confidence gate — pass the real strategy direction
                    gate_stats["evaluated"] += 1
                    try:
                        # Compute stop/target up-front so we can feed them to the gate
                        if is_short:
                            stop_price = current_price * (1 + strategy.stop_pct / 100)
                            target_price = current_price * (1 - strategy.target_pct / 100)
                        else:
                            stop_price = current_price * (1 - strategy.stop_pct / 100)
                            target_price = current_price * (1 + strategy.target_pct / 100)

                        gate_result = await gate.evaluate(
                            symbol=symbol,
                            setup_type=strategy.setup_type,
                            direction=trade_direction,
                            quality_score=70,  # Default quality for backtest
                            entry_price=current_price,
                            stop_price=stop_price,
                        )

                        decision = gate_result.get("decision", "SKIP")
                        position_multiplier = gate_result.get("position_multiplier", 1.0)

                        if decision in ("GO", "REDUCE"):
                            gate_stats["go" if decision == "GO" else "reduce"] += 1
                            position_value = capital * (strategy.position_size_pct / 100) * position_multiplier
                            shares = int(position_value / current_price)

                            if shares > 0:
                                current_trade = BacktestTrade(
                                    id=f"t_{uuid.uuid4().hex[:8]}",
                                    symbol=symbol,
                                    strategy_name=strategy.name,
                                    setup_type=strategy.setup_type,
                                    direction=trade_direction,
                                    entry_date=timestamp[:10],
                                    entry_time=timestamp[11:19] if len(timestamp) > 10 else "",
                                    entry_price=current_price,
                                    shares=shares,
                                    stop_price=stop_price,
                                    target_price=target_price,
                                    bars_held=0
                                )
                                in_position = True

                        else:
                            gate_stats["skip"] += 1

                    except Exception as e:
                        logger.debug(f"Gate evaluation error for {symbol}: {e}")
                        gate_stats["skip"] += 1

        return trades, equity_curve, gate_stats
    
    def _compute_mode_metrics(self, trades: List[BacktestTrade], starting_capital: float) -> Dict:
        """Compute aggregate metrics for a set of trades"""
        if not trades:
            return {
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
                "avg_winner": 0, "avg_loser": 0, "profit_factor": 0,
                "total_r": 0, "avg_r": 0, "sharpe_ratio": 0,
                "max_drawdown_pct": 0
            }
        
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl < 0]
        
        gross_profit = sum(t.pnl for t in winning) if winning else 0
        gross_loss = abs(sum(t.pnl for t in losing)) if losing else 0
        
        r_values = [t.r_multiple for t in trades if t.r_multiple != 0]
        
        # Sharpe
        returns = [t.pnl_percent for t in trades]
        sharpe = 0
        if len(returns) > 1:
            avg_r = statistics.mean(returns)
            std_r = statistics.stdev(returns)
            sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
        
        # Max drawdown
        equity = starting_capital
        peak = equity
        max_dd = 0
        for t in trades:
            equity += t.pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(len(winning) / len(trades) * 100, 2),
            "total_pnl": round(sum(t.pnl for t in trades), 2),
            "avg_pnl": round(sum(t.pnl for t in trades) / len(trades), 2),
            "avg_winner": round(gross_profit / len(winning), 2) if winning else 0,
            "avg_loser": round(-gross_loss / len(losing), 2) if losing else 0,
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else 0,
            "total_r": round(sum(r_values), 2),
            "avg_r": round(statistics.mean(r_values), 3) if r_values else 0,
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2)
        }

    # ========================================================================
    # Market-Wide Backtest (Full US Market Scanning)
    # ========================================================================
    
    async def run_market_wide_backtest(
        self,
        strategy: StrategyConfig,
        filters: BacktestFilters = None,
        symbols: List[str] = None,
        trade_style: str = "swing",
        bar_size: str = "1 day",
        starting_capital: float = 100000.0,
        max_symbols: int = 1500,
        use_multi_timeframe: bool = False,
        job_id: str = None
    ) -> Dict[str, Any]:
        """
        Run a strategy against the entire US market to find all historical trades.
        
        This answers: "Where would this strategy have triggered across all US stocks
        in the given time period, and what would the results have been?"
        
        Multi-Timeframe Analysis (when use_multi_timeframe=True):
        - Uses higher timeframe (daily) to determine trend direction
        - Uses specified bar_size for entry signal detection
        - Only takes trades aligned with higher timeframe trend
        
        Args:
            strategy: Strategy configuration to test
            filters: Date and market filters
            symbols: Optional list of symbols (if None, fetches full market)
            trade_style: 'intraday', 'swing', or 'investment' for pre-filtering
            bar_size: Bar size for simulation (e.g., '1 day', '5 mins', '1 min')
            starting_capital: Capital per trade calculation
            max_symbols: Maximum symbols to scan (default 1500 for comprehensive coverage)
            use_multi_timeframe: Enable multi-timeframe analysis (higher TF trend confirmation)
            job_id: Optional job ID for progress tracking
            
        Returns:
            Dict with all trades found, grouped by symbol, with summary stats
        """
        start_time = datetime.now(timezone.utc)
        result_id = f"mw_{uuid.uuid4().hex[:12]}"
        
        if filters is None:
            filters = BacktestFilters()
            # Default to last 30 days if not specified
            if not filters.end_date:
                filters.end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if not filters.start_date:
                start = datetime.now(timezone.utc) - timedelta(days=30)
                filters.start_date = start.strftime("%Y-%m-%d")
        
        # Get symbol universe if not provided
        if symbols is None:
            symbols = await self._get_market_symbols(trade_style, max_symbols)
        
        logger.info(f"Market-wide backtest starting: {strategy.name} on {len(symbols)} symbols")
        
        # Track progress
        total_symbols = len(symbols)
        processed = 0
        
        # Results containers
        all_trades: List[Dict] = []
        trades_by_symbol: Dict[str, List[Dict]] = {}
        symbols_with_trades: List[str] = []
        symbols_no_trades: List[str] = []
        errors: List[str] = []
        
        # Volume/price filters based on trade style
        min_price = 5.0
        max_price = 500.0
        min_volume = 100000
        
        if trade_style == "intraday":
            min_volume = 500000
            min_price = 10.0
            max_price = 200.0
        elif trade_style == "investment":
            min_volume = 50000
            max_price = 1000.0
        
        # Normalize bar_size to IB format and use it for primary timeframe
        normalized_bar_size = self._normalize_bar_size(bar_size)
        primary_timeframe = normalized_bar_size
        
        # Multi-timeframe setup: higher TF for trend, lower TF for entry
        higher_timeframe = "1 day"  # Always use daily for trend confirmation
        use_mtf = use_multi_timeframe and primary_timeframe != "1 day"
        
        logger.info(f"Market-wide backtest: bar_size={normalized_bar_size}, multi_timeframe={use_mtf}")
        
        # Process symbols in batches
        batch_size = 25
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            for symbol in batch:
                try:
                    # Fetch primary timeframe data
                    bars = await self._get_cached_bars(
                        symbol=symbol,
                        timeframe=primary_timeframe,
                        start_date=filters.start_date,
                        end_date=filters.end_date
                    )
                    
                    if not bars or len(bars) < 10:
                        continue
                    
                    # Apply price/volume filters
                    last_price = bars[-1].get("close", 0)
                    avg_volume = sum(b.get("volume", 0) for b in bars[-20:]) / min(20, len(bars))
                    
                    if last_price < min_price or last_price > max_price:
                        continue
                    if avg_volume < min_volume:
                        continue
                    
                    # Multi-timeframe: Get higher timeframe trend
                    htf_trend = None
                    if use_mtf:
                        htf_bars = await self._get_cached_bars(
                            symbol=symbol,
                            timeframe=higher_timeframe,
                            start_date=filters.start_date,
                            end_date=filters.end_date
                        )
                        if htf_bars and len(htf_bars) >= 20:
                            htf_trend = self._determine_trend(htf_bars)
                    
                    # Run strategy simulation on this symbol
                    trades, equity_curve = await self._simulate_strategy(
                        bars=bars,
                        strategy=strategy,
                        starting_capital=starting_capital,
                        symbol=symbol,
                        htf_trend=htf_trend if use_mtf else None
                    )
                    
                    if trades:
                        # Convert trades to dicts
                        trade_dicts = [t.to_dict() if hasattr(t, 'to_dict') else t for t in trades]
                        
                        # Tag with timeframe info
                        for td in trade_dicts:
                            td["bar_size"] = normalized_bar_size
                            td["multi_timeframe"] = use_mtf
                            if use_mtf and htf_trend:
                                td["htf_trend"] = htf_trend
                        
                        all_trades.extend(trade_dicts)
                        trades_by_symbol[symbol] = trade_dicts
                        symbols_with_trades.append(symbol)
                    else:
                        symbols_no_trades.append(symbol)
                        
                except Exception as e:
                    errors.append(f"{symbol}: {str(e)}")
                    logger.debug(f"Error processing {symbol}: {e}")
                
                processed += 1
            
            # Update job progress
            if job_id and job_id in self._running_jobs:
                job = self._running_jobs[job_id]
                job.progress = int((processed / total_symbols) * 100)
            
            # Small delay between batches
            await asyncio.sleep(0.5)
        
        # Calculate summary statistics
        total_trades = len(all_trades)
        winning_trades = [t for t in all_trades if t.get("pnl", 0) > 0]
        losing_trades = [t for t in all_trades if t.get("pnl", 0) < 0]
        
        total_pnl = sum(t.get("pnl", 0) for t in all_trades)
        gross_profit = sum(t.get("pnl", 0) for t in winning_trades)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losing_trades))
        
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0
        avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0
        
        # Top performers
        top_trades = sorted(all_trades, key=lambda x: x.get("pnl", 0), reverse=True)[:20]
        worst_trades = sorted(all_trades, key=lambda x: x.get("pnl", 0))[:10]
        
        # Symbols with most trades
        symbols_by_trade_count = sorted(
            [(s, len(trades_by_symbol.get(s, []))) for s in symbols_with_trades],
            key=lambda x: x[1],
            reverse=True
        )[:20]
        
        # Build result
        result = {
            "id": result_id,
            "type": "market_wide_backtest",
            "strategy_name": strategy.name,
            "strategy_config": strategy.to_dict() if hasattr(strategy, 'to_dict') else asdict(strategy),
            "trade_style": trade_style,
            "filters": filters.to_dict() if hasattr(filters, 'to_dict') else asdict(filters),
            "created_at": start_time.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            
            # Scan stats
            "total_symbols_scanned": total_symbols,
            "symbols_with_signals": len(symbols_with_trades),
            "symbols_no_signals": len(symbols_no_trades),
            "errors_count": len(errors),
            
            # Performance metrics
            "summary": {
                "total_trades": total_trades,
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate": round(win_rate, 2),
                "total_pnl": round(total_pnl, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
                "profit_factor": round(profit_factor, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "expectancy": round((win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss), 2)
            },
            
            # Top performers
            "top_trades": top_trades,
            "worst_trades": worst_trades,
            "most_active_symbols": symbols_by_trade_count,
            
            # All trades (can be filtered client-side)
            "all_trades": all_trades,
            "trades_by_symbol": trades_by_symbol,
            
            # Lists
            "symbols_traded": symbols_with_trades,
        }
        
        # Store result
        if self._backtest_results_col is not None:
            # Store without full trade list to save space (trades stored separately)
            store_result = {k: v for k, v in result.items() if k not in ['all_trades', 'trades_by_symbol']}
            store_result["trade_count"] = total_trades
            self._backtest_results_col.insert_one(store_result)
        
        logger.info(f"Market-wide backtest complete: {total_trades} trades on {len(symbols_with_trades)} symbols")
        
        return result
    
    async def _get_market_symbols(self, trade_style: str, max_symbols: int) -> List[str]:
        """
        Get comprehensive list of liquid symbols for market-wide scanning.
        
        Uses 1,500+ curated symbols from diverse sectors:
        - Major ETFs (50+)
        - S&P 500 components (500)
        - NASDAQ 100 + high-growth tech (100)
        - High-volume speculative stocks (80)
        - Biotech & Healthcare (80)
        - Financials & REITs (80)
        - Energy & Materials (60)
        - Industrials & Defense (60)
        """
        
        # Try to get from market scanner service first
        if hasattr(self, '_market_scanner_service') and self._market_scanner_service:
            try:
                symbols_data = await self._market_scanner_service.get_symbol_universe()
                symbols = [s.get("symbol") for s in symbols_data[:max_symbols]]
                if symbols and len(symbols) >= 500:
                    logger.info(f"Got {len(symbols)} symbols from market scanner service")
                    return symbols
            except Exception as e:
                logger.warning(f"Could not get symbols from scanner service: {e}")
        
        # Check if we have collected IB data to prioritize those symbols
        symbols_with_data = []
        if self._db is not None:
            try:
                symbols_with_data = list(set(self._db["ib_historical_data"].distinct("symbol")))
                if symbols_with_data:
                    logger.info(f"Found {len(symbols_with_data)} symbols with collected IB data")
            except Exception:
                pass
        
        # Comprehensive symbol universe (1,500+)
        # Major ETFs (65)
        etfs = [
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "VEA", "VWO", "EFA",
            "IEMG", "VNQ", "BND", "AGG", "LQD", "TLT", "GLD", "SLV", "USO", "UNG",
            "XLF", "XLE", "XLK", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB",
            "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ", "SOXL", "SOXS", "TQQQ", "SQQQ",
            "UVXY", "VXX", "SVXY", "SPXU", "SPXS", "TNA", "TZA", "FAS", "FAZ",
            "HYG", "JNK", "EMB", "VIG", "SCHD", "VYM", "DVY", "JEPI", "JEPQ",
            "XBI", "IBB", "XOP", "OIH", "KRE", "XHB", "ITB", "KWEB", "FXI", "EWZ"
        ]
        
        # S&P 500 (sorted by market cap, comprehensive)
        sp500 = [
            # Top 100 by market cap
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH",
            "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA", "ABBV", "MRK",
            "LLY", "AVGO", "PEP", "KO", "COST", "TMO", "MCD", "WMT", "CSCO", "ACN",
            "ABT", "DHR", "NEE", "DIS", "VZ", "ADBE", "WFC", "PM", "TXN", "CRM",
            "NKE", "BMY", "RTX", "ORCL", "COP", "QCOM", "UPS", "HON", "T", "LOW",
            "MS", "INTC", "UNP", "CAT", "IBM", "BA", "INTU", "SPGI", "GS", "DE",
            "AMD", "BLK", "GILD", "AXP", "AMAT", "MDLZ", "CVS", "SBUX", "PLD", "ADI",
            "LMT", "ISRG", "MMC", "AMT", "SYK", "CI", "MO", "NOW", "ZTS", "CB",
            "TJX", "LRCX", "BKNG", "ADP", "SO", "REGN", "VRTX", "BSX", "PGR", "FISV",
            "CME", "SCHW", "BDX", "CL", "EOG", "MU", "ITW", "SNPS", "CDNS", "NOC",
            # 101-200
            "DUK", "SHW", "ICE", "CSX", "PNC", "ETN", "MCK", "FDX", "AON", "KLAC",
            "EQIX", "APD", "EMR", "TGT", "NSC", "AZO", "ORLY", "FCX", "PSA", "AEP",
            "PXD", "HUM", "MCHP", "GD", "ADSK", "MPC", "MSI", "WM", "TRV", "EW",
            "JCI", "SLB", "F", "GM", "OXY", "KMB", "MNST", "D", "HLT", "ROP",
            "CMG", "NXPI", "MAR", "AIG", "STZ", "FTNT", "IQV", "PAYX", "TEL", "A",
            "GIS", "EXC", "BIIB", "HES", "KHC", "YUM", "PCAR", "SYY", "CTSH", "AFL",
            "DOW", "VLO", "ROST", "PSX", "HAL", "WELL", "KMI", "ON", "IDXX", "MSCI",
            "WMB", "DVN", "EL", "CTAS", "CARR", "DXCM", "DD", "ODFL", "DHI", "GWW",
            "HSY", "WBD", "FAST", "EXR", "KEYS", "CPRT", "VRSK", "VMC", "ANSS", "CSGP",
            "IT", "CDW", "FANG", "AME", "MTD", "XYL", "TSCO", "BRO", "DOV", "HPQ",
            # 201-350
            "RMD", "WAT", "GPN", "LH", "FTV", "CHD", "BR", "IRM", "STE", "PTC",
            "HOLX", "TRGP", "WAB", "PKI", "ALGN", "MOH", "WST", "CINF", "MKC", "AVB",
            "NTRS", "MTB", "HBAN", "RF", "FE", "DTE", "VTR", "ARE", "LDOS", "CFG",
            "DGX", "TDY", "BIO", "NDAQ", "TER", "LKQ", "EXPD", "COO", "ATO", "FMC",
            "NI", "KEY", "JBHT", "POOL", "DPZ", "ETSY", "FICO", "URI", "TECH",
            "PKG", "AES", "J", "IP", "CCL", "BBY", "CPB", "AKAM", "TYL", "GL",
            "AAL", "UAL", "DAL", "LUV", "ALK", "JBLU", "SAVE", "HA",
            "K", "SJM", "HRL", "CAG", "LW", "BG", "ADM", "TSN", "PPC",
            "CLX", "SPB", "COTY", "TPR", "CPRI", "PVH", "RL",
            "NVR", "LEN", "PHM", "TOL", "MTH", "MDC", "KBH", "TMHC", "MHO",
            "HPE", "NTAP", "WDC", "STX", "PSTG", "DELL", "ZBRA", "JNPR", "ANET"
        ]
        
        # NASDAQ high-growth tech (100)
        nasdaq_growth = [
            "NFLX", "PYPL", "CMCSA", "PDD", "ABNB", "MELI", "WDAY", "TEAM", "ZS", "DDOG",
            "MDB", "NET", "CRWD", "PANW", "OKTA", "ZM", "DOCU", "SPLK", "SNOW", "PLTR",
            "U", "RBLX", "COIN", "HOOD", "SOFI", "UPST", "AFRM", "BILL", "HUBS", "TWLO",
            "RIVN", "LCID", "NIO", "XPEV", "LI", "GRAB", "SE", "SHOP", "SQ", "LSPD",
            "MARA", "RIOT", "BITF", "HUT", "CLSK", "CIFR", "IREN",
            "ROKU", "TTD", "MGNI", "APPS", "PUBM", "DV", "IAS", "ZETA", "BRZE",
            "CFLT", "MNDY", "PATH", "AI", "GTLB", "ESTC", "NEWR", "FROG", "PD",
            "APP", "BMBL", "MTCH", "PINS", "SNAP", "RDDT", "CPNG", "DUOL",
            "DOCN", "IONQ", "RGTI", "QBTS", "QUBT", "FORM",
            "LAZR", "INVZ", "OUST", "MVIS", "CINT"
        ]
        
        # High-volume speculative/meme stocks (80)
        high_volume = [
            "AMC", "GME", "SNDL", "TLRY", "CGC", "ACB", "CRON", "OGI", "HEXO",
            "SPCE", "PLUG", "FCEL", "BLDP", "BE", "CHPT", "QS", "GOEV", "FSR", "WKHS",
            "RIDE", "NKLA", "HYLN", "ARVL", "REE", "FFIE", "MULN", "PTRA", "LEV", "EVGO",
            "ATER", "CLOV", "WISH", "SKLZ", "SDC", "ROOT", "LMND", "OPEN",
            "RDFN", "CVNA", "CARG", "VRM", "STNE", "PAGS", "NU", "PSFE",
            "LC", "UWMC", "RKT", "TREE", "LDI", "COOP",
            "BB", "NOK", "EXPR", "KOSS", "PRTY", "BGFV", "DKNG", "PENN"
        ]
        
        # Biotech & Healthcare (80)
        biotech = [
            "MRNA", "BNTX", "NVAX", "SGEN", "ALNY", "INCY", "BMRN", "EXEL", "SRPT", "RARE",
            "IONS", "UTHR", "NBIX", "FOLD", "HALO", "ARWR", "PTCT", "BLUE",
            "EDIT", "CRSP", "NTLA", "BEAM", "VERV", "PRME", "RXRX", "DNA", "TWST",
            "CERS", "IOVA", "AGEN", "FATE",
            "ILMN", "EXAS", "GH", "NVTA", "PACB", "BNGO", "CDNA", "MYGN", "NEO",
            "HZNP", "JAZZ", "LGND", "SUPN", "PRGO", "PAHC", "CTLT", "TFX",
            "PODD", "TNDM", "IRTC", "OFIX", "NUVA", "GMED", "LIVN", "PEN", "INSP",
            "VEEV", "CNC"
        ]
        
        # Financials & REITs (80)
        financials = [
            "C", "USB", "FITB",
            "ZION", "CMA", "ALLY", "COF", "DFS",
            "SYF", "GPN", "FIS", "FLT", "WU",
            "MET", "PRU", "ALL", "HIG", "LNC", "AIZ", "KMPR", "PFG",
            "O", "VICI", "DLR", "CCI", "SBAC", "SPG", "AVB", "EQR", "MAA", "UDR",
            "CUBE", "LSI", "COLD", "REXR", "DRE", "FR", "STAG",
            "WPC", "ADC", "NNN", "STOR", "EPRT", "SRC", "FCPT", "GTY", "PINE", "GOOD",
            "AMH", "INVH", "Z", "ZG", "OPAD", "COMP", "RMAX"
        ]
        
        # Energy & Materials (60)
        energy_materials = [
            "APA", "MTDR", "PR", "CTRA", "OVV", "SM", "RRC", "AR", "SWN", "EQT",
            "BKR", "NOV", "FTI", "HP", "OII", "RIG", "DO", "VAL",
            "DINO", "PBF", "HFC", "DK", "CVI", "PAR", "PARR",
            "LIN", "ECL", "NEM", "NUE", "STLD", "CLF",
            "AA", "ATI", "CMC", "RS", "SCHN", "X", "ARNC", "CENX", "KALU"
        ]
        
        # Industrials & Defense (60)
        industrials = [
            "MMM", "ROK", "IR", "PH", "DOV", "GNRC", "CMI", "AGCO", "OSK", "TEX",
            "TDG", "TXT", "HWM",
            "XPO", "KNX", "WERN", "LSTR", "SAIA", "OLD",
            "KSU", "CP", "CNI", "TRN", "GBX", "RAIL",
            "MESA"
        ]
        
        # Semiconductors (additional)
        semiconductors = [
            "MRVL", "SWKS", "WOLF", "CRUS", "SLAB", "LSCC", "RMBS", "MPWR",
            "FFIV"
        ]
        
        # Combine all lists
        all_symbols = (
            etfs + sp500 + nasdaq_growth + high_volume + 
            biotech + financials + energy_materials + industrials + semiconductors
        )
        
        # Remove duplicates while preserving order
        seen = set()
        unique_symbols = []
        for sym in all_symbols:
            if sym not in seen:
                seen.add(sym)
                unique_symbols.append(sym)
        
        # Prioritize symbols that have collected IB data
        if symbols_with_data:
            prioritized = []
            remaining = []
            for sym in unique_symbols:
                if sym in symbols_with_data:
                    prioritized.append(sym)
                else:
                    remaining.append(sym)
            unique_symbols = prioritized + remaining
            logger.info(f"Prioritized {len(prioritized)} symbols with IB data")
        
        logger.info(f"Market-wide symbol universe: {len(unique_symbols)} total symbols (max: {max_symbols})")
        
        return unique_symbols[:max_symbols]

    # ========================================================================
    # Data Caching and Management
    # ========================================================================
    
    def _normalize_bar_size(self, bar_size: str) -> str:
        """
        Normalize bar_size format to match IB collected data format.
        
        IB format: "1 day", "5 mins", "15 mins", "1 min", "1 hour"
        This ensures compatibility between different parts of the system.
        """
        bar_size_lower = bar_size.lower().strip()
        
        # Map common variations to IB format
        mapping = {
            # Daily
            "1day": "1 day",
            "1d": "1 day",
            "daily": "1 day",
            "day": "1 day",
            # 5 minute
            "5min": "5 mins",
            "5m": "5 mins",
            "5mins": "5 mins",
            "5 min": "5 mins",
            # 15 minute
            "15min": "15 mins",
            "15m": "15 mins",
            "15mins": "15 mins",
            "15 min": "15 mins",
            # 1 minute
            "1min": "1 min",
            "1m": "1 min",
            # 1 hour
            "1hour": "1 hour",
            "1h": "1 hour",
            "60min": "1 hour",
            "60 min": "1 hour",
        }
        
        return mapping.get(bar_size_lower, bar_size)

    async def _get_cached_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> List[Dict]:
        """Get bars from hybrid data service (cache -> IB -> Alpaca)"""
        
        # Normalize timeframe to IB format
        normalized_tf = self._normalize_bar_size(timeframe)
        
        # Try IB collected data first (PRIMARY SOURCE)
        if self._db is not None:
            try:
                # Determine date format based on bar size
                is_daily = normalized_tf == "1 day"
                
                query = {
                    "symbol": symbol.upper(),
                    "bar_size": normalized_tf,
                    "date": {
                        "$gte": start_date if is_daily else f"{start_date}T00:00:00",
                        "$lte": end_date if is_daily else f"{end_date}T23:59:59"
                    }
                }
                
                ib_bars = list(self._db["ib_historical_data"].find(
                    query,
                    {"_id": 0}
                ).sort("date", 1))
                
                if ib_bars and len(ib_bars) >= 5:
                    logger.debug(f"IB data: {symbol} {normalized_tf} -> {len(ib_bars)} bars")
                    # Convert to standard format
                    return [{
                        "timestamp": bar.get("date"),
                        "open": bar.get("open"),
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "close": bar.get("close"),
                        "volume": bar.get("volume"),
                        "symbol": symbol,
                        "bar_size": normalized_tf
                    } for bar in ib_bars]
            except Exception as e:
                logger.warning(f"IB data fetch error for {symbol}: {e}")
        
        # Try hybrid data service second
        if self._hybrid_data_service is not None:
            try:
                result = await self._hybrid_data_service.get_bars(
                    symbol=symbol,
                    timeframe=normalized_tf,
                    start_date=start_date,
                    end_date=end_date
                )
                if result.success and result.bars:
                    logger.debug(f"Hybrid data: {symbol} {normalized_tf} -> {result.bar_count} bars from {result.source}")
                    return result.bars
            except Exception as e:
                logger.warning(f"Hybrid data service error for {symbol}: {e}")
        
        # Fallback to legacy cache
        if self._backtest_cache_col is not None:
            cached = list(self._backtest_cache_col.find(
                {
                    "symbol": symbol.upper(),
                    "timeframe": normalized_tf,
                    "date": {"$gte": start_date, "$lte": end_date}
                },
                {"_id": 0}
            ).sort("date", 1))
            
            if cached and len(cached) > 10:  # Have meaningful cached data
                return cached
        
        # Fetch from Alpaca directly as last resort (only daily supported)
        bars = []
        if normalized_tf == "1 day":
            try:
                if self._alpaca_service:
                    bars = await self._alpaca_service.get_bars(
                        symbol, "1Day", 
                        start=start_date, 
                        end=end_date,
                        limit=1000
                    )
                elif self._historical_data_service:
                    bars = await self._historical_data_service.get_bars(
                        symbol, "1Day", start_date, end_date
                    )
            except Exception as e:
                logger.warning(f"Error fetching bars for {symbol}: {e}")
                
            # Cache the data
            if bars and self._backtest_cache_col is not None:
                for bar in bars:
                    bar["symbol"] = symbol.upper()
                    bar["timeframe"] = normalized_tf
                    bar["date"] = bar.get("timestamp", "")[:10]
                    
                # Upsert to avoid duplicates
                for bar in bars:
                    self._backtest_cache_col.update_one(
                        {"symbol": bar["symbol"], "timeframe": bar["timeframe"], "date": bar["date"]},
                        {"$set": bar},
                        upsert=True
                    )
        
        return bars

    # ========================================================================
    # Filtering and Simulation
    # ========================================================================
    
    def _apply_filters(self, bars: List[Dict], filters: BacktestFilters) -> List[Dict]:
        """Apply date, regime, and time filters to bars"""
        filtered = []
        
        for bar in bars:
            timestamp = bar.get("timestamp", "")
            
            # Date filter
            if filters.start_date and timestamp[:10] < filters.start_date:
                continue
            if filters.end_date and timestamp[:10] > filters.end_date:
                continue
            
            # Day of week filter (0=Monday, 4=Friday)
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.weekday() not in filters.days_of_week:
                    continue
            except (ValueError, AttributeError):
                pass
            
            # Market regime filter (simplified - based on price vs moving average)
            if "all" not in filters.market_regimes:
                regime = bar.get("regime", "unknown")
                if regime not in filters.market_regimes:
                    # Calculate simple regime based on recent data
                    pass  # Would need moving average context
            
            filtered.append(bar)
        
        return filtered
    
    def _determine_trend(self, bars: List[Dict], lookback: int = 20) -> str:
        """
        Determine trend direction from bars using multiple indicators.
        
        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        if not bars or len(bars) < lookback:
            return 'neutral'
        
        recent_bars = bars[-lookback:]
        closes = [b.get("close", b.get("c", 0)) for b in recent_bars]
        
        if not closes or all(c == 0 for c in closes):
            return 'neutral'
        
        # Calculate 20-period SMA
        sma20 = sum(closes) / len(closes)
        current_price = closes[-1]
        
        # Price vs SMA
        price_vs_sma = "above" if current_price > sma20 else "below"
        
        # Higher highs / higher lows analysis
        highs = [b.get("high", b.get("h", 0)) for b in recent_bars]
        lows = [b.get("low", b.get("l", 0)) for b in recent_bars]
        
        recent_high = max(highs[-10:]) if len(highs) >= 10 else max(highs)
        older_high = max(highs[:10]) if len(highs) >= 10 else highs[0]
        recent_low = min(lows[-10:]) if len(lows) >= 10 else min(lows)
        older_low = min(lows[:10]) if len(lows) >= 10 else lows[0]
        
        higher_highs = recent_high > older_high
        higher_lows = recent_low > older_low
        lower_highs = recent_high < older_high
        lower_lows = recent_low < older_low
        
        # Combine signals
        bullish_signals = 0
        bearish_signals = 0
        
        if price_vs_sma == "above":
            bullish_signals += 1
        else:
            bearish_signals += 1
            
        if higher_highs and higher_lows:
            bullish_signals += 2
        elif lower_highs and lower_lows:
            bearish_signals += 2
        
        # Final determination
        if bullish_signals >= 2:
            return 'bullish'
        elif bearish_signals >= 2:
            return 'bearish'
        else:
            return 'neutral'

    async def _simulate_strategy(
        self,
        symbol: str,
        bars: List[Dict],
        strategy: StrategyConfig,
        starting_capital: float,
        htf_trend: str = None
    ) -> Tuple[List[BacktestTrade], List[Dict]]:
        """
        Simulate a strategy on historical bars.
        
        Args:
            symbol: Stock symbol
            bars: Historical price bars
            strategy: Strategy configuration
            starting_capital: Starting capital
            htf_trend: Higher timeframe trend ('bullish', 'bearish', 'neutral') for MTF analysis
        """
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []
        
        capital = starting_capital
        in_position = False
        current_trade: BacktestTrade = None
        
        for i, bar in enumerate(bars):
            current_price = bar.get("close", bar.get("c", 0))
            timestamp = bar.get("timestamp", "")
            high = bar.get("high", bar.get("h", current_price))
            low = bar.get("low", bar.get("l", current_price))
            
            # Track equity
            equity = capital
            if in_position and current_trade:
                if current_trade.direction == "short":
                    unrealized_pnl = (current_trade.entry_price - current_price) * current_trade.shares
                else:
                    unrealized_pnl = (current_price - current_trade.entry_price) * current_trade.shares
                equity = capital + unrealized_pnl
                
                # Track MFE/MAE
                if unrealized_pnl > current_trade.max_favorable_excursion:
                    current_trade.max_favorable_excursion = unrealized_pnl
                if unrealized_pnl < current_trade.max_adverse_excursion:
                    current_trade.max_adverse_excursion = unrealized_pnl
            
            equity_curve.append({
                "timestamp": timestamp,
                "equity": equity,
                "price": current_price
            })
            
            if in_position and current_trade:
                current_trade.bars_held += 1
                is_short_trade = current_trade.direction == "short"
                
                # Check exit conditions
                exit_price = None
                exit_reason = ""
                
                if is_short_trade:
                    # Short trade: stop hit when price goes UP, target hit when DOWN
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                else:
                    # Long trade: stop hit when price goes DOWN, target hit when UP
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                
                # Time-based exit
                if not exit_price and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = current_price
                    exit_reason = "time"
                
                # End of data
                if not exit_price and i == len(bars) - 1:
                    exit_price = current_price
                    exit_reason = "end_of_data"
                
                if exit_price:
                    # Close trade
                    current_trade.exit_price = exit_price
                    current_trade.exit_date = timestamp[:10]
                    current_trade.exit_time = timestamp[11:19] if len(timestamp) > 10 else ""
                    current_trade.exit_reason = exit_reason
                    
                    if is_short_trade:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (current_trade.entry_price / exit_price - 1) * 100 if exit_price > 0 else 0
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0
                    
                    risk = abs(current_trade.entry_price - current_trade.stop_price)
                    if risk > 0:
                        current_trade.r_multiple = current_trade.pnl / (risk * current_trade.shares)
                    
                    trades.append(current_trade)
                    capital += current_trade.pnl
                    in_position = False
                    current_trade = None
            
            else:
                # Check entry conditions
                # Multi-timeframe filter: only trade in direction of higher TF trend
                entry_allowed = True
                if htf_trend:
                    # For now, only allow long entries in bullish trends
                    # Short entries in bearish trends
                    # Skip entries in neutral or opposing trends
                    if htf_trend == 'bearish':
                        entry_allowed = False  # No longs in downtrends
                    elif htf_trend == 'neutral':
                        entry_allowed = True   # Allow but with caution
                
                if entry_allowed and self._check_entry_signal(bar, strategy, bars[:i+1]):
                    # Determine trade direction from setup type
                    is_short = strategy.setup_type.lower().startswith("short_")
                    direction = "short" if is_short else "long"
                    
                    # Calculate position size
                    position_value = capital * (strategy.position_size_pct / 100)
                    shares = int(position_value / current_price)
                    
                    if shares > 0:
                        if is_short:
                            stop_price = current_price * (1 + strategy.stop_pct / 100)
                            target_price = current_price * (1 - strategy.target_pct / 100)
                        else:
                            stop_price = current_price * (1 - strategy.stop_pct / 100)
                            target_price = current_price * (1 + strategy.target_pct / 100)
                        
                        current_trade = BacktestTrade(
                            id=f"t_{uuid.uuid4().hex[:8]}",
                            symbol=symbol,
                            strategy_name=strategy.name,
                            setup_type=strategy.setup_type,
                            direction=direction,
                            entry_date=timestamp[:10],
                            entry_time=timestamp[11:19] if len(timestamp) > 10 else "",
                            entry_price=current_price,
                            shares=shares,
                            stop_price=stop_price,
                            target_price=target_price,
                            bars_held=0
                        )
                        in_position = True
        
        return trades, equity_curve
    
    def _check_entry_signal(
        self,
        bar: Dict,
        strategy: StrategyConfig,
        recent_bars: List[Dict]
    ) -> bool:
        """Check if entry conditions are met for the strategy"""
        
        # Volume filter
        volume = bar.get("volume", bar.get("v", 0))
        if volume < 100000:  # Min volume
            return False
        
        # Price filter
        price = bar.get("close", bar.get("c", 0))
        if price < 5.0 or price > 500.0:
            return False
        
        # Strategy-specific entry logic
        setup_type = strategy.setup_type.lower()
        
        # Short setups: strip prefix and invert direction
        is_short = setup_type.startswith("short_")
        clean_type = setup_type.replace("short_", "") if is_short else setup_type
        
        if clean_type == "orb":
            return self._check_orb_entry(bar, recent_bars, short=is_short)
        elif clean_type in ("vwap", "vwap_bounce"):
            return self._check_vwap_entry(bar, recent_bars, short=is_short)
        elif clean_type in ("gap_and_go", "gap_fade"):
            return self._check_gap_entry(bar, recent_bars, short=is_short)
        elif clean_type in ("breakout", "breakdown"):
            return self._check_breakout_entry(bar, recent_bars, short=is_short)
        elif clean_type == "scalp":
            return self._check_scalp_entry(bar, recent_bars, short=is_short)
        elif clean_type == "range":
            return self._check_range_entry(bar, recent_bars, short=is_short)
        elif clean_type == "mean_reversion":
            return self._check_mean_reversion_entry(bar, recent_bars, short=is_short)
        elif clean_type == "reversal":
            return self._check_reversal_entry(bar, recent_bars, short=is_short)
        elif clean_type in ("trend_continuation", "trend"):
            # Alias: SHORT_TREND (stripped → "trend") shares logic with TREND_CONTINUATION.
            # Previously "trend" fell through to the momentum fallback, making SHORT_TREND
            # produce identical trades to SHORT_MOMENTUM.
            return self._check_trend_continuation_entry(bar, recent_bars, short=is_short)
        elif clean_type == "momentum":
            return self._check_momentum_entry(bar, recent_bars, short=is_short)
        else:
            # Unknown setup — log once (not every bar) and fall back.
            # Note: silent fallback to momentum was masking real bugs (e.g. SHORT_TREND
            # aliasing to SHORT_MOMENTUM). We now warn loudly.
            if not getattr(self, "_warned_unknown_setups", None):
                self._warned_unknown_setups = set()
            warn_key = clean_type
            if warn_key not in self._warned_unknown_setups:
                logger.warning(
                    f"[BACKTEST] Unknown setup type '{strategy.setup_type}' "
                    f"(clean='{clean_type}') — no dedicated entry check, falling back to momentum. "
                    f"This may produce misleading results. Add an explicit branch."
                )
                self._warned_unknown_setups.add(warn_key)
            return self._check_momentum_entry(bar, recent_bars, short=is_short)
    
    def _check_orb_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Opening Range Breakout entry"""
        if len(recent_bars) < 3:
            return False
        
        current_high = bar.get("high", bar.get("h", 0))
        current_low = bar.get("low", bar.get("l", 0))
        prev_high = max(b.get("high", b.get("h", 0)) for b in recent_bars[-3:-1])
        prev_low = min(b.get("low", b.get("l", 0)) for b in recent_bars[-3:-1])
        
        if short:
            return current_low < prev_low * 0.998  # 0.2% breakdown
        return current_high > prev_high * 1.002  # 0.2% breakout
    
    def _check_vwap_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """VWAP bounce entry — uses MA proxy when VWAP unavailable"""
        if len(recent_bars) < 10:
            return False
        
        close = bar.get("close", bar.get("c", 0))
        # Use actual VWAP if available, otherwise approximate with 10-bar avg
        vwap = bar.get("vwap", 0)
        if not vwap or vwap == 0:
            vwap = sum(b.get("close", b.get("c", 0)) for b in recent_bars[-10:]) / 10
        
        if vwap == 0:
            return False
            
        dist = (close - vwap) / vwap
        
        if short:
            # Price rejecting from above VWAP
            return -0.002 < dist < 0.008 and close < vwap
        # Price bouncing from below VWAP
        return -0.008 < dist < 0.002 and close > vwap
    
    def _check_gap_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Gap and Go / Gap Fade entry"""
        if len(recent_bars) < 2:
            return False
        
        current_open = bar.get("open", bar.get("o", 0))
        prev_close = recent_bars[-2].get("close", recent_bars[-2].get("c", 0))
        
        if prev_close == 0:
            return False
        
        gap_pct = (current_open - prev_close) / prev_close * 100
        
        if short:
            return gap_pct <= -1.5  # 1.5% gap down
        return gap_pct >= 1.5  # 1.5% gap up
    
    def _check_breakout_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Resistance breakout / Support breakdown entry"""
        if len(recent_bars) < 20:
            return False
        
        if short:
            current_low = bar.get("low", bar.get("l", 0))
            recent_low = min(b.get("low", b.get("l", 0)) for b in recent_bars[-20:-1])
            return current_low < recent_low
        
        current_high = bar.get("high", bar.get("h", 0))
        recent_high = max(b.get("high", b.get("h", 0)) for b in recent_bars[-20:-1])
        return current_high > recent_high
    
    def _check_scalp_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Scalp entry — narrow range breakout with volume surge"""
        if len(recent_bars) < 5:
            return False
        
        close = bar.get("close", bar.get("c", 0))
        volume = bar.get("volume", bar.get("v", 0))
        
        # Recent range narrowing (low ATR)
        ranges = [b.get("high", b.get("h", 0)) - b.get("low", b.get("l", 0)) for b in recent_bars[-5:-1]]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        current_range = bar.get("high", bar.get("h", 0)) - bar.get("low", bar.get("l", 0))
        
        # Volume surge
        recent_vols = [b.get("volume", b.get("v", 0)) for b in recent_bars[-5:-1]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        
        if avg_range == 0 or avg_vol == 0:
            return False
        
        # Breakout from narrow range with volume confirmation
        range_expanding = current_range > avg_range * 1.3
        volume_surge = volume > avg_vol * 1.2
        
        if not (range_expanding and volume_surge):
            return False
        
        prev_close = recent_bars[-2].get("close", recent_bars[-2].get("c", 0))
        if prev_close == 0:
            return False
            
        if short:
            return close < prev_close  # Downward break
        return close > prev_close  # Upward break
    
    def _check_range_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Range-bound play — buy near support, sell near resistance"""
        if len(recent_bars) < 20:
            return False
        
        close = bar.get("close", bar.get("c", 0))
        highs = [b.get("high", b.get("h", 0)) for b in recent_bars[-20:]]
        lows = [b.get("low", b.get("l", 0)) for b in recent_bars[-20:]]
        
        range_high = max(highs)
        range_low = min(lows)
        range_size = range_high - range_low
        
        if range_size == 0:
            return False
        
        position_in_range = (close - range_low) / range_size  # 0 = bottom, 1 = top
        
        if short:
            # Near top of range — short
            return position_in_range > 0.85
        # Near bottom of range — long
        return position_in_range < 0.15
    
    def _check_mean_reversion_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Mean reversion — price stretched away from moving average"""
        if len(recent_bars) < 20:
            return False
        
        close = bar.get("close", bar.get("c", 0))
        closes = [b.get("close", b.get("c", 0)) for b in recent_bars[-20:]]
        ma20 = sum(closes) / len(closes)
        
        if ma20 == 0:
            return False
        
        deviation = (close - ma20) / ma20
        
        if short:
            # Overbought: price well above MA — short for reversion
            return deviation > 0.04  # 4% above MA
        # Oversold: price well below MA — long for reversion
        return deviation < -0.04  # 4% below MA
    
    def _check_reversal_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Reversal — trend change with higher low (long) or lower high (short)"""
        if len(recent_bars) < 15:
            return False
        
        closes = [b.get("close", b.get("c", 0)) for b in recent_bars[-15:]]
        lows = [b.get("low", b.get("l", 0)) for b in recent_bars[-15:]]
        highs = [b.get("high", b.get("h", 0)) for b in recent_bars[-15:]]
        
        if short:
            # Bearish reversal: prior uptrend, then lower high
            uptrend = closes[-8] > closes[-15]  # Was trending up
            lower_high = highs[-1] < max(highs[-8:-1])  # Current high is lower
            close_below_ma = closes[-1] < sum(closes[-10:]) / 10
            return uptrend and lower_high and close_below_ma
        
        # Bullish reversal: prior downtrend, then higher low
        downtrend = closes[-8] < closes[-15]  # Was trending down
        higher_low = lows[-1] > min(lows[-8:-1])  # Current low is higher
        close_above_ma = closes[-1] > sum(closes[-10:]) / 10
        return downtrend and higher_low and close_above_ma
    
    def _check_trend_continuation_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Trend continuation — pullback to MA in established trend"""
        if len(recent_bars) < 20:
            return False
        
        closes = [b.get("close", b.get("c", 0)) for b in recent_bars[-20:]]
        close = closes[-1]
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes) / 20
        
        if ma20 == 0 or ma10 == 0:
            return False
        
        if short:
            # Downtrend: MA10 < MA20 and price pulled back up to MA10
            in_downtrend = ma10 < ma20
            pullback_to_ma = abs(close - ma10) / ma10 < 0.01  # Within 1% of MA10
            return in_downtrend and pullback_to_ma and close < ma10
        
        # Uptrend: MA10 > MA20 and price pulled back to MA10
        in_uptrend = ma10 > ma20
        pullback_to_ma = abs(close - ma10) / ma10 < 0.01  # Within 1% of MA10
        return in_uptrend and pullback_to_ma and close > ma10
    
    def _check_momentum_entry(self, bar: Dict, recent_bars: List[Dict], short: bool = False) -> bool:
        """Momentum entry — sustained directional move"""
        if len(recent_bars) < 5:
            return False
        
        # 3-day momentum
        closes = [b.get("close", b.get("c", 0)) for b in recent_bars[-4:]]
        if closes[0] == 0:
            return False
        
        momentum = (closes[-1] - closes[0]) / closes[0] * 100
        
        if short:
            return momentum <= -2.0  # 2% drop over 3 days
        return momentum >= 2.0  # 2% rise over 3 days

    # ========================================================================
    # Metrics Calculation
    # ========================================================================
    
    def _calculate_strategy_metrics(
        self,
        result: StrategyResult,
        trades: List[BacktestTrade],
        equity_curve: List[Dict],
        starting_capital: float
    ) -> StrategyResult:
        """Calculate metrics for a single strategy"""
        
        if not trades:
            return result
        
        result.total_trades = len(trades)
        result.winning_trades = len([t for t in trades if t.pnl > 0])
        result.losing_trades = len([t for t in trades if t.pnl < 0])
        result.win_rate = result.winning_trades / result.total_trades * 100 if result.total_trades > 0 else 0
        
        result.total_pnl = sum(t.pnl for t in trades)
        result.avg_pnl = result.total_pnl / result.total_trades if result.total_trades > 0 else 0
        
        winners = [t.pnl for t in trades if t.pnl > 0]
        losers = [t.pnl for t in trades if t.pnl < 0]
        
        result.avg_winner = sum(winners) / len(winners) if winners else 0
        result.avg_loser = sum(losers) / len(losers) if losers else 0
        
        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 0
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # R metrics
        r_values = [t.r_multiple for t in trades if t.r_multiple != 0]
        result.total_r = sum(r_values)
        result.avg_r = result.total_r / len(r_values) if r_values else 0
        result.expectancy = result.avg_r  # Expected R per trade
        
        # Time metrics
        result.avg_bars_held = sum(t.bars_held for t in trades) / len(trades) if trades else 0
        
        # Max drawdown from equity curve
        if equity_curve:
            peak = starting_capital
            max_dd = 0
            for point in equity_curve:
                equity = point.get("equity", starting_capital)
                peak = max(peak, equity)
                dd = (peak - equity) / peak * 100
                max_dd = max(max_dd, dd)
            result.max_drawdown_pct = max_dd
        
        # Sharpe ratio (simplified)
        returns = [t.pnl_percent for t in trades]
        if len(returns) > 1:
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            result.sharpe_ratio = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        
        result.trades = [t.to_dict() for t in trades]
        result.equity_curve = equity_curve
        
        return result
    
    def _calculate_combined_metrics(
        self,
        result: MultiStrategyResult,
        strategy_results: List[StrategyResult],
        all_trades: List[BacktestTrade]
    ) -> MultiStrategyResult:
        """Calculate combined metrics across all strategies"""
        
        if not all_trades:
            return result
        
        result.combined_total_trades = len(all_trades)
        result.combined_win_rate = len([t for t in all_trades if t.pnl > 0]) / len(all_trades) * 100
        result.combined_total_pnl = sum(t.pnl for t in all_trades)
        
        winners = sum(t.pnl for t in all_trades if t.pnl > 0)
        losers = abs(sum(t.pnl for t in all_trades if t.pnl < 0))
        result.combined_profit_factor = winners / losers if losers > 0 else 0
        
        # Combined Sharpe
        returns = [t.pnl_percent for t in all_trades]
        if len(returns) > 1:
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            result.combined_sharpe_ratio = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        
        # Max drawdown across strategies (simplified)
        max_dds = [sr.max_drawdown_pct for sr in strategy_results if sr.max_drawdown_pct > 0]
        result.combined_max_drawdown_pct = max(max_dds) if max_dds else 0
        
        return result
    
    def _calculate_correlation_matrix(self, strategy_results: List[StrategyResult]) -> Dict:
        """Calculate correlation between strategy returns"""
        matrix = {}
        
        if len(strategy_results) < 2:
            return matrix
        
        for i, sr1 in enumerate(strategy_results):
            for j, sr2 in enumerate(strategy_results):
                if i >= j:
                    continue
                
                # Get daily returns for each strategy
                returns1 = {t["entry_date"]: t["pnl"] for t in sr1.trades}
                returns2 = {t["entry_date"]: t["pnl"] for t in sr2.trades}
                
                # Find overlapping dates
                common_dates = set(returns1.keys()) & set(returns2.keys())
                
                if len(common_dates) < 5:
                    correlation = 0
                else:
                    r1 = [returns1[d] for d in common_dates]
                    r2 = [returns2[d] for d in common_dates]
                    
                    # Calculate correlation coefficient
                    try:
                        mean1, mean2 = statistics.mean(r1), statistics.mean(r2)
                        std1, std2 = statistics.stdev(r1), statistics.stdev(r2)
                        
                        if std1 > 0 and std2 > 0:
                            cov = sum((r1[k] - mean1) * (r2[k] - mean2) for k in range(len(r1))) / len(r1)
                            correlation = cov / (std1 * std2)
                        else:
                            correlation = 0
                    except (statistics.StatisticsError, ZeroDivisionError):
                        correlation = 0
                
                key = f"{sr1.strategy_name}_vs_{sr2.strategy_name}"
                matrix[key] = round(correlation, 3)
        
        return matrix

    # ========================================================================
    # Background Job Management
    # ========================================================================
    
    def _update_job_progress(self, job_id: str, progress: float, message: str):
        """Update progress for a background job"""
        if job_id in self._running_jobs:
            self._running_jobs[job_id].progress = progress
            self._running_jobs[job_id].progress_message = message
        
        if self._backtest_jobs_col is not None:
            self._backtest_jobs_col.update_one(
                {"id": job_id},
                {"$set": {"progress": progress, "progress_message": message}}
            )
    
    async def create_background_job(
        self,
        job_type: str,
        config: Dict
    ) -> BacktestJob:
        """Create a background job for long-running backtest"""
        job = BacktestJob(
            id=f"job_{uuid.uuid4().hex[:12]}",
            job_type=job_type,
            status="pending",
            config=config,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        self._running_jobs[job.id] = job
        
        if self._backtest_jobs_col is not None:
            self._backtest_jobs_col.insert_one(job.to_dict())
        
        return job
    
    async def get_job_status(self, job_id: str) -> Optional[BacktestJob]:
        """Get status of a background job"""
        if job_id in self._running_jobs:
            return self._running_jobs[job_id]
        
        if self._backtest_jobs_col is not None:
            doc = self._backtest_jobs_col.find_one({"id": job_id}, {"_id": 0})
            if doc:
                return BacktestJob(**doc)
        
        return None

    # ========================================================================
    # Results Retrieval
    # ========================================================================
    
    async def get_backtest_result(self, result_id: str) -> Optional[Dict]:
        """Get a specific backtest result"""
        if self._backtest_results_col is None:
            return None
        
        doc = self._backtest_results_col.find_one({"id": result_id}, {"_id": 0})
        return doc
    
    async def get_recent_results(self, limit: int = 20, result_type: str = None) -> List[Dict]:
        """Get recent backtest results"""
        if self._backtest_results_col is None:
            return []
        
        query = {}
        if result_type:
            # Filter by result type based on ID prefix
            if result_type == "multi":
                query["id"] = {"$regex": "^mbt_"}
            elif result_type == "walk_forward":
                query["id"] = {"$regex": "^wf_"}
            elif result_type == "monte_carlo":
                query["id"] = {"$regex": "^mc_"}
        
        cursor = self._backtest_results_col.find(
            query, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
        
        return list(cursor)


# ============================================================================
# Singleton and Initialization
# ============================================================================

_advanced_backtest_engine: Optional[AdvancedBacktestEngine] = None


def get_advanced_backtest_engine() -> AdvancedBacktestEngine:
    """Get the advanced backtest engine singleton"""
    global _advanced_backtest_engine
    if _advanced_backtest_engine is None:
        _advanced_backtest_engine = AdvancedBacktestEngine()
    return _advanced_backtest_engine


def init_advanced_backtest_engine(
    db=None,
    historical_data_service=None,
    alpaca_service=None,
    tqs_engine=None
) -> AdvancedBacktestEngine:
    """Initialize the advanced backtest engine"""
    engine = get_advanced_backtest_engine()
    if db is not None:
        engine.set_db(db)
    engine.set_services(historical_data_service, alpaca_service, tqs_engine)
    return engine
