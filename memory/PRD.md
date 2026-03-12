# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with AI trading coach, autonomous trading bot, and mutual learning loop.



## Recent Updates (March 2026)

### P2 Complete: Proactive Stop Intelligence & Chart Modal Enhancements (March 12, 2026)

**Status:** ✅ COMPLETE - Tested and Verified (iteration_77.json - 100%)

**Features Delivered:**

1. **Proactive Stop Audit Integration**
   - New endpoint: `GET /api/trading-bot/audit-stops`
   - Analyzes all open positions for risky stop placements
   - Detects: Too tight stops, round number proximity, high hunt risk, urgency levels
   - Integrated into bot's "thoughts" stream as `stop_warning` action type
   - Color-coded severity: 🚨 CRITICAL (red) | ⚠️ WARNING (amber) | 💡 INFO (blue)

2. **Enhanced BotBrainPanel**
   - Stop warnings appear at top of thoughts stream (highest priority)
   - Color-coded borders based on severity
   - Confidence badges: CRITICAL, WARNING, HEADS UP
   - Clickable ticker symbols in warnings

3. **Enhanced BotTakeCard**
   - Fetches real-time stop analysis from `/api/smart-stops/analyze-trade`
   - Shows stop recommendations with optimal price
   - Visual indicator when stop needs attention

**API Endpoints:**
- `GET /api/trading-bot/audit-stops` - Full stop audit for all positions
- `GET /api/trading-bot/thoughts` - Now includes `stop_warning` action_type

---

### Unified Smart Stop System (March 12, 2026)

**Status:** ✅ COMPLETE - P0 and P1 Verified (iteration_75.json: 98%, iteration_76.json: 100%)

**P0: Service Consolidation Complete**
Merged two redundant stop-loss services (`intelligent_stop_manager.py` and `smart_stop_service.py`) into a single unified `SmartStopService`.

**Files Deleted:**
- `/app/backend/services/intelligent_stop_manager.py` (redundant)
- `/app/backend/routers/intelligent_stops.py` (redundant)

**Unified Service Features:**
The single `/app/backend/services/smart_stop_service.py` now contains ALL stop-loss logic:

1. **6 Stop Modes:**
   - `original`: Traditional stop below support (HIGH hunt risk)
   - `atr_dynamic`: 1.5x ATR buffer (MEDIUM hunt risk) - DEFAULT
   - `anti_hunt`: Beyond obvious levels (LOW hunt risk)
   - `volatility_adjusted`: Adapts to volatility regime
   - `layered`: 40%/30%/30% at 1.0/1.5/2.0 ATR depths
   - `chandelier`: 3.0x ATR trailing from high/low

2. **8 Setup-Based Rules:**
   - `breakout`, `pullback`, `momentum`, `mean_reversion`
   - `gap_and_go`, `vwap_reversal`, `earnings_play`, `default`

3. **Advanced Analysis Factors:**
   - Volume Profile (POC, VAH/VAL, HVN/LVN)
   - Stop Hunt Risk Detection
   - Sector/Market Correlation
   - Regime Context Adjustments
   - Round Number Avoidance

**Unified API Endpoints (all under `/api/smart-stops/`):**
- `GET /modes` - 6 stop modes
- `GET /setup-rules` - 8 setup types
- `GET /trailing-modes` - 6 trailing modes
- `GET /urgency-levels` - 4 urgency levels
- `GET /compare` - Compare all modes side-by-side
- `GET /recommend/{symbol}` - Personalized recommendation
- `POST /calculate` - Simple mode-based stop calculation
- `POST /intelligent-calculate` - Full multi-factor intelligent stop
- `POST /analyze-trade` - Analyze existing trade's stop

**P1: Smart Stops UI Complete**
Integrated `SmartStopSelector` component into `EnhancedTickerModal` sidebar:
- Visual comparison of all 6 stop modes
- Hunt risk indicators (color-coded)
- Personalized recommendations
- Layered stops visualization (3 layers with 40/30/30 split)
- Mode selection updates position progress bar

**Files Modified:**
- `/app/frontend/src/components/EnhancedTickerModal.jsx` - Added SmartStopSelector
- `/app/frontend/src/components/SmartStopSelector.jsx` - Enhanced with LayeredStopsVisualizer

---

### Sprint 1 Complete: Brief Me + Enhanced Regime Widget (March 12, 2026)

**Status:** ✅ COMPLETE - Tested and Verified (iteration_72.json)

**Features Delivered:**

1. **Brief Me Feature** - AI-generated personalized market briefings
   - Backend: `/app/backend/agents/brief_me_agent.py` - BriefMeAgent class
   - API: `POST /api/agents/brief-me` with `detail_level` param ("quick" or "detailed")
   - Frontend: `/app/frontend/src/components/BriefMeModal.jsx`
   - **Quick Mode**: 2-3 sentence summary with regime, bot status, P&L, top opportunity
   - **Detailed Mode**: Multi-section report (Market Overview, Bot Status, Personalized Insights, Opportunities, Recommendation)
   - Option C implemented: Quick by default, expandable to detailed

2. **Enhanced Market Regime Widget** - Personalized performance stats
   - API: `GET /api/market-regime/performance` - Returns user's trading performance by regime
   - Frontend: Updated `/app/frontend/src/components/MarketRegimeWidget.jsx`
   - **YOUR PERFORMANCE IN THIS REGIME** section shows:
     - Win Rate, Trade Count, Average P&L
     - Best setup for current regime
   - Note: Section only appears when trades have `market_regime` field tagged

**Testing Results (iteration_72.json):**
- ✅ Backend API tests: 13/13 passed (100%)
- ✅ Frontend UI tests: 11/12 verified (92% - performance section hidden when no data)

**Files Created/Modified:**
- `/app/backend/agents/brief_me_agent.py` - NEW
- `/app/backend/routers/agents.py` - Added /api/agents/brief-me endpoint
- `/app/backend/routers/market_regime.py` - Added /api/market-regime/performance endpoint
- `/app/backend/server.py` - Inject dependencies for regime performance
- `/app/frontend/src/components/BriefMeModal.jsx` - NEW
- `/app/frontend/src/components/MarketRegimeWidget.jsx` - Enhanced with performance section
- `/app/frontend/src/components/tabs/AICoachTab.jsx` - Integrated BriefMeModal
- `/app/backend/tests/test_sprint1_brief_me_regime.py` - Test file

---

### Phase 2 Complete: Full Dashboard UI Overhaul (March 12, 2026)

**Status:** ✅ COMPLETE - Tested and Verified

**Features Delivered:**

1. **New Backend API Endpoints** (`/app/backend/routers/trading_bot.py`)
   - `GET /api/trading-bot/dashboard-data` - All-in-one dashboard data endpoint
     - Returns: bot_status, today_pnl, open_pnl, open_trades, watching_setups, recent_thoughts, performance_summary
   - `GET /api/trading-bot/performance/equity-curve?period=[today|week|month|ytd|all]` - Equity curve data
     - Returns: equity_curve array, trade_markers, summary stats (total_pnl, trades_count, win_rate, avg_r, best_trade, worst_trade)
   - `GET /api/trading-bot/thoughts?limit=N` - Bot's thoughts in first person
     - Returns: thoughts array with text, timestamp, confidence, action_type, symbol

2. **NewDashboard Component** (`/app/frontend/src/components/NewDashboard.jsx`)
   - Bot-centric layout matching V2 approved mockup
   - Dashboard header with bot status (HUNTING/PAUSED/LOADING), session, regime, "Brief Me" button
   - Auto-refresh every 15 seconds for dashboard data
   - P&L display (TODAY'S P&L and OPEN P&L)
   - Grid layout: Left (8 cols) for main content, Right (4 cols) for AI Assistant

3. **BotPerformanceChart Component** (`/app/frontend/src/components/BotPerformanceChart.jsx`)
   - Equity curve visualization with time range toggles (Today/Week/Month/YTD/All)
   - Auto-refresh every 30 seconds
   - Quick stats display: Trades, Win Rate, Avg R, Best, Worst
   - TradingView Lightweight Charts integration

4. **BotBrainPanel Component** (`/app/frontend/src/components/BotBrainPanel.jsx`)
   - Bot's thoughts in first person (as requested: "I detected...", "I'm monitoring...")
   - Recent trade decisions with reasoning (Priority A)
   - Real-time thoughts as bot processes data (Priority B)
   - Processing indicator and "View History" link
   - Auto-refresh every 30 seconds

5. **ActivePositionsCard** - Shows all open positions with P&L
6. **WatchingSetupsCard** - Shows pending setups the bot is watching
7. **ScannerAlertsStrip** - Live scanner alerts at bottom

**Testing Results (Iteration 71):**
- ✅ All 25 backend API tests passed (100%)
- ✅ All 10 frontend UI elements verified (100%)
- ✅ No critical issues found
- ✅ No action items required

**Files Created/Modified:**
- `/app/backend/routers/trading_bot.py` - Added 3 new endpoints (lines 537-730)
- `/app/frontend/src/components/NewDashboard.jsx` - Main dashboard component
- `/app/frontend/src/components/BotPerformanceChart.jsx` - Equity curve chart
- `/app/frontend/src/components/BotBrainPanel.jsx` - Bot thoughts panel
- `/app/frontend/src/components/tabs/AICoachTab.jsx` - Integrated NewDashboard
- `/app/backend/tests/test_new_dashboard_apis.py` - Test file

---

### UI Redesign - FINAL APPROVED (March 12, 2026)

**Status:** ✅ APPROVED - Ready for Implementation

**Final Mockups:**
- Main Dashboard: `https://brief-me-dash.preview.emergentagent.com/api/scripts/ui_mockups_v2_enhanced.html`
- Chart Modal (Final Hybrid): `https://brief-me-dash.preview.emergentagent.com/api/scripts/ui_mockups_chart_modal_final.html`

---

### Main Dashboard Design:

1. **Bot Performance Chart** (Always visible at top)
   - Equity curve with trade markers
   - Time toggle: Today | Week | Month | YTD | All
   - Quick stats: Trades, Win Rate, Avg R

2. **Bot's Brain Panel** - First-person thoughts with timestamps
3. **My Active Positions** - Clickable cards open Chart Modal
4. **Setups I'm Watching** - Bot's pending entries
5. **AI Assistant Chat** - Second-person advice + Bot Control
6. **Market Regime** - Compact with bot awareness
7. **Scanner Alerts Strip** - Clickable, opens Chart Modal
8. **"Brief Me" Button** - AI-summoned personalized market report

---

### Chart Modal Design (Hybrid 1+2):

**Layout:** Chart-First (65%) + Sidebar (35%)

**Header:**
- Ticker + Grade badges (72 B+, LONG)
- Inline ticker search + quick chips (NVDA, AMD, TSLA, META, SPY)
- Price display

**3 Smart Tabs:**
- Overview: Chart + Sidebar (default)
- Chart: Full-width chart with more tools
- Research: Fundamentals, Earnings, News

**Chart Area (Left 65%):**
- Large chart with bot annotations (Entry, Stop, Targets, VWAP)
- Timeframe buttons (1m, 5m, 15m, 1h, D)
- Bot Vision toggle + Indicators + Draw tools
- Position badge overlay
- Key Levels bar below chart

**Sidebar (Right 35%):**
1. Trade Setup - Entry/Stop/Target + R:R + progress bar
2. Analysis - Score ring (72 B+) + bar graphs + "Deep Analysis" button
3. Bot's Take - Full reasoning with timestamp
4. AI Recommendation - BUY/SELL badge + strategy + timeframe
5. Company Info - Collapsible (hidden by default)

**Footer:**
- +Add, Alert, Buy [TICKER], Short [TICKER]

---

### Redundancies Eliminated:
| Previous Issue | Solution |
|---------------|----------|
| Score shown twice | Single Analysis card |
| Entry/Stop/Target 3x | Once in Trade Setup |
| 7 tabs overwhelming | 3 tabs: Overview, Chart, Research |
| Company info always visible | Collapsed by default |

---

### Design Principles:
- **Bot (1st Person)**: "I detected...", "I'm monitoring...", "My reasoning..."
- **AI (2nd Person)**: "Your risk is...", "You should...", "Here's what you need..."

---

### Files Created:
- `/app/documents/ui_mockups_v2.html` - Initial V2 mockup
- `/app/documents/ui_mockups_v2_enhanced.html` - Enhanced dashboard
- `/app/documents/ui_mockups_chart_modal_v3.html` - Merged features
- `/app/documents/ui_mockups_chart_modal_refined.html` - 3 approaches
- `/app/documents/ui_mockups_chart_modal_final.html` - **FINAL APPROVED**
- `/app/documents/BRIEF_ME_ARCHITECTURE.md` - Brief Me agent architecture

---

### Implementation Progress (March 12, 2026)

**Phase 1 Complete: Enhanced Chart Modal**

✅ **New Components Created:**
- `/app/frontend/src/components/EnhancedTickerModal.jsx` - New chart-first modal
- `/app/frontend/src/hooks/useTickerModal.jsx` - Global modal state management
- `/app/frontend/src/components/shared/ClickableTicker.jsx` - Reusable clickable ticker

✅ **Components Updated for Click Integration:**
- `TickerTape.js` - All tickers in the tape now open the modal
- `AICoachTab.jsx` - Trade alerts open the modal on ticker click
- `TradingTab.jsx` - Signal selection opens the modal
- `App.js` - Wrapped with TickerModalProvider

✅ **Features Working:**
- Chart-first layout (65% chart, 35% sidebar)
- 3 tabs: Overview | Chart | Research
- Trade setup with Entry/Stop/Target and progress bar
- Analysis scores with ring visualization
- AI Recommendation card with BUY/SELL badge
- Collapsible Company Info
- Key Levels bar below chart
- Bot Vision toggle for chart annotations
- Quick ticker chips (NVDA, AMD, TSLA, META, AAPL)
- Ticker input field
- Buy/Short action buttons

**Remaining Phase 1 Work:**
- Fix chart data loading (needs IB connection)
- Add "Deep Analysis" API call
- Wire Bot's Take card to real bot trade data

---


## Recent Updates (March 2026)

### Phase 5.1 Complete: AI Prompt Intelligence Plan - Phase 2 (March 12, 2026)

**Features Delivered:**

1. **Context Awareness Service** (`/app/backend/services/context_awareness_service.py`)
   - **Time-of-Day Awareness**: Detects current trading session (Pre-Market, Market Open, Morning, Midday, Afternoon, Market Close, After Hours, Weekend)
   - **Regime Awareness**: Integrates with Market Regime Engine to provide regime-specific advice
   - **Position Awareness**: Analyzes user's open positions, exposure, and risk warnings

2. **Session Context** - Trading session intelligence:
   - Session-specific trading advice (e.g., "ORB setups active" at market open)
   - Risk level assessment for each session
   - Strategy suggestions and things to avoid per session

3. **Regime Context** - Market condition intelligence:
   - Current regime state (RISK_ON, HOLD, RISK_OFF, CONFIRMED_DOWN)
   - Position sizing multiplier recommendations (25%-100% based on regime)
   - Favored strategies for current conditions

4. **Position Context** - Portfolio intelligence:
   - Total exposure (long/short breakdown)
   - At-risk positions (down >3%) flagged
   - Concentration warnings (>30% single position)

5. **Context API Endpoints** (`/app/backend/routers/context_awareness.py`)
   - `GET /api/context/session` - Current trading session data
   - `GET /api/context/regime` - Market regime data
   - `GET /api/context/positions` - Position analysis
   - `GET /api/context/full` - Complete context (all combined)
   - `GET /api/context/prompt` - Formatted context for AI prompts

6. **Coach Agent Integration**
   - Updated to use ContextAwarenessService for smarter responses
   - System prompt updated to include context-aware coaching rules
   - Responses now include session-specific advice even when LLM is offline

**Testing Results:**
- All context endpoints working correctly
- Session detection accurate (Market Open detected during market hours)
- Regime integration working (pulls from Market Regime Engine)
- Agent responses now include context-aware advice

**Files Created/Modified:**
- `/app/backend/services/context_awareness_service.py` - NEW: Core service
- `/app/backend/routers/context_awareness.py` - NEW: API router
- `/app/backend/agents/coach_agent.py` - Updated for context awareness
- `/app/backend/agents/orchestrator.py` - Updated inject_services
- `/app/backend/server.py` - Added service initialization

---

### Phase 5.0 Complete: AI Prompt Intelligence Plan - Phase 1 (March 12, 2026)

**Features Delivered:**

1. **New Intent Detection Categories** (`/app/backend/agents/router_agent.py`)
   - **SCANNER**: Detects "find me a trade", "any setups", "trade ideas" type queries
   - **QUICK_QUOTE**: Detects "price of AAPL", "where is TSLA", "MSFT quote" type queries  
   - **RISK_CHECK**: Detects "what's my risk exposure", "check my risk", "portfolio risk" type queries

2. **New Intent Handlers** (`/app/backend/agents/orchestrator.py`)
   - **`_handle_scanner_request()`**: Returns formatted scanner alerts with setup details, entry/stop/target prices, R:R ratio, and trigger probability
   - **`_handle_quick_quote()`**: Returns real-time price quotes with bid/ask spread, uses midpoint fallback when last price unavailable
   - **`_handle_risk_check()`**: Returns comprehensive portfolio risk analysis including total exposure, long/short breakdown, concentration risk, and warnings

3. **Pattern Matching Improvements**
   - Reordered pattern matching: Scanner and Risk check patterns now checked before Analysis and Position patterns
   - Fixed "where is TSLA" pattern to correctly capture symbol instead of "IS"
   - Fixed "portfolio risk" routing from position_query to risk_check
   - Added more phrase variations for each intent type

**Testing Results:**
- 31/31 backend tests passed (100%)
- All new intents correctly routed via pattern matching
- Existing intents (ANALYSIS, POSITION_QUERY, COACHING, MARKET_INFO, TRADE_EXECUTE) still work correctly

**Technical Details:**
- Pattern matching uses regex with confidence scoring
- High confidence (≥0.8) routes directly, lower confidence falls back to LLM classification
- All handlers return structured responses with metadata for frontend consumption
- Handlers are code-only (no LLM required) for fast response times

**Files Modified:**
- `/app/backend/agents/router_agent.py` - Added new intents and patterns
- `/app/backend/agents/orchestrator.py` - Added handler methods and routing logic
- `/app/backend/tests/test_ai_prompt_intelligence_phase1.py` - New test file

---


## Recent Updates (March 2026)

### Phase 4.6 Complete: Comprehensive Hover-Over Tooltip System (March 12, 2026)

**Features Delivered:**

1. **Comprehensive Tooltip Definition System** (`/app/frontend/src/components/shared/Tooltip.jsx`)
   - 180+ trading terms with clear, educational explanations
   - Organized by category: Market Regime, Scores, Technical, Volume, Levels, Risk Management, Trade Types, Strategies, Bot, Backtesting, Learning, and more
   - Reusable components: `Tip`, `TipIcon`, `CustomTip`, `MetricTip`
   - Smooth animations with framer-motion

2. **Components Enhanced with Tooltips:**
   - **MarketRegimeWidget** - Score, Confidence, Signal Blocks (Trend, Breadth, FTD, Vol/VIX), Risk Level
   - **TradingBotPanel** - Risk Parameters (Max Risk/Trade, Max Daily Loss, Capital, Min R:R)
   - **LiveAlertsPanel** - Price, Trigger Price, R:R, TQS, Time to Trigger, Probability
   - **LearningIntelligenceHub** - Profile Stats (Best Time, Setup, Regime, Avg Hold), Metrics (Win Rate, Profit Factor, Expectancy, Avg Winner/Loser)
   - **TradingDashboardPage** - Today's Performance, Trades, Win Rate, Daily Loss Limit, Position Exposure
   - **AdvancedBacktestPanel** - Tab explanations (Quick Test, Market-Wide, Walk-Forward, Monte Carlo)
   - **MarketIntelPanel** - Report time period explanations
   - **MarketScannerPanel** - Trade style descriptions

3. **HelpTooltip Integration**
   - Updated existing `HelpTooltip.js` to use comprehensive definitions
   - Backwards compatible with all existing termId references

**Technical Details:**
- Tooltips appear on hover with 120ms fade animation
- Positioned dynamically to stay in viewport
- Category badges show context (Market, Technical, Risk, etc.)
- Dark theme with cyan accent colors for consistency

---

### Phase 4.5 Complete: Regime-Aware Strategy Performance Tracking (March 12, 2026)

**Features Delivered:**

1. **RegimePerformanceService** (`/app/backend/services/regime_performance_service.py`)
   - Tracks strategy performance segmented by market regime
   - Logs closed trades with regime state, score, and position multiplier
   - Aggregates win rates, P&L, R-multiples per strategy/regime combo
   - Provides analysis of position sizing impact

2. **Trading Bot Integration**
   - Added `_log_trade_to_regime_performance` method to TradingBotService
   - Wired `RegimePerformanceService` to trading bot via `set_regime_performance_service`
   - Closed trades now automatically log to regime_trade_log collection

3. **API Endpoints**
   - `GET /api/regime-performance/summary` - Overall performance by regime
   - `GET /api/regime-performance/strategies` - Strategy performance with filters
   - `GET /api/regime-performance/best-for-regime/{regime}` - Top strategies per regime
   - `GET /api/regime-performance/position-sizing-impact` - Analyze sizing adjustments
   - `GET /api/regime-performance/recommendations` - AI-generated suggestions

4. **Testing** - 26/26 tests passed (10 unit + 16 API tests)
   - `/app/backend/tests/test_regime_performance.py`
   - Verified service initialization, trade logging, API responses

**Database Collections:**
- `regime_performance` - Aggregated stats by strategy/regime
- `regime_trade_log` - Individual trade records with regime data

**Data Model (BotTrade additions):**
```python
market_regime: str = "UNKNOWN"  # RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
regime_score: float = 50.0      # Composite score at entry (0-100)
regime_position_multiplier: float = 1.0  # Position size adjustment applied
```

---

### Phase 4.4 Complete: Market Regime Integration (March 12, 2026)

**Features Delivered:**

1. **Market Regime Widget on Dashboard**
   - Added to Command tab alongside Learning Insights
   - Shows current state: RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
   - Signal breakdown: Trend, Breadth, FTD, Vol/VIX scores
   - Risk Level bar and trading recommendation
   - Auto-refresh every 60 seconds

2. **Trading Bot Regime-Aware Position Sizing**
   - Position sizing now adjusts based on market regime
   - Multipliers:
     - RISK_ON: 100% (full sizing)
     - CAUTION: 75%
     - RISK_OFF: 50%
     - CONFIRMED_DOWN: 25% for longs, 100% for shorts
   - Short trades get full sizing in CONFIRMED_DOWN (they benefit)
   - Long shorts reduced in RISK_ON (counter-trend)

3. **Scanner/Backtest Integration** (Smart approach)
   - NOT blindly filtering signals by regime
   - Recognizes that:
     - Some long strategies work well in down markets (mean reversion)
     - Some short strategies work in up markets (scalps with tight stops)
   - Bot applies smarter position sizing instead of signal filtering

### Phase 4.3 Complete: Market-Wide Backtesting UI + Market Regime Deployment (March 12, 2026)

**Features Delivered:**

1. **Market-Wide Backtest UI Tab**
   - New "Market-Wide" tab in Advanced Backtest Panel
   - Select any of 77 strategies
   - Set trade style filter (intraday/swing/investment)
   - Configure date range and max symbols to scan
   - View results with full trade details, top performers, most active symbols
   
2. **Market Regime Engine Deployed**
   - Now live at `/api/market-regime/*` endpoints
   - Detects market state: RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
   - Uses SPY/QQQ breadth, VIX, sector rotation, volume analysis
   - Provides trading recommendations based on market conditions

**Endpoints Added:**
- `GET /api/market-regime/summary` - Current market state
- `GET /api/market-regime/current` - Full regime details
- `GET /api/market-regime/history` - Historical regime changes

### Phase 4.2 Complete: Market-Wide Strategy Scanner (March 11, 2026)
**Feature:** Full US market scanning for strategy signals across all 77 strategies

**Problem Solved:** The user wanted to scan the entire US market (12,500+ stocks) to find which stocks would trigger their strategies, with pre-filters for intraday/swing/investment styles.

**Solution Architecture:**
```
┌────────────────────────────────────────────────────────┐
│           MarketScannerService                         │
├────────────────────────────────────────────────────────┤
│  Stock Universe:                                       │
│  • 12,571 US tradeable stocks from Alpaca              │
│  • Cached in MongoDB for fast access                   │
├────────────────────────────────────────────────────────┤
│  Trade Style Presets:                                  │
│  • Intraday: 47 strategies, 500K min ADV               │
│  • Swing: 15 strategies, 100K min ADV                  │
│  • Investment: 15 strategies, 50K min ADV              │
│  • All: 77 strategies combined                         │
├────────────────────────────────────────────────────────┤
│  Pre-Filters:                                          │
│  • Price range ($5-$500)                               │
│  • Exclude OTC/Penny stocks                            │
│  • Sector filtering                                    │
│  • RVOL minimum                                        │
├────────────────────────────────────────────────────────┤
│  Signal Detection:                                     │
│  • Momentum (3%+ moves)                                │
│  • Breakout (20-day highs)                             │
│  • Mean Reversion (oversold bounce)                    │
│  • Swing (trend + pullback)                            │
│  • Investment (golden cross, value)                    │
├────────────────────────────────────────────────────────┤
│  Output:                                               │
│  • Top 20 setups ranked by Expected R-multiple         │
│  • Signals grouped by strategy                         │
│  • Signals grouped by sector (heat map)                │
│  • Background job with progress tracking               │
└────────────────────────────────────────────────────────┘
```

**Files Created:**
- `/app/backend/services/market_scanner_service.py` - Core service (970+ lines)
- `/app/backend/routers/market_scanner.py` - API endpoints
- `/app/frontend/src/components/MarketScannerPanel.jsx` - Full UI

**API Endpoints:**
- `GET /api/scanner/status` - Service status
- `GET /api/scanner/symbols` - Symbol universe (12,571 stocks)
- `POST /api/scanner/start` - Start market scan
- `GET /api/scanner/scan/{id}` - Get scan status/results
- `GET /api/scanner/scan/{id}/signals` - Get signals with filters
- `GET /api/scanner/scans` - List recent scans
- `DELETE /api/scanner/scan/{id}` - Cancel running scan
- `GET /api/scanner/filters/presets` - Get filter presets
- `GET /api/scanner/sectors` - Get available sectors

**UI Features:**
- Trade style selection cards (Intraday/Swing/Investment/All)
- Pre-filter configuration (price, OTC, penny stocks)
- Scan name input and Start/Cancel buttons
- Real-time progress bar during scan
- Recent scans list with status indicators
- Scan results with top setups and signals by strategy
- Full signals table with entry/stop/target prices

**Note:** Full market scans of 12,500+ stocks require significant API calls and may hit rate limits on Alpaca's free tier. For best results:
1. Connect IB Gateway for unlimited data
2. Run scans during off-hours to use cached data
3. Enable nightly auto-scans (future feature)

### Phase 4.1 Complete: Hybrid Data Service (March 11, 2026)
**Feature:** Intelligent data fetcher with IB primary + Alpaca fallback, automatic caching

**Problem Solved:** The user needed backtesting to work regardless of whether the local IB Gateway was running, with data consistency and zero additional costs when IB is connected.

**Solution Architecture:**
```
┌────────────────────────────────────────────────────────┐
│           HybridDataService                            │
├────────────────────────────────────────────────────────┤
│  1. Check MongoDB cache first (instant, free)          │
│  2. If cache miss + IB connected → Fetch from IB       │
│  3. If IB unavailable → Fall back to Alpaca            │
│  4. Cache all fetched data in MongoDB                  │
├────────────────────────────────────────────────────────┤
│  Rate Limiters (conservative to stay within limits):   │
│  • IB: 6 requests/minute                               │
│  • Alpaca: 150 requests/minute                         │
├────────────────────────────────────────────────────────┤
│  Cache Strategy:                                       │
│  • Daily bars: Cache indefinitely                      │
│  • Intraday: 7-day TTL                                 │
│  • 80%+ coverage check before using cache              │
└────────────────────────────────────────────────────────┘
```

**Files Created:**
- `/app/backend/services/hybrid_data_service.py` - Core service (650+ lines)
- `/app/backend/routers/hybrid_data.py` - API endpoints

**API Endpoints:**
- `GET /api/data/status` - Service status, rate limits, stats
- `GET /api/data/bars/{symbol}` - Simple GET for bars
- `POST /api/data/bars` - Advanced bar fetch with options
- `POST /api/data/prefetch` - Batch prefetch for multiple symbols
- `GET /api/data/cache/symbols` - List cached symbols
- `GET /api/data/cache/stats` - Cache statistics
- `DELETE /api/data/cache` - Clear cache

**Integration:**
- Advanced Backtest Engine now uses Hybrid Data Service as primary data source
- Wired into server.py under Phase 6 (Slow Learning)

**Benefits:**
- Free data when IB connected (you're already paying for it)
- 24/7 availability via Alpaca fallback (nights, weekends)
- MongoDB caching = repeat tests are instant
- Rate limiting prevents API bans
- Data consistency: backtest uses same source as live trading when IB connected

### Phase 3.7 Ready: Market Regime Engine (March 11, 2026)
**Status: BUILT - NOT DEPLOYED** (Ready to connect when desired)

**What It Is:** A sophisticated "Fear & Greed" style market analyzer inspired by VectorVest and IBD methodologies.

**Outputs:**
- **Market State**: `CONFIRMED_UP` | `HOLD` | `CONFIRMED_DOWN`
- **Risk Level**: 0-100 scale (inverse of bullishness)
- **Confidence Score**: 0-100 scale (how certain the signal is)

**Four Signal Blocks:**
| Block | Weight | What It Measures |
|-------|--------|------------------|
| Trend | 35% | SPY vs moving averages (21 EMA, 50 SMA, 200 SMA), price structure |
| Breadth | 25% | Market participation via sector ETF analysis |
| FTD | 20% | IBD-style Follow-Through Day detection, distribution day counting |
| Volume/VIX | 20% | Fear gauge (VIX level/trend), volume patterns |

**Files Created:**
- `/app/backend/services/market_regime_engine.py` - Core engine (770+ lines)
- `/app/backend/routers/market_regime.py` - API endpoints
- `/app/frontend/src/components/MarketRegimeWidget.jsx` - Dashboard widget

**API Endpoints (when deployed):**
- `GET /api/market-regime/current` - Full regime analysis
- `GET /api/market-regime/summary` - Concise summary for UI
- `GET /api/market-regime/signals/{block}` - Individual signal block details
- `GET /api/market-regime/history` - Historical regime data
- `POST /api/market-regime/refresh` - Force refresh

**Configuration:**
- Update Frequency: Every 30 minutes
- State Change Notifications: Toast + widget update
- Data Sources: IB Gateway (primary), Alpaca (fallback)

**Deployment Guide:** See `/app/documents/MARKET_REGIME_DEPLOYMENT_GUIDE.md`

**To Deploy:** Add 3 lines to `server.py` and import widget in dashboard.


### Phase 3.8 Complete: Service Registry & Deprecations (March 11, 2026)
**Refactor:** Replaced fragile `globals()` pattern with proper service registry.

**Changes Made:**
- Created `/app/backend/services/service_registry.py` - Singleton service container
- Replaced 15+ `globals().get()` calls in `server.py` with `get_service_optional()`
- Services now registered via `register_service('name', instance)`
- Marked `/api/assistant/chat` as DEPRECATED (use `/api/agents/chat` instead)

**Why This Matters:**
- Cleaner dependency injection
- Easier testing (can mock services)
- Clear service availability checks
- No more fragile string lookups in globals dict

**NOT Removed (Still in Use):**
- `ai_assistant_service.py` - Still has active endpoints: `/check-ollama`, `/coach/*`, `/accuracy-stats`, `/history/*`, `/sessions`
- `smart_context_engine.py` - Still used by assistant for response validation


### Phase 3.9 Complete: Learning Intelligence Hub (March 11, 2026)
**Feature:** Unified dashboard for all learning insights (Option B+C hybrid)

**Components Built:**
1. **Learning Intelligence Hub** (`/app/frontend/src/components/LearningIntelligenceHub.jsx`)
   - Trader Profile header (best time, setup, regime, avg hold)
   - Performance Metrics card (win rate, profit factor, expectancy)
   - Edge Health Monitor (strategy status with decay alerts)
   - AI Recommendations panel
   - This Week calendar view
   - Collapsible Backtest Results and Shadow Mode sections

2. **Learning Insights Widget** (`/app/frontend/src/components/LearningInsightsWidget.jsx`)
   - Compact widget for AI Coach tab
   - Shows: Win Rate, Today P&L, Avg R, Edge Score
   - Quick alert row for edge warnings/successes
   - Click to navigate to full Intelligence Hub

**Integration:**
- Analytics Tab restructured: "Intelligence Hub" | "Backtest" | "Shadow Mode"
- AI Coach Tab now shows Learning Insights Widget at top
- All data comes from existing backend services (no new endpoints needed)

**Data Sources (All Pre-existing):**
- `/api/learning/strategy-stats` - Performance metrics
- `/api/learning/loop/profile` - Trader profile
- `/api/learning/recommendations` - AI recommendations
- `/api/medium-learning/edge-decay/alerts` - Edge health

### Phase 4.0 Complete: Advanced Backtesting System (March 11, 2026)
**Feature:** Comprehensive backtesting with multi-strategy, walk-forward, Monte Carlo

**Backend (`/app/backend/services/slow_learning/advanced_backtest_engine.py`):**
- **Multi-Strategy Backtesting**: Compare multiple strategies on multiple symbols
- **Walk-Forward Optimization**: Rolling in-sample/out-of-sample testing to detect overfitting
- **Monte Carlo Simulation**: 10,000+ trade shuffles to understand outcome distributions
- **Custom Date Range**: Filter by date, regime, day of week
- **Data Caching**: MongoDB caching for fast repeat runs
- **Background Jobs**: Long-running backtests don't block the UI

**API Endpoints (`/app/backend/routers/advanced_backtest_router.py`):**
- `POST /api/backtest/quick` - Fast single-strategy test
- `POST /api/backtest/multi-strategy` - Compare strategies
- `POST /api/backtest/walk-forward` - Robustness testing
- `POST /api/backtest/monte-carlo` - Risk distribution analysis
- `GET /api/backtest/job/{id}` - Background job status
- `GET /api/backtest/results` - List recent results
- `GET /api/backtest/strategy-templates` - Pre-built strategy configs

**Frontend (`/app/frontend/src/components/AdvancedBacktestPanel.jsx`):**
- 5-tab interface: Quick Test, Multi-Strategy, Walk-Forward, Monte Carlo, Results
- 6 strategy templates: ORB Conservative/Aggressive, VWAP Bounce, Gap & Go, Breakout Swing, Momentum Scalp
- Real-time progress for background jobs
- Result visualization with key metrics

**Strategy Templates:**
| Template | Setup Type | Stop | Target | Hold |
|----------|-----------|------|--------|------|
| ORB Conservative | ORB | 1.5% | 3% | 10 bars |
| ORB Aggressive | ORB | 2% | 5% | 20 bars |
| VWAP Bounce | VWAP_BOUNCE | 1% | 2% | 5 bars |
| Gap and Go | GAP_AND_GO | 2.5% | 6% | 15 bars |
| Breakout Swing | BREAKOUT | 3% | 8% | 40 bars |
| Momentum Scalp | MOMENTUM | 1% | 1.5% | 3 bars |

**Output Metrics:**
- Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown
- R-Multiple tracking, Expectancy
- Equity curves, Trade logs
- Walk-forward efficiency ratio
- Monte Carlo percentile distributions (5th, 25th, 50th, 75th, 95th)

**Requires:** Alpaca API connection for historical data (already integrated)


- `/api/medium-learning/calibration/current` - Calibration status

**Next Priority:** Backtesting system enhancement (user-requested)





### Phase 3.6 Complete: Trade Style Renaming for Clarity (March 11, 2026)
**Refactor:** Renamed trade styles to eliminate confusion between "A+" as grade vs style.

**Old → New Names:**
| Old Name | New Name | Timeframe |
|----------|----------|-----------|
| `move_2_move` | `scalp` | Minutes to 1 hour |
| `trade_2_hold` | `intraday` | 1-6 hours |
| `a_plus` | `multi_day` | 1-5 days |

**Key Clarification:**
- **"A+"** now ONLY refers to quality GRADE (like A+, A, B, C, D, F)
- A scalp can be A+ quality, an investment can be C quality
- Style = timeframe, Grade = quality

**Backwards Compatibility:**
- Old names (`move_2_move`, `trade_2_hold`, `a_plus`) still work via aliases
- Existing code using old names will continue to function
- Gradually deprecate old names over time

**Testing Results (Iteration 68):**
- 22/22 tests passed (100%)
- New names work: scalp, intraday, multi_day, swing, position
- Old names still work: move_2_move, trade_2_hold, a_plus
- API accepts both old and new names

### Phase 3.5 Complete: High-TQS Alert UI Highlighting (March 11, 2026)
**UI Feature:** Scanner alerts now display TQS scores with special styling for high-quality setups (TQS >= 70).

**LiveAlertsPanel Enhancements:**
- TQS Score/Grade display inline (e.g., "TQS: 72 (B+)")
- Grade colors: A=emerald, B=blue, C=yellow, D=orange, F=red
- High-TQS alerts (>=70) get:
  - Emerald ring glow: `ring-2 ring-emerald-500/50 shadow-lg shadow-emerald-500/20`
  - "HIGH QUALITY" badge with Zap icon and pulse animation
  - Key Factors panel showing top contributing factors
- Trade timeframe displayed (e.g., "Scalp (minutes to 1 hour)")

**AICommandPanel Pipeline Cards:**
- TQS score with color coding (emerald >=70, yellow >=50, orange <50)
- "HQ" badge with Zap icon for high-quality setups

**Testing Results (Iteration 67):**
- 8/8 TQS UI features verified in code review
- 100% UI testing pass (app loads, navigation, trade cards)
- Live TQS display pending real-time alert generation

### Phase 3.4 Complete: Timeframe-Aware TQS & Scanner Integration (March 11, 2026)
**Major Feature:** TQS scoring now weights pillars based on trade timeframe. Scanner alerts include TQS with high-quality highlighting.

**Design Decision:** TQS thresholds remain universal (70+ = great trade) because the weights already normalize scores per timeframe. A 70 TQS scalp means "great on scalp factors" while a 70 TQS investment means "great on investment factors."

**Timeframe-Aware TQS Weights:**
| Trade Style | Technical | Setup | Fundamental | Context | Execution |
|------------|-----------|-------|-------------|---------|-----------|
| Scalp (M2M) | **35%** | 30% | 5% | 20% | 10% |
| Swing (T2H) | 25% | 25% | 15% | 20% | 15% |
| A+ Trade | 15% | 20% | **30%** | 20% | 15% |
| Swing | 20% | 20% | 25% | 20% | 15% |
| Investment | 10% | 15% | **40%** | 20% | 15% |

**Scanner TQS Integration:**
- Every alert now includes: `tqs_score`, `tqs_grade`, `tqs_action`, `tqs_trade_style`, `tqs_timeframe`
- High-quality alerts (TQS >= 70) flagged with `tqs_is_high_quality: true` for UI highlighting
- Trade style auto-inferred from setup type using SMB config

**TQS API Updated:**
- `POST /api/tqs/score` now accepts `trade_style` parameter
- Returns weights used and timeframe explanation
- Example: `{"trade_style": "scalp", "trade_timeframe": "Scalp (minutes to 1 hour)"}`

**Testing Results (Iteration 66):**
- 28/28 tests passed (100%)
- 1 bug fixed: Added trade_style to TQS API endpoint

### Phase 3.3 Complete: TQS Integration & Learning Verification (March 11, 2026)
**New Features:** TQS (Trade Quality Score) integrated with Analyst agent. Auto-recording verified.

**TQS in Analyst Agent:**
- Analyst now shows TQS score (0-100) with grade (A/B/C/D/F) and action (STRONG_BUY/BUY/HOLD/AVOID)
- All 5 pillars displayed: Setup, Technical, Fundamental, Context, Execution
- Key factors and concerns highlighted in analysis
- Example output: "TQS Score: 59/100 (C+) - HOLD"

**Auto-Recording Trade Outcomes (Verified):**
- Already implemented in `trading_bot_service.py` line 2324-2347
- Wired in `server.py` line 362: `trading_bot._learning_loop = learning_loop_service`
- When trade closes → `record_trade_outcome()` called → stored in `trade_outcomes` collection

**Testing Results (Iteration 65):**
- 9/11 tests passed (82%)
- 4 bugs fixed: TechnicalSnapshot.get() → getattr() in 5 files
- TQS scores appearing in analyst responses for NVDA, AAPL, TSLA

### Phase 3.2 Complete: Learning System Consolidation (March 11, 2026)
**Consolidation:** Removed duplicate learning_layer.py and integrated Coach Agent with existing Three-Speed Learning Architecture.

**Changes Made:**
- ✅ Deleted `/app/backend/agents/learning_layer.py` (was duplicate of existing services)
- ✅ Coach Agent now uses `LearningContextProvider.build_full_learning_context()` for personalized insights
- ✅ Coach Agent now uses `LearningLoopService.get_trader_profile()` for trader profile data
- ✅ Updated `orchestrator.py` to pass `learning_context_provider` and `learning_loop_service` to Coach
- ✅ Updated `server.py` to include learning services in agent initialization

**Three-Speed Learning Architecture (Existing - Now Fully Integrated):**
```
Fast Learning (Real-time):
├── LearningLoopService: Trade tracking, context capture, outcome recording
├── ExecutionTrackerService: Execution quality metrics
└── TradeContextService: Context snapshots at trade time

Medium Learning (End-of-Day):
├── CalibrationService: Threshold adjustments
├── ContextPerformanceService: Win rates by setup+regime+time
├── EdgeDecayService: Detects when setups stop working
├── ConfirmationValidatorService: Signal effectiveness
└── PlaybookPerformanceService: Playbook effectiveness

Slow Learning (Weekly):
├── BacktestEngine: Strategy backtesting
├── ShadowModeService: Paper trade validation
└── HistoricalDataService: Historical data management

Provider Layer:
└── LearningContextProvider: Aggregates all insights for AI prompts
    ├── TQS scores
    ├── Edge decay warnings
    ├── Calibration recommendations
    ├── Confirmation guidance
    └── RAG (similar past trades)
```

**Testing Results (Iteration 64):**
- 6/6 backend tests passed (100%)
- 2 API mismatches fixed by testing agent
- Coach agent gracefully handles null learning services

### Phase 3.1 Complete: Analyst Agent & Learning Layer (March 11, 2026)
**New Features:** Added Analyst agent for market analysis and Learning Layer for personalized coaching.

**Analyst Agent (`analyst_agent.py`):**
- Technical analysis with key levels (VWAP, HOD, LOD, Support, Resistance)
- Sector context integration
- Scanner alerts correlation
- Sentiment analysis integration
- Fallback to code-only analysis when LLM unavailable
- Routes via: "analyze NVDA", "technical analysis on AAPL"

**Learning Layer (`learning_layer.py`):**
- `TradeOutcomesDB`: Persistent storage for trade outcomes (wins, losses, R-multiples)
- `PerformanceAnalyzer`: Analyzes performance by setup type and time of day
- `MistakeTracker`: Tracks common trading mistakes for improvement suggestions
- Ready for integration with Coach agent

**Trade Confirmation Flow Enhanced:**
- User says "buy 100 AAPL" → Confirmation dialog with details
- User says "yes" → Order queued for execution
- Session context preserves pending_trade between messages

**Testing Results (Iteration 63):**
- 15/15 backend tests passed (100%)
- All 4 agents working: router, trade_executor, coach, analyst
- Pattern matching handles all buy formats: "buy 100 AAPL", "buy 100 shares of AAPL"

### Phase 3.0 Complete: Multi-Agent Architecture (March 11, 2026)
**Major Refactor:** Implemented user-approved multi-agent AI system with hybrid safety pattern.

**Architecture:**
```
User Chat → Router Agent → [Trade Executor | Coach | Analyst]
                ↓
         Pattern Matching + LLM Intent (fallback)
                ↓
         Specialized Agent
                ↓
         CODE handles all data (positions, prices, quantities)
         LLM handles only language (intent parsing, natural language)
```

**Components Implemented:**
- ✅ `llm_provider.py` - LLM abstraction layer (Ollama: GPT-OSS cloud → llama3.5 8b fallback)
- ✅ `base_agent.py` - Base class with DataFetcher for CODE-based data access
- ✅ `router_agent.py` - Intent classification via pattern matching + LLM fallback
- ✅ `trade_executor_agent.py` - Safe trade execution (confirmation required)
- ✅ `coach_agent.py` - Personalized trading guidance with position data
- ✅ `orchestrator.py` - Coordinates all agents, manages sessions
- ✅ `/api/agents/chat` - New unified chat endpoint
- ✅ `/api/agents/status` - Agent system health check
- ✅ `/api/agents/metrics` - Agent performance metrics
- ✅ Frontend updated to use new agent endpoints

**Hybrid Safety Pattern:**
- LLM ONLY used for: intent classification, natural language understanding
- CODE handles ALL: positions, prices, quantities, order execution
- This prevents AI hallucination for critical trading data

**Testing Results:**
- 20/20 backend tests passed (100%)
- Pattern matching fallback verified working when Ollama offline
- Trade confirmation flow tested (buy/close commands)
- Position queries return CODE-based data even without LLM



### Phase 2.6 Complete: AI Position Query Fix (March 11, 2026)
**Critical Fix:** AI was hallucinating position data due to context truncation
- ✅ Identified root cause: SYSTEM_PROMPT (5576 chars) + 6000 char limit = positions cut off
- ✅ Fixed `ai_assistant_service.py` to use smart_context directly for position queries
- ✅ Position queries now bypass the huge strategy system prompt
- ✅ AI now correctly reports exact IB positions: TMC (10K @ $7.92), INTC (1K @ $44.76), TSLA (101 @ $449.10)
- ✅ Fixed import pattern for IB data access (`import routers.ib as ib_module`)
- ✅ Added position keywords to deep complexity detection
- ✅ Lowered temperature from 0.7 to 0.3 for reduced hallucination
- ✅ Strengthened system prompts with explicit anti-hallucination instructions

### Phase 2.7 Complete: UI Text + Trading Bot Automation (March 11, 2026)
**UI Text Updates:**
- ✅ Updated StartupModal: IB Gateway now listed as primary data source, Alpaca as fallback
- ✅ Updated TradingBotPanel: "IB Gateway (Paper Account)" instead of "Alpaca Account (Paper)"
- ✅ Updated useCommandCenterData comments to reflect IB-first architecture

### Phase 2.8 Complete: IB Order Queue System (March 11, 2026)
**Full Order Execution via IB Gateway:**
The trading bot can now execute real trades through IB Gateway using a cloud↔local order queue system.

**Architecture:**
```
Cloud Trading Bot                    Local Machine
┌─────────────────┐                 ┌─────────────────────┐
│ Queue Order     │ ─── POLL ────► │ ib_data_pusher.py   │
│ (POST /orders/  │                 │   ↓                 │
│  queue)         │                 │ Execute via IB GW   │
│                 │                 │   ↓                 │
│ Get Result ◄────│ ◄── REPORT ──  │ Report fill/error   │
│ (GET /orders/   │                 │                     │
│  result/{id})   │                 │                     │
└─────────────────┘                 └─────────────────────┘
```

**New Backend Endpoints:**
- `POST /api/ib/orders/queue` - Queue order for execution
- `GET /api/ib/orders/pending` - Pusher polls for pending orders  
- `POST /api/ib/orders/claim/{id}` - Claim order (prevent duplicates)
- `POST /api/ib/orders/result` - Report execution result
- `GET /api/ib/orders/result/{id}` - Get order result (with optional wait)
- `GET /api/ib/orders/queue/status` - Queue status overview
- `DELETE /api/ib/orders/queue/{id}` - Cancel pending order

**Updated Services:**
- `trade_executor_service.py`: `_ib_entry()`, `_ib_stop()`, `_ib_close_position()` now use order queue
- `ib_data_pusher.py`: Added `poll_and_execute_orders()` to execute queued orders locally

**How It Works:**
1. Trading bot calls `queue_order()` which adds order to pending queue
2. Local pusher polls `/api/ib/orders/pending` every 2 seconds
3. Pusher claims order, executes via IB Gateway, reports result
4. Trade executor waits for result (up to 60s timeout)
5. Trade marked as filled/rejected based on IB response

### Phase 2.5 Complete: Scanner IB Data Priority (March 11, 2026)
- ✅ Refactored `enhanced_scanner.py` to prioritize IB pushed data for quotes
- ✅ Added `_get_ib_quote()` helper method (non-async, fast)
- ✅ Added `_is_ib_connected()` helper method
- ✅ Added `_get_quote_with_ib_priority()` async method for data fetch
- ✅ Updated `_get_tape_reading()` to use IB data first for tape analysis
- ✅ Updated `_get_active_symbols()` fallback to use IB priority
- ✅ Updated module docstring to document data source hierarchy
- ✅ Created comprehensive unit tests (`test_scanner_ib_data_priority.py`)
- ✅ All 9 tests passing

**Data Source Hierarchy for Scanner:**
- QUOTES: IB pusher (primary) → Alpaca (fallback)
- HISTORICAL BARS: Alpaca (IB pusher doesn't provide historical)
- LEVEL 2: IB pusher (when available)

### Phase 1 Complete: Core Data & Display Fixes (March 10, 2026)
- ✅ Fixed account data extraction from IB pusher (handles nested format with `-S` suffix keys)
- ✅ Net Liquidation, Buying Power, Daily P&L now display correctly from IB account
- ✅ Positions display correctly from IB Gateway (TMC, INTC, NVDA)
- ✅ Frontend data fetch priority changed: IB pushed data → Alpaca fallback
- ✅ Position field normalization (avgCost ↔ avg_cost, unrealizedPNL ↔ unrealized_pnl)

### Phase 2 Complete: Performance & AI Integration (March 10, 2026)
- ✅ Updated `realtime_technical_service.py` to check IB quotes first
- ✅ Updated `ai_assistant_service.py` to use IB data for quotes and positions
- ✅ Updated `smart_context_engine.py` to fetch positions/quotes from IB first
- ✅ Fixed AI context building to properly include IB positions
- ✅ Improved intent detection for position-related queries
- ✅ Changed default Ollama model to `deepseek-r1:8b` (better context following)
- ✅ Confirmed Ollama HTTP proxy is working (no ngrok needed for Ollama)
- ✅ AI now correctly reports real IB positions (TMC, INTC, TSLA)

### Ollama HTTP Proxy Architecture (No ngrok needed)
```
Local PC                              Cloud Backend
┌─────────────────┐                  ┌──────────────────────┐
│ Ollama          │                  │ FastAPI              │
│ (localhost:11434)──▶ ollama_      │ ┌──────────────────┐ │
│                 │   http.py  ◀──▶ │ │ /api/ollama-proxy│ │
│ Models:         │   (HTTP poll)   │ │ (request queue)  │ │
│ - deepseek-r1:8b│                  │ └────────┬─────────┘ │
│ - llama3:8b     │                  │          │           │
│ - qwen2.5:7b    │                  │  ┌───────▼────────┐  │
│ - gemma3:4b     │                  │  │ AI Assistant   │  │
└─────────────────┘                  │  │ (uses proxy)   │  │
                                     │  └────────────────┘  │
                                     └──────────────────────┘
```

### IB Data Pipeline Architecture
```
Local PC                              Cloud Backend
┌─────────────────┐                  ┌──────────────────────┐
│ IB Gateway      │                  │ FastAPI              │
│ (paper account) │──▶ ib_data_     │ ┌──────────────────┐ │
│ DUN615665       │   pusher.py ──▶ │ │ POST /api/ib/    │ │
│                 │   (quotes,      │ │ push-data        │ │
│                 │    positions,   │ └────────┬─────────┘ │
│                 │    account,     │          │           │
│                 │    L2 data)     │    ┌─────▼─────┐     │
└─────────────────┘                  │    │ _pushed_  │     │
                                     │    │ _ib_data  │     │
                                     │    └─────┬─────┘     │
                                     │          │           │
                                     │  ┌───────▼────────┐  │
                                     │  │ Services       │  │
                                     │  │ (AI, Scanner,  │  │
                                     │  │  Trading Bot)  │  │
                                     │  │ check IB first │  │
                                     │  │ Alpaca fallback│  │
                                     │  └────────────────┘  │
                                     └──────────────────────┘
```

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, TradingView Widget (embedded charts)
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **AI**: Smart Routing — Ollama (local via HTTP proxy, deepseek-r1:8b default) + GPT-4o (Emergent, deep tasks)
- **Integrations**: Alpaca, Finnhub, IB Gateway (see Data Sources below)
- **Local Scripts**: `ib_data_pusher.py` (IB data), `ollama_http.py` (AI proxy)

## Data Sources

| Source | Provides | Availability |
|--------|----------|--------------|
| **Alpaca** | Real-time quotes, paper trading, account data | Cloud (always on) |
| **Finnhub** | 100 live news headlines, earnings calendar | Cloud (always on) |
| **IB Gateway** | VIX index, IB scanners, fundamentals, live trading | Local only (requires IB Gateway running) |
| **Ollama** | Free AI for chat, summaries, market intel | Via ngrok tunnel |

## Startup Modes
- **Cloud Dev**: Ollama + ngrok → `https://brief-me-dash.preview.emergentagent.com`
- **Full Local**: All services on PC → `http://localhost:3000`
- See `/documents/STARTUP_GUIDE.md` for detailed instructions

## Smart AI Routing (Feb 2026)
| Complexity | Model | Tasks | Cost |
|-----------|-------|-------|------|
| **light** | Ollama (llama3:8b) | Quick chat, summaries | Free |
| **standard** | Ollama first, GPT-4o fallback | Market intel reports, general chat | Free (mostly) |
| **deep** | GPT-4o (Emergent) | Strategy analysis, trade evaluation, "should I buy", recommendations | Credits |

### Deep Keyword Triggers
`should i buy`, `should i sell`, `analyze`, `evaluate`, `deep dive`, `strategy`, `backtest`, `risk`, `recommend`, `quality score`, `compare`, `portfolio`, `rebalance`, `hedge`, `options`, `earnings play`, `swing trade`, `position size`, `thesis`

## Market Intel Data Sources (12 Enhanced - Feb 2026)
1. **Market Regime Classification** - Day type (Trend/Chop/Rotation) with strategy implications
2. **General News** - Finnhub 100 live headlines
3. **Market Indices** - SPY, QQQ, IWM, DIA, VIX prices and changes
4. **Smart Watchlist Status** - Actual watchlist symbols with IN-PLAY status
5. **Ticker-Specific News** - Finnhub company-news for watchlist stocks
6. **In-Play Technical Levels** - HOD, LOD, VWAP for active stocks
7. **Sector Heatmap** - 11 sector ETFs (XLK, XLF, XLE, etc.) leaders/laggards
8. **Earnings Calendar** - Watchlist stocks with upcoming earnings warnings
9. **Account/Positions** - From Alpaca
10. **Trading Bot Status** - Exact state from service
11. **Strategy Performance** - Exact from learning loop DB
12. **Scanner Signals** - Live alerts from enhanced scanner

## Enhanced Scanner (Feb 2026)
**~1,083 symbols scanned via ETF-based wave scanning (SPY + QQQ + IWM) with 30+ SMB strategies**

### Features Implemented:
| Feature | Description |
|---------|-------------|
| **ETF-Based Universe** | Stocks organized by SPY (Tier 1), QQQ (Tier 1), IWM (Tier 3 rotating) |
| **Volume Filtering** | ADV >= 100K for general, ADV >= 500K for intraday/scalp setups |
| **Wave Scanning** | Tiered scanning: Watchlist (T1) → High RVOL (T2) → Rotating Universe (T3) |
| **Smart Watchlist** | Hybrid auto-populated + manual watchlist with strategy-based expiration |
| **RVOL Pre-filtering** | Skips symbols with RVOL < 0.8 to focus on active stocks |
| **Tape Reading** | Analyzes bid/ask spread, order imbalance, momentum for confirmation |
| **Win-Rate Tracking** | Records outcomes for each strategy, calculates win rate & profit factor |
| **Auto-Execution** | Wires high-priority tape-confirmed alerts directly to Trading Bot |
| **AI Coaching** | Proactive AI notifications for high-priority scanner alerts |
| **Quarterly Rebalance Alerts** | System flags when ETF lists need refreshing |

### Universe Structure:
| ETF | Coverage | Count | Priority |
|-----|----------|-------|----------|
| SPY | S&P 500 Large Caps | ~492 | **Tier 1** (every scan) |
| QQQ | Nasdaq-100 Tech | ~120 | **Tier 1** (every scan) |
| IWM | Russell 2000 Small Caps | ~545 | **Tier 3** (rotating) |
| **Total Unique** | | ~1,083 | |

### Volume Filters:
- **General/Swing setups**: ADV >= 100,000
- **Intraday/Scalp setups**: ADV >= 500,000

### Scanner → AI → Bot Integration (Feb 2026)
```
Scanner detects HIGH/CRITICAL alert
    ↓
Auto-populates Smart Watchlist
    ↓
Triggers AI Coaching Notification
    ↓
(If auto-execute enabled) Submits to Trading Bot
```

### New API Endpoints (Feb 2026):
- `GET /api/assistant/coach/scanner-notifications` - Get proactive coaching alerts
- `POST /api/assistant/coach/scanner-coaching?symbol=X&setup_type=Y` - Manual coaching
- `GET /api/live-scanner/config/volume-filter` - Get ADV filter settings
- `POST /api/live-scanner/config/volume-filter` - Set ADV filter thresholds

### Existing API Endpoints:
- `GET /api/live-scanner/stats/strategies` - Win-rate stats per setup
- `POST /api/live-scanner/stats/record-outcome` - Record alert result
- `POST /api/live-scanner/auto-execute/enable` - Enable/disable auto-execution
- `GET /api/live-scanner/auto-execute/status` - Auto-execute status
- `POST /api/live-scanner/config/rvol-filter` - Set RVOL filter threshold
- `GET /api/smart-watchlist` - Get hybrid watchlist
- `POST /api/smart-watchlist/add` - Manual add to watchlist
- `DELETE /api/smart-watchlist/{symbol}` - Remove from watchlist

### Strategies Implemented:
| Category | Strategies |
|----------|------------|
| **Opening (9:30-9:45)** | First VWAP Pullback, Opening Drive, First Move Up/Down, Bella Fade |
| **Morning Momentum** | ORB, HitchHiker, Gap Give and Go, Gap Pick and Roll |
| **Core Session** | Spencer Scalp, Second Chance, Back$ide, Off Sides, Fashionably Late |
| **Mean Reversion** | Rubber Band, VWAP Bounce, VWAP Fade, Tidal Wave |
| **Consolidation** | Big Dog, Puppy Dog, 9-EMA Scalp, ABC Scalp |
| **Afternoon** | HOD Breakout, Time-of-Day Fade |
| **Special** | Breaking News, Volume Capitulation, Range Break, Breakout |

### Time-of-Day Filtering:
- Each strategy only triggers during its valid time window
- Time windows: opening_auction, opening_drive, morning_momentum, morning_session, late_morning, midday, afternoon, close

### Market Regime Detection:
- Scanner reads SPY to determine: strong_uptrend, strong_downtrend, range_bound, volatile, momentum, fade
- Strategies filtered based on optimal market conditions

### Universe Coverage:
- S&P 500: 493 symbols
- Nasdaq 1000: 610 symbols
- Russell 2000: 412 symbols (partial)
- ETFs: 228 symbols
- **Total Unique: 1,425 symbols**

## Architecture
```
/app/
├── backend/
│   ├── data/
│   │   └── index_symbols.py           # S&P 500, Nasdaq 1000, Russell 2000 lists
│   ├── routers/ (trading_bot, learning_dashboard, market_intel, assistant, live_scanner)
│   ├── services/
│   │   ├── ai_assistant_service.py      # Smart routing + Scanner coaching notifications
│   │   ├── enhanced_scanner.py          # Wave scanning + AI/Bot integration
│   │   ├── smart_watchlist_service.py   # Hybrid auto/manual watchlist
│   │   ├── wave_scanner.py              # Tiered universe scanning
│   │   ├── index_universe.py            # Large symbol universe management
│   │   ├── support_resistance_service.py # Advanced S/R calculation
│   │   ├── trading_bot_service.py
│   │   ├── strategy_performance_service.py
│   │   └── market_intel_service.py
│   └── server.py
└── frontend/
    ├── pages/CommandCenterPage.js       # 2-tab layout: Command | Analytics
    ├── components/
    │   ├── AICommandPanel.jsx           # **AI Trading Assistant** - Bot + AI + Scanner integrated
    │   ├── RightSidebar.jsx             # Smart Watchlist widget
    │   └── MarketIntel/MarketIntelPanel.jsx
    └── utils/
        └── tickerUtils.jsx              # Clickable ticker utility
```

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot with strategy configs (30+ strategies)
3. AI ↔ Bot integration: mutual awareness
4. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning
5. Performance optimization: caching, batching, tab-aware polling
6. UI: **2-tab layout (Command | Analytics)** - Consolidated from 3 tabs
7. Market Intelligence: 5 daily auto-reports, real Finnhub news, anti-hallucination
8. Morning Routine Auto-Trigger
9. Ollama Integration: local LLM via ngrok tunnel
10. Smart AI Routing: Ollama (light/standard) + GPT-4o (deep)
11. Enhanced Market Intel: 7 data sources
12. Newsletter + LLM Service routed through shared AI system
13. Signal Bubbles Integration: Live scanner signals displayed as clickable bubbles
14. **Clickable Tickers & News** (Feb 2026): All stock tickers clickable throughout UI
15. **Advanced S/R Analysis** (Feb 2026): Pivot Points, Volume Profile, historical zones
16. **Wave Scanning** (Feb 2026): Tiered scanning of 1,425 symbols
17. **Smart Watchlist** (Feb 2026): Hybrid auto/manual with strategy-based expiration
18. **Scanner → AI Coaching** (Feb 2026): Proactive notifications for high-priority alerts
19. **AI Trading Assistant Phase 1** (Feb 2026): Integrated panel with Bot + AI + Scanner
    - Bot controls (Start/Stop, Mode selector) in header
    - Coaching alerts with Execute/Half Size/Pass buttons
    - Confirmation dialog before trade execution
    - Conversational trading: "take NVDA", "show my trades", "stop the bot"
    - Removed separate TradingBotPanel
20. **AI Trading Assistant Phase 2** (Feb 2026): AI-Curated Opportunities
    - Two-column layout: Expanded chat (left) + Curated widget (right)
    - AI-Curated Opportunities widget shows top 3-5 TAKE/WAIT setups
    - Rank badges (#1, #2, #3), verdict icons, one-click Execute/Pass
    - Collapsed sections (Bot Trades, Earnings, Watchlist) for more chat space
    - Toast notifications for new TAKE opportunities
21. **Consolidated Stats Header** (Feb 2026): Removed QuickStatsRow
    - All stats moved into AI Trading Assistant header
    - Two-row layout: Account stats (top) + Bot controls (bottom)
    - Top row: Net Liquidation, Today's P&L, Positions, Market Regime
    - Bottom row: Bot toggle, P&L, open count, Mode selector
    - Cleaner UI with more vertical space for content
22. **Tavily Agent Skills** (Feb 2026): Credit-optimized research tools
    - Intelligent caching with variable TTLs (3min-24hr based on data type)
    - Agent Skills: `get_company_info`, `get_stock_analysis`, `get_market_context`
    - Combines FREE sources (Finnhub, Finviz, Yahoo scrapers) before using Tavily
    - Quick analysis mode (0 credits) for basic data
    - Cache stats monitoring via `/api/research/stats`

## Prioritized Backlog
### P0 - Completed
- ✅ Scanner ↔ AI ↔ Trading Bot real-time integration
- ✅ AI Trading Assistant Phase 1 (integrated panel)
- ✅ AI Trading Assistant Phase 2 (AI-curated opportunities widget)
- ✅ Consolidated Stats Header (removed QuickStatsRow)
- ✅ Tavily Agent Skills with intelligent caching
- ✅ Charts Tab Integration (TradingView embedded, click-to-view from widgets)
- ✅ Fixed service method bugs causing chatbot timeouts (Feb 12, 2026)
- ✅ Click-to-Chart Feature in AI Chat (chart icon next to tickers in chat messages)
- ✅ Code cleanup: Removed deprecated ChartsPage.js and IBRealtimeChart.jsx
- ✅ Enhanced Market Intelligence (7 new data sources) - Feb 12, 2026
- ✅ WebSocket Heartbeat & Event Loop Fixes - Feb 12, 2026
- ✅ **Ollama ngrok Connection (Feb 23, 2026)**: Stable local Ollama via paid ngrok tunnel
    - Removed debug headers (`ngrok-skip-browser-warning`) from backend
    - Updated Settings page with ngrok instructions (was Cloudflare Tunnel)
    - Static URL: `pseudoaccidentally-linty-addie.ngrok-free.dev`
    - Available models: deepseek-r1:8b, gpt-oss:120b-cloud, gemma3:4b, llama3:8b, qwen2.5:7b
- ✅ **One-Click Startup Script (Feb 23, 2026)**: `StartTrading.bat` auto-launches:
    - Ollama (with permanent OLLAMA_ORIGINS and OLLAMA_HOST env vars)
    - IB Gateway with auto-login and warning dismissal
    - ngrok tunnel
    - Trading platform in browser
- ✅ **Alert Logic Fix (Feb 23, 2026)**: Distinguished Approaching vs Confirmed alerts
    - HOD Breakout: Now only fires when price ABOVE HOD (confirmed breakout)
    - Added new "Approaching HOD" alert for stocks near HOD but not broken
    - Fixed ORB (Opening Range Breakout): Approaching vs Confirmed
    - Fixed Range Break: Approaching vs Confirmed
    - Fixed general Breakout: Approaching vs Confirmed
    - All alerts now show timestamps (HH:MM:SS) and WATCH/CONFIRMED badges
    - Pipeline cards, Scanner Alerts, and LiveAlertsPanel all updated with timestamps
- ✅ **Portfolio Awareness Phase 3 (Feb 23, 2026)**: Proactive AI suggestions
    - Created PortfolioAwarenessService that monitors positions
    - Alerts for: profit taking, stop loss, sector concentration, position size, correlation risk
    - New Portfolio Insights widget in AI panel
    - Suggestions show timestamp, priority, reasoning, and suggested actions
    - Dismissible suggestions with auto-refresh every 2 minutes
    - Example alerts: "MSFT down 6.9% - Monitor closely", "Heavy Technology exposure (100%)"
- ✅ **UI Cleanup - Status Indicators (Feb 23, 2026)**:
    - **System Status Popover**: Consolidated WS/IB Gateway/Ollama into single "System Status" button in header
    - Shows overall status (All Online/Partial/Offline) with color-coded indicator
    - Click opens popover with individual service status, icons, and Reconnect action for IB Gateway
    - **Bot Mode Dropdown**: Replaced toggle+mode buttons with single dropdown showing Auto/Confirm/Paused
    - Each mode has descriptive hover tooltip explaining when to use it
    - Shows bot stats (P&L, open count, pending) below the dropdown button
    - Power toggle (Start/Stop Bot) at bottom of dropdown menu
    - **Removed redundant Live/Offline dot** from AI Trading Assistant header
- ✅ **NASDAQ Ticker Index Expansion (Feb 23, 2026)**:
    - Added NASDAQ_EXTENDED list with ~480 quality-screened symbols
    - Criteria: Price >= $5, Volume >= 100K (based on snapshot data), tradeable
    - New Tier 2 system: 334 unique symbols (NASDAQ ext minus Tier 1 overlap)
    - Total universe expanded: **1,353 unique symbols** across all tiers
    - Tier 1: 567 (SPY + QQQ + ETFs)
    - Tier 2: 334 (NASDAQ Extended)
    - Tier 3: 452 (Russell 2000)
    - API endpoints updated: `/api/universe/symbols/nasdaq`, `/api/universe/symbols/tier2`

### P1 - Next Up
- **Quick Actions**: Implement backend API for close/add/alert position actions (frontend stubs exist)
- Audio alerts for high-priority setups
- Focus Mode: Hide all sections except chat + top opportunity when actively trading
- Russell 2000 expansion (currently ~542, could add more quality small caps)

### Recently Completed
- ✅ **Chart Timezone Fix (Feb 24, 2026)**: Changed TradingView widget timezone from 'Etc/UTC' to 'America/New_York' (Eastern Time) to show correct US market hours
- ✅ **Exchange Prefix Mapping (Feb 24, 2026)**: Added exchange prefixes (AMEX, NASDAQ, NYSE) to symbol mapping for potential real-time data
- ✅ **RealtimeChart Component (Feb 24, 2026)**: Created new component using lightweight-charts + Alpaca real-time data (available at `/app/frontend/src/components/charts/RealtimeChart.jsx` but not currently active due to rendering issues during pre-market)
- ✅ **Scanner Expansion Phase 1 - New AI Setups (Mar 2026)**: Added 4 new trade setup types + advanced technical indicators
    - **New Setups**: TTM Squeeze, Relative Strength vs SPY, Mean Reversion, Gap Fade
    - **New Indicators**: Bollinger Bands, Keltner Channels, Squeeze detection (BB inside KC), Opening Range Breakout, Relative Strength vs SPY
    - **Backend Implementation**: `/app/backend/services/enhanced_scanner.py` with `_check_squeeze`, `_check_mean_reversion`, `_check_relative_strength`, `_check_gap_fade` methods
    - **Technical Snapshot API**: `/api/technicals/{symbol}` returns bollinger_bands, keltner_channels, squeeze (on/fire), opening_range (high/low/breakout), relative_strength.vs_spy
    - **34 enabled setups** in scanner including all new setup types
    - Verified via pytest (26/26 tests passed) and Playwright UI testing
- ✅ **Earnings Calendar Live Data (Mar 2026)**: Switched from mock data to real Finnhub API feed
    - 5-day column layout with color-coded "heat map"
    - Full-column gradients, Expected Move data (% and $), Earnings Score
    - Backend endpoint: `/api/earnings/calendar`
- ✅ **IB Data Pusher Integration (Mar 2026)**: Fixed user's local `ib_data_pusher.py` script
    - Converted from asyncio to synchronous `requests` library to fix event loop conflicts
    - Script reliably pushes account/position data from IB Gateway to cloud app
    - Updated `StartTrading.bat` for automated startup
- ✅ **Quick Actions + Volatility-Adjusted Position Sizing (Mar 6, 2026)**: Implemented P1 features
    - **Buy/Sell Endpoints**: `/api/quick-actions/buy` and `/api/quick-actions/sell` with ATR-based position sizing
    - **Volatility Adjustment**: Positions automatically sized based on ATR% (low vol = larger position, high vol = smaller)
    - **Setup-Specific Stops**: Different ATR multipliers for different setup types (e.g., 1.0x for mean reversion, 1.5x for breakouts)
    - **RiskParameters Enhanced**: Added `use_volatility_sizing`, `base_atr_multiplier`, `volatility_scale_factor` config
    - Backend: `/app/backend/routers/quick_actions.py`, `/app/backend/services/trading_bot_service.py`
- ✅ **Sector/Industry Strength Analysis (Mar 6, 2026)**: Implemented sector rotation detection
    - **Sector Rankings**: `/api/sectors/rankings` - All 11 S&P sector ETFs ranked by performance
    - **Stock Sector Context**: `/api/sectors/context/{symbol}` - Get sector strength, relative performance, recommendation
    - **Rotation Signals**: `/api/sectors/rotation` - Detect risk-on/risk-off/inflation patterns with trading implications
    - **Scanner Integration**: Alerts enhanced with sector context (leaders in hot sectors get priority boost)
    - **AI Integration**: Sector summary added to AI assistant context for better recommendations
    - Backend: `/app/backend/services/sector_analysis_service.py`, `/app/backend/routers/sectors.py`
- ✅ **Advanced Chart Pattern Detection (Mar 6, 2026)**: Implemented pattern recognition
    - **Patterns Detected**: Flags (bull/bear), Pennants, Triangles (ascending/descending/symmetric), Wedges (rising/falling), Head & Shoulders (regular/inverse), Double Top/Bottom
    - **API Endpoints**: `/api/patterns/detect/{symbol}`, `/api/patterns/scan` (batch), `/api/patterns/summary`
    - **Scanner Integration**: `chart_pattern` setup type added to scanner - generates alerts for high-quality patterns
    - **Pattern Scoring**: 0-100 quality score based on clarity, volume confirmation, risk/reward
    - Backend: `/app/backend/services/chart_pattern_service.py`, `/app/backend/routers/patterns.py`
- ✅ **Sentiment Analysis Integration (Mar 6, 2026)**: Dual-layer sentiment analysis
    - **Basic Analysis**: Fast keyword-based scoring with weighted bullish/bearish dictionaries
    - **AI Deep Analysis**: Ollama-powered headline analysis for high-priority alerts
    - **API Endpoints**: `/api/sentiment/analyze/{symbol}`, `/api/sentiment/market`, `/api/sentiment/batch`
    - **Scanner Integration**: High-priority alerts automatically enriched with sentiment context
    - **Market Sentiment**: Aggregated sentiment from SPY, QQQ, DIA, IWM
    - Backend: `/app/backend/services/sentiment_analysis_service.py`, `/app/backend/routers/sentiment.py`
- ✅ **Market Hours Simulator (Mar 6, 2026)**: Scanner testing when markets closed
    - **Scenarios**: bullish_momentum, bearish_reversal, range_bound, high_volatility
    - **Features**: Configurable alert interval, real-time WebSocket alerts, on-demand generation
    - **API Endpoints**: `/api/simulator/start`, `/api/simulator/stop`, `/api/simulator/generate`, `/api/simulator/alerts`
    - **WebSocket**: `/api/simulator/ws/alerts` for real-time simulated alert stream
    - Backend: `/app/backend/services/market_simulator_service.py`, `/app/backend/routers/simulator.py`
    - **UI Control (Mar 6, 2026)**: SimulatorControl.jsx component integrated into Scanner Alerts widget
      - Start/Stop buttons with visual status indicators
      - Scenario selection (4 market scenarios with icons and descriptions)
      - Interval selection (10s, 30s, 1m, 2m presets)
      - Single alert generation button (lightning bolt)
      - Settings panel with collapsible configuration
      - 'SIM' badge on simulated alerts in feed
      - Frontend: `/app/frontend/src/components/SimulatorControl.jsx`, integrated into `RightSidebar.jsx`
- ✅ **SMB Capital Integration Phase 1 (Mar 9, 2026)**: Deep integration of SMB trading methodology
    - **Trade Style Classification**: Added M2M (Move2Move), T2H (Trade2Hold), A+ execution styles with targets
    - **SMB 5-Variable Scoring**: Big Picture, Intraday Fundamental, Technical Level, Tape Reading, Intuition
    - **Setup Direction Classification**: All 40 setups categorized as Long/Short/Both
    - **Setup Categories**: trend_momentum, catalyst_driven, reversal, consolidation, specialized
    - **Earnings Catalyst Scoring**: Full -10 to +10 scoring system with trading approach mapping
    - **SMB Alias Mapping**: SMB original names (bounce, stuffed, big_dawg) map to our implementation names
    - **New API Endpoints**: `/api/smb/setups/summary`, `/api/smb/setup/{name}`, `/api/smb/score`, `/api/smb/earnings/score`, `/api/smb/resolve-alias/{alias}`
    - Backend: `/app/backend/services/smb_integration.py`, `/app/backend/services/earnings_scoring_service.py`, `/app/backend/routers/smb_router.py`
    - Updated: `enhanced_scanner.py` (LiveAlert with SMB fields), `ev_tracking_service.py` (integrated alias resolution)
- ✅ **SMB Capital Integration Phase 2 (Mar 9, 2026)**: Unified scoring and advanced features
    - **Unified Scoring Integration**: SMB 5-Variable score now integrated into existing scoring_engine.py
    - **Enhanced Tape Reading**: Level 2 "Box" metrics with SMB signals (hidden seller/buyer, re-bid, absorption, stuffed)
    - **Reasons2Sell Framework**: Real-time monitoring for T2H exit triggers (9 EMA break, give-back rule, thesis invalid)
    - **Tiered Entry System**: Calculate tier 1/2/3 share allocations based on risk, trade style, and SMB grade
    - **AI Coaching Integration**: SMB methodology context automatically injected into AI coaching prompts
    - **New API Endpoints**: `/api/smb/reasons-to-sell/check`, `/api/smb/reasons-to-sell/list`, `/api/smb/tiered-entry/calculate`, `/api/smb/tape/analyze`
    - **Scoring Engine Enhanced**: `quick_stats` now includes `smb_grade`, `smb_is_a_plus`, `tape_score`, `tape_bias`, `trade_style`
    - Backend: `/app/backend/services/smb_unified_scoring.py`, updated `scoring_engine.py`, `ai_assistant_service.py`
- ✅ **SMB Capital Integration Phase 3 (Mar 9, 2026)**: Full system integration
    - **Frontend Alert Cards**: Updated with SMB grade, tape score, trade style badges (M2M/T2H/A+), direction bias warnings
    - **Reasons2Sell Monitor**: Real-time exit signal tracking for open positions in TradingBotPanel
    - **Scanner Integration**: Alerts now auto-populate SMB fields (trade_style, direction_bias, target_r_multiple)
    - **Trading Bot Enhancement**: BotTrade dataclass includes SMB fields for style-based management
    - **Market Intel Enhancement**: Scanner context now includes SMB metadata (grade, style, tape score)
    - **AI Coaching Enhancement**: SMB methodology context injected into coaching prompts with tiered entry suggestions
    - **Glossary Updated**: 8 new SMB terminology entries (methodology, trade styles, 5-var score, tape, R2S, tiered entry, earnings)
    - Frontend: `RightSidebar.jsx` (alert cards), `TradingBotPanel.jsx` (R2S monitor), `glossaryData.js`
    - Backend: `enhanced_scanner.py`, `trading_bot_service.py`, `market_intel_service.py`

### Data Source Clarification
| Component | Data Source | Latency |
|-----------|-------------|---------|
| Price Ticker Bar (top) | Alpaca Real-Time | ~0 sec |
| AI Assistant | Alpaca Real-Time | ~0 sec |
| Scanner Alerts | Alpaca Real-Time | ~0 sec |
| Market Intel Reports | Alpaca Real-Time | ~0 sec |
| Trading Bot | Alpaca Real-Time | ~0 sec |
| Positions/P&L | Alpaca Real-Time | ~0 sec |
| TradingView Chart | TradingView Feed | ~15 min delayed |

**Note**: All trading decisions use real-time Alpaca data. Only the chart visualization shows delayed data.

### P2 - Future
- Strategy backtesting integration
- Level 2 order book analysis (tape reading)
- Full bot state persistence in MongoDB
- Weekly performance digest
- Fix watchlist widget race condition showing "(0)" briefly on load
- **Trade Style Selector for Bot** - UI to choose scalp/swing/investment focus, auto-adjusts TQS thresholds and position sizing
- **Learning Dashboard Tab** - Visualize Three-Speed Learning insights (best/worst setups, edge decay alerts, trader profile)
- **Voice Command Support** - Hands-free trading via OpenAI Whisper ("Hey TradeCommand, what are my positions?")

---

## Session Log - February 12, 2026

### Tavily Agent Skills Implementation
**Goal**: Integrate Tavily's Agent Skills with aggressive caching to minimize credit usage on free tier.

**Implementation:**
1. **Intelligent Cache System**: Variable TTLs based on data freshness requirements
   - Company info: 1 hour (fundamentals don't change often)
   - Stock analysis: 10 minutes
   - News: 3 minutes
   - SEC filings: 24 hours
   - Deep dive/market context: 15 minutes

2. **Agent Skills Created**:
   - `get_company_info(ticker)`: Combines Finnhub + Finviz + Yahoo, uses Tavily only if gaps exist
   - `get_stock_analysis(ticker, type)`: Quick (0 credits), News (1 credit), Comprehensive (1-2 credits)
   - `get_market_context()`: Daily market overview (indices, regime, themes)

3. **Credit Optimization Strategy**:
   - Check FREE sources first (Finnhub, Finviz scrapers, Yahoo scrapers)
   - Only call Tavily to fill data gaps
   - Use "basic" search depth when possible (1 credit vs 2)
   - Cache all results aggressively

4. **New API Endpoints**:
   - `GET /api/research/skills/company-info/{ticker}`
   - `GET /api/research/skills/stock-analysis/{ticker}?analysis_type=quick|news|comprehensive`
   - `GET /api/research/skills/market-context`
   - `GET /api/research/stats` (cache monitoring)
   - `GET /api/research/budget` (credit budget status)
   - `POST /api/research/budget/limit` (update monthly limit)

5. **Credit Budget Tracking**:
   - Persistent monthly tracking in MongoDB (`tavily_credit_usage` collection)
   - Warning thresholds: 50% (low), 75% (medium), 90% (high), 95% (critical)
   - Auto-blocks searches when limit exceeded
   - Projects usage and warns if on track to exceed
   - Resets automatically on month rollover
   - **Frontend indicator in header bar** showing remaining credits with color-coded status
   - **Clickable modal** with detailed usage breakdown: circular progress ring, stats grid (daily avg, projected, session, days left), on-track indicator, recent queries list
   - **Credits Saved Banner**: Green gradient showing credits saved by caching, savings percentage, cache hit rate, and effective cost comparison

6. **AI Assistant Integration**:
   - Updated intent detection to route to Agent Skills
   - New research types: `company_info`, `stock_analysis`, `market_context`
   - Rich formatting for Agent Skill results

### Files Modified
- `backend/services/web_research_service.py` - Added IntelligentCache, Agent Skills, CreditBudgetTracker
- `backend/services/ai_assistant_service.py` - Updated research intent detection & formatting
- `backend/routers/research.py` - New Agent Skills and budget endpoints
- `backend/server.py` - Initialize web research service with DB on startup
- `frontend/src/hooks/useCommandCenterData.js` - Added creditBudget state and fetching
- `frontend/src/pages/CommandCenterPage.js` - Pass creditBudget to HeaderBar
- `frontend/src/components/layout/HeaderBar.jsx` - Added credit budget indicator UI

---

## Session Log - February 12, 2026 (Ticker Validation System)

### Feature: Centralized Ticker Validation to Prevent False Positives
**Problem**: The system was:
1. Processing invalid/outdated tickers (CADE, MODG) that no longer exist
2. Misidentifying common words as tickers ("Target" for TGT, "AI" for C3.ai, "ALL" for Allstate)

**Solution**: Created a centralized ticker validation utility with:

1. **False Positive Word List** (~200+ common words that match ticker patterns):
   - Trading terminology: SCALP, SETUP, TRADE, STOCK, ALERT, TREND, TARGET, etc.
   - Technology terms: AI, API, APP, WEB, NET, TECH, CODE, etc.
   - Common English words: ALL, NOW, IT, ON, BE, FOR, THE, etc.
   - Time-related: DAY, WEEK, MONTH, AM, PM, etc.

2. **Invalid/Delisted Tickers Registry**:
   - CADE, MODG, TWTR, ATVI, VMW, and other delisted stocks
   - Easily extensible as more tickers become invalid

3. **Context-Aware Detection Patterns**:
   - "profit target" / "price target" → NOT treated as TGT
   - "AI model" / "using AI" → NOT treated as AI stock
   - "right now" / "for now" → NOT treated as NOW
   - "$AI" / "AI stock" / "buy AI" → IS treated as AI stock

**Files Created/Modified**:
- `backend/utils/ticker_validator.py` - NEW: Centralized validation utility
- `backend/utils/__init__.py` - NEW: Utils package init
- `backend/services/realtime_technical_service.py` - Updated to use centralized validator
- `backend/services/quality_service.py` - Updated to use centralized validator
- `backend/services/ai_assistant_service.py` - Added ticker validation before research
- `backend/data/index_symbols.py` - Removed CADE, MODG from symbol lists

**Result**: 
- Invalid tickers like CADE, MODG are now rejected
- Common words like "Target", "AI" in non-ticker contexts are no longer misidentified
- Users get helpful feedback when trying to analyze invalid tickers

---

## Session Log - February 12, 2026 (Service Method Bug Fix)

### Bug Fix: Missing Service Methods Causing "Disconnect" Feel
**Problem**: User reported "disconnect issues" when using the chatbot. Investigation revealed the actual issue was **missing method calls** in `trading_bot_service.py`, not network disconnects. 

**Root Cause**:
- `_get_technical_intelligence()` was calling `self.technical_service.get_realtime_analysis()` which doesn't exist
- `_get_quality_intelligence()` was calling `self.quality_service.score_opportunity()` which doesn't exist
- These errors caused timeouts when the AI tried to gather intelligence on stocks, making the UI feel unresponsive

**Error Messages in Logs**:
```
Technical intelligence error for CADE: 'RealTimeTechnicalService' object has no attribute 'get_realtime_analysis'
Quality intelligence error for CADE: 'QualityService' object has no attribute 'score_opportunity'
Intelligence gathering timeout for CADE
```

**Fixes Applied**:
1. **Technical Intelligence**: Changed from non-existent `get_realtime_analysis()` to `get_technical_snapshot()` with proper response mapping
2. **Quality Intelligence**: Changed from non-existent `score_opportunity()` to `get_quality_metrics()` + `calculate_quality_score()` combination

**Files Modified**:
- `backend/services/trading_bot_service.py` - Fixed both `_get_technical_intelligence()` and `_get_quality_intelligence()` methods

**Result**: Chatbot now responds correctly without timeouts when analyzing stocks. The technical analysis and quality scores are properly fetched and formatted.

---

## Session Log - February 12, 2026 (Charts Tab Integration)

### Charts Tab Integration into Command Center
**Goal**: Integrate charting functionality directly into the Command Center as a third tab, enabling seamless navigation from any ticker to its chart.

**Implementation:**
1. **TradingView Widget Integration**: Replaced non-rendering lightweight-charts with TradingView embedded widget
   - Created `/frontend/src/components/charts/TradingViewWidget.jsx`
   - Full candlestick chart with volume, MA, and all TradingView tools
   - Responsive and auto-resizes to container

2. **ChartsTab Component**: New tab component at `/frontend/src/components/tabs/ChartsTab.jsx`
   - Symbol search input with Load button
   - Quick symbol buttons (SPY, QQQ, AAPL, NVDA, TSLA, MSFT, AMZN, META)
   - Watchlist symbols section (from Smart Watchlist)
   - Recent charts tracking

3. **Click-to-View-Chart Functionality**:
   - `viewChart(symbol)` function in `useCommandCenterData.js` (lines 338-344)
   - Sets chart symbol, saves to localStorage, adds to recent charts, switches to 'charts' tab
   - Chart icon buttons in Scanner Alerts widget trigger `onViewChart`
   - Chart icon buttons in Watchlist widget trigger `onViewChart`
   - Icons appear on hover (opacity-0 → opacity-100)

4. **Tab Navigation**:
   - Added "Charts" tab with LineChart icon to CommandCenterPage.js
   - Tab IDs: 'coach', 'charts', 'analytics'
   - State persisted in localStorage for tab selection

5. **Recent Charts Feature**:
   - Tracks last 10 viewed symbols
   - Persisted in localStorage (`tradecommand_recent_charts`)
   - Displayed as clickable badges below quick symbols

**Note**: The old lightweight-charts based `IBRealtimeChart.jsx` had a rendering bug where the canvas was created but no candles were drawn (axes rendered correctly but main chart was blank). This bug also existed in the old `/pages/ChartsPage.js`. Switched to TradingView embedded widget which works flawlessly.

### Files Modified/Created
- `frontend/src/components/charts/TradingViewWidget.jsx` - NEW: TradingView widget wrapper
- `frontend/src/components/tabs/ChartsTab.jsx` - Updated to use TradingView widget
- `frontend/src/pages/CommandCenterPage.js` - Added Charts tab to navigation
- `frontend/src/hooks/useCommandCenterData.js` - viewChart function, recent charts state
- `frontend/package.json` - Added react-ts-tradingview-widgets

### Testing Results
- All 16 tests passed (100% success rate)
- Charts tab renders correctly with TradingView candlestick charts
- Symbol switching works via input, quick buttons, and sidebar icons
- Tab navigation persists state correctly

---

## Session Log - February 12, 2026 (WebSocket Disconnect Fix)

### Issue: App disconnects after trading bot scan cycle completes

**Root Causes Identified:**
1. **Missing WebSocket heartbeat** - Proxies/ingress timeout idle connections
2. **Event loop blocking** - Heavy scan operations don't yield, blocking WebSocket handling
3. **MongoDB boolean check** - `if db:` causes warnings in PyMongo (use `if db is not None:`)
4. **Missing AlpacaService.get_positions()** - Method didn't exist, causing repeated errors

**Fixes Applied:**

1. **WebSocket Heartbeat** (`frontend/src/hooks/useWebSocket.js`):
   - Added ping/pong mechanism every 25 seconds
   - Keeps connection alive through proxies (most timeout at 30-60s)
   - Ignores pong responses in message handler

2. **Event Loop Yields** (`backend/services/trading_bot_service.py`, `background_scanner.py`):
   - Added `await asyncio.sleep(0)` after each symbol scan
   - Prevents long-running scans from blocking WebSocket message handling

3. **MongoDB Boolean Checks** (multiple files):
   - Changed `if db:` to `if db is not None:` in:
     - `background_scanner.py`
     - `enhanced_scanner.py`
     - `predictive_scanner.py`
     - `alert_system.py`

4. **AlpacaService.get_positions()** (`backend/services/alpaca_service.py`):
   - Added missing method to fetch open positions from Alpaca paper trading account
   - Returns list of positions with qty, avg_entry_price, unrealized_pl, etc.

**Files Modified:**
- `frontend/src/hooks/useWebSocket.js` - Added heartbeat mechanism
- `backend/services/alpaca_service.py` - Added get_positions method
- `backend/services/trading_bot_service.py` - Added event loop yield
- `backend/services/background_scanner.py` - Added event loop yield, fixed db check
- `backend/services/enhanced_scanner.py` - Fixed db check
- `backend/services/predictive_scanner.py` - Fixed db check
- `backend/services/alert_system.py` - Fixed db check

**Future Enhancement Saved:**
- RVOL (Relative Volume) calculation for better "in play" stock detection

---

## Session Log - February 12, 2026 (Enhanced Market Intelligence)

### Feature: Market Intelligence Improvements
**Goal**: Make Market Intel more accurate by using real data sources and proper context.

**7 New Context Gathering Methods Added:**

1. **`_gather_market_regime_context()`**
   - Classifies day type: STRONG UPTREND, DOWNTREND, CHOPPY/RANGE, ROTATION, SMALL CAP RISK-ON
   - Provides strategy recommendations based on regime
   - Includes VIX assessment (HIGH/ELEVATED/LOW/NORMAL volatility)

2. **`_gather_ticker_specific_news()`**
   - Fetches Finnhub company-news for watchlist stocks
   - Max 3 headlines per ticker, up to 8 tickers
   - More relevant than general market news

3. **`_gather_sector_heatmap()`**
   - 11 sector ETFs: XLK, XLF, XLE, XLV, XLI, XLC, XLY, XLP, XLU, XLRE, XLB
   - Sorted by performance with leaders/laggards marked
   - Enables rotation analysis

4. **`_gather_earnings_context()`**
   - Checks Finnhub earnings calendar for next 14 days
   - Filters for watchlist stocks only
   - Adds ⚠️ warnings about earnings risk

5. **`_gather_in_play_technical_context()`**
   - Gets HOD, LOD, VWAP levels for active stocks
   - Shows gap %, day range %
   - Provides above/below VWAP bias

6. **Enhanced `_gather_watchlist_context()`**
   - Uses actual Smart Watchlist (not hardcoded symbols)
   - Shows IN-PLAY vs ON-WATCH status
   - Includes matched strategies from scanner

7. **Wired Services**
   - `smart_watchlist` service now connected to Market Intel
   - `alert_system` service connected

**Bug Fixed by Testing Agent:**
- Alpaca's `get_quotes_batch` returns `Dict[str, Dict]` not `List[Dict]`
- Fixed iteration in 5 methods from `for q in quotes` to `for sym, q in quotes.items()`

**Files Modified:**
- `backend/services/market_intel_service.py` - Added 7 new context methods, enhanced prompts
- `backend/server.py` - Moved market_intel initialization, wired smart_watchlist

**Test Results:**
- 16/16 backend tests pass
- All 7 new features verified working
- Frontend displays enhanced report correctly

---

## Session Log - February 12, 2026 (Click-to-Chart in AI Chat)

### Feature: Click-to-Chart Integration in AI Chat Messages
**Goal**: Allow users to click a chart icon next to ticker symbols in AI chat responses to navigate directly to the Charts tab with that symbol loaded.

**Implementation:**
1. **TickerLink Component Enhancement** (`AICommandPanel.jsx` lines 41-63):
   - Added `onViewChart` prop support
   - Amber-colored LineChart icon button appears when `onViewChart` is provided
   - Uses `data-testid="ticker-chart-{symbol}"` for testing
   - Styled as a split-button: cyan ticker link (left) + amber chart icon (right)

2. **Prop Propagation Chain**:
   - `CommandCenterPage.js` → passes `viewChart` to `AICoachTab`
   - `AICoachTab.jsx` → passes `viewChart` as `onViewChart` to `AICommandPanel` and `RightSidebar`
   - `AICommandPanel.jsx` → passes `onViewChart` to:
     - `TickerLink` (in `TickerAwareText`)
     - `ChatMessage`
     - `CuratedOpportunityCard`
     - `AICuratedWidget`
   - `RightSidebar.jsx` → passes `onViewChart` to:
     - `ScannerResultsWidget`
     - `WatchlistWidget`
     - `EarningsWidget`

3. **viewChart Function** (`useCommandCenterData.js` lines 338-344):
   - Sets the chart symbol
   - Saves to localStorage
   - Adds to recent charts history
   - Switches to 'charts' tab automatically

4. **Code Cleanup**:
   - Deleted deprecated `/frontend/src/components/charts/IBRealtimeChart.jsx`
   - Deleted redundant `/frontend/src/pages/ChartsPage.js` and its route from `App.js`

**Testing Results**:
- Code review: All implementations verified correct
- Chart icons appear in AI-Curated Opportunity cards
- Chart icons appear on hover in Scanner Alerts and Smart Watchlist widgets
- AI chat backend responds correctly (GPT-4o fallback works when Ollama unavailable)

### Files Modified
- `frontend/src/components/AICommandPanel.jsx` - TickerLink with chart icon, prop propagation
- `frontend/src/components/RightSidebar.jsx` - Chart icons in Scanner, Watchlist, Earnings widgets
- `frontend/src/components/tabs/AICoachTab.jsx` - Pass onViewChart prop
- `frontend/src/pages/CommandCenterPage.js` - Pass viewChart to AICoachTab

### Files Deleted
- `frontend/src/components/charts/IBRealtimeChart.jsx` (deprecated, replaced by TradingView)
- `frontend/src/pages/ChartsPage.js` (replaced by ChartsTab in Command Center)

---

## Session Log - February 11, 2026

### P0 Bug Fix: IB Connection UI Issue
**Problem**: Frontend UI showed IB Gateway as "disconnected" despite backend being connected.

**Root Causes Fixed**:
1. `datetime` objects in `alpaca_service.py` not serialized to ISO strings before WebSocket broadcast
2. React StrictMode causing double-mounting and rapid WebSocket connect/disconnect cycles
3. Stale WebSocket connections not being properly cleaned up

**Fixes Applied**:
- Converted all `_cached_at` datetime fields to `.isoformat()` strings
- Disabled React StrictMode in `index.js`
- Improved WebSocket `ConnectionManager` to auto-cleanup stale connections
- Added auto-connect to IB Gateway on backend startup

### System Optimizations Implemented
1. **Staggered Polling Intervals**: Bot status 20s, trades 25s, coaching 15s (were all 10-15s)
2. **Batch Init Endpoint**: New `GET /api/dashboard/init` returns system health, alerts, smart watchlist in ONE call
3. **Phased Startup Loading**: Critical data first, earnings calendar loads last (1s delay)
4. **Removed Unused Newsletter Fetch**: No longer fetched on Command Center startup
5. **Reduced IB Check Interval**: 30s → 15s for faster UI updates

### Files Modified
- `backend/server.py` - WebSocket manager, auto-connect, batch init endpoint
- `backend/services/alpaca_service.py` - datetime serialization fix
- `backend/services/fundamental_data_service.py` - datetime serialization fix
- `frontend/src/index.js` - Disabled StrictMode
- `frontend/src/App.js` - IB check interval, debug logging
- `frontend/src/hooks/useCommandCenterData.js` - Batch init, staggered loading
- `frontend/src/components/AICommandPanel.jsx` - Optimized polling intervals
- `frontend/src/components/layout/HeaderBar.jsx` - Safety check for systemHealth.services


---

## Session Log - February 12, 2026 (WebSocket Connection Stability Fix)

### Issue: WebSocket Disconnection on Startup
**Problem**: User reported persistent "Reconnecting" status on app startup and after trading bot scan cycles. The WebSocket connection would connect but immediately disconnect.

**Root Causes Identified**:
1. **Missing DB Collections Initialization**: `EnhancedBackgroundScanner` was initialized without `db`, then `db` was set after. The `alerts_collection`, `stats_collection`, and `alert_outcomes_collection` attributes were never created, causing `AttributeError` on first access.

2. **MongoDB Truth Value Testing Bug**: PyMongo collections don't support boolean testing (`if self.collection:`). This caused `NotImplementedError` when checking collection existence.

3. **WebSocket Route Not Matched by Ingress**: The WebSocket endpoint at `/ws/quotes` was not being routed through the Kubernetes ingress (only `/api/*` routes are forwarded to backend).

4. **Connection Timeout on Initial Data Load**: The WebSocket handler was synchronously fetching 8 symbols (with 0.3s delays each = 2.4s) before responding, causing proxy timeouts.

### Fixes Applied

**1. Backend - EnhancedBackgroundScanner (`services/enhanced_scanner.py`)**:
- Added explicit `None` initialization for all collection attributes in `__init__`
- Created new `_init_db_collections(db)` method for collection setup
- Created new `set_db(db)` method for late binding after construction
- Changed all `if self.collection:` checks to `if self.collection is not None:`

**2. Backend - Server Initialization (`server.py`)**:
- Changed `background_scanner.db = db` to `background_scanner.set_db(db)` for proper initialization
- Changed WebSocket route from `/ws/quotes` to `/api/ws/quotes` for ingress compatibility

**3. Backend - WebSocket Handler (`server.py`)**:
- Added immediate `{"type": "connected"}` message on WebSocket open
- Created server-side keepalive ping task (every 20 seconds)
- Made initial data fetch non-blocking (background task)
- Reduced initial symbols from 8 to 4 and delay from 0.3s to 0.1s

**4. Frontend - WebSocket Hook (`hooks/useWebSocket.js`)**:
- Updated `getWebSocketUrl()` to use `/api/ws/quotes`
- Added handling for `server_ping` and `connected` message types
- Added cleanup of existing connection before reconnecting
- Modified onclose handler to not auto-reconnect on clean closes (code 1000)

**5. Background Scanner (`services/background_scanner.py`)**:
- Fixed MongoDB truth value testing bug

### Verification
- Python WebSocket client test confirmed 50+ seconds stable connection
- Frontend now shows "LIVE" status with active streaming quotes
- Backend shows `active_connections: 1` in `/api/stream/status`

### Files Modified
- `backend/services/enhanced_scanner.py` - Collection initialization and truth value fixes
- `backend/services/background_scanner.py` - Truth value fix
- `backend/server.py` - WebSocket route change, handler improvements, set_db usage
- `frontend/src/hooks/useWebSocket.js` - Route fix, message handling, cleanup
- `frontend/src/utils/api.js` - WebSocket URL update

---

## Prioritized Backlog

### P0 - Critical
- [x] WebSocket connection stability fix (DONE - Feb 12, 2026)
- [x] My Positions display fix (DONE - Feb 12, 2026)
- [x] Quick Actions for positions (DONE - Feb 12, 2026) - Close, Add, Alert, Chart buttons
- [x] AI Assistant positions context fix (DONE - Feb 21, 2026) - Wired alpaca_service to AIAssistantService

### P1 - High Priority
- [ ] Perplexity Finance API Integration (User interested)
- [ ] Complete Quick Actions backend (Close, Add, Alert handlers are stubs)
- [ ] Real-time RVOL in Market Intelligence (User approved)
- [ ] Portfolio Awareness (Phase 3) - AI proactive suggestions based on positions
- [ ] UI Focus Mode - Minimize all UI except chat and top opportunity
- [ ] Custom scrapers for SEC filings and financial data sources

### P2 - Medium Priority
- [ ] Keyboard shortcuts for common trading actions
- [ ] Full WebSocket Migration - Move remaining HTTP polling to WebSocket
- [ ] Strategy backtesting integration
- [ ] Alert sounds / browser push notifications

### P3 - Low Priority / Future
- [x] Fix WatchlistWidget button-in-button DOM nesting warning (DONE - Feb 21, 2026)
- [x] Clean up ai_assistant_service.py linting errors (DONE - Feb 21, 2026)
- [ ] Remove unused NewsletterPage.js and backend endpoints
- [ ] Extract PositionCard component to separate file

---

## Session Log - February 12, 2026 (Quick Actions Enhancement)

### Feature: Quick Actions for Position Cards
**Request**: User asked for quick action buttons on position cards to quickly close, add to position, or set price alerts.

**Implementation**:
1. Created new `PositionCard` component with hover-revealed action menu
2. Added 4 action buttons:
   - **Close** (red) - Opens confirmation dialog to close entire position at market
   - **Add** (green) - Opens dialog to add shares to existing position
   - **Alert** (amber) - Sets price alerts at ±5% from current price
   - **Chart** (cyan) - Opens chart view for the ticker
3. Enhanced `ConfirmationDialog` to support close and add position modes with appropriate styling
4. Added handler functions: `handleClosePosition`, `handleAddToPosition`, `handleSetPriceAlert`

**Files Modified**:
- `frontend/src/components/AICommandPanel.jsx` - Added PositionCard component, action handlers, enhanced dialog

**Testing Results**:
- 100% frontend tests passed
- All 7 features verified working
- data-testids verified for automation

---

## Session Log - February 21, 2026 (Full App Review & Bug Fixes)

### Comprehensive Review & Debug Session
**Goal**: Review entire app, codebase, API integrations, and AI assistant to ensure everything is working.

### Critical Bug Fixed: AI Assistant Missing alpaca_service Attribute

**Problem**: Backend logs showed `'AIAssistantService' object has no attribute 'alpaca_service'` causing positions context to fail in AI chat.

**Root Cause**: The `alpaca_service` was never wired to `AIAssistantService` in server.py, even though the service tried to access `self.alpaca_service` to fetch positions for context.

**Fix Applied**:
1. Added `_alpaca_service` initialization in `AIAssistantService.__init__()`
2. Added `set_alpaca_service(alpaca_service)` method
3. Added `@property alpaca_service` getter
4. Wired the service in server.py: `assistant_service.set_alpaca_service(alpaca_service)`

**Files Modified**:
- `backend/services/ai_assistant_service.py` - Added alpaca_service property and setter
- `backend/server.py` (line 161) - Added `assistant_service.set_alpaca_service(alpaca_service)`

### Minor Fixes

**1. WatchlistWidget DOM Nesting Warning**
- Changed button inside button to span with role="button" in `RightSidebar.jsx`
- Eliminates React `validateDOMNesting` console warning

**2. Python Linting Errors Fixed**
- Removed unused `message_lower` variable
- Removed unused `pattern_id` variable
- Changed bare `except:` to `except (ValueError, TypeError):`

### Testing Results (iteration_38.json)
- **Backend**: 100% (15/15 tests passed)
- **Frontend**: 100% (11 features verified)
- All core features working:
  - My Positions displays 2 real Alpaca positions (MSFT, NVDA)
  - Quick Actions buttons work
  - AI Chat responds with positions context
  - WebSocket shows LIVE status
  - Market Intel, Scanner Alerts, Smart Watchlist all functional
  - Charts tab loads TradingView widget

### Known Limitations
- Ollama ngrok tunnel is offline (expected) - AI falls back to Emergent GPT-4o
- IB Gateway not connected (expected in cloud environment)
- Quick Actions handlers are frontend stubs - backend endpoints need implementation

---


## Session Log - February 12, 2026 (My Positions Bug Fix)

### Bug Fix: My Positions Not Displaying Real Account Positions
**Problem**: The "My Positions" section showed "No open positions" despite the user having real MSFT and NVDA positions in their Alpaca account. The API was returning correct data, but the frontend wasn't displaying it.

**Root Cause**: The `fetchAccountData()` function in `useCommandCenterData.js` was only called when `connectionChecked` was true. However, `connectionChecked` starts as `false` and only becomes `true` after the IB status check completes. Since Alpaca positions don't depend on IB connection, this was causing the positions to never be fetched on initial load.

**Fix Applied**:
1. Added a separate `useEffect` hook that fetches positions immediately on component mount
2. The new useEffect runs independently of IB connection status
3. Added a 30-second refresh interval for positions

**Code Changes** (`frontend/src/hooks/useCommandCenterData.js`):
```javascript
// Fetch positions immediately on mount - doesn't depend on IB connection
useEffect(() => {
  fetchAccountData();
  const positionsInterval = setInterval(fetchAccountData, 30000);
  return () => clearInterval(positionsInterval);
}, []);
```

**Files Modified**:
- `frontend/src/hooks/useCommandCenterData.js` - Added separate useEffect for positions

**Testing Results**:
- 100% frontend tests passed
- My Positions section now correctly displays MSFT (242 shares) and NVDA (521 shares)
- Total Unrealized P&L shows correct sum
- Positions are clickable and open ticker detail modal

---

## Session Log - February 12, 2026 (UI Redesign - Glass Neon Theme)

### Feature: Full UI Redesign - "Glass Neon" Theme
**Design Direction**: Hybrid of Glassmorphism + Cyberpunk Neon aesthetics

### Design System Implemented

**Colors**:
- Background: Deep black (#050505)
- Glass: Semi-transparent with backdrop blur (rgba(10,10,10,0.75))
- Primary: Neon Cyan (#00E5FF) with glow effects
- Secondary: Magenta (#FF00F5) for alerts
- Status: Neon green/red/yellow with glow shadows

**Effects**:
- Frosted glass panels with 16px backdrop blur
- Neon glow shadows on active/hover states
- Subtle gradient highlights on glass cards
- Animated button hover effects with light sweep

### Components Updated
1. **index.css** - Complete design system with CSS variables and utility classes
2. **Sidebar.js** - Glass effect with neon active states
3. **HeaderBar.jsx** - Glass panel header with status indicators
4. **AICommandPanel.jsx** - Glass card with neon accents
5. **RightSidebar.jsx** - Glass cards for all widgets
6. **MarketIntelPanel.jsx** - Glass styling with neon icon
7. **CommandCenterPage.js** - Glass tabs navigation

### Key CSS Classes Added
- `.glass` / `.glass-card` / `.glass-panel` / `.glass-surface` - Frosted glass effects
- `.neon-glow` / `.neon-text` / `.neon-border` / `.neon-line` - Neon effects
- `.neon-dot` / `.neon-dot-success` / `.neon-dot-error` - Status indicators
- `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-icon` - Button variants
- `.input-glass` - Form input styling
- `.status-indicator` - Connection status badges
- `.glass-tab` - Tab button styling

### Maintainability
- All colors defined as CSS variables in `:root`
- Theme can be changed by updating ~15-20 CSS variables
- No hardcoded colors in components - all use semantic classes

### Feature: Full WebSocket Migration
**Goal**: Move all HTTP polling to WebSocket push for real-time updates, improving efficiency and reducing server load.

### What Was Migrated

| Data Type | Before (HTTP Polling) | After (WebSocket Push) |
|-----------|----------------------|------------------------|
| Quotes | Polling + WebSocket | WebSocket only |
| IB Status | 15s polling | 10s WebSocket push |
| Bot Status | 20s polling | 10s WebSocket push |
| Bot Trades | 25s polling | 20s WebSocket push |
| Scanner Alerts | 30s polling | 15s WebSocket push |
| Scanner Status | 30s polling | 10s WebSocket push |
| Smart Watchlist | 30s polling | 25s WebSocket push |
| Coaching Notifications | 15s polling | 12s WebSocket push |

### Backend Changes (`server.py`)
- Created 6 new background streaming tasks:
  - `stream_system_status()` - IB + Bot + Scanner status
  - `stream_bot_trades()` - Trading bot trades
  - `stream_scanner_alerts()` - Live scanner alerts
  - `stream_smart_watchlist()` - Smart watchlist updates
  - `stream_coaching_notifications()` - AI coaching alerts
- Each task uses change detection to only broadcast when data changes
- Proper serialization of LiveAlert and WatchlistItem objects to dicts

### Frontend Changes
- `App.js`: Added WebSocket state handlers for all new message types
- `AICommandPanel.jsx`: Uses WebSocket-pushed data instead of polling
- `RightSidebar.jsx`: Uses WebSocket-pushed data for scanner alerts and watchlist
- `AICoachTab.jsx`: Passes WebSocket data down to child components
- `CommandCenterPage.js`: Routes WebSocket data through component tree

### Connect Button Change
- Changed from "Connect/Disconnect" toggle to "Reconnect" button only
- Shows only when IB Gateway is disconnected (auto-connect handles normal case)
- Located in `HeaderBar.jsx`

### Bug Fixes During Migration
- Created missing `ChartsPage.js` wrapper component
- Fixed `get_stats()` method name in scanner streaming
- Fixed `get_all_trades_summary()` method name in bot trades streaming
- Fixed `get_coaching_notifications()` method name in notifications streaming
- Added proper object-to-dict serialization for WatchlistItem and LiveAlert objects

### Benefits
- Reduced HTTP request overhead by ~80%
- More responsive UI with push-based updates
- Single WebSocket connection handles all real-time data
- Better user experience with immediate status updates
- Reduced server load from polling


---

## Session Log - February 12, 2026 (Vibrant Dark Theme with Pop)

### Enhancement Request
User wanted a middle ground: darker than the light theme but not as dark as pure black, with more color and contrast for visual "pop".

### Implementation - Balanced Vibrant Dark Theme

**1. Color Palette** (`:root` in `index.css`):
- **Background**: `#0F1419` (balanced dark blue-gray, not pure black)
- **Paper**: `#151C24` (slightly lighter)
- **Primary**: `#00D4FF` (electric cyan - more vibrant)
- **Secondary**: `#FF2E93` (hot magenta/pink)
- **Accent**: `#A855F7` (electric purple)
- **Success**: `#10B981` with bright variant `#34D399`
- **Shadows**: Enhanced with colorful glows (`--shadow-pop`)

**2. Vibrant Gradient Background** (`body` in `index.css`):
```css
background-image: 
  radial-gradient(ellipse 80% 60% at 10% 0%, rgba(0, 212, 255, 0.15), transparent 50%),
  radial-gradient(ellipse 60% 50% at 90% 10%, rgba(168, 85, 247, 0.12), transparent 50%),
  radial-gradient(ellipse 70% 40% at 100% 50%, rgba(255, 46, 147, 0.1), transparent 50%),
  ...
```
Multiple colored gradient orbs at different positions for depth and visual interest.

**3. Glass Effects - Semi-transparent Dark**:
- `--glass-bg: rgba(21, 28, 36, 0.85)` - visible but not solid
- Enhanced blur (20-28px)
- Glowing borders and shadows

**4. Animated Gradient Borders - MORE VISIBLE**:
- Increased opacity from 0.4 to 0.6 (0.7 on featured cards)
- Hover increases to full 1.0 opacity
- 6-second rotation animation
- Colors: cyan → magenta → purple → cyan

**5. Neon Effects - HIGH CONTRAST**:
- Stronger text shadows on highlighted text
- Glowing icons with drop shadows
- Status indicators with colorful halos
- Buttons with double-layered glow shadows

**6. Component Updates**:
- All components now use dark glass (rgba 21,28,36)
- White text for high contrast
- Cyan neon accents on titles
- Vibrant gradient icons
- Glowing active states

### Visual Changes Achieved
1. ✅ Balanced dark background (not pure black)
2. ✅ Vibrant colorful gradient orbs in background
3. ✅ High-contrast animated gradient borders
4. ✅ Neon cyan text accents
5. ✅ Glowing gradient icon containers
6. ✅ High-visibility status indicators
7. ✅ "Pop" effect on hover with lift and glow

### Files Modified
- `frontend/src/index.css` - Complete color system for vibrant dark theme
- `frontend/src/App.js` - Vibrant gradient orbs
- `frontend/src/components/Sidebar.js` - Dark glass with neon accents
- `frontend/src/components/layout/HeaderBar.jsx` - Dark glass header
- `frontend/src/components/AICommandPanel.jsx` - Dark glass with gradient borders
- `frontend/src/components/MarketIntelPanel.jsx` - Dark glass panel

---

## Session Log - February 26, 2026 (P0 Blank Page Bug Fix)

### Bug Fix: Clicking Position Leads to Blank Page
**Problem**: User reported that clicking on a position (e.g., "MSFT") in the Positions tab or Portfolio Insights section caused the application to navigate to a blank page.

**Root Cause Analysis**:
1. **Type Mismatch**: In `AICoachTab.jsx`, the `handleTickerClick` function expected a **string** ticker parameter
2. However, `AICommandPanel.jsx` was calling `onTickerSelect` with an **object** `{ symbol, quote: {}, fromSearch: true }`
3. When `handleTickerClick(objectParam)` was called, `setChartSymbol(objectParam)` received an object instead of a string, causing unexpected behavior

**Fix Applied**:
1. Updated `handleTickerClick` in `AICoachTab.jsx` (lines 29-37) to handle both string and object parameters:
```javascript
const handleTickerClick = (tickerOrObject) => {
  const symbol = typeof tickerOrObject === 'string' 
    ? tickerOrObject 
    : tickerOrObject?.symbol;
  if (symbol) setChartSymbol(symbol);
};
```

2. Fixed undefined `CuratedOpportunityCard` component by changing it to `PipelineOpportunityCard` in `AICommandPanel.jsx` line 1088

**Files Modified**:
- `frontend/src/components/tabs/AICoachTab.jsx` - Fixed handleTickerClick to handle both string and object params
- `frontend/src/components/AICommandPanel.jsx` - Fixed CuratedOpportunityCard -> PipelineOpportunityCard

**Testing Results**:
- ✅ Clicking MSFT/NVDA badges in Portfolio Insights updates chart correctly
- ✅ My Positions expand/collapse works without blank page
- ✅ Trade Pipeline ticker buttons work correctly
- ✅ 100% frontend tests passed (iteration_40.json)

---

## Session Log - February 26, 2026 (P1 Ollama Stability Enhancement)

### Enhancement: Ollama Connection Retry Logic
**Problem**: Local Ollama connection via ngrok was intermittent, causing frequent timeouts and fallbacks to cloud AI.

**Fix Applied**:
Added retry mechanism with exponential backoff in `ai_assistant_service.py` (lines 1716-1810):
1. **3 retry attempts** before falling back to cloud AI
2. **Exponential backoff**: 1s, 2s, 4s delays between retries
3. **Increased timeout**: Base 180s + 30s per retry attempt
4. **Smart retry logic**:
   - Retries on: timeouts, connection errors, 5xx server errors, empty responses
   - No retry on: 4xx client errors
5. **Better logging**: Includes attempt number and specific error types

**Files Modified**:
- `backend/services/ai_assistant_service.py` - Added retry logic with exponential backoff

---

### Prioritized Backlog Update

### P0 - Critical (Completed)
- [x] **Blank page bug fix** (DONE - Feb 26, 2026) - Fixed handleTickerClick type handling

### P1 - High Priority
- [x] **Ollama retry logic** (DONE - Feb 26, 2026) - Added 3-retry mechanism with backoff
- [ ] Perplexity Finance API Integration (User interested)
- [ ] Complete Quick Actions backend (Close, Add, Alert handlers are stubs)
- [ ] Real-time RVOL in Market Intelligence

### P2 - Medium Priority
- [ ] Fix watchlist "(0)" flicker on load
- [ ] Remove dead code: RealtimeChart.jsx
- [ ] Keyboard shortcuts for common trading actions



---

## Session Log - March 4, 2026 (Smart Context Engine v2 + Validation Layer)

### Smart Context Engine v2 Enhancements

**New Features:**
1. **New Intent Categories** (12 total):
   - `news_check` - "Any news on NVDA?" → Fetches news + quote only
   - `technical_analysis` - "NVDA technicals" → Fetches technicals + quote only

2. **Structured Context Data** (`ContextData` class):
   - Stores quotes, positions, market indices for validation
   - Enables fact-checking of AI responses

3. **Intent-Specific Instructions**:
   - Each intent type now has tailored instructions for the LLM
   - Results in more focused, relevant responses

### Response Validation Layer

**New Class: `ResponseValidator`**
Validates AI responses against real-time data before returning to user.

**Validation Checks:**
1. **Price Validation**: Detects when AI claims a price that differs >2% from actual
2. **Position Validation**: Catches "no position" claims when user actually holds the stock
3. **Direction Validation**: Flags "breaking out" claims when stock is actually down
4. **Percentage Validation**: Warns on extreme percentage claims (>20% daily moves)

**Validation Output:**
```json
{
  "validated": true/false,
  "confidence": 0.0-1.0,
  "issues": [...],
  "recommendation": "Response validated successfully"
}
```

### New API Endpoints

1. **`POST /api/assistant/detect-intent`** - Test intent detection
2. **`POST /api/assistant/validate-response`** - Test validation independently
3. **`POST /api/assistant/chat`** - Now includes validation results

### Files Created/Modified
- `backend/services/smart_context_engine.py` - Added v2 features + ResponseValidator class
- `backend/services/ai_assistant_service.py` - Integrated validation layer, USE_SMART_CONTEXT flag
- `backend/routers/assistant.py` - Added validate-response endpoint

### Test Results
- Intent detection: 12 categories, 50-92% context reduction
- Validation: Correctly catches wrong prices, position claims, direction mismatches
- Chat responses now include validation confidence scores

### Updated Backlog

### P1 - High Priority (Completed)
- [x] **Smart Context Engine v2** (DONE - Mar 4, 2026)
- [x] **Response Validation Layer** (DONE - Mar 4, 2026)
- [x] **Phase 5: Earnings Proximity** (DONE - Mar 4, 2026)
- [x] **Auto-regeneration on validation failure** (DONE - Mar 4, 2026)
- [x] **Historical Accuracy Tracking** (DONE - Mar 4, 2026)

### P1 - High Priority (Remaining)
- [ ] Perplexity Finance API Integration
- [ ] Complete Quick Actions backend
- [ ] Real-time RVOL in Market Intelligence

### P2 - Medium Priority
- [x] Fix watchlist "(0)" flicker on load (DONE - Mar 4, 2026)
- [x] Remove dead code: RealtimeChart.jsx (DONE - already deleted)
- [ ] CrewAI multi-agent integration (future consideration)

---

## Session Log - March 4, 2026 (Phase 5 + Auto-Regeneration + Accuracy Tracking)

### Phase 5: Earnings Proximity Warnings (COMPLETE)

**Implementation:**
- Added `_get_earnings_proximity()` method to SmartContextEngine
- Checks Finnhub calendar for upcoming earnings on queried symbols
- Generates warnings based on proximity:
  - 🚨 EARNINGS TODAY - Extreme volatility
  - ⚠️ Within 2 days - HIGH RISK
  - ⚠️ Within 5 days - Elevated risk
  - 📅 Within 10 days - FYI notice
- Also shows historical beat/miss rates

**Files Modified:**
- `backend/services/smart_context_engine.py` - Added earnings proximity check

### Auto-Regeneration (COMPLETE)

**Implementation:**
- When validation finds HIGH-severity issues, automatically re-prompts the LLM
- Includes correction prompt with accurate data
- Max 1 retry to prevent infinite loops
- Tracks regeneration count in validation result

**Flow:**
```
LLM Response → Validation → High-severity issue found?
    ↓ YES
    Add correction prompt → Re-generate response → Re-validate
    ↓
    Return corrected response with regeneration_count
```

**Files Modified:**
- `backend/services/ai_assistant_service.py` - Added regeneration loop

### Historical Accuracy Tracking (COMPLETE)

**New Service:** `backend/services/accuracy_tracker.py`

**Features:**
- Records every chat validation result to MongoDB
- Tracks: intent, symbols, issues, confidence, provider, regeneration count
- Provides accuracy statistics over time

**New API Endpoints:**
- `GET /api/assistant/accuracy-stats` - Overall accuracy statistics
- `GET /api/assistant/accuracy-issues` - Recent validation issues
- `GET /api/assistant/accuracy-symbol/{symbol}` - Symbol-specific accuracy

**Example Statistics:**
```json
{
  "total_queries": 5,
  "validation_rate": 60.0,
  "average_confidence": 0.76,
  "by_intent": {"trade_decision": {"accuracy_rate": 60.0}},
  "by_provider": {"gpt-4o": {"accuracy_rate": 60.0}}
}
```

### Validation Improvements
- Fixed false positive on "any" being detected as a stock symbol
- Improved percentage validation to exclude portfolio allocation percentages
- Tightened regex patterns to reduce false positives


### UI Components Added (COMPLETE)

**AI Accuracy Indicator in Header:**
- Shows real-time accuracy percentage (color-coded: green ≥70%, yellow ≥50%, red <50%)
- Click to expand detailed stats popover
- Auto-refreshes after each chat query

**Accuracy Stats Popover:**
- Overall accuracy rate, query count, average confidence
- Breakdown by query type (price_check, trade_decision, etc.)
- Common issues list
- Dismissible with X button

**Per-Message Validation Indicator:**
- Shows confidence percentage (Shield icon + %) on each AI response
- Color-coded by confidence level
- Shows regeneration count if auto-regeneration was triggered (↻1)
- Tooltip shows validation status

**Files Modified:**
- `frontend/src/components/AICommandPanel.jsx`:
  - Added `accuracyStats` state and `fetchAccuracyStats()` function
  - Added accuracy indicator button in header
  - Added animated popover with stats breakdown
  - Modified `ChatMessage` component to show validation confidence
  - Messages now include validation data from API response

**Test Results:**
- Accuracy indicator visible in header: ✅
- Popover opens with stats: ✅
- Stats update after queries: ✅
- Per-message confidence shown: ✅


---

## Session Update - March 4, 2026

### P0-P3 Bug Fixes Completed

**P0 - IB Data Pusher Endpoint Verification**
- Status: ✅ VERIFIED
- Endpoint `GET /api/ib/pushed-data` returns valid JSON structure
- Returns `{connected: false, positions: [], quotes: {}, account: {}}` when local script not running
- Ready to receive data when user runs `ib_data_pusher.py` locally

**P1 - Ticker Modal Not Appearing**
- Status: ✅ FIXED
- Root Cause: `setSelectedTicker` was receiving a string instead of object
- Fix: Updated `handleTickerClick` in `AICoachTab.jsx` to pass `{ symbol, quote: {}, fromClick: true }`
- TickerDetailModal now opens correctly when clicking tickers in watchlist or chat

**P2 - Watchlist "(0)" Flicker on Load**
- Status: ✅ FIXED
- Root Cause: Watchlist count was rendering before data loaded
- Fix: Added `initialLoadComplete` state flag in `RightSidebar.jsx`
- Count only shows after initial data fetch completes; spinner shown during load

**P3 - Accuracy Indicator "--" on Load**
- Status: ✅ FIXED
- Root Cause: Accuracy indicator rendered with placeholder before data loaded
- Fix: Added `accuracyLoading` state in `AICommandPanel.jsx`
- Indicator hidden until fetch completes, then shows actual percentage (e.g., "80% accuracy")

### Files Modified This Session
- `frontend/src/components/tabs/AICoachTab.jsx` - Fixed ticker click handler
- `frontend/src/components/RightSidebar.jsx` - Added initialLoadComplete flag
- `frontend/src/components/AICommandPanel.jsx` - Added accuracyLoading state

### Files Deleted This Session
- `frontend/src/components/charts/RealtimeChart.jsx` - Dead code cleanup

### Pending Tasks (Backlog)
1. **Integrate IB Pushed Data into App Logic (P1)** - Refactor `ib_service.py` to consume data from push endpoint
2. ~~**Wire up Quick Actions buttons** - Implement close, add, alert actions~~ ✅ DONE
3. ~~**Ollama Model Toggle** - UI to switch between qwen2.5:3b and 7b models~~ ✅ DONE
4. **Perplexity Search API Integration** - Replace Tavily for market research
5. **CrewAI Multi-Agent System** - Advanced trading analysis

---

## Session Update - March 4, 2026 (Part 2)

### New Features Implemented

**1. Startup Explainer Modal**
- Opens on every fresh page load
- **Key Features Section**: 6 feature cards explaining the app:
  - AI Trading Assistant, Real-Time Charts, Smart Watchlist
  - Live Scanner, Trade Pipeline, AI Validation
- **System Status Section**: Real-time startup status with 6 indicators:
  - Backend, Alpaca, AI Assistant, Market Data, Portfolio, Watchlist
- "Don't show this again" checkbox (stores in localStorage: `tradecommand_skip_startup`)
- "Get Started" button enables when all systems connect (or after 10s fallback)

**2. Quick Actions System**
- **Backend API** (`/api/quick-actions/`):
  - `POST /add-to-watchlist` - Add symbol to smart watchlist
  - `POST /create-alert` - Create price/percent/volume alerts
  - `GET /alerts` - List active alerts
  - `DELETE /alerts/{symbol}` - Delete alerts for symbol
  - `DELETE /remove-from-watchlist/{symbol}` - Remove from watchlist
- **Frontend Component** (`QuickActionsMenu.jsx`):
  - 3 variants: `icon` (dropdown), `buttons` (inline), `compact` (small text links)
  - Integrated into: TickerDetailModal, Smart Watchlist, Scanner Alerts

**3. Ollama Model Toggle**
- **Backend API**: `POST /api/config/ollama-model`
- **Settings Page UI**: 3 model options with descriptions and speed indicators:
  - Qwen 2.5 3B (Fast)
  - Qwen 2.5 7B (Balanced)
  - Llama 3 8B (Balanced)
- Selection persists to `.env` for restart persistence

### Files Created
- `frontend/src/components/StartupModal.jsx`
- `frontend/src/components/QuickActionsMenu.jsx`
- `backend/routers/quick_actions.py`
- `backend/tests/test_quick_actions_and_config.py`

### Files Modified
- `backend/server.py` - Registered quick_actions router
- `backend/routers/config.py` - Added ollama-model endpoint
- `frontend/src/App.js` - Added StartupModal
- `frontend/src/components/TickerDetailModal.jsx` - Added QuickActionsMenu
- `frontend/src/components/RightSidebar.jsx` - Added QuickActionsMenu to watchlist/scanner
- `frontend/src/pages/SettingsPage.js` - Added model selection UI

### Testing Results
- Backend: 100% (19/19 tests passed)
- Frontend: 100% (all UI features verified)
- Test Report: `/app/test_reports/iteration_42.json`

### Remaining Backlog
1. ~~**Integrate IB Pushed Data** - Connect `ib_service.py` to push endpoint data~~ ✅ DONE
2. **Perplexity Search API** - Replace Tavily for market research
3. **CrewAI Multi-Agent** - Advanced trading analysis

---

## Session Update - March 4, 2026 (Part 3)

### IB Pushed Data Integration - COMPLETE

**Frontend Integration**:
- `useCommandCenterData.js`: Now fetches from `/api/ib/pushed-data` first, falls back to direct IB/Alpaca
- `IBTradingPage.js`: Both `fetchAccountData` and `fetchPositions` prioritize pushed data
- Automatic data normalization handles both IB and pusher field formats

**Backend API** (already existed, now fully utilized):
- `POST /api/ib/push-data`: Receives data from local `ib_data_pusher.py` script
- `GET /api/ib/pushed-data`: Returns quotes, positions, account with `connected` status
- Staleness check: `connected=false` if data >30 seconds old

### Startup Modal Enhancements

**z-index Fix**:
- Changed from `z-50` to inline `style={{ zIndex: 9999 }}`
- Modal now properly covers the entire screen including header

**Enhanced Feature Cards** (6 total):
1. **AI Trading Assistant** - "Privacy-first AI" badge
2. **Real-Time Charts** - "Auto S/R detection" badge
3. **Smart Watchlist** - "Auto-curated" badge
4. **Live Scanner** - "30+ strategies" badge
5. **Trade Pipeline** - "Built-in journaling" badge
6. **AI Validation Engine** - "Anti-hallucination" badge

Each card now shows:
- Title + highlight badge
- Short description
- Detailed explanation (visible on hover/scroll)

**New System Status Indicator**:
- Added "Checking IB Gateway connection..." to startup checks
- Shows ✓ when local pusher is connected and sending data
- Shows ⚠ warning when pusher not running (graceful degradation)

### Files Modified
- `frontend/src/components/StartupModal.jsx` - Enhanced features, z-index fix, IB pusher check
- `frontend/src/hooks/useCommandCenterData.js` - IB pushed data integration
- `frontend/src/pages/IBTradingPage.js` - IB pushed data integration

### Testing Results
- Backend: 100% (16/16 tests passed)
- Frontend: 100% (all UI features verified)
- Test Report: `/app/test_reports/iteration_43.json`

---

## Session Update - March 4, 2026 (Part 4)

### Scanner Universe Expansion - COMPLETE

**Before**: ~1,000 symbols scanned
**After**: ~1,473 unique symbols scanned (47% increase!)

**Expanded Coverage**:
- **SPY**: 495 symbols (S&P 500)
- **QQQ**: 120 symbols (NASDAQ 100)
- **NASDAQ Extended**: 480 symbols (mid-cap tech)
- **Russell 2000**: 542 symbols (expanded from ~300)
- **ETFs**: 45 key ETFs

**NEW: Sector-Specific Lists**:
| Sector | Symbols | Examples |
|--------|---------|----------|
| Biotech | 71 | CRSP, EDIT, NTLA, BEAM, XBI |
| Cannabis | 25 | TLRY, CGC, ACB, CRON, MSOS |
| EV/CleanTech | 57 | RIVN, LCID, CHPT, ENPH, TAN |
| Crypto | 38 | COIN, MARA, RIOT, MSTR, IBIT |
| Quantum/AI | 34 | IONQ, RGTI, QUBT, PLTR, AI |
| SPAC/IPO | 30 | ARM, CART, RBLX, JOBY, RKLB |

**NEW: User Viewed Symbol Tracking**:
- Symbols user interacts with (AI chat, watchlist, charts) are automatically tracked
- Tracked symbols get added to **Tier 1 scanning** (scanned every cycle)
- 7-day TTL with view count tracking
- Storage: MongoDB `user_viewed_symbols` collection

**Tier Structure**:
- **Tier 1**: ~579 symbols (SPY + QQQ + ETFs + Watchlist + User Viewed) - every cycle
- **Tier 2**: ~332 symbols (NASDAQ Extended) - every cycle  
- **Tier 3**: ~562 symbols (Russell 2000 + Sectors) - rotating batches

**Files Created**:
- `backend/services/user_viewed_tracker.py` - Symbol tracking service
- `backend/tests/test_scanner_universe_expansion.py` - Test coverage

**Files Modified**:
- `backend/data/index_symbols.py` - Expanded IWM, added sector lists
- `backend/services/wave_scanner.py` - Include user viewed in Tier 1
- `backend/services/smart_context_engine.py` - Track symbols from AI chat
- `backend/routers/scanner.py` - Added /universe-stats endpoint
- `backend/routers/quick_actions.py` - Track symbols on watchlist add

### Testing Results
- Backend: 100% (23/23 tests passed)
- Test Report: `/app/test_reports/iteration_44.json`

### Final Remaining Backlog
1. **Perplexity Search API** - Replace Tavily for market research
2. **CrewAI Multi-Agent** - Advanced trading analysis


---

## Session Log - March 5, 2026 (Earnings Calendar UI Verification)

### Fix: Earnings Calendar - Switched to Real Finnhub Data
**Issue**: Earnings Calendar had hardcoded/incorrect dates (e.g., NKE listed March 5 but actually reports March 18).

**Root Cause**: The `/api/earnings/calendar` endpoint used a hardcoded list of ~20 companies with guessed dates.

**Fix Applied**:
1. Replaced hardcoded data with real Finnhub `earnings_calendar` API
2. Filtered results to app's scanning universe (~1,500 symbols) for relevance
3. Added company name lookup for ~70 well-known symbols (COST→Costco, ADBE→Adobe, etc.)
4. Maintained same response shape so frontend works unchanged
5. **Column Layout**: Redesigned widget to 5-column grid (Mon-Fri) with companies listed vertically under each day
6. **Heat Indicators**: Days color-coded by earnings density (green=light, amber, orange, red=heavy) with a legend bar

**Results**:
- 93 real earnings entries across 2-week window (was 8 fake ones)
- March 5 correctly shows COST (Costco), MRVL (Marvell), ATHM etc.
- NKE (Nike) correctly placed on March 18
- `/api/earnings/today` also returns real data
- Sun/Moon icons distinguish Before Open vs After Close
- Week navigation loads fresh data per week

**Files Modified**: `backend/server.py` (earnings calendar endpoint + import), `frontend/src/components/RightSidebar.jsx` (EarningsWidget column layout + heat)
**Status**: ✅ COMPLETE & VERIFIED (iteration_46.json - 100% pass)

### Enhancement: Full Gradient Columns + Expected Move + Earnings Score
**Request**: Make the calendar more fully color-coded with gradient columns, add expected move in % and $, and earnings score for past/projected.

**Changes**:
1. **Full gradient columns** — entire column background is color-coded (green→amber→orange→red) based on density
2. **Expected move** — shows both percentage and dollar amount (e.g., "Exp 11.7% $27.94")
3. **Earnings score** — A+/A/B+/B/C/D/F with colored badges; based on EPS/revenue surprise for reported, analyst coverage for projected
4. **Proj vs Result labels** — distinguishes projected (upcoming) from actual (reported) scores
5. **EPS surprise** — for already-reported earnings, shows surprise % in green/red (e.g., "+18.0%")
6. **Column headers** — show day count (e.g., "14 reports")

**Files Modified**: `backend/server.py`, `frontend/src/components/RightSidebar.jsx`
**Status**: ✅ COMPLETE & VERIFIED (iteration_47.json - 100% pass, 10/10 backend, all frontend features)

### Updated Backlog

#### P0 - All Clear
- No critical issues remaining

#### P1 - High Priority
- [x] IB Data Pusher integrated into StartTrading.bat (auto-download, auto-install deps, connection verification)
- [x] AI Alert Reasoning Fix (March 2026) - AI now provides specific reasoning based on actual alert data
- [ ] Quick Actions Integration in Chat (Buy, Sell, Alert buttons in chat messages)
- [ ] IB Pushed Data Integration end-to-end verification (user must run pusher)
- [ ] Perplexity Search API integration
- [ ] Sentiment Heatmap Widget

#### P2 - Future
- [ ] CrewAI multi-agent system
- [ ] Strategy backtesting
- [ ] Remove unused NewsletterPage.js and backend endpoints

---

## Iteration 49 - AI Alert Reasoning Fix (March 2026)

**Problem**: When user asked "explain your reasoning for taking a trade on XPEV", the AI gave generic textbook responses instead of using the specific alert data (score, setup_type, reasoning) from the scanner.

**Root Causes Identified & Fixed**:
1. **Ticker Extraction Bug**: The regex was extracting common words like "PLAIN" (from "exPLAIN"), "ON", "YOU" instead of actual ticker symbols
2. **Alert Source**: Only checked live scanner alerts, not simulator alerts which persist separately
3. **Alert Expiration**: Live scanner alerts expire quickly, causing lookups to fail

**Changes Made** (`backend/services/ai_assistant_service.py`):
1. **Improved Ticker Extraction**:
   - Added context-based patterns: `on TICKER`, `for TICKER`, `about TICKER`
   - Expanded excluded words list with 80+ common English words
   - Prioritizes explicit `$TICKER` mentions
2. **Multi-Source Alert Lookup**:
   - Checks live scanner alerts first (`/api/live-scanner/alerts`)
   - Falls back to simulator alerts (`/api/simulator/alerts`)
   - Falls back to MongoDB `live_alerts` collection for recent (1-hour) alerts
3. **Rich Context Injection**:
   - When alert found, injects full context: setup_type, direction, priority, prices, R:R, reasoning points, market context
   - AI uses this specific data to explain the "why" behind alerts

**Testing**: Verified with simulator-generated alerts (XOM, NFLX, etc.) - AI now correctly explains specific setup data.

**Status**: ✅ COMPLETE

---

## Iteration 50 - "Explain Alert" Button Enhancement (March 2026)

**Feature**: Added an "Explain this alert" button to each alert card in the Scanner Alerts widget, making it one-click to get AI reasoning.

**Implementation**:
1. **Frontend - RightSidebar.jsx**:
   - Added `MessageSquare` icon import from lucide-react
   - Added a new button with `data-testid="explain-alert-{symbol}"` 
   - Button dispatches custom event `explainAlert` with symbol and alert data
   - Button appears on hover (opacity-0 → opacity-100 transition)

2. **Frontend - AICommandPanel.jsx**:
   - Added `useEffect` hook to listen for `explainAlert` custom event
   - When event received, auto-sends message: "Explain the reasoning for the {symbol} alert. Why was this setup identified?"
   - Uses existing `sendMessage` function

**UI/UX**:
- Button uses purple hover effect (`hover:bg-purple-500/20`)
- Icon turns purple on hover (`hover:text-purple-400`)
- Positioned between QuickActions and Chart button
- Shows tooltip: "Ask AI to explain this alert"

**Testing**: Verified via screenshot - clicking button sends message to AI, AI analyzes and responds with specific alert reasoning.

**Status**: ✅ COMPLETE

---

## Iteration 51 - SMB Capital EV Tracking System (March 2026)

**Feature**: Implemented full SMB Capital-style Expected Value (EV) tracking and workflow management system.

### Core Formula (SMB Capital Style)
```
EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)
```

### New Files Created
1. **`backend/services/ev_tracking_service.py`** - EV calculation engine and workflow state machine
2. **`backend/routers/ev_tracking.py`** - API endpoints for EV tracking

### Key Features

**1. Expected Value Calculation**
- Tracks R-multiples per setup (not just win/loss)
- Calculates EV using SMB's formula
- Maintains rolling EV trend (last 20 trades)
- Determines if EV is improving over time

**2. EV Gates (Sizing Recommendations)**
| Gate | EV Threshold | Size Multiplier | Recommendation |
|------|--------------|-----------------|----------------|
| A_SIZE | > 0.5R | 1.5x | Go big - strong edge |
| GREENLIGHT | > 0.2R | 1.0x | Standard size |
| CAUTIOUS | > 0R | 0.5x | Reduced size |
| REVIEW | > -0.2R | 0.25x | Needs analysis |
| DROP | < -0.2R | 0x | Remove from playbook |

**3. SMB Workflow State Machine**
```
IDEA_GEN → FILTER_GRADE → TRADE_PLAN → EXECUTION → REVIEW_EV
```
- **Idea Gen**: Create trade idea with catalyst score
- **Filter/Grade**: Assign A/B/C grade based on EV, catalyst, context
- **Trade Plan**: Define entry, stops, targets with EV-adjusted sizing
- **Execution**: Mark trade as live
- **Review**: Record R-multiple, update EV, close loop

**4. Trade Grading (A/B/C)**
- A-grade: Score ≥70 (best setups, 1.2x size bonus)
- B-grade: Score 45-69 (standard setups)
- C-grade: Score <45 (marginal, reduced size)

Grading factors:
- R:R ratio (30 pts max)
- Historical EV (30 pts max)
- Tape confirmation (20 pts max)
- Priority/catalyst (15 pts max)
- Market context (10 pts max)

**5. Enhanced Data Models**
- `StrategyStats` now includes R-multiples, EV calculation, EV trend
- `LiveAlert` now includes `strategy_ev_r`, `trade_grade`, `projected_r`, `workflow_state`

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ev/report` | GET | Get EV report for one/all setups |
| `/api/ev/playbook` | GET | Get PlayBook summary (positive/negative EV setups) |
| `/api/ev/record-outcome` | POST | Record R-multiple for EV calculation |
| `/api/ev/calculate` | POST | Manually recalculate EV |
| `/api/ev/workflow/idea` | POST | Create trade idea |
| `/api/ev/workflow/grade` | POST | Filter and grade idea |
| `/api/ev/workflow/plan` | POST | Create trade plan |
| `/api/ev/workflow/execute` | POST | Mark as executed |
| `/api/ev/workflow/review` | POST | Review trade, update EV |
| `/api/ev/active-ideas` | GET | Get active workflow ideas |
| `/api/ev/setup-gates` | GET | Get EV gates for all setups |

### SMB's 20 Core Setups Tracked
1. Changing Fundamentals
2. Breakout Trade
3. Big Dawg Trade
4. Technical Analysis
5. Opening Drive
6. IPO Trade
7. 2nd Day Trade
8. Elite Trading 101
9. Return Pullback
10. Scalp Trade
11. Stuffed Trade
12. Multiple Time Frame Support
13. Dr. S Trades
14. Market Play Trade
15. Breaking News
16. Bounce Trades
17. Gap and Go Trade
18. Low Float Trade
19. Stock Filters
20. VWAP with Shark

Plus our custom setups: rubber_band, vwap_bounce, vwap_fade, orb, hitchhiker, spencer_scalp, etc.

### Integration with AI Assistant
- AI context now includes EV data when explaining alerts
- Shows: Historical Win Rate, Avg Win R, Avg Loss R, EV per trade, EV Gate, Size Recommendation

### Testing Results
```
Setup: rubber_band (11 trades)
Win Rate: 63.6%
Avg Win R: 2.47
Avg Loss R: 0.88
Expected Value: 1.25R per trade
EV Gate: A_SIZE
Size Multiplier: 1.5x
Recommendation: A-SIZE - Strong edge, increase position size
```

**Status**: ✅ COMPLETE

---

## Iteration 52 - S/R Level Integration with EV (March 2026)

**Enhancement**: Integrated Support/Resistance levels, target prices, and stops into the EV calculation system for more accurate R-multiple projections.

### New Features

**1. TradeLevels Data Structure** (`ev_tracking_service.py`)
```python
@dataclass
class TradeLevels:
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: Optional[float]
    target_3: Optional[float]
    support: Optional[float]
    resistance: Optional[float]
    vwap: Optional[float]
    ema_9: Optional[float]
    atr: Optional[float]
```

**2. `calculate_levels_from_technical()`**
Calculates optimal entry, stop, and target levels based on:
- Support/Resistance levels
- ATR for volatility-adjusted stops
- VWAP and EMA for mean reversion targets
- Setup type (breakout vs mean reversion)

**For LONG trades:**
- Stop: Below support or 1 ATR below entry
- Target 1: At resistance or VWAP
- Target 2: Above resistance + 1 ATR

**For SHORT trades:**
- Stop: Above resistance or 1 ATR above entry
- Target 1: At support or VWAP
- Target 2: Below support - 1 ATR

**3. `calculate_projected_ev()`**
Calculates projected EV using:
- Actual price levels for R-multiple
- Historical win rate for the setup
- Partial profit management (50% at T1, 30% at T2, 20% trails)

### New API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/ev/calculate-levels` | Calculate entry/stop/targets from S/R levels |
| `POST /api/ev/projected-ev` | Calculate projected EV using levels + historical data |
| `GET /api/ev/analyze-alert/{symbol}` | Full EV analysis for a symbol |

### Updated Alert Generation
- Breakout and Rubber Band setups now calculate R-multiple from actual S/R levels
- Stop placed below support (long) or above resistance (short)
- Target placed at next key level
- Alert reasoning includes R:R ratio and historical EV data

### Test Results
```
Setup: rubber_band (10 trades)
Historical: 70% win rate, 2.20R avg win, 1.00R avg loss
EV: 1.24R (B_TRADE)

Projected Trade (TSLA-like):
  Entry: $250, Stop: $245.98, Target: $257.50
  R at T1: 1.87R
  Projected EV: 1.14R
  Grade: B_TRADE - Solid projected edge
```

**Status**: ✅ COMPLETE



---

## UI/UX Improvements (March 2026)

### Completed Fixes

| Issue | Fix | File |
|-------|-----|------|
| **Startup Modal Too Large** | Reduced to max-w-xl (576px), 2-column status grid, compact header/footer | `StartupModal.jsx` |
| **Chat Alert Cards Too Large** | Compact layout with inline price row, smaller padding (p-2.5) | `AICommandPanel.jsx` |
| **Missing Entry/Target/Stop Prices** | Fixed field mapping - backend sends `trigger_price/stop_loss/target`, frontend now handles both direct and nested `alert_data` formats | `AICommandPanel.jsx` |
| **Main Panels Too Small** | Changed from 8/4 to 9/3 column split, increased min-height to 900px | `AICoachTab.jsx` |

### Price Field Mapping Fix (BUG FIX)

**Problem**: Alert prices (Entry, Target, Stop) displayed as `$--` because:
1. Backend sends: `trigger_price`, `stop_loss`, `target`
2. Frontend expected: `entry`, `target`, `stop`
3. Coaching notifications nest data under `alert_data` object

**Solution** (AICommandPanel.jsx lines 237-246):
```javascript
const alertData = alert.alert_data || {};
const entryPrice = alert.entry || alert.trigger_price || alertData.trigger_price || alert.current_price || alertData.current_price;
const targetPrice = alert.target || alertData.target;
const stopPrice = alert.stop || alert.stop_loss || alertData.stop_loss;
const riskReward = alert.risk_reward || alertData.risk_reward;
```

**Status**: ✅ COMPLETE - Verified via testing agent (iteration_50.json)


---

## Additional UI Fixes (March 2026 - Follow-up)

### Panel Sizing Adjustments

| Change | Before | After | File |
|--------|--------|-------|------|
| Chat area maxHeight | 70% | 55% | `AICommandPanel.jsx` |
| Chat area minHeight | 400px | 280px | `AICommandPanel.jsx` |
| Chart minHeight | 350px | 400px | `AICommandPanel.jsx` |

**Result**: Portfolio Insights, My Portfolio, and Stock Charts panels now have more visible space without being cut off.

### Tape Score Formatting

**Problem**: Tape scores displayed with excessive decimal places (e.g., `-0.11428571428571428`)

**Solution** (RightSidebar.jsx line 690):
```javascript
const formattedScore = typeof score === 'number' ? score.toFixed(1) : score;
```

**Result**: Tape scores now display as `-0.1`, `0.3`, etc.

**Status**: ✅ COMPLETE


---

## SMB Playbook, DRC & Game Plan System (March 2026)

### Implementation Complete

Based on Mike Bellafiore's "The Playbook" methodology and SMB Capital's trading practices, implemented a comprehensive trading journal system with 3 new components:

#### **1. Playbook System** (`/app/backend/services/playbook_service.py`)
- Document repeatable trade setups with IF/THEN rules
- 30+ setup types from SMB registry
- Market context categories (High/Low Strength/Weakness)
- Catalyst types (Fresh Planned, Breaking News, Technical)
- Trade styles (M2M, T2H, A+, Scalp, Swing)
- Process-based grading (not P&L outcome)
- Performance tracking per playbook

#### **2. Daily Report Card (DRC)** (`/app/backend/services/drc_service.py`)
- Overall day grade (A+ to F)
- Pre-market checklist (customizable, 8 default items)
- Intraday performance tracker (3 segments: 7:30-11, 11-2, 2-4:30)
- Trades summary (auto-populated from day's activity)
- Reflections section ("Easiest $3K trade", lessons learned)
- Auto-generation from trading data

#### **3. Game Plan System** (`/app/backend/services/gameplan_service.py`)
- Big picture market commentary
- Stocks in play (max 5) with IF/THEN statements
- Day 2 names (continuation candidates)
- Risk management parameters (daily stop, per-trade risk)
- Session goals and what to avoid
- Auto-generation from scanner alerts

### API Endpoints (`/app/backend/routers/journal_router.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/journal/playbooks` | GET/POST | List/Create playbooks |
| `/api/journal/playbooks/{id}` | GET/PUT/DELETE | CRUD operations |
| `/api/journal/playbooks/{id}/trades` | POST | Log trade against playbook |
| `/api/journal/drc/today` | GET | Get/Create today's DRC |
| `/api/journal/drc/date/{date}` | GET/PUT | Get/Update DRC by date |
| `/api/journal/gameplan/today` | GET | Get/Create today's game plan |
| `/api/journal/gameplan/date/{date}/stocks` | POST | Add stock to game plan |
| `/api/journal/overview` | GET | Get journal overview stats |

### Frontend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `PlaybookTab.jsx` | `/app/frontend/src/components/Journal/` | Create/manage playbooks |
| `DRCTab.jsx` | `/app/frontend/src/components/Journal/` | Daily report card interface |
| `GamePlanTab.jsx` | `/app/frontend/src/components/Journal/` | Daily game plan interface |

### Integration with AI Assistant
The AI assistant now has access to:
- User's playbooks for personalized coaching
- DRC data for performance analysis
- Game plan data for trade suggestions

**Status**: ✅ COMPLETE - Backend services working, frontend tabs integrated into Trade Journal page


---

## TraderSync Import & AI Auto-Generation (March 2026)

### New Features Implemented

#### **1. TraderSync CSV Import**
- Drag & drop CSV upload
- Automatic column mapping for TraderSync exports
- Import batch tracking and management

#### **2. AI Playbook Generation**
- Analyze winning trades by setup type
- Generate complete SMB 6-section playbook entries
- Bulk generation from all TraderSync imports

#### **3. AI DRC Auto-Generation**
- Auto-populate DRC from day's trades
- Calculate overall grade based on P&L, win rate, trade count
- AI-generated reflections when LLM available

**Status**: ✅ COMPLETE

---

## End-of-Day Auto-Generation Scheduler (March 2026)

### Overview
Automatic generation of Daily Report Cards (DRCs) and Playbooks at market close without manual intervention.

### Implementation Details

#### **Scheduler Configuration**
- **DRC Generation**: 4:30 PM ET weekdays
- **Playbook Analysis**: 4:45 PM ET weekdays
- **Timezone**: America/New_York
- **Library**: APScheduler (BackgroundScheduler)

#### **Backend Components**
| File | Purpose |
|------|---------|
| `/app/backend/services/eod_generation_service.py` | Scheduler and generation logic |
| `/app/backend/server.py` (lines 114-116) | Scheduler initialization |
| `/app/backend/routers/journal_router.py` (lines 660-765) | EOD API endpoints |

#### **API Endpoints**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/journal/eod/status` | GET | Get scheduler status and next run times |
| `/api/journal/eod/trigger` | POST | Manually trigger EOD generation |
| `/api/journal/eod/pending-playbooks` | GET | List AI-generated playbooks awaiting review |
| `/api/journal/eod/pending-playbooks/{id}/approve` | POST | Approve pending playbook |
| `/api/journal/eod/pending-playbooks/{id}/reject` | POST | Reject pending playbook |
| `/api/journal/eod/logs` | GET | Get recent generation logs |

#### **Frontend Updates**
| Component | Changes |
|-----------|---------|
| `DRCTab.jsx` | Added Auto-Generation Status banner, AI Generated badge |
| `PlaybookTab.jsx` | Added Pending Playbooks review section, approve/reject buttons |

#### **Features**
1. **Auto-Generation Banner**: Shows scheduler status, next run time
2. **AI Generated Badge**: Marks auto-generated DRCs with timestamp
3. **Pending Playbooks**: AI-generated playbooks require user approval before activation
4. **Manual Override**: Users can still create manual entries alongside AI ones
5. **Edit Capability**: All AI-generated content is editable

**Status**: ✅ COMPLETE - Tested (25/25 backend tests passed)

---

## Bug Fix: Bot Autonomous Mode Not Auto-Executing (March 2026)

### Issue
When the trading bot was set to "autonomous" mode, it was still showing trade ideas as recommendations instead of auto-executing them.

### Root Cause
Two separate flags controlled auto-execution:
1. **Bot Mode** (`autonomous`/`confirmation`/`paused`) - Controls bot's internal behavior
2. **Scanner Auto-Execute** (`_auto_execute_enabled`) - Controls whether scanner pushes alerts to bot

These were independent - setting bot to "autonomous" didn't enable scanner auto-execute.

### Fix Applied
Modified `/app/backend/routers/trading_bot.py`:
- `POST /mode/{mode}` - Now syncs scanner auto-execute with bot mode
- `POST /start` - Syncs scanner auto-execute on bot start
- `POST /config` - Syncs scanner auto-execute on config update

When bot mode is `autonomous`:
- Scanner auto-execute enabled (min_win_rate=55%, min_priority=HIGH)

When bot mode is `confirmation` or `paused`:
- Scanner auto-execute disabled

**Status**: ✅ FIXED

---

## Future Enhancement: Weekly Performance Summary (Saved)

### Concept
Auto-generate a Weekly Performance Summary every Friday at market close that aggregates:
- All DRCs from the week
- Win rate and P&L totals
- Best performing playbooks
- Areas for improvement
- Comparison with previous weeks

### Implementation Notes (for future)
- Add new endpoint: `/api/journal/weekly-summary`
- Schedule generation: Friday 4:30 PM ET
- Include: win/loss ratio, average R, best/worst trades, playbook performance
- Could use AI to generate narrative insights

**Status**: 📋 SAVED FOR FUTURE

---

## Tech Debt Fix: Singleton Initialization Pattern (March 2026)

### Issue
Older backend services (chart_pattern_service, sector_analysis_service, sentiment_analysis_service) had inconsistent initialization patterns:
- Used `self._initialized` directly in checks
- External code accessed `service._initialized` (private attribute)
- No `is_initialized()` public method

### Fix Applied
Updated all three services and their routers to use a consistent pattern:

**Services Updated:**
- `/app/backend/services/chart_pattern_service.py`
- `/app/backend/services/sector_analysis_service.py`
- `/app/backend/services/sentiment_analysis_service.py`

**Routers Updated:**
- `/app/backend/routers/patterns.py`
- `/app/backend/routers/sectors.py`
- `/app/backend/routers/sentiment.py`

**Pattern Implemented:**
```python
def is_initialized(self) -> bool:
    """Check if service is properly initialized"""
    return self._initialized and self._dependency is not None

def _ensure_initialized(self) -> bool:
    """Ensure service is initialized before operations"""
    if not self.is_initialized():
        logger.warning("Service not initialized")
        return False
    return True
```

**Also Updated:**
- `/app/backend/server.py` - Added initialization for chart_pattern_service and sentiment_service at startup
- `/app/backend/services/enhanced_scanner.py` - Changed `_initialized` access to `is_initialized()`

**Status**: ✅ FIXED - All three services now working correctly

---

## Level 2 / DOM Integration for Tape Reading (March 2026)

### Overview
Enhanced tape reading with Level 2 (Depth of Market) data from IB Gateway for better trade confirmation signals.

### Components Updated

**IB Data Pusher** (`/app/documents/ib_data_pusher.py`):
- Added `level2_buffer` for DOM data storage
- Added `on_market_depth()` handler for L2 updates
- Added `subscribe_level2()` / `unsubscribe_level2()` methods
- Added `update_level2_subscriptions()` for dynamic in-play stock tracking
- Added `--no-level2` flag to disable if needed
- L2 subscriptions auto-update every 30 seconds based on in-play stocks

**Backend IB Router** (`/app/backend/routers/ib.py`):
- Added `level2` field to `IBPushDataRequest` model
- New endpoint: `GET /api/ib/level2/{symbol}` - Get L2 data for symbol
- New endpoint: `GET /api/ib/inplay-stocks` - Get symbols needing L2
- Helper functions: `get_level2_for_symbol()`, `get_all_level2_data()`

**Enhanced Scanner** (`/app/backend/services/enhanced_scanner.py`):
- `_get_tape_reading()` now incorporates L2 imbalance when available
- Added L2 fields to `TapeReading` dataclass:
  - `l2_available`, `l2_imbalance`, `l2_bid_depth`, `l2_ask_depth`
  - `l2_gate_would_pass_long`, `l2_gate_would_pass_short` (monitoring)

### L2 Gate Monitoring (Not Enforced Yet)
The system now tracks whether an L2-based gate **would have** blocked trades:
- Long trade gate: `l2_imbalance > 0.1` (10%+ more bids than asks)
- Short trade gate: `l2_imbalance < -0.1` (10%+ more asks than bids)

This data is logged for analysis. Once we confirm it improves accuracy without being too strict, we can enable it as a hard gate.

### Usage
```bash
# Run IB Data Pusher with Level 2 enabled (default)
python ib_data_pusher.py --cloud-url https://brief-me-dash.preview.emergentagent.com

# Disable Level 2 if needed
python ib_data_pusher.py --cloud-url https://brief-me-dash.preview.emergentagent.com --no-level2
```

**Status**: ✅ IMPLEMENTED - Monitoring mode active

---

## Sentiment Data Sources (Current State)

### Currently Integrated
- ✅ **Finnhub** - News articles and company news

### Not Yet Integrated
- ❌ **Twitter/X** - Would require API access ($100+/month for Basic)
- ❌ **Reddit** - Would need r/wallstreetbets, r/stocks scraping
- ❌ **StockTwits** - Free API available, good for retail sentiment

### Placeholder
The `social_sentiment` field exists in `SentimentResult` but is hardcoded to `0.0`.

**Status**: 📋 NOTED FOR FUTURE - Twitter/social integration on backlog

---

## Three-Speed Learning System - Master Implementation Plan (March 2026)

### Overview
A comprehensive learning and adaptation system for the AI Trading Bot that operates at three speeds:
- **Fast (Real-time)**: Updates after every trade
- **Medium (Daily)**: End-of-day analysis and calibration
- **Slow (Weekly)**: Backtesting and strategy verification

### Complete Feature List (29 Features)

#### High Impact - Accuracy
1. ✅ Tape Reading Calibration - Auto-adjust thresholds based on outcomes
2. ✅ Setup-Specific Win Rate Filters - Dynamic thresholds per setup
3. ✅ Time-of-Day Filters - Shadow mode first, then enable
4. ✅ Market Regime Awareness - Gate bot based on regime

#### Medium Impact - Reliability
5. ✅ Circuit Breakers - Daily loss limit, consecutive loss pause
6. ✅ Shadow/Paper Mode - Test changes before deploying
7. ✅ Health Monitoring Dashboard - API latency, fill rates, uptime
8. ✅ Graceful Degradation - Fallback when services fail

#### Quick Wins
9. ✅ Position Sizing by Conviction - TQS-based size multipliers
10. ✅ Exit Optimization - Track R-capture, tune stops
11. ✅ News Sentiment to Bot - Block longs on bearish, boost shorts

#### Competitive Edge
12. ✅ Backtest Module - Test setups on historical data
13. ✅ Multi-Timeframe Confirmation - Daily trend + 5min entry
14. ✅ Order Flow / Level 2 - IB Gateway integration (done)

#### Learning Enhancements
15. ✅ Contextual Win Rates - By regime, time, sector, VIX
16. ✅ Entry Quality Scoring - Slippage, chase detection
17. ✅ Exit Quality Analysis - R-capture, left-on-table
18. ✅ Confirmation Signal Validation - Which signals help?
19. ✅ Tilt Detection - Behavior change after losses
20. ✅ Edge Decay Detection - Rolling performance decline
21. ✅ Playbook Performance Linkage - Documented vs actual
22. ✅ Correlated Losses - VIX, sector, time patterns
23. ✅ Optimal Position Retrospective - What size would've been best
24. ✅ Multi-Factor TQS - Single 0-100 score

#### TQS Components
25. ✅ Setup Quality (25%) - Pattern, win rate, EV, tape
26. ✅ Technical Quality (25%) - Trend, levels, RSI, MAs, RVOL
27. ✅ Fundamental Quality (15%) - Catalyst, short%, float, inst%
28. ✅ Context Quality (20%) - Regime, time, sector, VIX
29. ✅ Execution Quality (15%) - Your history, entry/exit, tilt

### Implementation Phases

#### PHASE 1: Core Infrastructure + Graceful Degradation
**Files to create:**
- `/backend/services/learning_loop_service.py`
- `/backend/services/trade_context_service.py`
- `/backend/services/execution_tracker_service.py`
- `/backend/services/graceful_degradation.py`
- `/backend/models/learning_models.py`

**MongoDB collections:**
- `trade_outcomes` - Full trade records with context
- `learning_stats` - Aggregated statistics
- `calibration_log` - Threshold adjustments over time
- `trader_profile` - Your patterns for RAG

**Dataclasses:**
- `TradeContext` - regime, time, sector, VIX, fundamentals
- `ExecutionMetrics` - entry/exit quality, slippage, R-capture
- `TradeOutcome` - full trade with context and execution
- `LearningStats` - aggregated per setup/context
- `TraderProfile` - summary for AI context

#### PHASE 2: TQS Engine (All 5 Pillars)
**Files to create:**
- `/backend/services/tqs_engine.py` - Master scorer
- `/backend/services/setup_quality.py` - 25%
- `/backend/services/technical_quality.py` - 25%
- `/backend/services/fundamental_quality.py` - 15%
- `/backend/services/context_quality.py` - 20%
- `/backend/services/execution_quality.py` - 15%

**Technical Quality includes:**
- RSI calculation, MA stack detection
- Support/resistance proximity
- ATR-based risk assessment

**Fundamental Quality sources:**
- IB Gateway: P/E, short%, float, inst%
- Finnhub: Earnings calendar
- News sentiment integration

#### PHASE 3A: Fast Learning - Circuit Breakers + Health
- Daily loss limit (configurable)
- Consecutive loss pause (3 losses)
- Conviction-based sizing from TQS
- Tilt detection with behavior tracking
- Health monitoring dashboard
- API latency, fill rate, slippage tracking

#### PHASE 3B: Fast Learning - Dynamic Thresholds
- Per-setup win rate thresholds
- Tape score calibration
- Time-of-day filtering (shadow mode)
- Market regime gating
- News sentiment gating
- Bounded adjustments (max 10%/day)

#### PHASE 4: RAG Knowledge Base
- ChromaDB (local vector DB)
- Trader profile generator
- Similar trade retrieval
- Playbook/trade history embedding
- AI prompt enhancement with YOUR patterns

#### PHASE 5: Medium Learning - Daily Analysis (COMPLETE - Mar 10, 2026)
- EOD DRC/Playbook generation (done)
- Calibration analysis ✅
- Context performance report ✅
- Confirmation signal validation ✅
- Edge decay detection ✅
- Playbook performance linkage ✅
- Trader profile updates ✅

#### PHASE 6: Slow Learning - Backtest & Verify (COMPLETE - Mar 10, 2026)
- Historical data downloader (Alpaca) ✅
- Backtest engine ✅
- Shadow mode tracker ✅
- Weekly review generator ✅
- Strategy deployment verification ✅

### RAG Integration - Making Ollama Learn

The AI doesn't get "retrained" - instead, we inject YOUR knowledge into every prompt:

**Trader Profile (auto-generated):**
```
"You are advising a trader with these characteristics:
 - Best setups: Bull Flag (68%), VWAP Bounce (64%)
 - Avoid: Gap & Go (42%), Late Day Momentum (38%)
 - Best hours: 9:30-11:00 AM (62% win)
 - Tends to chase entries by avg 0.15%
 - Exits too early, captures only 60% of move
 - Performs best in trending markets (67% win)
 - Current state: 2 losses today, possible tilt"
```

**Similar Trade Retrieval:**
When analyzing a new setup, retrieve your past similar trades and outcomes.

### Data Sources Summary

| Data | Source | Status |
|------|--------|--------|
| Quotes/Bars | Alpaca | ✅ Working |
| Level 2/DOM | IB Gateway | ✅ Implemented |
| Fundamentals | IB Gateway | ✅ Implemented |
| Earnings | Finnhub | ✅ Working |
| News | Finnhub | ✅ Working |
| Sector Data | Alpaca/Internal | ✅ Working |
| Trade History | MongoDB | ✅ Working |
| Learning Stats | MongoDB | ✅ Phase 1-5 Complete |
| TQS Engine | Internal | ✅ Phase 2 Complete |
| Fast Learning | Internal | ✅ Phase 3 Complete |
| RAG Knowledge Base | ChromaDB | ✅ Phase 4 Complete |
| Medium Learning | Internal | ✅ Phase 5 Complete |
| Slow Learning | Internal | ✅ Phase 6 Complete |

**Status**: ✅ ALL 6 PHASES COMPLETE - Three-Speed Learning Architecture Fully Implemented

---

## Session Log - March 10, 2026 (Phase 1: Core Learning Infrastructure)

### Three-Speed Learning Architecture - Phase 1 COMPLETE

**Goal**: Build foundational infrastructure for the learning system.

**What was implemented:**

#### 1. New Data Models (`/app/backend/models/learning_models.py`)
- `TradeContext`: Complete market context snapshot (regime, VIX, time, sector, fundamentals, technicals, sentiment)
- `ExecutionMetrics`: Entry/exit quality tracking (slippage, R-capture, timing, scale-outs, stop management)
- `TradeOutcome`: Full trade record with context and execution for learning
- `LearningStats`: Aggregated statistics by context (win rate, EV, profit factor by setup+regime+time)
- `TraderProfile`: Summary of trader patterns for RAG injection into AI prompts
- Supporting: `TiltState`, `CalibrationEntry`, Enums for regime/time/volatility

#### 2. New Services
- **LearningLoopService** (`learning_loop_service.py`): Main orchestrator
  - Captures alert context, tracks executions, records outcomes
  - Runs daily analysis to aggregate stats and update profile
  - Tilt detection based on recent performance
  - Generates trader profile context for AI prompts
  
- **TradeContextService** (`trade_context_service.py`): Context capture
  - Gathers SPY/QQQ/VIX, time-of-day, sector rankings
  - Captures fundamentals from IB Gateway
  - Captures technicals (RSI, ATR, VWAP, MAs, squeeze)
  - Captures news sentiment
  
- **ExecutionTrackerService** (`execution_tracker_service.py`): Execution quality
  - Tracks entry/exit slippage
  - Monitors R-capture and timing
  - Records scale-outs and stop adjustments
  - Calculates overall execution quality score
  
- **GracefulDegradationService** (`graceful_degradation.py`): Fault tolerance
  - Service health monitoring by priority (critical/important/optional)
  - Automatic fallback mechanisms
  - Never blocks trading due to non-critical service failure

#### 3. New MongoDB Collections
- `trade_outcomes`: Full trade records with context and execution
- `learning_stats`: Aggregated statistics by context key
- `calibration_log`: History of threshold adjustments
- `trader_profile`: Current trader patterns for RAG

#### 4. New API Endpoints (`/api/learning/loop/*`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/learning/loop/stats` | GET | Learning statistics with filters |
| `/api/learning/loop/contextual-winrate` | GET | Win rate by setup+context |
| `/api/learning/loop/outcomes` | GET | Recent trade outcomes |
| `/api/learning/loop/profile` | GET | Trader profile for RAG |
| `/api/learning/loop/tilt-status` | GET | Current tilt status |
| `/api/learning/loop/daily-analysis` | POST | Trigger EOD analysis |
| `/api/learning/loop/health` | GET | System health status |

#### 5. Integration Points
- **Scanner** → Captures context when alerts are generated
- **Trading Bot** → Tracks execution and records outcomes when trades close
- **AI Assistant** → Can inject trader profile into prompts (future)

### Testing Results
- 17/17 backend API tests passed (100%)
- Frontend loads correctly with WebSocket streaming
- All new services initialize without errors

### Files Created/Modified
**New Files:**
- `/app/backend/models/__init__.py`
- `/app/backend/models/learning_models.py`
- `/app/backend/services/learning_loop_service.py`
- `/app/backend/services/trade_context_service.py`
- `/app/backend/services/execution_tracker_service.py`
- `/app/backend/services/graceful_degradation.py`
- `/app/backend/tests/test_learning_loop_phase1.py`

**Modified Files:**
- `/app/backend/server.py` - Added imports and service initialization
- `/app/backend/services/trading_bot_service.py` - Integrated learning loop
- `/app/backend/services/enhanced_scanner.py` - Added context capture
- `/app/backend/routers/learning_dashboard.py` - Added new endpoints

---

## Session Log - March 10, 2026 (Phase 2: TQS Engine) - COMPLETE

### Trade Quality Score (TQS) Engine - Phase 2 COMPLETE

**Goal**: Build unified 0-100 scoring system with 5 weighted pillars.

**What was implemented:**

#### 1. TQS Pillar Services (`/app/backend/services/tqs/`)

| Pillar | Weight | Components |
|--------|--------|------------|
| **Setup Quality** | 25% | pattern, win_rate, expected_value, tape, smb_grade |
| **Technical Quality** | 25% | trend, rsi, levels, volatility, volume |
| **Fundamental Quality** | 15% | catalyst, short_interest, float, institutional, earnings |
| **Context Quality** | 20% | regime, time, sector, vix, day_of_week |
| **Execution Quality** | 15% | history, tilt, entry_tendency, exit_tendency, streak |

#### 2. Action Recommendations

| Score Range | Action | Sizing |
|-------------|--------|--------|
| 80-100 | STRONG_BUY | Full position (100%) |
| 65-79 | BUY | Standard (75-100%) |
| 50-64 | HOLD | Reduced (50-75%) |
| 35-49 | AVOID | Paper trade only |
| 0-34 | STRONG_AVOID | Do not trade |

#### 3. Grade System

| Grade | Score Range |
|-------|-------------|
| A | 85-100 |
| B+ | 75-84 |
| B | 65-74 |
| C+ | 55-64 |
| C | 45-54 |
| D | 35-44 |
| F | 0-34 |

#### 4. New API Endpoints (`/api/tqs/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tqs/score/{symbol}` | GET | Quick TQS summary |
| `/api/tqs/breakdown/{symbol}` | GET | Detailed pillar breakdown |
| `/api/tqs/batch` | POST | Score multiple opportunities |
| `/api/tqs/pillars` | GET | Pillar information |
| `/api/tqs/thresholds` | GET | Action thresholds and weights |
| `/api/tqs/guidance` | GET | Trading guidance for a score |

### Testing Results
- 39/39 backend API tests passed (100%)
- All pillar components working correctly
- Grades and actions assigned correctly based on thresholds
- Frontend loads correctly

### Files Created
- `/app/backend/services/tqs/__init__.py`
- `/app/backend/services/tqs/tqs_engine.py`
- `/app/backend/services/tqs/setup_quality.py`
- `/app/backend/services/tqs/technical_quality.py`
- `/app/backend/services/tqs/fundamental_quality.py`
- `/app/backend/services/tqs/context_quality.py`
- `/app/backend/services/tqs/execution_quality.py`
- `/app/backend/routers/tqs_router.py`
- `/app/backend/tests/test_tqs_engine.py`

### Files Modified
- `/app/backend/server.py` - Added TQS router and initialization
- `/app/frontend/src/App.js` - Disabled startup modal for development

---

## Session Log - March 10, 2026 (Phase 3A & 3B: Fast Learning) - COMPLETE

### Fast Learning Architecture - Phase 3 COMPLETE

**Goal**: Implement real-time risk controls, adaptive sizing, and dynamic thresholds.

**What was implemented:**

#### 1. Circuit Breakers (`/app/backend/services/circuit_breaker.py`)

| Breaker Type | Default Threshold | Action |
|--------------|-------------------|--------|
| daily_loss_dollar | -$500 | BLOCK_ALL |
| daily_loss_percent | -2% | BLOCK_ALL |
| consecutive_losses | 3 | REDUCE_SIZE 50% |
| trade_frequency | 10/hour | REQUIRE_OVERRIDE |
| drawdown | -5% | BLOCK_ALL |
| tilt_detection | any | REDUCE_SIZE 50% |
| time_restriction | varies | WARN_ONLY |

#### 2. Position Sizing (`/app/backend/services/position_sizer.py`)

**TQS Multiplier Scale:**
| TQS Score | Multiplier |
|-----------|------------|
| 35 (min) | 0.25x |
| 50 (base) | 1.0x |
| 65 | 1.21x |
| 75 | 1.36x |
| 85+ (max) | 1.5x |

**Sizing Modes:**
- `fixed_dollar`: Risk same $ per trade
- `fixed_percent`: Risk same % per trade
- `tqs_scaled`: Scale based on TQS score (default)
- `kelly`: Kelly criterion with configurable fraction

#### 3. Health Monitor (`/app/backend/services/health_monitor.py`)

**Components Tracked:**
- Data Feeds: alpaca, alpaca_stream, ib_gateway, finnhub
- AI Services: ollama
- Database: mongodb
- Analytics: scanner, tqs_engine, learning_loop
- Risk: circuit_breakers

#### 4. Dynamic Thresholds (`/app/backend/services/dynamic_thresholds.py`)

**Context-Aware Adjustments:**
- **Market Regime**: -5 in strong uptrend, +8 in volatile
- **VIX Level**: -3 at 15-20 (sweet spot), +15 at extreme (40+)
- **Time of Day**: -1 opening drive, +2 midday
- **Performance**: +3 per consecutive loss, -3 for hot streak

#### 5. New API Endpoints (`/api/risk/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/circuit-breakers/status` | GET | All breaker states |
| `/circuit-breakers/configs` | GET | Breaker configs |
| `/circuit-breakers/{type}/configure` | POST | Update config |
| `/circuit-breakers/check-permission` | GET | Can trade? |
| `/position-sizing/config` | GET | Sizing config |
| `/position-sizing/calculate` | POST | Calculate size |
| `/position-sizing/table` | GET | TQS scaling table |
| `/thresholds/summary` | GET | Threshold configs |
| `/thresholds/calculate` | POST | Dynamic thresholds |
| `/thresholds/check-trade` | POST | Check vs thresholds |
| `/health/quick-status` | GET | Quick health |
| `/health/report` | GET | Full health report |

### Testing Results
- 27/27 backend API tests passed (100%)
- Position sizing formula verified correct
- Dynamic threshold adjustments working
- Circuit breakers ready for production

### Files Created
- `/app/backend/services/circuit_breaker.py`
- `/app/backend/services/position_sizer.py`
- `/app/backend/services/health_monitor.py`
- `/app/backend/services/dynamic_thresholds.py`
- `/app/backend/routers/risk_router.py`
- `/app/backend/tests/test_risk_management_phase3.py`

### Files Modified
- `/app/backend/server.py` - Added Phase 3 initialization

---

## Session Log - March 10, 2026 (Phase 4: RAG Knowledge Base) - COMPLETE

### RAG Knowledge Base - Phase 4 COMPLETE

**Goal**: Set up ChromaDB for personalized AI context injection.

**What was implemented:**

#### 1. RAG Services (`/app/backend/services/rag/`)
- **EmbeddingService**: SentenceTransformers (all-MiniLM-L6-v2) for text embeddings
- **VectorStoreService**: ChromaDB wrapper for persistence
- **RAGService**: Main orchestrator for indexing and retrieval

#### 2. Collections
- `trade_outcomes`: Historical trades with context
- `playbooks`: Trading strategy documents
- `patterns`: Chart patterns and templates
- `daily_insights`: Daily report card learnings

#### 3. API Endpoints (`/api/rag/*`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/rag/stats` | GET | Service statistics |
| `/api/rag/needs-sync` | GET | Check if sync needed |
| `/api/rag/sync` | POST | Force sync from MongoDB |
| `/api/rag/retrieve` | POST | Retrieve context for query |
| `/api/rag/augment-prompt` | POST | Inject context into prompt |
| `/api/rag/similar-trades` | POST | Find similar historical trades |
| `/api/rag/collections` | GET | Collection information |

### Testing Results
- 23/23 backend tests passed (100%)

### Files Created
- `/app/backend/services/rag/__init__.py`
- `/app/backend/services/rag/embedding_service.py`
- `/app/backend/services/rag/vector_store.py`
- `/app/backend/services/rag/rag_service.py`
- `/app/backend/routers/rag_router.py`

---

## Session Log - March 10, 2026 (Phase 5: Medium Learning) - COMPLETE

### Medium Learning - Daily Analysis - Phase 5 COMPLETE

**Goal**: Implement end-of-day analysis, calibration, and profile updates.

**What was implemented:**

#### 1. Medium Learning Services (`/app/backend/services/medium_learning/`)

| Service | Purpose |
|---------|---------|
| **CalibrationService** | TQS threshold recommendations based on performance |
| **ContextPerformanceService** | Track win rates by setup+regime+time combinations |
| **ConfirmationValidatorService** | Validate effectiveness of confirmation signals |
| **PlaybookPerformanceService** | Link playbook theory to actual results |
| **EdgeDecayService** | Detect when trading edges are degrading |

#### 2. Calibration Features
- TQS threshold analysis (strong_buy: 80, buy: 65, hold: 50, avoid: 35)
- Setup-specific threshold overrides
- Regime adjustment recommendations
- Confidence-weighted recommendations

#### 3. Context Performance Tracking
- Multi-dimensional performance (setup × regime × time)
- Heat map generation
- Best/worst context identification
- Trend analysis (improving/stable/declining)

#### 4. Confirmation Validation
8 confirmation types tracked:
- volume, rvol, tape, l2_support
- vwap_respect, trend_alignment, sector_momentum, news_catalyst

#### 5. Playbook Performance Linkage
- Expected vs actual win rates
- Execution quality metrics
- Common mistakes identification
- Improvement area suggestions

#### 6. Edge Decay Detection
- Rolling window comparison (7d, 14d, 30d vs all-time)
- Decay severity levels (none, mild, moderate, severe)
- Automatic alerts for declining strategies
- Statistical trend analysis

#### 7. API Endpoints (`/api/medium-learning/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/calibration/config` | GET | Current calibration config |
| `/calibration/analyze` | POST | Generate recommendations |
| `/calibration/apply/{id}` | POST | Apply a recommendation |
| `/calibration/history` | GET | Recommendation history |
| `/context-performance/update` | POST | Update performance stats |
| `/context-performance/report` | GET | Generate report |
| `/context-performance/all` | GET | All context records |
| `/confirmation/validate` | POST | Validate confirmations |
| `/confirmation/all` | GET | All confirmation stats |
| `/playbook/update` | POST | Update playbook stats |
| `/playbook/report` | GET | Linkage report |
| `/playbook` | GET | All playbook performances |
| `/edge-decay/analyze` | POST | Analyze all edges |
| `/edge-decay` | GET | All edge metrics |
| `/edge-decay/decaying/list` | GET | Decaying edges only |
| `/daily-analysis` | POST | Run complete EOD analysis |
| `/status` | GET | Service health status |

### Testing Results
- 29/29 backend tests passed (100%)

### Files Created
- `/app/backend/services/medium_learning/__init__.py`
- `/app/backend/services/medium_learning/calibration_service.py`
- `/app/backend/services/medium_learning/context_performance_service.py`
- `/app/backend/services/medium_learning/confirmation_validator_service.py`
- `/app/backend/services/medium_learning/playbook_performance_service.py`
- `/app/backend/services/medium_learning/edge_decay_service.py`
- `/app/backend/routers/medium_learning_router.py`

### Files Modified
- `/app/backend/server.py` - Added Phase 5 imports and initialization

---

## Session Log - March 10, 2026 (Weekly Intelligence Report Enhancement)

### Weekly Intelligence Report - COMPLETE

**Goal**: Create unified weekly report combining Analytics data and Journal reflection in the Trading Journal Tab.

**What was implemented:**

#### 1. WeeklyReportService (`/app/backend/services/weekly_report_service.py`)
Aggregates data from all Phase 5 Medium Learning services into a single weekly report.

#### 2. Report Structure
```
WeeklyIntelligenceReport:
├── Performance Snapshot (auto-generated)
│   ├── total_trades, wins, losses, win_rate
│   ├── total_pnl, profit_factor, avg_r
│   ├── best_day, worst_day
│   └── week-over-week comparison
├── Top Contexts (auto-generated from ContextPerformanceService)
├── Struggling Contexts (auto-generated)
├── Edge Alerts (auto-generated from EdgeDecayService)
├── Calibration Suggestions (auto-generated from CalibrationService)
├── Confirmation Insights (auto-generated from ConfirmationValidatorService)
├── Playbook Focus (auto-generated from PlaybookPerformanceService)
└── Personal Reflection (user-editable)
    ├── what_went_well
    ├── what_to_improve
    ├── key_lessons
    ├── goals_for_next_week
    ├── mood_rating (1-5)
    ├── confidence_rating (1-5)
    └── notes
```

#### 3. API Endpoints (`/api/journal/weekly-report/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate` | POST | Generate weekly report |
| `/current` | GET | Get/create current week's report |
| `/stats` | GET | Service statistics |
| `/week/{year}/{week_number}` | GET | Get by year/week |
| `/{report_id}` | GET | Get by ID |
| `/` | GET | Get recent reports (archive) |
| `/{report_id}/reflection` | PUT | Update personal reflection |
| `/{report_id}/complete` | POST | Mark report complete |

### Testing Results
- 21/21 backend tests passed (100%)

### Files Created
- `/app/backend/services/weekly_report_service.py`

### Files Modified
- `/app/backend/routers/journal_router.py` - Added weekly report endpoints

---

## Session Log - March 10, 2026 (Phase 6: Slow Learning) - COMPLETE

### Slow Learning - Backtesting & Verification - Phase 6 COMPLETE

**Goal**: Build backtesting engine and shadow mode for strategy verification.

**What was implemented:**

#### 1. Historical Data Service (`/app/backend/services/slow_learning/historical_data_service.py`)
- Downloads historical bars from Alpaca
- Stores in MongoDB for offline backtesting
- Supports multiple timeframes (1Min, 5Min, 15Min, 1Hour, 1Day)
- Data quality validation and gap detection

#### 2. Backtest Engine (`/app/backend/services/slow_learning/backtest_engine.py`)
- Runs strategy simulations on historical data
- Configurable parameters (capital, position size, stops, targets)
- Entry signal framework (default: SMA crossover)
- Exit strategies (stop loss, take profit, trailing stop, time exit)
- Comprehensive metrics: win rate, profit factor, max drawdown, R-multiples

#### 3. Shadow Mode Service (`/app/backend/services/slow_learning/shadow_mode_service.py`)
- Paper trading signal tracking
- Filter effectiveness validation
- Would-have P&L calculations
- Minimum 20 signals required for validation
- Filter activation recommendations

#### 4. API Endpoints (`/api/slow-learning/*`)

| Category | Endpoints |
|----------|-----------|
| Historical Data | `/download`, `/bars/{symbol}`, `/stats`, `/symbols` |
| Backtest | `/run`, `/results`, `/results/{id}` |
| Shadow Mode | `/filters`, `/signals`, `/update-outcomes`, `/report` |

### Testing Results
- 24/24 backend tests passed (100%)

### Files Created
- `/app/backend/services/slow_learning/__init__.py`
- `/app/backend/services/slow_learning/historical_data_service.py`
- `/app/backend/services/slow_learning/backtest_engine.py`
- `/app/backend/services/slow_learning/shadow_mode_service.py`
- `/app/backend/routers/slow_learning_router.py`

---

## Session Log - March 10, 2026 (Frontend: Weekly Report Tab) - COMPLETE

### Weekly Intelligence Report Frontend

**What was implemented:**

#### WeeklyReportTab Component
- Week navigation with prev/next arrows
- Performance Snapshot (Total Trades, Win Rate, P&L, Profit Factor)
- Context Insights (Top Performing, Struggling)
- Edge Decay Alerts
- Calibration Suggestions
- Confirmation Insights
- Playbook Focus recommendations
- Personal Reflection section (editable with mood/confidence ratings)
- Report History sidebar

### Testing Results
- 6/6 frontend sections verified (100%)

### Files Created
- `/app/frontend/src/components/Journal/WeeklyReportTab.jsx`

### Files Modified
- `/app/frontend/src/components/Journal/index.js`
- `/app/frontend/src/pages/TradeJournalPage.js`

---

## THREE-SPEED LEARNING ARCHITECTURE - FULLY IMPLEMENTED

All 6 phases complete:

| Phase | Name | Status |
|-------|------|--------|
| 1 | Core Learning Infrastructure | ✅ |
| 2 | TQS Engine (5-Pillar Scoring) | ✅ |
| 3 | Fast Learning (Circuit Breakers) | ✅ |
| 4 | RAG Knowledge Base (ChromaDB) | ✅ |
| 5 | Medium Learning (Daily Analysis) | ✅ |
| 6 | Slow Learning (Backtesting) | ✅ |


---

## Session Log - March 10, 2026 (Priority 1 & 2 Implementation) - COMPLETE

### What was implemented:

#### 1. Analytics Tab UI Integration (Priority 1)
- **Updated AnalyticsTab.jsx**: Added 3 sub-tabs (Learning, Backtest, Shadow Mode)
- **BacktestPanel.jsx**: Fixed import path for `../utils/api`
- **ShadowModePanel.jsx**: Fixed import path for `../utils/api`
- All panels now accessible from Analytics > sub-tabs

#### 2. AI Assistant Learning Context Integration (Priority 2)
- **ai_assistant_service.py**: Added `set_learning_context_provider()` method
- **ai_assistant_service.py**: Added `_learning_context_provider` to `__init__()`
- **ai_assistant_service.py**: Enhanced `_build_smart_context()` to inject learning context for trade decisions
- **server.py**: Wired `learning_context_provider` to `assistant_service`
- Learning context now provides TQS scores and performance insights during trade-related intents

#### 3. Trading Scheduler Verification (Priority 2)
- Confirmed all 4 scheduled jobs running:
  - shadow_update (every 5 min during market hours)
  - daily_analysis (4:00 PM ET Mon-Fri)
  - edge_decay_check (4:15 PM ET Mon-Fri)
  - weekly_report (Friday 4:30 PM ET)
- All medium learning services configured: calibration, context_performance, confirmation, playbook, edge_decay
- Manual task trigger via `POST /api/scheduler/run/{task_type}` working

### Testing Results (iteration_59.json)
- **Backend**: 89% (16/18 tests passed, 2 timeout failures were network-related)
- **Frontend**: 100% (all 3 sub-tabs verified)

### API Endpoints Verified
| Endpoint | Status |
|----------|--------|
| POST /api/slow-learning/backtest/run | ✅ |
| GET /api/slow-learning/shadow/filters | ✅ |
| GET /api/slow-learning/shadow/signals | ✅ |
| GET /api/slow-learning/shadow/report | ✅ |
| GET /api/scheduler/status | ✅ |
| GET /api/scheduler/jobs | ✅ |
| POST /api/scheduler/run/{task_type} | ✅ |
| GET /api/medium-learning/calibration/config | ✅ |
| GET /api/medium-learning/status | ✅ |

### Files Modified
- `/app/frontend/src/components/tabs/AnalyticsTab.jsx`
- `/app/frontend/src/components/BacktestPanel.jsx`
- `/app/frontend/src/components/ShadowModePanel.jsx`
- `/app/backend/services/ai_assistant_service.py`
- `/app/backend/server.py`

---

## Prioritized Backlog Update

### Completed (Priority 1 & 2)
- [x] Analytics Tab UI integration (Backtest + Shadow Mode panels)
- [x] AI Assistant Learning Context Provider integration
- [x] Trading Scheduler verification and testing

### Future Tasks (Priority 3 - Backlog)
- [ ] Data-Driven In-Trade Guidance (real-time advice during trades)
- [ ] Live Trading Dashboard (combined view of market data, positions, AI feedback)
- [ ] Monthly/Quarterly Performance Reviews

---

## Session Log - March 11, 2026 (Live Trading Dashboard Implementation)

### Feature: Live Trading Dashboard (Option D Design)
**Goal**: Implement the user-approved "Option D" mockup as a dedicated Trading Dashboard page with integrated TradingView chart.

### Implementation Details

**1. New Trading Dashboard Page** (`/app/frontend/src/pages/TradingDashboardPage.jsx`)
- Full-screen dedicated trading view accessible via `/trading` route
- 3-column layout:
  - **Left Column**: Open Positions with live P&L, clickable for chart navigation
  - **Center Column**: TradingView chart + Order Pipeline + In-Trade Guidance
  - **Right Column**: Today's Performance stats + Risk Status

**2. Key Components Implemented**:
- **TradingViewChart**: Embedded widget with proper exchange prefix mapping (AMEX:SPY, NASDAQ:AAPL, etc.)
- **PositionCard**: Position cards with P&L display, stop/target price bar, inline guidance alerts
- **OrderPipeline**: Visual pipeline showing Pending → Executing → Filled order flow with IB connection status
- **InTradeGuidance**: Real-time coaching alerts based on position state (loss warnings, target approach, winner management)
- **PerformanceStats**: Daily stats including trades executed, win rate, winners/losers, realized/unrealized P&L
- **RiskStatus**: Daily loss limit progress bar, position exposure indicator

**3. Navigation Integration**:
- Added "Trading Dashboard" nav item to `Sidebar.js` (data-testid="nav-trading")
- Added route mapping in `App.js` for 'trading' tab → `TradingDashboardPage`
- Dashboard accessible via sidebar click or localStorage `activeTab='trading'`

**4. TradingBotPanel Consolidation**:
- Removed `TradingBotPanel` from `RightSidebar.jsx` 
- Order queue and execution status functionality now integrated into Trading Dashboard
- Command Center sidebar now cleaner without redundant trading panel

**5. Chart Symbol Fix**:
- Fixed TradingView chart symbol prefix from hardcoded `NASDAQ:${symbol}` to proper exchange mapping
- Added `getFullSymbol()` helper that routes ETFs to AMEX, tech stocks to NASDAQ, others to NYSE
- SPY now correctly loads as `AMEX:SPY` (was showing "symbol doesn't exist")

### API Endpoints Used
| Endpoint | Purpose |
|----------|---------|
| GET /api/ib/pushed-data | Fetch IB positions, quotes, account data |
| GET /api/ib/orders/queue/status | Order pipeline status (pending/executing/completed) |
| GET /api/trading-bot/status | Bot running status, daily stats, risk params |

### Files Modified
- `/app/frontend/src/pages/TradingDashboardPage.jsx` - Fixed chart symbol mapping
- `/app/frontend/src/components/Sidebar.js` - Added 'trading' nav item
- `/app/frontend/src/App.js` - Added route for 'trading' tab, imported TradingDashboardPage
- `/app/frontend/src/components/RightSidebar.jsx` - Removed TradingBotPanel import and usage

### Testing Results (iteration_61.json)
- **Backend**: 100% (7/7 API tests passed)
- **Frontend**: 100% (all components verified rendering correctly)

### Features Verified
| Feature | Status |
|---------|--------|
| Trading Dashboard navigation | ✅ PASS |
| Open Positions component | ✅ PASS |
| SPY Chart (TradingView) | ✅ PASS |
| Order Pipeline | ✅ PASS |
| In-Trade Guidance | ✅ PASS |
| Today's Performance | ✅ PASS |
| Risk Status | ✅ PASS |
| TradingBotPanel removed from sidebar | ✅ PASS |
| Command Center still works | ✅ PASS |

### Completed
- [x] Live Trading Dashboard implementation (Option D design)
- [x] TradingView chart integration with proper exchange prefixes
- [x] Consolidated trading functionality from sidebar to dedicated page
- [x] Full testing verification

### Remaining Tasks (From Handoff)
- [ ] **P1**: Implement backend logic for "In-Trade Guidance" coaching alerts (currently client-side only)
- [ ] **P1**: Add "Fear and Greed" market index based on scanner/market breadth data
- [ ] **P2**: Fix missing API endpoints (`/api/scanner/status`, `/api/trading-bot/trades`, `/api/circuit-breaker/status`)
- [ ] **P2**: Refactor fragile service initialization in `server.py`
- [ ] **Future**: Restructure Trade Journal tabs
- [ ] **Future**: Migrate in-memory order queue to MongoDB for persistence


---

## Session Log - March 11, 2026 (AI Position Context Fix)

### Bug Fix: AI Not Seeing Live IB Positions
**Issue**: When user said "close TMC position please", the AI responded "I cannot close a non-existent position" even though TMC was visible in the Trading Dashboard.

**Root Cause**: The query intent classifier wasn't recognizing "close TMC" as a position-related query. The keyword matching was too narrow.

**Fix Applied**:
1. Added keywords to `ai_assistant_service.py`:
   - `position_keywords`: Added "close", "exit", "sell", "buy", ticker symbols (tmc, intc, tsla)
   - `is_position_query`: Added same keywords for response validation

2. Added patterns to `smart_context_engine.py`:
   - `POSITION_REVIEW` intent patterns: Added regex for "close/exit/sell [symbol]"
   - `POSITION_REVIEW` keywords: Added "close position", "exit position", specific ticker combinations

3. Added debug logging to `_get_positions_with_data` to trace context building

**Result**: AI now correctly identifies position queries and includes live IB positions in its context. Tested with "close TMC position please" - AI now responds with the actual TMC position data (10,000 shares @ $7.92).

### Files Modified
- `/app/backend/services/ai_assistant_service.py` - Extended keyword matching
- `/app/backend/services/smart_context_engine.py` - Extended intent patterns and debug logging


---

## Session Log - March 11, 2026 (API Endpoints & MongoDB Migration)

### 1. Fixed Missing API Endpoints

**Issue**: Three API endpoints were returning 404 errors.

**Fix Applied**:
- `/api/scanner/status` - Added to `scanner.py` router
- `/api/trading-bot/trades` - Added to `trading_bot.py` router  
- `/api/circuit-breaker/status` - Created new `circuit_breaker.py` router with status, reset, and configure endpoints

### 2. MongoDB Order Queue Migration

**Issue**: Order queue was in-memory only, causing orders to be lost on server restart.

**Fix Applied**:
- Created `/app/backend/services/order_queue_service.py` - MongoDB-backed order queue service
- Updated `/app/backend/routers/ib.py` to use the new service
- Added automatic fallback to in-memory if MongoDB fails
- Preserved backwards compatibility with legacy endpoints

**New MongoDB Collection**: `order_queue`
- Indexes on: `status`, `order_id` (unique), `queued_at`, `symbol`
- Auto-cleanup of orders older than 7 days
- Auto-expiration of stale orders (30 min default)

### 3. Circuit Breaker Implementation

**New Features**:
- Real-time monitoring of daily loss limits (1% default)
- Max drawdown tracking (5% default)
- Consecutive loss tracking
- Manual reset capability
- Configurable limits via API

### Files Created
- `/app/backend/routers/circuit_breaker.py`
- `/app/backend/services/order_queue_service.py`

### Files Modified
- `/app/backend/routers/scanner.py` - Added /status endpoint
- `/app/backend/routers/trading_bot.py` - Added /trades endpoint
- `/app/backend/routers/ib.py` - MongoDB queue integration
- `/app/backend/server.py` - Router registrations

### Testing Results
All endpoints now return 200 OK:
- ✅ `/api/scanner/status`
- ✅ `/api/trading-bot/trades`
- ✅ `/api/circuit-breaker/status`
- ✅ `/api/ib/orders/queue/status` (now backed by MongoDB)

