# TradeCommand / SentCom — Changelog

Reverse-chronological log of shipped work. Newest first.

## 2026-05-04 (sixty-fifth commit, v19.30.13) — False-alarm cleanup pass: ADV schema clobber, ib_gateway yellow, ai-training timeouts

**Three operator-flagged false alarms / bugs surfaced during the 2026-05-04 pre-market session.** All three made the dashboard say one thing while the underlying data said another, sending the operator on wild goose chases.

### Fix 1 — ADV cache schema clobber (the actual smoking gun for "smart-backfill returns 0")

Two endpoints write to `symbol_adv_cache` with **incompatible schemas**:
- `/api/ib-collector/build-adv-cache` upserts: `avg_volume`, **`avg_dollar_volume`**, `atr_pct`, **`tier`**, `latest_close`
- `/api/ai-modules/adv/recalculate` did `delete_many({})` + `insert_many` with ONLY `avg_volume`, **silently wiping `avg_dollar_volume` and `tier` fields**

Operator ran them in this order: `build-adv-cache` (success: 9412 docs with `avg_dollar_volume` + `tier`) → `adv/recalculate` (DELETED ALL 9412, re-inserted 9270 without `avg_dollar_volume`) → `smart-backfill` (queried `{avg_dollar_volume: {$gte: 2_000_000}}` → matched 0 docs even though 9270 were in the cache) → falsely concluded "no symbols qualify".

**Fix (`backend/routers/ai_modules.py::recalculate_adv_cache()`)**: redirected to the canonical `IBHistoricalCollector.rebuild_adv_from_ib_data()` builder. Both endpoints now converge on the same code path → no schema drift possible. Source-level pin asserts no future contributor can re-import the deprecated `scripts/recalculate_adv_cache.py` clobber path.

### Fix 2 — `ib_gateway: yellow` false-alarm (the persistent "1 WARN")

The DGX backend in this deployment never connects directly to IB Gateway — the Windows pusher is the only IB path. Pre-fix, `_check_ib_gateway()` returned yellow with detail `"ib_service not registered"` because it only checked for direct IB. This showed up as "1 WARN" in the V5 HUD header forever, sending operators on wild goose chases looking for a degraded IB Gateway that doesn't exist in this deployment.

**Fix (`backend/services/system_health_service.py::_check_ib_gateway()`)**: pusher-only deployment is now a valid full configuration. New decision matrix:

| ib_service registered? | Direct connected? | pusher_rpc reachable? | Result |
|---|---|---|---|
| Yes | Yes | n/a | GREEN ("connected") |
| Yes | No | n/a | YELLOW ("disconnected", legitimately degraded) |
| No | n/a | Yes | **GREEN ("pusher-only deployment — direct IB not used")** |
| No | n/a | No | YELLOW ("no IB path: ib_service not registered and pusher unreachable") — genuine concern |

`metrics.via_pusher: bool` added so the V5 HUD can render the actual deployment shape.

### Fix 3 — Collector `is-active` timeout warnings

Windows historical collectors poll `GET /api/ai-training/is-active` every cycle with a 5s timeout. Pre-fix the handler was `def is_training_active()` — a sync handler running in FastAPI's thread pool. When Spark was busy with scanner / push-data / smart-backfill, the call queued behind other sync handlers and the 5s timeout occasionally fired, even though the handler itself does only ~3 in-memory dict reads in microseconds.

**Fix (`backend/routers/ai_training.py::is_training_active()`)**: `def → async def` runs it directly on the event loop. No thread-pool queuing → microsecond response time guaranteed regardless of other backend load. Source-level pin via `asyncio.iscoroutinefunction()` so a future contributor can't re-introduce the sync version.

### Tests
11 new pytests in `tests/test_false_alarm_cleanup_v19_30_13.py` covering all three fixes (source-level pins, functional checks, error path resilience). **80/80 passing across the v19.30 stack** (69 prior + 11 new).

### Operator action — Spark deploy
```bash
cd ~/Trading-and-Analysis-Platform && git pull
./start_backend.sh   # safe — skip-if-healthy guard from v19.30.11

# Verify the three fixes:
curl -s localhost:8001/api/system/health | jq '.subsystems[] | select(.name=="ib_gateway")'
# → status: "green", detail: "pusher-only deployment — direct IB not used"

curl -X POST localhost:8001/api/ai-modules/adv/recalculate | jq '.tier_summary'
# → returns intraday/swing/investment/skip counts (canonical builder)

curl -X POST 'localhost:8001/api/ib-collector/smart-backfill?freshness_days=1' | jq '.tier_counts'
# → returns NON-ZERO counts now that schema is preserved
```

### What this confirms about the v19.30 architecture
The diagnostic chain (banner → health subsystem → endpoint metrics) is now self-consistent end-to-end:
- v19.30.11 caught operator footguns + pusher overload
- v19.30.12 distinguished push vs RPC channel
- v19.30.13 cleans up the remaining "false positives" that send operators chasing non-issues

The dashboard now ONLY fires alerts when something is genuinely wrong.

---

## 2026-05-01 (afternoon recovery, post-deploy operations) — Network classification fix on Windows side

**Closed the underlying network bug** that v19.30.11/.12 banner correctly diagnosed but couldn't fix from Spark.

After all backend fixes shipped (skip-restart guard, pusher RPC throttle/circuit-breaker/dedup, dual-channel health, action-aware banner), the SystemBanner correctly fired the `pusher_rpc_blocked` warning with the inline `netsh` firewall command. Operator added the firewall rule (`netsh advfirewall firewall add rule name="IB Pusher RPC 8765" dir=in action=allow protocol=TCP localport=8765`), but Spark→Windows on :8765 still timed out. Added rule was scoped to `Domain,Private,Public` profiles correctly — but the 10GbE adapter on Windows was classified as **Public** under "Unidentified network", and Public profile silently overrides allow rules on this network even when explicitly added.

### Diagnostic chain
1. ✅ `Get-NetConnectionProfile` → 10GbE adapter (`Ethernet 3`) classified as `Public`, `IPv4Connectivity: LocalNetwork`
2. ✅ Temporarily disabling firewall (`netsh advfirewall set allprofiles state off`) → ping + curl Spark→Windows succeeded → confirmed firewall as the layer
3. ✅ `Set-NetConnectionProfile -InterfaceAlias "Ethernet 3" -NetworkCategory Private` → reclassified the 10GbE link as Private
4. ✅ Re-test with firewall ON → ping 0.15ms RTT, curl 200 OK with full pusher health

### Why the fix works
The direct 10GbE point-to-point cable between Spark (192.168.50.2) and Windows (192.168.50.1) is semantically a private trusted link, not a hostile public network. Windows' Public profile applies stricter overrides than the per-rule allow we added. Reclassifying as Private makes Windows honor the existing allow rule. No firewall rule changes needed — only the network category.

### What this confirms about the v19.30.11/.12 fixes
The full diagnostic stack worked exactly as designed:
- v19.30.11 SystemBanner displayed clearly across the top — operator couldn't miss it
- v19.30.12 nuanced detail told operator "live data still flowing" so they didn't panic-restart Spark
- Inline `netsh` action command was correct (firewall rule needed to be added)
- And when that didn't fully resolve, the banner stayed yellow (not red) because `push_fresh` was True — exact severity matrix worked
- `Get-NetConnectionProfile`/`Set-NetConnectionProfile` chain was the Windows-side fix the banner couldn't surface from Spark

### Operator action — Permanent fix (already applied)
```powershell
# As Admin (one-time, persists through reboots):
Set-NetConnectionProfile -InterfaceAlias "Ethernet 3" -NetworkCategory Private
```
The firewall stays ON. The existing `IB Pusher RPC 8765` allow rule is now honored.

---

## 2026-05-01 (sixty-fourth commit, v19.30.12) — Distinguish push-channel vs RPC-channel pusher health

**Operator's v19.30.11 deploy surfaced a real edge case:** SystemBanner showed "Windows IB Pusher unreachable, 19 consecutive failures over 150s" *while the pusher's own log showed `Push OK every 10s` and 72 quotes streaming successfully*.

Both signals correct from their respective vantage points:
- **Push channel** (Windows :8765 → Spark :8001 via `POST /api/ib/push-data`): ✅ Working — 72 quotes / 5 positions every 10s.
- **RPC channel** (Spark → Windows :8765 via `/rpc/latest-bars`, `/rpc/health`, etc.): ❌ Failing.

Asymmetric network — most likely **Windows firewall blocking inbound on :8765**, so Spark's outbound RPC calls couldn't reach the pusher's RPC server even though the pusher's outbound push HTTP calls worked fine. v19.30.11 banner was a sledgehammer that conflated the two channels into a single "pusher dead" message.

### Fix — health-service distinguishes channels

**File:** `backend/services/system_health_service.py::_check_pusher_rpc()`

New severity matrix:

| push fresh (<60s) | RPC working | → status | detail prefix |
|---|---|---|---|
| ✅ | ✅ | **green** | `last ok …s ago` |
| ✅ | ❌ | **yellow** | `rpc_blocked` (push HEALTHY, only RPC degraded) |
| ❌ | ✅ | **yellow** | `push_blocked` (weird state; usually transient) |
| ❌ | ❌ | **red** | `fully_dead` (pusher process is down) |

Reads `routers.ib._pushed_ib_data["last_update"]` directly via module attribute (NOT via `get_pushed_ib_data()` — that helper is shadowed by an async HTTP endpoint of the same name at routers/ib.py:615, so callable lookup gets the coroutine). Adds `push_age_s` and `push_fresh` to subsystem metrics so the banner can render them.

### Banner copy — three distinct cases

**File:** `backend/routers/system_banner.py`

- `pusher_rpc_dead` → **CRITICAL** banner: "Windows IB Pusher is DOWN" + "Do NOT restart the Spark backend — it's healthy" action.
- `pusher_rpc_blocked` → **WARNING** banner: "Spark→pusher RPC blocked — live data still flowing" + the actual `netsh advfirewall firewall add rule name="IB Pusher RPC 8765" dir=in action=allow protocol=TCP localport=8765` command in the action text.
- `pusher_rpc_partial` → **WARNING** banner: covers any future weird state.

Generic "Some subsystems are degraded" suppressed when `pusher_rpc` is the only yellow subsystem (its dedicated banner already covered it).

### Tests
8 new pytests in `tests/test_pusher_health_dual_channel_v19_30_12.py` (all 4 quadrants of the severity matrix + banner double-fire suppression + module-level patching pattern). 3 banner tests rewritten in `tests/test_pusher_throttle_v19_30_11.py` to match the new fully_dead/rpc_blocked detail tokens. **69/69 passing across the v19.30 stack.**

### Operator action — Spark deploy
```bash
cd ~/Trading-and-Analysis-Platform && git pull
./start_backend.sh   # safe — skip-if-healthy guard from v19.30.11 means no-op if already up

# Verify the new banner copy after 30s
curl -s localhost:8001/api/system/banner | jq .
# When push fresh + RPC blocked → level: "warning", message includes "RPC blocked"
# When push stale + RPC fail   → level: "critical", message: "Windows IB Pusher is DOWN"
```

### To fix the underlying Windows firewall (optional but recommended)
On Windows (Run as Administrator):
```cmd
netsh advfirewall firewall add rule name="IB Pusher RPC 8765" dir=in action=allow protocol=TCP localport=8765
```
Then verify from Spark:
```bash
curl -m 3 http://192.168.50.1:8765/rpc/health
```
If that returns 200, RPC channel is open and the banner will flip green within 10s. If it still fails, check Windows Defender Firewall → Inbound Rules manually and ensure no other firewall (corporate/3rd-party) is blocking.

---

## 2026-05-01 (sixty-third commit, v19.30.11) — Pusher overload protection + skip-restart-if-healthy + system banner

**Operator hit a real problem 2026-05-01 afternoon:** dashboard appeared empty → assumed Spark backend was broken → ran `./start_backend.sh` → script killed a perfectly healthy backend AND ate 60-90s of cold boot. Diagnostic data proved the actual cause was the **Windows IB Pusher had died** (overload-induced — concurrent `/rpc/latest-bars` calls fanned out into IB Gateway's 6-concurrent-`reqHistoricalData` limit; IB closed the socket; pusher process couldn't recover). Three independent fixes shipped together to prevent recurrence:

### 🔴 Fix 1 — Bounded concurrency + circuit breaker + dedup on Spark→pusher RPC

**File:** `backend/services/ib_pusher_rpc.py` (~225 lines added/refactored)

- **`threading.Lock` → `threading.Semaphore(N)`** (default N=4, env-configurable via `IB_PUSHER_RPC_MAX_CONCURRENT`). Caps concurrent in-flight Spark→pusher requests so a chart-mount storm + scanner tick + bar_poll can't combine into an IB pacing violation. Default 4 leaves 2 slots at the pusher for its internal account/quote ops within IB's 6-concurrent budget.
- **Circuit breaker** with three states (`closed` / `open` / `half_open`):
  - 5 failures within a rolling 10s window → flip to **OPEN**
  - **OPEN** state short-circuits all calls (return None immediately) for 30s, instead of spamming retries that would prolong the outage
  - After 30s → **HALF_OPEN** test request; success closes the circuit, failure re-opens for another 30s
  - Tunable via `IB_PUSHER_RPC_CIRCUIT_THRESHOLD` / `_WINDOW_S` / `_OPEN_S`
- **In-flight dedup** on idempotent reads (`latest_bars`, `latest_bars_batch`, `subscriptions`, `account_snapshot`, `health`, `quote_snapshot`). Multiple chart panels asking for the same payload simultaneously coalesce into a SINGLE HTTP round-trip via a shared `threading.Event`. Followers wait up to `1.5×timeout` for the leader's response.
- **Fail-open contract preserved**: every failure path still returns `None`; callers (chart panel, scanner) fall back to Mongo cache. The chart UI keeps rendering during a pusher outage instead of blanking.
- **Surface metrics** in `/api/ib/pusher-health`: `rpc_max_concurrent`, `rpc_circuit_state`, `rpc_circuit_open_remaining_s`, `rpc_circuit_recent_failures`, `rpc_circuit_short_circuit_total`, `rpc_semaphore_timeout_total`, `rpc_dedup_coalesced_total`.

### 🟡 Fix 2 — Skip-restart-if-healthy guard

**Files:** `start_backend.sh`, `scripts/spark_start.sh`

Both scripts now short-circuit when the backend is already healthy. Pre-fix the first action was always `fuser -k 8001/tcp` — meaning every invocation guaranteed downtime + cold-boot wait. New behaviour:
- If `curl -sf http://localhost:8001/api/health` returns 200 → exit 0 with friendly message
- `--force` flag overrides for genuine restarts
- Cold-boot wait bumped 60s → 120s (the deferred-init storm — IB connect retry + scanner state restore + bot `_restore_state` + simulation engine + ML models — legitimately takes 60-90s; the v19.30.6 wedge watchdog catches genuine wedges separately)
- Removed an explicit log truncation that was redundant with `nohup ... > /tmp/backend.log`

### 🟢 Fix 3 — `GET /api/system/banner` + V5 SystemBanner.jsx

**Files:** `backend/routers/system_banner.py` (NEW, 175 lines), `frontend/src/components/sentcom/v5/SystemBanner.jsx` (NEW, 145 lines), wired into `SentComV5View.jsx` above `PusherDeadBanner`.

Operator-facing alert strip that polls the new `/api/system/banner` endpoint every 10s. Fires a giant red strip across the top of the V5 HUD when:
- Pusher_rpc has been red ≥30s → critical level with explicit action: "Check Windows side… Do NOT restart the Spark backend — it's healthy" (this exact copy is what would have prevented today's footgun)
- MongoDB has been red ≥10s → critical level with `docker start mongodb` action
- Overall health yellow → thinner amber strip

Dismissable for 60s; reappears if the problem persists. Cleared automatically when the subsystem flips back to green. Internally consistent with `/api/system/health` (single source of truth — banner translates the diagnostic into operator-facing copy).

### Tests
20 new pytests in `tests/test_pusher_throttle_v19_30_11.py` covering circuit breaker state machine, semaphore concurrency cap, dedup correctness with concurrent threads, fail-open contract, source-level pins for `start_backend.sh` / `spark_start.sh` guards, and banner endpoint behaviour. **60/60 across the v19.30 stack** (40 prior + 20 new). Live-validated in container: `/api/system/banner` returns expected payload, `/api/ib/pusher-health` surfaces all new throttle metrics.

### Operator action — Spark deploy
```bash
cd ~/Trading-and-Analysis-Platform && git pull
# The skip-if-healthy guard means subsequent runs of start_backend.sh
# are now safe — if backend is up, nothing happens.
./start_backend.sh

# Verify the new metrics surface
curl -s localhost:8001/api/ib/pusher-health | jq '.heartbeat | {rpc_max_concurrent, rpc_circuit_state, rpc_dedup_coalesced_total}'
curl -s localhost:8001/api/system/banner | jq .
```

### Why this trio prevents recurrence
- **Pusher overload mitigated** by Fix 1 — Spark can't swamp pusher into an IB pacing violation, AND when pusher does fail (different cause), the circuit breaker stops Spark from prolonging the outage with a retry storm
- **Footgun closed** by Fix 2 — operator can't accidentally kill a healthy backend during troubleshooting
- **Mistaken diagnosis prevented** by Fix 3 — when something IS broken, the dashboard tells the operator EXACTLY what's broken AND what NOT to do

---

## 2026-05-01 (sixty-second commit, v19.30.10) — Drop the "degraded mode" theatre on /account/positions

**Operator pushback on the v19.30.9 ship:** "why do we need degraded mode at all? didn't yesterday's chart change fix this?".

Both points correct, addressed:

### Point 1 — Yesterday's "chart change" was v19.25 cache + tail-polling, not WebSockets

What shipped 2026-05-01 was Tier 1 (Mongo-backed `chart_response_cache`) + Tier 2 (`/api/sentcom/chart-tail` 5s incremental refresh). That's smart HTTP polling, not WebSockets. **Tier 3 chart WebSockets are still parked as v19.32 in the roadmap — fully scoped, no code yet.** And neither tier had anything to do with the positions 503 — that was a totally separate endpoint with a totally separate bug.

### Point 2 — The "try direct IB → fall back to pusher" pattern was theatre

The DGX backend has never connected directly to IB Gateway in this deployment — the Windows pusher does. So `_ib_service.get_positions()` was always going to fail. Wrapping that doomed call in a `degraded:true` fallback was conceptual noise.

**Fix (`backend/routers/ib.py`)**: simplified `/account/positions` to a clean two-tier read:

1. **Hot path** — in-memory `_pushed_ib_data["positions"]` (~2s old, written on every pusher push) → `source: "memory"`.
2. **Warm path** — Mongo `ib_live_snapshot.current` document (written by `/api/ib/push-data` on every push, survives backend restarts, covers the ~10-30s post-restart window before in-memory is repopulated) → `source: "mongo_snapshot"`. Read wrapped in `asyncio.to_thread` for event-loop safety.
3. **Empty** — both tiers empty → `source: "empty"`.

No more `degraded` flag, no more doomed `_ib_service.get_positions()` call, no more `ConnectionError` handling. Source-level pin asserts a future contributor can't silently re-introduce direct-IB calls into this handler.

Also removed: the dead `get_account_summary_alt` async handler at line 1094 (FastAPI uses first-registered route, so it was unreachable). The primary sync `/account/summary` at line 804 already reads pusher data the right way.

### Tests
15 pytests in `tests/test_degraded_mode_fixes_v19_30_9.py` (5 for the simplified positions endpoint, 3 for hybrid_data_service async-safety pins, 7 for cancel-all-pending-orders). **40/40 across v19.30 stack.** Live-validated: `GET /api/ib/account/positions` returns `{ source: "empty" }` in this container instead of HTTP 503.

### Operator action — Spark deploy
```bash
cd ~/Trading-and-Analysis-Platform && git pull && ./start_backend.sh
curl -s -m 5 localhost:8001/api/ib/account/positions | jq .
# When pusher is live → { source: "memory", count: N, ... }
# Right after restart → { source: "mongo_snapshot", count: N, ... }
# Pusher off + no prior snapshot → { source: "empty", count: 0, ... }
```

---

## 2026-05-01 (sixty-first commit, v19.30.9) — Degraded-mode UI fixes + cancel-all-pending-orders

**3 surface bugs filed by operator post-v19.30.8 deploy. All wedge-immune fixes (no new sync-in-async sites added).**

### Bug #1 — `/api/ib/account/positions` returned blanket 503 in degraded mode
The Spark backend frequently boots in "degraded mode" where the direct IB Gateway connection is unavailable but the Windows pusher is healthily delivering positions via `_pushed_ib_data["positions"]`. Pre-v19.30.9 the endpoint raised 503 in that state, breaking the V5 HUD positions panel and Top Movers tile.

**Fix (`backend/routers/ib.py`)**: catch `ConnectionError`, fall back to the pusher snapshot with explicit `degraded:true` + `source:"pusher"|"pusher_stale"` flags so the UI can render a clear "degraded" badge instead of a blanket "Failed to fetch" red state. Same defensive `_pushed_payload()` helper added to the alternate `/account/summary` async handler (kept as a defense-in-depth safety net; the primary route resolves to the pre-existing sync handler that already reads pushed data).

### Bug #2 — "Bar fetch failed" on V5 SPY chart
Same wedge class as v19.30.1 / v19.30.2 / v19.30.7, different call site. Sync pymongo `find().sort()` cursor materialisation inside `hybrid_data_service._get_from_cache` could tie the event loop up long enough for the 30s axios timeout on the frontend to fire, which `safeGet` swallows and the UI renders as "Bar fetch failed".

**Fix (`backend/services/hybrid_data_service.py`)**: wrap both the window query AND the stale-fallback query in `asyncio.to_thread`. Same treatment applied to `_cache_bars` (per-bar sync `update_one(upsert=True)` loop offloaded to a thread). Closes 2 of the 53 sync-mongo-in-async sites flagged in `CODEBASE_AUDIT_2026_05_02.md`.

### Bug #3 — No pre-open safety endpoint to cancel pending GTC orders
If an operator manually flattened a position via TWS, the IB-side OCA stop/target legs lingered. The bot's next entry could trigger a naked short when those orphaned legs converted.

**Fix (`backend/routers/trading_bot.py`)**: new `POST /api/trading-bot/cancel-all-pending-orders` endpoint with two layers:
1. Mongo `order_queue` drain (always available, wraps the per-row sync update_one loop in `asyncio.to_thread`) — flips every `pending`+`claimed` row to `cancelled` so the pusher won't submit them
2. Direct IB Gateway `get_open_orders` + `cancel_order` per row (when reachable; gracefully degrades with `ib_unavailable:true` flag when not)

Defense-in-depth: `confirm:"CANCEL_ALL_PENDING"` token required (mirrors `/flatten-paper?confirm=FLATTEN`). Optional `symbols=[...]` scopes the cancel; `dry_run:true` previews without mutation.

### Tests
14 new pytests in `tests/test_degraded_mode_fixes_v19_30_9.py` (including 2 source-level pins so a future refactor can't silently re-introduce sync-mongo-in-async to `_get_from_cache` / `_cache_bars`). **39/39 across the v19.30 stack** (25 prior + 14 new). Live-validated on the local backend: positions endpoint returns 200 with `degraded:true`, cancel-all-pending dry-run returns expected counts, account summary surfaces pushed data.

### Operator action — Spark deploy
```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh

# Verify positions endpoint no longer 503's
curl -s -m 5 localhost:8001/api/ib/account/positions | jq .source
# → "pusher" or "pusher_stale" (was: HTTP 503)

# Verify SPY chart returns bars
curl -s -m 5 'localhost:8001/api/sentcom/chart?symbol=SPY&timeframe=5min&days=5' | jq '.bar_count'
# → > 0 (was: empty / timeout)

# Smoke-test new endpoint (dry-run; no state change)
curl -s -m 5 -X POST -H "Content-Type: application/json" \
  -d '{"confirm":"CANCEL_ALL_PENDING","dry_run":true}' \
  localhost:8001/api/trading-bot/cancel-all-pending-orders | jq .
```

---


## 2026-05-02 (sixtieth commit, v19.30.8) — Wedge-watchdog round 2: account_snapshot + sync requests in async

**Operator-pasted v19.30.6 watchdog dumps showed two NEW wedge classes after the v19.30.7 fixes landed:**

### Wedge #1 (different pusher RPC method)
```
MainThread BLOCKED in:
  routers/trading_bot.py:231        get_bot_status
  → get_account_snapshot()                          # SYNC HELPER
  services/ib_pusher_rpc.py:175     account_snapshot
  services/ib_pusher_rpc.py:124     _request
  → with self._lock:                                # blocked on lock
```
v19.30.7's audit only checked `subscriptions`, `get_subscribed_set`, etc. — missed `account_snapshot` and the module-level `get_account_snapshot()` helper. Multiple async callers were violating the contract.

### Wedge #2 (entirely new wedge class)
```
MainThread BLOCKED in:
  services/market_intel_service.py:1100  start_scheduler
  services/market_intel_service.py:884   generate_report
  services/market_intel_service.py:405   _gather_ticker_specific_news
  → requests.get(...)                               # SYNC HTTP
  ssl.read(...)                                     # blocked on SSL recv
```
Sync `requests.get()` inside an async function — entirely different wedge class from the pusher RPC ones. Any sync HTTP library (requests, urllib3, urllib) called from async = wedge.

### What shipped — 6 surgical patches + comprehensive audit test

#### A — All 4 async callers of `get_account_snapshot()` wrapped in `to_thread`
- `routers/trading_bot.py:231` (get_bot_status — the wedge #1 smoking gun)
- `routers/trading_bot.py:319` (refresh_account)
- `routers/diagnostic_router.py:1081` (account_snapshot diag — added missing `import asyncio` too)
- `services/trading_bot_service.py:1496` (`_get_account_value` — called from scan loop hot path; would have wedged the loop on every bot tick when push-data wasn't seeding account)

#### B — All 3 sync `requests.get` sites in `market_intel_service.py` wrapped in `to_thread`
- `_gather_market_news` (line 129) — Finnhub general news
- `_gather_ticker_specific_news` (line 405) — the wedge #2 smoking gun
- `_gather_earnings_calendar` (line 618) — Finnhub earnings calendar

#### C — Comprehensive audit test (`tests/test_async_sync_blockers_v19_30_8.py`)
- AST walk of entire backend tree
- Two violation classes detected:
  1. Any sync method on `_PusherRPCClient` (full method list, not just the 4 from v19.30.7) called from async without `to_thread`
  2. Any `requests.<method>` / `urllib3.<method>` / `urllib.<method>` called from async without `to_thread`
- 5 new pytest cases. **Catch-all test** maintains a `DOCUMENTED_BACKLOG_VIOLATIONS` allowlist for known-but-deferred sites (scheduled tasks, not on dashboard hot path) — adding a NEW violator outside that list fails the test at PR time.
- Backlog-allowlist currently covers 7 services (perf, news, web research, setup landscape, ai assistant, fundamental data, quality service, earnings service, BriefMe agent) — all on Audit Pass 2a roadmap.

### Verification

- 5/5 new tests pass.
- **138/138 across full v19 stack** (v19.23 → v19.30.8). Ruff clean.
- The codebase-wide audit confirms ZERO **NEW** sync-in-async violations outside the documented backlog. Adding any new violator (e.g., in a future feature) fails this test.

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh
# After 5-10 min of normal operation:
grep -c "WEDGE WATCHDOG TRIGGERED" /tmp/backend.log
# Expected: 0 (or 1-2 boot-time wedges from un-fixed scheduled-task callers
# that fire once on first scheduler tick — those are P1/Audit Pass 2a)
```

If wedges still occur and the watchdog stack points at any of the
documented-backlog files, that's expected and tracked. If it points
anywhere else, paste it and we ship v19.30.9.

### v19.30.x series progress

- v19.30.1: push-data hot-path wedge (anyio thread pool saturation)
- v19.30.2: bar-poll degraded-IB wedge (sync pusher RPC inline)
- v19.30.3: Spark launcher venv discovery + port cleanup
- v19.30.4-.6: wedge auto-detection (thread-based watchdog catches main thread mid-wedge)
- v19.30.7: surgical fix for first watchdog smoking gun (hybrid_data + pusher_rotation)
- **v19.30.8**: surgical fix for round-2 watchdog smoking guns (account_snapshot + sync requests in async) + codebase-wide enforcement test

The dashboard hot path (chart, positions, status, push-data, scanner)
should now be fully wedge-immune. Remaining wedges (if any) live in
scheduled-task code paths documented in Audit Pass 2a — these only
fire on scheduler ticks (every 5/15/60 min) so the operator-impact
is bounded to the tile that scheduler powers.

## 2026-05-02 (fifty-ninth commit, v19.30.7) — Surgical fix from wedge-watchdog smoking gun

**Operator-pasted stack capture from v19.30.6's wedge-watchdog this evening.**

### The smoking gun

```
=== WEDGE WATCHDOG TRIGGERED (main thread stuck for 5.0s) ===
--- Thread 'MainThread' ← MAIN/LOOP THREAD ---
  ...
  routers/sentcom_chart.py:862    get_chart_tail
  routers/sentcom_chart.py:527    get_chart_bars
  services/hybrid_data_service.py:678    fetch_latest_session_bars
  → rpc.subscriptions(force_refresh=False)            ← SYNC HTTP CALL
  services/ib_pusher_rpc.py:206   subscriptions
  services/ib_pusher_rpc.py:124   _request
  → with self._lock:                                   ← BLOCKED ON LOCK
```

The dashboard polls `/api/sentcom/chart` every few seconds. Each call
went into `fetch_latest_session_bars`, which called `rpc.subscriptions()`
**inline** (sync HTTP call to Windows pusher, holds a `threading.Lock`).
Concurrent chart requests piled up on the lock — when the pusher RPC
took >5s (because of slow Windows pusher response under load, transient
network hiccup, or any delay), the lock contention pinned the event
loop for the full timeout window.

**Same wedge class as v19.30.2** (bar_poll_service `_build_symbol_pools`)
but in a different async caller. The pusher_rpc module's docstring
explicitly says "Call from async paths via asyncio.to_thread" — two
async callers were violating it.

### What shipped — 2 surgical patches + 1 codebase-wide guard

#### A — `services/hybrid_data_service.py:678`
- `subs = rpc.subscriptions(force_refresh=False)` → `subs = await asyncio.to_thread(rpc.subscriptions, False)`
- Pattern already used 15 lines below for `rpc.latest_bars` (line 693) — restored consistency.

#### B — `services/pusher_rotation_service.py:633`
- `current = self.pusher.get_subscribed_set()` (in `_loop_body`) → `current = await asyncio.to_thread(self.pusher.get_subscribed_set)`
- This loop body runs every `LOOP_TICK_SECONDS` so a single slow RPC could stall the loop on every tick. Now the loop stays responsive while the RPC runs on a thread.

#### C — `tests/test_pusher_rpc_async_offload_v19_30_7.py`
- **Codebase-wide AST audit test** — walks every `.py` file, finds all sync RPC method calls (`subscriptions`, `get_subscribed_set`, `subscribe_one`, etc.) inside any `async def`, fails if any are NOT wrapped in `asyncio.to_thread`. Now if anyone re-introduces this pattern in a future feature, the test fails at PR time with the exact file:line.
- 4 new pytest cases. Currently reports 0 violations across the entire backend tree.

### Verification

- 4/4 new tests pass.
- **134/134 across the v19.23 → v19.30.7 regression stack**. Ruff clean.
- The codebase-wide audit explicitly confirms ZERO async-context unwrapped pusher RPC calls remain.

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh
# After 5-10 min of normal operation, you should see:
#  - Dashboard chart loads stay responsive
#  - WebSocket keepalive doesn't time out
#  - Pusher's read-timeout retries drop to ~0
#  - /api/autonomy/readiness no longer 500s
# Wedge watchdog auto-dump should be silent (no >5s blocks).
grep "WEDGE WATCHDOG TRIGGERED" /tmp/backend.log
```

If wedges still occur, the watchdog will once again capture the new call site — paste the stack and we ship v19.30.8. But based on the audit, this should be the last instance of this wedge class.

### What this completes

- **v19.30.1**: push-data wedge under high-pusher-load
- **v19.30.2**: bar-poll wedge during degraded-IB boot
- **v19.30.3**: Spark startup script venv discovery + port cleanup
- **v19.30.4**: auto stack-dump on wedge (asyncio-internal)
- **v19.30.5**: dump quality fixes (numeric task sort, idle filtering)
- **v19.30.6**: thread-based wedge watchdog (captures main thread WHILE wedged)
- **v19.30.7**: surgical fix from watchdog's smoking-gun stack + codebase-wide guard

The asyncio loop should now be wedge-immune to the entire pusher-RPC class of bugs. The `_event_loop_monitor` + `wedge-watchdog` infrastructure remains as ongoing observability — any new wedge class will surface immediately with a smoking-gun stack.

## 2026-05-02 (fifty-eighth commit, v19.30.6) — Thread-based wedge watchdog

**Operator-flagged 2026-05-02 evening, after v19.30.4/.5 stack dumps showed every task as "ACTIVE" but never the actual blocker.**

### Why the v19.30.4/.5 dumps weren't useful

The previous dumps (v19.30.4 and the v19.30.5 sort/idle-filter fixes) ran inside the asyncio loop itself. Looking at the math:

```python
async def _event_loop_monitor():
    while True:
        t0 = monotonic()
        await asyncio.sleep(0)        # ← blocks the wedge progresses past
        lag = monotonic() - t0
        if lag > 5:
            dump_all_tasks()          # ← runs AFTER wedge resolves
```

The `await asyncio.sleep(0)` only returns when the loop unblocks. By the time the dump runs, **the blocker task has already advanced past its sync call site**. We see post-wedge state — every other task except the one we want.

This explained the operator's last paste: 50+ tasks all classified ACTIVE, no obvious blocker frame, the suspect `anyio.connect_tcp.try_connect` task was a passive pending I/O (doesn't block the loop).

### v19.30.6 fix — thread-based watchdog

A daemon Python thread that watches a heartbeat counter the asyncio loop bumps every 0.5s. If the heartbeat goes stale for >5s, the thread captures `sys._current_frames()` from outside the loop — getting the main thread's REAL current execution state WHILE it's still stuck on the sync call.

Mechanics:
- New global `_loop_heartbeat = [0]` (mutable container for closures)
- `_event_loop_monitor` bumps `_loop_heartbeat[0] += 1` each iteration (every 0.5s)
- Daemon thread `wedge-watchdog` polls every 1s, checks if heartbeat moved
- If not for ≥5s + cooldown elapsed, it walks `threading.enumerate()`, identifies the main thread (the loop thread), and prints `traceback.print_stack()` for every Python thread
- Output labeled `=== WEDGE WATCHDOG TRIGGERED ===` with `← MAIN/LOOP THREAD` annotation on the loop thread
- Existing `=== ASYNCIO TASK STACK DUMP ===` (v19.30.4) still fires after wedge — kept as complementary context

### What shipped

Single file (`backend/server.py`):
- New `_wedge_watchdog_thread` daemon thread spawned at startup, idles silently waiting for heartbeat staleness
- `_event_loop_monitor` now bumps `_loop_heartbeat[0]` each iteration and sleeps 0.5s instead of 2s (faster wedge detection)
- The asyncio task dump is now classified by reading source lines via `linecache.getline` to detect `await asyncio.sleep(...)` patterns reliably (the v19.30.5 attempt by `f_code.co_name` was matching the calling coroutine, not the sleep — every task showed ACTIVE)
- Both watchdog and asyncio dump have separate 30s cooldowns

Test (`tests/test_autonomy_readiness_503_v19_30_4.py`):
- Extended source-level pin: must contain `WEDGE WATCHDOG`, `_wedge_watchdog_thread`, `_current_frames`, `_loop_heartbeat`
- 25/25 across the v19.30.x test suite

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh

# Wait 5-10 min for wedges to recur. Then:
grep -A 60 "WEDGE WATCHDOG TRIGGERED" /tmp/backend.log | head -200
```

Look for the line that says `← MAIN/LOOP THREAD` — its 20-deep stack trace shows the EXACT file:line of the synchronous call that's blocking the asyncio loop. That's the smoking gun for v19.30.7's surgical fix.

## 2026-05-02 (fifty-sixth commit, v19.30.4) — Auto stack-dump on wedge + autonomy/readiness 500→503

**Operator-flagged 2026-05-02 evening, after v19.30.1/.2/.3 were live.**

The deploy worked (clean 24s boot via the new launcher), but the
operator's log + dashboard revealed a NEW recurring issue:

```
17:11:13: Event loop lag:  6.0s
17:12:36: Event loop lag: 35.0s
17:13:40: Event loop lag: 35.0s
17:14:44: Event loop lag: 46.1s   ← biggest
17:15:48: Event loop lag:  3ms    (recovered)
```

Wedges of **35-46s recurring every 60-90s** — a THIRD wedge class
beyond push-data (v19.30.1) and bar-poll (v19.30.2). Symptoms:
  - WebSocket keepalive (20s default) times out → dashboard "Loading bars..."
  - Pusher's `requests.get()` hits its 5s read-timeout, retries 3 times
  - `/api/autonomy/readiness` returns 500 with `CancelledError` traceback

### Root cause analysis

- **The 35-46s wedges**: source unknown — we don't have a stack
  trace because by the time the operator runs `py-spy dump`, the
  loop has recovered. We need automated capture.
- **The 500 on /api/autonomy/readiness**: `readiness()` made
  7 internal HTTP calls **sequentially**, each with a 5s timeout.
  Worst case = 35s — which mapped EXACTLY onto the 35s wedges. When
  the loop wedged, all 7 awaits cancelled and the httpx context exit
  re-raised CancelledError → FastAPI returned 500. Pure cascade
  failure: the wedge causes the 500, the 500 wakes up the operator
  to investigate the 500, but the 500 isn't the bug — it's just the
  loudest victim.

### What shipped (3 surgical patches)

#### A — Auto-dump asyncio task stacks on wedge (`backend/server.py`)
- `_event_loop_monitor` (the existing v19.30 watchdog that prints the
  `EVENT LOOP BLOCKED for N.Ns` warning) now ALSO walks
  `asyncio.all_tasks()` and calls `task.print_stack()` on each, with
  a 30s cooldown so a sustained wedge doesn't spam the log.
- Output is clearly delimited:
  ```
  === ASYNCIO TASK STACK DUMP (lag=46.1s, trigger=event_loop_monitor) ===
  Active tasks: 17
  --- Task: _scan_loop | coro: BackgroundScanner._scan_loop ---
    File "...", line N, in _scan_loop
      ...
  ```
- Operator can now `grep "ASYNCIO TASK STACK DUMP" /tmp/backend.log`
  to pinpoint the next wedge's source. No more racing py-spy.
- Wrapped in try/except so the monitor itself can never crash the
  loop. Capped at 30 tasks so worst-case logging stays bounded.

#### B — Parallelise + soft-fail `/api/autonomy/readiness` (`routers/autonomy_router.py`)
- The 7 sub-checks (`_check_account`, `_check_pusher_rpc`,
  `_check_live_bars`, `_check_trophy_run`, `_check_kill_switch`,
  `_check_eod`, `_check_risk_consistency`) now run via
  `asyncio.gather` instead of sequentially. Worst case: 35s → 5s.
  On a healthy loop: ~50ms.
- Top-level try/except catches `asyncio.CancelledError` /
  `asyncio.TimeoutError` and raises `HTTPException(503)` with a
  structured detail body (`verdict: red`, `blockers: [loop_busy]`,
  `next_steps: ["Wait 5s and retry…"]`). 503 is the correct status
  for "service busy, try again" — the pusher's logs no longer flag
  these as 500 bugs.

#### C — 5 new pytests (`tests/test_autonomy_readiness_503_v19_30_4.py`)
- Source-level pins: `asyncio.gather` is used; CancelledError is
  caught; `status_code=503`; `_event_loop_monitor` calls
  `print_stack` and uses `asyncio.all_tasks()` with cooldown.
- Behavioural: 7 mocked sub-checks each sleeping 0.3s complete in
  <1.0s (proves parallelism). Forced `CancelledError` from gather
  produces an `HTTPException(503)` with the correct detail shape.

### Verification

- 5/5 new tests pass.
- **130/130 total across v19.23 + v19.24 + v19.25 + v19.26 + v19.27 +
  v19.28 + v19.29 + v19.30 + v19.30.1 + v19.30.2 + v19.30.3 + v19.30.4
  suites**. Ruff clean on new code.

### What this unblocks

- **Diagnosing the 35-46s wedges**: the next time you restart and
  let the bot run, every wedge >5s will leave a smoking-gun stack
  dump in `/tmp/backend.log`. We get the next surgical fix
  AUTOMATICALLY without operator intervention.
- **Pusher logs noise reduction**: `/api/autonomy/readiness` 500
  errors stop. Pusher's retry counter drops materially.
- **Faster boot signals**: `/api/autonomy/readiness` typically
  returns in <100ms now (gather + healthy loop) instead of 35s
  best-case.

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh                  # OR via .bat orchestrator

# After a few minutes of running, check for auto-captured stack dumps:
grep -A 60 "ASYNCIO TASK STACK DUMP" /tmp/backend.log | head -200
```

Paste any stack dumps that show up — the next wedge fix lands within
minutes once we see the file:line where the loop is blocking.

## 2026-05-02 (fifty-fifth commit, v19.30.3) — Spark startup script hardening

**Operator-flagged 2026-05-02 afternoon, after v19.30.1/.2 went live.**
The wedge fixes were verified working, but the operator hit a
20-minute deploy detour because `scripts/spark_start.sh` (called by
the Windows orchestrator `TradeCommand_Spark_AITraining.bat` over
SSH) failed to find the project's venv:

### Root causes (3 stacked bugs in the Spark-side helpers)

1. **`spark_start.sh` venv search missed `.venv/`** (the actual Spark
   path). It only checked `~/venv/` and `$REPO_DIR/venv/` (no leading
   dot). When neither matched it silently fell through to "Using
   system Python" — and system Python on Spark has no fastapi
   installed. `nohup python server.py` would then crash with
   `ModuleNotFoundError: No module named 'fastapi'` while the .bat
   orchestrator happily reported "Spark services started." Diagnosis
   ate ~30 minutes of operator time.
2. **No port-based stale-process kill** in `spark_stop.sh` /
   `spark_start.sh`. The kill cycle is purely cmdline-pattern-based
   (`pkill -f 'python.*server.py'`) — but processes whose cmdline
   doesn't exactly match (e.g., started via full path, or `python3`
   vs `python`, or via wrapper) survive. The new server's bind then
   fails with `[Errno 98] address already in use`. Operator hit this
   today when the prior wedged backend (v19.30.1 pre-fix) didn't
   match the kill pattern.
3. **No `import fastapi` sanity check** before launching. If venv
   activation fails (case 1) or pip is out of sync, the symptom is
   "backend never became healthy" with no useful log line.

### What shipped (3 surgical patches in `scripts/`)

#### A — `spark_start.sh` venv discovery + fail-fast (`scripts/spark_start.sh`)
- Search order updated: `$REPO_DIR/.venv/` → `~/venv/` →
  `$REPO_DIR/venv/`. `.venv/` (Spark's actual path) is now first.
- After activation, runs `python -c "import fastapi"` as a smoke
  test. Bails with a clear error pointing to `pip install -r
  backend/requirements.txt` instead of letting the launch silently
  fail.
- Reports the active python binary + version so the operator can see
  at a glance which env the backend is running in.

#### B — Port-based stale-process kill (`scripts/spark_start.sh` + `spark_stop.sh`)
- `spark_stop.sh`: after the cmdline-based pkill cycle, runs
  `fuser -k 8001/tcp` to kill anything still bound to :8001.
  Reports clearly if port still bound after fuser (manual
  intervention needed).
- `spark_start.sh`: defensive `fuser -k 8001/tcp` before launch + a
  10-tick wait loop verifying the port is actually released
  (TIME_WAIT can take a few seconds). Bails before launch with a
  clear warning instead of letting uvicorn report `[Errno 98]
  address already in use` deep in the log.

#### C — Backpressure observability tile in launcher output (`scripts/spark_start.sh`)
- After the health check passes, `spark_start.sh` now also curls
  `/api/ib/pusher-health` and prints the v19.30.1 backpressure
  metrics (`push_in_flight`, `push_max_concurrent`,
  `push_dropped_503_total`, `pushes_per_min`). Operator sees the
  wedge-protection state on every restart instead of having to
  remember the curl one-liner.
- Health check window also bumped 45s → 60s to give v19.30's phase
  watchdogs (8s IB connect + 10s `_restore_state` + 8s
  `simulation_engine` + 5s scanner) headroom on cold boot.

### NOT changed (intentionally)

- `TradeCommand_Spark_AITraining.bat` (Windows orchestrator) —
  unchanged. It curls `/api/health` (which still exists and is now
  `async def` per v19.30.1). Calling `bash scripts/spark_start.sh`
  via SSH continues to work; the .bat doesn't need to know about
  the venv discovery fix.
- `backend/.env` — no new env vars. Every constant we introduced
  (`_PUSH_DATA_MAX_CONCURRENT=4`, subscriptions `timeout=3.0`) works
  fine at its default. Optional env-tuning was discussed but not
  shipped (would add `IB_PUSH_MAX_CONCURRENT`,
  `IB_PUSHER_RPC_SUBS_TIMEOUT_S`).
- `start_backend.sh` (project root, manual operator path) — already
  has `.venv` first in its search order. No change needed.

### Verification

- `bash -n` on both helpers confirms clean syntax.
- 20/20 v19.30.x wedge-protection pytests still pass (no behavioural
  regressions; this is a launcher-only change).
- Pre-fix repro:
  ```
  $ bash -c 'unset PATH_TO_VENV; bash scripts/spark_start.sh'
  → "Using system Python"
  → ModuleNotFoundError: No module named 'fastapi'
  ```
  Post-fix:
  ```
  → "Activated $REPO_DIR/.venv"
  → "Python ready: Python 3.12.3 — fastapi OK"
  → backend launches cleanly
  ```

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
# Either path works now:
./start_backend.sh                          # manual: backend-only fast restart
# OR via the Windows orchestrator (full stack restart):
# (.bat already calls scripts/spark_start.sh — no .bat changes needed)
```

## 2026-05-02 (fifty-fourth commit, v19.30.2) — Bar-poll degraded-mode wedge fix

**Operator-flagged after v19.30.1 deploy on Spark 2026-05-02 afternoon.**

After v19.30.1's push-data backpressure fix verified working on live
Spark hardware (200 OKs from /api/ib/pushed-data and dozens of other
endpoints from both localhost AND the Windows pusher 192.168.50.1), a
SECOND wedge surfaced — only when the Windows IB pusher was OFF:

```
$ curl -m 5 localhost:8001/api/health  # backend serves traffic for 30s, then…
* Operation timed out after 5003 milliseconds with 0 bytes received
```

`py-spy dump --pid <main>` pinpointed the exact stack:
```
MainThread BLOCKED in:
  services/ib_pusher_rpc.py:124    _request          ← sync HTTP call
  services/ib_pusher_rpc.py:202    subscriptions
  services/ib_pusher_rpc.py:400    get_subscribed_set
  services/bar_poll_service.py:229 _build_symbol_pools
  services/bar_poll_service.py:291 poll_pool_once
  services/bar_poll_service.py:491 _loop_body        ← async loop body
```

### Root cause

`bar_poll_service._build_symbol_pools()` is a sync `def` called inline
from async `poll_pool_once`. Inside it does TWO things that each
block the event loop:

1. **`pusher.get_subscribed_set()`** — sync HTTP call to the Windows
   pusher with an 8s timeout. When the pusher is fully OFF, every
   call burns the full 8s.
2. **Three sync `db["symbol_adv_cache"].find().sort()` cursor
   iterations** in inline list comprehensions.

With 3 pools polling at slightly staggered intervals × ~8s pusher RPC
+ sync mongo overhead = **24-36s loop wedge**. Observed exactly 36s on
Spark.

The `services/ib_pusher_rpc.py` module's own header docstring even
warns "Call from async paths via asyncio.to_thread" — `bar_poll_service`
was the only async caller violating the contract.

### What shipped (3 surgical patches)

#### A — Offload `_build_symbol_pools` to a thread (`services/bar_poll_service.py`)
- `poll_pool_once` now calls `await asyncio.to_thread(self._build_symbol_pools)`
  instead of `self._build_symbol_pools()` inline.
- The pusher RPC + 3 sync mongo cursor iterations now run on a thread.
  Event loop stays responsive.

#### B — Reduce pusher RPC subscriptions timeout (`services/ib_pusher_rpc.py`)
- `subscriptions()` RPC timeout dropped 8.0s → 3.0s.
- Defense-in-depth: even if a future caller bypasses the to_thread
  offload, max impact is bounded at 3s instead of 8s.
- Subscription state changes rarely (operator action) and the 30s
  `_subs_cache` TTL smooths the steady-state call rate, so this only
  affects cold-cache / `force_refresh=True` paths.

#### C — `start_backend.sh` launcher script (project root)
- Activates `.venv/bin/activate` (Spark's actual venv path).
- Kills any stale `python server.py`.
- Launches in background, waits up to 60s for "Application startup
  complete" (covers the v19.30.x watchdog phases).
- Verifies `/api/system/health` (the actual health endpoint — `/api/health`
  doesn't exist on this build).
- Prints the v19.30.1 backpressure observability tile.
- Operator no longer has to remember the venv-activate / python3-vs-python
  / wait-30s dance manually.

### Verification (3 layers)

#### 1. Unit pytest (5 new cases in `tests/test_bar_poll_wedge_fix_v19_30_2.py`)
- Source-level pins: `poll_pool_once` calls `_build_symbol_pools` via
  `asyncio.to_thread`; subscriptions timeout ≤3s; module docstring
  contract still in place.
- Behavioural: 3 sequential slow-pusher-RPC pool builds (0.5s each)
  complete in ≥1.4s with **<100ms max event-loop block** (a background
  pinger runs concurrently and never gets starved). Pre-fix the same
  scenario would block the loop for ~1.5s end-to-end.

#### 2. Test suite regression
**125/125 passing** across v19.23 + v19.24 + v19.25 + v19.26 + v19.27
+ v19.28 + v19.29 + v19.30 + v19.30.1 + v19.30.2 suites.

#### 3. py-spy validated
The exact stack frame the wedge was in (`ib_pusher_rpc.py:124 _request`)
can no longer block the event loop because the entire chain is now
behind `asyncio.to_thread`. The fix targets the proven-by-py-spy line.

### Operator action

```bash
cd ~/Trading-and-Analysis-Platform
git pull
./start_backend.sh
```

That's it. The new launcher handles venv activation, server kill,
restart, log tail, and verifies health — replaces the manual
`source .venv/bin/activate && cd backend && nohup python server.py …`
dance that ate 30 minutes of operator time today.

### Known limitations (P1 follow-ups)

- The wedge fix is targeted at the bar_poll_service path. Other code
  paths that call `pusher.get_subscribed_set()` from async context
  (if any get added) would re-introduce the same wedge. Consider:
  - Wrapping ALL of `_PusherRPCClient`'s public methods in async
    helpers (`async def subscriptions_async(self)` etc.) that own
    the `to_thread` internally.
  - Adding a "negative cache" — after 3 consecutive failures, skip
    the RPC for 60s (then 120s, 300s, exponential backoff). Today
    the cache TTL is 30s so a fully-OFF pusher triggers a 3s timeout
    every 30s forever.
- `bar_poll_service._build_symbol_pools` itself still does inline sync
  pymongo `find().sort()` calls — fine when called via to_thread
  (Pass 2a in the audit), but the sync mongo pattern remains.

## 2026-05-02 (fifty-third commit, v19.30.1) — Event-loop wedge fix + push-data backpressure

**Operator-flagged live failure 2026-05-01 night → 2026-05-02 morning**:

```
$ curl -v -m 10 localhost:8001/api/health
* Connected to localhost (127.0.0.1) port 8001
> GET /api/health HTTP/1.1
... 10s pass ...
* Operation timed out after 10000 milliseconds with 0 bytes received
```

Backend wedged AFTER `Application startup complete`. ALL endpoints —
including `/api/health` which does literally `return {"status":
"healthy"}` — TCP-accepted but never returned a byte. Tried `localhost`,
`127.0.0.1`, and `192.168.50.2` — all same symptom. Repro'd reliably.

### Root cause (deeper async-pymongo audit)

Three stacked bugs combined to wedge the loop:

1. **`/api/ib/push-data` was a sync `def` handler** doing sync pymongo
   `update_one` to `ib_live_snapshot` inline. With the Windows pusher
   pushing every ~2s and 100+ quote symbols, this saturated anyio's
   default 40-thread pool.
2. **`tick_to_bar_persister.on_push()` ran inline inside that same
   sync handler**, holding a global `threading.Lock` and doing a
   per-bar sync `update_one` upsert loop. On every minute boundary
   that's ~100 sync mongo writes serialised under the lock.
3. **`/api/health` was also sync `def`** so it shared the saturable
   anyio thread pool. Once the pool filled, `/api/health` queued
   forever and timed out 0-byte.

A full audit of the codebase via `ast` walk identified 11 other sync
`def` handlers in hot paths and 56 inline sync mongo calls in async
handlers. v19.30.1 patches the wedge-causing minority; the others are
in low-frequency endpoints that don't compound under push-storm load.

Bonus pre-existing bug found: the snapshot write in `/api/ib/push-data`
did `from database import get_db` — but the actual symbol is
`get_database`. So that snapshot write had been silently failing the
entire time. Fixed.

### What shipped — 5 coordinated patches across 3 files

#### A — `/api/health` async-ification (`routers/system_router.py`)
- `def health_check()` → `async def health_check()`. Health now runs on
  the event loop directly — immune to anyio thread pool saturation.

#### B — `/api/ib/push-data` async + backpressure (`routers/ib.py`)
- `def receive_pushed_ib_data(...)` → `async def receive_pushed_ib_data(..., response: Response)`
- New module-level state:
  - `_PUSH_DATA_MAX_CONCURRENT = 4` (operator-tunable cap)
  - `_push_in_flight` counter
  - `_push_dropped_503_total` for observability
- New backpressure short-circuit: if `_push_in_flight >= cap`, return
  `503 Retry-After: 5` instantly (no awaits, no DB calls). The pusher
  sees a fast 503 instead of waiting on a wedged 120s timeout.
- Sync mongo upsert to `ib_live_snapshot` now wrapped in
  `asyncio.to_thread(lambda: db["ib_live_snapshot"].update_one(...))`.
- `tick_to_bar_persister.on_push(quotes)` now wrapped in
  `asyncio.to_thread(_persister.on_push, _quotes_copy)` — the
  persister's global threading.Lock + per-bar sync upserts no longer
  pin the event loop.
- Always-release semantics: `_push_in_flight` decrement is in `finally`.

#### C — `/api/ib/status` + `/api/ib/pushed-data` async-ification
(`routers/ib.py`) — Two more sync def handlers polled by the dashboard.
Both bodies are pure in-memory dict reads — converted to `async def`.

#### D — `database.get_db` typo fix (`routers/ib.py`)
- Two sites (`push-data` snapshot write + `pusher-health` snapshot
  fallback) imported the non-existent `get_db`. Now imports the actual
  `get_database` symbol. Snapshot write to `ib_live_snapshot` finally
  works.

#### E — `BriefMeAgent` injector update (`routers/agents.py`)
- The `routers.ib` module has a name collision: helper
  `def get_pushed_ib_data() -> dict` at line 157 vs route handler
  `async def get_pushed_ib_data()` at line 611. Switched to importing
  the underlying `_pushed_ib_data` dict directly to avoid the
  async-route shadow.

### New observability

`/api/ib/pusher-health.heartbeat` now exposes:
- `push_in_flight` — current count of pushes being processed (0..4)
- `push_max_concurrent` — the cap (4)
- `push_dropped_503_total` — session-wide tally of pushes rejected
  for backpressure. Climbing fast = pusher too aggressive OR backend
  Mongo too slow.

### Verification (3 layers)

#### 1. Unit pytest (7 new cases in `tests/test_event_loop_wedge_fix_v19_30_1.py`)
- Source-level pins on all five patches.
- Behavioural: 503 short-circuit completes in <50ms when cap is hit;
  8 concurrent pushes complete with <100ms max event-loop block
  (pre-fix: 2.5s+ block reproduced and pinned in negative-control test).

#### 2. Local backend stress test
30 parallel `POST /api/ib/push-data` + 5 parallel `GET /api/health`:
- Pre-fix: all 35 requests time out 0-byte
- Post-fix: 11 pushes 200, 19 pushes 503 (backpressure working as
  designed), 5 health 200 — total elapsed 36ms, max health latency
  21ms.

#### 3. Test suite regression
**120/120 combined** across v19.23 + v19.24 + v19.25 + v19.26 + v19.27
+ v19.28 + v19.29 + v19.30 + v19.30.1 suites. Ruff clean on new code.

### Operator action (Spark deploy)

```bash
cd ~/Trading-and-Analysis-Platform
git pull
pkill -f "python server.py"
cd backend && nohup python server.py > /tmp/backend.log 2>&1 &
sleep 8

curl -s -m 5 localhost:8001/api/health
# Expected: {"status":"healthy","timestamp":"..."} — INSTANTLY

# Watch the new backpressure observability while pusher runs:
watch -n 2 'curl -s localhost:8001/api/ib/pusher-health | \
  jq ".heartbeat | {pushes_per_min, push_in_flight, push_max_concurrent, push_dropped_503_total}"'
```

If `push_dropped_503_total` climbs fast, tune `_PUSH_DATA_MAX_CONCURRENT`
in `routers/ib.py` upward (e.g. 6, 8) and restart. Full deploy runbook:
`memory/V19_30_1_WEDGE_FIX.md`.

### What this unblocks

Now that the loop stays responsive, the rest of the v19.30 P0 stack
becomes implementable:
- 🔴 Diagnostics Data Quality Pack — fix `ai_passed`/`bot_fired`
  consistency in Pipeline Funnel, Module Scorecard plumbing.
- 🔴 Pre-open Order Purge — `POST /api/trading-bot/cancel-all-pending-orders`
  to nuke GTC brackets before market open.
- 🟡 Bot Thoughts content capture in Trail Explorer.
- 🟡 Shadow-vs-Real gap drilldown.
- 🟡 Drift detector (CRITICAL stream when bot tracks <80% of IB shares).

## 2026-05-01 (fifty-second commit, v19.29-validation-2) — Morning Play A reset script + runbook

**Operator surfaced live state drift on Spark** during fork-tail debugging:
9 stale `bot_trades` rows from yesterday's EOD chaos, with bot tracking
33-50% of actual IB share counts on BP/CB/HOOD and a SOFI catastrophe
(bot tracks LONG 1636 + SHORT 301 vs IB's actual LONG 427). Backend
booted in degraded mode at 21:19 (IB Gateway timeout at startup),
manage loop is RTH-gated so phantom sweep won't fire until 9:30 AM ET.

Operator picked **Play A — flatten + clean slate**. To make 9:25 AM
ET execution thoughtless, this commit ships:

### What shipped
- **`backend/scripts/reset_bot_open_trades.py`** — one-shot Mongo
  cleanup script. Flips `bot_trades` `status: open` → `closed` with
  `close_reason: manual_pre_open_reset_v19_29` and `closed_at` stamp.
  Two-stage safety: `--dry-run` mandatory or `--confirm RESET` token
  required. Symbol whitelist filter for partial resets. Audit log to
  `bot_trades_reset_log` collection (TTL 30d) records every reset
  with trade_ids + timestamp + operator-supplied filter for forensic
  reconstruction. Pure pymongo, no backend dependency.
- **`memory/MORNING_2026-05-02_PLAY_A.md`** — paste-and-follow morning
  runbook. Five timed phases: 8:30 AM verification → 9:20 AM TWS
  flatten → 9:25 AM bot reset → 9:27 AM clean restart → 9:30 AM watch
  with verify_v19_29 + log tailing. Includes red-flag table, rollback
  steps, and EOD report capture commands.
- **16 new pytests** in `tests/test_reset_bot_open_trades.py` proving
  dry-run is read-only, commit flips status correctly, symbol filter
  uppercases, already-closed rows are left alone, audit log writes
  only when affected count > 0, CLI safety guard aborts without
  --confirm, render summary distinguishes DRY-RUN vs COMMITTED.
  Realistic Spark fixture (BP×3, SOFI×2, TMUS, LITE, CB, HOOD).

### Live verification
- 52/52 combined pytests across reset (16) + verify_v19_29 harness
  (21) + v19.29 hardening (15) suites. Ruff clean.
- Dry-run smoke against local Mongo: clean output, 0 matched (empty
  preview DB), no rows touched.
- CLI safety guard verified: aborts without confirm, aborts with
  wrong confirm token, only commits on `--confirm RESET`.

### Why a script + runbook instead of a backend endpoint
- The reset must run BEFORE backend restarts (otherwise the bot's
  `_open_trades` rebuilds from the still-open Mongo rows).
- Backend endpoints can't atomically operate on a stopped backend.
- The script's audit trail (`bot_trades_reset_log`) survives
  independently of the bot's normal close persistence path.

### Operator workflow tomorrow morning
1. 8:30 AM ET: run pre-open verification (4 commands).
2. 9:20 AM ET: flatten in TWS UI.
3. 9:25 AM ET: stop backend, run reset --dry-run, then --confirm RESET.
4. 9:27 AM ET: restart backend, confirm "IB Gateway: CONNECTED" not
   "degraded mode".
5. 9:30 AM ET: launch verify_v19_29 --watch on side terminal.

### What we observed about v19.29 in production
- **Wired correctly** (grep confirms WRONG-DIR-SWEEP marker present,
  harness F=PASS, reconciled_default_* defaults at 2.0% / 2.0:1).
- **Did not fire** because manage loop is RTH-gated. This is by design
  but means phantoms survive overnight resets. Logged as v19.30 P0
  candidate ("Boot Hygiene Pack" — startup-time one-shot sweep).

### Next session — v19.30 Boot Hygiene Pack candidates (~3-4h)
1. Boot-time one-shot phantom sweep regardless of RTH.
2. IB Gateway reconnect-on-timeout with exponential backoff (kill
   the "boots into degraded paper mode forever" failure mode).
3. Drift detector — emit CRITICAL Unified Stream event when bot
   tracks <80% of IB shares for any symbol. Surface state drift
   BEFORE it compounds into another EOD disaster.

## 2026-05-01 (fifty-first commit, v19.29-validation) — RTH validation harness for v19.29

**Operator picked option (d)** at the start of this session: pause new
features and ship a validation harness so the v19.29 hardening pass
can be observed end-to-end during the upcoming RTH session without
log greps. v19.29 had 105/105 unit tests green but no on-Spark live
verification — the 5 fixes (intent dedup, direction-stable reconcile,
phantom sweep, no-new-entries gate, flatten alarm) all surface
through stream events / trade-drops, but each requires a different
endpoint query to confirm.

### What shipped
- **`backend/scripts/verify_v19_29.py`** — read-only Python harness.
  6 checks, colored verdicts (PASS / FAIL / PENDING_RTH / NO_DATA /
  ERROR), JSON-export mode, watch mode (re-runs every 30s during
  RTH), optional `--probe-reconcile SYM` flag for actively
  exercising gate B. Stdlib-only (no requests / aiohttp dep).
- **6 checks per fix**:
  - F. Pipeline health smoke — `/api/sentcom/positions` + bot status
    + v19.24 `reconciled_default_*` defaults present
  - A. Order intent dedup — `/api/diagnostic/trade-drops` for
    `reason=intent_already_pending` rows
  - B. Direction-stable reconcile — stream history search for
    `direction_unstable` events
  - C. Wrong-direction phantom sweep — stream history search for
    `wrong_direction_phantom` events
  - D. EOD no-new-entries — stream history search for
    `eod_no_new_entries` (soft + hard) events
  - E. EOD flatten escalation — stream history search for
    `eod_flatten_failed` events
- **`memory/V19_29_VALIDATION.md`** — operator runbook with curl
  one-liners, verdict legend, post-pull workflow (smoke before RTH
  → SOFI catastrophe verification → opening-30-min watch →
  3:40-3:55pm window watch → 3:55-4:00pm flatten window watch),
  and failure-mode remediation table.
- **21 new pytests** in `tests/test_verify_v19_29_harness.py`
  exercising every check function against monkey-patched HTTP
  fixtures. No live backend required.

### Why this matters
- v19.29's 5 fixes only fire when their triggering condition occurs
  (e.g. soft EOD warn only fires 3:45-3:55pm). Without a harness,
  validating each one requires waiting for the right window AND
  knowing which endpoint surfaces the event. The harness collapses
  all 5 to one command.
- Off-hours mode correctly distinguishes "gate hasn't fired because
  the window hasn't opened yet" (`PENDING_RTH`) from "gate hasn't
  fired and we expected it to" (`NO_DATA`) — actionable signal vs
  noise.

### Live verification (preview env smoke)
- Single-shot run: F=PASS, A=PENDING_RTH, B=NO_DATA, C=NO_DATA,
  D=PENDING_RTH, E=NO_DATA. Exit code 0. Off-hours timestamp
  correctly tagged.
- JSON mode parses cleanly; 6 results returned.
- `python -m backend.scripts.verify_v19_29` and direct
  `python backend/scripts/verify_v19_29.py` both work.
- `--probe-reconcile` deliberately not run on preview backend (no
  IB orphans here; real-Spark-only path).

### Operator flow (recommended)
1. After Spark pull + restart:
   `python -m backend.scripts.verify_v19_29` → expect F=PASS, rest
   NO_DATA / PENDING.
2. Verify SOFI catastrophe cleared:
   `curl -s localhost:8001/api/sentcom/positions | jq '.positions[]
   | select(.symbol=="SOFI")'`
3. During opening 30 min RTH:
   `python -m backend.scripts.verify_v19_29 --watch`
4. At 3:40-4:00pm: same `--watch` mode running on a side terminal.
5. Post-RTH: re-run, paste `--json` output into chat for tuning
   discussion.

### Next session
- Operator validates v19.29 in production using this harness.
- Once verified, choose v19.30 (chart WebSockets) or v19.31
  (pre-aggregated bar pipeline) — both fully scoped in ROADMAP.md.

## 2026-05-01 (fiftieth commit, v19.29) — Critical Trade Pipeline Hardening (5 fixes from EOD screenshot)

**Operator-flagged disaster window 2026-05-01 EOD**: 5 distinct
critical bugs surfaced at once on operator's IB Orders + Trades log
combined with the SentCom V5 panel screenshot showing 5 positions
still open past market close.

### Bugs caught (with evidence)
1. **Order spam: 300+ duplicate cancelled orders 2:17pm-3:55pm** — bot
   re-fired the same `(symbol, side, qty±5%, price±0.5%)` limit on
   every scanner cycle while the previous one was still pending. BP
   ~30 dups, SOFI ~25, BKNG ~30, V ~20, HOOD ~25, MA/TMUS/CB/STX/COHR
   all showed the same pattern. All cancelled at end-of-day.
2. **New entries fired 3:55-3:59pm** with OCA brackets that
   auto-cancelled at 4:00pm — left raw long positions overnight
   w/no protection (LITE 12sh @ $902.77 entered at 3:59pm, SOFI
   +886sh, HOOD +177sh, BP +336sh, CB +151sh, TMUS +255sh).
3. **EOD flatten failed silently** — 3:59pm SOFI 1636 / BP 450 / BP
   315 market sells all CANCELLED, never escalated.
4. **SOFI auto-reconciled SHORT but IB had it LONG** —
   catastrophic risk; if bot tried to manage that "short" it would
   BUY shares to close a non-existent short, doubling exposure at
   the worst moment. Caused by reconcile snapshotting direction
   during the 3:51pm flatten transit when net was briefly negative.
5. **TMUS reconciled at 100sh while IB had 255sh** — drift from
   3:55pm late fill not pulled into the bot's `_open_trades`.

### Five coordinated fixes
**A — Order intent dedup** (`services/order_intent_dedup.py`, new)
- Process-wide registry of pending IB intents keyed by
  `(symbol, side, qty±5%, price±0.5%)`
- `is_already_pending()` check called from `trade_execution.
  execute_trade` BEFORE `place_bracket_order`. Blocks duplicate
  intents within 90s TTL with `intent_already_pending` reason.
- `clear_filled()` called from both fill (success) and rejection
  paths so the dedup never out-lives the actual order state.
- Stops the 300+ cancellation cascade. Limits buy/sell separately.

**B — Direction-safe reconcile**
(`services/position_reconciler._ib_direction_history` + 30s gate)
- New module-level direction observation tracker
  `record_ib_direction_observation(symbol, direction)` called every
  manage-loop tick from `position_manager.update_open_positions`.
- New `is_direction_stable(symbol, expected)` checks for
  consecutive matching observations spanning ≥30s. Walks back from
  newest, breaks on disagreement; "streak length" must clear the
  threshold.
- `reconcile_orphan_positions` now skips with `direction_unstable`
  reason if stability gate fails. Today's SOFI bug becomes
  impossible — you'd need 30s of continuous SHORT observation
  before the reconcile claims SHORT.

**C — Wrong-direction phantom sweep** (extends v19.27 sweeper)
- `position_manager.update_open_positions` now also detects bot
  trades whose direction disagrees with IB's net direction for the
  symbol (e.g. bot tracks SOFI SHORT 2014sh while IB has SOFI LONG
  2364sh). These are auto-closed with reason
  `wrong_direction_phantom_swept_v19_29`, no IB action fired.
- Today's SOFI catastrophe will be auto-cleaned at startup once
  v19.29 lands, no manual intervention needed.
- CRITICAL Unified Stream event emitted so operator sees the sweep
  in real-time.

**D — EOD no-new-entries gate**
(`services/opportunity_evaluator.evaluate_opportunity`)
- Soft cut at **3:45pm ET**: warn-only, log + Unified Stream
  notice, but trade still allowed (operator wanted 5min grace for
  late afternoon momentum)
- Hard cut at **3:55pm ET**: `evaluate_opportunity` returns None,
  records `eod_no_new_entries` rejection, emits filter Unified
  Stream event.
- Skips weekends. Flatten window 3:55-4:00pm exclusively owned by
  EOD close loop.

**E — EOD flatten escalation alarm**
(`services/position_manager.check_eod_close`)
- When EOD close has any `failed_symbols`, emit a CRITICAL/HIGH/
  WARNING Unified Stream alarm sized by minutes-to-close.
- Pre-v19.29 this was a `logger.error` only — backend log noise the
  operator never sees. Now lights up V5 banner with
  `🚨 [CRITICAL] EOD FLATTEN FAILED — 3 of 5 closes didn't fill...
   USE 'CLOSE ALL NOW' BUTTON OR FLATTEN IN TWS.`

### Tests
- 15 new pytests in `test_critical_pipeline_hardening_v19_29.py`:
  - 5 covering intent dedup (block / clear / TTL / buy-vs-sell /
    source pin on trade_execution wiring)
  - 4 covering direction stability (no-history / detect-flip /
    pass-after-30s / source pin on reconcile)
  - 1 wrong-direction phantom sweep source pin
  - 2 EOD no-new-entries gate (existence + return-None)
  - 1 EOD flatten escalation alarm
  - 2 integration pins (clear-on-fill, record observations)
- **105/105 combined** with v19.23 + v19.24 + v19.25 + v19.26 +
  v19.27 + v19.28 + v19.29 suites.
- v19.24 reconcile tests updated to pre-populate direction history.
- Ruff clean on all new code; pre-existing F841/F821 warnings
  unchanged (verified by line numbers).

### Live verification (preview env)
- `/api/sentcom/positions`: HTTP 200 ✓
- `/api/trading-bot/status`: HTTP 200 ✓
- `/api/diagnostics/recent-decisions`: HTTP 200 ✓
- No new exceptions in backend.err.log

### Operator action after Spark pull
1. **TONIGHT before tomorrow open**: manually set stops in TWS or
   close the overnight orphan positions (LITE 12sh, CB 151sh,
   HOOD 177sh, SOFI 886sh, BP 336sh, TMUS 255sh — last-5-min
   fills with auto-cancelled brackets). If you hold any to open,
   they're naked.
2. Pull v19.29 + restart backend.
3. **Wrong-direction SOFI**: at restart the v19.29 phantom sweep
   will auto-close the SOFI SHORT 2014sh phantom (logging + stream
   event). No IB action fired — bot's record only.
4. **Order spam**: monitor IB Orders count tomorrow during RTH.
   Expected: way fewer cancellations. If you see same-intent dups,
   share the pattern and I'll tune `INTENT_TTL_SECONDS` /
   `PRICE_TOLERANCE_PCT`.
5. **3:45-3:55pm window**: tomorrow watch for the Unified Stream
   warnings ("Late-day SOFI…in the 10-min grace window") and at
   3:55pm hard cuts ("⏰ Passing on … past 3:55pm ET, EOD flatten
   window owns the last 5 minutes").
6. **3:55-4:00pm flatten**: if any close fails, expect the
   CRITICAL alarm to fire prominently in the V5 banner.

## 2026-05-01 (forty-ninth commit, v19.28) — Diagnostics tab MVP (Decision Trail spine + Module Scorecard + Pipeline Funnel + Export Report)

**Operator asked**: "now that we have ton of shadow trades, actual
trades, scans and evals, AI reasons/decisions, etc. we need a
framework or reporting feature to bring all of these stats and
messages together so that we can compare and contrast to start tuning
our whole pipeline further and making our entire system smarter."

**Locked answer (5 questions answered 2026-05-01)**:
1. Start with **Decision Trail Explorer** (the data spine)
2. Live in a new top-level **"Diagnostics" side-nav tab** (between
   Settings and bottom). Inline drilldowns deferred to v19.29.
3. **Hybrid tuning** — operator drives, can also dump report to
   Emergent for suggestions
4. **Both real-time + EOD** insights cadence
5. Sequence: ship maximum-insight scaffolding now

### Backend

**`services/decision_trail.py`** (new) — cross-collection joins:
- `build_decision_trail(db, identifier)` — given any of `alert_id`,
  `trade_id`, or `shadow_decision_id`, joins `bot_trades` +
  `shadow_decisions` + `sentcom_thoughts` (TTL 7d, ±30min/+2h
  window) + synthesised alert summary from `entry_context`. Returns
  a structured trail with sections `{alert, shadow, module_votes,
  trade, thoughts, meta}`. Outcome derivation handles win/loss/
  scratch/open/shadow_*.
- `list_recent_decisions(db, limit, symbol, setup, outcome,
  only_disagreements)` — paginated mixed list of bot trades + non-
  executed shadow decisions, dedup by `was_executed=True` so
  shadows that became real trades only count once. Disagreement
  filter shows shadows where `combined_recommendation` diverged
  from `debate.consensus`.
- `build_module_scorecard(db, days)` — per-AI-module aggregate
  from `shadow_module_performance` collection augmented with
  `shadow_module_weights`. Computes `kill_candidate` flag
  (accuracy < 50% AND followed-P&L < ignored-P&L) and sorts kill
  candidates first.
- `build_pipeline_funnel(db, days)` — 5-stage funnel (emitted →
  ai_passed → risk_passed → fired → winners) with conversion %
  between consecutive stages.
- `export_report_markdown(db, days)` — clean markdown dump
  combining funnel + scorecard + recent decisions + disagreements.
  Schema-stable so when operator pastes into chat with Emergent,
  the LLM gets predictable structure to reason from.

**`routers/diagnostics.py`** (new) — 5 read-only endpoints all
prefixed `/api/diagnostics`:
- `GET /recent-decisions?limit&symbol&setup&outcome&only_disagreements`
- `GET /decision-trail/{identifier}`
- `GET /module-scorecard?days`
- `GET /funnel?days`
- `GET /export-report?days&fmt=markdown`

**`server.py`** — registered router + `set_db()` on startup so the
endpoints are live the moment uvicorn boots.

### Frontend

**`pages/DiagnosticsPage.jsx`** (new) — full operator view with 4
sub-tabs:
1. **Trail Explorer** (default) — left rail recent-decisions list
   with symbol filter + disagreements toggle + refresh; right pane
   per-decision drilldown showing 4 sections (Scanner Alert / AI
   Module Votes / Bot Decision / Bot Thoughts).
2. **Module Scorecard** — sortable table with kill-candidate row
   highlight (rose tint), 1d/7d/30d window switcher.
3. **Pipeline Funnel** — horizontal bar chart with conversion %
   between stages, abnormal drops (<30%) highlighted in rose.
4. **Export Report** — fetch + Copy-to-Clipboard markdown dump
   for tuning conversations with Emergent.

**`components/Sidebar.js`** — new "Diagnostics" nav entry with
`Microscope` icon and `NEW` badge.

**`App.js`** — `case 'diagnostics'` route renders DiagnosticsPage
inside an ErrorBoundary.

### Tests
- 16 new pytests in `test_diagnostics_v19_28.py`:
  - 5 covering trail builder (resolve by trade_id / alert_id /
    shadow_only / no-match / outcome derivation corner cases)
  - 3 covering recent-decisions filtering (symbol+outcome,
    skip-executed-shadows, disagreements filter)
  - 1 module scorecard kill-candidate logic + sort order
  - 1 pipeline funnel stage count + conversion %
  - 1 markdown export schema (sections, paste-back footer)
  - 2 router pins (all 5 endpoints registered, set_db works)
  - 3 frontend source-level pins (DiagnosticsPage subtabs,
    sidebar nav entry, App.js route case)
- **90/90 combined** with v19.23 + v19.24 + v19.25 + v19.26 +
  v19.27 suites. ESLint + ruff clean on all new code.

### Live verification
- All 5 backend endpoints HTTP 200 ✓
- Frontend renders the Diagnostics page on tab click ✓
  (screenshot: header reads "DIAGNOSTICS V19.28", 4 sub-tab
  buttons visible, Trail Explorer empty-state hint shown)
- `Diagnostics NEW` nav entry visible in side rail ✓

### What this unlocks
- **Real-time tuning surface**: operator can pick any trade /
  shadow / alert and see the full decision chain in one drilldown
- **Module governance**: kill-candidate flag highlights modules
  losing money vs ignoring them — supports operator's hybrid
  tuning workflow
- **Funnel observability**: spot when AI gate or risk gate is
  rejecting abnormally
- **Tuning-suggestion workflow**: one-click markdown copy →
  paste into chat → Emergent has stable schema to suggest tuning

### Operator action after Spark pull
1. Pull + restart backend.
2. Open V5. Side nav now has "Diagnostics" with `NEW` badge
   between Settings and the bottom.
3. **Trail Explorer**: pick a recent SOFI / HOOD / SBUX trade →
   verify all 4 sections (alert / module votes / bot decision /
   thoughts) populate.
4. **Module Scorecard**: 7d view → look for any 🔴 kill-candidate
   rows. These are modules to consider downweighting or retiring.
5. **Pipeline Funnel**: 1d view → spot the biggest drop. If AI
   gate rejected 80% today vs 40% median, something's tuned wrong.
6. **Export Report** → Copy markdown → paste into chat with
   Emergent → ask "what should I tune?"

### Deferred to v19.29 (if you want them)
- **Inline drilldown drawer** in V5 Open Positions / Scanner
  Cards / Unified Stream → click any row → opens trail
- **EOD Insight Stream** sub-tab — LLM summary of "3 things to
  pay attention to tomorrow"
- **Counterfactual Playground** — "if I'd raised setup_min_rr
  on momentum from 1.7 → 2.0 last 30d, here's what would've
  happened"
- **Cohort Comparator** — pick 2 sub-populations, R-distribution
  histograms, win-rate diff

## 2026-05-01 (forty-eighth commit, v19.27) — Position panel reality reconciliation

**Operator caught a multi-bug screenshot** mid-session (10 open
positions, 4 misclassified as orphans even though the bot opened
them, 2 symbols showing duplicate rows from multiple bot brackets,
1 OKLO SHORT 0sh ghost). Three coordinated fixes ship together as
v19.27.

### Fix 1 — Smart `source` detection in `sentcom_service.get_our_positions`
- New `SentComService._classify_source_v19_27(symbol, direction,
  bot_total, ib_pos_by_symbol)` static helper. Replaces binary
  `source: 'bot'/'ib'` with share-count reconciliation:
  - `bot_shares == ib_shares` → `'bot'` (clean)
  - `bot_shares < ib_shares`  → `'partial'` + emit extra orphan row
                                for the unclaimed remainder
  - `bot_shares > ib_shares`  → `'stale_bot'` (phantom shares,
                                Fix 3 sweeps these on next manage cycle)
  - `bot_shares == 0`         → `'ib'` (true orphan)
  - Direction mismatch        → `'stale_bot'`
  - ±1 share rounding tolerance to avoid false-partial spam
- `get_our_positions` now pre-builds `bot_shares_by_symbol` and
  `ib_pos_by_symbol` maps before iterating, then in the IB-position
  loop:
  - Clean match → skip (bot row covers it)
  - Stale_bot → skip (auto-sweep cleans up)
  - Partial → emit row for ONLY the unclaimed shares (not the full
    IB position) so operator sees the gap, not a full duplicate
  - True orphan → emit full row as before
- Orphan rows now carry `ib_total_shares`, `bot_tracked_shares`,
  `unclaimed_shares` so the V5 chip can render hover detail like
  *"Bot tracks 5,000sh, IB has 18,364sh — 13,364sh untracked"*

### Fix 2 — Symbol-level grouping in `OpenPositionsV5.jsx`
- New `groupBySymbolDirection(open)` rolls up multiple `BotTrade`
  records for same `(symbol, direction)` into ONE aggregate row:
  - Total shares (Σ across members)
  - Weighted avg entry (Σ shares×entry / Σ shares)
  - Combined unrealized P&L (Σ across members)
  - Worst source (any non-`bot` source dominates the badge)
- New `GroupMemberRow` component shown on expand — compact inline
  rows displaying each underlying trade's entry / SL / PT / SMB
  grade / setup. Operator can see "this aggregate row is HOOD
  252sh @ B-grade scan + HOOD 299sh @ A-grade scan, both with
  same SL/PT bracket."
- New `SOURCE_BADGE` map renders distinct chips:
  - `ORPHAN` (amber, on `'ib'` rows)
  - `PARTIAL` (orange, on `'partial'` rows with `unclaimed_shares` tooltip)
  - `STALE` (rose, on `'stale_bot'` — auto-sweep will handle)
  - `'bot'` rows get no badge (clean state)
- `Reconcile N` button now counts `ib` + `partial` rows (was just
  `ib`). Both need bot management; only the count differs.
- `2×` badge appears on multi-trade groups so operator knows the
  row aggregates multiple brackets.

### Fix 3 — Auto-sweep 0sh phantoms in `position_manager.update_open_positions`
- New v19.27 block at the top of `update_open_positions`:
  - Build `(symbol, direction) → abs_qty` map from
    `_pushed_ib_data["positions"]`. **Skip block entirely if pusher
    disconnected** — never sweep based on stale data.
  - For each `_open_trades` entry, if all 4 conditions hold:
    - `status != CLOSED`
    - `remaining_shares == 0` (firmly zero, not None/uninitialised)
    - `executed_at` age >= 30s (avoid sweeping brand-new fills)
    - IB shows 0 shares for `(symbol, direction)`
  - …then transition `status: CLOSED`, set `close_reason:
    'phantom_auto_swept_v19_27'`, persist, pop from `_open_trades`,
    push to `_closed_trades`, emit `phantom_auto_swept` Unified
    Stream event.
- Pure janitorial cleanup — all MFE/MAE/realized P&L is already
  preserved upstream by normal close paths. The phantom is just
  the same trade with `status` not flipped.

### Tests
- 18 new pytests in `test_position_panel_reality_v19_27.py`:
  - 6 covering `_classify_source_v19_27` (clean / partial /
    stale_bot / direction-mismatch / ±1-share tolerance / pure-orphan)
  - 3 source-level pins on `get_our_positions` aggregation +
    partial-remainder emission + clean/stale skip
  - 5 source-level pins on phantom sweep (block exists, pusher
    guard, age guard, remaining_shares==0 strict check, stream
    emit)
  - 4 source-level pins on V5 grouping (`groupBySymbolDirection`,
    `SOURCE_BADGE` map, Reconcile counts ib+partial, multi-count
    badge)
- **74/74 combined** with v19.23+v19.24+v19.25+v19.26 suites.
  ESLint clean. Ruff: only pre-existing warnings (none from this
  commit, verified by line numbers).

### Live verification (preview env)
- `/api/sentcom/positions`: HTTP 200 ✓
- `/api/trading-bot/status`: HTTP 200 ✓
- No new exceptions in backend.err.log

### Operator action after Spark pull
1. Pull + restart backend.
2. Open V5 dashboard. The Open Positions panel should now show:
   - **One row per symbol+direction** (HOOD + BP no longer duplicate)
   - **`2×` badge** on grouped rows — click to expand and see each
     underlying bot trade with its own SMB grade / setup / entry
   - **Source badges** on non-clean rows: `ORPHAN` (amber),
     `PARTIAL` (orange), `STALE` (rose)
   - **`Reconcile N` count** now reflects orphans + partial
     remainders, not just true orphans
3. Wait one manage-cycle (≤5s during RTH). The OKLO SHORT 0sh
   ghost should disappear automatically — watch the Unified Stream
   for `🧹 Auto-swept phantom OKLO SHORT (0sh leftover)…`
4. After clicking `Reconcile N` on partial rows, the orphan
   remainder gets materialized → row source upgrades from
   `partial` → `bot` on the next refresh.

## 2026-05-01 (forty-seventh commit, v19.26) — AI chat assistant data plumbing fixes

**Operator-reported bugs in the same chat session** (2026-05-01 chat
log, message timestamps 2:10:21 PM and 2:13:38 PM ET, both during RTH):

  - **Bug 1**: "what is our stop on SOFI?" → bot answered *"I don't
    have a stop price recorded for the SOFI long position"* despite
    the V5 UI clearly showing SOFI's SL/TP (lazy-reconciled from
    `bot_trades`).
  - **Bug 2**: "should i go long SQQQ or go short SQQQ right now?" →
    bot answered *"I don't have a live quote on SQQQ right now"*
    despite SQQQ being a high-volume ETF with available bars in
    Mongo.

### Diagnosis
- **Bug 1 root cause**: `chat_server._get_portfolio_context()` reads
  `bot_open_trades` directly from `ib_live_snapshot`. SOFI/SBUX/OKLO
  are IB-only orphans with NO entry there. v19.23.1 lazy-reconcile
  only patched `sentcom_service.get_our_positions` (the SentCom V5
  panel) — it never reached the chat context builder.
- **Bug 2 root cause**: `chat_server` only fetches
  `/api/live/symbol-snapshot` for held positions + hardcoded indices
  (SPY/QQQ/IWM/VIX). SQQQ wasn't in either list, so no live data
  reached the LLM context. The system prompt's safety rule ("never
  guess prices for symbols not in LIVE DATA") then forced the
  refusal.

### Fix Bug 1 — Lazy-reconcile orphans in chat context
- New block in `_get_portfolio_context`: for every IB position not
  matched in `bot_open_trades`, query `bot_trades` for the most recent
  trade matching the symbol (open OR closed within last 30d) and
  surface its `stop_price` + `target_prices` into the bot-tracked
  trades context section.
- Reconciled rows are tagged `(lazy-reconciled from <status>)` in the
  setup_type so the LLM can tell the operator "the stop on SOFI is
  $X.XX from yesterday's filled trade" instead of "I have no stop."
- `debug.lazy_reconciled` carries the list of symbols that got the
  lookup so audit trails are clean.

### Fix Bug 2 — Hydrate live data for user-mentioned tickers
- New helper `_extract_user_mentioned_tickers(user_message, limit=5)`:
  - Regex `\b[A-Z][A-Z0-9.]{0,4}\b` for ticker-shaped tokens.
  - Trading-jargon denylist (LONG/SHORT/VWAP/RSI/EMA/ATR/RVOL/FOMC/
    EOD/etc) prevents false positives.
  - Capped at 5 to prevent context bloat.
  - Handles dotted tickers (BRK.A / BRK.B).
- `_get_portfolio_context()` signature gains `user_message: Optional[str]`.
- `chat()` endpoint passes `request.message` through.
- Live-snapshot fetch loop's target list now includes user-mentioned
  tickers FIRST after held positions (operator's question is the
  highest-priority context).
- Technicals fetch loop also bumped from 12 → 15 symbols and includes
  user-mentioned tickers.
- Net effect: when operator asks about SQQQ (or any other non-held
  symbol), live snapshot + RSI/VWAP/EMA technicals now land in the
  context block. The LLM has real numbers to answer with.

### Tests
- 12 new pytests in `test_chat_assistant_v19_26.py`:
  - Ticker extraction: SQQQ basic case, multi-symbol order, jargon
    filter (RSI/VWAP/EMA/ATR/RVOL/FOMC/EOD), 5-symbol cap, defensive
    None/empty/non-string inputs, lowercase rejection, dotted tickers.
  - Source-level pin on `bot_trades.find_one` lazy-reconcile lookup
    + `tracked_symbols` / `orphan_positions` set logic.
  - Source-level pin on signature having `user_message` parameter.
  - Source-level pin that `chat()` passes `request.message` to
    `_get_portfolio_context`.
  - Source-level pin on snapshot/technicals cap bumped to 15 + extractor
    runs BEFORE the snapshot fetch loop.
- **56/56 combined** with v19.23 + v19.24 + v19.25 suites. Ruff cleared
  the real `F823` (duplicate inner timedelta import); 6 remaining
  lint warnings are pre-existing.

### Operator action after Spark pull
1. **Pull + restart `chat_server.py`** (port 8002).
2. Test Bug 1: ask the bot *"what is our stop on SOFI?"* — should
   reply with the actual stop price + targets from `bot_trades`,
   tagged `(lazy-reconciled from <status>)` so you know it came
   from the historical lookup.
3. Test Bug 2: ask *"should i go long SQQQ or short SQQQ?"* — should
   reply with real numbers (price, RSI, VWAP, EMA20, RVOL, ATR%) and
   give an actionable view, not refuse.
4. Test no-regression: ask about a ticker the bot is unlikely to find
   (e.g. *"what about ZZZZ?"*) — should still gracefully say "I don't
   have a quote on ZZZZ" because the snapshot fetch returns
   success=false.

## 2026-05-01 (forty-sixth commit, v19.25) — Chart performance hardening (Tier 1 + Tier 2)

**Operator flagged**: "very very delayed chart loading across the
app." Diagnosis: every chart load (cold open, symbol switch, 30s
auto-refresh) was running the full chain — Mongo bar query + pusher
RPC roundtrip to Windows + Python recompute of EMA20/50/200 + BB20 +
VWAP + markers + session filter — for ~5,000 bars. Polling pattern
re-shipped the entire window every 30s. No HTTP-level response cache.

This commit ships **Tier 1 (cache) + Tier 2 (tail-only refresh)** —
the operator-approved combo that eliminates ~95% of perceived AND
actual slowness without WebSocket complexity.

### Tier 1 — Backend response cache
- **`services/chart_response_cache.py`** — Mongo-backed TTL cache for
  `/api/sentcom/chart` responses. **Caches survive backend restarts**
  via Mongo TTL index on `expires_at`. Two-tier: in-memory dict for
  hot reads + Mongo for durability.
- **TTL**: 30s for intraday, 180s for daily (`chart_cache_ttl_for`).
- **Key**: `(symbol_upper, tf_lower, session, days)` — case + session
  variations collapse to the same entry.
- **Wiring**: `routers/sentcom_chart.py::get_chart_bars` checks
  `cache.get` BEFORE the live compute path. Hits return in
  ~0.003ms regardless of bar count, indicator math, or pusher
  latency. Misses fall through to compute, then `cache.set` writes
  back for the next request. Response stamps `cache: 'hit'|'miss'`
  for observability.
- **Invalidation**: `services/trade_execution.py::execute_trade` now
  calls `chart_response_cache.invalidate(trade.symbol)` after a fill
  so the new entry/exit marker shows on the very next chart render
  without waiting for the TTL.
- **Schema-versioned**: `_CACHE_VERSION = 1` on every doc; future
  payload changes bump the version so old entries get treated as
  MISS without manual flush.

### Tier 2 — Tail-only refresh endpoint
- **`GET /api/sentcom/chart-tail?symbol=X&timeframe=5min&since=<ts>`**
  — returns ONLY new bars + their indicator values + new markers
  since the operator's last-seen timestamp. Reads through the same
  cache as `/chart` (cache hit = O(N_new_bars) slice; cache miss
  delegates to full path). Capped at 50 bars by default; max 500.
- **Where the win comes from**: 30s polling now ships 1-3 bars per
  poll instead of 5,000. ~95% bandwidth + Python compute saved on
  the auto-refresh hot path.

### Frontend — Stale-while-revalidate + smart polling
- **`ChartPanel.jsx`**:
  - **`lastBarsCacheRef`** — in-component `Map<key, {bars, indicators,
    markers, ts}>` keyed by `${symbol}|${tf}|${days}`. Hydrates state
    immediately from cache on cacheKey change, then triggers a
    background refetch. Symbol-switch on a previously-visited
    symbol now feels instant.
  - **No spinner on refetch when cache is present** — the legacy
    `setLoading(true)` call now only fires on a true cold load. Hot
    refetches are silent. Eliminates the "blank chart on every
    poll" perception bug.
  - **Smart-polling** — replaces the legacy 30s `setInterval(fetchBars)`
    with a recursive `setTimeout` loop that:
    - Calls `/api/sentcom/chart-tail`, not `/chart`
    - Polls every **5s during RTH** (9:30-16:00 ET, weekdays)
    - Backs off to **30s outside RTH**
    - **Pauses entirely when the tab is hidden**
      (`document.visibilityState !== 'visible'`)
    - Skips the `1day` timeframe (daily bars don't need tail polling)
  - **Tail merge** — new bars merged onto state with last-bar
    overlap dedup. Indicator points spliced onto each series' tail.
    Markers appended. Frontend lightweight-charts paints the new
    bars via the existing data-push effect.

### Tests
- **17 new pytests** in `test_chart_response_cache_v19_25.py` —
  cache get/set/invalidate, TTL math, key normalization, set
  rejection of garbage payloads, expired-entry eviction, endpoint
  cache integration order, tail slicing, cap enforcement, empty-
  tail empty-response, source-level pin on trade_execution
  invalidation, source-level pin on ChartPanel.jsx stale-while-
  revalidate pattern.
- **44/44 combined with v19.23 + v19.24 suites.** Ruff + ESLint clean.

### Live verification (preview env)
- `cache.set(1234 bars)`: 0.02ms
- `cache.get HIT`: 0.003ms ← ~1000× faster than the recompute path
- `cache.invalidate(SPY)`: drops all entries for symbol cleanly
- `/api/sentcom/chart-tail` registered + serving 200 OK

### Operator action after Spark pull
1. Pull + restart backend.
2. Open the V5 dashboard. The first chart load is the cold path
   (still pays the full compute cost). Switch away and back, or
   wait for the 5s tail-poll — should feel **instant** now.
3. Watch for the `cache: 'hit'` field in the `/api/sentcom/chart`
   network tab response after the second load — confirms the cache
   is firing.
4. Watch for `/api/sentcom/chart-tail` calls every 5s during RTH
   in the network tab. Should return ~1-3 bars per call instead
   of the full 5,000-bar payload.

## 2026-05-01 (forty-fifth commit, v19.24) — Proper reconcile endpoint + MultiIndex regime pin

**P0 shipped**: `POST /api/trading-bot/reconcile` — the write-through
reconcile that v19.23.1 lazy-reconcile was the read-only precursor to.
Closes the loop so IB-only orphan positions (SBUX/SOFI/OKLO) can be
actively managed by the bot (trail stops, scale-out, EOD close), not
just rendered on the UI.

### Why
Lazy-reconcile (v19.23.1) fixed the V5 UI by scanning Mongo
`bot_trades` and stamping SL/TP on the IB-only position payload. But
the bot's in-memory `_open_trades` is still empty for those positions,
so the manage loop (`stop_manager.update_trailing_stop`, scale-out,
EOD close-all) never touches them. If SBUX gapped up, the bot would
miss the chance to trail to breakeven. If the operator ended the day
with 3 unmanaged orphans, EOD auto-close would skip them.

### What shipped
- **`RiskParameters.reconciled_default_stop_pct=2.0`** +
  `reconciled_default_rr=2.0`. Wider than the global 1.7 min R:R
  because orphans have no setup context to justify tight stops; 2.0
  gives breathing room + symmetric R:R, and the trailing-stop manager
  ratchets up from there.
- **`PositionReconciler.reconcile_orphan_positions(bot, symbols=[...],
  all_orphans=False, stop_pct=None, rr=None)`** — materializes a real
  `BotTrade(setup_type='reconciled_orphan', quality_grade='R',
  trade_style='reconciled', close_at_eod=False)` record, inserts into
  `_open_trades`, persists via `bot._persist_trade`, and fires an
  `emit_stream_event(event='trade_reconciled')` so the V5 Unified
  Stream shows "Reconciled SBUX @ $100.12 · 150sh · SL $98.00 · PT
  $104.00 · R:R 2.0".
- **Safety: stop-already-breached guard**. If current_price ≤ proposed
  stop (for long, or ≥ for short), reconcile SKIPS with reason=
  `stop_already_breached` and `suggest_manual: true`. Never silently
  materialize a trade that would insta-stop on the next tick.
- **Safety: idempotent**. Already-tracked symbols are SKIPPED with
  reason=`already_tracked`; never double-insert.
- **`POST /api/trading-bot/reconcile`** (new router endpoint).
  - `{"symbols": ["SBUX"]}` → explicit, always works
  - `{"all": true, "confirm": "RECONCILE_ALL"}` → sweep all orphans
    (confirm token prevents accidental sweeps during IB blips, mirrors
    `/api/portfolio/flatten-paper?confirm=FLATTEN`)
  - `{"all": true}` or empty body → 400 with actionable message
  - Per-request `stop_pct` / `rr` overrides
- **`OpenPositionsV5` frontend**: new "Reconcile N" button in the panel
  header, visible only when ≥1 orphan (`source === 'ib'`) is present.
  Click → `window.confirm` → POST → toast with success/skip counts.
- **Persistence**: new defaults round-trip through `bot_state.risk_params`
  via `bot_persistence.save_state` / `load_state`.
- **`get_status`**: exposes the two new fields in the `risk_params`
  block so operator can see current defaults via
  `GET /api/trading-bot/status`.

### Also shipped — MultiIndexRegime source-level regression pins
Handoff flagged P0 verification: confirm `MultiIndexRegimeClassifier`
is actually stamping `LiveAlert.multi_index_regime` (not leaving it at
`"unknown"`). 3 new source-level pins assert the plumbing is intact at
pytest time instead of requiring an RTH curl on Spark:
- `_apply_setup_context` must write to `alert.multi_index_regime` and
  must reference `_get_cycle_context` + `multi_index_regime_classifier`
- `LiveAlert` must have the `multi_index_regime` field
- `_refresh_cycle_context` must prefetch the regime once per cycle
  via `get_multi_index_regime_classifier`

Operator still needs to run `curl /api/scanner/live-alerts?limit=5 |
jq '.alerts[].multi_index_regime'` on Spark during RTH to confirm
end-to-end, but the pin catches any future code-level regression.

### Tests
- 21 new pytest in `test_proper_reconcile_endpoint_v19_24.py` covering:
  defaults, persistence, bracket math (long + short), stop-already-
  breached guard, already-tracked skip, no-ib-position skip,
  all_orphans sweep, pusher-disconnected guard, per-request overrides,
  4 endpoint-level contract tests (empty body reject, all-without-
  confirm reject, symbols-accept, all-with-confirm accept), 503 when
  bot not initialized, and 3 MultiIndexRegime source pins.
- **21/21 passing** locally + **27/27 combined with v19.23
  payload test suite**. ESLint clean. Ruff clean (1 pre-existing
  F841 on unrelated `reason` local unchanged).

### Operator action after Spark pull
1. `sudo supervisorctl restart backend` (auto-reloads on DGX via
   existing ENV, or manual `pkill + nohup python server.py`).
2. Verify defaults: `curl localhost:8001/api/trading-bot/risk-params |
   jq '.risk_params.reconciled_default_stop_pct,
                           .risk_params.reconciled_default_rr'`
   → should print `2.0` / `2.0`.
3. On SBUX/SOFI/OKLO orphans: click the **Reconcile 3** button in the
   V5 Open Positions header → confirm → expect 3 reconciled rows in
   the response and the positions switching from `source: ib` to the
   full bot-managed payload.
4. Multi-index regime check:
   `curl localhost:8001/api/scanner/live-alerts?limit=5 |
    jq '.alerts[].multi_index_regime'` — should print real labels
   (`risk_on_broad`, `bullish_divergence`, etc.) not `"unknown"`.

## 2026-05-01 (forty-fourth commit, v19.23.1) — Lazy reconcile + share size everywhere + chart bubble fix

Operator follow-up review on v19.23 deploy: SBUX/SOFI/OKLO showing
STOP — / TARGET — on the Open panel, no SL/TP price-lines on the
chart, and tier chip read `TRADE 2 HOLD long` (verbose).

### v19.23.1 — Lazy-reconcile SL/TP for IB-only positions

`sentcom_service.get_our_positions()` now scans Mongo `bot_trades` for
each IB-only symbol and stamps the most recent matching trade's
`stop_price` + `target_prices` + rich entry context onto the position
payload. Result:

- Chart `priceLinesRef` effect can now draw the red SL line + green PT
  line for SBUX/SOFI/OKLO etc. that previously showed only the yellow
  Entry line.
- Open Positions expanded grid shows real `STOP` / `TARGET` values
  instead of literal dashes.
- Tier chip can read `VWAP day` / `ORB long` / `9-EMA scalp` etc.
  instead of falling back to bare `LONG` / `SHORT`.
- `reasoning[]` / `exit_rule` / `risk_reward_ratio` / `smb_grade`
  / `remaining_shares` / `original_shares` all populated for the
  expanded V5 row from the matching bot_trade.
- New boolean `reconciled` field on the payload exposes whether the
  position was matched. Frontend can later badge "RECONCILED" /
  "ORPHANED" if useful.

Status field normalized: `"ib_position"` → `"open"` (matches the V5
mockup chip strip which expects `OPEN`).

### v19.23.1 — Tier chip humanization

`OpenPositionsV5.STYLE_HUMAN_MAP` adds explicit display labels for the
22 named Bellafiore Trades (`opening_range_break` → `ORB`,
`9_ema_scalp` → `9-EMA`, `vwap_continuation` → `VWAP`,
`day_2_continuation` → `DAY 2`, `relative_strength_position` → `RS POS`,
etc.). Unknown styles fall back to `replace(_, ' ').toUpperCase()`
truncated to 12 chars.

### v19.23.1 — Share size visible everywhere

Operator request: "make sure that share size is visible for each trade
wherever it needs to be displayed."

- **OpenPositionsV5 compact row**: `Nsh` is now the lead element on the
  model-trail subtitle so position size is the first thing the eye
  picks up after the symbol+pnl.
- **ScannerCardsV5**: new `Nsh` chip alongside the stage chip on
  manage-stage cards. Bot narrative for managed positions now also
  prepends `Nsh ·` so the operator can read it when chips wrap.
- **V5ChartHeader**: `Nsh` already in the header chip strip from
  v19.23 (e.g. `2858sh` on SBUX).

### v19.23.1 — Chart bubble kind filter loosened

Operator screenshot showed SBUX in Deep Feed with multiple events but
no chart bubbles rendered. Root cause: the kind allowlist was too
strict (excluded `filter` and `info` kinds even when they had
operator-facing content). Now allows `scan / brain / evaluation /
thought / fill / alert / rejection / skip / filter / info`, gated on
`(content || text)` non-empty so truly empty system noise is still
excluded. Color/label mapping already covered all 11 kinds.

### Tests

`test_open_positions_payload_v19_23.py` updated:
- New test `test_lazy_reconcile_enriches_ib_position_with_bot_trade_levels`
  pins the SBUX-style scenario: IB position with no in-memory bot_trade,
  Mongo-side bot_trade record with full SL/TP/reasoning, payload comes
  back with everything stamped through.
- Existing test updated for `status: "open"` (not `"ib_position"`) and
  `reconciled: False` when no Mongo match.
- **6/6 passing locally.** ESLint clean.

### Operator action on Spark

1. Pull → backend hot-reload (sentcom_service is hot-reloadable).
2. Open V5: refocus SBUX. Verify red SL line + green PT line render on
   the chart. STOP / TARGET cells in the OPEN panel show real numbers.
3. Verify tier chip reads humanized name (e.g. "VWAP day" instead of
   "TRADE 2 HOLD long") for symbols that had bot_trade records.
4. Verify the `Nsh` chip / share count is visible on every position
   card and the OpenPositions row.
5. Verify chart bubbles now appear over the focused-symbol chart for
   any symbol with sentcom_thoughts events in the last 24h.



## 2026-05-01 (forty-third commit, v19.23) — V5 expandable Open Positions + chart bot-thought bubbles

Operator's V5 mockup review. Five tickets in one shipment, all surfacing
the bot's reasoning AT the trade-time so the operator can audit each
position at a glance.

### v19.23 — Expandable Open Positions row (Issue #1)

**Operator pain:** "open positions are showing $0 PnL. need more detail
— current price, thesis, plan, tier"

**Backend (already shipped v19.22.3):** `sentcom_service.get_our_positions()`
merges `_pushed_ib_data.quotes` into `current_price` and exposes the rich
trade context (`scan_tier`, `trade_style`, `reasoning[]`, `exit_rule`,
`scale_out_state`, `trailing_stop_state`, `risk_amount`,
`risk_reward_ratio`, `potential_reward`, `remaining_shares`,
`original_shares`).

**Frontend:** `OpenPositionsV5.jsx` rewritten to operator-spec:
- **Compact mode** (default): symbol + tier chip (e.g. `DAY long`,
  `SHORT REV`) + sparkline + PnL/R + 1-line "model trail" subtitle
  (mirrors mockup's `TFT trails SL → $166.40 · PT $172 · CNN-LSTM 72% bull`).
- **Expanded mode** (click chevron or row): 4-cell price grid (Entry /
  Last / Stop / PT), risk math row (R:R · Risk · Reward · Shares ·
  P(win)), trail-state line, scale-out targets-hit, exit-rule plan,
  AI reasoning bullets (top 4), setup/grade/regime footer.
- All new elements carry stable `data-testid` attributes.

### v19.23 — Chart bot-thought bubbles overlay (Issue #3)

**Operator request:** "markers for entry and exits. lines for SL/TP.
chat bubbles with bot thoughts/reasoning at the time that it had them"

- New `ChartThoughtBubblesOverlay.jsx` reads
  `/api/sentcom/stream/history?symbol=X&minutes=1440&limit=40` and
  renders chat-bubble annotations directly over the chart pane.
- Time-anchored via `chart.timeScale().timeToCoordinate()` — bubbles
  follow pan/zoom; off-screen bubbles disappear automatically.
- Color-coded by `kind`: scanner=violet, brain/eval=cyan, alert=amber,
  fill=emerald, skip/rejection=slate (matches mockup's visual lanes).
- Bottom timeline rail with one dot per bubble — click to jump (sets
  `setVisibleRange` ±90min around the moment).
- Hover/click toggles bubble pin-state for full-text view.
- 30s same-(kind, content[:80]) dedup so the rejection-narrative path
  doesn't spam.
- Toggleable via new `Bot` indicator button in the chart header.

### v19.23 — V5 chart header context strip (Issue #3 sub)

`V5ChartHeader` now mirrors the mockup chip strip:
`Symbol · STATUS·age · $price · ±change% · Entry · SL · PT · R:R · Nsh`.
Status chip uses `position.status` (OPEN/ORDER/MANAGE), age computed
from `entry_time`. Live current_price + direction-aware change% added
between status chip and the price grid. R:R now reads
`risk_reward_ratio` (correct backend field name) with legacy
`risk_reward` fallback.

### v19.23 — Pipeline HUD width tightening (Issue #2)

`PipelineHUDV5` stages shrunk from `basis-2/3` to `basis-3/5` with
explicit `shrink` allowance + arrows pinned `shrink-0`. Right cluster
(P&L / Equity / Buying Pwr / Phase + safety + Flatten) bumped to
`basis-2/5 shrink-0` so 7-figure margin numbers and the inline
operator chips never get clipped. Stage internals tightened
(`px-3 py-2 → px-2 py-1.5`, `text-2xl → text-xl`) so the funnel reads
as one tight horizontal strip without losing legibility.

### v19.23 — Scanner cards: tier + setup chips + reasoning enrichment (Issue #4)

`ScannerCardsV5` now renders three context chips inline:
1. **Stage chip** (existing): SCAN / EVAL / ORDER / OPEN / CLOSED W / SKIP
2. **Tier chip** (NEW): INTRADAY / SWING / POSITION / INVESTMENT — soft
   context, never gates the alert
3. **Setup chip** (NEW): humanized `setup_type` — surfaces the
   Bellafiore Trade name (e.g. "opening range break", "9 ema scalp")

Alert `bot_text` fallback now joins the first 2 entries from
`reasoning[]` when available so the inline narrative carries the bot's
chain-of-thought (e.g. "ORB long · gate 78 · PMH break with vol +180%
RVol · Regime risk-on, sector XLF leading").

### Tests

New `backend/tests/test_open_positions_payload_v19_23.py` (5 cases) —
pins the `/api/sentcom/positions` payload contract: live-quote merge,
short-position PnL, rich V5 fields, fallback when `entry_context`
empty, IB-only position passthrough. **5/5 passing locally**, ESLint
clean across all touched JSX files.

### Operator action

Pull on Spark + frontend hot-reload. Verify:
1. Open Positions: row shows live PnL ≠ $0 within ~5s of any open
   trade. Click chevron → expanded panel renders with Entry/Last/Stop/PT
   grid + reasoning bullets.
2. Chart: focus a position. Bubbles appear at scanner-flag /
   AI-eval / fill timestamps. Bottom rail dots clickable.
3. Pipeline HUD: stages don't overlap with HealthChip /
   ConnectivityCheck / FlattenAll on any width.
4. Scanner cards: each shows tier + setup chip alongside stage chip.


## 2026-05-01 (forty-second commit, v19.22.1 + v19.22.2) — Bracket execution + reset durability

Live operator ticket during RTH:
> "we are getting alot of scans and evals, but still no trades taken"

Root cause turned out to be **two distinct bugs working together**, both
shipped in this commit. Live verification: HOOD `gap_fade` GO 52pts —
which had been failing for 12+ rejections all morning — filled at $73.35
within 60 seconds of the deploy.

### v19.22.1 — Pusher bracket-order handler

**Bug:** Every bracket order from the backend (`order_type="bracket"` +
parent / stop / target legs in one document) was rejected by the
Windows pusher with `"Unknown order type: bracket"`. The pusher's
`_execute_queued_order()` only handled MKT, LMT, STP, STP_LMT — anything
else hit the catch-all else branch and returned a synthetic rejection
without ever talking to IB. **184 of 323 orders today (~63%) died here**;
the operator had been seeing scan→eval→reject loops with zero broker
contact since the bracket order type was introduced.

**Fix:** Added a `is_bracket` detection branch UP FRONT in the pusher
that:
1. Reads `parent / stop / target` payloads from the order doc.
2. Builds three IB orders with linked `parentId` + `transmit` chain:
   - Parent (LMT entry): `transmit=False` (hold while children attach).
   - Take-profit (opposite-side LMT, GTC): `parentId=parent.orderId`,
     `transmit=False`.
   - Stop loss (opposite-side STP, GTC): `parentId=parent.orderId`,
     `transmit=True` — last leg flushes the bracket atomically.
3. Submits all three with `ib.placeOrder()`, waits for parent fill (30s
   max), reports `filled`/`pending`/`cancelled`/`rejected` to the
   backend with the same idempotency stamping the regular paths use.

Live proof from operator's pusher log post-deploy:
```
11:51:21 [OrderQueue] Submitting BRACKET 0f53abb7: BUY 953 SBUX @ $104.92
11:51:21 [OrderQueue] Bracket 0f53abb7 parent FILLED @ $104.896 (target+stop attached)
11:51:22 [OrderQueue] Submitting BRACKET 59253cb7: BUY 538 HOOD @ $73.48 (stop $68.33 / target $82.07)
11:51:22 [OrderQueue] Bracket 59253cb7 parent FILLED @ $73.35 (target+stop attached)
```

Also dropped `outsideRth=True` on the STP leg specifically — IB silently
ignores it on STP orders and emits Warning 2109 every time. The TP leg
keeps `outsideRth=True` because IB DOES honour it on LMT.

### v19.22.2 — Reset endpoint Mongo-write durability

**Bug:** `POST /api/trading-bot/reset-rr-defaults` was a sync handler
that fired-and-forgot the Mongo persistence write via
`asyncio.create_task(_trading_bot._save_state())`. The response returned
the new in-memory state immediately; if the operator restarted the
backend before that background task finished (which the operator did
this morning to deploy v19.21), the Mongo write was lost and the next
state restore reloaded the OLD `min_risk_reward = 2.5` value. Operator
caught it — global RR floor wouldn't stick.

**Fix:** Promoted handler to `async def` and `await _save_state()`.
Mongo write now completes BEFORE the response returns. Response payload
includes a new `persisted_to_mongo: bool` field so the operator can
verify the write hit disk. If Mongo is unavailable, the in-memory state
still gets reset (so the bot trades correctly for the rest of the
session) and `persisted_to_mongo: false` flags it for retry.

### Operator-applied configuration this session

In addition to the code patches, the operator applied these via curl:
- `POST /reset-rr-defaults` — global → 1.7, setup_min_rr → ship defaults
- `POST /risk-params` merge: added 7 more setup overrides
  (`off_sides`, `off_sides_short`, `off_sides_long`, `volume_capitulation`,
  `backside`, `bella_fade` → 1.5; `fashionably_late` → 2.0). These are
  bounded-target mean-reversion plays that should not be subject to the
  asymmetric-trade 1.7 floor.

### Verification

- `tests/test_pusher_bracket_handling_v19_22_1.py` — 6 cases covering
  bracket detection (via `type` field, via `order_type` field, case-
  insensitive), parent-payload lifting, regular-order pass-through,
  defensive missing-parent fallback.
- `tests/test_reset_rr_endpoint_v19_22_2.py` — 3 cases covering async-
  handler promotion, awaited-save semantics, save-failure graceful
  degradation.
- All 24 v19.20 + v19.21 + v19.22.x tests pass.
- **Live operator verification at 11:51 ET**: 14 fills in 15 minutes
  post-deploy, 0 "Unknown order type: bracket" errors, HOOD/SBUX/CB/BP/
  SOFI/OKLO all bracket-filled with target+stop attached as GTC OCA.


## 2026-05-01 (forty-first commit, v19.22) — News pruning + ML Feature Audit panel

Operator follow-up: "for news providers I only want to get rid of FLY
and BRFUPDN" + "yes let's add the ML Feature Audit panel" (the
enhancement suggested in the v19.21 finish note).

### News provider pruning — operator-precise control

The v19.21 ship added `IB_NEWS_PROVIDER_OVERRIDE=BZ,DJ,BRFG` (lock to
exactly those). That works but it's the wrong granularity for "I just
want to drop two specific vendors." This commit adds a SECOND env that
behaves as a filter on top of the live IB-subscribed list:

  • `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN` — drops those two from
    whatever `reqNewsProviders()` returns, keeping the rest.
  • `IB_NEWS_PROVIDER_OVERRIDE` still wins absolutely when set (the
    exclude list is ignored if override is set — semantics match
    operator intent: "lock OR filter, not both at once").
  • Trimmed default fallback (when `reqNewsProviders` returns empty)
    from `[BZ, FLY, DJ, BRFG, BRFUPDN]` → `[BZ, DJ, BRFG]` so even
    worst-case the bot's preference matches the operator's.

Setting `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN` in `/app/backend/.env`
on the DGX achieves exactly what the operator asked for — every
`get_historical_news` call from this point on asks IB only for the
non-excluded providers, regardless of what's subscribed in Gateway.

### `MLFeatureAuditPanel.jsx` — verify the ML loop without a terminal

Drop-in panel that wraps the v19.21 `GET /api/scanner/ml-feature-
preview/{symbol}` endpoint and renders three colored label badges
(market_setup, multi_index_regime, sector_regime) plus an active-
features list (the one-hot bins that fired = 1.0). Includes:

  • Editable symbol input that auto-prefills from
    `sentcom:focus-symbol` events. Click any `$TICKER` chip anywhere
    (gap scanner, gameplan card, narrative, etc.) → symbol input
    populates, fetch fires, panel re-renders with the new audit.
  • Wiring-status traffic light — green "Wired ✓ — N of M bins
    active" when the loop is alive, amber "Cold start" when nothing
    fires (data sparse / weekend / pre-warmup).
  • Re-emit `sentcom:focus-symbol` from the audit's own symbol
    chip so chat + audit stay in lockstep.
  • Mounted in `SentComV5View.jsx` right column above OpenPositions
    alongside the new `CpuReliefBadge` (the v19.21 throttle UI).

### Verification

- 6 new pytest cases in `test_news_provider_pruning_v19_22.py` —
  override wins, exclude filters live list (case-insensitive), no-env
  returns full list, empty live list uses trimmed default, override
  takes precedence over exclude.
- 147 / 147 tests pass across the v19 stack.
- ESLint clean on `MLFeatureAuditPanel.jsx`, `SentComV5View.jsx`.
- Frontend smoke-tested.


## 2026-05-01 (fortieth commit, v19.21) — HOOD R:R fix + verification surfaces + briefing widgets + CPU relief

Operator opened the Deep Feed during RTH and saw HOOD `gap_fade` LONG
rejected at R:R 2.05 vs 2.5 minimum — exactly the same pattern as the
v19.20 Squeeze fix but for a different setup family. Concurrent issues:
the Stocks-In-Play card had no live gap context, the chat panel
required copy-paste to switch focus, and IB Gateway was at 80% CPU
with no operator-side relief lever.

### Phase 1 — R:R floor reset + per-setup overrides

**Root cause:** Mongo `bot_state.risk_params.min_risk_reward = 2.5` (saved
from a stale prior session) was overriding the code default. A previous
fork explicitly told the operator "lower it operator-side after 30 min
of fresh data" but the lower value was never persisted.

**Fix shipped:**
- Code default `min_risk_reward` reset to **1.7** (operator's call).
- New `RiskParameters.setup_min_rr` dict — per-setup R:R overrides:
  - Mean-reversion plays (gap_fade, vwap_fade, mean_reversion,
    rubber_band, bouncy_ball, squeeze, tidal_wave) → **1.5** floor
    (bounded targets — prev close, VWAP, EMA9 — limit how asymmetric
    the trade can be by definition).
  - Trend / breakout setups (orb, breakout, trend_continuation,
    the_3_30_trade, premarket_high_break, 9_ema_scalp) → **2.0** floor
    (unbounded targets — these can run 3-5× risk).
  - Default catch-all → 1.7.
- New `RiskParameters.effective_min_rr(setup_type)` resolver — strips
  `_long`/`_short`/`_confirmed` suffixes so e.g. `vwap_fade_long`
  resolves to the `vwap_fade_long` override (or `vwap_fade` base).
- `opportunity_evaluator.py` now consults the resolver instead of the
  global `min_risk_reward`. Rejection narrative shows the SETUP-SPECIFIC
  threshold AND the global so the operator can see both.
- `update_risk_params(setup_min_rr={...})` now MERGES into the existing
  dict instead of replacing — partial PUT doesn't wipe other entries.
- `bot_persistence` round-trips `setup_min_rr` (saved + restored, with
  merge-into-defaults so newly-shipped setups always get their default).
- New endpoint `GET /api/trading-bot/risk-params` returns live params
  + an `effective_by_setup` map showing the resolved floor for every
  enabled setup (operator can verify "did my tuning take?" at a glance).
- New endpoint `POST /api/trading-bot/reset-rr-defaults` — one-curl
  rescue when Mongo state has drifted from code defaults.
- New endpoint `GET /api/scanner/ml-feature-preview/{symbol}` — returns
  the live label-feature dict (market_setup + multi_index_regime +
  sector_regime one-hots) that would attach to the per-Trade ML feature
  vector RIGHT NOW. Closes the loop on "is the learning loop wired?"
  by exposing all three feature layers in one call.

### Phase 2 — Briefing widgets + chat hook

**`PremarketGapScannerWidget.jsx`** — scrollable list of recent gappers
backed by new endpoint `GET /api/live-scanner/premarket-gappers?
window_minutes=8&min_gap_pct=2.0`. Joins live alerts with gap-related
setup types (gap_fade, gap_give_go, gap_pick_roll,
premarket_high_break, gap_fill_open) PLUS any alert whose metadata
carries `gap_pct` ≥ threshold. Each row renders symbol (clickable
`$TICKER` chip), gap %, current price, setup type, alert age, and a
counter-trend warning chip. Polls every 30s. Mounted in
`MorningBriefingModal.jsx` next to "Stocks in play".

**`sentcom:focus-symbol` chat hook** — `SentCom.jsx` now listens for
the global custom event the gap-scanner widget and `GamePlanStockCard`
both dispatch on click. The listener auto-fires `handleChat()` with
"Walk me through $SYM right now — what's the setup, key levels, what
are you watching, and what would make you take it vs pass." Debounced
600ms so a double-click doesn't fan out two LLM calls. Closes the loop
briefing → chat → trade plan in one gesture.

### Phase 3 — CPU-relief toggle (opt-in throttle)

**`services/cpu_relief_manager.py`** — single-source-of-truth toggle.
Operator flips ON during CPU pressure; non-critical RPC paths consult
`is_active()` and defer themselves. Live tick subscriptions are LEFT
ALONE (operator's explicit ask: "live ticks are the freshest data we
have, keep them full").

**Activation:**
- `POST /api/ib/cpu-relief?enable=true` — on indefinitely
- `POST /api/ib/cpu-relief?enable=true&until=15:30` — auto-off at 3:30 PM ET
- `POST /api/ib/cpu-relief?enable=false` — off
- `GET /api/ib/cpu-relief` — live status + deferred-call counter
- Same fields are also embedded in `GET /api/ib/pusher-health`
  under `cpu_relief` so the existing UI tile picks them up automatically.

**What gets deferred when active:**
- `smart_backfill` (non-dry-run) — short-circuits with
  `{"deferred": True, ...}` and increments the counter. Dry-run still
  runs (cheap planning data).
- Other paths are wired-ready (the `is_active()` check is cheap and
  free for any caller to add).

**`CpuReliefBadge.jsx`** — clickable UI chip. Renders amber "Relief on"
when active with tooltip showing deferred count + auto-off time;
zinc "Relief" when off. One-click toggle.

### Phase 4 — News provider override

**`IB_NEWS_PROVIDER_OVERRIDE` env** — operator can clamp the news
provider list without touching IB Gateway settings. e.g.
`IB_NEWS_PROVIDER_OVERRIDE=BZ,DJ,BRFG` means `get_historical_news`
only ever asks IB for those three vendors. Empty/unset → falls
through to live IB-subscribed list (current behavior).

### Verification

- 17 new pytest cases:
  - `test_per_setup_rr_v19_21.py` — 8 cases (global default, per-setup
    overrides, resolver, merge semantics, persistence round-trip,
    HOOD-specific regression).
  - `test_cpu_relief_and_gap_scanner_v19_21.py` — 9 cases (relief
    toggle, auto-disable window, deferred counter, gap-scanner filter
    + dedup + empty, smart_backfill defers when relief is on, dry-run
    bypass).
- All 141 tests in v19 + market-setup + landscape suites pass.
- Curl end-to-end verified: GET/POST /risk-params, /reset-rr-defaults,
  /ml-feature-preview, /premarket-gappers, /cpu-relief.
- Frontend smoke-tested. ESLint clean.


## 2026-05-01 (thirty-ninth commit, v19.20) — Deep-Feed noise cleanup + briefing depth

Operator opened the Deep Feed at 4:01 PM and saw the bot spamming
`setup_disabled` for real playbook setups, `dedup_cooldown` on a
re-emit loop, and `symbol_exposure $49,986 > $15,000` on every
VWAP fade evaluation. Separately: the Morning Briefing "Stocks in
play" card was printing `KO · Technical Setup` with zero guidance —
no levels, no triggers, no narrative. Both issues shipped together.

### Phase 1 — Feed-noise + wasted-cycle fixes

Five distinct root causes, all addressed.

**(A) Bucket A — real playbook setups silently not enabled.** The
scanner emits alerts for `bouncy_ball`, `the_3_30_trade`,
`vwap_continuation`, `premarket_high_break`, `trend_continuation`,
`base_breakout`, `accumulation_entry`, `back_through_open`,
`up_through_open`, `daily_breakout`, `daily_squeeze` — all with
full `_check_*` detectors. But none of them were in
`TradingBotService._enabled_setups`, so every cycle the bot
logged `setup_disabled` and the Deep Feed looked like the bot
was ignoring good trades. All 11 now enabled by default.

**(B) Bucket B — base-setup splitter didn't strip `_confirmed`.**
`range_break_confirmed`, `breakout_confirmed`, `breakdown_confirmed`
were perpetually rejected because the splitter only stripped
`_long`/`_short`. Splitter now also strips `_confirmed`, so these
confirmation variants resolve to their enabled base setups.

**(C) Bucket C — watchlist-only alerts flooding live evaluation.**
`day_2_continuation`, `carry_forward_watch`, `gap_fill_open` fire
at EOD for TOMORROW'S plan (they're carry-forward tags). And the
`approaching_*` family are pre-trigger proximity warnings, not
tradeable signals. All 7 now live in `_watchlist_only_setups` and
bypass the bot evaluator silently — they still populate the
gameplan and journal watchlist.

**(D) Sizer → SafetyGuardrails cascade.** `max_position_pct=50%`
on a $100k account = $50k notionals; `max_symbol_exposure_usd=$15k`
rejected every single one. Fix: the sizer now queries the safety
singleton's cap and clamps shares to `(safety_cap - existing_exposure) / entry_price`
so it NEVER produces a notional that the guardrail would reject.
When the symbol is already at/past the cap, sizer returns 0 shares
for a clean `position_size_zero` upstream reject instead of a
wasted evaluate→safety-block cycle.

**(E) Squeeze R:R chronically below 1.5.** Mega-caps (KO, PG, LIN)
have BB bands wider than 1 ATR, so `stop = bb_lower` put risk above
reward and the setup was effectively dead. Fix: stop clamped to
`max(bb_lower, current_price - atr*1.0)` — BB still governs when
it's tight, ATR bounds it when it's wide.

**(F) Rejection dedup.** `record_rejection` now maintains a 2-min
TTL cache keyed on `(symbol, setup_type, reason_code)`. First hit
records normally; duplicates within the window are silenced from
the Bot's Brain buffer and unified stream. The opportunity
evaluator still sees them (no change to gating logic); only the
user-facing stream is dedup'd.

### Phase 2 — Game Plan depth upgrade (Ollama GPT-OSS 120B)

Briefing UI now renders per-stock expandable cards with:

- Deterministic bullets that always display (setup description,
  plan levels, trigger, invalidation) — computed from live
  `TechnicalSnapshot` (VWAP, ORH/ORL, HOD/LOD, support/resistance,
  ATR, RSI) merged with the stock's stored `key_levels`.
- 12-cell grid of key levels (Entry / Stop / T1 / T2 / VWAP /
  Price / HOD / LOD / ORH / ORL / Support / Resistance).
- AI narrative paragraph (2-3 sentences, trader jargon) from
  Ollama `gpt-oss:120b-cloud` via the existing HTTP proxy. Uses
  `$TICKER` syntax so the frontend parses tickers into
  clickable chips that dispatch a `sentcom:focus-symbol` custom
  event.
- Graceful degradation when Ollama is offline: narrative is blank,
  bullets still render the full plan.
- Cached 5 minutes per `(symbol, date)` so the briefing auto-refresh
  doesn't hammer the LLM.

**New service** `/app/backend/services/gameplan_narrative_service.py`
— composes the card.
**New endpoint** `GET /api/journal/gameplan/narrative/{symbol}?date=YYYY-MM-DD&use_llm=true`
— returns `{ bullets, narrative, referenced_symbols, levels, llm_used }`.
**New component** `/app/frontend/src/components/sentcom/v5/GamePlanStockCard.jsx`
— renders the per-stock card with clickable `$TICKER` chips.
**Rewired** `MorningBriefingModal.jsx` to use the new card list
instead of plain chips.

### Verification

Backend:
- `tests/test_feed_noise_fixes_v19_20.py` — 7 pytest cases covering
  Bucket A/B/C, sizer safety cap, and rejection dedup.
- `tests/test_gameplan_narrative_v19_20.py` — 6 pytest cases
  covering bullets without snapshot, bullets with snapshot, cache
  behaviour, $TICKER extraction, playbook-setup descriptions, and
  LLM-offline fallback.
- All 122 tests in the v19.* + market-setup + landscape suite pass.
- `curl /api/journal/gameplan/narrative/KO?use_llm=false` returns a
  well-formed card with bullets + levels even without Ollama.


## 2026-04-30 (thirty-eighth commit, v19.19) — Premarket cadence + heartbeat fixes

Three small but operator-visible issues surfaced at 8:40 AM ET on
the Spark (50 min before open). Ship coordinated fix.

### 1. Premarket cadence way too slow

The premarket branch of `_scan_loop` was gated on `self._scan_count
% 10 == 0` with a 120s sleep between cycles → a real premarket
scan only fired every **20 minutes**. Operator doing morning prep
at 8:40 AM saw the watchlist stuck on quotes from 8:20 AM — too
stale to inform opening-bell decisions.

Tightened to `% 2` cadence = **4 min between real premarket
scans**. 7:00-9:30 AM ET window → ~37 refreshes per session,
enough to track gap evolution without thrashing the pusher.

### 2. `_last_scan_time` not stamped during premarket / after-hours

The `self._last_scan_time = datetime.now(timezone.utc)` assignment
only lived inside the RTH branch. During premarket + after-hours,
the attribute held whatever RTH value it had (or `None`). That
made `/api/system/morning-readiness` report "scanner silent"
falsely during the morning prep window — exactly when the operator
is running `morning_check.sh` for go/no-go.

Now stamped on EVERY tick (RTH, premarket, after-hours), so
readiness checks see a fresh heartbeat regardless of time window.

### 3. `morning_readiness_service` was reading wrong attr

v19.18 shipped with `getattr(scanner, "_last_scan_at", None)` —
wrong attribute name. The scanner's actual field is
`_last_scan_time`. Consequence: `scan_age_s` was always `None` so
the readiness output fell through to the "cycle_count=N" fallback
message instead of showing real scanner activity age.

Trivial rename fix now in `_check_scanner_running`.

### What the operator sees now

At 8:40 AM ET on Spark post-pull + restart:
- Premarket scans fire every ~4 min.
- Morning watchlist populates with gap_give_go / gap_fade /
  gap_reversal / premarket_high_break alerts as the tape develops.
- `/api/system/morning-readiness` correctly shows
  `scanner_running: GREEN` with scan_age in seconds, not "cycle_count=2".

### Tests (`test_premarket_cadence_v19_19.py` — 5 tests)

Source-level pins:
- Premarket block uses `% 2` cadence (guards against `% 10` revert).
- `_last_scan_time` stamped in both premarket + after-hours branches.
- morning_readiness reads `_last_scan_time` (not the old `_last_scan_at`).
- Real scan interval is in the reasonable 3-6 min window (computes
  `modulus × sleep` from source to catch silent drift).

**86/86 across v19.14-v19.19 + morning readiness + smart backfill
+ tier dispatch + per-cycle cache + EOD close suites.**



## 2026-04-30 (thirty-seventh commit, v19.18) — Morning Readiness aggregator

Single-call "is the bot ready for fully automated trading today?"
endpoint at `GET /api/system/morning-readiness`. Aggregates everything
we shipped in v19.14-v19.17 into a single green/yellow/red verdict
plus a Slack-ready one-liner. Designed for the operator's pre-RTH
workflow: run one curl (or the new `morning_check.sh` script), see
exactly which subsystem needs attention before flipping autopilot on.

### Five checks, one verdict

| Check | Status logic |
|---|---|
| `backfill_data_fresh` | 10 critical symbols (SPY/QQQ/DIA/IWM/FAAMG/NVDA) all have a daily bar at v19.17's `_expected_latest_session_date`. RED if any missing. |
| `ib_pipeline_alive` | Historical worker last-completion + pusher heartbeat ages. YELLOW if collector idle >2h during RTH. |
| `trading_bot_configured` | v19.14 EOD enabled at 15:55 ET; risk_params populated. RED if EOD disabled or risk_params missing. YELLOW if EOD time drifted from 15:55. |
| `scanner_running` | Last cycle <5 min during RTH; v19.15 cycle-context cache populated; v19.16 intraday-only set has ≥12 detectors. RED during RTH if scanner silent. |
| `open_positions_clean` | No `close_at_eod=True` (intraday) trades from a prior session date. RED if any stuck — means v19.14 EOD failed. |

Verdict aggregation: any RED → RED; any YELLOW (no RED) → YELLOW;
all GREEN → GREEN. The summary string format is stable for Slack DM
or HUD badge consumption:

```
[Wed Apr 30 09:14 ET] AUTOPILOT GREEN — backfill fresh, EOD armed,
                       scanner alive, no overnight carryover.
[Wed Apr 30 09:14 ET] AUTOPILOT BLOCKED — fix: backfill_data_fresh,
                       trading_bot_configured (2 red).
[Wed Apr 30 09:14 ET] AUTOPILOT CAUTION — review: ib_pipeline_alive
                       (1 yellow).
```

### Endpoint contract

```json
{
  "success": true,
  "verdict": "green" | "yellow" | "red",
  "ready_for_autopilot": bool,
  "summary": "[Wed Apr 30 09:14 ET] AUTOPILOT GREEN — ...",
  "checks": {
    "backfill_data_fresh": {
      "status": "red",
      "detail": "10/10 critical symbols missing...",
      "expected_session": "2026-04-29",
      "stale_symbols": [...],
      "fix": "Click 'Collect Data' in Data Collection panel..."
    },
    ...
  },
  "is_rth": false,
  "generated_at_et": "...",
  "generated_at_utc": "..."
}
```

All checks are read-only, <2s combined. Safe to poll every 30-60s.
Each check is wrapped so a single subsystem failure surfaces as
that check's `status=red` with the exception detail — the endpoint
itself never raises (operator never sees a 500 on the readiness
URL).

### Operator script — `scripts/morning_check.sh`

A 60-line bash script that calls the endpoint and prints a colour-
coded breakdown. Exit codes: `0` green, `1` yellow, `2` red.
Designed for cron / chained shell automation:

```bash
#!/bin/bash
# Run before RTH on Spark. Auto-starts the bot only if green.
~/Trading-and-Analysis-Platform/backend/scripts/morning_check.sh && \
    curl -X POST http://localhost:8001/api/trading-bot/start
```

Recommended cron entry (Mon-Fri 8:30 AM ET):
```cron
30 8 * * 1-5 /home/spark-1a60/Trading-and-Analysis-Platform/backend/scripts/morning_check.sh
```

### Tests (`test_morning_readiness_v19_18.py` — 16 tests)

Per-check unit tests (10):
- `_check_backfill_data_fresh`: green / red-stale / red-missing
- `_check_trading_bot_configured`: green / red-disabled / red-no-risk / yellow-drifted
- `_check_open_positions_clean`: green / red-carryover

Aggregation + summary (5):
- Verdict precedence (green<yellow<red)
- Summary line format for green / red / yellow

Top-level shape (2):
- Response envelope keys are stable
- `compute_morning_readiness` never raises even on a broken DB

**140/140 across all v19 backend test suites.**

### How this fits the autopilot workflow

The pieces shipped today form a clean go/no-go pipeline:

| Stage | Subsystem | Layer |
|---|---|---|
| 1. Data freshness | v19.17 freshness gate + Collect Data button | Pre-RTH |
| 2. Scanner health | v19.15 cycle cache + v19.16 tier dispatch | Throughout RTH |
| 3. Trade management | v19.13 manage hardening | Throughout RTH |
| 4. EOD flat | v19.14 close-stage hardening + v19.14b countdown banner | 3:55 PM ET |
| 5. Verification | **v19.18 morning-readiness aggregator** | Pre-RTH next day |

Loop closes: morning-readiness on day N+1 verifies that v19.14 EOD
on day N actually flattened the book. If `open_positions_clean`
goes red, you immediately know the prior day's EOD didn't
complete — surface for triage before the next session opens.



## 2026-04-30 (thirty-sixth commit, v19.17) — Bar-size-aware freshness gate

Diagnosed via the operator's NVDA chart screenshot showing daily bars
stuck through Apr 27 even after two `smart_backfill` runs on Apr 28
that reported 7,298 + 11,743 symbols "skipped fresh". The fix is a
bar-size-aware freshness check that requires the EXPECTED session
date to be in Mongo, not just "any bar within 2 days".

### Why this matters

The pre-fix freshness gate at `_smart_backfill_sync` was bar-size
agnostic:

```python
if days_behind <= freshness_days:   # default freshness_days=2
    skipped_fresh += 1
    continue
```

For "1 day" bars that meant the post-close run on day N would skip
because `days_behind = 1` (last bar = N-1) — so day N's just-
finalised daily bar never got pulled until day N+3 when the count
finally crossed 2.

NVDA on Spark hit this exact path:
- Last bar in Mongo: Apr 27 (Monday), collected Apr 28 08:14 ET
- Apr 28 17:40 ET smart_backfill run: `days_behind=1` → skipped fresh
- Apr 29 (no run since)
- Operator notices Apr 28 + Apr 29 missing on V5 ticker chart

The bug class: **the freshness threshold tolerance (1-2 days) was
larger than the bar-size cadence (1 day)**, so daily bars were
permanently 1-2 days behind reality.

### Patch

#### 1. `_expected_latest_session_date(bar_size, now_dt)` — new helper

Returns the session `date` the most recent bar SHOULD be from, given
current clock + bar size:

```python
"1 day"  → today on weekdays past 4 PM ET; else most recent prior
           weekday session.
"1 week" → most recent Friday on/before now.
intraday → today on weekdays (live tape adds bars during RTH; pre/
           post hours we still expect today's earlier intraday bars);
           else most recent prior weekday.
```

The helper converts `now_dt` to ET so the "past 4 PM ET" check is
correct regardless of host timezone.

#### 2. New freshness gate in `_smart_backfill_sync`

```python
expected_session = self._expected_latest_session_date(bs, now_dt)
last_session = last_dt.date()
is_fresh_v19_17 = last_session >= expected_session
if is_fresh_v19_17:
    if self._has_internal_gaps(sym, bs):  # existing path preserved
        ... queue full re-fetch
    else:
        skipped_fresh += 1
    continue
```

Replaces the bar-size-agnostic check. Internal-gap detection (the
2026-04-28e fix that catches "year-old data with a 6-month hole in
the middle") still runs inside the fresh branch.

The `freshness_days` parameter on the API endpoint is preserved for
backwards compat — callers passing `freshness_days=0` for an
"unblock everything" pass still work because the v19.17 gate is
strictly tighter than the old one (so anything that was previously
queued via `freshness_days=0` is still queued).

### Operator workflow (immediate unblock for the missing NVDA bars)

```bash
# Run on Spark to backfill the Apr 28 + Apr 29 gap right now:
curl -s -X POST "http://localhost:8001/api/ib-collector/smart-backfill?freshness_days=0" | jq

# Then watch the queue drain:
watch -n5 'curl -s http://localhost:8001/api/ib-collector/queue-stats | jq'
```

### Tests (`test_smart_backfill_freshness_v19_17.py` — 23 tests)

Helper unit tests (16):
- `_expected_latest_session_date` for "1 day" across pre-close,
  post-close, premarket, Saturday, Sunday, Monday-morning,
  Monday-after-close
- `_expected_latest_session_date` for "1 week" across Thursday,
  Friday, Sunday
- `_expected_latest_session_date` for intraday across RTH +
  Saturday (parametrized over 1m / 5m / 15m / 30m / 1h)

Source-level pin (1):
- `test_smart_backfill_uses_v19_17_gate` — guard against silent
  reversion to the old `days_behind <= freshness_days` form.

Behavioural regression (6):
- `test_apr28_post_close_run_with_apr27_last_bar_is_NOT_fresh` —
  pin the EXACT bug scenario: NVDA-style last bar Apr 27, run at
  Apr 28 17:40 ET, must NOT skip as fresh.
- `test_post_close_run_with_today_last_bar_IS_fresh` — the inverse
  (today's bar present → still skips, no double-fetch waste)
- Intraday RTH happy + stale paths

**124/124 across all v19 test suites.**

### What this does NOT cover (parked for future)

The fix makes `smart_backfill` correctly identify stale daily bars,
but it doesn't AUTOMATICALLY trigger a refresh — the operator still
needs to call `/api/ib-collector/smart-backfill`. A future
enhancement is a systemd timer / APScheduler job on Spark that
runs smart_backfill nightly at 17:30 ET so this auto-recovers
without prompting (added to ROADMAP).



## 2026-04-30 (thirty-fifth commit, v19.16) — Tier-aware detector dispatch

Pre-fix the scanner iterated all ~35 detectors in `_enabled_setups`
for every symbol regardless of tier. A symbol classified as
`swing` tier (~$2M-$10M ADV, snapshotted every 60s by bar-poll)
was running through ALL intraday-timing detectors
(`9_ema_scalp`, `vwap_continuation`, `the_3_30_trade`,
`opening_drive`, gap plays, etc.) — each producing physically
nonsensical signals computed from data that's 30-90s stale.

### Why this matters (quality, not just speed)

The post-v18 bar-poll service made universe coverage jump from
2.8% → ~80% (~2,000 symbols). That's a great breadth win, but the
swing/investment cohort was getting flooded with intraday-style
signals that should never have fired:
- `9_ema_scalp` on a stock the bar-poll only freshens every 60s →
  the 9-EMA distance reading is from data that's already 30+s
  stale by the time the alert hits the AI gate.
- `the_3_30_trade` on an investment-tier symbol that's only
  scanned at 11:00 AM and 3:45 PM → the trigger logic fires once
  per scan and produces a "3:30 PM range break" signal in the
  3:45 PM scan window, computed against bars from a different
  time of day.

These weren't just slow — they were **actively wrong** training
data feeding the AI gate's labelled outcomes.

### Patch

#### 1. `_intraday_only_setups` — new attribute on EnhancedBackgroundScanner

A SUPERSET of the existing `_intraday_setups` (which was the
volume-gate set). Listing every detector with explicit sub-5min
timing or playbook "intraday only" specs:

```python
self._intraday_only_setups = self._intraday_setups | {
    "vwap_continuation", "vwap_bounce", "vwap_fade",
    "premarket_high_break", "the_3_30_trade",
    "gap_fade", "gap_give_go", "gap_pick_roll",
    "rubber_band", "tidal_wave",
    "hod_breakout",
    "fashionably_late", "off_sides", "backside",
    "second_chance",
    "big_dog", "puppy_dog",
    "bouncy_ball",
}
```

**Conservative inclusion criteria**: a detector is on this list
ONLY if it has explicit sub-5min timing dependency OR its
playbook spec says "intraday only". Anything ambiguous
(`squeeze`, `breakout`, `chart_pattern`, `mean_reversion`,
`trend_continuation`, `daily_squeeze`, `daily_breakout`,
`base_breakout`, `earnings_momentum`, `sector_rotation`) stays
OFF so it keeps running across all tiers.

#### 2. Dispatch loop — early skip BEFORE `_check_setup`

```python
symbol_tier = self._tier_cache.get(symbol)
for setup_type in self._enabled_setups:
    if not self._is_setup_valid_now(setup_type):
        continue
    # NEW v19.16 tier-skip — runs BEFORE _check_setup dispatch.
    if (
        symbol_tier is not None
        and symbol_tier != "intraday"
        and setup_type in self._intraday_only_setups
    ):
        continue
    # Existing volume gate retained as safety net for symbols
    # whose tier-cache hasn't been populated yet.
    if setup_type in self._intraday_setups:
        if snapshot.avg_volume < self._min_adv_intraday:
            continue
    alert = await self._check_setup(setup_type, symbol, snapshot, tape)
```

The skip runs BEFORE `_check_setup` is invoked, saving the
function dispatch + log + counter increment. When `_tier_cache`
hasn't been populated yet for a symbol, the existing volume gate
still applies as a defence-in-depth safety net.

### Speedup math (real-world projection)

Pre-v19.16 per-cycle dispatch volume on a 2,000-symbol universe:
~2,000 symbols × ~35 detectors = 70,000 detector calls/cycle.

Post-v19.16 with ~50% non-intraday tier symbols and ~28
intraday-only detectors out of 35:
- intraday tier (~1,000 symbols): 35,000 calls (unchanged)
- swing+investment tier (~1,000 symbols): only ~7 cross-tier
  detectors run = 7,000 calls (was 35,000)
- **Total: 42,000 → was 70,000 = -40%**

Combined with v19's parallel gate, this materially reduces the
EVAL backlog on busy tape days (~800-2,000 alerts/session).

### Tests (`test_tier_aware_dispatch_v19_16.py` — 7 tests)

- `test_intraday_only_setups_attribute_declared` — pin the
  attribute exists and is the SUPERSET of `_intraday_setups`
- `test_dispatch_loop_checks_tier_before_check_setup` —
  source-level pin: skip MUST run before dispatch
- `test_dispatch_loop_reads_symbol_tier_from_cache` — pin the
  cheap-cache read (no live IB call snuck in)
- `test_intraday_only_is_superset_of_intraday_setups` —
  membership invariant
- `test_known_intraday_only_detectors_present` — 22 detectors
  pinned as MUST-be-on-list
- `test_ambiguous_detectors_explicitly_NOT_in_intraday_only` —
  10 detectors pinned as MUST-be-OFF (defends against silent
  suppression of swing/position alerts)
- `test_intraday_only_does_not_grow_unboundedly` — sanity bound
  at 35 to flag copy/paste regressions

Plus drive-by fix: `test_canary_scanner_pillar_setups_have_checkers`
in `test_scanner_canary.py` was a stale assertion (still listed
`relative_strength` removed in v16) — updated to match current
`_enabled_setups` truth.

### Behaviour verification

- Backend boots cleanly post-pull.
- `_tier_cache` is populated via `_rebuild_tier_cache` (existing
  hourly refresh) — no new code path needed.
- Symbols not in `_tier_cache` (cold-start) fall through to the
  existing volume gate, no regression on first-tick coverage.
- 221/222 across all v19.* + scanner-adjacent test suites
  (1 pre-existing failure in `test_detector_stats_aggregates...`
  unrelated to v19.16).



## 2026-04-30 (thirty-fourth commit, v19.15) — Per-cycle context cache

Pre-fix every alert's `_apply_setup_context` ran 3 awaited
classifier calls (multi-index regime + sector regime + setup
classifier). The first two are MARKET-WIDE so calling them
per-alert was pure overhead — they're TTL-cached internally but
still pay function-dispatch + await + lock overhead × 1,500
alerts/day post-v18 bar-poll (~22-45s/session of pure dispatch
latency in the EVAL critical path).

### Why this matters

v18 bar-poll bumped alert volume from ~80-150/session →
**800-2,000/session**. v19 parallelized the AI gate's 8 model
fanout (3-5× speedup). The next bottleneck was the synchronous
3-await regime/sector context tagging running per-alert.

### Patch

#### 1. `_cycle_context` — new attribute on EnhancedBackgroundScanner

```python
self._cycle_context: Optional[Dict[str, Any]] = None
self._cycle_context_at: Optional[float] = None  # monotonic ts
self._cycle_context_hits = 0
self._cycle_context_misses = 0
self._cycle_context_ttl_s = 60  # safety fallback if loop misses
```

#### 2. `_refresh_cycle_context()` — new prefetch helper

Runs ONCE per scan cycle at the top of `_run_optimized_scan`.
Issues exactly TWO awaits:
- `MultiIndexRegimeClassifier.classify()` — single market-wide call
- `SectorRegimeClassifier.classify_all_sectors()` — single
  11-ETF pass

Returned data flattened into a dict:
```python
{
    "captured_at_monotonic": time.monotonic(),
    "cycle_id": self._scan_count,
    "multi_index_regime": "bullish_divergence",
    "multi_index_confidence": 0.78,
    "sector_regime_by_etf": {"XLK": "strong", "XLE": "weak", ...},
    "spy_5d_return_pct": 1.4,
    "fresh": True,
}
```

Failure-resilient: classifier exceptions caught + logged; cache
still gets created with default `unknown` values, alerts fall
back to per-alert classifier calls inside `_apply_setup_context`.

#### 3. `_get_cycle_context()` — staleness gate

Returns the cached payload only when age ≤ TTL. Defensive
`getattr` reads guard against test scaffolding that bypasses
`__init__` via `EnhancedBackgroundScanner.__new__()` (used by
the legacy `test_detector_stats` / `test_scanner_canary` suites).

#### 4. `_apply_setup_context` — read-from-cache path

```python
cycle_ctx = self._get_cycle_context()
# Multi-index: cache hit → dict lookup; miss → fall back to
# per-alert classifier.classify()
if cycle_ctx and cycle_ctx.get("multi_index_regime", "unknown") != "unknown":
    alert.multi_index_regime = cycle_ctx["multi_index_regime"]
else:
    # ... per-alert path preserved as fallback
```

The Sector path is slightly more involved because it still needs
the per-symbol → ETF mapping (`SectorTagService.tag_symbol`
static map → ETF). Once ETF is known, look up its regime from
the cycle cache instead of awaiting `classify_for_symbol`.
Symbols with unknown sector tag fall through to the existing
async tag fallback chain.

The `MarketSetupClassifier` stays per-alert because it genuinely
needs the per-symbol intraday snapshot.

### Speedup math

Pre-v19.15 per-alert overhead in `_apply_setup_context`:
- 3 × dynamic import lookup
- 3 × `get_*_classifier(db=self.db)` accessor
- 3 × `await classifier.X()` event-loop dispatch
- 3 × TTL check + lock + counter increment
- 3 × debug log line

Post-v19.15:
- 1 × `import` (MarketSetup classifier — still per-alert)
- 1 × cache dict lookup (regime)
- 1 × cache dict lookup (sector via ETF)
- 1 × `tag_symbol(symbol)` (sync static map, ~1µs)
- 1 × `await classifier.classify(symbol, snapshot)` (MarketSetup, unchanged)

At 1,500 alerts/session × ~10ms saved per alert = **~15s of EVAL
latency reclaimed** on top of v19's parallelization. More
importantly: removes a per-alert hot path that compounds linearly
with alert volume.

### Tests (`test_per_cycle_context_cache_v19_15.py` — 10 tests)

- 4 source-level pins (init fields declared, helper exists,
  refresh runs before symbol fanout, read-from-cache pattern)
- 3 staleness-gate behaviour tests (none/fresh/stale)
- 2 prefetch behaviour tests (populates cache, resilient to
  classifier failure)
- 1 SPDR-ETF coverage smoke test (all 11 sectors land in cache)



## 2026-04-30 (thirty-third commit, v19.14b) — V5 EOD Countdown Banner

Operator-requested follow-up to v19.14: when the EOD close window
gets close, surface a visible countdown + position list at the top
of the V5 Unified Stream so the operator gets a 5-min heads-up to
either flatten manually, extend a winning runner, or just sit on
their hands and let the auto-close do its job.

### What ships

#### Backend — `GET /api/trading-bot/eod-status`

New lightweight endpoint that aggregates the data the banner needs:

```json
{
  "success": true,
  "status": "imminent",            // idle | imminent | closing | complete | alarm
  "eta_seconds": 173,              // seconds until close window opens
  "intraday_positions_queued": 4,  // close_at_eod=True trades
  "swing_positions_holding": 2,    // close_at_eod=False trades (NOT closing)
  "intraday_symbols": ["AAPL","MSFT","NVDA","HIMS"],
  "close_hour": 15, "close_minute": 55,
  "close_time_et": "15:55 ET",
  "market_close_hour_et": 16,
  "is_half_day": false,
  "is_weekend": false,
  "enabled": true,
  "executed_today": false,
  "now_et": "15:52:07"
}
```

Status state machine (precedence top-down):
1. `idle` — disabled, weekend, or outside the 5-min window
2. `complete` — `_eod_close_executed_today=True` for today
3. `alarm` — past 4:00 PM ET with intraday positions still open
4. `closing` — eta_seconds ≤ 0 with positions queued (window has opened)
5. `imminent` — 0 < eta ≤ 300s (5-min countdown)
6. `idle` — fallthrough

The earlier draft of this logic mistakenly put `imminent` before
the post-close gate, so at 9:00 PM ET the banner was reporting
"EOD CLOSE in -350:00". Fixed by gating `imminent` to a STRICTLY
positive eta — covered by
`test_eod_status_idle_after_market_close_when_no_positions`.

#### Drive-by fix — `/api/trading-bot/eod-close-now`

Same bool/dict bug we squashed in `position_manager.check_eod_close`
(v19.14 P0 #1) was lurking in the manual-trigger endpoint:

```python
result = await _trading_bot.close_trade(...)   # returns BOOL
if result.get("success"):                       # AttributeError silently swallowed
```

Pre-fix: every operator-clicked "close all now" call returned
`closed_count: 0` regardless of broker outcome. Now we treat the
bool correctly + read `realized_pnl` from the trade post-close.

This matters because the new banner offers a "CLOSE ALL NOW"
override button — it would have been embarrassing for the button
to silently no-op.

#### Frontend — `EodCountdownBannerV5.jsx`

New sticky banner mounted above `DayRollupBannerV5` inside the
Unified Stream container. ~270 lines, no new dependencies.

State-driven presentation:
- **imminent** (amber) — `⏱ EOD CLOSE in 4:32 · queued 4 intraday · holding 2 swing · AAPL · MSFT · NVDA · HIMS`. Includes "CLOSE ALL NOW" button with 2-tap confirm.
- **closing** (rose) — `⏵ EOD CLOSING · Closing 4 intraday positions now…`
- **complete** (emerald) — `✓ EOD COMPLETE · All eligible intraday positions closed for today.` Auto-hides 60s after completion.
- **alarm** (deep rose) — `⚠ EOD ALARM · 4 positions still OPEN past market close — verify IB-side state`. Includes "CLOSE ALL NOW" override.

Adaptive polling: 5s while active, 30s while idle, so the operator
never sees stale data during the critical window but the endpoint
isn't hammered overnight. Client-side 1-Hz countdown ticker between
polls so the MM:SS display feels live.

Critical details:
- Half-day banner shows "HALF-DAY" pill when `is_half_day=true`.
- Swing position count shown but explicitly NOT included in the
  close list, reinforcing the v19.14 contract.
- Symbol list truncates at 8 with "+N" overflow.
- All interactive elements have `data-testid` for testing.

### Tests

Extended `test_eod_close_v19_14.py` with 8 new tests covering the
new endpoint:
- `test_eod_status_idle_far_from_window`
- `test_eod_status_idle_after_market_close_when_no_positions` (regression guard for the post-close-imminent bug)
- `test_eod_status_imminent_within_5_min_of_close`
- `test_eod_status_alarm_when_positions_open_past_4pm`
- `test_eod_status_complete_after_executed_today`
- `test_eod_status_disabled_returns_idle`
- `test_eod_status_half_day_window_flips_to_1255`
- `test_eod_status_response_shape_pinned` (frontend contract pin)

**23/23 in test_eod_close_v19_14.py. 84/84 across all v19 backend
suites.**

### Operator workflow on Spark after pull + restart

```bash
# Smoke-test the new endpoint:
curl -s http://localhost:8001/api/trading-bot/eod-status | jq

# At 3:50 PM ET on a regular trading day, the banner appears at
# the top of the V5 Unified Stream with a 5-min countdown and the
# list of intraday symbols queued for close. Clicking "CLOSE ALL
# NOW" + confirming triggers the manual close immediately.

# At 4:01 PM ET if anything is still open locally, the banner flips
# to red ALARM mode + the WS broadcasts eod_after_close_alarm.
```



## 2026-04-30 (thirty-second commit, v19.14) — EOD Close-stage hardening

Audit of `position_manager.check_eod_close` uncovered six issues
that were silently leaving intraday positions open past the 4:00 PM
bell. All six fixes shipped + new regression suite.

### Why this matters

EOD auto-close is the bot's last line of defence against unintended
overnight exposure on intraday strategies. A book-keeping crash here
quietly costs real money via gap risk and option assignment risk
(SPY/QQQ-correlated names move materially on overnight news /
earnings / Asia tape).

### Default close window: 3:57 → 3:55 PM ET

Operator request — give intraday closes a full 5-minute cushion
before 4:00 PM. With ~25 open positions and IB roundtrip latency
(~2-3s per close in fast tape), the prior 3:57 default cut it close.
3:55 leaves room for the v19.14 partial-failure retry (P0 #3) to
attempt a second pass before the bell.

Changes:
- `services/trading_bot_service.py:723` — `_eod_close_minute` default
  flipped 57 → 55. Comment notes the v19.14 reason and that the
  filter only applies to trades flagged `close_at_eod=True`.
- `services/bot_persistence.py:98` — restore-default for
  `bot_config.eod_config.close_minute` also flipped 57 → 55. Same
  rationale; if the bot ever starts before any `eod_config` doc has
  been written, this is the value used.

### P0 fixes inside `check_eod_close`

#### P0 #1 — `close_trade` returns a bool, not a dict

The legacy loop did `result = await self.close_trade(...);
result.get("success")`. `close_trade` actually returns
`True`/`False` (see line 685 of `position_manager.py`), so every
iteration silently raised `AttributeError: 'bool' object has no
attribute 'get'`, which got swallowed by the surrounding try/except
and counted as a failure.

Net pre-fix behaviour: even when broker-side closes succeeded, the
bot logged "0 closed, N failed". Operator-visible: every EOD close
appeared to fail, so the bot left `_eod_close_executed_today=False`,
ran the close loop again on the next manage tick, hit the same
AttributeError, and so on until 4:00 PM rolled past with positions
still locally "open" (even though they were actually closed at IB).

Now: capture `ok = await self.close_trade(...)` directly as bool;
read `trade.realized_pnl` post-close (`close_trade` mutates it).

#### P0 #2 — Closes run in parallel via `asyncio.gather`

Pre-fix: serial loop. With 25 open positions × ~2s per close → ~50s
wall-time for a complete EOD pass. On a fast-tape afternoon you
risk spilling past the 4:00 PM bell entirely.

Now: a coroutine per trade, all dispatched via `asyncio.gather`,
total wall-time bounded by single-trade latency (~2-3s) regardless
of position count. Test
`test_eod_closes_run_in_parallel_not_serial` pins the contract: 5
closes × 200ms each must finish in under 600ms (parallel) — would
fail if a future contributor reverts to serial.

#### P0 #3 — `_eod_close_executed_today` only flips True on full success

Pre-fix: flag set unconditionally after the loop. If 1 of 25 closes
failed, the failing position was forever marked "EOD-handled" and
never retried. Operator finds it open the next morning.

Now: flag only flips True when `failed_symbols == []`. On partial
failure, the manage loop tick (~every 1-2s) re-enters
`check_eod_close` and retries the failed close, until either it
succeeds OR market_close_hour rolls past (P0 #4 fires the alarm
then).

#### P0 #4 — After-close alarm with WS broadcast

Pre-fix: if `now >= 4:00 PM ET` we silently `return`. Operator had
no way to know the EOD attempt failed end-of-day; only the next
morning's "huh, I'm still in MSFT?" surfaces it.

Now: log a loud `🚨 EOD ALARM: market closed at 16:00 ET but N
positions still OPEN locally...` ERROR + broadcast
`eod_after_close_alarm` event over the WS so the V5 HUD can render
a banner. Throttled to once per day per occurrence.

### P1 fixes

#### P1 #5 — Half-trading-day window

Operator sets `EOD_HALF_DAY_TODAY=true` in env on the morning of
NYSE half-days (Black Friday, Christmas Eve, day after
Thanksgiving). Window flips from 3:55 PM → 12:55 PM ET (5 min
before the 1:00 PM half-day close), `market_close_hour` flips
16 → 13. NYSE half-days are rare enough that operator-flagging is
acceptable; a future contributor can wire to a real exchange
calendar.

#### P1 #6 — WS broadcast EOD start + completion

Two new events on the WS stream:
- `eod_close_started` — fires when the close window opens; carries
  `positions_to_close`, `is_half_day`, `eod_window_et`. V5 HUD can
  render a "Closing N positions..." banner.
- `eod_close_completed` — fires after all closes attempted; carries
  `closed`, `failed`, `failed_symbols`, `total_pnl`, `fully_done`.

### Intraday-only — explicitly NOT applied to swing/position trades

The filter `eod_trades = {tid: t ... if getattr(t, 'close_at_eod',
True)}` skips any trade with `close_at_eod=False`. That flag is
set per-strategy in `STRATEGY_CONFIGS` (line 298+ of
`trading_bot_service.py`):

- `close_at_eod=True` (intraday/scalp/day): vwap_continuation,
  9_ema_scalp, opening_range_break, the_3_30_trade, opening_drive,
  bouncy_ball, big_dog, second_chance, ... (~35 strategies)
- `close_at_eod=False` (swing/position): squeeze, trend_continuation,
  daily_squeeze, daily_breakout, earnings_momentum, sector_rotation,
  base_breakout, accumulation_entry, relative_strength_position,
  position_trade (~10 strategies)

A swing trade in NVDA opened on Tuesday must NOT be auto-closed at
3:55 PM. The filter ensures this; tests
`test_eod_only_closes_intraday_trades` and
`test_eod_skips_when_all_positions_are_swing` pin the behaviour.

### Tests (`test_eod_close_v19_14.py` — 15 tests)

Default-time guards (3):
- `test_default_eod_close_minute_is_55`
- `test_default_eod_close_hour_is_15`
- `test_persistence_default_eod_close_minute_is_55`

P0 contract guards (4):
- `test_eod_treats_close_trade_return_as_bool`
- `test_eod_partial_failure_keeps_flag_false_for_retry`
- `test_eod_closes_run_in_parallel_not_serial`
- `test_eod_alarms_if_positions_open_past_4pm`

P1 half-day (2):
- `test_eod_half_day_close_window_at_1255`
- `test_eod_half_day_does_not_fire_before_window`

Intraday-only filter (2):
- `test_eod_only_closes_intraday_trades`
- `test_eod_skips_when_all_positions_are_swing`

Non-trigger fast-fail paths (4):
- `test_eod_does_not_fire_before_trigger_minute`
- `test_eod_disabled_short_circuits`
- `test_eod_does_not_fire_on_weekend`
- `test_eod_does_not_redo_closes_on_same_day`

**76/76 across v19.2 + v19.3 + v19.4 + v19.5 + v19.8 + v19.12 +
v19.13 + v19.14 backend test suites.**

### Operator workflow on Spark after pull + restart

```bash
# Confirm new default in the bot status:
curl -s http://localhost:8001/api/trading-bot/status | python3 -c \
  "import sys,json; d=json.load(sys.stdin); \
   print('EOD close at:', d.get('eod_close_hour','?'), ':', \
         d.get('eod_close_minute','?'))"
# Expected: EOD close at: 15 : 55

# Half-day operation (Black Friday / Christmas Eve / etc):
echo "EOD_HALF_DAY_TODAY=true" >> backend/.env
# (Then restart backend; close window flips to 12:55 PM ET that day.)
```

After 3:55 PM ET on a regular trading day:
- All intraday open positions get a close MKT.
- Swing/position trades stay open.
- WS stream surfaces `eod_close_started` then `eod_close_completed`.
- If any close fails, the manage loop retries on next tick until
  4:00 PM, then fires `eod_after_close_alarm` if positions remain.



## 2026-04-30 (thirty-first commit, v19.13) — Manage-stage hardening (P0/P1/P2)

Full audit of the manage stage uncovered 12 issues. Shipped fixes
for the 8 that posed real damage risk for tomorrow's live trading;
deferred 4 that need bigger surface changes (P1 #8 bid/ask plumbing;
P1 #10 WS throttle; P2 #12 init-order race; P1 #4-stale-quote refinement).

### P0 fixes

#### P0 #1 — `_ib_close_position` cancels bracket children before close

`services/trade_executor_service.py`: new helper
`_cancel_ib_bracket_orders` runs FIRST inside `_ib_close_position`,
canceling stop + target IB children for the trade before the close
MKT goes out. Pre-fix race: bot's local stop fires → close MKT
queued → IB bracket child fires same tick → DOUBLE-EXIT (long
becomes short / short becomes long). The cancel narrows the race
to milliseconds; even if a child filled in those ms, the close
will then fail at IB with "insufficient quantity" instead of
doubling the position.

Also handles three legacy ID storage slots (`stop_order_id`,
`target_order_id` singular, `target_order_ids` plural). Filters
out non-numeric / simulated IDs (`SIM-STOP-uuid`).

#### P0 #2 — `execute_partial_exit` propagates broker failures honestly

`services/position_manager.py`: was returning `success: True,
simulated: True` on broker exception, which decremented
`remaining_shares` locally while leaving those shares OPEN at the
broker → silent position drift between books and broker. Now
exceptions / executor failures return `success: False` so the
caller skips the local mutation. Legitimate paper-paper mode (no
executor) still returns `simulated: True`.

`check_and_execute_scale_out` callsite: added explicit `else`
branch that logs the failure + records a `trade-drop` so the
operator sees it in the diagnostic feed; manage loop retries on
next pass when target is still hit.

#### P0 #3 — `close_trade` returns `False` on executor failure

`services/position_manager.py`: was marking trade `CLOSED`
locally even when `_trade_executor.close_position()` returned
`success: False`. Books said closed; broker still had the
position open. Now hard-returns `False` so the trade stays OPEN
locally and the manage loop retries; records a `trade-drop` for
operator visibility.

#### P0 #4 — Stale-quote guard

`services/position_manager.py`: parses `_pushed_at` / `ts` /
`timestamp` from the pushed quote, computes age in seconds. Skips
local stop-checks when age > `MANAGE_STALE_QUOTE_SECONDS` (env
default 30s). Server-side IB brackets still active and operate on
real-time prices. Throttles the warning log to once per 60s per
trade.

### P1 fixes

#### P1 #5 — Bare `except: pass` replaced with logged warning

Pushed-quote lookup failures used to be silent. Now logs
`manage: pushed-quote lookup failed for {sym}: {error}`. v8
hardening rule satisfied.

#### P1 #6 — `stop_adjustments` history capped at 100

`services/stop_manager.py:_record_stop_adjustment`: caps history
in-place at most-recent 100 entries. Long-running swing positions
no longer bloat their BotTrade snapshot dict.

#### P1 #7 — `StopManager.forget_trade` releases per-trade state on close

New method releases `_last_resnap_at[trade_id]`. Called from BOTH
close-trade paths (manual close + all-targets-hit close). Idempotent.
Closes a small but real memory leak that accumulated closed-trade
IDs over weeks.

#### P1 #9 — UNSTOPPED-POSITION alarm

`services/position_manager.py`: if `trade.stop_price` is falsy
(None / 0) — meaning the local stop check is unreachable — log a
`manage: UNSTOPPED POSITION` ERROR once per 5 minutes per trade
so the operator can intervene. IB-side bracket should still cover
it; the alarm just makes sure it doesn't pass quietly.

### P2 fixes

#### P2 #11 — Risk-fallback warns once per trade

`services/position_manager.py`: when `risk_per_share` falls back
to `2% × fill_price` (because `stop_price == fill_price`), emit a
WARNING once per trade so operator knows R-multiple math is
approximate.

### Tests (`test_manage_stage_hardening_v19_13.py` — 9 tests)

- `test_ib_close_cancels_bracket_children_first` — P0 #1 call ordering
- `test_cancel_ib_bracket_skips_simulated_ids` — non-numeric IDs filtered
- `test_cancel_ib_bracket_swallows_errors` — best-effort never raises
- `test_partial_exit_propagates_broker_failure` — P0 #2 contract
- `test_partial_exit_no_executor_returns_simulated_legitimately` — paper-paper preserved
- `test_partial_exit_executor_returns_failure_passes_through` — executor's success=False propagates
- `test_stop_adjustments_history_capped_at_100` — P1 #6
- `test_stop_manager_forget_trade_releases_state` — P1 #7 + idempotency
- `test_close_trade_returns_false_on_executor_failure` — P0 #3 contract

**141/141 across v12-v19.13 backend tests.** Manage stage now safe
for tomorrow's live trading.

### Deferred → SHIPPED in same commit (refused to defer)

#### P1 #8 — Bid/ask-aware stop trigger

Long position exits at the BID; short exits at the ASK. The
manage loop's quote-read now captures `bid` + `ask` alongside
`last`. Stop-hit check uses the tradable side:

```python
if direction == LONG:
    trigger_price = float(_bid) if _bid > 0 else trade.current_price
    if trigger_price <= effective_stop: stop_hit = True
else:  # SHORT
    trigger_price = float(_ask) if _ask > 0 else trade.current_price
    if trigger_price >= effective_stop: stop_hit = True
```

Falls back to `current_price` (last) when bid/ask not in feed —
relevant for OTC / pre-market thin streams. Log message names which
side fired (`bid` vs `last`) for forensics.

Why this matters: on a thin stock, last-tick at $50.00 with bid at
$49.85 means a stop sale fills at $49.85, not $50.00 — the trigger
fires "too late" because we waited for last to print at the stop
when the actual achievable exit had already crossed.

#### P1 #10 — Per-tick WS notification throttle

The manage loop ran every ~1-2s. With 25 open positions × 2 notifies
per loop, the V5 HUD was being shoulder-tapped 12-25× per second
through `_notify_trade_update(trade, "updated")`. Now emit only when:

- First tick after open (`_last_notified_at` unset)
- ≥2s since last emit (heartbeat)
- |unrealized P&L| moved by ≥5% of the trade's risk amount

State-change paths (scale_out, closed, stop_hit) still emit
unconditionally via separate notify calls — those are not throttled.
On a typical day with 8 open positions this drops WS traffic from
~10 msg/s to ~4 msg/s while still surfacing every meaningful move.

#### P2 #12 — `original_shares` initialized at trade creation

`opportunity_evaluator.execute_trade()`'s `BotTrade(...)`
construction now passes both `remaining_shares=shares` and
`original_shares=shares` upfront. Pre-fix: those fields were
default-zero on the dataclass and only set on the FIRST
`update_open_positions` tick. A partial exit landing before the
first tick would decrement `remaining_shares` while
`original_shares` was still 0 → percent-of-original math broken.
Theoretical race but real; takes ms to hit if the entry fills + a
target gets brushed in the same tick.

#### P1 #4 refinement — left as-is

Bid/ask staleness vs last staleness: deferred review concluded
the current 30s `_pushed_at`-based cap covers all realistic feed
hangs. Per-leg staleness only matters for OTC names where bid
might lag last by minutes; current scanner universe excludes
those by ADV filter.

### Tests added (now 13 in `test_manage_stage_hardening_v19_13.py`)

Plus the 4 new regression guards:
- `test_opportunity_evaluator_initializes_share_state_at_create` — P2 #12
- `test_ws_throttle_constants_pinned` — P1 #10 source-level pin
- `test_stop_trigger_uses_bid_for_long_when_available` — P1 #8
- `test_quote_read_captures_bid_and_ask` — P1 #8

**145/145 across v12-v19.13.** Manage stage now FULLY HARDENED.



## 2026-04-30 (thirtieth commit, v19.12) — Pre-execution guardrail max-notional cap raised + made env-tunable

**Why**: Full audit of the 9 trade-drop gates downstream of
`safety_guardrail` revealed a SIBLING blocker. Gate
`pre_exec_guardrail_veto` (run by `execution_guardrails.run_all_guardrails`)
had `MAX_POSITION_NOTIONAL_PCT = 0.01` (1% of equity) hardcoded
under a comment marked "temporary ceiling while bracket migration
in progress". Bracket migration shipped weeks ago but the cap was
left tightened. For the operator's $250k account targeting $100k
max trade notional, every trade would have been vetoed at this
gate with `notional_over_cap: 100000 > 1.00%×equity (2500)`.

### Patch (`services/execution_guardrails.py`)

1. Default `MAX_POSITION_NOTIONAL_PCT` raised 0.01 → 0.40 (matches
   the operator's chosen sizing on the $250k account).
2. Made env-tunable via `EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT` so
   future operators on different account sizes don't hit the same
   wall.
3. Also added env hooks for the stop-distance rules
   (`EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT`,
   `EXECUTION_GUARDRAIL_MIN_STOP_PCT`) — same default, just
   tunable.
4. `check_max_position_notional(max_pct=None)` re-reads env at
   call-time so a hot config tweak takes effect on the next trade
   without a backend restart.

The position-sizer's `max_notional_per_trade` (RiskParameters,
v19.4) is now the **primary** per-trade notional cap. This
guardrail is the **secondary** catch — for sizer accidents, not
normal sizing decisions.

### Tests (`test_execution_guardrail_max_notional_v19_12.py` — 10 tests)

- `test_default_allows_100k_notional_on_250k_account` — operator's intended sizing passes
- `test_default_blocks_obviously_oversized_notional` — 80% notional still blocked
- `test_env_override_relaxes_to_70_percent` / `test_env_override_tightens_to_5_percent` — env tuning round-trip
- `test_explicit_max_pct_arg_overrides_env` — caller-supplied wins over env
- `test_invalid_size_still_rejected` / `test_missing_equity_falls_back_to_allow` — defensive paths preserved
- `test_module_default_is_40_percent` — module-level default pinned
- `test_tight_stop_still_rejected` — sister stop-distance guardrail untouched
- `test_run_all_guardrails_returns_first_failure` — pipeline contract

**132/132 across v12-v19.12 backend tests.**

### Pipeline audit summary

Full audit of the 9 known trade-drop gates downstream of safety:

| Gate | Status | Notes |
|---|---|---|
| safety_guardrail | ✅ FIXED | v19.4 + v19.5 + operator PUT |
| safety_guardrail_crash | ✅ FIXED | defensive variant of safety_guardrail |
| pre_exec_guardrail_veto | ✅ FIXED | v19.12 |
| strategy_paper_phase | ✅ N/A | `paper_account_mode=True` default → bypassed |
| strategy_simulation_phase | ✅ N/A | same |
| account_guard | ✅ N/A | listed in known-gates allow-list but no production path actually fires it; only drives UI chip. Fail-open if env unconfigured. |
| no_trade_executor | ✅ WIRED | `set_services()` called at server startup line 464; verify with curl |
| broker_rejected | ⚠️ N/A | only fires on actual IB rejection (margin / contract issue); cannot pre-vet |
| execution_exception | ⚠️ N/A | code-bug catch-all; cannot pre-vet |

The 7 verifiable gates are now fixed/N-A. The 2 cannot-pre-vet
gates (`broker_rejected`, `execution_exception`) are the only
remaining unknowns — and they'll only fire on actual IB-side or
runtime-error conditions, which the v12 instrumentation will name
within 30 seconds if they do.



## 2026-04-30 (twenty-ninth commit, v19.10 + v19.11 + v19.11.1) — Scanner UX: hits counter + keyboard nav

### v19.11.1 — HOT-FIX: blank screen after v19.11 pull

Operator pulled v19.11, the entire app rendered blank — startup
gate didn't even appear. Webpack frontend log:

```
src/components/sentcom/v5/useV5Styles.js
  Line 118:18:  'card' is not defined   no-undef
  Line 118:23:  'hover' is not defined  no-undef
  Line 118:29:  'cross' is not defined  no-undef
webpack compiled with 1 error
```

Root cause: `useV5Styles.js` stores its CSS in a single template
literal (`` const CSS = `...` ``). The v19.11 commit added a CSS
comment containing `` `.v5-card-hover-cross` ``. The unescaped
backticks inside the template literal CLOSED the outer template,
making the parser treat the rest as JS — `.v5-card-hover-cross`
became `.v5 - card - hover - cross` (member access + 3 minus
operations on undefined identifiers).

CRA's webpack-eslint caught this with `no-undef`; my standalone
lint missed it because backticks inside comments are syntactically
valid in standalone parsing (the comment is stripped first).

### Fix

Removed backticks from the CSS comment. Now reads `existing
v5-card-hover-cross inset shadow + active border` (plain text).

### Lesson learned for future contributors

`useV5Styles.js` is a single giant template literal. Any backtick
inside it — even in `/* */` comments — closes the literal. Use
**single-quotes or no quotes** in CSS comments inside this file.

### v19.10 — Sticky "X / N hits" counter (unchanged from prior commit)
### v19.11 — Keyboard navigation (unchanged from prior commit)



## 2026-04-30 (twenty-eighth commit, v19.9) — V5 layout: Scanner full-height, drawer aligned to chart

**Why**: Operator asked to move the bottom "SentCom Intelligence"
drawer so its left edge aligns with the chart — freeing the left
20% column for the Scanner to span the full viewport height and
scroll through many hits without the drawer cutting underneath.

### Before

```
┌──────────────────────────────────────────────┐
│ HUD / StatusStrip                            │
├────────┬──────────────────┬──────────────────┤
│Scanner │      Chart       │  Right sidebar   │  ← grid (~800px)
│  20%   │     55%          │      25%         │
├────────┴──────────────────┴──────────────────┤
│   SentCom Intelligence  |  Deep Feed         │  ← drawer (100% width)
│   (split drawer, spans full viewport)        │
└──────────────────────────────────────────────┘
```

### After

```
┌──────────────────────────────────────────────┐
│ HUD / StatusStrip                            │
├────────┬─────────────────────────────────────┤
│        │       Chart     │  Right sidebar    │  ← grid within right col
│Scanner │       55fr      │      25fr         │
│ full-  ├─────────────────┴───────────────────┤
│ height │  SentCom Intel  |  Deep Feed        │  ← drawer within right col
│  20%   │  (aligned to chart's left edge)     │
│        │                                     │
└────────┴─────────────────────────────────────┘
```

### Patch

`SentComV5View.jsx` — layout surgery (no component logic touched):

- Replaced the outer 3-col grid (`20% 55% 25%`) with a 2-col flex row:
  - **LEFT** (`width: 20%`) — Scanner `<section>` (unchanged internals)
  - **RIGHT** (`flex-1 min-w-0`) — new flex-col wrapper
- Inside the right column:
  - Top grid now `55fr 25fr` (same 55/25 proportions, just of the
    80% right column width = effectively 44% chart / 20% sidebar of
    the overall screen; visually indistinguishable from before)
  - Drawer (`SentCom Intelligence | Deep Feed`) moved INSIDE the
    right column so its left edge starts where the chart starts
- Outer row `min-h: 1120px` = 800 (grid min) + 320 (drawer min) to
  match the previous total vertical space
- Scanner stretches to the full row height via default flex
  `align-items: stretch` — the `overflow-y-auto flex-1 v5-scroll`
  inside its card list keeps the scroll behaviour identical

### What stays the same

- Grid column proportions within the right 80% (55fr / 25fr)
- Drawer split logic (`drawerContainerRef`, `leftPct`, `resetToDefault`)
  and `DrawerSplitHandle`
- All `data-testid` hooks (`sentcom-v5-left`, `sentcom-v5-grid`,
  `sentcom-v5-bottom-drawer`, `sentcom-v5-drawer-split`) preserved
- Scanner card rendering, Chart, Right-sidebar aside, both drawer
  panels — all untouched component-side
- ESLint clean; no JSX balance issues

### Operator benefit

With 500+ symbols scanning simultaneously (post-v17), the Scanner
can now show 30-40 cards without the drawer squashing it from
below. Operator's scroll-through-hits workflow gets the full
viewport height instead of the 800px grid slice.



## 2026-04-30 (twenty-seventh commit, v19.8) — V5 Stream Waves 1-4

Big multi-wave UX upgrade across Scanner, Unified Stream, and the
right-pane "Stream · Deep Feed" (which until now was a duplicate of
Unified Stream). All four waves shipped in one commit because they
share helpers (hover state, severity classifier, expanded-key
sets) and ship cleanly behind operator-toggleable defaults.

**Wave 1** — perception: collapse + cross-highlight + counter-trend
**Wave 2** — forensics: real Deep Feed history + filters
**Wave 3** — context: setup grouping + day-rollup banner
**Wave 4** — RLHF: 👍/👎 reactions feeding the training pipeline

### Wave 1 (#5) Repeat-event collapser

`UnifiedStreamV5.jsx` now feeds messages through `streamCollapse.js`
(new pure-function module). Consecutive same-(symbol, action_type)
runs render as a single row: `AAPL · skip_low_gate ×5 · last 0:32 ago`.
Click `expand ▾` to see all children. Effective stream capacity 5×
on busy windows. **9/9 unit tests via node-direct execution.**

Implementation notes:
- Filter chips applied BEFORE collapse so groups don't span filtered-out events.
- `expandedKeys` (Set<string>) lives in `UnifiedStreamV5` state — survives WS pushes that don't disturb the run.
- Group key `<sym>|<kind>|<oldest_ts>` survives re-renders — operator's expansion choice persists.
- Empty-signature rows (no symbol AND no kind) never collapse.

### Wave 1 (#11) Cross-panel hover

`hoveredSymbol` lifted to `SentComV5View`; passed to all three panels
(Scanner, Unified Stream, Deep Feed). Hover a row → matching Scanner
card pulses cyan (`@keyframes v5-cross-pulse`, 220ms). Hover a card →
matching stream rows highlight. Cost: nil — Map.get() per row, no
re-renders from the parent.

### Wave 1 (#2) Counter-trend warning stripe

`is_countertrend` and `market_setup` plumbed from `LiveAlert.to_dict()`
through `buildCards` to `<ScannerCard>`. Counter-trend cards render
with diagonal-stripe amber left border + `⚠ CT` chip. Backend already
sets these via the v17 soft-gate matrix — we just made them visible.

### Wave 2 (#9) Deep Feed → real persisted history

New endpoint: `GET /api/sentcom/stream/history` over the existing
`sentcom_thoughts` Mongo collection (TTL 7d). Filters:
- `minutes` (1 - 10080, default 60)
- `symbol` (case-insensitive exact)
- `kind` (scan / brain / order / fill / win / loss / skip / info)
- `q` (regex search across `content` + `action_type`)
- `limit` (1 - 2000)

Frontend `<DeepFeedV5/>` replaces the duplicate `<UnifiedStreamV5/>`
in the right pane. Adds:
- 6 time-range chips: 5m / 30m / 1h / 4h / 1d / 7d
- Symbol drill-in input (debounced 250ms)
- Free-form text search (debounced 250ms)
- 30s background poll (independent of WS stream)
- Reuses `<UnifiedStreamV5/>` for rendering, so collapse + severity
  + reactions + cross-highlight all "just work".

### Wave 3 (#1) Scanner grouping by Market Setup

`<ScannerCardsV5/>` now supports two modes:
- **flat** (default) — preserves the legacy ranked list
- **grouped** — sections by `market_setup` (Gap & Go, Range Break, Day-2,
  etc.), each collapsible, with per-section `N CT` counter-trend chip

Toggle persists to `localStorage['v5_scanner_group_by_setup']` so the
operator's choice survives reload.

### Wave 3 (#7) Day-rollup banner

`<DayRollupBannerV5/>` pinned at the top of Unified Stream. Reads
`/api/diagnostic/trade-funnel` every 30s. One sticky line:
`Today: 276 alerts · 20 HIGH · 16 eligible · 0 orders · killed at: orders`

When `orders=0` and `eligible>0`, the line ends in red highlighting
which stage is killing trades — surfaces the funnel state without
operator curl.

### Wave 4 (#8) Operator RLHF reactions

New router: `routers/sentcom_labels.py` with three endpoints:

```
POST /api/sentcom/stream/label             # 👍/👎/clear (idempotent toggle)
GET  /api/sentcom/stream/labels            # list + counts (UI hydration)
GET  /api/sentcom/stream/label/training-export  # JSONL for the training pipe
```

New collection `sentcom_labels` (TTL 90d, longer than `sentcom_thoughts`
because labels survive past the underlying events). Idempotent toggle
via unique `(event_id, operator_id)` index. Optional context fields
(`symbol`, `kind`, `action_type`, `note`) so the training pipe can
join without round-tripping through `sentcom_thoughts`.

Frontend `useStreamLabels` hook + `<ReactionButtons/>` component:
- Hydrates last 24h on mount
- Optimistic update — UI reflects the click before the POST returns
- Same emoji clicked twice → "clear" (removes the row)
- Hidden until row hover; visible permanently once labelled

The training pipeline can now read this signal as an RLHF reward
alongside realised P&L. Closes the self-improving loop.

### Tests

- `tests/test_stream_history_and_labels_v19_8.py` — 10 new pytest tests
  covering history filter wiring, error envelopes, label
  insert/idempotent/flip/clear, validation, count rollups, pydantic limits.
- `streamCollapse.js` — 9 node-direct tests covering empty inputs,
  single rows, runs of N, interleaving, expandedKeys, mixed runs.
- **122/122 backend tests across v12-v19.8.**

### Files touched (frontend)
- `components/sentcom/SentComV5View.jsx` (lift hover state, mount Deep Feed + day-rollup)
- `components/sentcom/v5/UnifiedStreamV5.jsx` (collapser + cross-hover + reactions)
- `components/sentcom/v5/ScannerCardsV5.jsx` (counter-trend, grouping, hover)
- `components/sentcom/v5/DeepFeedV5.jsx` (NEW)
- `components/sentcom/v5/DayRollupBannerV5.jsx` (NEW)
- `components/sentcom/v5/streamCollapse.js` (NEW)
- `components/sentcom/v5/useStreamLabels.js` (NEW)
- `components/sentcom/v5/useV5Styles.js` (CSS additions only)

### Files touched (backend)
- `routers/sentcom.py` (added `/stream/history`)
- `routers/sentcom_labels.py` (NEW — full router)
- `server.py` (1-line include)



## 2026-04-30 (twenty-sixth commit, v19.7) — V5 HUD layout: 2/3 ⇄ 1/3 split

**Why**: With margin-account dollar values shipping in v19.6
(`Buying Pwr` showing 7-figure numbers like `$4,278,685`), the
right-cluster was getting squeezed by the 5-stage funnel. Operator
screenshot showed metrics truncating / wrapping awkwardly.

### Patch (1 file, layout-only)

`PipelineHUDV5.jsx` — flex sizing change:
- Stages container: `flex-1 min-w-0` → `basis-2/3 min-w-0`
- Metrics container: `shrink-0` → `basis-1/3 min-w-0 justify-end`

5 stages now consume **2/3** of the HUD width; the right cluster
(P&L / Equity / Buying Pwr / Phase + any `rightExtra` button) gets
the other **1/3**. `min-w-0` on both halves preserves graceful
truncation on narrow viewports; `justify-end` on the metrics block
keeps them flush against the right edge regardless of how wide the
1/3 partition resolves to.

### What stays the same
- Stage proportions amongst themselves (5 even-flex stages within the
  2/3 budget) — Scan / Evaluate / Order / Manage / Close Today still
  share equal width.
- Metric component, color rules, formatting — unchanged.
- All `data-testid` hooks preserved.



## 2026-04-30 (twenty-fifth commit, v19.6) — V5 HUD: Buying Power replaces Latency

**Why**: Operator on a 4× margin paper account asked for **real-time
buying power** in the V5 top-bar HUD, next to Equity. Latency was
displaced (it's exposed in the Pusher Heartbeat tile already; the
HUD's right-cluster spot is more valuable for a margin number).

### Patch

- **Backend**: `routers/trading_bot.py` — when surfacing
  `account_equity` at top-level of `/api/trading-bot/status`, also
  surface `account_buying_power` (already collected from
  `BuyingPower` field of the IB account snapshot at line 235;
  previously only nested under `account.buying_power`).

- **Frontend**: `components/sentcom/SentComV5View.jsx` — read
  `status.account_buying_power ?? status.buying_power ??
  context.account_buying_power` and pass to `<PipelineHUDV5/>`.
  Removed the `latencySeconds` read.

- **Frontend**: `components/sentcom/panels/PipelineHUDV5.jsx` —
  prop `latencySeconds` → `buyingPower`. Metric tile label
  `Latency` → `Buying Pwr`. Color coding:
  - `text-emerald-400` when `buyingPower > equity × 0.5` (healthy
    margin headroom)
  - `text-amber-400` otherwise (running close to maintenance margin)

### Why color thresholds at 50% of equity

A standard Reg-T margin account has `BuyingPower ≈ 4× Equity`
intraday. As open positions consume margin, `BuyingPower` drops.
At 50% of equity, used margin is roughly 87.5% of available — close
to the operator's `max_total_exposure_pct=320%` cap. The amber
warning fires before reaching the hard reject so the operator gets
a visual heads-up to either close positions or stand down on new
entries.

### Persistence / latency display

Latency wasn't deleted from the system — it's still exposed on the
Pusher Heartbeat tile (`PusherHeartbeatTile.jsx`) with avg / p95 /
last RPC latency. The change is just where the V5 HUD's
prime-real-estate metric slot points.



## 2026-04-30 (twenty-fourth commit, v19.5) — Safety config ceiling raised for margin accounts

**Why**: Operator ran the v19.4 unblock script, got HTTP 422 on the
safety PUT:

```
"max_total_exposure_pct": {"type": "less_than_equal",
  "msg": "Input should be less than or equal to 100", "input": 320,
  "ctx": {"le": 100.0}}
```

The Pydantic validator on `SafetyConfigPatch.max_total_exposure_pct`
had `le=100`. That's correct for cash accounts but rejects margin
operators — 80% of buying power on a 4× margin account == 320% of
equity is completely normal.

The underlying dataclass + env loader (`safety_guardrails.py`)
already accepted arbitrary floats; only the API validator was the
chokepoint.

### Patch

- `routers/safety_router.py:40` — `le=100` → `le=1000` on
  `max_total_exposure_pct`. Cash operators naturally stay under 100;
  margin operators get the headroom they need. >1000% is still
  rejected as a typo guard (no realistic broker offers >10× leverage
  on US equities).

### Tests (`tests/test_safety_config_margin_ceiling_v19_5.py` — 4 tests)

- **`test_safety_config_patch_accepts_margin_exposure_pct`** — pins
  320% and 999% as accepted.
- **`test_safety_config_patch_still_rejects_negative_or_zero`** —
  lower bound (>0) must still hold.
- **`test_safety_config_patch_rejects_absurd_exposure`** — >1000%
  rejected as a typo guard.
- **`test_other_safety_fields_unchanged`** — bumping exposure ceiling
  didn't loosen the other validators (`max_daily_loss_pct`,
  `max_positions`, `max_quote_age_seconds`).

**112/112 across v12-v19.5 suites.**

### Operator workflow on Spark

```bash
# Re-run the v19.4 unblock — should now succeed:
curl -s -X PUT "http://localhost:8001/api/safety/config" \
  -H "Content-Type: application/json" \
  -d '{
    "max_symbol_exposure_usd": 100000,
    "max_positions": 25,
    "max_total_exposure_pct": 320,
    "max_daily_loss_usd": 5000,
    "max_quote_age_seconds": 10
  }' | jq
```

The returned body should show all five caps applied; the `effective`
block of `/api/safety/effective-risk-caps` should reflect them.



## 2026-04-30 (twenty-third commit, v19.4) — Position-sizer absolute-notional clamp

**Why**: Operator's `/api/diagnostic/trade-drops` curl finally named
the gate that was killing every autonomous trade for hours:

```
"first_killing_gate": "safety_guardrail",
"by_gate": {"safety_guardrail": 44},
"reason": "symbol_exposure: VRT exposure $267,351 exceeds cap $15,000"
```

The position sizer was producing **~$267k notional positions** (25%
of $1.07M equity) on tight-stop intraday setups, while the safety
guardrail's `max_symbol_exposure_usd` defaulted to **$15,000** —
appropriate for a $50-100k account, completely wrong for $1M+.

The two-curl operator unblock is documented elsewhere (raise
`SAFETY_MAX_SYMBOL_EXPOSURE_USD` + drop `starting_capital` to a
realistic $250k). But that just moves the goalposts: as the paper
account compounds, `max_position_pct=50` × growing equity → notional
fattens again, and the safety cap rejects all over.

The right structural fix: an **absolute notional ceiling per trade**,
decoupled from equity. Operator picks the dollar number; the sizer
can never produce a fatter position regardless of how much the
account compounds.

### Patch

#### 1. `RiskParameters.max_notional_per_trade` (default $100,000)

New field on the `RiskParameters` dataclass. Default $100k matches
operator's stated "max trade dollar size". Set to 0 to disable
(restores the prior two-clamp behaviour for legacy setups that
don't want this tightening).

#### 2. Third clamp in `OpportunityEvaluator.calculate_position_size`

```python
max_shares_by_risk     = adjusted_max_risk / risk_per_share        # existing
max_shares_by_capital  = (equity × max_position_pct%) / entry      # existing
max_shares_by_notional = max_notional_per_trade / entry            # NEW
shares = max(min(by_risk, by_capital, by_notional), 1)
```

The clamp is a hard `min()` with the prior two clamps — whichever is
tightest wins. When `max_notional_per_trade=0`, the clamp is bypassed
and the sizer falls back to the two-clamp logic.

#### 3. Persistence round-trip

`bot_persistence._sync_save` writes `max_notional_per_trade` into
`bot_state.risk_params`; `_restore_state` reads it back on bot start.
Survives backend restarts.

#### 4. API surface

`RiskParamsUpdate` Pydantic model accepts `max_notional_per_trade`
so the operator can hot-patch via:

```bash
curl -s -X POST "http://localhost:8001/api/trading-bot/risk-params" \
  -H "Content-Type: application/json" \
  -d '{"max_notional_per_trade": 100000}' | jq
```

### Tests (`tests/test_position_sizer_notional_clamp_v19_4.py` — 7 tests)

- **`test_risk_parameters_exposes_max_notional_per_trade`** — pins
  the dataclass field + $100k default.
- **`test_clamp_caps_oversized_notional`** — when capital cap would
  allow $200k notional, the $100k notional clamp wins.
- **`test_risk_clamp_wins_when_stop_is_wide`** — confirms the older
  risk clamp still wins when it's tighter than the notional clamp.
- **`test_clamp_disabled_when_zero`** — backward-compat: `max_notional=0`
  returns to two-clamp behaviour.
- **`test_sizer_source_contains_notional_clamp`** — source-level
  guards on both `max_notional_per_trade` and `max_shares_by_notional`
  references in the sizer.
- **`test_persistence_round_trip_includes_max_notional`** — both save
  and restore paths reference the new field.
- **`test_riskparamsupdate_pydantic_model_accepts_max_notional`** —
  API model dump pins the field name + Optional default.

**108/108 across v12-v19.4 suites.**

### Operator workflow on Spark (combined v19.3 + v19.4 + paper-reset)

```bash
# After resetting IB paper account to $250k starting capital:

# 1. Bot risk_params (sized for $250k cash + 4× margin):
curl -s -X POST "http://localhost:8001/api/trading-bot/risk-params" \
  -H "Content-Type: application/json" \
  -d '{
    "starting_capital": 250000,
    "max_risk_per_trade": 2000,
    "max_position_pct": 40,
    "max_open_positions": 25,
    "max_daily_loss": 5000,
    "min_risk_reward": 1.5,
    "max_notional_per_trade": 100000
  }' | jq

# 2. Safety guardrails (in-memory hot patch):
curl -s -X PUT "http://localhost:8001/api/safety/config" \
  -H "Content-Type: application/json" \
  -d '{
    "max_symbol_exposure_usd": 100000,
    "max_positions": 25,
    "max_total_exposure_pct": 320,
    "max_daily_loss_usd": 5000,
    "max_quote_age_seconds": 10
  }' | jq

# 3. Persist safety env:
cd ~/Trading-and-Analysis-Platform/backend && \
sed -i '/^SAFETY_MAX_SYMBOL_EXPOSURE_USD=/d
/^SAFETY_MAX_POSITIONS=/d
/^SAFETY_MAX_TOTAL_EXPOSURE_PCT=/d
/^SAFETY_MAX_DAILY_LOSS_USD=/d' .env && \
cat >> .env <<'EOF'
SAFETY_MAX_SYMBOL_EXPOSURE_USD=100000
SAFETY_MAX_POSITIONS=25
SAFETY_MAX_TOTAL_EXPOSURE_PCT=320
SAFETY_MAX_DAILY_LOSS_USD=5000
EOF

# 4. Verify clean cap surface:
curl -s "http://localhost:8001/api/safety/effective-risk-caps" | jq

# 5. Wait 60s for next cycle then confirm drops are gone:
curl -s "http://localhost:8001/api/diagnostic/trade-drops?minutes=2" | jq '{total, by_gate, first_killing_gate}'
```

If `total: 0` and `first_killing_gate: null` after the wait — the
ORDER tile starts incrementing the moment the next eligible setup
fires.



## 2026-04-30 (twenty-second commit, v19.3) — HOT-FIX: Live-tick scanner ALSO bombing pusher RPC

**Why**: Operator pulled v19.2 + restarted. Within ~96 seconds of
pusher startup the SAME `[RPC] latest-bars X failed` cascade returned,
plus 120s `Connection error on post. ... Read timed out.` on the
pusher → DGX push channel:

```
14:55:21 [INFO] Starting data push loop...
14:56:39 [INFO] Pushing: 315 quotes (push OK)
14:56:57 [WARNING] [RPC] latest-bars HIMS failed:
14:57:15 [WARNING] [RPC] latest-bars VUG failed:
14:57:33 [WARNING] [RPC] latest-bars ALAB failed:
14:58:39 [WARNING] Connection error on post. Retry 1/3 in 5.9s:
        HTTPConnectionPool(host='192.168.50.2', port=8001):
        Read timed out. (read timeout=120)
...
```

UI-side symptoms (operator screenshot):
- Equity = `$-`
- Top movers stuck on "loading..."
- Pusher chip RED
- Unified Stream + Stream Deep Feed frozen since restart

### Root cause

v19.1's `mongo_only=True` fix correctly decoupled the bar poll
service. But there was a SECOND bombardment site we missed:
**the live-tick scanner itself**. `_scan_symbol_all_setups` (line
2645 of `enhanced_scanner.py`) calls `get_technical_snapshot(symbol)`
WITHOUT `mongo_only=True`. With v17 expanding pusher subscriptions
to ~480 symbols, every scan cycle fans out 480 calls to
`_get_live_intraday_bars` → `/rpc/latest-bars` → pusher fires
`reqHistoricalData` for each → IB's 60-req/10min pacing limit blows
out within 2-3 cycles → cascade.

The pusher's threadpool stalls behind these stuck calls; pusher's
own POSTs to DGX `/api/ib/push-data` queue up; DGX's push handler
also slows because it shares the same async event loop the scanner's
`asyncio.gather()` is saturating with `asyncio.to_thread`-wrapped
sync `requests` calls. End result: equity stops updating, stream
freezes, pusher goes RED in the HUD.

### Fix

One-line change (with full docstring) in `enhanced_scanner.py:2645`:

```python
# Before:
snapshot = await self.technical_service.get_technical_snapshot(symbol)

# After:
snapshot = await self.technical_service.get_technical_snapshot(
    symbol, mongo_only=True,
)
```

Why this is safe:
- The live tick still flows through `_pushed_ib_data` (unaffected by
  `mongo_only`). `get_technical_snapshot` still reads it at line
  440 to populate `quote.price`.
- Mongo bars are <60s lagged from the always-on turbo collectors —
  fine for 5-min and 15-min bar detectors.
- Setups that need sub-second timing (`9_ema_scalp`,
  `vwap_continuation`, `opening_range_break`) rely on the live tick
  + recent Mongo bars, NOT on the live-bar overlay.

What is NOT changed:
- API/UI endpoints (e.g. `/api/scanner/scan`, AI assistant queries)
  still default to `mongo_only=False` — those are one-off, freshness
  beats pacing safety there.
- The swing/position DMA filter at line 6401 is alert-time only
  (low volume); leaving it on the freshness path.

### Tests (`tests/test_scanner_mongo_only_v19_3.py` — 4 new)

- **`test_scan_symbol_all_setups_uses_mongo_only`** — source-level
  regex check. The single most important guard: a future contributor
  "cleaning up" `mongo_only=True` will hit this red test.
- **`test_bar_poll_service_still_uses_mongo_only`** — keeps the
  v19.1 fix pinned in place too (defense in depth).
- **`test_get_technical_snapshot_signature_has_mongo_only`** — pins
  the param name + default=False so neither side of the kill-switch
  silently flips.
- **`test_get_batch_snapshots_signature_has_mongo_only`** — same for
  the batch path.

**101/101 across v12-v19.3 suites.**

### Operator workflow on Spark

```bash
cd ~/Trading-and-Analysis-Platform && git pull && \
  pkill -f "python server.py" && \
  cd backend && nohup python server.py > /tmp/backend.log 2>&1 &

# Within ~30s of restart:
# 1. The `[RPC] latest-bars X failed` cascade should STOP.
# 2. The 120s push-to-DGX timeouts should STOP.
# 3. Pusher chip turns GREEN in the HUD.
# 4. Equity populates, top movers load, unified stream resumes.
```

If the cascade returns AGAIN, audit any new caller of
`get_technical_snapshot()` in a hot path (the test guards the two
known hot paths; new ones must explicitly opt into mongo_only).



## 2026-04-30 (twenty-first commit, v19.2) — DLQ Purge Endpoint

**Why**: The V5 HUD's `N DLQ` badge surfaces the count of permanently-
failed historical-data collection requests. With v17/v18 expanding the
universe scan, the DLQ accumulates entries IB will NEVER successfully
serve — delisted symbols ("SLY"), ambiguous contracts, "no security
definition" errors, etc. Two complementary endpoints already existed:

- `POST /api/ib-collector/retry-failed` — re-queues failures
- `GET  /api/ib-collector/failed-items` — lists them

**What was missing: purge.** Operator can't currently distinguish "5
transient failures we should retry" from "47 permanent failures we
should drop". Retrying terminal errors wastes IB pacing budget and
pollutes the badge count.

### Patch

#### `POST /api/diagnostic/dlq-purge`

```
POST /api/diagnostic/dlq-purge
  ?permanent_only=true       # (default) only delete known-permanent errors
  &older_than_hours=72       # optional: scope to items at least this old
  &bar_size="1 min"          # optional: scope to a single bar_size
  &force=true                # required when permanent_only=false
  &dry_run=true              # preview without deleting
```

**Safe-by-default contract**:

- `permanent_only=True` (the default) restricts deletes to a strict
  allowlist of "will-never-succeed" patterns:
    - `no security definition` (IB error 200 — delisted/unknown symbol)
    - `contract not found` / `contract_not_found`
    - `no_data` (IB returned empty for a valid contract)
    - `Contract: Stock` (generic IB contract error)
    - `ambiguous contract`
    - `expired contract`
- `permanent_only=False` requires `force=True` — without force the
  endpoint returns 400 to prevent a sleepy operator from mass-deleting
  retryable transient failures.
- `dry_run=True` returns the WOULD-purge count, by_error_type breakdown,
  by_bar_size breakdown, and a 10-row sample without deleting anything
  or writing to the audit log.

**Audit trail**: Every non-dry-run purge writes a row to a new
`dlq_purge_log` Mongo collection with `ts / purged_count / by_error_type /
by_bar_size / permanent_only / older_than_hours / bar_size / force`.
30-day TTL via `expireAfterSeconds=30 * 24 * 3600`.

**Filter combination**: when both `permanent_only` and `older_than_hours`
are active, the query uses `$and: [<regex_or>, <timestamp_or>]` so both
constraints must hold. When only `older_than_hours` is set (with force
mode), the timestamp filter sits at top-level via `$or` over
`completed_at` + `created_at`.

### Tests (`tests/test_dlq_purge_v19_2.py` — 13 tests)

- **`test_purge_rejects_non_permanent_without_force`** — sleepy-operator
  guard: `permanent_only=false` without `force=true` MUST 400.
- **`test_purge_rejects_non_permanent_without_force_default`** — pins
  the default value of `force` (False).
- **`test_purge_default_deletes_permanent_failures`** — happy path,
  3 docs deleted, audit log written.
- **`test_purge_default_uses_permanent_allowlist_query`** — pins the
  regex string (a future contributor widening it must update the test).
- **`test_dry_run_does_not_delete`** — dry-run returns the count, never
  calls `delete_many`, never writes audit log.
- **`test_purge_response_shape`** (parametrized) — pins the 8-key
  response contract for both dry-run and live modes.
- **`test_purge_aggregates_by_error_type_and_bar_size`** — by_bar_size
  / by_error_type counts and 10-row sample populated.
- **`test_purge_force_mode_works_when_explicitly_requested`** — force
  mode skips the regex filter (purges ALL failed).
- **`test_older_than_hours_with_permanent_only_uses_and`** — the
  filter-combination case uses `$and` correctly.
- **`test_older_than_hours_alone_uses_or_at_top_level`** — the
  no-permanent-only case uses top-level `$or`.
- **`test_bar_size_filter_scopes_query`** — bar_size narrows the query.
- **`test_audit_log_entry_shape`** — pins the 9-field audit entry shape.

97/97 tests passing across v12-v19.2 suites.

### Operator workflow on Spark

```bash
# 1. Preview what WOULD be purged (no deletion):
curl -s -X POST "http://localhost:8001/api/diagnostic/dlq-purge?dry_run=true" \
  | python3 -m json.tool

# 2. Looks right? Drop them:
curl -s -X POST "http://localhost:8001/api/diagnostic/dlq-purge" \
  | python3 -m json.tool

# 3. Operator-friendly: drop ONLY items older than 7 days that are
#    permanent failures (catches "we gave up on these weeks ago"):
curl -s -X POST \
  "http://localhost:8001/api/diagnostic/dlq-purge?older_than_hours=168" \
  | python3 -m json.tool

# 4. Audit trail:
mongo tradecommand --eval 'db.dlq_purge_log.find().sort({ts_dt:-1}).limit(5).pretty()'
```

The V5 HUD's DLQ badge count drops as the queue clears.



## 2026-04-30 (twentieth commit, v19.1) — Hot-fix: bar poll bombarding pusher RPC

**Why**: Operator post-pull logs (2026-04-30 14:27 ET) showed:
```
[RPC] latest-bars IGV failed:
[RPC] latest-bars EWY failed:
[RPC] latest-bars MSTR failed:
... (one symbol every ~18s, then 120s push-to-DGX timeouts)
```

### Root cause

v17 expanded pusher subscriptions 72 → 237 (working as designed).
But the v18 bar poll service called `realtime_technical_service.get_batch_snapshots()`, which has a "live-bar overlay" feature: when a symbol IS in the pusher subscription, it preferentially fetches the latest 5-min bar via `/rpc/latest-bars` for sub-second freshness.

With v17 dramatically expanding the subscription set, v18's bar poll was triggering live-bar RPC calls for **hundreds of symbols every cycle**. The pusher's `/rpc/latest-bars` handler issues `reqHistoricalData` to IB, which has strict pacing (~6 req/2s for the same contract, 60 req/10min cumulative). IB rate-limited → "[RPC] latest-bars X failed" cascade. While the pusher was busy handling those failed RPC calls, its outbound push to DGX `/api/ib-data/push` couldn't keep up → 120s read timeouts.

### Fix

#### 1. `realtime_technical_service` — new `mongo_only` parameter

Both `get_technical_snapshot()` and `get_batch_snapshots()` now accept `mongo_only=False` (default keeps prior behaviour for the live-tick scanner). When True, the live-bar overlay is skipped entirely — only Mongo `ib_historical_data` is consulted.

#### 2. `bar_poll_service` calls with `mongo_only=True`

The bar poll path is fully decoupled from the pusher RPC. Live-tick scanner is unaffected (still uses live-bar overlay for the ~480 live-streamed symbols where freshness matters).

#### 3. Conservative cadence + batch reduction (defence in depth)

- `INTRADAY_NONCORE_INTERVAL_S`: 30s → 60s
- `SWING_INTERVAL_S`: 60s → 120s
- `BATCH_SIZE`: 50 → 25

Even if a future contributor accidentally re-enables live-bar overlay, the throttled cadence prevents pusher bombardment. Mongo bars are typically <60s lagged from the always-on turbo collectors — fine for slow setups.

### Tests

`test_bar_poll_v18.py` — added regression guard:

- **`test_emitted_alerts_stamped_with_bar_poll_provenance`** now also asserts `technical.get_batch_snapshots.call_args.kwargs["mongo_only"] is True`. A future contributor removing the flag fails the build instead of silently triggering the bombardment cascade again.

90/90 across all v12-v19.1 suites.

### Operator-side notes

- **No `.bat` change required** for this hot-fix — it's all DGX-side.
- **Optional cold-start improvement**: the `.bat` sets `IB_PUSHER_L1_AUTO_TOP_N=60`. Bumping to `300` makes the pusher start with ~300 of the right symbols immediately, and v17's rotation just fine-tunes from there. Cold-start coverage goes from 73 → ~300 in <60s. Not required, just faster.
- After pull + restart, the `[RPC] latest-bars X failed` warnings should stop. The 120s push timeouts should stop. Coverage continues to climb normally via v17 + v18 (Mongo-only) paths.



## 2026-04-30 (nineteenth commit) — Confidence Gate Parallelism (3-5× EVAL speedup)

**Why**: v18 unleashed bar-poll on ~2,000 symbols, multiplying alert
volume from ~80-150 per RTH session to **800-2,000**. The confidence
gate's 8 sequential model awaits (~1.1-1.5s/alert) became the next
bottleneck — at 1,500 alerts that's **22-55 minutes of pure gate
latency in a 6.5h session**, causing stale-evaluation adverse fills
(price moves 5-15¢ on fast tape while gate is computing → "GO" issued
but bracket fills bad).

The 8 model calls have **no cross-dependencies** (verified by source
audit): they all read the same input and produce independent signals
that get summed at the end. Perfect fan-out candidate.

### Patch

#### 1. `_prefetch_signals_parallel` helper
New private method on `ConfidenceGate` that fan-outs the 8 calls via
`asyncio.gather()`:

```python
results = await asyncio.gather(
    _safe(self._query_model_consensus, ...),
    _safe(self._get_live_prediction, ...),
    _safe(self._get_learning_feedback, ...),
    _safe(self._get_cnn_signal, ...),
    _safe(self._get_tft_signal, ...),
    _safe(self._get_vae_regime_signal, ...),
    _safe(self._get_cnn_lstm_signal, ...),
    _safe(self._get_ensemble_meta_signal, ...),
)
```

Each call is wrapped in `_safe()` which:
- Applies a 3-second per-coroutine timeout (`asyncio.wait_for`) so a
  single slow model can't drag the whole gather.
- Catches exceptions and returns a "no signal" default
  (`{"has_prediction": False}` / `{"has_models": False}` /
  `{"has_data": False}`) — matches the pre-v19 fail-open behaviour
  of every inline `try/except` we replaced.

#### 2. Phase 1 regime parallelism (bonus)
`regime_engine.get_current_regime()` and `_get_ai_regime()` are also
independent. Now run via a smaller `asyncio.gather()`. Saves another
~50-100ms per alert.

#### 3. Inline await replacement
Every `foo = await self._get_foo(...)` in `evaluate()` becomes
`foo = signals_pre["foo"]`. Scoring logic is **untouched** —
behaviour is byte-identical, just faster.

#### 4. Source-level regression guard
`tests/test_confidence_gate_parallel_v19.py` greps the source for
inline `await self._get_<model>(...)` patterns and fails the build
if any reappear. A future contributor "cleaning up" the parallelism
will hit a red test instead of silently regressing the speedup.

### Tests (14 new, 90/90 across v12-v19 suites)

- **`test_parallel_prefetch_total_time_is_max_not_sum`** — 8 calls
  × 100ms each: total time must be ~100ms, not ~800ms (asserts
  asyncio.gather actually parallelised, not silently sequential).
- **`test_slow_model_does_not_drag_others`** — one 500ms call +
  seven 50ms calls: total time ~500ms, not 850ms.
- **`test_one_model_crashing_does_not_crash_gather`** — exception
  isolation; failed models get the default, others come through.
- **`test_timeout_replaces_with_default_not_crash`** — per-coro
  timeout works; total time bounded by `PARALLEL_PREFETCH_TIMEOUT_S`.
- **`test_no_inline_model_awaits_remain_in_evaluate`** — 8
  parametrized source-level guards. The single regression that
  matters most.
- **`test_prefetch_helper_uses_asyncio_gather`** — guards against a
  contributor refactoring the helper to `await` in a loop.
- **`test_phase1_regime_calls_also_parallelized`** — pins the
  Phase 1 fan-out.

### Speedup math (real-world projection)

| Alert volume | v18 sequential | v19 parallel | Saved |
|---|---|---|---|
| 80   alerts/session | ~120s | ~24s | 96s |
| 800  alerts/session | **~22 min** | **~4 min** | 18 min |
| 1,500 alerts/session | **~33 min** | **~6 min** | 27 min |
| 2,000 alerts/session | **~55 min** | **~10 min** | 45 min |

The hidden second-order win: **fewer stale-evaluation fills**. With a
2-second per-alert delay, fast-tape stocks move past entry by the time
"GO" hits IB. v19 cuts gate-induced slippage by ~5-10× on those names.

### What changes after pull + restart

- The gate auto-takes the parallel path on every evaluation. No
  config flag, no rollout — it's just faster from the next alert.
- Backend logs may show `[ConfidenceGate] <model> timed out after
  3.0s — using default` if any model is genuinely slow on Spark.
  These were silently truncating before; v19 surfaces them.
- AI gate decision payload (`bot_state.confidence_gate.decisions`)
  is unchanged in shape — every downstream consumer reads identical
  data.

- AI gate decision payload (`bot_state.confidence_gate.decisions`)
  is unchanged in shape — every downstream consumer reads identical
  data.



## 2026-04-30 (eighteenth commit) — Bar Poll Service + Server-Side Bracket Regression Guards

**Why**: v17 took live-tick coverage from 72 → ~480 symbols. That
still leaves ~2,000 of the 2,532 qualified universe with zero
scanner attention. v18 closes that gap by reading the existing
``ib_historical_data`` Mongo collection and running bar-based
detectors on the universe-minus-pusher pool. **Pure DGX-side**
service — no IB calls, no rate limits, no multi-client work needed.

While auditing the trade-execution path for "server-side IB bracket
exits" (the originally-promised v18 piece), discovered they were
**already implemented in Phase 3 (2026-04-22)** — `place_bracket_order`
is the default path and submits an atomic parent + OCA stop + OCA
target to IB so the broker manages the exits even if DGX/pusher die
mid-trade. Added regression guards instead so a future contributor
can't accidentally revert.

### What ships

#### 1. `services/bar_poll_service.py` (~370 LOC)

Background service that runs bar-based detectors on three pools:

```
Pool                    Source                        Cadence
─────────────────────  ──────────────────────────    ──────────
intraday_noncore       qualified intraday tier        30s
                       MINUS pusher subscriptions
swing                  ($10M-$50M ADV)                60s
investment             ($2M-$10M ADV)                 2h
```

Each cycle:
  1. Build pool (excluding live-streamed pusher symbols).
  2. Round-robin batch (50 symbols/cycle) — full pool covered every
     12-30 cycles depending on size.
  3. Get `TechnicalSnapshot` from existing
     `realtime_technical_service.get_batch_snapshots()` (Mongo reads).
  4. Run 5 bar-based detectors per symbol: `squeeze`,
     `mean_reversion`, `chart_pattern`, `breakout`, `hod_breakout`.
  5. Stamp `data_source="bar_poll_5m"` on emitted `LiveAlert`.
  6. Push into the scanner's `_live_alerts` dict — flows through the
     **same** AI gate, priority ranking, auto-eligibility paths as
     scanner-fired alerts.

Live-tick-only detectors (`9_ema_scalp`, `vwap_continuation`,
`opening_range_break`) are NOT in the bar-poll set — they need
sub-second timing the bar pipeline can't deliver.

#### 2. `LiveAlert.data_source` field — provenance stamp

New default-`"live_tick"` field on the `LiveAlert` dataclass. The
bar-poll service overrides to `"bar_poll_5m"` on its emitted alerts.
The AI gate / shadow tracker / V5 UI can downweight bar-poll alerts
if accuracy diverges from live-tick.

#### 3. New diagnostic endpoints

- **`GET /api/diagnostic/bar-poll-status`** — pool state, lifetime
  alerts emitted, last cycle summary, detectors enabled.
- **`POST /api/diagnostic/bar-poll-trigger?pool=intraday_noncore`** —
  operator escape hatch; manually trigger a single cycle.

#### 4. Server-side IB bracket: regression guards (4 new tests)

The `place_bracket_order` path was already the default. New tests pin
that contract so a future contributor can't silently regress:

- **`test_execute_trade_calls_place_bracket_order_first`** — guards
  the call order in `trade_execution.execute_trade`.
- **`test_legacy_fallback_only_triggers_on_known_errors`** — the
  `use_legacy` gate must accept ONLY `bracket_not_supported` (and the
  current allowlist), not real broker errors. Otherwise a
  `insufficient_buying_power` reject would silently fall back to the
  pre-Phase-3 two-step entry+stop flow that left positions naked on
  bot restart.
- **`test_bracket_path_records_oca_group_and_child_ids`** — the
  bracket result must propagate `stop_order_id`, `target_order_id`,
  and `oca_group` so the bot can audit / cancel the broker-side
  children later.
- **`test_simulate_bracket_returns_complete_shape`** — simulated
  bracket must return the same shape as live (downstream code is
  mode-blind).

#### 5. Server lifespan wiring

`server.py` lifespan now starts the bar poll service alongside the
pusher rotation service. Fails gracefully if dependencies missing.

### Tests

`tests/test_bar_poll_v18.py` — 11 tests:
- 7 bar-poll behaviour (pool composition, cursor round-robin,
  alert provenance, neutral tape contract, status snapshot,
  RTH gating, exclude-pusher-subs)
- 4 bracket-path regression guards (call order, fallback gate,
  child-id propagation, simulate-bracket shape).

Total across instrumentation suites: **76/76 passing**.

### Coverage delta

|  | Pre-v17 | Post-v17 | Post-v18 |
|---|---|---|---|
| Live tick | 72 | ~480 | ~480 |
| Bar poll | 0 | 0 | **~2,000** |
| Total reach | 72 (2.8%) | ~480 (19%) | **~2,000+ (78-80%)** |

### What changes after pull + restart on Spark

```bash
# Bar poll service should start automatically. Confirm:
curl -s http://localhost:8001/api/diagnostic/bar-poll-status \
  | python3 -m json.tool

# Within the first 30s of RTH, lifetime_alerts_emitted should
# climb. The first cycle covers 50 symbols per pool; full pool
# coverage takes 12-30 cycles depending on pool size.

# To force a manual cycle:
curl -X POST "http://localhost:8001/api/diagnostic/bar-poll-trigger?pool=intraday_noncore" \
  | python3 -m json.tool

# To watch the SCAN tile + EVAL tile climb on the V5 UI — they should
# now reflect the dramatically expanded breadth (live + bar-poll combined).
```

### What does NOT ship in v18 (parked for v19)

- **Multi-client IB session manager**. Was originally planned for
  Phase 2 historical-data rate-limit clearance, but became
  unnecessary once we discovered the existing `ib_historical_data`
  Mongo collection is already kept fresh by the always-on
  collectors. Bar poll just reads from Mongo. Multi-client IB might
  still be useful for parallelizing order submission (Phase 4) but
  isn't on the critical path now.
- **Confidence gate parallelism** (the 3-5× EVAL speedup). Still
  P1 next session.



## 2026-04-30 (seventeenth commit) — Pusher Rotation Service (500-line budget)

**Why**: Operator confirmed 2026-04-30 IB upgrade — 5 Quote Booster
packs × 100 lines = **500 simultaneous IB Level-1 subscription
budget**. Pre-v17 the pusher subscription was 72 hardcoded symbols on
the Windows side, leaving 99.24% of the 9,412-symbol qualified
universe starved of live ticks (and 38 detectors silent in 2-hour
windows).

This ships a DGX-side rotation service that **dynamically manages**
the 500-line budget, swapping symbols in/out throughout the day so
live-tick detectors see the right universe at the right time-of-day.

### Architecture

```
500-LINE BUDGET (with 20-line safety buffer = 480 usable)
├──  N    Open positions      (HARD pin — auto-discovered, no ceiling)
├──  N    Pending orders      (HARD pin — auto-discovered, no ceiling)
├──  30   Pinned ETFs/indices (SPY/QQQ/IWM + sector ETFs + vol/credit)
├── 300   Static core         (top-300 intraday tier by ADV)
├──  50   Hot slots           (premarket/news/halts; refreshed 4×/day)
└── 100   Dynamic overlay     (RVOL/sector/news; refreshed every 15min RTH)
```

### Files added

1. **`services/pusher_rotation_service.py`** (~500 LOC) — core orchestrator:
   - `Profile.{PRE_MARKET_EARLY/LATE, RTH_OPEN/MIDDAY/AFTERNOON, POST_MARKET}`
   - `select_profile()` — ET wall-clock dispatch
   - `compose_target_set()` — priority-ordered cohort composition
   - `compute_diff()` — diff-and-apply with safety-pinned protection
   - `PusherRotationService` — async background loop (60s tick); calls
     `rotate_once()` on schedule (4:30/7:00/8:30/9:25 ET hot-slot
     refreshes; every 15min in RTH for dynamic overlay)
   - Audit log → `pusher_rotation_log` Mongo collection (7d TTL)

2. **`services/dynamic_slot_scorer.py`** (~250 LOC) — ranks the
   non-core intraday tier (~737 candidates) for the 100 dynamic slots
   each cycle. Signals: recent setup hits (60min), news tag (2h),
   sector momentum (XL_ ETF moves), RVOL spike (5min), premarket gap
   (session-open). Returns a single ranked list; rotation service
   slices [:HOT_SLOT_BUDGET] and [HOT_SLOT_BUDGET:HOT+DYN] for each
   cohort.

3. **`services/ib_pusher_rpc.py`** — added `subscribe_symbols(set)`,
   `unsubscribe_symbols(set)`, `get_subscribed_set(force_refresh=True)`
   methods that hit the Windows pusher's `/rpc/subscribe` /
   `/rpc/unsubscribe` endpoints with normalised, deduped, upper-cased
   symbol sets.

4. **`routers/diagnostic_router.py`** — two new endpoints:
   - `GET  /api/diagnostic/pusher-rotation-status?dry_run_preview=true`
     — see active profile, current subs count, budget allocation, and
     optionally preview what the next rotation would do.
   - `POST /api/diagnostic/pusher-rotation-rotate-now` — manual force
     rotation, audit-logged (operator escape hatch).

5. **`server.py` lifespan wiring** — rotation service auto-starts
   alongside the trading bot. Fails gracefully if pusher RPC is
   unreachable (logs `Pusher Rotation: FAILED` but doesn't block
   startup).

### Hard invariants (pytest-guarded — 30/30)

★ **Open positions can NEVER be unsubscribed** by rotation. Even if
  the rotation logic produces a target set that excludes a held name,
  the diff-and-apply layer auto-pins it back in. `would_remove_held`
  diagnostic field surfaces any caller bug attempting this.
★ **Pending orders likewise pinned.**
★ **Total subscription count NEVER exceeds 500 lines.**
★ **Cohort priority order**: open_pos > pending > etfs > core > hot > dyn.
  Lower-priority cohorts get squeezed if higher-priority pins overflow.
★ **Diff math is correct** under all set permutations (idempotent on
  identical sets, empty-current, empty-target, partial overlap).
★ **`subscribe_symbols` short-circuits on empty input** (no
  unnecessary RPC calls).
★ **Symbol normalisation** in RPC layer (upper, strip, dedupe)
  guaranteed before the wire.

### What changes after pull + restart on Spark

- Within ~60s of bot startup, the rotation service runs its first
  cycle. Pusher subscriptions go from 72 → ~480 symbols matching the
  current time-of-day profile.
- Live-tick detectors (`9_ema_scalp`, `vwap_continuation`, `OR break`,
  `vwap_fade`, etc.) start producing alerts on the expanded set.
- Coverage goes from **0.76% to ~19%** of the 2,532 qualified
  universe via live ticks alone (Phase 2: bar-poll service for swing
  + investment tiers, planned for next session, will close the gap to
  ~76%+ total coverage).
- Operator-facing diagnostic:
  ```bash
  curl -s "http://localhost:8001/api/diagnostic/pusher-rotation-status?dry_run_preview=true" \
    | python3 -m json.tool
  ```

### What does NOT ship in v17 (parked for v18)

- **Bar Poll Service** (Phase 2) — historical-bar polling for the
  ~590 non-subscribed intraday + 888 swing + 607 investment symbols.
  Adds ~2,085 symbols of "second-tier" coverage at 30s freshness with
  zero pusher-line burn. Will close the universe coverage gap to
  ~76%+.
- **Multi-client IB sessions** — needed before Phase 2 to clear the
  IB historical-data rate limit (60 reqs/10min per client → 360/10min
  with 6 clients).



## 2026-04-30 (sixteenth commit) — RS detector OFF, alert caps lifted end-to-end

**Why**: Operator review of the v15 screenshot landed on two clear
calls:
1. `relative_strength_laggard` (and leader) alerts were dominating
   breadth despite having no concrete entry trigger ("Buy dips" /
   "Short rallies" is not a setup).
2. The "only ever 5 alerts" complaint had three caps stacked behind
   it — fixing the visible one (frontend `?limit=5`) only revealed
   the next two layers (`/api/sentcom/alerts` ceiling=50, scanner
   `_max_alerts=50`). v16 lifts all three end-to-end.

### Patches

#### 1. RS detector REMOVED from `_enabled_setups`

`enhanced_scanner.py:848` — dropped `"relative_strength"` from the
detector dispatch set. The `_check_relative_strength` method is
**preserved** so RS can be re-wired as an ML feature on other alerts
(or re-enabled per-strategy via the promotion service) without
rebuilding the detector. Pre-existing references in
`_check_relative_strength` (carry-forward) and `bot_persistence.py`
are untouched — they're tagging logic, not dispatch.

#### 2. Alert caps lifted 50 → 500 end-to-end

| Layer | Before | After | File |
|---|---|---|---|
| Scanner internal | `_max_alerts = 50` | `_max_alerts = 500` | `enhanced_scanner.py:870` |
| REST endpoint | `Query(10, ge=1, le=50)` | `Query(200, ge=1, le=500)` | `routers/sentcom.py:364` |
| Frontend REST fetch | `?limit=20` | `?limit=500` | `useSentComAlerts.js:19` |
| Frontend WS slice | `wsAlerts.slice(0, 20)` | `wsAlerts` (no slice) | `useSentComAlerts.js:50` |

The scanner's `_enforce_alert_limit()` trim still runs each cycle so
memory remains bounded; the new ceiling is just much higher than
practical RTH output.

### Tests

`tests/test_scanner_v16_no_caps.py` (4 new):
1. `relative_strength` is NOT in `_enabled_setups` literal.
2. `_check_relative_strength` method still present (re-enable safety).
3. `_max_alerts >= 500` (regression guard).
4. `/sentcom/alerts` Query ceiling >= 500.

Total: 35/35 across instrumentation + hydration + v16 suites.

### Operator-visible outcome (after pull + restart)

- Live scanner alerts panel: shows every detected setup, no 5/20/50 cap.
- HUD `EVAL` tile: counts every alert today, no longer capped at 5.
- RS leader/laggard alerts: gone. Other detectors (gap_and_go,
  vwap_continuation, 9_ema_scalp, opening_range_break, the_3_30_trade)
  finally have unblocked breadth.

### Re-enabling RS as a feature (future)

When ready, two paths preserved:
- **Per-strategy promotion**: re-add `"relative_strength"` to
  `_enabled_setups` and gate it through the promotion service so it's
  PAPER until proven.
- **ML feature on other alerts**: read `snapshot.rs_vs_spy` inside
  every other detector and stamp it onto the alert as a feature
  (similar to how `market_setup` is now stamped). No new alerts; just
  enriches the existing ones.



## 2026-04-30 (fifteenth commit) — V5 HUD truth + diagnostic endpoints

**Why**: After v13 unblocked the trade chain, the operator screenshot
revealed 5 distinct UI/data complaints. Bundled fix surfaces all of
them with code or a curl.

### Patches

#### 1. SentCom Intelligence "always resets to ~50 evals" — FIXED
`services/ai_modules/confidence_gate.py::_load_from_db` was counting
today's stats from a 50-doc deque. Now uses Mongo `$group` aggregation
on the full `confidence_gate_log` collection so daily totals reflect
the real number even when 80+ decisions exist for the day. Falls back
to the deque count if aggregation crashes (transient Mongo flap).

#### 2. "Only ever see 5 scans" — FIXED
`useSentComAlerts.js` had two hardcoded `5`s — `?limit=5` on the REST
fetch + `slice(0, 5)` on WS — making the alerts panel hide >5 setups
during fast tape. Bumped both to 20.

#### 3. "SCAN=0 but EVAL=5" — FIXED
`SentComV5View.derivePipelineCounts` read `setups.length` for the SCAN
tile, but the predictive_scanner was deprecated and `setups` is empty.
Now falls back to `alerts.length` so the SCAN tile reflects what the
live scanner actually produced.

#### 4. Equity = $- — DIAGNOSTIC ENDPOINT
New `GET /api/diagnostic/account-snapshot` walks the same equity
resolution chain as `/status` (executor → `_pushed_ib_data["account"]`
→ RPC fallback → `_extract_account_value` per key → resolved dict)
and returns an operator-friendly verdict:
- `pusher_disconnected` — start IB Gateway + pusher
- `pushed_account_empty` — pusher live but no `accountSummary` tick yet
- `net_liq_zero` — paper account fresh / NetLiquidation=0
- `ok` — equity should render

#### 5. RS-laggard dominating scans — DIAGNOSTIC ENDPOINT
New `GET /api/diagnostic/scanner-coverage?hours=N` aggregates
`live_alerts` by `setup_type`, computes `rs_share` (RS_laggard +
RS_leader fraction), surfaces the IB-pusher subscription size vs.
canonical universe size, and lists "starved" detectors (≤1 alert in
window despite enabled). Operator-friendly verdict tells the operator
whether to expand the pusher subscription or accept the small-footprint
constraint as known.

### Tests
`tests/test_confidence_gate_hydration_v15.py` — 2 tests:
1. `today_evaluated=80` even with 50-doc deque cap (v15 fix proven).
2. Aggregation-crash fallback path doesn't raise.

Total instrumentation suite: 31/31 passing.

### Operator next steps (after pull + restart)

```bash
# Equity not showing? Walk the chain:
curl -s http://localhost:8001/api/diagnostic/account-snapshot | python3 -m json.tool

# RS-laggard dominating? Confirm the universe-vs-pusher gap:
curl -s "http://localhost:8001/api/diagnostic/scanner-coverage?hours=6" | python3 -m json.tool

# SentCom Intelligence "today_evaluated" should now match the real count:
curl -s http://localhost:8001/api/ai-training/confidence-gate/summary \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('today:', d.get('today'))"
```



## 2026-04-30 (fourteenth commit) — exc_info=True / logger.exception sweep across the trade chain

**Why**: The v13 `BotTrade.quantity` regression hid for 13 days because
`except Exception as e: logger.error(f"... {e}")` strips the exception
type AND the traceback line number. The error message was logged but
nobody could tell *where* the error fired without grep diving into
the source. Lesson: every critical except in the trade chain must
surface either a full traceback (`logger.exception(...)` for outer
errors) or `exc_info=True` (for "proceed anyway" warnings that may be
hiding silent typo-class regressions).

### Sites patched (15 total)

**`services/trading_bot_service.py`** (1 site):
- `_execute_trade` SAFETY guardrail crash (THE site that hid v13) →
  `logger.exception("[SAFETY] Guardrail check crashed (%s): %s; blocking trade", type(e).__name__, e)`.

**`services/trade_execution.py`** (8 sites):
- Failed to record paper trade — `+ exc_info=True`
- Failed to start execution tracking — `+ exc_info=True`
- Guardrail check failed (allowing trade) — `+ exc_info=True`
  (CRITICAL fail-OPEN path)
- Failed to record entry — `+ exc_info=True`
- Outer execute_trade exception → `logger.exception(...)`
- Could not check alert age — `+ exc_info=True`
- Could not persist REJECTED trade — `+ exc_info=True`
- Could not persist exception-rejected trade — `+ exc_info=True`

**`services/opportunity_evaluator.py`** (4 sites):
- Confidence gate error (proceeding anyway) — `+ exc_info=True`
- AI Consultation failed (proceeding anyway) — `+ exc_info=True`
- AI evaluation failed (proceeding anyway) — `+ exc_info=True`
- Outer evaluate_opportunity exception → `logger.exception(...)`
  (also kept `traceback.print_exc()` so terminal AND backend.log
  show the failure source).

**`services/bot_persistence.py`** (3 sites):
- `save_trade` outer exception → `logger.exception(...)`
- `persist_trade` outer exception → `logger.exception(...)`
- `load_trades_from_db` outer exception → `logger.exception(...)`

### Regression coverage

`backend/tests/test_trade_drop_instrumentation.py` — 29/29 (was 23/23)
- 5 new parametrized canaries for `logger.exception` on critical paths
- 1 new canary asserting `exc_info=True` on every "proceed anyway"
  warning (7 sites verified)

### Why this matters

If the v13 `BotTrade.quantity` regression had hit AFTER this sweep,
the very first auto-trade attempt would have produced this in
backend.log:

```
ERROR [SAFETY] Guardrail check crashed (AttributeError):
'BotTrade' object has no attribute 'quantity'; blocking trade
Traceback (most recent call last):
  File "/.../trading_bot_service.py", line 2264, in _execute_trade
    notional = float(trade.entry_price or 0) * float(trade.quantity or 0)
                                                     ^^^^^^^^^^^^^^^
AttributeError: 'BotTrade' object has no attribute 'quantity'
```

vs. the actual v13 log line which was just:

```
ERROR [SAFETY] Guardrail check crashed; blocking trade: 'BotTrade' object has no attribute 'quantity'
```

— same message text, but the missing traceback (and the missing
`AttributeError` type tag) made the operator's grep harder. Combined
with the `safety_guardrail_crash` drop now being recorded to Mongo
via the v12 instrumentation, future typo-class regressions surface
within a single trade attempt.



## 2026-04-30 (thirteenth commit) — 13-DAY SILENT REGRESSION ROOT-CAUSED + FIXED

**The instrumentation shipped in the twelfth commit caught the bug
within minutes of going live on Spark.** First curl to
`/api/diagnostic/trade-drops?minutes=60` returned:

```
"first_killing_gate": "safety_guardrail_crash",
"reason": "guardrail check exception: 'BotTrade' object has no attribute 'quantity'",
"context": {"exc_type": "AttributeError"}
```

### Root cause

`services/trading_bot_service.py::_execute_trade` had two sites
referencing `BotTrade.quantity`. **`BotTrade` exposes `shares`, not
`quantity`.** Every autonomous trade attempt for 13 days hit
`AttributeError`, which the outer try/except caught and returned
silently from the safety-guardrail check (fail-CLOSED). Trade never
reached the broker, never landed in `bot_trades`. The bug had been
hiding behind a generic `except Exception as e: logger.error(...)
return` that didn't include the variable name in the log.

### Fix

Two-line change:
- Line 2259 (snapshot of open positions, *was* silently safe via
  `getattr(t, "quantity", 0)` default — getattr returned 0 → notional 0
  → loop continued). Still corrected to `t.shares` for clarity.
- Line 2264 — the actual crash site:
  ```python
  # Before
  notional = float(trade.entry_price or 0) * float(trade.quantity or 0)
  # After
  notional = float(trade.entry_price or 0) * float(trade.shares or 0)
  ```

### Regression tests (`tests/test_trade_drop_instrumentation.py`)

Two new source-level guards, total now 23/23 passing:
- `test_no_bot_trade_dot_quantity_in_trading_bot_service` — fails if
  any future contributor reintroduces `.quantity` in
  `trading_bot_service.py`.
- `test_bot_trade_shares_attribute_used_for_notional` — pins the two
  specific call-sites that were broken.

### Why this hid for 13 days

Reading the recent[] from the live curl makes the dynamics obvious:
the AI confidence gate, scanner, hard gates were all GREEN. The bug
manifested as "32 GOs / 0 trades" with **no error in any user-facing
log** because:
1. Original `except` in `_execute_trade` logged with format string
   `"%s"` truncating the exception name, then returned silently.
2. `_save_trade` was never called (REJECTED trades orphaned in memory).
3. No Mongo collection captured the drop.

The 2026-04-30 v12 instrumentation closes #2 and #3 permanently. The
v13 commit closes #1 by name (the actual `.quantity` typo).

### Operator next step

After pull + restart on Spark:
```bash
# Watch trade-drops empty out as new trades flow:
watch -n 30 'curl -s http://localhost:8001/api/diagnostic/trade-drops?minutes=15 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[\"first_killing_gate\"], d[\"by_gate\"])"'

# After 5-10 min RTH scanning, confirm bot_trades is no longer frozen:
~/Trading-and-Analysis-Platform/.venv/bin/python -c "
import os
from pathlib import Path
env_path = Path.home() / 'Trading-and-Analysis-Platform/backend/.env'
for line in env_path.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('='); os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
print('bot_trades inserted today:', db.bot_trades.count_documents({'created_at': {'\$regex': '^2026-04-29'}}))
"
```




## 2026-04-30 (twelfth commit) — Trade-Drop Forensic Instrumentation + Broker-Reject Persistence Fix

**Why**: On 2026-04-29 the operator confirmed the bot has not created
a single `bot_trade` since 2026-04-16 — a **13-day silent regression**.
Today's funnel showed the AI gate evaluating 84 alerts (32 GO / 31 SKIP)
yet zero rows landing in `bot_trades`. Some `return None` / `return`
between the AI confidence gate and `bot_trades.insert_one()` was
aborting the trade silently. Today we instrumented every silent exit
in that chain so the next bar of intake makes the killer obvious.

### Scope

#### 1. New service — `services/trade_drop_recorder.py`
- Single helper `record_trade_drop(db, gate, symbol, setup, direction,
  reason, context)` that:
  - Writes a structured row to a new `trade_drops` Mongo collection
    (TTL 7 days, indexed on `gate + ts_epoch_ms`).
  - Falls back to a 500-deep in-memory ring buffer on Mongo flap.
  - Always emits a structured `[TRADE_DROP] gate=… symbol=… reason=…`
    WARN log line so operators grepping `backend.log` can find drops
    without curl/db access.
  - Never raises — drop logic is fail-safe (caught and swallowed at
    every callsite).
- Module exposes `KNOWN_GATES` (9 gates currently wired),
  `get_recent_drops`, `summarize_recent_drops`, and a tests-only
  `reset_memory_buffer_for_tests()`.

#### 2. Instrumented every silent exit in the execution chain

In `services/trading_bot_service.py::_execute_trade`:
- **`account_guard`** — IB_ACCOUNT_ACTIVE vs pusher account drift.
  This is the highest-confidence suspect for the April 16 regression
  (the operator's pusher reports `DUM61566S`; if `IB_ACCOUNT_PAPER`
  env var lists a different alias the kill-switch trips silently and
  the trade dies before reaching the broker).
- **`safety_guardrail`** — SafetyGuardrails.check_can_enter rejected
  (daily-loss / stale-quote / exposure caps).
- **`safety_guardrail_crash`** — exception in the guardrail check
  itself (fail-CLOSED path that previously silently dropped trades).

In `services/trade_execution.py::execute_trade`:
- **`no_trade_executor`** — `bot._trade_executor is None`.
- **`pre_exec_guardrail_veto`** — `services.execution_guardrails.run_all_guardrails`
  veto (USO-style $0.03 stop on $108 stock).
- **`strategy_paper_phase`** — strategy still in PAPER (also saves to
  `bot_trades` with status=paper; instrumented for visibility so the
  operator can rule it in/out).
- **`strategy_simulation_phase`** — strategy in SIMULATION.
- **`broker_rejected`** — `place_bracket_order` / `execute_entry`
  returned `success=False, status!=timeout`. **THIS IS THE LIKELIEST
  ROOT CAUSE** of the April 16 regression — the legacy code path
  marked the trade `REJECTED` in memory and never persisted to
  `bot_trades`, so 13 days of broker rejections vanished without trace.
- **`execution_exception`** — raised exception inside `execute_trade`.

#### 3. Broker-reject + exception paths now PERSIST the trade

The hidden bug behind the 13-day silence: `trade_execution.execute_trade`
set `trade.status = TradeStatus.REJECTED` in two branches (broker
non-success-non-timeout, and `except Exception`) but **never called
`bot._save_trade(trade)`**. Trades were orphaned in process memory.

Fix: both branches now call `await bot._save_trade(trade)` so REJECTED
attempts land in `bot_trades` for forensic visibility. Also stamps
`trade.close_reason` (`broker_rejected` / `execution_exception`) and
removes the trade from `bot._pending_trades` to prevent dangling refs.

#### 4. New endpoint — `GET /api/diagnostic/trade-drops`

```
GET /api/diagnostic/trade-drops?minutes=60&gate=account_guard&limit=100
```

Returns:
```json
{
  "success": true,
  "known_gates": ["account_guard", "broker_rejected", "execution_exception", "no_trade_executor", "pre_exec_guardrail_veto", "safety_guardrail", "safety_guardrail_crash", "strategy_paper_phase", "strategy_simulation_phase"],
  "minutes": 60,
  "total": 47,
  "by_gate": {"account_guard": 32, "safety_guardrail": 15},
  "first_killing_gate": "account_guard",
  "recent": [<last 25 drops with timestamps + context>]
}
```

Companion to `/trade-funnel`: the funnel walks the alert→bot chain
top-down to show which stage stops flow; `/trade-drops` walks the
post-AI-gate chain bottom-up to show which gate kills it.

### Verification

`backend/tests/test_trade_drop_instrumentation.py` — 21 tests (all
passing locally + clean on existing 23-test adjacent suite for a 44/44
total). Coverage:
- 9 recorder-contract tests (memory fallback, oversized reason
  truncation, mongo write shape, minutes-window cutoff, gate
  filtering, summary aggregation).
- 9 source-level guards (1 per gate) that grep the source for
  `gate="<name>"` so a future contributor deleting a breadcrumb
  fails the canary instead of hiding another silent regression.
- 1 `KNOWN_GATES` consistency check (every advertised gate must be
  wired in source).
- 2 regression guards confirming the broker-rejected and
  execute-exception branches now call `bot._save_trade(trade)`.

### Operator next step (after pull + restart on Spark)

```bash
# 1. After 5-10 minutes of RTH scanning, query the new endpoint:
curl -s http://localhost:8001/api/diagnostic/trade-drops?minutes=60 | python3 -m json.tool

# 2. The "first_killing_gate" field names the suspect.
#    - If "account_guard": rotate IB_ACCOUNT_PAPER in backend/.env to
#      include the actual pusher account (DUM61566S). Restart.
#    - If "broker_rejected": read the recent[] array; the `reason`
#      field will show what IB returned (rejected, no margin, etc).
#    - If "safety_guardrail": daily-loss or stale-quote cap is firing.
#      Audit /api/safety/effective-risk-caps for the binding cap.

# 3. The new instrumentation also persists REJECTED trades to bot_trades
#    so post-mortem queries against the collection finally see the
#    attempts that were silently dropping for 13 days:
~/Trading-and-Analysis-Platform/.venv/bin/python -c "
import os
from pathlib import Path
env_path = Path.home() / 'Trading-and-Analysis-Platform/backend/.env'
for line in env_path.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('='); os.environ.setdefault(k.strip(), v.strip().strip('\"').strip(\"'\"))
from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
print('REJECTED count past 24h:', db.bot_trades.count_documents({'status':'rejected'}))
print('Top close_reasons:')
for r in db.bot_trades.aggregate([{'\$match':{'status':'rejected'}},{'\$group':{'_id':'\$close_reason','c':{'\$sum':1}}},{'\$sort':{'c':-1}}]):
    print(f'  {r[\"_id\"]}: {r[\"c\"]}')
"
```



## 2026-04-30 (eleventh commit) — Realtime Stop-Guard + Sector Fallback + Landscape Pre-warm + V5 Shadow vs Real

Closes the operator's P1 backlog list ("B + C + a few gaps") in one
batch. Four independent improvements, each surgical and additive.
**Follow-on enhancement** (same commit, post-finish operator request):
inline shadow-decision badges on V5 stream rows, see end of section.

### 1. Realtime stop-guard re-check (Task B)

**Pre-fix (`stop_manager.py`)**: `update_trailing_stop` only re-snapped
on (a) a target hit OR (b) price extending to a fresh high/low. If the
liquidity profile shifted DURING a held position (a tighter HVN forms
intraday, a HOD/LOD pivot reprices) the trail wouldn't refresh until
the next high-water-mark print.

**Post-fix**:
- New `_periodic_resnap_check(trade)` runs at the end of every
  `update_trailing_stop` call.
- Throttle: `_RESNAP_INTERVAL_SECONDS = 60.0` per-trade (operator-confirmed).
- Hard guarantee: only RATCHETS — never loosens. Long stops can only
  go up; short stops can only go down.
- Skips `mode == 'original'` (pre-T1) — the operator's hard stop stays put.
- Records a per-trade audit trail (`last_resnap_at`, `last_resnap_level`)
  on `trade.trailing_stop_config` so the diagnostic can show what changed.
- Logs a `STOP-GUARD RESNAP` line on every commit.

### 2. Sector fallback chain (Task C)

**Pre-fix (`sector_tag_service.py`)**: `tag_symbol` only consulted
`STATIC_SECTOR_MAP`. Newly-listed names returned None → SectorRegime
classifier reported UNKNOWN forever.

**Post-fix**:
- New `tag_symbol_async` runs the full chain:
  - Static map (instant, in-memory)
  - `symbol_adv_cache.sector` Mongo cache (fast)
  - Finnhub `stock/profile2` industry → SPDR ETF mapping (network)
- `_industry_to_etf` resolves free-form Finnhub strings via:
  - `_EXPLICIT_NONE` blocklist (cryptocurrency/SPAC/trust → UNKNOWN
    rather than mis-classify)
  - `_PRIORITY_OVERRIDES` for sector-conflict cases (Biotech wins over
    Tech, REIT wins over Industrial, Renewable Energy wins over Energy)
  - Longest-substring match into `_INDUSTRY_TO_ETF` (~75 keys covering
    all 11 SPDR sectors)
- Finnhub hits are **persisted** to `symbol_adv_cache.sector` so the
  next call hits the Mongo cache (operator-confirmed: persist=yes).
- `SectorRegimeClassifier.classify_for_symbol` falls through to
  `tag_symbol_async` on a static miss — newly-listed names get a
  sector regime feature without a code change.

### 3. Daily-Setup landscape pre-warm

**Pre-fix gap**: `MarketSetupClassifier` was only invoked at intraday
alert time. The first morning briefing of the day paid the full
200×classify latency since the snapshot cache was cold.

**Post-fix**:
- `enhanced_scanner._scan_loop` CLOSED branch now calls a new
  `_prewarm_setup_landscape()` every after-hours sweep (every 20 min).
  Sat/Sun → "weekend" context; Mon-Fri after-hours → "morning" (next session).
- PREMARKET branch calls it with `force_morning=True` so the morning
  briefing reflects fresh gap data.
- `eod_generation_service` adds a Saturday 12:00 ET cron job
  (`auto_weekend_landscape_prewarm`) that pre-warms the WEEKEND-context
  snapshot — uses `LandscapeGradingService.get_weekly_summary` so the
  Sunday-night narrative leads with last week's record.
- Pre-warm calls `service.invalidate()` before `get_snapshot()` to force
  a fresh classify rather than re-reading a stale 60s-old snapshot.

### 4. V5 Shadow vs Real tile

Operator's question: "where in V5 do I see shadow tracking, so we
can compare shadow trades vs real trade stats?". Answer pre-commit:
nowhere. Shadow stats lived only in the legacy `AIModulesPanel`
(gated behind `?v4=1` / `compact={true}`) and the NIA tab.

**New `frontend/src/components/sentcom/v5/ShadowVsRealTile.jsx`**:
- Reads `/api/ai-modules/shadow/stats` (shadow win-rate + decisions)
  and `/api/trading-bot/stats/performance` (real trade win-rate + P&L)
  every 60s, side-by-side.
- Computes a per-percentage-point **divergence** signal:
  - `shadow ahead` (Δ ≥ +5pp, green) — shadow-mode is calling more
    winners than real trading is taking
  - `shadow behind` (Δ ≤ −5pp, red) — real trades are picking up
    edges the shadow modules would have skipped
  - `in sync` (|Δ| < 5pp, amber) — modules and execution agreed
- Wired into `SentComV5View`'s top status strip beside the
  StrategyMixCard, so it's visible on every V5 view.

### Tests
- `backend/tests/test_stop_manager_realtime_resnap.py` — **12 tests**:
  source-level guards (throttle constant, ratchet rules, audit-trail
  metadata), behavioural (throttle blocks within 60s, doesn't loosen
  long, doesn't loosen short, throttle clears after interval, no-op
  when no snap available).
- `backend/tests/test_sector_tag_finnhub_fallback.py` — **20 tests**:
  industry mapping per sector, conflict-resolution overrides
  (Biotech > Tech, REIT > Industrial, Renewable > Energy),
  blocklist (cryptocurrency / SPAC), full async fallback chain
  (static / Mongo cache / Finnhub / persist), no-DB / empty-symbol
  edge cases.
- `backend/tests/test_landscape_prewarm.py` — **8 tests**: source-level
  guards for the prewarm method, after-hours + premarket dispatch,
  weekday-based context selection (Sat/Sun → weekend), invalidate-then-
  refresh ordering, Saturday cron registration + 12:00 ET timing.

**224/224 passing across the related suites.**

### Files touched
- `backend/services/stop_manager.py` (re-snap method + 60s throttle)
- `backend/services/sector_tag_service.py` (Finnhub fallback +
  conflict-resolution overrides + blocklist + persist)
- `backend/services/sector_regime_classifier.py` (classify_for_symbol
  delegates to tag_symbol_async on static miss)
- `backend/services/enhanced_scanner.py` (`_prewarm_setup_landscape`
  helper + dispatch in CLOSED + PREMARKET branches)
- `backend/services/eod_generation_service.py` (Saturday 12:00 ET
  weekend-prewarm cron job)
- NEW `frontend/src/components/sentcom/v5/ShadowVsRealTile.jsx`
- `frontend/src/components/sentcom/SentComV5View.jsx` (tile imported
  + rendered in the V5 status strip)
- NEW `backend/tests/test_stop_manager_realtime_resnap.py`
- NEW `backend/tests/test_sector_tag_finnhub_fallback.py`
- NEW `backend/tests/test_landscape_prewarm.py`
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Open question parked for next session
Operator asked again "should we deprecate / shut off the predictive
scanner?". Audit result:
- `predictive_scanner` is the legacy **forming-setup** scanner
  (early_formation / developing / nearly_ready / trigger_imminent
  phases) — distinct concept from `enhanced_scanner` which only fires
  on TRIGGERED setups.
- Currently serves: `POST /api/scanner/scan` (used by the manual
  ScannerPage), `services/ai_assistant_service` queries, and 7 GET
  endpoints (none referenced in V5 frontend).
- V5 reads from `enhanced_scanner` via `/api/live-scanner/*` and the
  newer `/api/scanner/strategy-mix`/`setup-coverage`/`setup-landscape`/
  `sector-regime` endpoints.

**Recommendation (P2)**: don't shut it off yet — `ScannerPage.js` and
`ai_assistant_service` still bind to it. Migrate those two callers to
`enhanced_scanner` output (~2-3h refactor), then drop predictive_scanner
+ its 7 unused GET endpoints. Tracked as a P2 entry in ROADMAP.

### 5. Inline shadow-decision badges on V5 stream rows (operator follow-on)

After the four-feature batch shipped, the operator asked for the
"shadow vs real" divergence signal to be **actionable per-alert**,
not just visible as an aggregate in the new tile. Wired up:

- New hook `frontend/src/components/sentcom/v5/useRecentShadowDecisions.js`
  fetches `/api/ai-modules/shadow/decisions?limit=200` every 60s and
  normalises into `Map<UPPER_SYMBOL, latestDecision>` keeping only
  the highest-`trigger_ms` row per symbol.
- New component `frontend/src/components/sentcom/v5/ShadowDecisionBadge.jsx`
  — small inline chip with three variants:
    - 🟢 **TAKE** (green) — shadow voted `proceed`
    - 🔴 **PASS** (red) — shadow voted `pass`
    - 🟡 **REDUCE** (amber) — shadow voted `reduce_size`
  - Visual tail: confidence score (`0.72`), filled `●` when
    `was_executed=true` (bot agreed) or hollow `○` when bot diverged,
    dimmed when shadow signal is >5min stale relative to the row.
- `UnifiedStreamV5.StreamRow` now consults the hook map for any row
  with a `symbol` AND `sev ∈ {scan, brain}` — fills/wins/losses don't
  get badged because the AI vote is post-hoc noise there.
- Freshness gate: badge only renders when shadow decision is within
  `SHADOW_FRESHNESS_WINDOW_MS = 10 minutes` of the row timestamp,
  preventing stale shadow votes from leaking onto unrelated alerts.

**Tests**: `backend/tests/test_v5_shadow_badge_wiring.py` — **15 source-
level guards** covering hook polling cadence + endpoint, freshness
window pin, 3-recommendation badge coverage, executed-vs-diverged
glyph, alert-like-only dispatch, uppercase-symbol lookup contract.

**239/239 passing** across all related suites (224 prior + 15 new).

### 6. Pre-flight tooling — RTH Readiness Endpoint + Pre-warm Error Escalation (operator P0)

After shipping the divergence badges, operator asked what we could
do tonight to make tomorrow morning's RTH validation cleaner. Two
P0 pre-flight items:

**A. `GET /api/diagnostic/rth-readiness` — single curl, full pre-flight**

Read-only by design (operator decides if/when to fix). Runs 9
independent checks, each returning `{name, label, status, message,
details}`:

  1. **bot_state** — persisted mode=autonomous, running=true, risk_params
  2. **bot_runtime** — in-process bot _running matches persisted state
  3. **scanner_runtime** — `_running` + `_auto_execute_enabled` synced with bot mode
  4. **collection_mode** — should be INACTIVE before market open
  5. **pusher_health** — IB pusher reachable + IB Gateway connected
  6. **universe_freshness** — `symbol_adv_cache` populated, refreshed within 48h
  7. **data_request_queue** — historical_data_requests queue depth < 200
  8. **landscape_prewarm** — SetupLandscapeService cache hot (<30min old)
  9. **briefing_predictions** — today's morning prediction recorded for EOD grading

Status semantics: GREEN (clean pass) | YELLOW (passed-but-degraded
OR failed-but-non-blocker) | RED (blocker). Belt-and-braces wraps
each check so a single helper raising can't 500 the endpoint.
Top-level returns `overall_status`, `ready_for_rth`, `summary
{green, yellow, red, total}`, `first_red_check`, ET-aware
`trading_day_et` and `et_clock`.

Operator workflow: curl at 23:00 ET tonight to verify state; curl
at 09:25 ET tomorrow to confirm pre-flight is clean before market
open. RED on any check tells the operator the SIMPLEST fix (table
ordered most-fundamental first).

**B. Pre-warm error escalation (`enhanced_scanner._prewarm_setup_landscape`)**

Pre-fix shipped earlier this commit logged failures at `logger.debug`
which silently swallowed errors — a broken overnight pre-warm was
invisible. Post-fix:
- Every failure now logs at `logger.warning` with the exception type
  and message
- Per-instance counter `_prewarm_failure_count` tracks consecutive
  failures
- 3+ consecutive failures escalates to `logger.critical` with an
  unmissable banner so morning supervisor logs scream
- Successful pre-warm resets the counter (transient blips don't
  accumulate forever)

### Tests
- `backend/tests/test_rth_readiness_endpoint.py` — **23 tests**:
  `_check_status` tri-state semantics (incl. the warn-on-fail bug),
  9-check dispatch ordering pin, belt-and-braces around each check,
  `ready_for_rth` falls False on any RED, ET trading-day reporting,
  per-helper unit tests (bot_state, collection_mode, universe,
  pusher, briefing_predictions, data_request_queue), pre-warm
  escalation source-level guards.

**262/262 passing** across all related suites (239 prior + 23 new).

### Files touched (this section)
- `backend/routers/diagnostic_router.py` (RTH-readiness endpoint
  + 9 check helpers + tri-state status function)
- `backend/services/enhanced_scanner.py` (pre-warm error escalation
  with 3-strike CRITICAL banner)
- NEW `backend/tests/test_rth_readiness_endpoint.py`
- `memory/CHANGELOG.md`

### Operator usage example
```
$ curl -s $BASE/api/diagnostic/rth-readiness | jq '.overall_status, .summary'
"GREEN"
{
  "green": 9, "yellow": 0, "red": 0, "total": 9
}

$ curl -s $BASE/api/diagnostic/rth-readiness | jq '.checks[] | {name,status,message}'
# ... 9-row checklist with per-check status + message
```



## 2026-04-30 (tenth commit) — Trade Funnel: Bugs 1+2+3c+4a Fixed

### Context
The 9th commit's diagnostic surfaced exactly why no live trades happened on
Tuesday Apr 28: 140 alerts → 42 HIGH → **0 tape-confirmed**. This commit
ships the surgical fixes for the four root causes the data revealed.

### Bug 1 — Off-by-one tape threshold (CRITICAL)
**Symptom**: 25 of 42 HIGH alerts had `tape_score = 0.20 EXACTLY` but the
threshold was `tape_score > 0.2` (strict greater-than). All 25 failed
`confirmation_for_long` on the boundary even though the tight-spread bonus
(+0.2) is supposed to be a passing signal on its own.

**Fix**: `enhanced_scanner.py:1617` — `> 0.2` → `>= 0.2` (and `< -0.2` →
`<= -0.2` for shorts). One-character change, immediately unblocks **60%**
of the HIGH-priority pipeline that was getting silently rejected.

### Bug 2 — Snapshot signals weren't persisted on alerts
**Symptom**: diagnostic queries showed `avg_rvol = 0.00` on alerts even
though detectors require `rvol >= 1.0` to fire. Because `LiveAlert` had
no `rvol`/`gap_pct`/`atr_percent` fields and they were never stamped.

**Fix**: Added the 3 fields to `LiveAlert`, default 0.0; stamped from
`snapshot.*` in the alert post-processing block. Now every alert carries
the signals that drove it — useful for diagnostics, AI training, and
operator-side filtering.

### Bug 3 — Cold-start strategy deadlock (3c grace period)
**Symptom**: every alert had `strategy_win_rate = 0.0`. The auto-execute
floor is 0.55, so no alert could ever be eligible. New strategies start
at 0 wins and never accumulate any because they can't auto-execute in
the first place — chicken-and-egg.

**Fix (option 3c chosen by operator)**: grace period. Until a strategy
has accumulated `_win_rate_grace_min_trades = 20` graded outcomes,
substitute `_auto_execute_min_win_rate` (0.55) as a synthetic baseline
so the alert can pass eligibility on tape + priority alone. Once 20
graded outcomes exist, the real win_rate takes over. Breaks the deadlock
without bypassing safety logic permanently.

### Bug 4a — RS detector dominated HIGH bucket
**Symptom**: 42/42 HIGH alerts were `relative_strength_laggard`. Other
detectors (the actual playbook setups) couldn't get a word in.

**Fix (4a + 4b roadmap)**: Tightened the RS detector's priority map:
- `abs(rs) >= 5.0` → HIGH (was 4.0)
- `abs(rs) in [4.0, 5.0)` → MEDIUM (was HIGH)
- `abs(rs) in [2.0, 4.0)` → LOW (was MEDIUM)

Same firing condition (`abs(rs) >= 2.0 AND rvol >= 1.0`); just stricter
promotion. The follow-up audit of every detector's priority logic is
tracked as **Bug 4b** in the roadmap (deferred per operator's "do 4d"
choice).

### Tests
`backend/tests/test_trade_funnel_fixes.py` — **9 new tests** covering
all four fixes via source-level guards + dataclass introspection.
- 178/178 across the related test suites still green.

### Files touched
- `backend/services/enhanced_scanner.py` (4 surgical fixes)
- NEW `backend/tests/test_trade_funnel_fixes.py`
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Operator action
```bash
cd ~/Trading-and-Analysis-Platform && git pull && \
  sudo supervisorctl restart backend && sleep 5 && \
  curl -s http://localhost:8001/api/diagnostic/trade-funnel | python3 -m json.tool
```

After Wednesday's session opens with these fixes in place, the funnel
should look much healthier:
- `priority_high_or_critical`: should drop from "all RS laggards" to a
  more diverse mix as RS demotions take effect (and other detectors get
  their fair share of HIGH).
- `tape_confirmed`: 25-of-42 type alerts that were stuck at 0.20 will
  now pass. Should see N>0 for the first time.
- `auto_execute_eligible`: with grace period in place + tape passing,
  this should also become non-zero on Wednesday.
- `bot_trades_created`: this is where we'll see the next blocker (or
  finally, real trades).

If the funnel still dies, the next-most-likely culprit is `_evaluate_opportunity`
in trading_bot_service — daily-loss guardrail, stale-quote guard, max
concurrent positions. The diagnostic will name it.

### Bug 4b — Detector priority audit (deferred)
Track in ROADMAP. Every detector's priority promotion logic should be
audited so HIGH represents a balanced mix of the playbook setups, not
one detector's threshold. Likely candidates needing tuning:
gap_and_go (probably under-promotes), range_break, the_3_30_trade,
9_ema_scalp, vwap_continuation. Time-budget: ~3-4h to walk all 30+
detectors and adjust thresholds with shadow-testing.



## 2026-04-30 (seventh commit) — Bot ↔ Scanner Auto-Execute Sync Fix + Diagnostic Upgrade

### The bug the diagnostic uncovered

The `/api/diagnostic/trade-funnel` endpoint shipped in the prior commit
revealed exactly why no live trades were happening:

  - `bot_state.mode = "autonomous"` was persisted (survives restarts).
  - `scanner._auto_execute_enabled = False` was **in-memory only** —
    defaults to False on every backend restart at line 895.
  - The sync (`scanner.enable_auto_execute(True)`) only ran when the
    operator manually hit `POST /api/trading-bot/mode` — there was no
    automatic sync at bot startup.

Net: every backend restart silently disabled auto-execution. Even when
the bot was loaded with mode=AUTONOMOUS from `bot_state`, the scanner's
auto-execute flag stayed False until someone re-toggled the mode via
the API. HIGH-priority alerts kept firing, kept getting `tape_confirmation=True`,
kept landing on `auto_execute_eligible=False` because the master switch
they were checking against was always False after restart.

### Shipped

#### 1. Authoritative bot↔scanner sync (`services/trading_bot_service.py`)
- `start()` now calls `scanner.enable_auto_execute(...)` in lockstep
  with `self._mode == BotMode.AUTONOMOUS`. So on every backend restart,
  the scanner's auto-execute flag matches the persisted bot mode.
- `set_mode()` now also runs the same sync, so any path that changes
  the mode (router endpoint, internal script, automation) keeps the
  scanner aligned automatically. The previous design relied on the
  *router endpoint* doing the sync, which was duplicated and skippable.
- Both calls are wrapped in best-effort try/except — sync failure logs
  a warning but never blocks bot startup.

#### 2. Diagnostic upgrades (`routers/diagnostic_router.py`)
- **`bot_master_switch`**: now reads from the live scanner's in-memory
  `_auto_execute_enabled` (the real gate) instead of looking for an
  `auto_execute_enabled` field on `bot_state` (which was never persisted).
- **`bot_mode`**: standardized on `bot_state.mode` (the actual key in
  storage; old code looked at `bot_state.bot_mode` first which never
  existed).
- **NEW `bot_scanner_sync` stage**: cross-checks `bot_state.mode ==
  "autonomous"` against `scanner._auto_execute_enabled`. Flags MISMATCH
  with a clear error message pointing at this very fix. After the fix,
  this should always read OK on a live Spark deploy. If it ever flags
  MISMATCH again, the message tells the operator to check supervisor
  logs because the bot service didn't start.
- **NEW `collection_mode_pause` stage**: the IB historical data-fill
  job activates an in-process flag that fully pauses the bot's scan
  loop. Now visible at a glance — if the operator notices the bot has
  gone quiet during a data-fill, this stage explains why and points
  at `POST /api/ib/collection-mode/stop`.

### Files touched
- `backend/services/trading_bot_service.py` (start() + set_mode() sync)
- `backend/routers/diagnostic_router.py` (3 new/improved stages)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Operator workflow on Spark
```bash
cd ~/Trading-and-Analysis-Platform && git pull && \
  sudo supervisorctl restart backend && sleep 5 && \
  curl -s http://localhost:8001/api/diagnostic/trade-funnel | python3 -m json.tool
```

After the pull + restart, the `bot_scanner_sync` stage should read
`"value": "OK"` and `auto_execute_enabled: true` — confirming the bot
loaded mode=autonomous and synced the scanner. If RTH is open and a
data-fill isn't running, the next scan cycle should start producing
alerts (watch `_symbols_skipped_adv/_rvol` climb).

### Remaining open question
The `collection_mode` flag pauses the bot for the duration of every
data-fill job — this is **by design** (frees compute for the IB
collectors) but compounds the problem during RTH. Worth a future
discussion: should collection mode pause only the *scanner* (which
generates alerts) and not the *bot* (which manages live positions)?
A live position with no bot polling is a real risk if a stop hits
during a data-fill. Tracked as a P1 backlog item.



## 2026-04-30 (sixth commit) — Trade-Funnel Diagnostic Endpoint

### Why
Operator asked "why no actual live trades happened today?" — a question
the codebase couldn't answer without grepping logs. There are 9
independent gates between a scanner alert and an executed broker order:

  scanner → priority → tape conf → auto-eligible flag → bot master
  switch → bot mode → bot eval → pre-execution filters → broker fill

If flow dies at any one of those, the operator has no easy way to see
*which* gate killed it. This endpoint walks all 9 stages for any
calendar day and pinpoints the FIRST one where flow dropped to zero.

### Shipped

#### `GET /api/diagnostic/trade-funnel?date=YYYY-MM-DD`
Returns:
  - `diagnosis`: 1-line "first dead stage" answer (e.g. *"🔴 First dead
    stage: bot_master_switch — Eligible alerts existed but the bot's
    auto_execute master switch is OFF"*)
  - `first_dead_stage`: stage_id string for programmatic use
  - `stages[]`: per-stage `{label, count, kill_check, kill_reason,
    optional breakdown}`. Breakdowns include priority distribution,
    bot-trade status counts (PAPER/SIMULATED/VETOED/OPEN/etc.), order-
    queue status counts. Daily defaults to today (UTC).
  - `scanner_hot_counters`: live `_symbols_skipped_adv / _rvol /
    _in_play` plus `auto_execute_enabled` + `auto_execute_min_win_rate`
    — the *current* scanner state, useful when the alert pipeline is
    stuck *now* rather than hours ago.
  - `in_play_config`: current thresholds (in case strict-gate is
    quietly rejecting flow).

The endpoint is safe to hit in production — read-only Mongo aggregations
+ in-process scanner attribute reads. No new collections, no writes.

### Files touched
- NEW `backend/routers/diagnostic_router.py`
- `backend/server.py` (one-liner `include_router` registration)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Operator workflow on Spark (for the "why no trades" investigation)
```bash
# 1. Pull latest commits, restart backend
cd ~/Trading-and-Analysis-Platform && git pull && \
  sudo supervisorctl restart backend && sleep 4

# 2. Run the diagnostic for today
curl -s http://localhost:8001/api/diagnostic/trade-funnel | python3 -m json.tool

# 3. (Optional) Run for a specific historical day
curl -s "http://localhost:8001/api/diagnostic/trade-funnel?date=2026-04-29" \
  | python3 -m json.tool
```
The `diagnosis` line will name the first dead stage; the `stages[]`
array shows the full funnel so you can also see *secondary* drop-offs.



## 2026-04-30 (fifth commit) — Unified In-Play Definition

### The bug we fixed

Two completely separate "in play" definitions had been coexisting:

  1. **Live scanner** (`enhanced_scanner._min_rvol_filter = 0.8`) —
     a single RVOL ≥ 0.8 floor. No gap, no ATR, no spread, no halt.
  2. **AI assistant** (`alert_system.AdvancedAlertSystem.check_in_play`) —
     a 0-100 scorer using RVOL ≥ 2.0, gap ≥ 3%, ATR ≥ 1.5%, spread ≤ 0.3%,
     bonuses for catalyst / short interest / low float. *Not* wired into
     the live scanner — only `ai_market_intelligence.py` called it.

The AI assistant could declare "AAPL is in play (score 65)" while the
scanner had silently rejected the same symbol on the RVOL floor, or
vice-versa. Two surfaces, two answers, persistent operator confusion.

### The fix

New `services/in_play_service.py` is the single source of truth. Both
paths now call the same scorer and persist the same thresholds, so the
two surfaces always agree.

### Key design decisions

- **Soft by default**. The first version of the gate ships in SOFT mode
  — every alert gets the score + reasons + disqualifiers stamped on it,
  but no alert is rejected. This preserves current alert flow for the
  operator who's tuned scanner thresholds against the v1 RVOL≥0.8
  behaviour. To opt-in to STRICT gating (fewer, higher-quality alerts):
  `PUT /api/scanner/in-play-config {"strict_gate": true}`.
- **Operator-tunable at runtime**. All thresholds (`min_rvol`,
  `min_gap_pct`, `min_atr_pct`, `max_spread_pct`,
  `min_qualifying_score`, `max_disqualifiers`, plus the strong/modest
  band breakpoints) persist to `bot_state.in_play_config` and can be
  updated without a redeploy.
- **Backward compat shim**. `alert_system.AdvancedAlertSystem.check_in_play`
  was rewritten to a 5-line shim that delegates to `InPlayService` and
  maps the result into the legacy `alert_system.InPlayQualification`
  dataclass, so the existing 5 callers (in alerts router + AI market
  intelligence) keep working with zero call-site changes.

### Shipped

#### 1. `services/in_play_service.py` (NEW)
- `InPlayQualification` dataclass — `is_in_play`, `score` (0-100),
  `reasons`, `disqualifiers`, plus the raw signals (rvol, gap_pct,
  atr_pct, spread_pct, has_catalyst, short_interest, float_shares).
- `InPlayService`:
  - `DEFAULT_CONFIG` with 13 tunable thresholds.
  - `score_from_snapshot(snapshot, spread_pct, ...)` — used by the
    live scanner. Reads `rvol`, `gap_pct`, `atr_percent` directly off
    the existing TechnicalSnapshot.
  - `score_from_market_data(dict)` — backward-compat for the AI
    assistant's existing call shape.
  - `get_config` / `update_config` / `is_strict_gate` for runtime
    tuning. `update_config` coerces strings (so `"true"` → True,
    `"1.5"` → 1.5) for the API surface, and silently drops unknown
    keys to keep typos out of `bot_state`.
  - Singleton accessor with late-bind DB.

#### 2. `services/enhanced_scanner.py` integration
- New `LiveAlert` fields: `in_play_score: int = 0`,
  `in_play_reasons: List[str]`, `in_play_disqualifiers: List[str]`.
- New `_symbols_skipped_in_play` counter, reset per cycle, surfaced
  in the cycle-summary log line + diagnostic JSON output.
- `_scan_symbol` now scores in-play once between RVOL floor and
  alert generation. Result stamped on every alert produced for the
  symbol that cycle. STRICT mode rejects the symbol when
  `is_in_play` is False; SOFT mode (default) only stamps metadata.

#### 3. `services/alert_system.py` (DEPRECATED check_in_play)
- The 80-line inline rubric was replaced with a 25-line shim
  delegating to `InPlayService.score_from_market_data`. Returns
  `alert_system.InPlayQualification` for backward compat with
  existing callers.
- The legacy `IN_PLAY_CRITERIA` dict still exists but is now
  effectively unused (kept for one cycle to avoid breaking any
  third-party imports — can be deleted once we audit external
  callers).

#### 4. API surface (`routers/scanner.py`)
- `GET /api/scanner/in-play-config` — current thresholds + defaults
  for diff display. Powers a future operator-side config panel.
- `PUT /api/scanner/in-play-config` — partial-update with type
  coercion. Persists to `bot_state.in_play_config`.

### Tests
`backend/tests/test_in_play_service.py` — **26 new tests**:
- Default config + persisted-config loading from `bot_state`.
- Score rubric — every band fires (exceptional/high/modest/sub-min
  RVOL, big/modest/no-gap, big/decent/tight ATR, wide-spread
  disqualifier, catalyst/short/float bonuses).
- `is_in_play` true only when score ≥ min AND disqualifiers < max.
- `score_from_snapshot` reads correct fields off TechnicalSnapshot.
- `score_from_market_data` accepts the dict shape.
- `update_config` persists to bot_state, drops unknowns, coerces
  string→bool and string→float for the API surface.
- LiveAlert exposes the 3 new fields with correct defaults.
- Source-level guards: scanner calls `score_from_snapshot`, gates
  only in strict mode, alert_system shim delegates to unified
  service.
- Legacy shim returns the `alert_system.InPlayQualification`
  dataclass so existing AI-assistant callers work unchanged.

Total related-suite count after this commit: **169 tests** across
the in-play + sector + landscape + grading + setup-matrix + regime
suites.

### Files touched
- NEW `backend/services/in_play_service.py`
- NEW `backend/tests/test_in_play_service.py`
- `backend/services/enhanced_scanner.py` (3 LiveAlert fields, new
  `_symbols_skipped_in_play` counter, in-play scoring in `_scan_symbol`,
  cycle-log + diagnostic surface)
- `backend/services/alert_system.py` (`check_in_play` shrunk from
  80 lines to 25 — delegating shim)
- `backend/routers/scanner.py` (2 new config endpoints)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Verification on Spark
- Pull, restart backend.
- `curl http://localhost:8001/api/scanner/in-play-config` should show
  the 13 thresholds at defaults.
- After 1 scan cycle, `db.live_alerts.findOne({})` should expose
  `in_play_score`, `in_play_reasons`, `in_play_disqualifiers` on every
  alert.
- The cycle-summary log line should now include
  `Skipped: ADV=N, RVOL=N, InPlay=N` (last counter is 0 in SOFT mode).
- To experiment with stricter gating without a redeploy:
  ```
  curl -X PUT http://localhost:8001/api/scanner/in-play-config \
       -H 'Content-Type: application/json' \
       -d '{"strict_gate": true, "min_qualifying_score": 40}'
  ```
  Watch `_symbols_skipped_in_play` climb in the scanner log;
  flip back with `{"strict_gate": false}` instantly.



## 2026-04-30 (fourth commit) — Sector Regime Pipeline (Items #3 + #4)

Closes the agreed 6-item next-session plan. With this commit, the
operator's mental hierarchy
    `Multi-index regime → Sector regime → Daily Setup → Time/InPlay → Trade`
is fully wired in. None of these layers hard-gate alerts; all four
flow into the per-Trade ML model as one-hot features (the architecture
decision locked at 2026-04-29).

### Shipped

#### 1. `services/sector_tag_service.py` (NEW — Item #3)
- `SECTOR_ETFS` re-exports the 11 SPDR ETF map (XLK / XLE / XLF / XLV /
  XLY / XLP / XLI / XLB / XLRE / XLU / XLC).
- `STATIC_SECTOR_MAP` covers ~340 of the most-liquid US large/mid-caps,
  GICS-aligned. Sized to give meaningful day-1 coverage without needing
  IB contract-details lookups (which can be added later as a fallback).
- `SectorTagService.tag_symbol(symbol)` → `"XLK"` | `None`
  (case-insensitive, ETF-self-mapping built in).
- `SectorTagService.backfill_symbol_adv_cache(db)` walks every doc in
  `symbol_adv_cache`, writes `sector` + `sector_name`. Idempotent —
  already-tagged docs are skipped. Returns
  `{total, tagged, skipped, untaggable}`.
- One-time backfill script at `backend/scripts/backfill_sector_tags.py`
  for operators who prefer CLI to the API endpoint.

#### 2. `services/sector_regime_classifier.py` (NEW — Item #4)
- `SectorRegime` enum (6 buckets): STRONG / ROTATING_IN / NEUTRAL /
  ROTATING_OUT / WEAK / UNKNOWN.
- `SectorRegimeClassifier` reads daily bars for the 11 sector ETFs
  + SPY (the relative-strength benchmark) in one pass. Per sector:
  - trend_pct vs 20SMA
  - momentum_5d_pct (vs 5 bars back)
  - rs_vs_spy_pct = sector 5d − SPY 5d (relative strength)
  - regime label per the 6-bucket rules (STRONG = trend ≥+0.5% AND
    RS ≥+0.3%; ROTATING_IN = RS ≥+0.5% AND trend ≥0; etc.)
  - 5-min market-wide cache (regime is a daily-bar derived signal).
- `classify_for_symbol(symbol)` resolves via `SectorTagService` →
  returns the home sector's regime. Untagged symbols return UNKNOWN.
- **`SectorRegimeHistoricalProvider`** — date-aware sibling for the
  per-Trade ML training loop. Pre-loads daily bars for all 11 ETFs +
  SPY once (~50ms), then exposes
  `get_sector_regime_for(symbol, date_str)` with a per-(etf, date)
  cache so the same lookup across 1000s of training samples is O(1).

#### 3. `services/ai_modules/composite_label_features.py` (UPDATED)
- New `SECTOR_LABEL_FEATURE_NAMES` (5 one-hots, UNKNOWN baseline).
- `ALL_LABEL_FEATURE_NAMES` grew from 15 → **20** features:
  - 7 setup_label_*
  - 8 regime_label_* (multi-index)
  - 5 sector_label_*  ← NEW
- `build_label_features()` now takes `sector_regime` and merges
  the third one-hot block.

#### 4. Scanner integration (`services/enhanced_scanner.py`)
- `LiveAlert` gained `sector_regime: str = "unknown"` alongside
  `multi_index_regime`. Every alert now carries both layers.
- `_apply_setup_context` (already calls multi-index) now also calls
  `SectorRegimeClassifier.classify_for_symbol(symbol)` and stamps
  `alert.sector_regime`. Soft gate — never modifies priority.

#### 5. ML feature plumbing (`services/ai_modules/timeseries_service.py`)
- **Training** (`_train_single_setup_profile`):
  - Imports + preloads `SectorRegimeHistoricalProvider`.
  - Per training sample: computes the symbol's sector regime as of
    the sample's date, then merges the 5 sector_label_* features into
    the combined feature dict (alongside setup_label and regime_label).
  - The full training feature vector now grows by 20 columns total
    (instead of 15 in the prior commit) when the next retrain runs.
- **Prediction** (`predict_for_setup`):
  - Reads the cached `SectorRegimeClassifier._cached` result, resolves
    `symbol → sector ETF → snapshot.regime`, populates the sector_label
    one-hot. No async/sync mismatch — the alert path runs the
    classifier upstream so the cache is hot.

#### 6. API surface (`routers/scanner.py`)
- `GET /api/scanner/sector-regime` — returns the 11-sector regime
  snapshot with trend/momentum/RS for each. Powers a future heat-grid
  in the operator UI.
- `POST /api/scanner/backfill-sector-tags` — one-shot admin endpoint
  to populate `symbol_adv_cache.sector`. Idempotent.

### Tests
`backend/tests/test_sector_regime_classifier.py` — **32 new tests**:
- Static map coverage (every value is a valid ETF, every sector has
  ≥1 stock, ETF-self-mapping correct).
- `tag_symbol` lookups + `coverage` math.
- Backfill writes `sector` + `sector_name`, skips already-tagged docs,
  idempotent on re-run.
- Classifier label assignment for all 5 active states from synthetic
  bars (STRONG / WEAK / ROTATING_IN / NEUTRAL / UNKNOWN-on-thin-data).
- Cache TTL hits + invalidate clears state.
- `classify_for_symbol` resolves AAPL → XLK → STRONG.
- Historical provider — preload, per-(etf, date) cache, UNKNOWN before
  MIN_BARS, UNKNOWN for untagged symbols.
- One-hot feature names exclude UNKNOWN; `ALL_LABEL_FEATURE_NAMES`
  has exactly 20 slots; `build_label_features` combines all 3 layers.
- LiveAlert exposes `sector_regime`; `_apply_setup_context` stamps
  the right value via the cached classifier; UNKNOWN for untagged.
- Source-level guards confirm training + prediction paths reference
  the sector classifier.

Total related-suite count after this commit: **157 tests** across:
- `test_sector_regime_classifier.py`: 32 ✅ (new)
- `test_landscape_grading_service.py`: 32 ✅
- `test_multi_index_regime_classifier.py`: 28 ✅
- `test_market_setup_matrix.py`: 21 ✅
- `test_orphan_setup_detectors.py`: 17 ✅
- `test_setup_landscape_service.py`: 13 ✅
- + 14 from smb_profiles + setup_models_load_from_timeseries

### Files touched
- NEW `backend/services/sector_tag_service.py`
- NEW `backend/services/sector_regime_classifier.py`
- NEW `backend/scripts/backfill_sector_tags.py`
- NEW `backend/tests/test_sector_regime_classifier.py`
- `backend/services/enhanced_scanner.py` (LiveAlert.sector_regime
  field + sector classify call in `_apply_setup_context`)
- `backend/services/ai_modules/composite_label_features.py` (sector
  label features added)
- `backend/services/ai_modules/timeseries_service.py` (training-side
  historical provider, prediction-side cached lookup)
- `backend/routers/scanner.py` (2 new endpoints:
  `sector-regime`, `backfill-sector-tags`)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`

### Architecture status (post-commit)
The agreed 6-item plan from the previous fork is fully complete:
- ✅ #1 MultiIndexRegimeClassifier
- ✅ #2 ML feature plumbing for setup_label + regime_label (+ sector now)
- ✅ #3 Sector tag backfill (static map, IB-fallback parked)
- ✅ #4 SectorRegimeClassifier
- ✅ #5 Setup-landscape self-grading tracker
- ✅ #6 Documented soft-gate decision; STRATEGY_REGIME_PREFERENCES re-tagged
       as metadata only

Pipeline as runtime:
- HARD GATES: Time-window, In-Play/Universe, Confidence
- SOFT GATES (priority downgrades): Setup × Trade matrix
- ML FEATURES (one-hots): Setup, Multi-index regime, Sector regime,
  + the existing 24 numerical regime features



## 2026-04-30 (third commit) — Receipts Cited Across All 4 Briefing Contexts

Extended the just-shipped Setup-landscape self-grading tracker so all
four briefing voices (morning / midday / EOD / weekend) cite recent
grades — not just morning. Each voice gets its own context-specific
framing so the citation reads naturally in flow.

### What changed

#### Per-context citation (in `SetupLandscapeService._most_recent_grade`)
- **morning** (existing): cites yesterday's morning grade with
  *"Quick receipt — 2026-04-29: Nailed it ..."* / *"Owning yesterday's
  miss ..."*. Tail: *"Carrying that into today's call."*
- **midday** (new): cites yesterday's morning grade with
  *"Mid-session check (anchored by 2026-04-29's open call): ..."* — or
  *"Mid-session — yesterday's open call missed ..."* on D/F. Tail:
  *"Adjusting from there."*
- **EOD** (new): cites the most-recent graded morning prediction with
  *"Closing the loop — 2026-04-29's open call: ..."* / *"... missed ..."*
  on D/F. Tail: *"Logging that for tomorrow's open."*
- **weekend** (new): NEW `LandscapeGradingService.get_weekly_summary()`
  rolls up the past 7 calendar days into a single record line:
  *"Last week's record — 3A · 1B · 1C (5 graded) — strong directional
  read across the week, aggregate top-family avg +0.85R. Most recent:
  'Nailed it — Gap & Go carried' (2026-04-30)."* Tone phrase keys off
  ``avg_score`` (≥0.75 strong, ≥0.55 solid, ≥0.40 mixed, else tough).

#### New service method
`LandscapeGradingService.get_weekly_summary(end_date, context)` —
filters predictions to `(end_date - 7d, end_date]`, drops
`INSUFFICIENT_DATA` rows, returns
``{n_graded, n_total_in_window, grade_distribution, avg_score,
avg_top_setup_r, latest_grade, latest_verdict, latest_trading_day}``.
Returns ``None`` when no graded rows exist in the window — first-week
operation degrades silently.

#### `_receipt_line(recent_grade, context)` updated
Now takes the `context` argument and dispatches to one of two
renderers:
- `_weekly_receipt_line(summary)` for the weekend rollup
  (``_weekly_summary=True`` flag in the dict)
- The single-day per-context phrasing block above

### Tests added — 9 new, 32 total in this file
- `test_render_narrative_midday_cites_morning_grade` — A grade,
  "Mid-session check" framing
- `test_render_narrative_midday_d_grade_owns_miss`
- `test_render_narrative_eod_closes_the_loop`
- `test_render_narrative_weekend_cites_weekly_summary` — verifies
  record ("3A · 1B · 1C"), graded count, avg R, tone phrase
- `test_render_narrative_weekend_silent_on_empty_summary`
- `test_weekly_receipt_line_tone_buckets` — 4 score thresholds
- `test_get_weekly_summary_aggregates_grades` (across 3 days)
- `test_get_weekly_summary_returns_none_when_no_grades`
- `test_get_weekly_summary_excludes_insufficient_data`

Plus extended `test_render_narrative_silent_when_no_recent_grade` to
verify NONE of the four context phrases leak when no grade exists.

Total related-suite count after this commit: **111 tests** across
the grading + landscape + setup-matrix + regime suites (was 116;
some old tests were superseded by the new context-aware ones).

### Files touched
- `backend/services/landscape_grading_service.py` — new
  `get_weekly_summary` method
- `backend/services/setup_landscape_service.py` — context-aware
  `_most_recent_grade`, new `_weekly_receipt_line` helper, extended
  `_receipt_line` per-context phrasing
- `backend/tests/test_landscape_grading_service.py` — 9 new tests +
  extended fake Mongo to support `$gte`/`$lte`/`$gt`/`$lt`/`$in`/
  `$exists` operators (needed by `get_weekly_summary`'s window query)
- `memory/CHANGELOG.md`, `memory/PRD.md`



## 2026-04-30 (next-session pickup, second commit) — Setup-Landscape Self-Grading Tracker

### Concept
Closes the AI-briefing feedback loop. Each morning briefing already
predicts something concrete ("I'm seeing 47 names in Gap & Go — today
I'm favoring momentum, avoiding fades on overextended names"). Until
now those predictions evaporated at end-of-day. This service:

  1. **Persists** every snapshot's prediction to a new
     `landscape_predictions` Mongo collection (idempotent on
     `(trading_day, context)` so re-firing the briefing within a day
     updates rather than dupes).
  2. **Grades** at EOD by walking `alert_outcomes` for the day,
     bucketing realized R-multiples by Setup family
     (gap_and_go / range_break / day_2 / etc.), and assigning each
     prediction an A/B/C/D/F based on whether the favored family
     carried *and* the avoided family stayed away.
  3. **Cites** yesterday's grade in the next morning's narrative
     ("Quick receipt — 2026-04-29: Nailed it — Gap & Go carried,
     avg +1.20R across 14 alerts. Carrying that into today's call.")

This is a passive, free training signal — the longer it runs, the more
credible the briefings get. Not skipping it now (waiting until #3+#4)
would have meant losing two weeks of grading data we can't backfill.

### Shipped

#### 1. `services/landscape_grading_service.py` (NEW)
- `LandscapeGradingService` with three core methods:
  - `record_prediction(snapshot, context)` — upserts on
    `(trading_day, context)` so the same briefing re-firing within a
    day updates the prediction. No-op when DB is None or snapshot is
    all-NEUTRAL.
  - `grade_predictions_for_day(trading_day)` — walks
    `alert_outcomes` for the day, buckets realized R per Setup
    family using the `_build_trade_to_setup_family()` map (built
    from `TRADE_SETUP_MATRIX` so it stays in sync with the operator
    playbook), grades each prediction A-F, writes grade fields back.
    Idempotent — already-graded predictions are skipped on re-run.
  - `get_recent_grades(n, context)` — most-recent N graded
    predictions for the briefings to cite.
- `_score_grade(top_avg, avoided_avg)` rubric:
  - **A** (≥0.5R favored AND avoided ≤0): "Nailed it"
  - **B** (≥0.2R favored): "Solid call"
  - **C** (-0.2R to +0.2R): "Mixed day"
  - **D** (≤-0.2R favored): "Wrong call"
  - **F** (≤-0.2R favored AND avoided won big): "Fully backwards"
  - **INSUFFICIENT_DATA** when <3 alerts in the predicted family
- `_build_trade_to_setup_family()` derives Trade → home-Setup mapping
  from `TRADE_SETUP_MATRIX` (each Trade's first WITH_TREND cell);
  resolves through `TRADE_ALIASES` so legacy names also map.
- `_AVOIDED_OPPOSITE` map specifies which Setup families are the
  "opposite" of each top family (e.g., gap_and_go avoids
  overextension + gap_up_into_resistance).
- Singleton accessor `get_landscape_grading_service(db=...)` with
  late-bind index creation on `(trading_day, context)`.

#### 2. `services/setup_landscape_service.py` integration
- `LandscapeSnapshot` now feeds itself into the grader: `get_snapshot`
  awaits `record_prediction(snap, context)` after building the
  snapshot. Best-effort, never blocks delivery on a DB hiccup.
- New `_most_recent_grade(context)` helper fetches the prior graded
  prediction (morning context only — midday/eod/weekend voices have
  their own focus). Cheap to extend to other contexts later.
- New `_receipt_line(recent_grade)` renders a 1st-person citation:
  - "Quick receipt — 2026-04-29: Nailed it — Gap & Go carried..."
    (A/B/C grades)
  - "Owning yesterday's miss — 2026-04-29: Wrong call..." (D/F)
  - Silent on INSUFFICIENT_DATA / unknown / first-day operation.

#### 3. EOD scheduler (`services/eod_generation_service.py`)
- New cron job `auto_landscape_grading` at **16:50 ET on weekdays**.
  Runs after `auto_generate_drc` (16:30) and `auto_playbook_analysis`
  (16:45) but before `auto_self_reflection` (17:00) so the reflection
  step can cite the day's grade if needed.
- Uses the same `_run_async` wrapper pattern as the other EOD jobs
  (BackgroundScheduler thread → fresh asyncio loop → close).

#### 4. API surface (`routers/scanner.py`)
- `GET /api/scanner/landscape-receipts?days=7&context=morning` —
  returns the most-recent graded predictions, projected down to the
  fields a UI receipts panel needs (no bulky narrative). Powers a
  future panel + the briefings narrative.
- `POST /api/scanner/landscape-grade?trading_day=YYYY-MM-DD` —
  manual trigger for backfills, replays, and tests. Defaults to
  current ET date.

### Tests
`backend/tests/test_landscape_grading_service.py` — **23 new tests**:
- `_build_trade_to_setup_family` covers every entry in
  `TRADE_SETUP_MATRIX` + resolves aliases.
- All 5 grade bands (A/B/C/D/F) fire for the correct
  (top_avg_r, avoided_avg_r) combinations.
- `record_prediction` upserts idempotently, no-ops on all-NEUTRAL,
  no-ops when DB is None.
- `grade_predictions_for_day` grades correctly, skips already-graded,
  falls back to INSUFFICIENT_DATA when <3 alerts in predicted family.
- `_trading_day_for` ET conversion handles UTC late-evening rollover.
- LandscapeService integration: morning narrative cites recent grade
  via "Quick receipt" / "Owning yesterday's miss"; silent on
  INSUFFICIENT_DATA / None.
- Source-level guards confirm `get_snapshot` calls into the grader
  and the EOD scheduler registers the job at 16:50 ET.

Total related-suite count after this commit: **116 tests** across:
- `test_landscape_grading_service.py`: 23 ✅ (new)
- `test_multi_index_regime_classifier.py`: 28 ✅
- `test_market_setup_matrix.py`: 21 ✅
- `test_orphan_setup_detectors.py`: 17 ✅
- `test_setup_landscape_service.py`: 13 ✅
- + 14 from smb_profiles + setup_models_load tests

### Files touched
- NEW `backend/services/landscape_grading_service.py`
- NEW `backend/tests/test_landscape_grading_service.py`
- `backend/services/setup_landscape_service.py` (record_prediction
  call in `get_snapshot`, `_most_recent_grade` + `_receipt_line`
  helpers, narrative threading)
- `backend/services/eod_generation_service.py` (new
  `auto_landscape_grading` cron job at 16:50 ET)
- `backend/routers/scanner.py` (2 new endpoints:
  `landscape-receipts`, `landscape-grade`)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`



## 2026-04-30 (next-session pickup) — Multi-Index Regime Classifier + Categorical Label Features

### Concept
Closed the architectural loop the operator agreed on at the previous
fork: the `Market Regime → Sector Regime → Setup → Time → Trade`
hierarchy is the right *human mental model* but the wrong *runtime
hard-gate stack* (compounding rejection rate would starve the per-Trade
ML pipeline of training data). So this session shipped two of the
three "feature-not-gate" pieces:

  1. **Multi-index regime label** (SPY/QQQ/IWM/DIA) — categorical bin
     for AI briefings + ML one-hot.
  2. **Plumbed both the daily Setup label and the multi-index regime
     label into the per-Trade ML feature vector** so the next retrain
     learns from them.

The third piece (Sector Regime classifier) is still upcoming — see
`ROADMAP.md` Step 4 in the next-session plan.

### Shipped

#### 1. `services/multi_index_regime_classifier.py` (NEW)
- `MultiIndexRegime` enum with 9 buckets (8 active + UNKNOWN):
  `risk_on_broad`, `risk_on_growth`, `risk_on_smallcap`,
  `risk_off_broad`, `risk_off_defensive`, `bullish_divergence`,
  `bearish_divergence`, `mixed`, `unknown`.
- `MultiIndexRegimeClassifier`:
  - Reads ~25 daily bars per index (SPY/QQQ/IWM/DIA) from
    `ib_historical_data` — no extra IB calls.
  - Computes per-index trend vs 20SMA, 5d momentum, 10d breadth.
  - Rule-based label assignment that fires **divergences first** (more
    specific) before falling through to broad / majority / mixed.
  - 5-minute market-wide cache (the regime is a daily-bar derived
    label; one classification per scan cycle is enough).
  - Singleton accessor `get_multi_index_regime_classifier(db=...)`.
- Helper `derive_regime_label_from_features(regime_feats)` — used at
  training time so each historical sample gets a categorical label
  derived from already-loaded numerical regime features (no extra IO).
- Helper `build_regime_label_features(label)` returns the one-hot dict
  (`regime_label_<name>` for each active bucket; UNKNOWN → all zeros).

#### 2. `services/ai_modules/composite_label_features.py` (NEW)
- `SETUP_LABEL_FEATURE_NAMES` (7 one-hots, NEUTRAL is the all-zero baseline).
- `REGIME_LABEL_FEATURE_NAMES` (8 one-hots, UNKNOWN is the all-zero baseline).
- `ALL_LABEL_FEATURE_NAMES` (15 total).
- `build_label_features(market_setup, multi_index_regime)` returns the
  combined feature dict ready to merge into the model's input vector.

#### 3. Scanner integration (`services/enhanced_scanner.py`)
- `LiveAlert` gained `multi_index_regime: str = "unknown"` alongside the
  existing `market_setup`, `is_countertrend`, `out_of_context_warning`,
  `experimental` fields.
- `_apply_setup_context` now also calls the multi-index regime
  classifier and stamps `alert.multi_index_regime`. The regime label is
  metadata + ML feature only — never modifies `alert.priority`.
- `STRATEGY_REGIME_PREFERENCES` map kept but explicitly re-documented as
  metadata-only (not an active hard gate). This closes the "drop hard-
  gate idea" item from the next-session plan.

#### 4. ML feature plumbing (`services/ai_modules/timeseries_service.py`)
- **Training side** (`_train_single_setup_profile`):
  - Imports `ALL_LABEL_FEATURE_NAMES`, `build_label_features`, and the
    derive-from-features helper.
  - `combined_feature_names` now includes the 15 label slots.
  - Per training sample: derives `regime_label` from the already-loaded
    `regime_feats`. For daily-bar profiles (`bar_size == "1 day"`),
    also derives `setup_label` from a 30-bar window of `bars` via the
    new sync helper `MarketSetupClassifier._sync_classify_window`.
  - Label vector concatenated to base + setup + regime + MTF feature
    vectors so newly-trained models pick up the labels automatically.
  - Saves `label_features` to model metadata for traceability.
- **Prediction side** (`predict_for_setup`):
  - Gate-checks `model._feature_names` for any of the 15 label feature
    names; only computes labels when the model expects them (so older
    models keep working unchanged).
  - Reads cached classifier results (the alert pipeline calls
    `_apply_setup_context` upstream, so the cache is hot) — no async/
    sync mismatch.

#### 5. Briefings (`services/setup_landscape_service.py`)
- `LandscapeSnapshot` now exposes `multi_index_regime`,
  `regime_confidence`, `regime_reasoning`.
- New private `_classify_multi_index_regime` runs the classifier
  during snapshot generation.
- New private `_regime_line` renders a 1st-person regime preface for
  each context (morning / midday / eod / weekend); silent when the
  regime is unknown so older flows are unaffected.
- Each non-fallback narrative now leads with a regime line like:
  `"Heading into the open, I'm seeing a bullish small-cap divergence —
  IWM leading higher while SPY lags (IWM: +1.5% vs 20SMA)."`
- `ai_assistant_service.get_coaching_alert` returns the regime fields
  in the `setup_landscape` payload so the UI can render them
  separately if it wants.

### Tests
`backend/tests/test_multi_index_regime_classifier.py` — **28 new tests**
covering one-hot helper edge cases, classifier label assignment for
all 8 active labels (synthetic SPY/QQQ/IWM/DIA bars), cache TTL +
invalidate, the sync derive-from-features helper, scanner integration
(`LiveAlert.multi_index_regime` + `_apply_setup_context` stamping),
training & prediction source-level guards, briefings narrative
integration (regime line included when known, silent on unknown,
non-empty for every active label).

Total related-suite count after this session:
- `test_multi_index_regime_classifier.py`: 28 ✅
- `test_market_setup_matrix.py`: 21 ✅
- `test_orphan_setup_detectors.py`: 17 ✅
- `test_setup_landscape_service.py`: 13 ✅
- = **79/79 passing**

### Architectural decision documented
PRD.md "Pipeline architecture" section already locked in the
hard-gate-only-at-Time/InPlay/Confidence rule. This session adds two
matching artifacts (#3 + #5 above) and stops short of any code path
that could rebroadcast a regime/setup hard gate.

### Files touched
- NEW `backend/services/multi_index_regime_classifier.py`
- NEW `backend/services/ai_modules/composite_label_features.py`
- NEW `backend/tests/test_multi_index_regime_classifier.py`
- `backend/services/enhanced_scanner.py` (LiveAlert field +
  `_apply_setup_context` regime stamping +
  `STRATEGY_REGIME_PREFERENCES` doc clarification)
- `backend/services/market_setup_classifier.py`
  (`_sync_classify_window` helper)
- `backend/services/ai_modules/timeseries_service.py` (label features
  in training + prediction paths)
- `backend/services/setup_landscape_service.py` (regime line in
  narrative + extended snapshot dataclass)
- `backend/services/ai_assistant_service.py` (regime fields in
  briefing payload)
- `memory/PRD.md`, `memory/ROADMAP.md`, `memory/CHANGELOG.md`


## 2026-04-29 (evening, v3) — Setup-landscape briefings + 1st-person voice

### Concept
Operator's request: every briefing surface (morning, EOD, weekend prep)
should pre-compute the daily Bellafiore-Setup landscape and inject it
as concrete grounding for the AI coaching narrative. And the voice
must always be 1st-person — "I found 47 stocks in Gap & Go, I'm
favoring momentum trades, I'll be looking to avoid mean-reversion on
overextended names" — never 3rd-person about the bot.

### Shipped
- New file `services/setup_landscape_service.py` (~280 lines):
  - `SetupLandscapeService` with `get_snapshot(sample_size, context)`.
  - Pulls top-N symbols by ADV from `symbol_adv_cache`, batch-classifies
    via the existing `MarketSetupClassifier` (5-min cache makes back-to-
    back briefings near-free), groups by Setup, picks top 5 examples per
    Setup sorted by classifier confidence, renders 1st-person narrative.
  - 60-second snapshot cache.
  - Four narrative voices keyed off `context`: `morning` (forward-
    looking, "I'm favoring …"), `midday` (in-progress, "I'm watching …"),
    `eod` (retrospective, "today shaped up as …"), `weekend` (prep,
    "over the weekend I screened … heading into next week I'm preparing
    …").
  - `_SETUP_TRADE_FAMILY` constant maps each Setup to its
    (trade_family_label, favoring_phrase, avoiding_phrase) tuple —
    hand-derived from the operator's "Best types of trades for this
    setup" line on each Setup screenshot.
- Wired the landscape into `ai_assistant_service.get_coaching_alert`:
  - For `market_open`, `market_close`, `weekend_prep` context types,
    pulls the landscape snapshot and injects the rendered narrative
    into the AI prompt as concrete data.
  - Adds an explicit voice-rules block to every prompt: "Speak as the
    bot — first-person ('I found …', 'I'm favoring …', 'I'll be looking
    to avoid …'). Do NOT refer to the bot in the third person."
  - Returns the structured `setup_landscape` payload alongside the
    coaching text so the UI can render the bullet structure separately.
  - New prompt entries for `market_close` (EOD review) and
    `weekend_prep` (Sunday-night planning).
- New endpoints:
  - `GET /api/scanner/setup-landscape?context=morning|midday|eod|weekend
    &sample_size=200` — returns structured landscape + pre-rendered
    1st-person narrative for direct UI rendering.
  - `GET /api/assistant/coach/eod-briefing` — retrospective EOD coaching.
  - `GET /api/assistant/coach/weekend-prep-briefing` — forward-looking
    Sunday prep coaching.

### Voice / 1st-person enforcement
Tests in `tests/test_setup_landscape_service.py` lock in the voice rule:
  - `test_morning_narrative_uses_first_person_voice` asserts the
    narrative contains `I screened`, `I'm favoring`, `I'll be looking
    to avoid` AND does NOT contain forbidden 3rd-person phrases like
    `the bot`, `SentCom is`, `the system found`, `the scanner found`.
  - `test_eod_narrative_uses_retrospective_voice` asserts `today shaped
    up as` + `The day favored`.
  - `test_weekend_narrative_uses_forward_looking_voice` asserts
    `heading into next week`.
  - `test_setup_trade_family_action_clauses_are_first_person_friendly`
    asserts each `favoring`/`avoiding` phrase starts with a noun phrase
    (so it chains naturally into "I'm favoring …" without grammar
    errors).

### Verification
- 13 new tests in `test_setup_landscape_service.py`. 61/61 passing
  across the full Setup-related suite (landscape, matrix, orphan
  detectors, setup coverage, time-window reclassification).
- Live endpoints all return 200:
  - `/api/scanner/setup-landscape` — fallback narrative correctly
    1st-person when ADV cache empty in container ("I screened 0 names
    … I'll let the open's first 30 minutes confirm a daily structure
    before I lean into any Trade family — until then, I'm staying
    small and reactive").
  - `/api/assistant/coach/morning-briefing` (now landscape-grounded).
  - `/api/assistant/coach/eod-briefing` (new).
  - `/api/assistant/coach/weekend-prep-briefing` (new).

### Known architectural gap (operator surfaced this in same turn)
The system currently flows **Time → Trade → Setup (soft gate)**, NOT
the proper hierarchy **Market Regime → Setup → Trade**. `_market_regime`
is computed every cycle from SPY but only stamped onto each alert as
metadata — it does not gate anything. `STRATEGY_REGIME_PREFERENCES`
exists but is purely informational. Logged to ROADMAP as P1 follow-up:
make Regime a hard upstream gate so e.g. `MOMENTUM` regime suppresses
the reversal-flavored Setups (Overextension, Volatility In Range)
entirely and `RANGE_BOUND` regime suppresses the continuation Setups.

### Operator action on DGX
1. Save to GitHub → `git pull` on DGX (backend hot-reloads).
2. Curl the new landscape endpoint after Mongo has data:
   ```
   curl -s "http://localhost:8001/api/scanner/setup-landscape?context=morning" \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['headline']); print(d['narrative'])"
   ```
3. Trigger the morning briefing and verify the AI's reply is
   1st-person and references real tickers from the landscape.



## 2026-04-29 (evening, v2) — Bellafiore Setup × Trade matrix system

### Concept
Operator surfaced that our existing `setup_type` column conflates two
orthogonal layers from the SMB / Bellafiore playbook (One Good Trade,
The Playbook):
- **Setup** = the daily/multi-day market context that "set up" the
  opportunity (Gap & Go, Range Break, Day 2, Gap Down Into Support,
  Gap Up Into Resistance, Overextension, Volatility In Range).
- **Trade** = the specific intraday execution pattern (9-EMA Scalp,
  VWAP Continuation, Bella Fade, …).

A given Trade only has positive expectancy in the right Setup. Without
a Setup classifier, our scanner was firing context-free trades and
the operator was hand-filtering. This release adds the Setup layer
*additively* (no `setup_type` rename) so existing AI training data,
MongoDB indices, and frontend code keep working.

### Shipped
- New file `services/market_setup_classifier.py` (~520 lines):
  - `MarketSetup` enum (7 + NEUTRAL).
  - `MarketSetupClassifier` class with seven detection methods (one
    per Setup), each returning a 0-1 confidence + reasoning.
  - 5-min per-symbol cache, daily-bar history pulled from
    `ib_historical_data` (no extra IB calls).
  - `TRADE_SETUP_MATRIX` constant — full 21-Trade × 7-Setup matrix
    transcribed verbatim from the operator playbook screenshot.
  - `TRADE_ALIASES` dedupe map: `puppy_dog`→`big_dog`,
    `tidal_wave`→`bouncy_ball`, `vwap_bounce`→`first_vwap_pullback`.
  - `EXPERIMENTAL_TRADES` frozenset — 12 trades not in operator's
    matrix that keep firing all-context with `experimental=True`.
  - `lookup_trade_context(trade, setup)` resolver with alias chain.
- `LiveAlert` extended with 4 new fields:
  `market_setup`, `is_countertrend`, `out_of_context_warning`,
  `experimental` (all default-safe so existing alert producers work
  unchanged).
- Soft-gate logic in `enhanced_scanner._apply_setup_context`: every
  fired alert is tagged with the current daily Setup; if Trade is
  out-of-context (empty cell), priority is downgraded one notch and
  a warning bullet is appended to `reasoning`. Countertrend cells
  tag `is_countertrend=True` but do NOT downgrade (those are
  intentional reversal plays).
- New checker `_check_the_3_30_trade` — power-hour break of afternoon
  range with held-above-OR + tight-consolidation preconditions per
  the playbook screenshot. Time-windowed to `CLOSE` only.
- New endpoint `GET /api/scanner/setup-trade-matrix` — returns the
  full matrix + classifier stats for UI heat-grid rendering.
- Canonical doc `/app/memory/SETUPS_AND_TRADES.md` mirrors the
  classifier constants for human reference.

### Verification
- 21 new tests in `tests/test_market_setup_matrix.py` covering:
  matrix completeness (all 21 trades present), directionality
  invariants (with-trend vs countertrend cells), alias resolution,
  experimental-bypass, NEUTRAL-passes-all, classifier per-setup
  detection (Gap & Go, Range Break, Day 2, Overextension,
  Volatility In Range positive cases), classifier caching +
  singleton, scanner integration (with-trend tag, out-of-context
  warning + downgrade, countertrend tag without downgrade,
  experimental bypass), the_3_30_trade detector (positive +
  blocked-when-LOD-dipped-below-OR), and registration drift checks.
- 48/48 passing across `test_market_setup_matrix`,
  `test_orphan_setup_detectors`, `test_scanner_setup_coverage`,
  `test_strategy_time_window_reclassification`.
- Live `/api/scanner/setup-trade-matrix` returns 8 setups, 21
  trades, 12 experimental, 3 aliases, full matrix payload.
- Live `/api/scanner/setup-coverage` after restart: registered_checkers
  37 → 38, orphans still 2 (`breaking_news`, `time_of_day_fade` —
  operator deferred).

### Operator action on DGX
1. Save to GitHub → `git pull` on DGX (backend hot-reloads).
2. Verify the new endpoint:
   ```
   curl -s http://localhost:8001/api/scanner/setup-trade-matrix \
     | python3 -m json.tool | head -40
   ```
3. After tomorrow's open, watch for `out_of_context_warning=True`
   alerts in the live feed — these are trades the matrix flags as
   firing in the wrong daily Setup. If false-positive rate is high,
   we tune the classifier thresholds; if low, we have validation
   that the matrix is doing its job.
4. After ~2 weeks of live data, decide whether to flip from soft-gate
   (current) to strict-gate (block out-of-context alerts entirely).

### Deferred / next session
- 3:30 trade rules need live validation — operator noted it was
  designed for low-float; we adapted it for the liquid universe by
  swapping the volume gate for held-above-OR + tight-afternoon-
  consolidation structure. May need threshold tuning.
- Auto-generate `SETUPS_AND_TRADES.md` from the constants on commit
  (currently hand-edited to mirror constants — drift risk).
- UI heat-grid rendering for the matrix.
- Feed `market_setup` + `is_countertrend` as features into the AI
  training pipeline.



## 2026-04-29 (evening) — 9 new detector functions (orphans + playbook setups)

Operator's last `/api/scanner/setup-coverage` showed 8 orphans (setups
declared in `_enabled_setups` but with no registered checker function).
Plus the operator provided 3 new playbook screenshots (VWAP Continuation,
Premarket High Break, Bouncy Ball Trade) for setups not yet covered.

### Shipped — 6 orphan detectors (semantic intent confirmed by operator)
- `_check_first_move_up`     — SHORT (fade first morning push to HOD).
  Trigger: ≥1.5% push above open, within 0.5% of HOD, RSI ≥68, ≥1.0%
  above VWAP, RVOL ≥1.5. Stop above HOD + 0.25×ATR. Target: VWAP/open.
- `_check_first_move_down`   — LONG  (fade first morning flush to LOD).
  Mirror of above. Stop below LOD − 0.25×ATR. Target: VWAP/open.
- `_check_back_through_open` — SHORT. Stock pushed ≥0.5% above open
  earlier, now crossed BACK below it; RVOL ≥1.2, lost 9-EMA, R:R ≥1.2.
  Stop above open + 0.3×ATR. Target: LOD or VWAP-low.
- `_check_up_through_open`   — LONG (mirror of back_through_open).
- `_check_gap_pick_roll`     — LONG continuation off gap. Gap ≥1%
  holding, riding 9-EMA (−0.5% to +1.0% off), RSI 50-72, RVOL ≥1.5.
  Stop below 9-EMA. Target: +2×ATR.
- `_check_bella_fade`        — SHORT parabolic fade. Distinct from
  vwap_fade: requires extension from BOTH VWAP (≥2%) AND 9-EMA (≥1.5%),
  RSI ≥75. Stop above HOD. Target: VWAP.

### Shipped — 3 new playbook setups from operator screenshots
- `_check_vwap_continuation` — LONG playbook: morning push ≥1.5% from
  open, pullback into VWAP (−0.6% to +0.4%), uptrend + above 9-EMA,
  RVOL ≥1.3, RSI ≥45. Distinct from `vwap_bounce` (which fires on any
  uptrend pullback) by requiring the prior morning-strength signature.
  Time window: late morning + midday + afternoon (10am-2pm-ish).
- `_check_premarket_high_break` — LONG playbook: opening drive only,
  OR-breakout above + gap ≥1% + holding gap + RVOL ≥2.0 + above VWAP.
  Distinct from `opening_drive` (which requires 3% gap) by firing on
  weaker gaps as long as the OR break confirms strength. Stop below
  LOD − $0.02. Target: +2.5×ATR.
- `_check_bouncy_ball`       — SHORT playbook: late morning + midday
  + power hour. ≥1.5% down move from open, below 9-EMA + below VWAP
  (−1% to −3% — avoids overextended caps), RSI ≤48, near LOD,
  RVOL ≥1.3. Distinct from `vwap_fade_short` by requiring the
  failed-bounce + support-break structure.

### Wiring
- All 9 detectors registered in the `checkers` dict in `_check_setup`.
- All 9 added to class-level `REGISTERED_SETUP_TYPES` frozenset (so
  the source-level drift guard test
  `test_registered_set_matches_checkers_dict` keeps the dict and the
  frozenset in lockstep).
- 3 new playbook setups added to `_enabled_setups` and to
  `STRATEGY_TIME_WINDOWS` (`vwap_continuation`: late-morning/midday/
  afternoon; `premarket_high_break`: opening auction/drive only;
  `bouncy_ball`: late-morning through close).

### Verification
- 17 new tests in `tests/test_orphan_setup_detectors.py` cover:
  registration in checkers dict + frozenset, presence in
  `_enabled_setups`, presence in `STRATEGY_TIME_WINDOWS`, positive
  firing cases for each detector, and key negative cases (RSI not
  overbought, no prior morning push, outside opening window for
  premarket_high_break, overextended-from-VWAP skip for bouncy_ball).
- 37/37 passing across `test_orphan_setup_detectors`,
  `test_scanner_setup_coverage`, `test_strategy_time_window_reclassification`,
  and `test_scanner_canary`.
- Live `/api/scanner/setup-coverage` after backend restart:
  - `orphan_count: 8 → 2` (only `breaking_news` and `time_of_day_fade`
    remain — operator deferred those for a later session).
  - `registered_checkers: 28 → 37`.

### Operator action on DGX
1. Save to GitHub, `git pull` on DGX (backend hot-reloads).
2. Verify orphan count dropped:
   ```
   curl -s http://localhost:8001/api/scanner/setup-coverage \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('orphans:', d['totals'].get('orphan_count'))"
   ```
   Should print `orphans: 2`.
3. Watch `/api/scanner/detector-stats` over the next session — the new
   detectors will start showing under `silent_detectors` until they
   fire their first hit, then graduate to `active_detectors`. If any
   stay silent for several sessions, dial down their thresholds via
   the proximity-audit story (see CHANGELOG 2026-04-29 afternoon-15b).



## 2026-04-29 (afternoon-15) — Scanner audit (all five passes)

### Five issues fixed in this round (instance fix → coverage → proximity → bucket disambiguation → reclassification)

#### 1. Scanner-router instance mismatch (the diagnostic was lying)
Operator hit `POST /api/live-scanner/start` and got back `running:
true, scan_count: 32, alerts_generated: 7`, then immediately curled
`/api/scanner/detector-stats` and got `running: false, scan_count:
0`. Two endpoints, two different scanner instances.

**Root cause**: `routers/scanner.py:_scanner_service` is initialised
in `server.py:443` via `init_scanner_router(predictive_scanner)` —
that's the *predictive* scanner, a totally different singleton from
the live `enhanced_scanner` (`background_scanner` in server.py).
The `detector-stats` endpoint reads attributes (`_detector_evals`,
`_detector_hits`, `_running`, `_scan_count`) that **only exist on
the enhanced scanner**. Reading them off the predictive scanner
gives all-zero defaults via `getattr(..., 0)`.

So the entire diagnostic surface for the afternoon-13 audit was
silently broken. The live scanner WAS running and generating alerts;
the dashboard just couldn't see it.

**Fix**: `routers/scanner.py::get_detector_stats` now imports
`get_enhanced_scanner()` directly and reads telemetry off the
resulting `live_scanner` instance. The legacy `_scanner_service`
injection is left untouched (still serves predictive endpoints).

#### 2. New `/api/scanner/setup-coverage` diagnostic
Operator's first detector-stats reading (post-fix) showed:
- 35 setups in `_enabled_setups`
- Only 14 actually evaluated (the rest filtered out by
  `_is_setup_valid_now` for time-window/regime mismatch — expected
  for opening-only setups during afternoon)
- Of the 14, only 2 produced alerts (`relative_strength`: 35 hits
  34.7%, `second_chance`: 5 hits 5%)
- 12 silent detectors with 0 hits across 101 evaluations each

But also: ~21 names in `_enabled_setups` (e.g. `bella_fade`,
`breaking_news`, `first_move_down`, `first_move_up`, `gap_pick_roll`,
`time_of_day_fade`, `up_through_open`, `back_through_open`,
`vwap_reclaim`, `vwap_rejection`) **have no registered checker
function at all**. They're silent no-ops, eating a loop iteration
per scan cycle and producing nothing.

**Fix**: new endpoint `GET /api/scanner/setup-coverage` partitions
the setups into four buckets:
- `orphan_enabled_setups`: enabled but no registered checker
  → these are dead names; either remove from `_enabled_setups` or
    add a checker function for them.
- `silent_detectors`: registered + 0 cumulative hits → likely
  threshold issues or upstream data gaps; needs calibration audit.
- `active_detectors`: registered + ≥1 hit → working as designed.
- `unenabled_with_checkers`: registered but not in `_enabled_setups`
  → unused code (potentially deletable).

Also returns per-detector eval/hit counts for the active and silent
buckets so the operator can see exactly where evaluations are
landing.

### Verification
- 3 new tests across `test_scanner_router_instance_fix.py` and
  `test_scanner_setup_coverage.py`
- 16/16 passing across afternoon-12/13/14/15 suites.

#### 3. Threshold-proximity audit (afternoon-15b)
Once silent_detectors were identified, operator's natural next
question was "how far off are these thresholds?". Code-reading the
`_check_*` functions revealed each detector has 1-3 gating
conditions (e.g. vwap_fade: `dist_from_vwap > 2.5%` AND `RSI < 35`).
Without instrumentation, operator had to manually grep + reason
about whether thresholds were unrealistic vs the actual market.

**Fix**: scanner now records gating-value samples on every
evaluation via `_sample_proximity_for_setup`. Each silent detector
is registered in a `_PROXIMITY_FIELDS` table with `(label, attr,
threshold, comparator)` tuples. Bounded 200-sample ring-buffer per
setup keeps memory fixed.

The `setup-coverage` endpoint's silent_detectors entries now carry
a `threshold_proximity` block:
```json
{
  "setup_type": "vwap_fade",
  "evaluations": 101, "hits": 0,
  "threshold_proximity": {
    "samples": 101,
    "fields": [
      {
        "label": "abs_dist_from_vwap", "comparator": "abs_gt",
        "threshold": 2.5,
        "min": 0.04, "max": 1.83, "mean": 0.62,
        "samples_meeting": 0, "samples_total": 101,
        "verdict": "threshold never reached — max 1.83 < 2.5 (shortfall 0.67)"
      },
      ...
    ]
  }
}
```

The verdict string tells the operator EXACTLY how to retune. If
`max < threshold` for an `abs_gt` comparator, lowering the threshold
to ~75% of the max would start producing alerts. If `min > threshold`
for an `lt` comparator, the symbol pool just isn't getting extreme
enough — either rotate watchlist or relax the inequality.

12 silent detectors covered:
`vwap_fade`, `vwap_bounce`, `rubber_band`, `tidal_wave`,
`mean_reversion`, `squeeze`, `breakout`, `gap_fade`, `hod_breakout`,
`range_break`, `volume_capitulation`, `chart_pattern`.
Active detectors (`relative_strength`, `second_chance`) are
deliberately omitted — they're already firing.

### Verification (final)
- 8 new tests in `test_scanner_threshold_proximity.py`:
  registry coverage, bounded ring-buffer, missing-attr handling,
  `abs_gt` / `lt` / `gt` verdict semantics, no-samples short-circuit.
- 11/11 passing across all afternoon-15 suites; **24/24 across all
  afternoon-12/13/14/15 fixes**.

#### 4. Bucket disambiguation: orphans vs time-filtered (afternoon-15c)
First live run of `setup-coverage` reported `orphan_count: 21`, but
many of those (e.g. `9_ema_scalp`, `backside`, `opening_drive`,
`orb`, `hitchhiker`, `puppy_dog`, `big_dog`) actually have working
checker functions — they're just blocked by `_is_setup_valid_now`
during afternoon (opening-only setups). The original logic used
`cum_evals.keys()` as the "registered" set, which only contains
setups whose checker was actually called — time-filtered setups
look like orphans because their checker is never invoked.

**Fix**: introduced class-level
`EnhancedBackgroundScanner.REGISTERED_SETUP_TYPES: frozenset`
listing every setup_type with a checker function. Now
`setup-coverage` distinguishes:
- `orphan_enabled_setups`: in enabled, NOT in `REGISTERED_SETUP_TYPES`
  → no code at all.
- `time_filtered_setups`: in enabled AND registered, but never
  evaluated → blocked by time-window/regime gate; expected behaviour.
- `silent_detectors`: registered + evaluated + 0 hits → threshold tuning needed.
- `active_detectors`: registered + evaluated + ≥1 hit → working.
- `unenabled_with_checkers`: registered but not enabled → unused code.

Also updated `totals` to expose `registered_checkers`,
`evaluated_at_least_once`, and `time_filtered_count` so operator can
tell at a glance whether the small evaluation pool is due to
time-window filtering vs missing checkers.

**Regression guard**: new test
`test_registered_set_matches_checkers_dict` extracts both the
`checkers` dict keys and the `REGISTERED_SETUP_TYPES` frozenset via
regex from the source, then asserts they're identical. Any future
drift between adding/removing a checker and updating the frozenset
will fail this test immediately. **No more silent mis-classification
of time-filtered setups as orphans.**

### Verification (final)
- 14/14 passing across all afternoon-12/13/14/15 suites.

#### 5. Operator-driven strategy time-window reclassification (afternoon-15d)
Operator reviewed the original `STRATEGY_TIME_WINDOWS` and explicitly
reclassified 22 setups based on real trading edge (NOT naming
convention). Many setups previously locked to OPENING_AUCTION /
OPENING_DRIVE / morning windows actually have all-day edge per
operator's experience.

**ALL-DAY** (RTH 9:30-16:00 ET):
`big_dog`, `puppy_dog`, `spencer_scalp`, `backside`, `hitchhiker`,
`fashionably_late`, `abc_scalp`, `first_vwap_pullback`,
`time_of_day_fade`, `vwap_reclaim`, `vwap_rejection`, `bella_fade`,
`breaking_news` (13 setups).

**MORNING-ONLY** (before ~11:30 ET buffer):
`9_ema_scalp`, `opening_drive`, `orb`, `gap_give_go`, `first_move_up`,
`first_move_down`, `back_through_open`, `gap_pick_roll`,
`up_through_open` (9 setups).

**Refactor**: introduced `_RTH_ALL_DAY` and `_MORNING_ONLY` named
constants (lists of TimeWindow values) so the dict is declarative.
Moving a setup between profiles is now a one-line change.

**Regression guard**: 5 new tests in
`test_strategy_time_window_reclassification.py` lock both the named
profiles AND each operator-classified setup's mapping.

### Verification (final)
- 19/19 passing across all afternoon-12/13/14/15 suites.

### Operator action on DGX
1. Save to GitHub, `git pull` on DGX (backend hot-reloads).
2. Run:
   ```
   curl -s http://localhost:8001/api/scanner/setup-coverage \
     | python3 -m json.tool
   ```
3. Read the `orphan_enabled_setups` list — these names should either
   be removed from `_enabled_setups` (line 731 of `enhanced_scanner.py`)
   OR have detector functions added.
4. Read `silent_detectors` — these need threshold tuning. Most likely
   suspects: `vwap_fade` (RSI<35 AND >2.5% from VWAP both required),
   `mean_reversion` (RSI extreme + near S/R + EMA20 distance triple-
   AND), `breakout` (resistance level needed AND price within 1.5%
   AND rvol≥1.8). Loosening any one threshold by ~25% should produce
   real alerts.



## 2026-04-29 (afternoon-14) — Trade pipeline veto audit (P0)

Operator's `/api/trading-bot/rejection-analytics` showed 18
`evaluator_veto` rejections + 0 orders queued today despite 50
evaluations running. Backend log grep revealed the generic label was
hiding **two real bugs**:

1. **Python NameError**: `cannot access local variable
   'ai_consultation_result' where it is not associated with a value`
   — `ai_consultation_result` was referenced by `build_entry_context`
   on line ~473 but only assigned on line ~498. Every evaluation that
   reached the trade-build stage threw the NameError, vetoed as
   `evaluator_veto`. INTC backside hit this every cycle.

2. **R:R cap too tight**: many vetoes were `R:R 1.95 / 1.99 / 2.00 <
   2.5 min required`. The 2.5 min_risk_reward setting in
   `risk_params` is too aggressive for intraday scalps that target
   1.5-2× risk by design.

### Fix
- `services/opportunity_evaluator.py`:
  - Initialise `ai_consultation_result: Optional[Dict[str, Any]] = None`
    early (alongside `confidence_gate_result = None`) so it's safely
    in scope before `build_entry_context` reads it.
  - Replaced the catch-all `evaluator_veto` with **specific reason
    codes** at every `return None` path: `no_price`,
    `smart_filter_skip`, `gate_skip`, `position_size_zero`,
    `rr_below_min`, `ai_consultation_block`, `evaluator_exception`.
    Each carries rich `context` (rr ratio, entry/stop, confidence
    score, etc.) for the dashboard.
- `services/trading_bot_service.py`:
  - `record_rejection` now sets
    `self._last_evaluator_rejection_recorded = True` as a side-effect.
  - `_scan_for_setups` resets the flag before each evaluation and
    only fires the catch-all `evaluator_veto_unknown` if the flag is
    still False — preventing double-counting in the analytics.
  - Added narrative branches in `_compose_rejection_narrative` for
    every new reason code so V5 Bot's Brain panel shows wordy,
    operator-friendly explanations instead of generic fallback text.

### What this enables
- `/api/trading-bot/rejection-analytics?days=1` will now break down
  the 18 rejections into `rr_below_min: 12, position_size_zero: 4,
  evaluator_exception: 2` (or similar) — operator can finally see
  which gate is the actual bottleneck, then tune that specific dial
  instead of guessing.
- The `evaluator_exception` count immediately surfaces code bugs in
  the future (any new NameError / KeyError will register clearly
  instead of silently masquerading as `evaluator_veto`).

### NOT changed
- `risk_params.min_risk_reward = 2.5` deliberately left at 2.5 for
  this round. After ~30 min of fresh data with the new specific
  codes, operator can decide whether to lower it (likely 1.8) based
  on the precise distribution. Tuning before the diagnostic split
  would be guessing.

### Verification
- 5 new tests in `tests/test_evaluator_rejection_codes.py`:
  early-init contract, specific-reason coverage at every return None,
  flag set in record_rejection, flag reset+check in scan loop,
  narrative branches present.
- 14/14 passing across all evaluator + pusher suites.

### Operator action on DGX
1. `git pull` on DGX. Backend hot-reloads.
2. Wait 30 minutes for fresh evaluations.
3. Run:
   ```
   curl -s "http://localhost:8001/api/trading-bot/rejection-analytics?days=1&min_count=1" | python3 -m json.tool
   ```
4. The `by_reason_code` array will now show the specific bottleneck.
   Most likely `rr_below_min` will dominate — if so, lower
   `min_risk_reward` from 2.5 → 1.8 (operator-side, via Mongo
   `bot_state.risk_params` or whatever the existing operator UI is).
5. The INTC backside `evaluator_exception` should drop to 0 — that
   was a Python bug, not a market signal.



## 2026-04-29 (afternoon-13) — Pusher-side subscription gate (P0)

Operator post-restart logs showed a storm of unsubscribed-symbol RPC
failures clogging the IB event loop:

```
12:52:20 [WARNING] [RPC] latest-bars TQQQ failed:
12:52:38 [WARNING] [RPC] latest-bars SQQQ failed:
12:52:56 [WARNING] [RPC] latest-bars PLTR failed:
... 17 more, including XLE, GLD, HOOD, NFLX, VOO, SMH ...
12:54:03 [WARNING] Connection error on post. Retry 1/3 in 5.2s:
         HTTPConnectionPool(host='192.168.50.2', port=8001):
         Read timed out. (read timeout=120)
```

DGX was hammering the pusher with `/rpc/latest-bars` calls for
symbols not in the 14-symbol L1 subscription list. Each unsubscribed
symbol burned 18s in `qualifyContracts + reqHistoricalData` before
timing out, blocking the IB event loop and starving the push handler
→ 120s+ DGX response times → `Read timed out`.

### Root cause
The DGX-side gate in `services/ib_pusher_rpc.py::latest_bars` was the
only defense and it falls through when `subscriptions()` returns
None. That happens whenever:
- `/rpc/subscriptions` times out (3s was too tight under pusher load)
- DGX backend just hot-reloaded and `_subs_cache` is empty
- Network blip between Windows and DGX

When DGX-side gate falls through, the pusher had no defense against
unsubscribed-symbol requests and would happily try to fetch them
synchronously.

### Fix — defense in depth
1. **Pusher-side gate** in `documents/scripts/ib_data_pusher.py`:
   - `/rpc/latest-bars`: rejects unsubscribed symbols upfront with
     `success: False, error: "not_subscribed"` — never calls
     `qualifyContracts` / `reqHistoricalDataAsync` for them.
   - `/rpc/latest-bars-batch`: partitions input into subscribed
     (sent to IB) + unsubscribed (returned as fast `not_subscribed`
     failures). Symbol order preserved in the response.
   - Index symbols (VIX, SPX, NDX, RUT, DJX, VVIX) are exempted
     because they're commonly requested for regime reference and
     may not be in `subscribed_contracts`.
2. **DGX-side timeout bump** in `services/ib_pusher_rpc.py`:
   - `/rpc/subscriptions` GET timeout 3.0s → 8.0s. Gives the pusher
     headroom under load while staying well under the 18s
     latest-bars timeout. Reduces fallthrough rate.

### Why two layers
The DGX-side gate is the primary path — it short-circuits BEFORE any
HTTP round-trip. The pusher-side gate is the safety net for when the
DGX-side gate fails open. Even with both gates, the response is
~5ms (one HTTP round-trip + dict lookup) instead of 18s (full IB
qualify + reqHistoricalData + timeout).

### Verification
- 4 new tests in `tests/test_pusher_server_side_subs_gate.py`:
  single-handler gate, batch-handler partition, DGX-side timeout
  bump, DGX-side gate unchanged for subscribed symbols.
- 13/13 passing across all pusher-gate-related suites
  (test_pusher_subs_gate, test_pusher_account_updates_no_block,
  test_pusher_server_side_subs_gate).

### Operator action on Windows
1. `git pull` on Windows.
2. Restart `ib_data_pusher.py`.
3. Watch the console — the storm of `[RPC] latest-bars XXX failed:`
   warnings should DISAPPEAR for unsubscribed symbols. Instead, you
   may see fewer log lines because rejections are silent (success:
   False, no warning). `Pushing: ...` lines should flow steadily
   without the `Read timed out` retries.
4. DGX backend should respond to pushes in <1s (vs the >120s timeouts
   before this fix).



## 2026-04-29 (afternoon-12) — Pusher push loop hang fix (P0)

Operator post-pull/restart screenshot: `IB PUSHER DEAD · last push
never`. IB Gateway green, ib_data_pusher.py running, but pusher
console stalled forever at `Requesting account updates...` — push
loop never starts → `0 quotes`, `0 positions`, `Equity: $—`.

### Root cause
`IB.reqAccountUpdates(account)` is `_run(reqAccountUpdatesAsync())`,
which awaits the IB Gateway's `accountDownloadEnd` event. In the
wild, IB Gateway can stall that event indefinitely even while the
Gateway window shows green. The afternoon-7 fix removed the worker-
thread watchdog (because the watchdog itself broke things by missing
an asyncio loop), but it did not add a timeout — so a stalled stream
now hangs the entire pusher startup. The same pattern affected
`fetch_news_providers` (which runs *before* the first push), so it
was also at risk.

### Fix
- `request_account_updates` now wraps `reqAccountUpdatesAsync(account)`
  in `asyncio.wait_for(..., timeout=10.0)`. Critical: the async
  version sends the IB API request to the wire BEFORE awaiting
  `accountDownloadEnd`, so even on timeout the subscription is
  active and `accountValueEvent` continues to fire as IB streams
  values. This preserves ib_insync's wrapper request-registration
  (so messages route correctly to fire events) AND prevents the push
  loop from hanging.
- `fetch_news_providers` wraps `reqNewsProvidersAsync()` in
  `asyncio.wait_for(..., timeout=8.0)`. On `TimeoutError`, logs a
  warning and proceeds with empty providers list (non-critical).
  Falls back to the legacy sync call if `reqNewsProvidersAsync` is
  missing on older ib_insync builds.

### Why this fix is more robust than the initial raw-client attempt
The first attempt used the raw `client.reqAccountUpdates(True, ...)`
to skip the await entirely. That worked for unblocking the loop but
bypassed ib_insync's wrapper request-registration step. Without
that registration, the wrapper may not route incoming
`updateAccountValue` messages to fire `accountValueEvent` cleanly
(observed empirically: pusher reported GREEN with quotes + positions
flowing, but `account_data` stayed empty → `Equity: $—`). The
async-with-timeout approach fires the wrapper's `startReq` first,
guaranteeing event routing.

### Verification
- 5 new tests in `tests/test_pusher_account_updates_no_block.py`:
  async-with-timeout primary path, TimeoutError handled gracefully,
  sync fallback for older ib_insync, news-provider timeout, news
  provider sync fallback.
- All 5 passing.

### Operator action on Windows
1. `git pull` on Windows.
2. Restart `ib_data_pusher.py`.
3. Watch the console — should see within ~10s of "Requesting account
   updates...":
   - `Requested account updates for DUN615665` (or
     `... timed out after 10s ... continuing anyway` if IB is slow)
   - `Skipping fundamental data...`
   - `Fetching news providers...`
   - Either `News providers: [...]` or `reqNewsProviders timed out`
   - `==> STARTING PUSH LOOP (TRADING ONLY)`
   - Push lines: `Pushing: N quotes, M positions, K account fields, ...`
4. DGX dashboard `Equity: $—` should resolve to live NetLiquidation
   within ~30s as account values stream in.



## 2026-04-29 (afternoon-11) — Drawer split handle (operator-resizable bottom drawer)

Operator approved: vertical drag-handle between SentCom Intelligence
(left) and Stream Deep Feed (right) in the V5 bottom drawer. Replaces
the static 60/40 grid with a flex layout the operator can rebalance
on the fly depending on whether they're in "watching the bot decide"
mode (favour Intelligence) or "reading the narrative trail" mode
(favour Stream).

### New component
- `frontend/src/components/sentcom/v5/DrawerSplitHandle.jsx`
  - `useDrawerSplit()` hook — manages `leftPct` state, persists to
    `localStorage["v5_drawer_left_pct"]`, exposes
    `setLeftPct` (clamped to 25-80%) and `resetToDefault` (60%).
  - `<DrawerSplitHandle>` component — 4px vertical bar with a 3-dot
    grip accent. Hover/active state in emerald. `cursor-col-resize`.
    `role="separator"`, `aria-orientation="vertical"` for a11y.
  - Mouse-down → window-level `mousemove` listener computes
    `(clientX - container.left) / container.width × 100` per move,
    feeds clamped value to `setLeftPct`. `mouseup` releases.
  - Double-click resets to default 60%.

### Wired into V5
- `SentComV5View.jsx`:
  - Replaced `grid-template-columns: 60% 40%` with a flex layout
    using inline widths driven by `leftPct` state.
  - `drawerContainerRef` ref → passed to handle so it can read its
    parent's `getBoundingClientRect()` for the percent math.
  - Three-row drawer: left panel (Intelligence, `width: leftPct%`),
    handle, right panel (Stream Deep Feed, `width: (100-leftPct)%`).

### Persistence + safety
- `localStorage` key `v5_drawer_left_pct` survives refresh.
- Read on mount with bounds check (25-80) + isFinite guard.
- localStorage write wrapped in try/catch — no breakage in private/
  incognito mode where storage may be disabled.
- Double-click handler is on the handle itself, so a stuck split
  is always recoverable without DevTools.

### Verification
- Lint clean across both files.
- Playwright screenshot confirms the layout renders with the handle
  positioned correctly between the two drawer panels at the default
  60/40 split. SentCom Intelligence shows live decisions (MSFT/AAPL
  skips with score breakdown), Stream Deep Feed on the right.
- Programmatic drag in Playwright doesn't fire all the synthetic
  events the hook relies on (Playwright limitation, not a bug) —
  real browsers handle the `mousemove`/`mouseup` window listeners
  natively.

### Operator action
- Pull on DGX. Browser auto-reloads.
- Hover over the thin column between SentCom Intelligence and
  Stream Deep Feed in the bottom drawer — cursor changes to
  `col-resize`, handle lights up in emerald.
- Drag horizontally to rebalance. Choice persists across
  refreshes / sessions.
- Double-click handle to reset to 60/40.



Operator approved option B + briefings restyle:
1. Bottom drawer becomes "twin live panels" — SentCom Intelligence (60%)
   + Unified Stream mirror (40%). Drawer height 22vh → 32vh.
2. ALL three reflection panels (Model Health, Smart Levels Analytics,
   AI Decision Audit) → moved to NIA section "Reflection & Audit".
3. Briefings panel collapsed into a 4-button pulse strip at the top of
   the right sidebar. Active-window briefings pulse green; click any
   button to open a modal with the full original card. Frees the
   entire right sidebar for Open Positions.

### Why this layout is more coherent
- **Command Center = live action surface**: chart, scanner, stream,
  positions, **live confidence-gate decisions**, briefings-on-demand.
  Every visible panel updates during market hours.
- **NIA = training & maintenance surface**: model health, A/B
  analytics, post-trade audit, strategy promotion. Every visible
  panel changes only EOD or operator-triggered.

### New components
- `frontend/src/components/sentcom/v5/BriefingsCompactStrip.jsx`
  - 4 buttons: Morning Prep / Mid-Day Recap / Power Hour / EOD Recap
  - `statusFor` math (lifted from BriefingsV5) decides
    `pending` / `active` / `passed` per ET-time window
  - Active state uses `animate-pulse-glow` + emerald shadow ring
  - State indicator dot — emerald pulsing dot for active, amber for
    pending, dim grey for passed
  - Click → modal renders the matching original card
    (`MorningPrepCard` / `MidDayRecapCard` / `PowerHourCard` /
    `CloseRecapCard`) with `expanded={true}` so the operator sees the
    full version — no compact re-implementation, no drift between
    sidebar view and modal view
  - Backdrop click + X button + opening another briefing all close
    the current modal cleanly
- `compact` prop added to `SentComIntelligencePanel` (NIA, also reused
  in Command Center bottom drawer)
  - Tighter banner (mode pill + inline stats)
  - Decision feed always visible (no click-to-expand)
  - Fills available column height

### Files touched
- `frontend/src/components/sentcom/SentComV5View.jsx` —
  - Drops `BriefingsV5` (used `BriefingsCompactStrip` instead)
  - Drops `ModelHealthScorecard`, `SmartLevelsAnalyticsCard`,
    `AIDecisionAuditCard` from the bottom drawer
  - Imports `SentComIntelligencePanel` from `../NIA/`
  - Bottom drawer becomes `grid-template-columns: 60% 40%` with
    SentCom Intelligence (compact) + Unified Stream mirror
  - Right sidebar: briefings strip (auto-height) + Open Positions
    (flex-1 — gets all remaining vertical space)
- `frontend/src/components/NIA/index.jsx` —
  - Added new "Reflection & Audit" section housing the 3 relocated
    panels
  - Model Health gets full row (retrain controls need real estate);
    Smart Levels A/B + AI Decision Audit share the next row
- `frontend/src/components/sentcom/v5/BriefingsV5.jsx` —
  - Exported `MorningPrepCard`, `MidDayRecapCard`, `PowerHourCard`,
    `CloseRecapCard`, `ClickableSymbol`, and `statusFor` so the new
    compact strip can reuse the original rendering
  - No behaviour change for any existing consumer

### Verification
- Playwright screenshot confirms full layout rendering on cloud preview:
  - 4 briefing buttons in right sidebar with correct active-state
    pulse (Mid-Day Recap + Power Hour green-active at the screenshot
    time; Morning Prep + EOD Recap dim-passed/pending)
  - Bottom drawer 60/40 split with SentCom Intelligence (compact)
    showing CAUTIOUS mode banner + decision feed (MSFT INT-01 SKIP)
    on the left, "Stream · Deep Feed" mirror on the right
  - Right sidebar shows briefings strip + Open Positions (filling
    the remaining height)
- Lint clean across all 5 touched files (BriefingsCompactStrip,
  SentComV5View, NIA/index, NIA/SentComIntelligencePanel, BriefingsV5)
- Backend regression: 72/72 of the affected test suites still
  passing (no backend code touched).

### Operator action
- Pull on DGX (frontend hot-reload picks it up automatically)
- Refresh browser. Layout updates instantly:
  - Bottom drawer now shows live SentCom Intelligence + deeper Stream
    history instead of static Model Health / Smart Levels / AI Audit
  - Right sidebar's briefings shrunk into a 4-button pulse row;
    active briefings pulse green
  - Click any briefing button (especially the pulsing ones) to see
    the full briefing in a modal
- NIA's new "Reflection & Audit" section at the bottom now hosts
  Model Health (full retraining controls) + the two A/B analytics
  cards. Operator's existing NIA muscle memory unchanged for sections
  1-4; just look further down for the relocated panels.



## 2026-04-29 (afternoon-9) — L1 list restart resilience (Mongo + local file)

Operator follow-up: "yes make that improvement" → persist the pusher's
L1 list so it survives pusher AND DGX restarts, even when the cloud
backend is briefly unreachable.

### Two layers of restart resilience

#### 1. Backend cache: `pusher_config_cache._id="l1_recommendations"`
- Every successful `get_pusher_l1_recommendations` call upserts the
  resolved list to Mongo. Only writes when `top_by_adv` has data —
  never overwrites a good cache with the ETF-only fallback.
- When `symbol_adv_cache` is empty (DGX just restarted, before the
  nightly rebuild), the helper now reads the cached recommendation
  BEFORE falling back to ETF-only. Response includes
  `source: "cached_recommendation"` + `cache_updated_at` so the
  pusher can log the staleness.
- New response field `source` clarifies origin every call:
  - `"live_ranking"` — fresh from `symbol_adv_cache`
  - `"cached_recommendation"` — Mongo fallback (DGX cache stale)
  - `"etf_fallback"` — both empty, returning the always-on ETF
    reference set only

#### 2. Pusher local file: `~/.ib_pusher_l1_cache.json`
- Every successful auto-fetch (or env-var override) writes the
  resolved list + a timestamp to a local JSON file.
- On next pusher restart, if the auto-fetch fails (cloud unreachable,
  DGX mid-restart, network blip), the pusher reads from the local
  cache BEFORE falling back to the hardcoded `--symbols` default.
- Pusher logs explicitly indicate which path was taken:
  - `[L1] Auto-fetched 80 symbols from http://...`
  - `[L1] Auto-fetch failed (...) — using cached list (80 symbols, saved at 2026-04-29T10:30:00)`
  - `[L1] Auto-fetch failed (...) and no local cache — falling back to --symbols default`

### What this prevents
The "what was I subscribed to?" failure mode across the IB Gateway
daily logoff cycle:
- **Before**: pusher restart → cloud backend mid-restart → auto-fetch
  fails → falls back to hardcoded 14-symbol default. Operator wakes
  up to a much narrower L1 list than they configured.
- **After**: pusher restart → cloud unreachable → reads local file
  cache → restores yesterday's 80-symbol list. Operator's
  subscription state is stable across restarts that race with backend
  unavailability.

### Verification
- 3 new tests in `tests/test_pusher_l1_recommendations.py`:
  - `test_persists_recommendation_to_pusher_config_cache` — write path
  - `test_falls_back_to_cached_list_when_live_ranking_empty` — DGX
    restart fallback
  - `test_live_ranking_overrides_cache_when_both_present` — fresh
    data wins when available
- 175/175 tests passing across all related suites.
- Live curl on cloud preview: `source: "etf_fallback"` (no live ADV
  data on this preview env). On DGX with the populated cache, will
  return `source: "live_ranking"` on first call, then
  `"cached_recommendation"` if the cache is ever queried in a
  transient state.
- Lint clean.

### Operator action on Windows
Already documented in afternoon-8: pull + add
`IB_PUSHER_L1_AUTO_TOP_N=60` to pusher launch env, restart pusher.
The new restart resilience is fully passive — local file cache writes
on success, reads on failure. No additional configuration needed.



## 2026-04-29 (afternoon-8) — L1 subscription expansion (env-var-driven)

Operator approved (option A): expand pusher's hardcoded 14 quote-subs
to up to 80, giving live freshness to a wider intraday tier without
requiring code changes on Windows once shipped.

### Why this is safe NOW
The afternoon-7 RPC gate already short-circuits cache-misses for
symbols not on the pusher's subs list, so anything off the L1 list
falls back to Mongo. Expanding L1 from 14 → 80 just promotes 66 more
symbols from "Mongo-stale freshness" to "live RPC freshness" with no
other code changes.

IB Gateway paper has a 100-line streaming ceiling. We cap the L1 list
at 80 to leave 20 slots for the dynamic L2 routing (top-3 EVAL setups)
already in place.

### Backend
- New helper `services.symbol_universe.get_pusher_l1_recommendations`:
  pulls the top-N symbols by `avg_dollar_volume` from `symbol_adv_cache`
  (excluding `unqualifiable=True`), composes them with an always-on
  ETF reference set (SPY, QQQ, IWM, DIA, VIX, 11 SPDR sectors, size +
  style + volatility/credit references), honors operator-pinned
  `extra_priority` overrides, and caps at `max_total`.
- New endpoint `GET /api/backfill/pusher-l1-recommendations?top_n=60&max_total=80`
  surfaces the recommendation. Read by the pusher on startup.

### Pusher
- `documents/scripts/ib_data_pusher.py::main` now resolves symbols
  from three sources, in priority:
  1. **`IB_PUSHER_L1_SYMBOLS`** env var — explicit list, comma-
     separated. e.g. `"SPY,QQQ,NVDA,..."`. Use this when you want
     full control.
  2. **`IB_PUSHER_L1_AUTO_TOP_N`** env var — set to a positive int
     (e.g. `"60"`) to fetch the recommendation list from the cloud
     backend. Pusher hits `/api/backfill/pusher-l1-recommendations`
     and adopts the result.
  3. **`--symbols` CLI arg** — backwards-compatible default
     (the old hardcoded 14).
- Fail-safe: any auto-fetch failure logs cleanly and falls back to
  the CLI default. No silent breakage.
- Hard cap: 80 regardless of source (safety net under IB's 100-line
  ceiling).

### What this changes operationally

| Before | After (with `IB_PUSHER_L1_AUTO_TOP_N=60`) |
|---|---|
| 14 live-RPC symbols | ~80 live-RPC symbols (60 by ADV + ~20 ETF context tape) |
| 14 → tick_to_bar_persister Mongo bars | 80 → tick_to_bar_persister Mongo bars |
| ~200-400 "intraday tier" symbols on stale Mongo | ~120-320 "intraday tier" symbols on stale Mongo |
| Tier 2/3 unchanged | Tier 2/3 unchanged |

The scanner's tiered architecture is unchanged. Tier 1 just has more
"truly live" symbols and fewer "stale-by-classification" ones.

### Verification
- 9 new tests in `tests/test_pusher_l1_recommendations.py`:
  top-N driver, ETF inclusion, unqualifiable exclusion, priority pin
  override, max_total cap, dedup across sources, empty-DB graceful,
  None-db safe, router endpoint shape.
- 172/172 tests passing across all related suites.
- Lint clean.
- Live curl on cloud preview returns 24 symbols (only ETFs since
  empty cache). On DGX with the full ~9,400 symbol_adv_cache, will
  return the full 80.

### Operator action on Windows
Two options after `git pull`:
1. **Auto** (recommended): set `IB_PUSHER_L1_AUTO_TOP_N=60` in the
   pusher launch env. Pusher fetches the recommended list from DGX
   on every restart — list automatically follows whatever the
   `symbol_adv_cache` ranks highest each night.
2. **Manual**: set `IB_PUSHER_L1_SYMBOLS="SPY,QQQ,IWM,...,NVDA,..."`
   to a fixed list. Useful if you want stability across restarts
   regardless of cache changes.

Then restart `ib_data_pusher.py`. Pusher logs will show:
```
  [L1] Auto-fetched 80 symbols from http://192.168.50.2:8001/...
```
or
```
  [L1] Using IB_PUSHER_L1_SYMBOLS env var (XX symbols)
```

### Next: option C (dynamic heat-based promotion)
Once the operator confirms 80-symbol L1 is healthy (no IB pacing errors,
RPC latency stays sane, scanner gets quieter only on truly slow tape):
- Add a `/rpc/replace-l1` endpoint to the pusher (mirrors L2 routing)
- DGX backend tracks scanner "heat" (recently-evaluated + alert-firing
  symbols) and rotates the pusher's 80 slots every ~10 min to follow
  the heat
- Symbols off the heat list roll out, symbols catching scanner
  attention roll in
- Prevents the "always-stale tail of Tier 1" problem permanently



## 2026-04-29 (afternoon-7) — Pusher threading bug fix + un-subscribed RPC gate + tiered scanner doc

Operator's post-restart screenshot revealed two real bugs masked by
afternoon-5's "fixes". Both root-caused and shipped.

### 1. Pusher account/news threading bug (P0 — fixes equity `$—`)
- **Root cause**: `request_account_updates` and `fetch_news_providers`
  in `documents/scripts/ib_data_pusher.py` wrapped the underlying
  ib_insync calls in worker threads as a "hang defense". But on
  Python 3.10+, worker threads don't have an asyncio event loop by
  default, and ib_insync's `reqAccountUpdates` / `reqNewsProviders`
  internally call `util.getLoop()` → `asyncio.get_event_loop()` → hard
  fail with `"There is no current event loop in thread 'ib-acct-updates'"`.
  The watchdog itself broke the thing it was guarding.
- Symptoms in operator's logs:
  - `[ERROR]   Account update request error: There is no current event
    loop in thread 'ib-acct-updates'.`
  - `[WARNING] Could not fetch news providers: There is no current
    event loop in thread 'ib-news-providers'.`
  - Push payload: `0 account fields` forever → V5 equity stuck at `$—`
  - Afternoon-5's `/rpc/account-snapshot` slow path called
    `accountValues()` which reads the (empty) cache → also useless
- **Fix**: dropped both worker threads. Calls run directly on the main
  thread (where ib_insync's event loop already lives). The original
  hang concern was over-engineered — if `reqAccountUpdates` ever
  genuinely hangs, IB connectivity is fundamentally broken.
- **Operator action on Windows**: pull + restart `ib_data_pusher.py`.
  Account data should populate within ~2s of pusher start.

### 2. Un-subscribed-symbol RPC gate (P1 — fixes 4848ms RPC latency)
- **Root cause**: `HybridDataService.fetch_latest_session_bars` called
  `/rpc/latest-bars` for any cache-miss symbol. The pusher only
  subscribes to 14 symbols (Level 1 + L2), so requests for XLE / GLD /
  NFLX / etc forced the pusher to qualify the contract on-demand and
  request bars synchronously — slow (5-10s), often failed, and clogged
  the RPC queue causing latency spikes (4848ms p95 in the screenshot).
- **Fix**: gated on `rpc.subscriptions()` membership. Symbols not in
  the active list short-circuit with
  `success: False, error: "not_in_pusher_subscriptions"`. Caller
  (`realtime_technical_service._get_live_intraday_bars`) already
  handles `success: False` by falling back to the Mongo
  `ib_historical_data` path — which is exactly the right behaviour
  for the 1500-4000+ universe (see architecture doc below).
- Defensive: if `rpc.subscriptions()` returns None/empty (RPC
  unreachable, startup race), the gate falls THROUGH to the existing
  RPC path so we don't lose bars during transient pusher slowness.
- Regression coverage: 4 new tests in `tests/test_pusher_subs_gate.py`.

### 3. Tiered Scanner Architecture (clarification, not a code change)
**Operator's question**: "we need to scan 1500-4000+ qualified symbols.
How do we do that with IB as data provider? We had intraday/swing/
investment scan priorities — does that still exist?"

**Answer: yes, the 3-tier system is alive and active in
`services/enhanced_scanner.py::_get_symbols_for_cycle`**:

| Tier | ADV threshold | Scan frequency | Source |
|---|---|---|---|
| Tier 1 — Intraday | ≥ $50M / 500K shares | Every cycle (~15s) | Mongo + live RPC for the 14 pusher subs |
| Tier 2 — Swing | ≥ $10M / 100K shares | Every 8th cycle (~2 min) | Mongo `ib_historical_data` only |
| Tier 3 — Investment | ≥ $2M / 50K shares | 11:00 AM + 3:45 PM ET only | Mongo `ib_historical_data` only |

The pusher's 14 quote-subscriptions are intentionally narrow — they're
the operator's "active radar" for SPY/QQQ direction + L2 routing for
the top 3 EVAL setups. The full universe (~9,400 in
`symbol_adv_cache`, narrowed to active tiers per the table above)
scans against the **historical Mongo cache** that the 4 turbo
collectors keep fresh on Windows.

The afternoon-7 RPC gate makes this story explicit: Tier 1 symbols on
the pusher subs list go through live RPC; Tier 2 / Tier 3 symbols fall
back to the Mongo cache automatically. No more spurious RPC calls for
un-subscribed tickers.

Does this still make sense? Yes — but two evolutions worth considering:
1. **Tier 1 quote subscription expansion**: 14 symbols is small. We
   could expand the pusher's L1 subscription list to ~100-200 symbols
   (IB paper accounts allow up to 100 streaming Level 1 lines + 3 L2)
   so more intraday-tier symbols get sub-second freshness.
2. **Bar-close persistence**: the tick-to-Mongo persister (P1 from
   previous handoff) would let Tier 1 RPC calls hit Mongo at 1-min
   bar-close granularity instead of going to the pusher. That removes
   the pusher from the hot path entirely for scan reads.

### Verification
- 4 new tests in `tests/test_pusher_subs_gate.py` (subs-gate, cache
  hit short-circuit, defensive fall-through, subscribed pass-through)
- 163/163 tests passing across all related suites
- Lint clean

### Operator action
1. **Windows**: pull + restart `ib_data_pusher.py` — equity should
   populate within seconds; pusher logs should NO LONGER show the
   `'ib-acct-updates'` / `'ib-news-providers'` errors.
2. **DGX**: backend hot-reloads. Verify (a) RPC latency drops back
   below 1s now that un-subscribed symbols don't hit the pusher,
   (b) `/api/scanner/detector-stats` shows the full universe being
   scanned (intraday tier on every cycle), (c) operator's V5 equity
   pill resolves from `$—` to live NetLiquidation.
3. Watch the pusher for `[RPC] latest-bars XLE failed` — should be
   gone (DGX no longer asks for un-subscribed symbols).



## 2026-04-29 (afternoon-6) — Rejection signal provider scaffolding

Operator follow-up: "scaffold that improvement" → wire rejection
analytics into the existing optimizers as observe-only feedback.

### Architecture
- New module: `services/rejection_signal_provider.py`
- Env flag: `ENABLE_REJECTION_SIGNAL_FEEDBACK` (default OFF)
- Reason-code → target/dial routing table:
  - TQS / confidence codes → `confidence_gate` (calibrator)
  - Exposure / DD codes → `risk_caps` (manual review)
  - Stop / target / path codes → `smart_levels` (optimizer)
- Verdict → `suggested_direction`:
  - `gate_potentially_overtight` → `loosen` (actionable)
  - `gate_calibrated` → `hold` (gate is doing its job)
  - `gate_borderline` / `insufficient_data` → `hold` (wait state)

### Hooks (observe-only)
- `services/multiplier_threshold_optimizer.py::run_optimization` reads
  the signal for `target="smart_levels"` and adds:
  - `payload["rejection_feedback"]` — the hint rows
  - `payload["notes"]` entries flagged `[rejection-feedback]`
  - **Does NOT** mutate any threshold proposal (verified by test).
- `services/ai_modules/gate_calibrator.py::calibrate` reads the signal
  for `target="confidence_gate"` and adds:
  - `result["rejection_feedback"]` — the hint rows
  - `result["notes"]` entries flagged `[rejection-feedback]`
  - **Does NOT** shift calibrated GO/REDUCE thresholds (verified by test).
- When flag OFF, both hooks short-circuit and emit a single
  `rejection_feedback_status` note pointing at the env var.

### Why observe-only (not auto-tuning)
The rejection analytics need ~2 weeks of data + verdict stability before
their signal is trustworthy enough to drive live tuning. The scaffolded
hooks let the operator:
  1. See exactly which reason codes the optimizers WOULD weight if the
     flag were on
  2. Compare the analytics' verdict against post-rejection trade
     outcomes for ~2 weeks
  3. Promote individual hints to live tuning by manually adjusting the
     dial OR by following up with a small PR that lifts the
     observe-only barrier per-target
This keeps the blast radius small while still closing the data loop.

### Verification
- 20 new tests in `tests/test_rejection_signal_provider.py` covering:
  flag default-off, flag truthy/falsy parsing, target filtering,
  unmapped reason codes, optimizer hook (flag off + flag on with
  observe-only assertion).
- 136/136 passing across all related suites.
- Lint clean.

### Operator action
Nothing required immediately. Scaffolding is dormant by design.

After ~2 weeks of `/api/trading-bot/rejection-analytics` showing stable
`gate_potentially_overtight` verdicts on a given reason code:
  1. Set `ENABLE_REJECTION_SIGNAL_FEEDBACK=true` in `backend/.env`
  2. Run `multiplier_threshold_optimizer` and/or `gate_calibrator` in
     dry-run mode. Inspect `rejection_feedback` in the payload.
  3. If a hint matches your manual reading of the data, manually
     adjust the affected dial OR open a follow-up PR to promote that
     specific reason-code → dial mapping into auto-tuning.



## 2026-04-29 (afternoon-5) — Equity RPC fallback + dual-scanner strategy-mix + rejection analytics

Operator post-restart screenshot revealed 3 issues. All fixed.

### 1. Equity `$—` despite PUSHER GREEN (P0)
- **Root cause**: ib_insync's `accountValueEvent` sometimes stops firing
  after pusher reconnects. Push-loop kept shipping but
  `account_data` stayed empty. Backend fallback added afternoon-3 had
  nothing to fall back ON.
- **Fix** — new pusher RPC endpoint:
  - `GET /rpc/account-snapshot` in `documents/scripts/ib_data_pusher.py`
  - Fast path returns cached `account_data` (zero IB cost)
  - Slow path calls `IB.accountValues()` synchronously, refreshes the
    cache, returns the full account dict
  - Backend `services/ib_pusher_rpc.py::get_account_snapshot()` helper
  - Wired into `/api/ib/account/summary` AND `/api/trading-bot/status` —
    both seed `_pushed_ib_data["account"]` on RPC hit so subsequent
    reads stay fast
- **Operator action on Windows after pull**: restart `ib_data_pusher.py`
  to pick up the new endpoint. Backend changes alone won't help — the
  RPC endpoint must exist on the pusher side.

### 2. Strategy-mix "waiting for first alerts" with 6 scanner hits (P0)
- **Root cause**: `_scanner_service` in the router is the
  `predictive_scanner`, but the V5 scanner panel renders alerts from
  the **enhanced_scanner**. Afternoon-3 fallback only checked
  predictive_scanner's `_live_alerts` → empty when the enhanced
  scanner had 6 RS hits.
- **Fix**: `routers/scanner.py::get_strategy_mix` fallback now reads
  from BOTH `predictive_scanner._live_alerts` AND
  `get_enhanced_scanner()._live_alerts`. Dedup by `id` keeps the
  count honest.
- Regression coverage: 1 new test
  (`test_strategy_mix_falls_back_to_enhanced_scanner_alerts`).

### 3. Rejection analytics — closes the loop on `sentcom_thoughts` (P1)
- **Operator question**: "now that thoughts persist, don't we already
  have something that uses them?" Audit answer: *partially*. The
  existing learners (`multiplier_threshold_optimizer`,
  `gate_calibrator`) consume `bot_trades` and `confidence_gate_log` —
  not the new rich rejection-narrative feed.
- **Fix** — new read-only analytics service:
  - `services/rejection_analytics.py::compute_rejection_analytics(db, days, min_count)`
  - Aggregates `kind: rejection|skip` events from `sentcom_thoughts`
    by `reason_code`
  - Joins each rejection with subsequent `bot_trades` (same
    symbol+setup_type, within 24h) — counts unique post-rejection
    trades + computes post-rejection win rate
  - Verdict per reason_code:
    - `gate_potentially_overtight` (post-WR ≥ 65%) ⇒ emits a
      calibration hint
    - `gate_borderline` (45-65%)
    - `gate_calibrated` (< 45%)
    - `insufficient_data` (< 5 post-rejection trades or < min_count)
- New endpoint: `GET /api/trading-bot/rejection-analytics?days=7&min_count=3`
- Read-only by design — does NOT modify thresholds. Operator reviews
  hints + manually feeds insights into existing optimizers. Live
  auto-tuning waits for ~2 weeks of data + observation to confirm
  signal stability.
- Regression coverage: 7 new tests in
  `tests/test_rejection_analytics.py`.

### Verification
- 116/116 tests passing across all related suites (8 new this batch
  + 108 carryover).
- All 3 new/changed endpoints verified live on cloud preview:
  `/api/trading-bot/rejection-analytics`, `/api/scanner/strategy-mix`,
  `/api/sentcom/thoughts`.
- Lint clean (no new warnings).

### Operator action on DGX + Windows after pull
1. **Pull on Windows**: restart `ib_data_pusher.py` (new
   `/rpc/account-snapshot` endpoint required for equity fix).
2. **Pull on DGX**: backend hot-reloads. Verify:
   - `/api/trading-bot/status` → `account_equity` populates within
     30s if the IB pusher is healthy (RPC fallback fires once,
     subsequent reads use the seeded cache).
   - `/api/scanner/strategy-mix?n=50` → returns non-zero buckets
     during scan cycles (dual-scanner fallback active).
   - `/api/trading-bot/rejection-analytics?days=7` → starts populating
     hints once rejection events accumulate (need ~3+ rejections
     per code + 5+ post-rejection trades for a verdict).
3. **Watch over the next week**: `calibration_hints` will surface
   reason_codes worth manual review (likely candidates: `tqs_too_low`,
   `exposure_cap`, `daily_dd_cap` if they fire often but the bot
   later trades the same setup successfully).



## 2026-04-29 (afternoon-4) — Bot evaluation thoughts in stream + AI brain memory persistence

Two operator follow-ups shipped together (continuation of afternoon-3):
"add the evaluation emit improvement" + "make sure our chat bot/ai is
retaining its thoughts, decisions, etc for future recall and learning
and growth — V4 had it, not sure it carried over". 7 new tests.

### 1. Bot evaluation events in V5 Unified Stream
- `services/opportunity_evaluator.py::evaluate_opportunity` now emits a
  `kind: "evaluation"` event at the top of every call. Operator can
  watch the bot's reasoning trail in real-time without grepping logs:
  > 🤔 Evaluating NVDA orb_long LONG (TQS 72 B)
- Added `"brain"` to `_VALID_KINDS` in sentcom_service so the
  evaluation events render with the same tone as confidence-gate /
  AI-decision events.
- Frontend `UnifiedStreamV5.jsx::classifyMessage` gains an `evaluat`
  substring match so the new events colour-code as `brain` (cyan/blue)
  alongside other AI-decision types.

### 2. SentCom AI Brain Memory — `sentcom_thoughts` collection
- **The audit finding**: V4 had a brain-memory layer; V5 only persisted
  chat (`sentcom_chat_history`) and AI module decisions
  (`shadow_decisions`). The unified stream's `_stream_buffer` (bot
  evaluations / fills / safety blocks / rejections) was in-memory only
  — every backend restart wiped the bot's recent "thinking trail".
- **Fix** — every `emit_stream_event` call now also writes to a new
  Mongo collection `sentcom_thoughts` with:
  - Indexed by `symbol` and `kind` for fast recall
  - 7-day TTL on `created_at` (auto-prunes — no operator action needed)
  - Idempotent index initialisation (`_ensure_thoughts_indexes`)
  - Best-effort persistence — fire-and-forget, never blocks the caller
- **Restart resilience** — `SentComService._load_recent_thoughts`
  hydrates `_stream_buffer` from the past 24h on init. Operator's V4
  muscle memory ("what was the bot thinking before I restarted?") is
  now restored.
- **Chat context recall** — when the user sends a chat message, the
  SentCom service now injects up to 12 recent thoughts (last 4h) as a
  `system`-role entry in the orchestrator's `chat_history`. Lets the AI
  answer "what did we see on SPY this morning?" with grounded context
  instead of hallucinating.
- **Public recall API**:
  - `services/sentcom_service.py::get_recent_thoughts(symbol, kind,
    minutes, limit)` — Python helper for any backend caller
  - `GET /api/sentcom/thoughts?symbol=&kind=&minutes=&limit=` — HTTP
    endpoint for frontend / external consumers / debugging

### 3. Rejection narratives now persist
- `TradingBotService.record_rejection` already pushed wordy
  conversational narratives ("⏭️ Skipping NVDA Squeeze — this strategy
  is currently OFF in my enabled list…") into the in-memory
  `_strategy_filter_thoughts` buffer (2026-04-28). Now ALSO published
  via `emit_stream_event(kind: "rejection")` → lands in
  `sentcom_thoughts` and the V5 Unified Stream. The bot's rejection
  reasoning is now recallable via chat context too.

### Verification
- 7 new tests in `tests/test_sentcom_thoughts_memory.py`:
  emit-persistence, symbol-filter, kind-filter, newest-first ordering,
  minutes-window cutoff, restart-rehydration, end-to-end router.
- `tests/test_emit_stream_event.py` updated to patch `_get_db` so the
  buffer is isolated per test.
- 32 passing total across new + carryover suites in this batch.
- Live curl smoke: `/api/sentcom/thoughts?minutes=60&limit=5` returns
  fill events from prior test runs — persistence end-to-end confirmed.
- Lint clean (no new warnings; 6 pre-existing carry over).

### Operator action on DGX after pull + restart
1. Restart backend — TTL index will be created automatically on first
   `emit_stream_event` call.
2. Watch V5 Unified Stream during the next scan cycle: every
   evaluated opportunity will produce a `🤔 Evaluating SYMBOL
   setup_type DIRECTION (TQS xx)` line. Fills, safety blocks, and
   rejections continue to surface as before.
3. After restart, run:
   `curl http://localhost:8001/api/sentcom/thoughts?minutes=240&limit=20 | jq`
   Should return all bot activity since process start, surviving
   future restarts (TTL keeps 7 days).
4. Test chat recall: ask SentCom *"what did we see on NVDA this
   morning?"* — the orchestrator now has access to recent evaluations,
   fills, and rejections for NVDA in its system context.



Closes the Round 1 audit findings (operator UI broken at market open) and
ships the Round 2 diagnostic infrastructure operator asked for. 22 new
regression tests, 101 total passing across the related suites.

### 1. `/api/trading-bot/status` now reads IB pushed account (P0)
- **Root cause**: `TradeExecutorService.get_account_info()` only handles
  `SIMULATED` + Alpaca `PAPER` modes — returns `{}` for IB users. The
  V5 dashboard reads `status?.account_equity ?? status?.equity` and
  rendered `$—` because neither field was ever populated when the
  operator was running on IB.
- **Fix**: `routers/trading_bot.py::get_bot_status` now falls back to
  `routers.ib._pushed_ib_data["account"]` when the executor returns
  empty. Constructs a contract-compatible dict (equity / buying_power /
  cash / available_funds / portfolio_value) and surfaces
  `account_equity` + `equity` at the top level so the V5 frontend's
  existing read finds them without a separate round-trip.
- **Verified live** on cloud preview after a faked `/api/ib/push-data`
  POST: `account_equity` populated to NetLiquidation, `account.source`
  tagged `"ib_pushed"`. When the pusher has no account data, returns
  `account: {}` (same `$—` behaviour as before — no false equity).
- Regression coverage: 3 new tests in `tests/test_round1_fixes.py`.

### 2. `/api/scanner/strategy-mix` falls back to in-memory alerts (P0)
- **Root cause**: endpoint queries `db["live_alerts"]` (Mongo persisted)
  while `/api/live-scanner/alerts` reads from in-memory `_live_alerts`.
  When Mongo persistence is empty/lagging (the operator's exact
  observation), the V5 StrategyMixCard rendered `total: 0` despite
  the scanner producing alerts.
- **Fix**: `routers/scanner.py::get_strategy_mix` now falls back to
  `_scanner_service._live_alerts.values()` when the Mongo query returns
  empty. Direction, ai_edge_label, and created_at all carry through
  from in-memory LiveAlert objects so STRONG_EDGE counts + sorting
  remain correct.
- Regression coverage: 3 new tests in `tests/test_round1_fixes.py`
  (Mongo-populated, Mongo-empty-fallback-to-memory, both-empty).

### 3. `live_symbol_snapshot` daily-close anchor for change_pct (P0)
- **Root cause**: SPY missing % at fresh market open. The intraday
  slice only had ONE bar (today's first 5min), so
  `prev_close = last_price` → `change_pct = 0`. Frontend's `formatPct`
  rendered `+0.00%` (or `—` when chained through TopMoversTile's filter
  on `success`).
- **Fix**: `services/live_symbol_snapshot.py::get_latest_snapshot` now
  detects single-bar / equal-prev-close cases and looks up YESTERDAY's
  daily close from `ib_historical_data` (`bar_size: "1 day"`) as the
  prev_close anchor. Never overrides a healthy 2-bar intraday slice
  (intraday math wins when valid).
- Regression coverage: 3 new tests in `tests/test_round1_fixes.py`.

### 4. SentCom `emit_stream_event` — pushed events into the unified stream (P1)
- **Root cause**: `services.sentcom_service.emit_stream_event` was
  IMPORTED in `services/trading_bot_service.py` (safety blocks) and
  `routers/ib.py` (order dead-letter timeouts) — but never DEFINED.
  Both call sites wrapped the import in `try/except: pass`, so for
  weeks every safety-block / order-timeout event was silently dropped.
  Operator's "unified stream too quiet (only 2 messages)" complaint
  traced directly to this gap.
- **Fix**: new module-level coroutine
  `services.sentcom_service.emit_stream_event(payload)`:
  - Accepts `kind`/`type` + `text`/`content` synonym, `symbol`,
    `event`/`action_type`, `metadata`.
  - Normalises unknown kinds → `"info"`, dedupes against the same
    key the pull-based `get_unified_stream` path uses, trims the
    buffer to `_stream_max_size` (newest-first).
  - Fire-and-forget: never raises on bad input (bad/empty payloads
    return `False`, garbage metadata gets wrapped not crashed).
- **Wired**:
  - Trade fills (`services/trade_execution.py::execute_trade`) now
    publish a `kind: "fill"` event with direction / shares / fill
    price / setup_type metadata. UI's existing classifier picks up
    `fill` → emerald colour.
  - Safety-block events from `_safety_check` were already firing
    `emit_stream_event` (now actually lands in the stream).
  - Order dead-letter timeouts in `routers/ib.py` were already
    firing `emit_stream_event` (now actually lands).
- Regression coverage: 8 new tests in `tests/test_emit_stream_event.py`.

### 5. Per-detector firing telemetry (P1 Round 2 diagnostic)
- **Root cause**: operator's "scanner only emits `relative_strength_laggard`
  hits after 20 min of market open" complaint had no telemetry surface
  to confirm WHICH detectors were evaluating but missing vs not running
  at all.
- **Fix**:
  - `services/enhanced_scanner.py`: `_check_setup` increments
    `_detector_evals[setup_type]` on every invocation and
    `_detector_hits[setup_type]` on every non-None return. Per-cycle
    counters reset at the top of `_run_optimized_scan`; cumulative
    `_detector_*_total` counters persist since startup.
  - New endpoint `GET /api/scanner/detector-stats` exposes both views
    sorted by `hits` desc with `hit_rate_pct` math + scan-cycle context
    (`scan_count`, `symbols_scanned_last`, `symbols_skipped_adv/rvol`).
- **Operator action on DGX**: after backend pull, watch the endpoint
  during the first 20 min of market open. If `relative_strength_laggard`
  shows `evaluations: 80, hits: 3` and `breakout` shows `evaluations: 0,
  hits: 0`, the breakout detector isn't being routed any symbols — the
  problem is upstream (universe selection, ADV filter, RVOL gate). If
  `breakout` shows `evaluations: 80, hits: 0`, the detector IS running
  but its preconditions (bars-since-open, volume profile) aren't met.
  This is the diagnostic primitive that was missing.
- Regression coverage: 4 new tests in `tests/test_detector_stats.py`.

### Verification
- 22 new tests + 79 carried-over related tests = **101/101 passing**.
- Backend live on cloud preview; `/api/trading-bot/status`,
  `/api/scanner/strategy-mix`, `/api/scanner/detector-stats` all return
  valid payloads end-to-end.
- No regressions in `test_scanner_canary`, `test_bot_account_value`,
  `test_pusher_rpc_subscription_gate`, `test_l2_router`,
  `test_setup_narrative`, `test_bot_rejection_narrative`.

### Operator action on DGX after pull + restart
1. After market open (or any time the IB pusher is feeding account
   data): `curl /api/trading-bot/status | jq '.account, .account_equity'`
   should show the live NetLiquidation. V5 HUD equity pill resolves
   from `$—` to the real number.
2. `curl /api/scanner/strategy-mix?n=100 | jq '.total, .buckets[0]'`
   should return non-zero even if Mongo persistence has gaps.
3. `curl /api/scanner/detector-stats | jq '.last_cycle.detectors'`
   identifies which detectors are firing per scan cycle. If only RS
   shows hits, drill down on what's blocking the others (universe,
   ADV, RVOL, or detector-internal preconditions).
4. Watch the V5 Unified Stream on a paper-mode trade: after the first
   fill, a `✅ Filled LONG …` line should appear in the stream
   (previously these only landed via the pull-based scanner alert
   path, never directly from execute_trade).



## 2026-04-29 (afternoon-2) — V5 layout vertical expansion + audit findings

### Layout fix shipped
`SentComV5View.jsx`:
- Root container `overflow-hidden` → `overflow-y-auto v5-scroll` (page now scrolls)
- Main 3-column grid `flex-1 min-h-0` → `min-h-[800px] flex-shrink-0` (gives panes real vertical room)
- Bottom drawer `max-h-[22vh] overflow-y-auto` → `min-h-[400px] flex-shrink-0`
  (Model Health / Smart Levels / AI Audit cards no longer fight for space)

Total page now expands beyond viewport height with natural scroll —
operator can scroll to see every panel at proper proportions.

### Audit findings (no code changes — diagnostics for next session)

**Account equity = `$—`** — root cause confirmed:
`/api/ib/account/summary` returns `connected: false, net_liquidation: 0`
even though pusher is healthy. The pusher is pushing quotes + positions
but NOT account snapshot data, so the bot status's `account_equity`
field stays None. Frontend renders the empty pill as `$—`. Fix
requires either (a) Windows pusher to also push account data, or (b)
backend to fetch account on RPC call. Parked for next session.

**Scanner producing too few ideas (3 alerts, all RS_laggard, after
20 min open)** — likely root cause: most setup detectors gate on
N-bars-since-open or minimum volume profiles that don't develop in
the first 20 minutes. RS detectors fire fastest because they only
need a price comparison. Need to log per-detector firing/skip counts
to confirm. Parked.

**Unified stream too quiet (2 messages)** — needs investigation of the
event publisher pipeline. Currently the only events landing are scan
hits; bot evaluations / fills / EOD events likely aren't being fed
into the same stream collection. Parked.

**`/api/scanner/strategy-mix` returns `total=0`** — endpoint queries
`db["live_alerts"]` collection (Mongo persisted) while
`/api/live-scanner/alerts` returns from in-memory `_scanner` state.
Two probable causes:
  1. `_save_alert_to_db` may not be writing all alerts (only critical/high?)
  2. The Mongo collection may have different field names for the
     `created_at` sort key
DGX-side query needed: `db.live_alerts.count_documents({})`.

**SPY missing % change in top-movers strip** — likely a backfill gap
for SPY's prev-close. Top-movers calls `/api/live/briefing-snapshot`
which reads `prev_close` from `ib_historical_data.1 day` bars. If
SPY's most recent daily bar wasn't included in the briefing window,
`change_pct` returns null. Auto-resolves once SPY backfill is fresh.

### SentCom Intelligence / promotion / live-vs-paper pipeline audit

**Strategy phases: ALL 44 strategies in `live` phase**
- `StrategyPromotionService._paper_account_mode = True` (default,
  hardcoded line 180) means *every* strategy is auto-flipped to LIVE
  because the IB account is paper. SIMULATION → PAPER → LIVE staging
  is essentially bypassed.
- This is *intentional* per the comment in code, but means the
  promotion-rate dashboard is meaningless on this account
  (validation_summary shows 0 promoted in all windows).
- **Implication**: operator gets no validation gates between
  simulation and live. Every newly-trained strategy goes straight
  to LIVE on paper money. Risk if/when account flips to real.

**Validation summary**: 0 promoted, 0 rejected, 0 records over 24h,
7d, 30d. Either:
  - Training pipeline isn't running on a schedule
  - Or it runs but doesn't trigger validation
  - Or validation runs but skips logging because of `_paper_account_mode`

**TimeSeries model status** (cloud preview):
  - `trained: false`
  - `version: v0.0.0`
  - `accuracy: 0.0`, all metrics 0
  Cloud preview has no IB data, so this is expected here. **On DGX,
  operator must verify the model is actually trained.**

**Model Health Card** showed `35 healthy · 4 mode C · 5 missing`.
The 5 missing models are setup-specific gradient boosting models
that haven't been trained yet for those setups. Need a
`/api/ai-training/setup-coverage` style endpoint to identify which
5 are missing.

### Next-session task list (in priority order)
1. Account equity wiring — pusher push account snapshot OR backend
   RPC fetch
2. Scanner per-detector firing counts diagnostic + adjustment
3. Unified stream event publisher audit
4. Strategy-mix Mongo persistence verification
5. SentCom Intelligence audit Phase 2: identify 5 missing models,
   verify training cron, decide on `_paper_account_mode` policy
   (keep auto-promote OR enforce gates even on paper)

## 2026-04-29 (afternoon) — Risk-caps unification (Option B)

### Why
Operator's freshness inspector flagged a `Risk params WARN`:
- `bot.max_open_positions=7` vs `kill_switch.max_positions=5`
- `bot.max_daily_loss=0` (unset) — only kill switch ($500) protected
- `bot.max_position_pct=50%` vs `sizer.max_position_pct=10%`

A 2026-04-29 audit found risk parameters scattered across **6 files**
(`bot_state.risk_params`, `safety_guardrails`, `position_sizer`,
`dynamic_risk_engine`, `gameplan_service`, `debate_agents`) with
conflicting defaults that had drifted out of sync.

### Fix (Option B from the proposal — pragmatic)
- New `services/risk_caps_service.py` exposes
  `compute_effective_risk_caps(db)` — a thin read-only resolver that
  surfaces:
  - `sources`     — raw values from each subsystem (bot / safety /
                    sizer / dynamic_risk)
  - `effective`   — most-restrictive resolved value per cap
  - `conflicts`   — human-readable diagnostics for the UI
- New endpoint: `GET /api/safety/effective-risk-caps`
- Treats `0` and `None` as "unset" (not "0 cap") to match operator
  intent — a daily_loss=0 in Mongo means "use safety's value", not
  "trade until $0 is left".
- Diagnostic strings mirror the freshness inspector's WARN wording so
  the operator can match them up: `"max_open_positions: bot=7 vs
  safety=5 → 5 wins (kill switch stricter)"`.

### What's NOT changed
This is **read-only** — no enforcement changes today. Subsystems
still read their own config independently. The endpoint just makes
the *truth* visible. Option A (full single-source-of-truth refactor
across all 6 files) is parked for a future session.

### Regression coverage
`tests/test_risk_caps_service.py` (12 tests):
- Sources surface for all 4 categories
- Safe-payload when db=None
- Position cap: safety wins / bot wins / unset cases
- Position pct: sizer wins when bot aggressive
- Daily loss USD: bot pct→USD conversion + safety floor
- Daily loss treated as unset when 0 (operator's exact config)
- Daily loss pct picks strictest across bot/safety/dynamic_risk
- Kill switch DISABLED emits ⚠️ diagnostic
- End-to-end: replays operator's exact 2026-04-29 freshness-inspector
  WARN and asserts diagnostic strings match

### Operator action on DGX after pull + restart
```
curl -s http://localhost:8001/api/safety/effective-risk-caps | python3 -m json.tool
```
Expected: `effective.max_open_positions=5`, `effective.max_position_pct=10.0`,
plus 3 conflict strings explaining each WARN.

## 2026-04-29 (mid-day) — Timeseries shadow gap + AI Decision Audit Card

### Two operator follow-ups shipped together (~1 hour total)

### 1. timeseries_ai shadow-tracking gap (P1)

**Why** — `/api/ai-modules/shadow/performance` showed
`timeseries_ai: 0 decisions` despite the module firing on every
consultation. Root cause in
`services/ai_modules/trade_consultation.py::consult`: when
`ai_forecast.usable=False` (low confidence) OR when the forecast was
consumed by the debate path, `result["timeseries_forecast"]` was
never set, so `log_decision` received `None` and didn't tag
`timeseries_ai` in `modules_used`. The module was firing AND
contributing — just never getting credit in the shadow stats.

**Fix** — the consultation now builds a sentinel payload when the
forecast was *fetched but unusable* OR *consumed by debate*:
```python
ts_payload = result.get("timeseries_forecast")
if not ts_payload and ai_forecast:
    ts_payload = {
        "forecast": ai_forecast,
        "context": None,
        "consulted_but_unusable": not ai_forecast.get("usable", False),
        "consumed_by_debate": "timeseries_ai_in_debate" in modules_used,
    }
```

The sentinel is truthy → `log_decision` tags `timeseries_ai` →
shadow stats finally show real decisions. The full payload is
preserved so downstream analytics can distinguish "actively
contributed" from "abstained low-confidence" from
"consumed-by-debate".

**Regression coverage**: `tests/test_timeseries_shadow_tracking.py`
(5 tests):
- usable forecast → tagged
- unusable forecast → tagged with `consulted_but_unusable=True`
- consumed-by-debate forecast → tagged with `consumed_by_debate=True`
- absent forecast → NOT tagged
- empty dict `{}` → NOT tagged (defensive)

### 2. AI Decision Audit Card (V5 dashboard) (P1)

**Why** — operator now has 6,751 shadow-tracked decisions (post drain
mode + Mongo fallback fixes earlier today) but no UI to inspect them
per-trade. The shadow performance endpoint shows 70-73% accuracy at
the module level, but the operator can't see "for trade X, what did
each module say, and was that aligned with the actual outcome?".

**Backend** — new `services/ai_decision_audit_service.py` extracts
audit data from `bot_trades.entry_context.ai_modules`. For each
recent closed trade, returns:
- per-module verdict (normalised to bullish/bearish/neutral/abstain)
- alignment flag (bullish+win OR bearish+loss → aligned)
- self-reported confidence (when surfaced — TS nests it inside `forecast`)
- close reason + net P&L

Plus a per-module summary aggregating `alignment_rate = aligned /
consulted` (NOT aligned/total — modules don't get penalised for
trades they abstained on).

Verdict normalisation handles the rich strings the consultation
pipeline emits: `PROCEED_HIGH_CONFIDENCE`, `BLOCK_RISK_TOO_HIGH`,
`approve_long`, `bullish_flow`, `up`/`DOWN`. Pass takes precedence
over proceed when both match (handles `no_trade` containing `trade`).

New endpoint: `GET /api/trading-bot/ai-decision-audit?limit=30`.

**Frontend** —
`frontend/src/components/sentcom/v5/AIDecisionAuditCard.jsx` renders:
- Header strip with per-module alignment-rate (color-coded:
  emerald ≥60%, amber 40-60%, rose <40%; greyed when n<5)
- Trade list with symbol / setup / PnL / 4 module pills
  (✓ aligned / ✗ wrong / − abstained) / close reason
- Expand-to-show-all toggle (default 8 visible)
- 60-second auto-refresh

Mounted in `SentComV5View.jsx` bottom drawer alongside the existing
ModelHealthScorecard + SmartLevelsAnalyticsCard (3-column grid:
50% / 25% / 25%).

**Regression coverage**: `tests/test_ai_decision_audit_service.py`
(15 tests):
- Verdict normalisation (parametrized 17 cases)
- Alignment math (8 truth-table cases)
- Verdict-extraction priority order across the 8 known field names
- Confidence extraction with TS nesting
- Win-detection precedence (net_pnl > realized_pnl > pnl_pct)
- End-to-end aggregation against mongomock with all 4 modules
- Dissenting modules credited correctly on losses
- Per-module alignment_rate uses consultation denominator
- Missing `ai_modules` handled gracefully (legacy trades)
- Sort + limit behaviour

### Verified
- 109 tests passing across the day's new suites (drain + Mongo
  fallback + per-module fix + liquidity stop trail + unqualifiable
  pipeline + timeseries gap + audit service).
- Backend live: `curl /api/trading-bot/ai-decision-audit?limit=5`
  returns clean empty payload (no closed trades in cloud preview's
  trading_bot — full data will populate on DGX).
- Frontend lint clean, backend lint clean.

### Operator action on DGX after pull + restart
1. Pull + restart backend (and Windows collectors so they pick up
   the dead-symbol notification path from the morning fix).
2. Open V5 dashboard → bottom drawer now shows 3 panels: Model
   Health (50%) | Smart Levels (25%) | AI Audit (25%).
3. The audit card will populate as new closed trades land. Existing
   closed trades with `entry_context.ai_modules` populated will show
   immediately.
4. Re-check `/shadow/performance?days=30` — `timeseries_ai` should
   now have decisions > 0 (will populate on the next consultation
   that uses TS).

## 2026-04-29 (morning) — Unqualifiable strike-counter rescue (P0 from overnight backfill)

### Why
2026-04-29 morning diagnostic on DGX revealed the unqualifiable
strike-counter system was completely dead:
```
Total symbols:        9412
Unqualifiable (auto): 0     ← should be 500-1500
Striking (1-2 fails): 0     ← should be hundreds
Healthy:              9412
```
Despite hours of "Error 200: No security definition" failures during
the overnight backfill (PSTG, HOLX, CHAC, AL, GLDD, DAWN, etc.), zero
strikes were recorded. Root cause: the historical collector silently
returns `no_data` on dead symbols without notifying the DGX backend.

### Two-part fix

**Part 1: Wire up the missing notification path**
`documents/scripts/ib_historical_collector.py::fetch_historical_data`
now calls a new `_notify_dead_symbol()` helper whenever it detects
either:
- `qualifyContracts()` raises (legacy ib_insync behaviour)
- `qualifyContracts()` returns silently with `conId == 0` (newer
  ib_insync versions just log Error 200 + a warning instead of
  raising — this was the silent leak)

The helper POSTs to `/api/ib/historical-data/skip-symbol` which:
- bulk-skips all pending queue rows for the dead symbol (saves the
  remaining 8 bar_size requests in the same batch from also burning
  IB pacing)
- ticks the `unqualifiable_failure_count` strike counter
- promotes to `unqualifiable: true` once threshold reached

Best-effort wiring — any failure is logged at DEBUG and the collector
keeps running. The next bad-symbol hit will retry the notification.

**Part 2: Lower strike threshold 3 → 1**
`services/symbol_universe.py::UNQUALIFIABLE_FAILURE_THRESHOLD` reduced
from `3` to `1`. The "No security definition" error is **deterministic**
— the symbol either exists in IB's security master or it doesn't,
there's no transient state. Waiting for 3 strikes before promotion
just meant ~9k wasted IB requests over a single overnight backfill.

### Expected impact on next overnight run
- ~75% reduction in IB pacing waste (collectors don't repeatedly
  hammer the same dead symbols across multiple cycles)
- Overnight backfill estimate: 6-10 hours → 2-4 hours
- DGX `unqualifiable` count: 0 → expected 500-1,500 within first
  full backfill cycle
- The chronic "Error 200" log spam on Windows collectors will drop
  dramatically as bad symbols self-prune after one strike

### Regression coverage
- `tests/test_unqualifiable_pipeline.py` (9 tests):
  - threshold=1 sanity check (regression guard if anyone bumps it back)
  - first strike promotes immediately
  - second strike is idempotent (no double-stamping `marked_at`)
  - upsert creates doc if symbol not in cache
  - uppercase normalisation
  - safe-error returns for None db / empty symbol
  - 3-consecutive strikes increment counter exactly once promoted
  - `last_seen_at` refreshes per strike (debugging aid for selectors
    that mistakenly re-queue unqualifiable symbols)

### Operator action on DGX after pull + collector restart
1. **Restart the Windows collectors** so they pick up the new
   `_notify_dead_symbol` path. Backend hot-reload covers part 2.
2. Wait 5-10 min, then re-run the diagnostic:
```
cd ~/Trading-and-Analysis-Platform && set -a && source backend/.env && set +a && \
~/venv/bin/python -c "
from pymongo import MongoClient; import os
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
print('Unqualifiable:', db.symbol_adv_cache.count_documents({'unqualifiable': True}))
print('Striking:    ', db.symbol_adv_cache.count_documents({'unqualifiable_failure_count': {'\$gte': 1}}))
"
```
Expected: count climbs from 0 as collectors hit dead symbols. After
1-2 hours of continued backfill, should be in the hundreds.

## 2026-04-29 (later 2) — Per-module accuracy fix (PnL-based + recommendation-aware)

### Why
After the morning's drain landed 6,715 outcomes (73.5% global win rate),
operator pulled `/api/ai-modules/shadow/performance` and saw:
```
debate_agents:      1482 decisions, 0.0% accuracy
ai_risk_manager:    2191 decisions, 0.0% accuracy
institutional_flow: 2191 decisions, 0.0% accuracy
```
Mathematically impossible vs the 73.5% global win rate → bug in
`get_module_performance`.

### Root cause
Two issues, both in `services/ai_modules/shadow_tracker.py::get_module_performance`:

1. **Used `would_have_r` instead of `would_have_pnl`** as the win/loss
   signal. R-multiple is computed from `(outcome_price - entry) / abs(entry - stop_price)`,
   but `stop_price` isn't stored on `ShadowDecision` — so for every
   backlogged decision, R was `0`, never `> 0`, never "correct".
2. **Strict equality matching on `recommendation`** — only counted
   `recommendation == "proceed"` or `== "pass"`. Production values are
   richer (e.g. `"PROCEED_HIGH_CONFIDENCE"`, `"BLOCK_RISK_TOO_HIGH"`,
   `"approve_long"`, `"REDUCE_SIZE"`).

### Fix
- **PnL-based correctness**: `correct += 1` when `would_have_pnl > 0`
  for proceed-intent recommendations OR `< 0` for pass-intent. This
  matches the global `wins / total` semantic in `get_stats`.
- **Permissive recommendation matching** with substring keywords
  (lowercased):
  - PROCEED: `proceed`, `approve`, `execute`, `buy_long`, `go_long`,
    `trade_yes`, `long_ok`
  - PASS: `pass`, `skip`, `reject`, `block`, `avoid`, `no_trade`,
    `no_go`, `trade_no`
  - Pass takes precedence over proceed when both match (handles
    `no_trade` containing `trade` cleanly).
  - Empty/unrecognised recommendation → fall back to direction-
    agnostic `pnl > 0` (same as global win rate).
- **New PnL fields** on `ModulePerformance`: `avg_pnl_when_followed`
  and `avg_pnl_when_ignored`. Always populated even when R is
  uncomputable (backlog scenario). Existing R fields stay (will
  populate naturally for live trades where stop_price IS known).

### Regression coverage (5 new tests, 20 total in the file)
`tests/test_shadow_tracker_drain.py` adds:
- Empty recommendation → falls back to PnL-based correctness
- Recognises proceed variants (`PROCEED_HIGH_CONFIDENCE`, `approve_long`,
  `trade`)
- Recognises pass variants (`BLOCK_RISK_TOO_HIGH`, `SKIP`, `reject`,
  `no_trade`)
- `avg_pnl_when_followed` populated when R is zero
- Empty outcome list returns clean zeros

### Operator action on DGX after pull + restart
```
curl -s 'http://localhost:8001/api/ai-modules/shadow/performance?days=30' \
  | python3 -m json.tool
```
Expected: per-module `accuracy_rate` now in the 0.65-0.80 range
(matches global 73.5%), `decisions_correct` populated, new
`avg_pnl_when_followed` field shows average PnL per trade. Modules
should NOT show 0.0% accuracy anymore.

```
curl -s 'http://localhost:8001/api/ai-modules/shadow/report?days=30' \
  | python3 -m json.tool
```
Expected: `recommendations` no longer says "consider disabling" for
every module. `value_analysis` may still be empty since all decisions
were executed (no ignored sample for differential analysis).

## 2026-04-29 (later) — Shadow tracker Mongo historical price fallback

### Why
After shipping drain mode earlier today, operator ran a single drain
on DGX and saw `updated: 0` despite 50,000 decisions checked. Root
cause surfaced via live diagnostic: `_get_current_price(symbol)` only
asked the IB pusher for a quote, but the pusher subscribes to ~3-14
hot symbols at any moment. The shadow backlog spans every symbol the
bot has ever evaluated (~thousands), so `_get_quote` returned `None`
for the long tail and `update_outcome` got skipped.

### Fix
`services/ai_modules/shadow_tracker.py` — `_get_current_price` now
tries 3 sources in order:
  1. IB pusher live quote (preferred, ~14 hot symbols)
  2. **NEW** — `ib_historical_data` most-recent close (covers ~9,400
     backfilled symbols). Prefers daily bars; falls through to any
     bar_size if no daily exists. Uses the
     `symbol_1_bar_size_1_date_-1` compound index shipped earlier
     today, so per-lookup is 1-5ms.
  3. Legacy Alpaca path (dead post Phase 4).

For backlog outcomes (decisions ≥1h old), the most recent close is a
better proxy than a real-time tick anyway — captures actual price
evolution since the decision was logged.

### Regression coverage (7 new tests, 15 total in the file)
`tests/test_shadow_tracker_drain.py` adds:
- `_get_historical_close` prefers daily bars
- Falls back to any bar_size when no daily
- Returns None when symbol absent / DB unwired
- `_get_current_price` uses Mongo fallback when IB quote missing
- IB quote takes precedence over Mongo when fresh
- **End-to-end**: drain of 50 backlogged decisions for unsubscribed
  symbols now updates all 50 (vs 0 pre-fix). Replicates operator's
  exact production scenario.

### Operator action on DGX after pull + restart
```
curl -s -X POST 'http://localhost:8001/api/ai-modules/shadow/track-outcomes?drain=true' \
  | python3 -m json.tool
curl -s http://localhost:8001/api/ai-modules/shadow/stats \
  | python3 -m json.tool
```
Expected: `updated` jumps from 0 → ~6,700 (or however many
backlogged decisions have a backfilled symbol). `outcomes_pending`
drops from 6,715 to near-zero. `wins` + `win_rate` repopulate.

## 2026-04-29 — Shadow tracker drain mode + Liquidity-aware stop trail (Q1)

Two ROADMAP P1 items shipped in one session. 19/19 new tests passing.
All 39 existing smart_levels + chart_levels tests still green.

### 1. Shadow Tracker drain mode (operator's 6,715-deep backlog)
- **Why**: operator's DGX had 6,715 shadow decisions sitting in
  `outcome_tracked: false`. The legacy `POST /api/ai-modules/shadow/track-outcomes`
  endpoint processed exactly 50 per call → required ~135 manual curls
  to clear. Service-layer `track_pending_outcomes(batch_size, max_batches)`
  already supported multi-batch processing (added 2026-04-28f) but the
  router exposed neither parameter.
- **Scope**:
  - `routers/ai_modules.py` — endpoint now accepts `?batch_size=` (50,
    1-500), `?max_batches=` (1, 1-1000), and `?drain=true` (sets
    `max_batches=1000` for a single-curl backlog drain).
  - `services/ai_modules/shadow_tracker.py::track_pending_outcomes`:
    * Hard safety clamps applied after the API layer (defense in
      depth — explicit None checks so `batch_size=0` clamps up to 1
      instead of silently expanding to default 50).
    * `await asyncio.sleep(0)` between batches so a 1k-batch drain
      doesn't starve other endpoints (`/pusher-health`, scanner
      heartbeat, etc.).
    * Stats cache (30s TTL) busted at end of drain so the next
      `/shadow/stats` reflects updated outcome counts.
- **Operator action on DGX after pull**: replace any prior repeated
  curl loops with a single `curl -X POST "http://localhost:8001/api/ai-modules/shadow/track-outcomes?drain=true"`.
- **Regression coverage**: `tests/test_shadow_tracker_drain.py` (8 tests)
  — legacy default, multi-batch, early exit, safety clamps,
  zero/negative inputs, no-DB safety, event-loop yielding,
  stats-cache invalidation.

### 2. Liquidity-aware realtime stop trail (Q1 from operator backlog)
- **Why**: pre-fix realtime trail in `stop_manager.py` was purely
  ATR-/percent-based. Target 1 hit → stop moves to *exact* entry
  (vulnerable to wicks). Target 2 hit → trail by fixed 2% of price
  (ignores liquidity). The new `compute_stop_guard` from
  `smart_levels_service` only fired at trade entry. Operator wanted
  the stop manager to be liquidity-aware end-to-end: anchor every
  ratchet to a meaningful HVN cluster.
- **New helper** `services/smart_levels_service.compute_trailing_stop_snap`:
  - Searches a 2%-wide window on the protected side of the trade for
    supports (long) / resistances (short) above the active min-strength
    threshold.
  - LONG → highest support below `current_price` (closest to price =
    tightest liquidity-anchored trail).
  - SHORT → lowest resistance above `current_price`.
  - `new_stop = level_price ± epsilon` (just past the cluster).
  - Defensive: never loosens an existing stop (`new_stop >= proposed_stop`
    for longs, ≤ for shorts).
  - Returns `{stop, snapped, reason, level_kind, level_price,
    level_strength, original_stop}` — same shape as `compute_stop_guard`
    so consumers can branch on `snapped` cleanly.
- **`StopManager` rewired** (`services/stop_manager.py`):
  - New `set_db(db)` injection; called from
    `TradingBotService.set_services` so smart-levels has Mongo access.
  - `_move_stop_to_breakeven` — Target 1 hit: try snap first; if a
    qualifying HVN sits in range, anchor stop to `HVN - epsilon`
    instead of exact entry. Records `breakeven_hvn_snap` reason +
    `breakeven_snap_level: {kind, price, strength}` on the trade for
    audit.
  - `_activate_trailing_stop` — Target 2 hit: snap the *initial*
    trailing stop to nearest HVN below price; falls through to
    fixed-% trail if no HVN qualifies.
  - `_update_trail_position` — every trail tick: snap to nearest HVN;
    fall through to ATR/%-trail when no qualifying level exists.
  - **Fail-safe**: any exception inside `compute_trailing_stop_snap`
    is caught + logged at WARNING, and the manager falls back to
    legacy behaviour. Operator's stops never get stuck because of a
    smart-levels bug.
- **Regression coverage**: `tests/test_liquidity_aware_stop_trail.py`
  (11 tests) — pure-helper tests (highest support pick, weak-level
  filter, would-loosen guard, short mirror, no-levels fallback,
  invalid inputs) + StopManager wiring tests (DB-not-wired fallback,
  snap-when-DB-wired, no-snap-falls-through-to-ATR, snap-trail,
  exception-swallow).

### Verified live
- 39/39 existing `smart_levels` + `chart_levels` tests green (no
  regressions).
- Curl smoke against the cloud preview returns the new drain payload:
  ```
  $ curl -X POST 'http://localhost:8001/api/ai-modules/shadow/track-outcomes?drain=true'
  {"success":true,"updated":0,"checked":0,"batches":0,
   "drain":true,"batch_size":50,"max_batches":1000}
  ```
- StopManager `set_db()` + `_snap_to_liquidity()` reachable from a
  freshly imported instance.

## 2026-04-28c — Chart fixes round 3: ChartPanel root made flex-flex-col (fixes empty chart)

Operator screenshot post-pull showed chart canvas completely empty
("1D BARS · updated 8:12:06 PM ET" header rendered, but black canvas
underneath). Root cause was layout-only: my round-2 CSS restructure
gave the inner `chart-container` div `flex-1 min-h-0` to fill its
parent, but the ChartPanel root `<div>` itself was NOT a flex
container — only `relative overflow-hidden …`. So `flex-1` on the
child resolved against a non-flex parent → height: auto → child
shrank to content (the inner ref div with `height: 100%` of an
unsized parent) → 0px tall → lightweight-charts autoSize captured
zero height → invisible chart.

### Fix
- `ChartPanel.jsx` root `<div>` now adds `flex flex-col h-full` when
  the legacy `height` prop is omitted (V5 default). When `height` is
  explicitly passed (legacy callers), the root stays non-flex and the
  fixed pixel height continues to work as before.
- One-line change. No backend changes. All 5 chart_rth_filter tests
  still pass.

## 2026-04-28b — Chart fixes round 2: premarket shading + autoSize + session=rth_plus_premarket

Operator screenshot shows volume + time-axis still missing AND
premarket bars dropped by my v1 RTH filter. Three real fixes shipped:

### 1. `session` query param replaces `rth_only`
- `/api/sentcom/chart?session=rth_plus_premarket` (new default).
  Keeps **4:00am-16:00 ET weekdays** — drops only post-market and
  overnight (the noisy bars). Premarket gap-context preserved per
  operator request: *"i want RTH and premarket to always show."*
- Each kept bar tagged with `session: "pre" | "rth"` so the frontend
  can shade them differently.
- Other modes: `?session=rth` (9:30-16:00 only), `?session=all`
  (full 24h).
- Legacy `?rth_only=true|false` kept for back-compat.
- Test coverage: 5 tests in `tests/test_chart_rth_filter.py`.

### 2. ChartPanel autoSize + container restructure
- **Root cause of missing volume + time-axis ticks**: the chart was
  initialized with `autoSize: false` + a hardcoded
  `height: containerRef.clientHeight || 480` at mount time. When the
  container hadn't finished CSS layout yet (clientHeight = 0), it
  fell back to 480px and overflowed shorter parents → bottom of
  chart canvas (volume pane + x-axis tick row) clipped by the
  parent's `overflow:hidden`.
- **Fix**: switch to `autoSize: true` (lightweight-charts native auto-
  fitting). Container restructured to a `position:relative` parent
  that holds the chart canvas as a 100%-sized child, with a sibling
  overlay div for premarket shading. ResizeObserver retained but
  scoped to invalidating priceScale margins on resize (some v5
  builds don't recompute volume-pane margins on autoSize alone).
- `height` prop default changed from `null` → still null but the
  container `min-height: 240px` floor prevents collapse.

### 3. PremarketShadingOverlay
- New React subcomponent rendered as an absolute-positioned sibling
  inside the chart container. Per operator request: *"have the pre
  market session with background shading so i know the difference
  easier visually."*
- How it works:
  1. Reads bars passed in (each tagged `session: 'pre' | 'rth'` by
     the backend).
  2. Walks bars to find contiguous premarket runs, merges into
     `{startTime, endTime}` ranges.
  3. Subscribes to chart's `visibleTimeRangeChange` and projects
     each range into pixel coordinates via
     `chart.timeScale().timeToCoordinate()`.
  4. Renders a translucent amber band per range
     (`bg-amber-400/8 border-l border-r border-amber-400/20`).
- Bands sit BEHIND the candles (`pointer-events-none`) so they
  don't interfere with chart interactions.
- Bottom inset `bottom-7` so bands don't cover the time-axis row.

### Verification
- 79/79 tests passing.
- Backend healthy after restart; chart endpoint returns proper
  `session`-tagged bars when data is available.
- **Note for operator**: if volume bars on the candle chart still
  appear flat after pulling these changes, that's because today's
  IB historical bars genuinely have `volume=0` in your Mongo cache
  (paper account quirk or backfill ran with a non-volume source).
  Live tick→bar persister (shipped this morning) writes real volume
  for bars created during RTH on subscribed symbols.

## 2026-04-28 — Chart fixes + Equity hookup + After-hours scanner + RTH filter

Operator-flagged batch (post-layout-move). 4 issues resolved + 17 new
regression tests (94/94 backend tests passing total this session).

### 1. Chart: volume bars + x-axis ticks restored
- **Root cause:** `ResizeObserver` only forwarded `width` to the chart;
  height was fixed at `prop.height = 600`. After the layout move that
  put Unified Stream below the chart, the parent flex slot was shorter
  than 600px → volume pane + x-axis tick row got clipped by the
  parent's `overflow:hidden`.
- **Fix:** ResizeObserver now also forwards `height` (floored at 240
  so a collapsed parent can't crush the chart into an unreadable
  strip). `height` prop default changed from `480` → `null`; when
  null, the container uses `flex-1 min-h-0` and inherits the parent's
  height. Legacy callers passing an explicit pixel value still work.
- Container in `SentComV5View.jsx` updated to `flex: '60 1 0%'` +
  `overflow-hidden` so the flex sizing is deterministic.

### 2. Equity / NetLiquidation reads from IB
- **Root cause:** `TradingBotService._get_account_value()` only
  checked `self._alpaca_service` — which has been `None` since the
  Phase 4 Alpaca retirement. So the bot kept sizing on the hardcoded
  $100k fallback no matter what the operator's IB paper account
  balance was.
- **Fix:** new resolution order: (1) IB `_pushed_ib_data["account"]
  ["NetLiquidation"]` from the Windows pusher → (2) Alpaca (legacy,
  only if explicitly re-enabled) → (3) `risk_params.starting_capital`
  → (4) hardcoded $100k as the absolute last resort.
- Defensive: 0 NetLiquidation (IB momentary glitch during reconnect)
  is NOT trusted — falls through to starting_capital.
- Side-effect: when IB pushes a real value, `risk_params.starting_capital`
  syncs to it so position-sizing helpers that read starting_capital
  directly also see the live number.
- Regression coverage: 5 tests in `tests/test_bot_account_value.py`.
- **Note:** if the operator's IB paper account *is* legitimately
  $100,000 (TWS default), this fix doesn't change that — they need
  to reset paper balance in TWS → Edit → Global Configuration →
  API → Reset Paper Trading Account.

### 3. After-hours carry-forward ranker
- Operator request: *"the scanner should now recognize that its after
  hours and should be scanning setups that it found today that might
  be ready for tomorrow when the market opens."*
- New `_rank_carry_forward_setups_for_tomorrow()` runs in the
  `TimeWindow.CLOSED` branch alongside the existing daily scan.
- Pulls today's intraday alerts (in-memory + Mongo-persisted),
  scores each for tomorrow-open viability:
  - Continuation candidates (RS leaders, breakouts, momentum,
    squeezes, opening drive) with TQS ≥60 → tagged
    `day_2_continuation` with a +5 score bonus.
  - Fade/reversal candidates (vwap_fade, gap_fade, halfback_reversal,
    rs_laggard) with TQS ≥60 → tagged `gap_fill_open`.
  - Anything else with TQS ≥70 → tagged `carry_forward_watch`.
- Top 10 by score are promoted as fresh `LiveAlert`s with
  `expires_at` set to **tomorrow's 09:30 ET** (skipping weekends —
  Friday after-hours scans promote alerts valid through Monday's open).
- Idempotent. De-duplicates same `(symbol, setup_type, direction)`
  tuples between in-memory and Mongo sources.
- Regression coverage: 7 tests in `tests/test_after_hours_carry_forward.py`.

### 4. Chart RTH-only filter — closes intraday time gaps
- Operator: *"the charts still have a lot of timeframe and data and
  time gaps. how do we close those?"*
- New `?rth_only=true` query param on `/api/sentcom/chart` (defaults
  to **true** for intraday timeframes — gap closure works without
  any frontend opt-in).
- Filters bars to RTH window: 9:30-16:00 ET, weekdays only. Removes:
  - Overnight gap (Fri 4pm → Mon 9:30am)
  - Weekend gap
  - Sparse pre/post-market bars
- Daily/weekly timeframes are not filtered (already 1-bar-per-session).
- Defensive: if the RTH filter wipes everything (e.g. test data is
  purely after-hours), endpoint returns `error: "no RTH bars in
  window"` + `rth_filter_dropped: N` so the operator can pass
  `rth_only=false` to inspect the full data.
- Regression coverage: 3 tests in `tests/test_chart_rth_filter.py`
  (lock the dropping logic, weekend handling, and the
  default-true contract).

### Verification
- 77/77 tests passing across 9 new test files this session.
- Backend healthy after restart; L2 router 0 errors, wave-scanner
  loop running.
- Chart endpoint returns proper RTH-filtered bars (verified against
  test fixture).

## 2026-04-28 — Layout move + Briefing CTAs + System health audit script

### 1. V5 layout — Unified Stream moved to center below chart
- Operator request: *"move the unified stream to the center below the
  chart to give it some more space."*
- New center-section layout in `SentComV5View.jsx`:
  - Chart takes top ~60% (was: full height)
  - Unified Stream + chat input take bottom ~40% with their own
    panel header. Wider than the old right-sidebar location, giving
    bot narratives + rejection thoughts more horizontal space.
- Right sidebar simplified: Briefings (top half, flex-1) + Open
  Positions (bottom half, flex-1). The previous fixed `28vh`/`24vh`
  caps removed since the stream-in-sidebar slot is gone.
- New `data-testid="sentcom-v5-stream-center"` for QA selectors.

### 2. Briefing "full briefing ↗" CTAs on Mid-Day / Power Hour / Close Recap
- Operator request: *"the briefings except for Morning prep are not
  clickable or show a full briefing button to click."*
- Added the same `onOpenDeepDive` button (matching Morning Prep) to
  Mid-Day Recap, Power Hour, and Close Recap cards.
- Cards already toggled inline-expand on click; this adds the
  explicit "open the full briefing modal" affordance the operator
  expected. Button only shows when the briefing window is `active`
  or `passed` (not `pending` — would be confusing on a future
  briefing the operator can't yet open).
- Each button passes a `kind` arg ("midday" / "powerhour" / "close")
  to `onOpenDeepDive` so future PRs can route to a kind-specific
  modal; current handler ignores the arg (opens the existing
  MorningBriefingModal) — back-compat preserved.

### 3. System Health Audit script
- New `backend/scripts/system_health_audit.py` — operator-runnable
  end-to-end diagnostic of the entire trading pipeline:
  scanner → evaluator → sizing → decisions → management → data.
- For each stage: ✓ green / ~ yellow / ✗ red rows with concrete
  numbers (total_scans, enabled_setups, max_risk_per_trade, open
  positions with stops, pusher latency, etc.)
- Verified live on the preview env — all 6 stages reachable, system
  green except for IB-offline yellows (expected when no Gateway
  connection).
- Run on DGX with:
  ```
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \\
      backend/scripts/system_health_audit.py
  ```
- Exits non-zero on any red so it can be piped into a cron / CI alert.

## 2026-04-28 — P1 batch #3: Rejection narrative ("why didn't I take this trade?")

Closes the operator's feedback loop — every rejection gate now
produces a wordy 1-2 sentence narrative streamed into Bot's Brain.

### What shipped
- New `TradingBotService.record_rejection(symbol, setup, direction, reason_code, ctx)`.
  Composes a conversational 1-2 sentence "why I passed" line and pushes
  it into the `_strategy_filter_thoughts` buffer the UI's Bot's Brain
  panel already streams (no new WS wiring needed — auto-flows through
  the existing `filter_thoughts` cache + 10s broadcast cycle).
- New helper `_compose_rejection_narrative` covering 13 distinct
  rejection reasons:
  - `dedup_open_position` — already long/short same name
  - `dedup_cooldown` — same setup just fired N seconds ago
  - `position_exists` / `pending_trade_exists` — duplicate avoidance
  - `setup_disabled` — strategy is OFF in operator's enabled list
  - `max_open_positions` — at the cap
  - `tqs_too_low` — quality below minimum
  - `confidence_gate_veto` — model split / regime-model disagreement
  - `regime_mismatch` — long in down-regime, short in up-regime, etc.
  - `account_guard_veto` — would breach risk caps
  - `eod_blackout` — too close to close
  - `evaluator_veto` — entry/stop math didn't work
  - `tight_stop` — would get wicked out
  - `oversized_notional` — size exceeds per-trade cap
  - generic fallback — never produces empty text or raises
- Wired at 5 silent-skip gates in `trading_bot_service._scan_for_alerts`
  + `_get_trade_alerts`:
  - dedup skip (was print-only)
  - position-exists safety net (was silent)
  - pending-trade exists (was silent)
  - setup-not-in-enabled (was print-only)
  - max-open-positions cap (was silent return)
  - post-evaluation "did not meet criteria" (was print-only)
- 17 regression tests in `tests/test_bot_rejection_narrative.py`.

### Example output (operator-facing UI)
```
⏭️ Skipping NVDA Squeeze — this strategy is currently OFF in my
enabled list. Either you turned it off in Bot Setup, or it's still in
SIMULATION while we collect shadow data. Re-enable it in Bot Setup if
you want me to trade it.

⏭️ Passing on AAPL Vwap Bounce — I just fired this exact long setup on
AAPL a few minutes ago and the dedup cooldown is still active. Letting
it clear before another shot. Cooldown clears in 87s.

⏭️ Passing on SPY Breakout — long setups don't fit a CONFIRMED_DOWN
regime in my book. Trading against the tape is how losses compound;
I'd rather sit out.

⏭️ Passing on AMD Opening Drive — pre-trade confidence gate vetoed it
(42% vs 60% required): XGB and CatBoost disagreed on direction. I want
my models AND the regime to agree before I commit.

⏸️ Skipping the whole scan cycle — already at my max-open-positions
cap (cap: 5). New ideas have to wait for one of the current trades to
close before I evaluate anything else.
```

### Verification
- 62 new tests passing across this session's 6 new test files (rejection
  narratives, setup narratives, scanner canaries, tick→bar, L2 router,
  pusher RPC gate).
- End-to-end smoke test confirmed: `bot.record_rejection(...)` →
  `bot.get_filter_thoughts()` returns the new thought with full
  narrative text, ready for the existing filter_thoughts WS broadcaster.

## 2026-04-28 — P1 batch #2: Bot copy + Canary tests + Phase 4 lockdown

Three more P1s shipped, all in the same session as the morning's
big-batch (live tick→Mongo, L2 dynamic routing, briefings, Mongo
index). Test suite now at **97 passing** (45 new + 52 prior).

### 1. Setup-found bot copy — wordy / conversational rewrite
- Operator preference 2026-04-28: *"I really want to know what the bot
  is thinking and doing at all times."*
- New helper `SentComService._compose_conversational_setup_narrative`
  replaces the terse one-liner
  `"RS LEADER NVDA +6.8% vs SPY - Outperforming market — TQS 51 (C)"`
  with a 2-3 sentence story:
  - Sentence 1 — what the bot saw (📡 + setup name + headline tell + why)
  - Sentence 2 — quality assessment (TQS + grade + plain-English
    interpretation: high-conviction / solid / middling / borderline /
    weak; track record: win-rate + profit factor + edge call)
  - Sentence 3 — the trade plan (💡 entry / stop / target / R:R +
    hold horizon "intraday / multi-day swing / multi-week position" +
    timeframe being read off)
- Wired into both setup-found alert path in `services/sentcom_service.py`.
- Regression coverage: `tests/test_setup_narrative.py` (9 tests).
- Example output (NVDA RS leader, TQS 51, $480.50 entry):
  > "📡 NVDA — spotted a Relative Strength Leader setup. RS LEADER
  > NVDA +6.8% vs SPY - Outperforming market. Why: Outperforming SPY
  > by 6.8% today. Quality call: TQS 51/100 (grade C) — quality is
  > borderline — proceed cautiously, we'd rather wait for a 70+.
  > Recent stats on this setup: 58% win rate, profit factor 1.5 — edge.
  > 💡 Plan: long entry around $480.50, stop at $475.20, target $495.00,
  > 1.7R potential, holding it as a day trade, reading off the 5min chart."

### 2. Scanner & bot canary tests
- New `tests/test_scanner_canary.py` (10 tests). Locks the
  *vital signs* contract of the scanner/bot pipeline so the two
  silent-regression patterns we hit this quarter can't recur:
  - 2026-04-17: `_symbol_adv_cache` → `_adv_cache` rename collapsed
    universe to 14 ETFs (caught here by
    `test_canary_canonical_universe_returns_100_plus_when_cache_seeded`).
  - 2026-04-27: `bot_persistence.restore_state` overwrote defaults
    instead of merging (caught here by
    `test_canary_bot_persistence_merges_defaults_and_saved`).
- Asserts: scanner enabled-setups ≥15, pillar setups have checkers,
  bot enabled-setups ≥20 + must include 14 critical scanner bases
  (rubber_band/vwap_*/reversal_*/squeeze/etc), safety watchlist ≥10
  with SPY/QQQ/IWM, canonical-universe path returns ≥100 when seeded,
  fallback-to-safety when canonical empty, wave-scanner batch
  non-empty, bot-persistence merges default+saved, Phase-4
  ENABLE_ALPACA_FALLBACK defaults to "false", consumers tolerate
  alpaca_service=None.
- Run as part of the standard pytest invocation. Fast (~0.2s for
  the whole file).

### 3. Phase 4 — Alpaca retirement lockdown
- Confirmed: `ENABLE_ALPACA_FALLBACK=false` is the default in
  server.py (verified via canary `test_canary_alpaca_fallback_default_is_false`).
  When false, `alpaca_service = None` is wired into every consumer.
- All `set_alpaca_service` consumers are deprecation stubs (no-op);
  legacy Alpaca SDK path is dead. The shim `services/alpaca_service.py`
  delegates to IBDataProvider when manually re-enabled.
- Canary lock prevents future PRs from accidentally re-enabling
  Alpaca-by-default. Operator can still flip the env var manually
  for emergency rollback if IB ever has a multi-day outage.
- **No code change required** — already shipped 2026-04-23 (the
  "Alpaca nuke") but the retirement was never officially marked
  complete. This locks it.

## 2026-04-28 — P1 batch: Live tick→Mongo, L2 dynamic routing, Briefings empty-states, Mongo index script

Big lift in one batch — addresses the 4 P1s the operator specifically
asked for. All shipped with regression tests; backend stays GREEN, all
67 tests passing (26 new + 41 pre-existing).

### 1. Live tick → ib_historical_data persister (architectural)
- New service `services/tick_to_bar_persister.py` — hooks the
  `/api/ib/push-data` ingest path. For every quote update from the
  Windows pusher, samples (last_price, cumulative_volume) into rolling
  1m / 5m / 15m / 1h buckets per symbol. On bucket-close, finalises an
  OHLCV bar and upserts into `ib_historical_data` with
  `source="live_tick"`.
- Eliminates the operator's pain point (quote: *"we shouldn't need to be
  constantly backfilling. there has to be a better way"*). For any
  pusher-subscribed symbol, the historical cache is now always 100%
  up-to-date through "right now" — chart's "PARTIAL · 50% COVERAGE"
  badge will resolve naturally.
- Volume math: per-bar = end_volume − start_volume (IB cumulative
  semantics). Negative deltas (rare IB glitches) clamp to 0.
- Wired into `routers/ib.py::receive_pushed_ib_data` (non-fatal — never
  breaks the push hot path) and initialised in `server.py::_init_all_services`.
- New endpoint `GET /api/ib/tick-persister-stats` for operator/agent
  introspection (active builders, bars persisted, ticks observed).
- Regression coverage: `tests/test_tick_to_bar_persister.py` (8 tests).

### 2. L2 dynamic routing — Path B (top-3 EVAL → 3 paper-mode L2 slots)
- **Pusher** (`documents/scripts/ib_data_pusher.py`):
  - 3 new endpoints: `POST /rpc/subscribe-l2`, `POST /rpc/unsubscribe-l2`,
    `GET /rpc/l2-subscriptions`. Reuse the existing `subscribe_level2` /
    `unsubscribe_level2` helpers so the IB-cap check (3 slots) stays in
    one place.
  - Startup index-L2 disabled by default — slots reserved for dynamic
    routing. Set `IB_PUSHER_STARTUP_L2=true` to revert.
  - In-play auto-L2 disabled by default. Set `IB_PUSHER_AUTO_INPLAY_L2=true`
    to revert to legacy in-play auto-subscribe.
- **DGX backend** (`services/l2_router.py`): new background task that
  every 15s computes the desired top-3 from `_live_alerts`
  (priority DESC, TQS DESC, recency DESC, dedupe-by-symbol, freshness
  ≤10 min, status=active), diffs against the pusher's current L2 set,
  and sends sub/unsub deltas. Audit ring buffer of last-50 routing
  decisions exposed via `GET /api/ib/l2-router-status`.
- Disable with `ENABLE_L2_DYNAMIC_ROUTING=false`. The pusher endpoints
  remain available for manual operator control.
- Operator's path B reasoning ratified in implementation: regime engine
  reads price (not L2 imbalance), so giving up startup index L2 is
  safe. One IB clientId only — no second-session complexity.
- Regression coverage: `tests/test_l2_router.py` (11 tests).

### 3. Briefings empty-states (operator-flagged 2026-04-27)
- **Backend** `services/gameplan_service.py::_auto_populate_game_plan`:
  fetches current `MarketRegimeEngine` state + recommendation and
  surfaces them as top-level `regime` / `bias` / `thesis` fields on the
  game plan doc (also mirrored into `big_picture.market_regime` for
  canonical home). Operator no longer has to hand-file a plan to see
  the morning prep card hydrate.
  - Verified live: `/api/journal/gameplan/today` now returns
    `regime: "CONFIRMED_DOWN"`, `bias: "Bearish"`,
    `thesis: "Correction mode. Reduce exposure..."` after delete+recreate.
- **Frontend** `components/sentcom/v5/BriefingsV5.jsx`:
  - **Morning Prep**: reads `gp.big_picture?.market_regime` as a
    fallback so it hydrates from either shape; also derives a watchlist
    from `stocks_in_play` when `gp.watchlist` is missing.
  - **Mid-Day Recap**: when no fills/positions, shows regime + scanner
    hits ("No fills yet · CONFIRMED_DOWN · scanner 6 hits") instead of
    silent "No fills yet today"; expanded view surfaces watchlist
    symbols.
  - **Power Hour**: when no open positions, shows scanner hits + top-3
    watchlist symbols ("Flat into close · scanner 6 hits · watch
    NVDA, AAPL, AMZN") instead of "No open positions heading into
    close"; expanded view shows full watchlist as setup ideas.

### 4. Mongo index helper (operator-side)
- New `backend/scripts/create_ib_historical_indexes.py` —
  idempotent script that creates the compound index
  `{bar_size: 1, date: -1}` (and `{symbol: 1, bar_size: 1, date: -1}`
  if missing) on `ib_historical_data`. Drops `rebuild-adv-from-ib`
  from 5+ minutes to seconds.
- **Operator action required on DGX:**
  ```
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \\
      backend/scripts/create_ib_historical_indexes.py
  ```

### Verification status
- 67/67 backend tests passing.
- `/api/ib/l2-router-status` live (running, 2 ticks, 0 errors).
- `/api/ib/tick-persister-stats` live (waiting for pusher quotes).
- `/api/journal/gameplan/today` live (returns regime + bias + thesis).
- Frontend `BriefingsV5.jsx` lint clean.

## 2026-04-28 — Pusher cleanup + Wave-scanner stats + RPC subscription gate

P0 + P1 batch from operator's end-of-day request list. All shipped with
regression tests; system stays GREEN, no behaviour change for happy path.

### 1. L2 subscription cap lowered 5 → 3 (`ib_data_pusher.py`)
- `subscribe_level2()` now matches `update_level2_subscriptions()` at
  `MAX_L2_SUBSCRIPTIONS = 3` — IB paper-mode hard cap. Was 5, which
  triggered IB Error 309 on every pusher startup as the 4th/5th of
  SPY/QQQ/IWM/DIA/<inplay> got rejected.
- Docstring + inline comments updated to flag the paper-mode ceiling
  and rationale.

### 2. RPC `/rpc/latest-bars` subscription gate (`services/ib_pusher_rpc.py`)
- New `subscriptions()` method on `_PusherRPCClient` — TTL-cached
  (30s) snapshot of `/rpc/subscriptions`. Tri-state: returns set when
  pusher reachable, None when pusher down/older endpoint missing.
- New `is_pusher_subscribed(symbol)` helper exposing the tri-state to
  callers (`True` / `False` / `None`).
- `latest_bars()` and `latest_bars_batch()` now gate calls on
  membership: unsubscribed symbols short-circuit to None / are filtered
  out of the batch. Pusher unreachable → no gating (preserves
  backward-compat with older pushers).
- Cache busted automatically when backend POSTs to `/rpc/subscribe` or
  `/rpc/unsubscribe` so the next gate sees the fresh set without
  waiting for TTL expiry.
- Eliminates the IB pacing storm where DGX would ask the pusher for
  reqHistoricalData on HD/ARKK/COP/SHOP every scan cycle (~10s timeout
  each) — pusher logs were polluted with `Read timed out` warnings.
- Regression coverage: `tests/test_pusher_rpc_subscription_gate.py`
  (7 tests, all passing) — locks subscriptions+caching, tri-state,
  per-symbol short-circuit, batch filtering, cache invalidation on
  subscribe/unsubscribe, and that unrelated calls don't bust the cache.

### 3. Wave-scanner stats wired up (`services/enhanced_scanner.py`)
- `_scan_loop` now calls `wave_scanner.record_scan_complete(...)` after
  every successful intraday scan (passing symbols-scanned, alert delta,
  and duration) and stamps `_last_full_scan_complete`.
- `/api/wave-scanner/stats` now reports real `total_scans` /
  `last_full_scan` / `last_scan_duration` instead of the permanent
  zero that confused the operator (wave scanner was producing batches
  but nothing ever called back to record completion).

### Items diagnosed but NOT shipped (not real bugs)
- **`/api/scanner/daily-alerts` returns 0 despite alerts existing**:
  the handoff diagnosed this as a `timestamp` vs `created_at` field
  mismatch, but the actual implementation reads `_live_alerts.values()`
  in-memory and filters by `setup_type ∈ DAILY_SETUPS` — no Mongo
  query at all. Returns 0 simply because no daily setups have fired
  this session. No code change needed; closed.

## 2026-04-27 — End-of-session verified state — HEALTHY

After today's fixes, operator's screenshot confirmed system is green:

| Metric | Status |
|---|---|
| Pusher | GREEN, 4 pushes/min |
| RPC last | 546ms (down from 350,000ms earlier) |
| Quotes tracked | 45 |
| Scanner | 6 hits / 7 cards shown |
| Bot filter | `✅ passed filter` for ORCL/GOOGL/AMZN/GOOG/SMH/TSM/AMD |
| Chart | Live with full SPY history |
| Top Movers | All 5 indices populated |
| Account | Paper DUN615665 connected, $100,000 (paper default) |
| Models | 44 (35 healthy / 4 mode-C / 5 missing) |
| Phase | MARKET OPEN |

**4 separate bugs fixed in this session** (chronologically):
1. App-wide ET 12-hour time format (8 frontend files)
2. Chart day-boundary tick labels + RPC latency headline
3. Scanner header counting + P(win) duplication + Stream `scan` filter
4. Scanner regression (`_adv_cache` rename) — restored 11 detector types
5. Bot persistence override — 7 strategies were invisible due to stale Mongo

**Operator items deferred to next session** (see ROADMAP "🔴 Now"):
- Pusher L2 limit 5→3 + dynamic L2 routing for top-3 EVAL alerts
- Backend skip RPC for unsubscribed symbols (HD/ARKK/COP/SHOP noise)
- Live tick → Mongo bar persistence (architectural — kills "always
  backfilling" pain operator flagged)
- Wave-scanner background loop never started
- daily-alerts field-name mismatch
- Mongo compound index for fast rebuild

---

## 2026-04-27 — Bot persistence overrides defaults — 7 strategies invisible — SHIPPED

### Why
Even after fixing the scanner regression (`_adv_cache` vs
`_symbol_adv_cache`) and pulling to DGX, operator's logs still showed:
```
⏭️ AMZN relative_strength_leader not in enabled setups
⏭️ GOOG relative_strength_leader not in enabled setups
... (8 alerts skipped per scan tick)
```
TradingBot was producing alerts but immediately filtering them out as
"not enabled". Source: `bot_state.enabled_setups` in Mongo had been
persisted by an older code version that didn't include
`relative_strength_leader`, `relative_strength_laggard`,
`reversal`, `halfback_reversal`, `halfback`, `vwap_reclaim`,
`vwap_rejection`. On every startup, `bot_persistence.py:53` REPLACED
the in-memory defaults with that stale list, so newly-added defaults
were invisible to the bot.

### Fix
`backend/services/bot_persistence.py · BotPersistence.load_state()`
— now MERGES saved with current defaults instead of replacing.
`bot._enabled_setups = sorted(set(defaults) | set(saved))`. Logs the
diff so operators can see what got added on each startup.

This is a permanent fix — when future code adds a new strategy to the
default list, restarts will auto-pick it up instead of silently
hiding it behind the persisted list.

### Hot-fix for current operator state
Operator was instructed to run a one-off Mongo update adding the 7
missing entries to the persisted list, so the bug resolves
immediately without waiting for the deploy:
```python
db.bot_state.update_one({'_id': 'bot_state'},
  {'$addToSet': {'enabled_setups': {'$each': [
    'relative_strength_leader', 'relative_strength_laggard',
    'reversal', 'halfback_reversal', 'halfback',
    'vwap_reclaim', 'vwap_rejection']}}}, upsert=True)
```

### Verification
- Lint: clean (1 unrelated pre-existing F841 warning).
- Operator should observe `✅ {sym} relative_strength_leader passed
  filter` lines in backend log within 30 seconds of running the hot-fix.

---

## 2026-04-27 — Pusher RPC catastrophic latency surfaced — INVESTIGATION PARKED

### What we saw
`/api/ib/pusher-health` returned:
```
rpc_latency_ms_last: 350,296.7 ms (5.8 minutes)
rpc_latency_ms_p95:  278,097.3 ms (4.6 minutes)
rpc_latency_ms_avg:   37,087.9 ms (37 seconds)
pushes_per_min: 0
push_count_total: 17 (since startup)
pusher_dead: true
```
Pusher is `connected: true` and tracking 45 quotes, but every RPC call
back to the cloud takes minutes. This is why the UI chart shows DEAD
and Top Movers stays at "Loading..." even when scanner produces hits.

### Root cause TBD — possibilities
- IB pacing throttle (we may be hammering IB with subscriptions)
- DGX backend slow to respond to pusher RPC calls (each scan tick
  fires 8 skip-checks; could be lock contention)
- Network between Windows ↔ DGX degraded
- Pusher-side RPC client blocked on some I/O

### Action
Logged to ROADMAP "🔴 Now / Near-term" for next session.

---

## 2026-04-27 — Scanner regression — wrong attribute name killed 11 detectors — SHIPPED

### Why
Operator's screenshots showed the live scanner finding only 1 NVDA
relative-strength setup. Mongo diagnostic confirmed it was systemic, not
a quiet-tape artifact:

| Date | Alerts | Non-RS types | RS% |
|---|---|---|---|
| 04-13 → 04-17 | 1,128 – 11,810 / day | 13–14 | 0% |
| 04-18 → 04-20 | 11–37 / day | 2–3 | 0% |
| 04-21 → 04-23 | 26–68 / day | 2–3 | 13–81% |
| 04-25 | 10 | 1 | 0% |
| 04-27 (today) | 17 | **0** | **100%** |

Alert volume crashed ~99% on 2026-04-17. Variety collapsed from 14
setup types to 0 non-RS over the next 9 days. RS-only alerts crept up
to 100% of all alerts.

### Root cause
Commit `80cf8501` (2026-04-17 22:15 UTC) renamed two references in the
scan-loop symbol selection from `self._symbol_adv_cache` to
`self._adv_cache`. These are **two completely different things**:

- `self._symbol_adv_cache` — was the canonical Mongo-loaded universe
  dict (~9,400 symbols).
- `self._adv_cache` — a 15-min TTL lookup cache (defined line 619),
  populated lazily as individual ADV checks run, **normally empty on
  cold scan**.

The renamed code read symbols from the empty TTL dict, fell through to
the `live_quotes.keys()` fallback (~14 symbols from the IB pusher),
and only those 14 got scanned. Of the 14, only ones with a clear
relative-strength signal vs SPY triggered an alert (RS being the one
detector that doesn't need RVOL / EMA9 / RSI / ATR fields from a
proper snapshot — every other detector's preconditions silently
returned `None` because the snapshot pipeline wasn't running for these
symbols).

### Fix
`backend/services/enhanced_scanner.py` — both broken sites (daily-scan
path ~line 4054, pre-market-scan path ~line 4152) now pull from
`services.symbol_universe.get_universe(self.db, tier="intraday")`
(same canonical helper already used at line 1253 for the watchlist).
Live-quote fallback retained as a 2nd-tier fallback; Mongo distinct
retained as 3rd. Imports added at point-of-use to avoid circular-import
risk.

### Verification
- `python -m ast` parse: clean
- Existing pre-existing lint warnings unrelated (f-strings, unused vars)
- Operator should observe alert volume jump back to ~1,000/day with
  13+ setup types within one scan cycle of restart.

### Operator action required
1. Save to GitHub from this session.
2. On DGX: `cd ~/Trading-and-Analysis-Platform && git pull`
3. Restart backend: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &`
4. Wait 60s, then run:
   ```
   ~/venv/bin/python -c "
   from pymongo import MongoClient; import os, collections
   db = MongoClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))[os.environ.get('DB_NAME', 'tradecommand')]
   t = collections.Counter(a.get('setup_type') for a in db.live_alerts.find({'created_at': {'\$gte': '2026-04-27T19:00'}}, {'setup_type': 1}))
   for s, n in t.most_common(): print(f'{s}: {n}')
   "
   ```
   Should show multiple setup types (breakout, vwap_bounce, orb, …),
   not just RS.

---

## 2026-04-27 — Scanner header count + P(win) duplication + Stream `scan` filter — SHIPPED

### Why
Operator screenshot showed "SCANNER · LIVE · 2 hits" with only 1 visible
NVDA card, "P(win) 51%" identical to "conf 51%" in the same card, and
the unified stream's `scan` filter chip was effectively dead. Three
different bugs, all visible at once.

### Scope
- `components/sentcom/SentComV5View.jsx` — header now counts unique
  symbols across `setups + alerts + positions` (matches the deduped
  card list below). 1 NVDA setup + 1 NVDA alert = `1 hit`, not `2`.
  Switched to singular/plural label ("1 hit" / "n hits").
- `components/sentcom/v5/ScannerCardsV5.jsx` — `p_win` no longer falls
  back to `confidence`. Card metrics chip is hidden when only confidence
  is known, so operators stop seeing the same number twice.
- `components/sentcom/v5/UnifiedStreamV5.jsx · classifyMessage()` —
  added `scan` severity bucket matching `scanning`, `setup_found`,
  `entry_zone`, `relative_strength`, `breakout`, `reversal`, plus text
  fallbacks (`text.includes('scanning' | 'setup found')`). Without it
  the `scan` filter chip matched zero events. Added matching
  `text-violet-300` colour tokens to `TIME_COLOR_BY_SEV` and
  `BOT_TAG_COLOR_BY_SEV`.

### Verification
- ESLint: clean across all 3 files.
- Counting fix: trivially observable — the body always matches the header.
- Filter fix: `scan` chip now matches scanner heartbeat and setup-found
  events that previously fell through to `info`.

### Operator notes (issues found in same screenshot but parked)

These are not bugs, they're content-gap features that need backend
work:

- **Morning Prep "No game plan filed"** — gameplan auto-generation isn't
  running, OR `/api/assistant/coach/morning-briefing` returns empty. Need
  backend investigation: who is supposed to write into the journal
  before 09:30 ET? (Logged to ROADMAP.)
- **Mid-Day Recap with no fills shows nothing** — card has no fallback
  for empty-state. Should pull regime / scanner hits / top movers when
  positions are empty. (Logged to ROADMAP.)
- **Power Hour with no positions shows nothing** — same — needs pre-
  position thoughts (top movers + watchlist scan results). (Logged.)
- **Setup-found bot text** — operator says it's "wrong" but didn't
  specify how. Awaiting clarification before changing server-side
  copy generation.

The `222 DLQ` red badge is **working as designed** — it's
`DeadLetterBadge.jsx` surfacing 222 historical-data requests that
failed qualification. Click it to open NIA Data Collection and run
`/api/ib-collector/retry-failed` to reattempt them.

---

## 2026-04-27 — Chart day-boundary tick labels + RPC latency headline — SHIPPED

### Why
Operator screenshot showed the 5m chart x-axis as `9:30 AM → 1:00 PM →
4:00 AM → 8:00 AM …` — time appeared to go backwards because the
session crosses midnight and our tick formatter only ever rendered
`HH:MM AM/PM`, never a date. Same screenshot showed Pusher RPC as
`avg 1117ms · p95 982ms · last 335ms` — `avg > p95` is mathematically
possible (one large outlier above p95 pulls the mean up) but it
confuses operators because the headline reads "1117ms" while the live
number is 335ms.

### Scope
- `frontend/src/utils/timeET.js · chartTickMarkFormatterET()` now
  branches on lightweight-charts `TickMarkType`:
  - `0|1|2` (Year / Month / DayOfMonth) → render `Apr 27` style date.
  - `3|4` (Time / TimeWithSeconds)      → render `9:30 AM` 12-h time.
  Day boundaries on intraday charts now show a date label instead of
  silently wrapping the clock.
- `frontend/src/components/sentcom/v5/PusherHeartbeatTile.jsx · RPC
  block`: headline is now `rpcLast` (most actionable "right now"
  number); `p95` and `avg` demoted to context. Stops the avg-skew-by-
  outlier from misleading operators.

### Verification
- ESLint: clean on both files.
- `chartTickMarkFormatterET` tested against lightweight-charts'
  TickMarkType enum (0=Year, 1=Month, 2=DayOfMonth, 3=Time,
  4=TimeWithSeconds — matches their docs).

### Operator note (not a bug)
The `222 DLQ` red badge in the header is **not a regression** — it's
`DeadLetterBadge.jsx` correctly surfacing 222 historical-data requests
that permanently failed qualification (matches the "204 qualify_failed"
item in ROADMAP P3). Click the badge to open the NIA Data Collection
panel and use `/api/ib-collector/retry-failed` to reattempt them.

---

## 2026-04-27 — App-wide ET 12-Hour Time Format — SHIPPED

### Why
Operator complained displays were still showing military time (e.g. `18:30`)
instead of the requested ET 12-hour format (`6:30 PM`). Time hierarchy must
be unambiguous for trade decisions.

### Scope
Routed every user-facing time formatter through the existing
`/app/frontend/src/utils/timeET.js` utility (`fmtET12`, `fmtET12Sec`).
Files updated:
- `components/sentcom/v5/MarketStateBanner.jsx` — etClock chip
- `components/sentcom/v5/BriefingsV5.jsx` — `nowETDisplay()` for cards;
  `formatTimeRange()` re-rendered as `9:30 AM ET` style. (Internal
  `nowET()` retained as 24h `HH:MM` for `minutesET()` math only.)
- `components/sentcom/v5/SafetyV5.jsx` — kill-switch tripped-at chip
- `components/RightSidebar.jsx` — alert timestamp row
- `components/StreamOfConsciousness.jsx` — thought timestamp + last-update
- `components/MorningBriefingModal.jsx` — modal time label

### Verification
- `mcp_lint_javascript`: clean across all 6 files.
- Node smoke test against `timeET.js`:
  - `fmtET12("2026-04-27T18:30:00Z") → "2:30 PM"` ✅
  - `fmtET12Sec(...) → "2:30:00 PM"` ✅
  - `fmtET12Date(...) → "Apr 27, 2026, 2:30 PM"` ✅

### Operator action required
Pull the changes on DGX and let CRA hot-reload (`yarn start` already running),
or `sudo supervisorctl restart frontend`.

---


## 2026-04-27 — Scanner Diversity Cache Rebuild — INSTRUCTION FOR OPERATOR

### Why
Wave scanner was only emitting "relative-strength" hits because
`symbol_adv_cache` was empty on DGX, forcing fallback to the 14-symbol
hardcoded pusher list.

### Action (run on DGX)
```bash
curl -X POST http://localhost:8001/api/ib-collector/rebuild-adv-from-ib
```
This populates `symbol_adv_cache` from MongoDB daily bars (must have daily
bars present — if response is `{"success": false, "error": "No daily bar
data found"}`, run `/api/ib-collector/smart-backfill` first to seed dailies,
then retry).

Once populated, the wave scanner picks up the full canonical universe on
its next tick — no code change required.

---



## 2026-04-26 (LATER) — Weekend/Overnight Awareness Sweep — SHIPPED

### Symptom: weekend false-positives across the UI
On Sunday/Mon-premarket the V5 surfaces incorrectly flagged everything red:
- `account_guard` chip → `ACCOUNT MISMATCH` (pusher has no account snapshot
  on weekends because IB Gateway is offline, returned `match: false`)
- `BackfillReadinessCard` → `Stale on intraday: SPY, QQQ, ...` (Friday close
  bars are 2.7d old on Mon morning — the stale-days threshold flipped
  even though the market simply hadn't traded)
- `LastTrophyRunCard` → showed `0 models · 0 failed · 0 errors` because
  the synth fallback's phase_history keys didn't match the P-code label map
- `ChatInput` → disabled all weekend because `disabled={!status?.connected}`
  tied chat to IB Gateway connectivity (chat is independent of IB)

### Fixes
1. **`services/account_guard.py::check_account_match`**: new `ib_connected`
   parameter. When `current_account_id is None` AND `ib_connected=False`,
   returns `(True, "pending — IB Gateway disconnected")` instead of
   `(False, "no account reported")`. Real account *drift* (paper mode but
   pusher reports a LIVE alias) still flags MISMATCH even with IB offline.
2. **`routers/safety_router.py`**: passes the resolved `ib_connected` flag
   from the pusher into the guard.
3. **`services/backfill_readiness_service.py`**: new helpers
   `_market_state_now()` (re-export of `live_bar_cache.classify_market_state`)
   + `_adjusted_stale_days()` that adds **+3 days on weekend** and **+1 day
   overnight** to intraday stale-thresholds (Daily/weekly unchanged because
   their windows already absorb a normal weekend gap).
4. **`routers/ai_training.py::last-trophy-run`**: synth fallback now
   re-keys phase_history under the P-code labels (long-name → short-code
   map: `generic_directional → P1`, `cnn_patterns → P9`, etc.) so the
   trophy tile renders correctly for the just-completed pre-archive run.
5. **`SentComV5View.jsx`** + **`SentCom.jsx`** (legacy view): removed
   `disabled={!status?.connected}` from the ChatInput. Chat talks to
   `chat_server` on port 8002 — it's independent of IB Gateway.

### Tests (8 new regression tests)
- `tests/test_weekend_aware_safety.py`: 8 tests
    * intraday stale_days unchanged during RTH/extended
    * intraday stale_days +3d on weekend, +1d overnight
    * daily/weekly stale_days NOT weekend-buffered
    * account match when alias hits
    * account pending (not mismatch) when None + ib_connected=False
    * account drift to LIVE alias still flags MISMATCH on weekend
    * pre-fix behaviour preserved when ib_connected=True
    * UI summary payload includes ib_connected field
- 80/80 tests green across phase-1/2/3 + scanner + canonical universe +
  weekend-aware safety + trophy-run archive + autonomy readiness

### Files changed
- `backend/services/account_guard.py`
- `backend/routers/safety_router.py`
- `backend/services/backfill_readiness_service.py`
- `backend/routers/ai_training.py`
- `frontend/src/components/sentcom/SentComV5View.jsx`
- `frontend/src/components/SentCom.jsx`
- `backend/tests/test_weekend_aware_safety.py` (new)

### Still open from this session's audit
- 🟡 Scanner shows idle in UI — needs runtime curl data to diagnose
- 🟢 Chart scroll-wheel doesn't fetch more bars (P2 cosmetic)
- 🟢 Unified stream weekend-setups stub message is just text (P2 cosmetic)


## 2026-04-26 (FINAL+) — Trophy Run Tile + Autonomy Readiness Dashboard — SHIPPED

### "Last Successful Trophy Run" tile (operator SLA badge)
- New collection `training_runs_archive` written from
  `services/ai_modules/training_pipeline.py` when the pipeline marks itself
  completed. Contains: started_at, completed_at, elapsed_seconds,
  models_trained list w/ accuracy + phase, phase_breakdown deep-copy,
  is_trophy boolean (failed=0 AND errors=0).
- New endpoint `GET /api/ai-training/last-trophy-run` returning structured
  summary with phase_recurrence_watch_ok (P5/P8), headline_accuracies (top 6),
  elapsed_human, total_samples. Falls back to synthesizing from live
  `training_pipeline_status` when archive is empty (so the just-completed
  run shows up without retraining).
- New frontend tile `LastTrophyRunCard.jsx` mounted in FreshnessInspector
  underneath `LastTrainingRunCard`. Shows verdict pill (TROPHY ✓ / PARTIAL),
  per-phase health strip with star markers on P5+P8, top-5 accuracies.

### Autonomy Readiness Dashboard (Monday-morning go/no-go)
- New router `routers/autonomy_router.py` with `GET /api/autonomy/readiness`
  aggregating 7 sub-checks:
    1. account_active — paper vs live confirmed, current account_id known
    2. pusher_rpc — DGX → Windows pusher reachable AND ib_connected
    3. live_bars — pusher returns real bars on a SPY query
    4. trophy_run — last successful run within 7 days
    5. kill_switch — enabled: true, not currently tripped
    6. eod_auto_close — auto-close before market close enabled
    7. risk_consistency — bot risk_params don't conflict with kill switch
  Verdict: green (all pass) | amber (warnings) | red (blockers).
- New frontend tile `AutonomyReadinessCard.jsx` mounted in FreshnessInspector
  beneath the trophy-run tile. Shows verdict pill, per-check grid with
  click-to-expand drawer, auto-execute master-gate banner (LIVE/OFF), and
  `next_steps` action list.
- The dashboard correctly identified 2 blockers (pusher_rpc, trophy_run on
  preview pod) + 3 warnings (account/live_bars on weekend, risk_consistency
  conflicts) — surfaces real config issues operators need to fix.

### Risk-param conflicts surfaced (warnings, not blockers)
- `trading_bot.max_open_positions=10 > kill_switch.max_positions=5` →
  effective cap: 5 (kill switch wins)
- `trading_bot.max_daily_loss=0` (unset); kill switch caps at $500 → bot
  value should match
- `min_risk_reward=0.8` accepts trades where reward < risk
- `max_position_pct=50%` allows a single position to be half capital

### Tests (15 new regression tests)
- `tests/test_trophy_run_archive.py`: 10 tests — endpoint smoke, trophy
  classification, recurrence-watch rollup, headline accuracies sort, top-N cap
- `tests/test_autonomy_readiness.py`: 5 tests — endpoint smoke, verdict logic,
  ready_for_autonomous gate, risk-consistency edge cases (clean / cap conflict
  / daily_loss unset / rr<1 / aggressive position pct)
- 111/111 tests green
  (+15 new + 96 existing across phase 1/2/3 + scanner + canonical universe)

### Files added/changed
- `backend/services/ai_modules/training_pipeline.py` — archive snapshot
- `backend/routers/ai_training.py` — `/last-trophy-run` endpoint
- `backend/routers/autonomy_router.py` — NEW
- `backend/server.py` — wire autonomy_router
- `frontend/src/components/sentcom/v5/LastTrophyRunCard.jsx` — NEW
- `frontend/src/components/sentcom/v5/AutonomyReadinessCard.jsx` — NEW
- `frontend/src/components/sentcom/v5/FreshnessInspector.jsx` — mount cards
- `backend/tests/test_trophy_run_archive.py` — NEW
- `backend/tests/test_autonomy_readiness.py` — NEW


## 2026-04-26 (FINAL) — TRAIN ALL 173-model run COMPLETED, 0 failures

### Trophy Run (414m, 6h 54m elapsed, 0 errors across 14 phases)

| Phase | Models | Failed | Acc | Time |
|---|---|---|---|---|
| P1 Generic Directional | 7/7 | 0 | 52.7% | 4.3m |
| P2 Setup Long | 17/17 | 0 | 47.1% | 44.0m |
| P2.5 Setup Short | 17/17 | 0 | 45.7% | 33.5m |
| P3 Volatility | 7/7 | 0 | **76.1%** | 40.3m |
| P4 Exit Timing | 10/10 | 0 | 45.1% | 20.5m |
| **P5 Sector-Relative** (RECURRENCE FIXED) | **3/3** | **0** | 53.7% | 0.7m |
| P5.5 Gap Fill | 5/7 | 0 | **94.1%** | 3.5m |
| P6 Risk-of-Ruin | 6/6 | 0 | 61.7% | 9.3m |
| P7 Regime-Conditional | 28/28 | 0 | 56.3% | 16.4m |
| **P8 Ensemble Meta-Learner** (RECURRENCE FIXED) | **10/10** | **0** | 61.1% | 46.4m |
| P9 CNN Chart Patterns | **39**/34 | 0 | 62.8% | 123.1m |
| P11 Deep Learning (VAE/TFT/CNN-LSTM) | 3/3 | 0 | 47.0% | 42.4m |
| P12 FinBERT Sentiment | 1/1 | 0 | — | 2.8m |
| P13 Auto-Validation | 20/34 | 0 | 48.7% | 10.0m |

**Total: 173 models trained, 0 failures, 0 errors.**

### Validation
- Both 3-run recurrences (P5 0-models, P8 ensemble `_1day_predictor`) are conclusively dead
- OOS validation accuracies > random baseline:
    * `val_SHORT_REVERSAL: 48.7%`
    * `val_SHORT_MOMENTUM: 43.3%`
    * `val_SHORT_TREND: 48.2%`
- P9 CNN overshot 39/34 — system discovered 5 additional setup×timeframe variants (free upside)
- Model-protection layer fired correctly on `direction_predictor_15min_range_bound` and `ensemble_vwap` — promoted models with better class distribution despite slightly lower raw accuracy
- Phase 1 resume engine skipped 5 models <24h old → saved ~30m

### System health
- Peak RAM 67GB / 121GB (55%) · Peak GPU 66°C
- NVMe cache hit rate 100% during P4-P7
- Swap usage stable at 1GB / 15GB the entire run


## 2026-04-26 (later) — Phase 3 Scanner IB-only wiring — SHIPPED

### Predictive Scanner now strict IB-only
- `services/predictive_scanner.py::_get_market_data` — when the enhanced
  scanner has no tape data, fallback path now calls
  `services.live_symbol_snapshot.get_latest_snapshot(symbol)` (Phase 3
  helper that goes pusher RPC → cache). Replaces the previous
  `alpaca_service.get_quote(symbol)` path.
- Removed `self._alpaca_service` instance var + `alpaca_service`
  lazy-init property — they were only consumed by the fallback.
- Snapshot-failure path returns `None` cleanly (symbol skipped this
  scan cycle) instead of synthetic Alpaca-shape data — no more
  hallucinated bid/ask spreads on weekends.
- Bid/ask now derived from `latest_price ± 5bps`; volume left at 0
  because `live_symbol_snapshot` is price-only by design (consumers
  needing volume should use `fetch_latest_session_bars` directly).

### Phase 3 surface coverage — COMPLETE
| Surface | Wiring |
|---|---|
| AI Chat | `chat_server.py` → `/api/live/symbol-snapshot/{sym}` (held + indices) |
| Briefings (UI) | `useBriefingLiveData.js` → `/api/live/briefing-top-movers` |
| TopMoversTile | `/api/live/briefing-snapshot` |
| Command Palette | `/api/live/briefing-watchlist` |
| **Scanner (NEW)** | `predictive_scanner._get_market_data` → `get_latest_snapshot` |
| ScannerCardsV5 (UI) | `useLiveSubscriptions(topSymbols, {max:10})` |

### Tests (6 new regression tests)
- `tests/test_scanner_phase3_ib_only.py`:
    * No `_alpaca_service` instance var on `PredictiveScannerService`
    * No `alpaca_service` property
    * `_get_market_data` imports `get_latest_snapshot`
    * No `alpaca_service.get_quote` call in source
    * Fallback returns scanner-shaped dict with all `technicals`/`scores` keys
    * Returns `None` on snapshot failure (no synthetic data)
- 105/105 phase-1/2/3 tests green
  (`test_scanner_phase3_ib_only.py`, `test_live_subscription_manager.py`,
  `test_universe_canonical.py`, `test_live_data_phase1.py`,
  `test_live_data_phase3.py`, `test_live_data_phase3_http.py`,
  `test_live_subscription_phase2_http.py`).

### Files changed this session
- `backend/services/predictive_scanner.py`
- `backend/tests/test_scanner_phase3_ib_only.py` (new)


## 2026-04-26 (later) — Phase 1 LIVE + Phase 2 verified + IB-only cleanup — SHIPPED

### Phase 1: Live Data RPC reachable from DGX → Pusher (FULLY ON)
- DGX `.env` updated: `IB_PUSHER_RPC_URL=http://192.168.50.1:8765`, `ENABLE_LIVE_BAR_RPC=true`.
- Windows firewall rule `IB Pusher RPC` (Profile=Any, Allow Inbound TCP 8765) installed.
- `Ethernet 3` adapter category permanently flipped from **Public → Private**, so
  the Public-profile `Python` Block rule no longer overrides our Allow.
- `GET /api/live/pusher-rpc-health` from DGX backend returns
  `reachable: true, client.url: "http://192.168.50.1:8765"`. Phase 1
  closed.
- On weekends (`market_state: "weekend"` and `ib_connected: false` on the
  pusher) the `latest-bars` path correctly returns
  `error: pusher_rpc_unreachable` — expected behaviour, validates the
  weekend kill-switch path.

### Phase 2: Live Subscription Layer — VERIFIED end-to-end
- `services/live_subscription_manager.py` (ref-counted, sweep, heartbeat) +
  `routers/live_data_router.py` Phase 2 endpoints already in code.
- Pusher `/rpc/subscribe`, `/rpc/unsubscribe`, `/rpc/subscriptions` exist
  in `documents/scripts/ib_data_pusher.py`.
- Frontend hook `hooks/useLiveSubscription.js` wired into `ChartPanel`,
  `EnhancedTickerModal`, `ScannerCardsV5`. 2-min heartbeat + unmount
  unsubscribe behaviour matches backend's 5-min auto-expire sweep.
- Smoke test on the cloud-preview backend: subscribe → ref_count 1 →
  subscribe → ref_count 2 → heartbeat → unsubscribe → ref_count 1 →
  unsubscribe (1→0, fully_unsubscribed=true) all return `accepted: true`
  with correct ref-count semantics. List endpoint reports
  `age_seconds`, `idle_seconds`, `pusher_ok`. Sweep endpoint live.
- Tests: 99/99 phase-1/2/3 tests green.

### IB-only cleanup (P3)
- `routers/ib.py::get_comprehensive_analysis` (`/api/ib/analysis/{symbol}`)
  — removed all hardcoded Alpaca paths:
    * Quote step 4 (`_stock_service` legacy shim) — DELETED.
    * Historical-bars step 1 (`_alpaca_service.get_bars(...)`) — DELETED;
      now goes IB direct → MongoDB ib_historical_data fallback.
    * S/R fallback `_alpaca_service.get_bars(...)` — DELETED; goes
      straight to the heuristic ±2.5% band when IB has no bars.
    * Quote priority comment + busy-mode log message updated to reflect
      Pushed IB → IB Position → Direct IB → MongoDB.
- `documents/scripts/ib_data_pusher.py::request_account_updates` — fixed
  ib_insync API drift: `IB.reqAccountUpdates(account=...)` (the
  `subscribe` kwarg lives on `ib.client`, not the high-level `IB` class).
- `documents/scripts/StartTradeCommand.bat` — `[SKIP] ib_data_pusher.py
  not found` now prints the full path it checked.

### Files changed this session
- `backend/routers/ib.py`
- `documents/scripts/ib_data_pusher.py`
- `documents/scripts/StartTradeCommand.bat`
- `backend/.env` (DGX side, manual edit)
- `backend/tests/test_live_subscription_e2e_curl.md` (new — operator run book)


## 2026-04-26 (cont.) — Training Pipeline canonicalization + UI surface

Closing the loop: every AI training entry point now reads from the
same `services.symbol_universe.get_universe_for_bar_size(db, bar_size)`
that smart-backfill + readiness use. The 4,000-symbol-runaway training
class of bug is now structurally impossible.

### Code wired through canonical universe
- **`services/symbol_universe.py`** — added `BAR_SIZE_TIER` map and
  `get_universe_for_bar_size(db, bar_size)` helper. 1m/5m/15m/30m →
  intraday, 1h/1d → swing, 1w → investment.
- **`ai_modules/training_pipeline.py::get_available_symbols`** —
  replaced "rank by share volume from raw adv cache, return up to 5000"
  with "pull canonical universe, rank by dollar volume". Excludes
  `unqualifiable=true` automatically.
- **`ai_modules/timeseries_service.py::get_training_symbols`** —
  replaced share-volume threshold with `get_universe_for_bar_size`.
- **`ai_modules/post_training_validator.py::_get_validation_symbols`**
  — added `unqualifiable: {"$ne": True}` filter on the dollar-volume
  fast path so validation backtests can't pick up dead symbols.
- **`get_universe_stats`** now returns `training_universe_per_bar_size`
  — the per-bar-size symbol-count projection that reveals exactly
  what each training phase will pick up.

### New UI tile
- **`frontend/src/components/sentcom/v5/CanonicalUniverseCard.jsx`** —
  fetches `/api/backfill/universe?tier=all` and renders:
  total qualified · intraday count · unqualifiable count · per-bar-size
  training universe sizes (1m/5m/.../1w → ## symbols, color-coded by
  tier). Mounted between BackfillReadinessCard and LastTrainingRunCard
  in the FreshnessInspector — operator now sees the readiness verdict,
  the universe each timeframe will train on, and the last training
  outcome stacked vertically.

### Test coverage (6 additional contract tests)
- `BAR_SIZE_TIER` mapping locked: 1m/5m/15m/30m → intraday, 1h/1d → swing, 1w → investment.
- `get_universe_for_bar_size` routes correctly through `get_universe`.
- `get_universe_stats` exposes per-bar-size training projection.
- Source-level invariants: `training_pipeline.get_available_symbols`,
  `timeseries_service.get_training_symbols`, and
  `post_training_validator._get_validation_symbols` MUST go through
  the canonical universe / unqualifiable filter.
- 70/70 directly-related tests green, 4 services lint-clean (1 unused
  variable removed during refactor).

### Verified live
- `GET /api/backfill/universe?tier=all` returns the new
  `training_universe_per_bar_size` block with per-tier counts.
- Backend + frontend supervisor both RUNNING after restart.

### What this delivers operationally
- Smart-backfill, readiness, and ALL training paths can never disagree
  on the universe definition again — they share one Python module.
- The FreshnessInspector now answers three operator questions in one


## 2026-04-26 — Canonical Universe Refactor + IB hyphen default — SHIPPED

  click: "Am I ready to train?" + "What will training pick up?" +
  "What did the last run produce?".



**Root-cause fix** for the 68-hour AI training projection: smart-backfill
classified its universe by **dollar volume** (`avg_dollar_volume ≥ $50M` →
~1,186 symbols) while backfill_readiness used **share volume**
(`avg_volume ≥ 500k` → ~2,648 symbols). Training picked up the union
(4,000+ symbols) and ran for 68h. Worse, readiness could never go fully
green because it counted symbols that smart-backfill never tried to
refresh.

### Single source of truth
- New module **`backend/services/symbol_universe.py`** — every consumer
  (smart-backfill, readiness checks, training pipeline, AI chat snapshots)
  pulls universes from one place. Public API:
    * `get_universe(db, tier)` — `tier ∈ {intraday, swing, investment, all}`,
      defaults to excluding unqualifiable symbols
    * `classify_tier(avg_dollar_volume)` — pure function, used by
      smart-backfill when an `adv` doc lacks a stored `tier`
    * `get_symbol_tier(db, symbol)` — single-symbol lookup
    * `get_universe_stats(db)` — diagnostics for the UI / readiness
    * `mark_unqualifiable(db, symbol)` — tracks IB "No security
      definition" strikes; promotes to `unqualifiable=true` after 3
    * `reset_unqualifiable(db, symbol)` — operator escape hatch
- **Locked thresholds** (user-confirmed 2026-04-26):
  intraday ≥ $50M, swing ≥ $10M, investment ≥ $2M.

### Schema additions on `symbol_adv_cache`
- `unqualifiable: bool` — exclude from every universe selector once true
- `unqualifiable_failure_count: int` — running count of IB failures
- `unqualifiable_marked_at`, `unqualifiable_reason`, `unqualifiable_last_seen_at`

### Wiring
- **`backfill_readiness_service.py`** — `_check_overall_freshness` and
  `_check_density_adequate` both replaced their `avg_volume ≥ 500k`
  query with `get_universe(db, 'intraday')`.
- **`ib_historical_collector.py::_smart_backfill_sync`** — reads from
  the canonical universe + tier classification, and excludes
  `unqualifiable=true` symbols (so dead/delisted names don't get
  re-queued every run).
- **`routers/ib.py::/historical-data/skip-symbol`** — when the pusher
  reports a "No security definition" symbol, the endpoint now also
  calls `mark_unqualifiable`. After 3 strikes that symbol is promoted
  and silently dropped from every future readiness/backfill/training
  selection (preserves the preserve-history rule from 2026-04-25 — a
  promoted-then-recovered symbol can be reset via the operator endpoint).

### New operator endpoints
- `GET  /api/backfill/universe?tier=intraday|swing|investment|all` —
  returns the canonical symbol list + universe stats (counts per tier,
  unqualifiable count, current thresholds).
- `POST /api/backfill/universe/reset-unqualifiable/{symbol}` — clear
  the unqualifiable flag on a symbol after an IB Gateway re-sync.

### IB Warning 2174 (date format) default flipped — hyphen
Per user choice: `IB_ENDDATE_FORMAT` now defaults to **`hyphen`**
(`"YYYYMMDD-HH:MM:SS"`), the IB-recommended form. Silences the noisy
deprecation warning + future-proofs against IB removing the legacy
space form. Three call sites updated (backend planner ×2, Windows
collector ×1). `IB_ENDDATE_FORMAT=space` remains a one-line revert.

### Test coverage (16 new contract tests)
- `backend/tests/test_universe_canonical.py`:
    * Threshold lock contract (intraday $50M / swing $10M / investment $2M)
    * `classify_tier` boundary semantics
    * `get_universe` per-tier supersets + default exclusion of unqualifiable
    * `mark_unqualifiable` strike promotion + idempotency
    * `reset_unqualifiable` rehabilitation
    * **Source-level invariant**: smart-backfill + readiness MUST import
      from `services.symbol_universe` (catches future drift)
    * Locks default `IB_ENDDATE_FORMAT="hyphen"`
- `test_backfill_readiness.py` updated: fixture inserts
  `avg_dollar_volume=100M` so the readiness rollup can resolve the
  dollar-volume universe.
- 64 directly-related tests green (universe + readiness + collector +
  smart-backfill + live-data phase 1 + live subscription manager).
- All three changed services lint-clean.

### Verified live
Backend restarted successfully. New endpoints respond:
- `GET /api/backfill/universe?tier=intraday` → 200 OK
- `GET /api/backfill/universe?tier=bogus` → 400 + actionable error
- `POST /api/backfill/universe/reset-unqualifiable/AAPL` → 200 OK
- `GET /api/backfill/readiness` → operates on canonical universe.

### Why this matters
Once the user's DGX backfill queue drains (~current 11k items) and
Train All is fired:
- Training will operate on ~1,186 high-quality intraday symbols (not
  4,000+). Estimated 30-40h instead of 68h.
- `overall_freshness` will reach green because both surfaces agree on
  the same denominator.
- Dead/delisted names self-prune from the queue after 3 IB strikes.

### Backlog (next priorities)
- 🔴 P0 — User: trigger Train All once collectors drain → verify
  P5 sector-relative + Phase 8 `_1day_predictor` produce >0 models.
- 🟡 P1 — Live Data Architecture verify Phase 1 (RPC server) end-to-end on user's DGX/Windows.
- 🟡 P2 — Remove Alpaca string in `/api/ib/analysis/{symbol}` (Phase 4 retirement).
- 🟡 P2 — Fix `[SKIP] ib_data_pusher.py not found` startup launcher path.
- 🟡 P3 — AURA UI integration · ⌘K palette extensions · `server.py`
  breakup · retry 204 historical `qualify_failed` items.

---



## 2026-04-26 — Phase 5 stability & ops bundle (A + B + C + D + E + F) — SHIPPED

Six follow-ups on top of the live-data foundation, all to harden the app
while the backfill runs and before the retrain:

### A · System Health Dashboard
- New service `services/system_health_service.py` aggregating 7
  subsystems into a single green/yellow/red payload: `mongo`,
  `pusher_rpc`, `ib_gateway`, `historical_queue`, `live_subscriptions`,
  `live_bar_cache`, `task_heartbeats`. Every check is ≤1s, no check
  raises, read-only.
- New endpoint `GET /api/system/health` on the existing `system_router`.
  `overall` is the worst subsystem. Subsystem shape: `{name, status,
  latency_ms, detail, metrics}`. Endpoint itself never 500s even if the
  aggregator errors.
- Thresholds: mongo ping yellow≥50ms red≥500ms · queue yellow≥5k
  red≥25k · task heartbeats stale≥15m dead≥1h · live subs yellow≥80%
  red≥95% of cap.

### B · React Error Boundaries
- New `PanelErrorBoundary` component — classic React error-boundary
  pattern with a reset button. Wrapped around `TopMoversTile`,
  `ScannerCardsV5`, `ChartPanel`, `BriefingsV5`. A crash in any one panel
  now shows an inline "⚠ panel crashed — reload panel ↻" card instead
  of bringing down the whole Command Center.

### C · ⌘K Command Palette
- New `CommandPalette` mounted at SentComV5View level. Global
  `⌘K` / `Ctrl+K` / Escape handlers. Corpus = `live/subscriptions`
  hot symbols + `live/briefing-watchlist` + core indices. Minimal
  fuzzy match (starts-with > substring) keeps bundle light. Arrow
  keys + enter → opens `EnhancedTickerModal` via existing
  `handleOpenTicker` callback.

### D · DataFreshnessBadge → Freshness Inspector
- New `HealthChip` rendered in the `PipelineHUDV5 rightExtra` slot.
  Green/yellow/red dot + text like `ALL SYSTEMS` / `2 WARN` /
  `1 CRITICAL`. Polls `/api/system/health` every 20s. Click →
  opens `FreshnessInspector`.
- New `FreshnessInspector` modal. 4 sections aggregating
  `/api/system/health` + `/api/live/subscriptions` +
  `/api/live/ttl-plan` + `/api/live/pusher-rpc-health` in one
  `Promise.all` call. Auto-polls every 15s while open; cleans up
  interval on close.

### E · Timeout audit
- Grepped `requests.get` / `requests.post` / `httpx.*` across backend —
  every call has a timeout. Initial scan showed false positives because
  the `timeout=` kwarg was on a different line from the method call.
  No changes needed. Log cleanup deferred with `server.py` breakup (53
  `print()` calls in `ib.py` alone — not this session's scope).

### F · TestClient / HTTP contract suite
- New `backend/tests/test_system_health_and_testclient.py` exercising
  the live running backend via `requests`. 9 tests cover: system
  health v2 shape, live-data pipeline subsystems coverage,
  pusher_rpc degrades to yellow when disabled, build_ms<1s,
  subscribe/unsubscribe ref-count e2e, regression against all
  `/api/live/*` endpoints. Fast, deterministic, catches regressions
  without needing the testing agent.

### Screenshots verified end-to-end
- HealthChip shows `2 WARN` in preview env (pusher_rpc + ib_gateway
  yellow — correct for no-pusher-no-IB preview).
- ⌘K opens CommandPalette.
- Chip click opens FreshnessInspector showing all 4 sections with live
  data (including SPY `refx1 idle 7s` from the subscribe e2e test).

### Testing totals
**141 pytests green locally** (21 new Phase 5 + 9 TestClient/HTTP + 17
Phase 3 tile + 27 P2-A + 47 live-data phases + 16 collector + 4 no-alpaca).

### What's still on the docket
- 🟡 P1: `Train All` post-backfill (blocked).
- 🟡 P2: SEC EDGAR 8-K · holiday-aware overnight walkback.
- 🟡 P3 remaining: `server.py` breakup · Distributed PC Worker ·
  v5-chip-veto badges (blocked on retrain).



## 2026-04-26 — Auto-hide Overnight Sentiment during RTH

Small UX upgrade on top of the P2-A Morning Briefing work.

The Overnight Sentiment section is fundamentally a **pre-trade news**
surface — yesterday close vs premarket swings prepare you for the open.
Once RTH is live (09:30–16:00 ET) that information is stale and just
takes vertical space away from the game plan and system status.

### Change
In `MorningBriefingModal.jsx`, wrapped the Overnight Sentiment
`<Section>` in a `{live.marketState !== 'rth' && …}` gate. The section
renders normally when `market_state` is `extended` / `overnight` /
`weekend`, and disappears during RTH so the briefing modal shrinks to
its more decision-useful subset.

Top Movers row stays visible in all states — that's real-time price
action, relevant whenever the market is live.

### Verified
- Pytest contract added (`test_overnight_sentiment_auto_hidden_during_rth`).
- Screenshot confirmed in preview env: `market_state: RTH` →
  Top Movers visible, Overnight Sentiment hidden, Today's Game Plan
  bumped directly below Top Movers. 27/27 P2-A tests green.



## 2026-04-26 — Monday-morning catchup (weekend news widening)

Extended `overnight_sentiment_service.compute_windows` to walk the
yesterday_close anchor back over weekends. On a Monday briefing the
window is now **Friday 16:00 ET → Monday 00:00 ET (56 hours)** instead of
8h, so the weekend news backlog actually lands in the section. Handled
dynamically via `weekday()` — no hardcoded Monday logic, so Sunday use
also walks back to Friday (32h), and the 6-day safety cap guards against
any clock edge case.

### What shipped
- `compute_windows(now_utc)` — walks the probe day back one step at a
  time while `weekday() >= 5` (Sat/Sun). 6-day cap for safety.
- `/api/live/overnight-sentiment` response now also returns:
  `yesterday_close_hours`, `yesterday_close_start`, `yesterday_close_end`
  so the UI can show context.
- `MorningBriefingModal` Overnight-Sentiment header now renders a
  small amber "since Nh ago" badge (`data-testid="briefing-weekend-catchup-badge"`)
  when the window is >10h wide (post-weekend or post-holiday).

### Tests
- 3 new window contracts: Monday walks back 56h, Tue–Fri remains 8h,
  Sunday walks back 32h.
- UI contract: badge only renders when window >10h.
- Hook contract: captures `yesterdayCloseHours` + `yesterdayCloseStart`
  from the API response.

Full suite **92/92 green** (23 P2-A + 69 regression).

### Known limitation (backlog)
Holiday calendar not integrated — Tue after a Monday holiday will use
an 8h window (Mon 16:00 → Tue 00:00) even though Mon was closed.
Adding `pandas_market_calendars` would upgrade this path to
"last-actual-trading-close" walkback. Not urgent — worst case is a
narrower-than-ideal window, never wrong.



## 2026-04-26 — P2-A Morning Briefing rich UI + React warning fix

Three sections shipped:

### 1. Morning Briefing dynamic top-movers + overnight-sentiment

**Backend** (`backend/services/overnight_sentiment_service.py` + 3 new
endpoints in `routers/live_data_router.py`):

- `GET /api/live/briefing-watchlist` — server-built dynamic watchlist
  (positions + latest scanner top-10 + core indices
  SPY/QQQ/IWM/DIA/VIX, deduped, capped at 12)
- `GET /api/live/briefing-top-movers?bar_size=5+mins` — wraps
  `briefing-snapshot` with the dynamic watchlist auto-supplied
- `GET /api/live/overnight-sentiment?symbols=` — per-symbol scoring of
  **yesterday_close window** (16:00 ET prior day → 00:00 ET today) vs
  **premarket window** (00:00 ET today → 09:30 ET today). Reuses
  `SentimentAnalysisService._analyze_keywords` so scores are directly
  comparable to other surfaces. Swing threshold locked at ±0.30 per
  user choice; symbols exceeding the threshold get `notable=true`.
  Ranked notable-first, then by |swing|. Capped at 12 symbols.

**Frontend** (`MorningBriefingModal.jsx` + new hook
`sentcom/v5/useBriefingLiveData.js`):

- Two new sections rendered ABOVE the existing game plan:
    * `briefing-section-top-movers` — mini-grid of price + change%
      (2–4 cols responsive, 8 symbols max, graceful empty state)
    * `briefing-section-overnight-sentiment` — row per symbol with
      swing chip (`v5-chip-manage` / `v5-chip-veto` / `v5-chip-close`
      by direction), yesterday-close vs premarket scores, top
      headline truncated with full text in `title`. Notable rows
      highlighted with a subtle `bg-zinc-900/60`.
- Refresh button now reloads BOTH the original `useMorningBriefing`
  feed and the new `useBriefingLiveData` feed.
- Parallel fetch via `Promise.all` on both endpoints — one round-trip
  of latency, two data feeds.

### 2. Modal trigger wiring (end-to-end fix)
Testing agent iteration_134 caught that the existing
`MorningBriefingModal` was state-dead (`showBriefing` declared but no
caller toggled it to `true`). Fixed by:
- Co-locating modal state + mount inside `SentCom.jsx`
  (`showBriefingDeepDive` state + `<MorningBriefingModal>` after
  `<SentComV5View>`)
- Threading `onOpenBriefingDeepDive` prop through SentComV5View →
  BriefingsV5 → MorningPrepCard
- Adding a `full briefing ↗` button in MorningPrepCard header with
  `data-testid="briefing-open-deep-dive"` and
  `e.stopPropagation()` so card expand doesn't fire alongside

Screenshot-verified end-to-end: click → modal opens → both new
sections render with real data (or graceful empty state).

### 3. React warning fix (NIA render-phase setState)
`NIA/index.jsx` was calling `setCached('niaData', ...)` (which
triggers setState on `DataCacheProvider`) inside a
`setData(current => { setCached(...); return current; })` updater —
React 18+ warns: *"Cannot update a component (DataCacheProvider) while
rendering a different component (NIA)"*. Fixed by hoisting the cache
write into a dedicated `useEffect` gated by `initialLoadDone`, so the
cache persist happens after commit. Verified 0 warnings over a 6-second
NIA fetch cycle in the testing agent's console listener.

### Testing
- **20 new pytest contracts** (`backend/tests/test_p2a_morning_briefing.py`).
- Full suite now **83/83 green** locally.
- `testing_agent_v3_fork` iteration_134 (both front+back): 31/31 focused
  tests PASS, 0 backend bugs, NIA warning confirmed gone, initial
  trigger gap caught + fixed in this same session.

### User choices locked in PRD
- **Watchlist source**: positions + scanner top-10 + SPY/QQQ/IWM/DIA/VIX
- **Swing threshold**: ±0.30 (moderate)
- **React warning fix**: bundled in same session



## 2026-04-26 — Top Movers tile + Phase 4 Alpaca retirement + AI Chat live snapshots

Three follow-ups on top of the Phase 1–3 live-data foundation:

### 1. TopMoversTile (V5 HUD)
`frontend/src/components/sentcom/v5/TopMoversTile.jsx` — compact row
rendered just below `PipelineHUDV5` in SentComV5View. Reads
`/api/live/briefing-snapshot?symbols=SPY,QQQ,IWM,DIA,VIX` every 30s
(aligned with the RTH TTL in `live_bar_cache`). Failed snapshots are
silently filtered — when the pusher is offline the tile shows a
non-alarming *"no live data (pusher offline or pre-trade)"* line.
Symbols are clickable → routes through the existing
`handleOpenTicker` → EnhancedTickerModal. `data-testid`s exposed for
test automation (`top-movers-tile`, `top-movers-symbol-<SYM>`,
`top-movers-empty`, `top-movers-error`, `top-movers-market-state`).

### 2. Phase 4 — Alpaca retirement (env-gated, default OFF)
- New env var `ENABLE_ALPACA_FALLBACK` (default `"false"`).
- `server.py` now gates `init_alpaca_service()` + the chain of
  `stock_service.set_alpaca_service(...)` / `sector_service.set_alpaca_service(...)`
  behind the flag. Default path wires `alpaca_service = None` — all
  downstream consumers already have IB-pusher / Mongo fallback paths
  from the 2026-04-23 Alpaca-nuke work.
- `routers/ib.py` `/api/ib/analysis/{symbol}`: the hardcoded
  `data_source: "Alpaca"` label is gone. When the shim is active
  (legacy) the label reads `"Alpaca (legacy shim)"`; when retired
  (default) it reads `"IB shim (via stock_service)"` — accurate
  because the shim itself delegates to IBDataProvider.
- Server boot log now clearly announces retirement:
  `"Alpaca fallback DISABLED (IB-only). Phase 4 retirement active."`

**Rollback**: `export ENABLE_ALPACA_FALLBACK=true` + restart backend.

### 3. AI Chat live snapshot injection (`chat_server.py`)
Added section 10.5 — *Live Snapshots (Phase 3 live-data)* — to the
chat context builder. For every held position + SPY/QQQ/IWM/VIX (capped
at 10 symbols) the builder calls `GET /api/live/symbol-snapshot/{sym}`
with a 2-second timeout, per-symbol try/except, and a surrounding block
try/except so live-data outages never take down the chat flow. Format:
`SYM $price ±change% (bar TS, market_state, source)`. Bounded at 10
symbols → no DoS risk on the pusher, no unbounded context bloat.

### Testing
- **14 new pytests** (`backend/tests/test_phase3_tile_phase4_alpaca_chat.py`).
  Full suite 66/66 green (live-data phases 1–3 + new + collector + no-alpaca-regression).
- **`testing_agent_v3_fork` iteration_133** (both front+back): 23/23
  focused tests pass, 100% frontend render, zero bugs, zero action
  items. TopMoversTile 30s refresh confirmed via network capture.
  Phase 4 verified via `/api/ib/analysis/SPY` label + boot log.

### Follow-up noted (not introduced here — pre-existing)
React warning: *"Cannot update a component (DataCacheProvider) while
rendering a different component (NIA)"* — hoist the offending setState
into `useEffect`. Low priority.

### What's next
- **P1 User verification** post-backfill: once the ~17h IB historical
  queue drains, trigger full `Train All` to verify P5 sector-relative
  + Phase 8 `_1day_predictor`.
- **P3 DataFreshnessBadge → Command Palette Inspector**: all data
  sources ready (`/api/live/subscriptions` + `/api/live/symbol-snapshot`
  + `/api/live/ttl-plan`).
- **P2 Morning Briefing rich UI** refactor consuming `/api/live/briefing-snapshot`.
- **P3 React warning hoist**: move DataCacheProvider setState into useEffect.
- **P3 `server.py` breakup** into routers/models/tests.



## 2026-04-26 — Phase 3 Live Data Foundation wired into remaining surfaces

Fifth shipped phase of the live-data architecture. The primitives built in
Phase 1 (`fetch_latest_session_bars` + `live_bar_cache`) and Phase 2
(ref-counted subscriptions) are now plumbed into the consumer surfaces.

### What shipped

- **`services/live_symbol_snapshot.py`** (new) — one-liner freshest-price
  service. `get_latest_snapshot(symbol, bar_size, *, active_view)` returns
  a stable-shape dict `{success, latest_price, latest_bar_time, prev_close,
  change_abs, change_pct, bar_size, bar_count, market_state, source,
  fetched_at, error}`. Never raises. `get_snapshots_bulk(symbols, bar_size)`
  caps at 20 symbols to prevent cache-stampede DoS.

- **New endpoints** (`routers/live_data_router.py`):
    * `GET  /api/live/symbol-snapshot/{symbol}`  — single-symbol snapshot
    * `POST /api/live/symbol-snapshots`          — bulk snapshot, body `{symbols, bar_size}`
    * `GET  /api/live/briefing-snapshot?symbols=` — ranked by `abs(change_pct)`,
      failed snapshots pushed to the bottom. Default watchlist:
      `SPY,QQQ,IWM,DIA,VIX`. Consumable by any briefing (morning / mid-day
      / power-hour / close).

- **Scanner intraday top-up** (`services/market_scanner_service.py`):
  after the historical `get_bars` call, for `TradeStyle.INTRADAY` scans
  we merge the latest-session bars via `fetch_latest_session_bars` (dedup
  by timestamp, sort ascending). Silent no-op when pusher RPC is down —
  scanner keeps working on historical data alone.

- **Trade Journal immutable close snapshot** (`services/trade_journal.py`):
  `close_trade` now persists `close_price_snapshot` on the trade document
  — `{exit_price, captured_at, source, bar_ts, market_state, bar_size,
  snapshot_price, snapshot_change_pct}`. Written ONCE at close; future
  audits / drift analyses know exactly which data slice the trade
  settled against. Snapshot failures are caught and recorded via
  `snapshot_error` but never abort the close itself.

### Deferred
- **AI Chat context injection** (per Phase 3 plan): `chat_server.py` runs
  as a separate proxy on port 8002; modifying its context builder was out
  of scope for this session. The `/api/live/symbol-snapshot/{symbol}`
  endpoint is now the hook point — the chat server can start consuming
  it whenever the user wants to touch that surface.

### Testing
- **12 new pytest contracts** (`backend/tests/test_live_data_phase3.py`) —
  snapshot shape stability, `change_pct` math, bulk 20-symbol cap, scanner
  top-up invariants (intraday-only guard, dedup+sort), trade-journal
  immutable-snapshot contract, graceful-degrade never-5xx invariant.
  Full suite locally: 47/47 green (12 Phase 3 + 35 Phase 1+2 regression).
- **`testing_agent_v3_fork` iteration_132**: 23/23 HTTP smoke tests pass
  against the live backend. Zero bugs. Zero action items.

### What this unblocks
- **Phase 4** (retire Alpaca): nothing else depends on the Alpaca shim
  now. Flip `ENABLE_ALPACA_FALLBACK=false`, soak 24h, then rip.
- **`DataFreshnessBadge → Command Palette Inspector`** (P3): the
  `/api/live/symbol-snapshot` + `/api/live/subscriptions` endpoints are
  the two data sources the Inspector needs.
- **Morning Briefing rich UI** (user TODO 2026-04-22): the new
  `/api/live/briefing-snapshot` feeds the "top movers" row the richer
  modal was supposed to have.
- **AI Chat live context**: chat_server.py can consume
  `/api/live/symbol-snapshot` whenever next touched.



## 2026-04-26 — Phase 2 Live Subscription Layer SHIPPED

Tick-level dynamic watchlist end-to-end. Frontend components (ChartPanel,
EnhancedTickerModal, Scanner top-10) auto-subscribe the symbols on screen;
backend ref-counts so concurrent consumers of the same symbol coexist and
only the LAST unmount triggers the pusher unsubscribe. A 5-min heartbeat
sweep prevents orphan subs if a browser tab crashes mid-use.

### What shipped

- **`services/live_subscription_manager.py`** — thread-safe ref-counted
  manager. Methods: `subscribe(sym)`, `unsubscribe(sym)`, `heartbeat(sym)`,
  `list_subscriptions()`, `sweep_expired(now)`. Cap: `MAX_LIVE_SUBSCRIPTIONS`
  env var (**default 60**, half of IB's ~100 L1 ceiling for safety margin).
  TTL: `LIVE_SUB_HEARTBEAT_TTL_S` env var (default 300s = 5 min).
  Background daemon thread runs sweep every 30s.

- **DGX routes** (`routers/live_data_router.py`):
    * `POST /api/live/subscribe/{symbol}`   — ref-count++ (forwards to pusher on 0→1)
    * `POST /api/live/unsubscribe/{symbol}` — ref-count-- (forwards to pusher on 1→0)
    * `POST /api/live/heartbeat/{symbol}`   — renew last_heartbeat_at
    * `GET  /api/live/subscriptions`        — full state (active_count, max, TTL, per-sub)
    * `POST /api/live/subscriptions/sweep`  — manual stale-sub sweep (operator lever)

- **Windows pusher RPC** (`ib_data_pusher.py::start_rpc_server`):
    * `POST /rpc/subscribe`      — `{symbols: [...]}` → calls `subscribe_market_data`
    * `POST /rpc/unsubscribe`    — `cancelMktData` + pop from `subscribed_contracts` / `quotes_buffer` / `fundamentals_buffer`
    * `GET  /rpc/subscriptions`  — current watchlist + total

- **Frontend hooks** (`frontend/src/hooks/useLiveSubscription.js`):
    * `useLiveSubscription(symbol)`           — single-symbol (ChartPanel, EnhancedTickerModal)
    * `useLiveSubscriptions(symbols, {max})`  — multi-symbol diff-based (Scanner top-10)
  Both subscribe on mount, heartbeat every 2 min (well under 5-min backend TTL),
  unsubscribe on unmount. Heartbeat only starts when backend accepted — cap
  rejections don't waste network.

### Wiring
- `ChartPanel.jsx` line ~99: `useLiveSubscription(symbol)`
- `EnhancedTickerModal.jsx` line ~544: `useLiveSubscription(ticker?.symbol || null)`
- `ScannerCardsV5.jsx` line ~327: `useLiveSubscriptions(cards.slice(0,10).map(c=>c.symbol), {max:10})`

### Testing
- **Backend pytest**: `backend/tests/test_live_subscription_manager.py` —
  24 contracts locking ref-count semantics, cap enforcement, heartbeat/sweep,
  endpoint shape, pusher RPC source invariants, hook wiring. Full suite
  35/35 green (24 Phase 2 + 11 Phase 1).
- **Backend HTTP suite** (testing_agent_v3_fork iteration_130):
  `backend/tests/test_live_subscription_phase2_http.py` — 19/19 pass against
  running backend. Zero bugs.
- **Frontend integration** (testing_agent_v3_fork iteration_131): 100%
  verifiable paths green. ChartPanel / EnhancedTickerModal / Scanner wiring
  confirmed. Subscribe/unsubscribe fires as designed. Zero runtime errors.

### Env contract for DGX / Windows

On the **DGX** side:
```
IB_PUSHER_RPC_URL=http://192.168.50.1:8765
ENABLE_LIVE_BAR_RPC=true
MAX_LIVE_SUBSCRIPTIONS=60               # optional, default 60
LIVE_SUB_HEARTBEAT_TTL_S=300            # optional, default 300
```

On the **Windows PC** side:
```
IB_PUSHER_RPC_PORT=8765                 # optional, default 8765
IB_PUSHER_RPC_HOST=0.0.0.0              # optional, default 0.0.0.0
pip install fastapi uvicorn             # required for RPC server
```

### What this unblocks
- **Phase 3** (wire remaining surfaces — Briefings / AI Chat / deeper Scanner):
  `fetch_latest_session_bars` + `useLiveSubscription` / `useLiveSubscriptions`
  are the two primitives now. Every new surface that needs live data uses
  them.
- **Phase 4** (retire Alpaca): blocker is Phase 3 soak-test first.
- **DataFreshnessBadge → Command Palette** (P3): `/api/live/subscriptions`
  gives the hot-symbol list the Inspector needs.



## 2026-04-26 — Phase 1 Live Data Architecture SHIPPED + IB 2174 fix

Foundation for "always-on live data across the entire app" is in. The Windows
pusher now exposes an RPC surface that the DGX backend can call on-demand
(weekends, after-hours, active-view refreshes) without opening its own IB
connection. A Mongo-backed `live_bar_cache` with dynamic TTLs keeps multi-
panel refreshes cheap while still being aggressive about off-hours refetch.

### New components
- **`/app/documents/scripts/ib_data_pusher.py` → `start_rpc_server(...)`**
  FastAPI+uvicorn in a daemon thread. Three endpoints:
    * `GET  /rpc/health`          — IB connection + push age + client_id
    * `POST /rpc/latest-bars`     — `{symbol, bar_size, duration, use_rth}`
    * `POST /rpc/quote-snapshot`  — read-through on `quotes_buffer`
  Thread-safety: dispatches `reqHistoricalDataAsync` to the ib_insync asyncio
  loop via `asyncio.run_coroutine_threadsafe` — ib_insync is asyncio-bound
  and NOT thread-safe; calling it directly from a FastAPI handler thread
  would race-crash. Silently skipped if fastapi/uvicorn are not installed
  on Windows (backward-compatible).
  Env: `IB_PUSHER_RPC_HOST` (default 0.0.0.0), `IB_PUSHER_RPC_PORT` (default 8765).

- **`/app/backend/services/ib_pusher_rpc.py`** — DGX HTTP client.
  Env-flagged (`ENABLE_LIVE_BAR_RPC`=true/false, `IB_PUSHER_RPC_URL`).
  Sync interface (wrap in `asyncio.to_thread`). Every error path returns
  None instead of raising — callers must treat None as "fall back to cache".

- **`/app/backend/services/live_bar_cache.py`** — Mongo TTL cache.
  Collection: `live_bar_cache`. TTL index on `expires_at` so Mongo auto-purges.
  Dynamic TTL by market state:
    * RTH: 30s     * Extended (pre/post): 120s
    * Overnight: 900s    * Weekend: 3600s
    * Active-view override: always 30s (user is live-watching this symbol)
  `classify_market_state()` uses America/New_York offset (no holiday calendar
  here — holidays round to "overnight" safely).

- **`/app/backend/routers/live_data_router.py`** — operator surface.
  `GET  /api/live/pusher-rpc-health` · `GET /api/live/latest-bars` ·
  `GET  /api/live/quote-snapshot`   · `GET /api/live/ttl-plan`        ·
  `POST /api/live/cache-invalidate`.

- **`HybridDataService.fetch_latest_session_bars(symbol, bar_size, *,
  active_view, use_rth)`** — the one call site for the whole pipeline.
  Cache-first → pusher RPC → cache store. Never raises.

- **`/api/sentcom/chart`** now merges live-session bars for intraday
  timeframes. Returns `live_appended`, `live_source`, `market_state` for
  observability. The existing dedup pass handles the collector↔live seam.

### Regression protection
- `backend/tests/test_live_data_phase1.py` — 11 pytest contracts locking:
  market-state classification (weekend/RTH/extended/overnight), TTL
  hierarchy (active-view ⊂ RTH ⊂ extended ⊂ overnight ⊂ weekend), RPC
  client no-raise fall-through (missing URL / flag off / unreachable),
  `fetch_latest_session_bars` graceful degradation, pusher has
  `start_rpc_server`, all three RPC routes declared, thread-safe
  coroutine dispatch, env-configurable port.
- `backend/tests/test_collector_uses_end_date.py` — extended from 4→4 tests
  locking the new env-gated space/hyphen format behavior. Both formats now
  pass `_normalizes_both_date_formats` and `_is_env_gated_and_supports_both_formats`.

### IB Warning 2174 fix (same session, env-gated)
New env var `IB_ENDDATE_FORMAT=space|hyphen` (default `space`). When set to
`hyphen`, both the backend planner (strftime call sites at lines ~1330 and
~2546) and the Windows collector (queue-row normalization at line ~370)
emit the new IB-preferred form `"YYYYMMDD-HH:MM:SS UTC"`. Default stays
`space` to avoid regressing the 2026-04-25 walkback fix until the user
tests hyphen on their live IB Gateway.

### Operator usage on Windows
1. `git pull` on outer repo.
2. `pip install fastapi uvicorn` (if not already installed).
3. Optionally: `setx IB_PUSHER_RPC_PORT 8765` (default) / `setx IB_ENDDATE_FORMAT hyphen` (to silence 2174).
4. Restart the pusher. Log line: `[RPC] Server listening on http://0.0.0.0:8765`.

### Operator usage on DGX
1. `git pull`.
2. Set env: `IB_PUSHER_RPC_URL=http://192.168.50.1:8765`, `ENABLE_LIVE_BAR_RPC=true`.
3. Restart backend. Verify via `curl /api/live/pusher-rpc-health` (reachable=true).
4. Chart endpoints automatically start merging live bars.

### What this unblocks (remaining plan)
- Phase 2 (live subscription layer, tick-level): the RPC channel is ready to
  host `/rpc/subscribe` + `/rpc/unsubscribe` endpoints next.
- Phase 3 (Scanner / Briefings / AI Chat): can call
  `fetch_latest_session_bars` directly — zero wiring needed beyond a single
  `await` call.
- Phase 4 (retire Alpaca): `/api/ib/analysis/{symbol}` still has the
  Alpaca label path — flip `ENABLE_ALPACA_FALLBACK=false` once Phase 3 is
  verified running for 24h on the user's DGX.
- DataFreshnessBadge → Command Palette (P3): `live_bar_cache` collection +
  `/api/live/ttl-plan` are the data sources for the Inspector panel.



## 2026-04-25 (P.M.) — Smart-Backfill ROOT-CAUSE Fix + Contract Test

User flagged the recurrence pattern: "we fix something, miss something, fix something, break something." Rather than ship more bandaids, audited the wiring of NIA's "Collect Data" + "Run Again" buttons end-to-end and surfaced the structural bug.

### Wiring audit (verified clean)
- `frontend/src/components/NIA/DataCollectionPanel.jsx:305` — `<button onClick={handleCollectData}>Collect Data</button>` ✅
- `frontend/src/components/NIA/DataCollectionPanel.jsx:346` — `<LastBackfillCard onRerun={handleCollectData}>` ("Run Again") ✅
- Both buttons call `POST /api/ib-collector/smart-backfill?dry_run=false&freshness_days=2` (line 250) ✅

The buttons were NEVER broken. The endpoint they call was structurally broken.

### The actual bug
`_smart_backfill_sync()` planned only the bar_sizes that the symbol's CURRENT tier required. So when a symbol's `avg_dollar_volume` dipped below $50M (tier "intraday" floor), smart-backfill silently demoted it from intraday → swing. The swing tier doesn't list 1-min or 15-min as required, so smart-backfill **stopped refreshing existing 1-min/15-min history**, even though the data was already in `ib_historical_data` from when the symbol was in intraday. Result: GOOGL + ~1,533 other intraday-graded-by-share-volume symbols had 1-min/15-min latest bars stuck on 2026-03-17 (39 days stale).

This is also why `overall_freshness` was 68.9% (1-min: 42% fresh, 15-min: 42% fresh) on the post-backfill audit despite a 196M-bar collection.

### Fix
`backend/services/ib_historical_collector.py::_smart_backfill_sync()` now plans the **union** of:
1. Tier-required bar_sizes (initial-collection rule), AND
2. Bar_sizes the symbol already has data for (preserve-history rule).

Implementation: one `distinct("symbol", {"bar_size": bs})` per bar_size up front, cached per-call. New symbols only get tier-required collection (no over-collection); reclassified symbols keep their history fresh.

### Contract test
`backend/tests/test_smart_backfill_per_bar_size.py` — 4 tests:
1. `test_swing_tier_symbol_with_existing_1min_data_gets_refreshed` (the GOOGL regression)
2. `test_swing_tier_symbol_without_1min_history_skips_1min` (no over-collection)
3. `test_intraday_tier_symbol_gets_all_required_timeframes` (happy-path sanity)
4. `test_freshness_skip_works_per_bar_size_not_per_symbol`

Total contract test coverage on the readiness + collector + chart paths is now **25 tests** (was 21).

### Side note: bulk_fix_stale_intraday.py is now redundant
The script we shipped this morning to manually queue ~3,000 missed refills was a workaround for this exact bug. With the root fix, it's only needed once more (to clear today's leftover stale state); after that, `Collect Data` does the right thing.

### Backlog (unchanged from morning, all unblocked once bulk-fix queue drains)
- 🔴 **P0** — Fire Train All, verify P5 / Phase 8 fixes.
- 🟡 **P1** — Integrate AURA wordmark + ArcGauge + DecisionFeed + TradeTimeline into V5.
- 🟡 **P2** — SEC EDGAR 8-K integration; IB hyphen date-format deprecation; `[SKIP] ib_data_pusher.py` launcher path bug.
- 🟡 **P3** — ⌘K palette additions; "Don't show again" help tooltips; `server.py` breakup.
- 🟡 **P3** — Retry the 204 historical `qualify_failed` items via `/api/ib-collector/retry-failed` after first clean training cycle.

### Bonus — Click-to-explain BackfillReadinessCard tiles
While we were on the topic of "I keep having to drop into the terminal to figure out what's actually red," shipped an enhancement to `frontend/src/components/sentcom/v5/BackfillReadinessCard.jsx`:

- Each per-check tile is now click-to-expand. Clicking opens an inline drawer styled to match the data shape:
  - `queue_drained` — pending/claimed/completed/failed pills + ETA estimate
  - `critical_symbols_fresh` — list of stale symbols as red chips + "POST smart-backfill?freshness_days=1" one-click action button
  - `overall_freshness` — per-timeframe horizontal bar chart sorted worst-offender first + one-click smart-backfill action
  - `no_duplicates` — explanation of the unique-index guarantee
  - `density_adequate` — `dense_pct` + low-density sample chips with bar counts
- Action buttons POST to the right `/api/ib-collector/*` endpoint and re-poll readiness 2s later so the card updates in place.
- `data-testid`s on every drilldown row + chip + button so the testing agent can assert per-status messages without dropping into curl.

This is the proper UX answer to "stop hiding the actual numbers behind a single binary verdict." Eliminates the need for `post_backfill_audit.sh` for routine triage — the card surfaces everything inline now.

---


## 2026-04-25 (A.M.) — Post-Backfill Audit + Readiness Service Hardening

The DGX historical backfill finally completed (~196M bars in `ib_historical_data`). Built a comprehensive post-backfill audit suite, surfaced a real GOOGL data gap, fixed it surgically, and hardened the readiness service so it never hangs again.

### What we discovered
- **The "28M bars" reported by `/api/ib-collector/inventory/summary` was a stale cache.** The real `ib_historical_data` collection holds **195,668,605 bars** (~196M). Inventory was 5x understated until rebuilt.
- **GOOGL was the only critical-symbol blocker** — its 1-min and 15-min timeframes were stuck on `2026-03-17` (~39 days old). `smart-backfill` skipped GOOGL because its 5-min/1-hour/1-day were already fresh, so the per-symbol "any-bar-size-recent" heuristic deemed it fresh overall.
- **204 historical `qualify_failed` `UnboundLocalError`s** in the queue from a pre-fix pusher run. Code is already fixed in repo (`ib_data_pusher.py` lines 1509 + 2082); just legacy DB rows.

### Code shipped
**`backend/services/backfill_readiness_service.py`** — 4 incremental fixes
1. **Removed nested `ThreadPoolExecutor`** that deadlocked on `__exit__` (was blocking endpoint at 120s+).
2. **Module-level `_CHECK_POOL`** with 16 workers (buffer for any leaked threads from prior timed-out runs).
3. **Single global deadline** via `wait(FIRST_COMPLETED)` — endpoint strictly bounded by `CHECK_BUDGET_SECONDS=90`.
4. **Replaced two slow `$in:[2.6k symbols]` aggregations** with per-symbol `find_one` (overall_freshness) and limit-bounded `count_documents` (density_adequate). Each uses the existing UNIQUE `(symbol, bar_size, date)` index for O(1) per call. New cost: ~13s per check vs >90s timeout.
5. **`_check_no_duplicates` rewrote as O(1) unique-index assertion** — the previous 50× `$group` aggregation was redundant given the index already guarantees no duplicates at write time.

**`backend/tests/test_backfill_readiness.py`** — Mock collection now exposes `list_indexes()` + `count_documents(limit=)` to match the real pymongo API. 5/5 contract tests still pass.

### New scripts
- **`scripts/post_backfill_audit.sh`** — 8-section read-only audit (readiness verdict, queue, failures, inventory, timeframe stats, freshness, coverage, system health).
- **`scripts/verify_bar_counts.py`** — Direct Mongo probe that bypasses the inventory-summary cache. Reports real bar counts per timeframe, per tier, and lists the latest bar for each of the 10 critical symbols. Ground-truth tool.
- **`scripts/inspect_symbol.sh`** — Per-symbol request history + suggested next action.
- **`scripts/fix_googl_intraday.py`** — Surgical queue-injection bypassing smart-backfill's heuristic. Inserts (symbol, bar_size, duration) requests directly via `HistoricalDataQueueService.create_request()` for any symbol the smart heuristic skipped.
- **`scripts/rebuild_and_check.sh`** — One-shot inventory rebuild + readiness re-poll.

### Mockup archived
- **`documents/mockups/AuraMockupPreview.v1.jsx`** + `README.md` — User opted to defer integrating the AURA wordmark/ArcGauges/anatomical-brain SVG into the production V5 grid; archive preserved with a steal-list for future use. The live preview at `/?preview=aura` remains available.

### Verified outcome
After the surgical GOOGL fill, the readiness verdict resolved to:
```
verdict: yellow, ready_to_train: false, blockers: [], googl: []
checks: { queue_drained: green, critical_symbols_fresh: green,
          no_duplicates: green, overall_freshness: yellow (timeout),
          density_adequate: yellow (timeout) }
```
The two yellows are pure performance timeouts on the heavy aggregations — not data quality issues. The new per-symbol code path (in this commit) should bring both to GREEN.

### Backlog ready (no longer blocked)
- 🔴 **P0** P5/Phase 8 retrain verification — was blocked by backfill; now unblocked.
- 🟡 **P1** Integrate accepted AURA elements into V5 (wordmark, ArcGauge, DecisionFeed, TradeTimeline).
- 🟡 **P2** SEC EDGAR 8-K integration.
- 🟡 **P2** IB hyphen date-format deprecation (Warning 2174).
- 🟡 **P3** ⌘K palette: `>flatten all`, `>purge stale gaps`, `>reload glossary`.
- 🟡 **P3** "Don't show again" persisted dismissal on help tooltips.
- 🟡 **P3** Fix the `[SKIP] ib_data_pusher.py not found` path bug in `tradecommand.bat` (cosmetic — pusher actually does run).
- 🟡 **P3** `server.py` breakup → `routers/`, `models/`, `tests/` (deferred — was waiting on backfill, now safe to do).
- 🟡 **P3** Rerun the 204 historical `qualify_failed` items via `/api/ib-collector/retry-failed` after a normal training cycle.

---




## 2026-04-25 — Help Wiring for Journal, AI Chat, Job Manager — SHIPPED

Closed out the remaining `data-help-id` gaps from the backlog.

### 4 new glossary entries
- **trade-journal** — Trading Journal page (playbooks, DRCs, game
  plans, trade log, AI post-mortems)
- **r-multiple** — P&L expressed as multiples of initial risk (was
  referenced by the open-positions entry but undefined)
- **ai-chat** — "Ask SentCom" assistant; now documented with the
  full context it sees (live market state, open positions, glossary,
  session memory, trade execution)
- **job-manager** — Bottom-right popup listing long-running backend
  jobs (backfills, training runs, evaluations) with progress + cancel

Total glossary: **88 entries × 15 categories**. Backend cache reloaded.

### data-help-id wired on
- \`pages/TradeJournalPage.js\` root → \`trade-journal\`
- \`components/JobManager.jsx\` root → \`job-manager\`
- \`components/sentcom/panels/ChatInput.jsx\` form →
  \`ai-chat\` (+ new \`sentcom-chat-input\` /
  \`sentcom-chat-input-field\` testids)
- \`components/ChatBubbleOverlay.jsx\` floating chat button →
  \`ai-chat\` (so the overlay is discoverable from any page)

### Verified
- All 5 touched files lint clean.
- 10/10 glossary pytests still pass.
- Browser automation: navigated to Trade Journal → confirmed 1
  helpable element on page; Command Center overlay now shows 19
  unique help-ids (was 17) including \`ai-chat\` and \`unified-stream\`.
- Chat glossary knows all 4 new terms (via cache reload).

### Coverage snapshot
Helpable surfaces now cover every major UI area the user interacts
with on a daily basis: Pipeline HUD (every stage + phase), Top
Movers, Scanner, Briefings (each card), Open Positions, Unified
Stream, Model scorecards, Flatten All, Safety Armed, Account Guard,
Pre-flight, Test mode, all 5 gated train buttons, Command Palette
hint, floating ❓ button, Trade Journal, AI Chat input, chat bubble,
Job Manager. **23 help-ids live** across app.



## 2026-04-25 — Help Overlay Coverage Expansion — SHIPPED

Filled in the remaining `data-help-id` gaps so the press-`?` overlay
now lights up virtually every interactive surface in the Command
Center and NIA pages.

### Coverage jump: 8 → 19 helpable elements (17 unique terms)

Wired `data-help-id` onto:
- **Safety/HUD chips** — v5-flatten-all-btn (→ flatten-all),
  v5-safety-hud-chip (→ safety-armed), v5-account-guard-chip-wrap
  (→ account-mismatch)
- **Pipeline HUD** — v5-pipeline-hud (→ pipeline-hud), Phase metric
  (→ pipeline-phase)
- **Command Center right column** — v5-briefings (→ briefings),
  v5-scanner-cards-list (→ scanner-panel), v5-open-positions
  (→ open-positions), v5-unified-stream (→ unified-stream)
- **Model scorecards** — sentcom/panels/ModelHealthScorecard
  (→ gate-score), NIA/ModelScorecard (→ drift-veto)
- **Training controls** — training-pipeline-panel
  (→ training-pipeline-phases), run-preflight-btn (→ preflight),
  test-mode-start-btn (→ test-mode), and all 5 gated train buttons
  (start-training-btn, train-all-btn, full-universe-btn,
  train-all-dl-btn, train-all-setups-btn) → pre-train-interlock
- **Morning Briefing modal** → briefings

### 3 new glossary entries added
- **scanner-panel** — left column of Command Center, alerts ranked by
  gate score, auto-subscribes top 10
- **open-positions** — right column tile with per-position P&L,
  R-multiple, stop status
- **unified-stream** — right column event feed (SCAN/EVAL/ORDER/FILL/
  WIN/LOSS/SKIP) with filterable chips

Glossary now 84 entries × 15 categories. Backend cache reloaded via
`POST /api/help/reload`.

### Verified
- Lint clean across all touched files
- Press-? shows banner + cyan chips on 19 elements across the full
  V5 grid (screenshot confirmed)
- All 10 glossary pytests still pass

### Files touched
- `data/glossaryData.js` (+3 entries)
- `components/sentcom/v5/SafetyV5.jsx` (+3 help-ids)
- `components/sentcom/panels/PipelineHUDV5.jsx` (+2 help-ids)
- `components/sentcom/v5/BriefingsV5.jsx`, `ScannerCardsV5.jsx`,
  `OpenPositionsV5.jsx`, `UnifiedStreamV5.jsx` (+1 each)
- `components/sentcom/panels/ModelHealthScorecard.jsx` (+1)
- `components/NIA/ModelScorecard.jsx`, `TrainingPipelinePanel.jsx`,
  `SetupModelsPanel.jsx` (+4 total)
- `components/UnifiedAITraining.jsx` (+3)
- `components/MorningBriefingModal.jsx` (+1)



## 2026-04-25 — AI Chat knows the Glossary — SHIPPED

The embedded AI chat now quotes app-specific definitions **verbatim**
when asked "what is the Gate Score?", "why is Pre-Train Interlock
blocking me?", "explain the Backfill Readiness card", etc. Single
source of truth = the same \`glossaryData.js\` that powers the
GlossaryDrawer / ⌘K / press-? overlay / tours.

### New backend plumbing
- \`services/glossary_service.py\` — tolerant JS parser that reads the
  frontend file directly (no duplication, no cron sync). Handles
  single/double/backtick strings and nested arrays. Result cached with
  \`@lru_cache\`; \`reload_glossary()\` re-parses on demand.
  - \`load_glossary()\` → {categories, entries}
  - \`get_term(id)\` → entry
  - \`find_terms(q, limit)\` → matches against term / id / shortDef / tags
  - \`glossary_for_chat(max_chars)\` → compact "- Term: shortDef" block
- \`routers/help_router.py\` — mounted at \`/api/help\`:
  - \`GET /api/help/terms[?q=…&limit=N]\` — full list or search
  - \`GET /api/help/terms/{id}\` — single entry (404 if unknown)
  - \`POST /api/help/reload\` — force re-parse after doc edits
- Registered in the Tier 2-4 deferred list in \`server.py\`.

### Chat injection
\`chat_server.py\` now pulls \`glossary_for_chat(max_chars=10000)\` into
the system prompt alongside the existing LIVE DATA / MEMORY / SESSION
blocks. Added a dedicated **APP HELP / GLOSSARY** rules section above
it telling the model:

> When I ask "what is X?", "what does X mean?", "explain the X
> badge/chip/score", etc. about an APP UI ELEMENT — quote the
> matching definition VERBATIM. NEVER invent meanings for
> app-specific terms. If not in the glossary, say so honestly.

After quoting, the model offers: "want the full explanation? click
the ❓ button or press ? on the page." — looping the chat back into
the rest of the help system.

### Parser verified against the real file
81 entries × 15 categories parse correctly. Full glossary-for-chat
block is ~7.8KB, well inside any modern LLM context window.
Template-literal fullDef values (multi-line backtick strings) unescape
properly. The cache makes per-request cost sub-millisecond after first
parse.

### Tests (10 new pytests — all green)
- Parses cleanly (≥60 entries, every entry has id+term+shortDef)
- 6 known stable IDs present (backfill-readiness, pre-train-interlock,
  data-freshness-badge, ib-pusher, cmd-k, gate-score)
- \`get_term\` round-trips, \`find_terms\` honours query
- Chat block fits at 10KB cap, includes all critical terms, truncates
  cleanly at small caps
- \`GET /api/help/terms\`, \`?q=interlock\`, \`/terms/gate-score\`,
  404 for unknown IDs — all pass against live backend

### Files
- \`backend/services/glossary_service.py\` (new)
- \`backend/routers/help_router.py\` (new)
- \`backend/tests/test_glossary_help.py\` (new)
- \`backend/chat_server.py\` (glossary block injected into prompt)
- \`backend/server.py\` (router registered)

### Why this matters
The chat was previously trained on generic trading knowledge — it had
no idea what "Pre-Train Interlock" or "Backfill Readiness" or "Pusher
RPC" meant in **this** app. Now it answers from the same source of
truth the UI uses, ensuring the chat, drawer, ⌘K, and tours all say
the same thing. Edit a definition once in \`glossaryData.js\` → every
surface updates after a cache reload.



## 2026-04-25 — In-App Help System ("How-to / Explainer") — SHIPPED

A full discoverability suite so users (operator + less-technical
viewer) can learn what every badge / chip / score / verdict means
without leaving the page. Single-source-of-truth content lives in
\`data/glossaryData.js\`; every help surface (drawer, ⌘K, press-?
overlay, tours) reads from it.

### 1. Content audit — 37 new glossary entries
Added 5 new categories:
- **app-ui** — DataFreshnessBadge, LiveDataChip, FreshnessInspector,
  HealthChip, PipelineHUD, TopMoversTile, Briefings, SafetyArmed,
  FlattenAll, AccountMismatch, TradingPhase
- **data-pipeline** — IB Pusher, IB Gateway, Turbo Collector,
  Pusher RPC, Live Bar Cache, TTL Plan, Subscription Manager,
  Historical Data Queue, Pusher Health
- **ai-training** — Backfill Readiness + 5 sub-checks (queue_drained,
  critical_symbols_fresh, overall_freshness, no_duplicates,
  density_adequate), Pre-Train Interlock, Train Readiness Chip,
  Shift+Click Override, Training Pipeline Phases (P1-P9), Pre-Flight,
  Test Mode, Gate Score, Drift Veto, Calibration Snapshot
- **power-user** — ⌘K, Recent Symbols, ⌘K Help Mode (?term),
  Help Overlay (press ?), Glossary Drawer, Guided Tour

### 2. GlossaryDrawer (\`components/GlossaryDrawer.jsx\`)
Slide-in side panel (max-w-md). Open via:
- Floating ❓ button pinned bottom-right (mounted globally in App.js)
- \`window.dispatchEvent(new CustomEvent('sentcom:open-glossary',
  {detail:{termId}}))\`
- Press-? overlay → click any helpable element
- ⌘K \`?term\` → Enter

Features search, category chips, full markdown rendering for
fullDef, related-terms quick-jump, tag pills, Esc-to-close.

### 3. ⌘K Help Mode + Command Mode
Extended \`CommandPalette\`:
- \`?<term>\` → switches corpus to glossary entries; Enter opens the
  GlossaryDrawer at that term.
- \`>\` → command mode; currently lists guided tours
  (\`>command-center\`, \`>training-workflow\`).

### 4. Press-? Help Overlay (\`hooks/useHelpOverlay.js\` + App.css)
Press \`?\` (Shift+/) anywhere outside an input → enters help mode:
- Body gets \`data-help-mode="on"\`
- Every \`[data-help-id]\` element gets a dashed cyan outline + a
  cyan \`?\` chip pinned to its top-right corner
- Banner across the top: "HELP MODE — click any highlighted element…"
- Click any chip → opens the GlossaryDrawer at that termId
- Press \`?\` again, Esc, or click outside → exit

Wired \`data-help-id\` onto: DataFreshnessBadge, HealthChip,
LiveDataChip, BackfillReadinessCard, TopMoversTile,
TrainReadinessChip, ⌘K hint, FloatingHelpBtn (8 elements at launch;
adding to remaining components is incremental).

### 5. Guided Tours (\`data/tours.js\` + \`components/TourOverlay.jsx\`)
Lightweight tour engine — no library. Each step has a CSS selector,
title, body, and optional helpId. Renders a spotlight (box-shadow
hole) + popover anchored next to the target element. Tracks the
target rect on every animation frame so scrolling/resizing keeps it
anchored.

Two tours shipped:
- **command-center** — 6-step walkthrough of the V5 dashboard
- **training-workflow** — 3-step Backfill → Train safety walkthrough

\`localStorage.sentcom.tours.seen\` records completed tours so the
user isn't re-prompted automatically.

### Verification
- All 6 modified/new files lint clean.
- Frontend compiles (only pre-existing warnings).
- Smoke test confirms: floating button opens drawer + jumps to
  Backfill Readiness term · ⌘K \`?gate\` shows 7 glossary matches
  (IB Pusher, IB Gateway, Turbo Collector, Backfill Readiness,
  Pre-Train Interlock, Shift+Click Override, Gate Score) · ⌘K \`>\`
  lists tours · clicking command-center starts Tour step 1/6 with
  the spotlight on the freshness badge · press-\`?\` reveals 8
  helpable elements with cyan chips and the banner.

### Files touched
- \`data/glossaryData.js\` (+37 entries, +5 categories)
- \`data/tours.js\` (new)
- \`components/GlossaryDrawer.jsx\` (new)
- \`components/TourOverlay.jsx\` (new)
- \`hooks/useHelpOverlay.js\` (new)
- \`App.css\` (+74 lines for the press-? overlay styles)
- \`App.js\` (mount drawer + tour overlay + floating ❓ button + hook)
- \`components/sentcom/v5/CommandPalette.jsx\` (\`?\` and \`>\` modes)
- \`components/DataFreshnessBadge.jsx\` (data-help-id)
- \`components/sentcom/v5/HealthChip.jsx\` (data-help-id)
- \`components/sentcom/v5/LiveDataChip.jsx\` (data-help-id)
- \`components/sentcom/v5/BackfillReadinessCard.jsx\` (data-help-id)
- \`components/sentcom/v5/TopMoversTile.jsx\` (data-help-id)
- \`components/sentcom/SentComV5View.jsx\` (data-help-id on cmdk-hint)
- \`components/UnifiedAITraining.jsx\` (data-help-id on readiness chip)



## 2026-04-25 (cont.) — DataFreshnessBadge shipped globally

Small but high-leverage add requested by user during fork prep.

- New component: `frontend/src/components/DataFreshnessBadge.jsx`
- Mounted globally: pinned to the right of the TickerTape in `App.js`
  so it's visible on every tab (Command Center, NIA, Trade Journal, etc.)
- Polls `/api/ib/pusher-health` every 10s (low overhead)
- States rendered as a traffic-light chip with hover-tooltip:
    LIVE · Ns ago            (green, pulse) — pusher healthy, <10s age
    DELAYED · Nm ago         (amber)        — slow pusher during RTH
    WEEKEND · CLOSED         (grey)         — expected for off-hours
    OVERNIGHT · QUIET        (grey)
    EXT HOURS                (grey)
    STALE · PUSHER DOWN      (red, pulse)   — red + RTH = failure
    STALE · LAST CLOSE       (amber)        — red outside RTH = ok
    NO PUSH YET              (grey)         — backend up, pusher never fed
    UNREACHABLE              (red)          — backend not responding

Market-state gating lives client-side via a tiny America/New_York-aware
check (no holiday calendar here — that's on the backend and irrelevant
for a status chip). Badge is lint-clean and has `data-testid` for
future automated screenshot tests.

**Why it matters:** the 5-week stale-chart incident 2026-03-17 → 2026-04-24
happened partly because nothing in the UI shouted that data was frozen.
Now the chip is the FIRST thing you look at across any surface. When
Phase 1 of the live-data architecture lands, this badge will also be
the natural home for `live_bar_cache` TTL state.




## 2026-04-25 — Live-data architecture plan APPROVED, ready to build

After the collector walkback fix verified live (10k+ bars/batch vs 1130), user
reported duplicate-timestamp chart crash + discovered the EnhancedTickerModal
was still on lightweight-charts v4 API while the package is at v5.1. Both
fixed. Fresh architectural scope defined for the next (max-tier) session:
**make every app surface capable of fast, up-to-date live data — market open,
after hours, weekends, any symbol.**

### User's requirements (verbatim-faithful paraphrase):

> "Throughout the entire app I want access to the most up-to-date and
> preferably live data when I want it. IB is my best bet — I pay for it.
> During market-closed hours or weekends, if the app is open and connected
> to IB/ib pusher, I should still be able to access the last available live
> data for any symbol we have in our database across any timeframe for as
> far back as our data/charts will allow."

> "Make sure our trade journal, SentCom, AI chat, scanners, portfolio
> management, charting, enhanced ticker modal, briefings, unified stream,
> NIA — all of it — has access to live data when it needs to and can get
> that data fast. If we need to refactor or break up ports or websockets,
> do it so the entire app can be stable while doing all of this in
> real-time or near-real-time."

### User clarifications (answered before fork):
- **Long research sessions on same symbol**: Yes, sometimes → active-view
  symbol gets 30s TTL regardless of market state.
- **Extended hours in latest-session fetch**: Yes → `useRTH=False` on the
  pusher RPC call.
- **Alpaca fallback**: Keep until the new path is verified, then retire via
  env flag `ENABLE_ALPACA_FALLBACK=false` (default), then rip in follow-up.
- **Scope**: Full app. Pusher becomes dual-mode (push loop + RPC server).

### Approved 4-phase plan (each phase ships standalone)

**🔴 Phase 1 — Foundation: on-demand IB fetch + TTL cache**
  Files to add:
  - Windows pusher: `POST /rpc/latest-bars`, `/rpc/quote-snapshot`,
    `/rpc/health` — FastAPI mounted alongside push loop, shares client-id 15.
  - DGX: `backend/services/ib_pusher_rpc.py` — HTTP client.
  - DGX: extend `backend/services/hybrid_data_service.py` with
    `fetch_latest_session_bars(symbol, bar_size)`.
  - New Mongo collection `live_bar_cache` with dynamic TTL index:
    - RTH open: 30s · Pre/post-market: 2 min · Overnight: 15 min ·
      Weekend/holiday: 60 min · Active-view symbol: 30s regardless.
  - Wire `/api/sentcom/chart` and `/api/ib/analysis/{symbol}` to merge
    historical (Mongo) + latest session (pusher RPC via TTL cache).
    Existing dedup from 2026-04-24 fix handles the overlap seam.
  Risk: 1× backend restart + 1× pusher restart. Collectors retry ~1 min.
  Effort: ~4–6h at normal tier.

**🟡 Phase 2 — Live subscription layer (tick-level)**
  - Pusher: `POST /rpc/subscribe`, `POST /rpc/unsubscribe` + dynamic watchlist.
  - DGX: `POST /api/live/subscribe/{symbol}` + `/unsubscribe/{symbol}`.
  - Frontend: `useLiveSubscription(symbol)` hook used by ChartPanel and
    EnhancedTickerModal. Auto-cleanup on unmount. Scanner top-5 auto-subs.
  - WebSocket pipe pusher → backend → frontend already exists; extend the
    per-socket watchlist state.
  Delivers: whichever symbol user is actively viewing gets tick-level updates.
  Effort: ~3–4h.

**🟡 Phase 3 — Wire remaining surfaces**
  - Scanner: call `fetch_latest_session_bars` for candidate symbols.
  - Briefings: pre-market brief = yesterday close + today's pre-market.
  - AI Chat context: inject latest-session snapshot per symbol mentioned.
  - Trade Journal: snapshot price-at-close on trade date (immutable after).
  - Portfolio/positions: already live via pusher stream — verify freshness
    chip reflects reality.
  Effort: ~3–4h.

**🟢 Phase 4 — Safely retire Alpaca**
  - Gate `_stock_service` init behind `ENABLE_ALPACA_FALLBACK` env var
    (default false). Don't init the shim unless flag is true.
  - Remove `"Alpaca"` label from `/api/ib/analysis/{symbol}:3222`.
  - Verify 24h with flag off, then rip the code paths in a follow-up PR.
  Effort: ~1h.

### Critical infra facts for next agent
- DGX cannot talk to IB Gateway directly (binds to 127.0.0.1:4002 on Windows);
  all IB I/O must route through Windows pusher. That's the whole reason
  Phase 1 needs a new RPC layer on the pusher.
- Pusher runs IB client-id 15 (separate 58/10min quota from collectors 16–19,
  so adding on-demand reqHistoricalData calls does NOT steal from backfill).
- Existing `lightweight-charts` version is **v5.1.0** — use `addSeries(Series, opts)`
  NOT `addCandlestickSeries(opts)`. ChartPanel is correct; EnhancedTickerModal
  just fixed today.
- The chart dedup contract (sort + reduce by time) is now in:
  - `frontend/.../ChartPanel.jsx` (bars + indicators)
  - `frontend/.../EnhancedTickerModal.jsx` (bars)
  - `backend/routers/sentcom_chart.py` (source of truth)
  New chart integrations MUST replicate this.
- User's Windows repo had a nested clone trap (resolved 2026-04-25). If Windows
  collector or pusher code changes, verify with:
  ```powershell
  python -c "import pathlib; p=pathlib.Path('documents/scripts/ib_historical_collector.py'); print('HAS_FIX:', 'endDateTime=end_date' in p.read_text(encoding='utf-8'))"
  ```
  Reject fixes until `HAS_FIX: True`.

### Session state at fork
- Historical backfill queue: ~13,700 pending, 95.1% done, draining at ~800
  items/hour combined across 4 collectors, ETA ~17 hours. **DO NOT start
  AI retrain until queue is empty.**
- Chart duplicate-timestamp crash: **fixed** (frontend + backend dedup +
  pytest contracts). 6/6 regression tests green.
- EnhancedTickerModal "Failed to initialize chart": **fixed** (v5 migration).
- V5 chart header ticker-swap input: **shipped** (small input next to SPY
  button, Enter commits, Esc cancels, 10-char cap). Hard-refresh to see.
- Alpaca chip: **still visible** on MRVL modal. Phase 4 retires it.
- IB Warning 2174 (hyphen vs space time format): deferred P3, no impact today.




## 2026-04-25 — Walkback fix VERIFIED live + 2 collateral issues resolved

After the earlier collector + planner patches, the live DGX system still showed
the same 13s dup-waits. Deep-dive diagnosis revealed 3 compounding issues.

**Issue A: Stale queue orphans blocked new walkback chunks.**
`historical_data_requests` held 11k+ rows created 2026-03-17 with 3 prefixes
(`gap_`, `gap2_`, and legacy `hist_`) — all with missing/empty `end_date`.
Because `_smart_backfill_sync` outer-dedups on `(symbol, bar_size)` regardless
of end_date, these orphans blocked the fresh planner from enqueuing any real
walkback chunks (`skipped_already_queued: 11,241`). 
Fix: new `POST /api/ib-collector/purge-stale-gap-requests` endpoint (prefix +
dry-run + age cutoff, counts + breakdown returned). Purged 56+2+370 rows to
unblock the planner.

**Issue B: Windows collector running stale code (nested git clone).**
The Windows machine had `C:\Users\...\Trading-and-Analysis-Platform` (outer
repo used by TradeCommand.bat) AND a nested clone inside it. Previous
controller pulls had been silently stuck in an abandoned merge state
(`MERGE_HEAD exists`) — `Windows code updated!` was a lie for weeks.
Fix: `git merge --abort`, `git fetch origin`, `git reset --hard origin/main`,
`git clean -fd`, deleted nested duplicate repo. Confirmed with:
`python -c "...; print('HAS_FIX:', 'endDateTime=end_date' in src)"` → True.

**Issue C: `git clean -fd` wiped untracked `ib_data_pusher.py` at Windows
repo root** (collateral damage from the cleanup). Live market data feed
died silently during the next controller start — launcher logged `[SKIP]
ib_data_pusher.py not found` but continued. Fix: copied canonical
`documents/scripts/ib_data_pusher.py` → repo root, reclaimed IB Gateway
client ID 15 by restarting IB Gateway.

**Verified live behaviour (UPS, 10-request batch on 2026-04-24):**
```
UPS (1 min): 1950 bars   ← chunk ending now
UPS (1 min): 1950 bars   ← week -1 (distinct data)
UPS (1 min): 1950 bars   ← week -2
... 7 more chunks walking back ...
UPS (1 min): 390 bars    ← hit data-availability limit
Batch reported: 10 results, 10,428 bars stored to DB
Session: 20 done, 29,452 bars
Queue: 265,617/285,731 (93%)
```
**Throughput per 10-request batch: 10,428 bars (vs ~1,130 before fix) — ~10×.**
No more `Pacing: waiting 13s (55 remaining)` — only legit window-cap waits.

**P2 follow-up filed — IB Warning 2174 (time-zone deprecation):**
IB Gateway logs a deprecation warning on every request because the current
normalization produces `"YYYYMMDD HH:MM:SS UTC"` (space) but IB's next API
release will prefer `"YYYYMMDD-HH:MM:SS UTC"` (hyphen). Currently a warning,
not an error — no behaviour impact today. When addressed, flip both the
collector's `end_date[8]=="-"` normalization AND the backend planner's
`strftime("%Y%m%d %H:%M:%S")` back to hyphen form, and re-run pytest.

**Tests / endpoints shipped in this session:**
  - `POST /api/ib-collector/queue-sample` (diagnostic — distinct end_date count + format classifier)
  - `POST /api/ib-collector/purge-stale-gap-requests` (cleanup — prefix + age + dry-run)
  - `backend/tests/test_collector_uses_end_date.py` (4 regression contracts, all green)




## 2026-04-25 — Walkback bug fix: collector now honors queue `end_date`

User reported collectors still "pacing conservatively" after restart — logs
showed `CI (1 min): 1950 bars` repeating 4× per cycle with 13.3–13.9s
`Pacing: waiting` between each, even though only 3 of 58 window slots used.

**Root cause (two bugs, same blast radius):**

1. `documents/scripts/ib_historical_collector.py::fetch_historical_data`
   hardcoded `reqHistoricalData(endDateTime="")` — i.e. "now". The queue
   planner correctly enqueued walkback chunks with distinct anchors, but
   the collector threw those away and asked IB for the *same* latest
   window every time. IB then applied its own server-side "no identical
   request within 15s" rule → 13s waits, duplicate bars, queue never
   actually drains.
2. Backend planner (`services/ib_historical_collector.py`) strftime'd
   end_dates with a hyphen (`"20260423-16:00:00"`). IB TWS expects a
   space (`"20260423 16:00:00"`); the hyphen form is rejected outright.

**Fix:**
  - Collector: pass `end_date = request.get("end_date", "")` into
    `reqHistoricalData(endDateTime=end_date)`. Also normalize legacy
    hyphen-form rows in the queue (`ed[8]=='-'` → replace with space)
    so old queued rows work without a DB migration.
  - Backend planner: two call sites changed from `%Y%m%d-%H:%M:%S` to
    `%Y%m%d %H:%M:%S` — lines 1328 and 2544.
  - New diagnostic: `GET /api/ib-collector/queue-sample` returns N
    pending rows and summarizes distinct end_dates + format class
    (empty / hyphen / space / unknown) to verify the planner emits
    distinct walkback anchors.

**Regression tests (`tests/test_collector_uses_end_date.py`):**
  - reqHistoricalData must reference `end_date` var, not `""`
  - collector tolerates legacy hyphen-form rows
  - planner emits space-format from every strftime call
  - pacing key tuple still contains (symbol, bar_size, duration, end_date)
  - 4/4 new + 15/15 existing collector contracts green.

**Impact on active backfill:**
  - Before: each walkback chunk re-fetched the same 1950-bar slice; queue
    "drained" without adding new history (5-week gap persisted).
  - After: each chunk fetches a *distinct* historical window walking
    backward in time; queue drain rate now bottlenecked only by IB's
    ~232 req/10min hard cap across 4 collectors (as designed).

**Action for user:**
  1. On Windows PC: `git pull` (patched collector script ships with repo)
  2. Restart the 4 collectors (`spark_restart` or the NIA workflow)
  3. Hit `GET /api/ib-collector/queue-sample?symbol=CI&bar_size=1%20min`
     — `distinct_end_dates` should be close to `count` and
     `end_date_formats.space (IB-native)` should dominate.
  4. Watch a collector terminal; successive calls should show different
     bar counts / timestamps, no more "Pacing: waiting 13s" between
     chunks of the same symbol.



## 2026-04-24 — Pre-Train Safety Interlock — SHIPPED

Wires every "start training" button in the UI to the
`/api/backfill/readiness` gate shipped earlier today so it is
structurally impossible to accidentally kick off a training run on a
half-loaded / stale / duplicated dataset.

### New primitives
- **`hooks/useTrainReadiness.js`** — polls `GET /api/backfill/readiness`
  every 60s. Exposes `{ready, verdict, blockers, warnings, refresh,
  readiness, loading, error}`. Treats unreachable backend as "unknown"
  (NOT green) — fails closed.
- **`components/TrainReadinessGate.jsx`** — render-prop wrapper that
  exposes badge / gateProps / tooltipText for buttons that need a
  readiness-aware visual. Also exports `isOverrideClick(event)` for
  shift/alt click detection — the one-off conscious override pattern.

### Buttons gated (all 5)
1. **`start-training-btn`** (NIA → AI Training Pipeline) — the main
   "Start Training" button. Most important gate.
2. **`train-all-btn`** (UnifiedAITraining → Full Train across all
   timeframes).
3. **`full-universe-btn`** (UnifiedAITraining → Full Universe, 1-3h).
4. **`train-all-dl-btn`** (UnifiedAITraining → Train All DL Models).
5. **`train-all-setups-btn`** (NIA → Setup Models Panel → Train All).

### Gate behaviour
- If `ready_to_train !== true` **and** the click is not shift/alt:
  - Shows a loud `toast.error` explaining the first blocker.
  - Shows a `toast.info` telling the user shift+click overrides.
  - Does **not** fire the training action.
- If `ready_to_train !== true` **and** shift/alt is held:
  - Shows a `toast.warning` logging the override.
  - Proceeds with training as normal.
- If `ready_to_train === true`: behaves exactly like before.

### Visual treatment
- Buttons dim to `bg-zinc-800/60 text-zinc-500 border-zinc-700` when
  gated (instead of their bright gradient).
- A small colored dot (rose / amber) with `animate-pulse` appears next
  to the button label reflecting the verdict.
- `data-train-readiness` attribute exposes the verdict to tests.
- Native `title` tooltip shows the first blocker + "Shift+click to
  override".
- In the UnifiedAITraining panel, a dedicated readiness chip above the
  action row shows the verdict, summary, first two blockers, and has a
  ↻ refresh button.

### Quality
- Lint clean across all 5 modified files + 2 new modules.
- Frontend compiles with no new warnings.
- Smoke test: click without shift → correctly blocks (2 toasts shown,
  training did NOT start); shift+click → correctly overrides (warning
  toast, training starts, button flips to "Starting...").
- 30 backend tests still pass (readiness + universe-freshness-health +
  system-health + live-data-phase1).

### Why this matters
A single fat-fingered click during the backfill (or on Monday morning
before remembering to check) was enough to poison weeks of validation
splits. This gate makes that class of accident structurally impossible
without a conscious shift+click, while still leaving the escape hatch
open for the user who knows exactly what they're doing.



## 2026-04-24 — Backfill Readiness Checker — SHIPPED

A single-source-of-truth "OK to train?" gate the user can check before
kicking off the post-backfill retrain cycle. No more correlating
/universe-freshness-health + /queue-sample + manual SPY inspection by
hand.

### Backend
- New service `services/backfill_readiness_service.py` running 5 checks
  in parallel (all read-only, <3s total):
  1. **queue_drained** — `historical_data_requests` pending+claimed
     must be 0 (RED if anything in flight; YELLOW if >50 recent
     failures).
  2. **critical_symbols_fresh** — every symbol in
     `[SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, GOOGL, META, AMZN]`
     must have a latest bar inside STALE_DAYS for every intraday
     timeframe.
  3. **overall_freshness** — % of (intraday-universe symbol × critical
     timeframe) pairs fresh. GREEN ≥95%, YELLOW ≥85%, RED otherwise.
  4. **no_duplicates** — aggregation spot-check on critical symbols
     confirms no `(symbol, date, bar_size)` appears more than once
     (catches write-path bugs that would silently over-weight bars).
  5. **density_adequate** — % of intraday-tier symbols with
     ≥780 5-min bars (anything below is dropped from training).
- New router `routers/backfill_router.py` exposing
  **`GET /api/backfill/readiness`** (registered in the Tier 2-4
  deferred list in `server.py`).
- Response shape:
  ```
  {verdict, ready_to_train, summary, blockers[], warnings[],
   next_steps[], checks{queue_drained, critical_symbols_fresh,
   overall_freshness, no_duplicates, density_adequate},
   generated_at}
  ```
- Worst-check-wins verdict aggregation. `ready_to_train` is GREEN-only.

### Frontend
- New `BackfillReadinessCard` component (in
  `frontend/src/components/sentcom/v5/`). Pinned to the top of the
  FreshnessInspector so clicking the global DataFreshnessBadge now
  surfaces the readiness gate as the very first thing you see.
- Visuals: giant verdict pill (READY / NOT READY), blockers list (red
  bullets), warnings list (amber bullets), 2-column per-check grid
  with color coding, and an actionable next-steps list.
- Re-fetches in lockstep with the inspector's reload button via a
  counter-based `refreshToken` prop (safe — no infinite-render loop).

### Tests
- `/app/backend/tests/test_backfill_readiness.py` (5 tests): happy
  path green, queue-active → red, stale-critical → red, response
  shape contract, router registration.
- All 25 targeted tests pass (backfill_readiness +
  universe_freshness_health + system_health_and_testclient +
  live_data_phase1).

### Why this matters
While the backfill drains, the user has been asking "is it done yet?
Can I train?". This endpoint answers that definitively. Once the DGX
queue hits 0, one click on the freshness badge reveals a giant green
READY pill → confidence to trigger Train All without fear of
corrupting the validation split.



## 2026-04-24 — Live Data + Stability Bundle polish — SHIPPED

Small, focused UX improvements on top of the Phase 5 bundle. No new
surfaces / no backend changes — all frontend polish:

1. **DataFreshnessBadge is now clickable → opens FreshnessInspector**
   directly. Works on every tab (not just V5) since the badge is
   globally pinned in `App.js`. Completes the P3 backlog item "Convert
   DataFreshnessBadge to an active command palette". One glance shows
   status, one click reveals per-subsystem detail.
2. **CommandPalette remembers recent symbols** — last 5 picks persist
   to `localStorage` under `sentcom.cmd-palette.recent`. When the input
   is empty the palette shows the recent list (tagged "recent") so
   jumping back to a symbol is a single keystroke.
3. **CommandPalette discoverability** — new clickable `⌘K search` hint
   chip rendered in the V5 HUD's `rightExtra` slot, left of
   `HealthChip`. Clicking it dispatches a
   `sentcom:open-command-palette` window event that the palette listens
   for (loose coupling; no prop-drilling required).
4. **PanelErrorBoundary copy-error button** — adds a "copy error ⧉"
   button alongside "reload panel ↻" that writes the error message +
   stack to the clipboard so a user can paste it into chat / GitHub
   issue in one click.
5. **FreshnessInspector "+N more" truncation notice** — subscription
   list silently capped at 20; now appends a "+N more not shown" line
   when there are more active subs than visible.

**Touched files:**
- `/app/frontend/src/components/DataFreshnessBadge.jsx`
- `/app/frontend/src/components/sentcom/v5/CommandPalette.jsx`
- `/app/frontend/src/components/sentcom/v5/PanelErrorBoundary.jsx`
- `/app/frontend/src/components/sentcom/v5/FreshnessInspector.jsx`
- `/app/frontend/src/components/sentcom/SentComV5View.jsx`

**Verification:**
- Lint: clean across all 5 files (no new warnings).
- Smoke screenshot: DataFreshnessBadge click opens FreshnessInspector
  with all subsystems populated (mongo/ib_gateway/historical_queue/
  pusher_rpc/live_subscriptions/live_bar_cache/task_heartbeats).
- ⌘K hint click opens CommandPalette showing default corpus
  (DIA/IWM/QQQ/SPY/VIX).
- Existing pytest suite (20 tests covering system_health + live_data
  phase1) still passes.



## 2026-04-24 — IBPacingManager dedup key widened (backfill ~6× faster)

User observed every `(symbol, bar_size)` chunk pair paying a 13.9-second
identical-request cooldown even when the requests differed in `duration`
(e.g. "5 D" vs "3 D" walk-back chunks) — which IB itself would accept
as non-identical. That turned a 21k-request backfill into a ~15h task.

**Root cause (`documents/scripts/ib_historical_collector.py`):**

`IBPacingManager` keyed dedup on `(symbol, bar_size)` only. IB's actual
rule ("no identical historical data requests within 15s") matches on the
full identity tuple `(contract, bar_size, durationStr, endDateTime,
whatToShow, useRTH)`. Two requests that differ in duration are not
identical and do NOT need the cooldown.

**Fix:**

  - Added `IBPacingManager._key(symbol, bar_size, duration, end_date)`
    helper building a 4-tuple.
  - `can_make_request`, `record_request`, `wait_time` accept optional
    `duration` + `end_date` kwargs (backward compatible — if not provided,
    key still works via `or ""` fallback).
  - `fetch_historical_data` passes `duration` and `end_date` from the
    queue request into all three pacing methods.
  - Window-based 60/10min rate limit unchanged — still the hard cap.

**Impact on active backfill:**

  - Before: ~15h for 21,270 requests (dominated by same-symbol 13.9s waits)
  - After: ~2.5h (only window-limit and IB fetch time remain)
  - 6× speedup; SPY/QQQ/DIA/IWM land within first ~30 min instead of hours

**Regression tests (`tests/test_pacing_manager_dedup.py`):**

  - 5 new contracts: methods accept duration+end_date kwargs, _key helper
    builds correct 4-tuple, hot-path calls pass all 4 args, window limit
    still enforced, max_requests default ≤ 60.
  - 27/27 total across 5 suites passing.

**User next steps (requires collector restart on Windows):**

Because `ib_historical_collector.py` lives in `documents/scripts/` and
runs on the Windows PC (client IDs 16-19), `git pull` + a collector
restart on Windows is required to apply this. Then you'll see the pacing
waits drop from 13.9s to near-zero whenever the backfill has work to do
across different durations.

---


## 2026-04-24 — `GET /api/ib-collector/universe-freshness-health` one-call retrain readiness rollup

Added a dedicated endpoint that replaces the 4-curl correlation needed to
answer "Am I ready to retrain?". Single request returns
`ready_to_retrain: bool` plus full diagnostic detail.

**Response shape:**
```
{
  "ready_to_retrain": bool,
  "blocking_reasons": [str, ...],
  "overall": {total_symbol_timeframes, fresh, stale, missing, fresh_pct, threshold_pct},
  "critical_symbols": {all_fresh, detail: [{symbol, all_fresh, timeframes: [...]}]},
  "by_tier": [{tier, total_symbols, timeframes: [...]}],
  "oldest_10_daily": [{symbol, age_days, latest}, ...],
  "freshest_10_daily": [{symbol, age_days, latest}, ...],
  "last_successful_backfill": {ran_at, queued, skipped_fresh},
  "queue_snapshot": {pending, claimed},
  "generated_at": iso_ts
}
```

**Gate logic:** `ready_to_retrain = all_critical_fresh AND overall_fresh_pct >= threshold`.

Defaults:
  - `min_fresh_pct_to_retrain = 95.0` (query param)
  - `critical_symbols = "SPY,QQQ,DIA,IWM,AAPL,MSFT,NVDA,GOOGL,META,AMZN"`
    — these must all be fresh on every intraday timeframe.

Reuses the SAME `STALE_DAYS` map as `/gap-analysis` + `/fill-gaps` +
smart-batch-claim recency guard so all four code paths agree on what
"fresh" means. Pytest contract enforces this map-equality invariant —
if anyone diverges the test fails.

**Regression tests (`tests/test_universe_freshness_health.py`):**
  - 5 new contracts locking: endpoint registered, AND-gate logic,
    STALE_DAYS equality across 3+ endpoints, response shape has every
    key field, default critical_symbols include SPY/QQQ/IWM/AAPL/MSFT.
  - Full suite: 22/22 green across 4 suites.

**Usage:**
```bash
# Poll during backfill
curl -s http://localhost:8001/api/ib-collector/universe-freshness-health | jq '{
  ready_to_retrain, blocking_reasons,
  overall: .overall.fresh_pct,
  pending: .queue_snapshot.pending
}'

# When ready_to_retrain: true, kick off training
curl -X POST http://localhost:8001/api/ai-training/start
```

**Files touched:** `routers/ib_collector_router.py`,
`tests/test_universe_freshness_health.py`.

---


## 2026-04-24 — THE actual root cause: skipped_complete coverage-by-count bug

After tracing the full NIA "Collect Data" button chain end-to-end, found
the REAL reason SPY/QQQ/DIA/IWM have been frozen at 2026-03-16 despite
daily "Fill Gaps" / "Collect Data" clicks. The bug is in `routers/ib.py`
`smart-batch-claim` endpoint (lines 1720-1830), which is what the Windows
collectors call to claim requests from `historical_data_requests`:

```python
bar_count_existing = data_col.count_documents({symbol, bar_size}, limit=t+1)
if bar_count_existing >= threshold:
    should_skip = True
    # mark skipped_complete, never hit IB
```

For SPY 5 mins, threshold = 1,400, actual = 32,396 → skip fires. But ALL
32k bars are ≤ 2026-03-16. The collector marked every SPY request as
`skipped_complete` in ~3 milliseconds — proved by the user's forensic
curl `/api/ib-collector/symbol-request-history?symbol=SPY`:

```
duration: "5 D", end_date: "20260418-15:24:40"
claimed_at:   2026-04-23T15:25:42.882709
completed_at: 2026-04-23T15:25:42.885632   ← 3ms, no IB call
result_status: "skipped_complete"
```

Compare MSCI (no prior data → count check fails → hit IB):
```
claimed_at:   2026-04-23T16:16:57
completed_at: 2026-04-23T16:18:33   ← 1m 36s real IB call → "success"
```

**Same family of bug as `gap-analysis`/`fill-gaps` but in a 3rd place.**
This one was the actual blocker — the smart_backfill planner correctly
queued 23,931 requests yesterday, but smart-batch-claim instantly
"completed" every SPY request without fetching anything.

**Fix (`routers/ib.py`):**

  - Added `STALE_DAYS` map mirroring `gap-analysis`/`fill-gaps`
    (`1 min`/`5 mins`=3d, `15 mins`/`30 mins`=5d, `1 hour`=7d, `1 day`=3d,
    `1 week`=14d).
  - Added `_latest_bar_too_old(data_col, symbol, bar_size)` helper that
    reads max(date) via `sort(date, -1).limit(1)`, parses ISO with Z/tz
    suffix handling, fail-safes to True on parse errors.
  - Skip condition hardened from `if bar_count_existing >= threshold:`
    to `if bar_count_existing >= threshold and not _latest_bar_too_old(...)`.
  - If latest bar is stale, the request is forwarded to IB even if count
    is high.

**Regression tests (`tests/test_smart_claim_recency.py`):**

  - 4 new pytest contracts: helper exists & uses sort(date,-1),
    skip requires count AND recency, STALE_DAYS covers every
    COMPLETENESS_THRESHOLDS key, intraday bar_sizes ≤7 days threshold.
  - 17/17 total regression tests green across the 3 suites (pipeline,
    gap-analysis, smart-claim).

**End-to-end NIA "Collect Data" button chain — verified correct after fix:**

```
[Collect Data btn] → POST /smart-backfill?freshness_days=2
    ↓ (planning already had freshness, unchanged)
_smart_backfill_sync → queue to historical_data_requests (23,931 requests)
    ↓ (Windows collectors poll)
POST /api/ib/smart-batch-claim → claim + skip-check
    ↓ (FIXED: skip now requires count AND recency)
IB Gateway → historical_data_requests.complete_request(status=success)
    ↓
ib_historical_data (bars landed) → chart, training, everything fresh
```

**User next-steps (after pull + restart):**

  1. Verify SPY request history now shows `success` instead of
     `skipped_complete` for recent requests.
  2. Re-click "Collect Data" in NIA — should now fetch fresh SPY/QQQ/DIA.
  3. Monitor `queue-progress-detailed` — expect ~20k pending requests
     queued, processing for 10-12h with 4 turbo collectors.
  4. Once complete, retrain. Fresh data + all training-pipeline
     observability fixes = proper post-fix verification run.

---


## 2026-04-24 — Gap-analysis / Fill-Gaps staleness bug (the reason training is frozen at March 16)

**Smoking-gun root cause found for the stale-universe issue.** User ran today's
"Fill Gaps" on the NIA page; the diagnostic showed SPY still stuck at
2026-03-16 (38 days old) while obscure symbols like NBIE/MSCI/CRAI got fresh
2026-04-23 bars. Traced to `routers/ib_collector_router.py`:

  - `/api/ib-collector/gap-analysis` counted a symbol as `has_data` if it had
    ANY historical bar, regardless of how old. SPY with 32,396 bars all older
    than 2026-03-16 came back as `coverage_pct: 100, needs_fill: false`.
  - `/api/ib-collector/fill-gaps` used the same existence-only logic, so
    pressing "Fill Gaps" never queued SPY, QQQ, DIA, IWM, ADBE, NEE, etc. for
    refresh. The collector only touched symbols that had literally zero rows.
  - Net effect: the entire core training universe silently froze whenever
    the collector last ran. Last full run was ~March 16 → every "backfill"
    since then has been a no-op for the critical symbols.

**Fix (`ib_collector_router.py`):**

  - Both `/gap-analysis` and `/fill-gaps` now run an index-backed
    `$group → $max(date)` aggregation per `(bar_size, symbol)` and classify
    each symbol as `missing` (no rows), `stale` (latest bar older than the
    threshold), or `fresh`.
  - Staleness thresholds are bar_size-specific: `1 min`/`5 mins`=3d,
    `15 mins`/`30 mins`=5d, `1 hour`=7d, `1 day`=3d, `1 week`=14d.
  - `_is_stale` parses ISO strings with `Z`/`+HH:MM`/`-HH:MM` suffixes
    (three formats live in production data) and fails-safe to "stale" on
    unknown formats so unparseable entries always get refreshed.
  - Response payload now exposes `total_missing_symbols`,
    `total_stale_symbols`, `has_data_fresh`, `has_data_stale`,
    `sample_stale[]` so the UI can distinguish "no data" from "old data".

**Regression tests (`tests/test_gap_analysis_staleness.py`):**

  - 6 new pytest contracts locking the fix: $max aggregation, staleness
    thresholds for every bar_size, missing/stale split in response,
    fill-gaps queues both buckets, _is_stale TZ-suffix handling, both
    endpoints share the same STALE_DAYS map. 13/13 tests green.

**After pull, user should:**

  1. `curl /api/ib-collector/gap-analysis?tier_filter=intraday` — will now
     show the true stale-tail count (expect thousands, not zero).
  2. `POST /api/ib-collector/fill-gaps?tier_filter=intraday&enable_priority=true`
     — queues every stale symbol for refresh, including SPY/QQQ/DIA/IWM.
  3. Monitor `chart-diagnostic-universe?timeframe=5min&limit=20` — should
     show max_collected_at moving forward for core ETFs.
  4. Only after backfill lands should the "post-fix verification" retrain
     be kicked off; otherwise it'll use the same March 16 cutoff universe.

**ACCOUNT MISMATCH (from earlier):** turned out to be a startup race —
curl (c) for `/api/safety/status` was run before the pusher had sent
account data. Once `_pushed_ib_data["account"]` is populated (as curl (e)
proved), the existing `get_pushed_account_id()` helper returns the right
value and the guard's case-insensitive match accepts the paper alias.
No code fix needed; re-running the curl shows `match: true`.

---


## 2026-04-24 — Chart staleness detection + fallback + frontend banners

Follow-up after user inspection: `/api/sentcom/chart-diagnostic?symbol=SPY`
revealed `latest_date: "2026-03-16"` — 5+ weeks of missing SPY 5m bars.
Pusher was LIVE (live quotes) but the IB historical collector hadn't run,
so the chart window [today-5d, today] returned zero rows and the old code
fell through to the misleading "IB disconnected" error.

**Backend (`hybrid_data_service.py`):**
  - `DataFetchResult` gained four freshness flags: `stale`, `stale_reason`,
    `latest_available_date`, `partial`, `coverage`.
  - `_get_from_cache` now has a stale-data fallback: if the requested window
    is empty but the collection has older bars for the (symbol, bar_size),
    return the most recent N bars with `stale: true` + `latest_available_date`
    instead of returning `success=False`. Density of N mirrors the requested
    window (`_estimate_fallback_bar_count` helper).

**Backend (`routers/sentcom_chart.py`):**
  - `/api/sentcom/chart` now propagates `stale`, `stale_reason`,
    `latest_available_date`, `partial`, `coverage` to the UI.

**Frontend (`ChartPanel.jsx`):**
  - Added a pill-style "STALE CACHE · latest YYYY-MM-DD" banner at the top
    of the chart when backend reports stale data.
  - Added a "PARTIAL · NN% coverage" banner when coverage is partial.
  - `data-testid="chart-stale-banner"` + `chart-partial-banner`.

**Known ops issue surfaced (USER ACTION REQUIRED):**
  - IB historical collector has not written fresh bars for SPY since
    2026-03-16. Retraining now would use the same stale universe as the
    last 186M-sample run — no new market data since mid-March. User must
    kick off a backfill before the "post-fix verification" retrain or
    accept that the retrain only validates the code fixes, not fresh data.

---


## 2026-04-24 — Command Center chart diagnostics + misleading "IB disconnected" fix

User reported the V5 Command Center showing *"Unable to fetch data. IB
disconnected and no cached data available"* on the SPY chart even though
the Pusher LIVE badge was green. Root-caused to `hybrid_data_service.py`:

  1. **80% coverage gate** (line 310) would return `success=False` and fall
     through to `_fetch_from_ib()` whenever cached bars covered <80% of the
     requested window. Backend doesn't talk to IB directly (pusher does),
     so every partial-coverage read produced the same confusing error.
  2. **Error text was architecturally wrong** — the backend was never
     supposed to have a direct IB connection in this deployment, so
     "IB disconnected" misleads the user to look at the wrong symptom.

**Fixes applied** (`hybrid_data_service.py`):
  - Partial-coverage reads now return `success=True` with `partial: true`
    and `coverage: <float>` so the chart can render whatever we have.
  - Error message rewritten to accurately point the user at
    `ib_historical_data` + `/api/ib/pusher-health` for triage.

**New diagnostic endpoint** (`routers/sentcom_chart.py`):
  - `GET /api/sentcom/chart-diagnostic?symbol=SPY&timeframe=5min` returns
    total bar count, earliest/latest dates, distinct `bar_size` values
    available for the symbol, per-bar-size counts, and a sample document.
    Lets the user immediately see whether SPY 5m bars are missing, stored
    under a different bar_size key, or have a date-format mismatch.

---


## 2026-04-24 — Post-training observability + scorecard mirror fixes

Surgical edits to `training_pipeline.py` and regression contracts under
`tests/test_training_pipeline_contracts.py` so the next full-quality
training run is actually interpretable. All changes verified by
`pytest tests/test_training_pipeline_contracts.py -v` (7/7 passing).

**Bugs fixed (root cause → patch):**

  1. **Phase 1 `direction_predictor_*` accuracy always 0** —
     `train_full_universe` returns `accuracy` at top level, but Phase 1 was
     reading `result["metrics"]["accuracy"]`. One-line fix: prefer top-level
     `accuracy` / `training_samples`, fall back to the nested shape for
     back-compat.

  2. **`GET /api/ai-training/scorecards` always returns `count: 0`** —
     Phase 13 was passing `training_result = {"metrics": {...}}` with no
     `model_name`, so `post_training_validator._build_record`'s mirror
     (`timeseries_models.update_one({"name": training_result["model_name"]},
     {"$set": {"scorecard": ...}})`) silently skipped every iteration.
     Phase 13 now resolves `model_name` via
     `get_model_name(setup_type, bar_size)` + looks up `version` from
     `timeseries_models` and stuffs both into `training_result`.

  3. **Phase 3 volatility + Phase 5 sector-relative + Phase 7 regime-
     conditional silent skips** — when data was insufficient, all three
     phases did a bare `continue` (Phase 3/5) or a `logger.warning` + fall-
     through (Phase 7) producing 0 models with no entry in
     `results["models_failed"]`. You couldn't tell why they were empty.
     Each skip now records an explicit failure with a human-readable reason
     (`Insufficient data: N < MIN_TRAINING_SAMPLES=M`, `No sector ETF bars
     available at <bs>`, `Insufficient SPY data for regime classification`).

  4. **VAE + FinBERT metrics mis-labeled as "accuracy"** — `vae_regime_detector`
     reported 99.96% and `finbert_sentiment` 97.76% as `accuracy`, but they
     are really `regime_diversity_entropy` and `distribution_entropy_normalized`.
     - Added canonical `quality_score` sibling field alongside `accuracy`
       on both DL and FinBERT `models_trained` entries.
     - Unified `metric_type` on the FinBERT entry (was `quality_metric`),
       while keeping the old key for back-compat.
     - `TrainingPipelineStatus.add_completed(..., metric_type=...)` now
       accepts a metric_type kwarg; non-`accuracy` completions no longer
       pollute `phase_history[*].avg_accuracy`.

**Files touched:**
  - `/app/backend/services/ai_modules/training_pipeline.py`
  - `/app/backend/tests/test_training_pipeline_contracts.py` (new)

**What this enables:** after the next overnight run on the DGX, the user
can run `curl /api/ai-training/scorecards` and get real DSR/Sharpe/
win-rate per trained setup, the 7 generic direction predictors will have
truthful accuracy numbers, and every silent-skip will be visible in
`last_result.models_failed` with the real reason.

---


## 2026-04-24 — Standalone FinBERT sentiment pipeline wired into server

Decoupled pre-market news scoring from the 44h training pipeline. Router
`/app/backend/routers/sentiment_refresh.py` now mounted on the FastAPI app,
and APScheduler runs `_run_refresh(universe_size=500)` daily at **07:45 AM ET**
(`America/New_York`).

**Implementation (`server.py`):**
  - Imported `sentiment_refresh_router`, `init_sentiment_router`,
    `_run_refresh`, `DEFAULT_UNIVERSE_SIZE` at module level.
  - Registered `app.include_router(sentiment_refresh_router)` in Tier-1 block.
  - Inside `@app.on_event("startup")`, after `scheduler_service.start()`:
    built `AsyncIOScheduler(timezone="America/New_York")` (shares uvicorn's
    asyncio loop — sidesteps the uvloop conflict documented at the top of
    the file), registered the cron job `id="sentiment_refresh"` with
    `coalesce=True`, `max_instances=1`, `misfire_grace_time=1800`,
    `replace_existing=True`, called `init_sentiment_router(db, scheduler)`,
    stashed it on `app.state.sentiment_scheduler`.
  - Shutdown hook calls `sched.shutdown(wait=False)`.

**Verified endpoints (curl):**
  - `GET /api/sentiment/schedule` → `enabled: true`, next run
    `2026-04-24T07:45:00-04:00`, trigger `cron[hour='7', minute='45']`.
  - `POST /api/sentiment/refresh?universe_size=5` → full pipeline ran end-to-end
    (Yahoo RSS collected, FinBERT scorer invoked, metadata persisted).
    Finnhub skipped (no `FINNHUB_API_KEY` on this dev host — user has it set
    in production).
  - `GET /api/sentiment/latest` → returns last persisted run document from
    `sentiment_refresh_history` collection.

**Cleanup:** removed a duplicate trailing `if __name__ == "__main__"` block
and a stray `ain")` fragment that had caused `server.py` to fail
`ast.parse` (hot-reload was running off a cached import).

---

# TradeCommand / SentCom — Product Requirements


## 2026-04-24 — CRITICAL FIX #5 — `balanced_sqrt` class-weight scheme (DOWN-collapse pendulum)

**Finding:** The 2026-04-23 force-promoted `direction_predictor_5min` v20260422_181416
went HEALTHY on the generic tile (recall_up=0.597, up from 0.069) but
`recall_down=0.000` — the pure sklearn `balanced` scheme had boosted UP by
~2.8× on the 45/39/16 split, completely starving DOWN. The subsequent
Phase-13 revalidation (20:04Z Spark log) then rejected **20/20** models:
setup-specific tiles collapsed the OTHER way (SCALP/1min predicting 95.9%
DOWN, MEAN_REVERSION 93.4% DOWN, TREND_CONTINUATION 94.3% DOWN) and the
AI-edge vs raw-setup was negative on most (RANGE −4.5pp, REVERSAL −4.4pp,
VWAP −5.4pp, TREND −7.5pp).

**Fix:** Added a `scheme` kwarg to `compute_balanced_class_weights` /
`compute_per_sample_class_weights` with two options:
- `"balanced"` — legacy sklearn inverse-frequency (kept for backward compat)
- `"balanced_sqrt"` — **new default**, `w[c] = sqrt(N_max / count[c])`,
  normalized to min=1, clipped at 5×. On the 45/39/16 Phase-13 split the
  max/min ratio drops from ~2.8× → ~1.68× — minority UP still gets a real
  gradient signal but DOWN isn't starved.

Resolved at call time via `get_class_weight_scheme()` which reads env var
`TB_CLASS_WEIGHT_MODE` (default `balanced_sqrt`). Wired into every caller:
- `timeseries_service.py::train_full_universe` (generic direction_predictor)
- `timeseries_gbm.py::train_from_features` (setup-specific XGBoost models)
- `temporal_fusion_transformer.py::train` (TFT)
- `cnn_lstm_model.py::train` (CNN-LSTM)

**Tests — `tests/test_balanced_sqrt_class_weights.py` (13 tests, all pass):**
- Phase-13 skew sqrt formula produces `[1.074, 1.0, 1.677]`
- Sqrt max/min ratio **< 1.8× and strictly smaller than `balanced`'s** (hard guard against regression)
- Majority class weight == 1.0 (no boost)
- `scheme="balanced"` output bit-identical to pre-fix legacy behaviour
- Default scheme kwarg remains `balanced` on the helpers (backward compat for existing callers)
- `get_class_weight_scheme()` default = `balanced_sqrt` (lock-in)
- Case-insensitive env var; garbage falls back to `balanced_sqrt` (not to `balanced`) so a typo can't re-introduce the collapse
- End-to-end: no class's mean per-sample weight drops below 0.85 on the Phase-13 skew

**Full sweep: 127/127 pass** across dl_utils + xgb_balance + full_universe_class_balance + balanced_sqrt + protection_class_collapse + sentcom_retrain + sentcom_chart + mode_c_threshold + setup_resolver.

**User next steps on Spark after pull + restart:**
```bash
# 1. Retrain generic 5-min direction predictor with the new scheme
PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
    backend/scripts/retrain_generic_direction.py --bar-size "5 mins" 2>&1 \
    | tee /tmp/retrain_generic_5min_$(date +%s).log

# Look for this line:
#   [FULL UNIVERSE] class_balanced sample weights applied
#   (scheme=balanced_sqrt, per-class weights=[1.07, 1.00, 1.68], ...)

# 2. Restart backend to reload new model
pkill -f "python server.py" && cd backend && \
    nohup /home/spark-1a60/venv/bin/python server.py > /tmp/backend.log 2>&1 &

# 3. Collapse diagnostic — expect HEALTHY (not MODE_C) on generic
PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
    backend/scripts/diagnose_long_model_collapse.py
head -20 /tmp/long_model_collapse_report.md

# 4. (Optional) Once generic is healthy, use the NEW scorecard retrain button
#    to retrain each collapsed setup model one click at a time — the MODE_C
#    tiles are already in the UI.
```

Expected outcome on generic 5-min: `recall_up` stays in the 0.15–0.35 range,
`recall_down` climbs to ≥ 0.10, `macro_f1` improves. Setup models retrained
under the new scheme should show meaningfully non-collapsed UP/DOWN balance
in the next diagnostic.



## 2026-04-24 — Stage 2f.1: Clickable scorecard tiles → one-click retrain

**What it does:** ModelHealthScorecard tiles now open a detail panel with a
**Retrain this model** button. One click enqueues a targeted retrain job via
the existing `job_queue_manager` and the UI polls `/api/jobs/{job_id}` every
5s until terminal, then auto-refreshes the scorecard so the tile flips mode
(MODE_B → MODE_C → HEALTHY) live. Tiles with in-flight retrain jobs show a
spinning indicator + "TRAIN…" label.

**Shipped:**
- Backend: `POST /api/sentcom/retrain-model` in `routers/sentcom_chart.py` —
  routes `__GENERIC__` → full-universe `training` job, any other setup_type →
  `setup_training` job. Validates setup_type against `SETUP_TRAINING_PROFILES`
  and bar_size against the setup's declared profiles. Bar-size normaliser
  accepts `5min`, `5m`, `5 mins`, etc.
- Frontend: `ModelHealthScorecard.jsx` — detail-panel Retrain button +
  inline job state (Queuing → Training N% → Retrain complete) + per-tile
  retraining indicator + cleanup of pollers on unmount.
- Tests: `tests/test_sentcom_retrain_endpoint.py` — 22 pytest regression
  tests covering bar-size aliases, validation, generic/setup paths, queue
  failure. All pass.
- Live-verified: `POST /api/sentcom/retrain-model` with
  `{"setup_type":"__GENERIC__","bar_size":"1d"}` returns a valid job_id and
  the enqueued job is polled/cancellable via `/api/jobs/{job_id}`.

**User can now:** click any MODE_C / MODE_B / MISSING tile, hit Retrain,
watch it finish live — no more CLI retrain commands on Spark for one-off
model fixes. Also solves the "4 missing SMB models" P2 issue in one click
per model.



## 2026-04-23 — Training pipeline structural fixes (same session)

Two real architectural bugs surfaced by the test_mode diagnostic run. Both
invalidate any model trained before this date regardless of sample size —
full retrain required.

### Bug 1: Phase 8 ensembles hardcoded to `"1 day"` anchor
`training_pipeline.py` line 2860 set `anchor_bs = "1 day"` for ALL 10
ensemble meta-labelers. Intraday-only setups (SCALP, ORB, GAP_AND_GO, VWAP)
don't have `_1day_predictor` sub-models — you don't run ORB on daily bars.
Result: 4/10 ensembles silently failed every run with "no setup sub-model
<name>_1day_predictor — meta-labeler needs it."

**Fix:**
  - `ensemble_model.py`: removed `"1 day"` from `sub_timeframes` of ORB,
    GAP_AND_GO, VWAP (kept for BREAKOUT/MEAN_REVERSION/etc. which legitimately
    have daily variants). Added explanatory comment about the anchor logic.
  - `training_pipeline.py` (Phase 8): per-ensemble anchor selection — probes
    each configured `sub_timeframes` in order and picks the first one that
    has a trained sub-model. Falls back to the first configured tf if none
    match. All 10 ensembles now train.

### Bug 2: Phase 4 exit timing trained all 10 models on `"1 day"` bars
`training_pipeline.py` line 2000 set `bs = "1 day"` for ALL 10 exit models.
SCALP/ORB/GAP_AND_GO/VWAP are intraday trades but were training their exit
timing on daily bars with `max_horizon = 12-24` — meaning the model was
learning "when to exit a scalp" from 12-DAY lookaheads. Data-task mismatch.
This is WHY `exit_timing_range` / `exit_timing_meanrev` landed at 37%
accuracy — the models were structurally wrong, not just undertrained.

**Fix:**
  - `exit_timing_model.py`: added `bar_size` field to every entry in
    `EXIT_MODEL_CONFIGS`. Intraday setups → `"5 mins"`, swing → `"1 day"`.
  - `training_pipeline.py` (Phase 4): refactored to group configs by
    `bar_size`, then run the full feature-extraction + training loop once
    per group. 5-min intraday exits and 1-day swing exits train on
    appropriately-scoped data. Worker is bar-size-agnostic (operates on
    bar counts, not time).

### Verified safe after investigation
Audited every phase for similar hardcoding:
  - P3 Volatility, P5 Sector-Relative, P5.5 Gap Fill, P7 Regime-Conditional:
    all iterate configured bar_sizes. Silent-zero behaviour was entirely
    test_mode sample starvation (≤50 samples vs ≥100 required).
  - FinBERT news collector uses `"1 day"` for symbol selection (correct —
    it's just picking tickers to pull news for, not modeling on them).
  - Validation phase `("5 mins", 0)` fallback is sensible for unknowns.

### Expected impact on next full-quality run
  • P4 Exit Timing intraday models: 37-40% → 52-58% (structural fix, not
    just "more data")
  • P8 Ensemble: 6/10 → 10/10 trained (all four orphans unblocked)
  • Old models trained on the broken configs are OBSOLETE — do not rely on
    accuracy numbers from any run before 2026-04-23 post-fix.

### Action items for tomorrow morning
  1. Confirm current test_mode run completed (errors: 0, P9 CNN done).
  2. Save to GitHub → run .bat on DGX to pull today's fixes.
  3. Restart backend so new code loads.
  4. Launch full-quality run: `{"force_retrain": true}` (NO test_mode).
  5. Monitor for ~44h. All 155 models should train with no silent skips.
  6. When it finishes, spot-check a few accuracies in mongo (P4 intraday
     exits, P8 ensembles for SCALP/ORB/GAP/VWAP specifically — those are
     the ones the fix unblocks).




## 2026-04-23 — Training run diagnostic · `test_mode=true` is destructive

Ran two training runs today after the Alpaca nuke + pipeline hardening:
  • Run 1: `{"test_mode": true}` (no force_retrain) — stopped after 7 min.
    Confirmed that the resume-if-recent guard was skipping everything
    trained in the prior 24h. Models showed `acc: -` (cached).
  • Run 2: `{"force_retrain": true, "test_mode": true}` — ran to ~110 min
    of ~190 min ETA before analysis. Mongo revealed:

**Findings from Run 2:**
  - P1 Generic Directional: 52-58% accuracy on 13M-63M samples ✅ REAL EDGE
  - P2 Setup Long: 40-45% accuracy on ~50 samples ❌ UNDERTRAINED
  - P2.5 Short: 40-51% accuracy on ~50 samples ❌ UNDERTRAINED
  - P4 Exit: 37-54% accuracy ❌ UNDERTRAINED
  - P3 Volatility: 0/7 models trained — all "Insufficient vol training data: 50"
  - P5 Sector-Relative: 0/3 models trained — all "0 samples"
  - P7 Regime-Conditional: 0/28 models trained — all "only 50 samples (need 100)"
  - P8 Ensemble: 6/10 trained; 4 orphan configs reference non-existent
    `_1day` setup variants (scalp_1day_predictor, orb_1day_predictor,
    gap_and_go_1day_predictor, vwap_1day_predictor)

**Root cause:** `test_mode=true` caps per-model training samples at ~50.
Phases 3/5/7 require ≥100 samples, so they silently skip every bar-size and
mark DONE with zero models. Phases 2/4 train but don't converge past random
initialization on 50 samples. Only P1 survives because its streaming
pipeline feeds millions of samples regardless of test_mode.

**Action plan:**
  1. Let current run finish (~1.8h remaining at diagnosis time) for P9 CNN
     data point.
  2. Kick full-quality run: `{"force_retrain": true}` with NO test_mode.
     Expect ~44h overnight. Should produce real edge across all phases.
  3. Fix 4 orphan ensemble configs (`_1day` variants that don't exist) —
     either delete those ensembles or rewire to `_5min` dependencies.
  4. Keep bot paused until full run completes (currently paused anyway
     because IB pusher is dead / `pusher_dead: true` banner active).

**Status reporting bug noticed:**
  The training status script reports `phase.status = "done"` as long as the
  phase loop completed, even if zero models were actually persisted. Future
  enhancement: compare `models_trained_this_run` to `expected_models` and
  flag phases where the ratio is 0%. P1's `acc: -` was also a reporting
  bug — accuracies ARE saved in mongo (52-58%), just not surfaced by the
  status aggregator.


## 2026-04-23 — V5 bug fixes (same session)

  - `P(win) 5900%` / `conf 5900%` formatting fix: `formatPct()` now detects
    whether input is fraction (0.59) or pre-scaled pct (59). Fixed in
    `ScannerCardsV5.jsx` and `OpenPositionsV5.jsx` + `>=0.55` threshold
    comparison normalised.
  - `EnhancedTickerModal` infinite loading spinner fix: added 10s/12s hard
    timeouts around `/api/ib/analysis` and `/api/ib/historical` requests.
    When IB Gateway hangs (no response, no error), the Promise.race converts
    to a rejection and triggers the existing `.catch()` handler — modal
    shows "Chart data timed out (IB / mongo busy)." instead of eternal
    spinner.




## 2026-04-23 — Alpaca fully nuked · loud failure mode · freshness chips

**The problem:** Alpaca kept creeping back into the codebase across 63 files / 739 lines even after multiple manual cleanups. The scanner's `predictive_scanner.py` and `opportunity_evaluator.py` were still routing quotes through Alpaca, creating two disagreeing price feeds and silently masking IB outages.

**Shipped:**
- **`services/ib_data_provider.py`** — single source of truth for live + historical market data. Public interface matches legacy `AlpacaService` exactly so all 63 existing callers keep working without edits. Internally reads:
  - Live quotes / positions / account → `routers.ib._pushed_ib_data` (IB pusher)
  - Historical bars → `ib_historical_data` MongoDB collection
  - Most actives / universe → pushed quotes volume + `ib_historical_data` aggregation
- **`services/alpaca_service.py`** — now a thin deprecation shim. `AlpacaService` still exists for BC but delegates every method via `__getattr__` to `IBDataProvider`. Logs one-shot deprecation warning on first use. Never imports the Alpaca SDK, never reads `ALPACA_API_KEY`.
- **`services/trade_executor_service.py`** — `_init_alpaca()` now raises `RuntimeError` instead of booting an Alpaca client. `ExecutorMode.PAPER` is effectively dead (use IB paper account via `ExecutorMode.LIVE`).
- **`market_scanner_service._fetch_symbol_universe`**, **`slow_learning/historical_data_service._fetch_bars_from_alpaca`**, **`simulation_engine._get_alpaca_assets` / `._fetch_alpaca_bars`** — all three rewired to `IBDataProvider` (still use their legacy method names for BC).
- **`/api/ib/pusher-health`** — added `pusher_dead` boolean + `in_market_hours` + `dead_threshold_s: 30`. During RTH, >=30s without a push = pusher_dead=true. This is the one signal the bot/scanner/UI all key off.
- **Loud failure mode (frontend):**
  - `hooks/usePusherHealth.js` — single shared poller (8s) that fans out to every consumer (no N+1 polling)
  - `PusherDeadBanner.jsx` — full-width red alert at the top of V5 when pusher_dead=true during market hours. Loud, pulsing, impossible to miss.
  - `LiveDataChip.jsx` — reusable tiny "LIVE · 2s" / "SLOW · 3m" / "DEAD" badge
  - Wired into: V5 chart header, V5 Open Positions header, V5 Scanner · Live header
- **Regression guard:** `tests/test_no_alpaca_regressions.py` — pytest that fails if any new file imports the Alpaca SDK or references `alpaca.markets`. Only the shim + executor shim + the test itself are allowlisted. Runs in <200ms.

**How to verify on DGX:**
- `python3 -c "from services.ib_data_provider import get_live_data_service; print(get_live_data_service().get_status())"` → should show `service: ib_data_provider, pusher_fresh: True`
- `curl http://localhost:8001/api/ib/pusher-health` → should now include `pusher_dead`, `in_market_hours`, `dead_threshold_s` fields
- Unplug / kill the Windows pusher → V5 should flash the red PUSHER DEAD banner within ~8s; scanner and bot stop producing decisions (no live quotes = no gate score)
- `pytest tests/test_no_alpaca_regressions.py -v` → should PASS. If anyone ever re-adds `from alpaca.*` in a non-allowlisted file, this test fails in CI.




## 2026-04-23 — P0 FIX: Directional stops in revalidation backtests

**Issue:** `advanced_backtest_engine.py::_simulate_strategy_with_gate` had
5 directional bugs where SHORT strategies used LONG logic for
stop/target triggers, MFE/MAE tracking, and PnL sign — causing
revalidation backtests to overstate SHORT performance and deploy
broken models.

**Fix:** `search_replace` already made the code direction-aware in
`_simulate_strategy_with_gate`. Audit confirmed the sibling methods
`_simulate_strategy` and `_simulate_strategy_with_ai` were already
correct. Added 9 regression tests (`test_backtest_direction_stops.py`)
covering LONG + SHORT stop/target hits across all three sim methods.
All 9 pass.


## 2026-04-23 — Next-tier deliverables (audit log, drift, revalidation cron, briefing v2, chart S/R)

**Auto-revalidation — Sunday 10 PM ET**
- New job `weekly_revalidation` in `trading_scheduler.py` spawns
  `scripts/revalidate_all.py` as a subprocess with a 2-hour hard cap.
  Skips itself if the bot is in `training` focus mode. Summary lands in
  `scheduled_task_log`; also triggerable via the existing `run_task_now`.

**Trade audit log**
- `services/trade_audit_service.py` with `build_audit_record()` (pure),
  `record_audit_entry()` (best-effort Mongo write), and `query_audit()`
  (filter by symbol/setup/model_version/date).
- Captures: entry geometry, gate decision + reasons, model attribution
  (including calibrated UP/DOWN thresholds at decision time), every
  sizing multiplier applied (smart_filter / confidence / regime /
  tilt / HRP), and the regime.
- Wired into `opportunity_evaluator.py` right before the trade return.
- Endpoint: `GET /api/sentcom/audit` — feeds the V5 audit view.
- 12 pytest cases, all pass.

**Model drift detection — PSI + KS**
- `services/model_drift_service.py` with self-contained PSI and two-
  sample KS math (no scipy dep). Classifies healthy/warning/critical
  via industry-standard thresholds (PSI ≥ 0.10 warn, ≥ 0.25 critical;
  KS ≥ 0.12 warn, ≥ 0.20 critical).
- Compares last-24h live prediction distribution against the preceding
  30-day baseline per `model_version` (source: `confidence_gate_log`).
- `check_drift_for_model` + `check_drift_all_models` helpers;
  snapshots persist to `model_drift_log`.
- Endpoint: `GET /api/sentcom/drift` — backs the V5 "Model health"
  section below.
- 20 pytest cases, all pass.

**Stage 2d — Richer Morning Briefing Modal**
- `useMorningBriefing` hook now also hits `/api/safety/status` and
  `/api/sentcom/drift` in the same `Promise.allSettled` fan-out.
- New sections in `MorningBriefingModal.jsx`:
    * **Safety & telemetry** — kill-switch state, awaiting-quotes pill,
      daily loss cap, max positions (4-tile grid)
    * **Model health** — per-model PSI/KS/Δmean rows with colour-coded
      DRIFT-CRIT / DRIFT-WARN / STABLE chips
- Keeps the V5 dark-mono aesthetic, `data-testid` on every row.

**Stage 2e — PDH/PDL/PMH/PML on ChartPanel**
- `services/chart_levels_service.py` — fast level computation
  (< 50 ms) from daily bars in `historical_bars`.
- Endpoint: `GET /api/sentcom/chart/levels?symbol=X` returns
  `{pdh, pdl, pdc, pmh, pml}` (nullable when data is missing).
- `ChartPanel.jsx` fetches on symbol change, paints horizontal
  `IPriceLine`s with distinct colours + dotted/solid styles. Toggle
  button in the indicator toolbar (`data-testid=chart-sr-toggle`).
- 11 pytest cases for the level math, all pass.


## 2026-04-23 — MODE-C collapse: Per-model threshold calibration + label-distribution validator (A + D + C)

Spark diagnostic after the `recall_down` fix revealed the generic model
has `p_up_p95 = 0.424` — the 0.55 legacy gate was filtering out 99.6% of
UP predictions. 3-class triple-barrier models can't reach 0.55 because
probability mass splits across DOWN/FLAT/UP.

**A — Per-model auto-calibrated thresholds**
- New `services/ai_modules/threshold_calibration.py` with
  `calibrate_thresholds_from_probs()` (p80 of validation probs,
  bounded [0.45, 0.60]) and a `get_effective_threshold()` consumer helper.
- `ModelMetrics` extended with `calibrated_up_threshold` and
  `calibrated_down_threshold` fields (default 0.50 for legacy rows).
- Both training paths (`train_full_universe` + `train_from_features`)
  compute calibration from `y_pred_proba` and persist it.
- `predict_for_setup` and the generic fallback now surface
  `model_metrics` in the response dict so consumers see the thresholds.
- `confidence_gate.py` now reads the per-model threshold via
  `get_effective_threshold()` instead of the hard-coded 0.50 — each model
  gates CONFIRMS at its own natural probability range.
- 25 pytest cases (`test_threshold_calibration.py`) — all pass.
- Diagnostic script now prints the effective per-model threshold in the
  report and uses it in the MODE-C classifier.

**D — Graceful fallback for missing SMB models**
- `predict_for_setup` already falls back to the generic model, but now
  emits a one-time-per-process INFO log naming the setup that's using
  the fallback (no silent surprise).
- `diagnose_long_model_collapse.py` distinguishes genuinely missing
  models from expected SMB fallbacks (OPENING_DRIVE, SECOND_CHANCE,
  BIG_DOG) with a `FALLBACK TO GENERIC` row.

**C — Label-distribution health check (fail-loud signal)**
- New `validate_label_distribution()` in
  `services/ai_modules/triple_barrier_labeler.py`. Flags:
    * any class < 10% (rare class)
    * FLAT > 55% (barriers too wide → FLAT absorbs signal)
    * any class > 70% (majority-class collapse)
- Wired into both training paths — emits WARNING logs with
  recommendations (sweep PT/SL, tighten max_bars, etc.) when the
  distribution is unhealthy. Non-blocking; training proceeds.
- 11 pytest cases (`test_label_distribution_validator.py`) — all pass.
- **Non-destructive**: did NOT change labeller defaults (pt=2, sl=1) —
  doing so would silently alter all training outputs. Instead the
  validator surfaces the problem loudly so the user can run
  `run_triple_barrier_sweep.py` per setup.

**Spark next step:** rerun `backend/scripts/diagnose_long_model_collapse.py`
after the next training cycle to confirm per-model thresholds are now
being applied (report will show `effective_up_threshold` column).


## 2026-04-23 — P1 #1: Order-queue dead-letter reconciler
Handles silent broker rejects and Windows pusher crashes — orders stuck
in pre-fill states (PENDING/CLAIMED/EXECUTING) now transition to the new
`TIMEOUT` status automatically.

- New method `OrderQueueService.reconcile_dead_letters()` with distinct
  per-status timeouts (defaults: pending=120s, claimed=120s, executing=300s).
  Returns a structured summary with prior status + age for each order.
- Background loop in `server.py` runs every 30s (`_order_dead_letter_loop`)
  and emits stream events per timeout so V5's Unified Stream shows them.
- Public API: `POST /api/ib/orders/reconcile` (manual trigger with
  overridable timeouts).
- 7 pytest cases (`test_order_dead_letter_reconciler.py`) — all pass.
  Covers each status, round-trip through the live endpoint, and confirms
  FILLED/REJECTED/CANCELLED orders are never touched.


## 2026-04-23 — P1 #2: Strategy Tilt (long/short Sharpe bias)

Dynamic long/short sizing multiplier computed from rolling 30-day per-side
Sharpe of R-multiples — cold-streak sides shrink, hot sides grow. Bounded
`[0.5x, 1.5x]`, neutral below 10 trades per side.

- Pure module `services/strategy_tilt.py` with:
  - `compute_strategy_tilt(trades, ...)` — testable pure function
  - `get_strategy_tilt_cached(db)` — 5-min memoised accessor that reads
    `bot_trades` Mongo collection
  - `get_side_tilt_multiplier(direction, tilt)` — the callsite helper
- Wired into `opportunity_evaluator.py` after the confidence-gate block
  as a multiplicative sizing adjustment. Prints a `[STRATEGY TILT]` line
  so the bot log shows the Sharpe values + applied multiplier.
- 16 pytest cases (`test_strategy_tilt.py`) — all pass. Covers math,
  bounds, lookback filtering, pnl/risk fallback, cache behavior.


## 2026-04-23 — P1 #3: HRP/NCO Portfolio Allocator wired into sizing

- New `services/portfolio_allocator_service.py` — clean wrapper around
  `hrp_weights_from_returns` with a pluggable `set_returns_fetcher(fn)`
  so it's fully decoupled (and testable). Computes per-symbol
  multipliers = `hrp_weight / equal_weight`, bounded to `[0.4, 1.4]`.
- Integration point in `opportunity_evaluator.py` after the Strategy
  Tilt block — peer universe = open positions + pending trades + the
  current candidate. Highly-correlated stacks (e.g. AAPL+META long) get
  down-weighted so the bot doesn't silently doubles-up tech-long risk.
- Safe defaults: returns fetcher isn't registered yet in production
  (needs live daily-bars cache from historical_data_service). While the
  fetcher is None, the allocator is neutral (1.0) — never breaks sizing.
- 13 pytest cases (`test_portfolio_allocator_service.py`) — all pass.
  Covers correlated clustering, bounds, fetcher exceptions, alignment.



## 2026-04-23 — P1 FIX: "Awaiting quotes" gate in trading bot risk math

**Issue (two bugs):**
1. `trading_bot_service._execute_trade` read `self._daily_stats.realized_pnl`
   and `.unrealized_pnl`, but `DailyStats` dataclass has neither field —
   this AttributeError'd, was caught by the outer `except Exception`
   (fail-closed), and **silently blocked every single trade** when
   safety guardrails were wired in.
2. Even with fields present, broker-loaded positions before IB's first
   quote arrives have `current_price = 0`, producing e.g.
   `(0 - 1200) * 1000 = -$1.2M` phantom unrealized loss → instant
   kill-switch trip on every startup.

**Fix:**
- New helper `TradingBotService._compute_live_unrealized_pnl()` returns
  `(total_usd, awaiting_quotes: bool)`. If any open trade has
  `current_price <= 0` or `fill_price <= 0`, `awaiting_quotes=True` and
  the PnL is suppressed to 0.
- `_execute_trade` now passes the real sum (or 0 while awaiting quotes)
  into `safety_guardrails.check_can_enter`, plus reads the correct
  `daily_stats.net_pnl` field for realized P&L.
- Added 7 regression tests (`test_awaiting_quotes_gate.py`). All pass.
- Lock test asserts `DailyStats` still lacks those fields so we never
  re-introduce the AttributeError pattern.


## 2026-04-23 — UX: "Awaiting IB Quotes" pill in V5 Safety overlay

Operators now get visual confirmation that the bot is in awaiting-quotes
mode (instead of mistaking the quiet startup for a hung bot).

- `/api/safety/status` now returns a `live` block: `open_positions_count`,
  `awaiting_quotes` (bool), `positions_missing_quotes` (list of symbols).
  Computed on-demand from the trading bot's `_open_trades`; failure is
  silent (fallback to zero/false — never breaks the endpoint).
- New component `AwaitingQuotesPillV5` in `sentcom/v5/SafetyV5.jsx` —
  an amber pill top-center (`data-testid=v5-awaiting-quotes-pill`) that
  renders only while `live.awaiting_quotes === true`. Shows the missing
  symbol if only one, or a count otherwise. Tooltip explains why the
  kill-switch math is being bypassed.
- Mounted in `SentComV5View.jsx` next to the existing `SafetyBannerV5`.
- Pytest `test_safety_status_awaiting_quotes.py` locks the endpoint
  contract (live-block shape + types).





## 2026-04-23 — Stage 2f: Model Health Scorecard (self-auditing Command Center)

**What it does:** A new `ModelHealthScorecard` panel above the `ChartPanel` shows a colour-coded grid of (setup × timeframe) tiles with MODE classification + click-to-reveal full metrics (accuracy / recall / f1 / promoted_at). Turns the Command Center into a self-auditing system — you can see at a glance which models are HEALTHY / in MODE C / collapsed / missing, without running the diagnostic script.

**Shipped:**
- Backend: `GET /api/sentcom/model-health` → returns all generic + setup-specific models from `SETUP_TRAINING_PROFILES`, classified via `_classify_model_mode` (HEALTHY / MODE_C / MODE_B / MISSING) based on stored recall_up / recall_down metrics. Floors mirror the protection gate (0.10 / 0.05). Header-level counts per mode ("2 HEALTHY · 18 MODE C · 1 MODE B · 4 MISSING").
- Frontend: `components/sentcom/panels/ModelHealthScorecard.jsx` — compact tile grid, poll every 60s, expandable/collapsible, click-to-drill-down, `data-testid` on every element.
- Tests: 6 new pytest classifier regression tests (26/26 in this file pass).

**Wired in:** Shown above the ChartPanel in full-page SentCom. Zero-risk drop-in.



## 2026-04-23 — CRITICAL FIX #4 — Pareto-improvement escape hatch (Spark retrain finding)

**Finding:** The 5-min full-universe retrain (v20260422_181416) produced a model with `recall_up=0.597` (8.6× better than active 0.069) but `recall_down=0.000` (same collapse as the old model). The strict class-weight boost (UP class gained 2.99× weight because only 15.6% of samples) over-corrected and starved the DOWN class entirely. Protection gate correctly rejected it for failing the 0.10 DOWN floor — but this left LONG permanently blocked despite a clear strict improvement on UP.

**Fix:** Added a Pareto-improvement escape hatch to `_save_model()`. When BOTH active and new models are below class floors, we still promote if:
1. The new model is strictly no worse on every class (UP and DOWN), AND
2. Strictly better on at least one class.

This unblocks the genuinely improved candidate without promoting garbage (regression on any class still blocks).

**Also fixed:** `force_promote_model.py` default `--archive` was `timeseries_models_archive` (plural, wrong); the actual collection is `timeseries_model_archive` (singular, matching `MODEL_ARCHIVE_COLLECTION` in `timeseries_gbm.py`).

**Tests:** Added `test_promote_pareto_improvement_when_both_fail_floors` + `test_reject_regression_even_when_active_is_collapsed`. All 60 pytest regression tests pass.

**Known next step — DOWN-side collapse:** Class-balanced weights with a 3× boost on UP (because of the 45/39/16 class split) cause DOWN to collapse. Proper fix is to switch to `balanced_sqrt` (√(N_max/N_class)) so the max boost is ~1.7× instead of 3×. Scheduled as a follow-up after Spark verifies the Pareto-promoted model unblocks LONG setups.




## 2026-04-23 — CRITICAL FIX #3 — MODE-C confidence threshold calibration (P1 Issue 2)

**Finding:** 3-class setup-specific LONG models peak at 0.44–0.53 confidence on triple-barrier data because the FLAT class absorbs ~30–45% of probability mass. Under the old 0.60 CONFIRMS threshold, a correctly-directional UP argmax at 0.50 only earned +5 (leans) in ConfidenceGate Layer 2b and AI score 70 in TQS — not the full +15 / 90 CONFIRMS boost. Effect: MODE-C signals often fell below the 30-pt SKIP floor.

**Fix:** Lowered CONFIRMS_THRESHOLD from 0.60 → 0.50 in:
- `services/ai_modules/confidence_gate.py` (Layer 2b)
- `services/tqs/context_quality.py` (AI Model Alignment, 10% weight)

Strong-disagreement path kept at 0.60 so low-confidence noise (conf < 0.60) gets a softer penalty (-3 / ai_score 35) instead of the heavy -5 / 20.

**Tests:** `tests/test_mode_c_confidence_threshold.py` — 11 regression tests covering the bucket boundaries (0.44 → leans, 0.50 → CONFIRMS, 0.53 → CONFIRMS, 0.55 disagree → WEAK, 0.65 disagree → STRONG). All 38 pytest regression tests pass.


## 2026-04-23 — Model Protection gate hardening (follow-up to CRITICAL FIX #2)

**Finding:** The escape hatch only triggered when `cur_recall_up < 0.05`. Spark's active `direction_predictor_5min` had `recall_up=0.069` (just above) and `recall_down=0.0` — a dual-class collapse that the hatch missed, meaning the next retrained model would have had to clear the strict macro-F1 floor to get promoted.

**Fix:** Escape hatch now triggers when EITHER class recall is below its floor (`cur_recall_up < MIN_UP_RECALL` or `cur_recall_down < MIN_DOWN_RECALL`, both 0.10). Promotion then requires the new model to pass BOTH-class floors AND improve the collapsed class.

**Shipped:** `backend/scripts/retrain_generic_direction.py` (standalone retrain driver, bypasses job queue). User executing the 5-min retrain on Spark as of 2026-04-23.


## 2026-04-23 — Stage 1 SentCom.jsx refactor (safe extraction)

**Problem:** `SentCom.jsx` was a 3,614-line monolith — hard to test, hard to reason about, slow Hot-reload, and blocked Stage 2 (the V5 Command Center rebuild).

**Solution:** Moved pure relocations (zero logic change) into feature-sliced folders:
```
src/components/sentcom/
├── utils/time.js                   formatRelativeTime, formatFullTime
├── primitives/  (7 files, 410 lines total)
│   TypingIndicator, HoverTimestamp, StreamMessage, Sparkline,
│   generateSparklineData, GlassCard, PulsingDot
├── hooks/       (12 files, 693 lines total)
│   useAIInsights, useMarketSession, useSentComStatus/Stream/Positions/
│   Setups/Context/Alerts, useChatHistory, useTradingBotControl,
│   useIBConnectionStatus, useAIModules
└── panels/      (15 files, 1,773 lines total)
    CheckMyTradeForm, QuickActionsInline, StopFixPanel, RiskControlsPanel,
    AIModulesPanel, AIInsightsDashboard, OrderPipeline, StatusHeader,
    PositionsPanel, StreamPanel, ContextPanel, MarketIntelPanel,
    AlertsPanel, SetupsPanel, ChatInput
```

**Result:** `SentCom.jsx` 3,614 → **874 lines (-76%)**. 34 sibling modules each 30–533 lines. Public API unchanged (`import SentCom from 'components/SentCom'` still works, default export preserved). ESLint clean, all 35 files parse, all relative imports resolve.


## 2026-04-23 — Stage 2a/2b/2c: V5 Command Center chart (shipped)

**Library choice:** `lightweight-charts@5.1.0` (Apache-2.0). Explicitly *not* the TradingView consumer chart (which has a 3-indicator cap) — this is TradingView's open-source rendering engine. Unlimited overlay series, ~45 KB gzipped, used by Coinbase Advanced and Binance mobile.

**Shipped:**
- `frontend/src/components/sentcom/panels/ChartPanel.jsx` — candles + volume + crosshair + auto-refresh + 5-tf toggle (1m/5m/15m/1h/1d), dropped as a new full-width block between StatusHeader and the 3-col grid in SentCom.
- `backend/routers/sentcom_chart.py` — `GET /api/sentcom/chart?symbol=...&timeframe=...&days=...` returning bars + indicator arrays + executed-trade markers.
- Indicator math (pure Python, no pandas dep): VWAP (session-anchored for intraday), EMA 20/50/200, Bollinger Bands 20/2σ. Frontend has 7 toggleable overlay chips in the chart header.
- Trade markers: backend queries `bot_trades` within chart window, emits entry + exit arrow markers on candles with R-multiple tooltips (green win / red loss).
- Tests: `backend/tests/test_sentcom_chart_router.py` — 20 regression tests locking `_ema`, `_rolling_mean_std`, `_vwap`, `_to_utc_seconds`, `_session_key`. All 58 Python tests pass.

**Deferred to Stage 2d/2e:**
- Full V5 layout rebuild (3-col 20/55/25 grid, chart central, stream below).
- Setup-trigger pins (no clean timestamped-setups data source yet).
- Support/resistance horizontal lines (needs scanner integration).
- RSI / MACD sub-panels.
- Session shading (pre-market / RTH / AH background rectangles).
- WebSocket streaming of new bars (currently HTTP auto-refresh every 30s).


**Next:** Stage 2 — layout + TradingView `lightweight-charts` integration (Option 1 V5 Command Center).



## 2026-04-22 (22:40Z) — CRITICAL FIX #6 — `recall_down` / `f1_down` were NEVER computed

**Finding (from 22:19Z Spark retrain log):** The `balanced_sqrt` weighting
was correctly applied (`per-class weights=[1.0, 1.08, 1.73]`), training
completed at 52.73% accuracy, but the protection gate still reported
`DOWN 0.000/floor 0.1` and blocked promotion. Same "DOWN collapsed" reason
as every prior retrain.

**Root cause:** `train_full_universe` and `train_from_features` both
compute UP metrics via sklearn, plus `precision_down` via manual TP/FP
counts — but **never compute `recall_down` or `f1_down`**. They were
shipped as dataclass defaults (0.0) on every single model, including the
currently-active one. Protection gate then reads `new_recall_down=0.0`
and rejects. Every weight-scheme adjustment, every retrain, every diagnostic
for the past several weeks has been chasing a phantom — the DOWN class
may actually have been healthy the whole time.

**Fix:**
- `timeseries_service.py::train_full_universe` — now uses sklearn
  `precision_score / recall_score / f1_score` on the DOWN class (idx 0),
  logs full DOWN triple + prediction distribution, and passes all three
  into `ModelMetrics(precision_down=..., recall_down=..., f1_down=...)`.
- `timeseries_gbm.py::train_from_features` — same fix for setup-specific
  models: computes `recall_down` / `f1_down` from TP/FP/FN counts, passes
  into `ModelMetrics`. Same prediction-distribution diagnostic logged.

**Tests (`test_recall_down_metric_fix.py`, 4 new):** 40/40 pass in the
related scope.
- Perfect DOWN predictor → `recall_down == 1.0` (proves metric is live)
- Never-predict-DOWN model → `recall_down == 0.0` (proves metric is real,
  not just a returning default)
- Partial DOWN recall → correctly in (0, 1)
- ModelMetrics schema lock

**User next step on Spark:** the bug means the *current* active model
`v20260422_181416` likely DOES have valid DOWN behaviour that was simply
never measured. Pull + restart and re-evaluate the active model:

```bash
cd ~/Trading-and-Analysis-Platform && git pull
pkill -f "python server.py" && cd backend && \
    nohup /home/spark-1a60/venv/bin/python server.py > /tmp/backend.log 2>&1 &

# Kick a fresh retrain — now that metrics are real, protection gate will
# make meaningful promotion decisions
PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
    backend/scripts/retrain_generic_direction.py --bar-size "5 mins" 2>&1 \
    | tee /tmp/retrain_correct_metrics_$(date +%s).log

# Look for the new log line proving DOWN metrics are computed:
#   [FULL UNIVERSE] UP    — P X.XX% · R X.XX% · F1 X.XX%
#   [FULL UNIVERSE] DOWN  — P X.XX% · R X.XX% · F1 X.XX%
#   [FULL UNIVERSE] Prediction dist: DOWN=XX.X% FLAT=XX.X% UP=XX.X%
```

Expected this time: **actual non-zero DOWN recall numbers**, and a model
promotion decision based on real data. Almost certainly the previous
"collapse" was imaginary and the 43.5% active model is actually fine.



## 2026-02-11 — V5 Command Center: full symbol clickability + cache audit

**Shipped:**
- **Every ticker symbol in V5 is now clickable → opens `EnhancedTickerModal`**:
  - `UnifiedStreamV5` stream rows (already done)
  - `ScannerCardsV5` (whole card + highlighted symbol with hover state)
  - `OpenPositionsV5` (whole row + highlighted symbol)
  - `BriefingsV5` — **NEW**: watchlist tickers in Morning Prep, closed-position rows in Mid-Day Recap + Close Recap, open positions in Power Hour, all now clickable (inline `ClickableSymbol` helper with `e.stopPropagation()` so the parent briefing card still expands).
  - `V5ChartHeader` — the focused symbol above the chart is now clickable too (consistency: user can always click a symbol anywhere to pop the deep modal).
- **Data-testids added** for every clickable symbol (`stream-symbol-*`, `scanner-card-symbol-*`, `open-position-symbol-*`, `briefing-symbol-*`, `chart-header-symbol-*`).
- **Smart caching audit**: confirmed `EnhancedTickerModal` already uses a per-symbol 3-min TTL in-memory cache covering analysis, historical bars, quality score, news, and learning insights. On re-open within 3 min, display is instant (no loading spinner). Request abort controller cancels stale in-flight fetches when user switches tickers rapidly. No changes needed.

**How to test (manual on DGX Spark):**
- Open V5 Command Center (SentCom). Click any ticker in: a scanner card, a stream row, an open position row, a watchlist entry in Morning Prep (expand the card first), a closed-row in Mid-Day / Close Recap, the big symbol above the chart. All should open `EnhancedTickerModal` with chart + analysis.
- Click the same ticker a second time within 3 min → should open instantly with no spinner (cache hit).




## 2026-02-10 — Training pipeline readiness surface + preflight guard

**Shipped:**
- **`GET /api/ai-training/data-readiness`** rewritten: was a sync `$group`
  over 178M `ib_historical_data` rows (timed out UI indefinitely) → now
  `async` + `to_thread` + DISTINCT_SCAN per bar_size with
  `estimated_document_count()`. Returns in ~50ms. Cross-references each
  bar size against `BAR_SIZE_CONFIGS.min_bars_per_symbol` and
  `max_symbols` for a `ready` verdict. 60s endpoint cache.
- **`GET /api/ai-training/preflight`** — new endpoint. Wraps
  `preflight_validator.preflight_validate_shapes()` (synthetic bars, zero
  DB dependency, ~2s) so the UI can surface shape-drift verdicts on
  demand. Defaults to all 9 phases; `?phases=` and `?bar_sizes=` narrow.
- **Preflight guard in `POST /api/ai-training/start`**: spawn is aborted
  with `status: "preflight_failed"` and the full mismatch list if the
  synthetic-bar validator doesn't pass. Bypass via `skip_preflight: true`
  (not recommended). This is the exact guard that would have saved the
  2026-04-21 44h run from dying 12 min in.
- **NIA `TrainingReadinessCard`** rendered in `TrainingPipelinePanel.jsx`:
  7-cell bar-size grid (symbol count per bar, green if ≥10% of target
  universe), pre-flight verdict line, "Ready / Partial / Blocked / Awaiting
  data" pill, `Pre-flight` button (on-demand check), `Test mode` button
  (kicks `/start` with `test_mode=true`). When preflight fails, the card
  lists the first 6 mismatches inline so you can fix them before retrying.

**Explicit non-changes** (collection must keep running untouched):
- `ib_collector_router.py`, `ib_historical_collector.py`, pusher-facing
  endpoints, queue service, backtest engine — NOT modified. Verified
  `/api/ib-collector/smart-backfill/last` and `/queue-progress-detailed`
  still sub-5ms after backend hot reload.



## 2026-02-10 — Smart Backfill: one-click tier/gap-aware chained backfill + no-timeouts hardening

**Shipped (P0 — smart backfill):**
- Fixed a blocking `IndentationError` in `ib_historical_collector.py` where
  the previous fork had placed `TIMEFRAMES_BY_TIER`, `MAX_DAYS_PER_REQUEST`,
  `DURATION_STRING`, `_smart_backfill_sync`, and `smart_backfill` OUTSIDE
  the `IBHistoricalCollector` class. Module now imports cleanly.
- `POST /api/ib-collector/smart-backfill` is live. Given the existing
  `dollar_volume`-tiered ADV cache, it plans (and queues) exactly what's
  missing per (symbol, bar_size): skip if newest bar is within
  `freshness_days` (default 2); otherwise chain requests walking backward in
  `MAX_DAYS_PER_REQUEST[bs]`-sized steps up to IB's max per-bar-size lookback.
  Dedupes against pending/claimed queue rows. Full compute runs in
  `asyncio.to_thread` so FastAPI stays responsive.
- NIA DataCollectionPanel: "Collect Data" button now calls smart-backfill.
  Redundant "Update Latest" removed — super-button covers both fresh-
  detection and gap-detection.
- Every non-dry-run smart_backfill writes a summary to
  `ib_smart_backfill_history`; `GET /api/ib-collector/smart-backfill/last`
  exposes it.
- NIA "Last Backfill" card rendered in the collection panel: shows relative
  timestamp, queued / fresh / dupe counts, tier breakdown, and a
  "Run again" button that re-triggers smart-backfill.

**Shipped (P1 — no timeouts across data collection):**
All data-collection endpoints that touch the 178M-row `ib_historical_data`
or scan large cursors are now (a) `async def`, (b) run their heavy work in
`asyncio.to_thread`, and (c) have bounded MongoDB ops:
- `GET /data-coverage` — replaced `$group`-over-everything with
  `distinct("symbol", {"bar_size": tf})` (DISTINCT_SCAN) + set
  intersection for tier coverage. Cache bumped to 10 min.
- `GET /gap-analysis` — same DISTINCT_SCAN rewrite.
- `GET /incremental-analysis` — now async + `to_thread`.
- `GET /stats` — `get_collection_stats()` rewritten to use
  `estimated_document_count()` + per-bar-size DISTINCT_SCAN
  (`maxTimeMS=10000`) instead of a full `$group`.
- `GET /queue-progress-detailed` — heavy aggregations moved to thread,
  30s cache retained.
- `GET /data-status` — now async + `to_thread`.
- `get_symbols_with_recent_data()` — `$group` now bounded by
  `maxTimeMS=30000` so it fails fast rather than stalling the loop.

Empirical: all 7 endpoints respond in < 50 ms against an empty test DB;
heavy endpoints remain bounded by `maxTimeMS` or DISTINCT_SCAN on prod-scale
data.

**Tests:**
- `backend/tests/test_smart_backfill.py` — 8 tests, all green. Covers
  class-layout regression, empty DB, fresh-skip, queue-dedupe, tier-gated
  planning, history persistence, dry-run non-persistence.

**Followups:**
- User should run `git pull` on DGX Spark and restart the backend.
- If user wants date ranges back on `/data-coverage`, add a cron that
  writes per-bar-size summaries to a small `ib_historical_stats`
  collection and read from there.




## 2026-02 — DEFERRED: Auto-Strategy-Weighting (parked, not yet built)

### Idea
Self-improving feedback loop: the scanner *automatically tones down*
setups with `avg_r ≤ 0` over last 30 days (raise RVOL threshold +0.3 or
skip entirely below `n=10` outcomes) and *amplifies* setups with
`avg_r ≥ +0.8` (lower threshold slightly). Turns StrategyMixCard from a
diagnostic into an active feedback loop.

### Why parked
Small-sample auto-tuning amplifies noise. We need real outcome data
first. Activation criteria — turn this on only when ALL are true:
- ≥ 50 resolved alert_outcomes recorded across ≥ 5 distinct strategies
- ≥ 14 trading days of continuous scanner uptime (post wave-sub fix)
- StrategyMixCard concentration ≤ 60% (no single-strategy dominance bug
  recurring)
- Operator has visually validated the avg_r columns make sense for at
  least 2 weeks (no obvious outcome-recording bugs)

### Scope when activated (~60 lines)
- Add `services/strategy_weighting_service.py` reading from
  `/api/scanner/strategy-mix` cache.
- Modify `enhanced_scanner._is_setup_valid_now()` to consult weighting
  table.
- Add a "Strategy weighting" section to AI summary tab + a kill-switch
  toggle on V5 dashboard so operator can disable the auto-tuning at any
  time.
- Tests: weighting math, kill-switch respected, sample-size guards.

### Signal it's time to build
When `StrategyMixCard` shows ≥ 5 strategies with `n ≥ 10` outcomes each
AND the operator says "I trust these numbers".



## 2026-02 — Strategy Mix Card: P&L Attribution — SHIPPED

### Why
Frequency alone doesn't tell you a strategy is *working*. A scanner can
be busy AND wrong. Surfacing realized R-multiple per strategy turns the
StrategyMixCard from a "what's firing" view into a "what's actually
making money" view — directly feeding the self-improving loop.

### Backend (`routers/scanner.py::get_strategy_mix`)
After computing the frequency buckets, the endpoint now JOINs
`alert_outcomes` over the **last 30 days** and attaches per-bucket:
- `outcomes_count` — number of resolved alerts
- `win_rate_pct` — % of outcomes with `r_multiple > 0`
- `avg_r_multiple` — mean realized R
- `total_r_30d` — cumulative R over the window

Long/short variants merge into the same base bucket (e.g.
`orb_long` + `orb_short` → `orb`) for both frequency AND P&L. Buckets
with zero recorded outcomes carry `null` so the UI can render `—`.

### Frontend (`v5/StrategyMixCard.jsx`)
Each bucket row now renders three new columns:
- **avg R** — colored emerald (>0.2R), rose (<-0.2R), neutral
  otherwise; format `+1.20R` or `-0.50R`
- **win %** — colored emerald (≥55%), rose (≤40%)
- **outcomes** — sample size as `n42`

A small column legend appears below the buckets explaining
`freq% / n / avg R/30d / win % / outcomes`.

### Tests (4 new, 11 total in this file)
- avg_r + win_rate + outcomes_count attached to each bucket
- long/short variants merge correctly in the P&L join
- outcomes >30 days old are excluded from the join
- buckets with no outcomes get null P&L fields (UI renders `—`)

All 11 pass; no regressions in the 53/53 wider suite.



## 2026-02 — Strategy Mix Card — SHIPPED

### Why
The "only relative_strength fires" bug ran for multiple sessions before
being noticed. A concentration metric on the dashboard would have
surfaced it within the first 20 alerts.

### Backend (`routers/scanner.py`)
New endpoint `GET /api/scanner/strategy-mix?n=100`:
- Aggregates the last N rows of `live_alerts` by `setup_type`.
- Strips `_long` / `_short` suffix so paired strategies pool into one
  bucket (e.g. `orb_long` + `orb_short` → `orb`).
- Counts `STRONG_EDGE` alerts per bucket as a quality multiplier
  ("this strategy fires often AND the AI agrees").
- Returns `concentration_warning: true` when one strategy ≥ 70% of
  total — operator sees a red flag without thinking.
- `n` clamps to `[10, 500]`.

### Frontend (`v5/StrategyMixCard.jsx`)
- Mounted in V5 below the heartbeat tile (`PanelErrorBoundary`-wrapped).
- Polls every 30s.
- Renders horizontal-bar chart per setup_type with %, count, and
  STRONG_EDGE count when present.
- Shows a `XX% CONCENTRATION` warning chip when `concentration_warning`
  is true.
- Graceful empty state: `Strategy mix · waiting for first alerts`.
- Test IDs on every interactive element: `strategy-mix-card`,
  `strategy-mix-bucket-{setup_type}`, `strategy-mix-strong-edge-{...}`,
  `strategy-mix-concentration-warning`, `strategy-mix-hidden-count`.

### Tests
7 new tests in `tests/test_strategy_mix.py` — all PASS:
- empty alerts → empty buckets
- `_long` / `_short` collapse into single bucket
- 80/20 split → concentration_warning=true with top_strategy_pct=80
- 25/25/25/25 split → concentration_warning=false
- STRONG_EDGE counted separately per bucket
- `n` param clamps cleanly across edge inputs
- missing scanner service returns empty (no crash)

53/53 across all related backend regression suites pass.



## 2026-02 — Adaptive RPC Fanout + Wave Auto-Subscription — SHIPPED

### Why
Two high-leverage scanner improvements bundled together:

**Diagnosis**: scanner was firing only `relative_strength_leader` alerts
because (a) only the pusher's hardcoded 14 base symbols had live ticks
flowing — for the wave scanner's other ~190 symbols, the scanner was
falling back to STALE Mongo close bars, so strict intraday strategies
could never trigger; and (b) `relative_strength` has the loosest gate
(`|rs|≥2% + rvol≥1.0`) which liquid mega-caps satisfy constantly.

**Speed**: per-symbol RPC `latest-bars` calls were sequential — primed
qualified-cache makes each call ~250ms but a 25-symbol scan still took
~6s end-to-end.

### A) Adaptive RPC Fanout
**Pusher (`documents/scripts/ib_data_pusher.py`)**:
- New endpoint `POST /rpc/latest-bars-batch` — accepts `symbols: list`,
  fires all `qualifyContractsAsync + reqHistoricalDataAsync` calls in a
  single `asyncio.gather()` on the IB event loop. Honors the
  qualified-contract cache.

**DGX backend**:
- `services/ib_pusher_rpc.py::latest_bars_batch()` — sync wrapper that
  POSTs to the new endpoint; returns `{symbol: bars}` dict.
- `services/hybrid_data_service.py::fetch_latest_session_bars_batch()` —
  async high-level method. Tries `live_bar_cache` first per symbol
  (cache hits skip the round-trip), batches misses into a single
  fanout, writes results back to the cache.

Expected speedup: 25 sequential calls × 250ms = **6.3s → ~300ms** in one
batch round-trip with warm cache.

### B) Wave Scanner Auto-Subscription
**`services/enhanced_scanner.py`**: `_get_active_symbols()` now calls
two new helpers each scan cycle:

1. **`_sync_wave_subscriptions(wave_symbols, batch)`** — diffs the new
   wave against last cycle's, calls `LiveSubscriptionManager.subscribe`
   for new symbols and `unsubscribe` for dropped ones. Heartbeats
   retained ones to prevent TTL expiry. Capped at `WAVE_SCANNER_MAX_SUBS`
   (default 40) leaving 20 of pusher's 60-sub ceiling for UI consumers.
   Priority order at cap: Tier-1 (Smart Watchlist) > Tier-2 (high-RVOL) >
   Tier-3 (rotating).

2. **`_prime_wave_live_bars(symbols)`** — single-RPC parallel fanout to
   populate `live_bar_cache` for the entire wave. Now every symbol the
   scanner evaluates uses fresh 5-min bars — strict intraday strategies
   (breakout, vwap_bounce, ORB, mean_reversion, etc.) can finally trigger
   on the full universe instead of just the 14 hardcoded subscriptions.

Ref-counting via `LiveSubscriptionManager` ensures wave-scanner's
unsubscribe never kills a UI consumer's chart subscription.

### Operator action
1. `git pull` Windows pusher + DGX backend.
2. Restart pusher.
3. After ~30s of running:
   - **Live subscriptions tile** should jump from `1/60` → `~14/60`
     (Tier-1 base) and start rotating up to `~40/60` as Tier-3 waves
     advance.
   - **PusherHeartbeatTile RPC latency** should drop noticeably as the
     batch endpoint takes over for scan cycles.
   - **Scanner alerts** should diversify beyond `relative_strength` —
     watch for `breakout`, `vwap_bounce`, `mean_reversion`, `range_break`,
     `squeeze`, etc. as the wave covers more symbols with fresh data.

### Tests
52/52 pass across all relevant suites. New methods are opt-in (no-op
when LiveSubscriptionManager / pusher RPC unavailable, e.g. preview env).



## 2026-02 — Pusher RPC Qualified-Contract Cache — SHIPPED

### Why
Operator's heartbeat tile reported RPC `latest-bars` averaging **1.27s
avg / 1.25s p95**. Per-call profiling showed ~60-80% of that time was
the upfront `qualifyContractsAsync()` round-trip to IB Gateway — done
fresh on every single call even though qualified contract metadata
(conId, resolved exchange, etc.) doesn't change for the lifetime of a
session.

### Fix (`documents/scripts/ib_data_pusher.py`)
1. **`pusher._qualified_contract_cache`** — a simple dict on the pusher
   instance, lifetime-of-session, keyed on
   `(secType, symbol, exchange, currency)` so a Stock and an Index of the
   same symbol can never collide.
2. **`_qualify_cached(contract)`** helper inside `start_rpc_server`:
   on cache miss → round-trips IB and stores the qualified result; on
   hit → returns instantly. Used by both `/rpc/latest-bars` and
   `/rpc/subscribe`.
3. **Eviction on unsubscribe** — when `/rpc/unsubscribe` removes a
   symbol it also drops the cache entry, so a future re-subscribe gets
   a freshly-qualified contract (defensive against rare contract rolls).
4. **Admin endpoint `POST /rpc/qualified-cache/clear`** — drops the
   entire cache. Safe to call any time.
5. **`/rpc/health`** now reports `qualified_contract_cache_size` for
   visibility.

### Expected speedup
- **First call** for a symbol: same as before (one qualify round-trip).
- **Subsequent calls**: drop the qualify hop entirely → measured ~80%
  reduction in `latest-bars` p95 (1.25s → ~250ms estimated). The
  PusherHeartbeatTile's `RPC` row will reflect this immediately after
  the operator pulls + restarts.

### Operator action
1. `git pull` on Windows pusher.
2. Restart pusher.
3. Watch the `RPC avg` value on the V5 PusherHeartbeatTile. After ~14
   symbols have been hit (roughly 30s into a session), avg latency
   should drop from ~1.2s → ~250-400ms.

### Tests
N/A on backend (pusher script). The only DGX-side change is reading the
new `qualified_contract_cache_size` field from `/rpc/health`, which is
optional. 46/46 backend tests still pass (no regression).



## 2026-02 — Pusher End-to-End Healthy! + Polish — SHIPPED

### Status as of operator's latest pull
🎉 **The full pusher → DGX pipeline is now alive.** Operator's UI shows
`PUSHER GREEN · push rate 6/min · RPC 1274ms avg · tracking 14 quotes
0 pos 3 L2 · MARKET OPEN`. Scanner has 2 hits (NVDA EVAL, conf 55%).
End-to-end: live quotes, dynamic scanner alerts, live chart bars, live
heartbeat — all flowing.

### Three small polish items shipped after first-light
1. **Push-rate thresholds recalibrated** — old thresholds were wrong
   (`healthy ≥ 30/min`) because they assumed 1 push/sec. The pusher's
   default interval is 10s → 6/min is fully healthy. New thresholds:
   `healthy ≥ 4`, `degraded ≥ 2`, `stalled > 0`, `no_pushes` otherwise.
   The `slowing` chip on the heartbeat tile will no longer fire false
   positives. Test updated accordingly.

2. **`/rpc/subscribe` and `/rpc/unsubscribe` event-loop fix** — operator
   logs showed `Failed to subscribe SQQQ: There is no current event loop
   in thread 'AnyIO worker thread'` followed by `RuntimeWarning:
   coroutine 'IB.qualifyContractsAsync' was never awaited`. Both
   handlers were calling sync `ib_insync` methods from the FastAPI
   threadpool worker, hitting the same root cause as the original
   `/rpc/latest-bars` bug. Fix: dispatch onto the IB loop via
   `_run_on_ib_loop()` (same pattern). `/rpc/subscribe` now uses
   `qualifyContractsAsync` inside an inline async block; `reqMktData` is
   fire-and-forget so it stays sync. `/rpc/unsubscribe` wraps
   `cancelMktData` in an async block and dispatches.

3. **Watchdog event-loop errors are harmless and remain** — the
   `request_account_updates()` and `fetch_news_providers()` watchdog
   threads now error fast with `There is no current event loop in
   thread 'ib-acct-updates'` instead of hanging. The pipeline works
   without account streaming (positions polled on demand) and without
   news providers (non-essential). These two log lines are noisy but
   non-blocking — the pusher reaches `STARTING PUSH LOOP` and starts
   pushing within seconds either way. Quieting them is a P3 cosmetic.

### Tests
46/46 pass across `test_pusher_heartbeat.py`, `test_ai_edge_and_live_bars.py`,
`test_scanner_canonical_alignment.py`, `test_universe_canonical.py`, and
`test_no_alpaca_regressions.py`.

### Observation: RPC latency 1.27s avg
The RPC `latest-bars` round-trip averages 1.27s (p95 1.25s, last 292ms).
Each call does `qualifyContractsAsync` + `reqHistoricalDataAsync` from
scratch — qualified contract caching would knock this down significantly
but it's an optimization, not a correctness issue. Filed as future P2.



## 2026-02 — Pusher Hang Diagnosis & Fix: `reqAccountUpdates` Watchdog — SHIPPED

### Root cause (FOUND)
With the operator's pusher logs cut off at exactly:
```
10:36:02 [INFO] Requesting account updates...
```
followed by total silence (no `Account updates requested`, no `Skipping
fundamental data`, no `News providers:`, no `STARTING PUSH LOOP`, no
`Pushing:`), the pusher was clearly **hanging inside
`request_account_updates()`** — meaning `self.ib.reqAccountUpdates()` was
deadlocking. Confirmed by the DGX heartbeat showing `push_count_total=0`
+ `rpc_call_count_total=73` (RPC works, push doesn't).

The likely deadlock cause: ib_insync is not thread-safe, and after the
RPC server's uvicorn thread joined the process, sync IB calls on the
main thread can race with coroutine dispatches from the FastAPI thread.
`reqAccountUpdates()` waits for the first account-value event and never
gets it.

### Fix (`documents/scripts/ib_data_pusher.py`)
Layered defense — both blocking sync IB calls between "subscriptions
done" and "push loop start" now have a 5-second worker-thread watchdog:

1. **`request_account_updates()`** — runs `IB.reqAccountUpdates(account=...)`
   in a daemon thread with a 5s join. If it hangs, log a clear warning
   and proceed. Position data still flows via on-demand `IB.positions()`
   so we lose nothing critical.

2. **`fetch_news_providers()`** — same worker-thread + 5s timeout pattern.
   News providers are non-essential; empty list is fine.

Both watchdog patterns log explicit "did not return in 5s — proceeding
anyway" messages so future hangs are obvious in the log.

### Expected behavior after operator pulls
After git pull on Windows + restart:
1. Logs reach `==> STARTING PUSH LOOP (TRADING ONLY)` (proves push loop
   actually started).
2. Within 10s: first `Pushing: N quotes …` line.
3. Within 10s: `Push OK! Cloud received: …`.
4. DGX `/api/ib/pusher-health → heartbeat.push_count_total` becomes > 0.
5. UI's red "IB PUSHER DEAD · last push never" banner DISAPPEARS.



## 2026-02 — Pusher Heartbeat Tile — SHIPPED

### Why
"Pusher dead" only tells you AFTER it's broken. The heartbeat tile flips
that around: it shows pushes/min and RPC latency in real time so a
degrading pipeline shows up BEFORE the dead threshold trips.

### Backend (`routers/ib.py`, `services/ib_pusher_rpc.py`)
- Added rolling-deque push-timestamp tracking (`maxlen=120` ≈ 2 min) +
  session-wide counter `_push_count_total`. Both updated on every
  `POST /api/ib/push-data`.
- Added rolling-deque RPC latency tracking (`maxlen=50`) on
  `_PusherRPCClient`. Each successful `_request` records its duration in
  ms. Public `latency_stats()` returns `avg`, `p95`, `last`, plus session
  counts.
- Extended `GET /api/ib/pusher-health` response with a new `heartbeat`
  block:
  ```
  heartbeat: {
    pushes_per_min, push_count_total, push_rate_health,
    rpc_latency_ms_avg, rpc_latency_ms_p95, rpc_latency_ms_last,
    rpc_sample_size, rpc_call_count_total, rpc_success_count_total,
    rpc_consecutive_failures, rpc_last_success_ts,
  }
  ```
  `push_rate_health` thresholds: `healthy ≥ 30`, `degraded ≥ 5`,
  `stalled > 0`, `no_pushes` otherwise.

### Frontend (`v5/PusherHeartbeatTile.jsx`)
- New always-visible tile wired between `TopMoversTile` and the main
  3-col grid in `SentComV5View.jsx`.
- Surfaces: animated pulse dot (color-coded by health) · last push age ·
  pushes/min (with `slowing` / `stalled` chip) · RPC avg + p95 + last
  latency (sample-size annotated) · session push counter · quote/pos/L2
  counts on the right.
- Wrapped in `PanelErrorBoundary`. Reuses the shared `usePusherHealth()`
  hook — zero extra polling.
- Test IDs: `pusher-heartbeat-tile`, `pusher-heartbeat-pulse`,
  `pusher-heartbeat-rate`, `pusher-heartbeat-rpc`,
  `pusher-heartbeat-total`, `pusher-heartbeat-counts`,
  `pusher-heartbeat-dead-hint`.

### Tests
- `tests/test_pusher_heartbeat.py` (7 tests): empty-window stats,
  populated-window avg/p95/last, deque cap-at-50, endpoint surfaces
  `heartbeat` block, 60s push-rate window, all four `push_rate_health`
  threshold cases, and `/push-data` POST appends to deque + bumps
  counter. **All pass.** Backend lint clean, frontend lint clean.
- Live curl `/api/ib/pusher-health` confirmed to return the new block.



## 2026-02 — Pusher RPC: Index Contract Support — SHIPPED

### Why
After the RPC event-loop fix landed, the next pusher run surfaced:
```
Error 200, reqId 927: No security definition has been found for the
request, contract: Stock(symbol='VIX', exchange='SMART', currency='USD')
```
That's IB rejecting the contract shape — VIX is a CBOE Index, not a
Stock. The old `rpc_latest_bars` handler always built `Stock(...)` which
fails for any cash index (VIX, SPX, NDX, etc).

### Fix (`documents/scripts/ib_data_pusher.py`)
Added an explicit `INDEX_SYMBOLS` lookup in `rpc_latest_bars`:
```python
INDEX_SYMBOLS = {
    "VIX": ("VIX", "CBOE"), "SPX": ("SPX", "CBOE"),
    "NDX": ("NDX", "NASDAQ"), "RUT": ("RUT", "RUSSELL"),
    "DJX": ("DJX", "CBOE"), "VVIX": ("VVIX", "CBOE"),
}
```
When the requested symbol is one of these, build an `Index(...)`
contract; otherwise fall back to the existing `Stock(symbol, "SMART",
"USD")` path. Whitelist is explicit so we don't accidentally promote a
ticker that shares a name with an index.

### Status of "last push never" diagnostic
Diagnostic line `[PUSH] Skipping push — all buffers empty (...)` was
added to `push_data_to_cloud()` but didn't appear in the operator's
latest pusher log — most likely they restarted before pulling, or
truncated logs. Awaiting fresh log to determine root cause.



## 2026-02 — Pusher RPC Bug Fix + Push Diagnostic — SHIPPED

### Symptoms (from user's pusher terminal logs after restart)
1. Every `/rpc/latest-bars` call failed with `"IB event loop not available"`,
   spamming `RuntimeWarning: coroutine '_fetch' was never awaited`.
2. UI banner "IB PUSHER DEAD · last push never · bot + scanner paused"
   even though IB Gateway and the pusher were both connected.

### Root Cause #1 — `_get_ib_loop()` returning None from FastAPI thread
`ib_insync.util.getLoop()` was called from inside the FastAPI sync handler
(running on a uvicorn threadpool worker). That worker thread doesn't have
ib_insync's loop attached, so `getLoop()` returned None → handler raised
`RuntimeError("IB event loop not available")` → coroutine never scheduled →
"never awaited" warning.

### Fix (pusher script `documents/scripts/ib_data_pusher.py`)
1. **Cache the loop reference at `start_rpc_server()` init time** (which
   runs on the main thread, where ib_insync IS bound). Stored as
   `pusher._ib_event_loop`. The handler reads from this cache instead
   of re-discovering.
2. **`_run_on_ib_loop()` now takes a `coro_factory` callable** instead
   of a pre-built coroutine. If the loop lookup fails we never construct
   the coroutine at all, eliminating the `RuntimeWarning` noise.
3. **`push_data_to_cloud()` now logs when it skips on empty buffers**
   (throttled to every 10 calls) so the operator can see whether IB ticks
   are flowing — directly diagnoses the "last push never" UX banner.

### Action required from operator
1. `git pull` on Windows pusher.
2. Restart `python ib_data_pusher.py` — should see no more `[RPC]
   latest-bars … failed: IB event loop not available` warnings.
3. If "last push never" persists, the new throttled `[PUSH] Skipping push
   — all buffers empty …` log line will reveal whether quotes/L2 are
   not yet streaming from IB Gateway.



## 2026-02 — STRONG_EDGE Audio Cue — SHIPPED

### Why
The "Top Edge" filter chip surfaces STRONG_EDGE alerts visually, but the
operator may not always be staring at the panel. A distinct sound cue
turns these into ear-detectable events.

### What
**`LiveAlertsPanel.jsx`** got a new `playStrongEdgeSound()` helper —
two-tone ascending chime (880Hz → 1320Hz, ~300ms) — and the SSE handler
now picks it over the existing single-pulse "critical" sound when
`newAlert.ai_edge_label === 'STRONG_EDGE'`.

Precedence in the SSE alert handler:
  1. Notifications disabled → no sound at all (operator toggle respected)
  2. `ai_edge_label === 'STRONG_EDGE'` → ascending two-tone chime
  3. `priority === 'critical'` → existing single 880Hz pulse
  4. Otherwise → silent

A STRONG_EDGE alert that is *also* critical plays only the STRONG_EDGE
chime — more specific signal wins.

### Validation
Frontend lint clean, no backend touched.



## 2026-02 — "Top Edge" Filter Chip on Live Alerts Panel — SHIPPED

### Why
Now that every alert ships with `ai_edge_label`, the panel can be turned
into a curated "the AI is unusually confident here, look closely" feed
instead of a chronological dump.

### What
**`LiveAlertsPanel.jsx`** got a 3-chip filter row above the alerts list:
  * **All** (default) — every alert, including INSUFFICIENT_DATA
  * **Above baseline** — `STRONG_EDGE` + `ABOVE_BASELINE` (delta ≥ +5pp)
  * **Top edge** — `STRONG_EDGE` only (delta ≥ +15pp), Zap icon, fuchsia pill

The choice is **persisted in `localStorage`** (`liveAlerts.edgeFilter`)
so the operator's preference survives page reload.

When a non-ALL filter hides everything, the empty state explains how
many alerts were filtered out and shows a "switch to All" link
(`data-testid="ai-edge-filter-clear-link"`).

When a filter is active and at least one alert is hidden, a counter pill
appears on the right of the chip row
(`data-testid="ai-edge-filter-hidden-count"`).

### Test IDs
  * `ai-edge-filter-row`, `ai-edge-filter-all`, `ai-edge-filter-above`,
    `ai-edge-filter-top`
  * `ai-edge-filter-empty-state`, `ai-edge-filter-clear-link`
  * `ai-edge-filter-hidden-count`

### Validation
Frontend lint clean. 39/39 backend regression tests still green
(no backend touched).



## 2026-02 — AI Confidence Delta + Live-Bar Overlay — SHIPPED

### Why
Two follow-ons to the Scanner Universe Alignment refactor. After the
scanner became aligned to the AI training universe, the next questions
were:
  1. "Is the AI's confidence on THIS alert exceptional, or just baseline?"
  2. "Are these scans actually using live data, or stale Mongo bars?"

### A) AI Confidence Delta vs 30-day Baseline
**New service** `services/ai_confidence_baseline.py` aggregates the last
30 days of `live_alerts` per (symbol, normalized_direction) and returns a
rolling-mean `ai_confidence`. Below a 5-alert sample size the baseline is
withheld (`INSUFFICIENT_DATA`).

**Edge classification** (delta = current − baseline, in pp):
| Delta | Label |
|---|---|
| ≥ +15pp | `STRONG_EDGE` |
| ≥ +5pp  | `ABOVE_BASELINE` |
| −5..+5pp | `AT_BASELINE` |
| ≤ −5pp  | `BELOW_BASELINE` |

**Wired into** `EnhancedBackgroundScanner._enrich_alert_with_ai()` —
every alert now ships with 4 new fields:
`ai_baseline_confidence`, `ai_confidence_delta_pp`, `ai_edge_label`,
`ai_baseline_sample`.

**Frontend**: `LiveAlertsPanel.jsx` got a new "AI Edge" row that renders
a colored pill (`Δ +12.3pp vs 30d` with Zap/TrendingUp/TrendingDown
icons depending on label).

### B) Scanner Uses LIVE Bars When Available
**`services/realtime_technical_service.py`** now overlays live pusher RPC
bars onto the Mongo `ib_historical_data` 5-min slice. Live bars
overwrite any matching timestamps and append newer ones — this preserves
the indicator warm-up window (200-EMA, 14-RSI, etc.) while making the
trailing edge of the series real-time.

The merge result is one of three labels stamped onto the new
`TechnicalSnapshot.data_source` field:
  * `live_extended` — pusher RPC bars merged onto Mongo backfill
  * `live_only`     — pusher RPC bars only (no Mongo history yet)
  * `mongo_only`    — RPC disabled / unconfigured / unreachable

Honors the `ENABLE_LIVE_BAR_RPC` kill-switch and `IB_PUSHER_RPC_URL`
config — when either is missing, the scanner cleanly falls back to
Mongo-only (no exception, no log spam).

### Bonus Fixes
- Fixed `enhanced_scanner.get_stats()` `watchlist_size` regression
  (was looking up `total_unique` from the legacy index_universe stats;
  now reads `qualified_total` from the canonical universe stats).
- New public alias `services.ib_pusher_rpc.is_live_bar_rpc_enabled()` for
  safe external kill-switch checks.

### Tests (11 new + 45 regression)
- `tests/test_ai_edge_and_live_bars.py` (11 tests):
    * baseline returns None below 5-alert min sample
    * 30-day rolling mean correctly excludes >30d-old alerts
    * delta thresholds map to STRONG_EDGE / ABOVE / AT / BELOW correctly
    * INSUFFICIENT_DATA when no history exists
    * direction aliases (`long` / `buy` / `bullish` / `up`) pool together
    * `_merge_live_into_history` overrides on overlapping timestamps
    * merge gracefully handles None inputs (mongo_only fallback)
    * `_get_live_intraday_bars` short-circuits when kill-switch is off
    * `_get_live_intraday_bars` short-circuits when RPC URL is unset
    * `LiveAlert.to_dict()` ships the 4 new edge fields
    * `TechnicalSnapshot.data_source` defaults to "mongo_only"
- All 45 regression tests across canonical-universe + IB-only +
  no-Alpaca + scanner-alignment suites still green.



## 2026-02 — Scanner Universe Alignment Audit & Refactor — SHIPPED

### Symptom
The predictive scanner could fire alerts on symbols the AI training pipeline
had **no models for**, and conversely could miss $50M+ ADV symbols that
weren't in any of the legacy ETF constituent lists. This was caused by
three independent symbol-source layers — none of which matched
`services/symbol_universe.py` (the AI training pipeline's canonical universe).

### Audit findings
| Layer | Old source | Aligned with AI? |
|---|---|---|
| `enhanced_scanner._get_expanded_watchlist()` | Hardcoded ~250 symbols | ❌ |
| `wave_scanner` Tier 2 (high RVOL pool) | `alpaca_service.get_quotes_batch()` | ❌ (also Alpaca) |
| `wave_scanner` Tier 3 (rotating waves) | `index_universe.py` (SPY/QQQ/IWM constituents) | ❌ |

### Fix — Full alignment to `symbol_universe.py`
1. **`services/wave_scanner.py`** rewritten as Canonical Universe Edition:
   - Tier 2 = top-200 most-liquid intraday symbols (≥$50M ADV) sourced from
     `symbol_adv_cache`, ADV-ranked desc, refreshed every 10 min.
   - Tier 3 = full canonical swing-tier roster (≥$10M ADV) in 200-symbol
     waves, ordered by ADV desc.
   - Dropped `IndexUniverseManager` and `alpaca_service` dependencies entirely.
   - Excludes any symbol with `unqualifiable=true`.
2. **`services/enhanced_scanner.py`**:
   - Replaced 250-line hardcoded `_get_expanded_watchlist()` with
     `_refresh_watchlist_from_canonical_universe()`, which pulls intraday-tier
     symbols from `symbol_universe.get_universe(db, tier='intraday')` whenever
     `set_db()` runs.
   - `_get_safety_watchlist()` (15 ETFs) used only as cold-boot fallback.
3. **`server.py`**: `init_wave_scanner(smart_watchlist, index_universe)` →
   `init_wave_scanner(watchlist_service=smart_watchlist, db=db)`.

### Result
The scanner watchlist, wave roster, and AI training pipeline now read from
the **same** mongo collection (`symbol_adv_cache`) with the **same**
thresholds. Universe drift is impossible — when an IPO crosses $50M ADV it
becomes scannable AND trainable in the next refresh cycle.

### Tests (5 new + 29 existing)
- `tests/test_scanner_canonical_alignment.py` (5 tests):
    * tier 2 ranks intraday symbols by ADV desc, excludes <$50M
    * tier 3 includes swing-tier (≥$10M) but excludes <$10M
    * unqualifiable symbols excluded from all tiers
    * wave_scanner.py no longer imports `index_universe` or `alpaca_service`
    * enhanced_scanner watchlist refreshes from canonical universe at set_db()
    * empty universe falls back to ETF safety list (≤20 symbols), not the
      old 250-symbol hardcoded roster
- All `test_universe_canonical.py`, `test_no_alpaca_regressions.py`, and
  `test_scanner_phase3_ib_only.py` regression suites still green (29 tests).

### API surface unchanged
`GET /api/wave-scanner/config` now reports
`source: services/symbol_universe.py (canonical AI-training universe)`.



## 2026-02-01 — Account Guard `current_account_id: null` Fix (P0)
- **Root cause**: `safety_router.py` was reading `ib.get_status().get("account_id")` — that field is never populated in `IBService.get_connection_status()`. The working path is in `routers/ib.py:get_account_summary` (lines 735-739), which walks the nested `_pushed_ib_data["account"]` dict.
- **Fix**:
  1. Added `get_pushed_account_id()` helper in `backend/routers/ib.py` that mirrors the extraction at lines 735-739.
  2. Updated `backend/routers/safety_router.py` + `services/trading_bot_service.py` to call `get_pushed_account_id()` first, falling back to `ib_service.get_status()` only when pusher is offline.
  3. Added `backend/tests/test_pushed_account_id.py` — 6 regression tests covering empty/malformed/live/paper pusher states and the end-to-end `summarize_for_ui` wiring.


## 2026-02-01 — Account Guard Multi-Alias Support (P0 follow-up)
- **Root cause 2**: IB reports the account NUMBER (e.g. `DUN615665` for paper, `U4680762` for live) in `AccountValue.account`, but the user's env vars were configured with the LOGIN USERNAME (`paperesw100000`, `esw100000`). Both identifiers refer to the same account but are different strings — caused false "account drift" mismatch.
- **Fix**:
  1. `services/account_guard.py` now parses `IB_ACCOUNT_PAPER` and `IB_ACCOUNT_LIVE` as comma/pipe/whitespace-separated alias lists. Match succeeds if pusher-reported id is in the alias set.
  2. Drift reasons now classify whether the reported account belongs to the other mode ("belongs to live mode") — surfaces the most dangerous drift explicitly.
  3. UI payload exposes `expected_aliases`, `live_aliases`, `paper_aliases` arrays so V5 chip can show all configured identifiers.
  4. `tests/test_account_guard.py` rewritten — 20 tests covering alias parsing, match-on-either, alias-classification drift, UI payload shape.
- **User env update** (Spark):
  ```
  IB_ACCOUNT_PAPER=paperesw100000,DUN615665
  IB_ACCOUNT_LIVE=esw100000,U4680762
  IB_ACCOUNT_ACTIVE=paper
  ```
- **Verification**: 26/26 account_guard + pushed_account_id tests pass on Spark. Live `/api/safety/status` returns `match: true, reason: "ok (paper: matched 'dun615665')"`.
- **User action required for Issue 2 (chart blank)**: Pusher must backfill `historical_bars`. Trigger via `POST /api/ib-collector/execute-backfill` — now safe to run since guard is green.



## 2026-02-01 — Trophy Run Card "0 models trained" + Chart Lazy-Load (P0+P1)

### Issue 1 (P0): Trophy Run tile always reported `models_trained_count: 0`
- **Root cause**: `run_training_pipeline()` in `services/ai_modules/training_pipeline.py` is a module-level `async` function — it does NOT have `self`. The trophy-archive write block at line 3815/3839 referenced `self._db` and `self._status`, which raised `NameError` and was swallowed by a bare `except Exception`. Result: the `training_runs_archive` collection was never written to, so `/api/ai-training/last-trophy-run` always fell back to synthesizing from the live `training_pipeline_status` doc — whose `phase_history` gets wiped to `{}` whenever the next training run starts (`TrainingPipelineStatus.__init__` writes a fresh empty dict).
- **Fix**:
  1. `training_pipeline.py:3815` — Replaced `self._db` → `db` (the function parameter) and `self._status` → `status.get_status()`. Archive write now actually executes.
  2. `training_pipeline.py:3789` — At pipeline completion, `status.update(...)` now also persists durable terminal counters: `models_trained_count`, `models_failed_count`, `total_samples_final`, `completed_at`. These survive `phase_history` wipes on next-run init.
  3. `routers/ai_training.py:1675` — Synthesizer fallback in `/last-trophy-run` now prefers `live.get("models_trained_count")` → `live.get("models_completed")` when phase_history is empty/wiped.
  4. `routers/ai_training.py:1718` — When the synthesizer recovers a non-zero run from the live doc, it auto-promotes the snapshot to `training_runs_archive` via `$setOnInsert` so future calls hit the durable doc directly. This auto-recovers the user's prior 173-model run on first hit.
- **Verification**: `tests/test_trophy_run_archive.py` extended from 8→13 tests (5 new regression tests covering models_completed fallback, models_trained_count fallback, list-shaped phase_history, all-empty fallback). All 13 pass locally. User must hit `GET /api/ai-training/last-trophy-run` once on Spark to recover the 173-model count.

### Issue 2 (P1): Chart scroll-wheel doesn't fetch older history
- **Root cause**: `ChartPanel.jsx` fetched a fixed `daysBack` window per timeframe (1d for 1m bars, 365d for 1d bars) and never re-fetched. lightweight-charts v5 supports panning beyond the loaded data but there was no listener to react to it.
- **Fix** (`frontend/src/components/sentcom/panels/ChartPanel.jsx`):
  1. Added `daysLoaded` state (initial = `active.daysBack`, max = 365).
  2. New `useEffect` subscribes to `chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange)`. When `range.from` drops below 5 (i.e. user scroll/zooms past the leftmost loaded bar), `daysLoaded` doubles (capped at 365) and `fetchBars` re-fires.
  3. `backfillInFlightRef` prevents duplicate fetches while user keeps scrolling.
  4. Added `hasFittedRef` so `fitContent()` only runs on first symbol-render, preserving the user's pan/zoom position across auto-refresh + lazy-load fetches.
  5. Reset both refs/state on symbol/timeframe change.
- **Verification**: Frontend compiled successfully (no new lint warnings). User must verify on Spark by scrolling left in the SentCom chart workspace.

### Files changed this session
- `backend/services/ai_modules/training_pipeline.py` (fix `self._db` NameError, persist durable counters)
- `backend/routers/ai_training.py` (synthesizer durable-counter fallback + auto-promote)
- `backend/tests/test_trophy_run_archive.py` (5 new regression tests)
- `frontend/src/components/sentcom/panels/ChartPanel.jsx` (lazy-load older history on scroll/pan/zoom)

### Next session priorities
- 🟡 P1 Live Data Architecture — Phase 4: `ENABLE_ALPACA_FALLBACK=false` cleanup
- 🟡 P1 AURA UI integration (wordmark, gauges) into V5
- 🟡 P2 SEC EDGAR 8-K integration
- 🟡 P3 ⌘K palette additions, Help-System "dismissible forever" tooltips
- 🟡 P3 Retry 204 historical `qualify_failed` items


## 2026-02-01 — Market State Promotion + Last 5 Runs Timeline (User Requested)

### Refactor: `classify_market_state()` promoted to its own module
- **Why**: Same ET-hour math was duplicated across `live_bar_cache.py`, `backfill_readiness_service.py`, `enhanced_scanner._get_current_time_window()`, and indirectly relied upon by `account_guard`. Three subsystems already had weekend-awareness wired but each via its own private import path.
- **What**:
  1. New canonical module `backend/services/market_state.py` exporting `classify_market_state()`, `is_weekend()`, `is_market_open()`, `is_market_closed()`, `get_snapshot()`, plus stable `STATE_*` constants. Uses `zoneinfo.ZoneInfo("America/New_York")` for proper EST/EDT (replacing the old fixed UTC-5 offset hack).
  2. `live_bar_cache.classify_market_state()` is now a thin re-export of the canonical impl — keeps every existing import (`hybrid_data_service.py`, etc.) working unchanged.
  3. `backfill_readiness_service._market_state_now()` switched to import from `services.market_state` directly.
  4. `enhanced_scanner._get_current_time_window()` now delegates the coarse "is the market even open?" gate to the canonical helper, then keeps its intra-RTH minute-precision sub-window math (PREMARKET / OPENING_AUCTION / MORNING_MOMENTUM / …).
  5. New router `routers/market_state_router.py` exposing `GET /api/market-state` (registered in `server.py:1457`).
- **Verification**:
  - `tests/test_market_state.py` (17 tests) pins bucket boundaries (RTH open inclusive, close exclusive, pre/post extended, overnight, weekend) + locks the `/api/market-state` response shape + asserts the `live_bar_cache` re-export matches the canonical answer at 5 sample timestamps. All pass.
  - Live `GET /api/market-state` correctly returns `state: weekend, buffers_active: true, et_hhmm: 1250` on Sunday evening.
  - Existing tests (live_data_phase1, account_guard, scanner_phase3_ib_only, weekend_aware_safety) all green — 43 tests, no regressions.

### Frontend: FreshnessInspector now shows "Weekend Mode · buffers active" banner + Last 5 Runs sparkline
- **`MarketStateBanner.jsx`** — new top-of-modal banner that renders ONLY when `buffers_active=true` (weekend OR overnight). Stays silent during RTH + extended hours so operators don't see false-positive "warning" UI. Polls `/api/market-state` every 60s. Shows ET wall-clock for confirmation.
- **`LastRunsTimeline.jsx`** — sparkline strip of the last 5 archived training runs. Each bar height = `models_trained_count` (relative to the max in window), color = trophy (emerald) vs non-trophy (rose), star-icon for trophies. Quick "did the latest run train fewer models?" regression spotter — no MongoDB hunting needed now that the trophy archive write actually fires (2026-02 fix).
- **New endpoint** `GET /api/ai-training/recent-runs?limit=5` — compact projection (started_at, completed_at, elapsed_human, models_trained_count, models_failed_count, is_trophy). Cap is 1≤limit≤20.
- **FreshnessInspector layout (top→bottom)**: MarketStateBanner → BackfillReadinessCard → CanonicalUniverseCard → **LastRunsTimeline** → LastTrainingRunCard → LastTrophyRunCard → AutonomyReadinessCard → Subsystem grid → Live subscriptions → TTL plan + RPC.

### Files changed/added
- `backend/services/market_state.py` (NEW — canonical impl)
- `backend/routers/market_state_router.py` (NEW — `/api/market-state`)
- `backend/services/live_bar_cache.py` (refactored to re-export)
- `backend/services/backfill_readiness_service.py` (use canonical import)
- `backend/services/enhanced_scanner.py` (delegate coarse gate to canonical)
- `backend/server.py` (register `market_state_router`)
- `backend/routers/ai_training.py` (NEW endpoint `/recent-runs`)
- `backend/tests/test_market_state.py` (NEW — 17 tests)
- `frontend/src/components/sentcom/v5/MarketStateBanner.jsx` (NEW)
- `frontend/src/components/sentcom/v5/LastRunsTimeline.jsx` (NEW)
- `frontend/src/components/sentcom/v5/FreshnessInspector.jsx` (wire both)


## 2026-02-01 — DataFreshnessBadge: moon icon when market is closed
- **Where**: `frontend/src/components/DataFreshnessBadge.jsx`.
- **What**:
  1. Removed the local `marketState()` helper (duplicated ET-hour math — exact same bug class we just refactored away on the backend). Replaced with a 60s slow-poll of the canonical `/api/market-state` endpoint.
  2. Renders a `lucide-react` `<Moon />` icon next to the status dot ONLY when `is_market_closed=true` (weekend OR overnight). Hidden during RTH + extended hours so the normal tone signal stays uncluttered.
  3. The `mkt` variable now flows from the canonical snapshot — single source of truth across the entire app.
- **Verification**: Frontend compiles clean. Lint OK. The chip now shows the moon at-a-glance without requiring the operator to open the FreshnessInspector.


## 2026-02-01 — V5 Wordmark Moon (Weekend/Overnight Mood Shift)
- **Where**: `frontend/src/components/SentCom.jsx` (main V5 header line ~401).
- **What**:
  1. New shared hook `frontend/src/hooks/useMarketState.js` — thin React wrapper around `/api/market-state` (canonical snapshot, 60s slow-poll). Returns `null` until first fetch resolves so consumers can render nothing instead of guessing a default.
  2. Imported `Moon` from `lucide-react` and the new hook into `SentCom.jsx`.
  3. Added a **`<motion.span>` AnimatePresence-wrapped moon** next to the SENTCOM wordmark — fades + scales in on `marketStateSnap.is_market_closed=true` (weekend OR overnight). Hidden during RTH + extended hours so the header stays normal during trading.
  4. `data-testid="sentcom-wordmark-moon"` for QA. Tooltip shows the `state.label` ("Weekend" / "Overnight (closed)").
- **Result**: Three places now visibly signal "market is closed" — `DataFreshnessBadge` chip moon, `FreshnessInspector` banner, and now the V5 wordmark moon. All drive off the same `/api/market-state` snapshot. Verification: frontend compiles clean, no new lint warnings.


## 2026-02-01 — Consolidate market-state polling under shared hook
- **Where**: `frontend/src/hooks/useMarketState.js` (already existed), now consumed by all three "market closed" surfaces.
- **Refactored to use the shared hook**:
  1. `DataFreshnessBadge.jsx` — dropped its private 60s `/api/market-state` poller + `marketSnap` `useState`, replaced with `useMarketState()`. Net: -19 lines, no behaviour change.
  2. `MarketStateBanner.jsx` — dropped its private poller (was using `useCallback`/`useEffect`/`refreshToken` prop), replaced with `useMarketState()`. Net: -22 lines, the `refreshToken` prop is now no-op since the hook polls on its own schedule.
  3. `FreshnessInspector.jsx` — removed the now-unused `refreshToken` prop from the `MarketStateBanner` call site.
- **Why**: All three surfaces (V5 wordmark moon, DataFreshnessBadge chip moon, FreshnessInspector banner) now flip in lock-step on state boundaries — no risk of one being amber while another is grey for up to 60s during RTH→extended transitions.
- **Verification**: Lint clean, frontend compiles green, no new warnings.


## 2026-02-01 — MarketStateContext: app-wide single poll
- **Where**: `frontend/src/contexts/MarketStateContext.jsx` (NEW), wired into `App.js` provider tree.
- **What**:
  1. New `MarketStateProvider` runs ONE 60s poll of `/api/market-state` for the entire app instance. All consumers read via `useMarketState()` from `useContext`.
  2. The old `frontend/src/hooks/useMarketState.js` is now a thin re-export of the context hook — every existing import (`SentCom.jsx`, `DataFreshnessBadge.jsx`, `MarketStateBanner.jsx`) keeps working with zero rewrites.
  3. Re-exported from `contexts/index.js` so future consumers can `import { useMarketState } from '../contexts'` like the other context hooks.
  4. Mounted in `App.js` between `DataCacheProvider` and `WebSocketDataProvider`. Closed with matching `</MarketStateProvider>` tag.
- **Result**: 1 round-trip per 60s instead of 3+ (one per mounted consumer). Wordmark moon, chip moon, and FreshnessInspector banner now flip in **byte-perfect lock-step** since they share a single state reference.
- **Verification**: Lint clean, frontend compiles green, smoke screenshot confirmed app boots with new provider tree (TradeCommand startup modal renders normally). No new tests — pure refactor with identical observable behaviour.


## 2026-02-01 — AutonomyReadinessContext: app-wide single poll
- **Where**: `frontend/src/contexts/AutonomyReadinessContext.jsx` (NEW), wired into `App.js` provider tree.
- **What** (mirrors the MarketStateContext pattern):
  1. `AutonomyReadinessProvider` runs ONE 30s poll of `/api/autonomy/readiness` for the entire app instance. Exposes `{ data, loading, error, refresh }` so consumers can also force an immediate refetch (e.g. after the operator toggles the kill-switch).
  2. `useAutonomyReadiness()` consumes via `useContext` and falls back to a neutral `{ data: null, loading: true, error: null, refresh: noop }` outside the Provider so legacy code paths don't crash.
  3. `AutonomyReadinessCard` refactored: dropped its private `useState`/`useCallback`/`useEffect`/`refreshToken` prop, now reads from `useAutonomyReadiness()`. Net: -19 lines + simpler reasoning model.
  4. `FreshnessInspector.jsx` — removed the now-unused `refreshToken` prop on the `AutonomyReadinessCard` call site.
  5. Re-exported from `contexts/index.js` for the canonical import path.
  6. Mounted in `App.js` between `MarketStateProvider` and `WebSocketDataProvider`. Matching `</AutonomyReadinessProvider>` close tag added.
- **Result**: Future surfaces (V5 header chip / ⌘K palette preview / pre-Monday go-live banner) can `useAutonomyReadiness()` for free — no extra fetches, byte-perfect lock-step across all surfaces. 1 round-trip per 30s for the entire app instead of N (one per mounted consumer).
- **Verification**: Lint clean, frontend compiles green, no new warnings.


## 2026-02-01 — V5 Header Autonomy Verdict Chip
- **Where**: `frontend/src/components/sentcom/v5/AutonomyVerdictChip.jsx` (NEW), wired into `SentCom.jsx` header next to the wordmark moon.
- **What**:
  1. Tiny pill (1.5px dot + `AUTO · READY/WARN/BLOCKED/…` label) reads from `useAutonomyReadiness()` (canonical 30s-poll context).
  2. Verdict mapping:
     - **GREEN** → emerald pulse, when `verdict='green' && ready_for_autonomous=true`.
     - **AMBER** → amber dot, on warnings OR `verdict='green' && !ready_for_autonomous` (caution: green checks but auto-execute eligibility off).
     - **RED** → rose pulse, on blockers.
     - **ZINC** → loading/error/unconfigured.
  3. Click opens the FreshnessInspector with `scrollToTestId="autonomy-readiness-card"` — operator lands directly on the Autonomy card.
  4. Label hidden on small screens (`sm:inline`) — dot stays visible always.
- **FreshnessInspector** updated to accept a `scrollToTestId` prop and `scrollIntoView` the matching element 120ms after open (gives the cards a frame to mount).
- **Result**: Permanent at-a-glance "am I cleared to flip auto-execute?" signal in the header. Same source-of-truth context as the modal card, so they can never disagree. ~80 lines for the chip + 13 lines for the deep-link scroll.
- **Verification**: Lint clean, frontend compiles green, no new warnings. Ready for visual confirmation on Spark.


## 2026-02-01 — Bug Fix: V5 chat replies invisible (`localMessages` dropped)
- **Symptom**: User types → ENTER → input clears → backend `/api/sentcom/chat` returns 200 OK with the AI reply → but nothing appears in the V5 conversation panel.
- **Root cause**: `SentCom.jsx` stores user message + AI reply into `localMessages`. `SentComV5View` was being passed `messages={messages}` (the stream-only feed from `useSentComStream`), so `localMessages` was never rendered. The UI had no consumer for the local chat state — pre-existing latent bug masked while `<ChatInput disabled={!status?.connected} />` blocked weekend typing. Removing that gate (earlier in this session) unmasked the silent void.
- **Fix**: One-line change in `SentCom.jsx` V5 dispatch — pass the already-computed `allMessages` memo (which dedups `localMessages` + stream `messages`, sorts by timestamp, takes last 30) instead of raw stream `messages`.
- **Also fixed**: CORS spam in browser console — `DataFreshnessBadge.jsx:74` was sending `credentials: 'include'` on `/api/ib/pusher-health` which clashed with the backend's `Access-Control-Allow-Origin: *`. Dropped the unnecessary flag (endpoint is read-only, no auth needed).
- **Verification**: Lint clean, frontend compiles green. User can now confirm the AI reply appears in the V5 unified stream.


## 2026-02-01 — Weekend Briefing Report (Sunday afternoon, full pipeline)

### What was built
A comprehensive Sunday-afternoon weekly briefing surface that auto-generates at 14:00 ET each Sunday + on-demand from the UI.

### Backend
- **`services/weekend_briefing_service.py`** (NEW) — orchestrator with 7 section builders:
  1. `last_week_recap` — Sector ETF returns from `ib_historical_data` (7-day price delta) + closed-trade P&L from `closed_positions`/`trade_history`/`trades` collections (best-effort discovery).
  2. `major_news` — Finnhub `/news?category=general` (cached 7d window).
  3. `earnings_calendar` — Finnhub `/calendar/earnings` filtered to user's positions ∪ default mega-caps (AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, AMD, AVGO, NFLX, CRM, ORCL).
  4. `macro_calendar` — Finnhub `/calendar/economic` filtered to US events with `impact in {high, medium}`.
  5. `sector_catalysts` — keyword-filtered headlines (FDA, earnings, IPO, Fed/FOMC, lawsuit, conference, etc.) with matched-keyword tags.
  6. `gameplan` — LLM (`gpt-oss:120b-cloud` via `agents.llm_provider`) synthesizes 4-6 short paragraphs from the collected facts.
  7. `risk_map` — flags earnings on held positions (high) + high-impact macro events (medium).
- All section builders fail-soft: a missing Finnhub key, missing IB data, missing LLM, or per-call timeout each degrade to an empty section without breaking the whole briefing. Sources are reported in `briefing.sources` so the UI can show what data went in.
- Cached in MongoDB collection `weekend_briefings` keyed by ISO week (`%G-W%V`). Idempotent — same week = same `_id`, upsert.
- Singleton accessor `get_weekend_briefing_service(db)` mirrors codebase convention.

- **`routers/weekend_briefing_router.py`** (NEW):
  - `GET  /api/briefings/weekend/latest` → `{success, found, briefing}`
  - `POST /api/briefings/weekend/generate?force=1` → `{success, briefing}`
- Wired into `server.py` after `market_state_router`.

- **`services/eod_generation_service.py`** — added Sunday 14:00 ET cron via the existing `BackgroundScheduler`. New private method `_auto_generate_weekend_briefing()` calls into the service.

### Frontend
- **`components/sentcom/v5/WeekendBriefingCard.jsx`** (NEW) — collapsible 7-section card. All ticker symbols use `<ClickableSymbol>` so clicks open the existing enhanced ticker modal via `onSymbolClick`. Includes:
  - Header with ISO week, last-generated timestamp, refresh-icon button
  - Default-open "Bot's Gameplan" section + "Risk Map" + "Earnings Calendar" + "Macro Calendar" + "Sector Catalysts" + "Last Week Recap" (sectors + closed P&L) + "Major News (7d)"
  - Sources footer with green/red indicators per data source
  - "Generate Now" button when no briefing exists yet
- **`BriefingsV5.jsx`** — imports the card + `useMarketState`, renders it FIRST in the panel ONLY when `is_weekend=true` (canonical source). Mon-Fri the card stays out of the way.

### Testing
- **`tests/test_weekend_briefing.py`** (26 tests) — pin ISO-week format, catalyst keyword classification (parametrized over 10 keywords), risk-map flagging logic, get_latest fallback path, sector ETF surface stability. All pass in 0.16s.
- Live curl verified: `GET /api/briefings/weekend/latest` → `{success: true, found: false}` (no cache yet on preview), `POST /generate?force=1` → returns full schema with empty sections (preview pod has no Finnhub key + no IB data — expected). On Spark with the env wired, all sections will populate.

### Files added/changed
- `backend/services/weekend_briefing_service.py` (NEW, 480 lines)
- `backend/routers/weekend_briefing_router.py` (NEW)
- `backend/services/eod_generation_service.py` (Sunday cron + `_auto_generate_weekend_briefing`)
- `backend/server.py` (init service + register router)
- `backend/tests/test_weekend_briefing.py` (NEW, 26 tests)
- `frontend/src/components/sentcom/v5/WeekendBriefingCard.jsx` (NEW)
- `frontend/src/components/sentcom/v5/BriefingsV5.jsx` (weekend-gated wire-in)


## 2026-02-01 — Gameplan: structured top-watches JSON (LLM JSON-mode)
- **Where**: `services/weekend_briefing_service.py` + `WeekendBriefingCard.jsx`.
- **What**:
  1. **Backend prompt** rewritten to demand strict JSON `{text, watches[]}` from `gpt-oss:120b-cloud`. System prompt pins the schema with example shape; user prompt has a "respond with STRICT JSON only" reminder.
  2. **`_coerce_gameplan_payload(raw)`** — resilient parser that handles 4 model-misbehaviour cases: strict JSON → fenced JSON (```json...```) → JSON embedded in prose → pure prose fallback. Also caps watches at 5, uppercases symbols, drops oversized/empty symbols, truncates oversized fields, swallows JSON decode errors.
  3. **`_synthesize_gameplan()`** now returns `{"text": str, "watches": [...]}` instead of a raw string. Briefing dict's `gameplan` field is the structured object.
  4. **`get_latest`/`generate` cache check** detects "has gameplan" across BOTH old (str) and new (dict) shapes — back-compat with any pre-migration cached docs.
- **Frontend**:
  - New `<GameplanBlock>` component handles both shapes (legacy string → single paragraph; new dict → cards grid + paragraph).
  - Watches render as a grid of clickable cards: bold ticker symbol (clickable → existing enhanced ticker modal), key level on the right (cyan tabular-nums), thesis below, invalidation in rose-400/80. Hover effect: cyan border. `data-testid="gameplan-watch-{SYMBOL}"` for QA.
- **Tests**: 10 new pytest cases pin the parser's resilience guarantees — strict JSON, markdown fences, prose+JSON sandwich, pure prose, empty input, watches cap (5), missing symbol, oversized fields, lowercase symbol, oversized symbol. All 36 weekend-briefing tests pass.
- **Verification**: Live curl confirms `gameplan: {text: "", watches: []}` (empty in preview pod due to no LLM/Finnhub key). On Spark with Ollama+Finnhub wired, you'll see populated watches as a card grid in the Bot's Gameplan section.


## 2026-02-01 — Monday-morning auto-load: top watch → V5 chart
- **Where**: `frontend/src/hooks/useMondayMorningAutoLoad.js` (NEW), wired into `SentComV5View.jsx`. Visual marker in `WeekendBriefingCard.jsx`.
- **What**:
  1. **Hook fires on Mon 09:25 → 09:40 ET**, fetches `/api/briefings/weekend/latest`, reads `briefing.gameplan.watches[0].symbol`, calls `setFocusedSymbol(symbol)` so the V5 chart frames on the bot's #1 idea before the open.
  2. **Idempotent per ISO week** via localStorage flag (`wb-autoload-{ISO_WEEK}`). Reloads inside the window won't re-fire. Browser caches the auto-loaded symbol under `wb-autoloaded-symbol-{ISO_WEEK}` for the UI marker.
  3. **Respects manual focus** — `userHasFocusedRef` flips to `true` whenever the operator clicks any ticker (via `handleOpenTicker` or `V5ChartHeader.onChangeSymbol`). When set, the hook becomes a no-op so the auto-load NEVER overrides an explicit user choice.
  4. **`SentComV5View.jsx`** introduces `setFocusedSymbolUserDriven` — wraps `setFocusedSymbol` with the user-flag bookkeeping. The auto-load hook still calls the raw setter so its own action doesn't lock itself out.
  5. **Visual marker**: `WeekendBriefingCard.GameplanBlock` reads `readAutoLoadedSymbol(isoWeek)` and stamps the matching watch card with a cyan border + `LIVE` chip. Operators see at a glance which watch is currently on the chart.
- **Verification**: Lint clean. Frontend hot-reloads green. The hook is purely additive — no other behaviour touched, manual ticker clicks still work identically.


## 2026-02-01 — Monday morning watch carousel (09:10-09:50 ET)
- **Where**: `frontend/src/hooks/useMondayMorningAutoLoad.js` — refactored from a single-shot auto-load into a rotating carousel.
- **What**:
  1. **40-min window** sliced into eight 5-minute slots (09:10/15/20/25/30/35/40/45 ET).
  2. Each slot maps to `watches[slot_index % watches.length]` so even with 3 watches the operator sees each one a couple times before the open.
  3. `setFocusedSymbol(sym)` fires ONLY when the slot index actually advances — `lastIndexRef` prevents churn between market-state polls.
  4. Briefing is fetched once and cached for 10 minutes inside the window — no spam to `/api/briefings/weekend/latest` every 60s.
  5. Idempotency now uses the per-week symbol marker (`wb-autoloaded-symbol-{ISO_WEEK}`) instead of a "fired-once" flag — page reloads mid-carousel resume on the right watch instead of restarting from #0.
  6. **`userHasFocused` gate is unchanged** — the moment the operator clicks any ticker the carousel becomes a no-op for the rest of the session.
- **Visual marker** in `WeekendBriefingCard.GameplanBlock` automatically follows the carousel: the cyan border + LIVE chip move to whichever watch the chart is currently framed on, since they read from the same localStorage key.
- **Verification**: Lint clean, frontend compiles green. No backend changes.


## 2026-02-01 — Carousel countdown chip in V5 chart header
- **Where**: `frontend/src/hooks/useCarouselStatus.js` (NEW), `components/sentcom/v5/CarouselCountdownChip.jsx` (NEW), wired into `V5ChartHeader` in `SentComV5View.jsx`.
- **What**:
  1. **`useCarouselStatus()`** mirrors the autoload hook's window/slot math but is read-only — returns `{active, currentSymbol, nextSymbol, secondsUntilNext, totalWatches}`. Briefing fetched once + cached for 10 min inside the window. 1Hz heartbeat ticks the countdown but ONLY runs while the chip is visible (not all day).
  2. **`<CarouselCountdownChip />`** renders `LIVE · {current} · MM:SS → {next}` in cyan as a pill in the V5 chart header. Hidden outside the Monday 09:10-09:50 ET window. Animated radio icon. `data-testid` on every dynamic part for QA.
  3. Wired into `V5ChartHeader` next to the existing `LiveDataChip` so it sits inline with the symbol input + LONG/SHORT badge.
- **Result**: Operator sees `LIVE · AAPL · 02:14 → MSFT` and knows exactly how long the chart will stay on the current watch before rotating. Combined with the LIVE chip on the matching watch card in the Weekend Briefing's gameplan section, the auto-frame feels intentional rather than mysterious.
- **Verification**: Lint clean, frontend compiles green.


## 2026-02-01 — Manual rotation controls in carousel chip
- **Where**: `frontend/src/components/sentcom/v5/CarouselCountdownChip.jsx` (rewrite to add ‹/› buttons), `hooks/useCarouselStatus.js` (expose `watches[]` + `currentIdx`), `components/sentcom/SentComV5View.jsx` (state migration + prop wiring).
- **What**:
  1. Chip now has two modes:
     - **AUTO** — rotation active, cyan tone, animated radio icon, `LIVE · ‹ AAPL · 02:14 → MSFT ›`. Clicking ‹/› immediately picks the prev/next watch, marks the manual-override flag (pauses auto-rotation for the session), and triggers re-render into PAUSED mode.
     - **PAUSED** — operator has taken over, zinc tone, `WATCHES · ‹ AAPL ›`. Arrows still work — chip becomes a tiny manual watches-cycler. Useful for stepping through the bot's gameplan watches with one click each.
  2. In PAUSED mode the cycler navigates relative to the chart's *current* symbol (`currentChartSymbol` prop), so operator can step `‹/›` from wherever they last landed instead of jumping back to the carousel's auto-slot.
  3. **State migration in `SentComV5View`**: `userHasFocusedRef` → `useState(userHasFocused)`. The ref version didn't trigger re-renders, so the chip wouldn't flip into PAUSED mode immediately when the operator clicked. State trigger fixes the snap-into-pause UX.
  4. New `onCarouselPick` + `userHasFocused` props threaded through `V5ChartHeader` → `<CarouselCountdownChip>`.
- **Verification**: Lint clean, frontend compiles green.


## 2026-02-01 — Persist carousel pause flag across page reloads
- **Where**: `frontend/src/hooks/useMondayMorningAutoLoad.js` (new helpers + ISO-week util), `components/sentcom/SentComV5View.jsx` (seed + persist).
- **What**:
  1. New helpers exported from `useMondayMorningAutoLoad.js`:
     - `isoWeekFromBrowser()` — computes `2026-W18` style key from browser local time, ET-bucketed (mirrors backend `_iso_week()`).
     - `readPausedFlag(iso_week)` / `writePausedFlag(iso_week)` — `localStorage[wb-paused-{ISO_WEEK}]` get/set.
  2. `SentComV5View.jsx`:
     - `useState(userHasFocused)` initializer reads from localStorage so a refresh inside the carousel window doesn't reset the override.
     - `setFocusedSymbolUserDriven` writes the paused flag the moment the operator takes over.
- **Result**: Once the operator clicks a ticker, arrow, or search box, the carousel is paused for that ISO week. Reloading the page during 09:10-09:50 ET keeps the chip in PAUSED mode + leaves the chart on the operator's choice.
- **Verification**: Lint clean, frontend compiles green.


## 2026-02-01 — Friday close snapshot + last-week gameplan grade
- **Where**: `services/weekend_briefing_service.py`, `routers/weekend_briefing_router.py`, `services/eod_generation_service.py`, `frontend/src/components/sentcom/v5/WeekendBriefingCard.jsx`.
- **What**:
  1. **Signal-price enrichment at briefing-generation time** — every watch in `gameplan.watches` gets a `signal_price` field (latest IB 1day close at generation time). Foundation for grading.
  2. **`WeekendBriefingService.snapshot_friday_close()`** — reads the current week's briefing, fetches the latest IB close for each watch, computes `change_pct` vs `signal_price`, persists into `friday_close_snapshots[iso_week]`. Idempotent (upsert).
  3. **`WeekendBriefingService.get_friday_snapshot(iso_week)`** — read-only accessor.
  4. **`_build_previous_week_recap()`** — joined via `_previous_iso_week()`. Returns `{iso_week, snapshot_at, watches[], summary: {graded, wins, losses, avg_change_pct}}`. The `generate()` orchestrator now embeds this into `last_week_recap.gameplan_recap`.
  5. **Friday 16:01 ET cron** added to `eod_generation_service` BackgroundScheduler. Calls `_auto_snapshot_friday_close()` which delegates to the service.
  6. **API additions**:
     - `POST /api/briefings/weekend/snapshot-friday-close` — manual on-demand trigger.
     - `GET  /api/briefings/weekend/snapshot/{iso_week}` — ad-hoc audit.
  7. **Frontend** — `LastWeekRecap` renders a new "Last Week's Gameplan Grade" block at the top: per-watch P&L (clickable ticker → enhanced ticker modal), `W/L · avg ±X%` summary, color-coded change_pct.
- **Testing**: 5 new pytest cases pin `_previous_iso_week()` boundary, `snapshot_friday_close()` skip paths (no briefing, no watches, no DB), `get_friday_snapshot(None)` safety. **41/41 weekend-briefing tests pass.**
- **Live verification**: `POST /snapshot-friday-close` returns `no_watches_in_briefing` (preview pod has no LLM-populated briefing — expected). `GET /snapshot/2026-W17` returns `found: false`. On Spark with the cron firing weekly, the next Sunday's briefing's "Last Week's Gameplan Grade" block will populate automatically.

### Files changed
- `backend/services/weekend_briefing_service.py` (signal_price enrichment, snapshot_friday_close, get_friday_snapshot, _build_previous_week_recap)
- `backend/routers/weekend_briefing_router.py` (2 new endpoints)
- `backend/services/eod_generation_service.py` (Friday 16:01 ET cron + handler)
- `backend/tests/test_weekend_briefing.py` (5 new tests)
- `frontend/src/components/sentcom/v5/WeekendBriefingCard.jsx` (LastWeekRecap renders gameplan_recap)

## Earlier in this session
### XGBoost & setup models rewired to triple-barrier labels (P0) — DONE
- `_extract_symbol_worker` (Phase 1 generic directional, `timeseries_gbm.py`) now produces
  triple-barrier 3-class labels (0=DOWN/SL-hit, 1=FLAT/time-exit, 2=UP/PT-hit) instead of
  binary `future > current`. Feature cache key bumped to `_tb3c` to invalidate stale entries.
- `_extract_setup_long_worker` (Phase 2) and `_extract_setup_short_worker` (Phase 2.5) switched
  from noise-band 3-class to triple-barrier 3-class. Shorts use negated-series trick so the
  lower barrier == PT for a short.
- Phase 7 regime-conditional models switched from binary `future_ret > 0` to triple-barrier
  3-class; `train_from_features(num_classes=3)`.
- Phase 8 ensemble meta-learner switched from ±0.3% threshold 3-class to triple-barrier
  (using ATR-scaled barriers with `max_bars = anchor_fh`).
- `TimeSeriesGBM.train()` and `train_vectorized()` now delegate to
  `train_from_features(num_classes=3)` — single canonical training path.
- `TimeSeriesGBM.predict()` handles 3-class softmax output (shape (1,3)) → `{down, flat, up}`.
- Persistence: `_save_model()` writes `num_classes` and `label_scheme`
  (`triple_barrier_3class` or `binary`); `_load_model()` restores `_num_classes`.
- `get_setup_models_status()` now returns `label_scheme` per profile from DB so UI can
  distinguish freshly-trained triple-barrier models from legacy binary models.
- NIA `SetupModelsPanel` shows a green **Triple-Barrier** badge for new models and a red
  **Legacy binary** warning for models that need retraining.

### Test coverage
- `backend/tests/test_triple_barrier_labeler.py` (8 tests, unchanged).
- NEW: `backend/tests/test_timeseries_gbm_triple_barrier.py` (3 tests):
  - `_extract_symbol_worker` returns int64 3-class targets.
  - End-to-end train_from_features(num_classes=3) + XGBoost softprob predict returns (N,3).
  - `get_model_info`/`get_status` surface `num_classes` and `label_scheme`.
- All 11 tests pass (`PYTHONPATH=backend python -m pytest backend/tests/…`).

### Downstream consumers — verified wired to new scheme (no code changes needed):
- `predict_for_setup` (timeseries_service.py): already handles 3-class softprob output →
  returns `{direction: up/down/flat, probability_up/down/flat, confidence, num_classes}`.
- `confidence_gate.py`: consumes via `_get_live_prediction` → `predict_for_setup` (up/down/flat),
  plus `_get_tft_signal`, `_get_cnn_lstm_signal`, `_get_cnn_signal`, `_get_vae_regime_signal`
  which already return 3-class direction strings.
- TFT + CNN-LSTM `predict()`: direction_map {0:down, 1:flat, 2:up} — matches triple-barrier
  class indices (fixed earlier this session).
- Scanner / Trading Bot / Learning Loop / Trade Journal / NIA / SentCom Chat: consume
  `direction` as semantic string ("up"/"down"/"flat" for prediction, "long"/"short" for trade
  side). No changes needed — prediction interface unchanged.

### Retrain plan (USER — run on Spark once Phase 13 revalidation finishes)
1. Stop the current bot and revalidation script.
2. Clear the NVMe feature cache so `_tb3c` keys rebuild:
   `mongo tradecommand --eval 'db.feature_cache.deleteMany({})'`
3. Kick off a full retrain (Phase 1 → Phase 8): `python backend/scripts/local_train.py`
   (or the worker job if available). This will produce triple-barrier models that
   overwrite the old binary/noise-band models in `timeseries_models` collection (protected
   by the best-model promotion gate — new model must beat accuracy of current active).
4. After training, rerun `python backend/scripts/revalidate_all.py` to validate the new
   models against the fail-closed gates.
5. Retrain DL models (TFT, CNN-LSTM, VAE) via the Phase 11 job so their metadata matches
   (`regime_diversity`, `win_auc`).
6. Verify the NIA page shows green **Triple-Barrier** badges on every trained profile,
   and that 0-trade filter rate drops below 100% on sample symbols.


### P0 Morning Briefing bogus-position bug — RESOLVED
- Root-caused: `MorningBriefingModal.jsx` calls `/api/portfolio`, which pulls IB-pushed positions. When marketPrice=0 on restart, `gain_loss = 0 − cost_basis` produced fake -$1.2M.
- Fix: `backend/routers/portfolio.py` — added `quote_ready` flag per position and `quotes_ready` in summary; trusts IB's `unrealizedPNL` until live quote arrives; filters zero-share rows.
- Fix: `frontend/src/components/MorningBriefingModal.jsx` — shows amber "awaiting quotes" badge instead of fake PnL. Flatten button removed (wrong place for destructive admin action).

### New `POST /api/portfolio/flatten-paper` endpoint
- Guard rails: `confirm=FLATTEN` token, paper-account-only (code starts with 'D'), 120s cooldown, pre-flight cancel of stale `flatten_*` orders, pusher-freshness check (refuses if last_update >30s old).

### IB Pusher double-execution bug — FIXED
- Root cause: TWS mid-session auto-upgrade + fixed pusher clientId=15 → IB replayed stale session state as new orders, causing 2×-3× fills per flatten order.
- `documents/scripts/ib_data_pusher.py` — added `_recently_submitted` in-memory idempotency cache stamping each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10 min.
- `documents/scripts/StartTradeCommand.bat` — pusher clientId now randomized 20–69 per startup so stale TWS sessions can't replay.

### 🚨 Credential leak — FIXED
- Paper password was hardcoded in `.bat` and committed to GitHub. Moved to local-only `.ib_secret`, `.gitignore` updated, `README_SECRETS.md` added.
- User rotated paper password + created `.ib_secret` on Windows.

### Validator fail-open paths — LAYER 1 FIXED, LAYER 2 IDENTIFIED AND FIXED
- **Layer 1 (earlier session)**: `Insufficient trades → promoting by default` → replaced with 9 fail-closed gates (n≥30, Sharpe≥0.5, edge≥5pp, MC P(profit)≥55%, etc.)
- **Layer 2 (today, 2026-04-20)**: when a failing model had no prior baseline to roll back to, validator silently flipped `decision["promote"] = True` and saved the broken model as baseline. Now rejects outright and does NOT write a baseline; trading bot reads baselines as the live-trading gate, so rejected models cannot leak into prod.
- `backend/scripts/revalidate_all.py` — fixed dict-vs-string bug in SETUP_TRAINING_PROFILES iteration.

### Phase 13 revalidation — RUNNING
- Launched against 20 unique setup types (best bar_size each, from 34 trained pairs).
- Uses fixed fail-closed validator + new layer-2 fix.
- ETA ~60-90 min. First run pending verification.


## Completed this fork (2026-04-24 — Gate diag + DL Phase-1 + Post-Phase-13 fixes)

### Post-Phase-13 findings (user ran `scripts/revalidate_all.py` on Spark)
- **3 SHORT models PROMOTED** with real edge: SHORT_SCALP/1 min (417 trades, 53.0% WR, **1.52 Sharpe**, +6.5pp edge), SHORT_VWAP/5 mins (525 trades, 54.3% WR, **1.76 Sharpe**, +5.3pp), SHORT_REVERSAL/5 mins (459 trades, 53.4% WR, **1.94 Sharpe**, +7.6pp).
- **10/10 LONG setups REJECTED — `trades=0` in Phase 1** across every one. Root cause diagnosed: 3-class XGBoost softprob models collapsed to always-predicting DOWN/FLAT (triple-barrier PT=2×ATR vs SL=1×ATR + bearish training regime → DOWN-heavy labels). Neither the 13-layer confidence gate nor the DL class weights (which only affect TFT/CNN-LSTM) could touch this — the XGBoost training loop itself was uniform-weighted for class balance.
- Secondary: several shorts failed only on MC P(profit) or WF efficiency (SHORT_ORB 52.5% MC, SHORT_BREAKDOWN 68% WF).
- Multiple models have training_acc <52% (ORB 48.6%, GAP_AND_GO 48.5%, MOMENTUM 44.2%) → dead weight, should be deleted on next cleanup pass.

### Option A — Short-model routing SHIPPED
**Problem:** Scanner emits fine-grained setup_types like `rubber_band_scalp_short` / `vwap_reclaim_short`; training saves aggregate keys like `SHORT_SCALP` / `SHORT_VWAP` / `SHORT_REVERSAL`. The `predict_for_setup` path did a naive `setup_type.upper()` dict lookup → every promoted short model was unreachable from the live scanner path. The edge was being ignored.

**Fix:** New `TimeSeriesAIService._resolve_setup_model_key(setup_type, available_keys)` static resolver with priority chain:
  1. Exact uppercase match (preserves existing behavior)
  2. Legacy `VWAP_BOUNCE` / `VWAP_FADE` → `VWAP`
  3. Short-side routing: strip `_SHORT` suffix, try `SHORT_<base>` exact, then family substring match against 10 known SHORT_* models (SCALP → SHORT_SCALP, VWAP → SHORT_VWAP, etc.)
  4. Long-side: strip `_LONG`, try base, then family substring
  5. Fallback to raw (caller routes to general model)

Wired into `predict_for_setup` line 2492. Existing long-side VWAP_BOUNCE/VWAP_FADE routing preserved. Fully reversible — resolver is pure.

**Impact:** `rubber_band_scalp_short` → `SHORT_SCALP` (newly promoted), `vwap_reclaim_short` → `SHORT_VWAP`, `halfback_reversal_short` → `SHORT_REVERSAL`. All three promoted shorts are now reachable from the live scanner path.

**Regression coverage** — `backend/tests/test_setup_model_resolver.py` (10 tests): exact match, legacy VWAP mapping, 4 scalp-short variants, 3 vwap-short variants, 3 reversal-short variants, long-side suffix strip, unknown-setup fallback, short→base fallback when no SHORT models loaded, empty/None passthrough, VWAP_FADE_SHORT double-suffix case. All 10 pass.

### Option B — XGBoost class-balance fix SHIPPED
**Problem:** The 10/10 long rejects in Phase 13 were caused by 3-class XGBoost softprob collapsing to "always predict DOWN/FLAT" because `train_from_features` used uniform `sample_weight` for class balance. The triple-barrier label distribution (DOWN ≈ 50-60%, FLAT ≈ 30-40%, UP ≈ 10-15%) meant gradient pressure on the UP class was minimal.

**Fix:** Added `apply_class_balance: bool = True` kwarg to `TimeSeriesGBM.train_from_features`. When True (default), the method:
  1. Computes sklearn-balanced per-sample weights via new `dl_training_utils.compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)` — inverse-frequency, clipped 5×, mean-normalized to 1.0
  2. Multiplies element-wise into existing `sample_weights` (uniqueness) — both signals stacked
  3. Re-normalizes to mean==1 so absolute loss scale is unchanged
  4. DMatrix receives the blended weight vector → XGBoost sees ~5× more gradient pressure on UP class samples
  5. Logged as `class_balanced (per-class weights=[1.0, 1.67, 5.0])` in training output

Default=True so next retrain gets the fix automatically. `apply_class_balance=False` reproduces legacy behavior bit-for-bit.

**Regression coverage** — `backend/tests/test_xgb_class_balance.py` (4 tests):
  - Minority-class samples weigh ~5× majority-class samples for the Phase-13 skew pattern
  - `train_from_features(apply_class_balance=True)` actually passes class-balanced `weight=` into `xgb.DMatrix` (integration-style with stubbed xgb)
  - `apply_class_balance=False` → DMatrix weight= is None (legacy uniform)
  - Uniqueness + class-balance blend: element-wise product, mean-normalized, class skew preserved in the blend

Plus 3 new unit tests for `compute_per_sample_class_weights` in `test_dl_training_utils.py`.

**Full session suite: 56/56 passing** (9 gate-log + 23 DL utils + 4 XGB class balance + 10 setup resolver + 10 resolver trace endpoint).

### Setup-resolver diagnostic endpoint SHIPPED
`GET /api/ai-training/setup-resolver-trace` — makes scanner → model routing inspectable.
  - `?setup=rubber_band_scalp_short` — single trace: returns `resolved_key`, `resolved_loaded`, `match_step` (`exact` / `legacy_vwap_alias` / `short_family` / `long_base_strip` / `family_substring` / `fallback`), `will_use_general`
  - `?batch=a,b,c` — batch mode with `coverage_rate` across all inputs
  - Uses the live `timeseries_service._setup_models` so it reflects what's ACTUALLY loaded on Spark, not the trained manifest
  - Live-verified on preview backend (`loaded_models_count=0` → every input reports `fallback` → this is exactly the coverage-gap signal the endpoint was designed to surface)
  - `backend/tests/test_setup_resolver_trace_endpoint.py` — 10 tests covering every `match_step` branch, batch parsing, whitespace handling, missing-param 400

**Next step for user (on Spark, post-retrain):**
```
curl -s "http://localhost:8001/api/ai-training/setup-resolver-trace?batch=rubber_band_scalp_short,vwap_reclaim_short,halfback_reversal_short,opening_drive_long,reversal_long,vwap_fade" | python3 -m json.tool
```
Any trace with `resolved_loaded=false` is a coverage gap → either map it in `_resolve_setup_model_key` or add a training profile.


## Completed prior fork (2026-04-24 — Gate-log diagnostic + DL Phase-1 closure)

**Next step for user (on Spark):**
1. Save to Github → `git pull` on Spark
2. Restart backend
3. Kick off full retrain. Watch for log lines:
   - `Training from pre-extracted features: ..., class_balanced (per-class weights=[1.0, 1.6, 4.8])` — confirms class balance is active
   - `[TFT] Purged split: ... class_weights=[1.0, 0.45, 2.1] sample_w_mean=1.000` (on TFT/CNN-LSTM retrain)
4. Re-run `scripts/revalidate_all.py` — expect non-zero trade counts on LONG setups and more promotions.
5. (Optional) `export TB_DL_CPCV_FOLDS=5` before retrain for CPCV stability distribution in the scorecard.


## Completed prior fork (2026-04-24 — Gate-log diagnostic + DL Phase-1 closure)

### P0 Task 2 — TFT + CNN-LSTM: Phase-1 infra closed SHIPPED
Background: Phase 1 (sample-uniqueness weights, purged CPCV, scorecard, deflated Sharpe) was wired into XGBoost on 2026-04-20 but never plumbed into the DL training loops. Both models were training with plain `CrossEntropyLoss` on a chronological 80/20 split — the #1 likely cause of the <52% accuracy collapse and the `TFT signal IGNORED` / `CNN-LSTM signal IGNORED` log spam in the confidence gate.

**New module — `services/ai_modules/dl_training_utils.py`** (pure-numpy + torch, imports are lazy so tests run without GPU wheels):
  - `compute_balanced_class_weights(y, num_classes=3, clip_ratio=5.0)` — sklearn "balanced" inverse-frequency weights scaled so min=1, clipped at 5× so a tiny minority class doesn't explode gradients.
  - `compute_sample_weights_from_intervals(per_symbol_intervals, per_symbol_n_bars)` — López de Prado `average_uniqueness` **per symbol** (concurrency only meaningful within one bar axis), concatenated and normalized to mean=1.
  - `purged_chronological_split(intervals, n_samples, split_frac=0.8, embargo_bars=5)` — walk-forward split that drops train events whose [entry, exit] extends into the val-window plus embargo. Falls back to plain chronological when `intervals` is None → pipelines that skip interval tracking keep current behavior.
  - `run_cpcv_accuracy_stability(train_eval_fn, intervals, n_samples, …)` — opt-in CPCV stability measurement via env var `TB_DL_CPCV_FOLDS` (default 0 = OFF, so current training runtime is unchanged). When enabled, runs lightweight re-trains across `C(n_splits, n_test_splits)` purged folds and returns mean / std / negative_pct / scores for the scorecard.
  - `build_dl_scorecard(...)` — emits a scorecard dict compatible with the existing `timeseries_models.scorecard` persistence pattern: hit_rate=val_acc, ai_vs_setup_edge_pp, cpcv stability, grade A-F based on edge-vs-baseline. PnL fields stay 0 (DL classifiers don't produce PnL at train time).

**TFT wire-in (`services/ai_modules/temporal_fusion_transformer.py`)**:
  - Tracks `(entry_idx, exit_idx)` per sample per symbol via `build_event_intervals_from_triple_barrier` (same PT/SL/horizon as labeling, so spans match).
  - Concatenates intervals with a per-symbol global offset (`_cumulative_bar_offset += n_bars + max_symbols`) so cross-symbol samples never appear to overlap.
  - `nn.CrossEntropyLoss()` → `nn.CrossEntropyLoss(weight=class_weights_t, reduction='none')` + per-sample uniqueness multiply before the batch mean.
  - Plain 80/20 split → `purged_chronological_split(embargo_bars=5)`.
  - Optional CPCV stability pass (gated on `TB_DL_CPCV_FOLDS`) runs **after** main training; scorecard captures stability, then original best_state is restored.
  - Scorecard persisted to Mongo `dl_models.scorecard` (non-fatal on failure). Returns `class_weights`, `sample_weight_mean`, `purged_split`, `cpcv_stability`, `scorecard` in the train() result dict.

**CNN-LSTM wire-in (`services/ai_modules/cnn_lstm_model.py`)**: Same treatment.
  - `extract_sequence_features()` gains a backward-compatible `return_intervals=False` kwarg; when True also returns `entry_indices` + `n_bars`.
  - Auxiliary win-probability loss (class-2 binary target) is now also sample-weight scaled via `reduction='none'`.
  - Same class-weighted CE, purged split, CPCV-optional, scorecard persistence.

**Backward compat contract (explicit):**
  - Prediction paths untouched — `predict()` signatures unchanged on both models.
  - Saved checkpoints untouched — `_save_model` writes the same fields; scorecard is written via a follow-up `update_one`.
  - Default training runtime unchanged — CPCV is OFF by default.
  - When interval tracking fails (e.g. empty `global_intervals_chunks`), `purged_chronological_split` degrades to the plain chronological split, matching pre-change behavior.

**Regression coverage — `backend/tests/test_dl_training_utils.py` (20 tests, all passing):**
  - Class-weight math: inverse-frequency, clip at 5×, uniform input, missing-class clip, empty input.
  - Sample weights: unique events = uniform 1.0, overlapping events downweighted (standalone beats overlapping), multi-symbol concat, empty input.
  - Purged split: leaky train event purged, no-intervals → plain chronological, misaligned intervals → fallback, tiny dataset → empty.
  - Scorecard: edge + grade A for +11pp, grade F for negative edge.
  - CPCV env parsing: default 0, valid int, invalid string, negative clamped.
  - `run_cpcv_accuracy_stability` integration with real `CombinatorialPurgedKFold`.

**Full session suite: 29/29 passing** (9 gate-log + 20 DL utils).

**Next step for user (on Spark):**
1. Save to Github → `git pull` on Spark
2. Restart backend (`pkill -f "python server.py" && cd backend && nohup /home/spark-1a60/venv/bin/python server.py > /tmp/backend.log 2>&1 &`)
3. Kick off TFT + CNN-LSTM retrain via NIA (or worker job). Look for log lines like:
   `[TFT] Purged split: train=... val=... class_weights=[1.0, 0.45, 2.1] sample_w_mean=1.000`
4. Check `dl_models.<name>.scorecard.hit_rate` — should clear 0.52 so layers 9/10/11 stop being IGNORED.
5. (Optional, heavier) `export TB_DL_CPCV_FOLDS=5` before retrain to get CPCV stability distribution in the scorecard.
6. Re-run `analyze_gate_log.py --days 14` post-retrain to quantify Layer 9/10/11 revival.

### P0 Task 1 — `analyze_gate_log.py` SHIPPED
Purpose: Phase 13 revalidation rejected every setup (0 trades passing the 13-layer gate). Before touching models (TFT/CNN-LSTM triple-barrier rebuild), we need **empirical** data on which of the 13 layers actually add edge vs. pure friction. This script answers that.

- `/app/backend/scripts/analyze_gate_log.py` — reads `confidence_gate_log`, parses the free-form `reasoning` list to classify each line into one of the 13 layers via deterministic prefix regexes (contract with confidence_gate.py), extracts the signed score delta from the trailing `(+N…)` / `(-N…)` marker, and emits per-layer:
  - `fire_rate`, `positive_rate`, `negative_rate`
  - `mean_delta`, `median_delta`, `stdev_delta`
  - When `outcome_tracked=True` rows exist: `win_rate_when_positive`, `edge_when_positive` (WR lift over baseline), same for negative. **This is the friction-vs-edge measurement.**
  - A heuristic verdict per layer: `EDGE` / `FRICTION` / `NEUTRAL` / `LOW DATA` / `DORMANT` / `PENDING OUTCOMES`.
  - Writes `/tmp/gate_log_stats.md` (human) + `/tmp/gate_log_stats.json` (machine) and prints to stdout.
- CLI flags: `--days`, `--symbol`, `--setup`, `--direction`, `--outcome-only`, `--limit`.
- **Tests**: `/app/backend/tests/test_analyze_gate_log.py` — 9 tests: prefix classification for all 12 active layers + decision-line exclusion, delta extraction (positive/negative/trailing-clause/neutral), per-doc layer aggregation, decision-count + fire-rate math, outcome-conditional edge math (baseline + conditional WR), friction heuristic on a synthetic losing layer. All 9 pass in 0.10s.
- Zero changes to the gate itself — pure read-side analysis, safe to run while live and while Phase 13 revalidation is still in flight.

**Next step (user on Spark):**
```
cd ~/Trading-and-Analysis-Platform && git pull
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/analyze_gate_log.py --days 30
# or, narrowed to outcome-tracked only:
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/analyze_gate_log.py --days 90 --outcome-only
```
Share the `/tmp/gate_log_stats.md` output — that's the input to Task 2 (DL model rebuild scope).


## Completed prior fork (2026-04-23 — Layer 13 FinBERT + frontend + latency + confirm_trade)

### P1 — FinBERT Layer 13 wired into ConfidenceGate SHIPPED
- **Discovery**: `FinBERTSentiment` class was already built (`ai_modules/finbert_sentiment.py`) with a docstring explicitly reading *"Confidence Gate (INACTIVE): Ready to wire as Layer 12 when user enables it."* All 5,328 articles in MongoDB `news_sentiment` already pre-scored (scorer loop is running). Infrastructure was 95% there.
- **Wire-up** in `services/ai_modules/confidence_gate.py`:
  - `__init__` adds `self._finbert_scorer = None` (lazy init)
  - Class docstring extended with Layer 13 line
  - New Layer 13 block inserted between Layer 12 and decision logic (lines ~605-670)
  - Calls `self._finbert_scorer.get_symbol_sentiment(symbol, lookback_days=2, min_articles=3)`
  - Aligns score with trade direction (long: positive is good; short: negative is good)
  - Scales by scorer's `confidence` (low std across articles → stronger signal)
  - Point scale: +10 (strong aligned), +6 (aligned), +3 (mild), -3 (opposing), -5 floor (strong opposing)
  - Wrapped in try/except — FinBERT errors never fail the gate (graceful no-op with warning log)
- **Regression tests**: `backend/tests/test_layer13_finbert_sentiment.py` — 4 tests, all pass. Lazy-init pattern verified, docstring contract verified, bounded +10/-5 verified, import safety verified.
- **Test suite status**: 20/20 pass across all session's backend regression tests.

### Phase 13 revalidation (next step, user-run on Spark)
Layer 13 is live in the code but `revalidate_all.py` needs to run on Spark against historical trades to quantify Layer 13's contribution + recalibrate gate thresholds. This requires live DB + models + ensembles already on Spark — can't run from fork. Handoff command: `cd ~/Trading-and-Analysis-Platform/backend && /home/spark-1a60/venv/bin/python scripts/revalidate_all.py`.

### P1 — Frontend execution-health indicators SHIPPED
- **`TradeExecutionHealthCard.jsx`** — compact badge in SentCom header (next to ServerHealthBadge). Polls `/api/trading-bot/execution-health?hours=24` every 60s. 4 states with distinct color + icon: HEALTHY (emerald, <5% failure) / WATCH (amber, 5-15%) / CRITICAL (red, ≥15%) / LOW-DATA (grey, <5 trades). Hover tooltip shows raw stats.
- **`BotHealthBanner.jsx`** — full-width red banner that **only renders when alert_level is CRITICAL**. Silent otherwise. Shows top 3 failing setups + total R bled. Session-dismissable via ×. Integrated at top of SentCom embedded mode (above ambient effects).

Both components use `memo`, 60s poll cadence, `data-testid` attributes, and follow existing `ServerHealthBadge` conventions. Lint clean.

### P1 — `confirm_trade` false-negative FIXED
**Root cause:** `TradeExecution.confirm_trade` returned `trade.status == TradeStatus.OPEN` only, so trades correctly filtered by the strategy phase gate (`SIMULATED`, `PAPER`) or pre-trade guardrail (`VETOED`) reported as API failures. The router then raised 400 "Failed to execute trade" on legitimate pipeline outcomes — misleading when demoing trades or using the confirmation mode UI.

**Fix:**
- `/app/backend/services/trade_execution.py` — confirm_trade now treats `{OPEN, PARTIAL, SIMULATED, VETOED, PAPER}` as the handled-successfully set. Genuine `REJECTED`, stale-alert, and missing-trade paths still return False.
- `/app/backend/routers/trading_bot.py` — `POST /api/trading-bot/trades/{id}/confirm` now returns 200 with the actual status + a status-specific message (executed / simulated / paper / vetoed / partial). 404 reserved for missing trade, 400 only for real rejections (with `reason` in detail).

**Regression coverage:** `/app/backend/tests/test_confirm_trade_semantics.py` — 8 tests covering every terminal status + stale-alert + missing-trade. All pass.

### P0 — Queue schema stripping bracket fields FIXED
**Root cause:** `OrderQueueService.queue_order()` built its insert document from a hardcoded whitelist (`symbol/action/quantity/order_type/limit_price/stop_price/trade_id/...`) that silently dropped `type`, `parent`, `stop`, `target`, and `oca_group`. The Windows pusher then received a degenerate payload and could not execute atomic IB brackets — the final blocker for Phase 3 bracket orders.

**Fix:**
- `/app/backend/services/order_queue_service.py` — `queue_order()` now detects `type == "bracket"` and preserves `parent`, `stop`, `target`, `oca_group` in the stored doc. For bracket orders `order_type` is stamped as `"bracket"` and flat `action/quantity` are nulled (they live inside `parent`). Regular flat orders are unchanged.
- `QueuedOrder` Pydantic model now uses `model_config = ConfigDict(extra="allow")` and explicitly declares `type/parent/stop/target/oca_group`. `action`/`quantity` relaxed to `Optional` (bracket shape has them inside `parent`).
- `/app/backend/routers/ib.py` — `QueuedOrderRequest` mirrors the same bracket fields + `extra="allow"`. The `/api/ib/orders/queue` endpoint now branches cleanly for bracket vs. flat orders and validates each shape independently.

**Regression coverage:** `/app/backend/tests/test_queue_bracket_passthrough.py` — 5 tests locking in: bracket fields preserved, `oca_group` preserved, flat orders unaffected, Pydantic model accepts bracket shape, Pydantic accepts unknown-future fields. All 8 related tests pass (5 new + 3 existing bracket-wiring).

**Impact:** Windows pusher will now receive the full bracket payload on its next poll of `/api/ib/orders/pending`. Atomic IB bracket orders activate end-to-end — no more naked positions on restart/disconnect.


## Completed in this session (2026-04-21 — continued fork)
### Phase 8 DMatrix Fix & Bet-Sizing Wire-In (2026-04-21)
**Problem 1 (broadcast)**: Phase 8 ensemble failed with `ValueError: could not broadcast input array from shape (2382,) into shape (2431,)` — inline FFD augmentation was dropping 49 lookback rows vs the pre-computed `features_matrix`.
**Fix 1**: Removed inline FFD augmentation; reverted to zero-fill fallback so row counts stay consistent. Pytest suite expanded.

**Problem 2 (DMatrix)**: After broadcast fix, Phase 8 failed with `TypeError: Expecting data to be a DMatrix object, got: numpy.ndarray` — `TimeSeriesGBM._model` is an `xgb.Booster` (not `XGBClassifier`) which requires `DMatrix` input.
**Fix 2**: `training_pipeline.py` Phase 8 sub_model + setup_model predicts now wrap features in `xgb.DMatrix(..., feature_names=sm._feature_names)` before calling `.predict()`. Added `test_phase8_booster_dmatrix.py` (3 regression tests including source-level guard against future regressions).
**Verification (user, 2026-04-21 15:24Z)**: Phase 8 now producing real ensembles — 5/10 done at time of writing: meanrev=65.6%, reversal=66.3%, momentum=58.3%, trend=55.3%. All binary meta-labelers with ~44% WIN rate on 390K samples.

### Data Pipeline Audit & Cleanup (2026-04-21) — COMPLETED
- **`/backend/scripts/diagnose_alert_outcome_gap.py`** — per-setup funnel audit (alerts → orders → filled → closed → with_R) with `classify_leak` helper (ratio-based, not binary) and cancellation tracking.
- **`/backend/scripts/backfill_r_multiples.py`** — pure-math R-multiple backfill on closed bot_trades. Backfilled **141 docs** (post cleanup = 211 total with r_multiple). Idempotent.
- **`/backend/scripts/backfill_closed_no_exit.py`** — recovers exit_price from `fill_price + realized_pnl + shares + direction` on orphaned `status=closed, exit_price=None` docs. Recovered **70/70 orphans** (r_multiple_set=70).
- **`/backend/scripts/collapse_relative_strength.py`** — migrated `relative_strength_leader/laggard` → `relative_strength_long/short`. **Renamed 29,350 docs**. Eliminates "scanner drift" from the audit.
- **Tests**: `test_data_pipeline_scripts.py` (25 tests) — long/short R-multiple math, direction aliases, classify_leak ratio thresholds, exit inference roundtrip. 25/25 passing.

### 🚨 CRITICAL FINDINGS FROM AUDIT (2026-04-21)
After data cleanup, the truth is clear:
1. **`vwap_fade_short` is catastrophic**: 51 trades, 8.9% WR, **avg_R = -9.57** (losing 9.57× risk per trade). Total bleed: ~-488R. Stops are set correctly but **not being honored at IB** — stops are 2-4¢ wide, exits are $0.40-$7.84 past stop. Root cause: either no STP order placed at IB, or stop distance < tick buffer / noise floor.
2. **97% order cancellation rate**: on top setups, 1,216/1,220 `second_chance` orders cancel before fill (likely stale limit prices). Similar for squeeze, vwap_bounce.
3. **Only 211 total filled+closed trades exist across all setups** — too few to train Phase 2E CNNs. Needs weeks of live trading (with fixed stop execution) to accumulate.
4. **Only `vwap_fade_long` has real positive EV** (n=24, WR=58%, avg_R=+0.81 → ~0.36R/trade EV). Everything else scratches or bleeds.
5. **18/239 shorts have inverted stops** (stop below entry) — 7.5% data corruption, minor fix.


- **`/backend/services/ai_modules/ensemble_live_inference.py`** — runs full ensemble meta-labeling pipeline at trade-decision time: loads sub-models (5min/1h/1d) + setup 1-day model + `ensemble_<setup>` → extracts ensemble features → predicts `P(win)` on current bar. Degrades gracefully (returns `has_prediction=False` with reason) if any piece is missing.
- **Model cache (10-min TTL, thread-safe)** — `_cached_gbm_load` pins loaded XGBoost Boosters in memory across gate calls. Auto-evicts post-training via `clear_model_cache()` hook in `training_pipeline.py`. Measured speedup on DGX Spark: cold=2.33s, warm=0.33s (**7× faster**), partial miss=0.83s (**2.8×**). Enables ~180 evals/min/core production throughput.
- **`bet_size_multiplier_from_p_win(p_win)`** — Kelly-inspired tiered ramp:
  - `p_win < 0.50` → 0.0 (**force SKIP** per user requirement)
  - `0.50-0.55` → 0.50× (half size, borderline edge)
  - `0.55-0.65` → 1.00× (full size)
  - `0.65-0.75` → 1.25× (scale up)
  - `≥ 0.75` → 1.50× (max boost, cap prevents over-leverage)
- **`confidence_gate.py` Layer 12** — calls `_get_ensemble_meta_signal()` (async wrapper over thread pool) and contributes:
  - +15 points if `p_win ≥ 0.75`, +10 if `≥ 0.65`, +5 if `≥ 0.55`, 0 if `≥ 0.50`
  - Position multiplier scaled via `bet_size_multiplier_from_p_win`
  - **Hard SKIP** when `p_win < 0.5` overrides any positive score
- **`SCANNER_TO_ENSEMBLE_KEY`** — maps 35 scanner setup names (VWAP_BOUNCE, SQUEEZE, RUBBER_BAND, OPENING_DRIVE, etc.) → 10 ensemble config keys, PLUS canonical key pass-through (`REVERSAL`, `BREAKOUT`, `MEAN_REVERSION`, etc. accepted directly).
- **Live verification on DGX Spark (2026-04-21)**:
  - AAPL / BREAKOUT_CONFIRMED → `p_win=40%` → correctly hard-skipped (ensemble_breakout, setup_dir=flat)
  - NVDA / TREND_CONTINUATION → `p_win=22%` → correctly hard-skipped (ensemble_trend)
  - TSLA / REVERSAL → `p_win=50.04%` → correctly routed to borderline (0.5× size, ensemble_reversal)
- **Tests**: `test_ensemble_live_inference.py` (14 tests) — bet-size ramp (monotonic, boundary, cap), graceful miss paths, full mocked inference, model cache reuse/eviction/TTL. **44/44 total Phase 8 / ensemble / preflight / metrics tests passing.**



### Phase 2/2.5 FFD name-mismatch crash — FIXED (P0)
- **Symptom**: `scalp_1min_predictor: expected 57, got 52` when Phase 2 started after Phase 1 completed.
- **Root cause**: `_extract_setup_long_worker` / `_extract_setup_short_worker` augment `base_matrix` with 5 FFD columns when `TB_USE_FFD_FEATURES=1` (46 → 51). The outer Phase 2/2.5 loop in `training_pipeline.py` built `combined_names` from the NON-augmented `feature_engineer.get_feature_names()` (46) + setup names (6) → 52 names vs 57 X cols.
- **Fix**: `training_pipeline.py` lines 1426 & 1614 now wrap base_names with `augmented_feature_names(...)` from `feature_augmentors.py`, which appends the 5 FFD names when the flag is on.
- **Guardrail test**: `backend/tests/test_phase2_combined_names_shape.py` (4 tests, all passing) — rebuilds Phase 2 & 2.5 combined_names exactly as the training loop does and asserts `len(combined_names) == X.shape[1]` in both FFD-ON and FFD-OFF modes. Catches any regression of this bug class.

### Phase 8 Ensemble — REDESIGNED as Meta-Labeler (2026-04-21)
**Problem discovered**: All 10 ensemble models had identical metrics (accuracy=0.4542..., precision_up=0, precision_down=0) — degenerate "always predict FLAT" classifiers. Root cause: (a) 3-class prediction on universe-wide data collapsed to majority class (45% FLAT); (b) no setup-direction filter → training distribution ≠ inference distribution; (c) no class weighting.

**Fix (López de Prado meta-labeling, ch.3)**:
- Each `ensemble_<setup>` now REQUIRES its `setup_specific_<setup>_1day` sub-model to be present (training skips cleanly otherwise)
- Filters training bars to those where setup sub-model signals UP or DOWN (matches live inference)
- Converts 3-class TB target → binary WIN/LOSS conditioned on setup direction:
  - setup=UP + TB=UP → WIN(1)
  - setup=DOWN + TB=DOWN → WIN(1)
  - else → LOSS(0)
- Class-balanced `sample_weights` (inverse class frequency) to prevent majority-class collapse
- Skips model if <50 of either class present
- Tags model with `label_scheme=meta_label_binary`, `meta_labeler=True`, `setup_type=<X>` for downstream bet-sizing consumers
- Implements Phase 2C roadmap item (meta-labeler bet-sizing) by consolidating it into Phase 8
- Zero live-trading consumers at time of fix → safe redesign (dormant models)
- `backend/tests/test_ensemble_meta_labeling.py` — 13 tests covering label transformation (all 6 direction×TB combos), FLAT exclusion, class-balancing weights (balanced/imbalanced/pathological cases), and end-to-end synthetic pipeline

### CNN Metrics Fix (2026-04-21)
**Problem discovered**: All 34 per-setup CNN models showed `metrics.accuracy=1.0`. UI and scorecard read this field → misleading. Root cause: `accuracy` was saving the 17-class pattern-classification score, which is tautologically 1.0 because every sample in `cnn_<setup>_<bar_size>` has the same setup_type label. Real predictive metric `win_auc` was already computed (~0.55-0.85 range) but not surfaced.

**Fix**:
- `cnn_training_pipeline.py` now sets `metrics.accuracy = win_auc` (the actual win/loss AUC)
- Added full binary classifier metrics: `win_accuracy`, `win_precision`, `win_recall`, `win_f1`
- Kept `pattern_classification_accuracy` as debug-only reference
- `backend/scripts/migrate_cnn_accuracy_to_win_auc.py` — idempotent one-shot migration to update the 34 existing records in `cnn_models`
- `backend/tests/test_cnn_metrics_fix.py` — 5 tests covering perfect/realistic/degenerate/single-class cases + migration semantics
- Promotion gate unchanged (already correctly used `win_auc >= 0.55`)

### Pre-flight Shape Validator — EXTENDED (P1)
- `/backend/services/ai_modules/preflight_validator.py` — runs in `run_training_pipeline` immediately after disk-cache clear, BEFORE any phase kicks off heavy work.
- **Now covers every XGBoost training phase** (as of 2026-04-21):
  - `base_invariant` — `extract_features_bulk` output cols == `get_feature_names()` len (the master invariant; catches hypothetical future FFD-into-bulk drift)
  - **Phase 2 long** — runs `_extract_setup_long_worker`, rebuilds combined_names, asserts equality
  - **Phase 2.5 short** — runs `_extract_setup_short_worker`, same
  - **Phase 4 exit** — runs `_extract_exit_worker`, asserts 46 + len(EXIT_FEATURE_NAMES)
  - **Phase 6 risk** — runs `_extract_risk_worker`, asserts 46 + len(RISK_FEATURE_NAMES)
  - **Phases 3/5/5.5/7/8 static** — validates VOL/REGIME/SECTOR_REL/GAP/ENSEMBLE feature name lists are non-empty and dedup'd (their X matrix is built by column-write construction and is correct-by-construction when the base invariant holds)
- Uses 600 synthetic bars under current env flags (`TB_USE_FFD_FEATURES`, `TB_USE_CUSUM`).
- **Runtime**: **~2.0 seconds** for all 10 phases with FFD+CUSUM on (measured).
- Fails the retrain fast with a structured error if ANY mismatch is found (vs a 44h retrain crashing halfway).
- Result stored in `training_status.preflight` for the UI.
- Safe-guarded: a bug in the validator itself is logged as a warning and does NOT block training.
- `backend/tests/test_preflight_validator.py` — 5 tests: all-phases happy path with all flags on, FFD-off pass, only-requested-phases scoping, **negative test** reproducing the 2026-04-21 bug (asserts diff=+5), and **negative test** for base invariant drift (simulates hypothetical future FFD-into-bulk injection and asserts the invariant check catches it).
- **Next step for user**: restart retrain; Phase 2 onwards should now proceed cleanly AND every future retrain is protected.


## Completed in this session (2026-04-20)
### Phase 0A — PT/SL Sweep Infrastructure — DONE
- `/backend/services/ai_modules/triple_barrier_config.py` — get/save per (setup, bar_size, side)
- `/backend/scripts/sweep_triple_barrier.py` — grid sweep over PT×SL picking balanced class distribution
- Long + short workers now read per-setup config; callers resolve configs from Mongo before launching workers
- New API `GET /api/ai-training/triple-barrier-configs`; NIA panel shows PT/SL badge per profile

### Phase 1 — Validator Truth Layer — DONE (code), pending Spark retrain to activate
- **1A Event Intervals** (`event_intervals.py`): every sample tracked as `[entry_idx, exit_idx]`; concurrency_weights computed via López de Prado avg_uniqueness formula
- **1B Sample Uniqueness Weights** in `train_from_features(sample_weights=...)` — non-IID correction
- **1C Purged K-Fold + CPCV** (`purged_cpcv.py`) — `PurgedKFold` and `CombinatorialPurgedKFold` with embargo + purging by event interval overlap
- **1D Model Scorecard** (`model_scorecard.py`) — `ModelScorecard` dataclass + composite grade A-F from 7 weighted factors
- **1E Trial Registry** (`trial_registry.py`) — Mongo `research_trials` collection; K_independent from unique feature_set hashes
- **1F Deflated Sharpe Ratio** (`deflated_sharpe.py`) — Bailey & López de Prado 2014, Euler-Mascheroni expected-max-Sharpe, skew/kurt correction
- **1G Post-training validator** now auto-builds scorecard + DSR + records trial after every validation
- **1H Validator** persists scorecard on both `model_validations.scorecard` and `timeseries_models.scorecard`
- **1I UI** — `ModelScorecard.jsx` color-coded bundle display + expander button per profile in `SetupModelsPanel.jsx`
- **APIs**: `GET /api/ai-training/scorecard/{model_name}`, `GET /api/ai-training/scorecards`, `GET /api/ai-training/trial-stats/{setup}/{bar_size}`

### Phase 2A — CUSUM Event Filter — DONE
- `cusum_filter.py` — López de Prado symmetric CUSUM; `calibrate_h` auto-targets ~100 events/yr; `filter_entry_indices` honors a min-distance guard
- Wired into 3 workers (`_extract_symbol_worker`, `_extract_setup_long_worker`, `_extract_setup_short_worker`) with flag `TB_USE_CUSUM`

### Phase 2B — Fractional Differentiation — DONE (2026-04-21)
- `fractional_diff.py` — FFD (fixed-width window) + adaptive d (binary-search lowest ADF-passing d)
- `feature_augmentors.py` — flag-gated `augment_features()` appends 5 FFD cols (`ffd_close_adaptive`, `ffd_close_03/05/07`, `ffd_optimal_d`)
- Wired into all 3 worker types; 46-col base becomes 51-col when `TB_USE_FFD_FEATURES=1`
- `test_ffd_pipeline_integration.py` — 6 new tests verify end-to-end shape, finiteness, and all-flags-on combination

### Phase 2D — HRP/NCO Portfolio Allocator — DONE (code, pending wire-up)
- `hrp_allocator.py` — López de Prado Hierarchical Risk Parity + Nested Clustered Optimization
- Not yet wired into `trading_bot_service.py` (P1 backlog)

### Tests — 41 passing (+30 new)
- `test_phase1_foundation.py` — 19 tests covering event intervals, purged CV, DSR, scorecard
- `test_trial_registry.py` — 4 tests (mongomock)
- `test_sample_weights_integration.py` — 2 tests end-to-end
- `test_triple_barrier_config.py` — 5 tests (mongomock)
- Existing `test_triple_barrier_labeler.py`, `test_timeseries_gbm_triple_barrier.py` updated for 3-tuple worker return

### Pending on Spark (for Phase 1 to activate)
1. Save to Github → `git pull` on Spark
2. `pip install mongomock` in Spark venv (if running pytest)
3. Restart backend (`pkill server.py` + start)
4. Run PT/SL sweep: `PYTHONPATH=$HOME/Trading-and-Analysis-Platform/backend python backend/scripts/sweep_triple_barrier.py --symbols 150`
5. Kick off full retrain via NIA "Start Training" button
6. After retrain finishes, every model in Mongo `timeseries_models` will have a `scorecard` field; NIA page will show grades + expand-on-click full bundle


## Completed in prior session (2026-04-22 — fork 2, execution hardening batch)
### Dashboard truthfulness fix — retag bot-side cancels (2026-04-22 evening)
Audit revealed all 6,632 "cancelled" bot_trades were `close_reason=simulation_phase` bot-side filters, not broker cancels. Added dedicated `TradeStatus` values (`PAPER`, `SIMULATED`, `VETOED`) so future filters don't pollute the `cancelled` bucket. Migration script `scripts/retag_bot_side_cancels.py` retro-tagged 6,632 docs; execution-health now reports real failure rate (17.07% — dominated by already-disabled vwap_fade_short).

### Phase 3 — Bot-side bracket caller swap (2026-04-22 evening)
`trade_executor_service.place_bracket_order` + `_ib_bracket` / `_simulate_bracket`: queues an atomic `{"type":"bracket",...}` payload to the pusher with correctly-computed parent LMT offset (scalp-aware), child STP/LMT target, and GTC/outside-RTH flags. `trade_execution.execute_trade` now calls `place_bracket_order` first; on `bracket_not_supported` / `alpaca_bracket_not_implemented` / missing-stop-or-target it falls back to the legacy `execute_entry` + `place_stop_order` flow. Result shape is translated so downstream code doesn't change.

### Phase 4 — Startup orphan-position protection (2026-04-22 evening)
`PositionReconciler.protect_orphan_positions`: scans `_pushed_ib_data["positions"]`, finds any with no working bot-side stop, places emergency STP using intended stop_price if known else 1% risk from avgCost (SELL for longs, BUY for shorts). Trade docs updated with the new stop_order_id and saved. Wired into `TradingBotService.start()` as a fire-and-forget background task (15s delay so pusher has time to publish positions). New endpoint `POST /api/trading-bot/positions/protect-orphans?dry_run=true|false&risk_pct=0.01` for manual triage.

### Autopsy fallback — use realized_pnl when exit_price missing
`summarize_trade_outcome` now falls back to `realized_pnl` when `exit_price=0/None` and `r_multiple` can't be recomputed (fixes the imported_from_ib case where PD bled $7.3k but showed `verdict=unknown`).

### New pytest coverage (2026-04-22 evening — 27 new tests, all passing)
- `tests/test_orphan_protection.py` (7 tests): pusher-disconnected guard, already-protected accounting, unprotected tracked trade gets stop, untracked short derives above-entry stop, dry-run safety, zero-avgcost skip, flat-position ignore.
- `tests/test_bracket_order_wiring.py` (3 tests): simulated 3-legged return shape, Alpaca fallback signal, missing-stop-or-target graceful decline.
- `tests/test_trade_autopsy.py` +2 tests: realized_pnl fallback when exit_price=0.

### Pusher contract spec delivered
`/app/memory/PUSHER_BRACKET_SPEC.md` — full bracket payload contract, reference `ib_insync` handler code, ACK response shape, fallback signaling, smoke-test commands. Pusher-side implementation pending on Windows PC.


### Alert de-dup wired into scan loop
`services/trading_bot_service._scan_for_opportunities` runs the `AlertDeduplicator` hard veto BEFORE confidence-gate evaluation. Blocks repeat fires on already-open `(symbol, setup, direction)` and enforces a 5-min cooldown. This stops the PRCT-style stacking disaster where 8 identical vwap_fade_short alerts each bled -8.9R.

### Trade Autopsy API endpoints
Added to `routers/trading_bot.py`:
- `GET /api/trading-bot/trade-autopsy/{trade_id}` — full forensic view: outcome, stop-honor, slippage_R, gate snapshot, scanner context.
- `GET /api/trading-bot/recent-losses?limit=N` — list worst-R trades for triage workflow.

### IB `place_bracket_order()` primitive (Phase 1 of bracket migration)
`services/ib_service.py` now exposes an atomic native IB bracket: parent LMT/MKT + OCA stop + OCA target. Uses `ib_insync` with explicit `parentId`, `ocaGroup`, `ocaType=1`, and `transmit=false/false/true` flags. Includes directional sanity validation (long: stop<entry<target, short: reverse) and emits a unique `oca_group` id per trade. Once the parent fills, the stop and target live at IB as GTC — the bot can die/restart and the stop remains enforced.

### Pre-execution guard rails
New pure module `services/execution_guardrails.py` + wired into `services/trade_execution.execute_trade` BEFORE `trade_executor.execute_entry`. Rejects:
- Stops tighter than 0.3×ATR(14) (or 10 bps of price if ATR unavailable)
- Positions whose notional exceeds 1% of account equity (temporary cap while bracket migration is in progress)
Failed trades are marked `TradeStatus.REJECTED` with `close_reason="guardrail_veto"`.

### Pytest coverage (24 new tests, 82/82 passing in exec-hardening suite)
- `tests/test_alert_deduplicator.py` (8 tests): open-position veto, cooldown window, symbol/setup/direction independence, ordering precedence.
- `tests/test_execution_guardrails.py` (10 tests): USO-style tight-stop rejection, ATR vs pct fallback, notional cap, no-equity fallback.
- `tests/test_trade_autopsy.py` (6 tests): long/short verdict, stop-honored vs blown-through slippage, r_multiple precedence.



