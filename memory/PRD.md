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

## Upcoming Tasks
- Phase 5e: RL Position Sizer
- Phase 6: Distributed PC Worker
- Phase 7: Infrastructure Polish (systemd)
- Implement true lazy loading for Tier 3-4 routers (defer imports)
