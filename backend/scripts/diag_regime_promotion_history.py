#!/usr/bin/env python3
"""
diag_regime_promotion_history.py  —  READ-ONLY  (2026-06-16, v320 prep)

Goal: prove (or disprove) the hypothesis that the 5 stale regime variants
   - direction_predictor_5min_bull_trend       (last promoted 2026-04-21)
   - direction_predictor_5min_range_bound      (last promoted 2026-04-21)
   - direction_predictor_15min_bull_trend      (last promoted 2026-04-26)
   - direction_predictor_1hour_bull_trend      (last promoted 2026-04-26)
   - direction_predictor_1hour_range_bound     (last promoted 2026-04-26)
stayed pinned to April because the v19.34.312 P0 class-collapse promotion
gate (or v321 PBO gate) REJECTED the candidates trained on June 10-11
(not because they were excluded from the training run).

Data sources (all read-only):
- `timeseries_model_archive`   ← every gate rejection lands here with
                                  `rejected_reason ∈ {class_collapse, pbo_gate}`
                                  and the candidate's `version` + recall metrics.
- `training_runs_archive`      ← per-run trophy snapshot containing
                                  `models_trained[]` and `models_failed[]`.
- `timeseries_models`          ← current promoted version (April baseline).

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_regime_promotion_history.py

Pure read-only. No writes. No service touch.
"""
import os
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

STALE_NAMES = [
    "direction_predictor_5min_bull_trend",
    "direction_predictor_5min_range_bound",
    "direction_predictor_15min_bull_trend",
    "direction_predictor_1hour_bull_trend",
    "direction_predictor_1hour_range_bound",
]

# Healthy June-promoted siblings — used as a control group so we can prove
# the same training run DID promote some regime variants successfully.
CONTROL_NAMES = [
    "direction_predictor_1min_bull_trend",
    "direction_predictor_5min_bear_trend",
    "direction_predictor_15min_bear_trend",
    "direction_predictor_1hour_bear_trend",
]


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _ts(doc, keys=("saved_at", "rejected_at", "archived_at",
                   "updated_at", "promoted_at", "created_at", "trained_at",
                   "started_at", "completed_at")):
    for k in keys:
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


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "?"


def _fmt_num(v, prec=3):
    try:
        return f"{float(v):.{prec}f}"
    except (TypeError, ValueError):
        return "?"


def dump_archive_rows(col, name, since=None):
    q = {"name": name}
    if since:
        # Try both saved_at and rejected_at; OR-condition.
        q = {"name": name, "$or": [
            {"saved_at": {"$gte": since}},
            {"rejected_at": {"$gte": since}},
            {"updated_at": {"$gte": since}},
        ]}
    rows = list(col.find(q, {"_id": 0}).limit(100))
    rows.sort(key=lambda r: _ts(r) or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def dump_run_history(arch_col, names, since=None):
    """Return list of (run_started_at, status_per_name) for recent runs."""
    runs = list(arch_col.find({}, {
        "_id": 1, "started_at": 1, "completed_at": 1,
        "models_trained": 1, "models_failed": 1,
        "models_trained_count": 1, "models_failed_count": 1,
    }))
    runs.sort(key=lambda r: _ts(r) or datetime.min.replace(tzinfo=timezone.utc),
              reverse=True)
    out = []
    for run in runs[:15]:  # cap at last 15 runs
        run_dt = _ts(run)
        trained = run.get("models_trained") or []
        failed = run.get("models_failed") or []
        trained_idx = {(m.get("name") or m.get("model")): m for m in trained
                       if isinstance(m, dict)}
        failed_idx = {(m.get("name") or m.get("model")): m for m in failed
                      if isinstance(m, dict)}
        per_name = {}
        for n in names:
            if n in trained_idx:
                per_name[n] = ("TRAINED",
                               trained_idx[n].get("accuracy"),
                               None)
            elif n in failed_idx:
                per_name[n] = ("FAILED",
                               failed_idx[n].get("accuracy"),
                               failed_idx[n].get("reason"))
            else:
                per_name[n] = ("not in lists", None, None)
        out.append((run, run_dt, per_name))
    return out


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    print(f"DB: {DB_NAME}")
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]

    # Surface what collections we have, so missing data is obvious upfront.
    have = set(db.list_collection_names())
    for c in ("timeseries_models", "timeseries_model_archive",
              "training_runs_archive"):
        print(f"  collection {c:>32} : "
              f"{'present' if c in have else 'MISSING'} "
              f"({db[c].estimated_document_count() if c in have else 0} docs)")

    # All names we want to investigate.
    all_names = STALE_NAMES + CONTROL_NAMES
    # Cutoff: only look at archive/run rows newer than the April baseline.
    since = datetime(2026, 5, 1, tzinfo=timezone.utc)

    # ----- 1. timeseries_model_archive: per-name gate rejection trace ----
    hr("1. timeseries_model_archive — per-model rejection trace (since May 1)")
    if "timeseries_model_archive" not in have:
        print("  collection missing — cannot prove rejection hypothesis from this lane.")
    else:
        arch = db["timeseries_model_archive"]
        for label, names in (("STALE (5 — the question)", STALE_NAMES),
                             ("CONTROL (June-promoted siblings)", CONTROL_NAMES)):
            print(f"\n  -- {label} --")
            for n in names:
                rows = dump_archive_rows(arch, n, since=since)
                if not rows:
                    print(f"     {n:>42}  →  no archive entries since May 1")
                    continue
                print(f"     {n}")
                for r in rows:
                    ver = r.get("version") or "?"
                    ts = _fmt(_ts(r))
                    rej = r.get("rejected_reason") or "(none — promoted/archived as old)"
                    ru = (r.get("rejected_recall_up")
                          or (r.get("metrics") or {}).get("recall_up"))
                    rd = (r.get("rejected_recall_down")
                          or (r.get("metrics") or {}).get("recall_down"))
                    acc = ((r.get("metrics") or {}).get("accuracy")
                           or r.get("accuracy"))
                    pbo = r.get("pbo_gate")
                    pbo_str = ""
                    if isinstance(pbo, dict):
                        pbo_str = f"  pbo={pbo.get('verdict','?')}:{pbo.get('reason','')[:50]}"
                    print(f"        v{ver}  {ts}  reason={rej}  "
                          f"acc={_fmt_num(acc)}  r_up={_fmt_num(ru,2)} "
                          f"r_dn={_fmt_num(rd,2)}{pbo_str}")

    # ----- 2. training_runs_archive: per-run participation -----------
    hr("2. training_runs_archive — last 15 runs (per-name participation)")
    if "training_runs_archive" not in have:
        print("  collection missing — cannot confirm run inclusion from this lane.")
    else:
        runs = dump_run_history(db["training_runs_archive"], all_names, since=since)
        if not runs:
            print("  no archived runs found.")
        else:
            header_names = [n.replace("direction_predictor_", "") for n in all_names]
            print(f"\n  Tracking {len(all_names)} names ({len(STALE_NAMES)} stale + "
                  f"{len(CONTROL_NAMES)} control):")
            for i, n in enumerate(header_names):
                kind = "STALE" if i < len(STALE_NAMES) else "ctrl"
                print(f"    [{i+1}] {kind}  {n}")
            print()
            print(f"  {'run_started':>17}  {'trained':>4}/{'failed':>4}  per-name verdict")
            for run, run_dt, per_name in runs:
                ts = _fmt(run_dt)
                tc = run.get("models_trained_count")
                fc = run.get("models_failed_count")
                tc_str = f"{tc:>4}" if tc is not None else "   ?"
                fc_str = f"{fc:>4}" if fc is not None else "   ?"
                verdict_tokens = []
                for i, n in enumerate(all_names):
                    status, acc, reason = per_name[n]
                    if status == "TRAINED":
                        tok = f"[{i+1}]T"
                    elif status == "FAILED":
                        tok = f"[{i+1}]F"
                    else:
                        tok = f"[{i+1}]-"
                    verdict_tokens.append(tok)
                print(f"  {ts:>17}  {tc_str}/{fc_str}  " + " ".join(verdict_tokens))
                # On FAILED, print the reason inline below
                for i, n in enumerate(all_names):
                    status, acc, reason = per_name[n]
                    if status == "FAILED":
                        print(f"      ↳ FAILED [{i+1}] {n}: {reason}")

    # ----- 3. Verdict synthesis ----------------------------------------
    hr("3. VERDICT")
    if "timeseries_model_archive" in have:
        arch = db["timeseries_model_archive"]
        rejected_stale = []
        for n in STALE_NAMES:
            rows = [r for r in dump_archive_rows(arch, n, since=since)
                    if r.get("rejected_reason") in ("class_collapse", "pbo_gate")]
            if rows:
                rejected_stale.append((n, rows[-1]))
        confirmed = len(rejected_stale)
        print(f"  stale models with a gate-rejection entry since May 1: "
              f"{confirmed} / {len(STALE_NAMES)}")
        if confirmed == len(STALE_NAMES):
            print("  ✅ HYPOTHESIS CONFIRMED: all 5 stale models were trained "
                  "in a more recent run but their candidate was REJECTED by "
                  "the v19.34.312 P0 collapse gate (or v321 PBO gate). The "
                  "April promotion stayed active because no replacement passed.")
        elif confirmed == 0:
            print("  ❌ HYPOTHESIS UNCONFIRMED: no recent rejection entries for "
                  "any of the 5 stale names. Most likely they were SKIPPED "
                  "entirely by recent training runs (different cause; check "
                  "the run-history table above to see who was in the trained "
                  "list and who wasn't).")
        else:
            print(f"  ⚠ PARTIAL: {confirmed}/5 confirmed rejections; "
                  f"{len(STALE_NAMES) - confirmed} stale name(s) have no recent "
                  "archive entry → those were probably skipped. Mixed cause.")
        for n, r in rejected_stale:
            print(f"     - {n}: v{r.get('version','?')} rejected on "
                  f"{_fmt(_ts(r))} reason={r.get('rejected_reason')}  "
                  f"r_up={_fmt_num(r.get('rejected_recall_up'),2)} "
                  f"r_dn={_fmt_num(r.get('rejected_recall_down'),2)}")
    print("\n  Next step: send this output back to the agent. If CONFIRMED, "
          "we still retrain (gate auto-rejects again unless the underlying "
          "target / sample window is also fixed — likely a P-TARGET task on "
          "slow-TF bull/range cells). If UNCONFIRMED, we figure out why they "
          "were skipped and patch the phase filter.")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
