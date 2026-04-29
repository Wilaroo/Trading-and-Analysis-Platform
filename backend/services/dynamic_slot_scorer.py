"""
Dynamic Slot Scorer — 2026-04-30 v17
=====================================

Each rotation cycle the pusher rotation service has 100 "dynamic
overlay" slots to fill. They come from the intraday tier symbols that
**didn't make the static top-300** — about 737 candidates. We need to
pick the 100 most likely to produce a profitable setup in the next
~15 minutes.

Scoring inputs (descending priority)
------------------------------------
1. **Recent setup hits** — symbols that fired a `live_alerts` row in
   the last 60min are high-priority. The market just told us they're
   active.
2. **News flag** — symbols tagged in the news collection in the last
   2h (catalyst-driven volatility, tradeable mean-reversion).
3. **Sector momentum** — when a sector ETF moves >0.5% in the last
   hour, pull its top-5 component names from the static-core remainder.
4. **RVOL spike (recent)** — symbols whose live tick volume / 30-day
   avg minute volume is >1.5× in the last 5min. Read from
   ``symbol_adv_cache`` historic rolling RVOL where stored, else from
   recent live_alerts that include rvol metadata.
5. **Premarket gap** — at session open, gappers (>2% premarket move)
   stay hot for the morning even after the gap-and-go fires.

Cohort design
-------------
The scorer doesn't *separate* hot-slots vs dynamic-overlay; the
pusher rotation service does that. Here we just produce a single
ranked list — the rotation service slices off `[:HOT_SLOT_BUDGET]`
for hot slots and `[HOT_SLOT_BUDGET:HOT_SLOT_BUDGET+DYN_BUDGET]` for
the dynamic overlay.

Performance
-----------
The scorer runs at most every 15min so it's never on the hot path.
We can afford a few Mongo reads. Target: <500ms total per call.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# Score weights — tuneable. These sum loosely to 100; absolute scale
# doesn't matter, only the ordering.
WEIGHT_RECENT_SETUP_HIT = 50       # last 60min — strongest signal
WEIGHT_NEWS_TAG = 30                # last 2h — known catalyst
WEIGHT_SECTOR_MOMENTUM = 20         # ETF >0.5% in last hour
WEIGHT_RVOL_SPIKE = 25              # >1.5× recent
WEIGHT_PREMARKET_GAP = 35           # session-open boost


def score_candidates(
    db,
    *,
    exclude: Optional[Set[str]] = None,
    universe_tier: str = "intraday",
    lookback_recent_setup_min: int = 60,
    lookback_news_hours: int = 2,
    lookback_rvol_min: int = 5,
) -> List[Dict[str, Any]]:
    """Return a ranked list of candidate symbols from the intraday tier
    (excluding ``exclude`` — typically the static-core 300 + ETFs).

    Returns:
        [
            {"symbol": "AVGO", "score": 95, "reasons": ["setup_hit", "rvol"]},
            {"symbol": "PLTR", "score": 80, "reasons": ["news"]},
            ...
        ]
        Sorted by score desc.
    """
    if db is None:
        return []
    exclude = {s.upper().strip() for s in (exclude or set())}

    # Build the candidate pool — intraday tier minus excluded (top-300 etc).
    candidates: Set[str] = set()
    try:
        cursor = db["symbol_adv_cache"].find(
            {"tier": universe_tier,
             "unqualifiable": {"$ne": True},
             "avg_dollar_volume": {"$gt": 0}},
            {"_id": 0, "symbol": 1},
        )
        for d in cursor:
            sym = d.get("symbol")
            if sym and sym.upper() not in exclude:
                candidates.add(sym.upper())
    except Exception as e:
        logger.warning(
            "[DynamicSlotScorer] candidate pool read failed (%s): %s",
            type(e).__name__, e, exc_info=True,
        )
        return []

    if not candidates:
        return []

    scores: Dict[str, int] = defaultdict(int)
    reasons: Dict[str, List[str]] = defaultdict(list)

    # Signal 1: recent setup hits (live_alerts in last N min)
    cutoff_setup = (
        datetime.now(timezone.utc) - timedelta(minutes=lookback_recent_setup_min)
    ).isoformat()
    try:
        for row in db["live_alerts"].aggregate([
            {"$match": {"timestamp": {"$gte": cutoff_setup}}},
            {"$group": {"_id": "$symbol", "n": {"$sum": 1}}},
        ]):
            sym = (row.get("_id") or "").upper()
            if sym in candidates:
                # Diminishing returns: 1 hit gives full weight, 5 hits don't
                # quintuple it (stickier symbols don't dominate the slot pool).
                count = int(row.get("n") or 0)
                bonus = min(count, 3) * (WEIGHT_RECENT_SETUP_HIT // 3)
                scores[sym] += bonus
                reasons[sym].append("setup_hit")
    except Exception as e:
        logger.debug(f"[DynamicSlotScorer] setup_hit signal failed: {e}")

    # Signal 2: news tag (last N hours). Look in `news_articles`
    # collection (or fall back to `news_items` / `material_events`).
    cutoff_news = (
        datetime.now(timezone.utc) - timedelta(hours=lookback_news_hours)
    ).isoformat()
    for col_name in ("news_articles", "news_items", "material_events"):
        try:
            for row in db[col_name].aggregate([
                {"$match": {
                    "$or": [
                        {"published_at": {"$gte": cutoff_news}},
                        {"created_at": {"$gte": cutoff_news}},
                        {"timestamp": {"$gte": cutoff_news}},
                    ]
                }},
                {"$project": {"_id": 0, "symbols": 1}},
                {"$unwind": {"path": "$symbols", "preserveNullAndEmptyArrays": False}},
                {"$group": {"_id": "$symbols", "n": {"$sum": 1}}},
            ]):
                sym = (row.get("_id") or "").upper()
                if sym in candidates and "news" not in reasons[sym]:
                    scores[sym] += WEIGHT_NEWS_TAG
                    reasons[sym].append("news")
            break  # first collection that exists wins
        except Exception:
            continue

    # Signal 3: sector momentum — for each sector ETF that moved >0.5%
    # in the last hour, boost its top intraday-tier components by
    # `services.sector_tag_service`.
    try:
        from services.sector_tag_service import get_sector_tag_service
        sector_svc = get_sector_tag_service()
        # We need the sector ETF moves; read recent quotes from the
        # `quote_history_5m` collection if it exists, else skip
        # (signal is nice-to-have, not load-bearing).
        sector_etfs = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLP",
                       "XLY", "XLU", "XLB", "XLRE", "XLC"]
        moving_sectors: Set[str] = set()
        cutoff_quote = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        for etf in sector_etfs:
            try:
                # Look at the last hour of bars for the ETF — if % move > 0.5%, mark
                bars = list(db.get_collection("bar_data").find(
                    {"symbol": etf, "bar_size": "5 mins",
                     "timestamp": {"$gte": cutoff_quote}},
                    {"_id": 0, "close": 1, "timestamp": 1},
                ).sort("timestamp", 1).limit(20))
                if len(bars) >= 2:
                    first_close = bars[0].get("close") or 0
                    last_close = bars[-1].get("close") or 0
                    if first_close > 0:
                        pct = abs(last_close - first_close) / first_close
                        if pct >= 0.005:
                            moving_sectors.add(etf)
            except Exception:
                continue
        # Boost components of moving sectors. We resolve sector via the
        # tag service, falling back to a simple ADV-cache lookup if the
        # sector tag isn't backfilled yet.
        if moving_sectors:
            for sym in candidates:
                tag = None
                try:
                    tag = sector_svc.get_sector_for(sym)
                except Exception:
                    pass
                # Map sector-name → ETF (rough mapping; close enough)
                sector_to_etf = {
                    "Technology": "XLK", "Information Technology": "XLK",
                    "Energy": "XLE", "Financials": "XLF",
                    "Health Care": "XLV", "Healthcare": "XLV",
                    "Industrials": "XLI", "Consumer Staples": "XLP",
                    "Consumer Discretionary": "XLY", "Utilities": "XLU",
                    "Materials": "XLB", "Real Estate": "XLRE",
                    "Communication Services": "XLC", "Telecom": "XLC",
                }
                etf_for_sym = sector_to_etf.get(tag or "")
                if etf_for_sym and etf_for_sym in moving_sectors:
                    scores[sym] += WEIGHT_SECTOR_MOMENTUM
                    reasons[sym].append(f"sector_{etf_for_sym}")
    except Exception as e:
        logger.debug(f"[DynamicSlotScorer] sector_momentum signal failed: {e}")

    # Signal 4: RVOL spike — read recent live_alerts that have
    # rvol_5min in their snapshot (cheaper than re-deriving). Anything
    # with RVOL ≥ 1.5 in the last `lookback_rvol_min` gets a bump.
    cutoff_rvol = (
        datetime.now(timezone.utc) - timedelta(minutes=lookback_rvol_min)
    ).isoformat()
    try:
        for row in db["live_alerts"].aggregate([
            {"$match": {"timestamp": {"$gte": cutoff_rvol},
                        "snapshot.rvol_5min": {"$gte": 1.5}}},
            {"$group": {"_id": "$symbol",
                        "max_rvol": {"$max": "$snapshot.rvol_5min"}}},
        ]):
            sym = (row.get("_id") or "").upper()
            if sym in candidates and "rvol" not in reasons[sym]:
                scores[sym] += WEIGHT_RVOL_SPIKE
                reasons[sym].append(
                    f"rvol_{row.get('max_rvol', 1.5):.1f}x"
                )
    except Exception as e:
        logger.debug(f"[DynamicSlotScorer] rvol signal failed: {e}")

    # Signal 5: premarket gap (session-open scoped). Active 04:00-10:30 ET only.
    from services.pusher_rotation_service import _now_et
    now_et = _now_et()
    in_premarket_window = (4 <= now_et.hour < 10) or (
        now_et.hour == 10 and now_et.minute < 30
    )
    if in_premarket_window:
        # Cheap proxy: any live_alerts row with `setup_type` containing "gap"
        # in the last 4 hours. Real gap classifier lives in market_setup.
        cutoff_gap = (
            datetime.now(timezone.utc) - timedelta(hours=4)
        ).isoformat()
        try:
            for row in db["live_alerts"].aggregate([
                {"$match": {
                    "timestamp": {"$gte": cutoff_gap},
                    "setup_type": {"$regex": "gap"},
                }},
                {"$group": {"_id": "$symbol", "n": {"$sum": 1}}},
            ]):
                sym = (row.get("_id") or "").upper()
                if sym in candidates and "premarket_gap" not in reasons[sym]:
                    scores[sym] += WEIGHT_PREMARKET_GAP
                    reasons[sym].append("premarket_gap")
        except Exception as e:
            logger.debug(f"[DynamicSlotScorer] premarket_gap signal failed: {e}")

    # Build sorted output
    ranked: List[Dict[str, Any]] = []
    for sym, sc in scores.items():
        if sc <= 0:
            continue
        ranked.append({
            "symbol": sym,
            "score": int(sc),
            "reasons": reasons[sym],
        })
    ranked.sort(key=lambda r: (-r["score"], r["symbol"]))
    return ranked


# ---- Provider adapters for pusher_rotation_service ------------------------

def hot_slots_provider(*, profile: str, db=None, bot=None) -> List[str]:
    """Return up to HOT_SLOT_BUDGET symbols for the hot slots cohort.

    Uses the same scoring as dynamic_overlay_provider, but with weights
    skewed toward news + premarket gap (the hot-slot timeframes are
    when those signals matter most).
    """
    from services.pusher_rotation_service import HOT_SLOT_BUDGET, STATIC_CORE_BUDGET
    static_core = _peek_static_core(db, STATIC_CORE_BUDGET)
    ranked = score_candidates(db, exclude=set(static_core))
    # Top scorers; the rotation service will dedupe with static-core anyway
    return [r["symbol"] for r in ranked[:HOT_SLOT_BUDGET]]


def dynamic_overlay_provider(*, profile: str, db=None, bot=None) -> List[str]:
    """Return up to DYNAMIC_OVERLAY_BUDGET symbols for the dynamic
    overlay cohort. Same source as hot slots, just the next slice."""
    from services.pusher_rotation_service import (
        HOT_SLOT_BUDGET, DYNAMIC_OVERLAY_BUDGET, STATIC_CORE_BUDGET,
    )
    static_core = _peek_static_core(db, STATIC_CORE_BUDGET)
    ranked = score_candidates(db, exclude=set(static_core))
    # Skip the symbols already in hot slots (they'd dedupe at rotation
    # composition anyway, but skipping keeps the cohort distinct).
    return [
        r["symbol"]
        for r in ranked[HOT_SLOT_BUDGET:HOT_SLOT_BUDGET + DYNAMIC_OVERLAY_BUDGET]
    ]


def _peek_static_core(db, budget: int) -> List[str]:
    """Helper: fetch the static-core list so providers exclude it."""
    if db is None:
        return []
    try:
        cursor = (
            db["symbol_adv_cache"]
            .find(
                {"tier": "intraday",
                 "unqualifiable": {"$ne": True},
                 "avg_dollar_volume": {"$gt": 0}},
                {"_id": 0, "symbol": 1},
            )
            .sort("avg_dollar_volume", -1)
            .limit(int(budget))
        )
        return [d["symbol"] for d in cursor if d.get("symbol")]
    except Exception:
        return []
