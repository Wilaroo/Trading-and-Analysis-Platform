"""
Trade Execution Health Monitor (2026-04-21)
===========================================

Purpose
-------
Every closed trade has an intended risk (1R = |entry - stop|) and an actual
realized outcome (|exit - entry|). The ratio of |actual_R| to 1 is a direct
measure of whether stops are being HONORED at IB.

If a trade exits 10× past its stop distance, either:
  - No STP child order was placed at IB (bot crashed / pusher disconnected
    between entry fill and stop placement)
  - IB accepted the stop but rejected it silently (rare)
  - The trade was manually closed at a huge loss long after stop should've fired

This service scans closed bot_trades, computes per-trade "stop honor ratio",
and surfaces systemic execution failures to the gate / dashboard.

Design goals
------------
- Pure compute over Mongo — no bot state dependency
- Idempotent: safe to run on a cron, attaches a `stop_honored` flag to docs
- Surfaces both per-trade flags AND aggregate session-level alerts
- Drives a live alert if >N% of the last M trades blew past 1R

Usage
-----
    from services.trade_execution_health import TradeExecutionHealth

    health = TradeExecutionHealth(db)
    report = await health.audit_recent_trades(hours=24)
    if report["alert_level"] == "critical":
        # N% of recent trades blew past stop — disable trading
        ...

CLI
---
    PYTHONPATH=backend python backend/services/trade_execution_health.py
    PYTHONPATH=backend python backend/services/trade_execution_health.py --hours 168
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Pure helpers (unit-tested) ────────────────────────────────────────────

@dataclass
class StopHonorResult:
    """Per-trade stop-honor analysis."""
    trade_id: str
    symbol: str
    setup_type: str
    direction: str
    entry: float
    stop: float
    exit: float
    intended_1R: float       # |entry - stop|
    realized_R_signed: float # Signed R outcome (+win / -loss)
    realized_R_abs: float    # Absolute magnitude
    blew_past_stop: bool     # True if |realized_R| > STOP_HONOR_THRESHOLD on a LOSS
    slippage_ratio: float    # realized_R_abs / 1.0 (only meaningful on losers)


STOP_HONOR_THRESHOLD = 1.5  # Losers beyond 1.5R = stop failure
CRITICAL_FAILURE_RATE = 0.15  # >15% of recent trades blowing past stop = CRITICAL
WARNING_FAILURE_RATE = 0.05   # >5% = WARNING


def analyze_stop_honor(
    entry: float,
    stop: float,
    exit_: float,
    direction: str,
    trade_id: str = "?",
    symbol: str = "?",
    setup_type: str = "?",
) -> Optional[StopHonorResult]:
    """Classify a single closed trade's stop-honor behavior.

    Returns None if inputs are degenerate (missing prices, zero risk).
    """
    if entry is None or stop is None or exit_ is None:
        return None
    try:
        e, s, x = float(entry), float(stop), float(exit_)
    except (TypeError, ValueError):
        return None
    if e <= 0 or s <= 0 or x <= 0:
        return None

    dir_lower = (direction or "").lower()
    is_long = dir_lower in ("long", "buy", "up")
    is_short = dir_lower in ("short", "sell", "down")
    if not (is_long or is_short):
        return None

    intended_risk = abs(e - s)
    if intended_risk == 0:
        return None

    # Signed R:  positive = winner,  negative = loser
    if is_long:
        realized_R_signed = (x - e) / intended_risk
    else:
        realized_R_signed = (e - x) / intended_risk

    realized_abs = abs(realized_R_signed)
    # Stop-honor rule: a LOSER that went > threshold past stop indicates execution failure.
    # (Winners beyond target don't count — those ran into the profit side.)
    blew_past_stop = (
        realized_R_signed < 0 and realized_abs > STOP_HONOR_THRESHOLD
    )

    return StopHonorResult(
        trade_id=trade_id,
        symbol=symbol,
        setup_type=setup_type,
        direction=dir_lower,
        entry=e, stop=s, exit=x,
        intended_1R=intended_risk,
        realized_R_signed=round(realized_R_signed, 3),
        realized_R_abs=round(realized_abs, 3),
        blew_past_stop=blew_past_stop,
        slippage_ratio=round(realized_abs, 3) if blew_past_stop else 0.0,
    )


@dataclass
class ExecutionHealthReport:
    window_hours: int
    n_closed_trades: int
    n_honored: int
    n_failed: int
    failure_rate: float
    alert_level: str                                # "ok" | "warning" | "critical"
    worst_offenders: List[StopHonorResult] = field(default_factory=list)
    failure_by_setup: Dict[str, int] = field(default_factory=dict)
    failure_by_symbol: Dict[str, int] = field(default_factory=dict)
    total_R_bled: float = 0.0                       # Aggregate excess R beyond intended

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_hours": self.window_hours,
            "n_closed_trades": self.n_closed_trades,
            "n_honored": self.n_honored,
            "n_failed": self.n_failed,
            "failure_rate": round(self.failure_rate, 4),
            "alert_level": self.alert_level,
            "total_R_bled": round(self.total_R_bled, 2),
            "worst_offenders": [r.__dict__ for r in self.worst_offenders],
            "failure_by_setup": self.failure_by_setup,
            "failure_by_symbol": self.failure_by_symbol,
        }


def classify_alert_level(failure_rate: float, n_closed: int) -> str:
    """Decide alert level based on recent failure rate.

    Requires at least 5 trades in the window — too few to trust the signal otherwise.
    """
    if n_closed < 5:
        return "insufficient_data"
    if failure_rate >= CRITICAL_FAILURE_RATE:
        return "critical"
    if failure_rate >= WARNING_FAILURE_RATE:
        return "warning"
    return "ok"


# ── Service class (orchestration) ─────────────────────────────────────────

class TradeExecutionHealth:
    """Analyze Mongo bot_trades for stop-execution failures."""

    def __init__(self, db):
        self._db = db

    def audit_recent_trades(self, hours: int = 24,
                            top_n: int = 10) -> ExecutionHealthReport:
        """Scan closed trades from the last N hours and produce a health report."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Use closed_at if available, otherwise last_updated
        query = {
            "status": {"$in": ["closed", "closed_manual"]},
            "exit_price": {"$ne": None},
            "$or": [
                {"closed_at": {"$gte": cutoff}},
                {"last_updated": {"$gte": cutoff}},
            ],
        }

        results: List[StopHonorResult] = []
        for doc in self._db["bot_trades"].find(
            query,
            {"_id": 0, "id": 1, "symbol": 1, "setup_type": 1, "direction": 1,
             "entry_price": 1, "stop_price": 1, "exit_price": 1},
        ):
            r = analyze_stop_honor(
                doc.get("entry_price"), doc.get("stop_price"),
                doc.get("exit_price"), doc.get("direction"),
                trade_id=doc.get("id", "?"),
                symbol=doc.get("symbol", "?"),
                setup_type=doc.get("setup_type", "?"),
            )
            if r:
                results.append(r)

        failures = [r for r in results if r.blew_past_stop]
        failure_rate = (len(failures) / len(results)) if results else 0.0

        by_setup: Dict[str, int] = {}
        by_symbol: Dict[str, int] = {}
        for f in failures:
            by_setup[f.setup_type] = by_setup.get(f.setup_type, 0) + 1
            by_symbol[f.symbol] = by_symbol.get(f.symbol, 0) + 1

        total_bled = sum(
            (r.realized_R_abs - 1.0) for r in failures  # Excess beyond 1R intended
        )

        return ExecutionHealthReport(
            window_hours=hours,
            n_closed_trades=len(results),
            n_honored=len(results) - len(failures),
            n_failed=len(failures),
            failure_rate=failure_rate,
            alert_level=classify_alert_level(failure_rate, len(results)),
            worst_offenders=sorted(failures, key=lambda r: r.realized_R_abs,
                                   reverse=True)[:top_n],
            failure_by_setup=by_setup,
            failure_by_symbol=by_symbol,
            total_R_bled=total_bled,
        )

    def flag_trade_docs(self, hours: int = 24) -> int:
        """Write `stop_honored` boolean onto bot_trades docs for frontend/dashboard use.

        Idempotent — overwrites existing flag.
        Returns number of docs updated.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        updated = 0
        for doc in self._db["bot_trades"].find({
            "status": {"$in": ["closed", "closed_manual"]},
            "exit_price": {"$ne": None},
            "$or": [
                {"closed_at": {"$gte": cutoff}},
                {"last_updated": {"$gte": cutoff}},
            ],
        }, {"_id": 1, "entry_price": 1, "stop_price": 1, "exit_price": 1,
            "direction": 1}):
            r = analyze_stop_honor(
                doc.get("entry_price"), doc.get("stop_price"),
                doc.get("exit_price"), doc.get("direction"),
            )
            if r:
                self._db["bot_trades"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {
                        "stop_honored": not r.blew_past_stop,
                        "realized_R_signed": r.realized_R_signed,
                    }},
                )
                updated += 1
        return updated


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli():
    from pymongo import MongoClient
    from dotenv import load_dotenv

    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--flag", action="store_true",
                    help="Write stop_honored flag onto each trade doc.")
    args = ap.parse_args()

    # Load .env from backend dir
    for env_path in (".env", "backend/.env", "../backend/.env"):
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break

    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    health = TradeExecutionHealth(db)

    report = health.audit_recent_trades(hours=args.hours)
    print(f"\n{'=' * 70}")
    print(f"TRADE EXECUTION HEALTH — last {args.hours}h")
    print(f"{'=' * 70}")
    print(f"  Closed trades    : {report.n_closed_trades}")
    print(f"  Stops HONORED    : {report.n_honored}")
    print(f"  Stops FAILED     : {report.n_failed}  ({report.failure_rate:.1%})")
    print(f"  Alert level      : {report.alert_level.upper()}")
    print(f"  Total R bled     : {report.total_R_bled:+.2f}R (beyond intended 1R)")

    if report.failure_by_setup:
        print("\n  Failures by setup:")
        for setup, n in sorted(report.failure_by_setup.items(),
                                key=lambda kv: -kv[1])[:10]:
            print(f"    {setup:<28} {n}")

    if report.worst_offenders:
        print("\n  Worst offenders (top 10):")
        for r in report.worst_offenders[:10]:
            print(f"    {r.symbol:<6} {r.direction:<5} {r.setup_type:<22} "
                  f"entry={r.entry:>8.2f} stop={r.stop:>8.2f} exit={r.exit:>8.2f} "
                  f"realized={r.realized_R_signed:+.1f}R")

    if args.flag:
        n = health.flag_trade_docs(hours=args.hours)
        print(f"\n[flag] Wrote stop_honored=? onto {n} docs.")
    print()


if __name__ == "__main__":
    _cli()
