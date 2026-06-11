#!/usr/bin/env python3
"""
scalp_exit_autopsy.py  (read-only)  — v322o
============================================
Answers: HOW are scalp/intraday trades actually exiting, and what is each
exit path costing/earning us? Feeds two upcoming builds:

  • M0 laddered scale-out — needs the realized-R distribution of TP exits
    (are we banking +1R singles or letting +2R runs go?).
  • v322p decay-timer rework — needs proof of whether `scalp_time_decay`
    closes are killing winners. For every decay exit we replay the NEXT
    --post-min minutes of 5-min bars from ib_historical_data and measure
    post-exit MFE/MAE in R: "had the timer not fired, what happened?"

Per exit bucket (TP / SL / DECAY / EOD / EXTERNAL / MANUAL / OTHER):
  n, win rate, total & avg P&L, avg realized R, avg hold minutes.
For DECAY exits additionally:
  % that ran >= +0.5R / +1R favorable post-exit (left on the table),
  % that would have hit the original stop first, median post-window move.

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:
  cd ~/Trading-and-Analysis-Platform && .venv/bin/python backend/scripts/scalp_exit_autopsy.py --days 14
  Options: --days N (lookback, default 14) --post-min M (decay replay window, default 60)
"""
from __future__ import annotations
import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


HORIZONS = ("scalp", "intraday", "swing", "position", "investment")


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _dir(t):
    return str(_enum(t.get("direction")) or "long").lower()


def _dt(v):
    """Parse an ISO string / datetime into an aware UTC datetime (or None)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def classify_exit(t) -> str:
    r = (t.get("close_reason") or "").lower()
    if "scalp_time_decay" in r or "decay" in r:
        return "DECAY"
    if "target" in r or "take_profit" in r or r.startswith("tp"):
        return "TP"
    if "stop" in r and "stale" not in r:
        return "SL"
    if "eod" in r:
        return "EOD"
    if "oca_closed_externally" in r or "external" in r:
        return "EXTERNAL"
    if "manual" in r or "operator" in r or "flatten" in r:
        return "MANUAL"
    return "OTHER"


def external_subclass(t):
    """v322o-2 — OCA bracket exits land as `oca_closed_externally` with no
    exit_price. Reconstruct exit = entry ± realized/shares and classify by
    realized-R magnitude + proximity: which bracket leg actually fired?
      EXT_TP      realized >= +0.5R and exit nearer target than stop
      EXT_SL      realized <= -0.5R and exit nearer stop than target
      EXT_SCRATCH |realized| < 0.5R (BE-ish stop, tight unwind, partial)
      None        fields missing — unclassifiable
    """
    entry = _f(t.get("entry_price")) or _f(t.get("fill_price"))
    stop = _f(t.get("stop_price")) or _f(t.get("stop_loss"))
    tps = t.get("target_prices") or []
    tgt = _f(tps[0]) if tps else (_f(t.get("tp_price")) or _f(t.get("target")))
    realized = _f(t.get("realized_pnl")) or _f(t.get("net_pnl"))
    shares = _f(t.get("shares"))
    if entry <= 0 or stop <= 0 or shares <= 0:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    rr = (realized / shares) / risk
    if abs(rr) < 0.5:
        return "EXT_SCRATCH"
    if tgt > 0:
        pps = realized / shares
        exit_px = entry + pps if _dir(t) == "long" else entry - pps
        near_target = abs(exit_px - tgt) <= abs(exit_px - stop)
        if rr > 0 and near_target:
            return "EXT_TP"
        if rr < 0 and not near_target:
            return "EXT_SL"
    return "EXT_TP" if rr > 0 else "EXT_SL"


def realized_r_signed(t):
    """Realized R: per-share pnl / per-share risk. pnl is already signed
    correctly for direction (realized_pnl is dollar P&L), so no flip needed."""
    entry = _f(t.get("entry_price")) or _f(t.get("fill_price"))
    stop = _f(t.get("stop_price")) or _f(t.get("stop_loss"))
    realized = _f(t.get("realized_pnl")) or _f(t.get("net_pnl"))
    shares = _f(t.get("shares"))
    if entry <= 0 or stop <= 0 or shares <= 0:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return (realized / shares) / risk


def hold_minutes(t):
    a = _dt(t.get("executed_at") or t.get("created_at"))
    b = _dt(t.get("closed_at"))
    if not a or not b:
        return None
    m = (b - a).total_seconds() / 60.0
    return m if 0 <= m <= 7 * 24 * 60 else None


def decay_replay(db, t, post_min: int):
    """Replay post-exit 5-min bars. Returns dict with post-exit MFE/MAE in R
    (favorable = in the trade's direction) and whether the original stop
    would have been tagged first. None when bars/fields are missing."""
    entry = _f(t.get("entry_price")) or _f(t.get("fill_price"))
    stop = _f(t.get("stop_price")) or _f(t.get("stop_loss"))
    closed_at = _dt(t.get("closed_at"))
    if entry <= 0 or stop <= 0 or not closed_at:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    d = _dir(t)
    # Reconstruct exit price from realized pnl (exit_price is rarely persisted).
    realized = _f(t.get("realized_pnl")) or _f(t.get("net_pnl"))
    shares = _f(t.get("shares"))
    if shares <= 0:
        return None
    pps = realized / shares
    exit_px = entry + pps if d == "long" else entry - pps

    end = closed_at + timedelta(minutes=post_min)
    bars = list(db["ib_historical_data"].find(
        {"symbol": t.get("symbol"), "bar_size": "5 mins",
         "date": {"$gte": closed_at.isoformat(), "$lte": end.isoformat()}},
        {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1},
    ).sort("date", 1))
    if not bars:
        return None

    mfe = 0.0   # best favorable excursion past the exit, in R
    mae = 0.0   # worst adverse excursion past the exit, in R
    stop_first = False
    for b in bars:
        hi, lo = _f(b.get("high")), _f(b.get("low"))
        if hi <= 0 or lo <= 0:
            continue
        if d == "long":
            fav = (hi - exit_px) / risk
            adv = (lo - exit_px) / risk
            hit_stop = lo <= stop
        else:
            fav = (exit_px - lo) / risk
            adv = (exit_px - hi) / risk
            hit_stop = hi >= stop
        if hit_stop and mfe < 0.25:
            # Stop would have been tagged before any meaningful run.
            stop_first = True
        mfe = max(mfe, fav)
        mae = min(mae, adv)
    last_close = _f(bars[-1].get("close"))
    end_move = ((last_close - exit_px) / risk) if d == "long" else ((exit_px - last_close) / risk)
    return {"mfe_r": mfe, "mae_r": mae, "stop_first": stop_first,
            "end_move_r": end_move, "n_bars": len(bars)}


def _fmt(v, spec="+.2f", na="   n/a"):
    return format(v, spec) if v is not None else na


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--post-min", type=int, default=60,
                    help="post-exit replay window for decay exits (minutes)")
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}, "status": {"$in": ["closed", "CLOSED"]}},
        {"_id": 0, "symbol": 1, "timeframe": 1, "trade_type": 1, "scan_tier": 1,
         "close_reason": 1, "net_pnl": 1, "realized_pnl": 1, "entry_price": 1,
         "fill_price": 1, "stop_price": 1, "stop_loss": 1, "target_prices": 1,
         "shares": 1, "direction": 1, "executed_at": 1, "created_at": 1,
         "closed_at": 1},
    )
    rows = [t for t in cur if horizon(t) in ("scalp", "intraday")]

    print("\n" + "=" * 76)
    print(f"SCALP/INTRADAY EXIT AUTOPSY — last {args.days}d — {len(rows)} closed trades")
    print("=" * 76)
    if not rows:
        print("No closed scalp/intraday trades in window.")
        return

    buckets = defaultdict(list)
    for t in rows:
        buckets[classify_exit(t)].append(t)

    print(f"\n{'EXIT':<10} {'n':>4} {'win%':>5} {'totPnL':>10} {'avgPnL':>8} "
          f"{'avgR':>6} {'medR':>6} {'avgHold':>8}")
    print("-" * 64)
    for k in ("TP", "SL", "DECAY", "EOD", "EXTERNAL", "MANUAL", "OTHER"):
        sub = buckets.get(k, [])
        if not sub:
            continue
        n = len(sub)
        pnls = [(_f(t.get("realized_pnl")) or _f(t.get("net_pnl"))) for t in sub]
        wins = sum(1 for p in pnls if p > 0)
        rs = [r for r in (realized_r_signed(t) for t in sub) if r is not None]
        holds = [h for h in (hold_minutes(t) for t in sub) if h is not None]
        print(f"{k:<10} {n:>4} {wins / n * 100:>4.0f}% {sum(pnls):>+10.0f} "
              f"{sum(pnls) / n:>+8.0f} "
              f"{_fmt(statistics.mean(rs) if rs else None, '+6.2f'):>6} "
              f"{_fmt(statistics.median(rs) if rs else None, '+6.2f'):>6} "
              f"{_fmt(statistics.mean(holds) if holds else None, '7.0f', '    n/a'):>7}m")

    # ── EXTERNAL sub-classification (which OCA leg actually fired?) ─────
    ext = buckets.get("EXTERNAL", [])
    if ext:
        subs = defaultdict(list)
        for t in ext:
            subs[external_subclass(t) or "EXT_UNKNOWN"].append(t)
        print(f"\nEXTERNAL ({len(ext)}) — reconstructed leg attribution "
              f"[no exit_price persisted; exit = entry ± pnl/shares]:")
        for k in ("EXT_TP", "EXT_SL", "EXT_SCRATCH", "EXT_UNKNOWN"):
            sub = subs.get(k, [])
            if not sub:
                continue
            n = len(sub)
            pnls = [(_f(t.get("realized_pnl")) or _f(t.get("net_pnl"))) for t in sub]
            rs = [r for r in (realized_r_signed(t) for t in sub) if r is not None]
            print(f"   {k:<12} {n:>4} ({n / len(ext) * 100:3.0f}%)  totPnL {sum(pnls):>+8.0f}  "
                  f"avgR {_fmt(statistics.mean(rs) if rs else None, '+.2f')}  "
                  f"medR {_fmt(statistics.median(rs) if rs else None, '+.2f')}")
        # Realized-R histogram across ALL externals (M0 ladder shape input).
        ext_rs = [r for r in (realized_r_signed(t) for t in ext) if r is not None]
        if ext_rs:
            print(f"   realized-R histogram (n={len(ext_rs)}):")
            for lab, lo, hi in (("<=-1R", -99, -1.0), ("-1..-0.5R", -1.0, -0.5),
                                ("-0.5..-0.25R", -0.5, -0.25), ("scratch ±0.25R", -0.25, 0.25),
                                ("+0.25..0.5R", 0.25, 0.5), ("+0.5..1R", 0.5, 1.0),
                                ("+1..2R", 1.0, 2.0), (">=+2R", 2.0, 99)):
                c = sum(1 for r in ext_rs if lo <= r < hi)
                if c:
                    print(f"      {lab:<16} {c:>4} ({c / len(ext_rs) * 100:3.0f}%)")

    # ── TP realized-R distribution (M0 ladder input) ─────────────────────
    tp_rs = [r for r in (realized_r_signed(t) for t in buckets.get("TP", []))
             if r is not None]
    if tp_rs:
        print(f"\nTP exits — realized-R distribution (n={len(tp_rs)}) "
              f"[M0 ladder input]:")
        for lab, lo, hi in ((" <+0.5R", -99, 0.5), ("+0.5..1R", 0.5, 1.0),
                            ("+1..1.5R", 1.0, 1.5), ("+1.5..2R", 1.5, 2.0),
                            ("  >=+2R", 2.0, 99)):
            c = sum(1 for r in tp_rs if lo <= r < hi)
            if c:
                print(f"   {lab:<10} {c:>4} ({c / len(tp_rs) * 100:3.0f}%)")

    # ── DECAY post-exit replay (v322p input) ─────────────────────────────
    decays = buckets.get("DECAY", [])
    if decays:
        print(f"\nDECAY exits — post-exit replay, next {args.post_min}min of 5-min bars "
              f"(n={len(decays)}) [v322p input]:")
        replays = []
        for t in decays:
            r = decay_replay(db, t, args.post_min)
            if r is not None:
                replays.append((t, r))
        if not replays:
            print("   no replayable decay exits (missing bars or stop/entry fields).")
        else:
            n = len(replays)
            ran_05 = sum(1 for _, r in replays if r["mfe_r"] >= 0.5 and not r["stop_first"])
            ran_10 = sum(1 for _, r in replays if r["mfe_r"] >= 1.0 and not r["stop_first"])
            stopped = sum(1 for _, r in replays if r["stop_first"])
            end_moves = [r["end_move_r"] for _, r in replays]
            print(f"   replayable                {n:>4} / {len(decays)}")
            print(f"   would-have-hit-stop first {stopped:>4} ({stopped / n * 100:3.0f}%)  <- timer SAVED these")
            print(f"   ran >= +0.5R post-exit    {ran_05:>4} ({ran_05 / n * 100:3.0f}%)  <- left on the table")
            print(f"   ran >= +1.0R post-exit    {ran_10:>4} ({ran_10 / n * 100:3.0f}%)")
            print(f"   median end-of-window move {statistics.median(end_moves):+.2f}R")
            worst = sorted(replays, key=lambda x: -x[1]["mfe_r"])[:8]
            print("   biggest post-exit runners:")
            for t, r in worst:
                if r["mfe_r"] < 0.5:
                    break
                print(f"      {t.get('symbol'):<6} {_dir(t):<5} closed {str(t.get('closed_at'))[:16]} "
                      f"mfe {r['mfe_r']:+.2f}R  end {r['end_move_r']:+.2f}R"
                      f"{'  (stop-first)' if r['stop_first'] else ''}")

    # ── close_reason raw inventory (sanity) ──────────────────────────────
    inv = defaultdict(int)
    for t in rows:
        inv[(t.get("close_reason") or "(none)")[:48]] += 1
    print("\nclose_reason inventory:")
    for k, c in sorted(inv.items(), key=lambda x: -x[1]):
        print(f"   {c:>5}  {k}")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
