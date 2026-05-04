"""
System Banner endpoint (v19.30.11, 2026-05-01)
==============================================

Single-source-of-truth alert tile that the V5 HUD polls to decide
whether to render a giant red strip across the top of the dashboard.

Why this exists:
  Operator spent 2026-05-01 afternoon thinking the Spark backend was
  broken because the dashboard had no live data. The real cause was
  the Windows pusher had died — but that was buried in a small
  "PUSHER RED" pill on the side of the V5 HUD that's easy to miss.
  The operator ran `./start_backend.sh` to "fix" the dashboard,
  which killed the perfectly-healthy backend AND ate a 60-90s
  cold-boot wait on top of the existing pusher outage.

  Lesson: when a critical subsystem is degraded, the dashboard
  needs to SCREAM, not whisper. This endpoint feeds the
  SystemBanner.jsx component which renders a giant red strip that
  is impossible to miss and tells the operator EXACTLY what's
  broken AND where to look.

Endpoint:
  GET /api/system/banner

Response:
  {
    "level": "critical" | "warning" | null,
    "message": str | None,                # human-readable headline
    "detail": str | None,                 # specific subsystem info
    "action": str | None,                 # what the operator should do
    "since_seconds": int | None,          # how long this has been red
    "subsystem": str | None,              # which /api/system/health subsystem fired
    "as_of": ISO timestamp,
  }

Levels:
  - "critical" — pusher_rpc red ≥30s (Windows pusher dead).
                 Renders as a giant red strip across the top.
  - "warning"  — overall health "yellow" (degraded but functional).
                 Renders as a thinner amber strip.
  - null       — everything is green. No banner.

Note: this DOES NOT compute its own health checks. It reads the
existing system_router output and translates it into UI-ready alert
copy. Single-source-of-truth principle: /api/system/health is the
diagnostic, /api/system/banner is the operator-facing presentation.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


# In-memory tracker for "how long has this subsystem been red?". Keyed
# by subsystem name. Reset to None when the subsystem flips back to green.
# Module-level state is fine here: single-process backend, low write rate.
_red_since_ts: Dict[str, Optional[float]] = {}


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _seconds_red(subsystem: str, currently_red: bool) -> Optional[int]:
    """Track and return how long `subsystem` has been red. Returns None
    if it's currently green (resets the tracker)."""
    if not currently_red:
        _red_since_ts[subsystem] = None
        return None
    if _red_since_ts.get(subsystem) is None:
        _red_since_ts[subsystem] = _now_ts()
    return int(_now_ts() - (_red_since_ts.get(subsystem) or _now_ts()))


@router.get("/banner")
async def get_system_banner() -> Dict[str, Any]:
    """Operator-facing banner derived from /api/system/health subsystems.

    Polled every 10s by the V5 HUD's SystemBanner component. Cheap —
    no I/O of its own; reads the existing health snapshot.
    """
    # Read the same snapshot that /api/system/health builds.
    try:
        from services.system_health_service import build_health
        from database import get_database
        _db = get_database()
        snapshot = await asyncio.to_thread(build_health, _db)
    except Exception as e:
        logger.debug(f"banner: snapshot build failed: {e}")
        snapshot = None

    if not snapshot:
        # If we can't read health, return nothing — better than a
        # confusing partial banner.
        return {
            "level": None,
            "message": None,
            "detail": None,
            "action": None,
            "since_seconds": None,
            "subsystem": None,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    subsystems = {s["name"]: s for s in snapshot.get("subsystems", [])}

    # ─── Critical-level checks (in priority order) ─────────────────────

    # 1. Windows pusher dead? Single most important signal — kills the
    # entire live-data pipeline. v19.30.12 distinguishes:
    #   - fully_dead  (push stale + RPC fail)        → CRITICAL
    #   - rpc_blocked (push fresh + RPC fail, e.g. firewall) → WARNING
    pusher = subsystems.get("pusher_rpc", {})
    pusher_status = pusher.get("status")
    pusher_metrics = pusher.get("metrics") or {}
    failures = pusher_metrics.get("consecutive_failures", 0)
    push_age_s = pusher_metrics.get("push_age_s")
    push_fresh = bool(pusher_metrics.get("push_fresh"))

    if pusher_status == "red":
        # Pusher subsystem returned red. Two sub-cases by push freshness.
        if push_fresh:
            # Live data IS flowing via push-data, but RPC channel is
            # broken. This shouldn't normally land in `red` (the new
            # _check_pusher_rpc emits yellow for this case), but defend
            # against a stale snapshot or future regression.
            sub_key = "pusher_rpc_blocked"
            level = "warning"
        else:
            sub_key = "pusher_rpc_dead"
            level = "critical"
    elif pusher_status == "yellow" and not push_fresh:
        # Stale push + RPC borderline — keep it as warning until either
        # channel firmly fails.
        sub_key = "pusher_rpc_partial"
        level = "warning"
    elif (
        pusher_status == "yellow"
        and push_fresh
        and int(failures or 0) >= 5
    ):
        # The clean "rpc_blocked" path: push fresh, RPC consistently failing.
        sub_key = "pusher_rpc_blocked"
        level = "warning"
    else:
        # Pusher fine — clear all trackers.
        _red_since_ts["pusher_rpc_dead"] = None
        _red_since_ts["pusher_rpc_blocked"] = None
        _red_since_ts["pusher_rpc_partial"] = None
        sub_key = None
        level = None

    if sub_key is not None and level is not None:
        # Reset the OTHER trackers so we don't carry stale "since" counts.
        for k in ("pusher_rpc_dead", "pusher_rpc_blocked", "pusher_rpc_partial"):
            if k != sub_key:
                _red_since_ts[k] = None

        red_for = _seconds_red(sub_key, True)
        threshold = 30  # seconds before banner fires (avoid flash on transients)
        if (red_for or 0) >= threshold:
            if sub_key == "pusher_rpc_dead":
                return {
                    "level": "critical",
                    "message": "Windows IB Pusher is DOWN",
                    "detail": (
                        f"{failures} consecutive RPC failures, "
                        f"no push received in "
                        f"{push_age_s if push_age_s is not None else '?'}s. "
                        "Live IB data is NOT flowing — backend is "
                        "otherwise healthy."
                    ),
                    "action": (
                        "Check Windows side: is the [IB PUSHER] CMD window "
                        "still showing a healthy log? If the process "
                        "crashed, restart it via the .bat orchestrator. "
                        "Do NOT restart the Spark backend — it's healthy."
                    ),
                    "since_seconds": red_for,
                    "subsystem": "pusher_rpc",
                    "as_of": snapshot.get("as_of"),
                }
            if sub_key == "pusher_rpc_blocked":
                push_age_str = (
                    f"{push_age_s:.1f}s ago"
                    if push_age_s is not None
                    else "recently"
                )
                return {
                    "level": "warning",
                    "message": "Spark→pusher RPC blocked — live data still flowing",
                    "detail": (
                        f"{failures} consecutive RPC failures, but push "
                        f"channel is HEALTHY (last push {push_age_str}). "
                        "Live quotes/positions/account are fine. "
                        "On-demand chart-bar RPC fetches degrade to Mongo cache."
                    ),
                    "action": (
                        "Most likely Windows firewall blocking inbound :8765. "
                        "On Windows (Run as Admin): "
                        'netsh advfirewall firewall add rule '
                        'name="IB Pusher RPC 8765" dir=in action=allow '
                        'protocol=TCP localport=8765 — '
                        "then verify from Spark: "
                        "curl -m 3 http://192.168.50.1:8765/rpc/health"
                    ),
                    "since_seconds": red_for,
                    "subsystem": "pusher_rpc",
                    "as_of": snapshot.get("as_of"),
                }
            if sub_key == "pusher_rpc_partial":
                return {
                    "level": "warning",
                    "message": "Pusher in partial state",
                    "detail": pusher.get("detail") or "Pusher status uncertain.",
                    "action": (
                        "Check both: (1) [IB PUSHER] window on Windows is "
                        "still pushing OK every 10s, AND (2) Spark can reach "
                        "http://192.168.50.1:8765/rpc/health."
                    ),
                    "since_seconds": red_for,
                    "subsystem": "pusher_rpc",
                    "as_of": snapshot.get("as_of"),
                }

    # 2. MongoDB dead? Game over for everything.
    mongo = subsystems.get("mongo", {})
    mongo_red = mongo.get("status") == "red"
    mongo_red_for = _seconds_red("mongo", mongo_red)
    if mongo_red and (mongo_red_for or 0) >= 10:
        return {
            "level": "critical",
            "message": "MongoDB is unreachable",
            "detail": mongo.get("detail") or "MongoDB ping failed.",
            "action": (
                "On Spark, check `sudo docker ps | grep mongodb`. "
                "If down: `sudo docker start mongodb`."
            ),
            "since_seconds": mongo_red_for,
            "subsystem": "mongo",
            "as_of": snapshot.get("as_of"),
        }

    # ─── Warning-level checks ──────────────────────────────────────────

    # IB Gateway yellow (degraded mode) — backend is fine but trading
    # functionality is impacted. Only show as a warning, not critical
    # (this is the EXPECTED state for a DGX backend that talks to IB
    # only via the pusher, so we don't want to alarm on it).
    ib = subsystems.get("ib_gateway", {})
    # 2026-05-04 — `pusher_red` was removed from this scope during the
    # v19.30.12 refactor that introduced the 4-quadrant push×RPC matrix
    # but the IB-yellow branch was left referencing it, causing every
    # /banner call to 500 with NameError. Re-derive from the same fields
    # the early section already computed.
    pusher_red_now = pusher_status == "red"
    if ib.get("status") == "yellow" and pusher_red_now:
        # Pusher is also red — pusher_rpc handler above has already
        # fired, no need to fire again here.
        pass
    elif snapshot.get("overall") == "yellow":
        # Some other yellow — surface as a thin warning strip. Skip
        # `pusher_rpc` (its own dedicated banners above already covered
        # rpc_blocked / partial; if those didn't fire we don't want to
        # double up with a generic "degraded" message).
        degraded = [
            s for s in snapshot.get("subsystems", [])
            if s.get("status") in ("yellow", "red")
            and s.get("name") != "pusher_rpc"
        ]
        if not degraded:
            # Only pusher_rpc was yellow and we already handled it.
            return {
                "level": None,
                "message": None,
                "detail": None,
                "action": None,
                "since_seconds": None,
                "subsystem": None,
                "as_of": snapshot.get("as_of"),
            }
        return {
            "level": "warning",
            "message": "Some subsystems are degraded",
            "detail": ", ".join(
                f"{s['name']}: {s.get('detail') or s['status']}"
                for s in degraded
            ) or None,
            "action": "Check /api/system/health for the full breakdown.",
            "since_seconds": None,
            "subsystem": None,
            "as_of": snapshot.get("as_of"),
        }

    # All clear.
    return {
        "level": None,
        "message": None,
        "detail": None,
        "action": None,
        "since_seconds": None,
        "subsystem": None,
        "as_of": snapshot.get("as_of"),
    }
