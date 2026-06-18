#!/usr/bin/env python3
"""diag_v372 (READ-ONLY) — why did a HON scalp pass the v322m scalp share-ADV
floor when HON trades ~2.2M sh/day (< the 3M default)?

Reproduces EXACTLY what the gate sees (enhanced_scanner._get_share_adv_for_gate):
  1. symbol_adv_cache.avg_volume  (the gate's primary source)
  2. ib_historical_data 20-bar avg volume  (the gate's fallback when #1 == 0)
Then prints the live SCALP_MIN_SHARE_ADV / SCALP_MIN_RVOL the SCRIPT sees, the
backend/.env values, and every recent HON bot_trade (style/status/pnl/timestamps)
so the trade can be lined up against the v322m deploy date.

NOTHING WRITTEN. Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v372_hon_scalp_gate.py --symbol HON --days 14
"""
import os
import sys


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


def _env_file():
    env = {}
    try:
        with open("backend/.env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def main():
    from datetime import datetime, timedelta, timezone
    sym = _arg("--symbol", "HON", str).upper()
    days = _arg("--days", 14, int)
    env = _env_file()
    from pymongo import MongoClient
    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]

    print(f"\n=== v372 scalp-gate forensics — {sym} ===")

    # 1) gate primary source: symbol_adv_cache.avg_volume
    cache = db["symbol_adv_cache"].find_one({"symbol": sym}, {"_id": 0}) or {}
    avg_volume = cache.get("avg_volume")
    addv = cache.get("avg_dollar_volume")
    print(f"  symbol_adv_cache.avg_volume        : {avg_volume}")
    print(f"  symbol_adv_cache.avg_dollar_volume : {addv}")
    print(f"  symbol_adv_cache.tier              : {cache.get('tier')}")

    # 2) gate fallback: ib_historical_data 20-bar avg volume
    bars = list(db["ib_historical_data"].aggregate([
        {"$match": {"symbol": sym, "bar_size": "1 day"}},
        {"$sort": {"date": -1}},
        {"$limit": 20},
        {"$project": {"_id": 0, "volume": 1, "date": 1}},
    ], allowDiskUse=True))
    vols = [b.get("volume", 0) for b in bars if (b.get("volume") or 0) > 0]
    fallback_adv = int(sum(vols) / len(vols)) if vols else 0
    print(f"  ib_historical_data 20-bar avg vol  : {fallback_adv}  (n_bars={len(vols)})")

    # the value the gate would actually use
    gate_share_adv = int(avg_volume or 0) or fallback_adv
    print(f"  → gate would use share_adv         : {gate_share_adv}")

    # 3) thresholds (script env + .env file). NOTE: the RUNNING backend's env
    #    may differ — also run `echo $SCALP_MIN_SHARE_ADV` in the backend shell.
    floor_script = os.environ.get("SCALP_MIN_SHARE_ADV", "(unset → default 3,000,000)")
    rvol_script = os.environ.get("SCALP_MIN_RVOL", "(unset → default 1.0)")
    print(f"\n  SCALP_MIN_SHARE_ADV (script env)   : {floor_script}")
    print(f"  SCALP_MIN_SHARE_ADV (backend/.env) : {env.get('SCALP_MIN_SHARE_ADV', '(absent)')}")
    print(f"  SCALP_MIN_RVOL      (script env)   : {rvol_script}")
    print(f"  SCALP_MIN_RVOL      (backend/.env) : {env.get('SCALP_MIN_RVOL', '(absent)')}")
    floor = 3_000_000
    try:
        floor = int(float(env.get("SCALP_MIN_SHARE_ADV") or os.environ.get("SCALP_MIN_SHARE_ADV") or 3_000_000))
    except Exception:
        pass
    verdict = "WOULD BLOCK" if gate_share_adv < floor else "WOULD PASS"
    print(f"\n  VERDICT @ floor {floor:,}: share_adv {gate_share_adv:,} → {verdict}")
    if gate_share_adv < floor:
        print("  → If a scalp on this symbol traded, EITHER the live backend floor is")
        print("    lower than this, OR the trade predates the v322m deploy, OR its")
        print("    style at gate-time was NOT scalp/intraday (gate only fires for those).")

    # 4) recent bot_trades for the symbol
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(f"\n=== recent {sym} bot_trades (last {days}d) ===")
    trs = list(db["bot_trades"].find(
        {"symbol": sym, "$or": [{"created_at": {"$gte": cut}}, {"closed_at": {"$gte": cut}}]},
        {"_id": 0, "setup_type": 1, "trade_style": 1, "status": 1, "entered_by": 1,
         "net_pnl": 1, "pnl": 1, "created_at": 1, "closed_at": 1, "alert_id": 1}
    ).sort([("created_at", -1)]).limit(40))
    if not trs:
        print("  (none)")
    for t in trs:
        pnl = t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")
        print(f"  {(t.get('created_at') or '')[:19]}  setup={t.get('setup_type'):<18} "
              f"style={t.get('trade_style') or '?':<12} status={t.get('status'):<8} "
              f"pnl={pnl}  alert_id={t.get('alert_id')}")
        # show the originating alert's style at emission for each
        aid = t.get("alert_id")
        if aid:
            a = db["live_alerts"].find_one(
                {"$or": [{"alert_id": aid}, {"id": aid}]},
                {"_id": 0, "trade_style": 1, "rvol": 1, "scan_tier": 1}) or {}
            if a:
                print(f"       └ alert.trade_style={a.get('trade_style')}  "
                      f"rvol={a.get('rvol')}  scan_tier={a.get('scan_tier')}")
    print()


if __name__ == "__main__":
    main()
