#!/usr/bin/env python3
"""
repair_v320c_may_june_backfill.py  —  v19.34.320c repair  (2026-06-16)

Enqueues IB historical-data requests for the 183 symbols with a
May→June 2026 daily-bar gap. All gaps are `1 day` bar_size; intraday
history was not collected pre-listing for these symbols (different
upstream issue, not this repair).

INVENTORY: embedded below (output of diag_may_june_gap_inventory.py
on 2026-06-16, SHA 6682e43d…). Re-derive with:
    .venv/bin/python backend/scripts/diag_may_june_gap_inventory.py

DESIGN:
  - Uses the canonical `HistoricalDataQueueService.create_request()`
    path so the live collector worker (client_id=16) picks the requests
    up automatically. No new IB client, no direct DB writes to
    `ib_historical_data`, no bypass of v320a pre-listing guard.
  - One IB request per (symbol, gap_end) — `duration = expected_bars + 7`
    days of padding so we always cover the gap_start edge.
  - All rows tagged `callback_id = "v320c_may_june_repair"` so a single
    flag lets us track / cancel / re-run the cohort cleanly.
  - `skip_if_pending=True` makes the run idempotent.

FLAGS:
  --check   Dry run. Prints the plan without inserting anything.
  --clear   Cancel any v320c-tagged pending/claimed rows (rollback).
  --apply   Actually enqueue.   (one of --check / --apply / --clear required)

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/repair_v320c_may_june_backfill.py --check
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/repair_v320c_may_june_backfill.py --apply

EXPECTED:
  • 183 requests enqueued (or some skipped as duplicates of already-pending).
  • 6,158 daily bars to fetch.
  • Pacing 58 req/10min → ETA ≈ 32m at default cadence; collector turbo
    cuts to ~6–10m.
"""
import argparse
import os
import sys
from datetime import datetime

CALLBACK_ID = "v320c_may_june_repair"
BAR_SIZE = "1 day"

# ---------------------------------------------------------------------------
# Embedded inventory (symbol, gap_start, gap_end, expected_bars).
# Source: diag_may_june_gap_inventory.py output 2026-06-16.
# ---------------------------------------------------------------------------
INVENTORY = [
    ("AACOU","2026-03-21","2026-05-31",52),("ACEL","2026-04-25","2026-05-31",27),
    ("ACET","2026-03-20","2026-05-31",52),("ACIU","2026-03-21","2026-05-31",52),
    ("ACXP","2026-04-25","2026-05-31",27),("AD","2026-05-05","2026-05-31",20),
    ("ADTX","2026-04-25","2026-05-31",27),("AEHL","2026-04-25","2026-05-31",27),
    ("AFK","2026-04-25","2026-05-31",27),("AGD","2026-03-21","2026-05-31",52),
    ("AIFF","2026-04-30","2026-05-31",23),("AIM","2026-04-25","2026-05-31",27),
    ("ALBT","2026-04-25","2026-05-31",27),("ALXO","2026-04-07","2026-05-31",40),
    ("AMC","2026-03-18","2026-05-31",54),("ANTX","2026-04-25","2026-05-31",27),
    ("AP","2026-04-25","2026-05-31",27),("APC","2026-04-25","2026-05-31",27),
    ("APUS","2026-03-21","2026-05-31",52),("ARCT","2026-05-05","2026-05-31",20),
    ("ARQ","2026-04-25","2026-05-31",27),("ATNM","2026-03-21","2026-05-31",52),
    ("AVX","2026-04-07","2026-05-31",40),("AVXX","2026-04-18","2026-05-31",32),
    ("AZI","2026-04-25","2026-05-31",27),("BCHT","2026-03-21","2026-05-31",52),
    ("BESS","2026-03-21","2026-05-31",52),("BHK","2026-04-30","2026-05-31",23),
    ("BIAF","2026-04-25","2026-05-31",27),("BMM","2026-03-21","2026-05-31",52),
    ("BNRG","2026-04-25","2026-05-31",27),("BRTX","2026-04-25","2026-05-31",27),
    ("BSJT","2026-04-30","2026-05-31",23),("CAMP","2026-04-25","2026-05-31",27),
    ("CCLD","2026-03-21","2026-05-31",52),("CCSI","2026-04-25","2026-05-31",27),
    ("CDTG","2026-04-25","2026-05-31",27),("CERS","2026-04-25","2026-05-31",27),
    ("CETY","2026-04-25","2026-05-31",27),("CGTL","2026-04-25","2026-05-31",27),
    ("CHGG","2026-03-21","2026-05-31",52),("CMCL","2026-04-28","2026-05-31",25),
    ("CMRC","2026-04-07","2026-05-31",40),("CMTG","2026-04-07","2026-05-31",40),
    ("CODA","2026-04-25","2026-05-31",27),("CODX","2026-04-25","2026-05-31",27),
    ("CTEV","2026-04-07","2026-05-31",40),("CUE","2026-03-21","2026-05-31",52),
    ("CURV","2026-04-25","2026-05-31",27),("CURX","2026-04-07","2026-05-31",40),
    ("CYCU","2026-04-18","2026-05-31",32),("CYN","2026-04-25","2026-05-31",27),
    ("DAIC","2026-03-21","2026-05-31",52),("DDFM","2026-04-07","2026-05-31",40),
    ("DGS","2026-05-21","2026-05-31",8),("DMAA","2026-04-07","2026-05-31",40),
    ("DOGZ","2026-03-21","2026-05-31",52),("DRCT","2026-04-07","2026-05-31",40),
    ("EARN","2026-04-25","2026-05-31",27),("ECX","2026-04-25","2026-05-31",27),
    ("EDSA","2026-04-24","2026-05-31",27),("EEIQ","2026-04-28","2026-05-31",25),
    ("EHTH","2026-03-20","2026-05-31",52),("ELAB","2026-05-12","2026-05-31",15),
    ("ELPW","2026-03-20","2026-05-31",52),("EMPD","2026-05-02","2026-05-31",22),
    ("ENGN","2026-04-25","2026-05-31",27),("EONR","2026-05-21","2026-05-31",8),
    ("EQ","2026-03-21","2026-05-31",52),("EZRA","2026-04-25","2026-05-31",27),
    ("FATE","2026-03-20","2026-05-31",52),("FBIO","2026-04-25","2026-05-31",27),
    ("FCNCN","2026-04-07","2026-05-31",40),("FEMB","2026-05-21","2026-05-31",8),
    ("FFC","2026-04-25","2026-05-31",27),("FLUD","2026-03-21","2026-05-31",52),
    ("FNKO","2026-04-28","2026-05-31",25),("FPF","2026-04-25","2026-05-31",27),
    ("FRGT","2026-03-21","2026-05-31",52),("FTK","2026-04-30","2026-05-31",23),
    ("FTNJ","2026-04-07","2026-05-31",40),("FVAV","2026-04-25","2026-05-31",27),
    ("GFAI","2026-04-07","2026-05-31",40),("GLIN","2026-04-25","2026-05-31",27),
    ("GRDX","2026-03-21","2026-05-31",52),("GRO","2026-04-25","2026-05-31",27),
    ("GXAI","2026-04-25","2026-05-31",27),("HCWB","2026-04-25","2026-05-31",27),
    ("HKD","2026-04-07","2026-05-31",40),("HRTX","2026-03-20","2026-05-31",52),
    ("HXHX","2026-03-21","2026-05-31",52),("HYLN","2026-03-20","2026-05-31",52),
    ("ICPY","2026-04-07","2026-05-31",40),("IFN","2026-04-30","2026-05-31",23),
    ("IKT","2026-04-25","2026-05-31",27),("ILLUU","2026-04-07","2026-05-31",40),
    ("IMPP","2026-04-28","2026-05-31",25),("IMTX","2026-05-02","2026-05-31",22),
    ("INDO","2026-05-12","2026-05-31",15),("INKT","2026-04-25","2026-05-31",27),
    ("IVVD","2026-05-12","2026-05-31",15),("JAGX","2026-03-21","2026-05-31",52),
    ("JFB","2026-04-07","2026-05-31",40),("JPXN","2026-04-25","2026-05-31",27),
    ("JRI","2026-04-25","2026-05-31",27),("JZXN","2026-04-07","2026-05-31",40),
    ("KALA","2026-04-25","2026-05-31",27),("KLMN","2026-04-25","2026-05-31",27),
    ("KNRX","2026-04-25","2026-05-31",27),("LAB","2026-05-21","2026-05-31",8),
    ("LNAI","2026-05-12","2026-05-31",15),("LNKS","2026-04-30","2026-05-31",23),
    ("LRHC","2026-03-19","2026-05-31",53),("LXEH","2026-04-25","2026-05-31",27),
    ("MDCX","2026-04-25","2026-05-31",27),("MEHA","2026-03-20","2026-05-31",52),
    ("MIST","2026-05-21","2026-05-31",8),("MOBX","2026-05-02","2026-05-31",22),
    ("MVIS","2026-04-25","2026-05-31",27),("MVO","2026-03-21","2026-05-31",52),
    ("NAMM","2026-04-25","2026-05-31",27),("NCPL","2026-03-21","2026-05-31",52),
    ("NIKL","2026-04-25","2026-05-31",27),("NRXP","2026-03-21","2026-05-31",52),
    ("OBAI","2026-04-07","2026-05-31",40),("OLOX","2026-04-25","2026-05-31",27),
    ("OLPX","2026-05-21","2026-05-31",8),("ONCH","2026-03-21","2026-05-31",52),
    ("ONCO","2026-05-12","2026-05-31",15),("ONMD","2026-04-25","2026-05-31",27),
    ("OPK","2026-04-25","2026-05-31",27),("OPTT","2026-04-25","2026-05-31",27),
    ("ORGN","2026-03-21","2026-05-31",52),("PALOU","2026-03-21","2026-05-31",52),
    ("PDX","2026-05-21","2026-05-31",8),("PMAX","2026-04-07","2026-05-31",40),
    ("PMVP","2026-04-25","2026-05-31",27),("PN","2026-04-25","2026-05-31",27),
    ("PONOU","2026-04-25","2026-05-31",27),("POWW","2026-04-25","2026-05-31",27),
    ("QH","2026-03-20","2026-05-31",52),("RAYA","2026-05-12","2026-05-31",15),
    ("RBBN","2026-04-25","2026-05-31",27),("REAX","2026-04-25","2026-05-31",27),
    ("RIME","2026-04-25","2026-05-31",27),("RITR","2026-04-25","2026-05-31",27),
    ("RNA","2026-05-21","2026-05-31",8),("ROMA","2026-04-25","2026-05-31",27),
    ("RVPH","2026-03-21","2026-05-31",52),("RYDE","2026-04-07","2026-05-31",40),
    ("SEGG","2026-03-18","2026-05-31",54),("SER","2026-04-25","2026-05-31",27),
    ("SGMO","2026-03-20","2026-05-31",52),("SKYE","2026-03-21","2026-05-31",52),
    ("SLAI","2026-03-21","2026-05-31",52),("SLNH","2026-03-20","2026-05-31",52),
    ("SMWB","2026-03-20","2026-05-31",52),("SPWR","2026-03-20","2026-05-31",52),
    ("SSAC","2026-04-25","2026-05-31",27),("SWIM","2026-04-25","2026-05-31",27),
    ("SXTP","2026-04-25","2026-05-31",27),("TARA","2026-04-25","2026-05-31",27),
    ("TLIH","2026-04-18","2026-05-31",32),("TLYS","2026-04-25","2026-05-31",27),
    ("TMCI","2026-03-20","2026-05-31",52),("TNYA","2026-04-25","2026-05-31",27),
    ("TPVG","2026-04-25","2026-05-31",27),("TRGSU","2026-04-25","2026-05-31",27),
    ("TRNR","2026-04-25","2026-05-31",27),("TRON","2026-04-25","2026-05-31",27),
    ("TRUD","2026-04-28","2026-05-31",25),("TURB","2026-05-02","2026-05-31",22),
    ("TUYA","2026-04-25","2026-05-31",27),("UIS","2026-03-20","2026-05-31",52),
    ("USEA","2026-04-07","2026-05-31",40),("VEEA","2026-04-07","2026-05-31",40),
    ("VNRX","2026-04-25","2026-05-31",27),("VNTG","2026-03-21","2026-05-31",52),
    ("VSEE","2026-04-07","2026-05-31",40),("XP","2026-03-14","2026-05-31",56),
    ("ZEO","2026-04-25","2026-05-31",27),("ZIP","2026-04-28","2026-05-31",25),
    ("ZNTL","2026-04-07","2026-05-31",40),
]

# Bootstrap path so we can import backend.services without modifying PYTHONPATH.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BACKEND_ROOT, ".env"))
except Exception:
    pass


def _to_ib_end(gap_end_iso: str) -> str:
    """Convert 'YYYY-MM-DD' to IB 'YYYYMMDD HH:MM:SS' end-date string.
    Use 23:59:59 so the bar at gap_end is included in the returned slice."""
    d = datetime.strptime(gap_end_iso, "%Y-%m-%d")
    return d.strftime("%Y%m%d") + " 23:59:59"


def _duration_str(expected_bars: int) -> str:
    """IB duration covering the gap (+7d safety buffer)."""
    return f"{expected_bars + 7} D"


def _connect_queue_service():
    from pymongo import MongoClient
    from services.historical_data_queue_service import (
        init_historical_data_queue_service, get_historical_data_queue_service,
    )
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=8000)[db_name]
    init_historical_data_queue_service(db)
    return get_historical_data_queue_service(), db


def cmd_check():
    print(f"[CHECK] {len(INVENTORY)} requests planned · "
          f"bar_size={BAR_SIZE} · callback_id={CALLBACK_ID}")
    total_bars = sum(b for _, _, _, b in INVENTORY)
    print(f"[CHECK] expected bars to fetch: {total_bars:,}")
    print(f"[CHECK] IB pacing 58 req/10min → ETA "
          f"≈ {len(INVENTORY) * 10 / 58:.0f}m default cadence")
    print(f"\n  {'symbol':>8} {'duration':>9} {'end_date':>22} {'bars':>5}")
    for sym, gs, ge, n in INVENTORY[:10]:
        print(f"  {sym:>8} {_duration_str(n):>9} {_to_ib_end(ge):>22} {n:>5}")
    if len(INVENTORY) > 10:
        print(f"  …and {len(INVENTORY) - 10} more")
    print("\n  re-run with --apply to enqueue.")


def cmd_clear():
    qsvc, db = _connect_queue_service()
    coll = qsvc.collection
    n = coll.count_documents({"callback_id": CALLBACK_ID,
                              "status": {"$in": ["pending", "claimed"]}})
    print(f"[CLEAR] {n} v320c rows pending/claimed in queue.")
    if n == 0:
        print("[CLEAR] nothing to do.")
        return
    res = coll.update_many(
        {"callback_id": CALLBACK_ID, "status": {"$in": ["pending", "claimed"]}},
        {"$set": {"status": "cancelled",
                  "cancelled_at": datetime.utcnow().isoformat() + "Z",
                  "cancel_reason": "v320c rollback"}},
    )
    print(f"[CLEAR] cancelled {res.modified_count} rows.")


def cmd_apply():
    qsvc, db = _connect_queue_service()
    enqueued = 0
    duped = 0
    for sym, gs, ge, n in INVENTORY:
        duration = _duration_str(n)
        end_date = _to_ib_end(ge)
        before = qsvc.collection.count_documents({
            "symbol": sym.upper(), "bar_size": BAR_SIZE,
            "end_date": end_date,
            "status": {"$in": ["pending", "claimed"]},
        })
        qsvc.create_request(
            symbol=sym, duration=duration, bar_size=BAR_SIZE,
            end_date=end_date, callback_id=CALLBACK_ID, skip_if_pending=True,
        )
        if before > 0:
            duped += 1
        else:
            enqueued += 1
    print(f"[APPLY] enqueued: {enqueued}  ·  skipped (dup): {duped}  "
          f"·  total: {enqueued + duped}")
    print("[APPLY] queue worker (collector @ client_id=16) will process "
          "these — watch with:")
    print("        tail -f $HOME/Trading-and-Analysis-Platform/logs/"
          "ib_historical_collector.log")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="Dry run")
    g.add_argument("--apply", action="store_true", help="Enqueue requests")
    g.add_argument("--clear", action="store_true", help="Cancel v320c rows")
    args = ap.parse_args()
    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply()
    elif args.clear:
        cmd_clear()


if __name__ == "__main__":
    main()
