# Market Regime Engine - Deployment Guide

## Overview

The Market Regime Engine is built and ready to deploy. This guide shows exactly how to connect it to the live application.

## Files Created

| File | Purpose | Status |
|------|---------|--------|
| `/app/backend/services/market_regime_engine.py` | Core engine with signal blocks | Ready |
| `/app/backend/routers/market_regime.py` | API endpoints | Ready |
| `/app/frontend/src/components/MarketRegimeWidget.jsx` | Dashboard widget | Ready |

## Backend Deployment Steps

### Step 1: Add imports to server.py

Find the imports section at the top of `/app/backend/server.py` and add:

```python
from services.market_regime_engine import MarketRegimeEngine, get_market_regime_engine
from routers.market_regime import router as market_regime_router, init_market_regime_engine
```

### Step 2: Initialize the engine

Find where other services are initialized (look for `alpaca_service`, `ib_service` initialization) and add:

```python
# Initialize Market Regime Engine
market_regime_engine = MarketRegimeEngine(alpaca_service, ib_service, db)
init_market_regime_engine(market_regime_engine)
```

### Step 3: Register the router

Find where other routers are included (look for `app.include_router(...)` statements) and add:

```python
app.include_router(market_regime_router)
```

## Frontend Deployment Steps

### Step 1: Import the widget

In the file where you want to display the widget (e.g., `AICoachTab.jsx` or `CommandCenterPage.js`):

```jsx
import MarketRegimeWidget from '../components/MarketRegimeWidget';
```

### Step 2: Add to the layout

Place the widget where you want it to appear:

```jsx
<MarketRegimeWidget 
  className="mb-4"  // Optional: add margin
  onStateChange={(newState, oldState) => {
    // Optional: handle state changes
    console.log(`Market regime changed: ${oldState} -> ${newState}`);
  }}
/>
```

### Recommended Placement

The widget works best at the **top of the Live Trading Dashboard** or **AI Coach Tab** where it's highly visible:

```jsx
// In AICoachTab.jsx or similar
<div className="space-y-4">
  {/* Market Regime at the top */}
  <MarketRegimeWidget />
  
  {/* Rest of your dashboard content */}
  <AICommandPanel ... />
</div>
```

## API Endpoints (Once Deployed)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/market-regime/current` | GET | Full regime analysis with all signal blocks |
| `/api/market-regime/state` | GET | Quick state check (lightweight) |
| `/api/market-regime/summary` | GET | Concise summary for UI display |
| `/api/market-regime/signals/{block}` | GET | Detailed signal block data |
| `/api/market-regime/history` | GET | Historical regime data |
| `/api/market-regime/refresh` | POST | Force refresh (bypass cache) |

## Testing Before Full Deployment

You can test the engine in isolation by temporarily adding the router:

```python
# In server.py - temporary test
from routers.market_regime import router as market_regime_router
app.include_router(market_regime_router)

# Test with curl:
# curl https://pipeline-control.preview.emergentagent.com/api/market-regime/summary
```

## Integration with Other Systems

### Trading Bot Integration

In `trading_bot_service.py`, you can use the regime to adjust behavior:

```python
from services.market_regime_engine import get_market_regime_engine

async def evaluate_trade(self, symbol, setup):
    engine = get_market_regime_engine()
    regime = await engine.get_current_regime()
    
    if regime["state"] == "CONFIRMED_DOWN":
        if setup.tqs_score < 75:
            return {"action": "SKIP", "reason": "Weak setup in bear market"}
```

### AI Agent Integration

In agent files, add regime to context:

```python
regime = await self.data_fetcher.get_market_regime()
context = f"Market Regime: {regime['state']} (Risk: {regime['risk_level']}%)"
```

## MongoDB Collections

The engine will create these collections automatically:

- `market_regime_state`: Daily regime snapshots
- `market_regime_ftd`: Follow-Through Day tracking state

## Rollback

If issues occur, simply:

1. Comment out the router inclusion in `server.py`
2. Remove the widget from the frontend
3. The collections can remain (no harm)

---

**Ready to deploy when you are!**
