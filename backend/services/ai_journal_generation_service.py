"""
AI Generation Service for Playbooks and DRC
Uses LLM to auto-generate playbook entries and DRC content
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List
import os
import json


class AIJournalGenerationService:
    """Service for AI-assisted generation of playbooks and DRC content"""
    
    def __init__(self, db):
        self.db = db
        self.playbooks_col = db["playbooks"]
        self.drc_col = db["daily_report_cards"]
        self.trades_col = db["trades"]
        self.bot_trades_col = db["bot_trades"]
        self.imported_trades_col = db["tradersync_imports"]
        self.market_intel_col = db.get_collection("market_intel")
        self.alerts_col = db.get_collection("live_alerts")
        
        # Initialize LLM client
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM client for AI generation"""
        try:
            from emergentintegrations.llm.chat import ChatSession, ChatModel
            api_key = os.environ.get("EMERGENT_LLM_KEY") or os.environ.get("EMERGENT_API_KEY")
            if api_key:
                self.chat_session = ChatSession(api_key=api_key, model=ChatModel.GPT_4O)
                self.llm_available = True
            else:
                self.llm_available = False
                self.chat_session = None
        except Exception as e:
            print(f"Failed to initialize LLM: {e}")
            self.llm_available = False
            self.chat_session = None
    
    async def generate_playbook_from_trades(self, trades: List[Dict], setup_type: str = None) -> Dict:
        """
        Generate a playbook entry from a list of similar trades
        
        Uses AI to analyze the trades and extract:
        - Common patterns and characteristics
        - Entry/exit triggers that worked
        - Risk management rules
        - IF/THEN statements
        """
        if not trades:
            return {"error": "No trades provided"}
        
        # Prepare trade summary for AI
        trade_summaries = []
        for t in trades[:10]:  # Limit to 10 trades for context
            summary = {
                "symbol": t.get("symbol"),
                "date": t.get("trade_date") or t.get("entry_date"),
                "direction": t.get("direction", "long"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "pnl": t.get("pnl"),
                "r_multiple": t.get("r_multiple"),
                "setup_type": t.get("setup_type") or setup_type,
                "notes": t.get("notes", ""),
                "tags": t.get("tags", [])
            }
            trade_summaries.append(summary)
        
        # Calculate aggregate stats
        total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
        winners = len([t for t in trades if (t.get("pnl", 0) or 0) > 0])
        win_rate = round(winners / len(trades) * 100, 1) if trades else 0
        avg_r = sum(t.get("r_multiple", 0) or 0 for t in trades if t.get("r_multiple")) / len([t for t in trades if t.get("r_multiple")]) if any(t.get("r_multiple") for t in trades) else 0
        
        # If no LLM available, generate template-based playbook
        if not self.llm_available:
            return self._generate_template_playbook(trades, setup_type, {
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "avg_r": avg_r
            })
        
        # Generate with AI
        prompt = f"""Analyze these {len(trades)} winning trades and create a detailed SMB-style playbook entry.

TRADES DATA:
{json.dumps(trade_summaries, indent=2)}

AGGREGATE STATS:
- Total P&L: ${total_pnl:.2f}
- Win Rate: {win_rate}%
- Average R Multiple: {avg_r:.2f}

Generate a playbook with these sections:

1. BIGGER PICTURE
- What market conditions were present?
- How did these trades relate to SPY/QQQ action?

2. INTRADAY FUNDAMENTALS
- What catalysts drove these trades?
- Why were these stocks in play?

3. TECHNICAL ANALYSIS
- What chart patterns were common?
- Key technical levels that mattered?

4. READING THE TAPE
- What tape signals confirmed entries?
- Was the tape clean or choppy?

5. TRADE MANAGEMENT
- Optimal entry triggers
- Stop placement rules
- Profit target levels
- Scaling strategy

6. IF/THEN STATEMENTS (3 rules)
- IF [condition] THEN [action]

Respond in JSON format with this structure:
{{
  "name": "Descriptive playbook name",
  "setup_type": "{setup_type or 'extracted from trades'}",
  "trade_style": "M2M or T2H or A+",
  "bigger_picture": {{
    "market_context": "",
    "trade_rationale": ""
  }},
  "intraday_fundamentals": {{
    "catalyst_type": "",
    "why_in_play": ""
  }},
  "technical_analysis": {{
    "chart_pattern": "",
    "vwap_position": "",
    "chart_markup_notes": ""
  }},
  "reading_the_tape": {{
    "clean_or_choppy": "",
    "key_tape_signals": ""
  }},
  "trade_management": {{
    "entry_trigger": "",
    "initial_stop": "",
    "profit_target_1": "",
    "profit_target_2": "",
    "scaling_rules": ""
  }},
  "trade_review": {{
    "what_to_look_for": "",
    "common_mistakes": ""
  }},
  "if_then_statements": [
    {{"condition": "", "action": "", "notes": ""}},
    {{"condition": "", "action": "", "notes": ""}},
    {{"condition": "", "action": "", "notes": ""}}
  ],
  "description": ""
}}"""
        
        try:
            response = await self.chat_session.send_async(prompt)
            
            # Parse JSON response
            response_text = response.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            playbook_data = json.loads(response_text.strip())
            playbook_data["source"] = "ai_generated"
            playbook_data["generated_from_trades"] = len(trades)
            playbook_data["performance_stats"] = {
                "total_pnl": round(total_pnl, 2),
                "win_rate": win_rate,
                "avg_r_multiple": round(avg_r, 2)
            }
            
            return playbook_data
            
        except Exception as e:
            print(f"AI generation failed: {e}")
            return self._generate_template_playbook(trades, setup_type, {
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "avg_r": avg_r
            })
    
    def _generate_template_playbook(self, trades: List[Dict], setup_type: str, stats: Dict) -> Dict:
        """Generate a template-based playbook when AI is not available"""
        symbols = list(set(t.get("symbol", "") for t in trades))
        directions = [t.get("direction", "long") for t in trades]
        primary_direction = "long" if directions.count("long") >= directions.count("short") else "short"
        
        return {
            "name": f"{setup_type or 'Custom'} Playbook - {', '.join(symbols[:3])}",
            "setup_type": setup_type or "Custom Setup",
            "trade_style": "M2M",
            "source": "template_generated",
            "generated_from_trades": len(trades),
            "performance_stats": stats,
            
            "bigger_picture": {
                "market_context": "Review market conditions during these trades",
                "trade_rationale": f"Profitable {primary_direction} setup with {stats['win_rate']}% win rate"
            },
            
            "intraday_fundamentals": {
                "catalyst_type": "Review trade notes for catalysts",
                "why_in_play": f"Traded symbols: {', '.join(symbols[:5])}"
            },
            
            "technical_analysis": {
                "chart_pattern": setup_type or "Define the chart pattern",
                "vwap_position": "Above/Below VWAP",
                "chart_markup_notes": "Add key level observations"
            },
            
            "reading_the_tape": {
                "clean_or_choppy": "Review tape during trades",
                "key_tape_signals": "Document confirmation signals"
            },
            
            "trade_management": {
                "entry_trigger": "Define entry trigger based on winning trades",
                "initial_stop": "Define stop based on trade data",
                "profit_target_1": "1R target",
                "profit_target_2": "2R target",
                "scaling_rules": "Scale 50% at T1, let rest ride"
            },
            
            "trade_review": {
                "what_to_look_for": "Key patterns from winning trades",
                "common_mistakes": "Document common errors to avoid"
            },
            
            "if_then_statements": [
                {"condition": f"IF setup type is {setup_type}", "action": f"THEN look for {primary_direction} entry", "notes": ""},
                {"condition": "IF price reaches target", "action": "THEN scale out", "notes": ""},
                {"condition": "IF stop is hit", "action": "THEN exit position", "notes": "Honor the stop"}
            ],
            
            "description": f"Auto-generated from {len(trades)} trades with ${stats['total_pnl']:.0f} total P&L"
        }
    
    async def generate_drc_content(self, date: str) -> Dict:
        """
        Auto-generate DRC content for a given date
        
        Pulls data from:
        - Day's trades (bot trades and manual trades)
        - Market intel
        - Scanner alerts
        """
        # Get trades for the date
        date_start = f"{date}T00:00:00"
        date_end = f"{date}T23:59:59"
        
        # Manual trades
        manual_trades = list(self.trades_col.find({
            "entry_date": {"$gte": date_start, "$lte": date_end}
        }, {"_id": 0}))
        
        # Bot trades
        bot_trades = list(self.bot_trades_col.find({
            "entry_time": {"$gte": date_start, "$lte": date_end}
        }, {"_id": 0}))
        
        all_trades = manual_trades + bot_trades
        
        # Calculate trade stats
        total_trades = len(all_trades)
        closed_trades = [t for t in all_trades if t.get("status") == "closed" or t.get("pnl") is not None]
        winners = len([t for t in closed_trades if (t.get("pnl") or 0) > 0])
        losers = len([t for t in closed_trades if (t.get("pnl") or 0) < 0])
        total_pnl = sum(t.get("pnl", 0) or 0 for t in closed_trades)
        win_rate = round(winners / len(closed_trades) * 100, 1) if closed_trades else 0
        
        # Find biggest winner/loser
        pnls = [(t.get("symbol", ""), t.get("pnl", 0) or 0) for t in closed_trades]
        biggest_winner = max(pnls, key=lambda x: x[1]) if pnls else None
        biggest_loser = min(pnls, key=lambda x: x[1]) if pnls else None
        
        # Get market intel
        market_context = {}
        if self.market_intel_col is not None:
            try:
                market_data = self.market_intel_col.find_one(
                    {"date": {"$regex": f"^{date}"}},
                    {"_id": 0}
                )
                if market_data:
                    market_context = {
                        "market_regime": market_data.get("regime", ""),
                        "market_sentiment": market_data.get("sentiment", ""),
                        "vix_level": market_data.get("vix", None)
                    }
            except Exception:
                pass
        
        # Group trades by time segment
        segments = {
            "morning": {"start": 7.5, "end": 11, "trades": [], "pnl": 0},
            "midday": {"start": 11, "end": 14, "trades": [], "pnl": 0},
            "afternoon": {"start": 14, "end": 16.5, "trades": [], "pnl": 0}
        }
        
        for trade in closed_trades:
            trade_time = trade.get("entry_time") or trade.get("entry_date", "")
            try:
                if "T" in trade_time:
                    hour = int(trade_time.split("T")[1].split(":")[0])
                    minute = int(trade_time.split("T")[1].split(":")[1])
                    decimal_hour = hour + minute / 60
                    
                    for seg_id, seg in segments.items():
                        if seg["start"] <= decimal_hour < seg["end"]:
                            seg["trades"].append(trade)
                            seg["pnl"] += trade.get("pnl", 0) or 0
                            break
            except Exception:
                pass
        
        # Generate segment grades based on P&L
        def get_segment_grade(pnl, trade_count):
            if trade_count == 0:
                return ""
            if pnl > 500:
                return "A"
            elif pnl > 200:
                return "B+"
            elif pnl > 0:
                return "B"
            elif pnl > -100:
                return "C"
            elif pnl > -300:
                return "D"
            else:
                return "F"
        
        # If AI available, generate reflections
        reflections = {
            "what_i_learned": "",
            "easiest_3k_trade": "",
            "changes_for_tomorrow": ""
        }
        
        if self.llm_available and total_trades > 0:
            try:
                prompt = f"""Based on today's trading activity, generate brief DRC reflections:

TRADING SUMMARY:
- Total Trades: {total_trades}
- Winners: {winners}, Losers: {losers}
- Win Rate: {win_rate}%
- Total P&L: ${total_pnl:.2f}
- Biggest Winner: {biggest_winner[0] if biggest_winner else 'N/A'} (${biggest_winner[1]:.2f if biggest_winner else 0})
- Biggest Loser: {biggest_loser[0] if biggest_loser else 'N/A'} (${biggest_loser[1]:.2f if biggest_loser else 0})

Generate JSON with these fields (keep each under 100 words):
{{
  "what_i_learned": "Key lesson from today",
  "easiest_3k_trade": "The most obvious high-probability trade today (even if missed)",
  "changes_for_tomorrow": "What to do differently tomorrow"
}}"""
                
                response = await self.chat_session.send_async(prompt)
                response_text = response.strip()
                if "```" in response_text:
                    response_text = response_text.split("```")[1].replace("json", "").strip()
                reflections = json.loads(response_text)
            except Exception:
                pass
        
        # Build DRC content
        drc_content = {
            "date": date,
            "overall_grade": self._calculate_overall_grade(total_pnl, win_rate, total_trades),
            "day_pnl": round(total_pnl, 2),
            
            "trades_summary": {
                "total_trades": total_trades,
                "winning_trades": winners,
                "losing_trades": losers,
                "win_rate": win_rate,
                "biggest_winner": {"symbol": biggest_winner[0], "pnl": round(biggest_winner[1], 2)} if biggest_winner and biggest_winner[1] > 0 else None,
                "biggest_loser": {"symbol": biggest_loser[0], "pnl": round(biggest_loser[1], 2)} if biggest_loser and biggest_loser[1] < 0 else None,
                "trades": [
                    {
                        "symbol": t.get("symbol"),
                        "direction": t.get("direction"),
                        "pnl": t.get("pnl"),
                        "setup_type": t.get("setup_type") or t.get("strategy_name")
                    }
                    for t in all_trades[:20]
                ]
            },
            
            "intraday_segments": [
                {
                    "segment_id": "morning",
                    "label": "7:30 AM - 11:00 AM",
                    "pnl": round(segments["morning"]["pnl"], 2),
                    "trades_taken": len(segments["morning"]["trades"]),
                    "grade": get_segment_grade(segments["morning"]["pnl"], len(segments["morning"]["trades"])),
                    "comments": ""
                },
                {
                    "segment_id": "midday",
                    "label": "11:00 AM - 2:00 PM",
                    "pnl": round(segments["midday"]["pnl"], 2),
                    "trades_taken": len(segments["midday"]["trades"]),
                    "grade": get_segment_grade(segments["midday"]["pnl"], len(segments["midday"]["trades"])),
                    "comments": ""
                },
                {
                    "segment_id": "afternoon",
                    "label": "2:00 PM - 4:30 PM",
                    "pnl": round(segments["afternoon"]["pnl"], 2),
                    "trades_taken": len(segments["afternoon"]["trades"]),
                    "grade": get_segment_grade(segments["afternoon"]["pnl"], len(segments["afternoon"]["trades"])),
                    "comments": ""
                }
            ],
            
            "big_picture": {
                "market_overview": "",
                "market_regime": market_context.get("market_regime", ""),
                "market_sentiment": market_context.get("market_sentiment", ""),
                "key_levels": {}
            },
            
            "reflections": reflections,
            
            "auto_generated": True,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        return drc_content
    
    def _calculate_overall_grade(self, pnl: float, win_rate: float, total_trades: int) -> str:
        """Calculate overall grade based on P&L, win rate, and trade count"""
        if total_trades == 0:
            return ""
        
        score = 0
        
        # P&L scoring (0-40 points)
        if pnl > 1000:
            score += 40
        elif pnl > 500:
            score += 35
        elif pnl > 200:
            score += 30
        elif pnl > 0:
            score += 25
        elif pnl > -100:
            score += 15
        elif pnl > -300:
            score += 10
        else:
            score += 0
        
        # Win rate scoring (0-40 points)
        if win_rate >= 70:
            score += 40
        elif win_rate >= 60:
            score += 35
        elif win_rate >= 50:
            score += 30
        elif win_rate >= 40:
            score += 20
        else:
            score += 10
        
        # Trade count bonus (0-20 points)
        if 3 <= total_trades <= 6:
            score += 20  # Optimal trading frequency
        elif total_trades <= 10:
            score += 15
        elif total_trades > 10:
            score += 5  # Possible overtrading
        
        # Convert score to grade
        if score >= 90:
            return "A+"
        elif score >= 85:
            return "A"
        elif score >= 80:
            return "A-"
        elif score >= 75:
            return "B+"
        elif score >= 70:
            return "B"
        elif score >= 65:
            return "B-"
        elif score >= 60:
            return "C+"
        elif score >= 55:
            return "C"
        elif score >= 50:
            return "C-"
        elif score >= 40:
            return "D"
        else:
            return "F"
    
    async def generate_multiple_playbooks_from_tradersync(self, min_trades: int = 2, min_pnl: float = 0) -> Dict:
        """
        Analyze all TraderSync imports and generate playbooks for each setup type
        """
        # Get trades grouped by setup
        pipeline = [
            {"$match": {
                "pnl": {"$gt": min_pnl},
                "setup_type": {"$exists": True, "$ne": ""}
            }},
            {"$group": {
                "_id": "$setup_type",
                "count": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "trades": {"$push": "$$ROOT"}
            }},
            {"$match": {"count": {"$gte": min_trades}}},
            {"$sort": {"total_pnl": -1}}
        ]
        
        setup_groups = list(self.imported_trades_col.aggregate(pipeline))
        
        generated_playbooks = []
        
        for group in setup_groups:
            setup_type = group["_id"]
            trades = group["trades"]
            
            # Check if playbook already exists
            existing = self.playbooks_col.find_one({"setup_type": setup_type})
            if existing:
                generated_playbooks.append({
                    "setup_type": setup_type,
                    "status": "skipped",
                    "reason": "Playbook already exists"
                })
                continue
            
            # Generate playbook
            playbook_data = await self.generate_playbook_from_trades(trades, setup_type)
            
            if "error" not in playbook_data:
                generated_playbooks.append({
                    "setup_type": setup_type,
                    "status": "generated",
                    "playbook": playbook_data
                })
            else:
                generated_playbooks.append({
                    "setup_type": setup_type,
                    "status": "error",
                    "error": playbook_data.get("error")
                })
        
        return {
            "total_setup_types": len(setup_groups),
            "playbooks_generated": len([p for p in generated_playbooks if p["status"] == "generated"]),
            "playbooks_skipped": len([p for p in generated_playbooks if p["status"] == "skipped"]),
            "results": generated_playbooks
        }


# Singleton instance
_ai_journal_service: Optional[AIJournalGenerationService] = None

def get_ai_journal_service(db=None) -> AIJournalGenerationService:
    global _ai_journal_service
    if _ai_journal_service is None and db is not None:
        _ai_journal_service = AIJournalGenerationService(db)
    return _ai_journal_service
