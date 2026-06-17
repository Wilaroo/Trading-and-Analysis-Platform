#!/usr/bin/env python3
"""
v340 — VWAP-FADE TRADE-OUTCOME REPLAY (READ-ONLY, native 1-min bars)

FADE SWEEP #1 (highest volume: vwap_fade 4982 fires / 73 genuine in 30d).
Generalizes the PROVEN v329/v330 rubber_band snapback template from
extension-from-OPEN to extension-from-VWAP — the actual vwap_fade thesis:
price stretches FAR from VWAP, then fades BACK to the mean.

  SHORT fade: price extends ABOVE VWAP (shorting strength — the v336/off_sides
              danger profile; measure honestly, do NOT assume edge).
  LONG  fade: price extends BELOW VWAP, fade the snapback up to VWAP.

TRADE MODEL (mirrors v329 geometry, anchored to a live cumulative 1-min VWAP):
  SHORT: arm when (high-vwap)/vwap >= ext%. Trigger = first RED bar within
         TRIGGER_WINDOW bars of the extreme-HIGH bar whose low breaks the
         prior-2 lows. entry = min(low[i-1],low[i-2]); stop = extreme_high+0.02;
         target = VWAP@entry (1R floor). Walk fwd: high>=stop → -1R; low<=target → +R.
  LONG : mirror (extreme-LOW, first GREEN breaking prior-2 highs, stop=extreme_low-0.02,
         target = VWAP@entry).
  accel gate: extreme-bar range >= ACCEL x median range so far. 2/day cap per side.

OUTPUT: n events / win% / avg+med R / totR / EV-per-trade, broken out BY EXTENSION
BUCKET (1-2 / 2-3 / >=3 %) and BY SNAPBACK SPEED — so we pick the ext floor + window
that earns edge BEFORE rewiring the live _check_vwap_fade detector (or prove no edge).

NOTHING IS WRITTEN. ib_historical_data + live_alerts read-only.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v340_vwap_fade_replay.py \
     --days 14 --ext 1.0 --universe 300 --maxhold 30 --side both
"""
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


def _vwaps(bars):
    """Cumulative intraday VWAP series (one value per bar, using typical price)."""
    out = []
    cum_pv = cum_v = 0.0
    for b in bars:
        h, l, c, v = b.get("high"), b.get("low"), b.get("close"), b.get("volume") or 0
        tp = ((h + l + c) / 3.0) if (h and l and c) else (c or 0.0)
        cum_pv += tp * v
        cum_v += v
        out.append((cum_pv / cum_v) if cum_v > 0 else (c or tp))
    return out


def _detect(bars, vwap, ext_pct, side):
    """Detect vwap-fade snapback events for one side. Returns list of event dicts."""
    if len(bars) < 5:
        return []
    ranges = []
    events = []
    # extreme tracking
    ext_idx = None
    ext_px = None  # extreme high (short) or extreme low (long)
    armed = False
    for i, b in enumerate(bars):
        h, l, c, o = b.get("high"), b.get("low"), b.get("close"), b.get("open")
        rng = (h - l) if (h and l) else 0.0
        vw = vwap[i] if vwap[i] else None
        if vw and vw > 0:
            if side == "short":
                stretch = (h - vw) / vw * 100.0 if h else 0.0
                if stretch >= ext_pct and (ext_px is None or h > ext_px):
                    ext_px, ext_idx = h, i
                    med_r = median(ranges) if ranges else 0.0
                    armed = (med_r <= 0) or (rng >= ACCEL * med_r)
            else:  # long
                stretch = (vw - l) / vw * 100.0 if l else 0.0
                if stretch >= ext_pct and (ext_px is None or l < ext_px):
                    ext_px, ext_idx = l, i
                    med_r = median(ranges) if ranges else 0.0
                    armed = (med_r <= 0) or (rng >= ACCEL * med_r)
        if armed and ext_idx is not None and i >= 2 and 0 < (i - ext_idx) <= TRIGGER_WINDOW:
            if side == "short":
                red = c < o
                breaks = l < min(bars[i - 1]["low"], bars[i - 2]["low"])
                if red and breaks:
                    ext_now = (ext_px - vwap[ext_idx]) / vwap[ext_idx] * 100.0 if vwap[ext_idx] else 0.0
                    events.append({"trigger_idx": i, "ext_px": ext_px, "ext_pct": round(ext_now, 2),
                                   "bars_from_ext": i - ext_idx})
                    armed = False; ext_idx = None; ext_px = None
                    if len(events) >= 2:
                        break
            else:
                green = c > o
                breaks = h > max(bars[i - 1]["high"], bars[i - 2]["high"])
                if green and breaks:
                    ext_now = (vwap[ext_idx] - ext_px) / vwap[ext_idx] * 100.0 if vwap[ext_idx] else 0.0
                    events.append({"trigger_idx": i, "ext_px": ext_px, "ext_pct": round(ext_now, 2),
                                   "bars_from_ext": i - ext_idx})
                    armed = False; ext_idx = None; ext_px = None
                    if len(events) >= 2:
                        break
        ranges.append(rng)
    return events


def _simulate(bars, vwap, ev, side, maxhold):
    i = ev["trigger_idx"]
    if i < 2 or i + 1 >= len(bars):
        return None
    if side == "short":
        entry = min(bars[i - 1]["low"], bars[i - 2]["low"])
        stop = ev["ext_px"] + 0.02
        risk = stop - entry
        if risk <= 0:
            return None
        target = vwap[i] if (vwap[i] and vwap[i] < entry) else (entry - risk)
        r_target = (entry - target) / risk
        end = min(i + 1 + maxhold, len(bars))
        for j in range(i + 1, end):
            if bars[j]["high"] >= stop:
                return -1.0
            if bars[j]["low"] <= target:
                return round(r_target, 3)
        return round((entry - bars[end - 1]["close"]) / risk, 3)
    else:
        entry = max(bars[i - 1]["high"], bars[i - 2]["high"])
        stop = ev["ext_px"] - 0.02
        risk = entry - stop
        if risk <= 0:
            return None
        target = vwap[i] if (vwap[i] and vwap[i] > entry) else (entry + risk)
        r_target = (target - entry) / risk
        end = min(i + 1 + maxhold, len(bars))
        for j in range(i + 1, end):
            if bars[j]["low"] <= stop:
                return -1.0
            if bars[j]["high"] >= target:
                return round(r_target, 3)
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


def _run_side(db, syms, side, start, start_utc, ext_pct, maxhold):
    all_r, by_bucket, by_window, ext_dist = [], defaultdict(list), defaultdict(list), []
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
            vwap = _vwaps(bars)
            evs = _detect(bars, vwap, ext_pct, side)
            if evs:
                days_with_event += 1
            for ev in evs:
                n_events += 1
                ext_dist.append(ev["ext_pct"])
                r = _simulate(bars, vwap, ev, side, maxhold)
                if r is None:
                    continue
                n_tradeable += 1
                all_r.append(r)
                by_bucket[_bucket(ev["ext_pct"])].append(r)
                by_window[ev["bars_from_ext"]].append(r)

    print("=" * 72)
    print(f"{side.upper()}  EVENTS: {n_events} ({days_with_event} symbol-days), {n_tradeable} tradeable")
    if ext_dist:
        sd = sorted(ext_dist)
        print(f"  extension-from-VWAP dist: p25={sd[len(sd)//4]:.1f}%  "
              f"p50={sd[len(sd)//2]:.1f}%  p75={sd[3*len(sd)//4]:.1f}%  max={sd[-1]:.1f}%")
    _report("ALL", all_r)
    print("  BY EXTENSION BUCKET")
    for b in ("1-2%", "2-3%", ">=3%"):
        _report("   " + b, by_bucket.get(b, []))
    print("  BY SNAPBACK SPEED (bars from extreme→trigger)")
    for w in sorted(by_window):
        _report(f"   +{w}bar", by_window[w])
    print()


def main():
    days = _arg("--days", 14, int)
    ext_pct = _arg("--ext", 1.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    side = _arg("--side", "both", str)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v340 VWAP-FADE TRADE REPLAY — trailing {days}d  ext>={ext_pct:g}%  "
          f"univ<={uni_cap}  maxhold={maxhold}min  side={side} ===")
    print("  SHORT: entry=2-bar-break-down stop=extHigh+0.02 target=VWAP(1R floor)")
    print("  LONG : entry=2-bar-break-up  stop=extLow-0.02  target=VWAP(1R floor)\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1,
                                       "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} scanner-watched symbols\n")

    sides = ("short", "long") if side == "both" else (side,)
    for s in sides:
        _run_side(db, syms, s, start, start_utc, ext_pct, maxhold)

    print("=== READING ===")
    print("• vwap_fade_SHORT = shorting strength (extended above VWAP). If SHORT avgR <=0")
    print("  across buckets → confirms the v336/off_sides 'no edge shorting strength' lesson →")
    print("  keep it suppressed / do NOT rewire the short side.")
    print("• Pick the lowest ext bucket whose avgR is comfortably >0 → that's the FIRE floor")
    print("  for the side(s) that earn edge. Faster snapbacks (+1..+4) usually carry the edge.")
    print("• Compare to rubber_band baselines (v329 long +0.27R, v330 short +0.59R). vwap_fade")
    print("  anchored to VWAP may differ — the VWAP target is tighter than the 9EMA/open anchor.\n")


if __name__ == "__main__":
    main()
