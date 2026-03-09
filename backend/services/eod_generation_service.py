"""
End of Day Auto-Generation Service
Automatically generates DRC and Playbook entries at market close

Runs at:
- 4:30 PM ET - Generate DRC for the day
- 4:45 PM ET - Analyze trades and suggest playbook entries
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import asyncio
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz


class EndOfDayGenerationService:
    """Service for automatic end-of-day DRC and Playbook generation"""
    
    def __init__(self, db):
        self.db = db
        self.scheduler = None
        self.et_timezone = pytz.timezone('America/New_York')
        
        # Collections
        self.drc_col = db["daily_report_cards"]
        self.playbooks_col = db["playbooks"]
        self.trades_col = db["trades"]
        self.bot_trades_col = db["bot_trades"]
        self.eod_log_col = db["eod_generation_log"]
        
        # Create index for logs
        self.eod_log_col.create_index([("date", -1)])
        self.eod_log_col.create_index([("type", 1), ("date", -1)])
    
    def start_scheduler(self):
        """Start the background scheduler for end-of-day tasks"""
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler(timezone=self.et_timezone)
            
            # Schedule DRC generation at 4:30 PM ET on weekdays
            self.scheduler.add_job(
                self.auto_generate_drc,
                CronTrigger(hour=16, minute=30, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_generate_drc',
                replace_existing=True
            )
            
            # Schedule Playbook analysis at 4:45 PM ET on weekdays
            self.scheduler.add_job(
                self.auto_analyze_trades_for_playbooks,
                CronTrigger(hour=16, minute=45, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_playbook_analysis',
                replace_existing=True
            )
            
            self.scheduler.start()
            print("End-of-day generation scheduler started")
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        if self.scheduler:
            self.scheduler.shutdown()
            self.scheduler = None
    
    async def auto_generate_drc(self, date: str = None) -> Dict:
        """
        Automatically generate DRC at end of day
        Called by scheduler or can be triggered manually
        """
        if date is None:
            date = datetime.now(self.et_timezone).strftime("%Y-%m-%d")
        
        print(f"Auto-generating DRC for {date}")
        
        try:
            # Import AI service
            from services.ai_journal_generation_service import get_ai_journal_service
            ai_service = get_ai_journal_service(self.db)
            
            # Check if DRC already exists and is complete
            existing_drc = self.drc_col.find_one({"date": date})
            if existing_drc and existing_drc.get("is_complete"):
                self._log_generation("drc", date, "skipped", "DRC already complete")
                return {"status": "skipped", "reason": "DRC already complete"}
            
            # Generate AI content
            ai_content = await ai_service.generate_drc_content(date)
            
            if existing_drc:
                # Update existing DRC with AI content
                update_data = {
                    "overall_grade": ai_content.get("overall_grade") or existing_drc.get("overall_grade", ""),
                    "day_pnl": ai_content.get("day_pnl", existing_drc.get("day_pnl", 0)),
                    "trades_summary": ai_content.get("trades_summary", existing_drc.get("trades_summary", {})),
                    "intraday_segments": ai_content.get("intraday_segments", existing_drc.get("intraday_segments", [])),
                    "reflections": {
                        **existing_drc.get("reflections", {}),
                        **ai_content.get("reflections", {})
                    },
                    "auto_generated": True,
                    "auto_generated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                
                self.drc_col.update_one({"date": date}, {"$set": update_data})
            else:
                # Create new DRC
                from services.drc_service import get_drc_service
                drc_service = get_drc_service(self.db)
                await drc_service.create_drc(date=date, auto_populate=True)
                
                # Update with AI content
                self.drc_col.update_one(
                    {"date": date},
                    {"$set": {
                        **ai_content,
                        "auto_generated": True,
                        "auto_generated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
            
            self._log_generation("drc", date, "success", f"Generated DRC with grade {ai_content.get('overall_grade', 'N/A')}")
            
            return {
                "status": "success",
                "date": date,
                "grade": ai_content.get("overall_grade"),
                "pnl": ai_content.get("day_pnl")
            }
            
        except Exception as e:
            self._log_generation("drc", date, "error", str(e))
            return {"status": "error", "error": str(e)}
    
    async def auto_analyze_trades_for_playbooks(self, date: str = None) -> Dict:
        """
        Automatically analyze day's trades for potential playbook entries
        Called by scheduler or can be triggered manually
        """
        if date is None:
            date = datetime.now(self.et_timezone).strftime("%Y-%m-%d")
        
        print(f"Auto-analyzing trades for playbooks on {date}")
        
        try:
            # Get day's trades
            date_start = f"{date}T00:00:00"
            date_end = f"{date}T23:59:59"
            
            manual_trades = list(self.trades_col.find({
                "entry_date": {"$gte": date_start, "$lte": date_end}
            }, {"_id": 0}))
            
            bot_trades = list(self.bot_trades_col.find({
                "entry_time": {"$gte": date_start, "$lte": date_end}
            }, {"_id": 0}))
            
            all_trades = manual_trades + bot_trades
            
            if not all_trades:
                self._log_generation("playbook_analysis", date, "skipped", "No trades for the day")
                return {"status": "skipped", "reason": "No trades"}
            
            # Filter winning trades
            winning_trades = [t for t in all_trades if (t.get("pnl") or 0) > 0]
            
            if not winning_trades:
                self._log_generation("playbook_analysis", date, "skipped", "No winning trades")
                return {"status": "skipped", "reason": "No winning trades"}
            
            # Group by setup type
            setup_groups = {}
            for trade in winning_trades:
                setup = trade.get("setup_type") or trade.get("strategy_name") or "Unknown"
                if setup not in setup_groups:
                    setup_groups[setup] = []
                setup_groups[setup].append(trade)
            
            # Generate playbook suggestions for setups with good trades
            suggestions = []
            
            from services.ai_journal_generation_service import get_ai_journal_service
            ai_service = get_ai_journal_service(self.db)
            
            for setup_type, trades in setup_groups.items():
                if setup_type == "Unknown":
                    continue
                
                # Check if playbook already exists for this setup
                existing = self.playbooks_col.find_one({"setup_type": setup_type})
                
                if existing:
                    # Log trade to existing playbook
                    suggestions.append({
                        "setup_type": setup_type,
                        "action": "logged_to_existing",
                        "playbook_name": existing.get("name"),
                        "trades_count": len(trades)
                    })
                else:
                    # Generate new playbook suggestion
                    playbook_data = await ai_service.generate_playbook_from_trades(trades, setup_type)
                    
                    # Save as pending playbook (not active until reviewed)
                    playbook_data["status"] = "pending_review"
                    playbook_data["auto_generated"] = True
                    playbook_data["auto_generated_at"] = datetime.now(timezone.utc).isoformat()
                    playbook_data["source_date"] = date
                    playbook_data["is_active"] = False  # Needs review
                    
                    # Store in pending playbooks collection
                    pending_col = self.db["pending_playbooks"]
                    pending_col.insert_one(playbook_data)
                    
                    suggestions.append({
                        "setup_type": setup_type,
                        "action": "new_suggestion",
                        "playbook_name": playbook_data.get("name"),
                        "trades_count": len(trades)
                    })
            
            self._log_generation(
                "playbook_analysis", 
                date, 
                "success", 
                f"Analyzed {len(winning_trades)} trades, {len(suggestions)} suggestions"
            )
            
            return {
                "status": "success",
                "date": date,
                "total_trades": len(all_trades),
                "winning_trades": len(winning_trades),
                "suggestions": suggestions
            }
            
        except Exception as e:
            self._log_generation("playbook_analysis", date, "error", str(e))
            return {"status": "error", "error": str(e)}
    
    def _log_generation(self, gen_type: str, date: str, status: str, message: str):
        """Log generation activity"""
        self.eod_log_col.insert_one({
            "type": gen_type,
            "date": date,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    async def get_pending_playbooks(self) -> List[Dict]:
        """Get playbooks pending review"""
        pending_col = self.db["pending_playbooks"]
        playbooks = list(pending_col.find(
            {"status": "pending_review"},
            {"_id": 0}
        ).sort("auto_generated_at", -1))
        
        # Add IDs
        for pb in playbooks:
            doc = pending_col.find_one({"name": pb.get("name")})
            if doc:
                pb["id"] = str(doc["_id"])
        
        return playbooks
    
    async def approve_pending_playbook(self, playbook_id: str) -> Dict:
        """Approve a pending playbook and make it active"""
        from bson import ObjectId
        
        pending_col = self.db["pending_playbooks"]
        playbook = pending_col.find_one({"_id": ObjectId(playbook_id)})
        
        if not playbook:
            return {"error": "Playbook not found"}
        
        # Remove MongoDB ID and status fields
        del playbook["_id"]
        playbook["status"] = "active"
        playbook["is_active"] = True
        playbook["approved_at"] = datetime.now(timezone.utc).isoformat()
        
        # Insert into main playbooks collection
        self.playbooks_col.insert_one(playbook)
        
        # Remove from pending
        pending_col.delete_one({"_id": ObjectId(playbook_id)})
        
        return {"success": True, "playbook": {k: v for k, v in playbook.items() if k != "_id"}}
    
    async def reject_pending_playbook(self, playbook_id: str) -> Dict:
        """Reject/delete a pending playbook"""
        from bson import ObjectId
        
        pending_col = self.db["pending_playbooks"]
        result = pending_col.delete_one({"_id": ObjectId(playbook_id)})
        
        return {"success": result.deleted_count > 0}
    
    async def get_generation_logs(self, days: int = 7) -> List[Dict]:
        """Get recent generation logs"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        logs = list(self.eod_log_col.find(
            {"timestamp": {"$gte": cutoff}},
            {"_id": 0}
        ).sort("timestamp", -1))
        
        return logs
    
    async def trigger_manual_generation(self, date: str = None) -> Dict:
        """Manually trigger end-of-day generation"""
        drc_result = await self.auto_generate_drc(date)
        playbook_result = await self.auto_analyze_trades_for_playbooks(date)
        
        return {
            "drc": drc_result,
            "playbook_analysis": playbook_result
        }


# Singleton instance
_eod_service: Optional[EndOfDayGenerationService] = None

def get_eod_service(db=None) -> EndOfDayGenerationService:
    global _eod_service
    if _eod_service is None and db is not None:
        _eod_service = EndOfDayGenerationService(db)
    return _eod_service
