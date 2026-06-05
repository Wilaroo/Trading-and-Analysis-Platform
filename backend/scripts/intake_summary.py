#!/usr/bin/env python3
"""
intake_summary.py — universe-wide auto-exec INELIGIBILITY rollup (v19.34.289).

One-glance answer to "why is the bot mostly NOT auto-trading?" across the WHOLE
universe over a window (default 30 days). Recomputes auto-exec eligibility from
persisted `live_alerts` via /api/scanner/intake-summary and prints:
  • totals (eligible vs ineligible),
  • the BOTTLENECK tally (how many ineligible alerts tripped each condition:
    win-rate floor vs tape vs priority — conditions can overlap),
  • top combined ineligibility reasons, and worst setups by ineligible count.

Usage (on the DGX, backend running):
    .venv/bin/python backend/scripts/intake_summary.py
    .venv/bin/python backend/scripts/intake_summary.py --days 7
    .venv/bin/python backend/scripts/intake_summary.py --days 30 --base http://localhost:8001

Read-only. Touches no order logic and no open positions.
"""
import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="lookback window (default 30)")
    ap.add_argument("--base", default="http://localhost:8001",
                    help="backend base URL (default http://localhost:8001)")
    args = ap.parse_args()

    url = f"{args.base}/api/scanner/intake-summary?days={int(args.days)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[ERROR] GET {url} failed: {e}")
        sys.exit(1)

    if not data.get("running", False):
        print(f"\nscanner not running / not initialized — "
              f"{data.get('message', 'no detail')}\n")
        return
    if not data.get("success", False):
        print(f"\n[ERROR] {data.get('error', 'unknown error')}\n")
        return

    t = data.get("totals", {}) or {}
    print(f"\n=== intake-summary: last {data.get('days')}d (since {data.get('since')}) ===")
    print(f"auto_exec_enabled={data.get('auto_exec_enabled')}  "
          f"min_win_rate={data.get('min_win_rate')}")
    print(f"alerts={t.get('alerts', 0)}  "
          f"eligible={t.get('eligible', 0)} ({t.get('eligible_pct', 0)}%)  "
          f"ineligible={t.get('ineligible', 0)}")
    print("-" * 60)

    c = data.get("condition_tally", {}) or {}
    print("BOTTLENECK — ineligible alerts tripping each condition (can overlap):")
    print(f"   win-rate < floor : {c.get('win_rate_below', 0)}")
    print(f"   tape unconfirmed : {c.get('tape_unconfirmed', 0)}")
    print(f"   priority < high  : {c.get('priority_low', 0)}")
    if c.get("auto_execute_disabled"):
        print(f"   auto-exec OFF    : {c.get('auto_execute_disabled', 0)}")
    print("-" * 60)

    print("TOP INELIGIBILITY REASONS (combined):")
    for r in (data.get("by_reason") or [])[:12]:
        setups = ",".join((r.get("top_setups") or [])[:3])
        print(f"   - {r.get('reason')} ×{r.get('count')}  ({r.get('symbols')} sym)"
              + (f"  setups={setups}" if setups else ""))
    print("-" * 60)

    print("WORST SETUPS BY INELIGIBLE COUNT:")
    for s in (data.get("by_setup") or [])[:12]:
        print(f"   - {s.get('setup')}: {s.get('ineligible')}/{s.get('total')} "
              f"ineligible ({s.get('ineligible_pct')}%)")
    print()


if __name__ == "__main__":
    main()
