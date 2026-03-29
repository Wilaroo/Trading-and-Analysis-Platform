"""
Shared collection mode state.

This lightweight module avoids circular imports between routers/ and services/.
Both the router (sets the flag) and the scanners (check the flag) import this.
"""

state = {
    "active": False,
    "started_at": None,
    "instances": 0,
}


def is_active() -> bool:
    return state["active"]


def activate():
    from datetime import datetime, timezone
    state["active"] = True
    state["instances"] = state.get("instances", 0) + 1
    state["started_at"] = datetime.now(timezone.utc).isoformat()


def deactivate():
    state["active"] = False
    state["instances"] = 0
    state["started_at"] = None
