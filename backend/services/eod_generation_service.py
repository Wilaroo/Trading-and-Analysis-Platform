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
import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)


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
        """Start the background scheduler for end-of-day tasks.
        Uses BackgroundScheduler (runs in its own thread) to avoid AsyncIO event loop issues.
        """
        if self.scheduler is None:
            self.scheduler = BackgroundScheduler(timezone=self.et_timezone)
            
            def _run_async(coro_func):
                """Wrapper to run async EOD functions from BackgroundScheduler's sync thread"""
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(coro_func())
                except Exception as e:
                    logger.error(f"EOD scheduler job failed: {e}")
                finally:
                    loop.close()
            
            # Schedule DRC generation at 4:30 PM ET on weekdays
            self.scheduler.add_job(
                lambda: _run_async(self.auto_generate_drc),
                CronTrigger(hour=16, minute=30, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_generate_drc',
                replace_existing=True
            )
            
            # Schedule Playbook analysis at 4:45 PM ET on weekdays
            self.scheduler.add_job(
                lambda: _run_async(self.auto_analyze_trades_for_playbooks),
                CronTrigger(hour=16, minute=45, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_playbook_analysis',
                replace_existing=True
            )
            
            # Schedule Self-Reflection at 5:00 PM ET — updates playbook learnings + DRC reflections
            self.scheduler.add_job(
                lambda: _run_async(self.auto_self_reflection),
                CronTrigger(hour=17, minute=0, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_self_reflection',
                replace_existing=True
            )

            # Weekend briefing — every Sunday at 14:00 ET. The
            # WeekendBriefingService aggregates last week's sector
            # returns + closed P&L, fetches Finnhub news / earnings /
            # macro / IPO calendars, and synthesizes the gameplan via
            # gpt-oss:120b-cloud. Idempotent within an ISO week.
            self.scheduler.add_job(
                lambda: _run_async(self._auto_generate_weekend_briefing),
                CronTrigger(hour=14, minute=0, day_of_week='sun', timezone=self.et_timezone),
                id='auto_generate_weekend_briefing',
                replace_existing=True
            )

            # Friday close snapshot — every Friday at 16:01 ET, capture
            # the closing price of each gameplan watch into
            # `friday_close_snapshots`. The Sunday briefing then surfaces
            # last week's per-watch P&L in the Last Week Recap section,
            # closing the feedback loop on whether the bot's weekly
            # thesis was right.
            self.scheduler.add_job(
                lambda: _run_async(self._auto_snapshot_friday_close),
                CronTrigger(hour=16, minute=1, day_of_week='fri', timezone=self.et_timezone),
                id='auto_snapshot_friday_close',
                replace_existing=True
            )

            # 2026-04-28e — Multiplier-threshold optimizer. Runs every
            # weekday at 18:00 ET (after EOD/playbook/reflection jobs
            # have finalised the day's bot_trades). Reads the last 30d
            # of cohort lift, proposes small (≤5% per night) bounded
            # adjustments to the smart-levels thresholds, and persists
            # them. Live trading picks up new values within ~5 min.
            def _run_threshold_optimizer():
                try:
                    from services.multiplier_threshold_optimizer import run_optimization
                    result = run_optimization(self.db, days_back=30, dry_run=False)
                    logger.info(
                        f"multiplier_threshold_optimizer: applied={result.get('applied')}, "
                        f"lifts={result.get('lifts')}, notes={result.get('notes')}"
                    )
                except Exception as e:
                    logger.error(f"multiplier_threshold_optimizer job failed: {e}")
            self.scheduler.add_job(
                _run_threshold_optimizer,
                CronTrigger(hour=18, minute=0, day_of_week='mon-fri', timezone=self.et_timezone),
                id='auto_multiplier_threshold_optimizer',
                replace_existing=True,
            )
            
            self.scheduler.start()
            logger.info("EOD generation scheduler started (BackgroundScheduler — 4:30/4:45/5:00 PM ET weekdays)")
    
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
                "$or": [
                    {"entry_time": {"$gte": date_start, "$lte": date_end}},
                    {"executed_at": {"$gte": date_start, "$lte": date_end}},
                ]
            }, {"_id": 0}))
            
            all_trades = manual_trades + bot_trades
            
            if not all_trades:
                self._log_generation("playbook_analysis", date, "skipped", "No trades for the day")
                return {"status": "skipped", "reason": "No trades"}
            
            # Filter winning trades (check both pnl and realized_pnl for bot trades)
            winning_trades = [t for t in all_trades if (t.get("pnl") or t.get("realized_pnl") or 0) > 0]
            
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
    
    async def _auto_generate_weekend_briefing(self) -> Dict:
        """Sunday 14:00 ET hook — kick off the WeekendBriefingService."""
        try:
            from services.weekend_briefing_service import get_weekend_briefing_service
            svc = get_weekend_briefing_service(self.db)
            if svc is None:
                print("[WeekendBriefing] Service not initialized — skipping cron")
                return {"success": False, "error": "service_not_initialized"}
            briefing = await svc.generate(force=False)
            print(
                f"[WeekendBriefing] Cron generated briefing for "
                f"{briefing.get('iso_week')} — gameplan_len="
                f"{len(briefing.get('gameplan') or '')}"
            )
            return {"success": True, "iso_week": briefing.get("iso_week")}
        except Exception as exc:
            print(f"[WeekendBriefing] Cron failed: {exc}")
            return {"success": False, "error": str(exc)}

    async def _auto_snapshot_friday_close(self) -> Dict:
        """Friday 16:01 ET hook — snapshot per-watch closes for grading."""
        try:
            from services.weekend_briefing_service import get_weekend_briefing_service
            svc = get_weekend_briefing_service(self.db)
            if svc is None:
                print("[FridayClose] Service not initialized — skipping cron")
                return {"success": False, "error": "service_not_initialized"}
            result = svc.snapshot_friday_close()
            print(
                f"[FridayClose] Cron persisted snapshot for "
                f"{result.get('iso_week')} — watches="
                f"{len(result.get('watches') or [])}"
            )
            return result
        except Exception as exc:
            print(f"[FridayClose] Cron failed: {exc}")
            return {"success": False, "error": str(exc)}


    async def auto_self_reflection(self, date: str = None) -> Dict:
        """
        Bot self-reflection — runs after-hours to analyze today's performance.
        
        Updates:
        1. Playbook "trade_review" sections with cumulative learnings
        2. DRC reflections (what went right/wrong, what to improve)
        3. Stores reflections in sentcom_memory for chat recall
        
        This is how the bot learns about ITSELF — not just patterns in data,
        but meta-learning about its own decision-making quality.
        """
        if date is None:
            date = datetime.now(self.et_timezone).strftime("%Y-%m-%d")
        
        print(f"[Self-Reflection] Running for {date}")
        
        try:
            date_start = f"{date}T00:00:00"
            date_end = f"{date}T23:59:59"
            
            # Get today's bot trades
            today_trades = list(self.bot_trades_col.find({
                "$or": [
                    {"executed_at": {"$gte": date_start, "$lte": date_end}},
                    {"closed_at": {"$gte": date_start, "$lte": date_end}},
                ]
            }, {"_id": 0}))
            
            if not today_trades:
                self._log_generation("self_reflection", date, "skipped", "No trades today")
                return {"status": "skipped", "reason": "No trades today"}
            
            # ── 1. Analyze performance by setup type with per-symbol + context breakdowns ──
            setup_stats = {}
            for trade in today_trades:
                setup = trade.get("setup_type", "unknown")
                symbol = trade.get("symbol", "?")
                pnl = trade.get("realized_pnl") or trade.get("pnl") or 0
                status = trade.get("status", "open")
                regime = trade.get("market_regime", "unknown")
                direction = trade.get("direction", "long")
                timeframe = trade.get("timeframe") or trade.get("trade_style", "")
                
                if setup not in setup_stats:
                    setup_stats[setup] = {
                        "trades": 0, "closed": 0, "wins": 0, "losses": 0, 
                        "total_pnl": 0, "reasons": [],
                        "by_symbol": {},    # Per-symbol tracking
                        "by_regime": {},    # Per-regime tracking
                        "by_direction": {"long": {"w": 0, "l": 0, "pnl": 0}, "short": {"w": 0, "l": 0, "pnl": 0}},
                    }
                
                ss = setup_stats[setup]
                ss["trades"] += 1
                
                # Per-symbol bucket
                if symbol not in ss["by_symbol"]:
                    ss["by_symbol"][symbol] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
                ss["by_symbol"][symbol]["trades"] += 1
                
                # Per-regime bucket
                if regime not in ss["by_regime"]:
                    ss["by_regime"][regime] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
                ss["by_regime"][regime]["trades"] += 1
                
                if status == "closed":
                    ss["closed"] += 1
                    won = pnl > 0
                    if won:
                        ss["wins"] += 1
                        ss["by_symbol"][symbol]["wins"] += 1
                        ss["by_regime"][regime]["wins"] += 1
                        ss["by_direction"][direction]["w"] += 1
                    elif pnl < 0:
                        ss["losses"] += 1
                        ss["by_symbol"][symbol]["losses"] += 1
                        ss["by_regime"][regime]["losses"] += 1
                        ss["by_direction"][direction]["l"] += 1
                    
                    ss["total_pnl"] += pnl
                    ss["by_symbol"][symbol]["pnl"] += pnl
                    ss["by_regime"][regime]["pnl"] += pnl
                    ss["by_direction"][direction]["pnl"] += pnl
                
                close_reason = trade.get("close_reason", "")
                if close_reason:
                    ss["reasons"].append(close_reason)
            
            # ── 2. Update playbook learnings for each setup ──
            playbook_updates = []
            for setup_type, stats in setup_stats.items():
                if stats["closed"] == 0:
                    continue
                
                wr = (stats["wins"] / stats["closed"] * 100) if stats["closed"] > 0 else 0
                avg_pnl = stats["total_pnl"] / stats["closed"] if stats["closed"] > 0 else 0
                
                # Build learning text
                learned = f"[{date}] {stats['closed']} trades, {stats['wins']}W/{stats['losses']}L ({wr:.0f}% WR), ${stats['total_pnl']:+,.0f} net."
                
                # Analyze close reasons
                stop_outs = sum(1 for r in stats["reasons"] if "stop" in r.lower())
                target_hits = sum(1 for r in stats["reasons"] if "target" in r.lower() or "profit" in r.lower())
                eod_closes = sum(1 for r in stats["reasons"] if "eod" in r.lower() or "end_of_day" in r.lower())
                
                if stop_outs > stats["closed"] * 0.5:
                    learned += f" {stop_outs} stop-outs — stops may be too tight or entries poorly timed."
                if target_hits > stats["closed"] * 0.5:
                    learned += f" {target_hits} target hits — execution working well."
                if eod_closes > 0:
                    learned += f" {eod_closes} EOD auto-closes — consider wider timeframe if trades need more time."
                
                # Build improvement text
                improvement = ""
                if wr < 40:
                    improvement = f"Win rate below 40% — review entry criteria. Are we entering too early? Is the setup confirmation clear enough?"
                elif wr < 50 and avg_pnl < 0:
                    improvement = f"Below 50% WR with negative avg P&L — consider tighter position sizing or stricter confidence gate threshold for {setup_type}."
                elif wr >= 60:
                    improvement = f"Strong {wr:.0f}% WR — this setup is working. Consider increasing size or loosening trail for bigger R."
                elif stop_outs > target_hits:
                    improvement = f"More stop-outs than target hits — stops may be too tight. Try widening by 0.5 ATR."
                else:
                    improvement = f"Adequate performance. Monitor for consistency over the next week."
                
                # Update the playbook if it exists
                try:
                    playbook = self.playbooks_col.find_one(
                        {"setup_type": {"$regex": setup_type, "$options": "i"}}
                    )
                    if playbook:
                        existing_review = playbook.get("trade_review", {})
                        history = existing_review.get("daily_reflections", [])
                        history.append({
                            "date": date,
                            "trades": stats["closed"],
                            "win_rate": wr,
                            "pnl": stats["total_pnl"],
                            "learned": learned,
                            "improvement": improvement,
                        })
                        # Keep last 30 days of reflections
                        history = history[-30:]
                        
                        # Build cumulative learning from recent reflections
                        recent_wrs = [h["win_rate"] for h in history[-7:]]
                        avg_recent_wr = sum(recent_wrs) / len(recent_wrs) if recent_wrs else 0
                        trend = "improving" if len(recent_wrs) >= 3 and recent_wrs[-1] > recent_wrs[0] else "declining" if len(recent_wrs) >= 3 and recent_wrs[-1] < recent_wrs[0] else "stable"
                        
                        cumulative = f"7-day avg WR: {avg_recent_wr:.0f}% ({trend}). "
                        cumulative += f"Total reflections: {len(history)} days."
                        
                        # ── Per-symbol cumulative stats (merge today into historical) ──
                        symbol_stats = existing_review.get("symbol_breakdown", {})
                        for sym, sym_data in stats["by_symbol"].items():
                            if sym not in symbol_stats:
                                symbol_stats[sym] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
                            symbol_stats[sym]["trades"] += sym_data["trades"]
                            symbol_stats[sym]["wins"] += sym_data["wins"]
                            symbol_stats[sym]["losses"] += sym_data["losses"]
                            symbol_stats[sym]["pnl"] += sym_data["pnl"]
                        
                        # ── Per-regime cumulative stats ──
                        regime_stats = existing_review.get("regime_breakdown", {})
                        for reg, reg_data in stats["by_regime"].items():
                            if reg not in regime_stats:
                                regime_stats[reg] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
                            regime_stats[reg]["trades"] += reg_data["trades"]
                            regime_stats[reg]["wins"] += reg_data["wins"]
                            regime_stats[reg]["losses"] += reg_data["losses"]
                            regime_stats[reg]["pnl"] += reg_data["pnl"]
                        
                        # ── Per-direction cumulative stats ──
                        dir_stats = existing_review.get("direction_breakdown", {
                            "long": {"w": 0, "l": 0, "pnl": 0},
                            "short": {"w": 0, "l": 0, "pnl": 0}
                        })
                        for d in ("long", "short"):
                            dir_stats[d]["w"] += stats["by_direction"][d]["w"]
                            dir_stats[d]["l"] += stats["by_direction"][d]["l"]
                            dir_stats[d]["pnl"] += stats["by_direction"][d]["pnl"]
                        
                        # ── Find weak spots (symbols/regimes that underperform) ──
                        weak_symbols = []
                        for sym, sd in symbol_stats.items():
                            if sd["trades"] >= 3:
                                sym_wr = (sd["wins"] / sd["trades"] * 100) if sd["trades"] > 0 else 0
                                if sym_wr < 35 or sd["pnl"] < -500:
                                    weak_symbols.append(f"{sym} ({sd['trades']}t, {sym_wr:.0f}%WR, ${sd['pnl']:+,.0f})")
                        
                        weak_regimes = []
                        for reg, rd in regime_stats.items():
                            if rd["trades"] >= 3:
                                reg_wr = (rd["wins"] / rd["trades"] * 100) if rd["trades"] > 0 else 0
                                if reg_wr < 35:
                                    weak_regimes.append(f"{reg} ({rd['trades']}t, {reg_wr:.0f}%WR)")
                        
                        edge_notes = ""
                        if weak_symbols:
                            edge_notes += f"Weak symbols: {', '.join(weak_symbols[:5])}. "
                        if weak_regimes:
                            edge_notes += f"Weak regimes: {', '.join(weak_regimes[:3])}. "
                        
                        self.playbooks_col.update_one(
                            {"_id": playbook["_id"]},
                            {"$set": {
                                "trade_review.what_did_i_learn": learned,
                                "trade_review.how_could_i_do_better": improvement,
                                "trade_review.what_would_i_do_differently": improvement,
                                "trade_review.historical_performance": cumulative,
                                "trade_review.daily_reflections": history,
                                "trade_review.symbol_breakdown": symbol_stats,
                                "trade_review.regime_breakdown": regime_stats,
                                "trade_review.direction_breakdown": dir_stats,
                                "trade_review.edge_notes": edge_notes,
                                "trade_review.last_updated": date,
                            }}
                        )
                        playbook_updates.append(setup_type)
                except Exception as e:
                    print(f"Playbook update error for {setup_type}: {e}")
            
            # ── 3. Update DRC reflections ──
            total_trades = len(today_trades)
            closed_trades = [t for t in today_trades if t.get("status") == "closed"]
            total_pnl = sum(t.get("realized_pnl") or t.get("pnl") or 0 for t in closed_trades)
            total_wins = sum(1 for t in closed_trades if (t.get("realized_pnl") or t.get("pnl") or 0) > 0)
            total_losses = sum(1 for t in closed_trades if (t.get("realized_pnl") or t.get("pnl") or 0) < 0)
            overall_wr = (total_wins / len(closed_trades) * 100) if closed_trades else 0
            
            # Best and worst trades
            sorted_by_pnl = sorted(closed_trades, key=lambda t: t.get("realized_pnl") or t.get("pnl") or 0)
            worst = sorted_by_pnl[0] if sorted_by_pnl else None
            best = sorted_by_pnl[-1] if sorted_by_pnl else None
            
            reflection_text = f"Today: {len(closed_trades)} closed trades, {total_wins}W/{total_losses}L ({overall_wr:.0f}% WR), ${total_pnl:+,.0f} net P&L.\n"
            if best:
                reflection_text += f"Best: {best.get('symbol')} {best.get('setup_type')} +${(best.get('realized_pnl') or 0):,.0f}.\n"
            if worst:
                reflection_text += f"Worst: {worst.get('symbol')} {worst.get('setup_type')} ${(worst.get('realized_pnl') or 0):,.0f}.\n"
            
            # What went right
            went_right = []
            if overall_wr >= 50:
                went_right.append(f"Above 50% win rate ({overall_wr:.0f}%)")
            if total_pnl > 0:
                went_right.append(f"Positive P&L (${total_pnl:+,.0f})")
            for setup, stats in setup_stats.items():
                if stats["closed"] > 0 and (stats["wins"] / stats["closed"]) > 0.6:
                    went_right.append(f"{setup} had {stats['wins']}/{stats['closed']} wins")
            
            # What went wrong
            went_wrong = []
            if overall_wr < 40:
                went_wrong.append(f"Low win rate ({overall_wr:.0f}%) — review entry timing")
            if total_pnl < 0:
                went_wrong.append(f"Negative P&L — losses exceeded wins in magnitude")
            for setup, stats in setup_stats.items():
                if stats["closed"] > 0 and (stats["wins"] / stats["closed"]) < 0.3:
                    went_wrong.append(f"{setup} only {stats['wins']}/{stats['closed']} wins — needs attention")
            
            # What to improve
            improvements = []
            all_reasons = []
            for s in setup_stats.values():
                all_reasons.extend(s["reasons"])
            stop_outs_total = sum(1 for r in all_reasons if "stop" in r.lower())
            if stop_outs_total > len(closed_trades) * 0.4:
                improvements.append("Too many stop-outs — review stop placement or entry quality")
            if len(closed_trades) > 10:
                improvements.append("High trade count — consider being more selective with entries")
            if not improvements:
                improvements.append("Continue executing the plan. Monitor for consistency.")
            
            drc_reflections = {
                "summary": reflection_text,
                "what_went_right": went_right,
                "what_went_wrong": went_wrong,
                "what_to_improve": improvements,
                "setup_breakdowns": {k: {
                    "trades": v["closed"], "wr": f"{(v['wins']/v['closed']*100) if v['closed'] else 0:.0f}%",
                    "pnl": f"${v['total_pnl']:+,.0f}"
                } for k, v in setup_stats.items() if v["closed"] > 0},
                "auto_generated": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # Update or create DRC with reflections
            existing_drc = self.drc_col.find_one({"date": date})
            if existing_drc:
                self.drc_col.update_one(
                    {"date": date},
                    {"$set": {
                        "reflections": drc_reflections,
                        "self_reflection_complete": True,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
            else:
                self.drc_col.insert_one({
                    "date": date,
                    "reflections": drc_reflections,
                    "self_reflection_complete": True,
                    "auto_generated": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            
            # ── 4. Store key learnings in sentcom_memory for chat recall ──
            memory_db = self.db["sentcom_memory"]
            if total_pnl != 0 or len(closed_trades) > 0:
                memory_content = f"[Self-reflection {date}] {reflection_text.strip()}"
                if went_wrong:
                    memory_content += f" Issues: {'; '.join(went_wrong[:2])}."
                if improvements:
                    memory_content += f" Action: {improvements[0]}."
                
                # Only store if meaningful (had trades)
                memory_db.insert_one({
                    "content": memory_content[:400],
                    "category": "self_reflection",
                    "source_user_msg": "auto_eod_reflection",
                    "session_id": f"eod_{date}",
                    "active": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            
            result = {
                "status": "success",
                "date": date,
                "trades_analyzed": len(closed_trades),
                "playbooks_updated": playbook_updates,
                "drc_reflections": bool(drc_reflections),
                "memory_stored": True,
            }
            
            self._log_generation("self_reflection", date, "success", 
                                f"{len(closed_trades)} trades, {len(playbook_updates)} playbooks updated, PnL: ${total_pnl:+,.0f}")
            
            print(f"[Self-Reflection] Complete: {len(closed_trades)} trades analyzed, {len(playbook_updates)} playbooks updated")
            return result
            
        except Exception as e:
            self._log_generation("self_reflection", date, "error", str(e))
            print(f"[Self-Reflection] Error: {e}")
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
        reflection_result = await self.auto_self_reflection(date)
        
        return {
            "drc": drc_result,
            "playbook_analysis": playbook_result,
            "self_reflection": reflection_result,
        }


# Singleton instance
_eod_service: Optional[EndOfDayGenerationService] = None

def get_eod_service(db=None) -> EndOfDayGenerationService:
    global _eod_service
    if _eod_service is None and db is not None:
        _eod_service = EndOfDayGenerationService(db)
    return _eod_service
