#!/usr/bin/env python3
"""
purge_outcomes_before_cutoff.py — REVERSIBLE archive-then-purge of trade/outcome
docs older than a cutoff date. Default is a SAFE DRY-RUN (writes nothing).

Why reversible: instead of a blind delete, each collection's pre-cutoff docs are
first COPIED (with original _id) to  {coll}__archive_pre_<YYYYMMDD>  and only
THEN deleted from the live collection. Restore anytime with --rollback.

Per the read-only preview (diag_outcomes_purge_preview.py):
  • the learning rebuild window (last 500 trade_outcomes) is ~0% pre-cutoff, so
    purging does NOT move current win-rate / EV stats;
  • ~30% of pre-cutoff bot_trades is broken-path/artifact (phantom/orphaned/
    consolidated/external) — genuine history is preserved in the archive.

Collections (default): bot_trades, alert_outcomes, trade_outcomes
  - bot_trades: CLOSED-only by default (won't touch any lingering open/pending
    state); pass --include-open to purge every pre-cutoff bot_trade.
  - date field is auto-detected per collection (created_at / closed_at / ...).

USAGE (repo root, DGX):
  # 1) DRY-RUN (default) — shows exactly what each step would archive/delete:
  .venv/bin/python backend/scripts/purge_outcomes_before_cutoff.py --before 2026-06-01
  # 2) EXECUTE (archive then delete):
  .venv/bin/python backend/scripts/purge_outcomes_before_cutoff.py --before 2026-06-01 --confirm
  # 3) ROLLBACK (restore live from the archives):
  .venv/bin/python backend/scripts/purge_outcomes_before_cutoff.py --before 2026-06-01 --rollback --confirm
  # narrow scope:  --collections trade_outcomes,alert_outcomes
After --confirm you may rebuild learning_stats (optional — ~0% window impact).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_COLLECTIONS = ["bot_trades", "alert_outcomes", "trade_outcomes"]
DATE_FIELDS = ["created_at", "closed_at", "executed_at", "timestamp", "date"]
BATCH = 1000


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services").is_dir():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pick_date_field(coll):
    doc = coll.find_one({}, {f: 1 for f in DATE_FIELDS})
    if not doc:
        return None
    for f in DATE_FIELDS:
        if doc.get(f):
            return f
    return None


def _archive_name(coll_name, cutoff):
    compact = cutoff.replace("-", "").replace(":", "").split("T")[0]
    return f"{coll_name}__archive_pre_{compact}"


def _filter_for(coll_name, df, cutoff_iso, include_open):
    f = {df: {"$lt": cutoff_iso}}
    if coll_name == "bot_trades" and not include_open:
        f["status"] = {"$regex": "^closed"}
    return f


def _copy_in_batches(src_cursor, dst_coll):
    buf, total = [], 0
    for doc in src_cursor:
        buf.append(doc)
        if len(buf) >= BATCH:
            dst_coll.insert_many(buf, ordered=False)
            total += len(buf)
            buf = []
    if buf:
        dst_coll.insert_many(buf, ordered=False)
        total += len(buf)
    return total


def do_purge(db, collections, cutoff_iso, cutoff, include_open, confirm):
    existing = set(db.list_collection_names())
    mode = "EXECUTE" if confirm else "DRY-RUN"
    print(f"\n=== PURGE ({mode}) — delete docs older than {cutoff} ===")
    grand = 0
    for name in collections:
        if name not in existing:
            print(f"\n  {name}: not present — skip")
            continue
        coll = db[name]
        df = _pick_date_field(coll)
        if not df:
            print(f"\n  {name}: no date field — SKIP (cannot cutoff safely)")
            continue
        filt = _filter_for(name, df, cutoff_iso, include_open)
        live_pre = coll.count_documents(filt)
        arch_name = _archive_name(name, cutoff)
        arch = db[arch_name]
        arch_existing = arch.estimated_document_count() if arch_name in existing else 0
        scope = "" if (name != "bot_trades" or include_open) else " [closed-only]"
        print(f"\n  {name}{scope}  date_field={df}")
        print(f"    pre-cutoff live docs : {live_pre}")
        print(f"    archive target       : {arch_name} (currently {arch_existing} docs)")
        grand += live_pre
        if live_pre == 0:
            print("    nothing to purge (idempotent no-op).")
            continue
        if arch_existing > 0:
            print(f"    ⚠ archive already has {arch_existing} docs — ABORT this collection to avoid")
            print(f"      double-archiving. --rollback first, or drop {arch_name} manually.")
            continue
        if not confirm:
            print(f"    DRY-RUN: would archive {live_pre} → {arch_name}, then delete {live_pre} from {name}.")
            continue
        # EXECUTE: archive first, verify, then delete.
        copied = _copy_in_batches(coll.find(filt), arch)
        arch_cnt = arch.count_documents({})
        print(f"    archived {copied} docs → {arch_name} (archive now {arch_cnt})")
        if arch_cnt < live_pre:
            print(f"    ❌ archive count {arch_cnt} < live_pre {live_pre} — NOT deleting. Investigate.")
            continue
        res = coll.delete_many(filt)
        remaining = coll.count_documents(filt)
        print(f"    deleted {res.deleted_count} from {name}; pre-cutoff remaining now {remaining}")
        if remaining != 0:
            print("    ⚠ some pre-cutoff docs remain (concurrent writes?) — re-run to finish.")
    print(f"\n  TOTAL pre-cutoff docs across scope: {grand}")
    if not confirm:
        print("  (DRY-RUN — nothing written. Re-run with --confirm to execute.)")


def do_rollback(db, collections, cutoff, confirm):
    existing = set(db.list_collection_names())
    mode = "EXECUTE" if confirm else "DRY-RUN"
    print(f"\n=== ROLLBACK ({mode}) — restore live collections from archives ===")
    for name in collections:
        arch_name = _archive_name(name, cutoff)
        if arch_name not in existing:
            print(f"\n  {name}: no archive {arch_name} — skip")
            continue
        arch = db[arch_name]
        n = arch.count_documents({})
        print(f"\n  {name}: archive {arch_name} has {n} docs")
        if not confirm:
            print(f"    DRY-RUN: would restore {n} docs back into {name}.")
            continue
        restored = _copy_in_batches(arch.find({}), db[name])
        print(f"    restored {restored} docs → {name}")
        print(f"    (archive {arch_name} left in place; drop it manually when satisfied)")


def main():
    cutoff = "2026-06-01"
    collections = DEFAULT_COLLECTIONS[:]
    confirm = "--confirm" in sys.argv
    rollback = "--rollback" in sys.argv
    include_open = "--include-open" in sys.argv
    if "--before" in sys.argv:
        try:
            cutoff = sys.argv[sys.argv.index("--before") + 1]
        except Exception:
            pass
    if "--collections" in sys.argv:
        try:
            collections = [c.strip() for c in sys.argv[sys.argv.index("--collections") + 1].split(",") if c.strip()]
        except Exception:
            pass
    cutoff_iso = cutoff if "T" in cutoff else cutoff + "T00:00:00+00:00"

    backend = _find_backend()
    _load_env(backend)
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 84)
    print(f"purge_outcomes_before_cutoff  cutoff={cutoff}  collections={collections}")
    print(f"  DB={os.environ.get('DB_NAME','tradecommand')}  include_open={include_open}  "
          f"{datetime.now(timezone.utc).isoformat()[:19]}Z")
    print("=" * 84)

    if rollback:
        do_rollback(db, collections, cutoff, confirm)
    else:
        do_purge(db, collections, cutoff_iso, cutoff, include_open, confirm)

    print("\n" + "=" * 84)
    if confirm and not rollback:
        print("Purge executed. Archives created: {coll}__archive_pre_<date> (restorable via --rollback).")
        print("Optional: rebuild learning_stats from the cleaned corpus (note: ~0% window impact).")
    print("=" * 84)


if __name__ == "__main__":
    main()
