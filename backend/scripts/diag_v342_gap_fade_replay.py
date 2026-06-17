#!/usr/bin/env python3
"""
v342 — GAP-FADE TRADE-OUTCOME REPLAY (READ-ONLY, native 1-min bars)

FADE SWEEP #2 (gap_fade 3627 fires / 154 genuine in 30d). Validates the LIVE
_check_gap_fade thesis (enhanced_scanner L5751): |gap|>=2% on RVOL, then
  • gap-UP that FAILS (trades below VWAP)  -> SHORT the fill back to prior close
  • gap-DOWN that RECOVERS (trades above VWAP) -> LONG the fill back to prior close
target = prior session close (the gap fill); stop = HOD/LOD ± 0.3*ATR.

Everything is derived from native 1-min RTH bars (prior_close = prior RTH day's last
1-min close; ATR proxy = median of prior ~10 days' RTH high-low range). One trade per
symbol-day (the first failing/recovering VWAP cross after a short warmup). Reports
rawAvg / winsorAvg / medR / win% by GAP-SIZE bucket (2-3 / 3-5 / >=5 %) and direction,
with the v340b risk discipline (min-risk gate + winsor) so the edge is trustworthy.

NOTHING IS WRITTEN. ib_historical_data + live_alerts read-only.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v342_gap_fade_replay.py \
     --days 21 --gapmin 2.0 --universe 300 --maxhold 60 --minriskpct 0.5 --winsor 3.0 --warmup 3
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
    if g < 3.0:
        return "2-3%"
    if g < 5.0:
        return "3-5%"
    return ">=5%"


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<14} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<14} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"rawAvg={mean(rs):+.3f}  winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  "
          f"totWinsorR={sum(wr):+.1f}")


def main():
    days = _arg("--days", 21, int)
    gapmin = _arg("--gapmin", 2.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 60, int)
    minriskpct = _arg("--minriskpct", 0.5, float)
    cap = _arg("--winsor", 3.0, float)
    warmup = _arg("--warmup", 3, int)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v342 GAP-FADE REPLAY — {days}d  |gap|>={gapmin:g}%  univ<={uni_cap}  "
          f"maxhold={maxhold}m  minrisk>={minriskpct:g}%  winsor=±{cap:g}R ===")
    print("  gap-UP fails(below VWAP)->SHORT to prior close | gap-DOWN recovers(above VWAP)->LONG to prior close\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} scanner-watched symbols\n")

    by_dir = {"short": [], "long": []}
    by_bucket = defaultdict(list)
    n_gaps = n_trig = n_gated = 0
    # also widen lookback so day-0 has a prior_close
    look_utc = (start - timedelta(days=6)).astimezone(timezone.utc)

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
        days_sorted = sorted(by_day)
        # per-day OHLC
        ohlc = {}
        for d in days_sorted:
            bs = sorted(by_day[d], key=lambda x: x["date"])
            ohlc[d] = (bs[0]["open"], max(x["high"] for x in bs),
                       min(x["low"] for x in bs), bs[-1]["close"])
        ranges_hist = []
        for k, d in enumerate(days_sorted):
            o, hi, lo, cl = ohlc[d]
            if k == 0:
                ranges_hist.append(hi - lo)
                continue
            prior_close = ohlc[days_sorted[k - 1]][3]
            atr = median(ranges_hist[-10:]) if ranges_hist else (hi - lo)
            ranges_hist.append(hi - lo)
            if prior_close <= 0 or d < start.strftime("%Y-%m-%d"):
                continue
            gap = (o - prior_close) / prior_close * 100.0
            if abs(gap) < gapmin:
                continue
            n_gaps += 1
            bars = sorted(by_day[d], key=lambda x: x["date"])
            vwap = _vwaps(bars)
            run_hi = run_lo = None
            entry = stop = target = None
            direction = "short" if gap > 0 else "long"
            for t in range(len(bars)):
                run_hi = bars[t]["high"] if run_hi is None else max(run_hi, bars[t]["high"])
                run_lo = bars[t]["low"] if run_lo is None else min(run_lo, bars[t]["low"])
                if t < warmup:
                    continue
                c = bars[t]["close"]
                if direction == "short" and c < vwap[t]:           # gap-up failing
                    entry = c; stop = run_hi + 0.3 * atr; target = prior_close
                    trig_t = t; break
                if direction == "long" and c > vwap[t]:             # gap-down recovering
                    entry = c; stop = run_lo - 0.3 * atr; target = prior_close
                    trig_t = t; break
            if entry is None or entry <= 0:
                continue
            risk = (stop - entry) if direction == "short" else (entry - stop)
            if risk <= 0:
                continue
            if risk / entry * 100.0 < minriskpct:
                n_gated += 1
                continue
            # target must be on the profitable side (gap fill direction)
            if direction == "short" and target >= entry:
                continue
            if direction == "long" and target <= entry:
                continue
            n_trig += 1
            r_target = (abs(entry - target)) / risk
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
                last_c = bars[end - 1]["close"]
                r = ((entry - last_c) if direction == "short" else (last_c - entry)) / risk
            r = round(r, 3)
            by_dir[direction].append(r)
            by_bucket[(direction, _bucket(gap))].append(r)

    print(f"gap-days={n_gaps}  triggered={n_trig}  gated<{minriskpct:g}%risk={n_gated}\n")
    for d in ("short", "long"):
        print("=" * 78)
        print(f"{d.upper()}  ({'gap-up failing' if d=='short' else 'gap-down recovering'})")
        _report("ALL", by_dir[d], cap)
        for b in ("2-3%", "3-5%", ">=5%"):
            _report("  gap " + b, by_bucket.get((d, b), []), cap)
        print()

    print("=== READING ===")
    print("• winsorAvg AND medR both >0 in a (dir,gap) cell → real gap-fill edge there.")
    print("• Compare to the live detector's gates (|gap|>=2%, rvol>=1.3, target=prev_close).")
    print("• If only one direction / gap-band earns edge → that's the FIRE config to keep;")
    print("  prune the rest (or add a snapback trigger like v341 if the raw VWAP-cross is weak).\n")


if __name__ == "__main__":
    main()
