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
        model_signals = await self._query_model_consensus(symbol, setup_type)

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

        # --- 4. DETERMINE DECISION ---
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

    async def _query_model_consensus(self, symbol: str, setup_type: str) -> Dict[str, Any]:
        """
        Query trained models relevant to this setup type for consensus.
        Returns agreement percentage and average confidence.
        """
        if self._db is None:
            return {"has_models": False, "summary": "No DB connection"}

        try:
            # Find models matching this setup type
            base_setup = setup_type.split("_long")[0].split("_short")[0]
            patterns = [
                {"model_name": {"$regex": f".*{base_setup}.*", "$options": "i"}},
                {"model_name": {"$regex": ".*direction.*", "$options": "i"}},
                {"model_name": {"$regex": ".*ensemble.*", "$options": "i"}},
            ]

            models = list(self._db["timeseries_models"].find(
                {"$or": patterns},
                {"_id": 0, "model_name": 1, "accuracy": 1, "training_samples": 1}
            ))

            if not models:
                return {"has_models": False, "summary": f"No trained models for {base_setup}"}

            # Calculate consensus from model accuracies
            # Models with high accuracy = higher confidence signal
            accuracies = [m.get("accuracy", 0) for m in models if m.get("accuracy", 0) > 0]

            if not accuracies:
                return {"has_models": False, "summary": "Models exist but no accuracy data"}

            avg_accuracy = sum(accuracies) / len(accuracies)
            high_confidence_models = sum(1 for a in accuracies if a > 0.55)
            agreement_pct = high_confidence_models / len(accuracies) if accuracies else 0

            return {
                "has_models": True,
                "models_checked": len(models),
                "models_with_accuracy": len(accuracies),
                "avg_confidence": round(avg_accuracy, 3),
                "agreement_pct": round(agreement_pct, 3),
                "high_confidence_count": high_confidence_models,
                "summary": f"{len(models)} models, {high_confidence_models} high-conf, avg acc {avg_accuracy:.1%}",
            }

        except Exception as e:
            logger.warning(f"Model consensus query failed: {e}")
            return {"has_models": False, "summary": f"Query error: {str(e)[:50]}"}

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
