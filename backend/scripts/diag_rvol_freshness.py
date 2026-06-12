#!/usr/bin/env python3
"""
diag_rvol_freshness.py — READ-ONLY probe: why no scalps + broken charts?
========================================================================
Symptom (2026-06-12): opening_drive trades fired 9:34-9:48, then the
scanner skipped EVERYTHING with "RVOL 0.09x below floor 0.80x" by
mid-morning, and the ADBE 1m chart shows flat/garbage segments with a
jump at ~10:35.

HYPOTHESIS (the decay signature): the scanner computes
    rvol = today_daily_volume / (avg_20d_volume * session_fraction)
(v19.34.290 time-of-day adjustment). If TODAY'S "1 day" bar volume in
`ib_historical_data` is written once (early) and never updated intraday,
rvol starts high at the open (tiny session_fraction) and DECAYS toward
zero as the day progresses — fine at 9:35, ~0.1x by 10:50, everything
RVOL-blocked, scalps die first. Sparse 1m bars from the same collector
outage would also explain the chart.

For each probe symbol this script prints:
  [A] today's "1 day" bar row: volume + collected_at (is it stale?)
  [B] today's 1m + 5m bars: count per 30-min bucket, last bar time,
      largest intra-session gap, collected_at lag  → chart evidence
  [C] sum(1m volumes today) vs daily-bar volume    → which is lying
  [D] the scanner's exact RVOL math reproduced: avg20, session fraction,
      rvol-now, PLUS what rvol WOULD be using summed 1m volume
  [E] verdict line per symbol

Run DURING MARKET HOURS from repo root:
  .venv/bin/python /tmp/diag_rvol_freshness.py
  (optionally: .venv/bin/python /tmp/diag_rvol_freshness.py NVDA TSLA)
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_SYMBOLS = ["OXY", "ADBE", "XOM", "EEM", "SNPS", "SPY"]
RTH_OPEN_MIN = 9 * 60 + 30   # 09:30 ET
RTH_CLOSE_MIN = 16 * 60      # 16:00 ET


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


def _et_now():
    # ET = UTC-4 (June, EDT)
    return datetime.now(timezone.utc) - timedelta(hours=4)


def _session_fraction(now_et):
    mins = now_et.hour * 60 + now_et.minute
    if mins <= RTH_OPEN_MIN:
        return 0.0
    return min(1.0, (mins - RTH_OPEN_MIN) / (RTH_CLOSE_MIN - RTH_OPEN_MIN))


def _bar_dt(bar):
    """Best-effort bar timestamp as ET-naive datetime."""
    for k in ("date", "time", "timestamp", "bar_time"):
        v = bar.get(k)
        if v is None:
            continue
        if isinstance(v, datetime):
            return v.replace(tzinfo=None)
        s = str(v)
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                    "%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def probe_symbol(db, symbol, today_str, now_et):
    print(f"\n{'─' * 70}\n{symbol}")
    col = db["ib_historical_data"]

    # [A] today's daily bar
    daily = list(col.find({"symbol": symbol, "bar_size": "1 day"})
                 .sort("date", -1).limit(25))
    today_daily = None
    for d in daily:
        if str(d.get("date", ""))[:10].replace("-", "")[:8] == today_str.replace("-", ""):
            today_daily = d
            break
    if today_daily:
        print(f"  [A] today's 1-day bar: volume={today_daily.get('volume'):,} "
              f"collected_at={str(today_daily.get('collected_at'))[:19]}")
    else:
        print("  [A] today's 1-day bar: MISSING (latest daily row is "
              f"{str(daily[0].get('date'))[:10] if daily else 'none'})")

    # [B] today's intraday bars
    intraday_stats = {}
    for bs in ("1 min", "5 mins"):
        bars = list(col.find({"symbol": symbol, "bar_size": bs})
                    .sort("date", -1).limit(900))
        todays = []
        for b in bars:
            dt = _bar_dt(b)
            if dt and dt.strftime("%Y%m%d") == today_str.replace("-", ""):
                todays.append((dt, b))
        todays.sort(key=lambda x: x[0])
        buckets = defaultdict(int)
        for dt, _ in todays:
            buckets[dt.strftime("%H:%M")[:4] + ("0" if dt.minute < 30 else "3") + "0"] += 1
        gap_max, prev = 0, None
        for dt, _ in todays:
            if prev is not None:
                gap_max = max(gap_max, (dt - prev).total_seconds() / 60)
            prev = dt
        vol_sum = sum(float(b.get("volume") or 0) for _, b in todays)
        last_dt = todays[-1][0] if todays else None
        last_collected = todays[-1][1].get("collected_at") if todays else None
        intraday_stats[bs] = vol_sum
        print(f"  [B] {bs:6s}: {len(todays):4d} bars today | "
              f"last bar {last_dt.strftime('%H:%M') if last_dt else '—'} "
              f"(collected {str(last_collected)[:19]}) | max gap {gap_max:.0f}m")
        if buckets:
            line = " ".join(f"{k}:{v}" for k, v in sorted(buckets.items()))
            print(f"        per-30min: {line}")

    # [C]+[D] the scanner's RVOL math
    closed_dailies = [d for d in daily
                      if str(d.get("date", ""))[:10].replace("-", "")[:8] != today_str.replace("-", "")]
    vols20 = [float(d.get("volume") or 0) for d in closed_dailies[:20]]
    avg20 = sum(vols20) / len(vols20) if vols20 else 0
    tf = _session_fraction(now_et)
    dv = float(today_daily.get("volume") or 0) if today_daily else 0.0
    rvol_now = dv / (avg20 * tf) if avg20 > 0 and tf > 0 else float("nan")
    v1m = intraday_stats.get("1 min", 0.0)
    rvol_1m = v1m / (avg20 * tf) if avg20 > 0 and tf > 0 else float("nan")
    print(f"  [C] volume sources: daily-bar={dv:,.0f} vs sum(1m)={v1m:,.0f} "
          f"vs sum(5m)={intraday_stats.get('5 mins', 0):,.0f}")
    print(f"  [D] avg20={avg20:,.0f} session_frac={tf:.3f} → "
          f"scanner RVOL={rvol_now:.2f}x | RVOL if fed sum(1m)={rvol_1m:.2f}x")

    # [E] verdict
    if today_daily is None:
        print("  [E] VERDICT: no today daily bar at all → scanner sees garbage.")
    elif avg20 > 0 and tf > 0.05:
        if rvol_now < 0.5 and rvol_1m >= 0.8:
            print("  [E] VERDICT: ⚠ DAILY BAR VOLUME IS STALE — intraday volume is "
                  "healthy but the daily row never updates → RVOL decays all day. "
                  "(matches the no-scalps signature)")
        elif rvol_now < 0.5 and rvol_1m < 0.5:
            print("  [E] VERDICT: ⚠ INTRADAY COLLECTION ALSO LOW/SPARSE — collector "
                  "outage (matches the chart gaps).")
        else:
            print("  [E] VERDICT: RVOL inputs look healthy for this symbol.")


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    symbols = [s.upper() for s in sys.argv[1:]] or DEFAULT_SYMBOLS
    now_et = _et_now()
    today_str = now_et.strftime("%Y%m%d")
    print("=" * 70)
    print(f"RVOL / BAR-PIPELINE FRESHNESS PROBE — {now_et.strftime('%Y-%m-%d %H:%M')} ET "
          f"(session fraction {_session_fraction(now_et):.3f})")
    print("=" * 70)
    for s in symbols:
        try:
            probe_symbol(db, s, today_str, now_et)
        except Exception as e:
            print(f"\n{s}: probe error — {e}")
    print(f"\n{'=' * 70}\nprobe complete — no writes")


if __name__ == "__main__":
    main()
