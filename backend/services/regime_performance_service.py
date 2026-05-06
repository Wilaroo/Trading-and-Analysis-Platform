"""
Regime Performance Tracking Service
====================================
Tracks strategy performance by market regime to identify:
- Which strategies work best in each regime
- How position sizing adjustments affect performance
- Optimal strategy selection based on current regime

Data stored in MongoDB for historical analysis.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class RegimePerformanceRecord:
    """Performance record for a strategy in a specific regime"""
    strategy_name: str
    market_regime: str  # RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
    
    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    
    # P&L
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    
    # Metrics
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    avg_r_multiple: float = 0.0
    
    # Position sizing analysis
    avg_position_multiplier: float = 1.0  # Average regime multiplier used
    trades_with_reduced_size: int = 0     # Trades where size was reduced due to regime
    
    # Timing
    last_updated: str = ""
    period_start: str = ""
    period_end: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class RegimePerformanceService:
    """
    Tracks and analyzes strategy performance segmented by market regime.
    
    Helps answer questions like:
    - "Which strategies work best in CONFIRMED_DOWN markets?"
    - "Should I reduce longs in RISK_OFF or just use different strategies?"
    - "How much has regime-aware position sizing saved me in drawdowns?"
    """
    
    def __init__(self):
        self._db = None
        self._performance_collection = None
        self._trade_log_collection = None
        
        # Cache for quick lookups
        self._performance_cache: Dict[str, Dict[str, RegimePerformanceRecord]] = {}
        self._cache_last_updated: Optional[datetime] = None
        self._cache_ttl = 300  # 5 minutes
        
    def set_db(self, db):
        """Set MongoDB connection"""
        self._db = db
        if db is not None:
            self._performance_collection = db['regime_performance']
            self._trade_log_collection = db['regime_trade_log']
            
            # Create indexes
            self._performance_collection.create_index([
                ("strategy_name", 1),
                ("market_regime", 1)
            ], unique=True)
            self._trade_log_collection.create_index([("trade_id", 1)])
            self._trade_log_collection.create_index([("market_regime", 1)])
            self._trade_log_collection.create_index([("strategy_name", 1)])
            self._trade_log_collection.create_index([("closed_at", -1)])
            
            logger.info("RegimePerformanceService: MongoDB connected")
    
    async def log_trade(self, trade: Dict[str, Any]):
        """
        Log a closed trade for regime performance tracking.
        Should be called when a trade is closed.
        
        Args:
            trade: Trade dictionary with at least:
                - trade_id or id
                - setup_type (strategy name)
                - market_regime
                - direction (LONG/SHORT)
                - realized_pnl
                - shares
                - entry_price
                - exit_price
                - regime_position_multiplier
        """
        if self._trade_log_collection is None:
            logger.warning("Cannot log trade: database not connected")
            return
        
        try:
            trade_id = trade.get("trade_id") or trade.get("id", "unknown")
            strategy_name = trade.get("setup_type", "unknown")
            market_regime = trade.get("market_regime", "UNKNOWN")
            direction = trade.get("direction", "LONG")
            pnl = float(trade.get("realized_pnl", 0))
            
            # Store trade log
            trade_log = {
                "trade_id": trade_id,
                "strategy_name": strategy_name,
                "market_regime": market_regime,
                "direction": direction.upper() if isinstance(direction, str) else direction,
                "pnl": pnl,
                "is_winner": pnl > 0,
                "shares": trade.get("shares", 0),
                "entry_price": trade.get("entry_price", 0),
                "exit_price": trade.get("exit_price", 0),
                "regime_score": trade.get("regime_score", 50.0),
                "regime_position_multiplier": trade.get("regime_position_multiplier", 1.0),
                "risk_amount": trade.get("risk_amount", 0),
                "r_multiple": self._calculate_r_multiple(trade),
                "closed_at": trade.get("closed_at") or datetime.now(timezone.utc).isoformat(),
                "logged_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Upsert to avoid duplicates
            self._trade_log_collection.update_one(
                {"trade_id": trade_id},
                {"$set": trade_log},
                upsert=True
            )
            
            # Update performance aggregates
            await self._update_performance_aggregate(strategy_name, market_regime)
            
            logger.debug(f"Logged trade {trade_id}: {strategy_name} in {market_regime} regime, P&L: ${pnl:.2f}")
            
        except Exception as e:
            logger.error(f"Error logging trade for regime performance: {e}")
    
    def _calculate_r_multiple(self, trade: Dict) -> float:
        """Calculate the R-multiple for a trade"""
        risk_amount = trade.get("risk_amount", 0)
        pnl = trade.get("realized_pnl", 0)
        
        if risk_amount and risk_amount > 0:
            return pnl / risk_amount
        return 0.0
    
    async def _update_performance_aggregate(self, strategy_name: str, market_regime: str):
        """Update aggregate performance for a strategy/regime combination"""
        if self._trade_log_collection is None or self._performance_collection is None:
            return
        
        try:
            # Aggregate all trades for this strategy/regime
            pipeline = [
                {"$match": {"strategy_name": strategy_name, "market_regime": market_regime}},
                {"$group": {
                    "_id": {"strategy": "$strategy_name", "regime": "$market_regime"},
                    "total_trades": {"$sum": 1},
                    "winning_trades": {"$sum": {"$cond": ["$is_winner", 1, 0]}},
                    "losing_trades": {"$sum": {"$cond": ["$is_winner", 0, 1]}},
                    "long_trades": {"$sum": {"$cond": [{"$eq": ["$direction", "LONG"]}, 1, 0]}},
                    "short_trades": {"$sum": {"$cond": [{"$eq": ["$direction", "SHORT"]}, 1, 0]}},
                    "total_pnl": {"$sum": "$pnl"},
                    "gross_profit": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
                    "gross_loss": {"$sum": {"$cond": [{"$lt": ["$pnl", 0]}, {"$abs": "$pnl"}, 0]}},
                    "avg_r_multiple": {"$avg": "$r_multiple"},
                    "avg_position_multiplier": {"$avg": "$regime_position_multiplier"},
                    "trades_with_reduced_size": {"$sum": {"$cond": [{"$lt": ["$regime_position_multiplier", 1]}, 1, 0]}},
                    "first_trade": {"$min": "$closed_at"},
                    "last_trade": {"$max": "$closed_at"}
                }}
            ]
            
            results = list(self._trade_log_collection.aggregate(pipeline))
            
            if not results:
                return
            
            agg = results[0]
            total = agg["total_trades"]
            winners = agg["winning_trades"]
            losers = agg["losing_trades"]
            gross_profit = agg["gross_profit"]
            gross_loss = agg["gross_loss"]
            
            win_rate = (winners / total * 100) if total > 0 else 0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
            avg_win = (gross_profit / winners) if winners > 0 else 0
            avg_loss = (gross_loss / losers) if losers > 0 else 0
            expectancy = ((win_rate/100) * avg_win) - ((1 - win_rate/100) * avg_loss)
            
            # Store updated performance
            performance = {
                "strategy_name": strategy_name,
                "market_regime": market_regime,
                "total_trades": total,
                "winning_trades": winners,
                "losing_trades": losers,
                "long_trades": agg["long_trades"],
                "short_trades": agg["short_trades"],
                "total_pnl": round(agg["total_pnl"], 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
                "win_rate": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "expectancy": round(expectancy, 2),
                "avg_r_multiple": round(agg["avg_r_multiple"] or 0, 2),
                "avg_position_multiplier": round(agg["avg_position_multiplier"] or 1, 2),
                "trades_with_reduced_size": agg["trades_with_reduced_size"],
                "period_start": agg["first_trade"],
                "period_end": agg["last_trade"],
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            self._performance_collection.update_one(
                {"strategy_name": strategy_name, "market_regime": market_regime},
                {"$set": performance},
                upsert=True
            )
            
        except Exception as e:
            logger.error(f"Error updating performance aggregate: {e}")
    
    async def get_strategy_regime_performance(
        self,
        strategy_name: str = None,
        market_regime: str = None
    ) -> List[Dict]:
        """
        Get performance data for strategies by regime.
        
        Args:
            strategy_name: Filter by strategy (None = all)
            market_regime: Filter by regime (None = all)
            
        Returns:
            List of performance records
        """
        if self._performance_collection is None:
            return []
        
        query = {}
        if strategy_name:
            query["strategy_name"] = strategy_name
        if market_regime:
            query["market_regime"] = market_regime
        
        results = list(self._performance_collection.find(query, {"_id": 0}))
        return results
    
    async def get_best_strategies_for_regime(
        self,
        market_regime: str,
        min_trades: int = 5,
        sort_by: str = "expectancy"
    ) -> List[Dict]:
        """
        Get the best performing strategies for a specific regime.
        
        Args:
            market_regime: The regime to analyze
            min_trades: Minimum trades required for inclusion
            sort_by: Sort field (expectancy, win_rate, profit_factor, total_pnl)
            
        Returns:
            List of strategies sorted by performance
        """
        if self._performance_collection is None:
            return []
        
        query = {
            "market_regime": market_regime,
            "total_trades": {"$gte": min_trades}
        }
        
        results = list(
            self._performance_collection.find(query, {"_id": 0})
            .sort(sort_by, -1)
            .limit(20)
        )
        
        return results
    
    async def get_regime_summary(self) -> Dict[str, Any]:
        """
        Get overall performance summary grouped by regime.
        
        Returns:
            Summary with aggregate stats per regime
        """
        if self._trade_log_collection is None:
            return {"regimes": {}}
        
        pipeline = [
            {"$group": {
                "_id": "$market_regime",
                "total_trades": {"$sum": 1},
                "winning_trades": {"$sum": {"$cond": ["$is_winner", 1, 0]}},
                "total_pnl": {"$sum": "$pnl"},
                "avg_r_multiple": {"$avg": "$r_multiple"},
                "unique_strategies": {"$addToSet": "$strategy_name"}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self._trade_log_collection.aggregate(pipeline))
        
        regimes = {}
        for r in results:
            regime = r["_id"] or "UNKNOWN"
            total = r["total_trades"]
            winners = r["winning_trades"]
            
            regimes[regime] = {
                "total_trades": total,
                "winning_trades": winners,
                "win_rate": round((winners / total * 100) if total > 0 else 0, 1),
                "total_pnl": round(r["total_pnl"], 2),
                "avg_r_multiple": round(r["avg_r_multiple"] or 0, 2),
                "strategies_used": len(r["unique_strategies"])
            }
        
        return {
            "regimes": regimes,
            "total_trades": sum(r["total_trades"] for r in regimes.values()),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_position_sizing_impact(self) -> Dict[str, Any]:
        """
        Analyze the impact of regime-based position sizing.
        
        Returns:
            Analysis of how position sizing adjustments affected P&L
        """
        if self._trade_log_collection is None:
            return {}
        
        pipeline = [
            {"$group": {
                "_id": {"$cond": [{"$lt": ["$regime_position_multiplier", 1]}, "reduced", "full"]},
                "total_trades": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "avg_pnl": {"$avg": "$pnl"},
                "winning_trades": {"$sum": {"$cond": ["$is_winner", 1, 0]}},
                "avg_multiplier": {"$avg": "$regime_position_multiplier"}
            }}
        ]
        
        results = list(self._trade_log_collection.aggregate(pipeline))
        
        analysis = {
            "full_size_trades": {},
            "reduced_size_trades": {},
            "impact_summary": ""
        }
        
        for r in results:
            category = r["_id"]
            total = r["total_trades"]
            winners = r["winning_trades"]
            
            data = {
                "total_trades": total,
                "total_pnl": round(r["total_pnl"], 2),
                "avg_pnl_per_trade": round(r["avg_pnl"] or 0, 2),
                "win_rate": round((winners / total * 100) if total > 0 else 0, 1),
                "avg_position_multiplier": round(r["avg_multiplier"] or 1, 2)
            }
            
            if category == "reduced":
                analysis["reduced_size_trades"] = data
            else:
                analysis["full_size_trades"] = data
        
        # Calculate impact
        reduced = analysis.get("reduced_size_trades", {})
        full = analysis.get("full_size_trades", {})
        
        if reduced and reduced.get("total_trades", 0) > 0:
            reduced_pnl = reduced.get("total_pnl", 0)
            # Estimate what P&L would have been at full size
            avg_mult = reduced.get("avg_position_multiplier", 0.5)
            estimated_full_pnl = reduced_pnl / avg_mult if avg_mult > 0 else 0
            savings = estimated_full_pnl - reduced_pnl
            
            if savings > 0:
                analysis["impact_summary"] = f"Regime-based sizing saved ${savings:,.2f} by reducing position sizes on losing trades"
            else:
                analysis["impact_summary"] = f"Regime-based sizing reduced profits by ${abs(savings):,.2f} (conservative sizing on winners)"
        
        analysis["generated_at"] = datetime.now(timezone.utc).isoformat()
        return analysis


# Singleton instance
_regime_performance_service: Optional[RegimePerformanceService] = None


def get_regime_performance_service() -> RegimePerformanceService:
    """Get singleton instance"""
    global _regime_performance_service
    if _regime_performance_service is None:
        _regime_performance_service = RegimePerformanceService()
    return _regime_performance_service


def init_regime_performance_service(db=None) -> RegimePerformanceService:
    """Initialize the service with dependencies"""
    service = get_regime_performance_service()
    if db is not None:
        service.set_db(db)
    return service
