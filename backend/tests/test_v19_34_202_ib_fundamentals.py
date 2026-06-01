"""v19.34.202 — IB ReportSnapshot float/shares parse + FINRA short-interest %."""
from services.ib_fundamentals_parser import parse_report_snapshot
from services.unified_fundamentals_cache import compute_short_interest_pct

_SNAPSHOT = """<?xml version="1.0" encoding="UTF-8"?>
<ReportSnapshot Major="1" Minor="0" Revision="1">
  <CoGeneralInfo>
    <Employees LastUpdated="2025-12-27">31000</Employees>
    <SharesOut Date="2026-04-29" TotalFloat="1623871179.0">1630600639.0</SharesOut>
  </CoGeneralInfo>
</ReportSnapshot>"""


def test_parse_shares_and_float():
    out = parse_report_snapshot(_SNAPSHOT)
    assert out["shares_outstanding"] == 1630600639.0
    assert out["float_shares"] == 1623871179.0
    assert out["employees"] == 31000


def test_parse_missing_sharesout_is_safe():
    out = parse_report_snapshot(
        "<ReportSnapshot><CoGeneralInfo></CoGeneralInfo></ReportSnapshot>")
    assert "shares_outstanding" not in out
    assert "float_shares" not in out


def test_short_interest_pct_basic():
    assert compute_short_interest_pct(50_000_000, 1_630_600_639) == 3.07


def test_short_interest_pct_high():
    assert compute_short_interest_pct(200_000_000, 1_000_000_000) == 20.0


def test_short_interest_pct_guards():
    assert compute_short_interest_pct(0, 1_000_000) is None
    assert compute_short_interest_pct(1_000_000, 0) is None
    assert compute_short_interest_pct(None, 1_000_000) is None
    assert compute_short_interest_pct("x", "y") is None
