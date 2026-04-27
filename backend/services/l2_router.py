"""
L2 Dynamic Router (DGX-side)
=============================
Routes the 3 paper-mode L2 (market depth) subscription slots dynamically
to the top-3 alerts currently in the bot's EVAL stage. Implements
"path B" of the design discussed 2026-04-27:

  • Path B (chosen): give up startup index L2 entirely; all 3 slots
    flow to top-3 EVAL alerts.
  • Path A (rejected): keep startup index L2 + add a 2nd IB clientId
    just for dynamic L2. Adds complexity for marginal benefit (regime
    engine doesn't read L2 imbalance, only price).

How it works:
  1. Every `_TICK_SEC` (default 15s), pull `_live_alerts` from the
     enhanced scanner, sort by (priority DESC, tqs_score DESC,
     created_at DESC), take the top-3 distinct symbols.
  2. Diff against the pusher's current L2 set (`/rpc/l2-subscriptions`).
  3. Call `/rpc/unsubscribe-l2` for symbols dropping out, then
     `/rpc/subscribe-l2` for symbols rotating in.
  4. Stamp `last_routed_at` + ring-buffer the last N routing decisions
     so the operator can audit what got promoted/demoted.

This is loop-driven, not event-driven, because:
  • Alert lifecycles are coarse (entries cluster, expirations every 5-15
    min) — sub-second routing wouldn't add value.
  • IB pacing: subscribing/unsubscribing market depth too rapidly
    triggers their pacing throttle (Error 322). 15s tick gives plenty
    of headroom.
  • Path B explicitly accepts a few seconds of "L2 still on stale
    symbol" lag in exchange for never letting index L2 occupy a slot.

Disable with `ENABLE_L2_DYNAMIC_ROUTING=false` if it's misbehaving;
the pusher endpoints remain available for manual operator control.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_TICK_SEC = 15.0          # how often to evaluate desired L2 set
_MAX_L2_SLOTS = 3         # IB paper-mode hard cap
_AUDIT_RING_SIZE = 50     # last-N routing decisions for /api/l2-router/status
_ALERT_FRESHNESS_SEC = 600  # 10 min — alerts older than this don't qualify


def _is_enabled() -> bool:
    return os.environ.get(
        "ENABLE_L2_DYNAMIC_ROUTING", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}


class L2DynamicRouter:
    """Top-3 EVAL → pusher L2 slots dynamic router."""

    def __init__(self, scanner=None) -> None:
        self._scanner = scanner
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_routed_at: Optional[float] = None
        self._last_desired: List[str] = []
        self._audit: deque = deque(maxlen=_AUDIT_RING_SIZE)
        self._tick_count: int = 0
        self._sub_calls: int = 0
        self._unsub_calls: int = 0
        self._errors: int = 0

    def set_scanner(self, scanner) -> None:
        self._scanner = scanner

    # ---------- top-3 EVAL selection ----------------------------------
    def _compute_desired_l2(self) -> List[str]:
        """
        Build the top-3 EVAL symbol list. "EVAL" = active alerts the
        bot would currently consider for entry. Sort by priority then
        TQS then recency; dedupe by symbol.
        """
        if self._scanner is None:
            return []
        try:
            alerts_dict = getattr(self._scanner, "_live_alerts", None)
            if not alerts_dict:
                return []
            now = datetime.now(timezone.utc)
            from services.enhanced_scanner import AlertPriority
            priority_rank = {
                AlertPriority.CRITICAL: 4,
                AlertPriority.HIGH: 3,
                AlertPriority.MEDIUM: 2,
                AlertPriority.LOW: 1,
            }

            scored: List = []
            for a in alerts_dict.values():
                if getattr(a, "status", "active") != "active":
                    continue
                created = getattr(a, "created_at", None)
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        )
                    except Exception:
                        created = None
                if created is None:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = (now - created).total_seconds()
                if age > _ALERT_FRESHNESS_SEC:
                    continue
                priority_val = priority_rank.get(getattr(a, "priority", None), 1)
                tqs = float(getattr(a, "tqs_score", 0) or 0)
                # Sort key: highest priority first, then highest TQS,
                # then youngest alert.
                sort_key = (priority_val, tqs, -age)
                scored.append((sort_key, a.symbol))

            scored.sort(key=lambda x: x[0], reverse=True)
            seen = set()
            desired: List[str] = []
            for _, sym in scored:
                if sym in seen:
                    continue
                seen.add(sym)
                desired.append(sym)
                if len(desired) >= _MAX_L2_SLOTS:
                    break
            return desired
        except Exception as exc:
            logger.warning(f"l2_router: _compute_desired_l2 failed: {exc}")
            return []

    # ---------- pusher RPC plumbing -----------------------------------
    def _pusher_l2_set(self) -> Optional[List[str]]:
        """Fetch the pusher's current L2 set. Returns None on RPC failure."""
        try:
            from services.ib_pusher_rpc import get_pusher_rpc_client
            client = get_pusher_rpc_client()
            if not client.is_configured():
                return None
            resp = client._request("GET", "/rpc/l2-subscriptions", timeout=3.0)
            if not resp or not resp.get("success"):
                return None
            return list(resp.get("symbols") or [])
        except Exception as exc:
            logger.debug(f"l2_router: pusher l2 fetch failed: {exc}")
            return None

    def _send_unsubscribe_l2(self, symbols: List[str]) -> Dict[str, Any]:
        if not symbols:
            return {"removed": [], "not_found": []}
        try:
            from services.ib_pusher_rpc import get_pusher_rpc_client
            client = get_pusher_rpc_client()
            resp = client._request(
                "POST", "/rpc/unsubscribe-l2",
                json_body={"symbols": symbols}, timeout=10.0,
            )
            self._unsub_calls += 1
            return resp or {}
        except Exception as exc:
            self._errors += 1
            logger.warning(f"l2_router: unsubscribe-l2 failed: {exc}")
            return {}

    def _send_subscribe_l2(self, symbols: List[str]) -> Dict[str, Any]:
        if not symbols:
            return {"added": []}
        try:
            from services.ib_pusher_rpc import get_pusher_rpc_client
            client = get_pusher_rpc_client()
            resp = client._request(
                "POST", "/rpc/subscribe-l2",
                json_body={"symbols": symbols}, timeout=20.0,
            )
            self._sub_calls += 1
            return resp or {}
        except Exception as exc:
            self._errors += 1
            logger.warning(f"l2_router: subscribe-l2 failed: {exc}")
            return {}

    # ---------- one routing tick --------------------------------------
    async def _route_once(self) -> Dict[str, Any]:
        """Compute desired set, diff against pusher, send sub/unsub deltas."""
        self._tick_count += 1
        desired = self._compute_desired_l2()
        current = await asyncio.to_thread(self._pusher_l2_set)
        if current is None:
            # Pusher unreachable → don't route this tick (don't pile up
            # failed sub/unsub calls). The next tick will retry naturally.
            return {"skipped": True, "reason": "pusher_unreachable"}

        current_set = {s.upper() for s in current}
        desired_set = {s.upper() for s in desired}
        to_remove = sorted(current_set - desired_set)
        to_add = sorted(desired_set - current_set)

        if not to_remove and not to_add:
            return {"skipped": True, "reason": "in_sync", "current": sorted(current_set)}

        # Always unsub first to free slots for the new arrivals.
        unsub_resp = await asyncio.to_thread(self._send_unsubscribe_l2, to_remove)
        sub_resp = await asyncio.to_thread(self._send_subscribe_l2, to_add)

        decision = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "desired": desired,
            "current_before": sorted(current_set),
            "added": sub_resp.get("added", []),
            "removed": unsub_resp.get("removed", []),
            "skipped_capped": sub_resp.get("skipped_capped", []),
            "current_after": sub_resp.get("total_l2_subscribed"),
        }
        self._audit.append(decision)
        self._last_routed_at = time.time()
        self._last_desired = desired
        logger.info(
            f"[L2-ROUTER] desired={desired} added={decision['added']} "
            f"removed={decision['removed']} skipped={decision['skipped_capped']}"
        )
        return decision

    # ---------- background loop ---------------------------------------
    async def _loop(self) -> None:
        logger.info(
            f"[L2-ROUTER] started (tick={_TICK_SEC}s, slots={_MAX_L2_SLOTS}, "
            f"freshness={_ALERT_FRESHNESS_SEC}s)"
        )
        # Stagger first run so we don't compete with startup.
        await asyncio.sleep(_TICK_SEC)
        while self._running:
            try:
                await self._route_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._errors += 1
                logger.warning(f"l2_router tick error: {exc}")
            await asyncio.sleep(_TICK_SEC)

    def start(self) -> bool:
        """Start the background routing loop. Idempotent."""
        if not _is_enabled():
            logger.info("[L2-ROUTER] disabled via ENABLE_L2_DYNAMIC_ROUTING=false")
            return False
        if self._running:
            return True
        self._running = True
        try:
            self._task = asyncio.create_task(self._loop())
            return True
        except RuntimeError:
            # No event loop yet — caller invoked start() too early.
            self._running = False
            logger.warning("[L2-ROUTER] start() called before event loop; aborting")
            return False

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": _is_enabled(),
            "running": self._running,
            "tick_count": self._tick_count,
            "sub_calls": self._sub_calls,
            "unsub_calls": self._unsub_calls,
            "errors": self._errors,
            "last_routed_at": self._last_routed_at,
            "last_desired": list(self._last_desired),
            "tick_interval_sec": _TICK_SEC,
            "max_l2_slots": _MAX_L2_SLOTS,
            "alert_freshness_sec": _ALERT_FRESHNESS_SEC,
            "recent_decisions": list(self._audit)[-10:],
        }


# Module-level singleton
_router: Optional[L2DynamicRouter] = None


def get_l2_router() -> L2DynamicRouter:
    global _router
    if _router is None:
        _router = L2DynamicRouter()
    return _router


def init_l2_router(scanner) -> L2DynamicRouter:
    router = get_l2_router()
    router.set_scanner(scanner)
    return router
