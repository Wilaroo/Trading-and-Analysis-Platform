#!/usr/bin/env python3
"""Generate scripts/patch_a2k_ring_pillar_colors.py — whole-file patcher (gzip+b64,
PRE & POST SHA256 hard-guards) for the FRONTEND component
frontend/src/components/sentcom/v5/ProvenanceRing.jsx.

Change: color each ring arc by a FIXED per-pillar identity hue (5 distinct
colors) and encode the pillar grade as the bright fill length over a faint
full-segment track. Pinned to the live DGX bytes (/tmp/pr_dgx.jsx, sha ef43a785…).
"""
import base64
import gzip
import hashlib

DGX = "/tmp/pr_dgx.jsx"                                                  # live (PRE)
NEW = "/app/frontend/src/components/sentcom/v5/ProvenanceRing.jsx"       # edited (POST)
REL = "frontend/src/components/sentcom/v5/ProvenanceRing.jsx"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    pre_bytes = open(DGX, "rb").read()
    post_bytes = open(NEW, "rb").read()
    pre, post = sha(pre_bytes), sha(post_bytes)
    b64 = base64.b64encode(gzip.compress(post_bytes, 9)).decode()
    print("PRE :", pre)
    print("POST:", post)
    print("payload b64 chars:", len(b64))

    patcher = f'''#!/usr/bin/env python3
"""
patch_a2k_ring_pillar_colors.py  —  v19.34.284 (UI Track A · A2k-ring)
"5 distinct colors in the Provenance Ring"

Previously each ring arc was colored by its GRADE (A=green … F=red), so
same-grade pillars (Technical B vs Context C+, Setup D vs Execution F) read as
one color and the ring looked like ~3 colors instead of 5. This gives each TQS
pillar a FIXED identity hue — Setup=violet, Technical=cyan, Fundamental=amber,
Context=emerald, Execution=rose — and encodes the per-pillar GRADE as the bright
fill length over a faint full-segment track, so the ring shows 5 distinct colors
AND still reads weak (short arc) vs strong (full arc) at a glance. Center keeps
the numeric TQS + grade letter.

FRONTEND change — whole-file replace of {REL}. PRE+POST SHA256 hard-guarded;
aborts on drift; --check dry-run; .a2kbak backup. REQUIRES a frontend rebuild.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2k_ring_pillar_colors.py --check
  .venv/bin/python scripts/patch_a2k_ring_pillar_colors.py
  cd frontend && yarn build && cd ..
  git add frontend/ scripts/ && git commit -m "v19.34.284 (A2k): 5 distinct pillar colors in Provenance Ring" && git push origin main
Then hard-reload the UI. Rollback: restore {REL}.a2kbak (and rebuild).
"""
import base64
import gzip
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = {REL!r}
PRE = {pre!r}
POST = {post!r}
B64 = {b64!r}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {{PATH}} — run from the repo root."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    new_bytes = gzip.decompress(base64.b64decode(B64))
    assert sha(new_bytes) == POST, "embedded payload sha != POST (corrupt patcher)"

    if cur_sha == POST:
        print(f"  [ALREADY-APPLIED] {{PATH}} sha={{cur_sha[:12]}} — nothing to do.")
        return
    if cur_sha != PRE:
        print(f"  [DRIFT] {{PATH}}")
        print(f"    expected PRE  {{PRE}}")
        print(f"    found on disk {{cur_sha}}")
        print("    ABORT (no write). Send me your copy to rebase:")
        print(f"      curl -sS --data-binary @{{PATH}} https://paste.rs/")
        sys.exit(3)
    if CHECK:
        print(f"  [CHECK OK] {{PATH}} sha={{cur_sha[:12]}} -> POST {{POST[:12]}} (whole-file). Re-run without --check.")
        return
    bak = PATH + ".a2kbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(new_bytes)
    print(f"  [APPLIED] {{PATH}}  {{PRE[:12]}} -> {{POST[:12]}}  (.a2kbak saved)")
    print("  NEXT: cd frontend && yarn build && cd .. ; commit; hard-reload the UI.")


if __name__ == "__main__":
    main()
'''
    out_path = "/app/scripts/patch_a2k_ring_pillar_colors.py"
    open(out_path, "w", encoding="utf-8").write(patcher)
    print("wrote", out_path, len(patcher), "bytes")


if __name__ == "__main__":
    main()
