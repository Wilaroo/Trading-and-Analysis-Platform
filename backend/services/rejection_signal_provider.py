"""
rejection_signal_provider.py — scaffolding for feeding rejection-analytics
data back into the live tuning loops.

Status: SCAFFOLDED, OFF BY DEFAULT.

The new `sentcom_thoughts` rejection feed (shipped 2026-04-29 afternoon-4)
captures rich "skip narratives" with `reason_code`, `setup_type`, and
post-rejection trade outcomes (computed by `rejection_analytics`). The
existing `multiplier_threshold_optimizer` and
`ai_modules.gate_calibrator` are the natural consumers of this signal —
but only AFTER ~2 weeks of accumulated data confirm verdict stability.

This module is the structural bridge:
  - Wraps `compute_rejection_analytics` and normalizes it into a small
    dict the optimizers can read without coupling to the analytics
    internals.
  - Reads the env flag `ENABLE_REJECTION_SIGNAL_FEEDBACK` (default OFF)
    so optimizers can call this unconditionally without changing
    behavior until the operator opts in.
  - When OFF: returns `{enabled: False, ...}` and downstream code is
    expected to no-op.
  - When ON: returns per-reason-code verdicts + suggested-direction
    hints. Downstream code is responsible for incorporating them.

Design note: this module does NOT directly mutate thresholds. Even when
the flag is ON, the consumers (optimizer / calibrator) decide how much
weight to give the signal — the bridge stays read-only. This keeps the
blast radius small if the rejection data turns out to be biased.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Env flag — default OFF. Operator flips to "true" / "1" / "yes" after
# 2+ weeks of clean rejection-analytics output to start using the signal.
_FLAG_ENV = "ENABLE_REJECTION_SIGNAL_FEEDBACK"


def is_feedback_enabled() -> bool:
    """Public flag reader. Optimizers call this to decide whether to
    incorporate the rejection signal into their tuning step."""
    raw = (os.environ.get(_FLAG_ENV) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# Mapping from rejection `reason_code` → which gate/optimizer dial it
# logically lives behind. Used to route hints to the right consumer.
# Keys are lowercase, conservative — only includes codes we've observed
# enough of to attribute a meaningful direction.
REASON_CODE_TO_TARGET: Dict[str, Dict[str, str]] = {
    # TQS / confidence gates — owned by gate_calibrator
    "tqs_too_low":      {"target": "confidence_gate", "dial": "min_score"},
    "low_confidence":   {"target": "confidence_gate", "dial": "min_score"},
    "ai_low_confidence":{"target": "confidence_gate", "dial": "min_score"},
    # Risk / exposure — owned by risk_caps_service (not auto-tuned today,
    # surfaced for manual review)
    "exposure_cap":     {"target": "risk_caps", "dial": "max_position_pct"},
    "daily_dd_cap":     {"target": "risk_caps", "dial": "daily_loss_pct"},
    "max_position":     {"target": "risk_caps", "dial": "max_position_pct"},
    # Smart-levels guards — owned by multiplier_threshold_optimizer
    "stop_too_close":   {"target": "smart_levels", "dial": "stop_min_level_strength"},
    "target_blocked":   {"target": "smart_levels", "dial": "target_snap_outside_pct"},
    "path_too_thick":   {"target": "smart_levels", "dial": "path_vol_fat_pct"},
}


def get_signal(
    db,
    *,
    days: int = 14,
    min_count: int = 5,
    target: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a normalized rejection signal for downstream optimizers.

    Args:
        db: Mongo handle.
        days: lookback window. Default 14 — wider than rejection_analytics'
            default 7 because optimizer tunings prefer more data.
        min_count: skip codes with fewer firings.
        target: optional filter — `"confidence_gate"`, `"risk_caps"`,
            `"smart_levels"`. None returns everything.

    Returns:
        {
          "enabled": bool,                # = is_feedback_enabled()
          "ran_at": iso str,
          "window_days": int,
          "by_target": {
            "confidence_gate": [
              {
                "reason_code": "tqs_too_low",
                "dial": "min_score",
                "verdict": "gate_potentially_overtight",
                "post_rejection_win_rate_pct": 71.0,
                "count": 47,
                "suggested_direction": "loosen" | "hold" | "tighten",
              }, ...
            ],
            "risk_caps":       [...],
            "smart_levels":    [...],
          },
          "actionable_count": int,        # rows with suggested_direction != "hold"
        }

    Never raises — returns `{enabled: False, by_target: {}, actionable_count: 0}`
    on any failure or when the flag is off.
    """
    enabled = is_feedback_enabled()
    out: Dict[str, Any] = {
        "enabled": enabled,
        "window_days": days,
        "by_target": {},
        "actionable_count": 0,
    }
    if not enabled:
        out["note"] = (
            f"feedback gated behind {_FLAG_ENV} env var; "
            "set to 'true' to enable tuning-loop integration"
        )
        return out

    if db is None:
        out["error"] = "db_unavailable"
        return out

    # Lazy import — keeps the analytics module decoupled.
    try:
        from services.rejection_analytics import compute_rejection_analytics
    except Exception as e:
        out["error"] = f"analytics_import_failed: {e}"
        return out

    raw = compute_rejection_analytics(db, days=days, min_count=min_count)
    if not raw.get("success"):
        out["error"] = raw.get("error") or "analytics_failed"
        return out

    out["ran_at"] = raw.get("ran_at")
    out["total_rejections"] = raw.get("total_rejections", 0)

    by_target: Dict[str, List[Dict[str, Any]]] = {}
    actionable = 0
    for row in raw.get("by_reason_code", []):
        code = (row.get("reason_code") or "").lower()
        mapping = REASON_CODE_TO_TARGET.get(code)
        if not mapping:
            continue  # unmapped code — surfaced via /api/trading-bot/rejection-analytics, not here
        if target and mapping["target"] != target:
            continue

        verdict = row.get("verdict")
        # Only act on verdicts we trust. `gate_borderline` is a wait-state.
        if verdict == "gate_potentially_overtight":
            direction = "loosen"
            actionable += 1
        elif verdict == "gate_calibrated":
            direction = "hold"  # gate is doing its job
        else:
            direction = "hold"  # insufficient_data / borderline

        by_target.setdefault(mapping["target"], []).append({
            "reason_code": code,
            "dial": mapping["dial"],
            "verdict": verdict,
            "post_rejection_win_rate_pct": row.get("post_rejection_win_rate_pct"),
            "count": row.get("count"),
            "suggested_direction": direction,
        })

    out["by_target"] = by_target
    out["actionable_count"] = actionable
    return out
