#!/usr/bin/env python3
"""
diag_pathb_pipelines.py  (READ-ONLY)

Proves the two Path-B root causes before we touch code:

  A. EV / r_outcomes — is the close path actually feeding R-multiples into
     `strategy_stats`? If r_outcomes is empty / EV=0 across the board while
     bot_trades HAS closed trades with the raw fields to compute R, the close
     path is bypassing stats.record_r_outcome().

  B. catalyst — is any news / fundamentals-catalyst data actually present in
     the DB for the scanner to surface? If the news collection is empty/stale
     and the fundamentals cache has no catalyst, has_catalyst=false is a DATA
     problem, not a scoring bug.

Usage on the DGX:
    python3 /tmp/diag_pathb_pipelines.py

Read-only. Nothing is written.
"""
import os
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


def _hdr(t):
    print("\n" + "=" * 72); print(t); print("=" * 72)


def main():
    from pymongo import MongoClient
    mongo_url, db_name = _load_env()
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    cols = set(db.list_collection_names())
    print(f"DB: {db_name}   collections: {len(cols)}")

    # ---------------- A. EV / strategy_stats ----------------
    _hdr("A1) strategy_stats — do setups have r_outcomes recorded? (EV source)")
    if "strategy_stats" not in cols:
        print("  !! collection 'strategy_stats' does NOT exist.")
    else:
        docs = list(db["strategy_stats"].find())
        print(f"  docs: {len(docs)}")
        print(f"  {'setup_type':22s} {'trig':>5} {'won':>4} {'win%':>6} "
              f"{'#r_out':>6} {'EV_r':>7}  last_updated")
        n_with_r = 0
        for d in sorted(docs, key=lambda x: -(x.get('alerts_triggered', 0))):
            r = d.get("r_outcomes") or []
            if len(r) > 0:
                n_with_r += 1
            wr = d.get("win_rate", 0) or 0
            print(f"  {str(d.get('setup_type','?'))[:22]:22s} "
                  f"{d.get('alerts_triggered',0):>5} {d.get('alerts_won',0):>4} "
                  f"{wr*100:>5.0f}% {len(r):>6} {d.get('expected_value_r',0.0):>7.2f}  "
                  f"{str(d.get('last_updated',''))[:19]}")
        print(f"\n  => setups WITH >=1 r_outcome: {n_with_r}/{len(docs)}  "
              f"(if ~0, the close path is NOT feeding stats.record_r_outcome)")
        print(f"  => setups with >=5 r_outcomes (EV unlocks at 5): "
              f"{sum(1 for d in docs if len(d.get('r_outcomes') or []) >= 5)}/{len(docs)}")

    # ---------------- A2. bot_trades raw R availability ----------------
    _hdr("A2) bot_trades — are there CLOSED trades with the fields to compute R?")
    if "bot_trades" not in cols:
        print("  !! collection 'bot_trades' does NOT exist.")
    else:
        bt = db["bot_trades"]
        total = bt.count_documents({})
        # closed = has an exit/close marker
        closed_q = {"$or": [
            {"status": {"$in": ["closed", "exited", "stopped", "filled_closed", "complete"]}},
            {"exit_price": {"$exists": True, "$ne": None}},
            {"close_reason": {"$exists": True, "$ne": None}},
            {"actual_pnl": {"$exists": True, "$ne": None}},
        ]}
        closed = bt.count_documents(closed_q)
        print(f"  total bot_trades: {total}   closed-ish: {closed}")
        sample = list(bt.find(closed_q).sort([("_id", -1)]).limit(200))
        if sample:
            fields = ["actual_r_multiple", "actual_pnl", "pnl", "realized_pnl",
                      "exit_price", "stop_loss", "entry_price", "current_price",
                      "target", "direction", "setup_type", "alert_id", "close_reason"]
            print(f"  field population over last {len(sample)} closed trades:")
            for f in fields:
                n = sum(1 for d in sample if d.get(f) not in (None, "", 0))
                print(f"    {f:20s} {n:>4}/{len(sample)}  {100*n/len(sample):5.1f}%")
            nz_r = sum(1 for d in sample if d.get("actual_r_multiple") not in (None, 0))
            print(f"\n  => closed trades carrying a non-zero actual_r_multiple: "
                  f"{nz_r}/{len(sample)}")

    # ---------------- A3. alert_outcomes (pnl_compute write target) ----------------
    _hdr("A3) alert_outcomes — the modern close-path write target")
    for cand in ("alert_outcomes", "bot_trade_outcomes", "trade_outcomes"):
        if cand in cols:
            c = db[cand]
            n = c.count_documents({})
            last = list(c.find().sort([("_id", -1)]).limit(1))
            keys = sorted(last[0].keys()) if last else []
            print(f"  {cand}: {n} docs")
            if last:
                rkeys = [k for k in keys if "r_mult" in k.lower() or k.lower() in
                         ("r", "r_outcome", "ev_r")]
                print(f"     sample keys: {keys}")
                print(f"     R-ish keys present: {rkeys or 'NONE'}")

    # ---------------- B. catalyst / news ----------------
    _hdr("B1) news collections — is any ticker news actually stored & fresh?")
    news_cols = [c for c in cols if "news" in c.lower()]
    if not news_cols:
        print("  (no collection with 'news' in the name — news may be in-memory/pushed only)")
    for nc in news_cols:
        c = db[nc]
        n = c.count_documents({})
        last = list(c.find().sort([("_id", -1)]).limit(1))
        ts = ""
        if last:
            for k in ("timestamp", "datetime", "created_at", "time", "as_of"):
                if last[0].get(k):
                    ts = str(last[0][k]); break
        print(f"  {nc}: {n} docs   most-recent ts: {ts or '?'}")

    _hdr("B2) fundamentals cache — does it carry any catalyst signal?")
    fcands = [c for c in cols if "fundamental" in c.lower() or "catalyst" in c.lower()]
    for fc in fcands:
        c = db[fc]
        n = c.count_documents({})
        sample = list(c.find().limit(300))
        with_cat = 0
        for d in sample:
            if d.get("has_catalyst") or d.get("catalyst_type") or d.get("catalyst") \
               or d.get("has_recent_news"):
                with_cat += 1
        print(f"  {fc}: {n} docs   with a catalyst/news flag (of {len(sample)} sampled): {with_cat}")
        if sample:
            print(f"     sample doc keys: {sorted(sample[0].keys())[:25]}")

    print("\n" + "=" * 72)
    print("Done. Read-only.")
    print("=" * 72)


if __name__ == "__main__":
    main()
