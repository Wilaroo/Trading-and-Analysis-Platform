"""
live_health_monitor.py — go-live trip wire (DESIGN SKETCH, parked).

================================================================
STATUS: Scaffolded 2026-04-28e for activation alongside the
        first LIVE flip. Not yet wired into supervisor / startup.
        Activate by:
          1. In `services.trading_bot_service.TradingBotService.start_bot`,
             instantiate `LiveHealthMonitor(self).start()`.
          2. Ensure `_trip_killswitch(reason)` calls
             `self.bot.kill_switch_latch(reason)` — hook already exists.
          3. Add a `/api/trading-bot/live-health` GET endpoint that
             returns `monitor.snapshot()` for the operator dashboard.
================================================================

WHAT IT GUARDS AGAINST
The bot now has many independent execution layers — the kill-switch
latch, account-guard, awaiting-quotes gate, daily-loss limit, and the
new liquidity-aware multipliers. Each layer is correct in isolation,
but **silent drift** between them is the failure mode that kills
unattended overnight runs. Specifically:

  1. Pusher offline > 60s → quote feed stale → bot manages positions
     against last-known prices instead of live ones (silent disaster).
  2. Account-guard mismatch → orders placed on a different account
     than expected (silent risk explosion).
  3. RPC latency p99 > 5s over a 2-min window → degraded execution
     (slippage spikes, potentially orders timing out).
  4. > 5 consecutive order rejects → broker-side issue (rate limits,
     halted symbols, margin call).
  5. Bot heartbeat stale > 90s → orchestrator stuck (deadlock,
     blocking task on the main loop).

When ANY of these trips, the monitor calls `bot.kill_switch_latch()`
which immediately:
  - Cancels all in-flight orders
  - Stops processing new alerts
  - Writes a `kill_switch_history` doc with the reason
  - Surfaces a red banner in the V5 view

================================================================
INTERFACE
================================================================
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─── Tuning knobs (all exported so an admin endpoint can tune live) ────

CHECK_INTERVAL_SEC = 30
PUSHER_OFFLINE_TRIP_SEC = 60
RPC_LATENCY_P99_TRIP_MS = 5000
RPC_LATENCY_WINDOW_SEC = 120
ORDER_REJECT_TRIP_COUNT = 5
BOT_HEARTBEAT_TRIP_SEC = 90


class LiveHealthMonitor:
    """A small async daemon that polls every CHECK_INTERVAL_SEC and
    trips the kill-switch on any of the documented failure modes.
    Designed to be a thin, single-responsibility safety wire — no
    business logic, no recovery attempts, just observation + trip."""

    def __init__(self, bot: "TradingBotService"):  # noqa: F821
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._rpc_latencies: deque = deque(maxlen=500)
        self._consecutive_rejects = 0
        self._last_snapshot: Dict[str, Any] = {}

    # ── Public API ──────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="live_health_monitor")
        logger.info("LiveHealthMonitor: started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
        logger.info("LiveHealthMonitor: stopped")

    def record_rpc_latency_ms(self, ms: float) -> None:
        self._rpc_latencies.append((time.time(), float(ms)))

    def record_order_outcome(self, accepted: bool) -> None:
        if accepted:
            self._consecutive_rejects = 0
        else:
            self._consecutive_rejects += 1

    def snapshot(self) -> Dict[str, Any]:
        """Read-only operator snapshot. Safe to call from any thread."""
        return dict(self._last_snapshot)

    # ── Internal loop ───────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_once()
            except Exception as e:
                logger.exception(f"LiveHealthMonitor.check_once failed: {e}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=CHECK_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass

    async def _check_once(self) -> None:
        now = time.time()
        snap: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tripped": False,
            "trips": [],
        }

        # 1. Pusher freshness
        last_pusher_ts = getattr(self.bot, "_last_pusher_heartbeat_ts", None)
        if last_pusher_ts is not None:
            pusher_age = now - float(last_pusher_ts)
            snap["pusher_age_sec"] = round(pusher_age, 1)
            if pusher_age > PUSHER_OFFLINE_TRIP_SEC:
                snap["trips"].append(f"pusher_offline_{pusher_age:.0f}s")

        # 2. Account-guard mismatch
        ag = getattr(self.bot, "_account_guard_status", None)
        if isinstance(ag, dict):
            snap["account_guard_ok"] = bool(ag.get("ok", True))
            if ag.get("ok") is False:
                snap["trips"].append(
                    f"account_guard_mismatch_{ag.get('reason') or 'unknown'}"
                )

        # 3. RPC latency p99 over WINDOW_SEC
        cutoff = now - RPC_LATENCY_WINDOW_SEC
        recent = [ms for ts, ms in self._rpc_latencies if ts >= cutoff]
        if len(recent) >= 30:    # need ≥30 samples to avoid spurious p99s
            recent_sorted = sorted(recent)
            p99 = recent_sorted[int(len(recent_sorted) * 0.99)]
            snap["rpc_p99_ms"] = round(p99, 1)
            if p99 > RPC_LATENCY_P99_TRIP_MS:
                snap["trips"].append(f"rpc_p99_{p99:.0f}ms")

        # 4. Consecutive order rejects
        snap["consecutive_rejects"] = self._consecutive_rejects
        if self._consecutive_rejects >= ORDER_REJECT_TRIP_COUNT:
            snap["trips"].append(
                f"consecutive_rejects_{self._consecutive_rejects}"
            )

        # 5. Bot heartbeat
        last_bot_ts = getattr(self.bot, "_last_loop_iteration_ts", None)
        if last_bot_ts is not None:
            bot_age = now - float(last_bot_ts)
            snap["bot_loop_age_sec"] = round(bot_age, 1)
            if bot_age > BOT_HEARTBEAT_TRIP_SEC:
                snap["trips"].append(f"bot_loop_stuck_{bot_age:.0f}s")

        if snap["trips"]:
            snap["tripped"] = True
            self._trip_killswitch("|".join(snap["trips"]))
        self._last_snapshot = snap

    def _trip_killswitch(self, reason: str) -> None:
        """Fire the bot's kill-switch latch. Safe to call repeatedly —
        the latch is idempotent."""
        try:
            if hasattr(self.bot, "kill_switch_latch"):
                self.bot.kill_switch_latch(f"live_health_monitor:{reason}")
            else:
                # Fallback: pause the bot
                self.bot.is_active = False
            logger.error(f"LiveHealthMonitor TRIPPED: {reason}")
        except Exception as e:
            logger.exception(f"LiveHealthMonitor: kill-switch fire failed: {e}")
