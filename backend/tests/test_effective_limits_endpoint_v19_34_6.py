"""
test_effective_limits_endpoint_v19_34_6.py — pin the new
/api/trading-bot/effective-limits endpoint added in v19.34.6.

2026-05-05 v19.34.6 — operator-filed bug from 2026-05-04:

  > Morning Prep UI shows max_positions=25, max_daily_loss=$5k (Master
  > Safety Guard). `/api/trading-bot/status` shows max_positions=10,
  > max_daily_loss=$0 (legacy per-trade limits). Two endpoints, two
  > different numbers. Which one actually enforces?

Fix: new `/api/trading-bot/effective-limits` endpoint returns the
intersection (most-restrictive AND) across all guard layers. Delegates
to the existing `compute_effective_risk_caps` service so behavior is
identical to `/api/safety/effective-risk-caps` — operator can hit
either one and get the same canonical answer.

This test pins:
  1. The endpoint exists and routes correctly
  2. It calls compute_effective_risk_caps with the bot's DB
  3. It returns the contract envelope (success + sources + effective + conflicts)
  4. It handles None bot / no DB gracefully
  5. It returns a safe error envelope on internal failures (no 500s)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestEffectiveLimitsEndpointV19_34_6:

    @pytest.mark.asyncio
    async def test_returns_effective_caps_envelope(self):
        """Happy path: endpoint delegates to compute_effective_risk_caps
        and wraps the result in `{success: true, ...}`."""
        from routers import trading_bot as tb

        fake_payload = {
            "sources": {
                "bot": {"max_open_positions": 7, "max_daily_loss_pct": 1.0},
                "safety": {"max_positions": 5, "max_daily_loss_pct": 2.0},
                "sizer": {"max_position_pct": 10.0},
                "dynamic_risk": {"max_daily_loss_pct": 3.0},
            },
            "effective": {
                "max_open_positions": 5,
                "max_daily_loss_pct": 1.0,
                "max_position_pct": 10.0,
            },
            "conflicts": [
                "max_open_positions: bot=7 vs safety=5 → 5 wins (kill switch stricter)",
            ],
            "checked_at": "2026-05-05T13:30:00+00:00",
        }

        # Stub out the bot so the endpoint sees a `_db` to forward
        fake_bot = MagicMock()
        fake_bot._db = MagicMock(name="mock_db")
        original = tb._trading_bot
        tb._trading_bot = fake_bot
        try:
            with patch("services.risk_caps_service.compute_effective_risk_caps",
                       return_value=fake_payload) as mock_compute:
                resp = await tb.get_effective_limits()

            mock_compute.assert_called_once_with(fake_bot._db)
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        assert resp["sources"] == fake_payload["sources"]
        assert resp["effective"] == fake_payload["effective"]
        assert resp["conflicts"] == fake_payload["conflicts"]
        assert resp["checked_at"] == "2026-05-05T13:30:00+00:00"

    @pytest.mark.asyncio
    async def test_handles_none_bot_gracefully(self):
        """If the bot hasn't been wired yet, the endpoint must not 500.
        It should pass `db=None` to the resolver, which the resolver
        already handles by returning empty source dicts."""
        from routers import trading_bot as tb
        original = tb._trading_bot
        tb._trading_bot = None
        try:
            with patch("services.risk_caps_service.compute_effective_risk_caps",
                       return_value={
                           "sources": {}, "effective": {}, "conflicts": [],
                           "checked_at": "ts"
                       }) as mock_compute:
                resp = await tb.get_effective_limits()

            # Called with db=None
            mock_compute.assert_called_once_with(None)
        finally:
            tb._trading_bot = original

        assert resp["success"] is True

    @pytest.mark.asyncio
    async def test_internal_failure_returns_safe_error_envelope(self):
        """If compute_effective_risk_caps raises, the endpoint returns
        success:false with the error — never a 500. The V5 dashboard
        risk card needs to render gracefully even when the resolver
        itself is broken."""
        from routers import trading_bot as tb

        with patch("services.risk_caps_service.compute_effective_risk_caps",
                   side_effect=RuntimeError("simulated resolver crash")):
            resp = await tb.get_effective_limits()

        assert resp["success"] is False
        assert "simulated resolver crash" in resp["error"]
        assert resp["sources"] == {}
        assert resp["effective"] == {}
        assert resp["conflicts"] == []

    @pytest.mark.asyncio
    async def test_payload_intersects_strictest_caps(self):
        """End-to-end against the REAL compute_effective_risk_caps.
        Stubs out env-driven SafetyConfig + Mongo bot_state read; this
        is the actual operator scenario from 2026-05-04 (UI showed 25
        in one place, 10 in another)."""
        from routers import trading_bot as tb
        from services import risk_caps_service

        # Stub Mongo: bot wants 7 positions, 1% daily loss
        fake_db = MagicMock()
        fake_db.__getitem__.return_value.find_one.return_value = {
            "risk_params": {
                "max_open_positions": 7,
                "max_position_pct": 50.0,
                "max_daily_loss_pct": 1.0,
                "max_risk_per_trade": 200.0,
                "min_risk_reward": 2.5,
                "starting_capital": 1_000_000.0,
            }
        }

        fake_bot = MagicMock()
        fake_bot._db = fake_db
        original = tb._trading_bot
        tb._trading_bot = fake_bot

        # Stub SafetyConfig.from_env(): kill switch wants 5 positions,
        # $500 daily loss, 2% pct
        class _FakeSafetyConfig:
            max_positions = 5
            max_daily_loss_usd = 500.0
            max_daily_loss_pct = 2.0
            max_symbol_exposure_usd = None
            max_total_exposure_pct = None
            enabled = True

        try:
            with patch.object(
                risk_caps_service.SafetyConfig,
                "from_env",
                return_value=_FakeSafetyConfig(),
            ):
                resp = await tb.get_effective_limits()
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        # Strictest position cap = min(7, 5) = 5
        assert resp["effective"]["max_open_positions"] == 5
        # Strictest daily loss USD = min(bot computed = 1% × $1M = $10k,
        # safety = $500) = $500
        assert resp["effective"]["max_daily_loss_usd"] == 500.0
        # Strictest daily loss pct = min(1, 2, 3) = 1
        assert resp["effective"]["max_daily_loss_pct"] == 1.0
        # Position pct = min(bot=50, sizer=10) = 10
        assert resp["effective"]["max_position_pct"] == 10.0
        # Conflicts list is human-readable
        assert any("max_open_positions" in c for c in resp["conflicts"])

    @pytest.mark.asyncio
    async def test_response_includes_all_documented_keys(self):
        """Defensive: pin the response shape so a future refactor of
        compute_effective_risk_caps doesn't silently drop a key the V5
        dashboard reads."""
        from routers import trading_bot as tb
        with patch("services.risk_caps_service.compute_effective_risk_caps",
                   return_value={
                       "sources": {"bot": {}, "safety": {}, "sizer": {}, "dynamic_risk": {}},
                       "effective": {},
                       "conflicts": [],
                       "checked_at": "2026-05-05T13:00:00+00:00",
                   }):
            resp = await tb.get_effective_limits()

        for key in ("success", "sources", "effective", "conflicts", "checked_at"):
            assert key in resp, f"missing required key: {key}"
        for src in ("bot", "safety", "sizer", "dynamic_risk"):
            assert src in resp["sources"], f"missing source: {src}"
