#!/usr/bin/env python3
"""
v320o — ALERT FUNNEL BY STYLE (READ-ONLY): where do intraday/scalp alerts die?

v320n proved it's a CONVERSION problem (intraday alerts plentiful, fire ~1.8% vs
carry ~5.3%). This drills the funnel: for TODAY's live_alerts, groups by
trade_style and shows what fraction reach HIGH priority / auto_execute_eligible /
A or A+ TQS grade / smb_is_a_plus. If intraday reaches the auto-fire bar far less
often than carry, the GRADE/PRIORITY gate is the choke (not sizing, not detection).

Also surfaces the A+→multi_day override footprint: how many alerts whose SETUP is
an intraday/scalp setup got stamped trade_style=multi_day (enhanced_scanner.py
L748-750 forces multi_day + 5R when smb_is_a_plus).

NOTHING is written.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320o_alert_funnel.py [YYYY-MM-DD]
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
INTRADAY_STYLES = {"scalp", "intraday"}
CARRY_STYLES = {"multi_day", "swing", "position", "investment"}

# setups whose NATURAL horizon is intraday/scalp (from enhanced_scanner
# _intraday_setups / _intraday_only_setups + all-day RTH scalps)
INTRADAY_SETUPS = {
    "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
    "back_through_open", "up_through_open", "opening_drive", "orb", "hitchhiker",
    "spencer_scalp", "9_ema_scalp", "abc_scalp", "vwap_continuation",
    "vwap_bounce", "vwap_fade", "premarket_high_break", "the_3_30_trade",
    "gap_fade", "gap_give_go", "gap_pick_roll", "rubber_band", "fading_bounce",
    "tidal_wave", "hod_breakout", "fashionably_late", "off_sides", "backside",
    "second_chance", "big_dog", "puppy_dog", "bouncy_ball", "spencer_scalp",
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
    d = (datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
         if date_str else datetime.now(ET))
    s = d.replace(hour=0, minute=0, second=0, microsecond=0)
    e = s.replace(hour=23, minute=59, second=59, microsecond=999000)
    return s, e, s.strftime("%Y-%m-%d")


def _to_et(v):
    if isinstance(v, str) and len(v) >= 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
        except Exception:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(ET)
    return None


def _grp(style):
    s = (style or "").strip().lower()
    if s in INTRADAY_STYLES:
        return "INTRADAY"
    if s in CARRY_STYLES:
        return "CARRY"
    return "OTHER"


def _pct(n, d):
    return f"{(100.0*n/d):.1f}%" if d else "  n/a"


def main():
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    db = _load_db()
    s, e, day = _day_bounds(date_arg)
    print(f"\n=== v320o ALERT FUNNEL BY STYLE — {day} ET ===\n")

    rows = []
    for a in db.live_alerts.find({}, {"_id": 0}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and s <= et <= e:
            rows.append(a)
    print(f"today's live_alerts: {len(rows)}\n")

    # per-style funnel
    gen = Counter()
    high = Counter()
    autoel = Counter()
    grade_a = Counter()
    aplus = Counter()
    for a in rows:
        st = (a.get("trade_style") or "?").strip().lower()
        gen[st] += 1
        if str(a.get("priority", "")).lower() == "high":
            high[st] += 1
        if a.get("auto_execute_eligible") is True:
            autoel[st] += 1
        if str(a.get("tqs_grade", "")).upper() in ("A", "A+"):
            grade_a[st] += 1
        if a.get("smb_is_a_plus") is True:
            aplus[st] += 1

    print("FUNNEL per trade_style  (gen → HIGH-pri → auto_exec_eligible → TQS A/A+ → smb_A+)")
    hdr = f"  {'style':<12} {'gen':>5} {'HIGH':>6} {'auto_el':>9} {'A/A+':>7} {'smbA+':>7}   group"
    print(hdr)
    for st, g in gen.most_common():
        print(f"  {st:<12} {g:>5} "
              f"{high[st]:>3}/{_pct(high[st],g):<5} "
              f"{autoel[st]:>3}/{_pct(autoel[st],g):<5} "
              f"{grade_a[st]:>3}/{_pct(grade_a[st],g):<5} "
              f"{aplus[st]:>3}/{_pct(aplus[st],g):<5}  {_grp(st)}")

    # group rollup
    def _grpsum(c):
        out = Counter()
        for st, n in c.items():
            out[_grp(st)] += n
        return out
    gG, hG, aG, gaG, apG = map(_grpsum, (gen, high, autoel, grade_a, aplus))
    print("\nGROUP ROLLUP:")
    for grp in ("INTRADAY", "CARRY", "OTHER"):
        g = gG[grp]
        print(f"  {grp:<9} gen={g:<5} HIGH={_pct(hG[grp],g):<7} "
              f"auto_el={_pct(aG[grp],g):<7} A/A+={_pct(gaG[grp],g):<7} smbA+={_pct(apG[grp],g)}")

    # A+ override footprint: intraday-setup alerts stamped multi_day
    print("\nA+→multi_day OVERRIDE FOOTPRINT (enhanced_scanner.py L748-750):")
    override = Counter()
    override_setups = Counter()
    for a in rows:
        st = (a.get("trade_style") or "").strip().lower()
        su = (a.get("setup_type") or "").strip().lower()
        if st == "multi_day" and su in INTRADAY_SETUPS:
            override[su] += 1
            override_setups[su] += 1
    tot = sum(override.values())
    print(f"  intraday-natured setups stamped multi_day: {tot}")
    for su, n in override.most_common(15):
        print(f"     {su:<24} {n:>3}")
    if tot == 0:
        print("     (none today — override not the dominant driver this session)")

    print("\n=== READING THE RESULT ===")
    print("• If GROUP ROLLUP shows INTRADAY auto_el%% << CARRY auto_el%% ->")
    print("    the auto-exec/priority/grade gate is the choke for intraday.")
    print("• Big A+ override footprint -> the L748-750 quality→horizon conflation")
    print("    is converting your best intraday signals into multi-day carries.\n")


if __name__ == "__main__":
    main()
