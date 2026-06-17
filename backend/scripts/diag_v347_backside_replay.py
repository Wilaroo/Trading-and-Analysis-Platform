#!/usr/bin/env python3
"""
v347 — BACKSIDE (VWAP-recovery, LONG-only) REPLAY + vwap_fade overlap, one run (READ-ONLY).

FADE SWEEP #4 (backside, 487 fires). The live _check_backside (enhanced_scanner L5057)
is a LONG-only STATE detector:
    trend==uptrend  AND  above_ema9  AND  NOT above_vwap  AND  dist_from_vwap > -2%  AND  rvol>=1.2
    target = VWAP,  stop = ema9-0.02 (ATR-floored),  no snapback trigger, no R cap, no min-risk gate.
"Back$ide" = price dipped BELOW VWAP but is recovering (holding above the 9-EMA) and snapping
back UP to VWAP. This replay applies the proven v341/v345 mechanics anchored to the 1-min VWAP:

  LONG: price extended BELOW VWAP (dip), STILL above the 9-EMA (recovering),
        -> green double-bar-HIGH-break after the dip-low within +1..+4 bars -> snapback target = VWAP.
  entry = 2-bar-high-break, stop = dip-low - 0.02, target = VWAP (1R floor),
  accel 1.3x, 2/day, EMA9 recovery gate, min-risk gate, R winsorized.

Because backside is capped at 2% below VWAP and the now-live vwap_fade triggers at ext>~1%,
the OVERLAP band is the 1-2% dip and the UNIQUE band is the shallow 0-1% dip vwap_fade misses.
Each trade is tagged UNIQUE (dip < --vwapgate, vwap_fade misses) vs OVERLAP (>= gate, vwap_fade dup)
to settle edge AND redundancy in a single run.

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v347_backside_replay.py \
     --days 14 --ext 0.3 --maxdip 2.0 --universe 300 --maxhold 30 \
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
EMA_LEN = 9  # backside recovery filter is the 9-EMA


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


def _bucket(d):
    if d < 0.5:
        return "0-0.5%"
    if d < 1.0:
        return "0.5-1%"
    if d < 1.5:
        return "1-1.5%"
    if d < 2.0:
        return "1.5-2%"
    return ">=2%"


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
    ext_pct = _arg("--ext", 0.3, float)       # min dip below VWAP to "arm" (backside is a dip)
    maxdip = _arg("--maxdip", 2.0, float)     # live caps dip at 2% below VWAP (dist_from_vwap>-2)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    minriskpct = _arg("--minriskpct", 1.0, float)
    cap = _arg("--winsor", 3.0, float)
    vwapgate = _arg("--vwapgate", 1.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v347 BACKSIDE (VWAP-recovery, LONG-only) REPLAY — {days}d  dip {ext_pct:g}..{maxdip:g}%  "
          f"minrisk>={minriskpct:g}%  winsor=±{cap:g}R  vwap_gate={vwapgate:g}% ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    all_r = []
    by_bucket = defaultdict(list)
    overlap = defaultdict(list)   # UNIQUE/OVERLAP -> R
    n_ev = n_tr = n_gated = n_capdip = 0

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
            ranges = []
            dip_idx = dip_px = None   # the LOD of the dip below VWAP
            armed = False
            fired = 0
            for i, b in enumerate(bars):
                h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                vw = vwap[i] if vwap[i] else None
                rng = h - l
                # arm on a fresh dip-low BELOW vwap within the live's 0..maxdip band
                if vw and vw > 0 and l < vw:
                    dip = (vw - l) / vw * 100.0
                    if ext_pct <= dip <= maxdip and (dip_px is None or l < dip_px):
                        dip_px, dip_idx = l, i
                        mr = median(ranges) if ranges else 0.0
                        armed = (mr <= 0) or (rng >= ACCEL * mr)
                # trigger: green bar breaks prior-2 highs, STILL above 9-EMA (recovering), below VWAP
                if armed and dip_idx is not None and i >= 2 and 0 < (i - dip_idx) <= TRIGGER_WIN and fired < 2:
                    em = ema[i] if i >= EMA_LEN else None
                    if (c > o and h > max(bars[i - 1]["high"], bars[i - 2]["high"])
                            and em is not None and c > em):
                        entry = max(bars[i - 1]["high"], bars[i - 2]["high"])
                        stop = dip_px - 0.02
                        n_ev += 1
                        armed = False; sidx = dip_idx; dip_idx = dip_px = None
                        tgt = vwap[i]
                        risk = entry - stop
                        # backside is only valid while entry is still below VWAP (recovering UP to it)
                        if vw is None or entry >= vw:
                            n_capdip += 1; ranges.append(rng); continue
                        if risk <= 0 or entry <= 0 or risk / entry * 100.0 < minriskpct:
                            n_gated += 1; ranges.append(rng); continue
                        if tgt <= entry:   # target must be above entry
                            ranges.append(rng); continue
                        n_tr += 1; fired += 1
                        rt = (tgt - entry) / risk
                        r = None
                        end = min(i + 1 + maxhold, len(bars))
                        for j in range(i + 1, end):
                            if bars[j]["low"] <= stop:
                                r = -1.0; break
                            if bars[j]["high"] >= tgt:
                                r = rt; break
                        if r is None:
                            lc = bars[end - 1]["close"]
                            r = (lc - entry) / risk
                        r = round(r, 3)
                        all_r.append(r)
                        dip_at_entry = (vw - entry) / vw * 100.0
                        by_bucket[_bucket(dip_at_entry)].append(r)
                        overlap["UNIQUE" if dip_at_entry < vwapgate else "OVERLAP"].append(r)
                ranges.append(rng)

    print(f"events={n_ev}  tradeable={n_tr}  gated<{minriskpct:g}%risk={n_gated}  entry>=VWAP_skip={n_capdip}\n")
    print("=" * 78)
    print("LONG  (dip-below-VWAP recovery -> snapback to VWAP)")
    _report("ALL", all_r, cap)
    for b in ("0-0.5%", "0.5-1%", "1-1.5%", "1.5-2%", ">=2%"):
        _report("  dip " + b, by_bucket.get(b, []), cap)
    _report("  UNIQUE vs vwap", overlap.get("UNIQUE", []), cap)
    _report("  OVERLAP w/ vwap", overlap.get("OVERLAP", []), cap)
    print()
    print("=== READING ===")
    print("• dip buckets where winsorAvg & medR >0 = real VWAP-recovery edge -> FIRE floor.")
    print("• UNIQUE (0..gate%, vwap_fade miss) sizeable & +EV -> backside adds shallow-dip edge -> REWRITE.")
    print("• UNIQUE small/neg & OVERLAP dominates -> mostly a vwap_fade duplicate -> SUPPRESS backside.")
    print("• live detector: above_ema9 + below_vwap + dist_from_vwap>-2% (no trigger/cap/min-risk).\n")


if __name__ == "__main__":
    main()
