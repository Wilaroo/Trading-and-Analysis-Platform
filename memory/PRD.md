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
10. Backend Event Loop Fix - Wrapped sync SDK calls in `asyncio.to_thread`
11. StartupModal Rearchitecture - Single `/api/startup-check` endpoint, <3s load
12. Data Persistence Fix - CSS-based tab switching (no unmount/remount)
13. P&L Calculation Fix - Handles null values from IB Gateway
14. Learning Insights Widget Fix - Correct per-strategy aggregation
15. Bot Performance Chart Fix - No blanking during load
16. `/api/ib-collector/fill-gaps` Fix - Non-blocking database operations

### NIA Page Refactoring (Mar 24, 2026) - COMPLETED
Refactored 3120-line monolithic `NIA.jsx` into modular directory structure:

**File Structure:**
```
NIA/
  index.jsx          - Main orchestrator (~300 lines)
  QuickStatsBar.jsx  - 6 real-time metric cards at top
  IntelOverview.jsx  - 4 key metric cards with connector health dots
  LearningProgressPanel.jsx
  ReportCardPanel.jsx (moved up for visibility)
  DataCollectionPanel.jsx (coverage/collect/progress tabs)
  SimulationQuickPanel.jsx
  TestingToolsPanel.jsx (merged Scanner + Advanced Testing, tabbed)
  AIModulesPanel.jsx (merged AI Performance + Connectors, tabbed)
  StrategyPipelinePanel.jsx (merged Lifecycle + Promotions, tabbed)
  constants.js (shared phase colors/icons)
```

**Changes:**
1. Removed duplicate promotion sections
2. Deduplicated AI accuracy display
3. Shared phase constants extracted
4. Merged Scanner + Advanced Testing into tabbed panel
5. Merged AI Performance + Connectors into tabbed panel
6. Merged Lifecycle + Promotions into tabbed panel
7. Moved ReportCard up for visibility
8. Added connector health dot indicator to IntelOverview
9. Migrated raw fetch() calls to centralized api utility
10. Smarter default expand/collapse states
11. Two-phase data fetch (fast endpoints → immediate UI update, slow endpoints with 10s timeout)
12. Added QuickStats summary bar with 6 real-time metrics

## In Progress
- Autonomous Learning Loop automation

## Prioritized Backlog

### P1
- Implement Best Model Protection - Only save new models if accuracy > current active model

### P2
- Enable GPU for LightGBM
- Complete backend router refactoring (activate modular routers in server.py)
- Migrate remaining ~85 raw fetch() calls to centralized api utility
- Fix TradingBot event loop blocking (synchronous evaluations block async event loop)

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
- Frontend state persistence uses CSS display:none (not React key-based unmounting)
- DataCollectionPanel has its own 15s polling cycle (separate from NIA's 60s main poll)
- NIA uses two-phase fetch: fast endpoints update UI immediately, slow endpoints have 10s timeout
- All backend routes must be prefixed with `/api`
- Connector data from API may be array or object; AIModulesPanel normalizes it
