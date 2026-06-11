#!/usr/bin/env python3
"""
diag_liquidity_trail.py — READ-ONLY forensic for "why did a low-ADV symbol
fire a scalp/intraday trade?" (AIQ / CZR, 2026-06-11).

Run from the repo root:
    python3 diag_liquidity_trail.py              # defaults: AIQ CZR, today
    python3 diag_liquidity_trail.py AIQ CZR 2026-06-11

Pulls, per symbol:
  1. bot_trades rows for the date (setup, style, shares, entry, notes)
  2. live_alerts + alerts rows (scan_tier, trade_style, source, rvol)
  3. symbol_adv_cache row — the EXACT value the liquidity gate read
  4. TRUE 20-day ADV recomputed from ib_historical_data daily bars
     (+ bar-date range so stale data is obvious)
  5. trade_drops rows (did any gate evaluate/reject it today?)
  6. confidence_gate_log rows
  7. Verdict: which tier floor applied vs cache vs true ADV

Makes NO writes.
"""
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

SYMS = [a.upper() for a in sys.argv[1:] if not a[0].isdigit()] or ["AIQ", "CZR"]
DATE = next((a for a in sys.argv[1:] if a[:2] == "20"), None) or \
    datetime.now(timezone.utc).strftime("%Y-%m-%d")

env = dict(
    l.strip().split("=", 1) for l in open("backend/.env")
    if "=" in l and not l.lstrip().startswith("#")
)
db = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]

FLOORS = {"intraday": 50_000_000, "swing": 10_000_000, "investment": 2_000_000}


def hdr(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def sub(t):
    print(f"\n--- {t} ---")


def fmt(d, keys):
    return {k: d.get(k) for k in keys if k in d}


for sym in SYMS:
    hdr(f"{sym} — liquidity decision trail for {DATE}")

    # 1. bot_trades
    sub("1. bot_trades (today)")
    rows = list(db["bot_trades"].find(
        {"symbol": sym, "$or": [
            {"executed_at": {"$regex": f"^{DATE}"}},
            {"created_at": {"$regex": f"^{DATE}"}},
        ]}, {"_id": 0}))
    if not rows:
        print("  (none)")
    for t in rows:
        print(f"  trade {t.get('id')}: status={t.get('status')} "
              f"setup={t.get('setup_type')} style={t.get('trade_style')} "
              f"tf={t.get('timeframe')} shares={t.get('shares')} "
              f"entry={t.get('entry_price')} entered_by={t.get('entered_by')}")
        print(f"    executed_at={t.get('executed_at')} "
              f"close_reason={t.get('close_reason')} pnl={t.get('pnl') or t.get('net_pnl')}")
        notes = (t.get("notes") or "")[:300]
        if notes:
            print(f"    notes: {notes}")

    # 2. alerts
    sub("2. alerts / live_alerts (today)")
    found_alert_tiers = []
    for coll in ("live_alerts", "alerts", "live_scanner_alerts"):
        try:
            arows = list(db[coll].find(
                {"symbol": sym, "$or": [
                    {"triggered_at": {"$regex": f"^{DATE}"}},
                    {"created_at": {"$regex": f"^{DATE}"}},
                ]}, {"_id": 0}).limit(10))
        except Exception as e:
            print(f"  {coll}: query error {e}")
            continue
        for a in arows:
            tier = a.get("scan_tier")
            style = a.get("trade_style")
            found_alert_tiers.append((tier, style))
            print(f"  [{coll}] {a.get('setup_type')} dir={a.get('direction')} "
                  f"scan_tier={tier} trade_style={style} "
                  f"source={a.get('source')} rvol={a.get('rvol')} "
                  f"prio={a.get('priority')} t={a.get('triggered_at') or a.get('created_at')}")
        if not arows:
            print(f"  {coll}: (none)")

    # 3. symbol_adv_cache — what the gate read
    sub("3. symbol_adv_cache (what the gate saw)")
    cache = db["symbol_adv_cache"].find_one({"symbol": sym}, {"_id": 0})
    cache_dollar = 0
    if cache:
        cache_dollar = int(cache.get("avg_dollar_volume") or 0)
        if not cache_dollar:
            cache_dollar = int((cache.get("avg_volume") or 0) *
                               (cache.get("latest_close") or 0))
        print(f"  avg_dollar_volume = ${int(cache.get('avg_dollar_volume') or 0):,}")
        print(f"  avg_volume(sh)    = {int(cache.get('avg_volume') or 0):,}")
        print(f"  latest_close      = {cache.get('latest_close')}")
        print(f"  atr_pct           = {cache.get('atr_pct')}")
        for k in ("updated_at", "computed_at", "ts", "last_updated"):
            if k in cache:
                print(f"  {k:<17} = {cache[k]}")
    else:
        print("  (NO CACHE ROW — gate would fall back to share-ADV × price, "
              "or fail-closed if that also returns 0)")

    # 4. TRUE ADV from daily bars
    sub("4. TRUE 20-day ADV from ib_historical_data daily bars")
    bars = list(db["ib_historical_data"].find(
        {"symbol": sym, "bar_size": "1 day"},
        {"_id": 0, "date": 1, "volume": 1, "close": 1},
    ).sort("date", -1).limit(20))
    true_dollar = 0
    if bars:
        vols = [float(b.get("volume") or 0) for b in bars]
        dollars = [float(b.get("volume") or 0) * float(b.get("close") or 0)
                   for b in bars]
        good = [d for d in dollars if d > 0]
        true_share = int(sum(v for v in vols if v > 0) / max(1, len([v for v in vols if v > 0])))
        true_dollar = int(sum(good) / max(1, len(good)))
        print(f"  bars used: {len(bars)}  range {bars[-1].get('date')} → {bars[0].get('date')}")
        print(f"  TRUE share ADV  = {true_share:,}/day")
        print(f"  TRUE dollar ADV = ${true_dollar:,}/day")
        if str(bars[0].get("date", ""))[:10] < DATE[:8] + "01":
            print("  ⚠ newest daily bar looks STALE relative to query date")
    else:
        print("  (no daily bars — collector gap; fallback path returned 0 → "
              "gate would FAIL-CLOSE unless an exception made it fail-open)")

    # 5. trade_drops
    sub("5. trade_drops (gate evaluations today)")
    drops = list(db["trade_drops"].find(
        {"symbol": sym, "$or": [
            {"ts": {"$regex": f"^{DATE}"}},
            {"created_at": {"$regex": f"^{DATE}"}},
            {"timestamp": {"$regex": f"^{DATE}"}},
        ]}, {"_id": 0}).limit(10))
    if not drops:
        print("  (none — no gate ever REJECTED this symbol today)")
    for d in drops:
        print(f"  gate={d.get('gate')} reason={str(d.get('reason'))[:120]}")
        ctx = d.get("context") or {}
        if ctx:
            print(f"    context: {fmt(ctx, ['tier', 'floor_usd', 'avg_dollar_volume', 'fail_closed', 'source'])}")

    # 6. confidence gate
    sub("6. confidence_gate_log (today)")
    cg = list(db["confidence_gate_log"].find(
        {"symbol": sym, "$or": [
            {"ts": {"$regex": f"^{DATE}"}},
            {"created_at": {"$regex": f"^{DATE}"}},
            {"timestamp": {"$regex": f"^{DATE}"}},
        ]}, {"_id": 0}).limit(5))
    if not cg:
        print("  (none)")
    for c in cg:
        print(f"  decision={c.get('decision') or c.get('outcome')} "
              f"setup={c.get('setup_type')} "
              f"score={c.get('final_score') or c.get('confidence')} "
              f"t={c.get('ts') or c.get('created_at') or c.get('timestamp')}")

    # 7. Verdict
    sub("7. VERDICT")
    tiers_seen = {t for t, _ in found_alert_tiers if t} or {"intraday (inferred default)"}
    for tier_raw in tiers_seen:
        tier = str(tier_raw).split(" ")[0]
        floor = FLOORS.get(tier, FLOORS["intraday"])
        print(f"  tier '{tier_raw}' → floor ${floor:,}")
        if cache_dollar:
            verdict = "PASS" if cache_dollar >= floor else "WOULD REJECT"
            print(f"    cache ${cache_dollar:,} vs floor → {verdict}")
        else:
            print("    cache empty → gate used fallback share-ADV × price")
        if true_dollar:
            verdict = "PASS" if true_dollar >= floor else "WOULD REJECT"
            print(f"    TRUE  ${true_dollar:,} vs floor → {verdict}")
        if cache_dollar and true_dollar and cache_dollar > true_dollar * 2:
            print("    ⚠ CACHE INFLATED >2x vs true ADV — stale/spiked cache row")

print(f"\n{'=' * 78}\ndone — read-only, nothing modified.")
