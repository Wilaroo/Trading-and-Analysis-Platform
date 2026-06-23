"""Horizon Funnel diagnostic (read-only) — why are fast trades crowded out?

Builds a per-horizon-class funnel from durable logs to locate WHERE scalp /
intraday setups are lost vs longer-horizon ones:

  evaluated (gate)  ->  approved (GO+REDUCE)  ->  taken (became a trade)  ->  realized R

Sources (no new pipelines):
  • confidence_gate_log — every gate evaluation (setup_type + decision GO/REDUCE/SKIP + ts).
  • bot_trades          — trades actually taken (+ realized clean-R when closed).
Horizon class via the SSOT trade-style classifier (style_of -> scalp/intraday/
multi_day/swing/investment/position) rolled up to {scalp, intraday, swing, position}.

Pure read-model. Surfaces a per-horizon CHOKE heuristic:
  • under_emitted  — tiny share of gate evaluations (scanner not producing them).
  • gate_veto      — low approve-rate (gate SKIPs them disproportionately).
  • capacity       — approved >> taken (position cap / sizing / exposure crowding out).
  • healthy        — none of the above.
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import median

logger = logging.getLogger(__name__)

HORIZON_OF_STYLE = {
    "scalp": "scalp",
    "intraday": "intraday",
    "multi_day": "swing",
    "swing": "swing",
    "investment": "position",
    "position": "position",
    "unknown": "unknown",
}
HORIZONS = ["scalp", "intraday", "swing", "position", "unknown"]


def horizon_of(setup_type) -> str:
    try:
        from services.setup_taxonomy import style_of
        return HORIZON_OF_STYLE.get(style_of(setup_type or ""), "unknown")
    except Exception:
        return "unknown"


def _clean_r(pnl, risk):
    try:
        ra = float(risk)
        if ra > 0:
            return max(-10.0, min(10.0, float(pnl) / ra))
    except (TypeError, ValueError):
        pass
    return None


def _ts_field(doc):
    for f in ("timestamp", "created_at", "entry_time", "opened_at", "closed_at"):
        v = doc.get(f)
        if v:
            return v
    return None


# Reason codes that indicate capacity/exposure caps bit (post-gate).
CAPACITY_REASONS = (
    "symbol_exposure_saturated", "portfolio_exposure_cap", "position_size_zero",
    "symbol_direction_open_cap", "max_positions", "max_open_positions",
    "dedup_open_position", "exposure_cap", "buying_power",
)


def _is_capacity_reason(rc: str) -> bool:
    rc = (rc or "").lower()
    return any(k in rc for k in CAPACITY_REASONS)


def _capacity_rejections(db, cutoff_iso):
    """Read the bounded rejection_daily_counts (persisted by record_rejection)."""
    out = {"by_horizon": {}, "by_reason": {}, "total": 0, "note": ""}
    try:
        cutoff_date = cutoff_iso[:10]
        cur = db["rejection_daily_counts"].find({"date": {"$gte": cutoff_date}})
        any_rows = False
        for d in cur:
            any_rows = True
            if not _is_capacity_reason(d.get("reason_code")):
                continue
            c = int(d.get("count") or 0)
            h = d.get("horizon") or "unknown"
            rc = d.get("reason_code") or "?"
            out["by_horizon"][h] = out["by_horizon"].get(h, 0) + c
            out["by_reason"][rc] = out["by_reason"].get(rc, 0) + c
            out["total"] += c
        if not any_rows:
            out["note"] = ("awaiting data — record_rejection began persisting "
                           "rejection_daily_counts with this change")
    except Exception as e:
        logger.debug("capacity_rejections read failed: %s", e)
    return out


def generate_report(db, days: int = 30) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "horizons": [],
        "totals": {"evaluated": 0, "approved": 0, "taken": 0},
        "headline": "",
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # spine: gate evaluations by horizon × decision (rows = per scan-cycle).
    # Also track UNIQUE opportunities (distinct alert_id) so the capacity claim
    # isn't inflated by the gate re-logging the same live alert every cycle.
    agg = {h: {"evaluated": 0, "go": 0, "reduce": 0, "skip": 0} for h in HORIZONS}
    uniq_eval = {h: set() for h in HORIZONS}
    uniq_appr = {h: set() for h in HORIZONS}
    for d in db["confidence_gate_log"].find(
        {}, {"setup_type": 1, "decision": 1, "timestamp": 1, "alert_id": 1}
    ):
        ts = d.get("timestamp")
        if ts and str(ts) < cutoff:
            continue
        h = horizon_of(d.get("setup_type"))
        cell = agg[h]
        cell["evaluated"] += 1
        dec = str(d.get("decision") or "").upper()
        aid = d.get("alert_id")
        if aid:
            uniq_eval[h].add(aid)
        if dec == "GO":
            cell["go"] += 1
        elif dec == "REDUCE":
            cell["reduce"] += 1
        elif dec == "SKIP":
            cell["skip"] += 1
        if dec in ("GO", "REDUCE") and aid:
            uniq_appr[h].add(aid)

    # taken + realized by horizon (bot_trades)
    taken = {h: {"taken": 0, "rs": []} for h in HORIZONS}
    for t in db["bot_trades"].find(
        {}, {"setup_type": 1, "status": 1, "realized_pnl": 1, "risk_amount": 1,
             "timestamp": 1, "created_at": 1, "entry_time": 1, "opened_at": 1, "closed_at": 1}
    ):
        ts = _ts_field(t)
        if ts and str(ts) < cutoff:
            continue
        h = horizon_of(t.get("setup_type"))
        taken[h]["taken"] += 1
        if str(t.get("status") or "").lower() == "closed":
            r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
            if r is not None:
                taken[h]["rs"].append(r)

    total_eval = sum(agg[h]["evaluated"] for h in HORIZONS) or 1
    total_taken = sum(taken[h]["taken"] for h in HORIZONS) or 1

    for h in HORIZONS:
        a = agg[h]
        tk = taken[h]
        evaluated = a["evaluated"]
        approved = a["go"] + a["reduce"]
        ev_uniq = len(uniq_eval[h])
        appr_uniq = len(uniq_appr[h])
        rs = tk["rs"]
        wins = sum(1 for r in rs if r > 0)
        # approve-rate on UNIQUE opportunities (falls back to raw if no alert_ids)
        approve_rate = (round(appr_uniq / ev_uniq, 3) if ev_uniq
                        else (round(approved / evaluated, 3) if evaluated else None))
        # capacity = approved unique opportunities that did NOT become trades
        tva_uniq = round(tk["taken"] / appr_uniq, 3) if appr_uniq else None
        eval_share = round(evaluated / total_eval, 3)
        taken_share = round(tk["taken"] / total_taken, 3)

        # choke heuristic on UNIQUE opportunities (skip 'unknown')
        choke = "healthy"
        if h != "unknown":
            if eval_share < 0.05 and evaluated < 0.5 * (total_eval / max(1, len(HORIZONS) - 1)):
                choke = "under_emitted"
            elif approve_rate is not None and approve_rate < 0.4:
                choke = "gate_veto"
            elif appr_uniq > 0 and tk["taken"] < 0.6 * appr_uniq:
                choke = "capacity"

        out["horizons"].append({
            "horizon": h,
            "evaluated": evaluated,
            "evaluated_unique": ev_uniq,
            "eval_share": eval_share,
            "go": a["go"], "reduce": a["reduce"], "skip": a["skip"],
            "approved": approved,
            "approved_unique": appr_uniq,
            "approve_rate": approve_rate,
            "taken": tk["taken"],
            "taken_share": taken_share,
            "taken_vs_approved_unique": tva_uniq,
            "realized": {
                "n_closed": len(rs),
                "win_rate": round(wins / len(rs) * 100, 1) if rs else None,
                "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
                "median_r": round(median(rs), 3) if rs else None,
            },
            "choke": choke,
        })
        out["totals"]["evaluated"] += evaluated
        out["totals"]["approved"] += approved
        out["totals"]["taken"] += tk["taken"]

    # capacity rejections (C-ii) — how often post-gate caps bit, by horizon.
    out["capacity_rejections"] = _capacity_rejections(db, cutoff)

    # headline: fast (scalp+intraday) vs slow (swing+position) shares
    fast_eval = sum(h["evaluated"] for h in out["horizons"] if h["horizon"] in ("scalp", "intraday"))
    fast_taken = sum(h["taken"] for h in out["horizons"] if h["horizon"] in ("scalp", "intraday"))
    out["fast_vs_slow"] = {
        "fast_eval_share": round(fast_eval / total_eval, 3),
        "fast_taken_share": round(fast_taken / total_taken, 3),
    }
    chokes = [h["horizon"] for h in out["horizons"]
              if h["horizon"] in ("scalp", "intraday") and h["choke"] != "healthy"]
    if chokes:
        labels = {h["horizon"]: h["choke"] for h in out["horizons"] if h["horizon"] in chokes}
        out["headline"] = "Fast-trade choke: " + ", ".join(f"{k}={v}" for k, v in labels.items())
    else:
        out["headline"] = "No fast-trade choke detected in window"
    return out
