"""
exit_archetype_service.py — m9 (2026-06)
========================================
Data-driven override of the STATIC exit_archetype prior.

`setup_taxonomy.exit_archetype_prior()` is a sensible default, but a
setup's REAL exit behaviour lives in its MFE/MAE distribution:

  • setups whose winners keep extending (a fat right tail in MFE_R) want a
    RUNNER bracket — tight stop, bank partials, trail a piece, ride the move;
  • setups whose MFE caps out near the first target want a fixed TARGET
    bracket — bank it at 1-2R, no runner.

Once a setup has enough closed samples this service overrides the prior
along the runner ↔ target axis ONLY. Horizon-locked archetypes
(`swing_hold` / `position_hold`) are NEVER flipped by intraday MFE/MAE —
those follow the trade-style horizon, not the intraday extension shape.

Public API:
    resolve_exit_archetype(setup_type, db=None) -> str
        runner | target | swing_hold | position_hold
        (data override applied along runner↔target only; falls back to the
         static prior when disabled / horizon-locked / insufficient data /
         ambiguous distribution).
    get_exit_archetype_service(db=None).describe(setup_type) -> dict
        prior + empirical + sample count + p50/p75 MFE_R + decision — the
        explainable trace surfaced by probe_bracket_reconcile.py.

Env (all reversible; default ON with a conservative sample gate):
    EXIT_ARCHETYPE_DATA_OVERRIDE_ENABLED  default "1"
    EXIT_ARCHETYPE_MIN_SAMPLES            default 30
    EXIT_ARCHETYPE_LOOKBACK_DAYS          default 90
    EXIT_ARCHETYPE_RUNNER_P50_R           default 2.0   (median MFE_R for runner)
    EXIT_ARCHETYPE_RUNNER_P75_R           default 3.5   (p75 MFE_R for runner)
    EXIT_ARCHETYPE_TARGET_P75_R           default 2.0   (p75 MFE_R ceiling for target)
    EXIT_ARCHETYPE_CACHE_TTL_S            default 3600

This is the live half of the consistency-map §6 plan: "the static prior is
later overridden from the setup's own MFE/MAE distribution once it has
enough samples." Fail-OPEN everywhere — any error returns the static prior
so a bug here can never break bracket placement.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Only these two are data-overridable. swing_hold / position_hold are
# horizon-locked (driven by setup_class, not intraday MFE/MAE).
_OVERRIDABLE = {"runner", "target"}


def _envf(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return str(os.environ.get("EXIT_ARCHETYPE_DATA_OVERRIDE_ENABLED", "1")).strip().lower() \
        not in ("0", "false", "no", "off", "")


def _percentile(sorted_vals: List[float], q: float) -> float:
    """Nearest-rank percentile on an already-sorted list (q in [0,1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, idx))]


def classify_distribution(mfe_values: List[float]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Pure, testable classifier. Returns (archetype_or_None, stats).

    runner  : median MFE_R ≥ RUNNER_P50 AND p75 MFE_R ≥ RUNNER_P75  (winners run)
    target  : p75 MFE_R ≤ TARGET_P75                                (capped, no extension)
    None    : not enough samples OR ambiguous → caller keeps the prior
    """
    vals = sorted(float(v) for v in mfe_values if v is not None)
    n = len(vals)
    min_samples = int(_envf("EXIT_ARCHETYPE_MIN_SAMPLES", 30))
    p50 = _percentile(vals, 0.50)
    p75 = _percentile(vals, 0.75)
    stats = {"n": n, "p50_mfe_r": round(p50, 3), "p75_mfe_r": round(p75, 3),
             "min_samples": min_samples}
    if n < min_samples:
        stats["reason"] = "insufficient_samples"
        return None, stats
    runner_p50 = _envf("EXIT_ARCHETYPE_RUNNER_P50_R", 2.0)
    runner_p75 = _envf("EXIT_ARCHETYPE_RUNNER_P75_R", 3.5)
    target_p75 = _envf("EXIT_ARCHETYPE_TARGET_P75_R", 2.0)
    if p50 >= runner_p50 and p75 >= runner_p75:
        stats["reason"] = "winners_extend"
        return "runner", stats
    if p75 <= target_p75:
        stats["reason"] = "mfe_capped"
        return "target", stats
    stats["reason"] = "ambiguous"
    return None, stats


class ExitArchetypeService:
    """Caches the empirical runner/target verdict per canonical setup."""

    def __init__(self, db=None):
        self._db = db
        # canonical_setup -> (archetype_or_None, stats, monotonic_ts)
        self._cache: Dict[str, Tuple[Optional[str], Dict[str, Any], float]] = {}

    def _resolve_db(self):
        if self._db is not None:
            return self._db
        from database import get_database
        return get_database()

    # ── data ────────────────────────────────────────────────────────────
    def _fetch_mfe_values(self, canonical: str, db) -> List[float]:
        """Pull MFE_R for closed, non-artifact, non-learning trades whose
        canonical setup == `canonical`, over the rolling lookback window."""
        from services.setup_taxonomy import canonicalize
        lookback_days = int(_envf("EXIT_ARCHETYPE_LOOKBACK_DAYS", 90))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        cursor = db["bot_trades"].find(
            {
                "status": {"$in": ["closed", "CLOSED"]},
                "closed_at": {"$gte": cutoff},
                "setup_type": {"$exists": True, "$nin": [None, ""]},
                "mfe_r": {"$ne": None},
            },
            {"_id": 0, "setup_type": 1, "mfe_r": 1,
             "learning_only": 1, "entry_context": 1},
        )
        out: List[float] = []
        for t in cursor:
            if canonicalize(t.get("setup_type")) != canonical:
                continue
            ec = t.get("entry_context") or {}
            if t.get("learning_only") is True or ec.get("learning_only") is True:
                continue
            mfe = t.get("mfe_r")
            try:
                out.append(float(mfe))
            except (TypeError, ValueError):
                continue
        return out

    def empirical_archetype(self, setup_type: str, db=None) -> Tuple[Optional[str], Dict[str, Any]]:
        """(archetype_or_None, stats) for a setup's MFE distribution. Cached."""
        from services.setup_taxonomy import canonicalize
        canonical = canonicalize(setup_type) or str(setup_type or "")
        ttl = _envf("EXIT_ARCHETYPE_CACHE_TTL_S", 3600)
        now = time.monotonic()
        cached = self._cache.get(canonical)
        if cached and (now - cached[2]) < ttl:
            return cached[0], cached[1]
        try:
            db = db or self._resolve_db()
            mfe_values = self._fetch_mfe_values(canonical, db)
            arch, stats = classify_distribution(mfe_values)
        except Exception as e:  # fail-open
            logger.debug("[exit_archetype] empirical calc failed for %s: %s", setup_type, e)
            arch, stats = None, {"n": 0, "reason": f"error:{type(e).__name__}"}
        self._cache[canonical] = (arch, stats, now)
        return arch, stats

    def describe(self, setup_type: str, db=None) -> Dict[str, Any]:
        """Explainable trace: prior + empirical + decision."""
        from services.setup_taxonomy import exit_archetype_prior, canonicalize
        prior = exit_archetype_prior(setup_type)
        enabled = _enabled()
        horizon_locked = prior not in _OVERRIDABLE
        emp, stats = (None, {"n": 0, "reason": "skipped"})
        if enabled and not horizon_locked:
            emp, stats = self.empirical_archetype(setup_type, db=db)
        final = emp if (enabled and not horizon_locked and emp) else prior
        return {
            "setup_type": setup_type,
            "canonical": canonicalize(setup_type) or setup_type,
            "prior": prior,
            "empirical": emp,
            "final": final,
            "overridden": bool(final != prior),
            "enabled": enabled,
            "horizon_locked": horizon_locked,
            "stats": stats,
        }


_service_singleton: Optional[ExitArchetypeService] = None


def get_exit_archetype_service(db=None) -> ExitArchetypeService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = ExitArchetypeService(db=db)
    elif db is not None and _service_singleton._db is None:
        _service_singleton._db = db
    return _service_singleton


def resolve_exit_archetype(setup_type: str, db=None) -> str:
    """Data-aware exit archetype: empirical override along runner↔target,
    else the static prior. Fail-OPEN to the prior on any error."""
    from services.setup_taxonomy import exit_archetype_prior
    try:
        prior = exit_archetype_prior(setup_type)
        if not _enabled() or prior not in _OVERRIDABLE:
            return prior
        emp, _stats = get_exit_archetype_service(db=db).empirical_archetype(setup_type, db=db)
        if emp and emp != prior:
            logger.info(
                "🎯 [m9 exit-archetype] %s: prior=%s overridden → %s from MFE distribution",
                setup_type, prior, emp,
            )
        return emp or prior
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("[exit_archetype] resolve failed for %s (using prior): %s", setup_type, e)
        try:
            from services.setup_taxonomy import exit_archetype_prior as _p
            return _p(setup_type)
        except Exception:
            return "target"
