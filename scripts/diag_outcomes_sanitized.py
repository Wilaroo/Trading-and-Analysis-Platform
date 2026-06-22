#!/usr/bin/env python3
"""
diag_outcomes_sanitized.py — TQS-vs-outcome on SANITIZED recent trades (READ-ONLY)
==================================================================================

Re-runs the prelim signal check, but on the trades the project considers
RELIABLE — per the previous agent's forensics (diag_v333/v334, v336) and
trade_outcome_hygiene:

  FILTER FUNNEL (each stage reported):
   1. closed bot_trades within --days (default 14 — operator: "only the last
      10-14 days have been semi-reliable")
   2. BOT-OWN only — drop ADOPTED/external positions (is_adopted_entry): the
      bot merely attributed reconciled IB holdings / operator fills (~46% of
      closes, +$181k) which it never chose on TQS — blending them inverts the
      signal.
   3. GENUINE only — drop execution/reconciliation artifacts (phantom/sweep/
      operator-flatten/corrupt-pnl), using the persisted hygiene `genuine` flag.
   4. RELIABLE R — drop r_risk_unreliable (corrupt entry/stop basis) and rows
      with no computable R.
   5. WINSORIZE R to +-3.0 (R_WINSOR_CLAMP) so a single -261R artifact can't
      poison the means.

Then: realized-R distribution + tercile win%/avgR by persisted tqs_score
(= scheme A) + corr(tqs_score, R). This tells us whether the CURRENT score
carries signal on CLEAN, RECENT, BOT-OWN trades — the only fair test.

100% READ-ONLY.

USAGE (DGX, repo root):
    .venv/bin/python diag_outcomes_sanitized.py                 # last 14d, full sanitize
    .venv/bin/python diag_outcomes_sanitized.py --days 10
    .venv/bin/python diag_outcomes_sanitized.py --include-adopted   # relax stage 2
    .venv/bin/python diag_outcomes_sanitized.py --no-winsor
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone, timedelta

# mirror services.trade_outcome_hygiene._ADOPTED_ENTRY_HINTS (kept inline so the
# probe is self-contained / import-free)
_ADOPTED_HINTS = ("reconcil", "external", "excess", "adopt", "orphan",
                  "ib_only", "ib-only", "imported")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _dir(d):
    return str(getattr(d, "value", d) or "long").lower()

def is_adopted(entered_by="", source="", close_reason=""):
    blob = f"{entered_by or ''} {source or ''} {close_reason or ''}".lower()
    return any(h in blob for h in _ADOPTED_HINTS)

def realized_r(bt):
    entry = _f(bt.get("fill_price"))
    direction = _dir(bt.get("direction"))
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
    xp = _f(bt.get("exit_price"))
    if not xp:
        realized = _f(bt.get("realized_pnl")); shares = _f(bt.get("shares"))
        if entry and realized is not None and shares and shares > 0:
            pps = realized / shares
            xp = entry + pps if direction == "long" else entry - pps
    if not (entry and xp and stop):
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    move = (xp - entry) if direction == "long" else (entry - xp)
    return move / risk

def _pct(v, p):
    if not v:
        return None
    s = sorted(v); k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)

def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def main():
    ap = argparse.ArgumentParser(description="TQS vs outcome on sanitized recent trades")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--winsor", type=float, default=3.0)
    ap.add_argument("--no-winsor", action="store_true")
    ap.add_argument("--include-adopted", action="store_true")
    ap.add_argument("--include-artifacts", action="store_true",
                    help="don't drop non-genuine closes")
    args = ap.parse_args()
    winsor = None if args.no_winsor else args.winsor

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set."); sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    q = {"status": {"$in": ["closed", "CLOSED"]}, "closed_at": {"$gte": cutoff}}
    proj = {"_id": 0, "id": 1, "trade_id": 1, "alert_id": 1, "symbol": 1,
            "setup_type": 1, "direction": 1, "entered_by": 1, "source": 1,
            "close_reason": 1, "fill_price": 1, "exit_price": 1, "stop_price": 1,
            "stop_loss": 1, "realized_pnl": 1, "shares": 1, "closed_at": 1,
            "tqs_score": 1}
    closed = list(db["bot_trades"].find(q, proj))

    # hygiene flags (genuine, r_risk_unreliable, canonical R) keyed by trade id
    to_map, ao_map = {}, {}
    for d in db["trade_outcomes"].find(
            {}, {"_id": 0, "bot_trade_id": 1, "actual_r": 1, "genuine": 1, "outcome": 1}):
        if d.get("bot_trade_id"):
            to_map[d["bot_trade_id"]] = d
    for d in db["alert_outcomes"].find(
            {}, {"_id": 0, "trade_id": 1, "r_multiple": 1, "genuine": 1,
                 "outcome": 1, "r_risk_unreliable": 1}):
        if d.get("trade_id"):
            ao_map[d["trade_id"]] = d

    # ── filter funnel ────────────────────────────────────────────────────
    n0 = len(closed)
    n_botown = n_genuine = n_relR = n_scored = 0
    drop_adopted = drop_artifact = drop_badR = 0
    rows = []  # (score, r, win)
    for bt in closed:
        tid = bt.get("id") or bt.get("trade_id")
        to = to_map.get(tid); ao = ao_map.get(tid)

        # stage 2: bot-own
        if not args.include_adopted and is_adopted(
                bt.get("entered_by"), bt.get("source"), bt.get("close_reason")):
            drop_adopted += 1
            continue
        n_botown += 1

        # stage 3: genuine
        genuine = True
        if to is not None:
            genuine = bool(to.get("genuine", True))
        elif ao is not None:
            genuine = bool(ao.get("genuine", True))
        if not args.include_artifacts and not genuine:
            drop_artifact += 1
            continue
        n_genuine += 1

        # stage 4: reliable R
        if ao is not None and ao.get("r_risk_unreliable"):
            drop_badR += 1
            continue
        r = None; outcome = None
        if to and to.get("actual_r") is not None:
            r = _f(to.get("actual_r")); outcome = to.get("outcome")
        elif ao and ao.get("r_multiple") is not None:
            r = _f(ao.get("r_multiple")); outcome = ao.get("outcome")
        else:
            r = realized_r(bt)
        if r is None:
            drop_badR += 1
            continue
        n_relR += 1

        # stage 5: winsorize
        win = (outcome == "won") if outcome in ("won", "lost", "scratch") else (r > 0)
        if winsor is not None:
            r = max(-winsor, min(winsor, r))

        score = _f(bt.get("tqs_score"))
        if score is not None and score > 0:
            n_scored += 1
            rows.append((score, r, win))

    print("=" * 90)
    print(f"  SANITIZED TQS-vs-OUTCOME   (last {args.days}d, bot-own"
          f"{'' if not args.include_adopted else ' +adopted'}"
          f"{'' if not args.include_artifacts else ' +artifacts'}, "
          f"winsor={'off' if winsor is None else f'±{winsor}'})")
    print("=" * 90)
    print("  FILTER FUNNEL")
    print(f"    closed in window:        {n0}")
    print(f"    - dropped ADOPTED:       {drop_adopted}  -> bot-own: {n_botown}")
    print(f"    - dropped ARTIFACTS:     {drop_artifact}  -> genuine: {n_genuine}")
    print(f"    - dropped bad/again R:   {drop_badR}  -> reliable R: {n_relR}")
    print(f"    - with tqs_score>0:      {n_scored}  (final usable)")

    rs = [r for _, r, _ in rows]
    if rs:
        wins = sum(1 for _, _, w in rows if w)
        print(f"\n  REALIZED R (sanitized): n={len(rs)}  win%={wins/len(rs)*100:.1f}  "
              f"min={min(rs):.2f}  p25={_pct(rs,25):.2f}  p50={_pct(rs,50):.2f}  "
              f"p75={_pct(rs,75):.2f}  max={max(rs):.2f}  mean={sum(rs)/len(rs):+.3f}R")

    print("\n" + "-" * 90)
    if len(rows) >= 12:
        rows.sort(key=lambda x: x[0])
        n = len(rows)
        thirds = [rows[:n // 3], rows[n // 3:2 * n // 3], rows[2 * n // 3:]]
        print(f"  TERCILE by tqs_score (=scheme A) — does the score separate winners?")
        print(f"  {'tercile':<10}{'n':>5}{'score rng':>14}{'win%':>8}{'avg R':>9}")
        for name, grp in zip(("low", "mid", "high"), thirds):
            if not grp:
                continue
            sc = [g[0] for g in grp]; gr = [g[1] for g in grp]
            wr = sum(1 for g in grp if g[2]) / len(grp) * 100
            print(f"  {name:<10}{len(grp):>5}{f'{min(sc):.1f}-{max(sc):.1f}':>14}"
                  f"{wr:>8.1f}{sum(gr)/len(gr):>+9.3f}")
        cor = _pearson([g[0] for g in rows], [g[1] for g in rows])
        print(f"\n  corr(tqs_score, R) = {cor:+.3f}" if cor is not None else "\n  corr: n/a")
        print("\n  READ: high tercile win%/R clearly ABOVE low (corr>+0.1) -> the score has")
        print("  signal on clean recent data -> proceed to the full A-E discrimination harness.")
        print("  Flat/negative even here -> the INPUTS/directional logic are wrong, not the")
        print("  aggregation; fix feeds + sign before any scheme decision.")
    else:
        print(f"  Only {len(rows)} sanitized+scored closes in {args.days}d — too few to grade.")
        print("  Widen --days, or this itself says: not enough clean bot-own outcomes yet to")
        print("  validate the score (decide scheme later; keep trading clean first).")
    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
