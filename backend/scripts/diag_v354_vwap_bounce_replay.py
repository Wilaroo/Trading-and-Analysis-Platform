#!/usr/bin/env python3
"""
v354 — VWAP BOUNCE (cheat-sheet-faithful) REPLAY  (READ-ONLY).

WHY: the shipped `_check_vwap_bounce` is a stateless near-VWAP STATE filter:
  LIVE  : fires when dist_from_vwap in (-0.8%, +0.3%), trend==uptrend, above 9-EMA, rvol>=1.5.
          trigger=VWAP, stop=VWAP-0.5*ATR, target=VWAP+1.5*ATR, R:R hard-coded 3.0.
          -> "price is near VWAP in an uptrend", no up-leg, no bounce trigger, no measured move.
  DOCTRINE (SMB "First VWAP Pullback" mechanics, generalized to the all-day vwap_bounce):
     1) a strong up-LEG prints (an opening-drive-style impulse: swing low -> swing high),
     2) price PULLS BACK to RISING VWAP and HOLDS ABOVE it (pullback must NOT close below VWAP),
     3) ENTER on a confirmation candle (green, closes above the prior candle) as buyers regain
        control near VWAP,
     4) STOP = just BELOW VWAP,
     5) TARGET = a MEASURED MOVE of the first leg (entry + leg height).
This script replays IB 1-min bars and scores TWO arms:
  • LIVE-PROXY : the shipped near-VWAP-state rule (stop=VWAP-0.5ATR, target=VWAP+1.5ATR).
  • DOCTRINE   : up-leg -> pullback-to-VWAP-holding -> confirm; stop just below VWAP, target=
                 measured move, RR-gated [--minrr, --maxrr].
Reports n, win%, winsorized avg R, median R, total winsorized R, avg R:R taken, and R:R
buckets for each arm.  NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v354_vwap_bounce_replay.py \
     --days 14 --leglook 10 --pullwin 5 --vwaptol 0.15 --minleg 0.5 --stopbuf 0.10 \
     --minrr 1.0 --maxrr 0 --maxhold 30 --maxattempts 2 --universe 300 --winsor 3.0 --timewin 0
  # --timewin 1 restricts to the cheat-sheet OPEN window (09:35-09:45 ET) for first_vwap_pullback.
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
EMA_LEN = 9
ATR_LEN = 14


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


def _in_open(et):
    if et is None:
        return False
    m = et.hour * 60 + et.minute
    return (9 * 60 + 35) <= m <= (9 * 60 + 45)


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


def _atrs(bars, n):
    out = []
    trs = []
    prev_c = None
    for b in bars:
        h, l, c = b["high"], b["low"], b["close"]
        tr = (h - l) if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
        prev_c = c
        window = trs[-n:]
        out.append(mean(window) if window else 0.0)
    return out


def _rr_bucket(rr):
    if rr < 1.0:
        return "<1.0"
    if rr < 1.5:
        return "1.0-1.5"
    if rr < 2.5:
        return "1.5-2.5"
    return ">=2.5"


def _sim_exit(bars, i, entry, stop, target, rr, maxhold):
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return None
    end = min(i + 1 + maxhold, len(bars))
    for j in range(i + 1, end):
        if bars[j]["low"] <= stop:
            return -1.0
        if bars[j]["high"] >= target:
            return rr
    return round((bars[end - 1]["close"] - entry) / risk, 3)


def _report(label, rs, rrs, cap):
    if not rs:
        print(f"  {label:<16} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    avg_rr = mean(rrs) if rrs else 0.0
    print(f"  {label:<16} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}  "
          f"avgRR={avg_rr:.2f}")


def main():
    days = _arg("--days", 14, int)
    leglook = _arg("--leglook", 10, int)     # window to find the up-leg (swing low -> high)
    pullwin = _arg("--pullwin", 5, int)      # pullback window (must touch & hold VWAP)
    vwaptol = _arg("--vwaptol", 0.15, float) # pullback low within vwaptol% of VWAP
    minleg = _arg("--minleg", 0.5, float)    # up-leg must be >= minleg% (a real drive)
    stopbuf = _arg("--stopbuf", 0.10, float) # stop = VWAP * (1 - stopbuf%) (just below VWAP)
    minrr = _arg("--minrr", 1.0, float)
    maxrr = _arg("--maxrr", 0.0, float)      # 0 = off
    maxhold = _arg("--maxhold", 30, int)
    maxattempts = _arg("--maxattempts", 2, int)
    uni_cap = _arg("--universe", 300, int)
    cap = _arg("--winsor", 3.0, float)
    timewin = _arg("--timewin", 0, int)      # 1 = OPEN-only (09:35-09:45) for first_vwap_pullback

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    _maxrr_lbl = f"{maxrr:g}" if maxrr > 0 else "off"
    print(f"\n=== v354 VWAP BOUNCE replay — {days}d  leglook={leglook}  pullwin={pullwin}  "
          f"vwaptol={vwaptol:g}%  minleg={minleg:g}%  stopbuf={stopbuf:g}%  minRR={minrr:g}  "
          f"maxRR={_maxrr_lbl}  timewin={'09:35-09:45' if timewin else 'all-RTH'}  winsor=±{cap:g}R ===\n")

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start and a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    print(f"universe: {len(syms)} symbols\n")

    doc_r, doc_rr = [], []
    doc_by_rr = defaultdict(list)
    live_r, live_rr = [], []
    n_doc_ev = n_doc_tr = n_live_tr = 0

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
            need = leglook + pullwin + 3
            if len(bars) < max(need, EMA_LEN + 3):
                continue
            bars.sort(key=lambda x: x["date"])
            ema = _ema(bars, EMA_LEN)
            vwap = _vwaps(bars)
            atr = _atrs(bars, ATR_LEN)

            doc_fired = 0
            live_fired = 0
            for i in range(need, len(bars)):
                b = bars[i]
                et = _to_et(b.get("date"))
                if timewin and not _in_open(et):
                    continue
                h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                vw, em = vwap[i], ema[i]

                # ---------- DOCTRINE arm ----------
                if doc_fired < maxattempts and vw and vw > 0:
                    leg = bars[i - leglook - pullwin:i - pullwin]   # up-leg region
                    ret = bars[i - pullwin:i]                       # pullback region (excl. entry)
                    if leg and ret:
                        leg_lows = [x["low"] for x in leg]
                        sl_idx = min(range(len(leg)), key=lambda k: leg[k]["low"])
                        swing_low = leg[sl_idx]["low"]
                        swing_high = max(x["high"] for x in leg[sl_idx:]) if sl_idx < len(leg) else max(x["high"] for x in leg)
                        leg_h = swing_high - swing_low
                        drive_ok = swing_low > 0 and (leg_h / swing_low * 100.0) >= minleg
                        pull_low = min(x["low"] for x in ret)
                        pull_close_min = min(x["close"] for x in ret)
                        touched = pull_low <= vw * (1 + vwaptol / 100.0)
                        held = pull_close_min >= vw * (1 - vwaptol / 100.0)   # didn't close below VWAP
                        above = c > vw
                        confirm = (c > o) and (c > bars[i - 1]["high"])
                        if drive_ok and touched and held and above and confirm:
                            n_doc_ev += 1
                            entry = c
                            stop = vw * (1 - stopbuf / 100.0)
                            target = entry + leg_h            # measured move of the first leg
                            risk = entry - stop
                            if risk > 0 and target > entry:
                                rr = (target - entry) / risk
                                if rr >= minrr and (maxrr <= 0 or rr <= maxrr):
                                    r = _sim_exit(bars, i, entry, stop, target, rr, maxhold)
                                    if r is not None:
                                        n_doc_tr += 1; doc_fired += 1
                                        doc_r.append(r); doc_rr.append(rr)
                                        doc_by_rr[_rr_bucket(rr)].append(r)

                # ---------- LIVE-PROXY arm (shipped near-VWAP state) ----------
                if live_fired < maxattempts and vw and vw > 0 and atr[i] > 0:
                    dist = (c - vw) / vw * 100.0
                    uptrend = (i >= 5 and vw > vwap[i - 5] and c > em)
                    med20 = median([x.get("volume") or 0 for x in bars[max(0, i - 20):i]]) or 0
                    rvol_ok = (b.get("volume") or 0) >= 1.5 * med20
                    if -0.8 < dist < 0.3 and uptrend and rvol_ok:
                        entry = c
                        stop = vw - 0.5 * atr[i]
                        target = vw + 1.5 * atr[i]
                        risk = entry - stop
                        if risk > 0 and target > entry:
                            rr = (target - entry) / risk
                            r = _sim_exit(bars, i, entry, stop, target, rr, maxhold)
                            if r is not None:
                                n_live_tr += 1; live_fired += 1
                                live_r.append(r); live_rr.append(rr)

    print(f"DOCTRINE events={n_doc_ev}  tradeable(RR>={minrr:g})={n_doc_tr}    "
          f"LIVE-proxy trades={n_live_tr}\n")
    print("=" * 78)
    print("VWAP BOUNCE — LIVE (near-VWAP state, stop=VWAP-0.5ATR, target=VWAP+1.5ATR) vs DOCTRINE")
    print("=" * 78)
    _report("LIVE-PROXY", live_r, live_rr, cap)
    _report("DOCTRINE ALL", doc_r, doc_rr, cap)
    for k in ("<1.0", "1.0-1.5", "1.5-2.5", ">=2.5"):
        _report("  DOC RR " + k, doc_by_rr.get(k, []),
                [rr for rr in doc_rr if _rr_bucket(rr) == k], cap)
    print()
    print("=== READING ===")
    print("• Doctrine: opening-drive up-leg -> pullback HOLDS VWAP -> confirm bounce; stop just")
    print("  below VWAP, target = measured move of the first leg.")
    print("• If a DOCTRINE R:R band shows win% with winsorAvg/medR > 0 AND beats LIVE-PROXY,")
    print("  rewrite _check_vwap_bounce gated to that band (like v353 second_chance).")
    print("• Use --timewin 1 (09:35-09:45) to evaluate the pure first_vwap_pullback (open) variant.")
    print("• If DOCTRINE n is tiny, loosen --vwaptol/--minleg; if RR<1.0 dominates negative, raise --minrr.\n")


if __name__ == "__main__":
    main()
