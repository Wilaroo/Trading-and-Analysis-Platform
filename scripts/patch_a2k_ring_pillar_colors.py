#!/usr/bin/env python3
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

FRONTEND change — whole-file replace of frontend/src/components/sentcom/v5/ProvenanceRing.jsx. PRE+POST SHA256 hard-guarded;
aborts on drift; --check dry-run; .a2kbak backup. REQUIRES a frontend rebuild.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2k_ring_pillar_colors.py --check
  .venv/bin/python scripts/patch_a2k_ring_pillar_colors.py
  cd frontend && yarn build && cd ..
  git add frontend/ scripts/ && git commit -m "v19.34.284 (A2k): 5 distinct pillar colors in Provenance Ring" && git push origin main
Then hard-reload the UI. Rollback: restore frontend/src/components/sentcom/v5/ProvenanceRing.jsx.a2kbak (and rebuild).
"""
import base64
import gzip
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = 'frontend/src/components/sentcom/v5/ProvenanceRing.jsx'
PRE = 'ef43a78596fedb70775ab71de65632fd8d36354cc7a280e600d73830e06dfb45'
POST = '17b24742c9d187c886276279ac9207eaaf88630e17d3275747b0cf30e84da28b'
B64 = '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'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {PATH} — run from the repo root."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    new_bytes = gzip.decompress(base64.b64decode(B64))
    assert sha(new_bytes) == POST, "embedded payload sha != POST (corrupt patcher)"

    if cur_sha == POST:
        print(f"  [ALREADY-APPLIED] {PATH} sha={cur_sha[:12]} — nothing to do.")
        return
    if cur_sha != PRE:
        print(f"  [DRIFT] {PATH}")
        print(f"    expected PRE  {PRE}")
        print(f"    found on disk {cur_sha}")
        print("    ABORT (no write). Send me your copy to rebase:")
        print(f"      curl -sS --data-binary @{PATH} https://paste.rs/")
        sys.exit(3)
    if CHECK:
        print(f"  [CHECK OK] {PATH} sha={cur_sha[:12]} -> POST {POST[:12]} (whole-file). Re-run without --check.")
        return
    bak = PATH + ".a2kbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(new_bytes)
    print(f"  [APPLIED] {PATH}  {PRE[:12]} -> {POST[:12]}  (.a2kbak saved)")
    print("  NEXT: cd frontend && yarn build && cd .. ; commit; hard-reload the UI.")


if __name__ == "__main__":
    main()
