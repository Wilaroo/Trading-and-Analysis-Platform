#!/usr/bin/env python3
"""patch_v320L_naked_sweep_datetime_fix.py  —  v19.34.320L patcher  (2026-06-16)

Bug fix (pre-existing v19.34.31): _naked_position_sweep had a\nfunction-local `from datetime import datetime, timezone` (L5958) inside\na conditional branch, making datetime/timezone LOCALS for the whole\nfunction. The naked-sweep telemetry write (~L6530) then raised\nUnboundLocalError every cycle when that branch wasn't taken. Removes\nthe redundant local import; module-global (L19) now resolves.\ntrading_bot_service.py.

AGENTS.md §2.2: PRE_SHA256 + POST_SHA256 guards, base64 (old,new) chunk pairs
applied in order (each must be unique), auto-backup, --check/--apply/--rollback
/--status. Local override via V320L_TBS_TARGET / TAP_REPO_ROOT.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "b4cb8a7dfcabe6fb02108b0f40283dc05f596351bcdb3ec45a17960604c2d8b6"
POST_SHA256 = "b3a9ae2929c31b9ed427fe1de059c17b3e413fcf8eb73859b89ea229ef98e19d"
SENTINEL = "v19.34.320L"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320L_TBS_TARGET") or (REPO_ROOT / "backend/services/trading_bot_service.py"))

# list of [old_b64, new_b64] applied in order
CHUNKS = [
    ["ICAgICAgICAgICAgICAgIGZyb20gcm91dGVycy5pYiBpbXBvcnQgX3B1c2hlZF9pYl9kYXRhCiAgICAgICAgICAgICAgICBmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRldGltZSwgdGltZXpvbmUKICAgICAgICAgICAgICAgIF9sdSA9IChfcHVzaGVkX2liX2RhdGEgb3Ige30pLmdldCgibGFzdF91cGRhdGUiKQo=",
     "ICAgICAgICAgICAgICAgIGZyb20gcm91dGVycy5pYiBpbXBvcnQgX3B1c2hlZF9pYl9kYXRhCiAgICAgICAgICAgICAgICAjIHYxOS4zNC4zMjBMIOKAlCB1c2UgbW9kdWxlLWdsb2JhbCBkYXRldGltZS90aW1lem9uZSAobGluZSAxOSkuCiAgICAgICAgICAgICAgICAjIFRoZSBwcmlvciBsb2NhbCAiZnJvbSBkYXRldGltZSBpbXBvcnQgZGF0ZXRpbWUsIHRpbWV6b25lIiBoZXJlCiAgICAgICAgICAgICAgICAjIGJvdW5kIHRoZW0gZnVuY3Rpb24td2lkZSwgY2F1c2luZyBVbmJvdW5kTG9jYWxFcnJvciBhdCB0aGUKICAgICAgICAgICAgICAgICMgbmFrZWQtc3dlZXAgdGVsZW1ldHJ5IHdyaXRlICh+TDY1MzApIHdoZW4gdGhpcyBicmFuY2ggd2Fzbid0IHRha2VuLgogICAgICAgICAgICAgICAgX2x1ID0gKF9wdXNoZWRfaWJfZGF0YSBvciB7fSkuZ2V0KCJsYXN0X3VwZGF0ZSIpCg=="],
]
APPLIED_STAMP = "/tmp/v320L_naked_sweep_datetime.applied"


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
    print("\n  NEXT: git add backend/services/trading_bot_service.py && git commit -m 'v19.34.320L' && git push origin main")
    print("        ./start_backend.sh --force")


def cmd_rollback():
    body = _read()
    if SENTINEL not in body:
        print("  no v19.34.320L sentinel present — nothing to roll back.")
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
