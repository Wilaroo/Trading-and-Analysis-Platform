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
    # entire live-data pipeline.
    pusher = subsystems.get("pusher_rpc", {})
    pusher_red = pusher.get("status") == "red"
    pusher_red_for = _seconds_red("pusher_rpc", pusher_red)
    # Only fire after 30s to avoid flashing during transient blips.
    if pusher_red and (pusher_red_for or 0) >= 30:
        failures = pusher.get("metrics", {}).get("consecutive_failures", "?")
        return {
            "level": "critical",
            "message": "Windows IB Pusher is unreachable",
            "detail": (
                f"{failures} consecutive failures over {pusher_red_for}s. "
                "Live IB data is NOT flowing — backend is otherwise healthy."
            ),
            "action": (
                "Check Windows side: is the [IB PUSHER] CMD window still "
                "showing a healthy log? If it crashed, restart it via "
                "the .bat orchestrator OR re-run "
                "C:\\Users\\13174\\Trading-and-Analysis-Platform\\"
                "documents\\scripts\\ib_data_pusher.py manually. "
                "Do NOT restart the Spark backend — it's healthy."
            ),
            "since_seconds": pusher_red_for,
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
    if ib.get("status") == "yellow" and pusher_red:
        # Pusher is also red — pusher_rpc handler above has already
        # fired, no need to fire again here.
        pass
    elif snapshot.get("overall") == "yellow":
        # Some other yellow — surface as a thin warning strip.
        return {
            "level": "warning",
            "message": "Some subsystems are degraded",
            "detail": ", ".join(
                f"{s['name']}: {s.get('detail') or s['status']}"
                for s in snapshot.get("subsystems", [])
                if s.get("status") in ("yellow", "red")
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
