#!/usr/bin/env python3
"""Generate scripts/patch_a2i_setups_pillar_grades.py — chunk patcher pinned to
the LIVE DGX backend/services/sentcom_service.py bytes (/tmp/sc, sha 0ef6e9f6…).

Edit: get_setups_watching() Source 1 (the /api/sentcom/setups 'live_scanner' dict)
surfaces tqs_score / tqs_grade / tqs_pillar_grades so the Provenance Ring renders
on EVAL scanner cards.
"""
import base64
import hashlib

DGX = "/tmp/sc"
REL = "backend/services/sentcom_service.py"

GRADE_LINE = '                        "grade": alert.tqs_grade or alert.trade_grade,\n'
INSERT = (
    '                        # v19.34.282 (A2i) — surface the per-pillar A-F breakdown +\n'
    '                        # canonical TQS score/grade so the Provenance Ring renders on\n'
    '                        # EVAL scanner cards. The /api/sentcom/setups feed (this dict)\n'
    '                        # previously dropped these, leaving every EVAL card ringless\n'
    '                        # even after A2h populated the alert objects.\n'
    '                        "tqs_score": (int(alert.tqs_score) if getattr(alert, "tqs_score", None) else None),\n'
    '                        "tqs_grade": getattr(alert, "tqs_grade", None) or getattr(alert, "trade_grade", None),\n'
    '                        "tqs_pillar_grades": getattr(alert, "tqs_pillar_grades", None) or {},\n'
)

# Anchor on the unique Source-1 'live_scanner' dict tail so we replace the right block.
OLD = (
    GRADE_LINE +
    '                        "priority": alert.priority.value if alert.priority else "medium",\n'
    '                        "headline": alert.headline,\n'
    '                        "timestamp": timestamp,\n'
    '                        "source": "live_scanner",\n'
    '                        "alert_id": alert.id\n'
    '                    })\n'
)
NEW = OLD.replace(GRADE_LINE, GRADE_LINE + INSERT, 1)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    pristine = open(DGX, "rb").read()
    ob, nb = OLD.encode(), NEW.encode()
    assert pristine.count(ob) == 1, f"OLD not unique in DGX file ({pristine.count(ob)})"
    assert nb not in pristine, "NEW already present — already applied?"
    patched = pristine.replace(ob, nb, 1)
    # sanity: patched must compile
    compile(patched.decode(), REL, "exec")
    pre, post = sha(pristine), sha(patched)
    print("PRE :", pre)
    print("POST:", post)

    patcher = f'''#!/usr/bin/env python3
"""
patch_a2i_setups_pillar_grades.py  —  v19.34.282 (UI Track A · A2i)
"Provenance Ring data on EVAL scanner cards"

The A2 Provenance Ring renders only when a card carries `tqs_pillar_grades`.
EVAL scanner cards are fed by GET /api/sentcom/setups -> get_setups_watching()
Source 1 (live scanner alerts), whose serialized dict DROPPED
tqs_pillar_grades / tqs_grade / tqs_score. So even when the alert object carries
the per-pillar breakdown, the /setups feed stripped it and the ring never rendered
on EVAL cards (OPEN positions use a different, already-fixed feed).

FIX (backend-only, additive, 1 chunk on services/sentcom_service.py): add the
three fields to the Source 1 'live_scanner' dict, read from the alert via getattr
with safe defaults ({{}} / None).

NOTE: A2i surfaces pillars that EXIST on the alert object. Alerts whose object
still lacks pillars (e.g. hydrated carry-forwards) are handled by the companion
A2j fix. PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run; .a2ibak backup.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2i_setups_pillar_grades.py --check
  .venv/bin/python scripts/patch_a2i_setups_pillar_grades.py
  git add backend/ scripts/ && git commit -m "v19.34.282 (A2i): /setups surfaces tqs_pillar_grades for EVAL ring" && git push origin main
  ./start_backend.sh --force
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = {REL!r}
PRE = {pre!r}
POST = {post!r}
OLD_B64 = {base64.b64encode(ob).decode()!r}
NEW_B64 = {base64.b64encode(nb).decode()!r}


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
        print("    ABORT (no write). Send me your copy to rebase:")
        print(f"      gzip -c -9 {{PATH}} | curl -sS --data-binary @- https://paste.rs/")
        sys.exit(3)
    n = cur.count(old)
    if n != 1:
        print(f"  [ANCHOR x{{n}}] OLD chunk not uniquely found — ABORT (no write)."); sys.exit(4)
    out = cur.replace(old, new, 1)
    out_sha = sha(out)
    if out_sha != POST:
        print(f"  [POST-MISMATCH] would produce {{out_sha}} != {{POST}} — ABORT."); sys.exit(5)
    if CHECK:
        print(f"  [CHECK OK] {{PATH}} sha={{cur_sha[:12]}} -> POST {{POST[:12]}} (1 chunk). Re-run without --check.")
        return
    bak = PATH + ".a2ibak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {{PATH}}  {{PRE[:12]}} -> {{POST[:12]}}  (.a2ibak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
'''
    out_path = "/app/scripts/patch_a2i_setups_pillar_grades.py"
    open(out_path, "w", encoding="utf-8").write(patcher)
    print("wrote", out_path, len(patcher), "bytes")


if __name__ == "__main__":
    main()
