"""
Tests for v19.34.114 — Morning briefing yesterday's grade recap.

Adds `SetupGradingService.get_yesterday_recap()` + the
`/api/setup-grades/yesterday-recap` endpoint. The recap surfaces the
most recent trading day with grade data so the morning briefing can
quote it verbatim:

  "Yesterday (2026-02-12): 3 setups graded. Top winner: vwap_bounce
   A+ (66% WR, +1.2R, 6 trades). Watch: breakout F (33% WR, -0.4R,
   9 trades) — consider widening stops or pausing."

Walks back up to 7 calendar days to skip weekends / market holidays.
Returns a deterministic shape with `has_data: false` when there's no
graded history in the window (track record starts on first close).
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


def _make_db_with_grade_rows(rows_by_date):
    """Build a stub `db` whose `[GRADE_COLLECTION].find()` returns the
    rows mapped to the requested `trading_date`."""
    db = MagicMock()
    collection = MagicMock()

    def find(filt, projection=None):
        td = filt.get("trading_date")
        rows = rows_by_date.get(td, [])
        return iter(rows)

    collection.find = find
    db.__getitem__.return_value = collection
    return db


def _grade_row(setup_type, grade, avg_r, win_rate, trades_count, trading_date):
    return {
        "setup_type": setup_type,
        "trading_date": trading_date,
        "trades_count": trades_count,
        "wins": int(trades_count * win_rate),
        "losses": trades_count - int(trades_count * win_rate),
        "win_rate": win_rate,
        "avg_r": avg_r,
        "total_r": avg_r * trades_count,
        "total_realized_pnl": avg_r * trades_count * 100.0,
        "grade": grade,
    }


class TestYesterdayRecapBasic:

    def test_no_data_in_window_returns_has_data_false(self):
        from services.setup_grading_service import SetupGradingService
        svc = SetupGradingService(db=_make_db_with_grade_rows({}))
        recap = svc.get_yesterday_recap(reference_date="2026-02-12")
        assert recap["has_data"] is False
        assert recap["trading_date"] is None
        assert recap["total_setups"] == 0
        assert recap["winners"] == []
        assert recap["losers"] == []
        # Deterministic fallback line — LLM can quote it.
        assert "No graded setups" in recap["summary_line"]

    def test_picks_most_recent_trading_day_skipping_weekends(self):
        """If today is Monday and there's data Friday, the recap MUST
        pull Friday — not throw or return blank. The walk goes back up
        to 7 days."""
        from services.setup_grading_service import SetupGradingService
        # reference = Monday 2026-02-16. Friday 2026-02-13 has data;
        # Sat/Sun have none.
        rows = {
            "2026-02-13": [_grade_row("scalp", "B", 0.4, 0.50, 8, "2026-02-13")],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-16")
        assert recap["has_data"] is True
        assert recap["trading_date"] == "2026-02-13"
        assert recap["total_setups"] == 1

    def test_recap_walks_no_more_than_seven_days(self):
        """If the last graded day is >7 days ago, recap is empty (we
        won't cite a stale receipt in today's briefing)."""
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-03": [_grade_row("scalp", "A", 1.0, 0.6, 10, "2026-02-03")],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-12")
        # 2026-02-03 is 9 days before 2026-02-12 → outside window
        assert recap["has_data"] is False


class TestYesterdayRecapWinnersLosers:

    def test_winners_sorted_by_avg_r_desc(self):
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("a", "B", 0.4, 0.5, 5, "2026-02-12"),
                _grade_row("b", "A+", 1.5, 0.7, 8, "2026-02-12"),
                _grade_row("c", "A", 0.8, 0.6, 6, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        winners = [w["setup_type"] for w in recap["winners"]]
        assert winners[0] == "b"  # highest avg_r first
        assert winners == ["b", "c", "a"]

    def test_losers_only_includes_f_grade(self):
        """The "Watch" / losers list MUST contain only F-graded setups.
        A C-graded breakeven setup is not "losing money" and should
        not appear in the watch line."""
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("scalp", "A", 0.8, 0.6, 6, "2026-02-12"),
                _grade_row("orb",   "C", 0.05, 0.4, 5, "2026-02-12"),  # breakeven, not loser
                _grade_row("brk",   "F", -0.5, 0.3, 7, "2026-02-12"),  # actual loser
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        losers = [l["setup_type"] for l in recap["losers"]]
        assert losers == ["brk"]
        # The C-graded breakeven setup MUST NOT show up
        assert "orb" not in losers

    def test_winners_excluded_when_avg_r_zero_or_negative(self):
        """A 'graded' setup with avg_r=0.0 (C) should not count as a
        winner even though it's not an F. The "Top winner" line gets
        skipped entirely if no real winners exist."""
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("orb",   "C", 0.0,  0.4, 5, "2026-02-12"),
                _grade_row("brk",   "F", -0.3, 0.3, 7, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        assert recap["winners"] == []
        assert "Top winner" not in recap["summary_line"]
        assert "Watch:" in recap["summary_line"]  # but the F-loser line stays

    def test_skips_insufficient_data_setups(self):
        """Setups with grade=INSUFFICIENT_DATA must not appear in
        winners or losers — they have no track record yet."""
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("rare_setup", "INSUFFICIENT_DATA", 5.0, 1.0, 2, "2026-02-12"),
                _grade_row("scalp",      "A",                 0.8, 0.6, 6, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        # Only the A-graded scalp is in the count and winners list.
        assert recap["total_setups"] == 1
        winners = [w["setup_type"] for w in recap["winners"]]
        assert winners == ["scalp"]
        assert "rare_setup" not in winners

    def test_max_winners_and_losers_capped(self):
        """Long days with 10+ graded setups: recap caps the lists so
        the summary line stays readable."""
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row(f"win_{i}", "A", 0.8 + 0.01*i, 0.6, 5, "2026-02-12")
                for i in range(10)
            ] + [
                _grade_row(f"lose_{i}", "F", -0.4, 0.3, 5, "2026-02-12")
                for i in range(10)
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13", max_winners=3, max_losers=3)
        assert len(recap["winners"]) == 3
        assert len(recap["losers"]) == 3


class TestYesterdayRecapSummaryLine:
    """The summary_line MUST be deterministic and operator-readable
    so the LLM briefing can quote it verbatim."""

    def test_includes_trading_date(self):
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [_grade_row("scalp", "B", 0.4, 0.5, 8, "2026-02-12")],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        assert "2026-02-12" in recap["summary_line"]

    def test_summary_line_mentions_top_winner_when_present(self):
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("vwap_bounce", "A+", 1.2, 0.66, 6, "2026-02-12"),
                _grade_row("scalp",       "B",  0.3, 0.5,  5, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        line = recap["summary_line"]
        assert "Top winner: vwap_bounce A+" in line
        assert "66% WR" in line
        assert "+1.2R" in line
        assert "6 trades" in line

    def test_summary_line_mentions_losers_when_present(self):
        from services.setup_grading_service import SetupGradingService
        rows = {
            "2026-02-12": [
                _grade_row("scalp",   "A", 0.8,  0.6, 6, "2026-02-12"),
                _grade_row("breakout","F", -0.4, 0.33, 9, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        line = recap["summary_line"]
        assert "Watch: breakout F" in line
        assert "-0.4R" in line
        assert "consider widening stops or pausing" in line

    def test_singular_plural_correct(self):
        """Grammar: '1 setup graded' (singular), '3 setups graded' (plural)."""
        from services.setup_grading_service import SetupGradingService
        rows1 = {
            "2026-02-12": [_grade_row("scalp", "B", 0.4, 0.5, 8, "2026-02-12")],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows1))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        assert "1 setup graded" in recap["summary_line"]
        rows3 = {
            "2026-02-12": [
                _grade_row("a", "B", 0.3, 0.5, 5, "2026-02-12"),
                _grade_row("b", "A", 0.8, 0.6, 5, "2026-02-12"),
                _grade_row("c", "F", -0.5, 0.3, 5, "2026-02-12"),
            ],
        }
        svc = SetupGradingService(db=_make_db_with_grade_rows(rows3))
        recap = svc.get_yesterday_recap(reference_date="2026-02-13")
        assert "3 setups graded" in recap["summary_line"]


class TestYesterdayRecapEndpointWiring:
    """Source-level: the FastAPI route MUST be registered BEFORE the
    `/{setup_type}` catch-all so it doesn't get shadowed."""

    def test_route_declared_before_setup_type_param(self):
        src = (BACKEND_DIR / "routers" / "setup_grades.py").read_text()
        recap_idx = src.find('@router.get("/yesterday-recap")')
        param_idx = src.find('@router.get("/{setup_type}")')
        assert recap_idx >= 0, "yesterday-recap route missing from router"
        assert param_idx >= 0, "setup_type route missing"
        assert recap_idx < param_idx, (
            "/yesterday-recap MUST be declared BEFORE /{setup_type} "
            "or FastAPI will route the path into the setup-name handler"
        )

    def test_only_one_yesterday_recap_declaration(self):
        """Avoid the regression where I accidentally left a duplicate
        declaration during the route-reordering fix."""
        src = (BACKEND_DIR / "routers" / "setup_grades.py").read_text()
        count = src.count('@router.get("/yesterday-recap")')
        assert count == 1, f"Expected 1 yesterday-recap declaration, found {count}"
