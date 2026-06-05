#!/usr/bin/env python3
"""
probe_symbol_day.py — one-shot per-symbol scan forensics (v19.34.281).

Answers "did our bot see / scan / skip SYMBOL today, and why didn't it
trade it" in a single command by reading the live scanner's
`/api/scanner/symbol-trace` endpoint (in-memory scanner state joined with
today's mongo alert/trade counts) and printing a verdict chain.

Usage (on the DGX, backend running):
    .venv/bin/python backend/scripts/probe_symbol_day.py TSLA
    .venv/bin/python backend/scripts/probe_symbol_day.py NVDA --base http://localhost:8001

Read-only. Touches no order logic and no open positions.
"""
import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="ticker, e.g. TSLA")
    ap.add_argument("--base", default="http://localhost:8001",
                    help="backend base URL (default http://localhost:8001)")
    args = ap.parse_args()

    sym = args.symbol.upper()
    url = f"{args.base}/api/scanner/symbol-trace?symbol={sym}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[ERROR] GET {url} failed: {e}")
        sys.exit(1)

    if not data.get("running", False):
        print(f"\n{sym}: scanner not running / not initialized — "
              f"{data.get('message', 'no detail')}\n")
        return

    rv = data.get("rvol", {}) or {}
    le = data.get("last_eval")
    tc = data.get("today_counts", {}) or {}

    print(f"\n=== symbol-trace: {sym} ===")
    print(f"VERDICT : {data.get('verdict')}")
    print("-" * 60)
    print(f"universe: in_universe={data.get('in_universe')}  "
          f"tier={data.get('tier')}  in_last_wave={data.get('in_last_wave')}")
    print(f"rvol    : value={rv.get('value')}  age={rv.get('age_seconds')}s  "
          f"fresh={rv.get('fresh')}  floor={rv.get('min_filter')}")
    if le:
        extra = {k: v for k, v in le.items() if k not in ("symbol", "stage", "ts")}
        print(f"last_eval: stage={le.get('stage')}  at={le.get('ts')}  {extra}")
    else:
        print("last_eval: <none> — symbol never entered _scan_symbol_all_setups this session")
    print(f"today   : live_alerts={tc.get('live_alerts', 0)}  "
          f"alerts={tc.get('alerts', 0)}  shadow={tc.get('shadow_decisions', 0)}  "
          f"rejections={tc.get('rejection_events', 0)}  bot_trades={tc.get('bot_trades', 0)}")
    # v19.34.286 — alert→trade gate funnel (which gate ate the alerts, by how much)
    gf = data.get("gate_funnel", {}) or {}
    bg = gf.get("by_gate", {}) or {}
    fk = f"  first_killing={gf.get('first_killing_gate')}" if gf.get("first_killing_gate") else ""
    print(f"gates   : {gf.get('total', 0)} trade_drop(s) today{fk}")
    for g, e in sorted(bg.items(), key=lambda kv: kv[1].get("count", 0), reverse=True):
        margin = f"  [{e.get('margin')}]" if e.get("margin") else ""
        setups = ",".join((e.get("setups") or [])[:3])
        print(f"   - {g} ×{e.get('count')}{margin}"
              + (f"  setups={setups}" if setups else ""))
        if e.get("last_reason"):
            print(f"       last: {e.get('last_reason')}")
    # v19.34.288 — intake-eligibility backfill (the "PRE-eval blind spot" answer):
    # recomputes auto-exec eligibility from today's persisted live_alerts when no
    # trade_drop was logged, so we see WHY surfaced alerts never auto-traded.
    ie = data.get("intake_eligibility", {}) or {}
    if ie.get("checked"):
        ae = ie.get("auto_exec_enabled")
        print(f"intake  : checked={ie.get('checked')}  auto_exec_enabled={ae}  "
              f"min_ev_r={ie.get('min_ev_r')}  eligible_no_drop={ie.get('eligible_no_drop', 0)}")
        for reason, e in sorted((ie.get("by_reason") or {}).items(),
                                key=lambda kv: kv[1].get("count", 0), reverse=True):
            setups = ",".join((e.get("setups") or [])[:3])
            print(f"   - {reason} ×{e.get('count')}"
                  + (f"  setups={setups}" if setups else ""))
    print()


if __name__ == "__main__":
    main()
