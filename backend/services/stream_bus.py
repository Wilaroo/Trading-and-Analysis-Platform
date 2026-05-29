"""
v19.34.184 — Mission Control live stream bus.

A lightweight, loop-local broadcaster that fan-outs `emit_stream_event`
output to connected Mission-Control WebSocket clients, classified into the
5 pipeline lanes (scanner / gates / execution / position / reconciler) plus
a system/safety strip.

Design constraints (see CHANGELOG v19.34.184):
  • The trading hot path must not slow down. `publish()` is a *synchronous*,
    allocation-cheap append — it does NOT await, serialize, or send. A
    background flush loop (≈300ms) does the per-connection send.
  • Zero idle overhead: when no client is connected, `publish()` early-returns
    after (cheaply) updating the scanner roll-up counters.
  • The scanner lane is a firehose (~46k skips/day). In `aggregate` mode we do
    NOT buffer individual skip/reject events at all — we only count them and
    emit a periodic `scan_pulse` summary. Individual `scanner_trigger` events
    always pass. `raw` mode streams everything (only buffered when at least one
    raw subscriber exists).

This module is import-safe and has no hard dependency on FastAPI; the WS
endpoint in server.py drives connect/disconnect/receive.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

ALL_LANES = ("scanner", "gates", "execution", "position", "reconciler", "system")
ALL_SEVERITIES = ("info", "success", "warn", "alarm")

_FLUSH_INTERVAL_S = 0.3      # batch window
_PULSE_EVERY_FLUSHES = 10    # → scan_pulse roughly every 3s
_MAX_BUFFER = 2000           # hard cap so a burst can't balloon memory


def classify_lane(action_type: Optional[str], kind: Optional[str], source: Optional[str]) -> str:
    """Map an event to one of ALL_LANES. action_type is the primary signal
    (well-populated + distinctive per the v19.34.184 coverage audit); source
    and kind are tie-breakers."""
    a = (action_type or "").lower()
    k = (kind or "").lower()
    s = (source or "").lower()

    if a.startswith("scanner_") or s == "enhanced_scanner":
        return "scanner"
    # reconciler / state-integrity (checked before position so the OCA-close
    # sweep lands here, not in position via the generic "swept" rule).
    if (any(t in a for t in ("reconcile", "drift", "zombie", "orphan"))
            or "phantom_v19_31_oca" in a
            or s in ("position_reconciler", "state_integrity_service")):
        return "reconciler"
    if (a.startswith("rejection_") or a.startswith("eod_no_new_entries")
            or a in ("evaluating_setup", "trade_decision",
                     "wrong_side_stop_recomputed", "position_stop_capped")
            or s == "opportunity_evaluator"
            or k in ("evaluation", "filter", "rejection", "skip")):
        return "gates"
    if a in ("trade_filled", "trade_executed", "bracket_attach_blocked",
             "order_submitted", "partial_fill", "bracket_attached") or k == "fill":
        return "execution"
    if (a in ("eod_flatten_failed", "position_memory_disagreement",
              "wrong_direction_phantom_swept", "stop_proximity",
              "stop_to_breakeven", "trailing_stop_moved", "target_hit",
              "scale_out", "time_stop_approaching", "eod_flatten_initiated",
              "external_partial_close_v19_34_15b", "operator_external_flatten_v19_34_72",
              "realized_pnl_autosync_v19_31_13", "first_tick_bracket_reaper_v19_34_153")
            or "swept" in a
            or s in ("position_manager", "position_consolidator", "bracket_reissue_service")):
        return "position"
    if (a in ("safety_block", "risk_update", "regime_update", "market_status",
              "breadth_update", "heartbeat", "account_guard", "pusher_freshness")
            or k == "system"):
        return "system"
    return "system"


def severity_of(kind: Optional[str], action_type: Optional[str]) -> str:
    k = (kind or "").lower()
    a = (action_type or "").lower()
    if k == "alarm" or "failed" in a or a == "safety_block" or "drift" in a:
        return "alarm"
    if k in ("warning", "rejection", "skip", "filter", "alert"):
        return "warn"
    if k == "fill" or "trigger" in a or "reconciled" in a or a in (
            "trade_filled", "trade_executed", "target_hit", "stop_to_breakeven"):
        return "success"
    return "info"


class _Conn:
    __slots__ = ("ws", "lanes", "severities", "mode")

    def __init__(self, ws: Any):
        self.ws = ws
        self.lanes: Set[str] = set(ALL_LANES)
        self.severities: Set[str] = set(ALL_SEVERITIES)
        self.mode: str = "aggregate"  # or "raw"


class StreamBus:
    def __init__(self) -> None:
        self._conns: List[_Conn] = []
        self._buffer: List[Dict[str, Any]] = []
        self._scan_window: Counter = Counter()
        self._flush_task: Optional[asyncio.Task] = None
        self._flush_count = 0

    # ── connection lifecycle (called from the WS endpoint) ──────────────
    async def register(self, ws: Any) -> _Conn:
        conn = _Conn(ws)
        self._conns.append(conn)
        self._ensure_flush_loop()
        return conn

    def unregister(self, ws: Any) -> None:
        self._conns = [c for c in self._conns if c.ws is not ws]

    def update_sub(self, conn: _Conn, *, lanes=None, severities=None, mode=None) -> None:
        if lanes is not None:
            conn.lanes = {x for x in lanes if x in ALL_LANES} or set(ALL_LANES)
        if severities is not None:
            conn.severities = {x for x in severities if x in ALL_SEVERITIES} or set(ALL_SEVERITIES)
        if mode in ("aggregate", "raw"):
            conn.mode = mode

    @property
    def _has_raw_subscriber(self) -> bool:
        return any(c.mode == "raw" for c in self._conns)

    # ── publish (HOT PATH — sync, cheap, never awaits) ──────────────────
    def publish(self, payload: Dict[str, Any]) -> None:
        try:
            action = payload.get("action_type") or payload.get("event")
            kind = payload.get("kind") or payload.get("type")
            meta = payload.get("metadata") or {}
            source = meta.get("source") if isinstance(meta, dict) else None

            lane = classify_lane(action, kind, source)

            # Scanner firehose: always count; only buffer skips/rejects when a
            # raw subscriber is listening. Triggers always pass through.
            sub_kind = (meta.get("kind") if isinstance(meta, dict) else None) or kind or ""
            if lane == "scanner" and str(sub_kind).lower() in ("skip", "reject"):
                self._scan_window[str(sub_kind).lower()] += 1
                if not self._has_raw_subscriber:
                    return
            elif lane == "scanner":
                self._scan_window["trigger"] += 1

            if not self._conns:
                return
            if len(self._buffer) >= _MAX_BUFFER:
                return  # shed load on extreme bursts; pulse still summarizes

            self._buffer.append({
                "id": payload.get("id"),
                "lane": lane,
                "severity": severity_of(kind, action),
                "kind": kind,
                "scan_kind": str(sub_kind).lower() if lane == "scanner" else None,
                "action_type": action,
                "symbol": payload.get("symbol"),
                "text": payload.get("text") or payload.get("content") or "",
                "confidence": payload.get("confidence"),
                "metadata": meta if isinstance(meta, dict) else {},
                "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            # Never let observability break the trading path.
            pass

    # ── background flush loop ───────────────────────────────────────────
    def _ensure_flush_loop(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            try:
                self._flush_task = asyncio.create_task(self._flush_loop())
            except RuntimeError:
                self._flush_task = None

    async def _flush_loop(self) -> None:
        try:
            while self._conns:
                await asyncio.sleep(_FLUSH_INTERVAL_S)
                await self._flush_once()
                self._flush_count += 1
                if self._flush_count % _PULSE_EVERY_FLUSHES == 0:
                    await self._emit_scan_pulse()
        except asyncio.CancelledError:
            pass
        finally:
            self._flush_task = None

    async def _flush_once(self) -> None:
        if not self._buffer or not self._conns:
            self._buffer.clear()
            return
        batch = self._buffer
        self._buffer = []
        for conn in list(self._conns):
            events = [
                e for e in batch
                if e["lane"] in conn.lanes
                and e["severity"] in conn.severities
                and not (conn.mode == "aggregate"
                         and e["lane"] == "scanner"
                         and e.get("scan_kind") in ("skip", "reject"))
            ]
            if not events:
                continue
            await self._safe_send(conn, {"type": "events", "events": events})

    async def _emit_scan_pulse(self) -> None:
        if not self._conns:
            self._scan_window.clear()
            return
        w = self._scan_window
        if not w:
            return
        pulse = {
            "type": "scan_pulse",
            "lane": "scanner",
            "window_s": _FLUSH_INTERVAL_S * _PULSE_EVERY_FLUSHES,
            "triggers": w.get("trigger", 0),
            "skips": w.get("skip", 0),
            "rejects": w.get("reject", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._scan_window = Counter()
        for conn in list(self._conns):
            if "scanner" in conn.lanes:
                await self._safe_send(conn, pulse)

    async def _safe_send(self, conn: _Conn, message: Dict[str, Any]) -> None:
        try:
            await conn.ws.send_json(message)
        except Exception:
            self.unregister(conn.ws)


_stream_bus: Optional[StreamBus] = None


def get_stream_bus() -> StreamBus:
    global _stream_bus
    if _stream_bus is None:
        _stream_bus = StreamBus()
    return _stream_bus
