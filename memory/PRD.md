# TradeCommand / SentCom — Product Requirements

> **🔜 2026-06-12 — v322r (leveraged scalp exclusion + ACMR EOD-escape probe) built/tested,
> patcher at paste.rs/5K39N — AWAITING OPERATOR APPLY + probe run.** M0 stack (base/a/b/c/d)
> deployed + committed; awaiting live-session ladder validation. See CHANGELOG top entry.
> DGX patcher workflow ONLY — no testing_agent, no git from bash. Respond in English.

> **🔜 FORKED 2026-06-11 — NEXT AGENT: read `/app/memory/NEXT_SESSION_TIER1_PLAN.md` FIRST.**
> All v319/b/c/d ML-integrity fixes are DEPLOYED + committed (DGX main @ d96def40). Full
> leakage audit done (clean). **Tier 1a (CPCV for GBMs, v320) + Tier 1b (backtest execution
> costs, v320b) are BUILT + container-tested — patchers on paste.rs mOsoh / UGzyM, tests
> 9ukb3 / 9Ryar — AWAITING OPERATOR APPLY on the DGX** (see CHANGELOG top entry). Pending
> DGX ops AFTER apply: retired-model eviction (paste.rs/wL0HT) + FULL RETRAIN (models then
> get CPCV-validated) + rotate Atlas password. DGX patcher workflow ONLY — no
> testing_agent, no git from bash. Respond in English.

> **⚠️ AGENTS — READ THIS BLOCK BEFORE ANY CODE CHANGE.**
>
> Open `/app/AGENTS.md` and read **§0 TL;DR** + any sections relevant
> to your task (typically §6.5 for journey context, §11.5 for the
> edit checklist). If you cannot or will not open the file, the 5
> rules below are the bare minimum — violating any of them has cost
> real money in production:
>
> 1. **`close_trade`, `submit_with_bracket`, kill-switch are SAFETY-
>    CRITICAL.** Fork via `_custom` siblings; never patch in place.
>    *(v19.34.123: $25k loss when kill-switch was bypassed.)*
> 2. **NEVER close at IB without `_cancel_ib_bracket_orders` + 8s + 5s
>    retry.** *(2026-05-20: IB position flipped direction.)*
> 3. **`_open_trades` is keyed by `trade_id`, NOT symbol.** Iterate
>    `.values()` and filter. *(b415ed5f phantom incident.)*
> 4. **`position_reconciler` MUST skip `entered_by="reconciled_excess_*"`**
>    on the orphan path or it duplicates trades every 60s. *(v19.34.22.)*
> 5. **Always project `{"_id": 0}` on Mongo reads.** ObjectId is not
>    JSON-serializable.
>
> Full context, why each rule exists, and the journey maps are in
> `/app/AGENTS.md`. Treat this PRD as the *what we're building*; treat
> AGENTS.md as the *how to safely touch it*.

> Lean, static spec. Dated work history lives in `CHANGELOG.md`.
> Open priorities and backlog live in `ROADMAP.md`.
>
> **Rules for the agent (keep these docs alive):**
>   - Ship something → prepend a `## YYYY-MM-DD — <title> — SHIPPED`
>     section to **CHANGELOG.md** (Why / Scope / Verification).
>   - Priority shifts → reorder **ROADMAP.md**; promoted item moves up,
>     completed item is removed and recorded in CHANGELOG.
>   - Architecture / API contract / hardware topology changes → edit
>     **PRD.md** (this file).
>   - Trap / journey / convention changes → edit **AGENTS.md**.
>   - Never silently drop history; never let `🔴 Now / Near-term` go
>     stale across more than one task.

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.


## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)




## Key API surface
- `GET /api/diagnostic/position-pnl-audit` — **v19.34.142d/e (2026-02-13)** — per-symbol diff of bot vs IB unrealized PnL with verdict classification (`OK`, `DRIFT_ABS`, `DRIFT_PCT`, `PHANTOM_IN_BOT`, `MISSING_IN_BOT`, `QTY_SIGN_MISMATCH`, `QTY_MAGNITUDE_MISMATCH`). Magnitude-mismatch rows include `ledger_fragments[]` listing every open BotTrade slice for the symbol (trade_id, shares, remaining_shares, setup_type, entered_by, stop_order_id, entry_time) so the operator can pinpoint which slice(s) over-booked vs IB. KMB phantom-share crisis use case: bot=144 / IB=55 fires a high-severity action with one-line `POST /api/trading-bot/reconcile-share-drift` remediation. Tolerance: `max(1 share, 1% of ib_qty)`.
- `GET /api/diagnostic/bracket-status[?symbols=A,B,C]` — **v19.34.143b (2026-02-13)** — live snapshot of every open fragment in `_open_trades` with `stop_order_id`, `is_simulated_stop`, `in_live_orders`, and a `status` (`BRACKETED / NAKED_NO_STOP / NAKED_SIM / NAKED_STALE`) per row. Cross-references against the 3-tier open-orders resolver used by `_naked_position_sweep`. Used by `scripts/verify_naked_orphan_healing.py` to confirm the v19.34.143 emergency-stop sweep healed reconciled orphans within the expected 60s cadence.
- `POST /api/trading-bot/sync-entry-prices` — **v19.34.148 (2026-02-13)** — manual reconciliation that snaps every open BotTrade's `entry_price` / `fill_price` to IB's live `avgCost`. Body: `{dry_run, symbols, tolerance_per_share}`. Returns per-trade synced/skipped report with signed `implied_pnl_correction` (direction-aware). Persists to `bot_trades` with audit columns. Also fires nightly via `TradingScheduler._run_entry_price_sync` at 16:35 ET Mon–Fri.
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/sentcom/positions` — bot + IB merged positions; injects live `_pushed_ib_data.quotes` into `current_price` so PnL doesn't lag the timer-driven `position_manager.update_open_positions` (2026-05-01 v19.22.3); exposes V5-rich fields `scan_tier / trade_style / reasoning[] / exit_rule / scale_out_state / trailing_stop_state / risk_reward_ratio / remaining_shares` (v19.23)
- `GET /api/sentcom/stream/history?symbol=X&minutes=N` — Used to fetch `sentcom_thoughts` for chart bubbles and per-symbol bot reasoning timeline (v19.23)
- `GET /api/diagnostics/unmatched-short-closes?days=N&symbol=X&emit_warning=bool` — **v19.34.16 (2026-05-06)** — flags Sell Short / Buy to Cover transactions in `ib_executions` that have NO matching `bot_trades` row with `direction=short`. FIFO inventory walk identifies SHORT round-trips (sell-short → buy-to-cover) and residual still-open shorts. When findings exist, emits `unmatched_sell_short_or_btc_v19_34_16` HIGH-severity stream warning. Closes the leak class v19.34.15a is designed to prevent. Companion to `scripts/audit_ib_fill_tape.py --bot-trades-json` cross-check.
- `GET /api/trading-bot/share-drift-status?symbols=X,Y` — **v19.34.18 (2026-05-06)** — read-only diagnostic for the v19.34.15b drift loop. Returns `{loop:{alive, task_exception, feature_flag, interval_s}, diag:{tick_count, last_tick_at, last_tick_status, last_tick_error, last_result_summary, last_drifts_detected, last_drifts_resolved, consecutive_failures}, pusher_connected, per_symbol:[{symbol, bot_qty_signed, ib_qty_signed, drift, would_act, verdict}], summary}`. Built to investigate why 93sh FDX + 338sh UPS naked drift went undetected. Pairs with the existing `POST /api/trading-bot/reconcile-share-drift` (`dry_run` flag) for full investigate-then-heal flow.
- `POST /api/trading-bot/reconcile-share-drift` — **v19.34.15b (2026-05-06)** — share-COUNT drift reconciler for already-tracked symbols. Detects 3 drift classes: `excess_unbracketed` (IB > bot → spawns `reconciled_excess_slice` BotTrade with 1% stop / 1R target, `entered_by="reconciled_excess_v19_34_15b"`), `partial_external_close` (IB < bot, IB > 0 → LIFO shrink of `remaining_shares`, newest trade drained first), `zero_external_close` (IB == 0 → closes bot_trade with `close_reason="external_close_v19_34_15b"`). Body: `{drift_threshold:int=1, auto_resolve:bool=true, dry_run:bool=false}`. Forensic write to `share_drift_events` Mongo collection (TTL 7d). Backed by 24/7 background loop (`SHARE_DRIFT_RECONCILE_ENABLED=true`, `SHARE_DRIFT_RECONCILE_INTERVAL_S=30`). Closes the v19.34.15a `[REJECTED: Bracket unknown]` race blind spot — orphan reconciler skips already-tracked symbols, so this is the only path that detects share-count drift on tracked positions.
- `POST /api/trading-bot/reconcile` — **v19.24 (2026-05-01)** — proper write-through reconcile of IB-only orphan positions. Materializes real `bot_trades` + in-memory `_open_trades` so manage-loop can actively trail stops / scale-out / EOD-close positions the bot didn't originate. Safety: `{all:true}` requires `{confirm:"RECONCILE_ALL"}`; stop-already-breached skip; idempotent (already-tracked skip). Body: `{symbols:[...]}` or `{all:true, confirm:"RECONCILE_ALL"}` with optional `stop_pct`/`rr` overrides. Counterpart to lazy-reconcile in `sentcom_service.get_our_positions` (v19.23.1) which only patched UI display.
- `GET /api/sentcom/chart-tail?symbol=X&timeframe=5min&since=<unix_ts>&cap=50` — **v19.25 (2026-05-01)** — incremental refresh endpoint. Returns ONLY new bars + matching indicator points + new markers since `since`. Reads through `chart_response_cache` (Mongo-backed TTL cache, 30s intraday / 180s daily, survives backend restart). Frontend `ChartPanel.jsx` smart-polls every 5s during RTH on the focused chart instead of re-shipping the full 5,000-bar window every 30s.
- `GET /api/ib/pusher-health` — **v19.30.11 (2026-05-01)** — adds `rpc_max_concurrent`, `rpc_circuit_state`, `rpc_circuit_open_remaining_s`, `rpc_circuit_recent_failures`, `rpc_circuit_short_circuit_total`, `rpc_semaphore_timeout_total`, `rpc_dedup_coalesced_total` to the `heartbeat` block. Surfaces the new throttle/circuit-breaker/dedup state on the V5 PusherHeartbeatTile.
- `GET /api/system/banner` — **v19.30.12 (2026-05-01)** — distinguishes 3 pusher failure modes: `pusher_rpc_dead` (critical, both channels down), `pusher_rpc_blocked` (warning, push HEALTHY but RPC firewall-blocked — exact case operator hit), `pusher_rpc_partial` (warning, edge cases). Action text includes the actual `netsh advfirewall` command for the RPC-blocked case.
- `GET /api/system/health` `pusher_rpc` subsystem — **v19.30.12 (2026-05-01)** — adds `push_age_s` + `push_fresh` to metrics. Reads `routers.ib._pushed_ib_data` module attr directly (the helper is shadowed by an async route). Severity matrix is push×RPC quadrants instead of just RPC failures.
- `GET /api/ib/account/positions` — **v19.30.10 (2026-05-01)** — simplified two-tier pusher read. Response shape: `{ positions, count, source: "memory"|"mongo_snapshot"|"empty", last_update }`. Hot path reads in-memory `_pushed_ib_data["positions"]`. Warm path reads Mongo `ib_live_snapshot.current` (survives backend restarts). Empty state when both tiers are empty. NEVER raises 503 — direct-IB call removed entirely (DGX has no direct IB connection in this deployment; pusher is the source of truth).
- `POST /api/trading-bot/cancel-all-pending-orders` — **v19.30.9 (2026-05-01)** — pre-open safety endpoint. Cancels pending+claimed rows in Mongo `order_queue` + direct IB-side open orders (when reachable). Requires `confirm:"CANCEL_ALL_PENDING"` token. Optional `symbols=[...]` scope + `dry_run:true` preview. Response surfaces `ib_unavailable:true` flag when direct IB is unreachable so operator knows to flatten via TWS / Workbench. Mirrors the `/flatten-paper?confirm=FLATTEN` safety pattern.
- `GET /api/system/account-mode` — **v19.31.13 (2026-05-04)** — operator-facing account-mode snapshot. Resolves `detected_mode` (paper/live/unknown) by classifying current pusher account ID through `account_guard.classify_account_id` (DU* prefix → paper, anything else → live). Returns `{detected_mode, effective_mode, current_account_id, expected_aliases, match, reason, ib_connected, active_mode}`. Powers the V5 HUD top-strip `<AccountModeBadge>` so the operator never confuses paper vs live across account flips.
- `GET /api/diagnostics/shadow-decisions?days=N&symbol=X&only_executed=&only_passed=` — **v19.31.13 (2026-05-04)** — V5 Diagnostics → Shadow Decisions tab. Reads `shadow_decisions` Mongo collection (the AI council's verdict on every alert, regardless of fire). Returns rows + summary: total, by_recommendation, executed_count/win_rate/pnl_sum, not_executed_count + would_pnl_sum, `divergence_signal` (`ai_too_conservative` / `ai_too_aggressive` / `balanced`).
- Realized-PnL auto-sync background task — **v19.31.13 (2026-05-04)** — `TradingBotService` schedules `_realized_pnl_autosync_loop()` every 30s. Scans `bot_trades` for `status=closed AND closed_at within last 24h AND realized_pnl in (0, null, missing)`, dedupes by symbol, and calls the same `routers.diagnostics._recalc_realized_pnl_for_symbol` helper as the manual `↻ Recalc` button. Idempotent + silent when healthy. Env: `REALIZED_PNL_AUTOSYNC_ENABLED=true`, `REALIZED_PNL_AUTOSYNC_INTERVAL_S=30`.
- `BotTrade.trade_type` — **v19.31.13 (2026-05-04)** — every fresh fill stamped at execution time with `paper`/`live`/`unknown` based on the IB account ID seen at fill time. Surfaced through `/api/sentcom/positions` (open + lazy IB-orphan branches), `/api/sentcom/positions.closed_today`, `/api/diagnostics/day-tape`, `/api/diagnostics/day-tape.csv` (new `trade_type` + `account_id_at_fill` columns), and `/api/diagnostics/forensics` (rolled up to `dominant_type` per symbol; `mixed` when concrete types diverge).
- `GET /api/ib-collector/throttle-policy` — **v19.31.14 (2026-05-04)** — RTH-aware historical-collector throttle. Returns `{max_concurrent_workers, rth_active, recommended_pending_request_limit, reason, et_iso}`. `max_concurrent_workers=1` during 9:30-15:55 ET weekdays, `4` otherwise. Windows IB pusher should poll every ~30s and cap its worker pool. Server-side enforcement: `/api/ib/historical-data/pending` caps the operator-passed `limit` at `recommended_pending_request_limit` when RTH is active so older pushers also benefit; payload includes `throttle_limit` + `rth_active` for the pusher to log/honor.
- `GET /api/trading-bot/boot-reconcile-status?pill_visible_seconds=600` — **v19.31.14 (2026-05-04)** — exposes the last `auto_reconcile_at_boot` event so the V5 HUD can render a "🔁 Auto-claimed N at boot" pill. Returns `{ran, ran_at, age_seconds, reconciled_count, skipped_count, errors_count, symbols, show_pill}`. Pill auto-hides after `pill_visible_seconds`. Backend persists to `bot_state.last_auto_reconcile_at_boot` so the pill survives restarts.
- `POST /api/sentcom/chart/warm` — **v19.32 (2026-05-04)** — pre-warm `chart_response_cache` for top-N visible scanner symbols × common timeframes. Body: `{symbols: [str], timeframes: [str]=["5min"], days: int=5, session: str="rth_plus_premarket", max_concurrent: int=4, per_cell_timeout_s: float=8.0}`. Concurrency-bounded by semaphore; per-cell timeout protects the batch. Returns `{success, summary: {warmed, skipped, failed, total}, elapsed_ms, results: [...]}`. ScannerCardsV5 calls this 1.5s-debounced on every top-12 card list change. Operator's NEXT chart click on a warmed symbol is <50ms vs. 400ms cold.
- `WS /api/sentcom/ws/chart-tail?symbol=X&timeframe=Y&since=Z&session=...` — **v19.33 (2026-05-04)** — server-pushed chart tail. Replaces 5s polling with 2s RTH-tick (30s off-hours) push-on-change. Reuses REST `get_chart_tail` handler internally; payload byte-identical so frontend merge code unchanged. Stamps `from_ws: true` + `server_t`. Heartbeat `{type:'ping', t:..., symbol:...}` every 15s of silence. Feature-flagged: `CHART_WS_ENABLED=false` immediate close-1008. `CHART_WS_TICK_S` env override. Hook `useChartTailWs` auto-reconnects with exponential backoff (1→2→4s); after 3 consecutive failures sets `status='fallback'` so polling loop resumes. Polling loop in `ChartPanel.jsx` pauses while `wsStatus ∈ {connecting, connected}`. New chart-ws-status pip ("live"/"poll"/"poll-fb") in chart header.
- `services/quote_tick_bus.py` + `GET /api/ib/quote-tick-bus/health` — **v19.34 (2026-05-04)** — in-memory L1 quote tick pub/sub. `defaultdict[symbol, set[asyncio.Queue]]` with bounded latest-N drop policy (size=8) per subscriber. Per-symbol drop counters; process-global publish/drop totals. Feature-flag `QUOTE_TICK_BUS_ENABLED=true` (default ON; no I/O when nobody subscribes). Pusher's `receive_pushed_ib_data` publishes every quote update to the bus.
- `services/bracket_tif.py` — **v19.34.5 (2026-05-05)** — classification-aware bracket TIF resolver. Intraday styles → `("DAY", False)`, overnight styles → `("GTC", True)`. Wired into trade_executor_service, ib_service, position_reconciler. Stops the GTC zombie bug at *placement* time.
- `GET /api/ib/orders` — **v19.34.6 (2026-05-05)** — Mongo `order_queue`-backed visibility endpoint. Filter by `status` (csv supported), `symbol`, `order_type`, `since`; `open_only=true` shorthand. Returns `{orders, summary, source: "mongo_order_queue", filters_applied}`. Replaces the dead `/orders/open` direct-IB endpoint.
- `POST /api/trading-bot/eod-validate-overnight-orders` — **v19.34.6 (2026-05-05)** — sweeps every active order with a GTC or `outside_rth=True` leg, classifies as `ok_swing_or_position` / `wrong_tif_intraday_parent` / `orphan_no_parent`, optionally cancels orphans + wrong-TIF rows. Two-step safety: requires BOTH `confirm="CANCEL_ORPHANS"` and `dry_run=False`. Closes the runtime edge of the GTC-zombie bug.
- `POST /api/trading-bot/cancel-orders-for-symbol` — **v19.34.6 (2026-05-05)** — EOD pre-cancel guard. Cancels every active order for one symbol BEFORE firing market-close flatten. Requires `confirm="CANCEL_FOR_SYMBOL"` token. Eliminates the OCA race against EOD market-close.
- `GET /api/trading-bot/effective-limits` — **v19.34.6 (2026-05-05)** — single canonical endpoint returning the most-restrictive AND across all guard layers (Master Safety, bot RiskParameters, PositionSizer, DynamicRisk). Mirrors `/api/safety/effective-risk-caps`. Fixes the 2026-05-04 operator confusion where Morning Prep UI showed 25 pos/$5k and `/status` showed 10 pos/$0.
- `services/sentcom_service.get_our_positions` watchlist filter — **v19.34.6 (2026-05-05)** — suppresses bot-tracked rows whose `setup_type` is in `_WATCHLIST_ONLY_SETUPS` (`carry_forward_watch`, `day_2_continuation`, `gap_fill_open`, `approaching_*`) when IB does NOT confirm a matching `(symbol, direction, qty>0)` position.
- `BotTrade.pre_submit_at` — **v19.34.6 (2026-05-05)** — ISO timestamp stamped immediately before broker call. Trade upserted to `bot_trades` with `status=PENDING` BEFORE `place_bracket_order`. Eliminates "IB fill but no Mongo row" gap. Save failure does NOT block the broker call (fail-open).
- `services/enhanced_scanner._persist_carry_forward_alert` + `_hydrate_carry_forward_alerts_from_mongo` — **v19.34.6 (2026-05-05)** — carry-forward gameplan persistence. After-hours `_rank_carry_forward_setups_for_tomorrow` writes to `carry_forward_alerts` Mongo collection on creation; `start()` rehydrates non-expired non-dismissed alerts back into `_live_alerts`. Morning prep workflow now survives backend restart.
- `services/bracket_reissue_service.py` — **v19.34.7 (2026-05-05 PM)** — unified `cancel-old + recompute + submit-new OCA pair` pipeline for the bracket lifecycle. Used by scale-out (auto-wired into `position_manager.check_and_execute_scale_out`), TIF promotion, manual operator overrides. Cancel-then-submit with 2s ack timeout; aborts on cancel failure (CRITICAL stream warning, never both old + new live). Recomputes stop from weighted-avg-entry × `default_stop_pct`; preserves target PRICE LEVELS, recomputes target QUANTITIES from new total × original `scale_out_pcts`. Feature-flag `BRACKET_REISSUE_AUTO_ENABLED=true` (default ON).
- `POST /api/trading-bot/reissue-bracket` — **v19.34.7 (2026-05-05 PM)** — operator-driven manual trigger for the bracket re-issue service. Supports `dry_run=true` to preview the computed plan. Body: `{trade_id, reason, new_total_shares?, new_avg_entry?, already_executed_shares?, preserve_target_levels?, cancel_ack_timeout_s?, dry_run?}`. 400/404/503 guards on missing args.
- `TradingBotService.start()` boot zombie sweeper — **v19.34.7 (2026-05-05 PM)** — 30s after startup, calls `eod_validate_overnight_orders` in dry-run mode and surfaces orphan + wrong-TIF counts to logs + operator stream. Does NOT auto-cancel — operator reviews + triggers cancel manually. Feature-flag `BOOT_ZOMBIE_SWEEP_ENABLED=true`.
- `services/rejection_cooldown_service.py` — **v19.34.8 (2026-05-05 PM)** — per-`(symbol, setup_type)` cooldown after a structural rejection. Subsequent re-evals during the cooldown window are short-circuited with a clear log breadcrumb. Auto-expiry; repeat rejections within window EXTEND the expiry + bump `rejection_count`. Operator nukes via `clear_cooldown` / `clear_all`. Wired into `trade_execution.execute_trade` at THREE points: top-of-function gate, broker-rejection branch, guardrail-veto branch. Defaults: `REJECTION_COOLDOWN_SECONDS=300` (5 min).
- `GET /api/trading-bot/rejection-cooldowns` + `POST /api/trading-bot/clear-rejection-cooldown` — **v19.34.8 (2026-05-05 PM)** — operator inspection / manual override endpoints for the rejection cooldown registry.
- `services/state_integrity_service.py` + `GET /api/trading-bot/integrity-status` + `POST /api/trading-bot/force-resync` — **v19.34.10 / 14 (2026-05-06)** — drift watchdog. Per-field policy: **MEMORY_WINS** for IB-sourced capital fields (`starting_capital`, `max_daily_loss`, `max_notional_per_trade`, `max_risk_per_trade`) + `setup_min_rr` (memory came from live IB / refresh-account; Mongo is just last persisted snapshot). **MONGO_WINS** for operator-tuned limits (`max_open_positions`, `max_position_pct`, `min_risk_reward`, `max_daily_loss_pct`, `reconciled_default_*`) — persisted Mongo IS the operator's intent. **Drift-loop detector** (v19.34.14): if same field flips ≥3 times in 600s, demote to detect-only for process lifetime; operator re-arms via `force-resync {rearm_demoted: true}`. Surfaces `demoted_fields[]` in status. Auto-resolve ON by default; flip via `STATE_INTEGRITY_AUTO_RESOLVE=false`. Drift events persist to `state_integrity_events` (TTL 7d) + emit CRITICAL `state_drift_detected_v19_34_10` Unified Stream event.
- `GET /api/trading-bot/bracket-history?trade_id|symbol&days&limit` — **v19.34.11 (2026-05-06)** — Mongo `bracket_lifecycle_events` (TTL 7d) reader. Returns full lifecycle of a trade's brackets (original → scale-out → re-issue → exit) with per-event `reason`, `phase`, `cancel_result`, `submit_result`, `plan` rich detail. Powers the V5 `<BracketHistoryPanel />` expandable inner panel inside `OpenPositionsV5.jsx`. Backend writer in `services/bracket_reissue_service._persist_lifecycle_event` runs on every `reissue_bracket_for_trade` return path (best-effort, never blocks broker call).
- `GET /api/trading-bot/rejection-events?symbol&setup_type&days&limit` — **v19.34.12 (2026-05-06)** — Mongo `rejection_events` (TTL 7d) reader with built-in heatmap aggregation. Returns `{events[], heatmap.rows[], heatmap.symbols[], heatmap.setups[], heatmap.max_rejections, heatmap.top_reasons[]}`. Powers the V5 Diagnostics → "Rejections" sub-tab heatmap (Symbol × Setup grid colored by rejection_count, tooltip per cell breaks down by reason). Backend writer in `services/rejection_cooldown_service._persist_rejection_event` runs on both initial-rejection and cooldown-extension paths.
- Quote `pushed_at` stamping at merge time + boot-reconcile retry pass — **v19.34.13 (2026-05-06)** — `routers/ib.receive_pushed_ib_data` now stamps `pushed_at` on every quote dict at merge (fixes "STALE 240m" V5 chip lying when pusher was LIVE 1s). Boot auto-reconcile schedules a 90s retry pass when the initial 20s pass leaves orphans skipped (clears `direction_unstable` 30s gate). `GET /api/trading-bot/boot-reconcile-status` exposes `skipped[]` per-orphan reasons + `retry_pass` flag. Redundant `<PusherHealthChip />` removed from HUD top strip (`<PusherHeartbeatTile />` panel below is single source of truth).

- `PositionManager.evaluate_single_trade_against_quote(trade, bot, quote)` + lifecycle reaper in `TradingBotService.start()` — **v19.34 (2026-05-04)** — manage-loop consumer for the tick bus. Per-open-trade subscriber task runs the same stop-trigger logic as `update_open_positions` on each fresh tick (~50ms cadence) instead of waiting for the next manage-loop cycle (~5-15s). Mirrors bid/ask-aware logic; trailing-stop precedence honored. Close reason stamped `stop_loss_mid_bar_v19_34` (or `..._<mode>_mid_bar_v19_34`) for journaling. Feature-flag `MID_BAR_TICK_EVAL_ENABLED=false` (default OFF — explicit opt-in after operator verifies bus health). Lifecycle reaper polls every 2s (`MID_BAR_TICK_RECONCILE_S`) — self-healing across all `_open_trades` insertion sites. Cancelled cleanly in `bot.stop()`.
- `GET /api/assistant/coach/morning-briefing` — Setup-landscape + multi-index-regime grounded morning briefing in 1st-person voice (2026-04-30 v4)
- `GET /api/assistant/coach/eod-briefing` — retrospective EOD coaching (2026-04-29 v3)
- `GET /api/assistant/coach/weekend-prep-briefing` — Sunday-night prep (2026-04-29 v3)
- `GET /api/scanner/setup-landscape?context=morning|midday|eod|weekend` — universe-wide Bellafiore-Setup snapshot + 1st-person narrative (now leads with multi-index regime line + cites yesterday's grade — 2026-04-30 v4)
- `GET /api/scanner/landscape-receipts?days=7&context=morning` — recent graded landscape predictions (closes the AI feedback loop — 2026-04-30 v4)
- `POST /api/scanner/landscape-grade?trading_day=YYYY-MM-DD` — manual trigger of EOD grading job (2026-04-30 v4)
- `POST /api/trading-bot/reconcile` — proper write-through reconcile of IB-only orphan positions; v19.29 added 30s direction stability gate (`direction_unstable` skip if observation history < 30s) preventing direction-mismatched claims.
- `GET /api/diagnostic/trade-drops?minutes=N&gate=X&limit=N` — silent execution-drop forensics; v19.29 instruments order-intent dedup blocks via `safety_guardrail` + `reason=intent_already_pending`.

## v19.29 validation harness (2026-05-01)

`backend/scripts/verify_v19_29.py` — read-only Python harness that
queries 6 backend surfaces to confirm v19.29's 5 fixes are wired and
observable end-to-end. Documented in `memory/V19_29_VALIDATION.md`.
Run during/after RTH:
```
python -m backend.scripts.verify_v19_29 --watch
```
- `GET /api/scanner/setup-trade-matrix` — full Trade × Setup matrix + classifier stats (2026-04-29 v2)
- `GET /api/scanner/sector-regime` — per-sector regime snapshot (11 SPDR ETFs + SPY benchmark, soft-gate ML feature — 2026-04-30 v6)
- `POST /api/scanner/backfill-sector-tags` — populate `symbol_adv_cache.sector` from the static GICS map (idempotent — 2026-04-30 v6)
- `GET /api/scanner/in-play-config` — current in-play scoring thresholds (single source of truth shared by scanner + AI assistant — 2026-04-30 v7)
- `PUT /api/scanner/in-play-config` — runtime threshold tuning, persists to `bot_state.in_play_config` (`{"strict_gate": true}` opts into hard gating — 2026-04-30 v7)
- `GET /api/diagnostic/trade-funnel?date=YYYY-MM-DD` — walks the alert→bot→execution chain and pinpoints the first dead stage (2026-04-30 v8)
- `GET /api/trading-bot/eod-status` — EOD countdown lookahead used by the V5 EodCountdownBannerV5 (status state-machine + intraday/swing counts; 2026-04-30 v19.14b)
- `POST /api/trading-bot/eod-close-now` — manual flatten of all open positions (bool-return fix 2026-04-30 v19.14b)
- `GET /api/system/morning-readiness` — pre-RTH autopilot go/no-go aggregator (2026-04-30 v19.18)
- `GET /api/diagnostic/trade-drops?minutes=N&gate=X&limit=N` — silent execution-drop forensics (2026-04-30 v12); 9 instrumented gates between AI gate and `bot_trades.insert_one()`
- `POST /api/diagnostic/dlq-purge?permanent_only=true&dry_run=true&older_than_hours=N&bar_size=X&force=true` — purges permanently-failed historical-data requests; safe-by-default allowlist + audit log to `dlq_purge_log` (2026-04-30 v19.2)
- `GET /api/scanner/setup-coverage` — orphan/silent/active/time-filtered diagnostic
- `GET /api/scanner/detector-stats` — per-detector evals + hits (cumulative + cycle)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot. **v19.30.1
  (2026-05-02)**: now `async def` with `asyncio.to_thread` offload
  for sync mongo snapshot upsert + `tick_to_bar_persister.on_push`,
  plus 503-Retry-After:5 backpressure when ≥4 pushes are in flight
  (cap = `_PUSH_DATA_MAX_CONCURRENT`). Pre-fix this sync handler did
  inline sync pymongo + held-lock per-bar upserts on every push,
  saturating anyio's 40-thread pool and wedging `/api/health` to
  0-byte timeouts. New observability: `/api/ib/pusher-health.heartbeat`
  exposes `push_in_flight`, `push_max_concurrent`, `push_dropped_503_total`.
- `GET /api/health` — **v19.30.1 (2026-05-02)**: `def` → `async def`.
  Must be async so it runs on the event loop directly, immune to
  thread-pool starvation regardless of what's happening downstream.
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not
- `POST /api/ai-modules/shadow/track-outcomes?drain=true&batch_size=50` — drain shadow-decision backlog (added 2026-04-29). Yields to event loop between batches.


## Canonical setup taxonomy (SSOT — v268→v271)

`services/setup_taxonomy.py` is the single source of truth for setup naming:
`canonicalize` (collapse `_long`/`_short`/`_scalp`/`_confirmed` + aliases),
`is_edge_excluded` (reconciled_*/imported_from_ib/approaching_*/watchlist),
`strategy_family`, `exit_archetype_prior`, `style_of`. Stamped on every alert via
`LiveAlert.__post_init__` (m3); exposed at `GET /api/sentcom/taxonomy` (m4) which
feeds `agents/vocabulary.py` (NIA) and `frontend/utils/tradeStyleMeta.js` (m4-fe).
**m5 (v271):** grading (`setup_grading_service`), EV (`ev_tracking_service`),
the corrected learning store (`learning_loop_service.rebuild_*` → read by
`tqs/setup_quality`) all roll up by canonical bucket + exclude artifacts; grades
compute off MEDIAN R with a sub-$1 `risk_amount` clamp. Flags (default ON,
reversible): `GRADING_CANONICAL_ROLLUP`, `GRADING_USE_MEDIAN`,
`GRADING_MIN_RISK_AMOUNT`, `EV_CANONICAL_ROLLUP`, `LEARNING_CANONICAL_BASE`.
Model feature input (`get_setup_features`) is intentionally UNCHANGED (m6 audit
done — `memory/M6_AI_FEATURE_INPUT_AUDIT_2026-06.md`; setup_type reaches models
only via coarse family routing, never a per-setup one-hot) — never feed
canonical/family names to trained models without a retrain.
**m8 (v272):** `tidal_wave` split — the old reversion detector → `fading_bounce`
(fade/reversion/target); a NEW true-momentum `tidal_wave` (RVOL surge + range
break, long runner; env-tunable TIDAL_WAVE_MIN_*) owns the name. Historical
`tidal_wave` rows migrate to `fading_bounce` via
`scripts/migrate_v19_34_272_tidal_wave.py`.
**Issue 2 (v273):** `smart_stop_service` bracket geometry now driven by SSOT
`exit_archetype_prior()` (INTRADAY_BRACKET_V2, env-reversible) — runner archetypes
(momentum/breakout/tidal_wave) get a tight stop + trailing remainder; target
archetypes (scalp/fade/fading_bounce) get a fixed 2-wave bracket.

## Pipeline architecture (Bellafiore + ML hybrid)

### Conceptual hierarchy (operator mental model + UI)
`Market Regime (SPY/QQQ/IWM/DIA) → Sector Regime → Daily Setup → Time/In-play → Trade`

### Runtime architecture (decided 2026-04-29 evening, locked 2026-04-30)
**Hard gates only in 3 places** to avoid compounding rejection rate
that would starve the ML pipeline of training data:
  1. **Time-window** (`_is_setup_valid_now` in `enhanced_scanner.py`) — opening_drive can't fire midday
  2. **In-Play / Universe** — ADV ≥ $2M/day floor (FAIL CLOSED on unknown ADV) + RVOL ≥ 0.8 floor + tier-based scan frequency. **Unified richer in-play score** (RVOL/Gap/ATR/Spread/Catalyst — `services/in_play_service.py`, shipped 2026-04-30 v7) is **stamped on every alert** as metadata; promotes to a hard gate only when `bot_state.in_play_config.strict_gate=true`.
  3. **Confidence gate** — predicted_R + win_prob threshold

**Everything else flows in as features** to the per-Trade ML models:
  - **Multi-index regime tag** (`MultiIndexRegimeClassifier` —
    shipped 2026-04-30) — composite SPY/QQQ/IWM/DIA label, 8 active
    buckets + UNKNOWN; one-hot encoded into `regime_label_*` features.
  - **Sector regime tag** (`SectorRegimeClassifier` — shipped
    2026-04-30) — 11 SPDR sector ETFs + SPY benchmark → 5 active
    buckets + UNKNOWN; per-symbol resolution via static GICS map
    in `SectorTagService`; one-hot encoded into `sector_label_*`
    features. Training uses `SectorRegimeHistoricalProvider` with
    per-(etf, date) caching.
  - Daily Setup tag (`MarketSetupClassifier` — shipped 2026-04-29 v2;
    one-hot encoded into `setup_label_*` features 2026-04-30)
  - Setup × Trade matrix context (`is_countertrend`, `out_of_context_warning`, `experimental` — shipped 2026-04-29 v2)
  - Setup landscape (`SetupLandscapeService` — shipped 2026-04-29 v3;
    extended with regime line 2026-04-30)
  - Numerical regime features (24 floats — `regime_features.py`,
    SPY/QQQ/IWM trend/RSI/momentum/breadth/correlations/rotations)

`STRATEGY_REGIME_PREFERENCES` in `enhanced_scanner.py` is METADATA
ONLY — explicitly NOT a hard-gate enforcement (re-documented
2026-04-30 to close the next-session-plan item #6). It documents the
operator's mental model of which trades thrive in which regimes; the
actual learning happens via the one-hot features above.

The matrix in `services/market_setup_classifier.py::TRADE_SETUP_MATRIX`
is the operator's source of truth for which Trade fits which Setup;
`/app/memory/SETUPS_AND_TRADES.md` is the human-readable mirror.


## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/routers/scanner.py` — `/setup-coverage`, `/setup-trade-matrix`, `/setup-landscape`, `/detector-stats`
- `backend/routers/assistant.py` — `/coach/morning-briefing`, `/coach/eod-briefing`, `/coach/weekend-prep-briefing`
- `backend/services/trade_drop_recorder.py` — **NEW 2026-04-30 v12** — silent-execution-drop audit trail. `record_trade_drop` writes to `trade_drops` Mongo collection (TTL 7d) + 500-deep in-memory ring buffer fallback + structured `[TRADE_DROP]` WARN log line. 9 KNOWN_GATES wired between AI confidence gate and `bot_trades.insert_one()`: `account_guard`, `safety_guardrail`, `safety_guardrail_crash`, `no_trade_executor`, `pre_exec_guardrail_veto`, `strategy_paper_phase`, `strategy_simulation_phase`, `broker_rejected`, `execution_exception`.
- `backend/services/trade_execution.py` — **PATCH 2026-04-30 v12** — `execute_trade` broker-reject + exception branches now call `await bot._save_trade(trade)` so REJECTED trades are no longer orphaned in process memory. This was the likeliest root cause of the April 16 → April 29 silent regression (zero `bot_trades` inserts despite 32 AI-gate GOs/day).
- `backend/routers/diagnostic_router.py` — `/api/diagnostic/trade-drops` endpoint added 2026-04-30 v12; aggregates drops by gate, names `first_killing_gate`, returns last 25 rows with full context.
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `backend/services/enhanced_scanner.py` — 38 trade detectors, scanner loop, `_apply_setup_context` matrix gate + multi-index regime stamping (2026-04-30), `LiveAlert` dataclass with context fields (`market_setup`, `is_countertrend`, `out_of_context_warning`, `experimental`, `multi_index_regime`)
- `backend/services/market_setup_classifier.py` — `MarketSetup` enum (7 + NEUTRAL), `MarketSetupClassifier` (daily-bar driven), `TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`, `lookup_trade_context()`, `_sync_classify_window()` for training-time per-bar labels (2026-04-30)
- `backend/services/in_play_service.py` — **NEW 2026-04-30** — unified in-play scorer used by both the live scanner (`score_from_snapshot`) and the AI assistant (`score_from_market_data`); runtime-tunable thresholds persisted to `bot_state.in_play_config`; SOFT mode by default (stamps `LiveAlert.in_play_score/reasons/disqualifiers` only), STRICT mode rejects alerts when `is_in_play=False`
- `backend/services/multi_index_regime_classifier.py` — **NEW 2026-04-30** — `MultiIndexRegime` enum (9 buckets), `MultiIndexRegimeClassifier` reads ~25 daily bars per index (SPY/QQQ/IWM/DIA), 5-min market-wide cache, `derive_regime_label_from_features()` for training
- `backend/services/sector_tag_service.py` — **NEW 2026-04-30** — static GICS-aligned `STATIC_SECTOR_MAP` (~340 most-liquid stocks) + ETF self-mapping; `tag_symbol`, `tag_many`, `coverage`, `backfill_symbol_adv_cache` (idempotent)
- `backend/services/sector_regime_classifier.py` — **NEW 2026-04-30** — `SectorRegime` enum (6 buckets: STRONG/ROTATING_IN/NEUTRAL/ROTATING_OUT/WEAK/UNKNOWN), `SectorRegimeClassifier` reads 11 SPDR ETFs + SPY (5-min market-wide cache), `SectorRegimeHistoricalProvider` for training-time per-sample sector regime lookup with per-(etf,date) caching
- `backend/services/ai_modules/composite_label_features.py` — **NEW 2026-04-30** — one-hot helpers: `SETUP_LABEL_FEATURE_NAMES` (7), `REGIME_LABEL_FEATURE_NAMES` (8), `SECTOR_LABEL_FEATURE_NAMES` (5), `ALL_LABEL_FEATURE_NAMES` (20), `build_label_features(market_setup, multi_index_regime, sector_regime)`
- `backend/scripts/backfill_sector_tags.py` — **NEW 2026-04-30** — one-shot CLI for sector backfill
- `backend/services/setup_landscape_service.py` — `SetupLandscapeService` with 4 narrative voices (morning/midday/eod/weekend), 1st-person voice rules, 60s cache, **regime line preface (2026-04-30)** + `LandscapeSnapshot.multi_index_regime/regime_confidence/regime_reasoning` + **auto-records snapshot to `landscape_predictions` (2026-04-30) + cites yesterday's grade in morning narrative**
- `backend/services/landscape_grading_service.py` — **NEW 2026-04-30** — `LandscapeGradingService` records every snapshot's prediction to `landscape_predictions`, grades EOD by joining to `alert_outcomes` (A/B/C/D/F per Bellafiore Setup family), `get_recent_grades` powers the morning briefing's "Quick receipt — yesterday I predicted ..." citation. **`get_weekly_summary` (2026-04-30 v5)** rolls up the past 7 days of grades for the Sunday weekend voice ("Last week's record — 3A · 1B · 1C — strong directional read")
- `backend/services/ai_assistant_service.py` — `get_coaching_alert()` injects landscape narrative + voice rules + multi-index regime fields into AI prompts and payload (2026-04-30)
- `backend/services/ai_modules/timeseries_service.py` — training (`_train_single_setup_profile`) + prediction (`predict_for_setup`) plumbed with the 15 categorical label features (2026-04-30)
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script
- `backend/services/smart_levels_service.py` — `compute_smart_levels`, `compute_stop_guard`, `compute_target_snap`, `compute_trailing_stop_snap` (added 2026-04-29 — liquidity-aware trail)
- `backend/services/stop_manager.py` — `set_db(db)` injection enables HVN-anchored breakeven + trail (2026-04-29). **Realtime stop-guard re-check (2026-04-30 v11)**: `_periodic_resnap_check` runs after every `update_trailing_stop` call (60s per-trade throttle), re-snaps to fresher HVN levels in `breakeven`/`trailing` modes, ratchet-only.
- `backend/services/sector_tag_service.py` — `tag_symbol_async` (2026-04-30 v11) full fallback chain: STATIC_MAP → `symbol_adv_cache.sector` → Finnhub `stock/profile2` industry → `_industry_to_etf` mapper → persist back to Mongo. `_PRIORITY_OVERRIDES` resolves conflicts (Biotech > Tech, REIT > Industrial, Renewable > Energy); `_EXPLICIT_NONE` blocklist returns UNKNOWN for cryptocurrency / SPAC / trust / fund.
- `frontend/src/components/sentcom/v5/ShadowVsRealTile.jsx` — **NEW 2026-04-30 v11** — V5 status-strip tile, reads `/api/ai-modules/shadow/stats` + `/api/trading-bot/stats/performance` every 60s, renders side-by-side win-rate + divergence signal (`shadow ahead` / `shadow behind` / `in sync` per ±5pp).
- `app/memory/SETUPS_AND_TRADES.md` — canonical doc for the 7 Setups + 22 Trades + matrix + aliases


## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)


## Audit tooling (v19.34.4 — 2026-05-04)

When operator wants to confirm bot accounting matches IB reality
(phantom shares, partial-fill drift, orphan adoptions):

1. Paste IB TWS Trades-pane → `memory/audit/<YYYY-MM-DD>_ib_fill_tape.txt`.
2. `python -m scripts.audit_ib_fill_tape --input ... --out report.md` — standalone parser + FIFO PnL + verdict classifier.
3. `python -m scripts.export_bot_trades_for_audit --date YYYY-MM-DD --out bt.json` — Spark Mongo export of today's `bot_trades` rows.
4. Re-run auditor with `--bot-trades-json bt.json` for cross-check section flagging IB-but-not-bot, bot-but-not-IB, and qty mismatches.

Full runbook: `memory/runbooks/audit_ib_fill_tape.md`.


## Scanner runtime architecture (v19.15 + v19.16 — 2026-04-30)

### Per-cycle context cache (v19.15)
At the top of each `_run_optimized_scan()` tick, `_refresh_cycle_context()`
prefetches the two market-wide classifiers (Multi-Index Regime + Sector
Regime) into a `Dict[str, Any]` on the scanner. `_apply_setup_context`
reads from this dict for all alerts in the same cycle instead of
awaiting the classifiers per-alert. TTL: 60s; on miss we fall back
to the per-alert path which is also TTL-cached internally (5 min).

### Tier-aware detector dispatch (v19.16)
`_intraday_only_setups` is a superset of `_intraday_setups` listing
every detector with explicit sub-5min timing or playbook "intraday
only" spec. The dispatch loop in `_scan_symbol_all_setups` skips
these detectors when the symbol's tier (from `_tier_cache`) is
non-intraday. Saves ~40% of detector calls on swing+investment
cohort and prevents stale-snapshot signals from polluting the AI
training pipeline.

## EOD Auto-Close (v19.14 — 2026-04-30)

- **Default window**: 3:55 PM ET on regular trading days, 12:55 PM ET
  on half-days (operator sets `EOD_HALF_DAY_TODAY=true` in env that
  morning). Configurable via `bot_config.eod_config.{close_hour,
  close_minute, enabled}` in Mongo.
- **Scope**: ONLY applies to trades flagged `close_at_eod=True` in
  `STRATEGY_CONFIGS` (intraday/scalp/day strategies). Swing
  (`squeeze`, `daily_*`, `earnings_momentum`, `sector_rotation`) and
  Position (`base_breakout`, `accumulation_entry`,
  `relative_strength_position`, `position_trade`) trades are
  explicitly held overnight.
- **Parallel closes**: `asyncio.gather` over all eligible trades
  bounds wall-time to single-trade IB-roundtrip latency.
- **Retry-on-partial**: if any close fails, the manage-loop tick
  (~every 1-2s) retries until either all succeed OR market_close_hour
  passes — at which point an `eod_after_close_alarm` WS event fires.
- **WS surface**: `eod_close_started` (window opens) + `eod_close_completed`
  (final state) + `eod_after_close_alarm` (positions still open after 4:00 PM).


## v19.34.110 — Pipeline Tile Split + Event-Driven Pusher ACK (2026-02-12)

**P3-A**: V5 HUD ORDER tile now renders `5q + 3@ib` split when there
are orders sitting at IB in `IB_PENDING` (v109). Falls back to flat
count when `ib_pending = 0`. Backend `SentComStatus` exposes
`order_pipeline.ib_pending`; also fixes a latent typo where the
service was reading `pending_count` / `executing_count` / `filled_today`
instead of the actual `get_queue_status` keys.

**P3-B**: `ib_data_pusher.py` no longer blocks on a 30s `while` loop
after `placeOrder`. Subscribes `trade.statusEvent` and reports
terminal states (Filled / Cancelled / Inactive) back to Spark
immediately. Pre-v110 polling capped queue throughput; v110
serializes only on `placeOrder` itself, not on terminal-state
discovery. The "still pending after 30s" fallback branch and the
"Unknown status:" rejection branch are removed entirely — under
event-driven dispatch we never time-out a transient.

Pusher redeploy required for P3-B; backend hot-reloads for P3-A
after frontend `yarn build`.

## v19.34.111 — Queue idempotency + reconciler attach cooldown (2026-02-12)

Root-cause fix for the bounce loop v109 patched at the symptom layer.
`order_queue_service.queue_order()` now returns the existing `order_id`
when the caller's `trade_id` is already in-flight (PENDING / CLAIMED /
IB_PENDING / EXECUTING). Reconciler's `attach_oca_stop_target` call
sites are throttled by a per-`trade.id` 60s cooldown
(`BRACKET_ATTACH_COOLDOWN_S` env-overridable). Two layered guards
ensure duplicate intents can't reach IB regardless of caller path.

## v19.34.112 — Scalp SL/TP calculation fix (2026-02-12)

Scalp setups (`scalp`, `nine_ema_scalp`, `spencer_scalp`, `abc_scalp`)
were silently using the generic 1.5-2.0× base ATR multiplier and the
fixed `[1.5R, 2.5R, 4R]` target ladder — wrong for <5min holding
periods. v112 ships:
- Tight ATR multipliers (0.4-0.5×) with min-clamp bypass for scalps only
- Trade-style-aware target ladder: scalp `[1R, 1.5R]`, intraday `[1.5R, 2.5R]`, swing `[1.5R, 2.5R, 4R]` (legacy), position `[2R, 4R, 8R]`
- `target_snap` skipped for scalps (avoids widening tight targets to S/R clusters)

Existing positions are NOT migrated — only new alerts get the v112 treatment.

## v19.34.113 — Setup Grading Subsystem (2026-02-12)

Per-setup_type performance scoreboard. Daily EOD tick (16:10 ET) walks
closed `bot_trades` and upserts per-(setup_type, date) snapshots into
`setup_grade_records`. Rolling 30-day grade card surfaces via the
V5 `SetupGradeChip` next to `TradeStyleChip` on positions + scanner
cards.

**Grade ladder**: A+ / A / B+ / B / C / F / INSUFFICIENT_DATA (< 5
trades). Formula gates on win_rate + avg_r — operator-readable, not
Sharpe. Sample-weighted rollup math (1-trade days don't count equally
with 20-trade days).

**API**: GET `/api/setup-grades`, GET `/api/setup-grades/{setup_type}`,
POST `/api/setup-grades/compute`, GET `/api/setup-grades/history/{setup_type}`.

**Observe-only**: chip and `get_grade_warning` API exist but do NOT
block alerts. A future PR can wire as a hard filter after a week of
live data validates the formula.

**Validates v112**: scalp ATR multiplier choices now have a measurable
scorecard. If `nine_ema_scalp` grades F at 0.4× consistently, widen
empirically rather than guessing.

## v19.34.114 — Yesterday's grade card in morning briefing (2026-02-12)

`GET /api/setup-grades/yesterday-recap` walks back up to 7 days to
find the most recent trading day with grade data; returns winners /
losers / a deterministic `summary_line` the LLM briefing can quote
verbatim. V5 `MorningPrepCard` renders the recap in its expanded
section: emerald winners, rose F-grade losers, italic advice.
Operator and LLM briefing now read identical text — no hallucination
surface on the citation.


## v19.34.115 — V6 integration prep + locked contracts (2026-02-12)

Locked the integration plan for v110–v114 → V6 panel rollout.
New: `/app/memory/V6_INTEGRATION_v110_v114.md` (master index).
Appended cross-reference sections to all three existing V6 specs.
Backend: promoted v111 cooldown counter to a 200-entry deque with
`get_attach_cooldown_skips()` public read — V6 Safety Activity Stream
aggregator dependency now satisfied. 5 non-negotiable invariants
codified for V6 implementation. 220/220 cumulative tests pass.

## v19.34.116 — POST /api/trading-bot/retune-stop (2026-02-12)

The "Tighten stop →" backend for V6 Position Health Console's
STOP-WIDE-FOR-STYLE row state. Recomputes the stop via v112's
OpportunityEvaluator table and re-fires attach_oca_stop_target under
v111 cooldown protection. Supports dry-run via `dry_run: true`.
Lets the operator surgically retune legacy v111-era scalp positions
WITHOUT waiting for V6 to ship. 18/18 new tests, 238/238 cumulative.

V6 Integration index marked the only remaining Phase C backend
dependency SHIPPED.

## v19.34.117 — POST /api/trading-bot/retune-stop/bulk-scalps (2026-02-12)

Bulk-fire version of v116's retune-stop. Default `dry_run=true`
(safety inversion vs single endpoint). Scans all open scalps, filters
by `stop_distance/atr > 1.0` (configurable), and applies v112's
corrected stop via shared `_retune_stop_core` helper. v111 cooldown
+ idempotency apply per-trade. One operator call to fix every
legacy wide-stop scalp in the book. Wires into V6 Position Health
Console's "Tighten all wide-stop scalps" batch action.
17/17 new tests, 255/255 cumulative v100→v117 PASS.

---
## Status update — 2026-06-05 (forked session)

### Done & verified on DGX (pytest 8/8, endpoint live)
- ✅ m5 (canonical grading/EV), m8 (tidal_wave momentum split / fading_bounce reversion) — code+data+tests committed (6696927f).
- ✅ Issue 2 — INTRADAY_BRACKET_V2 (runner/target/swing_hold/position_hold archetype brackets) — committed (b652f364).
- ✅ A — bracket reconciliation trace (`scripts/probe_bracket_reconcile.py`).
- ✅ B — horizon-aware daily-bar lookback (`market_setup_classifier.py`).
- ✅ C — `/api/scanner/in-play-health` endpoint + `scripts/probe_inplay_health.py`.
  (Deployed via compact anchored idempotent applier on paste.rs; backups *.bak.abc0606.)

### Next / backlog (reconciled 2026-06-05 — see ROADMAP.md for the live list)
- ✅ SHIPPED (verified in code): EV Leaderboard on MC (`EVLeaderboard.jsx`),
  adopted-position P&L split backend (`sentcom.py` `adopted_pnl_today`),
  `hold_seconds` at close (`trading_bot_service.py:1015`), EOD honors trade-style
  (`opportunity_evaluator.py` v245).
- 🟡 P1 OPEN: Bot-Vitals header on MC (off `/api/scanner/in-play-health`); MC sticky
  per-symbol search/filter across 5 lanes; squeeze intraday-vs-swing `trade_style` split.
- 🟢 P2 OPEN: L2 depth probe (`probe_l2_depth.py` — not built); "why-not-auto-traded" EV
  chip (v294 `ev_below`); adopted P&L split frontend chip; Gameplan boost surfacing;
  EOD close popup modal; scanner feed group/display; regime classifier tolerance patch.
- 🟢 P3 OPEN: break up server.py monolith; refresh AGENTS.md for SSOT architecture.

### Deploy/test constraints (unchanged)
- DO NOT use testing_agent (DGX hardware-bound). Validate via pytest + curl + probes in container, ship idempotent appliers via paste.rs.
- DGX restart: `./start_backend.sh --force`.

---
## m-series COMPLETE — 2026-06-05
- ✅ m1–m9 all shipped & verified on DGX (m9 = exit_archetype MFE/MAE data-override, paste.rs/vOlNF, 16/16 pytest).
- Open (m9 validation only): live market-hours run of `probe_bracket_reconcile.py --base http://localhost:8001` against open positions to confirm bracket attach+reconcile on the real IB path.
- Deferred cosmetic (fold into next deploy): probe CLI "no live DB" note (already fixed in container, not yet shipped).
- Next P1 UI: EV Leaderboard on Mission Control; Bot-Vitals header; MC sticky per-symbol search/filter across 5 lanes; Gameplan prioritization boost.

---
## ML Roadmap — decision logged 2026-06-05 (per-setup / realized-data models)

DECISION: Do NOT build per-raw-setup PRIMARY models. Family-keyed price-window
primaries (triple-barrier on ib_historical_data) pool statistical power and
generalize better; raw setups don't add samples to them. Setup nuance already
lives in per-family feature extractors + meta-labeler + m5 grade/EV pillars.

PLANNED (sample-gated, P1 when data allows): realized-outcome META-LABELING layer
— one model trained on bot_trades (entry-context features → realized win/R), with
`canonical_setup` as a FEATURE (not per-setup heads), gating/sizing the primary
signals. López de Prado meta-labeling; codebase already scaffolded (triple_barrier_
labeler, purged_cpcv). Validate with purged CPCV vs the current confidence gate
before it sizes anything.

GATE: needs ~hundreds of closed trades total, ~50–100 per canonical setup. Probe
shows tidal_wave=0, fading_bounce=2 (May→) — NOT trainable yet. Interim = the
statistical layer (learning-loop win-rate/EV, m5 grade, m9 override) — correct for
small N. Per-setup split only if a high-volume setup shows systematic calibration
error vs its family head (evidence-gated, one at a time).

NEXT ML STEPS:
1. (now) plain freshness retrain of family primaries (probe = GO; models ~39d stale).
2. (todo) extend retrain_readiness.py with a "realized-outcome trainability" budget
   (total + per-canonical closed-trade counts, label-field completeness, GO/WAIT for
   meta-labeling).
3. (later, gated) build the meta-labeling layer when the budget says GO.
4. (watch) confirm hold_seconds is stamped on bot_trades at close (net_pnl/mfe_r/
   mae_r already present) — needed as a clean label/feature for the meta-model.
   ✅ CONFIRMED 2026-06-05: `trading_bot_service.py:1015` stamps `hold_seconds` via
   `_compute_hold_seconds(entry_ts, close_ts)` at close.

---
## Action item added 2026-06-05: GPU-torch swap (P2, own task)
- torch is CPU build (2.10.0+cpu) while GPU works for XGBoost (CUDA enabled). CNN/deep-learning heads (P9 chart-pattern, P11 CNN-LSTM) train on CPU = slow.
- TODO: swap to a CUDA-enabled torch + matching torchvision (aarch64/Spark GB10) so P9/P11 train on GPU (~5–10× faster). Careful stack change, do as isolated task with a backup of the working CPU torch+torchvision (0.25.0). Verify `torch.cuda.is_available()` + re-run tensor probe after.

---
## 2026-06-08 — A+B+C audit P1 batch (v19.34.308–310) — PATCH READY (operator-apply pending)
Consolidated patch: https://paste.rs/q0CT1 (supersedes A+B-only paste.rs/p8mys).
- **A (v308)** IB-Gateway STARTUP hard-block probe: new `services/ib_boot_probe.py`, 30s grace poll of the IB execution feed; on fail → trips existing kill-switch (bot can't arm) + `/api/system/health` RED via new `ib_boot_probe` subsystem. Manual-reset by design.
- **B (v309)** Fundamental absent-data → NEUTRAL 50 (was optimistic: inst→80/float→65/earnings→60). `tqs/fundamental_quality.py`.
- **C (v310)** SMB: (C-1 always-on) persist `smb_5var_score` in `LiveAlert.to_dict()`; (C-2 env-gated `SMB_CHECKLIST_TIMEFRAME_AWARE`, DEFAULT OFF) timeframe-aware checklist thresholds + 50-SMA swing MTF confluence; (C-3 operator follow-up) drop the C→50 decompress via `TQS_SETUP_DECOMPRESS=false` after verifying real scores flow.
- Tests: 11/11 new (test_v308/309/310) + v305/smb_profiles/l4c regression green. NO testing_agent (DGX mandate).
- STILL PENDING (operator): rotate Atlas DB password (P0 security, old creds in git history).


---
## 2026-06-09 — Command Center regime + caps + HUD (v316f/g/h) — ✅ SHIPPED & LIVE ON DGX
- **v316f** (paste.rs/iagua): RegimeStrip.jsx (4-lane multi-tf band: context/lanes/long-short
  modes/$TICK/per-index/divergence) + `/summary` surfaces `multi_tf` + slashed-zero font
  (`.font-mono-data` font-feature "zero") + position cap unify → 25 (safety kill-switch
  5→25, LLMRules advisory floor 10→25). Operator set bot.max_open_positions=25 via POST
  /risk-params → `diag_risk_truth.py` confirms EFFECTIVE=25. Daily-loss left at 1%/~$2k
  (operator choice B).
- **v316g** (paste.rs/cYsqy): ROOT-CAUSE fix — the v315/v316 multi_tf ENGINE code
  (`_calculate_multi_tf`+`_get_tf_bars` in market_regime_engine.py, `get_historical_data`
  in ib_direct_service.py) had never landed on the DGX (only the helper module had). Strip
  was empty because `/current` returned multi_tf=null. VERIFIED LIVE: context=ALIGNED_UP,
  lanes 64.9/51.9/88.8/65.0, internals 64.8, per_index SPY60.6/QQQ60.5/IWM85.5. Intraday
  lanes fed by `live_tick` bars (queue historical returns no-data by design).
- **v316h** (paste.rs/mNomy): HUD top strip decluttered 14→6 core chips. Diagnostics
  (Brackets-Path/Connectivity/Scanner-Coverage/Boot-Reconcile/Drift-Guard/Cancel-Queue)
  folded into Ops Status popover "Pipeline Diagnostics" group; risk chips (LLM-Rules/
  Order-Policies) into Edge & Performance "Guardrails" group. Applied + yarn-built clean.

### Standing operator reminders (unchanged, P0/P1)
- 🔴 Rotate Atlas DB password (old creds in git history).
- 🟡 Retrain with TB_PT_MULT=1.5 / TB_SL_MULT=1.0.
- 🟡 v311 Monday-freshness buffer (paste.rs/L2rc2) — applied this session; verify the
  weekend-aware test is green after restart.

### Next P1
- M0 laddered server-side scale-out (multi-leg OCA).
- Optional: NEW effective-limits Guardrails chip (Pos 25 · Loss $5k/1%) surfacing the
  reconciler truth at a glance.

---
## 2026-06-11 — v19.34.319 gap-fill NO-PEEK fix — ✅ DONE & VERIFIED (deployed on DGX)
- Closed the gap-fill look-ahead leak (audit: 76.2%/49.6%/15.5% of 15m/5m/1m fills in the
  open bar). Training now decides AT THE OPEN: features end at bar i-1, bar-i gap features
  neutralized, target over [i+1, i+w]. Patch https://paste.rs/hIfcL applied; verify script
  showed balanced fill% (49/41/42%). 16/16 pytest.
- Honest models promoted: gap_fill_1min acc 0.750, 5min 0.689, 15min 0.706 (down from leaky
  0.83-0.94), healthy two-sided recall. Leaky 5min/15min + retired daily/weekly EVICTED via
  scripts/evict_leaky_gap_models_v319.py (paste.rs/KROyI). Only 3 honest intraday gap models remain.

## P1 patches — ✅ ALL DEPLOYED & GREEN on DGX (2026-06-11)
- v319d Phase-8 ensemble FFD match-fix → applied via https://paste.rs/U7WVq (training_pipeline.py).
  Sub-models now get real FFD (not zero-filled) in the meta-labeler. 4/4 pytest on DGX. Takes
  effect next ensemble/full retrain. FFD flag confirmed ON.
- v319b embargo + v319c GBM_FORCE_PROMOTE override → timeseries_gbm.py. The Brcge git-patch
  failed (DGX file had ~8-line drift above the class) so deployed via a line-number-proof
  STRING PATCHER https://paste.rs/GrkS1 (idempotent, py_compiles before write). +68 lines,
  12/12 pytest on DGX. Embargo de-biases all GBM train/val splits (logs `embargo gap: purging
  N boundary sample(s)…` on next full run); force-promote is the reusable lever to evict a
  known-invalid incumbent on future leakage fixes (env GBM_FORCE_PROMOTE).
  NOTE for future agents: prefer string patchers over git-diff patches for timeseries_gbm.py /
  large monolith files — line numbers drift between the container fork and the live DGX tree.

---
## 2026-06-10 — v322 Regime-First Funnel SHIPPED (container-validated, patch paste.rs/RVbeU)
- c2 (symbol regime → gate), sector regime → gate scoring, c3/T7 RS Leadership +
  Regime Focus List, focus-list scan-cadence promotion, P7 regime-conditional
  sample-count bug fix, mplfinance log-spam suppression. 43 new tests.
- "P1: per-stock multi-TF regime; regime-first scanning funnel (c3)" and
  "P2: RS leadership factor (RS 80+)" from the backlog below are now DONE.
- Remaining backlog updates: apply v322 on DGX BEFORE the full retrain (P7 fix
  affects the 28 regime-conditional models P-WIRE phase 2 depends on).

## Remaining backlog (from handoff, post-audit)
- Standing P0 (MANUAL, user action): rotate Atlas DB password (old creds in git history).
- PARKED: P-WIRE phase 2 wiring (needs ~5000 shadow decisions from pwire_shadow_eval.py).
- P1: ~~per-stock multi-TF regime (market_regime_engine.py); regime-first scanning funnel (c3)~~ ✅ v322.
- P2: dedicated intraday DL model; ~~RS leadership factor (RS 80+)~~ ✅ v322; Wyckoff trigger; L2 probe;
  break up server.py monolith.

---
## 2026-06-11 — v322k + v322l: orphan cancel↔re-issue loop + false-rejection re-claim
- **v322k (DEPLOYED on DGX, patch https://paste.rs/5H8Zw, 5/5 pytest on DGX)**: killed the
  UNP/USB pathological loop (orphan-GTC auto-sweep cancelled ADOPT-OCA brackets the
  naked-sweep had just issued, repeat ~60s). Root cause was NOT the limit(2000) cap (window
  was 890 rows) but stale order-id fields in the bot_trades snapshot. Fix: classifier now
  proves ownership via the trade id embedded in the OCA group name
  (ADOPT-OCA-{sym}-{trade_id}-{nonce}, ≥8-char token match) + oca_group threaded through
  tier-1/tier-3 order snapshots + sort("executed_at",-1) before the cap as defence.
  Files: services/orphan_gtc_reconciler.py, tests/test_v322k_orphan_loop.py.
- **v322l (CONTAINER-VALIDATED, patch https://paste.rs/fIwcU, 6/6 pytest, AWAITING DGX apply)**:
  fixes the upstream IB Gateway race — orders tagged `parent_not_filled:cancelled` →
  broker_rejected while the fill lands at IB. The v19.34.15a poll-back now RE-CLAIMS the
  rejected trade in-place (direction guard, qty clamp to |delta|, R-preserve via true avg
  fill from ib_direct fills by entry_order_id, brackets re-attached via
  attach_oca_stop_target, `trade_reclaimed_v322l` stream event) instead of leaving it to
  generic orphan adoption that lost setup/SL/PT.
  Files: services/trade_execution.py, tests/test_v322l_silent_fill_reclaim.py.
- Regression checked: all other failures in orphan/naked/trade-execution suites confirmed
  PRE-EXISTING (identical pre/post patch).
- NEXT: M0 laddered server-side scale-out (multi-leg OCA) — user's stated next priority.

---
## 2026-06-11 — v322m + v322n: scalp liquidity proof + ETF universe re-evaluation
- **v322m (patch https://paste.rs/2Cc5M, 30/30 tests, AWAITING DGX apply)**: AIQ/CZR audit
  found CZR ORB scalps judged against the $2M investment floor (scan_tier=investment +
  trade_style=scalp) with rvol=0.0, and AIQ scalping with only 2.2M sh/day. Fixes in
  enhanced_scanner: (1) floor = STRICTEST-OF(scan_tier, trade_style); (2) scalp/intraday
  alerts must prove RVOL ≥ SCALP_MIN_RVOL (default 1.0, rvol<=0 fail-closed); (3) scalp
  share-ADV floor SCALP_MIN_SHARE_ADV (default 3M sh/day, fail-closed). Env=0 disables.
- **v322n (patch https://paste.rs/quG8o, 9+66 tests, AWAITING DGX apply)**: ~25% of the
  top-400-dollar-ADV L1 universe was ETFs. New services/etf_classifier.py (8 classes).
  Focus list excludes leveraged_inverse/bond_cash/income/index_clone (carve-out:
  TQQQ/SQQQ/SOXL/SOXS per user). L1 top-N drops bond_cash/income/index_clone/single-stock
  leveraged (context ETF set unaffected; takes effect on pusher restart). bot_trades now
  stamped is_etf/etf_class for per-class EV measurement.
- Diagnostic created: /app/scripts/diag_liquidity_trail.py (paste.rs/rQfZB).
- FINDING: IB_PUSHER_L1_AUTO_TOP_N is set as a Windows env var (not in .bat) — auto-fetch
  works (404 symbols). The 14-symbol .bat IB_SYMBOLS list is fallback-only, harmless.
- NEXT: user applies v322m+v322n, then M0 laddered scale-out. Future: per-class EV review
  after ~2 weeks of tagged trades; ELF→XLE sector mis-tag; CZR tier misclassification probe.

---
## 2026-06-11 — v322o Quick-Wins Batch (CONTAINER-VALIDATED, patch https://paste.rs/VMM4l, AWAITING DGX apply)
- **#10 TQS stuck at C/C+ — ROOT CAUSE FOUND (display bug)**: backend calibration healthy
  (user diag: reference_n=16,069, scores 45–71). `TqsBadge.jsx` re-derived the grade from
  the raw score with the STATIC ladder (>=85=A…) "as single source of truth" (v19.34.257),
  undoing the v19.34.228 percentile calibration on the frontend. Fix: badge now prefers the
  backend-stamped calibrated `tqs_grade` (all call sites already pass it as gradeFallback);
  static ladder kept only for legacy rows with score-but-no-grade.
- **#5 2% toast spam**: usePriceAlerts.js dedup key was per-minute → re-toasted every 60s.
  Now ONE alert per symbol per 15 min (ALERT_COOLDOWN_MS).
- **#8 Command-center cutoff**: V5 root overflow-hidden → overflow-y-auto + main row hard
  floor min-h-[900px] + center column min-heights (chart 340 / stream 200 / drawer 240).
  Page scrolls on short viewports instead of crushing SentCom Intelligence / Deep Feed.
  v19.34.1 chart-ResizeObserver regression cannot recur (row height never content-driven).
- **#11 slow charts step 1**: /api/sentcom/chart now returns `timings` meta
  (cache_ms/mongo_ms/rpc_ms/indicators_ms/markers_ms/total_ms) on hit/miss/failure +
  WARNING log `[v322o chart-slow]` for loads > CHART_SLOW_LOG_MS (1500ms default).
  Verified all 4 paths via curl with seeded bars. NEXT: user loads slow charts → timings
  convict the phase → fix (likely short-circuit RPC merge for unsubscribed symbols).
- **#3 Scalp Exit Autopsy**: new read-only backend/scripts/scalp_exit_autopsy.py
  (https://paste.rs/Nv5cM): exit-bucket table (TP/SL/DECAY/EOD/EXTERNAL/MANUAL), TP
  realized-R distribution (M0 ladder input), decay post-exit replay vs 5-min bars — %
  stop-saved vs % left-on-table ≥0.5R/1R (v322p input). Validated against synthetic trades.
- NEXT: user applies v322o (backend restart needed) + pastes autopsy output + chart timings
  → then M0 laddered scale-out (3-leg OCA 40%@+1R/30%@+2R/30% runner, env-tunable, with
  orphan-safety: legs must share OCA group + ownership token per v322k conventions).

## 2026-06-11 — M0 Laddered Scale-Out BUILT (CONTAINER-VALIDATED, awaiting DGX apply)
- **Order-path finding**: DGX runs BOT_ORDER_PATH=direct (probe confirmed). The v19.34.103
  pusher ladder NEVER fired — every bracket has been single-target full-qty via
  ib_direct.place_oca_stop_target. Autopsy v2: EXT_TP 8 (+1.08R avg) vs EXT_SL 17
  (-1.62R avg — slippage red flag, backlog probe) vs EXT_SCRATCH 61 (71%).
- **M0 architecture** (paste.rs: patcher zQaVU, manager a4r4M, tests s6pgK):
  1. order_policy_registry: scalp/intraday tp_ladder → 40%@1R / 30%@2R / 30% runner
     (cap +4R scalp / +6R intraday). Env: M0_TP_LADDER_SCALP/_INTRADAY="0.4@1.0,...".
     _ladder_from_env validates (2-5 rungs, pcts sum 1, ascending R) else code default.
  2. ib_direct_service: _m0_ladder_plan (gates: M0_LADDER_ENABLED default true,
     M0_LADDER_STYLES default scalp,intraday, M0_LADDER_MIN_SHARES default 10) +
     _m0_place_oca_ladder: PER-LEG OCA pairs (stop_i+target_i own group
     `ADOPT-OCA-{sym}-{tradeid}-L{i}-{nonce}`, ocaType=1 — leg TP fill cancels only its
     own stop). Stops placed FIRST; any stop submit-fail or permanent-reject → cancel all,
     success=False (caller flattens). Target fail → stop-only leg, partial=True.
     All child ids → trade.target_order_ids so EVERY existing close/EOD/decay cancel
     path covers the ladder. modify_stop_price: in-place IB stop modify (same orderId,
     new auxPrice — OCA group preserved).
  3. NEW services/m0_ladder_manager.py: manage-loop tick. Leg-fill detection =
     open-orders snapshot (10s cache, blank snapshot → skip, never infer fills) +
     position-deficit corroboration; TP-vs-stop attribution via MFE; stamps
     targets_hit → EXISTING StopManager does BE-after-leg1/trail-after-leg2 internally;
     stop-sync pushes ratcheted current_stop to surviving IB stops (ratchet-only,
     M0_STOP_SYNC_MIN_R=0.1R min delta, M0_STOP_SYNC_INTERVAL_S=30s throttle).
  4. position_manager: manage hook after _update_trailing_stop + hard guard in
     check_and_execute_scale_out (m0_legs → return; kills v19.34.7 double-sell class).
- **Testing**: 36 new tests + 37 v322k-n regression all pass in container. Backend boots.
  test_strategy_configs.py failures are PRE-EXISTING (identical at HEAD).
- NEXT: user applies M0 + runs tests + paper-session validation checklist; then v322p
  decay (LIGHT touch — autopsy showed timer ~neutral), v322q, chart-slow phase fix
  (awaiting [v322o chart-slow] log lines from user).
- 2026-06-11 DEPLOYED: M0 applied on DGX (6/6 patches, 36/36 tests on-box), backend
  restarted clean (23s boot), registry ladders confirmed live (scalp 40/30/30 cap 4R,
  intraday cap 6R), health green incl. ib_gateway via ib-direct. AWAITING: first live
  [M0 LADDER] entry + leg-fill/BE-sync validation; [v322o chart-slow] log lines; TQS
  badge A/B visual confirmation.
- 2026-06-11 LIVE VALIDATION: M0 fired on 7 entries day 1 (C, SLV, CZR, IGV, CASY, KRE, B)
  — placement/qty-split/OCA-pairs all correct. BUG M0a found+fixed: scanner's single far
  target (~2.5R) became leg 1 while legs 2-3 used R-math → INVERTED ladders (C L1@145.36
  "1R" > L2@143.26 2R). Fix: explicit targets only honored as full monotonic ladder, else
  pure R-math (patcher U7Qtd, tests 0SILH, 40/40 pass). v322o2 taller layout shipped
  (row 1600px, browser-verified 1792px scroll). check_m0_status.py shipped (N81iR).
  TQS true-0-100 display rescale → backlog (pair with Tier 2a isotonic calibration).
- 2026-06-12 M0c SHIPPED (patcher https://paste.rs/lfViT): root cause of CASY ladder-kill
  CONFIRMED as unprimed in-memory snapshots after backend restarts (NOT a 4h-dead pusher —
  `_pushed_ib_data` wipes on every restart; boot audit fires 10s later; `if fresh:` in
  _fetch_ib_positions_async treats empty ib_direct reads as failure → falls to wiped
  snapshot → everything classified naked_no_position → auto-flush killed valid legs).
  Fixes: (1) audit_orphan_gtc_orders fail-closed abort on empty positions snapshot while
  bot tracks active trades OR pusher not fresh; (2) classifier downgrades matched-ACTIVE-
  trade+flat-snapshot to awaiting_data (never auto-cancel); (3) naked-sweep skips on
  blank order snapshot w/ tracked stop ids; (4) naked-sweep ladder-aware (ANY working
  m0_legs stop live at IB = protected; all-legs-lost → mark "lost" then reissue);
  (5) reissue no longer clobbers target_order_ids when reissue placed new M0 ladder;
  (6) consolidator refuses to merge groups holding working m0_legs. 15 new tests
  (test_m0c_reconciler_guards.py); 3 stale tests updated to current contracts
  (v89 cancel-queue fallback, async positions fetcher, v151 SAFE_TO_AUTO_CANCEL set);
  4 pre-existing sweep-test failures (v285 flip-guard unverifiable positions) repaired.
  148/148 relevant tests green in container. AWAITING: user applies M0c on DGX, runs
  pytest, flips M0_LADDER_ENABLED=true, restarts backend, validates next live ladder.
- 2026-06-12 M0c DEPLOYED+VERIFIED ON DGX: patcher lfViT (17/17 applied) + follow-up
  M0c-t1 patcher BaMtZ (test-only: _patch_fetch mocked tier pusher_orders_snapshot →
  ib_direct; DGX exports BOT_ORDER_PATH=direct so the v163 tier-mismatch guard skipped
  the sweep and 7 tests failed — env-dependent test flaw, reproduced+fixed in container).
  Final DGX run: 91/91 green in .venv (repo root ~/Trading-and-Analysis-Platform, use
  `source .venv/bin/activate`, NOT system python3.12). User instructed to flip
  M0_LADDER_ENABLED=true and restart. VALIDATION PENDING: clean boot audit (or M0c
  EMPTY-SNAPSHOT GUARD abort) with zero cancellations; next live ladder legs surviving
  restarts.
