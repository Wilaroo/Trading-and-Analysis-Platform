#!/usr/bin/env python3
"""
diag_bar_align_check.py  (READ-ONLY)
====================================
Sanity-checks whether the 1-min bar window in diag_mae_mfe_reconstruct.py
is actually aligned with trade entry timestamps — BEFORE we trust the
intraday MFE/MAE numbers.

Prints:
  1. A raw sample 1-min bar doc and a raw 1-day bar doc (so we SEE the
     `date` field format + timezone).
  2. Raw executed_at / closed_at values from a few bot_trades.
  3. For several intraday legit trades: entry ts + price, the symbol's
     1-min bars on the entry DAY (count + first/last `date`), and the
     CRITICAL check — does the bar at/just-after entry actually contain
     the entry price in its [low, high]? If not, the window is misaligned.

Run from repo root + venv:
    .venv/bin/python backend/scripts/diag_bar_align_check.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)[os.environ["DB_NAME"]]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    _load_env()
    db = _db()
    print(f"\n{'#'*92}\n#  BAR ALIGNMENT SANITY CHECK\n{'#'*92}")

    # 1. raw bar docs
    print("\n[1] sample 1-min bar doc:")
    one = db["ib_historical_data"].find_one({"bar_size": "1 min"}, {"_id": 0})
    print("   ", one)
    print("    sample 1-day bar doc:")
    day = db["ib_historical_data"].find_one({"bar_size": "1 day"}, {"_id": 0})
    print("   ", {k: day.get(k) for k in ("symbol", "date", "open", "high", "low", "close")} if day else None)
    print("\n    distinct bar_size values:", db["ib_historical_data"].distinct("bar_size")[:20])

    # 2. raw trade timestamps
    print("\n[2] raw bot_trade timestamps (executed_at / closed_at):")
    for t in db["bot_trades"].find(
            {"status": "closed", "entered_by": "bot_fired"},
            {"_id": 0, "symbol": 1, "executed_at": 1, "entry_time": 1,
             "closed_at": 1, "exit_time": 1, "entry_price": 1, "fill_price": 1}).limit(4):
        print(f"    {t.get('symbol'):<6} executed_at={t.get('executed_at')!r}  "
              f"entry_time={t.get('entry_time')!r}  closed_at={t.get('closed_at')!r}")

    # 3. per-trade alignment: does the entry-minute bar contain the entry price?
    print("\n[3] entry-minute alignment check (intraday-ish legit trades):")
    print(f"    {'sym':<6}{'entry_ts (raw)':<30}{'entry_px':>9}  "
          f"{'day bars':>9}{'first bar date':<26}{'price-in-band?'}")
    checked = 0
    for t in db["bot_trades"].find(
            {"status": "closed", "entered_by": "bot_fired",
             "entry_price": {"$gt": 0}},
            {"_id": 0, "symbol": 1, "executed_at": 1, "entry_time": 1,
             "entry_price": 1, "fill_price": 1}).limit(60):
        sym = t.get("symbol")
        ets_raw = t.get("executed_at") or t.get("entry_time")
        entry = _num(t.get("entry_price")) or _num(t.get("fill_price"))
        if not sym or not ets_raw or not entry:
            continue
        ets = str(ets_raw)
        day_str = ets[:10]
        # all 1-min bars for that symbol whose `date` starts with the entry day
        bars = list(db["ib_historical_data"].find(
            {"symbol": sym.upper(), "bar_size": "1 min",
             "date": {"$gte": day_str, "$lt": day_str + "T23:59:59"}},
            {"_id": 0, "date": 1, "high": 1, "low": 1}).sort("date", 1).limit(2000))
        if not bars:
            # try without the day filter — maybe date isn't ISO-day-prefixed
            anyb = db["ib_historical_data"].find_one({"symbol": sym.upper(), "bar_size": "1 min"})
            print(f"    {sym:<6}{ets:<30}{entry:>9.2f}  {'0':>9}(no day match; sample date={anyb.get('date') if anyb else None!r})")
            checked += 1
            if checked >= 12:
                break
            continue
        first = bars[0]["date"]
        # find the bar nearest to entry time (by string compare) and test band
        near = min(bars, key=lambda b: abs(len(str(b["date"])) and (str(b["date"]) > ets) - (str(b["date"]) < ets)))
        # better: first bar whose date >= ets
        after = [b for b in bars if str(b["date"]) >= ets]
        cand = after[0] if after else bars[-1]
        lo, hi = _num(cand.get("low")), _num(cand.get("high"))
        in_band = (lo is not None and hi is not None and lo - 0.02 * entry <= entry <= hi + 0.02 * entry)
        # also: does ANY bar that day contain the entry price?
        any_band = any((_num(b.get("low")) or 9e9) <= entry <= (_num(b.get("high")) or -9e9) for b in bars)
        print(f"    {sym:<6}{ets:<30}{entry:>9.2f}  {len(bars):>9}{str(first)[:25]:<26}"
              f"near={in_band} anyBarThatDay={any_band}")
        checked += 1
        if checked >= 12:
            break

    print(f"\n{'='*92}")
    print("DIAGNOSIS:")
    print("• If 'first bar date' format differs from entry_ts format (e.g. one has tz/'T',")
    print("  the other a space or ET offset) → the window query is misaligned.")
    print("• If near=False but anyBarThatDay=True → the entry price IS in the day's range but")
    print("  our entry-minute pick is offset (timezone shift) → intraday MFE is understated.")
    print("• If anyBarThatDay=False → entry price not even in that day's bars → symbol/day/price")
    print("  mismatch (deeper issue).")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
