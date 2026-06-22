#!/usr/bin/env python3
"""
patch_b_carryforward_dedup.py  —  2026-06-22 (rebased v2)  (SentCom / DGX Spark)

Stops the carry-forward alert ACCUMULATION that bloated the live scanner to ~148
alerts (operator diag_a11, 2026-06-22) — almost all stale dupes of ~15 names.

ROOT CAUSE: the after-hours ranker mints a UNIQUE id `cf_<sym>_<setup>_<unix_ts>`
every run (~every 20min), and _persist_carry_forward_alert upserts by that id —
so `carry_forward_alerts` Mongo grows one doc per (symbol,setup,run). The live
path is fine (_process_new_alert dedups per-symbol), but
_hydrate_carry_forward_alerts_from_mongo loads ALL non-expired docs on start()
with only an id-uniqueness check, dumping every historical dupe into _live_alerts.

TWO surgical edits to backend/services/enhanced_scanner.py:
  B1  _hydrate_... — insert a dedup step that collapses `docs` to the NEWEST per
      (symbol,setup_type,direction) BEFORE the existing hydrate loop, and best-
      effort delete the superseded Mongo docs. The loop (and its A2j pillar
      backfill) is left untouched — it just iterates fewer docs.
  B2  _persist_... — after each upsert, delete older same-key docs so the
      collection can't re-accumulate within a long session.

SAFE: each edit is span+sha256 guarded; idempotent; backs up .bcf.bak;
AST-compiles before committing. Aborts on drift with a rebase hint.
FAIL-SAFE: every new Mongo op is wrapped in try/except.

    .venv/bin/python scripts/patch_b_carryforward_dedup.py --check
    .venv/bin/python scripts/patch_b_carryforward_dedup.py
    .venv/bin/python scripts/patch_b_carryforward_dedup.py --rollback
"""
import hashlib
import os
import sys
import ast
import shutil

CANDIDATE_PATHS = [
    "backend/services/enhanced_scanner.py",
    "services/enhanced_scanner.py",
    os.path.join(os.path.dirname(__file__), "..", "backend", "services", "enhanced_scanner.py"),
]

# ---- Edit B1: hydrate dedup (insert before the loop) ----
B1_MARKER = "carry-forward HYDRATE DEDUP"
B1_SHA = "fa38340fcd47a37e1edc5910158f6abde8caf5631556ab7d87aeaa20fb25f1de"
B1_OLD = '''                    {"_id": 0},
                )
            )
            hydrated = 0
            backfilled = 0'''
B1_NEW = '''                    {"_id": 0},
                )
            )
            # 2026-06-22 (B) carry-forward HYDRATE DEDUP — collapse to newest per
            # (symbol,setup,dir) BEFORE the hydrate loop. The ranker mints a unique
            # cf_<sym>_<setup>_<ts> id every ~20min and _persist upserts by it, so
            # carry_forward_alerts accumulates hundreds of dupes the loader dumped
            # wholesale into _live_alerts (~148 cards; operator diag_a11 2026-06-22).
            # Best-effort delete the superseded Mongo docs so the collection self-
            # prunes on restart. The existing loop (and its A2j pillar backfill) is
            # left untouched — it just iterates fewer docs.
            try:
                _cf_newest = {}
                _cf_superseded = []
                for _cf_d in sorted(docs, key=lambda d: str(d.get("created_at") or ""), reverse=True):
                    _cf_k = ((_cf_d.get("symbol") or "").upper(),
                             _cf_d.get("setup_type") or "",
                             _cf_d.get("direction") or "long")
                    if _cf_k in _cf_newest:
                        if _cf_d.get("id"):
                            _cf_superseded.append(_cf_d["id"])
                    else:
                        _cf_newest[_cf_k] = _cf_d
                docs = list(_cf_newest.values())
                if _cf_superseded:
                    try:
                        self.db.carry_forward_alerts.delete_many({"id": {"$in": _cf_superseded}})
                    except Exception as _cf_prune_err:
                        logger.debug(f"carry-forward hydrate prune skipped: {_cf_prune_err}")
                    logger.info(
                        f"📅 (B) carry-forward hydrate dedup: collapsed "
                        f"{len(_cf_superseded)} dupes → {len(docs)} distinct"
                    )
            except Exception as _cf_dedup_err:
                logger.debug(f"carry-forward hydrate dedup skipped: {_cf_dedup_err}")
            hydrated = 0
            backfilled = 0'''

# ---- Edit B2: persist-time prune ----
B2_MARKER = "carry-forward persist prune"
B2_SHA = "a06a2ee5d9b3969802a66a99bd8d2cba712222b5221cb81b483d9ecbf0456d84"
B2_OLD = '''            self.db.carry_forward_alerts.update_one(
                {"id": alert.id},
                {"$set": doc},
                upsert=True,
            )'''
B2_NEW = '''            self.db.carry_forward_alerts.update_one(
                {"id": alert.id},
                {"$set": doc},
                upsert=True,
            )
            # 2026-06-22 (B) carry-forward persist prune — drop older same-key
            # gameplan docs so the collection can't accumulate one doc per ~20min
            # ranker run for the same (symbol,setup,dir). Keep the just-written newest.
            try:
                self.db.carry_forward_alerts.delete_many({
                    "symbol": alert.symbol,
                    "setup_type": alert.setup_type,
                    "direction": getattr(alert, "direction", "long"),
                    "id": {"$ne": alert.id},
                })
            except Exception as _prune_err:
                logger.debug(f"carry-forward persist prune skipped: {_prune_err}")'''

EDITS = [
    ("B1 hydrate-dedup", B1_MARKER, B1_SHA, B1_OLD, B1_NEW),
    ("B2 persist-prune", B2_MARKER, B2_SHA, B2_OLD, B2_NEW),
]


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _find_path():
    p = next((c for c in CANDIDATE_PATHS if os.path.isfile(c)), None)
    if not p:
        print("ERROR: enhanced_scanner.py not found. Run from the repo root.")
        sys.exit(2)
    return os.path.abspath(p)


def rollback():
    path = _find_path()
    bak = path + ".bcf.bak"
    if not os.path.isfile(bak):
        print(f"No backup at {bak} — nothing to roll back.")
        sys.exit(1)
    shutil.copy2(bak, path)
    print(f"Rolled back {path} from {bak}.")


def main(check_only=False):
    path = _find_path()
    content = open(path, encoding="utf-8").read()
    print(f"Target: {path}")
    print(f"PRE  whole-file sha256: {_sha(content)}")

    new_content = content
    applied, skipped = [], []
    for label, marker, sha, old, new in EDITS:
        if marker in new_content:
            print(f"  [{label}] idempotent marker present — skip.")
            skipped.append(label)
            continue
        if new_content.count(old) != 1:
            print(f"  ABORT [{label}] — anchor not unique (count={new_content.count(old)}). No changes written.")
            print("    rebase: re-grep the function and paste it back so I can re-anchor.")
            sys.exit(1)
        actual = _sha(old)
        if actual != sha:
            print(f"  ABORT [{label}] — span sha drift.\n      expected {sha}\n      actual   {actual}")
            print("    The anchored span differs byte-for-byte. Paste a `sed -n` of it and I'll rebase.")
            sys.exit(1)
        new_content = new_content.replace(old, new, 1)
        applied.append(label)

    if not applied:
        print("  Nothing to apply (all edits already present). \u2705")
        return

    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  ABORT — patched content failed to parse: {e}. No changes written.")
        sys.exit(1)

    if check_only:
        print(f"  --check OK: would apply {applied}; patched file AST-compiles.")
        print(f"  PREDICTED POST whole-file sha256: {_sha(new_content)}")
        print("  (no changes written)")
        return

    bak = path + ".bcf.bak"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  applied {applied}" + (f" · skipped {skipped}" if skipped else ""))
    print(f"Backup written: {bak}")
    print(f"POST whole-file sha256: {_sha(new_content)}")
    print("\u2705 patch_b applied. Restart the backend: ./start_backend.sh --force")
    print("   (the bloated 148→~15 collapse happens on the NEXT restart's hydrate;")
    print("    new ranker runs self-prune from here on.)")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        main(check_only=("--check" in sys.argv))
