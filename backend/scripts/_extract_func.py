#!/usr/bin/env python3
"""
_extract_func.py — DGX-safe GENERIC function extractor (READ-ONLY).

Pulls the EXACT current text of a named method from the live
backend/services/enhanced_scanner.py, writes it to /tmp/func.txt, prints its
sha256 + line span + whole-file sha, and uploads it to paste.rs so a §2.2
patcher can anchor on the operator's real bytes (the sandbox file has drifted
and is >paste.rs whole-file limit). Reusable across the FADE/MOMENTUM sweep.

Usage (repo root, DGX):
  curl -sS -o /tmp/_extract_func.py https://paste.rs/<id>
  python3 /tmp/_extract_func.py _check_vwap_fade
Then paste back: the printed 'function SHA', 'whole-file SHA', and the PASTE URL.
"""
import hashlib
import re
import subprocess
import sys

FILE = "backend/services/enhanced_scanner.py"


def main():
    if len(sys.argv) < 2:
        print("usage: python3 _extract_func.py <method_name>   e.g. _check_vwap_fade")
        sys.exit(1)
    name = sys.argv[1]
    marker = f"async def {name}"
    alt_marker = f"def {name}"

    try:
        lines = open(FILE, encoding="utf-8").read().split("\n")
    except FileNotFoundError:
        print(f"ERROR: {FILE} not found — run from repo root.")
        sys.exit(2)

    start = None
    for i, l in enumerate(lines):
        s = l.lstrip()
        if s.startswith(marker) or s.startswith(alt_marker):
            start = i
            break
    if start is None:
        print(f"ERROR: {name} not found.")
        sys.exit(3)

    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent and \
                re.match(r"\s*(async\s+)?def ", l):
            end = j
            break

    block = "\n".join(lines[start:end])
    with open("/tmp/func.txt", "w", encoding="utf-8") as f:
        f.write(block)

    sha = hashlib.sha256(block.encode("utf-8")).hexdigest()
    print(f"method       : {name}")
    print(f"file         : {FILE}")
    print(f"whole-file SHA: {hashlib.sha256(open(FILE, 'rb').read()).hexdigest()}")
    print(f"function span : lines {start + 1}..{end}  ({end - start} lines)")
    print(f"function SHA  : {sha}")
    print("wrote        : /tmp/func.txt")
    try:
        url = subprocess.check_output(
            ["curl", "-sS", "--data-binary", "@/tmp/func.txt", "https://paste.rs/"],
            text=True).strip()
        print(f"PASTE URL    : {url}")
        print("\n→ Paste back the 'function SHA' + 'whole-file SHA' + 'PASTE URL' above.")
    except Exception as e:
        print(f"(paste.rs upload failed: {e} — upload /tmp/func.txt manually)")


if __name__ == "__main__":
    main()
