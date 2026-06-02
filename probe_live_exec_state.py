#!/usr/bin/env python3
"""
probe_live_exec_state.py  (READ-ONLY)

Proves the DIRECT-pymongo read of trade_outcomes (what v219 will wire into the
Execution pillar, bypassing the flaky learning_loop reference) returns real
recent_win_rate + trailing consecutive_losses. Writes nothing.
"""
import os


def _load_env():
    url = os.environ.get("MONGO_URL"); name = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (url and name) or not os.path.exists(c):
            continue
        for line in open(c):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1); k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "MONGO_URL" and not url:
                url = v
            elif k == "DB_NAME" and not name:
                name = v
    return url or "mongodb://localhost:27017", name or "tradecommand"


def main():
    from pymongo import MongoClient
    url, name = _load_env()
    db = MongoClient(url, serverSelectionTimeoutMS=5000)[name]
    docs = list(db["trade_outcomes"].find(
        {}, {"outcome": 1, "actual_r": 1, "created_at": 1, "symbol": 1}
    ).sort("created_at", -1).limit(30))
    print(f"DB: {name}   trade_outcomes (newest 30 read): {len(docs)}")
    if not docs:
        print("  ⬅ EMPTY — direct read returned nothing (unexpected, diag showed 99).")
        return

    print("  outcome field type:", type(docs[0].get("outcome")).__name__,
          "  sample value:", repr(docs[0].get("outcome")))

    wins = losses = consec = 0
    counting = True
    for d in docs:  # newest-first
        oc = str(d.get("outcome", "")).lower()
        if oc == "won":
            wins += 1; counting = False
        elif oc == "lost":
            losses += 1
            if counting:
                consec += 1
        else:
            counting = False
    sample = wins + losses
    wr = (wins / sample) if sample else None
    print(f"\n  sample(won+lost)   : {sample}")
    print(f"  recent_win_rate    : {wr}")
    print(f"  consecutive_losses : {consec}  (trailing streak from newest)")
    print("\n  newest 8:")
    for d in docs[:8]:
        print(f"    {str(d.get('created_at'))[:19]}  {str(d.get('symbol')):8s} "
              f"{str(d.get('outcome')):6s}  R={d.get('actual_r')}")
    print("\nIf sample>0 and win-rate/streak look real → v219 direct read is the fix.")


if __name__ == "__main__":
    main()
