#!/usr/bin/env python3
"""
v320q — PRIORITY ATTRIBUTION BY STYLE (READ-ONLY): why do intraday/scalp alerts
under-reach the HIGH-priority auto-fire gate?

CONTEXT
-------
v320o proved a CONVERSION problem: CARRY alerts hit HIGH priority ~55% vs
INTRADAY ~20%, and HIGH is the auto-fire threshold
(`enhanced_scanner._auto_execute_min_priority = AlertPriority.HIGH`). v320p/v320u
removed the A+→multi_day horizon hijack; THIS diag isolates the *secondary* lever:
the priority scorer itself.

KEY ARCHITECTURAL FACT (verified in enhanced_scanner.py detector branches):
priority is NOT a single formula — each detector hard-codes its own ceiling.
The overwhelming pattern is:
    priority = AlertPriority.HIGH if tape.confirmation_for_<dir> else AlertPriority.MEDIUM
and several detectors are HARD-CAPPED at MEDIUM (no HIGH branch exists at all).

So the intraday HIGH-gap decomposes into TWO distinct, separable causes:
  (1) STRUCTURAL CEILING  — the setup's detector can never emit HIGH/CRITICAL.
  (2) TAPE-GATE DEFICIT   — a HIGH-capable setup failed `tape_confirmation`.
  (3) RESIDUAL            — HIGH-capable + tape-confirmed but still not HIGH
                            (some other in-branch condition, e.g. distance/RR).

This script classifies every non-HIGH alert into one of those buckets, rolls the
result up INTRADAY vs CARRY, and reports the scorer inputs
(tape_confirmation / tape_score / in_play_score / tqs_score / smb_big_picture /
smb_is_a_plus / catalyst) so we can SEE which input the priority gate keys on and
whether it structurally penalizes intraday context — BEFORE proposing any
calibration (NOT a sizing change).

The empirical per-setup priority ceiling is derived FROM THE DATA (max priority
ever observed for that setup across the whole window), so it reflects the live
detector wiring without hard-coding a static map that could drift.

NOTHING IS WRITTEN. All Mongo reads project {"_id": 0}.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320q_priority_attribution.py            # trailing 5 days
  .venv/bin/python backend/scripts/diag_v320q_priority_attribution.py --days 1   # today only
  .venv/bin/python backend/scripts/diag_v320q_priority_attribution.py --days 10
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
INTRADAY_STYLES = {"scalp", "intraday"}
CARRY_STYLES = {"multi_day", "swing", "position", "investment"}

# auto-fire tier (priority >= HIGH). CRITICAL also clears the bar.
FIRE_TIER = {"high", "critical"}

# v320p + v320u (A+ horizon-hijack fix) committed on the DGX 2026-06-16.
# Days on/after this are post-fix; days before are pre-fix (mix not directly
# comparable for trade_style attribution).
V320P_FIX_DATE = "2026-06-16"


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


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
    return f"{(100.0 * n / d):.1f}%" if d else "  n/a"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else 0.0


def _prio(a):
    return str(a.get("priority", "")).strip().lower()


def main():
    days = 5
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 5

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n=== v320q PRIORITY ATTRIBUTION BY STYLE — trailing {days} day(s) "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===\n")

    rows = []
    per_day = Counter()
    for a in db.live_alerts.find({}, {"_id": 0}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start:
            a["_et_day"] = et.strftime("%Y-%m-%d")
            rows.append(a)
            per_day[a["_et_day"]] += 1

    if not rows:
        print("No live_alerts in window. (live_alerts may be TTL-trimmed — try --days 1, "
              "or run intraday.)\n")
        return

    print(f"alerts in window: {len(rows)}")
    print("per ET day  (★ = post-v320p/v320u A+ fix):")
    for d in sorted(per_day):
        star = " ★" if d >= V320P_FIX_DATE else ""
        print(f"    {d}  {per_day[d]:>5}{star}")
    post = sum(n for d, n in per_day.items() if d >= V320P_FIX_DATE)
    print(f"  post-v320p fraction: {_pct(post, len(rows))}  "
          f"(trade_style attribution is most trustworthy on post-fix days)\n")

    # ---- empirical per-setup priority CEILING (max priority ever observed) ----
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    setup_max = defaultdict(int)            # setup -> max rank seen
    setup_count = Counter()
    for a in rows:
        su = (a.get("setup_type") or "?").strip().lower()
        setup_count[su] += 1
        setup_max[su] = max(setup_max[su], rank.get(_prio(a), 0))
    HIGH_CAPABLE = {su for su, r in setup_max.items() if r >= 3}   # reaches HIGH/CRIT somewhere

    # ---- per trade_style funnel + scorer-input means ----
    gen = Counter(); fire = Counter(); crit = Counter()
    tape_ok = Counter(); smbA = Counter()
    tape_score_by = defaultdict(list); inplay_by = defaultdict(list)
    tqs_by = defaultdict(list); bigpic_by = defaultdict(list)
    for a in rows:
        st = (a.get("trade_style") or "?").strip().lower()
        gen[st] += 1
        p = _prio(a)
        if p in FIRE_TIER:
            fire[st] += 1
        if p == "critical":
            crit[st] += 1
        if a.get("tape_confirmation") is True:
            tape_ok[st] += 1
        if a.get("smb_is_a_plus") is True:
            smbA[st] += 1
        tape_score_by[st].append(a.get("tape_score"))
        inplay_by[st].append(a.get("in_play_score"))
        tqs_by[st].append(a.get("tqs_score"))
        bigpic_by[st].append(a.get("smb_big_picture"))

    print("FUNNEL per trade_style  (gen → HIGH+ → CRIT → tape_conf → smb_A+ | mean scorer inputs)")
    print(f"  {'style':<12} {'gen':>5} {'HIGH+':>7} {'CRIT':>6} {'tape':>7} {'smbA+':>7} "
          f"| {'tapeSc':>6} {'inPlay':>6} {'TQS':>6} {'bigPic':>6}  group")
    for st, g in gen.most_common():
        print(f"  {st:<12} {g:>5} "
              f"{_pct(fire[st], g):>7} {_pct(crit[st], g):>6} "
              f"{_pct(tape_ok[st], g):>7} {_pct(smbA[st], g):>7} "
              f"| {_mean(tape_score_by[st]):>6.1f} {_mean(inplay_by[st]):>6.1f} "
              f"{_mean(tqs_by[st]):>6.1f} {_mean(bigpic_by[st]):>6.1f}  {_grp(st)}")

    # ---- group rollup ----
    def _grpsum(c):
        out = Counter()
        for st, n in c.items():
            out[_grp(st)] += n
        return out

    def _grpmean(d):
        out = defaultdict(list)
        for st, xs in d.items():
            out[_grp(st)].extend(xs)
        return out

    gG, fG, cG, tG, aG = map(_grpsum, (gen, fire, crit, tape_ok, smbA))
    tsG, ipG, tqG, bpG = map(_grpmean, (tape_score_by, inplay_by, tqs_by, bigpic_by))
    print("\nGROUP ROLLUP:")
    for grp in ("INTRADAY", "CARRY", "OTHER"):
        g = gG[grp]
        if not g:
            continue
        print(f"  {grp:<9} gen={g:<5} HIGH+={_pct(fG[grp], g):<7} CRIT={_pct(cG[grp], g):<7} "
              f"tape={_pct(tG[grp], g):<7} smbA+={_pct(aG[grp], g):<7} "
              f"| tapeSc={_mean(tsG[grp]):.1f} inPlay={_mean(ipG[grp]):.1f} "
              f"TQS={_mean(tqG[grp]):.1f} bigPic={_mean(bpG[grp]):.1f}")

    # ---- THE ATTRIBUTION: why is each non-HIGH alert not HIGH+? ----
    # ceiling_medium : setup never reaches HIGH/CRIT anywhere in window (structural)
    # tape_gate_miss : HIGH-capable setup, but tape_confirmation=False (tape lever)
    # residual       : HIGH-capable + tape-confirmed, still < HIGH (other in-branch gate)
    cause = defaultdict(Counter)            # group -> cause -> n
    for a in rows:
        if _prio(a) in FIRE_TIER:
            continue
        grp = _grp(a.get("trade_style"))
        su = (a.get("setup_type") or "?").strip().lower()
        if su not in HIGH_CAPABLE:
            cause[grp]["ceiling_medium"] += 1
        elif a.get("tape_confirmation") is not True:
            cause[grp]["tape_gate_miss"] += 1
        else:
            cause[grp]["residual"] += 1

    print("\nATTRIBUTION OF THE NON-HIGH POPULATION  (why each alert missed the auto-fire bar)")
    print(f"  {'group':<9} {'non-HIGH':>9} {'ceiling':>9} {'tapeMiss':>9} {'residual':>9}")
    for grp in ("INTRADAY", "CARRY", "OTHER"):
        c = cause[grp]
        tot = sum(c.values())
        if not tot:
            continue
        print(f"  {grp:<9} {tot:>9} "
              f"{c['ceiling_medium']:>4}/{_pct(c['ceiling_medium'], tot):<5} "
              f"{c['tape_gate_miss']:>4}/{_pct(c['tape_gate_miss'], tot):<5} "
              f"{c['residual']:>4}/{_pct(c['residual'], tot):<5}")

    # ---- per-setup ceiling table (intraday-group setups first) ----
    print("\nPER-SETUP CEILING & TAPE  (max priority ever observed = de-facto ceiling)")
    print(f"  {'setup':<26} {'n':>5} {'ceiling':>8} {'HIGH+':>7} {'tape_conf':>9}  capable?")
    rank_name = {0: "-", 1: "low", 2: "medium", 3: "HIGH", 4: "CRIT"}
    # recompute per-setup HIGH+ and tape rates
    su_fire = Counter(); su_tape = Counter()
    su_grp = {}
    for a in rows:
        su = (a.get("setup_type") or "?").strip().lower()
        su_grp[su] = _grp(a.get("trade_style"))
        if _prio(a) in FIRE_TIER:
            su_fire[su] += 1
        if a.get("tape_confirmation") is True:
            su_tape[su] += 1
    ordered = sorted(setup_count.items(),
                     key=lambda kv: (su_grp.get(kv[0]) != "INTRADAY", -kv[1]))
    for su, n in ordered:
        cap = "yes" if su in HIGH_CAPABLE else "NO (medium-capped)"
        print(f"  {su:<26} {n:>5} {rank_name[setup_max[su]]:>8} "
              f"{_pct(su_fire[su], n):>7} {_pct(su_tape[su], n):>9}  {cap}")

    print("\n=== READING THE RESULT ===")
    print("• INTRADAY 'ceiling' >> CARRY 'ceiling'  → STRUCTURAL: intraday alerts are")
    print("    dominated by MEDIUM-capped detectors. Fix = add a HIGH branch (tape/")
    print("    in-play/RR-gated) to those setups' detectors. NOT a sizing change.")
    print("• INTRADAY 'tapeMiss' dominates          → the tape gate is the choke. Compare")
    print("    GROUP tape% + mean tapeSc: if intraday tape-confirms far less, either tape")
    print("    confirmation is harder to earn intraday, or the HIGH branch over-weights it.")
    print("• If GROUP scorer-input means (inPlay/TQS/bigPic) are similar across groups but")
    print("    HIGH+ differs sharply → priority keys on tape/ceiling, NOT quality → the")
    print("    formula structurally penalizes intraday regardless of edge.")
    print("• Gate any calibration on a post-v320p (★) sample so the A+ fix isn't re-litigated.\n")


if __name__ == "__main__":
    main()
