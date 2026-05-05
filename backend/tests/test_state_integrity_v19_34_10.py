"""
test_state_integrity_v19_34_10.py — drift watchdog (v19.34.10).

Pins behaviour of `services.state_integrity_service.StateIntegrityService`
across the field-policy matrix:
  • Mongo wins for capital/limit fields → in-memory snapped to Mongo.
  • Memory wins for setup_min_rr → memory flushed to Mongo via _save_state.
  • detect_only path emits but never mutates.
  • Auto-resolve respects env flag.
  • Drift events persisted to `state_integrity_events`.
  • Stream emit is best-effort + non-fatal.

Built after the v19.34.9 root cause where in-memory $236k diverged from
Mongo $100k and triggered 135+ rejection brackets on a stale daily-loss
cap. v19.34.10 makes that class of bug auto-detectable + auto-resolved.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Re-init singleton between tests so env flips take effect.
@pytest.fixture(autouse=True)
def _reset_integrity_singleton(monkeypatch):
    import services.state_integrity_service as sis
    sis._integrity_service = None
    # Default-on env for tests
    monkeypatch.setenv("STATE_INTEGRITY_CHECK_ENABLED", "true")
    monkeypatch.setenv("STATE_INTEGRITY_AUTO_RESOLVE", "true")
    monkeypatch.setenv("STATE_INTEGRITY_CHECK_INTERVAL_S", "60")
    yield
    sis._integrity_service = None


# ─── Helpers ─────────────────────────────────────────────────────

def _make_bot(memory_kwargs: dict, mongo_risk_params: dict | None):
    """Build a MagicMock bot with risk_params + a Mongo-stub _db."""
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    rp = RiskParameters()
    for k, v in memory_kwargs.items():
        setattr(rp, k, v)
    bot.risk_params = rp

    bot._save_state = AsyncMock()

    state_doc = {"risk_params": mongo_risk_params} if mongo_risk_params is not None else None
    coll = MagicMock()
    coll.find_one = MagicMock(return_value=state_doc)
    insert_one = MagicMock()
    events_coll = MagicMock()
    events_coll.insert_one = insert_one

    def _getitem(key):
        if key == "bot_state":
            return coll
        if key == "state_integrity_events":
            return events_coll
        return MagicMock()
    bot._db = MagicMock()
    bot._db.__getitem__.side_effect = _getitem
    bot._db._events_insert = insert_one  # convenience for asserts
    return bot


# ─── Mongo-wins policy ───────────────────────────────────────────

class TestMongoWinsPolicy:

    @pytest.mark.asyncio
    async def test_starting_capital_drift_resolved_mongo_to_memory(self):
        """v19.34.9 root-cause case: memory says $100k, Mongo says $236k.
        Watchdog snaps memory back to $236k."""
        from services.state_integrity_service import get_state_integrity_service
        from services.trading_bot_service import RiskParameters
        rp = RiskParameters()
        # Provide a complete Mongo doc so the only drift is on the two
        # capital fields under test.
        full_mongo = {
            "starting_capital": 236487.27,
            "max_daily_loss": 2364.87,
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
            memory_kwargs={"starting_capital": 100000.0, "max_daily_loss": 1000.0},
            mongo_risk_params=full_mongo,
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        assert result.healthy is False
        # Drift on starting_capital + max_daily_loss
        fields = {d.field for d in result.drifts}
        assert "starting_capital" in fields
        assert "max_daily_loss" in fields
        # Memory snapped to Mongo
        assert bot.risk_params.starting_capital == 236487.27
        assert bot.risk_params.max_daily_loss == pytest.approx(2364.87)
        for d in result.drifts:
            assert d.policy == "mongo_wins"
            assert d.resolved is True
            assert d.resolution == "mongo→memory"

    @pytest.mark.asyncio
    async def test_no_drift_when_values_match(self):
        """When memory + mongo agree on every monitored field, healthy=True."""
        from services.state_integrity_service import get_state_integrity_service
        from services.trading_bot_service import RiskParameters
        # Build a Mongo doc that mirrors EVERY field memory has so no
        # drift can fire across either policy.
        rp = RiskParameters()
        full_mongo = {
            "starting_capital": 200000.0,
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
            memory_kwargs={"starting_capital": 200000.0},
            mongo_risk_params=full_mongo,
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        assert result.healthy is True
        assert len(result.drifts) == 0
        assert bot.risk_params.starting_capital == 200000.0

    @pytest.mark.asyncio
    async def test_float_epsilon_avoids_spurious_drift(self):
        """Tiny float jitter (< 0.01) MUST NOT trigger drift events."""
        from services.state_integrity_service import get_state_integrity_service
        from services.trading_bot_service import RiskParameters
        rp = RiskParameters()
        full_mongo = {
            "starting_capital": 100000.000,
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
            memory_kwargs={"starting_capital": 100000.001},
            mongo_risk_params=full_mongo,
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_max_open_positions_drift_resolved(self):
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"max_open_positions": 25},
            mongo_risk_params={"max_open_positions": 10},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        assert any(d.field == "max_open_positions" for d in result.drifts)
        assert bot.risk_params.max_open_positions == 10


# ─── Memory-wins policy ──────────────────────────────────────────

class TestMemoryWinsPolicy:

    @pytest.mark.asyncio
    async def test_setup_min_rr_drift_flushes_memory_to_mongo(self):
        """Operator hot-tunes setup_min_rr in-memory but Mongo is stale.
        Watchdog calls _save_state to flush memory→Mongo."""
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"setup_min_rr": {"squeeze": 1.3, "orb": 2.0}},
            mongo_risk_params={"setup_min_rr": {"squeeze": 1.5}},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        drifts = [d for d in result.drifts if d.field == "setup_min_rr"]
        assert len(drifts) == 1
        assert drifts[0].policy == "memory_wins"
        assert drifts[0].resolved is True
        assert drifts[0].resolution == "memory→mongo"
        bot._save_state.assert_awaited()


# ─── Auto-resolve OFF (detect-only mode) ─────────────────────────

class TestAutoResolveDisabled:

    @pytest.mark.asyncio
    async def test_detect_only_does_not_mutate(self, monkeypatch):
        monkeypatch.setenv("STATE_INTEGRITY_AUTO_RESOLVE", "false")
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        # Drift detected
        assert any(d.field == "starting_capital" for d in result.drifts)
        # But NOT auto-resolved — memory still stale
        assert bot.risk_params.starting_capital == 100000.0
        for d in result.drifts:
            assert d.resolved is False
            assert d.resolution == "detect_only"

    @pytest.mark.asyncio
    async def test_run_check_once_explicit_auto_resolve_override(self):
        """`auto_resolve=False` arg overrides env even when env is true."""
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot, auto_resolve=False)
        assert any(d.field == "starting_capital" for d in result.drifts)
        assert bot.risk_params.starting_capital == 100000.0  # unchanged


# ─── Skip / fail-soft cases ──────────────────────────────────────

class TestSkipAndFailSoft:

    @pytest.mark.asyncio
    async def test_skips_when_bot_state_doc_missing(self):
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(memory_kwargs={"starting_capital": 100000.0}, mongo_risk_params=None)
        svc = get_state_integrity_service()
        result = await svc.run_check_once(bot)
        assert result.skipped is True
        assert result.skip_reason == "bot_state_doc_missing"

    @pytest.mark.asyncio
    async def test_skips_when_db_is_none(self):
        from services.state_integrity_service import get_state_integrity_service
        from services.trading_bot_service import RiskParameters
        bot = MagicMock()
        bot.risk_params = RiskParameters()
        bot._db = None
        svc = get_state_integrity_service()
        result = await svc.run_check_once(bot)
        assert result.skipped is True
        assert result.skip_reason == "bot_not_ready"

    @pytest.mark.asyncio
    async def test_loop_exception_is_caught(self):
        """Mongo transient error should not crash the loop / raise."""
        from services.state_integrity_service import get_state_integrity_service
        from services.trading_bot_service import RiskParameters
        bot = MagicMock()
        bot.risk_params = RiskParameters()
        coll = MagicMock()
        coll.find_one = MagicMock(side_effect=RuntimeError("mongo down"))
        bot._db = MagicMock()
        bot._db.__getitem__.return_value = coll
        svc = get_state_integrity_service()
        result = await svc.run_check_once(bot)
        assert result.healthy is False
        assert result.error is not None and "mongo down" in result.error


# ─── Feature flag (kill switch) ──────────────────────────────────

class TestFeatureFlag:

    @pytest.mark.asyncio
    async def test_disabled_by_env_does_not_start_task(self, monkeypatch):
        monkeypatch.setenv("STATE_INTEGRITY_CHECK_ENABLED", "false")
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        bot = MagicMock()
        await svc.start(bot)
        assert svc.is_running is False

    def test_default_interval_60s(self, monkeypatch):
        monkeypatch.delenv("STATE_INTEGRITY_CHECK_INTERVAL_S", raising=False)
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        assert svc.interval_s == 60

    def test_interval_floor_at_5s(self, monkeypatch):
        monkeypatch.setenv("STATE_INTEGRITY_CHECK_INTERVAL_S", "1")
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        assert svc.interval_s == 5  # safety floor


# ─── Persistence + stream emit ───────────────────────────────────

class TestForensicPersistence:

    @pytest.mark.asyncio
    async def test_drift_persists_to_state_integrity_events(self):
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            await svc.run_check_once(bot)
        # insert_one called on state_integrity_events collection
        assert bot._db._events_insert.called
        doc = bot._db._events_insert.call_args[0][0]
        assert doc["drift_count"] >= 1
        assert any(d["field"] == "starting_capital" for d in doc["drifts"])

    @pytest.mark.asyncio
    async def test_stream_emit_failure_is_swallowed(self):
        """If sentcom_service.emit_stream_event blows up, the check
        MUST still complete cleanly (don't let stream side-effect
        torpedo the drift watcher)."""
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        with patch(
            "services.sentcom_service.emit_stream_event",
            new=AsyncMock(side_effect=RuntimeError("stream broker down")),
            create=True,
        ):
            svc = get_state_integrity_service()
            result = await svc.run_check_once(bot)
        # Drift still detected and resolved despite stream failure
        assert any(d.field == "starting_capital" for d in result.drifts)
        assert bot.risk_params.starting_capital == 236487.27


# ─── Status snapshot for /api/trading-bot/integrity-status ───────

class TestStatusSnapshot:

    @pytest.mark.asyncio
    async def test_status_reports_cumulative_drifts(self):
        from services.state_integrity_service import get_state_integrity_service
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
            svc = get_state_integrity_service()
            await svc.run_check_once(bot)
            await svc.run_check_once(bot)  # second tick: now resolved, no new drift
        status = svc.get_status()
        assert status["cumulative_drift_count"] >= 1
        assert status["cumulative_resolved_count"] >= 1
        assert "field_policy" in status
        assert "starting_capital" in status["field_policy"]["mongo_wins"]

    def test_status_when_never_started(self):
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        status = svc.get_status()
        assert status["running"] is False
        assert status["last_check"] is None
        assert status["cumulative_drift_count"] == 0


# ─── Endpoint smoke tests ────────────────────────────────────────

class TestEndpoints:

    @pytest.mark.asyncio
    async def test_get_integrity_status_endpoint(self):
        from routers import trading_bot as tb
        resp = await tb.get_integrity_status()
        assert resp["success"] is True
        assert "running" in resp
        assert "field_policy" in resp

    @pytest.mark.asyncio
    async def test_force_resync_endpoint_503_when_bot_missing(self):
        from routers import trading_bot as tb
        original = tb._trading_bot
        tb._trading_bot = None
        try:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await tb.force_state_resync({})
            assert exc_info.value.status_code == 503
        finally:
            tb._trading_bot = original

    @pytest.mark.asyncio
    async def test_force_resync_endpoint_dry_run_does_not_mutate(self):
        from routers import trading_bot as tb
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
                resp = await tb.force_state_resync({"dry_run": True})
        finally:
            tb._trading_bot = original
        assert resp["success"] is True
        assert resp["unresolved"] >= 1
        assert bot.risk_params.starting_capital == 100000.0  # not mutated

    @pytest.mark.asyncio
    async def test_force_resync_endpoint_full_run_resolves(self):
        from routers import trading_bot as tb
        bot = _make_bot(
            memory_kwargs={"starting_capital": 100000.0},
            mongo_risk_params={"starting_capital": 236487.27},
        )
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with patch("services.sentcom_service.emit_stream_event", new=AsyncMock(), create=True):
                resp = await tb.force_state_resync({})
        finally:
            tb._trading_bot = original
        assert resp["success"] is True
        assert resp["resolved"] >= 1
        assert bot.risk_params.starting_capital == 236487.27
