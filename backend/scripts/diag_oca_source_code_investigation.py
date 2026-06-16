#!/usr/bin/env python3
"""diag_oca_source_code_investigation.py  —  READ-ONLY  (2026-06-16)

Finds the SOURCE CODE path that handles IB-OCA-external fill notifications
and writes the broken sentinel close_reason='oca_closed_externally_v19_31'
+ net_pnl=-$1.00 to bot_trades. Goal: identify the exact file/function
that needs the fix.

Read-only investigation across:
  1. The actual data: today's 4 OCA-closed trades — full doc + their
     `realized_pnl` (which IS correct per UI) vs `net_pnl` (broken).
     Proves where the divergence happens.
  2. ib_executions cross-ref for today's 4 closes — confirms the exec
     was recorded properly (so IB callback path works).
  3. Code grep for the writers of the broken fields:
       • `oca_closed_externally_v19_31` literal
       • `net_pnl.*-1` or `net_pnl=.*1\\.0`
       • OCA fill callback / handler
  4. Code grep for the UI's PnL source (the endpoint that returns
     +$137.12 for SATS) — usually /api/v5/trades or similar.

Output: file:line list of every code site to consider patching.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

ET = ZoneInfo("America/New_York")
REPO = os.path.expanduser("~/Trading-and-Analysis-Platform")
BACKEND = os.path.join(REPO, "backend")


def hr(t):
    print("\n" + "=" * 100 + f"\n  {t}\n" + "=" * 100)


def _grep(pattern, path, extras=None):
    cmd = ["grep", "-rnE", "--include=*.py", pattern, path]
    if extras:
        cmd[1] = "-" + cmd[1].lstrip("-") + extras
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return [ln for ln in out.stdout.splitlines() if ln.strip()]
    except Exception as e:
        return [f"(grep error: {e})"]


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    now_utc = datetime.now(timezone.utc)
    today_open = now_utc.astimezone(ET).replace(
        hour=9, minute=30, second=0, microsecond=0).astimezone(timezone.utc).isoformat()

    # ── Section 1 — today's 4 broken closes: full forensics ──────────
    hr("Section 1 — Today's OCA-closed trades: realized_pnl vs net_pnl divergence")
    closes = list(db["bot_trades"].find(
        {"status": "closed",
         "closed_at": {"$gte": today_open},
         "close_reason": "oca_closed_externally_v19_31"},
        {"_id": 0}))
    print(f"  {len(closes)} OCA-closed trades today\n")
    interesting = (
        "id", "symbol", "direction", "shares",
        "entry_price", "fill_price", "exit_price",
        "stop_price", "target_prices", "target_order_ids",
        "entry_order_id", "stop_order_id",
        "executed_at", "closed_at",
        "realized_pnl", "net_pnl", "pnl_pct",
        "total_commissions", "commission_per_share",
        "close_reason", "setup_type", "trade_style",
    )
    for t in closes:
        print(f"\n  --- {t.get('symbol')} (id={t.get('id')}) ---")
        for k in interesting:
            v = t.get(k, "<missing>")
            if isinstance(v, list) and len(v) > 4:
                v = f"[{len(v)} items: {v[:3]}...]"
            print(f"    {k:>22} : {v}")
        # Back-calc what net_pnl SHOULD be
        rp = t.get("realized_pnl")
        tc = t.get("total_commissions") or 0
        net_should = (rp - tc) if rp is not None else None
        print(f"    → net_pnl SHOULD BE  : {net_should}")
        print(f"    → net_pnl ACTUALLY IS: {t.get('net_pnl')}  (delta = "
              f"${(t.get('net_pnl') or 0) - (net_should or 0):+.2f})")

    # ── Section 2 — ib_executions cross-ref ──────────────────────────
    hr("Section 2 — ib_executions cross-ref for today's OCA closes")
    if "ib_executions" not in db.list_collection_names():
        print("  ib_executions collection missing.")
    else:
        for t in closes:
            sym = t.get("symbol")
            closed_at_str = t.get("closed_at") or ""
            ct = datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
            ws = (ct - timedelta(minutes=15)).isoformat()
            we = (ct + timedelta(minutes=15)).isoformat()
            execs = list(db["ib_executions"].find(
                {"symbol": sym,
                 "$or": [{"side": "SELL"}, {"action": "SELL"}],
                 "$and": [{"$or": [{"time": {"$gte": ws, "$lte": we}},
                                   {"exec_time": {"$gte": ws, "$lte": we}}]}]},
                {"_id": 0}))
            print(f"\n  {sym}: {len(execs)} SELL exec(s) within ±15m of close")
            for e in execs:
                price = e.get("price") or e.get("fill_price") or e.get("avg_price")
                oid = e.get("order_id")
                # Determine which leg
                stop_oid = t.get("stop_order_id")
                tgt_oids = [str(x) for x in (t.get("target_order_ids") or [])]
                leg = "?"
                if str(oid) == str(stop_oid):
                    leg = "STOP"
                elif str(oid) in tgt_oids:
                    leg = "TARGET"
                else:
                    # Check by price proximity
                    if t.get("target_prices"):
                        for i, tp in enumerate(t.get("target_prices")):
                            if tp and abs(price - tp) < 0.10:
                                leg = f"TARGET_{i+1}_BY_PRICE"
                                break
                    if leg == "?" and t.get("stop_price"):
                        if abs(price - t.get("stop_price")) < 0.10:
                            leg = "STOP_BY_PRICE"
                print(f"    exec @ ${price}  order_id={oid}  leg={leg}  "
                      f"realized_pnl_in_exec={e.get('realized_pnl')}")

    # ── Section 3 — code grep: writers of the broken fields ──────────
    hr("Section 3 — Code locations writing 'oca_closed_externally_v19_31'")
    hits = _grep(r"oca_closed_externally_v19_31", BACKEND)
    for h in hits[:30]:
        print(f"  {h}")
    if len(hits) > 30:
        print(f"  ... +{len(hits)-30} more")

    hr("Section 4 — Code locations setting net_pnl to a sentinel value")
    hits = _grep(r"net_pnl\s*[=:]\s*-?1\.0", BACKEND)
    for h in hits[:20]:
        print(f"  {h}")
    hits2 = _grep(r"net_pnl\s*[=:]\s*['\"]-?1", BACKEND)
    for h in hits2[:10]:
        print(f"  {h}")

    hr("Section 5 — Code locations correctly computing net_pnl from realized_pnl")
    hits = _grep(r"net_pnl.*realized_pnl", BACKEND)
    for h in hits[:30]:
        print(f"  {h}")

    hr("Section 6 — IB-OCA fill callback / handler")
    for pat, label in (
        (r"def.*on_oca|def.*handle_oca|def.*oca_fill", "OCA-specific handlers"),
        (r"def.*orderStatus|def.*execDetails", "IB raw callbacks"),
        (r"def.*on_fill|def.*on_close|def.*close_trade", "close handlers"),
        (r"def.*reconcile.*close|def.*classify_close", "reconcile/classifier"),
    ):
        hits = _grep(pat, BACKEND)
        if hits:
            print(f"\n  {label}:")
            for h in hits[:8]:
                print(f"    {h}")

    hr("Section 7 — Closed-trade UI endpoint (what computes the UI's +$137.12)")
    for pat, label in (
        (r'@.*router.*trades.*closed|@.*get.*trades/closed', "closed-trades route"),
        (r"def.*get_closed_trades|def.*closed_trades_api", "closed-trades handler"),
        (r"net_pnl.*=.*realized.*comm|realized.*-.*total_commissions", "PnL compute"),
    ):
        hits = _grep(pat, BACKEND)
        if hits:
            print(f"\n  {label}:")
            for h in hits[:8]:
                print(f"    {h}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
