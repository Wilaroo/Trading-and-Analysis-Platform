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
                
                # v19.34.182 — Pre-market alerts → Stocks in Play (highest priority).
                # Uses the shared builder which reads the CORRECT LiveAlert
                # dataclass fields (stop_loss/target, not stop_price/target_price).
                for alert in pm_alerts[:8]:
                    game_plan["stocks_in_play"].append(
                        self._alert_to_stock_entry(alert, "premarket_scanner")
                    )

                # v19.34.182 — swing/position (daily) setups were previously
                # computed into `daily_alerts` then SILENTLY DROPPED (never
                # appended). Append them now so the gameplan reflects the full
                # multi-horizon watchlist.
                for alert in daily_alerts[:6]:
                    sym = getattr(alert, 'symbol', '')
                    if not any(s.get("symbol") == sym for s in game_plan["stocks_in_play"]):
                        game_plan["stocks_in_play"].append(
                            self._alert_to_stock_entry(alert, "daily_scanner")
                        )

                # Intraday alerts → additional stocks in play
                for alert in intraday_alerts[:5]:
                    sym = getattr(alert, 'symbol', '')
                    if not any(s.get("symbol") == sym for s in game_plan["stocks_in_play"]):
                        game_plan["stocks_in_play"].append(
                            self._alert_to_stock_entry(alert, "live_scanner")
                        )
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
        
        # Get previous day's watchlist that might be Day 2 candidates.
        # v19.34.182 — use the most recent PRIOR game plan (last *trading*
        # day) instead of strict `date - 1`, which lands on weekends/holidays
        # with no plan and silently produced zero Day-2 names every Monday.
        prev_plan = self.gameplan_col.find_one(
            {"date": {"$lt": date}}, sort=[("date", -1)]
        )
        
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
            regime_dict = None
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
            regime_dict = None

        # v19.34.182 — big_picture.key_levels was NEVER populated (always the
        # empty-string template), so the V5 big-picture card showed blank
        # SPY/QQQ S/R + VIX. Fill it from the realtime technical service
        # (SPY/QQQ support & resistance) + the regime engine (VIX).
        await self._populate_key_levels(game_plan, regime_dict)

        return game_plan

    @staticmethod
    def _reasoning_text(alert) -> str:
        """v19.34.182 — LiveAlert.reasoning is a List[str]; coerce to text so
        we don't store a list (or accidentally slice the list with [:80])."""
        r = getattr(alert, 'reasoning', '') or ''
        if isinstance(r, (list, tuple)):
            return " · ".join(str(x) for x in r if x)
        return str(r)

    def _alert_to_stock_entry(self, alert, source: str) -> Dict:
        """v19.34.182 — build a stocks_in_play entry from a LiveAlert dataclass.

        Reads the CORRECT dataclass field names: `stop_loss` and `target`
        (the old code read `stop_price` / `target_price` which don't exist on
        LiveAlert, so every stop/target rendered as $0).
        """
        symbol = getattr(alert, 'symbol', '') or ''
        direction = getattr(alert, 'direction', 'long') or 'long'
        entry = getattr(alert, 'trigger_price', 0) or 0
        stop = getattr(alert, 'stop_loss', 0) or 0
        target = getattr(alert, 'target', 0) or 0
        reasoning = self._reasoning_text(alert)
        setup = (getattr(alert, 'setup_type', '') or '').replace('_', ' ').title()
        return {
            "symbol": symbol,
            "setup_type": setup,
            "direction": direction,
            "key_levels": {
                "entry": entry,
                "stop": stop,
                "target": target,
            },
            "catalyst": reasoning,
            "timeframe": getattr(alert, 'scan_tier', 'intraday'),
            "if_then_statements": [
                {
                    "condition": f"IF {symbol} {'gaps up' if direction == 'long' else 'gaps down'} and holds",
                    "action": (f"THEN enter {direction} at ${entry:.2f}" if entry
                               else f"THEN enter {direction}"),
                    "notes": reasoning[:120],
                }
            ],
            "source": source,
            "score": getattr(alert, 'score', 0),
        }

    async def _populate_key_levels(self, game_plan: Dict, regime_dict: Optional[Dict]) -> None:
        """v19.34.182 — fill big_picture.key_levels with SPY/QQQ support &
        resistance (realtime technical service) + VIX (regime engine's
        volume_vix block). Best-effort; never raises."""
        try:
            kl = game_plan.get("big_picture", {}).get("key_levels")
            if kl is None:
                return
        except Exception:
            return

        # SPY / QQQ support & resistance from the technical snapshot.
        try:
            from services.realtime_technical_service import get_technical_service
            tech = get_technical_service()
            if tech is not None:
                for sym, sup_key, res_key in (
                    ("SPY", "spy_support", "spy_resistance"),
                    ("QQQ", "qqq_support", "qqq_resistance"),
                ):
                    try:
                        snap = await tech.get_technical_snapshot(sym, mongo_only=True)
                        if snap is not None:
                            kl[sup_key] = snap.support
                            kl[res_key] = snap.resistance
                    except Exception as e:
                        print(f"gameplan key-levels: {sym} snapshot skipped: {e}")
        except Exception as e:
            print(f"gameplan key-levels: tech service skipped: {e}")

        # VIX from the regime engine's volume_vix signal block.
        try:
            if regime_dict:
                vix = (
                    regime_dict.get("signal_blocks", {})
                    .get("volume_vix", {})
                    .get("signals", {})
                    .get("vix_price")
                )
                if vix:
                    kl["vix_level"] = vix
        except Exception as e:
            print(f"gameplan key-levels: vix skipped: {e}")

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
