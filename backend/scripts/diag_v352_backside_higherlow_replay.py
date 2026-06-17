#!/usr/bin/env python3
"""
v352 — BACK$IDE (cheat-sheet-faithful) REPLAY (READ-ONLY).

Re-validates backside per the OFFICIAL SMB "Back$ide" cheat sheet, which the shipped v348
deviated from on the STOP and R:R:
   v348 stop  = .02 below the FLUSH/LOD  (deep)  -> R:R << 1
   cheat sheet= .02 below the MOST RECENT HIGHER LOW (tight) -> target ~1.4:1 R:R, 50-60% win
Cheat-sheet rules modeled here (LONG only):
   • rising phase after a distinct low: a HIGHER LOW exists (recent pullback low > session LOD)
     and a HIGHER HIGH prints (green 1-min double-bar-high break = "break of 1-min bar from
     consolidation, pay the offer on the break").
   • majority of trade ABOVE the 9-EMA (entry close > 9-EMA) and still BELOW VWAP (recovering).
   • range location "greater than halfway between LOD and VWAP" (entry > LOD + 0.5*(VWAP-LOD)).
   • STOP = most-recent-higher-low - 0.02 (TIGHT).  TARGET = VWAP (exit all).
   • one-and-done: 1 attempt/day/symbol.  Time window 10:00-13:30 ET (cheat-sheet ideal periods).
   • require R:R >= --minrr so we only take the doctrine-quality trades.
This run reports win%, winsorized avg R, median R, and the AVERAGE R:R taken, plus R:R buckets,
so we can confirm the cheat-sheet's ~1.4:1 / 50-60% profile before shipping v352.

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v352_backside_higherlow_replay.py \
     --days 14 --recentk 5 --minrr 1.0 --halfway 0.5 --universe 300 --maxhold 30 \
     --winsor 3.0 --timewin 1
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
EMA_LEN = 9


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


def _in_window(et):
    if et is None:
        return False
    m = et.hour * 60 + et.minute
    return (10 * 60) <= m <= (13 * 60 + 30)


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


def _rr_bucket(rr):
    if rr < 1.0:
        return "<1.0"
    if rr < 1.5:
        return "1.0-1.5"
    if rr < 2.5:
        return "1.5-2.5"
    return ">=2.5"


def _report(label, rs, cap):
    if not rs:
        print(f"  {label:<14} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<14} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}")


def main():
    days = _arg("--days", 14, int)
    recentk = _arg("--recentk", 5, int)
    minrr = _arg("--minrr", 1.0, float)
    halfway = _arg("--halfway", 0.5, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    cap = _arg("--winsor", 3.0, float)
    timewin = _arg("--timewin", 1, int)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v352 BACK$IDE cheat-sheet replay (tight higher-low stop) — {days}d  recentK={recentk}  "
          f"minRR={minrr:g}  halfway={halfway:g}  timewin={'10:00-13:30' if timewin else 'off'}  "
          f"winsor=±{cap:g}R ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    all_r = []
    rrs = []
    by_rr = defaultdict(list)
    n_ev = n_tr = 0

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
            if len(bars) < EMA_LEN + recentk + 3:
                continue
            bars.sort(key=lambda x: x["date"])
            ema = _ema(bars, EMA_LEN)
            vwap = _vwaps(bars)
            ranges = []
            lod = None
            fired = 0
            for i, b in enumerate(bars):
                h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                lod = l if lod is None else min(lod, l)
                if i < max(EMA_LEN, recentk) + 2 or fired >= 1:
                    ranges.append(h - l); continue
                vw = vwap[i]
                em = ema[i]
                med_r = median(ranges) if ranges else 0.0
                green = c > o
                clears_hi = h > max(bars[i - 1]["high"], bars[i - 2]["high"])
                entry = max(bars[i - 1]["high"], bars[i - 2]["high"])
                recent_low = min(bars[j]["low"] for j in range(i - recentk, i))
                accel_ok = (med_r <= 0) or ((h - l) >= ACCEL * med_r)
                if not (vw and vw > 0 and green and clears_hi and entry < vw and c > em
                        and recent_low > lod                       # higher low (rising structure)
                        and entry > lod + halfway * (vw - lod)      # recovered > halfway to VWAP
                        and accel_ok):
                    ranges.append(h - l); continue
                if timewin and not _in_window(_to_et(b.get("date"))):
                    ranges.append(h - l); continue
                stop = recent_low - 0.02
                risk = entry - stop
                n_ev += 1
                if risk <= 0 or entry <= 0:
                    ranges.append(h - l); continue
                rr = (vw - entry) / risk
                if rr < minrr:
                    ranges.append(h - l); continue
                n_tr += 1; fired += 1
                rrs.append(rr); by_rr_key = _rr_bucket(rr)
                r = None
                end = min(i + 1 + maxhold, len(bars))
                for j in range(i + 1, end):
                    if bars[j]["low"] <= stop:
                        r = -1.0; break
                    if bars[j]["high"] >= vw:
                        r = rr; break
                if r is None:
                    r = (bars[end - 1]["close"] - entry) / risk
                r = round(r, 3)
                all_r.append(r)
                by_rr[by_rr_key].append(r)
                ranges.append(h - l)

    avg_rr = mean(rrs) if rrs else 0.0
    print(f"events={n_ev}  tradeable(RR>={minrr:g})={n_tr}  avgRR_taken={avg_rr:.2f}\n")
    print("=" * 70)
    print("BACK$IDE  (tight higher-low stop -> VWAP)")
    _report("ALL", all_r, cap)
    for k in ("<1.0", "1.0-1.5", "1.5-2.5", ">=2.5"):
        _report("  RR " + k, by_rr.get(k, []), cap)
    print()
    print("=== READING ===")
    print("• Cheat sheet claims ~50-60% win & 1.4:1 R:R. If win% in that band AND winsorAvg/medR>0,")
    print("  the tight higher-low stop is doctrine-faithful + better R:R than v348's deep LOD stop -> ship v352.")
    print("• Compare avgRR_taken to ~1.4. If RR<1.0 bucket dominates & is negative, raise --minrr.")
    print("• v348 (live) anchors stop at the flush LOD -> larger risk, RR<1; v352 fixes that.\n")


if __name__ == "__main__":
    main()
