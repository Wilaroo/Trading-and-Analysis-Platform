#!/usr/bin/env python3
"""
v356 — DAILY BREAKOUT (swing) REPLAY  (READ-ONLY).

LIVE _check_daily_breakout: long when today's close breaks the 20-day high by 0.5-8%% on
  adaptive volume (rvol >= 1.5/1.3/1.2 by ATR%%); stop = prev_high - 0.5*ATR; target =
  entry + 2*(entry-stop); R:R NOT gated (fires on any breakout+volume). Multi-day hold.
  It is the MOST auto-executed setup (~15x/day), so its edge matters most.

This replays IB DAILY bars with the exact live logic and a multi-day exit, and reports
win%%, winsorized avg R, median R, total R, avg R:R, and R:R buckets so we can see whether
the live config is +EV and whether an R:R gate / parameter change improves it. NOTHING WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v356_daily_breakout_replay.py \
     --days 180 --barsize "1 day" --lookback 20 --minbreak 0.5 --maxbreak 8 \
     --maxhold 10 --minrr 0 --maxrr 0 --cooldown 3 --universe 400 --winsor 3.0
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median, mean


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


def _atr(highs, lows, closes, i, n=14):
    trs = []
    for k in range(max(1, i - n + 1), i + 1):
        trs.append(max(highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1])))
    return (sum(trs) / len(trs)) if trs else 0.0


def _rr_bucket(rr):
    if rr < 1.0:
        return "<1.0"
    if rr < 1.5:
        return "1.0-1.5"
    if rr < 2.5:
        return "1.5-2.5"
    return ">=2.5"


def _report(label, rs, rrs, cap):
    if not rs:
        print(f"  {label:<16} n=0"); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f"  {label:<16} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  "
          f"medR={median(rs):+.3f}  totW={sum(wr):+.1f}  avgRR={mean(rrs) if rrs else 0:.2f}")


def main():
    days = _arg("--days", 180, int)
    barsize = sys.argv[sys.argv.index("--barsize") + 1] if "--barsize" in sys.argv else "1 day"
    lookback = _arg("--lookback", 20, int)
    minbreak = _arg("--minbreak", 0.5, float)
    maxbreak = _arg("--maxbreak", 8.0, float)
    maxhold = _arg("--maxhold", 10, int)
    minrr = _arg("--minrr", 0.0, float)
    maxrr = _arg("--maxrr", 0.0, float)
    cooldown = _arg("--cooldown", 3, int)   # min days between entries per symbol
    uni_cap = _arg("--universe", 400, int)
    cap = _arg("--winsor", 3.0, float)

    db = _load_db()
    start = datetime.now(timezone.utc) - timedelta(days=days)

    universe = Counter()
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1}):
        if a.get("symbol"):
            universe[a["symbol"]] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    _maxrr = f"{maxrr:g}" if maxrr > 0 else "off"
    print(f"\n=== v356 DAILY BREAKOUT replay — {days}d  bar='{barsize}'  lookback={lookback}  "
          f"break={minbreak:g}-{maxbreak:g}%  hold={maxhold}d  minRR={minrr:g}  maxRR={_maxrr}  "
          f"cooldown={cooldown}d  winsor=±{cap:g}R ===")
    print(f"universe: {len(syms)} symbols\n")

    rs, rrs = [], []
    by_rr = defaultdict(list)
    n_ev = 0
    for sym in syms:
        cur = db.ib_historical_data.find(
            {"symbol": sym, "bar_size": barsize},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}).sort("date", 1)
        bars = [b for b in cur if b.get("close") and b.get("high") and b.get("low")]
        if len(bars) < lookback + 5:
            continue
        highs = [b["high"] for b in bars]; lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]; vols = [b.get("volume") or 0 for b in bars]
        last_entry = -999
        for i in range(lookback, len(bars) - 1):
            if i - last_entry < cooldown:
                continue
            prev_high = max(highs[i - lookback:i])
            if prev_high <= 0:
                continue
            current = closes[i]
            bp = (current - prev_high) / prev_high * 100
            if bp < minbreak or bp > maxbreak:
                continue
            avg_vol = sum(vols[i - lookback:i]) / lookback
            atr = _atr(highs, lows, closes, i, 14)
            atr_pct = (atr / current * 100) if current > 0 else 2
            vth = 1.5 if atr_pct < 2 else 1.3 if atr_pct < 4 else 1.2
            rvol = (vols[i] / avg_vol) if avg_vol > 0 else 0
            if rvol < vth:
                continue
            stop = prev_high - atr * 0.5
            risk = current - stop
            if risk <= 0:
                continue
            target = current + 2 * risk
            rr = (target - current) / risk
            if minrr > 0 and rr < minrr:
                continue
            if maxrr > 0 and rr > maxrr:
                continue
            n_ev += 1; last_entry = i
            # multi-day exit
            r = None
            end = min(i + maxhold, len(bars) - 1)
            for j in range(i + 1, end + 1):
                if lows[j] <= stop:
                    r = -1.0; break
                if highs[j] >= target:
                    r = rr; break
            if r is None:
                r = round((closes[end] - current) / risk, 3)
            rs.append(r); rrs.append(rr); by_rr[_rr_bucket(rr)].append(r)

    print(f"DAILY BREAKOUT events={n_ev}\n")
    print("=" * 78)
    _report("LIVE (as-is)", rs, rrs, cap)
    for k in ("<1.0", "1.0-1.5", "1.5-2.5", ">=2.5"):
        _report("  RR " + k, by_rr.get(k, []),
                [rr for rr in rrs if _rr_bucket(rr) == k], cap)
    print()
    print("=== READING ===")
    print("• LIVE fires on ANY 20-day-high break + volume (no R:R gate). If winsorAvg/medR > 0")
    print("  overall -> setup is +EV as-is (keep). If negative overall but a R:R band is +EV ->")
    print("  add a gate (like ORB/second_chance). If negative everywhere -> tighten or suppress.")
    print("• Try --lookback 50, --minbreak 1.0, --maxhold 5/20, --cooldown 5 to refine.")
    print("• avg R:R ~2.0 by construction; buckets vary with how far prev_high stop sits.\n")


if __name__ == "__main__":
    main()
