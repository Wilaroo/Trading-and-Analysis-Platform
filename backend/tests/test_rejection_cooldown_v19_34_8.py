"""
test_rejection_cooldown_v19_34_8.py — pin the v19.34.8 rejection
cooldown service.

Operator-driven after the XLU/UPS forensic at 2026-05-05 PM:

  > 135 brackets / 0 bot_trades for XLU over 71 min, all rejected,
  > all distinct trade_ids. Bot's intent-dedup couldn't catch them
  > because qty fluctuated wildly with equity (1845→922→463→277).

Fix: per-`(symbol, setup_type)` cooldown after a structural rejection
(capital, position-cap, kill-switch, etc.). Subsequent re-evals during
the cooldown window are short-circuited with a clear log breadcrumb.

Pinned by this test suite:
  1. is_structural_rejection classifier — capital/positions/kill-
     switch trigger; transient (stale_quote, intent_already_pending)
     do NOT.
  2. mark_rejection / is_in_cooldown round-trip + key composition.
  3. Repeat-rejection extends the window + increments rejection_count.
  4. Auto-expiry: after expires_at passes, key is no longer in cooldown.
  5. Manual clear via clear_cooldown / clear_all.
  6. Stats + list_active surfaces correct snapshot.
  7. Default cooldown reads from REJECTION_COOLDOWN_SECONDS env.
  8. Empty / None inputs handled defensively.

Plus 4 endpoint tests for the operator API.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test gets a fresh RejectionCooldown singleton."""
    from services.rejection_cooldown_service import reset_rejection_cooldown_for_tests
    reset_rejection_cooldown_for_tests()
    yield
    reset_rejection_cooldown_for_tests()


# --------------------------------------------------------------------------
# is_structural_rejection classifier
# --------------------------------------------------------------------------

class TestIsStructuralRejection:

    @pytest.mark.parametrize("reason", [
        "max_daily_loss_hit",
        "Daily loss limit reached: $1000.00",
        "max_open_positions exceeded (10/10)",
        "kill_switch_tripped: account drawdown",
        "insufficient buying power",
        "BUYING POWER TOO LOW",
        "max_position_pct breached: 12% > 10%",
        "max_total_exposure 320% reached",
        "max_symbol_exposure_usd capped",
        "daily_dd_circuit broken",
        "exposure_cap_exceeded",
    ])
    def test_structural_reasons_classified_as_structural(self, reason):
        from services.rejection_cooldown_service import is_structural_rejection
        assert is_structural_rejection(reason) is True, (
            f"Expected '{reason}' to be structural"
        )

    @pytest.mark.parametrize("reason", [
        "stale_quote",
        "intent_already_pending",
        "duplicate_intent on bracket",
        "veto_strategy_phase",
        "no_position_data",
        "execution_exception: AttributeError",
        "guardrail_veto: stop too tight",
    ])
    def test_transient_reasons_classified_as_transient(self, reason):
        from services.rejection_cooldown_service import is_structural_rejection
        assert is_structural_rejection(reason) is False, (
            f"Expected '{reason}' to be transient"
        )

    def test_empty_reason_is_not_structural(self):
        from services.rejection_cooldown_service import is_structural_rejection
        assert is_structural_rejection(None) is False
        assert is_structural_rejection("") is False
        assert is_structural_rejection("   ") is False

    def test_unknown_reason_default_not_structural(self):
        """Unknown / unclassified reasons default to NOT structural,
        so we don't accidentally cooldown legit transient failures."""
        from services.rejection_cooldown_service import is_structural_rejection
        assert is_structural_rejection("some weird new error") is False


# --------------------------------------------------------------------------
# mark_rejection + is_in_cooldown round-trip
# --------------------------------------------------------------------------

class TestMarkAndCheckRoundTrip:

    def test_structural_rejection_creates_cooldown(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        entry = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="max_daily_loss_hit",
            cooldown_seconds=300,
        )
        assert entry is not None
        assert entry.symbol == "XLU"
        assert entry.setup_type == "orb"
        assert entry.rejection_count == 1
        assert entry.remaining_seconds() > 290
        # is_in_cooldown reflects this
        check = rc.is_in_cooldown("XLU", "orb")
        assert check is not None
        assert check.symbol == "XLU"

    def test_transient_rejection_does_not_create_cooldown(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        entry = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="stale_quote",
        )
        assert entry is None
        assert rc.is_in_cooldown("XLU", "orb") is None

    def test_key_is_case_insensitive_for_symbol(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection(symbol="xlu", setup_type="orb",
                          reason="max_daily_loss_hit")
        # All these lookup variants should hit the same key
        assert rc.is_in_cooldown("XLU", "orb") is not None
        assert rc.is_in_cooldown("xlu", "ORB") is not None
        assert rc.is_in_cooldown("Xlu", "Orb") is not None

    def test_distinct_setup_types_keyed_independently(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection(symbol="XLU", setup_type="orb",
                          reason="max_daily_loss_hit")
        # Different setup on same symbol — NOT in cooldown
        assert rc.is_in_cooldown("XLU", "gap_fade") is None
        assert rc.is_in_cooldown("XLU", "orb") is not None

    def test_distinct_symbols_keyed_independently(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection(symbol="XLU", setup_type="orb",
                          reason="max_daily_loss_hit")
        assert rc.is_in_cooldown("UPS", "orb") is None

    def test_repeat_rejection_extends_window_and_bumps_count(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        entry1 = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="max_daily_loss_hit",
            cooldown_seconds=60,
        )
        first_expiry = entry1.expires_at
        # Second rejection 30s into the window with a longer cooldown
        time.sleep(0.05)
        entry2 = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="max_daily_loss_hit",
            cooldown_seconds=300,
        )
        assert entry2 is entry1   # same object — extended in place
        assert entry2.rejection_count == 2
        assert entry2.expires_at > first_expiry

    def test_repeat_with_shorter_window_does_not_shrink(self):
        """If we already have a 5min cooldown active, a new 30s
        cooldown call should NOT shrink the window."""
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        e1 = rc.mark_rejection("XLU", "orb", "max_daily_loss_hit", cooldown_seconds=300)
        long_expiry = e1.expires_at
        e2 = rc.mark_rejection("XLU", "orb", "max_daily_loss_hit", cooldown_seconds=10)
        assert e2.expires_at == long_expiry  # still the longer one


# --------------------------------------------------------------------------
# Auto-expiry
# --------------------------------------------------------------------------

class TestAutoExpiry:

    def test_expired_cooldown_no_longer_returns_active(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        # Inject a cooldown that expired in the past
        entry = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="max_daily_loss_hit",
            cooldown_seconds=300,
        )
        # Mutate the expires_at to the past (test-only manipulation)
        entry.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        assert rc.is_in_cooldown("XLU", "orb") is None
        # And it's gone from list_active too
        assert rc.list_active() == []

    def test_zero_cooldown_seconds_is_noop(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        entry = rc.mark_rejection(
            symbol="XLU", setup_type="orb",
            reason="max_daily_loss_hit",
            cooldown_seconds=0,
        )
        assert entry is None
        assert rc.is_in_cooldown("XLU", "orb") is None


# --------------------------------------------------------------------------
# Manual clear
# --------------------------------------------------------------------------

class TestManualClear:

    def test_clear_cooldown_returns_true_when_present(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        assert rc.clear_cooldown("XLU", "orb") is True
        assert rc.is_in_cooldown("XLU", "orb") is None

    def test_clear_cooldown_returns_false_when_absent(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        assert rc.clear_cooldown("ZZZZ", "nonexistent") is False

    def test_clear_all_returns_count(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        rc.mark_rejection("UPS", "gap_fade", "kill_switch_tripped")
        rc.mark_rejection("HOOD", "orb", "max_open_positions exceeded")
        n = rc.clear_all()
        assert n == 3
        assert rc.list_active() == []


# --------------------------------------------------------------------------
# Stats + list_active
# --------------------------------------------------------------------------

class TestStatsAndListActive:

    def test_list_active_returns_dict_snapshots(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        active = rc.list_active()
        assert len(active) == 1
        assert active[0]["symbol"] == "XLU"
        assert active[0]["setup_type"] == "orb"
        assert active[0]["rejection_count"] == 1
        assert "remaining_seconds" in active[0]
        assert "expires_at" in active[0]

    def test_stats_reports_active_count(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        rc.mark_rejection("UPS", "gap_fade", "kill_switch_tripped")
        # Repeat XLU bumps total_rejection_count
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        s = rc.stats()
        assert s["active_cooldowns"] == 2
        assert s["total_rejection_count"] == 3

    def test_empty_inputs_handled_defensively(self):
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        assert rc.mark_rejection(None, "orb", "x") is None
        assert rc.mark_rejection("XLU", None, "x") is None
        assert rc.mark_rejection("XLU", "orb", None) is None
        assert rc.is_in_cooldown(None, "orb") is None
        assert rc.is_in_cooldown("XLU", None) is None
        assert rc.clear_cooldown(None, "orb") is False


# --------------------------------------------------------------------------
# Default cooldown reads from env
# --------------------------------------------------------------------------

class TestDefaultCooldownConfig:

    def test_default_cooldown_seconds_from_env(self, monkeypatch):
        # Reset module + reset singleton before re-import to pick up env
        monkeypatch.setenv("REJECTION_COOLDOWN_SECONDS", "120")
        # Force a re-import so module-level constant is rebuilt
        import importlib
        import services.rejection_cooldown_service as svc
        importlib.reload(svc)
        rc = svc.RejectionCooldown()
        assert rc._default_cooldown_seconds == 120
        # Reload back to default for other tests
        monkeypatch.delenv("REJECTION_COOLDOWN_SECONDS", raising=False)
        importlib.reload(svc)


# --------------------------------------------------------------------------
# Operator API endpoints
# --------------------------------------------------------------------------

class TestRejectionCooldownEndpoints:

    @pytest.mark.asyncio
    async def test_list_endpoint_returns_active_cooldowns(self):
        from routers import trading_bot as tb
        from services.rejection_cooldown_service import get_rejection_cooldown
        get_rejection_cooldown().mark_rejection("XLU", "orb", "max_daily_loss_hit")
        resp = await tb.list_rejection_cooldowns()
        assert resp["success"] is True
        assert len(resp["cooldowns"]) == 1
        assert resp["cooldowns"][0]["symbol"] == "XLU"
        assert resp["stats"]["active_cooldowns"] == 1

    @pytest.mark.asyncio
    async def test_clear_endpoint_clears_one_key(self):
        from routers import trading_bot as tb
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        rc.mark_rejection("UPS", "gap_fade", "max_daily_loss_hit")
        resp = await tb.clear_rejection_cooldown({
            "symbol": "XLU", "setup_type": "orb",
        })
        assert resp["success"] is True
        assert resp["cleared"] is True
        # UPS still in cooldown
        assert rc.is_in_cooldown("UPS", "gap_fade") is not None
        assert rc.is_in_cooldown("XLU", "orb") is None

    @pytest.mark.asyncio
    async def test_clear_all_nukes_everything(self):
        from routers import trading_bot as tb
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        rc.mark_rejection("XLU", "orb", "max_daily_loss_hit")
        rc.mark_rejection("UPS", "gap_fade", "max_daily_loss_hit")
        resp = await tb.clear_rejection_cooldown({"clear_all": True})
        assert resp["success"] is True
        assert resp["cleared_count"] == 2
        assert rc.list_active() == []

    @pytest.mark.asyncio
    async def test_clear_endpoint_400_on_missing_args(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await tb.clear_rejection_cooldown({})
        assert exc.value.status_code == 400
