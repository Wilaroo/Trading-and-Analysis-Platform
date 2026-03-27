"""
AI Confidence Gate
==================
The pre-trade intelligence layer that SentCom checks before every trade.

Flow: Setup Detected → Confidence Gate → Position Sizing → Execute or Skip → Log Decision

The gate evaluates:
1. Current market regime (rule-based + AI classification)
2. Model consensus for this setup type
3. Position sizing recommendation based on regime + confidence
4. GO / REDUCE / SKIP decision with full reasoning

Also tracks SentCom's overall "trading mode" (Aggressive/Cautious/Defensive)
and maintains a decision log for the UI.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from collections import deque

logger = logging.getLogger(__name__)

# Maximum decisions to keep in memory
MAX_DECISION_LOG = 200


class TradingMode:
    AGGRESSIVE = "aggressive"
    NORMAL = "normal"
    CAUTIOUS = "cautious"
    DEFENSIVE = "defensive"


class ConfidenceGate:
    """
    Pre-trade intelligence gate.
    Evaluates regime + model consensus to produce a go/no-go for each trade.
    """

    def __init__(self, db=None):
        self._db = db
        self._decision_log: deque = deque(maxlen=MAX_DECISION_LOG)
        self._trading_mode = TradingMode.NORMAL
        self._mode_reason = "Initialized — awaiting first regime check"
        self._last_regime_check = None
        self._regime_cache = None
        self._ai_regime_cache = None
        self._stats = {
            "total_evaluated": 0,
            "go_count": 0,
            "reduce_count": 0,
            "skip_count": 0,
            "today_evaluated": 0,
            "today_go": 0,
            "today_skip": 0,
            "today_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

    def set_db(self, db):
        self._db = db

    async def evaluate(
        self,
        symbol: str,
        setup_type: str,
        direction: str = "long",
        quality_score: int = 70,
        entry_price: float = 0,
        stop_price: float = 0,
        regime_engine=None,
    ) -> Dict[str, Any]:
        """
        Core evaluation: Should SentCom take this trade?

        Returns:
            {
                "decision": "GO" | "REDUCE" | "SKIP",
                "confidence_score": 0-100,
                "regime_state": str,
                "ai_regime": str,
                "trading_mode": str,
                "position_multiplier": 0.0-1.5,
                "reasoning": [str],
                "model_signals": {...},
            }
        """
        reasoning = []
        confidence_points = 50  # Start neutral
        position_multiplier = 1.0

        # Reset daily stats if new day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._stats["today_date"] != today:
            self._stats["today_date"] = today
            self._stats["today_evaluated"] = 0
            self._stats["today_go"] = 0
            self._stats["today_skip"] = 0

        self._stats["total_evaluated"] += 1
        self._stats["today_evaluated"] += 1

        # --- 1. REGIME CHECK ---
        regime_state = "HOLD"
        regime_score = 50
        ai_regime = "unknown"

        if regime_engine:
            try:
                regime_data = await regime_engine.get_current_regime()
                regime_state = regime_data.get("state", "HOLD")
                regime_score = regime_data.get("composite_score", 50)
                self._regime_cache = regime_data
            except Exception as e:
                logger.warning(f"Regime check failed: {e}")

        # AI regime classification
        try:
            ai_regime = await self._get_ai_regime()
        except Exception:
            pass

        # Regime contribution to confidence
        if regime_state == "CONFIRMED_UP" and direction == "long":
            confidence_points += 20
            reasoning.append(f"Regime BULLISH (score {regime_score}) — aligned with long entry")
        elif regime_state == "CONFIRMED_DOWN" and direction == "long":
            confidence_points -= 25
            position_multiplier *= 0.5
            reasoning.append(f"Regime BEARISH (score {regime_score}) — against long entry, halving size")
        elif regime_state == "CONFIRMED_DOWN" and direction == "short":
            confidence_points += 15
            reasoning.append("Regime BEARISH — aligned with short entry")
        elif regime_state == "CONFIRMED_UP" and direction == "short":
            confidence_points -= 20
            position_multiplier *= 0.5
            reasoning.append("Regime BULLISH — against short entry, halving size")
        else:
            reasoning.append(f"Regime NEUTRAL (score {regime_score}) — no strong directional bias")

        # AI regime refinement
        if ai_regime == "high_vol":
            confidence_points -= 10
            position_multiplier *= 0.7
            reasoning.append("AI detects HIGH VOLATILITY regime — reducing exposure 30%")
        elif ai_regime == "bull_trend" and direction == "long":
            confidence_points += 10
            reasoning.append("AI confirms BULL TREND — additional confidence for longs")
        elif ai_regime == "bear_trend" and direction == "short":
            confidence_points += 10
            reasoning.append("AI confirms BEAR TREND — additional confidence for shorts")

        # --- 2. MODEL CONSENSUS ---
        model_signals = await self._query_model_consensus(symbol, setup_type, direction)

        if model_signals.get("has_models"):
            avg_confidence = model_signals.get("avg_confidence", 0)
            agreement_pct = model_signals.get("agreement_pct", 0)

            if agreement_pct >= 0.7:
                confidence_points += 15
                reasoning.append(f"Model consensus STRONG ({agreement_pct:.0%} agree, avg conf {avg_confidence:.0%})")
            elif agreement_pct >= 0.5:
                confidence_points += 5
                reasoning.append(f"Model consensus MODERATE ({agreement_pct:.0%} agree)")
            else:
                confidence_points -= 10
                reasoning.append(f"Model consensus WEAK ({agreement_pct:.0%} agree) — models disagree")
        else:
            reasoning.append("No trained models for this setup — using regime + quality score only")

        # --- 3. QUALITY SCORE ---
        if quality_score >= 80:
            confidence_points += 10
            reasoning.append(f"Quality score HIGH ({quality_score})")
        elif quality_score >= 60:
            confidence_points += 5
        elif quality_score < 40:
            confidence_points -= 10
            reasoning.append(f"Quality score LOW ({quality_score}) — weaker setup")

        # --- 4. LEARNING LOOP FEEDBACK ---
        # Query historical win rate for this specific setup + regime + time context
        # This closes the loop: real outcomes dynamically adjust the gate
        learning_adjustment = await self._get_learning_feedback(setup_type, regime_state)
        if learning_adjustment["has_data"]:
            confidence_points += learning_adjustment["points"]
            if learning_adjustment["reasoning"]:
                reasoning.append(learning_adjustment["reasoning"])
            if learning_adjustment.get("multiplier_adj"):
                position_multiplier *= learning_adjustment["multiplier_adj"]

        # --- 5. DETERMINE DECISION ---
        confidence_score = max(0, min(100, confidence_points))

        if confidence_score >= 65:
            decision = "GO"
            self._stats["go_count"] += 1
            self._stats["today_go"] += 1
        elif confidence_score >= 40:
            decision = "REDUCE"
            position_multiplier *= 0.6
            self._stats["reduce_count"] += 1
            reasoning.append(f"Borderline confidence ({confidence_score}) — reducing to 60% size")
        else:
            decision = "SKIP"
            position_multiplier = 0
            self._stats["skip_count"] += 1
            self._stats["today_skip"] += 1
            reasoning.append(f"Low confidence ({confidence_score}) — skipping trade")

        # Update trading mode based on recent patterns
        self._update_trading_mode(regime_state, ai_regime, regime_score)

        result = {
            "decision": decision,
            "confidence_score": confidence_score,
            "regime_state": regime_state,
            "regime_score": regime_score,
            "ai_regime": ai_regime,
            "trading_mode": self._trading_mode,
            "position_multiplier": round(position_multiplier, 2),
            "reasoning": reasoning,
            "model_signals": model_signals,
            "symbol": symbol,
            "setup_type": setup_type,
            "direction": direction,
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Log decision
        self._decision_log.appendleft(result)

        # Persist to DB if available
        if self._db is not None:
            try:
                self._db["confidence_gate_log"].insert_one({
                    **{k: v for k, v in result.items() if k != "model_signals"},
                    "model_signal_summary": model_signals.get("summary", ""),
                })
            except Exception as e:
                logger.debug(f"Failed to persist confidence gate log: {e}")

        return result

    async def _get_ai_regime(self) -> str:
        """Get AI regime classification from DB data."""
        if self._db is None:
            return "unknown"

        try:
            import numpy as np
            from services.ai_modules.regime_conditional_model import classify_regime

            pipeline = [
                {"$match": {"symbol": "SPY", "bar_size": "1 day"}},
                {"$addFields": {"date_key": {"$substr": [{"$toString": "$date"}, 0, 10]}}},
                {"$sort": {"date": -1}},
                {"$group": {
                    "_id": "$date_key",
                    "close": {"$first": "$close"},
                    "high": {"$first": "$high"},
                    "low": {"$first": "$low"},
                }},
                {"$sort": {"_id": -1}},
                {"$limit": 30},
            ]
            bars = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            if len(bars) < 25:
                return "unknown"

            closes = np.array([b["close"] for b in bars], dtype=float)
            highs = np.array([b["high"] for b in bars], dtype=float)
            lows = np.array([b["low"] for b in bars], dtype=float)
            return classify_regime(closes, highs, lows)
        except Exception as e:
            logger.debug(f"AI regime classification failed: {e}")
            return "unknown"

    async def _query_model_consensus(self, symbol: str, setup_type: str, direction: str = "long") -> Dict[str, Any]:
        """
        Query trained models RELEVANT to this specific setup type and direction for live consensus.
        
        Relevance rules:
        - Setup-specific models: ONLY models matching this exact setup type
        - Direction filtering: SHORT models don't vote on LONG trades and vice versa
        - General direction model: Always included as a baseline (direction-agnostic)
        - Ensemble model: Included only if available
        
        Returns agreement percentage, average confidence, and per-model votes.
        """
        if self._db is None:
            return {"has_models": False, "summary": "No DB connection"}

        try:
            # Determine which models are relevant to this setup
            base_setup = setup_type.upper().replace("_LONG", "").replace("_SHORT", "")
            is_short = direction.lower() == "short" or "SHORT" in setup_type.upper()
            
            # Build TARGETED model search — only models that should vote
            relevant_patterns = []
            
            # 1. Exact setup-type models (e.g., scalp_1min_predictor, scalp_5min_predictor)
            relevant_patterns.append(
                {"model_name": {"$regex": f"^{base_setup.lower()}_.*_predictor$", "$options": "i"}}
            )
            # 2. Short-specific variant if this is a short trade
            if is_short:
                relevant_patterns.append(
                    {"model_name": {"$regex": f"^short_{base_setup.lower()}_.*_predictor$", "$options": "i"}}
                )
            
            # 3. General direction model (always relevant — it's direction-agnostic)
            relevant_patterns.append(
                {"model_name": {"$regex": "^direction_.*_predictor$", "$options": "i"}}
            )
            
            # 4. Ensemble model (cross-timeframe consensus — always relevant)
            relevant_patterns.append(
                {"model_name": {"$regex": "^ensemble_", "$options": "i"}}
            )

            models = list(self._db["timeseries_models"].find(
                {"$or": relevant_patterns},
                {"_id": 0, "model_name": 1, "accuracy": 1, "training_samples": 1, 
                 "setup_type": 1, "bar_size": 1}
            ))

            if not models:
                return {"has_models": False, "summary": f"No trained models for {base_setup}"}

            # Filter out OPPOSITE direction models that slipped through regex
            # E.g., if trade is LONG, exclude any model with "short_" prefix
            filtered_models = []
            for m in models:
                name = m.get("model_name", "").lower()
                if is_short:
                    # For short trades: include short-specific + general, exclude long-specific
                    # General models (direction_, ensemble_) are always included
                    if name.startswith("short_") or name.startswith("direction_") or name.startswith("ensemble_"):
                        filtered_models.append(m)
                    elif not any(name.startswith(f"{s.lower()}_") for s in [
                        "scalp", "orb", "gap_and_go", "vwap", "breakout", "range",
                        "mean_reversion", "reversal", "trend_continuation", "momentum"
                    ]):
                        # Not a known long setup prefix — include (could be general)
                        filtered_models.append(m)
                    # else: it's a long setup model, skip it
                else:
                    # For long trades: include long-specific + general, exclude short-specific
                    if not name.startswith("short_"):
                        filtered_models.append(m)

            if not filtered_models:
                return {"has_models": False, "summary": f"No relevant models for {base_setup} {direction}"}

            # Calculate consensus from filtered models
            accuracies = [m.get("accuracy", 0) for m in filtered_models if m.get("accuracy", 0) > 0]

            if not accuracies:
                return {"has_models": False, "summary": "Models exist but no accuracy data"}

            avg_accuracy = sum(accuracies) / len(accuracies)
            high_confidence_models = sum(1 for a in accuracies if a > 0.55)
            agreement_pct = high_confidence_models / len(accuracies) if accuracies else 0

            # Categorize what voted
            setup_models = [m for m in filtered_models if base_setup.lower() in m.get("model_name", "").lower()]
            general_models = [m for m in filtered_models if "direction_" in m.get("model_name", "")]
            ensemble_models = [m for m in filtered_models if "ensemble_" in m.get("model_name", "")]

            return {
                "has_models": True,
                "models_checked": len(filtered_models),
                "models_with_accuracy": len(accuracies),
                "avg_confidence": round(avg_accuracy, 3),
                "agreement_pct": round(agreement_pct, 3),
                "high_confidence_count": high_confidence_models,
                "setup_models_count": len(setup_models),
                "general_models_count": len(general_models),
                "ensemble_models_count": len(ensemble_models),
                "direction_filter": direction,
                "summary": (
                    f"{len(setup_models)} setup + {len(general_models)} general + {len(ensemble_models)} ensemble models, "
                    f"{high_confidence_models} high-conf, avg acc {avg_accuracy:.1%}"
                ),
            }

        except Exception as e:
            logger.warning(f"Model consensus query failed: {e}")
            return {"has_models": False, "summary": f"Query error: {str(e)[:50]}"}


    async def _get_learning_feedback(self, setup_type: str, regime_state: str) -> Dict[str, Any]:
        """
        Query the Learning Loop for real historical win rates on this setup type + regime context.
        
        Closes the feedback loop: actual trade outcomes dynamically adjust the gate's confidence.
        
        Logic:
        - If this setup type has been winning at 60%+ recently → boost confidence
        - If this setup type has been losing at <40% recently → penalize confidence
        - If this setup type is in edge decay → further penalize + reduce size
        - Minimum sample size of 5 trades to influence (avoids noise)
        """
        result = {"has_data": False, "points": 0, "reasoning": None, "multiplier_adj": None}
        
        try:
            from services.learning_loop_service import get_learning_loop_service
            learning = get_learning_loop_service()
            
            if learning._db is None:
                return result
            
            # Get contextual win rate for this setup + regime combo
            base_setup = setup_type.upper().replace("_LONG", "").replace("_SHORT", "")
            
            win_rate_data = await learning.get_contextual_win_rate(
                setup_type=base_setup,
                market_regime=regime_state
            )
            
            sample_size = win_rate_data.get("sample_size", 0)
            win_rate = win_rate_data.get("win_rate", 0.5)
            confidence_level = win_rate_data.get("confidence", "low")
            ev_r = win_rate_data.get("expected_value_r", 0)
            
            # Need minimum 5 trades to influence the gate
            if sample_size < 5:
                return result
            
            result["has_data"] = True
            
            # Scale impact by sample size confidence
            weight = 1.0 if confidence_level == "high" else 0.6 if confidence_level == "medium" else 0.3
            
            if win_rate >= 0.65:
                # Hot streak — this setup has been winning. Boost confidence.
                pts = int(15 * weight)
                result["points"] = pts
                result["reasoning"] = (
                    f"Learning Loop: {base_setup} winning at {win_rate:.0%} "
                    f"({sample_size} trades, EV {ev_r:.1f}R) — boosting confidence +{pts}"
                )
            elif win_rate >= 0.50:
                # Average performance — slight boost
                pts = int(5 * weight)
                result["points"] = pts
                result["reasoning"] = (
                    f"Learning Loop: {base_setup} at {win_rate:.0%} win rate "
                    f"({sample_size} trades) — slight confidence boost +{pts}"
                )
            elif win_rate >= 0.40:
                # Below average — slight penalty
                pts = int(-5 * weight)
                result["points"] = pts
                result["reasoning"] = (
                    f"Learning Loop: {base_setup} underperforming at {win_rate:.0%} "
                    f"({sample_size} trades) — reducing confidence {pts}"
                )
            else:
                # Losing setup — strong penalty + reduce size
                pts = int(-15 * weight)
                result["points"] = pts
                result["multiplier_adj"] = 0.6
                result["reasoning"] = (
                    f"Learning Loop: {base_setup} COLD at {win_rate:.0%} win rate "
                    f"({sample_size} trades, EV {ev_r:.1f}R) — penalizing confidence {pts}, reducing size 40%"
                )
            
            # Check for edge decay (declining win rate)
            try:
                stats = list(learning._learning_stats_col.find({
                    "setup_type": base_setup,
                    "edge_declining": True
                }))
                if stats:
                    result["points"] -= 5
                    result["reasoning"] = (result["reasoning"] or "") + " | EDGE DECAY detected"
                    if not result.get("multiplier_adj"):
                        result["multiplier_adj"] = 0.8
            except Exception:
                pass
            
            return result
            
        except Exception as e:
            logger.debug(f"Learning feedback query failed (non-critical): {e}")
            return result

    def _update_trading_mode(self, regime_state: str, ai_regime: str, regime_score: int):
        """
        Update SentCom's overall trading mode based on recent regime data.
        """
        if regime_state == "CONFIRMED_DOWN" or ai_regime == "bear_trend":
            self._trading_mode = TradingMode.DEFENSIVE
            self._mode_reason = f"Bear regime detected (score: {regime_score})"
        elif ai_regime == "high_vol":
            self._trading_mode = TradingMode.CAUTIOUS
            self._mode_reason = "High volatility regime — reducing activity"
        elif regime_state == "CONFIRMED_UP" and regime_score >= 70:
            self._trading_mode = TradingMode.AGGRESSIVE
            self._mode_reason = f"Strong bull regime (score: {regime_score})"
        elif regime_state == "CONFIRMED_UP":
            self._trading_mode = TradingMode.NORMAL
            self._mode_reason = f"Moderate bull regime (score: {regime_score})"
        else:
            self._trading_mode = TradingMode.CAUTIOUS
            self._mode_reason = f"Mixed signals — regime neutral (score: {regime_score})"

    def get_trading_mode(self) -> Dict[str, Any]:
        """Get current trading mode for UI display."""
        return {
            "mode": self._trading_mode,
            "reason": self._mode_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_decision_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent decisions for the NIA panel."""
        return list(self._decision_log)[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get confidence gate statistics."""
        total = self._stats["total_evaluated"]
        return {
            **self._stats,
            "go_rate": round(self._stats["go_count"] / total, 3) if total > 0 else 0,
            "skip_rate": round(self._stats["skip_count"] / total, 3) if total > 0 else 0,
            "trading_mode": self._trading_mode,
            "mode_reason": self._mode_reason,
        }

    def get_summary(self) -> Dict[str, Any]:
        """
        Compact summary for the NIA panel header.
        Shows: mode, today's stats, recent decision streak.
        """
        today_eval = self._stats["today_evaluated"]
        today_go = self._stats["today_go"]
        today_skip = self._stats["today_skip"]

        # Recent streak
        streak_type = None
        streak_count = 0
        for d in self._decision_log:
            if streak_type is None:
                streak_type = d["decision"]
                streak_count = 1
            elif d["decision"] == streak_type:
                streak_count += 1
            else:
                break

        return {
            "trading_mode": self._trading_mode,
            "mode_reason": self._mode_reason,
            "today": {
                "evaluated": today_eval,
                "taken": today_go,
                "skipped": today_skip,
                "take_rate": round(today_go / today_eval, 2) if today_eval > 0 else 0,
            },
            "streak": {
                "type": streak_type,
                "count": streak_count,
            } if streak_type else None,
            "total_evaluated": self._stats["total_evaluated"],
        }


# Module-level singleton
_confidence_gate: Optional[ConfidenceGate] = None


def get_confidence_gate() -> ConfidenceGate:
    global _confidence_gate
    if _confidence_gate is None:
        _confidence_gate = ConfidenceGate()
    return _confidence_gate


def init_confidence_gate(db=None) -> ConfidenceGate:
    global _confidence_gate
    _confidence_gate = ConfidenceGate(db=db)
    return _confidence_gate
