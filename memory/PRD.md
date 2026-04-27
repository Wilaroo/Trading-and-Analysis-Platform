# TradeCommand / SentCom — Product Requirements

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

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.

## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)



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



## TODO (user note 2026-04-22)
- 🟡 Revisit `MorningBriefingModal.jsx` to look like the user's "newer more in-depth briefing modal" (screenshot they shared). Current V5-restyled modal is a minimal summary; they want richer detail. Revisit after Stage 2d polish.


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

## Key API surface
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/assistant/coach/morning-briefing` — coach prompt only (not position source)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not

## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + new flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script

## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)

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
