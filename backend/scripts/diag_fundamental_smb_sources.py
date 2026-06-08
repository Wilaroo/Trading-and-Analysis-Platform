#!/usr/bin/env python3
"""
#3 investigation (read-only) — FUNDAMENTAL data sourcing + SMB sub-pillar state.

Answers two questions the ITW audit raised:
  A. Why does Fundamental fall back to optimistic DEFAULTS (institutional 50%→80)?
     → Is Finnhub configured? Is the fundamentals cache actually populated with
       real short_interest / float / institutional, or mostly empty?
  B. Is the SMB sub-pillar discriminating, or pinned at the "uninformative→50"
     neutral band for most alerts?

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_fundamental_smb_sources.py
"""
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402


def _pct(n, d):
    return f"{(100.0*n/d):.0f}%" if d else "n/a"


def main():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    print("=== A. FUNDAMENTAL DATA SOURCES ===")
    print(f"  FINNHUB_API_KEY set: {bool(os.environ.get('FINNHUB_API_KEY'))}")

    fc = db.symbol_fundamentals_cache
    n = fc.count_documents({})
    print(f"\n  symbol_fundamentals_cache: {n} docs")
    if n:
        si = fc.count_documents({"short_interest_percent": {"$ne": None, "$exists": True}})
        fl = fc.count_documents({"float_shares": {"$ne": None, "$exists": True}})
        io = fc.count_documents({"institutional_ownership_percent": {"$ne": None, "$exists": True}})
        print(f"    with short_interest_percent:        {si}  ({_pct(si,n)})")
        print(f"    with float_shares:                  {fl}  ({_pct(fl,n)})")
        print(f"    with institutional_ownership_percent:{io}  ({_pct(io,n)})")
        srcs = Counter(d.get("source", "?") for d in fc.find({}, {"source": 1}))
        print(f"    source chain distribution: {dict(srcs.most_common(8))}")

    ic = db.institutional_ownership_cache
    ni = ic.count_documents({})
    print(f"\n  institutional_ownership_cache: {ni} docs")
    if ni:
        latest = list(ic.find({}, {"fetched_at": 1, "updated_at": 1}).sort([("_id", -1)]).limit(1))
        if latest:
            ts = latest[0].get("fetched_at") or latest[0].get("updated_at") or "?"
            print(f"    most-recent fetched_at: {ts}")

    print("\n  VERDICT(A): if Finnhub is unset AND the caches are sparse, the")
    print("  Fundamental pillar is running on DEFAULTS. Fix = set FINNHUB_API_KEY")
    print("  + run the institutional-ownership refresh, OR make absent data score")
    print("  neutral-50 instead of optimistic-80.")

    print("\n=== B. SMB SUB-PILLAR DISCRIMINATION ===")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    la = db.live_alerts
    rows = list(la.find(
        {"created_at": {"$gte": cutoff}},
        {"smb_grade": 1, "tqs_breakdown": 1}))
    print(f"  live_alerts (last 7d): {len(rows)}")
    grades = Counter()
    smb_sub = []
    for r in rows:
        grades[str(r.get("smb_grade") or "none")] += 1
        bd = r.get("tqs_breakdown") or {}
        setup = bd.get("setup") if isinstance(bd, dict) else None
        # setup breakdown may carry the smb sub-score under a few key names
        if isinstance(setup, dict):
            for k in ("smb", "smb_score"):
                if setup.get(k) is not None:
                    smb_sub.append(float(setup[k]))
                    break
    print(f"  smb_grade distribution: {dict(grades.most_common())}")
    if smb_sub:
        import statistics
        at50 = sum(1 for x in smb_sub if abs(x - 50) < 0.5)
        print(f"  SMB sub-score: n={len(smb_sub)} min={min(smb_sub):.0f} "
              f"median={statistics.median(smb_sub):.0f} max={max(smb_sub):.0f}")
        print(f"    pinned at exactly 50 (uninformative→neutral): {at50}  "
              f"({_pct(at50, len(smb_sub))})")
        print("  VERDICT(B): a high % pinned at 50 → SMB is NOT discriminating")
        print("  (decompressed to neutral). Fix = timeframe-aware checklist +")
        print("  stop the blanket 50-decompress so real SMB variation flows through.")
    else:
        print("  (no SMB sub-scores found in tqs_breakdown.setup — may be stored "
              "under a different key; tell me the key shape and I'll adjust.)")


if __name__ == "__main__":
    main()
