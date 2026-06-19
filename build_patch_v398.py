#!/usr/bin/env python3
"""Generates patch_v398_technical_stale_price.py — 2-file patcher.
Un-blinds the Technical pillar for the ~45% of alerts with no live quote at score time."""
import base64, gzip, hashlib

ROOT = "/app"
TARGETS = [
    ("backend/services/realtime_technical_service.py",
     "570c09190c3b0b78335a4e7a11f34b88f4918d942444bdcf915cf035948b4d34"),  # git HEAD
    ("backend/services/tqs/technical_quality.py",
     "1de445fcda7f1b1fc0ab98d8d25afee3bc6386b0dd423dd9a8c1c6d0f4b3382f"),  # v391 POST
]
files = []
for rel, pre in TARGETS:
    content = open(f"{ROOT}/{rel}", "rb").read()
    files.append({"path": rel, "pre": pre,
                  "post": hashlib.sha256(content).hexdigest(),
                  "b64": base64.b64encode(gzip.compress(content, 9)).decode()})

header = '''#!/usr/bin/env python3
"""
patch_v398_technical_stale_price.py  —  un-blind the Technical pillar (no-live-quote gap)

ROOT CAUSE (diag v397): get_technical_snapshot() returns None whenever there is no
live IB pusher quote at score time (a deliberate "no live data = no scan" guard).
When None, the WHOLE 25%%-weight Technical pillar defaults — RSI 50, RVOL 1.0,
levels 50, neutral trend — for ~45%% of alerts.

FIX (opt-in, scoring path only):
  • New get_technical_snapshot(..., allow_stale_price=False) kwarg.
  • When True and there's no live pusher quote, compute the snapshot from the
    latest STORED Mongo bar (intraday last close, else daily) instead of None.
  • The TQS Technical pillar passes allow_stale_price=True. The scanner /
    auto-exec paths do NOT pass it and keep their fail-closed behaviour — so
    live-trade triggering is UNCHANGED. Only quality SCORING gets the fallback.

(The 20-day S/R algorithm was checked and left as-is: within real snapshots the
levels score is well-distributed, so no S/R rework needed.)

Applies on top of v391 (technical_quality PRE = v391 POST).

USAGE (repo root):
  .venv/bin/python backend/scripts/patch_v398_technical_stale_price.py --check
  .venv/bin/python backend/scripts/patch_v398_technical_stale_price.py
  ./start_backend.sh --force
"""
import base64, gzip, hashlib, os, sys

CHECK = "--check" in sys.argv
FILES = ''' + repr(files) + '''


def sha(b): return hashlib.sha256(b).hexdigest()


def main():
    drift = False
    for f in FILES:
        if not os.path.exists(f["path"]):
            print(f"  [MISSING!] {f['path']}"); drift = True; continue
        cur = sha(open(f["path"], "rb").read())
        if cur == f["post"]:
            print(f"  [ALREADY v398] {f['path']}")
        elif cur != f["pre"]:
            print(f"  [DRIFT!] {f['path']}\\n     on-disk {cur}\\n     expected PRE {f['pre']}")
            drift = True
        else:
            print(f"  [OK] {f['path']}  PRE {f['pre'][:16]} -> POST {f['post'][:16]}")
    if CHECK:
        print("\\n--check: " + ("DRIFT — do NOT apply." if drift else "all anchors OK, re-run without --check."))
        sys.exit(1 if drift else 0)
    if drift:
        print("\\nABORT — drift."); sys.exit(1)
    for f in FILES:
        bak = f["path"] + ".bak.v398"
        if not os.path.exists(bak):
            open(bak, "wb").write(open(f["path"], "rb").read())
        open(f["path"], "wb").write(gzip.decompress(base64.b64decode(f["b64"])))
        print(f"  WROTE {f['path']}  POST {sha(open(f['path'],'rb').read())[:16]} (backup .bak.v398)")
    print("\\nDONE. Restart backend (./start_backend.sh --force).")


if __name__ == "__main__":
    main()
'''

out = f"{ROOT}/patch_v398_technical_stale_price.py"
open(out, "w").write(header)
print("wrote", out)
for f in files:
    print(f"  {f['path']}  PRE={f['pre'][:16]} POST={f['post'][:16]}")
