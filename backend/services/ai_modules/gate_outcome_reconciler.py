"""
gate_outcome_reconciler.py  —  v19.34.311b  (2026-06-10)

Closes the Confidence-Gate outcome-COVERAGE gap WITHOUT live side-effects.

Why this exists
---------------
The live `gate.record_trade_outcome` only fires on the genuine close path
(position_manager._record_learning_outcome). OCA-external sweeps, EOD
auto-close, operator-panel closes and consolidation set status INLINE and skip
it — so the gate historically saw outcomes for only ~9% of closed trades
(the learning_reconciler §F1 gap, which deliberately does NOT touch the gate).

This module backfills `confidence_gate_log` outcomes for CLOSED `bot_trades`
that carry a stable `entry_context.confidence_gate.decision_id` (stamped at
entry by v19.34.311b), gated by a CLEAN-TRADE HYGIENE filter so build-phase
chaos (phantom / unmanaged / oversized / reconciled trades) never enters the
learning corpus.

It is READ-MOSTLY: the only write is an idempotent `$set` on a gate-log doc that
is still `outcome_tracked=False`. No tilt state, no session counters, no IB.

Used by: scripts/run_gate_outcome_reconcile.py (manual/cron) and the scheduled
hook in trading_scheduler (16:25 ET, just before gate_calibration).
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Optional sanity cap on share size — quarantines build-phase "running wild"
# oversized fills. 0 / unset = disabled.
_MAX_CLEAN_SHARES = int(os.environ.get("GATE_LEARN_MAX_SHARES", "0") or "0")

# entered_by prefixes/values that are NOT genuine strategy outcomes.
_ARTIFACT_ENTERED_BY = ("reconciled", "imported_from_ib", "watchlist", "manual")


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pnl_of(t: Dict[str, Any]) -> Optional[float]:
    for k in ("net_pnl", "realized_pnl", "pnl"):
        v = _num(t.get(k))
        if v is not None:
            return v
    return None


def _outcome_from_pnl(pnl: float) -> str:
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "scratch"


def is_clean_for_learning(trade: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Decide whether a closed trade is trustworthy enough to teach the gate.

    Conservative by design — when in doubt, EXCLUDE. Returns (ok, reason).
    """
    eb = str(trade.get("entered_by", "") or "").lower()
    if any(eb.startswith(p) or eb == p for p in _ARTIFACT_ENTERED_BY):
        return False, f"artifact entered_by={eb or '∅'}"

    if str(trade.get("status", "")).lower() != "closed":
        return False, "not closed"

    # Must be a real fill (not a phantom) with positive size.
    fill = _num(trade.get("fill_price")) or _num(trade.get("entry_price"))
    shares = _num(trade.get("shares")) or _num(trade.get("quantity"))
    if not fill or fill <= 0:
        return False, "no fill price (phantom?)"
    if not shares or shares <= 0:
        return False, "no/zero shares"

    # Must have been managed with a protective stop (bracketed).
    stop = _num(trade.get("stop_price"))
    if not stop or stop <= 0:
        return False, "no protective stop (unmanaged)"

    # Realized P&L must be present to score an outcome.
    if _pnl_of(trade) is None:
        return False, "no realized pnl"

    # Optional oversized-fill quarantine.
    if _MAX_CLEAN_SHARES and shares > _MAX_CLEAN_SHARES:
        return False, f"oversized {int(shares)} > {_MAX_CLEAN_SHARES}"

    return True, "clean"


def _decision_id_of(trade: Dict[str, Any]) -> Optional[str]:
    ec = trade.get("entry_context")
    if not isinstance(ec, dict):
        return None
    gate = ec.get("confidence_gate")
    if not isinstance(gate, dict):
        return None
    did = gate.get("decision_id")
    return did or None


class GateOutcomeReconciler:
    """Backfills confidence_gate_log outcomes from clean closed bot_trades."""

    def __init__(self, db=None):
        self._db = db

    def reconcile(self, limit: int = 5000, dry_run: bool = False) -> Dict[str, Any]:
        if self._db is None:
            return {"success": False, "reason": "No DB connection"}

        bt = self._db["bot_trades"]
        cg = self._db["confidence_gate_log"]

        cursor = bt.find(
            {"status": "closed", "entry_context.confidence_gate.decision_id": {"$exists": True}},
            {"_id": 0},
        ).limit(limit)

        stats = {
            "scanned": 0, "clean": 0, "excluded": 0, "matched": 0,
            "backfilled": 0, "already_tracked": 0, "no_gate_log": 0,
            "exclude_reasons": {},
        }

        for t in cursor:
            stats["scanned"] += 1
            ok, reason = is_clean_for_learning(t)
            if not ok:
                stats["excluded"] += 1
                stats["exclude_reasons"][reason] = stats["exclude_reasons"].get(reason, 0) + 1
                continue
            stats["clean"] += 1

            did = _decision_id_of(t)
            if not did:
                continue

            log_doc = cg.find_one({"decision_id": did}, {"_id": 0, "outcome_tracked": 1})
            if not log_doc:
                stats["no_gate_log"] += 1
                continue
            stats["matched"] += 1
            if log_doc.get("outcome_tracked"):
                stats["already_tracked"] += 1
                continue

            pnl = _pnl_of(t) or 0.0
            outcome = _outcome_from_pnl(pnl)
            if dry_run:
                stats["backfilled"] += 1
                continue

            res = cg.update_one(
                {"decision_id": did, "outcome_tracked": False},
                {"$set": {
                    "outcome_tracked": True,
                    "trade_outcome": outcome,
                    "outcome_pnl": pnl,
                    "outcome_recorded_at": datetime.now(timezone.utc).isoformat(),
                    "outcome_source": "reconciler",  # provenance for audit
                }},
            )
            if res.modified_count:
                stats["backfilled"] += 1

        stats["success"] = True
        stats["dry_run"] = dry_run
        logger.info(
            f"Gate-outcome reconcile: scanned={stats['scanned']} clean={stats['clean']} "
            f"backfilled={stats['backfilled']} (dry_run={dry_run})"
        )
        return stats


# Module-level singleton
_reconciler: Optional[GateOutcomeReconciler] = None


def init_gate_outcome_reconciler(db=None) -> GateOutcomeReconciler:
    global _reconciler
    _reconciler = GateOutcomeReconciler(db=db)
    return _reconciler
