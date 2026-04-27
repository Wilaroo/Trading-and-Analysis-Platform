"""
Backfill Readiness Service
==========================

Answers the single most important pre-retrain question:

    "Is the historical backfill complete and clean enough to kick off
     a full Train All cycle — or will the data poison the models?"

This is the module behind `GET /api/backfill/readiness`. It rolls up the
checks we *always* run by hand before a retrain and reduces them to a
green / yellow / red verdict plus a list of blockers/warnings/next-steps.

Checks performed (all read-only, all must complete in <3s):

  1. queue_drained
     - pending + claimed requests on `historical_data_requests`
     - + count of recent failed requests (last 24h)
     → RED if anything pending, YELLOW if failed > 0, GREEN otherwise.

  2. critical_symbols_fresh
     - For the core 10 (SPY/QQQ/DIA/IWM + FAAMG+NVDA), every intraday
       timeframe's latest bar must be within STALE_DAYS.
     → RED if any critical symbol stale on any timeframe.

  3. overall_freshness
     - Aggregate fresh_pct across all tiers × timeframes.
     → GREEN ≥95%, YELLOW ≥85%, RED otherwise.

  4. no_duplicates
     - Spot-check the 10 critical symbols: total bars per (symbol,
       bar_size) must equal count of distinct `date` values.
     → RED if any dupes found (indicates write-path bug).

  5. density_adequate
     - For each tier, % of symbols with ≥min_bars on 5-min timeframe.
     → YELLOW if <90% of tier symbols meet density bar (but not RED —
       density warnings are common and don't block training, just flag
       which symbols will be dropped from the universe).

The module is deliberately side-effect-free: no mutations, no writes,
no background jobs. Safe to poll every 30s from the frontend while the
collectors drain.
"""
from __future__ import annotations

import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait as _fwait
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from .symbol_universe import get_universe

logger = logging.getLogger(__name__)

# Per-check wall-clock budget. With this, the whole endpoint can never
# exceed ~CHECK_BUDGET_SECONDS (checks run in parallel). Hitting the
# budget downgrades that one check to "yellow — slow query" rather than
# hanging the whole endpoint.
#
# 90s is sized for the freshness/density aggregations against ~85M-row
# `ib_historical_data` collections — even with the unique compound index
# hint, MongoDB's planner takes 60-90s when the $in clause spans ~2.6k
# symbols on the user's hardware (DGX Spark + local Mongo).
CHECK_BUDGET_SECONDS = 90

# Index name pymongo's `hint=` param needs (must be a *string* index
# name for aggregate(), not a list of tuples — that one tripped us
# up the first time around). This matches the unique compound index
# created by services/ib_historical_collector.py: line 191.
HIST_INDEX_NAME = "symbol_1_bar_size_1_date_1"


CRITICAL_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN"]

# Same STALE_DAYS contract used by universe-freshness-health.
STALE_DAYS = {
    "1 min": 3, "5 mins": 3, "15 mins": 5, "30 mins": 5,
    "1 hour": 7, "1 day": 3, "1 week": 14,
}
CRITICAL_TIMEFRAMES = ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]

# Minimum bars per (symbol, 5-min) to consider the symbol "dense enough"
# for the training pipeline. Empirically 5-min is the anchor timeframe;
# <780 bars = <2 trading days of 5-min bars = too thin to train on.
DENSITY_MIN_5MIN_BARS = 780

# Verdict thresholds.
FRESHNESS_GREEN_PCT = 95.0
FRESHNESS_YELLOW_PCT = 85.0


def _age_days(date_str: Any, now_utc: datetime) -> float | None:
    """Return age in days given an ISO date string, None if unparseable."""
    if not date_str:
        return None
    try:
        s = str(date_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now_utc - dt).total_seconds() / 86400.0
    except Exception:
        return None


def _market_state_now() -> str:
    """Single source of truth — `services/market_state.classify_market_state`.

    Lazy import keeps backfill readiness importable in early boot before
    the full service tree is wired.
    """
    try:
        from services.market_state import classify_market_state
        return classify_market_state()
    except Exception:
        return "rth"  # safe default — never relax freshness if unsure


def _adjusted_stale_days(tf: str, market_state: str) -> int:
    """Stale-days threshold for a timeframe, expanded on weekends/overnight.

    Friday 16:00 ET → Monday 09:30 ET is ~2.7 days. The base STALE_DAYS
    threshold for 1-min/5-min is 3 days, which means *Monday morning
    before market open* incorrectly flags every intraday symbol as stale.
    The market simply hasn't traded — the Friday-close bar is the most
    recent bar that exists.

    Weekend rule:  add 3 days (covers Fri-close → Mon-premarket comfortably
                   without masking real backfill gaps that span weeks).
    Overnight rule: add 1 day (covers afterhours → next-day premarket).

    Daily / weekly timeframes are unaffected (their thresholds already
    span multi-day windows that absorb a normal weekend gap).
    """
    base = STALE_DAYS.get(tf, 7)
    if tf in ("1 day", "1 week"):
        return base
    if market_state == "weekend":
        return base + 3
    if market_state == "overnight":
        return base + 1
    return base


def _check_queue_drained(db) -> Dict[str, Any]:
    """Check historical_data_requests queue depth + recent failures."""
    q = db["historical_data_requests"]
    pending = q.count_documents({"status": "pending"})
    claimed = q.count_documents({"status": "claimed"})

    # Count recent failures (last 24h). A handful is normal (timeout /
    # no-data) but a flood signals IB Gateway trouble.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        failed_recent = q.count_documents({
            "status": "failed",
            "updated_at": {"$gte": cutoff},
        })
    except Exception:
        failed_recent = None

    in_flight = pending + claimed
    if in_flight > 0:
        status = "red"
        detail = f"{in_flight} requests still in queue (pending={pending}, claimed={claimed})"
    elif failed_recent and failed_recent > 50:
        status = "yellow"
        detail = f"Queue drained but {failed_recent} requests failed in last 24h — review /api/ib-collector/failed-requests"
    else:
        status = "green"
        detail = "Queue fully drained"

    return {
        "status": status,
        "detail": detail,
        "pending": pending,
        "claimed": claimed,
        "failed_recent_24h": failed_recent,
    }


def _check_critical_symbols(db) -> Dict[str, Any]:
    """Every critical symbol must be fresh on every intraday timeframe."""
    now = datetime.now(timezone.utc)
    data = db["ib_historical_data"]
    market_state = _market_state_now()

    per_symbol: List[Dict[str, Any]] = []
    all_fresh = True
    stale_symbols: List[str] = []

    for sym in CRITICAL_SYMBOLS:
        tf_detail = []
        sym_ok = True
        for tf in CRITICAL_TIMEFRAMES:
            doc = data.find_one(
                {"symbol": sym, "bar_size": tf},
                {"_id": 0, "date": 1},
                sort=[("date", -1)],
            )
            latest = doc.get("date") if doc else None
            age = _age_days(latest, now)
            stale_threshold = _adjusted_stale_days(tf, market_state)
            fresh = age is not None and age <= stale_threshold
            if not fresh:
                sym_ok = False
            tf_detail.append({
                "timeframe": tf,
                "latest": latest,
                "age_days": round(age, 2) if age is not None else None,
                "fresh": fresh,
                "stale_threshold_days": stale_threshold,
            })
        if not sym_ok:
            all_fresh = False
            stale_symbols.append(sym)
        per_symbol.append({
            "symbol": sym,
            "all_fresh": sym_ok,
            "timeframes": tf_detail,
        })

    detail_suffix = (f" (market_state={market_state}, weekend buffer applied)"
                     if market_state in ("weekend", "overnight") else "")
    return {
        "status": "green" if all_fresh else "red",
        "detail": ("All critical symbols fresh" + detail_suffix) if all_fresh
                  else f"Stale on intraday: {', '.join(stale_symbols)}{detail_suffix}",
        "all_fresh": all_fresh,
        "stale_symbols": stale_symbols,
        "market_state": market_state,
        "per_symbol": per_symbol,
    }


def _check_no_duplicates(db) -> Dict[str, Any]:
    """Confirm the unique compound index on `ib_historical_data` is in
    place. The index `{symbol:1, bar_size:1, date:1}` is `unique=True`,
    so duplicates are impossible at the write path — verifying its
    existence is O(1) and replaces the previous 50× aggregation scan
    that timed out on multi-million-row collections.
    """
    data = db["ib_historical_data"]
    target_keys = [("symbol", 1), ("bar_size", 1), ("date", 1)]
    try:
        indexes = list(data.list_indexes())
    except Exception as e:
        return {
            "status": "yellow",
            "detail": f"Could not list indexes ({e}); cannot prove dedup guarantee",
            "checked": 0,
            "dupes": [],
        }

    unique_present = any(
        list(idx.get("key", {}).items()) == target_keys
        and bool(idx.get("unique"))
        for idx in indexes
    )

    if unique_present:
        return {
            "status": "green",
            "detail": "Unique index on (symbol, bar_size, date) present — duplicates impossible at write path",
            "checked": 1,
            "dupes": [],
        }
    return {
        "status": "red",
        "detail": "Missing UNIQUE index on (symbol, bar_size, date) — duplicates may exist. Recreate index before training.",
        "checked": 1,
        "dupes": [],
    }


def _check_overall_freshness(db) -> Dict[str, Any]:
    """Simplified freshness rollup — fraction of (symbol, tf) pairs
    with a latest bar inside STALE_DAYS for that timeframe.

    Kept narrow (only the 5 critical timeframes against the ADV-gated
    intraday universe) to stay fast. Users who want the full per-tier
    breakdown go to /api/ib-collector/universe-freshness-health.
    """
    now = datetime.now(timezone.utc)
    data = db["ib_historical_data"]
    market_state = _market_state_now()

    intraday_symbols = get_universe(db, "intraday")
    total_symbols = len(intraday_symbols)
    if not total_symbols:
        return {
            "status": "yellow",
            "detail": "No intraday universe resolved (symbol_adv_cache empty?)",
            "fresh_pct": 0.0,
            "universe_size": 0,
            "market_state": market_state,
        }

    total_fresh = total_pairs = 0
    per_tf: List[Dict[str, Any]] = []
    intraday_list = list(intraday_symbols)
    # Per-symbol find_one with the unique compound index is O(1) per
    # call (~2-5ms). 2.6k symbols × 5 timeframes = ~13s total — well
    # under budget — and bypasses the slow $in:[2.6k symbols] aggregation
    # that timed out at 90s on the user's 85M-row collection.
    PROJ = {"_id": 0, "date": 1}
    SORT = [("date", -1)]
    for tf in CRITICAL_TIMEFRAMES:
        fresh = 0
        # Weekend/overnight-aware threshold (Friday close → Mon open ~2.7d)
        budget = _adjusted_stale_days(tf, market_state)
        for s in intraday_list:
            doc = data.find_one({"symbol": s, "bar_size": tf}, PROJ, sort=SORT)
            age = _age_days(doc.get("date") if doc else None, now)
            if age is not None and age <= budget:
                fresh += 1
        per_tf.append({
            "timeframe": tf,
            "fresh": fresh,
            "total": total_symbols,
            "fresh_pct": round(100.0 * fresh / total_symbols, 2),
            "stale_threshold_days": budget,
        })
        total_fresh += fresh
        total_pairs += total_symbols

    fresh_pct = 100.0 * total_fresh / total_pairs if total_pairs else 0.0
    state_suffix = (f" · market_state={market_state}"
                    if market_state in ("weekend", "overnight") else "")
    if fresh_pct >= FRESHNESS_GREEN_PCT:
        status = "green"
        detail = f"Overall intraday freshness {fresh_pct:.1f}% (≥{FRESHNESS_GREEN_PCT}%){state_suffix}"
    elif fresh_pct >= FRESHNESS_YELLOW_PCT:
        status = "yellow"
        detail = f"Overall intraday freshness {fresh_pct:.1f}% (below {FRESHNESS_GREEN_PCT}% target, above {FRESHNESS_YELLOW_PCT}% floor){state_suffix}"
    else:
        status = "red"
        detail = f"Overall intraday freshness {fresh_pct:.1f}% (below {FRESHNESS_YELLOW_PCT}% floor){state_suffix}"

    return {
        "status": status,
        "detail": detail,
        "fresh_pct": round(fresh_pct, 2),
        "universe_size": total_symbols,
        "market_state": market_state,
        "per_timeframe": per_tf,
    }


def _check_density_adequate(db) -> Dict[str, Any]:
    """% of intraday-tier symbols with ≥DENSITY_MIN_5MIN_BARS on 5-min.

    Symbols below the floor are typically newly-listed or thinly-traded
    names that will be dropped from the training universe. Warning-only
    because it's expected to have a tail — we just need to know how big.
    """
    data = db["ib_historical_data"]

    intraday_symbols = sorted(get_universe(db, "intraday"))
    if not intraday_symbols:
        return {
            "status": "yellow",
            "detail": "No intraday universe resolved",
            "dense_pct": 0.0,
            "low_density_sample": [],
        }

    # Per-symbol count_documents with a limit-bounded count is O(min(N,
    # threshold)) per call thanks to the (symbol, bar_size, date) index
    # — at most 780 index entries scanned per symbol. 2.6k × ~5ms = ~13s
    # total, replacing the slow $in:[2.6k symbols] aggregation that
    # timed out at 90s on the user's 85M-row collection.
    counts: Dict[str, int] = {}
    for s in intraday_symbols:
        counts[s] = data.count_documents(
            {"symbol": s, "bar_size": "5 mins"},
            limit=DENSITY_MIN_5MIN_BARS,
        )

    low: List[Dict[str, Any]] = []
    dense = 0
    for s in intraday_symbols:
        n = counts.get(s, 0)
        if n >= DENSITY_MIN_5MIN_BARS:
            dense += 1
        else:
            low.append({"symbol": s, "bars": n})

    total = len(intraday_symbols)
    dense_pct = 100.0 * dense / total if total else 0.0

    status = "green" if dense_pct >= 90.0 else "yellow"
    detail = (
        f"{dense_pct:.1f}% of intraday symbols have ≥{DENSITY_MIN_5MIN_BARS} 5-min bars"
        f" ({len(low)} below threshold)"
    )
    low_sorted = sorted(low, key=lambda x: x["bars"])[:10]
    return {
        "status": status,
        "detail": detail,
        "dense_pct": round(dense_pct, 2),
        "total_symbols": total,
        "dense_symbols": dense,
        "low_density_count": len(low),
        "low_density_sample": low_sorted,
        "threshold_bars": DENSITY_MIN_5MIN_BARS,
    }


# Color ranking for computing the overall verdict.
_RANK = {"green": 0, "yellow": 1, "red": 2}
_REVERSE = {v: k for k, v in _RANK.items()}


def _yellow_timeout(name: str) -> Dict[str, Any]:
    return {
        "status": "yellow",
        "detail": f"Check '{name}' exceeded {CHECK_BUDGET_SECONDS}s budget — slow Mongo aggregation. Verify index '{HIST_INDEX_NAME}' is present.",
        "timed_out": True,
    }


def _yellow_error(name: str, exc: BaseException) -> Dict[str, Any]:
    return {
        "status": "yellow",
        "detail": f"Check '{name}' raised {type(exc).__name__}: {exc}",
        "error": True,
    }


# Module-level executor — reused across requests so we don't pay
# thread-startup cost on every poll. Workers > #checks gives buffer
# for any leaked threads from previous timed-out runs (Python can't
# kill threads, only mark them done).
_CHECK_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="readiness")


def compute_readiness(db) -> Dict[str, Any]:
    """Run all readiness checks in parallel against a single deadline.

    Whole-endpoint wall-clock is bounded by `CHECK_BUDGET_SECONDS`. Any
    check that hasn't finished by the deadline is recorded as `yellow —
    timed out` and the in-flight Mongo aggregation is cancelled
    (`fut.cancel()` + `maxTimeMS` server-side). Crucially we DO NOT
    `shutdown(wait=True)` a per-request pool — that's what caused the
    earlier ≥120s hangs (inner pool's __exit__ blocked waiting on a
    still-running Mongo call).
    """
    check_fns = {
        "queue_drained":          _check_queue_drained,
        "critical_symbols_fresh": _check_critical_symbols,
        "overall_freshness":      _check_overall_freshness,
        "no_duplicates":          _check_no_duplicates,
        "density_adequate":       _check_density_adequate,
    }
    futures = {name: _CHECK_POOL.submit(fn, db) for name, fn in check_fns.items()}
    deadline = _time.monotonic() + CHECK_BUDGET_SECONDS
    pending = set(futures.values())

    # Drain futures as they complete, bounded by the global deadline.
    while pending:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        _done, pending = _fwait(pending, timeout=remaining, return_when=FIRST_COMPLETED)

    checks: Dict[str, Dict[str, Any]] = {}
    for name, fut in futures.items():
        if fut.done():
            try:
                checks[name] = fut.result()
            except Exception as exc:
                logger.error(f"readiness check {name} failed: {exc}", exc_info=True)
                checks[name] = _yellow_error(name, exc)
        else:
            # Best-effort cancel — won't kill an in-flight Mongo call,
            # but prevents the future from being scheduled if it's still
            # queued, and lets it finish in the background harmlessly.
            fut.cancel()
            checks[name] = _yellow_timeout(name)

    # Overall verdict = worst check.
    worst = max((_RANK[c["status"]] for c in checks.values()), default=0)
    verdict = _REVERSE[worst]

    blockers = [c["detail"] for c in checks.values() if c["status"] == "red"]
    warnings = [c["detail"] for c in checks.values() if c["status"] == "yellow"]

    # Ready-to-train is binary: GREEN only.
    ready = verdict == "green"

    next_steps: List[str] = []
    if checks["queue_drained"]["status"] == "red":
        next_steps.append("Wait for historical_data_requests queue to drain (pending + claimed = 0).")
    if checks["critical_symbols_fresh"]["status"] == "red":
        stale = checks["critical_symbols_fresh"]["stale_symbols"]
        next_steps.append(f"Re-run smart-backfill for: {', '.join(stale)}")
    if checks["no_duplicates"]["status"] == "red":
        next_steps.append("Inspect /api/backfill/readiness `no_duplicates.dupes` and run a dedup pass before training.")
    if checks["overall_freshness"]["status"] == "red":
        next_steps.append("Run POST /api/ib-collector/smart-backfill to close freshness gap.")
    if checks["density_adequate"]["status"] == "yellow":
        next_steps.append("Review density_adequate.low_density_sample — these symbols will be dropped from training.")

    if ready:
        summary = "READY — all checks green. Safe to trigger Train All."
    elif verdict == "yellow":
        summary = "NOT READY — warnings present. Review and proceed at your own risk."
    else:
        summary = "NOT READY — blockers present. Do not trigger training."

    return {
        "success": True,
        "verdict": verdict,
        "ready_to_train": ready,
        "summary": summary,
        "blockers": blockers,
        "warnings": warnings,
        "next_steps": next_steps,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
