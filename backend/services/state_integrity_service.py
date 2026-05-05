"""
state_integrity_service.py — v19.34.10 (2026-05-06)

Background watchdog that catches drift between in-memory `risk_params`
and persisted `bot_state.risk_params` in MongoDB.

Why this exists
---------------
v19.34.9 root cause was a "silent persistence skew": `refresh-account`
updated `_trading_bot.risk_params.starting_capital` in-memory but never
flushed to Mongo, so `risk_caps_service` (which reads from Mongo) kept
serving the stale $100k mock value while the bot internally believed
$236k. The result: 135+ ghost rejection brackets when the daily-loss
guardrail tripped on the mock value.

The fix in v19.34.9 plugged that one path. v19.34.10 makes drift
detectable AND auto-correctable across every persistence path —
present and future. If a future patch introduces a similar
in-memory-only mutation, this watchdog will:

  1. Detect drift within the next check interval.
  2. Auto-resolve based on the per-field policy (Mongo wins for
     capital/limit fields; memory wins for runtime-tuned dicts).
  3. Emit a CRITICAL `state_drift_detected` Unified Stream event.
  4. Persist a forensic record in `state_integrity_events` (TTL 7d)
     for later RCA.

Field policy (operator approved 2026-05-06):
  • Mongo wins for: capital + limit fields (the v19.34.9 class of bug).
  • Memory wins for: setup_min_rr dict (operator hot-tunes via PUT).
  • Booleans / runtime flags: DETECT only, do NOT auto-resolve.

Feature flags
-------------
  STATE_INTEGRITY_CHECK_ENABLED=true          (default ON)
  STATE_INTEGRITY_CHECK_INTERVAL_S=60         (default 60s)
  STATE_INTEGRITY_AUTO_RESOLVE=true           (default ON; flip to
                                               false to detect-only)
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Field policy ─────────────────────────────────────────────────
# v19.34.14 (2026-05-06) — POLICY FLIP after operator caught the
# watchdog snapping live IB capital ($236k) DOWN to mock default
# ($100k) on a real Spark deployment. The original "Mongo wins for
# all capital fields" policy was wrong-by-design: in the v19.34.9
# RCA, memory had the CORRECT $236k (from /refresh-account → live
# IB) and Mongo had the STALE $100k. Mongo was the lagging side,
# not the leading side.
#
# Smart split (operator-approved 2026-05-06):
#   • IB-sourced capital → memory wins. These get sourced from the
#     live broker via /refresh-account or pusher. Mongo is just the
#     last persisted snapshot, which can lag arbitrarily long.
#   • Operator-tuned limits → Mongo wins. These get set via PUT
#     /risk-params and the persisted value IS the operator's intent;
#     a flickering in-memory value is the suspect side.
#   • setup_min_rr → memory wins (operator hot-tunes via PUT, may
#     not have flushed yet).
MONGO_WINS_FIELDS: Tuple[str, ...] = (
    "max_daily_loss_pct",
    "max_open_positions",
    "max_position_pct",
    "min_risk_reward",
    "reconciled_default_stop_pct",
    "reconciled_default_rr",
)

MEMORY_WINS_FIELDS: Tuple[str, ...] = (
    # IB-sourced (live broker is source of truth):
    "starting_capital",
    "max_daily_loss",            # computed from starting_capital × pct
    "max_notional_per_trade",
    "max_risk_per_trade",
    # Operator-tuned dict that may not have flushed yet:
    "setup_min_rr",
)

DETECT_ONLY_FIELDS: Tuple[str, ...] = (
    # Reserved for future use (e.g. kill-switch mirror flags).
)

# Float comparison tolerance — avoids spurious drift events from
# normal float round-trip noise through JSON / Mongo.
FLOAT_EPSILON: float = 0.01

# ─── v19.34.14 — drift-loop detector ───────────────────────────
# Prevents the watchdog itself from oscillating. If the same field
# flips between the same two values >= LOOP_DEMOTE_FLIPS times in
# LOOP_DEMOTE_WINDOW_S seconds, we DEMOTE that field to detect-only
# mode for the rest of the process lifetime — operator gets alerts
# but no auto-mutation. Cleared by `reset_loop_state()` (test hook).
LOOP_DEMOTE_FLIPS: int = 3
LOOP_DEMOTE_WINDOW_S: int = 600   # 10 min


# ─── Data classes ─────────────────────────────────────────────────

@dataclass
class FieldDrift:
    field: str
    memory_value: Any
    mongo_value: Any
    policy: str          # "mongo_wins" | "memory_wins" | "detect_only"
    resolved: bool       # True if auto-resolved this cycle
    resolution: str      # "mongo→memory" | "memory→mongo" | "detect_only"


@dataclass
class IntegrityCheckResult:
    """Snapshot of a single integrity-check cycle."""
    checked_at: str
    drifts: List[FieldDrift] = field(default_factory=list)
    healthy: bool = True
    error: Optional[str] = None
    auto_resolve_enabled: bool = True
    skipped: bool = False
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "healthy": self.healthy,
            "drift_count": len(self.drifts),
            "auto_resolve_enabled": self.auto_resolve_enabled,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "drifts": [
                {
                    "field": d.field,
                    "memory_value": d.memory_value,
                    "mongo_value": d.mongo_value,
                    "policy": d.policy,
                    "resolved": d.resolved,
                    "resolution": d.resolution,
                }
                for d in self.drifts
            ],
        }


# ─── Comparison helpers ───────────────────────────────────────────

def _values_differ(memory: Any, mongo: Any) -> bool:
    """True iff memory and mongo values differ meaningfully.

    Floats use FLOAT_EPSILON tolerance.
    Dicts are deep-compared (key-by-key, float-aware).
    None vs missing key are treated as equal.
    """
    if memory is None and mongo is None:
        return False
    if memory is None or mongo is None:
        return True
    # Float-aware
    if isinstance(memory, (int, float)) and isinstance(mongo, (int, float)):
        return abs(float(memory) - float(mongo)) > FLOAT_EPSILON
    # Dict-aware (handles setup_min_rr)
    if isinstance(memory, dict) and isinstance(mongo, dict):
        if set(memory.keys()) != set(mongo.keys()):
            return True
        for k in memory:
            if _values_differ(memory[k], mongo[k]):
                return True
        return False
    return memory != mongo


# ─── Core integrity check ─────────────────────────────────────────

class StateIntegrityService:
    """Background drift watcher.

    One instance per TradingBotService. Started via `start(bot)`,
    stopped via `stop()`. Survives transient Mongo / pusher errors
    (try/except around the loop body).
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._last_result: Optional[IntegrityCheckResult] = None
        self._cumulative_drift_count: int = 0
        self._cumulative_resolved_count: int = 0
        self._started_at: Optional[str] = None
        # v19.34.14 — drift-loop detector state.
        # Maps `field` → list of (timestamp, memory_value, mongo_value)
        # tuples. When >= LOOP_DEMOTE_FLIPS distinct value-pair flips
        # in LOOP_DEMOTE_WINDOW_S, we demote the field to detect-only.
        self._flip_history: Dict[str, List[Tuple[float, Any, Any]]] = {}
        self._demoted_fields: set = set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def interval_s(self) -> int:
        try:
            v = int(os.environ.get("STATE_INTEGRITY_CHECK_INTERVAL_S", "60") or 60)
        except (TypeError, ValueError):
            v = 60
        return max(5, v)  # safety floor

    @property
    def enabled(self) -> bool:
        return os.environ.get(
            "STATE_INTEGRITY_CHECK_ENABLED", "true",
        ).strip().lower() not in ("0", "false", "no", "off")

    @property
    def auto_resolve_enabled(self) -> bool:
        return os.environ.get(
            "STATE_INTEGRITY_AUTO_RESOLVE", "true",
        ).strip().lower() not in ("0", "false", "no", "off")

    def get_status(self) -> Dict[str, Any]:
        """Operator-facing snapshot for `/api/trading-bot/integrity-status`."""
        return {
            "running": self._running,
            "enabled": self.enabled,
            "auto_resolve_enabled": self.auto_resolve_enabled,
            "interval_s": self.interval_s,
            "started_at": self._started_at,
            "cumulative_drift_count": self._cumulative_drift_count,
            "cumulative_resolved_count": self._cumulative_resolved_count,
            "last_check": self._last_result.to_dict() if self._last_result else None,
            "field_policy": {
                "mongo_wins": list(MONGO_WINS_FIELDS),
                "memory_wins": list(MEMORY_WINS_FIELDS),
                "detect_only": list(DETECT_ONLY_FIELDS),
            },
            # v19.34.14 — drift-loop detector status.
            "demoted_fields": sorted(self._demoted_fields),
            "loop_detector": {
                "demote_after_flips": LOOP_DEMOTE_FLIPS,
                "window_seconds": LOOP_DEMOTE_WINDOW_S,
            },
        }

    # v19.34.14 — drift-loop detector helpers.

    def _record_flip_and_check_demote(
        self,
        field: str,
        memory_value: Any,
        mongo_value: Any,
    ) -> bool:
        """Record one flip; return True iff `field` is now demoted.

        A flip is one (memory_value, mongo_value) pair observed while
        the field was drifting. If the SAME field has flipped >=
        `LOOP_DEMOTE_FLIPS` times in the last `LOOP_DEMOTE_WINDOW_S`
        seconds — regardless of whether the value pairs are
        identical — that's an oscillating watchdog, demote it.
        """
        import time as _time
        now = _time.time()
        history = self._flip_history.setdefault(field, [])
        # Prune history outside the window.
        cutoff = now - LOOP_DEMOTE_WINDOW_S
        history[:] = [(t, m, mo) for (t, m, mo) in history if t >= cutoff]
        history.append((now, memory_value, mongo_value))
        if len(history) >= LOOP_DEMOTE_FLIPS and field not in self._demoted_fields:
            self._demoted_fields.add(field)
            logger.error(
                "[v19.34.14 INTEGRITY] field %r DEMOTED to detect-only after "
                "%d flips in %ds — watchdog was oscillating. Operator must "
                "force-resync manually to re-arm.",
                field, len(history), LOOP_DEMOTE_WINDOW_S,
            )
            return True
        return field in self._demoted_fields

    def _is_demoted(self, field: str) -> bool:
        return field in self._demoted_fields

    def reset_loop_state(self) -> None:
        """Test / operator hook — clear flip history + demote set."""
        self._flip_history.clear()
        self._demoted_fields.clear()

    # ── lifecycle ──────────────────────────────────────────────

    async def start(self, bot: Any) -> None:
        """Schedule the background loop on `bot`'s event loop."""
        if self._running:
            return
        if not self.enabled:
            logger.info("[v19.34.10 INTEGRITY] disabled by env")
            return
        self._running = True
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._loop(bot))
        logger.info(
            f"[v19.34.10 INTEGRITY] started (interval={self.interval_s}s, "
            f"auto_resolve={self.auto_resolve_enabled})"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self, bot: Any) -> None:
        # Initial grace period — let bot startup persist initial state.
        try:
            await asyncio.sleep(min(30, self.interval_s))
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self.run_check_once(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[v19.34.10 INTEGRITY] tick failed: {e}")
            try:
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                return

    # ── single-cycle public entrypoint (also used by force-resync) ──

    async def run_check_once(
        self,
        bot: Any,
        auto_resolve: Optional[bool] = None,
    ) -> IntegrityCheckResult:
        """Run a single drift check + (optional) auto-resolve.

        Returns the result + caches it as `last_result`.
        """
        result = IntegrityCheckResult(
            checked_at=datetime.now(timezone.utc).isoformat(),
            auto_resolve_enabled=(
                self.auto_resolve_enabled if auto_resolve is None else auto_resolve
            ),
        )
        try:
            db = getattr(bot, "_db", None)
            risk_params = getattr(bot, "risk_params", None)
            if db is None or risk_params is None:
                result.skipped = True
                result.skip_reason = "bot_not_ready"
                self._last_result = result
                return result

            # Read Mongo state — wrap sync pymongo in to_thread so we
            # don't block the event loop.
            mongo_state = await asyncio.to_thread(
                db["bot_state"].find_one, {"_id": "bot_state"},
            )
            if not mongo_state:
                # No persisted state yet (fresh install or pre-first-save).
                result.skipped = True
                result.skip_reason = "bot_state_doc_missing"
                self._last_result = result
                return result

            mongo_risk_params = (mongo_state or {}).get("risk_params", {}) or {}

            # Check each field per policy.
            drifts: List[FieldDrift] = []

            for fname in MONGO_WINS_FIELDS:
                mem_val = getattr(risk_params, fname, None)
                mongo_val = mongo_risk_params.get(fname)
                # If Mongo doesn't have this field yet (fresh install or
                # post-schema-add), skip — there's nothing authoritative
                # to snap memory to. Memory will be flushed on next
                # `_save_state()` cycle anyway.
                if mongo_val is None:
                    continue
                if _values_differ(mem_val, mongo_val):
                    # v19.34.14 — record the flip + check for loop demote.
                    demoted = self._record_flip_and_check_demote(
                        fname, mem_val, mongo_val,
                    )
                    drift = FieldDrift(
                        field=fname,
                        memory_value=mem_val,
                        mongo_value=mongo_val,
                        policy="mongo_wins",
                        resolved=False,
                        resolution="detect_only",
                    )
                    if result.auto_resolve_enabled and not demoted:
                        try:
                            setattr(risk_params, fname, mongo_val)
                            drift.resolved = True
                            drift.resolution = "mongo→memory"
                        except Exception as ex:
                            logger.warning(
                                f"[v19.34.10 INTEGRITY] failed to flush "
                                f"{fname} mongo→memory: {ex}"
                            )
                    elif demoted:
                        drift.resolution = "demoted_loop"
                    drifts.append(drift)

            for fname in MEMORY_WINS_FIELDS:
                mem_val = getattr(risk_params, fname, None)
                mongo_val = mongo_risk_params.get(fname)
                if _values_differ(mem_val, mongo_val):
                    # v19.34.14 — record the flip + check for loop demote.
                    demoted = self._record_flip_and_check_demote(
                        fname, mem_val, mongo_val,
                    )
                    drift = FieldDrift(
                        field=fname,
                        memory_value=mem_val,
                        mongo_value=mongo_val,
                        policy="memory_wins",
                        resolved=False,
                        resolution="detect_only",
                    )
                    # Memory-wins: re-flush by saving state.
                    if result.auto_resolve_enabled and not demoted:
                        try:
                            save_state = getattr(bot, "_save_state", None)
                            if save_state is not None:
                                await save_state()
                                drift.resolved = True
                                drift.resolution = "memory→mongo"
                        except Exception as ex:
                            logger.warning(
                                f"[v19.34.10 INTEGRITY] failed to flush "
                                f"{fname} memory→mongo: {ex}"
                            )
                    elif demoted:
                        drift.resolution = "demoted_loop"
                    drifts.append(drift)

            for fname in DETECT_ONLY_FIELDS:
                mem_val = getattr(risk_params, fname, None)
                mongo_val = mongo_risk_params.get(fname)
                if _values_differ(mem_val, mongo_val):
                    drifts.append(FieldDrift(
                        field=fname,
                        memory_value=mem_val,
                        mongo_value=mongo_val,
                        policy="detect_only",
                        resolved=False,
                        resolution="detect_only",
                    ))

            result.drifts = drifts
            result.healthy = (len(drifts) == 0)

            # Forensic + alarm: persist drift events + emit stream event.
            if drifts:
                self._cumulative_drift_count += len(drifts)
                self._cumulative_resolved_count += sum(
                    1 for d in drifts if d.resolved
                )
                await self._persist_drift_event(db, result)
                await self._emit_critical_stream(result)
                logger.warning(
                    f"[v19.34.10 INTEGRITY] {len(drifts)} drift(s) detected: "
                    + ", ".join(
                        f"{d.field}: mem={d.memory_value} mongo={d.mongo_value} "
                        f"({d.resolution})"
                        for d in drifts
                    )
                )

            self._last_result = result
            return result

        except Exception as e:
            result.error = str(e)
            result.healthy = False
            self._last_result = result
            logger.warning(f"[v19.34.10 INTEGRITY] check failed: {e}")
            return result

    async def _persist_drift_event(
        self,
        db: Any,
        result: IntegrityCheckResult,
    ) -> None:
        """Write to `state_integrity_events` (TTL 7d) for later RCA."""
        try:
            doc = {
                "checked_at": result.checked_at,
                "drifts": [
                    {
                        "field": d.field,
                        "memory_value": d.memory_value,
                        "mongo_value": d.mongo_value,
                        "policy": d.policy,
                        "resolved": d.resolved,
                        "resolution": d.resolution,
                    }
                    for d in result.drifts
                ],
                "drift_count": len(result.drifts),
                "auto_resolve_enabled": result.auto_resolve_enabled,
                "created_at": datetime.now(timezone.utc),
            }
            await asyncio.to_thread(
                db["state_integrity_events"].insert_one, doc,
            )
        except Exception as e:
            logger.debug(f"[v19.34.10 INTEGRITY] persist event failed: {e}")

    async def _emit_critical_stream(
        self,
        result: IntegrityCheckResult,
    ) -> None:
        """Push a CRITICAL Unified Stream event so operator sees drift."""
        try:
            from services.sentcom_service import emit_stream_event
            unresolved = [d for d in result.drifts if not d.resolved]
            kind = "critical" if unresolved else "warning"
            top_fields = ", ".join(d.field for d in result.drifts[:5])
            text = (
                f"⚠ State drift detected on {len(result.drifts)} field(s): "
                f"{top_fields}"
                + (
                    f" (auto-resolved {len(result.drifts) - len(unresolved)}"
                    f"/{len(result.drifts)})"
                    if result.auto_resolve_enabled else " (detect-only mode)"
                )
            )
            await emit_stream_event({
                "kind": kind,
                "event": "state_drift_detected_v19_34_10",
                "text": text,
                "metadata": {
                    "drift_count": len(result.drifts),
                    "unresolved_count": len(unresolved),
                    "auto_resolve_enabled": result.auto_resolve_enabled,
                    "fields": [d.field for d in result.drifts],
                },
            })
        except Exception as e:
            logger.debug(f"[v19.34.10 INTEGRITY] stream emit failed: {e}")


# ─── Singleton accessor ───────────────────────────────────────────

_integrity_service: Optional[StateIntegrityService] = None


def get_state_integrity_service() -> StateIntegrityService:
    """Process-wide singleton."""
    global _integrity_service
    if _integrity_service is None:
        _integrity_service = StateIntegrityService()
    return _integrity_service
