"""
AI Confidence Baseline Service
==============================
Maintains a rolling 30-day baseline of AI confidence per
(symbol, direction) so the scanner can stamp each new alert with a
"how much edge above/below my own baseline" signal.

Why baselines?
--------------
A 75% AI confidence on AAPL means something very different from a 75%
on a thinly-modeled small cap — the same number reflects different
amounts of edge depending on the model's typical confidence for that
ticker. By comparing against a per-symbol rolling mean we surface the
delta (in percentage points) that actually matters: "AAPL alerts
normally fire at 62%, this one is at 78% — that's +16pp edge."

Usage
-----
    from services.ai_confidence_baseline import get_baseline_service
    svc = get_baseline_service()
    svc.set_db(db)
    baseline = svc.get_baseline("AAPL", "long")     # → 62.0 or None
    delta, label = svc.compute_delta("AAPL", "long", current_confidence=78.0)
    # → (16.0, "ABOVE_BASELINE")

Data source
-----------
Reads from the `live_alerts` Mongo collection (already populated by
the scanner). Looks at the last 30 days of alerts for the same
`(symbol, direction)` pair, takes the mean of `ai_confidence` where
that field was populated (>0), and caches the result for 10 minutes.

The 30-day window matches what the user asked for in the audit
follow-up: "AI confidence delta vs the rolling 30-day baseline".
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---- Tunables --------------------------------------------------------------

# Look-back window for the rolling baseline — kept in sync with the user's
# request ("30-day baseline").
BASELINE_LOOKBACK_DAYS = int(os.environ.get("AI_BASELINE_LOOKBACK_DAYS", "30"))

# Minimum number of past alerts before we trust the baseline. Below this we
# return label="INSUFFICIENT_DATA" and let the UI hide the delta pill.
MIN_SAMPLE_FOR_BASELINE = int(os.environ.get("AI_BASELINE_MIN_SAMPLE", "5"))

# Delta thresholds (percentage points above/below baseline) → label.
# Keep the labels short — they render as a pill on the LiveAlertCard.
STRONG_EDGE_PP = 15.0     # current >= baseline + 15pp
ABOVE_PP = 5.0            # current >= baseline + 5pp
BELOW_PP = -5.0           # current <= baseline - 5pp

# Cache TTL — recomputing the rolling mean for every alert would be wasteful,
# 10 min strikes a good balance (baseline barely moves intraday).
CACHE_TTL_SEC = int(os.environ.get("AI_BASELINE_CACHE_TTL_SEC", "600"))

# Edge labels surfaced to UI / API consumers.
LABEL_INSUFFICIENT = "INSUFFICIENT_DATA"
LABEL_STRONG_EDGE = "STRONG_EDGE"
LABEL_ABOVE = "ABOVE_BASELINE"
LABEL_AT = "AT_BASELINE"
LABEL_BELOW = "BELOW_BASELINE"


def _normalize_direction(direction: Optional[str]) -> str:
    """Collapse `long/buy/bullish` → "long" and `short/sell/bearish` → "short"."""
    if not direction:
        return "long"
    d = direction.lower()
    if d in ("long", "buy", "bullish", "up"):
        return "long"
    if d in ("short", "sell", "bearish", "down"):
        return "short"
    return d


def classify_delta(delta_pp: float) -> str:
    """Map a delta (current − baseline, in percentage points) to a label."""
    if delta_pp >= STRONG_EDGE_PP:
        return LABEL_STRONG_EDGE
    if delta_pp >= ABOVE_PP:
        return LABEL_ABOVE
    if delta_pp <= BELOW_PP:
        return LABEL_BELOW
    return LABEL_AT


class AIConfidenceBaselineService:
    """In-memory-cached rolling baseline reader over `live_alerts`."""

    def __init__(self):
        self._db = None
        # cache_key -> (baseline_value, sample_count, expires_at)
        self._cache: Dict[Tuple[str, str], Tuple[Optional[float], int, datetime]] = {}

    def set_db(self, db) -> None:
        self._db = db

    def _cache_get(
        self, symbol: str, direction: str
    ) -> Optional[Tuple[Optional[float], int]]:
        key = (symbol.upper(), _normalize_direction(direction))
        entry = self._cache.get(key)
        if not entry:
            return None
        baseline, sample, expires = entry
        if datetime.now(timezone.utc) > expires:
            self._cache.pop(key, None)
            return None
        return (baseline, sample)

    def _cache_put(
        self,
        symbol: str,
        direction: str,
        baseline: Optional[float],
        sample: int,
    ) -> None:
        key = (symbol.upper(), _normalize_direction(direction))
        expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SEC)
        self._cache[key] = (baseline, sample, expires)

    def _compute_baseline(
        self, symbol: str, direction: str
    ) -> Tuple[Optional[float], int]:
        """Aggregate past alerts in `live_alerts` for the rolling mean.

        Returns ``(baseline_or_None, sample_count)``. Excludes the current
        in-flight alert by only looking at alerts created strictly *before*
        now and only those with `ai_confidence > 0` (i.e. AI prediction
        actually populated)."""
        if self._db is None:
            return (None, 0)

        symbol_u = symbol.upper()
        direction_n = _normalize_direction(direction)

        cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_LOOKBACK_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Match either LONG aliases or SHORT aliases on `direction`. Mongo's
        # `$in` is fine here — direction values are stored exactly as the
        # scanner wrote them on the alert dataclass.
        if direction_n == "long":
            direction_aliases = ["long", "buy", "bullish", "up"]
        else:
            direction_aliases = ["short", "sell", "bearish", "down"]

        try:
            pipeline = [
                {
                    "$match": {
                        "symbol": symbol_u,
                        "direction": {"$in": direction_aliases},
                        "ai_confidence": {"$gt": 0},
                        "created_at": {"$gte": cutoff_iso},
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "mean_conf": {"$avg": "$ai_confidence"},
                        "sample": {"$sum": 1},
                    }
                },
            ]
            rows = list(self._db["live_alerts"].aggregate(pipeline))
        except Exception as e:
            logger.debug(f"baseline aggregate failed for {symbol_u}/{direction_n}: {e}")
            return (None, 0)

        if not rows:
            return (None, 0)

        row = rows[0]
        sample = int(row.get("sample", 0))
        if sample < MIN_SAMPLE_FOR_BASELINE:
            return (None, sample)
        return (round(float(row.get("mean_conf", 0.0)), 2), sample)

    # ---- Public API --------------------------------------------------------
    def get_baseline(
        self, symbol: str, direction: str
    ) -> Tuple[Optional[float], int]:
        """Return ``(baseline_confidence, sample_size)``. ``None`` if the
        sample is below ``MIN_SAMPLE_FOR_BASELINE``."""
        cached = self._cache_get(symbol, direction)
        if cached is not None:
            return cached

        baseline, sample = self._compute_baseline(symbol, direction)
        self._cache_put(symbol, direction, baseline, sample)
        return (baseline, sample)

    def compute_delta(
        self,
        symbol: str,
        direction: str,
        current_confidence: float,
    ) -> Dict[str, Any]:
        """Compute the per-alert edge payload.

        Returns a dict the scanner can splat onto a `LiveAlert`:
            {
              "ai_baseline_confidence": 62.0 | 0.0,
              "ai_confidence_delta_pp": 16.0,
              "ai_edge_label": "STRONG_EDGE" | ... | "INSUFFICIENT_DATA",
              "ai_baseline_sample": 47,
            }
        """
        baseline, sample = self.get_baseline(symbol, direction)
        if baseline is None:
            return {
                "ai_baseline_confidence": 0.0,
                "ai_confidence_delta_pp": 0.0,
                "ai_edge_label": LABEL_INSUFFICIENT,
                "ai_baseline_sample": sample,
            }

        delta = round(float(current_confidence) - baseline, 2)
        return {
            "ai_baseline_confidence": baseline,
            "ai_confidence_delta_pp": delta,
            "ai_edge_label": classify_delta(delta),
            "ai_baseline_sample": sample,
        }

    def invalidate(self, symbol: Optional[str] = None) -> None:
        """Drop cached baselines (call after a bulk alert backfill so the
        next read re-aggregates from Mongo)."""
        if symbol is None:
            self._cache.clear()
            return
        symbol_u = symbol.upper()
        self._cache = {
            k: v for k, v in self._cache.items() if k[0] != symbol_u
        }


# ---- Singleton -------------------------------------------------------------
_service: Optional[AIConfidenceBaselineService] = None


def get_baseline_service() -> AIConfidenceBaselineService:
    global _service
    if _service is None:
        _service = AIConfidenceBaselineService()
    return _service
