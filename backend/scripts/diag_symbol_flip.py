#!/usr/bin/env python3
"""
diag_symbol_flip.py  (read-only) — position flip / trade-history forensics
===========================================================================
Built for the GLD +77 → -77 flip (realized -$637): prints everything the
backend knows about a symbol so we can see whether a direction flip was a
deliberate bot trade, an adoption, or a reconciler/order escape.

Sections:
  1. bot_trades rows (newest first) — direction, shares, status, entered_by,
     setup, stop/targets, order ids, pnl, exit reason, timestamps.
  2. bracket_lifecycle_events — reissue/flip-guard/consolidation footprints.
  3. Net summary — realized pnl by trade, flips detected between rows.

Usage:
  cd ~/Trading-and-Analysis-Platform && .venv/bin/python backend/scripts/diag_symbol_flip.py --symbol GLD --days 2
"""
from __future__ import annotations
import argparse
import os
import sys
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
    return getattr(v, "value", v)


def _s(v, n=None):
    out = "-" if v is None else str(_enum(v))
    return out[:n] if n else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GLD")
    ap.add_argument("--days", type=int, default=2)
    args = ap.parse_args()
    sym = args.symbol.upper()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    rows = list(db["bot_trades"].find(
        {"symbol": sym, "created_at": {"$gte": cutoff}}, {"_id": 0},
    ).sort("created_at", -1))

    print("\n" + "=" * 100)
    print(f"1. bot_trades for {sym} — last {args.days}d — {len(rows)} row(s) (newest first)")
    print("=" * 100)
    for t in rows:
        print(f"\n  id={_s(t.get('id'))}  dir={_s(t.get('direction'))}"
              f"  shares={_s(t.get('shares'))}/{_s(t.get('remaining_shares'))}rem"
              f"  status={_s(t.get('status'))}  entered_by={_s(t.get('entered_by'))}")
        print(f"    setup={_s(t.get('setup_type'))}  style={_s(t.get('trade_style'))}"
              f"  tf={_s(t.get('timeframe'))}  sim={_s(t.get('simulated'))}")
        print(f"    entry={_s(t.get('entry_price'))}  fill={_s(t.get('fill_price'))}"
              f"  stop={_s(t.get('stop_price'))}  targets={_s(t.get('target_prices'))}")
        print(f"    stop_oid={_s(t.get('stop_order_id'))}"
              f"  tgt_oid={_s(t.get('target_order_id'))}"
              f"  tgt_oids={_s(t.get('target_order_ids'))}")
        so = t.get("scale_out_config") or {}
        legs = so.get("m0_legs") or []
        if legs:
            for l in legs:
                print(f"      m0_leg L{(l.get('idx') or 0) + 1}: {_s(l.get('qty'))}sh"
                      f" stop_oid={_s(l.get('stop_order_id'))}"
                      f" tgt={_s(l.get('target_px'))} status={_s(l.get('status'))}")
        print(f"    created={_s(t.get('created_at'), 19)}"
              f"  executed={_s(t.get('executed_at'), 19)}"
              f"  closed={_s(t.get('closed_at'), 19)}")
        print(f"    close_reason={_s(t.get('close_reason'))}"
              f"  realized_pnl={_s(t.get('realized_pnl'))}"
              f"  net_pnl={_s(t.get('net_pnl'))}")

    print("\n" + "=" * 100)
    print(f"2. bracket_lifecycle_events for {sym} — last {args.days}d")
    print("=" * 100)
    evs = list(db["bracket_lifecycle_events"].find(
        {"symbol": sym}, {"_id": 0},
    ).sort([("ts", -1), ("created_at", -1)]).limit(40))
    if not evs:
        print("  (none)")
    for e in reversed(evs):
        ts = _s(e.get("ts") or e.get("created_at"), 19)
        print(f"  {ts}  phase={_s(e.get('phase'))} ok={_s(e.get('success'))}"
              f" trade={_s(e.get('trade_id'), 8)} reason={_s(e.get('reason'))}"
              f" bot_rem={_s(e.get('bot_remaining_shares'))}"
              f" ib_qty={_s(e.get('ib_position_qty'))}")

    print("\n" + "=" * 100)
    print("3. Flip detection across rows (chronological)")
    print("=" * 100)
    chron = sorted(rows, key=lambda t: str(t.get("created_at")))
    prev_dir = None
    total_pnl = 0.0
    for t in chron:
        d = str(_enum(t.get("direction")) or "?").lower()
        pnl = t.get("realized_pnl") or t.get("net_pnl") or 0
        try:
            total_pnl += float(pnl)
        except (TypeError, ValueError):
            pass
        flag = ""
        if prev_dir and d != prev_dir:
            flag = "  ⚠️ DIRECTION FLIP vs previous row"
        prev_dir = d
        print(f"  {_s(t.get('created_at'), 19)}  {d:5s} {_s(t.get('shares')):>5s}sh"
              f"  {_s(t.get('status')):10s} by={_s(t.get('entered_by'), 20):20s}"
              f" pnl={_s(pnl)}{flag}")
    print(f"\n  Σ realized pnl across rows: {total_pnl:+.2f}")


if __name__ == "__main__":
    main()
