# Windows Pusher — Bracket Order Contract (Phase 2)

**Date:** 2026-04-22
**Status:** Spec — awaiting pusher-side implementation on Windows PC
**Blocks:** Phase 3 (caller swap) is ALREADY SHIPPED with graceful fallback — once the pusher implements this, atomic brackets activate automatically. No Spark-side change needed when you deploy this.

## Why

Sequential entry→stop submission leaves naked positions during:
- Bot restarts (stop order never placed)
- Pusher disconnects (stop order never reaches IB)
- Transient IB gateway hiccups
- Strategy-phase timing edge cases

Native IB bracket orders eliminate all four.

## New payload shape

When the Spark backend queues an order with `"type": "bracket"`, the pusher must:

1. Read parent, stop, and target child order specs.
2. Reserve 3 contiguous orderIds via `reqIds()`.
3. Submit parent with `transmit=False`.
4. Submit stop child with `parentId=<parent>`, `ocaGroup=<auto>`, `ocaType=1`, `transmit=False`.
5. Submit target child with `parentId=<parent>`, same `ocaGroup`, `ocaType=1`, `transmit=True` ← activates all three atomically.
6. ACK back via `POST /api/ib/orders/result` with the IB-assigned order IDs.

### Request payload (from Spark)
```json
{
  "type": "bracket",
  "trade_id": "<uuid fragment>",
  "symbol": "USO",
  "parent": {
    "action": "SELL",
    "quantity": 1000,
    "order_type": "LMT",
    "limit_price": 108.28,
    "time_in_force": "DAY",
    "exchange": "SMART"
  },
  "stop": {
    "action": "BUY",
    "quantity": 1000,
    "order_type": "STP",
    "stop_price": 109.20,
    "time_in_force": "GTC",
    "outside_rth": true
  },
  "target": {
    "action": "BUY",
    "quantity": 1000,
    "order_type": "LMT",
    "limit_price": 106.50,
    "time_in_force": "GTC",
    "outside_rth": true
  }
}
```

### Response payload (to Spark via POST /api/ib/orders/result)
```json
{
  "order_id": "<original_queue_id>",
  "status": "filled" | "working" | "rejected",
  "result": {
    "status": "filled",
    "entry_order_id": 12345,
    "stop_order_id":  12346,
    "target_order_id": 12347,
    "oca_group": "oca_USO_3f8a2c1d",
    "fill_price": 108.29,
    "filled_qty": 1000
  }
}
```

### Fallback signaling

If the pusher hasn't been upgraded yet, respond with:
```json
{
  "order_id": "<original_queue_id>",
  "status": "rejected",
  "result": { "error": "bracket_not_supported" }
}
```

The Spark caller automatically falls back to the legacy two-step flow when it
sees this — so you can safely roll out Phase 2 on the pusher whenever you're
ready, without coordinating a Spark restart.

## Reference `ib_insync` implementation

On Windows, the pusher uses `ib_insync`. The Phase 1 primitive that Spark
already has (see `backend/services/ib_service._do_place_bracket_order`) is
the reference implementation — copy its logic verbatim into the pusher's
order handler:

```python
from ib_insync import Stock, Order
import uuid

def handle_bracket(ib, order_payload):
    symbol = order_payload["symbol"]
    p = order_payload["parent"]
    s = order_payload["stop"]
    t = order_payload["target"]
    oca_group = f"oca_{symbol}_{uuid.uuid4().hex[:8]}"

    contract = Stock(symbol.upper(), "SMART", "USD")
    ib.qualifyContracts(contract)

    parent_oid = ib.client.getReqId()
    stop_oid   = ib.client.getReqId()
    target_oid = ib.client.getReqId()

    parent = Order(orderId=parent_oid, action=p["action"],
                   totalQuantity=p["quantity"], orderType=p["order_type"],
                   lmtPrice=p.get("limit_price", 0.0),
                   tif=p.get("time_in_force", "DAY"),
                   transmit=False, outsideRth=False)
    stop   = Order(orderId=stop_oid, action=s["action"],
                   totalQuantity=s["quantity"], orderType="STP",
                   auxPrice=s["stop_price"], parentId=parent_oid,
                   tif=s.get("time_in_force", "GTC"),
                   ocaGroup=oca_group, ocaType=1,
                   transmit=False,
                   outsideRth=s.get("outside_rth", True))
    target = Order(orderId=target_oid, action=t["action"],
                   totalQuantity=t["quantity"], orderType="LMT",
                   lmtPrice=t["limit_price"], parentId=parent_oid,
                   tif=t.get("time_in_force", "GTC"),
                   ocaGroup=oca_group, ocaType=1,
                   transmit=True,
                   outsideRth=t.get("outside_rth", True))

    pt = ib.placeOrder(contract, parent)
    st = ib.placeOrder(contract, stop)
    tt = ib.placeOrder(contract, target)
    ib.sleep(2)

    return {
        "status": "working" if pt.orderStatus.status in ("Submitted", "PreSubmitted") else pt.orderStatus.status.lower(),
        "entry_order_id": pt.order.orderId,
        "stop_order_id":  st.order.orderId,
        "target_order_id": tt.order.orderId,
        "oca_group": oca_group,
        "fill_price": pt.orderStatus.avgFillPrice or None,
        "filled_qty": pt.orderStatus.filled or 0,
    }
```

## Testing

After deploying on Windows, verify from Spark:

```bash
# Queue a tiny test bracket via a simulated bot trade
curl -s -X POST "http://localhost:8001/api/trading-bot/demo-trade" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","direction":"long","setup_type":"rubber_band"}' | jq .

# Verify the trade now has BOTH stop_order_id AND target_order_id filled
curl -s "http://localhost:8001/api/trading-bot/trades/open" | \
  jq '.trades[] | {symbol, entry_order_id, stop_order_id, target_order_id}'

# Watch for the `[BRACKET-INTERACTIVE_BROKERS]` tag in trade.notes — that's
# the proof path. Legacy flow leaves `[LIVE-INTERACTIVE_BROKERS]`.
```

## v19.34.103 amendment — Multi-rung OCA target ladder

**Date:** Feb 2026
**Status:** Spec extension — Spark backend now SENDS the new shape; pusher
implementation pending. Old single-`target` payload is preserved as a
fallback so older pushers continue to work unchanged.

### Why
v19.34.100 introduced per-style execution policies. Long-horizon styles
(`multi_day`, `swing`, `investment`, `position`) carry multi-rung TP
ladders (e.g. position = `25% @ 4R · 25% @ 8R · 50% @ 15R`). The single
`target: {...}` leg only books the FIRST rung — partial-profit
scale-outs never reach IB and the runner never gets booked.

### New optional payload field

When `trade.shares` and the registry's `tp_ladder` produce >1 rung,
Spark adds a `"targets"` ARRAY of LMT legs. Each rung is OCA-grouped
WITH THE SAME STOP — IB's native OCA-group semantics auto-reduce the
stop's quantity as each target fills (per operator confirmation
2026-02-12: "single shared stop, qty auto-reduces on each TP fill").

```json
{
  "type": "bracket",
  "trade_id": "<uuid fragment>",
  "symbol": "NVDA",
  "parent": { ... },
  "stop": {
    "action": "SELL",
    "quantity": 100,
    "order_type": "STP",
    "stop_price": 95.50,
    "time_in_force": "GTC",
    "outside_rth": true
  },
  "target": {                               // legacy single rung
    "action": "SELL", "quantity": 25, "order_type": "LMT",
    "limit_price": 110.00, "time_in_force": "GTC", "outside_rth": true
  },
  "targets": [                              // v19.34.103 multi-rung ladder
    {"action": "SELL", "quantity": 25, "order_type": "LMT",
     "limit_price": 110.00, "r_multiple": 4.0,
     "time_in_force": "GTC", "outside_rth": true},
    {"action": "SELL", "quantity": 25, "order_type": "LMT",
     "limit_price": 130.00, "r_multiple": 8.0,
     "time_in_force": "GTC", "outside_rth": true},
    {"action": "SELL", "quantity": 50, "order_type": "LMT",
     "limit_price": 165.00, "r_multiple": 15.0,
     "time_in_force": "GTC", "outside_rth": true}
  ],
  "policy": {                               // v19.34.102 audit stamp
    "style": "position",
    "horizon_label": "3+ months",
    "stop_trail_anchor": "sma_150",
    "eod_sweep_eligible": false
  }
}
```

Spark guarantees that `sum(targets[i].quantity) == stop.quantity == parent.quantity`.

### Pusher upgrade path
1. If `targets` is missing or empty → place a single target (legacy behavior).
2. If `targets` has 1+ entries:
   - Reserve N+2 `reqIds()` (parent + stop + N targets).
   - Submit parent (`transmit=False`).
   - Submit stop child (`parentId=<parent>`, `ocaGroup=<auto>`, `ocaType=1`, `transmit=False`).
   - Submit each `targets[i]` child (`parentId=<parent>`, same `ocaGroup`, `ocaType=1`, `transmit=False`) — except the LAST one which sets `transmit=True` to activate atomically.
3. ACK back with a `target_order_ids: [...]` list (and keep `target_order_id` = `target_order_ids[0]` for backward compat).

`ocaType=1` ("cancel-with-block") is correct here: when any TP fills
partial, IB reduces all other OCA legs' quantity proportionally.

### Backward compatibility
- Older pushers ignore `targets` and execute `target` only. Spark
  treats those trades as if only the first rung were booked (operator
  loses the multi-rung scale-out but the trade is otherwise safe — stop
  and first TP still active).
- Spark continues to surface `r.target_order_id` on the response object;
  multi-rung pushers SHOULD additionally surface `target_order_ids`.

### Parent TIF + outside_rth (v19.34.102)
Pre-v19.34.102 the parent leg was hardcoded `time_in_force: "DAY"` and
omitted `outside_rth` entirely. Spark now sources both fields from the
policy registry. Pushers MUST honor whatever Spark sends in the parent
block — particularly `time_in_force: "GTC"` for long-horizon entries
that are allowed to sit overnight if not filled in the first session.

---

## Rollback

If bracket submission misbehaves on Windows, return `bracket_not_supported`
from the pusher — Spark falls back to the legacy two-step path instantly,
no downtime.
