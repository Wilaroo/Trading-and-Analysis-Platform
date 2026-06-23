#!/usr/bin/env python3
"""
note_a7_changelog.py — prepend the (A7) CHANGELOG entry to memory/CHANGELOG.md
on the DGX (newest-first, per AGENTS §4 / §0.5 rule 5).

Track tag is A7 (NOT v19.34.311 — that number is already used by the
2026-06-10 Confidence-Gate audit; A3/A4/A6/A7 is the current track convention).

Idempotent: re-running after a successful prepend is a no-op.
Uses no shell interpolation (run via python, NOT a terminal paste) so the
parentheses / quotes in the entry can't corrupt the DGX bash session.

Run from the repo root:
    PYTHONPATH=backend .venv/bin/python scripts/note_a7_changelog.py
Then:
    git add memory/CHANGELOG.md
    git commit -m "A7: CHANGELOG note"
    git push origin main
"""
import os
import sys

ANCHOR = "(A7) — Scan-loop liveness"
ENTRY = """## 2026-06-22 — (A7) — Scan-loop liveness P0 + DMA directional-filter softening — SHIPPED, COMMITTED (63c92a1e), LIVE
NOTE: track tag is A7 (NOT a v19.34.NNN — 311/312 are already used by the
2026-06-10 Confidence-Gate/Model-family audit; the commit message's
"v19.34.311" label is a known collision, code comments use "A7").
RCA of the dead intraday scanner. /api/scanner/status reads the IDLE
predictive_scanner (red herring); the REAL enhanced scanner state is
/api/live-scanner/status — it showed running=False, scan_count=0,
last_scan=None with 19 stale hydrated alerts during afternoon RTH, IB
connected. ROOT CAUSE: EnhancedBackgroundScanner.start() awaited the blocking
pymongo carry-forward hydrate BEFORE setting _running / spawning _scan_task;
at server boot start() is wrapped in asyncio.wait_for(..., timeout=5.0)
(server.py:4362), so a slow hydrate (Atlas latency / cold cache) cancelled
start() mid-hydrate -> the loop task was never created and the scanner stayed
permanently dead while still showing the alerts the hydrate had already loaded
(explains active_alerts=19 + scan_count=0). FIX (EDIT-1): flip _running=True
and spawn _scan_task FIRST; the hydrate now runs after the loop is live, so its
fate can never strand the scanner.
EDIT-2 (DMA softening, operator-requested): the directional filter previously
HARD-rejected any swing/multi_day/position LONG whose last price was even $0.01
below EMA50 (and position longs below SMA200), killing textbook buy-the-dip /
basing entries in healthy uptrends. Softened on three axes: (1) proximity
buffer DMA_LONG_BUFFER_PCT (default 2%) — only reject when price is MORE than
the buffer below the MA; (2) structure-aware — never reject a long while
EMA50>SMA200 (a pullback within an uptrend), mirror for shorts; (3)
pullback-setup exemption (accumulation_entry, three_week_tight, vwap_bounce,
second_chance, rubber_band, backside, mean_reversion, first_vwap_pullback,
pullback).
Delivered via patch_a7 (paste.rs/wQ5jm), span-SHA-guarded (start span PRE
6869042d, DMA span PRE 6df9cbf3) — matched the DGX bytes exactly, zero drift.
test_a7_scanloop_dma.py = 14/14 (start() loop survives slow-hydrate +
wait_for-cancel; DMA truth-table). VERIFIED LIVE: manual POST
/api/live-scanner/start -> running=True, scan_count 0->2 in 60s; then a clean
./start_backend.sh --force boot AUTO-started the scanner (running=True,
scan_count climbing, 433 symbols) with no manual /start — durable fix proven.
Backup: enhanced_scanner.py.a7.bak. Follow-up offered: scan-loop watchdog
(A8) to auto-restart if _running flips False during RTH.

"""

CANDIDATES = [
    "memory/CHANGELOG.md",
    os.path.join(os.path.dirname(__file__), "..", "memory", "CHANGELOG.md"),
]


def main():
    path = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if not path:
        print("ERROR: memory/CHANGELOG.md not found. Run from the repo root.")
        sys.exit(2)
    path = os.path.abspath(path)
    content = open(path, encoding="utf-8").read()
    if ANCHOR in content:
        print(f"Idempotent: '{ANCHOR}' already present in {path} — no change.")
        sys.exit(0)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ENTRY + content)
    print(f"Prepended (A7) entry to {path} ({len(ENTRY)} chars).")
    print("Next: git add memory/CHANGELOG.md && "
          "git commit -m 'A7: CHANGELOG note (scan-loop liveness + DMA softening)' && git push origin main")


if __name__ == "__main__":
    main()
