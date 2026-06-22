#!/usr/bin/env python3
"""prepend_changelog_a2ij.py — idempotently PREPEND the v19.34.282 (A2i) +
v19.34.283 (A2j) entry to memory/CHANGELOG.md. Idempotent on the version anchor.

USAGE (repo root):
  .venv/bin/python scripts/prepend_changelog_a2ij.py
  git add memory/CHANGELOG.md scripts/ && git commit -m "v19.34.282-283 (A2i+A2j): changelog" && git push origin main
"""
import os
import sys

PATH = "memory/CHANGELOG.md"
ANCHOR = "v19.34.282-283 (A2i + A2j)"

BLOCK = """## 2026-06-22 — v19.34.282-283 (A2i + A2j) — Provenance Rings on EVAL & carry-forward cards
Follow-on to A2h. After A2h populated alert objects at the `_process_new_alert`
chokepoint, EVAL scanner cards were still ringless. Two more gaps, both fixed:

• A2i (services/sentcom_service.py, get_setups_watching Source 1): the
  GET /api/sentcom/setups 'live_scanner' dict DROPPED tqs_pillar_grades /
  tqs_grade / tqs_score, so the frontend read null and never rendered the ring on
  EVAL cards. Added all three (read from the alert via getattr, safe defaults).
  Verified by unit test backend/tests/test_a2i_setups_pillar_grades.py (PASS).
  patcher: paste.rs/UUiXm, PRE 0ef6e9f6 -> POST 76a1e569, commit 3a0dba80.

• A2j (services/enhanced_scanner.py, _hydrate_carry_forward_alerts_from_mongo):
  operator diagnostic (GET /api/live-scanner/alerts) showed 146/146 ringless
  cards were carry-forwards (cf_*) hydrated from Mongo at start(), which BYPASS
  _process_new_alert — so A2h never ran on them and they were persisted (pre-A2h)
  without a pillar breakdown. Now backfills the 5-pillar breakdown on hydration
  when missing and re-persists (self-healing; reports `A2j pillar-backfilled N`).
  patcher: paste.rs/rze8F, PRE 77956844 -> POST 8061578717d3, commit df585dcb.

VERIFICATION: calculate_tqs proven to ALWAYS emit a full 5-pillar pillar_grades
(neutral fallbacks; no IB/Finnhub/bars required) — so creation-path (A2h) and
hydration-path (A2j) backfill are reliable for any symbol/setup. Live carry-forward
gameplan cards went from 11/156 -> 10/11 carrying pillars; the lone miss (cf_SPLV)
was a transient per-alert enrich failure that self-heals on the next ranker run.

KNOWN-OPEN: transient per-alert enrich failures leave an occasional ringless card
until it rolls off. Optional follow-up A2k (periodic re-enrich sweep) would
guarantee 100%. Both A2i/A2j are backend-only, PRE/POST SHA-guarded, round-trip
verified.

"""


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {PATH} — run from the repo root."); sys.exit(2)
    cur = open(PATH, encoding="utf-8").read()
    if ANCHOR in cur:
        print(f"  [ALREADY-PRESENT] '{ANCHOR}' already in {PATH} — nothing to do.")
        return
    open(PATH, "w", encoding="utf-8").write(BLOCK + cur)
    print(f"  [PREPENDED] A2i+A2j block -> {PATH} (+{len(BLOCK)} chars)")
    print("  NEXT: git add memory/CHANGELOG.md scripts/ && git commit -m 'v19.34.282-283 (A2i+A2j): changelog' && git push origin main")


if __name__ == "__main__":
    main()
