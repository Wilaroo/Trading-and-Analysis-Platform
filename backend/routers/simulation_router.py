"""
Historical Simulation Router
============================

API endpoints for running and managing historical trading simulations.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["Historical Simulation"])

# Reference to the simulation engine (set during initialization)
_simulation_engine = None


def init_simulation_router(simulation_engine):
    """Initialize router with simulation engine reference"""
    global _simulation_engine
    _simulation_engine = simulation_engine
    logger.info("Simulation router initialized")


class SimulationConfigRequest(BaseModel):
    """Request body for starting a simulation"""
    # Time period (default: last 1 year)
    start_date: Optional[str] = Field(
        default=None, 
        description="Start date ISO format (default: 1 year ago)"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date ISO format (default: yesterday)"
    )
    
    # Stock filters
    min_adv: int = Field(default=100_000, description="Minimum average daily volume")
    min_price: float = Field(default=5.0, description="Minimum stock price")
    max_price: float = Field(default=500.0, description="Maximum stock price")
    min_rvol: float = Field(default=0.8, description="Minimum relative volume")
    
    # Universe
    universe: str = Field(default="all", description="Stock universe: all, sp500, nasdaq100, custom")
    custom_symbols: List[str] = Field(default=[], description="Custom symbol list if universe=custom")
    
    # Simulation settings
    starting_capital: float = Field(default=100_000.0, description="Starting capital")
    max_position_pct: float = Field(default=10.0, description="Max % per position")
    max_open_positions: int = Field(default=5, description="Max concurrent positions")
    use_ai_agents: bool = Field(default=True, description="Use full AI consultation pipeline")
    
    # Data source
    data_source: str = Field(default="alpaca", description="Data source: alpaca, ib, mongodb")
    
    # Multi-timeframe support
    bar_size: str = Field(
        default="1 day", 
        description="Bar size for simulation: 1 min, 5 mins, 15 mins, 1 hour, 1 day"
    )


@router.post("/start")
async def start_simulation(config: SimulationConfigRequest):
    """
    Start a new historical simulation job.
    
    This runs the complete SentCom trading bot simulation on historical data:
    - Fetches historical bars for all qualifying stocks
    - Applies first-gate filters (ADV, price, RVOL)
    - Detects trading signals
    - Runs AI consultation pipeline (if enabled)
    - Simulates trade execution and management
    - Tracks all decisions and outcomes
    
    The simulation runs in the background and can take hours for large universes.
    """
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        # Set default dates if not provided
        end_date = config.end_date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = config.start_date or (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        
        # Create simulation config
        from services.historical_simulation_engine import SimulationConfig
        
        sim_config = SimulationConfig(
            start_date=start_date,
            end_date=end_date,
            min_adv=config.min_adv,
            min_price=config.min_price,
            max_price=config.max_price,
            min_rvol=config.min_rvol,
            universe=config.universe,
            custom_symbols=config.custom_symbols,
            starting_capital=config.starting_capital,
            max_position_pct=config.max_position_pct,
            max_open_positions=config.max_open_positions,
            use_ai_agents=config.use_ai_agents,
            data_source=config.data_source,
            bar_size=config.bar_size
        )
        
        # Start simulation
        job_id = await _simulation_engine.start_simulation(sim_config)
        
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Simulation started for {start_date} to {end_date}",
            "config": sim_config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Error starting simulation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{job_id}")
async def get_simulation_status(job_id: str):
    """Get status of a simulation job"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        status = await _simulation_engine.get_job_status(job_id)
        
        if not status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        return {
            "success": True,
            "job": status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_simulation_jobs(limit: int = 20):
    """List all simulation jobs"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        jobs = await _simulation_engine.get_all_jobs(limit)
        
        return {
            "success": True,
            "jobs": jobs,
            "count": len(jobs)
        }
        
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades/{job_id}")
async def get_simulation_trades(job_id: str, limit: int = 100):
    """Get trades from a simulation job"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        trades = await _simulation_engine.get_job_trades(job_id, limit)
        
        return {
            "success": True,
            "trades": trades,
            "count": len(trades)
        }
        
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions/{job_id}")
async def get_simulation_decisions(job_id: str, limit: int = 100):
    """Get AI decisions from a simulation job (for learning analysis)"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        decisions = await _simulation_engine.get_job_decisions(job_id, limit)
        
        return {
            "success": True,
            "decisions": decisions,
            "count": len(decisions)
        }
        
    except Exception as e:
        logger.error(f"Error getting decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel/{job_id}")
async def cancel_simulation(job_id: str):
    """Cancel a running simulation job"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        cancelled = await _simulation_engine.cancel_job(job_id)
        
        if cancelled:
            return {
                "success": True,
                "message": f"Job {job_id} cancelled"
            }
        else:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found or not running")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{job_id}")
async def get_simulation_summary(job_id: str):
    """Get detailed summary of a completed simulation"""
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        status = await _simulation_engine.get_job_status(job_id)
        
        if not status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        trades = await _simulation_engine.get_job_trades(job_id, 1000)
        decisions = await _simulation_engine.get_job_decisions(job_id, 1000)
        
        # Analyze trades by setup type
        trades_by_setup = {}
        for trade in trades:
            setup = trade.get("setup_type", "unknown")
            if setup not in trades_by_setup:
                trades_by_setup[setup] = {
                    "count": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0
                }
            trades_by_setup[setup]["count"] += 1
            pnl = trade.get("realized_pnl", 0) or 0
            if pnl > 0:
                trades_by_setup[setup]["wins"] += 1
            elif pnl < 0:
                trades_by_setup[setup]["losses"] += 1
            trades_by_setup[setup]["total_pnl"] += pnl
        
        # Calculate win rate per setup
        for setup in trades_by_setup:
            total = trades_by_setup[setup]["count"]
            wins = trades_by_setup[setup]["wins"]
            trades_by_setup[setup]["win_rate"] = (wins / total * 100) if total > 0 else 0
        
        # Analyze AI decisions
        ai_stats = {
            "total_consultations": len(decisions),
            "proceeded": sum(1 for d in decisions if d.get("ai_decision", {}).get("recommendation") == "proceed"),
            "passed": sum(1 for d in decisions if d.get("ai_decision", {}).get("recommendation") == "pass"),
            "reduced_size": sum(1 for d in decisions if d.get("ai_decision", {}).get("recommendation") == "reduce_size")
        }
        
        return {
            "success": True,
            "job": status,
            "trades_by_setup": trades_by_setup,
            "ai_decision_stats": ai_stats,
            "total_trades": len(trades),
            "total_decisions": len(decisions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick-test")
async def quick_test_simulation(bar_size: str = "1 day"):
    """
    Run a SMART test simulation using the most liquid, well-traded symbols.
    Uses last 30 days and up to 30 "smart" symbols selected from:
    1. Symbols with collected IB data (highest data quality)
    2. Major liquid ETFs (SPY, QQQ, IWM)
    3. High-volume large-cap stocks across sectors
    
    Supports multiple bar sizes:
    - "1 day" (default): Daily bars for swing trading analysis
    - "5 mins": 5-minute bars for intraday strategies
    - "1 min": 1-minute bars for scalping strategies
    
    This provides meaningful, statistically-relevant results for testing strategies.
    """
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        from services.historical_simulation_engine import SimulationConfig
        
        db = _simulation_engine._db
        
        # Normalize bar_size to IB format
        bar_size_map = {
            "1day": "1 day", "1d": "1 day", "daily": "1 day",
            "5min": "5 mins", "5m": "5 mins", "5mins": "5 mins",
            "1min": "1 min", "1m": "1 min",
            "15min": "15 mins", "15m": "15 mins", "15mins": "15 mins",
        }
        normalized_bar_size = bar_size_map.get(bar_size.lower().replace(" ", ""), bar_size)
        
        # SMART symbol selection - prioritize stocks with good data quality
        smart_symbols = []
        
        # Tier 1: Most liquid ETFs (always include - highest liquidity, best for testing)
        core_etfs = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK"]
        
        # Tier 2: Mega-cap liquid stocks (diverse sectors)
        mega_caps = [
            # Tech leaders
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            # Finance
            "JPM", "BAC", "GS", "V", "MA",
            # Healthcare
            "UNH", "JNJ", "PFE",
            # Consumer/Industrial
            "WMT", "HD", "CAT", "BA",
            # Energy
            "XOM", "CVX",
            # High-beta momentum names
            "AMD", "CRM", "COIN", "MARA"
        ]
        
        if db is not None:
            # Check which symbols we have quality IB data for
            available_symbols = set(db["ib_historical_data"].distinct("symbol"))
            
            # Prioritize symbols with collected data
            for sym in core_etfs + mega_caps:
                if sym in available_symbols:
                    smart_symbols.append(sym)
            
            # If we don't have enough from our preferred list, get top-volume from DB
            if len(smart_symbols) < 15:
                top_volume_symbols = list(db["ib_historical_data"].aggregate([
                    {"$match": {"bar_size": "1 day"}},
                    {"$group": {
                        "_id": "$symbol",
                        "avg_vol": {"$avg": "$volume"},
                        "data_points": {"$sum": 1}
                    }},
                    {"$match": {"data_points": {"$gte": 10}}},  # At least 10 days of data
                    {"$sort": {"avg_vol": -1}},
                    {"$limit": 50}
                ]))
                
                for doc in top_volume_symbols:
                    sym = doc["_id"]
                    if sym not in smart_symbols:
                        smart_symbols.append(sym)
                        if len(smart_symbols) >= 30:
                            break
        
        # Fallback if no DB data
        if len(smart_symbols) < 10:
            smart_symbols = core_etfs + mega_caps[:23]
        
        # Ensure we use 30 symbols max for smart test
        smart_symbols = smart_symbols[:30]
        
        end_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        
        config = SimulationConfig(
            start_date=start_date,
            end_date=end_date,
            min_adv=100_000,
            min_price=5.0,
            max_price=500.0,
            min_rvol=0.3,
            universe="custom",
            custom_symbols=smart_symbols,
            starting_capital=100_000.0,
            max_position_pct=15.0,  # Slightly smaller positions for diversification
            max_open_positions=5,   # Allow more concurrent positions
            use_ai_agents=True,
            data_source="ib",  # Use IB collected data
            bar_size=normalized_bar_size  # Use requested timeframe
        )
        
        job_id = await _simulation_engine.start_simulation(config)
        
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Smart test started: {start_date} to {end_date} with {len(smart_symbols)} liquid symbols on {normalized_bar_size} bars",
            "test_type": "smart",
            "bar_size": normalized_bar_size,
            "symbols_count": len(smart_symbols),
            "symbols": smart_symbols,
            "config": config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Error starting smart test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
