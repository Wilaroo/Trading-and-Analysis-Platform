#!/usr/bin/env python3
"""
TAPE-CONFIRMED FLOW COMPOSITION (read-only) — what eats the 319->2 collapse?

The trade-funnel shows lots of tape-confirmed HIGH/CRITICAL alerts but almost none
becoming auto_execute_eligible. This script breaks TODAY's (ET) tape-confirmed
HIGH/CRITICAL `live_alerts` down BY SETUP, and annotates each setup with the EV-gate
verdict (from strategy_stats) + the win-rate floor (0.55), so you can see exactly
which setups are consuming the strong-signal flow and why they're blocked.

Verdict legend (per the v19.34.293 EV gate + win-rate floor):
  GRACE     outcomes < 20         → can auto-execute (cold-start grace)
  PASS      outcomes>=20, EV>0.10 → can auto-execute
  BLOCK-EV  outcomes>=20, EV<=0.10→ blocked (proven weak)  ← the bleeders
  WR<0.55   win_rate below floor  → (informational; EV gate is the live gate)

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_tape_confirmed_composition.py [DATE]  # default = today ET
"""
import sys
from collections import Counter
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
GRACE_MIN, MIN_EV_R, WR_FLOOR = 20, 0.10, 0.55
QUALITY = {
    "9_ema_scalp", "vwap_continuation", "big_dog", "hod_breakout", "second_chance",
    "the_3_30_trade", "gap_give_go", "premarket_high_break", "bouncy_ball",
    "power_trend_stack", "rs_leader_breakout", "pocket_pivot", "stage_2_breakout",
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


def _day_bounds(date_str):
    if date_str:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    else:
        d = datetime.now(ET)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat(), start.strftime("%Y-%m-%d")


def main():
    db = _load_db()
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    lo, hi, day = _day_bounds(date_arg)

    # strategy_stats lookup
    stats = {}
    for d in db.strategy_stats.find({}, {"_id": 0}):
        stats[d.get("setup_type")] = (
            int(d.get("alerts_triggered", 0) or 0),
            float(d.get("expected_value_r", 0.0) or 0.0),
            float(d.get("win_rate", 0.0) or 0.0),
        )

    def verdict(setup):
        if setup not in stats:
            return "NO_STATS", 0, 0.0, 0.0
        o, ev, wr = stats[setup]
        if o < GRACE_MIN:
            v = "GRACE"
        elif ev > MIN_EV_R:
            v = "PASS"
        else:
            v = "BLOCK-EV"
        return v, o, ev, wr

    q = {
        "created_at": {"$gte": lo, "$lte": hi},
        "priority": {"$in": ["high", "critical", "HIGH", "CRITICAL"]},
        "tape_confirmation": True,
    }
    alerts = list(db.live_alerts.find(q, {"setup_type": 1, "setup": 1, "auto_execute_eligible": 1, "direction": 1}))
    print(f"TAPE-CONFIRMED HIGH/CRITICAL alerts on {day}: {len(alerts)}\n")
    if not alerts:
        print("None found for this date (try a recent trading day as DATE arg).")
        return

    by_setup = Counter()
    eligible_by_setup = Counter()
    for a in alerts:
        s = a.get("setup_type") or a.get("setup") or "?"
        by_setup[s] += 1
        if a.get("auto_execute_eligible"):
            eligible_by_setup[s] += 1

    print(f"{'setup':<24}{'tapeHI':>7}{'elig':>6}{'out':>5}{'EV(R)':>8}{'win%':>6}  verdict")
    print("-" * 74)
    blocked_total = 0
    for s, n in by_setup.most_common():
        v, o, ev, wr = verdict(s)
        if v in ("BLOCK-EV", "NO_STATS"):
            blocked_total += n
        q = " ★" if s in QUALITY else ""
        wrf = "  WR<.55" if (o >= GRACE_MIN and wr < WR_FLOOR) else ""
        print(f"{s:<24}{n:>7}{eligible_by_setup[s]:>6}{o:>5}{ev:>+8.2f}{wr*100:>6.0f}  {v}{q}{wrf}")

    elig = sum(eligible_by_setup.values())
    print(f"\nSUMMARY: {len(alerts)} tape-confirmed HIGH/CRITICAL → {elig} auto_execute_eligible.")
    print(f"  {blocked_total} ({100*blocked_total/len(alerts):.0f}%) were eaten by BLOCK-EV / NO_STATS setups (correctly rejected bleeders).")
    qflow = sum(n for s, n in by_setup.items() if s in QUALITY)
    print(f"  {qflow} ({100*qflow/len(alerts):.0f}%) of the strong-signal flow came from QUALITY with-trend setups.")
    print("\nINTERPRETATION:")
    print("  • If most of the flow is BLOCK-EV fades → the gate is right; we need the QUALITY")
    print("    setups to PRODUCE more tape-confirmed HIGH-priority signals (signal-gen work),")
    print("    not a looser gate.")
    print("  • If QUALITY setups have lots of tapeHI but elig=0 → check why they're not flagged")
    print("    eligible (win-rate floor vs EV grace path).")


if __name__ == "__main__":
    main()
