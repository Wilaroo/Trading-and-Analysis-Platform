"""v336 — ib_boot_probe no longer latches RED forever: after a boot-grace
FAIL it keeps re-probing in the background and clears the HEALTH status
once the execution feed verifies live. The kill-switch latch stays
manual-reset (silent-start rationale untouched).

Probe evidence (2026-06-12): mid-session restart beat the deferred IB
connect; ib_boot_probe latched red + "1 CRITICAL" for the whole session
while ib_gateway itself was green.
"""
import asyncio
from pathlib import Path
import sys


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "ib_boot_probe.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services import ib_boot_probe as bp  # noqa: E402


def _reset_state():
    bp._STATE.update({
        "status": "pending", "detail": "probe not yet run",
        "order_path": None, "checked_at": None,
        "tripped_kill_switch": False, "recovered_at": None,
    })


class _FakeGuard:
    def __init__(self):
        self.tripped = []
        self.resets = []

    def trip_kill_switch(self, reason):
        self.tripped.append(reason)

    def reset_kill_switch(self, *a, **kw):
        self.resets.append(a)


def test_fail_then_recovery_clears_health(monkeypatch):
    _reset_state()
    feed = {"ok": False}
    monkeypatch.setattr(bp, "_probe_once",
                        lambda: (feed["ok"], "ib_direct connected (execution feed live)"
                                 if feed["ok"] else "ib_direct_service NOT connected"))
    guard = _FakeGuard()
    import services.safety_guardrails as sg
    monkeypatch.setattr(sg, "get_safety_guardrails", lambda: guard)

    async def _scenario():
        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01,
                                         recovery_poll_s=0.01)
        assert out["status"] == "red"
        assert out["tripped_kill_switch"] is True
        # feed comes alive a moment later → health must self-clear
        feed["ok"] = True
        for _ in range(100):
            await asyncio.sleep(0.02)
            if bp.get_boot_probe_state()["status"] == "green":
                break
        st = bp.get_boot_probe_state()
        assert st["status"] == "green", st
        assert "recovered" in st["detail"]
        assert st["recovered_at"] is not None

    asyncio.run(_scenario())
    # kill-switch latch must stay MANUAL: tripped once, never auto-reset
    assert len(guard.tripped) == 1
    assert guard.resets == []


def test_recovery_keeps_probing_until_live(monkeypatch):
    _reset_state()
    calls = {"n": 0}

    def _probe():
        calls["n"] += 1
        return (calls["n"] >= 4, "detail")
    monkeypatch.setattr(bp, "_probe_once", _probe)
    guard = _FakeGuard()
    import services.safety_guardrails as sg
    monkeypatch.setattr(sg, "get_safety_guardrails", lambda: guard)

    async def _scenario():
        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01,
                                         recovery_poll_s=0.01)
        assert out["status"] == "red"
        for _ in range(200):
            await asyncio.sleep(0.02)
            if bp.get_boot_probe_state()["status"] == "green":
                return
        raise AssertionError("recovery never flipped green")

    asyncio.run(_scenario())
    assert calls["n"] >= 4


def test_pass_path_unchanged(monkeypatch):
    _reset_state()
    monkeypatch.setattr(bp, "_probe_once", lambda: (True, "live"))

    async def _scenario():
        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01)
        assert out["status"] == "green"
        assert out["tripped_kill_switch"] is False
        assert out["recovered_at"] is None

    asyncio.run(_scenario())


def test_server_grace_env_tunable():
    src = (ROOT / "backend/server.py").read_text()
    assert "IB_BOOT_PROBE_GRACE_S" in src
