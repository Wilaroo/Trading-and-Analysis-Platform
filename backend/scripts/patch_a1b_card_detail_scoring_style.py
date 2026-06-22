#!/usr/bin/env python3
r"""
patch_a1b_card_detail_scoring_style.py — UI Track A · A1b (v19.34.280).

The TQS drill-down drawer already reads `detail.scoring_style`
(TqsDrillDownDrawer.jsx) to stamp how a trade was scored, but
GET /api/tqs/card-detail/{symbol} never returned it — so the drawer fell back
to a setup-derived GUESS. The P1 fix persists the exact pattern scoring lens as
`tqs_breakdown.scoring_style` (alerts) / `entry_context.tqs.breakdown.scoring_style`
(positions). This surfaces that persisted value in the endpoint so the drawer
shows the precise "scored as" stamp. Empty (legacy/pre-P1 rows) → frontend
gracefully falls back to the setup-derived pattern (current behaviour). No
frontend change needed.

1 file, BACKEND-ONLY, additive, idempotent, reversible (.a1bbak backup).
  EDIT  backend/routers/tqs_router.py

HASH GUARDS (v322t+):  PRE a808dd7c97be…  POST f52dbcd3e151…
Usage (repo root):
    python3 backend/scripts/patch_a1b_card_detail_scoring_style.py --check
    python3 backend/scripts/patch_a1b_card_detail_scoring_style.py --apply
    python3 backend/scripts/patch_a1b_card_detail_scoring_style.py --rollback
After --apply:  ./start_backend.sh --force   (backend-only)

On a PRE mismatch (drift) the patcher ABORTS — upload your live tqs_router.py
and rebase; never --force.
"""
import os, sys, base64, shutil, hashlib, argparse

BAK = ".a1bbak"
TARGET = "backend/routers/tqs_router.py"
PRE_SHA = "a808dd7c97be64eb02cf4e811ef3456edf2ed66af952687de610cdc842e2ec3e"
POST_SHA = "f52dbcd3e151b7489903823e96db7b635a309a6d461607874053c972c9625f03"
OLD_B64 = "ICAgICAgICAidHJhZGVfc3R5bGUiOiByZWMuZ2V0KCJ0cmFkZV9zdHlsZSIpIG9yICIiLAogICAgICAgICJicmVha2Rvd24iOiBicmVha2Rvd24s"
NEW_B64 = "ICAgICAgICAidHJhZGVfc3R5bGUiOiByZWMuZ2V0KCJ0cmFkZV9zdHlsZSIpIG9yICIiLAogICAgICAgICMgdjE5LjM0LjI4MCAoVUkgVHJhY2sgQSAvIEExYikg4oCUIHRoZSBFWEFDVCBwYXR0ZXJuIHNjb3JpbmcgbGVucyBUUVMKICAgICAgICAjIHdlaWdodGVkIHRoaXMgdHJhZGUgd2l0aC4gUDEgcGVyc2lzdHMgaXQgYXMgdHFzX2JyZWFrZG93bi5zY29yaW5nX3N0eWxlCiAgICAgICAgIyAoYWxlcnRzKTsgZm9yIHBvc2l0aW9ucyBpdCdzIG5lc3RlZCB1bmRlciBlbnRyeV9jb250ZXh0LnRxcy5icmVha2Rvd24uCiAgICAgICAgIyBMZXRzIHRoZSBkcmF3ZXIgc2hvdyB0aGUgcHJlY2lzZSAic2NvcmVkIGFzIiBzdGFtcCByYXRoZXIgdGhhbiBhCiAgICAgICAgIyBzZXR1cC1kZXJpdmVkIGd1ZXNzLiBFbXB0eSDihpIgZnJvbnRlbmQgZmFsbHMgYmFjayB0byBzZXR1cC1kZXJpdmVkLgogICAgICAgICJzY29yaW5nX3N0eWxlIjogKAogICAgICAgICAgICAoYnJlYWtkb3duLmdldCgic2NvcmluZ19zdHlsZSIpIGlmIGlzaW5zdGFuY2UoYnJlYWtkb3duLCBkaWN0KSBlbHNlICIiKQogICAgICAgICAgICBvciAoYnJlYWtkb3duLmdldCgiYnJlYWtkb3duIikgb3Ige30gaWYgaXNpbnN0YW5jZShicmVha2Rvd24sIGRpY3QpIGVsc2Uge30pLmdldCgic2NvcmluZ19zdHlsZSIpCiAgICAgICAgICAgIG9yICIiCiAgICAgICAgKSwKICAgICAgICAiYnJlYWtkb3duIjogYnJlYWtkb3duLA=="


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def dec(x):
    return base64.b64decode(x).decode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    a = ap.parse_args()

    print("=" * 84)
    print("  A1b PATCH — card-detail returns persisted scoring_style")
    print("  mode:", "CHECK" if a.check else "APPLY" if a.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print("  MISSING FILE:", TARGET)
        sys.exit(2)

    if a.rollback:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("  restored", TARGET, "sha=" + sha_full(p)[:12])
        else:
            print("  no backup (%s); nothing to restore." % BAK)
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur = sha_full(p)
    state = "ALREADY-APPLIED" if cur == POST_SHA else ("READY" if cur == PRE_SHA else "DRIFT")
    print("\n  %s  sha=%s  state=%s" % (TARGET, cur[:12], state))
    print("  PRE=%s  POST=%s" % (PRE_SHA[:12], POST_SHA[:12]))

    if state == "DRIFT":
        print("\n  DRIFT: matches neither PRE nor POST. Do NOT --force.")
        print("     upload:  curl --data-binary @%s https://paste.rs/" % TARGET)
        sys.exit(3)

    if state == "READY":
        src = open(p, encoding="utf-8").read()
        if src.count(dec(OLD_B64)) != 1:
            print("  anchor not unique — ABORT.")
            sys.exit(3)

    if a.check:
        print("\n  CHECK ok. %s" % ("nothing to do (applied)." if state == "ALREADY-APPLIED" else "ready — re-run with --apply."))
        return

    if state == "ALREADY-APPLIED":
        print("\n  Nothing to do — already at POST_SHA.")
        return

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    src = open(p, encoding="utf-8").read().replace(dec(OLD_B64), dec(NEW_B64), 1)
    open(p, "w", encoding="utf-8").write(src)
    got = sha_full(p)
    print("  patched %s  sha=%s  %s" % (TARGET, got[:12], "POST OK" if got == POST_SHA else "MISMATCH"))
    if got != POST_SHA:
        sys.exit(5)
    print("\n  APPLY complete. NEXT: ./start_backend.sh --force  (backend-only)")


if __name__ == "__main__":
    main()
