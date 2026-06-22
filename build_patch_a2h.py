#!/usr/bin/env python3
"""Generates scripts/patch_a2h_provenance_ring_backfill.py — canonical chunk patcher
(base64 OLD/NEW chunk + full-file PRE & POST SHA256 hard guards), per AGENTS.md §2.

Single edit on backend/services/enhanced_scanner.py: widen the _process_new_alert
TQS guard so the per-pillar breakdown is backfilled whenever it's MISSING (not only
when tqs_score<=0), guaranteeing a Provenance Ring on EVERY live scanner card.
"""
import base64
import hashlib
import importlib.util
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
REL = "backend/services/enhanced_scanner.py"
PRISTINE = os.path.join(ROOT, REL + ".a2hbak")   # pre-A2h bytes (baseline)
PATCHED = os.path.join(ROOT, REL)                 # current (A2h applied)

# Pull the byte-exact OLD/NEW chunk straight from the verified anchor patcher
spec = importlib.util.spec_from_file_location(
    "a2h_anchor", os.path.join(ROOT, "scripts/patch_a2h_live_alert_pillar_backfill.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
OLD = mod.EDITS[0]["old"]
NEW = mod.EDITS[0]["new"]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    pristine = open(PRISTINE, "rb").read()
    patched = open(PATCHED, "rb").read()

    # ---- validate the chunk reproduces the patched file byte-for-byte ----
    old_b = OLD.encode("utf-8")
    new_b = NEW.encode("utf-8")
    assert pristine.count(old_b) == 1, f"OLD chunk not unique in pristine ({pristine.count(old_b)})"
    assert patched.count(new_b) == 1, f"NEW chunk not unique in patched ({patched.count(new_b)})"
    reproduced = pristine.replace(old_b, new_b, 1)
    assert reproduced == patched, "chunk replace does NOT reproduce the patched file — abort"

    pre = sha(pristine)
    post = sha(patched)
    print(f"PRE  (pristine) {pre}")
    print(f"POST (patched)  {post}")

    patcher = f'''#!/usr/bin/env python3
"""
patch_a2h_provenance_ring_backfill.py  —  v19.34.281 (UI Track A · A2h)
"Provenance Rings on EVERY live scanner alert"

ROOT CAUSE
----------
The A2 Provenance Ring renders only when a scanner card carries
`tqs_pillar_grades` (the per-pillar A-F breakdown). The A2 changelog assumed
"the scanner payload already carries tqs_pillar_grades (asdict)" — but it is
EMPTY for a subset of live alerts, so only SOME EVAL/POS cards show the ring
(RIOT/TNA/MCHP did; KEYS/TTMI did not).

Those grades are computed only by `_enrich_alert_with_tqs()`, which runs
UNCONDITIONALLY on just the main RTH live-tick scan path (~line 4196). Every
OTHER alert path (bar-poll / daily-swing / re-emit) funnels through the single
universal emission chokepoint `_process_new_alert()`, which re-enriched ONLY
when `tqs_score <= 0`. Alerts that reach the chokepoint with tqs_score>0 (scored
by a lighter step) but an EMPTY tqs_pillar_grades therefore SKIPPED enrichment,
so their WS `scanner_alerts` payload (alert.to_dict()) shipped no breakdown and
the frontend rendered NO ring.

FIX (backend-only, additive)
----------------------------
Widen the chokepoint guard to ALSO re-enrich when the pillar breakdown is
MISSING — not just when the score is absent. Because `_process_new_alert` is
the universal emission point for EVERY alert path, this guarantees pillar grades
(hence a ring) on every live card. `_enrich_alert_with_tqs` is fully
try/except-safe and idempotent; RTH alerts that already carry pillars do not
match the new condition (no double work).

Scope: 1 chunk on backend/services/enhanced_scanner.py. No frontend / no
`yarn build`. PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run;
auto-backup .a2hbak.

USAGE (repo root, e.g. ~/Trading-and-Analysis-Platform):
  .venv/bin/python scripts/patch_a2h_provenance_ring_backfill.py --check
  .venv/bin/python scripts/patch_a2h_provenance_ring_backfill.py
  # COMMIT BEFORE ANY RESTART (StartTrading.bat step-2 git-wipes uncommitted code):
  git add backend/ && git commit -m "v19.34.281 (A2h): backfill tqs_pillar_grades at alert chokepoint" && git push origin main
  ./start_backend.sh --force
Rollback: restore backend/services/enhanced_scanner.py.a2hbak over the target.
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = {REL!r}
PRE = {pre!r}
POST = {post!r}
OLD_B64 = {base64.b64encode(old_b).decode()!r}
NEW_B64 = {base64.b64encode(new_b).decode()!r}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {{PATH}} — run from the repo root."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    old = base64.b64decode(OLD_B64)
    new = base64.b64decode(NEW_B64)

    if cur_sha == POST or new in cur:
        print(f"  [ALREADY-APPLIED] {{PATH}} sha={{cur_sha[:12]}} — nothing to do.")
        return

    if cur_sha != PRE:
        print(f"  [DRIFT] {{PATH}}")
        print(f"    expected PRE  {{PRE}}")
        print(f"    found on disk {{cur_sha}}")
        print("    ABORT (no write). The live file differs from the patch baseline.")
        print("    Send me your copy so I can rebase:")
        print(f"      curl -sS --data-binary @{{PATH}} https://paste.rs/   # paste me the URL")
        sys.exit(3)

    n = cur.count(old)
    if n != 1:
        print(f"  [ANCHOR x{{n}}] OLD chunk not uniquely found — ABORT (no write)."); sys.exit(4)

    out = cur.replace(old, new, 1)
    out_sha = sha(out)
    if out_sha != POST:
        print(f"  [POST-MISMATCH] would produce {{out_sha}} != expected {{POST}} — ABORT (no write)."); sys.exit(5)

    if CHECK:
        print(f"  [CHECK OK] {{PATH}} sha={{cur_sha[:12]}} -> POST {{POST[:12]}} (1 chunk). Re-run without --check to apply.")
        return

    bak = PATH + ".a2hbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {{PATH}}  {{PRE[:12]}} -> {{POST[:12]}}  (.a2hbak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
'''

    out_path = os.path.join(ROOT, "scripts/patch_a2h_provenance_ring_backfill.py")
    open(out_path, "w", encoding="utf-8").write(patcher)
    print(f"wrote {out_path} ({len(patcher)} bytes)")


if __name__ == "__main__":
    main()
