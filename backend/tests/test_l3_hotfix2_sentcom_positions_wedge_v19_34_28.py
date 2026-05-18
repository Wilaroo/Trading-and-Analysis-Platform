"""v19.34.28 L3-hotfix2 — Regression: /api/sentcom/positions MUST NOT block the event loop."""
from __future__ import annotations
import asyncio, inspect, time
from pathlib import Path
import pytest


def test_get_positions_does_not_call_list_cursor_directly():
    from routers import sentcom as sentcom_mod
    src = inspect.getsource(sentcom_mod.get_positions)
    code_lines = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert "to_thread(" in code, "L3-hotfix2: get_positions must use asyncio.to_thread"
    assert "closed_today_raw = list(cursor)" not in code, "L3-hotfix2: blocking pattern returned"


def test_source_marker_present():
    path = Path(__file__).parent.parent / "routers" / "sentcom.py"
    assert "L3-hotfix2" in path.read_text(), "L3-hotfix2 marker missing"


@pytest.mark.asyncio
async def test_to_thread_does_not_block_event_loop():
    SIMULATED = 0.8
    def _slow():
        time.sleep(SIMULATED)
        return [{"symbol": "TEST"}]
    ticks = {"n": 0}
    async def _heartbeat():
        deadline = time.monotonic() + SIMULATED + 0.2
        while time.monotonic() < deadline:
            ticks["n"] += 1
            await asyncio.sleep(0.05)
    t0 = time.monotonic()
    rows, _ = await asyncio.gather(asyncio.to_thread(_slow), _heartbeat())
    elapsed = time.monotonic() - t0
    assert rows == [{"symbol": "TEST"}]
    assert elapsed < SIMULATED + 0.4, f"Took {elapsed:.2f}s (expected ~{SIMULATED:.2f}s)"
    assert ticks["n"] >= 12, f"Heartbeat only ticked {ticks['n']} times — loop wedged"
