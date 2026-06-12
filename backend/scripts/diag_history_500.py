#!/usr/bin/env python3
"""
diag_history_500.py — capture the EXACT traceback behind the Chart Wall
========================================================================
Probe finding (2026-06-12): /api/sentcom/chart-history returns HTTP 500
on the very FIRST pagination call — that's why charts stop scrolling
back and the history pill spins forever. The DB has ADBE 5-min data
back to 2024-03-21, so this is purely an endpoint failure.

The same code + same DB run fine in the dev environment, so this probe
replays the endpoint function IN-PROCESS on the DGX to print the real
traceback, and cross-checks:

  1. live HTTP call (should reproduce the 500 + error body)
  2. in-process replay of routers.sentcom_chart.get_chart_history
     against the live Mongo — full traceback on failure
  3. JSON-serializability of the replay response (replay OK + HTTP 500
     would mean a serialization/middleware problem, not endpoint logic)
  4. value-type strata of the stored bars (Decimal128/None/str floats)

READ-ONLY — makes no writes. Run from repo root:
  .venv/bin/python /tmp/diag_history_500.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "http://127.0.0.1:8001"
ET = ZoneInfo("America/New_York")


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:800]
        except Exception:
            pass
        return {"_error": f"HTTP {e.code}", "_body": body}
    except Exception as e:
        return {"_error": str(e)}


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "routers" / "sentcom_chart.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def hr(t):
    print("\n" + "=" * 72 + f"\n  {t}\n" + "=" * 72)


def main():
    print(f"diag_history_500 — {datetime.now(ET):%Y-%m-%d %H:%M ET}")
    print(f"python: {sys.version.split()[0]}")
    root = find_root()
    load_env(root)
    sys.path.insert(0, str(root / "backend"))

    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    try:
        from routers import sentcom_chart as sc
    except Exception:
        print("FAILED importing routers.sentcom_chart:")
        traceback.print_exc()
        sys.exit(1)
    sc.init_sentcom_chart_router(None, db)

    for sym in ("ADBE", "SPY"):
        hr(f"{sym} 5min")

        # 0. value-type strata of stored bars (Decimal128 / str / None?)
        types = Counter()
        for d in db["ib_historical_data"].find(
            {"symbol": sym, "bar_size": "5 mins"},
            {"_id": 0, "open": 1, "close": 1, "volume": 1, "date": 1},
        ):
            types[(
                type(d.get("open")).__name__,
                type(d.get("volume")).__name__,
                type(d.get("date")).__name__,
            )] += 1
        print("   (open, volume, date) type strata:")
        for k, n in types.most_common():
            print(f"     {k}: {n}")

        # 1. cursor from live /chart (fallback: newest stored bar)
        chart = _get(f"{API}/api/sentcom/chart?symbol={sym}&timeframe=5min&days=14")
        bars = chart.get("bars") or []
        if bars:
            cursor = int(bars[0]["time"])
        else:
            print(f"   /chart returned no bars ({str(chart)[:120]}) — "
                  f"falling back to newest stored bar")
            newest = db["ib_historical_data"].find_one(
                {"symbol": sym, "bar_size": "5 mins"}, sort=[("date", -1)])
            if not newest:
                print("   no stored 5-min bars either — skipping symbol")
                continue
            cursor = sc._to_utc_seconds(newest.get("date")) or int(
                datetime.now(timezone.utc).timestamp())
        print(f"   cursor (earliest /chart bar): {cursor} = "
              f"{datetime.fromtimestamp(cursor, tz=ET):%Y-%m-%d %H:%M ET}")

        # 2. live HTTP call — expect the 500
        h = _get(f"{API}/api/sentcom/chart-history?symbol={sym}&timeframe=5min&before={cursor}")
        if h.get("_error"):
            print(f"   HTTP: {h['_error']}  body: {h.get('_body', '')[:300]}")
        else:
            print(f"   HTTP: OK bars={h.get('bar_count')} next={h.get('next_before')} "
                  f"more={h.get('has_more')}")

        # 3. in-process replay — walk up to 5 pages, print traceback on raise
        walk = cursor
        res = None
        for page in range(1, 6):
            try:
                res = asyncio.run(sc.get_chart_history(
                    symbol=sym, timeframe="5min", before=int(walk),
                    session="rth_plus_premarket", cap=None,
                ))
            except Exception:
                print(f"   REPLAY p{page} RAISED — Chart Wall traceback:")
                traceback.print_exc()
                res = None
                break
            e = res.get("earliest_time")
            e_str = (datetime.fromtimestamp(e, tz=ET).strftime("%Y-%m-%d %H:%M")
                     if e else "-")
            print(f"   replay p{page}: bars={res['bar_count']} earliest={e_str} "
                  f"next={res.get('next_before')} more={res.get('has_more')}")
            nb = res.get("next_before")
            if not res.get("has_more") or nb is None:
                print("   replay reports end of data")
                break
            if nb >= walk:
                print(f"   STALL: next_before {nb} did not advance past {walk}")
                break
            walk = nb

        # 4. serializability — replay OK but HTTP 500 means the response
        #    can't be JSON-encoded (or middleware breaks)
        if res is not None:
            try:
                json.dumps(res)
                print("   replay response IS json-serializable")
            except Exception as exc:
                print(f"   replay response NOT json-serializable: {exc}")
                def _scan(o, path="$"):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            _scan(v, f"{path}.{k}")
                    elif isinstance(o, list):
                        for i, v in enumerate(o[:3]):
                            _scan(v, f"{path}[{i}]")
                    elif not isinstance(o, (str, int, float, bool, type(None))):
                        print(f"     offender: {path} = {type(o).__name__} {str(o)[:60]}")
                _scan(res)

    print("\ndone (read-only)")


if __name__ == "__main__":
    main()
