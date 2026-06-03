#!/usr/bin/env python3
"""
v19.34.251 — SHADOW OUTCOME BACKFILL (recompute the broken historical metrics).

The v251 code fix makes NEW shadow decisions honest (direction + stop captured
at log time, direction-aware would_have_pnl, real would_have_r, real-fill
was_executed). But the ~4,407 historical decisions still carry the broken
values (would_have_r==0.00, direction-blind pnl, was_executed==proceed-flag),
which pollute the ShadowVsRealTile.

This script repairs them in place by joining each tracked shadow decision to
the nearest real `bot_trades` row for the same symbol to recover:
  • direction   (long/short)  → fixes direction-blind pnl
  • stop_price  (or stop_loss) → enables would_have_r
  • fill_price  (real entry)   → tightens the pnl base
  • trade_id    + was_executed → only flagged executed when a real fill exists
                                 within MATCH_WINDOW of the decision.

Decisions with NO matching bot_trade are treated as shadow-only (was_executed
set False) and, if a stop can't be recovered, would_have_r is left at 0 (the
honest "uncomputable" value) but would_have_pnl is still made direction-aware
when a direction is recoverable from the decision itself.

Run on DGX (DRY-RUN FIRST):
    .venv/bin/python backend/scripts/backfill_shadow_outcomes_v19_34_251.py --days 60 --dry-run
    .venv/bin/python backend/scripts/backfill_shadow_outcomes_v19_34_251.py --days 60 --commit
"""
import argparse
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[os.environ.get("DB_NAME", "tradecommand")]
db.client.admin.command("ping")
print(f"[db] {mongo_url}")

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=60)
ap.add_argument("--commit", action="store_true", help="write changes (default dry-run)")
ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (default)")
ap.add_argument("--match-window-min", type=int, default=120,
                help="±minutes to call a bot_trade a fill of the decision")
args = ap.parse_args()
COMMIT = args.commit and not args.dry_run
MATCH_WINDOW = args.match_window_min * 60
cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ── index bot_trades by symbol → [(dt, direction, stop, entry, trade_id)] ──
bt_idx = {}
for bt in db["bot_trades"].find(
    {"created_at": {"$gte": cutoff}},
    {"_id": 0, "symbol": 1, "created_at": 1, "executed_at": 1, "direction": 1,
     "stop_price": 1, "stop_loss": 1, "fill_price": 1, "entry_price": 1,
     "id": 1, "trade_id": 1}):
    sym = (bt.get("symbol") or "").upper()
    when = _dt(bt.get("executed_at") or bt.get("created_at"))
    if not sym or when is None:
        continue
    direction = str(bt.get("direction") or "long")
    direction = getattr(direction, "value", direction).lower()
    if direction not in ("long", "short"):
        direction = "long"
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
    entry = _f(bt.get("fill_price")) or _f(bt.get("entry_price"))
    tid = bt.get("trade_id") or bt.get("id") or ""
    bt_idx.setdefault(sym, []).append((when, direction, stop, entry, tid))


def nearest_fill(sym, sdt):
    rows = bt_idx.get(sym)
    if not rows or sdt is None:
        return None
    best = None
    for (when, direction, stop, entry, tid) in rows:
        gap = abs((when - sdt).total_seconds())
        if best is None or gap < best[0]:
            best = (gap, direction, stop, entry, tid)
    return best


tracked = list(db["shadow_decisions"].find(
    {"outcome_tracked": True,
     "$or": [{"timestamp": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]},
    {"_id": 0, "id": 1, "symbol": 1, "timestamp": 1, "created_at": 1,
     "direction": 1, "stop_price": 1, "price_at_decision": 1, "outcome_price": 1,
     "was_executed": 1, "would_have_pnl": 1, "would_have_r": 1}))

print(f"\n{'='*70}\nBACKFILL shadow outcomes — {len(tracked)} tracked decisions, "
      f"last {args.days}d  [{'COMMIT' if COMMIT else 'DRY-RUN'}]\n{'='*70}")

stats = Counter()
r_recovered = exec_corrected = pnl_flipped = 0

for d in tracked:
    sym = (d.get("symbol") or "").upper()
    sdt = _dt(d.get("timestamp") or d.get("created_at"))
    outcome = _f(d.get("outcome_price"))
    if outcome is None:
        stats["skip_no_outcome_price"] += 1
        continue

    match = nearest_fill(sym, sdt)
    is_fill = bool(match and match[0] <= MATCH_WINDOW)

    # Recover geometry: prefer matched bot_trade, else decision's own.
    direction = (match[1] if match else None) or str(d.get("direction") or "long").lower()
    if direction not in ("long", "short"):
        direction = "long"
    stop = (match[2] if match else None) or _f(d.get("stop_price"))
    entry = (match[3] if match else None) or _f(d.get("price_at_decision"))
    trade_id = match[4] if is_fill else ""

    if entry is None:
        stats["skip_no_entry"] += 1
        continue

    pnl = (entry - outcome) if direction == "short" else (outcome - entry)
    r = 0.0
    if stop and entry and abs(entry - stop) > 0:
        r = pnl / abs(entry - stop)

    new_set = {
        "direction": direction,
        "would_have_pnl": pnl,
        "would_have_r": r,
        "was_executed": is_fill,
        "backfilled_v19_34_251": True,
    }
    if stop:
        new_set["stop_price"] = stop
    if trade_id:
        new_set["trade_id"] = trade_id

    if r != 0 and (_f(d.get("would_have_r")) or 0) == 0:
        r_recovered += 1
    if bool(d.get("was_executed")) != is_fill:
        exec_corrected += 1
    old_pnl = _f(d.get("would_have_pnl")) or 0
    if (old_pnl > 0) != (pnl > 0):
        pnl_flipped += 1

    stats["matched_fill" if is_fill else "shadow_only"] += 1

    if COMMIT:
        db["shadow_decisions"].update_one({"id": d.get("id")}, {"$set": new_set})

print(f"\n  classification: {dict(stats)}")
print(f"  would_have_r recovered (was 0 → now ≠0): {r_recovered}")
print(f"  was_executed corrected:                  {exec_corrected}")
print(f"  pnl sign flipped (direction fix):        {pnl_flipped}")
print(f"\n  {'WROTE changes' if COMMIT else 'DRY-RUN — no writes. Re-run with --commit to apply.'}\n")
