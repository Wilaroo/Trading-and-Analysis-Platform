"""
Context Performance Service - Phase 5 Medium Learning

Generates detailed performance reports by context combinations.
Tracks win rates across setup + regime + time combinations.

Features:
- Multi-dimensional performance tracking
- Heat map generation for context combinations
- Best/worst context identification
- Performance trend analysis
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class ContextPerformance:
    """Performance metrics for a specific context"""
    context_key: str = ""
    setup_type: str = ""
    market_regime: str = ""
    time_of_day: str = ""
    day_of_week: str = ""
    vix_level: str = ""  # low, medium, high
    
    # Core metrics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    win_rate: float = 0.0
    
    # P&L metrics
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    
    # R metrics
    total_r: float = 0.0
    avg_r: float = 0.0
    expected_value_r: float = 0.0
    
    # Trend metrics
    recent_win_rate: float = 0.0  # Last 10 trades
    win_rate_trend: str = "stable"  # improving, declining, stable
    
    # Sample quality
    confidence: str = "low"  # low, medium, high
    last_trade_date: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ContextPerformance":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PerformanceReport:
    """Complete performance report"""
    report_date: str = ""
    report_type: str = "daily"  # daily, weekly, monthly
    
    # Summary
    total_trades: int = 0
    overall_win_rate: float = 0.0
    total_pnl: float = 0.0
    total_r: float = 0.0
    
    # Top performers
    best_contexts: List[Dict] = field(default_factory=list)
    worst_contexts: List[Dict] = field(default_factory=list)
    
    # Recommendations
    contexts_to_focus: List[str] = field(default_factory=list)
    contexts_to_avoid: List[str] = field(default_factory=list)
    
    # Detail breakdowns
    by_setup: List[Dict] = field(default_factory=list)
    by_regime: List[Dict] = field(default_factory=list)
    by_time: List[Dict] = field(default_factory=list)
    by_day: List[Dict] = field(default_factory=list)
    
    # Heat map data (setup x regime matrix)
    heat_map: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ContextPerformanceService:
    """
    Tracks and analyzes performance by context dimensions.
    
    Dimensions tracked:
    - Setup type (bull_flag, vwap_bounce, etc.)
    - Market regime (uptrend, choppy, etc.)
    - Time of day (opening, morning, afternoon, close)
    - Day of week
    - VIX level
    """
    
    def __init__(self):
        self._db = None
        self._context_performance_col = None
        self._trade_outcomes_col = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._context_performance_col = db['context_performance']
            self._trade_outcomes_col = db['trade_outcomes']
            
    async def update_context_performance(
        self,
        trades: List[Dict]
    ) -> int:
        """
        Update context performance stats from trade outcomes.
        Returns number of contexts updated.
        """
        if not trades or self._context_performance_col is None:
            return 0
            
        # Group trades by context key
        context_groups: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            key = self._generate_context_key(trade)
            if key not in context_groups:
                context_groups[key] = []
            context_groups[key].append(trade)
            
        updated = 0
        
        for context_key, trade_list in context_groups.items():
            try:
                perf = await self._calculate_context_performance(context_key, trade_list)
                
                # Upsert to database
                self._context_performance_col.update_one(
                    {"context_key": context_key},
                    {"$set": perf.to_dict()},
                    upsert=True
                )
                updated += 1
                
            except Exception as e:
                logger.error(f"Error updating context {context_key}: {e}")
                
        return updated
        
    def _generate_context_key(self, trade: Dict) -> str:
        """Generate a unique key for a context combination"""
        context = trade.get("context", {})
        
        parts = [
            trade.get("setup_type", "unknown"),
            context.get("market_regime", "unknown"),
            context.get("time_of_day", "unknown")
        ]
        
        return ":".join(parts)
        
    async def _calculate_context_performance(
        self,
        context_key: str,
        trades: List[Dict]
    ) -> ContextPerformance:
        """Calculate performance metrics for a context"""
        perf = ContextPerformance(context_key=context_key)
        
        if not trades:
            return perf
            
        # Parse context key
        parts = context_key.split(":")
        perf.setup_type = parts[0] if len(parts) > 0 else ""
        perf.market_regime = parts[1] if len(parts) > 1 else ""
        perf.time_of_day = parts[2] if len(parts) > 2 else ""
        
        # Calculate core metrics
        perf.total_trades = len(trades)
        perf.wins = sum(1 for t in trades if t.get("outcome") == "won")
        perf.losses = sum(1 for t in trades if t.get("outcome") == "lost")
        perf.scratches = sum(1 for t in trades if t.get("outcome") == "scratch")
        
        if perf.total_trades > 0:
            perf.win_rate = perf.wins / (perf.wins + perf.losses) if (perf.wins + perf.losses) > 0 else 0
            
        # P&L metrics
        pnls = [t.get("pnl", 0) for t in trades]
        perf.total_pnl = sum(pnls)
        perf.avg_pnl = perf.total_pnl / len(pnls) if pnls else 0
        
        wins_pnl = [p for p in pnls if p > 0]
        losses_pnl = [p for p in pnls if p < 0]
        
        perf.avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        perf.avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
        
        gross_profit = sum(wins_pnl) if wins_pnl else 0
        gross_loss = abs(sum(losses_pnl)) if losses_pnl else 0
        perf.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # R metrics
        rs = [t.get("actual_r", 0) for t in trades]
        perf.total_r = sum(rs)
        perf.avg_r = perf.total_r / len(rs) if rs else 0
        
        # Expected Value calculation
        if perf.win_rate > 0 and perf.avg_win > 0 and perf.avg_loss > 0:
            perf.expected_value_r = (perf.win_rate * perf.avg_win) - ((1 - perf.win_rate) * perf.avg_loss)
        
        # Recent performance (last 10)
        sorted_trades = sorted(trades, key=lambda t: t.get("created_at", ""), reverse=True)
        recent = sorted_trades[:10]
        if recent:
            recent_wins = sum(1 for t in recent if t.get("outcome") == "won")
            recent_total = sum(1 for t in recent if t.get("outcome") in ["won", "lost"])
            perf.recent_win_rate = recent_wins / recent_total if recent_total > 0 else 0
            
            # Determine trend
            if perf.recent_win_rate > perf.win_rate + 0.1:
                perf.win_rate_trend = "improving"
            elif perf.recent_win_rate < perf.win_rate - 0.1:
                perf.win_rate_trend = "declining"
            else:
                perf.win_rate_trend = "stable"
                
        # Confidence level
        if perf.total_trades >= 30:
            perf.confidence = "high"
        elif perf.total_trades >= 10:
            perf.confidence = "medium"
        else:
            perf.confidence = "low"
            
        # Last trade
        if sorted_trades:
            perf.last_trade_date = sorted_trades[0].get("created_at", "")
            
        return perf
        
    async def generate_performance_report(
        self,
        report_type: str = "daily",
        lookback_days: int = None
    ) -> PerformanceReport:
        """
        Generate a comprehensive performance report.
        
        Args:
            report_type: "daily", "weekly", or "monthly"
            lookback_days: Override default lookback
        """
        report = PerformanceReport(
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            report_type=report_type
        )
        
        if self._trade_outcomes_col is None:
            return report
            
        # Determine lookback
        if lookback_days is None:
            lookback_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(report_type, 7)
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        
        trades = list(self._trade_outcomes_col.find({
            "created_at": {"$gte": cutoff.isoformat()}
        }))
        
        if not trades:
            return report
            
        # Summary stats
        report.total_trades = len(trades)
        wins = sum(1 for t in trades if t.get("outcome") == "won")
        losses = sum(1 for t in trades if t.get("outcome") == "lost")
        report.overall_win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
        report.total_pnl = sum(t.get("pnl", 0) for t in trades)
        report.total_r = sum(t.get("actual_r", 0) for t in trades)
        
        # Performance by setup
        report.by_setup = await self._aggregate_by_dimension(trades, "setup_type")
        
        # Performance by regime
        report.by_regime = await self._aggregate_by_dimension(trades, "context.market_regime")
        
        # Performance by time
        report.by_time = await self._aggregate_by_dimension(trades, "context.time_of_day")
        
        # Performance by day
        report.by_day = await self._aggregate_by_dimension(trades, "day_of_week")
        
        # Find best and worst contexts
        all_contexts = await self.get_all_performances()
        
        # Filter to those with enough trades
        qualified = [c for c in all_contexts if c.total_trades >= 5]
        
        # Best (by profit factor and win rate combo)
        best = sorted(
            qualified,
            key=lambda c: c.win_rate * c.profit_factor if c.profit_factor > 0 else c.win_rate,
            reverse=True
        )[:5]
        
        report.best_contexts = [c.to_dict() for c in best]
        
        # Worst
        worst = sorted(
            qualified,
            key=lambda c: c.win_rate * (c.profit_factor if c.profit_factor > 0 else 0.5)
        )[:5]
        
        report.worst_contexts = [c.to_dict() for c in worst]
        
        # Recommendations
        for ctx in best[:3]:
            if ctx.win_rate > 0.55 and ctx.profit_factor > 1.2:
                report.contexts_to_focus.append(
                    f"{ctx.setup_type} in {ctx.market_regime} during {ctx.time_of_day}"
                )
                
        for ctx in worst[:3]:
            if ctx.win_rate < 0.40 or ctx.profit_factor < 0.8:
                report.contexts_to_avoid.append(
                    f"{ctx.setup_type} in {ctx.market_regime} during {ctx.time_of_day}"
                )
                
        # Generate heat map (setup x regime)
        report.heat_map = await self._generate_heat_map(trades)
        
        return report
        
    async def _aggregate_by_dimension(
        self,
        trades: List[Dict],
        dimension: str
    ) -> List[Dict]:
        """Aggregate performance by a single dimension"""
        groups: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            # Handle nested dimensions like "context.market_regime"
            if "." in dimension:
                parts = dimension.split(".")
                value = trade
                for p in parts:
                    value = value.get(p, {}) if isinstance(value, dict) else "unknown"
            else:
                value = trade.get(dimension, "unknown")
                
            if value not in groups:
                groups[value] = []
            groups[value].append(trade)
            
        results = []
        
        for dim_value, group_trades in groups.items():
            if not group_trades:
                continue
                
            wins = sum(1 for t in group_trades if t.get("outcome") == "won")
            losses = sum(1 for t in group_trades if t.get("outcome") == "lost")
            total = wins + losses
            
            results.append({
                "dimension": dimension.split(".")[-1],
                "value": dim_value,
                "total_trades": len(group_trades),
                "wins": wins,
                "losses": losses,
                "win_rate": wins / total if total > 0 else 0,
                "total_pnl": sum(t.get("pnl", 0) for t in group_trades),
                "avg_pnl": sum(t.get("pnl", 0) for t in group_trades) / len(group_trades)
            })
            
        return sorted(results, key=lambda x: x["win_rate"], reverse=True)
        
    async def _generate_heat_map(
        self,
        trades: List[Dict]
    ) -> List[Dict]:
        """Generate setup x regime heat map"""
        matrix: Dict[str, Dict[str, Dict]] = {}
        
        for trade in trades:
            setup = trade.get("setup_type", "unknown")
            regime = trade.get("context", {}).get("market_regime", "unknown")
            
            if setup not in matrix:
                matrix[setup] = {}
            if regime not in matrix[setup]:
                matrix[setup][regime] = {"wins": 0, "total": 0, "pnl": 0}
                
            matrix[setup][regime]["total"] += 1
            if trade.get("outcome") == "won":
                matrix[setup][regime]["wins"] += 1
            matrix[setup][regime]["pnl"] += trade.get("pnl", 0)
            
        heat_map = []
        
        for setup, regimes in matrix.items():
            for regime, data in regimes.items():
                heat_map.append({
                    "setup": setup,
                    "regime": regime,
                    "total_trades": data["total"],
                    "win_rate": data["wins"] / data["total"] if data["total"] > 0 else 0,
                    "total_pnl": data["pnl"],
                    "heat_score": (data["wins"] / data["total"] * 100) if data["total"] >= 3 else 50
                })
                
        return heat_map
        
    async def get_all_performances(self) -> List[ContextPerformance]:
        """Get all context performance records"""
        if self._context_performance_col is None:
            return []
            
        docs = list(self._context_performance_col.find({}))
        return [ContextPerformance.from_dict(d) for d in docs]
        
    async def get_performance(
        self,
        setup_type: str = None,
        market_regime: str = None,
        time_of_day: str = None
    ) -> Optional[ContextPerformance]:
        """Get performance for a specific context"""
        parts = [
            setup_type or "unknown",
            market_regime or "unknown",
            time_of_day or "unknown"
        ]
        context_key = ":".join(parts)
        
        if self._context_performance_col is None:
            return None
            
        doc = self._context_performance_col.find_one({"context_key": context_key})
        if doc:
            return ContextPerformance.from_dict(doc)
            
        return None
        
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        if self._context_performance_col is not None:
            count = self._context_performance_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "contexts_tracked": count
        }


# Singleton
_context_performance_service: Optional[ContextPerformanceService] = None


def get_context_performance_service() -> ContextPerformanceService:
    global _context_performance_service
    if _context_performance_service is None:
        _context_performance_service = ContextPerformanceService()
    return _context_performance_service
