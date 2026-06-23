#!/usr/bin/env python3
r"""
patch_v402_stale_alert_fail_closed.py — Stale-alert gate · fail-OPEN -> fail-CLOSED (v402).

WHY (proven by diag_open_trades_provenance.py / code audit on live DGX)
  Both staleness gates SKIPPED their check (and the trade EXECUTED) whenever the
  alert/trade timestamp was missing or unparseable:
    * opportunity_evaluator.py (v19.34.44 30s TTL): `if _triggered_unix is not
      None:` — no timestamp => no check => fires.
    * trade_execution.py (per-timeframe gate): falsy `if trade.created_at:` OR an
      unparseable created_at (except: log + continue) => fires.
  That is the only genuine "stale alert fired" hole — the daily/carry-forward
  trades flagged by the provenance diag were NOT stale (the gate keys on
  triggered_at, re-stamped each scan cycle; created_at is just a first-seen label).

FIX (BACKEND-ONLY, env-gated, reversible) — STALE_ALERT_POLICY:
    block   (DEFAULT) — missing/unparseable timestamp => REJECT (fail-CLOSED).
    observe           — log only, still fires (measure how often it would block).
    off               — legacy fail-OPEN behavior.
  Flip live without a rebuild: set STALE_ALERT_POLICY in backend/.env and restart.

2 anchored, idempotent edits across 2 files (.v402bak backups, reversible).
  EDIT backend/services/opportunity_evaluator.py  (30s TTL gate)
  EDIT backend/services/trade_execution.py        (per-timeframe gate)

HASH GUARDS (built against live DGX bytes; each edit verified independently):
  backend/services/opportunity_evaluator.py
    PRE_SHA256  = 0dc997f3e98be5217a803741fe85244ec71183fccfd2755ab757e124b8468d3f
    POST_SHA256 = ad1b2c07c6443444f5bb4c3cacef2da1af33be1c0c8c50c443bb116263406d43
  backend/services/trade_execution.py
    PRE_SHA256  = 5a349f9deb62ca192134b61cd3ba76d8905003ed2341efaeb291370b30c35a01
    POST_SHA256 = 7a685d082079b4048f8cb60d6d2eebe739a5b730949cff2d59541a51c9b100b5

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v402_stale_alert_fail_closed.py --check
    .venv/bin/python backend/scripts/patch_v402_stale_alert_fail_closed.py --apply
    .venv/bin/python backend/scripts/patch_v402_stale_alert_fail_closed.py --rollback
After --apply:  commit, then ./start_backend.sh --force (backend-only).
Default policy is BLOCK. To run log-only first:  add STALE_ALERT_POLICY=observe to backend/.env.

On a PRE_SHA mismatch (DGX drift) for either file, NOTHING is changed (atomic:
all edits must be READY/APPLIED). Upload the drifted file:
  gzip -9 -c <file> | base64 -w0 | curl --data-binary @- https://paste.rs/
and send the link so the edit can be rebased.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse
import py_compile

EDITS = [
    {
        "target": "backend/services/opportunity_evaluator.py",
        "bak": ".v402bak",
        "pre": "0dc997f3e98be5217a803741fe85244ec71183fccfd2755ab757e124b8468d3f",
        "post": "ad1b2c07c6443444f5bb4c3cacef2da1af33be1c0c8c50c443bb116263406d43",
        "marker": "v402 stale-policy",
        "label": "[evaluator 30s TTL gate]",
        "old_b64": (
        "ICAgICAgICAgICAgICAgICAgICBpZiBfdHJpZ2dlcmVkX3VuaXggaXMgbm90IE5vbmU6CiAgIC"
        "AgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9h"
        "Z2UgPSBfdGltZV90dGwudGltZSgpIC0gZmxvYXQoX3RyaWdnZXJlZF91bml4KQogICAgICAgIC"
        "AgICAgICAgICAgICAgICBleGNlcHQgKFR5cGVFcnJvciwgVmFsdWVFcnJvcik6CiAgICAgICAg"
        "ICAgICAgICAgICAgICAgICAgICBfYWdlID0gMC4wCg=="
        ),
        "new_b64": (
        "ICAgICAgICAgICAgICAgICAgICAjIHY0MDIg4oCUIGZhaWwtQ0xPU0VEIG9uIG1pc3NpbmcvdW"
        "5wYXJzZWFibGUgYWxlcnQgdGltZXN0YW1wLgogICAgICAgICAgICAgICAgICAgICMgUHJlLWZp"
        "eCB0aGlzIGJyYW5jaCB3YXMgc2tpcHBlZCB3aGVuIG5vIHRpbWVzdGFtcCBleGlzdGVkCiAgIC"
        "AgICAgICAgICAgICAgICAgIyAoZmFpbC1PUEVOKS4gU1RBTEVfQUxFUlRfUE9MSUNZID0gYmxv"
        "Y2t8b2JzZXJ2ZXxvZmYuCiAgICAgICAgICAgICAgICAgICAgX3N0YWxlX3BvbGljeSA9IF9vc1"
        "90dGwuZW52aXJvbi5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJTVEFMRV9BTEVSVF9Q"
        "T0xJQ1kiLCAiYmxvY2siKS5zdHJpcCgpLmxvd2VyKCkKICAgICAgICAgICAgICAgICAgICBpZi"
        "BfdHJpZ2dlcmVkX3VuaXggaXMgTm9uZSBhbmQgX3N0YWxlX3BvbGljeSBpbiAoImJsb2NrIiwg"
        "Im9ic2VydmUiKToKICAgICAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLndhcm5pbmcoCiAgIC"
        "AgICAgICAgICAgICAgICAgICAgICAgICAiXFUwMDAxZjU1MiBbdjQwMiBzdGFsZS1wb2xpY3k9"
        "JXNdICVzICVzIGhhcyBOTyB1c2FibGUgIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgIm"
        "FsZXJ0IHRpbWVzdGFtcCBcdTIwMTQgdHJlYXRpbmcgYXMgU1RBTEUuIiwKICAgICAgICAgICAg"
        "ICAgICAgICAgICAgICAgIF9zdGFsZV9wb2xpY3ksIHN5bWJvbCwgc2V0dXBfdHlwZSwKICAgIC"
        "AgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBfc3RhbGVf"
        "cG9saWN5ID09ICJibG9jayI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBfdHJpZ2dlcm"
        "VkX3VuaXggPSBfdGltZV90dGwudGltZSgpIC0gKF90dGxfc2VjcyArIDEuMCkKICAgICAgICAg"
        "ICAgICAgICAgICBpZiBfdHJpZ2dlcmVkX3VuaXggaXMgbm90IE5vbmU6CiAgICAgICAgICAgIC"
        "AgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9hZ2UgPSBfdGlt"
        "ZV90dGwudGltZSgpIC0gZmxvYXQoX3RyaWdnZXJlZF91bml4KQogICAgICAgICAgICAgICAgIC"
        "AgICAgICBleGNlcHQgKFR5cGVFcnJvciwgVmFsdWVFcnJvcik6CiAgICAgICAgICAgICAgICAg"
        "ICAgICAgICAgICBfYWdlID0gMC4wCg=="
        ),
    },
    {
        "target": "backend/services/trade_execution.py",
        "bak": ".v402bak",
        "pre": "5a349f9deb62ca192134b61cd3ba76d8905003ed2341efaeb291370b30c35a01",
        "post": "7a685d082079b4048f8cb60d6d2eebe739a5b730949cff2d59541a51c9b100b5",
        "marker": "v402 stale-policy",
        "label": "[execution timeframe gate]",
        "old_b64": (
        "ICAgICAgICBpZiB0cmFkZS5jcmVhdGVkX2F0OgogICAgICAgICAgICB0cnk6CiAgICAgICAgIC"
        "AgICAgICBjcmVhdGVkID0gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh0cmFkZS5jcmVhdGVkX2F0"
        "LnJlcGxhY2UoJ1onLCAnKzAwOjAwJykpCiAgICAgICAgICAgICAgICBhZ2UgPSAoZGF0ZXRpbW"
        "Uubm93KHRpbWV6b25lLnV0YykgLSBjcmVhdGVkKS50b3RhbF9zZWNvbmRzKCkKICAgICAgICAg"
        "ICAgICAgIGlmIGFnZSA+IG1heF9hZ2Vfc2Vjb25kczoKICAgICAgICAgICAgICAgICAgICBsb2"
        "dnZXIuaW5mbyhmIlN0YWxlIGFsZXJ0OiB7dHJhZGUuc3ltYm9sfSB7dHJhZGUuc2V0dXBfdHlw"
        "ZX0gaXMge2FnZTouMGZ9cyBvbGQgKG1heCB7bWF4X2FnZV9zZWNvbmRzfXMgZm9yIHt0cmFkZS"
        "50aW1lZnJhbWV9KSIpCiAgICAgICAgICAgICAgICAgICAgdHJhZGUuc3RhdHVzID0gVHJhZGVT"
        "dGF0dXMuUkVKRUNURUQKICAgICAgICAgICAgICAgICAgICB0cmFkZS5ub3RlcyA9ICh0cmFkZS"
        "5ub3RlcyBvciAiIikgKyBmIiBbRVhQSVJFRDoge2FnZTouMGZ9cyBvbGRdIgogICAgICAgICAg"
        "ICAgICAgICAgIGRlbCBib3QuX3BlbmRpbmdfdHJhZGVzW3RyYWRlX2lkXQogICAgICAgICAgIC"
        "AgICAgICAgIGF3YWl0IGJvdC5fbm90aWZ5X3RyYWRlX3VwZGF0ZSh0cmFkZSwgImV4cGlyZWQi"
        "KQogICAgICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgICAgICBleGNlcHQgRX"
        "hjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBsb2dnZXIud2FybmluZygKICAgICAgICAg"
        "ICAgICAgICAgICAiQ291bGQgbm90IGNoZWNrIGFsZXJ0IGFnZSAoJXMpOiAlcyIsCiAgICAgIC"
        "AgICAgICAgICAgICAgdHlwZShlKS5fX25hbWVfXywgZSwgZXhjX2luZm89VHJ1ZSwKICAgICAg"
        "ICAgICAgICAgICkK"
        ),
        "new_b64": (
        "ICAgICAgICAjIHY0MDIg4oCUIGZhaWwtQ0xPU0VEIHN0YWxlbmVzcy4gUHJlLWZpeCBhIG1pc3"
        "NpbmcgY3JlYXRlZF9hdCAoZmFsc3kKICAgICAgICAjIGBpZiB0cmFkZS5jcmVhdGVkX2F0OmAp"
        "IE9SIGFuIHVucGFyc2VhYmxlIG9uZSAoZXhjZXB0OiBsb2crY29udGludWUpCiAgICAgICAgIy"
        "Bib3RoIGZlbGwgdGhyb3VnaCBhbmQgRVhFQ1VURUQuIFNUQUxFX0FMRVJUX1BPTElDWSA9IGJs"
        "b2NrfG9ic2VydmV8b2ZmLgogICAgICAgIGltcG9ydCBvcyBhcyBfb3Nfc3RhbGUKICAgICAgIC"
        "Bfc3RhbGVfcG9saWN5ID0gX29zX3N0YWxlLmVudmlyb24uZ2V0KCJTVEFMRV9BTEVSVF9QT0xJ"
        "Q1kiLCAiYmxvY2siKS5zdHJpcCgpLmxvd2VyKCkKICAgICAgICBfdHNfb2sgPSBGYWxzZQogIC"
        "AgICAgIGFnZSA9IE5vbmUKICAgICAgICBpZiB0cmFkZS5jcmVhdGVkX2F0OgogICAgICAgICAg"
        "ICB0cnk6CiAgICAgICAgICAgICAgICBjcmVhdGVkID0gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdC"
        "h0cmFkZS5jcmVhdGVkX2F0LnJlcGxhY2UoJ1onLCAnKzAwOjAwJykpCiAgICAgICAgICAgICAg"
        "ICBhZ2UgPSAoZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgLSBjcmVhdGVkKS50b3RhbF9zZW"
        "NvbmRzKCkKICAgICAgICAgICAgICAgIF90c19vayA9IFRydWUKICAgICAgICAgICAgZXhjZXB0"
        "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbG9nZ2VyLndhcm5pbmcoCiAgICAgIC"
        "AgICAgICAgICAgICAgIkNvdWxkIG5vdCBwYXJzZSBhbGVydCB0aW1lc3RhbXAgKCVzKTogJXMi"
        "LAogICAgICAgICAgICAgICAgICAgIHR5cGUoZSkuX19uYW1lX18sIGUsIGV4Y19pbmZvPVRydW"
        "UsCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3JlamVjdCA9IEZhbHNlCiAgICAgICAgX3do"
        "eSA9ICIiCiAgICAgICAgaWYgX3RzX29rIGFuZCBhZ2UgaXMgbm90IE5vbmUgYW5kIGFnZSA+IG"
        "1heF9hZ2Vfc2Vjb25kczoKICAgICAgICAgICAgX3JlamVjdCA9IFRydWUKICAgICAgICAgICAg"
        "X3doeSA9IGYie2FnZTouMGZ9cyBvbGQgKG1heCB7bWF4X2FnZV9zZWNvbmRzfXMgZm9yIHt0cm"
        "FkZS50aW1lZnJhbWV9KSIKICAgICAgICBlbGlmIG5vdCBfdHNfb2sgYW5kIF9zdGFsZV9wb2xp"
        "Y3kgaW4gKCJibG9jayIsICJvYnNlcnZlIik6CiAgICAgICAgICAgIGxvZ2dlci53YXJuaW5nKA"
        "ogICAgICAgICAgICAgICAgIlxVMDAwMWY1NTIgW3Y0MDIgc3RhbGUtcG9saWN5PSVzXSAlcyAl"
        "cyBoYXMgTk8gdXNhYmxlIHRpbWVzdGFtcCAiCiAgICAgICAgICAgICAgICAiXHUyMDE0IHRyZW"
        "F0aW5nIGFzIFNUQUxFLiIsCiAgICAgICAgICAgICAgICBfc3RhbGVfcG9saWN5LCB0cmFkZS5z"
        "eW1ib2wsIHRyYWRlLnNldHVwX3R5cGUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgX3"
        "N0YWxlX3BvbGljeSA9PSAiYmxvY2siOgogICAgICAgICAgICAgICAgX3JlamVjdCA9IFRydWUK"
        "ICAgICAgICAgICAgICAgIF93aHkgPSAibm8gdXNhYmxlIHRpbWVzdGFtcCAoZmFpbC1jbG9zZW"
        "QpIgogICAgICAgIGlmIF9yZWplY3Q6CiAgICAgICAgICAgIGxvZ2dlci5pbmZvKGYiU3RhbGUg"
        "YWxlcnQ6IHt0cmFkZS5zeW1ib2x9IHt0cmFkZS5zZXR1cF90eXBlfSB7X3doeX0iKQogICAgIC"
        "AgICAgICB0cmFkZS5zdGF0dXMgPSBUcmFkZVN0YXR1cy5SRUpFQ1RFRAogICAgICAgICAgICB0"
        "cmFkZS5ub3RlcyA9ICh0cmFkZS5ub3RlcyBvciAiIikgKyBmIiBbRVhQSVJFRDoge193aHl9XS"
        "IKICAgICAgICAgICAgZGVsIGJvdC5fcGVuZGluZ190cmFkZXNbdHJhZGVfaWRdCiAgICAgICAg"
        "ICAgIGF3YWl0IGJvdC5fbm90aWZ5X3RyYWRlX3VwZGF0ZSh0cmFkZSwgImV4cGlyZWQiKQogIC"
        "AgICAgICAgICByZXR1cm4gRmFsc2UK"
        ),
    }
]


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def classify(e):
    p = resolve(e["target"])
    if not os.path.exists(p):
        return p, "MISSING"
    s = sha_full(p)
    if s == e["post"]:
        return p, "ALREADY-APPLIED"
    if s == e["pre"]:
        return p, "READY"
    return p, "DRIFT"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  v402 — stale-alert gates: fail-OPEN -> fail-CLOSED (STALE_ALERT_POLICY)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for e in EDITS:
            p = resolve(e["target"])
            bak = p + e["bak"]
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                ok = "matches PRE" if sha_full(p) == e["pre"] else "sha unexpected"
                print(f"  restored {e['target']}  sha={sha_full(p)[:12]}  {ok}")
            else:
                print(f"  no backup ({e['bak']}) for {e['target']}; skipped.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    states = []
    for e in EDITS:
        p, st = classify(e)
        states.append(st)
        print(f"\n  {e['target']}  {e['label']}")
        print(f"    sha    : {sha_full(p)[:12]}")
        print(f"    PRE    : {e['pre'][:12]}  POST: {e['post'][:12]}")
        print(f"    state  : {st}")

    if "MISSING" in states:
        print("\n  ABORT: a target file is missing.")
        sys.exit(2)
    if "DRIFT" in states:
        print("\n  DRIFT: a file matches neither PRE nor POST. NOTHING changed (atomic).")
        for e, st in zip(EDITS, states):
            if st == "DRIFT":
                print(f"    upload: gzip -9 -c {e['target']} | base64 -w0 | curl --data-binary @- https://paste.rs/")
        sys.exit(3)

    n_ready = states.count("READY")
    if args.check:
        print(f"\n  CHECK ok. {n_ready} edit(s) ready, {states.count('ALREADY-APPLIED')} already applied.")
        if n_ready:
            print("  Re-run with --apply.")
        return

    if n_ready == 0:
        print("\n  Nothing to do — all edits already at POST_SHA.")
        return

    # apply each READY edit; verify POST; revert ALL on any failure
    done = []
    for e in EDITS:
        p, st = classify(e)
        if st != "READY":
            continue
        old = base64.b64decode(e["old_b64"]).decode("utf-8")
        new = base64.b64decode(e["new_b64"]).decode("utf-8")
        src = open(p, encoding="utf-8").read()
        if src.count(old) != 1:
            print(f"  anchor not unique in {e['target']} — ABORT, reverting.")
            _revert(done)
            sys.exit(3)
        bak = p + e["bak"]
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(src.replace(old, new, 1))
        try:
            py_compile.compile(p, doraise=True)
        except py_compile.PyCompileError as ex:
            shutil.copy2(bak, p)
            print(f"  py_compile FAILED on {e['target']} — reverted.\n   {ex}")
            _revert(done)
            sys.exit(6)
        if sha_full(p) != e["post"]:
            shutil.copy2(bak, p)
            print(f"  POST_SHA MISMATCH on {e['target']} — reverted.")
            _revert(done)
            sys.exit(5)
        print(f"  patched {e['target']}  sha={sha_full(p)[:12]}  (verified)")
        done.append(e)

    print(f"\n  APPLY complete. {len(done)} edit(s).  Default policy: BLOCK (fail-closed).")
    print("  NEXT (commit BEFORE restart):")
    print("    git add -A && git commit -m 'v402: stale-alert gates fail-closed (STALE_ALERT_POLICY)' && git push origin main")
    print("    ./start_backend.sh --force   (backend-only)")


def _revert(done):
    for e in done:
        p = resolve(e["target"])
        bak = p + e["bak"]
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            print(f"    reverted {e['target']}")


if __name__ == "__main__":
    main()
