# SentCom Codebase Audit & Refactor Roadmap

**Date**: 2026-05-02 (post-v19.30.1 wedge fix)
**Status**: Discovery complete, strategy proposed. **No code changes yet** — all
findings below are read-only observations + recommendations.
**Audience**: SentCom operator (you) + future fork agents.

---

## TL;DR — What the audit found

| Metric | Value | Notes |
|---|---|---|
| Total backend LOC | **208,694** | Across `routers/` + `services/` + `server.py` |
| Files >2,000 LOC | **13** | `enhanced_scanner.py` 7,090 | `ib.py` 6,242 | `server.py` 4,643 |
| Frontend LOC (JSX) | ~85k | `AdvancedBacktestPanel.jsx` 2,754 LOC tops the list |
| Routers files | **82** | All wired into `server.py` (no orphans there) |
| Service files | **163** | 6 likely orphaned (no import sites) |
| Test files | **289** | Only **31** versioned (v19) — rest are pre-versioning |
| Distinct Mongo collections written | **38** | Modest fanout, well-isolated |
| Background tasks at startup | **27** | Centralised in `server.py` lifecycle |
| Ruff lint errors | **1,119** | 370 auto-fixable, 463 hidden (unsafe-fix) |
| Bare `except:` (E722) | **61** | Silent error swallowing — risky |
| Sync `def` route handlers in hot routers | **141** | Top: ib.py 43, ai_modules.py 37, ib_collector_router.py 32 |
| Inline sync mongo in async routes | **54** | Wedge follow-up class — top: sentcom_chart.py 11, ib_collector_router.py 11 |
| Duplicate function names per file | **3** in `ib.py` | `get_pushed_ib_data`, `get_fundamentals`, `get_account_summary` (one source-shadow bug already cost us today) |
| `v19.x` markers in code comments | **194** | Operator's time-machine — opportunity to consolidate context |
| Alpaca fallback references | **32 files** | Roadmap says "safely retire" — large blast radius |
| Hardcoded `localhost:8001` | **18** | Should be env-var |
| Lazy `import server` (back-imports) | **3 files** | Circular-smell, currently fine but fragile |

**Bottom line**: The codebase is **functionally healthy and tests pass** (120/120
on v19 stack), but it's accumulated 6+ months of "ship-the-feature, leave-the-old-
code" sediment. The wedge bug we just fixed is exactly the kind of issue that
emerges when sync/async lines blur. **This audit identifies 6 surgical
refactor passes that — done in order — would produce a leaner, faster,
more resilient bot without breaking a single live behaviour.**

---

## The 6-pass refactor strategy

Each pass is **independent + reversible** + has a **measurable success metric**.
You can ship each one across multiple sessions; nothing here requires a "big
bang" rewrite.

### Pass 1 — 🟢 SAFE: Lint + dead-code sweep (1 session, ~2h)

**Goal**: Drop ruff error count from 1,119 → <100. Pure cleanup, zero
behavioural change.

**Targets**:
- `ruff --fix` for the 370 auto-fixable errors (unused vars, unused imports,
  f-string-without-placeholder, single-line-statements). Gated by full v19
  test suite green.
- 61 bare `except:` → `except Exception:` (preserves behaviour, makes
  `KeyboardInterrupt` actually work).
- Delete the 6 likely-orphaned services (`advanced_targets.py`,
  `training_subprocess.py`, `catalyst_aware_carry_forward.py`,
  `live_health_monitor.py`, `multiplier_threshold_optimizer_v2.py`,
  `worker.py`) — verify no imports first.
- Resolve 3 duplicate function names in `ib.py` (`get_pushed_ib_data`,
  `get_fundamentals`, `get_account_summary`) — rename helpers with
  `_internal` suffix. **This was the cause of the route-shadow bug today.**
- 3 unused-local fixes (`F841`) flagged by ruff in routers.
- Replace 18 hardcoded `localhost:8001` URLs with env vars.

**Risk**: ⚪ very low. Ruff `--fix` is conservative; `ruff --unsafe-fixes`
is OFF by default. Run full test suite after.

**Success metric**: `ruff check .` reports <100 errors. Test pass rate
unchanged at 120/120 v19 stack.

---

### Pass 2 — 🟡 MEDIUM: Async-pymongo migration (2-3 sessions)

**Goal**: Eliminate the entire class of "wedge bugs" we hit today. Make
the FastAPI loop bulletproof under push-storm load.

This is the **direct continuation** of v19.30.1 — finish what we started.

**Targets** (in priority order):

#### 2a. Top 5 hot async routes with inline sync mongo (~10 endpoints)
| File | Inline sync mongo | Hottest endpoint |
|---|---|---|
| `routers/sentcom_chart.py` | 11 | Polled by V5 chart panel ~1×/sec |
| `routers/ib_collector_router.py` | 11 | Pusher polls historical data results |
| `routers/ib.py` | 8 | Order queue + pusher comms |
| `routers/ai_training.py` | 5 | Operator dashboard polls every 5s |
| `routers/ai_modules.py` | 3 | Confidence gate + module status |

Wrap every `find_one`/`update_one`/`aggregate` in `asyncio.to_thread`. Pattern
already proven in v19.30.1 push-data fix.

#### 2b. Top 5 sync `def` handlers in hot routers (~141 total — start with the polled ones)
- `routers/ib.py`: 43 sync handlers — focus on order queue endpoints first
  (pusher polls `/api/ib/orders/pending` every ~1s)
- `routers/ai_modules.py`: 37 — focus on `/training-status` + `/regime-live`
  (V5 dashboard polls every 5s)
- `routers/ib_collector_router.py`: 32 — focus on `/system-health`,
  `/data-coverage` (operator dashboard polls every 10s)
- `routers/live_scanner.py`: 20 — focus on `/live-alerts` (V5 polls every
  5s during RTH)
- `routers/trading_bot.py`: 28 — focus on `/status`, `/risk-snapshot`

**Convert to `async def`** if body is in-memory only; **keep `def` + add a
performance budget assertion** if body is heavy DB-only.

#### 2c. Add `EVENT_LOOP_GUARD` decorator
A reusable `@event_loop_safe` decorator that:
1. Times the handler body
2. Logs a CRITICAL stream event if any handler exceeds 200ms
3. Returns 503 + Retry-After if a per-route concurrency cap is exceeded

This generalises the v19.30.1 push-data backpressure pattern to every hot
endpoint. Operator gets early-warning observability for free.

**Risk**: 🟡 medium. Each file change is small and locally testable, but
the volume is high (~15 files, ~80 conversions). Mitigate by:
- Doing one router per session
- Adding a pytest for each converted endpoint that pins the contract
- Live-watching the new `event_loop_p99_ms` metric

**Success metric**:
- Zero inline sync mongo in async routes (audit script returns 0)
- p99 event-loop block during push storm <100ms (today's stress test
  showed 24ms; goal: keep it sub-50ms with full pusher load)
- Backpressure 503 surface area extends from 1 endpoint to ~5 hot ones

---

### Pass 3 — 🟡 MEDIUM: Break up the four monoliths (3-4 sessions)

**Goal**: Make the codebase navigable. Right now grepping `ib.py` is a
6,242-line scroll.

**Targets**:

#### 3a. `routers/ib.py` (6,242 LOC) → split into 6 sub-routers
Already partly done — `routers/ib_modules/` exists but only has a few
files. Finish the split:
- `routers/ib/connection.py` — connect/disconnect, status, health (~600 LOC)
- `routers/ib/quotes.py` — push-data, pushed-data, level2, fundamentals (~800 LOC)
- `routers/ib/orders.py` — order queue, claim, report, dead-letter (~1,200 LOC)
- `routers/ib/historical.py` — historical bar fetch + collector comms (~1,000 LOC)
- `routers/ib/news.py` — news, news_providers, news subscriptions (~400 LOC)
- `routers/ib/diagnostics.py` — pusher-health, RPC stats, debug endpoints (~800 LOC)
- `routers/ib/__init__.py` — single APIRouter that includes all sub-routers,
  preserves the `/api/ib/*` URL surface (zero frontend break)

#### 3b. `services/enhanced_scanner.py` (7,090 LOC) → split by responsibility
- `services/scanner/setups.py` — Bellafiore setup detection (~2,000 LOC)
- `services/scanner/regime_filter.py` — regime gating (~800 LOC)
- `services/scanner/ranker.py` — scoring + tiering (~1,500 LOC)
- `services/scanner/output_pipeline.py` — alert formatting + ML feature
  vector emission (~1,500 LOC)
- `services/scanner/__init__.py` — orchestrator (~1,000 LOC, the existing
  `run_scan` flow that calls into the above)

#### 3c. `server.py` (4,643 LOC) → bootloader-only
Move out (in this order, lowest risk first):
- All 17 `stream_*` async loops → `services/streaming/loops.py` (~800 LOC)
- `_streaming_cache_loop` + `_compute_all_sync_data` → `services/streaming/cache.py` (~400 LOC)
- 6 schedulers (perf, market_intel, EOD, trading, sentiment, weekly_adv)
  → `services/scheduling/orchestrator.py` (~600 LOC)
- `_init_all_services` → `services/bootstrap.py` (~500 LOC)
- After: `server.py` becomes <1,500 LOC, mostly app definition + lifespan +
  middleware. Easy to reason about.

#### 3d. `services/ai_assistant_service.py` (3,848 LOC) — defer to Pass 6
Lower priority because it's not a wedge risk and the AI assistant is mid-
flight. Revisit after the live-data plumbing is calm.

**Risk**: 🟡 medium. URL surfaces stay identical. Risk is in import-cycle
discovery during the split. Mitigate by:
- One file split per session (with full test run between)
- Use `git mv` to preserve git blame history
- Keep `__init__.py` re-exports for any symbol another module imports

**Success metric**:
- No file in `routers/` exceeds 1,500 LOC
- No file in `services/` exceeds 2,500 LOC
- All 120/120 v19 tests pass after each split
- Git blame still works (`git mv` preserves it)

---

### Pass 4 — 🟢 SAFE: Test suite consolidation (1 session)

**Goal**: Make pytest meaningful again. Right now 289 test files but
only 31 are versioned (`v19.x`), the rest are pre-versioning era and
likely cover removed/renamed behaviour.

**Targets**:
- Run `pytest tests/ --collect-only -q` and identify tests that error on
  collection (missing imports, removed services). Currently 3 fail to
  collect (we hit them today).
- Triage the **258 unversioned tests** into 3 buckets:
  - **KEEP** (still meaningful regression — versionise them: `tests/test_*_pinned.py`)
  - **DELETE** (cover removed/replaced behaviour — git rm)
  - **MIGRATE** (cover behaviour that moved to a new module — update imports)
- Add `pytest.ini` markers: `@pytest.mark.smoke`, `@pytest.mark.contract`,
  `@pytest.mark.integration`, `@pytest.mark.slow`. Today everything
  runs in one bag.
- Add a `tests/conftest.py` that pre-imports `server` once per session
  so tests don't pay the 2.8s import cost individually (we just hit
  this in v19.30.1 testing).

**Risk**: ⚪ very low. Tests that delete are tests that didn't run anyway.

**Success metric**:
- `pytest tests/ --collect-only` reports zero collection errors
- Smoke marker runs in <30s (vs current ~5min for full suite)
- Versioned test count climbs from 31 → ~150

---

### Pass 5 — 🟢 SAFE: Deprecation hygiene (1 session)

**Goal**: Stop carrying dead/legacy code paths.

**Targets**:

#### 5a. The 194 `v19.x` markers
These are operator-pinned change-context comments (great when fresh, noise
once 6 months old). Strategy:
- Keep the **last 5 versions** (v19.26+) inline as living-context comments
- Archive older markers (v19.0 - v19.25) into `memory/CHANGELOG.md`
  (already exists) and remove the inline comments
- **Net effect**: clean code surface, full history preserved in one
  searchable file

#### 5b. Alpaca fallback (32 files reference)
The roadmap says "safely retire Alpaca". Recommended approach:
- Audit each of the 32 reference sites — flag which paths actually
  execute (live RTH never hits Alpaca because IB-only law)
- Add a feature flag `USE_ALPACA_FALLBACK = False` (default off)
- After 1 week of observability with flag off → delete the entire
  `services/alpaca_service.py` + 32 reference cleanups
- **Saves**: ~3,000 LOC + reduces cognitive surface

#### 5c. `services/market_simulator_service.py` + `services/simulation_engine.py`
Two files with similar names — merge or delete the unused one. They were
flagged in the v19.30 work as event-loop blockers; understand what each
actually does today.

#### 5d. Remove the 6 orphaned services already identified
After verification:
- `services/ai_modules/advanced_targets.py`
- `services/ai_modules/training_subprocess.py`
- `services/catalyst_aware_carry_forward.py`
- `services/live_health_monitor.py`
- `services/multiplier_threshold_optimizer_v2.py` (note the `_v2` —
  there's likely a v1 still in use; verify)
- `worker.py` (probably superseded by supervisor + nohup pattern)

**Risk**: ⚪ low for deletions (verified orphans), 🟡 medium for Alpaca
retirement (touches 32 files). Use feature flag, not flag-day.

**Success metric**:
- ~5,000-7,000 LOC removed
- Reference sites for Alpaca → 0
- Inline `v19.<old>` comments → fewer than 50

---

### Pass 6 — 🟡 MEDIUM: Data-flow architecture consolidation (2 sessions)

**Goal**: One canonical path for each kind of data. Today we have multiple
caches + multiple writers to the same Mongo collections.

**Findings from the audit**:
- 4 cache layers: `chart_response_cache.py`, `data_cache.py`,
  `live_bar_cache.py`, `_streaming_cache` (in-memory dict in server.py)
- Some collections have multiple writers (`ib_live_snapshot` has 2 writers
  across 2 files; `training_pipeline_status` same; `symbol_adv_cache`
  same; `timeseries_models` same; `training_runs_archive` same)
- 17 individual `stream_*` async tasks each maintaining their own slice
  of the cache

**Recommended consolidation**:

#### 6a. One cache, multiple views
Merge the 4 cache layers into a single `services/cache_service.py` with
typed accessors:
- `cache.chart.get(symbol, timeframe)` / `cache.chart.set(...)`
- `cache.bars.get(symbol, timeframe)` / `cache.bars.set(...)`
- `cache.stream.get(channel)` / `cache.stream.set(...)`

Backed by either in-memory dict (current) or Redis (future P2 upgrade
once we want cross-process cache for chat_server).

#### 6b. One writer per collection
For collections with multiple writers (`ib_live_snapshot`, etc.):
- Define a single `services/persistence/<collection>_repository.py`
- Every other module calls the repo, never writes raw mongo
- Repo enforces invariants (timestamp UTC, no `_id` in response,
  upsert idempotency)

#### 6c. Streaming bus consolidation
The 17 `stream_*` loops in server.py each do their own polling +
WebSocket fanout. Replace with:
- A single `EventBus` (in-memory pub/sub) — services emit events,
  WebSocket fanout consumers subscribe
- Each `stream_*` loop becomes a 1-line subscriber, not a polling loop
- Reduces tick latency (event-driven vs 1-5s poll cycles)

**Risk**: 🟡 medium. This is the most invasive pass. Save for last.
Mitigate by:
- Keep old code paths alive behind feature flag during migration
- Migrate one cache type at a time (charts → bars → stream)
- Keep the public WebSocket surface identical so frontend doesn't break

**Success metric**:
- One canonical cache module, 4 typed namespaces
- Each Mongo collection has exactly 1 writer module
- Stream tick latency drops from 1-5s to <100ms (event-driven)

---

## Suggested execution order + estimated effort

| Pass | Sessions | Risk | LOC delta | Why this order |
|---|---|---|---|---|
| **1** Lint + dead-code | 1 | ⚪ | -2k | Cleanup baseline. Makes diffs in Pass 2-6 readable. |
| **2** Async-pymongo | 2-3 | 🟡 | +500 | Eliminates wedge class. Critical for live trading stability. |
| **4** Test consolidation | 1 | ⚪ | -3k | Need green tests before bigger refactors. |
| **5** Deprecation | 1 | 🟢 | -5k | Easier to refactor less code. |
| **3** Monolith splits | 3-4 | 🟡 | 0 | Tackle once smaller surface (post 5) is in. |
| **6** Data-flow consolidation | 2 | 🟡 | -1k | Most invasive — save for last. |

**Total**: ~11 sessions across the 6 passes. Each pass shippable
independently with green tests. **Net LOC removal**: ~10-15k LOC.
**Net cognitive load reduction**: significant (no file >1,500 LOC,
single canonical path for each data flow).

---

## What NOT to do (anti-patterns I'd avoid)

1. **Don't "modernise" what isn't broken**. The IB-only data law, the
   soft-gating-only-for-regimes law, and the OCA bracket order pattern
   are *load-bearing* and tested in production. Refactor around them,
   not through them.
2. **Don't migrate to async ORM (Motor/Beanie)**. We tested this trade-off:
   `pymongo` + `asyncio.to_thread` performs identically and keeps the
   sync paths (Mongo upserts in background workers, scripts) working
   without a parallel API. Sticking with pymongo is correct.
3. **Don't introduce a microservices split**. The chat_server on :8002
   is the only service split, and it works. More splits = more network
   hops = more wedge surface. Stay monolithic.
4. **Don't delete `server.py` import-time hot-paths** (e.g.,
   `_kill_orphan_processes()`). They protect against zombie processes
   wedging the bot — even though they look like noise.
5. **Don't reformat with black/isort wholesale** until Pass 1 is done.
   You'll lose git blame on every file you touch. Format incrementally
   inside the same commit as the actual change.

---

## Operator decision points (for next session)

When you start the next session, pick ONE of:

- **🟢 (cheapest, safest)**: "Do Pass 1 — lint sweep + dead-code removal."
  Visible-result-per-effort highest. ~2h. Drops error count 90%.
- **🟡 (highest value)**: "Continue v19.30.1 with Pass 2a — eliminate
  inline sync mongo in async routes." This is what we're already on.
  Direct continuation of today's wedge fix.
- **🔴 (operationally urgent)**: "Skip the audit and ship the P0
  Diagnostics + Pre-open Order Purge endpoints first." Audit can wait
  for a quiet weekend; live RTH stability comes first.

I'd recommend the 🔴 path for *now* (P0s have business impact today),
then schedule a "refactor weekend" for Pass 1 + Pass 2 in one block.
The codebase will outlive any single feature; cleanup compounds.
