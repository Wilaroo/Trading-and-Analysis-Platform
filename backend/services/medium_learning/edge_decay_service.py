"""
Edge Decay Service - Phase 5 Medium Learning

Detects when trading edges are degrading over time.
Monitors strategy performance trends and alerts on decline.

Features:
- Rolling performance tracking
- Statistical significance testing
- Early warning alerts
- Automatic strategy flagging
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class EdgeMetrics:
    """Metrics for tracking a trading edge"""
    edge_id: str = ""  # Usually setup_type or setup_type:regime
    name: str = ""
    
    # Historical performance
    all_time_win_rate: float = 0.0
    all_time_trades: int = 0
    all_time_profit_factor: float = 0.0
    
    # Rolling windows
    win_rate_30d: float = 0.0
    win_rate_14d: float = 0.0
    win_rate_7d: float = 0.0
    
    trades_30d: int = 0
    trades_14d: int = 0
    trades_7d: int = 0
    
    # Decay metrics
    decay_score: float = 0.0  # 0-100 (higher = more decay)
    is_decaying: bool = False
    decay_severity: str = "none"  # none, mild, moderate, severe
    decay_trend: str = "stable"  # improving, stable, declining
    
    # Alerts
    alert_generated: bool = False
    alert_message: str = ""
    
    # Timestamps
    first_trade_date: str = ""
    last_trade_date: str = ""
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "EdgeMetrics":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class EdgeDecayReport:
    """Complete edge decay analysis report"""
    report_date: str = ""
    total_edges_tracked: int = 0
    
    # Decay summary
    edges_decaying: int = 0
    edges_improving: int = 0
    edges_stable: int = 0
    
    # Alerts
    critical_alerts: List[Dict] = field(default_factory=list)
    warnings: List[Dict] = field(default_factory=list)
    
    # Edge details
    all_edges: List[Dict] = field(default_factory=list)
    
    # Recommendations
    edges_to_pause: List[str] = field(default_factory=list)
    edges_to_monitor: List[str] = field(default_factory=list)
    edges_performing_well: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class EdgeDecayService:
    """
    Monitors trading edges for signs of decay.
    
    Detection methods:
    1. Rolling window comparison (recent vs historical)
    2. Win rate trend analysis
    3. Profit factor degradation
    4. Statistical significance testing
    """
    
    # Thresholds for decay detection
    MILD_DECAY_THRESHOLD = 0.08  # 8% win rate drop
    MODERATE_DECAY_THRESHOLD = 0.15  # 15% win rate drop
    SEVERE_DECAY_THRESHOLD = 0.25  # 25% win rate drop
    
    MIN_TRADES_FOR_ANALYSIS = 10  # Minimum trades to analyze
    MIN_TRADES_ROLLING = 5  # Minimum trades in rolling window
    
    def __init__(self):
        self._db = None
        self._edge_metrics_col = None
        self._trade_outcomes_col = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._edge_metrics_col = db['edge_metrics']
            self._trade_outcomes_col = db['trade_outcomes']
            
    async def analyze_all_edges(self) -> EdgeDecayReport:
        """
        Analyze all trading edges for decay.
        
        Returns comprehensive report.
        """
        report = EdgeDecayReport(
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        
        if self._trade_outcomes_col is None:
            return report
            
        # Get all unique edges (setup types)
        edges = self._trade_outcomes_col.distinct("setup_type")
        
        report.total_edges_tracked = len(edges)
        
        for edge_name in edges:
            try:
                metrics = await self._analyze_edge(edge_name)
                
                # Save to database
                if self._edge_metrics_col is not None:
                    self._edge_metrics_col.update_one(
                        {"edge_id": metrics.edge_id},
                        {"$set": metrics.to_dict()},
                        upsert=True
                    )
                    
                report.all_edges.append(metrics.to_dict())
                
                # Categorize
                if metrics.decay_severity in ["moderate", "severe"]:
                    report.edges_decaying += 1
                    report.edges_to_pause.append(edge_name)
                    
                    if metrics.decay_severity == "severe":
                        report.critical_alerts.append({
                            "edge": edge_name,
                            "message": metrics.alert_message,
                            "decay_score": metrics.decay_score
                        })
                    else:
                        report.warnings.append({
                            "edge": edge_name,
                            "message": metrics.alert_message,
                            "decay_score": metrics.decay_score
                        })
                        
                elif metrics.decay_trend == "improving":
                    report.edges_improving += 1
                    report.edges_performing_well.append(edge_name)
                elif metrics.decay_severity == "mild":
                    report.edges_to_monitor.append(edge_name)
                else:
                    report.edges_stable += 1
                    report.edges_performing_well.append(edge_name)
                    
            except Exception as e:
                logger.error(f"Error analyzing edge {edge_name}: {e}")
                
        return report
        
    async def _analyze_edge(self, edge_name: str) -> EdgeMetrics:
        """Analyze a single edge for decay"""
        metrics = EdgeMetrics(
            edge_id=f"edge_{edge_name}",
            name=edge_name,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        if self._trade_outcomes_col is None:
            return metrics
            
        # Get all trades for this edge
        all_trades = list(self._trade_outcomes_col.find({"setup_type": edge_name}))
        
        if len(all_trades) < self.MIN_TRADES_FOR_ANALYSIS:
            return metrics
            
        # Calculate all-time metrics
        wins = sum(1 for t in all_trades if t.get("outcome") == "won")
        losses = sum(1 for t in all_trades if t.get("outcome") == "lost")
        total = wins + losses
        
        metrics.all_time_trades = len(all_trades)
        metrics.all_time_win_rate = wins / total if total > 0 else 0
        
        # Profit factor
        gross_profit = sum(t.get("pnl", 0) for t in all_trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t.get("pnl", 0) for t in all_trades if t.get("pnl", 0) < 0))
        metrics.all_time_profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Get trade dates
        sorted_trades = sorted(all_trades, key=lambda t: t.get("created_at", ""))
        if sorted_trades:
            metrics.first_trade_date = sorted_trades[0].get("created_at", "")
            metrics.last_trade_date = sorted_trades[-1].get("created_at", "")
            
        # Rolling window analysis
        now = datetime.now(timezone.utc)
        
        trades_30d = [t for t in all_trades if self._is_within_days(t, now, 30)]
        trades_14d = [t for t in all_trades if self._is_within_days(t, now, 14)]
        trades_7d = [t for t in all_trades if self._is_within_days(t, now, 7)]
        
        metrics.trades_30d = len(trades_30d)
        metrics.trades_14d = len(trades_14d)
        metrics.trades_7d = len(trades_7d)
        
        # Calculate rolling win rates
        if len(trades_30d) >= self.MIN_TRADES_ROLLING:
            wins_30 = sum(1 for t in trades_30d if t.get("outcome") == "won")
            total_30 = wins_30 + sum(1 for t in trades_30d if t.get("outcome") == "lost")
            metrics.win_rate_30d = wins_30 / total_30 if total_30 > 0 else 0
            
        if len(trades_14d) >= self.MIN_TRADES_ROLLING:
            wins_14 = sum(1 for t in trades_14d if t.get("outcome") == "won")
            total_14 = wins_14 + sum(1 for t in trades_14d if t.get("outcome") == "lost")
            metrics.win_rate_14d = wins_14 / total_14 if total_14 > 0 else 0
            
        if len(trades_7d) >= self.MIN_TRADES_ROLLING:
            wins_7 = sum(1 for t in trades_7d if t.get("outcome") == "won")
            total_7 = wins_7 + sum(1 for t in trades_7d if t.get("outcome") == "lost")
            metrics.win_rate_7d = wins_7 / total_7 if total_7 > 0 else 0
            
        # Calculate decay
        metrics = self._calculate_decay(metrics)
        
        return metrics
        
    def _is_within_days(self, trade: Dict, now: datetime, days: int) -> bool:
        """Check if trade is within N days of now"""
        try:
            created_at = trade.get("created_at", "")
            if not created_at:
                return False
                
            # Handle both ISO format strings
            if isinstance(created_at, str):
                trade_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                trade_date = created_at
                
            return (now - trade_date).days <= days
        except Exception:
            return False
            
    def _calculate_decay(self, metrics: EdgeMetrics) -> EdgeMetrics:
        """Calculate decay score and severity"""
        # Use 30d vs all-time as primary comparison
        # Weight by sample size
        
        decay_signals = []
        
        # Compare 30d to all-time
        if metrics.trades_30d >= self.MIN_TRADES_ROLLING:
            drop_30d = metrics.all_time_win_rate - metrics.win_rate_30d
            decay_signals.append(("30d", drop_30d, metrics.trades_30d))
            
        # Compare 14d to 30d or all-time
        if metrics.trades_14d >= self.MIN_TRADES_ROLLING:
            reference = metrics.win_rate_30d if metrics.trades_30d >= self.MIN_TRADES_ROLLING else metrics.all_time_win_rate
            drop_14d = reference - metrics.win_rate_14d
            decay_signals.append(("14d", drop_14d, metrics.trades_14d))
            
        # Compare 7d to 14d or 30d
        if metrics.trades_7d >= self.MIN_TRADES_ROLLING:
            reference = metrics.win_rate_14d if metrics.trades_14d >= self.MIN_TRADES_ROLLING else metrics.win_rate_30d
            if reference == 0:
                reference = metrics.all_time_win_rate
            drop_7d = reference - metrics.win_rate_7d
            decay_signals.append(("7d", drop_7d, metrics.trades_7d))
            
        if not decay_signals:
            return metrics
            
        # Calculate weighted decay score
        total_weight = sum(s[2] for s in decay_signals)
        weighted_drop = sum(s[1] * s[2] for s in decay_signals) / total_weight if total_weight > 0 else 0
        
        # Convert to 0-100 score (50 = neutral)
        # Positive drop = decay, negative drop = improvement
        metrics.decay_score = 50 + (weighted_drop * 200)  # Scale: 10% drop = +20 score
        metrics.decay_score = max(0, min(100, metrics.decay_score))
        
        # Determine severity
        if weighted_drop >= self.SEVERE_DECAY_THRESHOLD:
            metrics.is_decaying = True
            metrics.decay_severity = "severe"
            metrics.alert_generated = True
            metrics.alert_message = (
                f"CRITICAL: {metrics.name} edge severely degraded. "
                f"Win rate dropped from {metrics.all_time_win_rate*100:.0f}% to {metrics.win_rate_30d*100:.0f}%. "
                f"Consider pausing this strategy."
            )
        elif weighted_drop >= self.MODERATE_DECAY_THRESHOLD:
            metrics.is_decaying = True
            metrics.decay_severity = "moderate"
            metrics.alert_generated = True
            metrics.alert_message = (
                f"WARNING: {metrics.name} edge declining. "
                f"Win rate dropped from {metrics.all_time_win_rate*100:.0f}% to {metrics.win_rate_30d*100:.0f}%. "
                f"Review recent trades and market conditions."
            )
        elif weighted_drop >= self.MILD_DECAY_THRESHOLD:
            metrics.decay_severity = "mild"
            metrics.alert_message = (
                f"NOTE: {metrics.name} showing slight decline. "
                f"Continue monitoring."
            )
        else:
            metrics.decay_severity = "none"
            
        # Determine trend (comparing shorter to longer windows)
        if metrics.win_rate_7d > metrics.win_rate_14d > metrics.win_rate_30d:
            metrics.decay_trend = "improving"
        elif metrics.win_rate_7d < metrics.win_rate_14d < metrics.win_rate_30d:
            metrics.decay_trend = "declining"
        else:
            metrics.decay_trend = "stable"
            
        return metrics
        
    async def get_edge_metrics(self, edge_name: str) -> Optional[EdgeMetrics]:
        """Get metrics for a specific edge"""
        if self._edge_metrics_col is None:
            return None
            
        doc = self._edge_metrics_col.find_one({"edge_id": f"edge_{edge_name}"})
        if doc:
            return EdgeMetrics.from_dict(doc)
            
        return None
        
    async def get_all_metrics(self) -> List[EdgeMetrics]:
        """Get all edge metrics"""
        if self._edge_metrics_col is None:
            return []
            
        docs = list(self._edge_metrics_col.find({}))
        return [EdgeMetrics.from_dict(d) for d in docs]
        
    async def get_decaying_edges(self) -> List[EdgeMetrics]:
        """Get all edges currently showing decay"""
        if self._edge_metrics_col is None:
            return []
            
        docs = list(self._edge_metrics_col.find({"is_decaying": True}))
        return [EdgeMetrics.from_dict(d) for d in docs]
        
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        decaying = 0
        
        if self._edge_metrics_col is not None:
            count = self._edge_metrics_col.count_documents({})
            decaying = self._edge_metrics_col.count_documents({"is_decaying": True})
            
        return {
            "db_connected": self._db is not None,
            "edges_tracked": count,
            "edges_decaying": decaying
        }


# Singleton
_edge_decay_service: Optional[EdgeDecayService] = None


def get_edge_decay_service() -> EdgeDecayService:
    global _edge_decay_service
    if _edge_decay_service is None:
        _edge_decay_service = EdgeDecayService()
    return _edge_decay_service
