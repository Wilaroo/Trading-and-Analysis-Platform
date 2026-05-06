"""
Market Hours Simulator Service
Generates synthetic scanner alerts for testing when markets are closed.
Useful for:
- Testing alert flow end-to-end
- Demonstrating scanner capabilities
- Training and familiarization

Generates realistic alerts based on configured scenarios.
"""
import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Sample watchlist for simulation
SIMULATION_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "AMD", 
    "NFLX", "JPM", "BAC", "V", "MA", "UNH", "JNJ", "XOM", "CVX"
]

# Setup types for simulation
SETUP_TYPES = [
    ("rubber_band", "Rubber Band Scalp", "Mean reversion from EMA9"),
    ("squeeze", "TTM Squeeze", "Volatility compression breakout"),
    ("vwap_bounce", "VWAP Bounce", "Support at VWAP"),
    ("breakout", "Breakout", "Range/resistance breakout"),
    ("relative_strength", "Relative Strength", "Outperforming SPY"),
    ("gap_fade", "Gap Fade", "Fading failed gap"),
    ("orb", "Opening Range Breakout", "Breaking opening range"),
    ("chart_pattern", "Chart Pattern", "Technical pattern forming"),
]

# Scenario templates
SCENARIOS = {
    "bullish_momentum": {
        "description": "Strong uptrend day - momentum setups",
        "setups": ["breakout", "relative_strength", "orb"],
        "direction_bias": "long",
        "priority_weights": {"critical": 0.2, "high": 0.4, "medium": 0.3, "low": 0.1}
    },
    "bearish_reversal": {
        "description": "Market weakness - reversal setups",
        "setups": ["rubber_band", "gap_fade", "vwap_bounce"],
        "direction_bias": "short",
        "priority_weights": {"critical": 0.15, "high": 0.35, "medium": 0.35, "low": 0.15}
    },
    "range_bound": {
        "description": "Choppy market - mean reversion",
        "setups": ["rubber_band", "vwap_bounce", "squeeze"],
        "direction_bias": "mixed",
        "priority_weights": {"critical": 0.1, "high": 0.3, "medium": 0.4, "low": 0.2}
    },
    "high_volatility": {
        "description": "High VIX environment - squeeze plays",
        "setups": ["squeeze", "breakout", "chart_pattern"],
        "direction_bias": "mixed",
        "priority_weights": {"critical": 0.25, "high": 0.35, "medium": 0.25, "low": 0.15}
    }
}


@dataclass
class SimulatedAlert:
    """Simulated scanner alert"""
    id: str
    symbol: str
    setup_type: str
    strategy_name: str
    direction: str
    priority: str
    current_price: float
    trigger_price: float
    stop_loss: float
    target: float
    risk_reward: float
    headline: str
    reasoning: List[str]
    time_window: str
    tape_confirmation: bool
    created_at: str
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "setup_type": self.setup_type,
            "strategy_name": self.strategy_name,
            "direction": self.direction,
            "priority": self.priority,
            "current_price": self.current_price,
            "trigger_price": self.trigger_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "risk_reward": self.risk_reward,
            "headline": self.headline,
            "reasoning": self.reasoning,
            "time_window": self.time_window,
            "tape_confirmation": self.tape_confirmation,
            "created_at": self.created_at,
            "simulated": True
        }


class MarketSimulator:
    """
    Simulates market scanner activity for testing purposes.
    Generates realistic alerts based on scenarios.
    """
    
    def __init__(self):
        self._running = False
        self._scenario = "range_bound"
        self._alert_interval = 30  # Seconds between alerts
        self._subscribers: List[asyncio.Queue] = []
        self._generated_alerts: List[SimulatedAlert] = []
        self._max_alerts = 20
        self._alpaca_service = None
    
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for real price data"""
        self._alpaca_service = alpaca_service
    
    def subscribe(self) -> asyncio.Queue:
        """Subscribe to simulated alerts"""
        queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(queue)
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from alerts"""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
    
    def set_scenario(self, scenario: str):
        """Set the simulation scenario"""
        if scenario in SCENARIOS:
            self._scenario = scenario
            logger.info(f"Simulator scenario set to: {scenario}")
        else:
            logger.warning(f"Unknown scenario: {scenario}")
    
    def set_interval(self, seconds: int):
        """Set interval between alerts (5-120 seconds)"""
        self._alert_interval = max(5, min(120, seconds))
    
    async def start(self):
        """Start the simulator"""
        if self._running:
            return
        
        self._running = True
        logger.info(f"Starting market simulator with scenario: {self._scenario}")
        asyncio.create_task(self._simulation_loop())
    
    def stop(self):
        """Stop the simulator"""
        self._running = False
        logger.info("Market simulator stopped")
    
    async def _simulation_loop(self):
        """Main simulation loop"""
        while self._running:
            try:
                alert = await self._generate_alert()
                if alert:
                    self._generated_alerts.append(alert)
                    
                    # Enforce max alerts
                    if len(self._generated_alerts) > self._max_alerts:
                        self._generated_alerts = self._generated_alerts[-self._max_alerts:]
                    
                    # Notify subscribers
                    await self._notify_subscribers(alert)
                    
                    logger.info(f"[SIMULATOR] Generated: {alert.headline}")
                
                await asyncio.sleep(self._alert_interval)
            except Exception as e:
                logger.error(f"Simulator error: {e}")
                await asyncio.sleep(5)
    
    async def _generate_alert(self) -> Optional[SimulatedAlert]:
        """Generate a realistic simulated alert"""
        scenario = SCENARIOS[self._scenario]
        
        # Select random symbol and setup
        symbol = random.choice(SIMULATION_SYMBOLS)
        setup_type, strategy_name, description = random.choice(
            [(s, n, d) for s, n, d in SETUP_TYPES if s in scenario["setups"]]
        )
        
        # Get real price if possible
        current_price = await self._get_price(symbol)
        if not current_price:
            current_price = random.uniform(50, 500)
        
        # Determine direction
        if scenario["direction_bias"] == "mixed":
            direction = random.choice(["long", "short"])
        else:
            direction = scenario["direction_bias"]
        
        # Calculate prices
        atr = current_price * random.uniform(0.015, 0.035)  # 1.5-3.5% ATR
        
        if direction == "long":
            trigger_price = current_price * random.uniform(0.998, 1.002)
            stop_loss = trigger_price - atr * random.uniform(1.0, 1.5)
            target = trigger_price + atr * random.uniform(2.0, 4.0)
        else:
            trigger_price = current_price * random.uniform(0.998, 1.002)
            stop_loss = trigger_price + atr * random.uniform(1.0, 1.5)
            target = trigger_price - atr * random.uniform(2.0, 4.0)
        
        risk = abs(trigger_price - stop_loss)
        reward = abs(target - trigger_price)
        risk_reward = round(reward / risk, 2) if risk > 0 else 2.0
        
        # Determine priority
        priority = self._weighted_choice(scenario["priority_weights"])
        
        # Generate headline
        direction_word = "LONG" if direction == "long" else "SHORT"
        headline = f"{setup_type.upper().replace('_', ' ')} {symbol} {direction_word}"
        
        # Generate reasoning
        reasoning = [
            description,
            f"Price: ${current_price:.2f}",
            f"ATR: ${atr:.2f} ({atr/current_price*100:.1f}%)",
            f"R:R = {risk_reward:.1f}",
            f"Scenario: {scenario['description']}"
        ]
        
        tape_confirmation = random.random() > 0.4  # 60% chance of tape confirmation
        if tape_confirmation:
            reasoning.append("Tape confirmation: YES")
        
        return SimulatedAlert(
            id=f"sim_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=setup_type,
            strategy_name=strategy_name,
            direction=direction,
            priority=priority,
            current_price=round(current_price, 2),
            trigger_price=round(trigger_price, 2),
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=risk_reward,
            headline=headline,
            reasoning=reasoning,
            time_window="simulated",
            tape_confirmation=tape_confirmation,
            created_at=datetime.now(timezone.utc).isoformat()
        )
    
    async def _get_price(self, symbol: str) -> Optional[float]:
        """Get real price from Alpaca if available"""
        if self._alpaca_service:
            try:
                quote = await self._alpaca_service.get_quote(symbol)
                if quote:
                    return quote.get("price", 0)
            except:
                pass
        return None
    
    def _weighted_choice(self, weights: Dict[str, float]) -> str:
        """Choose based on weights"""
        items = list(weights.keys())
        probs = list(weights.values())
        return random.choices(items, weights=probs, k=1)[0]
    
    async def _notify_subscribers(self, alert: SimulatedAlert):
        """Notify all subscribers of new alert"""
        alert_data = alert.to_dict()
        for queue in self._subscribers:
            try:
                queue.put_nowait(alert_data)
            except asyncio.QueueFull:
                pass
    
    def get_alerts(self) -> List[Dict]:
        """Get all generated alerts"""
        return [a.to_dict() for a in self._generated_alerts]
    
    def get_status(self) -> Dict:
        """Get simulator status"""
        return {
            "running": self._running,
            "scenario": self._scenario,
            "scenario_description": SCENARIOS[self._scenario]["description"],
            "alert_interval": self._alert_interval,
            "alerts_generated": len(self._generated_alerts),
            "subscribers": len(self._subscribers),
            "available_scenarios": list(SCENARIOS.keys())
        }
    
    async def generate_single_alert(self) -> Optional[Dict]:
        """Generate a single alert on demand"""
        alert = await self._generate_alert()
        if alert:
            self._generated_alerts.append(alert)
            await self._notify_subscribers(alert)
            return alert.to_dict()
        return None


# Singleton instance
_simulator: Optional[MarketSimulator] = None


def get_market_simulator() -> MarketSimulator:
    """Get or create the market simulator singleton"""
    global _simulator
    if _simulator is None:
        _simulator = MarketSimulator()
    return _simulator
