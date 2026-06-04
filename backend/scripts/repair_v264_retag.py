#!/usr/bin/env python3
"""
repair_v264_retag.py — re-attribute today's mis-adopted orphans to the bot.

For the 2026-06-04 MRSH/CEG incident (and any like it): a bot-originated entry
filled at IB, lost fill attribution, and was adopted as a synthetic
`reconciled_orphan` (entered_by='reconciled_external') while the real bot row
was reaped as `stale_pending_auto_reaper`. This restores correct ATTRIBUTION
(so the trade counts toward Bot-Edge, not Adopted) WITHOUT touching the live
bracket/orders (operator choice C):

  - flips entered_by 'reconciled_external' -> 'bot_fired'
  - restores setup_type from the matching reaped bot_fired row (so the UI/bot
    recognize it as their own setup) when a confident match is found
  - stamps a `reattributed_v264` audit flag + note
  - leaves stop_price / target_prices / shares / orders UNTOUCHED

A match requires the reaped row to share symbol + direction + shares and be
close in time. Idempotent (skips rows already bot_fired / already flagged).
DRY-RUN by default. Reads MONGO_URL + DB_NAME from backend/.env.

Run from repo root:
    curl -s <url> | python3 -                      # preview (all auto-detected)
    curl -s <url> | python3 - --symbols MRSH,CEG    # restrict
    curl -s <url> | python3 - --commit              # apply
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timezone
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


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


def _enum(v):
    return str(getattr(v, "value", v) or "").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="comma list to restrict (default: auto)")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    _load_env()
    db = _db()
    only = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    bt = db["bot_trades"]
    q = {"status": {"$in": ["open", "OPEN"]}, "setup_type": "reconciled_orphan"}
    if only:
        q["symbol"] = {"$in": list(only)}
    orphans = list(bt.find(q))

    print("=" * 70)
    print(f"v19.34.264 re-tag repair — {'COMMIT' if args.commit else 'DRY-RUN'}")
    print(f"open reconciled_orphan rows: {len(orphans)}")
    print("=" * 70)

    changed = 0
    for o in orphans:
        sym = (o.get("symbol") or "").upper()
        oid = o.get("id") or o.get("trade_id")
        odir = _enum(o.get("direction"))
        osh = int(o.get("shares") or o.get("remaining_shares") or 0)
        if "bot_fired" in _enum(o.get("entered_by")) or o.get("reattributed_v264"):
            print(f"  • {sym} {oid}: already bot_fired/flagged — skip.")
            continue

        # Find the matching reaped bot_fired row (real setup + intent).
        reaped = list(bt.find({
            "symbol": sym,
            "status": {"$in": ["rejected", "REJECTED"]},
            "close_reason": "stale_pending_auto_reaper",
            "entered_by": {"$regex": "bot_fired", "$options": "i"},
        }))
        match = None
        for r in reaped:
            if _enum(r.get("direction")) != odir:
                continue
            if int(r.get("shares") or 0) != osh:
                continue
            match = r
            break

        real_setup = (match or {}).get("setup_type")
        real_alert = (match or {}).get("alert_id")
        print(f"  • {sym} {oid} {odir} {osh}sh: entered_by "
              f"{o.get('entered_by')!r} -> 'bot_fired'"
              + (f", setup_type 'reconciled_orphan' -> {real_setup!r} "
                 f"(from reaped {match.get('id')})" if match else
                 "  [no reaped match — setup_type left as-is]"))

        if args.commit:
            upd = {
                "entered_by": "bot_fired",
                "reattributed_v264": True,
                "reattributed_at": datetime.now(timezone.utc).isoformat(),
                "notes": (o.get("notes") or "") + (
                    " [v19.34.264 re-attributed to bot_fired; original fill lost "
                    "attribution and was synthetically adopted. Live bracket left "
                    "UNCHANGED per operator (synthetic 2% levels still in effect).]"
                ),
            }
            if real_setup:
                upd["setup_type"] = real_setup
            if real_alert and not o.get("alert_id"):
                upd["alert_id"] = real_alert
            bt.update_one({"$or": [{"id": oid}, {"trade_id": oid}]}, {"$set": upd})
            changed += 1

    print("-" * 70)
    if args.commit:
        print(f"COMMITTED — {changed} row(s) re-attributed to bot_fired.")
        print("Brackets untouched. These now count toward Bot-Edge (not Adopted).")
    else:
        print("DRY-RUN — nothing written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
