# SentCom AI Trading Platform — PRD

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## Completed Work (Apr 17, 2026)

### Critical: DST Timezone Bug Fix (Apr 17 — DONE)
- Scanner `_get_current_time_window()` used hardcoded EST `timezone(timedelta(hours=-5))`, but April = EDT (UTC-4)
- Scanner was blind to market hours since daylight saving started March 9th
- Fixed in `enhanced_scanner.py`, `trade_context_service.py`, `circuit_breaker.py`, `tqs/context_quality.py`
- All now use `ZoneInfo("America/New_York")` which auto-handles EST/EDT

### Critical: SentCom Stream Fix (Apr 17 — DONE)
- `server.py` streaming cache imported non-existent `sentcom_engine` module — silently failed
- WS stream `sentcom_data.stream` was ALWAYS empty (never populated)
- Fixed: replaced with `sentcom_service.get_unified_stream()` as async call in cache loop
- Also fixed WS push hash that was based on missing `status.last_updated` field

### Scanner Stale Price Fix (Apr 17 — DONE)
- Removed MongoDB bar fallback for price data — scanner now requires live IB quotes only
- Added 8% price-drift cleanup in `_cleanup_expired_alerts()` (removes alerts where live price diverged)
- Added `ib_connected` to scanner stats for frontend display
- Frontend shows "IB Not Connected" warning banner when IB is disconnected

### Scanner Loop Bug Fix (Apr 17 — DONE)
- Min-interval safety check was trapped inside an `except` block (dead code)
- Fixed indentation so it properly enforces 10s minimum between scan cycles

### Confidence Gate DB Hydration (Apr 17 — DONE)
- All gate stats/decisions were in-memory only, reset to zeros on restart
- Added `_load_from_db()` on startup: loads recent decisions, today's stats, lifetime counters, trading mode
- NIA "SentCom Intelligence" panel now shows historical data immediately after restart

### Positions Panel Overhaul (Apr 17 — DONE)
- Backend: added `market_value`, `cost_basis`, `portfolio_weight`, `risk_level`, `today_change` to positions
- Frontend: risk badges (CRITICAL >-30%, DANGER >-15%, WARNING >-7%), NO STOP warnings
- Sort controls (P&L $, P&L %, Value, Weight), source filter (All/Bot/IB)
- Portfolio-level stats: total_market_value, positions_at_risk, bot/ib counts

### Scanner Panel Reorder (Apr 17 — DONE)
- Watching list (top 10, was 6) now appears ABOVE All Alerts section
- IB connection warning banner when disconnected

### Prior Completed Work (Feb 2026)

#### A1: Service Init → Startup Event (DONE)
- Moved 1017 lines of service initialization from module-level into `_init_all_services()` function
- Server accepts connections BEFORE services fully initialized

#### Stability Optimization (DONE)
- 367 async→def endpoint conversions (event loop fully unblocked)
- Streaming cache layer (1 thread/cycle vs 26+)
- Chat server isolated on port 8002 with MongoDB-only context
- Response caching on 6 heavy endpoints

#### Confidence Gate Fix (DONE)
- Disabled AI Regime scoring, mode-aware thresholds, fixed model lookup mismatch
- Bypassed Strategy Promotion gate for paper trading

#### SentCom S.O.C. Enhancements (DONE)
- TQS score integration, richer setup descriptions, signal deduplication
- Color-coded FILTER cards, new data chips

#### Gate Auto-Calibration (DONE)
- `gate_calibrator.py`: analyzes outcomes by 5-point score buckets
- Scheduled nightly at 4:30 PM ET

#### LLM-Enriched Setup Descriptions (DONE)
- Ollama-powered human-readable narratives for S.O.C. stream

## Upcoming Tasks
- Trade Journal page data population (performance stats include bot trades)
- Verify chat hallucination fix from last session
- Phase 6: Distributed PC Worker
- Automated Daily Bar Collection Scheduling
- Re-enable uvloop

## Future Tasks
- Phase 7: Infrastructure Polish (systemd)
- Per-signal weight optimizer for gate auto-tuning
- Wire scanner technical indicators fully into chat context
- Earnings calendar & news feed integration for Chat
- Refactor `chat_server.py` context generation into modular context builders
