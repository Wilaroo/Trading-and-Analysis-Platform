#!/usr/bin/env python3
r"""
patch_v404_card_time_transparency.py — V5 UI · card lifecycle-timestamp transparency.

WHAT
  Surfaces the alert/entry/refreshed/exit timestamps (+ entry price already
  present) on the V5 Open-Position and Scanner cards, so backlogged/stale
  flushes are visible at a glance (this is exactly the triggered_at-vs-created_at
  distinction the recent stale-alert work hinged on).

  OpenPositionsV5.jsx — adds a 4-cell time grid in the expanded row:
        Alert (alert_time|triggered_at|created_at) · Entry (entry_time|
        executed_at|opened_at) · Refreshed (last_update|updated_at) ·
        Exit (exit_time|closed_at). Entry price already shows in the price grid.
  ScannerCardsV5.jsx — carries alert_ts/entry_ts/refreshed_ts onto each card
        and renders a compact "alert HH:MM:SS ET · N ago · refreshed N ago" line.

  Frontend-only, additive, reversible. NO data/logic/order path touched.

EDITS (per-file, byte-anchored; POST_SHA == a babel-validated build):
  EDIT frontend/src/components/sentcom/v5/OpenPositionsV5.jsx   (2 anchors)
  EDIT frontend/src/components/sentcom/v5/ScannerCardsV5.jsx    (4 anchors)

HASH GUARDS (built against live DGX bytes):
  frontend/src/components/sentcom/v5/OpenPositionsV5.jsx
    PRE_SHA256  = 034df1d94fb854d6ab54afe8ef6a351f7413a80c64276a3dcaeb1e41ab005551
    POST_SHA256 = 6533a71227d7ce853c1ef7085a447158b0e72f9f29f3b78362996711c235c6e4
  frontend/src/components/sentcom/v5/ScannerCardsV5.jsx
    PRE_SHA256  = e12859743619efa74d6002be309f9a63409bc6752785e1ec3a83645a6a5619e4
    POST_SHA256 = e159430dac0d7b118f85dc4616be30522b54e8252fc1c2b62886af37e90a5c3e

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v404_card_time_transparency.py --check
    .venv/bin/python backend/scripts/patch_v404_card_time_transparency.py --apply
    .venv/bin/python backend/scripts/patch_v404_card_time_transparency.py --rollback
After --apply (FRONTEND — a rebuild is REQUIRED, AGENTS.md §frontend):
    git add frontend/ && git commit -m "v404: card lifecycle-timestamp transparency" && git push origin main
    cd frontend && yarn build      # then restart the static server / spark_start
POST_SHA is byte-identical to a babel-validated build, so a green checksum == valid JSX.

On a PRE_SHA mismatch (DGX drift) for either file, NOTHING changes (atomic).
Upload the drifted file:
  gzip -9 -c <file> | base64 -w0 | curl --data-binary @- https://paste.rs/
and send the link so the edits can be rebased.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse

FILES = [
    {
        "target": "frontend/src/components/sentcom/v5/OpenPositionsV5.jsx",
        "bak": ".v404bak",
        "pre": "034df1d94fb854d6ab54afe8ef6a351f7413a80c64276a3dcaeb1e41ab005551",
        "post": "6533a71227d7ce853c1ef7085a447158b0e72f9f29f3b78362996711c235c6e4",
        "edits": [
            {
                "old_b64": (
                    "Y29uc3QgZm9ybWF0UHggPSAodikgPT4gewogIGlmICh2ID09IG51bGwgfHwgTnVtYmVyLmlz"
                    "TmFOKE51bWJlcih2KSkpIHJldHVybiAn4oCUJzsKICByZXR1cm4gTnVtYmVyKHYpLnRvRml4"
                    "ZWQoMik7Cn07Cg=="
                ),
                "new_b64": (
                    "Y29uc3QgZm9ybWF0UHggPSAodikgPT4gewogIGlmICh2ID09IG51bGwgfHwgTnVtYmVyLmlz"
                    "TmFOKE51bWJlcih2KSkpIHJldHVybiAn4oCUJzsKICByZXR1cm4gTnVtYmVyKHYpLnRvRml4"
                    "ZWQoMik7Cn07CgovLyB2NDA0ICgyMDI2LTA2LTIzKSDigJQgb3BlcmF0b3IgdHJhbnNwYXJl"
                    "bmN5OiBsaWZlY3ljbGUgdGltZXN0YW1wcwovLyAoYWxlcnQgLT4gZW50cnkgLT4gcmVmcmVz"
                    "aGVkIC0+IGV4aXQpIG9uIGVhY2ggcG9zaXRpb24gc28gYmFja2xvZ2dlZCAvCi8vIHN0YWxl"
                    "IGZsdXNoZXMgYXJlIHZpc2libGUgYXQgYSBnbGFuY2UuIEVUIHdhbGwtY2xvY2sgKyByZWxh"
                    "dGl2ZSBhZ2UuCmNvbnN0IGZtdEVUID0gKHRzKSA9PiB7CiAgaWYgKCF0cykgcmV0dXJuIG51"
                    "bGw7CiAgY29uc3QgZCA9IG5ldyBEYXRlKHRzKTsKICBpZiAoTnVtYmVyLmlzTmFOKGQuZ2V0"
                    "VGltZSgpKSkgcmV0dXJuIG51bGw7CiAgcmV0dXJuIGQudG9Mb2NhbGVUaW1lU3RyaW5nKCdl"
                    "bi1VUycsIHsgdGltZVpvbmU6ICdBbWVyaWNhL05ld19Zb3JrJywgaG91cjEyOiBmYWxzZSB9"
                    "KTsKfTsKY29uc3QgcmVsQWdlID0gKHRzKSA9PiB7CiAgaWYgKCF0cykgcmV0dXJuICcnOwog"
                    "IGNvbnN0IGQgPSBuZXcgRGF0ZSh0cyk7CiAgaWYgKE51bWJlci5pc05hTihkLmdldFRpbWUo"
                    "KSkpIHJldHVybiAnJzsKICBjb25zdCBzID0gTWF0aC5tYXgoMCwgTWF0aC5mbG9vcigoRGF0"
                    "ZS5ub3coKSAtIGQuZ2V0VGltZSgpKSAvIDEwMDApKTsKICBpZiAocyA8IDYwKSByZXR1cm4g"
                    "YCR7c31zYDsKICBpZiAocyA8IDM2MDApIHJldHVybiBgJHtNYXRoLmZsb29yKHMgLyA2MCl9"
                    "bWA7CiAgaWYgKHMgPCA4NjQwMCkgcmV0dXJuIGAke01hdGguZmxvb3IocyAvIDM2MDApfWhg"
                    "OwogIHJldHVybiBgJHtNYXRoLmZsb29yKHMgLyA4NjQwMCl9ZGA7Cn07CmNvbnN0IFRpbWVD"
                    "ZWxsID0gKHsgbGFiZWwsIHRzLCB0b25lIH0pID0+IHsKICBjb25zdCBjbG9jayA9IGZtdEVU"
                    "KHRzKTsKICBjb25zdCBhZ2UgPSByZWxBZ2UodHMpOwogIHJldHVybiAoCiAgICA8ZGl2IGRh"
                    "dGEtdGVzdGlkPXtgdGltZS1jZWxsLSR7U3RyaW5nKGxhYmVsKS50b0xvd2VyQ2FzZSgpfWB9"
                    "PgogICAgICA8ZGl2IGNsYXNzTmFtZT0idGV4dC1bMTNweF0gdXBwZXJjYXNlIHRyYWNraW5n"
                    "LXdpZGVyIHRleHQtemluYy02MDAiPntsYWJlbH08L2Rpdj4KICAgICAgPGRpdiBjbGFzc05h"
                    "bWU9e3RvbmUgfHwgJ3RleHQtemluYy0zMDAnfT4KICAgICAgICB7Y2xvY2sKICAgICAgICAg"
                    "ID8gPD57Y2xvY2t9PHNwYW4gY2xhc3NOYW1lPSJ0ZXh0LXppbmMtNjAwIj4gRVQ8L3NwYW4+"
                    "e2FnZSA/IDxzcGFuIGNsYXNzTmFtZT0idGV4dC16aW5jLTYwMCI+IMK3IHthZ2V9PC9zcGFu"
                    "PiA6IG51bGx9PC8+CiAgICAgICAgICA6ICfigJQnfQogICAgICA8L2Rpdj4KICAgIDwvZGl2"
                    "PgogICk7Cn07Cg=="
                ),
            },
            {
                "old_b64": (
                    "ICAgICAgICAgIHsvKiBSaXNrIC8gc2hhcmVzIHJvdyAqL30K"
                ),
                "new_b64": (
                    "ICAgICAgICAgIHsvKiB2NDA0IOKAlCBsaWZlY3ljbGUgdGltZXN0YW1wcyAoYWxlcnQgLT4g"
                    "ZW50cnkgLT4gcmVmcmVzaGVkIC0+IGV4aXQpICovfQogICAgICAgICAgPGRpdgogICAgICAg"
                    "ICAgICBjbGFzc05hbWU9ImdyaWQgZ3JpZC1jb2xzLTQgZ2FwLTEgdjUtbW9ubyB0ZXh0LVsx"
                    "MnB4XSIKICAgICAgICAgICAgZGF0YS10ZXN0aWQ9e2BvcGVuLXBvc2l0aW9uLXRpbWVzLSR7"
                    "cG9zaXRpb24uc3ltYm9sfWB9CiAgICAgICAgICA+CiAgICAgICAgICAgIDxUaW1lQ2VsbCBs"
                    "YWJlbD0iQWxlcnQiIHRzPXtwb3NpdGlvbi5hbGVydF90aW1lIHx8IHBvc2l0aW9uLnRyaWdn"
                    "ZXJlZF9hdCB8fCBwb3NpdGlvbi5jcmVhdGVkX2F0fSAvPgogICAgICAgICAgICA8VGltZUNl"
                    "bGwgbGFiZWw9IkVudHJ5IiB0cz17cG9zaXRpb24uZW50cnlfdGltZSB8fCBwb3NpdGlvbi5l"
                    "eGVjdXRlZF9hdCB8fCBwb3NpdGlvbi5vcGVuZWRfYXR9IC8+CiAgICAgICAgICAgIDxUaW1l"
                    "Q2VsbCBsYWJlbD0iUmVmcmVzaGVkIiB0cz17cG9zaXRpb24ubGFzdF91cGRhdGUgfHwgcG9z"
                    "aXRpb24udXBkYXRlZF9hdH0gdG9uZT0idGV4dC1jeWFuLTMwMCIgLz4KICAgICAgICAgICAg"
                    "PFRpbWVDZWxsIGxhYmVsPSJFeGl0IiB0cz17cG9zaXRpb24uZXhpdF90aW1lIHx8IHBvc2l0"
                    "aW9uLmNsb3NlZF9hdH0gdG9uZT0idGV4dC16aW5jLTQwMCIgLz4KICAgICAgICAgIDwvZGl2"
                    "PgoKICAgICAgICAgIHsvKiBSaXNrIC8gc2hhcmVzIHJvdyAqL30K"
                ),
            }
        ],
    },
    {
        "target": "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx",
        "bak": ".v404bak",
        "pre": "e12859743619efa74d6002be309f9a63409bc6752785e1ec3a83645a6a5619e4",
        "post": "e159430dac0d7b118f85dc4616be30522b54e8252fc1c2b62886af37e90a5c3e",
        "edits": [
            {
                "old_b64": (
                    "Y29uc3QgcmVsYXRpdmVBZ2UgPSAodHMpID0+IHsKICBpZiAoIXRzKSByZXR1cm4gJyc7CiAg"
                    "dHJ5IHsKICAgIGNvbnN0IGRpZmZTID0gTWF0aC5tYXgoMCwgTWF0aC5mbG9vcigoRGF0ZS5u"
                    "b3coKSAtIG5ldyBEYXRlKHRzKS5nZXRUaW1lKCkpIC8gMTAwMCkpOwogICAgaWYgKGRpZmZT"
                    "IDwgNjApIHJldHVybiBgJHtkaWZmU31zYDsKICAgIGlmIChkaWZmUyA8IDM2MDApIHJldHVy"
                    "biBgJHtNYXRoLmZsb29yKGRpZmZTIC8gNjApfW1gOwogICAgcmV0dXJuIGAke01hdGguZmxv"
                    "b3IoZGlmZlMgLyAzNjAwKX1oYDsKICB9IGNhdGNoIHsgcmV0dXJuICcnOyB9Cn07Cg=="
                ),
                "new_b64": (
                    "Y29uc3QgcmVsYXRpdmVBZ2UgPSAodHMpID0+IHsKICBpZiAoIXRzKSByZXR1cm4gJyc7CiAg"
                    "dHJ5IHsKICAgIGNvbnN0IGRpZmZTID0gTWF0aC5tYXgoMCwgTWF0aC5mbG9vcigoRGF0ZS5u"
                    "b3coKSAtIG5ldyBEYXRlKHRzKS5nZXRUaW1lKCkpIC8gMTAwMCkpOwogICAgaWYgKGRpZmZT"
                    "IDwgNjApIHJldHVybiBgJHtkaWZmU31zYDsKICAgIGlmIChkaWZmUyA8IDM2MDApIHJldHVy"
                    "biBgJHtNYXRoLmZsb29yKGRpZmZTIC8gNjApfW1gOwogICAgcmV0dXJuIGAke01hdGguZmxv"
                    "b3IoZGlmZlMgLyAzNjAwKX1oYDsKICB9IGNhdGNoIHsgcmV0dXJuICcnOyB9Cn07CgovLyB2"
                    "NDA0ICgyMDI2LTA2LTIzKSDigJQgRVQgd2FsbC1jbG9jayBmb3IgdGhlIGNhcmQgdGltZSBz"
                    "dHJpcCAoYWxlcnQgLwovLyBlbnRyeSB0aW1lc3RhbXBzKS4gUmV0dXJucyBudWxsIG9uIGJh"
                    "ZC9taXNzaW5nIGlucHV0IHNvIGNhbGxlcnMgZmFsbAovLyBiYWNrIGdyYWNlZnVsbHkuCmNv"
                    "bnN0IGZtdENsb2NrRVQgPSAodHMpID0+IHsKICBpZiAoIXRzKSByZXR1cm4gbnVsbDsKICBj"
                    "b25zdCBkID0gbmV3IERhdGUodHMpOwogIGlmIChOdW1iZXIuaXNOYU4oZC5nZXRUaW1lKCkp"
                    "KSByZXR1cm4gbnVsbDsKICByZXR1cm4gZC50b0xvY2FsZVRpbWVTdHJpbmcoJ2VuLVVTJywg"
                    "eyB0aW1lWm9uZTogJ0FtZXJpY2EvTmV3X1lvcmsnLCBob3VyMTI6IGZhbHNlIH0pOwp9Owo="
                ),
            },
            {
                "old_b64": (
                    "ICAgICAgdGltZXN0YW1wOiBhLnRpbWVzdGFtcCB8fCBhLmNyZWF0ZWRfYXQsCg=="
                ),
                "new_b64": (
                    "ICAgICAgYWxlcnRfdHM6IGEudHJpZ2dlcmVkX2F0IHx8IGEuY3JlYXRlZF9hdCB8fCBhLnRp"
                    "bWVzdGFtcCwKICAgICAgcmVmcmVzaGVkX3RzOiBhLnJlZnJlc2hlZF9hdCB8fCBhLmxhc3Rf"
                    "cmVmcmVzaGVkIHx8IGEudXBkYXRlZF9hdCB8fCBhLnRpbWVzdGFtcCwKICAgICAgdGltZXN0"
                    "YW1wOiBhLnRpbWVzdGFtcCB8fCBhLmNyZWF0ZWRfYXQsCg=="
                ),
            },
            {
                "old_b64": (
                    "ICAgICAgdGltZXN0YW1wOiBwLm9wZW5lZF9hdCB8fCBwLmVudHJ5X3RpbWUsCg=="
                ),
                "new_b64": (
                    "ICAgICAgYWxlcnRfdHM6IHAuYWxlcnRfdGltZSB8fCBwLnRyaWdnZXJlZF9hdCB8fCBwLmNy"
                    "ZWF0ZWRfYXQsCiAgICAgIGVudHJ5X3RzOiBwLmVudHJ5X3RpbWUgfHwgcC5leGVjdXRlZF9h"
                    "dCB8fCBwLm9wZW5lZF9hdCwKICAgICAgcmVmcmVzaGVkX3RzOiBwLmxhc3RfdXBkYXRlIHx8"
                    "IHAudXBkYXRlZF9hdCwKICAgICAgdGltZXN0YW1wOiBwLm9wZW5lZF9hdCB8fCBwLmVudHJ5"
                    "X3RpbWUsCg=="
                ),
            },
            {
                "old_b64": (
                    "ICAgICAgey8qIHYxOS4zNC4yOSDigJQgTGl2ZSBzY2FubmVyLXRob3VnaHRzIHN0cmlwIHBl"
                    "ciBjYXJkLiBBdXRvLWZldGNoZXMK"
                ),
                "new_b64": (
                    "ICAgICAgey8qIHY0MDQg4oCUIGFsZXJ0IC8gZW50cnkgLyByZWZyZXNoZWQgdGltZXN0YW1w"
                    "cyBmb3IgYmFja2xvZyB2aXNpYmlsaXR5ICovfQogICAgICB7KGNhcmQuYWxlcnRfdHMgfHwg"
                    "Y2FyZC5yZWZyZXNoZWRfdHMgfHwgY2FyZC5lbnRyeV90cykgJiYgKAogICAgICAgIDxkaXYK"
                    "ICAgICAgICAgIGNsYXNzTmFtZT0iZmxleCBpdGVtcy1jZW50ZXIgZ2FwLTMgbXQtMSB0ZXh0"
                    "LVsxMnB4XSB2NS1tb25vIHRleHQtemluYy01MDAiCiAgICAgICAgICBkYXRhLXRlc3RpZD17"
                    "YHNjYW5uZXItY2FyZC10aW1lcy0ke2NhcmQuc3ltYm9sfWB9CiAgICAgICAgPgogICAgICAg"
                    "ICAge2NhcmQuYWxlcnRfdHMgJiYgZm10Q2xvY2tFVChjYXJkLmFsZXJ0X3RzKSAmJiAoCiAg"
                    "ICAgICAgICAgIDxzcGFuPjxzcGFuIGNsYXNzTmFtZT0idGV4dC16aW5jLTYwMCI+YWxlcnQ8"
                    "L3NwYW4+IHtmbXRDbG9ja0VUKGNhcmQuYWxlcnRfdHMpfSBFVHtyZWxhdGl2ZUFnZShjYXJk"
                    "LmFsZXJ0X3RzKSA/IGAgwrcgJHtyZWxhdGl2ZUFnZShjYXJkLmFsZXJ0X3RzKX1gIDogJyd9"
                    "PC9zcGFuPgogICAgICAgICAgKX0KICAgICAgICAgIHtjYXJkLmVudHJ5X3RzICYmIGZtdENs"
                    "b2NrRVQoY2FyZC5lbnRyeV90cykgJiYgKAogICAgICAgICAgICA8c3Bhbj48c3BhbiBjbGFz"
                    "c05hbWU9InRleHQtemluYy02MDAiPmVudHJ5PC9zcGFuPiB7Zm10Q2xvY2tFVChjYXJkLmVu"
                    "dHJ5X3RzKX0gRVQ8L3NwYW4+CiAgICAgICAgICApfQogICAgICAgICAge2NhcmQucmVmcmVz"
                    "aGVkX3RzICYmIHJlbGF0aXZlQWdlKGNhcmQucmVmcmVzaGVkX3RzKSAmJiAoCiAgICAgICAg"
                    "ICAgIDxzcGFuIGNsYXNzTmFtZT0idGV4dC1jeWFuLTQwMC83MCI+PHNwYW4gY2xhc3NOYW1l"
                    "PSJ0ZXh0LXppbmMtNjAwIj5yZWZyZXNoZWQ8L3NwYW4+IHtyZWxhdGl2ZUFnZShjYXJkLnJl"
                    "ZnJlc2hlZF90cyl9IGFnbzwvc3Bhbj4KICAgICAgICAgICl9CiAgICAgICAgPC9kaXY+CiAg"
                    "ICAgICl9CiAgICAgIHsvKiB2MTkuMzQuMjkg4oCUIExpdmUgc2Nhbm5lci10aG91Z2h0cyBz"
                    "dHJpcCBwZXIgY2FyZC4gQXV0by1mZXRjaGVzCg=="
                ),
            }
        ],
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


def state_of(f):
    p = resolve(f["target"])
    if not os.path.exists(p):
        return p, "MISSING"
    s = sha_full(p)
    if s == f["post"]:
        return p, "ALREADY-APPLIED"
    if s == f["pre"]:
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
    print("  v404 — V5 card lifecycle-timestamp transparency (frontend)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    if args.rollback:
        for f in FILES:
            p = resolve(f["target"])
            bak = p + f["bak"]
            if os.path.exists(bak):
                shutil.copy2(bak, p)
                ok = "matches PRE" if sha_full(p) == f["pre"] else "sha unexpected"
                print(f"  restored {f['target']}  {ok}")
            else:
                print(f"  no backup for {f['target']}; skipped.")
        print("\n  ROLLBACK complete.  NEXT: cd frontend && yarn build")
        return

    states = []
    for f in FILES:
        p, st = state_of(f)
        states.append(st)
        print(f"\n  {f['target']}")
        print(f"    sha  : {sha_full(p)[:12]}   PRE {f['pre'][:12]}  POST {f['post'][:12]}")
        print(f"    state: {st}")

    if "MISSING" in states:
        print("\n  ABORT: a target file is missing.")
        sys.exit(2)
    if "DRIFT" in states:
        print("\n  DRIFT: a file matches neither PRE nor POST. NOTHING changed (atomic).")
        for f, st in zip(FILES, states):
            if st == "DRIFT":
                print(f"    upload: gzip -9 -c {f['target']} | base64 -w0 | curl --data-binary @- https://paste.rs/")
        sys.exit(3)

    ready = [f for f, st in zip(FILES, states) if st == "READY"]
    if args.check:
        print(f"\n  CHECK ok. {len(ready)} file(s) ready, {states.count('ALREADY-APPLIED')} already applied.")
        if ready:
            print("  Re-run with --apply.")
        return

    if not ready:
        print("\n  Nothing to do — all files at POST_SHA.")
        return

    done = []
    for f in ready:
        p = resolve(f["target"])
        src = open(p, encoding="utf-8").read()
        for ed in f["edits"]:
            old = base64.b64decode(ed["old_b64"]).decode("utf-8")
            new = base64.b64decode(ed["new_b64"]).decode("utf-8")
            if src.count(old) != 1:
                print(f"  anchor not unique in {f['target']} — ABORT, reverting.")
                _revert(done)
                sys.exit(3)
            src = src.replace(old, new, 1)
        bak = p + f["bak"]
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        open(p, "w", encoding="utf-8").write(src)
        if sha_full(p) != f["post"]:
            shutil.copy2(bak, p)
            print(f"  POST_SHA MISMATCH on {f['target']} — reverted.")
            _revert(done)
            sys.exit(5)
        print(f"  patched {f['target']}  sha={sha_full(p)[:12]}  (verified)")
        done.append(f)

    print(f"\n  APPLY complete. {len(done)} file(s).")
    print("  NEXT (FRONTEND — rebuild required):")
    print("    git add frontend/ && git commit -m 'v404: card lifecycle-timestamp transparency' && git push origin main")
    print("    cd frontend && yarn build")


def _revert(done):
    for f in done:
        p = resolve(f["target"])
        bak = p + f["bak"]
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            print(f"    reverted {f['target']}")


if __name__ == "__main__":
    main()
