"""
Pusher Rotation Service (DGX side) — 2026-04-30 v17
====================================================

The Windows-side IB Pusher streams live Level-1 quotes for a set of
symbols. The DGX backend uses those streams to drive every live-tick
detector (RVOL spike, EMA9 distance, OR break, VWAP fade, etc.).

Pre-v17 the pusher subscription was a static 72-symbol list configured
on the Windows side. With the operator's 2026-04-30 IB Quote Booster
upgrade (5 packs × 100 lines = **500 simultaneous lines** budget) the
DGX side can now manage the subscription **dynamically** — swap
symbols in/out throughout the day so live detectors see the right
universe at the right time.

Architecture
------------
The 500-line budget is split into 5 cohorts:

    Cohort         Size   Refresh                   Source
    ─────────────  ─────  ────────────────────────  ───────────────────
    PINNED ETFs    30     load once at startup      static list
    OPEN POSITIONS dyn    on every cycle            bot._open_trades
    STATIC CORE    300    once per trading day      top-N by ADV
    HOT SLOTS      50     04:30 / 07:00 / 08:30 /   premarket gappers
                          09:25 ET                  + news + halts
    DYNAMIC OVERLAY 100   every 15min in RTH        RVOL / sector / news

    SAFETY BUFFER  20     never fill — leaves headroom for IB pacing

    TOTAL BUDGET   500    matches account capacity

Hard invariants (pytest-guarded)
--------------------------------
1. Total subscribed symbols at any moment ≤ ``MAX_LINES`` (500).
2. **Open positions never get unsubscribed.** Even if the rotation
   would prefer to swap them out, the diff-and-apply layer pins them
   first. A held-position symbol with a stale tick during a stop check
   is the worst possible outcome — we'd close on bad data.
3. Pinned ETFs never get unsubscribed.
4. Subscribe-set growth is always idempotent (re-subscribing a symbol
   the pusher already has is a no-op).

Rotation cycle (single source of truth — :func:`compose_target_set`)
--------------------------------------------------------------------
Each cycle:
  1. Read **current** pusher subscriptions (RPC).
  2. Compose **target** set from the cohorts above (priority-ordered).
  3. ``to_add = target - current`` ; ``to_remove = current - target``.
  4. Apply: subscribe(to_add), unsubscribe(to_remove).
  5. Audit: write the diff to ``pusher_rotation_log`` collection.

The cohort composition is deterministic — given the same DB state and
clock, two consecutive calls to :func:`compose_target_set` return the
same set. That makes diffs idempotent and tests trivially reproducible.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---- Budget constants -----------------------------------------------------
# Operator-confirmed 2026-04-30: 5 Quote Booster packs × 100 = 500 lines.
# Buffer of 20 means the rotation NEVER tries to use more than 480 lines
# of the budget, leaving room for IB pacing latency / contract
# qualification spikes.
MAX_LINES: int = 500
SAFETY_BUFFER: int = 20
USABLE_LINES: int = MAX_LINES - SAFETY_BUFFER  # 480

# Cohort sizes — sum to 480
PINNED_ETF_BUDGET: int = 30
STATIC_CORE_BUDGET: int = 300
HOT_SLOT_BUDGET: int = 50
DYNAMIC_OVERLAY_BUDGET: int = 100
# Open positions are dynamic (not part of the 480 split). They're
# pinned first; if the operator opens 47 positions, we cut the dynamic
# overlay to make room. Open positions ALWAYS win.

# Always-on ETFs/indices. Same list as
# `symbol_universe.get_pusher_l1_recommendations` for consistency. Bumped
# to 30 to fit the budget cleanly with sector + size + style + vol/credit.
DEFAULT_PINNED_ETFS: List[str] = [
    # Major indices
    "SPY", "QQQ", "IWM", "DIA", "VIX",
    # SPDR sector ETFs (11)
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC",
    # Size / style
    "VTV", "VUG", "MDY", "SLY",
    # Volatility / credit / commodity / international
    "TLT", "HYG", "GLD", "SLV", "USO", "EEM", "EFA",
    # Crypto / popular leveraged
    "IBIT", "TQQQ", "SQQQ",
]
assert len(DEFAULT_PINNED_ETFS) >= PINNED_ETF_BUDGET, (
    "DEFAULT_PINNED_ETFS must have at least PINNED_ETF_BUDGET entries"
)


# ---- Profile selection ----------------------------------------------------
# Time-of-day determines how the HOT_SLOT_BUDGET is allocated. The static
# core + pinned ETFs + open positions never change between profiles —
# only the hot slots do.

class Profile:
    """Time-of-day profile for hot-slot allocation."""
    PRE_MARKET_EARLY = "pre_market_early"   # 04:00-07:00 ET — premarket gappers
    PRE_MARKET_LATE  = "pre_market_late"    # 07:00-09:25 ET — premarket movers + news
    RTH_OPEN         = "rth_open"           # 09:25-10:30 ET — opening range / gap-and-go
    RTH_MIDDAY       = "rth_midday"         # 10:30-13:30 ET — RVOL leaders + sector
    RTH_AFTERNOON    = "rth_afternoon"      # 13:30-16:00 ET — afternoon movers
    POST_MARKET      = "post_market"        # 16:00-04:00 ET — minimal hot slots


def _now_et() -> datetime:
    """Best-effort 'now in ET'. We don't import pytz here to keep the
    service dependency-light; we approximate via UTC offset of -4 (EDT)
    or -5 (EST). The schedule uses 1-hour granularity so the half-hour
    DST drift on the boundary days doesn't matter."""
    utc = datetime.now(timezone.utc)
    # Approximate: month 3-10 ≈ EDT (-4), 11-2 ≈ EST (-5)
    is_dst = 3 <= utc.month <= 10
    offset = -4 if is_dst else -5
    return utc + timedelta(hours=offset)


def select_profile(now_et: Optional[datetime] = None) -> str:
    """Return the active profile name based on ET wall-clock time."""
    now = now_et or _now_et()
    h, m = now.hour, now.minute
    minutes = h * 60 + m
    if 4 * 60 <= minutes < 7 * 60:
        return Profile.PRE_MARKET_EARLY
    if 7 * 60 <= minutes < (9 * 60 + 25):
        return Profile.PRE_MARKET_LATE
    if (9 * 60 + 25) <= minutes < (10 * 60 + 30):
        return Profile.RTH_OPEN
    if (10 * 60 + 30) <= minutes < (13 * 60 + 30):
        return Profile.RTH_MIDDAY
    if (13 * 60 + 30) <= minutes < (16 * 60):
        return Profile.RTH_AFTERNOON
    return Profile.POST_MARKET


# ---- Cohort composition ---------------------------------------------------

def _read_static_core(db, budget: int = STATIC_CORE_BUDGET) -> List[str]:
    """Top-N intraday-tier symbols by ADV. Stable for the whole trading
    day (no need to re-query mid-cycle)."""
    if db is None:
        return []
    try:
        cursor = (
            db["symbol_adv_cache"]
            .find(
                {"tier": "intraday",
                 "unqualifiable": {"$ne": True},
                 "avg_dollar_volume": {"$gt": 0}},
                {"_id": 0, "symbol": 1},
            )
            .sort("avg_dollar_volume", -1)
            .limit(int(budget))
        )
        return [d["symbol"] for d in cursor if d.get("symbol")]
    except Exception as e:
        logger.warning(
            "static_core read failed (%s): %s", type(e).__name__, e, exc_info=True,
        )
        return []


def _read_open_position_symbols(bot) -> Set[str]:
    """Live snapshot of currently held positions on the bot. NEVER cached
    — the rotation service queries this fresh every cycle so an open
    position can never be silently rotated out.

    Pulls from ``bot._open_trades`` (in-memory cache that mirrors the
    ``bot_trades`` collection's OPEN/PARTIAL rows). Falls back to None
    if the bot reference isn't available; the caller treats missing as
    "no positions to pin" but logs a WARN — silent failure here would
    re-introduce the v13-class regression."""
    if bot is None:
        logger.warning(
            "[PusherRotation] bot reference is None — open positions "
            "WILL NOT be pinned this cycle. This is unsafe; check the "
            "rotation service's bot wiring."
        )
        return set()
    try:
        open_trades = getattr(bot, "_open_trades", None)
        if open_trades is None:
            return set()
        # Defensive: support dict {trade_id: BotTrade} OR list[BotTrade]
        if isinstance(open_trades, dict):
            iterable = open_trades.values()
        else:
            iterable = open_trades
        symbols: Set[str] = set()
        for t in iterable:
            sym = getattr(t, "symbol", None) or (
                t.get("symbol") if isinstance(t, dict) else None
            )
            if sym:
                symbols.add(str(sym).upper().strip())
        return symbols
    except Exception as e:
        logger.warning(
            "[PusherRotation] open-positions read failed (%s): %s",
            type(e).__name__, e, exc_info=True,
        )
        return set()


def _read_pending_order_symbols(bot) -> Set[str]:
    """Symbols with a pending order in `bot._pending_trades`. Same
    rationale as open positions — if we have an order in flight, we
    MUST keep its quote stream live."""
    if bot is None:
        return set()
    try:
        pending = getattr(bot, "_pending_trades", None) or {}
        symbols: Set[str] = set()
        if isinstance(pending, dict):
            for t in pending.values():
                sym = getattr(t, "symbol", None)
                if sym:
                    symbols.add(str(sym).upper().strip())
        return symbols
    except Exception:
        return set()


def compose_target_set(
    db,
    bot,
    *,
    pinned_etfs: Optional[List[str]] = None,
    profile: Optional[str] = None,
    hot_slots_provider=None,
    dynamic_overlay_provider=None,
    static_core_override: Optional[List[str]] = None,
    max_lines: int = MAX_LINES,
    safety_buffer: int = SAFETY_BUFFER,
) -> Dict[str, Any]:
    """Compose the desired pusher subscription set for **right now**.

    Priority order (later cohorts only join if budget remains):
      1. Open positions  ── safety, MUST pin
      2. Pending orders  ── safety, MUST pin
      3. Pinned ETFs     ── always-on context tape
      4. Static core     ── top-N intraday by ADV
      5. Hot slots       ── time-of-day specific
      6. Dynamic overlay ── per-cycle scoring

    Returns:
        {
            "target": Set[str],                # the full subscription set
            "by_cohort": {cohort: List[str]},  # for diagnostics
            "profile": str,
            "budget_used": int,
            "budget_max": int,                  # max_lines - safety_buffer
            "dropped_for_budget": List[str],   # what didn't fit
            "warnings": List[str],
        }
    """
    pinned_etfs = pinned_etfs or DEFAULT_PINNED_ETFS
    profile = profile or select_profile()
    usable = max_lines - safety_buffer

    # Cohort 1: open positions (HARD pin — never displaceable)
    open_pos = _read_open_position_symbols(bot)
    pending_orders = _read_pending_order_symbols(bot)
    safety_pinned = open_pos | pending_orders

    # Cohort 2: pinned ETFs
    etfs = [s.upper().strip() for s in pinned_etfs[:PINNED_ETF_BUDGET] if s]

    # Cohort 3: static core
    if static_core_override is not None:
        core = [s.upper().strip() for s in static_core_override[:STATIC_CORE_BUDGET] if s]
    else:
        core = _read_static_core(db, budget=STATIC_CORE_BUDGET)

    # Cohort 4 + 5: providers (callable → List[str])
    hot_slots: List[str] = []
    if hot_slots_provider is not None:
        try:
            hot_slots = list(hot_slots_provider(profile=profile, db=db, bot=bot) or [])
        except Exception as e:
            logger.warning(
                "[PusherRotation] hot_slots_provider failed (%s): %s",
                type(e).__name__, e, exc_info=True,
            )
            hot_slots = []
    dynamic: List[str] = []
    if dynamic_overlay_provider is not None:
        try:
            dynamic = list(dynamic_overlay_provider(profile=profile, db=db, bot=bot) or [])
        except Exception as e:
            logger.warning(
                "[PusherRotation] dynamic_overlay_provider failed (%s): %s",
                type(e).__name__, e, exc_info=True,
            )
            dynamic = []

    # Compose, deduped, in priority order. Track which cohort each
    # symbol came from for diagnostics.
    seen: Set[str] = set()
    target: List[str] = []
    by_cohort: Dict[str, List[str]] = {
        "open_positions": [],
        "pending_orders": [],
        "pinned_etfs": [],
        "static_core": [],
        "hot_slots": [],
        "dynamic_overlay": [],
    }
    dropped: List[str] = []

    def _add(sym: str, cohort_name: str, ceiling: Optional[int] = None) -> bool:
        sym = sym.upper().strip()
        if not sym:
            return False
        if sym in seen:
            return True  # already in (from a higher-priority cohort)
        if len(target) >= usable:
            dropped.append(f"{cohort_name}:{sym}")
            return False
        if ceiling is not None and len(by_cohort[cohort_name]) >= ceiling:
            dropped.append(f"{cohort_name}:{sym}")
            return False
        seen.add(sym)
        target.append(sym)
        by_cohort[cohort_name].append(sym)
        return True

    # 1. Open positions (no ceiling — safety always wins)
    for sym in sorted(open_pos):
        _add(sym, "open_positions", ceiling=None)
    # 2. Pending orders (no ceiling)
    for sym in sorted(pending_orders):
        _add(sym, "pending_orders", ceiling=None)
    # 3. Pinned ETFs (capped at PINNED_ETF_BUDGET)
    for sym in etfs:
        _add(sym, "pinned_etfs", ceiling=PINNED_ETF_BUDGET)
    # 4. Static core (capped at STATIC_CORE_BUDGET)
    for sym in core:
        _add(sym, "static_core", ceiling=STATIC_CORE_BUDGET)
    # 5. Hot slots (capped at HOT_SLOT_BUDGET)
    for sym in hot_slots:
        _add(sym, "hot_slots", ceiling=HOT_SLOT_BUDGET)
    # 6. Dynamic overlay (capped at DYNAMIC_OVERLAY_BUDGET)
    for sym in dynamic:
        _add(sym, "dynamic_overlay", ceiling=DYNAMIC_OVERLAY_BUDGET)

    warnings: List[str] = []
    if len(target) >= usable:
        warnings.append(
            f"budget full at {len(target)}/{usable} — dropped "
            f"{len(dropped)} candidates"
        )
    if not safety_pinned and not open_pos and not pending_orders:
        # Operator may genuinely have 0 positions; informational only.
        pass

    return {
        "target": set(target),
        "target_list": target,  # ordered for diagnostics
        "by_cohort": by_cohort,
        "profile": profile,
        "budget_used": len(target),
        "budget_max": usable,
        "max_lines": max_lines,
        "safety_buffer": safety_buffer,
        "dropped_for_budget": dropped,
        "safety_pinned_count": len(safety_pinned),
        "warnings": warnings,
    }


# ---- Diff and apply -------------------------------------------------------

def compute_diff(
    current: Set[str],
    target: Set[str],
    *,
    safety_pinned: Optional[Set[str]] = None,
) -> Dict[str, Set[str]]:
    """Compute the set difference for diff-and-apply.

    The ``safety_pinned`` set is symbols that MUST stay subscribed
    regardless of target membership (open positions, pending orders).
    They get added to ``target`` if missing, and any attempt to remove
    them is filtered out — even if the caller passed a target that
    doesn't include them.

    Returns:
        {
            "to_add": Set[str],      # in target, not in current
            "to_remove": Set[str],   # in current, not in target, NOT safety-pinned
            "would_remove_held": Set[str],  # safety violations we filtered out
            "kept": Set[str],         # stays as-is
        }
    """
    safety_pinned = safety_pinned or set()
    # Diagnostic: which safety-pinned symbols would have been removed
    # by the *raw* target (before we patched it). Useful for test
    # canaries — empty in healthy code, non-empty if the caller
    # forgot a held position.
    raw_target = target
    would_remove_held = (current - raw_target) & safety_pinned
    # Force safety pins into target so we never "remove" them via a target gap
    target = target | safety_pinned
    to_add = target - current
    naive_remove = current - target
    # Belt-and-braces: even after the union above, double-check we never
    # remove a safety-pinned symbol. This catches a future contributor
    # swapping the operator pattern.
    to_remove = naive_remove - safety_pinned
    kept = current & target
    return {
        "to_add": to_add,
        "to_remove": to_remove,
        "would_remove_held": would_remove_held,
        "kept": kept,
    }


# ---- The service object ---------------------------------------------------

class PusherRotationService:
    """High-level rotation orchestrator. Holds the loop state, the audit
    log writer, and the bot/db wiring. Construction is cheap; call
    ``rotate_once()`` to run a single cycle, or ``start_loop()`` to
    keep rotating forever (intended to be launched once at backend
    startup)."""

    # Refresh cadence per cohort during RTH. Pre/post-market the loop
    # runs more slowly because nothing is moving.
    HOT_SLOT_REFRESH_TIMES_ET = [
        (4, 30), (7, 0), (8, 30), (9, 25),
    ]
    DYNAMIC_OVERLAY_REFRESH_INTERVAL_MIN = 15
    LOOP_TICK_SECONDS = 60  # check every minute whether a refresh is due

    def __init__(
        self,
        *,
        db=None,
        bot=None,
        pusher_client=None,
        hot_slots_provider=None,
        dynamic_overlay_provider=None,
    ) -> None:
        self.db = db
        self.bot = bot
        if pusher_client is None:
            from services.ib_pusher_rpc import get_pusher_rpc_client
            pusher_client = get_pusher_rpc_client()
        self.pusher = pusher_client
        self.hot_slots_provider = hot_slots_provider
        self.dynamic_overlay_provider = dynamic_overlay_provider

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_rotation: Optional[Dict[str, Any]] = None
        self._last_dynamic_refresh_minute: Optional[int] = None
        self._last_hot_refresh_key: Optional[Tuple[int, int]] = None

    # ---- single rotation --------------------------------------------------
    def rotate_once(self, *, dry_run: bool = False) -> Dict[str, Any]:
        """Run one rotation cycle. Returns a structured summary suitable
        for the diagnostic endpoint and the audit log.

        ``dry_run=True`` composes the target set and computes the diff
        without calling the pusher RPC (used by tests + the diagnostic
        endpoint when the operator wants to preview a change).
        """
        composed = compose_target_set(
            db=self.db,
            bot=self.bot,
            hot_slots_provider=self.hot_slots_provider,
            dynamic_overlay_provider=self.dynamic_overlay_provider,
        )
        target = composed["target"]
        safety_pinned = (
            _read_open_position_symbols(self.bot)
            | _read_pending_order_symbols(self.bot)
        )

        if dry_run:
            current = self.pusher.get_subscribed_set() or set()
            diff = compute_diff(current, target, safety_pinned=safety_pinned)
            return {
                "dry_run": True,
                "current_count": len(current),
                **composed,
                "diff": {
                    "to_add": sorted(diff["to_add"]),
                    "to_remove": sorted(diff["to_remove"]),
                    "would_remove_held": sorted(diff["would_remove_held"]),
                    "kept_count": len(diff["kept"]),
                },
                "applied": False,
            }

        # Live path: read current → diff → apply via RPC → audit
        current = self.pusher.get_subscribed_set()
        if current is None:
            logger.warning(
                "[PusherRotation] cannot read current subscriptions — "
                "pusher RPC unreachable. Skipping rotation."
            )
            return {
                "applied": False,
                "error": "pusher_unreachable",
                **composed,
            }

        diff = compute_diff(current, target, safety_pinned=safety_pinned)
        sub_resp = unsub_resp = None
        if diff["to_remove"]:
            unsub_resp = self.pusher.unsubscribe_symbols(diff["to_remove"])
        if diff["to_add"]:
            sub_resp = self.pusher.subscribe_symbols(diff["to_add"])

        result = {
            "applied": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "current_before": len(current),
            "diff": {
                "to_add": sorted(diff["to_add"]),
                "to_remove": sorted(diff["to_remove"]),
                "would_remove_held": sorted(diff["would_remove_held"]),
                "kept_count": len(diff["kept"]),
            },
            "subscribe_response": sub_resp,
            "unsubscribe_response": unsub_resp,
            **composed,
        }
        self._last_rotation = result
        self._write_audit_log(result)
        return result

    def _write_audit_log(self, result: Dict[str, Any]) -> None:
        if self.db is None:
            return
        try:
            self.db["pusher_rotation_log"].insert_one({
                "ts": result.get("ts"),
                "ts_dt": datetime.now(timezone.utc),
                "profile": result.get("profile"),
                "budget_used": result.get("budget_used"),
                "added": result["diff"]["to_add"],
                "removed": result["diff"]["to_remove"],
                "would_remove_held": result["diff"]["would_remove_held"],
                "by_cohort": {
                    k: len(v) for k, v in (result.get("by_cohort") or {}).items()
                },
                "safety_pinned_count": result.get("safety_pinned_count"),
            })
            # 7-day TTL (idempotent — Mongo silently no-ops if it exists)
            try:
                self.db["pusher_rotation_log"].create_index(
                    "ts_dt", expireAfterSeconds=7 * 24 * 3600,
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"[PusherRotation] audit log write failed: {e}")

    # ---- background loop --------------------------------------------------
    async def start_loop(self) -> None:
        """Start the rotation loop. Idempotent; calling twice is a no-op."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop_body())
        logger.info("[PusherRotation] background loop started")

    async def stop_loop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def _is_refresh_due(self) -> Tuple[bool, str]:
        """Decide whether this tick should rotate. Returns (yes, reason)."""
        now = _now_et()
        # Hot-slot refresh: scheduled times.
        for h, m in self.HOT_SLOT_REFRESH_TIMES_ET:
            if now.hour == h and now.minute == m:
                if self._last_hot_refresh_key != (h, m):
                    self._last_hot_refresh_key = (h, m)
                    return True, f"hot_slot_refresh@{h:02d}:{m:02d}_ET"
        # Dynamic overlay during RTH: every 15 min (clock-aligned).
        in_rth = (
            (9 * 60 + 25) <= (now.hour * 60 + now.minute) < (16 * 60)
        )
        if in_rth and now.minute % self.DYNAMIC_OVERLAY_REFRESH_INTERVAL_MIN == 0:
            if self._last_dynamic_refresh_minute != now.hour * 60 + now.minute:
                self._last_dynamic_refresh_minute = now.hour * 60 + now.minute
                return True, f"dynamic_overlay_15min@{now.hour:02d}:{now.minute:02d}_ET"
        # Safety pin refresh — every cycle re-checks open positions and
        # adds them if missing. Cheap; does not require a swap.
        return False, "no_refresh_due"

    async def _loop_body(self) -> None:
        while self._running:
            try:
                due, reason = self._is_refresh_due()
                # Always run a rotate_once on the first loop iteration
                # so the operator gets coverage immediately on startup.
                if due or self._last_rotation is None:
                    logger.info("[PusherRotation] running cycle: %s", reason)
                    # Run the sync rotate in a thread to keep the loop responsive.
                    await asyncio.to_thread(self.rotate_once)
                # Always check open positions for newly-opened trades
                # that need pinning (covered by next due cycle, but a
                # second-pass pin keeps stale-quote risk minimal).
                else:
                    safety_pinned = _read_open_position_symbols(self.bot)
                    # v19.30.7 (2026-05-02): wrap in asyncio.to_thread.
                    # Same wedge class as the hybrid_data_service fix
                    # in this version — get_subscribed_set transitively
                    # holds the pusher RPC `threading.Lock` and blocks
                    # the loop. This loop body fires every
                    # LOOP_TICK_SECONDS so a single slow RPC could
                    # stall the loop on EVERY tick.
                    current = await asyncio.to_thread(
                        self.pusher.get_subscribed_set
                    ) or set()
                    missing = safety_pinned - current
                    if missing:
                        logger.info(
                            "[PusherRotation] pinning %d newly-opened "
                            "positions: %s", len(missing), sorted(missing),
                        )
                        await asyncio.to_thread(
                            self.pusher.subscribe_symbols, missing,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(
                    "[PusherRotation] loop iteration crashed (%s): %s",
                    type(e).__name__, e,
                )
            await asyncio.sleep(self.LOOP_TICK_SECONDS)

    # ---- diagnostic snapshot ----------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Snapshot for /api/diagnostic/pusher-rotation-status."""
        last = self._last_rotation or {}
        try:
            current = self.pusher.get_subscribed_set(force_refresh=False)
            current_count = len(current) if current else None
        except Exception:
            current_count = None
        return {
            "running": self._running,
            "current_pusher_subscriptions": current_count,
            "max_lines": MAX_LINES,
            "safety_buffer": SAFETY_BUFFER,
            "usable_lines": USABLE_LINES,
            "active_profile": select_profile(),
            "last_rotation": {
                k: v for k, v in last.items()
                if k in ("ts", "profile", "budget_used", "diff", "warnings",
                         "safety_pinned_count")
            } if last else None,
        }


# ---- module singleton -----------------------------------------------------
_rotation_service: Optional[PusherRotationService] = None


def get_rotation_service(
    *,
    db=None,
    bot=None,
    hot_slots_provider=None,
    dynamic_overlay_provider=None,
) -> PusherRotationService:
    global _rotation_service
    if _rotation_service is None:
        _rotation_service = PusherRotationService(
            db=db,
            bot=bot,
            hot_slots_provider=hot_slots_provider,
            dynamic_overlay_provider=dynamic_overlay_provider,
        )
    return _rotation_service


def reset_for_tests() -> None:
    """Tests-only — drop the module singleton between cases."""
    global _rotation_service
    _rotation_service = None
