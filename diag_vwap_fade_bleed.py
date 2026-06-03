#!/usr/bin/env python3
"""
diag_vwap_fade_bleed.py — read-only root-cause for the vwap_fade leak.

Clean-data picture (post-hygiene): genuine n=130, 14% win, -1.60R avg, -$28.5k.
An average LOSS worse than -1R is the tell — the protective stop is NOT capping
risk at 1R. This drills into WHY:

  1. Expectancy decomposition: avg WIN R vs avg LOSS R (a -1.60R *avg* with
     14% wins means losers are running well past the stop).
  2. STOP-OVERSHOOT: losers with realized R < -1.1 (stop blown through —
     slippage / gap / stop never fired). The core hypothesis.
  3. Exit-reason mix: are these stop_loss fills, or target/eod/manual?
  4. MFE before the loss (floored in v240): did the fade work then reverse, or
     was it wrong from the tick? (fade-into-strength vs late stop).
  5. Long vs short fade split, and time-of-day — is one side / one window the leak?

READ-ONLY.  .venv/bin/python /tmp/diag_vwap_fade_bleed.py [--days 120]
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean, median

from pymongo import MongoClient

sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from services.trade_outcome_hygiene import classify_close  # noqa: E402

SETUP = "vwap_fade"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _base(s):
    s = str(s or "").lower()
    for suf in ("_long", "_short"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


def _hold_s(t):
    a, b = t.get("executed_at") or t.get("created_at"), t.get("closed_at")
    if not a or not b:
        return None
    try:
        return (datetime.fromisoformat(str(b).replace("Z", "+00:00"))
                - datetime.fromisoformat(str(a).replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


def _entry_hour_et(t):
    a = t.get("executed_at") or t.get("created_at")
    if not a:
        return None
    try:
        dt = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        return (dt - timedelta(hours=4)).hour  # crude UTC->ET (EDT)
    except Exception:
        return None


def _r(t):
    entry = _f(t.get("fill_price") or t.get("entry_price"))
    stop = _f((t.get("protective_stop") or {}).get("original_stop")) or _f(t.get("stop_price"))
    ex = _f(t.get("exit_price"))
    d = str(t.get("direction") or t.get("side") or "long").lower()
    if entry <= 0 or ex <= 0:
        return None
    rps = abs(entry - stop) if stop > 0 else entry * 0.02
    if rps <= 0:
        rps = entry * 0.02
    move = (ex - entry) if d.startswith("l") else (entry - ex)
    return move / rps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")).get_database(
        os.environ.get("DB_NAME", "tradecommand"))
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    rows = []
    for t in db.bot_trades.find({"status": "closed", "closed_at": {"$gte": since}}, {"_id": 0}):
        if _base(t.get("setup_type") or t.get("setup_variant")) != SETUP:
            continue
        g, _ = classify_close(
            close_reason=t.get("close_reason"),
            entered_by=str(t.get("entered_by", "") or ""),
            entry_price=_f(t.get("fill_price") or t.get("entry_price")),
            exit_price=_f(t.get("exit_price")),
            net_pnl=_f(t.get("net_pnl") or t.get("realized_pnl")),
            hold_seconds=_hold_s(t),
            setup_type=str(t.get("setup_type") or ""),
        )
        if not g:
            continue
        r = _r(t)
        if r is None or abs(r) > 20:
            continue
        rows.append((t, r))

    print(f"\n{'='*74}\nvwap_fade bleed — genuine closes, last {args.days}d  (n={len(rows)})\n{'='*74}")
    if not rows:
        print("no genuine vwap_fade trades in window.")
        return

    rs = [r for _, r in rows]
    pnls = [_f(t.get("net_pnl") or t.get("realized_pnl")) for t, _ in rows]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    # 1. expectancy decomposition
    print("\n--- expectancy decomposition ---")
    print(f"  win rate     : {len(wins)/len(rs)*100:.0f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  avg WIN  R   : {mean(wins) if wins else 0:+.2f}R   (median {median(wins) if wins else 0:+.2f})")
    print(f"  avg LOSS R   : {mean(losses) if losses else 0:+.2f}R   (median {median(losses) if losses else 0:+.2f})")
    print(f"  avg R (all)  : {mean(rs):+.2f}R     total net P&L: ${sum(pnls):+,.0f}")
    if wins and losses:
        be_wr = abs(mean(losses)) / (abs(mean(losses)) + mean(wins)) * 100
        print(f"  breakeven WR needed at this win/loss size: {be_wr:.0f}%  (actual {len(wins)/len(rs)*100:.0f}%)")

    # 2. STOP-OVERSHOOT (the core hypothesis)
    overshoot = [(t, r) for t, r in rows if r < -1.1]
    print("\n--- STOP-OVERSHOOT (realized R < -1.1 = stop blown through) ---")
    print(f"  {len(overshoot)}/{len(rows)} losers ran PAST the 1R stop "
          f"({len(overshoot)/len(rows)*100:.0f}% of all trades)")
    if overshoot:
        print(f"  avg overshoot R : {mean([r for _, r in overshoot]):+.2f}R")
        worst = sorted(overshoot, key=lambda x: x[1])[:10]
        for t, r in worst:
            mae = _f(t.get('mae_r'))
            print(f"    {t.get('symbol',''):<6} {str(t.get('side') or t.get('direction','')):<6}"
                  f" R={r:+.2f}  mae_r={mae:+.2f}  reason={t.get('close_reason','')}")

    # 3. exit-reason mix
    print("\n--- exit-reason mix (count · avg R) ---")
    by = defaultdict(list)
    for t, r in rows:
        by[t.get("close_reason", "?")].append(r)
    for reason, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason:<34} n={len(v):<3} avgR={mean(v):+.2f}")

    # 4. MFE before exit (did the fade work first?)
    mfes = [_f(t.get("mfe_r")) for t, _ in rows]
    went_green = [m for m in mfes if m >= 0.5]
    print("\n--- did it work before failing? (mfe_r, v240 floored) ---")
    print(f"  reached >=0.5R favorable: {len(went_green)}/{len(rows)} "
          f"({len(went_green)/len(rows)*100:.0f}%)   avg mfe_r={mean(mfes):+.2f}")
    print("  LOW % => fade is wrong from the tick (fading into strength).")
    print("  HIGH % => fade works then reverses (exit/stop-management problem).")

    # 5. long vs short + time-of-day
    print("\n--- long vs short fade ---")
    for side_key in ("long", "short"):
        sub = [(t, r) for t, r in rows
               if str(t.get("side") or t.get("direction", "")).lower().startswith(side_key[0])]
        if sub:
            sr = [r for _, r in sub]
            w = len([r for r in sr if r > 0])
            print(f"  {side_key:<6} n={len(sub):<3} win={w/len(sub)*100:.0f}%  avgR={mean(sr):+.2f}")
    print("\n--- entry hour (ET) ---")
    hour = defaultdict(list)
    for t, r in rows:
        h = _entry_hour_et(t)
        if h is not None:
            hour[h].append(r)
    for h in sorted(hour):
        v = hour[h]
        print(f"  {h:02d}:00  n={len(v):<3} avgR={mean(v):+.2f}")

    print()


if __name__ == "__main__":
    main()
