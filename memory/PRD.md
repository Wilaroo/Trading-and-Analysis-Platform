# SentCom AI Trading Platform — PRD

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## Completed Work

### Apr 18, 2026 — Session 3 (Trade Journal Performance Fix)

#### Critical: Trade Journal N+1 Query Fix
- `get_trades()` in `trade_journal.py` was doing 51 MongoDB queries for 50 trades (fetch IDs, then re-fetch each individually)
- Fixed to single query with in-memory `_id` conversion
- Same fix applied to `get_templates()`

#### Critical: Database Connection Reuse
- `/api/trades/ai/learning-stats` and `/api/trades/ai/strategy-insights` were creating new `MongoClient()` on every request
- `journal_router.py` services (`get_services()`, `get_import_services()`, `get_eod_service_instance()`, `get_weekly_report_service_instance()`) each created their own MongoClient
- All now use shared `get_database()` from `database.py`

#### Critical: Wrong Database Name Defaults
- `trades.py` AI endpoints defaulted to `"sentcom"` instead of `"tradecommand"`
- `journal_router.py` services defaulted to `"trading_app"` instead of `"tradecommand"`
- All corrected to use `database.py` which defaults to `"tradecommand"`

#### Critical: Weekly Report Hang Fix
- `generate_weekly_report()` called 7 medium learning services with synchronous PyMongo queries inside async functions, blocking the event loop
- Added `asyncio.to_thread()` for `_get_week_trades()` blocking DB queries
- Added 10-second per-section timeouts via `_safe_call()` wrapper
- Added 12-second endpoint-level timeout on `/weekly-report/current`
- Frontend: 15s timeout on Weekly Report API calls

#### Performance: Unified Trades Endpoint
- Both journal trades AND bot trades now fetch via `asyncio.to_thread()` — neither blocks the event loop
- `/api/trades/performance` has 10s timeout protection

#### Performance: Client-Side Filtering
- Frontend loads ALL trades once on mount, filters client-side for all/open/closed and source
- Switching filters is now instant (no API call)
- Explicit timeouts on all Trade Journal API calls

#### Performance: Unbounded Query Caps
- `get_performance_summary()` capped at 500 closed trades each for journal + bot
- Weekly report `bot_trades` query capped at 500

#### Bug Fix: Scanner `_symbol_adv_cache`
- `enhanced_scanner.py` referenced `self._symbol_adv_cache` but attribute is `self._adv_cache`
- Daily/pre-market scans were crashing every cycle
- Fixed both references (lines 3907, 4005)

### Apr 17, 2026 — Session 2 (Major Overhaul)

#### Critical: DST Timezone Bug Fix
- Scanner used hardcoded EST but April = EDT
- Fixed with `ZoneInfo("America/New_York")` in scanner, trade_context, circuit_breaker, tqs

#### Critical: SentCom Stream Fix
- WS stream was always empty due to wrong import
- Fixed with `sentcom_service.get_unified_stream()`, 100-msg buffer

#### Critical: Confidence Gate DB Writes
- `insert_one` failing due to numpy types
- Fixed with JSON round-trip serialization

#### After-Hours & Pre-Market Scanning Modes
- 3 scanning modes: Pre-market (watchlists), Live Intraday, After-hours (daily bars)

#### EnhancedTickerModal Overhaul
- Data freshness indicators, AbortController, removed fake earnings

#### LLM Chat Memory System
- 4 new MongoDB collections for persistent AI memory

#### Playbook & DRC Auto-Generation (EOD Service)
- Scheduled at 4:30/4:45/5:00 PM ET
- Granular per-symbol, per-regime, per-direction tracking in playbook trade_review
- Weak symbol/regime detection via `edge_notes`

#### Trade Deletion
- `DELETE /api/trading-bot/trades/{symbol}` endpoint

### Feb 2026 — Session 1

#### Stability & Performance
- `_init_all_services()`, async→def conversions, streaming cache, chat server isolation

#### Confidence Gate
- Mode-aware thresholds, gate auto-calibrator

## Pending Verification
- Granular Playbook Tracking — User needs to trigger EOD endpoint and verify per-symbol breakdowns appear

## Upcoming Tasks
- Phase 6: Distributed PC Worker (offload training to Windows PC)
- Automated Daily Bar Collection Scheduling
- Re-enable uvloop

## Future Tasks
- Phase 7: Infrastructure Polish (systemd)
- Per-signal weight optimizer for gate auto-tuning
- Real earnings calendar integration
- Wire scanner technical indicators fully into chat context
- Consider splitting Trade Journal to separate microservice if latency issues persist
