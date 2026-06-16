#!/usr/bin/env python3
"""patch_v320i_target_order_ids_capture.py  —  v19.34.320i patcher  (2026-06-16)

Issue 5 fix: the entry/bracket path stamped only the SINGULAR\ntrade.target_order_id and left the PLURAL trade.target_order_ids=[]\n(SATS 2026-06: OCA target hit but list empty -> stop-vs-target leg\nclassifier blind). Carries target_order_ids through the result dict\nand populates trade.target_order_ids at both the entry-stamp and the\nv322l reclaim sites. trade_execution.py.

AGENTS.md §2.2: PRE_SHA256 + POST_SHA256 guards, base64 (old,new) chunk pairs
applied in order (each must be unique), auto-backup, --check/--apply/--rollback
/--status. Local override via V320I_TE_TARGET / TAP_REPO_ROOT.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "f8037748a65d4dde4ca2435f6826f837726653fe8c10423702cd0a7c5aa7eeb4"
POST_SHA256 = "5a349f9deb62ca192134b61cd3ba76d8905003ed2341efaeb291370b30c35a01"
SENTINEL = "v19.34.320i"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320I_TE_TARGET") or (REPO_ROOT / "backend/services/trade_execution.py"))

# list of [old_b64, new_b64] applied in order
CHUNKS = [
    ["ICAgICAgICAgICAgICAgICAgICAidGFyZ2V0X29yZGVyX2lkIjogYnJhY2tldF9yZXN1bHQuZ2V0KCJ0YXJnZXRfb3JkZXJfaWQiKSwKICAgICAgICAgICAgICAgICAgICAib2NhX2dyb3VwIjogYnJhY2tldF9yZXN1bHQuZ2V0KCJvY2FfZ3JvdXAiKSwK",
     "ICAgICAgICAgICAgICAgICAgICAidGFyZ2V0X29yZGVyX2lkIjogYnJhY2tldF9yZXN1bHQuZ2V0KCJ0YXJnZXRfb3JkZXJfaWQiKSwKICAgICAgICAgICAgICAgICAgICAidGFyZ2V0X29yZGVyX2lkcyI6IGJyYWNrZXRfcmVzdWx0LmdldCgidGFyZ2V0X29yZGVyX2lkcyIpLAogICAgICAgICAgICAgICAgICAgICJvY2FfZ3JvdXAiOiBicmFja2V0X3Jlc3VsdC5nZXQoIm9jYV9ncm91cCIpLAo="],
    ["ICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5nZXQoJ2JyYWNrZXQnKToKICAgICAgICAgICAgICAgICAgICB0cmFkZS5zdG9wX29yZGVyX2lkID0gcmVzdWx0LmdldCgnc3RvcF9vcmRlcl9pZCcpCiAgICAgICAgICAgICAgICAgICAgdHJhZGUudGFyZ2V0X29yZGVyX2lkID0gcmVzdWx0LmdldCgndGFyZ2V0X29yZGVyX2lkJykKICAgICAgICAgICAgICAgICAgICBpZiByZXN1bHQuZ2V0KCdvY2FfZ3JvdXAnKToK",
     "ICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5nZXQoJ2JyYWNrZXQnKToKICAgICAgICAgICAgICAgICAgICB0cmFkZS5zdG9wX29yZGVyX2lkID0gcmVzdWx0LmdldCgnc3RvcF9vcmRlcl9pZCcpCiAgICAgICAgICAgICAgICAgICAgdHJhZGUudGFyZ2V0X29yZGVyX2lkID0gcmVzdWx0LmdldCgndGFyZ2V0X29yZGVyX2lkJykKICAgICAgICAgICAgICAgICAgICAjIHYxOS4zNC4zMjBpIOKAlCBhbHNvIHBvcHVsYXRlIHRoZSBwbHVyYWwgdGFyZ2V0X29yZGVyX2lkcwogICAgICAgICAgICAgICAgICAgICMgbGlzdCAobGVnLWlkIHNvdXJjZSBmb3IgY2xvc2UvRU9EIGNhbmNlbCBwYXRocyArIHRoZQogICAgICAgICAgICAgICAgICAgICMgc3RvcC12cy10YXJnZXQgY2xhc3NpZmllcikuIEVudHJ5IGhpc3RvcmljYWxseSBzZXQgb25seQogICAgICAgICAgICAgICAgICAgICMgdGhlIHNpbmd1bGFyIGlkLCBsZWF2aW5nIHRhcmdldF9vcmRlcl9pZHM9W10gKFNBVFMKICAgICAgICAgICAgICAgICAgICAjIDIwMjYtMDY6IHRhcmdldCBoaXQgYnV0IGxpc3QgZW1wdHkgLT4gY2xhc3NpZmllciBibGluZCkuCiAgICAgICAgICAgICAgICAgICAgX3RpZHNfMzIwaSA9IChyZXN1bHQuZ2V0KCd0YXJnZXRfb3JkZXJfaWRzJykKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9yIChbcmVzdWx0LmdldCgndGFyZ2V0X29yZGVyX2lkJyldIGlmIHJlc3VsdC5nZXQoJ3RhcmdldF9vcmRlcl9pZCcpIGVsc2UgW10pKQogICAgICAgICAgICAgICAgICAgIHRyYWRlLnRhcmdldF9vcmRlcl9pZHMgPSBbc3RyKF94KSBmb3IgX3ggaW4gX3RpZHNfMzIwaSBpZiBfeF0KICAgICAgICAgICAgICAgICAgICBpZiByZXN1bHQuZ2V0KCdvY2FfZ3JvdXAnKToK"],
    ["ICAgICAgICAgICAgICAgIGlmIG9jYS5nZXQoInRhcmdldF9vcmRlcl9pZCIpOgogICAgICAgICAgICAgICAgICAgIHRyYWRlLnRhcmdldF9vcmRlcl9pZCA9IG9jYS5nZXQoInRhcmdldF9vcmRlcl9pZCIpCiAgICAgICAgICAgICAgICB0cmFkZS5vY2FfZ3JvdXAgPSBvY2EuZ2V0KCJvY2FfZ3JvdXAiKQo=",
     "ICAgICAgICAgICAgICAgIGlmIG9jYS5nZXQoInRhcmdldF9vcmRlcl9pZCIpOgogICAgICAgICAgICAgICAgICAgIHRyYWRlLnRhcmdldF9vcmRlcl9pZCA9IG9jYS5nZXQoInRhcmdldF9vcmRlcl9pZCIpCiAgICAgICAgICAgICAgICAgICAgIyB2MTkuMzQuMzIwaSDigJQga2VlcCB0aGUgcGx1cmFsIGxpc3QgaW4gc3luYyAoc2VlIGVudHJ5IHBhdGgpLgogICAgICAgICAgICAgICAgICAgIF90aWRzXzMyMGkgPSAob2NhLmdldCgidGFyZ2V0X29yZGVyX2lkcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciBbb2NhLmdldCgidGFyZ2V0X29yZGVyX2lkIildKQogICAgICAgICAgICAgICAgICAgIHRyYWRlLnRhcmdldF9vcmRlcl9pZHMgPSBbc3RyKF94KSBmb3IgX3ggaW4gX3RpZHNfMzIwaSBpZiBfeF0KICAgICAgICAgICAgICAgIHRyYWRlLm9jYV9ncm91cCA9IG9jYS5nZXQoIm9jYV9ncm91cCIpCg=="],
]
APPLIED_STAMP = "/tmp/v320i_target_ids.applied"


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _read():
    if not TARGET.exists():
        print("ERROR: target missing:", TARGET)
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def _apply_all(body):
    for old_b64, new_b64 in CHUNKS:
        old = base64.b64decode(old_b64).decode("utf-8")
        new = base64.b64decode(new_b64).decode("utf-8")
        if body.count(old) != 1:
            return None, "anchor not unique (count=%d)" % body.count(old)
        body = body.replace(old, new, 1)
    return body, None


def _revert_all(body):
    for old_b64, new_b64 in reversed(CHUNKS):
        old = base64.b64decode(old_b64).decode("utf-8")
        new = base64.b64decode(new_b64).decode("utf-8")
        if body.count(new) != 1:
            return None, "patched chunk not unique (count=%d)" % body.count(new)
        body = body.replace(new, old, 1)
    return body, None


def cmd_check():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print("  target :", TARGET)
    print("  sha    :", cur)
    if SENTINEL in body:
        if cur == POST_SHA256:
            print("  ALREADY APPLIED (sha == POST_SHA256). No-op. Use --rollback to revert.")
            sys.exit(0)
        print("  marker present but sha != POST_SHA256 — file drifted post-apply.")
        sys.exit(4)
    if cur != PRE_SHA256:
        print("  PRE_SHA256 MISMATCH — file drifted from canonical baseline.")
        print("    expected", PRE_SHA256)
        print("    actual  ", cur)
        print("    -> upload your copy and ask for a rebase.")
        sys.exit(2)
    projected, err = _apply_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(3)
    pp = _sha(projected.encode("utf-8"))
    print("  PRE_SHA256 ok; all %d anchors unique." % len(CHUNKS))
    print("  projected POST_SHA256 =", pp)
    if pp != POST_SHA256:
        print("  projected sha != embedded POST_SHA256 — ABORT.")
        sys.exit(5)
    print("  projected hash matches embedded POST_SHA256. Run --apply to write.")


def cmd_apply():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if SENTINEL in body and cur == POST_SHA256:
        print("  ALREADY APPLIED. No-op.")
        return
    if cur != PRE_SHA256:
        print("  ABORT: PRE_SHA256 mismatch. Run --check.")
        sys.exit(2)
    new_body, err = _apply_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(3)
    pp = _sha(new_body.encode("utf-8"))
    if pp != POST_SHA256:
        print("  ABORT: post-patch sha %s != embedded POST_SHA256. No write." % pp)
        sys.exit(5)
    bak = TARGET.with_suffix(TARGET.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")
    Path(APPLIED_STAMP).write_text("applied_at=%s\npre=%s\npost=%s\nbackup=%s\n" % (
        datetime.now(timezone.utc).isoformat(), PRE_SHA256, POST_SHA256, bak))
    print("  wrote", TARGET, "(%d chars)" % len(new_body))
    print("  backup at", bak.name)
    print("  POST_SHA256 verified ==", POST_SHA256)
    print("\n  NEXT: git add backend/services/trade_execution.py && git commit -m 'v19.34.320i' && git push origin main")
    print("        ./start_backend.sh --force")


def cmd_rollback():
    body = _read()
    if SENTINEL not in body:
        print("  no v19.34.320i sentinel present — nothing to roll back.")
        return
    new, err = _revert_all(body)
    if err:
        print("  ABORT:", err)
        sys.exit(2)
    rp = _sha(new.encode("utf-8"))
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_rollback." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print("  rolled back. patched copy at", bak.name)
    print("  restored sha =", rp, " (== PRE_SHA256:", rp == PRE_SHA256, ")")


def cmd_status():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print("  target  :", TARGET)
    print("  sha     :", cur)
    print("  applied :", SENTINEL in body, " (sha==POST:", cur == POST_SHA256, "; sha==PRE:", cur == PRE_SHA256, ")")
    if os.path.exists(APPLIED_STAMP):
        print("  stamp   :\n" + Path(APPLIED_STAMP).read_text())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.check:
        cmd_check()
    elif a.apply:
        cmd_apply()
    elif a.rollback:
        cmd_rollback()
    elif a.status:
        cmd_status()


if __name__ == "__main__":
    main()
