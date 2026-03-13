# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with AI trading coach, autonomous trading bot, and mutual learning loop.

---

## RECENT UPDATES (March 13, 2026)

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

## 📋 FULL PRIORITY ROADMAP (March 2026)

### 🔴 P0 - CRITICAL (Data Integrity & Core Functionality)

1. **Session Persistence & Data Continuity** ✅ COMPLETE
2. **EOD Auto-Close for Intraday Trades** ✅ COMPLETE  
3. **Ticker Modal Click Bug** ✅ COMPLETE (March 13)

---

### 🟠 P1 - HIGH PRIORITY (UX & Architecture Cleanup)

4. **UI Consolidation: Trader Dashboard Tab Review** ✅ EVALUATED
   - Recommendation: KEEP both dashboards (serve different purposes)
   - NewDashboard: Bot briefing, AI coaching
   - TradingDashboard: Position management, order flow, risk

5. **Bot Performance Panel - More Space & Prominence** ✅ COMPLETE

6. **Market Regime Panel Redesign** ✅ COMPLETE

7. **Live Chart Data Loading** - Needs IB connection testing

8. **Deep Analysis API Integration** - Wire button in modal

---

### 🟡 P2 - MEDIUM PRIORITY (Feature Enhancement)

6. **Enhanced Brief Me Feature**
   - Real news/catalysts
   - Scan more symbols for gappers
   - Sector rotation analysis
   - Earnings calendar integration

7. **AI Improvement Plan Phase 3: Proactive Intelligence**

8. **Smart Strategy Filtering**

9. **Exit Optimization**

10. **Bot's Take for Non-Position Tickers**

---

### 🟢 P3 - LOW PRIORITY (Nice to Have)

11. **Market Scanner Alpaca Rate Limiting Fix**

12. **Deprecate Old Monolithic Services**
    - `ai_assistant_service.py`, `slow_learning_service.py`

13. **Voice Commands**

14. **Multi-Timeframe Analysis**

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
