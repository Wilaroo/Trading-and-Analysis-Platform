#!/usr/bin/env python3
"""diag_v376 (READ-ONLY) — "why didn't we trade it?" decision-trail trace.

For each watch symbol, reconstructs TODAY's full pipeline so we can see exactly
where each mover dropped out:
  1. symbol_adv_cache  — is it even in the universe? (tier/$-vol/shares/adrp)
  2. live_alerts       — did ANY setup fire? (setup/style/dir/prio/rvol/conf/time)
  3. trade_drops       — was it rejected at a gate, and WHICH? (gate + check + reason)
  4. confidence_gate_log (if present) — confidence/TQS verdicts
  5. bot_trades        — any attempt/fill today

Failure mode read-out per symbol:
  • no adv_cache row / not subscribed  → never scanned (data/universe gap)
  • adv_cache ok, NO live_alerts        → scanned but NO setup matched (detection gap)
  • live_alerts but trade_drops          → setup fired, GATE rejected (which gate?)
  • live_alerts, no drops, no trade      → passed gates, execution/risk blocked

NOTHING WRITTEN. Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v376_missed_movers_trace.py \
      --syms SNDK,TSLA,MRVL,SPCX,AMZN --since 2026-06-18T08:00:00
"""
import sys
from collections import defaultdict


def _arg(flag, d):
    if flag in sys.argv:
        try:
            return sys.argv[sys.argv.index(flag) + 1]
        except Exception:
            return d
    return d


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _g(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _t(v):
    return str(v)[11:19] if isinstance(v, str) and len(v) >= 19 else str(v)


def main():
    from datetime import datetime, timezone
    syms = _arg("--syms", "SNDK,TSLA,MRVL,SPCX,AMZN").upper().split(",")
    since = _arg("--since", datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00"))
    db = _db()
    print(f"\n=== v376 missed-movers decision trace — since {since} ===")

    # collection name flexibility
    cols = set(db.list_collection_names())
    cgl = "confidence_gate_log" if "confidence_gate_log" in cols else None

    for s in syms:
        s = s.strip()
        print(f"\n################  {s}  ################")

        # 1) universe
        c = db["symbol_adv_cache"].find_one({"symbol": s}, {"_id": 0}) or {}
        print(f"  [universe] tier={c.get('tier')}  $-vol={c.get('avg_dollar_volume')}  "
              f"shares={c.get('avg_volume')}  adrp_20d={c.get('adrp_20d', 'n/a')}  "
              f"unqualifiable={c.get('unqualifiable', False)}")

        # 2) live_alerts today
        al = list(db["live_alerts"].find(
            {"symbol": s, "$or": [{"timestamp": {"$gte": since}},
                                  {"created_at": {"$gte": since}},
                                  {"ts": {"$gte": since}}]},
            {"_id": 0}).limit(60))
        print(f"  [live_alerts] {len(al)} today")
        seen = defaultdict(int)
        for a in al:
            key = f"{_g(a,'setup_type','setup','?')}/{_g(a,'trade_style','style','?')}/{_g(a,'direction','dir','?')}"
            seen[key] += 1
        for k, n in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
            print(f"      {k:<46} x{n}")
        for a in al[:6]:
            print(f"        {_t(_g(a,'timestamp','created_at','ts'))} "
                  f"{_g(a,'setup_type','setup','?'):<20} "
                  f"style={_g(a,'trade_style','style','?'):<10} "
                  f"dir={_g(a,'direction','dir','?'):<5} "
                  f"prio={_g(a,'priority','prio','?')} "
                  f"rvol={_g(a,'rvol', default='?')} "
                  f"conf={_g(a,'confidence','confidence_score', default='?')} "
                  f"tqs={_g(a,'tqs_score','unified_score', default='?')}")

        # 3) trade_drops today
        dr = list(db["trade_drops"].find(
            {"symbol": s, "ts": {"$gte": since}}, {"_id": 0}).limit(200))
        bygate = defaultdict(lambda: {"n": 0, "ex": None})
        for d in dr:
            chk = (d.get("context") or {}).get("check", "")
            key = f"{d.get('gate')}" + (f":{chk}" if chk else "")
            bygate[key]["n"] += 1
            if bygate[key]["ex"] is None:
                bygate[key]["ex"] = d.get("reason")
        print(f"  [trade_drops] {len(dr)} today")
        for k, v in sorted(bygate.items(), key=lambda kv: -kv[1]["n"]):
            print(f"      {k:<34} x{v['n']:<4} e.g. {str(v['ex'])[:90]}")

        # 4) confidence gate log
        if cgl:
            cg = list(db[cgl].find(
                {"symbol": s, "$or": [{"timestamp": {"$gte": since}}, {"ts": {"$gte": since}}]},
                {"_id": 0}).limit(40))
            passed = sum(1 for x in cg if _g(x, "passed", "approved", default=False))
            print(f"  [confidence_gate_log] {len(cg)} today (passed≈{passed})")
            for x in cg[:4]:
                print(f"        {_t(_g(x,'timestamp','ts'))} "
                      f"passed={_g(x,'passed','approved', default='?')} "
                      f"reason={str(_g(x,'reason','detail', default=''))[:80]}")

        # 5) bot_trades today
        bt = list(db["bot_trades"].find(
            {"symbol": s, "$or": [{"created_at": {"$gte": since}}, {"closed_at": {"$gte": since}}]},
            {"_id": 0, "setup_type": 1, "trade_style": 1, "status": 1, "entered_by": 1,
             "net_pnl": 1, "pnl": 1, "created_at": 1}).limit(20))
        print(f"  [bot_trades] {len(bt)} today")
        for t in bt:
            print(f"        {_t(t.get('created_at'))} {t.get('setup_type')}/"
                  f"{t.get('trade_style')} status={t.get('status')} "
                  f"by={t.get('entered_by')} pnl={t.get('net_pnl', t.get('pnl'))}")

        # verdict
        if not c:
            v = "NOT IN UNIVERSE (never scanned)"
        elif not al:
            v = "scanned but NO SETUP FIRED (detection gap)"
        elif bt:
            v = "TRADED (see bot_trades)"
        elif dr:
            top = max(bygate.items(), key=lambda kv: kv[1]["n"])[0]
            v = f"alert(s) fired but GATED — top gate: {top}"
        else:
            v = "alert(s) fired, NO drop & NO trade — execution/risk or alert-only setup"
        print(f"  >>> VERDICT: {v}")

    print("\n=== READING ===")
    print("• Trace each symbol top→bottom. The first stage that shows 0 (or a drop)")
    print("  is where we lost the move. live_alerts=0 → setup-detection gap (the")
    print("  pattern exists on the chart but no setup definition caught it).")
    print("• trade_drops gate tells you which guard rejected a fired setup (liquidity,")
    print("  confidence, EV, risk-cap, dedupe, etc.).\n")


if __name__ == "__main__":
    main()
