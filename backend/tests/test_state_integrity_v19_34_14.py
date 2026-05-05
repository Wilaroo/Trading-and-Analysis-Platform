"""
test_state_integrity_v19_34_14.py — policy flip + drift-loop detector.

Pins v19.34.14 fix for the watchdog regression caught on the operator's
DGX where the v19.34.10 `mongo_wins` policy snapped live IB capital
($236,344.65) DOWN to the mock default ($100,000) — the same
catastrophic skew v19.34.9 was supposed to prevent, but caused by the
watchdog itself.

Pins:
  • `starting_capital`, `max_daily_loss`, `max_notional_per_trade`,
    `max_risk_per_trade` are now MEMORY_WINS (live IB → memory →
    mongo) — the auto-resolve direction is REVERSED vs v19.34.10.
  • `max_open_positions`, `max_position_pct`, `min_risk_reward`,
    `max_daily_loss_pct`, `reconciled_default_*` REMAIN mongo_wins.
  • Drift-loop detector demotes a field to detect-only after
    LOOP_DEMOTE_FLIPS flips in LOOP_DEMOTE_WINDOW_S — prevents the
    watchdog itself from oscillating.
  • `POST /api/trading-bot/force-resync {rearm_demoted: true}` clears
    the demote set so the operator can re-arm a field after fixing
    state manually.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    import services.state_integrity_service as sis
    sis._integrity_service = None
    monkeypatch.setenv("STATE_INTEGRITY_CHECK_ENABLED", "true")
    monkeypatch.setenv("STATE_INTEGRITY_AUTO_RESOLVE", "true")
    yield
    sis._integrity_service = None


def _make_bot(memory_kwargs, mongo_risk_params):
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    rp = RiskParameters()
    for k, v in memory_kwargs.items():
        setattr(rp, k, v)
    bot.risk_params = rp
    bot._save_state = AsyncMock()

    state_doc = {"risk_params": mongo_risk_params} if mongo_risk_params is not None else None
    bot_state_coll = MagicMock()
    bot_state_coll.find_one = MagicMock(return_value=state_doc)
    events_coll = MagicMock()
    events_coll.insert_one = MagicMock()

    def _getitem(key):
        if key == "bot_state":
            return bot_state_coll
        if key == "state_integrity_events":
            return events_coll
        return MagicMock()
    bot._db = MagicMock()
    bot._db.__getitem__.side_effect = _getitem
    return bot


# ─── Policy flip: starting_capital is now MEMORY_WINS ─────────────

class TestPolicyFlip:

    @pytest.mark.asyncio
    async def test_starting_capital_now_memory_wins(self):
        """The exact operator scenario: memory has live IB $236k,
        Mongo has stale $100k. Watchdog must NOT snap memory down."""
        from services.state_integrity_service import (
            get_state_integrity_service, MEMORY_WINS_FIELDS, MONGO_WINS_FIELDS,
        )
        # Compile-time pin: policy is correct
        assert "starting_capital" in MEMORY_WINS_FIELDS
        assert "starting_capital" not in MONGO_WINS_FIELDS

        from services.trading_bot_service import RiskParameters
        rp = RiskParameters()
        full_mongo = {
            "starting_capital": 100000.0,  # stale
            "max_daily_loss": rp.max_daily_loss,
            "max_daily_loss_pct": rp.max_daily_loss_pct,
            "max_open_positions": rp.max_open_positions,
            "max_position_pct": rp.max_position_pct,
            "min_risk_reward": rp.min_risk_reward,
            "max_notional_per_trade": rp.max_notional_per_trade,
            "max_risk_per_trade": rp.max_risk_per_trade,
            "reconciled_default_stop_pct": rp.reconciled_default_stop_pct,
            "reconciled_default_rr": rp.reconciled_default_rr,
            "setup_min_rr": dict(rp.setup_min_rr),
        }
        bot = _make_bot(
            memory_kwargs={"starting_capital": 236344.65},  # live IB
            mongo_risk_params=full_mongo,
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        # Memory PRESERVED at live IB value
        assert bot.risk_params.starting_capital == 236344.65
        # _save_state called → memory→mongo flush
        bot._save_state.assert_awaited()
        drift = next(d for d in result.drifts if d.field == "starting_capital")
        assert drift.policy == "memory_wins"
        assert drift.resolution == "memory→mongo"
        assert drift.resolved is True

    @pytest.mark.asyncio
    async def test_max_open_positions_still_mongo_wins(self):
        """Operator-tuned int field: persisted Mongo IS the intent."""
        from services.state_integrity_service import (
            get_state_integrity_service, MONGO_WINS_FIELDS,
        )
        assert "max_open_positions" in MONGO_WINS_FIELDS
        bot = _make_bot(
            memory_kwargs={"max_open_positions": 25},
            mongo_risk_params={"max_open_positions": 10},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        # Memory snapped to Mongo's persisted value
        assert bot.risk_params.max_open_positions == 10
        drift = next(d for d in result.drifts if d.field == "max_open_positions")
        assert drift.policy == "mongo_wins"
        assert drift.resolution == "mongo→memory"

    @pytest.mark.asyncio
    async def test_capital_derived_fields_all_memory_wins(self):
        """All IB-sourced capital fields flipped together."""
        from services.state_integrity_service import MEMORY_WINS_FIELDS
        for f in ("starting_capital", "max_daily_loss",
                  "max_notional_per_trade", "max_risk_per_trade"):
            assert f in MEMORY_WINS_FIELDS, (
                f"v19.34.14 — {f} must be memory_wins (sourced from IB)"
            )


# ─── Drift-loop detector ──────────────────────────────────────────

class TestDriftLoopDetector:

    @pytest.mark.asyncio
    async def test_demoted_after_3_flips_in_window(self):
        """Same field flipping 3 times → demoted to detect-only."""
        from services.state_integrity_service import get_state_integrity_service

        svc = get_state_integrity_service()
        # Simulate 3 flips of the same field in a fresh window.
        svc._record_flip_and_check_demote("max_open_positions", 25, 10)
        svc._record_flip_and_check_demote("max_open_positions", 5, 10)
        demoted = svc._record_flip_and_check_demote("max_open_positions", 10, 25)
        assert demoted is True
        assert svc._is_demoted("max_open_positions")
        assert "max_open_positions" in svc._demoted_fields

    @pytest.mark.asyncio
    async def test_demoted_field_no_longer_auto_resolves(self):
        """Once demoted, drift is logged but memory NOT mutated."""
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"max_open_positions": 25},
            mongo_risk_params={"max_open_positions": 10},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            # Pre-demote the field by recording 3 flips.
            for i in range(3):
                svc._record_flip_and_check_demote("max_open_positions", i, i + 10)
            assert svc._is_demoted("max_open_positions")

            result = await svc.run_check_once(bot)
        # Drift detected, but NOT auto-resolved
        drift = next(d for d in result.drifts if d.field == "max_open_positions")
        assert drift.resolved is False
        assert drift.resolution == "demoted_loop"
        # Memory NOT changed
        assert bot.risk_params.max_open_positions == 25

    @pytest.mark.asyncio
    async def test_reset_loop_state_rearms(self):
        """`reset_loop_state()` clears demote set so operator can re-arm."""
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        for i in range(3):
            svc._record_flip_and_check_demote("starting_capital", i, i + 10)
        assert svc._is_demoted("starting_capital")
        svc.reset_loop_state()
        assert not svc._is_demoted("starting_capital")
        assert len(svc._demoted_fields) == 0

    @pytest.mark.asyncio
    async def test_status_exposes_demoted_fields(self):
        """`/api/trading-bot/integrity-status` surfaces demoted set."""
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        for i in range(3):
            svc._record_flip_and_check_demote("starting_capital", i, i + 10)
        status = svc.get_status()
        assert "demoted_fields" in status
        assert "starting_capital" in status["demoted_fields"]
        assert status["loop_detector"]["demote_after_flips"] == 3


# ─── force-resync rearm_demoted endpoint flag ─────────────────────

class TestRearmEndpoint:

    @pytest.mark.asyncio
    async def test_force_resync_with_rearm_demoted_clears_set(self):
        """`POST /force-resync {rearm_demoted: true}` clears the demote
        set BEFORE running the check, allowing auto-resolve again."""
        from routers import trading_bot as tb
        from services.state_integrity_service import get_state_integrity_service

        svc = get_state_integrity_service()
        # Pre-demote starting_capital
        for i in range(3):
            svc._record_flip_and_check_demote("starting_capital", i, i + 10)
        assert svc._is_demoted("starting_capital")

        bot = _make_bot(
            memory_kwargs={"max_open_positions": 25},
            mongo_risk_params={"max_open_positions": 10},
        )
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
                resp = await tb.force_state_resync({"rearm_demoted": True})
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        # Demote set was cleared before the check ran
        assert not svc._is_demoted("starting_capital")
        assert len(svc._demoted_fields) == 0
