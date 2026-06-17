#!/usr/bin/env python3
"""
v340b — VWAP-FADE REPLAY, RISK-CONTROLLED (READ-ONLY) — strips the R-denominator artifact

v340 showed avgR +0.9..+2.3R but medR <=0 across most buckets → the mean is inflated by
TINY-RISK events (stop ~2c from entry → r_target explodes to 10R+ on a few prints). The live
system would never take those: v336 already blocks short fades with stop% < 1.0%. This re-run
(a) GATES OUT events whose stop distance < --minriskpct of entry (default 1.0%, matching v336),
and (b) reports RAW avg, WINSORIZED avg (±--winsor, default 3.0, matching v336/learning_loop),
and MEDIAN together so the TRUE central-tendency edge is visible, not the outlier-skewed mean.

Same geometry as v340 (entry=2-bar-break, stop=extreme±0.02, target=VWAP 1R-floor, accel1.3x,
2/day cap, by ext-bucket + snapback-speed).

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v340b_vwap_fade_riskctl.py \
     --days 14 --ext 1.0 --universe 300 --maxhold 30 --side both --minriskpct 1.0 --winsor 3.0
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
    if len(bars) < 5:
        return []
    ranges = []
    events = []
    ext_idx = None
    ext_px = None
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
            else:
                stretch = (vw - l) / vw * 100.0 if l else 0.0
                if stretch >= ext_pct and (ext_px is None or l < ext_px):
                    ext_px, ext_idx = l, i
                    med_r = median(ranges) if ranges else 0.0
                    armed = (med_r <= 0) or (rng >= ACCEL * med_r)
        if armed and ext_idx is not None and i >= 2 and 0 < (i - ext_idx) <= TRIGGER_WINDOW:
            if side == "short":
                if c < o and l < min(bars[i - 1]["low"], bars[i - 2]["low"]):
                    en = (ext_px - vwap[ext_idx]) / vwap[ext_idx] * 100.0 if vwap[ext_idx] else 0.0
                    events.append({"trigger_idx": i, "ext_px": ext_px, "ext_pct": round(en, 2),
                                   "bars_from_ext": i - ext_idx})
                    armed = False; ext_idx = None; ext_px = None
                    if len(events) >= 2:
                        break
            else:
                if c > o and h > max(bars[i - 1]["high"], bars[i - 2]["high"]):
                    en = (vwap[ext_idx] - ext_px) / vwap[ext_idx] * 100.0 if vwap[ext_idx] else 0.0
                    events.append({"trigger_idx": i, "ext_px": ext_px, "ext_pct": round(en, 2),
                                   "bars_from_ext": i - ext_idx})
                    armed = False; ext_idx = None; ext_px = None
                    if len(events) >= 2:
                        break
        ranges.append(rng)
    return events


def _simulate(bars, vwap, ev, side, maxhold):
    """Returns (realized_R, risk_pct_of_entry) or None."""
    i = ev["trigger_idx"]
    if i < 2 or i + 1 >= len(bars):
        return None
    if side == "short":
        entry = min(bars[i - 1]["low"], bars[i - 2]["low"])
        stop = ev["ext_px"] + 0.02
        risk = stop - entry
        if risk <= 0 or entry <= 0:
            return None
        rp = risk / entry * 100.0
        target = vwap[i] if (vwap[i] and vwap[i] < entry) else (entry - risk)
        r_target = (entry - target) / risk
        end = min(i + 1 + maxhold, len(bars))
        for j in range(i + 1, end):
            if bars[j]["high"] >= stop:
                return (-1.0, rp)
            if bars[j]["low"] <= target:
                return (round(r_target, 3), rp)
        return (round((entry - bars[end - 1]["close"]) / risk, 3), rp)
    else:
        entry = max(bars[i - 1]["high"], bars[i - 2]["high"])
        stop = ev["ext_px"] - 0.02
        risk = entry - stop
        if risk <= 0 or entry <= 0:
            return None
        rp = risk / entry * 100.0
        target = vwap[i] if (vwap[i] and vwap[i] > entry) else (entry + risk)
        r_target = (target - entry) / risk
        end = min(i + 1 + maxhold, len(bars))
        for j in range(i + 1, end):
            if bars[j]["low"] <= stop:
                return (-1.0, rp)
            if bars[j]["high"] >= target:
                return (round(r_target, 3), rp)
        return (round((bars[end - 1]["close"] - entry) / risk, 3), rp)


def _bucket(ext):
    if ext < 2.0:
        return "1-2%"
    if ext < 3.0:
        return "2-3%"
    return ">=3%"


def _report(label, rs, wins_cap):
    if not rs:
        print(f"  {label:<10} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-wins_cap, min(wins_cap, r)) for r in rs]
    print(f"  {label:<10} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"rawAvg={mean(rs):+.3f}  winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  "
          f"totWinsorR={sum(wr):+.1f}")


def _run_side(db, syms, side, start, start_utc, ext_pct, maxhold, minriskpct, wins_cap):
    all_r, by_bucket, by_window = [], defaultdict(list), defaultdict(list)
    n_events = n_tradeable = n_gated = days_with_event = 0
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
                sim = _simulate(bars, vwap, ev, side, maxhold)
                if sim is None:
                    continue
                r, rp = sim
                if rp < minriskpct:
                    n_gated += 1
                    continue
                n_tradeable += 1
                all_r.append(r)
                by_bucket[_bucket(ev["ext_pct"])].append(r)
                by_window[ev["bars_from_ext"]].append(r)

    print("=" * 78)
    print(f"{side.upper()}  events={n_events}  gated<{minriskpct:g}%risk={n_gated}  "
          f"tradeable={n_tradeable}  ({days_with_event} symbol-days)")
    _report("ALL", all_r, wins_cap)
    print("  BY EXTENSION BUCKET")
    for b in ("1-2%", "2-3%", ">=3%"):
        _report("   " + b, by_bucket.get(b, []), wins_cap)
    print("  BY SNAPBACK SPEED (bars from extreme→trigger)")
    for w in sorted(by_window):
        _report(f"   +{w}bar", by_window[w], wins_cap)
    print()


def main():
    days = _arg("--days", 14, int)
    ext_pct = _arg("--ext", 1.0, float)
    uni_cap = _arg("--universe", 300, int)
    maxhold = _arg("--maxhold", 30, int)
    side = _arg("--side", "both", str)
    minriskpct = _arg("--minriskpct", 1.0, float)
    wins_cap = _arg("--winsor", 3.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v340b VWAP-FADE REPLAY (RISK-CONTROLLED) — {days}d  ext>={ext_pct:g}%  "
          f"minrisk>={minriskpct:g}%  winsor=±{wins_cap:g}R  side={side} ===")
    print("  gates out tiny-stop R-explosions; winsorAvg+medR = the trustworthy edge.\n")

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
        _run_side(db, syms, s, start, start_utc, ext_pct, maxhold, minriskpct, wins_cap)

    print("=== READING ===")
    print("• winsorAvg and medR AGREE and are comfortably >0 in a bucket → REAL edge there.")
    print("• rawAvg >0 but winsorAvg/medR ~0 or <0 → the edge was an R-denominator artifact;")
    print("  do NOT rewire that side/bucket.")
    print("• If LONG 1-2% holds +EV after gating but SHORT stays <=0 → build a LONG-ONLY")
    print("  vwap_fade rewrite (mirrors the rubber_band long-only logic); keep short suppressed.\n")


if __name__ == "__main__":
    main()
