#!/usr/bin/env python3
"""patch_v320j_unrealized_pnl_persist.py  —  v19.34.320j patcher  (2026-06-16)

Issue 4 fix: manage_open_trades computed trade.unrealized_pnl /\npnl_pct in-memory each tick but never persisted them, so Mongo kept\nthe creation-time $0 for all open positions. Adds a THROTTLED (~20s/\ntrade) targeted update_one of {unrealized_pnl, pnl_pct, current_price,\nunrealized_pnl_synced_at}. No new asyncio loop. position_manager.py\n(targets the v320h.1-applied state, PRE 90c45132).

AGENTS.md §2.2: PRE_SHA256 + POST_SHA256 guards, base64 (old,new) chunk pairs
applied in order (each must be unique), auto-backup, --check/--apply/--rollback
/--status. Local override via V320H_PM_TARGET / TAP_REPO_ROOT.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "90c451329b766f369e03bb0bffb2fcc385e604dd765fb49f5ef9431d0503495d"
POST_SHA256 = "6752423e3694ef2a93875bed1f00c99035eb27ae29ad7d87ab6a56e4a67b9126"
SENTINEL = "v19.34.320j"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320H_PM_TARGET") or (REPO_ROOT / "backend/services/position_manager.py"))

# list of [old_b64, new_b64] applied in order
CHUNKS = [
    ["ICAgICAgICAgICAgICAgICMgSW5jbHVkZSByZWFsaXplZCBQJkwgZnJvbSBwYXJ0aWFsIGV4aXRzCiAgICAgICAgICAgICAgICB0b3RhbF92YWx1ZSA9IHRyYWRlLnJlbWFpbmluZ19zaGFyZXMgKiB0cmFkZS5maWxsX3ByaWNlCiAgICAgICAgICAgICAgICBpZiB0b3RhbF92YWx1ZSA+IDA6CiAgICAgICAgICAgICAgICAgICAgdHJhZGUucG5sX3BjdCA9ICgodHJhZGUudW5yZWFsaXplZF9wbmwgKyB0cmFkZS5yZWFsaXplZF9wbmwpIC8gKHRyYWRlLm9yaWdpbmFsX3NoYXJlcyAqIHRyYWRlLmZpbGxfcHJpY2UpKSAqIDEwMAoKICAgICAgICAgICAgICAgICMgVXBkYXRlIHRyYWlsaW5nIHN0b3AgaWYgZW5hYmxlZAo=",
     "ICAgICAgICAgICAgICAgICMgSW5jbHVkZSByZWFsaXplZCBQJkwgZnJvbSBwYXJ0aWFsIGV4aXRzCiAgICAgICAgICAgICAgICB0b3RhbF92YWx1ZSA9IHRyYWRlLnJlbWFpbmluZ19zaGFyZXMgKiB0cmFkZS5maWxsX3ByaWNlCiAgICAgICAgICAgICAgICBpZiB0b3RhbF92YWx1ZSA+IDA6CiAgICAgICAgICAgICAgICAgICAgdHJhZGUucG5sX3BjdCA9ICgodHJhZGUudW5yZWFsaXplZF9wbmwgKyB0cmFkZS5yZWFsaXplZF9wbmwpIC8gKHRyYWRlLm9yaWdpbmFsX3NoYXJlcyAqIHRyYWRlLmZpbGxfcHJpY2UpKSAqIDEwMAoKICAgICAgICAgICAgICAgICMgdjE5LjM0LjMyMGog4oCUIHBlcnNpc3QgbGl2ZSB1bnJlYWxpemVkX3BubC9wbmxfcGN0IHRvIE1vbmdvIHNvCiAgICAgICAgICAgICAgICAjIG9wZW4tcG9zaXRpb24gUCZMIGlzIG9ic2VydmFibGUgYXQgdGhlIERCIGxldmVsICh3YXMgY29tcHV0ZWQKICAgICAgICAgICAgICAgICMgaW4tbWVtb3J5IG9ubHkgLT4gREIgc2hvd2VkICQwIGZvciBhbGwgb3BlbnMpLiBUaHJvdHRsZWQgcGVyCiAgICAgICAgICAgICAgICAjIHRyYWRlICh+MjBzKSB0byBhdm9pZCBhIHBlci10aWNrIHdyaXRlIHN0b3JtLgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGltcG9ydCB0aW1lIGFzIF90XzMyMGoKICAgICAgICAgICAgICAgICAgICBmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRldGltZSBhcyBfZHRfMzIwaiwgdGltZXpvbmUgYXMgX3R6XzMyMGoKICAgICAgICAgICAgICAgICAgICBfbGFzdF8zMjBqID0gZ2V0YXR0cih0cmFkZSwgIl92MzIwal9sYXN0X3BubF9zeW5jIiwgMCkgb3IgMAogICAgICAgICAgICAgICAgICAgIGlmIChfdF8zMjBqLnRpbWUoKSAtIF9sYXN0XzMyMGopID49IDIwOgogICAgICAgICAgICAgICAgICAgICAgICBfZGJfMzIwaiA9IChnZXRhdHRyKGJvdCwgIl9kYiIsIE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoYm90LCAiX2RiIiwgTm9uZSkgaXMgbm90IE5vbmUKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZWxzZSBnZXRhdHRyKGJvdCwgImRiIiwgTm9uZSkpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9kYl8zMjBqIGlzIG5vdCBOb25lIGFuZCBnZXRhdHRyKHRyYWRlLCAiaWQiLCBOb25lKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF3YWl0IGFzeW5jaW8udG9fdGhyZWFkKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9kYl8zMjBqLmJvdF90cmFkZXMudXBkYXRlX29uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB7ImlkIjogdHJhZGUuaWR9LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHsiJHNldCI6IHsKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgInVucmVhbGl6ZWRfcG5sIjogZmxvYXQoZ2V0YXR0cih0cmFkZSwgInVucmVhbGl6ZWRfcG5sIiwgMCkgb3IgMCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJwbmxfcGN0IjogZmxvYXQoZ2V0YXR0cih0cmFkZSwgInBubF9wY3QiLCAwKSBvciAwKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgImN1cnJlbnRfcHJpY2UiOiBmbG9hdChnZXRhdHRyKHRyYWRlLCAiY3VycmVudF9wcmljZSIsIDApIG9yIDApLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAidW5yZWFsaXplZF9wbmxfc3luY2VkX2F0IjogX2R0XzMyMGoubm93KF90el8zMjBqLnV0YykuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgfX0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cmFkZS5fdjMyMGpfbGFzdF9wbmxfc3luYyA9IF90XzMyMGoudGltZSgpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIF9lXzMyMGo6CiAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKCJbdjE5LjM0LjMyMGpdIHVucmVhbGl6ZWRfcG5sIHBlcnNpc3QgdGhyZXc6ICVzIiwgX2VfMzIwaikKCiAgICAgICAgICAgICAgICAjIFVwZGF0ZSB0cmFpbGluZyBzdG9wIGlmIGVuYWJsZWQK"],
]
APPLIED_STAMP = "/tmp/v320j_unrealized_persist.applied"


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
    print("\n  NEXT: git add backend/services/position_manager.py && git commit -m 'v19.34.320j' && git push origin main")
    print("        ./start_backend.sh --force")


def cmd_rollback():
    body = _read()
    if SENTINEL not in body:
        print("  no v19.34.320j sentinel present — nothing to roll back.")
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
