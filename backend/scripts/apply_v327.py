#!/usr/bin/env python3
"""
apply_v327.py — show the SETUP on every open-position card
===========================================================
Operator: "I don't like that they just say intraday short or long —
what is the setup? what is the trade? I don't see that tagged."

The TradeStyleChip on the position card header already supports
rendering the humanised setup name — OpenPositionsV5 was explicitly
passing `showSetup={false}`. Flip it on so every card reads e.g.
"INTRADAY · Gap Fade short" instead of just "INTRADAY short".

SAFE TO RUN MULTIPLE TIMES (idempotent).
Run from repo root:  .venv/bin/python /tmp/apply_v327.py
Then: git add -A && git commit -m "v327: setup name on position cards" && git push
"""
from __future__ import annotations

import sys
from pathlib import Path

FE_REL = "frontend/src/components/sentcom/v5/OpenPositionsV5.jsx"

OLD = '''          <TradeStyleChip
            row={position}
            compact={true}
            showSetup={false}
            size="xs"
            testIdSuffix={`open-pos-${position.symbol}`}
          />
'''
NEW = '''          {/* v327 — operator wants the SETUP visible on the card face,
              not just "INTRADAY short". TradeStyleChip already knows how
              to render the humanised setup name. */}
          <TradeStyleChip
            row={position}
            compact={true}
            showSetup={true}
            size="xs"
            testIdSuffix={`open-pos-${position.symbol}`}
          />
'''


def main():
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / FE_REL).exists():
            root = cand
            break
    else:
        print("FATAL: run from repo root"); sys.exit(1)
    path = root / FE_REL
    text = path.read_text()
    if NEW in text:
        print("[SKIP] already applied")
        return
    if OLD not in text or text.count(OLD) != 1:
        print("[FAIL] anchor not found/unique — file drifted. ABORTING.")
        sys.exit(2)
    path.write_text(text.replace(OLD, NEW, 1))
    print("[OK] v327 applied — position cards now show the setup name.")
    print("Next: git add -A && git commit -m 'v327: setup name on position cards' && git push")
    print("(frontend hot-reloads; full restart not required for this one)")


if __name__ == "__main__":
    main()
