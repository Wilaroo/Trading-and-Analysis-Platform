#!/usr/bin/env python3
"""
Audit Phase 4 (Manage) — READ-ONLY diagnostic.

Empirically confirms two findings before any code change:

  M1  Trailing engine can get STUCK at breakeven: a trade that hit Target-2
      (scale_out_config.targets_hit contains index 1) should be in
      trailing_stop_config.mode == 'trailing'. If it's still 'breakeven'/'original',
      the dedicated % -trail engine never engaged (only the 60s resnap ratcheted it).

  M2  Trailed/breakeven stop moves are LOCAL-ONLY: counts trades whose local stop
      ratcheted past the original (stop_adjustments with trail/resnap/breakeven
      reasons). Each such trade had an in-memory stop tighter than the resting IB
      bracket stop — the server-side exposure window M2 describes. (Sizing, not proof:
      M2 is a code-structure fact — the trailing path never calls reissue/modify.)

Does NOT write anything. Uses {"_id": 0} projection. Safe to run on the live DGX.

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    ../.venv/bin/python scripts/audit_phase4_manage_diagnostic.py
    # optional: --days 30   (default: all trades)
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone


def _load_env():
    """Load MONGO_URL / DB_NAME from backend/.env without extra deps."""
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    mongo = os.environ.get("MONGO_URL")
    db = os.environ.get("DB_NAME")
    if not mongo or not db:
        print("ERROR: MONGO_URL / DB_NAME not found in env or backend/.env")
        sys.exit(2)
    return mongo, db


TRAIL_ENGINE_REASONS = ("trail_up", "trail_down", "trailing_activated")
RESNAP_REASONS = ("resnap",)
BREAKEVEN_REASONS = ("breakeven",)


def _reasons(trade):
    cfg = trade.get("trailing_stop_config") or {}
    return [str((a or {}).get("reason", "")).lower()
            for a in (cfg.get("stop_adjustments") or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0,
                    help="Only trades fired in the last N days (0 = all).")
    args = ap.parse_args()

    mongo_url, db_name = _load_env()
    from pymongo import MongoClient
    cli = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = cli[db_name]

    q = {"fill_price": {"$ne": None}}  # only trades that actually filled
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        q["$or"] = [{"executed_at": {"$gte": cutoff}},
                    {"created_at": {"$gte": cutoff}}]

    proj = {"_id": 0, "symbol": 1, "direction": 1, "status": 1,
            "close_reason": 1, "executed_at": 1, "trade_style": 1,
            "scale_out_config": 1, "trailing_stop_config": 1}
    trades = list(db["bot_trades"].find(q, proj))

    total = len(trades)
    print("=" * 72)
    print(f"AUDIT PHASE 4 — MANAGE DIAGNOSTIC   ({db_name})")
    print(f"filled trades scanned: {total}"
          + (f"  (last {args.days}d)" if args.days else "  (all time)"))
    print("=" * 72)
    if total == 0:
        print("No filled bot_trades found — nothing to analyze.")
        return

    # ── M1 — did % -trailing engage after T2? ─────────────────────────────
    hit_t1 = hit_t2 = 0
    mode_after_t2 = Counter()
    t2_no_trail_engine = []        # hit T2 but trail engine never ran
    t2_examples = []
    for t in trades:
        sc = t.get("scale_out_config") or {}
        th = sc.get("targets_hit") or []
        try:
            th = [int(x) for x in th]
        except Exception:
            th = []
        if 0 in th:
            hit_t1 += 1
        if 1 in th:
            hit_t2 += 1
            cfg = t.get("trailing_stop_config") or {}
            mode = str(cfg.get("mode", "original")).lower()
            mode_after_t2[mode] += 1
            reasons = _reasons(t)
            trail_engine_ran = any(any(r.startswith(p) or p in r for p in TRAIL_ENGINE_REASONS)
                                   for r in reasons)
            if not trail_engine_ran:
                t2_no_trail_engine.append(t)
            if len(t2_examples) < 8:
                t2_examples.append((t.get("symbol"), mode, t.get("close_reason"),
                                    "trail_engine" if trail_engine_ran else "NO_trail_engine"))

    print("\n── M1: trailing engine vs breakeven after Target-2 ──")
    print(f"  trades that hit Target-1 (idx 0): {hit_t1}")
    print(f"  trades that hit Target-2 (idx 1): {hit_t2}")
    if hit_t2:
        print(f"  mode AFTER hitting T2:  {dict(mode_after_t2)}")
        stuck = len(t2_no_trail_engine)
        pct = stuck / hit_t2 * 100
        print(f"  >>> hit T2 but % -trail engine NEVER ran: {stuck}/{hit_t2} "
              f"({pct:.0f}%)  <<<")
        print("      (these ratcheted only via 60s resnap / breakeven — M1 confirmed "
              "if this is high)")
        print("  examples (symbol, final_mode, close_reason, trail_engine?):")
        for ex in t2_examples:
            print(f"      {ex}")
    else:
        print("  (no trades reached Target-2 yet — re-run after a session with T2 hits)")

    # ── M2 — local-only trail exposure sizing ─────────────────────────────
    trailed_locally = 0          # stop moved past original via local engine/resnap
    breakeven_only = 0
    trail_move_total = 0
    for t in trades:
        reasons = _reasons(t)
        if not reasons:
            continue
        had_trail = any(any(p in r for p in TRAIL_ENGINE_REASONS + RESNAP_REASONS)
                        for r in reasons)
        had_be = any(any(p in r for p in BREAKEVEN_REASONS) for r in reasons)
        if had_trail:
            trailed_locally += 1
            trail_move_total += sum(
                1 for r in reasons
                if any(p in r for p in TRAIL_ENGINE_REASONS + RESNAP_REASONS))
        elif had_be:
            breakeven_only += 1

    print("\n── M2: local-only stop-ratchet exposure (sizing) ──")
    print(f"  trades with a LOCAL trail/resnap ratchet: {trailed_locally}")
    print(f"  total local trail/resnap moves recorded:  {trail_move_total}")
    print(f"  trades that moved to breakeven only:      {breakeven_only}")
    print("  NOTE: every local ratchet above was an in-memory stop TIGHTER than the")
    print("        resting IB bracket stop (the trailing path never reissues/modifies")
    print("        the IB order) — that's the M2 server-side exposure window. If the")
    print("        manage loop/quote feed stalls, IB protects only at the ORIGINAL")
    print("        (or last scale-out) stop, not these trailed levels.")

    print("\n" + "=" * 72)
    print("DONE — read-only. No documents were modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
