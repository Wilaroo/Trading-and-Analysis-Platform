#!/usr/bin/env python3
"""
apply_v328.py — Daily-Bar Leak (real fix) + RTH deep-backfill gate
====================================================================
Probe findings (diag_chart_wall_and_daily_leak, 2026-06-12 13:37 ET):
40 in-progress daily bars leaked DESPITE the v323b collector guard.

ROOT CAUSE — the v323b guard only covered the collector's own three
storage paths. The IB Data Pusher does NOT store through the collector:
it uploads via the router endpoints, which bulk-write straight into
`ib_historical_data` with NO guard:

  • routers/ib_modules/historical_data.py  /historical-data/result
  • routers/ib_modules/historical_data.py  /historical-data/batch-result
  • routers/ib.py                          (same two legacy endpoints)
  • services/slow_learning/historical_data_service.py (alpaca writer)

Every daily backfill request fulfilled mid-session re-writes TODAY'S
partial daily bar through these paths → partial volume poisons RVOL
(prior-day guard computes RVOL=partial/avg≈0.1x) → every scalp blocked.

FIX 1 — add the existing `_is_inprogress_daily_bar` guard to ALL five
        unguarded write sites.

FIX 2 — RTH deep-backfill gate (data-blackout root cause): during the
        ET cash session (Mon-Fri 09:25-16:05) the queue stops serving
        DEEP backfill requests (backward-chained `end_date` requests
        and >=2-month/year durations) to the pusher. They stay pending
        and resume automatically after the close. Live turbo refreshes
        ("1 D".."1 M", no end_date) keep flowing. This stops deep
        backfill from burning IB's 60-req/10-min pacing budget and
        starving live 5-min bars (the "snapshot unavailable" blackout
        that killed all scalps on 2026-06-12).
        Optional kill-switch: HIST_BACKFILL_RTH_GATE=0.

FIX 3 — one-shot DB purge: deletes daily bars from the last 10 days
        whose `collected_at` proves they were written BEFORE their own
        session close (16:15 ET) — i.e. partial/poisoned bars,
        including today's 40 leaked rows. Tonight's collection re-fetches
        them as final bars.

SAFE TO RUN MULTIPLE TIMES (idempotent).
Run from repo root:   .venv/bin/python /tmp/apply_v328.py
Files-only (no DB):   .venv/bin/python /tmp/apply_v328.py --files-only
Then: git add -A && git commit -m "v328: daily-bar leak fix + RTH backfill gate" && git push
Then restart the backend (StartTrading.bat does git checkout -- . — commit FIRST).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHUNKS = [
    ('backend/services/historical_data_queue_service.py',
     '\n# Global instance\n_historical_data_queue_service = None\n\n\nclass HistoricalDataQueueService:\n',
     '\n# Global instance\n_historical_data_queue_service = None\n\n\ndef _rth_backfill_gate_active() -> bool:\n    """v328 — True during the ET cash session (Mon-Fri 09:25-16:05 ET).\n\n    Deep historical backfill (chained end_date requests, multi-month /\n    year-long durations) burns IB\'s 60-req/10-min historical pacing\n    budget and starves the live turbo collectors. Mongo intraday bars\n    then go stale, get_technical_snapshot(mongo_only) returns None and\n    the scanner spams "snapshot unavailable" — a full data blackout\n    (2026-06-12 incident: zero scalps fired all session). While the\n    gate is active only short live-refresh requests are served; deep\n    requests simply stay `pending` and resume automatically after the\n    close. Set HIST_BACKFILL_RTH_GATE=0 to disable.\n    """\n    import os\n    if os.environ.get("HIST_BACKFILL_RTH_GATE", "1") == "0":\n        return False\n    try:\n        from zoneinfo import ZoneInfo\n        now = datetime.now(ZoneInfo("America/New_York"))\n        if now.weekday() >= 5:\n            return False\n        mins = now.hour * 60 + now.minute\n        return (9 * 60 + 25) <= mins <= (16 * 60 + 5)\n    except Exception:\n        return False\n\n\ndef _deep_request_exclusion() -> List[Dict]:\n    """v328 — Mongo clauses that EXCLUDE deep-backfill queue rows.\n\n    Deep = backward-chained requests (non-empty end_date) or durations\n    of >= 2 months / any year unit. Live turbo refreshes use short\n    durations ("1 D", "2 D", "1 M" catch-ups) with no end_date and\n    keep flowing during RTH.\n    """\n    return [\n        {"$or": [{"end_date": ""}, {"end_date": None},\n                 {"end_date": {"$exists": False}}]},\n        {"duration": {"$not": {"$regex": r"^\\s*\\d+\\s*Y\\s*$",\n                               "$options": "i"}}},\n        {"duration": {"$not": {"$regex": r"^\\s*([2-9]|[1-9][0-9]+)\\s*M\\s*$",\n                               "$options": "i"}}},\n    ]\n\n\nclass HistoricalDataQueueService:\n'),
    ('backend/services/historical_data_queue_service.py',
     '                       e.g., (0, 3) = this instance handles symbols whose hash % 3 == 0\n        """\n        match_filter = {"status": "pending"}\n        \n        # Filter by bar_sizes if specified\n        if bar_sizes:\n            match_filter["bar_size"] = {"$in": bar_sizes}\n',
     '                       e.g., (0, 3) = this instance handles symbols whose hash % 3 == 0\n        """\n        match_filter = {"status": "pending"}\n\n        # v328 — RTH deep-backfill gate: hold deep requests during the\n        # cash session so the IB pacing budget goes to live data (see\n        # _rth_backfill_gate_active docstring).\n        rth_gate = _rth_backfill_gate_active()\n        if rth_gate:\n            match_filter["$and"] = _deep_request_exclusion()\n\n        # Filter by bar_sizes if specified\n        if bar_sizes:\n            match_filter["bar_size"] = {"$in": bar_sizes}\n'),
    ('backend/services/historical_data_queue_service.py',
     '            target_symbol = candidate["_id"]\n            \n            find_filter = {"status": "pending", "symbol": target_symbol}\n            if bar_sizes:\n                find_filter["bar_size"] = {"$in": bar_sizes}\n            \n',
     '            target_symbol = candidate["_id"]\n            \n            find_filter = {"status": "pending", "symbol": target_symbol}\n            if rth_gate:\n                find_filter["$and"] = _deep_request_exclusion()\n            if bar_sizes:\n                find_filter["bar_size"] = {"$in": bar_sizes}\n            \n'),
    ('backend/routers/ib_modules/historical_data.py',
     '                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        \n                        bulk_operations.append(\n                            UpdateOne(\n',
     '                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        # v328 — this pusher upload path bypassed the v323b\n                        # collector guard: never persist today\'s in-progress\n                        # daily bar (partial volume poisons RVOL → blocks\n                        # every scalp for the session).\n                        if collector._is_inprogress_daily_bar(bar_size, date_val):\n                            continue\n                        \n                        bulk_operations.append(\n                            UpdateOne(\n'),
    ('backend/routers/ib_modules/historical_data.py',
     '                    for bar in data:\n                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        \n                        all_bulk_operations.append(\n',
     '                    for bar in data:\n                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        # v328 — never persist today\'s in-progress daily bar\n                        # (pusher batch path bypassed the v323b guard).\n                        if collector._is_inprogress_daily_bar(bar_size, date_val):\n                            continue\n                        \n                        all_bulk_operations.append(\n'),
    ('backend/routers/ib.py',
     '                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        bars_to_store.append({\n                            "symbol": symbol,\n                            "bar_size": bar_size,\n',
     '                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        # v328 — this pusher upload path bypassed the v323b\n                        # collector guard: never persist today\'s in-progress\n                        # daily bar (partial volume poisons RVOL → blocks\n                        # every scalp for the session).\n                        if collector._is_inprogress_daily_bar(bar_size, date_val):\n                            continue\n                        bars_to_store.append({\n                            "symbol": symbol,\n                            "bar_size": bar_size,\n'),
    ('backend/routers/ib.py',
     '                    for bar in data:\n                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        \n                        all_bulk_operations.append(\n',
     '                    for bar in data:\n                        date_val = bar.get("date") or bar.get("time")\n                        if not date_val:\n                            continue\n                        # v328 — never persist today\'s in-progress daily bar\n                        # (pusher batch path bypassed the v323b guard).\n                        if collector._is_inprogress_daily_bar(bar_size, date_val):\n                            continue\n                        \n                        all_bulk_operations.append(\n'),
    ('backend/services/slow_learning/historical_data_service.py',
     '            try:\n                timestamp = bar.get("timestamp", "")\n                date_str = timestamp[:10] if is_daily and isinstance(timestamp, str) else timestamp\n                \n                self._historical_bars_col.update_one(\n                    {\n                        "symbol": symbol,\n',
     '            try:\n                timestamp = bar.get("timestamp", "")\n                date_str = timestamp[:10] if is_daily and isinstance(timestamp, str) else timestamp\n\n                # v328 — never persist today\'s in-progress daily bar\n                from services.ib_historical_collector import IBHistoricalCollector\n                if IBHistoricalCollector._is_inprogress_daily_bar(bar_size, date_str):\n                    continue\n\n                self._historical_bars_col.update_one(\n                    {\n                        "symbol": symbol,\n'),
]


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "historical_data_queue_service.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def apply_chunks(root: Path) -> int:
    applied = 0
    for rel, old, new in CHUNKS:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} — chunk already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} — anchor found {n}x (expected 1). File drifted. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} — chunk applied")
    return applied


def _load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))


def purge_partial_daily_bars(root: Path) -> None:
    """Delete daily bars (last 10 days) written BEFORE their own 16:15 ET
    close — provably partial. Includes today's 40 leaked rows."""
    from zoneinfo import ZoneInfo
    from pymongo import MongoClient

    _load_env(root)
    url = os.environ.get("MONGO_URL")
    if not url:
        print("[WARN] MONGO_URL not found — skipping DB purge")
        return
    db = MongoClient(url)[os.environ.get("DB_NAME", "tradecommand")]
    coll = db["ib_historical_data"]
    ET = ZoneInfo("America/New_York")
    cutoff = (datetime.now(ET) - timedelta(days=10)).strftime("%Y-%m-%d")

    victims = []
    scanned = 0
    for doc in coll.find(
        {"bar_size": "1 day", "date": {"$gte": cutoff, "$type": "string"}},
        {"_id": 1, "symbol": 1, "date": 1, "collected_at": 1},
    ):
        scanned += 1
        ca = doc.get("collected_at")
        if not ca:
            continue
        try:
            ca_dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            if ca_dt.tzinfo is None:
                ca_dt = ca_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        d = str(doc.get("date"))[:10]
        try:
            y, m, dd = (int(x) for x in d.split("-"))
            close_utc = datetime(y, m, dd, 16, 15, tzinfo=ET).astimezone(timezone.utc)
        except Exception:
            continue
        if ca_dt < close_utc:
            victims.append((doc["_id"], doc.get("symbol"), d))

    print(f"[DB]   scanned {scanned} daily bars since {cutoff} — "
          f"{len(victims)} provably-partial (collected before own close)")
    for _id, sym, d in victims:
        coll.delete_one({"_id": _id})
        print(f"       purged {sym} {d}")
    print(f"[DB]   purge complete — {len(victims)} partial daily bars removed")


def main():
    root = find_root()
    print(f"repo root: {root}")
    applied = apply_chunks(root)
    if "--files-only" in sys.argv:
        print("[SKIP] DB purge (--files-only)")
    else:
        purge_partial_daily_bars(root)
    print()
    print(f"v328 done — {applied} chunk(s) newly applied.")
    print("Next:")
    print("  git add -A && git commit -m 'v328: daily-bar leak fix + RTH backfill gate' && git push")
    print("  then RESTART the backend (queue gate + router guards load at startup).")
    print("NOTE: with the RTH gate active, deep backfill requests pause 09:25-16:05 ET")
    print("      and auto-resume after the close. Disable via HIST_BACKFILL_RTH_GATE=0.")


if __name__ == "__main__":
    main()
