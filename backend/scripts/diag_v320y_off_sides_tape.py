#!/usr/bin/env python3
"""
v320y — OFF_SIDES_SHORT TAPE-GATE FORENSIC (READ-ONLY)

CONTEXT
-------
v320q showed off_sides_short fires a lot (≈637 alerts) but tape-confirms only
~3.8% of the time. off_sides_short is HARD-CAPPED at MEDIUM priority (no HIGH
branch exists in `_check_off_sides`), so it can NEVER auto-fire today regardless
of edge. Before deciding whether to add a HIGH branch (and what to gate it on),
we must answer ONE question with data:

    WHY does off_sides_short almost never earn tape confirmation?

ARCHITECTURAL FACTS (verified in enhanced_scanner.py):
  • _check_off_sides fires a SHORT when:
        regime ∈ {RANGE_BOUND, FADE}
        |dist_from_vwap| < 1.0      (price pinned near VWAP)
        daily_range_pct > 1.5       (wide-range day)
        dist_from_hod   < 1.0       (price is right at the high of day)
  • Tape confirmation for a SHORT requires raw tape_score ≤ -0.2.
        alert.tape_score (stored) = round((raw + 1.0) * 5.0, 2)  → 0..10 scale
        ⇒ SHORT confirms  ⟺  stored tape_score ≤ 4.0   (bearish tape)
        (LONG confirms ⟺ stored ≥ 6.0; the 4.0–6.0 band is "neutral".)

HYPOTHESIS to test: off_sides_short shorts price AT the high-of-day in a range.
At the instant price taps HOD the order-flow momentum is typically flat/bullish,
so a bearish tape (≤4.0) is structurally rare → the gate is self-defeating for
THIS setup, not a sign the setup is bad. This diag quantifies that vs a peer
SHORT-setup baseline and (defensively) checks realized edge.

NOTHING IS WRITTEN. Every Mongo read projects {"_id": 0} (live_alerts) and the
bot_trades section is fully read-only + field-name auto-detecting.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320y_off_sides_tape.py            # trailing 5 days
  .venv/bin/python backend/scripts/diag_v320y_off_sides_tape.py --days 10
  .venv/bin/python backend/scripts/diag_v320y_off_sides_tape.py --days 1
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
TARGET = "off_sides_short"

# Stored tape_score is on the 0..10 scale. SHORT confirmation ⟺ stored ≤ 4.0.
SHORT_CONFIRM_MAX = 4.0
LONG_CONFIRM_MIN = 6.0


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=8000)[env["DB_NAME"]]


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


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "  n/a"


def _prio(a):
    return str(a.get("priority", "")).strip().lower()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)

    def q(p):
        if n == 1:
            return xs[0]
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return xs[lo] * (1 - frac) + xs[hi] * frac

    return {
        "n": n, "min": xs[0], "p10": q(0.10), "p25": q(0.25),
        "median": q(0.50), "p75": q(0.75), "p90": q(0.90),
        "max": xs[-1], "mean": sum(xs) / n,
    }


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

    print(f"\n=== v320y OFF_SIDES_SHORT TAPE FORENSIC — trailing {days} day(s) "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===\n")

    rows = []
    for a in db.live_alerts.find({}, {"_id": 0}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if et and et >= start:
            rows.append(a)

    if not rows:
        print("No live_alerts in window. (live_alerts may be TTL-trimmed — try --days 1, "
              "or run intraday.)\n")
        return

    print(f"alerts in window: {len(rows)}\n")

    # ------------------------------------------------------------------
    # SECTION 1 — off_sides_short funnel
    # ------------------------------------------------------------------
    tgt = [a for a in rows if (a.get("setup_type") or "").strip().lower() == TARGET]
    print("=" * 78)
    print(f"SECTION 1 — {TARGET} funnel")
    print("=" * 78)
    if not tgt:
        print(f"  No {TARGET} alerts in window.\n")
    else:
        n = len(tgt)
        tape_ok = sum(1 for a in tgt if a.get("tape_confirmation") is True)
        prio = Counter(_prio(a) for a in tgt)
        print(f"  n alerts            : {n}")
        print(f"  tape_confirmation=T : {tape_ok}  ({_pct(tape_ok, n)})")
        print(f"  priority mix        : " +
              ", ".join(f"{k or '?'}={v}" for k, v in prio.most_common()))
        print(f"  HIGH+ (auto-fire)   : "
              f"{sum(prio[k] for k in ('high', 'critical'))}  "
              f"({_pct(sum(prio[k] for k in ('high', 'critical')), n)})  "
              f"[detector is MEDIUM-capped → expect 0]")

    # ------------------------------------------------------------------
    # SECTION 2 — tape_score distribution for off_sides_short
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"SECTION 2 — {TARGET} stored tape_score distribution (0..10 scale)")
    print(f"            SHORT confirms ⟺ tape_score ≤ {SHORT_CONFIRM_MAX:.1f}")
    print("=" * 78)
    ts = [_f(a.get("tape_score")) for a in tgt]
    q = _quantiles(ts)
    if not q:
        print("  No tape_score values stored on these alerts.\n")
    else:
        print(f"  n with score : {q['n']}  (missing: {len(tgt) - q['n']})")
        print(f"  min / p10    : {q['min']:.2f} / {q['p10']:.2f}")
        print(f"  p25 / median : {q['p25']:.2f} / {q['median']:.2f}")
        print(f"  p75 / p90    : {q['p75']:.2f} / {q['p90']:.2f}")
        print(f"  max / mean   : {q['max']:.2f} / {q['mean']:.2f}")
        below = sum(1 for x in ts if x is not None and x <= SHORT_CONFIRM_MAX)
        nearmiss = sum(1 for x in ts if x is not None and SHORT_CONFIRM_MAX < x <= SHORT_CONFIRM_MAX + 0.5)
        neutral = sum(1 for x in ts if x is not None and SHORT_CONFIRM_MAX < x < LONG_CONFIRM_MIN)
        bullish = sum(1 for x in ts if x is not None and x >= LONG_CONFIRM_MIN)
        print(f"\n  ≤ {SHORT_CONFIRM_MAX:.1f} (bearish, CONFIRMS short) : {below}  ({_pct(below, q['n'])})")
        print(f"  {SHORT_CONFIRM_MAX:.1f}–{SHORT_CONFIRM_MAX + 0.5:.1f} (near-miss)        : {nearmiss}  ({_pct(nearmiss, q['n'])})")
        print(f"  {SHORT_CONFIRM_MAX:.1f}–{LONG_CONFIRM_MIN:.1f} (neutral tape)       : {neutral}  ({_pct(neutral, q['n'])})")
        print(f"  ≥ {LONG_CONFIRM_MIN:.1f} (BULLISH tape)         : {bullish}  ({_pct(bullish, q['n'])})")
        print("\n  READ: if the mass sits in the neutral/bullish band (≥4.0), the tape is")
        print("        structurally absent at the short trigger (price tapping HOD) — the")
        print("        gate is self-defeating for THIS setup, not evidence it lacks edge.")

    # ------------------------------------------------------------------
    # SECTION 3 — peer SHORT-setup baseline
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("SECTION 3 — peer SHORT-setup tape baseline (is 3.8% an off_sides outlier?)")
    print("=" * 78)
    short_rows = [a for a in rows
                  if (a.get("direction") or "").strip().lower() == "short"
                  or (a.get("setup_type") or "").strip().lower().endswith("short")]
    by_setup = defaultdict(list)
    for a in short_rows:
        by_setup[(a.get("setup_type") or "?").strip().lower()].append(a)
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    rank_name = {0: "-", 1: "low", 2: "med", 3: "HIGH", 4: "CRIT"}
    print(f"  {'setup':<26} {'n':>5} {'tape_conf':>9} {'meanTS':>7} {'ceiling':>8}")
    rows_out = []
    for su, alist in by_setup.items():
        n = len(alist)
        tconf = sum(1 for a in alist if a.get("tape_confirmation") is True)
        tsv = [_f(a.get("tape_score")) for a in alist]
        tsv = [x for x in tsv if x is not None]
        mean_ts = (sum(tsv) / len(tsv)) if tsv else 0.0
        ceil = max((rank.get(_prio(a), 0) for a in alist), default=0)
        rows_out.append((n, su, tconf, mean_ts, ceil))
    for n, su, tconf, mean_ts, ceil in sorted(rows_out, reverse=True):
        mark = "  ← TARGET" if su == TARGET else ""
        print(f"  {su:<26} {n:>5} {_pct(tconf, n):>9} {mean_ts:>7.2f} "
              f"{rank_name[ceil]:>8}{mark}")
    all_tconf = sum(1 for a in short_rows if a.get("tape_confirmation") is True)
    print(f"\n  ALL shorts tape_conf : {_pct(all_tconf, len(short_rows))} "
          f"(baseline). If off_sides ≪ baseline → setup-specific structural miss.")

    # ------------------------------------------------------------------
    # SECTION 4 — regime mix for off_sides_short
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"SECTION 4 — {TARGET} market_regime mix")
    print("=" * 78)
    reg = Counter((a.get("market_regime") or "?") for a in tgt)
    if not reg:
        print("  (no alerts)")
    for r, c in reg.most_common():
        print(f"  {r:<20} {c:>5}  ({_pct(c, len(tgt))})")

    # ------------------------------------------------------------------
    # SECTION 5 — realized edge (DEFENSIVE, auto-detecting bot_trades schema)
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"SECTION 5 — {TARGET} realized edge from bot_trades (read-only)")
    print("=" * 78)
    try:
        bt = db["bot_trades"]
        sample = list(bt.find({}, {}).sort("created_at", -1).limit(800))
        if not sample:
            print("  bot_trades empty in recent window.\n")
        else:
            keys = Counter()
            for d in sample:
                keys.update(d.keys())
            setup_field = next((k for k in ("setup_type", "setup", "strategy", "pattern",
                                            "strategy_name") if keys.get(k)), None)
            r_field = next((k for k in ("r_multiple", "realized_r", "r", "pnl_r")
                            if keys.get(k)), None)
            pnl_field = next((k for k in ("realized_pnl", "pnl", "net_pnl", "pnl_after_fees",
                                          "gross_pnl") if keys.get(k)), None)
            print(f"  detected fields → setup='{setup_field}'  R='{r_field}'  pnl='{pnl_field}'")
            if not setup_field:
                print("  Could not detect a setup field — skipping edge calc.\n")
            else:
                matches = [d for d in sample
                           if str(d.get(setup_field, "")).strip().lower() == TARGET]
                print(f"  {TARGET} trades in last {len(sample)} bot_trades: {len(matches)}")
                if matches:
                    rs = [_f(d.get(r_field)) for d in matches] if r_field else []
                    rs = [x for x in rs if x is not None]
                    if rs:
                        wins = sum(1 for x in rs if x > 0)
                        print(f"    win rate (R>0) : {_pct(wins, len(rs))}  (n={len(rs)})")
                        print(f"    mean R         : {sum(rs) / len(rs):+.2f}")
                    pn = [_f(d.get(pnl_field)) for d in matches] if pnl_field else []
                    pn = [x for x in pn if x is not None]
                    if pn:
                        print(f"    sum pnl        : {sum(pn):+.2f}  mean {sum(pn) / len(pn):+.2f}")
                    if not rs and not pn:
                        print("    (no R/pnl fields populated on matches)")
    except Exception as e:
        print(f"  bot_trades probe skipped: {e}")

    print("\n=== READING THE RESULT ===")
    print("• SECTION 2 mass ≥4.0 + SECTION 3 off_sides ≪ peer baseline →")
    print("    the tape gate is STRUCTURALLY wrong for off_sides_short (shorting into")
    print("    HOD strength). A HIGH branch gated on tape_confirmation would still never")
    print("    fire. Promotion (if justified by SECTION 5 edge) must gate on a DIFFERENT")
    print("    signal (e.g. rejection wick / dist_from_hod tightness / RR), NOT tape.")
    print("• If SECTION 5 edge is negative/thin → do NOT promote; the low fire-rate is")
    print("    protective. Close as 'working as intended (correctly suppressed)'.")
    print("• If off_sides tape% ≈ peer baseline → 3.8% is just short-side tape difficulty,")
    print("    not setup-specific; re-frame the question around edge, not the gate.\n")


if __name__ == "__main__":
    main()
