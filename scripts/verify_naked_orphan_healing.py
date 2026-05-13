#!/usr/bin/env python3
"""verify_naked_orphan_healing.py — confirm reconciled orphans get
brackets within the v19.34.143 sweep cycle.

Runs on the DGX. Polls `_open_trades` (via the diagnostic endpoint
and `/api/trading-bot/bracket-status`) every 30s and prints a
table of monitored symbols + their stop_order_id status:

  PASS  if stop_order_id is set, doesn't start with SIM-/ADOPT-,
        and is matched in the live IB order book
  HEAL  if a prior poll showed NAKED and this poll shows REAL
        (the v19.34.143 sweep just fired its emergency attach)
  WAIT  if still NAKED (sweep hasn't reached this trade yet)
  GONE  if the trade has dropped out of `_open_trades` (closed/zombified)

Default monitored: TE, EGO, KTOS (the names called out in the
v19.34.142 handoff). Pass `--symbols T,E,...` to customize.

Usage:
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/verify_naked_orphan_healing.py
    python3 scripts/verify_naked_orphan_healing.py --symbols TE,EGO,KTOS
    python3 scripts/verify_naked_orphan_healing.py --max-minutes 5

Naked-sweep cadence is ~60s (see trading_bot_service kill-switch
monitor). Expect a PASS within 1-2 polls (≤2 minutes) on a healthy
pusher; longer means the pusher's openTrades snapshot isn't reaching
the executor — investigate `is_pusher_connected()` and `_fetch_ib_open_orders`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone


def _backend() -> str:
    return os.environ.get(
        "REACT_APP_BACKEND_URL", "http://localhost:8001"
    ).rstrip("/")


def _GET(path: str) -> dict:
    url = f"{_backend()}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_simulated(stop_id) -> bool:
    if stop_id is None:
        return False
    s = str(stop_id)
    return s.startswith("SIM-") or s.startswith("ADOPT-STOP-")


def _fetch_state(symbols: set) -> dict:
    """Pull current bracket state for the requested symbols via the
    dedicated `/api/diagnostic/bracket-status` endpoint (v19.34.143)."""
    try:
        params = ",".join(sorted(symbols))
        data = _GET(f"/api/diagnostic/bracket-status?symbols={params}")
    except Exception as e:
        return {"_error": f"bracket_status_fetch_failed:{e}"}
    if not data.get("success"):
        return {"_error": data.get("error", "unknown_error")}

    out: dict = {sym: {"fragments": []} for sym in symbols}
    out["_live_order_id_count"] = data.get("live_order_id_count", 0)
    out["_open_orders_source"] = data.get("open_orders_source")
    for row in data.get("rows", []):
        sym = row.get("symbol", "").upper()
        if sym not in symbols:
            continue
        out[sym]["fragments"].append({
            "trade_id": row.get("trade_id"),
            "shares": row.get("shares"),
            "remaining_shares": row.get("remaining_shares"),
            "setup_type": row.get("setup_type"),
            "entered_by": row.get("entered_by"),
            "stop_order_id": row.get("stop_order_id"),
            "status": row.get("status"),
            "_unknown_stop_id": False,
        })
    # Mark symbols with no fragments as GONE.
    for sym in symbols:
        if not out[sym]["fragments"]:
            out[sym] = {"gone": True}
    return out


def _print_table(*, state: dict, prev_state: dict, poll_n: int) -> dict:
    """Print one poll's table. Return updated prev_state."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"\n[poll {poll_n}] {now}")
    if state.get("_error"):
        print(f"  ERROR: {state['_error']}")
        return prev_state

    new_prev = dict(prev_state)
    for sym, info in state.items():
        if sym.startswith("_"):
            continue
        if info.get("gone"):
            print(f"  {sym:<6} GONE  (no longer in _open_trades / audit)")
            new_prev[sym] = "GONE"
            continue
        for frag in info["fragments"]:
            tid = frag.get("trade_id") or "?"
            status = frag.get("status")
            stop_id = frag.get("stop_order_id") or "—"
            rs = frag.get("remaining_shares")
            etype = frag.get("entered_by") or "-"
            key = f"{sym}:{tid}"
            prior = prev_state.get(key)
            tag = status
            if prior and prior.startswith("NAKED") and status == "BRACKETED":
                tag = f"HEAL → {status}"
            elif status == "BRACKETED":
                tag = "PASS"
            elif status.startswith("NAKED"):
                tag = f"WAIT ({status})"
            unknown = " [stop_id unknown — magnitude row only]" if frag.get("_unknown_stop_id") else ""
            print(
                f"  {sym:<6} tid={tid:<10} rs={rs:<5} "
                f"stop_id={stop_id:<22} entered_by={etype:<32} "
                f"→ {tag}{unknown}"
            )
            new_prev[key] = status
    return new_prev


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        default="TE,EGO,KTOS",
        help="Comma-separated symbols to monitor (default: TE,EGO,KTOS).",
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Seconds between polls (default: 30).",
    )
    parser.add_argument(
        "--max-minutes", type=int, default=10,
        help="Stop after this many minutes (default: 10).",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Single snapshot, exit.",
    )
    args = parser.parse_args()

    symbols = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
    if not symbols:
        print("No symbols supplied.", file=sys.stderr)
        return 2

    print(f"Monitoring {sorted(symbols)} every {args.interval}s "
          f"(max {args.max_minutes} min).")
    print("Naked-sweep fires every ~60s; expect PASS / HEAL within 1-2 polls.")

    start = time.time()
    prev: dict = {}
    poll_n = 0
    while True:
        poll_n += 1
        state = _fetch_state(symbols)
        prev = _print_table(state=state, prev_state=prev, poll_n=poll_n)
        # Three-way outcome:
        #   • all GONE   → trades closed or never tracked; can't verify
        #   • all PASS   → healing confirmed
        #   • else WAIT  → keep polling
        alive_fragments = [
            f
            for sym, info in state.items()
            if isinstance(info, dict) and not info.get("gone") and not sym.startswith("_")
            for f in info.get("fragments", [])
            if not f.get("_unknown_stop_id")
        ]
        all_gone = (
            bool(state)
            and all(
                isinstance(info, dict) and info.get("gone")
                for sym, info in state.items()
                if not sym.startswith("_")
            )
        )
        if all_gone:
            print(
                "\n⚠ All monitored symbols are GONE from _open_trades. "
                "Nothing to verify — either the trades were closed, "
                "they never landed in the bot ledger, or no open "
                "fragments currently exist for them in `_open_trades`."
            )
            return 0
        all_passed = bool(alive_fragments) and all(
            f["status"] == "BRACKETED" for f in alive_fragments
        )
        if all_passed:
            print("\n✅ All monitored fragments BRACKETED. Healing verified.")
            return 0
        if args.once:
            return 0
        if (time.time() - start) > args.max_minutes * 60:
            print(f"\n⏰ Hit {args.max_minutes}-minute cap without full PASS.")
            print("Check `/var/log/.../trading_bot_service.log` for "
                  "`[v127 naked-sweep]` lines to see if the sweep is "
                  "running and whether attach_oca_stop_target is "
                  "succeeding.")
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
