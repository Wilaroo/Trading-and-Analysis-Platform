#!/usr/bin/env python3
"""Generates patch_v393_pattern_tape.py — single-file patcher for setup_quality.py.
Builds ON TOP of v391 (PRE-SHA = v391 POST). Pattern taxonomy fallback + Tape absent→neutral."""
import base64, gzip, hashlib

ROOT = "/app"
REL = "backend/services/tqs/setup_quality.py"
PRE = "c1ca91932e190b96ef5f0e9d8f8c2a8e"  # placeholder, replaced below from arg
# v391 POST-SHA for setup_quality.py (full)
PRE_FULL = "c1ca91932e190b96"  # short; full computed from a known-good? we set actual full below

content = open(f"{ROOT}/{REL}", "rb").read()
post = hashlib.sha256(content).hexdigest()
b64 = base64.b64encode(gzip.compress(content, 9)).decode()

# The real PRE-SHA (full) of the v391 setup_quality.py = the file BEFORE this v393 edit.
# Supplied by caller via env to avoid drift.
import os
pre_full = os.environ.get("V391_SETUP_SHA")
assert pre_full, "set V391_SETUP_SHA env to the full v391 POST sha of setup_quality.py"

header = '''#!/usr/bin/env python3
"""
patch_v393_pattern_tape.py  —  Setup pillar: Pattern taxonomy fallback + Tape absent->neutral

APPLIES ON TOP OF v391 (PRE-SHA below = the v391 setup_quality.py).

  • PATTERN — when a setup_type's canonical base is missing from
    SETUP_BASE_SCORES it no longer pins to a flat 50. It derives a
    tier-appropriate base from the shared setup taxonomy:
      breakout 68 / continuation 66 / reversion 62 / reversal 58 /
      rotation 60 / swing 64 / position 62 / unknown 55.
    Explicit SETUP_BASE_SCORES stays the override for tier-1/2 names
    (orb 80, bull_flag 78, ...). Diag v392: fixes 62.5%% of the book (44 setups).
  • TAPE — tape_score==0 means NO tape/L2 reading was available (68%% of the
    book), not a weak read. Absent tape now scores neutral 50 instead of the
    punitive 30. Measured-weak (0<score<4) keeps its penalty.

USAGE (repo root):
  .venv/bin/python backend/scripts/patch_v393_pattern_tape.py --check
  .venv/bin/python backend/scripts/patch_v393_pattern_tape.py
  ./start_backend.sh --force
"""
import base64, gzip, hashlib, os, sys

CHECK = "--check" in sys.argv
PATH = ''' + repr(REL) + '''
PRE = ''' + repr(pre_full) + '''
POST = ''' + repr(post) + '''
B64 = ''' + repr(b64) + '''


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"[MISSING!] {PATH}"); sys.exit(1)
    cur = sha(open(PATH, "rb").read())
    if cur == POST:
        print(f"[ALREADY v393] {PATH}")
        if CHECK: sys.exit(0)
        return
    if cur != PRE:
        print(f"[DRIFT!] {PATH}\\n  on-disk {cur}\\n  expected PRE (v391) {PRE}\\n  --> apply v391 first, or investigate drift.")
        sys.exit(1)
    print(f"[OK] {PATH}  PRE {PRE[:16]} -> POST {POST[:16]}")
    if CHECK:
        print("--check OK. Re-run without --check."); sys.exit(0)
    open(PATH + ".bak.v393", "wb").write(open(PATH, "rb").read())
    open(PATH, "wb").write(gzip.decompress(base64.b64decode(B64)))
    print(f"WROTE {PATH}  POST {sha(open(PATH,'rb').read())[:16]} (backup .bak.v393). Restart backend.")


if __name__ == "__main__":
    main()
'''

out = f"{ROOT}/patch_v393_pattern_tape.py"
open(out, "w").write(header)
print("wrote", out, "| PRE(v391)=", pre_full[:16], "POST(v393)=", post[:16])
