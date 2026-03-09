# SMB Capital Earnings Scoring System

## Overview
A -10 to +10 scoring system for earnings catalysts that determines trading approach and opportunity quality.

---

## The Big Three (Initial Score)
Score earnings by comparing AGAINST ANALYST EXPECTATIONS (not absolute numbers):
1. **Revenue** - vs analyst consensus
2. **EPS (Earnings Per Share)** - vs analyst consensus  
3. **Margins** - expanding or contracting

Then layer on:
4. **Guidance** - Quarterly and/or Full Year forward-looking statements

### Key Rule: Revenue vs EPS Relationship
- Revenue beat % is typically **60-70% of EPS beat %**
- Example: If EPS beats by 10%, expect revenue beat ~6-7%
- If ratio is significantly different, investigate why

---

## Complete Scoring Scale

### Positive Catalysts (Bullish)

| Score | Name | EPS Surprise | Revenue Surprise | Guidance | Trading Approach |
|-------|------|--------------|------------------|----------|------------------|
| **+10** | Black Swan | Extreme (50%+) | Extreme (15%+) | Both Q & FY raised significantly | Max conviction long, but watch for "sell the news" |
| **+9** | Exponential | 15-50% | 8-15% | Both Q & FY guidance raised | Back-through-open, buy above PM high, trend to HOD |
| **+8** | Double Beat w/ Guidance | 5-10% | 4-6% | Q or FY guidance raised | Gap Give and Go, directional bias, fade dips |
| **+7** | Double Beat (Inline) | <5% | <5% | Reiterated or none | Limited opportunity, only if trade "falls in lap" |
| **+5/0** | Neutral | ~0% | ~0% | Mixed/none | Avoid or fade overextended moves |

### Negative Catalysts (Bearish)

| Score | Name | EPS Surprise | Revenue Surprise | Guidance | Trading Approach |
|-------|------|--------------|------------------|----------|------------------|
| **-5/0** | Neutral | ~0% | ~0% | Mixed/none | Avoid or fade overextended moves |
| **-7** | Double Miss (Inline) | >-5% | >-5% | Reiterated or none | Limited opportunity, only if trade "falls in lap" |
| **-8** | Double Miss w/ Guidance | -5 to -10% | -4 to -6% | Q or FY guidance lowered | Gap Pick and Roll, directional bias, fade bounces |
| **-9** | Exponential Miss | -15 to -50% | -8 to -15% | Both Q & FY guidance lowered | Short below PM low, trend to LOD |
| **-10** | Black Swan | Extreme (<-50%) | Extreme (<-15%) | Both Q & FY lowered significantly | Max conviction short, but watch for capitulation bounce |

---

## Detailed Score Characteristics

### +10 (Black Swan Bullish)
- Everything looks perfect
- Massive hype, everyone is talking about it
- Expectations are through the roof
- Stock price already reflects the good news
- **Example**: NVDA 05/24/2023

### +9 (Exponential Positive)
- Strongly positive expectations
- Analyst upgrades and bullish sentiment
- Media is very optimistic
- High retail interest
- **Trades**: Back-through-open, buy above premarket high, expect HOD close

### +8 (Double Beat with Guidance)
- Positive expectations
- Analyst consensus is for a good report
- Media coverage is positive
- Stock price has already run up ahead of earnings
- **Trades**: Gap Give and Go, fade moves against gap direction

### +7 (Double Beat Inline)
- Slightly positive expectations
- Consensus is for a beat
- Not much hype yet
- Stock price has moved up a little
- **Trades**: Limited - only clear setups that "fall in your lap"

### +5/0 (Neutral)
- Neutral expectations
- Analyst consensus is mixed
- Not much media coverage
- Stock price is range-bound
- Low retail interest
- **Trades**: Fade overextended moves, expect chop and traps

### -5/0 (Neutral Bearish Lean)
- Same as neutral but slight negative bias
- **Trades**: Same approach - fade extremes

### -7 (Double Miss Inline)
- Slightly negative expectations
- Consensus is for a miss
- Not much hype yet
- Stock price has moved down a little
- **Trades**: Limited short opportunities

### -8 (Double Miss with Guidance)
- Negative expectations
- Analyst consensus is for a bad report
- Media coverage is negative
- Stock price has already run down ahead of earnings
- **Trades**: Gap Pick and Roll (gap down, pop, fail, roll down)

### -9 (Exponential Negative)
- Strongly negative expectations
- Analyst downgrades and bearish sentiment
- Media is very pessimistic
- High retail pessimism
- Stock price likely at a trough
- **Trades**: Short below premarket low, trend trades into close at LOD

### -10 (Black Swan Bearish)
- Everything looks terrible
- Massive pessimism, everyone is talking about it
- Expectations are through the floor
- Stock price already reflects the bad news
- **Trades**: Max conviction short, watch for capitulation bounce

---

## Score Modifiers (Adjust ±1-2 points)

### Upgrade Score (+1 to +2)
1. **Management Track Record**: Company has reputation for under-promising and over-delivering (e.g., ROKU example)
2. **Competitor Comparison**: Competitor in same sector had significantly worse numbers
3. **Changing Fundamentals**: This earnings represents a fundamental shift in business model
4. **Beat on All Metrics**: Revenue, EPS, AND Margins all beat expectations

### Downgrade Score (-1 to -2)
1. **Management Track Record**: Company has history of over-promising and under-delivering
2. **Competitor Comparison**: Competitor had significantly better numbers (e.g., ON vs NXPI - NXPI had higher revenue guidance growth)
3. **Mixed Signals**: Beat on EPS but missed on revenue, or vice versa
4. **No Revenue Guidance**: Company only guided up on efficiency (EPS/margins) but not revenue growth
5. **Quarter Timing**: Q1 guidance without full year is less meaningful than Q3/Q4

---

## Trading Rules by Score

### Score ±6 and below: AVOID
- Not worth paying attention to
- High probability of traps and choppy moves
- Possible fade of overextended moves ONLY
- Don't force trades

### Score ±7: LIMITED
- No real new information (analysts were correct)
- Only trade if setup "falls in your lap"
- Expect slightly elevated volatility but directionless
- Fade moves in either direction if extended

### Score ±8: DIRECTIONAL
- Think directionally with the gap
- **Bullish (+8)**: Gap Give and Go - gap up, dip, consolidate, break higher
- **Bearish (-8)**: Gap Pick and Roll - gap down, pop, fail, roll down
- Fade moves AGAINST the gap direction
- Pre-market support/resistance levels become important

### Score ±9: AGGRESSIVE MOMENTUM
- Look for momentum continuation trades
- **Bullish (+9)**: 
  - Back-through-open (price dips then breaks back above open)
  - Buy above premarket high
  - Trend trades after 10am
  - Expect HOD close potential
- **Bearish (-9)**:
  - Short below premarket low
  - Trend trades into close
  - Expect LOD close potential
- Pre-market ranges are critical levels

### Score ±10: MAX CONVICTION (RARE)
- Should only be a handful per earnings cycle
- Go with full conviction in direction
- **But watch for**:
  - +10: "Sell the news" reversal
  - -10: Capitulation bounce
- These are the "Big Dog" trades

---

## Implementation for TradeCommand

### Data Structure
```python
@dataclass
class EarningsCatalystScore:
    symbol: str
    report_date: str
    
    # Big Three vs Expectations
    eps_actual: float
    eps_estimate: float
    eps_surprise_pct: float
    
    revenue_actual: float
    revenue_estimate: float
    revenue_surprise_pct: float
    
    margin_trend: str  # "expanding", "contracting", "flat"
    
    # Guidance
    q_guidance_provided: bool
    q_guidance_direction: str  # "raised", "lowered", "reiterated", "none"
    fy_guidance_provided: bool
    fy_guidance_direction: str
    
    # Calculated
    base_score: int  # -10 to +10
    
    # Modifiers
    management_track_record: str  # "under_promise", "over_promise", "neutral"
    competitor_comparison: str  # "better", "worse", "similar"
    modifier_adjustment: int  # -2 to +2
    
    # Final
    final_score: int  # base_score + modifier_adjustment
    trading_approach: str  # "avoid", "limited", "directional", "aggressive", "max_conviction"
    suggested_setups: List[str]  # ["gap_give_go", "back_through_open", etc.]
```

### Auto-Scoring Logic
```python
def calculate_earnings_score(data: EarningsCatalystScore) -> int:
    """
    Calculate base score from earnings data.
    Must complete in <3 minutes.
    """
    eps_pct = abs(data.eps_surprise_pct)
    rev_pct = abs(data.revenue_surprise_pct)
    direction = 1 if data.eps_surprise_pct > 0 else -1
    
    # Base score from percentages
    if eps_pct >= 50 and rev_pct >= 15:
        base = 10
    elif eps_pct >= 15 and rev_pct >= 8:
        base = 9
    elif eps_pct >= 5 and rev_pct >= 4:
        base = 8
    elif eps_pct >= 2 and rev_pct >= 2:
        base = 7
    else:
        base = 5  # Neutral
    
    # Guidance adjustment
    if data.q_guidance_provided and data.fy_guidance_provided:
        if "raised" in [data.q_guidance_direction, data.fy_guidance_direction]:
            base = min(10, base + 1)
    elif not data.q_guidance_provided and not data.fy_guidance_provided:
        base = max(5, base - 1)
    
    return base * direction

def get_trading_approach(score: int) -> Tuple[str, List[str]]:
    """
    Get trading approach and suggested setups based on score.
    """
    abs_score = abs(score)
    
    if abs_score <= 6:
        return "avoid", ["fade_extreme"]
    elif abs_score == 7:
        return "limited", ["wait_for_setup"]
    elif abs_score == 8:
        if score > 0:
            return "directional", ["gap_give_go", "fade_dips"]
        else:
            return "directional", ["gap_pick_roll", "fade_pops"]
    elif abs_score == 9:
        if score > 0:
            return "aggressive", ["back_through_open", "above_pm_high", "hod_breakout"]
        else:
            return "aggressive", ["below_pm_low", "trend_to_lod"]
    else:  # 10
        if score > 0:
            return "max_conviction", ["opening_drive", "trend_all_day"]
        else:
            return "max_conviction", ["opening_drive_short", "trend_to_lod"]
```

---

## Case Studies from SMB

### Case Study 1: ON Semiconductor (Downgrade 8 → 6)
- **Initial Score**: 8 (slight beats, guidance up)
- **Issue Found**: Guided up on EPS and margins but NOT revenue
- **Competitor Check**: NXPI (competitor) had huge revenue guidance increases
- **Final Score**: 6 (avoid or fade extremes only)
- **Result**: Stock chopped all day, trapped both longs and shorts

### Case Study 2: ROKU (Upgrade 8 → 9)
- **Initial Score**: 8 (slight beats, guidance up)
- **Modifier Found**: Management has consistent track record of under-promising and over-delivering
- **Final Score**: 9 (aggressive momentum)
- **Result**: Stock trended all day, closed at HOD
- **Trades**: Gap Give and Go, Hitchhiker continuation, Above the Clouds afternoon breakout

---

## Quick Reference: Score → Setup Mapping

| Score | Primary Setups | Avoid |
|-------|---------------|-------|
| ±10 | Opening Drive, Trend All Day | Fighting the move |
| ±9 | Back-Through-Open, PM High Break, HOD/LOD Trend | Fading early |
| ±8 | Gap Give and Go, Gap Pick and Roll | Going against gap direction aggressively |
| ±7 | Wait for clear setup | Forcing trades |
| ±6 | Fade extremes ONLY | Any directional bias |
| ±5/0 | None - avoid stock | Everything |

---

## 3-Minute Scoring Checklist

1. **Revenue vs Estimate** (30 sec): Beat or miss? By how much?
2. **EPS vs Estimate** (30 sec): Beat or miss? By how much?
3. **Margins** (30 sec): Expanding, contracting, or flat?
4. **Guidance** (30 sec): Q guidance? FY guidance? Raised, lowered, or reiterated?
5. **Quick Competitor Check** (30 sec): How did main competitor do?
6. **Management Reputation** (30 sec): Under-promise/over-deliver history?

**Total: <3 minutes → Base Score + Modifiers = Final Score**
