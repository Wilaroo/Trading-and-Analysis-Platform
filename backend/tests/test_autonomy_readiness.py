"""
Smoke + integration tests for /api/autonomy/readiness.

Locks in:
  * Endpoint always returns 200 with verdict in {green, amber, red}
  * Verdict logic: any red -> red, else any amber -> amber, else green
  * `ready_for_autonomous` only true when verdict == green
  * All 7 sub-checks present in `checks{}`
  * Risk-consistency warns when bot.max_open_positions > kill_switch.max_positions
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_readiness_smoke():
    """Endpoint must always respond cleanly with the expected shape."""
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8001/api/autonomy/readiness",
                             timeout=15.0)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["verdict"] in {"green", "amber", "red"}
    assert isinstance(body["ready_for_autonomous"], bool)
    assert isinstance(body["auto_execute_enabled"], bool)
    assert isinstance(body["blockers"], list)
    assert isinstance(body["warnings"], list)
    assert isinstance(body["checks"], dict)
    # All 7 named sub-checks must be present.
    for k in ("account", "pusher_rpc", "live_bars", "trophy_run",
              "kill_switch", "eod_auto_close", "risk_consistency"):
        assert k in body["checks"], f"missing check: {k}"
        assert body["checks"][k]["status"] in {"green", "amber", "red"}


@pytest.mark.asyncio
async def test_ready_for_autonomous_only_when_green():
    """`ready_for_autonomous` MUST be exactly verdict == green."""
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8001/api/autonomy/readiness",
                             timeout=15.0)
    body = r.json()
    assert body["ready_for_autonomous"] == (body["verdict"] == "green"), (
        "ready_for_autonomous must be true iff verdict is green"
    )


def _verdict_from_checks(checks: dict) -> str:
    """Mirror of the rollup logic in the route — pure unit test."""
    statuses = [c["status"] for c in checks.values()]
    if "red" in statuses:
        return "red"
    if "amber" in statuses:
        return "amber"
    return "green"


def test_verdict_red_when_any_red():
    checks = {
        "a": {"status": "green"},
        "b": {"status": "red"},
        "c": {"status": "amber"},
    }
    assert _verdict_from_checks(checks) == "red"


def test_verdict_amber_when_no_red_but_amber_present():
    checks = {
        "a": {"status": "green"},
        "b": {"status": "amber"},
        "c": {"status": "green"},
    }
    assert _verdict_from_checks(checks) == "amber"


def test_verdict_green_when_all_green():
    checks = {f"k{i}": {"status": "green"} for i in range(7)}
    assert _verdict_from_checks(checks) == "green"


# ── Risk-consistency edge cases (pure logic, no HTTP) ─────────────────

def _risk_warnings(bot_rp: dict, sf_cfg: dict) -> list:
    """Mirror of _check_risk_consistency without the HTTP layer."""
    warnings = []
    bot_max_pos = int(bot_rp.get("max_open_positions") or 0)
    sf_max_pos = int(sf_cfg.get("max_positions") or 0)
    if bot_max_pos and sf_max_pos and bot_max_pos > sf_max_pos:
        warnings.append("position_cap_conflict")
    bot_dl = float(bot_rp.get("max_daily_loss") or 0)
    sf_dl = float(sf_cfg.get("max_daily_loss_usd") or 0)
    if bot_dl == 0 and sf_dl > 0:
        warnings.append("daily_loss_unset")
    rr = float(bot_rp.get("min_risk_reward") or 0)
    if 0 < rr < 1.0:
        warnings.append("rr_below_one")
    pos_pct = float(bot_rp.get("max_position_pct") or 0)
    if pos_pct > 25:
        warnings.append("aggressive_position_pct")
    return warnings


def test_risk_consistency_clean_config():
    bot = {"max_open_positions": 5, "max_daily_loss": 500.0,
           "min_risk_reward": 1.5, "max_position_pct": 20.0}
    sf = {"max_positions": 5, "max_daily_loss_usd": 500.0}
    assert _risk_warnings(bot, sf) == []


def test_risk_consistency_position_cap_conflict():
    bot = {"max_open_positions": 10, "min_risk_reward": 1.5,
           "max_position_pct": 20.0, "max_daily_loss": 500.0}
    sf = {"max_positions": 5, "max_daily_loss_usd": 500.0}
    assert "position_cap_conflict" in _risk_warnings(bot, sf)


def test_risk_consistency_daily_loss_unset_warns():
    bot = {"max_open_positions": 5, "max_daily_loss": 0.0,
           "min_risk_reward": 1.5, "max_position_pct": 20.0}
    sf = {"max_positions": 5, "max_daily_loss_usd": 500.0}
    assert "daily_loss_unset" in _risk_warnings(bot, sf)


def test_risk_consistency_rr_below_one_warns():
    bot = {"max_open_positions": 5, "max_daily_loss": 500.0,
           "min_risk_reward": 0.8, "max_position_pct": 20.0}
    sf = {"max_positions": 5, "max_daily_loss_usd": 500.0}
    assert "rr_below_one" in _risk_warnings(bot, sf)


def test_risk_consistency_aggressive_position_pct_warns():
    bot = {"max_open_positions": 5, "max_daily_loss": 500.0,
           "min_risk_reward": 1.5, "max_position_pct": 50.0}
    sf = {"max_positions": 5, "max_daily_loss_usd": 500.0}
    assert "aggressive_position_pct" in _risk_warnings(bot, sf)
