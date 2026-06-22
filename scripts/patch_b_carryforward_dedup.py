#!/usr/bin/env python3
"""
patch_b_carryforward_dedup.py  —  2026-06-22  (SentCom / DGX Spark)

Stops the carry-forward alert ACCUMULATION that bloated the live scanner to ~148
alerts (operator diag_a11, 2026-06-22) — almost all stale dupes of ~15 names.

ROOT CAUSE: the after-hours ranker (_rank_carry_forward_setups_for_tomorrow)
mints a UNIQUE id `cf_<sym>_<setup>_<unix_ts>` every run (~every 20min), and
_persist_carry_forward_alert upserts by that id — so `carry_forward_alerts` Mongo
grows one doc per (symbol,setup,run). The live path is fine (_process_new_alert
dedups per-symbol), but `_hydrate_carry_forward_alerts_from_mongo` loads ALL
non-expired docs on start() with only an id-uniqueness check, dumping every
historical dupe into _live_alerts.

TWO surgical edits to backend/services/enhanced_scanner.py:
  B1  _hydrate_carry_forward_alerts_from_mongo — collapse to the NEWEST doc per
      (symbol,setup_type,direction) before inserting, and best-effort delete the
      superseded Mongo docs so the collection self-prunes on restart.
  B2  _persist_carry_forward_alert — after each upsert, delete older same-key
      docs so the collection can't re-accumulate within a long session.

SAFE: each edit is span+sha256 guarded; idempotent (re-run is a no-op);
backs up .bcf.bak; AST-compiles before committing. Aborts on drift with a
rebase hint. FAIL-SAFE: every new Mongo op is wrapped in try/except.

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

# ---- Edit B1: hydrate dedup ----
B1_MARKER = "carry-forward HYDRATE DEDUP"
B1_SHA = "2157920760da48d8c3ac98a2d22c869bbf27fc043a8948f9fb6c649e6421267b"
B1_OLD = '''            hydrated = 0
            for doc in docs:
                try:
                    alert = self._inflate_live_alert_from_mongo(doc)
                    if alert and alert.id not in self._live_alerts:
                        self._live_alerts[alert.id] = alert
                        hydrated += 1
                except Exception as e:
                    logger.debug(
                        f"Skipped hydrating carry-forward "
                        f"{doc.get('id')}: {e}"
                    )
            if hydrated:
                logger.info(
                    f"📅 v19.34.6 carry-forward hydrate: restored "
                    f"{hydrated} non-expired gameplan alerts from Mongo "
                    f"(survived backend restart)"
                )
            return hydrated'''
B1_NEW = '''            # 2026-06-22 (B) carry-forward HYDRATE DEDUP — the ranker mints a
            # unique cf_<sym>_<setup>_<ts> id every ~20min and _persist upserts by
            # that id, so carry_forward_alerts accumulates hundreds of dupes of the
            # same (symbol,setup,dir). The old loader loaded ALL of them (id-keyed
            # "not in _live_alerts"), bloating _live_alerts to ~148 cards (operator
            # diag_a11 2026-06-22). Collapse to the NEWEST per (symbol,setup,dir);
            # best-effort delete the superseded Mongo docs so the collection
            # self-prunes on restart.
            def _cf_key(d):
                return ((d.get("symbol") or "").upper(),
                        d.get("setup_type") or "",
                        d.get("direction") or "long")
            newest = {}
            superseded_ids = []
            for doc in sorted(docs, key=lambda d: str(d.get("created_at") or ""), reverse=True):
                k = _cf_key(doc)
                if k in newest:
                    if doc.get("id"):
                        superseded_ids.append(doc["id"])
                else:
                    newest[k] = doc
            if superseded_ids:
                try:
                    self.db.carry_forward_alerts.delete_many({"id": {"$in": superseded_ids}})
                except Exception as _prune_err:
                    logger.debug(f"carry-forward hydrate prune skipped: {_prune_err}")
            hydrated = 0
            for doc in newest.values():
                try:
                    alert = self._inflate_live_alert_from_mongo(doc)
                    if alert and alert.id not in self._live_alerts:
                        self._live_alerts[alert.id] = alert
                        hydrated += 1
                except Exception as e:
                    logger.debug(
                        f"Skipped hydrating carry-forward "
                        f"{doc.get('id')}: {e}"
                    )
            if hydrated:
                logger.info(
                    f"📅 v19.34.6 carry-forward hydrate: restored "
                    f"{hydrated} distinct gameplan alerts from Mongo "
                    f"(collapsed {len(superseded_ids)} dupes; survived restart)"
                )
            return hydrated'''

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
            print("    The function differs from what this patcher targets. No changes written.")
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
    print("\u2705 patch_b applied. Restart the backend to load it: ./start_backend.sh --force")
    print("   (the bloated 148→~15 collapse happens on the NEXT restart's hydrate;")
    print("    new ranker runs self-prune from here on.)")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        main(check_only=("--check" in sys.argv))
