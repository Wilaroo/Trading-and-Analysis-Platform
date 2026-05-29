#!/usr/bin/env python3
"""
v19.34.175 — Backfill `unified_grade` on historical bot_trades.

TQS is the single source of truth for a trade's grade. This one-time
(idempotent) script stamps `unified_grade` (and `tqs_grade`/`tqs_score`
when derivable) onto every historical `bot_trades` row that predates the
v19.34.175 write path.

Resolution priority (first non-empty wins):
  1. entry_context.tqs.unified_grade
  2. entry_context.tqs.post_gate_grade
  3. grade-from-score(entry_context.tqs.post_gate_score)
  4. grade-from-score(entry_context.tqs.pre_gate_score / .score)
  5. existing top-level tqs_grade
  6. quality_grade            (legacy composite grade)
  7. smb_grade                (audit-only legacy grade — last resort)

Run (DGX):
    .venv/bin/python backend/scripts/backfill_v19_34_175_unified_grade.py            # apply
    DRY_RUN=1 .venv/bin/python backend/scripts/backfill_v19_34_175_unified_grade.py  # preview only
"""
import os
import sys

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


def resolve(doc):
    """Return (unified_grade, tqs_grade, tqs_score) for a bot_trades doc."""
    ec = doc.get("entry_context") or {}
    tqs = ec.get("tqs") or {}

    post_score = tqs.get("post_gate_score")
    pre_score = tqs.get("pre_gate_score") or tqs.get("score")
    tqs_score = post_score or pre_score or doc.get("tqs_score") or 0

    candidates = [
        tqs.get("unified_grade"),
        tqs.get("post_gate_grade"),
        grade_from_score(post_score),
        grade_from_score(pre_score),
        doc.get("tqs_grade"),
        doc.get("quality_grade"),
        doc.get("smb_grade"),
    ]
    unified = next((c for c in candidates if c and str(c).strip()), "")

    # tqs_grade should reflect TQS specifically (not the legacy fallbacks).
    tqs_grade_candidates = [
        tqs.get("unified_grade"),
        tqs.get("post_gate_grade"),
        grade_from_score(post_score),
        grade_from_score(pre_score),
        doc.get("tqs_grade"),
    ]
    tqs_grade = next((c for c in tqs_grade_candidates if c and str(c).strip()), "")

    return unified, tqs_grade, float(tqs_score or 0)


def main():
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")

    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    # Only touch rows that don't already have a non-empty unified_grade.
    query = {"$or": [{"unified_grade": {"$exists": False}}, {"unified_grade": ""}, {"unified_grade": None}]}
    total = db.bot_trades.count_documents(query)
    print(f"[v19.34.175 backfill] {total} bot_trades rows missing unified_grade "
          f"(db={db_name}, dry_run={dry_run})")

    updated = 0
    skipped = 0
    cursor = db.bot_trades.find(query, {
        "id": 1, "symbol": 1, "entry_context.tqs": 1,
        "tqs_grade": 1, "tqs_score": 1, "quality_grade": 1, "smb_grade": 1,
    })
    for doc in cursor:
        unified, tqs_grade, tqs_score = resolve(doc)
        if not unified:
            skipped += 1
            continue
        update = {"unified_grade": unified}
        if tqs_grade and not (doc.get("tqs_grade") or "").strip():
            update["tqs_grade"] = tqs_grade
        if tqs_score and not doc.get("tqs_score"):
            update["tqs_score"] = tqs_score
        if dry_run:
            updated += 1
            if updated <= 15:
                print(f"  would set {doc.get('symbol','?'):<6} {doc.get('id','?')} -> "
                      f"unified={unified} tqs={tqs_grade or '-'} score={tqs_score:.0f}")
        else:
            db.bot_trades.update_one({"_id": doc["_id"]}, {"$set": update})
            updated += 1

    print(f"[v19.34.175 backfill] {'WOULD UPDATE' if dry_run else 'UPDATED'} {updated} rows; "
          f"{skipped} skipped (no derivable grade).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
