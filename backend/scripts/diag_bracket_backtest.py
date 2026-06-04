#!/usr/bin/env python3
"""
diag_bracket_backtest.py  (READ-ONLY)
=====================================
Re-simulates every legit intraday/scalp bot trade under a NEW, intraday-
aware bracket and compares it to the OLD (daily-ATR-scaled) bracket — so we
PROVE the recalibration helps before changing any live logic.

NEW bracket per trade:
  • stop  = entry ∓ (--atr-mult × INTRADAY ATR)   (intraday 1-min ATR, not daily)
  • T1    = entry ± (--target-r  × new_risk)
  • time-stop at --timestop-min (exit at market if neither level hit)

Comparison metric = $ P&L per trade at a FIXED $ risk budget (--risk-budget).
This is the only apples-to-apples way to compare two bracket geometries:
a tighter stop buys more shares for the same $ risk, so capturing the same
% move yields more $. Also reports target-hit / stop-out / timeout %.

Mongo only. Run from repo root + venv:
  .venv/bin/python backend/scripts/diag_bracket_backtest.py --days 90 \\
      --atr-mult 1.25 --target-r 1.5 --timestop-min 40 --risk-budget 500
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

INTRADAY_STYLES = {"scalp", "intraday", "unknown"}
FLIP_HINTS = ("wrong_direction", "flip", "flipped")


def _bootstrap_path():
    for cand in (Path.cwd() / "backend", Path.cwd()):
        if (cand / "services" / "trade_style_classifier.py").exists():
            sys.path.insert(0, str(cand)); return
    try:
        here = Path(__file__).resolve().parents[1]
        if (here / "services" / "trade_style_classifier.py").exists():
            sys.path.insert(0, str(here))
    except NameError:
        pass


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)[os.environ["DB_NAME"]]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fetch_bars(db, symbol, start, end):
    """1-min bars in absolute-time [start, end]. tz-correct (day-prefix query
    then parse-and-filter — the `date` field has mixed tz across rows)."""
    pad_lo = (start.date() - timedelta(days=1)).isoformat()
    pad_hi = (end.date() + timedelta(days=1)).isoformat()
    cur = db["ib_historical_data"].find(
        {"symbol": symbol.upper(), "bar_size": "1 min",
         "date": {"$gte": pad_lo, "$lte": pad_hi + "T99"}},
        {"_id": 0, "date": 1, "high": 1, "low": 1, "close": 1}).sort("date", 1)
    out = []
    for b in cur:
        bt = _dt(b.get("date"))
        hi, lo, cl = _num(b.get("high")), _num(b.get("low")), _num(b.get("close"))
        if bt and hi is not None and lo is not None and cl is not None and start <= bt <= end:
            out.append((bt, hi, lo, cl))
    return out


def _intraday_atr(pre_bars, n=14):
    if not pre_bars:
        return None
    trs = [hi - lo for _, hi, lo, _ in pre_bars[-n:] if hi >= lo]
    return statistics.fmean(trs) if trs else None


def _sim(bars, entry, stop, target, is_long, entry_ts, timestop_min=None):
    """Walk bars; return (outcome, exit_price)."""
    if not bars:
        return None
    cutoff = entry_ts + timedelta(minutes=timestop_min) if timestop_min else None
    last = entry
    for bt, hi, lo, cl in bars:
        last = cl
        hit_t = (hi >= target) if is_long else (lo <= target)
        hit_s = (lo <= stop) if is_long else (hi >= stop)
        if hit_s:          # conservative: stop checked before target on same bar
            return ("stop", stop)
        if hit_t:
            return ("target", target)
        if cutoff and bt >= cutoff:
            return ("timestop", cl)
    return ("eod", last)


def _pnl(entry, stop, exit_px, is_long, risk_budget):
    rps = abs(entry - stop)
    if rps <= 0:
        return 0.0
    shares = risk_budget / rps
    return shares * (exit_px - entry) * (1 if is_long else -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--since", type=str, default=None)
    ap.add_argument("--atr-mult", type=float, default=1.25)
    ap.add_argument("--target-r", type=float, default=1.5)
    ap.add_argument("--timestop-min", type=int, default=40)
    ap.add_argument("--risk-budget", type=float, default=500.0)
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--max-trades", type=int, default=1500)
    args = ap.parse_args()
    _bootstrap_path(); _load_env()
    from services.trade_style_classifier import resolve_trade_style
    db = _db()
    floor = args.since or (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"\n{'#'*116}\n#  BRACKET BACKTEST: OLD (daily-ATR) vs NEW (intraday-ATR)   since={floor}")
    print(f"#  NEW = stop {args.atr_mult}× intraday-ATR | T1 {args.target_r}R | time-stop "
          f"{args.timestop_min}m | risk-budget ${args.risk_budget:.0f}/trade\n{'#'*116}")

    proj = {"_id": 0, "symbol": 1, "setup_type": 1, "trade_style": 1, "timeframe": 1,
            "direction": 1, "entered_by": 1, "entry_price": 1, "fill_price": 1,
            "stop_price": 1, "stop_loss": 1, "target_price": 1, "target_prices": 1,
            "close_reason": 1, "executed_at": 1, "entry_time": 1, "closed_at": 1,
            "exit_time": 1, "learning_only": 1, "entry_context": 1}
    raw = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": floor}}, proj).limit(args.max_trades * 3))

    agg = defaultdict(lambda: defaultdict(list))
    n_legit = no_bars = no_atr = done = 0
    for t in raw:
        if t.get("learning_only") is True or (t.get("entry_context") or {}).get("learning_only") is True:
            continue
        if str(t.get("entered_by") or "").lower() != "bot_fired":
            continue
        if any(h in str(t.get("close_reason") or "").lower() for h in FLIP_HINTS):
            continue
        entry = _num(t.get("entry_price")) or _num(t.get("fill_price"))
        stop = _num(t.get("stop_price")) or _num(t.get("stop_loss"))
        tps = t.get("target_prices") if isinstance(t.get("target_prices"), list) else None
        tgt = _num(tps[0]) if tps else _num(t.get("target_price"))
        ets = _dt(t.get("executed_at") or t.get("entry_time"))
        cts = _dt(t.get("closed_at") or t.get("exit_time"))
        if not (entry and stop and tgt and ets and cts) or entry <= 0:
            continue
        style = resolve_trade_style(t)
        if style not in INTRADAY_STYLES:
            continue          # backtest targets intraday/scalp brackets only
        n_legit += 1
        if done >= args.max_trades:
            continue
        is_long = str(getattr(t.get("direction"), "value", t.get("direction")) or "long").lower() != "short"
        eod = ets.replace(hour=20, minute=0, second=0, microsecond=0)
        allbars = _fetch_bars(db, t["symbol"], ets - timedelta(minutes=40), max(cts, eod))
        if not allbars:
            no_bars += 1; continue
        pre = [b for b in allbars if b[0] < ets]
        post = [b for b in allbars if b[0] >= ets]
        if not post:
            no_bars += 1; continue
        iatr = _intraday_atr(pre)
        if not iatr or iatr <= 0:
            no_atr += 1; continue

        # OLD bracket: recorded stop/target, walk to EOD (no time-stop)
        old_oc, old_exit = _sim(post, entry, stop, tgt, is_long, ets, timestop_min=None)
        old_pnl = _pnl(entry, stop, old_exit, is_long, args.risk_budget)

        # NEW bracket: intraday-ATR stop, T1 at target_r×new_risk, time-stop
        new_risk = args.atr_mult * iatr
        new_stop = entry - new_risk if is_long else entry + new_risk
        new_tgt = entry + args.target_r * new_risk if is_long else entry - args.target_r * new_risk
        new_oc, new_exit = _sim(post, entry, new_stop, new_tgt, is_long, ets,
                                timestop_min=args.timestop_min)
        new_pnl = _pnl(entry, new_stop, new_exit, is_long, args.risk_budget)

        key = (style, t.get("setup_type") or "?")
        a = agg[key]
        a["old_pnl"].append(old_pnl); a["new_pnl"].append(new_pnl)
        a["old_oc"].append(old_oc); a["new_oc"].append(new_oc)
        done += 1
    print(f"\nlegit intraday/scalp trades: {n_legit}   simulated: {done}   "
          f"(no bars: {no_bars}, no intraday ATR: {no_atr})\n")

    def rate(lst, val):
        return 100.0 * lst.count(val) / len(lst) if lst else 0.0

    print(f"{'style/setup':<28}{'n':>4} | {'OLD $/t':>9}{'oHit%':>6}{'oStop%':>7}{'oTO%':>6}"
          f" | {'NEW $/t':>9}{'nHit%':>6}{'nStop%':>7}{'nTS%':>6} | {'Δ$/t':>9}")
    print("-" * 116)
    tot_old = tot_new = 0.0
    rows = []
    for (style, setup), a in agg.items():
        n = len(a["old_pnl"])
        if n < 3:
            continue
        o = statistics.fmean(a["old_pnl"]); nw = statistics.fmean(a["new_pnl"])
        rows.append((n, style, setup, o, nw,
                     rate(a["old_oc"], "target"), rate(a["old_oc"], "stop"),
                     rate(a["old_oc"], "eod") + rate(a["old_oc"], "timestop"),
                     rate(a["new_oc"], "target"), rate(a["new_oc"], "stop"),
                     rate(a["new_oc"], "timestop")))
        tot_old += sum(a["old_pnl"]); tot_new += sum(a["new_pnl"])
    for n, style, setup, o, nw, oh, os_, oto, nh, ns, nts in sorted(rows, key=lambda x: -x[0]):
        flag = "  ✅" if nw > o + 1 else ("  ⚠️" if nw < o - 1 else "")
        print(f"{(style+'/'+setup)[:27]:<28}{n:>4} | {o:>9.1f}{oh:>6.0f}{os_:>7.0f}{oto:>6.0f}"
              f" | {nw:>9.1f}{nh:>6.0f}{ns:>7.0f}{nts:>6.0f} | {nw-o:>+9.1f}{flag}")
    print("-" * 116)
    print(f"{'TOTAL (sum $)':<28}{'':>4} | {tot_old:>9.0f}{'':>19} | {tot_new:>9.0f}{'':>19} | {tot_new-tot_old:>+9.0f}")

    print(f"\n{'='*116}\nHOW TO READ\n{'='*116}")
    print("• $/t = MEAN $ P&L per trade at a fixed $ risk budget (apples-to-apples across geometries).")
    print("• OLD = recorded daily-ATR bracket, held to EOD. NEW = intraday-ATR stop + tight T1 + time-stop.")
    print("• Δ$/t > 0 (✅) → the recalibrated bracket would have made more $ per trade on REAL price paths.")
    print("• Tune --atr-mult / --target-r / --timestop-min to find the best config before we implement it.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
