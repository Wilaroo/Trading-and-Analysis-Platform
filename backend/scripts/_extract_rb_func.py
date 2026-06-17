#!/usr/bin/env python3
"""
_extract_rb_func.py — DGX-safe extractor (READ-ONLY).

Pulls the EXACT current text of `_check_rubber_band` from the live
backend/services/enhanced_scanner.py, writes it to /tmp/rb_func.txt, prints its
sha256 + line span, and uploads it to paste.rs so the patch author can anchor a
§2.2 patcher on the operator's real bytes (sandbox enhanced_scanner.py has drifted).

Usage (repo root, DGX):
  curl -sS -o /tmp/_extract_rb_func.py https://paste.rs/<id>
  python3 /tmp/_extract_rb_func.py
Then paste back: the printed sha + the returned paste.rs URL.
"""
import hashlib
import re
import subprocess
import sys

FILE = "backend/services/enhanced_scanner.py"
MARKER = "async def _check_rubber_band"


def main():
    try:
        lines = open(FILE, encoding="utf-8").read().split("\n")
    except FileNotFoundError:
        print(f"ERROR: {FILE} not found — run from repo root."); sys.exit(2)

    start = None
    for i, l in enumerate(lines):
        if l.lstrip().startswith(MARKER):
            start = i
            break
    if start is None:
        print("ERROR: _check_rubber_band not found."); sys.exit(3)

    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent and \
                re.match(r"\s*(async\s+)?def ", l):
            end = j
            break

    block = "\n".join(lines[start:end])
    # keep a trailing newline if the next line was blank-separated (typical)
    with open("/tmp/rb_func.txt", "w", encoding="utf-8") as f:
        f.write(block)

    sha = hashlib.sha256(block.encode("utf-8")).hexdigest()
    print(f"file        : {FILE}")
    print(f"whole-file SHA: {hashlib.sha256(open(FILE, 'rb').read()).hexdigest()}")
    print(f"function span : lines {start + 1}..{end}  ({end - start} lines)")
    print(f"function SHA  : {sha}")
    print("wrote        : /tmp/rb_func.txt")
    try:
        url = subprocess.check_output(
            ["curl", "-sS", "--data-binary", "@/tmp/rb_func.txt", "https://paste.rs/"],
            text=True).strip()
        print(f"PASTE URL    : {url}")
        print("\n→ Paste back the 'function SHA' + 'PASTE URL' above.")
    except Exception as e:
        print(f"(paste.rs upload failed: {e} — upload /tmp/rb_func.txt manually)")


if __name__ == "__main__":
    main()
