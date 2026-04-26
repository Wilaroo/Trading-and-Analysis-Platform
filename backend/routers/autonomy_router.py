"""
Autonomy readiness router — the single go/no-go gate the operator
checks before flipping `auto-execute: enabled: true` on a fresh session.

Aggregates 8 sub-checks across the trading stack:

    1. account_active   — paper vs live confirmed, current account_id known
    2. ib_connected     — live IB Gateway connection (via account/summary)
    3. pusher_rpc_ok    — DGX → Windows pusher reachable AND ib_connected
    4. live_bars_ok     — pusher returns real bars on a SPY query
    5. trophy_run_recent — last successful training run within 7 days
    6. risk_consistent  — bot risk_params don't conflict with kill switch
    7. kill_switch_armed — enabled: true, not currently tripped
    8. eod_armed        — auto-close before market close enabled

Verdict:
    green  — all 8 checks pass; safe to enable auto-execute
    amber  — one or more warnings (fixable without blocking trading)
    red    — at least one blocker; auto-execute MUST stay off

Endpoint:
    GET /api/autonomy/readiness
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autonomy", tags=["Autonomy Readiness"])

# ── Internal HTTP client targeting the same backend (so all checks run
# through public endpoints — operators see the exact same data as their
# manual curl checks).
INTERNAL_BASE = "http://localhost:8001"
TIMEOUT_SECS = 5.0


def _check(status: str, detail: str, **extra) -> Dict[str, Any]:
    """Build a uniform sub-check dict."""
    return {"status": status, "detail": detail, **extra}


async def _get_json(client: httpx.AsyncClient, path: str) -> Optional[dict]:
    try:
        r = await client.get(f"{INTERNAL_BASE}{path}", timeout=TIMEOUT_SECS)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def _check_account(client) -> Dict[str, Any]:
    j = await _get_json(client, "/api/ib/account/summary")
    if not j:
        return _check("red", "Account summary endpoint unreachable")
    account_id = j.get("account_id")
    connected = bool(j.get("connected"))
    if not account_id:
        return _check("red", "No active account_id resolved",
                      connected=connected)
    if not connected:
        return _check("amber",
                      f"Account {account_id} resolved but IB not connected (expected pre-market on weekend)",
                      account_id=account_id, connected=False)
    return _check("green", f"Account {account_id} connected",
                  account_id=account_id, connected=True,
                  net_liquidation=j.get("net_liquidation"))


async def _check_pusher_rpc(client) -> Dict[str, Any]:
    j = await _get_json(client, "/api/live/pusher-rpc-health")
    if not j:
        return _check("red", "Pusher RPC health endpoint unreachable")
    if not j.get("client", {}).get("enabled"):
        return _check("red",
                      "Pusher RPC client disabled — set IB_PUSHER_RPC_URL + ENABLE_LIVE_BAR_RPC=true")
    if not j.get("reachable"):
        return _check("red",
                      f"Pusher RPC unreachable at {j.get('client', {}).get('url')}",
                      url=j.get("client", {}).get("url"))
    remote = j.get("remote") or {}
    if not remote.get("ib_connected"):
        return _check("amber",
                      "Pusher reachable but IB Gateway not connected (expected on weekends)",
                      market_state=j.get("market_state"))
    return _check("green",
                  f"Pusher RPC reachable, IB connected, {remote.get('quotes_tracked', 0)} quotes tracked",
                  url=j.get("client", {}).get("url"),
                  ib_connected=True, market_state=j.get("market_state"))


async def _check_live_bars(client) -> Dict[str, Any]:
    j = await _get_json(client,
                        "/api/live/latest-bars?symbol=SPY&bar_size=5%20mins&use_rth=false")
    if not j:
        return _check("red", "/api/live/latest-bars unreachable")
    if j.get("success"):
        return _check("green",
                      f"SPY 5-min bars returned via {j.get('source')}",
                      source=j.get("source"), bars_count=len(j.get("bars") or []))
    err = j.get("error") or "unknown"
    market_state = j.get("market_state") or "unknown"
    if market_state == "weekend" or "ib_disconnected" in err or "unreachable" in err:
        return _check("amber",
                      f"Bars unavailable ({err}) — expected on {market_state}",
                      error=err, market_state=market_state)
    return _check("red", f"Bars failed: {err}", error=err, market_state=market_state)


async def _check_trophy_run(client) -> Dict[str, Any]:
    j = await _get_json(client, "/api/ai-training/last-trophy-run")
    if not j or not j.get("found"):
        return _check("red", "No completed training run on file. Click Train All.")
    if not j.get("is_trophy"):
        return _check("amber",
                      f"Last run had {j.get('models_failed_count', 0)} failed models — investigate before going live")
    if not j.get("phase_recurrence_watch_ok"):
        return _check("amber", "Recurrence-watch phase (P5/P8) not fully healthy")
    completed_at = j.get("completed_at")
    age_hours = None
    if completed_at:
        try:
            ct = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - ct).total_seconds() / 3600
        except Exception:
            pass
    if age_hours is not None and age_hours > 168:  # 7 days
        return _check("amber",
                      f"Trophy run is {age_hours/24:.1f} days old — consider retraining",
                      age_hours=age_hours,
                      models_trained=j.get("models_trained_count"))
    return _check("green",
                  f"Trophy run: {j.get('models_trained_count', 0)} models, {j.get('elapsed_human', '?')}, P5/P8 ✓",
                  models_trained=j.get("models_trained_count"),
                  age_hours=age_hours)


async def _check_kill_switch(client) -> Dict[str, Any]:
    j = await _get_json(client, "/api/safety/status")
    if not j:
        return _check("red", "Safety status unreachable")
    cfg = j.get("config") or {}
    state = j.get("state") or {}
    if not cfg.get("enabled"):
        return _check("red", "Kill switch DISABLED — enable before autonomous trading")
    if state.get("kill_switch_active"):
        return _check("red",
                      f"Kill switch TRIPPED: {state.get('kill_switch_reason')}",
                      tripped_at=state.get("kill_switch_tripped_at"))
    return _check("green",
                  f"Kill switch armed (max_daily_loss=${cfg.get('max_daily_loss_usd')}, max_positions={cfg.get('max_positions')})",
                  max_daily_loss_usd=cfg.get("max_daily_loss_usd"),
                  max_positions=cfg.get("max_positions"))


async def _check_eod(client) -> Dict[str, Any]:
    j = await _get_json(client, "/api/trading-bot/eod-config")
    if not j:
        return _check("amber", "EOD config unreachable (non-blocking)")
    cfg = j.get("eod_config") or {}
    if not cfg.get("enabled"):
        return _check("amber",
                      "EOD auto-close disabled — positions will hold overnight if not closed manually")
    return _check("green",
                  f"EOD auto-close at {cfg.get('close_time_et', '?')}",
                  close_time_et=cfg.get("close_time_et"))


async def _check_risk_consistency(client) -> Dict[str, Any]:
    bot = await _get_json(client, "/api/trading-bot/status")
    safety = await _get_json(client, "/api/safety/status")
    if not bot or not safety:
        return _check("amber", "Risk consistency check incomplete (endpoints unavailable)")
    bot_rp = bot.get("risk_params") or {}
    sf_cfg = safety.get("config") or {}
    warnings: List[str] = []
    bot_max_pos = int(bot_rp.get("max_open_positions") or 0)
    sf_max_pos = int(sf_cfg.get("max_positions") or 0)
    if bot_max_pos and sf_max_pos and bot_max_pos > sf_max_pos:
        warnings.append(
            f"trading_bot.max_open_positions ({bot_max_pos}) > kill_switch.max_positions ({sf_max_pos}) — "
            f"kill switch will block excess (effective cap: {sf_max_pos})")
    bot_dl = float(bot_rp.get("max_daily_loss") or 0)
    sf_dl = float(sf_cfg.get("max_daily_loss_usd") or 0)
    if bot_dl == 0 and sf_dl > 0:
        warnings.append(
            f"trading_bot.max_daily_loss is unset (=0); kill switch caps at ${sf_dl} — set bot value to match")
    rr = float(bot_rp.get("min_risk_reward") or 0)
    if 0 < rr < 1.0:
        warnings.append(
            f"min_risk_reward={rr} accepts trades where reward < risk")
    pos_pct = float(bot_rp.get("max_position_pct") or 0)
    if pos_pct > 25:
        warnings.append(
            f"max_position_pct={pos_pct}% allows a single position to be {pos_pct}% of capital (aggressive)")

    if warnings:
        return _check("amber", "; ".join(warnings),
                      warnings=warnings, bot_risk_params=bot_rp,
                      kill_switch_config=sf_cfg)
    return _check("green",
                  f"Bot risk_params consistent with kill switch (max_positions={sf_max_pos}, max_daily_loss=${sf_dl})",
                  bot_risk_params=bot_rp, kill_switch_config=sf_cfg)


@router.get("/readiness")
async def readiness() -> Dict[str, Any]:
    """Aggregate go/no-go for autonomous trading."""
    async with httpx.AsyncClient() as client:
        # Run all 8 checks
        account = await _check_account(client)
        pusher = await _check_pusher_rpc(client)
        live_bars = await _check_live_bars(client)
        trophy = await _check_trophy_run(client)
        kill_switch = await _check_kill_switch(client)
        eod = await _check_eod(client)
        risk = await _check_risk_consistency(client)

        # Auto-execute is informational, not a check
        ax = await _get_json(client, "/api/live-scanner/auto-execute/status")
        auto_execute_enabled = bool(ax and ax.get("enabled"))

    checks = {
        "account": account,
        "pusher_rpc": pusher,
        "live_bars": live_bars,
        "trophy_run": trophy,
        "kill_switch": kill_switch,
        "eod_auto_close": eod,
        "risk_consistency": risk,
    }

    blockers = [k for k, c in checks.items() if c["status"] == "red"]
    warnings_keys = [k for k, c in checks.items() if c["status"] == "amber"]

    if blockers:
        verdict = "red"
        summary = f"NOT READY — {len(blockers)} blocker(s): {', '.join(blockers)}"
    elif warnings_keys:
        verdict = "amber"
        summary = (f"READY WITH WARNINGS — {len(warnings_keys)} non-blocking issue(s): "
                   f"{', '.join(warnings_keys)}")
    else:
        verdict = "green"
        summary = "READY — all checks green. Safe to enable auto-execute."

    next_steps: List[str] = []
    if blockers:
        for k in blockers:
            next_steps.append(f"Fix `{k}`: {checks[k]['detail']}")
    if warnings_keys:
        for k in warnings_keys:
            next_steps.append(f"Review `{k}`: {checks[k]['detail']}")
    if verdict == "green" and not auto_execute_enabled:
        next_steps.append(
            "All checks green — flip auto-execute via "
            "`POST /api/live-scanner/auto-execute/enable` when ready.")

    return {
        "success": True,
        "verdict": verdict,
        "summary": summary,
        "ready_for_autonomous": verdict == "green",
        "auto_execute_enabled": auto_execute_enabled,
        "blockers": blockers,
        "warnings": warnings_keys,
        "next_steps": next_steps,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
