#!/usr/bin/env python3
"""
diag_outcomes_purge_preview.py — READ-ONLY preview of a "purge trade outcomes
before <DATE>" operation. NOTHING IS DELETED.

Shows, per outcome collection, EXACTLY what a cutoff purge would remove and what
it would keep, so the decision is made on real numbers — plus two safety reads:

  • how much of the pre-cutoff data is ALREADY broken-path/artifact (per the
    canonical hygiene classifier) vs genuine — i.e. how much is truly "junk".
  • how many of the learning rebuild's LAST-500 window are pre-cutoff — i.e.
    whether purging would even move current win-rate / EV stats.

Then it recommends the reversible archive-then-delete path (not a blind delete).

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_outcomes_purge_preview.py
  .venv/bin/python backend/scripts/diag_outcomes_purge_preview.py --before 2026-06-01
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CANDIDATES = [
    "bot_trades", "alert_outcomes", "trade_outcomes", "shadow_outcomes",
    "trade_grades", "gate_outcomes",
]
DATE_FIELDS = ["created_at", "closed_at", "executed_at", "timestamp", "date"]


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services" / "trade_outcome_hygiene.py").exists():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pick_date_field(coll):
    doc = coll.find_one({}, {f: 1 for f in DATE_FIELDS})
    if not doc:
        return None
    for f in DATE_FIELDS:
        if doc.get(f):
            return f
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    cutoff = "2026-06-01"
    if "--before" in sys.argv:
        try:
            cutoff = sys.argv[sys.argv.index("--before") + 1]
        except Exception:
            pass
    cutoff_iso = cutoff if "T" in cutoff else cutoff + "T00:00:00+00:00"

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    existing = set(db.list_collection_names())

    print("=" * 88)
    print(f"OUTCOMES PURGE PREVIEW — cutoff: delete docs with date < {cutoff}  (READ-ONLY)")
    print(f"  cutoff_iso={cutoff_iso}   DB={os.environ.get('DB_NAME','tradecommand')}   "
          f"{datetime.now(timezone.utc).isoformat()[:19]}Z")
    print("=" * 88)

    grand_del = 0
    for name in CANDIDATES:
        if name not in existing:
            continue
        coll = db[name]
        total = coll.estimated_document_count()
        df = _pick_date_field(coll)
        print("\n" + "-" * 88)
        print(f"  {name}   total≈{total}   date_field={df}")
        if not df:
            print("    no recognizable date field — SKIP (cannot cutoff safely).")
            continue
        pre = coll.count_documents({df: {"$lt": cutoff_iso}})
        post = coll.count_documents({df: {"$gte": cutoff_iso}})
        grand_del += pre
        # date range
        lo = coll.find_one({df: {"$exists": True, "$ne": None}}, sort=[(df, 1)])
        hi = coll.find_one({df: {"$exists": True, "$ne": None}}, sort=[(df, -1)])
        print(f"    would DELETE (< {cutoff}): {pre}")
        print(f"    would KEEP   (>= {cutoff}): {post}")
        print(f"    date range: {str((lo or {}).get(df))[:19]}  ..  {str((hi or {}).get(df))[:19]}")
        # null-date docs (would be untouched by a date cutoff — flag them)
        nulls = coll.count_documents({"$or": [{df: None}, {df: {"$exists": False}}]})
        if nulls:
            print(f"    ⚠ {nulls} docs have NO {df} → a date cutoff would NOT touch them")

    # ---- how much pre-cutoff bot_trades is already broken-path? ----
    if "bot_trades" in existing:
        try:
            from services.trade_outcome_hygiene import classify_close
            df = _pick_date_field(db["bot_trades"]) or "created_at"
            pre_docs = list(db["bot_trades"].find(
                {df: {"$lt": cutoff_iso}, "status": {"$regex": "^closed"}},
                {"_id": 0, "entered_by": 1, "close_reason": 1, "fill_price": 1,
                 "entry_price": 1, "exit_price": 1, "net_pnl": 1, "realized_pnl": 1,
                 "hold_seconds": 1, "setup_type": 1, "direction": 1, "stop_price": 1,
                 "target_prices": 1, "shares": 1}).limit(20000))
            genuine = artifact = 0
            reasons = Counter()
            for t in pre_docs:
                reasons[str(t.get("close_reason") or "?")[:24]] += 1
                try:
                    g, _ = classify_close(
                        close_reason=str(t.get("close_reason") or ""),
                        entered_by=str(t.get("entered_by") or ""),
                        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
                        exit_price=_f(t.get("exit_price")), net_pnl=_f(t.get("net_pnl")),
                        hold_seconds=_f(t.get("hold_seconds")),
                        setup_type=str(t.get("setup_type") or ""), direction=t.get("direction"),
                        stop_price=_f(t.get("stop_price")), target_prices=t.get("target_prices"),
                        realized_pnl=_f(t.get("realized_pnl")), shares=_f(t.get("shares")))
                    genuine += 1 if g else 0
                    artifact += 0 if g else 1
                except Exception:
                    pass
            n = len(pre_docs)
            print("\n" + "-" * 88)
            print(f"  pre-cutoff bot_trades CLOSED quality (sampled {n}):")
            if n:
                print(f"    genuine={genuine} ({100*genuine/n:.0f}%)   "
                      f"broken-path/artifact={artifact} ({100*artifact/n:.0f}%)")
                print("    top close_reasons: " + ", ".join(f"{k}={v}" for k, v in reasons.most_common(8)))
                print("    → the higher the artifact %, the more 'junk' the purge removes.")
        except Exception as e:
            print(f"\n  (bot_trades hygiene sample skipped: {e})")

    # ---- learning rebuild impact: how many of the last-500 trade_outcomes are pre-cutoff? ----
    if "trade_outcomes" in existing:
        df = _pick_date_field(db["trade_outcomes"]) or "created_at"
        last500 = list(db["trade_outcomes"].find({}, {"_id": 0, df: 1}).sort(df, -1).limit(500))
        pre_in_500 = sum(1 for d in last500 if str(d.get(df) or "") < cutoff_iso)
        print("\n" + "-" * 88)
        print(f"  learning_stats rebuild window (last {len(last500)} trade_outcomes):")
        print(f"    pre-cutoff in that window: {pre_in_500}/{len(last500)} "
              f"({100*pre_in_500/max(len(last500),1):.0f}%)")
        print("    → if this is ~0%, purging pre-cutoff barely moves current win-rate / EV stats.")

    print("\n" + "=" * 88)
    print(f"SUMMARY: a < {cutoff} cutoff would delete ~{grand_del} docs across the collections above.")
    print("RECOMMENDATION (reversible): archive-then-delete, not a blind delete —")
    print("  1) copy pre-cutoff docs to {coll}_archive_pre_<date>   (restorable)")
    print("  2) delete from the live collection")
    print("  3) rebuild learning_stats from the cleaned corpus")
    print("Say the word and I'll build that archive-then-purge script (with a --dry-run default,")
    print("explicit --confirm to actually write, and per-collection archive + counts). NOTHING WRITTEN.")
    print("=" * 88)


if __name__ == "__main__":
    main()
