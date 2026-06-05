#!/usr/bin/env python3
"""
rebuild_strategy_stats_clean.py  —  v19.34.275
==============================================
Recompute the per-setup `strategy_stats` (the win-rate / EV feed the Smart
Filter and TQS setup pillar read) from the authoritative `bot_trades`
ledger, applying the trade-outcome HYGIENE SSOT so reconciliation /
phantom / imported ARTIFACTS never grade a real strategy.

Why: `enhanced_scanner._strategy_stats` counted artifact closes (phantom
sweeps, reconciled_excess/orphan, operator flattens) as genuine strategy
outcomes — dragging real setups' win-rates down and poisoning the gate
(see the 2026-06-05 CRM reconcile incident: 222 artifact "trades").

Safe + reversible:
  • DRY-RUN by default — prints old-vs-new win-rate per setup, nothing written.
  • --commit backs up the whole `strategy_stats` collection to
    `strategy_stats_backup_<ts>` BEFORE writing, then upserts clean docs and
    drops artifact-setup rows.
  • After --commit, hot-reload the running bot with NO restart:
        curl -s -X POST http://localhost:8001/api/trading-bot/reload-strategy-stats

Usage (venv python on the DGX):
    python scripts/rebuild_strategy_stats_clean.py            # dry-run
    python scripts/rebuild_strategy_stats_clean.py --days 60  # window
    python scripts/rebuild_strategy_stats_clean.py --commit   # apply (+backup)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
load_dotenv(_BACKEND / ".env")

from dataclasses import asdict  # noqa: E402
from services.enhanced_scanner import StrategyStats  # noqa: E402
from services.trade_outcome_hygiene import classify_close  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")

_ARTIFACT_SETUP_SUBS = ("reconciled", "imported", "phantom")


def _base_setup(setup_type: str) -> str:
    """Match enhanced_scanner's base-setup key (strip _long/_short)."""
    return (setup_type or "").split("_long")[0].split("_short")[0]


def compute_clean_stats(trades):
    """Pure aggregation: closed bot_trades -> {base_setup: StrategyStats}.

    Applies classify_close(); artifact closes are excluded and tallied by
    reason tag. Returns (stats_by_setup, excluded_by_tag).
    """
    agg = {}
    excluded = {}
    # Chronological so r_outcomes / ev_trend mirror live ordering.
    for t in sorted(trades, key=lambda x: x.get("closed_at") or ""):
        setup_raw = t.get("setup_type") or ""
        genuine, tag = classify_close(
            close_reason=t.get("close_reason"),
            entered_by=t.get("entered_by", "") or "",
            entry_price=t.get("entry_price"),
            exit_price=t.get("exit_price"),
            net_pnl=t.get("net_pnl"),
            hold_seconds=t.get("hold_seconds"),
            setup_type=setup_raw,
            direction=t.get("direction"),
            stop_price=t.get("stop_price"),
            target_prices=t.get("target_prices"),
            realized_pnl=t.get("net_pnl"),
            shares=t.get("shares"),
        )
        if not genuine:
            excluded[tag] = excluded.get(tag, 0) + 1
            continue

        base = _base_setup(setup_raw)
        if not base:
            excluded["no_setup_type"] = excluded.get("no_setup_type", 0) + 1
            continue

        a = agg.setdefault(base, {
            "triggered": 0, "won": 0, "lost": 0, "total_pnl": 0.0,
            "sum_win": 0.0, "sum_loss": 0.0, "r_list": [],
            "grades": {"A": 0, "B": 0, "C": 0},
        })
        net = float(t.get("net_pnl") or 0.0)
        risk = t.get("risk_amount")
        try:
            risk = float(risk)
        except (TypeError, ValueError):
            risk = 0.0
        if risk and risk > 0:
            r = round(net / risk, 4)
        else:
            r = 1.0 if net > 0 else (-1.0 if net < 0 else 0.0)

        a["triggered"] += 1
        a["total_pnl"] += net
        a["r_list"].append(r)
        if net > 0:
            a["won"] += 1
            a["sum_win"] += net
        else:
            a["lost"] += 1
            a["sum_loss"] += net  # negative
        g = str(t.get("quality_grade") or t.get("trade_grade") or "B")[:1].upper()
        a["grades"][g if g in ("A", "B") else "C"] += 1

    stats_by_setup = {}
    for base, a in agg.items():
        st = StrategyStats(setup_type=base)
        st.alerts_triggered = a["triggered"]
        st.alerts_won = a["won"]
        st.alerts_lost = a["lost"]
        st.total_pnl = round(a["total_pnl"], 2)
        st.avg_win = round(a["sum_win"] / a["won"], 4) if a["won"] else 0.0
        st.avg_loss = round(a["sum_loss"] / a["lost"], 4) if a["lost"] else 0.0
        st.r_outcomes = a["r_list"][-100:]
        st.a_grade_count = a["grades"]["A"]
        st.b_grade_count = a["grades"]["B"]
        st.c_grade_count = a["grades"]["C"]
        st.update_win_rate()  # sets win_rate, profit_factor, expected_value_r
        stats_by_setup[base] = st
    return stats_by_setup, excluded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Backup + write clean stats (default: dry-run).")
    ap.add_argument("--days", type=int, default=0,
                    help="Only consider trades closed in the last N days (0=all).")
    args = ap.parse_args()

    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    q = {"status": {"$in": ["closed", "CLOSED"]}}
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        q["closed_at"] = {"$gte": cutoff}
    trades = list(db.bot_trades.find(q, {
        "setup_type": 1, "close_reason": 1, "entered_by": 1, "direction": 1,
        "entry_price": 1, "exit_price": 1, "net_pnl": 1, "hold_seconds": 1,
        "stop_price": 1, "target_prices": 1, "shares": 1, "risk_amount": 1,
        "quality_grade": 1, "trade_grade": 1, "closed_at": 1, "_id": 0,
    }))
    print(f"Loaded {len(trades)} closed bot_trades"
          f"{f' (last {args.days}d)' if args.days else ''}\n")

    clean, excluded = compute_clean_stats(trades)

    # current persisted stats for before/after.
    old = {d["setup_type"]: d for d in db.strategy_stats.find(
        {}, {"_id": 0, "setup_type": 1, "win_rate": 1, "alerts_triggered": 1})}

    print(f"{'setup':<26}{'old n':>7}{'old WR':>9}{'new n':>7}{'new WR':>9}{'new EV(R)':>11}")
    print("-" * 69)
    for base in sorted(clean, key=lambda k: -clean[k].alerts_triggered):
        st = clean[base]
        o = old.get(base, {})
        owr = o.get("win_rate")
        on = o.get("alerts_triggered")
        print(f"{base:<26}"
              f"{(on if on is not None else '-'):>7}"
              f"{(f'{owr*100:.1f}%' if isinstance(owr,(int,float)) else '-'):>9}"
              f"{st.alerts_triggered:>7}"
              f"{st.win_rate*100:>8.1f}%"
              f"{st.expected_value_r:>11.2f}")

    total_excl = sum(excluded.values())
    print(f"\nExcluded {total_excl} artifact closes (not graded):")
    for tag, n in sorted(excluded.items(), key=lambda kv: -kv[1]):
        print(f"   {n:>5}  {tag}")

    # artifact-setup rows currently polluting strategy_stats
    artifact_rows = [d["setup_type"] for d in db.strategy_stats.find(
        {}, {"_id": 0, "setup_type": 1})
        if any(s in (d.get("setup_type") or "").lower() for s in _ARTIFACT_SETUP_SUBS)]
    if artifact_rows:
        print(f"\nArtifact-setup rows to remove from strategy_stats: {artifact_rows}")

    if not args.commit:
        print("\nDRY-RUN — nothing written. Re-run with --commit to apply "
              "(a backup is taken first).")
        client.close()
        return

    # --- commit path: backup, then write ---
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"strategy_stats_backup_{ts}"
    existing = list(db.strategy_stats.find({}))
    if existing:
        db[backup_name].insert_many(existing)
    print(f"\nBacked up {len(existing)} docs -> {backup_name}")

    written = 0
    for base, st in clean.items():
        db.strategy_stats.update_one(
            {"setup_type": base}, {"$set": asdict(st)}, upsert=True)
        written += 1
    removed = db.strategy_stats.delete_many(
        {"setup_type": {"$regex": "reconciled|imported|phantom", "$options": "i"}})
    print(f"Wrote {written} clean setup rows; removed {removed.deleted_count} "
          f"artifact-setup rows.")
    print("\n✅ Done. Hot-reload the running bot (NO restart):")
    print("   curl -s -X POST http://localhost:8001/api/trading-bot/reload-strategy-stats")
    print(f"\nRollback if needed: restore docs from `{backup_name}`.")
    client.close()


if __name__ == "__main__":
    main()
