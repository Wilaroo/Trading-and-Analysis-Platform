"""
reset_bot_open_trades.py — one-shot bot state hard reset.

Use this AFTER manually flattening positions in TWS, BEFORE starting the
bot for a fresh trading day. It directly closes every `status: open`
row in `bot_trades` so the bot's in-memory `_open_trades` rebuilds
empty when the backend boots.

WHY YOU'D RUN THIS
    Yesterday's chaos left bot_trades records that are out-of-sync with
    IB (BP partial 1437/4281, SOFI long 1636/427, SOFI short 301/0,
    etc). Trailing stops would tick on the wrong share counts and
    duplicate trade-id collisions could occur on new entries. Cleanest
    recovery: flatten IB-side, reset bot-side, start fresh.

USAGE
    # ALWAYS dry-run first to see what would change.
    python3 backend/scripts/reset_bot_open_trades.py --dry-run

    # Commit the reset. Confirm token is REQUIRED to prevent accidents.
    python3 backend/scripts/reset_bot_open_trades.py --confirm RESET

    # Filter to specific symbols only:
    python3 backend/scripts/reset_bot_open_trades.py --confirm RESET --symbols SOFI BP

    # Use a non-default Mongo URL or DB name:
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand \\
        python3 backend/scripts/reset_bot_open_trades.py --dry-run

WHAT IT DOES (only when --confirm RESET is passed)
    For each `bot_trades` doc with `status == 'open'`:
      - Set `status = 'closed'`
      - Set `close_reason = 'manual_pre_open_reset_v19_29'`
      - Set `closed_at = now (UTC ISO8601)`
      - Set `remaining_shares = 0` if not already

    A snapshot of the affected trade_ids is written to
    `bot_trades_reset_log` (TTL 30d) for audit. Never deletes data.

POST-RESET STEPS
    1. Restart backend so `_open_trades` rebuilds empty from Mongo.
    2. Confirm: curl localhost:8001/api/sentcom/positions | jq '.positions | length'
       Should return 0 if IB is also flat.
    3. At 9:30 ET, watch v19.29 verification harness:
       python3 -m backend.scripts.verify_v19_29 --watch
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pymongo not installed in this Python env.")
    print("Run with the backend's venv:")
    print("  .venv/bin/python backend/scripts/reset_bot_open_trades.py --dry-run")
    print("OR install: pip3 install --user pymongo")
    sys.exit(2)


CLOSE_REASON = "manual_pre_open_reset_v19_29"
RESET_LOG_COLLECTION = "bot_trades_reset_log"
RESET_LOG_TTL_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_query(symbols: Optional[List[str]]) -> dict:
    q: dict = {"status": "open"}
    if symbols:
        q["symbol"] = {"$in": [s.upper() for s in symbols]}
    return q


def _summarise_open_trades(coll, query: dict) -> List[dict]:
    """Return a compact summary of trades matching the query."""
    proj = {
        "trade_id": 1,
        "symbol": 1,
        "direction": 1,
        "shares": 1,
        "remaining_shares": 1,
        "status": 1,
        "executed_at": 1,
        "_id": 0,
    }
    return list(coll.find(query, proj))


def _ensure_reset_log_index(db) -> None:
    try:
        db[RESET_LOG_COLLECTION].create_index(
            "ts", expireAfterSeconds=RESET_LOG_TTL_DAYS * 86400
        )
    except Exception:
        # Index may already exist with different options; ignore.
        pass


def _write_reset_log(db, affected_trade_ids: List[str], symbols_filter: Optional[List[str]]) -> None:
    if not affected_trade_ids:
        return
    try:
        _ensure_reset_log_index(db)
        db[RESET_LOG_COLLECTION].insert_one({
            "ts": datetime.now(timezone.utc),
            "ts_iso": _now_iso(),
            "reason": CLOSE_REASON,
            "trade_ids": affected_trade_ids,
            "symbols_filter": symbols_filter,
            "count": len(affected_trade_ids),
        })
    except Exception as e:
        # Log write is best-effort. The actual reset has already happened.
        print(f"WARN: reset log write failed (non-fatal): {e}")


def reset_open_trades(
    *,
    db,
    symbols: Optional[List[str]] = None,
    dry_run: bool = True,
) -> dict:
    """Core reset op. Returns a summary dict — never raises on data."""
    query = _build_query(symbols)
    coll = db["bot_trades"]
    affected = _summarise_open_trades(coll, query)
    affected_ids = [str(t.get("trade_id") or "") for t in affected if t.get("trade_id")]

    result = {
        "dry_run": dry_run,
        "query": query,
        "matched_count": len(affected),
        "affected": affected,
        "modified_count": 0,
        "log_written": False,
    }

    if dry_run or not affected:
        return result

    update = {
        "$set": {
            "status": "closed",
            "close_reason": CLOSE_REASON,
            "closed_at": _now_iso(),
            "remaining_shares": 0,
        }
    }
    upd = coll.update_many(query, update)
    result["modified_count"] = upd.modified_count

    _write_reset_log(db, affected_ids, symbols)
    result["log_written"] = True
    return result


def render_summary(result: dict) -> str:
    lines = []
    mode = "DRY-RUN" if result["dry_run"] else "COMMITTED"
    lines.append(f"\n[{mode}] reset_bot_open_trades — {_now_iso()}")
    lines.append(f"  matched: {result['matched_count']} open bot_trades")
    if result["affected"]:
        lines.append("  rows:")
        for t in result["affected"]:
            lines.append(
                f"    - {t.get('symbol'):<6} {str(t.get('direction') or '?'):<6} "
                f"shares={t.get('shares')} remaining={t.get('remaining_shares')} "
                f"trade_id={t.get('trade_id')}"
            )
    if not result["dry_run"]:
        lines.append(f"  modified: {result['modified_count']}")
        lines.append(f"  audit log written to bot_trades_reset_log: {result['log_written']}")
    else:
        lines.append("  (dry-run — no changes written)")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Hard-reset bot_trades status=open rows.")
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("DB_NAME", "tradecommand"))
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional symbol whitelist")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying")
    parser.add_argument("--confirm", default=None, help="Pass 'RESET' to actually commit")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of summary")
    args = parser.parse_args(argv)

    if not args.dry_run and args.confirm != "RESET":
        print("ABORT: pass either --dry-run OR --confirm RESET")
        print("  Dry-run preview:    python3 reset_bot_open_trades.py --dry-run")
        print("  Commit the reset:   python3 reset_bot_open_trades.py --confirm RESET")
        return 2

    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: cannot reach Mongo at {args.mongo_url}: {e}")
        return 3
    db = client[args.db]

    result = reset_open_trades(db=db, symbols=args.symbols, dry_run=args.dry_run)

    if args.json:
        import json
        print(json.dumps(result, default=str, indent=2))
    else:
        print(render_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
