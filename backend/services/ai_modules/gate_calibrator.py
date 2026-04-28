"""
Gate Calibrator — Auto-tunes Confidence Gate GO/REDUCE/SKIP thresholds
based on actual trade outcomes.

Reads from `confidence_gate_log` (outcome_tracked=True) and computes
optimal thresholds by analyzing win rates at different confidence score levels.

Stores calibrated thresholds in `gate_calibration` collection.
The ConfidenceGate loads these on startup and uses them instead of defaults.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Minimum outcomes needed before calibration adjusts thresholds
MIN_OUTCOMES_FOR_CALIBRATION = 50

# Default thresholds (used when no calibration data exists)
DEFAULT_THRESHOLDS = {
    "aggressive": {"go": 20, "reduce": 10},
    "normal":     {"go": 35, "reduce": 20},
    "cautious":   {"go": 50, "reduce": 30},
    "defensive":  {"go": 60, "reduce": 40},
}

# Target win rates for threshold placement
GO_TARGET_WIN_RATE = 0.50      # GO threshold: score level where win rate >= 50%
REDUCE_TARGET_WIN_RATE = 0.38  # REDUCE threshold: score level where win rate >= 38%


class GateCalibrator:
    """Analyzes gate decision outcomes and computes optimal thresholds."""

    def __init__(self, db=None):
        self._db = db

    def calibrate(self) -> Dict[str, Any]:
        """
        Run calibration: analyze outcomes, compute optimal thresholds.

        Returns dict with calibrated thresholds and analysis metadata.
        """
        if self._db is None:
            return {"success": False, "reason": "No DB connection"}

        # Step 1: Get all outcomes grouped by confidence score
        try:
            pipeline = [
                {"$match": {"outcome_tracked": True, "confidence_score": {"$exists": True}}},
                {"$project": {
                    "_id": 0,
                    "confidence_score": 1,
                    "decision": 1,
                    "trade_outcome": 1,
                    "outcome_pnl": {"$ifNull": ["$outcome_pnl", 0]},
                    "trading_mode": 1,
                }},
            ]
            outcomes = list(self._db["confidence_gate_log"].aggregate(pipeline))
        except Exception as e:
            logger.error(f"Calibration query failed: {e}")
            return {"success": False, "reason": f"Query error: {e}"}

        total_outcomes = len(outcomes)
        if total_outcomes < MIN_OUTCOMES_FOR_CALIBRATION:
            return {
                "success": False,
                "reason": f"Need {MIN_OUTCOMES_FOR_CALIBRATION} outcomes, have {total_outcomes}",
                "total_outcomes": total_outcomes,
            }

        # Step 2: Build score buckets (5-point intervals)
        buckets = {}
        for o in outcomes:
            score = int(o.get("confidence_score", 0))
            bucket = (score // 5) * 5  # 0, 5, 10, 15, 20, ...
            if bucket not in buckets:
                buckets[bucket] = {"total": 0, "wins": 0, "losses": 0, "scratches": 0, "pnl": 0}
            buckets[bucket]["total"] += 1
            outcome = o.get("trade_outcome", "")
            if outcome == "win":
                buckets[bucket]["wins"] += 1
            elif outcome == "loss":
                buckets[bucket]["losses"] += 1
            else:
                buckets[bucket]["scratches"] += 1
            buckets[bucket]["pnl"] += o.get("outcome_pnl", 0)

        # Step 3: Compute cumulative win rate from each score level upward
        # "If we only take trades with score >= X, what's the win rate?"
        sorted_buckets = sorted(buckets.keys())
        cumulative = {}
        for threshold in sorted_buckets:
            wins = sum(buckets[b]["wins"] for b in sorted_buckets if b >= threshold)
            total = sum(buckets[b]["total"] for b in sorted_buckets if b >= threshold)
            pnl = sum(buckets[b]["pnl"] for b in sorted_buckets if b >= threshold)
            cumulative[threshold] = {
                "win_rate": wins / total if total > 0 else 0,
                "total": total,
                "wins": wins,
                "pnl": round(pnl, 2),
            }

        # Step 4: Find optimal thresholds
        # GO: lowest score where cumulative win rate meets target
        go_threshold = self._find_threshold(cumulative, GO_TARGET_WIN_RATE, min_samples=10)
        reduce_threshold = self._find_threshold(cumulative, REDUCE_TARGET_WIN_RATE, min_samples=5)

        # Ensure reduce < go
        if reduce_threshold >= go_threshold:
            reduce_threshold = max(0, go_threshold - 10)

        # Step 5: Compute per-mode thresholds (apply offsets from base)
        base_go = go_threshold
        base_reduce = reduce_threshold
        calibrated = {
            "aggressive": {"go": max(5, base_go - 15), "reduce": max(0, base_reduce - 10)},
            "normal":     {"go": base_go, "reduce": base_reduce},
            "cautious":   {"go": base_go + 15, "reduce": base_reduce + 10},
            "defensive":  {"go": base_go + 25, "reduce": base_reduce + 15},
        }

        result = {
            "success": True,
            "total_outcomes": total_outcomes,
            "base_go_threshold": base_go,
            "base_reduce_threshold": base_reduce,
            "thresholds": calibrated,
            "bucket_analysis": {
                str(k): {**v, "win_rate": round(buckets[k]["wins"] / buckets[k]["total"], 3) if buckets[k]["total"] > 0 else 0}
                for k in sorted_buckets
            },
            "cumulative_analysis": {
                str(k): {**v, "win_rate": round(v["win_rate"], 3)}
                for k, v in cumulative.items()
            },
            "calibrated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Rejection-signal feedback (scaffolded 2026-04-29 afternoon-6) —
        # OFF by default. When `ENABLE_REJECTION_SIGNAL_FEEDBACK=true` the
        # calibrator reads the rejection-analytics signal for the
        # confidence_gate target and annotates the result with hints.
        # Observe-only — calibrated thresholds above are NOT shifted.
        # Operator promotes a hint into actual tuning by manually lowering
        # the GO/REDUCE thresholds OR by promoting the consumer to weight
        # the hint (planned follow-up PR).
        try:
            from services.rejection_signal_provider import get_signal
            signal = get_signal(
                self._db, target="confidence_gate", days=14, min_count=5
            )
            if signal.get("enabled"):
                cg_hints = signal.get("by_target", {}).get("confidence_gate", [])
                if cg_hints:
                    result["rejection_feedback"] = cg_hints
                    actionable = [
                        h for h in cg_hints
                        if h.get("suggested_direction") in ("loosen", "tighten")
                    ]
                    if actionable:
                        result.setdefault("notes", []).extend([
                            (
                                f"[rejection-feedback] {h['reason_code']} → "
                                f"min_score suggests {h['suggested_direction']} "
                                f"(post-WR {h.get('post_rejection_win_rate_pct')}% "
                                f"on {h.get('count')} rejections, "
                                f"verdict={h.get('verdict')}). NOT auto-applied — "
                                "review and promote manually."
                            )
                            for h in actionable
                        ])
            elif signal.get("enabled") is False and signal.get("note"):
                result["rejection_feedback_status"] = signal["note"]
        except Exception as e:
            logger.debug(f"rejection_signal_provider hook failed: {e}")

        # Step 6: Persist to DB
        try:
            self._db["gate_calibration"].update_one(
                {"_id": "current"},
                {"$set": {**result, "_id": "current"}},
                upsert=True,
            )
            logger.info(
                f"Gate calibrated: GO>={base_go}, REDUCE>={base_reduce} "
                f"(from {total_outcomes} outcomes)"
            )
        except Exception as e:
            logger.error(f"Failed to persist calibration: {e}")

        return result

    def _find_threshold(self, cumulative: Dict, target_win_rate: float, min_samples: int = 5) -> int:
        """Find the lowest score threshold where cumulative win rate >= target."""
        # Walk from lowest to highest score
        for score in sorted(cumulative.keys()):
            data = cumulative[score]
            if data["total"] >= min_samples and data["win_rate"] >= target_win_rate:
                return score
        # Fallback: return a conservative threshold if target never met
        return 40

    def load_calibrated_thresholds(self) -> Optional[Dict[str, Dict[str, int]]]:
        """Load the most recent calibration from DB. Returns None if not available."""
        if self._db is None:
            return None
        try:
            doc = self._db["gate_calibration"].find_one({"_id": "current"})
            if doc and doc.get("success"):
                return doc.get("thresholds")
        except Exception as e:
            logger.debug(f"Could not load calibration: {e}")
        return None


# Module-level singleton
_calibrator: Optional[GateCalibrator] = None


def get_gate_calibrator() -> GateCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = GateCalibrator()
    return _calibrator


def init_gate_calibrator(db=None) -> GateCalibrator:
    global _calibrator
    _calibrator = GateCalibrator(db=db)
    return _calibrator
