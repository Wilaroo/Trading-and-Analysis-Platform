#!/usr/bin/env python3
"""
diag_v392c_verify.py  —  READ-ONLY live re-score verification for v393 + v394

The v392 coverage diag reads PERSISTED breakdowns on OLD alerts (scored before
the patches) so it won't move on history. This script instead RE-SCORES a sample
of recent alert symbols through the CURRENT (patched) Setup + Context pillars and
prints the new Pattern / Tape / Sector sub-scores — proving v393/v394 are live.

NO WRITES. No IB needed (Setup + Context read Mongo only). Run from repo root:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v392c_verify.py
"""
import asyncio
import os
import sys

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")


async def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    from services.tqs.setup_quality import get_setup_quality_service
    from services.tqs.context_quality import get_context_quality_service
    setup = get_setup_quality_service()
    ctx = get_context_quality_service()
    ctx._db = db  # wire daily-bar + sector sources

    rows = list(db["live_alerts"].find(
        {"tqs_breakdown": {"$exists": True}},
        {"_id": 0, "symbol": 1, "setup_type": 1, "direction": 1, "tape_score": 1},
    ).sort("created_at", -1).limit(20))
    if not rows:
        print("No alerts found."); return

    print("=" * 92)
    print("LIVE RE-SCORE VERIFY (v392c) — Setup.Pattern/Tape + Context.Sector via current code")
    print("=" * 92)
    print(f"{'SYMBOL':<8}{'SETUP_TYPE':<24}{'PATTERN':<34}{'TAPE':<14}{'SECTOR'}")
    print("-" * 92)
    pat_nondefault = sect_real = tape_neutral = 0
    for r in rows:
        sym = r.get("symbol", "?")
        st = r.get("setup_type", "")
        dr = r.get("direction", "long")
        ts = r.get("tape_score", 0) or 0
        s = await setup.calculate_score(setup_type=st, symbol=sym, tape_score=ts)
        c = await ctx.calculate_score(symbol=sym, direction=dr, setup_type=st)
        sd, cd = s.to_dict(), c.to_dict()
        pat = sd["components"]["pattern"]; pat_rd = sd["display"]["pattern"]["reading"]
        tap = sd["components"]["tape"]; tap_v = sd["display"]["tape"]["verdict"]
        sec = cd["display"]["sector"]["reading"]
        if pat != 50:
            pat_nondefault += 1
        if "unavailable" not in sec:
            sect_real += 1
        if tap == 50.0:
            tape_neutral += 1
        print(f"{sym:<8}{st:<24}{str(round(pat))+' '+pat_rd:<34}{str(round(tap))+' '+tap_v:<14}{sec}")
    n = len(rows)
    print("-" * 92)
    print(f"Pattern non-flat-50: {pat_nondefault}/{n}   Sector resolved: {sect_real}/{n}   "
          f"Tape absent→neutral-50: {tape_neutral}/{n}")
    print("(Sector 'unavailable' = symbol has no symbol_adv_cache tag — honest No-data, expected for ~39%.)")
    print("Read-only — nothing was modified.")


if __name__ == "__main__":
    asyncio.run(main())
