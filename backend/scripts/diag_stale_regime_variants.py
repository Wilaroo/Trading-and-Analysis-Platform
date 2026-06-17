#!/usr/bin/env python3
"""
diag_stale_regime_variants.py  —  READ-ONLY  (2026-06-16, v320 prep)

Goal: produce the EXACT list of regime-conditional `direction_predictor_*`
variants and their `last_trained` (saved_at/updated_at) so we can decide
whether to kick off a targeted retrain for P-WIRE Phase 2.

Background (see /app/memory/AUDIT_model_families_2026-06-10.md + v19.34.313):
- Regime variants `direction_predictor_{1min|5min|15min|1hour}_{bull_trend|
  bear_trend|range_bound|high_vol}` are HEALTHY two-sided (acc 0.52-0.78)
  but DEAD at inference (live layer loads only the base variant).
- v19.34.313 wired them into SHADOW MODE; Phase 2 will wire them live.
- This script proves which of those models are stale (>14d since promotion)
  and which are still fresh enough to keep.

Also prints (for transparency) the DEPRECATED families that should NOT be
retrained: risk_of_ruin, sector_relative, legacy gap_fill (daily/weekly).

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_stale_regime_variants.py

Pure read-only. No writes. No side-effects.
"""
import os
import re
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
COLL = "timeseries_models"

# A "stale" regime variant = promoted more than STALE_DAYS ago.
STALE_DAYS = 14
EDGE_FLOOR = 0.52

REGIMES = ("bull_trend", "bear_trend", "range_bound", "high_vol")
REGIME_RX = re.compile(
    r"^direction_predictor_(1min|5min|15min|1hour)_(" + "|".join(REGIMES) + r")$"
)

DEPRECATED_RX = {
    "risk_of_ruin (RETIRED v19.34.314)": re.compile(r"^risk_of_ruin"),
    "sector_relative (RETIRED v19.34.314)": re.compile(r"^sector_relative"),
    "gap_fill legacy daily/weekly (REDESIGNED v19.34.314)":
        re.compile(r"^gap_fill_(daily|weekly)"),
}


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _ts(doc):
    """Return best-available promotion/save timestamp as aware UTC datetime."""
    for k in ("saved_at", "updated_at", "promoted_at", "created_at", "trained_at"):
        v = doc.get(k)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _acc(doc):
    m = doc.get("metrics") or {}
    for src in (m, doc):
        for k in ("accuracy", "val_accuracy", "test_accuracy",
                  "cv_accuracy", "oos_accuracy"):
            v = src.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _samples(doc):
    m = doc.get("metrics") or {}
    for src in (doc, m):
        for k in ("training_samples", "samples", "n_samples", "total_samples"):
            v = src.get(k)
            if isinstance(v, (int, float)):
                return int(v)
    return None


def _fmt_age(dt, now):
    if dt is None:
        return ("?", "?")
    age = now - dt
    days = age.days
    return (dt.strftime("%Y-%m-%d"), f"{days}d")


def _row(doc, now):
    name = doc.get("name", "?")
    dt = _ts(doc)
    date_str, age_str = _fmt_age(dt, now)
    acc = _acc(doc)
    acc_str = f"{acc:.3f}" if acc is not None else "  n/a"
    m = doc.get("metrics") or {}
    ru = m.get("recall_up")
    rd = m.get("recall_down")
    ru_str = f"{float(ru):.2f}" if isinstance(ru, (int, float)) else "  ?"
    rd_str = f"{float(rd):.2f}" if isinstance(rd, (int, float)) else "  ?"
    samples = _samples(doc)
    n_str = f"{samples:>6}" if samples is not None else "     ?"
    days_int = (now - dt).days if dt is not None else None
    stale = days_int is not None and days_int > STALE_DAYS
    edge = acc is not None and acc >= EDGE_FLOOR
    collapsed = (isinstance(ru, (int, float)) and isinstance(rd, (int, float))
                 and min(float(ru), float(rd)) < 0.15)
    flags = []
    if stale:
        flags.append("STALE")
    if collapsed:
        flags.append("COLLAPSE")
    if edge and not collapsed:
        flags.append("EDGE")
    flag_str = ",".join(flags) if flags else "-"
    return (name, date_str, age_str, acc_str, ru_str, rd_str, n_str,
            flag_str, dt, stale)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    print(f"DB: {DB_NAME}  ·  collection: {COLL}")
    print(f"STALE threshold: >{STALE_DAYS}d since promotion  "
          f"·  EDGE floor: acc>={EDGE_FLOOR}")
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    col = db[COLL]
    now = datetime.now(timezone.utc)

    # ---- Regime-conditional variants -------------------------------------
    hr("REGIME-CONDITIONAL VARIANTS  (direction_predictor_{tf}_{regime})")
    docs = list(col.find(
        {"name": {"$regex": "^direction_predictor_.*_(bull_trend|bear_trend|"
                            "range_bound|high_vol)$"}},
        {"_id": 0, "name": 1, "metrics": 1, "version": 1,
         "updated_at": 1, "saved_at": 1, "promoted_at": 1,
         "created_at": 1, "trained_at": 1, "training_samples": 1},
    ))
    # Filter to the canonical {tf}_{regime} pattern only (avoid stray names).
    docs = [d for d in docs if REGIME_RX.match(d.get("name", ""))]
    print(f"\nfound {len(docs)} regime variants in DB")
    print(f"  {'name':>44} {'last_trained':>12} {'age':>6} "
          f"{'acc':>6} {'r_up':>5} {'r_dn':>5} {'n_samp':>8}  flags")
    rows = [_row(d, now) for d in docs]
    rows.sort(key=lambda r: (r[8] or datetime.min.replace(tzinfo=timezone.utc)))
    stale_rows = []
    for r in rows:
        name, date_str, age_str, acc_str, ru_str, rd_str, n_str, flag_str, _, stale = r
        print(f"  {name:>44} {date_str:>12} {age_str:>6} "
              f"{acc_str:>6} {ru_str:>5} {rd_str:>5} {n_str:>8}  {flag_str}")
        if stale:
            stale_rows.append(r)

    # Coverage matrix
    hr("COVERAGE MATRIX  (timeframe × regime)")
    timeframes = ("1min", "5min", "15min", "1hour")
    present = {(REGIME_RX.match(d["name"]).group(1),
                REGIME_RX.match(d["name"]).group(2)) for d in docs}
    header = f"  {'tf/regime':>10} | " + " | ".join(f"{r:>11}" for r in REGIMES)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for tf in timeframes:
        cells = []
        for r in REGIMES:
            cells.append(" present" if (tf, r) in present else " MISSING")
        print(f"  {tf:>10} | " + " | ".join(f"{c:>11}" for c in cells))
    total_expected = len(timeframes) * len(REGIMES)
    print(f"\n  present: {len(present)}/{total_expected} "
          f"(missing: {total_expected - len(present)})")

    # ---- Deprecated families (for transparency) --------------------------
    hr("DEPRECATED FAMILIES  (DO NOT RETRAIN — listed for sanity check only)")
    for title, rx in DEPRECATED_RX.items():
        deps = list(col.find(
            {"name": {"$regex": rx.pattern}},
            {"_id": 0, "name": 1, "metrics": 1, "saved_at": 1,
             "updated_at": 1, "promoted_at": 1, "created_at": 1, "trained_at": 1},
        ))
        print(f"\n  {title}  →  {len(deps)} docs still in collection")
        if deps:
            for d in deps:
                dt = _ts(d)
                date_str, age_str = _fmt_age(dt, now)
                acc = _acc(d)
                acc_str = f"{acc:.3f}" if acc is not None else "  n/a"
                print(f"     {d['name']:>40}  last={date_str}  age={age_str:>5}  acc={acc_str}")

    # ---- Summary ---------------------------------------------------------
    hr("SUMMARY")
    print(f"  regime variants in DB:      {len(docs)}")
    print(f"  stale (>{STALE_DAYS}d):              {len(stale_rows)}")
    print(f"  missing coverage cells:     "
          f"{total_expected - len(present)} / {total_expected}")
    print("\n  STALE NAMES (proposed retrain hit-list, sorted oldest→newest):")
    if not stale_rows:
        print("     (none)")
    else:
        for r in stale_rows:
            name, date_str, _, acc_str, _, _, _, flag_str, _, _ = r
            print(f"     - {name}   (last={date_str}, acc={acc_str}, flags={flag_str})")

    print("\n  Next step: confirm this hit-list with operator, then build a")
    print("  paste.rs `retrain_regime_variants_v320*.py` patcher that drives")
    print("  training_pipeline.py with phases=['regime_conditional'] limited")
    print("  to just these names. v19.34.312 P0 collapse-promotion gate will")
    print("  auto-reject any retrain that still collapses.")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
