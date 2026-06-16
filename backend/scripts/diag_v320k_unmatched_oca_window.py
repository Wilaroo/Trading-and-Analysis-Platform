#!/usr/bin/env python3
"""diag_v320k_unmatched_oca_window.py  —  v19.34.320k READ-ONLY diag  (2026-06-16)

Investigates WHY ib_executions fails to match most OCA-closed trades (the "77
unmatched June OCA trades", Issue 3). For each `oca_closed_externally_v19_31`
row it probes the close-side fill across EXPANDING windows and buckets the
reason a match is/ isn't found:

  matched@15m / matched@60m / matched@1d-sameday
  symbol_has_execs_but_no_time_match   (window or time-format problem)
  symbol_absent_from_ib_executions     (data retention / never ingested)
  no_closed_at                         (can't anchor a window)

Also reports ib_executions coverage (count, min/max time, #symbols) and any
symbol-CASE mismatches. READ-ONLY — no writes.

FLAGS: --days N  --symbol SYM  --limit N (default 1000)  --verbose
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

CLOSE_REASON = "oca_closed_externally_v19_31"


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


def _exec_time(ex):
    for k in ("time", "timestamp", "exec_time", "execution_time", "executed_at", "ts"):
        if ex.get(k):
            return _parse_dt(ex.get(k))
    return None


def _close_side_match(ex, direction):
    eside = str(ex.get("side") or ex.get("action") or "").upper()
    want = "BUY" if direction == "short" else "SELL"
    if want == "SELL":
        return eside.startswith("S")
    return eside.startswith("B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--symbol", type=str, default=None)
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    db = _connect()
    ibx = db["ib_executions"]

    # ── ib_executions coverage ──
    total_x = ibx.estimated_document_count()
    times = [_exec_time(e) for e in ibx.find({}, {"_id": 0}).sort([("$natural", -1)]).limit(5000)]
    times = [t for t in times if t]
    syms = ibx.distinct("symbol")
    hr("ib_executions coverage")
    print(f"  total docs (est)      : {total_x:,}")
    print(f"  distinct symbols      : {len(syms)}")
    if times:
        print(f"  time range (last 5000): {min(times).isoformat()}  →  {max(times).isoformat()}")
    sym_set = {str(s).upper() for s in syms}

    # ── OCA-closed rows ──
    q = {"close_reason": CLOSE_REASON}
    if args.symbol:
        q["symbol"] = args.symbol.upper()
    if args.days is not None:
        q["closed_at"] = {"$gte": (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()}
    rows = list(db["bot_trades"].find(
        q, {"_id": 0, "id": 1, "symbol": 1, "direction": 1, "shares": 1, "closed_at": 1}
    ).sort("closed_at", -1).limit(args.limit))

    hr(f"OCA close-side match investigation  (rows={len(rows)})")
    buckets = Counter()
    case_mismatch = 0
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        direction = (r.get("direction") or "long").lower()
        closed = _parse_dt(r.get("closed_at"))
        if closed is None:
            buckets["no_closed_at"] += 1
            continue
        if sym not in sym_set:
            buckets["symbol_absent_from_ib_executions"] += 1
            continue
        # pull ALL execs for the symbol (case-insensitive), classify by window
        sym_execs = list(ibx.find({"symbol": {"$regex": f"^{sym}$", "$options": "i"}}, {"_id": 0}))
        if any((e.get("symbol") or "") != sym for e in sym_execs):
            case_mismatch += 1
        close_execs = [(e, _exec_time(e)) for e in sym_execs if _close_side_match(e, direction)]
        close_execs = [(e, t) for e, t in close_execs if t is not None]
        if not close_execs:
            buckets["symbol_has_execs_but_no_close_side"] += 1
            continue
        deltas = [abs((t - closed).total_seconds()) for _, t in close_execs]
        nearest = min(deltas)
        if nearest <= 15 * 60:
            buckets["matched@15m"] += 1
        elif nearest <= 60 * 60:
            buckets["matched@60m"] += 1
        elif nearest <= 24 * 3600:
            buckets["matched@1d"] += 1
        else:
            buckets["nearest_exec_>1d_away"] += 1
        if args.verbose:
            print(f"  {sym:6} {direction:5} closed={r.get('closed_at')}  nearest_close_exec={nearest/60:.1f}min")

    hr("SUMMARY — why ib_executions matched / didn't")
    for k, v in buckets.most_common():
        print(f"  {k:>36} : {v}")
    print(f"  {'symbol CASE mismatches seen':>36} : {case_mismatch}")
    matched = buckets["matched@15m"]
    print(f"\n  Interpretation:")
    print(f"   • matched@15m is what the LIVE v320h.1 cross-check + diag use.")
    print(f"   • matched@60m / matched@1d  → window is TOO NARROW (widen ±15m).")
    print(f"   • symbol_absent_from_ib_executions → DATA RETENTION (execs not kept "
          f"that far back; implied_from_realized is the only basis — already primary).")
    print(f"   • symbol_has_execs_but_no_close_side → side-field/partial-fill issue.")
    print(f"\n  READ-ONLY — no writes performed.")


if __name__ == "__main__":
    main()
