# SentCom AI Trading Platform — PRD

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## Completed Work (Apr 16, 2026)

### A1: Service Init → Startup Event (DONE)
- Moved 1017 lines of service initialization from module-level into `_init_all_services()` function
- Function called from `@app.on_event("startup")` via `asyncio.to_thread`
- 80 service variables declared as `None` at module level
- 70 router registrations remain at module level (routes exist before startup)
- Server now accepts connections BEFORE services are fully initialized
- Health check responds immediately after uvicorn starts

### Stability Optimization (DONE)
- 367 async→def endpoint conversions (event loop fully unblocked)
- Streaming cache layer (1 thread/cycle vs 26+)
- Chat server isolated on port 8002 with MongoDB-only context
- Direct cache update on IB push (positions in ~5s)
- Response caching on 6 heavy endpoints
- Aggregated insights endpoint (5 calls → 1)
- Server health badge in SENTCOM header
- Request throttler: maxConcurrent 2 → 4
- Scheduler starts moved to startup event

### Lazy Router Tiers (Documented, not yet lazy-loaded)
- Tier 1 CORE (18 routers): ib, trading_bot, sentcom, ai_training, ai_modules, system, dashboard, market_regime, dynamic_risk, live_scanner, trades, focus_mode, startup_status, market_context, notifications, watchlist, config, assistant
- Tier 2 ACTIVE TRADING (15 routers): smart_stops, quick_actions, circuit_breaker, risk, tqs, context_awareness, regime_performance, market_data, alerts, portfolio, portfolio_awareness, short_data, earnings, technicals, trade_snapshots
- Tier 3 NIA/TRAINING (14 routers): ib_collector, advanced_backtest, slow_learning, medium_learning, learning_connectors, strategy_promotion, learning_dashboard, learning, data_storage, market_scanner, scanner, hybrid_data, simulator, ev_tracking
- Tier 4 UTILITIES (12 routers): agents, rag, journal, research, knowledge, smb, social_feed, catalyst, sentiment, market_intel, ollama_proxy, alpaca

### A1 Cleanup (Feb 2026 — DONE)
- Removed duplicate module-level `init_*_router()` calls (lines 2646-2692) that referenced locally-scoped variables from `_init_all_services()`, causing `NameError` on boot.
- `server.py` now compiles cleanly; all router init calls exist only inside `_init_all_services()`.

### Tier 2-4 Lazy Router Loading (Feb 2026 — DONE)
- 24 Tier 1 CORE routers stay at module level (immediate availability for health checks, core UI).
- 46 Tier 2-4 routers (Active Trading, NIA/Training, Utilities) deferred to `_init_all_services()`.
- Router modules imported lazily inside `_init_all_services()`, registered during startup event via `_deferred_routers` list.
- All 46 deferred routers register via `app.include_router()` after `asyncio.to_thread(_init_all_services)` returns.
- Boot time improvement: heavy router modules (and their transitive dependencies) no longer block initial module load.

### Confidence Gate Fix (Feb 2026 — DONE)
- **Disabled AI Regime scoring**: `_get_ai_regime()` (classify_regime from SPY daily bars) was still subtracting points despite being "deprecated" in docstrings. Now logged-only, no score impact.
- **Mode-aware thresholds**: AGGRESSIVE: GO >= 20, REDUCE >= 10 | NORMAL: GO >= 35, REDUCE >= 20 | CAUTIOUS: GO >= 50, REDUCE >= 30 | DEFENSIVE: GO >= 60, REDUCE >= 40. Previously hardcoded at GO >= 55, REDUCE >= 30 regardless of mode.
- **Fixed evaluation order**: Trading mode now updated BEFORE threshold evaluation (was after, causing stale mode for each decision).
- **Result**: In AGGRESSIVE + BULLISH regime, a setup with regime +20 and quality +5 now scores 25 → GO (was SKIP at old threshold 55).
- **Fixed model lookup mismatch**: Scanner setup types (vwap_bounce, squeeze, second_chance, etc.) now map to training model base names (VWAP, BREAKOUT, MEAN_REVERSION, etc.) via SETUP_TO_MODEL dict. Previously `^vwap_bounce_.*_predictor$` could never match `vwap_5min_predictor`, causing "No trained models" for every setup despite models being available.
- **Fixed model DB field mismatch**: Confidence gate queried `model_name` field but DB stores `name`. Accuracy is at `metrics.accuracy` not top-level `accuracy`. Both fixed. Models with no accuracy data now return neutral consensus instead of "no models".
- **Bypassed Strategy Promotion gate**: All 105 strategies were stuck in SIMULATION phase (zero promotion records). Since IB paper account provides safety, the SIM→PAPER→LIVE check is bypassed. Re-enable when switching to live money.
- **Stale trades filtered**: SentCom stream now shows only today's closed trades (was showing weeks-old NIO/KOS trades).

### SentCom S.O.C. Enhancements (Feb 2026 — DONE)
- **Fix Score 0.0**: SentCom now reads `tqs_score` (0-100) from LiveAlert instead of non-existent `score` field. Falls back to `smb_score_total * 2` if TQS unavailable.
- **Richer setup descriptions**: Uses `alert.headline` (e.g., "LUNR Rubber Band LONG - 4.2% extended") and `alert.reasoning` list (RSI, RVOL, R:R, support/resistance) instead of generic "Pattern matches criteria" text.
- **Signal deduplication**: Enhanced scanner enforces max 1 active alert per symbol. Higher-priority alerts replace lower-priority ones. Prevents duplicate NOG/NIO signals.
- **Trade P&L fix**: Fixed falsy check (`pnl=0` treated as no P&L). Now shows actual P&L for breakeven/stopped trades. Added hold duration and R-multiple to trade metadata.
- **Color-coded FILTER cards**: SKIP = red/XCircle, REDUCE = amber/AlertTriangle, GO = green/CheckCircle, unknown = gray.
- **Confidence derived from TQS**: Setup confidence now maps 1:1 from TQS score (0-100) instead of hardcoded 70%.
- **New data chips**: TQS grade (A/B/C), direction (LONG/SHORT), R:R ratio, win rate %, tape score, R-multiple on closed trades.

## Upcoming Tasks
- Phase 5e: RL Position Sizer
- Phase 6: Distributed PC Worker
- Phase 7: Infrastructure Polish (systemd)
- Implement true lazy loading for Tier 3-4 routers (defer imports)
