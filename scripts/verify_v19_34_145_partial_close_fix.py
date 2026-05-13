#!/usr/bin/env python3
"""verify_v19_34_145_partial_close_fix.py
=========================================

Confirms the v19.34.145 fix landed correctly on the live DGX.

Pre-fix symptoms (from the 2026-05-13 audit run that motivated this fix):
  • KMB classified QTY_MAGNITUDE_MISMATCH (bot=144 vs ib=55)
  • ONON classified QTY_MAGNITUDE_MISMATCH (bot=235 vs ib=59)
  • False NAKED-position warning in `actions[]`
  • Audit delta ~$777 driven mostly by the inflated KMB / ONON unrealized

Post-fix expectations:
  • KMB / ONON classify as OK or DRIFT_* (small PnL drift only)
  • No `qty_magnitude_mismatch` count
  • No "MAGNITUDE drift" action line
  • Audit delta materially smaller

Usage (on the DGX):
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/verify_v19_34_145_partial_close_fix.py
    python3 scripts/verify_v19_34_145_partial_close_fix.py --symbols KMB,ONON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _backend() -> str:
    return os.environ.get(
        "REACT_APP_BACKEND_URL", "http://localhost:8001"
    ).rstrip("/")


def _GET(path: str) -> dict:
    url = f"{_backend()}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# Symbols the operator confirmed are scaled-out (partial close fired).
# Pre-fix these falsely tripped QTY_MAGNITUDE_MISMATCH.
DEFAULT_PARTIAL_CLOSE_WATCHLIST = ["KMB", "ONON"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_PARTIAL_CLOSE_WATCHLIST),
        help="Comma-separated symbols to verify (default: KMB,ONON).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any DRIFT_* (PnL) is still present on the "
             "watched symbols. Default is to PASS as long as no "
             "QTY_MAGNITUDE_MISMATCH fires.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON audit response and exit.",
    )
    args = parser.parse_args()

    watch = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    print(f"Hitting audit at {_backend()}/api/diagnostic/position-pnl-audit …")
    try:
        audit = _GET("/api/diagnostic/position-pnl-audit")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(audit, indent=2, default=str))
        return 0

    summary = audit.get("summary", {})
    rows = audit.get("rows", []) or []
    actions = audit.get("actions", []) or []

    print()
    print("=" * 60)
    print("Audit summary")
    print("=" * 60)
    print(f"  audited            : {summary.get('total_audited')}")
    print(f"  ok                 : {summary.get('ok')}")
    print(f"  drift_abs          : {summary.get('drift_abs')}")
    print(f"  drift_pct          : {summary.get('drift_pct')}")
    print(f"  missing_in_bot     : {summary.get('missing_in_bot')}")
    print(f"  phantom_in_bot     : {summary.get('phantom_in_bot')}")
    print(f"  qty_sign_mismatch  : {summary.get('qty_sign_mismatch')}")
    print(f"  qty_magnitude      : {summary.get('qty_magnitude_mismatch', 0)}")
    totals = summary.get("totals") or {}
    print(f"  ib_total           : ${totals.get('ib_unrealized'):>10}")
    print(f"  bot_total          : ${totals.get('bot_unrealized'):>10}")
    print(f"  delta              : ${totals.get('delta'):>10}")

    print()
    print("=" * 60)
    print(f"Watched symbols ({', '.join(sorted(watch))})")
    print("=" * 60)

    watched_rows = [r for r in rows if r.get("symbol", "").upper() in watch]
    if not watched_rows:
        print("  (no rows for watched symbols — they may be closed)")

    overall_pass = True
    for r in watched_rows:
        sym = r["symbol"]
        verdict = r.get("verdict")
        bot_q = r.get("bot_qty")
        ib_q = r.get("ib_qty")
        delta_abs = r.get("delta_abs")
        pnl_src = r.get("pnl_source")
        line = (
            f"  {sym:<6} verdict={verdict:<25} "
            f"bot_qty={bot_q:<6} ib_qty={ib_q:<6} "
            f"Δ$={delta_abs:<8} pnl_source={pnl_src}"
        )
        if verdict == "QTY_MAGNITUDE_MISMATCH":
            print(f"❌{line}")
            print(f"    → v19.34.145 fix DID NOT APPLY for {sym}.")
            print(f"      Check that the deployed backend version "
                  f"includes the audit `remaining_shares` switch.")
            overall_pass = False
        elif verdict in ("DRIFT_ABS", "DRIFT_PCT"):
            print(f"⚠ {line}")
            if args.strict:
                overall_pass = False
        else:
            print(f"✅{line}")

    # Magnitude-mismatch action line should be gone.
    magnitude_action = any(
        "MAGNITUDE" in a.upper() or "magnitude drift" in a.lower()
        for a in actions
    )
    print()
    print("=" * 60)
    print("Verdict")
    print("=" * 60)
    if summary.get("qty_magnitude_mismatch", 0) == 0 and not magnitude_action:
        print("✅ No QTY_MAGNITUDE_MISMATCH fired anywhere in the audit.")
    else:
        # If watch symbols are now OK but OTHER symbols are magnitude-mismatched,
        # those are genuine drifts the operator should investigate.
        mag_rows = [r for r in rows if r.get("verdict") == "QTY_MAGNITUDE_MISMATCH"]
        offenders = [r["symbol"] for r in mag_rows]
        watched_offenders = [s for s in offenders if s in watch]
        unwatched_offenders = [s for s in offenders if s not in watch]
        if watched_offenders:
            print(f"❌ Watched symbols STILL magnitude-mismatched: {watched_offenders}")
            print("   The v19.34.145 fix is not active on this backend. "
                  "Confirm you pulled / restarted after the patch.")
            overall_pass = False
        if unwatched_offenders:
            print(f"⚠ NEW magnitude drift on UNWATCHED symbols: {unwatched_offenders}")
            print("   These are NOT the KMB/ONON partial-close false-positive "
                  "— they're genuine ledger drifts. Walk their fragments with:")
            for s in unwatched_offenders[:3]:
                print(f"     python3 scripts/kmb_fragment_forensics.py --symbol {s}")

    if overall_pass:
        print("\n✅ PASS — v19.34.145 partial-close fix is active.")
        return 0
    print("\n❌ FAIL — see notes above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
