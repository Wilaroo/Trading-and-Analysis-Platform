#!/usr/bin/env python3
"""
ALERT GENERATION BY SETUP (read-only) — are quality setups DETECTED at all?

Composition showed 0% of tape-confirmed HIGH alerts came from quality with-trend
setups. This answers WHY: groups ALL of a day's `live_alerts` (no priority filter)
by setup_type and shows the priority breakdown + tape-confirmed count, flagging ★
quality setups. It distinguishes:
  • UNDER-DETECTED  — quality setup has ~0 alerts (universe lacks movers → fix universe)
  • UNDER-PRIORITIZED — quality setup has many alerts but they're MEDIUM / no-tape
                        (fix priority assignment / tape for that setup)

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_alert_generation_by_setup.py [DATE]  # default = today ET
"""
import sys
from collections import defaultdict
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
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    lo, hi, day = _bounds(date_arg)

    rows = list(db.live_alerts.find(
        {"created_at": {"$gte": lo, "$lte": hi}},
        {"setup_type": 1, "setup": 1, "priority": 1, "tape_confirmation": 1},
    ))
    print(f"ALERT GENERATION BY SETUP — {day}  (total alerts: {len(rows)})\n")
    if not rows:
        print("No alerts for this date.")
        return

    agg = defaultdict(lambda: {"total": 0, "critical": 0, "high": 0, "medium": 0,
                               "low": 0, "tape_hi": 0})
    for r in rows:
        s = r.get("setup_type") or r.get("setup") or "?"
        p = str(r.get("priority") or "").lower()
        a = agg[s]
        a["total"] += 1
        if p in a:
            a[p] += 1
        if p in ("high", "critical") and r.get("tape_confirmation"):
            a["tape_hi"] += 1

    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["total"])
    print(f"{'setup':<26}{'total':>6}{'crit':>5}{'high':>5}{'med':>5}{'low':>5}{'tapeHI':>7}  ")
    print("-" * 72)
    q_total = q_tapehi = 0
    for s, a in ranked:
        q = " ★" if s in QUALITY else ""
        if s in QUALITY:
            q_total += a["total"]
            q_tapehi += a["tape_hi"]
        print(f"{s:<26}{a['total']:>6}{a['critical']:>5}{a['high']:>5}"
              f"{a['medium']:>5}{a['low']:>5}{a['tape_hi']:>7}{q}")

    print(f"\nQUALITY (★) setups: {q_total} total alerts, {q_tapehi} tape-confirmed HIGH/CRITICAL.")
    print("VERDICT:")
    if q_total < 0.05 * len(rows):
        print(f"  → UNDER-DETECTED: quality setups are only {100*q_total/len(rows):.1f}% of all alerts.")
        print("    The universe lacks momentum movers → fix the universe / in-play selection.")
    elif q_tapehi == 0 and q_total > 0:
        print("  → UNDER-PRIORITIZED: quality setups ARE detected but 0 reached tape-confirmed")
        print("    HIGH/CRITICAL → fix priority assignment / tape gating for those setups.")
    else:
        print("  → Mixed; inspect per-setup rows above.")


if __name__ == "__main__":
    main()
