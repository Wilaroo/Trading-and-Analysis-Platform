"""v19.34.168 — Persistent regime_snapshots collection.

Captures composite SPY/QQQ/IWM regime transitions to MongoDB so we can
answer time-in-regime / divergence-correlation / setup-fire-rate-by-regime
questions without keeping every observation.

Schema (`regime_snapshots` collection):
  ts                  datetime (UTC, also TTL index field)
  regime              str (volatile / strong_uptrend / momentum / etc.)
  agreement           str (unanimous_up / majority_down / mixed / ...)
  divergence_flag     bool
  uptrend_votes       int
  downtrend_votes     int
  max_daily_range_pct float
  per_index           dict {spy, qqq, iwm}

Persistence policy: write ONLY when (regime, agreement, divergence_flag)
differs from the last snapshot. Time-in-regime is then derivable from
gaps between consecutive rows. TTL = 30 days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "regime_snapshots"
TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

# Track last-written tuple in-memory to avoid querying DB on every tick.
# Keyed by id(db) so multiple scanner instances don't cross-contaminate.
_last_snapshot_key: Dict[int, tuple] = {}
_ttl_index_created: set = set()


def _ensure_indexes(db) -> None:
    """Create TTL + lookup indexes on first call (idempotent)."""
    key = id(db)
    if key in _ttl_index_created:
        return
    try:
        coll = db[COLLECTION_NAME]
        coll.create_index("ts", expireAfterSeconds=TTL_SECONDS, name="ts_ttl")
        coll.create_index([("regime", 1), ("ts", -1)], name="regime_ts")
        _ttl_index_created.add(key)
        logger.info(f"regime_snapshots indexes ensured (TTL={TTL_SECONDS}s)")
    except Exception as e:
        logger.warning(f"Could not create regime_snapshots indexes: {e}")


def _snapshot_key(regime_value: str, metadata: Dict[str, Any]) -> tuple:
    """Tuple used to detect 'regime changed' — only these dimensions
    trigger a new persisted row."""
    return (
        regime_value,
        metadata.get("index_agreement"),
        bool(metadata.get("divergence_flag")),
    )


def record_if_changed(
    db,
    regime_value: str,
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """v19.34.168 — Persist a snapshot ONLY if regime/agreement/divergence
    differs from last write. Returns the inserted document (with ts) on
    write, or None when skipped."""
    if db is None or not regime_value:
        return None

    _ensure_indexes(db)

    key = id(db)
    new_tuple = _snapshot_key(regime_value, metadata)

    # First write of process lifetime → seed in-memory cache from DB so
    # we don't double-write the same regime across restarts.
    if key not in _last_snapshot_key:
        try:
            latest = db[COLLECTION_NAME].find_one(
                {}, sort=[("ts", -1)],
                projection={"regime": 1, "agreement": 1, "divergence_flag": 1},
            )
            if latest:
                _last_snapshot_key[key] = (
                    latest.get("regime"),
                    latest.get("agreement"),
                    bool(latest.get("divergence_flag")),
                )
        except Exception:
            pass

    if _last_snapshot_key.get(key) == new_tuple:
        return None  # no change

    doc = {
        "ts": datetime.now(timezone.utc),
        "regime": regime_value,
        "agreement": metadata.get("index_agreement"),
        "divergence_flag": bool(metadata.get("divergence_flag")),
        "uptrend_votes": int(metadata.get("uptrend_votes", 0)),
        "downtrend_votes": int(metadata.get("downtrend_votes", 0)),
        "max_daily_range_pct": float(metadata.get("max_daily_range_pct", 0.0)),
        "indices_valid": int(metadata.get("indices_valid", 0)),
        "per_index": metadata.get("per_index", {}),
    }

    try:
        db[COLLECTION_NAME].insert_one(doc)
        _last_snapshot_key[key] = new_tuple
        logger.info(
            f"regime snapshot persisted: {regime_value} "
            f"agreement={doc['agreement']} divergence={doc['divergence_flag']}"
        )
        return doc
    except Exception as e:
        logger.warning(f"regime snapshot write failed: {e}")
        return None


def query_history(db, hours: int = 24, limit: int = 500) -> list:
    """Return regime snapshots from the last `hours`, newest first."""
    if db is None:
        return []
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        cursor = db[COLLECTION_NAME].find(
            {"ts": {"$gte": cutoff}}
        ).sort("ts", -1).limit(limit)
        out = []
        for d in cursor:
            d.pop("_id", None)
            if isinstance(d.get("ts"), datetime):
                d["ts"] = d["ts"].isoformat()
            out.append(d)
        return out
    except Exception as e:
        logger.warning(f"regime history query failed: {e}")
        return []


def query_stats(db, hours: int = 24) -> Dict[str, Any]:
    """Compute % time spent in each regime over the last `hours`.

    Algorithm: between consecutive snapshots we were in the *earlier*
    snapshot's regime. The most recent snapshot's regime is assumed to
    continue up to now.
    """
    if db is None:
        return {"hours": hours, "regimes": {}, "total_seconds": 0}
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        snaps = list(
            db[COLLECTION_NAME].find({"ts": {"$gte": cutoff}})
                                .sort("ts", 1)  # oldest first
                                .limit(5000)
        )
        if not snaps:
            return {"hours": hours, "regimes": {}, "total_seconds": 0,
                    "note": "no snapshots in window"}

        now = datetime.now(timezone.utc)
        durations: Dict[str, float] = {}
        for i, s in enumerate(snaps):
            start = s["ts"] if isinstance(s["ts"], datetime) else datetime.fromisoformat(s["ts"])
            if i + 1 < len(snaps):
                next_s = snaps[i + 1]
                end = next_s["ts"] if isinstance(next_s["ts"], datetime) else datetime.fromisoformat(next_s["ts"])
            else:
                end = now
            secs = max(0.0, (end - start).total_seconds())
            regime = s.get("regime", "unknown")
            durations[regime] = durations.get(regime, 0.0) + secs

        total = sum(durations.values()) or 1.0
        regimes_pct = {r: round(100.0 * secs / total, 2) for r, secs in durations.items()}
        return {
            "hours": hours,
            "snapshots_observed": len(snaps),
            "total_seconds": round(total, 1),
            "regimes_seconds": {r: round(s, 1) for r, s in durations.items()},
            "regimes_pct": regimes_pct,
        }
    except Exception as e:
        logger.warning(f"regime stats query failed: {e}")
        return {"hours": hours, "regimes": {}, "error": str(e)}
