"""PROMOTE validation — sizing + GO/STAND-DOWN backtest for the Entry Edge Score.

The OOS abstention curve (entry-edge-score report) already proves WHICH trades to
skip. This report answers the two extra PROMOTE questions before we flip active:

  1. GO / STAND-DOWN: if we'd only taken GO trades (positive conservative edge,
     above the veto cutoff), how much realized R do we keep, and how much bleed do
     the STAND-DOWN trades carry? (stand-down R should be strongly negative.)
  2. SIZING: if we'd scaled each trade by edge×confidence (size_mult), does the
     size-weighted realized R beat equal-weight? (up-size winners, down-size losers.)

Model = the SAME conditional fit + bottom-PCTILE cutoff the live gate uses, scored
in-sample over the closed book (in-window caveat — directional, not a promise).

Endpoint: GET /api/slow-learning/entry-edge-promote/report?days=120
"""
import logging
from datetime import datetime, timezone

from services import entry_edge_score as ees
from services.entry_edge_gate import compute_decision, _envi, _envf

logger = logging.getLogger(__name__)


def _pctile_grade(edges_sorted, edge):
    if not edges_sorted or edge is None:
        return None
    below = sum(1 for x in edges_sorted if x <= edge)
    return round(below / len(edges_sorted) * 100, 1)


def generate_report(db, days: int = 120) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "mode": "backtest",
        "config": {
            "go_threshold": _envf("ENTRY_EDGE_GO_THRESHOLD", 0.0),
            "size_min": _envf("ENTRY_EDGE_SIZE_MIN", 0.5),
            "size_max": _envf("ENTRY_EDGE_SIZE_MAX", 1.25),
            "skip_bottom_pct": _envi("ENTRY_EDGE_VETO_PCTILE", 30),
        },
    }
    if db is None:
        return out

    target = "realized_r"
    clip = _envf("ENTRY_EDGE_VETO_CLIP", 3)
    rows, _ = ees.load_training_rows(db, days, target, clip)
    n = len(rows)
    out["n_used"] = n
    if n < _envi("ENTRY_EDGE_VETO_MIN_TRADES", ees.MIN_TRADES):
        out["note"] = "insufficient book (n=%d)" % n
        return out

    model = ees.fit_conditional([(f, tval) for f, _, _, tval in rows])
    edges = sorted(ees.score_conditional(model, f)["edge"] for f, _, _, _ in rows)
    pctile = _envi("ENTRY_EDGE_VETO_PCTILE", 30)
    k = max(1, min(len(edges), int(pctile / 100.0 * len(edges))))
    veto_threshold = edges[k - 1]

    base_total = 0.0          # equal-weight, all trades
    go_total = 0.0            # GO trades only, equal-weight
    standdown_total = 0.0     # STAND-DOWN trades realized R (bleed avoided)
    sized_total = 0.0         # GO trades, size-weighted
    sized_wsum = 0.0
    n_go = n_sd = 0
    sd_reasons = {}
    for f, _mfe, realized, _tval in rows:
        sc = ees.score_conditional(model, f)
        edge = sc.get("edge")
        cn = sc.get("confidence_n")
        grade = _pctile_grade(edges, edge)
        dec = compute_decision(edge, grade, cn, veto_threshold)
        base_total += realized
        if dec["go"]:
            n_go += 1
            go_total += realized
            sm = dec["size_mult"] or 1.0
            sized_total += realized * sm
            sized_wsum += sm
        else:
            n_sd += 1
            standdown_total += realized
            r = dec["stand_down_reason"] or "none"
            sd_reasons[r] = sd_reasons.get(r, 0) + 1

    # size-weighted avg R normalized so it's comparable to equal-weight avg R
    sized_avg = (sized_total / sized_wsum) if sized_wsum else 0.0
    go_avg = (go_total / n_go) if n_go else 0.0

    out["baseline_all"] = {"n": n, "total_r": round(base_total, 2),
                           "avg_r": round(base_total / n, 4)}
    out["go_only"] = {"n": n_go, "total_r": round(go_total, 2), "avg_r": round(go_avg, 4)}
    out["stand_down"] = {"n": n_sd, "total_r": round(standdown_total, 2),
                         "avg_r": round(standdown_total / n_sd, 4) if n_sd else 0.0,
                         "reasons": sd_reasons}
    out["sizing"] = {
        "go_equal_weight_avg_r": round(go_avg, 4),
        "go_size_weighted_avg_r": round(sized_avg, 4),
        "sizing_lift_avg_r": round(sized_avg - go_avg, 4),
    }
    out["verdict"] = (
        "GO keeps %d/%d trades at %s total_R (vs %s baseline); STAND-DOWN removes %d "
        "trades carrying %s total_R of bleed. Size-weighting GO trades: %s avg_R vs %s "
        "equal-weight (lift %s)." % (
            n_go, n, round(go_total, 1), round(base_total, 1), n_sd,
            round(standdown_total, 1), round(sized_avg, 4), round(go_avg, 4),
            round(sized_avg - go_avg, 4)))
    return out
