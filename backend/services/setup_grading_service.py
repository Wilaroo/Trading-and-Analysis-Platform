"""
SetupGradingService — v19.34.113 (Feb 2026)
============================================

Per-setup_type performance scoreboard. Computes a daily snapshot per
(setup_type, trading_date) from `bot_trades` and surfaces a rolling
30-day grade card. Closes the A/B feedback loop on the v19.34.112
scalp ATR multiplier choices:

  • Without this service: we picked 0.4-0.5×ATR for scalps on
    judgement. If `nine_ema_scalp` is winning 65% but bleeding R
    via stop-outs, we won't know for weeks.
  • With this service: every EOD we re-compute the per-setup card.
    Week 1 we read the data; week 2 we tune the multipliers
    empirically. Auto-tune is INTENTIONALLY out of scope for v113 —
    operator stays in the loop until the formula is sanity-checked.

Data flow:
  1. EOD tick at 16:05 ET fires `compute_eod_grades(date=today)`.
  2. Service queries `bot_trades` where:
       - status = "closed"
       - closed_at in [date 00:00 ET, date 23:59:59 ET)
       - setup_type is non-empty
       - r_multiple is not None (filters out broken / partial rows)
     Groups by `setup_type`, computes the daily stats block, upserts
     into `setup_grade_records` keyed on (setup_type, trading_date).
  3. `get_rolling_grade(setup_type, days=30)` aggregates the last N
     daily records into a single rolling card.
  4. `get_all_rolling_grades(days=30)` returns one card per
     setup_type observed in the window.

Grade formula (intentionally readable, not Sharpe — operators tune
on intuition first, statistics second):

  • A+ → win_rate ≥ 60% AND avg_r ≥ 1.0
  • A  → win_rate ≥ 55% AND avg_r ≥ 0.7
  • B+ → win_rate ≥ 50% AND avg_r ≥ 0.5
  • B  → win_rate ≥ 45% AND avg_r ≥ 0.3
  • C  → avg_r ≥ 0.0  (breakeven setup, still earning the spread)
  • F  → avg_r < 0.0  (the setup is losing money — review or kill)

Minimum sample size = 5 trades. Below that → INSUFFICIENT_DATA. The
operator's UI surfaces "INSUFFICIENT_DATA" without blocking the
setup — rare setups still need a runway.

The service is read-mostly; the only write path is the EOD
upsert. We do NOT mutate `bot_trades` or `alert_outcomes`.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, asdict, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Collection name — single source of truth for the grade snapshots.
GRADE_COLLECTION = "setup_grade_records"

# Minimum sample size below which we refuse to assign a letter grade.
# Tunable via env to let the operator inspect low-sample setups
# during early-shakedown if desired.
MIN_TRADES_FOR_GRADE = 5

# Grade formula band edges. Centralized so tests can assert against
# the exact thresholds, and a future PR can swap to a richer formula
# (risk-adjusted, regime-conditioned, etc.) without touching callers.
GRADE_BANDS = [
    # (label, min_win_rate, min_avg_r)
    ("A+", 0.60, 1.0),
    ("A",  0.55, 0.7),
    ("B+", 0.50, 0.5),
    ("B",  0.45, 0.3),
    ("C",  0.00, 0.0),  # breakeven — must clear avg_r ≥ 0 to land here
]
# Failing band — anything below "C" thresholds lands on F.


def compute_letter_grade(
    trades_count: int,
    win_rate: float,
    avg_r: float,
    min_sample: int = MIN_TRADES_FOR_GRADE,
) -> str:
    """Pure function — given the three primary stats, return a letter.

    Pulled out so tests can lock the grade ladder independently of
    the IO-bound aggregation path.
    """
    if trades_count < min_sample:
        return "INSUFFICIENT_DATA"
    if avg_r < 0.0:
        return "F"
    for label, min_wr, min_r in GRADE_BANDS:
        if win_rate >= min_wr and avg_r >= min_r:
            return label
    return "F"


@dataclass
class SetupDailyStats:
    """One day's worth of stats for a single setup_type.

    Stored as a document in `setup_grade_records`. Key:
    (setup_type, trading_date) — unique per upsert.
    """
    setup_type: str
    trading_date: str  # "YYYY-MM-DD" (US/Eastern session date)
    trades_count: int
    wins: int
    losses: int
    breakevens: int
    win_rate: float
    avg_r: float
    median_r: float
    total_r: float
    worst_r: float
    best_r: float
    avg_mfe_r: float
    avg_mae_r: float
    avg_hold_seconds: float
    total_realized_pnl: float
    grade: str
    computed_at: str  # ISO timestamp of the snapshot generation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SetupRollingGrade:
    """Aggregated rolling-window view used by the V5 chip + API.

    Built on-the-fly from a set of `SetupDailyStats` rows in the
    window — never persisted, always recomputed so freshness reflects
    the last EOD tick.
    """
    setup_type: str
    window_days: int
    trades_count: int
    wins: int
    losses: int
    win_rate: float
    avg_r: float
    total_r: float
    worst_r: float
    best_r: float
    avg_mfe_r: float
    avg_mae_r: float
    avg_hold_seconds: float
    total_realized_pnl: float
    grade: str
    days_with_data: int
    last_trade_date: Optional[str]


class SetupGradingService:
    """Persistent grading + rolling-window service. Pure IO + math."""

    def __init__(self, db=None):
        self._db = db

    def _resolve_db(self):
        if self._db is not None:
            return self._db
        from database import get_database
        return get_database()

    # ───────────────────────── EOD computation ─────────────────────────

    def compute_eod_grades(self, trading_date: Optional[str] = None) -> Dict[str, Any]:
        """Walk closed bot_trades for `trading_date` (default = today
        US/Eastern), group by setup_type, upsert per-setup daily
        snapshot rows. Returns a summary of what was written.
        """
        from zoneinfo import ZoneInfo

        et = ZoneInfo("US/Eastern")
        if trading_date is None:
            trading_date = datetime.now(et).strftime("%Y-%m-%d")

        day_start_et = datetime.strptime(trading_date, "%Y-%m-%d").replace(tzinfo=et)
        day_end_et = day_start_et + timedelta(days=1)
        day_start_utc = day_start_et.astimezone(timezone.utc)
        day_end_utc = day_end_et.astimezone(timezone.utc)

        db = self._resolve_db()
        # Read closed trades inside the trading-day window.
        # `closed_at` is stored as ISO string in bot_trades; we filter
        # by the ISO range so a Mongo index on `closed_at` can help.
        cursor = db["bot_trades"].find(
            {
                "status": "closed",
                "closed_at": {
                    "$gte": day_start_utc.isoformat(),
                    "$lt": day_end_utc.isoformat(),
                },
                "setup_type": {"$exists": True, "$nin": [None, ""]},
            },
            {
                "_id": 0,
                "id": 1,
                "setup_type": 1,
                "realized_pnl": 1,
                "risk_amount": 1,
                "r_multiple": 1,
                "mfe_r": 1,
                "mae_r": 1,
                "executed_at": 1,
                "closed_at": 1,
            },
        )

        # Group by setup_type.
        by_setup: Dict[str, List[Dict[str, Any]]] = {}
        for trade in cursor:
            st = trade.get("setup_type")
            if not st:
                continue
            by_setup.setdefault(st, []).append(trade)

        summaries: List[Dict[str, Any]] = []
        for setup_type, trades in by_setup.items():
            stats = self._compute_daily_stats(setup_type, trading_date, trades)
            if stats is None:
                continue
            self._upsert_daily_stats(stats)
            summaries.append({
                "setup_type": setup_type,
                "trades_count": stats.trades_count,
                "grade": stats.grade,
                "avg_r": stats.avg_r,
                "win_rate": stats.win_rate,
            })

        result = {
            "trading_date": trading_date,
            "setups_graded": len(summaries),
            "summaries": summaries,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "[v19.34.113 EOD-GRADE] %s — graded %d setup_type(s)",
            trading_date, len(summaries),
        )
        return result

    def _compute_daily_stats(
        self,
        setup_type: str,
        trading_date: str,
        trades: List[Dict[str, Any]],
    ) -> Optional[SetupDailyStats]:
        """Aggregate one setup's daily trades into a SetupDailyStats."""
        # Filter rows missing a usable r_multiple. We prefer the stored
        # `r_multiple` field; if absent, derive from
        # realized_pnl / risk_amount (best-effort).
        clean: List[Dict[str, Any]] = []
        for t in trades:
            r = t.get("r_multiple")
            if r is None:
                pnl = t.get("realized_pnl")
                risk = t.get("risk_amount")
                if pnl is not None and risk and risk > 0:
                    r = float(pnl) / float(risk)
            if r is None:
                continue
            t = {**t, "r_multiple": float(r)}
            clean.append(t)

        if not clean:
            return None

        r_values = [t["r_multiple"] for t in clean]
        wins = sum(1 for r in r_values if r > 0)
        losses = sum(1 for r in r_values if r < 0)
        breakevens = sum(1 for r in r_values if r == 0)
        trades_count = len(r_values)
        win_rate = wins / trades_count if trades_count else 0.0
        avg_r = statistics.fmean(r_values)
        median_r = statistics.median(r_values)
        total_r = sum(r_values)
        worst_r = min(r_values)
        best_r = max(r_values)

        mfe_values = [float(t.get("mfe_r") or 0.0) for t in clean]
        mae_values = [float(t.get("mae_r") or 0.0) for t in clean]
        avg_mfe_r = statistics.fmean(mfe_values) if mfe_values else 0.0
        avg_mae_r = statistics.fmean(mae_values) if mae_values else 0.0

        hold_seconds: List[float] = []
        for t in clean:
            ex = t.get("executed_at") or t.get("entry_time")
            cl = t.get("closed_at") or t.get("exit_time")
            if ex and cl:
                try:
                    dt_ex = datetime.fromisoformat(ex.replace("Z", "+00:00"))
                    dt_cl = datetime.fromisoformat(cl.replace("Z", "+00:00"))
                    delta = (dt_cl - dt_ex).total_seconds()
                    if delta >= 0:
                        hold_seconds.append(delta)
                except Exception:
                    continue
        avg_hold_seconds = statistics.fmean(hold_seconds) if hold_seconds else 0.0

        total_realized_pnl = sum(float(t.get("realized_pnl") or 0.0) for t in clean)

        grade = compute_letter_grade(trades_count, win_rate, avg_r)

        return SetupDailyStats(
            setup_type=setup_type,
            trading_date=trading_date,
            trades_count=trades_count,
            wins=wins,
            losses=losses,
            breakevens=breakevens,
            win_rate=round(win_rate, 4),
            avg_r=round(avg_r, 4),
            median_r=round(median_r, 4),
            total_r=round(total_r, 4),
            worst_r=round(worst_r, 4),
            best_r=round(best_r, 4),
            avg_mfe_r=round(avg_mfe_r, 4),
            avg_mae_r=round(avg_mae_r, 4),
            avg_hold_seconds=round(avg_hold_seconds, 1),
            total_realized_pnl=round(total_realized_pnl, 2),
            grade=grade,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _upsert_daily_stats(self, stats: SetupDailyStats) -> None:
        db = self._resolve_db()
        db[GRADE_COLLECTION].update_one(
            {"setup_type": stats.setup_type, "trading_date": stats.trading_date},
            {"$set": stats.to_dict()},
            upsert=True,
        )

    # ───────────────────────── Rolling read ─────────────────────────

    def get_rolling_grade(
        self,
        setup_type: str,
        days: int = 30,
    ) -> Optional[SetupRollingGrade]:
        """Build a `SetupRollingGrade` from the last `days` of daily
        records for `setup_type`. Returns None if there are zero
        records in the window."""
        from zoneinfo import ZoneInfo

        et = ZoneInfo("US/Eastern")
        today = datetime.now(et).date()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        db = self._resolve_db()
        cursor = db[GRADE_COLLECTION].find(
            {
                "setup_type": setup_type,
                "trading_date": {"$gte": from_date},
            },
            {"_id": 0},
        )
        rows = list(cursor)
        if not rows:
            return None
        return self._rollup(setup_type, days, rows)

    def get_all_rolling_grades(
        self,
        days: int = 30,
    ) -> List[SetupRollingGrade]:
        """Return one `SetupRollingGrade` per setup_type observed in
        the last `days`. Sorted by `avg_r` descending so the V5 chip
        carousel can lead with the strongest setups."""
        from zoneinfo import ZoneInfo

        et = ZoneInfo("US/Eastern")
        today = datetime.now(et).date()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        db = self._resolve_db()
        cursor = db[GRADE_COLLECTION].find(
            {"trading_date": {"$gte": from_date}},
            {"_id": 0},
        )
        # Group rows by setup_type.
        by_setup: Dict[str, List[Dict[str, Any]]] = {}
        for row in cursor:
            st = row.get("setup_type")
            if not st:
                continue
            by_setup.setdefault(st, []).append(row)

        out: List[SetupRollingGrade] = []
        for setup_type, rows in by_setup.items():
            rolling = self._rollup(setup_type, days, rows)
            if rolling is not None:
                out.append(rolling)
        # Sort by avg_r desc, tie-break by total_r desc.
        out.sort(key=lambda g: (g.avg_r, g.total_r), reverse=True)
        return out

    def _rollup(
        self,
        setup_type: str,
        days: int,
        rows: List[Dict[str, Any]],
    ) -> Optional[SetupRollingGrade]:
        """Combine multiple daily records into one rolling card.

        We re-aggregate at the row level (not just re-average the daily
        avgs) — taking the mean-of-means would weight a 1-trade day
        equally with a 20-trade day. Instead we sum totals and divide
        by total trades.
        """
        if not rows:
            return None
        trades_count = sum(int(r.get("trades_count") or 0) for r in rows)
        if trades_count == 0:
            return None
        wins = sum(int(r.get("wins") or 0) for r in rows)
        losses = sum(int(r.get("losses") or 0) for r in rows)
        total_r = sum(float(r.get("total_r") or 0.0) for r in rows)
        total_realized_pnl = sum(float(r.get("total_realized_pnl") or 0.0) for r in rows)
        worst_r = min((float(r.get("worst_r") or 0.0) for r in rows), default=0.0)
        best_r = max((float(r.get("best_r") or 0.0) for r in rows), default=0.0)
        # Sample-weighted averages.
        weighted_mfe = sum(
            float(r.get("avg_mfe_r") or 0.0) * int(r.get("trades_count") or 0)
            for r in rows
        )
        weighted_mae = sum(
            float(r.get("avg_mae_r") or 0.0) * int(r.get("trades_count") or 0)
            for r in rows
        )
        weighted_hold = sum(
            float(r.get("avg_hold_seconds") or 0.0) * int(r.get("trades_count") or 0)
            for r in rows
        )
        avg_mfe_r = weighted_mfe / trades_count
        avg_mae_r = weighted_mae / trades_count
        avg_hold_seconds = weighted_hold / trades_count
        avg_r = total_r / trades_count
        win_rate = wins / trades_count if trades_count else 0.0
        last_trade_date = max((r.get("trading_date") for r in rows if r.get("trading_date")), default=None)
        grade = compute_letter_grade(trades_count, win_rate, avg_r)
        return SetupRollingGrade(
            setup_type=setup_type,
            window_days=days,
            trades_count=trades_count,
            wins=wins,
            losses=losses,
            win_rate=round(win_rate, 4),
            avg_r=round(avg_r, 4),
            total_r=round(total_r, 4),
            worst_r=round(worst_r, 4),
            best_r=round(best_r, 4),
            avg_mfe_r=round(avg_mfe_r, 4),
            avg_mae_r=round(avg_mae_r, 4),
            avg_hold_seconds=round(avg_hold_seconds, 1),
            total_realized_pnl=round(total_realized_pnl, 2),
            grade=grade,
            days_with_data=len(rows),
            last_trade_date=last_trade_date,
        )

    # ───────────────────────── Operator: alert grade hint ─────────────────────────

    def get_grade_warning(self, setup_type: str, days: int = 30) -> Optional[str]:
        """Cheap read used by the alert pipeline: if a setup_type is
        currently graded `F` over the rolling window, return the
        grade label so the alert can be stamped with a warning. The
        ALERT IS NOT BLOCKED — v113 is observe-only. A future PR can
        flip this to a hard block once we've sanity-checked the
        formula against a week of live data.
        """
        try:
            rolling = self.get_rolling_grade(setup_type, days=days)
            if rolling is None:
                return None
            if rolling.grade == "F":
                return "F"
            return None
        except Exception as e:
            # Never let a grading read break the alert pipeline.
            logger.debug("get_grade_warning(%s) failed: %s", setup_type, e)
            return None


# Module-level singleton — most callers want a shared instance.
_SERVICE: Optional[SetupGradingService] = None


def get_setup_grading_service() -> SetupGradingService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SetupGradingService()
    return _SERVICE
