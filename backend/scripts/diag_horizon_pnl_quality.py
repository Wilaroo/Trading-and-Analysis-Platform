#!/usr/bin/env python3
"""
diag_horizon_pnl_quality.py  (read-only)
========================================
Validation probe before deciding the slot-cap (C) and decay (D):

  1. Per-horizon P&L QUALITY (genuine closes): n, win%, total, MEDIAN,
     and top-3-trade share of total  -> exposes outlier skew (is the
     'position +$154k' real breadth or 1-2 monster trades?).

  2. BOT-EDGE vs ADOPTED: split each horizon by entered_by /
     close_reason into 'bot' (the bot's own entries) vs
     'reconciled/external/adopted' (your externally-managed IB
     positions the bot merely attributed). Re-state P&L for BOT-ONLY.

  3. SCALP raw close_reason counts -> decode the 48% 'other' bucket.

  4. TOP trade_drop gates (last 7d) -> what is the bot rejecting
     ~100k times, and is 'max_open_positions' actually material?

Read-only. Connects via MONGO_URL + DB_NAME from backend/.env.

Usage (repo root):  curl -s <url> | python3 - --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env", Path(__file__).resolve().parents[1] / ".env"):
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


HORIZONS = ("scalp", "intraday", "swing", "position", "investment")
ARTIFACT = (
    "consolidated", "stale_pending", "phantom", "symbol_cooldown",
    "guardrail_veto", "operator_flatten_suppression", "intent_already_pending",
    "rejection_cooldown", "broker_rejected", "execution_exception",
    "paper_phase", "simulation_phase", "auto_reaper", "vetoed",
)
ADOPTED_HINTS = ("reconcil", "external", "excess", "adopt", "orphan", "ib_only", "ib-only")


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def is_adopted(t):
    blob = (str(t.get("entered_by") or "") + " " + str(t.get("close_reason") or "")
            + " " + str(t.get("source") or "")).lower()
    return any(h in blob for h in ADOPTED_HINTS)


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}},
        {"_id": 0, "timeframe": 1, "trade_type": 1, "scan_tier": 1, "status": 1,
         "close_reason": 1, "net_pnl": 1, "realized_pnl": 1, "entered_by": 1,
         "source": 1, "exit_price": 1, "symbol": 1},
    )
    trades = []
    for t in cur:
        st = str(_enum(t.get("status")) or "").lower()
        if st in ("open", "pending", "vetoed", "rejected"):
            continue
        if t.get("exit_price") in (None, 0) and t.get("net_pnl") in (None, 0):
            continue
        if any(a in (t.get("close_reason") or "").lower() for a in ARTIFACT):
            continue
        trades.append(t)

    print("\n" + "=" * 74)
    print(f"HORIZON P&L QUALITY — last {args.days}d — {len(trades)} genuine closes")
    print("=" * 74)
    if not trades:
        print("No genuine closed trades.")
        return

    by_h = defaultdict(list)
    for t in trades:
        by_h[horizon(t)].append(t)

    print(f"\n{'horizon':<10}{'n':>5}{'win%':>6}{'total$':>12}{'median$':>10}"
          f"{'top3share':>11}{'  bot-only total$ (n)'}")
    for h in list(HORIZONS) + ["unknown"]:
        rows = by_h.get(h)
        if not rows:
            continue
        pnls = [_f(r.get("net_pnl") or r.get("realized_pnl")) for r in rows]
        n = len(rows)
        wins = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        top3 = sum(sorted(pnls, reverse=True)[:3])
        top3share = (top3 / total * 100) if total else 0
        bot_rows = [r for r in rows if not is_adopted(r)]
        bot_pnls = [_f(r.get("net_pnl") or r.get("realized_pnl")) for r in bot_rows]
        print(f"{h:<10}{n:>5}{wins/n*100:>5.0f}%{total:>12,.0f}{median(pnls):>10,.0f}"
              f"{top3share:>10.0f}%{sum(bot_pnls):>12,.0f} ({len(bot_rows)})")

    # adopted vs bot breakdown
    adopted = [t for t in trades if is_adopted(t)]
    print(f"\nADOPTED/reconciled/external rows: {len(adopted)}/{len(trades)} "
          f"({len(adopted)/len(trades)*100:.0f}%)  "
          f"total$={sum(_f(t.get('net_pnl') or t.get('realized_pnl')) for t in adopted):,.0f}")
    print("  -> if this $ is large, the headline horizon P&L is YOUR positions, not the bot's edge.")

    # scalp raw close reasons
    print("\n" + "-" * 74)
    print("SCALP raw close_reason counts (decode the 'other' bucket)")
    print("-" * 74)
    scc = Counter((t.get("close_reason") or "(none)") for t in by_h.get("scalp", []))
    for cr, c in scc.most_common(20):
        print(f"  {c:>4}  {cr}")

    # top drop gates
    print("\n" + "-" * 74)
    print("TOP trade_drop gates (whole collection, TTL ~7d)")
    print("-" * 74)
    try:
        gates = Counter()
        for d in db["trade_drops"].find({}, {"_id": 0, "gate": 1, "reason_code": 1, "reason": 1}):
            g = d.get("gate") or d.get("reason_code") or d.get("reason") or "(unknown)"
            gates[str(g)] += 1
        tot = sum(gates.values())
        for g, c in gates.most_common(20):
            print(f"  {c:>7} ({c/tot*100:4.1f}%)  {g}")
        print(f"  total drops: {tot}")
    except Exception as e:
        print("  trade_drops read failed:", e)

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
