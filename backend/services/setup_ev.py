"""setup_ev — per-setup realized-R audit (read-only).

Answers "which setup_type(s) leak -R?" for a given horizon class, so the operator
can suppress/tighten negative-EV detectors (same playbook as the v353–v363
setup adjudications). Pure read-model over `bot_trades` (status=closed) joined to
realized R via the shared `_clean_r`.

Endpoint: GET /api/slow-learning/setup-ev/report?horizon=swing&days=30&min_n=1
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import mean, median

# Reuse the canonical horizon mapping + R cleaner + timestamp picker so this
# stays consistent with the horizon-funnel + tqs-integrity reports.
from services.horizon_funnel import horizon_of, _clean_r, _ts_field

logger = logging.getLogger(__name__)

HORIZONS = ("scalp", "intraday", "swing", "position", "unknown")


def _winsor_mean(rs, lo_p=10, hi_p=90):
    """Winsorized mean — clamp the tails to the lo/hi percentile so a single
    fat outlier can't flip a setup's verdict (robust EV, matches the v3xx
    'winsorAvg R' convention). Plain mean when n<10."""
    n = len(rs)
    if n < 10:
        return round(mean(rs), 3) if rs else None
    s = sorted(rs)
    lo = s[max(0, int(lo_p / 100.0 * (n - 1)))]
    hi = s[min(n - 1, int(hi_p / 100.0 * (n - 1)))]
    clamped = [min(hi, max(lo, r)) for r in rs]
    return round(mean(clamped), 3)


def _verdict(avg_r, n):
    if n < 10:
        return "thin"            # not enough closed trades to judge
    if avg_r <= -0.10:
        return "bleeding"        # clear negative EV — suppress/tighten candidate
    if avg_r < 0.05:
        return "marginal"        # ~breakeven — watch / refine
    return "healthy"


def _dir_of(t):
    d = t.get("direction")
    d = getattr(d, "value", d)
    d = str(d or "").lower()
    if d in ("long", "buy", "bull", "bullish"):
        return "long"
    if d in ("short", "sell", "bear", "bearish"):
        return "short"
    return "other"


def _agg(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "win_rate": None, "avg_r": None}
    wins = sum(1 for r in rs if r > 0)
    return {"n": n, "win_rate": round(wins / n * 100, 1), "avg_r": round(mean(rs), 3)}


def generate_setup_ev_report(db, days: int = 30, horizon: str = None,
                             min_n: int = 1) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "horizon_filter": horizon or "all",
        "min_n": min_n,
        "setups": [],
        "headline": "",
    }
    if db is None:
        return out

    horizon = (horizon or "").strip().lower() or None
    if horizon and horizon not in HORIZONS:
        out["headline"] = f"unknown horizon '{horizon}' (use {', '.join(HORIZONS)})"
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    buckets = {}  # setup_type -> {"horizon":h, "rs":[], "long":[], "short":[]}
    proj = {"setup_type": 1, "status": 1, "realized_pnl": 1, "risk_amount": 1,
            "direction": 1, "timestamp": 1, "created_at": 1, "entry_time": 1,
            "opened_at": 1, "closed_at": 1}
    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = _ts_field(t)
        if ts and str(ts) < cutoff:
            continue
        st = (t.get("setup_type") or "unknown")
        h = horizon_of(st)
        if horizon and h != horizon:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        b = buckets.setdefault(st, {"horizon": h, "rs": [], "long": [], "short": []})
        b["rs"].append(r)
        d = _dir_of(t)
        if d in ("long", "short"):
            b[d].append(r)

    rows = []
    for st, b in buckets.items():
        rs = b["rs"]
        n = len(rs)
        if n < min_n:
            continue
        avg = round(mean(rs), 3)
        rows.append({
            "setup_type": st,
            "horizon": b["horizon"],
            "n": n,
            "win_rate": round(sum(1 for r in rs if r > 0) / n * 100, 1),
            "avg_r": avg,
            "median_r": round(median(rs), 3),
            "winsor_avg_r": _winsor_mean(rs),
            "total_r": round(sum(rs), 2),
            "by_direction": {"long": _agg(b["long"]), "short": _agg(b["short"])},
            "verdict": _verdict(avg, n),
        })

    # worst total-R bleeders first (where the money actually leaks)
    rows.sort(key=lambda x: x["total_r"])
    out["setups"] = rows

    bleeders = [r for r in rows if r["verdict"] == "bleeding"]
    if bleeders:
        top = bleeders[:3]
        out["headline"] = "Bleeding setups: " + ", ".join(
            f"{r['setup_type']}({r['avg_r']}R n{r['n']}, totR {r['total_r']})" for r in top)
    else:
        out["headline"] = ("No 'bleeding' setups (avg_r<=-0.10 & n>=10) in window"
                           + (f" for horizon={horizon}" if horizon else ""))
    return out
