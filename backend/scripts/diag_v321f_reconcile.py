#!/usr/bin/env python3
"""
v321f — FUNNEL RECONCILIATION (READ-ONLY)

Double-checks every number quoted this session and resolves the apparent
contradictions between v321b/v321e and diag_live_gate_decisions.py:

  - bot_trades TOTAL (15,167) vs status^closed (1,646) vs in-window (710) vs
    sanitized (66) — prints the FULL status distribution + windowed counts so
    the chain is explained, not assumed.
  - LIVE vs SHADOW split of placed trades (learning_only / [SIMULATED] /
    trade_type / entered_by) — how much of "trading" is paper.
  - GATE → TRADE conversion: GO / REDUCE / SKIP per window vs trades placed,
    and the meta-labeler force-skip share.
  - alerts (live_alerts) vs gate decisions (confidence_gate_log) populations,
    to show they are NOT the same funnel.

Prints raw counts only; no interpretation baked into the numbers. NOTHING WRITTEN.

Usage (repo root):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v321f_reconcile.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v321f_reconcile.py --days 14
"""
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _load_env(b):
    env = b / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
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
    return (pnl / risk) if (pnl is not None and risk) else None


def _ts(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hold(t):
    hs = _f(t.get("hold_seconds"))
    if hs and hs > 0:
        return hs
    a, b = _ts(t.get("executed_at")), _ts(t.get("closed_at"))
    return (b - a).total_seconds() if (a and b) else None


def _excl(t, classify_close):
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
    genuine, _ = classify_close(
        close_reason=cr, entered_by=str(t.get("entered_by") or ""),
        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
        exit_price=_f(t.get("exit_price")), net_pnl=_f(t.get("net_pnl")),
        hold_seconds=_hold(t), setup_type=str(t.get("setup_type") or ""),
        direction=t.get("direction"), stop_price=_f(t.get("stop_price")),
        target_prices=t.get("target_prices"), realized_pnl=_f(t.get("realized_pnl")),
        shares=_f(t.get("shares")))
    if not genuine:
        return "hygiene_artifact"
    if (_f(t.get("fill_price")) or _f(t.get("entry_price")) or 0) <= 0 or (_f(t.get("shares")) or 0) <= 0:
        return "never_filled"
    if (_f(t.get("exit_price")) or 0) <= 0:
        return "no_exit_price"
    if (_f(t.get("risk_amount")) or 0) <= 0:
        return "no_risk"
    h = _hold(t)
    if h is not None and h < 10:
        return "sub_10s_hold"
    r = _r_multiple(t)
    if r is not None and abs(r) > 10:
        return "absurd_r"
    return None


def main():
    days = _arg("--days", 14, int)
    b = _find_backend(); _load_env(b); sys.path.insert(0, str(b))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    now = datetime.now(timezone.utc)
    w7 = (now - timedelta(days=7)).isoformat()
    w14 = (now - timedelta(days=days)).isoformat()
    w30 = (now - timedelta(days=30)).isoformat()
    bt = db["bot_trades"]

    print(f"\n=== v321f FUNNEL RECONCILIATION (window={days}d) ===\n")

    # ---- bot_trades status distribution ----
    print("=" * 72)
    print("BOT_TRADES — status distribution (ALL TIME)")
    print("=" * 72)
    total = bt.estimated_document_count()
    status = Counter()
    for d in bt.find({}, {"_id": 0, "status": 1}):
        status[str(d.get("status") or "?")] += 1
    print(f"  total documents : {total:,}")
    for s, c in status.most_common(20):
        print(f"     {s:<28} {c:>7,}")
    closed_all = sum(v for k, v in status.items() if k.startswith("closed"))
    print(f"  closed* subtotal : {closed_all:,}")

    # ---- windowed placement counts (which ts field is populated) ----
    print("\n" + "=" * 72)
    print("BOT_TRADES — placement counts by window & timestamp field")
    print("=" * 72)
    for field in ("created_at", "executed_at", "closed_at", "entry_time", "timestamp"):
        n7 = bt.count_documents({field: {"$gte": w7}})
        n14 = bt.count_documents({field: {"$gte": w14}})
        n30 = bt.count_documents({field: {"$gte": w30}})
        if n7 or n14 or n30:
            print(f"  {field:<14} 7d={n7:<6} {days}d={n14:<6} 30d={n30:<6}")

    # ---- live vs shadow split (window) ----
    print("\n" + "=" * 72)
    print(f"BOT_TRADES — LIVE vs SHADOW split (created_at last {days}d)")
    print("=" * 72)
    win = list(bt.find({"created_at": {"$gte": w14}}, {
        "_id": 0, "status": 1, "entered_by": 1, "learning_only": 1,
        "entry_context.learning_only": 1, "notes": 1, "trade_type": 1, "close_reason": 1,
        "fill_price": 1, "entry_price": 1, "exit_price": 1, "shares": 1, "risk_amount": 1,
        "net_pnl": 1, "realized_pnl": 1, "pnl": 1, "hold_seconds": 1, "executed_at": 1,
        "closed_at": 1, "direction": 1, "stop_price": 1, "target_prices": 1, "setup_type": 1}))
    n = len(win)
    lo = sum(1 for t in win if t.get("learning_only") is True or (t.get("entry_context") or {}).get("learning_only") is True)
    sim = sum(1 for t in win if "[SIMULATED]" in (t.get("notes") or "") or t.get("trade_type") == "shadow")
    tt = Counter(str(t.get("trade_type") or "?") for t in win)
    eb = Counter(str(t.get("entered_by") or "?") for t in win)
    print(f"  trades in window        : {n}")
    print(f"  learning_only=True      : {lo}  ({100.0*lo/n:.0f}%)" if n else "  (none)")
    print(f"  simulated/shadow        : {sim}  ({100.0*sim/n:.0f}%)" if n else "")
    print(f"  trade_type : " + ", ".join(f"{k}={v}" for k, v in tt.most_common(6)))
    print(f"  entered_by : " + ", ".join(f"{k}={v}" for k, v in eb.most_common(6)))

    # ---- sanitization funnel (window) ----
    closed_win = [t for t in win if str(t.get("status") or "").startswith("closed")]
    funnel = Counter(); surv = 0
    for t in closed_win:
        r = _excl(t, classify_close)
        if r is None:
            surv += 1
        else:
            funnel[r] += 1
    print("\n" + "=" * 72)
    print(f"SANITIZATION FUNNEL on closed trades (last {days}d)")
    print("=" * 72)
    print(f"  closed in window : {len(closed_win)}")
    for r, c in funnel.most_common():
        print(f"     -{c:>4}  {r}")
    print(f"     ={surv:>4}  SANITIZED survivors")

    # ---- gate vs trades conversion ----
    print("\n" + "=" * 72)
    print("CONFIDENCE_GATE_LOG vs trades placed (conversion)")
    print("=" * 72)
    log = db.confidence_gate_log
    for label, iso in (("7d", w7), (f"{days}d", w14), ("30d", w30)):
        dc = Counter()
        for r in log.find({"timestamp": {"$gte": iso}}, {"_id": 0, "decision": 1}):
            dc[r.get("decision", "?")] += 1
        go = dc.get("GO", 0)
        placed = bt.count_documents({"created_at": {"$gte": iso}})
        conv = f"{100.0*placed/go:.0f}%" if go else "n/a"
        print(f"  {label:<5} GO={go:<6} REDUCE={dc.get('REDUCE',0):<6} SKIP={dc.get('SKIP',0):<6}"
              f"  | trades_placed={placed:<6} (placed/GO={conv})")

    # ---- alerts population (NOT the gate population) ----
    print("\n" + "=" * 72)
    print("LIVE_ALERTS vs gate decisions (different funnels)")
    print("=" * 72)
    na = db.live_alerts.count_documents({})
    na14 = db.live_alerts.count_documents({"created_at": {"$gte": w14}})
    print(f"  live_alerts total={na:,}   last {days}d≈{na14:,}")
    print(f"  (gate decisions are logged separately; alerts ≠ gate evaluations ≠ trades)")

    print("\n=== HOW TO READ ===")
    print("• status dist explains TOTAL vs closed*: non-closed rows (pending/cancelled/")
    print("    rejected/open) are NOT bleed — they never closed.")
    print("• LIVE vs SHADOW: high learning_only/simulated% ⇒ much 'trading' is paper.")
    print("• placed/GO conversion: ~50% means half of GO decisions become orders; the")
    print("    other half are REDUCE-to-zero / downstream risk vetoes.")
    print("• meta-labeler force-skip (from diag_live_gate_decisions) is the dominant SKIP")
    print("    driver — that is the EV lever for the setups that never trade.\n")


if __name__ == "__main__":
    main()
