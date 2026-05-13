#!/usr/bin/env python3
"""position_reopen_forensics.py — per-symbol forensic: was each open
IB position REOPENED by the bot, or ADOPTED from existing IB state?

Designed for incident analysis like 2026-05-13 where the operator
manually flattened all positions at ~3:57 PM ET and noticed positions
re-emerging on IB in the final 2 min before close. Answers:

  • Did the bot fire NEW entry orders after my manual flatten?
  • Or did the reconciler just "inhale" the positions IB still
    showed (because my IB-side flatten hadn't settled into the
    pusher snapshot yet)?

Verdicts (per symbol):
  🚨 REOPENED_BY_BOT             — strategy fired a fresh entry after
                                   the cutoff (REAL bug if unintended)
  ℹ ADOPTED_FROM_IB              — reconciler absorbed an IB position;
                                   no new order placed
  ✅ STRATEGY_ENTRY_BEFORE_CUTOFF — normal trade entered before cutoff
  ⚠ NO_BOT_RECORD                — IB has a position the bot has zero
                                   trace of (pure manual / external)

Usage:
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/position_reopen_forensics.py            # cutoff 15:30 ET
    python3 scripts/position_reopen_forensics.py --since 15:57  # custom cutoff
    python3 scripts/position_reopen_forensics.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


def _backend() -> str:
    return os.environ.get(
        "REACT_APP_BACKEND_URL", "http://localhost:8001"
    ).rstrip("/")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--since", default=None,
                   help="HH:MM ET cutoff (default 15:30)")
    p.add_argument("--json", action="store_true", help="raw JSON")
    args = p.parse_args()

    qs = f"?since_et={urllib.parse.quote(args.since)}" if args.since else ""
    url = f"{_backend()}/api/diagnostic/position-reopen-forensics{qs}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(resp, indent=2, default=str))
        return 0

    print("=" * 78)
    print("Position-Reopen Forensics")
    print("=" * 78)
    print(f"  generated_at : {resp.get('generated_at')}")
    print(f"  cutoff_et    : {resp.get('cutoff_et')}")
    s = resp.get("summary") or {}
    print(f"  summary      : "
          f"REOPENED={s.get('REOPENED_BY_BOT', 0)} "
          f"ADOPTED={s.get('ADOPTED_FROM_IB', 0)} "
          f"BEFORE={s.get('STRATEGY_ENTRY_BEFORE_CUTOFF', 0)} "
          f"NO_RECORD={s.get('NO_BOT_RECORD', 0)}")
    print()
    print("=" * 78)
    print("Per-symbol")
    print("=" * 78)
    print(
        f"  {'symbol':<6} {'qty':>8} {'verdict':<32} "
        f"{'fill_age':>10} {'entered_by':<30} setup"
    )
    for r in resp.get("rows") or []:
        bt = r.get("last_bot_trade") or {}
        eb = (bt.get("entered_by") or "—")[:30]
        st = (bt.get("setup_type") or "—")[:18]
        fa = r.get("most_recent_fill_age_seconds")
        fa_str = (
            f"{fa // 60}m {fa % 60}s" if fa is not None else "—"
        )
        emoji = {
            "REOPENED_BY_BOT": "🚨",
            "ADOPTED_FROM_IB": "ℹ ",
            "STRATEGY_ENTRY_BEFORE_CUTOFF": "✅",
            "NO_BOT_RECORD": "⚠ ",
        }.get(r.get("verdict"), "  ")
        print(
            f"  {emoji}{r.get('symbol'):<5} {int(r.get('ib_qty', 0)):>8} "
            f"{r.get('verdict'):<32} {fa_str:>10} {eb:<30} {st}"
        )

    print()
    print("=" * 78)
    print("Diagnosis")
    print("=" * 78)
    for d in resp.get("diagnosis") or []:
        print(f"  {d}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
