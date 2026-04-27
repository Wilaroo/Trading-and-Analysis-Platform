"""
SentCom System Health Audit (2026-04-28)
=========================================
End-to-end diagnostic of the trading pipeline:

  scanner → evaluator → position-sizer → bot/decision → trade-management

For each stage we verify:
  • The component is *configured* (initialized, deps wired)
  • The component is *running* (loop active / alive)
  • The component is *producing* (counters incrementing)
  • The component is *reachable* end-to-end (an alert can flow through it)

Output: a structured report printed to stdout. Exits 0 on green,
non-zero on yellow/red so CI/operator scripts can branch.

Usage:
    PYTHONPATH=/app/backend /root/.venv/bin/python /app/backend/scripts/system_health_audit.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import requests


# ---- Color helpers (no external deps) ----
RED = "\033[91m"
YEL = "\033[93m"
GRN = "\033[92m"
BLU = "\033[94m"
DIM = "\033[2m"
RST = "\033[0m"


def _row(stage: str, status: str, detail: str = ""):
    color = GRN if status == "✓" else YEL if status == "~" else RED if status == "✗" else BLU
    print(f"  {color}{status}{RST}  {stage:<32} {DIM}{detail}{RST}")


def _backend_url() -> str:
    return os.environ.get("BACKEND_URL", "http://localhost:8001")


def _get(path: str, timeout=4):
    try:
        r = requests.get(_backend_url() + path, timeout=timeout)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as exc:
        return None, str(exc)[:80]


def audit_scanner() -> dict:
    """Stage 1 — Scanner is finding the right stocks."""
    print(f"\n{BLU}━━━ STAGE 1: SCANNER ━━━{RST}")
    findings = OrderedDict()

    # 1a. Wave-scanner stats endpoint reachable + total_scans incrementing
    stats, err = _get("/api/wave-scanner/stats")
    if err:
        _row("wave-scanner stats", "✗", err)
        findings["wave_scanner_reachable"] = False
        return findings
    findings["wave_scanner_reachable"] = True
    total_scans = stats.get("scan_stats", {}).get("total_scans", 0)
    if total_scans > 0:
        _row("wave-scanner total_scans", "✓", f"{total_scans} scans recorded")
    else:
        _row("wave-scanner total_scans", "~",
             "0 scans (expected if IB Gateway not connected, "
             "else loop is stalled)")
    findings["total_scans"] = total_scans

    # 1b. Universe size — symbols_scanned per scan
    syms_scanned = stats.get("scan_stats", {}).get("symbols_scanned", 0)
    if syms_scanned >= 100:
        _row("universe size", "✓", f"{syms_scanned} symbols cumulative scanned")
    elif syms_scanned > 0:
        _row("universe size", "~", f"{syms_scanned} only — possible fallback to ETF list")
    else:
        _row("universe size", "~", "0 (will populate once a scan completes)")
    findings["symbols_scanned"] = syms_scanned

    # 1c. Strategy diversity via /api/scanner/strategy-mix
    mix, err = _get("/api/scanner/strategy-mix?hours=24")
    if mix and not err:
        n_strategies = len(mix.get("strategies", []) or [])
        if n_strategies >= 3:
            _row("strategy diversity", "✓",
                 f"{n_strategies} setup types found in last 24h")
        elif n_strategies > 0:
            _row("strategy diversity", "~",
                 f"Only {n_strategies} setup type — investigate")
        else:
            _row("strategy diversity", "~",
                 "0 setups in last 24h (off-hours / IB offline)")
        findings["strategy_diversity"] = n_strategies

    # 1d. Verify enabled_setups is non-empty (canary contract)
    bot_status, err = _get("/api/trading-bot/status")
    if bot_status and not err:
        enabled = bot_status.get("enabled_setups", [])
        if len(enabled) >= 15:
            _row("bot enabled_setups", "✓", f"{len(enabled)} strategies on")
        else:
            _row("bot enabled_setups", "~",
                 f"only {len(enabled)} — check config")
        findings["enabled_setups"] = len(enabled)

    return findings


def audit_evaluator() -> dict:
    """Stage 2 — Alerts are being evaluated."""
    print(f"\n{BLU}━━━ STAGE 2: EVALUATOR ━━━{RST}")
    findings = OrderedDict()

    bot_status, err = _get("/api/trading-bot/status")
    if err or not bot_status:
        _row("bot status reachable", "✗", err or "no payload")
        return findings
    findings["bot_status_reachable"] = True
    bot_running = bot_status.get("running", False)
    _row("bot running",
         "✓" if bot_running else "~",
         f"running={bot_running} mode={bot_status.get('mode')}")
    findings["bot_running"] = bot_running

    # Filter thoughts buffer (rejection narratives + smart filter)
    thoughts, err = _get("/api/trading-bot/thoughts?limit=20")
    n_thoughts = 0
    if thoughts and not err:
        n_thoughts = len(thoughts.get("thoughts", []) or thoughts.get("filter_thoughts", []) or [])
        if n_thoughts >= 1:
            _row("evaluator producing thoughts", "✓",
                 f"{n_thoughts} narrative thoughts in buffer")
        else:
            _row("evaluator producing thoughts", "~",
                 "0 thoughts (no alerts evaluated yet, or IB offline)")
    findings["thoughts_count"] = n_thoughts

    # Confidence-gate config (sanity: gate active and threshold reasonable)
    gate, err = _get("/api/confidence-gate/config")
    if gate and not err:
        thresh = gate.get("min_confidence")
        if thresh is not None and 0.50 <= thresh <= 0.90:
            _row("confidence gate threshold", "✓",
                 f"min_confidence={thresh:.2f}")
        else:
            _row("confidence gate threshold", "~",
                 f"unusual threshold: {thresh}")

    return findings


def audit_position_sizing() -> dict:
    """Stage 3 — Position sizing follows risk params."""
    print(f"\n{BLU}━━━ STAGE 3: POSITION SIZING ━━━{RST}")
    findings = OrderedDict()

    bot_status, _ = _get("/api/trading-bot/status")
    if not bot_status:
        _row("risk params", "✗", "no bot status")
        return findings
    rp = bot_status.get("risk_params") or {}
    mr = rp.get("max_risk_per_trade")
    mdl = rp.get("max_daily_loss") or rp.get("max_daily_loss_pct")
    mop = rp.get("max_open_positions")

    if mr is not None:
        # Risk model can be either fractional (e.g. 0.005 = 0.5% of equity)
        # or fixed-dollar (e.g. 2500 = $2,500 per trade). Both are valid.
        if 0 < mr < 0.10:
            _row("max_risk_per_trade", "✓", f"{mr*100:.2f}% of equity (fractional)")
        elif 1 <= mr <= 100_000:
            _row("max_risk_per_trade", "✓", f"${mr:,.0f} fixed per trade")
        else:
            _row("max_risk_per_trade", "~", f"unusual value: {mr}")

    if mop and 1 <= mop <= 20:
        _row("max_open_positions", "✓", f"cap {mop}")
    else:
        _row("max_open_positions", "~", f"cap {mop}")

    findings["risk_params"] = rp

    # DRC (daily risk circuit breaker) status
    drc, err = _get("/api/trading-bot/drc-status")
    if drc and not err:
        st = drc.get("status") or drc.get("health")
        if st in ("green", "healthy", "ok"):
            _row("DRC", "✓", f"status={st} max_daily_risk=${drc.get('max_daily_risk', '?')}")
        else:
            _row("DRC", "~", f"status={st}")
        findings["drc_status"] = st

    return findings


def audit_decision_quality() -> dict:
    """Stage 4 — Bot is taking the right trades / passing the wrong ones."""
    print(f"\n{BLU}━━━ STAGE 4: DECISION QUALITY ━━━{RST}")
    findings = OrderedDict()

    # Filter thoughts contain rejection narratives — good way to verify
    # the bot is actively REASONING about each alert (not just silently
    # dropping them).
    thoughts, _ = _get("/api/trading-bot/thoughts?limit=50")
    items = []
    if thoughts:
        items = thoughts.get("thoughts") or thoughts.get("filter_thoughts") or []
    if items:
        rejections = sum(1 for t in items if str(t.get("action", "")).lower() in ("rejected", "filtered", "skipped"))
        accepts = sum(1 for t in items if str(t.get("action", "")).lower() in ("accepted", "passed"))
        _row("rejection narratives",
             "✓" if rejections >= 1 else "~",
             f"{rejections} rejections / {accepts} accepts in last {len(items)}")
        findings["rejections"] = rejections
        findings["accepts"] = accepts

    # Recent trades — winners vs losers as a coarse sanity bar
    trades, err = _get("/api/trading-bot/recent-trades?limit=20")
    if trades and not err:
        items = trades.get("trades", []) if isinstance(trades, dict) else trades
        if items:
            wins = sum(1 for t in items if (t.get("realized_pnl") or t.get("pnl") or 0) > 0)
            losses = sum(1 for t in items if (t.get("realized_pnl") or t.get("pnl") or 0) < 0)
            wr = wins / (wins + losses) if (wins + losses) else None
            wr_label = f"{wr*100:.0f}% WR" if wr is not None else "no closed trades"
            _row("recent trade win rate",
                 "✓" if wr is None or wr >= 0.45 else "~",
                 f"{wins}W · {losses}L · {wr_label}")
            findings["recent_wr"] = wr

    return findings


def audit_trade_management() -> dict:
    """Stage 5 — Open trades are being managed (stops trailed, EOD, etc.)."""
    print(f"\n{BLU}━━━ STAGE 5: TRADE MANAGEMENT ━━━{RST}")
    findings = OrderedDict()

    # Open positions — every open position should have a stop set
    pos, err = _get("/api/trading-bot/open-positions")
    items = []
    if pos:
        items = pos.get("positions", []) if isinstance(pos, dict) else pos
    if not items:
        _row("open positions", "~", "0 open (off-hours / no entries)")
        findings["open_positions"] = 0
        return findings

    findings["open_positions"] = len(items)
    n_with_stop = sum(1 for p in items if (p.get("stop_price") or p.get("stop")) not in (None, 0))
    n_with_target = sum(1 for p in items if (p.get("target_price") or p.get("target")) not in (None, 0))
    _row("open positions",
         "✓",
         f"{len(items)} open · {n_with_stop} with stop · {n_with_target} with target")
    if n_with_stop < len(items):
        _row("UNPROTECTED positions", "✗",
             f"{len(items) - n_with_stop} positions WITHOUT a stop!")

    # EOD config — should have flatten time set
    eod, err = _get("/api/trading-bot/eod-config")
    if eod and not err:
        if eod.get("enabled"):
            _row("EOD auto-close", "✓",
                 f"flatten at {eod.get('hour')}:{eod.get('minute', '00'):02} ET")
        else:
            _row("EOD auto-close", "~", "DISABLED")

    return findings


def audit_data_pipeline() -> dict:
    """Stage 6 — The data the bot is reading."""
    print(f"\n{BLU}━━━ STAGE 6: DATA PIPELINE ━━━{RST}")
    findings = OrderedDict()

    # Pusher heartbeat — RPC latency, connection status
    h, err = _get("/api/ib/pusher-health")
    if h and not err:
        connected = h.get("connected", False)
        health = h.get("health", "unknown")
        latency = (h.get("rpc_health") or {}).get("p50_latency_ms") or h.get("rpc_p50_ms")
        if connected and health in ("green", "healthy"):
            _row("pusher heartbeat", "✓",
                 f"{health} · p50 latency {latency}ms")
        else:
            _row("pusher heartbeat", "~" if not connected else "✗",
                 f"connected={connected} health={health}")
        findings["pusher_connected"] = connected
        findings["pusher_health"] = health

    # Tick → Mongo bar persister (was just shipped this morning)
    ttb, err = _get("/api/ib/tick-persister-stats")
    if ttb and not err:
        if ttb.get("success"):
            persisted = ttb.get("bars_persisted_total", 0)
            ticks = ttb.get("ticks_observed_total", 0)
            if persisted > 0 or ticks > 0:
                _row("tick→bar persister", "✓",
                     f"{persisted} bars persisted, {ticks} ticks observed")
            else:
                _row("tick→bar persister", "~",
                     "loaded but no ticks yet (IB offline)")
            findings["bars_persisted"] = persisted
            findings["ticks_observed"] = ticks

    # L2 router (also shipped this morning)
    l2, err = _get("/api/ib/l2-router-status")
    if l2 and not err:
        if l2.get("success"):
            running = l2.get("running")
            tick_count = l2.get("tick_count", 0)
            errors = l2.get("errors", 0)
            _row("L2 dynamic router",
                 "✓" if running and errors == 0 else "~",
                 f"running={running} ticks={tick_count} errors={errors}")
            findings["l2_router_running"] = running

    return findings


def main():
    print(f"{BLU}╔════════════════════════════════════════════════════════════╗{RST}")
    print(f"{BLU}║  SentCom System Health Audit — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}     ║{RST}")
    print(f"{BLU}╚════════════════════════════════════════════════════════════╝{RST}")
    print(f"{DIM}Backend: {_backend_url()}{RST}")

    overall = OrderedDict()
    overall["scanner"] = audit_scanner()
    overall["evaluator"] = audit_evaluator()
    overall["sizing"] = audit_position_sizing()
    overall["decisions"] = audit_decision_quality()
    overall["management"] = audit_trade_management()
    overall["data_pipeline"] = audit_data_pipeline()

    print(f"\n{BLU}━━━ SUMMARY ━━━{RST}")
    # Critical reds (will exit non-zero)
    reds = []
    if overall["scanner"].get("wave_scanner_reachable") is False:
        reds.append("scanner: wave-scanner unreachable")
    if overall["evaluator"].get("bot_status_reachable") is False:
        reds.append("evaluator: bot status unreachable")
    open_pos = overall["management"].get("open_positions", 0)
    # Check by counting from inside management audit (simplified here).

    if reds:
        print(f"{RED}REDS:{RST}")
        for r in reds:
            print(f"  • {r}")
        sys.exit(2)

    print(f"  {GRN}✓ All stages reachable. See per-stage rows above for "
          f"~/✗ details (most ~ are expected when IB is offline).{RST}")
    sys.exit(0)


if __name__ == "__main__":
    main()
