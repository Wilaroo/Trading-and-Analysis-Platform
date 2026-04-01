"""
Agent Data Service - Shared Historical Data Layer for AI Agents

Breaks the agent silos by providing all AI agents (Bull, Bear, Coach, Risk Manager)
with access to:
1. IB Historical Data - OHLCV bars for technical analysis
2. Alert Outcomes - Historical accuracy of setup types
3. Trade Journal - User's historical trades and performance
4. Symbol-specific statistics

This enables agents to make more informed decisions based on:
- "This symbol's ORB setups have 72% win rate over 90 days"
- "You've traded NVDA 15 times with 67% win rate"
- "This setup type historically has 1.8R average"
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SymbolContext:
    """Historical context for a specific symbol"""
    symbol: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_r_multiple: float = 0.0
    avg_hold_time_minutes: int = 0
    best_trade_r: float = 0.0
    worst_trade_r: float = 0.0
    last_traded: Optional[str] = None
    recent_bars_available: int = 0
    avg_volume_20d: float = 0.0
    volatility_20d: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "avg_hold_time_minutes": self.avg_hold_time_minutes,
            "best_trade_r": round(self.best_trade_r, 2),
            "worst_trade_r": round(self.worst_trade_r, 2),
            "last_traded": self.last_traded,
            "recent_bars_available": self.recent_bars_available,
            "avg_volume_20d": round(self.avg_volume_20d, 0),
            "volatility_20d": round(self.volatility_20d, 4)
        }


@dataclass
class SetupTypeContext:
    """Historical context for a setup type"""
    setup_type: str
    total_alerts: int = 0
    traded_count: int = 0
    profitable_count: int = 0
    win_rate: float = 0.0
    avg_r_multiple: float = 0.0
    best_regime: str = ""
    worst_regime: str = ""
    best_time_of_day: str = ""
    sample_size_adequate: bool = False  # True if >20 samples
    
    def to_dict(self) -> Dict:
        return {
            "setup_type": self.setup_type,
            "total_alerts": self.total_alerts,
            "traded_count": self.traded_count,
            "profitable_count": self.profitable_count,
            "win_rate": round(self.win_rate, 2),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "best_regime": self.best_regime,
            "worst_regime": self.worst_regime,
            "best_time_of_day": self.best_time_of_day,
            "sample_size_adequate": self.sample_size_adequate
        }


class AgentDataService:
    """
    Provides shared data access for all AI agents.
    
    Usage:
        data_service = get_agent_data_service()
        data_service.set_db(db)
        
        # In agent code:
        symbol_ctx = await data_service.get_symbol_context("NVDA")
        setup_ctx = await data_service.get_setup_type_context("orb_breakout")
    """
    
    def __init__(self):
        self._db = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        logger.info("AgentDataService connected to database")
        
    def get_symbol_context(self, symbol: str, days: int = 90) -> SymbolContext:
        """
        Get historical context for a specific symbol.
        
        Returns trading history, win rate, and technical data availability.
        """
        if self._db is None:
            return SymbolContext(symbol=symbol)
            
        ctx = SymbolContext(symbol=symbol.upper())
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            # Get trade history for this symbol
            trades = list(self._db["trade_outcomes"].find({
                "symbol": symbol.upper(),
                "timestamp": {"$gte": cutoff.isoformat()}
            }))
            
            if trades:
                ctx.total_trades = len(trades)
                ctx.winning_trades = len([t for t in trades if t.get("pnl", 0) > 0])
                ctx.losing_trades = len([t for t in trades if t.get("pnl", 0) <= 0])
                ctx.win_rate = ctx.winning_trades / ctx.total_trades if ctx.total_trades > 0 else 0
                
                r_multiples = [t.get("r_multiple", 0) for t in trades if t.get("r_multiple") is not None]
                if r_multiples:
                    ctx.avg_r_multiple = sum(r_multiples) / len(r_multiples)
                    ctx.best_trade_r = max(r_multiples)
                    ctx.worst_trade_r = min(r_multiples)
                    
                # Calculate average hold time
                hold_times = []
                for t in trades:
                    if t.get("entry_time") and t.get("exit_time"):
                        try:
                            entry = datetime.fromisoformat(t["entry_time"].replace('Z', '+00:00'))
                            exit = datetime.fromisoformat(t["exit_time"].replace('Z', '+00:00'))
                            hold_times.append((exit - entry).total_seconds() / 60)
                        except (ValueError, KeyError, TypeError):
                            pass
                if hold_times:
                    ctx.avg_hold_time_minutes = int(sum(hold_times) / len(hold_times))
                    
                # Last traded
                latest = max(trades, key=lambda t: t.get("timestamp", ""))
                ctx.last_traded = latest.get("timestamp", "")[:10]
                
            # Get historical bars availability
            bars_count = self._db["ib_historical_data"].count_documents({
                "symbol": symbol.upper()
            })
            ctx.recent_bars_available = bars_count
            
            # Calculate volume and volatility from recent bars
            recent_bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "close": 1, "volume": 1}
            ).sort("date", -1).limit(20))
            
            if len(recent_bars) >= 5:
                volumes = [b.get("volume", 0) for b in recent_bars if b.get("volume")]
                if volumes:
                    ctx.avg_volume_20d = sum(volumes) / len(volumes)
                    
                closes = [b.get("close", 0) for b in recent_bars if b.get("close")]
                if len(closes) >= 5:
                    # Calculate simple volatility (std of returns)
                    returns = [(closes[i] - closes[i+1]) / closes[i+1] 
                              for i in range(len(closes)-1) if closes[i+1] > 0]
                    if returns:
                        import statistics
                        ctx.volatility_20d = statistics.stdev(returns) if len(returns) > 1 else 0
                        
        except Exception as e:
            logger.warning(f"Error getting symbol context for {symbol}: {e}")
            
        return ctx
        
    def get_setup_type_context(self, setup_type: str, days: int = 90) -> SetupTypeContext:
        """
        Get historical context for a setup type.
        
        Returns win rate, average R, best/worst conditions.
        """
        if self._db is None:
            return SetupTypeContext(setup_type=setup_type)
            
        ctx = SetupTypeContext(setup_type=setup_type)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            # Get alert outcomes for this setup type
            alerts = list(self._db["alert_outcomes"].find({
                "setup_type": setup_type,
                "timestamp": {"$gte": cutoff.isoformat()}
            }))
            
            ctx.total_alerts = len(alerts)
            
            # Filter to traded alerts
            traded = [a for a in alerts if a.get("was_traded", False)]
            ctx.traded_count = len(traded)
            
            if traded:
                profitable = [a for a in traded if a.get("outcome") == "profitable" or a.get("pnl", 0) > 0]
                ctx.profitable_count = len(profitable)
                ctx.win_rate = len(profitable) / len(traded) if traded else 0
                
                r_multiples = [a.get("r_multiple", 0) for a in traded if a.get("r_multiple") is not None]
                if r_multiples:
                    ctx.avg_r_multiple = sum(r_multiples) / len(r_multiples)
                    
            # Analyze by regime
            regime_stats = {}
            for a in traded:
                regime = a.get("market_regime", "UNKNOWN")
                if regime not in regime_stats:
                    regime_stats[regime] = {"wins": 0, "total": 0}
                regime_stats[regime]["total"] += 1
                if a.get("outcome") == "profitable" or a.get("pnl", 0) > 0:
                    regime_stats[regime]["wins"] += 1
                    
            if regime_stats:
                # Find best and worst regimes
                regime_wr = {r: s["wins"]/s["total"] if s["total"] > 0 else 0 
                            for r, s in regime_stats.items()}
                if regime_wr:
                    ctx.best_regime = max(regime_wr, key=regime_wr.get)
                    ctx.worst_regime = min(regime_wr, key=regime_wr.get)
                    
            # Analyze by time of day
            time_stats = {"morning": 0, "midday": 0, "afternoon": 0, "morning_wins": 0, "midday_wins": 0, "afternoon_wins": 0}
            for a in traded:
                ts = a.get("timestamp", "")
                try:
                    hour = int(ts[11:13]) if len(ts) > 13 else 12
                    if hour < 11:
                        time_stats["morning"] += 1
                        if a.get("outcome") == "profitable":
                            time_stats["morning_wins"] += 1
                    elif hour < 14:
                        time_stats["midday"] += 1
                        if a.get("outcome") == "profitable":
                            time_stats["midday_wins"] += 1
                    else:
                        time_stats["afternoon"] += 1
                        if a.get("outcome") == "profitable":
                            time_stats["afternoon_wins"] += 1
                except (ValueError, IndexError, TypeError):
                    pass
                    
            # Find best time of day
            time_wr = {
                "morning": time_stats["morning_wins"]/time_stats["morning"] if time_stats["morning"] > 0 else 0,
                "midday": time_stats["midday_wins"]/time_stats["midday"] if time_stats["midday"] > 0 else 0,
                "afternoon": time_stats["afternoon_wins"]/time_stats["afternoon"] if time_stats["afternoon"] > 0 else 0
            }
            ctx.best_time_of_day = max(time_wr, key=time_wr.get) if time_wr else ""
            
            # Determine if sample size is adequate
            ctx.sample_size_adequate = ctx.traded_count >= 20
            
        except Exception as e:
            logger.warning(f"Error getting setup type context for {setup_type}: {e}")
            
        return ctx
        
    async def get_historical_bars(
        self,
        symbol: str,
        bar_size: str = "1 day",
        limit: int = 50
    ) -> List[Dict]:
        """
        Get recent historical bars for technical analysis.
        """
        if self._db is None:
            return []
            
        try:
            bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": bar_size},
                {"_id": 0}
            ).sort("date", -1).limit(limit))
            
            return bars
        except Exception as e:
            logger.warning(f"Error getting historical bars for {symbol}: {e}")
            return []
            
    def get_user_trading_stats(self, days: int = 90) -> Dict[str, Any]:
        """
        Get user's overall trading statistics.
        """
        if self._db is None:
            return {}
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            trades = list(self._db["trade_outcomes"].find({
                "timestamp": {"$gte": cutoff.isoformat()}
            }))
            
            if not trades:
                return {"total_trades": 0, "message": "No trades in period"}
                
            winners = [t for t in trades if t.get("pnl", 0) > 0]
            losers = [t for t in trades if t.get("pnl", 0) <= 0]
            
            r_multiples = [t.get("r_multiple", 0) for t in trades if t.get("r_multiple") is not None]
            
            # Stats by setup type
            setup_stats = {}
            for t in trades:
                st = t.get("setup_type", "unknown")
                if st not in setup_stats:
                    setup_stats[st] = {"wins": 0, "total": 0, "r_sum": 0}
                setup_stats[st]["total"] += 1
                if t.get("pnl", 0) > 0:
                    setup_stats[st]["wins"] += 1
                if t.get("r_multiple"):
                    setup_stats[st]["r_sum"] += t["r_multiple"]
                    
            best_setup = max(setup_stats.items(), 
                           key=lambda x: x[1]["wins"]/x[1]["total"] if x[1]["total"] > 5 else 0,
                           default=(None, {}))
            
            return {
                "total_trades": len(trades),
                "winning_trades": len(winners),
                "losing_trades": len(losers),
                "win_rate": len(winners) / len(trades) if trades else 0,
                "avg_r_multiple": sum(r_multiples) / len(r_multiples) if r_multiples else 0,
                "best_setup_type": best_setup[0],
                "best_setup_win_rate": best_setup[1].get("wins", 0) / best_setup[1].get("total", 1) if best_setup[1] else 0,
                "period_days": days
            }
            
        except Exception as e:
            logger.warning(f"Error getting user trading stats: {e}")
            return {}
            
    def build_agent_context(
        self,
        symbol: str,
        setup_type: str,
        direction: str = "long"
    ) -> Dict[str, Any]:
        """
        Build comprehensive context for AI agents.
        
        This is the main method agents should call to get all relevant context.
        """
        symbol_ctx = self.get_symbol_context(symbol)
        setup_ctx = self.get_setup_type_context(setup_type)
        user_stats = self.get_user_trading_stats()
        
        # Build actionable insights
        insights = []
        
        # Symbol-specific insight
        if symbol_ctx.total_trades >= 5:
            if symbol_ctx.win_rate >= 0.6:
                insights.append(f"You're {symbol_ctx.win_rate*100:.0f}% on {symbol} ({symbol_ctx.total_trades} trades)")
            elif symbol_ctx.win_rate <= 0.4:
                insights.append(f"Caution: Only {symbol_ctx.win_rate*100:.0f}% win rate on {symbol}")
                
        # Setup type insight
        if setup_ctx.sample_size_adequate:
            if setup_ctx.win_rate >= 0.55:
                insights.append(f"{setup_type} setups have {setup_ctx.win_rate*100:.0f}% win rate")
            elif setup_ctx.win_rate <= 0.45:
                insights.append(f"Warning: {setup_type} setups only {setup_ctx.win_rate*100:.0f}% win rate")
                
            if setup_ctx.avg_r_multiple >= 1.5:
                insights.append(f"Average {setup_ctx.avg_r_multiple:.1f}R on {setup_type} setups")
                
        # Regime insight
        if setup_ctx.best_regime:
            insights.append(f"Best regime for {setup_type}: {setup_ctx.best_regime}")
            
        return {
            "symbol_context": symbol_ctx.to_dict(),
            "setup_context": setup_ctx.to_dict(),
            "user_stats": user_stats,
            "insights": insights,
            "has_sufficient_data": symbol_ctx.recent_bars_available > 20 or symbol_ctx.total_trades > 0
        }


# Singleton
_agent_data_service: Optional[AgentDataService] = None


def get_agent_data_service() -> AgentDataService:
    """Get singleton instance"""
    global _agent_data_service
    if _agent_data_service is None:
        _agent_data_service = AgentDataService()
    return _agent_data_service


def init_agent_data_service(db=None) -> AgentDataService:
    """Initialize with database"""
    service = get_agent_data_service()
    if db is not None:
        service.set_db(db)
    return service
