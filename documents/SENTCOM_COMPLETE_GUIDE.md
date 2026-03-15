# SentCom Complete System Guide
## From Startup to Shutdown - Everything That Happens

---

# Table of Contents
1. [Startup Sequence](#1-startup-sequence)
2. [System Architecture](#2-system-architecture)
3. [The Trading Day](#3-the-trading-day)
4. [AI Decision Making](#4-ai-decision-making)
5. [Trade Execution Flow](#5-trade-execution-flow)
6. [Data Collection](#6-data-collection)
7. [Learning & Self-Improvement](#7-learning--self-improvement)
8. [Chat Interactions](#8-chat-interactions)
9. [End of Day](#9-end-of-day)
10. [Weekend Automation](#10-weekend-automation)

---

# 1. Startup Sequence

## What Happens When You Run StartTrading.bat

```
┌─────────────────────────────────────────────────────────────────┐
│                    StartTrading.bat                              │
│                                                                  │
│  Step 1: Check Prerequisites                                     │
│    ├── Python installed? ✓                                      │
│    ├── Required packages? ✓                                     │
│    └── Network connection? ✓                                    │
│                                                                  │
│  Step 2: Start IB Gateway (Port 4002)                           │
│    ├── Launch TWS/Gateway application                           │
│    ├── Auto-login with stored credentials                       │
│    └── Wait for "Accepting connections" status                  │
│                                                                  │
│  Step 3: Start IB Data Pusher                                    │
│    ├── Connects to IB Gateway locally                           │
│    ├── Connects to Cloud backend                                │
│    └── Begins polling for data requests                         │
│                                                                  │
│  Step 4: Start Ollama Proxy (if using local LLM)                │
│    └── Routes AI requests to local Ollama instance              │
│                                                                  │
│  Step 5: Health Check Loop                                       │
│    └── Continuously monitors all connections                    │
└─────────────────────────────────────────────────────────────────┘
```

### Example Startup Console Output:
```
============================================
   TradeCommand - Starting Up
============================================
[OK] Python 3.11 found
[OK] IB Gateway starting...
[OK] IB Gateway connected on port 4002
[OK] IB Data Pusher connected to cloud
[OK] All systems ready!

Health Check: IB Gateway ✓ | Data Pusher ✓ | Cloud API ✓
```

---

# 2. System Architecture

## The Big Picture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         YOUR COMPUTER                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   IB Gateway    │    │  IB Data Pusher │    │  Ollama (LLM)   │  │
│  │   (Port 4002)   │◄──►│    (Python)     │    │   (Optional)    │  │
│  │                 │    │                 │    │                 │  │
│  │ • Live quotes   │    │ • Polls cloud   │    │ • Local AI      │  │
│  │ • Order exec    │    │ • Fetches data  │    │ • Fast response │  │
│  │ • Account info  │    │ • Reports back  │    │                 │  │
│  └────────┬────────┘    └────────┬────────┘    └─────────────────┘  │
│           │                      │                                   │
└───────────┼──────────────────────┼───────────────────────────────────┘
            │                      │
            │   INTERNET           │
            ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         CLOUD SERVER                                  │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                      FastAPI Backend                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │ │
│  │  │   Scanner    │  │  Trading Bot │  │  AI Modules  │          │ │
│  │  │  • Finds     │  │  • Executes  │  │  • Debate    │          │ │
│  │  │    setups    │  │    trades    │  │  • Risk Mgr  │          │ │
│  │  │  • Filters   │  │  • Manages   │  │  • Coach     │          │ │
│  │  │    alerts    │  │    positions │  │  • Analyst   │          │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘          │ │
│  │                                                                  │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │ │
│  │  │  Learning    │  │  Time-Series │  │   Training   │          │ │
│  │  │  Connectors  │  │     AI       │  │    Center    │          │ │
│  │  │  • Calibrate │  │  • Predict   │  │  • Collect   │          │ │
│  │  │  • Improve   │  │  • Forecast  │  │  • Store     │          │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘          │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                         MongoDB                                  │ │
│  │  • Historical Data    • Trade Journal    • Learning Data        │ │
│  │  • Alert Outcomes     • Module Weights   • Predictions          │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 3. The Trading Day

## Timeline of a Typical Day

```
┌──────────────────────────────────────────────────────────────────────┐
│                        TRADING DAY TIMELINE                          │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  4:00 AM ET    Pre-Market Opens                                      │
│  ────────────────────────────────────────────────────────────────    │
│  • Scanner begins monitoring pre-market movers                       │
│  • Gap scanner identifies overnight gaps                             │
│  • News service fetches overnight headlines                          │
│                                                                       │
│  8:00 AM ET    You Start the App                                     │
│  ────────────────────────────────────────────────────────────────    │
│  • StartTrading.bat launches                                         │
│  • IB Gateway connects                                               │
│  • System syncs open positions                                       │
│                                                                       │
│  9:30 AM ET    Market Opens                                          │
│  ────────────────────────────────────────────────────────────────    │
│  • Scanner shifts to intraday mode                                   │
│  • ORB (Opening Range Breakout) setups activate                      │
│  • First 15-30 mins: High volatility scanning                        │
│                                                                       │
│  9:30-10:00    ORB Window                                            │
│  ────────────────────────────────────────────────────────────────    │
│  • Opening range established                                         │
│  • ORB breakout alerts generated                                     │
│  • Example: "NVDA ORB Breakout Long at $485.50"                      │
│                                                                       │
│  10:00-12:00   Morning Session                                       │
│  ────────────────────────────────────────────────────────────────    │
│  • VWAP reclaim/reject plays                                         │
│  • 9 EMA scalps                                                      │
│  • Pattern breakouts (flags, triangles)                              │
│                                                                       │
│  12:00-2:00    Midday Lull                                           │
│  ────────────────────────────────────────────────────────────────    │
│  • Scanner widens thresholds (less activity)                         │
│  • Focus on swing setups                                             │
│  • Daily chart patterns                                              │
│                                                                       │
│  2:00-4:00     Power Hour                                            │
│  ────────────────────────────────────────────────────────────────    │
│  • Volume picks up                                                   │
│  • EOD (End of Day) setups                                           │
│  • Position sizing for overnight holds                               │
│                                                                       │
│  4:00 PM ET    Market Closes                                         │
│  ────────────────────────────────────────────────────────────────    │
│  • Final position sync with IB                                       │
│  • Trade journal updated                                             │
│  • Learning connections sync                                         │
│  • Daily performance calculated                                      │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 4. AI Decision Making

## How SentCom Decides to Trade

When an alert comes in, here's what happens:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ALERT RECEIVED                                    │
│                                                                      │
│  Example: "AAPL Bull Flag Breakout at $178.50"                      │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 1: INITIAL FILTERING                               │
│                                                                      │
│  ADV Check:     AAPL daily volume = 50M shares ✓ (need 500K+)       │
│  Price Check:   $178.50 ✓ (within $1-$1000 range)                   │
│  Spread Check:  $0.02 spread ✓ (acceptable)                         │
│  Blacklist:     Not blacklisted ✓                                   │
│                                                                      │
│  Result: PASSED → Continue to analysis                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 2: INTELLIGENCE GATHERING                          │
│                                                                      │
│  Run these in parallel (10 second timeout):                         │
│                                                                      │
│  📰 NEWS:                                                           │
│     └── "Apple announces record iPhone sales"                       │
│     └── Sentiment: BULLISH                                          │
│                                                                      │
│  📊 TECHNICALS:                                                     │
│     └── RSI: 58 (neutral-bullish)                                   │
│     └── MACD: Bullish crossover                                     │
│     └── 9 EMA: Price above ✓                                        │
│     └── VWAP: Price above ✓                                         │
│                                                                      │
│  📈 QUALITY METRICS:                                                │
│     └── Setup Quality Score: 7.2/10                                 │
│     └── Historical Win Rate: 62%                                    │
│     └── Average R-Multiple: 1.4R                                    │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 3: BULL vs BEAR DEBATE                             │
│                                                                      │
│  ┌─────────────────────────┐   ┌─────────────────────────┐         │
│  │      🐂 BULL AGENT      │   │      🐻 BEAR AGENT      │         │
│  │                         │   │                         │         │
│  │ Arguments FOR:          │   │ Arguments AGAINST:      │         │
│  │                         │   │                         │         │
│  │ • Clean bull flag       │   │ • Market slightly       │         │
│  │   pattern (+0.15)       │   │   overbought (-0.10)    │         │
│  │                         │   │                         │         │
│  │ • Strong volume         │   │ • Near resistance       │         │
│  │   confirmation (+0.12)  │   │   at $180 (-0.08)       │         │
│  │                         │   │                         │         │
│  │ • Bullish news          │   │ • Sector rotation       │         │
│  │   catalyst (+0.10)      │   │   concerns (-0.05)      │         │
│  │                         │   │                         │         │
│  │ • Above VWAP (+0.08)    │   │                         │         │
│  │                         │   │                         │         │
│  │ SCORE: 0.72             │   │ SCORE: 0.38             │         │
│  │ CONFIDENCE: 75%         │   │ CONFIDENCE: 45%         │         │
│  └─────────────────────────┘   └─────────────────────────┘         │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                    ⚖️ ARBITER DECISION                   │       │
│  │                                                          │       │
│  │  Bull Score: 0.72  vs  Bear Score: 0.38                 │       │
│  │  Margin: +0.34 (Bull wins by significant margin)        │       │
│  │                                                          │       │
│  │  VERDICT: PROCEED WITH TRADE                            │       │
│  │  Combined Confidence: 68%                               │       │
│  │  Recommended Size: FULL POSITION                        │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 4: RISK MANAGER ASSESSMENT                         │
│                                                                      │
│  Risk Factors Evaluated:                                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Factor              │ Score  │ Weight │ Weighted │ Warning?    │ │
│  ├─────────────────────┼────────┼────────┼──────────┼─────────────┤ │
│  │ Position Size Risk  │ 3/10   │ 20%    │ 0.60     │ No          │ │
│  │ Market Regime       │ 4/10   │ 15%    │ 0.60     │ No          │ │
│  │ Correlation Risk    │ 2/10   │ 15%    │ 0.30     │ No          │ │
│  │ Volatility          │ 5/10   │ 15%    │ 0.75     │ No          │ │
│  │ Liquidity           │ 1/10   │ 10%    │ 0.10     │ No          │ │
│  │ Time of Day         │ 3/10   │ 10%    │ 0.30     │ No          │ │
│  │ Historical Perf     │ 3/10   │ 15%    │ 0.45     │ No          │ │
│  ├─────────────────────┼────────┼────────┼──────────┼─────────────┤ │
│  │ TOTAL RISK SCORE    │        │        │ 3.10/10  │ ACCEPTABLE  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Risk Assessment: LOW-MEDIUM                                        │
│  Recommendation: PROCEED (no risk flags)                            │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 5: FINAL TRADE CONSTRUCTION                        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      TRADE DETAILS                           │   │
│  │                                                              │   │
│  │  Symbol:        AAPL                                        │   │
│  │  Direction:     LONG                                        │   │
│  │  Entry:         $178.50                                     │   │
│  │  Stop Loss:     $176.80 (below flag low)                    │   │
│  │  Risk:          $1.70 per share                             │   │
│  │                                                              │   │
│  │  Position Sizing:                                           │   │
│  │  ─────────────────────────────────────────────              │   │
│  │  Account Risk:    $500 (1% of $50,000 account)              │   │
│  │  Shares:          $500 ÷ $1.70 = 294 shares                 │   │
│  │  Position Value:  294 × $178.50 = $52,479                   │   │
│  │                                                              │   │
│  │  Targets (Scale Out):                                       │   │
│  │  ─────────────────────────────────────────────              │   │
│  │  Target 1:  $181.90 (+2R) - Sell 33% (97 shares)           │   │
│  │  Target 2:  $183.60 (+3R) - Sell 33% (97 shares)           │   │
│  │  Target 3:  $186.20 (+4.5R) - Sell remaining (100 shares)  │   │
│  │                                                              │   │
│  │  Risk/Reward:  1:3 average                                  │   │
│  │                                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  Status: PENDING YOUR CONFIRMATION                                  │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 6: USER CONFIRMATION                               │
│                                                                      │
│  📱 Alert Shown in UI:                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                                                              │   │
│  │  🟢 NEW TRADE OPPORTUNITY                                   │   │
│  │                                                              │   │
│  │  AAPL Bull Flag Breakout                                    │   │
│  │  Entry: $178.50 | Stop: $176.80 | Target: $183.60           │   │
│  │                                                              │   │
│  │  AI Confidence: 68% | Risk Score: 3.1/10                    │   │
│  │  Bull/Bear: Bull wins +0.34                                 │   │
│  │                                                              │   │
│  │  [ ✓ CONFIRM ]  [ ✗ REJECT ]  [ ✏️ MODIFY ]                │   │
│  │                                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 5. Trade Execution Flow

## What Happens When You Confirm a Trade

```
┌─────────────────────────────────────────────────────────────────────┐
│              YOU CLICK "CONFIRM"                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 1: ORDER PREPARATION                               │
│                                                                      │
│  Order Type Decision:                                               │
│  • Price at/near bid? → LIMIT ORDER at $178.50                      │
│  • Fast-moving? → Could use MARKET ORDER                            │
│  • Large size? → Could use TWAP/VWAP algo                           │
│                                                                      │
│  Selected: LIMIT ORDER @ $178.50                                    │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 2: SEND TO IB GATEWAY                              │
│                                                                      │
│  Cloud Backend → IB Data Pusher → IB Gateway → Exchange            │
│                                                                      │
│  Order Details Sent:                                                │
│  {                                                                  │
│    "action": "BUY",                                                 │
│    "symbol": "AAPL",                                                │
│    "quantity": 294,                                                 │
│    "order_type": "LMT",                                             │
│    "limit_price": 178.50,                                           │
│    "time_in_force": "DAY"                                           │
│  }                                                                  │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 3: ORDER STATUS UPDATES                            │
│                                                                      │
│  Timeline:                                                          │
│  09:45:01.234  Order submitted to IB                                │
│  09:45:01.456  Order acknowledged (ID: 12847)                       │
│  09:45:01.892  Order routed to NASDAQ                               │
│  09:45:02.103  FILLED 294 shares @ $178.48 (better than limit!)     │
│                                                                      │
│  Fill Details:                                                      │
│  • Filled: 294 shares                                               │
│  • Avg Price: $178.48                                               │
│  • Commission: $0.35                                                │
│  • Total Cost: $52,465.47                                           │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 4: STOP LOSS PLACED                                │
│                                                                      │
│  Automatic stop loss order:                                         │
│  {                                                                  │
│    "action": "SELL",                                                │
│    "symbol": "AAPL",                                                │
│    "quantity": 294,                                                 │
│    "order_type": "STP",                                             │
│    "stop_price": 176.80                                             │
│  }                                                                  │
│                                                                      │
│  Status: WORKING (will trigger if price hits $176.80)               │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STEP 5: POSITION MONITORING                             │
│                                                                      │
│  SentCom now monitors:                                              │
│                                                                      │
│  • Price Updates (every 250ms):                                     │
│    Current: $178.72 | P&L: +$70.56 (+0.13%)                        │
│                                                                      │
│  • Target Tracking:                                                 │
│    T1 ($181.90): 1.78 away | T2 ($183.60): 3.48 away               │
│                                                                      │
│  • Trailing Stop (optional):                                        │
│    If enabled, stop moves up as price increases                     │
│                                                                      │
│  • Time-Based Rules:                                                │
│    Auto-close if held past 4 PM? Configurable                       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Scale-Out Execution (When Targets Hit)

```
┌─────────────────────────────────────────────────────────────────────┐
│              TARGET 1 HIT ($181.90)                                  │
│                                                                      │
│  10:23 AM - AAPL reaches $181.90                                    │
│                                                                      │
│  Action: Sell 97 shares (33% of position)                           │
│  Fill: 97 shares @ $181.88                                          │
│  Realized P&L: +$329.88 (+1.9%)                                     │
│                                                                      │
│  Remaining Position: 197 shares                                     │
│  Stop Loss: Moved to BREAKEVEN ($178.48)                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              TARGET 2 HIT ($183.60)                                  │
│                                                                      │
│  11:47 AM - AAPL reaches $183.60                                    │
│                                                                      │
│  Action: Sell 97 shares (another 33%)                               │
│  Fill: 97 shares @ $183.55                                          │
│  Realized P&L: +$491.79 (+2.8%)                                     │
│                                                                      │
│  Remaining Position: 100 shares                                     │
│  Stop Loss: Moved to $181.00 (lock in 1.4R)                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              TRADE CLOSED (Target 3 or Stop)                         │
│                                                                      │
│  SCENARIO A - Target 3 Hit ($186.20):                               │
│  ─────────────────────────────────────                              │
│  Sell remaining 100 shares @ $186.15                                │
│  Final P&L: +$767 (+1.46% on position)                              │
│  R-Multiple: +3.2R (excellent!)                                     │
│                                                                      │
│  SCENARIO B - Trailing Stop Hit ($181.00):                          │
│  ─────────────────────────────────────────                          │
│  Sell remaining 100 shares @ $180.95                                │
│  Final P&L: +$247 (+0.47% on position)                              │
│  R-Multiple: +1.6R (good, locked in profit)                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# 6. Data Collection

## What Data SentCom Collects & Stores

### Real-Time Data (During Trading Hours)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REAL-TIME DATA STREAMS                            │
│                                                                      │
│  📊 PRICE DATA (from IB Gateway)                                    │
│  ────────────────────────────────                                   │
│  • Bid/Ask/Last prices - every 250ms                                │
│  • Volume - tick by tick                                            │
│  • High/Low of day                                                  │
│                                                                      │
│  Example Quote:                                                     │
│  {                                                                  │
│    "symbol": "AAPL",                                                │
│    "bid": 178.45,                                                   │
│    "ask": 178.47,                                                   │
│    "last": 178.46,                                                  │
│    "volume": 12847293,                                              │
│    "timestamp": "2026-03-15T10:23:45.123Z"                          │
│  }                                                                  │
│                                                                      │
│  📰 NEWS DATA                                                       │
│  ────────────────────────────────                                   │
│  • IB News feed (primary)                                           │
│  • Finnhub headlines (backup)                                       │
│  • Sentiment analysis on each headline                              │
│                                                                      │
│  📈 MARKET CONTEXT                                                  │
│  ────────────────────────────────                                   │
│  • SPY/QQQ levels and direction                                     │
│  • VIX level                                                        │
│  • Sector performance                                               │
│  • Market breadth (advance/decline)                                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Historical Data Collection (Your IB Data Pusher)

```
┌─────────────────────────────────────────────────────────────────────┐
│              HISTORICAL DATA COLLECTION FLOW                         │
│                                                                      │
│  Cloud Creates Request:                                             │
│  ─────────────────────                                              │
│  {                                                                  │
│    "request_id": "hist_abc123",                                     │
│    "symbol": "AAPL",                                                │
│    "duration": "1 M",     // 1 month                                │
│    "bar_size": "1 day",   // daily bars                             │
│    "status": "pending"                                              │
│  }                                                                  │
│                                                                      │
│             ↓ Stored in MongoDB queue                               │
│                                                                      │
│  Your IB Data Pusher Polls:                                         │
│  ──────────────────────────                                         │
│  GET /api/ib/historical-data/pending                                │
│  → Sees request for AAPL                                            │
│  → Claims it (status → "claimed")                                   │
│                                                                      │
│             ↓                                                       │
│                                                                      │
│  Pusher Fetches from IB Gateway:                                    │
│  ────────────────────────────────                                   │
│  Sends request to IB Gateway (port 4002)                            │
│  IB Gateway fetches from IB servers                                 │
│  Returns ~22 daily bars                                             │
│                                                                      │
│             ↓                                                       │
│                                                                      │
│  Pusher Reports Back:                                               │
│  ───────────────────                                                │
│  POST /api/ib/historical-data/result                                │
│  {                                                                  │
│    "request_id": "hist_abc123",                                     │
│    "symbol": "AAPL",                                                │
│    "success": true,                                                 │
│    "data": [                                                        │
│      {"date": "2026-02-15", "open": 172.50, "high": 174.20,        │
│       "low": 171.80, "close": 173.90, "volume": 48293847},         │
│      {"date": "2026-02-16", "open": 173.95, ...},                  │
│      ... (22 bars total)                                            │
│    ]                                                                │
│  }                                                                  │
│                                                                      │
│             ↓ Stored immediately in ib_historical_data              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### What Gets Stored in MongoDB

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MONGODB COLLECTIONS                               │
│                                                                      │
│  📊 ib_historical_data (Price History)                              │
│  ──────────────────────────────────────                             │
│  {                                                                  │
│    symbol: "AAPL",                                                  │
│    bar_size: "1 day",                                               │
│    date: "2026-03-15",                                              │
│    open: 178.20,                                                    │
│    high: 186.45,                                                    │
│    low: 177.90,                                                     │
│    close: 185.80,                                                   │
│    volume: 89234567,                                                │
│    collected_at: "2026-03-15T16:05:00Z"                             │
│  }                                                                  │
│                                                                      │
│  📝 trade_journal (Your Trades)                                     │
│  ─────────────────────────────                                      │
│  {                                                                  │
│    trade_id: "trade_xyz789",                                        │
│    symbol: "AAPL",                                                  │
│    direction: "long",                                               │
│    entry_price: 178.48,                                             │
│    exit_price: 183.55,                                              │
│    shares: 294,                                                     │
│    pnl: 1491.62,                                                    │
│    r_multiple: 2.98,                                                │
│    setup_type: "bull_flag",                                         │
│    entry_time: "2026-03-15T09:45:02Z",                              │
│    exit_time: "2026-03-15T11:47:15Z",                               │
│    ai_confidence: 0.68,                                             │
│    bull_score: 0.72,                                                │
│    bear_score: 0.38                                                 │
│  }                                                                  │
│                                                                      │
│  🎯 alert_outcomes (For Learning)                                   │
│  ────────────────────────────────                                   │
│  {                                                                  │
│    alert_id: "alert_123",                                           │
│    symbol: "AAPL",                                                  │
│    setup_type: "bull_flag",                                         │
│    was_traded: true,                                                │
│    outcome: "profitable",                                           │
│    r_multiple: 2.98,                                                │
│    timestamp: "2026-03-15T09:44:00Z"                                │
│  }                                                                  │
│                                                                      │
│  🧠 module_weights (Calibration Data)                               │
│  ─────────────────────────────────────                              │
│  {                                                                  │
│    module: "bull_agent",                                            │
│    current_weight: 0.32,                                            │
│    accuracy_30d: 0.64,                                              │
│    total_calls: 847,                                                │
│    correct_calls: 542,                                              │
│    last_calibrated: "2026-03-15T02:15:00Z"                          │
│  }                                                                  │
│                                                                      │
│  📈 timeseries_predictions (AI Forecasts)                           │
│  ─────────────────────────────────────────                          │
│  {                                                                  │
│    symbol: "AAPL",                                                  │
│    prediction_date: "2026-03-15",                                   │
│    predicted_direction: "up",                                       │
│    confidence: 0.73,                                                │
│    predicted_move: 2.3%,                                            │
│    actual_move: 2.1%,  // filled in later                           │
│    was_correct: true   // filled in later                           │
│  }                                                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# 7. Learning & Self-Improvement

## How SentCom Gets Smarter Over Time

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE LEARNING LOOP                                 │
│                                                                      │
│                      ┌──────────────┐                               │
│                      │   COLLECT    │                               │
│                      │    DATA      │                               │
│                      └──────┬───────┘                               │
│                             │                                        │
│                             ▼                                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │    TRADE     │───►│    LEARN     │───►│   IMPROVE    │          │
│  │   OUTCOMES   │    │   PATTERNS   │    │  DECISIONS   │          │
│  └──────────────┘    └──────────────┘    └──────┬───────┘          │
│         ▲                                       │                    │
│         │                                       │                    │
│         └───────────────────────────────────────┘                   │
│                      (Repeat Forever)                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Learning Connection #1: Outcomes → Scanner Calibration

```
┌─────────────────────────────────────────────────────────────────────┐
│              SCANNER THRESHOLD CALIBRATION                           │
│                                                                      │
│  What it does:                                                      │
│  ─────────────                                                      │
│  Analyzes which setup types are winning/losing, adjusts             │
│  scanner sensitivity accordingly.                                   │
│                                                                      │
│  Example Calculation:                                               │
│  ───────────────────                                                │
│                                                                      │
│  Setup Type: "ORB Breakout"                                         │
│  Last 30 Days:                                                      │
│    • Total Alerts: 47                                               │
│    • Profitable: 31                                                 │
│    • Win Rate: 66%                                                  │
│    • Avg R-Multiple: +1.8R                                          │
│                                                                      │
│  Current Threshold: 1.0                                             │
│  Win Rate > 60% AND Avg R > 0.5?  YES                              │
│  → Can LOWER threshold slightly (more alerts, still good edge)      │
│  New Threshold: 0.95                                                │
│                                                                      │
│  ─────────────────────────────────────────────────────              │
│                                                                      │
│  Setup Type: "VWAP Reject"                                          │
│  Last 30 Days:                                                      │
│    • Total Alerts: 38                                               │
│    • Profitable: 14                                                 │
│    • Win Rate: 37%                                                  │
│    • Avg R-Multiple: -0.3R                                          │
│                                                                      │
│  Current Threshold: 1.0                                             │
│  Win Rate < 40% OR Avg R < 0?  YES                                 │
│  → Must RAISE threshold (fewer alerts, only high-quality)           │
│  New Threshold: 1.30                                                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Learning Connection #2: Shadow Tracker → Module Weights

```
┌─────────────────────────────────────────────────────────────────────┐
│              MODULE WEIGHT CALIBRATION                               │
│                                                                      │
│  What it does:                                                      │
│  ─────────────                                                      │
│  Tracks how accurate each AI module is, adjusts how much            │
│  influence each has in decisions.                                   │
│                                                                      │
│  Module Performance (Last 30 Days):                                 │
│  ──────────────────────────────────                                 │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Module          │ Predictions │ Correct │ Accuracy │ Weight    │ │
│  ├─────────────────┼─────────────┼─────────┼──────────┼───────────┤ │
│  │ Bull Agent      │ 234         │ 156     │ 67%      │ 0.32 (+)  │ │
│  │ Bear Agent      │ 234         │ 142     │ 61%      │ 0.28      │ │
│  │ Risk Manager    │ 189         │ 134     │ 71%      │ 0.35 (++) │ │
│  │ Time-Series AI  │ 150         │ 87      │ 58%      │ 0.05 (new)│ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Weight Adjustment Logic:                                           │
│  ────────────────────────                                           │
│  • Accuracy > 65%? → Increase weight by 5%                          │
│  • Accuracy < 50%? → Decrease weight by 10%                         │
│  • New module? → Start at 5%, grow based on performance             │
│                                                                      │
│  Result: Risk Manager's opinion counts more because it's            │
│  been more accurate lately.                                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Learning Connection #3: Simulations → Model Training

```
┌─────────────────────────────────────────────────────────────────────┐
│              TIME-SERIES MODEL TRAINING                              │
│                                                                      │
│  What it does:                                                      │
│  ─────────────                                                      │
│  Uses historical data + simulation results to train the             │
│  Time-Series AI to make better predictions.                         │
│                                                                      │
│  Training Data Sources:                                             │
│  ─────────────────────                                              │
│  • IB Historical Data: 5,900 symbols × 22 days = 129,800 bars      │
│  • Simulation Results: Win/loss patterns for each setup             │
│  • Feature Engineering: RSI, MACD, Volume patterns, etc.            │
│                                                                      │
│  Example Training Process:                                          │
│  ─────────────────────────                                          │
│                                                                      │
│  Input Features (for AAPL on 2026-03-14):                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Feature                │ Value     │ Normalized               │ │
│  ├────────────────────────┼───────────┼──────────────────────────┤ │
│  │ RSI (14)               │ 58        │ 0.58                     │ │
│  │ MACD Histogram         │ 0.45      │ 0.23                     │ │
│  │ Volume vs 20d Avg      │ 1.3x      │ 0.65                     │ │
│  │ Distance from 9 EMA    │ +0.8%     │ 0.54                     │ │
│  │ Distance from VWAP     │ +0.5%     │ 0.52                     │ │
│  │ Sector Performance     │ +1.2%     │ 0.62                     │ │
│  │ Market (SPY) Direction │ +0.3%     │ 0.53                     │ │
│  │ VIX Level              │ 18        │ 0.36                     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Target (What Actually Happened):                                   │
│  • Next day return: +2.1%                                           │
│  • Classification: "UP" (correct prediction = 1)                    │
│                                                                      │
│  Model Learns:                                                      │
│  "When RSI ~58, MACD positive, volume elevated, and price           │
│   above both EMAs with low VIX → likely to go UP"                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# 8. Chat Interactions

## Common Conversations with SentCom

### Example 1: Morning Briefing

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOU: "Brief me on today"                                           │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SENTCOM (AI Coach):                                                │
│                                                                      │
│  Good morning! Here's your market briefing for March 15, 2026:      │
│                                                                      │
│  📊 MARKET CONTEXT                                                  │
│  • SPY: $512.45 (+0.3% premarket)                                   │
│  • QQQ: $445.80 (+0.5% premarket)                                   │
│  • VIX: 16.8 (low volatility = risk-on)                             │
│  • Futures: Slightly green                                          │
│                                                                      │
│  🔥 PRE-MARKET MOVERS                                               │
│  • NVDA +4.2% - Analyst upgrade from Goldman                        │
│  • TSLA -2.1% - Delivery concerns                                   │
│  • AMD +1.8% - Riding NVDA sympathy                                 │
│                                                                      │
│  📈 YOUR OPEN POSITIONS                                             │
│  • AAPL Long: +$485 (+1.2%) - Target 1 close                        │
│  • MSFT Long: -$120 (-0.4%) - Watching support                      │
│                                                                      │
│  🎯 SETUPS TO WATCH                                                 │
│  • NVDA: Gap up, potential ORB long if holds $890                   │
│  • AMD: Bull flag forming on daily                                  │
│  • META: Approaching breakout at $510                               │
│                                                                      │
│  💡 COACHING NOTE                                                   │
│  Your win rate on gap-up ORB plays is 72% this month.               │
│  NVDA fits that pattern today - be ready at the open!               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Example 2: Trade Analysis Request

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOU: "Should I take this NVDA long?"                               │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SENTCOM (Running Analysis...):                                     │
│                                                                      │
│  Let me analyze NVDA for you...                                     │
│                                                                      │
│  🐂 BULL CASE (Score: 0.78)                                         │
│  • Gap up on analyst upgrade (strong catalyst)                      │
│  • Above all key moving averages                                    │
│  • Volume 2.3x average (institutional interest)                     │
│  • Sector (semiconductors) leading today                            │
│                                                                      │
│  🐻 BEAR CASE (Score: 0.31)                                         │
│  • Extended from 9 EMA (2.1% stretch)                               │
│  • Near psychological resistance at $900                            │
│  • RSI at 68 (approaching overbought)                               │
│                                                                      │
│  ⚖️ MY VERDICT: PROCEED WITH CAUTION                               │
│                                                                      │
│  The setup is good but entry timing matters. I'd suggest:           │
│                                                                      │
│  OPTION A: Wait for pullback to $892 (VWAP) for better R:R         │
│  OPTION B: Take half size now, add on pullback                      │
│                                                                      │
│  If entering now at $897:                                           │
│  • Stop: $889 (below gap fill)                                      │
│  • Target 1: $908 (1.4R)                                            │
│  • Target 2: $920 (2.9R)                                            │
│                                                                      │
│  Risk/Reward: 1:2.1 (acceptable)                                    │
│  Historical win rate on gap ORBs: 68%                               │
│                                                                      │
│  Want me to set up this trade?                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Example 3: Learning from Mistakes

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOU: "Why did my TSLA trade fail?"                                 │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SENTCOM (Trade Analysis):                                          │
│                                                                      │
│  Let me review your TSLA trade from yesterday...                    │
│                                                                      │
│  📋 TRADE SUMMARY                                                   │
│  • Entry: $245.50 (Bull Flag breakout)                              │
│  • Stop: $242.00                                                    │
│  • Exit: $241.80 (stopped out)                                      │
│  • Loss: -$1.54 per share (-0.63%)                                  │
│  • R-Multiple: -1.06R                                               │
│                                                                      │
│  🔍 WHAT WENT WRONG                                                 │
│                                                                      │
│  1. MARKET CONTEXT IGNORED                                          │
│     At entry time, SPY was rolling over (-0.4% in 30 mins)          │
│     High-beta stocks like TSLA amplify market moves                 │
│     → Should have waited for market to stabilize                    │
│                                                                      │
│  2. NEWS MISSED                                                     │
│     30 mins before entry: "TSLA delivery concerns" headline         │
│     This created selling pressure that broke the pattern            │
│     → News check would have flagged this                            │
│                                                                      │
│  3. ENTRY TIMING                                                    │
│     You entered at 2:15 PM (midday lull)                            │
│     Your stats show 45% win rate on midday entries                  │
│     vs 67% win rate on morning entries                              │
│     → Pattern was valid but timing wasn't ideal                     │
│                                                                      │
│  💡 LESSONS FOR NEXT TIME                                           │
│                                                                      │
│  1. Always check market direction before high-beta entries          │
│  2. Do a quick news check on volatile names                         │
│  3. Your edge is strongest 9:30-11:00 AM                            │
│                                                                      │
│  I've logged this in your learning profile. Next time TSLA          │
│  sets up midday, I'll remind you of this pattern.                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Example 4: Performance Review

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOU: "How am I doing this week?"                                   │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SENTCOM (Performance Report):                                      │
│                                                                      │
│  📊 WEEKLY PERFORMANCE (Mar 11-15)                                  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Metric              │ This Week │ Last Week │ Change           │ │
│  ├─────────────────────┼───────────┼───────────┼──────────────────┤ │
│  │ Total Trades        │ 12        │ 15        │ -3               │ │
│  │ Winners             │ 8         │ 9         │ -1               │ │
│  │ Losers              │ 4         │ 6         │ -2 (better!)     │ │
│  │ Win Rate            │ 67%       │ 60%       │ +7%              │ │
│  │ Total P&L           │ +$2,847   │ +$1,923   │ +$924            │ │
│  │ Avg Winner          │ +$512     │ +$445     │ +$67             │ │
│  │ Avg Loser           │ -$286     │ -$312     │ +$26 (smaller)   │ │
│  │ Profit Factor       │ 2.38      │ 1.91      │ +0.47            │ │
│  │ Avg R-Multiple      │ +1.4R     │ +0.9R     │ +0.5R            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  🏆 BEST TRADE                                                      │
│  NVDA Long (+$892, +3.2R)                                           │
│  Clean ORB breakout, held through all targets                       │
│                                                                      │
│  📉 WORST TRADE                                                     │
│  TSLA Long (-$462, -1.5R)                                           │
│  Midday entry, missed the news catalyst                             │
│                                                                      │
│  💡 KEY INSIGHTS                                                    │
│                                                                      │
│  What's working:                                                    │
│  ✓ Morning ORB setups (5/6 winners)                                 │
│  ✓ Cutting losers faster (-0.8R avg loss vs -1.1R last week)        │
│  ✓ Semiconductor plays (you understand the sector)                  │
│                                                                      │
│  What needs work:                                                   │
│  ✗ Midday trades (2/5 winners - below your average)                 │
│  ✗ Taking profits too early on runners (left $400 on table)         │
│                                                                      │
│  🎯 SUGGESTION FOR NEXT WEEK                                        │
│  Focus on morning sessions (9:30-11:30). Your edge is clearest      │
│  there. Consider skipping midday unless setup is exceptional.       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# 9. End of Day

## What Happens When You Close the App

```
┌─────────────────────────────────────────────────────────────────────┐
│              END OF DAY SEQUENCE                                     │
│                                                                      │
│  4:00 PM ET - Market Closes                                         │
│  ───────────────────────────                                        │
│                                                                      │
│  STEP 1: Final Position Sync                                        │
│  ────────────────────────────                                       │
│  • Compare SentCom positions vs IB Gateway                          │
│  • Flag any discrepancies                                           │
│  • Update P&L with closing prices                                   │
│                                                                      │
│  STEP 2: Trade Journal Update                                       │
│  ────────────────────────────                                       │
│  • Save all closed trades to database                               │
│  • Calculate final R-multiples                                      │
│  • Tag each trade with setup type, time, outcome                    │
│                                                                      │
│  STEP 3: Learning Sync                                              │
│  ─────────────────────                                              │
│  • Update alert_outcomes with today's results                       │
│  • Run scanner calibration (if threshold changes needed)            │
│  • Update module weights (if accuracy changed significantly)        │
│                                                                      │
│  STEP 4: Daily Stats Calculation                                    │
│  ──────────────────────────────                                     │
│  • Total P&L: +$1,247                                               │
│  • Trades: 5 (4 wins, 1 loss)                                       │
│  • Win Rate: 80%                                                    │
│  • Best Trade: NVDA +$623                                           │
│  • Worst Trade: TSLA -$187                                          │
│                                                                      │
│  STEP 5: Prediction Verification                                    │
│  ───────────────────────────────                                    │
│  • Check Time-Series AI predictions from morning                    │
│  • Compare predicted vs actual moves                                │
│  • Log accuracy for model improvement                               │
│                                                                      │
│  Example:                                                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Symbol │ Predicted │ Actual │ Correct? │ Confidence           │ │
│  ├────────┼───────────┼────────┼──────────┼──────────────────────┤ │
│  │ AAPL   │ +1.5%     │ +2.1%  │ ✓        │ 73%                  │ │
│  │ NVDA   │ +2.0%     │ +3.4%  │ ✓        │ 68%                  │ │
│  │ MSFT   │ -0.5%     │ +0.3%  │ ✗        │ 55%                  │ │
│  │ TSLA   │ +1.0%     │ -1.8%  │ ✗        │ 51%                  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  Today's Prediction Accuracy: 50% (2/4)                             │
│                                                                      │
│  STEP 6: Cleanup                                                    │
│  ────────────                                                       │
│  • Clear expired alerts                                             │
│  • Archive old queue items                                          │
│  • Compress logs                                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Shutting Down

```
┌─────────────────────────────────────────────────────────────────────┐
│  When you close StartTrading.bat or your computer:                  │
│                                                                      │
│  1. IB Data Pusher disconnects from cloud                           │
│     → Cloud sees "pusher offline"                                   │
│     → Pending data requests stay in queue (resumed next session)    │
│                                                                      │
│  2. IB Gateway closes (or stays open based on your settings)        │
│     → If Auto-Logoff enabled: Closes at 11:59 PM                    │
│     → If Auto-Restart: Restarts at 1:45 AM                          │
│                                                                      │
│  3. Cloud backend keeps running                                     │
│     → All your data is safely stored                                │
│     → Learning connectors continue processing                       │
│     → Ready for next session                                        │
│                                                                      │
│  4. Local Ollama (if running) stays available                       │
│     → Can be used for other tasks                                   │
│     → Or shuts down with computer                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# 10. Weekend Automation

## What Happens Automatically on Weekends

```
┌─────────────────────────────────────────────────────────────────────┐
│              WEEKEND BATCH TIMELINE                                  │
│                                                                      │
│  Friday 4:00 PM - Market Closes                                     │
│  ─────────────────────────────                                      │
│  • Normal end-of-day process                                        │
│  • You close app, go enjoy weekend                                  │
│                                                                      │
│  Friday 11:59 PM - IB Gateway Auto-Logoff                           │
│  ────────────────────────────────────────                           │
│  • IB Gateway shuts down cleanly                                    │
│  • Frees up resources                                               │
│                                                                      │
│  Saturday 1:45 AM - IB Gateway Auto-Restart                         │
│  ───────────────────────────────────────────                        │
│  • IB Gateway starts up                                             │
│  • Ready for connection                                             │
│                                                                      │
│  Saturday 2:00 AM - WeekendAuto.bat Runs                            │
│  ────────────────────────────────────────                           │
│  (Task Scheduler wakes computer, auto-login)                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  WeekendAuto.bat                                                │ │
│  │  ├── Runs StartTrading.bat                                      │ │
│  │  │   ├── Starts IB Gateway                                      │ │
│  │  │   ├── Logs in automatically                                  │ │
│  │  │   └── Starts IB Data Pusher                                  │ │
│  │  │                                                              │ │
│  │  └── Runs weekend_batch.py                                      │ │
│  │      ├── Waits for pusher connection                            │ │
│  │      ├── Triggers Smart Collection                              │ │
│  │      ├── ... (see below)                                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Saturday 2:04 AM - Smart Collection Starts                         │
│  ───────────────────────────────────────────                        │
│  • Creates ~5,900 data requests in queue                            │
│  • IB Data Pusher starts processing:                                │
│                                                                      │
│    Intraday Tier (ADV ≥ 500K):                                      │
│    └── ~280 symbols × 3.5 sec = ~16 minutes                         │
│                                                                      │
│    Swing Tier (ADV ≥ 100K):                                         │
│    └── ~1,500 symbols × 3.5 sec = ~87 minutes                       │
│                                                                      │
│    Investment Tier (ADV ≥ 50K):                                     │
│    └── ~2,400 symbols × 3.5 sec = ~140 minutes                      │
│                                                                      │
│  Saturday ~6:00 AM - Collection Complete                            │
│  ───────────────────────────────────────                            │
│  • ~5,900 symbols refreshed                                         │
│  • ~130,000 new daily bars stored                                   │
│                                                                      │
│  Saturday 6:05 AM - Model Retraining                                │
│  ────────────────────────────────────                               │
│  • Time-Series AI trains on new data                                │
│  • Updates prediction weights                                       │
│  • Takes ~10-15 minutes                                             │
│                                                                      │
│  Saturday 6:20 AM - Batch Simulations                               │
│  ─────────────────────────────────────                              │
│  • Runs backtests on all 5,900 symbols                              │
│  • Tests momentum strategy on new data                              │
│  • Identifies what's working                                        │
│  • Takes ~30-45 minutes                                             │
│                                                                      │
│  Saturday 7:00 AM - Learning Sync                                   │
│  ─────────────────────────────────                                  │
│  • Scanner thresholds calibrated                                    │
│  • Module weights updated                                           │
│  • Prediction accuracy logged                                       │
│                                                                      │
│  Saturday 7:15 AM - WEEKEND BATCH COMPLETE!                         │
│  ──────────────────────────────────────────                         │
│  • All results logged to weekend_batch.log                          │
│  • SentCom is now smarter                                           │
│  • Ready for Monday trading                                         │
│                                                                      │
│  Sunday 2:00 AM - (Optional) Second Run                             │
│  ──────────────────────────────────────────                         │
│  • Can run again to catch any missed symbols                        │
│  • Or skip if Saturday was successful                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

# Summary: The Complete Picture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SENTCOM ECOSYSTEM                                 │
│                                                                      │
│                         ┌───────────────┐                           │
│                         │    YOU        │                           │
│                         │  (Trader)     │                           │
│                         └───────┬───────┘                           │
│                                 │                                    │
│              ┌──────────────────┼──────────────────┐                │
│              │                  │                  │                │
│              ▼                  ▼                  ▼                │
│     ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│     │    CHAT     │    │   ALERTS    │    │  DASHBOARD  │          │
│     │  Interface  │    │   & Trades  │    │   & Stats   │          │
│     └──────┬──────┘    └──────┬──────┘    └──────┬──────┘          │
│            │                  │                  │                  │
│            └──────────────────┼──────────────────┘                  │
│                               │                                      │
│                               ▼                                      │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │                    AI BRAIN                              │    │
│     │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │    │
│     │  │  Coach  │ │  Bull   │ │  Bear   │ │  Risk   │       │    │
│     │  │  Agent  │ │  Agent  │ │  Agent  │ │ Manager │       │    │
│     │  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │    │
│     │                                                          │    │
│     │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │    │
│     │  │ Scanner │ │  Time-  │ │ Learning│ │ Trading │       │    │
│     │  │         │ │ Series  │ │Connector│ │   Bot   │       │    │
│     │  │         │ │   AI    │ │         │ │         │       │    │
│     │  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │    │
│     └─────────────────────────────────────────────────────────┘    │
│                               │                                      │
│                               ▼                                      │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │                    DATA LAYER                            │    │
│     │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │    │
│     │  │  Historical  │ │    Trade     │ │   Learning   │    │    │
│     │  │    Prices    │ │   Journal    │ │     Data     │    │    │
│     │  └──────────────┘ └──────────────┘ └──────────────┘    │    │
│     └─────────────────────────────────────────────────────────┘    │
│                               │                                      │
│                               ▼                                      │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │                  EXECUTION LAYER                         │    │
│     │                                                          │    │
│     │     Your Computer              Exchanges                 │    │
│     │  ┌──────────────┐          ┌──────────────┐             │    │
│     │  │  IB Gateway  │  ─────►  │    NYSE      │             │    │
│     │  │  IB Pusher   │  ◄─────  │   NASDAQ     │             │    │
│     │  └──────────────┘          │    etc.      │             │    │
│     │                            └──────────────┘             │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                      │
│                         THE LEARNING LOOP                           │
│                    ┌────────────────────────┐                       │
│                    │  Trade → Outcome →     │                       │
│                    │  Learn → Improve →     │                       │
│                    │  Trade (smarter) →     │                       │
│                    │  REPEAT FOREVER        │                       │
│                    └────────────────────────┘                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference Card

| When | What Happens |
|------|--------------|
| **Startup** | StartTrading.bat → IB Gateway → Data Pusher → Cloud Connected |
| **Pre-Market** | Scanner monitors gaps, news flows in |
| **Market Open** | ORB setups, high activity, alerts generated |
| **Alert Received** | Filter → Intel Gather → Bull/Bear Debate → Risk Check → Your Approval |
| **Trade Confirmed** | Order → IB Gateway → Exchange → Fill → Monitor |
| **Targets Hit** | Auto scale-out, stop adjustments |
| **Trade Closed** | Journal updated, outcomes recorded |
| **Market Close** | Final sync, daily stats, learning update |
| **Weekend** | Auto batch: Collection → Training → Simulations → Calibration |

---

*Document Generated: March 15, 2026*
*Version: 1.0*
*SentCom Trading System*
