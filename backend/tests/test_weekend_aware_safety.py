"""
Regression tests for weekend-aware freshness + account guard.

Locks in:
  * `_adjusted_stale_days` adds +3d buffer on weekend, +1d on overnight,
    untouched during RTH/extended.
  * Daily/weekly timeframes are not weekend-buffered (their thresholds
    already absorb a normal weekend gap).
  * `check_account_match` returns (True, 'pending') when account is None
    AND ib_connected is False (weekend / Gateway offline) instead of
    (False, 'no account reported') which previously turned the chip red
    every weekend.
"""

from __future__ import annotations

import pytest


# ──────────────────────────────────────────────────────────────────────
# Stale-days adjustment — weekend / overnight buffer
# ──────────────────────────────────────────────────────────────────────

def test_intraday_stale_days_unchanged_during_rth():
    from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS
    for tf in ("1 min", "5 mins", "15 mins", "30 mins", "1 hour"):
        assert _adjusted_stale_days(tf, "rth") == STALE_DAYS[tf]


def test_intraday_stale_days_unchanged_during_extended():
    from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS
    assert _adjusted_stale_days("5 mins", "extended") == STALE_DAYS["5 mins"]


def test_intraday_stale_days_buffered_on_weekend():
    from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS
    for tf in ("1 min", "5 mins", "15 mins", "30 mins", "1 hour"):
        assert _adjusted_stale_days(tf, "weekend") == STALE_DAYS[tf] + 3, (
            f"{tf} weekend buffer should be +3 days "
            f"(covers Fri-close → Mon-premarket)"
        )


def test_intraday_stale_days_buffered_on_overnight():
    from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS
    assert _adjusted_stale_days("5 mins", "overnight") == STALE_DAYS["5 mins"] + 1


def test_daily_weekly_not_weekend_buffered():
    """Daily/weekly thresholds are already multi-day windows that absorb
    a normal weekend gap, so we don't double-count by adding +3."""
    from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS
    assert _adjusted_stale_days("1 day", "weekend") == STALE_DAYS["1 day"]
    assert _adjusted_stale_days("1 week", "weekend") == STALE_DAYS["1 week"]
    assert _adjusted_stale_days("1 day", "overnight") == STALE_DAYS["1 day"]


# ──────────────────────────────────────────────────────────────────────
# Account guard — weekend behaviour
# ──────────────────────────────────────────────────────────────────────

def _exp_paper_only():
    from services.account_guard import AccountExpectation
    return AccountExpectation(
        active_mode="paper",
        expected_aliases=["paperesw100000", "dun615665"],
        live_aliases=[],
        paper_aliases=["paperesw100000", "dun615665"],
    )


def test_account_match_when_account_in_aliases():
    from services.account_guard import check_account_match
    ok, reason = check_account_match("DUN615665", _exp_paper_only())
    assert ok is True
    assert "matched" in reason


def test_account_match_pending_on_weekend_when_pusher_has_no_account():
    """The user's pre-fix behaviour: weekend → pusher has no account
    snapshot → old code returned (False, 'no account reported') → chip
    turned RED falsely every weekend. New behaviour: ib_connected=False
    softens to (True, 'pending')."""
    from services.account_guard import check_account_match
    ok, reason = check_account_match(None, _exp_paper_only(), ib_connected=False)
    assert ok is True
    assert "pending" in reason
    assert "IB Gateway" in reason


def test_account_mismatch_when_account_drifts_to_live_alias():
    """Even with ib_connected=False, an explicit drift (paper mode but
    pusher reports a LIVE account) should still flag mismatch — we don't
    want to mask real config errors as 'pending'."""
    from services.account_guard import check_account_match, AccountExpectation
    exp = AccountExpectation(
        active_mode="paper",
        expected_aliases=["paperesw100000", "dun615665"],
        live_aliases=["esw100000", "u4680762"],
        paper_aliases=["paperesw100000", "dun615665"],
    )
    ok, reason = check_account_match("U4680762", exp, ib_connected=False)
    assert ok is False
    assert "live mode" in reason or "drift" in reason


def test_account_pre_fix_behaviour_preserved_when_ib_connected_true():
    """When ib_connected is explicitly True (or None) and there's no
    account, behaviour is unchanged: returns mismatch — because Gateway
    being up but pusher having no account IS a real bug."""
    from services.account_guard import check_account_match
    ok, reason = check_account_match(None, _exp_paper_only(), ib_connected=True)
    assert ok is False
    assert "no account" in reason


def test_account_summarize_includes_ib_connected():
    """The UI payload should always carry the ib_connected flag so the
    chip can render 'pending' vs 'mismatch' distinctly."""
    from services.account_guard import summarize_for_ui
    out = summarize_for_ui("DUN615665", ib_connected=True)
    assert "ib_connected" in out
    assert out["ib_connected"] is True
