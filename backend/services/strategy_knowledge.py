"""
Complete Trading Strategy Knowledge Base
All strategies, rules, and logic from SMB cheat sheets
This file provides comprehensive strategy context to the AI Assistant
"""

STRATEGY_KNOWLEDGE = """
=== COMPLETE TRADING STRATEGY KNOWLEDGE BASE ===

### 1. SPENCER SCALP
**Description**: Breakout from tight consolidation near HOD
**Entry**: Break of consolidation high with volume
**Setup Requirements**:
- Tight consolidation (< 20% of day's range)
- Located near high of day (HOD)
- Duration: 20+ minutes ideal
- Volume decreasing during consolidation, spike on break
- Low volume bar immediately before break = ideal
**Avoidance**:
- After 3 legs into consolidation
- After 3 PM (except ranging stocks)
- Consolidation not near HOD
**Exit**: Scale out in thirds at 1R, 2R, 3R

### 2. RUBBER BAND SCALP (Mean Reversion)
**Description**: Mean reversion play when price stretches away from 9 EMA
**Entry**: Snapback candle (double bar break) after extension below key MAs
**Setup Requirements**:
- Price extended below 9 EMA (for longs) or above (for shorts)
- Snapback candle MUST be in top 5 volume bars of day
- Entry on double bar break (single candle clears highs of 2+ prior candles)
**Best Market Condition**: Range fade / mean reversion markets
**Avoidance**:
- In cleanly trending markets (momentum too strong)
- After 2 failed attempts (two strikes rule)
- Snapback candle not in top 5 volume
**Exit**: Scale out in thirds
**Stop**: $0.02 below snapback candle low
**Max Attempts**: 2 per day per stock

### 3. HITCHHIKER
**Description**: Early entry into strong momentum move via consolidation
**Entry**: Break of small consolidation (5-20 min) after opening move
**Setup Requirements**:
- Setup before 9:59 AM (time restricted)
- Clean consolidation (no large wicks/chop)
- Initial move was NOT a single large candle
- Duration: 5-20 minutes
**Avoidance**:
- Choppy consolidations (large wicks)
- Initial move was single large candle
- Multiple prior break attempts
**Exit**: Waves method - half on first rush slowing, half on second acceleration
**Attempts**: One and done

### 4. GAP GIVE AND GO
**Description**: Continuation of gap direction after brief consolidation
**Entry**: Break of consolidation in gap direction
**Setup Requirements**:
- Must trigger before 9:45 AM
- Consolidation above key support level
- Consolidation < 50% of opening move
- Max consolidation duration: 7 minutes
- Stock must be In Play
**Avoidance**:
- Consolidation BELOW support level
- Consolidation > 50% of opening move
- Not In Play stock
- Move closes > 50% of gap before consolidation
- Multiple failed attempts before consolidation
**Exit**: Move2move - half first leg, half second leg
**Re-entry**: Allowed within 3 minutes if range breaks again
**Stop**: $0.02 below consolidation low

### 5. BACK$IDE
**Description**: Short-term reversal trade from overextended move
**Entry**: Higher low formation on pullback
**Setup Requirements**:
- Range > halfway between LOD and VWAP
- Higher highs/higher lows pattern (2+ minimum)
- Not Day 1 breakout on higher timeframe
**Avoidance**:
- Day 1 breakout on higher timeframe
- Stock gapped below higher TF range
- Market trending against trade
- Range not > halfway LOD to VWAP
**Exit**: Full exit at VWAP
**Stop**: $0.02 below most recent higher low
**Attempts**: One and done

### 6. OFF SIDES
**Description**: Fade of failed breakout/breakdown in range
**Entry**: After double high/double low range establishes battle zone
**Setup Requirements**:
- Double high and double low pattern (range with 2 highs and 2 lows)
- Clear battle zone established
- NOT day 1 breakout with 8+ catalyst
**Best Market Condition**: Range fade / mean reversion markets
**Avoidance**:
- Day 1 breakout stocks with 8+ catalyst
- Market trending opposite to trade
- Slow choppy action after break
- Momentum market conditions
**Stop**: $0.01 outside range boundary
**Attempts**: One and done

### 7. SECOND CHANCE
**Description**: Retest of broken level (support becomes resistance or vice versa)
**Entry**: On retest of broken level
**Setup Requirements**:
- Clean initial breakout
- Level held on retest
- Volume confirmation
**Avoidance**:
- Never take 3rd time on same setup
- Fighting bigger picture trend
**Exit**: Trail with 9-EMA
**Stop**: $0.02 below broken resistance (now support)

### 8. TIDAL WAVE / BOUNCY BALL
**Description**: Fading exhausted moves with 3+ weaker bounces
**Entry**: After 3+ iterations of progressively weaker bounces
**Setup Requirements**:
- 3+ bounces showing exhaustion pattern
- Each bounce weaker than prior
- Buyers/sellers clearly exhausting
**Exit**: Halves method - half at 2x measured move, half at 3x
**Stop**: Above most recent bounce high (short) or below bounce low (long)

### 9. ORB (Opening Range Breakout) ENHANCED
**Description**: Breakout of opening range (first 5-15 min)
**Entry**: Break of opening range high/low
**Setup Requirements**:
- Clear opening range established
- Volume confirmation on break
- In direction of gap/premarket bias
**Exit**: Trail with bar-by-bar method (2-min if ARVOL > 3)
**Time Exits**: 10:30 AM or 11:30 AM options

### 10. BREAKING NEWS
**Description**: Trading news catalyst immediately
**Entry**: Based on catalyst score (-10 to +10)
**Catalyst Scoring**:
- +10: Acquisition, FDA approval, massive beat → Strong conviction long
- +8/+9: Major beat, significant upgrade → High conviction long
- +6/+7: Solid beat, positive guidance → Standard long
- -6/-7: Significant miss, major downgrade → Standard short
- -8/-9: Major miss, severe guidance cut → High conviction short
- -10: Fraud, bankruptcy, delisting → Strong conviction short
**Avoidance**:
- Overreacting without scoring
- Ignoring market context
- Trading without clear plan
**Key Rule**: Score immediately - first instinct often correct

### 11. FASHIONABLY LATE
**Description**: Late entry after stock proves itself
**Entry**: When 9-EMA crosses VWAP (confirms turn)
**Setup Requirements**:
- Clear turn in price action
- 9-EMA crossing VWAP confirms
**Avoidance**:
- Price action flat/choppy after turn
- 9-EMA flat for 15+ min after turn

### 12. RANGE BREAK
**Description**: Breakout from established range
**Entry**: Break above range high or below range low
**Setup Requirements**:
- S/R needs 3+ touches to be valid
- Volume confirmation required
- Hold above level after break
**Best Market Condition**: Volatile two-way action
**Stop**: $0.01 outside range boundary

### 13. FIRST VWAP PULLBACK
**Description**: First pullback to VWAP after opening move
**Time**: Opening auction (9:30-9:35 AM)
**Entry**: Bounce off VWAP
**Avoidance**:
- Buying too extended/parabolic
- Pullback goes below premarket high
- Choppy or slow opening auction
- Pullback breaks below VWAP
**Exit**: Full exit at target

### 14. FIRST MOVE UP / FIRST MOVE DOWN
**Description**: Fading first move of day
**Time**: Opening auction (9:30-9:35 AM)
**Entry**: Fade of initial directional move
**Avoidance (First Move Up - Short)**:
- Slow controlled buying (buying program)
- Initial buying breaks important resistance
- Buying pressure after entry
- VWAP acts as support
**Avoidance (First Move Down - Long)**:
- Slow controlled selling (selling program)
- Initial selling breaks important support
- Selling pressure after entry
- VWAP acts as resistance
**Exit**: Move2move - half first leg, half second leg

### 15. BELLA FADE
**Description**: Fading extreme opening moves
**Time**: Opening auction (9:30-9:35 AM)
**Entry**: Fade of overextended open
**Avoidance**:
- Negative catalyst weighing on stock
- Stock consolidates near lows for long
- Stock breaks support
- Catalyst more than 8 (too strong)
- Breaking strong technical level
**Exit**: Waves method

### 16. BACK-THROUGH OPEN
**Description**: Trade through opening price on strong catalyst
**Time**: Opening auction (9:30-9:35 AM)
**Entry**: As price breaks through opening level
**Requirements**: Catalyst at least 8+
**Avoidance**:
- Catalyst not at least 8+
- Market trending opposite direction
- Chop or pause after entry - should work right away
- Range-bound market
- Market fading moves
**Exit**: Momentum exit - close below 9-EMA or two-bar break against

### 17. 9 EMA SCALP
**Description**: Scalp on retouch of 9 EMA in trend
**Entry**: Pullback to 9 EMA in established trend
**Avoidance**:
- No strong catalyst or setup
- Choppy opening move
- Too big a move before 9-EMA test (trend near end)
**Exit**: Trail with 9-EMA

### 18. ABC SCALP
**Description**: Trendline break scalp
**Entry**: Break of well-defined trendline
**Avoidance**:
- Trendline not well connected with red bars
- Trendline not smooth with wicks above
- Last candle out of place from trendline

### 19. BIG DOG CONSOLIDATION
**Description**: Extended consolidation breakout
**Entry**: Break of consolidation after 15+ minutes
**Requirements**:
- Consolidation 15+ minutes
- Volume declining into breakout
- Price above VWAP/9-EMA/21-EMA during consolidation
**Avoidance**:
- Consolidation less than 15 minutes
- Volume not declining into breakout
- Price below VWAP/9-EMA/21-EMA during consolidation

### 20. VOLUME CAPITULATION (Stuffed Trade)
**Description**: Reversal on exhaustion volume spike
**Entry**: After extreme volume spike (2x+ the 2nd highest bar)
**Setup Requirements**:
- Capitulation volume 2x or more the 2nd highest volume candle of day
- Move overextended
- Tape confirmation on flush
**Significance**: Buyers/sellers giving up - orders absorbed

### 21. HOD BREAKOUT
**Description**: Breakout above high of day
**Time**: Works best in afternoon
**Entry**: Break above HOD
**Requirements**: Catalyst 9+
**Avoidance**:
- Catalyst less than 9
- Earlier in day (works best afternoon)
- HOD break doesn't hold - reclaims below

### 22. PUPPY DOG
**Description**: Continuation pattern after pullback
**Entry**: Break of consolidation after pullback
**Requirements**: Volume decreasing during consolidation
**Stop**: $0.02 below consolidation low

=== TIME OF DAY RULES ===

**9:30-9:35 AM (Opening Auction)**:
Best for: Back-Through Open, First VWAP Pullback, Bella Fade, First Move Up/Down
Caution: Widest spreads, fastest moves

**9:35-9:45 AM (Opening Drive)**:
Best for: Gap Give and Go, HitchHiker, ORB
Caution: Wide stops, fast moves

**9:45-10:00 AM (Morning Momentum)**:
Best for: Spencer Scalp, Second Chance, Trend Momentum
Caution: Avoid chasing extended moves

**10:00-10:45 AM (Morning Session)**:
Best for: Spencer Scalp, Back$ide, Fashionably Late, Second Chance, Off Sides
PRIME TIME - Best overall trading window

**10:45-11:30 AM (Late Morning)**:
Best for: Back$ide, Second Chance, Range Break, Fashionably Late
Watch for midday transition

**11:30 AM-1:30 PM (Midday)**:
Best for: Mean Reversion, VWAP trades, Off Sides
REDUCE SIZE, be selective, lower volume

**1:30-3:00 PM (Afternoon)**:
Best for: Second Chance, Trend continuation
Only ranging stocks for Spencer Scalp

**3:00-4:00 PM (Close)**:
Best for: Time-of-Day Fade, MOC imbalance plays, HOD Breakout
Increased volatility, wider stops

=== VOLUME RULES ===

**RVOL Thresholds**:
- 1.5x = Minimum In Play
- 2.0x = Strong Interest
- 3.0x = High Conviction
- 5.0x = Exceptional / Ideal for Rubber Band

**Volume Patterns**:
- Consolidation: Volume should DECREASE (50% or less)
- Breakout: Volume should SPIKE (30%+ increase)
- Top 5 Volume: Required for Rubber Band snapback
- Equal Volume Bars: Institutional accumulation

=== MARKET REGIME STRATEGIES ===

**Strong Uptrend (High Strength/Low Weakness)**:
Preferred: Spencer Scalp, HitchHiker, Gap Give and Go, Trend Momentum
Avoid: Short scalps, Fade setups
Size: Full on longs

**Strong Downtrend (High Weakness/Low Strength)**:
Preferred: Tidal Wave, Back$ide inverse, Off Sides short
Avoid: Long scalps, Breakout longs
Size: Full on shorts

**Volatile Two-Way (High Strength/High Weakness)**:
Preferred: Range Break, Second Chance, Off Sides
Avoid: Directional bias trades
Size: Normal to reduced

**Choppy Range (Low Strength/Low Weakness)**:
Preferred: Mean Reversion, VWAP Fade, Range Trading
Avoid: Momentum trades, Breakouts
Size: REDUCED 50%

**Momentum Market (Breakouts Working)**:
Preferred: ORB, HitchHiker, Spencer Scalp, Gap Give and Go
Avoid: Fade trades, Mean reversion
Size: Full

**Mean Reversion Market (Fades Working)**:
Preferred: Off Sides, VWAP Fade, Rubber Band, Back$ide
Avoid: Breakout trades, Momentum continuation
Size: Normal

=== UNIVERSAL AVOIDANCE RULES ===
1. Fighting the bigger picture trend
2. Trading against SPY/QQQ/IWM direction
3. Overtrading in choppy conditions
4. Ignoring market context
5. Setting monetary profit goals
6. Trading without predefined stop loss
"""

def get_full_strategy_knowledge() -> str:
    """Returns complete strategy knowledge for AI context"""
    return STRATEGY_KNOWLEDGE

def get_strategy_by_name(name: str) -> str:
    """Returns specific strategy information"""
    name_lower = name.lower().replace(" ", "_").replace("-", "_")
    
    strategies = {
        "rubber_band": """
RUBBER BAND SCALP:
- Mean reversion when price extends from 9 EMA
- Entry: Snapback candle (double bar break) in top 5 volume
- Max 2 attempts per day per stock
- Avoid in trending markets
- Stop: $0.02 below snapback candle low
""",
        "spencer_scalp": """
SPENCER SCALP:
- Breakout from tight consolidation near HOD
- Consolidation < 20% of day's range, 20+ min ideal
- Volume decreasing, then spike on break
- Avoid after 3 PM, after 3 legs
- Exit in thirds: 1R, 2R, 3R
""",
        "hitchhiker": """
HITCHHIKER:
- Early momentum entry via 5-20 min consolidation
- Must setup before 9:59 AM
- Clean consolidation (no chop/wicks)
- One and done - no re-entry
""",
        "gap_give_go": """
GAP GIVE AND GO:
- Continuation after brief consolidation in gap direction
- Must trigger before 9:45 AM
- Max 7 min consolidation, above support
- Re-entry allowed within 3 min
""",
        "backside": """
BACK$IDE:
- Reversal from overextended move
- Higher high/higher low pattern
- Range > halfway LOD to VWAP
- Exit at VWAP, one and done
""",
        "off_sides": """
OFF SIDES:
- Fade failed breakout in range
- Double high/double low establishes zone
- Avoid day 1 breakouts with 8+ catalyst
- One and done
""",
        "second_chance": """
SECOND CHANCE:
- Retest of broken level
- Never take 3rd time
- Trail with 9-EMA
""",
    }
    
    return strategies.get(name_lower, f"Strategy '{name}' details not found in quick reference.")
