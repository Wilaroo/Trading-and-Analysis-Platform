#!/usr/bin/env python3
"""
apply_v19_34_320b_quarantine.py
================================
One-time (and re-runnable) quarantine sweep for ib_historical_data.

WHY
---
v320a protects the COMPUTE path (rebuild_adv_from_ib_data) by filtering
pre-listing pollution in Python before averaging. But the polluted bars
still PHYSICALLY live in ib_historical_data, so any future code path
that reads them directly (e.g. raw breakout-level lookups, daily-bar
gap consumers, future ML features) would still see stale rows.

This sweep moves those rows to a NEW collection,
`ib_historical_data_quarantine`, fully preserving them with metadata so
the operation is reversible. It does NOT delete data — only relocates.

DETECTION
---------
Uses the same canonical helper that v320a ships with:
  IBHistoricalCollector._filter_pre_listing_pollution(...)
…so the sweep and the compute path can never drift.

For each symbol:
  • pull ALL daily bars sorted newest→oldest
  • call _filter_pre_listing_pollution
  • if meta["filter_applied"] is True:
      - older cohort (everything past meta["window_start_iso"]) is
        moved to ib_historical_data_quarantine
      - new docs get: _quarantined_at, _quarantined_reason,
        _quarantined_by_patch, _original_id (preserves the source _id)

USAGE
-----
  --check          : dry-run, report planned moves, NO writes
  (default)        : execute moves + rebuild ADV cache
  --no-rebuild     : skip the ADV rebuild after sweep
  --restore SYM    : reverse the quarantine for a single symbol
  --restore-all    : move EVERY quarantined row back (full undo)
  --symbol SYM     : restrict the sweep to one symbol (useful for re-runs)

NO destructive ops happen without --check first showing the plan.
A backup of the affected raw rows is also written to
/tmp/v320b_quarantine_<utc>.jsonl as a flat-file safety net.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median as _median

PATCH_TAG = "v19_34_320b"
REPO_DEFAULT = Path.home() / "Trading-and-Analysis-Platform"


def _load_env(repo: Path):
    for cand in (repo / "backend" / ".env",):
        if cand.is_file():
            for ln in cand.read_text().splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(),
                                          v.strip().strip('"').strip("'"))


def _fmt_dt(d):
    if d is None: return "—"
    if hasattr(d, "isoformat"):
        try: return d.isoformat(timespec="seconds")
        except Exception: return str(d)
    return str(d)


def _trigger_rebuild():
    """Call /api/ib-collector/rebuild-adv-from-ib via curl + frontend/.env."""
    repo = Path.cwd()
    env_path = repo / "frontend" / ".env"
    if not env_path.is_file():
        print("  [skip] frontend/.env not found, can't auto-rebuild")
        return False
    api_url = None
    for ln in env_path.read_text().splitlines():
        if ln.startswith("REACT_APP_BACKEND_URL"):
            api_url = ln.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not api_url:
        print("  [skip] REACT_APP_BACKEND_URL not found")
        return False
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             f"{api_url}/api/ib-collector/rebuild-adv-from-ib",
             "-H", "Content-Type: application/json"],
            capture_output=True, text=True, timeout=300,
        )
        try:
            j = json.loads(r.stdout)
            print(json.dumps(j, indent=2)[:600])
            return j.get("success", False)
        except Exception:
            print(r.stdout[:600])
            return False
    except Exception as e:
        print(f"  [warn] rebuild trigger failed: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--symbol")
    ap.add_argument("--restore")
    ap.add_argument("--restore-all", action="store_true")
    ap.add_argument("--gap-days", type=int, default=30)
    ap.add_argument("--vol-ratio", type=float, default=50.0)
    ap.add_argument("--price-ratio", type=float, default=3.0,
                    help="v320b refinement — min price discontinuity for TRUE_RECYCLE class")
    ap.add_argument("--cluster-threshold", type=int, default=5,
                    help="v320b refinement — window_start shared by N+ symbols → LIKELY_INGEST (excluded)")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    _load_env(repo)
    sys.path.insert(0, str(repo / "backend"))

    try:
        from pymongo import MongoClient
    except ImportError:
        print("[ABORT] pymongo missing")
        return 2

    try:
        from services.ib_historical_collector import IBHistoricalCollector  # noqa: F401
    except Exception as e:
        print(f"[ABORT] cannot import IBHistoricalCollector: {e}")
        print("        Ensure v320a + hotfix2 are applied first.")
        return 2

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or "tradecommand"
    if not mongo_url:
        print("[ABORT] MONGO_URL not set")
        return 2

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    db = client[db_name]
    src_col = db["ib_historical_data"]
    q_col = db["ib_historical_data_quarantine"]

    print("═" * 72)
    print(f" apply_{PATCH_TAG} — quarantine sweep")
    print("═" * 72)
    print(f"  db           : {db_name}")
    print(f"  src          : ib_historical_data")
    print(f"  quarantine   : ib_historical_data_quarantine")
    print(f"  thresholds   : gap > {args.gap_days}d  &  vol_ratio >= {args.vol_ratio}×")
    print(f"  utc now      : {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print()

    # ── RESTORE PATHS ───────────────────────────────────────────────
    if args.restore_all:
        n = q_col.count_documents({})
        print(f"  [restore-all] {n} quarantined doc(s) staged for restore")
        if args.check:
            print("  --check: no writes")
            return 0
        if n == 0:
            print("  nothing to restore")
            return 0
        moved = 0
        for doc in list(q_col.find({})):
            doc_clean = {k: v for k, v in doc.items() if not k.startswith("_quarantined")}
            # restore original _id
            if "_original_id" in doc_clean:
                doc_clean["_id"] = doc_clean.pop("_original_id")
            try:
                src_col.insert_one(doc_clean)
                q_col.delete_one({"_id": doc["_id"]})
                moved += 1
            except Exception as e:
                print(f"  [warn] restore failed for {doc.get('symbol')}: {e}")
        print(f"  [ok] restored {moved}/{n} doc(s)")
        if not args.no_rebuild:
            print("\n─── trigger ADV rebuild ───")
            _trigger_rebuild()
        return 0

    if args.restore:
        sym = args.restore.upper()
        n = q_col.count_documents({"symbol": sym})
        print(f"  [restore {sym}] {n} quarantined doc(s) staged for restore")
        if args.check:
            return 0
        if n == 0:
            print("  nothing to restore")
            return 0
        moved = 0
        for doc in list(q_col.find({"symbol": sym})):
            doc_clean = {k: v for k, v in doc.items() if not k.startswith("_quarantined")}
            if "_original_id" in doc_clean:
                doc_clean["_id"] = doc_clean.pop("_original_id")
            try:
                src_col.insert_one(doc_clean)
                q_col.delete_one({"_id": doc["_id"]})
                moved += 1
            except Exception as e:
                print(f"  [warn] restore failed: {e}")
        print(f"  [ok] restored {moved}/{n} doc(s) for {sym}")
        if not args.no_rebuild:
            print("\n─── trigger ADV rebuild ───")
            _trigger_rebuild()
        return 0

    # ── SCAN PATH ───────────────────────────────────────────────────
    print("─── scan ───")
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = sorted(src_col.distinct("symbol", {"bar_size": "1 day"}))
    print(f"  scanning {len(symbols):,} symbol(s) with daily bars …")

    plans = []  # (sym, total, kept, removed, window_start)
    for sym in symbols:
        bars = list(src_col.find(
            {"symbol": sym, "bar_size": "1 day"},
            {"_id": 1, "date": 1, "volume": 1, "high": 1, "low": 1, "close": 1},
        ).sort("date", -1))
        if len(bars) < 3:
            continue
        dates = [b.get("date") for b in bars]
        vols = [b.get("volume") for b in bars]
        highs = [b.get("high") for b in bars]
        lows = [b.get("low") for b in bars]
        closes = [b.get("close") for b in bars]

        from services.ib_historical_collector import IBHistoricalCollector as IBC
        fd, fv, fh, fl, fc, meta = IBC._filter_pre_listing_pollution(
            dates, vols, highs, lows, closes,
            gap_threshold_days=args.gap_days,
            vol_ratio_threshold=args.vol_ratio,
        )
        if not meta["filter_applied"]:
            continue

        kept = len(fd)
        removed = len(bars) - kept
        # the polluted docs are bars[kept:] (older cohort)
        polluted_ids = [b["_id"] for b in bars[kept:]]
        # v320b refinement — compute price_ratio for classification
        newer_closes = [c for c in closes[:kept]        if c]
        older_closes = [c for c in closes[kept:len(bars)] if c]
        if newer_closes and older_closes:
            nm_c = _median(newer_closes)
            om_c = _median(older_closes)
            if min(nm_c, om_c) > 0:
                price_ratio = max(nm_c, om_c) / min(nm_c, om_c)
            else:
                price_ratio = float("inf")
        else:
            price_ratio = 0.0
        plans.append({
            "sym": sym, "total": len(bars),
            "kept": kept, "removed": removed,
            "window_start": meta["window_start_iso"],
            "window_start_day": (meta["window_start_iso"] or "")[:10],
            "price_ratio": price_ratio,
            "polluted_ids": polluted_ids,
            "polluted_docs": bars[kept:],   # for the backup file
        })

    if not plans:
        print("  [ok] no pollution detected. nothing to do.")
        return 0

    # v320b refinement — classify and FILTER plans
    #   TRUE_RECYCLE  : price_ratio >= --price-ratio AND not in cluster
    #   LIKELY_INGEST : window_start shared by >= --cluster-threshold symbols
    #   AMBIGUOUS     : everything else
    ws_counts = Counter(p["window_start_day"] for p in plans)
    ingest_dates = {d for d, n in ws_counts.items()
                    if n >= args.cluster_threshold and d}

    for p in plans:
        if p["window_start_day"] in ingest_dates:
            p["klass"] = "LIKELY_INGEST"
        elif p["price_ratio"] >= args.price_ratio:
            p["klass"] = "TRUE_RECYCLE"
        else:
            p["klass"] = "AMBIGUOUS"

    cls_count = Counter(p["klass"] for p in plans)
    cls_rows  = {k: sum(p["removed"] for p in plans if p["klass"] == k)
                 for k in cls_count}

    print()
    print(f"  [SCAN] {len(plans)} raw candidate(s). Classification:")
    print(f"   {'class':<18} {'symbols':>8} {'rows':>10}")
    for k in ("TRUE_RECYCLE", "LIKELY_INGEST", "AMBIGUOUS"):
        print(f"   {k:<18} {cls_count.get(k, 0):>8} {cls_rows.get(k, 0):>10,}")
    if ingest_dates:
        print(f"   ingest cluster dates excluded: {sorted(ingest_dates)}")

    # NEW — only TRUE_RECYCLE is acted on. Others are reported but skipped.
    actionable = [p for p in plans if p["klass"] == "TRUE_RECYCLE"]
    if not actionable:
        print()
        print("  [ok] no TRUE_RECYCLE plans (after price + cluster filters).")
        print("       LIKELY_INGEST entries reflect a separate ingest-pipeline issue.")
        print("       AMBIGUOUS entries may need manual review or lower --price-ratio.")
        return 0

    print()
    print(f"  ACTIONABLE — {len(actionable)} TRUE_RECYCLE symbol(s) to quarantine:")
    print(f"   {'sym':<8} {'total':>6} {'keep':>6} {'remove':>7} {'px_ratio':>9}   {'window_start':<22}")
    print(f"   {'-'*70}")
    actionable.sort(key=lambda p: -p["price_ratio"])
    total_to_remove = 0
    for p in actionable[:50]:
        pr = "inf" if p["price_ratio"] == float("inf") else f"{p['price_ratio']:.2f}"
        print(f"   {p['sym']:<8} {p['total']:>6} {p['kept']:>6} {p['removed']:>7} "
              f"{pr:>9}   {p['window_start'] or '—':<22}")
        total_to_remove += p["removed"]
    if len(actionable) > 50:
        # still need to sum the tail's removed for the total
        for p in actionable[50:]:
            total_to_remove += p["removed"]
        print(f"   ... ({len(actionable) - 50} more)")
    print(f"   {'-'*55}")
    print(f"   {'TOTAL':<8} {'':>6} {'':>6} {total_to_remove:>7} rows to quarantine")
    print()

    if args.check:
        print("  --check: no writes. re-run WITHOUT --check to execute.")
        return 0

    # ── EXECUTE ─────────────────────────────────────────────────────
    # v320b refinement — only quarantine TRUE_RECYCLE. LIKELY_INGEST + AMBIGUOUS
    # remain untouched. Use `actionable` (computed during scan).
    # 1. write a flat-file backup
    backup_path = Path("/tmp") / f"{PATCH_TAG}_quarantine_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.jsonl"
    n_backed = 0
    with backup_path.open("w") as fp:
        for p in actionable:
            for doc in p["polluted_docs"]:
                d = {**doc}
                if "_id" in d:
                    d["_id"] = str(d["_id"])
                if "date" in d and hasattr(d["date"], "isoformat"):
                    try: d["date"] = d["date"].isoformat()
                    except Exception: d["date"] = str(d["date"])
                fp.write(json.dumps(d, default=str) + "\n")
                n_backed += 1
    print(f"  [ok] flat-file backup → {backup_path}  ({n_backed} doc(s))")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted_total = 0
    deleted_total = 0
    for p in actionable:
        sym = p["sym"]
        # Insert into quarantine
        to_insert = []
        for doc in p["polluted_docs"]:
            d = {k: v for k, v in doc.items() if k != "_id"}
            d["_original_id"] = doc["_id"]
            d["_quarantined_at"] = now_iso
            d["_quarantined_reason"] = "pre_listing_pollution"
            d["_quarantined_by_patch"] = PATCH_TAG
            d["_quarantine_window_start"] = p["window_start"]
            d["_quarantine_price_ratio"] = p["price_ratio"]
            to_insert.append(d)
        if to_insert:
            try:
                res = q_col.insert_many(to_insert, ordered=False)
                inserted = len(res.inserted_ids)
                inserted_total += inserted
                # only delete after successful insert
                del_res = src_col.delete_many({"_id": {"$in": p["polluted_ids"]}})
                deleted = del_res.deleted_count
                deleted_total += deleted
                ok = (inserted == deleted == p["removed"])
                mark = "✓" if ok else "!"
                print(f"  [{mark}] {sym:<8}  inserted={inserted:<4} deleted={deleted:<4}"
                      f"  expected={p['removed']}")
            except Exception as e:
                print(f"  [ERR] {sym}: {e}  — left source bars in place")
                continue

    print()
    print(f"─── summary ───")
    print(f"  symbols actioned  : {len(actionable)}  (TRUE_RECYCLE only)")
    print(f"  symbols skipped   : {len(plans) - len(actionable)}  (LIKELY_INGEST + AMBIGUOUS)")
    print(f"  rows inserted     : {inserted_total}")
    print(f"  rows deleted      : {deleted_total}")
    print(f"  flat-file backup  : {backup_path}")

    if inserted_total != deleted_total:
        print(f"  [WARN] insert/delete counts diverged.")
        print(f"         The flat-file backup contains the full polluted set.")
        print(f"         Use --restore-all to reverse if needed.")
        return 6

    # ── TRIGGER ADV REBUILD ─────────────────────────────────────────
    if not args.no_rebuild:
        print()
        print("─── trigger ADV rebuild (so caches reflect cleaned data) ───")
        ok = _trigger_rebuild()
        if not ok:
            print("  [warn] rebuild call returned non-success. inspect manually.")

    print()
    print("═" * 72)
    print(f" {PATCH_TAG} complete.")
    print("═" * 72)
    print()
    print("Verify SPCX (expect pre_listing_filter_applied: False now that")
    print("source bars are clean):")
    print()
    print("  .venv/bin/python /tmp/diag_spcx_forensics.py")
    print()
    print("Undo a single symbol  : .venv/bin/python /tmp/apply_v19_34_320b_quarantine.py --restore SYMBOL")
    print("Undo the entire sweep : .venv/bin/python /tmp/apply_v19_34_320b_quarantine.py --restore-all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
