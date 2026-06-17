#!/usr/bin/env python3
"""
v351 — BREAKOUT / CONTINUATION REPLAY (LONG-only) — the MOMENTUM-sweep template (READ-ONLY).

PHASE B #1. First momentum/continuation setup. The live _check_breakout (enhanced_scanner
L4714) fires when price is just ABOVE resistance (0..-1.5%) with RVOL>=1.8, stop=resistance-
ATR, target=price+2*ATR — a continuation bet on FOLLOW-THROUGH (opposite of the FADE snapback
mechanics). This template measures that follow-through edge with proper risk control:

  Build a rolling LOOKBACK consolidation: R = max high over [i-LOOKBACK, i-1] (resistance),
  base_low = min low over the same window. A BREAKOUT bar i prints when high_i clears
  R*(1+BRK_MARGIN%) AND close_i > R AND the bar is accel(1.3x median range). entry = R (the
  pivot, stop-buy fill), stop = base_low - 0.02 (below the consolidation), 1.0% min-risk floor,
  2/day. To separate "does it follow through?" from "is the target right?", THREE targets are
  measured side-by-side:
     MM  = entry + (R - base_low)   [measured move = consolidation height projected up]
     2R  = entry + 2*risk
     3R  = entry + 3*risk
  Also reports the 1R-follow-through rate (fraction that reach +1R before stop) and buckets by
  base tightness (tight bases tend to break cleaner). R winsorized to ±cap.

NOTHING IS WRITTEN. Reusable for hod_breakout / range_break / opening_drive by swapping the
resistance definition.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v351_breakout_replay.py \
     --days 14 --lookback 15 --brkmargin 0.05 --universe 300 --maxhold 30 \
     --minriskpct 1.0 --winsor 3.0
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


def _bucket(h):
    if h < 0.75:
        return "tight<0.75%"
    if h < 1.5:
        return "med0.75-1.5%"
    return "wide>=1.5%"


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<18} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<18} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}")


def _sim_long(bars, i, entry, stop, tgt, maxhold):
    risk = entry - stop
    if risk <= 0:
        return None
    rt = (tgt - entry) / risk
    end = min(i + 1 + maxhold, len(bars))
    for j in range(i + 1, end):
        if bars[j]["low"] <= stop:
            return -1.0
        if bars[j]["high"] >= tgt:
            return round(rt, 3)
    lc = bars[end - 1]["close"]
    return round((lc - entry) / risk, 3)


def main():
    days = _arg("--days", 14, int)
    lookback = _arg("--lookback", 15, int)
    brkmargin = _arg("--brkmargin", 0.05, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    minriskpct = _arg("--minriskpct", 1.0, float)
    cap = _arg("--winsor", 3.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v351 BREAKOUT/CONTINUATION REPLAY (LONG) — {days}d  lookback={lookback}  "
          f"brkmargin={brkmargin:g}%  minrisk>={minriskpct:g}%  winsor=±{cap:g}R ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    by_tgt = {"MM": [], "2R": [], "3R": []}
    by_bucket = defaultdict(list)        # bucket -> R (using 2R target)
    n_ev = n_tr = n_gated = 0
    ft_1r = 0  # follow-through: reached +1R before stop (using 2R sim path)

    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": "1 min", "date": {"$gte": start_utc.isoformat()}},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
        by_day = defaultdict(list)
        for b in cur:
            et = _to_et(b.get("date"))
            if _is_rth(et):
                by_day[et.strftime("%Y-%m-%d")].append(b)
        for d, bars in by_day.items():
            if len(bars) < lookback + 5:
                continue
            bars.sort(key=lambda x: x["date"])
            fired = 0
            i = lookback
            while i < len(bars):
                if fired >= 2:
                    break
                window = bars[i - lookback:i]
                R = max(b["high"] for b in window)
                base_low = min(b["low"] for b in window)
                h, l, c, o = bars[i]["high"], bars[i]["low"], bars[i]["close"], bars[i]["open"]
                rng = h - l
                med_r = median([(b["high"] - b["low"]) for b in window]) if window else 0.0
                accel_ok = (med_r <= 0) or (rng >= ACCEL * med_r)
                if h > R * (1 + brkmargin / 100.0) and c > R and accel_ok:
                    n_ev += 1
                    entry = round(R, 2)
                    stop = round(base_low - 0.02, 2)
                    risk = entry - stop
                    if risk <= 0 or entry <= 0 or risk / entry * 100.0 < minriskpct:
                        n_gated += 1; i += 1; continue
                    n_tr += 1; fired += 1
                    base_h = (R - base_low) / entry * 100.0
                    tgts = {"MM": entry + (R - base_low), "2R": entry + 2 * risk, "3R": entry + 3 * risk}
                    for name, tg in tgts.items():
                        r = _sim_long(bars, i, entry, stop, tg, maxhold)
                        if r is not None:
                            by_tgt[name].append(r)
                    r2 = _sim_long(bars, i, entry, stop, entry + 2 * risk, maxhold)
                    if r2 is not None:
                        by_bucket[_bucket(base_h)].append(r2)
                    r1 = _sim_long(bars, i, entry, stop, entry + risk, maxhold)
                    if r1 is not None and r1 > 0:
                        ft_1r += 1
                    i += lookback   # skip ahead to avoid re-firing the same breakout
                    continue
                i += 1

    ft_rate = (100.0 * ft_1r / n_tr) if n_tr else 0.0
    print(f"events={n_ev}  tradeable={n_tr}  gated<{minriskpct:g}%risk={n_gated}  1R-follow-through={ft_rate:.0f}%\n")
    for name in ("MM", "2R", "3R"):
        print("=" * 80)
        print(f"TARGET = {name}")
        _report("ALL", by_tgt[name], cap)
        print()
    print("=" * 80)
    print("BASE TIGHTNESS (target=2R)")
    for b in ("tight<0.75%", "med0.75-1.5%", "wide>=1.5%"):
        _report("  " + b, by_bucket.get(b, []), cap)
    print()
    print("=== READING ===")
    print("• High 1R-follow-through + a target with winsorAvg & medR >0 = real continuation edge.")
    print("• tight-base bucket usually breaks cleanest -> if only tight is +EV, gate breakout on base tightness.")
    print("• if all targets neg / low follow-through -> breakouts in this universe are mostly traps -> tighten or SUPPRESS.")
    print("• live uses stop=resistance-ATR & target=price+2*ATR; compare 2R column as the closest analog.\n")


if __name__ == "__main__":
    main()
