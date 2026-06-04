#!/usr/bin/env python3
"""
diag_setup_quality_truth.py  (READ-ONLY)
========================================
Two audits in one run, both read-only (writes nothing):

PART A — WIN-RATE INTEGRITY
  Are the 12-34% win rates feeding the SETUP pillar + F-gates TRUSTWORTHY,
  or polluted? Per setup_type it separates:
    • COST-POISONING  — gross winners (price hit target) flipped to net
      losers by commission/fees. Smoking gun for scalps.
    • NON-EDGE EXITS  — closes that don't measure the setup's edge
      (external / reconciled / EOD / operator / stale / zombie).
    • PAPER pollution — stats dominated by paper fills.
    • RECONCILED rows — synthetic orphan adoptions w/ 2% brackets, not the
      setup's real SL/TP.
    • Scalp-vs-swing mixing (median hold).

PART B — OVER-BLOCKING REVIEW
  Reads the ACTUAL rolling `setup_grade_records` (30d) the F-gate uses,
  classifies each F as HARD-F (clearly dead) vs BORDERLINE-F (avg_r near 0
  / small sample → maybe recoverable), lists the DISABLED_SETUPS blocklist,
  and counts how many B+ alerts each blocked setup is currently suppressing.

Mongo only (MONGO_URL / DB_NAME from backend/.env).
Run from repo root on the DGX:
    .venv/bin/python backend/scripts/diag_setup_quality_truth.py --days 30
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

GENUINE_HINTS = ("stop", "target", "trail", "take_profit", "profit", "_sl", "_tp",
                 "scale", "tp1", "tp2", "tp3", "breakeven")
NONEDGE_HINTS = ("external", "reconcil", "operator", "eod", "stale", "zombie",
                 "phantom", "consolidated", "simulation", "cooldown", "manual",
                 "flatten", "purge", "expire", "kill", "panic")


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("ERROR: MONGO_URL / DB_NAME not set.")
        sys.exit(1)
    return MongoClient(url, serverSelectionTimeoutMS=4000)[name]


def _num(v):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def _r_of(t):
    """Net r_multiple — prefer stored, else realized_pnl/risk_amount."""
    r = _num(t.get("r_multiple"))
    if r is not None:
        return r
    pnl, risk = _num(t.get("realized_pnl")), _num(t.get("risk_amount"))
    if pnl is not None and risk and risk > 0:
        return pnl / risk
    return None


def _classify_exit(cr):
    s = (cr or "").lower()
    if not s:
        return "unknown"
    if any(h in s for h in NONEDGE_HINTS):
        return "non_edge"
    if any(h in s for h in GENUINE_HINTS):
        return "genuine"
    return "other"


def _cost_flip(t):
    """True if GROSS pnl was a winner but NET (after cost) is a loser/zero."""
    g = _num(t.get("gross_pnl"))
    n = _num(t.get("realized_pnl"))
    if g is None or n is None:
        return False
    return g > 0 and n <= 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-n", type=int, default=3, help="min closed trades to report a setup")
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    print(f"\n{'#'*100}\n#  SETUP-QUALITY TRUTH AUDIT   window={args.days}d (since {cutoff_str})\n{'#'*100}")

    # ── load closed trades ──────────────────────────────────────────────
    proj = {"_id": 0, "setup_type": 1, "trade_style": 1, "trade_type": 1,
            "entered_by": 1, "realized_pnl": 1, "gross_pnl": 1, "commission": 1,
            "fees": 1, "risk_amount": 1, "r_multiple": 1, "close_reason": 1,
            "exit_reason": 1, "hold_seconds": 1, "reclassified": 1,
            "executed_at": 1, "closed_at": 1, "learning_only": 1, "entry_context": 1}
    rows = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": cutoff_str}}, proj))
    if not rows:  # tolerate datetime closed_at
        rows = list(db["bot_trades"].find(
            {"status": "closed", "closed_at": {"$gte": cutoff}}, proj))
    # drop learning_only micro trades (same as grading service)
    rows = [t for t in rows if not (t.get("learning_only") is True
            or (t.get("entry_context") or {}).get("learning_only") is True)]
    print(f"\nClosed non-learning trades in window: {len(rows)}")
    tt = Counter((t.get("trade_type") or "?") for t in rows)
    print(f"trade_type split: " + "  ".join(f"{k}={v}" for k, v in tt.most_common()))
    if tt.get("paper", 0) > 0.6 * len(rows):
        print("  ⚠ Majority PAPER — win rates reflect paper fills/commissions, "
              "not live edge.")

    # group by setup
    by_setup = defaultdict(list)
    for t in rows:
        st = t.get("setup_type")
        if st:
            by_setup[st].append(t)

    # ── PART A: per-setup integrity ─────────────────────────────────────
    print(f"\n{'='*100}\nPART A — WIN-RATE INTEGRITY (per setup_type, n>= {args.min_n})\n{'='*100}")
    hdr = (f"{'setup_type':<24}{'n':>4}{'net_wr':>7}{'net_R':>7}{'grs_wr':>7}"
           f"{'cost_flip':>10}{'recon%':>7}{'nonedge%':>9}{'medHold':>8}")
    print(hdr); print("-" * len(hdr))
    suspect = []
    rprep = []  # (volume, line) for sort
    for st, trades in by_setup.items():
        rs = [_r_of(t) for t in trades]
        rs = [r for r in rs if r is not None]
        n = len(rs)
        if n < args.min_n:
            continue
        net_wr = 100.0 * sum(1 for r in rs if r > 0) / n
        net_avg_r = statistics.fmean(rs)
        # gross win rate
        gross = [_num(t.get("gross_pnl")) for t in trades]
        gross = [g for g in gross if g is not None]
        grs_wr = 100.0 * sum(1 for g in gross if g > 0) / len(gross) if gross else float("nan")
        cost_flips = sum(1 for t in trades if _cost_flip(t))
        recon = 100.0 * sum(1 for t in trades
                            if "reconcil" in (t.get("entered_by") or "").lower()) / len(trades)
        exits = Counter(_classify_exit(t.get("close_reason") or t.get("exit_reason")) for t in trades)
        nonedge_pct = 100.0 * exits.get("non_edge", 0) / len(trades)
        holds = [_num(t.get("hold_seconds")) for t in trades]
        holds = [h for h in holds if h is not None]
        med_hold = statistics.median(holds) if holds else 0
        med_hold_s = (f"{med_hold/60:.0f}m" if med_hold < 3600
                      else f"{med_hold/3600:.1f}h")
        gw = f"{grs_wr:5.1f}" if grs_wr == grs_wr else "  n/a"
        line = (f"{st:<24}{n:>4}{net_wr:>6.1f}%{net_avg_r:>7.2f}{gw:>7}"
                f"{cost_flips:>10}{recon:>6.0f}%{nonedge_pct:>8.0f}%{med_hold_s:>8}")
        rprep.append((n, line))
        # flags
        gap = (grs_wr - net_wr) if grs_wr == grs_wr else 0
        why = []
        if gap >= 15:
            why.append(f"COST-POISON (gross_wr {grs_wr:.0f}% vs net {net_wr:.0f}%)")
        if cost_flips >= max(2, 0.2 * n):
            why.append(f"{cost_flips} cost-flipped winners")
        if recon >= 40:
            why.append(f"{recon:.0f}% reconciled rows")
        if nonedge_pct >= 40:
            why.append(f"{nonedge_pct:.0f}% non-edge exits")
        if why:
            suspect.append((st, n, net_avg_r, "; ".join(why)))
    for _, line in sorted(rprep, key=lambda x: -x[0]):
        print(line)

    print(f"\n  SUSPECT setups (stats likely NOT measuring true edge):")
    if suspect:
        for st, n, avg_r, why in sorted(suspect, key=lambda x: x[1], reverse=True):
            print(f"    • {st:<22} n={n:<4} avg_r={avg_r:+.2f}  → {why}")
    else:
        print("    none — win/avg_r look like they reflect genuine SL/TP outcomes.")

    # ── PART B: over-blocking review ────────────────────────────────────
    print(f"\n{'='*100}\nPART B — OVER-BLOCKING REVIEW (rolling 30d setup_grade_records = the F-gate source)\n{'='*100}")
    # rolling rollup: aggregate setup_grade_records last 30d per setup
    grcut = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    grrows = list(db["setup_grade_records"].find(
        {"trading_date": {"$gte": grcut}},
        {"_id": 0, "setup_type": 1, "trades_count": 1, "win_rate": 1,
         "avg_r": 1, "total_r": 1}))
    roll = defaultdict(lambda: {"n": 0, "tr": 0.0, "w": 0.0})
    for r in grrows:
        st = r.get("setup_type")
        n = int(r.get("trades_count") or 0)
        if not st or n <= 0:
            continue
        roll[st]["n"] += n
        roll[st]["tr"] += float(r.get("total_r") or (float(r.get("avg_r") or 0) * n))
        roll[st]["w"] += float(r.get("win_rate") or 0) * n
    cards = []
    for st, d in roll.items():
        n = d["n"]
        avg_r = d["tr"] / n if n else 0.0
        wr = d["w"] / n if n else 0.0
        if n < 5:
            grade = "INSUFFICIENT_DATA"
        elif avg_r < 0:
            grade = "F"
        elif wr >= 0.50 and avg_r >= 0.5:
            grade = "B+"
        elif wr >= 0.45 and avg_r >= 0.3:
            grade = "B"
        elif avg_r >= 0:
            grade = "C"
        else:
            grade = "F"
        cards.append((st, grade, n, wr, avg_r))

    f_hard, f_border, others = [], [], []
    for st, grade, n, wr, avg_r in cards:
        if grade == "F":
            (f_hard if avg_r < -0.3 else f_border).append((st, n, wr, avg_r))
        else:
            others.append((st, grade, n, wr, avg_r))

    print(f"\n  HARD-F (avg_r < -0.30 → clearly dead, keep blocked):")
    for st, n, wr, avg_r in sorted(f_hard, key=lambda x: x[3]):
        print(f"    {st:<24} n={n:<4} win={wr*100:4.0f}%  avg_r={avg_r:+.2f}")
    if not f_hard:
        print("    none")

    print(f"\n  BORDERLINE-F (-0.30 <= avg_r < 0 OR small sample → RE-EXAMINE, may be recoverable):")
    for st, n, wr, avg_r in sorted(f_border, key=lambda x: x[3], reverse=True):
        tag = " (small-n)" if n < 12 else ""
        print(f"    {st:<24} n={n:<4} win={wr*100:4.0f}%  avg_r={avg_r:+.2f}{tag}")
    if not f_border:
        print("    none")

    print(f"\n  PASSING setups (C and above):")
    for st, grade, n, wr, avg_r in sorted(others, key=lambda x: x[4], reverse=True):
        print(f"    {st:<24} {grade:<6} n={n:<4} win={wr*100:4.0f}%  avg_r={avg_r:+.2f}")
    if not others:
        print("    none — NO setup is currently grading C or better. Major red flag.")

    # DISABLED_SETUPS env blocklist
    disabled = os.environ.get("DISABLED_SETUPS", "vwap_fade_short")
    print(f"\n  DISABLED_SETUPS env blocklist: {disabled or '(empty)'}")

    # how many B+ alerts each F/border setup is suppressing (last 7d)
    a7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    alerts = list(db["live_alerts"].find(
        {"created_at": {"$gte": a7}, "tqs_grade": {"$exists": True}},
        {"_id": 0, "setup_type": 1, "tqs_grade": 1}))
    bplus_by_setup = Counter()
    for a in alerts:
        g = (a.get("tqs_grade") or "").strip()[:1].upper()
        if g in ("A", "B") and a.get("setup_type"):
            bplus_by_setup[a["setup_type"]] += 1
    blocked_setups = {x[0] for x in f_hard} | {x[0] for x in f_border}
    if disabled:
        blocked_setups |= {s.strip() for s in disabled.split(",") if s.strip()}
    print(f"\n  B+ alerts (7d) being suppressed by blocked/F setups:")
    sup = [(s, bplus_by_setup.get(s, 0)) for s in blocked_setups]
    sup = [x for x in sup if x[1] > 0]
    if sup:
        for s, c in sorted(sup, key=lambda x: -x[1]):
            print(f"    {c:>5} B+ alerts/7d  ← {s}")
        print(f"    (these would re-enter the funnel if the setup were restored)")
    else:
        print("    none of the blocked setups produced B+ alerts in 7d — blocks aren't "
              "costing high-grade opportunities.")

    # ── verdict ─────────────────────────────────────────────────────────
    print(f"\n{'='*100}\nVERDICT\n{'='*100}")
    if tt.get("paper", 0) > 0.6 * len(rows):
        print("• DATA TRUST: stats are mostly PAPER — treat all win rates as provisional.")
    if suspect:
        print(f"• POLLUTION: {len(suspect)} setups have stats NOT measuring true edge "
              f"(cost-poison / reconciled / non-edge exits). Recompute these on GENUINE, "
              f"FULL-SIZE, GROSS-aware outcomes before trusting their F-gate / setup score.")
    else:
        print("• Stats look clean — the poor win rates are likely REAL setup underperformance.")
    if f_border:
        print(f"• OVER-BLOCK: {len(f_border)} BORDERLINE-F setups (avg_r near 0 / small-n) "
              f"may be wrongly killed by the strict avg_r<0 gate. Consider a tolerance band "
              f"or min-sample bump.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
