"""MFE/MAE study (read-only) — is the bleed from BAD ENTRIES or BAD EXITS?

Per horizon class, aggregates each closed trade's max-favorable (MFE_R) and
max-adverse (MAE_R) excursion vs realized R (all already persisted on bot_trades):

  • low MFE_R                      -> trades never work  -> ENTRY problem (fix TQS).
  • losers that were up >= +1R     -> went green then reversed -> EXIT giveback.
  • big avg(MFE - realized) + low  -> winners give back their run -> EXIT geometry
    winner-capture                    / no time-decay / late trail.

Pure read-model. Emits a per-horizon verdict (entry_problem | exit_giveback | mixed
| ok) so we know whether to prioritise TQS (entries) or exit-geometry/time-decay.
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import median

logger = logging.getLogger(__name__)

GREEN_R = 1.0   # "the trade worked" threshold (reached +1R favorable)
MAX_PLAUSIBLE_R = 10.0   # v19.34.401 — drop legacy-corrupt excursions (the pre-fix
#                           current_price<=0 bug wrote mae_r ~ -50R). Realized R is
#                           already clamped to ±10; MFE/MAE beyond that is corruption.


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


def _verdict(avg_mfe, frac_losers_green, giveback, winner_capture, n):
    if n < 10:
        return "insufficient"
    if avg_mfe is not None and avg_mfe < 0.5:
        return "entry_problem"          # trades rarely move our way
    if frac_losers_green is not None and frac_losers_green > 0.35:
        return "exit_giveback"          # 1/3+ of losers were up >=1R first
    if (giveback is not None and giveback > 0.8
            and winner_capture is not None and winner_capture < 0.5):
        return "exit_giveback"          # winners hand back most of their run
    return "mixed"


def generate_report(db, days: int = 30) -> dict:
    from services.horizon_funnel import horizon_of, HORIZONS

    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "horizons": [],
        "overall": {},
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    buckets = {h: [] for h in HORIZONS}
    corrupt = 0
    proj = {"setup_type": 1, "status": 1, "realized_pnl": 1, "risk_amount": 1,
            "mfe_r": 1, "mae_r": 1, "timestamp": 1, "created_at": 1,
            "entry_time": 1, "opened_at": 1, "closed_at": 1}
    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        mfe, mae = _f(t.get("mfe_r")), _f(t.get("mae_r"))
        # v19.34.401 — discard physically-impossible excursions from legacy
        # corruption so the verdict isn't poisoned by -50R MAE artifacts.
        if mfe is not None and abs(mfe) > MAX_PLAUSIBLE_R:
            mfe = None
            corrupt += 1
        if mae is not None and abs(mae) > MAX_PLAUSIBLE_R:
            mae = None
            corrupt += 1
        if r is None:
            continue
        buckets[horizon_of(t.get("setup_type"))].append((r, mfe, mae))

    all_rows = []
    for h in HORIZONS:
        rows = buckets[h]
        all_rows += rows
        out["horizons"].append(_summarize(h, rows))
    out["overall"] = _summarize("ALL", all_rows)
    out["corrupt_excursions_dropped"] = corrupt
    return out


def _summarize(label, rows):
    n = len(rows)
    base = {"horizon": label, "n_closed": n}
    if n == 0:
        base.update({"verdict": "no_data"})
        return base
    rs = [r for r, _, _ in rows]
    mfes = [m for _, m, _ in rows if m is not None]
    maes = [a for _, _, a in rows if a is not None]
    losers = [(r, m) for r, m, _ in rows if r <= 0]
    winners = [(r, m) for r, m, _ in rows if r > 0]

    avg_mfe = round(sum(mfes) / len(mfes), 3) if mfes else None
    avg_mae = round(sum(maes) / len(maes), 3) if maes else None
    avg_r = round(sum(rs) / len(rs), 3)
    losers_green = [1 for r, m in losers if m is not None and m >= GREEN_R]
    frac_losers_green = round(len(losers_green) / len(losers), 3) if losers else None
    # v19.34.401 — capture can't exceed 1.0 by definition (you can't keep more
    # than the peak). Clamp legacy under-sampled mfe (m < r) to r so the metric
    # is trustworthy on mixed pre/post-fix data.
    cap = [r / max(m, r) for r, m in winners if m and m > 0]
    winner_capture = round(sum(cap) / len(cap), 3) if cap else None
    giveback = round(avg_mfe - avg_r, 3) if avg_mfe is not None else None

    base.update({
        "win_rate": round(sum(1 for r in rs if r > 0) / n * 100, 1),
        "avg_r": avg_r,
        "median_r": round(median(rs), 3),
        "avg_mfe_r": avg_mfe,
        "avg_mae_r": avg_mae,
        "giveback_r": giveback,                         # avg run handed back
        "winner_capture": winner_capture,               # realized/MFE for winners
        "pct_losers_reached_1r": frac_losers_green,      # went green then lost
        "n_winners": len(winners),
        "n_losers": len(losers),
        "verdict": _verdict(avg_mfe, frac_losers_green, giveback, winner_capture, n),
    })
    return base



def repair_corrupt_excursions(db, apply: bool = False,
                              max_r: float = MAX_PLAUSIBLE_R) -> dict:
    """v19.34.401 — one-time repair of physically-impossible mfe_r/mae_r on closed
    bot_trades (legacy of the pre-fix current_price<=0 bug, e.g. mae_r ~ -50R).

    These corrupt rows poison ALL consumers (setup_grading, exit_archetype), not
    just the study. We reset ONLY corrupt fields to the safe realized-R bound
    (mfe_r=max(0,realized_r), mae_r=min(0,realized_r)) — a conservative lower
    bound that is never worse than reality. Sane rows are NEVER touched.

    DRY-RUN by default (apply=False) — returns what WOULD change. apply=True writes.
    """
    out = {"dry_run": not apply, "max_r": max_r, "scanned": 0,
           "corrupt_found": 0, "repaired": 0, "skipped_no_realized": 0,
           "samples": []}
    if db is None:
        return out
    proj = {"_id": 0, "id": 1, "trade_id": 1, "symbol": 1, "realized_pnl": 1,
            "risk_amount": 1, "mfe_r": 1, "mae_r": 1}
    cur = db["bot_trades"].find(
        {"status": "closed",
         "$or": [{"mfe_r": {"$gt": max_r}}, {"mfe_r": {"$lt": -max_r}},
                 {"mae_r": {"$gt": max_r}}, {"mae_r": {"$lt": -max_r}}]}, proj)
    for t in cur:
        out["scanned"] += 1
        mfe, mae = _f(t.get("mfe_r")), _f(t.get("mae_r"))
        bad_mfe = mfe is not None and abs(mfe) > max_r
        bad_mae = mae is not None and abs(mae) > max_r
        if not (bad_mfe or bad_mae):
            continue
        out["corrupt_found"] += 1
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            out["skipped_no_realized"] += 1
            continue
        set_fields = {}
        if bad_mfe:
            set_fields["mfe_r"] = round(max(0.0, r), 3)
        if bad_mae:
            set_fields["mae_r"] = round(min(0.0, r), 3)
        if len(out["samples"]) < 15:
            out["samples"].append({
                "symbol": t.get("symbol"),
                "old_mfe_r": mfe, "old_mae_r": mae,
                "new_mfe_r": set_fields.get("mfe_r"),
                "new_mae_r": set_fields.get("mae_r")})
        if apply and set_fields:
            set_fields["excursion_repair"] = "v19_34_401"
            tid = t.get("id") or t.get("trade_id")
            db["bot_trades"].update_one(
                {"$or": [{"id": tid}, {"trade_id": tid}]}, {"$set": set_fields})
            out["repaired"] += 1
    return out
