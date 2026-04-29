"""
Bar Poll Service (DGX-side) — 2026-04-30 v18
==============================================

Companion to the v17 Pusher Rotation Service. Closes the universe-
coverage gap by running **bar-based detectors** against the symbols
that aren't on the live pusher pipe.

Why this exists
---------------
v17 took live-tick coverage from 72 → ~480 symbols. That still leaves
~2,000 of the 2,532 qualified universe with zero scanner attention.
The bar-poll service plugs that gap by reading the existing
``ib_historical_data`` Mongo collection (populated by the always-on
IB historical collectors) and running setup detectors that don't
need live ticks to be useful.

Architecture
------------
This service is **pure DGX-side** — it never calls the IB pusher RPC
and never opens an IB connection. The bar data is already kept fresh
in Mongo by the historical collectors. So this service has zero
external API calls, zero rate-limit pressure, and zero subscription-
budget impact.

The detectors that fire on bar-poll data:
  · `squeeze`        — BB inside KC volatility compression
  · `mean_reversion` — RSI extreme + S/R snapback
  · `chart_pattern`  — multi-bar structure
  · `breakout`       — multi-day high break
  · `hod_breakout`   — high-of-day break (5-min bar precision is fine)

Any alert this service produces is stamped ``data_source="bar_poll_5m"``
on the `LiveAlert` so the AI gate, the V5 UI, and post-mortem queries
can distinguish bar-poll alerts from live-tick alerts. They flow
through the **same** ``LiveAlert`` queue the scanner emits to, so
no downstream changes are needed.

Cadence
-------
RTH (09:30-16:00 ET):
  · Non-subscribed intraday tier (~590 symbols): every 30s
  · Swing tier (888 symbols): every 60s
  · Investment tier (607 symbols): every 2 hours

Off-hours: service idles (no point burning CPU when nothing's moving).

Outputs
-------
Each cycle emits:
  - LiveAlert objects pushed onto ``enhanced_scanner._live_alerts``
    (the scanner's existing dict). Treated identically to scanner-fired
    alerts by every downstream consumer (priority ranking, AI gate,
    auto-eligibility).
  - Audit log row in ``bar_poll_log`` Mongo collection (7d TTL).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# Cadence per pool, in seconds
INTRADAY_NONCORE_INTERVAL_S = 60   # bumped 30→60s 2026-04-30 v19.1 to ease pusher load
SWING_INTERVAL_S = 120              # bumped 60→120s for the same reason
INVESTMENT_INTERVAL_S = 7200  # 2 hours

# Per-cycle batch size — keeps Mongo reads + snapshot computation
# bounded so a slow cycle doesn't compound. 25 is a comfortable size
# (was 50 pre-v19.1; halved after we observed pusher RPC bombardment
# in the wild — the snapshot service now uses mongo_only mode so
# it doesn't hit pusher RPC at all, but the smaller batch also keeps
# event-loop blocks shorter for indicator computation).
BATCH_SIZE = 25

# Detectors that fire on bar-poll snapshots. Live-tick-dependent
# detectors (9_ema_scalp, vwap_continuation, opening_range_break) are
# NOT in this list — they need sub-second timing the bar-poll
# pipeline can't deliver.
BAR_POLL_DETECTORS: List[str] = [
    "squeeze",
    "mean_reversion",
    "chart_pattern",
    "breakout",
    "hod_breakout",
]


@dataclass
class _PoolState:
    """Per-pool cycle state — last poll time + cursor through the symbol pool.

    The cursor enables round-robin batching: if a pool has 600
    symbols and BATCH_SIZE=50, each cycle processes 50 fresh symbols
    and the cursor advances. After 12 cycles all 600 are visited;
    then it loops back to the start.
    """
    name: str
    interval_s: int
    last_run_ts: Optional[datetime] = None
    cursor: int = 0


class BarPollService:
    """Background service that runs bar-based detectors on the
    universe-minus-pusher-subscription pool.

    Lifecycle
    ---------
    Construction is cheap; the actual loop starts when ``start_loop()``
    is called. The trading-bot lifespan owns the loop (mirrors the
    pusher rotation service pattern from v17).
    """

    def __init__(
        self,
        *,
        db=None,
        scanner=None,
        pusher_client=None,
        technical_service=None,
        in_rth_only: bool = True,
    ) -> None:
        self.db = db
        self.scanner = scanner  # enhanced_scanner instance, has _live_alerts
        self.in_rth_only = in_rth_only

        # Wire the pusher client (so we know the live-tick subscriptions
        # to EXCLUDE from the bar-poll universe).
        if pusher_client is None:
            try:
                from services.ib_pusher_rpc import get_pusher_rpc_client
                pusher_client = get_pusher_rpc_client()
            except Exception:
                pusher_client = None
        self.pusher = pusher_client

        # Wire the technical service (Mongo-fed snapshot builder).
        if technical_service is None:
            try:
                from services.realtime_technical_service import (
                    get_realtime_technical_service,
                )
                technical_service = get_realtime_technical_service()
            except Exception:
                technical_service = None
        self.technical = technical_service

        self._pools: Dict[str, _PoolState] = {
            "intraday_noncore": _PoolState(
                name="intraday_noncore", interval_s=INTRADAY_NONCORE_INTERVAL_S,
            ),
            "swing": _PoolState(
                name="swing", interval_s=SWING_INTERVAL_S,
            ),
            "investment": _PoolState(
                name="investment", interval_s=INVESTMENT_INTERVAL_S,
            ),
        }
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_alerts_emitted_count = 0
        self._lifetime_alerts_emitted = 0
        self._last_cycle_summary: Optional[Dict[str, Any]] = None

    # ---- public API -------------------------------------------------------
    async def start_loop(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop_body())
        logger.info("[BarPoll] background loop started")

    async def stop_loop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def status(self) -> Dict[str, Any]:
        """Diagnostic snapshot for /api/diagnostic/bar-poll-status."""
        try:
            current_subs = self.pusher.get_subscribed_set(force_refresh=False) if self.pusher else None
        except Exception:
            current_subs = None
        return {
            "running": self._running,
            "in_rth_only": self.in_rth_only,
            "current_pusher_subscription_count": (
                len(current_subs) if current_subs else 0
            ),
            "pools": [
                {
                    "name": p.name,
                    "interval_s": p.interval_s,
                    "last_run_ts": p.last_run_ts.isoformat() if p.last_run_ts else None,
                    "cursor": p.cursor,
                }
                for p in self._pools.values()
            ],
            "lifetime_alerts_emitted": self._lifetime_alerts_emitted,
            "last_alerts_emitted_count": self._last_alerts_emitted_count,
            "last_cycle_summary": self._last_cycle_summary,
            "detectors": list(BAR_POLL_DETECTORS),
            "batch_size": BATCH_SIZE,
        }

    # ---- pool composition -------------------------------------------------
    def _build_symbol_pools(self) -> Dict[str, List[str]]:
        """Compose the three pools, EXCLUDING anything currently on the
        pusher live-tick pipe (those symbols are covered by the live
        scanner; bar-poll would just produce duplicate alerts)."""
        if self.db is None:
            return {"intraday_noncore": [], "swing": [], "investment": []}

        # Live-tick exclusion set — read fresh each cycle so newly-pinned
        # symbols (rotation just added them) are immediately excluded.
        try:
            current_subs = (
                self.pusher.get_subscribed_set(force_refresh=False)
                if self.pusher else None
            )
        except Exception:
            current_subs = None
        excluded: Set[str] = {s.upper() for s in (current_subs or set())}

        pools: Dict[str, List[str]] = {}
        try:
            # Intraday — skip whatever's already live-streamed
            intraday = [
                d["symbol"] for d in self.db["symbol_adv_cache"].find(
                    {"tier": "intraday",
                     "unqualifiable": {"$ne": True},
                     "avg_dollar_volume": {"$gt": 0}},
                    {"_id": 0, "symbol": 1},
                ).sort("avg_dollar_volume", -1)
                if d.get("symbol") and d["symbol"].upper() not in excluded
            ]
            pools["intraday_noncore"] = intraday

            # Swing — never live-streamed (out of budget by design)
            swing = [
                d["symbol"] for d in self.db["symbol_adv_cache"].find(
                    {"tier": "swing",
                     "unqualifiable": {"$ne": True},
                     "avg_dollar_volume": {"$gt": 0}},
                    {"_id": 0, "symbol": 1},
                ).sort("avg_dollar_volume", -1)
                if d.get("symbol")
            ]
            pools["swing"] = swing

            # Investment — slow cadence, full breadth
            investment = [
                d["symbol"] for d in self.db["symbol_adv_cache"].find(
                    {"tier": "investment",
                     "unqualifiable": {"$ne": True},
                     "avg_dollar_volume": {"$gt": 0}},
                    {"_id": 0, "symbol": 1},
                ).sort("avg_dollar_volume", -1)
                if d.get("symbol")
            ]
            pools["investment"] = investment
        except Exception as e:
            logger.warning(
                "[BarPoll] pool composition failed (%s): %s",
                type(e).__name__, e, exc_info=True,
            )
            pools = {"intraday_noncore": [], "swing": [], "investment": []}
        return pools

    # ---- one cycle for one pool -------------------------------------------
    async def poll_pool_once(self, pool_name: str) -> Dict[str, Any]:
        """Run one batch from `pool_name`. Returns a per-cycle summary.

        Public so the diagnostic endpoint can manually trigger a cycle.
        """
        pool = self._pools.get(pool_name)
        if pool is None:
            return {"error": f"unknown pool: {pool_name}"}

        symbols = self._build_symbol_pools().get(pool_name, [])
        if not symbols:
            return {
                "pool": pool_name,
                "batch_size": 0,
                "alerts_emitted": 0,
                "skipped_no_symbols": True,
            }

        # Round-robin batch slicing
        start = pool.cursor % len(symbols)
        batch = symbols[start:start + BATCH_SIZE]
        if len(batch) < BATCH_SIZE and len(symbols) > BATCH_SIZE:
            # Wrap around so we never short the batch
            batch = batch + symbols[: BATCH_SIZE - len(batch)]
        pool.cursor = (start + BATCH_SIZE) % len(symbols)

        # Build snapshots for the batch (Mongo reads — no IB calls).
        # 2026-04-30 v19.1 — explicitly request `mongo_only=True` so
        # the snapshot service skips its pusher RPC live-bar overlay.
        # Pre-fix: bar poll bombarded the pusher's /rpc/latest-bars
        # endpoint with 50 calls/cycle on the v17-expanded subscription
        # set, hitting IB historical-data rate limits and triggering
        # the "[RPC] latest-bars X failed" cascade + 120s push-to-DGX
        # backend timeouts. With mongo_only the bar poll is fully
        # decoupled from the pusher.
        snapshots: Dict[str, Any] = {}
        if self.technical is not None:
            try:
                snapshots = await self.technical.get_batch_snapshots(
                    batch, mongo_only=True,
                )
            except Exception as e:
                logger.warning(
                    "[BarPoll] snapshot build failed for pool=%s (%s): %s",
                    pool_name, type(e).__name__, e, exc_info=True,
                )

        alerts_emitted = 0
        emitted_setups: Dict[str, int] = {}
        for sym, snap in snapshots.items():
            for det_name in BAR_POLL_DETECTORS:
                try:
                    alert = await self._run_detector(det_name, sym, snap)
                    if alert is not None:
                        alert.data_source = "bar_poll_5m"
                        # Forensic breadcrumb in the reasoning so it's
                        # visible in the V5 UI's alert detail without
                        # surfacing a new field.
                        alert.reasoning = list(alert.reasoning) + [
                            "Source: bar-poll (5min Mongo bars, ~30s lag)"
                        ]
                        await self._emit_alert(alert)
                        alerts_emitted += 1
                        emitted_setups[det_name] = emitted_setups.get(det_name, 0) + 1
                except Exception as e:
                    logger.debug(
                        "[BarPoll] detector %s crashed on %s: %s",
                        det_name, sym, e,
                    )

        pool.last_run_ts = datetime.now(timezone.utc)
        summary = {
            "pool": pool_name,
            "ts": pool.last_run_ts.isoformat(),
            "batch_symbols": len(batch),
            "snapshots_built": len(snapshots),
            "alerts_emitted": alerts_emitted,
            "by_setup": emitted_setups,
            "cursor": pool.cursor,
            "pool_size": len(symbols),
        }
        self._last_alerts_emitted_count = alerts_emitted
        self._lifetime_alerts_emitted += alerts_emitted
        self._last_cycle_summary = summary
        # Audit log
        if self.db is not None:
            try:
                self.db["bar_poll_log"].insert_one({
                    **summary,
                    "ts_dt": pool.last_run_ts,
                })
                # 7-day TTL idempotent
                try:
                    self.db["bar_poll_log"].create_index(
                        "ts_dt", expireAfterSeconds=7 * 24 * 3600,
                    )
                except Exception:
                    pass
            except Exception:
                pass
        return summary

    async def _run_detector(
        self, det_name: str, symbol: str, snap: Any,
    ) -> Optional[Any]:
        """Run a single named bar-based detector and return any LiveAlert
        it produces. Routes via the existing ``enhanced_scanner``
        detector methods so we share their tested logic and don't fork
        the implementations.

        The scanner detectors take a ``tape`` arg derived from live
        ticks; bar-poll has none. We build a no-confirmation neutral
        tape so the detector's tape-confirmation gates default to
        "not confirmed" (which lowers alert priority but never blocks
        emission). That mirrors how the scanner already handles
        symbols whose tape is unavailable.
        """
        if self.scanner is None:
            return None
        check_method = getattr(self.scanner, f"_check_{det_name}", None)
        if check_method is None:
            return None
        # Build a neutral tape — see TapeReading import for the shape.
        tape = self._neutral_tape()
        return await check_method(symbol, snap, tape)

    @staticmethod
    def _neutral_tape() -> Any:
        """Construct a TapeReading with no live confirmation. The
        detector inspects ``tape.confirmation_for_long`` /
        ``tape.confirmation_for_short`` /  ``tape.tape_score`` /
        ``tape.overall_signal``; we return a dataclass-shaped object
        that defaults all of those to falsy / zero / neutral.

        The real ``TapeReading`` dataclass requires many bid/ask
        fields we don't have (no live tape on bar-poll symbols), so
        we fall straight to a duck-typed neutral object — the
        detectors only inspect 4 attributes anyway.
        """
        try:
            from services.enhanced_scanner import TapeSignal
            neutral = TapeSignal.NEUTRAL
        except Exception:
            class _Sig:
                value = "neutral"
                name = "NEUTRAL"
            neutral = _Sig()

        class _NoTape:
            tape_score = 0.0
            confirmation_for_long = False
            confirmation_for_short = False
            signals: list = []
            overall_signal = neutral
            spread_signal = neutral
            imbalance_signal = neutral
            momentum_signal = neutral
        return _NoTape()

    async def _emit_alert(self, alert) -> None:
        """Push a bar-poll-produced alert into the scanner's live
        alerts dict so all downstream consumers (UI, AI gate, bot)
        see it identically to a scanner-fired alert."""
        if self.scanner is None:
            return
        try:
            self.scanner._live_alerts[alert.id] = alert
            # Trigger the scanner's alert-broadcast hook if it exists
            broadcaster = getattr(self.scanner, "_broadcast_alert", None)
            if callable(broadcaster):
                try:
                    await broadcaster(alert)
                except Exception:
                    pass
            # Best-effort persist to live_alerts collection so the
            # rejection-analytics + funnel endpoints see bar-poll
            # alerts identically.
            persister = getattr(self.scanner, "_persist_alert", None)
            if callable(persister):
                try:
                    await persister(alert)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[BarPoll] _emit_alert failed: {e}")

    # ---- main loop --------------------------------------------------------
    @staticmethod
    def _is_in_rth() -> bool:
        from services.pusher_rotation_service import _now_et
        now = _now_et()
        # 09:25 - 16:00 ET; mirror the rotation service's RTH window
        minutes = now.hour * 60 + now.minute
        return (9 * 60 + 25) <= minutes < (16 * 60)

    async def _loop_body(self) -> None:
        TICK_SECONDS = 5
        while self._running:
            try:
                if self.in_rth_only and not self._is_in_rth():
                    await asyncio.sleep(30)
                    continue

                now = datetime.now(timezone.utc)
                for pool_name, pool in self._pools.items():
                    last = pool.last_run_ts
                    elapsed = None if last is None else (now - last).total_seconds()
                    if last is None or (elapsed is not None and elapsed >= pool.interval_s):
                        try:
                            await self.poll_pool_once(pool_name)
                        except Exception as e:
                            logger.exception(
                                "[BarPoll] poll_pool_once(%s) crashed (%s): %s",
                                pool_name, type(e).__name__, e,
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(
                    "[BarPoll] loop iteration crashed (%s): %s",
                    type(e).__name__, e,
                )
            await asyncio.sleep(TICK_SECONDS)


# ---- module singleton -----------------------------------------------------
_bar_poll_service: Optional[BarPollService] = None


def get_bar_poll_service(
    *,
    db=None,
    scanner=None,
    pusher_client=None,
    technical_service=None,
    in_rth_only: bool = True,
) -> BarPollService:
    global _bar_poll_service
    if _bar_poll_service is None:
        _bar_poll_service = BarPollService(
            db=db, scanner=scanner, pusher_client=pusher_client,
            technical_service=technical_service, in_rth_only=in_rth_only,
        )
    return _bar_poll_service


def reset_for_tests() -> None:
    global _bar_poll_service
    _bar_poll_service = None
