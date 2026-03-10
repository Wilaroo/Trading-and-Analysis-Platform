"""
Confirmation Validator Service - Phase 5 Medium Learning

Tracks which confirmation signals actually improve trade outcomes.
Validates the effectiveness of different confirmation types.

Features:
- Volume confirmation tracking
- Tape reading confirmation validation
- Multiple confirmation analysis
- Confirmation strength scoring
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import statistics

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationStats:
    """Statistics for a confirmation signal type"""
    confirmation_type: str = ""  # volume, tape, l2_bid, rvol, vwap, etc.
    
    # With confirmation
    trades_with: int = 0
    wins_with: int = 0
    win_rate_with: float = 0.0
    avg_pnl_with: float = 0.0
    avg_r_with: float = 0.0
    
    # Without confirmation
    trades_without: int = 0
    wins_without: int = 0
    win_rate_without: float = 0.0
    avg_pnl_without: float = 0.0
    avg_r_without: float = 0.0
    
    # Impact metrics
    win_rate_lift: float = 0.0  # Percentage point improvement
    pnl_lift: float = 0.0
    r_lift: float = 0.0
    effectiveness_score: float = 0.0  # 0-100
    
    # Recommendation
    is_effective: bool = True
    recommendation: str = ""
    confidence: str = "low"
    
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ConfirmationStats":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ConfirmationValidationReport:
    """Complete validation report for all confirmations"""
    report_date: str = ""
    total_trades_analyzed: int = 0
    
    # Confirmation stats
    confirmation_stats: List[Dict] = field(default_factory=list)
    
    # Best confirmations
    most_effective: List[str] = field(default_factory=list)
    least_effective: List[str] = field(default_factory=list)
    
    # Combination analysis
    best_combinations: List[Dict] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ConfirmationValidatorService:
    """
    Validates the effectiveness of confirmation signals.
    
    Confirmation types tracked:
    - volume: Above-average volume at entry
    - rvol: Relative volume >= 1.5
    - tape: Tape reading confirmation (bid/ask imbalance)
    - l2_support: Level 2 support visible
    - vwap_respect: Price respecting VWAP
    - trend_alignment: Setup aligned with higher timeframe trend
    - sector_momentum: Sector showing strength/weakness
    - news_catalyst: Recent news catalyst present
    """
    
    CONFIRMATION_TYPES = [
        "volume",
        "rvol",
        "tape",
        "l2_support",
        "vwap_respect",
        "trend_alignment",
        "sector_momentum",
        "news_catalyst"
    ]
    
    def __init__(self):
        self._db = None
        self._confirmation_stats_col = None
        self._trade_outcomes_col = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._confirmation_stats_col = db['confirmation_stats']
            self._trade_outcomes_col = db['trade_outcomes']
            
    async def validate_confirmations(
        self,
        lookback_days: int = 30
    ) -> ConfirmationValidationReport:
        """
        Validate all confirmation types against historical trades.
        
        Returns a complete validation report.
        """
        report = ConfirmationValidationReport(
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        
        if self._trade_outcomes_col is None:
            return report
            
        # Get trades from lookback period
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        
        trades = list(self._trade_outcomes_col.find({
            "created_at": {"$gte": cutoff.isoformat()}
        }))
        
        report.total_trades_analyzed = len(trades)
        
        if not trades:
            return report
            
        # Validate each confirmation type
        all_stats = []
        
        for conf_type in self.CONFIRMATION_TYPES:
            stats = await self._validate_confirmation_type(conf_type, trades)
            all_stats.append(stats)
            
            # Save to database
            if self._confirmation_stats_col is not None:
                self._confirmation_stats_col.update_one(
                    {"confirmation_type": conf_type},
                    {"$set": stats.to_dict()},
                    upsert=True
                )
                
        report.confirmation_stats = [s.to_dict() for s in all_stats]
        
        # Find most/least effective
        effective = sorted(all_stats, key=lambda s: s.effectiveness_score, reverse=True)
        
        report.most_effective = [s.confirmation_type for s in effective[:3] if s.effectiveness_score > 60]
        report.least_effective = [s.confirmation_type for s in effective[-3:] if s.effectiveness_score < 40]
        
        # Analyze combinations
        report.best_combinations = await self._analyze_combinations(trades)
        
        # Generate recommendations
        for stats in all_stats:
            if stats.recommendation:
                report.recommendations.append(stats.recommendation)
                
        return report
        
    async def _validate_confirmation_type(
        self,
        conf_type: str,
        trades: List[Dict]
    ) -> ConfirmationStats:
        """Validate a single confirmation type"""
        stats = ConfirmationStats(
            confirmation_type=conf_type,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        # Split trades by whether they had this confirmation
        with_conf = []
        without_conf = []
        
        for trade in trades:
            confirmations = trade.get("context", {}).get("confirmations", {})
            
            # Check if confirmation was present
            has_conf = self._check_confirmation(trade, conf_type)
            
            if has_conf:
                with_conf.append(trade)
            else:
                without_conf.append(trade)
                
        # Calculate stats for each group
        if with_conf:
            stats.trades_with = len(with_conf)
            stats.wins_with = sum(1 for t in with_conf if t.get("outcome") == "won")
            total_with = stats.wins_with + sum(1 for t in with_conf if t.get("outcome") == "lost")
            stats.win_rate_with = stats.wins_with / total_with if total_with > 0 else 0
            stats.avg_pnl_with = sum(t.get("pnl", 0) for t in with_conf) / len(with_conf)
            stats.avg_r_with = sum(t.get("actual_r", 0) for t in with_conf) / len(with_conf)
            
        if without_conf:
            stats.trades_without = len(without_conf)
            stats.wins_without = sum(1 for t in without_conf if t.get("outcome") == "won")
            total_without = stats.wins_without + sum(1 for t in without_conf if t.get("outcome") == "lost")
            stats.win_rate_without = stats.wins_without / total_without if total_without > 0 else 0
            stats.avg_pnl_without = sum(t.get("pnl", 0) for t in without_conf) / len(without_conf)
            stats.avg_r_without = sum(t.get("actual_r", 0) for t in without_conf) / len(without_conf)
            
        # Calculate impact
        stats.win_rate_lift = (stats.win_rate_with - stats.win_rate_without) * 100
        stats.pnl_lift = stats.avg_pnl_with - stats.avg_pnl_without
        stats.r_lift = stats.avg_r_with - stats.avg_r_without
        
        # Calculate effectiveness score (0-100)
        # Based on: win rate lift, sample size, consistency
        score = 50  # Start neutral
        
        # Win rate lift contributes up to 30 points
        if stats.win_rate_lift > 0:
            score += min(stats.win_rate_lift * 2, 30)
        else:
            score += max(stats.win_rate_lift * 2, -30)
            
        # P&L lift contributes up to 20 points
        if stats.pnl_lift > 0:
            score += min(stats.pnl_lift / 10, 20)
        else:
            score += max(stats.pnl_lift / 10, -20)
            
        # Sample size bonus (confidence)
        min_trades = min(stats.trades_with, stats.trades_without)
        if min_trades >= 20:
            stats.confidence = "high"
        elif min_trades >= 10:
            stats.confidence = "medium"
        else:
            stats.confidence = "low"
            score *= 0.8  # Reduce score if low confidence
            
        stats.effectiveness_score = max(0, min(100, score))
        
        # Determine if effective
        stats.is_effective = stats.effectiveness_score >= 50 and stats.win_rate_lift > 0
        
        # Generate recommendation
        if stats.confidence != "low":
            if stats.win_rate_lift > 10:
                stats.recommendation = f"REQUIRE {conf_type} confirmation - adds {stats.win_rate_lift:.0f}% to win rate"
            elif stats.win_rate_lift > 5:
                stats.recommendation = f"PREFER {conf_type} confirmation - adds {stats.win_rate_lift:.0f}% to win rate"
            elif stats.win_rate_lift < -5:
                stats.recommendation = f"IGNORE {conf_type} - may be misleading (reduces win rate by {abs(stats.win_rate_lift):.0f}%)"
                
        return stats
        
    def _check_confirmation(self, trade: Dict, conf_type: str) -> bool:
        """Check if a trade had a specific confirmation"""
        context = trade.get("context", {})
        confirmations = context.get("confirmations", {})
        
        # Direct check in confirmations dict
        if conf_type in confirmations:
            return bool(confirmations[conf_type])
            
        # Check derived confirmations
        if conf_type == "volume":
            return context.get("volume_ratio", 0) > 1.2
        elif conf_type == "rvol":
            return context.get("rvol", 0) >= 1.5
        elif conf_type == "tape":
            return confirmations.get("tape_bullish") or confirmations.get("tape_bearish")
        elif conf_type == "l2_support":
            return confirmations.get("l2_bid_support") or confirmations.get("l2_offer_wall")
        elif conf_type == "vwap_respect":
            technicals = context.get("technicals", {})
            return technicals.get("vwap_distance_percent", 0) < 0.5
        elif conf_type == "trend_alignment":
            return confirmations.get("trend_aligned", False)
        elif conf_type == "sector_momentum":
            return context.get("sector_rank", 6) <= 3  # Top 3 sector
        elif conf_type == "news_catalyst":
            return bool(context.get("has_news_catalyst")) or bool(context.get("news_sentiment"))
            
        return False
        
    async def _analyze_combinations(
        self,
        trades: List[Dict]
    ) -> List[Dict]:
        """Analyze which confirmation combinations work best"""
        combinations: Dict[str, Dict] = {}
        
        for trade in trades:
            # Build confirmation fingerprint
            active_confs = []
            for conf_type in self.CONFIRMATION_TYPES:
                if self._check_confirmation(trade, conf_type):
                    active_confs.append(conf_type)
                    
            if not active_confs:
                key = "no_confirmations"
            else:
                key = "+".join(sorted(active_confs))
                
            if key not in combinations:
                combinations[key] = {"trades": [], "wins": 0, "total": 0}
                
            combinations[key]["trades"].append(trade)
            combinations[key]["total"] += 1
            if trade.get("outcome") == "won":
                combinations[key]["wins"] += 1
                
        # Convert to list with win rates
        result = []
        for combo_key, data in combinations.items():
            if data["total"] >= 3:  # Min sample
                result.append({
                    "confirmations": combo_key.split("+") if combo_key != "no_confirmations" else [],
                    "total_trades": data["total"],
                    "wins": data["wins"],
                    "win_rate": data["wins"] / data["total"] if data["total"] > 0 else 0,
                    "avg_pnl": sum(t.get("pnl", 0) for t in data["trades"]) / len(data["trades"])
                })
                
        return sorted(result, key=lambda x: x["win_rate"], reverse=True)[:10]
        
    async def get_confirmation_stats(
        self,
        conf_type: str
    ) -> Optional[ConfirmationStats]:
        """Get stats for a specific confirmation type"""
        if self._confirmation_stats_col is None:
            return None
            
        doc = self._confirmation_stats_col.find_one({"confirmation_type": conf_type})
        if doc:
            return ConfirmationStats.from_dict(doc)
            
        return None
        
    async def get_all_stats(self) -> List[ConfirmationStats]:
        """Get all confirmation stats"""
        if self._confirmation_stats_col is None:
            return []
            
        docs = list(self._confirmation_stats_col.find({}))
        return [ConfirmationStats.from_dict(d) for d in docs]
        
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        if self._confirmation_stats_col is not None:
            count = self._confirmation_stats_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "confirmations_tracked": count,
            "confirmation_types": self.CONFIRMATION_TYPES
        }


# Singleton
_confirmation_validator_service: Optional[ConfirmationValidatorService] = None


def get_confirmation_validator_service() -> ConfirmationValidatorService:
    global _confirmation_validator_service
    if _confirmation_validator_service is None:
        _confirmation_validator_service = ConfirmationValidatorService()
    return _confirmation_validator_service
