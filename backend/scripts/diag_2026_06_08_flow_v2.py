#!/usr/bin/env python3
"""
READ-ONLY — corrected trade-flow verification (2026-06-08 v2).

The first pass queried `trade_drops.created_at`, which DOES NOT EXIST (the field
is `ts_epoch_ms` / `ts_dt` / `ts`), so the "0 drops today" was spurious. This
version uses the real timestamp fields and is type-robust, and adds a 7-day
baseline so we can see whether today's trade volume is actually anomalous.

Goal: definitively answer "is v297's universal_liquidity_gate over-blocking and
choking trade flow today?"  Writes nothing.

Usage: cd ~/Trading-and-Analysis-Platform/backend && python scripts/diag_2026_06_08_flow_v2.py
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient


def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ["MONGO_URL"], os.environ["DB_NAME"]


def main():
    mongo_url, db_name = _load_env()
    db = MongoClient(mongo_url)[db_name]
    now_ms = int(time.time() * 1000)
    print(f"[db] {mongo_url} / {db_name}")
    print(f"[now] {datetime.now(timezone.utc).isoformat()}  (epoch_ms={now_ms})\n")

    # ───────── trade_drops by gate over several windows (real ts field) ─────────
    print("=" * 78)
    print("TRADE_DROPS by gate (using ts_epoch_ms — the REAL timestamp field)")
    print("=" * 78)
    total_dd = db.trade_drops.estimated_document_count()
    print(f"  trade_drops total in collection: {total_dd}")
    for label, mins in (("last 60 min", 60), ("last 6 h (≈ since open)", 360),
                        ("last 24 h", 1440)):
        cutoff = now_ms - mins * 60 * 1000
        rows = list(db.trade_drops.find({"ts_epoch_ms": {"$gte": cutoff}}))
        by_gate = {}
        for d in rows:
            by_gate[d.get("gate", "?")] = by_gate.get(d.get("gate", "?"), 0) + 1
        print(f"\n  ── {label}: {len(rows)} drops")
        for g, c in sorted(by_gate.items(), key=lambda x: -x[1]):
            flag = "  <<< v297" if g == "universal_liquidity_gate" else ""
            print(f"       {g:<34} {c}{flag}")

    # Most-recent drops regardless of gate (see what's actually being filtered).
    print("\n  ── 15 most-recent trade_drops (any gate):")
    for d in db.trade_drops.find().sort("ts_epoch_ms", -1).limit(15):
        ctx = d.get("context", {}) or {}
        extra = ""
        if d.get("gate") == "universal_liquidity_gate":
            extra = f"  adv=${ctx.get('avg_dollar_volume',0):,} tier={ctx.get('tier')}"
        print(f"       {str(d.get('ts',''))[:19]}  {d.get('gate','?'):<28} "
              f"{d.get('symbol','—'):<6} {d.get('setup_type','—'):<14}{extra}")

    # Fallback: if ts_epoch_ms is somehow absent, show via ts_dt too.
    dd_with_epoch = db.trade_drops.count_documents({"ts_epoch_ms": {"$exists": True}})
    print(f"\n  (sanity: {dd_with_epoch}/{total_dd} drops have ts_epoch_ms)")

    # ───────── bot_trades: today vs 7-day baseline (created_at is ISO STRING) ─────────
    print("\n" + "=" * 78)
    print("BOT_TRADES volume — today vs 7-day baseline (created_at = ISO string)")
    print("=" * 78)
    for i in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        nxt = (datetime.now(timezone.utc) - timedelta(days=i - 1)).strftime("%Y-%m-%d")
        q = {"created_at": {"$gte": day, "$lt": nxt}}
        total = db.bot_trades.count_documents(q)
        filled = db.bot_trades.count_documents({**q, "status": {"$in": ["open", "closed"]}})
        rejected = db.bot_trades.count_documents({**q, "status": "rejected"})
        reaped = db.bot_trades.count_documents({**q, "close_reason": "stale_pending_auto_reaper"})
        tag = "  <-- TODAY" if i == 0 else ""
        print(f"  {day}:  total {total:>3}  | filled(open/closed) {filled:>3}  "
              f"| rejected {rejected:>3}  | reaped {reaped:>2}{tag}")

    # ───────── stale-pending reaper activity (the real MA bug) ─────────
    print("\n" + "=" * 78)
    print("STALE-PENDING REAPER — recent rejections (root cause of MA orphan)")
    print("=" * 78)
    reaped = list(db.bot_trades.find(
        {"close_reason": "stale_pending_auto_reaper"}
    ).sort("created_at", -1).limit(12))
    print(f"  recent stale_pending_auto_reaper rejections: {len(reaped)}")
    for t in reaped:
        print(f"     {str(t.get('created_at'))[:19]}  {t.get('symbol','?'):<6} "
              f"shares={t.get('shares')} entry={t.get('fill_price')}")
    # reaper-skip events (the fill-race guard catching filled orders)
    try:
        skips = db.state_integrity_events.count_documents(
            {"event": "reaper_skip_likely_filled"})
        print(f"\n  state_integrity_events 'reaper_skip_likely_filled' (guard caught fill): {skips}")
    except Exception:
        pass

    print("\n>>> READ: if universal_liquidity_gate count is ~0 across all windows AND")
    print("    today's bot_trades total is in line with the baseline, v297 is NOT the")
    print("    cause. If today is a big outlier low, dig further (EV gate / dedup).")


if __name__ == "__main__":
    sys.exit(main())
