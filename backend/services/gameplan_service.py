"""
SMB Game Plan Service
Based on SMB Capital's Game Plan Best Practices

The Game Plan is a daily trading preparation document that includes:
- Big picture market commentary (prepared night before)
- Stocks in play with IF/THEN statements
- Day 2 names (follow-up candidates)
- Risk management parameters
- Auto-generation from scanner alerts and market data
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from bson import ObjectId
import os


class GamePlanService:
    """Service for managing daily trading Game Plans"""
    
    def __init__(self, db):
        self.db = db
        self.gameplan_col = db["game_plans"]
        self.stocks_in_play_col = db["stocks_in_play"]
        
        # Create indexes
        self.gameplan_col.create_index([("date", -1)], unique=True)
        self.stocks_in_play_col.create_index([("game_plan_date", 1)])
        self.stocks_in_play_col.create_index([("symbol", 1)])
    
    async def create_game_plan(self, date: str = None, auto_populate: bool = True) -> Dict:
        """
        Create a new Game Plan for a trading day
        
        If auto_populate=True, will pull data from:
        - Scanner alerts
        - Earnings calendar
        - Previous day's watchlist
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Check if game plan already exists
        existing = self.gameplan_col.find_one({"date": date})
        if existing:
            existing["id"] = str(existing["_id"])
            del existing["_id"]
            return existing
        
        now = datetime.now(timezone.utc)
        
        game_plan = {
            "date": date,
            
            # Big Picture Commentary (prepared night before)
            "big_picture": {
                "market_overview": "",
                "overnight_news": "",
                "economic_data": "",
                "geopolitical_events": "",
                "recent_observations": "",  # What's been working recently
                "market_regime": "",  # Trending/Consolidating/Choppy
                "bias": "",  # Bullish/Bearish/Neutral
                "key_levels": {
                    "spy_support": "",
                    "spy_resistance": "",
                    "qqq_support": "",
                    "qqq_resistance": "",
                    "vix_level": ""
                }
            },
            
            # Stocks In Play (3-5 max, with full IF/THEN plans)
            "stocks_in_play": [],
            
            # Day 2 Names (continuation candidates)
            "day_2_names": [],
            
            # Risk Management
            "risk_management": {
                "daily_stop": "",  # Max loss for the day
                "per_trade_risk": "",  # Risk per trade
                "max_positions": 3,
                "sizing_notes": "",
                "risk_off_conditions": ""  # When to stop trading
            },
            
            # Session Goals
            "session_goals": {
                "primary_goal": "",
                "secondary_goal": "",
                "what_to_avoid": "",
                "focus_areas": []
            },
            
            # Alerts and Reminders
            "alerts": [],  # Price alerts to set
            
            # Metadata
            "is_night_before": True,  # Was this prepared the night before?
            "is_complete": False,
            "reviewed_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        # Auto-populate if requested
        if auto_populate:
            game_plan = await self._auto_populate_game_plan(game_plan, date)
        
        result = self.gameplan_col.insert_one(game_plan)
        game_plan["id"] = str(result.inserted_id)
        
        return {k: v for k, v in game_plan.items() if k != "_id"}
    
    async def _auto_populate_game_plan(self, game_plan: Dict, date: str) -> Dict:
        """Auto-populate game plan with live scanner alerts and market data"""
        
        # Get LIVE scanner alerts (pre-market watchlist + daily setups)
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                live_alerts = scanner.get_live_alerts()
                
                # Separate by type
                pm_alerts = [a for a in live_alerts if getattr(a, 'id', '').startswith('pm_')]
                daily_alerts = [a for a in live_alerts if getattr(a, 'scan_tier', '').lower() in ('swing', 'position')]
                intraday_alerts = [a for a in live_alerts if getattr(a, 'scan_tier', '').lower() in ('intraday', 'scalp')]
                
                # Pre-market alerts → Stocks in Play (highest priority)
                for alert in pm_alerts[:8]:
                    stock_entry = {
                        "symbol": getattr(alert, 'symbol', ''),
                        "setup_type": getattr(alert, 'setup_type', '').replace('_', ' ').title(),
                        "direction": getattr(alert, 'direction', 'long'),
                        "key_levels": {
                            "entry": getattr(alert, 'trigger_price', 0),
                            "stop": getattr(alert, 'stop_price', 0),
                            "target": getattr(alert, 'target_price', 0),
                        },
                        "catalyst": getattr(alert, 'reasoning', ''),
                        "timeframe": getattr(alert, 'scan_tier', 'intraday'),
                        "if_then_statements": [
                            {
                                "condition": f"IF {getattr(alert, 'symbol', '')} {'gaps up' if getattr(alert, 'direction', '') == 'long' else 'gaps down'} and holds",
                                "action": f"THEN enter {getattr(alert, 'direction', 'long')} at ${getattr(alert, 'trigger_price', 0):.2f}",
                                "notes": getattr(alert, 'reasoning', '')[:80]
                            }
                        ],
                        "source": "premarket_scanner",
                        "score": getattr(alert, 'score', 0),
                    }
                    game_plan["stocks_in_play"].append(stock_entry)
                
                # Intraday alerts → additional stocks in play
                for alert in intraday_alerts[:5]:
                    if not any(s.get("symbol") == getattr(alert, 'symbol', '') for s in game_plan["stocks_in_play"]):
                        stock_entry = {
                            "symbol": getattr(alert, 'symbol', ''),
                            "setup_type": getattr(alert, 'setup_type', '').replace('_', ' ').title(),
                            "direction": getattr(alert, 'direction', 'long'),
                            "key_levels": {
                                "entry": getattr(alert, 'trigger_price', 0),
                                "stop": getattr(alert, 'stop_price', 0),
                                "target": getattr(alert, 'target_price', 0),
                            },
                            "catalyst": getattr(alert, 'reasoning', ''),
                            "source": "live_scanner",
                        }
                        game_plan["stocks_in_play"].append(stock_entry)
        except Exception as e:
            print(f"Failed to load live scanner alerts: {e}")
        
        # Fallback: try MongoDB collection if live scanner not available
        if not game_plan.get("stocks_in_play"):
            try:
                alerts_col = self.db.get_collection("live_alerts")
                if alerts_col is not None:
                    alerts = list(alerts_col.find(
                        {"priority": {"$in": ["high", "A+", "A"]}},
                        {"_id": 0, "symbol": 1, "setup_type": 1, "direction": 1, 
                         "trigger_price": 1, "stop_loss": 1, "target": 1, "reasoning": 1}
                    ).sort("created_at", -1).limit(10))
                    
                    for alert in alerts[:5]:
                        stock_entry = await self._create_stock_in_play_entry(alert)
                        game_plan["stocks_in_play"].append(stock_entry)
            except Exception as e:
                print(f"Failed to load scanner alerts from DB: {e}")
        
        # Get earnings for the date
        try:
            earnings_col = self.db.get_collection("earnings_calendar")
            if earnings_col is not None:
                earnings = list(earnings_col.find(
                    {"date": {"$regex": f"^{date}"}},
                    {"_id": 0, "symbol": 1, "time": 1, "estimate": 1}
                ).limit(10))
                
                for earning in earnings:
                    game_plan["big_picture"]["economic_data"] += f"\n{earning.get('symbol')} earnings {earning.get('time', '')}"
        except Exception as e:
            print(f"Failed to load earnings: {e}")
        
        # Get previous day's watchlist that might be Day 2 candidates
        prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_plan = self.gameplan_col.find_one({"date": prev_date})
        
        if prev_plan:
            # Stocks that moved well yesterday are Day 2 candidates
            for stock in prev_plan.get("stocks_in_play", [])[:3]:
                day2_entry = {
                    "symbol": stock.get("symbol", ""),
                    "reason_for_followup": "Previous day momentum",
                    "setup_type": stock.get("setup_type", ""),
                    "if_then_statements": [
                        {"condition": f"IF {stock.get('symbol')} holds above yesterday's close", 
                         "action": "THEN look for continuation entry", "notes": ""}
                    ],
                    "key_levels": stock.get("key_levels", {}),
                    "notes": "Day 2 continuation play"
                }
                game_plan["day_2_names"].append(day2_entry)

        # 2026-04-28: pull current market regime + bias so the V5
        # MorningPrep card has something to show even when the operator
        # hasn't filed a manual game plan yet. Both top-level (read by
        # frontend `gp.regime || gp.market_regime`) AND inside
        # `big_picture` (canonical home) so neither shape goes stale.
        try:
            from services.market_regime_engine import get_market_regime_engine
            engine = get_market_regime_engine()
            if engine is not None:
                regime_dict = await engine.get_current_regime()
                if regime_dict:
                    # MarketRegimeEngine canonical key is `state`
                    # ("CONFIRMED_UP" / "CONFIRMED_DOWN" / "HOLD" / etc).
                    # Older callers used overall_regime / regime — read all
                    # 3 so we work with any future shape change.
                    regime_label = (
                        regime_dict.get("state")
                        or regime_dict.get("overall_regime")
                        or regime_dict.get("regime")
                    )
                    # Bias derived from state (no separate bias field on
                    # the engine output today).
                    bias_label = None
                    if isinstance(regime_label, str):
                        if "UP" in regime_label.upper():
                            bias_label = "Bullish"
                        elif "DOWN" in regime_label.upper():
                            bias_label = "Bearish"
                        elif regime_label.upper() in ("HOLD", "NEUTRAL", "CHOPPY"):
                            bias_label = "Neutral"
                    if regime_label:
                        game_plan["big_picture"]["market_regime"] = str(regime_label)
                        game_plan["regime"] = str(regime_label)  # top-level for FE
                        game_plan["market_regime"] = str(regime_label)
                    if bias_label:
                        game_plan["big_picture"]["bias"] = str(bias_label)
                        game_plan["bias"] = str(bias_label)
                    rec = regime_dict.get("recommendation")
                    if rec:
                        # Surface the engine's recommendation as the
                        # gameplan thesis when operator hasn't filed one.
                        game_plan["thesis"] = rec
                    # Surface the watchlist as `watchlist` for V5 frontend.
                    watchlist = [
                        s.get("symbol") for s in game_plan.get("stocks_in_play", [])
                        if s.get("symbol")
                    ]
                    if watchlist:
                        game_plan["watchlist"] = watchlist
        except Exception as e:
            # Non-fatal — gameplan still saves with stocks_in_play / day_2.
            print(f"gameplan auto-populate: regime fetch skipped: {e}")

        return game_plan
    
    async def _create_stock_in_play_entry(self, alert: Dict) -> Dict:
        """Create a stock in play entry from a scanner alert"""
        symbol = alert.get("symbol", "")
        direction = alert.get("direction", "long")
        entry = alert.get("trigger_price", 0)
        stop = alert.get("stop_loss", 0)
        target = alert.get("target", 0)
        
        return {
            "symbol": symbol,
            "catalyst": alert.get("catalyst", "Technical Setup"),
            "setup_type": alert.get("setup_type", ""),
            "direction": direction,
            
            # IF/THEN Statements (core of game plan)
            "if_then_statements": [
                {
                    "condition": f"IF {symbol} breaks {'above' if direction == 'long' else 'below'} ${entry:.2f}" if entry else f"IF {symbol} triggers entry",
                    "action": f"THEN enter {direction} position",
                    "notes": "Wait for volume confirmation"
                },
                {
                    "condition": f"IF price reaches ${target:.2f}" if target else "IF price hits first target",
                    "action": "THEN scale out 50%",
                    "notes": "Trail remaining position"
                },
                {
                    "condition": f"IF price hits ${stop:.2f}" if stop else "IF stop is hit",
                    "action": "THEN exit full position immediately",
                    "notes": "Honor the stop, no exceptions"
                }
            ],
            
            "key_levels": {
                "entry": entry,
                "target_1": target,
                "target_2": target * 1.5 if target else 0,
                "stop": stop,
                "support": "",
                "resistance": ""
            },
            
            "trade_plan": {
                "entry_trigger": alert.get("reasoning", ""),
                "position_size": "Standard",
                "risk_amount": "",
                "max_loss": ""
            },
            
            "priority": "primary",  # primary or secondary
            "notes": alert.get("reasoning", ""),
            "added_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_game_plan(self, date: str) -> Optional[Dict]:
        """Get game plan for a specific date"""
        plan = self.gameplan_col.find_one({"date": date})
        if plan:
            plan["id"] = str(plan["_id"])
            del plan["_id"]
        return plan
    
    async def get_game_plan_by_id(self, plan_id: str) -> Optional[Dict]:
        """Get game plan by ID"""
        plan = self.gameplan_col.find_one({"_id": ObjectId(plan_id)})
        if plan:
            plan["id"] = str(plan["_id"])
            del plan["_id"]
        return plan
    
    async def update_game_plan(self, date: str, updates: Dict) -> Dict:
        """Update a game plan"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Remove protected fields
        protected = ["_id", "id", "date", "created_at"]
        update_data = {k: v for k, v in updates.items() if k not in protected}
        
        self.gameplan_col.update_one(
            {"date": date},
            {"$set": update_data}
        )
        
        return await self.get_game_plan(date)
    
    async def add_stock_in_play(self, date: str, stock_data: Dict) -> Dict:
        """Add a stock to the game plan"""
        plan = await self.get_game_plan(date)
        if not plan:
            plan = await self.create_game_plan(date, auto_populate=False)
        
        # Create stock entry
        stock_entry = {
            "symbol": stock_data["symbol"].upper(),
            "catalyst": stock_data.get("catalyst", ""),
            "setup_type": stock_data.get("setup_type", ""),
            "direction": stock_data.get("direction", "long"),
            
            "if_then_statements": stock_data.get("if_then_statements", [
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""}
            ]),
            
            "key_levels": stock_data.get("key_levels", {
                "entry": None,
                "target_1": None,
                "target_2": None,
                "stop": None,
                "support": "",
                "resistance": ""
            }),
            
            "trade_plan": stock_data.get("trade_plan", {
                "entry_trigger": "",
                "position_size": "Standard",
                "risk_amount": "",
                "max_loss": ""
            }),
            
            "priority": stock_data.get("priority", "secondary"),
            "notes": stock_data.get("notes", ""),
            "added_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add to stocks in play
        stocks = plan.get("stocks_in_play", [])
        stocks.append(stock_entry)
        
        await self.update_game_plan(date, {"stocks_in_play": stocks})
        return stock_entry
    
    async def remove_stock_from_play(self, date: str, symbol: str) -> bool:
        """Remove a stock from the game plan"""
        plan = await self.get_game_plan(date)
        if not plan:
            return False
        
        stocks = plan.get("stocks_in_play", [])
        stocks = [s for s in stocks if s.get("symbol", "").upper() != symbol.upper()]
        
        await self.update_game_plan(date, {"stocks_in_play": stocks})
        return True
    
    async def add_day_2_name(self, date: str, stock_data: Dict) -> Dict:
        """Add a Day 2 candidate"""
        plan = await self.get_game_plan(date)
        if not plan:
            plan = await self.create_game_plan(date, auto_populate=False)
        
        day2_entry = {
            "symbol": stock_data["symbol"].upper(),
            "reason_for_followup": stock_data.get("reason_for_followup", ""),
            "setup_type": stock_data.get("setup_type", ""),
            "if_then_statements": stock_data.get("if_then_statements", [
                {"condition": "", "action": "", "notes": ""}
            ]),
            "key_levels": stock_data.get("key_levels", {}),
            "notes": stock_data.get("notes", ""),
            "added_at": datetime.now(timezone.utc).isoformat()
        }
        
        day2_names = plan.get("day_2_names", [])
        day2_names.append(day2_entry)
        
        await self.update_game_plan(date, {"day_2_names": day2_names})
        return day2_entry
    
    async def get_recent_game_plans(self, limit: int = 14) -> List[Dict]:
        """Get recent game plans"""
        plans = list(self.gameplan_col.find(
            {},
            {"_id": 1, "date": 1, "is_complete": 1, "is_night_before": 1,
             "stocks_in_play": {"$slice": 5}, "day_2_names": {"$slice": 3}}
        ).sort("date", -1).limit(limit))
        
        for plan in plans:
            plan["id"] = str(plan["_id"])
            del plan["_id"]
            plan["stocks_count"] = len(plan.get("stocks_in_play", []))
            plan["day2_count"] = len(plan.get("day_2_names", []))
        
        return plans
    
    async def mark_as_reviewed(self, date: str) -> Dict:
        """Mark game plan as reviewed (morning review)"""
        return await self.update_game_plan(date, {
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "is_complete": True
        })
    
    async def generate_game_plan_from_ai(self, market_data: Dict, scanner_alerts: List[Dict]) -> Dict:
        """
        AI-assisted: Generate a suggested game plan
        Returns a game plan template pre-filled with AI suggestions
        """
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        
        suggested_plan = {
            "date": tomorrow,
            "big_picture": {
                "market_overview": market_data.get("summary", ""),
                "overnight_news": "",
                "economic_data": "",
                "geopolitical_events": "",
                "recent_observations": market_data.get("recent_observations", ""),
                "market_regime": market_data.get("regime", ""),
                "bias": market_data.get("bias", "Neutral"),
                "key_levels": market_data.get("key_levels", {})
            },
            "stocks_in_play": [],
            "day_2_names": [],
            "risk_management": {
                "daily_stop": "$500",  # Default
                "per_trade_risk": "1% of account",
                "max_positions": 3,
                "sizing_notes": "Reduce size in choppy conditions",
                "risk_off_conditions": "Stop trading after 2 consecutive losses"
            },
            "session_goals": {
                "primary_goal": "Execute playbook setups with discipline",
                "secondary_goal": "Document all trades for review",
                "what_to_avoid": "Revenge trading, FOMO entries",
                "focus_areas": ["Process over P&L", "Honor stops", "Let winners run"]
            }
        }
        
        # Convert scanner alerts to stocks in play
        for alert in scanner_alerts[:5]:
            stock_entry = await self._create_stock_in_play_entry(alert)
            suggested_plan["stocks_in_play"].append(stock_entry)
        
        return suggested_plan
    
    async def get_game_plan_stats(self, days: int = 30) -> Dict:
        """Get statistics about game plan usage"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        plans = list(self.gameplan_col.find(
            {"date": {"$gte": cutoff}},
            {"_id": 0, "date": 1, "is_complete": 1, "is_night_before": 1, 
             "stocks_in_play": 1}
        ))
        
        if not plans:
            return {
                "period_days": days,
                "total_plans": 0,
                "complete_plans": 0,
                "night_before_prep": 0,
                "avg_stocks_per_plan": 0
            }
        
        total = len(plans)
        complete = len([p for p in plans if p.get("is_complete")])
        night_before = len([p for p in plans if p.get("is_night_before")])
        
        total_stocks = sum(len(p.get("stocks_in_play", [])) for p in plans)
        
        return {
            "period_days": days,
            "total_plans": total,
            "complete_plans": complete,
            "completion_rate": round(complete / total * 100, 1) if total > 0 else 0,
            "night_before_prep": night_before,
            "night_before_rate": round(night_before / total * 100, 1) if total > 0 else 0,
            "avg_stocks_per_plan": round(total_stocks / total, 1) if total > 0 else 0
        }


# Singleton instance
_gameplan_service: Optional[GamePlanService] = None

def get_gameplan_service(db=None) -> GamePlanService:
    """Get or create the game plan service singleton"""
    global _gameplan_service
    if _gameplan_service is None and db is not None:
        _gameplan_service = GamePlanService(db)
    return _gameplan_service
