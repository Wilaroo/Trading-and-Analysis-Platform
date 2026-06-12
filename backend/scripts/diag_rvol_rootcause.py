#!/usr/bin/env python3
"""
diag_rvol_rootcause.py — READ-ONLY round 2: pin the exact RVOL lie
==================================================================
Round 1 (diag_rvol_freshness.py, 2026-06-12) proved:
  * NO today-dated "1 day" bar exists for any probed symbol
  * nightly daily collection is STALE (SPY's newest daily = 06-09!)
  * intraday 1m/5m collection is healthy (900 bars/day, tiny gaps)

Contradiction to resolve: with no today-bar, the scanner's F7 guard sets
session-fraction = 1.0 for a prior-day bar, so RVOL should be ~1.0
(yesterday_vol / avg20) — yet the scanner reported 0.00-0.17x live.
Suspects:
  S1. yesterday's daily-bar volume itself is wrong (units? partial write?)
  S2. mixed `date` formats break the string sort so daily_bars[-1] isn't
      what we think
  S3. the live service computes from different data than the raw collection
  S4. the timestamp rename ('date'→'timestamp') vs probe assumptions

This probe, per symbol:
  [1] dumps the last 8 RAW "1 day" rows: date (verbatim), volume,
      collected_at, source — catches S1/S2 instantly
  [2] replicates the scanner's _calculate_snapshot daily math EXACTLY
      (same sort, same F7 guard) and prints the rvol it implies
  [3] units calibration: sum(1m volumes) for YESTERDAY vs yesterday's
      daily-bar volume → the true lot/share factor (≈1 shares, ≈100 lots)
  [4] asks the LIVE backend: GET /api/technicals/{sym} → the rvol the
      running process actually serves right now (catches S3)
  [5] verdict per symbol

Run DURING MARKET HOURS from repo root:
  .venv/bin/python /tmp/diag_rvol_rootcause.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_SYMBOLS = ["OXY", "ADBE", "XOM", "SPY"]


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


def _now_et():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=4)


def _rth_time_fraction(today_bar, now_et):
    """EXACT mirror of realtime_technical_service._rth_time_fraction."""
    try:
        if today_bar is not None:
            ts = str(today_bar.get("timestamp") or "")[:10].replace("/", "-")
            if len(ts) == 8 and ts.isdigit():
                ts = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            if ts and ts != now_et.strftime("%Y-%m-%d"):
                return 1.0
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if now_et < market_open or now_et >= market_close:
            return 1.0
        minutes = (now_et - market_open).total_seconds() / 60.0
        return max(min(minutes / 390.0, 1.0), 1.0 / 390.0)
    except Exception:
        return 1.0


def _bar_day(b):
    s = str(b.get("date") or "")
    s10 = s[:10].replace("/", "-")
    if len(s10) >= 8 and s10[:8].isdigit():
        return f"{s10[:4]}-{s10[4:6]}-{s10[6:8]}"
    return s10


def probe(db, symbol, now_et):
    print(f"\n{'─' * 70}\n{symbol}")
    col = db["ib_historical_data"]

    # [1] raw last-8 daily rows, scanner's exact sort
    rows = list(col.find(
        {"symbol": symbol, "bar_size": "1 day"},
        {"_id": 0, "date": 1, "volume": 1, "collected_at": 1, "source": 1},
    ).sort("date", -1).limit(8))
    print("  [1] last 8 raw '1 day' rows (scanner sort order, newest first):")
    for r in rows:
        print(f"      date={str(r.get('date'))!r:24s} vol={float(r.get('volume') or 0):>14,.0f} "
              f"collected={str(r.get('collected_at'))[:19]} src={r.get('source')}")

    # [2] scanner replication (50-row window like _get_daily_bars_from_db)
    bars = list(col.find(
        {"symbol": symbol, "bar_size": "1 day"},
        {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ).sort("date", -1).limit(50))
    if len(bars) >= 10:
        bars.reverse()
        for b in bars:
            b["timestamp"] = b.pop("date", None)
        today = bars[-1]
        daily_volume = float(today.get("volume") or 0)
        vols = ([float(b["volume"] or 0) for b in bars[-21:-1]]
                if len(bars) > 21 else [float(b["volume"] or 0) for b in bars[:-1]])
        avg_volume = sum(vols) / len(vols) if vols else daily_volume
        tf = _rth_time_fraction(today, now_et)
        expected = avg_volume * tf
        rvol = daily_volume / expected if expected > 0 else 1.0
        print(f"  [2] scanner replication: daily_bars[-1] ts={today.get('timestamp')!r} "
              f"vol={daily_volume:,.0f}")
        print(f"      avg20={avg_volume:,.0f} tf={tf:.3f} → REPLICATED RVOL={rvol:.2f}x")
    else:
        print(f"  [2] scanner replication: <10 daily rows ({len(bars)}) → "
              f"_get_daily_bars_from_db returns None → FALLBACK rvol=1.0 (!)")

    # [3] units calibration on the most recent day that has BOTH sources
    yday = None
    for r in rows:
        d = _bar_day(r)
        if d and d != now_et.strftime("%Y-%m-%d"):
            yday = (d, float(r.get("volume") or 0))
            break
    if yday:
        d, dvol = yday
        d8 = d.replace("-", "")
        m1 = list(col.find({"symbol": symbol, "bar_size": "1 min"},
                           {"_id": 0, "date": 1, "volume": 1})
                  .sort("date", -1).limit(2500))
        s1 = sum(float(b.get("volume") or 0) for b in m1
                 if str(b.get("date") or "").replace("-", "")[:8] == d8)
        if s1 > 0 and dvol > 0:
            ratio = dvol / s1
            unit = ("SHARES both (ratio≈1)" if 0.5 <= ratio <= 2 else
                    "1m bars in LOTS x100" if 50 <= ratio <= 200 else
                    f"UNEXPECTED ratio {ratio:.1f}")
            print(f"  [3] units calib {d}: daily={dvol:,.0f} vs sum(1m)={s1:,.0f} "
                  f"→ ratio {ratio:.2f} → {unit}")
        else:
            print(f"  [3] units calib {d}: daily={dvol:,.0f} sum(1m)={s1:,.0f} — insufficient")

    # [4] live service answer
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:8001/api/technicals/{symbol}", timeout=8)
        if r.status_code == 200:
            d = r.json() or {}
            t = d.get("technicals") or d
            print(f"  [4] LIVE /api/technicals: rvol={t.get('rvol')} "
                  f"volume={t.get('volume') or t.get('daily_volume')} "
                  f"avg_volume={t.get('avg_volume')} "
                  f"data_source={t.get('data_source')} "
                  f"bar_age_min={t.get('intraday_bar_age_min')}")
        else:
            print(f"  [4] LIVE /api/technicals: HTTP {r.status_code}")
    except Exception as e:
        print(f"  [4] LIVE /api/technicals failed: {e}")


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    now_et = _now_et()
    symbols = [s.upper() for s in sys.argv[1:]] or DEFAULT_SYMBOLS
    print("=" * 70)
    print(f"RVOL ROOT-CAUSE PROBE r2 — {now_et.strftime('%Y-%m-%d %H:%M')} ET")
    print("=" * 70)
    for s in symbols:
        try:
            probe(db, s, now_et)
        except Exception as e:
            print(f"\n{s}: probe error — {e}")
    print(f"\n{'=' * 70}\nprobe complete — no writes")


if __name__ == "__main__":
    main()
