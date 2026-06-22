#!/usr/bin/env python3
"""
patch_a2j_carryforward_pillar_backfill.py  —  v19.34.283 (UI Track A · A2j)
"Provenance Rings on the carry-forward gameplan watchlist"

DIAGNOSIS (operator curl /api/live-scanner/alerts): 146/146 ringless alerts were
carry-forwards (id prefix cf_*, setup carry_forward_watch/day_2_continuation,
trade_style multi_day, scan_tier swing, time_window CLOSED), all with tqs_score>0
but NO tqs_pillar_grades. They are HYDRATED from Mongo at scanner start() via
_hydrate_carry_forward_alerts_from_mongo() -> _inflate_live_alert_from_mongo(),
which BYPASSES _process_new_alert — so A2h's chokepoint backfill never ran on them,
and they were persisted (pre-A2h) without a pillar breakdown. Result: every cf_*
gameplan card rendered without a Provenance Ring.

FIX (backend-only, additive, 1 chunk on services/enhanced_scanner.py): in the
hydration loop, when an inflated carry-forward lacks tqs_pillar_grades, call
_enrich_alert_with_tqs (computes the 5-pillar breakdown from the alert's own
attributes — no live tape/IB fetch needed; try/except-safe; lazily loads the TQS
engine) and re-persist it so subsequent restarts restore the pillars directly
(self-healing, one-time cost per alert). A new `backfilled` counter is reported in
the existing hydrate log. Companion to A2h (creation-path) + A2i (/setups feed).

PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run; .a2jbak backup.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2j_carryforward_pillar_backfill.py --check
  .venv/bin/python scripts/patch_a2j_carryforward_pillar_backfill.py
  git add backend/ scripts/ && git commit -m "v19.34.283 (A2j): backfill pillar grades for hydrated carry-forwards" && git push origin main
  ./start_backend.sh --force
After restart, watch the boot log for: 'A2j pillar-backfilled N', then the cf_*
gameplan cards should all render rings. Verify:
  curl -s http://localhost:8001/api/live-scanner/alerts | python3 -c "import sys,json;a=json.load(sys.stdin)['alerts'];print(sum(1 for x in a if x.get('tqs_pillar_grades')),'/',len(a),'carry pillars')"
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = 'backend/services/enhanced_scanner.py'
PRE = '77956844aef9ce69e92d469e362874472516f9b72ae4b74ea85caff25fe3227f'
POST = '8061578717d37e5964b5d73920ea660c52afed1cc7f9302586f5a83b5a7a45d1'
OLD_B64 = 'ICAgICAgICAgICAgaHlkcmF0ZWQgPSAwCiAgICAgICAgICAgIGZvciBkb2MgaW4gZG9jczoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBhbGVydCA9IHNlbGYuX2luZmxhdGVfbGl2ZV9hbGVydF9mcm9tX21vbmdvKGRvYykKICAgICAgICAgICAgICAgICAgICBpZiBhbGVydCBhbmQgYWxlcnQuaWQgbm90IGluIHNlbGYuX2xpdmVfYWxlcnRzOgogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9saXZlX2FsZXJ0c1thbGVydC5pZF0gPSBhbGVydAogICAgICAgICAgICAgICAgICAgICAgICBoeWRyYXRlZCArPSAxCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKAogICAgICAgICAgICAgICAgICAgICAgICBmIlNraXBwZWQgaHlkcmF0aW5nIGNhcnJ5LWZvcndhcmQgIgogICAgICAgICAgICAgICAgICAgICAgICBmIntkb2MuZ2V0KCdpZCcpfToge2V9IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgaHlkcmF0ZWQ6CiAgICAgICAgICAgICAgICBsb2dnZXIuaW5mbygKICAgICAgICAgICAgICAgICAgICBmIvCfk4UgdjE5LjM0LjYgY2FycnktZm9yd2FyZCBoeWRyYXRlOiByZXN0b3JlZCAiCiAgICAgICAgICAgICAgICAgICAgZiJ7aHlkcmF0ZWR9IG5vbi1leHBpcmVkIGdhbWVwbGFuIGFsZXJ0cyBmcm9tIE1vbmdvICIKICAgICAgICAgICAgICAgICAgICBmIihzdXJ2aXZlZCBiYWNrZW5kIHJlc3RhcnQpIgogICAgICAgICAgICAgICAgKQo='
NEW_B64 = 'ICAgICAgICAgICAgaHlkcmF0ZWQgPSAwCiAgICAgICAgICAgIGJhY2tmaWxsZWQgPSAwCiAgICAgICAgICAgIGZvciBkb2MgaW4gZG9jczoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBhbGVydCA9IHNlbGYuX2luZmxhdGVfbGl2ZV9hbGVydF9mcm9tX21vbmdvKGRvYykKICAgICAgICAgICAgICAgICAgICBpZiBhbGVydCBhbmQgYWxlcnQuaWQgbm90IGluIHNlbGYuX2xpdmVfYWxlcnRzOgogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9saXZlX2FsZXJ0c1thbGVydC5pZF0gPSBhbGVydAogICAgICAgICAgICAgICAgICAgICAgICBoeWRyYXRlZCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgICMgdjE5LjM0LjI4MyAoQTJqKSDigJQgY2FycnktZm9yd2FyZHMgcGVyc2lzdGVkIGJlZm9yZSB0aGUKICAgICAgICAgICAgICAgICAgICAgICAgIyBhbGVydCBvYmplY3QgY2FycmllZCBhIHBpbGxhciBicmVha2Rvd24gKG9yIGJlZm9yZSBBMmgpCiAgICAgICAgICAgICAgICAgICAgICAgICMgcmVzdG9yZSBXSVRIT1VUIHRxc19waWxsYXJfZ3JhZGVzLCBzbyB0aGUgUHJvdmVuYW5jZSBSaW5nCiAgICAgICAgICAgICAgICAgICAgICAgICMgbmV2ZXIgcmVuZGVycyBmb3IgdGhlIG1vcm5pbmcgZ2FtZXBsYW4gd2F0Y2hsaXN0IChldmVyeQogICAgICAgICAgICAgICAgICAgICAgICAjIGNmXyogY2FyZCB3YXMgcmluZ2xlc3MpLiBCYWNrZmlsbCB0aGUgNS1waWxsYXIgYnJlYWtkb3duIG9uCiAgICAgICAgICAgICAgICAgICAgICAgICMgaHlkcmF0aW9uIHdoZW4gbWlzc2luZywgdGhlbiByZS1wZXJzaXN0IHNvIGZ1dHVyZSByZXN0YXJ0cwogICAgICAgICAgICAgICAgICAgICAgICAjIHJlc3RvcmUgaXQgZGlyZWN0bHkgKHNlbGYtaGVhbGluZywgb25lLXRpbWUgcGVyIGFsZXJ0KS4KICAgICAgICAgICAgICAgICAgICAgICAgaWYgbm90IChnZXRhdHRyKGFsZXJ0LCAidHFzX3BpbGxhcl9ncmFkZXMiLCBOb25lKSBvciB7fSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXdhaXQgc2VsZi5fZW5yaWNoX2FsZXJ0X3dpdGhfdHFzKGFsZXJ0KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoYWxlcnQsICJ0cXNfcGlsbGFyX2dyYWRlcyIsIE5vbmUpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X2NhcnJ5X2ZvcndhcmRfYWxlcnQoYWxlcnQpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGJhY2tmaWxsZWQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfYmZfZXJyOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxvZ2dlci5kZWJ1ZygKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJBMmogcGlsbGFyIGJhY2tmaWxsIHNraXBwZWQgZm9yICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJ7Z2V0YXR0cihhbGVydCwgJ2lkJywgJz8nKX06IHtfYmZfZXJyfSIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKAogICAgICAgICAgICAgICAgICAgICAgICBmIlNraXBwZWQgaHlkcmF0aW5nIGNhcnJ5LWZvcndhcmQgIgogICAgICAgICAgICAgICAgICAgICAgICBmIntkb2MuZ2V0KCdpZCcpfToge2V9IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgaHlkcmF0ZWQ6CiAgICAgICAgICAgICAgICBsb2dnZXIuaW5mbygKICAgICAgICAgICAgICAgICAgICBmIvCfk4UgdjE5LjM0LjYgY2FycnktZm9yd2FyZCBoeWRyYXRlOiByZXN0b3JlZCAiCiAgICAgICAgICAgICAgICAgICAgZiJ7aHlkcmF0ZWR9IG5vbi1leHBpcmVkIGdhbWVwbGFuIGFsZXJ0cyBmcm9tIE1vbmdvICIKICAgICAgICAgICAgICAgICAgICBmIihzdXJ2aXZlZCBiYWNrZW5kIHJlc3RhcnQpOyBBMmogcGlsbGFyLWJhY2tmaWxsZWQgIgogICAgICAgICAgICAgICAgICAgIGYie2JhY2tmaWxsZWR9IgogICAgICAgICAgICAgICAgKQo='


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
        print("    ABORT (no write). Send me your copy to rebase:")
        print(f"      gzip -c -9 {PATH} | curl -sS --data-binary @- https://paste.rs/")
        sys.exit(3)
    n = cur.count(old)
    if n != 1:
        print(f"  [ANCHOR x{n}] OLD chunk not uniquely found — ABORT (no write)."); sys.exit(4)
    out = cur.replace(old, new, 1)
    out_sha = sha(out)
    if out_sha != POST:
        print(f"  [POST-MISMATCH] would produce {out_sha} != {POST} — ABORT."); sys.exit(5)
    if CHECK:
        print(f"  [CHECK OK] {PATH} sha={cur_sha[:12]} -> POST {POST[:12]} (1 chunk). Re-run without --check.")
        return
    bak = PATH + ".a2jbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {PATH}  {PRE[:12]} -> {POST[:12]}  (.a2jbak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
