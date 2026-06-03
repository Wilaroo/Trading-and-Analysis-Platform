#!/usr/bin/env python3
"""
diag_accumulation_entry.py — read-only early-exit investigation for the
`accumulation_entry` POSITION setup (🟡 P1).

Question we're answering: are profitable `accumulation_entry` trades being
shaken out early (stop too tight / systemic premature exit), or is the setup
just genuinely low-edge?

Signals used (all from `bot_trades`, the canonical execution history):
  - close_reason            -> WHY it exited (stop_loss / trailing / target / eod / manual)
  - mfe_r / mae_r           -> Max Favorable / Adverse Excursion in R-multiples
  - realized_pnl + risk     -> final realized R
  - executed_at -> closed_at -> hold time (a POSITION trade held only minutes
                                is itself a red flag)

The smoking gun for "shaken out early": a stop/trail exit where mfe_r was
comfortably positive (trade WAS working) but final R came in negative — i.e.
we gave back an open gain and then some.

Run on the DGX:  .venv/bin/python /tmp/diag_accumulation_entry.py
Optional:        ... /tmp/diag_accumulation_entry.py --days 120
READ-ONLY. No writes, no order actions.
"""
import argparse
import os
from datetime import datetime, timezone, timedelta
from statistics import median, mean

from pymongo import MongoClient

SETUP = "accumulation_entry"
NAME_FIELDS = ("setup_type", "setup_variant", "strategy_name")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _matches_setup(doc) -> bool:
    for k in NAME_FIELDS:
        if str(doc.get(k, "") or "").strip().lower() == SETUP:
            return True
    return False


def _entry_price(t):
    return _f(t.get("fill_price") or t.get("entry_price"))


def _orig_stop(t):
    ps = t.get("protective_stop") or {}
    s = _f(ps.get("original_stop")) or _f(ps.get("current_stop")) or _f(t.get("stop_price"))
    return s


def _shares(t):
    return _f(t.get("shares") or t.get("remaining_shares"))


def _final_r(t):
    """Realized R = realized_pnl / (risk_per_share * shares). Falls back to
    actual_r if the per-share risk is unknowable."""
    if t.get("actual_r") is not None:
        return _f(t.get("actual_r"))
    entry, stop, sh = _entry_price(t), _orig_stop(t), _shares(t)
    rps = abs(entry - stop)
    risk = rps * sh
    pnl = _f(t.get("net_pnl")) or _f(t.get("realized_pnl"))
    if risk > 0:
        return pnl / risk
    return 0.0


def _hold_minutes(t):
    a = t.get("executed_at") or t.get("created_at")
    b = t.get("closed_at")
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db_ = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        return (db_ - da).total_seconds() / 60.0
    except Exception:
        return None


def _bucket_reason(r: str) -> str:
    r = (r or "unknown").lower()
    if "target" in r:
        return "target"
    if "trail" in r:
        return "trailing_stop"
    if "stop" in r or "breakeven" in r:
        return "stop_loss"
    if "eod" in r:
        return "eod"
    if "manual" in r or "operator" in r:
        return "manual"
    if "phantom" in r or "sweep" in r or "reconcil" in r or "purge" in r:
        return "reconcile/sweep"
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")).get_database(
        os.environ.get("DB_NAME", "tradecommand")
    )
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    closed = [
        t for t in db.bot_trades.find(
            {"status": "closed"}, {"_id": 0}
        )
        if _matches_setup(t) and (t.get("closed_at") or "") >= since
    ]

    print(f"\n{'='*72}")
    print(f"accumulation_entry early-exit investigation — last {args.days}d")
    print(f"{'='*72}")
    if not closed:
        print("No closed accumulation_entry trades in window. Nothing to analyze.")
        # cross-check trade_outcomes too
        oc = [o for o in db.trade_outcomes.find({}, {"_id": 0}) if _matches_setup(o)]
        print(f"(trade_outcomes carrying this setup at all: {len(oc)})")
        return

    n = len(closed)
    rs = [_final_r(t) for t in closed]
    wins = [r for r in rs if r > 0]
    pnls = [_f(t.get("net_pnl")) or _f(t.get("realized_pnl")) for t in closed]
    holds = [h for h in (_hold_minutes(t) for t in closed) if h is not None]

    print(f"\nSample: {n} closed trades")
    print(f"  win rate         : {len(wins)/n*100:5.1f}%  ({len(wins)}/{n})")
    print(f"  avg realized R   : {mean(rs):+.2f}R   (median {median(rs):+.2f}R)")
    print(f"  total net P&L    : ${sum(pnls):+,.0f}")
    if holds:
        print(f"  hold time        : median {median(holds)/60:.1f}h  mean {mean(holds)/60:.1f}h"
              f"   (POSITION setup — expect days/weeks)")
        quick = [h for h in holds if h < 60]
        print(f"  exited <60min    : {len(quick)}/{len(holds)}  "
              f"({len(quick)/len(holds)*100:.0f}%)  <- red flag if high for a POSITION trade")

    # Exit-reason breakdown
    print("\n--- exit reasons (count · avg R · avg mfe_r reached before exit) ---")
    from collections import defaultdict
    by = defaultdict(list)
    for t in closed:
        by[_bucket_reason(t.get("close_reason"))].append(t)
    for reason, ts in sorted(by.items(), key=lambda kv: -len(kv[1])):
        r_avg = mean([_final_r(t) for t in ts])
        mfe_avg = mean([_f(t.get("mfe_r")) for t in ts])
        print(f"  {reason:<16} n={len(ts):<3}  avgR={r_avg:+.2f}  avg_mfe_r={mfe_avg:+.2f}")

    # ---- SHAKEN OUT EARLY detector ----
    # Stop/trail exit, trade reached >=1R in our favor, but closed at a LOSS.
    shaken = []
    for t in closed:
        reason = _bucket_reason(t.get("close_reason"))
        if reason in ("stop_loss", "trailing_stop"):
            mfe = _f(t.get("mfe_r"))
            fr = _final_r(t)
            if mfe >= 1.0 and fr < 0:
                shaken.append((t, mfe, fr))
    print("\n--- SHAKEN-OUT-EARLY (stop/trail exit, mfe_r>=1.0, closed RED) ---")
    print(f"  {len(shaken)}/{n} trades reached >=1R in profit then stopped for a loss")
    if shaken:
        gave_back = mean([mfe - fr for _, mfe, fr in shaken])
        print(f"  avg gain given back: {gave_back:.2f}R")
        for t, mfe, fr in sorted(shaken, key=lambda x: -x[1])[:12]:
            print(f"    {t.get('symbol',''):<6} {str(t.get('side') or t.get('direction','')):<5}"
                  f" mfe={mfe:+.2f}R  final={fr:+.2f}R  reason={t.get('close_reason','')}")

    # ---- STOP TIGHTNESS ----
    # Among ALL trades, how deep did MAE go before the eventual outcome?
    # If winners routinely dipped to ~-0.9R (just inside the stop) the stop is
    # sitting right on the noise band.
    win_mae = [_f(t.get("mae_r")) for t in closed if _final_r(t) > 0]
    loss_mae = [_f(t.get("mae_r")) for t in closed if _final_r(t) <= 0]
    print("\n--- stop tightness (MAE = how far underwater before exit) ---")
    if win_mae:
        deep_winners = [m for m in win_mae if m <= -0.7]
        print(f"  winners' avg MAE : {mean(win_mae):+.2f}R   "
              f"({len(deep_winners)}/{len(win_mae)} dipped <=-0.7R before working) "
              f"<- if high, stop is on the noise band")
    if loss_mae:
        print(f"  losers'  avg MAE : {mean(loss_mae):+.2f}R")

    print("\n--- READ ---")
    if shaken and len(shaken) / n >= 0.20:
        print("  >=20% of trades reached 1R+ then stopped for a loss -> EARLY-EXIT")
        print("  problem is real. Likely levers: widen initial stop to ATR-based,")
        print("  or move to breakeven only after a larger MFE buffer.")
    elif win_mae and mean(win_mae) <= -0.6:
        print("  Winners routinely dip near the stop before working -> stop is on")
        print("  the noise band. Consider a wider ATR-multiple initial stop.")
    else:
        print("  No strong early-exit signal in this sample — the setup's edge")
        print("  (avg R above) is the thing to question, not the exits.")
    print()


if __name__ == "__main__":
    main()
