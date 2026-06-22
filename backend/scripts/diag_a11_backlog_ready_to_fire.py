#!/usr/bin/env python3
"""
diag_a11_backlog_ready_to_fire.py  —  2026-06-22  (SentCom / DGX Spark)  READ-ONLY

"Do we need to clear the slate?" — snapshots every LIVE scanner alert that is
auto_execute_eligible RIGHT NOW and shows, per alert, what the A10 trigger-drift
gate would decide at fire-time (WOULD-FIRE vs WOULD-BLOCK), how old it is, and
how concentrated the eligible backlog is by setup_type / symbol. Cross-refs open
positions so you can see which eligible alerts would try to stack on a held name.

Reads the LIVE running backend (in-memory _live_alerts is the source of truth):
  GET /api/live-scanner/alerts
  GET /api/live-scanner/auto-execute/status
  GET /api/live-scanner/status
  GET /api/trading-bot/trades/open
Nothing is written or dismissed. Drift uses each alert's last-known current_price
as a proxy for the live quote the gate re-fetches (close, not byte-identical).

Run on the DGX (backend must be up):
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py --eligible-only --threshold 2.0
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py --emit-dismiss   # prints (does NOT run) dismiss curls
"""
import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

BASE = os.environ.get("DIAG_BASE_URL", "http://localhost:8001")


def _get(path):
    url = BASE.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! GET {path} failed: {e}")
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _age_hours(created_at):
    if not created_at:
        return None
    try:
        s = str(created_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _age_bucket(h):
    if h is None:
        return "no-ts"
    if h < 0.25:
        return "<15m"
    if h < 1:
        return "15-60m"
    if h < 4:
        return "1-4h"
    return ">4h"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT", "2.0")),
                    help="A10 max trigger-drift %% (default = env or 2.0)")
    ap.add_argument("--eligible-only", action="store_true",
                    help="only print the auto_execute_eligible rows")
    ap.add_argument("--emit-dismiss", action="store_true",
                    help="print ready-to-paste dismiss curls for eligible alerts (does NOT run them)")
    args = ap.parse_args()
    thr = args.threshold

    print(f"=== A11 backlog / ready-to-fire snapshot @ {datetime.now(timezone.utc).isoformat()} ===")
    print(f"    base={BASE}  A10 drift threshold={thr:.2f}%\n")

    ax = _get("/api/live-scanner/auto-execute/status") or {}
    st = _get("/api/live-scanner/status") or {}
    print(f"AUTO-EXECUTE: enabled={ax.get('enabled')}  min_priority={ax.get('min_priority')}  "
          f"bot_connected={ax.get('trading_bot_connected')}")
    print(f"SCANNER:      running={st.get('running', st.get('scanner_running'))}  "
          f"scan_count={st.get('scan_count')}\n")

    payload = _get("/api/live-scanner/alerts")
    if not payload:
        print("ABORT — could not read /api/live-scanner/alerts (is the backend up?)")
        sys.exit(1)
    alerts = payload.get("alerts", []) if isinstance(payload, dict) else (payload or [])
    print(f"Total live alerts in scanner: {len(alerts)}")

    # Open positions (held symbols) — tolerate list-or-dict shapes.
    held = set()
    op = _get("/api/trading-bot/trades/open")
    if op is not None:
        items = op if isinstance(op, list) else next(
            (v for v in op.values() if isinstance(v, list)), [])
        for p in items:
            s = (p.get("symbol") or "").upper()
            if s:
                held.add(s)
    print(f"Open positions (held symbols): {len(held)}\n")

    rows = []
    for a in alerts:
        status = (a.get("status") or "active")
        elig = bool(a.get("auto_execute_eligible"))
        sym = (a.get("symbol") or "").upper()
        setup = a.get("setup_type") or "?"
        prio = a.get("priority")
        prio = prio.get("value") if isinstance(prio, dict) else prio
        trig = _f(a.get("trigger_price"))
        cur = _f(a.get("current_price"))
        h = _age_hours(a.get("created_at"))
        if trig > 0 and cur > 0:
            drift = abs(cur - trig) / trig * 100.0
            verdict = "WOULD-FIRE" if drift <= thr else "WOULD-BLOCK(A10)"
        else:
            drift = None
            verdict = "NO-PRICE"
        rows.append({
            "id": a.get("id") or a.get("alert_id"), "sym": sym, "setup": setup,
            "prio": prio, "dir": a.get("direction"), "trig": trig, "cur": cur,
            "drift": drift, "verdict": verdict, "age_h": h, "bucket": _age_bucket(h),
            "elig": elig, "status": status, "held": sym in held,
        })

    elig_rows = [r for r in rows if r["elig"] and r["status"] != "dismissed"]
    fire_rows = [r for r in elig_rows if r["verdict"] == "WOULD-FIRE"]
    block_rows = [r for r in elig_rows if r["verdict"] == "WOULD-BLOCK(A10)"]
    noprice_rows = [r for r in elig_rows if r["verdict"] == "NO-PRICE"]

    show = elig_rows if args.eligible_only else rows
    show = sorted(show, key=lambda r: (r["verdict"] != "WOULD-FIRE", -(r["drift"] or -1)))

    print(f"{'SYMBOL':<7}{'SETUP':<22}{'PRIO':<9}{'DIR':<6}{'TRIG':>9}{'LIVE':>9}"
          f"{'DRIFT%':>8}  {'AGE':>7}  {'VERDICT':<17}{'ELIG':<5}{'HELD'}")
    print("-" * 108)
    for r in show:
        d = f"{r['drift']:.2f}" if r["drift"] is not None else "  -  "
        ah = f"{r['age_h']:.1f}h" if r["age_h"] is not None else "  -  "
        print(f"{r['sym']:<7}{r['setup'][:21]:<22}{str(r['prio'])[:8]:<9}{str(r['dir'] or '')[:5]:<6}"
              f"{r['trig']:>9.2f}{r['cur']:>9.2f}{d:>8}  {ah:>7}  {r['verdict']:<17}"
              f"{'Y' if r['elig'] else '-':<5}{'HELD' if r['held'] else ''}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  eligible (ready-to-fire queue):        {len(elig_rows)}")
    print(f"    → WOULD-FIRE now (drift <= {thr:.1f}%):   {len(fire_rows)}")
    print(f"    → WOULD-BLOCK by A10 (drift > {thr:.1f}%): {len(block_rows)}")
    print(f"    → NO-PRICE (fail-open, would fire):    {len(noprice_rows)}")
    print(f"  eligible on ALREADY-HELD symbols:      {sum(1 for r in elig_rows if r['held'])}")

    if elig_rows:
        print("\n  eligible by setup_type:")
        for k, v in Counter(r["setup"] for r in elig_rows).most_common():
            print(f"     {v:>3}  {k}")
        print("  eligible by age bucket:")
        for k in ("<15m", "15-60m", "1-4h", ">4h", "no-ts"):
            c = sum(1 for r in elig_rows if r["bucket"] == k)
            if c:
                print(f"     {c:>3}  {k}")
        top_setup, top_n = Counter(r["setup"] for r in elig_rows).most_common(1)[0]
        conc = top_n / max(1, len(elig_rows))
        print(f"\n  concentration: top setup '{top_setup}' = {top_n}/{len(elig_rows)} ({conc*100:.0f}%)")

    # ---- recommendation ----
    print("\n" + "=" * 60)
    print("READ")
    print("=" * 60)
    would_fire_now = len(fire_rows) + len(noprice_rows)
    if not elig_rows:
        print("  ✅ No auto_execute_eligible alerts queued — nothing ready to fire. No action needed.")
    else:
        print(f"  • {would_fire_now} alert(s) would FIRE on the next auto-exec pass (A10 lets them through;")
        print(f"    they are within {thr:.1f}% of their trigger = actionable, not stale chases).")
        print(f"  • {len(block_rows)} extended alert(s) are now NEUTRALIZED by the A10 gate at fire-time.")
        if sum(1 for r in elig_rows if r["held"]) > 0:
            print(f"  • {sum(1 for r in elig_rows if r['held'])} eligible alert(s) are on ALREADY-HELD symbols "
                  f"(dedup/position checks should block stacking — verify if any slip through).")
        if elig_rows and (Counter(r['setup'] for r in elig_rows).most_common(1)[0][1] / len(elig_rows)) >= 0.5:
            print("  ⚠ HIGH single-setup concentration — a clean open could stack many similar holds")
            print("    (Issue 3 per-style cap is not yet built). Consider pausing auto-exec until it is,")
            print("    or clearing the slate before next RTH.")
    print("\n  CLEAR-THE-SLATE OPTIONS (operator choice — none run by this read-only diag):")
    print("    1) HARD PAUSE (durable, cleanest): stop ALL auto-fires until you re-arm —")
    print("         curl -sS -X POST '" + BASE + "/api/live-scanner/auto-execute/enable?enabled=false'")
    print("       re-arm later with enabled=true.")
    print("    2) Per-alert dismiss (UI/queue tidy; NOTE: daily setups RE-DETECT next scan cycle,")
    print("       so dismiss is NOT durable for them — use option 1 to truly hold):")
    if args.emit_dismiss:
        for r in elig_rows:
            if r["id"]:
                print(f"         curl -sS -X POST '{BASE}/api/live-scanner/alerts/{r['id']}/dismiss'")
    else:
        print("         re-run with --emit-dismiss to print the per-alert curls.")
    print("    3) Do nothing: A10 + dedup + confidence-gate + max_open_positions already govern fires;")
    print("       the would-fire set above is near-trigger and within risk caps.")


if __name__ == "__main__":
    main()
