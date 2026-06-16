#!/usr/bin/env python3
"""diag_v320h_oca_finalize_preview.py  —  v19.34.320h READ-ONLY preview  (2026-06-16)

Replays the v19.34.320h OCA close-finalize logic over existing `bot_trades`
rows closed by the v19.31 external-close sweep (`close_reason =
"oca_closed_externally_v19_31"`) and prints EXACTLY what `fix` mode WOULD write
— without touching anything. Doubles as the inventory + accuracy check before
flipping V320H_OCA_FIX_POLICY=fix, and as the planning input for a historical
backfill repair.

The probe mirrors the deployed patch byte-for-byte:
  • close leg  : long → SELL, short → BUY
  • exit_price : best-qty-match `ib_executions` close-side fill within ±15m of
                 `closed_at`; falls back to last `current_price` mark.
  • net_pnl    : round(realized_pnl - total_commissions, 2)
  • pnl_pct    : long  → (exit_price - entry_basis)/entry_basis*100
                 short → (entry_basis - exit_price)/entry_basis*100
                 entry_basis = fill_price || entry_price
It ADDITIONALLY classifies the leg (stop vs target) using order-id match then
price proximity — informational only (the patch itself sets just exit_price /
net_pnl / pnl_pct).

READ-ONLY. No writes. No collections created.

FLAGS:
  --days N      only rows whose closed_at >= now-N days  (default: all)
  --symbol SYM  restrict to one symbol
  --limit N     cap rows examined (default 500, newest closed_at first)
  --only-corrupt  only show rows that look corrupted (net_pnl==-1.0 or exit_price missing)
  --verbose     print every row (default prints corrupt rows + a sample)
"""
import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

CLOSE_REASON = "oca_closed_externally_v19_31"
WINDOW_MIN = 15
SENTINEL_NET = -1.0
EPS = 0.0001


def hr(t):
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def _connect():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    return MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]


def _parse_dt(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
    else:
        d = raw
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _norm_side(s):
    return str(s or "").upper()


def _find_close_exec(db, symbol, direction, closed_dt, want_shares):
    """Mirror of the patch probe. Returns (exit_px, src, exec_doc | None)."""
    if closed_dt is None:
        return None, None, None
    close_side = "BUY" if direction == "short" else "SELL"
    lo = (closed_dt - timedelta(minutes=WINDOW_MIN)).isoformat()
    hi = (closed_dt + timedelta(minutes=WINDOW_MIN)).isoformat()
    q = {
        "symbol": (symbol or "").upper(),
        "$or": [
            {"time": {"$gte": lo, "$lte": hi}},
            {"timestamp": {"$gte": lo, "$lte": hi}},
            {"exec_time": {"$gte": lo, "$lte": hi}},
        ],
    }
    try:
        execs = list(db["ib_executions"].find(q, {"_id": 0}))
    except Exception as e:
        print(f"    ib_executions read failed: {e}")
        execs = []
    best = None
    best_doc = None
    best_score = None
    for ex in execs:
        eside = _norm_side(ex.get("side") or ex.get("action"))
        if close_side == "SELL" and not eside.startswith("S"):
            continue
        if close_side == "BUY" and not eside.startswith("B"):
            continue
        epx = float(ex.get("price") or ex.get("avg_price") or ex.get("fill_price") or 0)
        if epx <= 0:
            continue
        eqty = int(abs(float(ex.get("shares") or ex.get("qty") or 0)))
        score = abs(eqty - int(want_shares or 0))
        if best_score is None or score < best_score:
            best_score = score
            best = epx
            best_doc = ex
    if best is not None:
        return round(best, 4), "ib_executions", best_doc
    return None, None, None


def _classify_leg(exec_doc, exit_px, stop_oid, target_oids, stop_price, target_price):
    """Informational: stop vs target. order-id match first, then price proximity."""
    if exec_doc is not None:
        eoid = str(exec_doc.get("order_id") or exec_doc.get("orderId") or "")
        if eoid:
            if stop_oid and str(stop_oid) == eoid:
                return "stop_loss_via_oca"
            if any(str(t) == eoid for t in (target_oids or [])):
                return "target_hit_via_oca"
    if exit_px is not None and (stop_price or target_price):
        ds = abs(exit_px - stop_price) if stop_price else float("inf")
        dt = abs(exit_px - target_price) if target_price else float("inf")
        if ds < dt:
            return "stop_loss_via_oca_price_match"
        if dt < ds:
            return "target_hit_via_oca_price_match"
    return "unclassified"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--symbol", type=str, default=None)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--only-corrupt", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    db = _connect()
    bt = db["bot_trades"]

    query = {"close_reason": CLOSE_REASON}
    if args.symbol:
        query["symbol"] = args.symbol.upper()
    if args.days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        query["closed_at"] = {"$gte": cutoff}

    proj = {
        "_id": 0, "id": 1, "symbol": 1, "direction": 1, "shares": 1, "status": 1,
        "entry_price": 1, "fill_price": 1, "exit_price": 1,
        "realized_pnl": 1, "net_pnl": 1, "pnl_pct": 1, "total_commissions": 1,
        "closed_at": 1, "stop_order_id": 1, "target_order_ids": 1,
        "stop_price": 1, "primary_target": 1, "target_price": 1,
    }
    rows = list(bt.find(query, proj).sort("closed_at", -1).limit(args.limit))

    hr(f"v320h preview — close_reason={CLOSE_REASON!r}  "
       f"(days={args.days} symbol={args.symbol} limit={args.limit})")
    print(f"  rows examined: {len(rows)}")
    if not rows:
        print("  no matching rows. Nothing to preview.")
        return

    n_corrupt = 0
    n_from_exec = 0
    n_from_fallback = 0
    n_unresolved = 0
    total_net_before = 0.0
    total_net_after = 0.0
    leg_counts = {}
    shown = 0

    for r in rows:
        sym = r.get("symbol")
        direction = (r.get("direction") or "long").lower()
        shares = r.get("shares") or 0
        entry_basis = float(r.get("fill_price") or r.get("entry_price") or 0)
        realized = float(r.get("realized_pnl") or 0)
        commissions = float(r.get("total_commissions") or 0)
        cur_net = r.get("net_pnl")
        cur_exit = r.get("exit_price")
        cur_pct = r.get("pnl_pct")
        closed_dt = _parse_dt(r.get("closed_at"))

        is_corrupt = (cur_exit is None) or (
            cur_net is not None and abs(float(cur_net) - SENTINEL_NET) < EPS)
        if is_corrupt:
            n_corrupt += 1
        if args.only_corrupt and not is_corrupt:
            continue

        exit_px, src, exec_doc = _find_close_exec(db, sym, direction, closed_dt, shares)
        if exit_px is None:
            cp = float(r.get("current_price") or 0)
            if cp > 0:
                exit_px, src = round(cp, 4), "current_price_fallback"
        if src == "ib_executions":
            n_from_exec += 1
        elif src == "current_price_fallback":
            n_from_fallback += 1
        else:
            n_unresolved += 1

        new_net = round(realized - commissions, 2)
        new_pct = None
        if exit_px is not None and entry_basis > 0:
            if direction == "short":
                new_pct = round((entry_basis - exit_px) / entry_basis * 100, 4)
            else:
                new_pct = round((exit_px - entry_basis) / entry_basis * 100, 4)

        leg = _classify_leg(
            exec_doc, exit_px,
            r.get("stop_order_id"), r.get("target_order_ids"),
            r.get("stop_price"),
            r.get("primary_target") or r.get("target_price"))
        leg_counts[leg] = leg_counts.get(leg, 0) + 1

        if cur_net is not None:
            total_net_before += float(cur_net)
        total_net_after += new_net

        if args.verbose or is_corrupt or shown < 20:
            shown += 1
            print(f"\n  [{r.get('id')}] {sym} {direction.upper()} x{shares}  closed={r.get('closed_at')}")
            print(f"      entry_basis={entry_basis}  realized_pnl={realized}  commissions={commissions}")
            print(f"      exit_price : {cur_exit!r:>14}  →  {exit_px!r}   ({src})")
            print(f"      net_pnl    : {cur_net!r:>14}  →  {new_net!r}")
            print(f"      pnl_pct    : {cur_pct!r:>14}  →  {new_pct!r}")
            print(f"      leg        : {leg}")

    hr("SUMMARY")
    print(f"  rows examined            : {len(rows)}")
    print(f"  corrupt (net==-1 / no exit): {n_corrupt}")
    print(f"  exit resolvable from ib_executions : {n_from_exec}")
    print(f"  exit from current_price fallback   : {n_from_fallback}")
    print(f"  exit UNRESOLVED (no exec, no mark) : {n_unresolved}")
    print(f"  net_pnl total  before → after : {round(total_net_before,2)}  →  {round(total_net_after,2)}  "
          f"(Δ {round(total_net_after-total_net_before,2)})")
    print(f"  leg classification:")
    for k, v in sorted(leg_counts.items(), key=lambda x: -x[1]):
        print(f"      {k:>34} : {v}")
    print("\n  READ-ONLY — no writes performed. This is what `fix` mode would compute.")


if __name__ == "__main__":
    main()
