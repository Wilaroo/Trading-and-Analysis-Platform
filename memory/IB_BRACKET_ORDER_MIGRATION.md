# IB Order Persistence Analysis & Bracket-Order Migration Plan

**Date:** 2026-04-21  
**Status:** Analysis complete — migration proposed, not yet implemented  
**Priority:** 🔴 P0 (causing real account losses — vwap_fade_short bled ~-488R)

## The problem we just lived through

During development, SentCom placed entry orders via the Windows PC pusher, then tried to place a separate STOP order a moment later. Three failure modes produce the same catastrophic outcome — **entry filled at IB, no stop at IB**:

1. **Bot process crashes / restarts** between step 1 and step 2. Development involved many restarts.
2. **Windows pusher disconnects** during the two-call sequence.
3. **`place_stop_order` silently fails** (returns `success=False`), `trade.stop_order_id` stays empty, and the bot thinks it's protected when it isn't.

Evidence from Mongo audit (2026-04-21):
- USO short: entry 108.28, intended stop 108.31 ($0.03 risk), actual exit 116.12 → **blew 261× past stop**
- WTI short: $0.02 stop, exit $0.36 past → **18× past stop**
- 51 `vwap_fade_short` trades averaged -9.57R with 8.9% WR

## The fix: IB Native Bracket Orders

IB supports bracket orders that are ATOMIC at the broker level:

```
PARENT  : BUY 100 USO LMT @ 108.28   (transmit=false)
CHILD A : SELL 100 USO STP @ 108.31  (parentId=PARENT, OCA group)
CHILD B : SELL 100 USO LMT @ 107.50  (parentId=PARENT, OCA group, transmit=true)
```

Semantics IB guarantees once the parent fills:
- STP and TGT sit at IB indefinitely as GTC orders
- OCA (One-Cancels-All) — whichever triggers first cancels the other
- **The bot can die, restart, or be offline for days** — the orders persist
- IB itself enforces the stop; no round-trip to SentCom required

## Current code path (what we have)

`backend/services/trade_execution.py:158` — executes entry, awaits fill, then:
```python
stop_result = await bot._trade_executor.place_stop_order(trade)
```

`backend/services/trade_executor_service.py` — `place_stop_order` submits a
standalone STP order to the pusher queue, completely decoupled from the parent.

`backend/services/ib_service.py:1130` — `place_order` supports `order_type` field
but doesn't support `parentId` / `ocaGroup`.

## Migration plan (what we need to build)

### Phase 1 — IB service supports bracket primitive (2-3 hours)
Add `ib_service.place_bracket_order(trade)` that:
- Submits 3 orders via `reqIds()` + batched `placeOrder` calls to IB gateway
- Uses `parentId` + `ocaGroup` + `transmit=false/false/true` correctly
- Returns `{parent_id, stop_id, target_id}` atomically
- Falls back to legacy two-step path if IB gateway doesn't respond

### Phase 2 — Windows pusher supports atomic bracket submission (2-3 hours)
Current pusher queues single orders. Needs a `"type": "bracket"` payload:
```json
{
  "type": "bracket",
  "parent": {"action": "BUY", "order_type": "LMT", "price": 108.28, ...},
  "stop":   {"action": "SELL", "order_type": "STP", "price": 108.31},
  "target": {"action": "SELL", "order_type": "LMT", "price": 107.50}
}
```
Pusher submits all three to IB before ACKing back to SentCom.

### Phase 3 — trade_execution.py uses bracket submission (1 hour)
Replace the two-step flow in `trade_execution.py` with single `place_bracket_order` call. Remove the separate `place_stop_order` path for NEW trades (keep the function for manual-stop-moves on existing positions).

### Phase 4 — Reconciliation on bot startup (2 hours)
On startup, `position_reconciler.py` must:
1. Query IB for all open positions AND working STP/LMT orders
2. Rebuild the `_open_trades` dict from IB (source of truth)
3. If a position exists at IB without a working stop → **CRITICAL ALERT** + auto-place emergency stop at last-known risk distance

### Phase 5 — Stop-honor monitoring (DONE today)
`services/trade_execution_health.py` + `GET /api/trading-bot/execution-health` — detects stop failures post-hoc so we know immediately if any regression creeps in.

### Phase 6 — Frontend alert card (1 hour, future)
Add a `<TradeExecutionHealthCard>` to the NIA dashboard that polls the new endpoint every 60s and shows an amber/red banner when `alert_level != "ok"`.

## Guard rails to implement BEFORE migrating

These should land in a small hotfix regardless of the bracket migration:

1. **Minimum stop distance**: reject any trade where `|entry - stop| < 0.3 × ATR(sym, 14)`. The USO $0.03 stop on a $108 stock was absurd — noise alone crosses it.
2. **Maximum position notional**: cap `shares × entry` at `0.01 × account_equity` per trade until bracket migration is complete. Small positions = small damage if a stop fails.
3. **Disable `vwap_fade_short`** in `setup_config.py` until root cause is confirmed fixed.

## Risk of NOT migrating

Continuing with two-step submission means every bot restart creates a window where live positions can have no stop at IB. Even with a 99.9% reliable pusher, that's 1 naked position per 1,000 trades. Given the leverage from tight stops (a 0.03% stop on a 10% mover = 333× leverage), a single failure can wipe weeks of gains.

## Out-of-scope for now

- Trailing stops at IB (post-bracket feature)
- IB's `adjusted stops` via `AdjustableOrder` API
- Multi-leg options orders (if ever needed)

---

## Next action items

- [ ] Implement Phase 1-3 (bracket order end-to-end)
- [ ] Add ATR-based minimum stop distance check
- [ ] Disable `vwap_fade_short` in `setup_config.py`
- [ ] Run the new `GET /api/trading-bot/execution-health?hours=168` weekly as a regression check
- [ ] Fix the 18 inverted-stop short docs identified in the audit
