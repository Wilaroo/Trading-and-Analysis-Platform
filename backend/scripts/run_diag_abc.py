#!/usr/bin/env python3
"""Run the A/B/C trade-integrity diagnostics against the LIVE Mongo — read-only.

No backend restart needed. Reads MONGO_URL/DB_NAME from backend/.env (same DB the
bot writes to) and prints the three reports as JSON:

  A) MFE/MAE study      — bad ENTRIES vs bad EXITS, per horizon.
  B) TQS integrity      — is the quality score actually PREDICTIVE?
  C) Horizon funnel     — where fast (scalp/intraday) trades are crowded out.

Usage (on the DGX, from anywhere):
    python /app/backend/scripts/run_diag_abc.py --days 5
    python /app/backend/scripts/run_diag_abc.py --days 5 --section A
"""
import os
import sys
import json
import argparse

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def _load_env():
    """Load backend/.env into os.environ without requiring python-dotenv."""
    env_path = os.path.join(BACKEND_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="lookback window (default 5)")
    ap.add_argument("--section", choices=["A", "B", "C", "all"], default="all")
    args = ap.parse_args()

    _load_env()
    if not os.environ.get("MONGO_URL"):
        print("ERROR: MONGO_URL not set (checked backend/.env and environment).")
        sys.exit(1)

    from database import get_database
    from services.mfe_mae_study import generate_report as mfe_report
    from services.tqs_integrity import generate_report as tqs_report
    from services.horizon_funnel import generate_report as funnel_report

    db = get_database()
    if db is None:
        print("ERROR: could not connect to Mongo (get_database returned None).")
        sys.exit(1)

    out = {}
    if args.section in ("A", "all"):
        out["A_mfe_mae"] = mfe_report(db, args.days)
    if args.section in ("B", "all"):
        out["B_tqs_integrity"] = tqs_report(db, args.days)
    if args.section in ("C", "all"):
        out["C_horizon_funnel"] = funnel_report(db, args.days)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
