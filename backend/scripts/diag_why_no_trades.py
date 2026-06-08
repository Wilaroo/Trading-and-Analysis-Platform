#!/usr/bin/env python3
"""
WHY NO TRADES? (read-only) — tally the auto-execute gate drops.

The scanner records EVERY alert it surfaces but does NOT auto-execute into the
`trade_drops` collection (gate="auto_exec_ineligible") with the exact failed
conditions in context.failed:
   priority=<x><high · tape_unconfirmed · no_strategy_stats · EV <=+0.10R ·
   stale_intraday_bars
…plus other gates (universal_liquidity_gate, account_guard, sym-dir-cap, etc.).

This script buckets the last N hours of `trade_drops` by GATE, and for the
auto-exec gate, by EACH failed condition (a drop can fail several at once), so you
can see the DOMINANT blocker keeping the bot flat. It also shows the priority +
tape-confirmation distribution across those drops.

`trade_drops` has a 7-day TTL. Timestamps: `ts` (ISO) + `ts_epoch_ms` (int).

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_why_no_trades.py [HOURS]   # default 8 (today's session)
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def main():
    db = _load_db()
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(hours=HOURS)).timestamp() * 1000)
    rows = list(
        db.trade_drops.find({"ts_epoch_ms": {"$gte": cutoff_ms}}, {"_id": 0, "ts_dt": 0})
        .sort("ts_epoch_ms", -1)
    )
    print(f"WHY NO TRADES — trade_drops in the last {HOURS:g}h  ({len(rows)} drops)\n")
    if not rows:
        print("  No drops recorded. Either the scanner surfaced nothing, or the bot")
        print("  isn't running / not in autonomous mode. Check bot_state.mode and")
        print("  whether _auto_execute_enabled is true (enable_auto_execute).")
        return

    # 1) Drops by gate
    by_gate = Counter(r.get("gate") or "unknown" for r in rows)
    print("=== drops by GATE ===")
    for gate, n in by_gate.most_common():
        print(f"  {n:>5}  {gate}")

    # 2) auto-exec gate — break down by each failed condition
    ae = [r for r in rows if (r.get("gate") == "auto_exec_ineligible")]
    if ae:
        print(f"\n=== auto_exec_ineligible — failed-condition tally ({len(ae)} drops) ===")
        cond = Counter()
        prio = Counter()
        tape = Counter()
        for r in ae:
            ctx = r.get("context") or {}
            for f in (ctx.get("failed") or []):
                # normalize the dynamic "priority=medium<high" / "EV +0.03R<=+0.10R"
                key = f
                if f.startswith("priority="):
                    key = "priority<high"
                elif f.startswith("win-rate"):
                    key = "win-rate<floor"
                elif f.startswith("EV "):
                    key = "EV<=min"
                cond[key] += 1
            prio[str(ctx.get("priority"))] += 1
            tape[bool(ctx.get("tape_confirmation"))] += 1
        for c, n in cond.most_common():
            pct = 100.0 * n / len(ae)
            print(f"  {n:>5} ({pct:4.0f}%)  {c}")
        print(f"\n  priority distribution: " +
              ", ".join(f"{k}={v}" for k, v in prio.most_common()))
        print(f"  tape_confirmation:     " +
              ", ".join(f"{k}={v}" for k, v in tape.most_common()))

        # 3) per-setup view — which setups are getting blocked most
        by_setup = defaultdict(lambda: Counter())
        for r in ae:
            s = r.get("setup_type") or "?"
            for f in (r.get("context") or {}).get("failed") or []:
                k = ("priority<high" if f.startswith("priority=")
                     else "EV<=min" if f.startswith("EV ")
                     else "win-rate<floor" if f.startswith("win-rate")
                     else f)
                by_setup[s][k] += 1
        print("\n=== top blocked setups (auto_exec_ineligible) ===")
        ranked = sorted(by_setup.items(), key=lambda kv: -sum(kv[1].values()))[:12]
        for setup, c in ranked:
            tot = sum(c.values())
            detail = ", ".join(f"{k}:{v}" for k, v in c.most_common())
            print(f"  {tot:>4}  {setup:<22} {detail}")

    # 4) other gates — sample reasons
    other = [r for r in rows if r.get("gate") != "auto_exec_ineligible"]
    if other:
        print("\n=== other gate drops — sample reasons ===")
        seen = set()
        for r in other:
            g = r.get("gate")
            if g in seen:
                continue
            seen.add(g)
            print(f"  [{g}] {r.get('symbol','?')} {r.get('setup_type','?')}: {r.get('reason','')[:90]}")

    print("\nINTERPRETATION:")
    print("  • 'priority<high' dominant   → setups never reach HIGH/CRITICAL priority")
    print("    (usually because tape isn't confirming). Look at tape_confirmation above.")
    print("  • 'tape_unconfirmed' dominant→ the tape pillar is gating; check tape_score feed.")
    print("  • 'no_strategy_stats'        → setup not registered in _strategy_stats (cold).")
    print("  • 'EV<=min'                  → proven setups with weak expectancy (working as intended).")


if __name__ == "__main__":
    main()
