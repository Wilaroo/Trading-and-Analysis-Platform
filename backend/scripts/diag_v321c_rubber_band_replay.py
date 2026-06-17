#!/usr/bin/env python3
"""
v321c — RUBBER BAND BAR-REPLAY CENSUS (READ-ONLY, native 1-min bars)

GOAL: ground the "find it / fire it / trade it" rebuild in DATA. The current
`_check_rubber_band` fires on a STATE (%-from-EMA9 + RSI + RVOL); the SMB cheat
sheet's edge is a TRIGGER: after price extends from the OPEN and accelerates
lower, a SINGLE green 1-min candle clears the highs of the 2 prior candles (a
"double-bar-break SNAPBACK"). We now have native 1-min bars in
`ib_historical_data` (bar_size='1 min'), so we can reconstruct the REAL event.

This diag, over a trailing clean window:
  1. Builds the universe = symbols the scanner actually watched
     (distinct symbols in live_alerts in the window), capped for runtime.
  2. For each (symbol, RTH day) reconstructs 1-min bars and detects REAL
     rubber-band-LONG snapbacks with an explicit, tunable rule:
        • extension : running low_of_day ≤ open × (1 − EXT_PCT)
        • acceleration (optional): the LOD bar's range ≥ ACCEL× the median
          1-min range so far (sloppy-selling proxy)
        • SNAPBACK  : first GREEN bar after the LOD whose HIGH exceeds the
          highs of the 2 preceding bars, within TRIGGER_WINDOW bars of the LOD
        • discipline: cap 2 events/day (cheat-sheet "2 strikes & out")
  3. Compares the REAL event census to our rubber_band_* alerts at the
     (symbol, day) level → RECALL (real events we alerted on) and PRECISION
     (our alerts that sat on a real-event day).

Day-level matching (not minute) is deliberate: robust, and answers "are we even
firing on the right symbols/days, and how many real ones do we miss?".

RESIDUAL: "3 ATR from open" uses %-from-open here (EXT_PCT) since a clean daily
ATR isn't on the bar doc; tune --ext and read the printed extension distribution.

NOTHING IS WRITTEN. ib_historical_data + live_alerts read-only.

Usage (from repo root):
  .venv/bin/python backend/scripts/diag_v321c_rubber_band_replay.py                 # 14d, ext1.0%, 300 syms
  .venv/bin/python backend/scripts/diag_v321c_rubber_band_replay.py --days 14 --ext 1.5 --universe 200
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TRIGGER_WINDOW = 6     # snapback must print within N bars after the LOD bar
ACCEL = 1.3            # LOD-bar range ≥ ACCEL × median range so far (sloppy sell)


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


def _pct(n, d):
    return f"{(100.0 * n / d):.0f}%" if d else "n/a"


def _detect_long_snapbacks(bars, ext_pct):
    """bars: list of dicts sorted by time within one RTH day. Returns list of
    snapback events (each a dict with low_ext_pct, trigger_idx)."""
    if len(bars) < 5:
        return [], None
    o = bars[0]["open"]
    if not o or o <= 0:
        return [], None
    low_of_day = o
    lod_idx = 0
    ranges = []
    events = []
    armed = False
    armed_at = None
    for i, b in enumerate(bars):
        rng = (b["high"] - b["low"]) if (b["high"] and b["low"]) else 0.0
        if b["low"] and b["low"] < low_of_day:
            low_of_day = b["low"]
            lod_idx = i
            # re-arm whenever we make a new extended low
            if low_of_day <= o * (1.0 - ext_pct / 100.0):
                med_r = median(ranges) if ranges else 0.0
                accel_ok = (med_r <= 0) or (rng >= ACCEL * med_r)
                armed = True
                armed_at = i if accel_ok else None
        # snapback trigger: green bar clearing prior-2 highs, shortly after LOD
        if armed and armed_at is not None and i >= 2 and i - lod_idx <= TRIGGER_WINDOW:
            green = b["close"] > b["open"]
            clears = b["high"] > max(bars[i - 1]["high"], bars[i - 2]["high"])
            if green and clears:
                events.append({
                    "ext_pct": round((o - low_of_day) / o * 100.0, 2),
                    "trigger_min": i,
                })
                armed = False
                armed_at = None
                if len(events) >= 2:   # cheat-sheet 2/day cap
                    break
        ranges.append(rng)
    ext_seen = round((o - low_of_day) / o * 100.0, 2)
    return events, ext_seen


def main():
    days = _arg("--days", 14, int)
    ext_pct = _arg("--ext", 1.0, float)
    uni_cap = _arg("--universe", 300, int)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v321c RUBBER BAND BAR-REPLAY — trailing {days}d (since "
          f"{start.strftime('%Y-%m-%d')} ET)  ext≥{ext_pct:g}%  univ≤{uni_cap} ===\n")

    # ---- our rubber_band alerts (for recall/precision + universe weighting) ----
    rb_alert_days = defaultdict(int)     # (symbol, day) -> alert count
    alert_syms = Counter()
    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "setup_type": 1,
                                       "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if not (et and et >= start):
            continue
        sym = a.get("symbol")
        if not sym:
            continue
        universe[sym] += 1
        su = (a.get("setup_type") or "").lower()
        if su.startswith("rubber_band"):
            rb_alert_days[(sym, et.strftime("%Y-%m-%d"))] += 1
            alert_syms[sym] += 1

    syms = [s for s, _ in universe.most_common(uni_cap)]
    # make sure every symbol we alerted rubber_band on is in the replay universe
    for s in alert_syms:
        if s not in syms:
            syms.append(s)
    print(f"universe: {len(syms)} symbols (scanner-watched; "
          f"{len(alert_syms)} had rubber_band alerts)\n")

    # ---- bar replay ----
    real_event_days = set()              # (symbol, day) with ≥1 real snapback
    real_event_count = 0
    ext_dist = []
    days_scanned = 0
    syms_with_bars = 0
    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": "1 min", "date": {"$gte": start_utc.isoformat()}},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        )
        by_day = defaultdict(list)
        for b in cur:
            et = _to_et(b.get("date"))
            if _is_rth(et):
                b["_et"] = et
                by_day[et.strftime("%Y-%m-%d")].append(b)
        if by_day:
            syms_with_bars += 1
        for day, bars in by_day.items():
            bars.sort(key=lambda x: x["_et"])
            days_scanned += 1
            events, ext_seen = _detect_long_snapbacks(bars, ext_pct)
            if ext_seen is not None:
                ext_dist.append(ext_seen)
            if events:
                real_event_days.add((sym, day))
                real_event_count += len(events)

    print(f"scanned {days_scanned} (symbol,RTH-day) cells across {syms_with_bars} "
          f"symbols with 1-min bars\n")

    # ---- census ----
    print("=" * 78)
    print("SECTION 1 — REAL rubber-band-LONG snapback census (from 1-min bars)")
    print("=" * 78)
    print(f"  real snapback EVENTS (≤2/day)      : {real_event_count}")
    print(f"  (symbol,day) cells with ≥1 event   : {len(real_event_days)}")
    if days_scanned:
        print(f"  event-day rate                     : {_pct(len(real_event_days), days_scanned)} "
              f"of scanned cells")

    # ---- recall / precision vs our alerts (day-level) ----
    print("\n" + "=" * 78)
    print("SECTION 2 — current detector vs REAL events  (day-level match)")
    print("=" * 78)
    our_days = set(rb_alert_days.keys())
    overlap = real_event_days & our_days
    recall = _pct(len(overlap), len(real_event_days))
    precision = _pct(len(overlap), len(our_days))
    print(f"  our rubber_band alert (symbol,day) cells : {len(our_days)}  "
          f"(total alerts {sum(rb_alert_days.values())})")
    print(f"  REAL event cells                         : {len(real_event_days)}")
    print(f"  overlap (we alerted on a real-event day) : {len(overlap)}")
    print(f"  RECALL    (real events we caught)        : {recall}")
    print(f"  PRECISION (our alerts on a real day)     : {precision}")
    if our_days:
        spam = [c for c in rb_alert_days.values() if c > 2]
        print(f"  alert cells firing >2/day (over cap)     : {len(spam)}/{len(our_days)} "
              f"({_pct(len(spam), len(our_days))})  max {max(rb_alert_days.values())}/day")

    # ---- extension distribution (calibrate --ext) ----
    print("\n" + "=" * 78)
    print("SECTION 3 — intraday max-drawdown-from-open distribution (calibration)")
    print("=" * 78)
    if ext_dist:
        xs = sorted(ext_dist)
        n = len(xs)
        def q(p): return xs[min(int(p * (n - 1)), n - 1)]
        print(f"  per (symbol,day) max % below open:  p50={q(.5):.2f}%  p75={q(.75):.2f}%  "
              f"p90={q(.9):.2f}%  p95={q(.95):.2f}%  max={xs[-1]:.2f}%")
        for thr in (0.5, 1.0, 1.5, 2.0, 3.0):
            c = sum(1 for x in xs if x >= thr)
            print(f"    cells reaching ≥{thr:.1f}% below open: {c} ({_pct(c, n)})")

    print("\n=== READING THE RESULT ===")
    print("• LOW RECALL = we MISS most real snapbacks → the detector looks on the wrong")
    print("    axis (%-from-EMA9 vs ATR-from-open) and has no trigger. This is the")
    print("    'find it properly' gap, quantified.")
    print("• LOW PRECISION = our alerts mostly DON'T sit on a real snapback day → we fire")
    print("    on the grind-down state, not the reversal. This is the over-fire, quantified.")
    print("• A redesigned detector = {ext-from-open ≥ chosen %} + {1-min double-bar-break")
    print("    snapback within a few bars of the LOD} + {RVOL/quality} + {2/day cap}. This")
    print("    diag's rule IS that detector, run historically — tune --ext to your event rate.")
    print("• Next: a TRADE-side trace (why rubber_band alerts → 0 sanitized trades) closes")
    print("    the 'trade it properly' third of the loop.\n")


if __name__ == "__main__":
    main()
