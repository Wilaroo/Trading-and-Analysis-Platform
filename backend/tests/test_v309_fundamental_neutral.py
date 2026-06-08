"""v19.34.309 — Fundamental absent-data → neutral 50 (not optimistic)."""
import asyncio

from services.tqs.fundamental_quality import FundamentalQualityService


def _score(**kw):
    svc = FundamentalQualityService()  # no services wired → all lookups skipped/fail-soft
    return asyncio.run(svc.calculate_score("ZZZZ", direction="long", **kw))


def test_absent_data_components_are_neutral_50():
    # Nothing provided and no services wired → every data point absent.
    r = _score()
    assert r.short_interest_score == 50.0
    assert r.float_score == 50.0
    assert r.institutional_score == 50.0
    assert r.earnings_score == 50.0


def test_absent_data_overall_not_optimistic():
    # Pre-fix this scored ~57 (C+). With neutral-50 it must be <= 50.
    r = _score()
    assert r.score <= 50.0


def test_present_data_still_scored_normally():
    # High short interest for a long should still earn its squeeze credit.
    r = _score(short_interest_pct=22.0, float_shares=15_000_000, institutional_pct=55.0)
    assert r.short_interest_score == 95
    assert r.float_score == 90      # low float
    assert r.institutional_score == 80  # ideal 40-70 band
