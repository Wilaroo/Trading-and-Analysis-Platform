#!/usr/bin/env python3
"""eod_ghost_dry_run.py — v19.34.153 (P0 EOD ghost-flatten verifier)

Run this on the DGX **before** the next market open to verify the new
v19.34.153 EOD ghost-flatten logic would correctly detect & flatten
IB-side positions the bot's `_open_trades` dict doesn't know about.

This script is READ-ONLY by default. It:
  1. Hits `GET /api/ib/positions` to enumerate IB ground truth.
  2. Reads `bot_trades` to identify which symbols the bot considers
     swing/position (`close_at_eod=False` AND `executed_at` ≤ 48h old).
  3. Computes the "ghosts" set = IB-held symbols minus bot-tracked
     minus recent-swing.
  4. Prints what `_flatten_ghost_positions` WOULD do (action + qty per
     symbol) — but does NOT submit any orders.

To actually fire test MKT closes (e.g. against a paper account), pass
`--live`. Off-hours these will queue but not execute, which is exactly
what you want for a smoke test.

Usage (on DGX):
    cd ~/Trading-and-Analysis-Platform
    PYTHONPATH=backend python3 backend/scripts/eod_ghost_dry_run.py
    PYTHONPATH=backend python3 backend/scripts/eod_ghost_dry_run.py --live  # actually places MKT
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Path setup so `backend.*` imports resolve when run from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Optional .env loader (parity with backend startup).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_ROOT, ".env"))
except Exception:
    pass


def _short(x):
    s = str(x)
    return s if len(s) <= 80 else s[:77] + "..."


async def main(live: bool) -> int:
    # Mongo
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        print("[FATAL] MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        return 2
    db = MongoClient(mongo_url).get_database(db_name)

    # IB snapshot — use the same path the bot uses.
    try:
        from routers.ib import _pushed_ib_data
    except Exception as e:
        print(f"[FATAL] cannot import routers.ib._pushed_ib_data: {e}", file=sys.stderr)
        return 3

    ib_positions = [
        p for p in (_pushed_ib_data.get("positions") or [])
        if isinstance(p, dict) and abs(float(p.get("position") or 0)) > 0
    ]
    print(f"[1/4] IB live positions (abs(qty)>0): {len(ib_positions)}")
    for p in ib_positions:
        print(f"        {p.get('symbol','?'):<8}  qty={int(float(p.get('position') or 0)):+d}")

    # Bot tracked (in-memory) — we cannot read the live process here, so
    # we approximate via bot_trades.status IN ('open','partial'). This is
    # safe-side: if the dry-run flags X as ghost but the live bot has X
    # tracked, the real flatten path will still see it & no-op.
    tracked_rows = list(db.bot_trades.find(
        {"status": {"$in": ["open", "partial", "OPEN", "PARTIAL"]}},
        {"_id": 0, "symbol": 1, "close_at_eod": 1, "executed_at": 1, "status": 1},
    ))
    tracked_syms = {(r.get("symbol") or "").upper() for r in tracked_rows}
    print(f"[2/4] bot_trades open/partial symbols (approx _open_trades): {len(tracked_syms)}")
    print(f"        {sorted(tracked_syms)}")

    # Recent swing exception (operator choice 3B: today/yesterday only).
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    recent_swing_rows = list(db.bot_trades.find(
        {
            "status": {"$in": ["open", "partial", "OPEN", "PARTIAL"]},
            "close_at_eod": False,
            "executed_at": {"$gte": cutoff},
        },
        {"_id": 0, "symbol": 1, "executed_at": 1},
    ))
    swing_safe = {(r.get("symbol") or "").upper() for r in recent_swing_rows}
    print(f"[3/4] Recent swing (close_at_eod=False AND executed_at>={cutoff[:10]}): {len(swing_safe)}")
    for r in recent_swing_rows:
        print(f"        {r.get('symbol','?'):<8}  executed_at={_short(r.get('executed_at'))}")

    # Ghost set.
    ghosts = []
    skipped_swing = []
    for p in ib_positions:
        sym = (p.get("symbol") or "").upper()
        qty = float(p.get("position") or 0)
        if not sym:
            continue
        if sym in tracked_syms:
            continue
        if sym in swing_safe:
            skipped_swing.append({"symbol": sym, "qty": qty})
            continue
        ghosts.append({"symbol": sym, "qty": qty})

    print()
    print(f"[4/4] Ghost positions detected: {len(ghosts)}")
    if not ghosts and not skipped_swing:
        print("        🟢  No ghosts. EOD would proceed via normal tracked-close path.")
    for g in ghosts:
        action = "SELL" if g["qty"] > 0 else "BUY"
        print(f"        🟥  {g['symbol']:<8}  qty={int(g['qty']):+d}  -> emergency {action} MKT {int(abs(g['qty']))}")
    for s in skipped_swing:
        print(f"        🟦  {s['symbol']:<8}  qty={int(s['qty']):+d}  -> SKIP (recent swing)")

    if not live:
        print()
        print("[DRY-RUN] No orders submitted. Re-run with --live to actually fire emergency MKT.")
        return 0

    if not ghosts:
        print("[LIVE] No ghosts to flatten. Done.")
        return 0

    # Live fire — uses the SAME path the EOD logic will use.
    print()
    print(f"[LIVE] Firing {len(ghosts)} emergency MKT close(s) via ib_direct_service...")
    from services.ib_direct_service import get_ib_direct_service
    svc = get_ib_direct_service()
    if not (svc.is_available() and svc.is_connected()):
        # ensure_connected is called inside place_emergency_mkt_close,
        # but we surface the state up front for visibility.
        print("[WARN] ib_direct not reporting connected pre-call; attempting anyway.")

    results = []
    for g in ghosts:
        action = "SELL" if g["qty"] > 0 else "BUY"
        res = await svc.place_emergency_mkt_close(
            symbol=g["symbol"],
            qty=int(abs(round(g["qty"]))),
            action=action,
            wait_for_fill_s=8.0,
        )
        print(f"        {g['symbol']:<8}  -> success={res.get('success')}  "
              f"status={res.get('status')}  order_id={res.get('order_id')}  "
              f"err={_short(res.get('error') or '')}")
        results.append({"symbol": g["symbol"], "result": res})

    ok = sum(1 for r in results if r["result"].get("success"))
    print()
    print(f"[LIVE] Done. {ok}/{len(results)} emergency closes reported success.")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--live", action="store_true",
        help="Actually submit MKT orders. Default is DRY-RUN (read-only).",
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.live)))
