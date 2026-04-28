"""
Backfill the `sector` + `sector_name` fields on every doc in
`symbol_adv_cache`. One-time script — re-running is safe (idempotent).

Usage on Spark:
    cd ~/Trading-and-Analysis-Platform
    PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
        backend/scripts/backfill_sector_tags.py

Or hit the equivalent admin endpoint:
    POST /api/scanner/backfill-sector-tags

Either path uses the static map in `services.sector_tag_service`. Any
symbol outside the map stays untagged — the SectorRegimeClassifier
returns UNKNOWN for those (alerts still fire — soft gate).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymongo import MongoClient

from services.sector_tag_service import (  # noqa: E402
    get_sector_tag_service, SECTOR_ETFS,
)


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    svc = get_sector_tag_service(db=db)
    print(f"Static sector map covers {len(svc.all_tags()):,} symbols "
          f"across {len(SECTOR_ETFS)} sectors.")

    result = asyncio.run(svc.backfill_symbol_adv_cache(db=db))
    print()
    print("=" * 50)
    print("Sector backfill complete:")
    print(f"  Total docs scanned:        {result['total']:,}")
    print(f"  Newly tagged:              {result['tagged']:,}")
    print(f"  Already tagged (skipped):  {result['skipped']:,}")
    print(f"  Untaggable (not in map):   {result['untaggable']:,}")
    print("=" * 50)
    if result["total"] > 0:
        coverage = (result["tagged"] + result["skipped"]) / result["total"] * 100
        print(f"Final coverage: {coverage:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
