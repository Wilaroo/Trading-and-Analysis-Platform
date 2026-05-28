"""Audit the 98 historical_data_requests failures — v19.34.170 sidecar.

Read-only. Buckets failures by error category + symbol + age + bar size so
the operator can tell at a glance whether the 98 failures are:

  * 1 broken symbol × 98 retries (config bug → fix one row),
  * 98 different symbols × 1 failure each (IB pacing breach → backoff retry),
  * a flood from a specific bar size or date range (pipeline bug),
  * stale failures from a prior session (just clean them up).

Run:
    .venv/bin/python backend/scripts/audit_historical_failures.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
load_dotenv(os.path.join(ROOT, ".env"))

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")


def _short_error(msg: str, n: int = 80) -> str:
    if not msg:
        return "(empty)"
    msg = " ".join(msg.split())
    return msg if len(msg) <= n else msg[: n - 1] + "…"


def _categorize_error(msg: str) -> str:
    """Bucket IB-style error messages into actionable categories."""
    if not msg:
        return "empty"
    m = msg.lower()
    if "pacing violation" in m or "too many requests" in m or "max number of" in m:
        return "ib_pacing_violation"
    if "no security definition" in m or "no contract" in m or "ambiguous" in m:
        return "bad_contract_definition"
    if "no historical data" in m or "no data" in m or "outside trading hours" in m:
        return "no_data_returned"
    if "timeout" in m:
        return "timeout"
    if "not connected" in m or "connection lost" in m or "disconnected" in m:
        return "connection_lost"
    if "permission" in m or "subscribe" in m:
        return "permission_denied"
    if "invalid bar size" in m or "bad bar" in m:
        return "invalid_bar_size"
    return "other"


def main() -> int:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    db = client[DB_NAME]
    col = db["historical_data_requests"]

    failures = list(col.find({"status": "failed"}))
    if not failures:
        print("[OK] No failed rows in historical_data_requests.")
        return 0

    print(f"[INFO] Found {len(failures)} failed historical_data_requests rows.\n")

    # ── 1) By error category ────────────────────────────────────────
    cat_counts: Counter = Counter()
    cat_examples: dict = defaultdict(list)
    for row in failures:
        err = row.get("error") or row.get("error_message") or row.get("last_error") or ""
        cat = _categorize_error(err)
        cat_counts[cat] += 1
        if len(cat_examples[cat]) < 3:
            cat_examples[cat].append(
                f"  • {row.get('symbol','?'):>6} {row.get('bar_size','?'):>10}  "
                f"{_short_error(err)}"
            )

    print("─" * 70)
    print("BY ERROR CATEGORY")
    print("─" * 70)
    for cat, n in cat_counts.most_common():
        pct = 100.0 * n / len(failures)
        print(f"  {cat:<28}  {n:>4} ({pct:5.1f}%)")
        for ex in cat_examples[cat]:
            print(ex)
        print()

    # ── 2) By symbol ─────────────────────────────────────────────────
    sym_counts: Counter = Counter(r.get("symbol", "?") for r in failures)
    distinct_syms = len(sym_counts)
    print("─" * 70)
    print(f"BY SYMBOL  ({distinct_syms} distinct symbols)")
    print("─" * 70)
    top = sym_counts.most_common(15)
    for sym, n in top:
        bar_size_dist = Counter(
            r.get("bar_size", "?") for r in failures if r.get("symbol") == sym
        )
        bars = ", ".join(f"{b}×{c}" for b, c in bar_size_dist.most_common(3))
        print(f"  {sym:<8}  {n:>3}× failures   bar_sizes: {bars}")
    if distinct_syms > 15:
        print(f"  ... and {distinct_syms - 15} more")
    print()

    # ── 3) By bar size ──────────────────────────────────────────────
    bar_counts: Counter = Counter(r.get("bar_size", "?") for r in failures)
    print("─" * 70)
    print("BY BAR SIZE")
    print("─" * 70)
    for bs, n in bar_counts.most_common():
        print(f"  {bs:<14}  {n:>4}")
    print()

    # ── 4) By age (when did the failure occur?) ─────────────────────
    now = datetime.now(timezone.utc)
    age_buckets = Counter()
    for r in failures:
        ts = r.get("failed_at") or r.get("updated_at") or r.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = None
        if not isinstance(ts, datetime):
            age_buckets["unknown"] += 1
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        hours = (now - ts).total_seconds() / 3600
        if hours < 1:
            age_buckets["<1h"] += 1
        elif hours < 6:
            age_buckets["1-6h"] += 1
        elif hours < 24:
            age_buckets["6-24h"] += 1
        elif hours < 168:
            age_buckets["1-7d"] += 1
        else:
            age_buckets[">7d"] += 1

    print("─" * 70)
    print("BY AGE")
    print("─" * 70)
    order = ["<1h", "1-6h", "6-24h", "1-7d", ">7d", "unknown"]
    for k in order:
        if k in age_buckets:
            print(f"  {k:<12}  {age_buckets[k]:>4}")
    print()

    # ── 5) Verdict ───────────────────────────────────────────────────
    print("─" * 70)
    print("VERDICT")
    print("─" * 70)
    top_cat, top_cat_n = cat_counts.most_common(1)[0]
    top_sym_n = top[0][1] if top else 0

    if top_cat == "ib_pacing_violation" and top_cat_n / len(failures) > 0.5:
        print(
            "  → IB pacing breach dominates. Recommend: lower worker "
            "concurrency / longer backoff in the historical worker pool. "
            "Failures can likely be retried after worker tuning."
        )
    elif top_cat == "bad_contract_definition" and top_cat_n / len(failures) > 0.3:
        print(
            "  → Bad contract definitions. Symbols in the BY SYMBOL list "
            "above need to be removed from the backfill watchlist OR "
            "their contract specs corrected (look at exchange + currency)."
        )
    elif top_sym_n > 20:
        print(
            f"  → 1 symbol responsible for {top_sym_n}/{len(failures)} failures. "
            "Likely a single broken row stuck in a retry loop. "
            "Remove or repair that symbol's spec."
        )
    elif age_buckets.get(">7d", 0) > len(failures) * 0.7:
        print(
            "  → 70%+ of failures are stale (>7d old). Recommend: archive "
            "and clear. They're not actively bleeding the pipeline."
        )
    else:
        print(
            "  → Mixed failure modes. Inspect the BY ERROR CATEGORY "
            "section for which bucket to chase first."
        )
    print()

    # ── 6) Optional cleanup hint ────────────────────────────────────
    stale_count = sum(
        1 for r in failures
        if (lambda ts: ts and isinstance(ts, datetime)
            and (now - (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))).days > 7)
        (r.get("failed_at") or r.get("updated_at") or r.get("created_at"))
    )
    if stale_count:
        print(
            f"  ℹ  To archive {stale_count} stale (>7d) failures, run:"
            f"\n     mongosh {DB_NAME} --eval 'db.historical_data_requests"
            f".updateMany({{status:\"failed\", failed_at:{{$lt:new Date("
            f"Date.now()-7*24*3600*1000)}}}}, {{$set:{{status:\"archived\"}}}})'"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
