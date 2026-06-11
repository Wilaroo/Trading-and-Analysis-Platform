#!/usr/bin/env python3
"""
repair_created_at_backfill.py — one-off repair for bot_trades rows whose
`created_at` is an empty string / None / missing (the BotTrade dataclass
default was `""` until v322s — any construction path that didn't set it
explicitly persisted an empty string, hiding the row from every
date-windowed query; the ACMR 65h-carry row e11450ca was invisible to two
autopsy probes because of this).

Backfill source priority: executed_at → pre_submit_at → closed_at.
Rows with none of the three are reported but left untouched.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/repair_created_at_backfill.py            # DRY-RUN
  .venv/bin/python backend/scripts/repair_created_at_backfill.py --apply    # write
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env", BACKEND / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is dry-run)")
    args = ap.parse_args()
    _load_env()
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    db = MongoClient(url)[os.environ.get("DB_NAME", "tradecommand")]
    print(f"[db] {os.environ.get('DB_NAME', 'tradecommand')} @ {url.split('@')[-1]}")
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[mode] {mode}\n")

    q = {"$or": [
        {"created_at": {"$in": ["", None]}},
        {"created_at": {"$exists": False}},
    ]}
    rows = list(db["bot_trades"].find(
        q, {"_id": 1, "id": 1, "symbol": 1, "status": 1,
            "executed_at": 1, "pre_submit_at": 1, "closed_at": 1}))
    print(f"{len(rows)} row(s) with empty/missing created_at")

    fixed = unfixable = 0
    for t in rows:
        src_field, src_val = None, None
        for f in ("executed_at", "pre_submit_at", "closed_at"):
            v = t.get(f)
            if v:
                src_field, src_val = f, v
                break
        tid = str(t.get("id"))[:8]
        if not src_val:
            unfixable += 1
            print(f"  ✗ {tid} {t.get('symbol'):6s} status={t.get('status')} — "
                  f"no executed/pre_submit/closed timestamp; LEFT UNTOUCHED")
            continue
        if not isinstance(src_val, str):
            try:
                src_val = src_val.isoformat()
            except Exception:
                unfixable += 1
                print(f"  ✗ {tid} {t.get('symbol'):6s} — {src_field} not "
                      f"serializable ({type(src_val).__name__}); LEFT UNTOUCHED")
                continue
        print(f"  ✓ {tid} {t.get('symbol'):6s} status={t.get('status'):9s} "
              f"created_at ← {src_field} = {src_val[:19]}")
        if args.apply:
            db["bot_trades"].update_one(
                {"_id": t["_id"]},
                {"$set": {"created_at": src_val,
                          "created_at_backfilled_from": src_field}})
        fixed += 1

    print(f"\n{mode}: {fixed} fixable, {unfixable} unfixable"
          + ("" if args.apply else "  (re-run with --apply to write)"))


if __name__ == "__main__":
    main()
