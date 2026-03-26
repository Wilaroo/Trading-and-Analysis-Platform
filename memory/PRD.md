# SentCom AI Trading Platform - PRD

## Original Problem Statement
AI trading platform with 5-Phase Auto-Validation Pipeline, Data Inventory System, and maximum IB historical data collection via request chaining.

## Core Requirements
1. **5-Phase Auto-Validation UI** - Display AI Comparison, Monte Carlo, Walk-Forward, and baseline results per setup model (**DONE**)
2. **Data Inventory System** - Unified DB tracking data depth per symbol/timeframe vs expected minimums (**DONE**)
3. **Max Lookback Data Chaining** - Auto-chunk and chain IB API requests to fetch maximum historical data (**DONE**)
4. **Vendor Data Import** - Stream-import bulk ndjson/CSV OHLCV data from third-party vendors (**DONE**)

## Architecture
- **Frontend**: React + Shadcn/UI
- **Backend**: FastAPI + MongoDB Atlas (~39M+ historical bars)
- **Local Scripts**: IB Data Pusher (connects to IB Gateway), Vendor Data Importer

## What's Been Implemented

### Session 1 (Previous)
- 5-Phase Auto-Validation Pipeline UI in SetupModelsPanel.jsx
- Backend worker.py and ai_modules.py routing for batch validations
- Data inventory service (data_inventory_service.py) for gap analysis
- Cleared 15 stale collection jobs

### Session 2 (Current - Mar 25, 2026)
- **IB Request Chaining Logic**: `generate_chain_requests()` method in `ib_historical_collector.py`
  - Calculates chains needed per (symbol, bar_size) based on existing data depth
  - Steps backward in time using `end_date` field
  - Anti-redundancy: queries earliest bar dates to only chain for missing windows
  - Duration-to-calendar-days mapping for accurate step calculations

- **Queue Service `end_date` Support**: `historical_data_queue_service.py`
  - Added `end_date` param to `create_request()`
  - Updated dedup logic to include `end_date` for chain uniqueness

- **IB Pusher Updates**: `ib_data_pusher.py`
  - All 3 fetch methods read `end_date` from request
  - Pass to IB's `reqHistoricalData(endDateTime=end_date)`
  - Auto-reconnect with exponential backoff (survives Gateway restarts)
  - Auto-login via VBScript (types credentials after Gateway restart)
  - Connection health check every loop iteration

- **Async Storage Fix**: `routers/ib.py`
  - Historical data result endpoint now responds instantly
  - Bars written to Atlas in background via asyncio.create_task
  - Eliminates all timeout issues for both collector and trading pusher

- **New API Endpoints**:
  - `POST /api/ib-collector/max-lookback-collection` - Background max lookback with chaining
  - `GET /api/ib-collector/max-lookback-status` - Check background job status
  - `GET /api/ib-collector/chain-preview?symbol=X&bar_size=Y` - Preview chains for any symbol

- **Vendor Data Import Script**: `documents/scripts/import_vendor_data.py`
  - Streaming ndjson/CSV parser (constant memory)
  - Filters to qualifying symbols via ADV cache
  - Skips overlapping date ranges
  - bulk_write in batches of 5000
  - Progress tracking, resume support, dry-run mode

- **Standalone Chain Builder**: `build_chains.py`
  - Direct MongoDB queue insertion (bypasses API for large jobs)
  - Queued 111,192 chained requests for 4,611 symbols

- **Bat File Updates**:
  - `TradeCommand_AITraining.bat`: Added Step 9 (Collector), now 11 steps, health check shows queue progress
  - `StartTrading.bat` + `StartCollection.bat`: Pointed to localhost:8001
  - All scripts use local backend (no more Cloudflare timeouts)

- **Bug Fix**: `/api/ai-modules/timeseries/status` 500 error (unhashable list type)

### Session 3 (Mar 26, 2026)
- **Auto-Skip Dead Symbols**: `ib_data_pusher.py`
  - Tracks `_dead_symbols` set and `_symbol_nodata_count` dict
  - After 2 consecutive no-data/no-security-definition results, symbol is flagged dead
  - All future queue requests for dead symbols skip IB entirely (instant claim+skip)
  - Calls backend `POST /api/ib/historical-data/skip-symbol` to bulk-mark remaining pending requests
  - Status log now shows dead symbol count and list

- **Timezone Fix (IB Warning 2174)**: `ib_data_pusher.py`
  - New `_normalize_end_date()` method ensures all `end_date` values include explicit "UTC" suffix
  - Applied to `_collection_fetch_single`, `_collection_fetch_single_fast`, and `_fetch_and_return_historical_data`
  - Eliminates IB warning about implicit timezone before IB removes support

- **New API Endpoint**: `POST /api/ib/historical-data/skip-symbol`
  - Bulk-updates all pending requests for a symbol to `skipped_dead_symbol` status
  - Returns count of skipped requests
  - Pre-emptively skipped 107 SGN requests as first use

- **Multi-Instance Collection**: `ib_data_pusher.py` + `historical_data_queue_service.py` + `ib.py`
  - New CLI args: `--bar-sizes` (filter by timeframe), `--partition`/`--partition-total` (symbol hash partitioning)
  - Backend `/pending` endpoint accepts `bar_sizes`, `partition`, `partition_total` query params
  - Queue service `get_pending_requests()` filters by bar_size and symbol partition
  - Enables running 3 parallel collector instances with independent IB pacing limits

- **5-Min Duration Optimization**: `build_chains.py`
  - Tested and confirmed IB accepts `"3 M"` duration for 5-min bars (was `"1 M"`)
  - Re-queued all 5-min requests: 64K → 21K (67% reduction, ~8 chains/symbol instead of ~24)
  - Updated BAR_CONFIGS to use `"3 M"` for future runs

- **Swing-Tier 5-Min Trim**
  - Cancelled 31K pending 5-min requests for swing-tier symbols (100K-500K ADV)
  - Swing symbols retain 30 mins, 1 hour, 1 day coverage

- **Queue Reduction Summary**: 153K → 79K pending requests (48% reduction)

- **Bat File Update**: `TradeCommand_AITraining.bat`
  - Step 9 now launches 3 collector instances (client IDs 16/17/18)
  - Collector 1: Daily/Weekly (dark yellow), Collector 2: Hourly/15m/30m (light red), Collector 3: 5-min (aqua)
  - Updated terminal color guide and health check display

## Key Technical Details

### IB Lookback Limits & Chaining
| Bar Size | Max Lookback | Duration/Request | Chains/Symbol |
|----------|-------------|-----------------|---------------|
| 1 min    | 180 days    | 1 W             | ~26           |
| 5 mins   | 730 days    | 1 M             | ~25           |
| 15 mins  | 730 days    | 3 M             | ~9            |
| 30 mins  | 730 days    | 6 M             | ~5            |
| 1 hour   | 1825 days   | 1 Y             | ~5            |
| 1 day    | 7300 days   | 8 Y             | ~3            |
| 1 week   | 7300 days   | 20 Y            | ~1            |

### Data Inventory Thresholds
- MIN_BACKTEST_BARS: 1min=3900, 5min=780, 15min=260, 30min=130, 1hr=65, 1day=252, 1wk=52
- Depth categories: Deep (10x min), Backtestable (>min), Moderate (50-100%), Shallow (<50%), Stub (<10%)

## Prioritized Backlog

### P1 - Next Up
- User to verify overnight collection progress (33,513 of 187,260 completed = ~18%)
- User to purchase vendor 1-min data and run import script

### P2 - Upcoming
- Real-time collection dashboard (heatmap of data depth per symbol/bar_size)
- MFE/MAE Scatter Chart per setup type
- Auto-Optimize AI Settings

### P3 - Future
- API Route Profiling Dashboard
- Compare Simulations Side-by-Side
- Refactor active polling to WebSocket (~44 intervals)
- Refactor trading_bot_service.py (4,300+ lines → modules)

## Key Files
- `/app/backend/services/ib_historical_collector.py` - Chaining logic
- `/app/backend/services/data_inventory_service.py` - Gap analysis
- `/app/backend/services/historical_data_queue_service.py` - Queue with end_date
- `/app/backend/routers/ib_collector_router.py` - Collection endpoints
- `/app/documents/scripts/ib_data_pusher.py` - Local IB fetcher (updated for end_date)
- `/app/documents/scripts/import_vendor_data.py` - Vendor bulk import
