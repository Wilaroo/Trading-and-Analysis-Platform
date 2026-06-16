#!/usr/bin/env python3
"""
diag_regime_classifier_distribution.py  —  READ-ONLY  (2026-06-16)

Anomaly under investigation:
    pwire_shadow_eval.py reports
        regime distribution: {'high_vol': 3255, 'range_bound': 320}
    over 5 days of live shadow decisions. Zero `bull_trend`. Zero
    `bear_trend`. That is structurally blocking P-WIRE Phase 2.

This diag triangulates WHY by inspecting every regime-bearing field
inside `confidence_gate_log` for the recent window, plus the upstream
sources that feed it (`market_regime_history` / `multi_tf_state` /
`vix_state` if present). We answer four questions:

  Q1. What VALUES appear in each regime-bearing field of the gate log?
      (Is `bull_trend` / `bear_trend` ever emitted DOWNSTREAM, or always
      coerced to high_vol / range_bound somewhere?)
  Q2. What values are emitted UPSTREAM by the market regime engine?
      (If upstream never emits bull/bear, the classifier itself is the
      bottleneck. If upstream does emit but downstream drops, the wire
      between them is the bottleneck.)
  Q3. Per-symbol per-day modal regime — sanity check against eyeballed
      market action (a recognisable bull day should show bull_trend
      somewhere in the system).
  Q4. Coverage gap: of the shadow-tagged decisions, what % carry a
      regime variant model (regime_model_available true)? Drill down
      by (timeframe, regime) to confirm the v313-deployment hypothesis
      that the live timeseries_service still only loads base variants.

No writes. Pure Mongo reads.

Run on DGX:
    cd ~/Trading-and-Analysis-Platform && \
      set -a && . backend/.env && set +a && \
      .venv/bin/python backend/scripts/diag_regime_classifier_distribution.py
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

# Window we inspect.
WINDOW_DAYS = 7
NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(days=WINDOW_DAYS)

# Every dotted path inside confidence_gate_log that might carry a regime label.
REGIME_PATHS = [
    "live_prediction.regime_shadow.regime",
    "live_prediction.regime_shadow.regime_label",
    "live_prediction.regime_state",
    "regime_state",
    "regime_label",
    "regime",
    "context.regime",
    "context.regime_state",
    "multi_tf.context",
    "multi_tf.regime",
    "market_regime",
    "market_regime.regime",
    "market_regime.state",
    "ensemble.regime",
]

# Trend labels we expect to see (definition-of-done for upstream emission).
TREND_LABELS = (
    "bull_trend", "bear_trend",
    "ALIGNED_UP", "ALIGNED_DOWN",
    "STRONG_UPTREND", "STRONG_DOWNTREND",
    "bull", "bear",
)


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def dotted_get(doc, path):
    parts = path.split(".")
    cur = doc
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def normalize(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("regime", "label", "state", "name"):
            if k in v and isinstance(v[k], str):
                return v[k]
        return str(v)[:60]
    return str(v)[:60]


def section_1_gate_log(db):
    hr(f"Q1. confidence_gate_log — last {WINDOW_DAYS}d : "
       f"regime-bearing field distributions")
    col = db["confidence_gate_log"]
    q = {"_id": {"$gte": _objectid_from_dt(WINDOW_START)}}
    total = col.count_documents(q)
    print(f"  total docs in window: {total:,}")
    if total == 0:
        print("  (window empty — nothing to do)")
        return

    seen = defaultdict(Counter)
    sample_size = min(total, 20_000)
    cursor = col.find(q, projection={"_id": 0, "live_prediction": 1,
                                     "regime": 1, "regime_state": 1,
                                     "regime_label": 1, "context": 1,
                                     "multi_tf": 1, "market_regime": 1,
                                     "ensemble": 1}).limit(sample_size)
    for d in cursor:
        for path in REGIME_PATHS:
            v = normalize(dotted_get(d, path))
            if v is not None:
                seen[path][v] += 1

    print(f"  sampled: {sample_size:,} docs\n")
    for path in REGIME_PATHS:
        if path not in seen:
            continue
        c = seen[path]
        top = c.most_common(8)
        n = sum(c.values())
        trend_n = sum(c[k] for k in c if any(t in k for t in TREND_LABELS))
        trend_pct = (trend_n / n * 100) if n else 0
        print(f"  {path}")
        print(f"    population: {n:,}   trend-labelled: "
              f"{trend_n:,} ({trend_pct:.1f}%)")
        for k, v in top:
            mark = " ← TREND" if any(t in k for t in TREND_LABELS) else ""
            print(f"      {k:>26} : {v:>7,}{mark}")
        if len(c) > 8:
            print(f"      …and {len(c) - 8} more")
        print()


def section_2_upstream(db):
    hr(f"Q2. UPSTREAM regime sources — last {WINDOW_DAYS}d "
       f"(does the engine itself emit bull/bear?)")
    candidate_cols = [
        ("market_regime_history", ("regime", "regime_state", "label")),
        ("market_regime", ("regime", "regime_state", "label")),
        ("multi_tf_state", ("context", "regime")),
        ("regime_decisions", ("regime", "decision")),
        ("vix_state", ("regime",)),
    ]
    have = set(db.list_collection_names())
    for col_name, fields in candidate_cols:
        if col_name not in have:
            print(f"  collection {col_name:>22} : MISSING")
            continue
        col = db[col_name]
        q_field = "_id" if "_id" in (col.find_one() or {}) else None
        # Use _id objectid threshold for time filter; fall back to no filter.
        q = ({"_id": {"$gte": _objectid_from_dt(WINDOW_START)}}
             if q_field else {})
        total = col.count_documents(q)
        print(f"  collection {col_name:>22} : {total:,} docs in window")
        if total == 0:
            continue
        for f in fields:
            c = Counter()
            for d in col.find(q, projection={"_id": 0, f: 1}).limit(20_000):
                v = normalize(d.get(f))
                if v is not None:
                    c[v] += 1
            if not c:
                continue
            n = sum(c.values())
            trend_n = sum(c[k] for k in c if any(t in k for t in TREND_LABELS))
            trend_pct = (trend_n / n * 100) if n else 0
            print(f"    field '{f}': {n:,} non-null   "
                  f"trend-labelled: {trend_n:,} ({trend_pct:.1f}%)")
            for k, v in c.most_common(8):
                mark = " ← TREND" if any(t in k for t in TREND_LABELS) else ""
                print(f"        {k:>22} : {v:>7,}{mark}")
        print()


def section_3_per_day(db):
    hr(f"Q3. Per-day modal regime — last {WINDOW_DAYS}d "
       f"(sanity check against market reality)")
    col = db["confidence_gate_log"]
    q = {"_id": {"$gte": _objectid_from_dt(WINDOW_START)}}
    daily = defaultdict(Counter)
    for d in col.find(q, projection={"_id": 1,
                                     "live_prediction.regime_shadow.regime": 1,
                                     "multi_tf.context": 1,
                                     "regime_state": 1}).limit(50_000):
        day = d["_id"].generation_time.date().isoformat()
        for path in ("live_prediction.regime_shadow.regime",
                     "multi_tf.context", "regime_state"):
            v = normalize(dotted_get(d, path))
            if v is not None:
                daily[day][f"{path}={v}"] += 1
    for day in sorted(daily):
        c = daily[day]
        print(f"  {day}  ({sum(c.values()):,} non-null tags)")
        for k, v in c.most_common(6):
            print(f"      {k:>50} : {v:>5,}")


def section_4_model_availability(db):
    hr("Q4. regime_model_available — coverage gap drill-down")
    col = db["confidence_gate_log"]
    q = {"_id": {"$gte": _objectid_from_dt(WINDOW_START)},
         "live_prediction.regime_shadow": {"$exists": True}}
    n_total = col.count_documents(q)
    n_avail = col.count_documents({**q,
                                   "live_prediction.regime_shadow."
                                   "regime_model_available": True})
    n_missing = col.count_documents({**q,
                                     "live_prediction.regime_shadow."
                                     "regime_model_available": False})
    print(f"  shadow-tagged decisions     : {n_total:,}")
    print(f"  regime_model_available=True : {n_avail:,} "
          f"({(n_avail / n_total * 100) if n_total else 0:.1f}%)")
    print(f"  regime_model_available=False: {n_missing:,} "
          f"({(n_missing / n_total * 100) if n_total else 0:.1f}%)")
    print(f"  field not set               : "
          f"{n_total - n_avail - n_missing:,}")

    # Per (timeframe, regime) breakdown of unavailability.
    print("\n  unavailable cells — (timeframe, regime) breakdown:")
    pipeline = [
        {"$match": {**q,
                    "live_prediction.regime_shadow.regime_model_available": False}},
        {"$group": {
            "_id": {
                "tf": "$live_prediction.regime_shadow.timeframe",
                "regime": "$live_prediction.regime_shadow.regime",
            },
            "n": {"$sum": 1},
        }},
        {"$sort": {"n": -1}},
        {"$limit": 30},
    ]
    for d in col.aggregate(pipeline):
        tf = d["_id"].get("tf") or "?"
        regime = d["_id"].get("regime") or "?"
        print(f"      tf={tf!s:>8}  regime={regime!s:>14}  n={d['n']:>6,}")


def _objectid_from_dt(dt):
    """Build a minimal ObjectId that sorts >= dt for range queries."""
    from bson import ObjectId
    return ObjectId.from_datetime(dt)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    print(f"DB: {DB_NAME}  window: last {WINDOW_DAYS}d "
          f"(since {WINDOW_START.isoformat(timespec='seconds')})")
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]

    section_1_gate_log(db)
    section_2_upstream(db)
    section_3_per_day(db)
    section_4_model_availability(db)

    hr("VERDICT GUIDANCE")
    print("  Look for:")
    print("    • Section 1 — does ANY field in confidence_gate_log ever show")
    print("      bull_trend/bear_trend/ALIGNED_UP/_DOWN? If NO anywhere, the")
    print("      live wire never propagates trend regimes (bottleneck is")
    print("      downstream of regime engine).")
    print("    • Section 2 — does the upstream engine emit trend? If YES")
    print("      while Section 1 shows NO → coercion bug between engine and")
    print("      gate log. If NO → classifier itself is the bottleneck.")
    print("    • Section 3 — sanity per day. If June 12 was a strong-up day")
    print("      in real markets and the modal regime is high_vol — that's")
    print("      our smoking gun for an overly-strict trend threshold.")
    print("    • Section 4 — if regime_model_available is mostly False even")
    print("      for high_vol/range_bound (regimes we KNOW have promoted")
    print("      models), the live timeseries_service.MODEL_CONFIGS")
    print("      doesn't include regime variants in its loader registry.")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
