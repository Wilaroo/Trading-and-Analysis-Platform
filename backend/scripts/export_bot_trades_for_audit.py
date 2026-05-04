#!/usr/bin/env python3
"""
export_bot_trades_for_audit.py — v19.34.4 (2026-05-04)

Operator runs this on Spark (where Mongo lives). Exports today's
`bot_trades` rows (filled today, regardless of open/closed status)
into a JSON sidecar that audit_ib_fill_tape.py consumes via the
`--bot-trades-json` flag.

Usage on Spark:
  cd ~/Trading-and-Analysis-Platform/backend
  python -m scripts.export_bot_trades_for_audit \
      --date 2026-05-04 \
      --out /tmp/bot_trades_2026_05_04.json

  # Then on the same machine:
  python -m scripts.audit_ib_fill_tape \
      --input /path/to/ib_tape.txt \
      --bot-trades-json /tmp/bot_trades_2026_05_04.json \
      --out /tmp/audit_2026_05_04.md

Output JSON shape:
  [
    {"symbol":"VALE","row_count":1,"total_qty":5179,
     "rows":[{"trade_id":"...", "direction":"long",
              "executed_at":"...", "closed_at":"...",
              "shares":5179, "entry_price":16.14,
              "exit_price":15.82, "realized_pnl":...,
              "entered_by":"...", "synthetic_source":"...",
              "prior_verdict_conflict":false, ...}]},
    ...
  ]

The summary block is what `audit_ib_fill_tape.py` consumes;
the per-row detail is included for human inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: F401
except ImportError:
    AsyncIOMotorClient = None  # type: ignore

try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pymongo not installed. Run from backend/.venv", file=sys.stderr)
    sys.exit(2)


def parse_et_date(date_str: str) -> tuple[datetime, datetime]:
    """
    Returns (start_utc, end_utc) for the given trading day in ET.
    Approximates as 04:00 UTC → 04:00 UTC of next day (covers ET trading window).
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = datetime(d.year, d.month, d.day, 4, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD trading day")
    ap.add_argument("--out", type=Path, required=True, help="Output JSON path")
    ap.add_argument(
        "--mongo-url",
        default=os.environ.get("MONGO_URL", "mongodb://localhost:27017"),
    )
    ap.add_argument(
        "--db-name",
        default=os.environ.get("DB_NAME", "tradecommand_db"),
    )
    args = ap.parse_args()

    start_utc, end_utc = parse_et_date(args.date)
    print(f"Window: {start_utc.isoformat()} → {end_utc.isoformat()}", file=sys.stderr)

    client = MongoClient(args.mongo_url)
    db = client[args.db_name]

    # Bot rows where any of executed_at, closed_at, or created_at falls in window.
    query = {
        "$or": [
            {"executed_at": {"$gte": start_utc, "$lt": end_utc}},
            {"closed_at": {"$gte": start_utc, "$lt": end_utc}},
            {"created_at": {"$gte": start_utc, "$lt": end_utc}},
        ]
    }

    proj = {
        "_id": 0,
        "trade_id": 1,
        "symbol": 1,
        "direction": 1,
        "shares": 1,
        "entry_price": 1,
        "exit_price": 1,
        "stop_price": 1,
        "target_prices": 1,
        "executed_at": 1,
        "closed_at": 1,
        "created_at": 1,
        "status": 1,
        "realized_pnl": 1,
        "trade_type": 1,
        "account_id_at_fill": 1,
        "entered_by": 1,
        "synthetic_source": 1,
        "prior_verdict_conflict": 1,
        "close_reason": 1,
        "setup_type": 1,
        "trade_style": 1,
        "risk_reward_ratio": 1,
    }

    rows = list(db.bot_trades.find(query, proj))
    print(f"Loaded {len(rows)} rows from bot_trades", file=sys.stderr)

    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        # Stringify datetime for JSON.
        for k in ("executed_at", "closed_at", "created_at"):
            if k in r and isinstance(r[k], datetime):
                r[k] = r[k].isoformat()
        sym = r.get("symbol")
        if not sym:
            continue
        by_sym.setdefault(sym, []).append(r)

    summary = []
    for sym, sym_rows in sorted(by_sym.items()):
        total_qty = sum(int(r.get("shares") or 0) for r in sym_rows)
        total_realized = sum(float(r.get("realized_pnl") or 0) for r in sym_rows)
        summary.append({
            "symbol": sym,
            "row_count": len(sym_rows),
            "total_qty": total_qty,
            "total_realized_pnl": round(total_realized, 2),
            "rows": sym_rows,
        })

    args.out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"Wrote {args.out} ({len(summary)} symbols)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
