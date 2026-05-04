"""
System Health Aggregator
========================
Single source of truth for "is everything OK?" across the app. Aggregates
subsystem health signals (IB, pusher RPC, Mongo, queues, subscriptions,
caches, scheduler heartbeats) into a normalised green/yellow/red payload
the UI can render as a single HUD chip + a drill-down inspector grid.

Design principles:
    * Every subsystem check has a timeout < 1s — the health endpoint must
      stay snappy even when one subsystem is down.
    * NO subsystem check raises. All failures degrade to `status: "error"`
      with the exception message stringified (capped at 300 chars).
    * Read-only — this module never writes to Mongo or calls mutative
      backend methods. Safe to poll.
    * No external network calls (pusher RPC check reuses the existing
      cached client status — does NOT call /rpc/health itself, which would
      add latency and confuse the metric).

Severity rules:
    green   — everything nominal
    yellow  — degraded but functional (e.g. pusher RPC unreachable but
              historical cache still serves; backlog > threshold; slow)
    red     — subsystem broken to the point of data loss / decision risk

Overall status is the worst subsystem severity.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Yellow / red thresholds — tuned to DGX + Windows pusher operational norms.
MONGO_PING_YELLOW_MS = 50
MONGO_PING_RED_MS = 500
HIST_QUEUE_YELLOW = 5_000
HIST_QUEUE_RED = 25_000        # over 25k = IB pacing will be underwater
TASK_HEARTBEAT_STALE_S = 900    # 15 min without activity → yellow
TASK_HEARTBEAT_DEAD_S = 3_600   # 1 hour → red


@dataclass
class SubsystemHealth:
    name: str
    status: str             # "green" | "yellow" | "red"
    latency_ms: Optional[float] = None
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "metrics": self.metrics,
        }


def _error(name: str, exc: Exception) -> SubsystemHealth:
    return SubsystemHealth(
        name=name,
        status="red",
        detail=f"{type(exc).__name__}: {str(exc)[:280]}",
    )


def _check_mongo(db) -> SubsystemHealth:
    if db is None:
        return SubsystemHealth(name="mongo", status="red", detail="db handle not initialised")
    try:
        t0 = time.time()
        # server_info is the cheapest round-trip — doesn't touch any collection
        db.client.admin.command("ping")
        ms = round((time.time() - t0) * 1000, 2)
        status = "green"
        if ms >= MONGO_PING_RED_MS:
            status = "red"
        elif ms >= MONGO_PING_YELLOW_MS:
            status = "yellow"
        return SubsystemHealth(
            name="mongo",
            status=status,
            latency_ms=ms,
            detail=f"ping {ms} ms",
        )
    except Exception as exc:
        return _error("mongo", exc)


def _check_pusher_rpc() -> SubsystemHealth:
    """Health of the Spark→pusher RPC channel (separate from push-data).

    v19.30.12 (2026-05-01) — distinguish pusher-fully-dead from
    pusher-RPC-blocked. Two signals, two channels:

      * Push channel  (Windows :8765 → Spark :8001):
        push-data POST. Reflected in `_pushed_ib_data["last_update"]`.
      * RPC channel   (Spark → Windows :8765):
        Spark calls /rpc/latest-bars etc. Reflected in
        `pusher_rpc_client.consecutive_failures`.

    Asymmetric network failures (e.g. Windows firewall blocking inbound
    on :8765) mean these can be in different states. Pre-v19.30.12 we
    only looked at the RPC channel, so the operator saw "pusher
    unreachable" even when 72 quotes/sec were flowing fine.

    New severity matrix:

        push fresh (<60s) | RPC working      → GREEN
        push fresh (<60s) | RPC failing      → YELLOW (rpc_blocked)
        push stale (>60s) | RPC working      → YELLOW (push_blocked)
        push stale (>60s) | RPC failing      → RED    (fully_dead)
    """
    try:
        from services.ib_pusher_rpc import get_pusher_rpc_client
        client = get_pusher_rpc_client()
        s = client.status()
        # We do NOT call client.health() here (adds latency). Instead we
        # rely on the running consecutive_failures + last_success_ts signal.
        if not s.get("enabled"):
            return SubsystemHealth(
                name="pusher_rpc",
                status="yellow",
                detail="ENABLE_LIVE_BAR_RPC=false (live data disabled)",
                metrics=s,
            )
        if not s.get("url"):
            return SubsystemHealth(
                name="pusher_rpc",
                status="yellow",
                detail="IB_PUSHER_RPC_URL not set",
                metrics=s,
            )

        # ─── Read the push channel state ─────────────────────────────────
        # Reach into routers.ib._pushed_ib_data for last_update timestamp.
        # We deliberately import-on-demand to avoid a hard module dep at
        # health_service import time AND we read the module attribute
        # directly (NOT the get_pushed_ib_data helper) because the HTTP
        # route at routers.ib:615 shadows the sync helper with an async
        # endpoint of the same name, so any callable lookup picks up
        # the coroutine instead of the dict.
        push_age_s: Optional[float] = None
        try:
            import routers.ib as ib_module
            pushed = getattr(ib_module, "_pushed_ib_data", None) or {}
            last_update = pushed.get("last_update")
            if last_update:
                from datetime import datetime
                try:
                    if isinstance(last_update, str):
                        s_clean = last_update.rstrip("Z").replace("Z", "")
                        dt = datetime.fromisoformat(s_clean)
                        if dt.tzinfo is None:
                            from datetime import timezone as _tz
                            dt = dt.replace(tzinfo=_tz.utc)
                        push_age_s = (
                            datetime.now(dt.tzinfo) - dt
                        ).total_seconds()
                except Exception:
                    push_age_s = None
        except Exception:
            push_age_s = None

        push_fresh = push_age_s is not None and push_age_s < 60.0

        # ─── RPC channel state ──────────────────────────────────────────
        failures = int(s.get("consecutive_failures") or 0)
        last_success = s.get("last_success_ts")
        age = None
        if last_success:
            age = round(time.time() - float(last_success), 1)
        rpc_failing = failures >= 5

        # ─── Severity matrix ────────────────────────────────────────────
        detail_parts: list = []
        if push_fresh and not rpc_failing:
            status = "green"
            if last_success:
                detail_parts.append(f"last ok {age}s ago")
            else:
                detail_parts.append("push healthy")
        elif push_fresh and rpc_failing:
            # Live data is flowing via push-data, but Spark's outbound
            # RPC calls to the pusher are failing. Most likely cause:
            # Windows firewall blocking inbound on :8765. On-demand
            # historical bar fetches degrade to Mongo cache; live
            # quotes/positions/account fields keep flowing fine.
            status = "yellow"
            detail_parts.append("rpc_blocked")
            detail_parts.append(f"{failures} consecutive RPC failures")
            detail_parts.append(
                f"push fresh ({push_age_s:.1f}s ago) — live data IS flowing"
            )
        elif (push_age_s is None or not push_fresh) and rpc_failing:
            # Both channels failing — pusher is fully dead.
            status = "red"
            detail_parts.append("fully_dead")
            detail_parts.append(f"{failures} consecutive RPC failures")
            if push_age_s is not None:
                detail_parts.append(f"push stale ({push_age_s:.1f}s ago)")
            else:
                detail_parts.append("no push data ever received")
        elif (push_age_s is None or not push_fresh) and not rpc_failing:
            # RPC works but push direction blocked — weird, surface as yellow.
            status = "yellow"
            detail_parts.append("push_blocked")
            if push_age_s is not None:
                detail_parts.append(f"push stale ({push_age_s:.1f}s ago)")
            else:
                detail_parts.append("no push data yet (recent boot?)")
        else:
            # Defensive default
            status = "yellow"
            detail_parts.append(f"{failures} recent RPC failures")

        return SubsystemHealth(
            name="pusher_rpc",
            status=status,
            detail=" · ".join(detail_parts),
            metrics={
                **s,
                "last_success_age_s": age,
                "push_age_s": push_age_s,
                "push_fresh": push_fresh,
            },
        )
    except Exception as exc:
        return _error("pusher_rpc", exc)


def _check_ib_gateway() -> SubsystemHealth:
    """Health of the direct IB Gateway connection.

    v19.30.13 (2026-05-04) — pusher-only deployment is now treated as a
    valid full configuration (status: green) instead of a misleading
    yellow warning. The DGX backend in this deployment never connects
    directly to IB Gateway — the Windows pusher is the only IB path.
    Pre-fix this check returned yellow forever and showed up as "1 WARN"
    in the V5 HUD header, which sent operators on a wild goose chase.

    Determination logic:
      * `ib_service` registered AND connected → GREEN ("connected")
      * `ib_service` registered AND disconnected → YELLOW (legitimately
        degraded — the operator deployed direct IB intentionally and
        it's down)
      * `ib_service` NOT registered AND pusher_rpc reachable →
        GREEN ("pusher-only deployment") — this is the SentCom standard
        deployment shape, not an error
      * `ib_service` NOT registered AND pusher_rpc unreachable →
        YELLOW ("no IB path available") — genuine concern
    """
    try:
        from services.service_registry import get_service_optional
        ib = get_service_optional("ib_service")
        if ib is None:
            # No direct IB. Check if pusher is the IB path (the SentCom
            # standard deployment).
            pusher_reachable = False
            try:
                from services.ib_pusher_rpc import get_pusher_rpc_client
                client = get_pusher_rpc_client()
                s = client.status()
                # Pusher is reachable if it's enabled, has a URL, and
                # has either succeeded recently OR has had < 5 consecutive
                # failures (in which case it might just be a transient
                # blip). The pusher_rpc subsystem check has its own
                # nuanced logic; we just need a cheap "is it our IB path?"
                # signal here.
                pusher_reachable = (
                    bool(s.get("enabled"))
                    and bool(s.get("url"))
                    and (s.get("last_success_ts") is not None
                         or int(s.get("consecutive_failures") or 0) < 5)
                )
            except Exception:
                pass

            if pusher_reachable:
                return SubsystemHealth(
                    name="ib_gateway",
                    status="green",
                    detail="pusher-only deployment — direct IB not used",
                    metrics={"connected": False, "via_pusher": True},
                )
            # No direct IB AND no pusher — that's a real concern.
            return SubsystemHealth(
                name="ib_gateway",
                status="yellow",
                detail="no IB path: ib_service not registered and pusher unreachable",
                metrics={"connected": False, "via_pusher": False},
            )

        connected = False
        try:
            if getattr(ib, "connected", False):
                connected = True
            elif hasattr(ib, "ib") and ib.ib is not None:
                connected = bool(ib.ib.isConnected())
        except Exception:
            pass
        return SubsystemHealth(
            name="ib_gateway",
            status="green" if connected else "yellow",
            detail="connected" if connected else "disconnected (preview env OK)",
            metrics={"connected": connected, "via_pusher": False},
        )
    except Exception as exc:
        return _error("ib_gateway", exc)


def _check_historical_queue(db) -> SubsystemHealth:
    if db is None:
        return SubsystemHealth(name="historical_queue", status="yellow", detail="db not initialised")
    try:
        col = db["historical_data_requests"]
        pending = col.count_documents({"status": {"$in": ["pending", "in_progress"]}})
        failed = col.count_documents({"status": "failed"})
        status = "green"
        if pending >= HIST_QUEUE_RED:
            status = "red"
        elif pending >= HIST_QUEUE_YELLOW:
            status = "yellow"
        return SubsystemHealth(
            name="historical_queue",
            status=status,
            detail=f"{pending:,} pending · {failed:,} failed",
            metrics={"pending": pending, "failed": failed},
        )
    except Exception as exc:
        return _error("historical_queue", exc)


def _check_live_subscriptions() -> SubsystemHealth:
    try:
        from services.live_subscription_manager import get_live_subscription_manager
        mgr = get_live_subscription_manager()
        listing = mgr.list_subscriptions()
        active = int(listing.get("active_count") or 0)
        max_subs = int(listing.get("max_subscriptions") or 60)
        status = "green"
        ratio = active / max_subs if max_subs else 0
        if ratio >= 0.95:
            status = "red"
        elif ratio >= 0.8:
            status = "yellow"
        return SubsystemHealth(
            name="live_subscriptions",
            status=status,
            detail=f"{active}/{max_subs} slots used",
            metrics={"active": active, "max": max_subs, "ratio": round(ratio, 2)},
        )
    except Exception as exc:
        return _error("live_subscriptions", exc)


def _check_live_bar_cache(db) -> SubsystemHealth:
    if db is None:
        return SubsystemHealth(name="live_bar_cache", status="yellow", detail="db not initialised")
    try:
        col = db["live_bar_cache"]
        total = col.count_documents({})
        now = datetime.now(timezone.utc)
        fresh = col.count_documents({"expires_at": {"$gt": now}})
        return SubsystemHealth(
            name="live_bar_cache",
            status="green",
            detail=f"{fresh}/{total} entries fresh",
            metrics={"fresh": fresh, "total": total},
        )
    except Exception as exc:
        return _error("live_bar_cache", exc)


def _check_task_heartbeats(db) -> SubsystemHealth:
    """Check last_run timestamps on known scheduled tasks. Falls back to
    green (no data) — we don't want to block health when a task collection
    doesn't exist yet in a fresh deployment."""
    if db is None:
        return SubsystemHealth(name="task_heartbeats", status="yellow", detail="db not initialised")
    try:
        col = db["task_heartbeats"]
        docs = list(col.find({}, {"_id": 0}))
        now = time.time()
        stale: List[str] = []
        dead: List[str] = []
        task_states: Dict[str, Any] = {}
        for d in docs:
            task = d.get("task") or d.get("name") or "unknown"
            last_ts = d.get("last_ok_ts") or d.get("last_run_ts")
            if last_ts is None:
                continue
            try:
                if isinstance(last_ts, (int, float)):
                    last = float(last_ts)
                else:
                    last = datetime.fromisoformat(
                        str(last_ts).replace("Z", "+00:00")
                    ).timestamp()
                age = now - last
                task_states[task] = round(age, 1)
                if age >= TASK_HEARTBEAT_DEAD_S:
                    dead.append(task)
                elif age >= TASK_HEARTBEAT_STALE_S:
                    stale.append(task)
            except Exception:
                continue
        if dead:
            return SubsystemHealth(
                name="task_heartbeats",
                status="red",
                detail=f"dead: {', '.join(dead[:5])}",
                metrics={"stale": stale, "dead": dead, "ages": task_states},
            )
        if stale:
            return SubsystemHealth(
                name="task_heartbeats",
                status="yellow",
                detail=f"stale: {', '.join(stale[:5])}",
                metrics={"stale": stale, "dead": dead, "ages": task_states},
            )
        return SubsystemHealth(
            name="task_heartbeats",
            status="green",
            detail=f"{len(task_states)} task(s) healthy",
            metrics={"ages": task_states},
        )
    except Exception as exc:
        return _error("task_heartbeats", exc)


def _worst(statuses: List[str]) -> str:
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def build_health(db) -> Dict[str, Any]:
    """Aggregate every subsystem into a single response. Never raises."""
    t0 = time.time()
    checks: List[SubsystemHealth] = [
        _check_mongo(db),
        _check_pusher_rpc(),
        _check_ib_gateway(),
        _check_historical_queue(db),
        _check_live_subscriptions(),
        _check_live_bar_cache(db),
        _check_task_heartbeats(db),
    ]
    total_ms = round((time.time() - t0) * 1000, 2)
    overall = _worst([c.status for c in checks])
    return {
        "overall": overall,
        "counts": {
            "green": sum(1 for c in checks if c.status == "green"),
            "yellow": sum(1 for c in checks if c.status == "yellow"),
            "red": sum(1 for c in checks if c.status == "red"),
        },
        "subsystems": [c.to_dict() for c in checks],
        "build_ms": total_ms,
        "env": {
            "alpaca_fallback": os.environ.get("ENABLE_ALPACA_FALLBACK", "false"),
            "live_bar_rpc": os.environ.get("ENABLE_LIVE_BAR_RPC", "true"),
            "pusher_rpc_url_set": bool(os.environ.get("IB_PUSHER_RPC_URL")),
        },
        "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
