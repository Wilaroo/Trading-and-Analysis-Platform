#!/usr/bin/env python3
"""
extract_v347_anchor.py  (READ-ONLY) — emits the exact live anchor for patch_v348.

Prints, for the LIVE enhanced_scanner.py on the DGX:
  • whole-file SHA256        -> becomes DGX_WHOLE_PRE in patch_v348
  • _check_backside function : presence count, char length, SHA256, base64 of exact bytes
    (delimited from "    async def _check_backside" up to "    async def _check_off_sides")

NOTHING IS WRITTEN. Paste the entire output back to the agent.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/extract_v347_anchor.py
"""
import base64, hashlib, sys, os

FILE = "backend/services/enhanced_scanner.py"
START = "    async def _check_backside(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:"
END = "    async def _check_off_sides(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:"


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    if not os.path.exists(FILE):
        print(f"ERROR: {FILE} not found (run from repo root)"); sys.exit(2)
    src = open(FILE, encoding="utf-8").read()
    print(f"file               : {FILE}")
    print(f"whole-file SHA256  : {_sha(src)}")
    si = src.find(START)
    if si < 0:
        print("ERROR: _check_backside start anchor not found."); sys.exit(3)
    ei = src.find(END, si)
    if ei < 0:
        print("ERROR: _check_off_sides end anchor not found."); sys.exit(3)
    func = src[si:ei]
    print(f"backside present   : count={src.count(START)}")
    print(f"backside char len  : {len(func)}")
    print(f"backside func SHA  : {_sha(func)}")
    print("backside OLD_B64   : (single line below)")
    print(base64.b64encode(func.encode("utf-8")).decode("ascii"))


if __name__ == "__main__":
    main()
