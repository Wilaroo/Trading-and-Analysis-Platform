#!/usr/bin/env python3
"""bracket_governor_dry_run.py — v19.34.154

Read-only dump of the in-process BracketAttachGovernor state. Run on
the DGX while the backend is live to see:
  * Current config (cutoff time, max attempts, attempt window)
  * Today's per-symbol attempt counts (total + in-rolling-window)
  * Permanent block list with reason codes

Usage:
    PYTHONPATH=backend python3 backend/scripts/bracket_governor_dry_run.py
    PYTHONPATH=backend python3 backend/scripts/bracket_governor_dry_run.py --json

Note: this hits the LIVE backend over HTTP (REACT_APP_BACKEND_URL); the
in-process governor singleton isn't accessible from a separate Python
process. The script wraps `GET /api/trading-bot/bracket-attach/state`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urljoin

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))

# Load .env so REACT_APP_BACKEND_URL is available.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_ROOT, "..", "frontend", ".env"))
    load_dotenv(os.path.join(BACKEND_ROOT, ".env"))
except Exception:
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true",
                    help="Raw JSON output (default: pretty table)")
    ap.add_argument("--url",
                    default=os.environ.get("REACT_APP_BACKEND_URL")
                    or "http://localhost:8001",
                    help="Backend base URL (default: REACT_APP_BACKEND_URL "
                         "or http://localhost:8001)")
    args = ap.parse_args()

    endpoint = urljoin(args.url.rstrip("/") + "/",
                       "api/trading-bot/bracket-attach/state")
    try:
        r = requests.get(endpoint, timeout=10)
        r.raise_for_status()
        body = r.json()
    except Exception as e:
        print(f"[FATAL] GET {endpoint} failed: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(body, indent=2))
        return 0

    state = body.get("state") or {}
    cfg = state.get("config") or {}
    print("─" * 70)
    print(f"BRACKET-ATTACH GOVERNOR  (date: {state.get('today_et', '?')})")
    print("─" * 70)
    print(f"  hard cutoff       : {cfg.get('hard_cutoff_hour', '?'):02d}:"
          f"{cfg.get('hard_cutoff_minute', '?'):02d} ET")
    print(f"  max attempts      : {cfg.get('max_attempts', '?')} in "
          f"{cfg.get('attempt_window_s', '?')}s rolling window")
    print()

    blocks = state.get("blocks") or {}
    if not blocks:
        print("  PERMANENT BLOCKS  : (none — healthy)")
    else:
        print(f"  PERMANENT BLOCKS  : {len(blocks)}")
        for sym, b in sorted(blocks.items()):
            print(f"    {sym:<8}  reason={b.get('reason','?')}  "
                  f"code={b.get('code','?')}  "
                  f"blocked_at={b.get('blocked_at_et', '?')}  "
                  f"attempts={b.get('attempt_count', '?')}")
    print()

    attempts = state.get("attempts") or {}
    if not attempts:
        print("  ATTEMPTS TODAY    : (none)")
    else:
        print(f"  ATTEMPTS TODAY    : {len(attempts)} symbol(s)")
        for sym, a in sorted(attempts.items(),
                             key=lambda kv: -kv[1].get("in_window", 0)):
            marker = " 🚨" if a.get("in_window", 0) >= cfg.get("max_attempts", 99) else ""
            print(f"    {sym:<8}  total={a.get('total_today', 0):<3}  "
                  f"in_window={a.get('in_window', 0)}{marker}")
    print("─" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
