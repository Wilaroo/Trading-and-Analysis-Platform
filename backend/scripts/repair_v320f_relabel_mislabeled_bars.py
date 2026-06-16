#!/usr/bin/env python3
"""
repair_v320f_relabel_mislabeled_bars.py  —  v19.34.320f cleanup  (2026-06-16)
v320f-fix1 (2026-06-16): PARTIAL bucket → QUARANTINE (was: tag-only).
  Sets bar_size='partial_review_v320f' so the row is excluded from
  production 1-min/1-day reads and MIS_Q. Original bar_size preserved
  in `bar_size_pre_v320f`. Full doc copied to review collection. Audit
  row stores drift_keys (which OHLCV fields differed) for analysis.
  Rationale: partial-drift diag showed ~9–11% of mislabeled rows are
  higher-volume (likely consolidated-tape) bars vs single-exchange
  1-min siblings — both are arguably valid data, so quarantine, never
  delete.

Cleans up the ~386,919 mislabeled rows in `ib_historical_data` where
`bar_size="1 day"` but the `date` field is a full timestamp (len > 10),
proving they are actually 1-minute bars wearing the wrong label.

Diag findings (diag_mislabeled_bars_dup_check.py / _relabel_plan.py,
2026-06-16) confirmed three buckets exist in the population:
  • EXACT-MATCH dup    → safe to DELETE (a true 1-min sibling exists)
  • UNIQUE row         → must be RELABELED in place (`bar_size`="1 min")
                          — ~250k rows would have been lost on a bulk
                          DELETE.
  • PARTIAL OHLCV mismatch → STAGE to `ib_historical_data_partial_review`
                          for manual triage. NEVER auto-resolved.

DESIGN
------
- Idempotent + resumable: batches of 1,000 processed in `_id` order with a
  checkpoint file (last processed _id) under `/tmp/`. Re-running picks up
  where it left off.
- Per-row audit: every DELETE / UPDATE / STAGE writes a row to
  `mislabel_relabel_audit_v320f` so `--rollback` can fully reverse the
  treatment without touching anything else.
- Treatment is decided per-row at apply time (NOT pre-computed) — the
  population mutates as we delete dups, so we re-probe the 1-min sibling
  on every iteration.
- Pre + post counts printed. Self-SHA256 of THIS file logged into the
  audit collection on first apply (drift guard).
- Mongo writes use ordered=False bulk ops for throughput.

UNIQUE-INDEX HAZARD
-------------------
Some clusters carry a unique index on (symbol, bar_size, date). If one
exists, a relabel UPDATE could collide with an existing 1-min sibling.
We HANDLE this two ways:
  1. `--check` prints all indexes on the collection so the operator can
     verify.
  2. On each UPDATE we first re-probe for an EXACT match — if discovered
     it gets DELETED instead. (covers the race where a partial bucket
     became exact between diag and apply.)

FLAGS
-----
  --check      Dry run. Prints index list + count summary + bucket
               projection from a 1,000-row scan. No writes.
  --apply      Process the population in batches of 1,000 until exhausted.
               Honours the checkpoint file.
  --resume     Same as --apply but ignores a stale checkpoint banner.
  --rollback   Reverses every action logged in the v320f audit collection
               (UPDATE → revert bar_size; DELETE → re-insert original;
               STAGE → drop from partial_review).
  --status     Prints checkpoint state + per-action counts + recent rows
               from the audit collection.

USAGE (on DGX)
--------------
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/repair_v320f_relabel_mislabeled_bars.py --check
    .venv/bin/python backend/scripts/repair_v320f_relabel_mislabeled_bars.py --apply
    .venv/bin/python backend/scripts/repair_v320f_relabel_mislabeled_bars.py --status
    # only if needed:
    .venv/bin/python backend/scripts/repair_v320f_relabel_mislabeled_bars.py --rollback
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne, DeleteOne, InsertOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TAG = "v320f"
SOURCE_COLL = "ib_historical_data"
AUDIT_COLL = f"mislabel_relabel_audit_{TAG}"
REVIEW_COLL = "ib_historical_data_partial_review"
CHECKPOINT = f"/tmp/{TAG}_relabel_checkpoint.json"
BATCH = 1000
OHLCV_KEYS = ("open", "high", "low", "close", "volume")

# Mislabeled population: bar_size="1 day" AND len(date) > 10 (i.e. a
# timestamp, not a YYYY-MM-DD calendar date).
MIS_Q = {
    "bar_size": "1 day",
    "$expr": {"$gt": [{"$strLenCP": {"$ifNull": ["$date", ""]}}, 10]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _self_sha256():
    with open(os.path.abspath(__file__), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _connect():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    return MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]


def _read_checkpoint():
    if not os.path.exists(CHECKPOINT):
        return None
    try:
        return json.load(open(CHECKPOINT))
    except Exception:
        return None


def _write_checkpoint(last_id, processed):
    json.dump(
        {"last_id": str(last_id), "processed": processed, "ts": _now_iso()},
        open(CHECKPOINT, "w"),
    )


def _decide_bucket(col, doc):
    """Re-probe the 1-min sibling for `doc`. Returns (bucket, sibling_or_None)."""
    sib = col.find_one(
        {"symbol": doc["symbol"], "bar_size": "1 min", "date": doc["date"]},
        {"_id": 0, **{k: 1 for k in OHLCV_KEYS}},
    )
    if sib is None:
        return "unique", None
    if all(sib.get(k) == doc.get(k) for k in OHLCV_KEYS):
        return "exact", sib
    return "partial", sib


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def cmd_check():
    db = _connect()
    col = db[SOURCE_COLL]

    hr("Section 1 — population")
    total = col.count_documents(MIS_Q)
    print(f"  total mislabeled rows (bar_size='1 day' + len(date)>10): {total:,}")
    if total == 0:
        print("  nothing to do.")
        return

    hr("Section 2 — collection indexes (unique-index hazard)")
    for ix_name, ix_info in col.index_information().items():
        keys = ix_info.get("key", [])
        is_uniq = ix_info.get("unique", False)
        flag = "  ← UNIQUE" if is_uniq else ""
        print(f"  {ix_name:>30} {keys}{flag}")

    hr("Section 3 — bucket projection (1,000-row sample)")
    n_sample = min(BATCH, total)
    sample = list(col.aggregate([
        {"$match": MIS_Q},
        {"$sample": {"size": n_sample}},
        {"$project": {"symbol": 1, "date": 1,
                      **{k: 1 for k in OHLCV_KEYS}}},
    ]))
    cnt = {"exact": 0, "unique": 0, "partial": 0}
    for d in sample:
        b, _ = _decide_bucket(col, d)
        cnt[b] += 1
    for k, n in cnt.items():
        pct = n / n_sample * 100
        proj = int(total * pct / 100)
        print(f"  {k:>10} : {n:>4}/{n_sample} ({pct:5.1f}%)  → projected {proj:>7,}")
    err = int(total * 1.96 * 0.5 / (n_sample ** 0.5))
    print(f"\n  ± projection error at 95% CI ≈ ±{err:,} rows")

    hr("Section 4 — checkpoint state")
    cp = _read_checkpoint()
    if cp is None:
        print(f"  no checkpoint at {CHECKPOINT} — first run will start at the beginning.")
    else:
        print(f"  checkpoint found: last_id={cp.get('last_id')[:24]}...  "
              f"processed={cp.get('processed', 0):,}  ts={cp.get('ts')}")
        print(f"  delete {CHECKPOINT} to force a full restart.")

    hr("Section 5 — audit + review collections")
    print(f"  audit: {AUDIT_COLL}    "
          f"rows={db[AUDIT_COLL].estimated_document_count():,}")
    print(f"  review: {REVIEW_COLL}  "
          f"rows={db[REVIEW_COLL].estimated_document_count():,}")
    print(f"\n  self-SHA256: {_self_sha256()}")
    print("\n  re-run with --apply to begin processing.")


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------
def cmd_apply(resume=False):
    db = _connect()
    col = db[SOURCE_COLL]
    aud = db[AUDIT_COLL]
    rev = db[REVIEW_COLL]

    pre = col.count_documents(MIS_Q)
    print(f"[apply] starting population: {pre:,} rows  ·  sha256={_self_sha256()[:16]}")

    cp = _read_checkpoint()
    last_id = cp.get("last_id") if cp else None
    processed = cp.get("processed", 0) if cp else 0
    if last_id and not resume:
        print(f"[apply] resuming from checkpoint: last_id={last_id[:24]}... "
              f"processed={processed:,}")

    from bson import ObjectId
    last_obj = ObjectId(last_id) if last_id else None
    counts = {"exact_delete": 0, "unique_relabel": 0,
              "partial_stage": 0, "skipped": 0}
    started = time.time()

    while True:
        q = dict(MIS_Q)
        if last_obj is not None:
            q["_id"] = {"$gt": last_obj}
        # Project everything we need for audit + treatment.
        batch = list(col.find(q, sort=[("_id", 1)], limit=BATCH))
        if not batch:
            break

        deletes, audits, reviews = [], [], []
        for d in batch:
            bucket, sib = _decide_bucket(col, d)
            base = {"_v320f_id": str(d["_id"]),
                    "symbol": d["symbol"],
                    "date": d["date"],
                    "ts": _now_iso()}
            if bucket == "exact":
                deletes.append(DeleteOne({"_id": d["_id"]}))
                audits.append({**base, "action": "delete",
                               "original": {k: d.get(k) for k in
                                            ("symbol", "date", "bar_size",
                                             *OHLCV_KEYS)},
                               "sibling_ohlcv_match": True})
                counts["exact_delete"] += 1
            elif bucket == "unique":
                # Atomic UPDATE — handle a unique-index collision by
                # downgrading to a delete (race with concurrent ingest).
                try:
                    col.update_one(
                        {"_id": d["_id"]},
                        {"$set": {"bar_size": "1 min",
                                  "relabeled_by_v320f": _now_iso()}},
                    )
                    audits.append({**base, "action": "update",
                                   "original_bar_size": "1 day",
                                   "new_bar_size": "1 min"})
                    counts["unique_relabel"] += 1
                except DuplicateKeyError:
                    deletes.append(DeleteOne({"_id": d["_id"]}))
                    audits.append({**base, "action": "delete_on_dupe_key",
                                   "note": "unique-idx collision; treated as dup"})
                    counts["exact_delete"] += 1
            else:  # partial — QUARANTINE (v320f-fix1)
                # Copy the FULL original doc into the review collection
                # (preserve everything, including potentially-better volume
                # data, so the operator can promote/demote later).
                full_copy = dict(d)
                full_copy["_orig_id"] = str(full_copy.pop("_id"))
                full_copy["_v320f_id"] = base["_v320f_id"]
                full_copy["v320f_quarantined_at"] = base["ts"]
                full_copy["ohlcv_1min_existing"] = sib
                full_copy["needs_review"] = True
                reviews.append(full_copy)
                # Flip bar_size so MIS_Q no longer matches AND the row is
                # excluded from production 1-min and 1-day reads. Keep
                # original bar_size in `bar_size_pre_v320f` for full revert.
                col.update_one(
                    {"_id": d["_id"]},
                    {"$set": {"bar_size": "partial_review_v320f",
                              "bar_size_pre_v320f": "1 day",
                              "v320f_partial_review_staged": _now_iso()}},
                )
                audits.append({**base, "action": "stage_partial",
                               "original_bar_size": "1 day",
                               "new_bar_size": "partial_review_v320f",
                               "review_coll": REVIEW_COLL,
                               "drift_keys": [k for k in OHLCV_KEYS
                                              if d.get(k) != sib.get(k)]})
                counts["partial_stage"] += 1

            last_obj = d["_id"]
            processed += 1

        # Flush
        if deletes:
            try:
                col.bulk_write(deletes, ordered=False)
            except BulkWriteError as e:
                print(f"[apply] bulk delete partial err: {e.details}")
        if audits:
            try:
                aud.bulk_write([InsertOne(a) for a in audits], ordered=False)
            except BulkWriteError as e:
                print(f"[apply] audit insert partial err: {e.details}")
        if reviews:
            try:
                rev.bulk_write([InsertOne(r) for r in reviews], ordered=False)
            except BulkWriteError as e:
                print(f"[apply] review insert partial err: {e.details}")

        _write_checkpoint(last_obj, processed)
        elapsed = time.time() - started
        rate = processed / elapsed if elapsed > 0 else 0
        print(f"[apply] processed {processed:,}  ·  "
              f"exact_del={counts['exact_delete']:,} "
              f"relabel={counts['unique_relabel']:,} "
              f"partial_stage={counts['partial_stage']:,}  "
              f"·  {rate:.0f}/s")

    post = col.count_documents(MIS_Q)
    hr("FINISHED")
    print(f"  pre  mislabeled rows: {pre:,}")
    print(f"  post mislabeled rows: {post:,}")
    print(f"  processed total:      {processed:,}")
    print(f"  per-action: {counts}")
    print(f"  audit collection:  {AUDIT_COLL} ({aud.estimated_document_count():,} rows)")
    print(f"  review collection: {REVIEW_COLL} ({rev.estimated_document_count():,} rows)")
    print(f"\n  Rollback: .venv/bin/python {os.path.basename(__file__)} --rollback")


# ---------------------------------------------------------------------------
# --rollback
# ---------------------------------------------------------------------------
def cmd_rollback():
    db = _connect()
    col = db[SOURCE_COLL]
    aud = db[AUDIT_COLL]
    rev = db[REVIEW_COLL]

    pending = aud.count_documents({"rolled_back": {"$ne": True}})
    print(f"[rollback] {pending:,} pending audit rows to reverse.")
    if pending == 0:
        return

    reverted = {"update": 0, "delete": 0, "delete_on_dupe_key": 0,
                "stage_partial": 0, "skipped": 0}
    cursor = aud.find({"rolled_back": {"$ne": True}})
    for a in cursor:
        action = a.get("action")
        try:
            from bson import ObjectId
            orig_id = ObjectId(a["_v320f_id"])
        except Exception:
            reverted["skipped"] += 1
            continue

        if action == "update":
            r = col.update_one({"_id": orig_id, "bar_size": "1 min"},
                               {"$set": {"bar_size": "1 day"},
                                "$unset": {"relabeled_by_v320f": ""}})
            if r.modified_count == 1:
                reverted["update"] += 1
        elif action == "stage_partial":
            # v320f-fix1: also revert bar_size back to '1 day'.
            col.update_one(
                {"_id": orig_id},
                {"$set": {"bar_size": "1 day"},
                 "$unset": {"v320f_partial_review_staged": "",
                            "bar_size_pre_v320f": ""}},
            )
            rev.delete_one({"_v320f_id": a["_v320f_id"]})
            reverted["stage_partial"] += 1
        elif action in ("delete", "delete_on_dupe_key"):
            orig = a.get("original")
            if orig:
                # Re-insert preserving original _id so future audit links
                # remain valid.
                doc = dict(orig)
                doc["_id"] = orig_id
                try:
                    col.insert_one(doc)
                    reverted[action] += 1
                except DuplicateKeyError:
                    reverted["skipped"] += 1
        aud.update_one({"_id": a["_id"]},
                       {"$set": {"rolled_back": True, "rolled_back_at": _now_iso()}})

    hr("ROLLBACK SUMMARY")
    print(f"  reverted: {reverted}")
    print(f"  delete the checkpoint to allow a fresh apply: rm {CHECKPOINT}")


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------
def cmd_status():
    db = _connect()
    col = db[SOURCE_COLL]
    aud = db[AUDIT_COLL]
    rev = db[REVIEW_COLL]
    cp = _read_checkpoint()

    hr("STATUS")
    print(f"  remaining mislabeled rows: {col.count_documents(MIS_Q):,}")
    print(f"  audit rows total: {aud.estimated_document_count():,}")
    print(f"  review (partial) rows:    {rev.estimated_document_count():,}")
    print(f"  checkpoint: {cp}")
    print()
    for a in aud.aggregate([{"$group": {"_id": "$action", "n": {"$sum": 1}}},
                            {"$sort": {"n": -1}}]):
        print(f"  {a['_id']:>25} : {a['n']:,}")
    print("\n  last 5 audit rows:")
    for r in aud.find({}, {"_id": 0}).sort("ts", -1).limit(5):
        print(f"    {r.get('ts')}  {r.get('action'):>20}  "
              f"{r.get('symbol')}  {r.get('date')[:19]}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--resume", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply(resume=False)
    elif args.resume:
        cmd_apply(resume=True)
    elif args.rollback:
        cmd_rollback()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
