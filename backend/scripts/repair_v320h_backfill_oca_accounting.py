#!/usr/bin/env python3
"""repair_v320h_backfill_oca_accounting.py  —  v19.34.320h backfill  (2026-06-16)

Backfills the three corrupted accounting fields on ALL `bot_trades` rows closed
by the v19.31 external-close sweep (`close_reason="oca_closed_externally_v19_31"`).

For each row it writes (only when they differ from current):
  • exit_price  ← implied_from_realized (PRIMARY, internally consistent):
                    long : entry_basis + realized_pnl/shares
                    short: entry_basis - realized_pnl/shares
                  entry_basis = fill_price || entry_price.
                  Falls back to ib_executions close-side fill (±15m) then
                  current_price ONLY if the implied basis is unavailable.
  • net_pnl     ← realized_pnl - total_commissions
  • pnl_pct     ← long : (exit-entry)/entry*100 ; short: (entry-exit)/entry*100

`close_reason` is LEFT UNTOUCHED (the price-proximity leg classifier is
unreliable — it tags winners as stops). ib_executions is recorded as an audit
cross-check (`ib_xcheck_px`, `ib_xcheck_delta`); rows whose delta exceeds
--review-threshold-pct are stamped `v320h_needs_review=True` (still repaired
with the consistent implied value).

SAFETY (mirrors v320g):
  • Per-row audit in `bot_trades_repair_audit_v320h` inserted BEFORE the update
    (crash-safe), carrying before/after + source + xcheck + the EXPECTED before
    values used as a race-guard in the update filter.
  • Idempotent: a row with an unrolled audit row is skipped; --apply re-probes.
  • Batched, ordered=False not needed (single-row updates).
  • Full --rollback restores before-values from the audit collection.

FLAGS:
  --check     dry-run: prints per-row diff + summary; no writes.
  --apply     writes; aborts a row if its before-values drifted from --check.
  --rollback  reverts all v320h repairs from the audit collection.
  --status    prints repaired/needs-review counts + sample audit rows.
  --days N / --symbol SYM / --limit N   scope filters (default: all rows).
  --review-threshold-pct F   flag rows where |ib-implied|/entry*100 > F (default 0.5).
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
AUDIT_COLL = "bot_trades_repair_audit_v320h"
ACTION = "oca_close_accounting_backfill"
WINDOW_MIN = 15
EPS = 0.005


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_v320h_oca_close_finalize_patcher.py)
# ---------------------------------------------------------------------------
def implied_exit(entry_basis, realized, shares, direction):
    if not (entry_basis and entry_basis > 0 and shares):
        return None
    if direction == "short":
        return round(entry_basis - realized / float(shares), 4)
    return round(entry_basis + realized / float(shares), 4)


def new_net_pnl(realized, commissions):
    return round(float(realized or 0) - float(commissions or 0), 2)


def new_pnl_pct(entry_basis, exit_px, direction):
    if exit_px is None or not (entry_basis and entry_basis > 0):
        return None
    if direction == "short":
        return round((entry_basis - exit_px) / entry_basis * 100, 4)
    return round((exit_px - entry_basis) / entry_basis * 100, 4)


def needs_repair(cur_exit, cur_net, cur_pct, new_exit, new_net, new_pct):
    def diff(a, b):
        if a is None and b is None:
            return False
        if a is None or b is None:
            return True
        return abs(float(a) - float(b)) > EPS
    return diff(cur_exit, new_exit) or diff(cur_net, new_net) or diff(cur_pct, new_pct)


# ---------------------------------------------------------------------------
def hr(t):
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def _connect():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    return MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]


def _now():
    return datetime.now(timezone.utc).isoformat()


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


def _ib_cross_check(db, symbol, direction, closed_dt, want_shares):
    if closed_dt is None:
        return None
    close_side = "BUY" if direction == "short" else "SELL"
    lo = (closed_dt - timedelta(minutes=WINDOW_MIN)).isoformat()
    hi = (closed_dt + timedelta(minutes=WINDOW_MIN)).isoformat()
    q = {"symbol": (symbol or "").upper(),
         "$or": [{"time": {"$gte": lo, "$lte": hi}},
                 {"timestamp": {"$gte": lo, "$lte": hi}},
                 {"exec_time": {"$gte": lo, "$lte": hi}}]}
    try:
        execs = list(db["ib_executions"].find(q, {"_id": 0}))
    except Exception:
        return None
    best, best_score = None, None
    for ex in execs:
        eside = str(ex.get("side") or ex.get("action") or "").upper()
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
            best_score, best = score, epx
    return round(best, 4) if best is not None else None


def _build_query(args):
    q = {"close_reason": CLOSE_REASON}
    if args.symbol:
        q["symbol"] = args.symbol.upper()
    if args.days is not None:
        q["closed_at"] = {"$gte": (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()}
    return q


def _plan_row(db, r, review_pct):
    """Returns plan dict or None if row needs no repair."""
    sym = r.get("symbol")
    direction = (r.get("direction") or "long").lower()
    shares = r.get("shares") or 0
    entry_basis = float(r.get("fill_price") or r.get("entry_price") or 0)
    realized = float(r.get("realized_pnl") or 0)
    commissions = float(r.get("total_commissions") or 0)
    cur_exit, cur_net, cur_pct = r.get("exit_price"), r.get("net_pnl"), r.get("pnl_pct")

    implied = implied_exit(entry_basis, realized, shares, direction)
    ib_px = _ib_cross_check(db, sym, direction, _parse_dt(r.get("closed_at")), shares)

    if implied is not None:
        exit_px, src = implied, "implied_from_realized"
    elif ib_px is not None:
        exit_px, src = ib_px, "ib_executions"
    else:
        cp = float(r.get("current_price") or 0)
        exit_px, src = (round(cp, 4), "current_price_fallback") if cp > 0 else (None, None)

    n_net = new_net_pnl(realized, commissions)
    n_pct = new_pnl_pct(entry_basis, exit_px, direction)

    if not needs_repair(cur_exit, cur_net, cur_pct, exit_px, n_net, n_pct):
        return None

    xdelta = round(abs(ib_px - implied), 4) if (ib_px is not None and implied is not None) else None
    needs_review = bool(xdelta is not None and entry_basis > 0
                        and (xdelta / entry_basis * 100) > review_pct)
    return {
        "id": r.get("id"), "symbol": sym, "direction": direction, "shares": shares,
        "before": {"exit_price": cur_exit, "net_pnl": cur_net, "pnl_pct": cur_pct},
        "after": {"exit_price": exit_px, "net_pnl": n_net, "pnl_pct": n_pct},
        "source": src, "ib_xcheck_px": ib_px, "ib_xcheck_delta": xdelta,
        "needs_review": needs_review,
    }


def cmd_check(args):
    db = _connect()
    rows = list(db["bot_trades"].find(_build_query(args), {"_id": 0}).sort("closed_at", -1).limit(args.limit))
    hr(f"v320h backfill DRY-RUN  (rows matched={len(rows)})")
    plans = []
    for r in rows:
        p = _plan_row(db, r, args.review_threshold_pct)
        if p:
            plans.append(p)
    shown = 0
    for p in plans:
        if shown < 40:
            shown += 1
            b, a = p["before"], p["after"]
            flag = "  ⚑REVIEW" if p["needs_review"] else ""
            print(f"  [{p['id']}] {p['symbol']} {p['direction'].upper()} x{p['shares']}  src={p['source']}"
                  f"  ib_xcheck={p['ib_xcheck_px']} d={p['ib_xcheck_delta']}{flag}")
            print(f"       exit_price {b['exit_price']!r} → {a['exit_price']!r} | "
                  f"net_pnl {b['net_pnl']!r} → {a['net_pnl']!r} | pnl_pct {b['pnl_pct']!r} → {a['pnl_pct']!r}")
    _summary(plans, "WOULD REPAIR")
    print("\n  DRY-RUN — no writes. Run --apply to write.")


def cmd_apply(args):
    db = _connect()
    bt, aud = db["bot_trades"], db[AUDIT_COLL]
    rows = list(bt.find(_build_query(args), {"_id": 0}).sort("closed_at", -1).limit(args.limit))
    hr(f"v320h backfill APPLY  (rows matched={len(rows)})")
    applied, skipped_noop, skipped_prior, raced = 0, 0, 0, 0
    plans = []
    for r in rows:
        p = _plan_row(db, r, args.review_threshold_pct)
        if not p:
            skipped_noop += 1
            continue
        if aud.find_one({"trade_id": p["id"], "action": ACTION, "rolled_back": {"$ne": True}}):
            skipped_prior += 1
            continue
        audit = {
            "trade_id": p["id"], "action": ACTION, "ts": _now(),
            "before": p["before"], "after": p["after"], "source": p["source"],
            "ib_xcheck_px": p["ib_xcheck_px"], "ib_xcheck_delta": p["ib_xcheck_delta"],
            "needs_review": p["needs_review"], "rolled_back": False,
            "self_sha256": _self_sha(),
        }
        aud_id = aud.insert_one(audit).inserted_id
        race_guard = {f"{k}": v for k, v in p["before"].items()}
        upd = {**p["after"], "v320h_repaired_at": _now(), "v320h_audit_ref": str(aud_id),
               "v320h_exit_source": p["source"], "v320h_ib_xcheck_px": p["ib_xcheck_px"],
               "v320h_ib_xcheck_delta": p["ib_xcheck_delta"], "v320h_needs_review": p["needs_review"]}
        res = bt.update_one({"id": p["id"], **race_guard}, {"$set": upd})
        if res.modified_count == 1:
            applied += 1
            plans.append(p)
        else:
            raced += 1
            aud.update_one({"_id": aud_id}, {"$set": {"rolled_back": True, "race_skip": True, "rolled_back_at": _now()}})
    print(f"  applied={applied}  skipped_noop={skipped_noop}  skipped_prior_audit={skipped_prior}  raced={raced}")
    _summary(plans, "REPAIRED")
    print(f"\n  rollback: .venv/bin/python {os.path.basename(__file__)} --rollback")


def cmd_rollback(args):
    db = _connect()
    bt, aud = db["bot_trades"], db[AUDIT_COLL]
    q = {"action": ACTION, "rolled_back": {"$ne": True}}
    if args.symbol:
        q["symbol"] = args.symbol.upper()
    audits = list(aud.find(q, {"_id": 1, "trade_id": 1, "before": 1}))
    hr(f"v320h backfill ROLLBACK  (audit rows={len(audits)})")
    n = 0
    for a in audits:
        bt.update_one({"id": a["trade_id"]},
                      {"$set": a["before"],
                       "$unset": {"v320h_repaired_at": "", "v320h_audit_ref": "",
                                  "v320h_exit_source": "", "v320h_ib_xcheck_px": "",
                                  "v320h_ib_xcheck_delta": "", "v320h_needs_review": ""}})
        aud.update_one({"_id": a["_id"]}, {"$set": {"rolled_back": True, "rolled_back_at": _now()}})
        n += 1
    print(f"  reverted {n} row(s) to before-values; audit rows marked rolled_back.")


def cmd_status(args):
    db = _connect()
    bt, aud = db["bot_trades"], db[AUDIT_COLL]
    repaired = bt.count_documents({"v320h_repaired_at": {"$exists": True}})
    review = bt.count_documents({"v320h_needs_review": True})
    audited = aud.count_documents({"action": ACTION})
    rolled = aud.count_documents({"action": ACTION, "rolled_back": True})
    hr("v320h backfill STATUS")
    print(f"  bot_trades repaired (stamped) : {repaired}")
    print(f"  flagged needs_review          : {review}")
    print(f"  audit rows (total / rolled)   : {audited} / {rolled}")
    for a in aud.find({"action": ACTION}, {"_id": 0}).sort("ts", -1).limit(8):
        print(f"    {a.get('ts')}  {a.get('trade_id')}  src={a.get('source')}  "
              f"review={a.get('needs_review')}  rolled={a.get('rolled_back')}")


def _summary(plans, label):
    by_src, n_review = {}, 0
    net_b, net_a = 0.0, 0.0
    for p in plans:
        by_src[p["source"]] = by_src.get(p["source"], 0) + 1
        if p["needs_review"]:
            n_review += 1
        if p["before"]["net_pnl"] is not None:
            net_b += float(p["before"]["net_pnl"])
        net_a += float(p["after"]["net_pnl"])
    print(f"\n  {label}: {len(plans)} row(s)")
    for k, v in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"      source {k:>26} : {v}")
    print(f"      flagged needs_review : {n_review}")
    print(f"      net_pnl total before → after : {round(net_b,2)} → {round(net_a,2)} (Δ {round(net_a-net_b,2)})")


def _self_sha():
    import hashlib
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--symbol", type=str, default=None)
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--review-threshold-pct", type=float, default=0.5)
    args = ap.parse_args()
    if args.check:
        cmd_check(args)
    elif args.apply:
        cmd_apply(args)
    elif args.rollback:
        cmd_rollback(args)
    elif args.status:
        cmd_status(args)


if __name__ == "__main__":
    main()
