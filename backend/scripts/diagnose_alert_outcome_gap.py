"""Diagnose the alert→trade→outcome data gap.

Problem
-------
The setup coverage audit showed 11 setups with hundreds-to-thousands of scanner
alerts but ZERO decided outcomes (9_ema_scalp, spencer_scalp, abc_scalp,
volume_capitulation, hod_breakout, ...). We don't know whether:
  a) Scanner fires → bot REJECTS them (never becomes a trade), or
  b) Bot takes the trade but outcome never gets written back to live_alerts, or
  c) Trades complete but r_multiple/pnl never stored on bot_trades

This script quantifies each funnel stage per setup:

    alerts_fired → trades_executed → trades_closed → trades_with_r

and ranks setups by the biggest LEAK — that's where the pipeline needs fixing.

Run
---
    PYTHONPATH=backend python backend/scripts/diagnose_alert_outcome_gap.py

Output
------
    /tmp/alert_outcome_gap.md — per-setup funnel table with leak analysis
    stdout                    — compact summary
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from pymongo import MongoClient


def _norm(raw):
    """Collapse setup_type variants to a canonical root (mirrors audit script)."""
    if not raw:
        return None
    code = str(raw).strip().lower()
    for p in ("approaching_",):
        if code.startswith(p):
            code = code[len(p):]
    for s in ("_long", "_short", "_confirmed"):
        if code.endswith(s):
            code = code[: -len(s)]
    return code or None


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


# ── Pure stage classifier (unit-tested) ──────────────────────────────────

def classify_leak(stages: Dict[str, int]) -> str:
    """Given {'alerts', 'executed', 'closed', 'with_r'} return the biggest leak stage.

    Returns one of:
      - 'no_alerts' / 'no_executed' / 'no_closed' / 'no_r'
      - 'healthy'         — full funnel present
      - 'execution_gap'   — alerts but none executed
      - 'closure_gap'     — executed but not closed
      - 'r_gap'           — closed but no r_multiple
    """
    alerts = stages.get("alerts", 0)
    executed = stages.get("executed", 0)
    closed = stages.get("closed", 0)
    with_r = stages.get("with_r", 0)

    if alerts == 0 and executed == 0:
        return "no_alerts"
    if alerts > 0 and executed == 0:
        return "execution_gap"
    if executed > 0 and closed == 0:
        return "closure_gap"
    if closed > 0 and with_r == 0:
        return "r_gap"
    return "healthy"


# ── Data collection ──────────────────────────────────────────────────────

def collect_funnel(db) -> Dict[str, Dict[str, int]]:
    """Build per-setup funnel counts from 3 Mongo collections."""
    funnel: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"alerts": 0, "executed": 0, "closed": 0, "with_r": 0}
    )

    # Stage 1: live_alerts — every scanner fire
    for doc in db["live_alerts"].find(
        {"setup_type": {"$exists": True, "$nin": [None, ""]}},
        {"setup_type": 1, "_id": 0},
    ):
        code = _norm(doc.get("setup_type"))
        if code:
            funnel[code]["alerts"] += 1

    # Stages 2-4: bot_trades
    for doc in db["bot_trades"].find(
        {"setup_type": {"$exists": True, "$nin": [None, ""]}},
        {"setup_type": 1, "status": 1, "exit_price": 1, "realized_pnl": 1,
         "r_multiple": 1, "_id": 0},
    ):
        code = _norm(doc.get("setup_type"))
        if not code:
            continue
        funnel[code]["executed"] += 1

        closed = (
            doc.get("exit_price") is not None
            or doc.get("realized_pnl") not in (None, 0)
            or (doc.get("status") or "").lower() in ("closed", "exited", "filled_exited")
        )
        if closed:
            funnel[code]["closed"] += 1
            if doc.get("r_multiple") is not None:
                funnel[code]["with_r"] += 1

    return dict(funnel)


# ── Report ────────────────────────────────────────────────────────────────

LEAK_DESCRIPTIONS = {
    "healthy": "✅ full funnel (alerts→executed→closed→R)",
    "execution_gap": "🚨 alerts fire but bot never takes the trade",
    "closure_gap": "⚠️ trades executed but never closed (open or lost?)",
    "r_gap": "🟡 trades closed but r_multiple missing (run backfill)",
    "no_alerts": "— no scanner fires or bot activity",
}


def render_report(funnel: Dict[str, Dict[str, int]]) -> str:
    rows = sorted(funnel.items(), key=lambda kv: kv[1].get("alerts", 0), reverse=True)

    lines = [
        "# Alert → Trade → Outcome Funnel Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Per-setup funnel",
        "",
        "| setup | alerts | executed | closed | with_R | conv % | leak |",
        "|-------|-------:|---------:|-------:|-------:|-------:|------|",
    ]
    by_leak: Dict[str, list] = defaultdict(list)
    for code, st in rows:
        leak = classify_leak(st)
        by_leak[leak].append(code)
        alerts = st["alerts"]
        executed = st["executed"]
        conv = (executed / alerts * 100.0) if alerts else 0.0
        lines.append(
            f"| `{code}` | {alerts} | {executed} | {st['closed']} | "
            f"{st['with_r']} | {conv:.2f}% | {leak} |"
        )

    lines += ["", "## Summary by leak stage", ""]
    for leak, codes in sorted(by_leak.items(), key=lambda kv: -len(kv[1])):
        desc = LEAK_DESCRIPTIONS.get(leak, leak)
        lines.append(f"- **{leak}** ({len(codes)}): {desc}")
        lines.append(f"  - {', '.join(codes) if codes else '_none_'}")

    lines += [
        "",
        "## Interpretation",
        "",
        "- `execution_gap`: scanner is firing but **trading bot rejects** before entry. "
        "Check confidence gate, trade limits, or setup-enabled flags.",
        "- `closure_gap`: bot takes trades but **never writes exit_price/realized_pnl**. "
        "Check `_close_trade` / `position_manager` persistence.",
        "- `r_gap`: trades closed but **r_multiple missing** — run `backfill_r_multiples.py`.",
        "- `healthy`: full telemetry — safe to build Phase 2E models on this setup.",
        "",
    ]
    return "\n".join(lines)


def render_compact(funnel: Dict[str, Dict[str, int]]) -> str:
    by_leak: Dict[str, int] = defaultdict(int)
    for code, st in funnel.items():
        by_leak[classify_leak(st)] += 1

    lines = [
        "",
        "=" * 70,
        "ALERT → TRADE → OUTCOME FUNNEL",
        "=" * 70,
        f"Total setup codes with any activity: {len(funnel)}",
        "",
        "Pipeline health:",
    ]
    for leak in ("healthy", "r_gap", "closure_gap", "execution_gap", "no_alerts"):
        n = by_leak.get(leak, 0)
        desc = LEAK_DESCRIPTIONS.get(leak, leak)
        lines.append(f"  {desc:<60}  {n:>3} setups")

    # Top 10 worst leaks by alert volume
    rows = sorted(funnel.items(), key=lambda kv: kv[1].get("alerts", 0), reverse=True)
    lines += ["", "Top 10 alert volume — funnel leak:"]
    for code, st in rows[:10]:
        leak = classify_leak(st)
        lines.append(
            f"  {code:<28} alerts={st['alerts']:>6} exec={st['executed']:>4} "
            f"closed={st['closed']:>3} withR={st['with_r']:>3}  → {leak}"
        )

    lines += ["", "Full report: /tmp/alert_outcome_gap.md", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="/tmp/alert_outcome_gap.md")
    args = ap.parse_args()

    db = get_db()
    print(f"[gap-audit] db={db.name}")

    funnel = collect_funnel(db)
    md = render_report(funnel)
    Path(args.output).write_text(md)
    print(render_compact(funnel))


if __name__ == "__main__":
    main()
