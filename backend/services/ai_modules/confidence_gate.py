"""
AI Confidence Gate — Additive Ensemble Scoring System (v2)
==========================================================
The pre-trade intelligence layer that SentCom checks before every trade.

Flow: Setup Detected → Confidence Gate → Position Sizing → Execute or Skip → Log Decision

Scoring Architecture (ADDITIVE — base 0, earn confirmation points):
    Layer 1: Regime Check (max +20 / floor -10)
    Layer 2: AI Regime (max +10 / floor -5)
    Layer 3: Model Consensus (max +15 / floor -5)
    Layer 4: Live Model Prediction (max +15 / floor -5, weighted by accuracy)
    Layer 5: Cross-Model Agreement (max +5 / floor -5)
    Layer 6: Quality Score (max +10 / floor -5)
    Layer 7: Learning Loop Feedback (max +8 / floor -5)
    Layer 8: CNN Visual Pattern (max +12 / floor -5)
    Layer 9: TFT Multi-Timeframe (max +12 / floor -5)   [Phase 5 DL]
    Layer 10: VAE Regime Detection (max +8 / floor -5)   [Phase 5 DL]
    Layer 11: CNN-LSTM Temporal (max +10 / floor -5)     [Phase 5 DL]
    Layer 12: Ensemble Meta-Labeler P(win) (max +15 + bet-sizing)  [Phase 8 — hard skip if <50%]
    Layer 13: FinBERT News Sentiment (max +10 / floor -5)  [Phase 5c — aligned with direction]

Decision Thresholds:
    >= 55 pts  → GO (full size)
    >= 30 pts  → REDUCE (60% size)
    <  30 pts  → SKIP

Key Design: Adding more DL models creates more confirmation signals, not more kill switches.
Floor protection (-10 max per gate) prevents any single factor from vetoing a trade.

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
        self._calibrated_thresholds = None  # Loaded from gate_calibration collection
        self._finbert_scorer = None  # Lazy-init on first Layer 13 call
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
        # Load calibrated thresholds if available
        self._load_calibrated_thresholds()
        # Hydrate from MongoDB (recent decisions + today's stats)
        self._load_from_db()

    def _load_from_db(self):
        """Load recent decisions and today's stats from confidence_gate_log in MongoDB."""
        if self._db is None:
            return
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            # Load recent decisions (last 50) into memory
            recent = list(self._db["confidence_gate_log"].find(
                {},
                {"_id": 0, "model_signals": 0}
            ).sort("timestamp", -1).limit(50))
            
            # Add to deque — newest first (appendleft maintains order since we iterate newest→oldest)
            for d in recent:
                self._decision_log.append(d)
            
            # 2026-04-30 v15: count TODAY's decisions directly from the DB,
            # not from the 50-doc deque hydrated above. Operator flagged
            # that the SentCom Intelligence panel always reset to ≤50
            # evaluations on restart even when the bot had evaluated 80+
            # since midnight UTC. Root cause: `for d in recent` could only
            # see the last 50 decisions, so today_evaluated was capped at
            # min(len(recent_today), 50). Counting via Mongo aggregation
            # surfaces the true daily totals while the deque continues to
            # hold only the last 50 for the recent-decision log UI.
            today_eval = 0
            today_go = 0
            today_reduce = 0
            today_skip = 0
            try:
                today_pipeline = [
                    {"$match": {"timestamp": {"$regex": f"^{today}"}}},
                    {"$group": {
                        "_id": "$decision",
                        "n": {"$sum": 1},
                    }},
                ]
                for row in self._db["confidence_gate_log"].aggregate(today_pipeline):
                    n = int(row.get("n") or 0)
                    today_eval += n
                    dec = row.get("_id")
                    if dec == "GO":
                        today_go = n
                    elif dec == "REDUCE":
                        today_reduce = n
                    elif dec == "SKIP":
                        today_skip = n
            except Exception as agg_err:
                # Fall back to the deque-based count if aggregation fails
                # (transient Mongo flap, etc.) so the UI still shows
                # *something* useful.
                logger.debug(
                    "[ConfidenceGate] today aggregation fallback (%s); "
                    "using deque count", agg_err,
                )
                for d in recent:
                    ts = str(d.get("timestamp", ""))
                    if ts.startswith(today):
                        today_eval += 1
                        dec = d.get("decision", "")
                        if dec == "GO":
                            today_go += 1
                        elif dec == "REDUCE":
                            today_reduce += 1
                        elif dec == "SKIP":
                            today_skip += 1
            
            # Compute lifetime stats from DB
            total = self._db["confidence_gate_log"].count_documents({})
            go_total = self._db["confidence_gate_log"].count_documents({"decision": "GO"})
            reduce_total = self._db["confidence_gate_log"].count_documents({"decision": "REDUCE"})
            skip_total = self._db["confidence_gate_log"].count_documents({"decision": "SKIP"})
            
            self._stats.update({
                "total_evaluated": total,
                "go_count": go_total,
                "reduce_count": reduce_total,
                "skip_count": skip_total,
                "today_evaluated": today_eval,
                "today_go": today_go,
                "today_skip": today_skip,
                "today_date": today,
            })
            
            # Set trading mode from most recent decision's regime
            if recent:
                last = recent[0]
                regime = last.get("regime_state", "")
                mode = last.get("trading_mode", "normal")
                if mode and mode != "normal":
                    self._trading_mode = mode
                    self._mode_reason = f"Restored from last session — {regime}"
                elif regime:
                    self._mode_reason = f"Last regime: {regime}"
            
            if total > 0:
                logger.info(
                    f"Confidence gate loaded from DB: {total} total, "
                    f"{today_eval} today ({today_go} GO, {today_skip} SKIP), "
                    f"{len(recent)} recent decisions in memory"
                )
        except Exception as e:
            logger.warning(f"Failed to load confidence gate history from DB: {e}")

    def _load_calibrated_thresholds(self):
        """Load auto-calibrated thresholds from DB (if available)."""
        if self._db is None:
            return
        try:
            from services.ai_modules.gate_calibrator import GateCalibrator
            cal = GateCalibrator(db=self._db)
            thresholds = cal.load_calibrated_thresholds()
            if thresholds:
                self._calibrated_thresholds = thresholds
                logger.info(f"Loaded calibrated gate thresholds: {thresholds}")
        except Exception as e:
            logger.debug(f"No calibrated thresholds available: {e}")

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
        confidence_points = 0  # ADDITIVE: Start at 0, earn confirmation points
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

        # --- 1. REGIME CHECK (max +20 / floor -10) ---
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

        # AI regime classification (logged for analysis but no longer penalizes scoring)
        try:
            ai_regime = await self._get_ai_regime()
        except Exception:
            pass

        # Update trading mode FIRST so thresholds are mode-aware for this evaluation
        self._update_trading_mode(regime_state, ai_regime, regime_score)

        # Regime contribution — graduated scale
        if regime_state == "CONFIRMED_UP" and direction == "long":
            confidence_points += 20
            reasoning.append(f"Regime BULLISH (score {regime_score}) — strongly aligned with long (+20)")
        elif regime_state == "CONFIRMED_UP" and direction == "short":
            confidence_points -= 10  # Floor: max -10 for regime
            position_multiplier *= 0.7
            reasoning.append("Regime BULLISH — against short entry (-10, size -30%)")
        elif regime_state == "CONFIRMED_DOWN" and direction == "long":
            confidence_points -= 10  # Floor: max -10 for regime
            position_multiplier *= 0.7
            reasoning.append(f"Regime BEARISH (score {regime_score}) — against long entry (-10, size -30%)")
        elif regime_state == "CONFIRMED_DOWN" and direction == "short":
            confidence_points += 15
            reasoning.append("Regime BEARISH — aligned with short entry (+15)")
        elif regime_state in ("HOLD", "NEUTRAL"):
            # Neutral regime — moderate boost if score leans our way
            if regime_score >= 60 and direction == "long":
                confidence_points += 10
                reasoning.append(f"Regime leans bullish (score {regime_score}) — moderate alignment (+10)")
            elif regime_score <= 40 and direction == "short":
                confidence_points += 10
                reasoning.append(f"Regime leans bearish (score {regime_score}) — moderate alignment (+10)")
            else:
                reasoning.append(f"Regime NEUTRAL (score {regime_score}) — no directional confirmation")
        else:
            reasoning.append(f"Regime state '{regime_state}' (score {regime_score})")

        # AI regime classification removed — no longer logged in reasoning

        # --- 2. MODEL CONSENSUS (max +15 / floor -5) ---
        model_signals = await self._query_model_consensus(symbol, setup_type, direction)

        if model_signals.get("has_models"):
            avg_confidence = model_signals.get("avg_confidence", 0)
            agreement_pct = model_signals.get("agreement_pct", 0)
            models_count = model_signals.get("models_checked", 0)

            if agreement_pct >= 0.7:
                confidence_points += 15
                reasoning.append(f"Model consensus STRONG ({agreement_pct:.0%} of {models_count} models, avg acc {avg_confidence:.0%}) (+15)")
            elif agreement_pct >= 0.5:
                confidence_points += 8
                reasoning.append(f"Model consensus MODERATE ({agreement_pct:.0%} of {models_count} models) (+8)")
            elif agreement_pct >= 0.3:
                # Weak but present — neutral, don't penalize
                reasoning.append(f"Model consensus MIXED ({agreement_pct:.0%} of {models_count} models, avg acc {avg_confidence:.0%}) — no score adjustment")
            else:
                # Very low agreement — small penalty
                confidence_points -= 3
                reasoning.append(f"Model consensus LOW ({agreement_pct:.0%} of {models_count} models) — weak signal (-3)")
        else:
            reasoning.append("No trained models for this setup — using regime + quality score only")

        # --- 2b. LIVE MODEL PREDICTION (max +15 / floor -5, weighted by accuracy) ---
        live_prediction = await self._get_live_prediction(symbol, setup_type, direction)
        if live_prediction.get("has_prediction"):
            pred_direction = live_prediction["direction"]
            pred_confidence = live_prediction["confidence"]
            pred_model = live_prediction.get("model_used", "unknown")
            
            # Weight by model accuracy (if available)
            model_accuracy = live_prediction.get("model_accuracy", 0.55)
            accuracy_weight = min(1.0, max(0.5, (model_accuracy - 0.45) / 0.2))  # 0.5-1.0 weight
            
            # Does the model agree with the proposed trade direction?
            trade_is_long = direction.lower() in ("long", "buy")
            model_agrees = (
                (trade_is_long and pred_direction == "up") or
                (not trade_is_long and pred_direction == "down")
            )
            
            # MODE-C calibration (2026-04-23): 3-class setup-specific LONG models
            # max out at 0.44–0.53 on triple-barrier data (FLAT class absorbs
            # probability mass). A correctly directional UP argmax at 0.50 is
            # a real edge — bucket it into CONFIRMS, not "leans". Preserves the
            # old 0.6 for STRONG disagreements so floor penalties aren't noisy.
            #
            # Per-model calibration (P1 2026-04-23 follow-up): each model now
            # carries calibrated_up_threshold / calibrated_down_threshold in
            # its ModelMetrics (derived from top-20% of training predictions,
            # bounded [0.45, 0.60]). Use it when available so each model
            # operates at its own natural probability range.
            from services.ai_modules.threshold_calibration import get_effective_threshold
            model_metrics = live_prediction.get("model_metrics") or {}
            CONFIRMS_THRESHOLD = get_effective_threshold(model_metrics, direction)
            if model_agrees and pred_confidence >= CONFIRMS_THRESHOLD:
                pts = int(15 * accuracy_weight)
                confidence_points += pts
                reasoning.append(
                    f"Live {pred_model} CONFIRMS {direction.upper()} "
                    f"({pred_direction}, {pred_confidence:.0%} conf ≥ {CONFIRMS_THRESHOLD:.2f}, weight {accuracy_weight:.1f}) (+{pts})"
                )
            elif model_agrees:
                pts = int(5 * accuracy_weight)
                confidence_points += pts
                reasoning.append(
                    f"Live {pred_model} leans {direction.upper()} "
                    f"({pred_confidence:.0%} conf) (+{pts})"
                )
            elif pred_direction == "flat":
                confidence_points -= 2
                reasoning.append(
                    f"Live {pred_model} sees NO EDGE (flat, {pred_confidence:.0%} conf) (-2)"
                )
            else:
                # Model disagrees — floor protection: max -5. Strong disagreement
                # (conf ≥ 0.6) still the heavy penalty; weak disagreement (<0.6)
                # gets a softer -3 so low-confidence noise doesn't over-veto.
                if pred_confidence >= 0.60:
                    confidence_points -= 5
                    position_multiplier *= 0.85
                    reasoning.append(
                        f"Live {pred_model} DISAGREES STRONGLY — predicts {pred_direction.upper()} "
                        f"vs proposed {direction.upper()} ({pred_confidence:.0%} conf) (-5, size -15%)"
                    )
                else:
                    confidence_points -= 3
                    reasoning.append(
                        f"Live {pred_model} weakly disagrees — predicts {pred_direction.upper()} "
                        f"vs proposed {direction.upper()} ({pred_confidence:.0%} conf) (-3)"
                    )

        # --- 2c. CROSS-MODEL AGREEMENT (max +5 / floor -5) ---
        cross_model_agreement = None
        if model_signals.get("has_models") and live_prediction.get("has_prediction"):
            consensus_agrees = model_signals.get("agreement_pct", 0) >= 0.5
            live_agrees = live_prediction.get("has_prediction") and (
                (direction.lower() in ("long", "buy") and live_prediction["direction"] == "up") or
                (direction.lower() not in ("long", "buy") and live_prediction["direction"] == "down")
            )
            
            if consensus_agrees and live_agrees:
                cross_model_agreement = "aligned"
                confidence_points += 5
                reasoning.append("Cross-model: consensus + live prediction ALIGNED (+5)")
            elif not consensus_agrees and not live_agrees:
                cross_model_agreement = "both_disagree"
                confidence_points -= 5  # Floor
                position_multiplier *= 0.9
                reasoning.append("Cross-model: consensus + live BOTH AGAINST (-5, size -10%)")
            else:
                cross_model_agreement = "mixed"
                reasoning.append(
                    f"Cross-model: MIXED signals (consensus {'agrees' if consensus_agrees else 'disagrees'}, "
                    f"live {'agrees' if live_agrees else 'disagrees'})"
                )

        # --- 3. QUALITY SCORE (max +10 / floor -5) ---
        if quality_score >= 80:
            confidence_points += 10
            reasoning.append(f"Quality score HIGH ({quality_score}) (+10)")
        elif quality_score >= 60:
            confidence_points += 5
            reasoning.append(f"Quality score GOOD ({quality_score}) (+5)")
        elif quality_score >= 40:
            # Neutral — no points
            reasoning.append(f"Quality score AVERAGE ({quality_score})")
        else:
            confidence_points -= 5  # Floor
            reasoning.append(f"Quality score LOW ({quality_score}) — weaker setup (-5)")

        # --- 4. LEARNING LOOP FEEDBACK (max +8 / floor -5) ---
        # Query historical win rate for this specific setup + regime + time context
        learning_adjustment = await self._get_learning_feedback(setup_type, regime_state)
        if learning_adjustment["has_data"]:
            # Cap the learning loop contribution with floor protection
            pts = learning_adjustment["points"]
            pts = max(-5, min(8, pts))  # Floor -5, cap +8
            confidence_points += pts
            if learning_adjustment["reasoning"]:
                reasoning.append(learning_adjustment["reasoning"])
            if learning_adjustment.get("multiplier_adj"):
                position_multiplier *= learning_adjustment["multiplier_adj"]

        # --- 4b. CNN VISUAL PATTERN SIGNAL (max +12 / floor -5) ---
        cnn_signal = await self._get_cnn_signal(symbol, setup_type, direction)
        if cnn_signal.get("has_prediction"):
            cnn_win_prob = cnn_signal["win_probability"]
            cnn_pattern = cnn_signal["pattern"]
            cnn_conf = cnn_signal["pattern_confidence"]

            if cnn_win_prob >= 0.65:
                confidence_points += 12
                reasoning.append(
                    f"CNN visual analysis: HIGH win probability ({cnn_win_prob:.0%}) — "
                    f"pattern '{cnn_pattern}' ({cnn_conf:.0%} conf) (+12)"
                )
            elif cnn_win_prob >= 0.50:
                confidence_points += 5
                reasoning.append(
                    f"CNN visual analysis: moderate win probability ({cnn_win_prob:.0%}) — "
                    f"pattern '{cnn_pattern}' (+5)"
                )
            elif cnn_win_prob < 0.35:
                confidence_points -= 5  # Floor: max -5
                position_multiplier *= 0.9
                reasoning.append(
                    f"CNN visual analysis: LOW win probability ({cnn_win_prob:.0%}) — "
                    f"chart looks unfavorable (-5, size -10%)"
                )
            else:
                reasoning.append(
                    f"CNN visual analysis: neutral ({cnn_win_prob:.0%}) — no strong visual signal"
                )

        # --- 5a. TFT MULTI-TIMEFRAME SIGNAL (max +12 / floor -5) ---
        tft_signal = await self._get_tft_signal(symbol, direction)
        if tft_signal.get("has_prediction"):
            tft_direction = tft_signal["direction"]
            tft_confidence = tft_signal["confidence"]
            tft_model_acc = tft_signal.get("model_accuracy", 0.5)

            # GATE: DL models must show real edge (≥52% accuracy) before they can
            # influence live trade decisions. Below that, they're likely stuck in
            # majority-class collapse (worse than coin flip). Skipping here is
            # preferable to the old floor-at-0.5 weight, which let a 35%-accurate
            # model still contribute 50% weight to every entry.
            if tft_model_acc < 0.52:
                reasoning.append(
                    f"TFT signal IGNORED — model accuracy {tft_model_acc:.1%} below 52% threshold "
                    f"(likely majority-class collapse; rebuild with triple-barrier targets)"
                )
            else:
                trade_is_long = direction.lower() in ("long", "buy")
                tft_agrees = (
                    (trade_is_long and tft_direction == "up") or
                    (not trade_is_long and tft_direction == "down")
                )

                accuracy_weight = min(1.0, max(0.5, (tft_model_acc - 0.45) / 0.2))

                if tft_agrees and tft_confidence >= 0.6:
                    pts = int(12 * accuracy_weight)
                    confidence_points += pts
                    tf_info = tft_signal.get("timeframe_weights", {})
                    top_tf = max(tf_info, key=tf_info.get) if tf_info else "unknown"
                    reasoning.append(
                        f"TFT multi-timeframe CONFIRMS {direction.upper()} "
                        f"({tft_confidence:.0%} conf, top TF: {top_tf}) (+{pts})"
                    )
                elif tft_agrees:
                    pts = int(5 * accuracy_weight)
                    confidence_points += pts
                    reasoning.append(
                        f"TFT leans {direction.upper()} ({tft_confidence:.0%} conf) (+{pts})"
                    )
                elif tft_direction == "flat":
                    confidence_points -= 2
                    reasoning.append(f"TFT sees NO EDGE (flat, {tft_confidence:.0%} conf) (-2)")
                else:
                    confidence_points -= 5
                    reasoning.append(
                        f"TFT DISAGREES — predicts {tft_direction.upper()} "
                        f"vs proposed {direction.upper()} (-5)"
                    )

        # --- 5b. VAE REGIME SIGNAL (max +8 / floor -5) ---
        vae_signal = await self._get_vae_regime_signal(direction)
        if vae_signal.get("has_prediction"):
            vae_regime = vae_signal["regime"]
            vae_confidence = vae_signal["confidence"]
            vae_diversity = vae_signal.get("regime_diversity", 1.0)

            # GATE: refuse VAE signal if the trained VAE collapsed to a single
            # regime (mode collapse). Diversity = entropy of regime assignment
            # across training samples, normalized to [0,1]. Below 0.3 the VAE
            # is essentially picking the same regime for every sample and its
            # regime classification is meaningless.
            if vae_diversity < 0.3:
                reasoning.append(
                    f"VAE signal IGNORED — regime diversity {vae_diversity:.2f} below 0.3 threshold "
                    f"(mode collapse; rebuild VAE with balanced regime distribution)"
                )
            else:
                trade_is_long = direction.lower() in ("long", "buy")

                if vae_regime == "bull_trending" and trade_is_long:
                    pts = min(8, int(8 * vae_confidence))
                    confidence_points += pts
                    reasoning.append(f"VAE detects BULL TRENDING regime ({vae_confidence:.0%} conf) — aligned (+{pts})")
                elif vae_regime == "bear_trending" and not trade_is_long:
                    pts = min(8, int(8 * vae_confidence))
                    confidence_points += pts
                    reasoning.append(f"VAE detects BEAR TRENDING regime ({vae_confidence:.0%} conf) — aligned (+{pts})")
                elif vae_regime == "momentum_surge":
                    confidence_points += 5
                    reasoning.append(f"VAE detects MOMENTUM SURGE ({vae_confidence:.0%} conf) — high conviction (+5)")
                elif vae_regime == "high_volatility":
                    confidence_points -= 5
                    position_multiplier *= 0.85
                    reasoning.append(f"VAE detects HIGH VOLATILITY regime ({vae_confidence:.0%}) — reducing exposure (-5, size -15%)")
                elif vae_regime == "mean_reverting":
                    reasoning.append(f"VAE detects MEAN REVERTING regime ({vae_confidence:.0%}) — neutral")
                elif (vae_regime == "bull_trending" and not trade_is_long) or (vae_regime == "bear_trending" and trade_is_long):
                    confidence_points -= 5
                    reasoning.append(f"VAE regime {vae_regime.upper()} AGAINST {direction.upper()} (-5)")

        # --- 5c. CNN-LSTM TEMPORAL SIGNAL (max +10 / floor -5) ---
        cnn_lstm_signal = await self._get_cnn_lstm_signal(symbol, direction)
        if cnn_lstm_signal.get("has_prediction"):
            lstm_direction = cnn_lstm_signal["direction"]
            lstm_win_prob = cnn_lstm_signal["win_probability"]
            lstm_confidence = cnn_lstm_signal["confidence"]
            lstm_model_acc = cnn_lstm_signal.get("model_accuracy", 0.5)

            # GATE: same DL-accuracy floor as TFT. Models below 52% are likely
            # majority-class-collapsed and must not contribute to live scoring.
            if lstm_model_acc < 0.52:
                reasoning.append(
                    f"CNN-LSTM signal IGNORED — model accuracy {lstm_model_acc:.1%} below 52% threshold "
                    f"(likely majority-class collapse; rebuild with triple-barrier targets)"
                )
            else:
                trade_is_long = direction.lower() in ("long", "buy")
                lstm_agrees = (
                    (trade_is_long and lstm_direction == "up") or
                    (not trade_is_long and lstm_direction == "down")
                )

                if lstm_agrees and lstm_win_prob >= 0.6:
                    confidence_points += 10
                    reasoning.append(
                        f"CNN-LSTM temporal: HIGH win prob ({lstm_win_prob:.0%}), "
                        f"pattern evolving favorably (+10)"
                    )
                elif lstm_agrees and lstm_win_prob >= 0.5:
                    confidence_points += 5
                    reasoning.append(f"CNN-LSTM temporal: moderate ({lstm_win_prob:.0%}) (+5)")
                elif not lstm_agrees and lstm_win_prob < 0.4:
                    confidence_points -= 5
                    position_multiplier *= 0.9
                    reasoning.append(
                        f"CNN-LSTM temporal: pattern UNFAVORABLE ({lstm_win_prob:.0%}) "
                        f"predicts {lstm_direction.upper()} (-5, size -10%)"
                    )
                else:
                    reasoning.append(f"CNN-LSTM temporal: neutral ({lstm_win_prob:.0%})")

        # --- Layer 12: ENSEMBLE META-LABELER P(WIN) (bet-sizing + hard skip) ---
        # Uses the binary ensemble_<setup> trained in Phase 8 to compute P(win)
        # for the proposed trade. Drives both:
        #   - Confidence score (up to +15)
        #   - Position multiplier (0.5× → 1.5× Kelly-inspired ramp)
        #   - Hard SKIP when p_win < 0.5 (meta-labeler sees no edge)
        ensemble_meta = await self._get_ensemble_meta_signal(symbol, setup_type)
        force_skip = False
        if ensemble_meta.get("has_prediction"):
            p_win = ensemble_meta["p_win"]
            ens_name = ensemble_meta.get("ensemble_name", "ensemble")
            ens_acc = ensemble_meta.get("ensemble_accuracy", 0.0)

            # Scoring contribution
            if p_win >= 0.75:
                confidence_points += 15
                reasoning.append(
                    f"Ensemble meta-labeler {ens_name}: P(win)={p_win:.0%} STRONG "
                    f"(model acc {ens_acc:.0%}) — bet-size MAX (+15)"
                )
            elif p_win >= 0.65:
                confidence_points += 10
                reasoning.append(
                    f"Ensemble meta-labeler {ens_name}: P(win)={p_win:.0%} high — bet-size boost (+10)"
                )
            elif p_win >= 0.55:
                confidence_points += 5
                reasoning.append(
                    f"Ensemble meta-labeler {ens_name}: P(win)={p_win:.0%} moderate — full size (+5)"
                )
            elif p_win >= 0.50:
                # Borderline — no score boost, but keep trade at half size
                reasoning.append(
                    f"Ensemble meta-labeler {ens_name}: P(win)={p_win:.0%} borderline — half size"
                )
            else:
                # Meta-labeler says no edge — FORCE SKIP
                force_skip = True
                reasoning.append(
                    f"Ensemble meta-labeler {ens_name}: P(win)={p_win:.0%} < 50% — NO EDGE, skipping trade"
                )

            # Bet-sizing multiplier (only applied when not force-skipping)
            if not force_skip:
                from services.ai_modules.ensemble_live_inference import bet_size_multiplier_from_p_win
                bet_mult = bet_size_multiplier_from_p_win(p_win)
                position_multiplier *= bet_mult
        else:
            # No meta-labeler available — surface why so we can diagnose live
            miss_reason = ensemble_meta.get("reason_if_missing", "unknown")
            reasoning.append(f"Ensemble meta-labeler unavailable: {miss_reason}")
            logger.info(f"Ensemble meta-labeler miss for {symbol}/{setup_type}: {miss_reason}")

        # --- Layer 13: FINBERT NEWS SENTIMENT (max +10 / floor -5) ---
        # Queries pre-scored news_sentiment collection (populated by
        # FinBERTSentiment.score_unscored_articles batch job). Aligned sentiment
        # with trade direction earns points; opposing sentiment penalizes.
        # Graceful no-op when < min_articles or scorer unavailable.
        try:
            if self._finbert_scorer is None and self._db is not None:
                from services.ai_modules.finbert_sentiment import FinBERTSentiment
                self._finbert_scorer = FinBERTSentiment(db=self._db)

            if self._finbert_scorer is not None:
                sent = self._finbert_scorer.get_symbol_sentiment(
                    symbol, lookback_days=2, min_articles=3
                )
                if sent.get("has_sentiment"):
                    raw_score = float(sent.get("score", 0.0))
                    n_articles = int(sent.get("article_count", 0))
                    sconf = float(sent.get("confidence", 0.0))

                    # Align sentiment with trade direction (long = positive is good, short = negative is good)
                    is_long = (direction or "long").lower() == "long"
                    aligned_score = raw_score if is_long else -raw_score

                    # Scale by agreement confidence to discount mixed signals
                    effective = aligned_score * max(0.5, sconf)

                    if effective >= 0.5:
                        confidence_points += 10
                        reasoning.append(
                            f"FinBERT sentiment: {sent['sentiment']} (score={raw_score:+.2f}, "
                            f"{n_articles} articles, conf={sconf:.0%}) aligned STRONG (+10)"
                        )
                    elif effective >= 0.25:
                        confidence_points += 6
                        reasoning.append(
                            f"FinBERT sentiment: {sent['sentiment']} (score={raw_score:+.2f}, "
                            f"{n_articles} articles) aligned (+6)"
                        )
                    elif effective >= 0.10:
                        confidence_points += 3
                        reasoning.append(
                            f"FinBERT sentiment: {sent['sentiment']} (score={raw_score:+.2f}, "
                            f"{n_articles} articles) mild alignment (+3)"
                        )
                    elif effective <= -0.5:
                        confidence_points -= 5  # Floor: max -5 for sentiment
                        reasoning.append(
                            f"FinBERT sentiment: {sent['sentiment']} (score={raw_score:+.2f}, "
                            f"{n_articles} articles, conf={sconf:.0%}) OPPOSES trade (-5)"
                        )
                    elif effective <= -0.25:
                        confidence_points -= 3
                        reasoning.append(
                            f"FinBERT sentiment: {sent['sentiment']} (score={raw_score:+.2f}, "
                            f"{n_articles} articles) opposes trade (-3)"
                        )
                    else:
                        # Neutral or low-confidence — no contribution
                        reasoning.append(
                            f"FinBERT sentiment: neutral/weak (score={raw_score:+.2f}, "
                            f"{n_articles} articles)"
                        )
                else:
                    ac = sent.get("article_count", 0)
                    reasoning.append(f"FinBERT sentiment: no data ({ac} articles < min 3)")
        except Exception as e:
            # Never let FinBERT fail the gate — log and skip
            logger.warning(f"Layer 13 FinBERT skipped for {symbol}: {e}")

        # --- 6. DETERMINE DECISION (Mode-aware thresholds) ---
        # Additive scoring: base 0, earn points from confirmation
        confidence_score = max(0, min(100, confidence_points))

        # Use calibrated thresholds if available, else defaults
        mode = self._trading_mode
        mode_key = mode.lower() if isinstance(mode, str) else "normal"
        
        if self._calibrated_thresholds and mode_key in self._calibrated_thresholds:
            cal = self._calibrated_thresholds[mode_key]
            go_threshold = cal["go"]
            reduce_threshold = cal["reduce"]
        elif mode == TradingMode.AGGRESSIVE:
            go_threshold = 28
            reduce_threshold = 18
        elif mode == TradingMode.NORMAL:
            go_threshold = 38
            reduce_threshold = 25
        elif mode == TradingMode.CAUTIOUS:
            go_threshold = 50
            reduce_threshold = 35
        else:  # DEFENSIVE
            go_threshold = 60
            reduce_threshold = 45

        if force_skip:
            # Meta-labeler hard veto — overrides any positive score
            decision = "SKIP"
            position_multiplier = 0
            self._stats["skip_count"] += 1
            self._stats["today_skip"] += 1
        elif confidence_score >= go_threshold:
            decision = "GO"
            self._stats["go_count"] += 1
            self._stats["today_go"] += 1
        elif confidence_score >= reduce_threshold:
            decision = "REDUCE"
            position_multiplier *= 0.6
            self._stats["reduce_count"] += 1
            reasoning.append(f"Borderline confidence ({confidence_score}, need {go_threshold} for GO) — reducing to 60% size")
        else:
            decision = "SKIP"
            position_multiplier = 0
            self._stats["skip_count"] += 1
            self._stats["today_skip"] += 1
            reasoning.append(f"Insufficient confirmation ({confidence_score}, need {reduce_threshold}) — skipping trade")

        result = {
            "decision": decision,
            "confidence_score": confidence_score,
            "scoring_version": "additive_v1",  # Track scoring system version for migration
            "regime_state": regime_state,
            "regime_score": regime_score,
            "ai_regime": ai_regime,
            "trading_mode": self._trading_mode,
            "position_multiplier": round(position_multiplier, 2),
            "reasoning": reasoning,
            "model_signals": model_signals,
            "live_prediction": live_prediction if live_prediction.get("has_prediction") else None,
            "learning_feedback": learning_adjustment if learning_adjustment.get("has_data") else None,
            "cross_model_agreement": cross_model_agreement,
            "cnn_signal": cnn_signal if cnn_signal.get("has_prediction") else None,
            "tft_signal": tft_signal if tft_signal.get("has_prediction") else None,
            "vae_regime_signal": vae_signal if vae_signal.get("has_prediction") else None,
            "cnn_lstm_signal": cnn_lstm_signal if cnn_lstm_signal.get("has_prediction") else None,
            "ensemble_meta_signal": ensemble_meta if ensemble_meta.get("has_prediction") else None,
            "symbol": symbol,
            "setup_type": setup_type,
            "direction": direction,
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Log decision
        self._decision_log.appendleft(result)

        # GAP 5: Persist to DB with outcome-trackable fields for auto-calibration
        if self._db is not None:
            try:
                # Safely serialize — convert numpy types to Python natives
                import json
                log_data = {k: v for k, v in result.items() if k != "model_signals"}
                log_data["model_signal_summary"] = model_signals.get("summary", "")
                log_data["scoring_version"] = "additive_v1"
                log_data["outcome_tracked"] = False
                log_data["trade_outcome"] = None
                log_data["outcome_pnl"] = None
                
                # Force JSON round-trip to convert numpy/non-standard types
                clean = json.loads(json.dumps(log_data, default=str))
                self._db["confidence_gate_log"].insert_one(clean)
            except Exception as e:
                logger.warning(f"Failed to persist confidence gate log: {e}")

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
            
            # Map scanner setup types → training model base names
            # Scanner uses descriptive names; training uses canonical categories
            SETUP_TO_MODEL = {
                "VWAP_BOUNCE": ["VWAP"], "FIRST_VWAP_PULLBACK": ["VWAP"],
                "VWAP_FADE": ["VWAP", "SHORT_VWAP"],
                "SQUEEZE": ["BREAKOUT", "RANGE"], "BREAKOUT_CONFIRMED": ["BREAKOUT"],
                "HOD_BREAKOUT": ["BREAKOUT", "MOMENTUM"],
                "APPROACHING_BREAKOUT": ["BREAKOUT"], "APPROACHING_HOD": ["BREAKOUT"],
                "APPROACHING_RANGE_BREAK": ["RANGE", "BREAKOUT"],
                "RANGE_BREAK_CONFIRMED": ["RANGE", "BREAKOUT"],
                "RUBBER_BAND": ["MEAN_REVERSION"],
                "MEAN_REVERSION": ["MEAN_REVERSION"],
                "SECOND_CHANCE": ["TREND_CONTINUATION", "BREAKOUT"],
                "FASHIONABLY_LATE": ["TREND_CONTINUATION"],
                "OPENING_DRIVE": ["ORB", "MOMENTUM"], "ORB_LONG_CONFIRMED": ["ORB"],
                "APPROACHING_ORB": ["ORB"],
                "GAP_GIVE_GO": ["GAP_AND_GO"], "GAP_FADE": ["SHORT_GAP_FADE"],
                "9_EMA_SCALP": ["SCALP"], "ABC_SCALP": ["SCALP"],
                "SPENCER_SCALP": ["SCALP"], "PUPPY_DOG": ["SCALP"],
                "BIG_DOG": ["MOMENTUM", "TREND_CONTINUATION"],
                "TIDAL_WAVE": ["MOMENTUM", "BREAKOUT"],
                "HITCHHIKER": ["TREND_CONTINUATION"],
                "VOLUME_CAPITULATION": ["REVERSAL", "MEAN_REVERSION"],
                "BACKSIDE": ["REVERSAL", "SHORT_REVERSAL"],
                "OFF_SIDES_SHORT": ["SHORT_BREAKDOWN", "SHORT_MOMENTUM"],
                "CHART_PATTERN": ["BREAKOUT", "RANGE"],
                # Swing/Position setups map to broader model categories
                "DAILY_SQUEEZE": ["BREAKOUT", "RANGE"],
                "DAILY_BREAKOUT": ["BREAKOUT", "MOMENTUM"],
                "TREND_CONTINUATION": ["TREND_CONTINUATION", "MOMENTUM"],
                "BASE_BREAKOUT": ["BREAKOUT", "TREND_CONTINUATION"],
                "ACCUMULATION_ENTRY": ["REVERSAL", "MEAN_REVERSION"],
                "RELATIVE_STRENGTH_POSITION": ["MOMENTUM", "TREND_CONTINUATION"],
                "EARNINGS_MOMENTUM": ["MOMENTUM", "BREAKOUT"],
                "SECTOR_ROTATION": ["MOMENTUM", "TREND_CONTINUATION"],
                "BREAKDOWN_CONFIRMED": ["SHORT_BREAKDOWN", "SHORT_MOMENTUM"],
                "GAP_FADE_DAILY": ["SHORT_GAP_FADE", "SHORT_VWAP"],
                "SHORT_SQUEEZE_FADE": ["SHORT_SCALP", "REVERSAL"],
            }
            
            # Get mapped model base names, fallback to the raw setup name
            model_bases = SETUP_TO_MODEL.get(base_setup, [base_setup])
            
            # Build TARGETED model search — only models that should vote
            relevant_patterns = []
            
            for mb in model_bases:
                # Setup-specific models (e.g., vwap_5min_predictor, breakout_1min_predictor)
                relevant_patterns.append(
                    {"name": {"$regex": f"^{mb.lower()}_.*_predictor$", "$options": "i"}}
                )
                # Short-specific variant if this is a short trade
                if is_short and not mb.startswith("SHORT_"):
                    relevant_patterns.append(
                        {"name": {"$regex": f"^short_{mb.lower()}_.*_predictor$", "$options": "i"}}
                    )
            
            # General direction model (always relevant — it's direction-agnostic)
            relevant_patterns.append(
                {"name": {"$regex": "^direction_.*_predictor$", "$options": "i"}}
            )
            
            # Ensemble model (cross-timeframe consensus — always relevant)
            relevant_patterns.append(
                {"name": {"$regex": "^ensemble_", "$options": "i"}}
            )

            models = list(self._db["timeseries_models"].find(
                {"$or": relevant_patterns},
                {"_id": 0, "name": 1, "metrics": 1, "version": 1}
            ))

            if not models:
                return {"has_models": False, "summary": f"No trained models for {base_setup}"}

            # Filter out OPPOSITE direction models that slipped through regex
            # E.g., if trade is LONG, exclude any model with "short_" prefix
            filtered_models = []
            for m in models:
                mname = m.get("name", "").lower()
                if is_short:
                    if mname.startswith("short_") or mname.startswith("direction_") or mname.startswith("ensemble_"):
                        filtered_models.append(m)
                    elif not any(mname.startswith(f"{s.lower()}_") for s in [
                        "scalp", "orb", "gap_and_go", "vwap", "breakout", "range",
                        "mean_reversion", "reversal", "trend_continuation", "momentum"
                    ]):
                        filtered_models.append(m)
                else:
                    if not mname.startswith("short_"):
                        filtered_models.append(m)

            if not filtered_models:
                return {"has_models": False, "summary": f"No relevant models for {base_setup} {direction}"}

            # Extract accuracy from metrics sub-document (metrics.accuracy)
            accuracies = []
            for m in filtered_models:
                metrics = m.get("metrics", {}) or {}
                acc = metrics.get("accuracy", 0) or 0
                if acc > 0:
                    accuracies.append(acc)

            if not accuracies:
                # Models exist but haven't been evaluated yet — treat as available with baseline
                return {
                    "has_models": True,
                    "models_checked": len(filtered_models),
                    "models_with_accuracy": 0,
                    "avg_confidence": 0.5,  # Baseline: no data = neutral
                    "agreement_pct": 0.5,
                    "high_confidence_count": 0,
                    "setup_models_count": len(filtered_models),
                    "general_models_count": 0,
                    "ensemble_models_count": 0,
                    "direction_filter": direction,
                    "summary": f"{len(filtered_models)} models found (no accuracy data yet — neutral consensus)",
                }

            avg_accuracy = sum(accuracies) / len(accuracies)
            # For 3-class models (up/down/flat), random chance = 33%.
            # Accuracy > 40% = meaningful edge. For 2-class, > 52% = edge.
            high_confidence_models = sum(1 for a in accuracies if a > 0.40)
            agreement_pct = high_confidence_models / len(accuracies) if accuracies else 0

            # Categorize what voted
            setup_models = [m for m in filtered_models if any(mb.lower() in m.get("name", "").lower() for mb in model_bases)]
            general_models = [m for m in filtered_models if "direction_" in m.get("name", "")]
            ensemble_models = [m for m in filtered_models if "ensemble_" in m.get("name", "")]

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


    async def _get_live_prediction(self, symbol: str, setup_type: str, direction: str) -> Dict[str, Any]:
        """
        Run predict_for_setup() to get the model's real-time prediction for this symbol.
        
        This is the critical "super model" wire — it takes the setup-specific (or general)
        trained model and asks it: "Right now, for this symbol, what direction do you predict?"
        
        The prediction feeds directly into confidence scoring:
        - Model agrees with proposed direction → confidence boost
        - Model disagrees → confidence penalty + size reduction
        - Model says flat → slight penalty (no edge detected)
        
        Runs in a thread pool since predict_for_setup() does synchronous DB queries
        for regime features.
        """
        result = {"has_prediction": False}
        
        try:
            from services.ai_modules.timeseries_service import get_timeseries_ai
            import asyncio
            
            ts_ai = get_timeseries_ai()
            if ts_ai is None or ts_ai._db is None:
                return result
            
            # Get recent bars for this symbol (need bars for feature extraction)
            # Use the most recent bars from ib_historical_data
            def _fetch_and_predict():
                try:
                    bars = list(ts_ai._db["ib_historical_data"].find(
                        {"symbol": symbol, "bar_size": "5 mins"},
                        {"_id": 0}
                    ).sort("date", -1).limit(200))
                    
                    if len(bars) < 50:
                        # Try daily bars as fallback
                        bars = list(ts_ai._db["ib_historical_data"].find(
                            {"symbol": symbol, "bar_size": "1 day"},
                            {"_id": 0}
                        ).sort("date", -1).limit(200))
                    
                    if len(bars) < 50:
                        return None
                    
                    # Reverse to chronological order (oldest first)
                    bars.reverse()
                    
                    # Call predict_for_setup — this is the core ML inference
                    prediction = ts_ai.predict_for_setup(symbol, bars, setup_type)
                    return prediction
                except Exception as e:
                    logger.debug(f"Live prediction fetch/predict failed for {symbol}: {e}")
                    return None
            
            # Run in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(None, _fetch_and_predict)
            
            if prediction is None:
                return result
            
            result["has_prediction"] = True
            result["direction"] = prediction.get("direction", "flat")
            result["confidence"] = prediction.get("confidence", 0.0)
            result["prob_up"] = prediction.get("probability_up", 0.5)
            result["prob_down"] = prediction.get("probability_down", 0.5)
            result["model_used"] = prediction.get("model_used", "unknown")
            result["model_type"] = prediction.get("model_type", "unknown")
            # Pass through model metrics (incl. calibrated_up_threshold /
            # calibrated_down_threshold) so the CONFIRMS check can use per-
            # model thresholds instead of a global 0.50.
            result["model_metrics"] = prediction.get("model_metrics") or {}
            
            if prediction.get("regime_adjustment"):
                result["regime_adjustment"] = prediction["regime_adjustment"]
            
            return result
            
        except Exception as e:
            logger.debug(f"Live prediction failed (non-critical): {e}")
            return result

    async def _get_cnn_signal(self, symbol: str, setup_type: str, direction: str) -> Dict[str, Any]:
        """
        Get CNN visual pattern analysis for the current chart.
        
        Loads the trained CNN model for this setup type and generates a prediction
        from the latest bar data. Returns pattern classification and win probability.
        """
        result = {"has_prediction": False}

        try:
            import asyncio
            from services.ai_modules.chart_pattern_cnn import (
                load_model_from_db, predict_from_image,
                CNN_WINDOW_SIZES, DEFAULT_WINDOW_SIZE
            )
            from services.ai_modules.chart_image_generator import generate_live_chart_tensor

            if self._db is None:
                return result

            def _run_cnn():
                try:
                    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES
                    profiles = SETUP_TRAINING_PROFILES.get(setup_type, [])
                    bar_size = "1 day"
                    if profiles:
                        bar_size = profiles[0]["bar_size"]

                    model, metadata = load_model_from_db(self._db, setup_type, bar_size)
                    if model is None:
                        return None

                    window_size = CNN_WINDOW_SIZES.get(setup_type, DEFAULT_WINDOW_SIZE)
                    tensor, chart_meta = generate_live_chart_tensor(
                        self._db, symbol, bar_size, window_size
                    )
                    if tensor is None:
                        return None

                    prediction = predict_from_image(model, tensor)
                    prediction["model_accuracy"] = metadata.get("metrics", {}).get("accuracy", 0)
                    return prediction
                except Exception as e:
                    logger.debug(f"CNN inference failed for {symbol}/{setup_type}: {e}")
                    return None

            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(None, _run_cnn)

            if prediction is None:
                return result

            result["has_prediction"] = True
            result["pattern"] = prediction.get("pattern", "UNKNOWN")
            result["pattern_confidence"] = prediction.get("pattern_confidence", 0)
            result["win_probability"] = prediction.get("win_probability", 0.5)
            result["top_patterns"] = prediction.get("top_patterns", [])
            result["model_accuracy"] = prediction.get("model_accuracy", 0)
            return result

        except Exception as e:
            logger.debug(f"CNN signal failed (non-critical): {e}")
            return result

    async def _get_tft_signal(self, symbol: str, direction: str) -> Dict[str, Any]:
        """Get TFT multi-timeframe prediction."""
        result = {"has_prediction": False}
        try:
            import asyncio
            from services.ai_modules.temporal_fusion_transformer import TFTModel

            if self._db is None:
                return result

            def _run_tft():
                try:
                    tft = TFTModel(db=self._db)
                    if not tft.load_model():
                        return None

                    # Gather multi-timeframe bars for this symbol
                    bars_by_tf = {}
                    for tf in ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]:
                        cursor = self._db["ib_historical_data"].find(
                            {"symbol": symbol, "bar_size": tf},
                            {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
                        ).sort("date", -1).limit(200)
                        bars = list(cursor)
                        if bars:
                            bars.reverse()  # chronological order
                            bars_by_tf[tf] = bars

                    if "1 day" not in bars_by_tf:
                        return None

                    return tft.predict(bars_by_tf, symbol)
                except Exception as e:
                    logger.debug(f"TFT inference failed for {symbol}: {e}")
                    return None

            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(None, _run_tft)
            return prediction if prediction else result

        except Exception as e:
            logger.debug(f"TFT signal failed (non-critical): {e}")
            return result

    async def _get_vae_regime_signal(self, direction: str) -> Dict[str, Any]:
        """Get VAE regime detection signal."""
        result = {"has_prediction": False}
        try:
            import asyncio
            from services.ai_modules.vae_regime import VAERegimeModel

            if self._db is None:
                return result

            def _run_vae():
                try:
                    vae = VAERegimeModel(db=self._db)
                    if not vae.load_model():
                        return None

                    # Load SPY + sector ETF bars
                    bars_by_symbol = {}
                    for sym in ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLE"]:
                        cursor = self._db["ib_historical_data"].find(
                            {"symbol": sym, "bar_size": "1 day"},
                            {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
                        ).sort("date", -1).limit(100)
                        bars = list(cursor)
                        if bars:
                            bars.reverse()
                            bars_by_symbol[sym] = bars

                    if "SPY" not in bars_by_symbol:
                        return None

                    prediction = vae.predict(bars_by_symbol)
                    if prediction.get("regime") != "unknown":
                        prediction["has_prediction"] = True
                    return prediction
                except Exception as e:
                    logger.debug(f"VAE regime inference failed: {e}")
                    return None

            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(None, _run_vae)
            return prediction if prediction else result

        except Exception as e:
            logger.debug(f"VAE regime signal failed (non-critical): {e}")
            return result

    async def _get_ensemble_meta_signal(self, symbol: str, setup_type: str) -> Dict[str, Any]:
        """Get ensemble meta-labeler P(win) prediction for this symbol+setup.

        Thin async wrapper that runs the synchronous live inference in a thread
        executor (because it does DB queries and XGBoost CPU work).
        """
        if self._db is None:
            return {"has_prediction": False, "reason_if_missing": "no_db"}
        try:
            import asyncio
            from services.ai_modules.ensemble_live_inference import predict_meta_label_p_win

            def _run():
                return predict_meta_label_p_win(self._db, symbol, setup_type)

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _run)
        except Exception as exc:
            logger.debug(f"Ensemble meta signal failed (non-critical) for {symbol}/{setup_type}: {exc}")
            return {"has_prediction": False, "reason_if_missing": f"exception:{exc}"}

    async def _get_cnn_lstm_signal(self, symbol: str, direction: str) -> Dict[str, Any]:
        """Get CNN-LSTM temporal pattern signal."""
        result = {"has_prediction": False}
        try:
            import asyncio
            from services.ai_modules.cnn_lstm_model import CNNLSTMModel

            if self._db is None:
                return result

            def _run_cnn_lstm():
                try:
                    model = CNNLSTMModel(db=self._db)
                    if not model.load_model():
                        return None

                    cursor = self._db["ib_historical_data"].find(
                        {"symbol": symbol, "bar_size": "1 day"},
                        {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
                    ).sort("date", -1).limit(200)
                    bars = list(cursor)
                    if not bars or len(bars) < 60:
                        return None

                    bars.reverse()
                    return model.predict(bars, symbol)
                except Exception as e:
                    logger.debug(f"CNN-LSTM inference failed for {symbol}: {e}")
                    return None

            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(None, _run_cnn_lstm)
            return prediction if prediction else result

        except Exception as e:
            logger.debug(f"CNN-LSTM signal failed (non-critical): {e}")
            return result

    def _update_trading_mode(self, regime_state: str, ai_regime: str, regime_score: int):
        """
        Update SentCom's overall trading mode based on Market Regime Engine.
        AI regime (classify_regime) removed — it duplicated the market regime with stale data.
        VAE regime still contributes via Layer 10 confidence gate scoring.
        """
        if regime_state == "CONFIRMED_DOWN":
            self._trading_mode = TradingMode.DEFENSIVE
            self._mode_reason = f"Bear regime confirmed (score: {regime_score})"
        elif regime_state == "CONFIRMED_UP" and regime_score >= 70:
            self._trading_mode = TradingMode.AGGRESSIVE
            self._mode_reason = f"Strong bull regime (score: {regime_score})"
        elif regime_state == "CONFIRMED_UP":
            self._trading_mode = TradingMode.NORMAL
            self._mode_reason = f"Moderate bull regime (score: {regime_score})"
        elif regime_score >= 55:
            self._trading_mode = TradingMode.NORMAL
            self._mode_reason = f"Leaning bullish (score: {regime_score})"
        elif regime_score <= 45:
            self._trading_mode = TradingMode.CAUTIOUS
            self._mode_reason = f"Leaning bearish (score: {regime_score})"
        else:
            self._trading_mode = TradingMode.CAUTIOUS
            self._mode_reason = f"Neutral regime (score: {regime_score})"

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

    async def record_trade_outcome(
        self, symbol: str, setup_type: str, outcome: str, pnl: float = 0
    ) -> bool:
        """
        GAP 5: Close the feedback loop by recording trade outcomes against gate decisions.
        
        Called by the learning loop when a trade is closed. Finds the most recent
        gate decision for this symbol+setup and updates it with the outcome.
        
        This data enables the future Confidence Gate Tuner (P2) to auto-calibrate
        GO/REDUCE/SKIP thresholds by analyzing which decisions led to wins/losses.
        
        Args:
            symbol: Trade symbol
            setup_type: Setup type used
            outcome: "win", "loss", or "scratch"
            pnl: Actual P&L of the trade
            
        Returns:
            True if a matching gate decision was found and updated
        """
        if self._db is None:
            return False
            
        try:
            result = self._db["confidence_gate_log"].find_one_and_update(
                {
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "outcome_tracked": False,
                },
                {
                    "$set": {
                        "outcome_tracked": True,
                        "trade_outcome": outcome,
                        "outcome_pnl": pnl,
                        "outcome_recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
                sort=[("timestamp", -1)],  # Most recent decision first
            )
            if result:
                logger.debug(
                    f"Gate outcome recorded: {symbol} {setup_type} "
                    f"decision={result.get('decision')} → outcome={outcome} pnl={pnl:.2f}"
                )
                return True
            return False
        except Exception as e:
            logger.debug(f"Failed to record gate outcome: {e}")
            return False

    def get_decision_accuracy(self, limit: int = 100) -> Dict[str, Any]:
        """
        GAP 5: Get accuracy stats for gate decisions — how often did GO lead to wins?
        
        Returns breakdown of outcomes per decision type for the Gate Tuner.
        """
        if self._db is None:
            return {"has_data": False}
            
        try:
            pipeline = [
                {"$match": {"outcome_tracked": True}},
                {"$sort": {"timestamp": -1}},
                {"$limit": limit},
                {"$group": {
                    "_id": "$decision",
                    "total": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$eq": ["$trade_outcome", "win"]}, 1, 0]}},
                    "losses": {"$sum": {"$cond": [{"$eq": ["$trade_outcome", "loss"]}, 1, 0]}},
                    "scratches": {"$sum": {"$cond": [{"$eq": ["$trade_outcome", "scratch"]}, 1, 0]}},
                    "total_pnl": {"$sum": {"$ifNull": ["$outcome_pnl", 0]}},
                    "avg_confidence": {"$avg": "$confidence_score"},
                }},
            ]
            results = list(self._db["confidence_gate_log"].aggregate(pipeline))
            
            accuracy = {}
            for r in results:
                decision = r["_id"]
                total = r["total"]
                wins = r["wins"]
                accuracy[decision] = {
                    "total": total,
                    "wins": wins,
                    "losses": r["losses"],
                    "scratches": r["scratches"],
                    "win_rate": round(wins / total, 3) if total > 0 else 0,
                    "total_pnl": round(r["total_pnl"], 2),
                    "avg_confidence": round(r["avg_confidence"], 1),
                }
            
            return {"has_data": bool(accuracy), "decisions": accuracy}
        except Exception as e:
            logger.debug(f"Decision accuracy query failed: {e}")
            return {"has_data": False}


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
