"""Entry feature discovery (read-only) — WHICH entry-context fields predict MFE?

The TQS audit proved all 5 pillars are noise vs entry quality (MFE_R). But setup-EV
shows raw dimensions (setup_type, regime, direction) clearly separate outcomes — so
the edge lives in entry-context fields the pillars don't capture. This tool ranks
every available entry-context field by how well it predicts realized entry quality,
so the rebuilt entry score can be assembled from signals that actually generalise.

Pure read-model over closed `bot_trades` (+ nested `entry_context`). For CONTINUOUS
features: Spearman rank-corr vs MFE_R and realized_R. For CATEGORICAL features:
eta-squared (correlation ratio, 0..1 — fraction of outcome variance the field
explains) plus the best/worst categories by avg MFE_R. No model, no side effects.
"""
import logging
from datetime import datetime, timezone, timedelta

from services.tqs_entry_quality import _spearman, _clean_r, _f, MAX_PLAUSIBLE_R

logger = logging.getLogger(__name__)


def _get(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _minutes_from_open(hhmmss):
    """ET wall-clock 'HH:MM:SS' → minutes since the 09:30 open."""
    if not hhmmss or not isinstance(hhmmss, str):
        return None
    parts = hhmmss.split(":")
    if len(parts) < 2:
        return None
    try:
        m = int(parts[0]) * 60 + int(parts[1]) - (9 * 60 + 30)
    except ValueError:
        return None
    return m if -60 <= m <= 600 else None


def _trigger_drift(t, ec):
    """Signed 'chase' % past the trigger (positive = paid up beyond the signal).
    Best-effort: trigger_price is not always persisted; coverage is reported."""
    ep = _f(t.get("entry_price"))
    tp = _f(t.get("trigger_price") or ec.get("trigger_price") or _get(ec, "trigger", "price"))
    if not ep or not tp or tp <= 0:
        return None
    d = (ep - tp) / tp
    if (t.get("direction") or "").lower() in ("short", "sell"):
        d = -d
    return round(d * 100, 4)


def _continuous(t, ec):
    g = _f(ec.get("gap_pct"))
    return {
        "scanner_score": _f(ec.get("score")),
        "trigger_probability": _f(ec.get("trigger_probability")),
        "regime_score": _f(ec.get("regime_score")),
        "filter_win_rate": _f(ec.get("filter_win_rate")),
        "strategy_win_rate": _f(ec.get("strategy_win_rate")),
        "atr_percent": _f(ec.get("atr_percent")),
        "rvol": _f(ec.get("rvol")),
        "gap_pct_abs": abs(g) if g is not None else None,
        "rsi": _f(_get(ec, "technicals", "rsi")),
        "gate_confidence_score": _f(_get(ec, "confidence_gate", "confidence_score")),
        "gate_position_multiplier": _f(_get(ec, "confidence_gate", "position_multiplier")),
        "tape_score": _f(t.get("tape_score") if t.get("tape_score") is not None else ec.get("tape_score")),
        "minutes_from_open": _minutes_from_open(ec.get("entry_time_et")),
        "trigger_drift_pct": _trigger_drift(t, ec),
        "risk_reward_ratio": _f(t.get("risk_reward_ratio")),
    }


def _categorical(t, ec):
    def s(v):
        return str(v).lower() if v not in (None, "") else None
    tc = ec.get("tape_confirmation")
    return {
        "setup_type": s(t.get("setup_type") or ec.get("scanner_setup_type")),
        "market_regime": s(ec.get("market_regime")),
        "direction": s(t.get("direction")),
        "time_window": s(ec.get("time_window")),
        "timeframe": s(t.get("timeframe")),
        "priority": s(ec.get("priority")),
        "tape_confirmed": ("yes" if tc else "no") if tc is not None else None,
        "catalyst_tag": s(ec.get("catalyst_tag")),
        "trend": s(_get(ec, "technicals", "trend")),
        "vwap_relation": s(_get(ec, "technicals", "vwap_relation")),
        "volume_trend": s(_get(ec, "technicals", "volume_trend")),
        "filter_action": s(ec.get("filter_action")),
        "gate_decision": s(_get(ec, "confidence_gate", "decision")),
    }


def _eta2(groups):
    """Correlation ratio eta^2 over category → list[value]. 0..1."""
    vals = [v for g in groups.values() for v in g]
    n = len(vals)
    if n < 2:
        return None
    gm = sum(vals) / n
    ss_tot = sum((v - gm) ** 2 for v in vals)
    if ss_tot == 0:
        return 0.0
    ss_bet = sum(len(g) * ((sum(g) / len(g)) - gm) ** 2 for g in groups.values() if g)
    return round(ss_bet / ss_tot, 4)


def generate_report(db, days: int = 30, min_n: int = 30, cat_min: int = 12) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "n": 0, "continuous": [], "categorical": [],
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    proj = {"_id": 0, "entry_context": 1, "realized_pnl": 1, "risk_amount": 1,
            "mfe_r": 1, "setup_type": 1, "timeframe": 1, "direction": 1,
            "entry_price": 1, "trigger_price": 1, "tape_score": 1,
            "risk_reward_ratio": 1, "timestamp": 1, "created_at": 1, "closed_at": 1}

    cont = {}   # feat -> list[(value, mfe, r)]
    cats = {}   # feat -> {cat -> {"mfe":[], "r":[]}}
    n = 0
    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        ec = t.get("entry_context") or {}
        if not isinstance(ec, dict):
            ec = {}
        mfe = _f(t.get("mfe_r"))
        if mfe is not None and abs(mfe) > MAX_PLAUSIBLE_R:
            mfe = None
        n += 1
        for feat, val in _continuous(t, ec).items():
            if val is not None:
                cont.setdefault(feat, []).append((val, mfe, r))
        for feat, val in _categorical(t, ec).items():
            if val is not None:
                d = cats.setdefault(feat, {}).setdefault(val, {"mfe": [], "r": []})
                if mfe is not None:
                    d["mfe"].append(mfe)
                d["r"].append(r)

    # ── continuous ranking
    crows = []
    for feat, rows in cont.items():
        pairs_m = [(v, m) for v, m, _ in rows if m is not None]
        sp_m = _spearman([v for v, _ in pairs_m], [m for _, m in pairs_m]) if len(pairs_m) >= min_n else None
        sp_r = _spearman([v for v, _, _ in rows], [r for _, _, r in rows]) if len(rows) >= min_n else None
        crows.append({"feature": feat, "n": len(rows),
                      "spearman_vs_mfe": sp_m, "spearman_vs_r": sp_r})
    crows.sort(key=lambda x: (x["spearman_vs_mfe"] is None, -abs(x["spearman_vs_mfe"] or 0)))

    # ── categorical ranking
    krows = []
    for feat, groups in cats.items():
        gm = {c: g["mfe"] for c, g in groups.items() if len(g["mfe"]) >= cat_min}
        gr = {c: g["r"] for c, g in groups.items() if len(g["r"]) >= cat_min}
        if len(gr) < 2:
            continue
        cells = []
        for c, g in groups.items():
            if len(g["r"]) >= cat_min:
                rs = g["r"]
                ms = g["mfe"]
                cells.append({"value": c, "n": len(rs),
                              "avg_r": round(sum(rs) / len(rs), 3),
                              "win_rate": round(sum(1 for x in rs if x > 0) / len(rs) * 100, 1),
                              "avg_mfe_r": round(sum(ms) / len(ms), 3) if ms else None})
        cells.sort(key=lambda x: x["avg_r"], reverse=True)
        krows.append({
            "feature": feat,
            "n": sum(len(g["r"]) for g in groups.values()),
            "n_categories": len(cells),
            "eta2_vs_mfe": _eta2(gm) if len(gm) >= 2 else None,
            "eta2_vs_r": _eta2(gr),
            "best": cells[:3],
            "worst": cells[-3:][::-1],
        })
    krows.sort(key=lambda x: (x["eta2_vs_r"] is None, -(x["eta2_vs_r"] or 0)))

    out.update({"n": n, "continuous": crows, "categorical": krows})
    top_c = next((c for c in crows if c["spearman_vs_mfe"] is not None), None)
    top_k = krows[0] if krows else None
    out["headline"] = (
        "Top continuous predictor: %s (spearman_vs_mfe=%s) | Top categorical: %s "
        "(eta2_vs_r=%s, best=%s)" % (
            top_c["feature"] if top_c else None,
            top_c["spearman_vs_mfe"] if top_c else None,
            top_k["feature"] if top_k else None,
            top_k["eta2_vs_r"] if top_k else None,
            (top_k["best"][0]["value"] if top_k and top_k["best"] else None),
        )
    )
    return out
