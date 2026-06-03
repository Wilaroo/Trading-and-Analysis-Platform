#!/usr/bin/env python3
"""
v19.34.250 — SETUP LOSS FORENSICS (READ-ONLY).

Answers: "are this setup's losses REAL strategy bleed, or artifacts of our
previous buggy era (phantoms, flip-side/wrong-direction, oversizing, orphan
fills, blown stops)?" — so the operator can decide on the −1.5R circuit breaker.

Breaks the setup's closed bot_trades down by:
  • direction (long vs short — e.g. vwap_fade_short was the disabled bleeder)
  • genuine vs hygiene-tagged artifact
  • close_reason  +  entered_by
  • weekly era histogram (did losses cluster pre-fix?)
  • loss-magnitude buckets (>-1.5R / >-3R / >-5R / >-10R) + worst
  • BLOWN-STOP slippage (how far past the stop the exit filled — the signature
    of illiquid squeezes the breaker would cap)
  • oversizing flag (notional vs median)

Run on DGX:
    .venv/bin/python backend/scripts/diag_setup_loss_forensics_v19_34_250.py --setup vwap_fade --days 60
"""
import argparse
import os
import sys
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[os.environ.get("DB_NAME", "tradecommand")]
db.client.admin.command("ping")
print(f"[db] {mongo_url}")

ap = argparse.ArgumentParser()
ap.add_argument("--setup", default="vwap_fade")
ap.add_argument("--days", type=int, default=60)
args = ap.parse_args()
cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def base(s):
    return (s or "").lower().replace("_long", "").replace("_short", "")


def resolve_exit(bt, entry, direction):
    xp = _f(bt.get("exit_price"))
    if xp:
        return xp
    r, sh = _f(bt.get("realized_pnl")), _f(bt.get("shares"))
    if entry and r is not None and sh and sh > 0:
        pps = r / sh
        return entry + pps if direction == "long" else entry - pps
    return None


rows = [d for d in db["bot_trades"].find(
    {"status": {"$in": ["closed", "CLOSED"]}, "closed_at": {"$gte": cutoff}})
    if base(d.get("setup_type")) == args.setup]

print(f"\n{'='*70}\nFORENSICS: {args.setup}  ({len(rows)} closed trades, last {args.days}d)\n{'='*70}")

try:
    from services.trade_outcome_hygiene import classify_close
except Exception:
    classify_close = None

by_dir = Counter()
by_reason = Counter()
by_enteredby = Counter()
by_week = defaultdict(lambda: [0, 0.0])  # week -> [count, sum_R]
genuine_n = artifact_n = 0
loss_buckets = {"-1.5R..": 0, "-3R..": 0, "-5R..": 0, "-10R..": 0}
worst = (0.0, None)
blown_stops = []        # (symbol, R, slippage_beyond_stop_in_R)
notionals = []
all_R = []
sample_bad = []

for bt in rows:
    entry = _f(bt.get("fill_price"))
    direction = str(bt.get("direction") or "long").lower()
    if direction not in ("long", "short"):
        direction = "long"
    exit_p = resolve_exit(bt, entry, direction)
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
    sh = _f(bt.get("shares")) or 0
    if entry and sh:
        notionals.append(entry * sh)
    by_dir[direction] += 1
    by_reason[bt.get("close_reason") or "?"] += 1
    by_enteredby[str(bt.get("entered_by") or "?")] += 1
    if classify_close:
        g, _t = classify_close(
            close_reason=bt.get("close_reason"), entered_by=str(bt.get("entered_by") or ""),
            entry_price=entry, exit_price=exit_p,
            net_pnl=_f(bt.get("net_pnl")) or _f(bt.get("realized_pnl")) or 0.0,
            hold_seconds=None, setup_type=str(bt.get("setup_type") or ""))
        genuine_n += 1 if g else 0
        artifact_n += 0 if g else 1

    if entry and exit_p and stop and abs(entry - stop) > 0:
        risk = abs(entry - stop)
        pps = (exit_p - entry) if direction == "long" else (entry - exit_p)
        R = pps / risk
        all_R.append(R)
        wk = str(bt.get("closed_at", ""))[:10]
        # bucket to ISO week-ish (just date prefix → group by week below)
        by_week[wk[:7]][0] += 1
        by_week[wk[:7]][1] += R
        if R < worst[0]:
            worst = (R, bt.get("symbol"))
        if R <= -1.5:
            loss_buckets["-1.5R.."] += 1
        if R <= -3:
            loss_buckets["-3R.."] += 1
        if R <= -5:
            loss_buckets["-5R.."] += 1
        if R <= -10:
            loss_buckets["-10R.."] += 1
        # blown stop: loser filled WORSE than the stop (beyond -1R by slippage)
        if R < -1.05:
            beyond = abs(R) - 1.0  # R of slippage past the intended -1R stop
            blown_stops.append((bt.get("symbol"), round(R, 2), round(beyond, 2),
                                bt.get("close_reason")))
        if R <= -3:
            sample_bad.append((bt.get("symbol"), round(R, 2), direction,
                               bt.get("close_reason"), str(bt.get("closed_at", ""))[:10],
                               int(sh)))

print(f"\n  direction:   {dict(by_dir)}")
print(f"  genuine:     {genuine_n}   artifact(hygiene-tagged): {artifact_n}")
print(f"  entered_by:  {dict(by_enteredby)}")
print("\n  close_reason:")
for r, c in by_reason.most_common(10):
    print(f"      {r:<42} {c}")

print(f"\n  realized R: n={len(all_R)}  mean={statistics.mean(all_R):.2f}  "
      f"median={statistics.median(all_R):.2f}" if all_R else "  (no R-computable trades)")
print(f"  worst single trade: {worst[0]:.1f}R ({worst[1]})")
print(f"  loss-magnitude buckets (trades at-or-worse): {loss_buckets}")
n_blown = len(blown_stops)
print(f"\n  BLOWN STOPS (filled worse than -1R): {n_blown}/{len(all_R)} "
      f"({100*n_blown//max(len(all_R),1)}%)")
if all_R:
    capped = sum(min(0, max(R, -1.5)) - R for R in all_R if R < -1.5)
    raw = sum(R for R in all_R)
    print(f"  Σ realized R = {raw:.1f}R ; if a -1.5R hard cap had applied, "
          f"the >-1.5R blowouts would have saved ~{abs(capped):.1f}R")
print("  worst blown stops (symbol, R, R-slippage past stop, reason):")
for s in sorted(blown_stops, key=lambda x: x[1])[:12]:
    print(f"      {str(s[0]):<8} {s[1]:>7}R  slip+{s[2]}R  {s[3]}")

if notionals:
    med = statistics.median(notionals)
    over = [n for n in notionals if n > 3 * med]
    print(f"\n  notional $: median={med:,.0f}  trades >3× median (oversizing?): {len(over)}")

print("\n  weekly mean-R (did the bleed cluster in a buggy era?):")
for wk in sorted(by_week):
    c, s = by_week[wk]
    print(f"      {wk}   n={c:<4} meanR={s/c:+.2f}" if c else "")

print("\n  worst trades (≤ -3R) sample (symbol, R, dir, reason, date, shares):")
for s in sorted(sample_bad, key=lambda x: x[1])[:15]:
    print(f"      {s}")
print("\nDone. (read-only)\n")
