"""
Trade Audit Log — post-mortem forensics for every live trade decision.

For each trade that reaches entry, we snapshot:
  - Identity + meta: trade_id, symbol, direction, setup_type, timeframe
  - Entry geometry: entry_price, stop_price, target_prices, shares, risk_amount
  - Decision trail: confidence_gate decision (GO/REDUCE/SKIP), score, reasons
  - Model attribution: model_used, model_version, model_metrics with calibrated
                      thresholds + p_win at entry
  - Sizing multipliers applied: smart_filter, confidence_gate, regime, strategy_tilt, hrp
  - Regime + timestamp for later slicing

Stored in Mongo `trade_audit_log` so post-mortem tooling (and the V5
dashboard's future audit view) can query by trade_id, symbol, setup_type,
model_version, or date range without touching `bot_trades`.

The write is best-effort and NEVER raises — a failure here must not
block the live trade.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "trade_audit_log"


def _safe(obj: Any, attr: str, default: Any = None) -> Any:
    """Read `obj.attr` or `obj[attr]` (in that order) without raising."""
    if obj is None:
        return default
    try:
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)
    except Exception:
        return default


def build_audit_record(
    trade: Any,
    *,
    gate_result: Optional[Dict[str, Any]] = None,
    model_prediction: Optional[Dict[str, Any]] = None,
    regime: Optional[str] = None,
    multipliers: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Pure function — builds the audit document.

    Kept separate from `record_audit_entry` so it's unit-testable without
    a live Mongo connection.
    """
    gate_result = gate_result or {}
    pred = model_prediction or {}
    multipliers = multipliers or {}

    # Pull the calibrated thresholds from the model metrics if present
    model_metrics = pred.get("model_metrics") or {}

    return {
        "trade_id": _safe(trade, "id"),
        "symbol": _safe(trade, "symbol"),
        "direction": (_safe(_safe(trade, "direction"), "value",
                            str(_safe(trade, "direction")))) or None,
        "setup_type": _safe(trade, "setup_type"),
        "timeframe": _safe(trade, "timeframe"),
        "created_at": datetime.now(timezone.utc).isoformat(),

        # Entry geometry
        "entry": {
            "entry_price": _safe(trade, "entry_price"),
            "stop_price": _safe(trade, "stop_price"),
            "target_prices": _safe(trade, "target_prices"),
            "shares": _safe(trade, "shares"),
            "risk_amount": _safe(trade, "risk_amount"),
            "potential_reward": _safe(trade, "potential_reward"),
            "risk_reward_ratio": _safe(trade, "risk_reward_ratio"),
            "quality_score": _safe(trade, "quality_score"),
            "quality_grade": _safe(trade, "quality_grade"),
        },

        # Decision trail from the confidence gate
        "gate": {
            "decision": gate_result.get("decision"),
            "score": gate_result.get("confidence_score"),
            "position_multiplier": gate_result.get("position_multiplier"),
            "reasoning": (gate_result.get("reasoning") or [])[:12],  # cap size
        },

        # Model attribution — includes calibrated thresholds so post-mortems
        # can reconstruct why the gate did/didn't fire for this model.
        "model": {
            "model_used": pred.get("model_used"),
            "model_type": pred.get("model_type"),
            "model_version": pred.get("model_version"),
            "num_classes": pred.get("num_classes"),
            "predicted_direction": pred.get("direction"),
            "p_up": pred.get("probability_up"),
            "p_down": pred.get("probability_down"),
            "p_flat": pred.get("probability_flat"),
            "confidence": pred.get("confidence"),
            "calibrated_up_threshold": model_metrics.get("calibrated_up_threshold"),
            "calibrated_down_threshold": model_metrics.get("calibrated_down_threshold"),
            "accuracy": model_metrics.get("accuracy"),
            "precision_up": model_metrics.get("precision_up"),
            "precision_down": model_metrics.get("precision_down"),
            "recall_up": model_metrics.get("recall_up"),
            "recall_down": model_metrics.get("recall_down"),
        },

        # Sizing stack applied to this trade
        "multipliers": {
            "smart_filter": multipliers.get("smart_filter"),
            "confidence_gate": multipliers.get("confidence_gate"),
            "regime": multipliers.get("regime"),
            "strategy_tilt": multipliers.get("strategy_tilt"),
            "hrp_allocator": multipliers.get("hrp_allocator"),
            "ai_consultation": multipliers.get("ai_consultation"),
        },

        "regime": regime,
    }


def record_audit_entry(
    db,
    trade: Any,
    *,
    gate_result: Optional[Dict[str, Any]] = None,
    model_prediction: Optional[Dict[str, Any]] = None,
    regime: Optional[str] = None,
    multipliers: Optional[Dict[str, float]] = None,
) -> bool:
    """Persist a single audit record. Never raises.

    Returns True on write, False otherwise.
    """
    if db is None:
        return False
    try:
        doc = build_audit_record(
            trade,
            gate_result=gate_result,
            model_prediction=model_prediction,
            regime=regime,
            multipliers=multipliers,
        )
        db[COLLECTION_NAME].insert_one(doc)
        return True
    except Exception as e:
        logger.debug(f"[TradeAudit] Failed to record audit entry: {e}")
        return False


def query_audit(
    db,
    *,
    symbol: Optional[str] = None,
    setup_type: Optional[str] = None,
    model_version: Optional[str] = None,
    since: Optional[str] = None,  # ISO
    limit: int = 200,
) -> list:
    """Query helper used by the upcoming V5 audit view."""
    if db is None:
        return []
    q: Dict[str, Any] = {}
    if symbol:
        q["symbol"] = symbol
    if setup_type:
        q["setup_type"] = setup_type
    if model_version:
        q["model.model_version"] = model_version
    if since:
        q["created_at"] = {"$gte": since}
    try:
        cursor = db[COLLECTION_NAME].find(q, {"_id": 0}).sort("created_at", -1).limit(int(limit))
        return list(cursor)
    except Exception as e:
        logger.debug(f"[TradeAudit] Query failed: {e}")
        return []
