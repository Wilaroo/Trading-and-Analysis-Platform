"""
Advanced Backtest Router
========================
API endpoints for the advanced backtesting system.

Features:
- Multi-strategy backtesting
- Walk-forward optimization  
- Monte Carlo simulation
- Custom date range selection
- Background job management
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["advanced-backtest"])

# Will be initialized from server
_advanced_engine = None
_simulation_engine = None


def _activate_backtest_mode(context: dict = None):
    """Auto-activate BACKTESTING focus mode when a backtest starts."""
    try:
        from services.focus_mode_manager import focus_mode_manager
        focus_mode_manager.set_mode(mode="backtesting", context=context or {})
        logger.info("[FOCUS] Auto-activated BACKTESTING mode")
    except Exception as e:
        logger.warning(f"Failed to auto-activate backtesting mode: {e}")


def _restore_live_mode():
    """Restore to LIVE mode after backtest completes."""
    try:
        from services.focus_mode_manager import focus_mode_manager
        focus_mode_manager.reset_to_live()
        logger.info("[FOCUS] Restored to LIVE mode after backtest")
    except Exception as e:
        logger.warning(f"Failed to restore live mode: {e}")


def init_advanced_backtest_router(engine, simulation_engine=None):
    """Initialize the router with the backtest engine and optional simulation engine"""
    global _advanced_engine, _simulation_engine
    _advanced_engine = engine
    _simulation_engine = simulation_engine


# ============================================================================
# Request/Response Models
# ============================================================================

class StrategyConfigModel(BaseModel):
    """Strategy configuration for backtest"""
    name: str = Field(..., description="Strategy name")
    setup_type: str = Field(..., description="Setup type: ORB, VWAP_BOUNCE, GAP_AND_GO, BREAKOUT, MOMENTUM")
    min_tqs_score: float = Field(60.0, description="Minimum TQS score for entry")
    stop_pct: float = Field(2.0, description="Stop loss percentage")
    target_pct: float = Field(4.0, description="Take profit percentage")
    use_trailing_stop: bool = Field(False, description="Use trailing stop")
    trailing_stop_pct: float = Field(1.5, description="Trailing stop percentage")
    max_bars_to_hold: int = Field(20, description="Maximum bars to hold position")
    position_size_pct: float = Field(10.0, description="Position size as % of capital")


class BacktestFiltersModel(BaseModel):
    """Filters for custom date range selection"""
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    market_regimes: List[str] = Field(["all"], description="Market regime filters: all, bull, bear, high_vol, low_vol")
    time_filters: List[str] = Field(["all_day"], description="Time of day filters")
    days_of_week: List[int] = Field([0,1,2,3,4], description="Days to include (0=Mon, 4=Fri)")
    exclude_earnings_days: bool = Field(False, description="Exclude earnings announcement days")


class MultiStrategyRequest(BaseModel):
    """Request for multi-strategy backtest"""
    symbols: List[str] = Field(..., description="List of stock symbols")
    strategies: List[StrategyConfigModel] = Field(..., description="List of strategies to test")
    filters: Optional[BacktestFiltersModel] = Field(None, description="Date and market filters")
    starting_capital: float = Field(100000.0, description="Starting capital per strategy")
    name: Optional[str] = Field(None, description="Name for this backtest")
    run_in_background: bool = Field(False, description="Run as background job")


class WalkForwardRequest(BaseModel):
    """Request for walk-forward optimization"""
    symbol: str = Field(..., description="Stock symbol")
    strategy: StrategyConfigModel = Field(..., description="Strategy to test")
    in_sample_days: int = Field(180, description="Training period in days")
    out_of_sample_days: int = Field(30, description="Testing period in days")
    step_days: int = Field(30, description="Days to step forward each period")
    total_days: int = Field(365, description="Total days of data to use")
    end_date: Optional[str] = Field(None, description="End date (defaults to today)")
    run_in_background: bool = Field(False, description="Run as background job")


class MonteCarloRequest(BaseModel):
    """Request for Monte Carlo simulation"""
    backtest_id: Optional[str] = Field(None, description="ID of existing backtest to analyze")
    num_simulations: int = Field(10000, description="Number of simulations to run")
    starting_capital: float = Field(100000.0, description="Starting capital")
    randomize_trade_order: bool = Field(True, description="Shuffle trade order")
    randomize_trade_size: bool = Field(False, description="Vary position sizes")
    size_variation_pct: float = Field(20.0, description="Position size variation (+/- %)")
    run_in_background: bool = Field(True, description="Run as background job (recommended)")


class QuickBacktestRequest(BaseModel):
    """Request for quick single-strategy backtest"""
    symbol: str = Field(..., description="Stock symbol")
    strategy: StrategyConfigModel = Field(..., description="Strategy configuration")
    start_date: Optional[str] = Field(None, description="Start date")
    end_date: Optional[str] = Field(None, description="End date")
    starting_capital: float = Field(100000.0, description="Starting capital")


class MarketWideBacktestRequest(BaseModel):
    """Request for market-wide backtest (scan entire US market with a strategy)"""
    strategy: StrategyConfigModel = Field(..., description="Strategy to test across the market")
    trade_style: str = Field("swing", description="Trade style: intraday, swing, investment")
    bar_size: str = Field("1 day", description="Bar size for simulation: '1 min', '5 mins', '15 mins', '1 hour', '1 day'")
    start_date: Optional[str] = Field(None, description="Start date (default: 30 days ago)")
    end_date: Optional[str] = Field(None, description="End date (default: today)")
    starting_capital: float = Field(100000.0, description="Starting capital for trade sizing")
    max_symbols: int = Field(1500, description="Max symbols to scan (default 1500 for comprehensive coverage)")
    symbols: Optional[List[str]] = Field(None, description="Specific symbols (None = scan market)")
    run_in_background: bool = Field(True, description="Run as background job")
    use_multi_timeframe: bool = Field(False, description="Enable multi-timeframe analysis (higher TF trend + lower TF entry)")


class AIComparisonRequest(BaseModel):
    """Request for AI vs Setup comparison backtest"""
    symbols: List[str] = Field(..., description="Stock symbols to backtest")
    strategy: StrategyConfigModel = Field(..., description="Strategy configuration")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD). Default: 1 year ago")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD). Default: today")
    starting_capital: float = Field(100000.0, description="Starting capital")
    ai_confidence_threshold: float = Field(0.0, ge=0.0, le=1.0, description="Minimum AI confidence to confirm entry (0.0 = any 'up' prediction)")
    ai_lookback_bars: int = Field(50, ge=20, le=200, description="Number of historical bars for AI prediction")
    run_in_background: bool = Field(True, description="Run as background job (recommended)")


class FullAISimulationRequest(BaseModel):
    """Request for full AI pipeline simulation (replays the complete SentCom bot)"""
    start_date: Optional[str] = Field(None, description="Start date ISO format (default: 6 months ago)")
    end_date: Optional[str] = Field(None, description="End date ISO format (default: yesterday)")
    universe: str = Field("sp500", description="Stock universe: all, sp500, nasdaq100, custom")
    custom_symbols: List[str] = Field(default=[], description="Custom symbol list if universe=custom")
    starting_capital: float = Field(100000.0, description="Starting capital")
    max_position_pct: float = Field(10.0, description="Max % of capital per position")
    max_open_positions: int = Field(5, description="Max concurrent open positions")
    use_ai_agents: bool = Field(True, description="Use full AI consultation pipeline (debate, risk, institutional)")
    bar_size: str = Field("1 day", description="Bar size: '1 min', '5 mins', '15 mins', '1 hour', '1 day'")
    min_adv: int = Field(100000, description="Minimum average daily volume")
    min_price: float = Field(5.0, description="Minimum stock price")
    max_price: float = Field(500.0, description="Maximum stock price")


# ============================================================================
# Multi-Strategy Endpoints
# ============================================================================

@router.post("/multi-strategy")
async def run_multi_strategy_backtest(
    request: MultiStrategyRequest,
    background_tasks: BackgroundTasks
):
    """
    Run multiple strategies on multiple symbols and compare results.
    
    Returns comparison metrics including:
    - Per-strategy performance (win rate, profit factor, Sharpe, etc.)
    - Combined portfolio performance
    - Strategy correlation matrix
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    # Convert Pydantic models to dataclasses
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    
    strategies = [
        StrategyConfig(
            name=s.name,
            setup_type=s.setup_type,
            min_tqs_score=s.min_tqs_score,
            stop_pct=s.stop_pct,
            target_pct=s.target_pct,
            use_trailing_stop=s.use_trailing_stop,
            trailing_stop_pct=s.trailing_stop_pct,
            max_bars_to_hold=s.max_bars_to_hold,
            position_size_pct=s.position_size_pct
        ) for s in request.strategies
    ]
    
    filters = None
    if request.filters:
        filters = BacktestFilters(
            start_date=request.filters.start_date,
            end_date=request.filters.end_date,
            market_regimes=request.filters.market_regimes,
            time_filters=request.filters.time_filters,
            days_of_week=request.filters.days_of_week,
            exclude_earnings_days=request.filters.exclude_earnings_days
        )
    
    if request.run_in_background:
        # Create background job
        job = await _advanced_engine.create_background_job(
            "multi_strategy",
            {
                "symbols": request.symbols,
                "strategies": [s.to_dict() for s in strategies],
                "filters": filters.to_dict() if filters else None,
                "starting_capital": request.starting_capital,
                "name": request.name
            }
        )
        
        # Run in background
        background_tasks.add_task(
            _run_multi_strategy_job,
            job.id,
            request.symbols,
            strategies,
            filters,
            request.starting_capital,
            request.name
        )
        
        return {
            "success": True,
            "job_id": job.id,
            "message": "Backtest started in background. Poll /api/backtest/job/{job_id} for status."
        }
    
    # Run synchronously
    try:
        result = await _advanced_engine.run_multi_strategy_backtest(
            symbols=request.symbols,
            strategies=strategies,
            filters=filters,
            starting_capital=request.starting_capital,
            name=request.name
        )
        
        return {
            "success": True,
            "result": result.to_dict()
        }
    except Exception as e:
        raise HTTPException(500, f"Backtest failed: {str(e)}")


async def _run_multi_strategy_job(job_id, symbols, strategies, filters, capital, name):
    """Background task for multi-strategy backtest"""
    _activate_backtest_mode({"job_id": job_id, "type": "multi_strategy"})
    try:
        result = await _advanced_engine.run_multi_strategy_backtest(
            symbols=symbols,
            strategies=strategies,
            filters=filters,
            starting_capital=capital,
            name=name,
            job_id=job_id
        )
        
        # Update job with result
        _advanced_engine._running_jobs[job_id].status = "completed"
        _advanced_engine._running_jobs[job_id].result_id = result.id
        _advanced_engine._running_jobs[job_id].result = result.to_dict()
        _advanced_engine._running_jobs[job_id].completed_at = datetime.utcnow().isoformat()
        
    except Exception as e:
        _advanced_engine._running_jobs[job_id].status = "failed"
        _advanced_engine._running_jobs[job_id].error = str(e)
    finally:
        _restore_live_mode()


# ============================================================================
# Walk-Forward Endpoints
# ============================================================================

@router.post("/walk-forward")
async def run_walk_forward_optimization(
    request: WalkForwardRequest,
    background_tasks: BackgroundTasks
):
    """
    Run walk-forward optimization to test strategy robustness.
    
    Splits data into rolling training/testing periods to detect overfitting.
    Returns efficiency ratio comparing in-sample vs out-of-sample performance.
    
    - Efficiency >= 90%: Excellent robustness
    - Efficiency 70-90%: Good robustness
    - Efficiency 50-70%: Moderate (possible overfitting)
    - Efficiency < 50%: Poor (likely overfit)
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, WalkForwardConfig
    )
    
    strategy = StrategyConfig(
        name=request.strategy.name,
        setup_type=request.strategy.setup_type,
        min_tqs_score=request.strategy.min_tqs_score,
        stop_pct=request.strategy.stop_pct,
        target_pct=request.strategy.target_pct,
        use_trailing_stop=request.strategy.use_trailing_stop,
        trailing_stop_pct=request.strategy.trailing_stop_pct,
        max_bars_to_hold=request.strategy.max_bars_to_hold,
        position_size_pct=request.strategy.position_size_pct
    )
    
    wf_config = WalkForwardConfig(
        in_sample_days=request.in_sample_days,
        out_of_sample_days=request.out_of_sample_days,
        step_days=request.step_days
    )
    
    if request.run_in_background:
        job = await _advanced_engine.create_background_job(
            "walk_forward",
            {
                "symbol": request.symbol,
                "strategy": strategy.to_dict(),
                "wf_config": wf_config.to_dict(),
                "total_days": request.total_days,
                "end_date": request.end_date
            }
        )
        
        background_tasks.add_task(
            _run_walk_forward_job,
            job.id,
            request.symbol,
            strategy,
            wf_config,
            request.total_days,
            request.end_date
        )
        
        return {
            "success": True,
            "job_id": job.id,
            "message": "Walk-forward optimization started. Poll /api/backtest/job/{job_id} for status."
        }
    
    try:
        result = await _advanced_engine.run_walk_forward(
            symbol=request.symbol,
            strategy=strategy,
            wf_config=wf_config,
            total_days=request.total_days,
            end_date=request.end_date
        )
        
        return {
            "success": True,
            "result": result.to_dict()
        }
    except Exception as e:
        raise HTTPException(500, f"Walk-forward failed: {str(e)}")


async def _run_walk_forward_job(job_id, symbol, strategy, wf_config, total_days, end_date):
    """Background task for walk-forward optimization"""
    _activate_backtest_mode({"job_id": job_id, "type": "walk_forward"})
    try:
        result = await _advanced_engine.run_walk_forward(
            symbol=symbol,
            strategy=strategy,
            wf_config=wf_config,
            total_days=total_days,
            end_date=end_date,
            job_id=job_id
        )
        
        _advanced_engine._running_jobs[job_id].status = "completed"
        _advanced_engine._running_jobs[job_id].result_id = result.id
        _advanced_engine._running_jobs[job_id].result = result.to_dict()
        _advanced_engine._running_jobs[job_id].completed_at = datetime.utcnow().isoformat()
        
    except Exception as e:
        _advanced_engine._running_jobs[job_id].status = "failed"
        _advanced_engine._running_jobs[job_id].error = str(e)
    finally:
        _restore_live_mode()


# ============================================================================
# Monte Carlo Endpoints
# ============================================================================

@router.post("/monte-carlo")
async def run_monte_carlo_simulation(
    request: MonteCarloRequest,
    background_tasks: BackgroundTasks
):
    """
    Run Monte Carlo simulation on backtest results.
    
    Shuffles trade order thousands of times to understand:
    - Range of possible P&L outcomes
    - Realistic drawdown expectations
    - Probability of profit/ruin
    - Win/loss streak distributions
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    if not request.backtest_id:
        raise HTTPException(400, "backtest_id is required")
    
    from services.slow_learning.advanced_backtest_engine import MonteCarloConfig
    
    mc_config = MonteCarloConfig(
        num_simulations=request.num_simulations,
        randomize_trade_order=request.randomize_trade_order,
        randomize_trade_size=request.randomize_trade_size,
        size_variation_pct=request.size_variation_pct
    )
    
    if request.run_in_background:
        job = await _advanced_engine.create_background_job(
            "monte_carlo",
            {
                "backtest_id": request.backtest_id,
                "mc_config": mc_config.to_dict(),
                "starting_capital": request.starting_capital
            }
        )
        
        background_tasks.add_task(
            _run_monte_carlo_job,
            job.id,
            request.backtest_id,
            mc_config,
            request.starting_capital
        )
        
        return {
            "success": True,
            "job_id": job.id,
            "message": "Monte Carlo simulation started. Poll /api/backtest/job/{job_id} for status."
        }
    
    try:
        result = await _advanced_engine.run_monte_carlo(
            backtest_id=request.backtest_id,
            mc_config=mc_config,
            starting_capital=request.starting_capital
        )
        
        return {
            "success": True,
            "result": result.to_dict()
        }
    except Exception as e:
        raise HTTPException(500, f"Monte Carlo simulation failed: {str(e)}")


async def _run_monte_carlo_job(job_id, backtest_id, mc_config, starting_capital):
    """Background task for Monte Carlo simulation"""
    _activate_backtest_mode({"job_id": job_id, "type": "monte_carlo"})
    try:
        result = await _advanced_engine.run_monte_carlo(
            backtest_id=backtest_id,
            mc_config=mc_config,
            starting_capital=starting_capital,
            job_id=job_id
        )
        
        _advanced_engine._running_jobs[job_id].status = "completed"
        _advanced_engine._running_jobs[job_id].result_id = result.id
        _advanced_engine._running_jobs[job_id].result = result.to_dict()
        _advanced_engine._running_jobs[job_id].completed_at = datetime.utcnow().isoformat()
        
    except Exception as e:
        _advanced_engine._running_jobs[job_id].status = "failed"
        _advanced_engine._running_jobs[job_id].error = str(e)
    finally:
        _restore_live_mode()


# ============================================================================
# Market-Wide Backtest (Full US Market Scanning)
# ============================================================================

@router.post("/market-wide")
async def run_market_wide_backtest(
    request: MarketWideBacktestRequest,
    background_tasks: BackgroundTasks
):
    """
    Run a strategy against the entire US market to find all historical trades.
    
    This answers: "Where would this strategy have triggered across all US stocks
    in the given time period, and what would the results have been?"
    
    Supports multi-timeframe analysis when use_multi_timeframe=True:
    - Higher timeframe (e.g., daily) determines trend direction
    - Lower timeframe (e.g., 5 min) used for precise entry signals
    
    Example use case:
    - "Show me every stock where Rubberband Long Scalp would have triggered in the last 30 days"
    - "What trades would Momentum Swing have taken across the whole market last month?"
    
    Returns:
    - All trades found with entry/exit prices and P&L
    - Summary statistics (win rate, profit factor, etc.)
    - Top performing trades
    - Most active symbols
    - Trades grouped by symbol
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    
    strategy = StrategyConfig(
        name=request.strategy.name,
        setup_type=request.strategy.setup_type,
        min_tqs_score=request.strategy.min_tqs_score,
        stop_pct=request.strategy.stop_pct,
        target_pct=request.strategy.target_pct,
        use_trailing_stop=request.strategy.use_trailing_stop,
        trailing_stop_pct=request.strategy.trailing_stop_pct,
        max_bars_to_hold=request.strategy.max_bars_to_hold,
        position_size_pct=request.strategy.position_size_pct
    )
    
    filters = BacktestFilters(
        start_date=request.start_date,
        end_date=request.end_date
    )
    
    if request.run_in_background:
        job = await _advanced_engine.create_background_job(
            "market_wide",
            {
                "strategy": strategy.to_dict() if hasattr(strategy, 'to_dict') else request.strategy.dict(),
                "trade_style": request.trade_style,
                "bar_size": request.bar_size,
                "max_symbols": request.max_symbols,
                "use_multi_timeframe": request.use_multi_timeframe
            }
        )
        
        background_tasks.add_task(
            _run_market_wide_job,
            job.id,
            strategy,
            filters,
            request.symbols,
            request.trade_style,
            request.bar_size,
            request.starting_capital,
            request.max_symbols,
            request.use_multi_timeframe
        )
        
        bar_size_display = request.bar_size
        mtf_note = " (Multi-Timeframe)" if request.use_multi_timeframe else ""
        return {
            "success": True,
            "job_id": job.id,
            "bar_size": bar_size_display,
            "use_multi_timeframe": request.use_multi_timeframe,
            "message": f"Market-wide backtest started for {request.strategy.name} on {bar_size_display}{mtf_note}. Scanning up to {request.max_symbols} symbols. Poll /api/backtest/job/{job.id} for status."
        }
    
    try:
        result = await _advanced_engine.run_market_wide_backtest(
            strategy=strategy,
            filters=filters,
            symbols=request.symbols,
            trade_style=request.trade_style,
            bar_size=request.bar_size,
            starting_capital=request.starting_capital,
            max_symbols=request.max_symbols,
            use_multi_timeframe=request.use_multi_timeframe
        )
        
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        raise HTTPException(500, f"Market-wide backtest failed: {str(e)}")


async def _run_market_wide_job(
    job_id: str,
    strategy,
    filters,
    symbols,
    trade_style: str,
    bar_size: str,
    starting_capital: float,
    max_symbols: int,
    use_multi_timeframe: bool = False
):
    """Background task for market-wide backtest"""
    _activate_backtest_mode({"job_id": job_id, "type": "market_wide"})
    try:
        result = await _advanced_engine.run_market_wide_backtest(
            strategy=strategy,
            filters=filters,
            symbols=symbols,
            trade_style=trade_style,
            bar_size=bar_size,
            starting_capital=starting_capital,
            max_symbols=max_symbols,
            use_multi_timeframe=use_multi_timeframe,
            job_id=job_id
        )
        
        _advanced_engine._running_jobs[job_id].status = "completed"
        _advanced_engine._running_jobs[job_id].result_id = result.get("id")
        _advanced_engine._running_jobs[job_id].result = result
        _advanced_engine._running_jobs[job_id].completed_at = datetime.utcnow().isoformat()
        
    except Exception as e:
        _advanced_engine._running_jobs[job_id].status = "failed"
        _advanced_engine._running_jobs[job_id].error = str(e)
    finally:
        _restore_live_mode()


# ============================================================================
# AI Comparison Backtest
# ============================================================================

@router.post("/ai-comparison")
async def run_ai_comparison_backtest(
    request: AIComparisonRequest,
    background_tasks: BackgroundTasks
):
    """
    Run a three-way AI comparison backtest:
    1. Setup-only: Traditional entry signals
    2. AI+Setup: Entry requires both setup AND AI confirmation
    3. AI-only: Only enter when AI predicts upward movement
    
    Returns detailed comparison metrics showing whether the AI model
    improves, hurts, or has no effect on trading results.
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    
    strategy = StrategyConfig(
        name=request.strategy.name,
        setup_type=request.strategy.setup_type,
        min_tqs_score=request.strategy.min_tqs_score,
        stop_pct=request.strategy.stop_pct,
        target_pct=request.strategy.target_pct,
        use_trailing_stop=request.strategy.use_trailing_stop,
        trailing_stop_pct=request.strategy.trailing_stop_pct,
        max_bars_to_hold=request.strategy.max_bars_to_hold,
        position_size_pct=request.strategy.position_size_pct
    )
    
    filters = BacktestFilters(
        start_date=request.start_date,
        end_date=request.end_date
    )
    
    if request.run_in_background:
        job = await _advanced_engine.create_background_job(
            "ai_comparison",
            {
                "symbols": request.symbols,
                "strategy": strategy.to_dict() if hasattr(strategy, 'to_dict') else request.strategy.dict(),
                "ai_confidence_threshold": request.ai_confidence_threshold,
                "ai_lookback_bars": request.ai_lookback_bars
            }
        )
        
        background_tasks.add_task(
            _run_ai_comparison_job,
            job.id,
            request.symbols,
            strategy,
            filters,
            request.starting_capital,
            request.ai_confidence_threshold,
            request.ai_lookback_bars
        )
        
        return {
            "success": True,
            "job_id": job.id,
            "message": "AI comparison backtest started in background",
            "status": "running"
        }
    
    # Run synchronously
    result = await _advanced_engine.run_ai_comparison_backtest(
        symbols=request.symbols,
        strategy=strategy,
        filters=filters,
        starting_capital=request.starting_capital,
        ai_confidence_threshold=request.ai_confidence_threshold,
        ai_lookback_bars=request.ai_lookback_bars
    )
    
    return {"success": True, "result": result.to_dict()}


async def _run_ai_comparison_job(
    job_id: str,
    symbols: list,
    strategy,
    filters,
    starting_capital: float,
    ai_confidence_threshold: float,
    ai_lookback_bars: int
):
    """Background task for AI comparison backtest"""
    _activate_backtest_mode({"job_id": job_id, "type": "ai_comparison"})
    try:
        _advanced_engine._running_jobs[job_id].status = "running"
        _advanced_engine._running_jobs[job_id].started_at = datetime.utcnow().isoformat()
        
        result = await _advanced_engine.run_ai_comparison_backtest(
            symbols=symbols,
            strategy=strategy,
            filters=filters,
            starting_capital=starting_capital,
            ai_confidence_threshold=ai_confidence_threshold,
            ai_lookback_bars=ai_lookback_bars,
            job_id=job_id
        )
        
        _advanced_engine._running_jobs[job_id].status = "completed"
        _advanced_engine._running_jobs[job_id].result_id = result.id
        _advanced_engine._running_jobs[job_id].result = result.to_dict()
        _advanced_engine._running_jobs[job_id].completed_at = datetime.utcnow().isoformat()
        
    except Exception as e:
        logger.error(f"AI comparison backtest failed: {e}")
        _advanced_engine._running_jobs[job_id].status = "failed"
        _advanced_engine._running_jobs[job_id].error = str(e)
    finally:
        _restore_live_mode()


@router.get("/ai-comparison/status")
def get_ai_model_status():
    """Check if the AI model is available for comparison backtesting"""
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    model = _advanced_engine._timeseries_model
    has_model = model is not None and getattr(model, '_model', None) is not None
    
    return {
        "ai_available": has_model,
        "model_version": getattr(model, '_version', 'none') if model else 'none',
        "model_accuracy": getattr(model, '_metrics', None).accuracy if model and getattr(model, '_metrics', None) else 0,
        "feature_count": len(getattr(model, '_feature_names', [])) if model else 0
    }


# ============================================================================
# Quick Single Backtest
# ============================================================================

@router.post("/quick")
async def run_quick_backtest(request: QuickBacktestRequest):
    """
    Run a quick single-strategy backtest on one symbol.
    For fast iteration and testing.
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    
    strategy = StrategyConfig(
        name=request.strategy.name,
        setup_type=request.strategy.setup_type,
        min_tqs_score=request.strategy.min_tqs_score,
        stop_pct=request.strategy.stop_pct,
        target_pct=request.strategy.target_pct,
        use_trailing_stop=request.strategy.use_trailing_stop,
        trailing_stop_pct=request.strategy.trailing_stop_pct,
        max_bars_to_hold=request.strategy.max_bars_to_hold,
        position_size_pct=request.strategy.position_size_pct
    )
    
    filters = BacktestFilters(
        start_date=request.start_date,
        end_date=request.end_date
    )
    
    try:
        result = await _advanced_engine.run_multi_strategy_backtest(
            symbols=[request.symbol],
            strategies=[strategy],
            filters=filters,
            starting_capital=request.starting_capital,
            name=f"Quick: {strategy.name} on {request.symbol}"
        )
        
        # Return simplified result for quick backtest
        if result.strategy_results:
            strategy_result = result.strategy_results[0]
            return {
                "success": True,
                "result": {
                    "id": result.id,
                    "symbol": request.symbol,
                    "strategy": strategy.name,
                    "start_date": result.start_date,
                    "end_date": result.end_date,
                    "total_trades": strategy_result.get("total_trades", 0),
                    "win_rate": strategy_result.get("win_rate", 0),
                    "total_pnl": strategy_result.get("total_pnl", 0),
                    "profit_factor": strategy_result.get("profit_factor", 0),
                    "sharpe_ratio": strategy_result.get("sharpe_ratio", 0),
                    "max_drawdown_pct": strategy_result.get("max_drawdown_pct", 0),
                    "avg_r": strategy_result.get("avg_r", 0),
                    "trades": strategy_result.get("trades", [])[:20]  # First 20 trades
                }
            }
        
        return {"success": True, "result": result.to_dict()}
        
    except Exception as e:
        raise HTTPException(500, f"Quick backtest failed: {str(e)}")


# ============================================================================
# Job Management
# ============================================================================

@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """
    Get status of a background backtest job.
    
    Returns:
    - status: pending, running, completed, failed
    - progress: 0-100
    - result: Full result when completed
    """
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    job = await _advanced_engine.get_job_status(job_id)
    
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    
    return {
        "success": True,
        "job": job.to_dict()
    }


@router.get("/jobs")
def list_recent_jobs(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status")
):
    """List recent backtest jobs"""
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    jobs = list(_advanced_engine._running_jobs.values())
    
    if status:
        jobs = [j for j in jobs if j.status == status]
    
    jobs.sort(key=lambda x: x.created_at or "", reverse=True)
    
    return {
        "success": True,
        "jobs": [j.to_dict() for j in jobs[:limit]]
    }


@router.post("/cleanup-stale")
def cleanup_stale_data():
    """Remove cancelled jobs, empty backtest results (0 trades), and empty validations"""
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    result = _advanced_engine.clear_stale_results()
    total = sum(result.values())
    return {
        "success": True,
        **result,
        "message": f"Cleaned up {total} stale records ({result['removed_results']} empty results, {result['removed_jobs']} cancelled jobs, {result['removed_validations']} empty validations, {result['removed_batch_validations']} empty batch validations)"
    }



# ============================================================================
# Results
# ============================================================================

@router.get("/results")
async def list_backtest_results(
    limit: int = Query(20, ge=1, le=100),
    result_type: Optional[str] = Query(None, description="Filter: multi, walk_forward, monte_carlo")
):
    """List recent backtest results"""
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    results = await _advanced_engine.get_recent_results(limit, result_type)
    
    return {
        "success": True,
        "results": results
    }


@router.get("/results/{result_id}")
async def get_backtest_result(result_id: str):
    """Get a specific backtest result by ID"""
    if not _advanced_engine:
        raise HTTPException(503, "Advanced backtest engine not initialized")
    
    result = await _advanced_engine.get_backtest_result(result_id)
    
    if not result:
        raise HTTPException(404, f"Result {result_id} not found")
    
    return {
        "success": True,
        "result": result
    }


# ============================================================================
# Strategy Templates
# ============================================================================

@router.get("/strategy-templates")
def get_strategy_templates():
    """
    Get pre-configured strategy templates for common setups.
    Use these as starting points for your backtests.
    """
    templates = [
        {
            "name": "ORB Conservative",
            "setup_type": "ORB",
            "description": "Opening Range Breakout with tight stops",
            "config": {
                "min_tqs_score": 65,
                "stop_pct": 1.5,
                "target_pct": 3.0,
                "use_trailing_stop": False,
                "max_bars_to_hold": 10,
                "position_size_pct": 8
            }
        },
        {
            "name": "ORB Aggressive",
            "setup_type": "ORB",
            "description": "Opening Range Breakout with wider targets",
            "config": {
                "min_tqs_score": 60,
                "stop_pct": 2.0,
                "target_pct": 5.0,
                "use_trailing_stop": True,
                "trailing_stop_pct": 1.5,
                "max_bars_to_hold": 20,
                "position_size_pct": 10
            }
        },
        {
            "name": "VWAP Bounce",
            "setup_type": "VWAP_BOUNCE",
            "description": "Mean reversion plays off VWAP",
            "config": {
                "min_tqs_score": 60,
                "stop_pct": 1.0,
                "target_pct": 2.0,
                "use_trailing_stop": False,
                "max_bars_to_hold": 5,
                "position_size_pct": 10
            }
        },
        {
            "name": "Gap and Go",
            "setup_type": "GAP_AND_GO",
            "description": "Momentum play on gapping stocks",
            "config": {
                "min_tqs_score": 70,
                "stop_pct": 2.5,
                "target_pct": 6.0,
                "use_trailing_stop": True,
                "trailing_stop_pct": 2.0,
                "max_bars_to_hold": 15,
                "position_size_pct": 8
            }
        },
        {
            "name": "Breakout Swing",
            "setup_type": "BREAKOUT",
            "description": "Multi-day breakout for swing trading",
            "config": {
                "min_tqs_score": 65,
                "stop_pct": 3.0,
                "target_pct": 8.0,
                "use_trailing_stop": True,
                "trailing_stop_pct": 2.5,
                "max_bars_to_hold": 40,
                "position_size_pct": 6
            }
        },
        {
            "name": "Momentum Scalp",
            "setup_type": "MOMENTUM",
            "description": "Quick momentum plays with tight risk",
            "config": {
                "min_tqs_score": 55,
                "stop_pct": 1.0,
                "target_pct": 1.5,
                "use_trailing_stop": False,
                "max_bars_to_hold": 3,
                "position_size_pct": 12
            }
        }
    ]
    
    return {
        "success": True,
        "templates": templates
    }


@router.get("/strategies")
def get_all_strategies():
    """
    Get all trading strategies from the database.
    These are the full 77+ strategies available for backtesting.
    """
    try:
        from data.strategies_data import ALL_STRATEGIES_DATA
        
        # Format strategies for backtest use
        strategies = []
        for strategy in ALL_STRATEGIES_DATA:
            # Map strategy data to backtest config
            setup_type = _map_strategy_to_setup_type(strategy.get("name", ""))
            
            strategies.append({
                "id": strategy.get("id", ""),
                "name": strategy.get("name", ""),
                "category": strategy.get("category", "intraday"),
                "setup_type": setup_type,
                "description": ", ".join(strategy.get("criteria", [])[:2]),
                "timeframe": strategy.get("timeframe", "5min"),
                "indicators": strategy.get("indicators", []),
                "config": {
                    "min_tqs_score": 60,
                    "stop_pct": 2.0,
                    "target_pct": 4.0,
                    "use_trailing_stop": False,
                    "max_bars_to_hold": 20 if strategy.get("category") == "intraday" else 60,
                    "position_size_pct": 10
                }
            })
        
        # Group by category
        grouped = {
            "intraday": [s for s in strategies if s["category"] == "intraday"],
            "swing": [s for s in strategies if s["category"] == "swing"],
            "investment": [s for s in strategies if s["category"] == "investment"]
        }
        
        return {
            "success": True,
            "total": len(strategies),
            "strategies": strategies,
            "grouped": grouped
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "strategies": []
        }


def _map_strategy_to_setup_type(name: str) -> str:
    """Map strategy name to a backtest setup type"""
    name_lower = name.lower()
    
    if "orb" in name_lower or "opening range" in name_lower:
        return "ORB"
    elif "vwap" in name_lower:
        if "reversion" in name_lower or "fade" in name_lower:
            return "VWAP_FADE"
        return "VWAP_BOUNCE"
    elif "gap" in name_lower:
        return "GAP_AND_GO"
    elif "breakout" in name_lower:
        return "BREAKOUT"
    elif "pullback" in name_lower or "dip" in name_lower:
        return "PULLBACK"
    elif "reversal" in name_lower:
        return "REVERSAL"
    elif "scalp" in name_lower:
        return "SCALP"
    elif "flag" in name_lower:
        return "FLAG"
    elif "momentum" in name_lower:
        return "MOMENTUM"
    elif "mean reversion" in name_lower:
        return "MEAN_REVERSION"
    elif "range" in name_lower:
        return "RANGE"
    elif "trend" in name_lower:
        return "TREND_CONTINUATION"
    elif "swing" in name_lower:
        return "SWING"
    elif "pivot" in name_lower:
        return "PIVOT"
    elif "hod" in name_lower or "high of day" in name_lower:
        return "HOD_BREAK"
    else:
        return "MOMENTUM"  # Default


# ============================================================================
# Full AI Simulation (unified from historical_simulation_engine)
# ============================================================================

@router.post("/full-ai-simulation")
async def run_full_ai_simulation(
    request: FullAISimulationRequest,
    background_tasks: BackgroundTasks
):
    """
    Run a full AI pipeline simulation that replays the complete SentCom bot
    on historical data. This uses all AI agents (Debate, Risk, Institutional,
    Time-Series) to make trade decisions on each bar.
    
    Unlike strategy backtests which test entry/exit rules, this simulates
    the actual live trading bot behavior including AI consultation.
    
    Always runs in background due to compute intensity.
    """
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized. Make sure the historical simulation engine is loaded.")
    
    from services.simulation_engine import SimulationConfig
    
    config = SimulationConfig(
        start_date=request.start_date,
        end_date=request.end_date,
        universe=request.universe,
        custom_symbols=request.custom_symbols,
        starting_capital=request.starting_capital,
        max_position_pct=request.max_position_pct,
        max_open_positions=request.max_open_positions,
        use_ai_agents=request.use_ai_agents,
        bar_size=request.bar_size,
        min_adv=request.min_adv,
        min_price=request.min_price,
        max_price=request.max_price,
    )
    
    job_id = await _simulation_engine.start_simulation(config)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": "Full AI simulation started in background",
        "status": "running",
        "config": {
            "universe": config.universe,
            "start_date": config.start_date,
            "end_date": config.end_date,
            "starting_capital": config.starting_capital,
            "use_ai_agents": config.use_ai_agents,
            "bar_size": config.bar_size
        }
    }


@router.get("/full-ai-simulation/status/{job_id}")
async def get_simulation_status(job_id: str):
    """Get status of a running full AI simulation"""
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized")
    
    status = await _simulation_engine.get_job_status(job_id)
    if not status:
        raise HTTPException(404, f"Simulation job {job_id} not found")
    
    return {
        "success": True,
        "job": status
    }


@router.get("/full-ai-simulation/trades/{job_id}")
async def get_simulation_trades(job_id: str, limit: int = Query(50, ge=1, le=500)):
    """Get trades from a completed simulation"""
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized")
    
    trades = await _simulation_engine.get_job_trades(job_id, limit)
    return {
        "success": True,
        "job_id": job_id,
        "trades": trades,
        "count": len(trades)
    }


@router.get("/full-ai-simulation/decisions/{job_id}")
async def get_simulation_decisions(job_id: str, limit: int = Query(50, ge=1, le=500)):
    """Get AI decisions from a simulation (how each trade was evaluated)"""
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized")
    
    decisions = await _simulation_engine.get_job_decisions(job_id, limit)
    return {
        "success": True,
        "job_id": job_id,
        "decisions": decisions,
        "count": len(decisions)
    }


@router.get("/full-ai-simulation/summary/{job_id}")
async def get_simulation_summary(job_id: str):
    """Get comprehensive summary of a completed simulation"""
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized")
    
    job = await _simulation_engine.get_job_status(job_id)
    if not job:
        raise HTTPException(404, f"Simulation job {job_id} not found")
    
    trades = await _simulation_engine.get_job_trades(job_id, limit=500)
    decisions = await _simulation_engine.get_job_decisions(job_id, limit=500)
    
    # Compute summary from trades
    total_trades = len(trades)
    winners = [t for t in trades if (t.get("realized_pnl") or 0) > 0]
    losers = [t for t in trades if (t.get("realized_pnl") or 0) < 0]
    win_rate = len(winners) / total_trades * 100 if total_trades else 0
    total_pnl = sum(t.get("realized_pnl", 0) for t in trades)
    avg_win = sum(t.get("realized_pnl", 0) for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t.get("realized_pnl", 0) for t in losers) / len(losers) if losers else 0
    gross_profit = sum(t.get("realized_pnl", 0) for t in winners)
    gross_loss = abs(sum(t.get("realized_pnl", 0) for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
    
    # Symbols breakdown
    symbols = {}
    for t in trades:
        sym = t.get("symbol", "?")
        if sym not in symbols:
            symbols[sym] = {"trades": 0, "pnl": 0, "wins": 0}
        symbols[sym]["trades"] += 1
        symbols[sym]["pnl"] += t.get("realized_pnl", 0)
        if (t.get("realized_pnl") or 0) > 0:
            symbols[sym]["wins"] += 1
    
    summary = {
        "job": job,
        "total_trades": total_trades,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor if profit_factor != float("inf") else 999,
        "total_decisions": len(decisions),
        "symbols_breakdown": symbols,
    }
    
    return {
        "success": True,
        "job_id": job_id,
        "summary": summary
    }


@router.get("/full-ai-simulation/jobs")
async def list_simulation_jobs(limit: int = Query(20, ge=1, le=100)):
    """List all simulation jobs (running and completed)"""
    if not _simulation_engine:
        raise HTTPException(503, "Simulation engine not initialized")
    
    jobs = await _simulation_engine.get_all_jobs(limit)
    return {
        "success": True,
        "jobs": jobs
    }
