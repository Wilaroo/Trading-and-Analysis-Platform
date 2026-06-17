#!/usr/bin/env python3
"""
extract_v353_second_chance.py  (READ-ONLY anchor extractor for the v353 patcher).

Prints the live enhanced_scanner whole-file SHA256, and the EXACT current
`_check_second_chance` function bytes (anchor) + its SHA256 + base64, using the
SAME slicing the anchored-chunk patcher uses (def line .. up to & including the
blank line that precedes the next `    async def `). NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/extract_v353_second_chance.py
Paste the WHOLE output back so the v353 patcher can be hash-pinned.
"""
import base64, hashlib

FILE = "backend/services/enhanced_scanner.py"
MARKER = "    async def _check_second_chance"


def main():
    src = open(FILE, encoding="utf-8").read()
    whole = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file           : {FILE}")
    print(f"whole-file SHA : {whole}")

    if MARKER not in src:
        print("ERROR: _check_second_chance not found"); return
    start = src.index(MARKER)
    # next sibling method at 4-space indent; the matched '\n' ends the blank line
    # ('    \n') that precedes it, so anchor ends '...return None\n    \n' (matches
    # the v352 OLD_B64 tail convention).
    nxt = src.index("\n    async def ", start + len(MARKER))
    end = nxt + 1
    anchor = src[start:end]

    print(f"anchor count   : {src.count(anchor)}  (MUST be 1)")
    print(f"anchor lines   : {anchor.count(chr(10))}")
    print(f"PRE_FUNC_SHA   : {hashlib.sha256(anchor.encode('utf-8')).hexdigest()}")
    print(f"anchor tail    : {anchor[-40:]!r}")
    print("\n--- OLD_B64 (copy verbatim) ---")
    print(base64.b64encode(anchor.encode("utf-8")).decode("ascii"))
    print("--- end OLD_B64 ---")


if __name__ == "__main__":
    main()
