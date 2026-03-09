# SMB Capital Integration Analysis

## Current State vs. SMB Methodology

### Key SMB Concepts (From User's Research)

#### 1. Setup vs Trade Distinction
- **Setup**: Repeatable high-probability pattern with proven edge (the "what")
- **Trade**: Real-time execution of that setup within specific context (the "how")

#### 2. The 5 Variable Score
| Variable | Description | Our Current Implementation |
|----------|-------------|---------------------------|
| **Big Picture** | Is SPY/Sector helping or hurting? | Partial (market_regime) |
| **Intraday Fundamentals** | Why is the stock moving? | Partial (catalyst_score) |
| **Technical Level** | Clear level to trade against? | Yes (S/R service) |
| **Reading the Tape** | Hidden Seller/Aggressive Buyer? | Basic (tape_reading) |
| **Intuition** | Historical pattern recognition | Missing |

#### 3. Execution Styles (CRITICAL GAP)
| Style | Description | Target R | Win Rate | Our Status |
|-------|-------------|----------|----------|------------|
| **Move2Move (M2M)** | Scalp - capture immediate move | 1R | 60-70% | NOT IMPLEMENTED |
| **Trade2Hold (T2H)** | Intraday swing - hold for Reason2Sell | 3-5R | 40-50% | NOT IMPLEMENTED |
| **A+ Trade** | Full conviction when all align | 10R+ | Variable | Partial (grade A) |

#### 4. Tiered Entry System
| Tier | Description | Our Status |
|------|-------------|------------|
| **Tier 1 (Feelers)** | Starter position at key level | NOT IMPLEMENTED |
| **Tier 2 (Confirmation)** | Add on tape confirmation | NOT IMPLEMENTED |
| **Tier 3 (A+ Size)** | Full size when all align | NOT IMPLEMENTED |

#### 5. Reasons2Sell Checklist
| Reason | Description | Our Status |
|--------|-------------|------------|
| Price Target Reached | Hit predetermined level | Yes |
| Trend Violation | 9 EMA break | Partial |
| Thesis Invalidation | Fundamental reason invalid | NOT TRACKED |
| Market Resistance | SPY/QQQ hits major level | NOT TRACKED |
| Tape Exhaustion | Volume dissipates | Basic |
| Parabolic Extension | Too far from value | NOT TRACKED |
| Breaking News | Fresh headlines | NOT TRACKED |
| End of Day | Close before market close | Yes |

---

## Restructuring Recommendations

### Phase 1: Trade Style Classification

**Add `trade_style` to LiveAlert and TradeIdea models:**
```python
class TradeStyle(Enum):
    MOVE_2_MOVE = "move_2_move"  # Scalp for 1R
    TRADE_2_HOLD = "trade_2_hold"  # Swing for 3R+
    A_PLUS = "a_plus"  # Max conviction
```

**Auto-detect based on setup type:**
- M2M: `spencer_scalp`, `9_ema_scalp`, `abc_scalp`, `gap_give_go`, `first_vwap_pullback`
- T2H: `orb`, `breakout`, `hod_breakout`, `hitchhiker`, `second_chance`
- Context-dependent: `rubber_band`, `vwap_bounce` (depends on market regime)

---

### Phase 2: SMB 5-Variable Scoring

**Replace current checklist with SMB's exact variables:**

```python
@dataclass
class SMBVariableScore:
    big_picture: int  # 1-10 (SPY trend, sector strength)
    intraday_fundamental: int  # 1-10 (catalyst score)
    technical_level: int  # 1-10 (S/R clarity)
    tape_reading: int  # 1-10 (order flow quality)
    intuition: int  # 1-10 (pattern recognition confidence)
    
    @property
    def total_score(self) -> int:
        return (self.big_picture + self.intraday_fundamental + 
                self.technical_level + self.tape_reading + self.intuition)
    
    @property
    def is_a_plus(self) -> bool:
        return self.total_score >= 40 and min(self.big_picture, 
            self.intraday_fundamental, self.technical_level, 
            self.tape_reading) >= 7
```

---

### Phase 3: Setup Categories (Restructure)

**Map all setups to SMB categories:**

```python
SETUP_CATEGORIES = {
    # Trend & Momentum (Works in STRONG_UPTREND/DOWNTREND)
    "trend_momentum": [
        "opening_drive", "hitchhiker", "gap_give_go", "gap_pick_roll",
        "orb", "hod_breakout", "breakout", "relative_strength"
    ],
    
    # Catalyst-Driven (Breaking news, fundamentals changed)
    "catalyst_driven": [
        "breaking_news", "first_vwap_pullback", "back_through_open",
        "up_through_open", "first_move_up", "first_move_down"
    ],
    
    # Reversal/Counter-Trend (Mean reversion, fades)
    "reversal": [
        "rubber_band", "vwap_bounce", "vwap_fade", "bella_fade",
        "off_sides", "backside", "mean_reversion", "time_of_day_fade",
        "tidal_wave", "volume_capitulation", "gap_fade"
    ],
    
    # Consolidation (Flag breaks, squeezes)
    "consolidation": [
        "spencer_scalp", "big_dog", "puppy_dog", "squeeze",
        "range_break", "chart_pattern"
    ],
    
    # Specialized Execution
    "specialized": [
        "fashionably_late", "second_chance", "9_ema_scalp", "abc_scalp"
    ]
}
```

---

### Phase 4: Reasons2Sell Framework

**New service: `/backend/services/reasons2sell_service.py`**

```python
class Reason2Sell(Enum):
    PRICE_TARGET = "price_target"
    TREND_VIOLATION = "trend_violation"
    THESIS_INVALID = "thesis_invalid"
    MARKET_RESISTANCE = "market_resistance"
    TAPE_EXHAUSTION = "tape_exhaustion"
    PARABOLIC_EXTENSION = "parabolic_extension"
    BREAKING_NEWS = "breaking_news"
    END_OF_DAY = "end_of_day"
    GIVE_BACK_RULE = "give_back_rule"  # 30-50% of peak profit

async def check_reasons_to_sell(position: Position) -> List[Reason2Sell]:
    """
    Real-time check for all Reasons2Sell.
    Called every tick for Trade2Hold positions.
    """
    triggers = []
    
    # Check each reason...
    if position.unrealized_pnl >= position.target_price * position.shares:
        triggers.append(Reason2Sell.PRICE_TARGET)
    
    if price_below_9ema(position.symbol):
        triggers.append(Reason2Sell.TREND_VIOLATION)
    
    # etc...
    
    return triggers
```

---

### Phase 5: Level 2 "Box" Structure

**Enhance TapeReading with SMB's Box metrics:**

```python
@dataclass
class Level2Box:
    # Level 1 (Summary)
    symbol: str
    last_price: float
    net_change: float
    net_change_pct: float
    best_bid: float
    best_ask: float
    spread: float
    
    # Level 2 (Depth)
    bid_depth: List[Dict]  # [{price, size, source}]
    ask_depth: List[Dict]
    thick_levels: List[float]  # Large size levels
    
    # Time & Sales (Tape)
    tape_velocity: float  # Prints per second
    green_vs_red: float  # Ratio of hitting ask vs bid
    large_prints: List[Dict]  # Prints > 10k shares
    
    # SMB Signals
    hidden_seller: bool
    aggressive_buyer: bool
    absorption_detected: bool
    stuffed_pattern: bool
    re_bid_signal: bool
    re_offer_signal: bool
    
    def score_tape(self) -> int:
        """Score 1-10 based on SMB tape reading criteria"""
        score = 5  # Neutral start
        
        if self.aggressive_buyer:
            score += 2
        if self.re_bid_signal:
            score += 2
        if self.hidden_seller:
            score -= 2
        if self.stuffed_pattern:
            score -= 2
        # etc...
        
        return max(1, min(10, score))
```

---

### Phase 6: Tiered Entry System

**New service: `/backend/services/tiered_entry_service.py`**

```python
@dataclass
class TieredPosition:
    symbol: str
    direction: str  # "long" or "short"
    
    # Tier entries
    tier_1_shares: int = 0
    tier_1_price: float = 0
    tier_1_reason: str = ""  # "Key level reached"
    
    tier_2_shares: int = 0
    tier_2_price: float = 0
    tier_2_reason: str = ""  # "Tape confirmed"
    
    tier_3_shares: int = 0
    tier_3_price: float = 0
    tier_3_reason: str = ""  # "A+ alignment"
    
    @property
    def total_shares(self) -> int:
        return self.tier_1_shares + self.tier_2_shares + self.tier_3_shares
    
    @property
    def avg_entry(self) -> float:
        total_cost = (self.tier_1_shares * self.tier_1_price +
                     self.tier_2_shares * self.tier_2_price +
                     self.tier_3_shares * self.tier_3_price)
        return total_cost / self.total_shares if self.total_shares > 0 else 0

def calculate_tier_sizes(
    base_risk: float,  # e.g., $200
    smb_score: SMBVariableScore,
    trade_style: TradeStyle
) -> Dict[str, int]:
    """
    Calculate share counts for each tier based on SMB methodology.
    """
    if trade_style == TradeStyle.MOVE_2_MOVE:
        # M2M: Larger tier 1 (capture immediate move)
        return {"tier_1": 70, "tier_2": 20, "tier_3": 10}
    
    elif trade_style == TradeStyle.TRADE_2_HOLD:
        # T2H: Scaled entry
        return {"tier_1": 30, "tier_2": 40, "tier_3": 30}
    
    elif trade_style == TradeStyle.A_PLUS:
        # A+: Start larger
        return {"tier_1": 40, "tier_2": 30, "tier_3": 30}
```

---

### Phase 7: Daily Report Card (DRC)

**New service: `/backend/services/daily_report_card_service.py`**

```python
@dataclass
class DailyReportCard:
    date: str
    
    # Big Picture Metrics
    total_pnl: float
    total_r_captured: float
    best_trade: Dict
    worst_trade: Dict
    
    # Setup & Execution Audit (1-5 each)
    selection_score: int  # Did I trade stocks In Play?
    patience_score: int  # Did I wait for triggers?
    risk_mgmt_score: int  # Did I hit out when invalid?
    sizing_score: int  # Did I push A+ setups?
    
    # Trade Details
    trades: List[Dict]  # Each with setup, style, 1R, result, reason2sell
    
    # Reflection
    a_plus_setup: str
    held_for_reason2sell: bool
    tape_note: str
    
    # Tomorrow
    one_thing_to_improve: str
    one_thing_to_repeat: str
    
    def calculate_avg_win_r(self) -> float:
        wins = [t for t in self.trades if t["result_r"] > 0]
        return sum(t["result_r"] for t in wins) / len(wins) if wins else 0
    
    def calculate_avg_loss_r(self) -> float:
        losses = [t for t in self.trades if t["result_r"] < 0]
        return abs(sum(t["result_r"] for t in losses) / len(losses)) if losses else 0
```

---

## Implementation Priority

### P0 - Foundation (Do First)
1. Add `TradeStyle` enum (M2M/T2H/A+)
2. Map existing setups to styles
3. Add SMB 5-Variable scoring

### P1 - Core SMB Features
4. Implement Reasons2Sell framework
5. Add tiered entry tracking
6. Enhance tape reading with Box metrics

### P2 - Advanced Features
7. Daily Report Card
8. Auto-detection of M2M vs T2H based on context
9. AI integration for SMB coaching

---

## Files to Modify

| File | Changes |
|------|---------|
| `/backend/services/ev_tracking_service.py` | Add TradeStyle, SMBVariableScore |
| `/backend/services/enhanced_scanner.py` | Map setups to categories/styles |
| `/backend/models/alert.py` | Add trade_style, smb_score fields |
| `/backend/services/reasons2sell_service.py` | NEW - Reasons2Sell framework |
| `/backend/services/tiered_entry_service.py` | NEW - Tiered entry system |
| `/backend/services/daily_report_card_service.py` | NEW - DRC tracking |
| `/backend/services/tape_reading_service.py` | NEW - Enhanced Level 2 Box |

---

## SMB Setup-to-Trade Mapping Reference

### Trend & Momentum Setups → Typical Trades
| Setup | Default Style | Long Rules | Short Rules |
|-------|---------------|------------|-------------|
| Opening Drive | M2M | Break of 1-5 min high on gap up | Break of 1-5 min low on gap down |
| Gap and Go | T2H | 1-min/5-min high break after open | Inverse |
| Pullback to VWAP | T2H | Bounce off VWAP + re-bid on tape | Rejection at VWAP + re-offer |
| Flag Break | M2M/T2H | Break of tight range above level | Break of tight range below level |
| Trend Join | T2H | Enter on pullback during Day 1 trend | Enter on pop during Day 1 downtrend |

### Catalyst-Driven Setups → Typical Trades
| Setup | Default Style | Long Rules | Short Rules |
|-------|---------------|------------|-------------|
| Day 2 Play | T2H | Buy Day 1 high flyer that holds gains | Short Day 1 laggard that fails bounce |
| Earnings Gap | T2H | Post-earnings beat clears pre-market highs | Post-earnings miss breaks lows |
| Headline Trade | T2H | Buy on FDA approval, partnerships | Short on investigation, dividend cuts |
| Changing Fundamentals | T2H | Major positive catalyst | Major negative catalyst |

### Reversal/Counter-Trend Setups → Typical Trades
| Setup | Default Style | Long Rules | Short Rules |
|-------|---------------|------------|-------------|
| Stuffed Play | M2M | Broke lower but quickly re-bid above support | Broke higher but stuffed by hidden seller |
| Mean Reversion | M2M | Climax volume spike at range bottom | Parabolic move too far from 20 EMA |
| VWAP Reclaim | T2H | Weak stock breaks and holds above VWAP | Strong stock breaks and holds below VWAP |
| Rubber Band | M2M | 2.5%+ extension from EMA9, snapback | Inverse |

### Specialized Execution Styles
| Style | Goal | Target R | Entry Rule | Exit Rule |
|-------|------|----------|------------|-----------|
| Move2Move | Immediate next level | 1R | Full size on tape confirmation | Exit on first momentum pause |
| Trade2Hold | Multi-point capture | 3-5R | Tiered entry | Only exit on Reason2Sell |
| A+ Setup | Max conviction | 10R+ | All 5 variables align (>40 score) | Trail with 9 EMA, give back rule |
| Fashionably Late | Late-day momentum | 2R | After 10:30 AM when noise settles | Measured move |

---

## R-Multiple Scoring Legend

| R Result | Assessment |
|----------|------------|
| Negative R | Unacceptable - failed to follow stop |
| 0R to 1R | Break-even - scalping too much or exiting early |
| 2R to 5R | Trading system correctly - catching the "meat" |
| 10R+ | Big Dog trade - scaled in correctly, held until trend end |

**Key Insight**: If average win = 1R and average loss = 1R, you have ZERO EDGE after commissions. Goal: Average Win > 2R.
