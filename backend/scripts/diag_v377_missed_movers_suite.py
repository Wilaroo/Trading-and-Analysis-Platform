#!/usr/bin/env python3
"""diag_v377 (READ-ONLY) — consolidated "missed movers" root-cause suite.

Sections (NOTHING WRITTEN):
  A) RVOL fail-close audit — system-wide today: scalp_rvol drops split by
     rvol == 0.0 (UNMEASURED → fail-closed) vs 0 < rvol < floor (real low).
     Top symbols killed on rvol == 0.0. If many, the gate is nuking real
     movers whose RVOL we simply aren't computing.
  B) Live-data / subscription freshness — last live_bar_cache bar per watch
     symbol. Stale/missing ⇒ not in the live IB push ⇒ no intraday volume
     ⇒ rvol = 0.0.
  C) Price-data sanity — symbol_adv_cache derived price ($-vol / shares) vs
     latest daily close. Big gap ⇒ corrupted price (SNDK-class) that inflates
     $-vol rank and breaks RVOL/ATR.
  D) tier=skip audit — liquid names ($-vol ≥ $1B) marked skip, with atr_pct,
     i.e. excluded by the ATR%>10% "chaos" ceiling (the SPCX/MRVL paradox).
  E) smart_filter_skip audit — today's smart-filter drops + the strategy_stats
     win-rate driving them (is it contaminated/garbage-era data?).
  F) direction + dedup — today's alert long/short split (short-side gap) and
     dedup_cooldown drop volume.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v377_missed_movers_suite.py \
      --watch SNDK,TSLA,MRVL,SPCX,AMZN --since 2026-06-18T08:00:00
"""
import re
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


def _first(d, *ks, default=None):
    for k in ks:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def main():
    from datetime import datetime, timezone
    watch = _arg("--watch", "SNDK,TSLA,MRVL,SPCX,AMZN").upper().split(",")
    since = _arg("--since", datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00"))
    db = _db()
    print(f"\n############ v377 missed-movers suite — since {since} ############")

    # ── A) RVOL fail-close audit ─────────────────────────────────────────
    print("\n=== A) scalp_rvol drop audit (system-wide today) ===")
    zero, lowreal, other = 0, 0, 0
    by_zero_sym = defaultdict(int)
    for d in db["trade_drops"].find(
            {"gate": "universal_liquidity_gate", "ts": {"$gte": since}},
            {"_id": 0, "symbol": 1, "context": 1, "reason": 1}):
        ctx = d.get("context") or {}
        if ctx.get("check") != "scalp_rvol":
            continue
        rv = ctx.get("rvol")
        if rv in (0, 0.0, None):
            zero += 1
            by_zero_sym[d.get("symbol") or "?"] += 1
        elif isinstance(rv, (int, float)) and rv > 0:
            lowreal += 1
        else:
            other += 1
    print(f"  scalp_rvol drops: rvol==0.0 (UNMEASURED, fail-closed) = {zero}  |  "
          f"0<rvol<floor (real low) = {lowreal}  |  other = {other}")
    print("  top symbols killed on rvol==0.0:")
    for s, n in sorted(by_zero_sym.items(), key=lambda kv: -kv[1])[:20]:
        print(f"      {s:<8} x{n}")

    # ── B) live-data freshness ───────────────────────────────────────────
    print("\n=== B) live_bar_cache freshness (subscription proof) ===")
    for s in watch:
        s = s.strip()
        doc = db["live_bar_cache"].find_one({"symbol": s}, {"_id": 0}) or \
            db["live_bar_cache"].find_one({"_id": s}) or {}
        ts = _first(doc, "timestamp", "ts", "updated_at", "last_update", "bar_time")
        close = _first(doc, "close", "c", "last", "price")
        print(f"  {s:<7} bar_ts={str(ts)[:19] or 'MISSING':<20} close={close}")

    # ── C) price-data sanity ─────────────────────────────────────────────
    print("\n=== C) price sanity (derived $-vol/shares vs latest daily close) ===")
    print(f"  {'sym':<7}{'derived$px':>12}{'dailyClose':>12}{'ratio':>8}  flag")
    for s in watch:
        s = s.strip()
        c = db["symbol_adv_cache"].find_one(
            {"symbol": s}, {"_id": 0, "avg_dollar_volume": 1, "avg_volume": 1}) or {}
        dv, sh = c.get("avg_dollar_volume") or 0, c.get("avg_volume") or 0
        derived = (dv / sh) if sh else 0
        bar = db["ib_historical_data"].find_one(
            {"symbol": s, "bar_size": "1 day"}, {"_id": 0, "close": 1},
            sort=[("date", -1)]) or {}
        close = bar.get("close") or 0
        ratio = (derived / close) if close else 0
        flag = "⚠ CORRUPT PRICE" if close and (ratio > 1.5 or ratio < 0.66) else ""
        print(f"  {s:<7}{derived:>12.2f}{close:>12.2f}{ratio:>8.2f}  {flag}")

    # ── D) tier=skip audit (liquid names excluded by ATR ceiling) ────────
    print("\n=== D) liquid names ($-vol≥$1B) marked tier=skip ===")
    skipped = list(db["symbol_adv_cache"].find(
        {"tier": "skip", "avg_dollar_volume": {"$gte": 1_000_000_000}},
        {"_id": 0, "symbol": 1, "avg_dollar_volume": 1, "avg_volume": 1,
         "atr_pct": 1, "atr_percent": 1, "atr": 1}).sort([("avg_dollar_volume", -1)]).limit(40))
    print(f"  {len(skipped)} liquid names skipped (likely ATR%>10% chaos ceiling):")
    for d in skipped:
        atr = _first(d, "atr_pct", "atr_percent", "atr", default="n/a")
        print(f"      {d['symbol']:<7} $-vol=${(d.get('avg_dollar_volume') or 0)/1e9:.1f}B  "
              f"shares={int(d.get('avg_volume') or 0):,}  atr_pct={atr}")

    # ── E) smart_filter_skip audit ───────────────────────────────────────
    print("\n=== E) smart_filter_skip drops today + win-rate driver ===")
    sf = list(db["trade_drops"].find(
        {"gate": "smart_filter_skip", "ts": {"$gte": since}}, {"_id": 0}).limit(300))
    by_setup = defaultdict(lambda: {"n": 0, "wr": set(), "syms": set()})
    for d in sf:
        ctx = d.get("context") or {}
        st = _first(ctx, "setup_type", "setup", default=d.get("setup_type") or "?")
        wr = _first(ctx, "win_rate", "filter_win_rate")
        by_setup[st]["n"] += 1
        if wr is not None:
            by_setup[st]["wr"].add(round(float(wr), 3))
        if d.get("symbol"):
            by_setup[st]["syms"].add(d["symbol"])
    print(f"  {len(sf)} smart_filter_skip drops today, by setup:")
    for st, v in sorted(by_setup.items(), key=lambda kv: -kv[1]["n"])[:20]:
        print(f"      {st:<24} x{v['n']:<4} win_rate(s)={sorted(v['wr'])[:5]}  "
              f"syms={sorted(v['syms'])[:8]}")
    # cross-ref strategy_stats for the top skipped setups
    print("  strategy_stats backing the top skipped setups:")
    for st in list(by_setup)[:8]:
        rows = list(db["strategy_stats"].find(
            {"$or": [{"setup_type": st}, {"strategy": st}, {"_id": st}, {"setup": st}]},
            {"_id": 0}).limit(3))
        for r in rows:
            print(f"      {st:<24} wr={_first(r,'win_rate','winrate')} "
                  f"n={_first(r,'total','count','n','trades')} "
                  f"avgR={_first(r,'avg_r','avgR','expectancy')}")

    # ── F) direction split + dedup ───────────────────────────────────────
    print("\n=== F) today's alert direction split + dedup volume ===")
    dirs = defaultdict(int)
    for a in db["live_alerts"].find(
            {"$or": [{"timestamp": {"$gte": since}}, {"created_at": {"$gte": since}},
                     {"ts": {"$gte": since}}]},
            {"_id": 0, "direction": 1, "dir": 1}):
        dirs[(_first(a, "direction", "dir", default="?")).lower()] += 1
    print(f"  live_alerts by direction: {dict(dirs)}")
    dedup = db["trade_drops"].count_documents({"gate": "dedup_cooldown", "ts": {"$gte": since}})
    print(f"  dedup_cooldown drops today: {dedup}")

    print("\n=== READING ===")
    print("• A zero-count ≫ low-real ⇒ the RVOL gate is fail-closing real movers we")
    print("  don't measure; fix the RVOL source and/or only fail-closed when there's")
    print("  truly no live volume. B confirms which watch names lack live bars.")
    print("• C flags corrupted prices (bad $-vol rank + broken RVOL/ATR).")
    print("• D = liquid names excluded purely by the ATR%>10% ceiling.")
    print("• E shows if the smart filter is vetoing setups on garbage-era win rates.\n")


if __name__ == "__main__":
    main()
