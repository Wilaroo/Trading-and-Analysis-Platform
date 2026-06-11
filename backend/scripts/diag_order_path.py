#!/usr/bin/env python3
"""
diag_order_path.py  (read-only) — v322o follow-up
==================================================
Answers definitively: WHICH order path is live (Windows pusher vs ib-direct),
and whether the v19.34.103 multi-rung target ladder is actually reaching IB.

Checks, in order:
  1. BOT_ORDER_PATH — backend/.env file AND the live backend process env
     (via /api/system/ib-direct/migration-status which reads os.environ).
  2. order_queue (Mongo) — bracket payloads queued for the PUSHER in the
     last N days. If recent brackets exist here, the pusher path is live.
     Also inspects whether payloads carry the multi-rung `targets` array
     and whether pusher ACKs returned `target_order_ids`.
  3. bot_trades — oca_group string conventions + order-id formats on
     recent OPEN/CLOSED trades (ADOPT-OCA-* = adoption, REISSUE-* =
     re-issued pair, pusher bracket groups vs ib-direct).

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:  .venv/bin/python backend/scripts/diag_order_path.py --days 14
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
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
            return cand
    return None


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set.")
        sys.exit(1)
    return MongoClient(url)[name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--api", default="http://localhost:8001")
    args = ap.parse_args()
    env_file = _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    print("=" * 72)
    print("ORDER-PATH DIAGNOSTIC")
    print("=" * 72)

    # ── 1. env file value ────────────────────────────────────────────────
    file_val = None
    if env_file:
        for line in env_file.read_text().splitlines():
            if line.strip().startswith("BOT_ORDER_PATH"):
                file_val = line.strip()
    print(f"\n[1] backend/.env BOT_ORDER_PATH line : {file_val or '(not set — defaults to pusher)'}")

    # Live process env via the migration-status endpoint.
    try:
        with urllib.request.urlopen(f"{args.api}/api/system/ib-direct/migration-status",
                                    timeout=5) as r:
            ms = json.loads(r.read())
        print(f"    LIVE backend process order_path  : {ms.get('order_path')}")
        print(f"    migration verdict                : {ms.get('verdict')}")
        checks = ms.get("checks") or ms.get("checklist") or {}
        if checks:
            print(f"    checklist: {json.dumps(checks)[:300]}")
    except Exception as e:
        print(f"    migration-status endpoint unreachable: {e}")
        print(f"    (fallback) shell env BOT_ORDER_PATH={os.environ.get('BOT_ORDER_PATH', '(unset → pusher)')}")

    # ── 2. order_queue bracket payloads (pusher path evidence) ──────────
    print(f"\n[2] order_queue — bracket payloads, last {args.days}d:")
    try:
        q = {"order_data.type": "bracket"}
        rows = list(db["order_queue"].find(q, sort=[("created_at", -1)], limit=400))
        # created_at may be datetime or str — filter in python, tolerant.
        def _ts(r):
            v = r.get("created_at")
            return v.isoformat() if isinstance(v, datetime) else str(v or "")
        recent = [r for r in rows if _ts(r) >= cutoff]
        print(f"    bracket orders queued (pusher path): {len(recent)}")
        if recent:
            statuses = Counter((r.get("status") or "?") for r in recent)
            print(f"    statuses: {dict(statuses)}")
            with_ladder = sum(
                1 for r in recent
                if (r.get("order_data") or {}).get("targets")
            )
            multi_rung = sum(
                1 for r in recent
                if len((r.get("order_data") or {}).get("targets") or []) > 1
            )
            print(f"    payloads carrying `targets` array : {with_ladder}/{len(recent)}")
            print(f"    payloads with MULTI-rung ladder   : {multi_rung}/{len(recent)}")
            acks_with_ids = 0
            for r in recent:
                res = (r.get("result") or {})
                if res.get("target_order_ids"):
                    acks_with_ids += 1
            print(f"    pusher ACKs returning target_order_ids: {acks_with_ids}/{len(recent)}")
            print("    3 newest:")
            for r in recent[:3]:
                od = r.get("order_data") or {}
                tl = od.get("targets") or []
                res = r.get("result") or {}
                print(f"      {_ts(r)[:19]} {od.get('symbol'):<6} status={r.get('status')} "
                      f"rungs={len(tl)} "
                      f"ladder=[{', '.join(str(t.get('quantity')) + '@' + str(t.get('limit_price')) for t in tl)}] "
                      f"ack_target_ids={bool(res.get('target_order_ids'))}")
        else:
            print("    NONE — if trades executed in this window, orders did NOT go via pusher.")
    except Exception as e:
        print(f"    order_queue probe failed: {e}")

    # ── 3. bot_trades order-id / oca conventions ─────────────────────────
    print(f"\n[3] bot_trades — OCA + order-id conventions, last {args.days}d:")
    try:
        rows = list(db["bot_trades"].find(
            {"created_at": {"$gte": cutoff}},
            {"_id": 0, "symbol": 1, "status": 1, "oca_group": 1,
             "entry_order_id": 1, "stop_order_id": 1, "target_order_id": 1,
             "target_order_ids": 1, "notes": 1},
            sort=[("created_at", -1)], limit=500,
        ))
        print(f"    trades: {len(rows)}")
        oca_kinds = Counter()
        with_multi_ids = 0
        for t in rows:
            g = str(t.get("oca_group") or "")
            if g.startswith("ADOPT-OCA"):
                oca_kinds["ADOPT-OCA-*"] += 1
            elif g.startswith("REISSUE"):
                oca_kinds["REISSUE-*"] += 1
            elif g:
                oca_kinds[g.split("-")[0][:16] + "-*"] += 1
            else:
                oca_kinds["(none)"] += 1
            if t.get("target_order_ids"):
                with_multi_ids += 1
        print(f"    oca_group conventions: {dict(oca_kinds)}")
        print(f"    trades with target_order_ids list populated: {with_multi_ids}/{len(rows)}")
        samples = [t for t in rows if t.get("entry_order_id")][:5]
        for t in samples:
            print(f"      {t.get('symbol'):<6} entry_id={str(t.get('entry_order_id'))[:20]:<20} "
                  f"stop_id={str(t.get('stop_order_id'))[:14]:<14} "
                  f"tgt_id={str(t.get('target_order_id'))[:14]}")
    except Exception as e:
        print(f"    bot_trades probe failed: {e}")

    print("\nVERDICT GUIDE:")
    print("  • live order_path=pusher + recent order_queue brackets → PUSHER path live.")
    print("  • live order_path=direct + empty order_queue           → IB-DIRECT path live.")
    print("  • multi-rung=0 on intraday trades → ladder is NOT reaching IB (single TP only).")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
