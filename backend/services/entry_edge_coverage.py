"""Entry Edge Score — Phase 0 field-coverage report (READ-ONLY).

Measures how DARK each field the regime-conditional Entry Edge Score needs is,
on closed `bot_trades` (+ nested `entry_context`). No model, no side effects.

WHY: the model can only condition on a dimension once that dimension is reliably
PRESENT on the trade record. The TQS deep-dive proved the old composite collapsed
to noise partly because 60-80% of inputs were absent and silently defaulted to 50.
This report is the gate that tells us when each Phase-0 field (sector_regime,
rs_rating, symbol_rs_regime, trigger_price/drift) is light enough to build P4'.

Locked plan: memory/ENTRY_EDGE_SCORE_PLAN.md
"""
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

from services.tqs_entry_quality import _f, _clean_r, MAX_PLAUSIBLE_R
from services.entry_feature_discovery import _get, _trigger_drift

logger = logging.getLogger(__name__)

# The 6 dimensions that form the Entry Edge Score archetype cell. A trade is only
# usable by the regime-conditional model when ALL of these are present.
ARCHETYPE_DIMS = [
    "setup_type", "direction", "timeframe",
    "time_window", "market_regime", "sector_regime", "symbol_rs_regime",
]


def _setup(t, ec):
    return (t.get("setup_type") or ec.get("scanner_setup_type")) or None


def _label(v):
    """Categorical present-check: None/''/'unknown' all count as DARK."""
    return v if v not in (None, "", "unknown") else None


def _extractors():
    """field -> (kind, is_categorical, extractor(t, ec) -> present-value or None)."""
    return {
        # --- Phase 0 NEW fields (the keystone gaps this phase fills) ---
        "sector_regime":   ("phase0_new", True,  lambda t, ec: _label(ec.get("sector_regime"))),
        "rs_rating":       ("phase0_new", False, lambda t, ec: _f(ec.get("rs_rating"))),
        "symbol_rs_regime":("phase0_new", True,  lambda t, ec: _label(ec.get("symbol_rs_regime"))),
        "trigger_price":   ("phase0_new", False, lambda t, ec: (_f(t.get("trigger_price") or ec.get("trigger_price")) or None)),
        "trigger_drift_pct":("phase0_new", False, lambda t, ec: _trigger_drift(t, ec)),
        # --- archetype-key dims (needed to bucket every trade) ---
        "setup_type":      ("archetype", True,  lambda t, ec: _label(_setup(t, ec))),
        "direction":       ("archetype", True,  lambda t, ec: _label(t.get("direction"))),
        "timeframe":       ("archetype", True,  lambda t, ec: _label(t.get("timeframe"))),
        "time_window":     ("archetype", True,  lambda t, ec: _label(ec.get("time_window"))),
        "market_regime":   ("archetype", True,  lambda t, ec: _label(ec.get("market_regime"))),
        "regime_score":    ("archetype", False, lambda t, ec: _f(ec.get("regime_score"))),
        # --- robust continuous predictors (from the n=1002 discovery) ---
        "rsi":             ("predictor", False, lambda t, ec: _f(_get(ec, "technicals", "rsi"))),
        "trigger_probability":("predictor", False, lambda t, ec: _f(ec.get("trigger_probability"))),
        "tape_score":      ("predictor", False, lambda t, ec: _f(t.get("tape_score") if t.get("tape_score") is not None else ec.get("tape_score"))),
        # --- outcome labels (the model learns from these) ---
        "mfe_r":           ("label", False, lambda t, ec: _f(t.get("mfe_r"))),
        "realized_R":      ("label", False, lambda t, ec: _clean_r(t.get("realized_pnl"), t.get("risk_amount"))),
    }


def generate_report(db, days: int = 45, recent_days: int = 3) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "n": 0, "fields": [], "archetype_cell": {}, "headline": "no data",
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    proj = {"_id": 0, "entry_context": 1, "realized_pnl": 1, "risk_amount": 1,
            "mfe_r": 1, "setup_type": 1, "timeframe": 1, "direction": 1,
            "entry_price": 1, "trigger_price": 1, "tape_score": 1,
            "timestamp": 1, "created_at": 1, "closed_at": 1}

    ext = _extractors()
    present = {f: 0 for f in ext}
    values = {f: Counter() for f, (_, is_cat, _) in ext.items() if is_cat}
    cell_complete = 0
    cell_complete_with_label = 0
    n = 0

    for t in db["bot_trades"].find({"status": "closed"}, proj):
        ts = t.get("closed_at") or t.get("timestamp") or t.get("created_at")
        if ts and str(ts) < cutoff:
            continue
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue  # not a real, label-bearing closed trade
        ec = t.get("entry_context") or {}
        if not isinstance(ec, dict):
            ec = {}
        n += 1

        for f, (_, is_cat, fn) in ext.items():
            try:
                v = fn(t, ec)
            except Exception:
                v = None
            if v is not None and not (f == "mfe_r" and abs(v) > MAX_PLAUSIBLE_R):
                present[f] += 1
                if is_cat:
                    values[f][str(v)] += 1

        dims_ok = all(ext[d][2](t, ec) is not None for d in ARCHETYPE_DIMS)
        if dims_ok:
            cell_complete += 1
            mfe = _f(t.get("mfe_r"))
            if mfe is not None and abs(mfe) <= MAX_PLAUSIBLE_R:
                cell_complete_with_label += 1

    def pct(x):
        return round(x / n * 100, 1) if n else 0.0

    rows = []
    for f, (kind, is_cat, _) in ext.items():
        row = {"field": f, "kind": kind, "present": present[f],
               "coverage_pct": pct(present[f])}
        if is_cat:
            row["top_values"] = values[f].most_common(6)
        rows.append(row)
    # group by kind (phase0_new first), then ascending coverage so the darkest float up
    kind_order = {"phase0_new": 0, "archetype": 1, "predictor": 2, "label": 3}
    rows.sort(key=lambda x: (kind_order.get(x["kind"], 9), x["coverage_pct"]))

    out.update({
        "n": n,
        "fields": rows,
        "archetype_cell": {
            "dims": ARCHETYPE_DIMS,
            "complete": cell_complete,
            "complete_pct": pct(cell_complete),
            "complete_with_label": cell_complete_with_label,
            "complete_with_label_pct": pct(cell_complete_with_label),
        },
    })

    p0 = [r for r in rows if r["kind"] == "phase0_new"]
    darkest = min(p0, key=lambda x: x["coverage_pct"]) if p0 else None
    out["headline"] = (
        "n=%d closed trades | archetype-cell COMPLETE (all %d dims) on %s%% "
        "(with MFE label: %s%%) | darkest Phase-0 field: %s @ %s%%" % (
            n, len(ARCHETYPE_DIMS),
            out["archetype_cell"]["complete_pct"],
            out["archetype_cell"]["complete_with_label_pct"],
            darkest["field"] if darkest else None,
            darkest["coverage_pct"] if darkest else None,
        )
    )

    # ── Phase-0 STAMPING freshness (decisive working-vs-broken test) ──
    # The loop above is closed-only over a wide `days` window, so a just-deployed
    # stamp is invisible until those trades close. This scans trades ENTERED in the
    # last `recent_days` (ANY status) to see whether NEW fills actually receive the
    # Phase-0 fields. 0% here too ⇒ the alert dict isn't carrying them (source gap,
    # not a window artefact). Read-only.
    out["phase0_recent"] = _recent_stamp_check(db, recent_days)
    return out


def _recent_stamp_check(db, recent_days: int) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=recent_days)).isoformat()
    fields = ["sector_regime", "rs_rating", "symbol_rs_regime", "trigger_price"]
    ext = _extractors()
    present = {f: 0 for f in fields}          # has a REAL (non-dark) value
    key_present = {f: 0 for f in fields}      # the entry_context KEY exists at all
    rn = 0
    samples = []
    proj = {"_id": 0, "entry_context": 1, "setup_type": 1, "direction": 1,
            "timeframe": 1, "trigger_price": 1, "tape_score": 1, "status": 1,
            "symbol": 1, "created_at": 1, "timestamp": 1}
    # entry_context keys for the raw-presence check (trigger_price lives on the trade
    # OR ec; sector/rs live on ec only).
    ec_keys = {"sector_regime": "sector_regime", "rs_rating": "rs_rating",
               "symbol_rs_regime": "symbol_rs_regime", "trigger_price": "trigger_price"}
    cur = db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": cutoff}}, {"timestamp": {"$gte": cutoff}}]},
        proj).sort("created_at", -1).limit(500)
    for t in cur:
        ec = t.get("entry_context") or {}
        if not isinstance(ec, dict):
            ec = {}
        rn += 1
        row = {}
        for f in fields:
            try:
                v = ext[f][2](t, ec)
            except Exception:
                v = None
            if v is not None:
                present[f] += 1
            has_key = (ec_keys[f] in ec) or (f == "trigger_price" and "trigger_price" in t)
            if has_key:
                key_present[f] += 1
            if len(samples) < 8:
                row["raw_" + f] = ec.get(ec_keys[f]) if ec_keys[f] in ec else (
                    t.get("trigger_price") if f == "trigger_price" else "<no key>")
        if len(samples) < 8:
            samples.append({
                "symbol": t.get("symbol"),
                "status": t.get("status"),
                "created_at": t.get("created_at") or t.get("timestamp"),
                "ec_has_sector_key": "sector_regime" in ec,
                **row,
            })

    def pct(x):
        return round(x / rn * 100, 1) if rn else 0.0

    sec_keys = key_present["sector_regime"]
    if rn == 0:
        verdict = "no recent trades"
    elif sec_keys == 0:
        verdict = ("STAMP NOT LIVE for these trades — entry_context has NO Phase-0 keys "
                   "(they predate the stamp code running on the DGX). Retest after the "
                   "next RTH session with the current build.")
    elif present["sector_regime"] == 0:
        verdict = ("STAMP LIVE but SOURCE DARK — keys are written but sector_regime is "
                   "'unknown'/empty (the alert isn't carrying it). Source-gap fix needed.")
    else:
        verdict = "STAMPING LIVE"

    return {
        "recent_days": recent_days,
        "n_recent_trades": rn,
        "coverage_pct": {f: pct(present[f]) for f in fields},
        "key_present_pct": {f: pct(key_present[f]) for f in fields},
        "samples": samples,
        "verdict": verdict,
    }
