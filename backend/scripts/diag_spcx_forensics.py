#!/usr/bin/env python3
"""
diag_spcx_forensics.py — READ-ONLY deep-dive on SPCX historical data
====================================================================
Built after diag_splits_unadjusted.py flagged SPCX with a 666% move
between 2026-06-12 and 2026-03-13. User confirms SPCX is a brand-new
IPO that debuted Friday 2026-06-09. The 2026-03-13 bar is therefore
pollution from the OLD delisted SPCX (SpaceX SPAC ETF).

This probe answers:
  1. Every daily bar in ib_historical_data for SPCX (date, OHLCV).
  2. Where the time-gap actually sits.
  3. symbol_adv_cache state for SPCX (polluted avg_volume?).
  4. The held bot_trades row (entry time, size, conid).
  5. Whether v319a gap_stale would fire on this state.

USAGE:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python /tmp/diag_spcx_forensics.py
  .venv/bin/python /tmp/diag_spcx_forensics.py --symbol RKLB   # scan another sym
NO WRITES.
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_env():
    for cand in (
        Path.cwd() / "backend" / ".env",
        Path.home() / "Trading-and-Analysis-Platform" / "backend" / ".env",
    ):
        if cand.is_file():
            for ln in cand.read_text().splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


_load_env()
try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pymongo missing.")
    sys.exit(1)


def _fmt_date(d):
    if d is None:
        return "—"
    if isinstance(d, str):
        return d[:19]
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return str(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPCX")
    ap.add_argument("--mongo-url",
                    default=os.environ.get("MONGO_URL") or "mongodb://localhost:27017")
    ap.add_argument("--db", default=os.environ.get("DB_NAME") or "tradecommand")
    args = ap.parse_args()

    sym = args.symbol.upper()
    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    db = client[args.db]

    print("═══════════════════════════════════════════════════════════════════════")
    print(f" diag_spcx_forensics  —  READ-ONLY  —  symbol={sym}")
    print("═══════════════════════════════════════════════════════════════════════")
    now = datetime.now(timezone.utc)
    print(f"  now (UTC)               : {now.isoformat(timespec='seconds')}")
    print()

    # ─────────────────────────────────────────────────────────────────
    # 1. All daily bars
    # ─────────────────────────────────────────────────────────────────
    print(f"─── 1. ib_historical_data (bar_size='1 day') ─────────────────────────")
    bars = list(db["ib_historical_data"].find(
        {"symbol": sym, "bar_size": "1 day"},
        {"_id": 0}
    ).sort("date", 1))
    print(f"  Total daily bars: {len(bars)}")
    if not bars:
        print("  [!] No daily bars at all for this symbol.")
    else:
        # Show first 3, last 5
        head = bars[:3]
        tail = bars[-5:] if len(bars) > 5 else []
        print(f"\n  Oldest 3 bars:")
        print(f"   {'date':<22} {'open':>9} {'high':>9} {'low':>9} {'close':>9} {'volume':>14} {'source':<14}")
        for b in head:
            print(f"   {_fmt_date(b.get('date')):<22} "
                  f"{(b.get('open') or 0):>9.2f} {(b.get('high') or 0):>9.2f} "
                  f"{(b.get('low') or 0):>9.2f} {(b.get('close') or 0):>9.2f} "
                  f"{(b.get('volume') or 0):>14,} {str(b.get('source') or b.get('what_to_show') or '—'):<14}")
        if tail:
            print(f"\n  Newest 5 bars:")
            print(f"   {'date':<22} {'open':>9} {'high':>9} {'low':>9} {'close':>9} {'volume':>14} {'source':<14}")
            for b in tail:
                print(f"   {_fmt_date(b.get('date')):<22} "
                      f"{(b.get('open') or 0):>9.2f} {(b.get('high') or 0):>9.2f} "
                      f"{(b.get('low') or 0):>9.2f} {(b.get('close') or 0):>9.2f} "
                      f"{(b.get('volume') or 0):>14,} {str(b.get('source') or b.get('what_to_show') or '—'):<14}")

        # Detect time-gaps > 7 days
        gaps = []
        for i in range(1, len(bars)):
            prev = bars[i-1].get("date")
            curr = bars[i].get("date")
            if isinstance(prev, str):
                prev = datetime.fromisoformat(prev.replace("Z", "+00:00"))
            if isinstance(curr, str):
                curr = datetime.fromisoformat(curr.replace("Z", "+00:00"))
            if isinstance(prev, datetime) and isinstance(curr, datetime):
                dd = (curr - prev).days
                if dd > 7:
                    gaps.append((prev, curr, dd))
        print(f"\n  Time-gaps > 7 days between consecutive bars: {len(gaps)}")
        for p, c, d in gaps[:5]:
            print(f"   {_fmt_date(p)}  →  {_fmt_date(c)}   ({d} days)")
        if gaps:
            print(f"\n  [!] These gaps strongly suggest historical-data pollution")
            print(f"      from a recycled/relisted ticker. Bars BEFORE the gap")
            print(f"      likely belong to a previously delisted entity.")

    # ─────────────────────────────────────────────────────────────────
    # 2. symbol_adv_cache
    # ─────────────────────────────────────────────────────────────────
    print(f"\n─── 2. symbol_adv_cache ──────────────────────────────────────────────")
    adv = db["symbol_adv_cache"].find_one({"symbol": sym})
    if adv:
        print(f"  avg_volume      : {adv.get('avg_volume'):,}" if adv.get('avg_volume')
              else f"  avg_volume      : {adv.get('avg_volume')}")
        print(f"  avg_dollar_vol  : {adv.get('avg_dollar_vol')}")
        print(f"  last_updated    : {_fmt_date(adv.get('last_updated') or adv.get('updated_at'))}")
        print(f"  bars_used       : {adv.get('bars_used') or adv.get('lookback_days') or '—'}")
        print(f"  source          : {adv.get('source') or '—'}")
    else:
        print("  (no entry)")

    # ─────────────────────────────────────────────────────────────────
    # 3. bot_trades open row(s)
    # ─────────────────────────────────────────────────────────────────
    print(f"\n─── 3. bot_trades (open) ─────────────────────────────────────────────")
    open_trades = list(db["bot_trades"].find({"symbol": sym, "status": "open"}))
    print(f"  Open rows: {len(open_trades)}")
    for t in open_trades:
        print(f"   id              : {t.get('trade_id') or t.get('_id')}")
        print(f"   entry_time      : {_fmt_date(t.get('entry_time') or t.get('opened_at'))}")
        print(f"   entry_price     : {t.get('entry_price')}")
        print(f"   size / qty      : {t.get('size') or t.get('quantity')}")
        print(f"   stop / target   : {t.get('stop_price')} / {t.get('target_price')}")
        print(f"   strategy        : {t.get('strategy') or t.get('setup_type') or '—'}")
        print(f"   conid           : {t.get('conid') or '—'}")

    # ─────────────────────────────────────────────────────────────────
    # 4. gap_pct + gap_stale simulation (mirrors v319a logic)
    # ─────────────────────────────────────────────────────────────────
    print(f"\n─── 4. v319a gap_pct / gap_stale simulation ─────────────────────────")
    if len(bars) >= 2:
        last = bars[-1]
        prev = bars[-2]
        ld = last.get("date")
        pd = prev.get("date")
        if isinstance(ld, str):
            ld = datetime.fromisoformat(ld.replace("Z", "+00:00"))
        if isinstance(pd, str):
            pd = datetime.fromisoformat(pd.replace("Z", "+00:00"))
        gap_days = (ld - pd).days if (isinstance(ld, datetime) and isinstance(pd, datetime)) else None
        raw_gap = 100.0 * (last.get("close", 0) - prev.get("close", 0)) / prev.get("close", 1)
        clamped = max(-50.0, min(50.0, raw_gap))
        gap_stale = (gap_days or 0) > 2
        print(f"  prev close   : {prev.get('close')} @ {_fmt_date(pd)}")
        print(f"  last close   : {last.get('close')} @ {_fmt_date(ld)}")
        print(f"  gap_days     : {gap_days}")
        print(f"  raw gap_pct  : {raw_gap:+.2f}%")
        print(f"  clamped      : {clamped:+.2f}%  (v319a ±50% cap)")
        print(f"  gap_stale    : {gap_stale}  ({'FIRES' if gap_stale else 'silent'} — >2-day flag)")
    else:
        print("  (insufficient bars to compute gap)")

    # ─────────────────────────────────────────────────────────────────
    # 5. recent bars by ANY bar_size (catch 1-min, 5-min, etc.)
    # ─────────────────────────────────────────────────────────────────
    print(f"\n─── 5. ib_historical_data — counts by bar_size ───────────────────────")
    bar_counts = list(db["ib_historical_data"].aggregate([
        {"$match": {"symbol": sym}},
        {"$group": {"_id": "$bar_size",
                    "n": {"$sum": 1},
                    "min_date": {"$min": "$date"},
                    "max_date": {"$max": "$date"}}},
        {"$sort": {"n": -1}},
    ]))
    print(f"   {'bar_size':<14} {'count':>8} {'min_date':<22} {'max_date':<22}")
    for bc in bar_counts:
        print(f"   {str(bc['_id']):<14} {bc['n']:>8,} "
              f"{_fmt_date(bc['min_date']):<22} {_fmt_date(bc['max_date']):<22}")
    print()
    print("═══════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
