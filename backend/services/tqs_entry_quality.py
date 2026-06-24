"""TQS entry-quality cross-tab (read-only) — does TQS PREDICT entry quality?

The MFE/MAE study proves the book bleeds from ENTRIES (avg MFE ~+0.16R, avg MAE
~-0.25R, winner_capture ~0.87 → holding/exits are fine). The open question for the
TQS audit is whether the bot's own Trade Quality Score actually SEPARATES good
entries from bad ones. If a high-TQS trade realizes the same low MFE as a low-TQS
trade, TQS is non-predictive noise and the whole Confidence-Gate gating is theatre.

This is a pure read-model over closed `bot_trades` (every field already persisted:
`tqs_grade`/`tqs_score` = the FINAL post-gate TQS the bot entered on, plus
`mfe_r`/`mae_r`/`realized_pnl`/`risk_amount`). It buckets realized R and MFE_R by
TQS grade and by TQS score band, and computes the Spearman rank correlation between
TQS score and (realized R, MFE_R). A flat/negative correlation ⇒ TQS does not
predict entry quality ⇒ rework TQS against MFE, not gate thresholds.
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import median

logger = logging.getLogger(__name__)

MAX_PLAUSIBLE_R = 10.0   # mirror mfe_mae_study — drop legacy-corrupt excursions
GREEN_R = 1.0

# Canonical TQS grade order, best → worst (UI uses A+ .. F).
GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
SCORE_BANDS = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 101)]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clean_r(pnl, risk):
    try:
        ra = float(risk)
        if ra > 0:
            return max(-10.0, min(10.0, float(pnl) / ra))
    except (TypeError, ValueError):
        pass
    return None


def _rank(xs):
    """Average-tie ranks for a Spearman computation."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def _bucket_summary(label, rows):
    """rows = list of (r, mfe, mae, score)."""
    n = len(rows)
    base = {"bucket": label, "n": n}
    if n == 0:
        return base
    rs = [r for r, _, _, _ in rows]
    mfes = [m for _, m, _, _ in rows if m is not None]
    maes = [a for _, _, a, _ in rows if a is not None]
    winners = [(r, m) for r, m, _, _ in rows if r > 0]
    cap = [r / max(m, r) for r, m in winners if m and m > 0]
    avg_mfe = round(sum(mfes) / len(mfes), 3) if mfes else None
    base.update({
        "win_rate": round(sum(1 for r in rs if r > 0) / n * 100, 1),
        "avg_r": round(sum(rs) / n, 3),
        "median_r": round(median(rs), 3),
        "avg_mfe_r": avg_mfe,
        "avg_mae_r": round(sum(maes) / len(maes), 3) if maes else None,
        "winner_capture": round(sum(cap) / len(cap), 3) if cap else None,
        "total_r": round(sum(rs), 2),
    })
    return base


def _verdict(corr_mfe, corr_r, n):
    if n < 30 or corr_mfe is None:
        return "insufficient"
    c = corr_mfe
    if c <= -0.05:
        return "inverted"          # higher TQS → WORSE entries (actively harmful)
    if c < 0.05:
        return "non_predictive"    # TQS is noise for entry quality → rework TQS
    if c < 0.15:
        return "weak"              # marginal signal
    return "predictive"            # TQS separates entries → tighten gate to top grades


def generate_report(db, days: int = 30, min_n: int = 5) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "by_grade": [],
        "by_score_band": [],
        "correlation": {},
        "overall": {},
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    proj = {"_id": 0, "setup_type": 1, "status": 1, "realized_pnl": 1,
            "risk_amount": 1, "mfe_r": 1, "mae_r": 1, "tqs_grade": 1,
            "tqs_score": 1, "timestamp": 1, "created_at": 1, "closed_at": 1}

    by_grade = {g: [] for g in GRADE_ORDER}
    by_grade["ungraded"] = []
    by_band = {b: [] for b in SCORE_BANDS}
    all_rows = []
    xs_score, ys_r, ys_mfe = [], [], []
    corrupt = 0

    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        mfe, mae = _f(t.get("mfe_r")), _f(t.get("mae_r"))
        if mfe is not None and abs(mfe) > MAX_PLAUSIBLE_R:
            mfe = None
            corrupt += 1
        if mae is not None and abs(mae) > MAX_PLAUSIBLE_R:
            mae = None
            corrupt += 1
        score = _f(t.get("tqs_score"))
        grade = str(t.get("tqs_grade") or "").strip().upper()
        if grade not in by_grade:
            grade = "ungraded" if not grade else grade
        row = (r, mfe, mae, score)
        all_rows.append(row)
        by_grade.setdefault(grade, []).append(row)
        if score is not None and 0 <= score <= 100:
            for b in SCORE_BANDS:
                if b[0] <= score < b[1]:
                    by_band[b].append(row)
                    break
            # correlation uses only rows that have BOTH a score and an MFE
            xs_score.append(score)
            ys_r.append(r)
            if mfe is not None:
                ys_mfe.append((score, mfe))

    # ── grade buckets in canonical order, then any unexpected grades, then ungraded
    seen = set()
    for g in GRADE_ORDER + [k for k in by_grade if k not in GRADE_ORDER and k != "ungraded"] + ["ungraded"]:
        if g in seen:
            continue
        seen.add(g)
        rows = by_grade.get(g, [])
        if len(rows) >= min_n:
            out["by_grade"].append(_bucket_summary(g, rows))

    for b in SCORE_BANDS:
        rows = by_band[b]
        if len(rows) >= min_n:
            label = f"{b[0]}-{b[1]-1 if b[1] <= 100 else 100}"
            out["by_score_band"].append(_bucket_summary(label, rows))

    corr_r = _spearman(xs_score, ys_r) if len(xs_score) >= 5 else None
    corr_mfe = None
    if len(ys_mfe) >= 5:
        corr_mfe = _spearman([s for s, _ in ys_mfe], [m for _, m in ys_mfe])
    out["correlation"] = {
        "spearman_tqs_vs_realized_r": corr_r,
        "spearman_tqs_vs_mfe_r": corr_mfe,
        "n_scored": len(xs_score),
        "n_scored_with_mfe": len(ys_mfe),
    }
    out["overall"] = _bucket_summary("ALL", all_rows)
    out["corrupt_excursions_dropped"] = corrupt
    out["verdict"] = _verdict(corr_mfe, corr_r, len(all_rows))
    out["headline"] = _headline(out)
    return out


def _headline(out):
    v = out.get("verdict")
    c = out["correlation"].get("spearman_tqs_vs_mfe_r")
    grades = out.get("by_grade", [])
    msg = {
        "predictive": "TQS PREDICTS entry quality — tighten the gate toward top grades.",
        "weak": "TQS is a WEAK predictor of entry quality — partial signal only.",
        "non_predictive": "TQS does NOT predict entry quality (noise) — rework TQS against MFE, not gate thresholds.",
        "inverted": "TQS is INVERTED — higher TQS = worse entries. Actively harmful; audit the score immediately.",
        "insufficient": "Insufficient scored sample for a TQS-predictiveness verdict.",
    }.get(v, v)
    if grades:
        best = grades[0]
        worst = grades[-1]
        return (f"{msg} (spearman(TQS,MFE)={c}; top bucket {best['bucket']} "
                f"avg_mfe_r={best.get('avg_mfe_r')} vs {worst['bucket']} "
                f"avg_mfe_r={worst.get('avg_mfe_r')})")
    return msg


# ── Per-pillar predictiveness ────────────────────────────────────────────────
# Which of the 5 TQS pillars actually tracks entry quality (MFE_R)? Reads the
# pillar subscores persisted at entry under bot_trades.entry_context.tqs.
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]


def _tertile_mfe(pairs):
    """pairs = [(pillar_score, mfe_r)]. avg MFE in low/mid/high score tertiles."""
    pairs = [(s, m) for s, m in pairs if s is not None and m is not None]
    if len(pairs) < 9:
        return None
    pairs.sort(key=lambda x: x[0])
    n = len(pairs)
    a, b = n // 3, 2 * n // 3

    def am(seg):
        ms = [m for _, m in seg]
        return round(sum(ms) / len(ms), 3) if ms else None
    return {"low": am(pairs[:a]), "mid": am(pairs[a:b]), "high": am(pairs[b:])}


def generate_pillar_report(db, days: int = 30, min_n: int = 30) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "n": 0, "pillars": [], "current_weights": {},
        "suggested_weights_by_mfe_signal": {}, "composite_spearman_vs_mfe": None,
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    proj = {"_id": 0, "entry_context": 1, "realized_pnl": 1, "risk_amount": 1,
            "mfe_r": 1, "timestamp": 1, "created_at": 1, "closed_at": 1}
    data = {p: {"score": [], "r": [], "mfe": []} for p in PILLARS}
    comp_s, comp_m = [], []
    weight_votes = {}   # json(weights) -> count
    n = 0
    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        ec = t.get("entry_context") or {}
        tqs = (ec.get("tqs") or {}) if isinstance(ec, dict) else {}
        ps = tqs.get("pillar_scores")
        if not isinstance(ps, dict) or not ps:
            continue
        mfe = _f(t.get("mfe_r"))
        if mfe is not None and abs(mfe) > MAX_PLAUSIBLE_R:
            mfe = None
        n += 1
        w = tqs.get("weights")
        if isinstance(w, dict) and w:
            key = ",".join(f"{p}:{round(_f(w.get(p)) or 0, 3)}" for p in PILLARS)
            weight_votes[key] = weight_votes.get(key, 0) + 1
        for p in PILLARS:
            sc = _f(ps.get(p))
            if sc is None:
                continue
            data[p]["score"].append(sc)
            data[p]["r"].append(r)
            data[p]["mfe"].append(mfe)
        comp = _f(tqs.get("post_gate_score") or tqs.get("score"))
        if comp is not None and mfe is not None:
            comp_s.append(comp)
            comp_m.append(mfe)

    # modal weights actually in force
    cur_w = {}
    if weight_votes:
        top = max(weight_votes.items(), key=lambda kv: kv[1])[0]
        cur_w = {kv.split(":")[0]: float(kv.split(":")[1]) for kv in top.split(",")}

    rows = []
    for p in PILLARS:
        d = data[p]
        pairs = [(s, m) for s, m in zip(d["score"], d["mfe"]) if m is not None]
        rows.append({
            "pillar": p,
            "n": len(d["score"]),
            "current_weight": cur_w.get(p),
            "spearman_vs_mfe": _spearman([s for s, _ in pairs], [m for _, m in pairs]) if len(pairs) >= min_n else None,
            "spearman_vs_r": _spearman(d["score"], d["r"]) if len(d["score"]) >= min_n else None,
            "mfe_by_score_tertile": _tertile_mfe(pairs),
        })
    rows.sort(key=lambda x: (x["spearman_vs_mfe"] is None, -(x["spearman_vs_mfe"] or -9.0)))

    pos = {r["pillar"]: r["spearman_vs_mfe"] for r in rows
           if r["spearman_vs_mfe"] and r["spearman_vs_mfe"] > 0}
    tot = sum(pos.values())
    suggested = {p: round(v / tot, 2) for p, v in pos.items()} if tot else {}

    out.update({
        "n": n, "pillars": rows, "current_weights": cur_w,
        "suggested_weights_by_mfe_signal": suggested,
        "composite_spearman_vs_mfe": _spearman(comp_s, comp_m) if len(comp_s) >= min_n else None,
    })
    best = rows[0] if rows else {}
    out["headline"] = (
        f"Most-predictive pillar: {best.get('pillar')} "
        f"(spearman_vs_mfe={best.get('spearman_vs_mfe')}, weight={best.get('current_weight')}). "
        f"Suggested MFE-signal weights: {suggested or 'no pillar shows positive MFE signal'}."
    )
    return out

