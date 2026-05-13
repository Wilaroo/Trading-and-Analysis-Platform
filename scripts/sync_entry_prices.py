#!/usr/bin/env python3
"""sync_entry_prices.py — heal entry_price vs IB.avgCost drift.

Wraps `POST /api/trading-bot/sync-entry-prices` for the v19.34.148
manual remediation flow.

Usage (on the DGX):
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/sync_entry_prices.py --dry-run        # preview
    python3 scripts/sync_entry_prices.py                  # apply
    python3 scripts/sync_entry_prices.py --symbols ICLN,CW
    python3 scripts/sync_entry_prices.py --tolerance 0.5  # widen gate
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what WOULD sync but don't mutate state.",
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbols to limit scope (default: all).",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.01,
        help="Skip syncs below this per-share gap (default: 0.01).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Dump raw JSON response.",
    )
    args = parser.parse_args()

    body = {
        "dry_run": args.dry_run,
        "tolerance_per_share": args.tolerance,
    }
    if args.symbols:
        body["symbols"] = [s.strip() for s in args.symbols.split(",")
                           if s.strip()]

    url = f"{_backend()}/api/trading-bot/sync-entry-prices"
    print(f"POST {url}")
    print(f"body: {json.dumps(body)}")
    print()

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(resp, indent=2, default=str))
        return 0

    if not resp.get("success"):
        print(f"❌ Sync did not run: reason={resp.get('reason')}")
        return 1

    print(f"mode               : {resp.get('mode')}")
    print(f"tolerance_per_share: ${resp.get('tolerance_per_share')}")
    print(f"ib_positions_seen  : {resp.get('ib_positions_seen')}")
    print(f"tracked_trades     : {resp.get('tracked_trades')}")
    print(f"candidates         : {resp.get('candidates')}")

    synced = resp.get("synced") or []
    skipped_tol = resp.get("skipped_within_tol") or []
    skipped_no_data = resp.get("skipped_no_ib_data") or []
    persisted = resp.get("persisted_to_db", 0)
    correction = resp.get("total_implied_pnl_correction", 0)

    print(f"synced             : {len(synced)}")
    print(f"  persisted to DB  : {persisted}")
    print(f"skipped (≤tol)     : {len(skipped_tol)}")
    print(f"skipped (no IB)    : {len(skipped_no_data)}")
    print(f"net PnL correction : ${correction:+.2f}")

    if synced:
        print()
        print("=" * 78)
        print("Synced trades")
        print("=" * 78)
        for s in synced:
            tag = "(would-sync)" if s.get("applied") is False else "✓"
            print(
                f"  {tag} {s['symbol']:<6} {s['direction']:<5} "
                f"qty={s['qty']:<5} "
                f"${s['old_entry_price']} → ${s['new_entry_price']} "
                f"(Δ ${s['delta_per_share']:+.4f}/sh, "
                f"PnL correction ${s['implied_pnl_correction']:+.2f})"
            )

    perr = resp.get("persist_errors") or []
    if perr:
        print()
        print("⚠ persist errors:")
        for e in perr:
            print(f"  - {e['symbol']} ({e['trade_id']}): {e['error']}")

    if args.dry_run:
        print()
        print("ℹ DRY RUN — no state changed. "
              "Rerun without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
