#!/usr/bin/env python3
"""
v345 — MEAN_REVERSION (EMA20-anchored) REPLAY + vwap_fade overlap, in one run (READ-ONLY).

FADE SWEEP #3 (mean_reversion 2680 fires / 73 genuine). The live _check_mean_reversion
(enhanced_scanner L5584) is a STATE detector: RSI extreme + dist_from_ema20 >3% + near
S/R, target = 20-EMA — no snapback trigger, no cap. This replay applies the proven v341
mechanics anchored to a 1-min EMA20 mean:
  SHORT: extended ABOVE EMA20 -> red double-bar-break after HOD within +1..+4 -> fade to EMA20
  LONG : extended BELOW EMA20 -> green clears prior-2 highs after LOD -> snapback to EMA20
entry=2-bar-break, stop=extreme±0.02, target=EMA20(1R floor), accel1.3x, 2/day, min-risk gate, winsor.

Because mean_reversion may overlap the now-live vwap_fade (also a mean snapback), each trade
is ALSO tagged UNIQUE (ext-from-VWAP<1%, vwap_fade misses) vs OVERLAP (>=1%, vwap_fade dup) —
settles edge AND redundancy in a single run.

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v345_mean_reversion_replay.py \
     --days 14 --ext 3.0 --universe 300 --maxhold 30 --side both --minriskpct 1.0 --winsor 3.0 --vwapgate 1.0
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
EMA_LEN = 20


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


def _ema(bars, n):
    out = []
    k = 2.0 / (n + 1)
    e = None
    for b in bars:
        c = b.get("close")
        if c is None:
            out.append(e if e is not None else 0.0); continue
        e = c if e is None else (c * k + e * (1 - k))
        out.append(e)
    return out


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


def _bucket(e):
    if e < 2.0:
        return "1-2%"
    if e < 3.0:
        return "2-3%"
    if e < 4.0:
        return "3-4%"
    return ">=4%"


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<16} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<16} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}")


def main():
    days = _arg("--days", 14, int)
    ext_pct = _arg("--ext", 3.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    side = _arg("--side", "both", str)
    minriskpct = _arg("--minriskpct", 1.0, float)
    cap = _arg("--winsor", 3.0, float)
    vwapgate = _arg("--vwapgate", 1.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v345 MEAN_REVERSION (EMA20) REPLAY — {days}d  ext>={ext_pct:g}%  minrisk>={minriskpct:g}%  "
          f"winsor=±{cap:g}R  side={side}  vwap_gate={vwapgate:g}% ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    by_dir = {"short": [], "long": []}
    by_bucket = defaultdict(list)
    overlap = defaultdict(list)   # (dir, UNIQUE/OVERLAP) -> R
    n_ev = n_tr = n_gated = 0

    sides = ("short", "long") if side == "both" else (side,)

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
            if len(bars) < EMA_LEN + 5:
                continue
            bars.sort(key=lambda x: x["date"])
            ema = _ema(bars, EMA_LEN)
            vwap = _vwaps(bars)
            for direction in sides:
                ranges = []
                ext_idx = ext_px = None
                armed = False
                fired = 0
                for i, b in enumerate(bars):
                    h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                    m = ema[i] if i >= EMA_LEN else None  # warmup
                    rng = h - l
                    if m and m > 0:
                        if direction == "short":
                            st = (h - m) / m * 100.0
                            if st >= ext_pct and (ext_px is None or h > ext_px):
                                ext_px, ext_idx = h, i
                                mr = median(ranges) if ranges else 0.0
                                armed = (mr <= 0) or (rng >= ACCEL * mr)
                        else:
                            st = (m - l) / m * 100.0
                            if st >= ext_pct and (ext_px is None or l < ext_px):
                                ext_px, ext_idx = l, i
                                mr = median(ranges) if ranges else 0.0
                                armed = (mr <= 0) or (rng >= ACCEL * mr)
                    if armed and ext_idx is not None and i >= 2 and 0 < (i - ext_idx) <= TRIGGER_WIN and fired < 2:
                        trig = False
                        if direction == "short" and c < o and l < min(bars[i - 1]["low"], bars[i - 2]["low"]):
                            entry = min(bars[i - 1]["low"], bars[i - 2]["low"]); stop = ext_px + 0.02; trig = True
                        elif direction == "long" and c > o and h > max(bars[i - 1]["high"], bars[i - 2]["high"]):
                            entry = max(bars[i - 1]["high"], bars[i - 2]["high"]); stop = ext_px - 0.02; trig = True
                        if trig:
                            n_ev += 1
                            armed = False; sidx = ext_idx; ext_idx = ext_px = None
                            tgt = ema[i]
                            risk = (stop - entry) if direction == "short" else (entry - stop)
                            ext_now = abs(entry - ema[sidx]) / ema[sidx] * 100.0 if ema[sidx] else 0.0
                            if risk <= 0 or entry <= 0 or risk / entry * 100.0 < minriskpct:
                                n_gated += 1; ranges.append(rng); continue
                            if (direction == "short" and tgt >= entry) or (direction == "long" and tgt <= entry):
                                ranges.append(rng); continue
                            n_tr += 1; fired += 1
                            rt = abs(entry - tgt) / risk
                            r = None
                            end = min(i + 1 + maxhold, len(bars))
                            for j in range(i + 1, end):
                                if direction == "short":
                                    if bars[j]["high"] >= stop:
                                        r = -1.0; break
                                    if bars[j]["low"] <= tgt:
                                        r = rt; break
                                else:
                                    if bars[j]["low"] <= stop:
                                        r = -1.0; break
                                    if bars[j]["high"] >= tgt:
                                        r = rt; break
                            if r is None:
                                lc = bars[end - 1]["close"]
                                r = ((entry - lc) if direction == "short" else (lc - entry)) / risk
                            r = round(r, 3)
                            by_dir[direction].append(r)
                            by_bucket[(direction, _bucket(ext_now))].append(r)
                            ev = abs(entry - vwap[i]) / vwap[i] * 100.0 if vwap[i] else 99.0
                            overlap[(direction, "UNIQUE" if ev < vwapgate else "OVERLAP")].append(r)
                    ranges.append(rng)

    print(f"events={n_ev}  tradeable={n_tr}  gated<{minriskpct:g}%risk={n_gated}\n")
    for d in sides:
        print("=" * 78)
        print(f"{d.upper()}  (extension-from-EMA20)")
        _report("ALL", by_dir[d], cap)
        for b in ("1-2%", "2-3%", "3-4%", ">=4%"):
            _report("  ext " + b, by_bucket.get((d, b), []), cap)
        _report("  UNIQUE vs vwap", overlap.get((d, "UNIQUE"), []), cap)
        _report("  OVERLAP w/ vwap", overlap.get((d, "OVERLAP"), []), cap)
        print()
    print("=== READING ===")
    print("• ext buckets where winsorAvg & medR >0 = real EMA20-snapback edge -> FIRE floor.")
    print("• UNIQUE (vwap_fade miss) sizeable & +EV -> mean_reversion adds edge -> REWRITE (EMA20 anchor).")
    print("• UNIQUE small/neg & OVERLAP dominates -> mostly a vwap_fade duplicate -> SUPPRESS mean_reversion.")
    print("• note live detector gates ext at 3% (dist_from_ema20>3) -> compare 3-4/>=4 vs 1-3 buckets.\n")


if __name__ == "__main__":
    main()
