#!/usr/bin/env python3
"""
v330 — RUBBER BAND SHORT-SIDE TRADE-OUTCOME REPLAY (READ-ONLY, native 1-min bars)

Mirror of v329 for the SHORT snapback (mean-reversion fade from an overbought
extension). v329 proved the LONG side is strongly +EV (+0.268R, 76% win). The
SHORT side is UNVALIDATED and we already proved off_sides_short (shorting into
strength) has NO edge — so we must measure before rewiring the FIRE short path.

DETECTOR (symmetric to v329 long):
  • extension : running HIGH-of-day >= open x (1 + EXT_PCT/100)
  • acceleration: the HOD bar's range >= ACCEL x median 1-min range so far
  • SNAPBACK : first RED 1-min bar whose LOW breaks BELOW the lows of the 2
    preceding bars, within TRIGGER_WINDOW bars of the HOD bar (a double-bar
    break DOWN)
  • discipline: cap 2 events/day

TRADE MODEL (symmetric to v329):
  entry  = double-bar-break-down level = min(low[i-1], low[i-2])  (stop-sell fill)
  stop   = running high-of-day at trigger + $0.02
  target = 9-EMA on 1-min closes at entry (floored to 1R if already at mean)
  walk fwd up to --maxhold bars: stop-first if high>=stop (-1R), else target if
  low<=target (+R_target), else mark-to-market at last close.

OUTPUT: n, win%, avg/median R, total R, by EXTENSION BUCKET and snapback speed.
Compare directly to v329 long numbers to decide long-only vs both-sides deploy.

NOTHING IS WRITTEN. ib_historical_data + live_alerts read-only.

Usage (from repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v330_rubber_band_short_replay.py --days 14 --universe 300
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
TRIGGER_WINDOW = 6
ACCEL = 1.3
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


def _detect_short_snapbacks(bars, ext_pct):
    """Symmetric to v329 long: extension ABOVE open + double-bar-break DOWN."""
    if len(bars) < 5:
        return []
    o = bars[0]["open"]
    if not o or o <= 0:
        return []
    high_of_day = o
    hod_idx = 0
    ranges = []
    events = []
    armed = False
    armed_at = None
    for i, b in enumerate(bars):
        rng = (b["high"] - b["low"]) if (b["high"] and b["low"]) else 0.0
        if b["high"] and b["high"] > high_of_day:
            high_of_day = b["high"]
            hod_idx = i
            if high_of_day >= o * (1.0 + ext_pct / 100.0):
                med_r = median(ranges) if ranges else 0.0
                accel_ok = (med_r <= 0) or (rng >= ACCEL * med_r)
                armed = True
                armed_at = i if accel_ok else None
        if armed and armed_at is not None and i >= 2 and i - hod_idx <= TRIGGER_WINDOW:
            red = b["close"] < b["open"]
            breaks = b["low"] < min(bars[i - 1]["low"], bars[i - 2]["low"])
            if red and breaks:
                events.append({
                    "ext_pct": round((high_of_day - o) / o * 100.0, 2),
                    "trigger_idx": i,
                    "hod_high": high_of_day,
                    "bars_from_hod": i - hod_idx,
                })
                armed = False
                armed_at = None
                if len(events) >= 2:
                    break
        ranges.append(rng)
    return events


def _simulate_short(bars, ev, maxhold):
    i = ev["trigger_idx"]
    if i < 2 or i + 1 >= len(bars):
        return None
    entry = min(bars[i - 1]["low"], bars[i - 2]["low"])
    stop = ev["hod_high"] + 0.02
    risk = stop - entry
    if risk <= 0:
        return None
    closes = [b["close"] for b in bars[:i + 1]]
    ema9 = _ema(closes, EMA_P)
    target = ema9 if (ema9 and ema9 < entry) else (entry - risk)  # 1R floor
    r_target = (entry - target) / risk
    end = min(i + 1 + maxhold, len(bars))
    for j in range(i + 1, end):
        b = bars[j]
        if b["high"] >= stop:
            return -1.0
        if b["low"] <= target:
            return round(r_target, 3)
    return round((entry - bars[end - 1]["close"]) / risk, 3)


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

    print(f"\n=== v330 RUBBER BAND SHORT TRADE REPLAY — trailing {days}d  ext>={ext_pct:g}%  "
          f"univ<={uni_cap}  maxhold={maxhold}min ===\n")
    print("  entry=double-bar-break-DOWN  stop=HOD+0.02  target=9EMA(1m) (1R floor)\n")

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
            evs = _detect_short_snapbacks(bars, ext_pct)
            if evs:
                days_with_event += 1
            for ev in evs:
                n_events += 1
                ext_dist.append(ev["ext_pct"])
                r = _simulate_short(bars, ev, maxhold)
                if r is None:
                    continue
                n_tradeable += 1
                all_r.append(r)
                by_bucket[_bucket(ev["ext_pct"])].append(r)
                by_window[ev["bars_from_hod"]].append(r)

    print("=" * 72)
    print(f"EVENTS: {n_events} detected ({days_with_event} symbol-days), {n_tradeable} tradeable")
    if ext_dist:
        sd = sorted(ext_dist)
        print(f"extension-from-open dist: p25={sd[len(sd)//4]:.1f}%  "
              f"p50={sd[len(sd)//2]:.1f}%  p75={sd[3*len(sd)//4]:.1f}%  max={sd[-1]:.1f}%")
    print("=" * 72)
    print("OVERALL (SHORT)")
    _report("ALL", all_r)
    print("\nBY EXTENSION BUCKET")
    for b in ("1-2%", "2-3%", ">=3%"):
        _report(b, by_bucket.get(b, []))
    print("\nBY SNAPBACK SPEED (bars from HOD)")
    for w in sorted(by_window):
        _report(f"+{w}bar", by_window[w])

    print("\n=== READING THE RESULT (compare to v329 long: +0.268R, 76% win) ===")
    print("• SHORT avgR comfortably >0 across buckets → build BOTH sides into patch_v330.")
    print("• SHORT avgR <=0 or much weaker than long → ship LONG-ONLY; do NOT rewire shorts")
    print("    (consistent with off_sides_short: fading strength has no edge in this regime).")
    print("• If only >=3% is +EV on shorts, use a HIGHER short ext floor than the long side.\n")


if __name__ == "__main__":
    main()
