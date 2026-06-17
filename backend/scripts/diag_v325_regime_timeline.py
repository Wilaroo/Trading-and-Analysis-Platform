#!/usr/bin/env python3
"""
v325 — REGIME / MODE TIMELINE (READ-ONLY)

v324 found the FIRE funnel's TOP gate: 100% CAUTIOUS mode, regime_state=HOLD,
regime_score pinned at 68 — raising GO to 50 + activating regime_suppression,
which is why ~nothing trades. KEY question: is that defensive posture a
legitimate current-conditions call, or is the regime classifier STUCK?

This diag walks confidence_gate_log day-by-day (ET) over N days and shows, per
day: trading_mode mix, regime_state mix, regime_score range, GO count and GO%.
If mode is cautious/defensive and regime_score is static for many days straight,
the classifier is likely stale (a fixable upstream lever). If it varies day to
day, the current caution is a real-time call (leave it; few setups deserve GO).

Usage:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v325_regime_timeline.py --days 21
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

ET = ZoneInfo("America/New_York")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_et(s):
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
    except ValueError:
        return None


def main():
    days = 21
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 21
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = list(db.confidence_gate_log.find(
        {"timestamp": {"$gte": iso}},
        {"_id": 0, "decision": 1, "trading_mode": 1, "regime_state": 1,
         "regime_score": 1, "timestamp": 1}))

    print(f"\n=== v325 REGIME / MODE TIMELINE — last {days}d ===\n")
    if not rows:
        print("  No decisions in window.\n"); return

    by_day = defaultdict(list)
    for r in rows:
        et = _to_et(r.get("timestamp"))
        if et:
            by_day[et.strftime("%Y-%m-%d")].append(r)

    print(f"  {'day':<12} {'dec':>5} {'GO':>4} {'GO%':>4}  {'mode(top)':<22} "
          f"{'regime_state(top)':<18} {'regScore min/med/max':<20}")
    all_scores = set()
    for day in sorted(by_day):
        rs = by_day[day]
        n = len(rs)
        go = sum(1 for r in rs if r.get("decision") == "GO")
        modes = Counter(str(r.get("trading_mode") or "?") for r in rs)
        states = Counter(str(r.get("regime_state") or "?") for r in rs)
        sc = sorted(x for x in (_f(r.get("regime_score")) for r in rs) if x is not None)
        all_scores.update(sc)
        mode_top = ", ".join(f"{k}:{v}" for k, v in modes.most_common(2))
        state_top = ", ".join(f"{k}:{v}" for k, v in states.most_common(2))
        scr = f"{sc[0]:.0f}/{sc[len(sc)//2]:.0f}/{sc[-1]:.0f}" if sc else "-"
        print(f"  {day:<12} {n:>5} {go:>4} {100.0*go/n:>3.0f}%  {mode_top:<22} "
              f"{state_top:<18} {scr:<20}")

    print("\n" + "=" * 72)
    print("STUCK-CLASSIFIER CHECK")
    print("=" * 72)
    mode_all = Counter(str(r.get("trading_mode") or "?") for r in rows)
    state_all = Counter(str(r.get("regime_state") or "?") for r in rows)
    print(f"  distinct regime_score values seen : {len(all_scores)}  "
          f"({sorted(all_scores)[:12]}{'…' if len(all_scores) > 12 else ''})")
    print(f"  trading_mode mix (all)            : " + ", ".join(f"{k}={v}" for k, v in mode_all.most_common()))
    print(f"  regime_state mix (all)            : " + ", ".join(f"{k}={v}" for k, v in state_all.most_common()))
    days_seen = len(by_day)
    caut_def = sum(1 for r in rows if str(r.get("trading_mode") or "").lower() in ("cautious", "defensive"))
    print(f"  cautious/defensive share          : {100.0*caut_def/len(rows):.0f}% of decisions over {days_seen} days")

    print("\n=== READING THE RESULT ===")
    print("• Few distinct regime_score values + cautious/HOLD every day → classifier is STUCK")
    print("    (stale/coarse). It perpetually starves GO regardless of real conditions →")
    print("    the upstream lever: fix the regime→mode trigger or the score's update cadence.")
    print("• regime_score & mode VARY across days (some normal/aggressive days) → the current")
    print("    caution is a real-time call; the system is correctly selective right now.")
    print("• GO% per day shows whether ANY day let trades flow, and how today compares.\n")


if __name__ == "__main__":
    main()
