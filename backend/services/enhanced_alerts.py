"""
Enhanced Alert Service
Generates detailed, contextual alerts with timestamps, reasons, and timeframes.
Provides natural language summaries for trading opportunities.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


class AlertTimeframe:
    """Trading timeframe classifications"""
    SCALP = "SCALP"  # Seconds to minutes
    INTRADAY = "INTRADAY"  # Minutes to hours (same day)
    SWING = "SWING"  # Days to weeks
    POSITION = "POSITION"  # Weeks to months


class AlertType:
    """Types of trading alerts"""
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    REVERSAL = "REVERSAL"
    PULLBACK = "PULLBACK"
    MOMENTUM = "MOMENTUM"
    SQUEEZE = "SQUEEZE"
    EARNINGS = "EARNINGS"
    STRATEGY_MATCH = "STRATEGY_MATCH"


def format_time_natural(dt: datetime) -> str:
    """Format datetime in natural language"""
    now = datetime.now(timezone.utc)
    
    if dt.date() == now.date():
        return f"Today at {dt.strftime('%-I:%M%p').lower()}"
    elif (now.date() - dt.date()).days == 1:
        return f"Yesterday at {dt.strftime('%-I:%M%p').lower()}"
    else:
        return dt.strftime('%b %d at %-I:%M%p').lower()


def determine_timeframe(strategy_id: str, features: Dict[str, Any]) -> str:
    """
    Determine the appropriate trading timeframe based on strategy and features.
    """
    # Strategy prefix indicates timeframe
    if strategy_id.startswith("INT-"):
        # Intraday strategies
        if "scalp" in strategy_id.lower() or features.get("atr_percentage", 0) < 1:
            return AlertTimeframe.SCALP
        return AlertTimeframe.INTRADAY
    
    elif strategy_id.startswith("SWG-"):
        return AlertTimeframe.SWING
    
    elif strategy_id.startswith("POS-"):
        return AlertTimeframe.POSITION
    
    # Determine by technical context
    bars_analyzed = features.get("bars_analyzed", 78)
    if bars_analyzed <= 20:
        return AlertTimeframe.SCALP
    elif bars_analyzed <= 78:  # 1 day of 5-min bars
        return AlertTimeframe.INTRADAY
    elif bars_analyzed <= 390:  # 5 days
        return AlertTimeframe.SWING
    else:
        return AlertTimeframe.POSITION


def get_timeframe_description(timeframe: str) -> str:
    """Get human-readable timeframe description"""
    descriptions = {
        AlertTimeframe.SCALP: "quick scalp (minutes)",
        AlertTimeframe.INTRADAY: "intraday trade (same day)",
        AlertTimeframe.SWING: "swing trade (days to weeks)",
        AlertTimeframe.POSITION: "position trade (weeks to months)"
    }
    return descriptions.get(timeframe, "trade")


def generate_trigger_reason(
    alert_type: str,
    symbol: str,
    strategy: Dict[str, Any],
    features: Dict[str, Any],
    scores: Dict[str, Any]
) -> str:
    """
    Generate detailed reason why the alert was triggered.
    """
    strategy_name = strategy.get("name", "Unknown Strategy")
    strategy_id = strategy.get("id", "")
    
    reasons = []
    
    # Primary trigger
    if alert_type == AlertType.BREAKOUT:
        level = features.get("breakout_level", features.get("resistance_1", 0))
        reasons.append(f"broke above resistance at ${level:.2f}")
    elif alert_type == AlertType.BREAKDOWN:
        level = features.get("breakdown_level", features.get("support_1", 0))
        reasons.append(f"broke below support at ${level:.2f}")
    elif alert_type == AlertType.PULLBACK:
        reasons.append(f"pulled back to key support while maintaining uptrend")
    elif alert_type == AlertType.REVERSAL:
        reasons.append(f"showing reversal signals at extreme levels")
    elif alert_type == AlertType.MOMENTUM:
        reasons.append(f"momentum surge detected")
    elif alert_type == AlertType.SQUEEZE:
        reasons.append(f"short squeeze potential with high short interest")
    
    # Supporting factors
    rvol = features.get("rvol", 1.0)
    if rvol >= 2.0:
        reasons.append(f"volume {rvol:.1f}x above average")
    elif rvol >= 1.5:
        reasons.append(f"elevated volume ({rvol:.1f}x)")
    
    rsi = features.get("rsi", 50)
    if rsi > 70:
        reasons.append(f"RSI overbought at {rsi:.0f}")
    elif rsi < 30:
        reasons.append(f"RSI oversold at {rsi:.0f}")
    
    trend = features.get("trend", "NEUTRAL")
    if trend == "BULLISH":
        reasons.append("trend aligned bullish")
    elif trend == "BEARISH":
        reasons.append("trend aligned bearish")
    
    return "; ".join(reasons) if reasons else "matched strategy criteria"


def generate_natural_language_summary(
    symbol: str,
    company_name: str,
    alert_type: str,
    timeframe: str,
    strategy: Dict[str, Any],
    features: Dict[str, Any],
    scores: Dict[str, Any],
    trading_summary: Dict[str, Any],
    triggered_at: datetime
) -> str:
    """
    Generate a full natural language summary of the trading opportunity.
    """
    strategy_name = strategy.get("name", "Unknown")
    price = features.get("price", trading_summary.get("entry", 0))
    direction = trading_summary.get("direction", "LONG" if alert_type == AlertType.BREAKOUT else "SHORT")
    entry = trading_summary.get("entry", price)
    stop = trading_summary.get("stop_loss", 0)
    target = trading_summary.get("target", 0)
    rr = trading_summary.get("risk_reward", 0)
    
    overall_score = scores.get("overall", 0)
    confidence = "high" if overall_score >= 70 else "moderate" if overall_score >= 50 else "low"
    
    time_str = format_time_natural(triggered_at)
    timeframe_desc = get_timeframe_description(timeframe)
    
    # Build the summary
    if alert_type == AlertType.BREAKOUT:
        level_type = "resistance" if direction == "LONG" else "support"
        level = features.get("breakout_level", features.get("resistance_1", entry))
        
        summary = f"{time_str}, {symbol} ({company_name}) broke above {level_type} at ${level:.2f}, "
        summary += f"triggering a {strategy_name} opportunity on a {timeframe_desc} timeframe. "
        
    elif alert_type == AlertType.BREAKDOWN:
        level = features.get("breakdown_level", features.get("support_1", entry))
        
        summary = f"{time_str}, {symbol} ({company_name}) broke below support at ${level:.2f}, "
        summary += f"triggering a {strategy_name} short opportunity on a {timeframe_desc} timeframe. "
        
    elif alert_type == AlertType.PULLBACK:
        summary = f"{time_str}, {symbol} ({company_name}) pulled back to key support, "
        summary += f"triggering a {strategy_name} buy-the-dip opportunity on a {timeframe_desc} timeframe. "
        
    else:
        summary = f"{time_str}, {symbol} ({company_name}) triggered a {strategy_name} "
        summary += f"opportunity on a {timeframe_desc} timeframe. "
    
    # Add conviction and analysis
    summary += f"\n\nBased on my analysis, this setup has {confidence} conviction "
    summary += f"(Overall Score: {overall_score}/100) to "
    
    if direction == "LONG":
        summary += f"move higher towards the target. "
    else:
        summary += f"move lower towards the target. "
    
    # Trade details
    summary += f"\n\n**Trade Plan:**\n"
    summary += f"• Direction: {direction}\n"
    summary += f"• Entry: ${entry:.2f}\n"
    summary += f"• Stop Loss: ${stop:.2f}\n"
    summary += f"• Target: ${target:.2f}\n"
    summary += f"• Risk/Reward: 1:{rr:.1f}\n"
    
    # Risk context
    risk_per_share = abs(entry - stop)
    reward_per_share = abs(target - entry)
    summary += f"\n**Risk Analysis:**\n"
    summary += f"• Risk per share: ${risk_per_share:.2f}\n"
    summary += f"• Reward per share: ${reward_per_share:.2f}\n"
    
    # Supporting factors
    rvol = features.get("rvol", 1.0)
    rsi = features.get("rsi", 50)
    trend = features.get("trend", "NEUTRAL")
    
    summary += f"\n**Supporting Factors:**\n"
    summary += f"• Relative Volume: {rvol:.1f}x {'(elevated)' if rvol >= 1.5 else '(normal)'}\n"
    summary += f"• RSI: {rsi:.0f} {'(overbought)' if rsi > 70 else '(oversold)' if rsi < 30 else '(neutral)'}\n"
    summary += f"• Trend: {trend}\n"
    
    # Strategy match info
    matched_strategies = features.get("matched_strategies", [])
    if matched_strategies:
        summary += f"• Matched {len(matched_strategies)} of your 77 trading rules\n"
    
    return summary


def create_enhanced_alert(
    symbol: str,
    company_name: str,
    alert_type: str,
    strategy: Dict[str, Any],
    features: Dict[str, Any],
    scores: Dict[str, Any],
    trading_summary: Dict[str, Any],
    matched_strategies: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a comprehensive alert with all context.
    """
    triggered_at = datetime.now(timezone.utc)
    timeframe = determine_timeframe(strategy.get("id", ""), features)
    
    # Store matched strategies in features for summary generation
    if matched_strategies:
        features["matched_strategies"] = matched_strategies
    
    trigger_reason = generate_trigger_reason(
        alert_type, symbol, strategy, features, scores
    )
    
    natural_summary = generate_natural_language_summary(
        symbol, company_name, alert_type, timeframe,
        strategy, features, scores, trading_summary, triggered_at
    )
    
    return {
        "id": f"{symbol}_{alert_type}_{triggered_at.timestamp()}",
        "symbol": symbol,
        "company_name": company_name,
        "alert_type": alert_type,
        "timeframe": timeframe,
        "timeframe_description": get_timeframe_description(timeframe),
        
        # Timing
        "triggered_at": triggered_at.isoformat(),
        "triggered_at_formatted": format_time_natural(triggered_at),
        "triggered_at_unix": int(triggered_at.timestamp()),
        
        # Why it triggered
        "trigger_reason": trigger_reason,
        "primary_strategy": {
            "id": strategy.get("id"),
            "name": strategy.get("name"),
            "category": strategy.get("category"),
            "description": strategy.get("description", "")
        },
        
        # Scores
        "scores": {
            "overall": scores.get("overall", 0),
            "technical": scores.get("technical", 0),
            "fundamental": scores.get("fundamental", 0),
            "catalyst": scores.get("catalyst", 0),
            "confidence": scores.get("confidence", 0)
        },
        "grade": get_grade(scores.get("overall", 0)),
        
        # Trade plan
        "trade_plan": {
            "direction": trading_summary.get("direction", "LONG"),
            "entry": trading_summary.get("entry"),
            "stop_loss": trading_summary.get("stop_loss"),
            "target": trading_summary.get("target"),
            "risk_reward": trading_summary.get("risk_reward", 0),
            "position_bias": trading_summary.get("position_bias", "NEUTRAL")
        },
        
        # Supporting data
        "features": {
            "price": features.get("price", 0),
            "change_percent": features.get("change_percent", 0),
            "rvol": features.get("rvol", 1.0),
            "rsi": features.get("rsi", 50),
            "trend": features.get("trend", "NEUTRAL"),
            "vwap_distance": features.get("vwap_distance", 0),
            "atr": features.get("atr", 0)
        },
        
        # Levels
        "levels": {
            "resistance_1": features.get("resistance_1"),
            "resistance_2": features.get("resistance_2"),
            "support_1": features.get("support_1"),
            "support_2": features.get("support_2"),
            "breakout_level": features.get("breakout_level"),
            "breakdown_level": features.get("breakdown_level")
        },
        
        # Strategy matches
        "matched_strategies_count": len(matched_strategies) if matched_strategies else 0,
        "signal_strength": round((len(matched_strategies) / 77) * 100, 1) if matched_strategies else 0,
        "matched_strategies": matched_strategies[:5] if matched_strategies else [],
        
        # Natural language
        "headline": generate_headline(symbol, alert_type, strategy, timeframe, triggered_at),
        "summary": natural_summary,
        
        # Metadata
        "is_active": True,
        "is_new": True,
        "expires_at": None,  # Alerts don't expire, they're archived
    }


def generate_headline(
    symbol: str,
    alert_type: str,
    strategy: Dict[str, Any],
    timeframe: str,
    triggered_at: datetime
) -> str:
    """Generate a concise headline for the alert"""
    time_str = format_time_natural(triggered_at)
    strategy_name = strategy.get("name", "")
    
    timeframe_adj = {
        AlertTimeframe.SCALP: "scalp",
        AlertTimeframe.INTRADAY: "intraday",
        AlertTimeframe.SWING: "swing",
        AlertTimeframe.POSITION: "position"
    }.get(timeframe, "")
    
    if alert_type == AlertType.BREAKOUT:
        return f"{symbol} triggered {time_str}: {strategy_name} {timeframe_adj} breakout opportunity"
    elif alert_type == AlertType.BREAKDOWN:
        return f"{symbol} triggered {time_str}: {strategy_name} {timeframe_adj} breakdown (short) opportunity"
    elif alert_type == AlertType.PULLBACK:
        return f"{symbol} triggered {time_str}: {strategy_name} {timeframe_adj} pullback entry"
    elif alert_type == AlertType.SQUEEZE:
        return f"{symbol} triggered {time_str}: Short squeeze potential on {timeframe_adj} timeframe"
    else:
        return f"{symbol} triggered {time_str}: {strategy_name} on {timeframe_adj} timeframe"


def get_grade(score: int) -> str:
    """Get letter grade from score"""
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 35:
        return "D"
    return "F"


# Singleton for managing active alerts
class EnhancedAlertManager:
    """Manages enhanced alerts with full context"""
    
    def __init__(self):
        self.active_alerts: List[Dict[str, Any]] = []
        self.alert_history: List[Dict[str, Any]] = []
    
    def add_alert(self, alert: Dict[str, Any]) -> None:
        """Add a new alert"""
        # Check for duplicate (same symbol and type within 5 minutes)
        for existing in self.active_alerts:
            if (existing["symbol"] == alert["symbol"] and 
                existing["alert_type"] == alert["alert_type"]):
                time_diff = alert["triggered_at_unix"] - existing["triggered_at_unix"]
                if time_diff < 300:  # 5 minutes
                    return  # Duplicate, skip
        
        self.active_alerts.append(alert)
        self.alert_history.append(alert)
        
        # Keep history manageable
        if len(self.alert_history) > 500:
            self.alert_history = self.alert_history[-500:]
    
    def get_active_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get active alerts"""
        return sorted(
            self.active_alerts,
            key=lambda x: x["triggered_at_unix"],
            reverse=True
        )[:limit]
    
    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get alert history"""
        return sorted(
            self.alert_history,
            key=lambda x: x["triggered_at_unix"],
            reverse=True
        )[:limit]
    
    def mark_alert_viewed(self, alert_id: str) -> None:
        """Mark an alert as viewed (no longer new)"""
        for alert in self.active_alerts:
            if alert["id"] == alert_id:
                alert["is_new"] = False
                break
    
    def archive_alert(self, alert_id: str) -> None:
        """Archive an alert (remove from active)"""
        self.active_alerts = [a for a in self.active_alerts if a["id"] != alert_id]
    
    def clear_active_alerts(self) -> None:
        """Clear all active alerts"""
        self.active_alerts = []


# Global alert manager
_alert_manager: Optional[EnhancedAlertManager] = None


def get_alert_manager() -> EnhancedAlertManager:
    """Get the global alert manager"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = EnhancedAlertManager()
    return _alert_manager
