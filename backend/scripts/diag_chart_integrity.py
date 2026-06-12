#!/usr/bin/env python3
"""
diag_chart_integrity.py — READ-ONLY probe: where do the garbage chart bars come from?
=====================================================================================
Symptom (2026-06-12, ADBE 1m chart): long flat segment at a wrong price
followed by a vertical jump to the real price. The /chart pipeline has
several layers that could each inject this:

    Mongo historical rows → hybrid get_bars → pusher live-merge →
    normalise/dedup → bad-tick clamp → session filter → response cache

The v19.34.265 bad-tick clamp only fixes LONE spikes — a CONTIGUOUS run
of corrupt bars survives because the local median inside the run IS the
corrupt price. This probe captures the ACTUAL served bars and the RAW
Mongo rows for the same window and reports which layer is lying.

Per symbol/timeframe it prints:
  [1] /api/sentcom/chart response meta: bar_count, cache hit/miss,
      live_appended/live_source, stale/partial flags, timings
  [2] served-bar anomaly scan: flat runs (>=10 identical closes), jumps
      (bar-to-bar close move >3%), with ET timestamps + context bars
  [3] raw Mongo scan of the same ET window ('1 min' rows): price
      min/max, same anomaly scan → corrupt in Mongo = collector bug;
      clean in Mongo = merge/cache bug
  [4] response-cache key freshness for the symbol

Run from repo root (market hours ideal but not required):
  .venv/bin/python /tmp/diag_chart_integrity.py            # ADBE
  .venv/bin/python /tmp/diag_chart_integrity.py NVDA 5min  # custom
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

API = "http://127.0.0.1:8001/api/sentcom/chart"


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _et(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, tz=ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


def _scan_anomalies(bars, label):
    """bars: list of dicts with time/close (UTC seconds)."""
    if not bars:
        print(f"  [{label}] no bars to scan")
        return
    closes = [b["close"] for b in bars]
    lo, hi = min(closes), max(closes)
    print(f"  [{label}] {len(bars)} bars | close min={lo:.2f} max={hi:.2f} "
          f"| {_et(bars[0]['time'])} → {_et(bars[-1]['time'])} ET")

    # flat runs
    runs = []
    start = 0
    for i in range(1, len(bars) + 1):
        if i == len(bars) or bars[i]["close"] != bars[start]["close"]:
            if i - start >= 10:
                runs.append((start, i - 1))
            start = i
    for s, e in runs[:6]:
        print(f"      FLAT RUN: {e - s + 1} bars @ {bars[s]['close']:.2f} "
              f"({_et(bars[s]['time'])} → {_et(bars[e]['time'])} ET)")

    # jumps
    jumps = []
    for i in range(1, len(bars)):
        prev, cur = bars[i - 1]["close"], bars[i]["close"]
        if prev > 0 and abs(cur - prev) / prev > 0.03:
            jumps.append(i)
    for i in jumps[:6]:
        print(f"      JUMP: {bars[i-1]['close']:.2f} → {bars[i]['close']:.2f} "
              f"({100.0*(bars[i]['close']-bars[i-1]['close'])/bars[i-1]['close']:+.1f}%) "
              f"at {_et(bars[i]['time'])} ET")
        for j in range(max(0, i - 2), min(len(bars), i + 3)):
            b = bars[j]
            print(f"        {_et(b['time'])}  O={b.get('open', 0):.2f} H={b.get('high', 0):.2f} "
                  f"L={b.get('low', 0):.2f} C={b['close']:.2f} V={b.get('volume', 0)}")
    if not runs and not jumps:
        print("      no flat runs >=10 bars, no >3% jumps — series looks clean")


def probe(db, symbol, tf):
    import requests
    print(f"\n{'─' * 72}\n{symbol} {tf}")

    # [1]+[2] served response (twice: cached + cache-busted via days)
    for days, tag in ((1, "days=1"), (2, "days=2 (cache-bust)")):
        try:
            r = requests.get(API, params={"symbol": symbol, "timeframe": tf,
                                          "days": days}, timeout=30)
            d = r.json()
        except Exception as e:
            print(f"  [1] /chart {tag} FAILED: {e}")
            continue
        t = d.get("timings") or {}
        print(f"  [1] /chart {tag}: success={d.get('success')} bars={d.get('bar_count')} "
              f"cache={d.get('cache')} live_appended={d.get('live_appended')} "
              f"live_source={d.get('live_source')} stale={d.get('stale')} "
              f"partial={d.get('partial')} total_ms={t.get('total_ms')}")
        bars = d.get("bars") or []
        # focus the anomaly scan on TODAY's ET session bars only
        if bars:
            today_cut = bars[-1]["time"] - 86400
            recent = [b for b in bars if b["time"] >= today_cut]
            _scan_anomalies(recent, f"2 served last-24h ({tag})")
        if days == 1:
            out = Path(f"/tmp/chart_{symbol}_{tf}_served.json")
            out.write_text(json.dumps(d.get("bars") or []))
            print(f"      full served bars saved → {out}")

    # [3] raw Mongo same window
    col = db["ib_historical_data"]
    bar_size = {"1min": "1 min", "5min": "5 mins", "15min": "15 mins",
                "1hour": "1 hour"}.get(tf, "1 min")
    rows = list(col.find({"symbol": symbol, "bar_size": bar_size},
                         {"_id": 0, "date": 1, "open": 1, "high": 1,
                          "low": 1, "close": 1, "volume": 1})
                .sort("date", -1).limit(1500))
    raw = []
    for b in rows:
        s = str(b.get("date") or "")
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            raw.append({"time": int(dt.timestamp()),
                        "open": float(b.get("open") or 0),
                        "high": float(b.get("high") or 0),
                        "low": float(b.get("low") or 0),
                        "close": float(b.get("close") or 0),
                        "volume": b.get("volume") or 0})
        except (ValueError, TypeError):
            continue
    raw.sort(key=lambda x: x["time"])
    if raw:
        cut = raw[-1]["time"] - 86400
        _scan_anomalies([b for b in raw if b["time"] >= cut], "3 RAW Mongo last-24h")
        # duplicate-timestamp check (chunk seams)
        times = [b["time"] for b in raw]
        dups = len(times) - len(set(times))
        if dups:
            print(f"      ⚠ {dups} duplicate timestamps in raw rows (chunk seams)")
    else:
        print("  [3] no raw rows parsed")

    # [4] response-cache entries for this symbol
    try:
        cache_rows = list(db["chart_response_cache"].find(
            {"key": {"$regex": f"^{symbol}:"}},
            {"_id": 0, "key": 1, "created_at": 1, "expires_at": 1}).limit(10))
        for c in cache_rows:
            print(f"  [4] cache {c.get('key')} created={str(c.get('created_at'))[:19]} "
                  f"expires={str(c.get('expires_at'))[:19]}")
        if not cache_rows:
            print("  [4] no response-cache rows for symbol")
    except Exception as e:
        print(f"  [4] cache inspect failed: {e}")


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    args = sys.argv[1:]
    symbol = (args[0] if args else "ADBE").upper()
    tfs = [args[1]] if len(args) > 1 else ["1min", "5min"]
    print("=" * 72)
    print(f"CHART INTEGRITY PROBE — {symbol} {tfs} — "
          f"{datetime.now(timezone.utc).isoformat()[:16]}Z")
    print("=" * 72)
    for tf in tfs:
        try:
            probe(db, symbol, tf)
        except Exception as e:
            print(f"{tf}: probe error — {e}")
    print(f"\n{'=' * 72}\nprobe complete — no writes (served bars dumped to /tmp)")


if __name__ == "__main__":
    main()
