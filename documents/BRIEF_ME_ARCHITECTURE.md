# Brief Me Feature - Agent Architecture

## Overview
The "Brief Me" button triggers an AI-generated personalized market report that is tailored to:
1. Current market conditions
2. Your bot's state and performance
3. Your historical learning data (what works for you)
4. Open positions and risk exposure
5. Active scanner opportunities

## Agent Responsibilities

### 1. **MarketIntelAgent** (Existing: `/app/backend/services/market_intel_service.py`)
Provides:
- Market regime status (RISK_ON, HOLD, RISK_OFF)
- SPY/QQQ/IWM performance
- VIX level and trend
- Sector rotation analysis
- News headlines summary

### 2. **ContextAwarenessService** (Existing: `/app/backend/services/context_awareness_service.py`)
Provides:
- Current trading session (Pre-Market, Market Open, etc.)
- Session-specific trading advice
- Risk level for current session

### 3. **LearningContextProvider** (Existing: `/app/backend/services/learning/learning_context_provider.py`)
Provides:
- Your best performing setups by win rate
- Best time of day for your trading
- Best market regime for your strategies
- Edge decay warnings (setups that stopped working)
- Calibration recommendations

### 4. **TradingBotService** (Existing: `/app/backend/services/trading_bot_service.py`)
Provides:
- Current bot state (HUNTING, MONITORING, PAUSED)
- Open positions with P&L
- Today's performance (wins/losses/P&L)
- Pending setups being watched

### 5. **EnhancedScanner** (Existing: `/app/backend/services/enhanced_scanner.py`)
Provides:
- Active high-quality alerts
- Top opportunities by TQS score
- Setups approaching trigger

---

## New: BriefMeAgent

### Location
`/app/backend/agents/brief_me_agent.py`

### Responsibilities
1. **Aggregate** data from all above services
2. **Personalize** the report based on learning data
3. **Prioritize** information (most relevant first)
4. **Generate** natural language summary via LLM

### Data Flow
```
User clicks "Brief Me"
        ↓
BriefMeAgent.generate_brief()
        ↓
    ┌───────────────────────────────────────┐
    │  Parallel Data Fetch:                 │
    │  ├─ MarketIntelService.get_summary()  │
    │  ├─ ContextAwarenessService.get_full()│
    │  ├─ LearningContextProvider.build()   │
    │  ├─ TradingBotService.get_status()    │
    │  └─ EnhancedScanner.get_top_alerts()  │
    └───────────────────────────────────────┘
        ↓
    Build structured context
        ↓
    LLM generates personalized summary
        ↓
    Return to AI Assistant chat
```

### Sample Output Structure
```json
{
  "market_summary": {
    "regime": "HOLD",
    "regime_score": 62,
    "spy_status": "+0.3% above VWAP",
    "vix": 18.5,
    "session": "Market Open"
  },
  "your_bot": {
    "state": "HUNTING",
    "today_pnl": 2847.32,
    "trades_today": 4,
    "win_rate": 0.75,
    "open_positions": [
      {"symbol": "LABD", "pnl": 127.50, "pnl_pct": 0.65}
    ]
  },
  "personalized_insights": {
    "best_setup_for_regime": "ORB Breakout",
    "win_rate_in_hold": 0.72,
    "avoid_today": "VWAP Fades (historically weak in HOLD)",
    "edge_warning": null
  },
  "opportunities": [
    {"symbol": "NVDA", "setup": "Breakout", "trigger_prob": 0.75, "tqs": 72},
    {"symbol": "META", "setup": "ORB", "trigger_prob": 0.90, "tqs": 78}
  ],
  "recommendation": "Focus on ORB setups today. Your bot is performing well. NVDA breakout has highest probability. Consider reducing position size to 75% due to HOLD regime."
}
```

### LLM Prompt Template
```
You are a trading assistant providing a personalized market brief.

MARKET CONDITIONS:
- Regime: {regime} (Score: {score})
- SPY: {spy_status}
- VIX: {vix}
- Session: {session}

USER'S BOT STATUS:
- State: {bot_state}
- Today's P&L: ${pnl}
- Win Rate: {win_rate}%
- Open Positions: {positions}

USER'S LEARNING DATA:
- Best setup in {regime} regime: {best_setup} ({win_rate_for_setup}% win rate)
- Best time of day: {best_time}
- Setups to avoid: {avoid_setups}

TOP OPPORTUNITIES:
{opportunities}

Generate a concise, personalized market brief (3-4 paragraphs) that:
1. Summarizes current market conditions
2. Relates them to the user's historical performance
3. Highlights the best opportunities for THEIR trading style
4. Provides a clear recommendation

Use second person ("You should...", "Your bot is...").
Be specific with numbers and data.
```

---

## Implementation Steps

1. **Create BriefMeAgent** (`/app/backend/agents/brief_me_agent.py`)
2. **Add endpoint** (`POST /api/agents/brief-me`)
3. **Wire to Orchestrator** - Add "brief_me" intent detection
4. **Frontend** - "Brief Me" button triggers chat message "Brief me on the market"
5. **AI Assistant** - Displays formatted brief in chat

## Existing Code to Reuse
- `MarketIntelService.generate_report()` - Already generates market summaries
- `LearningContextProvider.build_full_learning_context()` - Already aggregates learning
- `ContextAwarenessService.get_full_context()` - Already provides session/regime
- Router patterns for "brief me", "what's the market", "market update"

## Time Estimate
- BriefMeAgent: ~2-3 hours
- Integration: ~1 hour
- Testing: ~1 hour
