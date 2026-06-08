"""v19.34.308 — IB-Gateway startup hard-block probe tests."""
import asyncio
import pytest

from services import ib_boot_probe as bp


def _reset_state():
    bp._STATE.update({
        "status": "pending", "detail": "probe not yet run",
        "order_path": None, "checked_at": None, "tripped_kill_switch": False,
    })


def test_probe_pass_sets_green(monkeypatch):
    _reset_state()
    monkeypatch.setattr(bp, "_probe_once", lambda: (True, "ib_direct connected (execution feed live)"))
    out = asyncio.run(bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01))
    assert out["status"] == "green"
    assert out["tripped_kill_switch"] is False


def test_probe_fail_trips_kill_switch(monkeypatch):
    _reset_state()
    tripped = {}

    class _FakeGuard:
        def trip_kill_switch(self, reason):
            tripped["reason"] = reason

    monkeypatch.setattr(bp, "_probe_once", lambda: (False, "ib_direct NOT connected"))
    # Patch the lazily-imported safety_guardrails accessor.
    import services.safety_guardrails as sg
    monkeypatch.setattr(sg, "get_safety_guardrails", lambda: _FakeGuard())

    out = asyncio.run(bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01))
    assert out["status"] == "red"
    assert out["tripped_kill_switch"] is True
    assert "ib_gateway_boot_probe_failed" in tripped["reason"]


def test_probe_once_never_raises(monkeypatch):
    _reset_state()
    # direct path but service raises → must return (False, detail), not raise.
    monkeypatch.setenv("BOT_ORDER_PATH", "direct")
    ok, detail = bp._probe_once()
    assert isinstance(ok, bool)
    assert isinstance(detail, str)
