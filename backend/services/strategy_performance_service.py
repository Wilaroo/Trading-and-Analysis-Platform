"""
Strategy Performance & Mutual Learning Loop Service

Tracks per-strategy performance metrics, uses AI to analyze patterns,
and auto-tunes bot strategy configurations based on learned insights.

Features:
- Per-strategy performance tracking (win rate, avg P&L, R:R achieved)
- AI-powered performance analysis and recommendations
- Auto-tuning engine with safety guardrails
- Tuning audit trail
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)

# Safety guardrails for auto-tuning
TUNING_BOUNDS = {
    "trail_pct": {"min": 0.005, "max": 0.08, "max_change_pct": 0.20},
    "close_at_eod": {"type": "bool"},
    "scale_out_pcts": {"min_per_level": 0.1, "max_per_level": 0.7},
}


class StrategyPerformanceService:
    """Tracks and analyzes per-strategy trading performance"""
    
    def __init__(self, db=None):
        self._db = db
        self._trading_bot = None
        self._ai_assistant = None
    
    def set_services(self, trading_bot, ai_assistant):
        self._trading_bot = trading_bot
        self._ai_assistant = ai_assistant
        logger.info("Strategy performance service wired to bot and AI")
    
    # ==================== PERFORMANCE TRACKING ====================
    
    def record_trade(self, trade_dict: Dict):
        """Record a closed trade's performance metrics to MongoDB"""
        if not self._db:
            return

        try:
            col = self._db["strategy_performance"]
            record = {
                "trade_id": trade_dict.get("id"),
                "symbol": trade_dict.get("symbol"),
                "strategy": trade_dict.get("setup_type", "unknown"),
                "timeframe": trade_dict.get("timeframe", "intraday"),
                "direction": trade_dict.get("direction", "long"),
                "entry_price": trade_dict.get("fill_price") or trade_dict.get("entry_price", 0),
                "exit_price": trade_dict.get("exit_price", 0),
                "shares": trade_dict.get("shares", 0),
                "realized_pnl": trade_dict.get("realized_pnl", 0),
                "pnl_pct": trade_dict.get("pnl_pct", 0),
                "risk_reward_ratio": trade_dict.get("risk_reward_ratio", 0),
                "close_reason": trade_dict.get("close_reason", "unknown"),
                "quality_score": trade_dict.get("quality_score", 0),
                "quality_grade": trade_dict.get("quality_grade", ""),
                "close_at_eod": trade_dict.get("close_at_eod", True),
                "trail_pct_used": trade_dict.get("trailing_stop_config", {}).get("trail_pct", 0),
                "created_at": trade_dict.get("created_at"),
                "closed_at": trade_dict.get("closed_at") or datetime.now(timezone.utc).isoformat(),
                "recorded_at": datetime.now(timezone.utc).isoformat()
            }
            col.insert_one(record)
            logger.info(f"Recorded performance: {record['symbol']} {record['strategy']} P&L=${record['realized_pnl']:.2f}")
        except Exception as e:
            logger.error(f"Error recording trade performance: {e}")
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get aggregated performance stats per strategy"""
        if not self._db:
            return {}
        
        try:
            col = self._db["strategy_performance"]
            pipeline = [
                {"$group": {
                    "_id": "$strategy",
                    "total_trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}},
                    "losses": {"$sum": {"$cond": [{"$lte": ["$realized_pnl", 0]}, 1, 0]}},
                    "total_pnl": {"$sum": "$realized_pnl"},
                    "avg_pnl": {"$avg": "$realized_pnl"},
                    "avg_pnl_pct": {"$avg": "$pnl_pct"},
                    "avg_rr": {"$avg": "$risk_reward_ratio"},
                    "max_win": {"$max": "$realized_pnl"},
                    "max_loss": {"$min": "$realized_pnl"},
                    "avg_quality": {"$avg": "$quality_score"},
                    "strategies_used": {"$addToSet": "$timeframe"},
                    "close_reasons": {"$push": "$close_reason"},
                    "trail_pcts": {"$push": "$trail_pct_used"}
                }},
                {"$sort": {"total_trades": -1}}
            ]
            
            results = list(col.aggregate(pipeline))
            stats = {}
            for r in results:
                strategy = r["_id"]
                total = r["total_trades"]
                wins = r["wins"]
                win_rate = (wins / total * 100) if total > 0 else 0
                
                # Analyze close reasons
                reasons = r.get("close_reasons", [])
                reason_counts = {}
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                
                stats[strategy] = {
                    "total_trades": total,
                    "wins": wins,
                    "losses": r["losses"],
                    "win_rate": round(win_rate, 1),
                    "total_pnl": round(r["total_pnl"], 2),
                    "avg_pnl": round(r["avg_pnl"], 2),
                    "avg_pnl_pct": round(r.get("avg_pnl_pct", 0), 2),
                    "avg_rr_achieved": round(r.get("avg_rr", 0), 2),
                    "best_trade": round(r.get("max_win", 0), 2),
                    "worst_trade": round(r.get("max_loss", 0), 2),
                    "avg_quality_score": round(r.get("avg_quality", 0), 1),
                    "close_reasons": reason_counts,
                    "timeframe": r.get("strategies_used", ["unknown"])[0] if r.get("strategies_used") else "unknown"
                }
            
            return stats
        except Exception as e:
            logger.error(f"Error getting strategy stats: {e}")
            return {}
    
    def get_recent_trades(self, strategy: str = None, limit: int = 20) -> List[Dict]:
        """Get recent trade records, optionally filtered by strategy"""
        if not self._db:
            return []
        
        try:
            col = self._db["strategy_performance"]
            query = {"strategy": strategy} if strategy else {}
            cursor = col.find(query, {"_id": 0}).sort("closed_at", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting recent trades: {e}")
            return []
    
    # ==================== AI PERFORMANCE ANALYZER ====================
    
    async def analyze_performance(self) -> Dict:
        """Have AI analyze strategy performance and generate recommendations"""
        stats = self.get_strategy_stats()
        
        if not stats:
            return {
                "success": True,
                "analysis": "No trade data yet. The bot needs to close some trades before performance analysis can run.",
                "recommendations": []
            }
        
        if not self._ai_assistant:
            return {"success": False, "error": "AI assistant not connected"}
        
        # Get current strategy configs for context
        current_configs = {}
        if self._trading_bot:
            current_configs = self._trading_bot.get_strategy_configs()
        
        # Build analysis prompt
        prompt = f"""STRATEGY PERFORMANCE ANALYSIS REQUEST:

Analyze the trading bot's per-strategy performance data and suggest specific parameter tuning.

=== CURRENT STRATEGY CONFIGS ===
{json.dumps(current_configs, indent=2)}

=== PERFORMANCE DATA BY STRATEGY ===
{json.dumps(stats, indent=2)}

Based on this data, provide:
1. PERFORMANCE SUMMARY: Brief overview of each strategy's performance
2. PATTERN ANALYSIS: What patterns do you see? (e.g., stop losses too tight, runners being cut short, certain strategies underperforming)
3. SPECIFIC RECOMMENDATIONS: For each strategy that needs adjustment, provide EXACT parameter changes:
   - trail_pct: new value (current is X%)
   - close_at_eod: true/false
   - scale_out_pcts: [pct1, pct2, pct3]
   
Format each recommendation as:
RECOMMENDATION: strategy_name | parameter | current_value | suggested_value | reasoning

Keep analysis concise and actionable. Focus on data-driven insights."""
        
        try:
            result = await self._ai_assistant.evaluate_bot_opportunity({
                "symbol": "PERFORMANCE_ANALYSIS",
                "direction": "analysis",
                "setup_type": "performance_review",
                "timeframe": "all",
                "entry_price": 0, "stop_price": 0, "target_prices": [],
                "risk_amount": 0, "risk_reward_ratio": 0,
                "quality_score": 0, "quality_grade": "N/A"
            })
            
            # Actually use direct LLM call for better analysis
            messages = [{"role": "user", "content": prompt}]
            analysis_text = await self._ai_assistant._call_llm(messages, "")
            
            # Parse recommendations from the analysis
            recommendations = self._parse_recommendations(analysis_text, stats, current_configs)
            
            # Save analysis to DB
            self._save_analysis(analysis_text, recommendations, stats)
            
            return {
                "success": True,
                "analysis": analysis_text,
                "recommendations": recommendations,
                "strategy_stats": stats,
                "current_configs": current_configs
            }
        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            return {"success": False, "error": str(e)}
    
    def _parse_recommendations(self, analysis: str, stats: Dict, configs: Dict) -> List[Dict]:
        """Parse structured recommendations from AI analysis text"""
        recommendations = []
        
        for line in analysis.split("\n"):
            line = line.strip()
            if line.startswith("RECOMMENDATION:"):
                parts = line.replace("RECOMMENDATION:", "").strip().split("|")
                if len(parts) >= 4:
                    strategy = parts[0].strip()
                    param = parts[1].strip()
                    current = parts[2].strip()
                    suggested = parts[3].strip()
                    reasoning = parts[4].strip() if len(parts) > 4 else ""
                    
                    # Validate strategy exists
                    if strategy in configs:
                        rec = {
                            "id": f"{strategy}_{param}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                            "strategy": strategy,
                            "parameter": param,
                            "current_value": current,
                            "suggested_value": suggested,
                            "reasoning": reasoning,
                            "status": "pending",
                            "created_at": datetime.now(timezone.utc).isoformat()
                        }
                        
                        # Validate against safety bounds
                        if self._validate_recommendation(rec):
                            recommendations.append(rec)
        
        # If no structured recs found, generate heuristic ones
        if not recommendations and stats:
            recommendations = self._generate_heuristic_recommendations(stats, configs)
        
        return recommendations
    
    def _generate_heuristic_recommendations(self, stats: Dict, configs: Dict) -> List[Dict]:
        """Generate data-driven recommendations when AI doesn't produce structured ones"""
        recommendations = []
        
        for strategy, perf in stats.items():
            if strategy not in configs:
                continue
            config = configs[strategy]
            
            # Low win rate with stops being hit -> trail stop too tight
            stop_losses = perf.get("close_reasons", {}).get("stop_loss", 0)
            trailing_stops = perf.get("close_reasons", {}).get("stop_loss_trailing", 0)
            total = perf["total_trades"]
            
            if total >= 3:
                stop_rate = (stop_losses + trailing_stops) / total
                
                if stop_rate > 0.5 and perf["win_rate"] < 50:
                    current_trail = config.get("trail_pct", 0.02)
                    suggested_trail = min(current_trail * 1.15, TUNING_BOUNDS["trail_pct"]["max"])
                    recommendations.append({
                        "id": f"{strategy}_trail_pct_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                        "strategy": strategy,
                        "parameter": "trail_pct",
                        "current_value": str(current_trail),
                        "suggested_value": str(round(suggested_trail, 4)),
                        "reasoning": f"High stop-out rate ({stop_rate*100:.0f}%) with low win rate ({perf['win_rate']}%). Wider trailing stop may let winners run.",
                        "status": "pending",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
                
                # High win rate but low avg P&L -> scale out too aggressively early
                if perf["win_rate"] > 65 and perf["avg_pnl"] < perf.get("best_trade", 0) * 0.2:
                    current_scale = config.get("scale_out_pcts", [0.33, 0.33, 0.34])
                    if len(current_scale) >= 3 and current_scale[0] > 0.3:
                        suggested_scale = [round(current_scale[0] - 0.05, 2), round(current_scale[1], 2), round(1 - (current_scale[0] - 0.05) - current_scale[1], 2)]
                        recommendations.append({
                            "id": f"{strategy}_scale_out_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                            "strategy": strategy,
                            "parameter": "scale_out_pcts",
                            "current_value": str(current_scale),
                            "suggested_value": str(suggested_scale),
                            "reasoning": f"High win rate ({perf['win_rate']}%) but avg P&L (${perf['avg_pnl']:.0f}) is low relative to best trade (${perf['best_trade']:.0f}). Hold more shares for runners.",
                            "status": "pending",
                            "created_at": datetime.now(timezone.utc).isoformat()
                        })
        
        return recommendations
    
    def _validate_recommendation(self, rec: Dict) -> bool:
        """Validate recommendation against safety bounds"""
        param = rec.get("parameter")
        if param not in TUNING_BOUNDS:
            return True
        
        bounds = TUNING_BOUNDS[param]
        
        if param == "trail_pct":
            try:
                val = float(rec["suggested_value"])
                return bounds["min"] <= val <= bounds["max"]
            except (ValueError, TypeError):
                return False
        
        return True
    
    # ==================== AUTO-TUNING ENGINE ====================
    
    def apply_recommendation(self, rec_id: str) -> Dict:
        """Apply a specific recommendation to the bot's strategy config"""
        if not self._trading_bot:
            return {"success": False, "error": "Trading bot not connected"}
        
        # Find the recommendation
        rec = self._get_recommendation(rec_id)
        if not rec:
            return {"success": False, "error": f"Recommendation {rec_id} not found"}
        
        strategy = rec["strategy"]
        param = rec["parameter"]
        suggested = rec["suggested_value"]
        
        # Parse value
        try:
            if param == "trail_pct":
                update = {"trail_pct": float(suggested)}
            elif param == "close_at_eod":
                update = {"close_at_eod": suggested.lower() == "true"}
            elif param == "scale_out_pcts":
                update = {"scale_out_pcts": json.loads(suggested.replace("'", '"'))}
            else:
                return {"success": False, "error": f"Unknown parameter: {param}"}
        except (ValueError, json.JSONDecodeError) as e:
            return {"success": False, "error": f"Invalid value: {e}"}
        
        # Apply to bot
        success = self._trading_bot.update_strategy_config(strategy, update)
        
        if success:
            # Record in audit trail
            self._record_tuning_action(rec, "applied")
            # Update recommendation status
            self._update_recommendation_status(rec_id, "applied")
            
            new_configs = self._trading_bot.get_strategy_configs()
            return {
                "success": True,
                "message": f"Applied: {strategy}.{param} = {suggested}",
                "updated_config": new_configs.get(strategy)
            }
        
        return {"success": False, "error": "Failed to update strategy config"}
    
    def dismiss_recommendation(self, rec_id: str) -> Dict:
        """Dismiss a recommendation"""
        self._update_recommendation_status(rec_id, "dismissed")
        return {"success": True, "message": f"Recommendation {rec_id} dismissed"}
    
    def get_pending_recommendations(self) -> List[Dict]:
        """Get all pending recommendations"""
        if not self._db:
            return []
        try:
            col = self._db["tuning_recommendations"]
            return list(col.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1))
        except Exception:
            return []
    
    def get_tuning_history(self, limit: int = 20) -> List[Dict]:
        """Get audit trail of all tuning actions"""
        if not self._db:
            return []
        try:
            col = self._db["tuning_history"]
            return list(col.find({}, {"_id": 0}).sort("applied_at", -1).limit(limit))
        except Exception:
            return []
    
    # ==================== INTERNAL HELPERS ====================
    
    def _save_analysis(self, analysis: str, recommendations: List[Dict], stats: Dict):
        """Save analysis and recommendations to DB"""
        if not self._db:
            return
        try:
            # Save recommendations
            if recommendations:
                col = self._db["tuning_recommendations"]
                for rec in recommendations:
                    col.replace_one({"id": rec["id"]}, rec, upsert=True)
            
            # Save analysis record
            col = self._db["performance_analyses"]
            col.insert_one({
                "analysis": analysis,
                "recommendation_count": len(recommendations),
                "strategy_stats": stats,
                "created_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            logger.error(f"Error saving analysis: {e}")
    
    def _get_recommendation(self, rec_id: str) -> Optional[Dict]:
        if not self._db:
            return None
        try:
            col = self._db["tuning_recommendations"]
            return col.find_one({"id": rec_id}, {"_id": 0})
        except Exception:
            return None
    
    def _update_recommendation_status(self, rec_id: str, status: str):
        if not self._db:
            return
        try:
            col = self._db["tuning_recommendations"]
            col.update_one({"id": rec_id}, {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}})
        except Exception as e:
            logger.error(f"Error updating recommendation: {e}")
    
    def _record_tuning_action(self, rec: Dict, action: str):
        if not self._db:
            return
        try:
            col = self._db["tuning_history"]
            col.insert_one({
                "recommendation_id": rec.get("id"),
                "strategy": rec.get("strategy"),
                "parameter": rec.get("parameter"),
                "old_value": rec.get("current_value"),
                "new_value": rec.get("suggested_value"),
                "reasoning": rec.get("reasoning"),
                "action": action,
                "applied_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            logger.error(f"Error recording tuning action: {e}")


# Singleton
_perf_service = None

def get_performance_service():
    global _perf_service
    if _perf_service is None:
        _perf_service = StrategyPerformanceService()
    return _perf_service
