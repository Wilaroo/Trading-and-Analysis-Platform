#!/usr/bin/env python3
"""
backfill_strategy_stats.py

Aggregates closed-trade R-multiples from `alert_outcomes` into the
`strategy_stats` collection that the TQS Setup pillar reads (via
enhanced_scanner._load_strategy_stats). This reconnects the EV / real-win-rate
pipeline that broke when the close path migrated to pnl_compute and orphaned
the scanner's record_alert_outcome().

DEFAULT = DRY RUN (prints the full per-setup table, writes nothing).
Pass --commit to upsert into strategy_stats.

  python3 /tmp/backfill_strategy_stats.py            # preview
  python3 /tmp/backfill_strategy_stats.py --commit   # write

Keying + EV formula match the runtime exactly:
  base_setup = setup_type.split("_long")[0].split("_short")[0]
  EV = win_rate*avg_win_r - (1-win_rate)*avg_loss_r   (only if >=5 r_outcomes)
"""
import os
import argparse
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone


def _load_env():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (mongo_url and db_name) or not os.path.exists(c):
            continue
        for line in open(c):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "MONGO_URL" and not mongo_url:
                mongo_url = v
            elif k == "DB_NAME" and not db_name:
                db_name = v
    return mongo_url or "mongodb://localhost:27017", db_name or "tradecommand"


def base_setup(st):
    return str(st or "").split("_long")[0].split("_short")[0]


WIN_TOK = {"won", "win", "winner", "target", "target_hit", "profit", "tp",
           "take_profit", "profit_target"}
LOSS_TOK = {"lost", "loss", "loser", "stopped", "stop", "stop_hit",
            "stopped_out", "sl", "stop_loss"}


def _classify(outcome, r, pnl):
    """Return 'win' / 'loss' / None using outcome string, then r, then pnl."""
    o = str(outcome or "").lower().strip()
    if o in WIN_TOK:
        return "win"
    if o in LOSS_TOK:
        return "loss"
    if r is not None:
        return "win" if r > 0 else "loss"
    if pnl:
        return "win" if pnl > 0 else "loss"
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually write strategy_stats")
    args = ap.parse_args()

    from pymongo import MongoClient
    mongo_url, db_name = _load_env()
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    rows = list(db["alert_outcomes"].find())
    print(f"DB: {db_name}   alert_outcomes docs: {len(rows)}")
    if not rows:
        print("Nothing to aggregate."); return

    # self-documentation
    print("\noutcome value distribution:",
          dict(Counter(str(r.get("outcome", "?")).lower() for r in rows)))
    rmult_present = sum(1 for r in rows if _f(r.get("r_multiple")) is not None)
    print(f"r_multiple present: {rmult_present}/{len(rows)}")
    print("sample setup_types -> base:",
          {st: base_setup(st) for st in
           list({r.get("setup_type", "?") for r in rows})[:8]})

    # aggregate
    agg = defaultdict(lambda: {"trig": 0, "won": 0, "lost": 0, "skip": 0,
                               "r": [], "pnl": 0.0})
    # stable order by closed_at then _id so "last 100" is the most recent
    def _key(d):
        return (str(d.get("closed_at", "")), str(d.get("_id", "")))
    for d in sorted(rows, key=_key):
        bs = base_setup(d.get("setup_type"))
        if not bs:
            continue
        r = _f(d.get("r_multiple"))
        pnl = _f(d.get("net_pnl"))
        if pnl is None:
            pnl = _f(d.get("pnl")) or 0.0
        cls = _classify(d.get("outcome"), r, pnl)
        a = agg[bs]
        if cls is None:
            a["skip"] += 1
            continue
        a["trig"] += 1
        a["won" if cls == "win" else "lost"] += 1
        a["pnl"] += pnl or 0.0
        if r is not None:
            a["r"].append(r)

    # build docs
    docs = {}
    now = datetime.now(timezone.utc).isoformat()
    for bs, a in agg.items():
        r_out = a["r"][-100:]
        trig = a["trig"]
        win_rate = (a["won"] / trig) if trig else 0.0
        wins_r = [x for x in r_out if x > 0]
        losses_r = [x for x in r_out if x <= 0]
        avg_win_r = (sum(wins_r) / len(wins_r)) if wins_r else 0.0
        avg_loss_r = abs(sum(losses_r) / len(losses_r)) if losses_r else 1.0
        ev = 0.0
        if len(r_out) >= 5:
            ev = (win_rate * avg_win_r) - ((1 - win_rate) * avg_loss_r)
        avg_rr = (sum(r_out) / len(r_out)) if r_out else 0.0
        profit_factor = (sum(wins_r) / abs(sum(losses_r))) if losses_r and sum(losses_r) != 0 else 0.0
        docs[bs] = {
            "setup_type": bs,
            "total_alerts": trig,
            "alerts_triggered": trig,
            "alerts_won": a["won"],
            "alerts_lost": a["lost"],
            "total_pnl": round(a["pnl"], 2),
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "avg_rr_achieved": round(avg_rr, 3),
            "last_updated": now,
            "r_outcomes": [round(x, 4) for x in r_out],
            "avg_win_r": round(avg_win_r, 4),
            "avg_loss_r": round(avg_loss_r, 4),
            "expected_value_r": round(ev, 4),
        }

    # report
    print("\n" + "=" * 84)
    print(f"  {'base_setup':22s} {'trig':>5} {'won':>4} {'win%':>6} {'#r':>4} "
          f"{'avgR':>6} {'EV_r':>7} {'skip':>5}")
    print("=" * 84)
    for bs in sorted(docs, key=lambda k: -docs[k]["alerts_triggered"]):
        d = docs[bs]
        ev_unlocked = "" if len(d["r_outcomes"]) >= 5 else "  (EV<5 locked)"
        print(f"  {bs[:22]:22s} {d['alerts_triggered']:>5} {d['alerts_won']:>4} "
              f"{d['win_rate']*100:>5.0f}% {len(d['r_outcomes']):>4} "
              f"{d['avg_rr_achieved']:>6.2f} {d['expected_value_r']:>7.2f} "
              f"{agg[bs]['skip']:>5}{ev_unlocked}")
    n_ev = sum(1 for d in docs.values() if len(d["r_outcomes"]) >= 5)
    print(f"\nsetups: {len(docs)}   with >=5 r_outcomes (EV unlocked): {n_ev}")

    if not args.commit:
        print("\nDRY RUN — nothing written. Re-run with --commit to upsert into strategy_stats.")
        return

    coll = db["strategy_stats"]
    for bs, d in docs.items():
        coll.update_one({"setup_type": bs}, {"$set": d}, upsert=True)
    print(f"\n✅ COMMITTED — upserted {len(docs)} docs into strategy_stats.")
    print("   Restart the backend (./start_backend.sh --force) so _load_strategy_stats picks them up.")


if __name__ == "__main__":
    main()
