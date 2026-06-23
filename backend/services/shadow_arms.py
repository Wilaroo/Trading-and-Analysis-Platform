"""Shadow-arm harness (P3, Seam 3) — feeds the EXISTING shadow_mode_service
engine with arm-tagged counterfactual signals so each decision-logic change is
measured as a paper "shadow trade" before it ever touches capital.

Per evaluated alert it records up to three arms into `shadow_signals`:
  • champion      — what the live dual-gate actually decided (baseline)
  • unified_1a2a  — the unified verdict (TQS-anchored, single size) [Arm A1]
  • gate_off      — TQS-only, confidence gate ignored               [Arm A2]

Each is tagged {tier:"shadow", arm:<name>, alert_id:<live alert>} and scored by
the already-scheduled `update_signal_outcomes()` (would-have R from geometry).
NOTHING is sent to IB; this NEVER mutates live state and is fully guarded so it
can't raise into the decision path. Toggle with SHADOW_ARMS_ENABLED (default on).
"""
import os
import logging
from typing import Optional, Dict, Any

from services.unified_verdict import (
    resolve_unified_verdict, resolve_tqs_only, champion_verdict,
)

logger = logging.getLogger(__name__)


def shadow_arms_enabled() -> bool:
    return os.environ.get("SHADOW_ARMS_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _geometry(alert: Dict[str, Any], current_price: float, direction: str):
    """Best-effort entry/stop/target for the would-have scorer. Derives a 2R
    target when the alert carries none, so the scorer can mark won/lost."""
    entry = (alert.get("trigger_price") or alert.get("entry_price")
             or current_price or 0) or 0
    stop = (alert.get("stop_price") or alert.get("stop_loss") or 0) or 0
    target = 0.0
    targets = alert.get("targets")
    if isinstance(targets, list) and targets:
        try:
            target = float(targets[0])
        except (TypeError, ValueError):
            target = 0.0
    if not target:
        try:
            target = float(alert.get("target_price") or 0)
        except (TypeError, ValueError):
            target = 0.0
    entry, stop = float(entry or 0), float(stop or 0)
    if (not target) and entry and stop:
        risk = abs(entry - stop)
        if risk > 0:
            target = entry + 2 * risk if direction == "long" else entry - 2 * risk
    return entry, stop, float(target or 0)


async def record_shadow_arms(
    bot, alert: Dict[str, Any], *,
    grade: Optional[str], tqs_score, gate_result,
    champion_decision: str, champion_conf_mult=1.0,
    current_price: float = 0.0, direction: str = "long", regime: str = "",
) -> None:
    """Best-effort recorder. NEVER raises into the live decision path."""
    try:
        if not shadow_arms_enabled():
            return
        from services.slow_learning.shadow_mode_service import get_shadow_mode_service
        svc = get_shadow_mode_service()
        if svc is None or getattr(svc, "_shadow_signals_col", None) is None:
            return

        symbol = alert.get("symbol") or alert.get("ticker") or ""
        if not symbol:
            return
        setup_type = alert.get("setup_type") or ""
        alert_id = str(alert.get("id") or alert.get("alert_id") or "")
        dir_norm = "long" if str(direction).lower() in ("long", "buy", "bull", "1") else "short"
        entry, stop, target = _geometry(alert, current_price, dir_norm)
        try:
            score = float(tqs_score) if tqs_score is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0

        verdicts = {
            "champion": champion_verdict(
                champion_decision, grade=grade, tqs_score=score, conf_mult=champion_conf_mult),
            "unified_1a2a": resolve_unified_verdict(grade, gate_result, tqs_score=score),
            "gate_off": resolve_tqs_only(grade, tqs_score=score),
        }

        for arm, v in verdicts.items():
            decision = v["decision"]
            # SKIP arms: 'skipped' (counted, not scored). GO/REDUCE: 'pending' -> scored.
            status = "skipped" if decision == "SKIP" else "pending"
            await svc.record_signal(
                symbol=symbol, direction=dir_norm, setup_type=setup_type,
                signal_price=entry, stop_price=stop, target_price=target,
                tqs_score=score, market_regime=regime,
                confirmations=v.get("reasons", []),
                notes=f"arm={arm}",
                arm=arm, tier="shadow", alert_id=alert_id,
                arm_decision=decision, size_mult=v["size_mult"], status=status,
            )
    except Exception as e:  # never break the live path
        logger.debug("record_shadow_arms skipped (%s): %s", type(e).__name__, e)
