"""
IB-Gateway STARTUP health probe — v19.34.308 (2026-06)
======================================================
Boot-time HARD-BLOCK gate. After a backend (re)start the bot could
silently begin a trading session with NO live execution feed (IB Gateway
down at 192.168.50.1:4002, or the ib_direct socket never came up). The
reactive /api/system/health turned yellow but nothing PREVENTED trading.

This probe polls the IB execution path for a bounded grace window after
boot. If the feed never comes up, it:
  1. TRIPS the kill-switch (hard block — the bot cannot arm / open
     entries; reuses the same persisted latch as the daily-loss cap).
  2. Marks /api/system/health RED via the `ib_boot_probe` subsystem.

The block is intentionally manual-reset: once the operator confirms the
feed is live they reset the kill-switch. Auto-re-arming without a human
verifying the feed is exactly the silent-start failure mode we prevent.

SAFETY NOTE (AGENTS.md §2.1): this module NEVER patches the kill-switch
loop itself — it only calls the existing public trip_kill_switch() API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# Module-level latch read by services.system_health_service for the
# `ib_boot_probe` subsystem. status ∈ {"pending", "green", "red"}.
_STATE: Dict[str, Any] = {
    "status": "pending",
    "detail": "probe not yet run",
    "order_path": None,
    "checked_at": None,
    "tripped_kill_switch": False,
    "recovered_at": None,
}


def get_boot_probe_state() -> Dict[str, Any]:
    """Read-only snapshot of the latest boot-probe result."""
    return dict(_STATE)


def _probe_once() -> Tuple[bool, str]:
    """One non-raising connectivity check of the IB EXECUTION feed.

    Returns (ok, detail). Data-feed (pusher push) freshness is NOT a
    hard-block trigger here — at fresh boot no push has flowed yet, so
    keying the block on it would false-positive. Execution connectivity
    is the authoritative "is IB live" signal.
    """
    order_path = (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower()
    _STATE["order_path"] = order_path
    try:
        if order_path == "direct":
            from services.ib_direct_service import get_ib_direct_service
            ibd = get_ib_direct_service()
            if ibd is None:
                return False, "ib_direct_service not initialised"
            if not ibd.is_connected():
                return False, "ib_direct_service NOT connected (execution feed down)"
            return True, "ib_direct connected (execution feed live)"

        # pusher order path
        from services.service_registry import get_service_optional
        ib = get_service_optional("ib_service")
        connected = False
        if ib is not None:
            try:
                if getattr(ib, "connected", False):
                    connected = True
                elif hasattr(ib, "ib") and ib.ib is not None:
                    connected = bool(ib.ib.isConnected())
            except Exception:
                connected = False
        if connected:
            return True, "ib_service connected (execution feed live)"

        # Fall back to pusher RPC reachability as the IB-path signal.
        try:
            from services.ib_pusher_rpc import get_pusher_rpc_client
            s = get_pusher_rpc_client().status()
            reachable = (
                bool(s.get("enabled")) and bool(s.get("url"))
                and (s.get("last_success_ts") is not None
                     or int(s.get("consecutive_failures") or 0) < 5)
            )
            if reachable:
                return True, "pusher RPC reachable (IB path live)"
        except Exception:
            pass
        return False, "no live IB path: ib_service down and pusher unreachable"
    except Exception as exc:  # never raise out of a probe
        return False, f"probe error: {type(exc).__name__}: {str(exc)[:160]}"


async def run_ib_boot_probe(grace_s: float = 30.0, poll_s: float = 2.0,
                            recovery_poll_s: float = 30.0) -> Dict[str, Any]:
    """Poll the IB execution feed for up to `grace_s` seconds. On success,
    mark the subsystem green. On persistent failure, trip the kill-switch
    (HARD BLOCK), mark the subsystem red, and keep re-probing in the
    background so the HEALTH status self-clears once the feed verifies
    live (the kill-switch latch stays manual-reset). Never raises."""
    deadline = time.monotonic() + max(0.0, grace_s)
    ok, detail = False, "probe not yet run"
    # Give the deferred IB connect a moment before the first check.
    await asyncio.sleep(min(5.0, grace_s))
    while True:
        ok, detail = await asyncio.to_thread(_probe_once)
        if ok or time.monotonic() >= deadline:
            break
        await asyncio.sleep(poll_s)

    _STATE["checked_at"] = time.time()
    if ok:
        _STATE["status"] = "green"
        _STATE["detail"] = detail
        logger.info("[IB-BOOT-PROBE] PASS — %s", detail)
        print(f"[STARTUP] v19.34.308 — IB boot probe PASS: {detail}")
        return get_boot_probe_state()

    # Hard block.
    _STATE["status"] = "red"
    _STATE["detail"] = f"IB feed not live after {grace_s:.0f}s boot grace — {detail}"
    logger.error("[IB-BOOT-PROBE] FAIL — %s", _STATE["detail"])
    print(f"[STARTUP] v19.34.308 — IB boot probe FAIL → TRIPPING KILL-SWITCH: {_STATE['detail']}")
    try:
        from services.safety_guardrails import get_safety_guardrails
        await asyncio.to_thread(
            get_safety_guardrails().trip_kill_switch,
            f"ib_gateway_boot_probe_failed: {detail}",
        )
        _STATE["tripped_kill_switch"] = True
    except Exception as exc:
        logger.error("[IB-BOOT-PROBE] FAILED TO TRIP KILL-SWITCH: %s", exc)
        print(f"[STARTUP] v19.34.308 — CRITICAL: could not trip kill-switch: {exc}")

    # v336 — RECOVERY RE-PROBE. The red latch previously persisted for
    # the rest of the session even after IB came up seconds later
    # (observed 2026-06-12: a mid-session restart beat the deferred IB
    # connect, so overall health stayed red + "1 CRITICAL" all day while
    # ib_gateway itself was green). Keep checking in the background and
    # clear the HEALTH status once the execution feed verifies live.
    # The KILL-SWITCH latch is intentionally NOT touched — resetting it
    # stays a manual operator action (silent-start rationale above).
    if recovery_poll_s and recovery_poll_s > 0:
        try:
            asyncio.create_task(_recovery_reprobe(recovery_poll_s))
        except RuntimeError:
            pass  # no running loop — skip background recovery
    return get_boot_probe_state()


async def _recovery_reprobe(poll_s: float) -> None:
    """v336 — after a boot-probe FAIL, re-check the execution feed every
    `poll_s` seconds and flip the health status green once it verifies
    live. Exits on success. Never raises."""
    while _STATE["status"] == "red":
        try:
            await asyncio.sleep(poll_s)
            ok, detail = await asyncio.to_thread(_probe_once)
            if ok:
                now = time.time()
                _STATE["status"] = "green"
                _STATE["recovered_at"] = now
                _STATE["checked_at"] = now
                _STATE["detail"] = (
                    f"recovered: {detail} — boot probe had failed; "
                    "kill-switch latch unchanged (reset manually if tripped)"
                )
                logger.warning("[IB-BOOT-PROBE] RECOVERED — %s", detail)
                print(f"[IB-BOOT-PROBE] v336 — RECOVERED: {detail}")
                return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("[IB-BOOT-PROBE] recovery probe error: %s", exc)
