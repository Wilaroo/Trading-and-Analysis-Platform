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

## Rollback

If bracket submission misbehaves on Windows, return `bracket_not_supported`
from the pusher — Spark falls back to the legacy two-step path instantly,
no downtime.
