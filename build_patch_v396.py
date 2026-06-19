#!/usr/bin/env python3
"""Generates patch_v396_financial_ratio_codes.py — 2-file patcher.
Fixes the v389 Financial sub-score (was 100% blind) by correcting the IB ReportSnapshot
ratio codes + deriving net margin + reading forward growth from <ForecastData>."""
import base64, gzip, hashlib

ROOT = "/app"
TARGETS = [
    ("backend/services/ib_fundamentals_parser.py",
     "dc4082c9dc119279c75c2a27dc2fafc7eee537b54cb257124efc77b35461b65d"),  # git HEAD (untouched)
    ("backend/services/tqs/fundamental_quality.py",
     "31b5f7c635ba6208b029f8ad0754f6a86028846a1a86874fded1bc998bb62c8f"),  # v391 POST
]

files = []
for rel, pre in TARGETS:
    content = open(f"{ROOT}/{rel}", "rb").read()
    files.append({"path": rel, "pre": pre,
                  "post": hashlib.sha256(content).hexdigest(),
                  "b64": base64.b64encode(gzip.compress(content, 9)).decode()})

header = '''#!/usr/bin/env python3
"""
patch_v396_financial_ratio_codes.py  —  un-blind the v389 Financial sub-score

ROOT CAUSE (diag v395/b/c): the Fundamental pillar's Financial sub-score (20%% of
the pillar) was 100%% blind (0/1383 cached symbols had roe/margin/growth/debt) —
NOT a coverage gap, a parser FIELD-CODE MISMATCH. IB ReportSnapshot uses
TTMROEPCT (not ROEPCT), has no net-margin ratio, and puts forward growth in
<ForecastData>. debt-to-equity is absent from ReportSnapshot entirely.

FIX (parser + sub-score mapping):
  • roe_pct      ← TTMROEPCT   (the real IB code)
  • net_margin_pct ← DERIVED   TTMNIAC / TTMREV * 100  (robust across sectors;
                               gross TTMGROSMGN is a -99999 sentinel for banks)
  • growth       ← <ForecastData> ProjLTGrowthRate  (forward LT growth estimate)
  • debt_to_equity → absent → dropped; sub-score averages only available metrics.
  • -99999.99 sentinel rejected everywhere.

Verified: AAPL financial 50→84, JPM 50→75 (3/4 metrics). Applies on top of v391
(fundamental_quality PRE = v391 POST).

USAGE (repo root):
  .venv/bin/python backend/scripts/patch_v396_financial_ratio_codes.py --check
  .venv/bin/python backend/scripts/patch_v396_financial_ratio_codes.py
  ./start_backend.sh --force
  # then backfill the cache (off-hours): POST /api/short-data/warm-fundamentals
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
            print(f"  [ALREADY v396] {f['path']}")
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
        bak = f["path"] + ".bak.v396"
        if not os.path.exists(bak):
            open(bak, "wb").write(open(f["path"], "rb").read())
        open(f["path"], "wb").write(gzip.decompress(base64.b64decode(f["b64"])))
        print(f"  WROTE {f['path']}  POST {sha(open(f['path'],'rb').read())[:16]} (backup .bak.v396)")
    print("\\nDONE. Restart backend, then re-warm fundamentals to backfill the cache.")


if __name__ == "__main__":
    main()
'''

out = f"{ROOT}/patch_v396_financial_ratio_codes.py"
open(out, "w").write(header)
print("wrote", out)
for f in files:
    print(f"  {f['path']}  PRE={f['pre'][:16]} POST={f['post'][:16]}")
