"""Entry Edge Score v1 (P3') — expected-R from robust MARGINAL factors, with
empirical-Bayes shrinkage + an OUT-OF-SAMPLE lift proof. READ-ONLY model/report
(no live gating yet — that is the shadow-arm wiring step).

WHY: the TQS composite is noise (spearman≈0 across all 5 pillars) and the ML gate
`confidence_score` is INVERTED (−0.029 vs MFE; `go` worse than `reduce`). This is
the replacement spine — an additive, interpretable expected-MFE-R model built ONLY
from the factors the n=1002 discovery proved robust:
  categorical: time_window, direction, timeframe, priority, setup_type
  continuous:  regime_score (re-signed automatically via binning), rsi,
               trigger_probability, tape_score
Each factor contributes a SHRUNK delta from the global mean:
    edge = global_mean + Σ_factor shrunk_delta(bucket)
    shrunk_delta = n/(n+K) · (bucket_mean − global_mean)
Interpretable ("why" = the per-factor contributions), robust (thin buckets shrink
to 0), no ML deps. Continuous factors are quantile-binned so non-linearity and
sign-inversion (high regime_score → worse) are captured automatically.

Evaluated OUT-OF-SAMPLE via K-fold CV so reported lift is REAL, not the in-sample
overfit that produced TQS. Reports decile lift + OOS Spearman vs BOTH mfe_r and
realized_R, so we can prove it beats the champion gate BEFORE it gates live.

v1 caveat: additive main-effects can double-count correlated factors (e.g.
direction × time_window). That is acceptable for the shadow proof; P4' replaces
this with full archetype-cell conditioning + hierarchical shrinkage.

Methodology note: the OOS metric has a small CONSERVATIVE negative floor (~−0.04
Spearman on pure noise) from the leave-out group-mean effect (a left-out value is
mildly anti-correlated with the mean of its remaining group-mates). This is the
SAFE direction — the estimator never manufactures positive lift on noise — so any
materially positive OOS Spearman is real signal above that floor. OOS ranking uses
the delta-sum (discriminative signal), not the per-fold baseline, to avoid an
additional baseline artifact. Validated in tests/test_entry_edge_score.py.

Plan: memory/ENTRY_EDGE_SCORE_PLAN.md (P3').
"""
import logging
import random
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from services.tqs_entry_quality import _f, _clean_r, _spearman, MAX_PLAUSIBLE_R
from services.entry_feature_discovery import _get

logger = logging.getLogger(__name__)

SHRINK_K = 20.0          # bucket needs ~K obs for half-weight toward its own mean
N_QUANTILE_BINS = 5      # continuous → quintile buckets
DEFAULT_K_FOLDS = 5
MIN_TRADES = 60          # below this, lift is not meaningful

CATEGORICAL = ["time_window", "direction", "timeframe", "priority", "setup_type"]
CONTINUOUS = ["regime_score", "rsi", "trigger_probability", "tape_score"]


def _is_real_entry(t, ec):
    """Exclude reconciliation artifacts (orphans / excess-slices) — they have no
    real entry decision and would pollute the marginal means."""
    st = str(t.get("setup_type") or ec.get("scanner_setup_type") or "").lower()
    if st.startswith("reconciled") or "orphan" in st or "excess_slice" in st:
        return False
    return bool(ec)


def _raw_factors(t, ec):
    def s(v):
        return str(v).lower() if v not in (None, "") else None
    return {
        "time_window": s(ec.get("time_window")),
        "direction": s(t.get("direction")),
        "timeframe": s(t.get("timeframe")),
        "priority": s(ec.get("priority")),
        "setup_type": s(t.get("setup_type") or ec.get("scanner_setup_type")),
        "regime_score": _f(ec.get("regime_score")),
        "rsi": _f(_get(ec, "technicals", "rsi")),
        "trigger_probability": _f(ec.get("trigger_probability")),
        "tape_score": _f(t.get("tape_score") if t.get("tape_score") is not None else ec.get("tape_score")),
    }


def _quantile_edges(values, n_bins):
    vals = sorted(v for v in values if v is not None)
    if len(vals) < n_bins:
        return []
    return [vals[int(i * len(vals) / n_bins)] for i in range(1, n_bins)]


def _bin_continuous(v, edges):
    if v is None:
        return None
    b = 0
    for e in edges:
        if v >= e:
            b += 1
        else:
            break
    return "q%d" % b


def fit(rows):
    """rows: list of (factors_dict, target_value) → model dict."""
    targets = [tr for _, tr in rows]
    if not targets:
        return {"global_mean": 0.0, "edges": {}, "deltas": {}}
    gmean = sum(targets) / len(targets)
    edges = {cf: _quantile_edges([f.get(cf) for f, _ in rows], N_QUANTILE_BINS)
             for cf in CONTINUOUS}
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))  # factor→bucket→[sum,n]
    for f, tr in rows:
        for cat in CATEGORICAL:
            b = f.get(cat)
            if b is not None:
                acc[cat][b][0] += tr
                acc[cat][b][1] += 1
        for cf in CONTINUOUS:
            b = _bin_continuous(f.get(cf), edges[cf])
            if b is not None:
                acc[cf][b][0] += tr
                acc[cf][b][1] += 1
    deltas = {}
    for fac, buckets in acc.items():
        deltas[fac] = {}
        for b, (s, n) in buckets.items():
            mean = s / n
            deltas[fac][b] = {"delta": (n / (n + SHRINK_K)) * (mean - gmean),
                              "n": n, "mean": round(mean, 4)}
    return {"global_mean": gmean, "edges": edges, "deltas": deltas}


def score(model, factors):
    """factors → {edge, contributions, confidence_n}."""
    edge = model["global_mean"]
    contribs = {}
    min_n = None
    for cat in CATEGORICAL:
        b = factors.get(cat)
        d = model["deltas"].get(cat, {}).get(b) if b is not None else None
        if d:
            edge += d["delta"]
            contribs[cat] = round(d["delta"], 4)
            min_n = d["n"] if min_n is None else min(min_n, d["n"])
    for cf in CONTINUOUS:
        b = _bin_continuous(factors.get(cf), model["edges"].get(cf, []))
        d = model["deltas"].get(cf, {}).get(b) if b is not None else None
        if d:
            edge += d["delta"]
            contribs[cf] = round(d["delta"], 4)
    return {"edge": round(edge, 4), "contributions": contribs, "confidence_n": min_n}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def confidence_level(n):
    """Per-cell reliability band from the thinnest contributing bucket's eff_n."""
    if n is None:
        return "low"
    if n >= 40:
        return "high"
    if n >= 15:
        return "medium"
    return "low"


def score_full(model, factors, cohort_edges=None):
    """The score TRIPLE for live use: EDGE (expected-R) + CONFIDENCE (band/eff_n)
    + GRADE (0-100 percentile of edge within the archetype's rolling cohort, when
    a sorted cohort_edges list is supplied). No letter — single number, per the plan."""
    sc = score(model, factors)
    grade = None
    if cohort_edges:
        below = sum(1 for e in cohort_edges if e <= sc["edge"])
        grade = round(below / len(cohort_edges) * 100, 1)
    return {
        "edge": sc["edge"],
        "contributions": sc["contributions"],
        "confidence_n": sc["confidence_n"],
        "confidence": confidence_level(sc["confidence_n"]),
        "grade": grade,
    }


def generate_report(db, days: int = 120, target: str = "mfe_r",
                    k_folds: int = DEFAULT_K_FOLDS, clip: float = 0.0) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days, "target": target, "k_folds": k_folds,
        "clip": clip, "n_total": 0, "n_used": 0, "headline": "insufficient data",
    }
    if db is None:
        return out
    if target not in ("mfe_r", "realized_r", "win"):
        target = "mfe_r"

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    proj = {"_id": 0, "entry_context": 1, "realized_pnl": 1, "risk_amount": 1,
            "mfe_r": 1, "setup_type": 1, "timeframe": 1, "direction": 1,
            "tape_score": 1, "timestamp": 1, "created_at": 1, "closed_at": 1}

    data = []  # (factors, mfe, realized, target_value)
    n_total = 0
    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        n_total += 1
        ec = t.get("entry_context") or {}
        if not isinstance(ec, dict):
            ec = {}
        if not _is_real_entry(t, ec):
            continue
        realized = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if realized is None:
            continue
        mfe = _f(t.get("mfe_r"))
        if mfe is not None and abs(mfe) > MAX_PLAUSIBLE_R:
            mfe = None
        if target == "mfe_r":
            tval = mfe
            if tval is None:
                continue
            if clip > 0:
                tval = max(0.0, min(clip, tval))   # MFE is favorable-only
        elif target == "win":
            tval = 1.0 if realized > 0 else 0.0     # reliability label (P profitable)
        else:  # realized_r
            tval = max(-clip, min(clip, realized)) if clip > 0 else realized
        data.append((_raw_factors(t, ec), mfe, realized, tval))

    n = len(data)
    out["n_total"] = n_total
    out["n_used"] = n
    if n < MIN_TRADES:
        out["headline"] = "insufficient data: only %d usable real-entry trades (need ≥%d)" % (n, MIN_TRADES)
        return out

    kf = max(2, min(k_folds, n // 10))
    rnd = random.Random(42)
    idx = list(range(n))
    rnd.shuffle(idx)
    folds = [idx[i::kf] for i in range(kf)]
    oos_edge = [None] * n   # absolute predicted edge (for display)
    oos_rank = [None] * n   # delta-sum only (discriminative signal; removes the
                            # per-fold baseline artifact from the OOS metric)
    for fi in range(kf):
        test = set(folds[fi])
        train = [(data[i][0], data[i][3]) for i in range(n) if i not in test]
        model = fit(train)
        for i in folds[fi]:
            sc = score(model, data[i][0])
            oos_edge[i] = sc["edge"]
            oos_rank[i] = round(sc["edge"] - model["global_mean"], 6)

    # OOS decile lift (sorted by the discriminative signal, ascending)
    order = sorted(range(n), key=lambda i: oos_rank[i])
    deciles = []
    for d in range(10):
        seg = order[int(d * n / 10):int((d + 1) * n / 10)]
        if not seg:
            continue
        rs = [data[i][2] for i in seg]
        deciles.append({
            "decile": d + 1,
            "n": len(seg),
            "avg_pred_edge": _mean([oos_edge[i] for i in seg]),
            "avg_mfe_r": _mean([data[i][1] for i in seg]),
            "avg_realized_r": _mean(rs),
            "win_rate": round(sum(1 for x in rs if x > 0) / len(rs) * 100, 1),
        })

    sp_mfe = _spearman([oos_rank[i] for i in range(n) if data[i][1] is not None],
                       [data[i][1] for i in range(n) if data[i][1] is not None])
    sp_real = _spearman(oos_rank, [data[i][2] for i in range(n)])

    # full-data model for the per-factor "why" / effect display
    full = fit([(data[i][0], data[i][3]) for i in range(n)])
    factor_rows = []
    for fac, buckets in full["deltas"].items():
        cells = sorted(
            [{"bucket": b, "n": v["n"], "delta": round(v["delta"], 4), "mean": v["mean"]}
             for b, v in buckets.items() if v["n"] >= 12],
            key=lambda x: x["delta"])
        if not cells:
            continue
        factor_rows.append({
            "factor": fac,
            "n_buckets": len(cells),
            "spread": round(cells[-1]["delta"] - cells[0]["delta"], 4),
            "best": cells[-3:][::-1],
            "worst": cells[:3],
        })
    factor_rows.sort(key=lambda x: -x["spread"])

    top, bot = (deciles[-1], deciles[0]) if deciles else (None, None)

    # Per-archetype GRADE reliability: within each (setup_type × direction) cohort,
    # does the edge's higher half out-realize its lower half? (the per-archetype
    # "trustability" proof — a 90 must mean "best of its kind").
    arche = defaultdict(list)
    for i in range(n):
        f = data[i][0]
        key = "%s|%s" % (f.get("setup_type") or "?", f.get("direction") or "?")
        arche[key].append((oos_rank[i], data[i][2]))
    per_arche = []
    for key, rows in arche.items():
        if len(rows) < 25:
            continue
        rows.sort(key=lambda x: x[0])
        h = len(rows) // 2
        lo = _mean([r for _, r in rows[:h]])
        hi = _mean([r for _, r in rows[h:]])
        per_arche.append({
            "archetype": key, "n": len(rows),
            "low_half_realized_r": lo, "high_half_realized_r": hi,
            "within_archetype_lift": round(hi - lo, 4) if (hi is not None and lo is not None) else None,
        })
    per_arche.sort(key=lambda x: -(x["within_archetype_lift"] if x["within_archetype_lift"] is not None else -9))

    out.update({
        "global_mean_target": round(full["global_mean"], 4),
        "oos_spearman_pred_vs_mfe": sp_mfe,
        "oos_spearman_pred_vs_realized": sp_real,
        "oos_decile_lift": deciles,
        "factor_effects": factor_rows,
        "per_archetype_grade_check": per_arche,
    })
    out["headline"] = (
        "OOS (target=%s, n=%d, %d-fold): top-decile realized_R=%s vs bottom-decile=%s "
        "(lift=%s) | spearman pred-vs-realized=%s, pred-vs-mfe=%s | strongest factor: %s" % (
            target, n, kf,
            top["avg_realized_r"] if top else None,
            bot["avg_realized_r"] if bot else None,
            round((top["avg_realized_r"] - bot["avg_realized_r"]), 4)
            if (top and bot and top["avg_realized_r"] is not None and bot["avg_realized_r"] is not None) else None,
            sp_real, sp_mfe,
            factor_rows[0]["factor"] if factor_rows else None,
        )
    )
    return out
