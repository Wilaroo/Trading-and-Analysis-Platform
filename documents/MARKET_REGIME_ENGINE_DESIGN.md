# Market Regime Engine Design Document

## Overview

The **Market Regime Engine** is a sophisticated market state analyzer inspired by VectorVest and IBD (Investor's Business Daily) methodologies. It determines the overall market condition to guide trading decisions with three primary outputs:

1. **Market State**: `CONFIRMED_UP`, `HOLD`, `CONFIRMED_DOWN`
2. **Risk Level**: 0-100 scale
3. **Confidence Score**: 0-100 scale

This acts as a "Fear and Greed Index" tailored for active traders.

---

## Architecture Design

### Location
```
/app/backend/services/market_regime_engine.py  (NEW)
/app/backend/routers/market_regime.py          (NEW)
/app/frontend/src/components/MarketRegimeWidget.jsx (NEW)
```

### Integration Points
- **Data Sources**: IB Gateway (primary), Alpaca (fallback)
- **Dependencies**: `alpaca_service.py`, `ib_service.py`, `market_indicators.py`
- **Consumers**: Dashboard UI, Trading Bot, AI Agents, Scanner

---

## Signal Block Architecture

Based on VectorVest and IBD research, the engine uses **four signal blocks**, each contributing to the final market state determination:

### 1. Trend Signal Block (Weight: 35%)

**Purpose**: Determines primary market direction using moving averages and price structure.

**Indicators**:
| Indicator | Description | Bullish Signal | Bearish Signal |
|-----------|-------------|----------------|----------------|
| SPY vs 21 EMA | Short-term trend | Price > 21 EMA | Price < 21 EMA |
| SPY vs 50 SMA | Medium-term trend | Price > 50 SMA | Price < 50 SMA |
| SPY vs 200 SMA | Long-term trend | Price > 200 SMA | Price < 200 SMA |
| 21 EMA vs 50 SMA | Trend alignment | 21 EMA > 50 SMA | 21 EMA < 50 SMA |
| Higher Highs/Lows | Price structure | HH + HL pattern | LH + LL pattern |

**Calculation**:
```python
trend_score = (
    (spy_above_21ema * 20) +
    (spy_above_50sma * 20) +
    (spy_above_200sma * 15) +
    (ema21_above_sma50 * 15) +
    (higher_highs_lows * 30)  # Strong weight for price structure
)
# Score: 0-100
```

---

### 2. Breadth Signal Block (Weight: 25%)

**Purpose**: Measures market participation - are the majority of stocks participating in the trend?

**Indicators**:
| Indicator | Description | Bullish Signal | Bearish Signal |
|-----------|-------------|----------------|----------------|
| Advance/Decline Ratio | Stock participation | A/D > 1.5 | A/D < 0.67 |
| % Above 200 SMA | Long-term strength | > 60% stocks | < 40% stocks |
| % Above 50 SMA | Medium-term strength | > 60% stocks | < 40% stocks |
| New Highs vs Lows | Momentum | Highs > Lows * 2 | Lows > Highs * 2 |
| Sector Participation | Sector breadth | > 7 sectors up | > 7 sectors down |

**Data Source Approach**:
Since we don't have direct breadth data, we'll use proxies:
- **SPY vs QQQ vs IWM correlation**: If all three trending same direction = good breadth
- **Sector ETF analysis**: Count sectors (XLK, XLF, XLE, etc.) above/below key MAs
- **VOLD ratio** from existing `market_indicators.py`

```python
breadth_score = (
    (all_indices_aligned * 25) +
    (sectors_positive_count / 11 * 35) +  # 11 sector ETFs
    (vold_ratio_positive * 20) +
    (small_caps_participating * 20)  # IWM confirmation
)
```

---

### 3. Follow-Through Day Signal Block (Weight: 20%)

**Purpose**: Detects market turns using IBD's Follow-Through Day methodology.

**IBD Follow-Through Day Criteria**:
1. Market in correction for at least 4 days
2. Big up day (>1.25% gain) on major index
3. Volume higher than previous day
4. Occurs on day 4+ of attempted rally

**Indicators**:
| Indicator | Description | Bullish Signal | Bearish Signal |
|-----------|-------------|----------------|----------------|
| Rally Attempt Count | Days since low | >= 4 days | N/A |
| FTD Signal | Confirmed rally | FTD occurred | No FTD in 25 days |
| Distribution Days | Selling pressure | < 4 in 25 days | >= 5 in 25 days |
| Failed Rally | Rally failed | N/A | FTD failed within 5 days |

**Distribution Day Definition (IBD)**:
- Index down >= 0.2%
- Volume higher than previous day
- Count resets after 25 trading days or 5% rally from count start

```python
# State machine for FTD tracking
ftd_state = "CORRECTION" | "RALLY_ATTEMPT" | "CONFIRMED_UP" | "CONFIRMED_DOWN"

ftd_score = (
    (ftd_confirmed * 50) +
    (distribution_day_count_low * 30) +  # < 4 = bullish
    (rally_intact * 20)
)
```

---

### 4. Volume & VIX Signal Block (Weight: 20%)

**Purpose**: Measures fear/greed through volume patterns and volatility.

**Indicators**:
| Indicator | Description | Bullish Signal | Bearish Signal |
|-----------|-------------|----------------|----------------|
| VIX Level | Fear gauge | VIX < 20 | VIX > 25 |
| VIX Trend | Direction | VIX falling | VIX rising |
| Volume Pattern | Institutional activity | Up days have higher vol | Down days have higher vol |
| Relative Volume | Activity level | RVOL 1.0-1.5 | RVOL > 2.0 (panic) |

```python
volume_vix_score = (
    (vix_level_healthy * 30) +
    (vix_trend_favorable * 20) +
    (volume_confirms_trend * 30) +
    (rvol_normal_range * 20)
)
```

---

## Market State Determination

### Composite Score Calculation

```python
composite_score = (
    trend_score * 0.35 +
    breadth_score * 0.25 +
    ftd_score * 0.20 +
    volume_vix_score * 0.20
)
```

### State Mapping

| Composite Score | Market State | Trading Implications |
|-----------------|--------------|---------------------|
| 70-100 | `CONFIRMED_UP` | Full position sizes, favor longs, buy dips |
| 50-69 | `HOLD` | Reduced exposure, selective trades, quick profits |
| 0-49 | `CONFIRMED_DOWN` | Defensive, favor shorts/cash, sell rallies |

### Risk Level Calculation

```python
risk_level = 100 - composite_score
# When composite is high (bullish), risk is low
# When composite is low (bearish), risk is high
```

### Confidence Score

Based on signal agreement across blocks:
```python
# If all 4 blocks agree on direction
if all_blocks_bullish or all_blocks_bearish:
    confidence = 90 + (score_variance_inverse * 10)
# If 3 of 4 blocks agree
elif three_blocks_agree:
    confidence = 70 + (agreement_strength * 20)
# Mixed signals
else:
    confidence = 40 + (dominant_signal_strength * 30)
```

---

## API Design

### Endpoints

```python
# Get current market regime
GET /api/market-regime/current
Response: {
    "state": "CONFIRMED_UP" | "HOLD" | "CONFIRMED_DOWN",
    "risk_level": 25,
    "confidence": 85,
    "composite_score": 75,
    "signal_blocks": {
        "trend": { "score": 80, "signals": {...} },
        "breadth": { "score": 70, "signals": {...} },
        "ftd": { "score": 75, "signals": {...} },
        "volume_vix": { "score": 72, "signals": {...} }
    },
    "recommendation": "Favor momentum longs, buy pullbacks to support",
    "last_updated": "2026-03-11T14:30:00Z"
}

# Get historical regime changes
GET /api/market-regime/history?days=30
Response: [{
    "date": "2026-03-10",
    "state": "HOLD",
    "previous_state": "CONFIRMED_UP",
    "trigger": "Distribution day count reached 5"
}]

# Get signal block details
GET /api/market-regime/signals/{block}
# block = trend | breadth | ftd | volume_vix

# Force refresh (bypass cache)
POST /api/market-regime/refresh
```

---

## UI Component Design

### MarketRegimeWidget.jsx

**Location**: Top of Live Trading Dashboard, high visibility

**Visual Elements**:

```
┌─────────────────────────────────────────────────────────────┐
│  MARKET REGIME                                    ⟳ 14:30  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│     🟢  CONFIRMED UP                                        │
│     ────────────────                                        │
│     Composite: 75/100    Confidence: 85%                   │
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │ TREND   │  │ BREADTH │  │   FTD   │  │ VOL/VIX │       │
│  │   80    │  │   70    │  │   75    │  │   72    │       │
│  │   ▲     │  │   ▲     │  │   ●     │  │   ▲     │       │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘       │
│                                                             │
│  Risk Level: ████████░░░░░░░░░░░░ 25%                      │
│                                                             │
│  💡 Favor momentum longs, buy pullbacks to support         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Color Coding**:
- `CONFIRMED_UP`: Green glow, green traffic light
- `HOLD`: Yellow/amber glow, yellow traffic light  
- `CONFIRMED_DOWN`: Red glow, red traffic light

**Interactions**:
- Click to expand detailed signal breakdown
- Hover on signal blocks for individual indicator details
- Manual refresh button

---

## Implementation Phases

### Phase 1: Core Engine (Backend)
1. Create `market_regime_engine.py` with signal block classes
2. Implement data fetching from IB/Alpaca
3. Implement trend and volume/VIX blocks (easiest, most data available)
4. Create basic API endpoints
5. Unit tests

### Phase 2: Advanced Signals
1. Implement breadth signal block (sector analysis proxy)
2. Implement FTD tracking state machine
3. Add distribution day counter
4. Historical state tracking in MongoDB

### Phase 3: UI Integration
1. Create `MarketRegimeWidget.jsx`
2. Integrate into Live Trading Dashboard
3. Add to AI agent context
4. Add to Trading Bot decision logic

### Phase 4: Refinement
1. Tune weights based on backtesting
2. Add alerts for state changes
3. Learning integration (track regime vs trade outcomes)

---

## Data Requirements

### From IB Gateway (Primary)
- SPY, QQQ, IWM, DIA real-time quotes
- VIX real-time quote
- Historical daily bars (50+ days for MAs)

### From Alpaca (Fallback)
- Same indices if IB unavailable
- Sector ETF quotes (XLK, XLF, XLE, XLV, XLI, XLC, XLY, XLP, XLU, XLRE, XLB)

### Calculated/Derived
- Moving averages (21 EMA, 50 SMA, 200 SMA)
- Distribution day tracking (stored in MongoDB)
- FTD state machine (stored in MongoDB)

---

## MongoDB Collections

```javascript
// market_regime_state - Current and historical state
{
    "_id": ObjectId,
    "date": ISODate("2026-03-11"),
    "state": "CONFIRMED_UP",
    "composite_score": 75,
    "risk_level": 25,
    "confidence": 85,
    "signal_blocks": {
        "trend": { "score": 80, "details": {...} },
        "breadth": { "score": 70, "details": {...} },
        "ftd": { "score": 75, "details": {...} },
        "volume_vix": { "score": 72, "details": {...} }
    },
    "distribution_days": [
        { "date": "2026-03-05", "change_pct": -0.8, "volume_ratio": 1.2 }
    ],
    "ftd_state": {
        "current_state": "CONFIRMED_UP",
        "rally_start_date": "2026-02-15",
        "ftd_date": "2026-02-20",
        "days_in_rally": 18
    }
}
```

---

## Integration with Existing Systems

### Trading Bot
```python
# In trading_bot_service.py
async def evaluate_trade(self, symbol, setup):
    regime = await market_regime_engine.get_current_regime()
    
    if regime.state == "CONFIRMED_DOWN":
        # Reduce position sizes, skip marginal setups
        if setup.tqs_score < 75:
            return {"action": "SKIP", "reason": "Weak setup in bear market"}
    
    elif regime.state == "HOLD":
        # Be selective
        if setup.tqs_score < 70:
            return {"action": "SKIP", "reason": "Only A+ setups in uncertain market"}
```

### AI Agents
```python
# In analyst_agent.py
async def analyze(self, symbol):
    regime = await self.data_fetcher.get_market_regime()
    
    context = f"""
    Current Market Regime: {regime.state}
    Risk Level: {regime.risk_level}%
    Key Factor: {regime.recommendation}
    
    Adjust analysis accordingly...
    """
```

### Scanner
```python
# In enhanced_scanner.py
async def prioritize_alerts(self, alerts):
    regime = await market_regime_engine.get_current_regime()
    
    for alert in alerts:
        if regime.state == "CONFIRMED_UP" and alert.direction == "LONG":
            alert.priority_boost = 10
        elif regime.state == "CONFIRMED_DOWN" and alert.direction == "SHORT":
            alert.priority_boost = 10
```

---

## Success Metrics

1. **Accuracy**: Market state should align with actual market performance 70%+ of the time
2. **Timeliness**: State changes should occur within 1-2 days of actual market turns
3. **Trader Utility**: Should reduce losses during corrections by promoting defensive posture

---

## Questions for Review

1. **Weight Tuning**: The initial weights (35/25/20/20) are starting points. Should we add a backtesting phase to optimize these?

2. **Update Frequency**: Should the engine update:
   - Real-time (every minute during market hours)?
   - Periodic (every 15 minutes)?
   - End-of-day only?

3. **Alert Mechanism**: When state changes (e.g., CONFIRMED_UP → HOLD), should we:
   - Send push notification?
   - Show modal popup?
   - Just update the widget?

4. **Historical Depth**: How many days of regime history should we store for analysis?

---

## Appendix: VectorVest & IBD Research Summary

### VectorVest Approach
- Uses Market Timing Indicator (MTI) based on:
  - Price trend (weighted moving averages)
  - Breadth (advance/decline data)
  - Volume analysis
- Generates BUY/SELL signals with confirmation requirements

### IBD Approach
- Follow-Through Day for rally confirmation
- Distribution Day counting for topping signals
- Requires volume confirmation for all signals
- Uses major indices (S&P 500, Nasdaq) as primary reference

### Our Hybrid Approach
- Combines VectorVest's quantitative scoring with IBD's FTD/Distribution methodology
- Adapts for available data (proxy calculations where direct data unavailable)
- Adds VIX integration for volatility context
- Tailored for active/day trading vs. longer-term swing trading

---

*Document Version: 1.0*
*Created: March 11, 2026*
*Author: TradeCommand AI System*
