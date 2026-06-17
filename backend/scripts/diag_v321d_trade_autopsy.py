#!/usr/bin/env python3
"""
v321d — SETUP TRADE-LIFECYCLE AUTOPSY (READ-ONLY)

Closes the "trade it properly" third of the loop. v321b showed rubber_band:
192 alerts, 60% auto-fire-capable, yet 0 SANITIZED trades. WHY? This diag takes
ONE setup (default rubber_band, --setup overrides) and follows it from alert →
bot_trade → sanitization funnel, so we see EXACTLY where the outcome dies:

  • are trades even CREATED for these alerts? (alert→trade execution census)
  • of created trades, the STATUS / entered_by / close_reason / hold mix
  • the SANITIZATION funnel (same canonical classify_close as v321b) applied to
    just this setup → which exclusion bucket eats them (hygiene_artifact?
    no_exit_price? sub_10s_hold? simulated? learning_only?)
  • realized edge of the survivors (R = pnl ÷ risk_amount)

Reusable across the scalp family: --setup hitchhiker / big_dog / second_chance …
(prefix match, so rubber_band catches rubber_band_long/short).

NOTHING IS WRITTEN.

Usage (from repo root):
  .venv/bin/python backend/scripts/diag_v321d_trade_autopsy.py                      # rubber_band, 14d
  .venv/bin/python backend/scripts/diag_v321d_trade_autopsy.py --setup big_dog --days 21
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BOT_PROVENANCE = {"bot_fired", "bot", "", None}
ADMIN_CLOSE_PREFIXES = (
    "stale_pending", "phantom_sibling_purge", "consolidated", "broker_rejected",
    "execution_exception", "guardrail_veto", "intent_already_pending",
    "rejection_cooldown", "symbol_cooldown", "paper_phase", "simulation_phase",
    "operator_flatten_suppression", "emergency_flatten",
)


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services" / "trade_outcome_hygiene.py").exists():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t):
    pnl = t.get("net_pnl")
    if pnl in (None, 0):
        pnl = t.get("realized_pnl") if t.get("realized_pnl") not in (None, 0) else t.get("pnl")
    risk = _f(t.get("risk_amount"))
    pnl = _f(pnl)
    if pnl is None or not risk:
        return None
    return pnl / risk


def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hold_seconds(t):
    hs = _f(t.get("hold_seconds"))
    if hs is not None and hs > 0:
        return hs
    a, b = _parse_ts(t.get("executed_at")), _parse_ts(t.get("closed_at"))
    if a and b:
        return (b - a).total_seconds()
    return None


def _exclusion_reason(t, classify_close):
    if t.get("entered_by") not in BOT_PROVENANCE:
        return "provenance"
    ec = t.get("entry_context") or {}
    if t.get("learning_only") is True or ec.get("learning_only") is True:
        return "learning_only"
    if "[SIMULATED]" in (t.get("notes") or "") or t.get("trade_type") == "shadow":
        return "simulated"
    cr = str(t.get("close_reason") or "")
    if any(cr.startswith(p) for p in ADMIN_CLOSE_PREFIXES):
        return "admin_close"
    if "orphan" in cr.lower():
        return "legacy_orphan"
    genuine, tag = classify_close(
        close_reason=cr, entered_by=str(t.get("entered_by") or ""),
        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
        exit_price=_f(t.get("exit_price")), net_pnl=_f(t.get("net_pnl")),
        hold_seconds=_hold_seconds(t), setup_type=str(t.get("setup_type") or ""),
        direction=t.get("direction"), stop_price=_f(t.get("stop_price")),
        target_prices=t.get("target_prices"), realized_pnl=_f(t.get("realized_pnl")),
        shares=_f(t.get("shares")),
    )
    if not genuine:
        return f"hygiene_artifact:{tag}"
    fill = _f(t.get("fill_price")) or _f(t.get("entry_price")) or 0
    if fill <= 0 or (_f(t.get("shares")) or 0) <= 0:
        return "never_filled"
    if (_f(t.get("exit_price")) or 0) <= 0:
        return "no_exit_price"
    if (_f(t.get("risk_amount")) or 0) <= 0:
        return "no_risk"
    hs = _hold_seconds(t)
    if hs is not None and hs < 10:
        return "sub_10s_hold"
    r = _r_multiple(t)
    if r is not None and abs(r) > 10:
        return "absurd_r"
    return None


def _to_et(v):
    if isinstance(v, str) and len(v) >= 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
        except Exception:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(ET)
    return None


def _pct(n, d):
    return f"{(100.0 * n / d):.0f}%" if d else "n/a"


def main():
    setup = _arg("--setup", "rubber_band", str).strip().lower()
    days = _arg("--days", 14, int)

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"\n=== v321d TRADE AUTOPSY — setup='{setup}*'  trailing {days}d "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===\n")

    # ---- alert census (find / fire) ----
    alert_cells = defaultdict(int)
    alert_total = 0
    fire_capable = 0
    for a in db.live_alerts.find({}, {"_id": 0, "symbol": 1, "setup_type": 1,
                                       "priority": 1, "created_at": 1, "timestamp": 1, "ts": 1}):
        if not (a.get("setup_type") or "").lower().startswith(setup):
            continue
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if not (et and et >= start):
            continue
        alert_total += 1
        alert_cells[(a.get("symbol"), et.strftime("%Y-%m-%d"))] += 1
        if str(a.get("priority", "")).lower() in ("high", "critical"):
            fire_capable += 1
    print("=" * 78)
    print("SECTION 1 — ALERT census (find / fire)")
    print("=" * 78)
    print(f"  alerts                 : {alert_total}")
    print(f"  (symbol,day) cells     : {len(alert_cells)}")
    print(f"  HIGH+ (auto-fireable)  : {fire_capable}  ({_pct(fire_capable, alert_total)})")

    # ---- trade census (all statuses) ----
    all_tr = list(db["bot_trades"].find(
        {"setup_type": {"$regex": f"^{setup}"}},
        {"_id": 0, "id": 1, "symbol": 1, "status": 1, "entered_by": 1, "learning_only": 1,
         "entry_context.learning_only": 1, "notes": 1, "trade_type": 1, "close_reason": 1,
         "fill_price": 1, "entry_price": 1, "exit_price": 1, "shares": 1, "risk_amount": 1,
         "net_pnl": 1, "realized_pnl": 1, "pnl": 1, "hold_seconds": 1, "executed_at": 1,
         "closed_at": 1, "created_at": 1, "direction": 1, "stop_price": 1, "target_prices": 1}))
    inwin = []
    for t in all_tr:
        et = _to_et(t.get("created_at") or t.get("executed_at") or t.get("closed_at"))
        if et and et >= start:
            inwin.append(t)

    print("\n" + "=" * 78)
    print("SECTION 2 — TRADE census (created from these alerts?)")
    print("=" * 78)
    print(f"  bot_trades matching setup (all time) : {len(all_tr)}")
    print(f"  bot_trades in window                 : {len(inwin)}")
    status_mix = Counter(str(t.get("status") or "?") for t in inwin)
    print(f"  status mix  : " + ", ".join(f"{k}={v}" for k, v in status_mix.most_common()))
    eb_mix = Counter(str(t.get("entered_by") or "?") for t in inwin)
    print(f"  entered_by  : " + ", ".join(f"{k}={v}" for k, v in eb_mix.most_common()))
    if alert_total:
        print(f"  rough exec rate (trades/alerts)      : {_pct(len(inwin), alert_total)}")

    # ---- sanitization funnel applied to this setup ----
    closed = [t for t in inwin if str(t.get("status") or "").startswith("closed")]
    print("\n" + "=" * 78)
    print("SECTION 3 — WHY trades die: sanitization funnel on CLOSED trades")
    print("=" * 78)
    print(f"  closed trades in window : {len(closed)}")
    funnel = Counter()
    survivors = []
    for t in closed:
        r = _exclusion_reason(t, classify_close)
        if r is None:
            survivors.append(t)
        else:
            funnel[r] += 1
    for reason, n in funnel.most_common():
        print(f"     -{n:>4}  {reason}")
    print(f"     ={len(survivors):>4}  SANITIZED survivors")

    # close_reason mix (raw) for color
    cr_mix = Counter(str(t.get("close_reason") or "?")[:40] for t in closed)
    if cr_mix:
        print("\n  raw close_reason mix (top 10):")
        for cr, n in cr_mix.most_common(10):
            print(f"     {n:>4}  {cr}")

    # hold-time distribution
    holds = sorted(h for h in (_hold_seconds(t) for t in closed) if h is not None)
    if holds:
        n = len(holds)
        print(f"\n  hold_seconds: p10={holds[n//10]:.0f} p50={holds[n//2]:.0f} "
              f"p90={holds[min(9*n//10, n-1)]:.0f}  (<10s = sub_10s exclusion)")

    # ---- survivor edge ----
    print("\n" + "=" * 78)
    print("SECTION 4 — survivor realized edge")
    print("=" * 78)
    rs = [r for r in (_r_multiple(t) for t in survivors) if r is not None]
    if rs:
        wins = sum(1 for r in rs if r > 0)
        print(f"  n={len(rs)}  win%={100.0*wins/len(rs):.0f}  avgR={sum(rs)/len(rs):+.2f}  "
              f"medR={median(rs):+.2f}")
    else:
        print("  no sanitized survivors with usable R.")

    print("\n=== READING THE RESULT ===")
    print("• If SECTION 2 exec rate ≈ 0 → alerts NEVER become trades: a FIRE/gate problem")
    print("    (priority cap, EV-gate, cooldown) — fix upstream, not the exit.")
    print("• If trades exist but SECTION 3 is dominated by hygiene_artifact / no_exit_price /")
    print("    sub_10s_hold → trades fire but the MANAGEMENT/exit path mangles them: that's")
    print("    the 'trade it properly' bug, and it's shared across setups.")
    print("• simulated / learning_only dominant → they ARE working, just in shadow/paper —")
    print("    not a bug, a mode. Promote to live to get real outcomes.")
    print("• Survivor edge (SECTION 4) is only trustworthy at n≥~10; below that it's a hint.\n")


if __name__ == "__main__":
    main()
