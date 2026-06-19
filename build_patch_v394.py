#!/usr/bin/env python3
"""Generates patch_v394_sector_ibbars.py — single-file patcher for context_quality.py.
Builds ON TOP of v391 (PRE-SHA = v391 context_quality POST). IB-bar sector fallback."""
import base64, gzip, hashlib, os

ROOT = "/app"
REL = "backend/services/tqs/context_quality.py"
PRE = os.environ["V391_CTX_SHA"]
content = open(f"{ROOT}/{REL}", "rb").read()
post = hashlib.sha256(content).hexdigest()
b64 = base64.b64encode(gzip.compress(content, 9)).decode()

header = '''#!/usr/bin/env python3
"""
patch_v394_sector_ibbars.py  —  Context pillar: IB-bar sector fallback (Sector was 100% blind)

APPLIES ON TOP OF v391 (PRE-SHA below = the v391 context_quality.py).

  Root cause (diag v392b): on the ib-direct DGX alpaca is dead, so
  sector_analysis_service.get_sector_rankings() returned no quotes →
  get_stock_sector_context() returned None → Sector was 'unknown' (flat 55)
  for 100%% of the book. Plus STOCK_SECTORS only mapped 34 symbols.

  FIX (v254-style, no alpaca): rank the 11 sector ETFs by 1-day %% from
  ib_historical_data daily bars, and map symbol→sector ETF via
  symbol_adv_cache.sector (which already stores the ETF ticker). stock-vs-sector
  leader test uses the symbol's own daily 1d %% vs its ETF. Symbols without a
  sector tag stay honest 'No data' (v391 descriptor). 0%% → ~61%% real on the
  live book, climbing as sector_tag_service tags more of the universe.

USAGE (repo root):
  .venv/bin/python backend/scripts/patch_v394_sector_ibbars.py --check
  .venv/bin/python backend/scripts/patch_v394_sector_ibbars.py
  ./start_backend.sh --force
"""
import base64, gzip, hashlib, os, sys

CHECK = "--check" in sys.argv
PATH = ''' + repr(REL) + '''
PRE = ''' + repr(PRE) + '''
POST = ''' + repr(post) + '''
B64 = ''' + repr(b64) + '''


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"[MISSING!] {PATH}"); sys.exit(1)
    cur = sha(open(PATH, "rb").read())
    if cur == POST:
        print(f"[ALREADY v394] {PATH}")
        if CHECK: sys.exit(0)
        return
    if cur != PRE:
        print(f"[DRIFT!] {PATH}\\n  on-disk {cur}\\n  expected PRE (v391) {PRE}\\n  --> apply v391 first, or investigate drift.")
        sys.exit(1)
    print(f"[OK] {PATH}  PRE {PRE[:16]} -> POST {POST[:16]}")
    if CHECK:
        print("--check OK. Re-run without --check."); sys.exit(0)
    open(PATH + ".bak.v394", "wb").write(open(PATH, "rb").read())
    open(PATH, "wb").write(gzip.decompress(base64.b64decode(B64)))
    print(f"WROTE {PATH}  POST {sha(open(PATH,'rb').read())[:16]} (backup .bak.v394). Restart backend.")


if __name__ == "__main__":
    main()
'''

out = f"{ROOT}/patch_v394_sector_ibbars.py"
open(out, "w").write(header)
print("wrote", out, "| PRE(v391)=", PRE[:16], "POST(v394)=", post[:16])
