#!/usr/bin/env python3
"""
diag_list_models.py  —  audit helper  (2026-06-10)   READ-ONLY

Locates where trained models actually live: lists every *model* collection,
its count, the distinct name-like field values, and one sample doc's keys.
Helps find vol_predictor / gap_fill models that diag_vol_gap_models.py missed.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_list_models.py
"""
import os
import sys
from collections import Counter

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
NAME_FIELDS = ("model_name", "name", "setup_type", "model_key", "key", "model_id")


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]

    colls = [c for c in db.list_collection_names()
             if "model" in c.lower() or "gbm" in c.lower() or "train" in c.lower()]
    hr(f"MODEL-ish COLLECTIONS ({len(colls)})")
    for c in sorted(colls):
        try:
            n = db[c].estimated_document_count()
        except Exception:
            n = "?"
        print(f"  {c:<40} {n}")

    for c in sorted(colls):
        try:
            cnt = db[c].count_documents({})
        except Exception:
            continue
        if cnt == 0 or cnt > 100000:
            continue
        sample = db[c].find_one({}, {"_id": 0})
        if not sample:
            continue
        name_field = next((f for f in NAME_FIELDS if f in sample), None)
        hr(f"{c}  (docs={cnt}, name_field={name_field})")
        print(f"  sample keys: {sorted(sample.keys())[:25]}")
        if name_field:
            names = Counter()
            for d in db[c].find({}, {"_id": 0, name_field: 1}).limit(2000):
                names[str(d.get(name_field))] += 1
            # show vol/gap matches first, then a few others
            vg = {k: v for k, v in names.items() if "vol" in k.lower() or "gap" in k.lower()}
            if vg:
                print("  >>> VOL/GAP matches:")
                for k, v in sorted(vg.items()):
                    print(f"        {k}: {v}")
            print(f"  distinct {name_field} (top 20):")
            for k, v in names.most_common(20):
                print(f"        {k}: {v}")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
