#!/usr/bin/env python3
"""extract_region_generic.py (READ-ONLY) — exact-bytes anchor extractor for a
REGION delimited by a unique substring (for patcher hash-pinning where the
target is NOT a class method, e.g. a dataclass field block or a constructor
call site that extract_func_generic.py can't slice).

Prints the whole-file SHA256, then the EXACT bytes of the window
[N lines before .. anchor line .. N lines after], its SHA256, and base64 so a
compact anchored-chunk patcher can pin PRE/POST hashes.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/extract_region_generic.py <file> "<unique_substr>" [before] [after]
e.g.
  .venv/bin/python backend/scripts/extract_region_generic.py \
      services/trading_bot_service.py 'smb_grade: str = "B"' 1 1
  .venv/bin/python backend/scripts/extract_region_generic.py \
      services/opportunity_evaluator.py 'trade_style=alert.get("trade_style"' 12 2
Paste the WHOLE output back.
"""
import base64
import hashlib
import os
import sys


def main():
    if len(sys.argv) < 3:
        print("usage: extract_region_generic.py <file> <unique_substr> [before] [after]")
        return
    path = sys.argv[1]
    needle = sys.argv[2]
    before = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    after = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    if not os.path.exists(path) and os.path.exists("backend/" + path):
        path = "backend/" + path
    src = open(path, encoding="utf-8").read()
    print(f"file           : {path}")
    print(f"whole-file SHA : {hashlib.sha256(src.encode('utf-8')).hexdigest()}")
    occ = src.count(needle)
    print(f"needle         : {needle!r}")
    print(f"needle count   : {occ}  (MUST be 1 to anchor safely)")
    if occ == 0:
        print("ERROR: needle not found"); return

    lines = src.splitlines(keepends=True)
    # find the line index containing the needle
    idx = None
    for i, ln in enumerate(lines):
        if needle in ln:
            idx = i
            break
    lo = max(0, idx - before)
    hi = min(len(lines), idx + after + 1)
    region = "".join(lines[lo:hi])
    print(f"anchor line #  : {idx + 1}  (window lines {lo + 1}..{hi})")
    print(f"region count   : {src.count(region)}  (MUST be 1)")
    print(f"region lines   : {region.count(chr(10))}")
    print(f"REGION_SHA     : {hashlib.sha256(region.encode('utf-8')).hexdigest()}")
    print(f"region head    : {region[:60]!r}")
    print(f"region tail    : {region[-50:]!r}")
    print("\n--- OLD_B64 (copy verbatim) ---")
    print(base64.b64encode(region.encode("utf-8")).decode("ascii"))
    print("--- end OLD_B64 ---")


if __name__ == "__main__":
    main()
