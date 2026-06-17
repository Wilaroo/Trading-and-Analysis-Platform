#!/usr/bin/env python3
"""
v329 — RUBBER BAND REDESIGN: TRADE-OUTCOME REPLAY (READ-ONLY, native 1-min bars)

WHY: v321c proved the FIND (919 real double-bar-break snapbacks, ext-from-open
calibration: ≥2%=29% of cells). But FIND alone doesn't justify rewiring the live
FIRE path — given the thin/negative sanitized edge, we must prove the redesigned
detector would actually EARN edge, and find the extension threshold that maximizes
it. This diag reuses v321c's EXACT snapback detector, then for every detected
event SIMULATES the trade forward on the same 1-min series and reports realized R.

TRADE MODEL (matches the live detector's geometry):
  entry  = the double-bar-break level  = max(high[i-1], high[i-2])  (stop-buy fill)
  stop   = running low-of-day at trigger − $0.02  (detector: low_of_day − 0.02)
  target = 9-EMA on the 1-min closes at entry  (detector target_1 = ema_9);
           floored to a 1R target if price already reached the mean.
  walk forward up to --maxhold bars: stop-first if low<=stop (−1R), else target if
  high>=target (+R_target), else mark-to-market at the last close.

OUTPUT: n events, win%, avg/median R, total expectancy, broken out BY EXTENSION
BUCKET (1-2% / 2-3% / >=3%) and by trigger-window position — so we can pick the
ext threshold + trigger window that the FIRE detector should use.

NOTHING IS WRITTEN. ib_historical_data + live_alerts read-only.

Usage (from repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v329_rubber_band_trade_replay.py
  ... --days 14 --ext 1.0 --universe 300 --maxhold 30
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median, mean

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TRIGGER_WINDOW = 6     # snapback must print within N bars after the LOD bar
ACCEL = 1.3            # LOD-bar range >= ACCEL x median range so far
EMA_P = 9


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _to_et(v):
    if isinstance(v, str) and len(v) >= 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
        except Exception:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(ET)
    return None


def _is_rth(et):
    if et is None or et.weekday() >= 5:
        return False
    m = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= m <= 16 * 60


def _ema(vals, p):
    if not vals:
        return None
    if len(vals) < p:
        return sum(vals) / len(vals)
    k = 2 / (p + 1)
    e = sum(vals[:p]) / p
    for v in vals[p:]:
        e = (v - e) * k + e
    return e


def _detect_long_snapbacks(bars, ext_pct):
    """Reuses v321c's proven detector; additionally returns lod_low at trigger."""
    if len(bars) < 5:
        return []
    o = bars[0]["open"]
    if not o or o <= 0:
        return []
    low_of_day = o
    lod_idx = 0
    ranges = []
    events = []
    armed = False
    armed_at = None
    for i, b in enumerate(bars):
        rng = (b["high"] - b["low"]) if (b["high"] and b["low"]) else 0.0
        if b["low"] and b["low"] < low_of_day:
            low_of_day = b["low"]
            lod_idx = i
            if low_of_day <= o * (1.0 - ext_pct / 100.0):
                med_r = median(ranges) if ranges else 0.0
                accel_ok = (med_r <= 0) or (rng >= ACCEL * med_r)
                armed = True
                armed_at = i if accel_ok else None
        if armed and armed_at is not None and i >= 2 and i - lod_idx <= TRIGGER_WINDOW:
            green = b["close"] > b["open"]
            clears = b["high"] > max(bars[i - 1]["high"], bars[i - 2]["high"])
            if green and clears:
                events.append({
                    "ext_pct": round((o - low_of_day) / o * 100.0, 2),
                    "trigger_idx": i,
                    "lod_low": low_of_day,
                    "bars_from_lod": i - lod_idx,
                })
                armed = False
                armed_at = None
                if len(events) >= 2:   # 2/day cap
                    break
        ranges.append(rng)
    return events


def _simulate_trade(bars, ev, maxhold):
    """Returns realized R for one snapback long event, or None if untradeable."""
    i = ev["trigger_idx"]
    if i < 2 or i + 1 >= len(bars):
        return None
    entry = max(bars[i - 1]["high"], bars[i - 2]["high"])
    stop = ev["lod_low"] - 0.02
    risk = entry - stop
    if risk <= 0:
        return None
    closes = [b["close"] for b in bars[:i + 1]]
    ema9 = _ema(closes, EMA_P)
    target = ema9 if (ema9 and ema9 > entry) else (entry + risk)  # 1R floor
    r_target = (target - entry) / risk
    end = min(i + 1 + maxhold, len(bars))
    for j in range(i + 1, end):
        b = bars[j]
        if b["low"] <= stop:
            return -1.0
        if b["high"] >= target:
            return round(r_target, 3)
    # mark-to-market at last available close in window
    return round((bars[end - 1]["close"] - entry) / risk, 3)


def _bucket(ext):
    if ext < 2.0:
        return "1-2%"
    if ext < 3.0:
        return "2-3%"
    return ">=3%"


def _report(label, rs):
    if not rs:
        print(f"  {label:<10} n=0")
        return
    wins = sum(1 for r in rs if r > 0)
    print(f"  {label:<10} n={len(rs):<4} win={100.0*wins/len(rs):>3.0f}%  "
          f"avgR={mean(rs):+.3f}  medR={median(rs):+.3f}  "
          f"totR={sum(rs):+.1f}  EV/trade={mean(rs):+.3f}R")


def main():
    days = _arg("--days", 14, int)
    ext_pct = _arg("--ext", 1.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v329 RUBBER BAND TRADE REPLAY — trailing {days}d  ext>={ext_pct:g}%  "
          f"univ<={uni_cap}  maxhold={maxhold}min ===\n")
    print("  entry=double-bar-break  stop=LOD-0.02  target=9EMA(1m) (1R floor)\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1,
                                       "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} scanner-watched symbols\n")

    all_r, by_bucket, by_window = [], defaultdict(list), defaultdict(list)
    ext_dist = []
    n_events = n_tradeable = days_with_event = 0
    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": "1 min", "date": {"$gte": start_utc.isoformat()}},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
        by_day = defaultdict(list)
        for b in cur:
            et = _to_et(b.get("date"))
            if _is_rth(et):
                by_day[et.strftime("%Y-%m-%d")].append(b)
        for day, bars in by_day.items():
            bars.sort(key=lambda x: x["date"])
            evs = _detect_long_snapbacks(bars, ext_pct)
            if evs:
                days_with_event += 1
            for ev in evs:
                n_events += 1
                ext_dist.append(ev["ext_pct"])
                r = _simulate_trade(bars, ev, maxhold)
                if r is None:
                    continue
                n_tradeable += 1
                all_r.append(r)
                by_bucket[_bucket(ev["ext_pct"])].append(r)
                by_window[ev["bars_from_lod"]].append(r)

    print("=" * 72)
    print(f"EVENTS: {n_events} detected ({days_with_event} symbol-days), {n_tradeable} tradeable")
    if ext_dist:
        sd = sorted(ext_dist)
        print(f"extension-from-open dist: p25={sd[len(sd)//4]:.1f}%  "
              f"p50={sd[len(sd)//2]:.1f}%  p75={sd[3*len(sd)//4]:.1f}%  max={sd[-1]:.1f}%")
    print("=" * 72)
    print("OVERALL")
    _report("ALL", all_r)
    print("\nBY EXTENSION BUCKET  (which ext threshold earns edge?)")
    for b in ("1-2%", "2-3%", ">=3%"):
        _report(b, by_bucket.get(b, []))
    print("\nBY SNAPBACK SPEED (bars from LOD to trigger)")
    for w in sorted(by_window):
        _report(f"+{w}bar", by_window[w])

    print("\n=== READING THE RESULT ===")
    print("• Pick the lowest ext bucket whose avgR is comfortably >0 → that becomes the")
    print("    FIRE detector's extension floor (don't fire below it).")
    print("• If even >=3% is <=0, the snapback-long has no edge in this regime → do NOT")
    print("    rewire FIRE; revisit entry/stop/target geometry or the regime filter first.")
    print("• Faster snapbacks (+1/+2 bars) usually carry the edge; a wide trigger window")
    print("    dilutes it — tighten TRIGGER_WINDOW if late triggers are negative.\n")


if __name__ == "__main__":
    main()
