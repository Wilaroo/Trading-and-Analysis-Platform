#!/usr/bin/env python3
"""
audit_ups_31s_close.py — Forensic audit for `oca_closed_externally_v19_31`
sweeps that fire suspiciously close to the 30-second age floor.

The v19.31 phantom sweep in `services/position_manager.py` requires:
  1. bot tracks remaining_shares > 0
  2. IB shows 0 shares in BOTH directions for the symbol
  3. trade age >= 30 seconds (`age_s_e >= 30`)

A "31-second close" sits exactly on the boundary. Two possible causes:

  (a) LEGITIMATE target hit — OCA bracket fired at IB, the position
      genuinely closed, and the sweep correctly cleaned up the bot's
      record on the next manage-loop tick.
  (b) FALSE POSITIVE — IB pusher momentarily reported position=0
      during a snapshot rebuild OR realized PnL was missing/zero,
      so the bot swept a still-live position.

This script audits one symbol's `oca_closed_externally_v19_31` sweeps
and classifies each as LEGITIMATE / SUSPICIOUS / UNKNOWN by
correlating against IB execution tape (when available) and the
bot's own bracket lifecycle events.

Usage:
    python audit_ups_31s_close.py --symbol UPS --days 7
    python audit_ups_31s_close.py --symbol UPS --days 7 --json > ups.json

Output: pretty-printed report to stdout (or JSON with --json).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _to_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _fetch_db():
    from database import get_database
    db = get_database()
    if db is None:
        raise SystemExit(
            "❌ Could not resolve MongoDB. Run this from the DGX where "
            "MONGO_URL + DB_NAME are configured in /app/backend/.env."
        )
    return db


def _classify(trade, db):
    """Decide LEGITIMATE / SUSPICIOUS / UNKNOWN for a single trade."""
    findings = []
    score = 0  # negative = suspicious, positive = legitimate

    sym = (trade.get("symbol") or "").upper()
    executed_at = _to_dt(trade.get("executed_at"))
    closed_at = _to_dt(trade.get("closed_at"))
    if executed_at and closed_at:
        age_s = (closed_at - executed_at).total_seconds()
    else:
        age_s = None
    findings.append(f"age_s={age_s}")

    realized = float(trade.get("realized_pnl") or 0)
    findings.append(f"realized_pnl=${realized:+.2f}")

    fill_price = float(trade.get("fill_price") or trade.get("entry_price") or 0)
    target_prices = trade.get("target_prices") or []
    stop_price = float(trade.get("stop_price") or 0)
    direction = (trade.get("direction") or "").lower()

    # Heuristic 1: If realized_pnl is non-zero AND aligned with target
    # direction (long: positive, short: positive too because realized >0
    # means we covered profitably), it's a legitimate target hit.
    if realized > 0:
        score += 2
        findings.append("✓ realized_pnl > 0 (target likely hit)")
    elif realized < 0:
        score += 1  # Still legit close, just at a loss (stop hit)
        findings.append("✓ realized_pnl < 0 (stop likely hit)")
    elif realized == 0:
        score -= 2
        findings.append("⚠ realized_pnl is exactly $0 — pusher may have "
                        "been mid-snapshot at sweep time")

    # Heuristic 2: age tight to 30s = suspicious.
    if age_s is not None:
        if 30 <= age_s <= 35:
            score -= 2
            findings.append(f"⚠ age {age_s:.1f}s sits on the 30s floor")
        elif age_s > 60:
            score += 1
            findings.append(f"✓ age {age_s:.1f}s well past the floor")

    # Heuristic 3: IB execution tape correlation. Look for an opposite-
    # action fill at IB within ±60s of `closed_at` for this symbol.
    try:
        if closed_at:
            window_lo = (closed_at - timedelta(seconds=60)).isoformat()
            window_hi = (closed_at + timedelta(seconds=60)).isoformat()
            tape = list(db["ib_executions"].find(
                {
                    "symbol": sym,
                    "time": {"$gte": window_lo, "$lte": window_hi},
                },
                {"_id": 0, "symbol": 1, "side": 1, "shares": 1, "price": 1, "time": 1},
            ).limit(10))
            if tape:
                # Expect opposite side to the entry (long entry → SLD, short → BOT).
                expected_side = "SLD" if direction == "long" else "BOT"
                matching = [t for t in tape if (t.get("side") or "").upper().startswith(expected_side[:3])]
                if matching:
                    score += 3
                    findings.append(
                        f"✓ IB tape shows {len(matching)} {expected_side} "
                        f"execution(s) within ±60s of close — bracket fill confirmed"
                    )
                else:
                    score -= 1
                    findings.append(
                        f"⚠ {len(tape)} tape rows in window but none matched "
                        f"expected side {expected_side}"
                    )
            else:
                score -= 2
                findings.append("⚠ no IB execution tape in ±60s window — "
                                "no broker-side fill backs this close")
    except Exception as e:
        findings.append(f"  (tape lookup skipped: {e})")

    # Heuristic 4: bracket lifecycle event correlation.
    try:
        cursor = db["bracket_lifecycle_events"].find(
            {"trade_id": trade.get("id")}, {"_id": 0, "phase": 1, "reason": 1, "created_at": 1},
        )
        events = list(cursor)
        if events:
            findings.append(f"  {len(events)} bracket-lifecycle event(s): "
                            f"{[e.get('phase') or e.get('reason') for e in events][:6]}")
    except Exception:
        pass

    # Heuristic 5: target reached check (price comparison if we have data).
    if fill_price and target_prices and direction:
        try:
            pt = float(target_prices[0])
            if direction == "long" and pt and fill_price < pt:
                # Look for any quote ≥ pt within ±30s of close.
                # (Best-effort — if we have intraday cache.)
                pass  # placeholder; quote_history not always retained
        except Exception:
            pass

    if score >= 3:
        verdict = "LEGITIMATE"
    elif score <= -2:
        verdict = "SUSPICIOUS"
    else:
        verdict = "UNKNOWN"

    return {
        "trade_id": trade.get("id"),
        "symbol": sym,
        "direction": direction,
        "shares": trade.get("shares") or trade.get("original_shares"),
        "executed_at": str(trade.get("executed_at") or ""),
        "closed_at": str(trade.get("closed_at") or ""),
        "age_s": age_s,
        "fill_price": fill_price,
        "stop_price": stop_price,
        "target_prices": target_prices,
        "realized_pnl": realized,
        "verdict": verdict,
        "score": score,
        "findings": findings,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None,
                    help="Filter by symbol (e.g. UPS). Omit for all symbols.")
    ap.add_argument("--days", type=int, default=7,
                    help="Look back N days. Default 7.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    db = _fetch_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    query = {
        "close_reason": "oca_closed_externally_v19_31",
        "$or": [
            {"closed_at": {"$gte": cutoff}},
            {"executed_at": {"$gte": cutoff}},
        ],
    }
    if args.symbol:
        query["symbol"] = args.symbol.upper()

    cursor = db["bot_trades"].find(query, {"_id": 0}).sort("closed_at", -1)
    trades = list(cursor)
    if not trades:
        print(f"No `oca_closed_externally_v19_31` trades found in the last "
              f"{args.days} day(s)" + (f" for {args.symbol}" if args.symbol else "") + ".")
        return

    classified = [_classify(t, db) for t in trades]
    summary = {
        "total": len(classified),
        "LEGITIMATE": sum(1 for c in classified if c["verdict"] == "LEGITIMATE"),
        "SUSPICIOUS": sum(1 for c in classified if c["verdict"] == "SUSPICIOUS"),
        "UNKNOWN": sum(1 for c in classified if c["verdict"] == "UNKNOWN"),
    }

    if args.json:
        print(json.dumps({"summary": summary, "trades": classified}, indent=2, default=str))
        return

    print("\n=== oca_closed_externally_v19_31 audit ===")
    print(f"Window: last {args.days} day(s)" + (f", symbol={args.symbol}" if args.symbol else ""))
    print(f"Total: {summary['total']} | "
          f"LEGITIMATE: {summary['LEGITIMATE']} | "
          f"SUSPICIOUS: {summary['SUSPICIOUS']} | "
          f"UNKNOWN: {summary['UNKNOWN']}\n")

    for c in classified:
        marker = {"LEGITIMATE": "✅", "SUSPICIOUS": "🚨", "UNKNOWN": "❓"}.get(c["verdict"], "·")
        print(f"{marker} {c['verdict']}  {c['symbol']} {c['direction'].upper():<5} "
              f"{c['shares']}sh  age={c['age_s']:.1f}s  "
              f"realized=${c['realized_pnl']:+.2f}  trade_id={c['trade_id']}")
        for f in c["findings"]:
            print(f"      {f}")
        print()


if __name__ == "__main__":
    main()
