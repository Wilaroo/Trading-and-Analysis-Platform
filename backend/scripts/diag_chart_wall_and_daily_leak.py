#!/usr/bin/env python3
"""
diag_chart_wall_and_daily_leak.py — READ-ONLY forensics (2026-06-12)
=====================================================================
Two mysteries from diag_decision_audit:

A. CHART WALL — ADBE has 5-min bars back to 2024-03-21 (45k rows), yet
   the chart only scrolls back to ~Jun 8 with the history pill spinning.
   Suspects: (1) stale chart_response_cache serving a pre-backfill
   window, (2) date-FORMAT heterogeneity (UTC-offset vs naive-ET vs
   space-separated strings) breaking string-sorted pagination or the
   naive-as-UTC parse, (3) /chart-history pagination stalling.
   This probe walks the REAL API pagination and maps the format strata.

B. DAILY-BAR LEAK — 19 in-progress daily bars exist for today before
   the close (v323b guard expected 0). Which writer path stamped them?

READ-ONLY. Run from repo root:
  .venv/bin/python /tmp/diag_chart_wall_and_daily_leak.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pymongo import MongoClient

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
API = "http://127.0.0.1:8001"


def _load_env():
    for cand in (".", "backend", "../backend"):
        p = os.path.join(cand, ".env")
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def fmt_class(s) -> str:
    s = str(s)
    if "+" in s or s.endswith("Z"):
        return "UTC_OFFSET"
    if "T" in s:
        return "T_NAIVE"
    if " " in s:
        return "SPACE_NAIVE"
    return "OTHER"


def parse_as_utc(s):
    """Mirror of sentcom_chart._to_utc_seconds string path."""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())
    except Exception:
        return None


def hr(t):
    print("\n" + "═" * 72 + f"\n  {t}\n" + "═" * 72)


def main():
    _load_env()
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    hist = db["ib_historical_data"]
    now_et = datetime.now(ET)
    print(f"diag_chart_wall_and_daily_leak — {now_et:%Y-%m-%d %H:%M ET}")

    # ────────────────────────────────────────────────────────────────
    hr("A1. DATE-FORMAT STRATA (ADBE + SPY, 5 mins & 1 min)")
    # ────────────────────────────────────────────────────────────────
    for sym in ("ADBE", "SPY"):
        for bs in ("5 mins", "1 min"):
            strata = defaultdict(lambda: {"n": 0, "min": None, "max": None, "sample": None})
            for doc in hist.find({"symbol": sym, "bar_size": bs},
                                 {"_id": 0, "date": 1}):
                d = str(doc.get("date"))
                c = fmt_class(d)
                s = strata[c]
                s["n"] += 1
                if s["min"] is None or d < s["min"]:
                    s["min"] = d
                if s["max"] is None or d > s["max"]:
                    s["max"] = d
                if s["sample"] is None:
                    s["sample"] = d
            print(f"\n   {sym} {bs}:")
            for c, s in sorted(strata.items()):
                parsed = parse_as_utc(s["sample"])
                shown = (datetime.fromtimestamp(parsed, tz=ET).strftime("%m-%d %H:%M ET")
                         if parsed else "PARSE-FAIL")
                print(f"     {c:<12} n={s['n']:<7} min={s['min'][:19]:<20} "
                      f"max={s['max'][:19]:<20}")
                print(f"       sample '{s['sample']}' → parsed-as-UTC renders {shown}"
                      f"  {'⚠ 4h SKEW if stored as ET-naive' if c != 'UTC_OFFSET' else ''}")
            # string-sort sanity: does the format boundary scramble order?
            if len(strata) > 1:
                print(f"     ⚠ {len(strata)} formats coexist — string sort('date') "
                      f"interleaves them: ' ' < 'T' < '0-9' rules apply")

    # ────────────────────────────────────────────────────────────────
    hr("A2. chart_response_cache staleness (ADBE)")
    # ────────────────────────────────────────────────────────────────
    if "chart_response_cache" in db.list_collection_names():
        rows = list(db["chart_response_cache"].find(
            {"$or": [{"symbol": "ADBE"}, {"key": {"$regex": "ADBE"}},
                     {"cache_key": {"$regex": "ADBE"}}]},).limit(10))
        if not rows:
            print("   no ADBE cache entries")
        for r in rows:
            keys = {k: r.get(k) for k in ("key", "cache_key", "symbol", "timeframe",
                                          "days", "created_at", "updated_at", "ts")
                    if k in r}
            bars = r.get("bars") or (r.get("payload") or {}).get("bars") or []
            span = (str(bars[0].get("time"))[:16] + " → " +
                    str(bars[-1].get("time"))[:16]) if bars else "—"
            print(f"   {json.dumps(keys, default=str)[:160]} bars={len(bars)} span={span}")
    else:
        print("   (no chart_response_cache collection)")

    # ────────────────────────────────────────────────────────────────
    hr("A3. LIVE PAGINATION WALK — /api/sentcom/chart-history ADBE 5min")
    # ────────────────────────────────────────────────────────────────
    chart = _get(f"{API}/api/sentcom/chart?symbol=ADBE&timeframe=5min&days=14")
    if chart.get("_error") or not chart.get("success"):
        print(f"   /chart failed: {str(chart)[:200]}")
        return
    bars = chart.get("bars") or []
    print(f"   /chart days=14 → {len(bars)} bars, "
          f"earliest={datetime.fromtimestamp(bars[0]['time'], tz=ET):%Y-%m-%d %H:%M ET}, "
          f"latest={datetime.fromtimestamp(bars[-1]['time'], tz=ET):%Y-%m-%d %H:%M ET}")
    if bars and (datetime.now(UTC).timestamp() - bars[0]["time"]) < 12 * 86400:
        print("   ⚠ initial window much shallower than 14d — cache or composition issue")

    cursor = bars[0]["time"]
    prev_earliest = cursor
    stall = 0
    for page in range(1, 26):
        h = _get(f"{API}/api/sentcom/chart-history?symbol=ADBE&timeframe=5min&before={cursor}")
        if h.get("_error") or not h.get("success"):
            print(f"   p{page}: FAILED {str(h)[:160]}")
            break
        et_earliest = (datetime.fromtimestamp(h["earliest_time"], tz=ET)
                       .strftime("%Y-%m-%d %H:%M") if h.get("earliest_time") else "—")
        print(f"   p{page}: bars={h.get('bar_count')} earliest={et_earliest} "
              f"next_before={h.get('next_before')} has_more={h.get('has_more')}")
        nb = h.get("next_before")
        if not h.get("has_more"):
            print("   pagination reports END of data")
            break
        if nb is None or nb >= cursor:
            stall += 1
            print(f"   ⚠ CURSOR DID NOT ADVANCE (nb={nb} vs cursor={cursor}) — STALL")
            if stall >= 2:
                break
            cursor = cursor - 86400  # nudge to keep diagnosing
        else:
            cursor = nb
        if h.get("bar_count") and h.get("earliest_time"):
            if h["earliest_time"] >= prev_earliest:
                print(f"   ⚠ page earliest {h['earliest_time']} NOT older than previous "
                      f"{prev_earliest} — prepend would be EMPTY in the UI (frontend stall)")
            prev_earliest = min(prev_earliest, h["earliest_time"])
    final_et = datetime.fromtimestamp(prev_earliest, tz=ET)
    print(f"   walked back to: {final_et:%Y-%m-%d %H:%M ET}")

    # ────────────────────────────────────────────────────────────────
    hr("B. DAILY-BAR LEAK — who wrote today's in-progress daily bars?")
    # ────────────────────────────────────────────────────────────────
    today = now_et.strftime("%Y-%m-%d")
    rows = list(hist.find({"bar_size": "1 day", "date": today}).limit(25))
    # also catch datetime-typed / prefixed dates
    rows += list(hist.find({"bar_size": "1 day",
                            "date": {"$regex": f"^{today}"}}).limit(25))
    seen = set()
    print(f"   rows with date == '{today}' (or prefix): {len(rows)}")
    for r in rows:
        key = (r.get("symbol"), str(r.get("date")))
        if key in seen:
            continue
        seen.add(key)
        meta = {k: str(v)[:40] for k, v in r.items()
                if k not in ("_id", "open", "high", "low", "close", "volume")}
        print(f"     {json.dumps(meta, default=str)[:240]}")
    if not rows:
        print("   none right now (TTL/cleanup may have removed them — rerun pre-close)")

    print("\ndone (read-only)")


if __name__ == "__main__":
    main()
