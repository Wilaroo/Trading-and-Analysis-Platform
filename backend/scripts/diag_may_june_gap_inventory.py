#!/usr/bin/env python3
"""
diag_may_june_gap_inventory.py  —  READ-ONLY  (2026-06-16, v320c prep)

Goal: re-derive (from `ib_historical_data` alone) the exact list of
symbols + bar_sizes + gap windows that compose the May→June 2026 ingest
gap previously identified by yesterday's diag_ingest_continuity.py
operator script.

Pattern we're matching (signature from session handoff):
  - History stops around March / April 2026.
  - Resumes cleanly on 2026-06-01 (the day they entered the active universe).
  - The 33-76 trading-day gap between is the unfilled window.

Output:
  Section 1 — per (symbol, bar_size) gap matrix with start/end dates and
              estimated bars-needed.
  Section 2 — symbol roll-up: total symbols, total bar requests, etas.
  Section 3 — SUGGESTED CSV (paste-rs-ready) for the repair patcher to
              consume, with one row per (symbol, bar_size, gap_start,
              gap_end) tuple.

No writes. No IB calls. Just Mongo aggregations.

Run on DGX:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_may_june_gap_inventory.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
COLL = "ib_historical_data"

# What we consider a "gap": at least N trading days where we have NO bars.
GAP_MIN_DAYS = 5

# Trading-day approximation (5 of every 7 calendar days). Good enough for ETA.
TRADING_DAYS_PER_WEEK = 5

# Window we suspect the gap lives in.
WINDOW_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 1, tzinfo=timezone.utc)

# Resumption sentinel — symbols that resume EXACTLY here (within 1 day)
# are the handoff signature.
RESUME_DATE = datetime(2026, 6, 1, tzinfo=timezone.utc)
RESUME_TOL_DAYS = 2

# Bar sizes to inspect.
BAR_SIZES = ("1 day", "1 hour", "15 mins", "5 mins", "1 min")


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def parse_date(v):
    """Return aware UTC datetime from BSON Date or 'YYYY-MM-DD[…]' string."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                # Bare YYYY-MM-DD form (1 day bars).
                d = datetime.strptime(v[:10], "%Y-%m-%d")
                return d.replace(tzinfo=timezone.utc)
            except Exception:
                return None
    return None


def trading_days_between(a, b):
    """Crude trading-day count between two aware datetimes."""
    if a is None or b is None or b <= a:
        return 0
    cal = (b - a).days
    return int(cal * TRADING_DAYS_PER_WEEK / 7)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    col = db[COLL]

    # 1. Pull active universe from symbol_adv_cache so we don't chase
    #    delisted/unused tickers.
    have = set(db.list_collection_names())
    if "symbol_adv_cache" not in have:
        print("ERROR: symbol_adv_cache collection missing — cannot scope.")
        sys.exit(1)
    universe = sorted(
        d["symbol"] for d in
        db["symbol_adv_cache"].find({}, {"_id": 0, "symbol": 1})
        if isinstance(d.get("symbol"), str)
    )
    print(f"Active universe: {len(universe)} symbols (from symbol_adv_cache)")
    print(f"Inspecting bar_sizes: {BAR_SIZES}")
    print(f"Gap window: {WINDOW_START.date()} .. {WINDOW_END.date()}")
    print(f"Resume sentinel: {RESUME_DATE.date()} ± {RESUME_TOL_DAYS}d")

    # 2. For each (symbol, bar_size), compute pre-window-max-date and
    #    post-window-min-date. A "qualifying gap" = max_pre < window_start_offset
    #    AND post-min ≈ RESUME_DATE.
    hr("Section 1 — per (symbol, bar_size) gap matrix")
    print(f"  {'symbol':>10} {'bar_size':>8} {'last_pre':>11} "
          f"{'first_post':>11} {'gap_td':>6} {'expect_bars':>11}")
    rows = []
    skipped_no_data = 0
    skipped_no_gap = 0
    skipped_no_resume = 0
    for sym in universe:
        for bs in BAR_SIZES:
            pre = col.find(
                {"symbol": sym, "bar_size": bs,
                 "date": {"$lt": WINDOW_END.strftime("%Y-%m-%d")
                          if bs == "1 day" else WINDOW_END}},
                {"_id": 0, "date": 1},
                sort=[("date", -1)], limit=1
            )
            pre = list(pre)
            post = col.find(
                {"symbol": sym, "bar_size": bs,
                 "date": {"$gte": WINDOW_END.strftime("%Y-%m-%d")
                          if bs == "1 day" else WINDOW_END}},
                {"_id": 0, "date": 1},
                sort=[("date", 1)], limit=1
            )
            post = list(post)
            if not pre or not post:
                skipped_no_data += 1
                continue
            pre_d = parse_date(pre[0].get("date"))
            post_d = parse_date(post[0].get("date"))
            if pre_d is None or post_d is None:
                skipped_no_data += 1
                continue
            gap_td = trading_days_between(pre_d, post_d)
            if gap_td < GAP_MIN_DAYS:
                skipped_no_gap += 1
                continue
            # Resume sentinel filter — only count symbols whose post-gap first
            # bar lands within RESUME_TOL_DAYS of 2026-06-01 (the handoff
            # signature; ignores symbols with other-shaped gaps).
            if abs((post_d - RESUME_DATE).days) > RESUME_TOL_DAYS:
                skipped_no_resume += 1
                continue
            expected_bars = {
                "1 day": gap_td,
                "1 hour": gap_td * 7,    # ~7 RTH hours/day
                "15 mins": gap_td * 26,
                "5 mins": gap_td * 78,
                "1 min": gap_td * 390,
            }.get(bs, gap_td)
            rows.append((sym, bs, pre_d, post_d, gap_td, expected_bars))
            print(f"  {sym:>10} {bs:>8} "
                  f"{pre_d.strftime('%Y-%m-%d'):>11} "
                  f"{post_d.strftime('%Y-%m-%d'):>11} "
                  f"{gap_td:>6} {expected_bars:>11,}")

    hr("Section 2 — roll-up")
    n_unique_syms = len({r[0] for r in rows})
    n_requests = len(rows)
    total_bars = sum(r[5] for r in rows)
    print(f"  qualifying symbols     : {n_unique_syms}")
    print(f"  total (sym,bar_size) requests : {n_requests}")
    print(f"  total bars to backfill : {total_bars:,}")
    print(f"  rejected (no pre/post data)   : {skipped_no_data}")
    print(f"  rejected (gap < {GAP_MIN_DAYS}d) : {skipped_no_gap}")
    print(f"  rejected (post-date ≠ 2026-06-01): {skipped_no_resume}")
    print(f"\n  IB pacing: 58 reqs / 10 min → "
          f"queue ETA ≈ {n_requests * 10 / 58:.0f}m at default cadence "
          f"(turbo cuts this ~3-5x).")

    hr("Section 3 — paste-rs-ready CSV (consume in repair patcher)")
    print("# symbol,bar_size,gap_start_date,gap_end_date,expected_bars")
    for sym, bs, pre_d, post_d, gap_td, expected_bars in rows:
        # Backfill window = the gap (exclusive of the existing pre/post bars).
        gap_start = (pre_d + timedelta(days=1)).strftime("%Y-%m-%d")
        gap_end = (post_d - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"{sym},{bs},{gap_start},{gap_end},{expected_bars}")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
