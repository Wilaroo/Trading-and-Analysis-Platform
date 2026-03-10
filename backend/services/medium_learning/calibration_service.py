"""
Calibration Service - Phase 5 Medium Learning

Analyzes trading results and recommends threshold adjustments.
Tracks historical calibrations and their impact.

Features:
- TQS threshold calibration
- Setup-specific adjustments  
- Market regime adaptations
- Confidence-weighted recommendations
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import statistics

logger = logging.getLogger(__name__)


@dataclass
class CalibrationRecommendation:
    """A recommended threshold adjustment"""
    id: str = ""
    parameter: str = ""  # e.g., "tqs_min_threshold", "bull_flag_min_score"
    current_value: float = 0.0
    recommended_value: float = 0.0
    change_percent: float = 0.0
    reason: str = ""
    confidence: str = "low"  # low, medium, high
    supporting_data: Dict = field(default_factory=dict)
    created_at: str = ""
    applied: bool = False
    impact_after_applied: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CalibrationRecommendation":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CalibrationConfig:
    """Configuration for calibration thresholds"""
    # Global TQS thresholds
    tqs_strong_buy_threshold: float = 80
    tqs_buy_threshold: float = 65
    tqs_hold_threshold: float = 50
    tqs_avoid_threshold: float = 35
    
    # Setup-specific thresholds (can override global)
    setup_overrides: Dict[str, float] = field(default_factory=dict)
    
    # Regime-specific adjustments
    regime_adjustments: Dict[str, float] = field(default_factory=lambda: {
        "strong_uptrend": -5,
        "strong_downtrend": 5,
        "choppy": 10,
        "high_volatility": 8
    })
    
    # Min sample size for calibration
    min_sample_size: int = 10
    
    # Max adjustment per calibration
    max_adjustment: float = 10.0
    
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CalibrationConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CalibrationService:
    """
    Manages threshold calibration based on trading results.
    
    Workflow:
    1. Analyze recent trade outcomes
    2. Compare results against thresholds used
    3. Recommend adjustments based on patterns
    4. Track impact of applied changes
    """
    
    def __init__(self):
        self._db = None
        self._calibration_config_col = None
        self._calibration_history_col = None
        self._trade_outcomes_col = None
        
        self._current_config: Optional[CalibrationConfig] = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._calibration_config_col = db['calibration_config']
            self._calibration_history_col = db['calibration_history']
            self._trade_outcomes_col = db['trade_outcomes']
            
    async def get_config(self) -> CalibrationConfig:
        """Get current calibration configuration"""
        if self._current_config:
            return self._current_config
            
        if self._calibration_config_col is not None:
            doc = self._calibration_config_col.find_one({"config_id": "default"})
            if doc:
                doc.pop('_id', None)
                self._current_config = CalibrationConfig.from_dict(doc)
                return self._current_config
                
        self._current_config = CalibrationConfig()
        return self._current_config
        
    async def save_config(self, config: CalibrationConfig):
        """Save calibration configuration"""
        if self._calibration_config_col is None:
            return
            
        config.last_updated = datetime.now(timezone.utc).isoformat()
        doc = config.to_dict()
        doc['config_id'] = 'default'
        
        self._calibration_config_col.update_one(
            {"config_id": "default"},
            {"$set": doc},
            upsert=True
        )
        self._current_config = config
        
    async def analyze_and_recommend(
        self,
        lookback_days: int = 30
    ) -> List[CalibrationRecommendation]:
        """
        Analyze recent trades and generate calibration recommendations.
        
        Returns list of recommended threshold adjustments.
        """
        recommendations = []
        
        if self._trade_outcomes_col is None:
            return recommendations
            
        config = await self.get_config()
        
        # Get trades from lookback period
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        
        trades = list(self._trade_outcomes_col.find({
            "created_at": {"$gte": cutoff.isoformat()}
        }))
        
        if len(trades) < config.min_sample_size:
            return recommendations
            
        # 1. Analyze TQS threshold performance
        tqs_recommendations = await self._analyze_tqs_thresholds(trades, config)
        recommendations.extend(tqs_recommendations)
        
        # 2. Analyze setup-specific performance
        setup_recommendations = await self._analyze_setup_thresholds(trades, config)
        recommendations.extend(setup_recommendations)
        
        # 3. Analyze regime adjustments
        regime_recommendations = await self._analyze_regime_adjustments(trades, config)
        recommendations.extend(regime_recommendations)
        
        # Save recommendations to history
        for rec in recommendations:
            if self._calibration_history_col is not None:
                rec.id = f"cal_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{rec.parameter}"
                rec.created_at = datetime.now(timezone.utc).isoformat()
                self._calibration_history_col.insert_one(rec.to_dict())
                
        return recommendations
        
    async def _analyze_tqs_thresholds(
        self,
        trades: List[Dict],
        config: CalibrationConfig
    ) -> List[CalibrationRecommendation]:
        """Analyze TQS threshold effectiveness"""
        recommendations = []
        
        # Group trades by TQS score bands
        bands = {
            "strong_buy": {"min": 80, "trades": [], "threshold": config.tqs_strong_buy_threshold},
            "buy": {"min": 65, "max": 80, "trades": [], "threshold": config.tqs_buy_threshold},
            "hold": {"min": 50, "max": 65, "trades": [], "threshold": config.tqs_hold_threshold},
            "avoid": {"min": 35, "max": 50, "trades": [], "threshold": config.tqs_avoid_threshold}
        }
        
        for trade in trades:
            tqs = trade.get("tqs_score", trade.get("quality_score", 50))
            
            if tqs >= 80:
                bands["strong_buy"]["trades"].append(trade)
            elif tqs >= 65:
                bands["buy"]["trades"].append(trade)
            elif tqs >= 50:
                bands["hold"]["trades"].append(trade)
            else:
                bands["avoid"]["trades"].append(trade)
                
        # Check each band's performance
        for band_name, band_data in bands.items():
            band_trades = band_data["trades"]
            
            if len(band_trades) < 5:
                continue
                
            wins = sum(1 for t in band_trades if t.get("outcome") == "won")
            win_rate = wins / len(band_trades)
            
            # Expected win rates by band
            expected_rates = {
                "strong_buy": 0.65,
                "buy": 0.55,
                "hold": 0.50,
                "avoid": 0.40
            }
            
            expected = expected_rates.get(band_name, 0.50)
            
            # Check if actual significantly differs from expected
            if win_rate < expected - 0.10:  # 10% below expected
                # Recommend raising threshold
                current = band_data["threshold"]
                suggested = min(current + 5, 100)
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"tqs_{band_name}_threshold",
                    current_value=current,
                    recommended_value=suggested,
                    change_percent=((suggested - current) / current) * 100 if current > 0 else 0,
                    reason=f"{band_name.replace('_', ' ').title()} trades underperforming. "
                           f"Win rate {win_rate*100:.0f}% vs expected {expected*100:.0f}%",
                    confidence="medium" if len(band_trades) >= 15 else "low",
                    supporting_data={
                        "sample_size": len(band_trades),
                        "actual_win_rate": win_rate,
                        "expected_win_rate": expected,
                        "total_pnl": sum(t.get("pnl", 0) for t in band_trades)
                    }
                ))
            elif win_rate > expected + 0.15:  # 15% above expected
                # Can lower threshold (more opportunities)
                current = band_data["threshold"]
                suggested = max(current - 3, 0)
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"tqs_{band_name}_threshold",
                    current_value=current,
                    recommended_value=suggested,
                    change_percent=((suggested - current) / current) * 100 if current > 0 else 0,
                    reason=f"{band_name.replace('_', ' ').title()} trades outperforming. "
                           f"Win rate {win_rate*100:.0f}% vs expected {expected*100:.0f}%",
                    confidence="medium" if len(band_trades) >= 15 else "low",
                    supporting_data={
                        "sample_size": len(band_trades),
                        "actual_win_rate": win_rate,
                        "expected_win_rate": expected,
                        "total_pnl": sum(t.get("pnl", 0) for t in band_trades)
                    }
                ))
                
        return recommendations
        
    async def _analyze_setup_thresholds(
        self,
        trades: List[Dict],
        config: CalibrationConfig
    ) -> List[CalibrationRecommendation]:
        """Analyze setup-specific threshold needs"""
        recommendations = []
        
        # Group trades by setup type
        setup_trades: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            setup = trade.get("setup_type", "unknown")
            if setup not in setup_trades:
                setup_trades[setup] = []
            setup_trades[setup].append(trade)
            
        for setup_type, setup_list in setup_trades.items():
            if len(setup_list) < 5:
                continue
                
            wins = sum(1 for t in setup_list if t.get("outcome") == "won")
            win_rate = wins / len(setup_list)
            avg_pnl = sum(t.get("pnl", 0) for t in setup_list) / len(setup_list)
            
            # Get current override or default
            current_threshold = config.setup_overrides.get(setup_type, config.tqs_buy_threshold)
            
            # Analyze
            if win_rate < 0.40 and avg_pnl < 0:
                # Struggling setup - raise threshold
                suggested = min(current_threshold + 8, 90)
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"setup_threshold_{setup_type}",
                    current_value=current_threshold,
                    recommended_value=suggested,
                    change_percent=((suggested - current_threshold) / current_threshold) * 100 if current_threshold > 0 else 0,
                    reason=f"{setup_type} struggling with {win_rate*100:.0f}% win rate "
                           f"and ${avg_pnl:.0f} avg P&L. Tighten entry criteria.",
                    confidence="high" if len(setup_list) >= 20 else "medium",
                    supporting_data={
                        "sample_size": len(setup_list),
                        "win_rate": win_rate,
                        "avg_pnl": avg_pnl,
                        "total_pnl": sum(t.get("pnl", 0) for t in setup_list)
                    }
                ))
            elif win_rate > 0.60 and avg_pnl > 0:
                # Strong setup - could lower threshold for more opportunities
                suggested = max(current_threshold - 5, 50)
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"setup_threshold_{setup_type}",
                    current_value=current_threshold,
                    recommended_value=suggested,
                    change_percent=((suggested - current_threshold) / current_threshold) * 100 if current_threshold > 0 else 0,
                    reason=f"{setup_type} performing well with {win_rate*100:.0f}% win rate. "
                           f"Consider lowering threshold for more opportunities.",
                    confidence="medium",
                    supporting_data={
                        "sample_size": len(setup_list),
                        "win_rate": win_rate,
                        "avg_pnl": avg_pnl
                    }
                ))
                
        return recommendations
        
    async def _analyze_regime_adjustments(
        self,
        trades: List[Dict],
        config: CalibrationConfig
    ) -> List[CalibrationRecommendation]:
        """Analyze if regime adjustments are working"""
        recommendations = []
        
        # Group trades by regime
        regime_trades: Dict[str, List[Dict]] = {}
        
        for trade in trades:
            regime = trade.get("context", {}).get("market_regime", "unknown")
            if regime not in regime_trades:
                regime_trades[regime] = []
            regime_trades[regime].append(trade)
            
        for regime, regime_list in regime_trades.items():
            if len(regime_list) < 5 or regime == "unknown":
                continue
                
            wins = sum(1 for t in regime_list if t.get("outcome") == "won")
            win_rate = wins / len(regime_list)
            
            current_adjustment = config.regime_adjustments.get(regime, 0)
            
            # If win rate is low in this regime, increase the adjustment (harder to pass)
            if win_rate < 0.40:
                suggested = current_adjustment + 5
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"regime_adjustment_{regime}",
                    current_value=current_adjustment,
                    recommended_value=suggested,
                    change_percent=((suggested - current_adjustment) / abs(current_adjustment)) * 100 if current_adjustment != 0 else 100,
                    reason=f"Low win rate ({win_rate*100:.0f}%) in {regime} regime. "
                           f"Increase threshold adjustment to be more selective.",
                    confidence="medium" if len(regime_list) >= 15 else "low",
                    supporting_data={
                        "sample_size": len(regime_list),
                        "win_rate": win_rate
                    }
                ))
            elif win_rate > 0.65:
                suggested = current_adjustment - 3
                
                recommendations.append(CalibrationRecommendation(
                    parameter=f"regime_adjustment_{regime}",
                    current_value=current_adjustment,
                    recommended_value=suggested,
                    change_percent=((suggested - current_adjustment) / abs(current_adjustment)) * 100 if current_adjustment != 0 else -100,
                    reason=f"Strong win rate ({win_rate*100:.0f}%) in {regime} regime. "
                           f"Can reduce threshold adjustment for more opportunities.",
                    confidence="medium",
                    supporting_data={
                        "sample_size": len(regime_list),
                        "win_rate": win_rate
                    }
                ))
                
        return recommendations
        
    async def apply_recommendation(
        self,
        recommendation_id: str
    ) -> Dict[str, Any]:
        """Apply a calibration recommendation"""
        if self._calibration_history_col is None:
            return {"success": False, "error": "Database not connected"}
            
        # Find the recommendation
        rec_doc = self._calibration_history_col.find_one({"id": recommendation_id})
        if not rec_doc:
            return {"success": False, "error": "Recommendation not found"}
            
        rec = CalibrationRecommendation.from_dict(rec_doc)
        config = await self.get_config()
        
        # Apply the change based on parameter type
        param = rec.parameter
        new_value = rec.recommended_value
        
        if param.startswith("tqs_"):
            if "strong_buy" in param:
                config.tqs_strong_buy_threshold = new_value
            elif "buy" in param:
                config.tqs_buy_threshold = new_value
            elif "hold" in param:
                config.tqs_hold_threshold = new_value
            elif "avoid" in param:
                config.tqs_avoid_threshold = new_value
        elif param.startswith("setup_threshold_"):
            setup_name = param.replace("setup_threshold_", "")
            config.setup_overrides[setup_name] = new_value
        elif param.startswith("regime_adjustment_"):
            regime_name = param.replace("regime_adjustment_", "")
            config.regime_adjustments[regime_name] = new_value
            
        # Save updated config
        await self.save_config(config)
        
        # Mark recommendation as applied
        self._calibration_history_col.update_one(
            {"id": recommendation_id},
            {"$set": {"applied": True, "applied_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        return {
            "success": True,
            "parameter": param,
            "old_value": rec.current_value,
            "new_value": new_value
        }
        
    async def get_history(
        self,
        limit: int = 50,
        applied_only: bool = False
    ) -> List[CalibrationRecommendation]:
        """Get calibration history"""
        if self._calibration_history_col is None:
            return []
            
        query = {}
        if applied_only:
            query["applied"] = True
            
        docs = list(
            self._calibration_history_col
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        
        return [CalibrationRecommendation.from_dict(d) for d in docs]
        
    def get_stats(self) -> Dict[str, Any]:
        """Get calibration service statistics"""
        return {
            "config_loaded": self._current_config is not None,
            "db_connected": self._db is not None
        }


# Singleton
_calibration_service: Optional[CalibrationService] = None


def get_calibration_service() -> CalibrationService:
    global _calibration_service
    if _calibration_service is None:
        _calibration_service = CalibrationService()
    return _calibration_service


def init_calibration_service(db=None) -> CalibrationService:
    service = get_calibration_service()
    if db is not None:
        service.set_db(db)
    return service
