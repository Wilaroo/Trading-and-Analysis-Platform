#!/usr/bin/env python3
"""
patch_a2h_provenance_ring_backfill.py  —  v19.34.281 (UI Track A · A2h)
"Provenance Rings on EVERY live scanner alert"

ROOT CAUSE
----------
The A2 Provenance Ring renders only when a scanner card carries
`tqs_pillar_grades` (the per-pillar A-F breakdown). The A2 changelog assumed
"the scanner payload already carries tqs_pillar_grades (asdict)" — but it is
EMPTY for a subset of live alerts, so only SOME EVAL/POS cards show the ring
(RIOT/TNA/MCHP did; KEYS/TTMI did not).

Those grades are computed only by `_enrich_alert_with_tqs()`, which runs
UNCONDITIONALLY on just the main RTH live-tick scan path (~line 4196). Every
OTHER alert path (bar-poll / daily-swing / re-emit) funnels through the single
universal emission chokepoint `_process_new_alert()`, which re-enriched ONLY
when `tqs_score <= 0`. Alerts that reach the chokepoint with tqs_score>0 (scored
by a lighter step) but an EMPTY tqs_pillar_grades therefore SKIPPED enrichment,
so their WS `scanner_alerts` payload (alert.to_dict()) shipped no breakdown and
the frontend rendered NO ring.

FIX (backend-only, additive)
----------------------------
Widen the chokepoint guard to ALSO re-enrich when the pillar breakdown is
MISSING — not just when the score is absent. Because `_process_new_alert` is
the universal emission point for EVERY alert path, this guarantees pillar grades
(hence a ring) on every live card. `_enrich_alert_with_tqs` is fully
try/except-safe and idempotent; RTH alerts that already carry pillars do not
match the new condition (no double work).

Scope: 1 chunk on backend/services/enhanced_scanner.py. No frontend / no
`yarn build`. PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run;
auto-backup .a2hbak.

USAGE (repo root, e.g. ~/Trading-and-Analysis-Platform):
  .venv/bin/python scripts/patch_a2h_provenance_ring_backfill.py --check
  .venv/bin/python scripts/patch_a2h_provenance_ring_backfill.py
  # COMMIT BEFORE ANY RESTART (StartTrading.bat step-2 git-wipes uncommitted code):
  git add backend/ && git commit -m "v19.34.281 (A2h): backfill tqs_pillar_grades at alert chokepoint" && git push origin main
  ./start_backend.sh --force
Rollback: restore backend/services/enhanced_scanner.py.a2hbak over the target.
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = 'backend/services/enhanced_scanner.py'
PRE = '011b8c0ee59bd5b2aea62d3e2575296af50bea0304178a1fd8608edc7a428cea'
POST = '77956844aef9ce69e92d469e362874472516f9b72ae4b74ea85caff25fe3227f'
OLD_B64 = 'ICAgICAgICBpZiAoZ2V0YXR0cihhbGVydCwgJ3Rxc19zY29yZScsIDApIG9yIDApIDw9IDAgYW5kIFwKICAgICAgICAgICBvcy5lbnZpcm9uLmdldCgiUFJFTUFSS0VUX1RRU19FTkFCTEVEIiwgIjEiKS5zdHJpcCgpLmxvd2VyKCkgbm90IGluICgiMCIsICJmYWxzZSIsICJubyIsICJvZmYiKToKICAgICAgICAgICAgYXdhaXQgc2VsZi5fZW5yaWNoX2FsZXJ0X3dpdGhfdHFzKGFsZXJ0KQo='
NEW_B64 = 'ICAgICAgICAjIHYxOS4zNC54IChVSSBUcmFjayBBIC8gQTJoKSDigJQgYWxzbyByZS1lbnJpY2ggd2hlbiB0aGUgcGVyLXBpbGxhcgogICAgICAgICMgYnJlYWtkb3duIGlzIE1JU1NJTkcsIG5vdCBqdXN0IHdoZW4gdGhlIHNjb3JlIGlzIGFic2VudC4gQWxlcnRzIHRoYXQKICAgICAgICAjIHJlYWNoIHRoaXMgdW5pdmVyc2FsIGNob2tlcG9pbnQgdmlhIGEgbm9uLVJUSC1saXZlLXRpY2sgcGF0aCAoYmFyLXBvbGwKICAgICAgICAjIC8gZGFpbHktc3dpbmcgLyByZS1lbWl0KSBjYW4gY2FycnkgdHFzX3Njb3JlPjAgeWV0IGFuIEVNUFRZCiAgICAgICAgIyB0cXNfcGlsbGFyX2dyYWRlcywgd2hpY2ggbWFrZXMgdGhlaXIgV1MgcGF5bG9hZCBzaGlwIG5vIGJyZWFrZG93biBhbmQKICAgICAgICAjIHRoZSBmcm9udGVuZCByZW5kZXIgTk8gUHJvdmVuYW5jZSBSaW5nIChvbmx5IFNPTUUgY2FyZHMgZ290IHJpbmdzKS4KICAgICAgICAjIEJhY2tmaWxsaW5nIHBpbGxhcnMgaGVyZSBndWFyYW50ZWVzIGEgcmluZyBvbiBFVkVSWSBsaXZlIGNhcmQuCiAgICAgICAgIyBfZW5yaWNoX2FsZXJ0X3dpdGhfdHFzIGlzIHRyeS9leGNlcHQtc2FmZSArIGlkZW1wb3RlbnQ7IFJUSCBhbGVydHMKICAgICAgICAjIHRoYXQgYWxyZWFkeSBjYXJyeSBwaWxsYXJzIGRvIG5vdCBtYXRjaCB0aGlzIGNvbmRpdGlvbiAobm8gZG91YmxlIHdvcmspLgogICAgICAgIF9hMmhfbWlzc2luZ19waWxsYXJzID0gbm90IChnZXRhdHRyKGFsZXJ0LCAndHFzX3BpbGxhcl9ncmFkZXMnLCBOb25lKSBvciB7fSkKICAgICAgICBpZiAoKGdldGF0dHIoYWxlcnQsICd0cXNfc2NvcmUnLCAwKSBvciAwKSA8PSAwIG9yIF9hMmhfbWlzc2luZ19waWxsYXJzKSBhbmQgXAogICAgICAgICAgIG9zLmVudmlyb24uZ2V0KCJQUkVNQVJLRVRfVFFTX0VOQUJMRUQiLCAiMSIpLnN0cmlwKCkubG93ZXIoKSBub3QgaW4gKCIwIiwgImZhbHNlIiwgIm5vIiwgIm9mZiIpOgogICAgICAgICAgICBhd2FpdCBzZWxmLl9lbnJpY2hfYWxlcnRfd2l0aF90cXMoYWxlcnQpCg=='


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {PATH} — run from the repo root."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    old = base64.b64decode(OLD_B64)
    new = base64.b64decode(NEW_B64)

    if cur_sha == POST or new in cur:
        print(f"  [ALREADY-APPLIED] {PATH} sha={cur_sha[:12]} — nothing to do.")
        return

    if cur_sha != PRE:
        print(f"  [DRIFT] {PATH}")
        print(f"    expected PRE  {PRE}")
        print(f"    found on disk {cur_sha}")
        print("    ABORT (no write). The live file differs from the patch baseline.")
        print("    Send me your copy so I can rebase:")
        print(f"      curl -sS --data-binary @{PATH} https://paste.rs/   # paste me the URL")
        sys.exit(3)

    n = cur.count(old)
    if n != 1:
        print(f"  [ANCHOR x{n}] OLD chunk not uniquely found — ABORT (no write)."); sys.exit(4)

    out = cur.replace(old, new, 1)
    out_sha = sha(out)
    if out_sha != POST:
        print(f"  [POST-MISMATCH] would produce {out_sha} != expected {POST} — ABORT (no write)."); sys.exit(5)

    if CHECK:
        print(f"  [CHECK OK] {PATH} sha={cur_sha[:12]} -> POST {POST[:12]} (1 chunk). Re-run without --check to apply.")
        return

    bak = PATH + ".a2hbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {PATH}  {PRE[:12]} -> {POST[:12]}  (.a2hbak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
