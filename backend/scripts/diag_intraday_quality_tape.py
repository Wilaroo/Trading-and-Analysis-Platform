#!/usr/bin/env python3
"""
INTRADAY QUALITY tape breakdown (read-only) — excludes daily/swing detectors.

The daily/swing setups (DAILY_DETECTORS: power_trend_stack, stage_2_breakout,
pocket_pivot, vcp_breakout, weekly_breakout, rs_leader_break, two_hundred_day_*, etc.)
are watchlist-by-design and never get intraday tape — so they pollute a blanket
"quality" view. This script looks ONLY at the genuinely INTRADAY momentum setups that
DO go through the snapshot/tape path, grouped by setup, so we can see whether they
have real tape_signals (and just fail the >=0.2 threshold) or also come through with
no tape at all.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_intraday_quality_tape.py [DATE]   # default = today ET
"""
import sys
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Intraday momentum/with-trend setups (NOT in DAILY_DETECTORS). These SHOULD get
# intraday tape + be auto-execute candidates.
INTRADAY_QUALITY = {
    "gap_give_go", "vwap_continuation", "9_ema_scalp", "second_chance", "big_dog",
    "bouncy_ball", "first_vwap_pullback", "the_3_30_trade", "premarket_high_break",
    "range_break", "opening_drive", "trend_continuation",
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
        "setup_type": {"$in": list(INTRADAY_QUALITY)},
    }, {"setup_type": 1, "direction": 1, "priority": 1, "tape_score": 1,
        "tape_signals": 1, "tape_confirmation": 1, "rvol": 1}))

    print(f"INTRADAY QUALITY alerts on {day}: {len(rows)}\n")
    if not rows:
        print("None. Try a recent trading day as DATE arg.")
        return

    g = defaultdict(lambda: {"n": 0, "hi": 0, "tapeHI": 0, "ts": [], "mom": Counter(),
                             "spread": Counter(), "rvol": [], "has_tape_obj": 0})
    for r in rows:
        s = r.get("setup_type") or "?"
        p = str(r.get("priority") or "").lower()
        a = g[s]
        a["n"] += 1
        a["ts"].append(float(r.get("tape_score") or 0.0))
        if r.get("rvol") is not None:
            a["rvol"].append(float(r.get("rvol") or 0.0))
        sig = r.get("tape_signals") or []
        if len(sig) >= 3:
            a["has_tape_obj"] += 1
            a["spread"][sig[0]] += 1
            a["mom"][sig[2]] += 1
        if p in ("high", "critical"):
            a["hi"] += 1
            if r.get("tape_confirmation"):
                a["tapeHI"] += 1

    print(f"{'setup':<22}{'n':>4}{'hi/crit':>8}{'tapeHI':>7}{'hasTapeObj':>11}{'medRVOL':>8}{'medTS':>7}")
    print("-" * 72)
    for s, a in sorted(g.items(), key=lambda kv: -kv[1]["n"]):
        med_rvol = statistics.median(a["rvol"]) if a["rvol"] else 0.0
        med_ts = statistics.median(a["ts"]) if a["ts"] else 0.0
        print(f"{s:<22}{a['n']:>4}{a['hi']:>8}{a['tapeHI']:>7}{a['has_tape_obj']:>11}"
              f"{med_rvol:>8.2f}{med_ts:>7.2f}")

    # detail momentum/spread for the biggest intraday setup
    biggest = max(g.items(), key=lambda kv: kv[1]["hi"])
    s, a = biggest
    print(f"\nDetail for biggest hi/crit intraday setup: {s}")
    print(f"  has_tape_obj (tape_signals populated): {a['has_tape_obj']}/{a['n']}")
    print(f"  spread signal: " + (", ".join(f"{k}={v}" for k, v in a['spread'].most_common()) or "(none — no tape obj)"))
    print(f"  momentum signal: " + (", ".join(f"{k}={v}" for k, v in a['mom'].most_common()) or "(none — no tape obj)"))
    if a["rvol"]:
        ge2 = sum(1 for v in a["rvol"] if v >= 2.0)
        band = sum(1 for v in a["rvol"] if 1.5 <= v < 2.0)
        print(f"  rvol: median={statistics.median(a['rvol']):.2f}  >=2.0: {ge2}  1.5-2.0: {band}")
    print("\nVERDICT:")
    print("  • hasTapeObj≈0 → this intraday setup ALSO bypasses the tape path (a wiring bug like")
    print("    the daily detectors) → fix: route it through tape + auto_execute_eligible.")
    print("  • hasTapeObj high but tapeHI=0 & medRVOL in 1.5-2.0 → tape's rvol>=2 momentum gate")
    print("    is misaligned with the setup floor → fix: graduated momentum bonus.")


if __name__ == "__main__":
    main()
