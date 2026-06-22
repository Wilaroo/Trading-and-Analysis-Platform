#!/usr/bin/env python3
"""
prepend_changelog_a2h.py — idempotently PREPEND the v19.34.281 (A2h) entry to
memory/CHANGELOG.md (per AGENTS.md §0.5 item 5: prepend, never blind-overwrite;
idempotent on the version anchor).

USAGE (repo root):
  .venv/bin/python scripts/prepend_changelog_a2h.py          # prepend if absent
  git add memory/CHANGELOG.md && git commit -m "v19.34.281 (A2h): changelog" && git push origin main
"""
import os
import sys

PATH = "memory/CHANGELOG.md"
ANCHOR = "v19.34.281 (A2h)"

BLOCK = """## 2026-06-22 — v19.34.281 (A2h) — Provenance Rings on EVERY live scanner alert
The A2 Provenance Ring renders only when a scanner card carries `tqs_pillar_grades`
(the per-pillar A–F breakdown). The A2 changelog assumed "the scanner payload already
carries tqs_pillar_grades (asdict)" — but it was EMPTY for a subset of live alerts, so
only SOME EVAL/POS cards showed the ring (RIOT/TNA/MCHP did; KEYS/TTMI did not).
ROOT CAUSE: those grades are computed only by `_enrich_alert_with_tqs()`, which runs
unconditionally on just the main RTH live-tick scan path (~L4196). Every OTHER alert
path (bar-poll / daily-swing / re-emit) funnels through the universal emission chokepoint
`_process_new_alert()`, which re-enriched ONLY when `tqs_score <= 0`. Alerts reaching the
chokepoint with `tqs_score>0` (scored by a lighter step) but an EMPTY `tqs_pillar_grades`
skipped enrichment → their WS `scanner_alerts` payload (`alert.to_dict()`) shipped no
breakdown → frontend rendered NO ring.
FIX (backend-only, additive, 1 chunk on services/enhanced_scanner.py): widen the chokepoint
guard to ALSO re-enrich when the pillar breakdown is MISSING, not just when the score is
absent — `_a2h_missing_pillars = not (alert.tqs_pillar_grades or {})`. Because
`_process_new_alert` is the universal emission point for EVERY alert path, this guarantees
pillar grades (hence a ring) on every live card. `_enrich_alert_with_tqs` is try/except-safe
+ idempotent; RTH alerts that already carry pillars don't match the new condition (no
double work).
DELIVERY: chunk patcher `scripts/patch_a2h_provenance_ring_backfill.py` (paste.rs/dNzkk),
PRE `011b8c0e…` → POST `77956844…` (rebased against live DGX bytes after a sandbox-baseline
drift abort — exactly the §2 drift-recovery flow; round-trip verified). Applied + committed
`60943659`; backend restarted clean.
VERIFY: next scan cycle — every EVAL/POS scanner card carries a Provenance Ring.

"""


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {PATH} — run from the repo root."); sys.exit(2)
    cur = open(PATH, encoding="utf-8").read()
    if ANCHOR in cur:
        print(f"  [ALREADY-PRESENT] '{ANCHOR}' already in {PATH} — nothing to do.")
        return
    open(PATH, "w", encoding="utf-8").write(BLOCK + cur)
    print(f"  [PREPENDED] v19.34.281 (A2h) block → {PATH} (+{len(BLOCK)} chars)")
    print("  NEXT: git add memory/CHANGELOG.md && git commit -m 'v19.34.281 (A2h): changelog' && git push origin main")


if __name__ == "__main__":
    main()
