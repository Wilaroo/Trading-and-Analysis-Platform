#!/usr/bin/env python3
"""
extract_func.py  (READ-ONLY, generic function-anchor extractor for patchers).

Prints the live enhanced_scanner whole-file SHA256 and the EXACT current bytes of a
given `    async def <name>` method (anchor) + its SHA256 + base64, using the SAME
slicing the anchored-chunk patchers use (def line .. up to & including the blank line
that precedes the next `    async def `). NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/extract_func.py _check_vwap_bounce
Paste the WHOLE output back so the patcher can be hash-pinned.
"""
import base64, hashlib, sys, re

FILE = "backend/services/enhanced_scanner.py"


def main():
    if len(sys.argv) < 2:
        print("usage: extract_func.py <method_name>"); return
    name = sys.argv[1]
    marker = f"    async def {name}"
    src = open(FILE, encoding="utf-8").read()
    print(f"file           : {FILE}")
    print(f"whole-file SHA : {hashlib.sha256(src.encode('utf-8')).hexdigest()}")
    if marker not in src:
        print(f"ERROR: {name} not found"); return
    start = src.index(marker)
    # End at the FIRST next sibling at 4-space indent (def / async def / comment /
    # decorator), i.e. the first '\n    <non-space>' after the def line. This keeps
    # trailing blank line(s) (anchor tail '...\n    \n') and does NOT swallow a
    # following sync helper like _atr_floored_stop.
    m = re.search(r"\n    \S", src[start + len(marker):])
    nxt = (start + len(marker)) + m.start()
    anchor = src[start:nxt + 1]
    print(f"method         : {name}")
    print(f"anchor count   : {src.count(anchor)}  (MUST be 1)")
    print(f"anchor lines   : {anchor.count(chr(10))}")
    print(f"PRE_FUNC_SHA   : {hashlib.sha256(anchor.encode('utf-8')).hexdigest()}")
    print(f"anchor tail    : {anchor[-40:]!r}")
    print("\n--- OLD_B64 (copy verbatim) ---")
    print(base64.b64encode(anchor.encode("utf-8")).decode("ascii"))
    print("--- end OLD_B64 ---")


if __name__ == "__main__":
    main()
