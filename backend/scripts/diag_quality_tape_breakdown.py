#!/usr/bin/env python3
"""
WHY QUALITY LONGS NEVER TAPE-CONFIRM (read-only) — which tape component fails?

For a LONG, tape_confirmation = (raw tape_score >= 0.2), where
  raw = (+0.2 tight_spread) + (imbalance*0.4) + (+0.3 momentum if rvol>=2 & above ema9)
The normalized tape_score stored on the alert is (raw+1)*5, so confirmed == stored>=6.0.

This dumps today's QUALITY-setup HIGH/CRITICAL alerts and shows, from the PERSISTED
fields (tape_score, tape_signals=[spread,imbalance,momentum], rvol):
  • the stored tape_score distribution (how far below the 6.0 confirm line they sit)
  • the momentum-signal tally (neutral vs momentum_up) — proves the rvol>=2 gate
  • the spread-signal tally (tight vs neutral/wide)
  • the rvol distribution (median, % >= 2.0)  ← the suspected culprit
so we can see whether momentum longs miss the +0.3 momentum bonus because their RVOL
sits in the 1.5–2.0 band (below the tape's 2.0 gate) while their setup floor let them fire.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_quality_tape_breakdown.py [DATE]   # default = today ET
"""
import sys
import statistics
from collections import Counter
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
QUALITY = {
    "9_ema_scalp", "vwap_continuation", "big_dog", "hod_breakout", "second_chance",
    "the_3_30_trade", "gap_give_go", "premarket_high_break", "bouncy_ball",
    "power_trend_stack", "rs_leader_breakout", "pocket_pivot", "stage_2_breakout",
    "daily_breakout", "trend_continuation", "range_break", "first_vwap_pullback",
    "vcp_breakout", "weekly_breakout", "two_hundred_day_reclaim",
}


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _bounds(date_str):
    d = (datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
         if date_str else datetime.now(ET))
    s = d.replace(hour=0, minute=0, second=0, microsecond=0)
    e = s.replace(hour=23, minute=59, second=59)
    return s.astimezone(timezone.utc).isoformat(), e.astimezone(timezone.utc).isoformat(), s.strftime("%Y-%m-%d")


def main():
    db = _load_db()
    lo, hi, day = _bounds(sys.argv[1] if len(sys.argv) > 1 else None)
    rows = list(db.live_alerts.find({
        "created_at": {"$gte": lo, "$lte": hi},
        "priority": {"$in": ["high", "critical", "HIGH", "CRITICAL"]},
        "setup_type": {"$in": list(QUALITY)},
    }, {"setup_type": 1, "direction": 1, "tape_score": 1, "tape_signals": 1,
        "tape_confirmation": 1, "rvol": 1}))

    print(f"QUALITY-setup HIGH/CRITICAL alerts on {day}: {len(rows)}\n")
    if not rows:
        print("None found. Try a recent trading day as DATE arg.")
        return

    longs = [r for r in rows if (r.get("direction") or "long") == "long"]
    ts = [float(r.get("tape_score") or 0.0) for r in rows]
    confirmed = sum(1 for r in rows if r.get("tape_confirmation"))
    rvols = [float(r.get("rvol") or 0.0) for r in rows if r.get("rvol") is not None]

    spread_c, imb_c, mom_c = Counter(), Counter(), Counter()
    for r in rows:
        sig = r.get("tape_signals") or []
        if len(sig) >= 3:
            spread_c[sig[0]] += 1
            imb_c[sig[1]] += 1
            mom_c[sig[2]] += 1

    print(f"tape_confirmed: {confirmed}/{len(rows)}  ({100*confirmed/len(rows):.0f}%)   "
          f"(confirm line = stored tape_score >= 6.0)")
    if ts:
        print(f"stored tape_score: min={min(ts):.2f}  median={statistics.median(ts):.2f}  "
              f"max={max(ts):.2f}   (>=6.0 ⇒ confirmed)")
    print()
    print(f"SPREAD signal:   " + ", ".join(f"{k}={v}" for k, v in spread_c.most_common()))
    print(f"IMBALANCE signal:" + ", ".join(f" {k}={v}" for k, v in imb_c.most_common()))
    print(f"MOMENTUM signal: " + ", ".join(f"{k}={v}" for k, v in mom_c.most_common()))
    print()
    if rvols:
        ge2 = sum(1 for v in rvols if v >= 2.0)
        in_band = sum(1 for v in rvols if 1.5 <= v < 2.0)
        print(f"RVOL: median={statistics.median(rvols):.2f}  "
              f">=2.0: {ge2}/{len(rvols)} ({100*ge2/len(rvols):.0f}%)  "
              f"1.5–2.0 band: {in_band} ({100*in_band/len(rvols):.0f}%)")
    print("\nVERDICT:")
    if mom_c and mom_c.get("neutral", 0) > 0.6 * sum(mom_c.values()):
        print("  → MOMENTUM signal is mostly NEUTRAL → the tape's rvol>=2.0 gate isn't")
        print("    firing for these longs. If RVOL sits in the 1.5–2.0 band, the tape")
        print("    momentum threshold is MISALIGNED with the setup RVOL floor → that's")
        print("    why quality longs never reach tape_score>=0.2 (no +0.3 bonus, and")
        print("    spread/imbalance alone don't get there). FIX: lower/align the tape")
        print("    momentum rvol gate (or add a 1.5–2.0 partial-momentum tier).")
    else:
        print("  → Inspect the signal tallies above to see which component is short.")


if __name__ == "__main__":
    main()
