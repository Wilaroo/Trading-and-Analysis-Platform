"""Autonomous Strategy On/Off by Regime (P6, ARC-3) — OBSERVE-first read-model.

Bounded autonomy: RECOMMENDS enabling/disabling KNOWN strategy families based on
their live edge x the CURRENT regime — it never invents strategies or hot-tunes
params. Phase-1 is a pure compute-on-read recommendation surface (zero live-loop
cost, zero behavior change). Active enforcement (feeding the recommendations into
the bot's DISABLED_SETUPS gate) is intentionally DEFERRED behind a flag until the
operator reviews a probation window of observe data.

Signal sources (both already maintained — no new pipelines):
  • Current regime band  — latest `market_regime_state.composite_score` -> band_of.
  • Per-(setup x band) expectancy + term-structure — the SAME T6
    `setup_regime_expectancy` table P4/P5 use (cells[`{canon}|{band}`] with
    weighted_mean_r, eff_n, and diag.r_30d / r_90d / r_all).

Recommendation per strategy family (canonical setup) in the CURRENT band:
  • DISABLE — current-band cell is statistically hostile (weighted_mean_r <= hard_r
    with eff_n >= min_eff_n)  => the edge is gone in this regime.
  • WATCH   — soft-hostile (<= soft_r), OR edge-decaying (r_30d <= decay_r AND
    r_30d materially below r_90d) with enough recent sample.
  • ENABLE  — positive/neutral expectancy, no decay flag.
  • UNKNOWN — insufficient sample (eff_n < min_eff_n) -> no opinion, leave as-is.
Operator's static DISABLED_SETUPS is surfaced (already_disabled) so the view is honest.

MODE = off | observe | active  (STRATEGY_AUTONOMY_MODE, default "observe").
"""
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def mode() -> str:
    return os.environ.get("STRATEGY_AUTONOMY_MODE", "observe").strip().lower()


def _decay_r() -> float:
    """r_30d at/below this AND materially below r_90d => edge-decay WATCH."""
    try:
        return float(os.environ.get("STRATEGY_AUTONOMY_DECAY_R", "0.0"))
    except (TypeError, ValueError):
        return 0.0


def _decay_gap() -> float:
    """How far r_30d must sit below r_90d (in R) to count as decaying."""
    try:
        return float(os.environ.get("STRATEGY_AUTONOMY_DECAY_GAP", "0.15"))
    except (TypeError, ValueError):
        return 0.15


def _latest_regime_score(db):
    """Latest persisted composite regime score (market_regime_state)."""
    try:
        doc = db["market_regime_state"].find_one(sort=[("timestamp", -1)])
        if doc:
            return doc.get("composite_score")
    except Exception as e:
        logger.debug("strategy-autonomy regime read failed: %s", e)
    return None


def _classify(cell, params, decaying):
    """-> (recommendation, reason). Pure."""
    if not cell:
        return "UNKNOWN", "no expectancy cell for this setup x regime band"
    eff_n = float(cell.get("eff_n") or 0)
    wmr = cell.get("weighted_mean_r")
    min_n = float(params.get("min_eff_n", 25.0))
    hard_r = float(params.get("hard_r", -0.50))
    soft_r = float(params.get("soft_r", -0.12))
    if wmr is None or eff_n < min_n:
        return "UNKNOWN", f"insufficient sample (eff_n {eff_n:.0f} < {min_n:.0f})"
    if wmr <= hard_r:
        return "DISABLE", f"hostile in regime: weighted_mean_R {wmr:.2f} <= {hard_r:.2f} (eff_n {eff_n:.0f})"
    if wmr <= soft_r:
        return "WATCH", f"soft-hostile: weighted_mean_R {wmr:.2f} <= {soft_r:.2f}"
    if decaying:
        return "WATCH", "edge-decay: recent 30d R deteriorating vs 90d"
    return "ENABLE", f"healthy: weighted_mean_R {wmr:.2f} (eff_n {eff_n:.0f})"


def _is_decaying(cell):
    diag = (cell or {}).get("diag") or {}
    r30, r90 = diag.get("r_30d"), diag.get("r_90d")
    n30 = diag.get("n_30d") or 0
    if r30 is None or r90 is None or n30 < 10:
        return False
    return r30 <= _decay_r() and (r90 - r30) >= _decay_gap()


def generate_report(db) -> dict:
    """Compute-on-read strategy on/off recommendations for the CURRENT regime."""
    from services.ai_modules.regime_expectancy_calibrator import band_of
    from services.entry_gate import parse_disabled_setups

    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "mode": mode(),
        "current_regime_score": None,
        "current_band": None,
        "expectancy_generated_at": None,
        "already_disabled": [],
        "recommendations": [],
        "counts": {"ENABLE": 0, "WATCH": 0, "DISABLE": 0, "UNKNOWN": 0},
    }
    if db is None:
        return out

    score = _latest_regime_score(db)
    band = band_of(score)
    out["current_regime_score"] = score
    out["current_band"] = band
    out["already_disabled"] = sorted(parse_disabled_setups(os.environ.get("DISABLED_SETUPS")))
    if not band:
        return out

    exp = db["setup_regime_expectancy"].find_one({"_id": "current"}) or {}
    cells = exp.get("cells") or {}
    params = exp.get("params") or {}
    out["expectancy_generated_at"] = exp.get("generated_at")

    # Family-level view = the direction-agnostic `{canon}|{band}` cells.
    suffix = f"|{band}"
    families = sorted({
        k[: -len(suffix)] for k in cells
        if k.endswith(suffix) and k.count("|") == 1
    })
    disabled = out["already_disabled"]
    for canon in families:
        cell = cells.get(f"{canon}{suffix}")
        decaying = _is_decaying(cell)
        rec, reason = _classify(cell, params, decaying)
        diag = (cell or {}).get("diag") or {}
        out["recommendations"].append({
            "setup": canon,
            "recommendation": rec,
            "reason": reason,
            "weighted_mean_r": (cell or {}).get("weighted_mean_r"),
            "eff_n": (cell or {}).get("eff_n"),
            "r_30d": diag.get("r_30d"),
            "r_90d": diag.get("r_90d"),
            "decaying": decaying,
            "currently_disabled": canon.lower() in disabled,
        })
        out["counts"][rec] = out["counts"].get(rec, 0) + 1

    # DISABLE first, then WATCH, for operator triage.
    order = {"DISABLE": 0, "WATCH": 1, "ENABLE": 2, "UNKNOWN": 3}
    out["recommendations"].sort(key=lambda r: (order.get(r["recommendation"], 9), r["setup"]))
    return out
