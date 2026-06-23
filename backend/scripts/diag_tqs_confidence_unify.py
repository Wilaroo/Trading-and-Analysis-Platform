#!/usr/bin/env python3
"""diag_tqs_confidence_unify.py (READ-ONLY) — quantify the TQS <-> Confidence
Gate "dual decision authority" ambiguity before any unification patch.

The two authorities today (opportunity_evaluator.evaluate_opportunity):
  1. smart_filter — SKIP/REDUCE off the TQS grade (hard veto #1, L837).
  2. confidence_gate.evaluate — GO/REDUCE/SKIP off an AI confidence_score
     (hard veto #2, L917); TQS is only passed in as `quality_score`.
  3. position size then STACKS grade_mult (A1.0/B0.7/C0.3/D0.1)
     × smart_filter adj × confidence_multiplier (×0.6 on REDUCE).
  4. TQS `action` (STRONG_BUY>=80/BUY>=65/HOLD>=50) is absolute against a
     composite crushed to ~48-66 → ~everything is "HOLD" (degenerate verdict).

This script measures, writing NOTHING:
  A) cross-tab TQS-grade × gate-decision (how often they DISAGREE).
  B) the stacked-multiplier distribution (double-discounting).
  C) the two skip authorities' kill counts (trade_drops).
  D) outcome lens — does the gate decision or the TQS grade better separate
     winners (confidence_gate_log rows that carry a tracked outcome)?
  E) plain-language reading + the unification levers.

Usage (repo root, DGX):
  .venv/bin/python /tmp/diag_tqs_confidence_unify.py --days 7
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


# ── grade calibration mirror (services/tqs/grade_calibration.py defaults) ──
def _build_grader(db):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    rows = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}, "tqs_score": {"$gt": 0},
         "time_window": {"$nin": ["premarket", "closed"]}},
        {"tqs_score": 1, "_id": 0}))
    ref = sorted(float(r["tqs_score"]) for r in rows
                 if isinstance(r.get("tqs_score"), (int, float)) and r["tqs_score"] > 0)
    n = len(ref)
    cuts = {"A": 90.0, "B": 70.0, "C": 35.0, "D": 10.0}
    floors = {"A": 60.0, "B": 57.0, "C": 0.0, "D": 0.0}
    import bisect

    def static_grade(s):
        if s >= 85: return "A"
        if s >= 75: return "B"
        if s >= 65: return "B"
        if s >= 55: return "C"
        if s >= 45: return "C"
        if s >= 35: return "D"
        return "F"

    def grade(s):
        try:
            s = float(s)
        except (TypeError, ValueError):
            return "F"
        if n < 200:
            return static_grade(s)
        rank = 100.0 * bisect.bisect_right(ref, s) / n
        chosen = "F"
        for g in ("A", "B", "C", "D"):
            if rank >= cuts[g]:
                chosen = g
                break
        order = ["A", "B", "C", "D", "F"]
        i = order.index(chosen)
        while chosen in ("A", "B", "C", "D") and s < floors.get(chosen, 0.0):
            i += 1
            chosen = order[i]
        return chosen

    return grade, n


def _tqs_action(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return "?"
    if s >= 80: return "STRONG_BUY"
    if s >= 65: return "BUY"
    if s >= 50: return "HOLD"
    if s >= 35: return "AVOID"
    return "STRONG_AVOID"


_GRADE_MULT = {"A": 1.0, "B": 0.7, "C": 0.3, "D": 0.1, "F": 0.1}


def main():
    days = _arg("--days", 7, int)
    db = _db()
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    grade_of, ref_n = _build_grader(db)
    print(f"\ngrade reference: n={ref_n} live_alerts (5d RTH); "
          f"{'PERCENTILE' if ref_n >= 200 else 'STATIC fallback'} grading")

    rows = list(db["confidence_gate_log"].find(
        {"timestamp": {"$gte": cut}},
        {"_id": 0, "decision": 1, "confidence_score": 1, "quality_score": 1,
         "position_multiplier": 1, "setup_type": 1, "symbol": 1,
         "outcome_pnl": 1, "trade_outcome": 1, "timestamp": 1}))
    print(f"confidence_gate_log rows (last {days}d): {len(rows)}")
    if not rows:
        print("  (none — gate hasn't logged in this window; re-run after RTH.)")
        return

    # ── A) cross-tab grade × decision ────────────────────────────────────
    print("\n=== A) TQS-grade  ×  gate-decision ===")
    grid = defaultdict(lambda: defaultdict(int))
    act_dist = defaultdict(int)
    DEC = ["GO", "REDUCE", "SKIP"]
    for r in rows:
        g = grade_of(r.get("quality_score"))
        d = (r.get("decision") or "?").upper()
        grid[g][d] += 1
        act_dist[_tqs_action(r.get("quality_score"))] += 1
    hdr = f"  {'grade':<6}" + "".join(f"{d:>9}" for d in DEC) + f"{'total':>9}"
    print(hdr)
    tot_dec = defaultdict(int)
    for g in ["A", "B", "C", "D", "F"]:
        rowt = sum(grid[g].values())
        if rowt == 0:
            continue
        line = f"  {g:<6}" + "".join(f"{grid[g][d]:>9}" for d in DEC) + f"{rowt:>9}"
        print(line)
        for d in DEC:
            tot_dec[d] += grid[g][d]
    grand = sum(tot_dec.values())
    print(f"  {'TOTAL':<6}" + "".join(f"{tot_dec[d]:>9}" for d in DEC) + f"{grand:>9}")
    print(f"  gate decision mix: " + "  ".join(
        f"{d}={100.0*tot_dec[d]/grand:.1f}%" for d in DEC))
    print(f"  TQS action mix (absolute thresholds): " + "  ".join(
        f"{a}={100.0*c/grand:.1f}%" for a, c in sorted(act_dist.items(), key=lambda kv: -kv[1])))

    # disagreement
    ab = sum(sum(grid[g].values()) for g in ("A", "B"))
    ab_skip = sum(grid[g]["SKIP"] for g in ("A", "B"))
    df = sum(sum(grid[g].values()) for g in ("D", "F"))
    df_go = sum(grid[g]["GO"] for g in ("D", "F"))
    print("\n  DISAGREEMENT:")
    print(f"   • high-TQS (A/B) but gate SKIP : {ab_skip}/{ab} "
          f"({100.0*ab_skip/ab:.1f}% of A/B)  ← gate vetoes quality setups")
    print(f"   • low-TQS  (D/F) but gate GO   : {df_go}/{df} "
          f"({100.0*df_go/df:.1f}% of D/F)  ← gate passes weak setups"
          if df else "   • low-TQS (D/F): none in window")

    # ── B) stacked-multiplier distribution ───────────────────────────────
    print("\n=== B) STACKED multiplier (grade_mult × confidence_multiplier) ===")
    bands = [(0.0, 0.15), (0.15, 0.35), (0.35, 0.7), (0.7, 1.01)]
    band_ct = defaultdict(int)
    double_disc = 0
    n_exec = 0
    combos = []
    for r in rows:
        if (r.get("decision") or "").upper() == "SKIP":
            continue
        n_exec += 1
        gm = _GRADE_MULT.get(grade_of(r.get("quality_score")), 0.1)
        cm = r.get("position_multiplier")
        cm = float(cm) if isinstance(cm, (int, float)) else 1.0
        comb = gm * cm
        combos.append(comb)
        if gm < 1.0 and cm < 1.0:
            double_disc += 1
        for lo, hi in bands:
            if lo <= comb < hi:
                band_ct[(lo, hi)] += 1
                break
    combos.sort()
    med = combos[len(combos) // 2] if combos else 0.0
    print(f"  executed-ish (GO/REDUCE) rows: {n_exec}   median combined size mult: {med:.2f}")
    for lo, hi in bands:
        c = band_ct[(lo, hi)]
        pct = (100.0 * c / n_exec) if n_exec else 0.0
        print(f"    {lo:.2f}–{hi:.2f}x : {c:>6}  ({pct:.1f}%)")
    print(f"  DOUBLE-DISCOUNTED (grade<1 AND gate<1): {double_disc}/{n_exec} "
          f"({100.0*double_disc/n_exec:.1f}%)  ← both authorities shrink the same trade")

    # ── C) two skip authorities (trade_drops) ────────────────────────────
    print(f"\n=== C) SKIP-authority kill counts (trade_drops, last {days}d) ===")
    tdcut = cut
    counts = {}
    for g in ("smart_filter_skip", "gate_skip"):
        counts[g] = db["trade_drops"].count_documents(
            {"gate": g, "ts": {"$gte": tdcut}})
    # some builds store under reason_code; tolerate both
    for g in ("smart_filter_skip", "gate_skip"):
        if counts[g] == 0:
            counts[g] = db["trade_drops"].count_documents(
                {"reason_code": g, "ts": {"$gte": tdcut}})
    print(f"  smart_filter_skip (TQS-grade authority): {counts['smart_filter_skip']}")
    print(f"  gate_skip         (AI-confidence authority): {counts['gate_skip']}")
    print("  → two independent vetoes; an alert must clear BOTH to reach sizing.")

    # ── D) outcome lens (which authority separates winners) ──────────────
    print("\n=== D) OUTCOME LENS (confidence_gate_log rows with tracked outcome) ===")
    out = [r for r in rows if isinstance(r.get("outcome_pnl"), (int, float))]
    print(f"  rows with outcome_pnl: {len(out)}")
    if out:
        def _bucketed(keyfn, order):
            agg = defaultdict(lambda: [0, 0, 0.0])  # n, wins, pnl_sum
            for r in out:
                k = keyfn(r)
                a = agg[k]
                a[0] += 1
                a[2] += float(r["outcome_pnl"])
                if r["outcome_pnl"] > 0:
                    a[1] += 1
            for k in order:
                if k not in agg:
                    continue
                n, w, p = agg[k]
                print(f"    {k:<12} n={n:<5} win%={100.0*w/n:5.1f}  avg_pnl={p/n:+8.2f}")
        print("  by gate decision:")
        _bucketed(lambda r: (r.get("decision") or "?").upper(), ["GO", "REDUCE", "SKIP"])
        print("  by TQS grade:")
        _bucketed(lambda r: grade_of(r.get("quality_score")), ["A", "B", "C", "D", "F"])
        print("  (compare the win%/avg_pnl SPREAD — the wider-separating axis is")
        print("   the stronger single authority to anchor the unified verdict on.)")
    else:
        print("  (no tracked outcomes yet — gate_outcome_reconciler fills these on")
        print("   close; re-run once trades from this window have closed.)")

    # ── E) reading ───────────────────────────────────────────────────────
    print("\n=== READING / UNIFICATION LEVERS ===")
    print("• A quantifies the disagreement: A/B-but-SKIP = gate overriding TQS;")
    print("  D/F-but-GO = gate firing what TQS would down-grade. A degenerate TQS")
    print("  action mix (~all HOLD) confirms the action field is a dead verdict.")
    print("• B shows the double-discount: when both authorities shrink the SAME")
    print("  trade, effective size collapses (e.g. B 0.7 × REDUCE 0.6 = 0.42x).")
    print("• C shows two separate kill switches — the structural ambiguity.")
    print("• D says which axis actually predicts P&L → anchor the merged verdict")
    print("  on the stronger one, fold the other in as an input (not a 2nd veto).")
    print("• UNIFY options: (1) ONE verdict object {decision,size_mult,grade,why}")
    print("  computed once; (2) TQS-primary (gate AI score folds into Context")
    print("  pillar, already partly does post-gate) with a single grade→size mult;")
    print("  (3) gate-primary (TQS = quality input only). Pick after seeing A–D.\n")


if __name__ == "__main__":
    main()
