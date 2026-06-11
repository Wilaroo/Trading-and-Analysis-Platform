#!/usr/bin/env python3
"""
check_m0_status.py  (read-only) — M0 ladder live verification
===============================================================
Shows, for every OPEN scalp/intraday bot trade (and today's closed ones):
  • whether it got an M0 ladder (legs, qtys, target prices, order ids)
  • per-leg status (working / filled_tp / filled_stop)
  • targets_hit + the stop price last synced to IB (BE / trail evidence)

Usage:
  .venv/bin/python backend/scripts/check_m0_status.py            # open trades
  .venv/bin/python backend/scripts/check_m0_status.py --today    # + today's closed
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", action="store_true",
                    help="also show trades closed today")
    args = ap.parse_args()
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    q = {"status": {"$nin": ["closed", "CLOSED", "cancelled", "CANCELLED"]}}
    rows = list(db.bot_trades.find(q, sort=[("created_at", -1)], limit=50))
    if args.today:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows += list(db.bot_trades.find(
            {"status": {"$in": ["closed", "CLOSED"]},
             "closed_at": {"$gte": today}},
            sort=[("closed_at", -1)], limit=50))

    print("=" * 78)
    print(f"M0 LADDER STATUS — {len(rows)} trade(s)")
    print("=" * 78)
    if not rows:
        print("No open trades. (Run with --today to include today's closed.)")

    n_m0 = 0
    for t in rows:
        style = ""
        for f in ("timeframe", "trade_type", "scan_tier"):
            v = t.get(f)
            v = getattr(v, "value", v)
            if v:
                style = str(v).lower()
                break
        cfg = t.get("scale_out_config") or {}
        legs = cfg.get("m0_legs") or []
        head = (f"{t.get('symbol', '?'):<6} {style:<9} {str(t.get('status', '')):<10} "
                f"sh={t.get('shares')} rem={t.get('remaining_shares')} "
                f"entry={t.get('entry_price')} stop={t.get('stop_price')}")
        if not legs:
            print(f"\n• {head}")
            print(f"   M0: — no ladder (single-pair bracket). "
                  f"style eligible: {style in ('scalp', 'intraday')}, "
                  f"shares >= 10: {(t.get('shares') or 0) >= 10}, "
                  f"created: {str(t.get('created_at'))[:19]}")
            continue
        n_m0 += 1
        print(f"\n★ {head}   [M0 LADDER — {len(legs)} legs]")
        for l in legs:
            print(f"   L{l.get('idx', 0) + 1}: {l.get('qty')}sh  "
                  f"target {l.get('target_px')} ({l.get('r_multiple')}R)  "
                  f"stop {l.get('stop_px')}  "
                  f"ids stop={l.get('stop_order_id')} tgt={l.get('target_order_id')}  "
                  f"status={l.get('status')}")
        print(f"   targets_hit={cfg.get('targets_hit')}  "
              f"ib_stop_px={cfg.get('m0_ib_stop_px')}  "
              f"last_sync={str(cfg.get('m0_stop_synced_at', ''))[:19] or '—'}  "
              f"trail_mode={(t.get('trailing_stop_config') or {}).get('mode', '?')}")

    print(f"\nSummary: {n_m0}/{len(rows)} trades carry an M0 ladder.")
    print("Log evidence:  grep 'M0 LADDER\\|M0 LEG-FILL\\|M0 STOP-SYNC' /tmp/backend.log")
    print("Done (read-only).")


if __name__ == "__main__":
    main()
