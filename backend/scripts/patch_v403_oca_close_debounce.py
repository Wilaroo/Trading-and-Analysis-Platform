#!/usr/bin/env python3
r"""
patch_v403_oca_close_debounce.py — Position close-path · transient-snapshot guard (v403).

WHY (proven by diag_oca_close_transient_vs_reentry.py on live DGX)
  The v19.31 "externally-closed phantom sweep" marks a bot_trade
  `oca_closed_externally` whenever IB reports 0 shares in BOTH directions and
  the trade is >=30s old. The fill tape proved FOXA/KR/LULU were each marked
  closed 30-60s AFTER a fresh open fill while the position was fully held
  (net=-20/-77/-8, ZERO cover fills) -- i.e. a TRANSIENT IB 0-share snapshot in
  the first minute after a fill. The reconciler then re-adopted the live
  position as a synthetic `reconciled_external` orphan (2% stop + a false
  "I did NOT open this" warning).

FIX (BACKEND-ONLY, reversible) -- DEBOUNCE the sweep:
  Require OCA_CLOSE_ZERO_STREAK (default 2) CONSECUTIVE zero-both-direction
  reads before closing; the streak resets the instant IB reports ANY shares for
  the symbol. A one-tick transient snapshot can no longer prematurely close a
  live position. Set OCA_CLOSE_ZERO_STREAK=1 to restore the old single-read
  behavior; raise it (3+) for a stricter guard.

2 anchored, idempotent edits to ONE file (.v403bak backup, reversible).
  EDIT backend/services/position_manager.py
    1) loop-top: reset _oca_zero_streak when IB shows any shares
    2) externally-closed branch: defer close until the streak is met

HASH GUARDS (built against live DGX bytes):
  PRE_SHA256  = 6752423e3694ef2a93875bed1f00c99035eb27ae29ad7d87ab6a56e4a67b9126
  POST_SHA256 = f23a1fa85d5ebedc68d6b0cff0c36fa2c4efdbf3251acd5ccf61077c28590b9b

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v403_oca_close_debounce.py --check
    .venv/bin/python backend/scripts/patch_v403_oca_close_debounce.py --apply
    .venv/bin/python backend/scripts/patch_v403_oca_close_debounce.py --rollback
After --apply:  commit, then ./start_backend.sh --force (backend-only).

On a PRE_SHA mismatch (DGX drift), NOTHING changes. Upload your live copy:
  gzip -9 -c backend/services/position_manager.py | base64 -w0 | curl --data-binary @- https://paste.rs/
and send the link so the edits can be rebased.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse
import py_compile

BAK = ".v403bak"
TARGET = "backend/services/position_manager.py"
PRE_SHA = "6752423e3694ef2a93875bed1f00c99035eb27ae29ad7d87ab6a56e4a67b9126"
POST_SHA = "f23a1fa85d5ebedc68d6b0cff0c36fa2c4efdbf3251acd5ccf61077c28590b9b"
APPLIED_MARKER = "v402b OCA debounce"

OLD_B = base64.b64decode(
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWJfcXR5X215X2RpciA9IGliX3Bvc19tYXAuZ2V0KC"
    "hfc3ltX3UsIF9kaXIpLCAwKQogICAgICAgICAgICAgICAgICAgICAgICBpYl9xdHlfb3BwX2Rp"
    "ciA9IGliX3Bvc19tYXAuZ2V0KChfc3ltX3UsIG9wcCksIDApCg=="
).decode("utf-8")
NEW_B = base64.b64decode(
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWJfcXR5X215X2RpciA9IGliX3Bvc19tYXAuZ2V0KC"
    "hfc3ltX3UsIF9kaXIpLCAwKQogICAgICAgICAgICAgICAgICAgICAgICBpYl9xdHlfb3BwX2Rp"
    "ciA9IGliX3Bvc19tYXAuZ2V0KChfc3ltX3UsIG9wcCksIDApCiAgICAgICAgICAgICAgICAgIC"
    "AgICAgICMgdjQwMmIgLS0gcmVzZXQgT0NBIHplcm8tc2hhcmUgZGVib3VuY2Ugc3RyZWFrIHRo"
    "ZQogICAgICAgICAgICAgICAgICAgICAgICAjIG1vbWVudCBJQiByZXBvcnRzIEFOWSBzaGFyZX"
    "MgKGVpdGhlciBzaWRlKSwgc28gYQogICAgICAgICAgICAgICAgICAgICAgICAjIG9uZS10aWNr"
    "IHRyYW5zaWVudCAwLXNuYXBzaG90IGNhbiBuZXZlciBhY2N1bXVsYXRlLgogICAgICAgICAgIC"
    "AgICAgICAgICAgICBpZiBub3QgKGliX3F0eV9teV9kaXIgPT0gMCBhbmQgaWJfcXR5X29wcF9k"
    "aXIgPT0gMCk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBnZXRhdHRyKF90cmFkZS"
    "wgIl9vY2FfemVyb19zdHJlYWsiLCAwKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF90cmFkZS5fb2NhX3"
    "plcm9fc3RyZWFrID0gMAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MK"
).decode("utf-8")
OLD_A = base64.b64decode(
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGFnZV9va19lOgogICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICMgdjE5LjMxLjEyIOKAlCBjbGFpbSBJQiByZWFsaXplZFBOTCBv"
    "bnRvCg=="
).decode("utf-8")
NEW_A = base64.b64decode(
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGFnZV9va19lOgogICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICMgLS0gdjQwMmIgKDIwMjYtMDYtMjMpIE9DQSBjbG9zZSBERUJP"
    "VU5DRSAtLQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICMgZGlhZ19vY2FfY2xvc2"
    "VfdHJhbnNpZW50X3ZzX3JlZW50cnkucHkgcHJvdmVkCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIyBGT1hBL0tSL0xVTFUgd2VyZSBtYXJrZWQgb2NhX2Nsb3NlZF9leHRlcm5hbG"
    "x5CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyAzMC02MHMgYWZ0ZXIgYSBGUkVT"
    "SCBmaWxsIHdoaWxlIHRoZSBmaWxsIHRhcGUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AgICAjIHNob3dlZCB0aGUgcG9zaXRpb24gZnVsbHkgaGVsZCAoemVybyBjb3ZlcgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICMgZmlsbHMpIC0tIGEgdHJhbnNpZW50IElCIDAtc2"
    "hhcmUgc25hcHNob3QuCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyBSZXF1aXJl"
    "IE4gQ09OU0VDVVRJVkUgemVyby1ib3RoLWRpciByZWFkcwogICAgICAgICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICMgYmVmb3JlIGNsb3NpbmcuIE9DQV9DTE9TRV9aRVJPX1NUUkVBSyBkZWZh"
    "dWx0CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyAyIChzZXQgMSB0byBkaXNhYm"
    "xlKS4gU3RyZWFrIHJlc2V0cyBhdCBsb29wIHRvcC4KICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBpbXBvcnQgb3MgYXMgX29zX2RlYgogICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX25lZWRfemVy"
    "byA9IGludChfb3NfZGViLmVudmlyb24uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICAgIk9DQV9DTE9TRV9aRVJPX1NUUkVBSyIsICIyIikpCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IChUeXBlRXJyb3IsIFZhbHVlRXJyb3IpOgogIC"
    "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfbmVlZF96ZXJvID0gMgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIF96ZXJvX3N0cmVhayA9IGludCgKICAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICAgICAgICAgZ2V0YXR0cihfdHJhZGUsICJfb2NhX3plcm9fc3Ry"
    "ZWFrIiwgMCkgb3IgMCkgKyAxCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdHJ5Og"
    "ogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfdHJhZGUuX29jYV96ZXJvX3N0"
    "cmVhayA9IF96ZXJvX3N0cmVhawogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2"
    "VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfemVyb19zdHJlYWsgPCBtYXgoMS"
    "wgX25lZWRfemVybyk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxvZ2dl"
    "ci5pbmZvKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlt2NDAyYi"
    "BPQ0EgZGVib3VuY2VdICVzIHplcm8tc2hhcmUgIgogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgInJlYWQgJWQvJWQgLS0gZGVmZXJyaW5nIGV4dGVybmFsLWNsb3NlIC"
    "IKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICIodHJhbnNpZW50IHNu"
    "YXBzaG90IGd1YXJkKS4iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AgX3RyYWRlLnN5bWJvbCwgX3plcm9fc3RyZWFrLCBfbmVlZF96ZXJvKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgICAgIC"
    "AgICAgICAgICMgdjE5LjMxLjEyIOKAlCBjbGFpbSBJQiByZWFsaXplZFBOTCBvbnRvCg=="
).decode("utf-8")


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
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
    print("  v403 -- OCA externally-closed sweep DEBOUNCE (OCA_CLOSE_ZERO_STREAK)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print(f"  MISSING FILE: {TARGET}")
        sys.exit(2)

    if args.rollback:
        bak = p + BAK
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            ok = "matches PRE_SHA" if sha_full(p) == PRE_SHA else "sha unexpected"
            print(f"  restored {TARGET}  sha={sha_full(p)[:12]}  {ok}")
        else:
            print(f"  no backup ({BAK}); nothing to restore.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur = sha_full(p)
    state = "ALREADY-APPLIED" if cur == POST_SHA else ("READY" if cur == PRE_SHA else "DRIFT")
    print(f"\n  file   : {TARGET}")
    print(f"    sha     : {cur[:12]}")
    print(f"    PRE_SHA : {PRE_SHA[:12]}  POST_SHA: {POST_SHA[:12]}")
    print(f"    state   : {state}")

    if state == "DRIFT":
        print("\n  DRIFT: live file matches neither PRE nor POST. Do NOT --force.")
        print(f"     gzip -9 -c {TARGET} | base64 -w0 | curl --data-binary @- https://paste.rs/")
        sys.exit(3)

    src = open(p, encoding="utf-8").read()
    applied = APPLIED_MARKER in src
    cB, cA = src.count(OLD_B), src.count(OLD_A)
    print(f"\n  [edit1 loop-top reset]      anchor x{cB}")
    print(f"  [edit2 close-branch debounce] anchor x{cA}")
    if args.check:
        if applied:
            print("\n  CHECK ok. already applied.")
        elif cB == 1 and cA == 1:
            print("\n  CHECK ok. 2 edits ready. Re-run with --apply.")
        else:
            print("\n  anchors not uniquely found -- ABORT.")
            sys.exit(3)
        return

    if applied or state == "ALREADY-APPLIED":
        print("\n  Nothing to do -- already at POST_SHA.")
        return
    if cB != 1 or cA != 1:
        print("\n  anchors not uniquely found -- ABORT (no change).")
        sys.exit(3)

    bak = p + BAK
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    out = src.replace(OLD_B, NEW_B, 1).replace(OLD_A, NEW_A, 1)
    open(p, "w", encoding="utf-8").write(out)
    try:
        py_compile.compile(p, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, p)
        print(f"  py_compile FAILED -- reverted.\n   {e}")
        sys.exit(6)
    post = sha_full(p)
    if post == POST_SHA:
        print(f"\n  patched {TARGET}  sha={post[:12]}  ({BAK} saved)  POST verified.")
    else:
        shutil.copy2(bak, p)
        print(f"  POST_SHA MISMATCH expected {POST_SHA[:12]} got {post[:12]} -- reverted.")
        sys.exit(5)
    print("\n  APPLY complete. 2 edits.  Default OCA_CLOSE_ZERO_STREAK=2.")
    print("  NEXT (commit BEFORE restart):")
    print("    git add -A && git commit -m 'v403: OCA externally-closed sweep debounce' && git push origin main")
    print("    ./start_backend.sh --force   (backend-only)")


if __name__ == "__main__":
    main()
