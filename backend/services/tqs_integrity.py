"""TQS integrity audit (read-only) — is the quality score actually PREDICTIVE?

Three lenses:
  1) GRADE SEPARATION (durable, from alert_outcomes): group realized r_multiple by
     trade_grade (A..F). If TQS works, avg-R should rank A > B > C > D > F. We flag
     monotonicity + the A-minus-D spread. If it doesn't separate, the gate is
     anchoring on a meaningless score (explains the cross-horizon bleed).
  2) SCORE DISCRIMINATION (from confidence_gate_log.quality_score): distribution
     (mean / sd / p10-p50-p90). A compressed score (low SD, everything ~50) can't
     discriminate — the known "pillars pinned at neutral default" smell.
  3) PILLAR COVERAGE (forward, from gate-log pillar_scores once logged): how often
     each pillar sits at/near its neutral default (real vs defaulted). Empty until
     the gate starts logging pillar_scores (added alongside this audit).

Pure read-model.
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import mean, pstdev, median

logger = logging.getLogger(__name__)

GRADES = ["A", "B", "C", "D", "F"]
NEUTRAL = 50.0          # pillar neutral default
NEUTRAL_EPS = 2.0       # within +-eps of neutral counts as "defaulted"


def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return round(s[i], 2)


def _grade_separation(db, cutoff):
    rows = list(db["alert_outcomes"].find(
        {"closed_at": {"$gte": cutoff}},
        {"trade_grade": 1, "r_multiple": 1, "outcome": 1}))
    by = {g: [] for g in GRADES}
    for r in rows:
        g = str(r.get("trade_grade") or "").strip().upper()[:1]
        rm = r.get("r_multiple")
        if g in by and rm is not None:
            try:
                by[g].append(float(rm))
            except (TypeError, ValueError):
                pass
    grades = []
    avgs = {}
    for g in GRADES:
        v = by[g]
        if v:
            avgs[g] = round(mean(v), 3)
        grades.append({
            "grade": g, "n": len(v),
            "win_rate": round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None,
            "avg_r": round(mean(v), 3) if v else None,
            "median_r": round(median(v), 3) if v else None,
        })
    present = [g for g in GRADES if g in avgs]
    monotonic = all(avgs[present[i]] >= avgs[present[i + 1]] for i in range(len(present) - 1)) \
        if len(present) >= 2 else None
    spread = None
    if "A" in avgs and present:
        worst = present[-1]
        spread = round(avgs["A"] - avgs[worst], 3)
    return {
        "total_scored": sum(len(by[g]) for g in GRADES),
        "by_grade": grades,
        "monotonic_A_to_F": monotonic,         # True == TQS ranks correctly
        "avg_r_spread_A_minus_worst": spread,  # >0 and large == good separation
        "verdict": ("predictive" if (monotonic and (spread or 0) > 0.2)
                    else "weak_or_inverted" if monotonic is not None else "insufficient"),
    }


def _score_discrimination(db, cutoff):
    qs = []
    for d in db["confidence_gate_log"].find(
            {}, {"quality_score": 1, "timestamp": 1}):
        ts = d.get("timestamp")
        if ts and str(ts) < cutoff:
            continue
        v = d.get("quality_score")
        if isinstance(v, (int, float)):
            qs.append(float(v))
    if not qs:
        return {"n": 0, "verdict": "insufficient"}
    sd = round(pstdev(qs), 2) if len(qs) > 1 else 0.0
    return {
        "n": len(qs),
        "mean": round(mean(qs), 2),
        "sd": sd,
        "p10": _pct(qs, 10), "p50": _pct(qs, 50), "p90": _pct(qs, 90),
        "min": round(min(qs), 1), "max": round(max(qs), 1),
        # tight band (low SD) => the score can't separate trades
        "verdict": "compressed" if sd < 8 else "ok_spread",
    }


def _pillar_coverage(db, cutoff):
    agg = {}
    n_docs = 0
    for d in db["confidence_gate_log"].find(
            {"pillar_scores": {"$exists": True}},
            {"pillar_scores": 1, "timestamp": 1}):
        ts = d.get("timestamp")
        if ts and str(ts) < cutoff:
            continue
        ps = d.get("pillar_scores") or {}
        if not isinstance(ps, dict) or not ps:
            continue
        n_docs += 1
        for pillar, val in ps.items():
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            a = agg.setdefault(pillar, {"n": 0, "defaulted": 0, "sum": 0.0})
            a["n"] += 1
            a["sum"] += v
            if abs(v - NEUTRAL) <= NEUTRAL_EPS or v == 0.0:
                a["defaulted"] += 1
    pillars = []
    for p, a in sorted(agg.items()):
        pillars.append({
            "pillar": p, "n": a["n"],
            "mean": round(a["sum"] / a["n"], 2) if a["n"] else None,
            "defaulted_pct": round(a["defaulted"] / a["n"] * 100, 1) if a["n"] else None,
        })
    return {"evaluations_with_pillars": n_docs, "pillars": pillars,
            "note": ("awaiting data — gate began logging pillar_scores with this audit"
                     if n_docs == 0 else "")}


def _grade_by_horizon(db, cutoff):
    """Per-(grade × horizon) realized-R — localises WHERE the grade ranks R and
    where it INVERTS. (Aggregate grade-separation can hide a horizon that works
    cleanly under one that is inverted — e.g. intraday monotonic vs scalp where
    grade A is the worst cell.)"""
    from services.horizon_funnel import horizon_of
    cell = {}
    for d in db["alert_outcomes"].find(
            {"closed_at": {"$gte": cutoff}},
            {"trade_grade": 1, "r_multiple": 1, "setup_type": 1}):
        g = str(d.get("trade_grade") or "").strip().upper()[:1]
        if g not in GRADES:
            continue
        rm = d.get("r_multiple")
        if rm is None:
            continue
        try:
            rm = float(rm)
        except (TypeError, ValueError):
            continue
        cell.setdefault(horizon_of(d.get("setup_type")), {}).setdefault(g, []).append(rm)

    horizons = []
    inverted = []
    for h, grades in sorted(cell.items()):
        rows, avgs = [], {}
        for g in GRADES:
            v = grades.get(g, [])
            if v:
                avgs[g] = round(mean(v), 3)
            rows.append({
                "grade": g, "n": len(v),
                "win_rate": round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None,
                "avg_r": round(mean(v), 3) if v else None,
            })
        present = [g for g in GRADES if g in avgs]
        mono = (all(avgs[present[i]] >= avgs[present[i + 1]] for i in range(len(present) - 1))
                if len(present) >= 2 else None)
        # inverted = best grade present underperforms the worst grade present
        inv = len(present) >= 2 and avgs[present[0]] < avgs[present[-1]]
        if inv and h != "unknown":
            inverted.append(h)
        horizons.append({"horizon": h, "by_grade": rows,
                         "monotonic": mono, "inverted": inv})
    return {"horizons": horizons, "inverted_horizons": inverted}


def generate_report(db, days: int = 30) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
    }
    if db is None:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out["grade_separation"] = _grade_separation(db, cutoff)
    out["score_discrimination"] = _score_discrimination(db, cutoff)
    out["pillar_coverage"] = _pillar_coverage(db, cutoff)
    out["grade_by_horizon"] = _grade_by_horizon(db, cutoff)
    gs, sd = out["grade_separation"], out["score_discrimination"]
    bits = []
    if gs.get("verdict") == "weak_or_inverted":
        bits.append("TQS grades do NOT rank realized R (not predictive)")
    inv = out["grade_by_horizon"].get("inverted_horizons") or []
    if inv:
        bits.append("grade INVERTED on: " + ", ".join(inv))
    if sd.get("verdict") == "compressed":
        bits.append(f"quality_score compressed (SD {sd.get('sd')})")
    out["headline"] = "; ".join(bits) if bits else "TQS separation/spread look reasonable"
    return out
