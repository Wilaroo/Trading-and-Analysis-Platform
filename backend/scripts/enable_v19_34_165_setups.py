#!/usr/bin/env python3
"""v19.34.165 — Enable 5 momentum-playbook setups in bot_state.

v19.34.164 trade-drops persistence revealed 446 alerts/hour being killed
at the `setup_disabled` gate for 5 setup types the scanner emits but
the bot's `_enabled_setups` list never knew about:

    rs_leader_break     (159/hr)  IBD/CAN SLIM RS leader breakout
    power_trend_stack   (136/hr)  Minervini Power-Play continuation
    pocket_pivot        ( 70/hr)  Kacher pocket pivot
    stage_2_breakout    ( 56/hr)  Weinstein Stage-2 base breakout
    three_week_tight    ( 25/hr)  Minervini 3-week tight

This script appends them to the LIVE `bot_state.enabled_setups` doc so
the change takes effect WITHOUT a backend restart. The code-level
constructor list in `trading_bot_service.py` (lines ~970) has been
patched too so the new entries survive any bot_state wipe.

Idempotent — safe to run multiple times. Prints before/after diff.

Usage:
    cd ~/Trading-and-Analysis-Platform && source .venv/bin/activate
    DB_NAME=tradecommand python backend/scripts/enable_v19_34_165_setups.py
    DB_NAME=tradecommand python backend/scripts/enable_v19_34_165_setups.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient


NEW_SETUPS = [
    "rs_leader_break",
    "power_trend_stack",
    "pocket_pivot",
    "stage_2_breakout",
    "three_week_tight",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Enable v165 momentum setups")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show diff but don't write")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    # Find the bot_state doc that actually carries enabled_setups
    # (there may be other bot_state-like docs for the share-drift loop
    # etc. — we filter on the field existence so we don't clobber them).
    doc = db.bot_state.find_one({"enabled_setups": {"$exists": True}})
    if not doc:
        print(f"❌ No bot_state doc with `enabled_setups` found in `{db_name}`.")
        print("   Either the bot hasn't initialized yet, or the schema "
              "changed. Aborting (nothing to update).")
        return 1

    current = list(doc.get("enabled_setups") or [])
    missing = [s for s in NEW_SETUPS if s not in current]
    already_in = [s for s in NEW_SETUPS if s in current]

    print("=== bot_state.enabled_setups update — v19.34.165 ===")
    print(f"DB={db_name}  doc _id={doc.get('_id')}")
    print(f"Current count: {len(current)} setups")
    if already_in:
        print(f"\nAlready enabled ({len(already_in)}): {already_in}")
    if not missing:
        print("\n✅ Nothing to do — all 5 setups already in enabled_setups.")
        return 0
    print(f"\nWill APPEND ({len(missing)}): {missing}")

    if args.dry_run:
        print("\n--dry-run set; not writing.")
        return 0

    new_list = current + missing
    res = db.bot_state.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "enabled_setups": new_list,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "v19_34_165_setups_added": missing,
                "v19_34_165_added_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )
    print(f"\n✅ Updated {res.modified_count} doc. New count: {len(new_list)}")

    # Verify
    after = db.bot_state.find_one({"_id": doc["_id"]}, {"enabled_setups": 1})
    after_list = list(after.get("enabled_setups") or [])
    confirmed = [s for s in NEW_SETUPS if s in after_list]
    if len(confirmed) == 5:
        print("✅ Verification: all 5 setups now present in DB.")
    else:
        print(f"⚠️  Verification: only {len(confirmed)}/5 confirmed: {confirmed}")
        return 2

    print("\nNext steps:")
    print("  1. The bot reads enabled_setups on startup AND honors live DB")
    print("     changes via the periodic bot_state sync loop. Allow up to")
    print("     30s for the in-memory list to refresh.")
    print("  2. Watch trade_drops shrink:")
    print(f"       DB_NAME={db_name} python /tmp/drop_gates.py")
    print("  3. Watch new trades appear:")
    print(f"       DB_NAME={db_name} mongosh ... or use a pymongo find().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
