"""
Create / verify the compound index `{bar_size: 1, date: -1}` on the
`ib_historical_data` collection.

WHY
---
`/api/ib-collector/rebuild-adv-from-ib` (and downstream scanner queries)
do an aggregation pipeline keyed on `bar_size` + `date`. Without this
compound index, MongoDB falls back to a collection scan over ~13.5M
documents and spills to disk — typical rebuild duration: 5+ minutes.
With the index in place: seconds.

USAGE
-----
On DGX:
    PYTHONPATH=backend /home/spark-1a60/venv/bin/python \\
        backend/scripts/create_ib_historical_indexes.py

or any Python that has access to MONGO_URL + DB_NAME.

Idempotent. Safe to re-run. Uses background:True so it doesn't block
writes during creation. Prints index name + estimated wall-time.
"""

from __future__ import annotations

import os
import sys
import time

try:
    from pymongo import MongoClient
except ImportError:
    print("pymongo not installed in this Python environment; aborting.")
    sys.exit(1)


_INDEXES = [
    # name -> (keys, options)
    (
        "bar_size_1_date_-1",
        ([("bar_size", 1), ("date", -1)], {"background": True}),
    ),
    # symbol+bar_size+date keeps existing single-symbol queries fast.
    # Already exists in many envs; create_index is idempotent so the
    # call is a cheap no-op if it's there.
    (
        "symbol_1_bar_size_1_date_-1",
        (
            [("symbol", 1), ("bar_size", 1), ("date", -1)],
            {"background": True},
        ),
    ),
]


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME must both be set in env. Aborting.")
        return 2

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5_000)
    db = client[db_name]
    col = db["ib_historical_data"]

    print(f"Connecting to {db_name}.ib_historical_data ...")
    existing = {idx["name"] for idx in col.list_indexes()}
    print(f"Existing indexes: {sorted(existing)}\n")

    for name, (keys, opts) in _INDEXES:
        if name in existing:
            print(f"  SKIP (already present): {name}")
            continue
        t0 = time.time()
        print(f"  CREATE: {name} keys={keys} opts={opts}")
        try:
            new_name = col.create_index(keys, name=name, **opts)
            elapsed = time.time() - t0
            print(f"    -> created `{new_name}` in {elapsed:.1f}s")
        except Exception as exc:
            print(f"    !! create_index failed: {exc}")
            return 3

    print("\nDone. Re-running this script is safe — it's idempotent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
