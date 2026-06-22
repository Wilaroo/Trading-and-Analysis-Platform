#!/usr/bin/env python3
r"""
patch_a2h_live_alert_pillar_backfill.py — UI Track A · A2h
"Provenance Rings on EVERY live scanner alert".

ROOT CAUSE
----------
The Provenance Ring renders only when a scanner card carries
`tqs_pillar_grades` (the per-pillar A–F breakdown). Those grades are
computed exclusively by `_enrich_alert_with_tqs()`.

`_enrich_alert_with_tqs()` runs UNCONDITIONALLY only on the main RTH
live-tick scan path (enhanced_scanner.py ~line 4196). Every OTHER alert
path (bar-poll / daily-swing / re-emit) funnels through the universal
emission chokepoint `_process_new_alert()`, which re-enriches ONLY when
`tqs_score <= 0`:

    if (getattr(alert, 'tqs_score', 0) or 0) <= 0 and PREMARKET_TQS_ENABLED:
        await self._enrich_alert_with_tqs(alert)

Alerts that arrive at the chokepoint with `tqs_score > 0` (scored by a
lighter step) but with an EMPTY `tqs_pillar_grades` therefore skip
enrichment → they ship a score with no pillar breakdown → the WS
`scanner_alerts` payload (alert.to_dict()) carries `tqs_pillar_grades = {}`
→ the frontend renders NO ring. This is exactly why only SOME EVAL
scanner cards show the ring (RIOT/TNA/MCHP did; KEYS/TTMI did not).

THE FIX
-------
Widen the guard so the chokepoint ALSO re-enriches when the pillar
breakdown is missing — not just when the score is absent. Because
`_process_new_alert` is the single universal emission point for EVERY
alert path, this guarantees every live scanner card emits pillar grades
and therefore renders its ring. `_enrich_alert_with_tqs` is fully
try/except-safe and idempotent; RTH alerts that already carry pillars
do not match the new condition (no double work).

SCOPE: backend only — no `yarn build`. Restart the backend after --apply.

1 anchored, idempotent edit (.a2hbak backup):
  EDIT backend/services/enhanced_scanner.py   (widen _process_new_alert TQS guard)

Usage (repo root, e.g. ~/Trading-and-Analysis-Platform):
    python3 scripts/patch_a2h_live_alert_pillar_backfill.py --check
    python3 scripts/patch_a2h_live_alert_pillar_backfill.py --apply
    python3 scripts/patch_a2h_live_alert_pillar_backfill.py --rollback
After --apply:  restart the backend (supervisor / spark_start), then watch
the next scan cycle — every EVAL/POS scanner card should now carry a ring.
"""
import os
import sys
import shutil
import hashlib
import argparse

EDITS = [
    {
        "id": "a2h-process_new_alert pillar backfill guard",
        "path": "backend/services/enhanced_scanner.py",
        "old": """        if (getattr(alert, 'tqs_score', 0) or 0) <= 0 and \\
           os.environ.get("PREMARKET_TQS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off"):
            await self._enrich_alert_with_tqs(alert)
""",
        "new": """        # v19.34.x (UI Track A / A2h) — also re-enrich when the per-pillar
        # breakdown is MISSING, not just when the score is absent. Alerts that
        # reach this universal chokepoint via a non-RTH-live-tick path (bar-poll
        # / daily-swing / re-emit) can carry tqs_score>0 yet an EMPTY
        # tqs_pillar_grades, which makes their WS payload ship no breakdown and
        # the frontend render NO Provenance Ring (only SOME cards got rings).
        # Backfilling pillars here guarantees a ring on EVERY live card.
        # _enrich_alert_with_tqs is try/except-safe + idempotent; RTH alerts
        # that already carry pillars do not match this condition (no double work).
        _a2h_missing_pillars = not (getattr(alert, 'tqs_pillar_grades', None) or {})
        if ((getattr(alert, 'tqs_score', 0) or 0) <= 0 or _a2h_missing_pillars) and \\
           os.environ.get("PREMARKET_TQS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off"):
            await self._enrich_alert_with_tqs(alert)
""",
        "applied_marker": "_a2h_missing_pillars",
    },
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  A2h PATCH — Provenance Rings on EVERY live scanner alert")
    print("  (backfill tqs_pillar_grades at the universal _process_new_alert chokepoint)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for e in EDITS:
            p = resolve(e["path"])
            bak = p + ".a2hbak"
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                print(f"  restored {e['path']}  sha={sha(p)}")
            else:
                print(f"  no .a2hbak for {e['path']} — nothing to restore")
        print("\n  ROLLBACK complete. Restart the backend.")
        return

    # EDITS plan
    ed_plan = []
    for e in EDITS:
        p = resolve(e["path"])
        if not os.path.exists(p):
            print(f"  \u274c MISSING FILE: {e['path']}")
            sys.exit(2)
        src = open(p, encoding="utf-8").read()
        applied = e["applied_marker"] in src
        n = src.count(e["old"])
        status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
        print(f"\n  [{e['id']}]\n    file   : {e['path']}  sha={sha(p)}\n    status : {status}")
        if not applied and n != 1:
            print("    \u274c anchor not uniquely found — ABORT (no files changed).")
            sys.exit(3)
        ed_plan.append((e, p, src, applied))

    if args.check:
        nready = sum(1 for _, _, _, a in ed_plan if not a)
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    # APPLY
    changed = 0
    for e, p, _src, applied in ed_plan:
        if applied:
            print(f"  skip (applied): {e['path']}")
            continue
        cur = open(p, encoding="utf-8").read()
        if e["old"] not in cur:
            print(f"  \u274c anchor vanished at apply for {e['id']} — ABORT.")
            sys.exit(4)
        bak = p + ".a2hbak"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(cur.replace(e["old"], e["new"], 1))
        print(f"  patched {e['path']}  sha={sha(p)}  (.a2hbak saved)")
        changed += 1
    print(f"\n  APPLY complete. {changed} change(s).")
    print("  NEXT: restart the backend, then watch the next scan cycle —")
    print("        every EVAL/POS scanner card should now render a Provenance Ring.")


if __name__ == "__main__":
    main()
