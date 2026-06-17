#!/usr/bin/env python3
"""
v342c — gap_fade vs vwap_fade OVERLAP probe (READ-ONLY) — settles rewrite-vs-suppress.

v342b proved a gap-gated snapback+VWAP gap_fade is +EV (SHORT +0.17R, LONG +0.18R).
But the LIVE vwap_fade (v341) already fires the same snapback-to-VWAP on any >=1%
extension-from-VWAP flush. If gap_fade's triggers mostly ALSO clear vwap_fade's 1%
extension gate, gap_fade is REDUNDANT (double-fire / correlated risk) -> suppress.
If a meaningful share are LOW-VWAP-extension (<1%) gap reversals vwap_fade MISSES,
gap_fade adds UNIQUE edge -> rewrite.

For each gap-day snapback trigger this records ext-from-VWAP at the entry bar and the
realized R, split into UNIQUE (<1% ext, vwap_fade misses) vs OVERLAP (>=1% ext, vwap_fade
also fires). Decision = is the UNIQUE bucket both sizeable AND +EV?

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v342c_overlap.py \
     --days 21 --gapmin 2.0 --universe 300 --maxhold 60 --minriskpct 0.5 --winsor 3.0 --warmup 3 --vwapgate 1.0
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


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<24} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<24} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}")


def main():
    days = _arg("--days", 21, int)
    gapmin = _arg("--gapmin", 2.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 60, int)
    minriskpct = _arg("--minriskpct", 0.5, float)
    cap = _arg("--winsor", 3.0, float)
    warmup = _arg("--warmup", 3, int)
    vwapgate = _arg("--vwapgate", 1.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    look_utc = (start - timedelta(days=6)).astimezone(timezone.utc)

    print(f"\n=== v342c gap_fade vs vwap_fade OVERLAP — {days}d  |gap|>={gapmin:g}%  "
          f"vwap_gate={vwapgate:g}% ===")
    print("  UNIQUE = ext-from-VWAP < gate (vwap_fade MISSES) | OVERLAP = >= gate (vwap_fade also fires)\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]

    buckets = defaultdict(list)   # (dir, UNIQUE/OVERLAP) -> [R]
    ext_dist = []

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
            rh.append(hi - lo)
            if prior_close <= 0 or d < start.strftime("%Y-%m-%d"):
                continue
            gap = (o - prior_close) / prior_close * 100.0
            if abs(gap) < gapmin:
                continue
            bars = sorted(by_day[d], key=lambda x: x["date"])
            vwap = _vwaps(bars)
            direction = "short" if gap > 0 else "long"
            run_hi = run_lo = None
            ext_idx = None
            ranges = []
            for t in range(len(bars)):
                h, l, c, op = bars[t]["high"], bars[t]["low"], bars[t]["close"], bars[t]["open"]
                if run_hi is None or h > run_hi:
                    run_hi = h
                    if direction == "short":
                        ext_idx = t
                if run_lo is None or l < run_lo:
                    run_lo = l
                    if direction == "long":
                        ext_idx = t
                if t < warmup or t < 2:
                    ranges.append(h - l); continue
                med_r = median(ranges) if ranges else 0.0
                hit = None
                if direction == "short":
                    accel = (med_r <= 0) or ((bars[ext_idx]["high"] - bars[ext_idx]["low"]) >= ACCEL * med_r)
                    if c < op and l < min(bars[t - 1]["low"], bars[t - 2]["low"]) and accel and 1 <= (t - ext_idx) <= TRIGGER_WIN:
                        entry = min(bars[t - 1]["low"], bars[t - 2]["low"]); stop = run_hi + 0.02; hit = t
                else:
                    accel = (med_r <= 0) or ((bars[ext_idx]["high"] - bars[ext_idx]["low"]) >= ACCEL * med_r)
                    if c > op and h > max(bars[t - 1]["high"], bars[t - 2]["high"]) and accel and 1 <= (t - ext_idx) <= TRIGGER_WIN:
                        entry = max(bars[t - 1]["high"], bars[t - 2]["high"]); stop = run_lo - 0.02; hit = t
                ranges.append(h - l)
                if hit is None:
                    continue
                target = vwap[hit]
                risk = (stop - entry) if direction == "short" else (entry - stop)
                if risk <= 0 or entry <= 0 or risk / entry * 100.0 < minriskpct:
                    break
                if (direction == "short" and target >= entry) or (direction == "long" and target <= entry):
                    break
                ext_from_vwap = abs(entry - vwap[hit]) / vwap[hit] * 100.0
                ext_dist.append(ext_from_vwap)
                r_target = abs(entry - target) / risk
                r = None
                end = min(hit + 1 + maxhold, len(bars))
                for j in range(hit + 1, end):
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
                tag = "UNIQUE(<gate)" if ext_from_vwap < vwapgate else "OVERLAP(>=gate)"
                buckets[(direction, tag)].append(round(r, 3))
                break  # one trade/day

    if ext_dist:
        sd = sorted(ext_dist)
        n = len(sd)
        unique = sum(1 for e in ext_dist if e < vwapgate)
        print(f"ext-from-VWAP at entry: p25={sd[n//4]:.2f}% p50={sd[n//2]:.2f}% p75={sd[3*n//4]:.2f}%")
        print(f"UNIQUE (ext<{vwapgate:g}%, vwap_fade MISSES): {unique}/{n} = {100.0*unique/n:.0f}%\n")
    for d in ("short", "long"):
        print(f"{d.upper()}")
        _report("  UNIQUE (vwap_fade miss)", buckets.get((d, "UNIQUE(<gate)"), []), cap)
        _report("  OVERLAP (vwap_fade dup)", buckets.get((d, "OVERLAP(>=gate)"), []), cap)
        print()
    print("=== DECISION ===")
    print("• UNIQUE share LARGE and +EV → gap_fade adds real edge vwap_fade misses → REWRITE (gap-gated).")
    print("• UNIQUE share SMALL or ~0 / negative → gap_fade is mostly a vwap_fade DUPLICATE → SUPPRESS")
    print("  gap_fade (remove from _enabled_setups); vwap_fade already covers gap-day snapbacks.\n")


if __name__ == "__main__":
    main()
