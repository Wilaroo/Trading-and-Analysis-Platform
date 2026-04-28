"""
Unified Data Inventory Service

Consolidates data from both `ib_historical_data` and `historical_bars`
into a single `data_inventory` collection. Provides:
  1. Unified view of what data exists per (symbol, bar_size)
  2. Depth-aware gap detection against IB max lookbacks
  3. Smart backfill plan generation prioritized by liquidity
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ─── IB Max Lookback Config ──────────────────────────────────────────────────

IB_MAX_LOOKBACK = {
    "1 min":  {"max_days": 180,  "max_duration": "1 W",  "bars_per_day": 390},
    "5 mins": {"max_days": 730,  "max_duration": "1 M",  "bars_per_day": 78},
    "15 mins":{"max_days": 730,  "max_duration": "3 M",  "bars_per_day": 26},
    "30 mins":{"max_days": 730,  "max_duration": "6 M",  "bars_per_day": 13},
    "1 hour": {"max_days": 1825, "max_duration": "1 Y",  "bars_per_day": 7},
    "1 day":  {"max_days": 7300, "max_duration": "8 Y",  "bars_per_day": 1},
    "1 week": {"max_days": 7300, "max_duration": "20 Y", "bars_per_day": 0.2},
}

# Minimum bars needed for meaningful backtesting
MIN_BACKTEST_BARS = {
    "1 min":  3900,   # ~2 weeks of 1-min data
    "5 mins": 1560,   # ~4 months of 5-min data (20 trading days × 78 bars)
    "15 mins": 520,   # ~4 months of 15-min data
    "30 mins": 260,   # ~4 months of 30-min data
    "1 hour": 140,    # ~4 months (~20 days × 7 bars)
    "1 day":  120,    # ~6 months of daily bars
    "1 week": 52,     # ~1 year of weekly bars
}

def _build_adv_tiers() -> Dict[str, Any]:
    """Build the per-tier ADV bucket config from the canonical
    singleton in `services.symbol_universe.get_adv_thresholds()`.
    Called once at module load — the resulting dict is read-only by
    convention.
    """
    from services.symbol_universe import get_adv_thresholds
    t = get_adv_thresholds()
    return {
        # ≥ intraday        → full intraday TF stack
        "intraday":   {"min_adv": t["intraday"],
                       "timeframes": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]},
        # [swing, intraday) → 5m/30m/1h/1d
        "swing":      {"min_adv": t["swing"], "max_adv": t["intraday"],
                       "timeframes": ["5 mins", "30 mins", "1 hour", "1 day"]},
        # [investment, swing) → 1h/1d/1w
        "investment": {"min_adv": t["investment"], "max_adv": t["swing"],
                       "timeframes": ["1 hour", "1 day", "1 week"]},
    }


# 2026-04-28f: ADV_TIERS UNIFIED with the canonical singleton in
# `services.symbol_universe`. ALL ADV thresholds in the app now resolve
# from one place. Field used: `symbol_adv_cache.avg_dollar_volume`.
ADV_TIERS = _build_adv_tiers()

DEPTH_CATEGORIES = {
    "deep":     lambda bars, bs: bars >= IB_MAX_LOOKBACK.get(bs, {}).get("bars_per_day", 1) * 252 * 2,  # 2+ years
    "moderate": lambda bars, bs: bars >= MIN_BACKTEST_BARS.get(bs, 120),  # meets backtest minimum
    "shallow":  lambda bars, bs: bars >= 30,   # some data
    "stub":     lambda bars, bs: bars < 30,    # near useless
}


# ─── Build Inventory ─────────────────────────────────────────────────────────

def build_data_inventory(db) -> Dict[str, Any]:
    """
    Scan both ib_historical_data and historical_bars, merge into data_inventory.
    Returns stats on what was cataloged.
    """
    start = datetime.now(timezone.utc)
    logger.info("[INVENTORY] Starting unified data inventory build...")

    ib_col = db["ib_historical_data"]
    hist_col = db["historical_bars"]
    adv_col = db["symbol_adv_cache"]
    inv_col = db["data_inventory"]

    # ── Step 1: Aggregate ib_historical_data ──
    logger.info("[INVENTORY] Scanning ib_historical_data...")
    ib_pipeline = [
        {"$group": {
            "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
            "bars": {"$sum": 1},
            "earliest": {"$min": "$date"},
            "latest": {"$max": "$date"},
        }}
    ]
    ib_data = {}
    for doc in ib_col.aggregate(ib_pipeline, allowDiskUse=True):
        sym = doc["_id"].get("symbol")
        bs = doc["_id"].get("bar_size")
        if not sym or not bs:
            continue
        key = (sym, bs)
        ib_data[key] = {
            "bars": doc["bars"],
            "earliest": doc["earliest"],
            "latest": doc["latest"],
        }
    logger.info(f"[INVENTORY] ib_historical_data: {len(ib_data)} (symbol, bar_size) combos")

    # ── Step 2: Aggregate historical_bars ──
    # Map timeframe names: historical_bars uses "5min", "1day" etc
    tf_map = {"5min": "5 mins", "1day": "1 day", "1Day": "1 day", "15min": "15 mins",
              "30min": "30 mins", "1min": "1 min", "1hour": "1 hour", "1week": "1 week"}

    logger.info("[INVENTORY] Scanning historical_bars...")
    hist_pipeline = [
        {"$group": {
            "_id": {"symbol": "$symbol", "timeframe": "$timeframe"},
            "bars": {"$sum": 1},
            "earliest": {"$min": "$timestamp"},
            "latest": {"$max": "$timestamp"},
        }}
    ]
    hist_data = {}
    for doc in hist_col.aggregate(hist_pipeline, allowDiskUse=True):
        raw_tf = doc["_id"]["timeframe"]
        bar_size = tf_map.get(raw_tf, raw_tf)
        key = (doc["_id"]["symbol"], bar_size)
        if key in hist_data:
            # Merge with existing (same symbol might appear under "1day" and "1Day")
            existing = hist_data[key]
            existing["bars"] += doc["bars"]
            if doc["earliest"] and (not existing["earliest"] or doc["earliest"] < existing["earliest"]):
                existing["earliest"] = doc["earliest"]
            if doc["latest"] and (not existing["latest"] or doc["latest"] > existing["latest"]):
                existing["latest"] = doc["latest"]
        else:
            hist_data[key] = {
                "bars": doc["bars"],
                "earliest": doc["earliest"],
                "latest": doc["latest"],
            }
    logger.info(f"[INVENTORY] historical_bars: {len(hist_data)} (symbol, bar_size) combos")

    # ── Step 3: Load ADV cache ──
    logger.info("[INVENTORY] Loading ADV cache...")
    adv_lookup = {}
    for doc in adv_col.find({}, {"_id": 0, "symbol": 1, "avg_volume": 1}):
        adv_lookup[doc["symbol"]] = doc.get("avg_volume", 0)

    # ── Step 4: Merge into unified inventory ──
    all_keys = set(ib_data.keys()) | set(hist_data.keys())
    logger.info(f"[INVENTORY] Merging {len(all_keys)} unique (symbol, bar_size) combos...")

    now = datetime.now(timezone.utc)
    bulk_ops = []
    stats = {"total": 0, "deep": 0, "moderate": 0, "shallow": 0, "stub": 0}

    for (symbol, bar_size) in all_keys:
        ib = ib_data.get((symbol, bar_size))
        hist = hist_data.get((symbol, bar_size))

        # Combine bars/dates
        total_bars = (ib["bars"] if ib else 0) + (hist["bars"] if hist else 0)

        # Use the widest date range
        dates = []
        if ib and ib["earliest"]:
            dates.append(ib["earliest"])
        if hist and hist["earliest"]:
            dates.append(hist["earliest"])
        earliest = min(dates) if dates else None

        dates_latest = []
        if ib and ib["latest"]:
            dates_latest.append(ib["latest"])
        if hist and hist["latest"]:
            dates_latest.append(hist["latest"])
        latest = max(dates_latest) if dates_latest else None

        # Calculate date range and freshness
        date_range_days = 0
        days_since_last = 9999
        if earliest and latest:
            if isinstance(earliest, str):
                try:
                    earliest = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                except Exception:
                    pass
            if isinstance(latest, str):
                try:
                    latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                except Exception:
                    pass
            if isinstance(earliest, datetime) and isinstance(latest, datetime):
                # Normalize: make both aware or both naive
                if earliest.tzinfo and not latest.tzinfo:
                    latest = latest.replace(tzinfo=timezone.utc)
                elif latest.tzinfo and not earliest.tzinfo:
                    earliest = earliest.replace(tzinfo=timezone.utc)
                try:
                    date_range_days = (latest - earliest).days
                except TypeError:
                    date_range_days = 0
                try:
                    if latest.tzinfo:
                        days_since_last = (now - latest).days
                    else:
                        days_since_last = (now.replace(tzinfo=None) - latest).days
                except TypeError:
                    days_since_last = 9999

        # Depth category
        depth = "stub"
        for cat, fn in DEPTH_CATEGORIES.items():
            if fn(total_bars, bar_size):
                depth = cat
                break
        stats[depth] = stats.get(depth, 0) + 1
        stats["total"] += 1

        # ADV info
        adv_vol = adv_lookup.get(symbol, 0)
        tier = "skip"
        for tier_name, cfg in ADV_TIERS.items():
            if adv_vol >= cfg["min_adv"]:
                if "max_adv" not in cfg or adv_vol < cfg["max_adv"]:
                    tier = tier_name
                    break
                elif tier_name == "intraday":
                    tier = "intraday"
                    break

        # IB max lookback info
        ib_cfg = IB_MAX_LOOKBACK.get(bar_size, {})
        max_possible_bars = int(ib_cfg.get("bars_per_day", 1) * ib_cfg.get("max_days", 365) * 252 / 365)
        bars_deficit = max(0, max_possible_bars - total_bars)
        min_bars = MIN_BACKTEST_BARS.get(bar_size, 120)
        needs_backfill = total_bars < min_bars

        record = {
            "symbol": symbol,
            "bar_size": bar_size,
            "total_bars": total_bars,
            "earliest_date": str(earliest)[:19] if earliest else None,
            "latest_date": str(latest)[:19] if latest else None,
            "date_range_days": date_range_days,
            "days_since_last": min(days_since_last, 9999),
            "sources": {},
            "depth_category": depth,
            "is_backtestable": total_bars >= min_bars,
            "adv_volume": adv_vol,
            "liquidity_tier": tier,
            "ib_max_duration": ib_cfg.get("max_duration", "?"),
            "ib_max_days": ib_cfg.get("max_days", 0),
            "expected_max_bars": max_possible_bars,
            "bars_deficit": bars_deficit,
            "needs_backfill": needs_backfill,
            "updated_at": now.isoformat(),
        }

        if ib:
            record["sources"]["ib_historical_data"] = {
                "bars": ib["bars"],
                "earliest": str(ib["earliest"])[:19] if ib["earliest"] else None,
                "latest": str(ib["latest"])[:19] if ib["latest"] else None,
            }
        if hist:
            record["sources"]["historical_bars"] = {
                "bars": hist["bars"],
                "earliest": str(hist["earliest"])[:19] if hist["earliest"] else None,
                "latest": str(hist["latest"])[:19] if hist["latest"] else None,
            }

        from pymongo import UpdateOne
        bulk_ops.append(UpdateOne(
            {"symbol": symbol, "bar_size": bar_size},
            {"$set": record},
            upsert=True,
        ))

        if len(bulk_ops) >= 1000:
            inv_col.bulk_write(bulk_ops)
            bulk_ops = []

    if bulk_ops:
        inv_col.bulk_write(bulk_ops)

    # Create indexes
    inv_col.create_index([("symbol", 1), ("bar_size", 1)], unique=True)
    inv_col.create_index([("bar_size", 1), ("depth_category", 1)])
    inv_col.create_index([("liquidity_tier", 1), ("bar_size", 1)])
    inv_col.create_index([("needs_backfill", 1)])

    duration = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(f"[INVENTORY] Complete in {duration:.1f}s — {stats['total']} entries")

    return {
        "success": True,
        "total_entries": stats["total"],
        "depth_breakdown": {k: v for k, v in stats.items() if k != "total"},
        "duration_seconds": round(duration, 1),
    }


# ─── Query Inventory ─────────────────────────────────────────────────────────

def get_inventory_summary(db) -> Dict[str, Any]:
    """Get a high-level summary of the data inventory."""
    inv = db["data_inventory"]

    if inv.count_documents({}) == 0:
        return {"success": False, "error": "Inventory not built. Call build first."}

    # By bar_size
    bar_pipeline = [
        {"$group": {
            "_id": "$bar_size",
            "symbols": {"$sum": 1},
            "total_bars": {"$sum": "$total_bars"},
            "backtestable": {"$sum": {"$cond": ["$is_backtestable", 1, 0]}},
            "needs_backfill": {"$sum": {"$cond": ["$needs_backfill", 1, 0]}},
            "deep": {"$sum": {"$cond": [{"$eq": ["$depth_category", "deep"]}, 1, 0]}},
            "moderate": {"$sum": {"$cond": [{"$eq": ["$depth_category", "moderate"]}, 1, 0]}},
            "shallow": {"$sum": {"$cond": [{"$eq": ["$depth_category", "shallow"]}, 1, 0]}},
            "stub": {"$sum": {"$cond": [{"$eq": ["$depth_category", "stub"]}, 1, 0]}},
        }},
        {"$sort": {"total_bars": -1}},
    ]
    by_bar_size = list(inv.aggregate(bar_pipeline))

    # By liquidity tier
    tier_pipeline = [
        {"$group": {
            "_id": "$liquidity_tier",
            "symbols": {"$addToSet": "$symbol"},
            "entries": {"$sum": 1},
            "backtestable": {"$sum": {"$cond": ["$is_backtestable", 1, 0]}},
        }},
        {"$project": {
            "_id": 1, "unique_symbols": {"$size": "$symbols"},
            "entries": 1, "backtestable": 1,
        }},
        {"$sort": {"unique_symbols": -1}},
    ]
    by_tier = list(inv.aggregate(tier_pipeline))

    total = inv.count_documents({})
    backtestable = inv.count_documents({"is_backtestable": True})
    needs_fill = inv.count_documents({"needs_backfill": True})
    unique_symbols = len(inv.distinct("symbol"))

    return {
        "success": True,
        "total_entries": total,
        "unique_symbols": unique_symbols,
        "backtestable": backtestable,
        "needs_backfill": needs_fill,
        "by_bar_size": by_bar_size,
        "by_tier": by_tier,
    }


def query_symbol_inventory(db, symbol: str) -> Dict[str, Any]:
    """Get complete data inventory for a single symbol."""
    inv = db["data_inventory"]
    records = list(inv.find({"symbol": symbol.upper()}, {"_id": 0}).sort("bar_size", 1))
    if not records:
        return {"success": False, "symbol": symbol, "error": "Not in inventory"}
    return {
        "success": True,
        "symbol": symbol.upper(),
        "timeframes": len(records),
        "records": records,
    }


# ─── Deep Gap Analysis ───────────────────────────────────────────────────────

def run_deep_gap_analysis(db, tier_filter: str = None) -> Dict[str, Any]:
    """
    Depth-aware gap analysis using the unified inventory.

    For each ADV-qualified symbol, checks:
      1. Which timeframes are MISSING entirely
      2. Which timeframes have data but are too SHALLOW to backtest
      3. Which timeframes are STALE (last bar > 7 days old)
      4. Which timeframes need DEEPENING (has data but far from IB max)

    Returns gaps prioritized by severity and liquidity.
    """
    inv = db["data_inventory"]
    adv_col = db["symbol_adv_cache"]

    if inv.count_documents({}) == 0:
        return {"success": False, "error": "Inventory not built. Call build first."}

    gaps = {
        "missing": [],     # Symbol qualifies for timeframe but has zero data
        "shallow": [],     # Has data but below backtest minimum
        "stale": [],       # Has data but >7 days old
        "needs_deepening": [],  # Has moderate data, could go deeper
    }

    total_gap_requests = 0

    for tier_name, tier_cfg in ADV_TIERS.items():
        if tier_filter and tier_filter != tier_name:
            continue

        # 2026-04-28f: query DOLLAR volume to match the canonical tier
        # definition in services.symbol_universe (was querying
        # `avg_volume` shares, which silently never matched the new
        # dollar-volume thresholds and produced empty tier_symbols).
        adv_query = {"avg_dollar_volume": {"$gte": tier_cfg["min_adv"]}}
        if "max_adv" in tier_cfg:
            adv_query["avg_dollar_volume"]["$lt"] = tier_cfg["max_adv"]

        tier_symbols = [d["symbol"] for d in adv_col.find(adv_query, {"_id": 0, "symbol": 1})]
        if not tier_symbols:
            continue

        for tf in tier_cfg["timeframes"]:
            # Get inventory entries for this tier+timeframe
            existing = {
                d["symbol"]: d
                for d in inv.find(
                    {"symbol": {"$in": tier_symbols}, "bar_size": tf},
                    {"_id": 0}
                )
            }

            min_bars = MIN_BACKTEST_BARS.get(tf, 120)
            ib_cfg = IB_MAX_LOOKBACK.get(tf, {})

            for sym in tier_symbols:
                entry = existing.get(sym)

                if not entry:
                    # MISSING: no data at all
                    gaps["missing"].append({
                        "symbol": sym,
                        "bar_size": tf,
                        "tier": tier_name,
                        "duration": ib_cfg.get("max_duration", "1 M"),
                        "priority": "high",
                    })
                    total_gap_requests += 1

                elif entry["total_bars"] < min_bars:
                    # SHALLOW: has data but not enough
                    gaps["shallow"].append({
                        "symbol": sym,
                        "bar_size": tf,
                        "tier": tier_name,
                        "current_bars": entry["total_bars"],
                        "needed_bars": min_bars,
                        "duration": ib_cfg.get("max_duration", "1 M"),
                        "priority": "medium",
                    })
                    total_gap_requests += 1

                elif entry.get("days_since_last", 0) > 7:
                    # STALE: data exists but outdated
                    gaps["stale"].append({
                        "symbol": sym,
                        "bar_size": tf,
                        "tier": tier_name,
                        "days_since_last": entry["days_since_last"],
                        "duration": "1 M",  # Just need recent update
                        "priority": "low",
                    })
                    total_gap_requests += 1

                elif entry["depth_category"] in ("shallow", "moderate") and entry["bars_deficit"] > min_bars:
                    # NEEDS DEEPENING: could benefit from more history
                    gaps["needs_deepening"].append({
                        "symbol": sym,
                        "bar_size": tf,
                        "tier": tier_name,
                        "current_bars": entry["total_bars"],
                        "max_possible": entry["expected_max_bars"],
                        "deficit": entry["bars_deficit"],
                        "duration": ib_cfg.get("max_duration", "1 M"),
                        "priority": "low",
                    })
                    total_gap_requests += 1

    return {
        "success": True,
        "total_gaps": total_gap_requests,
        "missing_count": len(gaps["missing"]),
        "shallow_count": len(gaps["shallow"]),
        "stale_count": len(gaps["stale"]),
        "deepening_count": len(gaps["needs_deepening"]),
        "gaps": gaps,
    }


# ─── Smart Backfill Plan ─────────────────────────────────────────────────────

def generate_backfill_plan(db, tier_filter: str = None, max_requests: int = None) -> Dict[str, Any]:
    """
    Generate a prioritized backfill plan from gap analysis.

    Priority order:
      1. Missing daily data for liquid symbols (most valuable)
      2. Missing hourly data
      3. Shallow daily (needs deepening)
      4. Missing intraday
      5. Stale data refresh
      6. General deepening

    Returns a list of collection requests ready to be queued.
    """
    gap_result = run_deep_gap_analysis(db, tier_filter)
    if not gap_result["success"]:
        return gap_result

    gaps = gap_result["gaps"]

    # Priority scoring: lower = higher priority
    TIMEFRAME_PRIORITY = {
        "1 day": 1, "1 hour": 2, "5 mins": 3, "15 mins": 4,
        "30 mins": 5, "1 min": 6, "1 week": 7,
    }
    TIER_PRIORITY = {"intraday": 1, "swing": 2, "investment": 3, "skip": 99}
    SEVERITY_PRIORITY = {"missing": 1, "shallow": 2, "stale": 3, "needs_deepening": 4}

    all_requests = []
    seen = set()  # Deduplicate (symbol, bar_size) combos

    for severity, items in gaps.items():
        for item in items:
            key = (item["symbol"], item["bar_size"])
            if key in seen:
                continue
            seen.add(key)

            score = (
                SEVERITY_PRIORITY.get(severity, 5) * 100
                + TIER_PRIORITY.get(item.get("tier", "skip"), 99) * 10
                + TIMEFRAME_PRIORITY.get(item["bar_size"], 8)
            )

            all_requests.append({
                "symbol": item["symbol"],
                "bar_size": item["bar_size"],
                "duration": item["duration"],
                "tier": item.get("tier", "skip"),
                "gap_type": severity,
                "priority_score": score,
            })

    # Sort by priority score (lower = more important)
    all_requests.sort(key=lambda x: x["priority_score"])

    if max_requests:
        all_requests = all_requests[:max_requests]

    # Estimate time
    # IB pacing: 60 requests per 10 minutes = 6 per minute
    # But each request can take variable time depending on duration
    time_estimates = {
        "1 min": 3, "5 mins": 5, "15 mins": 8, "30 mins": 10,
        "1 hour": 15, "1 day": 20, "1 week": 10,
    }
    total_seconds = sum(time_estimates.get(r["bar_size"], 10) for r in all_requests)

    # Group by bar_size for summary
    by_bar_size = {}
    for r in all_requests:
        bs = r["bar_size"]
        if bs not in by_bar_size:
            by_bar_size[bs] = {"count": 0, "gap_types": {}}
        by_bar_size[bs]["count"] += 1
        gt = r["gap_type"]
        by_bar_size[bs]["gap_types"][gt] = by_bar_size[bs]["gap_types"].get(gt, 0) + 1

    return {
        "success": True,
        "total_requests": len(all_requests),
        "estimated_minutes": round(total_seconds / 60, 1),
        "estimated_hours": round(total_seconds / 3600, 1),
        "by_bar_size": by_bar_size,
        "requests": all_requests,
    }


# ─── Queue Backfill Requests ─────────────────────────────────────────────────

def queue_backfill_plan(db, plan_requests: List[Dict], batch_size: int = 500) -> Dict[str, Any]:
    """
    Take requests from generate_backfill_plan and queue them into
    historical_data_requests for the collector to process.
    """
    queue_col = db["historical_data_requests"]
    now = datetime.now(timezone.utc).isoformat()

    queued = 0
    skipped = 0

    for req in plan_requests:
        # Check if already queued (pending or processing)
        existing = queue_col.find_one({
            "symbol": req["symbol"],
            "bar_size": req["bar_size"],
            "status": {"$in": ["pending", "processing"]},
        })
        if existing:
            skipped += 1
            continue

        queue_col.insert_one({
            "symbol": req["symbol"],
            "bar_size": req["bar_size"],
            "duration": req["duration"],
            "status": "pending",
            "priority": req.get("priority_score", 999),
            "gap_type": req.get("gap_type", "unknown"),
            "tier": req.get("tier", "unknown"),
            "created_at": now,
            "source": "backfill_plan",
        })
        queued += 1

    return {
        "success": True,
        "queued": queued,
        "skipped_already_queued": skipped,
        "total_in_plan": len(plan_requests),
    }
