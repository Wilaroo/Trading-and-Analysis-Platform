#!/usr/bin/env python3
"""
diag_a8_position_freshness.py — READ-ONLY audit of the bot's OPEN positions.

Answers the operator question: "are these 25 stage_2_breakout positions stale
alerts that fired at old prices, or valid trades with sane parameters?"

For each open position it checks:
  * bracket sanity  — stop on the correct side of entry, target on the correct
    side, and the resulting reward:risk (R:R).
  * entry-vs-mark drift — how far the recorded entry sits from the current mark
    (a large ADVERSE drift right after entry is the classic stale-fill tell).
  * timing — when the position was opened (were they all opened in the tight
    window right after the scanner restart, before live quotes were flowing?).
  * setup/style/source distribution.

Then it cross-checks bot entry_price vs IB avg_cost via /positions/truth-diff,
which is the authoritative "did this fill at the recorded price?" signal.

GET-only. No writes. No DB connection. urllib stdlib only.

Run from the repo root (or anywhere):
    PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a8_position_freshness.py
"""
import json
import urllib.request
from datetime import datetime, timezone

BASE = "http://localhost:8001"
DRIFT_WARN = 1.5   # % adverse drift entry->mark that flags a position
RR_MIN = 1.0       # minimum acceptable reward:risk


def _get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}


def _f(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _num(d, *keys, default=0.0):
    v = _f(d, *keys, default=None)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main():
    now = datetime.now(timezone.utc)
    print(f"== A8 position-freshness · now={now.isoformat()} ==\n")

    data = _get("/api/trading-bot/trades/open")
    if data.get("_error"):
        print(f"ERROR calling /api/trading-bot/trades/open: {data['_error']}")
        return
    trades = data.get("trades") or data.get("open_trades") or []
    print(f"open positions reported: {data.get('count', len(trades))}\n")
    if not trades:
        print("No open positions.")
        return

    by_setup, by_style, by_source = {}, {}, {}
    flagged = []
    opened_times = []
    hdr = f"{'SYM':<6} {'SETUP':<20} {'STYLE':<10} {'SIDE':<5} {'ENTRY':>9} {'MARK':>9} {'DRIFT%':>7} {'STOP':>9} {'TGT':>9} {'R:R':>5} {'UPL':>9}  FLAGS"
    print(hdr)
    print("-" * len(hdr))

    for t in trades:
        sym = str(_f(t, "symbol", "ticker", default="?"))
        setup = str(_f(t, "setup_type", "setup", "strategy", "strategy_name", default="?"))
        style = str(_f(t, "trade_style", "style", default="?"))
        source = str(_f(t, "source", "entered_by", "origin", default="?"))
        side = str(_f(t, "side", "direction", "action", default="long")).lower()
        is_long = not (side.startswith("s") or side in ("sell", "short"))

        entry = _num(t, "entry_price", "avg_entry_price", "avg_cost", "entry")
        mark = _num(t, "current_price", "last_price", "mark_price", "market_price", "last")
        stop = _num(t, "stop_loss", "stop_price", "stop")
        tgt = _num(t, "target", "target_price", "take_profit", "pt")
        upl = _num(t, "unrealized_pnl", "unrealized", "upl")
        opened = str(_f(t, "entered_at", "created_at", "executed_at", "entry_time", "opened_at", default=""))

        by_setup[setup] = by_setup.get(setup, 0) + 1
        by_style[style] = by_style.get(style, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        if opened:
            opened_times.append(opened)

        flags = []
        # drift (signed so + = in profit direction)
        drift = 0.0
        if entry > 0 and mark > 0:
            drift = ((mark - entry) / entry * 100.0) * (1 if is_long else -1)
            if drift <= -DRIFT_WARN:
                flags.append(f"ADVERSE_DRIFT")
        elif entry <= 0:
            flags.append("NO_ENTRY")
        if mark <= 0:
            flags.append("NO_MARK")

        # bracket sanity
        rr = 0.0
        if entry > 0 and stop > 0:
            risk = (entry - stop) if is_long else (stop - entry)
            if risk <= 0:
                flags.append("STOP_WRONG_SIDE")
            elif tgt > 0:
                reward = (tgt - entry) if is_long else (entry - tgt)
                if reward <= 0:
                    flags.append("TARGET_WRONG_SIDE")
                else:
                    rr = reward / risk
                    if rr < RR_MIN:
                        flags.append(f"LOW_RR")
        else:
            if stop <= 0:
                flags.append("NO_STOP")
            if tgt <= 0:
                flags.append("NO_TARGET")

        print(f"{sym:<6} {setup[:20]:<20} {style[:10]:<10} {('LONG' if is_long else 'SHORT'):<5} "
              f"{entry:>9.2f} {mark:>9.2f} {drift:>7.2f} {stop:>9.2f} {tgt:>9.2f} {rr:>5.2f} {upl:>9.2f}  "
              f"{','.join(flags) if flags else 'ok'}")
        if flags:
            flagged.append((sym, setup, flags))

    print("\n── distribution ──")
    print("  by setup :", dict(sorted(by_setup.items(), key=lambda x: -x[1])))
    print("  by style :", dict(sorted(by_style.items(), key=lambda x: -x[1])))
    print("  by source:", dict(sorted(by_source.items(), key=lambda x: -x[1])))
    if opened_times:
        opened_times.sort()
        print(f"  opened span: {opened_times[0]}  →  {opened_times[-1]}")

    print(f"\n── verdict ──")
    print(f"  positions flagged: {len(flagged)} / {len(trades)}")
    for sym, setup, flags in flagged:
        print(f"    {sym:<6} {setup:<20} {flags}")
    if not flagged:
        print("  ✅ all positions have sane brackets and are near their mark — look VALID.")
    else:
        print("  ⚠️  review the flagged positions above (ADVERSE_DRIFT / NO_STOP / "
              "STOP_WRONG_SIDE / LOW_RR = likely stale or mis-bracketed).")

    # Authoritative fill cross-check.
    print("\n── IB truth-diff (bot entry_price vs live IB avg_cost) ──")
    td = _get("/api/trading-bot/positions/truth-diff")
    if td.get("_error"):
        print(f"  (skipped: {td['_error']})")
    else:
        # Print compactly whatever the endpoint returns.
        diffs = td.get("diffs") or td.get("mismatches") or td.get("positions") or td
        print("  " + json.dumps(diffs, default=str)[:1500])


if __name__ == "__main__":
    main()
