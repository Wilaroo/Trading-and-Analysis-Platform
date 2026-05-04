"""
v19.30.13 (2026-05-04) — Three operator-flagged false alarms / bugs:

  1. ADV cache schema clobber: `/api/ai-modules/adv/recalculate` was
     `delete_many({})` + `insert_many` and only wrote `avg_volume`,
     wiping `avg_dollar_volume` and `tier` fields that
     `/api/ib-collector/build-adv-cache` had previously populated.
     Smart-backfill then queried `{avg_dollar_volume: {$gte: ...}}`
     and matched 0 docs even though 9000+ symbols were in the cache.

     Fix: `/api/ai-modules/adv/recalculate` now redirects to the
     canonical builder (`IBHistoricalCollector.rebuild_adv_from_ib_data`)
     so both endpoints converge on the same code path. No schema drift.

  2. `ib_gateway: yellow` false alarm: pusher-only deployment is the
     SentCom standard shape, not a warning. Pre-fix this showed up as
     "1 WARN" in the V5 HUD header forever, sending operators on a
     wild goose chase.

     Fix: `_check_ib_gateway()` returns GREEN when ib_service is
     unregistered AND pusher_rpc is reachable (= valid pusher-only
     deployment). Returns YELLOW only when there's no IB path at all.

  3. Collector `is-active` timeouts: `def is_training_active()` was
     a sync handler running in the thread pool. When Spark was busy
     with scanner / push-data / smart-backfill, the 5s timeout from
     the Windows collector poll would occasionally fire even though
     the handler itself does only ~3 dict reads in microseconds.

     Fix: `def → async def` runs directly on the event loop, no
     thread-pool queuing.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fix 1: ADV recalculate redirects to canonical builder ───────────────────


def test_adv_recalculate_uses_canonical_builder_not_clobbering_script():
    """Source-level pin: `/api/ai-modules/adv/recalculate` MUST call
    `rebuild_adv_from_ib_data` (the canonical builder), NOT the
    `recalculate_adv_cache` script that did `delete_many+insert_many`
    and wiped `avg_dollar_volume`/`tier` fields.
    """
    from routers.ai_modules import recalculate_adv_cache
    src = inspect.getsource(recalculate_adv_cache)
    assert "rebuild_adv_from_ib_data" in src, (
        "recalculate_adv_cache must redirect to the canonical "
        "IBHistoricalCollector.rebuild_adv_from_ib_data builder"
    )
    # Must NOT call the deprecated script that clobbered the schema.
    assert "from scripts.recalculate_adv_cache" not in src
    assert "do_recalc(" not in src


def test_adv_recalculate_calls_collector_when_present():
    """Functional check: recalculate endpoint awaits the collector's
    rebuild method when the collector is available.
    """
    from routers import ai_modules

    fake_collector = MagicMock()
    fake_collector.rebuild_adv_from_ib_data = AsyncMock(return_value={
        "success": True,
        "message": "Rebuilt ADV cache with dollar volume + ATR% for 9412 symbols",
        "symbols_updated": 9412,
        "tier_summary": {"intraday": 1026, "swing": 885, "investment": 603, "skip": 6898},
        "thresholds": {
            "dollar_volume": {"intraday": 50_000_000},
            "atr_pct": {"min": 0.015, "max": 0.1},
        },
    })

    with patch("services.ib_historical_collector.get_ib_collector",
               return_value=fake_collector):
        result = asyncio.run(ai_modules.recalculate_adv_cache())

    assert result["success"] is True
    assert result["symbols_updated"] == 9412
    assert "tier_summary" in result
    # The wrapper adds a `stats` mirror for backwards compatibility.
    assert "stats" in result
    assert result["stats"]["total_symbols"] == 9412
    fake_collector.rebuild_adv_from_ib_data.assert_called_once()


def test_adv_recalculate_503_when_collector_unavailable():
    """If the collector singleton isn't initialised, surface 503
    (not 500 — service is temporarily unavailable, not a code error).
    """
    from routers import ai_modules
    from fastapi import HTTPException

    with patch("services.ib_historical_collector.get_ib_collector",
               return_value=None):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ai_modules.recalculate_adv_cache())

    assert exc.value.status_code == 503


# ─── Fix 2: ib_gateway false-alarm fix ───────────────────────────────────────


def test_ib_gateway_green_for_pusher_only_deployment():
    """When ib_service is unregistered AND pusher_rpc is reachable
    (the SentCom standard deployment), `_check_ib_gateway` must return
    GREEN with detail "pusher-only deployment", NOT a misleading
    yellow "ib_service not registered" warning.
    """
    from services.system_health_service import _check_ib_gateway

    fake_pusher_client = MagicMock()
    fake_pusher_client.status.return_value = {
        "enabled": True,
        "url": "http://192.168.50.1:8765",
        "consecutive_failures": 0,
        "last_success_ts": 1234567890.0,
    }

    with patch("services.service_registry.get_service_optional", return_value=None), \
         patch("services.ib_pusher_rpc.get_pusher_rpc_client",
               return_value=fake_pusher_client):
        result = _check_ib_gateway()

    assert result.status == "green"
    assert "pusher-only" in result.detail.lower() or "pusher" in result.detail.lower()
    assert result.metrics.get("via_pusher") is True


def test_ib_gateway_yellow_when_no_ib_path_at_all():
    """If neither direct IB nor pusher is reachable, that's a real
    yellow — there's NO IB path at all.
    """
    from services.system_health_service import _check_ib_gateway

    fake_pusher_client = MagicMock()
    fake_pusher_client.status.return_value = {
        "enabled": True,
        "url": "http://192.168.50.1:8765",
        "consecutive_failures": 42,
        "last_success_ts": None,
    }

    with patch("services.service_registry.get_service_optional", return_value=None), \
         patch("services.ib_pusher_rpc.get_pusher_rpc_client",
               return_value=fake_pusher_client):
        result = _check_ib_gateway()

    assert result.status == "yellow"
    assert "no IB path" in result.detail
    assert result.metrics.get("via_pusher") is False


def test_ib_gateway_green_when_direct_ib_connected():
    """When direct IB is registered AND connected, return green."""
    from services.system_health_service import _check_ib_gateway

    fake_ib = MagicMock()
    fake_ib.connected = True
    fake_ib.ib = MagicMock()
    fake_ib.ib.isConnected.return_value = True

    with patch("services.service_registry.get_service_optional", return_value=fake_ib):
        result = _check_ib_gateway()

    assert result.status == "green"
    assert result.detail == "connected"
    assert result.metrics["connected"] is True
    assert result.metrics.get("via_pusher") is False


def test_ib_gateway_yellow_when_direct_ib_disconnected():
    """If direct IB is registered but disconnected, that's still
    legitimately yellow — operator deployed direct IB intentionally
    and it's down.
    """
    from services.system_health_service import _check_ib_gateway

    fake_ib = MagicMock()
    fake_ib.connected = False
    fake_ib.ib = None  # Not yet attached

    with patch("services.service_registry.get_service_optional", return_value=fake_ib):
        result = _check_ib_gateway()

    assert result.status == "yellow"
    assert result.metrics["connected"] is False


# ─── Fix 3: ai-training/is-active async ──────────────────────────────────────


def test_is_training_active_is_async():
    """Source-level pin: `is_training_active` MUST be `async def` so
    it runs on the event loop instead of queuing behind other sync
    handlers in the FastAPI thread pool. Was the cause of the Windows
    collector's recurring "Timeout on GET /api/ai-training/is-active"
    warnings even though the handler is microsecond-fast.
    """
    from routers.ai_training import is_training_active
    assert asyncio.iscoroutinefunction(is_training_active), (
        "is_training_active must be `async def` so it runs on the "
        "event loop and never queues behind sync handlers."
    )


def test_is_training_active_returns_idle_when_nothing_running():
    """Default state: no training, no focus mode, no subprocess —
    returns `{"active": False, "reason": "idle"}`.
    """
    from routers import ai_training as at_module

    fake_focus_mgr = MagicMock()
    fake_focus_mgr.get_mode.return_value = "live"

    fake_train_mgr = MagicMock()
    fake_train_mgr.is_training_active.return_value = False

    with patch("services.focus_mode_manager.focus_mode_manager", fake_focus_mgr), \
         patch("services.training_mode.training_mode_manager", fake_train_mgr), \
         patch.object(at_module, "_training_task", None):
        result = asyncio.run(at_module.is_training_active())

    assert result["active"] is False
    assert result["reason"] == "idle"


def test_is_training_active_returns_active_when_focus_mode_training():
    """When focus_mode == 'training', report active with focus_mode reason."""
    from routers import ai_training as at_module

    fake_focus_mgr = MagicMock()
    fake_focus_mgr.get_mode.return_value = "training"

    with patch("services.focus_mode_manager.focus_mode_manager", fake_focus_mgr):
        result = asyncio.run(at_module.is_training_active())

    assert result["active"] is True
    assert "focus_mode" in result["reason"]


def test_is_training_active_swallows_focus_manager_errors():
    """Defensive: if focus_mode_manager throws, fall through to the
    other checks. Operator-side polling must NEVER 500.
    """
    from routers import ai_training as at_module

    fake_train_mgr = MagicMock()
    fake_train_mgr.is_training_active.return_value = False

    with patch("services.focus_mode_manager.focus_mode_manager",
               side_effect=Exception("boom")), \
         patch("services.training_mode.training_mode_manager", fake_train_mgr), \
         patch.object(at_module, "_training_task", None):
        result = asyncio.run(at_module.is_training_active())

    assert result["active"] is False
