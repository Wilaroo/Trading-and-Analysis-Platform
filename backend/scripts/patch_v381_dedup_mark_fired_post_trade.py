#!/usr/bin/env python3
"""patch_v381_dedup_mark_fired_post_trade.py
=============================================
Issue 4 fix — stop the dedup cooldown from blocking legitimate re-evaluations.

ROOT CAUSE (proven by diag_v380 on live DGX data, 7d):
  `_dedup.mark_fired(symbol, setup, direction)` was called in the bot loop
  BEFORE evaluation, so EVERY alert that passed the dedup/position checks
  started the 300s (symbol,setup,dir) cooldown — even when it was REJECTED
  downstream (smart_filter / confidence gate / no-price / …) and never opened a
  trade. Result: 92.9% of all dedup_cooldown blocks (20,567 in 7d; HON 96.4%)
  were keys that NEVER traded that day — the cooldown silently suppressed
  re-evaluation of trending names for 5 minutes at a time.

FIX (1 file, fully reversible):
  D1  REMOVE the pre-evaluation mark_fired (replace with an explanatory comment).
  D2  ADD mark_fired inside the `if trade:` block — the cooldown now starts ONLY
      when a real trade is created. Marking before `_execute_trade` still blocks
      a duplicate same-key alert later in the SAME batch, and the existing
      open-position + pending checks still prevent stacking on a live position
      (preserving the original PRCT anti-stacking intent).

NET: rejected alerts no longer burn the cooldown, so trending setups get
re-evaluated each cycle (fresh chance to fire as conditions change), while real
entries still get the 300s anti-churn guard.

Usage (DGX, repo root):
  .venv/bin/python backend/scripts/patch_v381_dedup_mark_fired_post_trade.py --check
  .venv/bin/python backend/scripts/patch_v381_dedup_mark_fired_post_trade.py --apply
  .venv/bin/python backend/scripts/patch_v381_dedup_mark_fired_post_trade.py --rollback
"""
import base64
import hashlib
import os
import sys
import py_compile

TARGET = "backend/services/trading_bot_service.py"
BAK = TARGET + ".bak.v381"
PRE_SHA = "7344020bcbee515b2a92aea5698d174f3b68157580991854f7920811caa7b51a"
POST_SHA = "a141edb6e170abde13e731b6106d20fee384d5eb594c5ddf168ebfcc59986a2e"

EDITS = [
    # (tag, OLD_B64, NEW_B64)
    ("D1 remove pre-eval mark_fired",
     "ICAgICAgICAgICAgICAgICMgTWFyayBhbGVydCBhcyBmaXJlZCAoc3RhcnRzIGNvb2xkb3duKSBCRUZPUkUgaGVhdnkgZXZhbHVhdGlvbgogICAgICAgICAgICAgICAgX2RlZHVwLm1hcmtfZmlyZWQoc3ltYm9sLCBzZXR1cCwgZGlyZWN0aW9uKQo=",
     "ICAgICAgICAgICAgICAgICMgdjM4MCDigJQgbWFya19maXJlZCBNT1ZFRCB0byBBRlRFUiBhIHRyYWRlIGlzIGNyZWF0ZWQgKHRoZQogICAgICAgICAgICAgICAgIyBgaWYgdHJhZGU6YCBibG9jayBiZWxvdykuIEl0IHVzZWQgdG8gc3RhcnQgdGhlIDMwMHMKICAgICAgICAgICAgICAgICMgKHN5bWJvbCxzZXR1cCxkaXIpIGNvb2xkb3duIEhFUkUsIGJlZm9yZSBldmFsdWF0aW9uLCBzbyBldmVyeQogICAgICAgICAgICAgICAgIyBhbGVydCBsYXRlciBSRUpFQ1RFRCBkb3duc3RyZWFtIHN0aWxsIGJ1cm5lZCB0aGUgY29vbGRvd24g4oCUCiAgICAgICAgICAgICAgICAjIGRpYWdfdjM4MDogOTIuOSUgb2YgZGVkdXBfY29vbGRvd24gYmxvY2tzIChIT04gOTYuNCUpIHdlcmUKICAgICAgICAgICAgICAgICMga2V5cyB0aGF0IE5FVkVSIHRyYWRlZCwgc2lsZW50bHkgc3VwcHJlc3NpbmcgcmUtZXZhbHVhdGlvbiBvbgogICAgICAgICAgICAgICAgIyB0cmVuZGluZyBuYW1lcy4gVGhlIG9wZW4tcG9zaXRpb24gKyBwZW5kaW5nIGNoZWNrcyBhYm92ZSBzdGlsbAogICAgICAgICAgICAgICAgIyBwcmV2ZW50IHN0YWNraW5nIG9uIGEgbGl2ZSBwb3NpdGlvbi4K"),
    ("D2 add mark_fired in if-trade",
     "ICAgICAgICAgICAgICAgIGlmIHRyYWRlOgogICAgICAgICAgICAgICAgICAgIHByaW50KGYi4pyFIFtUcmFkaW5nQm90XSBUcmFkZSBjcmVhdGVkIGZvciB7c3ltYm9sfToge3RyYWRlLmRpcmVjdGlvbi52YWx1ZX0ge3RyYWRlLnNoYXJlc30gc2hhcmVzIEAgJHt0cmFkZS5lbnRyeV9wcmljZTouMmZ9IikK",
     "ICAgICAgICAgICAgICAgIGlmIHRyYWRlOgogICAgICAgICAgICAgICAgICAgICMgdjM4MCDigJQgc3RhcnQgdGhlIChzeW1ib2wsc2V0dXAsZGlyKSBjb29sZG93biBIRVJFOiBhIHJlYWwKICAgICAgICAgICAgICAgICAgICAjIHRyYWRlIHdhcyBjcmVhdGVkLiBBbHNvIHN0b3BzIGEgZHVwbGljYXRlIHNhbWUta2V5IGFsZXJ0CiAgICAgICAgICAgICAgICAgICAgIyBsYXRlciBpbiB0aGlzIHNhbWUgYmF0Y2ggZnJvbSBvcGVuaW5nIGEgc2Vjb25kIHRyYWRlCiAgICAgICAgICAgICAgICAgICAgIyBiZWZvcmUgdGhlIG9wZW4vcGVuZGluZyBkaWN0cyByZWZsZWN0IHRoaXMgb25lLgogICAgICAgICAgICAgICAgICAgIF9kZWR1cC5tYXJrX2ZpcmVkKHN5bWJvbCwgc2V0dXAsIGRpcmVjdGlvbikKICAgICAgICAgICAgICAgICAgICBwcmludChmIuKchSBbVHJhZGluZ0JvdF0gVHJhZGUgY3JlYXRlZCBmb3Ige3N5bWJvbH06IHt0cmFkZS5kaXJlY3Rpb24udmFsdWV9IHt0cmFkZS5zaGFyZXN9IHNoYXJlcyBAICR7dHJhZGUuZW50cnlfcHJpY2U6LjJmfSIpCg=="),
]


def _d(b64):
    return base64.b64decode(b64).decode("utf-8")


def _resolve():
    if os.path.exists(TARGET):
        return TARGET
    alt = TARGET.replace("backend/", "")
    return alt if os.path.exists(alt) else TARGET


def main():
    path = _resolve()
    bak = path + ".bak.v381" if path != TARGET else BAK

    if "--rollback" in sys.argv:
        if os.path.exists(bak):
            open(path, "w", encoding="utf-8").write(open(bak, encoding="utf-8").read())
            print(f"restored {path} from {bak}")
        else:
            print(f"no backup {bak}")
        return

    apply_mode = "--apply" in sys.argv
    force = "--force" in sys.argv
    src = open(path, encoding="utf-8").read()
    cur = hashlib.sha256(src.encode()).hexdigest()
    print(f"target        : {path}")
    print(f"whole-file SHA: {cur}")
    print(f"expected PRE  : {PRE_SHA}  {'OK' if cur == PRE_SHA else 'MISMATCH'}")
    if cur == POST_SHA:
        print("Already applied (file matches POST-SHA). Nothing to do.")
        return

    out = src
    ok = True
    for tag, old_b64, new_b64 in EDITS:
        old = _d(old_b64)
        n = src.count(old)
        flag = "OK" if n == 1 else "FAIL"
        if n != 1:
            ok = False
        print(f"  [{flag}] {tag:<32} anchor count = {n} (need 1)")
        if n == 1:
            out = out.replace(old, _d(new_b64), 1)
    try:
        compile(out, path, "exec")
        print("  patched syntax : compile OK")
    except SyntaxError as e:
        print(f"  patched syntax : COMPILE ERROR: {e}")
        ok = False
    got = hashlib.sha256(out.encode()).hexdigest()
    print(f"  would-be POST  : {got}  {'OK' if got == POST_SHA else '(differs from tested build)'}")

    if cur != PRE_SHA and not force:
        ok = False
        print("  PRE-SHA mismatch — re-extract or use --force if anchors are all 1.")
    if not ok and not force:
        sys.exit("\nABORT: checks failed. No file written.")
    if not apply_mode:
        print("\n--check complete. Re-run with --apply.")
        return

    open(bak, "w", encoding="utf-8").write(src)
    open(path, "w", encoding="utf-8").write(out)
    print(f"\nAPPLIED {path} (backup {bak}). POST SHA: {got}")
    try:
        py_compile.compile(path, doraise=True)
        print("py_compile: OK")
    except py_compile.PyCompileError as e:
        open(path, "w", encoding="utf-8").write(src)
        sys.exit(f"py_compile FAILED — restored original.\n{e}")
    print("\n✅ v381 applied. Restart backend/scanner to load.")
    print("   Verify with diag_v380 after an RTH cycle (BLOCKED_NO_TRADE_DAY should collapse).")
    print("   Rollback: --rollback")


if __name__ == "__main__":
    main()
