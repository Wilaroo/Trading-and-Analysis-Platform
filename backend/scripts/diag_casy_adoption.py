#!/usr/bin/env python3
"""
diag_casy_adoption.py  (read-only) — CASY ladder forensics
===========================================================
The adopted CASY got an M0 ladder while its Mongo record reads
`swing` + `rejected`. This dumps everything needed to see which record
owns the ladder orders, what status it's in (i.e. is anything managing
those legs?), and what the app's positions view is actually showing.

Usage:  .venv/bin/python backend/scripts/diag_casy_adoption.py [--symbol CASY]
"""
from __future__ import annotations
import argparse
import json
import os
import urllib.request
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
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="CASY")
    ap.add_argument("--api", default="http://localhost:8001")
    args = ap.parse_args()
    sym = args.symbol.upper()
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    print("=" * 76)
    print(f"{sym} ADOPTION/LADDER FORENSICS")
    print("=" * 76)

    # 1. every bot_trades record for the symbol (3d)
    rows = list(db.bot_trades.find(
        {"symbol": sym, "created_at": {"$gte": cutoff}},
        sort=[("created_at", 1)]))
    # also catch records with missing/odd created_at
    if not rows:
        rows = list(db.bot_trades.find({"symbol": sym},
                                       sort=[("created_at", -1)], limit=10))
    print(f"\n[1] bot_trades records ({len(rows)}):")
    for t in rows:
        adopt_fields = {k: v for k, v in t.items() if "adopt" in k.lower()}
        cfg = t.get("scale_out_config") or {}
        legs = cfg.get("m0_legs") or []
        print(f"\n  id={t.get('id')}  status={t.get('status')}")
        print(f"    style fields: trade_style={t.get('trade_style')} "
              f"timeframe={t.get('timeframe')} trade_type={t.get('trade_type')} "
              f"scan_tier={t.get('scan_tier')} setup_type={t.get('setup_type')}")
        print(f"    sh={t.get('shares')} rem={t.get('remaining_shares')} "
              f"entry={t.get('entry_price')} fill={t.get('fill_price')} "
              f"stop={t.get('stop_price')} targets={t.get('target_prices')}")
        print(f"    order ids: entry={t.get('entry_order_id')} "
              f"stop={t.get('stop_order_id')} tgt={t.get('target_order_id')} "
              f"tgt_ids={t.get('target_order_ids')}")
        print(f"    oca_group={t.get('oca_group')}")
        print(f"    m0_legs={len(legs)}: " + "; ".join(
            f"L{l.get('idx', 0) + 1} {l.get('qty')}sh tgt={l.get('target_px')} "
            f"stop_id={l.get('stop_order_id')} tgt_id={l.get('target_order_id')} "
            f"[{l.get('status')}]" for l in legs))
        if adopt_fields:
            print(f"    adoption fields: {json.dumps(adopt_fields, default=str)[:300]}")
        notes = str(t.get("notes") or "")[:200]
        if notes:
            print(f"    notes: {notes}")
        print(f"    created={str(t.get('created_at'))[:19]} "
              f"executed={str(t.get('executed_at'))[:19]} "
              f"closed={str(t.get('closed_at'))[:19]} "
              f"close_reason={t.get('close_reason')}")

    # 2. adoption-related collections
    print("\n[2] adoption-related collections:")
    for cname in db.list_collection_names():
        if "adopt" in cname.lower():
            docs = list(db[cname].find({"symbol": sym},
                                       sort=[("_id", -1)], limit=3))
            print(f"  {cname}: {len(docs)} recent doc(s) for {sym}")
            for d in docs:
                d.pop("_id", None)
                print(f"    {json.dumps(d, default=str)[:400]}")

    # 3. what the app's positions view sees
    print("\n[3] /api/sentcom/positions view:")
    try:
        with urllib.request.urlopen(f"{args.api}/api/sentcom/positions",
                                    timeout=8) as r:
            data = json.loads(r.read())
        plist = data if isinstance(data, list) else (
            data.get("positions") or data.get("open") or [])
        hits = [p for p in plist if str(p.get("symbol", "")).upper() == sym]
        if not hits:
            print(f"  {sym} not in open positions payload "
                  f"({len(plist)} positions total)")
        for p in hits:
            keep = {k: p.get(k) for k in (
                "symbol", "status", "trade_style", "timeframe", "shares",
                "remaining_shares", "entry_price", "stop_price",
                "target_prices", "adopted", "is_adopted", "source",
                "direction", "id", "trade_id") if k in p}
            print(f"  {json.dumps(keep, default=str)}")
    except Exception as e:
        print(f"  positions endpoint unreachable: {e}")

    print("\nDone (read-only). Paste this whole output back.")


if __name__ == "__main__":
    main()
