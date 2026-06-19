#!/usr/bin/env python3
"""
diag_v395_residual_audit.py  —  READ-ONLY closeout diag for the 3 remaining audit items

  1. SMB stamp rate     — how often alerts carry a real 5-var SMB score / grade
                          vs the "B"/25 default the Setup pillar falls back to.
  2. Financial coverage — how often symbol_fundamentals_cache actually has the
                          IB metrics the v389 financial sub-score reads
                          (roe_pct / net_margin_pct / eps_change_pct / debt_to_equity).
  3. Levels S/R         — distribution of the persisted Technical 'levels' sub-score;
                          flags the share sitting on tell-tale no-S/R defaults.

NO WRITES. Reads Mongo only. Run from repo root:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v395_residual_audit.py
"""
import os
import sys
from collections import Counter

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
FIN_FIELDS = ["roe_pct", "net_margin_pct", "eps_change_pct", "debt_to_equity"]


def pct(a, b):
    return f"{100.0*a/b:.1f}%" if b else "n/a"


def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    print("=" * 66)
    print("RESIDUAL AUDIT CLOSEOUT  (v395, READ-ONLY)")
    print("=" * 66)
    print(f"DB: {DB_NAME}\n")

    # ---- 1. SMB stamp rate -------------------------------------------------
    print("1) SMB STAMP RATE  (Setup pillar default = grade 'B' / 5-var 25)")
    la = db["live_alerts"]
    n = 0
    smb_real = 0          # smb_score_total > 0
    grade_present = 0
    grades = Counter()
    used_grade = Counter()   # what the pillar actually used (breakdown raw)
    for d in la.find({}, {"_id": 0, "smb_score_total": 1, "trade_grade": 1,
                          "tqs_breakdown.setup.raw_values.smb_grade": 1}).limit(50000):
        n += 1
        sst = d.get("smb_score_total")
        if sst is not None and float(sst) > 0:
            smb_real += 1
        g = d.get("trade_grade")
        if g:
            grade_present += 1
            grades[str(g)] += 1
        try:
            ug = d["tqs_breakdown"]["setup"]["raw_values"]["smb_grade"]
            used_grade[str(ug)] += 1
        except (KeyError, TypeError):
            pass
    print(f"   alerts: {n}")
    print(f"   real 5-var smb_score_total>0 : {smb_real}  ({pct(smb_real, n)})")
    print(f"   trade_grade present          : {grade_present}  ({pct(grade_present, n)})")
    print(f"   trade_grade distribution     : {dict(grades.most_common())}")
    print(f"   pillar-used smb_grade dist   : {dict(used_grade.most_common())}")
    blind = n - smb_real
    print(f"   => SMB blind (no real 5-var) : {pct(blind, n)}  "
          f"[{'RED' if blind/n>=0.5 else 'AMBER' if n and blind/n>=0.2 else 'GREEN'}]" if n else "")

    # ---- 2. Financial coverage (symbol_fundamentals_cache) -----------------
    print("\n2) FINANCIAL COVERAGE  (symbol_fundamentals_cache — feeds v389 sub-score)")
    fc = db["symbol_fundamentals_cache"]
    total = fc.count_documents({})
    print(f"   cached symbols: {total}")
    per = {}
    for f in FIN_FIELDS:
        per[f] = fc.count_documents({f: {"$exists": True, "$ne": None}})
        print(f"   {f:<16}: {per[f]}  ({pct(per[f], total)})")
    any1 = fc.count_documents({"$or": [{f: {"$exists": True, "$ne": None}} for f in FIN_FIELDS]})
    print(f"   >=1 metric present: {any1}  ({pct(any1, total)})")
    # alert-symbol coverage
    syms = la.distinct("symbol")
    cov = 0
    for s in syms:
        if fc.count_documents({"symbol": s, "$or": [{f: {"$exists": True, "$ne": None}} for f in FIN_FIELDS]}, limit=1):
            cov += 1
    print(f"   alert symbols with >=1 metric: {cov}/{len(syms)}  ({pct(cov, len(syms))})  "
          f"[{'RED' if syms and cov/len(syms)<0.5 else 'AMBER' if syms and cov/len(syms)<0.8 else 'GREEN'}]" if syms else "")

    # ---- 3. Levels S/R availability ----------------------------------------
    print("\n3) LEVELS SUB-SCORE DISTRIBUTION  (no-S/R defaults cluster at 35/50/65)")
    hist = Counter()
    ln = 0
    for d in la.find({"tqs_breakdown.technical.components.levels": {"$exists": True}},
                     {"_id": 0, "tqs_breakdown.technical.components.levels": 1}).limit(50000):
        try:
            v = round(float(d["tqs_breakdown"]["technical"]["components"]["levels"]))
            hist[v] += 1
            ln += 1
        except (KeyError, TypeError, ValueError):
            pass
    if ln:
        print(f"   alerts with levels score: {ln}")
        for v, c in hist.most_common(10):
            tag = "  <- likely no-S/R default" if v in (35, 50, 65) else ""
            print(f"     levels={v:<4} n={c}  ({pct(c, ln)}){tag}")
        defaults = sum(hist.get(v, 0) for v in (35, 50, 65))
        print(f"   => on a default band (35/50/65): {pct(defaults, ln)}  "
              f"[{'RED' if defaults/ln>=0.5 else 'AMBER' if defaults/ln>=0.2 else 'GREEN'}]")
        print("   (indicative — S/R distances aren't persisted; this is the score histogram.)")
    else:
        print("   no levels data found.")

    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    main()
