# SentCom AI Trading Platform — PRD

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## Completed Work

### Apr 17, 2026 — Session 2 (Major Overhaul)

#### Critical: DST Timezone Bug Fix
- Scanner `_get_current_time_window()` used hardcoded EST, but April = EDT
- Scanner was blind to market hours since March 9th daylight saving
- Fixed in `enhanced_scanner.py`, `trade_context_service.py`, `circuit_breaker.py`, `tqs/context_quality.py`
- All now use `ZoneInfo("America/New_York")`

#### Critical: SentCom Stream Fix
- `server.py` imported non-existent `sentcom_engine` module — silently failed
- WS stream `sentcom_data.stream` was ALWAYS empty
- Fixed: replaced with `sentcom_service.get_unified_stream()` as async call in cache loop
- Fixed WS push hash that was based on missing field

#### Critical: Confidence Gate DB Writes
- `insert_one` was failing silently due to numpy types (from CNN-LSTM/TFT signals)
- Fixed with JSON round-trip serialization (`json.loads(json.dumps(data, default=str))`)
- Upgraded error logging from debug→warning
- Added `_load_from_db()` on startup: loads recent decisions, today's stats, lifetime counters

#### Scanner Fixes
- Removed MongoDB bar fallback for pricing — scanner requires live IB quotes only
- Added IB disconnected warning banner in frontend
- Fixed scan loop min-interval check (was dead code inside except block)
- Fixed PyMongo boolean check on db objects (`if not self.db` → `if self.db is None`)
- Added `ib_connected` and `scan_mode` to scanner status

#### After-Hours Scanning Mode (NEW)
- When market CLOSED: scanner runs `_scan_daily_setups()` every 5 min on daily bars
- Checks: daily_squeeze, trend_continuation, daily_breakout, base_breakout, accumulation_entry
- Daily scan no longer requires live quotes (works from MongoDB bars alone)
- S.O.C. generates after-hours content:
  - Session status ("After-hours — scanning daily charts")
  - Session recap (trades, W/L, P&L)
  - Portfolio review (open positions count, tight stops)
  - Daily swing/position setups found

#### EnhancedTickerModal Overhaul
- Analysis endpoint now reads pushed IB data (quote priority: pushed IB → positions → direct IB → Alpaca → MongoDB)
- Historical endpoint falls back to MongoDB for intraday bars
- Data freshness indicators: "LIVE" green pulse vs "Last known (date)" amber
- Cache TTL 60s→180s, AbortController for fetch cancellation
- Removed fake earnings endpoint (random data), fixed quality data access path
- Ticker search now actually navigates via `openTickerModal()`

#### Positions Panel Overhaul
- Risk badges: CRITICAL (>-30%), DANGER (>-15%), WARNING (>-7%)
- NO STOP warnings for IB positions without stops
- Portfolio weight %, market value, sort controls, source filter (All/Bot/IB)
- Backend returns enriched data: market_value, cost_basis, portfolio_weight, risk_level, today_change

#### Clickable Tickers
- All symbols across app now use `ClickableTicker` → opens `EnhancedTickerModal`
- Wired in: DetailedPositionsPanel, ScannerAlertsPanel, StreamOfConsciousness, SentCom stream

#### S.O.C. Stream Improvements
- Accumulating buffer (100 entries) — messages persist across refresh cycles
- Sorted by timestamp (newest first)
- Removed fake demo message generator
- Container height 500px→700px

#### UI Cleanup
- Removed deprecated AI regime from NIA TrainingPipelinePanel
- TickerTape: removed sticky overlay, hidden when no data
- HeaderBar: removed z-index overlap
- Scanner Watching list: 6→10, positioned above alerts
- Learning Insights widget: hidden when no data
- Fixed NIA QuickStatsBar polling (was blocked during training)
- Wired WS training updates to QuickStatsBar

#### Trade Management
- LABD trade purged via new DELETE `/api/trading-bot/trades/{symbol}` endpoint
- Learning exclusion not needed (LABD was IB-only, never went through gate)
- IB order queue verified working (queued LABD sell → Windows pusher executed)

### Feb 2026 — Session 1

#### Stability & Performance
- Moved 1017 lines init into `_init_all_services()`
- 367 async→def endpoint conversions
- Streaming cache layer
- Chat server isolated on port 8002

#### Confidence Gate
- Disabled AI Regime scoring, mode-aware thresholds
- Bypassed Strategy Promotion gate for paper trading
- Gate Auto-Calibrator (`gate_calibrator.py`)

#### SentCom S.O.C.
- TQS integration, LLM-enriched descriptions, deduplication
- Swing/position scanner with daily bars

## Upcoming Tasks
- Trade Journal page data population (performance stats include bot trades)
- Verify chat hallucination fix from last session
- Deploy and validate after-hours scanning overnight

## Future Tasks
- Phase 6: Distributed PC Worker (offload training to Windows PC)
- Automated Daily Bar Collection Scheduling
- Re-enable uvloop
- Phase 7: Infrastructure Polish (systemd)
- Per-signal weight optimizer for gate auto-tuning
- Real earnings calendar integration
- Wire scanner technical indicators fully into chat context
