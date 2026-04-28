"""
Canonical Symbol Universe — single source of truth for tier classification.

Until 2026-04-26 the codebase had THREE different definitions of "the
intraday universe":

  - `services/ib_historical_collector.py::_smart_backfill_sync` used
    **dollar volume** (`avg_dollar_volume >= $50M`).
  - `services/backfill_readiness_service.py::_check_overall_freshness`
    + `_check_density_adequate` used **share volume**
    (`avg_volume >= 500_000`).
  - The training pipeline downstream used yet a third proxy.

Result: the share-volume universe was ~2,648 symbols; the dollar-volume
universe was ~1,186. Training inflated to 4,000+ symbols (union),
tripling per-cycle compute and inflating estimated train time to
68 hours. Smart-backfill and readiness silently disagreed on what was
"missing", so users could never get to a green readiness verdict.

This module is the ONE place those decisions live now. Every collector,
every readiness check, every training job pulls from `get_universe()`
so they all classify symbols identically.

Schema additions to `symbol_adv_cache`:
  - `unqualifiable: bool`            — True if IB has no security
                                        definition for the symbol after
                                        `UNQUALIFIABLE_FAILURE_THRESHOLD`
                                        attempts. Skipped from all
                                        universes.
  - `unqualifiable_failure_count: int` — running count of "No security
                                          definition" errors.
  - `unqualifiable_marked_at: str`    — ISO timestamp when promoted.
  - `unqualifiable_reason: str`       — last reason recorded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---- Tier thresholds (DOLLAR VOLUME — confirmed by user 2026-04-26) ----
# avg_volume × latest close, computed by
# IBHistoricalCollector.rebuild_adv_from_ib() and stored on
# `symbol_adv_cache.avg_dollar_volume`.
INTRADAY_THRESHOLD = 50_000_000     # $50M/day  → 1m, 5m, 15m, 1h, 1d
SWING_THRESHOLD    = 10_000_000     # $10M/day  → 5m, 30m, 1h, 1d
INVESTMENT_THRESHOLD = 2_000_000    # $2M/day   → 1h, 1d, 1w

DOLLAR_VOL_THRESHOLDS: Dict[str, int] = {
    "intraday":   INTRADAY_THRESHOLD,
    "swing":      SWING_THRESHOLD,
    "investment": INVESTMENT_THRESHOLD,
}


# 2026-04-28f — single-source-of-truth accessor. ALL consumers that
# need ADV tier thresholds (`enhanced_scanner`, `data_inventory_service`,
# `ib_historical_collector`, future scaffolds) MUST call this function
# instead of importing the module-level constants directly. That way a
# future copy-paste mistake can't desynchronise tiers across the app —
# there's only one place to change a threshold.
def get_adv_thresholds() -> Dict[str, int]:
    """Canonical ADV (dollar volume) tier thresholds, returned as a
    fresh dict so callers can't mutate the module state. Single source
    of truth for every consumer in the codebase."""
    return {
        "intraday":   INTRADAY_THRESHOLD,
        "swing":      SWING_THRESHOLD,
        "investment": INVESTMENT_THRESHOLD,
    }

# Per-bar-size → tier mapping. Used by every training entry point so a
# 1-min model trains on the same universe smart-backfill is keeping
# fresh, never on a wider/narrower one.
#   1m / 5m / 15m / 30m  → intraday tier   (≥ $50M/day)
#   1h  / 1d              → swing tier      (≥ $10M/day, super-set of intraday)
#   1w                    → investment tier (≥ $2M/day,  super-set of swing)
BAR_SIZE_TIER: Dict[str, str] = {
    "1 min":   "intraday",
    "5 mins":  "intraday",
    "15 mins": "intraday",
    "30 mins": "intraday",
    "1 hour":  "swing",
    "1 day":   "swing",
    "1 week":  "investment",
}

# Bar sizes each tier needs on initial backfill. Smart-backfill in the
# collector adds the union of `(tier-required, already-on-disk)` so
# tier reclassification doesn't strand existing history (preserve-history
# rule, see `_smart_backfill_sync` for details).
TIER_TIMEFRAMES: Dict[str, List[str]] = {
    "intraday":   ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
    "swing":      ["5 mins", "30 mins", "1 hour", "1 day"],
    "investment": ["1 hour", "1 day", "1 week"],
}

# Promote to `unqualifiable=true` after N "No security definition"
# strikes from IB.
#
# 2026-04-29: lowered 3 → 1 because "No security definition" is a
# DETERMINISTIC error from IB (the symbol either exists in their
# security master or it doesn't — there's no transient state). Waiting
# for 3 strikes meant a single bad symbol burned 3 IB requests across
# 3 separate backfill cycles before being pruned. Cumulative cost on
# the 2026-04-29 overnight backfill: ~9000 wasted requests, 3-5×
# slower than necessary. With strike=1, one bad batch = one strike =
# one immediate promotion. Caller can pass a transient_error_reason
# if they want the legacy 3-strike behaviour for retryable errors
# like timeouts/disconnects.
UNQUALIFIABLE_FAILURE_THRESHOLD = 1

# Match-all sentinel for callers that want every tier in one query.
ALL_TIERS = ("intraday", "swing", "investment")


# ---- Public API -------------------------------------------------------

def get_universe(
    db,
    tier: str = "intraday",
    *,
    include_unqualifiable: bool = False,
) -> Set[str]:
    """Return the set of qualified symbols at or above `tier`.

    `tier='intraday'` ⇒ symbols with avg_dollar_volume >= $50M
    `tier='swing'`    ⇒ symbols with avg_dollar_volume >= $10M (super-set of intraday)
    `tier='investment'` ⇒ symbols with avg_dollar_volume >= $2M (super-set of swing)
    `tier='all'`      ⇒ same as 'investment' (everything qualified)

    Excludes `unqualifiable=true` symbols by default. Set
    `include_unqualifiable=True` only for diagnostics.
    """
    if db is None:
        return set()
    tier_key = "investment" if tier == "all" else tier
    if tier_key not in DOLLAR_VOL_THRESHOLDS:
        raise ValueError(f"Unknown tier: {tier!r}; must be one of "
                         f"{list(DOLLAR_VOL_THRESHOLDS) + ['all']}")
    threshold = DOLLAR_VOL_THRESHOLDS[tier_key]

    query: Dict[str, Any] = {"avg_dollar_volume": {"$gte": threshold}}
    if not include_unqualifiable:
        query["unqualifiable"] = {"$ne": True}

    cursor = db["symbol_adv_cache"].find(query, {"symbol": 1, "_id": 0})
    return {d["symbol"] for d in cursor if d.get("symbol")}


def get_universe_for_bar_size(
    db,
    bar_size: str,
    *,
    include_unqualifiable: bool = False,
) -> Set[str]:
    """Return the canonical universe the AI training pipeline should
    use for a given bar_size — single source of truth shared with
    smart-backfill and readiness."""
    tier = BAR_SIZE_TIER.get(bar_size, "swing")
    return get_universe(db, tier, include_unqualifiable=include_unqualifiable)


def classify_tier(avg_dollar_volume: Optional[float]) -> Optional[str]:
    """Map a dollar volume to its tier name. None → unqualified."""
    if avg_dollar_volume is None or avg_dollar_volume <= 0:
        return None
    if avg_dollar_volume >= INTRADAY_THRESHOLD:
        return "intraday"
    if avg_dollar_volume >= SWING_THRESHOLD:
        return "swing"
    if avg_dollar_volume >= INVESTMENT_THRESHOLD:
        return "investment"
    return None


def get_symbol_tier(db, symbol: str) -> Optional[str]:
    """Look up a single symbol's tier from the cache. None if unknown
    or marked unqualifiable."""
    if db is None or not symbol:
        return None
    doc = db["symbol_adv_cache"].find_one(
        {"symbol": symbol},
        {"_id": 0, "tier": 1, "avg_dollar_volume": 1, "unqualifiable": 1},
    )
    if not doc or doc.get("unqualifiable"):
        return None
    tier = doc.get("tier")
    if tier in DOLLAR_VOL_THRESHOLDS:
        return tier
    return classify_tier(doc.get("avg_dollar_volume"))


def get_pusher_l1_recommendations(
    db,
    *,
    top_n: int = 60,
    extra_etfs: Optional[List[str]] = None,
    extra_priority: Optional[List[str]] = None,
    max_total: int = 80,
) -> Dict[str, Any]:
    """Recommend which symbols the IB pusher should subscribe to as
    Level-1 quote streams.

    Why: IB Gateway (paper) caps streaming Level-1 lines at 100. Today
    the pusher subscribes to a hardcoded 14 symbols, which leaves
    intraday-tier symbols (≥$50M ADV) running on minute-stale Mongo
    bars instead of live ticks. This helper picks the top-N symbols
    by `avg_dollar_volume` from `symbol_adv_cache`, plus a small set
    of always-on sector / size / volatility ETFs, and returns a
    deduped + capped list.

    Args:
        db: Mongo handle.
        top_n: how many ADV-ranked symbols to include (default 60).
        extra_etfs: explicit ETF list. Defaults to the 11 SPDR sector
            ETFs + size + style + key volatility/credit references.
        extra_priority: caller-pinned symbols (always included if
            present, e.g. operator's most-evaluated tickers from
            sentcom_thoughts).
        max_total: hard cap on the returned list size (default 80).
            Leaves headroom under IB's 100-line ceiling for the
            dynamic L2 routing path (top-3 EVAL setups).

    Returns:
        {
          "success": True,
          "symbols": [...],            # the recommended L1 list
          "count": int,
          "top_n_by_adv": [...],       # the ADV-ranked subset
          "etfs_included": [...],      # the always-on ETFs
          "priority_included": [...],  # caller-pinned overrides
          "max_total": int,
          "iso_ts": str,
        }
    """
    if db is None:
        return {"success": False, "error": "db_unavailable", "symbols": []}

    if extra_etfs is None:
        # Always-on ETF reference set — sector rotation + size/style +
        # volatility/credit. These are the "context tape" for the bot's
        # macro reads, regardless of where the operator's universe
        # happens to rank them on dollar volume.
        extra_etfs = [
            # Indices & key ETFs
            "SPY", "QQQ", "IWM", "DIA", "VIX",
            # SPDR sector ETFs (11)
            "XLK", "XLE", "XLF", "XLV", "XLI", "XLP",
            "XLY", "XLU", "XLB", "XLRE", "XLC",
            # Size / style
            "VTV", "VUG", "MDY", "SLY",
            # Volatility / credit
            "TLT", "HYG", "GLD", "USO",
        ]

    extra_priority = extra_priority or []

    # Pull top-N by avg_dollar_volume (qualified + non-unqualifiable only)
    top_by_adv: List[str] = []
    try:
        cursor = (
            db["symbol_adv_cache"]
            .find(
                {"unqualifiable": {"$ne": True},
                 "avg_dollar_volume": {"$gt": 0}},
                {"_id": 0, "symbol": 1, "avg_dollar_volume": 1},
            )
            .sort("avg_dollar_volume", -1)
            .limit(int(top_n))
        )
        top_by_adv = [d["symbol"] for d in cursor if d.get("symbol")]
    except Exception as e:
        return {"success": False, "error": str(e)[:120], "symbols": []}

    # Compose: priority pins → top-by-ADV → ETFs (in that order)
    seen: Set[str] = set()
    out: List[str] = []
    for src in (extra_priority, top_by_adv, extra_etfs):
        for s in src:
            if not s:
                continue
            su = str(s).upper().strip()
            if su in seen:
                continue
            seen.add(su)
            out.append(su)
            if len(out) >= max_total:
                break
        if len(out) >= max_total:
            break

    # If the live ranking returned NOTHING (empty cache, transient
    # connection loss) check `pusher_config_cache` for a previous
    # recommendation BEFORE we overwrite it. The cached list is closer
    # to "what we'd want today" than the static ETF set.
    if not top_by_adv:
        try:
            cached = db["pusher_config_cache"].find_one(
                {"_id": "l1_recommendations"},
                {"_id": 0, "symbols": 1, "updated_at": 1},
            )
            if cached and cached.get("symbols"):
                return {
                    "success": True,
                    "symbols": list(cached["symbols"])[:max_total],
                    "count": min(len(cached["symbols"]), max_total),
                    "top_n_by_adv": [],
                    "etfs_included": [
                        e for e in extra_etfs if e in (cached["symbols"] or [])
                    ],
                    "priority_included": [],
                    "max_total": max_total,
                    "iso_ts": datetime.now(timezone.utc).isoformat(),
                    "source": "cached_recommendation",
                    "cache_updated_at": (
                        cached["updated_at"].isoformat()
                        if isinstance(cached.get("updated_at"), datetime)
                        else cached.get("updated_at")
                    ),
                }
        except Exception as e:
            logger.debug(f"pusher_config_cache read failed: {e}")

    # Persist to `pusher_config_cache` so a subsequent call from a
    # transient state (empty `symbol_adv_cache` post-DGX-restart, before
    # the nightly rebuild) still returns the last known-good list. Only
    # writes when we have live ranking data — otherwise we'd overwrite
    # a good cache with the ETF-only fallback.
    if top_by_adv:
        try:
            db["pusher_config_cache"].update_one(
                {"_id": "l1_recommendations"},
                {"$set": {
                    "_id": "l1_recommendations",
                    "symbols": out,
                    "top_n": int(top_n),
                    "max_total": int(max_total),
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"pusher_config_cache persist failed: {e}")

    return {
        "success": True,
        "symbols": out,
        "count": len(out),
        "top_n_by_adv": top_by_adv,
        "etfs_included": [e for e in extra_etfs if e in seen],
        "priority_included": [p.upper() for p in extra_priority if p.upper() in seen],
        "max_total": max_total,
        "iso_ts": datetime.now(timezone.utc).isoformat(),
        "source": "live_ranking" if top_by_adv else "etf_fallback",
    }


def get_universe_stats(db) -> Dict[str, Any]:
    """Diagnostic snapshot — counts per tier + unqualifiable counts +
    per-bar-size training-universe projection.

    Used by /api/backfill/readiness and the FreshnessInspector UI to
    surface universe drift and answer the operator question
    "how many symbols will training pick up for each bar_size?".
    """
    if db is None:
        return {"error": "db not initialized"}
    adv = db["symbol_adv_cache"]
    intraday = len(get_universe(db, "intraday"))
    swing_or_better = len(get_universe(db, "swing"))
    invest_or_better = len(get_universe(db, "investment"))
    unqualifiable_count = adv.count_documents({"unqualifiable": True})
    total = adv.count_documents({})

    # Per-bar-size training universe sizes — exactly what each training
    # phase will pick up via get_universe_for_bar_size (also used by
    # smart-backfill via TIMEFRAMES_BY_TIER for collection planning).
    per_bar_size: Dict[str, Dict[str, Any]] = {}
    by_tier_count = {
        "intraday":   intraday,
        "swing":      swing_or_better,
        "investment": invest_or_better,
    }
    for bs, tier in BAR_SIZE_TIER.items():
        per_bar_size[bs] = {
            "tier": tier,
            "symbols": by_tier_count[tier],
        }

    return {
        "intraday": intraday,
        "swing_only": swing_or_better - intraday,
        "investment_only": invest_or_better - swing_or_better,
        "qualified_total": invest_or_better,
        "unqualifiable": unqualifiable_count,
        "total_in_cache": total,
        "thresholds": dict(DOLLAR_VOL_THRESHOLDS),
        "training_universe_per_bar_size": per_bar_size,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def mark_unqualifiable(
    db,
    symbol: str,
    reason: str = "No security definition found",
) -> Dict[str, Any]:
    """Increment failure_count and promote to `unqualifiable=true` once
    it crosses `UNQUALIFIABLE_FAILURE_THRESHOLD`.

    Idempotent — safe to call repeatedly. Returns the updated doc state
    so the caller can log / surface to UI.
    """
    if db is None or not symbol:
        return {"success": False, "error": "missing db or symbol"}

    sym = symbol.upper()
    now_iso = datetime.now(timezone.utc).isoformat()
    adv = db["symbol_adv_cache"]

    # Increment failure count. Use upsert so symbols not yet in the
    # cache (rare but possible — e.g. a delisted name that never got
    # an ADV row) still get tracked.
    adv.update_one(
        {"symbol": sym},
        {
            "$inc": {"unqualifiable_failure_count": 1},
            "$set": {"unqualifiable_last_reason": reason,
                     "unqualifiable_last_seen_at": now_iso},
            "$setOnInsert": {"symbol": sym, "first_seen_at": now_iso},
        },
        upsert=True,
    )

    doc = adv.find_one(
        {"symbol": sym},
        {"_id": 0, "unqualifiable_failure_count": 1, "unqualifiable": 1},
    ) or {}
    count = doc.get("unqualifiable_failure_count", 0)
    already = bool(doc.get("unqualifiable"))

    promoted = False
    if not already and count >= UNQUALIFIABLE_FAILURE_THRESHOLD:
        adv.update_one(
            {"symbol": sym},
            {"$set": {
                "unqualifiable": True,
                "unqualifiable_marked_at": now_iso,
                "unqualifiable_reason": reason,
            }},
        )
        promoted = True
        logger.warning(
            f"Symbol {sym} promoted to unqualifiable after {count} failures "
            f"(reason={reason!r})"
        )

    return {
        "success": True,
        "symbol": sym,
        "failure_count": count,
        "unqualifiable": already or promoted,
        "promoted_now": promoted,
    }


def reset_unqualifiable(db, symbol: str) -> bool:
    """Operator escape hatch — clear the unqualifiable flag. Used after
    a manual symbol-list correction or an IB Gateway re-sync."""
    if db is None or not symbol:
        return False
    res = db["symbol_adv_cache"].update_one(
        {"symbol": symbol.upper()},
        {"$set": {
            "unqualifiable": False,
            "unqualifiable_failure_count": 0,
            "unqualifiable_cleared_at":
                datetime.now(timezone.utc).isoformat(),
        }},
    )
    return res.modified_count > 0
