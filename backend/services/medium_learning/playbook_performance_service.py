"""
Playbook Performance Service - Phase 5 Medium Learning

Links playbook theory to actual trading results.
Tracks how well traders execute each playbook strategy.

Features:
- Playbook execution tracking
- Theory vs reality comparison
- Playbook improvement suggestions
- Personal playbook ranking
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class PlaybookPerformance:
    """Performance metrics for a playbook/strategy"""
    playbook_id: str = ""
    playbook_name: str = ""
    setup_type: str = ""
    
    # Trade counts
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    
    # Performance metrics
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    avg_r: float = 0.0
    profit_factor: float = 0.0
    
    # Expected vs actual
    expected_win_rate: float = 0.0  # From playbook theory
    expected_avg_r: float = 0.0
    win_rate_deviation: float = 0.0  # Actual - Expected
    r_deviation: float = 0.0
    
    # Execution quality
    avg_entry_quality: float = 0.0
    avg_exit_quality: float = 0.0
    avg_r_capture: float = 0.0  # % of potential R captured
    
    # Common issues
    common_mistakes: List[str] = field(default_factory=list)
    improvement_areas: List[str] = field(default_factory=list)
    
    # Trends
    recent_win_rate: float = 0.0  # Last 10 trades
    trend: str = "stable"  # improving, declining, stable
    
    # Confidence
    confidence: str = "low"
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PlaybookPerformance":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PlaybookLinkageReport:
    """Report linking playbooks to real performance"""
    report_date: str = ""
    total_playbooks: int = 0
    total_trades: int = 0
    
    # Rankings
    top_performing_playbooks: List[Dict] = field(default_factory=list)
    underperforming_playbooks: List[Dict] = field(default_factory=list)
    
    # Execution gaps
    biggest_execution_gaps: List[Dict] = field(default_factory=list)
    
    # Recommendations
    playbooks_to_focus: List[str] = field(default_factory=list)
    playbooks_to_review: List[str] = field(default_factory=list)
    playbooks_to_avoid: List[str] = field(default_factory=list)
    
    # Detailed performance
    all_playbooks: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class PlaybookPerformanceService:
    """
    Links playbook strategies to actual trading results.
    
    This service:
    1. Tracks performance by playbook/strategy
    2. Compares actual results to playbook expectations
    3. Identifies execution gaps
    4. Recommends playbook improvements
    """
    
    # Default playbook expectations (can be overridden by actual playbook data)
    DEFAULT_EXPECTATIONS = {
        "bull_flag": {"expected_win_rate": 0.55, "expected_r": 1.5},
        "bear_flag": {"expected_win_rate": 0.50, "expected_r": 1.5},
        "vwap_bounce": {"expected_win_rate": 0.60, "expected_r": 1.2},
        "vwap_fade": {"expected_win_rate": 0.55, "expected_r": 1.0},
        "opening_range_breakout": {"expected_win_rate": 0.45, "expected_r": 2.0},
        "gap_and_go": {"expected_win_rate": 0.50, "expected_r": 1.8},
        "morning_momentum": {"expected_win_rate": 0.55, "expected_r": 1.5},
        "mean_reversion": {"expected_win_rate": 0.60, "expected_r": 1.0},
        "ttm_squeeze": {"expected_win_rate": 0.50, "expected_r": 2.0},
        "first_pullback": {"expected_win_rate": 0.55, "expected_r": 1.3},
        "relative_strength": {"expected_win_rate": 0.58, "expected_r": 1.4},
        "breakout": {"expected_win_rate": 0.45, "expected_r": 2.5},
        "default": {"expected_win_rate": 0.50, "expected_r": 1.5}
    }
    
    def __init__(self):
        self._db = None
        self._playbook_performance_col = None
        self._trade_outcomes_col = None
        self._playbooks_col = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._playbook_performance_col = db['playbook_performance']
            self._trade_outcomes_col = db['trade_outcomes']
            self._playbooks_col = db['playbooks']
            
    async def update_playbook_performance(
        self,
        trades: List[Dict] = None,
        lookback_days: int = 90
    ) -> Dict[str, Any]:
        """
        Update performance stats for all playbooks based on trades.
        
        Returns summary of updates.
        """
        result = {
            "playbooks_updated": 0,
            "total_trades": 0,
            "errors": []
        }
        
        if self._trade_outcomes_col is None:
            return result
            
        # Get trades if not provided
        if trades is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            trades = list(self._trade_outcomes_col.find({
                "created_at": {"$gte": cutoff.isoformat()}
            }))
            
        result["total_trades"] = len(trades)
        
        if not trades:
            return result
            
        # Group by setup type (which maps to playbook)
        setup_trades: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            setup = trade.get("setup_type", "unknown")
            if setup not in setup_trades:
                setup_trades[setup] = []
            setup_trades[setup].append(trade)
            
        # Update performance for each setup/playbook
        for setup_type, trade_list in setup_trades.items():
            try:
                perf = await self._calculate_playbook_performance(setup_type, trade_list)
                
                if self._playbook_performance_col is not None:
                    self._playbook_performance_col.update_one(
                        {"setup_type": setup_type},
                        {"$set": perf.to_dict()},
                        upsert=True
                    )
                    result["playbooks_updated"] += 1
                    
            except Exception as e:
                logger.error(f"Error updating playbook {setup_type}: {e}")
                result["errors"].append(str(e))
                
        return result
        
    async def _calculate_playbook_performance(
        self,
        setup_type: str,
        trades: List[Dict]
    ) -> PlaybookPerformance:
        """Calculate performance metrics for a playbook"""
        perf = PlaybookPerformance(
            playbook_id=f"playbook_{setup_type}",
            playbook_name=setup_type.replace("_", " ").title(),
            setup_type=setup_type,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        if not trades:
            return perf
            
        # Basic counts
        perf.total_trades = len(trades)
        perf.wins = sum(1 for t in trades if t.get("outcome") == "won")
        perf.losses = sum(1 for t in trades if t.get("outcome") == "lost")
        perf.scratches = sum(1 for t in trades if t.get("outcome") == "scratch")
        
        # Win rate
        total = perf.wins + perf.losses
        perf.win_rate = perf.wins / total if total > 0 else 0
        
        # P&L metrics
        pnls = [t.get("pnl", 0) for t in trades]
        perf.total_pnl = sum(pnls)
        perf.avg_pnl = perf.total_pnl / len(pnls) if pnls else 0
        
        # R metrics
        rs = [t.get("actual_r", 0) for t in trades]
        perf.avg_r = sum(rs) / len(rs) if rs else 0
        
        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        perf.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Get expected values
        expectations = self.DEFAULT_EXPECTATIONS.get(
            setup_type,
            self.DEFAULT_EXPECTATIONS["default"]
        )
        perf.expected_win_rate = expectations["expected_win_rate"]
        perf.expected_avg_r = expectations["expected_r"]
        
        # Calculate deviations
        perf.win_rate_deviation = perf.win_rate - perf.expected_win_rate
        perf.r_deviation = perf.avg_r - perf.expected_avg_r
        
        # Execution quality from trades
        entry_quals = []
        exit_quals = []
        r_captures = []
        
        for trade in trades:
            exec_data = trade.get("execution", {})
            if exec_data:
                if exec_data.get("entry_quality"):
                    entry_quals.append(exec_data["entry_quality"])
                if exec_data.get("exit_quality"):
                    exit_quals.append(exec_data["exit_quality"])
                if exec_data.get("r_capture_percent"):
                    r_captures.append(exec_data["r_capture_percent"])
                    
        perf.avg_entry_quality = sum(entry_quals) / len(entry_quals) if entry_quals else 50
        perf.avg_exit_quality = sum(exit_quals) / len(exit_quals) if exit_quals else 50
        perf.avg_r_capture = sum(r_captures) / len(r_captures) if r_captures else 50
        
        # Identify common mistakes
        perf.common_mistakes = await self._identify_mistakes(trades)
        perf.improvement_areas = await self._identify_improvements(perf)
        
        # Recent performance
        sorted_trades = sorted(trades, key=lambda t: t.get("created_at", ""), reverse=True)
        recent = sorted_trades[:10]
        if recent:
            recent_wins = sum(1 for t in recent if t.get("outcome") == "won")
            recent_total = sum(1 for t in recent if t.get("outcome") in ["won", "lost"])
            perf.recent_win_rate = recent_wins / recent_total if recent_total > 0 else 0
            
            if perf.recent_win_rate > perf.win_rate + 0.1:
                perf.trend = "improving"
            elif perf.recent_win_rate < perf.win_rate - 0.1:
                perf.trend = "declining"
                
        # Confidence
        if perf.total_trades >= 30:
            perf.confidence = "high"
        elif perf.total_trades >= 10:
            perf.confidence = "medium"
        else:
            perf.confidence = "low"
            
        return perf
        
    async def _identify_mistakes(self, trades: List[Dict]) -> List[str]:
        """Identify common execution mistakes from trade data"""
        mistakes = []
        
        # Check for chasing entries
        entry_slippages = [
            t.get("execution", {}).get("entry_slippage_percent", 0) 
            for t in trades if t.get("execution")
        ]
        if entry_slippages:
            avg_slippage = sum(entry_slippages) / len(entry_slippages)
            if avg_slippage > 0.3:
                mistakes.append(f"Chasing entries (avg {avg_slippage:.1f}% slippage)")
                
        # Check for early exits
        r_captures = [
            t.get("execution", {}).get("r_capture_percent", 100) 
            for t in trades if t.get("execution") and t.get("outcome") == "won"
        ]
        if r_captures:
            avg_capture = sum(r_captures) / len(r_captures)
            if avg_capture < 60:
                mistakes.append(f"Exiting too early (only capturing {avg_capture:.0f}% of move)")
                
        # Check for holding losers
        losses = [t for t in trades if t.get("outcome") == "lost"]
        if losses:
            big_losses = sum(1 for t in losses if abs(t.get("actual_r", 0)) > 1.5)
            if big_losses / len(losses) > 0.3:
                mistakes.append("Holding losers beyond stop (30%+ trades exceed 1.5R loss)")
                
        return mistakes
        
    async def _identify_improvements(self, perf: PlaybookPerformance) -> List[str]:
        """Identify areas for improvement"""
        improvements = []
        
        if perf.win_rate < perf.expected_win_rate - 0.1:
            improvements.append("Entry selection needs work - win rate below expected")
            
        if perf.avg_entry_quality < 50:
            improvements.append("Work on entry timing - quality score below 50")
            
        if perf.avg_r_capture < 60:
            improvements.append("Let winners run more - capturing less than 60% of move")
            
        if perf.profit_factor < 1.0:
            improvements.append("Risk management needs attention - profit factor below 1")
            
        if perf.trend == "declining":
            improvements.append("Recent performance declining - review recent trades")
            
        return improvements
        
    async def generate_linkage_report(
        self,
        lookback_days: int = 90
    ) -> PlaybookLinkageReport:
        """Generate a complete playbook-performance linkage report"""
        report = PlaybookLinkageReport(
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        
        if self._playbook_performance_col is None:
            return report
            
        # Update performance first
        await self.update_playbook_performance(lookback_days=lookback_days)
        
        # Get all playbook performances
        all_perf = await self.get_all_performance()
        
        report.total_playbooks = len(all_perf)
        report.total_trades = sum(p.total_trades for p in all_perf)
        report.all_playbooks = [p.to_dict() for p in all_perf]
        
        # Sort by win rate to find top/bottom performers
        qualified = [p for p in all_perf if p.total_trades >= 5]
        
        if qualified:
            top = sorted(qualified, key=lambda p: p.win_rate * p.profit_factor, reverse=True)[:5]
            report.top_performing_playbooks = [
                {"name": p.playbook_name, "win_rate": p.win_rate, "profit_factor": p.profit_factor, "trades": p.total_trades}
                for p in top
            ]
            
            bottom = sorted(qualified, key=lambda p: p.win_rate * max(p.profit_factor, 0.1))[:5]
            report.underperforming_playbooks = [
                {"name": p.playbook_name, "win_rate": p.win_rate, "profit_factor": p.profit_factor, "trades": p.total_trades}
                for p in bottom if p.profit_factor < 1.0 or p.win_rate < 0.45
            ]
            
        # Find biggest execution gaps
        for p in qualified:
            if p.win_rate_deviation < -0.15:  # More than 15% below expected
                report.biggest_execution_gaps.append({
                    "playbook": p.playbook_name,
                    "expected_win_rate": p.expected_win_rate,
                    "actual_win_rate": p.win_rate,
                    "gap": abs(p.win_rate_deviation)
                })
                
        report.biggest_execution_gaps.sort(key=lambda x: x["gap"], reverse=True)
        report.biggest_execution_gaps = report.biggest_execution_gaps[:5]
        
        # Generate recommendations
        for p in qualified:
            if p.win_rate >= 0.55 and p.profit_factor >= 1.5:
                report.playbooks_to_focus.append(p.playbook_name)
            elif p.win_rate < 0.40 or p.profit_factor < 0.8:
                report.playbooks_to_avoid.append(p.playbook_name)
            elif p.trend == "declining" or len(p.common_mistakes) >= 2:
                report.playbooks_to_review.append(p.playbook_name)
                
        return report
        
    async def get_performance(self, setup_type: str) -> Optional[PlaybookPerformance]:
        """Get performance for a specific playbook"""
        if self._playbook_performance_col is None:
            return None
            
        doc = self._playbook_performance_col.find_one({"setup_type": setup_type})
        if doc:
            return PlaybookPerformance.from_dict(doc)
            
        return None
        
    async def get_all_performance(self) -> List[PlaybookPerformance]:
        """Get all playbook performances"""
        if self._playbook_performance_col is None:
            return []
            
        docs = list(self._playbook_performance_col.find({}))
        return [PlaybookPerformance.from_dict(d) for d in docs]
        
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        if self._playbook_performance_col is not None:
            count = self._playbook_performance_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "playbooks_tracked": count
        }


# Singleton
_playbook_performance_service: Optional[PlaybookPerformanceService] = None


def get_playbook_performance_service() -> PlaybookPerformanceService:
    global _playbook_performance_service
    if _playbook_performance_service is None:
        _playbook_performance_service = PlaybookPerformanceService()
    return _playbook_performance_service
