#!/usr/bin/env python3
"""
v355 — OPENING RANGE BREAK (cheat-sheet-faithful) REPLAY  (READ-ONLY).

WHY: the shipped `_check_orb` treats the running HIGH/LOW OF DAY as the "opening range":
  LIVE  : morning only, rvol>=2; "confirmed" when price broke the running HOD by 0.1-1.5%
          and above VWAP. stop = LOD-0.02 (full-day low), target = price + 2*(HOD-LOD), R:R 2.0.
          -> HOD/LOD drift all morning, so it is NOT the opening range; the LOD stop is far.
  DOCTRINE (SMB Opening Range Break cheat sheet):
     1) define the OPENING RANGE = high/low of the first --ormin minutes (5/15/30) from 09:30,
     2) ENTER when price breaks ABOVE the OR high with a VOLUME expansion (flood of green),
     3) STOP just BELOW THE BREAKOUT BAR (not the full range low),
     4) TARGET = 2x measured move of the opening range (OR_high + tmult*OR_height),
     5) TIME-EXIT by 10:30/11:30 ET to avoid reversals; >=2:1 R:R; trending (avoid chop).
This script replays IB 1-min bars and scores TWO arms:
  • LIVE-PROXY : the shipped running-HOD/LOD rule (stop=LOD-0.02, target=price+2*(HOD-LOD)).
  • DOCTRINE   : true first-N-min OR -> break+volume -> stop below breakout bar, target=2x OR,
                 time-exit, RR-gated [--minrr, --maxrr], one breakout/day.
Reports n, win%, winsorized avg R, median R, total winsorized R, avg R:R, R:R buckets. NOTHING WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v355_orb_replay.py \
     --days 14 --ormin 15 --volmult 1.5 --stopbuf 0.05 --tmult 2.0 --timeexit 690 \
     --minrr 1.0 --maxrr 0 --maxhold 60 --universe 300 --winsor 3.0
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


def _etmin(et):
    return et.hour * 60 + et.minute if et else None


def _is_rth(et):
    if et is None or et.weekday() >= 5:
        return False
    m = _etmin(et)
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


def _rr_bucket(rr):
    if rr < 1.0:
        return "<1.0"
    if rr < 1.5:
        return "1.0-1.5"
    if rr < 2.5:
        return "1.5-2.5"
    return ">=2.5"


def _sim_exit(bars, i, entry, stop, target, rr, last_idx):
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return None
    for j in range(i + 1, last_idx + 1):
        if bars[j]["low"] <= stop:
            return -1.0
        if bars[j]["high"] >= target:
            return rr
    return round((bars[last_idx]["close"] - entry) / risk, 3)


def _report(label, rs, rrs, cap):
    if not rs:
        print(f"  {label:<16} n=0")
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    avg_rr = mean(rrs) if rrs else 0.0
    print(f"  {label:<16} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  "
          f"winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}  avgRR={avg_rr:.2f}")


def main():
    days = _arg("--days", 14, int)
    ormin = _arg("--ormin", 15, int)         # opening-range minutes (5/15/30)
    volmult = _arg("--volmult", 1.5, float)  # breakout bar vol >= volmult * OR avg vol
    stopbuf = _arg("--stopbuf", 0.05, float) # stop = breakout-bar low * (1 - stopbuf%)
    tmult = _arg("--tmult", 2.0, float)      # target = OR_high + tmult*OR_height (2x measured move)
    timeexit = _arg("--timeexit", 690, int)  # ET minute hard exit (690=11:30, 630=10:30)
    minrr = _arg("--minrr", 1.0, float)
    maxrr = _arg("--maxrr", 0.0, float)
    maxhold = _arg("--maxhold", 60, int)
    uni_cap = _arg("--universe", 300, int)
    cap = _arg("--winsor", 3.0, float)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)
    or_end = 570 + ormin

    _maxrr_lbl = f"{maxrr:g}" if maxrr > 0 else "off"
    print(f"\n=== v355 ORB replay — {days}d  ormin={ormin}  volmult={volmult:g}  stopbuf={stopbuf:g}%  "
          f"tmult={tmult:g}x  timeexit={timeexit}ET  minRR={minrr:g}  maxRR={_maxrr_lbl}  winsor=±{cap:g}R ===\n")

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
    n_doc = n_live = 0

    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": "1 min", "date": {"$gte": start_utc.isoformat()}},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
        by_day = defaultdict(list)
        for b in cur:
            et = _to_et(b.get("date"))
            if _is_rth(et):
                b["_etm"] = _etmin(et)
                by_day[et.strftime("%Y-%m-%d")].append(b)

        for d, bars in by_day.items():
            if len(bars) < 20:
                continue
            bars.sort(key=lambda x: x["date"])
            vwap = _vwaps(bars)
            # last tradable index = last bar at/before timeexit
            exit_idx = max((k for k, b in enumerate(bars) if b["_etm"] <= timeexit), default=-1)

            # ---------- DOCTRINE: true opening range ----------
            or_bars = [b for b in bars if 570 <= b["_etm"] < or_end]
            if or_bars and exit_idx >= 0:
                or_high = max(b["high"] for b in or_bars)
                or_low = min(b["low"] for b in or_bars)
                or_h = or_high - or_low
                or_vol = mean([b.get("volume") or 0 for b in or_bars]) or 0.0
                if or_h > 0:
                    for i, b in enumerate(bars):
                        if b["_etm"] < or_end or b["_etm"] > timeexit:
                            continue
                        if b["close"] > or_high and b["high"] > or_high \
                                and ((or_vol <= 0) or (b.get("volume") or 0) >= volmult * or_vol):
                            entry = b["close"]
                            stop = b["low"] * (1 - stopbuf / 100.0)
                            target = or_high + tmult * or_h
                            risk = entry - stop
                            if risk > 0 and target > entry:
                                rr = (target - entry) / risk
                                if rr >= minrr and (maxrr <= 0 or rr <= maxrr):
                                    last = min(i + maxhold, exit_idx)
                                    r = _sim_exit(bars, i, entry, stop, target, rr, last)
                                    if r is not None:
                                        n_doc += 1
                                        doc_r.append(r); doc_rr.append(rr)
                                        doc_by_rr[_rr_bucket(rr)].append(r)
                            break  # first breakout only

            # ---------- LIVE-PROXY: running HOD/LOD rule ----------
            for i in range(1, len(bars)):
                b = bars[i]
                if not (570 + 5 <= b["_etm"] <= timeexit):
                    continue
                hod = max(x["high"] for x in bars[:i])
                lod = min(x["low"] for x in bars[:i])
                price = b["close"]
                if price <= 0 or hod <= 0:
                    continue
                dist = (hod - price) / price * 100.0
                med20 = median([x.get("volume") or 0 for x in bars[max(0, i - 20):i]]) or 0
                rvol_ok = (b.get("volume") or 0) >= 2.0 * med20
                if -1.5 < dist < -0.1 and price > vwap[i] and rvol_ok:
                    entry = price
                    stop = lod - 0.02
                    target = entry + 2.0 * (hod - lod)
                    risk = entry - stop
                    if risk > 0 and target > entry:
                        rr = (target - entry) / risk
                        last = min(i + maxhold, exit_idx if exit_idx >= 0 else len(bars) - 1)
                        r = _sim_exit(bars, i, entry, stop, target, rr, last)
                        if r is not None:
                            n_live += 1
                            live_r.append(r); live_rr.append(rr)
                    break  # first breakout only

    print(f"DOCTRINE trades={n_doc}    LIVE-proxy trades={n_live}\n")
    print("=" * 80)
    print("ORB — LIVE (running HOD/LOD, stop=LOD-.02, target=price+2*(HOD-LOD)) vs DOCTRINE (true OR)")
    print("=" * 80)
    _report("LIVE-PROXY", live_r, live_rr, cap)
    _report("DOCTRINE ALL", doc_r, doc_rr, cap)
    for k in ("<1.0", "1.0-1.5", "1.5-2.5", ">=2.5"):
        _report("  DOC RR " + k, doc_by_rr.get(k, []),
                [rr for rr in doc_rr if _rr_bucket(rr) == k], cap)
    print()
    print("=== READING ===")
    print("• Doctrine: first --ormin-min OR; break above OR-high + volume; stop just below the")
    print("  breakout bar; target = 2x OR measured move; hard time-exit; one breakout/day.")
    print("• If a DOCTRINE R:R band shows win% with winsorAvg/medR > 0 AND beats LIVE-PROXY,")
    print("  rewrite _check_orb gated to that band. Try --ormin 5/15/30 and --timeexit 630/690.")
    print("• If LIVE-PROXY is ~0/negative, the running-HOD/LOD 'range' is mislabeled -> rewrite.\n")


if __name__ == "__main__":
    main()
