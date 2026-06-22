#!/usr/bin/env python3
"""
note_a8_changelog.py — prepend the (A8) CHANGELOG entry to memory/CHANGELOG.md
(newest-first). Idempotent. Run via python (NOT a terminal paste).

    PYTHONPATH=backend .venv/bin/python scripts/note_a8_changelog.py
    git add memory/CHANGELOG.md && git commit -m "A8: CHANGELOG note" && git push origin main
"""
import os
from pathlib import Path

ANCHOR = "(A8) — Auto-exec restart/feed guard"
ENTRY = """## 2026-06-22 — (A8) — Auto-exec restart/feed guard (kill backlog-flush-on-restart) — SHIPPED, LIVE
Operator-traced 2026-06-22 with diag_a9_entry_provenance: after the A7 scanner
resurrection, ~14 stage_2_breakout positions opened in a single 17:54-18:03Z
burst the instant the A6-enabled scanner relaunched, while the IB pusher was
still cold ("no push data yet"). Their alert DB records were timestamped
14:00-14:30Z (pre-A6, never executed then because the tape gate blocked
daily/swing auto-exec) — i.e. a FLUSH-ON-RESTART of a backlog, not 14
real-time decisions. IB truth-diff confirmed all are real positions with
correctly-placed stops; entries sat within ~1-2% of trigger, so limited price
damage, but they were not vetted against live data and over-concentrated one
setup type. NOTE: an alert-AGE gate was rejected — daily alert created_at can
be pinned via dedup/upsert, so age would miss the flush or over-block legit
re-detections. FIX (patch_a8, paste.rs/hsKB7): a RESTART/FEED GUARD at the top
of _auto_execute_alert (the single chokepoint for BOTH the intraday ~4212 and
A6 daily ~7421 callers): (1) WARM-UP — hold auto-exec for the first
AUTO_EXEC_WARMUP_SCANS loop cycles after (re)start (_scan_count resets to 0 on
start, ticks every cycle); (2) FEED HEALTH — require routers.ib.is_pusher_connected()
(AUTO_EXEC_REQUIRE_FEED=0 to disable). Both fail-open. Span-SHA guarded
(_auto_execute_alert eligibility span PRE 3b98662a). test_a8_restart_feed_guard.py
= 8/8 (warm-up holds, feed-down holds, warm+feed-up executes, knobs bypass).
Backup: enhanced_scanner.py.a8.bak. Open follow-ups: target_price + live-mark
plumbing for position holds (enables L7 thesis-invalidation exits), per-style
position cap, and card timestamp/price transparency (Time of Alert / Refreshed
/ Entry / Exit + Entry Price on scanner + open-position cards).

"""

for cand in ["memory/CHANGELOG.md", os.path.join(os.path.dirname(__file__), "..", "memory", "CHANGELOG.md")]:
    if os.path.isfile(cand):
        p = os.path.abspath(cand)
        c = open(p, encoding="utf-8").read()
        if ANCHOR in c:
            print(f"Idempotent: anchor present in {p} — no change.")
        else:
            open(p, "w", encoding="utf-8").write(ENTRY + c)
            print(f"Prepended (A8) entry to {p}.")
        break
else:
    print("ERROR: memory/CHANGELOG.md not found. Run from repo root.")
