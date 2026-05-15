# IB-Direct Migration Plan — Institutional-Grade Trading Pipeline

**Created**: 2026-05-15 (during v19.34.26 Patch J session)
**Operator goal**: Stop patching pusher-bus symptoms; rebuild the trading
pipeline on a synchronous IB API client. Make this institutional grade.

---

## 1. Today's failure modes (the "why")

In ~6 hours of session work we fixed/found these distinct bugs, ALL of
which trace back to one root cause — using a one-way data pusher as a
two-way order bus:

| # | Bug | Root cause |
|---|-----|-----------|
| 1 | Silent simulated brackets (Patch J fixed) | Pusher offline → bot silently lied with SIM-* IDs |
| 2 | Bracket submission timeout (EGO 1639 sh naked) | Pusher confirmation arrives after bot's wait window |
| 3 | Stale position cache (8 phantom positions after flatten) | `ib_async` event-driven cache misses close events during reconnects |
| 4 | Account guard tripping during pusher warmup (Patch I fixed) | account_id arrives after positions/quotes |
| 5 | Naked-sweep infinite loop on SIM-* IDs (Patch J fixed) | Reissue path called the same broken `attach_oca_stop_target` |
| 6 | Startup race: entries fire before audit (Patch G fixed) | Scan loop ahead of orphan-GTC tripwire |
| 7 | Startup grace missing (Patch H fixed) | Pre-market staged signals cascaded on boot |
| 8 | Zombie DAY orders cascading at open (Patch F fixed) | Pre-F boot tripwire ignored TIF=DAY |

Patches A-J added 9 layers of defensive logic to a fundamentally fragile
architecture. Each layer added complexity. **Patch L (this plan) removes
the fragility instead of layering more defense.**

---

## 2. Current architecture (what we're migrating FROM)

```
        +---------------------+
        |   IB Gateway        |    Windows PC (192.168.50.1:4002)
        |   (paper account    |
        |    DUN615665)       |
        +----------+----------+
                   |
        +----------v--------------------------+
        |   ib_data_pusher.py (clientId 15)   |   Windows PC
        |   ─ Reads quotes/positions/news     |
        |   ─ Also: reads bot's order queue   |
        |     and submits to IB on bot behalf |
        +----------+--------------------------+
                   |  HTTP POST /api/ib/push-data
                   v
        +----------+--------------------------+
        |   DGX Spark — FastAPI Backend       |
        |   ─ _pushed_ib_data dict            |
        |   ─ Bot calls queue_order()         |
        |     pusher polls queue, submits     |
        |   ─ Bot waits 30-60s for pusher to  |
        |     report fill via push-data       |
        +-------------------------------------+

        +-------------------------------------+
        |   ib_direct_service.py (cid 11)     |   DGX-side (Phase 1 done)
        |   ─ Connected, authorized to trade  |
        |   ─ Used ONLY for emergency_flatten |
        |     and shadow observations         |
        +-------------------------------------+
```

### Pain points
- **Order roundtrip**: bot → DB queue → HTTP → pusher poll → IB → fill →
  pusher push → DB → bot. ~6 hops, each with timeout risk.
- **Position freshness**: pusher's snapshot is event-cached and gets
  stale on disconnect. ib-direct's snapshot is also event-cached
  (same library, same bug).
- **Failure semantics**: pusher offline = SILENT (pre-Patch-J) or HARD
  FAIL (post-Patch-J). Both are bad: the silent version causes naked
  positions, the hard version cancels every entry.

---

## 3. Target architecture (what we're migrating TO)

```
        +---------------------+
        |   IB Gateway        |
        +----+----------------+
             |
             |    Data (quotes/news/historical)
             |    +-----------+ clientId 15 +-----------+
             |    |  pusher   |─────────────│  bot      |
             +────│ (Windows) |─────POST───▶│ FastAPI   |
                  +-----------+             |  + Mongo  |
                                            |           |
             Orders + position queries      |           |
             +────────────────────────────-▶│           |
                  +---------------+          |           |
                  | ib_direct     |◀─────────│           |
                  | (DGX, cid 11) |          +-----------+
                  +---------------+
```

- **Two clients, two roles**: pusher = data-only publisher, ib-direct =
  order placement + authoritative position queries
- **Orders are synchronous**: bot calls `placeOrder()`, gets orderId in
  milliseconds, awaits `orderStatus` event for confirmation. No polling
  loops, no queues.
- **Positions are pollable**: ib-direct exposes a forced-refresh API.
  Reconciler polls fresh state each scan cycle instead of trusting cache.
- **clientId 1 (your old test) retired or kept as manual debug socket**

---

## 4. Audit — every order/position touchpoint that must migrate

### A. Bot → IB write paths (CRITICAL — naked-positions class)

| Function | File | Used by | Migration target |
|----------|------|---------|------------------|
| `execute_entry` | trade_executor_service.py:498 | Legacy single-order entry | NEW `ib_direct.place_entry()` |
| `_ib_stop` | trade_executor_service.py:640 | Legacy stop-only path | NEW `ib_direct.place_stop()` |
| `_ib_bracket` | trade_executor_service.py:895 | **Modern entry (hot path)** | NEW `ib_direct.place_bracket_order()` ← P0 |
| `attach_oca_stop_target` | trade_executor_service.py:706 | Reconciler post-fill attach | NEW `ib_direct.place_oca_stop_target()` |
| `place_market_order` | ib_direct_service.py:495 | Emergency flatten ONLY | ✅ Already on ib-direct |
| `cancel_order` | ib_direct_service.py:538 | Emergency flatten ONLY | ✅ Already on ib-direct |

### B. Bot ← IB read paths (CRITICAL — phantom-positions class)

| Source | File | Used by | Migration target |
|--------|------|---------|------------------|
| `_pushed_ib_data["positions"]` | routers/ib.py | Most position queries | Replace callers with `ib_direct.get_positions_fresh()` |
| `ib_direct.get_positions()` (cached) | ib_direct_service.py:467 | Reconciler authoritative source | Add `force_refresh=True` mode |
| `_pushed_ib_data["orders"]` | routers/ib.py | Naked-sweep, working order audit | Replace with `ib_direct.get_open_orders()` (NEW) |
| `_pushed_ib_data["account_fields"]` | routers/ib.py | Account guard, P&L | Migrate to `ib_direct.get_account_summary()` (NEW) |

### C. Reconcilers and watchdogs (must keep working through migration)

| Service | File | What it does | Migration impact |
|---------|------|--------------|------------------|
| `naked_position_sweep` | trading_bot_service.py | Detects naked positions, reissues brackets | Switch to ib-direct for "fresh orders list" and "reissue path" |
| `position_reconciler` | position_reconciler.py | Heals drift between bot and IB | Switch to ib-direct fresh-poll |
| `orphan_gtc_reconciler` | orphan_gtc_reconciler.py | Cancels untracked GTC orders at boot | Switch to ib-direct for cancel calls |
| `bracket_reissue_service` | bracket_reissue_service.py | Re-attaches brackets after detached | Switch to ib-direct attach_oca_stop_target |
| `account_guard` | account_guard.py | Verifies pusher's account_id matches expected | Switch to ib-direct managedAccounts (synchronous, no warmup race) |
| `kill_switch_gate` | kill_switch_gate.py | Refuses execution when kill switch tripped | No change (gate runs in-bot) |

### D. State stores (no migration, but verify integrity)

| Collection | What it tracks | Action |
|-----------|---------------|--------|
| `bot_trades` | Canonical trade ledger | None — Mongo doesn't care about client IDs |
| `bracket_lifecycle_events` | TTL 7d audit log | None |
| `share_drift_events` | Detected drifts | None |
| `safety_state` | Kill switch persistence | None |

---

## 5. Risks / hiccups foreseen

### R1: ib_async event cache staleness (Bug #3 today)
**Risk**: even on ib-direct, `client.positions()` returns the event-driven
cache, not a fresh server query. If position events are missed (disconnect,
network blip), cache is stale.
**Mitigation**: implement `get_positions_fresh()` that calls
`client.cancelPositions()` then `client.reqPositions()` and awaits a
full re-broadcast. Or use account-update events which are more reliable.
**Cost**: ~30 extra lines.

### R2: OCA group semantics
**Risk**: ib_async's OCA group support requires the parent order to be
transmitted=False until ALL children are queued, then the last child is
transmitted=True. Get the sequence wrong and IB rejects with confusing
errors.
**Mitigation**: ib_async has a `bracketOrder()` helper that constructs
the parent+stop+target trio correctly. Use it. Test against paper IB.
**Cost**: well-trodden pattern, low risk.

### R3: Order rejection handling
**Risk**: ib-direct will surface IB rejections (insufficient buying power,
outside RTH, etc.) as exceptions or error events. Today, pusher swallows
these. Bot needs to handle them explicitly.
**Mitigation**: wrap every placeOrder in try/except, capture
`order.orderStatus.status == "Cancelled"` events, log + drop the trade.
**Cost**: ~20 lines per call site.

### R4: Connection drops mid-trade
**Risk**: ib-direct disconnects between placeOrder and orderStatus
callback. Order may or may not be at IB. Bot doesn't know.
**Mitigation**: ib_async's watchdog auto-reconnects in ~15s. On
reconnect, query `reqOpenOrders()` for the trade's orderId. If
present → mark trade open. If absent → mark cancelled, retry.
**Cost**: ~40 lines of reconnect-rescue logic.

### R5: Concurrent clientIds on same account
**Risk**: clientId 11 (ib-direct) and clientId 15 (pusher) both place
orders on same account. Duplicate orders if both think they own the
flow.
**Mitigation**: After migration, pusher's queue_order is REMOVED.
Pusher becomes read-only. Only clientId 11 places orders. No
duplication possible.
**Cost**: Phase 3 cleanup, ~50 lines deletion.

### R6: Mongo trade record format change
**Risk**: pre-migration trades have UUID-style IDs in `entry_order_id`,
post-migration trades have IB integer IDs. Reconciler queries may
break on mixed formats.
**Mitigation**: do migration when account is flat (we already are).
All open trades closed. All new trades use new format. No mixed-format
queries against open positions.
**Cost**: 0 — just careful timing.

### R7: Latency on DGX→Windows network
**Risk**: ib-direct connects from DGX (192.168.50.2) to Windows IB
Gateway (192.168.50.1:4002). One network hop. Pusher runs ON Windows
so it has zero network latency to Gateway.
**Mitigation**: 10GbE link between DGX and Windows is sub-ms latency.
Negligible compared to IB's own ~100ms order-routing latency.
**Cost**: 0.

### R8: Paper-to-live transition
**Risk**: paper account behaves slightly different from live (no real
fills, simulated fills sometimes never happen). Code that works in
paper may misbehave in live.
**Mitigation**: validate in paper Mon-Wed before any live capital.
You're already on paper. Stay paper through Patch L burn-in.
**Cost**: 0.

### R9: Operator UI assumptions
**Risk**: the V5 UI reads `_pushed_ib_data["positions"]` etc. After
migration the canonical position source is ib-direct. UI continues to
work (still reads pusher's positions feed) but is one event-cycle
behind ib-direct's view. Could cause "UI shows naked, sweep sees
bracket attached" confusion.
**Mitigation**: in Phase 3, add an ib-direct view alongside the
pusher view in the UI. Operator can compare.
**Cost**: small UI patch in Phase 3.

### R10: Patch L's own complexity
**Risk**: Patch L is the BIG ONE. Could introduce its own bugs.
**Mitigation**: ship in three phases:
- **L1** today: scaffold `place_bracket_order` + tests, env var
  `BOT_ORDER_PATH` defaults to `pusher` (zero behavior change)
- **L2** Saturday: scaffold remaining components (place_entry, place_stop,
  place_oca_stop_target, get_positions_fresh, get_open_orders,
  get_account_summary). All ib-direct callers gated by env var.
- **L3** Monday morning: paper-validate by flipping env var to
  `shadow` for 30 min, then to `direct`. Kill switch ON throughout
  paper-validation. Operator unlocks after observing 3+ successful
  fills with real bracket IDs.

---

## 6. Migration deliverables (what gets shipped)

### Phase L1 — Today, ~75 min
**Goal**: scaffold the new `place_bracket_order` on ib-direct, wire it
into `_ib_bracket` under env var control, ship to `origin/main` with
default unchanged.

Files modified:
- `backend/services/ib_direct_service.py` — add `place_bracket_order(trade)`
  using `ib_async.bracketOrder()` helper. Returns dict matching existing
  `_ib_bracket` contract (success, entry_order_id, stop_order_id,
  target_order_id, oca_group, status, fill_price, filled_qty).
- `backend/services/trade_executor_service.py` — in `_ib_bracket`, add
  branch: `if self._order_path_mode() == "direct": return await
  self._ib_direct_bracket(trade)`. Keep existing pusher path as default.
- `backend/tests/test_patch_l1_ib_direct_bracket_v19_34_27.py` — 8
  regression tests: connection check, real bracket placement (mocked
  ib_async), OCA group correctness, timeout handling, error
  propagation, rejection handling, post-Patch-J integration, no SIM-*
  leakage.

Outcome:
- All tests pass on DGX
- Code on `origin/main` but `BOT_ORDER_PATH=pusher` by default — zero
  behavior change

### Phase L2 — Saturday-Sunday, ~3-4 hours
Files modified:
- `ib_direct_service.py` — add `place_entry`, `place_stop`,
  `place_oca_stop_target`, `get_positions_fresh`, `get_open_orders`,
  `get_account_summary` methods.
- `trade_executor_service.py` — branch all 4 hot paths on env var.
- `account_guard.py` — accept ib_direct's `managedAccounts` directly
  (eliminate Patch I warmup window dependency).
- `naked_position_sweep` (in trading_bot_service.py) — fetch fresh
  open orders from ib-direct when env var is "direct".
- `position_reconciler.py` — use `get_positions_fresh` when env var
  is "direct".
- `orphan_gtc_reconciler.py` — use ib-direct cancel when env var is
  "direct".
- `backend/tests/test_patch_l2_full_migration_v19_34_28.py` — full
  regression suite (~20 tests).

Outcome:
- All ib-direct paths code-complete and tested
- Operator can flip `BOT_ORDER_PATH` to `shadow` (parallel observation,
  pusher still acts) or `direct` (ib-direct acts, pusher data-only)
- Kill switch state respected on both paths

### Phase L3 — Monday morning runbook
1. **09:00 ET** — operator runs `.bat`, verifies pusher healthy, ib-direct
   connected & authorized, kill switch ON, account flat
2. **09:25 ET** — set `BOT_ORDER_PATH=shadow` in `.env`, restart backend.
   Bot still uses pusher for actual orders. Ib-direct submits parallel
   orders and logs divergences (no actual extra orders — shadow mode
   is observation only). Watch for 30 min.
3. **09:55 ET** — if shadow observations show ib-direct would have
   succeeded where pusher succeeded (zero divergences), set
   `BOT_ORDER_PATH=direct`, restart backend.
4. **10:00 ET** — kill switch stays ON. Watch first natural signal:
   bot should log `[v19.34.27 PATCH-L] place_bracket_order via
   ib_direct` and place a real bracket. Verify via TWS UI (don't
   need to log in if signal comes during pre-trade window — query
   `/api/system/ib-direct/orders`).
5. **10:15 ET** — if first 3 bracket placements all have real IB
   integer order IDs (not SIM-*) and all show stop+target legs in
   `get_open_orders`, unlock kill switch.
6. **10:30 ET onwards** — monitor for 1 trading hour. If clean, declare
   ib-direct primary.
7. **End of day Monday** — if hour-1 was clean, scaffold Phase L4
   (pusher queue cleanup, remove queue_order, make pusher data-only).

### Phase L4 — Tuesday-Wednesday
- Remove `queue_order` / `get_order_result` from `routers/ib.py`
- Update pusher to log + drop any order-related calls (defensive)
- Add operator dashboard showing "ib-direct order path: ACTIVE,
  pusher order path: DEPRECATED"
- Document for operator

---

## 7. What stays the same (NOT migrating)

- Pusher continues to push quotes, news, news providers, historical
  bars. That's its sweet spot — high-throughput streaming data.
- Mongo schema unchanged.
- Kill switch logic unchanged.
- Strategy/setup logic unchanged.
- ML models, opportunity_evaluator, scanner all unchanged.
- Operator UI mostly unchanged (one new status pill in Phase L4).

---

## 8. Success criteria

Patch L is "done" when:
- ✅ 25+ regression tests passing on DGX
- ✅ 1 trading hour in Monday paper mode with kill switch unlocked,
  zero naked positions, zero `bracket_submission_timeout` errors,
  zero SIM-* IDs in any open trade
- ✅ ib-direct status endpoint shows order_path=direct, observed_ok
  counter > 50 (i.e., 50 successful bracket placements)
- ✅ Stale-cache bug reproduced and confirmed FIXED via
  `get_positions_fresh()` (close a position, immediately query, see
  qty=0)
- ✅ Operator confidence: 3 trading days of paper before any live
  capital

---

## 9. Out of scope (explicitly NOT in Patch L)

- Migrating pusher to a different framework
- Adding additional brokers
- Real-money cutover (separate decision after paper validation)
- Refactoring server.py monolith (separate task)
- V6 UI refactor (separate task)

---

## 10. Today's stopping point recommendation

Given remaining session time and need for careful execution:

✅ **Ship Patch L1 today (~75 min)**: scaffold `place_bracket_order`,
wire under env var, ship tests, code lives on `origin/main` doing
nothing.

✅ **Document this plan as `IB_DIRECT_MIGRATION_PLAN.md`** so weekend
work has a north star.

⛔ **Do NOT flip `BOT_ORDER_PATH` today**. Code lands inert.

📋 **Saturday-Sunday agent session**: draft Patch L2 patches, deliver
via the Emergent sandbox URL.

🚀 **Monday 09:00 ET**: operator runs the L3 runbook.
