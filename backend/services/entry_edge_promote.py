"""PROMOTE validation — OOS sizing + GO/STAND-DOWN backtest for the Entry Edge Score.

Answers the two PROMOTE questions before we flip active:
  1. GO / STAND-DOWN — keep only positive-conservative-edge trades above the veto
     cutoff; how much realized R do we keep vs the bleed the stand-downs carry?
  2. SIZING — scale each GO trade by edge×confidence (size_mult); does size-weighted
     realized R beat equal-weight?

HEADLINE = OUT-OF-SAMPLE (k-fold): per fold we fit on train, derive the bottom-PCTILE
cutoff + grade distribution from TRAIN ONLY, then score the held-out TEST trades.
This removes the in-sample optimism (a model graded on its own training rows looks
better than it will live). The `in_sample` block is kept for reference only.

Endpoint: GET /api/slow-learning/entry-edge-promote/report?days=120&k_folds=5
"""
import logging
import random
from datetime import datetime, timezone

from services import entry_edge_score as ees
from services.entry_edge_gate import compute_decision, _envi, _envf

logger = logging.getLogger(__name__)


def _pctile_grade(edges_sorted, edge):
    if not edges_sorted or edge is None:
        return None
    below = sum(1 for x in edges_sorted if x <= edge)
    return round(below / len(edges_sorted) * 100, 1)


def _cutoff(edges_sorted, pctile):
    k = max(1, min(len(edges_sorted), int(pctile / 100.0 * len(edges_sorted))))
    return edges_sorted[k - 1]


def _decisions(model, grade_edges, threshold, scored_rows):
    """scored_rows: [(factors, realized)] → [(realized, decision)]."""
    res = []
    for f, realized in scored_rows:
        sc = ees.score_conditional(model, f)
        edge = sc.get("edge")
        cn = sc.get("confidence_n")
        grade = _pctile_grade(grade_edges, edge)
        res.append((realized, compute_decision(edge, grade, cn, threshold)))
    return res


def _accumulate(items):
    base = go = sd = sized = wsum = 0.0
    n_go = n_sd = 0
    reasons = {}
    for realized, dec in items:
        base += realized
        if dec["go"]:
            n_go += 1
            go += realized
            sm = dec["size_mult"] or 1.0
            sized += realized * sm
            wsum += sm
        else:
            n_sd += 1
            sd += realized
            r = dec["stand_down_reason"] or "none"
            reasons[r] = reasons.get(r, 0) + 1
    n = len(items)
    go_avg = (go / n_go) if n_go else 0.0
    sized_avg = (sized / wsum) if wsum else 0.0
    return {
        "baseline_all": {"n": n, "total_r": round(base, 2),
                         "avg_r": round(base / n, 4) if n else 0.0},
        "go_only": {"n": n_go, "total_r": round(go, 2), "avg_r": round(go_avg, 4)},
        "stand_down": {"n": n_sd, "total_r": round(sd, 2),
                       "avg_r": round(sd / n_sd, 4) if n_sd else 0.0, "reasons": reasons},
        "sizing": {"go_equal_weight_avg_r": round(go_avg, 4),
                   "go_size_weighted_avg_r": round(sized_avg, 4),
                   "sizing_lift_avg_r": round(sized_avg - go_avg, 4)},
    }


def generate_report(db, days: int = 120, k_folds: int = 5) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days, "k_folds": k_folds, "mode": "backtest",
        "config": {
            "go_threshold": _envf("ENTRY_EDGE_GO_THRESHOLD", 0.0),
            "size_min": _envf("ENTRY_EDGE_SIZE_MIN", 0.5),
            "size_max": _envf("ENTRY_EDGE_SIZE_MAX", 1.25),
            "skip_bottom_pct": _envi("ENTRY_EDGE_VETO_PCTILE", 30),
        },
    }
    if db is None:
        return out

    clip = _envf("ENTRY_EDGE_VETO_CLIP", 3)
    pctile = _envi("ENTRY_EDGE_VETO_PCTILE", 30)
    rows, _ = ees.load_training_rows(db, days, "realized_r", clip)
    n = len(rows)
    out["n_used"] = n
    if n < _envi("ENTRY_EDGE_VETO_MIN_TRADES", ees.MIN_TRADES):
        out["note"] = "insufficient book (n=%d)" % n
        return out

    realized = [r for _, _, r, _ in rows]
    train_pairs = [(f, tval) for f, _, _, tval in rows]

    # ---- in-sample (reference) ----
    full = ees.fit_conditional(train_pairs)
    full_edges = sorted(ees.score_conditional(full, f)["edge"] for f, _, _, _ in rows)
    full_cut = _cutoff(full_edges, pctile)
    out["in_sample"] = _accumulate(
        _decisions(full, full_edges, full_cut, [(f, realized[i]) for i, (f, _, _, _) in enumerate(rows)]))

    # ---- OOS k-fold (headline) ----
    kf = max(2, min(k_folds, n // 10))
    rnd = random.Random(42)
    idx = list(range(n))
    rnd.shuffle(idx)
    folds = [idx[i::kf] for i in range(kf)]
    oos_items = []
    for fi in range(kf):
        test = set(folds[fi])
        tr = [(rows[i][0], rows[i][3]) for i in range(n) if i not in test]
        model = ees.fit_conditional(tr)
        tr_edges = sorted(ees.score_conditional(model, rows[i][0])["edge"]
                          for i in range(n) if i not in test)
        thr = _cutoff(tr_edges, pctile)
        oos_items.extend(_decisions(model, tr_edges, thr,
                                    [(rows[i][0], realized[i]) for i in folds[fi]]))
    oos = _accumulate(oos_items)
    out["oos"] = oos

    b, g, sd, sz = oos["baseline_all"], oos["go_only"], oos["stand_down"], oos["sizing"]
    out["verdict"] = (
        "OOS %d-fold: GO keeps %d/%d trades at %s total_R / %s avg_R (vs %s baseline); "
        "STAND-DOWN benches %d carrying %s total_R (avg %s). Sizing lift %s avg_R. "
        "%s" % (
            kf, g["n"], b["n"], g["total_r"], g["avg_r"], b["total_r"],
            sd["n"], sd["total_r"], sd["avg_r"], sz["sizing_lift_avg_r"],
            "GREEN: GO positive + stand-down negative."
            if (g["avg_r"] > 0 and sd["avg_r"] < 0) else
            "MIXED: inspect before going active."))
    return out
