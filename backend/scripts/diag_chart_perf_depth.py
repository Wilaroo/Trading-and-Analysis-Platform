#!/usr/bin/env python3
"""
diag_chart_perf_depth.py  (read-only)
=====================================
Measure the THREE things that decide whether charts feel fast / realtime /
deep, per timeframe, at the operator's TARGET history depth:

  • DEPTH AVAILABLE  — how many days of bars actually exist in
    ib_historical_data for (symbol, bar_size). If this is < target, the fix
    is a HISTORY BACKFILL (not a frontend param bump).
  • COLD vs WARM LATENCY — time a cache-miss /chart load at the TARGET days,
    then an immediate re-load (cache hit). Cold = "slow to appear".
  • REALTIME GAP — live_bar_cache latest vs the served chart's latest bar
    ("slow to update").

Operator targets: 1min=7d, 5min=14d, 15min=30d, 1hour=60d, 1day=365d.

Read-only. MONGO_URL + DB_NAME from backend/.env; hits the local API.
Usage:  curl -s <url> | python3 - --symbols CEG,SPY
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("CHART_API", "http://127.0.0.1:8001")
TARGETS = {"1min": 7, "5min": 14, "15min": 30, "1hour": 60, "1day": 365}
TF_TO_BARSIZE = {"1min": "1 min", "5min": "5 mins", "15min": "15 mins",
                 "1hour": "1 hour", "1day": "1 day"}


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        # Running via `curl ... | python3 -` — __file__ is undefined.
        pass
    for cand in cands:
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set.")
        sys.exit(1)
    return MongoClient(url)[name]


def _to_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _get(url):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8"))
        return (time.time() - t0) * 1000, body
    except Exception as e:
        return (time.time() - t0) * 1000, {"error": str(e)}


def _bars_span_days(bars):
    if not bars:
        return 0, None, None
    def _bt(b):
        t = b.get("time") or b.get("date")
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t / 1000 if t > 1e12 else t, timezone.utc)
        return _to_dt(t)
    a, b2 = _bt(bars[0]), _bt(bars[-1])
    if a and b2:
        return round((b2 - a).total_seconds() / 86400, 1), a, b2
    return 0, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="CEG,SPY")
    args = ap.parse_args()
    _load_env()
    db = _db()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    now = datetime.now(timezone.utc)
    print(f"[api] {API}   now={now.isoformat()[:19]}Z\n")

    for sym in syms:
        print("=" * 92)
        print(f"SYMBOL {sym}")
        print("=" * 92)
        hdr = (f"{'TF':<6} {'target':>7} {'avail_d':>8} {'stored_bars':>11} "
               f"{'COLD_ms':>8} {'WARM_ms':>8} {'served_d':>9} {'served_bars':>11} "
               f"{'rt_gap':>8}")
        print(hdr)
        print("-" * len(hdr))
        for tf, tgt in TARGETS.items():
            bs = TF_TO_BARSIZE[tf]
            # available depth in storage
            coll = db["ib_historical_data"]
            n_stored = coll.count_documents({"symbol": sym, "bar_size": bs})
            oldest = coll.find_one({"symbol": sym, "bar_size": bs}, sort=[("date", 1)])
            newest = coll.find_one({"symbol": sym, "bar_size": bs}, sort=[("date", -1)])
            avail_d = "-"
            od, nd = _to_dt((oldest or {}).get("date")), _to_dt((newest or {}).get("date"))
            if od and nd:
                avail_d = round((nd - od).total_seconds() / 86400, 1)

            # cold load at target depth (cache-bust with a rare days value first
            # is hard since cache keys on days; use target days, time it; the
            # 2nd identical call is the warm hit)
            url = f"{API}/api/sentcom/chart?symbol={sym}&timeframe={tf}&days={tgt}"
            cold_ms, cold = _get(url)
            warm_ms, warm = _get(url)
            served_bars = len(cold.get("bars") or [])
            served_d, _, _ = _bars_span_days(cold.get("bars") or [])
            cache_state = warm.get("cache", "?")

            # realtime gap (intraday only)
            rt = "-"
            if tf in ("1min", "5min", "15min", "1hour"):
                lbc = db["live_bar_cache"].find_one({"symbol": sym, "bar_size": bs})
                lbc_latest = None
                if lbc and lbc.get("bars"):
                    lbc_latest = _to_dt(lbc["bars"][-1].get("date") or lbc["bars"][-1].get("time"))
                served = cold.get("bars") or []
                srv_latest = None
                if served:
                    t = served[-1].get("time") or served[-1].get("date")
                    srv_latest = (datetime.fromtimestamp(t/1000 if isinstance(t,(int,float)) and t>1e12 else t, timezone.utc)
                                  if isinstance(t, (int, float)) else _to_dt(t))
                if lbc_latest and srv_latest:
                    rt = f"{(lbc_latest - srv_latest).total_seconds():.0f}s"
                elif not lbc:
                    rt = "no-lbc"

            flag = ""
            if isinstance(avail_d, (int, float)) and avail_d < tgt:
                flag += " ⚠BACKFILL"
            if cold_ms > 2500:
                flag += " 🐢COLD"
            print(f"{tf:<6} {tgt:>6}d {str(avail_d):>8} {n_stored:>11} "
                  f"{cold_ms:>8.0f} {warm_ms:>8.0f} {str(served_d):>9} {served_bars:>11} "
                  f"{rt:>8}  {cache_state}{flag}")
        print()

    print("LEGEND: avail_d=days of history stored | COLD_ms=cache-miss load | "
          "WARM_ms=cache-hit load | served_d=days actually returned | "
          "rt_gap=feed−served | ⚠BACKFILL=storage<target | 🐢COLD=>2.5s")
    print("Done (read-only).")


if __name__ == "__main__":
    main()
