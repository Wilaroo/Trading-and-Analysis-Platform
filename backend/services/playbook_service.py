"""
SMB Playbook Service - Trade Setup Documentation System
Based on Mike Bellafiore's "The Playbook" methodology

The SMB Playbook Template has 6 main sections:
1. BIGGER PICTURE - Market context and how the trade fits
2. INTRADAY FUNDAMENTALS - Catalysts, news, volume anomalies
3. TECHNICAL ANALYSIS - Chart patterns and key levels
4. READING THE TAPE - Order flow patterns and tape confirmation
5. TRADE MANAGEMENT - Entry, stops, additions, profit targets
6. TRADE REVIEW - Lessons learned and improvements

Each playbook entry documents a repeatable trade setup.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List
from bson import ObjectId
import os


class PlaybookService:
    """Service for managing trade playbooks based on SMB methodology"""
    
    # SMB Setup Types from the registry
    SETUP_TYPES = [
        "Opening Range Breakout", "First VWAP Pullback", "Gap and Go",
        "Gap Give and Go", "Momentum Ignition", "ABCD Pattern", "Bull Flag", "Bear Flag",
        "Relative Strength Leader", "First Move Up", "First Move Down",
        "Puppy Dog Consolidation", "Back Through Open", "Bella Fade",
        "Spencer Scalp", "Hitchhiker Scalp", "Rubberband Scalp",
        "Second Chance Scalp", "Fashionably Late Scalp", "Tidal Wave",
        "Bouncy Ball", "Off Sides Scalp", "9 EMA Reclaim",
        "Range Break", "Breaking News", "Technical Breakout",
        "Support Bounce", "Resistance Fade", "VWAP Reversion",
        "Trend Continuation", "Mean Reversion", "Consolidation Break",
        "ATH Breakout", "Backside Short", "Leader Lagger Play"
    ]
    
    # Market Context Categories (from SMB Market Context Best Practice)
    MARKET_CONTEXTS = [
        "High Strength / High Weakness",
        "High Strength / Low Weakness", 
        "Low Strength / High Weakness",
        "Low Strength / Low Weakness",
        "Trending Up", "Trending Down", "Balancing/Range-Bound",
        "Gap Up Day", "Gap Down Day", "Reversal Day", "Inside Day"
    ]
    
    # Catalyst Types (from Opportunity Framing Model)
    CATALYST_TYPES = [
        "Fresh Planned Catalyst",
        "Breaking News",
        "Price Target Raises",
        "Earnings Beat/Miss",
        "Sector Momentum",
        "Technical Setup Only",
        "Random Institutional Orderflow",
        "Volume Anomaly",
        "ATH Breakout",
        "No Significant Catalyst"
    ]
    
    # Trade Styles (from SMB integration)
    TRADE_STYLES = ["M2M", "T2H", "A+", "Scalp", "Swing"]
    
    # Process Grades (grade execution quality, NOT P&L)
    PROCESS_GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
    
    def __init__(self, db):
        self.db = db
        self.playbooks_col = db["playbooks"]
        self.playbook_trades_col = db["playbook_trades"]
        
        # Create indexes
        self.playbooks_col.create_index([("name", 1)], unique=True)
        self.playbooks_col.create_index([("setup_type", 1)])
        self.playbooks_col.create_index([("trade_style", 1)])
        self.playbooks_col.create_index([("is_active", 1)])
        self.playbook_trades_col.create_index([("playbook_id", 1)])
        self.playbook_trades_col.create_index([("trade_date", -1)])
    
    async def create_playbook(self, data: Dict) -> Dict:
        """
        Create a new playbook entry following the exact SMB Playbook Template:
        
        1. BIGGER PICTURE - Market context
        2. INTRADAY FUNDAMENTALS - Catalysts  
        3. TECHNICAL ANALYSIS - Chart patterns
        4. READING THE TAPE - Order flow
        5. TRADE MANAGEMENT - Entry/Stop/Targets
        6. TRADE REVIEW - Lessons learned
        """
        now = datetime.now(timezone.utc)
        
        if not data.get("name"):
            raise ValueError("Playbook name is required")
        if not data.get("setup_type"):
            raise ValueError("Setup type is required")
        
        playbook = {
            "name": data["name"],
            "setup_type": data["setup_type"],
            "ticker": data.get("ticker", ""),
            "direction": data.get("direction", "long"),
            "trade_style": data.get("trade_style", "M2M"),
            "trade_date": data.get("trade_date", ""),
            
            # ============ 1. BIGGER PICTURE ============
            "bigger_picture": {
                "market_context": data.get("bigger_picture", {}).get("market_context", ""),
                "spy_action": data.get("bigger_picture", {}).get("spy_action", ""),
                "qqq_action": data.get("bigger_picture", {}).get("qqq_action", ""),
                "sector_action": data.get("bigger_picture", {}).get("sector_action", ""),
                "market_play_or_not": data.get("bigger_picture", {}).get("market_play_or_not", ""),
                "trade_rationale": data.get("bigger_picture", {}).get("trade_rationale", ""),
                "notes": data.get("bigger_picture", {}).get("notes", "")
            },
            
            # ============ 2. INTRADAY FUNDAMENTALS ============
            "intraday_fundamentals": {
                "catalyst_type": data.get("intraday_fundamentals", {}).get("catalyst_type", "Technical Setup Only"),
                "catalyst_description": data.get("intraday_fundamentals", {}).get("catalyst_description", ""),
                "news_headline": data.get("intraday_fundamentals", {}).get("news_headline", ""),
                "price_targets": data.get("intraday_fundamentals", {}).get("price_targets", ""),
                "volume_analysis": data.get("intraday_fundamentals", {}).get("volume_analysis", ""),
                "premarket_action": data.get("intraday_fundamentals", {}).get("premarket_action", ""),
                "why_in_play": data.get("intraday_fundamentals", {}).get("why_in_play", ""),
                "identified_risks": data.get("intraday_fundamentals", {}).get("identified_risks", ""),
                "notes": data.get("intraday_fundamentals", {}).get("notes", "")
            },
            
            # ============ 3. TECHNICAL ANALYSIS ============
            "technical_analysis": {
                "chart_pattern": data.get("technical_analysis", {}).get("chart_pattern", ""),
                "key_support_levels": data.get("technical_analysis", {}).get("key_support_levels", []),
                "key_resistance_levels": data.get("technical_analysis", {}).get("key_resistance_levels", []),
                "vwap_position": data.get("technical_analysis", {}).get("vwap_position", ""),
                "ema_9_position": data.get("technical_analysis", {}).get("ema_9_position", ""),
                "ema_20_position": data.get("technical_analysis", {}).get("ema_20_position", ""),
                "daily_levels": data.get("technical_analysis", {}).get("daily_levels", ""),
                "chart_markup_notes": data.get("technical_analysis", {}).get("chart_markup_notes", ""),
                "notes": data.get("technical_analysis", {}).get("notes", "")
            },
            
            # ============ 4. READING THE TAPE ============
            "reading_the_tape": {
                "tape_patterns": data.get("reading_the_tape", {}).get("tape_patterns", []),
                "bid_held": data.get("reading_the_tape", {}).get("bid_held", ""),
                "offer_held": data.get("reading_the_tape", {}).get("offer_held", ""),
                "clean_or_choppy": data.get("reading_the_tape", {}).get("clean_or_choppy", ""),
                "absorption_levels": data.get("reading_the_tape", {}).get("absorption_levels", ""),
                "key_tape_signals": data.get("reading_the_tape", {}).get("key_tape_signals", ""),
                "tape_confirmation_notes": data.get("reading_the_tape", {}).get("tape_confirmation_notes", ""),
                "notes": data.get("reading_the_tape", {}).get("notes", "")
            },
            
            # ============ 5. TRADE MANAGEMENT ============
            "trade_management": {
                "entry_trigger": data.get("trade_management", {}).get("entry_trigger", ""),
                "entry_price": data.get("trade_management", {}).get("entry_price", None),
                "initial_stop": data.get("trade_management", {}).get("initial_stop", ""),
                "stop_adjustment_rules": data.get("trade_management", {}).get("stop_adjustment_rules", ""),
                "add_levels": data.get("trade_management", {}).get("add_levels", ""),
                "add_rules": data.get("trade_management", {}).get("add_rules", ""),
                "profit_target_1": data.get("trade_management", {}).get("profit_target_1", ""),
                "profit_target_2": data.get("trade_management", {}).get("profit_target_2", ""),
                "profit_target_3": data.get("trade_management", {}).get("profit_target_3", ""),
                "profit_target_selection": data.get("trade_management", {}).get("profit_target_selection", ""),
                "scaling_rules": data.get("trade_management", {}).get("scaling_rules", ""),
                "position_sizing": data.get("trade_management", {}).get("position_sizing", "Standard"),
                "max_risk": data.get("trade_management", {}).get("max_risk", ""),
                "notes": data.get("trade_management", {}).get("notes", "")
            },
            
            # ============ 6. TRADE REVIEW ============
            "trade_review": {
                "what_did_i_learn": data.get("trade_review", {}).get("what_did_i_learn", ""),
                "how_could_i_do_better": data.get("trade_review", {}).get("how_could_i_do_better", ""),
                "what_would_i_do_differently": data.get("trade_review", {}).get("what_would_i_do_differently", ""),
                "what_to_look_for": data.get("trade_review", {}).get("what_to_look_for", ""),
                "common_mistakes": data.get("trade_review", {}).get("common_mistakes", ""),
                "best_time_of_day": data.get("trade_review", {}).get("best_time_of_day", ""),
                "avoid_times": data.get("trade_review", {}).get("avoid_times", ""),
                "notes": data.get("trade_review", {}).get("notes", "")
            },
            
            # ============ IF/THEN STATEMENTS ============
            "if_then_statements": data.get("if_then_statements", [
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""}
            ]),
            
            # ============ PERFORMANCE TRACKING ============
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_r_multiple": 0.0,
            "total_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            
            # ============ METADATA ============
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "is_active": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        result = self.playbooks_col.insert_one(playbook)
        playbook["id"] = str(result.inserted_id)
        
        return {k: v for k, v in playbook.items() if k != "_id"}
    
    async def get_playbooks(
        self,
        setup_type: str = None,
        trade_style: str = None,
        ticker: str = None,
        is_active: bool = True,
        limit: int = 50
    ) -> List[Dict]:
        """Get playbooks with optional filters"""
        query = {}
        
        if setup_type:
            query["setup_type"] = setup_type
        if trade_style:
            query["trade_style"] = trade_style
        if ticker:
            query["ticker"] = ticker.upper()
        if is_active is not None:
            query["is_active"] = is_active
        
        playbooks = list(self.playbooks_col.find(query).sort("updated_at", -1).limit(limit))
        
        # Convert _id to string id in one pass
        for pb in playbooks:
            pb["id"] = str(pb.pop("_id"))
        
        return playbooks
    
    async def get_playbook_by_id(self, playbook_id: str) -> Optional[Dict]:
        """Get a specific playbook by ID"""
        playbook = self.playbooks_col.find_one({"_id": ObjectId(playbook_id)}, {"_id": 0})
        if playbook:
            playbook["id"] = playbook_id
        return playbook
    
    async def get_playbook_by_name(self, name: str) -> Optional[Dict]:
        """Get a playbook by name"""
        doc = self.playbooks_col.find_one({"name": name})
        if doc:
            playbook = {k: v for k, v in doc.items() if k != "_id"}
            playbook["id"] = str(doc["_id"])
            return playbook
        return None
    
    async def update_playbook(self, playbook_id: str, updates: Dict) -> Dict:
        """Update a playbook"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        protected_fields = ["_id", "id", "created_at", "total_trades", "winning_trades", 
                          "losing_trades", "win_rate", "avg_r_multiple", "total_pnl"]
        update_data = {k: v for k, v in updates.items() if k not in protected_fields}
        
        self.playbooks_col.update_one({"_id": ObjectId(playbook_id)}, {"$set": update_data})
        
        return await self.get_playbook_by_id(playbook_id)
    
    async def delete_playbook(self, playbook_id: str) -> bool:
        """Soft delete a playbook (set inactive)"""
        result = self.playbooks_col.update_one(
            {"_id": ObjectId(playbook_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0
    
    async def log_playbook_trade(self, playbook_id: str, trade_data: Dict) -> Dict:
        """Log a trade against a playbook and update performance metrics"""
        now = datetime.now(timezone.utc)
        
        playbook_trade = {
            "playbook_id": playbook_id,
            "symbol": trade_data["symbol"].upper(),
            "trade_date": trade_data.get("trade_date", now.isoformat()),
            "entry_price": float(trade_data.get("entry_price", 0)),
            "exit_price": float(trade_data.get("exit_price", 0)) if trade_data.get("exit_price") else None,
            "stop_price": float(trade_data.get("stop_price", 0)) if trade_data.get("stop_price") else None,
            "target_price": float(trade_data.get("target_price", 0)) if trade_data.get("target_price") else None,
            "shares": int(trade_data.get("shares", 0)),
            "direction": trade_data.get("direction", "long"),
            "pnl": float(trade_data.get("pnl", 0)),
            "r_multiple": float(trade_data.get("r_multiple", 0)),
            "process_grade": trade_data.get("process_grade", "B"),
            "followed_rules": trade_data.get("followed_rules", True),
            "what_worked": trade_data.get("what_worked", ""),
            "what_didnt_work": trade_data.get("what_didnt_work", ""),
            "lessons_learned": trade_data.get("lessons_learned", ""),
            "notes": trade_data.get("notes", ""),
            "created_at": now.isoformat()
        }
        
        result = self.playbook_trades_col.insert_one(playbook_trade)
        playbook_trade["id"] = str(result.inserted_id)
        
        await self._update_playbook_stats(playbook_id)
        
        return {k: v for k, v in playbook_trade.items() if k != "_id"}
    
    async def _update_playbook_stats(self, playbook_id: str):
        """Update playbook performance statistics"""
        trades = list(self.playbook_trades_col.find({"playbook_id": playbook_id}))
        
        if not trades:
            return
        
        total = len(trades)
        winners = len([t for t in trades if t.get("pnl", 0) > 0])
        losers = total - winners
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        r_multiples = [t.get("r_multiple", 0) for t in trades if t.get("r_multiple")]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        pnls = [t.get("pnl", 0) for t in trades]
        best_pnl = max(pnls) if pnls else 0
        worst_pnl = min(pnls) if pnls else 0
        
        self.playbooks_col.update_one(
            {"_id": ObjectId(playbook_id)},
            {"$set": {
                "total_trades": total,
                "winning_trades": winners,
                "losing_trades": losers,
                "win_rate": round(winners / total * 100, 1) if total > 0 else 0,
                "avg_r_multiple": round(avg_r, 2),
                "total_pnl": round(total_pnl, 2),
                "best_trade_pnl": round(best_pnl, 2),
                "worst_trade_pnl": round(worst_pnl, 2),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
    
    async def get_playbook_trades(self, playbook_id: str, limit: int = 50) -> List[Dict]:
        """Get trades for a specific playbook"""
        trades = list(self.playbook_trades_col.find(
            {"playbook_id": playbook_id}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit))
        
        for idx, trade in enumerate(trades):
            doc = self.playbook_trades_col.find_one({
                "playbook_id": playbook_id,
                "symbol": trade["symbol"],
                "trade_date": trade["trade_date"]
            })
            if doc:
                trade["id"] = str(doc["_id"])
        
        return trades
    
    async def get_best_playbooks(self, min_trades: int = 3, limit: int = 10) -> List[Dict]:
        """Get best performing playbooks"""
        playbooks = list(self.playbooks_col.find(
            {"is_active": True, "total_trades": {"$gte": min_trades}}, {"_id": 0}
        ).sort([("win_rate", -1), ("avg_r_multiple", -1)]).limit(limit))
        
        for pb in playbooks:
            doc = self.playbooks_col.find_one({"name": pb["name"]})
            if doc:
                pb["id"] = str(doc["_id"])
        
        return playbooks
    
    async def get_playbook_summary(self) -> Dict:
        """Get summary of all playbooks"""
        all_playbooks = list(self.playbooks_col.find({"is_active": True}, {"_id": 0}))
        
        total_playbooks = len(all_playbooks)
        total_trades = sum(p.get("total_trades", 0) for p in all_playbooks)
        total_pnl = sum(p.get("total_pnl", 0) for p in all_playbooks)
        
        by_setup_type = {}
        for pb in all_playbooks:
            st = pb.get("setup_type", "Unknown")
            if st not in by_setup_type:
                by_setup_type[st] = {"count": 0, "trades": 0, "pnl": 0}
            by_setup_type[st]["count"] += 1
            by_setup_type[st]["trades"] += pb.get("total_trades", 0)
            by_setup_type[st]["pnl"] += pb.get("total_pnl", 0)
        
        by_trade_style = {}
        for pb in all_playbooks:
            ts = pb.get("trade_style", "Unknown")
            if ts not in by_trade_style:
                by_trade_style[ts] = {"count": 0, "trades": 0, "pnl": 0}
            by_trade_style[ts]["count"] += 1
            by_trade_style[ts]["trades"] += pb.get("total_trades", 0)
            by_trade_style[ts]["pnl"] += pb.get("total_pnl", 0)
        
        return {
            "total_playbooks": total_playbooks,
            "total_trades": total_trades,
            "total_pnl": round(total_pnl, 2),
            "by_setup_type": by_setup_type,
            "by_trade_style": by_trade_style,
            "setup_types": self.SETUP_TYPES,
            "market_contexts": self.MARKET_CONTEXTS,
            "catalyst_types": self.CATALYST_TYPES,
            "trade_styles": self.TRADE_STYLES,
            "process_grades": self.PROCESS_GRADES
        }
    
    async def generate_playbook_from_trade(self, trade_data: Dict) -> Dict:
        """AI-assisted: Generate a playbook template from trade data"""
        symbol = trade_data.get("symbol", "").upper()
        setup_type = trade_data.get("setup_type", trade_data.get("strategy_name", ""))
        direction = trade_data.get("direction", "long")
        entry_price = trade_data.get("entry_price", 0)
        exit_price = trade_data.get("exit_price", 0)
        stop_price = trade_data.get("stop_loss", 0)
        target_price = trade_data.get("target", trade_data.get("take_profit", 0))
        
        r_multiple = 0
        if entry_price and stop_price and exit_price:
            risk = abs(entry_price - stop_price)
            if risk > 0:
                reward = abs(exit_price - entry_price)
                r_multiple = reward / risk
        
        suggested_playbook = {
            "name": f"{symbol} {setup_type}",
            "setup_type": setup_type,
            "ticker": symbol,
            "direction": direction,
            "trade_style": trade_data.get("smb_trade_style", "M2M"),
            "trade_date": datetime.now().strftime("%Y-%m-%d"),
            
            "bigger_picture": {
                "market_context": "",
                "spy_action": "",
                "trade_rationale": f"Trade setup for {symbol} using {setup_type} strategy"
            },
            
            "intraday_fundamentals": {
                "catalyst_type": trade_data.get("catalyst", "Technical Setup Only"),
                "why_in_play": trade_data.get("reasoning", ""),
                "volume_analysis": ""
            },
            
            "technical_analysis": {
                "chart_pattern": setup_type,
                "key_support_levels": [stop_price] if stop_price else [],
                "key_resistance_levels": [target_price] if target_price else []
            },
            
            "reading_the_tape": {
                "tape_patterns": [],
                "clean_or_choppy": "",
                "key_tape_signals": ""
            },
            
            "trade_management": {
                "entry_trigger": f"Entry at ${entry_price:.2f}" if entry_price else "",
                "entry_price": entry_price,
                "initial_stop": f"${stop_price:.2f}" if stop_price else "",
                "profit_target_1": f"${target_price:.2f}" if target_price else "1R",
                "profit_target_2": "2R",
                "scaling_rules": "Scale 50% at T1, 25% at T2, 25% runner"
            },
            
            "trade_review": {
                "what_did_i_learn": "",
                "how_could_i_do_better": "",
                "what_would_i_do_differently": ""
            },
            
            "if_then_statements": [
                {
                    "condition": f"IF {symbol} breaks {'above' if direction == 'long' else 'below'} key level",
                    "action": f"THEN enter {direction} position",
                    "notes": "Wait for confirmation"
                },
                {
                    "condition": "IF price reaches first target",
                    "action": "THEN scale out 50%",
                    "notes": "Trail remaining position"
                },
                {
                    "condition": "IF stop is hit",
                    "action": "THEN exit full position",
                    "notes": "Honor the stop"
                }
            ],
            
            "description": f"Generated from {symbol} trade on {datetime.now().strftime('%Y-%m-%d')}",
            "tags": [symbol, setup_type, direction]
        }
        
        return suggested_playbook


# Singleton instance
_playbook_service: Optional[PlaybookService] = None

def get_playbook_service(db=None) -> PlaybookService:
    """Get or create the playbook service singleton"""
    global _playbook_service
    if _playbook_service is None and db is not None:
        _playbook_service = PlaybookService(db)
    return _playbook_service
