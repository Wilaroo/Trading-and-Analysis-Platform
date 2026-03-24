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
2. **NIA (Neural Intelligence Agency)** - AI performance, strategy lifecycle, learning, data collection, backtesting
3. **Trade Journal** - Trade logging and analysis
4. **Charts** - Technical analysis
5. **Glossary & Logic** - Reference documentation
6. **Settings** - Configuration

## What's Been Implemented

### Completed Features
1. Robust Data Pipeline - Historical data collection for all timeframes (33,387 completed jobs, ~39M bars)
2. Startup Status Dashboard - Fast `/api/startup-check` endpoint, responsive modal
3. Comprehensive User Guide - Detailed, visual, downloadable guide
4. Resource Prioritization System ("Focus Mode")
5. Startup & Polling Optimization - Prevents backend overload
6. Job Processing Pipeline - Background job creation, queuing, execution
7. Persistent Chat History - Messages persist across sessions/refreshes
8. Market Regime Clarity - Improved panel readability
9. Shadow Learning - Auto-evaluates "shadow" trade decisions
10. NIA Page Refactoring - Modular component architecture
11. QuickStats Bar Enhancement
12. Frontend Performance Optimization - Two-phase data fetching

### Backend Event Loop Fix (Feb 2026) - COMPLETED
- ThreadPoolExecutor(max_workers=32) in server.py startup
- Alpaca SDK timeouts (10s) via asyncio.wait_for on all SDK calls + async client initialization
- 20+ synchronous DB calls wrapped in asyncio.to_thread across server.py, sentcom_service.py, ai_assistant_service.py, trading_bot_service.py
- Result: All endpoints respond under 500ms with 8 concurrent requests

### AI Comparison Backtesting (Mar 2026) - COMPLETED
**Problem**: User wanted to know if their trained AI model (LightGBM time-series predictor) actually improves trading results.

**Solution**: Built a three-way comparison backtest system:
1. **Setup-only**: Traditional entry signals (no AI)
2. **AI+Setup (filtered)**: Entry requires both setup signal AND AI confirmation
3. **AI-only**: Only enter when AI predicts "up" movement

**Implementation**:
- `advanced_backtest_engine.py` — Added `run_ai_comparison_backtest()`, `_simulate_strategy_with_ai()`, `_get_ai_prediction()`, `_compute_mode_metrics()`, `AIComparisonResult` dataclass
- `advanced_backtest_router.py` — Added `POST /api/backtest/ai-comparison` (sync + background job modes), `GET /api/backtest/ai-comparison/status`
- `server.py` — Wired timeseries model into backtest engine via `set_timeseries_model()`
- `AdvancedBacktestPanel.jsx` — New "AI Comparison" tab with full config form and results display

**Results** (AAPL/MSFT/NVDA, ORB strategy, 9 months):
- Setup-only: 96 trades, 39.6% win rate, $684 profit, Sharpe 0.48
- AI+Setup: 28 trades, **50% win rate**, $1,518 profit, Sharpe 3.4
- AI-only: 92 trades, 42.4% win rate, $783 profit
- AI filtered 71% of trades, keeping only high-confidence entries

### Infrastructure Cleanup (Mar 2026) - COMPLETED
- Fixed `/api/scanner` prefix conflict between predictive scanner and market scanner
- Market scanner moved to `/api/market-scanner`
- Fixed MongoDB ObjectId serialization in market_scanner_service.py

## Service Architecture Audit

### Scanners (Keep/Phase Out)
| Service | Lines | Status |
|---------|-------|--------|
| `enhanced_scanner.py` | 4,044 | **PRIMARY** — 15+ setup checks, tape reading, market regime |
| `background_scanner.py` | 921 | **DEAD CODE** — Variable aliased to enhanced_scanner in server.py |
| `predictive_scanner.py` | 1,105 | **ACTIVE** — On-demand "forming setups" for scanner UI |
| `market_scanner_service.py` | 973 | **ACTIVE** — Market-wide scanning with filters |

### Backtesting (Keep/Phase Out)
| Service | Lines | Status |
|---------|-------|--------|
| `advanced_backtest_engine.py` | 2,200+ | **PRIMARY** — Multi-strategy, walk-forward, Monte Carlo, AI comparison |
| `backtest_engine.py` | 635 | **SUPERSEDED** — Basic single-strategy, replaced by advanced |
| `historical_simulation_engine.py` | 1,633 | **ACTIVE** — Full AI pipeline replay for simulations |

### Shadow Tracking (Both Active)
| Service | Lines | Status |
|---------|-------|--------|
| `shadow_tracker.py` | 459 | AI decision logging (debate, risk, timeseries) |
| `shadow_mode_service.py` | 574 | Trade signal validation against real outcomes |

## Prioritized Backlog

### P1
- Implement Best Model Protection — only save new models if accuracy > current active model
- Consolidate `predictive_scanner.py` to delegate setup checks to `enhanced_scanner`
- Phase out `background_scanner.py` (dead code) and `backtest_engine.py` (superseded)

### P1.5
- **AI Parameter Auto-Optimizer** — Sweep AI confidence thresholds (0.0→0.5) and lookback windows (20→200) across strategies to find the optimal settings per strategy. Runs as a background job and surfaces the best parameter combination automatically.

### P2
- Enable GPU for LightGBM
- Complete backend router refactoring (activate modular routers in server.py)
- Migrate remaining ~85 raw fetch() calls to centralized api utility
- Merge `historical_simulation_engine` AI pipeline into `advanced_backtest_engine` as "AI Simulation" mode

### P3
- Setup-specific AI Models (77 trading setups)
- Backtesting Workflow Automation — auto-run backtests on model retraining

## Key API Endpoints
- `/api/startup-check` - Fast consolidated status check
- `/api/backtest/ai-comparison` - POST: Run AI comparison backtest
- `/api/backtest/ai-comparison/status` - GET: Check AI model availability
- `/api/backtest/jobs` - GET: List backtest jobs
- `/api/market-scanner/symbols` - GET: List scannable symbols (was /api/scanner)
- `/api/live-scanner/alerts` - GET: Live trading alerts
- `/api/scanner/scan` - POST: On-demand setup scanning
- `/api/sentcom/positions` - User positions with P&L
- `/api/ai-modules/timeseries/status` - AI model status

## Technical Notes
- **CRITICAL**: Never use synchronous I/O in async functions. Always use `asyncio.to_thread` for blocking calls.
- ThreadPoolExecutor with 32 workers configured as default asyncio executor
- All Alpaca SDK calls have 10s timeout via `asyncio.wait_for`
- AI backtest uses `_get_ai_prediction()` which calls the LightGBM model's `predict()` with reversed bars (most-recent-first)
- Model UP_THRESHOLD = 0.52, confidence formula: `(prob_up - 0.52) / (1 - 0.52)`, typical values 0.0-0.2
- Default `ai_confidence_threshold` = 0.0 (any "up" direction counts as confirmation)
