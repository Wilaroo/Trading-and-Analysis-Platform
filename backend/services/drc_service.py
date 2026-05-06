"""
SMB Daily Report Card (DRC) Service
Based on SMB Capital's DRC methodology

The DRC is a structured daily trading journal that includes:
- Overall day grade (A-F) based on PROCESS, not just P&L
- Pre-market checklist (customizable)
- Intraday performance tracker (3 segments: 7:30-11, 11-2, 2-4:30)
- Big picture market commentary
- Reflections and lessons learned
- Auto-generation from daily trading data
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from bson import ObjectId


class DRCService:
    """Service for managing Daily Report Cards"""
    
    # Default pre-market checklist items (customizable)
    DEFAULT_PREMARKET_CHECKLIST = [
        {"id": "visualization", "label": "Visualization (execution and process)", "checked": False},
        {"id": "chief_aim", "label": "Chief Aim Statement + Vision Board", "checked": False},
        {"id": "daily_markup", "label": "Daily markup (at least 2 trading zones)", "checked": False},
        {"id": "game_plan", "label": "Review Game Plan", "checked": False},
        {"id": "news_check", "label": "Check pre-market news/catalysts", "checked": False},
        {"id": "levels", "label": "Key levels marked on charts", "checked": False},
        {"id": "risk_defined", "label": "Daily risk limit defined", "checked": False},
        {"id": "phone_dnd", "label": "Phone on DND", "checked": False}
    ]
    
    # Default post-market checklist items
    DEFAULT_POSTMARKET_CHECKLIST = [
        {"id": "trade_review", "label": "Review all trades taken", "checked": False},
        {"id": "replay", "label": "Film review (replay key trades)", "checked": False},
        {"id": "journal_update", "label": "Update trading journal", "checked": False},
        {"id": "playbook_update", "label": "Update playbook if new setup", "checked": False},
        {"id": "tomorrow_prep", "label": "Prep stocks for tomorrow", "checked": False}
    ]
    
    # Time segments for intraday tracking
    TIME_SEGMENTS = [
        {"id": "morning", "label": "7:30 AM - 11:00 AM", "start": "07:30", "end": "11:00"},
        {"id": "midday", "label": "11:00 AM - 2:00 PM", "start": "11:00", "end": "14:00"},
        {"id": "afternoon", "label": "2:00 PM - 4:30 PM", "start": "14:00", "end": "16:30"}
    ]
    
    # Process grades
    GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
    
    def __init__(self, db):
        self.db = db
        self.drc_col = db["daily_report_cards"]
        self.checklist_settings_col = db["drc_checklist_settings"]
        
        # Create indexes
        self.drc_col.create_index([("date", -1)], unique=True)
        self.drc_col.create_index([("overall_grade", 1)])
    
    async def create_drc(self, date: str = None, auto_populate: bool = True) -> Dict:
        """
        Create a new Daily Report Card
        
        If auto_populate=True, will pull data from:
        - Day's trades
        - Market context
        - Portfolio performance
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Check if DRC already exists for this date
        existing = self.drc_col.find_one({"date": date})
        if existing:
            existing["id"] = str(existing["_id"])
            del existing["_id"]
            return existing
        
        now = datetime.now(timezone.utc)
        
        # Get custom checklist settings or use defaults
        checklist_settings = self.checklist_settings_col.find_one({"type": "settings"})
        premarket_checklist = checklist_settings.get("premarket", self.DEFAULT_PREMARKET_CHECKLIST) if checklist_settings else self.DEFAULT_PREMARKET_CHECKLIST
        postmarket_checklist = checklist_settings.get("postmarket", self.DEFAULT_POSTMARKET_CHECKLIST) if checklist_settings else self.DEFAULT_POSTMARKET_CHECKLIST
        
        drc = {
            "date": date,
            
            # Overall Assessment
            "overall_grade": "",
            "day_pnl": 0.0,
            "day_pnl_percent": 0.0,
            
            # Pre-Market Section
            "premarket_checklist": [item.copy() for item in premarket_checklist],
            "goal_for_today": "",
            "focus_areas": [],
            
            # Big Picture Commentary
            "big_picture": {
                "market_overview": "",
                "market_regime": "",  # Trending, Consolidating, etc.
                "key_levels": {
                    "spy_support": "",
                    "spy_resistance": "",
                    "qqq_support": "",
                    "qqq_resistance": ""
                },
                "vix_level": None,
                "market_sentiment": "",  # Risk-On, Risk-Off, Neutral
                "major_news": "",
                "sector_leaders": [],
                "sector_laggards": []
            },
            
            # Intraday Performance Tracker (3 segments)
            "intraday_segments": [
                {
                    "segment_id": seg["id"],
                    "label": seg["label"],
                    "start": seg["start"],
                    "end": seg["end"],
                    "grade": "",
                    "pnl": 0.0,
                    "trades_taken": 0,
                    "sizing_proper": True,
                    "in_my_favor": True,
                    "comments": ""
                }
                for seg in self.TIME_SEGMENTS
            ],
            
            # Trades Summary (auto-populated)
            "trades_summary": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "biggest_winner": None,
                "biggest_loser": None,
                "trades": []  # List of trade summaries
            },
            
            # Post-Market Section
            "postmarket_checklist": [item.copy() for item in postmarket_checklist],
            
            # Reflections (Key DRC Component)
            "reflections": {
                "what_i_learned": "",
                "what_worked_well": "",
                "what_needs_improvement": "",
                "changes_for_tomorrow": "",
                "easiest_3k_trade": "",  # Even if missed, identify it
                "biggest_mistake": "",
                "best_decision": ""
            },
            
            # Notes for Tomorrow
            "tomorrow_notes": {
                "stocks_to_watch": [],
                "setups_to_look_for": [],
                "things_to_avoid": [],
                "general_notes": ""
            },
            
            # Metadata
            "is_complete": False,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        # Auto-populate if requested
        if auto_populate:
            drc = await self._auto_populate_drc(drc, date)
        
        result = self.drc_col.insert_one(drc)
        drc["id"] = str(result.inserted_id)
        
        return {k: v for k, v in drc.items() if k != "_id"}
    
    async def _auto_populate_drc(self, drc: Dict, date: str) -> Dict:
        """Auto-populate DRC with data from the day's trading activity"""
        
        # Get trades from the day
        trades_col = self.db["trades"]
        bot_trades_col = self.db["bot_trades"]
        
        # Parse date to get date range
        date_start = f"{date}T00:00:00"
        date_end = f"{date}T23:59:59"
        
        # Get manual trades
        manual_trades = list(trades_col.find({
            "entry_date": {"$gte": date_start, "$lte": date_end}
        }, {"_id": 0}))
        
        # Get bot trades
        bot_trades = list(bot_trades_col.find({
            "$or": [
                {"entry_time": {"$gte": date_start, "$lte": date_end}},
                {"executed_at": {"$gte": date_start, "$lte": date_end}},
            ]
        }, {"_id": 0}))
        
        all_trades = manual_trades + bot_trades
        
        if all_trades:
            total_trades = len(all_trades)
            closed_trades = [t for t in all_trades if t.get("status") == "closed" or t.get("pnl") is not None or t.get("realized_pnl") is not None]
            
            def _get_pnl(t):
                return t.get("pnl") or t.get("realized_pnl") or 0
            
            winning = len([t for t in closed_trades if _get_pnl(t) > 0])
            losing = len([t for t in closed_trades if _get_pnl(t) < 0])
            total_pnl = sum(_get_pnl(t) for t in closed_trades)
            
            pnls = [(t.get("symbol", ""), _get_pnl(t)) for t in closed_trades]
            biggest_winner = max(pnls, key=lambda x: x[1]) if pnls else None
            biggest_loser = min(pnls, key=lambda x: x[1]) if pnls else None
            
            drc["trades_summary"] = {
                "total_trades": total_trades,
                "winning_trades": winning,
                "losing_trades": losing,
                "win_rate": round(winning / len(closed_trades) * 100, 1) if closed_trades else 0,
                "biggest_winner": {"symbol": biggest_winner[0], "pnl": biggest_winner[1]} if biggest_winner and biggest_winner[1] > 0 else None,
                "biggest_loser": {"symbol": biggest_loser[0], "pnl": biggest_loser[1]} if biggest_loser and biggest_loser[1] < 0 else None,
                "trades": [
                    {
                        "symbol": t.get("symbol"),
                        "direction": t.get("direction"),
                        "pnl": t.get("pnl"),
                        "setup_type": t.get("setup_type") or t.get("strategy_name"),
                        "entry_time": t.get("entry_time") or t.get("entry_date")
                    }
                    for t in all_trades[:20]  # Limit to 20 trades in summary
                ]
            }
            
            drc["day_pnl"] = round(total_pnl, 2)
        
        # Get market context from the day
        try:
            market_intel_col = self.db.get_collection("market_intel")
            if market_intel_col is not None:
                market_data = market_intel_col.find_one(
                    {"date": {"$regex": f"^{date}"}},
                    {"_id": 0}
                )
                if market_data:
                    drc["big_picture"]["market_regime"] = market_data.get("regime", "")
                    drc["big_picture"]["market_sentiment"] = market_data.get("sentiment", "")
        except Exception as e:
            print(f"Failed to load market intel: {e}")
        
        return drc
    
    async def get_drc(self, date: str) -> Optional[Dict]:
        """Get DRC for a specific date"""
        drc = self.drc_col.find_one({"date": date})
        if drc:
            drc["id"] = str(drc["_id"])
            del drc["_id"]
        return drc
    
    async def get_drc_by_id(self, drc_id: str) -> Optional[Dict]:
        """Get DRC by ID"""
        drc = self.drc_col.find_one({"_id": ObjectId(drc_id)})
        if drc:
            drc["id"] = str(drc["_id"])
            del drc["_id"]
        return drc
    
    async def update_drc(self, date: str, updates: Dict) -> Dict:
        """Update a DRC"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Remove protected fields
        protected = ["_id", "id", "date", "created_at"]
        update_data = {k: v for k, v in updates.items() if k not in protected}
        
        self.drc_col.update_one(
            {"date": date},
            {"$set": update_data}
        )
        
        return await self.get_drc(date)
    
    async def get_recent_drcs(self, limit: int = 30) -> List[Dict]:
        """Get recent DRCs"""
        drcs = list(self.drc_col.find(
            {},
            {"_id": 1, "date": 1, "overall_grade": 1, "day_pnl": 1, "is_complete": 1, 
             "trades_summary.total_trades": 1, "trades_summary.win_rate": 1}
        ).sort("date", -1).limit(limit))
        
        for drc in drcs:
            drc["id"] = str(drc["_id"])
            del drc["_id"]
        
        return drcs
    
    async def get_drc_stats(self, days: int = 30) -> Dict:
        """Get DRC statistics over a period"""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        drcs = list(self.drc_col.find(
            {"date": {"$gte": cutoff_date}},
            {"_id": 0, "date": 1, "overall_grade": 1, "day_pnl": 1, "is_complete": 1,
             "trades_summary": 1, "intraday_segments": 1}
        ))
        
        if not drcs:
            return {
                "period_days": days,
                "total_drcs": 0,
                "complete_drcs": 0,
                "total_pnl": 0,
                "grade_distribution": {},
                "best_segment": None,
                "worst_segment": None
            }
        
        # Grade distribution
        grade_dist = {}
        for drc in drcs:
            grade = drc.get("overall_grade", "")
            if grade:
                grade_dist[grade] = grade_dist.get(grade, 0) + 1
        
        # Segment performance
        segment_pnls = {"morning": 0, "midday": 0, "afternoon": 0}
        segment_counts = {"morning": 0, "midday": 0, "afternoon": 0}
        
        for drc in drcs:
            for seg in drc.get("intraday_segments", []):
                seg_id = seg.get("segment_id")
                if seg_id in segment_pnls:
                    segment_pnls[seg_id] += seg.get("pnl", 0)
                    segment_counts[seg_id] += 1
        
        # Calculate averages
        segment_avgs = {}
        for seg_id in segment_pnls:
            if segment_counts[seg_id] > 0:
                segment_avgs[seg_id] = round(segment_pnls[seg_id] / segment_counts[seg_id], 2)
            else:
                segment_avgs[seg_id] = 0
        
        best_seg = max(segment_avgs.items(), key=lambda x: x[1]) if segment_avgs else None
        worst_seg = min(segment_avgs.items(), key=lambda x: x[1]) if segment_avgs else None
        
        return {
            "period_days": days,
            "total_drcs": len(drcs),
            "complete_drcs": len([d for d in drcs if d.get("is_complete")]),
            "total_pnl": round(sum(d.get("day_pnl", 0) for d in drcs), 2),
            "avg_daily_pnl": round(sum(d.get("day_pnl", 0) for d in drcs) / len(drcs), 2) if drcs else 0,
            "grade_distribution": grade_dist,
            "segment_performance": segment_avgs,
            "best_segment": {"id": best_seg[0], "avg_pnl": best_seg[1]} if best_seg else None,
            "worst_segment": {"id": worst_seg[0], "avg_pnl": worst_seg[1]} if worst_seg else None
        }
    
    async def update_checklist_settings(self, premarket: List[Dict] = None, postmarket: List[Dict] = None) -> Dict:
        """Update custom checklist settings"""
        settings = self.checklist_settings_col.find_one({"type": "settings"}) or {"type": "settings"}
        
        if premarket is not None:
            settings["premarket"] = premarket
        if postmarket is not None:
            settings["postmarket"] = postmarket
        
        settings["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self.checklist_settings_col.update_one(
            {"type": "settings"},
            {"$set": settings},
            upsert=True
        )
        
        return settings
    
    async def get_checklist_settings(self) -> Dict:
        """Get current checklist settings"""
        settings = self.checklist_settings_col.find_one({"type": "settings"})
        if settings:
            del settings["_id"]
            return settings
        return {
            "premarket": self.DEFAULT_PREMARKET_CHECKLIST,
            "postmarket": self.DEFAULT_POSTMARKET_CHECKLIST
        }
    
    async def generate_drc_summary(self, date: str) -> Dict:
        """
        AI-assisted: Generate a summary/analysis of the DRC
        Returns insights and suggestions based on the day's data
        """
        drc = await self.get_drc(date)
        if not drc:
            return {"error": "DRC not found for this date"}
        
        insights = []
        suggestions = []
        
        # Analyze trade performance
        trades = drc.get("trades_summary", {})
        if trades.get("total_trades", 0) > 0:
            win_rate = trades.get("win_rate", 0)
            if win_rate >= 60:
                insights.append(f"Strong win rate of {win_rate}% - your setups are working well")
            elif win_rate < 40:
                insights.append(f"Win rate of {win_rate}% suggests reviewing setup selection")
                suggestions.append("Consider reducing position sizes until win rate improves")
        
        # Analyze segment performance
        segments = drc.get("intraday_segments", [])
        segment_grades = {s["segment_id"]: s.get("grade", "") for s in segments}
        
        best_segment = None
        worst_segment = None
        for seg_id, grade in segment_grades.items():
            if grade in ["A+", "A", "A-"]:
                best_segment = seg_id
            elif grade in ["D", "F"]:
                worst_segment = seg_id
        
        if best_segment:
            insights.append(f"Best performance during {best_segment} session")
        if worst_segment:
            suggestions.append(f"Review what went wrong during {worst_segment} session")
        
        # Check checklist completion
        premarket = drc.get("premarket_checklist", [])
        premarket_complete = sum(1 for item in premarket if item.get("checked", False))
        premarket_total = len(premarket)
        
        if premarket_complete < premarket_total * 0.7:
            suggestions.append("Pre-market preparation was incomplete - complete all checklist items tomorrow")
        
        return {
            "date": date,
            "insights": insights,
            "suggestions": suggestions,
            "overall_assessment": drc.get("overall_grade", "Not graded"),
            "day_pnl": drc.get("day_pnl", 0)
        }


# Singleton instance
_drc_service: Optional[DRCService] = None

def get_drc_service(db=None) -> DRCService:
    """Get or create the DRC service singleton"""
    global _drc_service
    if _drc_service is None and db is not None:
        _drc_service = DRCService(db)
    return _drc_service
