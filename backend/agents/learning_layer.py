"""
Learning Layer - Tracks trading outcomes for personalized coaching
Provides TradeOutcomesDB, PerformanceAnalyzer, and MistakeTracker
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pymongo import MongoClient
from pymongo.database import Database
from bson import ObjectId

logger = logging.getLogger(__name__)


@dataclass
class TradeOutcome:
    """Represents a completed trade outcome"""
    symbol: str
    action: str  # BUY, SELL
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_percent: float
    hold_time_minutes: int
    setup_type: str  # e.g., "vwap_pullback", "breakout"
    entry_time: datetime
    exit_time: datetime
    market_conditions: Dict = None
    notes: str = ""
    outcome: str = ""  # "win", "loss", "breakeven"
    r_multiple: float = 0  # Risk/reward achieved


@dataclass
class TradingMistake:
    """Tracks common trading mistakes for learning"""
    timestamp: datetime
    symbol: str
    mistake_type: str  # "early_exit", "oversized", "revenge_trade", etc.
    description: str
    pnl_impact: float
    setup_type: str
    could_have_been: float  # What the PnL would have been with better execution


class TradeOutcomesDB:
    """
    Persistent storage for trade outcomes.
    Used by Coach agent to provide personalized advice based on history.
    """
    
    COLLECTION = "trade_outcomes"
    
    def __init__(self, db: Database = None):
        self._db = db
        self._collection = None
        if db is not None:
            self._collection = db[self.COLLECTION]
    
    def set_db(self, db: Database):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._collection = db[self.COLLECTION]
    
    def record_trade(self, outcome: TradeOutcome) -> str:
        """Record a completed trade outcome"""
        if self._collection is None:
            logger.warning("No database connection - trade not recorded")
            return None
        
        doc = asdict(outcome)
        doc["created_at"] = datetime.now(timezone.utc)
        
        result = self._collection.insert_one(doc)
        logger.info(f"Recorded trade outcome: {outcome.symbol} {outcome.outcome} ${outcome.pnl:.2f}")
        return str(result.inserted_id)
    
    def get_recent_trades(self, days: int = 30, symbol: str = None, 
                         setup_type: str = None) -> List[Dict]:
        """Get recent trade outcomes"""
        if self._collection is None:
            return []
        
        query = {
            "exit_time": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}
        }
        if symbol:
            query["symbol"] = symbol.upper()
        if setup_type:
            query["setup_type"] = setup_type
        
        trades = list(self._collection.find(query, {"_id": 0}).sort("exit_time", -1).limit(100))
        return trades
    
    def get_trades_by_setup(self, setup_type: str) -> List[Dict]:
        """Get all trades for a specific setup type"""
        if self._collection is None:
            return []
        
        trades = list(self._collection.find(
            {"setup_type": setup_type}, {"_id": 0}
        ).sort("exit_time", -1).limit(50))
        return trades
    
    def get_summary_stats(self) -> Dict:
        """Get summary statistics across all trades"""
        if self._collection is None:
            return {}
        
        # Aggregate stats
        pipeline = [
            {"$group": {
                "_id": None,
                "total_trades": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "avg_pnl": {"$avg": "$pnl"},
                "avg_r": {"$avg": "$r_multiple"},
                "wins": {"$sum": {"$cond": [{"$eq": ["$outcome", "win"]}, 1, 0]}},
                "losses": {"$sum": {"$cond": [{"$eq": ["$outcome", "loss"]}, 1, 0]}},
                "avg_hold_time": {"$avg": "$hold_time_minutes"}
            }}
        ]
        
        result = list(self._collection.aggregate(pipeline))
        if result:
            stats = result[0]
            del stats["_id"]
            if stats["total_trades"] > 0:
                stats["win_rate"] = stats["wins"] / stats["total_trades"] * 100
            else:
                stats["win_rate"] = 0
            return stats
        return {}


class PerformanceAnalyzer:
    """
    Analyzes trading performance patterns.
    Identifies strengths, weaknesses, and improvement opportunities.
    """
    
    def __init__(self, outcomes_db: TradeOutcomesDB):
        self.outcomes_db = outcomes_db
    
    def analyze_by_setup(self) -> Dict[str, Dict]:
        """Analyze performance by setup type"""
        if self.outcomes_db._collection is None:
            return {}
        
        pipeline = [
            {"$group": {
                "_id": "$setup_type",
                "count": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "avg_pnl": {"$avg": "$pnl"},
                "avg_r": {"$avg": "$r_multiple"},
                "wins": {"$sum": {"$cond": [{"$eq": ["$outcome", "win"]}, 1, 0]}},
                "losses": {"$sum": {"$cond": [{"$eq": ["$outcome", "loss"]}, 1, 0]}}
            }},
            {"$sort": {"total_pnl": -1}}
        ]
        
        result = list(self.outcomes_db._collection.aggregate(pipeline))
        
        by_setup = {}
        for r in result:
            setup = r["_id"] or "unknown"
            by_setup[setup] = {
                "trades": r["count"],
                "total_pnl": r["total_pnl"],
                "avg_pnl": r["avg_pnl"],
                "avg_r": r["avg_r"],
                "win_rate": (r["wins"] / r["count"] * 100) if r["count"] > 0 else 0,
                "grade": self._grade_setup(r)
            }
        
        return by_setup
    
    def analyze_by_time(self) -> Dict[str, Dict]:
        """Analyze performance by time of day"""
        if self.outcomes_db._collection is None:
            return {}
        
        pipeline = [
            {"$addFields": {
                "hour": {"$hour": "$entry_time"}
            }},
            {"$group": {
                "_id": "$hour",
                "count": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "win_rate": {"$avg": {"$cond": [{"$eq": ["$outcome", "win"]}, 100, 0]}}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(self.outcomes_db._collection.aggregate(pipeline))
        
        by_hour = {}
        for r in result:
            hour = r["_id"]
            if hour is not None:
                period = self._get_trading_period(hour)
                if period not in by_hour:
                    by_hour[period] = {"trades": 0, "total_pnl": 0, "hours": []}
                by_hour[period]["trades"] += r["count"]
                by_hour[period]["total_pnl"] += r["total_pnl"]
                by_hour[period]["hours"].append(hour)
        
        return by_hour
    
    def get_best_setups(self, min_trades: int = 5) -> List[Dict]:
        """Get the trader's best performing setups"""
        by_setup = self.analyze_by_setup()
        
        best = []
        for setup, stats in by_setup.items():
            if stats["trades"] >= min_trades and stats["win_rate"] >= 50:
                best.append({
                    "setup": setup,
                    **stats
                })
        
        return sorted(best, key=lambda x: x["total_pnl"], reverse=True)[:5]
    
    def get_worst_setups(self, min_trades: int = 3) -> List[Dict]:
        """Get the trader's worst performing setups"""
        by_setup = self.analyze_by_setup()
        
        worst = []
        for setup, stats in by_setup.items():
            if stats["trades"] >= min_trades and stats["win_rate"] < 40:
                worst.append({
                    "setup": setup,
                    **stats
                })
        
        return sorted(worst, key=lambda x: x["total_pnl"])[:5]
    
    def get_improvement_suggestions(self) -> List[str]:
        """Generate specific improvement suggestions based on data"""
        suggestions = []
        
        # Analyze data for suggestions
        by_time = self.analyze_by_time()
        
        # Check for underperforming setups
        worst = self.get_worst_setups()
        if worst:
            for w in worst[:2]:
                if w["win_rate"] < 40:
                    suggestions.append(
                        f"Consider reducing size or avoiding '{w['setup']}' setups "
                        f"(win rate: {w['win_rate']:.0f}%, total P&L: ${w['total_pnl']:.2f})"
                    )
        
        # Check for time-based patterns
        for period, stats in by_time.items():
            if stats["trades"] >= 5 and stats["total_pnl"] < -500:
                suggestions.append(
                    f"Your {period} trading has been unprofitable "
                    f"(${stats['total_pnl']:.2f} over {stats['trades']} trades). "
                    "Consider being more selective during this time."
                )
        
        # Check for best setups
        best = self.get_best_setups()
        if best:
            suggestions.append(
                f"Your best setup is '{best[0]['setup']}' with {best[0]['win_rate']:.0f}% win rate. "
                "Consider increasing size on these setups."
            )
        
        return suggestions
    
    def _grade_setup(self, stats: Dict) -> str:
        """Grade a setup based on performance"""
        win_rate = (stats["wins"] / stats["count"] * 100) if stats["count"] > 0 else 0
        avg_r = stats.get("avg_r", 0) or 0
        
        if win_rate >= 60 and avg_r >= 1.5:
            return "A+"
        elif win_rate >= 55 and avg_r >= 1.0:
            return "A"
        elif win_rate >= 50 and avg_r >= 0.8:
            return "B"
        elif win_rate >= 45:
            return "C"
        else:
            return "D"
    
    def _get_trading_period(self, hour: int) -> str:
        """Map hour to trading period"""
        if hour < 10:
            return "opening"
        elif hour < 12:
            return "morning"
        elif hour < 14:
            return "midday"
        else:
            return "afternoon"


class MistakeTracker:
    """
    Tracks and categorizes trading mistakes.
    Helps Coach agent identify patterns for improvement.
    """
    
    COLLECTION = "trading_mistakes"
    
    MISTAKE_TYPES = {
        "early_exit": "Exited a winning trade too early",
        "late_exit": "Held a losing trade too long",
        "oversized": "Position size was too large for the setup",
        "undersized": "Position size was too small (fear-based)",
        "revenge_trade": "Traded emotionally after a loss",
        "fomo": "Entered due to fear of missing out",
        "no_plan": "Traded without a clear plan or levels",
        "ignored_stop": "Moved or ignored stop loss",
        "overtrading": "Too many trades in a session",
        "chasing": "Chased entry after missing initial setup"
    }
    
    def __init__(self, db: Database = None):
        self._db = db
        self._collection = None
        if db is not None:
            self._collection = db[self.COLLECTION]
    
    def set_db(self, db: Database):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._collection = db[self.COLLECTION]
    
    def record_mistake(self, mistake: TradingMistake) -> str:
        """Record a trading mistake"""
        if self._collection is None:
            logger.warning("No database connection - mistake not recorded")
            return None
        
        doc = asdict(mistake)
        doc["created_at"] = datetime.now(timezone.utc)
        
        result = self._collection.insert_one(doc)
        logger.info(f"Recorded mistake: {mistake.mistake_type} on {mistake.symbol}")
        return str(result.inserted_id)
    
    def get_recent_mistakes(self, days: int = 30) -> List[Dict]:
        """Get recent mistakes"""
        if self._collection is None:
            return []
        
        query = {
            "timestamp": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}
        }
        
        mistakes = list(self._collection.find(query, {"_id": 0}).sort("timestamp", -1).limit(50))
        return mistakes
    
    def get_mistake_patterns(self) -> Dict[str, int]:
        """Analyze mistake patterns"""
        if self._collection is None:
            return {}
        
        pipeline = [
            {"$group": {
                "_id": "$mistake_type",
                "count": {"$sum": 1},
                "total_impact": {"$sum": "$pnl_impact"}
            }},
            {"$sort": {"count": -1}}
        ]
        
        result = list(self._collection.aggregate(pipeline))
        
        patterns = {}
        for r in result:
            mistake_type = r["_id"]
            patterns[mistake_type] = {
                "count": r["count"],
                "total_impact": r["total_impact"],
                "description": self.MISTAKE_TYPES.get(mistake_type, mistake_type)
            }
        
        return patterns
    
    def get_coaching_focus(self) -> List[str]:
        """Identify top areas to focus coaching on"""
        patterns = self.get_mistake_patterns()
        
        # Sort by count and impact
        sorted_mistakes = sorted(
            patterns.items(),
            key=lambda x: (x[1]["count"], abs(x[1]["total_impact"])),
            reverse=True
        )
        
        focus_areas = []
        for mistake_type, data in sorted_mistakes[:3]:
            focus_areas.append(
                f"**{mistake_type.replace('_', ' ').title()}** ({data['count']} occurrences, "
                f"${data['total_impact']:.2f} impact): {data['description']}"
            )
        
        return focus_areas


# Singleton instances
_outcomes_db: Optional[TradeOutcomesDB] = None
_performance_analyzer: Optional[PerformanceAnalyzer] = None
_mistake_tracker: Optional[MistakeTracker] = None


def get_outcomes_db() -> TradeOutcomesDB:
    """Get the global outcomes database instance"""
    global _outcomes_db
    if _outcomes_db is None:
        _outcomes_db = TradeOutcomesDB()
    return _outcomes_db


def get_performance_analyzer() -> PerformanceAnalyzer:
    """Get the global performance analyzer instance"""
    global _performance_analyzer
    if _performance_analyzer is None:
        _performance_analyzer = PerformanceAnalyzer(get_outcomes_db())
    return _performance_analyzer


def get_mistake_tracker() -> MistakeTracker:
    """Get the global mistake tracker instance"""
    global _mistake_tracker
    if _mistake_tracker is None:
        _mistake_tracker = MistakeTracker()
    return _mistake_tracker


def init_learning_layer(db: Database):
    """Initialize all learning layer components with database"""
    global _outcomes_db, _performance_analyzer, _mistake_tracker
    
    _outcomes_db = TradeOutcomesDB(db)
    _performance_analyzer = PerformanceAnalyzer(_outcomes_db)
    _mistake_tracker = MistakeTracker(db)
    
    logger.info("Learning layer initialized")
    return {
        "outcomes_db": _outcomes_db,
        "performance_analyzer": _performance_analyzer,
        "mistake_tracker": _mistake_tracker
    }
