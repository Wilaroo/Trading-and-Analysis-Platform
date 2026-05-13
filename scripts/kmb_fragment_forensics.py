#!/usr/bin/env python3
"""kmb_fragment_forensics.py — KMB (or any symbol) phantom-share root cause
============================================================================

v19.34.142e exposes `ledger_fragments[]` on every magnitude-mismatch
row from `/api/diagnostic/position-pnl-audit`. This helper hits the
endpoint, isolates the offending symbol(s), and pretty-prints the
fragments so you can identify WHICH slice(s) over-booked.

Run on the DGX (where the IB pusher is actually feeding data):

    cd ~/Trading-and-Analysis-Platform
    python3 scripts/kmb_fragment_forensics.py
    python3 scripts/kmb_fragment_forensics.py --symbol KMB
    python3 scripts/kmb_fragment_forensics.py --json   # raw JSON dump

Output columns per fragment:
  trade_id           — bot_trades.id (use to grep logs/db)
  shares             — original trade.shares
  remaining          — trade.remaining_shares (live)
  setup_type         — momentum_breakout / reconciled_excess_slice / …
  entered_by         — bot_fired / reconciled_excess_v19_34_15b / …
  stop_order_id      — None / SIM-STP-* / real IB order id
  entry_time         — when this fragment was opened

If you see a `reconciled_excess_slice` fragment whose shares + the
original bot-fired fragment SUM to more than IB qty, that's the
double-book the v19.34.144 clamp now prevents. The remediation
recommended by the diagnostic action is:

    POST /api/trading-bot/reconcile-share-drift
    body: {"symbols": ["KMB"], "auto_resolve": true}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _backend_url() -> str:
    # Honor REACT_APP_BACKEND_URL when set, fall back to localhost:8001
    # since this script runs on the DGX itself.
    url = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
    return url.rstrip("/")


def _hit_audit() -> dict:
    url = f"{_backend_url()}/api/diagnostic/position-pnl-audit"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_fragment(f: dict) -> str:
    return (
        f"  {f.get('trade_id', '?'):<12} "
        f"shares={f.get('shares', '?'):<6} "
        f"remaining={f.get('remaining_shares', '?'):<6} "
        f"setup={(f.get('setup_type') or '-'):<28} "
        f"entered_by={(f.get('entered_by') or '-'):<32} "
        f"stop_id={(f.get('stop_order_id') or '-'):<20} "
        f"entry_time={f.get('entry_time') or '-'}"
    )


def _print_row(row: dict) -> None:
    sym = row.get("symbol", "?")
    print(f"\n=== {sym} ===")
    print(
        f"  ib_qty      = {row.get('ib_qty')}\n"
        f"  bot_qty     = {row.get('bot_qty')}\n"
        f"  qty_delta   = {row.get('qty_delta')} share(s) "
        f"({'OVER-booked' if row.get('bot_qty', 0) and abs(row.get('bot_qty', 0)) > abs(row.get('ib_qty', 0) or 0) else 'UNDER-booked'})\n"
        f"  verdict     = {row.get('verdict')}\n"
        f"  pnl_source  = {row.get('pnl_source')}\n"
        f"  fragments   = {row.get('ledger_fragment_count', 0)}"
    )
    fragments = row.get("ledger_fragments") or []
    if not fragments:
        print("  (no fragments returned — endpoint may be older than v19.34.142e)")
        return
    print("\n  Fragments:")
    for f in fragments:
        if "error" in f:
            print(f"    (walk error: {f['error']})")
            continue
        print(_fmt_fragment(f))
    # Quick heuristic: identify the most likely double-book pair.
    by_setup = {}
    for f in fragments:
        if "error" in f:
            continue
        by_setup.setdefault(f.get("setup_type") or "-", []).append(f)
    if any(
        s in by_setup
        for s in ("reconciled_excess_slice", "reconciled_orphan")
    ) and any(
        s in by_setup
        for s in ("momentum_breakout", "bot_originated", "vwap_pullback")
    ):
        print(
            "\n  ⚠ Likely root cause: a `reconciled_excess_slice` "
            "fragment was spawned ALONGSIDE the original bot-fired "
            "fragment, double-booking the same IB position. The "
            "v19.34.144 clamp now prevents this from leaking into a "
            "mis-sized consolidator bracket; v19.34.15b auto-resolves "
            "the underlying ledger drift on the next share-drift loop "
            "tick (or run reconcile-share-drift manually)."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--symbol", "-s",
        action="append",
        help="Filter to specific symbol(s). May be repeated. "
             "Default: all magnitude-mismatch rows.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON instead of pretty output.",
    )
    parser.add_argument(
        "--include-ok",
        action="store_true",
        help="Also dump OK / DRIFT_* rows for the requested symbol(s).",
    )
    args = parser.parse_args()

    try:
        audit = _hit_audit()
    except Exception as e:
        print(f"ERROR: failed to reach audit endpoint: {e}", file=sys.stderr)
        return 2

    rows = audit.get("rows") or []
    summary = audit.get("summary") or {}
    actions = audit.get("actions") or []

    target_syms = (
        {s.upper() for s in (args.symbol or [])} if args.symbol else None
    )

    if args.include_ok and target_syms:
        rows_to_show = [r for r in rows if r.get("symbol", "").upper() in target_syms]
    elif target_syms:
        rows_to_show = [
            r for r in rows
            if r.get("symbol", "").upper() in target_syms
            and r.get("verdict") in (
                "QTY_MAGNITUDE_MISMATCH", "QTY_SIGN_MISMATCH",
                "DRIFT_ABS", "DRIFT_PCT", "PHANTOM_IN_BOT",
            )
        ]
    else:
        rows_to_show = [
            r for r in rows
            if r.get("verdict") in (
                "QTY_MAGNITUDE_MISMATCH", "QTY_SIGN_MISMATCH",
            )
        ]

    if args.json:
        print(json.dumps({
            "summary": summary,
            "actions": actions,
            "rows": rows_to_show,
        }, indent=2, default=str))
        return 0

    print(f"audit generated_at  : {audit.get('generated_at')}")
    print(f"ib_position_count   : {audit.get('ib_position_count')}")
    print(f"bot_position_count  : {audit.get('bot_position_count')}")
    print(f"summary             : {summary}")
    print(f"actions             :")
    for a in actions:
        print(f"  - {a}")

    if not rows_to_show:
        print("\nNo magnitude/sign mismatches found in this audit run. ✅")
        return 0

    print(f"\n{len(rows_to_show)} row(s) with drift:")
    for row in rows_to_show:
        _print_row(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
