# SentCom AI Trading Platform - PRD

## Original Problem Statement
AI-powered trading platform that combines market scanning, strategy simulation, and autonomous learning to assist with trading decisions. The system integrates with Interactive Brokers via IB Gateway, uses AI models for predictions, and provides a comprehensive dashboard for monitoring and managing trading activities.

## Architecture
- **Frontend**: React with Tailwind CSS, Shadcn UI components
- **Backend**: FastAPI (Python) with MongoDB
- **AI**: PyTorch, LightGBM, Ollama Pro, Emergent LLM Key (GPT-4o fallback)
- **Data**: MongoDB Atlas, ChromaDB
- **Trading**: Interactive Brokers (IB Gateway), Alpaca

## Core Tabs
1. **Command Center** - Main dashboard with positions, P&L, bot performance, market regime
2. **NIA (Neural Intelligence Agency)** - AI performance, strategy lifecycle, learning, data collection
3. **Trade Journal** - Trade logging and analysis
4. **Charts** - Technical analysis
5. **Glossary & Logic** - Reference documentation
6. **Settings** - Configuration

## What's Been Implemented

### Completed Features
1. Robust Data Pipeline - Historical data collection for all timeframes
2. Startup Status Dashboard - Fast `/api/startup-check` endpoint, responsive modal
3. Comprehensive User Guide - Detailed, visual, downloadable guide
4. Resource Prioritization System ("Focus Mode")
5. Startup & Polling Optimization - Prevents backend overload
6. Job Processing Pipeline - Background job creation, queuing, execution
7. Persistent Chat History - Messages persist across sessions/refreshes
8. Market Regime Clarity - Improved panel readability
9. Shadow Learning - Auto-evaluates "shadow" trade decisions
10. StartupModal Rearchitecture - Single `/api/startup-check` endpoint, <3s load
11. Data Persistence Fix - CSS-based tab switching (no unmount/remount)
12. P&L Calculation Fix - Handles null values from IB Gateway
13. Learning Insights Widget Fix - Correct per-strategy aggregation
14. Bot Performance Chart Fix - No blanking during load
15. `/api/ib-collector/fill-gaps` Fix - Non-blocking database operations

### NIA Page Refactoring (Mar 24, 2026) - COMPLETED
Refactored 3120-line monolithic `NIA.jsx` into modular directory structure with 10+ focused components, QuickStats bar, two-phase data fetching.

### Backend Event Loop Fix (Feb 2026) - COMPLETED
**Problem**: Synchronous I/O operations (pymongo DB calls, Alpaca SDK calls) inside async functions blocked the asyncio event loop, causing API timeouts and frontend unresponsiveness.

**Solution**:
1. **ThreadPoolExecutor(max_workers=32)** in `server.py` startup - prevents thread starvation
2. **Alpaca SDK timeouts** (`ALPACA_CALL_TIMEOUT=10s`) via `asyncio.wait_for` on all SDK calls + async client initialization
3. **server.py inline route handlers** - 15+ DB calls wrapped in `asyncio.to_thread`
4. **sentcom_service.py** - `_save_chat_message`, `_cleanup_old_messages` made async with `to_thread`
5. **ai_assistant_service.py** - `_get_or_create_conversation`, `_load/_save_conversation_to_db`, `_track_request_pattern`, `get_conversation_history`, `clear_conversation`, `get_all_sessions` all made async with `to_thread`
6. **trading_bot_service.py** - Remaining `_persist_trade` calls in async context wrapped in `to_thread`

**Result**: All endpoints respond under 500ms even with 8 concurrent requests. No more event loop blocking.

## In Progress
- Autonomous Learning Loop automation

## Prioritized Backlog

### P1
- Implement Best Model Protection - Only save new models if accuracy > current active model

### P2
- Enable GPU for LightGBM
- Complete backend router refactoring (activate modular routers in server.py)
- Migrate remaining ~85 raw fetch() calls to centralized api utility

### P3
- Setup-specific AI Models (77 trading setups)
- Backtesting Workflow Automation

## Key API Endpoints
- `/api/startup-check` - Fast consolidated status check
- `/api/sentcom/positions` - User positions with P&L
- `/api/ib-collector/fill-gaps` - Non-blocking historical data backfill
- `/api/learning/strategy-stats` - Aggregated performance data
- `/api/scanner/alerts` - Live trading alerts
- `/api/strategy-promotion/phases` - Strategy lifecycle phases
- `/api/strategy-promotion/candidates` - Promotion candidates
- `/api/ai-modules/timeseries/status` - AI model status
- `/api/learning-connectors/status` - Connector health

## Technical Notes
- **CRITICAL**: Never use synchronous I/O in async functions. Always use `asyncio.to_thread` for blocking calls.
- ThreadPoolExecutor with 32 workers configured as default asyncio executor
- All Alpaca SDK calls have 10s timeout via `asyncio.wait_for`
- Frontend state persistence uses CSS display:none (not React key-based unmounting)
- DataCollectionPanel has its own 15s polling cycle (separate from NIA's 60s main poll)
- NIA uses two-phase fetch: fast endpoints update UI immediately, slow endpoints have 10s timeout
- All backend routes must be prefixed with `/api`
- Connector data from API may be array or object; AIModulesPanel normalizes it
