#!/usr/bin/env python3
"""
diag_a11_backlog_ready_to_fire.py  —  2026-06-22 (v2)  (SentCom / DGX Spark)  READ-ONLY

"Do we need to clear the slate?" — snapshots every LIVE scanner alert that is
auto_execute_eligible RIGHT NOW and shows, per DISTINCT (symbol, setup, dir),
what the A10 trigger-drift gate would decide at fire-time (WOULD-FIRE vs
WOULD-BLOCK), how old it is, and how concentrated the eligible backlog is.

v2 changes (operator ask A):
  • Real LIVE quotes from Mongo `ib_live_snapshot.current.quotes` (the price the
    A10 gate actually re-fetches), with a `SRC` column: live | proxy | frozen.
    Falls back to the alert's last current_price when no live quote exists.
  • Collapses duplicate alert objects by (symbol, setup_type, direction), keeping
    the NEWEST — so the carry-forward re-emit dupes don't drown the table.
  • Concentration warning only trips when ≥3 distinct alerts are eligible.

Reads the LIVE running backend (in-memory _live_alerts is the source of truth):
  GET /api/live-scanner/alerts · /auto-execute/status · /status
  GET /api/trading-bot/trades/open
Plus Mongo `ib_live_snapshot` (read-only). Nothing is written or dismissed.

Run on the DGX (backend up):
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py --eligible-only
    .venv/bin/python scripts/diag_a11_backlog_ready_to_fire.py --emit-dismiss
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


def _env(key):
    for cand in ("backend/.env", os.path.join(os.path.dirname(__file__), "..", ".env"), ".env"):
        try:
            for line in open(cand, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and line.split("=", 1)[0].strip() == key:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return os.environ.get(key)


def _live_quotes():
    """{SYMBOL: price} from Mongo ib_live_snapshot.current.quotes. {} on any failure."""
    try:
        from pymongo import MongoClient
        url, dbn = _env("MONGO_URL"), _env("DB_NAME")
        if not url or not dbn:
            return {}, "no MONGO_URL/DB_NAME"
        cli = MongoClient(url, serverSelectionTimeoutMS=4000)
        snap = cli[dbn]["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0, "quotes": 1, "last_update": 1})
        cli.close()
        if not snap:
            return {}, "no snapshot doc"
        out = {}
        for sym, q in (snap.get("quotes") or {}).items():
            if not isinstance(q, dict):
                continue
            p = q.get("last") or q.get("close") or q.get("price") or 0
            if not p:
                b, a = q.get("bid") or 0, q.get("ask") or 0
                if b and a:
                    p = (b + a) / 2.0
            if p:
                out[sym.upper()] = float(p)
        return out, f"{len(out)} syms · upd {snap.get('last_update')}"
    except Exception as e:
        return {}, f"err: {e}"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _age_hours(created_at):
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _bucket(h):
    if h is None:
        return "no-ts"
    return "<15m" if h < 0.25 else "15-60m" if h < 1 else "1-4h" if h < 4 else ">4h"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT", "2.0")))
    ap.add_argument("--eligible-only", action="store_true")
    ap.add_argument("--emit-dismiss", action="store_true")
    args = ap.parse_args()
    thr = args.threshold

    print(f"=== A11 backlog / ready-to-fire snapshot @ {datetime.now(timezone.utc).isoformat()} ===")
    print(f"    base={BASE}  A10 drift threshold={thr:.2f}%")

    quotes, qsrc = _live_quotes()
    print(f"    live quotes (ib_live_snapshot): {qsrc}\n")

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

    held = set()
    op = _get("/api/trading-bot/trades/open")
    if op is not None:
        items = op if isinstance(op, list) else next((v for v in op.values() if isinstance(v, list)), [])
        for p in items:
            s = (p.get("symbol") or "").upper()
            if s:
                held.add(s)

    # ---- collapse dupes by (symbol, setup_type, direction), keep newest ----
    by_key = {}
    for a in alerts:
        sym = (a.get("symbol") or "").upper()
        setup = a.get("setup_type") or "?"
        direction = (a.get("direction") or "long")
        key = (sym, setup, direction)
        ca = a.get("created_at") or ""
        if key not in by_key or str(ca) > str(by_key[key].get("created_at") or ""):
            by_key[key] = a
    distinct = list(by_key.values())
    n_dupes = len(alerts) - len(distinct)
    print(f"Total live alerts: {len(alerts)}  →  distinct (symbol,setup,dir): {len(distinct)} "
          f"(collapsed {n_dupes} dupes)")
    print(f"Open positions (held symbols): {len(held)}\n")

    rows = []
    for a in distinct:
        status = a.get("status") or "active"
        elig = bool(a.get("auto_execute_eligible"))
        sym = (a.get("symbol") or "").upper()
        setup = a.get("setup_type") or "?"
        prio = a.get("priority")
        prio = prio.get("value") if isinstance(prio, dict) else prio
        trig = _f(a.get("trigger_price"))
        cur = _f(a.get("current_price"))
        live = quotes.get(sym, 0.0)
        if live > 0:
            px, src = live, "live"
        elif cur > 0 and trig > 0 and abs(cur - trig) < 1e-9:
            px, src = cur, "frozen"   # current==trigger → not a real live mark
        else:
            px, src = cur, "proxy"
        if trig > 0 and px > 0:
            drift = abs(px - trig) / trig * 100.0
            verdict = "WOULD-FIRE" if drift <= thr else "WOULD-BLOCK(A10)"
        else:
            drift, verdict = None, "NO-PRICE"
        h = _age_hours(a.get("created_at"))
        rows.append({"id": a.get("id") or a.get("alert_id"), "sym": sym, "setup": setup,
                     "prio": prio, "dir": a.get("direction"), "trig": trig, "px": px,
                     "src": src, "drift": drift, "verdict": verdict, "age_h": h,
                     "bucket": _bucket(h), "elig": elig, "status": status, "held": sym in held})

    elig_rows = [r for r in rows if r["elig"] and r["status"] != "dismissed"]
    fire_rows = [r for r in elig_rows if r["verdict"] == "WOULD-FIRE"]
    block_rows = [r for r in elig_rows if r["verdict"] == "WOULD-BLOCK(A10)"]
    noprice_rows = [r for r in elig_rows if r["verdict"] == "NO-PRICE"]

    show = elig_rows if args.eligible_only else rows
    show = sorted(show, key=lambda r: (not r["elig"], r["verdict"] != "WOULD-FIRE", -(r["drift"] or -1)))

    print(f"{'SYMBOL':<7}{'SETUP':<22}{'PRIO':<9}{'DIR':<6}{'TRIG':>9}{'PRICE':>9}{'SRC':>7}"
          f"{'DRIFT%':>8}  {'AGE':>7}  {'VERDICT':<17}{'ELIG':<5}{'HELD'}")
    print("-" * 116)
    for r in show:
        d = f"{r['drift']:.2f}" if r["drift"] is not None else "  -  "
        ah = f"{r['age_h']:.1f}h" if r["age_h"] is not None else "  -  "
        print(f"{r['sym']:<7}{r['setup'][:21]:<22}{str(r['prio'])[:8]:<9}{str(r['dir'] or '')[:5]:<6}"
              f"{r['trig']:>9.2f}{r['px']:>9.2f}{r['src']:>7}{d:>8}  {ah:>7}  {r['verdict']:<17}"
              f"{'Y' if r['elig'] else '-':<5}{'HELD' if r['held'] else ''}")

    print("\n" + "=" * 60 + "\nSUMMARY\n" + "=" * 60)
    print(f"  distinct alerts:                       {len(rows)}")
    print(f"  eligible (ready-to-fire queue):        {len(elig_rows)}")
    print(f"    → WOULD-FIRE now (drift <= {thr:.1f}%):   {len(fire_rows)}")
    print(f"    → WOULD-BLOCK by A10 (drift > {thr:.1f}%): {len(block_rows)}")
    print(f"    → NO-PRICE (fail-open, would fire):    {len(noprice_rows)}")
    print(f"  eligible on ALREADY-HELD symbols:      {sum(1 for r in elig_rows if r['held'])}")

    conc = 0.0
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
        conc = top_n / len(elig_rows)
        print(f"\n  concentration: top setup '{top_setup}' = {top_n}/{len(elig_rows)} ({conc*100:.0f}%)")

    print("\n" + "=" * 60 + "\nREAD\n" + "=" * 60)
    would_fire_now = len(fire_rows) + len(noprice_rows)
    if not elig_rows:
        print("  ✅ No auto_execute_eligible alerts queued — nothing ready to fire. No action needed.")
    else:
        print(f"  • {would_fire_now} alert(s) would FIRE on the next auto-exec pass (A10 lets them through;")
        print(f"    within {thr:.1f}% of trigger = actionable, not stale chases).")
        print(f"  • {len(block_rows)} extended alert(s) are NEUTRALIZED by the A10 gate at fire-time.")
        if sum(1 for r in elig_rows if r["held"]) > 0:
            print(f"  • {sum(1 for r in elig_rows if r['held'])} eligible alert(s) on ALREADY-HELD symbols "
                  f"(dedup/position checks should block stacking — verify).")
        if len(elig_rows) >= 3 and conc >= 0.5:
            print("  ⚠ HIGH single-setup concentration across the eligible set — a clean open could stack")
            print("    many similar holds (Issue 3 per-style cap not yet built). Consider pausing auto-exec.")
    print("\n  CLEAR-THE-SLATE OPTIONS (operator choice — none run by this read-only diag):")
    print("    1) HARD PAUSE (durable, cleanest): stop ALL auto-fires until you re-arm —")
    print("         curl -sS -X POST '" + BASE + "/api/live-scanner/auto-execute/enable?enabled=false'")
    print("       re-arm later with enabled=true.")
    print("    2) Per-alert dismiss (UI tidy; NOTE: daily setups RE-DETECT next scan cycle — not durable):")
    if args.emit_dismiss:
        for r in elig_rows:
            if r["id"]:
                print(f"         curl -sS -X POST '{BASE}/api/live-scanner/alerts/{r['id']}/dismiss'")
    else:
        print("         re-run with --emit-dismiss to print the per-alert curls.")
    print("    3) Do nothing: A10 + dedup + confidence-gate + max_open_positions already govern fires.")


if __name__ == "__main__":
    main()
