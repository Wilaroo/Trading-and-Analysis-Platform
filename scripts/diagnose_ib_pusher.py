#!/usr/bin/env python3
"""diagnose_ib_pusher.py — find out why IB pusher fields are zero.

Wraps `GET /api/diagnostic/ib-pusher-position-health` for the
v19.34.150 investigation flow. Drops a clean per-field summary,
diagnosis, and per-symbol drill-down.

Usage:
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/diagnose_ib_pusher.py            # full report
    python3 scripts/diagnose_ib_pusher.py --json     # raw JSON
    python3 scripts/diagnose_ib_pusher.py --quiet    # just diagnosis
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
    parser.add_argument("--json", action="store_true",
                        help="Dump raw JSON.")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only the diagnosis section.")
    parser.add_argument("--show-symbols", action="store_true",
                        help="Include per-symbol drill-down (verbose).")
    args = parser.parse_args()

    url = f"{_backend()}/api/diagnostic/ib-pusher-position-health"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(resp, indent=2, default=str))
        return 0

    if not resp.get("success"):
        print(f"❌ Endpoint failed: {resp.get('error')}")
        return 1

    diagnosis = resp.get("diagnosis") or []

    if args.quiet:
        for d in diagnosis:
            print(d)
        return 0

    print("=" * 70)
    print("IB Pusher Position Payload Health")
    print("=" * 70)
    print(f"  generated_at        : {resp.get('generated_at')}")
    print(f"  pusher_connected    : {resp.get('pusher_connected')}")
    print(f"  last_update         : {resp.get('last_update')}")
    print(f"  age_seconds         : {resp.get('age_seconds')}")
    print(f"  pushes/min (recent) : {resp.get('pushes_per_minute_recent')}")
    print(f"  total pushes (sess) : {resp.get('total_pushes_since_start')}")
    print(f"  total positions     : {resp.get('total_positions')}")

    print()
    print("=" * 70)
    print("Per-field health (across all pushed positions)")
    print("=" * 70)
    field_stats = resp.get("field_stats") or {}
    print(
        f"  {'field':<15}  {'non-zero':>8}  {'zero':>5}  "
        f"{'missing':>7}  {'present %':>9}  sample"
    )
    for f, s in field_stats.items():
        sample = s.get("sample_non_zero") or {}
        sample_str = (
            f"{sample.get('symbol')}=${sample.get('value')}"
            if sample else "—"
        )
        emoji = ""
        if s["presence_pct"] >= 80:
            emoji = "✅"
        elif s["presence_pct"] >= 30:
            emoji = "🟡"
        else:
            emoji = "🔴"
        print(
            f"  {emoji} {f:<13}  {s['non_zero_count']:>8}  "
            f"{s['zero_count']:>5}  {s['missing_count']:>7}  "
            f"{s['presence_pct']:>8.1f}%  {sample_str}"
        )

    print()
    print("=" * 70)
    print("Diagnosis")
    print("=" * 70)
    for d in diagnosis:
        print(f"  {d}")

    if args.show_symbols:
        print()
        print("=" * 70)
        print("Per-symbol drill-down")
        print("=" * 70)
        for r in resp.get("per_symbol") or []:
            print(
                f"  {r['symbol']:<6} pos={r.get('position'):<6} "
                f"avgCost={r.get('avgCost')} "
                f"marketPrice={r.get('marketPrice')} "
                f"unrPNL={r.get('unrealizedPNL')}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
