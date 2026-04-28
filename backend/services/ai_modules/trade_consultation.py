"""
AI Trade Consultation Service - Pre-Trade AI Analysis Integration

Wires the AI modules (Debate, Risk Manager, Institutional Flow, Volume)
into the trading bot decision flow.

When enabled, every trade setup runs through:
1. Bull/Bear Debate - Should we take this trade?
2. AI Risk Manager - What's the risk profile?
3. Institutional Flow - Any ownership concerns?
4. Volume Analysis - Any unusual activity?

All decisions are logged via Shadow Tracker for learning.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AITradeConsultation:
    """
    Pre-trade consultation service that runs AI modules before execution.
    
    Integration points:
    - Called after trade object is created
    - Before trade is executed or added to pending
    - Returns recommendation to proceed, pass, or adjust
    
    Shadow Mode behavior:
    - Always logs decisions to Shadow Tracker
    - Only blocks/modifies trades if shadow mode is OFF
    """
    
    def __init__(self):
        self._module_config = None
        self._shadow_tracker = None
        self._debate_agents = None
        self._risk_manager = None
        self._institutional_flow = None
        self._volume_anomaly = None
        self._timeseries_ai = None
        self._enabled = False
        
    def inject_services(
        self,
        module_config=None,
        shadow_tracker=None,
        debate_agents=None,
        risk_manager=None,
        institutional_flow=None,
        volume_anomaly=None,
        timeseries_ai=None
    ):
        """Inject AI module services"""
        self._module_config = module_config
        self._shadow_tracker = shadow_tracker
        self._debate_agents = debate_agents
        self._risk_manager = risk_manager
        self._institutional_flow = institutional_flow
        self._volume_anomaly = volume_anomaly
        self._timeseries_ai = timeseries_ai
        self._enabled = module_config is not None
        
        if self._enabled:
            logger.info("AI Trade Consultation enabled - pre-trade analysis active")
            
    async def consult_on_trade(
        self,
        trade: Dict,
        market_context: Dict,
        portfolio: Dict = None,
        bars: list = None
    ) -> Dict[str, Any]:
        """
        Run AI consultation on a potential trade.
        
        Args:
            trade: Trade dict with symbol, direction, entry, stop, target, etc.
            market_context: Current market regime, VIX, trends
            portfolio: Current portfolio state (positions, exposure)
            bars: Recent OHLCV bars for volume analysis
            
        Returns:
            {
                "proceed": bool,  # Should execute the trade?
                "size_adjustment": float,  # Position size multiplier (0.5 = half size)
                "reasoning": str,  # Summary of AI analysis
                "debate_result": dict,  # Full debate output
                "risk_assessment": dict,  # Full risk assessment
                "institutional_context": dict,  # Ownership context
                "volume_context": dict,  # Volume analysis
                "shadow_logged": bool,  # Was this logged to shadow tracker?
                "shadow_decision_id": str  # ID for tracking outcome
            }
        """
        if not self._enabled or not self._module_config:
            return self._default_proceed_result()
            
        result = {
            "proceed": True,
            "size_adjustment": 1.0,
            "reasoning": "",
            "debate_result": None,
            "risk_assessment": None,
            "institutional_context": None,
            "volume_context": None,
            "timeseries_forecast": None,
            "shadow_logged": False,
            "shadow_decision_id": None
        }
        
        symbol = trade.get("symbol", "")
        direction = trade.get("direction", "long")
        if hasattr(direction, 'value'):
            direction = direction.value
            
        entry_price = trade.get("entry_price", 0)
        stop_price = trade.get("stop_price", 0)
        target_prices = trade.get("target_prices", [])
        target_price = target_prices[0] if target_prices else entry_price
        shares = trade.get("shares", 0)
        setup_type = trade.get("setup_type", "unknown")
        quality_score = trade.get("quality_score", 0)
        risk_reward = trade.get("risk_reward_ratio", 0)
        
        # Build setup dict for AI modules
        setup = {
            "setup_type": setup_type,
            "direction": direction,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "tqs_score": quality_score,
            "quality_score": quality_score,
            "risk_reward": risk_reward,
            "confirmations": trade.get("confirmations", []),
            "historical_win_rate": trade.get("historical_win_rate", 0.5),
            "atr_pct": trade.get("atr_percent", 2.0)
        }
        
        # Track which modules contributed
        modules_used = []
        all_signals = []
        
        # ==================== 0. GET TIME-SERIES FORECAST FIRST ====================
        # Fetch forecast early so it can be passed to the debate
        ai_forecast = None
        if self._module_config.is_timeseries_enabled() and self._timeseries_ai and bars:
            try:
                ai_forecast = await self._timeseries_ai.get_forecast(
                    symbol=symbol,
                    bars=bars
                )
                logger.info(f"Time-Series forecast for {symbol}: {ai_forecast.get('direction')} "
                           f"(confidence: {ai_forecast.get('confidence', 0):.0%})")
            except Exception as e:
                logger.warning(f"Time-series forecast fetch failed for {symbol}: {e}")
        
        # ==================== 1. BULL/BEAR DEBATE (now with AI forecast) ====================
        if self._module_config.is_debate_enabled() and self._debate_agents:
            try:
                # Pass AI forecast to debate for integrated decision making
                debate = await self._debate_agents.run_debate(
                    symbol=symbol,
                    setup=setup,
                    market_context=market_context,
                    technical_data=market_context.get("technicals", {}),
                    portfolio=portfolio,
                    ai_forecast=ai_forecast  # NEW: Pass forecast to debate
                )
                
                result["debate_result"] = debate.to_dict()
                modules_used.append("debate_agents")
                
                # Note if AI was used in debate
                if debate.ai_forecast_used:
                    modules_used.append("timeseries_ai_in_debate")
                
                # Apply debate recommendation
                if debate.final_recommendation == "pass":
                    ai_note = f" (AI: {debate.ai_advisor_signal})" if debate.ai_advisor_signal else ""
                    all_signals.append(f"Debate: PASS ({debate.winner} case prevailed){ai_note}")
                    # Only block if NOT in shadow mode
                    if not self._module_config.is_shadow_mode("debate_agents"):
                        result["proceed"] = False
                        result["reasoning"] = f"Bull/Bear Debate rejected: {debate.reasoning}"
                elif debate.final_recommendation == "reduce_size":
                    all_signals.append("Debate: REDUCE SIZE (close debate)")
                    if not self._module_config.is_shadow_mode("debate_agents"):
                        result["size_adjustment"] = min(result["size_adjustment"], 0.7)
                else:
                    ai_note = ""
                    if debate.ai_forecast_used and debate.ai_advisor_signal:
                        ai_note = f" | AI: {debate.ai_advisor_signal}"
                    all_signals.append(f"Debate: PROCEED ({debate.winner}, confidence {debate.combined_confidence:.0%}){ai_note}")
                    
            except Exception as e:
                logger.warning(f"Debate failed for {symbol}: {e}")
                
        # ==================== 2. AI RISK MANAGER ====================
        if self._module_config.is_risk_manager_enabled() and self._risk_manager:
            try:
                account_value = portfolio.get("account_value", 100000) if portfolio else 100000
                
                assessment = await self._risk_manager.assess_risk(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    position_size_shares=shares,
                    account_value=account_value,
                    setup=setup,
                    market_context=market_context,
                    portfolio=portfolio
                )
                
                result["risk_assessment"] = assessment.to_dict()
                modules_used.append("ai_risk_manager")
                
                # Apply risk recommendation
                if assessment.recommendation == "block":
                    all_signals.append(f"Risk: BLOCKED (score {assessment.total_risk_score}/10)")
                    if not self._module_config.is_shadow_mode("ai_risk_manager"):
                        result["proceed"] = False
                        result["reasoning"] = f"AI Risk Manager blocked: {assessment.reasoning}"
                elif assessment.recommendation == "reduce_size":
                    all_signals.append(f"Risk: REDUCE SIZE ({assessment.risk_level}, {assessment.size_adjustment}x)")
                    if not self._module_config.is_shadow_mode("ai_risk_manager"):
                        result["size_adjustment"] = min(
                            result["size_adjustment"], 
                            assessment.size_adjustment
                        )
                else:
                    all_signals.append(f"Risk: OK ({assessment.risk_level}, score {assessment.total_risk_score}/10)")
                    
            except Exception as e:
                logger.warning(f"Risk assessment failed for {symbol}: {e}")
                
        # ==================== 3. INSTITUTIONAL FLOW ====================
        if self._module_config.is_institutional_flow_enabled() and self._institutional_flow:
            try:
                context = await self._institutional_flow.get_ownership_context(symbol)
                
                result["institutional_context"] = context.to_dict()
                modules_used.append("institutional_flow")
                
                # Apply institutional signals
                if context.recommendation == "caution":
                    all_signals.append(f"Institutional: CAUTION - {context.signals[0] if context.signals else 'ownership concern'}")
                    if not self._module_config.is_shadow_mode("institutional_flow"):
                        result["size_adjustment"] = min(result["size_adjustment"], 0.8)
                elif context.signals:
                    all_signals.append(f"Institutional: {context.signals[0]}")
                    
            except Exception as e:
                logger.warning(f"Institutional flow failed for {symbol}: {e}")
                
        # ==================== 4. VOLUME ANALYSIS ====================
        if bars and self._volume_anomaly:
            try:
                vol_context = self._volume_anomaly.get_volume_context_for_trade(
                    symbol=symbol,
                    bars=bars,
                    direction=direction
                )
                
                result["volume_context"] = vol_context
                modules_used.append("volume_analysis")
                
                # Apply volume signals
                if vol_context.get("signals"):
                    all_signals.extend(vol_context["signals"][:2])  # Top 2 signals
                    
                if vol_context.get("recommendation") == "volume_caution":
                    if not self._module_config.is_shadow_mode("institutional_flow"):
                        result["size_adjustment"] = min(result["size_adjustment"], 0.85)
                        
            except Exception as e:
                logger.warning(f"Volume analysis failed for {symbol}: {e}")
                
        # ==================== 5. TIME-SERIES AI (store result) ====================
        # Note: Forecast was already fetched in section 0 for the debate
        # Here we just store it in the result and apply any additional signals
        if ai_forecast and ai_forecast.get("usable", False):
            # Get consultation context from forecast
            ts_context = self._timeseries_ai.get_consultation_context(
                forecast=ai_forecast,
                direction=direction
            )
            
            result["timeseries_forecast"] = {
                "forecast": ai_forecast,
                "context": ts_context
            }
            
            # Only add to modules_used if not already added via debate
            if "timeseries_ai" not in modules_used and "timeseries_ai_in_debate" not in modules_used:
                modules_used.append("timeseries_ai")
            
            # Apply timeseries signals (only if debate is NOT enabled)
            # This avoids double-counting the AI's contribution
            if not self._module_config.is_debate_enabled():
                if ts_context.get("signal"):
                    all_signals.append(f"TimeSeries: {ts_context['signal']}")
                    
                # Apply risk adjustment based on alignment
                if ts_context.get("align_with_trade") == "contrary":
                    # Forecast contradicts trade direction
                    if not self._module_config.is_shadow_mode("timeseries_ai"):
                        result["size_adjustment"] = min(
                            result["size_adjustment"], 
                            0.7  # Reduce size when AI contradicts
                        )
                
        # ==================== BUILD COMBINED REASONING ====================
        if all_signals:
            result["reasoning"] = " | ".join(all_signals)
        else:
            result["reasoning"] = "No AI modules active"
            
        # ==================== LOG TO SHADOW TRACKER ====================
        if self._shadow_tracker and modules_used:
            try:
                # Determine combined recommendation
                if not result["proceed"]:
                    combined_rec = "pass"
                elif result["size_adjustment"] < 1.0:
                    combined_rec = "reduce_size"
                else:
                    combined_rec = "proceed"

                # 2026-04-29 fix: timeseries_ai shadow-tracking gap.
                # Previously, log_decision only got `timeseries_forecast`
                # when ai_forecast.usable=True — meaning low-confidence
                # forecasts (which are themselves a TS decision: "I
                # abstain") and forecasts consumed by the debate path
                # were never credited to the timeseries_ai bucket. As
                # a result `/shadow/performance` showed
                # `timeseries_ai: 0 decisions` despite the module
                # firing on every consultation. We now pass the raw
                # forecast in both cases so log_decision tags
                # timeseries_ai in modules_used.
                ts_payload = result.get("timeseries_forecast")
                if not ts_payload and ai_forecast:
                    ts_payload = {
                        "forecast": ai_forecast,
                        "context": None,
                        "consulted_but_unusable": not ai_forecast.get("usable", False),
                        "consumed_by_debate": "timeseries_ai_in_debate" in modules_used,
                    }

                decision = await self._shadow_tracker.log_decision(
                    symbol=symbol,
                    trigger_type="trade_opportunity",
                    price_at_decision=entry_price,
                    market_regime=market_context.get("regime", ""),
                    vix_level=market_context.get("vix", 0),
                    debate_result=result["debate_result"],
                    risk_assessment=result["risk_assessment"],
                    institutional_context=result["institutional_context"],
                    timeseries_forecast=ts_payload,
                    combined_recommendation=combined_rec,
                    confidence_score=self._calculate_combined_confidence(result),
                    reasoning=result["reasoning"],
                    was_executed=result["proceed"],  # Will be updated later
                    execution_reason="Pre-trade consultation"
                )

                result["shadow_logged"] = True
                result["shadow_decision_id"] = decision.id

                logger.info(f"Shadow logged {symbol}: {combined_rec} (modules: {', '.join(modules_used)})")

            except Exception as e:
                logger.warning(f"Shadow logging failed: {e}")
                
        return result
        
    def _calculate_combined_confidence(self, result: Dict) -> float:
        """Calculate combined confidence from all module outputs"""
        confidences = []
        
        if result.get("debate_result"):
            confidences.append(result["debate_result"].get("combined_confidence", 0.5))
            
        if result.get("risk_assessment"):
            # Convert risk score to confidence (lower risk = higher confidence)
            risk_score = result["risk_assessment"].get("total_risk_score", 5)
            confidences.append(1 - (risk_score / 10))
            
        if result.get("institutional_context"):
            # Convert risk_score to confidence
            inst_risk = result["institutional_context"].get("risk_score", 3)
            confidences.append(1 - (inst_risk / 10))
            
        if result.get("timeseries_forecast"):
            ts_forecast = result["timeseries_forecast"].get("forecast", {})
            ts_confidence = ts_forecast.get("confidence", 0)
            confidences.append(ts_confidence)
            
        if confidences:
            return sum(confidences) / len(confidences)
        return 0.5
        
    def _default_proceed_result(self) -> Dict[str, Any]:
        """Return default result when AI consultation is disabled"""
        return {
            "proceed": True,
            "size_adjustment": 1.0,
            "reasoning": "AI consultation not enabled",
            "debate_result": None,
            "risk_assessment": None,
            "institutional_context": None,
            "volume_context": None,
            "timeseries_forecast": None,
            "shadow_logged": False,
            "shadow_decision_id": None
        }
        
    def get_status(self) -> Dict[str, Any]:
        """Get consultation service status"""
        return {
            "enabled": self._enabled,
            "modules_available": {
                "debate": self._debate_agents is not None,
                "risk_manager": self._risk_manager is not None,
                "institutional_flow": self._institutional_flow is not None,
                "volume_anomaly": self._volume_anomaly is not None,
                "timeseries_ai": self._timeseries_ai is not None
            },
            "modules_enabled": {
                "debate": self._module_config.is_debate_enabled() if self._module_config else False,
                "risk_manager": self._module_config.is_risk_manager_enabled() if self._module_config else False,
                "institutional_flow": self._module_config.is_institutional_flow_enabled() if self._module_config else False,
                "timeseries_ai": self._module_config.is_timeseries_enabled() if self._module_config else False,
            },
            "shadow_mode": self._module_config.is_shadow_mode() if self._module_config else True
        }


# Singleton
_ai_consultation: Optional[AITradeConsultation] = None


def get_ai_consultation() -> AITradeConsultation:
    """Get singleton instance"""
    global _ai_consultation
    if _ai_consultation is None:
        _ai_consultation = AITradeConsultation()
    return _ai_consultation


def init_ai_consultation(**services) -> AITradeConsultation:
    """Initialize with services"""
    consultation = get_ai_consultation()
    consultation.inject_services(**services)
    return consultation
