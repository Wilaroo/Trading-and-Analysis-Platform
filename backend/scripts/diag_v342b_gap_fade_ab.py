#!/usr/bin/env python3
"""
v342b — GAP-FADE A/B: trigger {vwapcross|snapback} x target {prevclose|vwap}  (READ-ONLY)

v342 proved the LIVE gap_fade (vwapcross trigger + full prior-close fill target) is
NEGATIVE-EV across all cells (n=1080). This A/B tests whether the v341-proven mechanics
rescue it: a 1-min double-bar-break SNAPBACK after the gap extreme + a CLOSER VWAP target.

  --trigger vwapcross : first bar closing through VWAP after warmup (the live logic)
  --trigger snapback  : red breaks prior-2 lows (short) / green clears prior-2 highs (long)
                        within +1..+4 bars of the post-gap HOD/LOD extreme (v341 mechanics)
  --target  prevclose : prior session close (full gap fill, the live target)
  --target  vwap      : session VWAP at entry (closer mean-revert target)

Still gap-gated (|gap|>=gapmin), one trade/symbol-day, prior_close + ATR from 1-min OHLC,
min-risk gate + winsor. Reports by (direction, gap-bucket).

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v342b_gap_fade_ab.py \
     --days 21 --gapmin 2.0 --universe 300 --maxhold 60 --minriskpct 0.5 --winsor 3.0 \
     --warmup 3 --trigger snapback --target vwap
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
TRIGGER_WIN = 4
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
    out = []
    cum_pv = cum_v = 0.0
    for b in bars:
        h, l, c, v = b.get("high"), b.get("low"), b.get("close"), b.get("volume") or 0
        tp = ((h + l + c) / 3.0) if (h and l and c) else (c or 0.0)
        cum_pv += tp * v
        cum_v += v
        out.append((cum_pv / cum_v) if cum_v > 0 else (c or tp))
    return out


def _bucket(g):
    g = abs(g)
    return "2-3%" if g < 3.0 else "3-5%" if g < 5.0 else ">=5%"


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<14} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<14} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"rawAvg={mean(rs):+.3f}  winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  "
          f"totWinsorR={sum(wr):+.1f}")


def _find_trigger(bars, vwap, direction, warmup, atr, prior_close):
    """Return (entry, stop, trig_t) or None for the chosen trigger mode."""
    mode = _arg("--trigger", "snapback", str)
    run_hi = run_lo = None
    ext_idx = None  # HOD idx (short) / LOD idx (long)
    ranges = []
    for t in range(len(bars)):
        h, l, c, o = bars[t]["high"], bars[t]["low"], bars[t]["close"], bars[t]["open"]
        if run_hi is None or h > run_hi:
            run_hi = h
            if direction == "short":
                ext_idx = t
        if run_lo is None or l < run_lo:
            run_lo = l
            if direction == "long":
                ext_idx = t
        if t < warmup or t < 2:
            ranges.append(h - l)
            continue
        if mode == "vwapcross":
            if direction == "short" and c < vwap[t]:
                return (c, run_hi + 0.3 * atr, t)
            if direction == "long" and c > vwap[t]:
                return (c, run_lo - 0.3 * atr, t)
        else:  # snapback
            med_r = median(ranges) if ranges else 0.0
            if direction == "short":
                accel = (med_r <= 0) or ((bars[ext_idx]["high"] - bars[ext_idx]["low"]) >= ACCEL * med_r)
                red = c < o
                breaks = l < min(bars[t - 1]["low"], bars[t - 2]["low"])
                if red and breaks and accel and 1 <= (t - ext_idx) <= TRIGGER_WIN:
                    entry = min(bars[t - 1]["low"], bars[t - 2]["low"])
                    return (entry, run_hi + 0.02, t)
            else:
                accel = (med_r <= 0) or ((bars[ext_idx]["high"] - bars[ext_idx]["low"]) >= ACCEL * med_r)
                green = c > o
                clears = h > max(bars[t - 1]["high"], bars[t - 2]["high"])
                if green and clears and accel and 1 <= (t - ext_idx) <= TRIGGER_WIN:
                    entry = max(bars[t - 1]["high"], bars[t - 2]["high"])
                    return (entry, run_lo - 0.02, t)
        ranges.append(h - l)
    return None


def main():
    days = _arg("--days", 21, int)
    gapmin = _arg("--gapmin", 2.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 60, int)
    minriskpct = _arg("--minriskpct", 0.5, float)
    cap = _arg("--winsor", 3.0, float)
    warmup = _arg("--warmup", 3, int)
    trig = _arg("--trigger", "snapback", str)
    tgt = _arg("--target", "vwap", str)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    look_utc = (start - timedelta(days=6)).astimezone(timezone.utc)

    print(f"\n=== v342b GAP-FADE A/B — {days}d  |gap|>={gapmin:g}%  trigger={trig}  target={tgt}  "
          f"minrisk>={minriskpct:g}%  winsor=±{cap:g}R ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    by_dir = {"short": [], "long": []}
    by_bucket = defaultdict(list)
    n_gaps = n_trig = n_gated = 0

    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": "1 min", "date": {"$gte": look_utc.isoformat()}},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
        by_day = defaultdict(list)
        for b in cur:
            et = _to_et(b.get("date"))
            if _is_rth(et):
                by_day[et.strftime("%Y-%m-%d")].append(b)
        if len(by_day) < 2:
            continue
        ds = sorted(by_day)
        ohlc = {}
        for d in ds:
            bs = sorted(by_day[d], key=lambda x: x["date"])
            ohlc[d] = (bs[0]["open"], max(x["high"] for x in bs), min(x["low"] for x in bs), bs[-1]["close"])
        rh = []
        for k, d in enumerate(ds):
            o, hi, lo, cl = ohlc[d]
            if k == 0:
                rh.append(hi - lo); continue
            prior_close = ohlc[ds[k - 1]][3]
            atr = median(rh[-10:]) if rh else (hi - lo)
            rh.append(hi - lo)
            if prior_close <= 0 or d < start.strftime("%Y-%m-%d"):
                continue
            gap = (o - prior_close) / prior_close * 100.0
            if abs(gap) < gapmin:
                continue
            n_gaps += 1
            bars = sorted(by_day[d], key=lambda x: x["date"])
            vwap = _vwaps(bars)
            direction = "short" if gap > 0 else "long"
            res = _find_trigger(bars, vwap, direction, warmup, atr, prior_close)
            if not res:
                continue
            entry, stop, trig_t = res
            if entry <= 0:
                continue
            target = prior_close if tgt == "prevclose" else vwap[trig_t]
            risk = (stop - entry) if direction == "short" else (entry - stop)
            if risk <= 0 or risk / entry * 100.0 < minriskpct:
                n_gated += 1; continue
            if direction == "short" and target >= entry:
                continue
            if direction == "long" and target <= entry:
                continue
            n_trig += 1
            r_target = abs(entry - target) / risk
            r = None
            end = min(trig_t + 1 + maxhold, len(bars))
            for j in range(trig_t + 1, end):
                if direction == "short":
                    if bars[j]["high"] >= stop:
                        r = -1.0; break
                    if bars[j]["low"] <= target:
                        r = r_target; break
                else:
                    if bars[j]["low"] <= stop:
                        r = -1.0; break
                    if bars[j]["high"] >= target:
                        r = r_target; break
            if r is None:
                lc = bars[end - 1]["close"]
                r = ((entry - lc) if direction == "short" else (lc - entry)) / risk
            r = round(r, 3)
            by_dir[direction].append(r)
            by_bucket[(direction, _bucket(gap))].append(r)

    print(f"gap-days={n_gaps}  triggered={n_trig}  gated={n_gated}\n")
    for d in ("short", "long"):
        print("=" * 78)
        print(f"{d.upper()}  ({'gap-up' if d=='short' else 'gap-down'}, trigger={trig}, target={tgt})")
        _report("ALL", by_dir[d], cap)
        for b in ("2-3%", "3-5%", ">=5%"):
            _report("  gap " + b, by_bucket.get((d, b), []), cap)
        print()
    print("=== READING ===")
    print("• snapback+vwap POSITIVE (winsorAvg & medR >0) → rewrite gap_fade with v341 mechanics,")
    print("  gap-gated. If it just matches vwap_fade's edge → gap_fade is REDUNDANT → suppress and")
    print("  let vwap_fade cover gap-day flushes. If still <=0 → gap-fill has no edge → SUPPRESS gap_fade.\n")


if __name__ == "__main__":
    main()
