# Team Brain Unification - Implementation Plan

## Overview

This document outlines the plan to unify the AI Assistant and Bot Brain into a single "Team Brain" that uses "we" language throughout, creating a partnership feeling between the trader and the AI system.

---

## Current Architecture Analysis

### Backend Services (Keep Separate)

| Service | Purpose | Voice Change Needed |
|---------|---------|---------------------|
| `orchestrator.py` | Routes requests to specialized agents | Update system prompts to "we" |
| `router_agent.py` | Intent classification | No change |
| `trade_executor_agent.py` | Trade execution decisions | Update to "we" language |
| `coach_agent.py` | Personalized guidance | Update to "we" language |
| `analyst_agent.py` | Market analysis | Update to "we" language |
| `brief_me_agent.py` | Market summaries | Update to "we" language |
| `trading_bot_service.py` | Bot logic, thoughts generation | Update to "we" language |
| `ai_assistant_service.py` | Chat interactions | **DEPRECATE** - Merge into orchestrator |
| `smart_context_engine.py` | Context building | No change |

### Frontend Components (Need Consolidation)

| Component | Current State | Action |
|-----------|--------------|--------|
| `BotBrainPanel.jsx` | Bot's first-person thoughts | **REPLACE** with TeamBrain.jsx |
| `AIAssistant.jsx` | Separate chat interface | **DEPRECATE** - Merge into TeamBrain |
| `TeamBrain.jsx` | New unified component (created by design agent) | **WIRE UP** to real APIs |
| `NewDashboard.jsx` | Shows both panels separately | **UPDATE** layout to single TeamBrain |
| `EnhancedTickerModal.jsx` | "Bot's Take" section | Rename to "Our Take", update language |
| `BriefMeModal.jsx` | Market summary | Update language to "we" |
| `LearningDashboard.jsx` | Strategy stats | Rename to "Our Performance" |

---

## Implementation Phases

### Phase 1: Backend Voice Unification (Prompts Only)

**Files to Update:**
1. `/app/backend/agents/orchestrator.py` - System prompt
2. `/app/backend/agents/coach_agent.py` - Response language
3. `/app/backend/agents/analyst_agent.py` - Response language
4. `/app/backend/agents/brief_me_agent.py` - Summary language
5. `/app/backend/services/trading_bot_service.py` - Thought generation

**Language Guidelines:**
```
OLD: "I'm monitoring NVDA for a breakout"
NEW: "We're monitoring NVDA for a breakout"

OLD: "I recommend you consider taking profits"
NEW: "We should consider taking profits here"

OLD: "Your win rate on breakouts is 65%"
NEW: "Our win rate on breakouts is 65%"

OLD: "I detected a pullback setup"
NEW: "We've spotted a pullback setup"
```

**New Unified API Endpoint:**
```
POST /api/team-brain/chat
- Accepts user messages
- Routes through orchestrator
- Returns unified "we" voice responses
- Includes recent thoughts in context

GET /api/team-brain/stream
- Returns unified stream of:
  - Bot thoughts (execution reasoning)
  - Proactive alerts
  - Filter decisions
  - Chat history
```

---

### Phase 2: Frontend Consolidation

**Step 1: Wire TeamBrain.jsx to Real APIs**
- Replace mock data with actual API calls
- Connect to `/api/trading-bot/thoughts`
- Connect to `/api/team-brain/chat` (new)
- Connect to `/api/trading-bot/smart-filter/thoughts`

**Step 2: Update NewDashboard.jsx Layout**
```
CURRENT LAYOUT (12 cols):
├── Left (8 cols)
│   ├── Bot's Brain Panel
│   ├── Active Positions
│   └── Setups I'm Watching
└── Right (4 cols)
    ├── AI Assistant (separate)
    └── Other widgets

NEW LAYOUT (12 cols):
├── Left (7 cols)
│   ├── Team Brain (unified - taller)
│   └── Active Positions (compact)
└── Right (5 cols)
    ├── Setups We're Watching
    ├── Our Performance Mini
    └── Market Regime
```

**Step 3: Deprecate Old Components**
- `AIAssistant.jsx` → Remove from dashboard, keep code for reference
- `BotBrainPanel.jsx` → Keep as fallback, mark deprecated

---

### Phase 3: Modal & Detail Updates

**EnhancedTickerModal.jsx:**
- Rename "Bot's Take" → "Our Take"
- Update `BotTakeCard` language
- Update `HypotheticalBotTakeCard` language

**BriefMeModal.jsx:**
- Update summary language to "we"
- "The market is showing..." → "We're seeing the market..."

---

### Phase 4: Analytics & Learning Integration

**AnalyticsTab.jsx Updates:**
- Add "Our Performance" sub-tab
- Show strategy win rates in visual chart
- Language: "Our edge", "What we've learned"

**LearningDashboard.jsx Updates:**
- Rename to "TeamPerformanceDashboard.jsx"
- Update all labels to "Our" language
- Add strategy performance visualization

---

## Deprecation Candidates

### Safe to Deprecate (After Migration)
1. `AIAssistant.jsx` - Functionality merged into TeamBrain
2. Parts of `ai_assistant_service.py` - Chat functionality moves to orchestrator

### Keep but Rename
1. `BotBrainPanel.jsx` → Legacy fallback (remove after stable)
2. `LearningDashboard.jsx` → `TeamPerformanceDashboard.jsx`

### Do NOT Deprecate (User requested to keep)
1. `TradingDashboardPage.jsx` - Old dashboard, keep for now

---

## New Files to Create

### Backend
```
/app/backend/routers/team_brain.py
- POST /api/team-brain/chat - Unified chat endpoint
- GET /api/team-brain/stream - Combined thoughts + chat stream
- GET /api/team-brain/context - Current team context (positions, regime, etc.)
```

### Frontend
```
/app/frontend/src/components/TeamBrain.jsx ✅ (Already created by design agent)
/app/frontend/src/components/TeamPerformanceDashboard.jsx
/app/frontend/src/hooks/useTeamBrain.js - Unified data hook
```

---

## Voice Style Guide

### The "We" Persona
- **Collaborative**: "We should consider..." not "You should..."
- **Inclusive**: "Our position in TSLA..." not "Your position..."
- **Partnership**: "We've learned that breakouts work for us" not "The bot has learned..."
- **Transparent**: "We're passing on this trade because our win rate is low"

### Message Types
| Type | Voice Example |
|------|---------------|
| Analysis | "We're seeing strong momentum in NVDA with volume confirmation" |
| Trade Entry | "We're entering AAPL - this pullback matches our criteria" |
| Trade Exit | "We should consider exiting here - approaching our target" |
| Learning | "We've been 67% on pullbacks lately - this is our strength" |
| Warning | "Heads up - this stop is tight. We might want to adjust" |
| Filter | "We're passing on this setup - our history shows 38% win rate" |

---

## Testing Checklist

- [ ] All "I" and "Your" replaced with "We" and "Our" in bot thoughts
- [ ] Chat responses use "we" language consistently
- [ ] TeamBrain panel shows unified stream (thoughts + chat)
- [ ] Order pipeline visible in TeamBrain header
- [ ] Proactive alerts appear in unified stream
- [ ] Filter thoughts appear with proper styling
- [ ] Stop fix functionality works from unified view
- [ ] EnhancedTickerModal shows "Our Take"
- [ ] BriefMe uses "we" language
- [ ] Analytics shows "Our Performance"
- [ ] No console errors from deprecated components

---

## Rollout Strategy

1. **Phase 1** (Backend) - Can be deployed independently, backward compatible
2. **Phase 2** (Frontend) - Feature flag: `USE_TEAM_BRAIN=true`
3. **Phase 3** (Modals) - Direct update, low risk
4. **Phase 4** (Analytics) - Can be done in parallel

---

## Questions for User

1. Should the TeamBrain panel have an "expanded/fullscreen" mode for focused trading?
2. Should quick action chips be visible always or only on hover?
3. Preference for the unified stream order: newest first or oldest first?
4. Should we preserve the ability to see ONLY bot thoughts vs ONLY chat?
