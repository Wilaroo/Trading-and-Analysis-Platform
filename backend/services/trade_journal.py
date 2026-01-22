"""
Trade Journal & Strategy Performance Tracking Service
Tracks trades, links them to strategies and market contexts,
and calculates performance metrics
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pymongo import MongoClient
from bson import ObjectId
import os

class TradeJournalService:
    """Service for logging trades and tracking strategy performance"""
    
    def __init__(self, db):
        self.db = db
        self.trades_col = db["trades"]
        self.performance_col = db["strategy_performance"]
        
        # Create indexes for efficient querying
        self.trades_col.create_index([("symbol", 1), ("entry_date", -1)])
        self.trades_col.create_index([("strategy_id", 1)])
        self.trades_col.create_index([("market_context", 1)])
        self.trades_col.create_index([("status", 1)])
    
    async def log_trade(self, trade_data: Dict) -> Dict:
        """
        Log a new trade with strategy and context information
        
        Required fields:
        - symbol: Stock symbol
        - strategy_id: Strategy used (e.g., INT-01)
        - entry_price: Entry price
        - shares: Number of shares
        - direction: 'long' or 'short'
        
        Optional fields:
        - market_context: TRENDING, CONSOLIDATION, MEAN_REVERSION
        - entry_date: datetime (defaults to now)
        - stop_loss: Stop loss price
        - take_profit: Take profit target
        - notes: Trade notes
        """
        now = datetime.now(timezone.utc)
        
        trade = {
            "symbol": trade_data["symbol"].upper(),
            "strategy_id": trade_data["strategy_id"],
            "strategy_name": trade_data.get("strategy_name", ""),
            "market_context": trade_data.get("market_context", ""),
            "context_confidence": trade_data.get("context_confidence", 0),
            "direction": trade_data.get("direction", "long"),
            "entry_price": float(trade_data["entry_price"]),
            "shares": float(trade_data["shares"]),
            "entry_date": trade_data.get("entry_date", now.isoformat()),
            "stop_loss": trade_data.get("stop_loss"),
            "take_profit": trade_data.get("take_profit"),
            "notes": trade_data.get("notes", ""),
            "tags": trade_data.get("tags", []),
            "status": "open",  # open, closed, cancelled
            "exit_price": None,
            "exit_date": None,
            "pnl": None,
            "pnl_percent": None,
            "holding_days": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        result = self.trades_col.insert_one(trade)
        trade["id"] = str(result.inserted_id)
        
        # Remove MongoDB _id from response
        return {k: v for k, v in trade.items() if k != "_id"}
    
    async def close_trade(self, trade_id: str, exit_price: float, notes: str = "") -> Dict:
        """Close an open trade and calculate P&L"""
        trade = self.trades_col.find_one({"_id": ObjectId(trade_id)})
        
        if not trade:
            raise ValueError("Trade not found")
        
        if trade["status"] != "open":
            raise ValueError("Trade is already closed")
        
        now = datetime.now(timezone.utc)
        entry_date = datetime.fromisoformat(trade["entry_date"].replace('Z', '+00:00'))
        holding_days = (now - entry_date).days
        
        # Calculate P&L
        entry_price = trade["entry_price"]
        shares = trade["shares"]
        direction = trade["direction"]
        
        if direction == "long":
            pnl = (exit_price - entry_price) * shares
            pnl_percent = ((exit_price - entry_price) / entry_price) * 100
        else:  # short
            pnl = (entry_price - exit_price) * shares
            pnl_percent = ((entry_price - exit_price) / entry_price) * 100
        
        # Update trade
        update_data = {
            "status": "closed",
            "exit_price": exit_price,
            "exit_date": now.isoformat(),
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl_percent, 2),
            "holding_days": holding_days,
            "exit_notes": notes,
            "updated_at": now.isoformat()
        }
        
        self.trades_col.update_one(
            {"_id": ObjectId(trade_id)},
            {"$set": update_data}
        )
        
        # Update strategy performance cache
        await self._update_strategy_performance(
            trade["strategy_id"],
            trade["market_context"],
            pnl,
            pnl_percent
        )
        
        return {**{k: v for k, v in trade.items() if k != "_id"}, **update_data, "id": trade_id}
    
    async def _update_strategy_performance(
        self, 
        strategy_id: str, 
        market_context: str, 
        pnl: float, 
        pnl_percent: float
    ):
        """Update cached strategy performance metrics"""
        key = f"{strategy_id}_{market_context}" if market_context else strategy_id
        
        # Get or create performance record
        perf = self.performance_col.find_one({"key": key})
        
        if perf:
            # Update existing
            new_trades = perf["total_trades"] + 1
            new_wins = perf["winning_trades"] + (1 if pnl > 0 else 0)
            new_total_pnl = perf["total_pnl"] + pnl
            new_total_pnl_pct = perf["total_pnl_percent"] + pnl_percent
            
            self.performance_col.update_one(
                {"key": key},
                {"$set": {
                    "total_trades": new_trades,
                    "winning_trades": new_wins,
                    "losing_trades": new_trades - new_wins,
                    "win_rate": round(new_wins / new_trades * 100, 1),
                    "total_pnl": round(new_total_pnl, 2),
                    "total_pnl_percent": round(new_total_pnl_pct, 2),
                    "avg_pnl": round(new_total_pnl / new_trades, 2),
                    "avg_pnl_percent": round(new_total_pnl_pct / new_trades, 2),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
        else:
            # Create new
            self.performance_col.insert_one({
                "key": key,
                "strategy_id": strategy_id,
                "market_context": market_context,
                "total_trades": 1,
                "winning_trades": 1 if pnl > 0 else 0,
                "losing_trades": 0 if pnl > 0 else 1,
                "win_rate": 100 if pnl > 0 else 0,
                "total_pnl": round(pnl, 2),
                "total_pnl_percent": round(pnl_percent, 2),
                "avg_pnl": round(pnl, 2),
                "avg_pnl_percent": round(pnl_percent, 2),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
    
    async def get_trades(
        self, 
        status: str = None, 
        strategy_id: str = None,
        market_context: str = None,
        symbol: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get trades with optional filters"""
        query = {}
        
        if status:
            query["status"] = status
        if strategy_id:
            query["strategy_id"] = strategy_id
        if market_context:
            query["market_context"] = market_context
        if symbol:
            query["symbol"] = symbol.upper()
        
        trades = list(self.trades_col.find(
            query,
            {"_id": 1}  # Include _id for now
        ).sort("entry_date", -1).limit(limit))
        
        # Convert ObjectId to string
        for trade in trades:
            trade["id"] = str(trade.pop("_id"))
        
        # Re-fetch without _id
        result = []
        for trade_ref in trades:
            trade = self.trades_col.find_one(
                {"_id": ObjectId(trade_ref["id"])},
                {"_id": 0}
            )
            trade["id"] = trade_ref["id"]
            result.append(trade)
        
        return result
    
    async def get_trade_by_id(self, trade_id: str) -> Optional[Dict]:
        """Get a specific trade by ID"""
        trade = self.trades_col.find_one(
            {"_id": ObjectId(trade_id)},
            {"_id": 0}
        )
        if trade:
            trade["id"] = trade_id
        return trade
    
    async def update_trade(self, trade_id: str, updates: Dict) -> Dict:
        """Update trade fields (for open trades)"""
        allowed_fields = ["stop_loss", "take_profit", "notes", "tags", "shares"]
        
        update_data = {k: v for k, v in updates.items() if k in allowed_fields}
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self.trades_col.update_one(
            {"_id": ObjectId(trade_id)},
            {"$set": update_data}
        )
        
        return await self.get_trade_by_id(trade_id)
    
    async def delete_trade(self, trade_id: str) -> bool:
        """Delete a trade (only if open/cancelled)"""
        result = self.trades_col.delete_one({
            "_id": ObjectId(trade_id),
            "status": {"$in": ["open", "cancelled"]}
        })
        return result.deleted_count > 0
    
    async def get_strategy_performance(
        self, 
        strategy_id: str = None, 
        market_context: str = None
    ) -> List[Dict]:
        """Get strategy performance metrics"""
        query = {}
        
        if strategy_id:
            query["strategy_id"] = strategy_id
        if market_context:
            query["market_context"] = market_context
        
        perfs = list(self.performance_col.find(query, {"_id": 0}))
        return perfs
    
    async def get_performance_summary(self) -> Dict:
        """Get overall performance summary"""
        # Get all closed trades
        closed_trades = list(self.trades_col.find(
            {"status": "closed"},
            {"_id": 0, "pnl": 1, "pnl_percent": 1, "strategy_id": 1, "market_context": 1}
        ))
        
        if not closed_trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "best_strategy": None,
                "worst_strategy": None,
                "best_context": None
            }
        
        total_trades = len(closed_trades)
        winning_trades = len([t for t in closed_trades if t["pnl"] > 0])
        total_pnl = sum(t["pnl"] for t in closed_trades)
        
        # Get performance by strategy
        strategy_perfs = await self.get_strategy_performance()
        best_strategy = max(strategy_perfs, key=lambda x: x.get("win_rate", 0), default=None)
        worst_strategy = min(strategy_perfs, key=lambda x: x.get("win_rate", 100), default=None)
        
        # Get performance by context
        context_perfs = {}
        for trade in closed_trades:
            ctx = trade.get("market_context", "UNKNOWN")
            if ctx not in context_perfs:
                context_perfs[ctx] = {"wins": 0, "total": 0, "pnl": 0}
            context_perfs[ctx]["total"] += 1
            context_perfs[ctx]["pnl"] += trade["pnl"]
            if trade["pnl"] > 0:
                context_perfs[ctx]["wins"] += 1
        
        best_context = max(
            context_perfs.items(), 
            key=lambda x: x[1]["wins"] / x[1]["total"] if x[1]["total"] > 0 else 0,
            default=(None, {})
        )
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": total_trades - winning_trades,
            "win_rate": round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
            "best_strategy": best_strategy,
            "worst_strategy": worst_strategy,
            "best_context": {
                "context": best_context[0],
                "win_rate": round(best_context[1]["wins"] / best_context[1]["total"] * 100, 1) if best_context[1].get("total", 0) > 0 else 0,
                "total_pnl": round(best_context[1].get("pnl", 0), 2)
            } if best_context[0] else None,
            "context_breakdown": {
                ctx: {
                    "win_rate": round(data["wins"] / data["total"] * 100, 1) if data["total"] > 0 else 0,
                    "total_trades": data["total"],
                    "total_pnl": round(data["pnl"], 2)
                }
                for ctx, data in context_perfs.items()
            }
        }
    
    async def get_strategy_context_matrix(self) -> Dict:
        """
        Get a matrix showing strategy performance across different market contexts
        This helps identify which strategies work best in which contexts
        """
        perfs = list(self.performance_col.find({}, {"_id": 0}))
        
        # Build matrix
        matrix = {}
        strategies = set()
        contexts = set()
        
        for perf in perfs:
            strategy_id = perf["strategy_id"]
            context = perf.get("market_context", "ALL")
            
            strategies.add(strategy_id)
            contexts.add(context)
            
            if strategy_id not in matrix:
                matrix[strategy_id] = {}
            
            matrix[strategy_id][context] = {
                "win_rate": perf.get("win_rate", 0),
                "total_trades": perf.get("total_trades", 0),
                "avg_pnl_percent": perf.get("avg_pnl_percent", 0),
                "total_pnl": perf.get("total_pnl", 0)
            }
        
        # Find best strategy-context combinations
        best_combos = []
        for strategy, ctx_data in matrix.items():
            for context, metrics in ctx_data.items():
                if metrics["total_trades"] >= 3:  # Minimum 3 trades for significance
                    best_combos.append({
                        "strategy": strategy,
                        "context": context,
                        "win_rate": metrics["win_rate"],
                        "avg_pnl_percent": metrics["avg_pnl_percent"],
                        "trades": metrics["total_trades"]
                    })
        
        best_combos.sort(key=lambda x: (x["win_rate"], x["avg_pnl_percent"]), reverse=True)
        
        return {
            "matrix": matrix,
            "strategies": sorted(list(strategies)),
            "contexts": sorted(list(contexts)),
            "top_combinations": best_combos[:10],
            "worst_combinations": best_combos[-5:] if len(best_combos) > 5 else []
        }


# Singleton instance
_trade_journal_service: Optional[TradeJournalService] = None

def get_trade_journal_service(db=None) -> TradeJournalService:
    """Get or create the trade journal service singleton"""
    global _trade_journal_service
    if _trade_journal_service is None and db is not None:
        _trade_journal_service = TradeJournalService(db)
    return _trade_journal_service
