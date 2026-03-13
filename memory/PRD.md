# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with AI trading coach, autonomous trading bot, and mutual learning loop.

---

## BUG FIX (March 13, 2026)

### Positions Not Showing in SentCom Panel ✅ FIXED

**Problem:** "Our Positions" panel was showing empty even though there were 8 open trades in the trading bot.

**Root Cause:** The `get_our_positions()` method in `sentcom_service.py` was trying to get trades from `trading_bot.get_status()["open_trades"]`, but that returns just a count (integer), not the actual list of trades.

**Fix:** Changed to call `trading_bot.get_open_trades()` directly, which returns the full list of trade objects. Also improved P&L calculation to handle short positions correctly.

**Result:** All 8 positions now display with:
- Symbol, quantity, entry price, current price
- P&L in dollars and percentage (red/green coloring)
- Stop and target prices
- Mini price chart for each position

---

## LATEST UPDATES (March 13, 2026)

### P0 COMPLETE: Chat Conversational Context & Bot Control Mechanisms

**Status:** ✅ COMPLETE - Tested and Verified (iteration_86.json - 100% backend, 100% frontend)

**P0 Task 1: Chat Conversational Context** ✅ COMPLETE
- **Backend Changes:**
  - `sentcom_service.py`: chat() method now builds recent_history from _chat_history and passes to orchestrator.process()
  - `orchestrator.py`: process() method accepts chat_history parameter and stores it in session context
  - `coach_agent.py`: _build_coaching_prompt_async() includes conversation_history section in prompts
  - Conversation context formatted as "Trader: ..." / "SentCom: ..." pairs for the last 6 messages
- **Result:** AI responses now maintain conversational continuity and can reference previous discussion points

**P0 Task 2: Bot Control Mechanisms** ✅ COMPLETE
- **Backend Endpoints (already existed, verified working):**
  - `POST /api/trading-bot/start` - Start the bot
  - `POST /api/trading-bot/stop` - Stop the bot
  - `POST /api/trading-bot/mode/{mode}` - Change mode (autonomous/confirmation/paused)
  - `POST /api/trading-bot/risk-params` - Update risk parameters
- **Frontend Enhancements:**
  - `useTradingBotControl` hook now includes `updateRiskParams()` function
  - Added `RiskControlsPanel` component with inputs for:
    - Risk Per Trade (%)
    - Max Daily Loss ($)
    - Max Positions
    - Min R:R Ratio
  - Settings panel now has two tabs: "Trading Mode" and "Risk Controls"
  - Toast notifications added for mode changes and risk param updates
  - **NEW: Quick Risk Profile Presets** (March 13, 2026):
    - 🛡️ **Conservative**: 0.5% risk/trade, $250 max daily loss, 3 positions, 3:1 R:R
    - ⚖️ **Moderate**: 1% risk/trade, $500 max daily loss, 5 positions, 2:1 R:R
    - 🔥 **Aggressive**: 2% risk/trade, $1000 max daily loss, 8 positions, 1.5:1 R:R
  - Active preset auto-detected and highlighted when params match
- **Result:** Users can fully control the bot from the SentCom interface with one-click risk profiles

---

## RECENT UPDATES (March 13, 2026)

### P0 ACTIVE: SentCom Unification Project

**Status:** ✅ COMPLETE - Phase 1, 2, 3 & 3.5 Done

**Project Goal:** Unify the AI Assistant and Bot Brain into a single "SentCom" (Sentient Command) that uses "we" language throughout, creating a partnership feeling between the trader and the AI system.

**Phase 1: Backend & Frontend Voice Unification** ✅ COMPLETE
- Updated all backend agent prompts (coach_agent.py, analyst_agent.py, brief_me_agent.py) to use "we/our" voice
- Updated frontend fallback messages in BotBrainPanel.jsx and NewDashboard.jsx
- Changed "SETUPS I'M WATCHING" → "SETUPS WE'RE WATCHING"
- Changed "TEAM BRAIN" → "SENTCOM" throughout the UI
- EnhancedTickerModal already has "OUR TAKE" language and GlassCard V2 styling

**Phase 2: Backend Wiring** ✅ COMPLETE
- Created `/app/backend/services/sentcom_service.py` - Unified orchestrator with "we" voice
- Created `/app/backend/routers/sentcom.py` with endpoints:
  - GET `/api/sentcom/health` - Health check
  - GET `/api/sentcom/status` - Full operational status
  - GET `/api/sentcom/stream` - Unified message stream
  - POST `/api/sentcom/chat` - Chat interface
  - GET `/api/sentcom/context` - Market context
  - GET `/api/sentcom/positions` - Our positions
  - GET `/api/sentcom/setups` - Setups we're watching
  - GET `/api/sentcom/alerts` - Recent alerts
- Wired into server.py with service injection

**Phase 3: UI Implementation** ✅ COMPLETE
- Created `/app/frontend/src/components/SentCom.jsx` - Production component
- **Compact Mode**: Embedded in Command Center, replacing BotBrainPanel + AI Assistant
- Full Page Mode: Accessible via sidebar "SentCom" menu item
- Wired to real `/api/sentcom/*` endpoints with polling hooks
- Removed separate AICommandPanel from right sidebar (chat now in SentCom)

**Phase 3.5: Trading Bot Header Merge & Glassy Styling** ✅ COMPLETE (March 13, 2026)
- **Merged Trading Bot Panel Header into SentCom Header:**
  - Added `useTradingBotControl()` hook for bot status (start/stop, mode changes)
  - Added `useIBConnectionStatus()` hook for IB connection monitoring
  - Unified header now shows: SENTCOM branding, CONNECTED/OFFLINE status, Bot Status (ACTIVE/STOPPED), Mode (AUTONOMOUS/CONFIRMATION/PAUSED), IB status (IB LIVE/OFFLINE), Order Pipeline (Pending→Executing→Filled), Settings button, Start/Stop button
  - Added Trading Mode selector panel (collapsible via Settings button)
- **Applied Glassy Mockup Styling:**
  - Glass-morphism effects: `bg-gradient-to-br from-white/[0.08] to-white/[0.02]`, `backdrop-blur-xl`, `border border-white/10`
  - Ambient background effects with cyan/violet gradient blurs
  - Updated "Our Positions" panel with glassy styling and sparklines
  - Updated "Setups We're Watching" panel with glassy styling
  - Updated Live Team Stream with enhanced message styling
  - Enhanced chat input with improved placeholder and send button
  - Improved Position Detail Modal with more data and "Our Take" section
- **Simplified DashboardHeader:**
  - Changed from "TRADING BOT" branding to "Command Center" branding
  - Removed redundant bot status (now in SentCom)
  - Added AI Credits indicator
  - Shows: Command Center branding, AI Credits, Session status, Account, Buying Power, Today P&L, Open P&L, Time
  - Applied glassy gradient background

**Phase 3.6: Full Functionality Integration** ✅ COMPLETE (March 13, 2026)
- **Connected ALL Bot Brain & AI Assistant Functionality into SentCom:**
  - **Bot Controls**: Start/Stop, Mode changes (Autonomous/Confirmation/Paused) via `/api/trading-bot/*` endpoints
  - **Quick Actions** (6 total):
    - Performance → `/api/sentcom/chat` → Trading performance analysis
    - News → `/api/sentcom/chat` → Market news/headlines
    - Brief → `/api/assistant/coach/morning-briefing` → 3-point coaching
    - Rules → `/api/assistant/coach/rule-reminder` → Trading rules
    - Summary → `/api/assistant/coach/daily-summary` → Watchlist + coaching
    - Check Trade → Opens trade analysis form
  - **Check Trade Form**: Symbol, Entry $, Stop $ fields → Calls `/api/assistant/coach/check-rules` and `/api/assistant/coach/position-size` in parallel
  - **Chat**: Full AI chat via `/api/sentcom/chat` → Routes to appropriate agent (coach, analyst, trader)
  - **Unified Stream**: Displays user messages ("YOU") and AI responses ("SENTCOM") with timestamps
  - **Stop Fix Panel**: Shows alert when risky stops detected, "Fix All Stops" button calls `/api/trading-bot/fix-all-risky-stops`
- **Backend Testing**: 17/17 tests passed (100%)
- **Frontend Testing**: 14/14 features verified (100%)

**V2 Interactive Mockups (For Reference):**
- `/app/frontend/src/pages/TeamBrainMockupsV2.jsx` - Now labeled "SentCom Mockups"
- Accessible via sidebar "SentCom Mockups" menu item

**Next: Phase 4 - Deprecation & Polish** ✅ COMPLETE (March 13, 2026)
1. ~~Remove old AIAssistant.jsx component~~ ✅ REMOVED
2. ~~Remove BotBrainPanel.jsx~~ ✅ REMOVED  
3. ~~Remove AICommandPanel.jsx~~ ✅ REMOVED
4. Updated AICoachTab.jsx to use SentCom instead of AICommandPanel
5. Build verified successful - no broken imports
6. App tested and working post-deprecation

---

### Previous P0 Features Complete - Smart Strategy Filtering & One-Click Stop Fix

**Status:** ✅ COMPLETE - Tested and Verified (iteration_83.json - 100% backend, 100% frontend)

**Features Implemented:**

#### Smart Strategy Filtering ✅
The bot now adjusts trade decisions based on user's historical win rate for each setup type:

1. **Core Logic in `trading_bot_service.py`:**
   - `get_strategy_historical_stats()` - Fetches win rate, sample size, avg R from enhanced scanner
   - `_evaluate_strategy_filter()` - Decision tree: SKIP, REDUCE_SIZE, REQUIRE_HIGHER_TQS, or PROCEED
   - `_add_filter_thought()` - Logs reasoning to Bot's Thoughts stream

2. **Filtering Thresholds (configurable via API):**
   - Win rate < 35%: SKIP trade entirely
   - Win rate 35-45%: REDUCE_SIZE to 50%
   - Win rate 45-50%: REQUIRE_HIGHER_TQS (75+) to proceed
   - Win rate > 55%: PROCEED with normal sizing

3. **New API Endpoints:**
   - `GET /api/trading-bot/smart-filter/config` - Get filter configuration
   - `POST /api/trading-bot/smart-filter/config` - Update filter settings
   - `GET /api/trading-bot/smart-filter/thoughts` - Get filtered trade reasoning
   - `GET /api/trading-bot/smart-filter/strategy-stats/{setup_type}` - Get stats for setup
   - `GET /api/trading-bot/smart-filter/all-strategy-stats` - Get all 35 strategy stats

4. **Bot's Thoughts Integration:**
   - Filter reasoning appears with new action types: `filter_skip`, `filter_reduce`, `filter_proceed`
   - Styled badges: FILTERED OUT (amber), REDUCED SIZE (purple), GREENLIGHT (emerald)
   - Shows win rate percentage for each filter decision

#### One-Click Stop Fix ✅
Quick fix for risky stop-loss placements:

1. **New API Endpoints:**
   - `POST /api/trading-bot/fix-stop/{trade_id}` - Fix single trade's stop
   - `POST /api/trading-bot/fix-all-risky-stops` - Fix all risky stops at once

2. **StopFixActions Component (BotBrainPanel.jsx):**
   - Detects stop_warning thoughts with critical/warning severity
   - Shows "Fix All Stops" button when risky stops detected
   - Displays fix results with symbol, old_stop → new_stop, improvement %
   - Loading state during fix operation

**Files Modified:**
- `/app/backend/services/trading_bot_service.py` - Smart filtering methods
- `/app/backend/routers/trading_bot.py` - 8 new endpoints
- `/app/backend/server.py` - Wired scanner ↔ trading bot for stats access
- `/app/frontend/src/components/BotBrainPanel.jsx` - StopFixActions, filter styling

---

### P1 & P2 Features Complete

**Status:** ✅ COMPLETE - Tested and Verified (iteration_82.json - 94% backend, 100% frontend)

**Features Implemented:**

#### A. Deep Analysis API Integration ✅
- `askAIAboutStock` function triggers AI assistant with context-aware prompts
- Supports: analyze, buy, sell, quality actions
- Properly wired through useCommandCenterData hook

#### B. AI Proactive Intelligence ✅
- **ProactiveIntelligence component** in Bot Brain panel
- Generates alerts for:
  - Setup Near Trigger (within 2% of entry)
  - Profit-Taking Suggestions (positions up 3-5%)
  - Strong Runners (positions up 5%+)
  - Market Regime warnings (RISK-OFF with open positions)
  - Session alerts (Power Hour, Market Closing)
- Alerts displayed with colored badges and click-to-ticker functionality

#### D. Exit Optimization (Trailing Stops) ✅
- **New endpoints:**
  - `POST /api/smart-stops/calculate-trailing-stop` - Calculate optimal trail
  - `POST /api/smart-stops/auto-trail-positions` - Batch analyze all positions
- **Trailing modes:** ATR, Percent, Chandelier, Parabolic
- Returns: new_stop, should_trail, reasoning, lock_in_profit_pct

#### E. Bot's Take for Non-Position Tickers ✅
- **HypotheticalBotTakeCard component** in EnhancedTickerModal
- Shows "IF I WERE TO TRADE THIS..." analysis
- Calculates hypothetical entry, stop, target based on analysis
- Direction: LONG, SHORT, or PASS with reasoning

#### F. Live Chart Data ✅
- Historical data endpoint `/api/ib/historical/{symbol}` working
- Charts tab loads candlestick data from IB Gateway (with Alpaca fallback)
- Timeframe buttons: 1m, 5m, 15m, 1h, D

**UI Improvements:**
- **Active Positions panel** - Compact single-row card layout
- **Bot Brain panel** - Expanded height, thoughts + order pipeline + proactive alerts + in-trade guidance

**Files Modified:**
- `/app/backend/routers/smart_stops.py` - New trailing stop endpoints
- `/app/frontend/src/components/NewDashboard.jsx` - Compact ActivePositionsCard
- `/app/frontend/src/components/BotBrainPanel.jsx` - ProactiveIntelligence component
- `/app/frontend/src/components/EnhancedTickerModal.jsx` - HypotheticalBotTakeCard

---

### Enhanced "Brief Me" Feature Complete

**Status:** ✅ COMPLETE - Tested and Verified (iteration_81.json - 92%)

**New Features Added:**

1. **Real News Headlines & Catalysts**
   - Fetches from IB Gateway (primary) or Finnhub (fallback)
   - 8+ market news headlines displayed
   - Catalyst extraction: earnings, analyst, fed, economic, deal, product types
   - Each catalyst shows type, ticker, headline, and impact level

2. **News Sentiment Analysis**
   - Bullish/Bearish/Neutral market tone indicator
   - Displayed as colored badge in quick summary
   - Derived from headline keyword analysis

3. **Market Themes Extraction**
   - Auto-detects: Inflation Data, AI/Technology, Energy/Oil, Fed/Rates, etc.
   - Displayed as theme badges in quick summary
   - Helps identify market-moving narratives

4. **Sector Rotation Analysis**
   - Tracks 11 sector ETFs (XLK, XLF, XLE, XLV, XLI, XLC, XLY, XLP, XLU, XLRE, XLB)
   - Shows top 3 leaders and bottom 3 laggards with % change
   - Rotation signals: risk_on_growth, risk_off_defensive, cyclical_rotation, broad_selling, broad_buying, mixed_rotation
   - Strategy recommendations based on rotation

5. **Earnings Calendar Integration**
   - Warns about upcoming earnings for watchlist stocks
   - Shows date, timing (BMO/AMC), and EPS estimates
   - Position sizing advice before earnings

**Files Modified:**
- `/app/backend/agents/brief_me_agent.py` - Complete rewrite with parallel data fetching, timeouts, and enhanced sections
- `/app/backend/routers/agents.py` - Injected news_service into BriefMeAgent
- `/app/frontend/src/components/BriefMeModal.jsx` - Added News Tone, Top Sector, Catalyst badges; themes row; detailed sections for news, catalysts, sectors, earnings

**Testing Results (iteration_81.json):**
- ✅ API returns news headlines (8+ items): PASS
- ✅ News themes extracted: PASS
- ✅ News sentiment analysis: PASS  
- ✅ Sector rotation leaders/laggards: PASS
- ✅ Sector rotation signal: PASS
- ✅ Catalysts extracted: PASS
- ✅ Quick response time ~15s: PASS
- ✅ Frontend modal opens: PASS
- ✅ Quick summary badges: PASS
- ✅ Themes row: PASS
- ✅ Toggle to detailed view: PASS
- ⚠️ Detailed response time ~52s: NEEDS OPTIMIZATION (target was 40s)

---

### Custom Chart & In-Trade Guidance Complete

**Status:** ✅ COMPLETE - Tested and Verified (iteration_80.json - 100%)

**1. Custom Proprietary Bot Performance Chart (SVG-based)**
- Removed TradingView dependency
- Built with pure SVG/React (no external charting library)
- Features:
  - Green gradient area fill for equity curve
  - Y-axis dollar labels with auto-scaling
  - X-axis time labels
  - Hover tooltips with trade details
  - Trade markers (green=win, red=loss)
  - Time range buttons: Today, Week, Month, YTD, All
  - Stats: Trades, Win Rate, Open, Unrealized, Realized, Best, Worst

**2. In-Trade Guidance Alerts in Bot's Brain**
- Position-specific recommendations based on:
  - 🛑 **STOP WARNING**: Position within 2% of stop loss
  - 🎯 **TARGET ZONE**: Position within 3% of target
  - 🚀 **RUNNING**: Position up 5%+ (suggest trailing stop)
  - ⚠️ **UNDERWATER**: Position down 3%+ (review thesis)
- Clickable alerts → opens ticker modal for that symbol
- Auto-prioritized by urgency

**Files Modified:**
- `/app/frontend/src/components/BotPerformanceChart.jsx` - Complete rewrite with CustomEquityChart SVG component
- `/app/frontend/src/components/BotBrainPanel.jsx` - Added InTradeGuidance component

---

### Dashboard Integration Complete: TradingDashboard → Command Center

**Status:** ✅ COMPLETE - Tested and Verified (iteration_79.json - 100%)

**Features Integrated from TradingDashboardPage:**

1. **Account Data in Header (Auto-Updating)**
   - Account Value: Shows Net Liquidation value
   - Buying Power: Shows available trading capital
   - Auto-refresh every 5 seconds from `/api/ib/account/summary`
   - Shows $0 when IB Gateway offline (expected)

2. **Risk Status Bar**
   - Daily Loss Limit: Progress bar showing % of limit used
   - Position Exposure: Shows X/10 positions open
   - IB Connection Status badge (LIVE/OFFLINE)
   - Visual alerts when daily limit is hit

3. **Order Pipeline in Bot's Brain**
   - Visual flow: Pending → Executing → Filled
   - Real-time updates from `/api/ib/orders/queue/status`
   - Shows order counts at each stage
   - Auto-refresh every 3 seconds

4. **Compact Header Redesign**
   - Session/Regime/Brief Me now compact badges
   - More space for account data and P&L
   - Cleaner, more data-dense layout

**Files Modified:**
- `/app/frontend/src/components/NewDashboard.jsx` - Complete header redesign
- `/app/frontend/src/components/BotBrainPanel.jsx` - Added OrderPipeline component

**Testing Results (iteration_79.json):**
- ✅ All 11 features verified: 100% pass rate
- ✅ Position card → Modal regression test: PASS
- ✅ Modal features (Buy/Short, tabs, analysis): PASS

---

### P0 COMPLETE: Ticker Modal Click Bug Fixed

**Status:** ✅ COMPLETE - Tested and Verified (iteration_78.json - 100%)

**Issue:** Clicking a position card in the `NewDashboard.jsx` did not open the `EnhancedTickerModal`. The modal worked when triggered via a test button but failed when clicking directly on position cards.

**Root Cause:** The original `motion.div` (from framer-motion) wrapper was not properly forwarding click events to the React onClick handler.

**Fix Applied:**
- Changed position card from `motion.div` to semantic `<button>` element
- Button provides native click handling that works reliably
- Removed unnecessary debug logging after fix confirmed

**Files Modified:**
- `/app/frontend/src/components/NewDashboard.jsx` - ActivePositionsCard now uses `<button>` for position cards
- `/app/frontend/src/hooks/useTickerModal.jsx` - Cleaned up debug logging

**Testing Results (iteration_78.json):**
- ✅ Position card click opens modal: PASS
- ✅ Ticker symbol in header: PASS - Shows "LABD" with badges
- ✅ Overview tab: PASS
- ✅ Chart tab: PASS  
- ✅ Research tab: PASS
- ✅ Buy/Sell buttons: PASS
- ✅ Console logs confirm click handler: PASS

---

### P1 IN PROGRESS: Trader Dashboard Tab Evaluation

**Status:** 🔄 EVALUATED - Recommendation: KEEP (Not Deprecate)

**Analysis of TradingDashboardPage.jsx (755 lines):**

The "Trading Dashboard" tab (`TradingDashboardPage.jsx`) contains unique features NOT present in `NewDashboard`:

| Feature | In NewDashboard | In TradingDashboard | Notes |
|---------|-----------------|---------------------|-------|
| Bot Performance Chart | ✅ | ❌ | NewDashboard has it |
| Bot's Brain Panel | ✅ | ❌ | NewDashboard has it |
| Active Positions | ✅ | ✅ | Both have |
| Order Pipeline | ❌ | ✅ | **Unique to TradingDashboard** |
| In-Trade Guidance | ❌ | ✅ | **Unique to TradingDashboard** |
| Risk Status | ❌ | ✅ | **Unique to TradingDashboard** |
| TradingView Chart | ❌ | ✅ | NewDashboard uses LightweightCharts |
| AI Assistant | ✅ | ❌ | NewDashboard has it |
| Market Regime Widget | ✅ | ❌ | NewDashboard has it |

**Unique TradingDashboard Features:**
1. **Order Pipeline** - Visual flow of orders: Pending → Executing → Filled
2. **In-Trade Guidance** - Position-specific recommendations and alerts
3. **Risk Status** - Daily loss limit tracking, position exposure monitoring
4. **TradingView Chart** - Full embedded TradingView widget

**Recommendation:** 
Do NOT deprecate `TradingDashboardPage`. Instead:
- Keep it as a dedicated "Position Management" view
- Consider renaming tab from "Trading Dashboard" to "Trade Monitor" or "Position Manager"
- Both dashboards serve different purposes:
  - `NewDashboard` (AI Coach tab): Bot-centric, briefing, analysis
  - `TradingDashboard`: Execution-focused, position management, risk monitoring

---

## 🎯 NEXT SESSION: Smart Strategy Filtering

**Priority:** P2 - MEDIUM

**What to Implement:**
Build smart strategy filtering directly into the bot's AI reasoning, NOT as a separate UI filter.

**How It Works:**
1. When bot evaluates a setup, query learning_provider for user's historical stats on that setup type
2. Factor historical win rate into trade decision:
   - High WR (>55%): Proceed normally
   - Medium WR (45-55%): Require higher TQS threshold
   - Low WR (<45%): Skip or reduce size significantly
3. Surface reasoning in bot's thoughts:
   - "Taking this breakout - you're 67% on these"
   - "Passing on this pullback - you're only 38% historically"

**Files to Modify:**
- `/app/backend/services/trading_bot_service.py` - Trade evaluation logic
- `/app/backend/agents/trade_executor_agent.py` - Decision making
- `/app/backend/services/slow_learning_service.py` - Query historical stats

**Data Already Available:**
- learning_provider tracks win rate by setup type
- learning_provider tracks win rate by regime
- learning_provider tracks average R-multiple by setup

**User Preference:** Bake into bot reasoning, not UI filters. Bot should explain WHY it passed on setups.

---

## 📋 FULL PRIORITY ROADMAP (March 2026)

### 🔴 P0 - CRITICAL (Active)

1. **Team Brain Unification** 🟡 IN PROGRESS
   - Phase 1: Voice Unification ✅ COMPLETE
   - Phase 2: Backend Wiring ⏳ NEXT
   - Phase 3: UI Implementation (pending user approval of mockups)
   - Phase 4: Deprecation (AIAssistant.jsx, BotBrainPanel.jsx)

---

### ✅ P0 - COMPLETE (Data Integrity & Core Functionality)

1. **Session Persistence & Data Continuity** ✅ COMPLETE
2. **EOD Auto-Close for Intraday Trades** ✅ COMPLETE  
3. **Ticker Modal Click Bug** ✅ COMPLETE (March 13)
4. **Smart Strategy Filtering** ✅ COMPLETE (March 13)
5. **One-Click Stop Fix** ✅ COMPLETE (March 13)

---

### 🟠 P1 - HIGH PRIORITY (UX & Architecture Cleanup)

4. **UI Consolidation: Trader Dashboard Tab Review** ✅ EVALUATED
   - Recommendation: KEEP both dashboards (serve different purposes)
   - NewDashboard: Bot briefing, AI coaching
   - TradingDashboard: Position management, order flow, risk

5. **Bot Performance Panel - More Space & Prominence** ✅ COMPLETE

6. **Market Regime Panel Redesign** ✅ COMPLETE

7. **Live Chart Data Loading** ✅ COMPLETE - IB/Alpaca fallback working

8. **Deep Analysis API Integration** ✅ COMPLETE - askAIAboutStock wired

9. **Enhanced Brief Me Feature** ✅ COMPLETE
   - Real news/catalysts from Finnhub
   - Sector rotation analysis
   - Earnings calendar integration
   - News sentiment analysis

---

### 🟡 P2 - MEDIUM PRIORITY (Feature Enhancement)

10. **AI Proactive Intelligence** ✅ COMPLETE
    - ProactiveIntelligence component in Bot Brain
    - Alerts for setup triggers, profit-taking, runners, regime warnings

11. **Exit Optimization (Trailing Stops)** ✅ COMPLETE
    - /api/smart-stops/calculate-trailing-stop
    - /api/smart-stops/auto-trail-positions
    - ATR, percent, chandelier, parabolic modes

12. **Bot's Take for Non-Position Tickers** ✅ COMPLETE
    - HypotheticalBotTakeCard in ticker modal

13. **Smart Strategy Filtering** ✅ COMPLETE (moved to P0)
    - Built into bot's AI reasoning (not UI filters)
    - Bot checks user's historical win rate on setup type
    - Surfaces reasoning in thoughts

14. **One-Click Stop Fix** ✅ COMPLETE (moved to P0)
    - Auto-adjust risky stops to recommended level
    - Fix All Stops button in Bot Brain panel

---

### 🟢 P3 - LOW PRIORITY (Nice to Have)

15. **Market Scanner Alpaca Rate Limiting Fix**
    - Scanning 12,000+ symbols is impractically slow
    - Consider pre-filtered lists or caching

16. **Voice Commands**
    - Voice-based interaction for Team Brain

17. **Multi-Timeframe Analysis**

18. **Deprecate Old Trader Dashboard** (after Team Brain complete)
    - TradingDashboardPage.jsx can be removed once Team Brain has all features

---

## Code Architecture

```
/app
├── backend/
│   └── app/
│       ├── api/routers/
│       │   ├── ib.py (IB data endpoints)
│       │   └── trading_bot_router.py (bot control, reconciliation, EOD)
│       └── services/
│           ├── trading_bot_service.py (core bot logic)
│           ├── ib_service.py (IB integration)
│           └── news_service.py (unified news)
├── documents/
│   └── ib_data_pusher.py (local script)
└── frontend/
    └── src/
        ├── components/
        │   ├── NewDashboard.jsx (main dashboard, MODIFIED)
        │   ├── BotPerformanceChart.jsx
        │   ├── BotBrainPanel.jsx
        │   ├── MarketRegimeWidget.jsx
        │   └── EnhancedTickerModal.jsx
        ├── hooks/
        │   └── useTickerModal.jsx (global modal state, MODIFIED)
        └── pages/
            ├── CommandCenterPage.js
            └── TradingDashboardPage.jsx (separate dashboard)
```

---

## Key Technical Notes

### Position Card Click Fix (March 13)
- Changed from `motion.div` to `<button>` for reliable native click handling
- `data-testid="position-card-{symbol}"` for testing
- `handlePositionClick(symbol)` calls `openTickerModal(symbol)` from context

### Trading Dashboard Features (To Keep)
- Order Pipeline: Visual order flow tracking
- In-Trade Guidance: Position-specific alerts
- Risk Status: Daily loss limit, exposure monitoring
- TradingView Chart: Full-featured embedded chart

---

## Files of Reference
- `/app/frontend/src/components/NewDashboard.jsx` - Main dashboard with position cards
- `/app/frontend/src/hooks/useTickerModal.jsx` - Modal context and state
- `/app/frontend/src/components/EnhancedTickerModal.jsx` - Chart modal
- `/app/frontend/src/pages/TradingDashboardPage.jsx` - Execution-focused dashboard
- `/app/backend/app/services/trading_bot_service.py` - Bot logic
