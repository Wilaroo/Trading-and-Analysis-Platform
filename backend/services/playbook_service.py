"""
SMB Playbook Service - Trade Setup Documentation System
Based on Mike Bellafiore's "The Playbook" methodology

Each playbook entry documents a repeatable trade setup with:
- Setup name and type
- Market context and catalyst
- Entry/Exit/Stop rules with IF/THEN statements
- Process-based grading (not P&L outcome)
- Trade style (M2M, T2H, A+)
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
        "Momentum Ignition", "ABCD Pattern", "Bull Flag", "Bear Flag",
        "Relative Strength Leader", "First Move Up", "First Move Down",
        "Puppy Dog Consolidation", "Back Through Open", "Bella Fade",
        "Spencer Scalp", "Hitchhiker Scalp", "Rubberband Scalp",
        "Second Chance Scalp", "Fashionably Late Scalp", "Tidal Wave",
        "Bouncy Ball", "Off Sides Scalp", "9 EMA Reclaim",
        "Range Break", "Breaking News", "Technical Breakout",
        "Support Bounce", "Resistance Fade", "VWAP Reversion",
        "Trend Continuation", "Mean Reversion", "Consolidation Break"
    ]
    
    # Market Context Categories (from SMB Market Context Best Practice)
    MARKET_CONTEXTS = [
        "High Strength / High Weakness",
        "High Strength / Low Weakness", 
        "Low Strength / High Weakness",
        "Low Strength / Low Weakness",
        "Trending Up", "Trending Down", "Balancing/Range-Bound"
    ]
    
    # Catalyst Types (from Opportunity Framing Model)
    CATALYST_TYPES = [
        "Fresh Planned Catalyst",  # Earnings, FDA, etc.
        "Breaking News",
        "Sector Momentum",
        "Technical Setup Only",
        "Random Institutional Orderflow",
        "No Significant Catalyst"
    ]
    
    # Trade Styles (from SMB integration)
    TRADE_STYLES = ["M2M", "T2H", "A+", "Scalp", "Swing"]
    
    # Process Grades (grade execution quality, NOT P&L)
    PROCESS_GRADES = ["A+", "A", "B+", "B", "C", "D", "F"]
    
    def __init__(self, db):
        self.db = db
        self.playbooks_col = db["playbooks"]
        self.playbook_trades_col = db["playbook_trades"]  # Links trades to playbooks
        
        # Create indexes
        self.playbooks_col.create_index([("name", 1)], unique=True)
        self.playbooks_col.create_index([("setup_type", 1)])
        self.playbooks_col.create_index([("trade_style", 1)])
        self.playbooks_col.create_index([("is_active", 1)])
        self.playbook_trades_col.create_index([("playbook_id", 1)])
        self.playbook_trades_col.create_index([("trade_date", -1)])
    
    async def create_playbook(self, data: Dict) -> Dict:
        """
        Create a new playbook entry documenting a trade setup
        
        Required fields:
        - name: Unique descriptive name (e.g., "NVDA Earnings Gap Play")
        - setup_type: Type of setup from SETUP_TYPES
        
        Optional fields filled with SMB framework:
        - description: Setup description
        - market_context: Best market conditions for this setup
        - catalyst_type: Type of catalyst that makes this work
        - trade_style: M2M, T2H, A+, Scalp, Swing
        - if_then_statements: Array of 3 IF/THEN conditions
        - entry_rules: Entry criteria and triggers
        - exit_rules: Target and scaling rules
        - stop_rules: Stop loss rules
        - risk_reward_target: Target R:R ratio
        - position_sizing: Sizing guidelines
        - best_time_of_day: When this setup works best
        - notes: Additional notes
        - tags: Searchable tags
        """
        now = datetime.now(timezone.utc)
        
        # Validate required fields
        if not data.get("name"):
            raise ValueError("Playbook name is required")
        if not data.get("setup_type"):
            raise ValueError("Setup type is required")
        
        playbook = {
            "name": data["name"],
            "setup_type": data["setup_type"],
            "description": data.get("description", ""),
            
            # Market Context (from SMB Best Practice)
            "market_context": data.get("market_context", ""),
            "market_regime": data.get("market_regime", ""),  # Trending/Consolidating/etc.
            
            # Catalyst (from Opportunity Framing Model)
            "catalyst_type": data.get("catalyst_type", "Technical Setup Only"),
            "catalyst_description": data.get("catalyst_description", ""),
            
            # Trade Style (from SMB integration)
            "trade_style": data.get("trade_style", "M2M"),
            
            # IF/THEN Statements (core of Playbook methodology)
            "if_then_statements": data.get("if_then_statements", [
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""},
                {"condition": "", "action": "", "notes": ""}
            ]),
            
            # Entry Rules
            "entry_rules": data.get("entry_rules", {
                "trigger": "",
                "confirmation": "",
                "timing": "",
                "notes": ""
            }),
            
            # Exit Rules
            "exit_rules": data.get("exit_rules", {
                "target_1": "",
                "target_2": "",
                "target_3": "",
                "scaling_rules": "",
                "trail_stop": "",
                "notes": ""
            }),
            
            # Stop Rules
            "stop_rules": data.get("stop_rules", {
                "initial_stop": "",
                "break_even_rule": "",
                "time_stop": "",
                "notes": ""
            }),
            
            # Risk Management
            "risk_reward_target": data.get("risk_reward_target", 2.0),
            "max_risk_percent": data.get("max_risk_percent", 1.0),
            "position_sizing": data.get("position_sizing", "Standard"),
            
            # Timing
            "best_time_of_day": data.get("best_time_of_day", ""),
            "avoid_times": data.get("avoid_times", ""),
            
            # Performance Tracking
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_r_multiple": 0.0,
            "total_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            
            # Metadata
            "notes": data.get("notes", ""),
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
        market_context: str = None,
        is_active: bool = True,
        limit: int = 50
    ) -> List[Dict]:
        """Get playbooks with optional filters"""
        query = {}
        
        if setup_type:
            query["setup_type"] = setup_type
        if trade_style:
            query["trade_style"] = trade_style
        if market_context:
            query["market_context"] = {"$regex": market_context, "$options": "i"}
        if is_active is not None:
            query["is_active"] = is_active
        
        playbooks = list(self.playbooks_col.find(
            query,
            {"_id": 0}
        ).sort("updated_at", -1).limit(limit))
        
        # Add IDs
        for pb in playbooks:
            doc = self.playbooks_col.find_one({"name": pb["name"]})
            if doc:
                pb["id"] = str(doc["_id"])
        
        return playbooks
    
    async def get_playbook_by_id(self, playbook_id: str) -> Optional[Dict]:
        """Get a specific playbook by ID"""
        playbook = self.playbooks_col.find_one(
            {"_id": ObjectId(playbook_id)},
            {"_id": 0}
        )
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
        
        # Remove fields that shouldn't be updated directly
        protected_fields = ["_id", "id", "created_at", "total_trades", "winning_trades", 
                          "losing_trades", "win_rate", "avg_r_multiple", "total_pnl"]
        update_data = {k: v for k, v in updates.items() if k not in protected_fields}
        
        self.playbooks_col.update_one(
            {"_id": ObjectId(playbook_id)},
            {"$set": update_data}
        )
        
        return await self.get_playbook_by_id(playbook_id)
    
    async def delete_playbook(self, playbook_id: str) -> bool:
        """Soft delete a playbook (set inactive)"""
        result = self.playbooks_col.update_one(
            {"_id": ObjectId(playbook_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0
    
    async def log_playbook_trade(self, playbook_id: str, trade_data: Dict) -> Dict:
        """
        Log a trade against a playbook and update performance metrics
        
        trade_data fields:
        - symbol: Stock symbol
        - trade_date: Date of trade
        - entry_price: Entry price
        - exit_price: Exit price (if closed)
        - stop_price: Stop loss price
        - shares: Number of shares
        - direction: long/short
        - pnl: Profit/Loss
        - r_multiple: R multiple achieved
        - process_grade: Grade for execution quality (A+ to F)
        - followed_rules: Boolean - did you follow the playbook rules?
        - notes: Trade-specific notes
        - lessons_learned: What did you learn from this trade?
        """
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
            
            # Process-based grading (NOT outcome-based)
            "process_grade": trade_data.get("process_grade", "B"),
            "followed_rules": trade_data.get("followed_rules", True),
            
            # Review
            "what_worked": trade_data.get("what_worked", ""),
            "what_didnt_work": trade_data.get("what_didnt_work", ""),
            "lessons_learned": trade_data.get("lessons_learned", ""),
            "notes": trade_data.get("notes", ""),
            
            "created_at": now.isoformat()
        }
        
        result = self.playbook_trades_col.insert_one(playbook_trade)
        playbook_trade["id"] = str(result.inserted_id)
        
        # Update playbook performance metrics
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
            {"playbook_id": playbook_id},
            {"_id": 0}
        ).sort("trade_date", -1).limit(limit))
        
        # Add IDs
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
        """Get best performing playbooks (by win rate and R multiple)"""
        playbooks = list(self.playbooks_col.find(
            {"is_active": True, "total_trades": {"$gte": min_trades}},
            {"_id": 0}
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
        
        # Group by setup type
        by_setup_type = {}
        for pb in all_playbooks:
            st = pb.get("setup_type", "Unknown")
            if st not in by_setup_type:
                by_setup_type[st] = {"count": 0, "trades": 0, "pnl": 0}
            by_setup_type[st]["count"] += 1
            by_setup_type[st]["trades"] += pb.get("total_trades", 0)
            by_setup_type[st]["pnl"] += pb.get("total_pnl", 0)
        
        # Group by trade style
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
        """
        AI-assisted: Generate a playbook entry from trade data
        Returns a playbook template pre-filled with trade information
        """
        # Extract information from trade
        symbol = trade_data.get("symbol", "").upper()
        setup_type = trade_data.get("setup_type", trade_data.get("strategy_name", ""))
        direction = trade_data.get("direction", "long")
        entry_price = trade_data.get("entry_price", 0)
        exit_price = trade_data.get("exit_price", 0)
        stop_price = trade_data.get("stop_loss", 0)
        target_price = trade_data.get("target", trade_data.get("take_profit", 0))
        
        # Calculate R multiple if we have the data
        r_multiple = 0
        if entry_price and stop_price and exit_price:
            risk = abs(entry_price - stop_price)
            if risk > 0:
                reward = abs(exit_price - entry_price)
                r_multiple = reward / risk
        
        # Generate suggested playbook
        suggested_playbook = {
            "name": f"{symbol} {setup_type}",
            "setup_type": setup_type,
            "description": f"Trade setup for {symbol} using {setup_type} strategy",
            "trade_style": trade_data.get("smb_trade_style", "M2M"),
            "catalyst_type": trade_data.get("catalyst", "Technical Setup Only"),
            
            "if_then_statements": [
                {
                    "condition": f"IF {symbol} breaks above/below [key level]",
                    "action": f"THEN enter {direction} position",
                    "notes": "Wait for confirmation"
                },
                {
                    "condition": "IF price reaches target",
                    "action": "THEN scale out 50%",
                    "notes": "Trail remaining position"
                },
                {
                    "condition": "IF price hits stop",
                    "action": "THEN exit full position",
                    "notes": "No adding to losers"
                }
            ],
            
            "entry_rules": {
                "trigger": f"Entry at ${entry_price:.2f}" if entry_price else "Define entry trigger",
                "confirmation": "Volume confirmation required",
                "timing": "Best during first hour or power hour",
                "notes": ""
            },
            
            "exit_rules": {
                "target_1": f"${target_price:.2f}" if target_price else "1R",
                "target_2": "2R",
                "target_3": "Let runner ride",
                "scaling_rules": "Scale 50% at T1, 25% at T2, 25% runner",
                "trail_stop": "Trail at 20 EMA or breakeven",
                "notes": ""
            },
            
            "stop_rules": {
                "initial_stop": f"${stop_price:.2f}" if stop_price else "Below key support",
                "break_even_rule": "Move to B/E after +1R",
                "time_stop": "Exit if no movement in 30 min",
                "notes": ""
            },
            
            "risk_reward_target": round(r_multiple, 1) if r_multiple > 0 else 2.0,
            "max_risk_percent": 1.0,
            
            "notes": f"Generated from {symbol} trade on {datetime.now().strftime('%Y-%m-%d')}",
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
