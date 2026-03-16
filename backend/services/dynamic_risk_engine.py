"""
Dynamic Risk Engine
====================
Intelligent position sizing based on multiple factors:
1. Portfolio Health (40%) - P&L trends, drawdown, win rate
2. Market Regime (30%) - VIX, breadth, trend
3. Stock-Specific (20%) - ATR, liquidity, correlation
4. Learning Layer (10%) - Historical performance patterns

Outputs a position size multiplier (0.25x - 2.0x by default)
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
import statistics

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    MINIMAL = "minimal"      # 0.25x - extreme caution
    REDUCED = "reduced"      # 0.5x - defensive
    NORMAL = "normal"        # 1.0x - standard
    ELEVATED = "elevated"    # 1.5x - confident
    MAXIMUM = "maximum"      # 2.0x - ideal conditions


@dataclass
class FactorScore:
    """Individual factor score with explanation"""
    name: str
    score: float  # 0.0 to 1.0
    weight: float
    details: Dict
    recommendation: str


@dataclass
class RiskAssessment:
    """Complete risk assessment result"""
    multiplier: float
    risk_level: RiskLevel
    factors: List[FactorScore]
    final_position_size: float
    base_position_size: float
    explanation: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            "multiplier": round(self.multiplier, 2),
            "risk_level": self.risk_level.value,
            "factors": [
                {
                    "name": f.name,
                    "score": round(f.score, 2),
                    "weight": f.weight,
                    "weighted_score": round(f.score * f.weight, 3),
                    "details": f.details,
                    "recommendation": f.recommendation
                }
                for f in self.factors
            ],
            "final_position_size": round(self.final_position_size, 2),
            "base_position_size": round(self.base_position_size, 2),
            "explanation": self.explanation,
            "timestamp": self.timestamp.isoformat()
        }


class DynamicRiskEngine:
    """
    Core engine for dynamic position sizing.
    Integrates with trading bot, market data, and learning systems.
    """
    
    def __init__(self):
        # Configuration
        self._enabled = True
        self._min_multiplier = 0.25
        self._max_multiplier = 2.0
        self._base_position_size = 1000.0  # Default, updated from bot config
        
        # Factor weights (must sum to 1.0)
        self._weights = {
            "portfolio_health": 0.40,
            "market_regime": 0.30,
            "stock_specific": 0.20,
            "learning_layer": 0.10
        }
        
        # Thresholds
        self._thresholds = {
            # Portfolio Health
            "max_daily_loss_pct": 3.0,       # Reduce size if down 3%+
            "drawdown_warning": 5.0,          # Caution at 5% drawdown
            "drawdown_critical": 10.0,        # Minimum size at 10%+ drawdown
            "win_streak_bonus": 5,            # Size up after 5 wins
            "loss_streak_penalty": 3,         # Size down after 3 losses
            
            # Market Regime
            "vix_low": 15,                    # Low volatility
            "vix_normal": 20,                 # Normal volatility
            "vix_elevated": 25,               # Elevated - reduce size
            "vix_extreme": 35,                # Extreme - minimum size
            
            # Stock Specific
            "atr_pct_warning": 4.0,           # High volatility stock
            "atr_pct_extreme": 7.0,           # Extreme volatility
            "min_adv": 500000,                # Minimum liquidity
        }
        
        # Override settings
        self._override_active = False
        self._override_multiplier = 1.0
        self._override_expiry: Optional[datetime] = None
        self._override_reason = ""
        
        # Cache for recent assessments
        self._assessment_history: List[RiskAssessment] = []
        self._max_history = 100
        
        # Learning data cache
        self._learning_cache: Dict = {}
        self._learning_cache_ttl = 300  # 5 minutes
        self._learning_cache_time: Optional[datetime] = None
        
        # Service references (injected)
        self._trading_bot = None
        self._market_data = None
        self._db = None
        
        logger.info("DynamicRiskEngine initialized")
    
    def inject_services(self, services: Dict):
        """Inject required services"""
        self._trading_bot = services.get("trading_bot")
        self._market_data = services.get("market_data")
        self._db = services.get("db")
        logger.info("DynamicRiskEngine services injected")
    
    # ==================== CONFIGURATION ====================
    
    def get_config(self) -> Dict:
        """Get current configuration"""
        return {
            "enabled": self._enabled,
            "min_multiplier": self._min_multiplier,
            "max_multiplier": self._max_multiplier,
            "base_position_size": self._base_position_size,
            "weights": self._weights.copy(),
            "thresholds": self._thresholds.copy(),
            "override": {
                "active": self._override_active,
                "multiplier": self._override_multiplier,
                "expiry": self._override_expiry.isoformat() if self._override_expiry else None,
                "reason": self._override_reason
            }
        }
    
    def update_config(self, config: Dict) -> Dict:
        """Update configuration"""
        if "enabled" in config:
            self._enabled = config["enabled"]
        if "min_multiplier" in config:
            self._min_multiplier = max(0.1, min(1.0, config["min_multiplier"]))
        if "max_multiplier" in config:
            self._max_multiplier = max(1.0, min(5.0, config["max_multiplier"]))
        if "base_position_size" in config:
            self._base_position_size = max(100, config["base_position_size"])
        if "weights" in config:
            # Validate weights sum to 1.0
            weights = config["weights"]
            total = sum(weights.values())
            if 0.99 <= total <= 1.01:
                self._weights.update(weights)
        if "thresholds" in config:
            self._thresholds.update(config["thresholds"])
        
        logger.info(f"DynamicRiskEngine config updated: {config}")
        return self.get_config()
    
    def set_override(self, multiplier: float, duration_minutes: int = 60, reason: str = "") -> Dict:
        """Set a temporary override multiplier"""
        self._override_active = True
        self._override_multiplier = max(self._min_multiplier, min(self._max_multiplier, multiplier))
        self._override_expiry = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        self._override_reason = reason
        
        logger.info(f"Override set: {multiplier}x for {duration_minutes}min - {reason}")
        return {
            "success": True,
            "override_multiplier": self._override_multiplier,
            "expiry": self._override_expiry.isoformat(),
            "reason": self._override_reason
        }
    
    def clear_override(self) -> Dict:
        """Clear any active override"""
        self._override_active = False
        self._override_multiplier = 1.0
        self._override_expiry = None
        self._override_reason = ""
        
        logger.info("Override cleared")
        return {"success": True, "message": "Override cleared"}
    
    # ==================== CORE ASSESSMENT ====================
    
    async def assess_risk(self, symbol: Optional[str] = None, setup_type: Optional[str] = None) -> RiskAssessment:
        """
        Perform a complete risk assessment and return position size multiplier.
        
        Args:
            symbol: Optional stock symbol for stock-specific scoring
            setup_type: Optional setup type for learning layer
        
        Returns:
            RiskAssessment with multiplier and detailed breakdown
        """
        # Check for override
        if self._override_active:
            if self._override_expiry and datetime.now(timezone.utc) > self._override_expiry:
                self.clear_override()
            else:
                return self._create_override_assessment()
        
        if not self._enabled:
            return self._create_disabled_assessment()
        
        # Calculate all factor scores
        factors = []
        
        # 1. Portfolio Health (40%)
        portfolio_score = await self._calculate_portfolio_health()
        factors.append(portfolio_score)
        
        # 2. Market Regime (30%)
        market_score = await self._calculate_market_regime()
        factors.append(market_score)
        
        # 3. Stock-Specific (20%)
        stock_score = await self._calculate_stock_specific(symbol)
        factors.append(stock_score)
        
        # 4. Learning Layer (10%)
        learning_score = await self._calculate_learning_layer(symbol, setup_type)
        factors.append(learning_score)
        
        # Calculate weighted score (0.0 to 1.0)
        weighted_total = sum(f.score * f.weight for f in factors)
        
        # Convert to multiplier (0.25 to 2.0)
        # Score of 0.0 -> min_multiplier, Score of 1.0 -> max_multiplier
        # Score of 0.5 -> 1.0 (neutral)
        if weighted_total >= 0.5:
            # Above neutral: scale from 1.0 to max
            multiplier = 1.0 + (weighted_total - 0.5) * 2 * (self._max_multiplier - 1.0)
        else:
            # Below neutral: scale from min to 1.0
            multiplier = self._min_multiplier + weighted_total * 2 * (1.0 - self._min_multiplier)
        
        multiplier = round(max(self._min_multiplier, min(self._max_multiplier, multiplier)), 2)
        
        # Determine risk level
        risk_level = self._determine_risk_level(multiplier)
        
        # Generate explanation
        explanation = self._generate_explanation(factors, multiplier, risk_level)
        
        # Create assessment
        assessment = RiskAssessment(
            multiplier=multiplier,
            risk_level=risk_level,
            factors=factors,
            final_position_size=self._base_position_size * multiplier,
            base_position_size=self._base_position_size,
            explanation=explanation
        )
        
        # Store in history
        self._assessment_history.append(assessment)
        if len(self._assessment_history) > self._max_history:
            self._assessment_history = self._assessment_history[-self._max_history:]
        
        return assessment
    
    # ==================== FACTOR CALCULATIONS ====================
    
    async def _calculate_portfolio_health(self) -> FactorScore:
        """Calculate portfolio health score (0.0 = worst, 1.0 = best)"""
        details = {}
        score_components = []
        
        try:
            # Get portfolio data
            daily_pnl_pct = 0.0
            drawdown_pct = 0.0
            win_rate = 0.5
            streak = 0
            
            if self._trading_bot:
                try:
                    status = self._trading_bot.get_status() if hasattr(self._trading_bot, 'get_status') else {}
                    daily_pnl_pct = status.get('daily_pnl_pct', 0)
                    drawdown_pct = abs(status.get('drawdown_pct', 0))
                except:
                    pass
            
            # Try to get from database
            if self._db is not None:
                try:
                    # Get recent trades for win rate and streak
                    trades_col = self._db['trade_history']
                    recent_trades = list(trades_col.find(
                        {"status": "closed"},
                        {"pnl": 1, "closed_at": 1}
                    ).sort("closed_at", -1).limit(20))
                    
                    if recent_trades:
                        wins = sum(1 for t in recent_trades if t.get('pnl', 0) > 0)
                        win_rate = wins / len(recent_trades)
                        
                        # Calculate streak
                        streak = 0
                        if recent_trades:
                            first_pnl = recent_trades[0].get('pnl', 0)
                            streak_positive = first_pnl > 0
                            for t in recent_trades:
                                if (t.get('pnl', 0) > 0) == streak_positive:
                                    streak += 1
                                else:
                                    break
                            if not streak_positive:
                                streak = -streak
                except Exception as e:
                    logger.debug(f"Could not fetch trade history: {e}")
            
            details = {
                "daily_pnl_pct": round(daily_pnl_pct, 2),
                "drawdown_pct": round(drawdown_pct, 2),
                "win_rate": round(win_rate, 2),
                "streak": streak
            }
            
            # Score components (each 0-1)
            
            # Daily P&L score
            if daily_pnl_pct <= -self._thresholds["max_daily_loss_pct"]:
                pnl_score = 0.0
            elif daily_pnl_pct >= 2.0:
                pnl_score = 1.0
            else:
                pnl_score = 0.5 + (daily_pnl_pct / 4.0)  # Normalize to 0-1
            score_components.append(pnl_score * 0.3)
            
            # Drawdown score
            if drawdown_pct >= self._thresholds["drawdown_critical"]:
                dd_score = 0.0
            elif drawdown_pct >= self._thresholds["drawdown_warning"]:
                dd_score = 0.3
            elif drawdown_pct > 0:
                dd_score = 1.0 - (drawdown_pct / self._thresholds["drawdown_warning"])
            else:
                dd_score = 1.0
            score_components.append(dd_score * 0.3)
            
            # Win rate score
            wr_score = min(1.0, win_rate / 0.6)  # 60%+ win rate = max score
            score_components.append(wr_score * 0.2)
            
            # Streak score
            if streak >= self._thresholds["win_streak_bonus"]:
                streak_score = 1.0
            elif streak <= -self._thresholds["loss_streak_penalty"]:
                streak_score = 0.0
            else:
                streak_score = 0.5 + (streak / 10.0)
            score_components.append(streak_score * 0.2)
            
            final_score = sum(score_components)
            
        except Exception as e:
            logger.error(f"Error calculating portfolio health: {e}")
            final_score = 0.5
            details = {"error": str(e)}
        
        # Generate recommendation
        if final_score >= 0.7:
            recommendation = "Portfolio performing well - conditions favor larger positions"
        elif final_score >= 0.4:
            recommendation = "Portfolio health neutral - maintain standard sizing"
        else:
            recommendation = "Portfolio under stress - reduce position sizes to protect capital"
        
        return FactorScore(
            name="Portfolio Health",
            score=final_score,
            weight=self._weights["portfolio_health"],
            details=details,
            recommendation=recommendation
        )
    
    async def _calculate_market_regime(self) -> FactorScore:
        """Calculate market regime score based on VIX, breadth, trend"""
        details = {}
        score_components = []
        
        try:
            vix = 20.0  # Default
            spy_trend = "neutral"
            breadth = 0.5
            
            # Try to get VIX from market data
            if self._market_data:
                try:
                    vix_data = await self._market_data.get_quote("VIX") if hasattr(self._market_data, 'get_quote') else None
                    if vix_data:
                        vix = vix_data.get('last', 20.0)
                except:
                    pass
            
            # Try to get SPY trend
            if self._db is not None:
                try:
                    # Check if SPY is above/below moving average from cached data
                    market_col = self._db.get('market_regime')
                    if market_col:
                        regime_data = market_col.find_one({"symbol": "SPY"})
                        if regime_data:
                            spy_trend = regime_data.get('trend', 'neutral')
                            breadth = regime_data.get('breadth', 0.5)
                except:
                    pass
            
            details = {
                "vix": round(vix, 2),
                "spy_trend": spy_trend,
                "market_breadth": round(breadth, 2)
            }
            
            # VIX score (40% of market regime)
            if vix >= self._thresholds["vix_extreme"]:
                vix_score = 0.0
            elif vix >= self._thresholds["vix_elevated"]:
                vix_score = 0.25
            elif vix >= self._thresholds["vix_normal"]:
                vix_score = 0.5
            elif vix >= self._thresholds["vix_low"]:
                vix_score = 0.75
            else:
                vix_score = 1.0
            score_components.append(vix_score * 0.4)
            
            # SPY trend score (30%)
            trend_scores = {"bullish": 1.0, "neutral": 0.5, "bearish": 0.2}
            trend_score = trend_scores.get(spy_trend, 0.5)
            score_components.append(trend_score * 0.3)
            
            # Breadth score (30%)
            breadth_score = breadth  # Already 0-1
            score_components.append(breadth_score * 0.3)
            
            final_score = sum(score_components)
            
        except Exception as e:
            logger.error(f"Error calculating market regime: {e}")
            final_score = 0.5
            details = {"error": str(e)}
        
        # Generate recommendation
        if final_score >= 0.7:
            recommendation = "Market conditions favorable - low volatility, bullish trend"
        elif final_score >= 0.4:
            recommendation = "Market conditions mixed - proceed with standard caution"
        else:
            recommendation = "Market conditions challenging - high volatility or bearish trend, reduce exposure"
        
        return FactorScore(
            name="Market Regime",
            score=final_score,
            weight=self._weights["market_regime"],
            details=details,
            recommendation=recommendation
        )
    
    async def _calculate_stock_specific(self, symbol: Optional[str]) -> FactorScore:
        """Calculate stock-specific score based on volatility and liquidity"""
        details = {}
        
        if not symbol:
            return FactorScore(
                name="Stock-Specific",
                score=0.5,  # Neutral if no symbol
                weight=self._weights["stock_specific"],
                details={"note": "No symbol provided - using neutral score"},
                recommendation="Provide a symbol for stock-specific risk assessment"
            )
        
        try:
            atr_pct = 2.0  # Default
            adv = 1000000  # Default
            
            # Try to get stock data
            if self._market_data:
                try:
                    quote = await self._market_data.get_quote(symbol) if hasattr(self._market_data, 'get_quote') else None
                    if quote:
                        price = quote.get('last', 100)
                        atr = quote.get('atr', price * 0.02)
                        atr_pct = (atr / price) * 100 if price > 0 else 2.0
                        adv = quote.get('adv', 1000000)
                except:
                    pass
            
            details = {
                "symbol": symbol,
                "atr_pct": round(atr_pct, 2),
                "adv": adv
            }
            
            # ATR score (60% of stock-specific)
            if atr_pct >= self._thresholds["atr_pct_extreme"]:
                atr_score = 0.0
            elif atr_pct >= self._thresholds["atr_pct_warning"]:
                atr_score = 0.3
            elif atr_pct >= 2.0:
                atr_score = 0.6
            else:
                atr_score = 1.0
            
            # Liquidity score (40%)
            if adv >= self._thresholds["min_adv"] * 2:
                liq_score = 1.0
            elif adv >= self._thresholds["min_adv"]:
                liq_score = 0.7
            else:
                liq_score = 0.3
            
            final_score = (atr_score * 0.6) + (liq_score * 0.4)
            
        except Exception as e:
            logger.error(f"Error calculating stock-specific score: {e}")
            final_score = 0.5
            details = {"error": str(e), "symbol": symbol}
        
        # Generate recommendation
        if final_score >= 0.7:
            recommendation = f"{symbol} has favorable volatility and liquidity for full sizing"
        elif final_score >= 0.4:
            recommendation = f"{symbol} has moderate risk characteristics"
        else:
            recommendation = f"{symbol} is highly volatile or illiquid - reduce position size"
        
        return FactorScore(
            name="Stock-Specific",
            score=final_score,
            weight=self._weights["stock_specific"],
            details=details,
            recommendation=recommendation
        )
    
    async def _calculate_learning_layer(self, symbol: Optional[str], setup_type: Optional[str]) -> FactorScore:
        """Calculate score based on historical learning data"""
        details = {}
        
        try:
            # Check cache
            now = datetime.now(timezone.utc)
            if self._learning_cache_time and (now - self._learning_cache_time).total_seconds() < self._learning_cache_ttl:
                learning_data = self._learning_cache
            else:
                learning_data = await self._fetch_learning_data()
                self._learning_cache = learning_data
                self._learning_cache_time = now
            
            setup_score = 0.5
            time_score = 0.5
            sector_score = 0.5
            
            # Setup type performance
            if setup_type and setup_type in learning_data.get('setup_performance', {}):
                setup_stats = learning_data['setup_performance'][setup_type]
                setup_win_rate = setup_stats.get('win_rate', 0.5)
                setup_score = min(1.0, setup_win_rate / 0.6)
                details['setup_type'] = setup_type
                details['setup_win_rate'] = round(setup_win_rate, 2)
            
            # Time of day performance
            current_hour = now.hour
            time_performance = learning_data.get('time_performance', {})
            if str(current_hour) in time_performance:
                time_stats = time_performance[str(current_hour)]
                time_win_rate = time_stats.get('win_rate', 0.5)
                time_score = min(1.0, time_win_rate / 0.6)
                details['hour'] = current_hour
                details['hour_win_rate'] = round(time_win_rate, 2)
            
            # Sector performance (if we can determine sector)
            # This would require sector lookup - simplified for now
            details['learning_data_available'] = bool(learning_data.get('setup_performance'))
            
            final_score = (setup_score * 0.5) + (time_score * 0.3) + (sector_score * 0.2)
            
        except Exception as e:
            logger.error(f"Error calculating learning layer: {e}")
            final_score = 0.5
            details = {"error": str(e)}
        
        # Generate recommendation
        if final_score >= 0.7:
            recommendation = "Historical data suggests favorable conditions for this type of trade"
        elif final_score >= 0.4:
            recommendation = "Historical performance is mixed - standard sizing recommended"
        else:
            recommendation = "Historical data suggests caution - this setup/time has underperformed"
        
        return FactorScore(
            name="Learning Layer",
            score=final_score,
            weight=self._weights["learning_layer"],
            details=details,
            recommendation=recommendation
        )
    
    async def _fetch_learning_data(self) -> Dict:
        """Fetch learning data from database"""
        learning_data = {
            'setup_performance': {},
            'time_performance': {},
            'sector_performance': {}
        }
        
        if not self._db:
            return learning_data
        
        try:
            trades_col = self._db['trade_history']
            
            # Get trades from last 90 days
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            trades = list(trades_col.find(
                {"status": "closed", "closed_at": {"$gte": cutoff}},
                {"pnl": 1, "setup_type": 1, "entry_time": 1, "symbol": 1}
            ))
            
            if not trades:
                return learning_data
            
            # Calculate setup performance
            setup_trades = {}
            for t in trades:
                setup = t.get('setup_type', 'unknown')
                if setup not in setup_trades:
                    setup_trades[setup] = []
                setup_trades[setup].append(t.get('pnl', 0) > 0)
            
            for setup, results in setup_trades.items():
                if len(results) >= 5:  # Need at least 5 trades
                    learning_data['setup_performance'][setup] = {
                        'win_rate': sum(results) / len(results),
                        'trade_count': len(results)
                    }
            
            # Calculate time performance
            time_trades = {}
            for t in trades:
                entry_time = t.get('entry_time')
                if entry_time:
                    hour = entry_time.hour if hasattr(entry_time, 'hour') else 12
                    if hour not in time_trades:
                        time_trades[hour] = []
                    time_trades[hour].append(t.get('pnl', 0) > 0)
            
            for hour, results in time_trades.items():
                if len(results) >= 3:
                    learning_data['time_performance'][str(hour)] = {
                        'win_rate': sum(results) / len(results),
                        'trade_count': len(results)
                    }
            
        except Exception as e:
            logger.error(f"Error fetching learning data: {e}")
        
        return learning_data
    
    # ==================== HELPERS ====================
    
    def _determine_risk_level(self, multiplier: float) -> RiskLevel:
        """Determine risk level from multiplier"""
        if multiplier <= 0.35:
            return RiskLevel.MINIMAL
        elif multiplier <= 0.65:
            return RiskLevel.REDUCED
        elif multiplier <= 1.25:
            return RiskLevel.NORMAL
        elif multiplier <= 1.75:
            return RiskLevel.ELEVATED
        else:
            return RiskLevel.MAXIMUM
    
    def _generate_explanation(self, factors: List[FactorScore], multiplier: float, risk_level: RiskLevel) -> str:
        """Generate human-readable explanation"""
        # Find the most impactful factors
        sorted_factors = sorted(factors, key=lambda f: abs(f.score - 0.5) * f.weight, reverse=True)
        
        if risk_level == RiskLevel.MAXIMUM:
            opener = "Conditions are ideal for larger positions."
        elif risk_level == RiskLevel.ELEVATED:
            opener = "Conditions favor slightly larger positions."
        elif risk_level == RiskLevel.NORMAL:
            opener = "Conditions suggest standard position sizing."
        elif risk_level == RiskLevel.REDUCED:
            opener = "Caution advised - reducing position sizes."
        else:
            opener = "High risk detected - using minimum position sizes."
        
        # Add top factor insights
        insights = []
        for f in sorted_factors[:2]:
            if f.score >= 0.7:
                insights.append(f"{f.name} is favorable")
            elif f.score <= 0.3:
                insights.append(f"{f.name} signals caution")
        
        if insights:
            return f"{opener} {', '.join(insights)}. Sizing at {multiplier}x."
        return f"{opener} Sizing at {multiplier}x."
    
    def _create_override_assessment(self) -> RiskAssessment:
        """Create assessment when override is active"""
        return RiskAssessment(
            multiplier=self._override_multiplier,
            risk_level=self._determine_risk_level(self._override_multiplier),
            factors=[],
            final_position_size=self._base_position_size * self._override_multiplier,
            base_position_size=self._base_position_size,
            explanation=f"Manual override active: {self._override_multiplier}x - {self._override_reason}"
        )
    
    def _create_disabled_assessment(self) -> RiskAssessment:
        """Create assessment when engine is disabled"""
        return RiskAssessment(
            multiplier=1.0,
            risk_level=RiskLevel.NORMAL,
            factors=[],
            final_position_size=self._base_position_size,
            base_position_size=self._base_position_size,
            explanation="Dynamic risk engine disabled - using standard sizing"
        )
    
    # ==================== STATUS & HISTORY ====================
    
    def get_status(self) -> Dict:
        """Get current engine status"""
        latest = self._assessment_history[-1] if self._assessment_history else None
        
        return {
            "enabled": self._enabled,
            "current_multiplier": latest.multiplier if latest else 1.0,
            "current_risk_level": latest.risk_level.value if latest else "normal",
            "base_position_size": self._base_position_size,
            "effective_position_size": latest.final_position_size if latest else self._base_position_size,
            "last_assessment": latest.to_dict() if latest else None,
            "override": {
                "active": self._override_active,
                "multiplier": self._override_multiplier if self._override_active else None,
                "expiry": self._override_expiry.isoformat() if self._override_expiry else None,
                "reason": self._override_reason
            },
            "assessments_today": len([a for a in self._assessment_history 
                                      if a.timestamp.date() == datetime.now(timezone.utc).date()])
        }
    
    def get_history(self, limit: int = 20) -> List[Dict]:
        """Get recent assessment history"""
        return [a.to_dict() for a in self._assessment_history[-limit:]]
    
    def get_factor_summary(self) -> Dict:
        """Get summary of recent factor scores for analytics"""
        if not self._assessment_history:
            return {}
        
        recent = self._assessment_history[-20:]
        
        summary = {}
        for factor_name in ["Portfolio Health", "Market Regime", "Stock-Specific", "Learning Layer"]:
            scores = []
            for assessment in recent:
                for f in assessment.factors:
                    if f.name == factor_name:
                        scores.append(f.score)
                        break
            
            if scores:
                summary[factor_name] = {
                    "avg_score": round(statistics.mean(scores), 2),
                    "min_score": round(min(scores), 2),
                    "max_score": round(max(scores), 2),
                    "latest_score": round(scores[-1], 2) if scores else 0.5
                }
        
        return summary


# Singleton instance
_dynamic_risk_engine: Optional[DynamicRiskEngine] = None


def get_dynamic_risk_engine() -> DynamicRiskEngine:
    """Get singleton instance of DynamicRiskEngine"""
    global _dynamic_risk_engine
    if _dynamic_risk_engine is None:
        _dynamic_risk_engine = DynamicRiskEngine()
    return _dynamic_risk_engine
