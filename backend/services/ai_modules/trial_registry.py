"""
Research Trial Registry — track every training run for Deflated Sharpe denominator.

Reference: López de Prado AFML Ch. 11 "The Dangers of Backtesting" +
appendix H "governance checklist". Mlfinlab has no direct equivalent — this is
a governance/tooling layer unique to each firm.

Mongo collection: research_trials
Fields:
    trial_id:            UUID
    setup_type:          "BREAKOUT" | ...
    bar_size:            "5 mins" | ...
    trade_side:          "long" | "short"
    model_name:          e.g. "breakout_5min_predictor"
    sharpe:              training Sharpe (non-annualized or annualized — stay consistent)
    sample_length:       n validation observations
    skew, kurtosis:      return distribution moments
    feature_set_hash:    md5 of sorted feature names list
    hyperparams_hash:    md5 of sorted hyperparam dict
    trained_at:          ISO timestamp
    label_scheme:        "triple_barrier_3class" | "binary"
    pt_atr_mult, sl_atr_mult, max_bars: labeling config

Usage:
    record_trial(db, setup_type=..., bar_size=..., sharpe=..., ...)
    stats = get_trial_statistics(db, setup_type, bar_size, trade_side)
    # → {"K": 12, "variance": 0.14, "mean_sharpe": 0.8, ...}
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import numpy as np
import logging

logger = logging.getLogger(__name__)

COLLECTION = "research_trials"


def _hash_dict(d: dict) -> str:
    return hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _hash_list(items: list) -> str:
    return hashlib.md5(",".join(sorted(str(x) for x in items)).encode()).hexdigest()[:12]


def record_trial(
    db,
    setup_type: str,
    bar_size: str,
    trade_side: str,
    model_name: str,
    sharpe: float,
    sample_length: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    feature_names: Optional[list] = None,
    hyperparams: Optional[dict] = None,
    label_scheme: str = "triple_barrier_3class",
    pt_atr_mult: Optional[float] = None,
    sl_atr_mult: Optional[float] = None,
    max_bars: Optional[int] = None,
    extra: Optional[dict] = None,
) -> Optional[str]:
    """Write a trial doc. Returns trial_id or None if db unavailable."""
    if db is None:
        return None
    trial_id = str(uuid.uuid4())
    doc = {
        "trial_id": trial_id,
        "setup_type": setup_type.upper() if setup_type else "_GENERIC_",
        "bar_size": bar_size,
        "trade_side": (trade_side or "long").lower(),
        "model_name": model_name,
        "sharpe": float(sharpe),
        "sample_length": int(sample_length),
        "skewness": float(skewness),
        "kurtosis": float(kurtosis),
        "feature_set_hash": _hash_list(feature_names or []),
        "hyperparams_hash": _hash_dict(hyperparams or {}),
        "label_scheme": label_scheme,
        "pt_atr_mult": pt_atr_mult,
        "sl_atr_mult": sl_atr_mult,
        "max_bars": max_bars,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "extra": extra or {},
    }
    try:
        db[COLLECTION].insert_one(doc)
        return trial_id
    except Exception as e:
        logger.warning(f"trial_registry: insert failed: {e}")
        return None


def get_trial_statistics(
    db,
    setup_type: Optional[str] = None,
    bar_size: Optional[str] = None,
    trade_side: Optional[str] = None,
    min_trials: int = 1,
) -> dict:
    """
    Aggregate stats from past trials in the same bucket.

    "Independent trials" here is approximated as COUNT of UNIQUE feature-set hashes
    in the bucket (trials that share features are considered one trial group).
    This matches López de Prado's "independent trials K" idea: different
    hyperparams on same features are NOT independent trials.
    """
    if db is None:
        return _empty_stats()
    query = {}
    if setup_type:
        query["setup_type"] = setup_type.upper()
    if bar_size:
        query["bar_size"] = bar_size
    if trade_side:
        query["trade_side"] = trade_side.lower()
    try:
        docs = list(db[COLLECTION].find(query, {"_id": 0}))
    except Exception as e:
        logger.warning(f"trial_registry: query failed: {e}")
        return _empty_stats()

    if not docs:
        return _empty_stats()

    sharpes = np.array([d.get("sharpe", 0.0) for d in docs], dtype=np.float64)
    feature_hashes = set(d.get("feature_set_hash", "") for d in docs)

    stats = {
        "N_trials_total": int(len(docs)),
        "K_independent": max(min_trials, int(len(feature_hashes))),
        "sharpe_variance": float(sharpes.var(ddof=1)) if len(sharpes) > 1 else 0.0,
        "sharpe_mean": float(sharpes.mean()),
        "sharpe_max": float(sharpes.max()),
        "sharpe_min": float(sharpes.min()),
    }
    return stats


def _empty_stats() -> dict:
    return {
        "N_trials_total": 0, "K_independent": 1, "sharpe_variance": 0.0,
        "sharpe_mean": 0.0, "sharpe_max": 0.0, "sharpe_min": 0.0,
    }


def list_recent_trials(
    db,
    setup_type: Optional[str] = None,
    bar_size: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """UI: recent trials for a bucket."""
    if db is None:
        return []
    q = {}
    if setup_type:
        q["setup_type"] = setup_type.upper()
    if bar_size:
        q["bar_size"] = bar_size
    try:
        cursor = db[COLLECTION].find(q, {"_id": 0}).sort("trained_at", -1).limit(limit)
        return list(cursor)
    except Exception:
        return []


def prune_old_trials(db, keep_days: int = 180) -> int:
    """Clean out old trial records. Returns delete count."""
    if db is None:
        return 0
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    try:
        r = db[COLLECTION].delete_many({"trained_at": {"$lt": cutoff}})
        return int(r.deleted_count)
    except Exception:
        return 0
