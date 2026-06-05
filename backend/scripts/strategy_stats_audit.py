#!/usr/bin/env python3
"""
strategy_stats_audit.py — win-rate / EV TRUST audit (v19.34.291).

Answers "which setups are blocked by a REAL low win-rate vs a misleading
NO-DATA->0% default?" across the universe over a window (default 30 days).
Replays the scanner's win-rate decision (enhanced_scanner.py:3500-3519) per setup:
  • NO-DATA->0%  : not registered in _strategy_stats (or daily-path only) -> defaults 0.0
  • GRACE        : registered but < grace_min graded outcomes -> uses the floor baseline
  • REAL-LOW     : registered, >= grace_min outcomes, win_rate < floor (genuinely weak)
  • REAL-OK      : registered, >= grace_min outcomes, win_rate >= floor

Usage (on the DGX, backend running):
    .venv/bin/python backend/scripts/strategy_stats_audit.py
    .venv/bin/python backend/scripts/strategy_stats_audit.py --days 7
    .venv/bin/python backend/scripts/strategy_stats_audit.py --days 30 --base http://localhost:8001

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

    url = f"{args.base}/api/scanner/strategy-stats-audit?days={int(args.days)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[ERROR] GET {url} failed: {e}")
        sys.exit(1)

    if not data.get("running", False):
        print(f"\nscanner not running — {data.get('message', 'no detail')}\n")
        return
    if not data.get("success", False):
        print(f"\n[ERROR] {data.get('error', 'unknown error')}\n")
        return

    print(f"\n=== strategy-stats audit: last {data.get('days')}d "
          f"(since {data.get('since')}) ===")
    print(f"registered_setups={data.get('registered_setup_count')}  "
          f"grace_min_trades={data.get('grace_min_trades')}  "
          f"min_win_rate={data.get('min_win_rate')}")
    print("-" * 72)

    sm = data.get("summary_by_verdict", {}) or {}
    print("SUMMARY BY VERDICT (setups / alerts in window):")
    for tag in ("NO-DATA->0%", "GRACE", "REAL-LOW", "REAL-OK"):
        e = sm.get(tag, {}) or {}
        print(f"   {tag:14s}: {e.get('setups', 0)} setups, {e.get('alerts', 0)} alerts")
    print("-" * 72)

    print(f"{'setup_base':24s} {'alerts':>7s} {'reg':>4s} {'trig':>5s} "
          f"{'win%':>5s} {'eff%':>5s} {'EV_R':>6s}  verdict")
    for s in (data.get("setups") or [])[:40]:
        print(f"{s.get('setup_base', '?'):24.24s} "
              f"{s.get('alerts_in_window', 0):>7d} "
              f"{'Y' if s.get('registered') else 'N':>4s} "
              f"{s.get('alerts_triggered', 0):>5d} "
              f"{s.get('win_rate', 0) * 100:>5.0f} "
              f"{s.get('effective_win_rate', 0) * 100:>5.0f} "
              f"{s.get('expected_value_r', 0):>6.2f}  "
              f"{s.get('verdict', '')}")
    print()


if __name__ == "__main__":
    main()
