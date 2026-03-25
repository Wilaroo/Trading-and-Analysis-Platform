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
  - Empty string = current time (backward compatible)

- **New API Endpoints**:
  - `POST /api/ib-collector/max-lookback-collection` - Trigger full max lookback with chaining
  - `GET /api/ib-collector/chain-preview?symbol=X&bar_size=Y` - Preview chains for any symbol

- **Vendor Data Import Script**: `documents/scripts/import_vendor_data.py`
  - Streaming ndjson/CSV parser (constant memory)
  - Filters to qualifying symbols via ADV cache
  - Skips overlapping date ranges
  - bulk_write in batches of 5000
  - Progress tracking, resume support, dry-run mode

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
- IB Pusher / Gateway connection stability (localhost:8001 timeouts)
- User to purchase vendor 1-min data and run import script

### P2 - Upcoming
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
