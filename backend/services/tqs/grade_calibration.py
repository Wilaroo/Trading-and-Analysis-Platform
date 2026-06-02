"""
v19.34.228 — TQS grade calibration layer.

WHY: the composite TQS is a weighted AVERAGE of 5 pillar scores
(tqs_engine.calculate_tqs). Averaging 5 mid-range pillars crushes the variance
into a narrow band (~48-66, stdev ~3), so the old absolute thresholds
(A>=85, B>=65, C>=45, ...) lumped ~100% of trades into C/C+ and sized every
trade at 0.3x. The composite's ABSOLUTE value is a poor ruler, but its RANKING
is valid (a 60 really is a better setup than a 53).

WHAT: grade by PERCENTILE RANK against a rolling reference of recent alert
scores, with an ABSOLUTE FLOOR (hybrid) so a weak day can't mint A/B grades on
mediocre setups. Monotonic + safe: never changes which setup ranks higher, only
spreads the grade labels. Falls back to the legacy static bands whenever the
rolling reference is unavailable or too small, so grading never breaks.

Self-adapting: the reference refreshes on a TTL, so when the pillars are later
de-compressed (setup cap / execution floor) the grades re-spread automatically
with no redeploy. Everything is env-tunable.
"""
import bisect
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── env helpers ────────────────────────────────────────────────────────
def _envf(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _envi(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# Percentile breakpoints (0-100): grade = highest tier whose rank >= cut.
def _pct_cuts() -> dict:
    return {
        "A": _envf("TQS_CAL_PCT_A", 90.0),
        "B": _envf("TQS_CAL_PCT_B", 70.0),
        "C": _envf("TQS_CAL_PCT_C", 35.0),
        "D": _envf("TQS_CAL_PCT_D", 10.0),
    }


# Absolute floors: minimum RAW score required to earn each grade (hybrid safety).
def _floors() -> dict:
    return {
        "A": _envf("TQS_CAL_FLOOR_A", 60.0),
        "B": _envf("TQS_CAL_FLOOR_B", 57.0),
        "C": _envf("TQS_CAL_FLOOR_C", 0.0),
        "D": _envf("TQS_CAL_FLOOR_D", 0.0),
    }


def _window_days() -> int:
    return _envi("TQS_CAL_WINDOW_DAYS", 5)


def _ttl_sec() -> int:
    return _envi("TQS_CAL_TTL_SEC", 900)


def _min_sample() -> int:
    return _envi("TQS_CAL_MIN_SAMPLE", 200)


def _enabled() -> bool:
    return os.environ.get("TQS_CAL_ENABLED", "true").strip().lower() not in ("false", "0", "no")


# ── legacy static-band fallback (the engine's original thresholds) ──────
def static_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B+"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C+"
    if score >= 45:
        return "C"
    if score >= 35:
        return "D"
    return "F"


# ── rolling reference cache ─────────────────────────────────────────────
class _RefCache:
    def __init__(self):
        self.sorted_scores: List[float] = []
        self.fetched_at: float = 0.0
        self.n: int = 0


_cache = _RefCache()

# Dedicated sync client (mirrors execution_quality.py — robust regardless of
# whether the app's injected db handle is motor/async or pymongo/sync).
_CAL_CLIENT = None
_CAL_DB = None


def _get_db():
    global _CAL_CLIENT, _CAL_DB
    if _CAL_DB is not None:
        return _CAL_DB
    try:
        from pymongo import MongoClient
        url = os.environ.get("MONGO_URL")
        name = os.environ.get("DB_NAME")
        if not url or not name:
            return None
        _CAL_CLIENT = MongoClient(url, serverSelectionTimeoutMS=1500)
        _CAL_DB = _CAL_CLIENT[name]
        return _CAL_DB
    except Exception as e:  # pragma: no cover
        logger.warning("[tqs-cal] mongo client init failed: %s: %s", type(e).__name__, e)
        return None


def _refresh_reference() -> None:
    db = _get_db()
    if db is None:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_window_days())).strftime("%Y-%m-%d")
    try:
        rows = list(db["live_alerts"].find(
            {"created_at": {"$gte": cutoff}, "tqs_score": {"$gt": 0}},
            {"tqs_score": 1, "_id": 0},
        ))
        scores = [float(r["tqs_score"]) for r in rows
                  if isinstance(r.get("tqs_score"), (int, float)) and r["tqs_score"] > 0]
        scores.sort()
        _cache.sorted_scores = scores
        _cache.n = len(scores)
        _cache.fetched_at = time.time()
        logger.info("[tqs-cal] reference refreshed: n=%d window=%dd", _cache.n, _window_days())
    except Exception as e:
        logger.warning("[tqs-cal] reference refresh failed: %s: %s", type(e).__name__, e)


def _percentile_rank(score: float) -> Optional[float]:
    n = _cache.n
    if n <= 0:
        return None
    idx = bisect.bisect_right(_cache.sorted_scores, score)
    return 100.0 * idx / n


# ── public API ──────────────────────────────────────────────────────────
def calibrate_grade(score) -> str:
    """Map a raw composite TQS score to a calibrated grade (A/B/C/D/F).

    Percentile-rank against the rolling reference, then enforce absolute floors.
    Falls back to the legacy static bands when calibration is disabled or the
    reference is unavailable / too small.
    """
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "F"

    if not _enabled():
        return static_grade(score)

    # Refresh the reference on TTL (cheap; ~once per TTL window, not per alert).
    if _cache.n == 0 or (time.time() - _cache.fetched_at) > _ttl_sec():
        _refresh_reference()

    if _cache.n < _min_sample():
        return static_grade(score)

    rank = _percentile_rank(score)
    if rank is None:
        return static_grade(score)

    cuts = _pct_cuts()
    floors = _floors()

    # Highest tier earned by percentile rank.
    chosen = "F"
    for g in ("A", "B", "C", "D"):
        if rank >= cuts[g]:
            chosen = g
            break

    # Demote while the raw score is below the absolute floor for the chosen tier.
    order = ["A", "B", "C", "D", "F"]
    i = order.index(chosen)
    while chosen in ("A", "B", "C", "D") and score < floors.get(chosen, 0.0):
        i += 1
        chosen = order[i]
    return chosen


def get_calibration_state() -> dict:
    """Observability snapshot for diagnostics / endpoints."""
    age = time.time() - _cache.fetched_at if _cache.fetched_at else None
    return {
        "enabled": _enabled(),
        "reference_n": _cache.n,
        "window_days": _window_days(),
        "ttl_sec": _ttl_sec(),
        "min_sample": _min_sample(),
        "age_sec": round(age, 1) if age is not None else None,
        "pct_cuts": _pct_cuts(),
        "floors": _floors(),
        "min_score": _cache.sorted_scores[0] if _cache.n else None,
        "max_score": _cache.sorted_scores[-1] if _cache.n else None,
    }
