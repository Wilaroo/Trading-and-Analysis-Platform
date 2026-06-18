#!/usr/bin/env python3
"""
extract_func_generic.py  (READ-ONLY, generic file+method anchor extractor for patchers).

Same slicing contract as extract_func.py, but works on ANY backend file and matches both
`    def <name>` and `    async def <name>` at 4-space (class-method) indent. Prints the
whole-file SHA256, the EXACT current bytes of the method (def line .. up to & including the
text just before the next 4-space-indented sibling), its SHA256, and base64. NOTHING WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/extract_func_generic.py services/ai_modules/confidence_gate.py _get_live_prediction
Paste the WHOLE output back so the patcher can be hash-pinned.
"""
import base64, hashlib, sys, re


def main():
    if len(sys.argv) < 3:
        print("usage: extract_func_generic.py <file_path> <method_name>"); return
    path = sys.argv[1]
    name = sys.argv[2]
    import os
    if not os.path.exists(path) and os.path.exists("backend/" + path):
        path = "backend/" + path
    src = open(path, encoding="utf-8").read()
    print(f"file           : {path}")
    print(f"whole-file SHA : {hashlib.sha256(src.encode('utf-8')).hexdigest()}")

    marker = None
    for cand in (f"    async def {name}(", f"    def {name}(",
                 f"    async def {name} ", f"    def {name} "):
        if cand in src:
            marker = cand; break
    if marker is None:
        # fall back to bare prefix (no paren) for defs split across lines
        for cand in (f"    async def {name}", f"    def {name}"):
            if cand in src:
                marker = cand; break
    if marker is None:
        print(f"ERROR: {name} not found in {path}"); return

    start = src.index(marker)
    m = re.search(r"\n    \S", src[start + len(marker):])
    if not m:
        print("ERROR: could not find next 4-space sibling boundary"); return
    nxt = (start + len(marker)) + m.start()
    anchor = src[start:nxt + 1]
    print(f"method         : {name}")
    print(f"matched marker : {marker!r}")
    print(f"anchor count   : {src.count(anchor)}  (MUST be 1)")
    print(f"anchor lines   : {anchor.count(chr(10))}")
    print(f"PRE_FUNC_SHA   : {hashlib.sha256(anchor.encode('utf-8')).hexdigest()}")
    print(f"anchor head    : {anchor[:60]!r}")
    print(f"anchor tail    : {anchor[-40:]!r}")
    print("\n--- OLD_B64 (copy verbatim) ---")
    print(base64.b64encode(anchor.encode("utf-8")).decode("ascii"))
    print("--- end OLD_B64 ---")


if __name__ == "__main__":
    main()
