# TradeCommand - Trading Taxonomy & Workflow

## Visual Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    TRADING HIERARCHY                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐
│ TRADING STYLE   │  ← Overall approach to markets (Scalping, Swing, Position)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ STRATEGY        │  ← Methodology/edge (Mean Reversion, Momentum, Breakout)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ SETUP           │  ← Specific pattern/condition that signals opportunity
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TRADE IDEA      │  ← Filtered setup with catalyst + thesis
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TRADE PLAN      │  ← Entry, Stop, Target, Size (using S/R levels)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TRADE           │  ← Executed position with live P&L
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ OUTCOME         │  ← Result: Won/Lost + R-multiple for EV tracking
└─────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   SMB WORKFLOW STATE MACHINE                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  IDEA_GEN    │────▶│ FILTER_GRADE │────▶│ TRADE_PLAN   │────▶│  EXECUTION   │────▶│  REVIEW_EV   │
│              │     │              │     │              │     │              │     │              │
│ • Scanner    │     │ • A/B/C/D    │     │ • Entry      │     │ • Execute    │     │ • Record R   │
│ • News       │     │ • Catalyst   │     │ • Stop (S/R) │     │ • Manage     │     │ • Update EV  │
│ • Catalyst   │     │ • EV Check   │     │ • Target     │     │ • Partials   │     │ • Gate check │
│ • Pattern    │     │ • Drop if F  │     │ • Size       │     │ • Trail      │     │              │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────┬───────┘
                            │                                                              │
                            │ (Drop if                                                     │
                            │  EV < 0 or                                          ┌───────▼───────┐
                            │  Catalyst < 5)                                      │ Loop back if  │
                            ▼                                                     │ EV > 0        │
                      ┌──────────┐                                                └───────────────┘
                      │ DROPPED  │
                      └──────────┘
```

---

## Category 1: TRADING STRATEGIES (Methodologies)

These are overarching approaches that define HOW you trade:

### Momentum Strategies
| Strategy | Description | Market Regime | Time Windows |
|----------|-------------|---------------|--------------|
| **Trend Following** | Trade in direction of prevailing trend | STRONG_UPTREND, STRONG_DOWNTREND | All day |
| **Breakout Trading** | Enter on price breaking key levels | MOMENTUM | Late Morning, Afternoon |
| **Gap Trading** | Trade opening gaps | MOMENTUM | Opening, Morning |

### Mean Reversion Strategies
| Strategy | Description | Market Regime | Time Windows |
|----------|-------------|---------------|--------------|
| **VWAP Reversion** | Fade extremes back to VWAP | RANGE_BOUND, FADE | Mid-day |
| **EMA Snapback** | Fade extensions from moving averages | RANGE_BOUND | All day |
| **Oversold/Overbought** | Trade RSI extremes | FADE | Mid-day, Afternoon |

### Scalping Strategies
| Strategy | Description | Market Regime | Time Windows |
|----------|-------------|---------------|--------------|
| **Tape Reading** | Trade based on order flow | All | All day |
| **Level Scalping** | Trade bounces off key levels | RANGE_BOUND | All day |
| **Spread Capture** | Trade bid/ask inefficiencies | All | All day |

---

## Category 2: SETUPS (Patterns & Conditions)

These are SPECIFIC patterns that generate trade signals. Organized by time window:

### Opening Setups (9:30-9:45 AM)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **First VWAP Pullback** | `first_vwap_pullback` | First touch of VWAP after gap | Both | Price touches VWAP |
| **First Move Up** | `first_move_up` | Strong opening momentum up | Long | >1% move with volume |
| **First Move Down** | `first_move_down` | Strong opening momentum down | Short | <-1% move with volume |
| **Bella Fade** | `bella_fade` | Fade extreme opening move | Counter | 3%+ move, RSI extreme |
| **Opening Drive** | `opening_drive` | Ride strong directional open | Both | High RVOL, trend confirm |
| **Back Through Open** | `back_through_open` | Short failed gap up | Short | Gap up fails, breaks open |
| **Up Through Open** | `up_through_open` | Long after gap down reversal | Long | Gap down reverses above open |

### Morning Momentum Setups (9:45-10:30 AM)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **Opening Range Breakout (ORB)** | `orb` | Break first 15-30 min range | Both | Price breaks range |
| **HitchHiker** | `hitchhiker` | Ride strong leader momentum | Long | Outperforming SPY >3% |
| **Gap Give & Go** | `gap_give_go` | Gap continues after pullback | Long | Gap up holds, pullback bought |
| **Gap Pick & Roll** | `gap_pick_roll` | Gap reversal play | Short | Gap up fails, sells off |

### Core Session Setups (10:30 AM - 1:30 PM)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **Spencer Scalp** | `spencer_scalp` | Scalp strong momentum moves | Both | Flags, volume spikes |
| **Second Chance** | `second_chance` | Re-entry after pullback | Both | Pullback to prior breakout |
| **Backside** | `backside` | Reversal after extended move | Counter | 5%+ move, divergence |
| **Off Sides** | `off_sides` | Fade extreme intraday move | Counter | 4%+ move, no news |
| **Fashionably Late** | `fashionably_late` | Late entry on continuation | Both | Pattern confirms late |
| **Big Dog** | `big_dog` | Large cap consolidation break | Both | Major level break |
| **Puppy Dog** | `puppy_dog` | Small cap follow the leader | Both | Follows sector leader |

### Mean Reversion Setups (All Day)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **Rubber Band** | `rubber_band` | Snapback to EMA9 | Both | 2.5%+ extension from EMA9 |
| **VWAP Bounce** | `vwap_bounce` | Bounce off VWAP | Long | Touch VWAP with support |
| **VWAP Fade** | `vwap_fade` | Fade extension from VWAP | Both | 2%+ from VWAP |
| **Tidal Wave** | `tidal_wave` | Large cap mean reversion | Both | 3%+ move, reversal candle |
| **Mean Reversion** | `mean_reversion` | RSI extreme + S/R snap | Both | RSI <30 or >70 at level |

### Consolidation & Squeeze Setups
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **Squeeze** | `squeeze` | BB inside KC compression | Both | Volatility breakout |
| **9 EMA Scalp** | `9_ema_scalp` | Scalp bounces off 9 EMA | Both | Touch 9 EMA in trend |
| **ABC Scalp** | `abc_scalp` | 3-wave pullback scalp | Both | A-B-C pattern complete |

### Afternoon Setups (1:30-4:00 PM)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **HOD Breakout** | `hod_breakout` | Break high of day | Long | New HOD with volume |
| **Time of Day Fade** | `time_of_day_fade` | Fade late day extension | Counter | Overextended into close |

### Special Setups (Context Dependent)
| Setup | Code | Description | Direction | Trigger |
|-------|------|-------------|-----------|---------|
| **Breaking News** | `breaking_news` | Trade fresh catalyst | Both | News breaks |
| **Volume Capitulation** | `volume_capitulation` | Extreme volume reversal | Both | 5x+ volume spike |
| **Range Break** | `range_break` | Multi-day range breakout | Both | Range breaks |
| **Breakout** | `breakout` | Resistance breakout | Long | Breaks key resistance |
| **Relative Strength** | `relative_strength` | Sector leader/laggard | Both | +/- 3% vs SPY |
| **Gap Fade** | `gap_fade` | Fade failing gap | Counter | Gap fails to hold |
| **Chart Pattern** | `chart_pattern` | Classic patterns | Both | Pattern triggers |

---

## Category 3: SMB CAPITAL'S 20 SETUPS (PlayBook)

These are the original SMB Capital playbook setups:

| # | Setup | Description | Our Equivalent |
|---|-------|-------------|----------------|
| 1 | **Changing Fundamentals** | Trade on fundamental change | `breaking_news` |
| 2 | **Breakout Trade** | Classic breakout | `breakout` |
| 3 | **Big Dawg Trade** | Large cap consolidation | `big_dog` |
| 4 | **Technical Analysis** | Pure TA plays | `chart_pattern` |
| 5 | **Opening Drive** | Ride strong opens | `opening_drive` |
| 6 | **IPO Trade** | Trade new issues | (Special handling) |
| 7 | **2nd Day Trade** | Day 2 momentum | (News-based) |
| 8 | **Elite Trading 101** | Master pattern | `spencer_scalp` |
| 9 | **Return Pullback** | Pullback entry | `second_chance` |
| 10 | **Scalp Trade** | Quick scalps | `spencer_scalp` |
| 11 | **Stuffed Trade** | Failed breakout fade | `off_sides` |
| 12 | **Multiple Time Frame Support** | MTF confluence | `vwap_bounce` |
| 13 | **Dr. S Trades** | Steve Spencer specials | `spencer_scalp` |
| 14 | **Market Play Trade** | Sector/macro plays | `hitchhiker` |
| 15 | **Breaking News** | News catalyst | `breaking_news` |
| 16 | **Bounce Trades** | Oversold bounces | `rubber_band` |
| 17 | **Gap and Go Trade** | Gap continuation | `gap_give_go` |
| 18 | **Low Float Trade** | Low float momentum | (Special handling) |
| 19 | **Stock Filters** | Screener-based | Scanner-based |
| 20 | **VWAP with Shark** | VWAP plays | `vwap_bounce`, `vwap_fade` |

---

## Category 4: TRADE LIFECYCLE

### Trade States
```
┌────────────┐
│  PENDING   │  Alert generated, waiting for trigger
└─────┬──────┘
      │
      ▼
┌────────────┐
│  ACTIVE    │  Position open, managing
└─────┬──────┘
      │
      ├────────────────┬────────────────┐
      ▼                ▼                ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│    WON     │  │    LOST    │  │  SCRATCHED │
│   (+R)     │  │   (-R)     │  │   (0R)     │
└────────────┘  └────────────┘  └────────────┘
```

### Trade Grading (A/B/C/D/F)
| Grade | EV Threshold | Size Multiplier | Action |
|-------|--------------|-----------------|--------|
| **A** | EV ≥ 2.5R | 1.5x | Full size + add |
| **B** | EV 1.0-2.5R | 1.0x | Standard size |
| **C** | EV 0.5-1.0R | 0.75x | Reduced size |
| **D** | EV 0-0.5R | 0.5x | Minimal or pass |
| **F** | EV < 0R | 0x | Do not trade |

---

## Category 5: MARKET REGIMES

Setups are filtered by current market regime:

| Regime | Description | Best Setups |
|--------|-------------|-------------|
| **STRONG_UPTREND** | SPY >1% up | Breakouts, ORB long, Hitchhiker |
| **STRONG_DOWNTREND** | SPY >1% down | Backside, Fades, Shorts |
| **MOMENTUM** | Volatile directional | ORB, Breaking News, Gaps |
| **RANGE_BOUND** | SPY <0.5% range | Mean reversion, VWAP trades |
| **FADE** | Exhausted moves | Rubber Band, Off Sides |
| **VOLATILE** | High VIX, choppy | Reduced size, quick scalps |

---

## Category 6: TIME WINDOWS

| Window | Time (ET) | Best Setups |
|--------|-----------|-------------|
| **OPENING_AUCTION** | 9:30-9:35 | Opening plays, Bella Fade |
| **OPENING_DRIVE** | 9:35-9:45 | ORB, HitchHiker, Gap plays |
| **MORNING_MOMENTUM** | 9:45-10:30 | Spencer Scalp, Breakouts |
| **MORNING_SESSION** | 10:30-11:30 | Big Dog, Mean Reversion |
| **LATE_MORNING** | 11:30-12:00 | Second Chance, Patterns |
| **MIDDAY** | 12:00-13:30 | Reduced activity, scalps |
| **AFTERNOON** | 13:30-15:30 | HOD Breakout, Range Break |
| **CLOSE** | 15:30-16:00 | Time of Day Fade |

---

## Summary Statistics

### Implemented Setups: 35
- **Opening**: 7 setups
- **Morning Momentum**: 4 setups
- **Core Session**: 7 setups
- **Mean Reversion**: 5 setups
- **Consolidation**: 4 setups
- **Afternoon**: 2 setups
- **Special**: 6 setups

### EV Tracking Coverage
- All 35 setups have EV tracking enabled
- R-multiple recording on every closed trade
- Historical win rate used for projected EV
- S/R levels inform stop/target calculations

---

## Quick Reference: Setup → Alert Flow

```
1. Scanner detects pattern (e.g., rubber_band)
2. Technical levels fetched (S/R, VWAP, ATR)
3. Stop/Target calculated from levels
4. R-multiple computed (Target - Entry) / (Entry - Stop)
5. Historical EV fetched for this setup
6. Trade graded (A/B/C/D/F) based on EV + context
7. Alert generated with full reasoning
8. User reviews and executes
9. Outcome recorded → EV updated
```
