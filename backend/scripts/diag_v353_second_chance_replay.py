#!/usr/bin/env python3
"""
v353 — SECOND CHANCE SCALP (cheat-sheet-faithful) REPLAY  (READ-ONLY).

WHY: the shipped live `_check_second_chance` is NOT the SMB "2nd Chance Scalp".
  LIVE  : fires when price is within 0.5% ABOVE VWAP, trend==uptrend, rvol>=1.2.
          trigger=VWAP, stop=VWAP-0.5*ATR, target=HIGH_OF_DAY, R:R hard-coded 2.0.
          -> this is a generic "near-VWAP momentum" filter, NOT a resistance retest.
  DOCTRINE (per SMB the_second_chance_scalp cheat sheet):
     1) a RESISTANCE level breaks with a strong, high-VOLUME move (rush out of range),
     2) price PULLS BACK and RETESTS the broken level on LOW volume
        (old resistance must hold as NEW support; do NOT fall back into range),
     3) ENTER on a confirmation candle that closes ABOVE the prior candle (buyers return),
     4) STOP = .02 below the LOW OF THE TURN CANDLE (new support),
     5) TARGET(1/2) = the HIGH OF THE INITIAL PULLBACK (the rush high that set up the scalp),
        trail the rest on a 1-min close below the 9-EMA,
     6) ~1.9:1 R:R, 50-55% win, all-day RTH (09:59-16:00 ET),
     7) AVOID if it breaks back into range and does not recover the next candle;
        AVOID if the breakout move is taller than the prior range; max 2 attempts/day.

This script replays IB 1-min bars and scores TWO arms so we can prove the gap:
  • LIVE-PROXY : the shipped near-VWAP rule (stop=VWAP-0.5*ATR, target=running HOD).
  • DOCTRINE   : the resistance break -> low-vol retest -> confirm model above.
Reports n, win%, winsorized avg R, median R, total winsorized R, avg R:R taken, and
R:R buckets for each arm.  NOTHING IS WRITTEN.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v353_second_chance_replay.py \
     --days 14 --reslook 15 --rushwin 6 --rettest 4 --rettol 0.20 --supporttol 0.15 \
     --minbreak 0.10 --volmult 1.3 --maxbreakmult 1.0 --minrr 1.5 --maxhold 30 \
     --maxattempts 2 --universe 300 --winsor 3.0 --timewin 1
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


def _in_window(et):
    # cheat-sheet ideal windows span 09:59 -> 16:00 ET (all RTH after the first 29 min)
    if et is None:
        return False
    m = et.hour * 60 + et.minute
    return (9 * 60 + 59) <= m <= (16 * 60)


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
    """Simple rolling mean of true range (Wilder-free, matches the live ATR proxy)."""
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
    """Bar-by-bar: stop first (conservative), else target, else mark-to-close."""
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
    reslook = _arg("--reslook", 15, int)        # consolidation lookback (resistance window)
    rushwin = _arg("--rushwin", 6, int)         # bars over which the rush high is measured
    rettest = _arg("--rettest", 4, int)         # bars over which the retest/turn low is measured
    rettol = _arg("--rettol", 0.20, float)      # retest must come within rettol% of broken level
    supporttol = _arg("--supporttol", 0.15, float)  # turn low may dip <= supporttol% below level
    minbreak = _arg("--minbreak", 0.10, float)  # rush must clear resistance by >= minbreak%
    volmult = _arg("--volmult", 1.3, float)     # break-vol vs consolidation median-vol
    maxbreakmult = _arg("--maxbreakmult", 1.0, float)  # rush height <= mult * prior range height (0=off)
    minrr = _arg("--minrr", 1.5, float)
    maxhold = _arg("--maxhold", 30, int)
    maxattempts = _arg("--maxattempts", 2, int)  # cheat-sheet "2 strikes and we're out"
    uni_cap = _arg("--universe", 300, int)
    cap = _arg("--winsor", 3.0, float)
    timewin = _arg("--timewin", 1, int)

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc)

    print(f"\n=== v353 SECOND CHANCE replay — {days}d  reslook={reslook}  rush={rushwin}  "
          f"retest={rettest}  rettol={rettol:g}%  minbreak={minbreak:g}%  volmult={volmult:g}  "
          f"maxbreakmult={maxbreakmult:g}  minRR={minrr:g}  "
          f"timewin={'09:59-16:00' if timewin else 'off'}  winsor=±{cap:g}R ===\n")

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
            need = reslook + rushwin + rettest + 3
            if len(bars) < max(need, EMA_LEN + 3):
                continue
            bars.sort(key=lambda x: x["date"])
            ema = _ema(bars, EMA_LEN)
            vwap = _vwaps(bars)
            atr = _atrs(bars, ATR_LEN)
            hod = []
            running = None
            for b in bars:
                running = b["high"] if running is None else max(running, b["high"])
                hod.append(running)

            doc_fired = 0
            live_fired = 0
            for i in range(need, len(bars)):
                b = bars[i]
                et = _to_et(b.get("date"))
                if timewin and not _in_window(et):
                    continue
                h, l, c, o = b["high"], b["low"], b["close"], b["open"]
                vw, em = vwap[i], ema[i]

                # ---------- DOCTRINE arm ----------
                if doc_fired < maxattempts:
                    # consolidation / resistance window BEFORE the rush
                    cs0, cs1 = i - reslook - rushwin, i - rushwin
                    cons = bars[cs0:cs1]
                    rush = bars[i - rushwin:i]            # rush + pullback region
                    ret = bars[i - rettest:i]             # retest / turn region (excl. entry bar)
                    if cons and rush and ret:
                        resistance = max(x["high"] for x in cons)
                        cons_lo = min(x["low"] for x in cons)
                        prior_range = resistance - cons_lo
                        rush_high = max(x["high"] for x in rush)
                        turn_bar = min(ret, key=lambda x: x["low"])
                        turn_low = turn_bar["low"]
                        med_vol = median([x.get("volume") or 0 for x in cons]) or 0.0
                        break_vol = max(x.get("volume") or 0 for x in rush)
                        retest_vol = min(x.get("volume") or 0 for x in ret)

                        broke = rush_high >= resistance * (1 + minbreak / 100.0)
                        # retest held: turn low near broken level, did NOT fall back into range
                        near = turn_low <= resistance * (1 + rettol / 100.0)
                        held = turn_low >= resistance * (1 - supporttol / 100.0)
                        vol_ok = (med_vol <= 0) or (break_vol >= volmult * med_vol and retest_vol < break_vol)
                        confirm = (c > o) and (c > bars[i - 1]["high"])  # closes above prior candle
                        not_too_tall = (maxbreakmult <= 0) or (prior_range <= 0) or \
                                       ((rush_high - resistance) <= maxbreakmult * prior_range)

                        if broke and near and held and vol_ok and confirm and not_too_tall:
                            n_doc_ev += 1
                            entry = c
                            stop = turn_low - 0.02
                            target = rush_high
                            risk = entry - stop
                            if risk > 0 and target > entry:
                                rr = (target - entry) / risk
                                if rr >= minrr:
                                    r = _sim_exit(bars, i, entry, stop, target, rr, maxhold)
                                    if r is not None:
                                        n_doc_tr += 1; doc_fired += 1
                                        doc_r.append(r); doc_rr.append(rr)
                                        doc_by_rr[_rr_bucket(rr)].append(r)

                # ---------- LIVE-PROXY arm (shipped near-VWAP rule) ----------
                if live_fired < maxattempts and vw and vw > 0:
                    dist = (c - vw) / vw * 100.0
                    uptrend = (i >= 5 and vw > vwap[i - 5] and c > em)
                    rvol_ok = volmult <= 0 or ((b.get("volume") or 0) >= 1.2 * (median(
                        [x.get("volume") or 0 for x in bars[max(0, i - 20):i]]) or 0))
                    if 0 < dist <= 0.5 and c > vw and uptrend and rvol_ok:
                        entry = c
                        stop = vw - 0.5 * atr[i]
                        target = hod[i]                     # live uses high_of_day
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
    print("SECOND CHANCE — LIVE (near-VWAP, stop=VWAP-0.5ATR, target=HOD) vs DOCTRINE")
    print("=" * 78)
    _report("LIVE-PROXY", live_r, live_rr, cap)
    _report("DOCTRINE ALL", doc_r, doc_rr, cap)
    for k in ("<1.0", "1.0-1.5", "1.5-2.5", ">=2.5"):
        _report("  DOC RR " + k, doc_by_rr.get(k, []),
                [rr for rr in doc_rr if _rr_bucket(rr) == k], cap)
    print()
    print("=== READING ===")
    print("• Cheat sheet claims ~1.9:1 R:R & 50-55% win. If DOCTRINE win% is in/above that band")
    print("  AND winsorAvg/medR > 0 AND it beats LIVE-PROXY -> rewrite _check_second_chance (v353 patch).")
    print("• If LIVE-PROXY is ~0/negative edge, the shipped VWAP rule is mislabeled momentum, not a")
    print("  resistance retest -> doctrine rewrite is justified (target=rush-high, stop=turn-low-.02).")
    print("• If DOCTRINE n is tiny, loosen --rettol/--supporttol/--minbreak or drop --volmult to 0.")
    print("• If RR<1.0 bucket dominates & is negative, raise --minrr toward 1.9 (doctrine R:R).\n")


if __name__ == "__main__":
    main()
