"""v19.34.28 L3-hotfix3 — Regression: get_our_positions must NOT block on sync pusher RPC."""
from __future__ import annotations
import inspect
from pathlib import Path
from services import sentcom_service as svc_mod


def _strip_comments(src):
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_get_our_positions_does_not_call_gas_sync():
    src = inspect.getsource(svc_mod.SentComService.get_our_positions)
    code = _strip_comments(src)
    assert "_snap = _gas()" not in code, "L3-hotfix3: blocking _gas() pattern returned"
    assert "to_thread(_gas)" in code, "L3-hotfix3: _gas must be invoked via asyncio.to_thread"


def test_l3_hotfix3_marker_present():
    path = Path(svc_mod.__file__)
    assert "L3-hotfix3" in path.read_text(), "L3-hotfix3 marker missing"
