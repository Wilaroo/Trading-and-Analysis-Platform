"""
v19.31 (2026-05-04) — regression pin for the `pusher_red` NameError that
was breaking every call to GET /api/system/banner.

The v19.30.12 refactor introduced a 4-quadrant push×RPC severity matrix
but left an IB-yellow branch (line 260) referencing `pusher_red`, a
variable that no longer existed in scope. Result: every banner poll
returned 500 → SystemBanner UI never rendered → operator lost the
giant red strip we built specifically so pusher outages can't be missed.

These tests pin the contract:
  1. GET /api/system/banner returns 200 (not 500) when ib_gateway is
     yellow and pusher is red.
  2. Source-level pin: the function does NOT reference an undefined
     `pusher_red` symbol (catches accidental re-introduction).
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest


# Make backend importable without running the full server.py module.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_system_banner_does_not_reference_undefined_pusher_red():
    """Source-level pin: `pusher_red` (without `_now` suffix) must NOT
    appear as a free variable inside `get_system_banner`. Catches the
    exact regression we just fixed.
    """
    from routers import system_banner

    src = inspect.getsource(system_banner.get_system_banner)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, (ast.AsyncFunctionDef, ast.FunctionDef))

    # Collect every Name node that's read (Load context) inside the func.
    loaded_names = {
        node.id
        for node in ast.walk(func_def)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    # Collect all assigned names so we can subtract locals.
    assigned_names = {
        target.id
        for node in ast.walk(func_def)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    } | {
        node.target.id
        for node in ast.walk(func_def)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    # `pusher_red` (the bug) must not be referenced anywhere as a Load.
    # `pusher_red_now` (the fix) is allowed.
    free_pusher_red = (
        "pusher_red" in loaded_names
        and "pusher_red" not in assigned_names
    )
    assert not free_pusher_red, (
        "`pusher_red` is referenced but never assigned inside "
        "get_system_banner — this is the v19.31 regression. "
        "Use `pusher_red_now` (re-derived from `pusher_status`) instead."
    )


@pytest.mark.asyncio
async def test_get_system_banner_returns_200_when_ib_yellow():
    """Live call: drive build_health to return ib_gateway=yellow and
    confirm get_system_banner doesn't 500 with NameError."""
    from routers import system_banner as sb

    # Stub build_health to a minimal yellow snapshot.
    fake_snapshot = {
        "overall": "yellow",
        "as_of": "2026-05-04T13:47:00Z",
        "subsystems": [
            {
                "name": "ib_gateway",
                "status": "yellow",
                "detail": "no IB path",
                "metrics": {},
            },
            {
                "name": "pusher_rpc",
                "status": "yellow",
                "detail": "RPC degraded but pushing",
                "metrics": {
                    "consecutive_failures": 1,
                    "push_age_s": 5.0,
                    "push_fresh": True,
                },
            },
        ],
    }

    # Patch build_health import inside the handler.
    import services.system_health_service as shs
    original = shs.build_health
    try:
        shs.build_health = lambda _db: fake_snapshot
        result = await sb.get_system_banner()
    finally:
        shs.build_health = original

    # Should NOT raise. Should return a dict (level may be None or warning).
    assert isinstance(result, dict)
    assert "level" in result
    assert "as_of" in result


@pytest.mark.asyncio
async def test_get_system_banner_returns_200_when_pusher_red_and_ib_yellow():
    """The exact failure scenario: ib_gateway=yellow + pusher=red.
    The v19.30.12 refactor tried to silence the IB-yellow banner in
    this case (since the pusher_rpc handler already fired), but left
    the dangling `pusher_red` reference. Confirm it now works."""
    from routers import system_banner as sb

    fake_snapshot = {
        "overall": "red",
        "as_of": "2026-05-04T13:47:00Z",
        "subsystems": [
            {
                "name": "ib_gateway",
                "status": "yellow",
                "detail": "no IB path",
                "metrics": {},
            },
            {
                "name": "pusher_rpc",
                "status": "red",
                "detail": "Windows pusher unreachable",
                "metrics": {
                    "consecutive_failures": 10,
                    "push_age_s": 120.0,
                    "push_fresh": False,
                },
            },
        ],
    }

    import services.system_health_service as shs
    original = shs.build_health
    try:
        shs.build_health = lambda _db: fake_snapshot
        result = await sb.get_system_banner()
    finally:
        shs.build_health = original

    assert isinstance(result, dict)
    # Should NOT have raised NameError. Banner level may be critical
    # (pusher_rpc_dead path) — what matters is it returned a dict.
    assert "as_of" in result
