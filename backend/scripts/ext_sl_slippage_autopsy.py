#!/usr/bin/env python3
"""
ext_sl_slippage_autopsy.py  (read-only)  — EXT_SL -1.62R probe
===============================================================
The Scalp Exit Autopsy showed stop exits averaging ≈ -1.62R against a
designed -1.0R. This script decomposes WHERE the extra ~0.6R is bleeding:

  • per-trade excess loss   excess_R = realized_R − (−1.0)
  • slippage in price       slip = how far past the stop the fill landed
                            (exit reconstructed as entry ± pnl/shares since
                            exit_price is rarely persisted)
  • gap-through detection   replay 5-min bars around the exit from
                            ib_historical_data: if the bar that crossed the
                            stop OPENED beyond it → gap (unavoidable);
                            else traded-through → execution slippage
  • buckets                 time-of-day (half-hours), hold time, symbol
                            leaderboard, designed-risk size (tight stops
                            slip proportionally more)

Includes BOTH bot-recorded stop exits (close_reason contains "stop") and
external OCA stop fills (realized ≤ −0.5R, exit nearer stop than target).

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:
  cd ~/Trading-and-Analysis-Platform && .venv/bin/python backend/scripts/ext_sl_slippage_autopsy.py --days 14
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


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def trade_metrics(t):
    """Returns dict with entry, stop, risk, realized_r, exit_px, slip_px,
    slip_r, excess_r — or None when unreconstructable."""
    entry = _f(t.get("fill_price")) or _f(t.get("entry_price"))
    stop = _f(t.get("stop_price")) or _f(t.get("stop_loss"))
    shares = _f(t.get("shares"))
    realized = _f(t.get("realized_pnl"))
    if realized is None:
        realized = _f(t.get("net_pnl"))
    if not entry or not stop or not shares or realized is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    d = str(_enum(t.get("direction")) or "long").lower()
    pps = realized / shares
    exit_px = entry + pps if d == "long" else entry - pps
    rr = pps / risk
    # signed slip: positive = filled WORSE than the stop price
    slip_px = (stop - exit_px) if d == "long" else (exit_px - stop)
    return {
        "entry": entry, "stop": stop, "risk": risk, "shares": shares,
        "dir": d, "realized": realized, "realized_r": rr,
        "exit_px": exit_px, "slip_px": slip_px, "slip_r": slip_px / risk,
        "excess_r": rr - (-1.0),
    }


def is_stop_exit(t, m):
    reason = (t.get("close_reason") or "").lower()
    if "stop" in reason and "stale" not in reason:
        return True
    # external OCA: no reason — classify by realized-R + proximity
    if m["realized_r"] <= -0.5:
        tgts = [x for x in (t.get("target_prices") or []) if x]
        tgt = _f(tgts[0]) if tgts else None
        if tgt is None:
            return True
        return abs(m["exit_px"] - m["stop"]) < abs(m["exit_px"] - tgt)
    return False


def gap_check(db, t, m):
    """Replay 5-min bars [closed_at-45m, closed_at+5m]; find the first bar
    crossing the stop. Returns 'GAP' / 'TRADED' / None (no bars)."""
    closed = _dt(t.get("closed_at"))
    if closed is None:
        return None
    bars = list(db["ib_historical_data"].find(
        {"symbol": t.get("symbol"), "bar_size": "5 mins",
         "date": {"$gte": (closed - timedelta(minutes=45)).isoformat(),
                  "$lte": (closed + timedelta(minutes=5)).isoformat()}},
        {"_id": 0, "open": 1, "high": 1, "low": 1, "date": 1},
    ).sort("date", 1))
    for b in bars:
        o, hi, lo = _f(b.get("open"), 0), _f(b.get("high"), 0), _f(b.get("low"), 0)
        if o <= 0:
            continue
        if m["dir"] == "long" and lo <= m["stop"]:
            return "GAP" if o < m["stop"] else "TRADED"
        if m["dir"] == "short" and hi >= m["stop"]:
            return "GAP" if o > m["stop"] else "TRADED"
    return None


def _tod_bucket(t):
    dt = _dt(t.get("closed_at"))
    if dt is None:
        return "??"
    # ET = UTC-4 (June)
    et_h = (dt.hour - 4) % 24
    half = 0 if dt.minute < 30 else 30
    return f"{et_h:02d}:{half:02d}"


def _hold_min(t):
    a, b = _dt(t.get("executed_at") or t.get("created_at")), _dt(t.get("closed_at"))
    return (b - a).total_seconds() / 60 if a and b else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--top", type=int, default=12, help="worst-offender rows")
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}, "status": {"$in": ["closed", "CLOSED"]}},
        {"_id": 0, "id": 1, "symbol": 1, "timeframe": 1, "trade_type": 1,
         "scan_tier": 1, "close_reason": 1, "net_pnl": 1, "realized_pnl": 1,
         "entry_price": 1, "fill_price": 1, "stop_price": 1, "stop_loss": 1,
         "target_prices": 1, "shares": 1, "direction": 1, "executed_at": 1,
         "created_at": 1, "closed_at": 1},
    )
    rows = [t for t in cur if horizon(t) in ("scalp", "intraday")]
    sl = []
    for t in rows:
        m = trade_metrics(t)
        if m and is_stop_exit(t, m):
            m["gap"] = gap_check(db, t, m)
            m["tod"] = _tod_bucket(t)
            m["hold"] = _hold_min(t)
            m["sym"] = t.get("symbol")
            m["tid"] = (t.get("id") or "")[:8]
            m["reason"] = (t.get("close_reason") or "ext_oca")[:24]
            sl.append(m)

    print("\n" + "=" * 78)
    print(f"EXT_SL SLIPPAGE AUTOPSY — last {args.days}d — "
          f"{len(sl)} stop exits / {len(rows)} closed scalp+intraday")
    print("=" * 78)
    if not sl:
        print("No stop exits in window.")
        return

    rr = [m["realized_r"] for m in sl]
    ex = [m["excess_r"] for m in sl]
    sr = [m["slip_r"] for m in sl]
    print(f"\nrealized R   avg {_avg(rr):+.2f}   median {statistics.median(rr):+.2f}"
          f"   worst {min(rr):+.2f}")
    print(f"excess R     avg {_avg(ex):+.2f}  (0 = stop filled exactly at design)")
    print(f"slip (R)     avg {_avg(sr):+.2f}   median {statistics.median(sr):+.2f}"
          f"   >0.25R: {sum(1 for x in sr if x > 0.25)}/{len(sr)}")

    by_gap = defaultdict(list)
    for m in sl:
        by_gap[m["gap"] or "NO-BARS"].append(m)
    print("\n── gap-through vs traded-through ──")
    for k in ("GAP", "TRADED", "NO-BARS"):
        sub = by_gap.get(k, [])
        if not sub:
            continue
        print(f"  {k:8s} n={len(sub):3d}  avg realized {_avg([m['realized_r'] for m in sub]):+.2f}R"
              f"  avg slip {_avg([m['slip_r'] for m in sub]):+.2f}R")

    print("\n── by time of day (ET, close time) ──")
    by_tod = defaultdict(list)
    for m in sl:
        by_tod[m["tod"]].append(m)
    for k in sorted(by_tod):
        sub = by_tod[k]
        print(f"  {k}  n={len(sub):3d}  avg realized {_avg([m['realized_r'] for m in sub]):+.2f}R"
              f"  avg slip {_avg([m['slip_r'] for m in sub]):+.2f}R")

    print("\n── by designed risk size (stop distance as % of entry) ──")
    by_risk = defaultdict(list)
    for m in sl:
        pct = m["risk"] / m["entry"] * 100
        b = "<0.5%" if pct < 0.5 else "0.5-1%" if pct < 1 else "1-2%" if pct < 2 else ">2%"
        by_risk[b].append(m)
    for k in ("<0.5%", "0.5-1%", "1-2%", ">2%"):
        sub = by_risk.get(k, [])
        if not sub:
            continue
        print(f"  {k:7s} n={len(sub):3d}  avg realized {_avg([m['realized_r'] for m in sub]):+.2f}R"
              f"  avg slip {_avg([m['slip_r'] for m in sub]):+.2f}R")

    print(f"\n── worst {args.top} offenders ──")
    print(f"  {'sym':6s} {'tid':9s} {'rR':>6s} {'slipR':>6s} {'gap':7s} "
          f"{'hold':>6s} {'tod':5s} reason")
    for m in sorted(sl, key=lambda x: x["realized_r"])[: args.top]:
        hold = f"{m['hold']:.0f}m" if m["hold"] is not None else "?"
        print(f"  {m['sym']:6s} {m['tid']:9s} {m['realized_r']:+6.2f} "
              f"{m['slip_r']:+6.2f} {(m['gap'] or 'NO-BARS'):7s} {hold:>6s} "
              f"{m['tod']:5s} {m['reason']}")

    print("\nInterpretation guide:")
    print("  • GAP-dominated excess → structural (news/illiquid names at the")
    print("    stop): fix via entry filters/liquidity floor, not execution.")
    print("  • TRADED-through slip → STP triggering late / market-order")
    print("    queue cost: consider STP-LMT with offset, or tighter symbols.")
    print("  • <0.5% risk bucket slipping worst → stops too tight for spread;")
    print("    enforce a min stop distance vs ATR/spread.")


if __name__ == "__main__":
    main()
