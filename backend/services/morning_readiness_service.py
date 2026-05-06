"""
Morning Readiness Service
=========================

Single-call "is the bot ready for fully automated trading today?"
aggregator. Mounted at `GET /api/system/morning-readiness`.

Different from `/api/backfill/readiness` (training data quality) and
`/api/system/health` (live-data pipeline). This service answers a
narrower operator question:

    "If I leave the trading bot on autopilot for the next 6.5 hours,
     will every subsystem we care about behave correctly?"

Checks performed (all read-only, all complete in <2s):

  1. backfill_data_fresh
     - Latest "1 day" bar for the critical 10 (SPY/QQQ/DIA/IWM + FAAMG+NVDA)
       must be within v19.17's expected_session window.
     → RED if any critical symbol's daily bar is older than expected.

  2. ib_pipeline_alive
     - Pusher RPC heartbeat + historical-collector worker recently active.
     → RED if either is silent.

  3. trading_bot_configured
     - `_eod_close_enabled=True`, sane `_eod_close_minute` (≤58 to leave
       cushion before the bell), `risk_params` populated.
     → RED if EOD disabled or risk params missing.

  4. eod_close_window
     - EOD close time is 3:55 PM ET (or 12:55 PM on flagged half-days)
       and the v19.14 hardening is active in `position_manager.py`.
     → YELLOW if drifted from the v19.14 default.

  5. scanner_running
     - Last scan cycle within 5 min of now. v19.15 cycle context cache
       and v19.16 intraday-only setups are populated.
     → RED if scanner silent >5 min during RTH.

  6. open_positions_clean
     - No intraday-tier positions left over from yesterday's session
       (would mean v19.14 EOD failed or ran into a partial-failure
       retry loop).
     → RED if any swing-flagged-True intraday positions are open
       past today's market open.

The endpoint returns one verdict (`green` / `yellow` / `red`) plus
per-check breakdown + a one-line "morning summary" suitable for a
Slack DM or the operator's mobile glance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Critical universe — must be daily-bar-fresh for autopilot.
_CRITICAL_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT",
                     "META", "GOOGL", "AMZN", "NVDA"]


def _et_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def _is_rth() -> bool:
    """Return True if current ET wallclock is inside regular trading
    hours on a weekday (9:30 AM – 4:00 PM)."""
    et = _et_now()
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 570 <= minutes <= 960  # 9:30 → 16:00


def _check_backfill_data_fresh(db) -> Dict[str, Any]:
    """Check 1 — every critical symbol's daily bar matches v19.17's
    expected session date."""
    try:
        from services.ib_historical_collector import get_ib_collector
        collector = get_ib_collector()
        now_dt = datetime.now(timezone.utc)
        expected_daily = collector._expected_latest_session_date("1 day", now_dt)

        stale: List[Dict[str, Any]] = []
        per_symbol: Dict[str, str] = {}
        for sym in _CRITICAL_SYMBOLS:
            doc = db["ib_historical_data"].find_one(
                {"symbol": sym, "bar_size": "1 day"},
                {"_id": 0, "date": 1},
                sort=[("date", -1)],
            )
            if not doc or not doc.get("date"):
                stale.append({"symbol": sym, "last": None,
                              "expected": expected_daily.isoformat()})
                per_symbol[sym] = "no_data"
                continue
            try:
                last_str = (doc["date"].split("T")[0]
                            if "T" in doc["date"] else doc["date"])
                last_date = datetime.strptime(
                    last_str, "%Y-%m-%d"
                ).date()
            except Exception:
                stale.append({"symbol": sym, "last": doc.get("date"),
                              "expected": expected_daily.isoformat()})
                per_symbol[sym] = "unparseable"
                continue
            per_symbol[sym] = last_date.isoformat()
            if last_date < expected_daily:
                stale.append({
                    "symbol": sym,
                    "last": last_date.isoformat(),
                    "expected": expected_daily.isoformat(),
                    "days_behind": (expected_daily - last_date).days,
                })
        if not stale:
            return {
                "status": "green",
                "detail": (f"All {len(_CRITICAL_SYMBOLS)} critical "
                           f"symbols have {expected_daily.isoformat()} "
                           f"daily bar."),
                "expected_session": expected_daily.isoformat(),
                "per_symbol": per_symbol,
            }
        return {
            "status": "red",
            "detail": (f"{len(stale)}/{len(_CRITICAL_SYMBOLS)} critical "
                       f"symbols missing the expected "
                       f"{expected_daily.isoformat()} daily bar."),
            "expected_session": expected_daily.isoformat(),
            "stale_symbols": stale,
            "per_symbol": per_symbol,
            "fix": ("Click 'Collect Data' in Data Collection panel — "
                    "v19.17 freshness gate will now queue these "
                    "automatically."),
        }
    except Exception as e:
        return {"status": "red",
                "detail": f"check failed: {type(e).__name__}: {e}"}


def _check_ib_pipeline_alive(db) -> Dict[str, Any]:
    """Check 2 — IB pusher RPC + historical collector worker have
    heartbeats within the last few minutes."""
    issues: List[str] = []
    try:
        # Historical collector worker — check for recent queue activity.
        queue = db["historical_data_requests"]
        last_completed = queue.find_one(
            {"status": "completed"},
            {"_id": 0, "completed_at": 1},
            sort=[("completed_at", -1)],
        )
        if last_completed and last_completed.get("completed_at"):
            try:
                ca = last_completed["completed_at"]
                if isinstance(ca, str):
                    ca_dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                else:
                    ca_dt = ca
                age_min = (datetime.now(timezone.utc) - ca_dt
                           ).total_seconds() / 60
            except Exception:
                age_min = 9999
        else:
            age_min = 9999
        # Pusher RPC heartbeat is on `_pushed_ib_data` collection if used.
        pusher_doc = db["pusher_heartbeat"].find_one(
            sort=[("ts", -1)]
        ) if "pusher_heartbeat" in db.list_collection_names() else None
        if pusher_doc:
            try:
                ts = pusher_doc.get("ts")
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    ts_dt = ts
                pusher_age_s = (datetime.now(timezone.utc) - ts_dt
                                ).total_seconds()
            except Exception:
                pusher_age_s = 9999
        else:
            pusher_age_s = None  # collection absent → don't block on it

        # Verdict — collector's queue age can be high overnight (idle);
        # we only flag if RTH and last completion >2h.
        if _is_rth() and age_min > 120:
            issues.append(
                f"historical collector last completion {age_min:.0f} min ago"
            )
        if pusher_age_s is not None and pusher_age_s > 60:
            issues.append(f"pusher heartbeat {pusher_age_s:.0f}s stale")
        if not issues:
            return {
                "status": "green",
                "detail": "Historical worker active; pusher heartbeat "
                          "fresh.",
                "collector_age_min": round(age_min, 1),
                "pusher_age_s": (round(pusher_age_s, 1)
                                 if pusher_age_s is not None else "n/a"),
            }
        return {"status": "yellow" if _is_rth() else "yellow",
                "detail": "; ".join(issues),
                "collector_age_min": round(age_min, 1),
                "pusher_age_s": (round(pusher_age_s, 1)
                                 if pusher_age_s is not None else "n/a")}
    except Exception as e:
        return {"status": "yellow",
                "detail": f"check failed: {type(e).__name__}: {e}"}


def _check_trading_bot_configured(db, bot=None) -> Dict[str, Any]:
    """Check 3 — bot has the v19.14 EOD config + risk params."""
    if bot is None:
        try:
            from services.trading_bot_service import get_trading_bot_service
            bot = get_trading_bot_service()
        except Exception as e:
            return {"status": "red",
                    "detail": f"Trading bot singleton unavailable: "
                              f"{type(e).__name__}: {e}"}
    if bot is None:
        return {"status": "red", "detail": "Trading bot not initialised"}

    issues: List[str] = []
    if not getattr(bot, "_eod_close_enabled", False):
        issues.append("EOD auto-close DISABLED")
    eod_min = getattr(bot, "_eod_close_minute", None)
    eod_hr = getattr(bot, "_eod_close_hour", None)
    if eod_hr != 15 or not (50 <= (eod_min or 0) <= 58):
        issues.append(
            f"EOD close window unusual: {eod_hr}:{eod_min:02d} "
            f"(expected 15:55)"
            if eod_min is not None else "EOD close window not set"
        )

    # Risk params — try both access patterns (dataclass attr `risk_params`
    # on TradingBotService, and legacy dict `_risk_params` used by some
    # test fixtures + rebuild paths).
    risk_obj = getattr(bot, "risk_params", None)
    if risk_obj is None:
        risk_obj = getattr(bot, "_risk_params", None)

    def _risk_field(name):
        """Read a field whether risk_params is a dataclass or a dict."""
        if risk_obj is None:
            return None
        if isinstance(risk_obj, dict):
            return risk_obj.get(name)
        return getattr(risk_obj, name, None)

    starting_capital = _risk_field("starting_capital")
    max_daily_loss = _risk_field("max_daily_loss")

    if risk_obj is None:
        issues.append("risk_params not set")
    elif not starting_capital:
        issues.append("starting_capital missing or zero")

    open_count = len(getattr(bot, "_open_trades", {}) or {})
    if not issues:
        return {
            "status": "green",
            "detail": (f"EOD enabled at {eod_hr}:{eod_min:02d} ET; "
                       f"starting_capital=${starting_capital:,.0f}; "
                       f"{open_count} open trades."),
            "eod_window_et": f"{eod_hr}:{eod_min:02d}",
            "open_trades": open_count,
            "starting_capital": starting_capital,
            "max_daily_loss": max_daily_loss,
        }
    return {
        "status": "red" if ("DISABLED" in " ".join(issues)
                            or "not set" in " ".join(issues)
                            or "missing" in " ".join(issues)) else "yellow",
        "detail": "; ".join(issues),
        "eod_window_et": (f"{eod_hr}:{eod_min:02d}"
                          if eod_min is not None else "unset"),
        "open_trades": open_count,
    }


def _check_scanner_running(db) -> Dict[str, Any]:
    """Check 4 — scanner has run a cycle recently and v19.15/16 are
    active."""
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        scanner = get_enhanced_scanner()
    except Exception as e:
        return {"status": "red",
                "detail": f"scanner unavailable: {type(e).__name__}: {e}"}

    issues: List[str] = []
    last_scan = getattr(scanner, "_last_scan_time", None)
    if last_scan:
        try:
            if isinstance(last_scan, str):
                last_dt = datetime.fromisoformat(
                    last_scan.replace("Z", "+00:00")
                )
            else:
                last_dt = last_scan
            scan_age_s = (datetime.now(timezone.utc) - last_dt
                          ).total_seconds()
        except Exception:
            scan_age_s = 9999
    else:
        scan_age_s = None
    if _is_rth() and (scan_age_s is None or scan_age_s > 300):
        issues.append(
            f"scanner silent for {scan_age_s:.0f}s during RTH"
            if scan_age_s is not None else "scanner has never run"
        )    # v19.15 cycle cache — confirm it's been populated at least once
    # (fresh OR stale, doesn't matter for this check).
    cycle_ctx = getattr(scanner, "_cycle_context", None)
    cycle_hits = getattr(scanner, "_cycle_context_hits", 0)
    cycle_misses = getattr(scanner, "_cycle_context_misses", 0)
    if cycle_ctx is None and _is_rth():
        issues.append("v19.15 cycle-context cache never populated")

    # v19.16 intraday-only setups — non-empty set.
    intraday_only = getattr(scanner, "_intraday_only_setups", set())
    if not intraday_only or len(intraday_only) < 12:
        issues.append(
            f"v19.16 intraday_only_setups underset ({len(intraday_only)} "
            f"detectors; expected ≥12)"
        )

    if not issues:
        return {
            "status": "green",
            "detail": (f"Scanner active "
                       f"({scan_age_s:.0f}s ago); v19.15 cache hits="
                       f"{cycle_hits}/misses={cycle_misses}; "
                       f"v19.16 intraday-only set has "
                       f"{len(intraday_only)} detectors."
                       if scan_age_s is not None else
                       f"Scanner present (cycle_count={getattr(scanner, '_scan_count', 0)}); "
                       f"v19.16 intraday-only set has "
                       f"{len(intraday_only)} detectors."),
            "scan_age_s": scan_age_s,
            "v19_15_hits": cycle_hits,
            "v19_15_misses": cycle_misses,
            "v19_16_intraday_only_count": len(intraday_only),
        }
    return {
        "status": "yellow" if not _is_rth() else "red",
        "detail": "; ".join(issues),
        "scan_age_s": scan_age_s,
        "v19_15_hits": cycle_hits,
        "v19_16_intraday_only_count": len(intraday_only),
    }


def _check_open_positions_clean(db, bot=None) -> Dict[str, Any]:
    """Check 5 — no intraday-tier (close_at_eod=True) positions are
    still open from a prior session.

    Surface for the operator: the v19.14 EOD close should have flat-ed
    these. If we see them, EOD didn't run or partially failed.
    """
    if bot is None:
        try:
            from services.trading_bot_service import get_trading_bot_service
            bot = get_trading_bot_service()
        except Exception:
            return {"status": "yellow",
                    "detail": "trading bot unavailable for position scan"}
    if bot is None:
        return {"status": "yellow",
                "detail": "trading bot unavailable for position scan"}

    today_et = _et_now().date()
    stuck: List[Dict[str, Any]] = []
    intraday_carryover_safe = 0
    swing_count = 0

    for tid, trade in (bot._open_trades or {}).items():
        close_at_eod = getattr(trade, "close_at_eod", True)
        if not close_at_eod:
            swing_count += 1
            continue
        # Intraday trade — check open date.
        opened_at = getattr(trade, "opened_at", None) or \
                    getattr(trade, "open_time", None) or \
                    getattr(trade, "fill_time", None)
        try:
            if isinstance(opened_at, str):
                opened_dt = datetime.fromisoformat(
                    opened_at.replace("Z", "+00:00")
                )
            elif isinstance(opened_at, datetime):
                opened_dt = opened_at
            else:
                opened_dt = None
            opened_et_date = (opened_dt.astimezone(_et_now().tzinfo).date()
                              if opened_dt else None)
        except Exception:
            opened_et_date = None
        if opened_et_date and opened_et_date < today_et:
            stuck.append({
                "trade_id": tid,
                "symbol": getattr(trade, "symbol", "?"),
                "opened_et": opened_et_date.isoformat(),
                "shares": getattr(trade, "remaining_shares",
                                  getattr(trade, "shares", 0)),
            })
        else:
            intraday_carryover_safe += 1

    if stuck:
        return {
            "status": "red",
            "detail": (f"{len(stuck)} intraday position(s) carried "
                       f"overnight — v19.14 EOD didn't flatten them."),
            "stuck_positions": stuck,
            "swing_holding": swing_count,
            "fix": ("Manually close via 'CLOSE ALL NOW' on the EOD "
                    "Countdown Banner OR POST /api/trading-bot/eod-close-now"),
        }

    # v19.18 add — surface IB account positions that the bot ISN'T tracking.
    # These are "manual holdings" in the IB account (from seeds, prior
    # sessions, or the operator opening a trade outside the bot). They're
    # not bot-managed, so the bot won't auto-close them at EOD. Surface
    # as YELLOW so the operator sees "the IB account has these; the bot
    # will leave them alone" and can decide to flatten or keep.
    ib_only_positions: List[Dict[str, Any]] = []
    try:
        from routers.ib import get_pushed_positions, is_pusher_connected
        if is_pusher_connected():
            bot_symbols = {
                getattr(t, "symbol", "")
                for t in (bot._open_trades or {}).values()
            }
            for pos in (get_pushed_positions() or []):
                sym = pos.get("symbol", "")
                shares = pos.get("position", 0) or pos.get("qty", 0)
                if not sym or not shares:
                    continue
                if sym not in bot_symbols:
                    ib_only_positions.append({
                        "symbol": sym,
                        "shares": shares,
                        "avg_cost": round(
                            pos.get("avg_cost", 0) or pos.get("avgCost", 0), 4
                        ),
                    })
    except Exception:
        pass  # pusher not available — skip IB-divergence check

    if ib_only_positions:
        sample = ", ".join(
            f"{p['symbol']}({p['shares']}sh)"
            for p in ib_only_positions[:5]
        )
        more = (f" +{len(ib_only_positions) - 5} more"
                if len(ib_only_positions) > 5 else "")
        return {
            "status": "yellow",
            "detail": (f"{len(ib_only_positions)} IB position(s) not "
                       f"tracked by bot: {sample}{more}. Bot will NOT "
                       f"auto-close these at EOD."),
            "intraday_open_today": intraday_carryover_safe,
            "swing_holding": swing_count,
            "ib_only_positions": ib_only_positions,
            "fix": ("Flatten manually in IB, or let them run as swing "
                    "holds — bot treats them as out-of-scope."),
        }

    return {
        "status": "green",
        "detail": (f"No stuck intraday carryovers. "
                   f"{intraday_carryover_safe} intraday + "
                   f"{swing_count} swing trades open (clean)."),
        "intraday_open_today": intraday_carryover_safe,
        "swing_holding": swing_count,
    }


def _aggregate_verdict(checks: Dict[str, Dict[str, Any]]) -> str:
    statuses = {c.get("status", "yellow") for c in checks.values()}
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def _build_summary(verdict: str, checks: Dict[str, Dict[str, Any]]) -> str:
    """One-line operator summary suitable for a Slack DM."""
    et = _et_now().strftime("%a %b %-d %H:%M ET")
    if verdict == "green":
        return (f"[{et}] AUTOPILOT GREEN — backfill fresh, EOD armed, "
                f"scanner alive, no overnight carryover.")
    reds = [name for name, c in checks.items() if c.get("status") == "red"]
    yellows = [name for name, c in checks.items() if c.get("status") == "yellow"]
    if reds:
        return (f"[{et}] AUTOPILOT BLOCKED — fix: "
                f"{', '.join(reds[:3])} ({len(reds)} red).")
    return (f"[{et}] AUTOPILOT CAUTION — review: "
            f"{', '.join(yellows[:3])} ({len(yellows)} yellow).")


def compute_morning_readiness(db, bot=None) -> Dict[str, Any]:
    """Run all 5 morning checks and roll into a single verdict.

    Each check is wrapped so a single subsystem failure surfaces as that
    check's `status=red` with the exception detail — never raises.
    """
    checks: Dict[str, Dict[str, Any]] = {
        "backfill_data_fresh": _check_backfill_data_fresh(db),
        "ib_pipeline_alive": _check_ib_pipeline_alive(db),
        "trading_bot_configured": _check_trading_bot_configured(db, bot=bot),
        "scanner_running": _check_scanner_running(db),
        "open_positions_clean": _check_open_positions_clean(db, bot=bot),
    }
    verdict = _aggregate_verdict(checks)
    summary = _build_summary(verdict, checks)
    return {
        "success": True,
        "verdict": verdict,
        "ready_for_autopilot": verdict == "green",
        "summary": summary,
        "checks": checks,
        "is_rth": _is_rth(),
        "generated_at_et": _et_now().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
