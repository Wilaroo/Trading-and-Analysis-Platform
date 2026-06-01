#!/usr/bin/env python3
"""
diag_tqs_distribution.py — READ-ONLY TQS score/grade distribution.

Answers: "Is TQS compressing everything into the C band, or is the universe
genuinely mediocre?" Looks across recent `bot_trades` and reports:
  • Histogram of the captured TQS score (entry_context.tqs.score /
    post_gate_score, falling back to top-level tqs_score).
  • Count per TQS grade bucket (A / B+ / B / C+ / C / D / F / none).
  • Mean / median / min / max TQS score.
  • TQS grade vs legacy quality_grade divergence (how often they disagree —
    the "card shows B but TQS is C" effect).
  • Per-setup_type mean TQS (so you can see if specific setups score low).

100% read-only. No writes, no restart.

Run (DGX):
    .venv/bin/python backend/scripts/diag_tqs_distribution.py
    DAYS=7 .venv/bin/python backend/scripts/diag_tqs_distribution.py
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


def grade_from_score(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    if s >= 85:
        return "A"
    if s >= 75:
        return "B+"
    if s >= 65:
        return "B"
    if s >= 55:
        return "C+"
    if s >= 45:
        return "C"
    if s >= 35:
        return "D"
    return "F"


def tqs_of(doc):
    """Return (score, grade) for a trade's captured TQS, or (None, '')."""
    ec = doc.get("entry_context") or {}
    tqs = ec.get("tqs") or {}
    score = (tqs.get("score") or tqs.get("post_gate_score")
             or tqs.get("pre_gate_score") or doc.get("tqs_score") or 0)
    try:
        score = float(score or 0)
    except (TypeError, ValueError):
        score = 0.0
    grade = (tqs.get("unified_grade") or tqs.get("post_gate_grade")
             or doc.get("tqs_grade") or grade_from_score(score) or "")
    return (score if score > 0 else None), grade


def bar(n, total, width=40):
    if total <= 0:
        return ""
    filled = int(round(width * n / total))
    return "█" * filled + "·" * (width - filled)


def main():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    try:
        days = int(os.environ.get("DAYS", "14"))
    except ValueError:
        days = 14

    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    # created_at is ISO string; fall back to all if the field is absent.
    query = {"$or": [
        {"created_at": {"$gte": cutoff}},
        {"ts": {"$gte": cutoff}},
    ]}
    docs = list(db.bot_trades.find(query))
    if not docs:
        docs = list(db.bot_trades.find().sort("_id", -1).limit(500))
        scope = "last 500 trades (no created_at window matched)"
    else:
        scope = f"last {days} days"

    print(f"[diag_tqs_distribution] {len(docs)} trades · {scope} (db={db_name})")
    if not docs:
        print("  (no trades)")
        return 0

    grade_counts = defaultdict(int)
    scores = []
    divergences = 0
    divergence_examples = []
    by_setup = defaultdict(list)

    for d in docs:
        score, grade = tqs_of(d)
        gkey = grade or "none"
        grade_counts[gkey] += 1
        if score is not None:
            scores.append(score)
            by_setup[d.get("setup_type", "?")].append(score)
        # divergence vs legacy quality_grade (first char compare)
        q = (d.get("quality_grade") or "").strip().upper()[:1]
        g = (grade or "").strip().upper()[:1]
        if q and g and q != g:
            divergences += 1
            if len(divergence_examples) < 8:
                divergence_examples.append(
                    f"{d.get('symbol','?'):<6} quality={d.get('quality_grade')} "
                    f"vs TQS={grade}"
                )

    # ── Grade histogram ───────────────────────────────────────────────
    print("\n  TQS GRADE DISTRIBUTION")
    order = ["A", "B+", "B", "C+", "C", "D", "F", "none"]
    total = len(docs)
    for g in order:
        n = grade_counts.get(g, 0)
        if n == 0:
            continue
        print(f"    {g:<5} {n:>4}  {bar(n, total)}  {100*n/total:.0f}%")

    # ── Score stats ───────────────────────────────────────────────────
    if scores:
        scores_sorted = sorted(scores)
        mean = sum(scores) / len(scores)
        median = scores_sorted[len(scores_sorted) // 2]
        print(f"\n  TQS SCORE  n={len(scores)}  "
              f"mean={mean:.1f}  median={median:.1f}  "
              f"min={min(scores):.0f}  max={max(scores):.0f}")
        # 10-wide histogram
        buckets = defaultdict(int)
        for s in scores:
            b = int(s // 10) * 10
            buckets[b] += 1
        print("  SCORE HISTOGRAM (10-wide)")
        for b in range(0, 100, 10):
            n = buckets.get(b, 0)
            if n:
                print(f"    {b:>2}-{b+9:<2} {n:>4}  {bar(n, len(scores))}")

    # ── Divergence ────────────────────────────────────────────────────
    print("\n  LABEL DIVERGENCE (legacy quality_grade vs real TQS)")
    print(f"    {divergences}/{total} trades disagree "
          f"({100*divergences/total:.0f}%) — these show the wrong grade if "
          f"the UI falls back to quality_grade.")
    for ex in divergence_examples:
        print(f"      · {ex}")

    # ── Per-setup mean ────────────────────────────────────────────────
    print("\n  MEAN TQS BY SETUP (n≥2)")
    rows = []
    for setup, vals in by_setup.items():
        if len(vals) >= 2:
            rows.append((sum(vals) / len(vals), len(vals), setup))
    rows.sort()
    for mean_s, n, setup in rows:
        print(f"    {mean_s:>5.1f}  (n={n:<3}) {setup}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
