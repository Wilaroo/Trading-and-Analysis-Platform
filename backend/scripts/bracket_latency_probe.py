"""Bracket-order latency probe.

Measures end-to-end latency of the queue → pusher → IB → ACK loop using
the timestamps already stored on each order (`queued_at`, `claimed_at`,
`executed_at`). No pusher changes required.

Usage (on Spark):
    python3 scripts/bracket_latency_probe.py --count 5 --symbol AAPL
    python3 scripts/bracket_latency_probe.py --cancel  # cancels prior probe orders

After-hours note: parent LMT @ $100 won't fill on AAPL, but we only
measure SUBMISSION latency (queue → IB ACK with ib_order_id), not fill
latency. IB accepts the bracket instantly regardless of whether the
market is open — the pusher's submission timing is what we want.
"""
import argparse
import os
import sys
import time
import json
from datetime import datetime, timezone
from statistics import median
from typing import List, Dict, Optional

import requests

API = os.environ.get("SPARK_API", "http://localhost:8001")


def _post_bracket(symbol: str, tag: str) -> Optional[str]:
    """Queue one test bracket order. Returns order_id or None."""
    payload = {
        "type": "bracket",
        "symbol": symbol,
        "trade_id": f"latency-probe-{tag}",
        "parent": {
            "action": "BUY", "quantity": 1, "order_type": "LMT",
            "limit_price": 100.0, "time_in_force": "DAY", "exchange": "SMART",
        },
        "stop": {
            "action": "SELL", "quantity": 1, "order_type": "STP",
            "stop_price": 98.0, "time_in_force": "GTC", "outside_rth": True,
        },
        "target": {
            "action": "SELL", "quantity": 1, "order_type": "LMT",
            "limit_price": 104.0, "time_in_force": "GTC", "outside_rth": True,
        },
    }
    r = requests.post(f"{API}/api/ib/orders/queue", json=payload, timeout=5)
    if r.status_code != 200:
        print(f"  ✗ Queue failed: HTTP {r.status_code} — {r.text[:200]}")
        return None
    return r.json().get("order_id")


def _wait_for_ack(order_id: str, max_wait: float = 90.0) -> Optional[Dict]:
    """Poll until the pusher ACKs back (status moves past 'claimed') or timeout."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = requests.get(f"{API}/api/ib/orders/result/{order_id}", timeout=3)
        if r.status_code == 200:
            o = r.json().get("order", {})
            # ACK'd once pusher wrote executed_at OR ib_order_id
            if o.get("executed_at") or o.get("ib_order_id"):
                return o
            # Still pending or claimed
        time.sleep(0.25)
    # Final read even on timeout — returns last-known state
    r = requests.get(f"{API}/api/ib/orders/result/{order_id}", timeout=3)
    return r.json().get("order") if r.status_code == 200 else None


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _delta_s(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def _fmt(v: Optional[float], unit: str = "s") -> str:
    if v is None:
        return "    —    "
    return f"{v:>7.2f}{unit}"


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def probe(count: int, symbol: str, spacing: float) -> int:
    print(f"\n🔬 Bracket latency probe — {count} orders on {symbol}, {spacing}s spacing")
    print(f"   API: {API}\n")

    results: List[Dict] = []

    for i in range(count):
        tag = f"{int(time.time())}-{i}"
        t_start = time.time()
        print(f"[{i + 1}/{count}] Queueing bracket (tag={tag})...", end=" ", flush=True)

        order_id = _post_bracket(symbol, tag)
        if not order_id:
            print("SKIP")
            continue

        print(f"order_id={order_id}, waiting for ACK...", end=" ", flush=True)

        order = _wait_for_ack(order_id)
        if not order:
            print("TIMEOUT (no response from pusher)")
            continue

        q = _parse_ts(order.get("queued_at"))
        c = _parse_ts(order.get("claimed_at"))
        e = _parse_ts(order.get("executed_at"))

        queue_to_claim = _delta_s(q, c)
        claim_to_ack = _delta_s(c, e)
        total = _delta_s(q, e)
        wall = time.time() - t_start

        results.append({
            "order_id": order_id,
            "ib_order_id": order.get("ib_order_id"),
            "status": order.get("status"),
            "error": order.get("error"),
            "queue_to_claim": queue_to_claim,
            "claim_to_ack": claim_to_ack,
            "total": total,
            "wall": wall,
        })

        status = order.get("status", "?")
        ib_oid = order.get("ib_order_id") or "-"
        err = order.get("error")
        err_str = f" ERR={err}" if err else ""
        print(f"status={status} ib_oid={ib_oid}{err_str}")

        if i < count - 1:
            time.sleep(spacing)

    if not results:
        print("\n❌ No successful probes. Is the backend running?")
        return 1

    # ────────────────── REPORT ──────────────────
    print("\n" + "═" * 80)
    print(f"{'order_id':<10} {'ib_oid':<8} {'status':<10} {'q→claim':>10} {'claim→ack':>11} {'total':>9}")
    print("─" * 80)
    for r in results:
        print(
            f"{r['order_id']:<10} "
            f"{str(r['ib_order_id'] or '-'):<8} "
            f"{str(r['status']):<10} "
            f"{_fmt(r['queue_to_claim']):>10} "
            f"{_fmt(r['claim_to_ack']):>11} "
            f"{_fmt(r['total']):>9}"
        )
    print("═" * 80)

    # Aggregates
    def _stats(key: str, label: str):
        vals = [r[key] for r in results if r[key] is not None]
        if not vals:
            print(f"  {label}: no data")
            return
        print(
            f"  {label:<18} "
            f"min={min(vals):.2f}s  "
            f"p50={median(vals):.2f}s  "
            f"p95={_percentile(vals, 95):.2f}s  "
            f"max={max(vals):.2f}s"
        )

    print("\n📊 Latency breakdown:")
    _stats("queue_to_claim", "queue → claim")
    _stats("claim_to_ack", "claim → pusher ACK")
    _stats("total", "TOTAL queue → ACK")

    # Verdict
    p50_total = median([r["total"] for r in results if r["total"] is not None])
    print("\n🎯 Verdict by timeframe:")
    tiers = [
        ("scalp (1-60 min)", 3.0),
        ("intraday (1-4 hr)", 10.0),
        ("swing (1-5 days)", 60.0),
        ("position (weeks)", 300.0),
    ]
    for tier_name, budget in tiers:
        mark = "✅" if p50_total <= budget else "❌"
        print(f"   {mark} {tier_name:<22} budget {budget:>6.1f}s  actual p50 {p50_total:.2f}s")

    # Diagnosis hints
    p50_claim = median([r["queue_to_claim"] for r in results if r["queue_to_claim"] is not None])
    p50_ack = median([r["claim_to_ack"] for r in results if r["claim_to_ack"] is not None])
    print("\n🔍 Diagnosis:")
    if p50_claim > 2.0:
        print(f"   ⚠️  Pusher polling interval is slow ({p50_claim:.1f}s p50). "
              "Likely /orders/pending poll loop on a 5s sleep. Consider dropping to 500ms "
              "or WebSocket push.")
    else:
        print(f"   ✅  Pusher polling tight ({p50_claim:.2f}s p50) — no fix needed.")
    if p50_ack > 5.0:
        print(f"   ⚠️  Pusher → IB ACK is slow ({p50_ack:.1f}s p50). "
              "Likely `ib.sleep(2)` after placeOrder + waiting for all 3 orderStatus events. "
              "Next step: PowerShell-patch the pusher's bracket handler to log per-step timing.")
    else:
        print(f"   ✅  Pusher → IB ACK tight ({p50_ack:.2f}s p50) — no fix needed.")

    print("\n💡 To cancel these probe orders:")
    print("   python3 scripts/bracket_latency_probe.py --cancel")
    print()
    return 0


def cancel_probe_orders() -> int:
    """Find and cancel any open probe orders (by trade_id prefix)."""
    print("🧹 Cancelling probe orders (trade_id starts with 'latency-probe-')...\n")
    # Use the queue-status endpoint to find them
    try:
        r = requests.get(f"{API}/api/ib/orders/queue/status", timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ✗ Could not fetch queue status: {e}")
        return 1

    all_orders = (data.get("pending", []) + data.get("executing", []))
    probe_orders = [
        o for o in all_orders
        if str(o.get("trade_id", "")).startswith("latency-probe-")
    ]

    if not probe_orders:
        print("  No probe orders found in queue (they may have already completed).")
        print("  To cancel live IB orders, use TWS/IB Gateway directly or the pusher's cancel path.")
        return 0

    for o in probe_orders:
        oid = o.get("order_id")
        ib_oid = o.get("ib_order_id") or "-"
        print(f"  Order {oid} (ib_oid={ib_oid}, status={o.get('status')})")
        print(f"    → Must be cancelled via IB Gateway/TWS — see ib_order_id above")

    print(f"\n  Found {len(probe_orders)} open probe orders. Cancel them in IB Gateway.")
    return 0


def main():
    p = argparse.ArgumentParser(description="Measure bracket-order submission latency")
    p.add_argument("--count", type=int, default=5, help="Number of test brackets to send")
    p.add_argument("--symbol", default="AAPL", help="Symbol to use (stays below market)")
    p.add_argument("--spacing", type=float, default=2.0,
                   help="Seconds between test orders (avoid burst)")
    p.add_argument("--cancel", action="store_true", help="List + help cancel prior probe orders")
    args = p.parse_args()

    if args.cancel:
        return cancel_probe_orders()
    return probe(args.count, args.symbol, args.spacing)


if __name__ == "__main__":
    sys.exit(main())
