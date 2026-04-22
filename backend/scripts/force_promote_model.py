"""
Force-promote a specific archived model version to active.

Why: the Model Protection gate is only fixed in code (pull + restart makes new
retrains use the new gate), but models already archived under the old gate need
a manual promotion to become active. This script does exactly that — no shell
dependency.

Usage (on Spark, from repo root):
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
      backend/scripts/force_promote_model.py \
      --name direction_predictor_5min \
      --version v20260422_162431

Idempotent. Prints BEFORE/AFTER state.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except Exception:
    pass

import pymongo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="model name (e.g. direction_predictor_5min)")
    ap.add_argument("--version", required=True, help="archived version to promote (e.g. v20260422_162431)")
    ap.add_argument("--archive", default="timeseries_model_archive")
    ap.add_argument("--active", default="timeseries_models")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERR: MONGO_URL not set")
        sys.exit(2)

    client = pymongo.MongoClient(mongo_url)
    db = client[db_name]

    print(f"==> Connected to {db_name}")

    cur = db[args.active].find_one({"name": args.name}, {"_id": 0, "version": 1, "metrics": 1})
    if cur:
        m = cur.get("metrics") or {}
        print(f"==> BEFORE · active {args.name}: version={cur.get('version')}"
              f" accuracy={m.get('accuracy')} recall_up={m.get('recall_up')}"
              f" recall_down={m.get('recall_down')}")
    else:
        print(f"==> BEFORE · no active {args.name} yet")

    archived = db[args.archive].find_one(
        {"name": args.name, "version": args.version},
        {"_id": 0},
    )
    if not archived:
        print(f"ERR: archived model {args.name}@{args.version} not found in {args.archive}")
        sys.exit(3)
    m = archived.get("metrics") or {}
    print(f"==> ARCHIVED candidate {args.name}@{args.version}: accuracy={m.get('accuracy')}"
          f" recall_up={m.get('recall_up')} recall_down={m.get('recall_down')}"
          f" f1_up={m.get('f1_up')} f1_down={m.get('f1_down')}")

    archived["updated_at"] = datetime.now(timezone.utc)
    archived["promoted_at"] = datetime.now(timezone.utc)

    result = db[args.active].update_one(
        {"name": args.name},
        {"$set": archived},
        upsert=True,
    )
    print(f"==> update_one matched={result.matched_count} modified={result.modified_count}"
          f" upserted_id={result.upserted_id}")

    after = db[args.active].find_one({"name": args.name}, {"_id": 0, "version": 1, "metrics": 1})
    m = (after or {}).get("metrics") or {}
    print(f"==> AFTER · active {args.name}: version={after.get('version')}"
          f" accuracy={m.get('accuracy')} recall_up={m.get('recall_up')}"
          f" recall_down={m.get('recall_down')}")

    if after and after.get("version") == args.version:
        print(f"==> SUCCESS · {args.name} is now {args.version}. "
              f"Restart backend to reload into memory.")
    else:
        print(f"ERR: promotion did not take effect")
        sys.exit(4)


if __name__ == "__main__":
    main()
