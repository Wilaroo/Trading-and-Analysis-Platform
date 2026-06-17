#!/usr/bin/env python3
"""
v349 — OFF_SIDES (range-top fade, SHORT-only) REPLAY + vwap_fade overlap (READ-ONLY).

FADE SWEEP #5 (off_sides, last loose FADE-family state-detector). The live _check_off_sides
(enhanced_scanner L5098) fires ONLY in RANGE_BOUND/FADE regime when:
    |dist_from_vwap| < 1.0%  AND  daily_range_pct > 1.5%  AND  within 1.0% of HOD
    -> SHORT, trigger=LOD, stop=HOD+buf, target = LOD - (HOD-LOD)  [a FULL range projected
       BELOW the LOD — very aggressive], RR=1.5. No trigger bar, no min-risk gate, no cap.

This replay applies the proven v341/v347 mechanics to the range-top fade: arm when price
returns within --hodprox of the session HOD in a wide (--minrange) session, then require a
RED 1-min double-bar-LOW-break (the rejection) within +1..+4 bars + accel(1.3x). entry=
2-bar-low-break, stop=HOD+0.02 (1.0% min-risk floor), 2/day, R winsorized. Because the live
target is unusually far, THREE targets are measured side-by-side to separate "is the SETUP
+EV?" from "is the live TARGET unrealistic?":
    LIVE = lod-(hod-lod)   |   LOD = session low   |   VWAP = session VWAP

Each trade is also tagged UNIQUE (|dist_vwap|<--vwapgate, vwap_fade-short misses) vs OVERLAP
(>=gate, vwap_fade-short territory) — settles edge AND redundancy in one run. The live gate
caps |dist_vwap|<1.0% so its real zone is the UNIQUE band; --vwapnear is relaxed here to
explore the full spectrum.

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v349_off_sides_replay.py \
     --days 14 --hodprox 1.0 --minrange 1.5 --vwapnear 5.0 --universe 300 --maxhold 30 \
     --minriskpct 1.0 --winsor 3.0 --vwapgate 1.0
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
        print(f"  {label:<18} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<18} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}")


def _simulate(bars, i, entry, stop, tgt, maxhold):
    """SHORT mark: stop above (high>=stop -> -1), target below (low<=tgt -> +rt), else MTC."""
    risk = stop - entry
    if risk <= 0:
        return None
    rt = (entry - tgt) / risk
    end = min(i + 1 + maxhold, len(bars))
    for j in range(i + 1, end):
        if bars[j]["high"] >= stop:
            return -1.0
        if bars[j]["low"] <= tgt:
            return round(rt, 3)
    lc = bars[end - 1]["close"]
    return round((entry - lc) / risk, 3)


def main():
    days = _arg("--days", 14, int)
    hodprox = _arg("--hodprox", 1.0, float)
    minrange = _arg("--minrange", 1.5, float)
    vwapnear = _arg("--vwapnear", 5.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    minriskpct = _arg("--minriskpct", 1.0, float)
    cap = _arg("--winsor", 3.0, float)
    vwapgate = _arg("--vwapgate", 1.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v349 OFF_SIDES (range-top fade, SHORT) REPLAY — {days}d  hodprox<={hodprox:g}%  "
          f"range>={minrange:g}%  vwapnear<={vwapnear:g}%  minrisk>={minriskpct:g}%  "
          f"winsor=±{cap:g}R  vwap_gate={vwapgate:g}% ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    by_tgt = {"LIVE": [], "LOD": [], "VWAP": []}
    overlap = defaultdict(lambda: defaultdict(list))  # tgt -> UNIQUE/OVERLAP -> R
    n_arm = n_ev = n_tr = n_gated = 0

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
            if len(bars) < 10:
                continue
            bars.sort(key=lambda x: x["date"])
            vwap = _vwaps(bars)
            hod = lod = None
            ranges = []
            armed = False
            arm_hod = arm_lod = None
            fired = 0
            for i, b in enumerate(bars):
                h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                rng = h - l
                hod = h if hod is None else max(hod, h)
                lod = l if lod is None else min(lod, l)
                vw = vwap[i] if vwap[i] else None
                if vw and vw > 0 and lod and lod > 0:
                    range_pct = (hod - lod) / lod * 100.0
                    dist_hod = (hod - c) / c * 100.0 if c else 99.0
                    dist_vwap = abs(c - vw) / vw * 100.0
                    if (dist_hod <= hodprox and range_pct >= minrange and dist_vwap <= vwapnear):
                        n_arm += 1
                        arm_hod, arm_lod = hod, lod
                        mr = median(ranges) if ranges else 0.0
                        armed = (mr <= 0) or (rng >= ACCEL * mr)
                if armed and arm_hod is not None and i >= 2 and fired < 2:
                    if c < o and l < min(bars[i - 1]["low"], bars[i - 2]["low"]):
                        entry = min(bars[i - 1]["low"], bars[i - 2]["low"])
                        stop = arm_hod + 0.02
                        n_ev += 1
                        armed = False
                        risk = stop - entry
                        if risk <= 0 or entry <= 0 or risk / entry * 100.0 < minriskpct:
                            n_gated += 1; ranges.append(rng); arm_hod = arm_lod = None; continue
                        tgts = {
                            "LIVE": arm_lod - (arm_hod - arm_lod),
                            "LOD": arm_lod,
                            "VWAP": vwap[i],
                        }
                        n_tr += 1; fired += 1
                        ev_above = (c - vwap[i]) / vwap[i] * 100.0 if vwap[i] else 0.0
                        tag = "UNIQUE" if abs(ev_above) < vwapgate else "OVERLAP"
                        for name, tg in tgts.items():
                            if tg >= entry:   # target must be BELOW entry for a short
                                continue
                            r = _simulate(bars, i, entry, stop, tg, maxhold)
                            if r is None:
                                continue
                            by_tgt[name].append(r)
                            overlap[name][tag].append(r)
                        arm_hod = arm_lod = None
                ranges.append(rng)

    print(f"arms={n_arm}  events={n_ev}  tradeable={n_tr}  gated<{minriskpct:g}%risk={n_gated}\n")
    for name in ("LIVE", "LOD", "VWAP"):
        print("=" * 80)
        print(f"TARGET = {name}" + ("   (the shipping target: LOD-(HOD-LOD))" if name == "LIVE" else ""))
        _report("ALL", by_tgt[name], cap)
        _report("  UNIQUE vs vwap", overlap[name].get("UNIQUE", []), cap)
        _report("  OVERLAP w/ vwap", overlap[name].get("OVERLAP", []), cap)
        print()
    print("=== READING ===")
    print("• LIVE target +EV & sizeable -> setup AND target are sound -> keep/REWRITE w/ trigger+min-risk.")
    print("• LIVE target neg but LOD/VWAP target +EV -> SETUP is fine, live TARGET is too far -> REWRITE w/ closer target.")
    print("• all three neg / tiny n -> no robust range-top-fade edge -> SUPPRESS off_sides.")
    print("• UNIQUE (|dist_vwap|<gate = live's actual zone) is what matters; OVERLAP is vwap_fade-short turf.\n")


if __name__ == "__main__":
    main()
