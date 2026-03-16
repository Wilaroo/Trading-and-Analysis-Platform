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
async def quick_test_simulation():
    """
    Run a quick test simulation on a few symbols to verify everything works.
    Uses last 30 days and 10 liquid symbols from IB collected data.
    """
    if not _simulation_engine:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    
    try:
        from services.historical_simulation_engine import SimulationConfig
        
        # Get symbols that we have IB data for
        db = _simulation_engine._db
        test_symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "AMD", "META", "AMZN", "JPM", "SPY"]
        
        if db is not None:
            # Check which symbols we actually have data for
            available_symbols = db["ib_historical_data"].distinct("symbol")
            available_set = set(available_symbols)
            
            # Use our preferred test symbols if available, otherwise grab from what we have
            valid_symbols = [s for s in test_symbols if s in available_set]
            
            if len(valid_symbols) < 5:
                # Get high-volume symbols from our data
                top_symbols = list(db["ib_historical_data"].aggregate([
                    {"$match": {"bar_size": "1 day"}},
                    {"$group": {
                        "_id": "$symbol",
                        "avg_vol": {"$avg": "$volume"},
                        "count": {"$sum": 1}
                    }},
                    {"$match": {"count": {"$gte": 15}}},  # At least 15 days of data
                    {"$sort": {"avg_vol": -1}},
                    {"$limit": 20}
                ]))
                valid_symbols = [s["_id"] for s in top_symbols][:10]
            
            test_symbols = valid_symbols if valid_symbols else test_symbols
        
        end_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        
        config = SimulationConfig(
            start_date=start_date,
            end_date=end_date,
            min_adv=100_000,  # Lower threshold to match more stocks
            min_price=5.0,
            max_price=500.0,
            min_rvol=0.3,
            universe="custom",
            custom_symbols=test_symbols[:10],
            starting_capital=100_000.0,
            max_position_pct=20.0,
            max_open_positions=3,
            use_ai_agents=True,
            data_source="ib"  # Use IB collected data
        )
        
        job_id = await _simulation_engine.start_simulation(config)
        
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Quick test started: {start_date} to {end_date} with {len(test_symbols[:10])} symbols",
            "config": config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Error starting quick test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
