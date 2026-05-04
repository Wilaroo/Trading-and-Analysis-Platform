# TradeCommand / SentCom — Roadmap & Backlog

Open priorities, deferred ideas, and backlog. Move items to
`CHANGELOG.md` once shipped; promote/demote priority by reordering.


## 🔴 Now / Near-term (next session pickup — 2026-05-04 v19.34.4)

### 🎯 Just shipped 2026-05-04 v19.34.4 — see CHANGELOG (eighty-fifth commit)
**IB fill-tape auditor + Spark Mongo cross-check + 2026-05-04 audit run.**

- ✅ `backend/scripts/audit_ib_fill_tape.py` — TWS-paste parser + FIFO PnL + verdict classifier (`CARRYOVER_FLATTENED` / `OPEN_POSITION_LONG` / `MULTI_LEG_*` / `INVERSION_SHORT_COVER` / `CLEAN_ROUND_TRIP`).
- ✅ `backend/scripts/export_bot_trades_for_audit.py` — Spark Mongo export (today's `bot_trades` rows with full v19.34.3 provenance fields).
- ✅ `memory/runbooks/audit_ib_fill_tape.md` — 5-phase operator runbook.
- ✅ 2026-05-04 audit complete: **328 fills / 21 symbols / -$14,560 net** PAPER day. Single residual `STX -17sh` flagged as carryover.
- ✅ **15/15 new pytests passing**, **256/256 cumulative across all v19.x suites**.

### 🔴 P0 — Top of next session (operator-driven, requires Spark access)

**Step 1 — Spark cross-check the 2026-05-04 audit:**
```bash
cd ~/Trading-and-Analysis-Platform/backend
python -m scripts.export_bot_trades_for_audit --date 2026-05-04 --out /tmp/bt_2026_05_04.json
python -m scripts.audit_ib_fill_tape \
    --input ../memory/audit/2026-05-04_ib_fill_tape.txt \
    --bot-trades-json /tmp/bt_2026_05_04.json \
    --out /tmp/audit_2026_05_04_with_xcheck.md
```
- **Investigate the STX -17sh carryover** — confirm via `/api/diagnostics/orphan-origin/STX?days=7` whether the bot ever owned those 17 shares or they were a manual click / prior session that the morning reset didn't close.
- **VALE confirmation** — the audit flags VALE as `MULTI_LEG_LONG` with -$1,528 realized; verify v19.34.3's `prior_verdict_conflict` flag on the matching `bot_trades` row (operator's previous bug).
- **Spot-check fragmentation** on BKNG (87 fills) and V (46 fills) — confirm bot has 1 row per parent order, not 1 row per venue child fill.

### 🔴 P0 — MID_BAR_TICK_EVAL activation (carry-over from v19.34)
Per `/app/memory/runbooks/midbar_tick_eval_activation.md`:
1. `curl ${BACKEND_URL}/api/ib/quote-tick-bus/health` — confirm `enabled=true`, `publish_total > 0`, `drop_total ≈ 0` for 30 min during RTH.
2. Flip `MID_BAR_TICK_EVAL_ENABLED=true` in `.env` and restart.
3. Verify `[v19.34 MID-BAR TICK]` subscriber-spawn logs and `mid_bar_v19_34` close-reason stamping in Day Tape on next stop hit.

### 🔴 P0 — Carry-over verifications (still pending operator confirmation)

- (v19.31.13) AccountModeBadge correctness on paper vs live accounts.
- (v19.31.13) Realized PnL auto-syncs within 30s without operator clicks.
- (v19.31.13) Diagnostics → Shadow Decisions tab loads cleanly.
- (v19.31.13) PAPER/LIVE chips render on Open Positions / Day Tape / Forensics.
- (v19.31.14) Pre-Market banner appears 7:00-9:30 ET in scanner panel.
- (v19.31.14) `/api/ib-collector/throttle-policy` returns `max_concurrent_workers=1` during RTH.
- (v19.31.14) BootReconcilePill appears in HUD after backend restart, fades after 10 min.
- (v19.31.14) Module Vote Breakdown panel renders below Module Scorecard.
- (v19.31.14) Funnel `⚠ Shadow drift` chip appears when shadow ≠ trades.
- (v19.32) Chart click on a recently-visible scanner symbol lands in <50ms (was ~400ms cold).
- (v19.33) Chart header shows cyan **"live"** pip when on a focused intraday chart during RTH.
- (v19.34.3) RECONCILED + ⚠ CONFLICT chips render on V5 Open Positions row when applicable.

### 🟡 P1 (operator-facing improvements, carried forward)
- Frontend L1 tick rendering with RAF-coalescing on `/ws/quote-ticks` (deferred from v19.33).
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over).
- Pusher honors `max_concurrent_workers` from `/api/ib-collector/throttle-policy`.

### 🟢 P2 / P3 (future evolution paths now unlocked by v19.34)
- **Stop-distance journal → ML training data** (operator-suggested 2026-05-04) — pipe `tick_evaluated` annotations into `sentcom_thoughts` on every mid-bar eval. After a week, microsecond-resolution journal of every stop's distance-to-fire — perfect training data for a "predict stop-run probability before the wick fires" ML module.
- **Sub-bar trailing stops** — once mid-bar is proven safe.
- **Mid-bar entry eval** — selectively front-run entries on high-conviction signals.
- **L1 → L2 escalation** — request L2 depth via the tick bus for actively-evaluated symbols.
- **Audit Pass 1**: lint sweep + dead-code (370 ruff fixes).
- **Audit Pass 3**: break up 4 monoliths.
- v19.32 evolution — predictive warmer that pre-fetches the chart for the symbol an alert is about to fire on.
- v19.33 evolution — WS pushes per-tick L1 quote updates.
- Setup-landscape EOD self-grading tracker.
- Mean-reversion metrics service (per-symbol Hurst exponent + Ornstein-Uhlenbeck half-life).
- Liquidity-aware trail in `stop_manager.py`.
- IB Gateway auto-login resilience.
- Safely retire Alpaca fallback.

---

## 🔴 Now / Near-term (next session pickup — 2026-05-04 v19.34)

### 🎯 Just shipped 2026-05-04 v19.34 — see CHANGELOG (eighty-first commit)
**L1 tick bus + mid-bar stop eval. Three phases. Bus + bridge always on; manage-loop consumer defaulted OFF for explicit operator opt-in.**

- ✅ **Phase 1 — `services/quote_tick_bus.py`** — in-memory pub/sub with latest-N drop, per-subscriber `asyncio.Queue(8)`, drop counters, `bus.stream()` async-generator helper.
- ✅ **Phase 2 — Pusher → bus bridge** — `routers/ib.py:receive_pushed_ib_data` publishes every quote update. New `GET /api/ib/quote-tick-bus/health` for monitoring.
- ✅ **Phase 3 — Mid-bar stop eval** — `PositionManager.evaluate_single_trade_against_quote` mirrors bid/ask-aware stop-trigger logic but per-trade per-tick (~50ms cadence). Lifecycle reaper in `TradingBotService.start()` walks `_open_trades` every 2s and reconciles subscribers. Close reason stamped `stop_loss_mid_bar_v19_34`. Defaulted OFF via `MID_BAR_TICK_EVAL_ENABLED`.
- ✅ **Operator playbook** — `memory/runbooks/midbar_tick_eval_activation.md` with pre-flight checklist (30min bus health on RTH), activation steps, verification, rollback (single env-var flip), and red-flag monitoring.
- ✅ **208/208 v19.31.x + v19.23.x + v19.32 + v19.33 + v19.34 pytests passing.**

### 🔴 P0 — Top of next session (operator-driven activation path)

**Step 1 (today, RTH window) — Validate bus health:**
1. `curl ${BACKEND_URL}/api/ib/quote-tick-bus/health` — confirm `enabled=true`, `publish_total > 0` and growing, `drop_total ≈ 0`, `active_symbols=0` (no consumers yet).
2. Re-check after 30min of RTH. Drop rate should still be 0.

**Step 2 (after Step 1 passes) — Flip Phase 3 ON:**
1. `echo "MID_BAR_TICK_EVAL_ENABLED=true" >> /app/backend/.env && sudo supervisorctl restart backend`.
2. Within 5s of an open trade, look for `[v19.34 MID-BAR TICK] +sub trade_id=...` in logs.
3. Health endpoint should now show `active_symbols ≥ #(open trades)`.
4. On any stop-hit during the session, look for `[v19.34 MID-BAR STOP]` warning + a `mid_bar_v19_34` close reason in Day Tape / Forensics.

**Step 3 — Verification of saved latency:**
- Compare Day Tape `mid_bar_v19_34` rows vs equivalent bar-close stops on prior days. Mid-bar fires should land within ~0-2s of the trigger crossing; bar-close fires were typically 5-30s.

**ROLLBACK if anything goes wrong:**
- `sed -i 's/MID_BAR_TICK_EVAL_ENABLED=true/MID_BAR_TICK_EVAL_ENABLED=false/' /app/backend/.env && sudo supervisorctl restart backend`. Bot reverts to v19.33 behavior immediately.

**ALSO verify existing v19.31.13 + v19.31.14 + v19.32 + v19.33 features** (12-point checklist preserved below).

### 🔴 P0 — Verification carry-over from prior sessions

- (v19.31.13) AccountModeBadge correctness on paper vs live accounts.
- (v19.31.13) Realized PnL auto-syncs within 30s without operator clicks.
- (v19.31.13) Diagnostics → Shadow Decisions tab loads cleanly.
- (v19.31.13) PAPER/LIVE chips render on Open Positions / Day Tape / Forensics.
- (v19.31.14) Pre-Market banner appears 7:00-9:30 ET in scanner panel.
- (v19.31.14) `/api/ib-collector/throttle-policy` returns `max_concurrent_workers=1` during RTH.
- (v19.31.14) BootReconcilePill appears in HUD after backend restart, fades after 10 min.
- (v19.31.14) Module Vote Breakdown panel renders below Module Scorecard.
- (v19.31.14) Funnel `⚠ Shadow drift` chip appears when shadow ≠ trades.
- (v19.32) Chart click on a recently-visible scanner symbol lands in <50ms (was ~400ms cold).
- (v19.33) Chart header shows cyan **"live"** pip when on a focused intraday chart during RTH.
- (v19.33) Auto-fallback test: temporarily set `CHART_WS_ENABLED=false` → confirm chart switches to "poll" pip + still updates via REST.

### 🟡 P1 (operator-facing improvements, carried forward)
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over).
- **Pusher honors `max_concurrent_workers`** — current Windows pusher reads `/api/ib-collector/throttle-policy` and parks N-1 of its 4 workers.

### 🟢 P2 / P3 (future evolution paths now unlocked by v19.34)
- **Stop-distance journal → ML training data** *(operator-suggested 2026-05-04, captured from v19.34 finish summary)* — pipe a tiny `tick_evaluated` annotation into `sentcom_thoughts` on every mid-bar eval, e.g. `"AAPL: bid 148.42 vs stop 148.50 (-8c safety margin) at 09:33:14"`. After a week, you'd have a microsecond-resolution journal of every stop's distance-to-fire across every open trade — perfect training data for an AI module that learns to predict stop-run probability **before** the wick actually fires. Implementation notes:
  - Throttle the writer (1 sample/sec/trade max) so we don't drown `sentcom_thoughts` — the existing TTL=7d is fine.
  - Add a new `kind: "stop_distance_sample"` so it's filterable from the operator-facing thought stream.
  - Stamp `bid/ask/last/effective_stop/distance_pct/seconds_until_fire` so the trainer has both the live state and (computed at fire-time, in a later batch job) the eventual outcome label.
  - Train a small classifier (XGBoost or a 2-layer MLP) on `(distance, recent volatility, time-of-day, regime)` → `P(stop hit within next N seconds)`. Wire prediction back into the AI council's "should we tighten the stop?" decision.
- **Sub-bar trailing stops** — once mid-bar stop eval is proven safe, extend to per-tick trailing recalc. Needs careful smoothing to avoid noise-driven exits.
- **Mid-bar entry eval** — currently entries wait for bar-close to avoid wicks. Could selectively front-run entries on high-conviction signals using the same tick bus.
- **L1 → L2 escalation** — for actively-evaluated symbols, request L2 depth via the tick bus to spot stop-runs before they fire.
- v19.32 evolution — predictive warmer that pre-fetches the chart for the symbol an alert is about to fire on.
- v19.33 evolution — WS pushes per-tick L1 quote updates, not just per-bar updates. Latency floor would drop to ~50ms but needs server-side dedup tuning.
- Setup-landscape EOD self-grading tracker.
- Mean-reversion metrics service (per-symbol Hurst exponent + Ornstein-Uhlenbeck half-life).
- Liquidity-aware trail in `stop_manager.py`.
- IB Gateway auto-login resilience
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths

### 🎯 Just shipped 2026-05-04 v19.31.3 — see CHANGELOG (sixty-ninth commit)
**System banner thin strip + smarter `historical_queue` thresholds. Operator's "banner is huge" feedback.**

- ✅ `HIST_QUEUE_*` thresholds rebalanced: yellow 5K→50K pending, failures-first escalation (≥25 failed → yellow). Deep queue with 0 failures now stays green.
- ✅ New `level: "info"` banner state (slate-blue) for deep-queue-no-failures, with `metrics.deep_queue_no_failures` flag from the health service.
- ✅ `SystemBanner.jsx` collapsed from ~200px to ~28px single-strip layout. 3-color scheme (red/amber/slate). Inline detail+since+action. Full detail in title tooltip.
- ✅ **12/12 new pytests** + **51/51 v19.31 total** across 6 suites.

### 🎯 v19.31.0–v19.31.3 cumulative — operator pain-points resolved this session

1. ✅ Unified Stream `.slice(0,2)` cap removed; fetch limit 20→200.
2. ✅ ORPHAN/PARTIAL/STALE badge no longer obscures live PnL.
3. ✅ `/api/system/banner` `NameError: pusher_red` fixed.
4. ✅ External-close phantom sweep (`oca_closed_externally_v19_31`) catches LITE-style cases.
5. ✅ Reset script `--force` flag + IB-survival guard prevents orphaning real positions.
6. ✅ MANAGE +0.0R aggregator fixed via `pnl_r` field on every position.
7. ✅ Auto-reconcile-at-boot (`AUTO_RECONCILE_AT_BOOT=true`) — no more morning click ritual.
8. ✅ Historical-queue threshold rebalance + info-level banner + thin strip — backfill no longer alarms.

### 🎯 Just shipped 2026-05-04 v19.31.2 — see CHANGELOG (sixty-eighth commit)
**Auto-reconcile-at-boot toggle — kills the morning RECONCILE-N click ritual.**

- ✅ `AUTO_RECONCILE_AT_BOOT=true` env flag wired into `TradingBotService.start()`. Runs 20s after start (after emergency stops), claims every IB-only carryover via `reconcile_orphan_positions(all_orphans=True)`. Default OFF for safety.
- ✅ Stream event `auto_reconcile_at_boot` emitted on success with first 8 symbols + overflow tag.
- ✅ Wrapped in try/except so reconcile failure never crashes `start()`.
- ✅ **17/17 pytests** including 6 truthy variants + 7 falsy variants + exception-safe test.
- ✅ Combined with v19.31.1 reset-survival guard, operator literally never sees "RECONCILE 13" in the morning anymore.

### 🎯 Just shipped 2026-05-04 v19.31.1 — see CHANGELOG (sixty-seventh commit)
**Three live-RTH bugs from operator screenshot at 9:36 AM ET RTH.**

- ✅ **External-close phantom sweep** in `position_manager.py` — catches the LITE-style case where IB's OCA bracket closed the position but bot's `_open_trades` still tracks it. Marks CLOSED with `oca_closed_externally_v19_31` reason. 6 new pytests.
- ✅ **Reset script IB-survival guard** in `reset_bot_open_trades.py` — refuses to close `bot_trades` rows where IB still holds matching `(symbol, direction)`. New `--force` to bypass; fail-closed when snapshot missing. 7 new pytests.
- ✅ **MANAGE +0.0R aggregator fix** — `sentcom_service.get_our_positions` now emits `pnl_r` + `unrealized_r` for both bot-tracked and orphan/lazy-reconciled paths (was silently 0 because the fields were never populated). 6 new pytests including LITE +12.5R math validation.
- ✅ **22/22 v19.31 pytests passing** across 4 suites. Backend syntax + ESLint clean.

### 🎯 Just shipped 2026-05-04 v19.31.0 — see CHANGELOG (sixty-sixth commit)
**Live-RTH HUD paper-cuts: stream cap + ORPHAN badge overlap + banner NameError.**

- ✅ Unified Stream `.slice(0, 2)` cap removed (HTTP + WS); fetch limit 20 → 200.
- ✅ ORPHAN/PARTIAL/STALE badge moved inline next to tier chip — no longer obscures live PnL.
- ✅ `/api/system/banner` `NameError: pusher_red` fixed. 3 regression pytests.

### 🔴 P0 — Top of next session
- **Verify v19.31.1 fixes live during next RTH session**:
  1. After pull + restart, confirm the LITE-style phantom sweeps within 30-60s of OCA closure.
  2. Check `MANAGE +XR` HUD aggregator now reflects realized R per open position.
  3. Try a dry-run reset script with the new `--dry-run` to see the IB-survival report.
- **Diagnostics Data Quality Pack** — fix Pipeline Funnel `ai_passed`/`bot_fired` consistency + Module Scorecard `shadow_module_performance` per-vote breakdown (carry-over).
- **Bot Thoughts content capture** — Trail Explorer empty `content` field for fired trades (carry-over).

### 🟡 P1 (operator-facing improvements)
- **Auto-reconcile-at-boot** — if `_restore_open_trades` finds 0 rows but IB still has positions, auto-fire a `POST /api/trading-bot/reconcile {all: true}` so the operator doesn't have to click RECONCILE every morning. Likely best gated behind an env flag (`AUTO_RECONCILE_AT_BOOT=true`).
- **Stale-snapshot warning on reset** — if `ib_live_snapshot.current.as_of` is more than ~30s old when the reset script runs, print a warning before partitioning. Defends against a freshly-restarted backend with no pusher data yet.
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over).
- Async-pymongo audit follow-up — 51 remaining sync-mongo-in-async sites.

### 🟢 P2 / P3
- v19.32 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.33 Chart WebSockets (Tier 3 — kill remaining 5s polling latency)
- IB Gateway auto-login resilience
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths

---


## 🔴 Now / Near-term (next session pickup — 2026-05-01 v19.30.12 + Windows network fix)

### 🟢 Today fully resolved — all data channels healthy
- ✅ v19.30.11 — Pusher RPC throttle/circuit-breaker/dedup + skip-restart-if-healthy + system banner
- ✅ v19.30.12 — Distinguish push-channel vs RPC-channel pusher health (4-quadrant severity matrix)
- ✅ Windows network classification fix — 10GbE adapter set to Private (was Public), so `IB Pusher RPC 8765` allow rule is now honored. Spark→Windows on :8765 succeeds. SystemBanner clears, RPC chip green.

### 🔴 P0 — Top of next session
- **Diagnostics Data Quality Pack** — fix Pipeline Funnel `ai_passed`/`bot_fired` consistency + Module Scorecard `shadow_module_performance` per-vote breakdown
- **Verify v19.24 Reconcile endpoint live on Spark** on SBUX/SOFI/OKLO orphans
- **Bot Thoughts content capture** — Trail Explorer empty `content` field for fired trades

### 🟡 P1 (operator-facing improvements)
- **`.bat` health screen probes pusher actually**: replace `WINDOWTITLE eq [IB PUSHER]` check with `curl -s -f -m 3 http://localhost:8765/rpc/health` so operator sees real status, not "window open = OK"
- **Pusher auto-restart on Windows**: wrap CMD launch in `pusher_watchdog.bat` loop that re-spawns on crash
- **Shadow-vs-Real gap drilldown** (71% shadow vs 32% real)
- **Drift detector** — CRITICAL stream when bot tracks <80% of IB shares
- **Async-pymongo audit follow-up** — 51 remaining sync-mongo-in-async sites (was 53)

### 🟢 P2 / P3
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (Tier 3 — kill remaining 5s polling latency)
- IB Gateway auto-login resilience (more robust SendKeys + foreground verification)
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths (ib.py 6349, server.py 4643, enhanced_scanner.py 7090, training_pipeline.py 3869)
- Safely retire Alpaca fallback (32 reference sites)

---

## 🔴 Now / Near-term (next session pickup — 2026-05-01 v19.30.11 fork)

### 🎯 Just shipped 2026-05-01 v19.30.11 — see CHANGELOG (sixty-third commit)
**Pusher overload protection + skip-restart-if-healthy + system banner.**

Three coordinated fixes after operator hit a real outage:
- ✅ **Pusher RPC throttle**: bounded `Semaphore(4)` + circuit breaker (5 failures/10s → open 30s → half-open test → close) + per-method dedup on idempotent reads. Caps Spark→pusher concurrency below IB's 6-concurrent reqHistoricalData limit. Surface metrics in `/api/ib/pusher-health`.
- ✅ **Skip-restart-if-healthy guard** on both `start_backend.sh` and `scripts/spark_start.sh`. `--force` flag for genuine restarts. Cold-boot wait bumped 60s → 120s. Closes the "killed my own healthy backend" footgun.
- ✅ **`GET /api/system/banner`** + V5 SystemBanner.jsx — giant red strip when pusher_rpc red ≥30s OR mongo red ≥10s. Includes explicit "Do NOT restart Spark backend" action copy. Dismissable for 60s; reappears if persistent.
- ✅ 20 new pytests, **60/60 across v19.30 stack**. Live-validated in container.

### 🎯 Just shipped 2026-05-01 v19.30.10 — see CHANGELOG (sixty-second commit)
**Drop the "degraded mode" theatre — pusher-only with Mongo fallback.**

### 🎯 Just shipped 2026-05-01 v19.30.9 — see CHANGELOG (sixty-first commit)
**Degraded-mode UI fixes + cancel-all-pending-orders.**

3 surface bugs operator filed after the v19.30.8 wedge-immunity deploy:

- ✅ `/api/ib/account/positions` no longer 503's in degraded mode —
  falls back to `_pushed_ib_data["positions"]` with explicit
  `degraded:true` + `source:"pusher"|"pusher_stale"` flags. Same
  treatment applied to the alt `/account/summary` async handler.
- ✅ "Bar fetch failed" on V5 chart → root cause was sync pymongo
  `find().sort()` in `hybrid_data_service._get_from_cache` blocking
  the loop long enough for the 30s axios timeout. Both window
  query + stale fallback now `asyncio.to_thread`-wrapped. Same
  treatment applied to `_cache_bars` per-bar upsert loop.
- ✅ NEW `POST /api/trading-bot/cancel-all-pending-orders` —
  pre-open safety endpoint. Drains Mongo `order_queue` of
  pending+claimed rows + cancels direct IB-side open orders when
  reachable (graceful degradation). Requires `confirm:"CANCEL_ALL_PENDING"`
  token. Optional `symbols=[...]` scope + `dry_run:true` preview.
- ✅ 14 new pytests, **39/39 across v19.30 stack** (25 prior + 14
  new). 2 source-level pins so a future refactor can't silently
  re-introduce sync-mongo-in-async to the cache helpers.

Operator action:
```bash
cd ~/Trading-and-Analysis-Platform && git pull && ./start_backend.sh
```

### 🔴 P0 — Now unblocked by v19.30.9
1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency; fix Module Scorecard
   plumbing for `shadow_module_performance` per-vote breakdown.
2. **Bot Thoughts content capture** — Trail Explorer empty `content`.
3. **Verify v19.24 Reconcile endpoint live on Spark** — already
   shipped per PRD but never confirmed in production. Click
   "Reconcile N" in V5 Open Positions header on SBUX/SOFI/OKLO
   and verify they switch from `source:ib` to bot-managed payload.

### 🟡 P1 (unchanged from v19.30.8)
- Shadow-vs-Real gap drilldown (71% shadow vs 32% real).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares.
- **Async-pymongo audit follow-up** — 51 remaining sync-mongo-in-async
  sites (was 53; v19.30.9 closed 2 in `hybrid_data_service`).
- "PUSHER RED" while pusher is actually pushing (is_connected stale).
- `monitor_training.sh:149: [: 0: integer expression expected` bash
  arithmetic bug.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback (32 reference sites)
- **Audit Pass 1** — lint sweep + dead-code (370 ruff auto-fixes,
  61 bare excepts, 6 orphaned services, 3 dup function names in ib.py)
- **Audit Pass 3** — break up 4 monoliths (ib.py 6331, server.py
  4643, enhanced_scanner.py 7090, training_pipeline.py 3869)

---

## 🔴 Now / Near-term (next session pickup — 2026-05-02 v19.30.2 fork)

### 🎯 Just shipped 2026-05-02 v19.30.2 — see CHANGELOG (fifty-fourth commit)
**Bar-poll degraded-mode wedge fix.**

After v19.30.1 verified working live on Spark (200 OKs), a SECOND
wedge surfaced when the Windows IB pusher was OFF. `py-spy dump`
nailed it:

```
MainThread BLOCKED in:
  ib_pusher_rpc.py:124    _request          ← sync HTTP, 8s timeout
  ib_pusher_rpc.py:202    subscriptions
  bar_poll_service.py:229 _build_symbol_pools  ← sync def
  bar_poll_service.py:291 poll_pool_once       ← async caller!
```

What shipped:
- ✅ `poll_pool_once` now calls `_build_symbol_pools` via
  `asyncio.to_thread` — sync HTTP RPC + 3 sync mongo cursor iterations
  now run in a thread, loop stays responsive.
- ✅ Pusher RPC `subscriptions()` timeout dropped 8s → 3s
  (defense-in-depth bound).
- ✅ NEW `start_backend.sh` launcher at project root — handles venv
  activation, server kill, restart, 60s startup wait, health check,
  backpressure observability print. Operator no longer fights the
  venv dance every restart.
- ✅ 5 new pytests in `test_bar_poll_wedge_fix_v19_30_2.py`.
  **125/125 across v19 stack** including v19.30.1 + v19.30.2.

Operator action:
```bash
cd ~/Trading-and-Analysis-Platform && git pull && ./start_backend.sh
```

### 🟡 P1 — Bar-poll wedge fix follow-ups
- **Async-wrap the entire `_PusherRPCClient`** — add `async def
  subscriptions_async(self)`, etc., that own the `to_thread`
  internally. Prevents future async callers from re-introducing the
  same wedge.
- **Negative cache** — after 3 consecutive pusher RPC failures, skip
  the RPC for 60s (then 120s, 300s — exponential backoff). Today's
  fix bounds the per-call wedge at 3s but a fully-OFF pusher still
  costs 3s every 30s forever.
- Boot-time one-shot phantom sweep regardless of RTH.
- IB Gateway reconnect-on-timeout with exponential backoff.

### 🔴 P0 — Now unblocked by v19.30.1 + v19.30.2
The loop stays responsive in BOTH push-storm AND degraded-IB scenarios.
The rest of the v19.30 P0 stack is buildable:

1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency; fix Module Scorecard
   plumbing for `shadow_module_performance` per-vote breakdown.
2. **`POST /api/trading-bot/cancel-all-pending-orders`** — nuke
   pending GTC brackets at IB before market open.
3. **Bot Thoughts content capture** — Trail Explorer empty `content`.

### 🟡 Other P1 (unchanged from v19.30.1 fork)
- Shadow-vs-Real gap drilldown (71% shadow vs 32% real).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares.
- **(Deeper async-pymongo audit follow-up — Audit Pass 2a)** — the
  audit flagged 11 sync `def` handlers in hot routers and 54 inline
  sync mongo calls in async routes. The 2 wedge-causing ones (push-data
  + bar-poll) are fixed. Convert the remaining 53 incrementally as
  they surface as bottlenecks.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback (32 reference sites)
- **Audit Pass 1** — lint sweep + dead-code (370 ruff auto-fixes,
  61 bare excepts, 6 orphaned services, 3 dup function names in ib.py)
- **Audit Pass 3** — break up the 4 monoliths (ib.py 6242, server.py
  4643, enhanced_scanner.py 7090, training_pipeline.py 3869)

---

## 🔴 Now / Near-term (previous fork pickup — 2026-05-02 v19.30.1)

### 🎯 Just shipped 2026-05-02 v19.30.1 — see CHANGELOG (fifty-third commit)
**FastAPI event-loop wedge fix + push-data backpressure.**

The backend was wedging AFTER startup — `/api/health` would TCP-accept
but never return a byte. Three stacked bugs:

1. `/api/ib/push-data` was a sync `def` doing inline sync mongo
   `update_one` to `ib_live_snapshot`.
2. `tick_to_bar_persister.on_push()` ran inline inside that sync
   handler, holding a global lock + per-bar sync upserts.
3. `/api/health` was also sync `def` so it shared the saturated anyio
   thread pool — hence the 0-byte timeouts.

What shipped:
- ✅ `/api/health` `def` → `async def` (now event-loop-protected).
- ✅ `/api/ib/push-data` `def` → `async def` + `asyncio.to_thread`
  for snapshot upsert + tick_to_bar offload.
- ✅ NEW: 503 Retry-After:5 backpressure when ≥4 pushes in flight.
  Pusher backs off cleanly instead of timing out 120s.
- ✅ `/api/ib/status` + `/api/ib/pushed-data` `def` → `async def`.
- ✅ Bonus: fixed pre-existing `from database import get_db` typo
  (real symbol is `get_database`) — `ib_live_snapshot` writes from
  push-data finally work.
- ✅ `BriefMeAgent` injector switched to use `_pushed_ib_data` dict
  directly to avoid the now-async route handler shadow.
- ✅ 7 new pytests in `test_event_loop_wedge_fix_v19_30_1.py`.
  **120/120 combined across v19 stack.**
- ✅ Live verified locally: 30 parallel pushes + 5 health checks
  completed in 36ms total, all health 200, max latency 21ms.

Operator action — Spark deploy:
```bash
cd ~/Trading-and-Analysis-Platform
git pull
pkill -f "python server.py"
cd backend && nohup python server.py > /tmp/backend.log 2>&1 &
sleep 8
curl -s -m 5 localhost:8001/api/health  # MUST return instantly
```

### 🔴 P0 — Now unblocked by v19.30.1
Now that the loop stays responsive, the rest of the v19.30 P0 stack is
buildable:

1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency (currently shows 0% AI
   pass while SentCom Intelligence shows 60%); fix Module Scorecard
   plumbing so `shadow_module_performance` surfaces per-vote breakdown.
2. **`POST /api/trading-bot/cancel-all-pending-orders`** — nuke all
   pending GTC brackets at IB before market open to prevent naked
   shorts if positions are manually flattened.
3. **Bot Thoughts content capture** — Trail Explorer shows empty
   `content` field for fired trades.

### 🟡 P1
- Shadow-vs-Real gap drilldown — endpoint + UI panel showing why
  shadow win rate is 71% but real is 32% (which stop hit early?).
- Drift detector — CRITICAL Unified Stream event when bot tracks
  <80% of IB shares for any symbol.
- Boot-time one-shot phantom sweep regardless of RTH (so phantoms
  don't survive backend restarts).
- IB Gateway reconnect-on-timeout with exponential backoff.
- **(Deeper async-pymongo audit follow-up)** — the v19.30.1 audit
  flagged 11 sync `def` handlers in hot paths and 56 inline sync
  mongo calls in async handlers. The wedge-causing minority are
  fixed. The remaining ones are in low-frequency endpoints
  (`/api/ib/orders/*`, `/system-health`, `/training-status`,
  `/regime-live`, etc.) — convert to async incrementally as they
  surface as bottlenecks.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback
- Break up monolithic `server.py`

---

## 🔴 Now / Near-term (previous fork pickup — 2026-05-01 v19.29-validation-2)

### 🎯 Just shipped 2026-05-01 v19.29-validation-2 — see CHANGELOG (fifty-second commit)
**Morning Play A — clean slate reset for 2026-05-02 open.**
- ✅ `backend/scripts/reset_bot_open_trades.py` — one-shot Mongo
  cleanup script with --dry-run / --confirm RESET safety guard,
  symbol whitelist, 30d audit log to `bot_trades_reset_log`.
- ✅ `memory/MORNING_2026-05-02_PLAY_A.md` — paste-and-follow morning
  runbook (8:30 AM verification → 9:20 TWS flatten → 9:25 reset →
  9:27 restart → 9:30 watch).
- ✅ 16 new pytests + lint clean. 52/52 across reset + verify_v19_29
  harness + v19.29 hardening suites.
- ✅ Live diagnostics revealed Spark backend booted at 21:19 in
  degraded mode (IB Gateway TimeoutError at startup) — pusher works
  but direct IB connection failed; manage loop is RTH-gated so the
  v19.29 phantom sweep won't auto-fire until 9:30 AM ET. Hence the
  manual reset path tomorrow.

### 🔴 P0 — v19.30 Boot Hygiene Pack (~3-4h, scoped 2026-05-01 evening)
After tomorrow's clean-open observation, the right next-feature is a
3-piece pack that prevents tonight's diagnostic dance from recurring:

1. **Boot-time one-shot phantom sweep** — runs once at backend init
   regardless of RTH so phantoms don't survive backend restarts.
   Currently the manage loop is RTH-gated (correct for trail-stop
   ticks but wrong for phantom housekeeping).
2. **IB Gateway reconnect-on-timeout** — replace the silent
   `API connection failed: TimeoutError() → degraded paper mode
   forever` path with exponential-backoff retry (1s → 2s → 4s → 8s,
   max 30s, give up after 5min and surface CRITICAL alarm).
3. **Drift detector** — emit CRITICAL Unified Stream event when bot
   tracks <80% of IB shares for any symbol. Tonight we found BP at
   33%, CB at 50%, HOOD at 37%, SOFI catastrophic — all silent.
   Operator should see drift BEFORE it compounds.

### 🔴 P0 — Choose ONE for the session AFTER v19.30 Boot Hygiene
Both pre-scoped in this doc, ~6h each, pair beautifully:
- **v19.31 — Pre-Aggregated Bar Pipeline** (cold chart load 400ms→30ms)
- **v19.32 — Chart WebSockets** (live bar push, ~50ms vs 5s tail-poll)

Operator picks based on which feels more painful after using v19.28
Diagnostics + v19.30 Boot Hygiene for a few sessions.

### 🎯 Just shipped 2026-05-01 v19.29-validation — see CHANGELOG (fifty-first commit)
**RTH validation harness for v19.29.**
- ✅ `backend/scripts/verify_v19_29.py` — 6 read-only checks with
  colored output / JSON export / watch mode / optional active
  reconcile probe.
- ✅ `memory/V19_29_VALIDATION.md` — operator runbook with curl
  one-liners + post-pull workflow + failure-mode remediation.
- ✅ 21 new pytests; no production code touched.
- ✅ Smoke verified on preview backend: F=PASS / A,D=PENDING_RTH /
  B,C,E=NO_DATA (off-hours).

**Operator action — Spark side**:
1. `python -m backend.scripts.verify_v19_29` after pull + restart.
2. `--watch` mode during opening 30 min of RTH and again at
   3:40-4:00pm to validate gates D + E.
3. Once green sweep observed in production, pick v19.30 or v19.31.

### 🔴 P0 — pick after v19.29 RTH validation
- **v19.30 — Chart WebSockets** (~6-8h, fully scoped below)
- **v19.31 — Pre-Aggregated Bar Pipeline** (~6h, fully scoped below)
- These pair beautifully — v19.31's `on_bucket_close` hook becomes
  v19.30's WS publisher trigger. Operator picks based on which
  hurts more after using v19.28 Diagnostics for a few sessions.

### 🎯 Just shipped 2026-05-01 v19.26 — see CHANGELOG (forty-seventh commit)
**AI chat assistant data plumbing** — operator caught two same-session
bugs (SOFI stop missing, SQQQ no live quote) both rooted in
`chat_server._get_portfolio_context` reading from incomplete sources.
- ✅ **Bug 1 (SOFI stop)**: lazy-reconcile lookup in chat context
  surfaces `bot_trades.stop_price` + `target_prices` for IB orphans
  the bot doesn't track in `_open_trades`. Mirrors v19.23.1 V5 UI fix
  on the chat side.
- ✅ **Bug 2 (SQQQ no quote)**: ticker extraction from user message
  with trading-jargon denylist + live-snapshot + technicals fetched
  for up to 5 mentioned symbols, not just held positions and
  hardcoded indices.
- ✅ 12 new pytests (56/56 combined). Real `timedelta` shadow bug
  caught and fixed by ruff during this commit.

### 🎯 Just shipped 2026-05-01 v19.25 — see CHANGELOG (forty-sixth commit)
**Chart performance hardening — Tier 1 (cache) + Tier 2 (tail refresh).**
Closes operator's "very very delayed chart loading across the app"
complaint without WebSocket complexity.
- ✅ **`services/chart_response_cache.py`** — Mongo-backed TTL cache
  (30s intraday / 180s daily) on `/api/sentcom/chart`. Survives
  backend restarts via Mongo TTL index. ~0.003ms hit time vs full
  compute (~hundreds of ms - several seconds). Schema-versioned.
- ✅ **`/api/sentcom/chart-tail`** — incremental refresh endpoint.
  Returns only bars + indicator points + markers newer than `since`.
  Capped at 50 bars by default. Reads through the same cache.
- ✅ **`ChartPanel.jsx` stale-while-revalidate** — in-component cache
  hydrates state immediately on symbol/tf change, no spinner on
  refetch. Symbol-switch feels instant on previously-visited
  symbols.
- ✅ **Smart polling** — 5s `/chart-tail` polls during RTH on the
  focused chart, 30s outside RTH, paused entirely when tab hidden.
  Replaces the legacy 30s blanket polling that re-shipped 5,000
  bars every cycle.
- ✅ **Cache invalidation on fills** — `trade_execution.execute_trade`
  drops chart cache for the filled symbol so the new entry marker
  shows on the next render without waiting for TTL.
- ✅ 17 new pytests (44/44 combined with v19.23+v19.24). Ruff +
  ESLint clean. Live curl shows cache HIT in ~0.003ms.

### 🟡 Next session priorities

#### 🎯 Just shipped 2026-05-01 v19.29 — see CHANGELOG (fiftieth commit)
**Critical Trade Pipeline Hardening** — operator caught 5 stacked
bugs from EOD screenshot 2026-05-01:
- ✅ **Order intent dedup** — kills the 300+ duplicate cancelled
  orders pattern (BP/SOFI/BKNG/V/HOOD/MA spam)
- ✅ **Direction-safe reconcile** — 30s stability gate prevents
  catastrophic SOFI-SHORT-while-LONG bug from recurring
- ✅ **Wrong-direction phantom sweep** — auto-cleans the existing
  SOFI catastrophe at startup, no IB action fired
- ✅ **EOD no-new-entries gate** — soft cut 3:45pm / hard cut 3:55pm
- ✅ **EOD flatten escalation alarm** — CRITICAL Unified Stream
  event with minutes-to-close severity tier when flatten fails
- ✅ 15 new pytests (105/105 combined). Ruff clean on new code.

#### 🟡 Next session menu (unchanged from v19.28 — pick what helps tuning most):

#### 🎯 Just shipped 2026-05-01 v19.28 — see CHANGELOG (forty-ninth commit)
**Diagnostics tab MVP** — new top-level side-nav tab unifying shadow
trades / actual trades / scans / AI reasoning into one drilldown
+ aggregate views. 5 read-only endpoints powering 4 sub-tabs:
- ✅ **Trail Explorer**: pick any decision → see scanner alert / AI
  module votes / bot decision / bot thoughts as a vertical timeline
- ✅ **Module Scorecard**: per-AI-module accuracy / P&L (followed vs
  ignored) / weight / 🔴 kill-candidate flag
- ✅ **Pipeline Funnel**: emitted → AI-passed → risk-passed → fired
  → winners with conversion %, abnormal drops highlighted
- ✅ **Export Report**: one-click markdown for paste-to-Emergent
  tuning conversations
- ✅ 16 new pytests (90/90 combined). Live verified — all 5 endpoints
  HTTP 200, frontend renders cleanly.

#### 🟡 Next session menu — pick what helps tuning most:

**Option A (most leverage)**: v19.29 — **EOD Insight Stream + Inline drilldowns** (~6h)
- New "Insights" sub-tab on Diagnostics: LLM auto-generates 3-7
  bullets each EOD ("Debate's bear vote was right 80% on momentum
  but you ignored it 70% — consider weighting Bear higher on
  momentum-class setups"). Uses chat_server stack.
- Inline drilldown drawer: click any row in V5 Open Positions /
  Scanner Cards / Unified Stream → trail opens in a side drawer.
  Eliminates the "open Diagnostics, search, find it" friction.

**Option B**: v19.29 — **Tier 3 chart WebSocket** (~6-8h)
- Push new bars to charts within ~50ms (replaces 5s polling).
- Operator approved earlier; full design spec below.

**Option C**: v19.29 — **Pre-aggregated bar pipeline** (~6h, scoped 2026-05-01)
- Eliminates on-the-fly bar aggregation. When a 1-min bar lands
  in Mongo, write the corresponding 5m/15m/1h bars at the same
  time. Chart cold-load drops from ~400-1200ms to ~30-60ms.
- Backfill strategy: **lazy + warm pool on startup** — the 30
  most-recently-viewed symbols × last 30 days get pre-aggregated
  in the background (~10min total); all other symbols use
  fallback path until first viewed, then self-warm. Self-
  optimizing — frequently-used symbols stay fast forever.
- Skip 1day timeframe (180s v19.25 cache already covers it).
- Pairs perfectly with WebSocket (Option B): the aggregator's
  `on_bucket_close(symbol, tf, bar)` hook is exactly what the
  WS publisher needs to push new 5m/15m/1h bars.
- Full spec section below.

**Option D**: v19.29 — **Cohort Comparator + Counterfactual Playground** (~12h)
- "Pick 2 cohorts (e.g. all SOFI long where Debate=BUY but bot
  passed) and compare R-distributions side-by-side"
- "If I'd raised setup_min_rr on momentum from 1.7 → 2.0 last 30d,
  here's what would've happened"
- Heaviest piece, but the prize for closed-loop calibration.

**Option E**: Operator chooses based on first-day Diagnostics use.

#### 🔴 (P0 — verify on Spark)
- **v19.28**: Pull + open Diagnostics tab → Trail Explorer / Module
  Scorecard / Funnel / Export should all populate with real data.
- **v19.27**: Smart source detection on positions panel — partial
  drift rendered correctly, OKLO 0sh phantom auto-swept.
- **v19.26**: Chat assistant — SOFI stop, SQQQ live quote.
- **v19.25**: Chart cache + tail polling latency.
- **MultiIndexRegime live curl during RTH.**

#### 🟡 P1 backlog
- HOOD chart wrong-prices `useEffect` — likely resolved by v19.25
- Per-setup R:R operator overrides → `RiskParameters.setup_min_rr` defaults
- `cpu_relief_manager.is_active()` into deferable paths + RPC-latency auto-trigger
- `SectorRegimeClassifier` end-to-end verification

#### 🟢 P2 / P3 backlog
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback
- Break up monolithic `server.py`

#### 🔴 (P0 conditional — only ship if v19.25 not enough) v19.30 — Tier 3 chart WebSocket layer
**Goal**: Push new bars to the chart within ~50ms of IB delivering them,
replacing the 5s polling cycle entirely. T1 (cache) + T2 (tail) already
killed ~95% of the perceived slowness; Tier 3 closes the last 5%
poll-cycle latency for fast-tape moments.

#### 🔴 (P0 — fully scoped 2026-05-01) v19.31 — Pre-Aggregated Bar Pipeline
**Goal**: Eliminate on-the-fly bar aggregation. When a 1-min bar lands
in Mongo, immediately write the corresponding 5m / 15m / 1h bars at
the same time. Chart cold-load drops from ~400-1200ms to ~30-60ms
(no aggregation compute, just a key lookup). This is the single
remaining architectural gap between SentCom and the consumer
charting platforms (TradingView, TC2000, Finviz) — they all
pre-aggregate on ingest, never on read.

**Cost**: $0 — all work runs on existing DGX CPU + disk you own.
3-5× storage growth on `ib_historical_data` (1m + 5m + 15m + 1h
rows per symbol-bucket) is free disk.

**Skip 1day** — the v19.25 180s cache already makes daily charts
feel instant. Adding daily pre-aggregation = complexity for no win.

**Backfill strategy: lazy + warm pool**
1. **On startup**, read `chart_response_cache` history → identify
   the 30 most-recently-viewed symbols.
2. Background-aggregate those 30 symbols × last 30 days
   (~10 min total). Non-blocking, gated by
   `cpu_relief_manager.is_active()` so it backs off if RTH is busy.
3. **On every chart load**, if no pre-aggregated bars exist for
   the requested window:
   - Serve via the existing on-the-fly fallback (~400-1200ms,
     same as today)
   - Trigger a background aggregation of THAT symbol's full history
   - Next load is instant
4. Self-optimizing: symbols you actively chart get fast and stay
   fast; symbols you never look at never waste compute.

**Storage shape (extends current schema, no new collections)**
```
ib_historical_data {
  symbol, timeframe, time, open, high, low, close, volume, vwap,
  source, partial?
  // existing rows: timeframe = "1min"
  // v19.31 adds rows where timeframe ∈ {"5min", "15min", "1hour"}
}
```
Existing compound index `(symbol, timeframe, time)` already covers
the new query path. No schema migration needed.

**Aggregation engine** (`services/bar_aggregator.py`, new)
```
On every 1-min bar write:
  bucket_5m  = align(bar.time, 5min)   # 09:30, 09:35, 09:40...
  bucket_15m = align(bar.time, 15min)
  bucket_1h  = align(bar.time, 60min)
  for each higher_tf:
    upsert ib_historical_data {symbol, tf, time: bucket_start}:
      open  = first 1m bar in bucket
      high  = max(high) across bars
      low   = min(low) across bars
      close = latest 1m bar
      volume = Σ(volume)
      vwap   = Σ(typical_price × volume) / Σ(volume)
      partial = true if bucket isn't full (last bar of session)
```

**Boundary alignment**
- Anchored to session open (RTH = 9:30 ET, premarket = 4:00 ET)
- Last 5m of RTH may be a 4-min "partial" bar at 15:56-16:00 ET —
  flagged with `partial: true` so the chart can render correctly
- Out-of-order 1m arrival re-computes the affected higher-TF
  bucket atomically via `findAndModify` upsert

**Integration points**
| Component | Change |
|---|---|
| `bar_poll_service` | After persisting a 1-min bar, call `bar_aggregator.on_new_bar(symbol, bar)` |
| `routers/ib._pushed_ib_data` writer | Same hook — when ticks assemble into a partial bar, the in-memory partial is broadcast at every TF boundary |
| `hybrid_data_service.get_bars` | Reads pre-aggregated rows directly via `find({symbol, timeframe})`. Fallback to on-the-fly if zero docs found. |
| `sentcom_chart` router | Unchanged |
| `chart_response_cache` (v19.25) | Unchanged — but each cache miss is now ~50ms instead of ~500ms |
| `chart_ws` (v19.30 when shipped) | Aggregator's `on_bucket_close(symbol, tf, bar)` hook becomes the WS publisher trigger |
| `bot_state.aggregator_cursors` | New persisted dict `{symbol: last_aggregated_iso}` so backfill resumes after restart |

**Expected numbers**
| Metric | Today | After v19.31 |
|---|---|---|
| Cold chart load (5m, 5d) | ~400-1200ms | **~30-60ms** |
| Hot chart load (v19.25 cached) | ~5ms | ~3ms |
| Storage `ib_historical_data` per symbol/yr | ~120MB at 1m | ~150MB (5m=20%, 15m=7%, 1h=2%) |
| Aggregation CPU per new 1m bar | 0 | ~30-80ms (fits in 5s scanner cycle) |
| WebSocket publish latency (when v19.30 ships) | N/A | ~50ms IB tick → frontend candle update |

**Risk + safety**
- Backfill during RTH: gated by `cpu_relief_manager.is_active()`
  to cap at ~5% CPU
- Out-of-order arrivals: atomic upsert re-computes affected bucket
- Bug-corrupted higher-TF rows: `--rebuild` flag drops + re-
  aggregates all higher-TF for a symbol, ~1min per year of data
- Storage sprawl: per-symbol `pre_aggregated_storage_kb` stat in
  Diagnostics > Funnel sub-tab; alert if total >10GB

**Tests** (`test_bar_aggregator_v19_31.py`)
- 5m alignment: 9:30, 9:35, 9:40 (not 9:31, 9:36)
- High/low/volume math correctness on a known 5-bar set
- Partial last-bar flag when bucket isn't full
- Idempotent re-run produces identical output
- Out-of-order 1m arrival re-computes affected buckets
- Backfill cursor resumes correctly after restart
- `cpu_relief_manager` gate skips aggregation when CPU pressure high
- Falls back to on-the-fly when pre-aggregated row missing
- Lazy backfill triggers on first chart-load miss
- Warm pool seeds 30 most-recently-viewed symbols on startup

**Effort**: ~6 hours. Best paired with v19.30 WebSocket since the
aggregator's `on_bucket_close` hook is exactly what the WS publisher
needs. Can ship before or after — operator decides after using
v19.28 Diagnostics for a few sessions.

**Design (locked-in spec — ship as-is unless operator overrides)**:

**Backend** — new `routers/chart_ws.py`
```
WS endpoint: /api/ws/chart/{symbol}/{timeframe}
  - On connect:
      1. server.send_json({"type": "hydrate", ...full /chart payload})
         — sourced from chart_response_cache for instant hydration
         (zero compute, ~0.003ms cache hit + ~5ms wire time)
      2. server enrolls (symbol, tf) in pub-sub registry
  - On every new bar from the pusher:
      server.send_json({"type": "bar", "bar": {...}, "indicators_tail": {...}})
  - On bot fill for symbol:
      server.send_json({"type": "marker", "marker": {...}})
  - On disconnect:
      Remove from pub-sub registry. No reconnect logic on backend
      (frontend handles exponential backoff).
```

**Backend pub-sub** — new `services/chart_ws_broker.py`
- Process-wide singleton `ChartWSBroker`
- `subscribe(ws, symbol, tf)` / `unsubscribe(ws)` 
- `await broker.publish_bar(symbol, tf, bar_dict)` — fanout to all WS
  clients subscribed to (symbol, tf). Best-effort: dropped clients
  cleaned up silently.
- Hook publish_bar into TWO places that already see fresh bars:
  1. `services/bar_poll_service.py` — when a new bar lands in
     `ib_historical_data`, publish.
  2. `routers/ib.py` `_pushed_ib_data["quotes"]` update path — when
     a new tick assembles into a partial bar, publish.
- Hook `publish_marker` into `services/trade_execution.py` right
  next to the existing `chart_response_cache.invalidate(...)` call.

**Frontend** — new hook `frontend/src/hooks/useChartLiveStream.js`
```js
useChartLiveStream(symbol, timeframe, {
  onBar:    (bar)    => candleSeries.update(bar),
  onMarker: (marker) => setMarkers(prev => [...prev, marker]),
  onHydrate:(payload)=> setBars(payload.bars), // first-paint fallback
})
- Auto-connects on mount, reconnects with exponential backoff
  (1s, 2s, 4s, 8s, max 30s) on disconnect
- Pauses when document.visibilityState !== 'visible' (same rule as
  the smart-polling loop)
- Clean unmount on symbol/tf change
- Returns {connected: bool, lastBarTs: number} for the
  ChartHeader status chip
```

**Wire into `ChartPanel.jsx`**:
- Add `useChartLiveStream(symbol, active.value, {...callbacks})`
- Keep `/api/sentcom/chart` cold-load fetch (still needed for
  cacheKey-driven hydration on cold cache)
- KEEP smart-polling 5s `/chart-tail` as a FALLBACK when WS is
  disconnected — don't rip it out, just gate it on
  `wsConnected === false`. Belt-and-braces.

**Backend integration with existing pusher pipeline**:
- The pusher already pushes ticks via `POST /api/ib/push-data` →
  `_pushed_ib_data["quotes"]`. The bar assembly happens in
  `bar_poll_service.py`. So the WS broker just needs to be called
  from the existing assembly path — no new RPC/IB integration.

**Estimated effort**: 6-8 hours
- Backend broker + ws router: 3h
- Frontend hook + ChartPanel wire: 2h
- Pub-sub hooks into bar_poll_service + trade_execution: 1h
- Tests (mock WS connections via httpx-ws or starlette TestClient
  with WS support): 2h

**Tests to ship with it**:
- `test_chart_ws_broker.py` — subscribe/unsubscribe/publish/cleanup
- `test_chart_ws_router.py` — connect → hydrate → bar push → disconnect
- `test_useChartLiveStream.js` — exponential backoff, visibility pause
- Source-level pin asserting `chart_ws_broker.publish_bar` is called
  from `bar_poll_service` (regression guard for v18 architecture)

**Operator-facing surfaces**:
- `GET /api/diagnostic/chart-ws-status` — connected client count,
  per-symbol subscription count, p95 publish latency
- V5 ChartHeader chip showing `LIVE` (WS connected) / `POLL` (WS
  fallback to /chart-tail) so operator sees the state

**Risk / things to watch**:
- WS connection limits — Spark is single-process, but FastAPI/
  Uvicorn handles ~10K concurrent WS by default. Operator unlikely
  to ever hit this. Document the ceiling for future scale.
- Backpressure — if a client falls behind (slow network), don't
  block the publish path. Use `asyncio.wait_for(send, timeout=0.5)`
  and drop the client on timeout.
- Hot-reload safety — broker MUST survive uvicorn reload during dev.
  Singleton pattern + module-level registration handles this.

**Why NOT do this now**:
- T1 + T2 already eliminate ~95% of the perceived slowness without
  the complexity of WS reconnect logic, backpressure handling, and
  pub-sub state.
- Operator wants to verify T1 + T2 on Spark first. If they're
  satisfied, T3 becomes optional polish. If they still feel lag,
  T3 is the fix and the design above is ready to ship.

#### Other priorities (after Tier 3 ships)
- **(P0 — operator verification on Spark — v19.25)** After pull + restart:
  1. Check `cache: 'hit'` field appears on `/api/sentcom/chart`
     responses in the network tab on the second+ load.
  2. Confirm `/api/sentcom/chart-tail?since=<ts>` polls every 5s
     during RTH, paused outside RTH, paused when tab hidden.
  3. Symbol-switch on a previously-visited symbol should feel
     instant (no spinner, chart re-paints sub-100ms).
  4. After a real trade fills, the new entry marker should appear
     on the chart within 5s (next tail poll), not 30s+.
- **(P0 — reconcile UX verification — v19.24)** — operator action item:
  click **Reconcile N** on SBUX/SOFI/OKLO once IB pusher is live,
  confirm bot picks them up.
- **(P0 verify)** MultiIndexRegime live curl on Spark during RTH.
- **(P1) HOOD chart wrong-prices `useEffect` chain** — likely
  resolved as a side-effect of v19.25 cacheKey-driven hydration but
  worth confirming with the operator.
- **(P1) Per-setup R:R overrides as code defaults.**
- **(P1) `cpu_relief_manager.is_active()` into deferable paths.**
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P1) `SectorRegimeClassifier` end-to-end verification.**
- **(P2) Setup-landscape EOD self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" badge.**
- **(P3) Chart bubble click → `sentcom:focus-symbol`.**
- **(P3) SEC EDGAR 8-K integration.**
- **(P3) Safely retire Alpaca fallback.**
- **(P3) Break up monolithic `server.py`.**

### 🎯 Just shipped 2026-05-01 v19.24 — see CHANGELOG (forty-fifth commit)
**P0 proper reconcile + MultiIndexRegime source-level pins.**
- ✅ **`POST /api/trading-bot/reconcile`** — write-through
  counterpart to v19.23.1 lazy-reconcile. Materializes real
  BotTrade records for IB-only orphans (SBUX/SOFI/OKLO) so the bot's
  manage loop can actively trail stops, scale-out, and EOD-close
  them. Modes: `{symbols: [...]}` (explicit) or `{all: true,
  confirm: "RECONCILE_ALL"}` (sweep). Per-request `stop_pct`/`rr`
  overrides.
- ✅ **`RiskParameters.reconciled_default_stop_pct=2.0`** +
  `reconciled_default_rr=2.0`. Persisted through
  `bot_state.risk_params`, surfaced in `/api/trading-bot/status`.
- ✅ **Safety guards** — stop-already-breached skip (never insta-stop
  trades), already-tracked skip (idempotent), no-ib-position skip,
  pusher-disconnected fail-closed, `all=true` requires confirm token.
- ✅ **`OpenPositionsV5` Reconcile N button** — appears in panel
  header only when ≥1 orphan (`source === 'ib'`) is present.
  `window.confirm` → POST → toast with counts.
- ✅ **MultiIndexRegime source-level pins** — `_apply_setup_context`
  + `LiveAlert` + `_refresh_cycle_context` contracts pinned at
  pytest time so a future refactor can't silently drop the
  `multi_index_regime` stamping path.
- ✅ **21/21 new pytests**, **27/27 combined w/ v19.23 suite.**
  ESLint clean.

### 🟡 Next session priorities
- **(P0 — user verification on Spark)** After pulling v19.24:
  1. Restart backend.
  2. Confirm `reconciled_default_stop_pct=2.0` / `reconciled_default_rr=2.0`
     via `curl localhost:8001/api/trading-bot/risk-params`.
  3. Click **Reconcile 3** button in V5 Open Positions header on
     SBUX/SOFI/OKLO and verify the 3 positions switch from
     `source:ib` to the full bot-managed payload + begin appearing in
     manage-loop actions (trail stop ticks, scale-out on PT hit, etc.)
  4. **MultiIndexRegime live check**:
     `curl localhost:8001/api/scanner/live-alerts?limit=5 |
      jq '.alerts[].multi_index_regime'` — should print real labels
     (`risk_on_broad`, etc.), not `"unknown"`. If `"unknown"`,
     investigate `_refresh_cycle_context` cache hookup.
- **(P1) HOOD chart wrong-prices `useEffect` chain** investigation in
  `ChartPanel.jsx`.
- **(P1) Per-setup R:R overrides as code defaults** — operator
  curled 7 overrides in this session. Promote into `RiskParameters.
  setup_min_rr` defaults so fresh deploys pick them up without
  curl-merge.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency**.
- **(P1) `SectorRegimeClassifier` end-to-end verification** — same
  pattern as MultiIndexRegime: pin in pytest + curl on Spark.
- **(P2) Setup-landscape EOD self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.
- **(P3) Chart bubble click → fire `sentcom:focus-symbol` event so
  operator can chat-coach any moment in the day with one click.**
- **(P3) SEC EDGAR 8-K integration for material events.**
- **(P3) Safely retire Alpaca fallback.**
- **(P3) Break up monolithic `server.py`** (Wait until pipeline is
  100% stable).

### 🎯 Just shipped 2026-05-01 v19.23.1 — see CHANGELOG (forty-fourth commit)
**Operator screenshot review on v19.23 deploy → 4 follow-ups in one commit.**
- ✅ **Lazy-reconcile SL/TP for IB-only positions.** `get_our_positions`
  scans Mongo `bot_trades` for matching symbols and stamps stop/target +
  rich entry context onto IB-side positions. SBUX/SOFI/OKLO now show
  red SL + green PT lines on the chart and real values in the OPEN
  panel grid. Status normalized `ib_position` → `open`.
- ✅ **Tier chip humanization.** 22-name `STYLE_HUMAN_MAP` so
  `trade_2_hold` → `DAY 2`, `opening_range_break` → `ORB`,
  `9_ema_scalp` → `9-EMA`, etc. Unknowns fall back to underscore-strip
  + 12-char truncate.
- ✅ **Share size visible everywhere.** `Nsh` is now the lead element
  on the OpenPositionsV5 model-trail subtitle, a chip on
  ScannerCardsV5 manage-stage cards, the lead in the bot narrative
  line, and the right-edge of the V5ChartHeader chip strip.
- ✅ **Chart bubble kind filter loosened.** Allows `filter` and `info`
  events with non-empty `content`. Operator's SBUX deep-feed events
  should now render as bubbles.
- ✅ 6/6 backend pytests passing (added
  `test_lazy_reconcile_enriches_ib_position_with_bot_trade_levels`).
  ESLint clean.

### 🟡 Next session priorities

- **(P0) `POST /api/trading-bot/reconcile`** (proper, heavier).
  Lazy-reconcile is read-only — it doesn't materialize bot_trade rows
  for orphaned IB positions, so the bot can't actively manage them
  (trail stop, scale-out, EOD-close). Build proper endpoint that
  POSTs `{symbols: [...]}` and creates real bot_trades, applies
  default stop/target overlays, and starts RTH management.
- **(P0) MultiIndexRegimeClassifier** verification curl on Spark.
- **(P1) HOOD chart wrong-prices `useEffect` chain** investigation.
- **(P1) Per-setup R:R overrides as code defaults.**
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P2) Setup-landscape EOD self-grading.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.
- **(P3) Chart bubble click → fire `sentcom:focus-symbol` event so
  operator can chat-coach any moment in the day with one click.**

### 🎯 Just shipped 2026-05-01 v19.23 — see CHANGELOG (forty-third commit)
**V5 mockup compliance pass — operator surfaced 4 paper-cuts after the
v19.22.x bracket save, all addressed in one commit.**
- ✅ **Issue #1 — Open Positions $0 PnL + missing detail.** Frontend
  `OpenPositionsV5.jsx` now renders the v19.22.3 backend payload:
  compact rows with sparkline + tier chip + 1-line model trail; click
  chevron to expand into Entry/Last/Stop/PT grid + R:R/Risk/Reward/Shares
  + trailing-stop state + scale-out targets + AI reasoning bullets +
  setup/grade footer.
- ✅ **Issue #3 — Chart annotations.** New
  `ChartThoughtBubblesOverlay.jsx` paints chat-bubble annotations from
  `sentcom_thoughts` over the chart, color-coded by kind, anchored to
  bar timestamps via `timeScale.timeToCoordinate`. Bottom timeline rail
  with click-to-jump. New `Bot` toggle in chart header. Existing E/SL/PT
  price lines + entry/exit markers preserved.
- ✅ **Issue #3 sub — V5 chart header strip.** Mirrors the mockup:
  Symbol · STATUS·age · $price · ±change% · Entry · SL · PT · R:R · Nsh.
  Live current_price + direction-aware change%. Status chip reads
  `position.status` and shows age relative to `entry_time`. R:R now
  uses correct `risk_reward_ratio` field with legacy fallback.
- ✅ **Issue #2 — Pipeline HUD width.** Stages basis-2/3 → 3/5 with
  shrink allowance; right cluster basis-1/3 → 2/5 with shrink-0 so
  7-figure margin balances + 6 inline chips never clip. Stage
  internals tightened (px-2 py-1.5, text-xl) without losing legibility.
- ✅ **Issue #4 — Scanner card tier + setup + reasoning.**
  `ScannerCardsV5` renders tier chip (INTRADAY/SWING/POSITION) +
  setup-type chip (Bellafiore Trade name, humanized) inline alongside
  the stage chip. Alert `bot_text` fallback now joins first 2
  `reasoning[]` entries so chain-of-thought rides the headline.
- ✅ 5 new pytests in `tests/test_open_positions_payload_v19_23.py`
  pinning the position payload contract. **5/5 passing.** ESLint clean.

### 🟡 Next session priorities

- **(P0) MultiIndexRegimeClassifier** verification curl on Spark — was
  shipped 2026-04-30 per CHANGELOG but operator hasn't confirmed
  `LiveAlert.multi_index_regime` is firing on live alerts. Run:
  `curl -s http://localhost:8001/api/scanner/live-alerts?limit=5 |
  jq '.alerts[].multi_index_regime'`. If null, investigate
  `_apply_setup_context` per-cycle cache hookup.
- **(P1) `/api/trading-bot/reconcile`** — let the bot claim untracked
  IB positions (NVDA/TSLA/GOOGL — operator pinned). New endpoint posts
  `{symbols: [...]}` + uses pusher's account snapshot to materialize
  bot trades + apply default stop/target overlays + start RTH
  management.
- **(P1) HOOD chart wrong-prices UI bug** — operator hard-refresh fix;
  investigate `useEffect`/symbol-prop chain in `ChartPanel.jsx` to make
  re-fetch deterministic on symbol change.
- **(P1) Per-setup R:R overrides as code (not curl)** — operator
  curled in 7 extras this session. Add to `RiskParameters.setup_min_rr`
  dict default in `trading_bot_service.py` so a fresh deploy picks
  them up without curl-merge.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P2) Setup-landscape self-grading tracker EOD wiring.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.

### 🎯 Just shipped 2026-05-01 v19.22.1 + v19.22.2 — see CHANGELOG (forty-second commit)
**Live RTH save: HOOD GO 52pts → fill in 60s of deploy.**
- ✅ **v19.22.1** Bracket order handler in Windows pusher — was rejecting
  ~63% of orders with "Unknown order type: bracket". Now constructs
  proper IB 3-leg parent + stop + target with linked parentId/transmit
  chain. Live proof: 14 fills in 15 min post-deploy.
- ✅ **v19.22.1** Dropped `outsideRth=True` on STP leg (IB ignores +
  warns). TP leg keeps it.
- ✅ **v19.22.2** `/reset-rr-defaults` async fix — handler now `async
  def` and awaits Mongo save, returns `persisted_to_mongo` flag.
  Previously fire-and-forget create_task() lost the write across
  restarts.
- ✅ Operator applied via curl: global `min_risk_reward=1.7`,
  added 7 mean-reversion setup overrides (`off_sides`, `volume_
  capitulation`, `backside`, `bella_fade`=1.5, `fashionably_late`=2.0).
- ✅ 24 / 24 pytests pass across v19.20 + v19.21 + v19.22.x.

### 🟡 Next session priorities
- **(P1) HOOD chart wrong-prices UI bug** — backend returns correct
  $73 bars, frontend renders $265-$280 (likely stale symbol state).
  Operator hard-refresh fixed it ad-hoc; investigate the
  `useEffect`/symbol-prop chain in `ChartPanel.jsx` to make the
  re-fetch deterministic on symbol change.
- **(P1) Apply per-setup R:R overrides as code (not curl)** — operator
  curled in 7 extras this session. Add them to the
  `RiskParameters.setup_min_rr` dict default in
  `trading_bot_service.py` so a fresh deploy picks them up without
  needing the curl-merge dance.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P1) Setup-landscape self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**

### 🎯 Just shipped 2026-05-01 v19.22 — see CHANGELOG (forty-first commit)
News pruning + ML Feature Audit panel:
- ✅ `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN` env — filters live IB list
  without touching Gateway settings. Override env still wins absolutely.
- ✅ Trimmed default fallback `[BZ, DJ, BRFG]` (was 5-vendor).
- ✅ `MLFeatureAuditPanel.jsx` mounted in V5 right column —
  click any $TICKER → instant audit of which label-features fire
  (market_setup + multi_index_regime + sector_regime).
- ✅ `CpuReliefBadge` mounted next to it — manual throttle toggle.
- ✅ 6 new pytests, 147/147 pass across full v19 stack.

**Operator action needed on DGX**: add `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN`
to `/app/backend/.env` and `sudo supervisorctl restart backend` — the
filter only takes effect on next backend boot.

### 🎯 Just shipped 2026-05-01 v19.21 — see CHANGELOG (fortieth commit)
HOOD R:R fix + verification surfaces + briefing widgets + CPU relief:
- ✅ Per-setup R:R floors (mean-reversion=1.5, breakout/trend=2.0,
  global=1.7). Gap_fade @ 2.05 R:R now passes; HOOD regression closed.
- ✅ `RiskParameters.effective_min_rr()` resolver with suffix stripping
  (`_long`/`_short`/`_confirmed`).
- ✅ `update_risk_params(setup_min_rr={...})` merges, doesn't replace.
- ✅ Persistence round-trip is lossless for `setup_min_rr`.
- ✅ New endpoints: `GET /api/trading-bot/risk-params` (live + resolved),
  `POST /api/trading-bot/reset-rr-defaults` (one-curl rescue),
  `GET /api/scanner/ml-feature-preview/{symbol}` (verifies all 3 ML
  label-feature layers fire).
- ✅ Premarket Gap-Scanner widget — live scrollable list of gappers
  in last N min, mounted in `MorningBriefingModal`.
- ✅ `sentcom:focus-symbol` global event wired into `SentCom.jsx` chat —
  any `$TICKER` click auto-fires "walk me through $SYM right now".
- ✅ CPU-relief toggle (`/api/ib/cpu-relief`) with `until=HH:MM` window,
  deferred-call counter, UI badge. Smart-backfill respects it.
- ✅ `IB_NEWS_PROVIDER_OVERRIDE` env so operator can clamp news vendors.
- ✅ 17 new pytest cases. 141/141 pass across the v19 stack.

### 🟡 Next session priorities
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable paths**
  (eval-time historical pulls, daily collect, periodic backfill loops).
  Right now only `smart_backfill` defers. The infrastructure is in
  place — each new caller is a one-line check.
- **(P1) Auto-trigger relief based on RPC latency** — watch
  `/api/ib/pusher-health` avg latency. If >2s sustained 60s, flip on;
  reset when latency drops <800ms 60s. (Operator chose manual+timed
  this round; auto is a future enhancement.)
- **(P1) Setup-landscape self-grading tracker** — record briefing
  predictions, grade EOD, feed AI training pipeline.
- **(P2) Mean-reversion metrics service** — Hurst exponent +
  Ornstein-Uhlenbeck half-life per symbol.
- **(P2) Realtime stop-guard re-check** — liquidity-aware trail in
  `stop_manager.py`.
- **(P3) Break up monolithic `server.py`.**

### 🎯 Just shipped 2026-05-01 v19.20 — see CHANGELOG (thirty-ninth commit)
Deep Feed noise cleanup (Phase 1) + Morning Briefing depth (Phase 2):
- ✅ Enabled 11 real playbook setups that were silently sitting in
  `setup_disabled` limbo (`bouncy_ball`, `the_3_30_trade`,
  `vwap_continuation`, `premarket_high_break`, `trend_continuation`,
  `base_breakout`, `accumulation_entry`, `back_through_open`,
  `up_through_open`, `daily_breakout`, `daily_squeeze`).
- ✅ Base-setup splitter now also strips `_confirmed` so
  `range_break_confirmed` / `breakout_confirmed` / `breakdown_confirmed`
  resolve to their enabled base setups.
- ✅ Watchlist-only setups (`day_2_continuation`, `carry_forward_watch`,
  `gap_fill_open`, `approaching_*`) bypass the bot evaluator silently.
- ✅ Sizer now clamps to SafetyGuardrails `max_symbol_exposure_usd`
  so sizes never exceed the safety cap → killed the
  `symbol_exposure $49,986 > $15,000` rejection cascade.
- ✅ Squeeze stop clamped to `max(bb_lower, current - atr*1.0)`
  — R:R holds above 1.5 on mega-caps now.
- ✅ Rejection dedup — 2-min TTL cache by `(symbol, setup, reason)`
  kills duplicate feed spam.
- ✅ New `gameplan_narrative_service.py` + `/api/journal/gameplan/narrative/{symbol}`
  endpoint — returns bullets, levels grid, and an Ollama GPT-OSS 120B
  2-3 sentence trader narrative with `$TICKER` clickable chips.
- ✅ New `GamePlanStockCard.jsx` wired into `MorningBriefingModal.jsx`
  — per-stock expandable cards with levels, triggers, targets,
  invalidation, and AI read.
- ✅ 13 new pytest cases (`test_feed_noise_fixes_v19_20.py`,
  `test_gameplan_narrative_v19_20.py`). 122/122 pass across v19
  + market-setup + landscape suites.

### 🟡 P0/P1 — Next session priorities
- **(P0) Build `MultiIndexRegimeClassifier`** — read SPY/QQQ/IWM/DIA
  daily+intraday, compute breadth + divergence, emit a composite
  regime label plumbed into `LiveAlert` as a soft-gate ML feature.
- **(P1) Build `POST /api/trading-bot/reconcile`** — let the bot
  explicitly claim the 3 untracked IB positions (NVDA, TSLA, GOOGL)
  into `_open_trades` so they get RTH management + EOD handling.
- **(P1) Close the ML learning loop** — plumb `market_setup` +
  `multi_index_regime` into the per-Trade ML feature vector.
- **(P1) Premarket Gap-Scanner UI widget** — scrollable list of
  what gapped in the last 8 mins.
- **(P1) SectorRegimeClassifier** — per-sector ETF regime tags
  feeding `LiveAlert.sector_regime`.

### 🎯 Just shipped 2026-04-30 v19.19 — see CHANGELOG (thirty-eighth commit)
Premarket scan cadence + heartbeat fixes:
- ✅ Premarket cadence tightened `% 10` → `% 2` (20 min → 4 min real
  scans). 37 refreshes over 7:00-9:30 AM ET instead of 7.
- ✅ `_last_scan_time` stamped in premarket + after-hours branches
  (was only RTH). Morning-readiness shows real scanner age now.
- ✅ Fixed v19.18 typo — `_last_scan_at` → `_last_scan_time`.
- ✅ 5 new source-level pins in `test_premarket_cadence_v19_19.py`.

### 🎯 Just shipped 2026-04-30 v19.18 — see CHANGELOG (thirty-seventh commit)
Morning Readiness aggregator (pre-RTH go/no-go check):
- ✅ New `GET /api/system/morning-readiness` endpoint — 5 checks
  (backfill_data_fresh / ib_pipeline_alive / trading_bot_configured
  / scanner_running / open_positions_clean) → single verdict.
- ✅ New `scripts/morning_check.sh` — colour-coded CLI breakdown
  with exit codes (0 green / 1 yellow / 2 red) for cron + chained
  shell automation.
- ✅ Closes the autopilot loop: morning-readiness on day N+1
  verifies that v19.14 EOD on day N flattened the book.
- ✅ 16 new pytest. **140/140 across all v19 backend suites.**

### Operator's automation pipeline (now end-to-end clean)

| Stage | Subsystem | Time |
|---|---|---|
| 1. Pre-RTH go/no-go | v19.18 morning-readiness | 8:30 AM ET |
| 2. Data freshness | v19.17 freshness gate + Collect Data button | as needed |
| 3. Scanner running | v19.15/v19.16 EVAL hot path | RTH |
| 4. Trade management | v19.13 manage stage | RTH |
| 5. EOD flat | v19.14 close stage + v19.14b banner | 3:55 PM ET |

### 🎯 Just shipped 2026-04-30 v19.17 — see CHANGELOG (thirty-sixth commit)
Bar-size-aware smart_backfill freshness gate:
- ✅ New `_expected_latest_session_date(bar_size, now_dt)` helper —
  daily bars require today's session post-4pm ET; intraday require
  today during RTH; weekly require most recent Friday.
- ✅ Replaced `days_behind <= freshness_days` gate with `last_session
  >= expected_session`. Daily bars no longer get silently skipped
  when they're 1-2 days behind.
- ✅ Diagnosed via operator's NVDA chart screenshot showing Apr 27
  as latest bar despite two backfill runs.
- ✅ 23 new pytest including direct pin of the Apr 28 NVDA scenario.

### 🟡 P1 — Next session priorities

- **Nightly auto-backfill schedule** (parked here from v19.17):
  Add a systemd timer (or APScheduler job in `server.py`) on Spark
  that runs `smart_backfill` at 17:30 ET nightly. With the v19.17
  freshness gate now correct, the only remaining gap is the
  manual-trigger requirement. ~15 min of work; mostly a Spark-side
  systemd unit. Sample unit:
  ```ini
  # /etc/systemd/system/smart-backfill.service
  [Unit]
  Description=SentCom nightly smart_backfill
  [Service]
  Type=oneshot
  ExecStart=/usr/bin/curl -fsS -X POST http://localhost:8001/api/ib-collector/smart-backfill
  ```
  Plus a `.timer` unit firing at `OnCalendar=Mon..Fri 17:30 America/New_York`.

- **Detector confidence tier badge on V5 Scanner cards** (parked
  2026-04-30 v19.16). With the EVAL hot path now lean post-v19.15/16,
  the next quality lever is making per-detector evidence visibility
  on the alert UI. Badge spec:
    - 🟢 **Proven** — detector has ≥30 graded R-outcomes
      (`strategy_stats.r_outcomes` length ≥ 30)
    - 🟡 **Maturing** — 5-29 graded R-outcomes
    - ⚪ **Cold-start** — <5 graded R-outcomes
  Plus a tooltip on hover showing `N trades · win-rate% · avg-R · last-fired`.
  Implementation: small badge component on `<ScannerCardV5/>`,
  reads from existing `strategy_stats` field already plumbed onto
  the alert. No new endpoint needed. ~30 min of work.

- **Divergence drill-in panel (Shadow vs Real)**: every shadow-vs-real
  disagreement becomes a labelled training sample. ~2-3h.
- **Setup-landscape self-grading EOD tracker**: record briefing
  predictions, grade EOD against `alert_outcomes`, surface as
  receipts in next morning's briefing.
- **Tier-tag backfill for symbol_adv_cache**: GICS-aligned tags
  on symbols beyond the static map (Finnhub fallback already
  shipped, just needs a one-shot CLI to flush the universe).

### 🎯 Just shipped 2026-04-30 v19.16 — see CHANGELOG (thirty-fifth commit)
Tier-aware detector dispatch:
- ✅ New `_intraday_only_setups` SUPERSET of `_intraday_setups` —
  pin-listed 28 detectors that have explicit sub-5min timing or
  playbook "intraday only" specs.
- ✅ Dispatch loop early-skip BEFORE `_check_setup` when the
  symbol's tier is non-intraday and the detector is in the
  intraday-only set.
- ✅ Conservative inclusion — ambiguous detectors (`squeeze`,
  `breakout`, `chart_pattern`, `mean_reversion`, etc.) explicitly
  pinned as MUST-be-OFF the list to defend against silent
  suppression of swing/position alerts.
- ✅ ~40% reduction in detector dispatch volume on 2,000-symbol
  universe + cleaner AI training data (no more stale-snapshot
  9-EMA scalp signals on swing-tier symbols).
- ✅ 7 new pytest. Fixed pre-existing stale canary test.

### 🎯 Just shipped 2026-04-30 v19.15 — see CHANGELOG (thirty-fourth commit)
Per-cycle context cache:
- ✅ New `_refresh_cycle_context()` runs ONCE per scan cycle —
  prefetches multi-index regime + sector regime market-wide.
- ✅ `_apply_setup_context` reads from the cache; falls back to
  per-alert classifier when cache stale/missing.
- ✅ ~15s/session of EVAL latency reclaimed at 1,500 alerts/day.
  Compounds with v19's parallel gate.
- ✅ Defensive `getattr` so test scaffolding (`__new__`-bypass
  pattern in detector_stats / scanner_canary) keeps working.
- ✅ 10 new pytest. **101/101 across all v19 backend suites + 221/222
  across full scanner-adjacent suite (1 pre-existing unrelated failure).**

### 🎯 Just shipped 2026-04-30 v19.14b — see CHANGELOG (thirty-third commit)
V5 EOD Countdown Banner — 5-min lookahead + CLOSE ALL NOW button.

### 🎯 Just shipped 2026-04-30 v19.14 — see CHANGELOG (thirty-second commit)
EOD close-stage hardening — 6 fixes + 3:55 PM ET default + 15 tests.

### 🟡 P1 — Next session priorities

- **Detector confidence tier badge on V5 Scanner cards** (parked
  2026-04-30 v19.16). With the EVAL hot path now lean post-v19.15/16,
  the next quality lever is making per-detector evidence visibility
  on the alert UI. Badge spec:
    - 🟢 **Proven** — detector has ≥30 graded R-outcomes
      (`strategy_stats.r_outcomes` length ≥ 30)
    - 🟡 **Maturing** — 5-29 graded R-outcomes
    - ⚪ **Cold-start** — <5 graded R-outcomes
  Plus a tooltip on hover showing `N trades · win-rate% · avg-R · last-fired`.
  Gives the operator an at-a-glance signal of which alerts are
  riding on real evidence vs which are still gathering data —
  particularly relevant for the v16-introduced setups
  (`the_3_30_trade`, `bouncy_ball`, `premarket_high_break`) that
  have few graded outcomes yet.
  Implementation: small badge component on `<ScannerCardV5/>`,
  reads from existing `strategy_stats` field already plumbed onto
  the alert. No new endpoint needed. ~30 min of work.

- **Divergence drill-in panel (Shadow vs Real)**: every shadow-vs-real
  disagreement becomes a labelled training sample. ~2-3h.
- **Setup-landscape self-grading EOD tracker**: record briefing
  predictions, grade EOD against `alert_outcomes`, surface as
  receipts in next morning's briefing.
- **Tier-tag backfill for symbol_adv_cache**: GICS-aligned tags
  on symbols beyond the static map (Finnhub fallback already
  shipped, just needs a one-shot CLI to flush the universe).

### 🎯 Just shipped 2026-04-30 v19.14b — see CHANGELOG (thirty-third commit)
V5 EOD Countdown Banner:

- ✅ New `GET /api/trading-bot/eod-status` lookahead endpoint —
  countdown + intraday vs swing position counts + state-machine
  (idle/imminent/closing/complete/alarm).
- ✅ New `EodCountdownBannerV5.jsx` mounted above `DayRollupBannerV5`
  in the Unified Stream container. 5-min countdown, position list,
  CLOSE ALL NOW override button (2-tap confirm), auto-hides on
  completion, alarm state past 4:00 PM ET.
- ✅ Drive-by fix: `/api/trading-bot/eod-close-now` had the same
  bool/dict bug we just killed in `check_eod_close` (v19.14 P0 #1).
  Now treats `close_trade` return as bool. Operator's "CLOSE ALL NOW"
  button actually works.
- ✅ 8 new pytest covering all 5 banner states + shape pin. **23/23
  in test_eod_close_v19_14.py.**

### 🎯 Just shipped 2026-04-30 v19.14 — see CHANGELOG (thirty-second commit)
EOD close-stage hardening — full audit + 6 fixes:

- ✅ **Default close window 3:57 → 3:55 PM ET** per operator request
  (extra 2-min cushion before the 4:00 PM bell). Updated the live
  default + the bot_persistence restore default so the change
  survives restarts and fresh-DB starts.
- ✅ **P0 #1**: `close_trade` returns a bool, not a dict — was raising
  silent AttributeError on every close attempt. Now treated as bool.
- ✅ **P0 #2**: closes run in PARALLEL via `asyncio.gather` (was
  serial; risked spilling past 4:00 PM with 25 open positions).
- ✅ **P0 #3**: `_eod_close_executed_today` only flips True on full
  success; partial failure leaves the flag False so the manage-loop
  tick retries the failed close before the bell.
- ✅ **P0 #4**: After-close alarm — if positions are still locally
  open at/after 4:00 PM, log loud ERROR + broadcast
  `eod_after_close_alarm` event so the V5 HUD can render a banner.
- ✅ **P1 #5**: Half-trading-day detection — `EOD_HALF_DAY_TODAY=true`
  flips the window to 12:55 PM ET (5 min before 1:00 PM close).
- ✅ **P1 #6**: WS-broadcast `eod_close_started` + `eod_close_completed`
  events for V5 HUD visibility.
- ✅ **Intraday-only**: explicit pin via `close_at_eod=True` filter —
  swing/position trades are NEVER auto-closed.

**Tests**: 15 new pytest in `test_eod_close_v19_14.py`. **76/76 across
v19.2 + v19.3 + v19.4 + v19.5 + v19.8 + v19.12 + v19.13 + v19.14 backend
test suites.**

### 🎯 Just shipped 2026-04-30 v19.8 — see CHANGELOG (twenty-seventh commit)
All 4 stream-improvement waves shipped together:

- ✅ **Wave 1** — perception layer:
  - Repeat-event collapser (5× effective stream capacity on busy windows)
  - Cross-panel hover highlight (Scanner ⇄ Stream ⇄ Deep Feed)
  - Counter-trend striping on Scanner cards (surfaces v17 soft-gate decisions)
- ✅ **Wave 2** — Deep Feed → real forensic tool:
  - `GET /api/sentcom/stream/history` over `sentcom_thoughts` (TTL 7d)
  - Time-range chips (5m / 30m / 1h / 4h / 1d / 7d) + symbol drill-in + free-form search
  - Right pane stops being a duplicate of Unified Stream
- ✅ **Wave 3** — context layer:
  - Scanner groupable by Market Setup (operator-toggleable, persisted)
  - Day-rollup banner pinned to top of Unified Stream — names the
    funnel's first dead stage in 1 line so operator stops curling
    `/api/diagnostic/trade-funnel`
- ✅ **Wave 4** — RLHF labels:
  - `POST /api/sentcom/stream/label` (👍/👎/clear, idempotent toggle)
  - New `sentcom_labels` Mongo collection (TTL 90d)
  - Training-pipeline export endpoint joins labels with stored events
  - Closes the self-improving loop alongside realised P&L

**Tests**: 10 new pytest + 9 frontend collapser tests = **122/122 v12-v19.8 + 9/9 collapser**.
ESLint & ruff clean.

### 🎯 Just shipped 2026-04-30 v19.7 — V5 HUD layout 2/3 ⇄ 1/3 split (CHANGELOG: twenty-sixth commit)

### 🎯 Just shipped 2026-04-30 v19.6 — see CHANGELOG (twenty-fifth commit)
- ✅ **V5 HUD: Buying Power replaces Latency** in the top-bar metrics
  cluster. More actionable on a margin account — shows real-time
  margin headroom alongside equity. Color-coded (emerald when
  `BP > equity × 0.5`; amber when running close to maintenance).
- ✅ Backend already collected `BuyingPower` from IB account snapshot
  (line 235 of trading_bot.py); v19.6 surfaces it at top-level of
  `/api/trading-bot/status` so the V5 HUD can read it without an
  extra round-trip.
- ✅ Latency still visible on the Pusher Heartbeat tile (avg/p95/last);
  we just freed the prime HUD slot for buying power.

### 🎯 Just shipped 2026-04-30 v19.5 — see CHANGELOG (twenty-fourth commit)
- ✅ **Safety config Pydantic ceiling raised** for margin accounts —
  `max_total_exposure_pct` validator was `le=100`, rejecting the
  v19.4 unblock curl with HTTP 422 (`Input should be less than or
  equal to 100`, input=320). Bumped to `le=1000` (still rejects
  typos but allows realistic Reg-T margin operation).
- ✅ Cash operators unaffected; only impacts margin-account operators
  who legitimately need >100% of equity in aggregate exposure.
- ✅ 4 new validator tests. **112/112 across v12-v19.5 suites.**

### 🎯 Just shipped 2026-04-30 v19.4 — see CHANGELOG (twenty-third commit)
- ✅ **Position-sizer absolute-notional clamp** — new
  `RiskParameters.max_notional_per_trade` field (default $100,000),
  applied as a third `min()` clamp in `calculate_position_size`
  alongside the existing risk + capital clamps. Decouples per-trade
  size from equity so the sizer can never silently fatten as the
  paper account compounds.
- ✅ Operator's diagnostic curl finally named `safety_guardrail`
  with `symbol_exposure: $267k exceeds cap $15k` — the two-curl
  unblock raised the safety cap to $100k, but the structural fix
  is the sizer clamp itself.
- ✅ Persisted to Mongo; surfaced via `POST /api/trading-bot/risk-params`.
- ✅ 7 new regression tests (clamp wins / risk clamp still wins /
  zero disables / source-level guards / persistence + API round-trip).
- ✅ **108/108 across v12-v19.4 suites.**

### 🎯 Just shipped 2026-04-30 v19.3 — see CHANGELOG (twenty-second commit)
- ✅ **HOT-FIX**: live-tick scanner ALSO bombing pusher RPC.
  Operator's post-v19.2 restart logs reproduced the same cascade
  v19.1 was supposed to kill, plus 120s push-to-DGX timeouts +
  equity `$-` + frozen unified stream.
- ✅ Root cause: `_scan_symbol_all_setups` was the OTHER caller
  hitting `_get_live_intraday_bars` for every scanned symbol —
  ~480 calls/cycle blow IB's pacing limit within 2-3 cycles.
- ✅ One-line fix: pass `mongo_only=True` in the live-tick scanner's
  hot path. Live quote still flows through `_pushed_ib_data`; Mongo
  bars are <60s lagged so 5-min/15-min detectors are unaffected.
- ✅ 4 new regression guards (1 source-level pin on the call site,
  1 v19.1 bar-poll re-pin, 2 signature pins on `get_technical_snapshot`
  / `get_batch_snapshots`). **101/101 across v12-v19.3 suites.**

### 🎯 Just shipped 2026-04-30 v19.2 — see CHANGELOG (twenty-first commit)
- ✅ **DLQ purge endpoint** — `POST /api/diagnostic/dlq-purge` finally
  closes the third corner of the historical-data DLQ tooling (alongside
  `/retry-failed` and `/failed-items`). Safe-by-default: `permanent_only`
  allowlist of known-terminal IB errors (no security definition, contract
  not found, no_data, etc.); `permanent_only=False` requires explicit
  `force=true`; `dry_run=true` previews without deleting.
- ✅ Optional `older_than_hours` and `bar_size` filters; combines
  `$and` with the permanent regex when both active.
- ✅ Audit trail to new `dlq_purge_log` collection (30d TTL).
- ✅ 13 new regression tests; **97/97 across v12-v19.2 suites**.
- **Operator usage**: dry-run first, then drop. The V5 HUD's `N DLQ`
  badge clears as the queue thins.

### 🎯 Just shipped 2026-04-30 v19.1 — see CHANGELOG (twentieth commit)
- ✅ **Hot-fix**: bar poll bombarding pusher RPC. Operator's
  post-v19 logs showed `[RPC] latest-bars X failed` cascade + 120s
  push-to-DGX timeouts. Root cause: v17 expanded subscriptions,
  triggering live-bar overlay in the snapshot service for hundreds
  of symbols every bar-poll cycle.
- ✅ Added `mongo_only=True` flag on `realtime_technical_service`,
  threaded through `bar_poll_service`. Bar poll now reads ONLY from
  Mongo; live-tick scanner unaffected (still uses the live-bar
  overlay for the ~480 streamed symbols).
- ✅ Defence in depth: bar poll cadence/batch dialed down (30s→60s,
  50→25 symbols).
- ✅ Regression guard added — `mongo_only=True` is mandatory.

### 🎯 Just shipped 2026-04-30 v19 — see CHANGELOG (nineteenth commit)
- ✅ **Confidence Gate Parallelism (3-5× EVAL speedup)** — 8
  independent model awaits now fan out via `asyncio.gather()` with
  per-coroutine timeouts and exception isolation. Phase 1 regime
  calls also parallelised.
- ✅ **Source-level regression guard** — 8 parametrized tests assert
  no inline model awaits remain in `evaluate()`. A future contributor
  can't silently undo the speedup.
- ✅ Test suite total: **90/90** across v12-v19.
- **Real-world impact**: at 1,500 alerts/session, gate latency drops
  from ~33 min to ~6 min. Eliminates ~5-10× of the gate-induced
  slippage on fast-tape stocks (where prior 2s per-alert delay caused
  bracket fills past intended entry).

### 🟡 P1 — Next session priorities
- **Per-cycle context cache** — regime/sector/multi-index regime
  recomputed per-alert today; cache once per scan cycle for ~30%
  free additional EVAL speedup. Most of the wiring already done in
  v19 (the gather pattern is established).
- **Tier-aware detector dispatch** — skip impossible detector/tier
  combinations. Quality > speed. Needs operator's tier-mapping
  judgment for ambiguous detectors.

### 🎯 Just shipped 2026-04-30 v18 — see CHANGELOG (eighteenth commit)
- ✅ **Bar Poll Service** — pure DGX-side service that runs bar-based
  detectors on the universe-minus-pusher pool by reading
  ``ib_historical_data`` Mongo (no IB calls, no rate limits). Three
  pools: intraday-noncore (30s), swing (60s), investment (2h).
- ✅ **`LiveAlert.data_source`** field — alerts stamped `live_tick`
  vs `bar_poll_5m` so AI gate / shadow tracker / V5 UI can
  distinguish.
- ✅ **Server-side IB bracket exits** — discovered already shipped
  in Phase 3 (2026-04-22). Added 4 regression guards so a future
  contributor can't silently revert to legacy two-step entry+stop.
- ✅ **`/api/diagnostic/bar-poll-status`** + manual trigger endpoint.
- 11 new tests (76/76 across all instrumentation suites).
- **Universe coverage now ~80%** of the 2,532 qualified universe,
  up from 2.8% pre-v17.

### 🟡 P1 — Next session priorities
- **Confidence gate parallelism** (the 3-5× EVAL speedup) —
  `asyncio.gather()` the independent model consultations.
- **Per-cycle context cache** — regime/sector/multi-index regime are
  recomputed per-alert today; cache once per scan cycle for ~30%
  free EVAL speedup.
- **Tier-aware detector dispatch** — skip impossible
  detector/symbol-tier combinations (e.g. don't run `9_ema_scalp` on
  swing-tier names).

### 🎯 Just shipped 2026-04-30 v17 — see CHANGELOG (seventeenth commit)
- ✅ **Pusher Rotation Service** — DGX-side service that manages
  the new 500-line IB Quote Booster budget. Goes live ~60s after
  bot startup. Pre-v17: 72 hardcoded symbols. Post-v17: ~480
  symbols dynamically rotated by time-of-day profile.
- ✅ **Hard safety guard**: open positions + pending orders
  AUTO-PINNED, can NEVER be unsubscribed by rotation. 30/30 tests
  pass including 4 dedicated safety canaries.
- ✅ **`/api/diagnostic/pusher-rotation-status`** with optional
  dry-run preview, plus `POST /api/diagnostic/pusher-rotation-
  rotate-now` operator escape hatch.
- ✅ Live-tick coverage jumps from **0.76% → ~19%** of qualified
  universe. Phase 2 (bar-poll service) will close to ~76%+.

### 🟠 P1 — Phase 2 (next session): Bar Poll Service
- Build `services/bar_poll_service.py` — IB historical-bar polling
  for the 1,495 swing/investment + ~590 non-subscribed intraday
  symbols. Bar-based detectors (`squeeze`, `mean_reversion`,
  `chart_pattern`, `breakout`, etc.) run on this expanded pool.
- Build multi-client IB session manager — needed to clear the
  60 reqs/10min historical-data rate limit (6 clients = 360/10min).
- Stamp `data_source: bar_poll_5m` on alerts; AI gate can downweight
  if needed.
- Result: total scanner reach jumps from ~480 (v17) to ~2,000+ of
  2,532 qualified symbols.

### 🎯 Just shipped 2026-04-30 v16 — see CHANGELOG (sixteenth commit)
- ✅ **`relative_strength` detector OFF** — operator-flagged: no
  concrete entry trigger, was dominating breadth. Detector method
  preserved for future re-wiring as ML feature on other alerts.
- ✅ **Alert caps lifted 50 → 500 end-to-end** — scanner internal,
  REST endpoint ceiling, frontend REST + WS slice. Operator can now
  see every detected setup/idea to tweak/grow the scanner faster.
- ✅ 4 new regression guards (35/35 across instrumentation + hydration
  + v16 suites).

### 🎯 Just shipped 2026-04-30 v15 — see CHANGELOG (fifteenth commit)
- ✅ **SentCom Intelligence 50-eval cap** removed — confidence_gate
  hydration now counts today via Mongo `$group` aggregation (not the
  50-doc deque), so "today_evaluated" reflects the real daily total.
- ✅ **Alerts panel 5-cap** lifted — `useSentComAlerts.js` 5 → 20 on
  both REST limit and WS slice.
- ✅ **SCAN=0 vs EVAL=5 mismatch** fixed — `derivePipelineCounts` now
  falls back to `alerts.length` when `setups` (predictive_scanner) is
  empty.
- ✅ **`/api/diagnostic/account-snapshot`** — walks the equity
  resolution chain and returns operator-friendly verdict
  (`pusher_disconnected` / `pushed_account_empty` / `net_liq_zero` /
  `ok`).
- ✅ **`/api/diagnostic/scanner-coverage?hours=N`** — surfaces RS-share,
  pusher_sub_count vs. universe_size, and starved detectors so the
  operator can prove the IB-subscription bottleneck without log diving.
- 31/31 tests passing (2 new hydration regression guards).

### 🎯 Just shipped 2026-04-30 v14 — see CHANGELOG (fourteenth commit)
- ✅ **`exc_info=True` / `logger.exception` sweep across the trade
  chain** (15 sites in 4 files). Every critical except now surfaces
  the exception type AND traceback line number in the log, so future
  typo-class regressions like the v13 `BotTrade.quantity` bug surface
  within the first failed trade attempt instead of needing a 13-day
  forensic investigation.
- ✅ 6 new regression canaries (29/29 total in
  `test_trade_drop_instrumentation.py`).

### 🎯 Just shipped 2026-04-30 v13 — see CHANGELOG (thirteenth commit)
- ✅ **13-DAY SILENT REGRESSION FIXED**. The v12 instrumentation
  caught the bug within minutes of going live: `BotTrade` exposes
  `shares` not `quantity`, but `_execute_trade` had two
  `trade.quantity` typos. Every autonomous trade for 13 days hit
  `AttributeError`, silently fail-CLOSED through the
  `safety_guardrail_crash` path, and never reached the broker.
- ✅ Two-line fix in `trading_bot_service.py` lines 2259 + 2264.
- ✅ Two new source-level regression guards in
  `tests/test_trade_drop_instrumentation.py` (23/23 passing).
- ✅ Operator's first curl after pull — confirm `bot_trades` count
  starts climbing again during RTH.

### 🎯 Just shipped 2026-04-30 v12 — see CHANGELOG (twelfth commit)
- ✅ **Trade-drop forensic instrumentation** — new
  `services/trade_drop_recorder.py` + 9 instrumented gates between
  the AI confidence gate and `bot_trades.insert_one()`. Every silent
  exit now writes to `trade_drops` Mongo collection (TTL 7d) AND emits
  a `[TRADE_DROP] gate=… symbol=… reason=…` WARN log.
- ✅ **Broker-reject + exception paths now persist** —
  `trade_execution.execute_trade` was orphaning REJECTED trades in
  memory (no `bot._save_trade(trade)` call). **THIS IS THE LIKELIEST
  ROOT CAUSE** of the April 16 → April 29 silent regression. Fixed.
- ✅ **New endpoint `/api/diagnostic/trade-drops?minutes=N&gate=X`** —
  aggregates drops by gate, names `first_killing_gate`, lists last 25
  with full context. Companion to `/trade-funnel`.
- 21 new tests (44/44 across instrumentation + adjacent suites).

### 🟠 P0 — User-verification pending after Spark pull + restart
**MUST RUN AFTER OPERATOR PULLS AND RESTARTS:**
1. After 5-10 min of RTH scanning:
   `curl -s http://localhost:8001/api/diagnostic/trade-drops?minutes=60 | jq .`
2. Read `first_killing_gate` — that names the suspect.
3. If `account_guard` (highest-confidence suspect for the April 16
   regression): inspect `IB_ACCOUNT_PAPER` in backend/.env and
   ensure it includes the pusher's reported `DUM61566S` alias.
4. If `broker_rejected`: read the `recent[]` array's `reason` field
   for the IB-side error (margin, no-buying-power, etc).
5. Verify REJECTED trades now appear in `bot_trades` (the
   instrumentation also fixed the orphan-in-memory bug).

### 🎯 Just shipped 2026-04-30 v11 — see CHANGELOG
- ✅ **Realtime stop-guard re-check** — 60s per-trade throttle, ratchet-only,
  re-snaps to fresher HVN levels in breakeven + trailing modes.
- ✅ **Sector fallback chain** — `tag_symbol_async` adds Mongo cache +
  Finnhub `stock/profile2` industry mapping with `_PRIORITY_OVERRIDES`
  (Biotech > Tech, REIT > Industrial) + `_EXPLICIT_NONE` blocklist.
  Persists Finnhub hits back to `symbol_adv_cache.sector`.
- ✅ **Daily-Setup landscape pre-warm** — runs in `_scan_loop` CLOSED +
  PREMARKET branches; Saturday 12:00 ET cron job for weekend-context
  rollup. First morning briefing now O(1) instead of paying 200×classify
  latency.
- ✅ **V5 Shadow vs Real tile** — side-by-side win-rate comparison
  with divergence signal (shadow ahead / behind / in sync). Wired
  into the V5 status strip.
- 40 new tests (12 + 20 + 8). 224/224 across related suites.

### 🟠 P1 — Divergence drill-in (operator-saved 2026-04-30 v11)

The shadow-decision badges shipped this commit (●/○ on V5 stream
rows) make divergence VISIBLE but not yet DIAGNOSTIC. Goal: make
every shadow-vs-real disagreement a labeled training sample.

**Behaviour spec**:
  - Click a `○` (bot diverged) badge → side panel opens
  - Panel shows the full shadow decision context:
      • What modules contributed (debate/risk/institutional/timeseries)
      • The reasoning string from `ShadowDecision.reasoning`
      • Why the bot diverged (look up the matching `live_alert` and
        show which gate killed it: `tape_confirmation=false` /
        `auto_execute_eligible=false` / `priority<HIGH` / etc)
      • Outcome: `would_have_pnl` and `would_have_r` (already tracked)
      • A "label" button (good_skip / bad_skip / unsure) that writes
        to a new `divergence_labels` collection
  - Click a `●` (bot agreed) badge → simpler panel showing both
    decisions converged + actual trade outcome if closed

**Implementation surface**:
  - New endpoint `GET /api/ai-modules/shadow/decisions/{id}/divergence`
    — joins shadow decision + matching `live_alert` + `bot_trade` row.
  - New endpoint `POST /api/ai-modules/shadow/decisions/{id}/label`
    — operator-supplied label for training data.
  - New component `frontend/src/components/sentcom/v5/DivergenceDrillInPanel.jsx`.
  - Wire badge `onClick` in `ShadowDecisionBadge.jsx`.

**Why this matters**: closes the learning loop on the bot's gate
calibration. Every time the operator marks a divergence as "bad_skip"
the gate weights get a labeled signal — without that, divergence
data sits unused. ~2-3h since `would_have_pnl` is already tracked on
`ShadowDecision` and the join keys (symbol + trigger_time) align
with `live_alerts`.

### 🟠 P2 — Predictive scanner deprecation (parked from this commit)
The legacy `predictive_scanner` (forming-setup phases — early_formation /
developing / nearly_ready / trigger_imminent) is still wired to:
  - `POST /api/scanner/scan` (used by `ScannerPage.js`)
  - `services/ai_assistant_service.py:1852` (AI assistant context query)
  - 7 GET endpoints (`/setups`, `/alerts`, `/status`, `/summary`,
    `/ai-context`, `/setup-types`, `/alerts/history`) — none of which
    are referenced in V5.

Plan to retire (~2-3h):
  1. Migrate `ScannerPage.js` to `enhanced_scanner` output (likely
     `/api/live-scanner/*` + a small server-side adapter for the
     "scan these symbols now" trigger).
  2. Re-point `ai_assistant_service.get_predictive_scanner()` calls
     to `get_enhanced_scanner()` — both expose the same shape for the
     specific data the assistant reads.
  3. Drop the 7 unused GET endpoints from `routers/scanner.py`.
  4. Delete `services/predictive_scanner.py` + its 1.1k LOC.

Rationale: `enhanced_scanner` is the live source of truth for V5 +
diagnostics + matrix-driven gating. Keeping `predictive_scanner`
around adds confusion (two scanner singletons, one feeds telemetry,
the other doesn't) and dead code surface. Confirmed no V5 frontend
component references `predictive_scanner` data — safe to migrate.

### 🎯 NEXT-SESSION PLAN — Regime → Setup → Trade pipeline (6-item rollout — STATUS UPDATE)

This is the agreed plan after the operator's architectural question
about the pipeline `Market Regime (SPY/QQQ/IWM/DIA) → Sector Regime →
Setup → Time / In-play → Trade`. The decision was: **the hierarchy is
the right human mental model but the wrong runtime architecture for
hard gates** (compounding rejection rate would starve the ML pipeline).
Instead, hard-gate only in 3 places (Time, In-Play, Confidence) and
encode every other layer as a feature into the per-Trade ML models.

| # | Item | Effort | Impact | Status |
|---|---|---|---|---|
| 1 | **`MultiIndexRegimeClassifier`** — read SPY+QQQ+IWM+DIA, return richer regime tags (incl. divergence/breadth). Stamp on alert metadata. | ~3h | **High** | ✅ **SHIPPED 2026-04-30** |
| 2 | **Plumb `market_setup` + new `multi_index_regime` into per-Trade ML feature vector** so the models actually train on them | ~2h | **High** | ✅ **SHIPPED 2026-04-30** |
| 3 | **Backfill sector tags** onto `symbol_adv_cache` (one-time job, GICS via IB or static map) | ~2h | Medium | ✅ **SHIPPED 2026-04-30** |
| 4 | **`SectorRegimeClassifier`** — read sector ETFs (XLK/XLE/XLF/XLV/XLY/XLP/XLI/XLB/XLRE/XLU/XLC), tag each ticker's sector regime | ~3h | **High** (after #3) | ✅ **SHIPPED 2026-04-30** |
| 5 | **Setup-landscape self-grading tracker** — `landscape_predictions` Mongo collection, EOD compare to realized R per Setup family, briefings get receipts | ~3h | Medium-high | ✅ **SHIPPED 2026-04-30** |
| 6 | **Drop the "regime as hard gate" idea** that earlier-fork ROADMAP suggested (`STRATEGY_REGIME_PREFERENCES` enforcement). Replace with feature-based learning per items #1-2. Document the decision. | ~30min | (cleanup) | ✅ **SHIPPED 2026-04-30** |

**Recommended commit ordering**: ~~#1 → #2 ship together~~ ✅ done.
~~Next: #5 as quick parallel win~~ ✅ done. ~~Next: #3 → #4 ship together~~
✅ done. **All 6 items SHIPPED 2026-04-30.** The agreed Regime → Sector
→ Setup → Time → Trade pipeline is fully implemented with soft-gate
ML feature plumbing. Next session: pick up from the P1 backlog.

**Hard gates after this work:**
1. **Time-window** (`_is_setup_valid_now`) — opening_drive can't fire midday
2. **In-Play / Universe** (ADV ≥$2M/day floor + RVOL ≥0.8 floor + tier-based scan frequency, optional STRICT in-play gate) — see `services/in_play_service.py`
3. **Confidence gate** (already exists — predicted_R + win_prob threshold)

Everything else (regime, sector, setup, intraday tape) → features.

### 🧪 What to verify after the next retrain on Spark
After items #1 + #2 shipped (2026-04-30), the next full retrain on the
DGX should produce setup-specific models whose feature vector grew
from N → N+15 (7 setup-label one-hots + 8 regime-label one-hots). Run
the verification suite on Spark:
```
PYTHONPATH=backend python -m pytest tests/test_multi_index_regime_classifier.py -v
```
Live-side spot checks:
- `db.timeseries_models.findOne({setup_type:"9_ema_scalp"}).meta.label_features`
  → should list the 15 new feature names.
- LiveAlert payloads include both `market_setup` and
  `multi_index_regime` (curl `/api/scanner/live-alerts`).
- Morning briefing narrative leads with a 1st-person regime line
  like "Heading into the open, I'm reading the tape as risk-on broad…"
  via `GET /api/scanner/setup-landscape?context=morning` →
  `narrative` field.

### 🟢 Just shipped 2026-04-30 — see CHANGELOG
- ✅ **Item #1**: `MultiIndexRegimeClassifier` (SPY/QQQ/IWM/DIA → 8
  regime labels) + 5-min market-wide cache. Stamps
  `LiveAlert.multi_index_regime`.
- ✅ **Item #2**: `composite_label_features` module + plumbing into
  `_train_single_setup_profile` AND `predict_for_setup`. 15 new
  one-hot features (`setup_label_*`, `regime_label_*`).
- ✅ **Item #6**: `STRATEGY_REGIME_PREFERENCES` re-documented as
  metadata-only (not an active hard gate). Architecture notes locked
  into PRD.md "Pipeline architecture" section.
- ✅ **Item #5** (second commit, same day): Setup-landscape
  self-grading tracker. New `landscape_predictions` collection +
  `LandscapeGradingService` (record / grade / get_recent_grades),
  EOD cron job at 16:50 ET, two new endpoints
  (`/api/scanner/landscape-receipts`, `/api/scanner/landscape-grade`),
  morning narrative now cites yesterday's grade via "Quick receipt"
  / "Owning yesterday's miss" 1st-person line.
- 51 new tests; 116/116 across the related suites still green.

### 🟢 Just shipped 2026-04-29 evening (3 commits) — see CHANGELOG
- ✅ **v1**: 9 new detector functions (6 orphans + 3 playbook setups)
- ✅ **v2**: Bellafiore Setup × Trade matrix system (`MarketSetupClassifier`,
  21-trade × 7-setup matrix, soft-gate, `_check_the_3_30_trade`,
  `/api/scanner/setup-trade-matrix`)
- ✅ **v3**: Setup-landscape briefings + 1st-person voice enforcement
  (`SetupLandscapeService`, 4 narrative voices, `/api/scanner/setup-
  landscape` + EOD/weekend coaching endpoints, voice-rule regression
  tests). Q2 architectural gap (Regime → Setup → Trade) audited;
  decision: handle via features not hard gates (see plan above).
- 61/61 tests passing across the full Setup-related suite.

### 🟠 Still-open items from earlier in session (not part of next-session plan)
- 🟡 **P1** UI heat-grid rendering for the Setup × Trade matrix in the Scanner panel
- 🟡 **P1** Auto-generate `SETUPS_AND_TRADES.md` from classifier constants on commit (currently hand-edited — drift risk)
- 🟡 **P2** Threshold-tune `the_3_30_trade` after first session of live data
- 🟡 **P2** Threshold-proximity sampler tuning for `bella_fade`, `bouncy_ball`, `vwap_continuation` (instrumented; needs live data + tuning)
- 🟢 **Backlog** Define `breaking_news` + `time_of_day_fade` checkers (the 2 remaining orphans)

### 🟠 Operator-prioritized follow-ups (parked)
- **Detector backtest harness** (saved 2026-04-29 evening) — replay last
  30d of `ib_historical_data` against each detector, compute per-setup
  hit-rate + simulated R. Persist into `strategy_stats.r_outcomes`.
- **Tighten Tier 2/3 freshness via smarter collector dispatch**.
- **Mean-reversion timing metric** (Hurst + OU half-life cached on
  `symbol_adv_cache`).
- Realtime stop-guard re-check, EOD Rejection Summary, Chart Pulse.

### 🟢 Earlier this session (2026-04-29 afternoon-12 → afternoon-15) — see CHANGELOG
- Scanner-router instance fix + `setup-coverage` diagnostic.
- Threshold-proximity audit for 12 silent detectors.
- Bucket disambiguation (orphans vs time-filtered).
- Operator-driven strategy time-window reclassification (22 setups).
- Pusher push-loop hang fix (account_data $— → live equity).
- Pusher subscription gate (RPC noise elimination).
- Evaluator-veto specific reason codes + NameError fix.
- Risk caps unified at `max_positions=25` and `min_risk_reward=1.5`.

### 🟢 Just shipped earlier (2026-04-29 afternoon-3) — see CHANGELOG
- ✅ **Bellafiore Setup × Trade matrix system**: new `MarketSetup` enum
  (7 setups), `MarketSetupClassifier` service with daily-bar-driven
  detectors, `TRADE_SETUP_MATRIX` (21 Trades × 7 Setups), 4 new
  `LiveAlert` fields, soft-gate logic in `_apply_setup_context`, new
  `_check_the_3_30_trade` checker, new `/api/scanner/setup-trade-matrix`
  endpoint, canonical `SETUPS_AND_TRADES.md` doc. 48/48 tests passing.
  Trade aliases dedupe: `puppy_dog`→`big_dog`, `tidal_wave`→`bouncy_ball`,
  `vwap_bounce`→`first_vwap_pullback`.

### 🟢 Just shipped earlier this session (2026-04-29 evening, v1) — see CHANGELOG
- ✅ **9 new detector functions**: 6 orphans (`first_move_up`,
  `first_move_down`, `back_through_open`, `up_through_open`,
  `gap_pick_roll`, `bella_fade`) + 3 playbook setups
  (`vwap_continuation`, `premarket_high_break`, `bouncy_ball`).
  Orphan count dropped 8→2 (only `breaking_news` and
  `time_of_day_fade` remain, operator deferred). 17 regression tests
  passing; 37/37 across related suites.

### 🟠 P1 — Outstanding orphans (operator deferred)
- `breaking_news` — operator wants to define rules separately later.
- `time_of_day_fade` — operator explicitly skipping for now.

### 🟠 Operator-prioritized follow-ups (next session candidates)
- **🟢 Detector backtest harness (saved 2026-04-29 evening)** —
  replay last 30d of `ib_historical_data` against each detector
  (especially the 9 new ones) to compute per-setup hit-rate +
  simulated R-multiples. Persist into `strategy_stats` so the SMB
  A/B/C grade + `expected_value_r` fields populate within hours
  instead of waiting weeks for live alerts to accumulate. Sketch:
  `services/scanner_backtest_harness.py` walks each symbol's bars
  forward in 5-min steps, builds a `TechnicalSnapshot` per step,
  calls each `_check_*` detector, then simulates entry/stop/target
  through subsequent bars to measure realized R. Endpoint
  `POST /api/scanner/backtest-detectors?days=30&setups=...` triggers
  the run; results land in `strategy_stats.r_outcomes` so the
  existing EV machinery picks them up automatically.
- **Tighten Tier 2/3 freshness via smarter collector dispatch**: have
  the 4 turbo collectors lazily refresh the most recently scanned
  symbols on cache miss, instead of relying on the nightly batch job.
- **Mean-reversion timing metric (Q2)** (~2-3 hours)
  No half-life / Hurst exponent calculation anywhere today. The bot
  detects "mean_reversion" as a setup type but can't answer "this
  symbol typically reverts in X bars". Plan: new
  `services/mean_reversion_metrics_service.py` computes per-symbol
  Hurst exponent + Ornstein-Uhlenbeck half-life nightly from daily
  bars and caches `mean_reversion_stats` on `symbol_adv_cache`.
  Evaluator can then prefer/avoid mean-revert setups based on the
  symbol's intrinsic reversion speed. ~2-3 hours, real differentiator
  vs typical setup scanners.
- **Realtime stop-guard re-check** in `stop_manager.py` (liquidity-aware trail).
- **EOD Rejection Summary** narrative line.
- **Chart Pulse** (live cache freshness tick).

### 🟢 Earlier this session (2026-04-29 afternoon-12 → afternoon-15) — see CHANGELOG
- Scanner-router instance fix + `setup-coverage` diagnostic.
- Threshold-proximity audit for 12 silent detectors.
- Bucket disambiguation (orphans vs time-filtered).
- Operator-driven strategy time-window reclassification (22 setups).
- Pusher push-loop hang fix (account_data $— → live equity).
- Pusher subscription gate (RPC noise elimination).
- Evaluator-veto specific reason codes + NameError fix.
- Risk caps unified at `max_positions=25` and `min_risk_reward=1.5`.

### 🟢 Just shipped earlier (2026-04-29 afternoon-3) — see CHANGELOG
- ✅ **Round 1 backend fixes** — `/api/trading-bot/status` now reads IB
  pushed account (was `$—`), `/api/scanner/strategy-mix` falls back to
  in-memory alerts when Mongo empty (was `total: 0`), SPY change_pct now
  uses daily-close anchor when only 1 intraday bar exists.
- ✅ **`emit_stream_event` shipped** — module-level helper in
  `services/sentcom_service.py`. Was imported but never defined → trade
  fills + safety blocks + order dead-letters silently dropped from V5
  Unified Stream for weeks. Wired into trade fills.
- ✅ **Per-detector firing telemetry** — `_check_setup` counts
  evaluations + hits per setup_type; `/api/scanner/detector-stats`
  endpoint exposes per-cycle + cumulative views so operator can finally
  diagnose "why is the scanner only emitting RS hits?".

### 🟢 Just shipped this session (2026-04-29) — see CHANGELOG
- ✅ **Shadow tracker drain mode** — `?drain=true` clears 6,715-deep
  backlog in one curl; yields to event loop between batches; stats
  cache busted on drain.
- ✅ **Mongo historical price fallback** for shadow tracker — drain
  now actually updates outcomes for symbols not in the IB pusher
  subscription. Operator's 6,715 backlog cleared 100%.
- ✅ **Per-module accuracy fix** — PnL-based correctness +
  recommendation keyword matching. Modules now show real 70-73%
  accuracy instead of perpetual 0%.
- ✅ **Liquidity-aware realtime stop trail (Q1)** — new
  `compute_trailing_stop_snap` + `StopManager.set_db()` so Target 1
  / Target 2 / trail ticks all anchor to HVN clusters when available
  (clean fallback to legacy ATR/% trail otherwise). 11 regression tests.
- ✅ **Mongo compound indexes** — `bar_size_1_date_-1` and
  `symbol_1_bar_size_1_date_-1` shipped on DGX. `rebuild-adv-from-ib`
  dropped from 5+ min → 44s.
- ✅ **Unqualifiable strike-counter rescue** — historical collector
  now POSTs to `/api/ib/historical-data/skip-symbol` on Error 200,
  and threshold lowered 3 → 1. Should drop overnight backfill time
  ~3-5×. 9 regression tests.
- ✅ **timeseries_ai shadow-tracking gap** — sentinel payload built
  for unusable / debate-consumed forecasts so the module finally
  gets credit in shadow stats. 5 regression tests.
- ✅ **AI Decision Audit Card (V5 dashboard)** — new
  `/api/trading-bot/ai-decision-audit` endpoint + AIDecisionAuditCard
  rendering per-trade module verdicts + outcome alignment. 15
  regression tests.
- ✅ **Risk-caps unification (Option B — read-only)** — new
  `/api/safety/effective-risk-caps` surfaces the actual binding
  cap across 6 conflicting sources + human-readable conflict
  diagnostics. 12 regression tests.

### 🟠 Backlog (next session candidates)
- **Risk-caps unification — Option A (full refactor, ~2-3 hours)**:
  Make `RiskParameters` (Mongo `bot_state.risk_params`) the single
  source of truth. `SafetyGuardrailConfig.from_env()` becomes
  `from_bot_state(db)`. PositionSizer + DynamicRiskEngine + gameplan +
  debate all read the same config. One UI panel to edit → all
  subsystems update. Touches 6 files. Worth doing once the
  intermediate Option B has been live for a session and proven the
  effective-cap resolution logic is sound.

### 🔴 P0 OPTIMIZATION — DEFERRED (was 2026-04-29 morning's top item, now shipped above)
**Pre-flight contract validation in `ib_historical_collector.py`**
- **Symptom**: During the 2026-04-29 overnight backfill, 3 of 4
  collectors burned their entire 60-req/10-min IB pacing quota on
  bad symbols (PSTG, HOLX, CHAC, AL, GLDD, DAWN…). Each bad symbol
  consumes 9 IB requests (one per bar_size) before being pruned.
  ~1,000-1,500 bad symbols in the queue = ~9,000-13,500 wasted IB
  requests across the run, slowing total backfill ~3-5×.
- **Fix**:
  1. In `ib_historical_collector.py` (Windows PC), before queuing 9
     bar_sizes for a symbol, do **one** `reqContractDetails()` call.
     If it errors with "No security definition", **immediately**
     mark the symbol unqualifiable and skip all 9 bar_size tasks.
  2. Lower the strike threshold for "No security definition" from
     3 → 1 in `services/symbol_universe.py::mark_unqualifiable`. The
     error is deterministic, not transient — no point waiting for
     more failures.
- **Expected impact**: ~75% reduction in IB quota burn during backfills.
  Overnight runs that currently take 6-10 hours should drop to 2-4 hours.
- **Effort**: ~30 min code change, no risk to existing logic.
- **Test plan**: Pick 3 known-bad symbols (PSTG, HOLX, CHAC), trigger
  smart-backfill, verify each consumes only 1 IB request and
  immediately gets `unqualifiable: true`.

### 🟠 Operator-prioritized follow-ups (next session candidates)
- **Mean-reversion timing metric (Q2)** (~2-3 hours)
  No half-life / Hurst exponent calculation anywhere today. The bot
  detects "mean_reversion" as a setup type but can't answer "this
  symbol typically reverts in X bars". Plan: new
  `services/mean_reversion_metrics_service.py` computes per-symbol
  Hurst exponent + Ornstein-Uhlenbeck half-life nightly from daily
  bars and caches `mean_reversion_stats` on `symbol_adv_cache`.
  Evaluator can then prefer/avoid mean-revert setups based on the
  symbol's intrinsic reversion speed. ~2-3 hours, real differentiator
  vs typical setup scanners.

### 🟣 Saved improvements (operator pinned 2026-04-28)

- **Trade-chain log watcher / first-occurrence pager** (operator
  pinned 2026-04-30 v14). Now that every critical except in the
  trade chain emits a full traceback (`logger.exception(...)`) and
  every silent drop writes to `trade_drops`, wire a tiny watcher
  that pages on FIRST occurrence of `[TRADE_DROP] gate=…` /
  `safety_guardrail_crash` / new `AttributeError`/`TypeError`/
  `KeyError` in the trade chain. Two flavours:

  • **Light (~30min)**: cron-style `journalctl -k --since "5 min ago"
    | grep -E "[TRADE_DROP]|guardrail check crashed|execute_trade
    error"` piped to a `mail`/`curl webhook` if non-empty. Lives in
    a small `scripts/trade_chain_log_watcher.sh` on Spark, runs every
    5 min via cron. Stores last-seen line hash in `/tmp` to avoid
    spamming on the same recurring bug.

  • **Heavy (~3h)**: real Loki/Promtail/Vector setup with structured
    log labels (`gate`, `symbol`, `setup_type`) → Grafana alert rule
    that fires on `count_over_time({app="sentcom"} |~ "TRADE_DROP"
    [10m]) > 5`. Better long-term but adds infra.

  Recommended start: light flavor. Heavy version when we have ≥2 more
  silent regressions worth justifying the infra weight.

  **Why this matters**: the 13-day v13 regression cost real trading
  days. With the v12 instrumentation + v14 logging the next typo will
  surface in the first failed trade attempt, but only if someone is
  watching. A 30-min watcher closes that loop.

- **Live cache freshness pulse on chart x-axis** — turn the most
  recent x-axis tick green when its bar was written by
  `source="live_tick"` within the last 60s. Visual confirmation the
  symbol is "self-healing" on live ticks (no PARTIAL coverage anxiety).
  ~30 min of work; touches `ChartPanel.jsx` + a new tiny
  `/api/ib/tick-persister-symbol-freshness?symbol=X` endpoint.
- **EOD narrative rejection summary** — at 16:00 ET, compose a
  single end-of-day summary line from the rejection-narrative buffer:
  *"Today I passed on 47 alerts: 18 setup_disabled (most: bella_fade),
  12 dedup_cooldown, 9 regime_mismatch, 5 tqs_too_low,
  3 max_open_positions."* Tells operator at a glance whether filters
  are too tight or scanner's spamming. ~20 min of work; group by
  reason_code in a new `/api/trading-bot/eod-rejection-summary`
  endpoint, render as the Close Recap card subtitle.
- **Multiplier-threshold optimizer v2 — held-out validation slice**
  (sketched 2026-04-28e at `services/multiplier_threshold_optimizer_v2.py`,
  not yet wired). Splits the trade window 80/20 train/holdout and
  only persists threshold changes whose direction is confirmed on
  the held-out slice. Defends against the v1 optimizer chasing a
  lucky 30-day regime window. Activate by:
  (a) swapping `from .multiplier_threshold_optimizer import run_optimization`
      → `from .multiplier_threshold_optimizer_v2 import run_optimization_v2`
      in `eod_generation_service.py` and `routers/trading_bot.py`,
  (b) bumping `_MIN_COHORT_N_V2` (default 25) once cohort sizes stabilize,
  (c) running v1 + v2 in dry-run alongside each other for ~2 weeks
      to compare proposal stability before flipping.
- **Catalyst-aware carry-forward ranker**
  (sketched 2026-04-28e at `services/catalyst_aware_carry_forward.py`,
  not yet wired). Filters today's intraday alerts by overnight news /
  EPS catalyst presence before the carry-forward TQS gate, so a
  B-grade setup on a stock with a fresh 8-K filing or post-market
  earnings beats the same setup on a quiet stock. Components
  scored: 8-K (+35), earnings within 5d (+25), material news within
  24h (+20), analyst action within 48h (+10), overnight gap >2%
  (+25). Activate by calling `enrich_with_catalyst(alert, db)` in
  `enhanced_scanner._rank_carry_forward_setups_for_tomorrow` and
  sorting by `(catalyst_score, tqs_score)` so news-driven candidates
  surface first. Pairs naturally with the SEC EDGAR 8-K integration
  (also on the roadmap as P2).
- **Live health monitor — go-live trip wire**
  (sketched 2026-04-28e at `services/live_health_monitor.py`,
  not yet wired). Async daemon polling every 30s; trips
  `bot.kill_switch_latch()` on any of: pusher offline >60s, account-
  guard mismatch, RPC p99 >5s over a 2-min window, ≥5 consecutive
  order rejects, bot loop heartbeat >90s stale. 10/10 tests
  passing (`test_live_health_monitor.py`). Activate alongside the
  first LIVE flip by:
  (a) instantiating `LiveHealthMonitor(self).start()` in
      `TradingBotService.start_bot`,
  (b) adding a `/api/trading-bot/live-health` GET endpoint that
      returns `monitor.snapshot()` for the operator dashboard,
  (c) recording RPC latencies via `monitor.record_rpc_latency_ms`
      in `routers/ib.py` after each pusher RPC call.

### Operator user-noted issues at end of session
- **Paper account shows $100,000** instead of operator's expected balance
  → Not a code bug. Operator is logged into IB paper account `DUN615665`.
  Resolution: in TWS → Edit → Global Configuration → API →
  Reset Paper Trading Account → set custom starting balance. One-time
  TWS-side action, no code change needed.
- **Scanner still mostly RS hits** — partly explained by the small
  pusher subscription set (14 symbols). Live-tick-driven detectors
  (RVOL, EMA9 distance) are starved on symbols not in the pusher's
  subscription. Resolved long-term by item below ("Live tick → Mongo
  bar persistence") — see ROADMAP.

### P0 — Pusher cleanup ✅ SHIPPED 2026-04-28 (see CHANGELOG)
- ~~Lower L2 sub limit 5 → 3~~ ✅ Done.
- ~~Backend: skip `/rpc/latest-bars` for symbols not in pusher's
  subscription~~ ✅ Done — new `subscriptions()` cache + gate in
  `services/ib_pusher_rpc.py` + 7 regression tests.

### P1 — L2 dynamic routing for top-3 EVAL alerts ✅ SHIPPED 2026-04-28 (Path B)
- Pusher: `/rpc/subscribe-l2`, `/rpc/unsubscribe-l2`, `/rpc/l2-subscriptions`.
- Backend: `services/l2_router.py` (15s tick, top-3 EVAL diff routing).
- Path B chosen — startup index L2 disabled (set
  `IB_PUSHER_STARTUP_L2=true` to revert). One IB clientId, no second
  session needed.
- Disable globally with `ENABLE_L2_DYNAMIC_ROUTING=false`.
- Status endpoint: `GET /api/ib/l2-router-status`.
- See CHANGELOG 2026-04-28 entry #2 for full details.

### P1 — ⭐ Live tick → Mongo bar persistence ✅ SHIPPED 2026-04-28
- New `services/tick_to_bar_persister.py` builds 1m/5m/15m/1h bars
  from `/api/ib/push-data` quote stream and upserts to
  `ib_historical_data` with `source="live_tick"`.
- Status endpoint: `GET /api/ib/tick-persister-stats`.
- See CHANGELOG 2026-04-28 entry #1 for full details.

### P0 — Pusher RPC latency partially recovered
- After backend restart at ~3:06 PM ET, RPC latency dropped from 350s
  to 546ms (last sample). Avg/p95 still skewed high (11.4s / 17.9s,
  n=50) but normalising as good samples accumulate. Tentatively
  resolved by the restart.
- If it spikes again, investigate: IB pacing, DGX RPC handler
  profile (synchronous Mongo writes?), network Windows ↔ DGX.

### P0 — Wave-scanner background loop never started ✅ FIXED 2026-04-28
- `/api/wave-scanner/stats` now reports real `total_scans` /
  `last_full_scan` / `last_scan_duration`. Root cause was that
  `enhanced_scanner._scan_loop` produced wave batches but never called
  `wave_scanner.record_scan_complete()` to roll the counters forward.
  Fix wires the callback after every successful scan cycle.

### P1 — Briefings content gaps ✅ SHIPPED 2026-04-28 (frontend + backend)
- Backend: `_auto_populate_game_plan` now fetches MarketRegimeEngine
  state + recommendation; surfaces `regime` / `bias` / `thesis` at
  top-level of the gameplan doc.
- Frontend: Morning Prep / Mid-Day Recap / Power Hour cards all read
  the new shape with fallbacks (no more "No game plan filed" silence;
  empty-state recap + power hour show regime + scanner hits + watchlist).
- See CHANGELOG 2026-04-28 entry #3.

### P1 — Setup-found bot text (operator flagged 2026-04-27)
- Operator says "RS LEADER NVDA +6.8% vs SPY - Outperforming market —
  TQS 51 (C)" copy is wrong but didn't specify how. **Action:** ask
  operator what the copy *should* say, then fix the server-side
  bot-narrative template.

### P1 — `/api/scanner/daily-alerts` returns 0 ❌ NOT A BUG (closed 2026-04-28)
- Diagnosed: endpoint reads `_live_alerts.values()` in-memory and
  filters by `setup_type ∈ DAILY_SETUPS`. No Mongo `timestamp` filter
  exists. Returns 0 simply because no daily setups have fired this
  session. No code change required.

### P1 — Mongo aggregation index for `rebuild-adv-from-ib` ✅ SCRIPT SHIPPED 2026-04-28
- Operator-side script: `backend/scripts/create_ib_historical_indexes.py`.
  Idempotent. Creates `{bar_size: 1, date: -1}` and
  `{symbol: 1, bar_size: 1, date: -1}` if missing.
- Run on DGX:
  ```
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \\
      backend/scripts/create_ib_historical_indexes.py
  ```

### P1 — Live Data Phase 4: retire Alpaca fallback
- Set `ENABLE_ALPACA_FALLBACK=false`, run smoke for 1 trading day,
  then remove the Alpaca client + fixtures entirely.

### P1 — User-verification pending
- Visually confirm new ET 12-hour formatting on DGX after frontend
  hot-reload (chart x-axis, alerts row, S.O.C., briefings).
- Confirm chart x-axis now shows "Apr 27" labels at day boundaries
  instead of looping `9:30 AM → 1:00 PM → 4:00 AM`.
- Confirm Pusher RPC tile headline now reads `last 335ms` instead of
  the misleading `avg 1117ms`.

### P2 — SEC EDGAR 8-K integration
- Material-events feed for the Briefings panel.

### P3 — Quick wins
- ⌘K palette: `>flatten all`, `>purge stale gaps`, `>reload glossary`.
- "Dismissible forever" tooltip option on Help System.
- Retry the 222 historical `qualify_failed` items via
  `/api/ib-collector/retry-failed` (click the red `222 DLQ` badge).
- Auto-strategy-weighting (parked — see CHANGELOG `2026-02 — DEFERRED`).
- Refactor monolithic `server.py` → routers/, models/, tests/ (defer
  until pipeline is 100% stable).
- Build the Agent Brain memory system (Option C scope agreed
  2026-04-27 — see chat history; user pinned for later).
- ~~Add a "scanner-health canary" pytest~~ ✅ SHIPPED 2026-04-28 —
  `tests/test_scanner_canary.py` (10 tests). See CHANGELOG batch #2
  entry #2.

### P0 — Wave-scanner: ✅ SHIPPED — see CHANGELOG 2026-04-28.

### P1 — Briefings: ✅ shipped — see CHANGELOG 2026-04-28 entry #3.

### P1 — Setup-found bot text ✅ SHIPPED 2026-04-28
- Operator preference: wordy / conversational. Now renders 2-3
  sentences (saw + quality call + plan) instead of one terse line.
- See CHANGELOG 2026-04-28 batch #2 entry #1.

### P1 — Phase 4 Alpaca retirement ✅ LOCKED 2026-04-28
- `ENABLE_ALPACA_FALLBACK=false` is the default. Canary tests
  prevent silent rollback. See CHANGELOG 2026-04-28 batch #2 entry #3.

### P1 — `/api/scanner/daily-alerts`: ❌ closed (not a bug) — see CHANGELOG 2026-04-28.

### P1 — Mongo index: ✅ script shipped — see CHANGELOG 2026-04-28 entry #4.

### P1 — Live Data Phase 4: retire Alpaca fallback
- Set `ENABLE_ALPACA_FALLBACK=false`, run smoke for 1 trading day, then
  remove the Alpaca client + fixtures entirely.

### P1 — User-verification pending
- Visually confirm new ET 12-hour formatting on DGX after frontend
  hot-reload (chart x-axis, alerts row, S.O.C., briefings — see
  CHANGELOG `2026-04-27 — App-wide ET 12-Hour Time Format`).
- Confirm chart x-axis now shows "Apr 27" labels at day boundaries
  instead of looping `9:30 AM → 1:00 PM → 4:00 AM`.
- Confirm Pusher RPC tile headline now reads `last 335ms` instead of
  the misleading `avg 1117ms`.
- After scanner-regression fix is pulled to DGX, verify alert volume
  recovers to ~1,000/day with multiple setup types.

### P2 — SEC EDGAR 8-K integration
- Material-events feed for the Briefings panel.

### P3 — Quick wins
- ⌘K palette: `>flatten all`, `>purge stale gaps`, `>reload glossary`.
- "Dismissible forever" tooltip option on Help System.
- Retry the 222 historical `qualify_failed` items via `/api/ib-collector/retry-failed`
  (click the red `222 DLQ` badge in the V5 header → opens NIA panel).
- Auto-strategy-weighting (parked — see CHANGELOG `2026-02 — DEFERRED`).
- Refactor monolithic `server.py` → routers/, models/, tests/ (defer
  until pipeline is 100% stable).
- Build the Agent Brain memory system (Option A/C, scoped 2026-04-27 —
  see chat history "Brain memory pinned for later").

---

## Backlog — DataFreshnessBadge → Command Palette evolution (P2, post-Phase-3)

**Concrete spec** for when the live-data foundation is in place:

Turn the passive `DataFreshnessBadge` chip into an active control surface.
Clicking the badge opens a slide-down inspector panel (or `⌘K` modal on
desktop) showing:

  1. **Global pipes** — one row each:
     - Pusher push age + health (from `/api/ib/pusher-health`)
     - Historical-queue freshness (from `/api/ib-collector/universe-freshness-health`)
     - Live-bar cache stats (from Phase 1's `live_bar_cache` collection)
     - IB Gateway connection (derived from pusher health)

  2. **Per active-view symbol** (the ones user is currently looking at):
     - Symbol · last bar time · cache TTL remaining · "Refresh now" button
     - Example: `MRVL · closed 16:00 ET · 42m until refresh · [Refresh now]`
     - Uses Phase 2's subscription manager to know which symbols are "hot".

  3. **One-click actions**:
     - `Refresh all now` — bypass cache TTL, force pusher RPC fetch for all hot symbols
     - `Pause live subs` — emergency lever when IB pacing is tight
     - `Open pusher-health endpoint` — for deep debugging
     - `⌘K` fuzzy symbol search — this is also BL-01 (command palette), merges here

  4. **Discovery affordance**: a small pulsing chevron on the chip on first
     visit per browser session hints that the chip is clickable.

**Why this is the right move:**
- Current chip is read-only — tells you the state, not how to fix it.
- Inspector collapses multiple diagnostic endpoints into one pane.
- BL-01 (⌘K command palette) was listed as P3 separately but naturally
  shares the surface — wiring them together saves a code path AND gives
  users a consistent "everything starts from the badge" muscle memory.
- Directly addresses the 5-week-stale-data RCA: *"nothing in the UI
  shouted that data was frozen."* Now not only does it shout, it offers
  the fix button right there.

**Effort estimate:** ~3–4h once Phases 1–3 are in. Do not attempt before —
it depends on `live_bar_cache` and subscription state that don't exist yet.

**File plan:**
  - `frontend/src/components/DataFreshnessInspector.jsx` — slide-down panel
  - `frontend/src/hooks/useActiveViewSymbols.js` — tracks hot symbols
    across ChartPanel, EnhancedTickerModal, SentComV5View
  - Extend `DataFreshnessBadge.jsx` — `onClick` opens the inspector
  - Backend: `GET /api/live/freshness-snapshot` — aggregates the 3 pipes
    + hot-symbol cache TTL into one response




## 🗂️ Backlog — UX Power-User Layer (not started, user approved for later)

### [BL-01] Keyboard Shortcuts + Symbol Command Palette
- **`⌘K` / `Ctrl+K`** → opens centered fuzzy-match symbol picker. Tiers: (1) open positions, (2) today's setups/alerts, (3) watchlist, (4) recent stream symbols, (5) full 264K universe from `ib_historical_data` (lazy, cached in localStorage daily).
- **`/`** → focus the V5 chat input.
- **`Esc`** → close active modal/palette. **`?`** → shortcut cheatsheet overlay.
- New files: `CommandPaletteV5.jsx`, `useKeyboardShortcuts.js`. New backend (optional): `GET /api/ib-collector/symbol-universe` (distinct symbols).
- Reuses existing `handleOpenTicker` + 3-min modal cache. ~1 hour effort.

### [BL-02] Hover Tooltips Everywhere
- Add explanatory hover tooltips to virtually every data point and UI feature in V5 (and across the app): HUD metrics, scorecard values, gate scores, R multiples, DRC states, pipeline stage chips, chart header abbreviations (E/SL/PT/R:R), briefing timings, scanner metric abbreviations (RVol, Sharpe, P(win)), etc.
- Goal: user never has to guess what a number means. Teach the platform through discovery.
- Suggested approach: shadcn `Tooltip` component, centralized `/utils/fieldDefinitions.js` as single source of truth (label + short explanation + optional formula), reusable `<FieldTooltip field="gate_score">…</FieldTooltip>` wrapper.

### [BL-03] Training Integrity Card on V5 HUD
- Small card showing per-phase health of the last training run: `models_trained_this_run / expected_models` as a color-coded bar, red when 0% of a phase completed, yellow when partial, green when 100%.
- Would have caught 2026-04-23's silent-zero P3/P5/P7 phases in seconds instead of the hours of mongo detective work we did today.
- Source: `/api/ai-training/status.pipeline_status.phase_history[].models_trained` vs configured `expected_models`. Data already exists; just needs a card.
- Bonus: add a "Last Full Retrain" timestamp + 3 avg accuracy bands (`< 50%` red, `50-55%` yellow, `> 55%` green) so the user always knows at a glance whether the models are trustworthy.
- ~30 min effort.




## TODO (user note 2026-04-22)
- 🟡 Revisit `MorningBriefingModal.jsx` to look like the user's "newer more in-depth briefing modal" (screenshot they shared). Current V5-restyled modal is a minimal summary; they want richer detail. Revisit after Stage 2d polish.



## Backlog — P1 / P2 ideas captured but not yet scheduled

### Regime-Aware Strategy Phase Auto-Throttle (captured 2026-04-22)
**Idea:** In `trading_bot_service.py`, track rolling 30-day per-side Sharpe (LONG vs SHORT aggregated across all paper/live setups). When one side outperforms the other by >1.0 Sharpe, auto-tilt position sizing (e.g. 60/40 short-heavy when shorts dominate, back to 50/50 when parity returns). Also works as an early-warning: if BOTH sides' rolling Sharpe drop below 0.5 at the same time, auto-pause new entries and flag for review (likely regime shift the models haven't caught up to).

**Why it matters:** current state has 3 shorts paper-promoted and longs still recovering — hardcoded sizing doesn't reflect where the measurable edge actually lives. Auto-throttle lets the bot compound on its proven side without manual tuning every week, and gives us a principled way to exit a bad regime before it costs too much.

**Implementation sketch:**
- Query `bot_trades` for last 30d, compute per-side Sharpe + expectancy by setup-type.
- Add `position_multiplier_by_side` to `opportunity_evaluator.calculate_position_size` (default 1.0 for both).
- Persist the current tilt + reasoning to a new `strategy_tilt_snapshots` Mongo collection (audit trail).
- Expose via `GET /api/trading-bot/strategy-tilt` for the dashboard.
- Unit tests for Sharpe crossover, parity, dual-collapse pause.

**Status:** NOT STARTED · P1 · deferred until post-Phase-13-v3 (need LONG side producing real data first so tilt math isn't lopsided by definition).

### CRITICAL FIX #2 — Model Protection gate was class-collapse-blind (2026-04-22, post first retrain)

**Finding:** After shipping CRITICAL FIX #1, the Phase 1 retrain ran successfully and produced a class-balanced `direction_predictor_5min` v20260422_162431 with accuracy 43.5%, UP recall ~0.30, macro-F1 0.36. BUT the Model Protection gate rejected it because `0.4346 < 0.5351` (old model's accuracy). Problem: the old collapsed model "wins" accuracy precisely BY collapsing — predicting the DOWN majority class on every bar gives high aggregate accuracy in bearish training windows while yielding zero tradeable LONG signals. Classic Goodhart's law — we were measuring the wrong thing.

**Fix (`services/ai_modules/timeseries_gbm.py` L461–L540, `_save_model`):**
- Replaced `new.accuracy > old.accuracy` with a multi-metric gate driven by per-class recall and macro-F1.
- **Escape hatch**: if active is class-collapsed (`recall_up < 0.05`), promote ANY new model whose UP recall beats active AND DOWN recall ≥ 10%. This unblocks the specific situation we're in right now.
- **Normal path** (once active is healthy): require new UP recall ≥ 10% AND DOWN recall ≥ 10% AND new macro-F1 ≥ 0.92 × active macro-F1. The 8% macro-F1 slack allows for noise while preventing outright regression.
- Logs much richer: both accuracy AND macro-F1 AND per-class recall for active vs new.

**Regression tests — `tests/test_model_protection_class_collapse.py` (8 new, all passing):**
- `test_promote_when_active_is_collapsed_and_new_improves_up_recall` — reproduces the EXACT Phase 13 v2 situation; asserts the fix now promotes.
- Escape hatch must still reject if new's DOWN recall is broken.
- Normal path rejects any model with UP recall < 10%, DOWN recall < 10%, or macro-F1 below the 92% floor.
- Legacy active models without recall fields → treated as collapsed → new promotes.

**Force-promote command (one-shot unblock for current archived model):**
```bash
# on Spark, outside Python:
mongo tradecommand --eval '
  const a = db.timeseries_models_archive.findOne(
    {name:"direction_predictor_5min", version:"v20260422_162431"},
    {_id:0}
  );
  if (!a) { print("archived model not found"); quit(1); }
  a.updated_at = new Date();
  a.promoted_at = new Date();
  db.timeseries_models.updateOne({name:"direction_predictor_5min"}, {$set: a}, {upsert:true});
  print("PROMOTED direction_predictor_5min v20260422_162431");
'
```

Or future retrains will auto-promote once the protection fix is pulled + backend restarted.



### CRITICAL FIX #1 — Generic direction_predictor class-balance (2026-04-22, Phase 13 v2 post-mortem)

**Finding:** Phase 13 v2 revalidation showed 10/10 LONG setups with `trades=0` in Phase 1 (shorts promoted cleanly: SHORT_SCALP 1.52 Sharpe, SHORT_VWAP 1.76, SHORT_REVERSAL 1.94). Root cause found via code review: `revalidate_all.py` loads ONE model for AI filtering — `direction_predictor_5min` — and that model is trained by `TimeSeriesAIService.train_full_universe` in `services/ai_modules/timeseries_service.py`. That path builds `xgb.DMatrix(...)` without `weight=` and calls `xgb.train()` directly, **completely bypassing** `TimeSeriesGBM.train_from_features()` where the 2026-04-20 class-balance fix was applied. Net effect: the generic directional model never gets per-class sample weights, collapses to the bearish-majority class (DOWN/FLAT), argmax never resolves to UP, and every LONG setup Phase 1 backtest records `trades=0`.

**Fix (`services/ai_modules/timeseries_service.py` L1111–L1141):**
- Compute `compute_per_sample_class_weights(y_train, num_classes=3, clip_ratio=5.0)` via the existing `services.ai_modules.dl_training_utils` helpers (same math used by `train_from_features` for setup-specific models).
- Pass as `weight=` to `xgb.DMatrix` for `dtrain`. Validation DMatrix left uniform (weights are a training-signal concern only).
- Log line `[FULL UNIVERSE] class_balanced sample weights applied (per-class weights=[…], sample_w_mean=1.000)` — mirrors the log pattern the user greps on Spark.
- Non-fatal: wrapped in `try/except` falling back to uniform with a warning so an 8-hour retrain never dies on a class-balance edge case.

**Diagnostic script — `backend/scripts/diagnose_long_model_collapse.py`:**
- Probes `direction_predictor_5min` + every LONG setup-specific 5m/1m model across 20 liquid symbols, ~120 rolling predictions each.
- Classifies each into MODE A (2-class regression), MODE B (3-class UP never wins argmax), MODE C (argmax UP but below threshold), MODE D (code-level miss), HEALTHY, or MODEL MISSING.
- Dumps `/tmp/long_model_collapse_report.md` + `.json`.
- Runs on Spark: `PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/diagnose_long_model_collapse.py`.

**Regression tests (17 new, all passing):**
- `tests/test_diagnose_long_model_collapse.py` (11): tally math on empty/all-UP/all-FLAT/mixed, classifier covers every MODE branch + missing-model + no-data, `LONG_ONLY_SETUPS` excludes shorts.
- `tests/test_train_full_universe_class_balance.py` (6): class-weight math proportional to Phase 13 v2 skew, `clip_ratio=5` respected, **source-level guards** that train_full_universe (a) passes `weight=` to DMatrix, (b) logs `[FULL UNIVERSE] class_balanced`, (c) imports the class-balance helpers, (d) wraps the block in a non-fatal try/except. These guards prevent a silent regression back to uniform weights.

**Full session suite: 63/63 passing** in diag + class-balance + dl_utils + xgb_balance + resolver + smb_profiles scopes.

**User verification on Spark after git pull + restart + retrain:**
```bash
# 1. After retrain, confirm the NEW log line appears for direction_predictor training:
grep "\[FULL UNIVERSE\] class_balanced" /home/spark-1a60/Trading-and-Analysis-Platform/backend/training_subprocess.log

# 2. Run the forensic diagnostic (quick — ~2-3 min):
cd ~/Trading-and-Analysis-Platform
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/diagnose_long_model_collapse.py
cat /tmp/long_model_collapse_report.md

# 3. Rerun Phase 13 v2:
/home/spark-1a60/venv/bin/python backend/scripts/revalidate_all.py 2>&1 | tee /tmp/phase13_v3.log
```
Expected: LONG setups show non-zero Phase 1 trade counts (100s like the SHORTs) and at least some LONG models promote.

### Option A — SMB Profiles + Resolver Ordering (2026-04-22)
**Finding:** Phase 13 v2 coverage-trace confirmed 3/12 scanner names had no training profile: `opening_drive`, `second_chance`, `big_dog`. These are distinct SMB patterns (not family variants of SCALP/VWAP/REVERSAL), so pure routing can't help — each needs a dedicated model. Also confirmed: XGBoost class-balance + DL purged-split fixes from prior session BOTH ACTIVE in the 8.8hr retrain.

**Changes in `setup_training_config.py`:**
  - `"OPENING_DRIVE"` — 2 profiles (5 mins / 1 min, forecast_horizon 12 / 30). Intraday opening continuation, same feature class as ORB.
  - `"SECOND_CHANCE"` — 1 profile (5 mins, forecast_horizon 12). Breakout re-try on 5-min bars.
  - `"BIG_DOG"` — 2 profiles (5 mins / 1 day). The 1-day profile has forecast_horizon=3 for multi-day holds, scale_pos_weight=1.1 for the bullish trend bias big-dog plays carry.
  - All use `num_classes=3` (triple-barrier) so they pick up the class-weighted CE + uniqueness weights automatically on next retrain.

**Changes in `timeseries_service._resolve_setup_model_key`:**
  - Added `OPENING_DRIVE / SECOND_CHANCE / BIG_DOG` to the family-substring match tuple so scanner variants like `big_dog_rvol` or `second_chance_breakout` route correctly.
  - **Ordering fix**: compound SMB keys go FIRST in the tuple. Without this, `SECOND_CHANCE_BREAKOUT` was matching BREAKOUT (substring hit earlier in iteration) instead of SECOND_CHANCE.

**Regression coverage** — `backend/tests/test_smb_profiles.py` (9 tests): each profile declared correctly, required fields present, generated model names match loader expectations, exact-name routing, family-substring routing (including the ordering bug regression), SMB short fallback to base, no-models-loaded fallback. All pass.

**Full session suite: 79/79 passing** (added 9 SMB tests to the previous 70).

**User impact after Save+Pull+Next-Retrain:**
- Coverage rate: 75% → ~100% for the 12-name scanner sample
- 5 new models: `opening_drive_5min_predictor`, `opening_drive_1min_predictor`, `second_chance_5min_predictor`, `big_dog_5min_predictor`, `big_dog_1day_predictor`
- Existing retrain already added `class_balanced` + `Purged split` to all models → these will too
- Live trading: scanner alerts for `opening_drive`, `second_chance`, `big_dog` (all 3 already in `_enabled_setups`) will hit a dedicated model instead of the general direction_predictor

### Paper-Mode Enablement for the 3 Promoted Shorts (2026-04-24)
**Change:** Added REVERSAL-family and VWAP-family scanner base names to `trading_bot_service._enabled_setups`:
  - `reversal`, `halfback_reversal`, `halfback` — so scanner alerts for REVERSAL-style setups (e.g. `halfback_reversal_short`) pass the enabled-setups filter and reach `predict_for_setup` → `SHORT_REVERSAL` model (Sharpe 1.94, +7.6pp edge).
  - `rubber_band_scalp` — was a gap; scanner emits `rubber_band_scalp_short` which strips to `rubber_band_scalp` (NOT `rubber_band`), which wasn't enabled.
  - `vwap_reclaim`, `vwap_rejection` — additional scanner variants that route to `SHORT_VWAP` (Sharpe 1.76).
  
Comments inline document why each base was added — so the next person understands the filter chain.

**User promotion commands (run on Spark after pull + restart):**
```
# Promote each of the 3 proven shorts to PAPER phase
for STRAT in short_scalp short_vwap short_reversal; do
  curl -s -X POST "http://localhost:8001/api/strategy-promotion/promote" \
    -H "Content-Type: application/json" \
    -d "{\"strategy_name\":\"$STRAT\",\"target_phase\":\"paper\",\"approved_by\":\"user\",\"force\":false}" \
    | python3 -m json.tool
done

# Verify they're now in PAPER
curl -s http://localhost:8001/api/strategy-promotion/phases | python3 -m json.tool | grep -iE "short_(scalp|vwap|reversal)|paper"
```

If the first promotion call fails with "not found" or "not registered", the strategy may need to be registered first — paste the error and we handle it.

### Startup Model-Load Consistency Diagnostic SHIPPED (2026-04-24)
**Rationale:** The latent bug above (17 trained, 0 loaded) went undetected for weeks because nothing cross-checked `timeseries_models` vs `_setup_models`. This is the safety net.

**Fix:**
- New `TimeSeriesAIService.diagnose_model_load_consistency()` — scans `timeseries_models` collection, compares against in-memory `_setup_models` keyed by `model_name`, produces a report with `trained_in_db_count` / `loaded_count` / `missing_count` / `missing_models` + per-profile `by_setup` rows with `status: loaded|missing_in_memory|not_trained`.
- Auto-runs at end of `_load_setup_models_from_db()` — **logs a WARNING on boot if anything is missing in memory**. Would have caught the 2026-04-24 bug at the first startup after the XGBoost migration.
- Exposed at `GET /api/ai-training/model-load-diagnostic` for on-demand inspection.
- Handles `_db=None` gracefully (structured error, no exception).

**Regression coverage** — `backend/tests/test_model_load_diagnostic.py` (9 tests): detects missing, clean-state, partial load, ignores failed-deserialize GBMs, by_setup coverage + status values, `_db=None` safe, endpoint wrapper + 500 error path. All pass.

**Full session suite: 70/70 passing.**

**User check on Spark after pull + restart (next boot will run the diagnostic automatically):**
```
# 1. Look for the consistency line in backend.log
grep -E "Model load consistency" /tmp/backend.log

# 2. On-demand check anytime
curl -s "http://localhost:8001/api/ai-training/model-load-diagnostic" | python3 -m json.tool | head -40
```
If you see `Model load consistency: 17/17 trained models reachable` on boot, the fix worked. If you see `MISSING:` followed by names, the loader still isn't finding them and we dig deeper.

### CRITICAL BUG FIX — setup models never loaded at startup (2026-04-24)
**Finding:** After shipping the resolver, live test on Spark showed `loaded_models_count: 0` from resolver-trace — but `/api/ai-modules/timeseries/setups/status` reported 17 trained models. Investigation:
  - Training writes to `timeseries_models` collection (xgboost_json_zlib format)
  - Startup loader `_load_setup_models_from_db()` only scanned `setup_type_models` collection (legacy xgboost_json format, effectively empty)
  - `predict_for_setup` does a pure in-memory `_setup_models.get()` lookup, no DB fallback
  - **Net effect: every `predict_for_setup` call was silently falling through to the general direction_predictor, including calls that should have used the 3 promoted SHORT_* models.** Option A routing was academically correct but had nothing to route to. Latent bug present since the XGBoost migration.

**Fix:** Extended `_load_setup_models_from_db()`. After the legacy loop, it iterates every declared profile in `SETUP_TRAINING_PROFILES`, computes `get_model_name(setup, bar)`, and looks it up in `timeseries_models`. Uses the existing `TimeSeriesGBM.set_db() → _load_model()` path which already handles xgboost_json_zlib deserialization, feature_names restore, num_classes restore. Skips dups; skips models that fail deserialization.

**Regression coverage** — `backend/tests/test_setup_models_load_from_timeseries.py` (5 tests): primary load path, empty DB safe, failed-deserialize not cached, legacy not overwritten, `_db=None` early-exit.

**Full session suite: 61/61 passing.**

**User verification on Spark after pull + restart:**
```
curl -s "http://localhost:8001/api/ai-training/setup-resolver-trace?batch=SHORT_SCALP,SHORT_VWAP,SHORT_REVERSAL,rubber_band_scalp_short,vwap_reclaim_short" | python3 -m json.tool
```
`loaded_models_count` should now report ≥17 and all shorts should show `resolved_loaded: true`.


## Active P0 Blockers
### 🟢 Pusher double-execution bug — FIXED (pending verification on Windows)
- **Root cause**: TWS mid-session auto-upgrade caused the pusher's IB client connection (fixed clientId=15) to reconnect with stale session state. Previously-submitted MKT orders got replayed by TWS as if new, causing 2×-3× execution for each flatten order.
- **Fixes applied (2026-04-20)**:
  1. `ib_data_pusher.py` — `_recently_submitted` in-memory cache stamps each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10-min window.
  2. `StartTradeCommand.bat` — pusher clientId now randomized 20–69 each startup (`set /a IB_PUSHER_CLIENT_ID=%RANDOM% %% 50 + 20`). TWS can't replay a clientId it's never seen.
  3. `routers/portfolio.py` flatten endpoint — refuses to fire if pusher snapshot > 30s old (prevents flattening against stale positions).
  4. Pre-flight cancel of prior `flatten_*` orders (already done in first pass).
- **Verification plan for next session**: re-enable TWS API, restart pusher with new fixes, queue a single test order, confirm IB shows exactly one fill.

### 🚨 Security — paper password was committed to git
- `StartTradeCommand.bat` had `set IB_PASSWORD=Socr1025!@!?` hardcoded (line 30, pre-fix).
- **Fixed**: password moved to local `.ib_secret` file loaded via `call "%REPO_DIR%\.ib_secret"`. `.gitignore` updated to cover `*.secret`. `documents/scripts/README_SECRETS.md` explains setup.
- **User action required**: rotate the paper password in IB Account Management, then create `.ib_secret` on the Windows PC with the new password.


## P1 Outstanding
- Phase 13 revalidation: `backend/scripts/revalidate_all.py` against the fixed fail-closed validator (was next after Morning Briefing)
- Phase 6 Distributed PC Worker: offload CNN/DL training to Windows PC over LAN
- Rebuild TFT / CNN-LSTM with triple-barrier targets (binary up/down → majority-class collapse)
- Wire FinBERT into confidence gate as Layer 12
- Wire confidence gate into live validation


## Model Inventory & Deprecation Status (2026-04-21)

| Layer | Model family | Count | Status | Notes |
|---|---|---|---|---|
| **Sub-models** | XGBoost `setup_specific_<setup>_<bs>` | 17 long + 17 short = 34 | ✅ Keep (retraining now) | Tabular direction predictor, uses FFD+CUSUM+TB |
| | XGBoost `direction_predictor_<bs>`, `vol_<bs>`, `exit_*`, `risk_*`, `regime_*`, `sector_*`, `gap_*` | ~65 | ✅ Keep | Generic + specialist tabular models |
| | DL `cnn_lstm_chart` | 1 | ✅ Keep | 1D CNN+LSTM on OHLCV sequences; feeds Phase 2E tabular arm |
| | DL `tft_<bs>`, `vae_<bs>` | 2 | ✅ Keep | Temporal fusion + regime encoder |
| | FinBERT sentiment | 1 | ✅ Keep | Layer 12 of confidence gate (pending wire-in) |
| | Legacy `cnn_<setup>_<bs>` | 34 | 🗑 **Deprecate post-Phase 2E** | Strict subset of Phase 2E; no unique value |
| **Meta-labelers** | XGBoost `ensemble_<setup>` (Phase 8) | 10 | ✅ Keep | Tabular meta-labeler, P(win). **Phase 2C equivalent.** Just redesigned 2026-04-21 |
| | Phase 2E `phase2e_<setup>` (visual+tabular) | 0 | 🔨 **Build** | Hybrid multimodal meta-labeler; will supersede legacy CNN |
| **Fusion** | `P(win)_final = w_tab·P_tab + w_vis·P_vis` | 0 | 🔮 Future | After both meta-labelers prove individual edge |

**Net reduction once Phase 2E ships**: 34 legacy CNN models → ~10 Phase 2E models. Phase 9 removed from training pipeline. Full-retrain time drops from ~7h to ~5h.


## Post-Retrain Roadmap (proper sequencing)

The order below is intentional — each step depends on artifacts from the prior step.

### Step 1 — [USER] Full retrain with all flags
- `TB_USE_CUSUM=1 TB_USE_FFD_FEATURES=1`
- Populates `timeseries_models.scorecard` with 15-metric grades across all current setups.
- Produces the first deflated-Sharpe-validated, uniqueness-weighted, CUSUM+FFD-featured model set.

### Step 1.5 — Setup Coverage Audit (run immediately after retrain)
Run `PYTHONPATH=backend python backend/scripts/audit_setup_coverage.py`.

Writes `/tmp/setup_coverage_audit.md` summarising, per taxonomy code:
- # of tagged trades across `trades` / `bot_trades` / `trade_snapshots` / `live_alerts`
- Win rate + avg R-multiple
- Verdict: `trainable` / `thin` / `negative_edge` / `too_few` / `unknown_outcome`
- Highlighted Phase 2E Tier-1 candidates (visual-pattern setups with enough data).

This is the critical bridge: TRADING_TAXONOMY.md defines ~35 SMB setups but the
XGBoost pipeline only trains 10 long + 10 short generic families. The audit tells
us which of the 35 have the journal coverage to warrant dedicated (setup, bar_size)
XGBoost + CNN model pairs in Step 5/Step 6.

Inputs to Step 2 (scorecard triage): A-grade generic model + strong audit
coverage  →  split into dedicated setup-specific model.

### Step 2 — Scorecard triage
- Sort all models by composite grade (A-F).
- **Delete** setups grading D/F that can't be salvaged (REVERSAL/5min almost certainly in this bucket — see `/app/memory/notes_sweep_observations.md`).
- **Widen PT/SL sweep grid** on daily setups (all converged to pt=1.5/sl=1.5/max_bars=5 — suspicious).
- Free up training budget for new setups in Step 5.

### Step 3 — Phase 2C: XGBoost Tabular Meta-Labeler ✅ COMPLETED 2026-04-21
**Consolidated into Phase 8 Ensemble** (see "Phase 8 Ensemble — REDESIGNED as Meta-Labeler" above).
Each `ensemble_<setup>` now IS the Phase 2C tabular bet-sizer: P(win | setup_direction, meta_features).

### Step 3.5 — Wire bet-sizer into `trading_bot_service.py` (NEXT)
- `confidence_gate.py` → add `_get_meta_label_signal(setup_type, features)` reading `ensemble_<setup>`
- Expose `meta_label_p_win` in confidence gate result
- `opportunity_evaluator.calculate_position_size()` → new `meta_multiplier` (capped [0.3, 1.5]) alongside volatility + regime multipliers
- Skip trade if `P(win) < 0.50` (meta-labeler says "no edge")
- Log `meta_label_p_win` + `meta_multiplier` in `trade.entry_context` for backtest uplift tracking
- Fallback: absent `ensemble_<setup>` → unchanged sizing (safe)

### Step 4 — Phase 6: Distributed PC Worker infrastructure
- Training coordinator on Spark offloads CNN/DL jobs to Windows PC over LAN.
- REST endpoint contract + job queue + heartbeat + result sync.
- Enables Step 5 (CNN visual meta-labeler would otherwise bottleneck Spark's GB10).

### Step 5 — Phase 2E: Setup-Specific Visual CNN Meta-Labeler ⭐ (high conviction)
Scalp setups (especially SMB-style) are visually defined. Tabular features flatten the chart into 46 numbers; a CNN trained on the actual chart image sees the shape.

**Architecture:** Hybrid multimodal — chart-image CNN + tabular MLP → concat → classifier.

**Pipeline:**
1. **Chart rendering** — OHLCV window → 96×96 or 128×128 PNG with candlesticks, volume bars, and setup-relevant overlays (9EMA/21EMA/VWAP). No axis labels; pure visual signal.
2. **Shared backbone** — train one CNN (EfficientNet-Small or similar) on ALL setups' charts with triple-barrier labels. Self-supervised contrastive pre-training optional.
3. **Per-setup fine-tune heads** — each setup gets a lightweight fine-tuning head on ~5-10k labeled examples.
4. **Tabular fusion** — concat MLP features (46 base + setup + regime + VIX + sub-model probs from cnn_lstm/TFT) with backbone visual features before the classifier head.
5. **Inference** — López de Prado meta-labeling, visual edition: XGBoost says "rubberband scalp candidate" → multimodal CNN sees the chart + context → returns `P(win)`. Combined into bet size.
6. **Explainability** — Grad-CAM activation overlay surfaced to NIA UI so user can verify the CNN is learning real patterns (exhaustion wick, volume climax) vs spurious noise.

**Distribution (requires Step 4):** Spark GB10 trains the shared backbone once a week; Windows PC fine-tunes per-setup heads overnight.

### Step 5.5 — DEPRECATE legacy `cnn_<setup>_<bs>` (34 models) — post-Phase 2E
The current 34 per-setup CNN models in `cnn_models` collection are a **strict subset** of what Phase 2E does:
- Image-only input (no tabular fusion)
- Isolated per-setup training (~2K samples each, no shared backbone transfer learning)
- 17-class pattern head is tautologically 100% (every sample has same setup_type); only the win-AUC head carries signal

**Cutover plan:**
1. Phase 2E models go live + validated on scorecard (≥2 weeks shadow mode)
2. Switch `confidence_gate.py` to read `phase2e_<setup>` instead of `cnn_<setup>`
3. **Remove Phase 9 from the training pipeline** (shaves ~1h 51min off every full retrain — from ~7h to ~5h)
4. Archive `cnn_models` collection (30-day backup), then drop
5. Remove `chart_pattern_cnn.py` + per-setup loop in `cnn_training_pipeline.py`
6. Scorecard: replace 34 `cnn_<setup>` rows with ~10 `phase2e_<setup>` rows

**Keep** `cnn_lstm_chart` (DL model) — different modality (1D CNN+LSTM on OHLCV sequences, not images). Its output feeds into Phase 2E's tabular arm as a stacking feature.

### Step 6 — Add SMB-specific setups (tiered)
Only after visual CNN infrastructure exists, and only for setups the CNN/scorecard analysis justifies.

**Tier 1 — Scalp/Intraday (5-min and 1-min):**
- `RUBBERBAND_SCALP` (long + short) — 2+ ATR stretch from 9EMA/VWAP → reversion scalp
- `EMA9_PULLBACK` (long + short) — trending stock pulls to 9EMA on lower volume → continuation
- `FIRST_RED_CANDLE` / `FIRST_GREEN_CANDLE` — first reversal candle after parabolic move

**Tier 2 — Day-structure:**
- `OPENING_DRIVE_REVERSAL` (5 min) — exhausted opening drive fade
- `HALFBACK_REVERSION` — 50% morning-range retrace
- `INSIDE_DAY_BREAKOUT` (1 day)

**Tier 3 — Cross-instrument (needs SPY sync in training data):**
- `RS_VS_SPY_LONG` / `RW_VS_SPY_SHORT` — relative strength divergence vs SPY

Each new setup needs: detector in `setup_pattern_detector.py`, feature extractor in `setup_features.py`/`short_setup_features.py`, PT/SL sweep entry, and (if visual) chart-render config.


## P2 / Backlog
- Motor async MongoDB driver migration (replace sync PyMongo in hot paths)
- Per-signal weight optimizer for gate auto-tuning
- Earnings calendar + news feed in Chat
- Sparkline (12-wk promotion rate) on ValidationSummaryCard
- `server.py` breakup → `routers/` + `models/` + `tests/`


