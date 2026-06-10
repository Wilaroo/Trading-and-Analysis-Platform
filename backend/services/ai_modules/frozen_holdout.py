"""
v321 Tier-2b — FROZEN FORWARD HOLD-OUT
=======================================

Reserves the most recent TB_FROZEN_HOLDOUT_DAYS calendar days (default 45) as
a "final exam" window that NO GBM model ever trains on.

Why: CPCV (v320) grades generalization across purged folds, but the freshest
window is the only data that is *guaranteed* future-like. By freezing it out
of training, ANY backtest/revalidation over the last N days (which now runs
with v320b execution costs) becomes TRUE out-of-sample evidence.

IMPORTANT CONTRACT
------------------
* Only TRAINING data loaders call apply_frozen_holdout().
* Inference / live prediction paths MUST keep seeing the latest bars — never
  wire this into a quote/feature path used at decision time.
* NVMe + Mongo feature caches embed the cutoff in their cache keys (see
  training_pipeline._fh_cache_tag and TimeSeriesGBM._get_feature_cache_key),
  so changing TB_FROZEN_HOLDOUT_DAYS auto-invalidates stale caches.

Env:
  TB_FROZEN_HOLDOUT_DAYS   default 45; 0 disables the hold-out entirely.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_LOGGED_ONCE = set()


def holdout_days() -> int:
    """TB_FROZEN_HOLDOUT_DAYS (default 45; 0 disables the hold-out)."""
    try:
        return max(0, int(os.environ.get("TB_FROZEN_HOLDOUT_DAYS", "45")))
    except (TypeError, ValueError):
        return 45


def holdout_cutoff_iso() -> Optional[str]:
    """YYYY-MM-DD cutoff (UTC). Bars dated AFTER this day are frozen.
    Returns None when the hold-out is disabled."""
    d = holdout_days()
    if d <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")


def frozen_holdout_stamp() -> Optional[Dict]:
    """Stamp persisted into model docs so we always know which models are
    holdout-clean (and against which cutoff)."""
    cutoff = holdout_cutoff_iso()
    if cutoff is None:
        return None
    return {"days": holdout_days(), "cutoff": cutoff}


def _bar_day(ts) -> str:
    """Normalize a bar timestamp to YYYY-MM-DD.
    Handles ISO ('2026-06-11T15:30:00', '2026-06-11') and IB-compact
    ('20260611 15:30:00', '20260611') formats."""
    t = str(ts or "").strip()
    if len(t) >= 10 and t[4:5] == "-" and t[7:8] == "-":
        return t[:10]
    if len(t) >= 8 and t[:8].isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return t[:10]


def apply_frozen_holdout(
    bars: Optional[List[Dict]],
    symbol: str = "",
    bar_size: str = "",
) -> Optional[List[Dict]]:
    """Drop bars NEWER than the frozen cutoff. TRAINING LOADERS ONLY.

    Reads 'timestamp' first, then 'date'. Bars with no parseable date are
    kept (treated as old). Preserves chronological order. Returns the input
    unchanged when the hold-out is disabled or bars is empty/None.
    """
    cutoff = holdout_cutoff_iso()
    if not cutoff or not bars:
        return bars
    kept = [b for b in bars if _bar_day(b.get("timestamp") or b.get("date")) <= cutoff]
    dropped = len(bars) - len(kept)
    if dropped > 0 and bar_size not in _LOGGED_ONCE:
        _LOGGED_ONCE.add(bar_size)
        logger.info(
            f"[FROZEN-HOLDOUT] {bar_size or 'bars'}: training excludes data after "
            f"{cutoff} (e.g. {symbol}: dropped {dropped}/{len(bars)} bars). "
            f"Logged once per bar_size."
        )
    return kept
