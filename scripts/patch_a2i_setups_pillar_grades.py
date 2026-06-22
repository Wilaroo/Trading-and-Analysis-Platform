#!/usr/bin/env python3
"""
patch_a2i_setups_pillar_grades.py  —  v19.34.282 (UI Track A · A2i)
"Provenance Ring data on EVAL scanner cards"

The A2 Provenance Ring renders only when a card carries `tqs_pillar_grades`.
EVAL scanner cards are fed by GET /api/sentcom/setups -> get_setups_watching()
Source 1 (live scanner alerts), whose serialized dict DROPPED
tqs_pillar_grades / tqs_grade / tqs_score. So even when the alert object carries
the per-pillar breakdown, the /setups feed stripped it and the ring never rendered
on EVAL cards (OPEN positions use a different, already-fixed feed).

FIX (backend-only, additive, 1 chunk on services/sentcom_service.py): add the
three fields to the Source 1 'live_scanner' dict, read from the alert via getattr
with safe defaults ({} / None).

NOTE: A2i surfaces pillars that EXIST on the alert object. Alerts whose object
still lacks pillars (e.g. hydrated carry-forwards) are handled by the companion
A2j fix. PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run; .a2ibak backup.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2i_setups_pillar_grades.py --check
  .venv/bin/python scripts/patch_a2i_setups_pillar_grades.py
  git add backend/ scripts/ && git commit -m "v19.34.282 (A2i): /setups surfaces tqs_pillar_grades for EVAL ring" && git push origin main
  ./start_backend.sh --force
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = 'backend/services/sentcom_service.py'
PRE = '0ef6e9f6add4b48cdac8119daa31580db555a92ec31dfdf78170e3aa51b25be8'
POST = '76a1e56953a9dd800e64c7bbe55c9a9d4458325d9dbabb2d8dbe340f4b8721e6'
OLD_B64 = 'ICAgICAgICAgICAgICAgICAgICAgICAgImdyYWRlIjogYWxlcnQudHFzX2dyYWRlIG9yIGFsZXJ0LnRyYWRlX2dyYWRlLAogICAgICAgICAgICAgICAgICAgICAgICAicHJpb3JpdHkiOiBhbGVydC5wcmlvcml0eS52YWx1ZSBpZiBhbGVydC5wcmlvcml0eSBlbHNlICJtZWRpdW0iLAogICAgICAgICAgICAgICAgICAgICAgICAiaGVhZGxpbmUiOiBhbGVydC5oZWFkbGluZSwKICAgICAgICAgICAgICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRpbWVzdGFtcCwKICAgICAgICAgICAgICAgICAgICAgICAgInNvdXJjZSI6ICJsaXZlX3NjYW5uZXIiLAogICAgICAgICAgICAgICAgICAgICAgICAiYWxlcnRfaWQiOiBhbGVydC5pZAogICAgICAgICAgICAgICAgICAgIH0pCg=='
NEW_B64 = 'ICAgICAgICAgICAgICAgICAgICAgICAgImdyYWRlIjogYWxlcnQudHFzX2dyYWRlIG9yIGFsZXJ0LnRyYWRlX2dyYWRlLAogICAgICAgICAgICAgICAgICAgICAgICAjIHYxOS4zNC4yODIgKEEyaSkg4oCUIHN1cmZhY2UgdGhlIHBlci1waWxsYXIgQS1GIGJyZWFrZG93biArCiAgICAgICAgICAgICAgICAgICAgICAgICMgY2Fub25pY2FsIFRRUyBzY29yZS9ncmFkZSBzbyB0aGUgUHJvdmVuYW5jZSBSaW5nIHJlbmRlcnMgb24KICAgICAgICAgICAgICAgICAgICAgICAgIyBFVkFMIHNjYW5uZXIgY2FyZHMuIFRoZSAvYXBpL3NlbnRjb20vc2V0dXBzIGZlZWQgKHRoaXMgZGljdCkKICAgICAgICAgICAgICAgICAgICAgICAgIyBwcmV2aW91c2x5IGRyb3BwZWQgdGhlc2UsIGxlYXZpbmcgZXZlcnkgRVZBTCBjYXJkIHJpbmdsZXNzCiAgICAgICAgICAgICAgICAgICAgICAgICMgZXZlbiBhZnRlciBBMmggcG9wdWxhdGVkIHRoZSBhbGVydCBvYmplY3RzLgogICAgICAgICAgICAgICAgICAgICAgICAidHFzX3Njb3JlIjogKGludChhbGVydC50cXNfc2NvcmUpIGlmIGdldGF0dHIoYWxlcnQsICJ0cXNfc2NvcmUiLCBOb25lKSBlbHNlIE5vbmUpLAogICAgICAgICAgICAgICAgICAgICAgICAidHFzX2dyYWRlIjogZ2V0YXR0cihhbGVydCwgInRxc19ncmFkZSIsIE5vbmUpIG9yIGdldGF0dHIoYWxlcnQsICJ0cmFkZV9ncmFkZSIsIE5vbmUpLAogICAgICAgICAgICAgICAgICAgICAgICAidHFzX3BpbGxhcl9ncmFkZXMiOiBnZXRhdHRyKGFsZXJ0LCAidHFzX3BpbGxhcl9ncmFkZXMiLCBOb25lKSBvciB7fSwKICAgICAgICAgICAgICAgICAgICAgICAgInByaW9yaXR5IjogYWxlcnQucHJpb3JpdHkudmFsdWUgaWYgYWxlcnQucHJpb3JpdHkgZWxzZSAibWVkaXVtIiwKICAgICAgICAgICAgICAgICAgICAgICAgImhlYWRsaW5lIjogYWxlcnQuaGVhZGxpbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0aW1lc3RhbXAiOiB0aW1lc3RhbXAsCiAgICAgICAgICAgICAgICAgICAgICAgICJzb3VyY2UiOiAibGl2ZV9zY2FubmVyIiwKICAgICAgICAgICAgICAgICAgICAgICAgImFsZXJ0X2lkIjogYWxlcnQuaWQKICAgICAgICAgICAgICAgICAgICB9KQo='


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
    bak = PATH + ".a2ibak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {PATH}  {PRE[:12]} -> {POST[:12]}  (.a2ibak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
