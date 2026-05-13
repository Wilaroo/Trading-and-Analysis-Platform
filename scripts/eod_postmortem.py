#!/usr/bin/env python3
"""eod_postmortem.py — pull today's EOD close postmortem from Mongo + IB.

Designed to be run AFTER market close on a day where EOD didn't behave.
Surfaces, in one report:

  1. Today's `bot_events.eod_auto_close` row (closed_count, failed_symbols,
     total_pnl, close_time_et) — what the bot THINKS happened.
  2. All `trade_drops` recorded today with `phase=close` — the specific
     IB-side rejections during the EOD window.
  3. Live IB open orders snapshot — anything still pending POST-market
     close is suspicious (intraday LMTs that should have been cancelled,
     orphan brackets, etc.).
  4. Live IB positions — anything `position != 0` after 4:05 PM ET on a
     full trading day is an overnight-exposure event.
  5. Today's WS broadcasts of type `eod_close_started`/`eod_close_completed`
     / `eod_flatten_failed` / `eod_orphan_sweep` if persisted.

Usage:
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/eod_postmortem.py
    python3 scripts/eod_postmortem.py --json     # raw payload
    python3 scripts/eod_postmortem.py --date 2026-05-13
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _backend() -> str:
    return os.environ.get(
        "REACT_APP_BACKEND_URL", "http://localhost:8001"
    ).rstrip("/")


def _fetch(path: str, timeout: float = 20.0):
    url = f"{_backend()}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e), "_path": path}


def _section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true",
                        help="Dump raw aggregated JSON.")
    parser.add_argument("--date", default=None,
                        help="ISO date (default = today, ET)")
    args = parser.parse_args()

    payload = _fetch(
        f"/api/diagnostic/eod-postmortem"
        + (f"?date={args.date}" if args.date else "")
    )

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if payload.get("_error"):
        print(f"❌ endpoint failed: {payload['_error']} ({payload.get('_path')})")
        return 2

    _section("EOD Postmortem")
    print(f"  date (ET)          : {payload.get('date_et')}")
    print(f"  generated_at       : {payload.get('generated_at')}")
    print(f"  market_state       : {payload.get('market_state')}")

    eod = payload.get("eod_auto_close_event") or {}
    _section("1. bot_events.eod_auto_close")
    if not eod:
        print("  ⚠ NO eod_auto_close event recorded today — "
              "EOD loop never executed OR positions filter was empty.")
    else:
        print(f"  close_time_et      : {eod.get('close_time_et')}")
        print(f"  positions_closed   : {eod.get('positions_closed')}")
        print(f"  positions_failed   : {eod.get('positions_failed')}")
        print(f"  failed_symbols     : {eod.get('failed_symbols')}")
        print(f"  total_pnl          : ${eod.get('total_pnl', 0):+,.2f}")
        print(f"  is_half_day        : {eod.get('is_half_day')}")

    drops = payload.get("close_phase_drops") or []
    _section(f"2. trade_drops phase=close ({len(drops)} during EOD window)")
    if not drops:
        print("  ✅ no close-phase drops recorded today.")
    else:
        for d in drops[:25]:
            print(
                f"  • {d.get('symbol'):<6} {d.get('gate'):<25} "
                f"reason={d.get('reason'):<18} "
                f"err={(d.get('error') or '')[:70]}"
            )
        if len(drops) > 25:
            print(f"  … and {len(drops) - 25} more.")

    open_orders = payload.get("ib_open_orders_post_close") or []
    _section(f"3. IB open orders STILL ALIVE post-close ({len(open_orders)})")
    if not open_orders:
        print("  ✅ no live IB orders. Clean EOD.")
    else:
        print("  ⚠ ORDERS STILL OPEN AT IB — review individually:")
        for o in open_orders[:50]:
            print(
                f"  • {o.get('symbol'):<6} {o.get('action'):<4} "
                f"{o.get('quantity'):<6} {o.get('order_type'):<6} "
                f"lmt={o.get('limit_price')} stp={o.get('stop_price')} "
                f"tif={o.get('time_in_force')} status={o.get('status')} "
                f"ib_id={o.get('ib_order_id')} verdict={o.get('verdict')}"
            )

    positions = payload.get("ib_open_positions_post_close") or []
    _section(f"4. IB open positions post-close ({len(positions)})")
    overnight = [p for p in positions if abs(p.get("position", 0)) > 0]
    if not overnight:
        print("  ✅ no overnight exposure.")
    else:
        intraday_overnight = [p for p in overnight if p.get("close_at_eod")]
        if intraday_overnight:
            print("  🔴 INTRADAY positions held overnight (BUG):")
            for p in intraday_overnight:
                print(
                    f"     • {p.get('symbol'):<6} qty={p.get('position'):<6} "
                    f"avg_cost={p.get('avg_cost')} unrPNL={p.get('unrealized_pnl')}"
                )
        swing = [p for p in overnight if not p.get("close_at_eod")]
        if swing:
            print(f"  ✅ {len(swing)} swing/position trades held overnight (intentional):")
            for p in swing[:10]:
                print(
                    f"     • {p.get('symbol'):<6} qty={p.get('position'):<6} "
                    f"trade_type={p.get('trade_type')}"
                )

    sweep = payload.get("eod_orphan_sweep_event") or {}
    _section("5. v19.34.90 EOD orphan sweep (post-close cleanup)")
    if not sweep:
        print("  ⚠ NO orphan sweep ran today.")
        print("    Cause: sweep is gated by `closed_count > 0` — if zero")
        print("    positions closed, the sweep doesn't fire (PRE-FIX BUG).")
    else:
        print(f"  queued_cancellations : {sweep.get('queued')}")
        print(f"  errors               : {sweep.get('errors')}")
        for d in (sweep.get("details") or [])[:25]:
            print(
                f"  • {d.get('symbol'):<6} order_id={d.get('ib_order_id')} "
                f"verdict={d.get('verdict')} status={d.get('status')}"
            )

    _section("DIAGNOSIS")
    for line in payload.get("diagnosis") or []:
        print(f"  {line}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
