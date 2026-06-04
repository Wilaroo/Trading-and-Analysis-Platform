#!/usr/bin/env python3
"""
backfill_v263.py — reprocess historical external/OCA scalp+intraday closes
through the v19.34.263 reclassifier, fixing their genuine flag +
effective_close_reason in `alert_outcomes` and refreshing `strategy_stats`.

DRY-RUN by default (counts only, no writes). Pass --commit to apply.
Read-only on --dry-run. Reads MONGO_URL + DB_NAME from backend/.env.

Run from the repo root AFTER apply_v263.py + backend restart:
    curl -s <this-url> | python3 - --days 30           # preview
    curl -s <this-url> | python3 - --days 30 --commit  # apply
    curl -s <this-url> | python3 - --commit            # all-time
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _repo_backend_on_path() -> Path:
    root = Path.cwd()
    backend = root / "backend"
    if not backend.is_dir():
        backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    return backend


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None,
                    help="lookback window (default: all-time)")
    ap.add_argument("--commit", action="store_true",
                    help="write changes (default: dry-run)")
    args = ap.parse_args()

    _load_env()
    _repo_backend_on_path()
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        return 2

    from pymongo import MongoClient
    from services import learning_reconciler as LR
    from services import pnl_compute

    db = MongoClient(url)[name]
    pnl_compute._AO_DB = db  # point canonical strategy_stats writer at this db

    mode = "COMMIT" if args.commit else "DRY-RUN"
    span = f"{args.days}d" if args.days else "all-time"
    print("=" * 70)
    print(f"v19.34.263 external-close reclass backfill — {mode} — {span}")
    print(f"[db] {name} @ {url.split('@')[-1]}")
    print("=" * 70)

    rep = LR.reprocess_external_closes(
        db, days=args.days, commit=args.commit, verbose=False)

    bk = rep["by_kind"]
    print(f"  closed scanned       : {rep['scanned']}")
    print(f"  external bracket rows : {rep['external_rows']}")
    print(f"  reclassified (genuine): {rep['reclassified']}")
    print(f"      → target          : {bk['target']}")
    print(f"      → stop_loss       : {bk['stop_loss']}")
    print(f"      → external_partial: {bk['external_partial']}")
    print(f"      → corrupt_r (drop): {bk['corrupt_r']}")
    print(f"      → unresolved      : {bk['unresolved']}")
    print(f"  flipped→genuine (were dropped): {rep['flipped_to_genuine']}")
    print(f"  alert_outcomes upserted       : {rep['ao_upserted']}")
    print(f"  affected setups ({len(rep['affected_setups'])}): "
          f"{', '.join(rep['affected_setups'][:20])}")

    if not args.commit:
        print("\nDRY-RUN — nothing written. Re-run with --commit to apply.")
    else:
        print("\nCOMMITTED — alert_outcomes + strategy_stats updated.")
        print("Verify scalp EV: GET /api/setup-grades  or re-run "
              "diag_scalp_exit_truth.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
