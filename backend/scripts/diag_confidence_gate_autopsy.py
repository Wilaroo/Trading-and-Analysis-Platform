#!/usr/bin/env python3
"""
CONFIDENCE-GATE DECISION AUTOPSY (read-only) — why is the bot DEFENSIVE / 0 taken?

The confidence gate flips to DEFENSIVE only when the Market Regime Engine reports
regime_state == "CONFIRMED_DOWN". Scoring: >=55 GO, >=30 REDUCE, <30 SKIP. In a
CONFIRMED_DOWN regime, LONGS get -10 (+ 30% size cut) and SHORTS get +15.

This reads today's `confidence_gate_log` and shows:
  • decision split (GO / REDUCE / SKIP) and the take-rate
  • the regime_state + regime_score the gate saw (is it really CONFIRMED_DOWN?)
  • the LONG vs SHORT split of evaluations (are we only seeing penalized longs?)
  • confidence_score distribution (are scores far below 30, or just missing?)
  • the most common SKIP reasoning lines (what's dragging scores down)
So we can tell apart: (a) real bear day, longs penalized; (b) scores universally
low because AI models contribute nothing; (c) regime stuck/miscalibrated on DOWN.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_confidence_gate_autopsy.py [HOURS]   # default 8
"""
import sys
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def main():
    db = _load_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).isoformat()
    rows = list(db.confidence_gate_log.find({"timestamp": {"$gte": cutoff}}))
    print(f"CONFIDENCE-GATE AUTOPSY — last {HOURS:g}h  ({len(rows)} decisions)\n")
    if not rows:
        print("No gate decisions logged. The opportunity evaluator may not be reaching")
        print("the gate (upstream filter), or the bot loop isn't evaluating. Check that")
        print("alerts are flowing into _evaluate_opportunity.")
        return

    dec = Counter(r.get("decision") for r in rows)
    mode = Counter(r.get("trading_mode") for r in rows)
    regimes = Counter(f"{r.get('regime_state')}({r.get('regime_score')})" for r in rows)
    dirs = Counter((r.get("direction") or "?").lower() for r in rows)
    scores = [float(r.get("confidence_score") or 0) for r in rows]

    go = dec.get("GO", 0)
    print(f"DECISIONS: GO={go}  REDUCE={dec.get('REDUCE',0)}  SKIP={dec.get('SKIP',0)}"
          f"   take-rate={100*go/len(rows):.1f}%")
    print(f"TRADING MODE: " + ", ".join(f"{k}={v}" for k, v in mode.most_common()))
    print(f"REGIME (state(score)): " + ", ".join(f"{k}={v}" for k, v in regimes.most_common(6)))
    print(f"DIRECTION split: " + ", ".join(f"{k}={v}" for k, v in dirs.most_common()))
    if scores:
        ge55 = sum(1 for s in scores if s >= 55)
        ge30 = sum(1 for s in scores if 30 <= s < 55)
        lt30 = sum(1 for s in scores if s < 30)
        print(f"\nCONFIDENCE SCORE: min={min(scores):.0f} median={statistics.median(scores):.0f} "
              f"max={max(scores):.0f}")
        print(f"  >=55 (GO): {ge55}   30-54 (REDUCE): {ge30}   <30 (SKIP): {lt30}")

    # SKIP breakdown by direction + score
    skips = [r for r in rows if r.get("decision") == "SKIP"]
    if skips:
        sd = Counter((r.get("direction") or "?").lower() for r in skips)
        print(f"\nSKIP direction split: " + ", ".join(f"{k}={v}" for k, v in sd.most_common()))
        # most common reasoning lines (normalize numbers out)
        import re
        rc = Counter()
        for r in skips:
            for line in (r.get("reasoning") or []):
                norm = re.sub(r"[-+]?\d[\d.,%]*", "#", str(line))
                rc[norm.strip()] += 1
        print("\nTop SKIP reasoning lines:")
        for line, n in rc.most_common(14):
            print(f"  {n:>5}  {line[:96]}")

    # Best-scoring shorts (should pass in a bear regime) — are any close to GO?
    shorts = sorted([r for r in rows if (r.get("direction") or "").lower() in ("short", "sell")],
                    key=lambda r: -float(r.get("confidence_score") or 0))[:8]
    if shorts:
        print("\nTop-scoring SHORTS (bear regime should favor these):")
        for r in shorts:
            print(f"  {r.get('symbol','?'):<6} {str(r.get('setup_type'))[:18]:<18} "
                  f"score={float(r.get('confidence_score') or 0):.0f} → {r.get('decision')}")
    else:
        print("\n⚠ NO short evaluations at all — in a CONFIRMED_DOWN regime the bot is only")
        print("  seeing long setups (all penalized -10), which would explain 0 trades.")

    print("\nVERDICT GUIDE:")
    print("  • regime=CONFIRMED_DOWN + mostly LONG evals  → longs penalized; need short setups")
    print("    surfacing (scanner short-side generation) OR regime is wrong.")
    print("  • scores cluster just under 30 with 'model IGNORED' reasons → AI models contribute")
    print("    nothing (low accuracy) → gate can't reach threshold in defensive mode.")
    print("  • regime_score looks bullish (>=55) but state=CONFIRMED_DOWN → regime engine STUCK.")


if __name__ == "__main__":
    main()
