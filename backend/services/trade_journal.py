"""
Trade Journal & Strategy Performance Tracking Service
Tracks trades, links them to strategies and market contexts,
and calculates performance metrics.

AI Integration:
- Trades can be enriched with AI context (Confidence Gate, model predictions, TQS)
- On close, outcomes feed into the Learning Loop and Confidence Gate for auto-calibration
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pymongo import MongoClient
from bson import ObjectId
import os
import logging

logger = logging.getLogger(__name__)

class TradeJournalService:
    """Service for logging trades and tracking strategy performance"""
    
    def __init__(self, db):
        self.db = db
        self.trades_col = db["trades"]
        self.performance_col = db["strategy_performance"]
        self.templates_col = db["trade_templates"]
        
        # Create indexes for efficient querying
        self.trades_col.create_index([("symbol", 1), ("entry_date", -1)])
        self.trades_col.create_index([("strategy_id", 1)])
        self.trades_col.create_index([("market_context", 1)])
        self.trades_col.create_index([("status", 1)])
        self.templates_col.create_index([("name", 1)])
    
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
            "source": trade_data.get("source", "manual"),  # manual, bot, ib
            "ai_context": trade_data.get("ai_context"),  # Populated by enrich-ai endpoint
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        result = self.trades_col.insert_one(trade)
        trade["id"] = str(result.inserted_id)
        
        # Remove MongoDB _id from response
        return {k: v for k, v in trade.items() if k != "_id"}
    
    async def close_trade(self, trade_id: str, exit_price: float, notes: str = "") -> Dict:
        """Close an open trade, calculate P&L, and feed AI learning loop"""
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
        
        # Determine outcome for learning loop
        if abs(pnl_percent) < 0.1:
            outcome = "breakeven"
        elif pnl > 0:
            outcome = "won"
        else:
            outcome = "lost"
        
        # Update trade
        update_data = {
            "status": "closed",
            "exit_price": exit_price,
            "exit_date": now.isoformat(),
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl_percent, 2),
            "holding_days": holding_days,
            "exit_notes": notes,
            "outcome": outcome,
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
        
        # Feed AI Learning Loop (write to trade_outcomes)
        await self._feed_learning_loop(trade, exit_price, pnl, pnl_percent, outcome, now)
        
        # Auto-generate chart snapshot with AI annotations
        try:
            if hasattr(self, '_snapshot_service') and self._snapshot_service:
                import asyncio
                asyncio.create_task(self._snapshot_service.generate_snapshot(trade_id, "manual"))
                logger.info(f"Snapshot generation triggered for manual trade {trade_id}")
        except Exception as e:
            logger.warning(f"Failed to trigger snapshot for manual trade: {e}")
        
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
    
    async def _feed_learning_loop(
        self,
        trade: Dict,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        outcome: str,
        exit_time: datetime
    ):
        """Feed the AI learning loop with trade outcome data"""
        try:
            from services.learning_loop_service import get_learning_loop_service
            learning = get_learning_loop_service()
            
            if learning._trade_outcomes_col is None:
                logger.debug("Learning loop DB not initialized, skipping feed")
                return
            
            symbol = trade.get("symbol", "")
            setup_type = trade.get("strategy_id", "MANUAL")
            direction = trade.get("direction", "long")
            entry_price = trade.get("entry_price", 0)
            stop_loss = trade.get("stop_loss") or (entry_price * 0.98 if direction == "long" else entry_price * 1.02)
            take_profit = trade.get("take_profit") or (entry_price * 1.04 if direction == "long" else entry_price * 0.96)
            
            # Map outcome to learning loop format
            outcome_map = {"won": "won", "lost": "lost", "breakeven": "breakeven"}
            ll_outcome = outcome_map.get(outcome, "breakeven")
            
            # Write directly to trade_outcomes collection
            trade_outcome_doc = {
                "id": f"journal_{str(trade.get('_id', ''))[:8]}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                "alert_id": f"journal_manual_{symbol}",
                "bot_trade_id": f"journal_{str(trade.get('_id', ''))}",
                "symbol": symbol,
                "setup_type": setup_type,
                "strategy_name": trade.get("strategy_name", ""),
                "direction": direction,
                "trade_style": trade.get("market_context", "manual"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "stop_price": stop_loss,
                "target_price": take_profit,
                "outcome": ll_outcome,
                "pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
                "actual_r": round(
                    (exit_price - entry_price) / abs(entry_price - stop_loss), 2
                ) if abs(entry_price - stop_loss) > 0 else 0,
                "source": "trade_journal",
                "entry_time": trade.get("entry_date", ""),
                "exit_time": exit_time.isoformat(),
                "context": {
                    "market_regime": trade.get("market_context", "UNKNOWN"),
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reviewed": False,
            }
            
            # Include AI context if the trade was enriched
            ai_ctx = trade.get("ai_context")
            if ai_ctx:
                trade_outcome_doc["context"]["confidence_gate"] = ai_ctx.get("confidence_gate")
                trade_outcome_doc["context"]["tqs_score"] = ai_ctx.get("tqs_score")
                trade_outcome_doc["context"]["model_prediction"] = ai_ctx.get("model_prediction")
            
            learning._trade_outcomes_col.insert_one(trade_outcome_doc)
            logger.info(f"Journal trade fed to learning loop: {symbol} {ll_outcome} ${pnl:.2f}")
            
            # Also update Confidence Gate outcome tracking
            try:
                from services.ai_modules.confidence_gate import get_confidence_gate
                gate = get_confidence_gate()
                gate_outcome = "win" if ll_outcome == "won" else ("loss" if ll_outcome == "lost" else "scratch")
                await gate.record_trade_outcome(
                    symbol=symbol,
                    setup_type=setup_type,
                    outcome=gate_outcome,
                    pnl=pnl,
                )
            except Exception as e:
                logger.debug(f"Confidence gate outcome update skipped: {e}")
            
        except Exception as e:
            logger.warning(f"Failed to feed learning loop (non-critical): {e}")
    
    async def enrich_trade_with_ai(self, trade_id: str) -> Dict:
        """
        Capture current AI state and attach it to a trade.
        Called when user clicks 'Enrich with AI' on a trade entry.
        Captures: Confidence Gate evaluation, model predictions, TQS score.
        """
        trade = self.trades_col.find_one({"_id": ObjectId(trade_id)}, {"_id": 0})
        if not trade:
            raise ValueError("Trade not found")
        
        ai_context = {}
        symbol = trade["symbol"]
        setup_type = trade.get("strategy_id", "MANUAL")
        direction = trade.get("direction", "long")
        
        # 1. Run Confidence Gate evaluation
        try:
            from services.ai_modules.confidence_gate import get_confidence_gate
            gate = get_confidence_gate()
            if gate._db is not None:
                gate_result = await gate.evaluate(
                    symbol=symbol,
                    setup_type=setup_type,
                    direction=direction,
                    quality_score=70,
                    entry_price=trade.get("entry_price", 0),
                    stop_price=trade.get("stop_loss") or 0,
                )
                ai_context["confidence_gate"] = {
                    "decision": gate_result.get("decision", ""),
                    "confidence_score": gate_result.get("confidence_score", 0),
                    "position_multiplier": gate_result.get("position_multiplier", 1.0),
                    "trading_mode": gate_result.get("trading_mode", ""),
                    "reasoning": gate_result.get("reasoning", [])[:5],
                    "regime_state": gate_result.get("regime_state", ""),
                    "ai_regime": gate_result.get("ai_regime", ""),
                }
                if gate_result.get("live_prediction"):
                    pred = gate_result["live_prediction"]
                    ai_context["model_prediction"] = {
                        "direction": pred.get("direction", "flat"),
                        "confidence": pred.get("confidence", 0),
                        "model_used": pred.get("model_used", ""),
                    }
                if gate_result.get("learning_feedback", {}).get("has_data"):
                    fb = gate_result["learning_feedback"]
                    ai_context["learning_feedback"] = {
                        "points": fb.get("points", 0),
                        "reasoning": fb.get("reasoning", ""),
                    }
        except Exception as e:
            logger.debug(f"Confidence gate enrichment failed: {e}")
        
        # 2. Get TQS score if available
        try:
            from services.tqs.tqs_engine import get_tqs_engine
            tqs_engine = get_tqs_engine()
            if tqs_engine:
                tqs_result = await tqs_engine.calculate_tqs(
                    symbol=symbol,
                    setup_type=setup_type,
                    direction=direction,
                )
                if tqs_result:
                    ai_context["tqs_score"] = round(tqs_result.score, 1)
                    ai_context["tqs_grade"] = tqs_result.grade
                    ai_context["tqs_action"] = tqs_result.action
        except Exception as e:
            logger.debug(f"TQS enrichment failed: {e}")
        
        ai_context["enriched_at"] = datetime.now(timezone.utc).isoformat()
        
        # Save to trade
        self.trades_col.update_one(
            {"_id": ObjectId(trade_id)},
            {"$set": {
                "ai_context": ai_context,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Return the full updated trade
        updated = self.trades_col.find_one({"_id": ObjectId(trade_id)}, {"_id": 0})
        updated["id"] = trade_id
        return updated

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
            query
        ).sort("entry_date", -1).limit(limit))
        
        # Convert ObjectId to string id and remove _id in one pass
        result = []
        for trade in trades:
            trade["id"] = str(trade.pop("_id"))
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
        """Get overall performance summary — merges manual journal + bot trades"""
        # Get closed trades from manual journal (cap at 500 for performance)
        closed_trades = list(self.trades_col.find(
            {"status": "closed"},
            {"_id": 0, "pnl": 1, "pnl_percent": 1, "strategy_id": 1, "market_context": 1, "source": 1}
        ).sort("entry_date", -1).limit(500))
        
        # Also get closed bot trades
        try:
            bot_closed = list(self.db["bot_trades"].find(
                {"status": "closed"},
                {"_id": 0, "realized_pnl": 1, "pnl_percent": 1, "setup_type": 1, 
                 "market_regime": 1, "close_reason": 1, "direction": 1,
                 "fill_price": 1, "close_price": 1, "shares": 1}
            ).sort("closed_at", -1).limit(500))
            for bt in bot_closed:
                # Normalize bot trade to match journal format
                pnl = bt.get("realized_pnl", 0) or 0
                if pnl == 0 and bt.get("fill_price") and bt.get("close_price") and bt.get("shares"):
                    entry = bt["fill_price"]
                    exit_p = bt["close_price"]
                    shares = bt["shares"]
                    direction = bt.get("direction", "long")
                    if direction == "short":
                        pnl = (entry - exit_p) * shares
                    else:
                        pnl = (exit_p - entry) * shares
                
                closed_trades.append({
                    "pnl": pnl,
                    "pnl_percent": bt.get("pnl_percent", 0),
                    "strategy_id": bt.get("setup_type", "bot_trade"),
                    "market_context": bt.get("market_regime", "UNKNOWN"),
                    "source": "bot"
                })
        except Exception:
            pass
        
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
        Get a matrix showing strategy performance across different market contexts,
        enriched with AI metrics (gate accuracy, prediction accuracy, edge trend).
        """
        perfs = list(self.performance_col.find({}, {"_id": 0}))
        
        # Build base matrix from strategy_performance collection
        matrix = {}
        strategies = set()
        contexts = set()
        
        for perf in perfs:
            strategy_id = perf.get("strategy_id", "unknown")
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
        
        # Enrich with AI metrics from trade_outcomes
        ai_metrics_by_strategy = {}
        try:
            from services.learning_loop_service import get_learning_loop_service
            learning = get_learning_loop_service()
            if learning._trade_outcomes_col is not None:
                pipeline = [
                    {"$group": {
                        "_id": {
                            "setup": "$setup_type",
                            "regime": "$context.market_regime"
                        },
                        "total": {"$sum": 1},
                        "wins": {"$sum": {"$cond": [{"$eq": ["$outcome", "won"]}, 1, 0]}},
                        "losses": {"$sum": {"$cond": [{"$eq": ["$outcome", "lost"]}, 1, 0]}},
                        "total_pnl": {"$sum": "$pnl"},
                        "avg_pnl": {"$avg": "$pnl"},
                        "gate_go": {"$sum": {"$cond": [{"$eq": ["$context.confidence_gate.decision", "GO"]}, 1, 0]}},
                        "gate_reduce": {"$sum": {"$cond": [{"$eq": ["$context.confidence_gate.decision", "REDUCE"]}, 1, 0]}},
                        "gate_skip": {"$sum": {"$cond": [{"$eq": ["$context.confidence_gate.decision", "SKIP"]}, 1, 0]}},
                    }}
                ]
                ai_results = list(learning._trade_outcomes_col.aggregate(pipeline))
                for r in ai_results:
                    setup = r["_id"].get("setup", "")
                    regime = r["_id"].get("regime", "ALL")
                    if setup not in ai_metrics_by_strategy:
                        ai_metrics_by_strategy[setup] = {}
                    total = r["total"]
                    wins = r["wins"]
                    ai_metrics_by_strategy[setup][regime] = {
                        "ai_trades": total,
                        "ai_win_rate": round((wins / total * 100), 1) if total > 0 else 0,
                        "ai_avg_pnl": round(r["avg_pnl"], 2) if r["avg_pnl"] else 0,
                        "gate_go": r.get("gate_go", 0),
                        "gate_reduce": r.get("gate_reduce", 0),
                        "gate_skip": r.get("gate_skip", 0),
                    }
        except Exception as e:
            logger.debug(f"AI metrics enrichment skipped: {e}")
        
        # Merge AI metrics into matrix
        for strategy, ctx_data in matrix.items():
            for context, metrics in ctx_data.items():
                ai = ai_metrics_by_strategy.get(strategy, {}).get(context, {})
                if ai:
                    metrics["ai_trades"] = ai.get("ai_trades", 0)
                    metrics["ai_win_rate"] = ai.get("ai_win_rate", 0)
                    metrics["ai_avg_pnl"] = ai.get("ai_avg_pnl", 0)
                    metrics["gate_go"] = ai.get("gate_go", 0)
                    metrics["gate_reduce"] = ai.get("gate_reduce", 0)
                    metrics["gate_skip"] = ai.get("gate_skip", 0)
        
        # Find best strategy-context combinations
        best_combos = []
        for strategy, ctx_data in matrix.items():
            for context, metrics in ctx_data.items():
                if metrics["total_trades"] >= 3:
                    combo = {
                        "strategy": strategy,
                        "context": context,
                        "win_rate": metrics["win_rate"],
                        "avg_pnl_percent": metrics["avg_pnl_percent"],
                        "trades": metrics["total_trades"],
                    }
                    ai = ai_metrics_by_strategy.get(strategy, {}).get(context, {})
                    if ai:
                        combo["ai_win_rate"] = ai.get("ai_win_rate", 0)
                        combo["gate_go"] = ai.get("gate_go", 0)
                        combo["gate_reduce"] = ai.get("gate_reduce", 0)
                    best_combos.append(combo)
        
        best_combos.sort(key=lambda x: (x["win_rate"], x["avg_pnl_percent"]), reverse=True)
        
        return {
            "matrix": matrix,
            "strategies": sorted(list(strategies)),
            "contexts": sorted(list(contexts)),
            "top_combinations": best_combos[:10],
            "worst_combinations": best_combos[-5:] if len(best_combos) > 5 else [],
            "ai_strategy_metrics": ai_metrics_by_strategy,
        }
    
    # ==================== TRADE TEMPLATES ====================
    
    async def create_template(self, template_data: Dict) -> Dict:
        """
        Create a trade template for quick logging
        
        Fields:
        - name: Template name (required)
        - template_type: 'basic' or 'strategy' (required)
        - strategy_id: Strategy ID for strategy templates
        - strategy_name: Strategy name for strategy templates
        - market_context: Pre-filled market context
        - direction: Default direction (long/short)
        - default_shares: Default number of shares
        - risk_percent: Default risk % for stop loss calculation
        - reward_ratio: R:R ratio for take profit calculation
        - notes: Default notes template
        """
        now = datetime.now(timezone.utc)
        
        template = {
            "name": template_data["name"],
            "template_type": template_data.get("template_type", "basic"),
            "strategy_id": template_data.get("strategy_id", ""),
            "strategy_name": template_data.get("strategy_name", ""),
            "market_context": template_data.get("market_context", ""),
            "direction": template_data.get("direction", "long"),
            "default_shares": template_data.get("default_shares"),
            "risk_percent": template_data.get("risk_percent", 1.0),
            "reward_ratio": template_data.get("reward_ratio", 2.0),
            "notes": template_data.get("notes", ""),
            "is_default": template_data.get("is_default", False),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        result = self.templates_col.insert_one(template)
        template["id"] = str(result.inserted_id)
        
        return {k: v for k, v in template.items() if k != "_id"}
    
    async def get_templates(self, template_type: str = None) -> List[Dict]:
        """Get all trade templates"""
        query = {}
        if template_type:
            query["template_type"] = template_type
        
        templates = list(self.templates_col.find(query))
        
        result = []
        for t in templates:
            t["id"] = str(t.pop("_id"))
            result.append(t)
        
        return result
    
    async def get_template(self, template_id: str) -> Optional[Dict]:
        """Get a specific template by ID"""
        from bson import ObjectId
        template = self.templates_col.find_one(
            {"_id": ObjectId(template_id)},
            {"_id": 0}
        )
        if template:
            template["id"] = template_id
        return template
    
    async def update_template(self, template_id: str, updates: Dict) -> Dict:
        """Update a trade template"""
        from bson import ObjectId
        
        allowed_fields = ["name", "strategy_id", "strategy_name", "market_context", 
                         "direction", "default_shares", "risk_percent", "reward_ratio", 
                         "notes", "is_default"]
        
        update_data = {k: v for k, v in updates.items() if k in allowed_fields}
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self.templates_col.update_one(
            {"_id": ObjectId(template_id)},
            {"$set": update_data}
        )
        
        return await self.get_template(template_id)
    
    async def delete_template(self, template_id: str) -> bool:
        """Delete a trade template"""
        from bson import ObjectId
        result = self.templates_col.delete_one({"_id": ObjectId(template_id)})
        return result.deleted_count > 0
    
    async def get_default_templates(self) -> List[Dict]:
        """Get the default system templates"""
        defaults = [
            {
                "name": "Quick Long",
                "template_type": "basic",
                "strategy_id": "",
                "strategy_name": "",
                "market_context": "",
                "direction": "long",
                "default_shares": 100,
                "risk_percent": 1.0,
                "reward_ratio": 2.0,
                "notes": "",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Quick Short",
                "template_type": "basic",
                "strategy_id": "",
                "strategy_name": "",
                "market_context": "",
                "direction": "short",
                "default_shares": 100,
                "risk_percent": 1.0,
                "reward_ratio": 2.0,
                "notes": "",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Trend Momentum (INT-01)",
                "template_type": "strategy",
                "strategy_id": "INT-01",
                "strategy_name": "Trend Momentum Continuation",
                "market_context": "TRENDING",
                "direction": "long",
                "default_shares": 100,
                "risk_percent": 1.0,
                "reward_ratio": 2.5,
                "notes": "Entry above VWAP, RVOL > 2",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "ORB Breakout (INT-03)",
                "template_type": "strategy",
                "strategy_id": "INT-03",
                "strategy_name": "Opening Range Breakout",
                "market_context": "TRENDING",
                "direction": "long",
                "default_shares": 100,
                "risk_percent": 0.5,
                "reward_ratio": 3.0,
                "notes": "ORB 5-30min, break above ORH with volume",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Mean Reversion (INT-07)",
                "template_type": "strategy",
                "strategy_id": "INT-07",
                "strategy_name": "VWAP Reversion",
                "market_context": "MEAN_REVERSION",
                "direction": "short",
                "default_shares": 100,
                "risk_percent": 1.0,
                "reward_ratio": 2.0,
                "notes": "Fade parabolic move to VWAP target",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Range Trade (INT-13)",
                "template_type": "strategy",
                "strategy_id": "INT-13",
                "strategy_name": "Intraday Range Trading",
                "market_context": "CONSOLIDATION",
                "direction": "long",
                "default_shares": 100,
                "risk_percent": 0.75,
                "reward_ratio": 1.5,
                "notes": "Long support, short resistance in range",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Swing Breakout (SWG-02)",
                "template_type": "strategy",
                "strategy_id": "SWG-02",
                "strategy_name": "Multi-Week Base Breakout",
                "market_context": "CONSOLIDATION",
                "direction": "long",
                "default_shares": 50,
                "risk_percent": 2.0,
                "reward_ratio": 3.0,
                "notes": "Breakout from tight multi-week base",
                "is_default": True,
                "is_system": True
            },
            {
                "name": "Earnings Gap (INT-04)",
                "template_type": "strategy",
                "strategy_id": "INT-04",
                "strategy_name": "Gap-and-Go",
                "market_context": "TRENDING",
                "direction": "long",
                "default_shares": 100,
                "risk_percent": 1.5,
                "reward_ratio": 2.0,
                "notes": "Gap > 3%, RVOL > 3, above VWAP",
                "is_default": True,
                "is_system": True
            }
        ]
        return defaults
    
    async def log_trade_from_template(self, template_id: str, trade_data: Dict) -> Dict:
        """
        Log a trade using a template
        trade_data overrides template defaults
        """
        # Get template
        template = await self.get_template(template_id) if template_id else None
        
        # Merge template with trade_data
        merged_data = {
            "strategy_id": template.get("strategy_id", "") if template else "",
            "strategy_name": template.get("strategy_name", "") if template else "",
            "market_context": template.get("market_context", "") if template else "",
            "direction": template.get("direction", "long") if template else "long",
            "shares": template.get("default_shares", 100) if template else 100,
            "notes": template.get("notes", "") if template else ""
        }
        
        # Override with provided trade_data
        merged_data.update(trade_data)
        
        # Calculate stop loss and take profit if entry_price provided
        if trade_data.get("entry_price") and template:
            entry = float(trade_data["entry_price"])
            risk_pct = template.get("risk_percent", 1.0) / 100
            reward_ratio = template.get("reward_ratio", 2.0)
            
            if merged_data["direction"] == "long":
                if not trade_data.get("stop_loss"):
                    merged_data["stop_loss"] = round(entry * (1 - risk_pct), 2)
                if not trade_data.get("take_profit"):
                    merged_data["take_profit"] = round(entry * (1 + risk_pct * reward_ratio), 2)
            else:  # short
                if not trade_data.get("stop_loss"):
                    merged_data["stop_loss"] = round(entry * (1 + risk_pct), 2)
                if not trade_data.get("take_profit"):
                    merged_data["take_profit"] = round(entry * (1 - risk_pct * reward_ratio), 2)
        
        return await self.log_trade(merged_data)


# Singleton instance
_trade_journal_service: Optional[TradeJournalService] = None

def get_trade_journal_service(db=None) -> TradeJournalService:
    """Get or create the trade journal service singleton"""
    global _trade_journal_service
    if _trade_journal_service is None and db is not None:
        _trade_journal_service = TradeJournalService(db)
    return _trade_journal_service
