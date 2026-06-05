"""
Tests for v19.34.113 — Setup Grading Subsystem.

Three areas:
  1. Pure grade-formula correctness (compute_letter_grade)
  2. Daily aggregation math (SetupGradingService._compute_daily_stats)
  3. Rolling rollup math (SetupGradingService._rollup)

Avoid Mongo / database fixtures — drive the service with a stub `db`
exposing `find` / `update_one` so the tests run in <100ms with no
external infra.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# 1. Pure grade-formula
# ---------------------------------------------------------------------------

class TestComputeLetterGrade:
    """`compute_letter_grade` is the heart of the rubric. Lock the
    exact band edges so any future tuning produces a visible diff."""

    def test_below_sample_size_returns_insufficient_data(self):
        from services.setup_grading_service import compute_letter_grade
        # 4 trades < default min sample (5) → INSUFFICIENT_DATA even with great stats
        assert compute_letter_grade(4, win_rate=0.90, avg_r=2.5) == "INSUFFICIENT_DATA"

    def test_negative_avg_r_always_f(self):
        from services.setup_grading_service import compute_letter_grade
        # Even with 80% WR, negative avg_r means the few losses are
        # huge — that's still an F setup.
        assert compute_letter_grade(20, win_rate=0.80, avg_r=-0.1) == "F"

    def test_a_plus_thresholds(self):
        from services.setup_grading_service import compute_letter_grade
        # A+: ≥60% AND avg_r ≥ 1.0
        assert compute_letter_grade(10, win_rate=0.60, avg_r=1.0) == "A+"
        assert compute_letter_grade(10, win_rate=0.59, avg_r=1.0) == "A"   # WR falls through
        assert compute_letter_grade(10, win_rate=0.60, avg_r=0.99) == "A"  # avg_r falls through

    def test_a_grade(self):
        from services.setup_grading_service import compute_letter_grade
        assert compute_letter_grade(10, win_rate=0.55, avg_r=0.7) == "A"
        assert compute_letter_grade(10, win_rate=0.54, avg_r=0.7) == "B+"

    def test_b_plus_grade(self):
        from services.setup_grading_service import compute_letter_grade
        assert compute_letter_grade(10, win_rate=0.50, avg_r=0.5) == "B+"
        assert compute_letter_grade(10, win_rate=0.49, avg_r=0.5) == "B"

    def test_b_grade(self):
        from services.setup_grading_service import compute_letter_grade
        assert compute_letter_grade(10, win_rate=0.45, avg_r=0.3) == "B"

    def test_c_grade_breakeven(self):
        from services.setup_grading_service import compute_letter_grade
        # Breakeven setup — still earning the spread, still passable.
        assert compute_letter_grade(10, win_rate=0.30, avg_r=0.0) == "C"
        assert compute_letter_grade(10, win_rate=0.30, avg_r=0.05) == "C"

    def test_f_grade(self):
        from services.setup_grading_service import compute_letter_grade
        # avg_r < 0 always F regardless of WR
        assert compute_letter_grade(10, win_rate=0.45, avg_r=-0.01) == "F"

    def test_grade_band_ordering(self):
        """Walking up the bands must produce monotonically improving labels."""
        from services.setup_grading_service import compute_letter_grade
        cases = [
            ("F",  10, 0.40, -0.5),
            ("C",  10, 0.30,  0.1),
            ("B",  10, 0.45,  0.4),
            ("B+", 10, 0.50,  0.5),
            ("A",  10, 0.55,  0.8),
            ("A+", 10, 0.65,  1.2),
        ]
        for label, n, wr, r in cases:
            assert compute_letter_grade(n, wr, r) == label, f"{label} ladder broke at ({n}, {wr}, {r})"


# ---------------------------------------------------------------------------
# 2. Daily aggregation
# ---------------------------------------------------------------------------

class TestComputeDailyStats:
    """`_compute_daily_stats` ingests raw bot_trades rows and produces
    a SetupDailyStats. Test the math + edge cases."""

    def setup_method(self):
        from services.setup_grading_service import SetupGradingService
        self.svc = SetupGradingService(db=MagicMock())

    def _trade(self, r_mul, *, mfe=0.0, mae=0.0, pnl=0.0):
        # Provide a minimal trade dict with the fields _compute_daily_stats reads.
        return {
            "id": f"t-{r_mul}",
            "setup_type": "scalp",
            "r_multiple": r_mul,
            "realized_pnl": pnl,
            "risk_amount": 100.0,
            "mfe_r": mfe,
            "mae_r": mae,
            "executed_at": "2026-02-12T13:30:00+00:00",
            "closed_at": "2026-02-12T13:35:00+00:00",
        }

    def test_basic_aggregation(self):
        trades = [self._trade(1.5), self._trade(-1.0), self._trade(2.0), self._trade(-1.0), self._trade(0.5)]
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", trades)
        assert stats is not None
        assert stats.trades_count == 5
        assert stats.wins == 3
        assert stats.losses == 2
        assert stats.breakevens == 0
        assert stats.win_rate == 0.6
        # avg = (1.5 -1 +2 -1 +0.5) / 5 = 0.4
        assert abs(stats.avg_r - 0.4) < 1e-6
        assert stats.total_r == 2.0
        assert stats.worst_r == -1.0
        assert stats.best_r == 2.0
        # v19.34.271 — grade now MEDIAN-driven. median([-1,-1,0.5,1.5,2]) = 0.5
        # 60% WR + 0.5 median_r → B+
        assert stats.grade == "B+"

    def test_breakeven_trades_counted_separately(self):
        trades = [self._trade(0.0)] * 5
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", trades)
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.breakevens == 5
        assert stats.win_rate == 0.0
        assert stats.avg_r == 0.0
        # Breakeven setup → C
        assert stats.grade == "C"

    def test_below_min_sample_grades_insufficient(self):
        trades = [self._trade(2.0)] * 3  # Only 3 trades < min 5
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", trades)
        assert stats.trades_count == 3
        assert stats.grade == "INSUFFICIENT_DATA"

    def test_returns_none_for_no_trades(self):
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", [])
        assert stats is None

    def test_derives_r_multiple_from_pnl_when_missing(self):
        """If r_multiple is missing, fall back to realized_pnl/risk_amount."""
        trade = {
            "id": "t-derive",
            "setup_type": "breakout",
            "r_multiple": None,
            "realized_pnl": 150.0,
            "risk_amount": 100.0,
            "mfe_r": 0,
            "mae_r": 0,
        }
        stats = self.svc._compute_daily_stats("breakout", "2026-02-12", [trade] * 5)
        # 150 / 100 = 1.5R each
        assert abs(stats.avg_r - 1.5) < 1e-6

    def test_skips_rows_with_no_r_multiple_or_pnl(self):
        """Rows where r_multiple AND realized_pnl/risk are missing must
        be silently dropped — never inflate or zero-out stats."""
        good = [self._trade(1.0) for _ in range(5)]
        broken = [{
            "id": "broken",
            "setup_type": "scalp",
            "r_multiple": None,
            "realized_pnl": None,
            "risk_amount": None,
        }]
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", good + broken)
        # Only the 5 good rows count
        assert stats.trades_count == 5

    def test_mfe_mae_aggregation(self):
        trades = [
            self._trade(0.5, mfe=2.0, mae=-0.5),
            self._trade(1.0, mfe=1.5, mae=-0.3),
            self._trade(-1.0, mfe=0.2, mae=-1.0),
            self._trade(2.0, mfe=2.5, mae=-0.2),
            self._trade(0.0, mfe=0.8, mae=-0.6),
        ]
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", trades)
        # avg_mfe = (2 + 1.5 + 0.2 + 2.5 + 0.8) / 5 = 1.4
        assert abs(stats.avg_mfe_r - 1.4) < 1e-6
        # avg_mae = (-0.5 + -0.3 + -1.0 + -0.2 + -0.6) / 5 = -0.52
        assert abs(stats.avg_mae_r - (-0.52)) < 1e-6

    def test_hold_seconds_uses_executed_and_closed(self):
        # 5 minutes = 300s
        trades = [self._trade(1.0) for _ in range(5)]
        stats = self.svc._compute_daily_stats("scalp", "2026-02-12", trades)
        assert abs(stats.avg_hold_seconds - 300.0) < 1.0


# ---------------------------------------------------------------------------
# 3. Rolling rollup math
# ---------------------------------------------------------------------------

class TestRollingRollup:
    """`_rollup` re-aggregates per-day records into a rolling card.
    Critical correctness: must use SAMPLE-WEIGHTED averages, not
    mean-of-means (a 1-trade day MUST NOT count equally with a 20-trade
    day)."""

    def setup_method(self):
        from services.setup_grading_service import SetupGradingService
        self.svc = SetupGradingService(db=MagicMock())

    def _day(self, date, n_trades, wins, total_r, mfe=1.0, mae=-0.5, hold=180.0, pnl=0.0, median_r=None):
        return {
            "trading_date": date,
            "trades_count": n_trades,
            "wins": wins,
            "losses": n_trades - wins,
            "total_r": total_r,
            # v19.34.271 — real daily records always store median_r; the
            # rolling grade is now median-weighted. Default to the per-day
            # mean when not explicitly provided by a test.
            "median_r": (total_r / n_trades if n_trades else 0.0) if median_r is None else median_r,
            "worst_r": -2.0,
            "best_r": 3.0,
            "avg_mfe_r": mfe,
            "avg_mae_r": mae,
            "avg_hold_seconds": hold,
            "total_realized_pnl": pnl,
        }

    def test_basic_rollup(self):
        rows = [
            self._day("2026-02-10", 10, 6, total_r=5.0),
            self._day("2026-02-11", 5,  3, total_r=2.0),
            self._day("2026-02-12", 15, 9, total_r=8.0),
        ]
        rolling = self.svc._rollup("scalp", 30, rows)
        assert rolling.trades_count == 30
        assert rolling.wins == 18
        assert rolling.losses == 12
        assert rolling.win_rate == 0.6
        # total_r = 5 + 2 + 8 = 15; avg_r = 15/30 = 0.5
        assert abs(rolling.avg_r - 0.5) < 1e-6
        assert rolling.total_r == 15.0
        # 60% WR + 0.5 avg_r → B+
        assert rolling.grade == "B+"

    def test_rollup_uses_sample_weighted_mfe_mae(self):
        """A 1-trade day with mfe=10R must NOT skew the rolling avg."""
        rows = [
            self._day("2026-02-10", 1,  1, total_r=10.0, mfe=10.0, mae=0.0),
            self._day("2026-02-12", 20, 12, total_r=5.0, mfe=0.5, mae=-0.3),
        ]
        rolling = self.svc._rollup("scalp", 30, rows)
        # weighted mfe = (10*1 + 0.5*20) / 21 = 20/21 ≈ 0.952
        # mean-of-means would give (10 + 0.5)/2 = 5.25 — wrong.
        assert abs(rolling.avg_mfe_r - (20 / 21)) < 1e-4

    def test_rollup_returns_none_for_no_rows(self):
        assert self.svc._rollup("scalp", 30, []) is None

    def test_rollup_returns_none_when_total_zero_trades(self):
        rows = [self._day("2026-02-12", 0, 0, total_r=0.0)]
        assert self.svc._rollup("scalp", 30, rows) is None

    def test_last_trade_date_is_max(self):
        rows = [
            self._day("2026-02-09", 5, 2, total_r=0.0),
            self._day("2026-02-12", 5, 2, total_r=0.0),
            self._day("2026-02-10", 5, 2, total_r=0.0),
        ]
        rolling = self.svc._rollup("scalp", 30, rows)
        assert rolling.last_trade_date == "2026-02-12"

    def test_worst_best_r_across_window(self):
        rows = [
            {**self._day("2026-02-10", 5, 2, total_r=0.0), "worst_r": -1.5, "best_r": 2.0},
            {**self._day("2026-02-11", 5, 2, total_r=0.0), "worst_r": -3.0, "best_r": 1.5},
            {**self._day("2026-02-12", 5, 2, total_r=0.0), "worst_r": -0.5, "best_r": 4.0},
        ]
        rolling = self.svc._rollup("scalp", 30, rows)
        assert rolling.worst_r == -3.0
        assert rolling.best_r == 4.0


# ---------------------------------------------------------------------------
# 4. EOD compute path — end-to-end with mocked db
# ---------------------------------------------------------------------------

class TestComputeEodGrades:
    """`compute_eod_grades` walks Mongo and upserts. We mock the db
    layer to assert correct queries + upsert calls without an actual
    database."""

    def setup_method(self):
        from services.setup_grading_service import SetupGradingService

        # The service's `_resolve_db()` returns self._db if set.
        self.db = MagicMock()
        self.collection_calls = {"find_args": [], "update_one_args": []}
        bot_trades_col = MagicMock()
        grade_records_col = MagicMock()

        def find(filt, projection=None):
            self.collection_calls["find_args"].append((filt, projection))
            return iter([
                {"id": "t1", "setup_type": "scalp", "r_multiple": 1.5,
                 "realized_pnl": 150.0, "risk_amount": 100.0, "mfe_r": 2.0, "mae_r": -0.3,
                 "executed_at": "2026-02-12T14:00:00+00:00", "closed_at": "2026-02-12T14:05:00+00:00"},
                {"id": "t2", "setup_type": "scalp", "r_multiple": -1.0,
                 "realized_pnl": -100.0, "risk_amount": 100.0, "mfe_r": 0.5, "mae_r": -1.0,
                 "executed_at": "2026-02-12T14:30:00+00:00", "closed_at": "2026-02-12T14:33:00+00:00"},
                {"id": "t3", "setup_type": "breakout", "r_multiple": 2.0,
                 "realized_pnl": 200.0, "risk_amount": 100.0, "mfe_r": 2.5, "mae_r": -0.2,
                 "executed_at": "2026-02-12T15:00:00+00:00", "closed_at": "2026-02-12T15:15:00+00:00"},
            ])
        bot_trades_col.find = find

        def upsert(filt, update, upsert=False):
            self.collection_calls["update_one_args"].append((filt, update, upsert))
        grade_records_col.update_one = upsert

        def getitem(name):
            if name == "bot_trades":
                return bot_trades_col
            if name == "setup_grade_records":
                return grade_records_col
            raise KeyError(name)
        self.db.__getitem__.side_effect = getitem

        self.svc = SetupGradingService(db=self.db)

    def test_compute_returns_summary_per_setup(self):
        result = self.svc.compute_eod_grades(trading_date="2026-02-12")
        assert result["trading_date"] == "2026-02-12"
        # We have 2 distinct setup_types in fixture: scalp, breakout.
        # v19.34.271 — canonical rollup aliases `scalp` → `spencer_scalp`
        # per the SSOT (services/setup_taxonomy._ALIASES).
        setups = [s["setup_type"] for s in result["summaries"]]
        assert "spencer_scalp" in setups
        assert "breakout" in setups
        assert result["setups_graded"] == 2

    def test_upserts_one_row_per_setup_type(self):
        self.svc.compute_eod_grades(trading_date="2026-02-12")
        # Two upserts — one per setup_type.
        assert len(self.collection_calls["update_one_args"]) == 2
        # Each upsert key must include both setup_type AND trading_date
        for filt, update, upsert in self.collection_calls["update_one_args"]:
            assert "setup_type" in filt
            assert "trading_date" in filt
            assert filt["trading_date"] == "2026-02-12"
            assert upsert is True

    def test_query_filters_to_closed_trades_only(self):
        self.svc.compute_eod_grades(trading_date="2026-02-12")
        # Inspect the first find() call — must filter on status=closed
        filt, _ = self.collection_calls["find_args"][0]
        assert filt["status"] == "closed"
        assert "closed_at" in filt
        assert "setup_type" in filt


# ---------------------------------------------------------------------------
# 5. Grade-warning helper for alert pipeline
# ---------------------------------------------------------------------------

class TestGradeWarning:
    """`get_grade_warning` returns 'F' for setups graded F in the
    rolling window; None otherwise. Never raises — alert pipeline
    safety."""

    def setup_method(self):
        from services.setup_grading_service import SetupGradingService, SetupRollingGrade
        self.svc = SetupGradingService(db=MagicMock())
        # Stub the rolling lookup so we don't need Mongo.
        self.SetupRollingGrade = SetupRollingGrade

    def _rolling_with_grade(self, grade: str):
        return self.SetupRollingGrade(
            setup_type="scalp", window_days=30,
            trades_count=20, wins=8, losses=12,
            win_rate=0.4, avg_r=-0.2, total_r=-4.0,
            worst_r=-2.0, best_r=1.0,
            avg_mfe_r=0.6, avg_mae_r=-0.8,
            avg_hold_seconds=180, total_realized_pnl=-400.0,
            grade=grade, days_with_data=5, last_trade_date="2026-02-12",
        )

    def test_f_grade_returns_warning(self):
        self.svc.get_rolling_grade = MagicMock(return_value=self._rolling_with_grade("F"))
        assert self.svc.get_grade_warning("scalp") == "F"

    def test_non_f_returns_none(self):
        for g in ("A+", "A", "B+", "B", "C"):
            self.svc.get_rolling_grade = MagicMock(return_value=self._rolling_with_grade(g))
            assert self.svc.get_grade_warning("scalp") is None, f"Grade {g} should NOT warn"

    def test_no_data_returns_none(self):
        """A setup with no trades in the window must not warn."""
        self.svc.get_rolling_grade = MagicMock(return_value=None)
        assert self.svc.get_grade_warning("brand_new_setup") is None

    def test_exception_in_lookup_returns_none(self):
        """Alert pipeline safety — never crash."""
        self.svc.get_rolling_grade = MagicMock(side_effect=RuntimeError("mongo down"))
        assert self.svc.get_grade_warning("scalp") is None


# ---------------------------------------------------------------------------
# 6. Source-level wiring assertions
# ---------------------------------------------------------------------------

class TestSchedulerWiring:
    """The EOD grading tick MUST be wired into the trading_bot scan
    loop and the bot service MUST initialize the daily-execution
    guard. Source-grep assertions because we can't run the live loop
    inside a unit test."""

    @pytest.fixture
    def bot_src(self):
        return (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()

    def test_eod_grading_state_initialized(self, bot_src):
        assert "_eod_grading_hour = 16" in bot_src
        assert "_eod_grading_minute = 10" in bot_src
        assert "_eod_grading_executed_today_key" in bot_src

    def test_check_eod_grading_method_exists(self, bot_src):
        assert "async def _check_eod_grading(self):" in bot_src

    def test_check_eod_grading_called_from_scan_loop(self, bot_src):
        assert "self._check_eod_grading()" in bot_src

    def test_grading_uses_setup_grading_service(self, bot_src):
        assert "from services.setup_grading_service import get_setup_grading_service" in bot_src

    def test_router_mounted_in_server(self):
        server_src = (BACKEND_DIR / "server.py").read_text()
        assert "from routers.setup_grades import router as setup_grades_router" in server_src
        assert "app.include_router(setup_grades_router)" in server_src
