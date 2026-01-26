/**
 * TradeCommand Glossary & Logic Reference
 * Comprehensive definitions of all trading terms, calculations, and scoring logic
 */

export const glossaryData = {
  // ==================== CATEGORIES ====================
  categories: [
    { id: 'scores', name: 'Scores & Grades', icon: 'Target', description: 'How we evaluate trading opportunities' },
    { id: 'technical', name: 'Technical Indicators', icon: 'TrendingUp', description: 'Price and volume based signals' },
    { id: 'momentum', name: 'Momentum & Volume', icon: 'Zap', description: 'Market energy and participation' },
    { id: 'levels', name: 'Support & Resistance', icon: 'Activity', description: 'Key price levels' },
    { id: 'strategies', name: 'Trading Strategies', icon: 'Briefcase', description: 'Trade setups and patterns' },
    { id: 'risk', name: 'Risk Management', icon: 'Shield', description: 'Position sizing and protection' },
    { id: 'orders', name: 'Order Types', icon: 'FileText', description: 'How to execute trades' },
    { id: 'market', name: 'Market Context', icon: 'Globe', description: 'Broader market conditions' },
    { id: 'earnings', name: 'Earnings & Catalysts', icon: 'Calendar', description: 'Event-driven opportunities' },
    { id: 'abbreviations', name: 'Abbreviations', icon: 'Hash', description: 'Common shorthand terms' },
  ],

  // ==================== GLOSSARY ENTRIES ====================
  entries: [
    // === SCORES & GRADES ===
    {
      id: 'overall-score',
      term: 'Overall Score',
      category: 'scores',
      shortDef: 'Composite score (0-100) combining technical, fundamental, and catalyst factors',
      fullDef: `The Overall Score is a weighted composite of multiple factors that determines the quality of a trading opportunity.

**Calculation:**
- Technical Score: 40% weight
- Fundamental Score: 25% weight  
- Catalyst Score: 20% weight
- Confidence Score: 15% weight

**Interpretation:**
- 80-100: Excellent opportunity (A grade)
- 65-79: Good opportunity (B grade)
- 50-64: Moderate opportunity (C grade)
- 35-49: Weak opportunity (D grade)
- 0-34: Poor opportunity (F grade)`,
      relatedTerms: ['technical-score', 'fundamental-score', 'catalyst-score', 'grade'],
      tags: ['score', 'composite', 'evaluation']
    },
    {
      id: 'grade',
      term: 'Grade (A/B/C/D/F)',
      category: 'scores',
      shortDef: 'Letter grade based on Overall Score, indicating opportunity quality',
      fullDef: `Grades provide a quick visual indicator of opportunity quality.

**Grade Breakdown:**
- **Grade A** (80-100): High conviction, strong setup, multiple confirmations
- **Grade B** (65-79): Good setup with minor concerns, trade with normal size
- **Grade C** (50-64): Moderate setup, consider reduced position size
- **Grade D** (35-49): Weak setup, only trade with very small size or avoid
- **Grade F** (0-34): Do not trade, setup fails key criteria

**Color Coding:**
- A = Green
- B = Cyan/Blue
- C = Yellow
- D = Orange
- F = Red`,
      relatedTerms: ['overall-score'],
      tags: ['grade', 'quality', 'rating']
    },
    {
      id: 'technical-score',
      term: 'Technical Score',
      category: 'scores',
      shortDef: 'Score (0-100) based on price action, trend, and technical indicators',
      fullDef: `The Technical Score evaluates the technical setup of a stock.

**Components:**
1. **Trend Alignment** (25 pts max)
   - Price above/below key EMAs (9, 20, 50)
   - Higher highs/lows for uptrend, lower highs/lows for downtrend

2. **RSI Position** (20 pts max)
   - Bonus for RSI 40-60 (optimal entry zone)
   - Penalty for overbought (>70) or oversold (<30)

3. **VWAP Relationship** (15 pts max)
   - Distance from VWAP
   - VWAP as support/resistance

4. **Moving Average Alignment** (15 pts max)
   - EMA 9 > EMA 20 > SMA 50 for bullish
   - Reverse for bearish

5. **MACD Signal** (15 pts max)
   - MACD above signal line = bullish
   - MACD histogram momentum

6. **Price Structure** (10 pts max)
   - Clean breakout patterns
   - Support/resistance respect`,
      relatedTerms: ['rsi', 'macd', 'vwap', 'ema', 'trend'],
      tags: ['score', 'technical', 'indicators']
    },
    {
      id: 'fundamental-score',
      term: 'Fundamental Score',
      category: 'scores',
      shortDef: 'Score based on company financials and valuation metrics',
      fullDef: `The Fundamental Score evaluates the company's financial health.

**Components:**
1. **Market Cap** (20 pts max)
   - Large cap preferred for liquidity
   - Micro caps get lower scores

2. **Sector Strength** (20 pts max)
   - How the sector is performing
   - Rotation patterns

3. **Earnings Quality** (25 pts max)
   - Recent earnings beats/misses
   - Revenue growth

4. **Analyst Ratings** (15 pts max)
   - Buy/hold/sell consensus
   - Recent upgrades/downgrades

5. **Institutional Ownership** (20 pts max)
   - Institutional buying/selling
   - 13F filing changes`,
      relatedTerms: ['market-cap', 'sector'],
      tags: ['score', 'fundamental', 'financials']
    },
    {
      id: 'catalyst-score',
      term: 'Catalyst Score',
      category: 'scores',
      shortDef: 'Score based on upcoming events that could move the stock',
      fullDef: `The Catalyst Score measures potential price-moving events.

**Components:**
1. **Earnings Proximity** (30 pts max)
   - Days until earnings
   - Historical earnings reactions

2. **News Flow** (25 pts max)
   - Recent news sentiment
   - News volume

3. **Options Activity** (20 pts max)
   - Unusual options volume
   - Put/call ratio changes

4. **Short Interest** (15 pts max)
   - Days to cover
   - Short squeeze potential

5. **Analyst Events** (10 pts max)
   - Conference presentations
   - Investor days`,
      relatedTerms: ['earnings', 'iv', 'short-interest'],
      tags: ['score', 'catalyst', 'events']
    },
    {
      id: 'confidence-score',
      term: 'Confidence Score',
      category: 'scores',
      shortDef: 'How confident the system is in the analysis based on data quality',
      fullDef: `The Confidence Score indicates data reliability and analysis certainty.

**Components:**
1. **Data Freshness** (25 pts max)
   - Real-time vs delayed data
   - Last update timestamp

2. **Strategy Matches** (30 pts max)
   - Number of strategies that confirm the setup
   - Quality of matches

3. **Indicator Agreement** (25 pts max)
   - How many indicators align
   - Conflicting signals reduce score

4. **Historical Accuracy** (20 pts max)
   - How similar setups performed historically
   - Win rate of matched patterns`,
      relatedTerms: ['signal-strength', 'strategy-match'],
      tags: ['score', 'confidence', 'reliability']
    },
    {
      id: 'signal-strength',
      term: 'Signal Strength',
      category: 'scores',
      shortDef: 'Percentage of your 77 trading rules/strategies that a stock matches',
      fullDef: `Signal Strength shows how many of your custom trading rules a stock satisfies.

**Calculation:**
Signal Strength = (Rules Matched / 77 Total Rules) × 100%

**Interpretation:**
- **VERY STRONG** (13%+ / 10+ rules): High conviction, multiple confirmations
- **STRONG** (9-12% / 7-9 rules): Good setup, solid confirmations
- **MODERATE** (5-8% / 4-6 rules): Decent setup, some confirmations
- **WEAK** (<5% / 1-3 rules): Few confirmations, proceed with caution

**Why 77 Rules?**
Your custom strategy library contains 77 rules covering:
- Intraday patterns (INT-01 to INT-30)
- Swing setups (SWG-01 to SWG-25)
- Earnings plays (ERN-01 to ERN-12)
- Special situations (SPL-01 to SPL-10)`,
      relatedTerms: ['strategy-match', 'breakout-score'],
      tags: ['signal', 'rules', 'strategies', 'match']
    },
    {
      id: 'breakout-score',
      term: 'Breakout Score',
      category: 'scores',
      shortDef: 'Composite score for breakout quality considering multiple factors',
      fullDef: `The Breakout Score specifically evaluates breakout opportunities.

**Calculation:**
Base = Overall Score
+ RVOL Bonus (up to 10 pts for high relative volume)
+ Strategy Match Bonus (2 pts per matched strategy)
+ Breakout Strength (up to 10 pts based on distance from breakout level)

**Key Factors:**
1. Price breaking clearly above resistance (LONG) or below support (SHORT)
2. Volume confirmation (RVOL >= 1.2x)
3. Trend alignment with breakout direction
4. Multiple strategy confirmations

**Best Breakouts Have:**
- Score 80+
- RVOL 2x+
- 5+ strategy matches
- Clean price level break`,
      relatedTerms: ['resistance', 'support', 'rvol', 'signal-strength'],
      tags: ['breakout', 'score', 'momentum']
    },

    // === TECHNICAL INDICATORS ===
    {
      id: 'rsi',
      term: 'RSI (Relative Strength Index)',
      category: 'technical',
      shortDef: 'Momentum oscillator (0-100) measuring speed and magnitude of price changes',
      fullDef: `RSI measures the speed and magnitude of recent price changes to evaluate overbought or oversold conditions.

**Calculation:**
RSI = 100 - (100 / (1 + RS))
Where RS = Average Gain / Average Loss over 14 periods

**Interpretation:**
- **>70**: Overbought - price may be due for pullback
- **<30**: Oversold - price may be due for bounce
- **40-60**: Neutral zone - trend continuation likely
- **50**: Midpoint, often acts as support/resistance

**Trading Applications:**
- Divergence: Price makes new high/low but RSI doesn't = reversal signal
- Failure swings: RSI breaks its own support/resistance before price
- Trend confirmation: RSI >50 in uptrend, <50 in downtrend`,
      relatedTerms: ['overbought', 'oversold', 'divergence'],
      tags: ['indicator', 'momentum', 'oscillator']
    },
    {
      id: 'macd',
      term: 'MACD (Moving Average Convergence Divergence)',
      category: 'technical',
      shortDef: 'Trend-following momentum indicator showing relationship between two EMAs',
      fullDef: `MACD shows the relationship between two exponential moving averages.

**Components:**
- **MACD Line**: 12-period EMA minus 26-period EMA
- **Signal Line**: 9-period EMA of MACD Line
- **Histogram**: MACD Line minus Signal Line

**Signals:**
1. **Bullish Crossover**: MACD crosses above Signal Line
2. **Bearish Crossover**: MACD crosses below Signal Line
3. **Zero Line Cross**: MACD crosses above/below zero
4. **Divergence**: Price and MACD move in opposite directions

**Best Practices:**
- Use with trend (trade crossovers in trend direction)
- Watch histogram for momentum shifts
- Divergence often precedes reversals`,
      relatedTerms: ['ema', 'crossover', 'divergence'],
      tags: ['indicator', 'trend', 'momentum']
    },
    {
      id: 'vwap',
      term: 'VWAP (Volume Weighted Average Price)',
      category: 'technical',
      shortDef: 'Average price weighted by volume, resets daily',
      fullDef: `VWAP represents the average price a stock has traded at throughout the day, weighted by volume.

**Calculation:**
VWAP = Cumulative(Price × Volume) / Cumulative(Volume)

**Uses:**
1. **Institutional Benchmark**: Large traders aim to execute at or better than VWAP
2. **Support/Resistance**: Price often bounces off VWAP
3. **Trend Indicator**: Above VWAP = bullish, Below = bearish

**Trading Applications:**
- Buy pullbacks to VWAP in uptrend
- Sell rallies to VWAP in downtrend
- VWAP reclaim = potential reversal signal
- First break of VWAP often significant`,
      relatedTerms: ['vwap-distance', 'support', 'resistance'],
      tags: ['indicator', 'volume', 'price', 'intraday']
    },
    {
      id: 'vwap-distance',
      term: 'VWAP Distance',
      category: 'technical',
      shortDef: 'Percentage distance of current price from VWAP',
      fullDef: `VWAP Distance measures how far price has deviated from the day's VWAP.

**Calculation:**
VWAP Distance = ((Current Price - VWAP) / VWAP) × 100%

**Interpretation:**
- **+2% to +5%**: Extended above VWAP, watch for pullback
- **0% to +2%**: Healthy uptrend, near fair value
- **-2% to 0%**: Healthy downtrend or consolidation
- **-2% to -5%**: Extended below VWAP, watch for bounce
- **Beyond ±5%**: Extreme extension, reversion likely`,
      relatedTerms: ['vwap', 'mean-reversion'],
      tags: ['indicator', 'distance', 'vwap']
    },
    {
      id: 'ema',
      term: 'EMA (Exponential Moving Average)',
      category: 'technical',
      shortDef: 'Moving average giving more weight to recent prices',
      fullDef: `EMA is a type of moving average that gives more weight to recent prices.

**Common EMAs:**
- **EMA 9**: Short-term trend (intraday/scalping)
- **EMA 20**: Short-term trend (swing trading)
- **EMA 50**: Medium-term trend
- **EMA 200**: Long-term trend

**Uses:**
1. **Trend Direction**: Price above EMA = uptrend
2. **Dynamic Support/Resistance**: EMAs act as S/R
3. **Crossovers**: Faster EMA crossing slower = signal

**Key Relationships:**
- EMA 9 > EMA 20 > EMA 50 = Strong uptrend
- EMA 9 < EMA 20 < EMA 50 = Strong downtrend
- Converging EMAs = Potential breakout coming`,
      relatedTerms: ['sma', 'crossover', 'trend'],
      tags: ['indicator', 'moving-average', 'trend']
    },
    {
      id: 'sma',
      term: 'SMA (Simple Moving Average)',
      category: 'technical',
      shortDef: 'Average price over a period, equal weighting to all prices',
      fullDef: `SMA is the arithmetic mean of prices over a specified period.

**Calculation:**
SMA = Sum of Closing Prices / Number of Periods

**Common SMAs:**
- **SMA 20**: Often used for Bollinger Bands
- **SMA 50**: Key medium-term level (watched by many)
- **SMA 200**: Long-term trend, major institutional level

**Differences from EMA:**
- SMA is smoother, slower to react
- EMA responds faster to recent price changes
- SMA 200 is more widely watched than EMA 200`,
      relatedTerms: ['ema', 'moving-average'],
      tags: ['indicator', 'moving-average', 'average']
    },
    {
      id: 'atr',
      term: 'ATR (Average True Range)',
      category: 'technical',
      shortDef: 'Measure of volatility based on price range',
      fullDef: `ATR measures market volatility by calculating the average range of price movement.

**Calculation:**
True Range = Max of:
1. Current High - Current Low
2. |Current High - Previous Close|
3. |Current Low - Previous Close|

ATR = 14-period average of True Range

**Uses:**
1. **Stop Loss Placement**: Set stops 1-2x ATR from entry
2. **Position Sizing**: Larger ATR = smaller position
3. **Volatility Filter**: Compare current ATR to average
4. **Target Setting**: Use ATR multiples for profit targets

**Example:**
If ATR = $2.00 and you buy at $100:
- Stop Loss: $98.00 (1 ATR)
- Target: $104.00 (2 ATR = 2:1 risk/reward)`,
      relatedTerms: ['volatility', 'stop-loss', 'position-sizing'],
      tags: ['indicator', 'volatility', 'range']
    },

    // === MOMENTUM & VOLUME ===
    {
      id: 'rvol',
      term: 'RVOL (Relative Volume)',
      category: 'momentum',
      shortDef: 'Current volume compared to average volume, expressed as a multiple',
      fullDef: `RVOL compares today's volume to the average volume at the same time of day.

**Calculation:**
RVOL = Current Volume / Average Volume (same time period)

**Interpretation:**
- **0.5x**: Half normal volume - low interest
- **1.0x**: Normal volume - baseline
- **1.5x**: Elevated volume - increased interest
- **2.0x+**: High volume - significant activity
- **3.0x+**: Very high volume - major event or breakout

**Why It Matters:**
- Volume confirms price moves
- Breakouts need volume confirmation (1.5x+ preferred)
- Low volume rallies/drops often fail
- Watch for volume spikes at key levels`,
      relatedTerms: ['volume', 'breakout', 'confirmation'],
      tags: ['volume', 'momentum', 'relative']
    },
    {
      id: 'volume-profile',
      term: 'Volume Profile',
      category: 'momentum',
      shortDef: 'Distribution of volume at different price levels',
      fullDef: `Volume Profile shows how much volume occurred at each price level.

**Key Concepts:**
- **POC (Point of Control)**: Price with most volume - acts as magnet
- **Value Area**: Price range containing 70% of volume
- **High Volume Nodes**: Prices with significant trading activity
- **Low Volume Nodes**: Prices with little activity - price moves fast through these

**Trading Applications:**
- POC acts as support/resistance
- Breakouts through low volume nodes are faster
- Value area often contains price during consolidation`,
      relatedTerms: ['poc', 'value-area', 'support', 'resistance'],
      tags: ['volume', 'profile', 'levels']
    },
    {
      id: 'momentum',
      term: 'Momentum',
      category: 'momentum',
      shortDef: 'Rate of change in price, indicating strength of trend',
      fullDef: `Momentum measures the velocity of price changes.

**Indicators:**
- RSI: Momentum oscillator
- MACD: Trend momentum
- Rate of Change (ROC): Percentage change
- Momentum indicator: Price difference

**Strong Momentum Signs:**
1. Price making new highs/lows with volume
2. RSI > 50 and rising (bullish) or < 50 and falling (bearish)
3. MACD histogram expanding
4. Higher highs in price AND indicators

**Weak Momentum Signs:**
1. Divergence between price and indicators
2. Volume declining on price moves
3. MACD histogram contracting
4. Lower highs despite higher price`,
      relatedTerms: ['rsi', 'macd', 'divergence'],
      tags: ['momentum', 'trend', 'strength']
    },

    // === SUPPORT & RESISTANCE ===
    {
      id: 'resistance',
      term: 'Resistance',
      category: 'levels',
      shortDef: 'Price level where selling pressure tends to emerge',
      fullDef: `Resistance is a price level where selling pressure historically emerges.

**Types:**
1. **Horizontal Resistance**: Fixed price level from previous highs
2. **Trendline Resistance**: Diagonal line connecting lower highs
3. **Moving Average Resistance**: EMA/SMA acting as ceiling
4. **Psychological Resistance**: Round numbers ($100, $50, etc.)

**Why Resistance Forms:**
- Traders who bought higher looking to exit at breakeven
- Profit-taking from longs
- Short sellers entering positions

**Breakout Confirmation:**
- Price closes above resistance with volume
- Former resistance becomes support
- Ideally 2-3% above level with RVOL > 1.5x`,
      relatedTerms: ['support', 'breakout', 'level'],
      tags: ['levels', 'resistance', 'ceiling']
    },
    {
      id: 'support',
      term: 'Support',
      category: 'levels',
      shortDef: 'Price level where buying pressure tends to emerge',
      fullDef: `Support is a price level where buying pressure historically emerges.

**Types:**
1. **Horizontal Support**: Fixed price level from previous lows
2. **Trendline Support**: Diagonal line connecting higher lows
3. **Moving Average Support**: EMA/SMA acting as floor
4. **VWAP Support**: Daily VWAP level

**Why Support Forms:**
- Value buyers see opportunity
- Short sellers covering
- Technical traders buying the level

**Breakdown Confirmation:**
- Price closes below support with volume
- Former support becomes resistance
- Watch for failed breakdowns (bear traps)`,
      relatedTerms: ['resistance', 'breakdown', 'level'],
      tags: ['levels', 'support', 'floor']
    },

    // === RISK MANAGEMENT ===
    {
      id: 'stop-loss',
      term: 'Stop Loss',
      category: 'risk',
      shortDef: 'Order to exit position at predetermined price to limit loss',
      fullDef: `A stop loss is a predetermined exit point to limit potential losses.

**Placement Methods:**
1. **ATR-based**: 1-2x ATR below entry (recommended)
2. **Percentage**: Fixed % below entry (e.g., 2%)
3. **Technical**: Below key support/resistance
4. **Volatility-adjusted**: Wider stops for volatile stocks

**Best Practices:**
- Always define stop BEFORE entering
- Place stop at level that invalidates thesis
- Don't set stops at obvious levels (round numbers)
- Consider using stop-limit to avoid slippage`,
      relatedTerms: ['atr', 'risk-reward', 'position-sizing'],
      tags: ['risk', 'stop', 'exit']
    },
    {
      id: 'risk-reward',
      term: 'Risk/Reward Ratio (R/R)',
      category: 'risk',
      shortDef: 'Ratio of potential profit to potential loss',
      fullDef: `Risk/Reward ratio compares potential gain to potential loss.

**Calculation:**
R/R = (Target Price - Entry) / (Entry - Stop Loss)

**Example:**
Entry: $100, Stop: $98, Target: $106
R/R = ($106 - $100) / ($100 - $98) = $6 / $2 = 3:1

**Guidelines:**
- **2:1 minimum**: Standard for most trades
- **3:1 preferred**: For breakout trades
- **1:1 acceptable**: Only for very high probability setups

**Why It Matters:**
With 2:1 R/R, you can be wrong 50% of the time and still profit.
With 3:1 R/R, you can be wrong 66% of the time and still profit.`,
      relatedTerms: ['stop-loss', 'target', 'position-sizing'],
      tags: ['risk', 'reward', 'ratio']
    },
    {
      id: 'position-sizing',
      term: 'Position Sizing',
      category: 'risk',
      shortDef: 'How much capital to allocate to a single trade',
      fullDef: `Position sizing determines how much of your account to risk per trade.

**1% Rule:**
Risk no more than 1% of account per trade.

**Calculation:**
Position Size = (Account × Risk%) / (Entry - Stop)

**Example:**
Account: $100,000
Risk: 1% = $1,000
Entry: $50, Stop: $48 (risk = $2/share)
Position Size = $1,000 / $2 = 500 shares

**Adjustments:**
- Higher conviction = up to 2%
- Lower conviction = 0.5%
- Volatile stocks = smaller size
- Low volatility = larger size`,
      relatedTerms: ['risk-reward', 'stop-loss', 'atr'],
      tags: ['risk', 'position', 'size']
    },

    // === ORDER TYPES ===
    {
      id: 'market-order',
      term: 'Market Order',
      category: 'orders',
      shortDef: 'Order to buy/sell immediately at best available price',
      fullDef: `A market order executes immediately at the current market price.

**Pros:**
- Guaranteed execution
- Fast fills
- Simple to use

**Cons:**
- No price control
- May get slippage in fast markets
- Wider spreads = worse fills

**When to Use:**
- Need to enter/exit immediately
- Highly liquid stocks with tight spreads
- Urgent stop-out situations`,
      relatedTerms: ['limit-order', 'slippage'],
      tags: ['order', 'execution', 'market']
    },
    {
      id: 'limit-order',
      term: 'Limit Order',
      category: 'orders',
      shortDef: 'Order to buy/sell at specified price or better',
      fullDef: `A limit order executes only at your specified price or better.

**Buy Limit**: Placed below current price
**Sell Limit**: Placed above current price

**Pros:**
- Price control
- Can get better fills
- Avoid slippage

**Cons:**
- May not fill
- May miss moves
- Requires patience

**When to Use:**
- Entering on pullbacks
- Targeting specific levels
- Less urgent situations`,
      relatedTerms: ['market-order', 'stop-limit'],
      tags: ['order', 'limit', 'price']
    },
    {
      id: 'stop-limit',
      term: 'Stop-Limit Order',
      category: 'orders',
      shortDef: 'Stop order that becomes limit order when triggered',
      fullDef: `Stop-limit combines a stop trigger with a limit order.

**Components:**
- Stop Price: Triggers the order
- Limit Price: Maximum/minimum fill price

**Example (Sell Stop-Limit):**
Stop: $48.00, Limit: $47.50
When price hits $48, a sell limit at $47.50 is placed.

**Pros:**
- Price control even when stopped out
- Avoids bad fills in gaps

**Cons:**
- May not fill if price moves fast
- Stock could gap through both prices`,
      relatedTerms: ['limit-order', 'stop-loss'],
      tags: ['order', 'stop', 'limit']
    },

    // === MARKET CONTEXT ===
    {
      id: 'market-regime',
      term: 'Market Regime',
      category: 'market',
      shortDef: 'Current overall market condition (bullish/bearish/neutral/volatile)',
      fullDef: `Market Regime describes the current state of the overall market.

**Regimes:**
- **BULLISH**: Uptrend, buy dips, favor longs
- **BEARISH**: Downtrend, sell rallies, favor shorts
- **NEUTRAL**: Range-bound, trade levels
- **VOLATILE**: High uncertainty, reduce size

**Determination Factors:**
1. SPY trend (above/below key MAs)
2. VIX level (fear gauge)
3. Breadth (advancing vs declining stocks)
4. Sector rotation

**Trading Implications:**
- Trade WITH the regime, not against
- Bullish regime: 70% long exposure
- Bearish regime: 70% short or cash
- Volatile: Reduce all exposure`,
      relatedTerms: ['vix', 'trend', 'breadth'],
      tags: ['market', 'regime', 'condition']
    },
    {
      id: 'vix',
      term: 'VIX (Volatility Index)',
      category: 'market',
      shortDef: 'Fear gauge measuring expected S&P 500 volatility over 30 days',
      fullDef: `VIX measures expected volatility derived from S&P 500 options prices.

**Interpretation:**
- **<15**: Low fear, complacent market
- **15-20**: Normal volatility
- **20-30**: Elevated fear, caution warranted
- **>30**: High fear, potential bottom
- **>40**: Extreme fear, crisis mode

**Trading Uses:**
- VIX spike often marks market bottoms
- VIX falling = bullish for stocks
- Mean-reverting: extreme readings tend to revert`,
      relatedTerms: ['volatility', 'market-regime', 'iv'],
      tags: ['market', 'volatility', 'fear']
    },

    // === EARNINGS & CATALYSTS ===
    {
      id: 'iv',
      term: 'IV (Implied Volatility)',
      category: 'earnings',
      shortDef: 'Market\'s expectation of future price movement, derived from options prices',
      fullDef: `Implied Volatility reflects the market's expectation of how much a stock will move.

**IV Rank** (0-100):
- 0: IV at yearly low
- 100: IV at yearly high

**Earnings Context:**
- IV rises into earnings (uncertainty)
- IV crushes after earnings (resolved)
- High IV = expensive options
- Low IV = cheap options

**Trading Implications:**
- High IV before earnings = big expected move
- Compare expected move vs historical
- IV crush can hurt long options positions`,
      relatedTerms: ['expected-move', 'earnings', 'options'],
      tags: ['volatility', 'options', 'earnings']
    },
    {
      id: 'expected-move',
      term: 'Expected Move',
      category: 'earnings',
      shortDef: 'Implied range stock might move based on options pricing',
      fullDef: `Expected Move is the range the market expects a stock to trade within.

**Calculation:**
EM = Stock Price × IV × √(Days to Expiration/365)

**Earnings Example:**
Stock at $100, IV = 50%, 1 day to earnings
EM ≈ $100 × 0.50 × √(1/365) ≈ ±$2.60

**Use in Earnings Plays:**
- Compare historical moves to expected move
- If stock typically moves less than expected: sell premium
- If stock typically moves more: buy premium

**Display Format:**
ExpMove: ±7.5% means market expects $100 stock to be between $92.50 and $107.50`,
      relatedTerms: ['iv', 'earnings', 'historical-reaction'],
      tags: ['earnings', 'move', 'expected']
    },
    {
      id: 'earnings-bmo-amc',
      term: 'BMO / AMC (Earnings Timing)',
      category: 'earnings',
      shortDef: 'Before Market Open / After Market Close earnings release timing',
      fullDef: `Indicates when a company releases earnings relative to market hours.

**BMO (Before Market Open):**
- Released before 9:30 AM ET
- Gap up/down at open
- React during regular hours

**AMC (After Market Close):**
- Released after 4:00 PM ET
- React in after-hours/pre-market
- Gap next morning

**Trading Considerations:**
- BMO: Can trade reaction same day
- AMC: May need to hold overnight for reaction
- Liquidity differs between regular hours and extended`,
      relatedTerms: ['earnings', 'gap'],
      tags: ['earnings', 'timing', 'schedule']
    },
    {
      id: 'short-interest',
      term: 'Short Interest',
      category: 'earnings',
      shortDef: 'Number of shares sold short, expressed as % of float',
      fullDef: `Short Interest shows how many shares are currently sold short.

**Metrics:**
- **Short Interest %**: Shares short / Float
- **Days to Cover**: Shares short / Avg daily volume

**Interpretation:**
- **>20%**: High short interest
- **>30%**: Very high, squeeze potential
- **Days to Cover >5**: Difficult to exit shorts quickly

**Short Squeeze:**
When heavily shorted stocks rally:
1. Shorts must buy to cover losses
2. Buying pressure increases price
3. More shorts forced to cover
4. Creates rapid upward spiral`,
      relatedTerms: ['days-to-cover', 'squeeze-score', 'float'],
      tags: ['short', 'interest', 'squeeze']
    },

    // === ABBREVIATIONS ===
    {
      id: 'abbreviations-list',
      term: 'Common Abbreviations',
      category: 'abbreviations',
      shortDef: 'Quick reference for common trading abbreviations',
      fullDef: `**Price & Levels:**
- H/L: High/Low
- O/C: Open/Close
- HOD: High of Day
- LOD: Low of Day
- ATH: All-Time High
- ATL: All-Time Low
- S/R: Support/Resistance

**Technical:**
- MA: Moving Average
- EMA: Exponential Moving Average
- SMA: Simple Moving Average
- RSI: Relative Strength Index
- MACD: Moving Average Convergence Divergence
- ATR: Average True Range
- VWAP: Volume Weighted Average Price
- BB: Bollinger Bands

**Volume:**
- VOL: Volume
- RVOL: Relative Volume
- AVOL: Average Volume
- OBV: On-Balance Volume

**Trading:**
- B/A: Bid/Ask
- PT: Price Target
- SL: Stop Loss
- TP: Take Profit
- R/R: Risk/Reward
- PnL: Profit and Loss
- ROI: Return on Investment

**Options:**
- IV: Implied Volatility
- P/C: Put/Call
- OI: Open Interest
- DTE: Days to Expiration
- ITM/OTM/ATM: In/Out/At The Money

**Time:**
- EOD: End of Day
- PRE: Pre-market
- AH: After Hours
- BMO: Before Market Open
- AMC: After Market Close

**Market:**
- SPY: S&P 500 ETF
- QQQ: Nasdaq 100 ETF
- DIA: Dow Jones ETF
- VIX: Volatility Index`,
      relatedTerms: [],
      tags: ['abbreviation', 'acronym', 'shorthand']
    }
  ]
};

export default glossaryData;
