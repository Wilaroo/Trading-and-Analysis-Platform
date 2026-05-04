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


def _fetch_ib_held_keys(db) -> Optional[set]:
    """v19.31 — IB-survival guard. Read the latest pusher snapshot from
    `ib_live_snapshot.current` and return the set of `(symbol_upper,
    direction)` tuples IB currently holds. Returns None if the snapshot
    is missing or unparseable so callers can decide whether to bail.

    The snapshot is updated on every pusher push (~5s cadence) so it's
    fresh enough for a manual pre-open reset.
    """
    try:
        snap = db["ib_live_snapshot"].find_one(
            {"_id": "current"}, {"_id": 0, "positions": 1}
        )
    except Exception as e:
        print(f"WARN: cannot read ib_live_snapshot.current: {e}")
        return None
    if not snap or not isinstance(snap, dict):
        return None
    positions = snap.get("positions") or []
    held: set = set()
    for p in positions:
        try:
            sym = (p.get("symbol") or "").upper()
            qty = float(p.get("position", p.get("qty", 0)) or 0)
            if not sym or abs(qty) < 0.001:
                continue
            held.add((sym, "long" if qty > 0 else "short"))
        except Exception:
            continue
    return held


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
    force: bool = False,
) -> dict:
    """Core reset op. Returns a summary dict — never raises on data.

    v19.31 (2026-05-04) — IB-survival guard. Before this, the script
    blindly closed every `bot_trades` row with status=open even when
    IB still actually held the position. Operator hit this 2026-05-04
    when 13 carryover positions ended up reading as "ORPHAN" because
    the morning reset wiped the bot's tracking record while IB still
    owned the shares.

    New behavior: rows whose `(symbol, direction)` tuple is still in
    IB's pushed-snapshot positions get SKIPPED with `skipped_ib_held`
    in the summary. Pass `force=True` to override (returns to the old
    "close everything" behavior).
    """
    query = _build_query(symbols)
    coll = db["bot_trades"]
    affected = _summarise_open_trades(coll, query)
    affected_ids = [str(t.get("trade_id") or "") for t in affected if t.get("trade_id")]

    result = {
        "dry_run": dry_run,
        "force": force,
        "query": query,
        "matched_count": len(affected),
        "affected": affected,
        "modified_count": 0,
        "log_written": False,
        "skipped_ib_held": [],
        "ib_snapshot_available": False,
    }

    # v19.31 — partition `affected` into "IB still holds" vs "safe to close"
    # before any DB writes. If `force=True`, skip the partition (legacy
    # behavior). If snapshot can't be read, fail-closed by default —
    # operator must pass --force to override.
    held_keys: Optional[set] = None if force else _fetch_ib_held_keys(db)
    result["ib_snapshot_available"] = held_keys is not None

    if held_keys is None and not force and not dry_run:
        print(
            "ABORT: ib_live_snapshot.current is missing or unreadable. "
            "Cannot verify which positions IB still holds. Pass --force "
            "to override (this will close ALL matching rows regardless "
            "of IB state)."
        )
        result["aborted"] = "no_ib_snapshot"
        return result

    safe_to_close: List[dict] = []
    for t in affected:
        sym = (t.get("symbol") or "").upper()
        direction = str(t.get("direction") or "long").lower()
        if held_keys is not None and (sym, direction) in held_keys:
            result["skipped_ib_held"].append({
                "symbol": sym,
                "direction": direction,
                "trade_id": str(t.get("trade_id") or ""),
                "shares": t.get("shares"),
                "remaining_shares": t.get("remaining_shares"),
            })
        else:
            safe_to_close.append(t)

    safe_ids = [str(t.get("trade_id") or "") for t in safe_to_close if t.get("trade_id")]
    result["safe_to_close_count"] = len(safe_to_close)
    result["affected"] = safe_to_close  # surface only the rows we'll actually touch
    result["affected_ids"] = safe_ids

    if dry_run or not safe_to_close:
        return result

    # Build a tighter query so update_many ONLY hits the safe rows.
    update_query = dict(query)
    if safe_ids:
        # trade_id is the canonical key on bot_trades.
        update_query["trade_id"] = {"$in": safe_ids}

    update = {
        "$set": {
            "status": "closed",
            "close_reason": CLOSE_REASON,
            "closed_at": _now_iso(),
            "remaining_shares": 0,
        }
    }
    upd = coll.update_many(update_query, update)
    result["modified_count"] = upd.modified_count

    _write_reset_log(db, safe_ids, symbols)
    result["log_written"] = True
    # keep affected_ids for downstream callers / tests that expect it
    return result


def render_summary(result: dict) -> str:
    lines = []
    mode = "DRY-RUN" if result["dry_run"] else "COMMITTED"
    forced = " [FORCED]" if result.get("force") else ""
    lines.append(f"\n[{mode}{forced}] reset_bot_open_trades — {_now_iso()}")
    lines.append(f"  matched (raw): {result['matched_count']} open bot_trades")
    snap_status = (
        "available" if result.get("ib_snapshot_available")
        else ("BYPASSED (--force)" if result.get("force") else "MISSING")
    )
    lines.append(f"  ib snapshot: {snap_status}")

    skipped = result.get("skipped_ib_held") or []
    if skipped:
        lines.append(
            f"  skipped {len(skipped)} row(s) — IB still holds the position "
            f"(v19.31 survival guard):"
        )
        for s in skipped:
            lines.append(
                f"    ⚠ {s.get('symbol'):<6} {s.get('direction'):<6} "
                f"shares={s.get('shares')} remaining={s.get('remaining_shares')} "
                f"trade_id={s.get('trade_id')}"
            )
        lines.append(
            "  (closing these rows would orphan real IB positions — "
            "use --force to override at your own risk.)"
        )

    if result["affected"]:
        lines.append(f"  rows that would be closed: {result.get('safe_to_close_count', len(result['affected']))}")
        for t in result["affected"]:
            lines.append(
                f"    - {t.get('symbol'):<6} {str(t.get('direction') or '?'):<6} "
                f"shares={t.get('shares')} remaining={t.get('remaining_shares')} "
                f"trade_id={t.get('trade_id')}"
            )
    elif not skipped:
        lines.append("  rows that would be closed: 0")

    if result.get("aborted"):
        lines.append(f"  ABORTED: {result['aborted']}")
    elif not result["dry_run"]:
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
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "v19.31 — bypass the IB-survival guard. Without this flag, "
            "rows whose (symbol, direction) is still in IB's pushed "
            "snapshot are skipped to avoid orphaning real positions. "
            "Pass --force to close everything regardless of IB state."
        ),
    )
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

    result = reset_open_trades(
        db=db, symbols=args.symbols, dry_run=args.dry_run, force=args.force,
    )

    if args.json:
        import json
        print(json.dumps(result, default=str, indent=2))
    else:
        print(render_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
