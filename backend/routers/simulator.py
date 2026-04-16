"""
Market Simulator API Router
Provides endpoints for testing scanner alerts when markets are closed.
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional
import asyncio
import logging

from services.market_simulator_service import get_market_simulator, SCENARIOS

router = APIRouter(prefix="/api/simulator", tags=["Market Simulator"])
logger = logging.getLogger(__name__)


def _ensure_initialized():
    """Ensure simulator has Alpaca service for real prices"""
    simulator = get_market_simulator()
    if simulator._alpaca_service is None:
        try:
            from services.alpaca_service import get_alpaca_service
            alpaca = get_alpaca_service()
            simulator.set_alpaca_service(alpaca)
        except Exception as e:
            logger.warning(f"Could not set Alpaca service for simulator: {e}")
    return simulator


@router.get("/status")
def get_status():
    """Get simulator status"""
    simulator = _ensure_initialized()
    return {
        "success": True,
        **simulator.get_status()
    }


@router.post("/start")
async def start_simulator(scenario: Optional[str] = None, interval: Optional[int] = None):
    """
    Start the market simulator.
    
    Args:
        scenario: One of: bullish_momentum, bearish_reversal, range_bound, high_volatility
        interval: Seconds between alerts (5-120)
    """
    simulator = _ensure_initialized()
    
    if scenario:
        if scenario not in SCENARIOS:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid scenario. Choose from: {list(SCENARIOS.keys())}"
            )
        simulator.set_scenario(scenario)
    
    if interval:
        simulator.set_interval(interval)
    
    await simulator.start()
    
    return {
        "success": True,
        "message": "Simulator started",
        **simulator.get_status()
    }


@router.post("/stop")
def stop_simulator():
    """Stop the market simulator"""
    simulator = _ensure_initialized()
    simulator.stop()
    
    return {
        "success": True,
        "message": "Simulator stopped"
    }


@router.get("/alerts")
def get_simulated_alerts():
    """Get all generated simulated alerts"""
    simulator = _ensure_initialized()
    alerts = simulator.get_alerts()
    
    return {
        "success": True,
        "count": len(alerts),
        "alerts": alerts
    }


@router.post("/generate")
async def generate_single_alert():
    """Generate a single alert on demand"""
    simulator = _ensure_initialized()
    alert = await simulator.generate_single_alert()
    
    if alert:
        return {
            "success": True,
            "alert": alert
        }
    else:
        return {
            "success": False,
            "message": "Could not generate alert"
        }


@router.post("/scenario/{scenario_name}")
def set_scenario(scenario_name: str):
    """Change the simulation scenario"""
    simulator = _ensure_initialized()
    
    if scenario_name not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scenario. Choose from: {list(SCENARIOS.keys())}"
        )
    
    simulator.set_scenario(scenario_name)
    
    return {
        "success": True,
        "scenario": scenario_name,
        "description": SCENARIOS[scenario_name]["description"]
    }


@router.get("/scenarios")
def list_scenarios():
    """List all available scenarios"""
    return {
        "success": True,
        "scenarios": {
            name: info["description"] 
            for name, info in SCENARIOS.items()
        }
    }


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint for real-time simulated alerts.
    Connect to receive alerts as they're generated.
    """
    await websocket.accept()
    simulator = _ensure_initialized()
    queue = simulator.subscribe()
    
    try:
        while True:
            try:
                # Wait for alert with timeout
                alert = await asyncio.wait_for(queue.get(), timeout=60)
                await websocket.send_json(alert)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        simulator.unsubscribe(queue)
