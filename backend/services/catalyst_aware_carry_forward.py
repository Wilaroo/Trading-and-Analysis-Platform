"""
catalyst_aware_carry_forward.py — DESIGN SKETCH (not yet wired)

================================================================
STATUS: Scaffolded 2026-04-28e for future activation.
        Not imported by any router or scheduler yet.
        Activate by:
          1. In `enhanced_scanner._rank_carry_forward_setups_for_tomorrow`,
             after the per-alert TQS gate but before promotion, call
             `enrich_with_catalyst(alert, db)`.
          2. Add a `catalyst_score` field to the promoted alert and let
             the ranker sort by `(catalyst_score, tqs_score)` so news-
             driven candidates surface first.
          3. Optionally raise the TQS bar back to 60 for catalyst-FREE
             stocks while keeping the lowered 50/55 bar for catalyst-
             positive stocks — the precision/recall trade-off the
             operator gets to make.
================================================================

WHY: The carry-forward ranker today is symbol-agnostic — it promotes
any alert above the TQS bar regardless of the underlying stock's
overnight context. A B-grade breakout on a stock with a fresh 8-K
filing is materially more interesting than the same setup on a quiet
stock. This module attaches a simple catalyst score so the ranker
can prefer (and not just promote) high-context setups.

CATALYST SOURCES (all pre-existing in the codebase, just not yet
fused into the carry-forward ranker):
  1. SEC EDGAR 8-K filings (one-off material events) — read from
     `sec_edgar_8k_filings` collection if populated. Operator's P2
     roadmap item; will hook in cleanly when that ships.
  2. Earnings calendar — `upcoming_earnings` collection. Pre-earnings
     positions are usually CLOSED before the print, but post-earnings
     gappers are prime carry-forward candidates.
  3. Overnight news — `live_news` or `intraday_news` collections,
     filtered to material event types (M&A, FDA approval, partnership,
     guidance change, lawsuit). Already populated by the news
     pipeline.
  4. Analyst rating changes — `analyst_actions` collection. Upgrades
     near support / downgrades near resistance amplify the setup.
  5. Premarket gap (computed at runtime from the latest pusher quote
     vs prior close). > 2% gap = automatic catalyst flag.

SCORING (each component contributes additive points, capped at 100):
   8-K filing within 24h        : +35
   Earnings within 5d           : +25
   Material news within 24h     : +20
   Analyst action within 48h    : +10
   Overnight gap > 2%           : +25 (cap stacking with above at 100)
   No catalyst found            : 0

The ranker then sorts:
   (catalyst_score >= 30, tqs_score) DESC

…so any catalyst-positive alert beats every catalyst-free alert,
even if the catalyst-free alert has a slightly higher TQS.

================================================================
INTERFACE
================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Tuning knobs ──────────────────────────────────────────────────────

_LOOKBACK_8K_HOURS         = 24
_LOOKBACK_NEWS_HOURS       = 24
_LOOKBACK_ANALYST_HOURS    = 48
_LOOKBACK_EARNINGS_DAYS    = 5
_GAP_THRESHOLD_PCT         = 0.02  # 2%

_SCORE_8K           = 35
_SCORE_EARNINGS     = 25
_SCORE_NEWS         = 20
_SCORE_ANALYST      = 10
_SCORE_GAP          = 25
_CATALYST_FLOOR     = 30   # score ≥ this => "has catalyst"


# ─── Catalyst component fetchers ───────────────────────────────────────

def _check_8k_filing(db, symbol: str) -> Optional[Dict[str, Any]]:
    """Return the most recent 8-K within `_LOOKBACK_8K_HOURS` for
    `symbol`, or None. Schema follows the planned `sec_edgar_8k_filings`
    collection: `{symbol, filed_at, item_codes, summary}`."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_8K_HOURS)
        return db["sec_edgar_8k_filings"].find_one(
            {"symbol": symbol, "filed_at": {"$gte": cutoff.isoformat()}},
            sort=[("filed_at", -1)],
            projection={"_id": 0},
        )
    except Exception:
        return None


def _check_upcoming_earnings(db, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=_LOOKBACK_EARNINGS_DAYS)
        return db["upcoming_earnings"].find_one(
            {"symbol": symbol,
             "earnings_date": {"$gte": now.isoformat(),
                               "$lte": cutoff.isoformat()}},
            projection={"_id": 0},
        )
    except Exception:
        return None


def _check_recent_news(db, symbol: str) -> Optional[Dict[str, Any]]:
    """Look in both `live_news` and `intraday_news` for material
    events. Returns the most recent material headline if any."""
    material_types = {"merger", "acquisition", "fda_approval",
                      "partnership", "guidance", "lawsuit", "ceo_change"}
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_NEWS_HOURS)
        for coll in ("live_news", "intraday_news"):
            try:
                doc = db[coll].find_one(
                    {"symbol": symbol,
                     "category": {"$in": list(material_types)},
                     "published_at": {"$gte": cutoff.isoformat()}},
                    sort=[("published_at", -1)],
                    projection={"_id": 0},
                )
                if doc:
                    return doc
            except Exception:
                continue
    except Exception:
        return None
    return None


def _check_recent_analyst_action(db, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_ANALYST_HOURS)
        return db["analyst_actions"].find_one(
            {"symbol": symbol, "acted_at": {"$gte": cutoff.isoformat()}},
            sort=[("acted_at", -1)],
            projection={"_id": 0},
        )
    except Exception:
        return None


def _check_overnight_gap(symbol: str, last_quote: Optional[float],
                         prior_close: Optional[float]) -> Optional[float]:
    """Return absolute gap pct (> 0) if it exceeds threshold."""
    if not last_quote or not prior_close or prior_close <= 0:
        return None
    gap_pct = abs(last_quote - prior_close) / prior_close
    return gap_pct if gap_pct >= _GAP_THRESHOLD_PCT else None


# ─── Public API ────────────────────────────────────────────────────────

def compute_catalyst_score(
    db,
    symbol: str,
    last_quote: Optional[float] = None,
    prior_close: Optional[float] = None,
) -> Dict[str, Any]:
    """Return `{score, components, has_catalyst}` for `symbol`.

    `score` ∈ [0, 100], `has_catalyst` is True iff score >= CATALYST_FLOOR.
    `components` is a dict of which sources contributed, suitable for
    embedding in the alert's `entry_context` for post-trade analytics.
    """
    if db is None:
        return {"score": 0, "components": {}, "has_catalyst": False}

    components: Dict[str, Any] = {}
    score = 0

    f8k = _check_8k_filing(db, symbol)
    if f8k:
        components["filing_8k"] = {"items": f8k.get("item_codes"),
                                    "filed_at": f8k.get("filed_at")}
        score += _SCORE_8K

    earn = _check_upcoming_earnings(db, symbol)
    if earn:
        components["earnings"] = {"date": earn.get("earnings_date")}
        score += _SCORE_EARNINGS

    news = _check_recent_news(db, symbol)
    if news:
        components["news"] = {"category": news.get("category"),
                               "headline": news.get("headline")}
        score += _SCORE_NEWS

    analyst = _check_recent_analyst_action(db, symbol)
    if analyst:
        components["analyst"] = {"action": analyst.get("action"),
                                  "firm": analyst.get("firm")}
        score += _SCORE_ANALYST

    gap = _check_overnight_gap(symbol, last_quote, prior_close)
    if gap is not None:
        components["gap"] = {"pct": round(gap, 4)}
        score += _SCORE_GAP

    score = min(score, 100)
    return {
        "score": score,
        "components": components,
        "has_catalyst": score >= _CATALYST_FLOOR,
    }


def enrich_with_catalyst(
    alert_dict: Dict[str, Any],
    db,
    quote_provider=None,
) -> Dict[str, Any]:
    """Mutate `alert_dict` in-place by adding `catalyst` field. Returns
    the mutated dict. Use this from the carry-forward ranker just
    before the TQS gate so promotion can be conditional on context.

    `quote_provider`: optional callable(symbol) -> {"last": float,
    "prior_close": float}. If None, gap component is skipped.
    """
    sym = alert_dict.get("symbol")
    if not sym:
        return alert_dict
    last, prior = None, None
    if quote_provider:
        try:
            q = quote_provider(sym) or {}
            last  = q.get("last") or q.get("price")
            prior = q.get("prior_close")
        except Exception:
            pass
    alert_dict["catalyst"] = compute_catalyst_score(db, sym, last, prior)
    return alert_dict
