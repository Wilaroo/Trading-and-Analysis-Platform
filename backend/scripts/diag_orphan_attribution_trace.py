#!/usr/bin/env python3
"""
diag_orphan_attribution_trace.py  (read-only)
=============================================
Forensic timeline for "the bot initiated it but it shows as an ADOPTED IB
orphan" — e.g. MRSH squeeze / CEG gap_fade on 2026-06-04.

For each requested symbol it stitches a single time-ordered timeline across:
  - bot_trades        (every row: bot-originated AND reconciled/adopted)
  - order_queue       (what was actually submitted to IB + terminal state)
  - trade_drops       (silent execution drops by gate/reason)
  - bot_events        (reconcile/adopt/flatten events)

Goal: prove WHETHER a bot-originated bot_trade exists separate from the
adopted orphan (linkage break), and WHEN the orphan was adopted vs when the
bot fired/submitted — so we can fix the fill→bot_trade linkage instead of
synthesizing a wrong 2% bracket.

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:  curl -s <url> | python3 - --symbols MRSH,CEG --hours 12
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


def _ts(d, *keys):
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return ""


def _short(v, n=10):
    s = str(v or "")
    return s[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MRSH,CEG")
    ap.add_argument("--hours", type=int, default=12)
    args = ap.parse_args()
    _load_env()
    db = _db()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()

    for sym in syms:
        print("\n" + "=" * 78)
        print(f"SYMBOL {sym} — last {args.hours}h (since {cutoff[:19]})")
        print("=" * 78)

        # ── bot_trades ────────────────────────────────────────────────
        bts = list(db["bot_trades"].find(
            {"symbol": sym},
            {"_id": 0, "id": 1, "trade_id": 1, "status": 1, "setup_type": 1,
             "direction": 1, "entered_by": 1, "source": 1, "trade_type": 1,
             "timeframe": 1, "fill_price": 1, "entry_price": 1, "stop_price": 1,
             "target_prices": 1, "created_at": 1, "pre_submit_at": 1,
             "executed_at": 1, "closed_at": 1, "close_reason": 1,
             "alert_id": 1, "remaining_shares": 1, "shares": 1, "net_pnl": 1,
             "realized_pnl": 1}))
        # keep only rows touching the window (created/executed/closed within)
        def _recent(d):
            for k in ("created_at", "executed_at", "closed_at", "pre_submit_at"):
                if str(d.get(k) or "") >= cutoff:
                    return True
            return False
        bts = [d for d in bts if _recent(d)] or bts  # fall back to all if none recent
        print(f"\n  bot_trades rows: {len(bts)}")
        for d in sorted(bts, key=lambda x: _ts(x, "created_at", "executed_at")):
            print(f"    • id={_short(d.get('id') or d.get('trade_id'),8)} "
                  f"status={_enum(d.get('status'))} "
                  f"setup={d.get('setup_type')} dir={_enum(d.get('direction'))} "
                  f"sh={d.get('shares')}/{d.get('remaining_shares')}")
            print(f"        entered_by={d.get('entered_by')!r} source={d.get('source')!r} "
                  f"alert_id={_short(d.get('alert_id'),8)} type={d.get('trade_type')}")
            print(f"        entry={d.get('fill_price') or d.get('entry_price')} "
                  f"stop={d.get('stop_price')} tgt={d.get('target_prices')} "
                  f"close_reason={d.get('close_reason')}")
            print(f"        created={_short(_ts(d,'created_at'),19)} "
                  f"pre_submit={_short(_ts(d,'pre_submit_at'),19)} "
                  f"exec={_short(_ts(d,'executed_at'),19)} "
                  f"closed={_short(_ts(d,'closed_at'),19)}")

        # ── order_queue ───────────────────────────────────────────────
        try:
            oq = list(db["order_queue"].find(
                {"symbol": sym},
                {"_id": 0, "order_id": 1, "trade_id": 1, "status": 1,
                 "order_type": 1, "action": 1, "quantity": 1, "created_at": 1,
                 "updated_at": 1, "filled_at": 1}))
            oq = [d for d in oq if _ts(d, "created_at") >= cutoff] or oq[-10:]
            print(f"\n  order_queue rows: {len(oq)}")
            for d in sorted(oq, key=lambda x: _ts(x, "created_at")):
                print(f"    • oid={_short(d.get('order_id'),8)} "
                      f"trade_id={_short(d.get('trade_id'),8)} status={d.get('status')} "
                      f"{d.get('action')} {d.get('order_type')} q={d.get('quantity')} "
                      f"created={_short(_ts(d,'created_at'),19)} "
                      f"filled={_short(_ts(d,'filled_at','updated_at'),19)}")
        except Exception as e:
            print(f"  order_queue: query failed ({e})")

        # ── trade_drops ───────────────────────────────────────────────
        try:
            td = list(db["trade_drops"].find(
                {"symbol": sym}, {"_id": 0, "gate": 1, "reason": 1,
                                  "timestamp": 1, "ts": 1, "setup_type": 1}))
            td = [d for d in td if _ts(d, "timestamp", "ts") >= cutoff]
            print(f"\n  trade_drops rows: {len(td)}")
            from collections import Counter
            gc = Counter((d.get("gate"), d.get("reason")) for d in td)
            for (g, r), c in gc.most_common(12):
                print(f"    • gate={g} reason={r}  x{c}")
        except Exception as e:
            print(f"  trade_drops: query failed ({e})")

        # ── bot_events ────────────────────────────────────────────────
        try:
            be = list(db["bot_events"].find(
                {"symbol": sym}, {"_id": 0, "event_type": 1, "timestamp": 1,
                                  "shares": 1, "direction": 1}))
            be = [d for d in be if _ts(d, "timestamp") >= cutoff]
            print(f"\n  bot_events rows: {len(be)}")
            for d in sorted(be, key=lambda x: _ts(x, "timestamp")):
                print(f"    • {_short(_ts(d,'timestamp'),19)} {d.get('event_type')} "
                      f"dir={_enum(d.get('direction'))} sh={d.get('shares')}")
        except Exception as e:
            print(f"  bot_events: query failed ({e})")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
