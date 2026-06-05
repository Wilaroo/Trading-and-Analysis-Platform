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


# ── v19.34.271 (m5 + Issue 3) — canonical roll-up + robust grade math ──
# All three flags default ON but are instantly reversible via env so the
# operator can A/B the new behaviour against the legacy avg_R / raw-variant
# grading without a code change.
#
#   GRADING_CANONICAL_ROLLUP — group closed trades by canonicalize(setup_type)
#     (collapses vwap_fade_long + vwap_fade_short → vwap_fade) and EXCLUDE
#     reconciliation/import/watchlist artifacts (is_edge_excluded).
#   GRADING_USE_MEDIAN — grade off MEDIAN R instead of mean R (outlier-robust).
#   GRADING_MIN_RISK_AMOUNT — drop sub-$1 risk-basis rows from grade math; a
#     $0.20 dollar-risk trade produces an absurd R that dominates the mean.
def _grading_flag(key: str, default: bool = True) -> bool:
    import os
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _grading_min_risk() -> float:
    import os
    v = os.environ.get("GRADING_MIN_RISK_AMOUNT")
    if v in (None, ""):
        return 1.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 1.0


def _canonical_grade_key(setup_type):
    """Resolve the grade-bucket key for a raw setup_type, honoring the
    GRADING_CANONICAL_ROLLUP flag. Returns None for edge-excluded artifacts
    (caller must skip)."""
    if not setup_type:
        return None
    if not _grading_flag("GRADING_CANONICAL_ROLLUP"):
        return setup_type
    try:
        from services.setup_taxonomy import canonicalize, is_edge_excluded
        if is_edge_excluded(setup_type):
            return None
        return canonicalize(setup_type) or setup_type
    except Exception:  # pragma: no cover - fail-open to raw key
        return setup_type

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
    canonical_setup: str  # v19.34.271 — canonical bucket name (== setup_type when canonical rollup on)
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
            # v19.34.271 (m5) — canonical roll-up + artifact exclusion.
            # Collapse directional/style variants into one bucket and drop
            # reconciliation/import/watchlist artifacts so they never skew
            # per-setup edge or grade math.
            grade_key = _canonical_grade_key(st)
            if grade_key is None:
                continue
            # v19.34.173 — exclude learning_only micro trades from
            # grade aggregation. These are 0.1x-sized F-graded trades
            # whose realized R is dominated by fixed commission costs
            # (~0.5% of position on a 1-share trade vs <0.05% at full
            # size). Including them in avg_R creates a self-perpetuating
            # feedback loop (F grade keeps trading at micro → keeps
            # bleeding cost-poisoned R → stays F).
            #
            # Flag lives at either `trade.learning_only` (top-level on
            # newer rows) OR `trade.entry_context.learning_only`
            # (the propagation path from `build_entry_context`).
            _ec = trade.get("entry_context") or {}
            if trade.get("learning_only") is True or _ec.get("learning_only") is True:
                continue
            by_setup.setdefault(grade_key, []).append(trade)

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
            # v19.34.271 (Issue 3) — risk clamp. A sub-$1 dollar-risk basis
            # yields an absurd R-multiple (e.g. $0.20 risk on a $10 move = 50R)
            # that dominates the mean and ranks noise as a "best" setup. Drop
            # these micro-risk rows from grade math entirely.
            _risk = t.get("risk_amount")
            try:
                if _risk is not None and float(_risk) < _grading_min_risk():
                    continue
            except (TypeError, ValueError):
                pass
            r = t.get("r_multiple")
            if r is None:
                pnl = t.get("realized_pnl")
                risk = t.get("risk_amount")
                if pnl is not None and risk and float(risk) >= _grading_min_risk():
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

        # v19.34.271 (Issue 3) — grade off MEDIAN R (outlier-robust) when the
        # flag is on; legacy mean-R path preserved for instant reversibility.
        _grade_r = median_r if _grading_flag("GRADING_USE_MEDIAN") else avg_r
        grade = compute_letter_grade(trades_count, win_rate, _grade_r)

        return SetupDailyStats(
            setup_type=setup_type,
            canonical_setup=setup_type,
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

        # v19.34.271 (m5) — resolve to the canonical bucket the records are
        # keyed on so a raw variant lookup (vwap_fade_long) finds the
        # collapsed bucket (vwap_fade). No-op when canonical rollup is off.
        _ck = _canonical_grade_key(setup_type)
        if _ck is not None:
            setup_type = _ck
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
        # v19.34.271 (Issue 3) — robust rolling grade off a trade-count-weighted
        # blend of each day's MEDIAN R (each daily median is already
        # outlier-resistant) instead of the raw window mean R.
        weighted_median = sum(
            float(r.get("median_r") or 0.0) * int(r.get("trades_count") or 0)
            for r in rows
        )
        median_weighted_r = weighted_median / trades_count if trades_count else 0.0
        _grade_r = median_weighted_r if _grading_flag("GRADING_USE_MEDIAN") else avg_r
        grade = compute_letter_grade(trades_count, win_rate, _grade_r)
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

    # ───────────────────────── Morning Briefing recap ─────────────────────────

    def get_yesterday_recap(
        self,
        reference_date: Optional[str] = None,
        max_winners: int = 3,
        max_losers: int = 3,
    ) -> Dict[str, Any]:
        """v19.34.114 — Yesterday's grade card, formatted for the
        morning briefing line.

        Returns a structured recap with a deterministic `summary_line`
        the LLM briefing can quote verbatim. Pulls the most recent
        trading day with data (≤ `reference_date`, default = today
        US/Eastern) so weekend / holiday loads don't show a blank.

        Output shape:
            {
              "trading_date": "2026-02-12" | null,
              "total_setups": int,
              "winners":  [{"setup_type", "grade", "avg_r", "trades_count", "win_rate"}, ...],
              "losers":   [{"setup_type", "grade", "avg_r", "trades_count", "win_rate"}, ...],
              "summary_line": "Yesterday: 3 graded. nine_ema_scalp B (61%, +0.6R, 7t). breakout F (33%, -0.4R, 9t) — consider widening.",
              "has_data": bool,
            }
        """
        from zoneinfo import ZoneInfo

        et = ZoneInfo("US/Eastern")
        today = (
            datetime.strptime(reference_date, "%Y-%m-%d").date()
            if reference_date else datetime.now(et).date()
        )

        # Walk back up to 7 calendar days to find the most recent date
        # with any grade records (skips weekends / market holidays).
        db = self._resolve_db()
        target_date: Optional[str] = None
        rows: List[Dict[str, Any]] = []
        for delta in range(1, 8):
            probe = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
            cursor = db[GRADE_COLLECTION].find(
                {"trading_date": probe},
                {"_id": 0},
            )
            probe_rows = list(cursor)
            if probe_rows:
                target_date = probe
                rows = probe_rows
                break

        if not rows or target_date is None:
            return {
                "trading_date": None,
                "total_setups": 0,
                "winners": [],
                "losers": [],
                "summary_line": "No graded setups in the last 7 trading days. Track record starts on first close.",
                "has_data": False,
            }

        # Filter to setups with a real letter grade (skip INSUFFICIENT_DATA).
        graded = [r for r in rows if (r.get("grade") or "") not in ("", "INSUFFICIENT_DATA")]
        graded_sorted = sorted(graded, key=lambda r: r.get("avg_r", 0.0), reverse=True)

        def _pick_fields(r: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "setup_type": r.get("setup_type"),
                "grade": r.get("grade"),
                "avg_r": r.get("avg_r"),
                "trades_count": r.get("trades_count"),
                "win_rate": r.get("win_rate"),
                "total_realized_pnl": r.get("total_realized_pnl"),
            }

        winners = [_pick_fields(r) for r in graded_sorted[:max_winners] if r.get("avg_r", 0) > 0]
        losers = [
            _pick_fields(r) for r in graded_sorted
            if r.get("grade") == "F"
        ][:max_losers]

        # Compose the summary line. Format chosen so a human can read
        # it at a glance AND the LLM can quote it verbatim:
        #   "Yesterday (2026-02-12): 5 setups graded.
        #    Top winner: nine_ema_scalp B (61% WR, +0.6R, 7 trades).
        #    Watch: breakout F (33% WR, -0.4R, 9 trades) — consider widening or pausing."
        parts: List[str] = [
            f"Yesterday ({target_date}): {len(graded)} setup{'s' if len(graded) != 1 else ''} graded."
        ]
        if winners:
            top = winners[0]
            wr_pct = round((top.get("win_rate") or 0.0) * 100)
            avg_r = top.get("avg_r") or 0.0
            avg_r_str = f"+{avg_r:.1f}R" if avg_r >= 0 else f"{avg_r:.1f}R"
            parts.append(
                f"Top winner: {top.get('setup_type')} {top.get('grade')} "
                f"({wr_pct}% WR, {avg_r_str}, {top.get('trades_count')} trades)."
            )
        if losers:
            worst = losers[0]
            wr_pct = round((worst.get("win_rate") or 0.0) * 100)
            avg_r = worst.get("avg_r") or 0.0
            avg_r_str = f"+{avg_r:.1f}R" if avg_r >= 0 else f"{avg_r:.1f}R"
            parts.append(
                f"Watch: {worst.get('setup_type')} F "
                f"({wr_pct}% WR, {avg_r_str}, {worst.get('trades_count')} trades) — "
                f"consider widening stops or pausing."
            )
        summary_line = " ".join(parts)

        return {
            "trading_date": target_date,
            "total_setups": len(graded),
            "winners": winners,
            "losers": losers,
            "summary_line": summary_line,
            "has_data": True,
        }


# Module-level singleton — most callers want a shared instance.
_SERVICE: Optional[SetupGradingService] = None


def get_setup_grading_service() -> SetupGradingService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SetupGradingService()
    return _SERVICE
