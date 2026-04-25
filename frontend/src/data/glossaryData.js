/**
 * TradeCommand Glossary & Logic Reference
 * Comprehensive definitions of all trading terms, calculations, and scoring logic
 */

export const glossaryData = {
  // ==================== CATEGORIES ====================
  categories: [
    { id: 'scores', name: 'Scores & Grades', icon: 'Target', description: 'How we evaluate trading opportunities' },
    { id: 'smb', name: 'SMB Methodology', icon: 'Briefcase', description: 'SMB Capital trading framework' },
    { id: 'technical', name: 'Technical Indicators', icon: 'TrendingUp', description: 'Price and volume based signals' },
    { id: 'momentum', name: 'Momentum & Volume', icon: 'Zap', description: 'Market energy and participation' },
    { id: 'levels', name: 'Support & Resistance', icon: 'Activity', description: 'Key price levels' },
    { id: 'strategies', name: 'Trading Strategies', icon: 'Target', description: 'Trade setups and patterns' },
    { id: 'risk', name: 'Risk Management', icon: 'Shield', description: 'Position sizing and protection' },
    { id: 'orders', name: 'Order Types', icon: 'FileText', description: 'How to execute trades' },
    { id: 'market', name: 'Market Context', icon: 'Globe', description: 'Broader market conditions' },
    { id: 'earnings', name: 'Earnings & Catalysts', icon: 'Calendar', description: 'Event-driven opportunities' },
    { id: 'abbreviations', name: 'Abbreviations', icon: 'Hash', description: 'Common shorthand terms' },
    { id: 'app-ui', name: 'App UI Elements', icon: 'BookOpen', description: 'Buttons, badges, chips, and panels you see in the app' },
    { id: 'data-pipeline', name: 'Data Pipeline', icon: 'Activity', description: 'How market data flows from IB Gateway into the app' },
    { id: 'ai-training', name: 'AI Training', icon: 'Brain', description: 'Model lifecycle, readiness gates, and pipeline phases' },
    { id: 'power-user', name: 'Power-User Features', icon: 'Zap', description: 'Keyboard shortcuts, command palette, and pro tools' },
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
- VIX: Volatility Index

**SMB Capital:**
- M2M: Move2Move (scalp)
- T2H: Trade2Hold (swing)
- R2S: Reason2Sell
- EV: Expected Value`,
      relatedTerms: [],
      tags: ['abbreviation', 'acronym', 'shorthand']
    },
    // === SMB CAPITAL METHODOLOGY ===
    {
      id: 'smb-methodology',
      term: 'SMB Capital Methodology',
      category: 'strategies',
      shortDef: 'Professional trading framework with 5-variable scoring, trade styles, and disciplined execution',
      fullDef: `SMB Capital is a proprietary trading firm in NYC known for their systematic approach to intraday trading.

**Core Principles:**
1. **Setup vs Trade**: A setup is a repeatable pattern with edge. A trade is real-time execution of that setup.
2. **5-Variable Scoring**: Every trade idea is scored on Big Picture, Fundamentals, Technical, Tape, and Intuition.
3. **Trade Styles**: M2M (scalp 1R), T2H (swing 3R+), A+ (max conviction 10R+)
4. **Tiered Entries**: Scale in with Tier 1 (feelers), Tier 2 (confirmation), Tier 3 (A+ size)
5. **Reasons2Sell**: Exit rules specific to each trade style

**TradeCommand Integration:**
- SMB 5-Variable score automatically calculated from our existing metrics
- Trade style recommendations based on setup type and context
- Reasons2Sell monitoring for open positions
- AI coaching uses SMB methodology for guidance`,
      relatedTerms: ['trade-style', 'smb-5var', 'reasons2sell', 'tiered-entry'],
      tags: ['smb', 'methodology', 'framework']
    },
    {
      id: 'trade-style',
      term: 'Trade Style (M2M/T2H/A+)',
      category: 'strategies',
      shortDef: 'SMB execution style determining how long to hold and when to exit',
      fullDef: `Trade styles define your execution approach based on setup quality and market conditions.

**Move2Move (M2M):**
- Target: 1R (1x your risk)
- Win Rate: 60-70%
- Exit: First momentum pause or target hit
- Use for: Scalps, weak setups, choppy markets

**Trade2Hold (T2H):**
- Target: 3-5R
- Win Rate: 40-50%
- Exit: Only on Reason2Sell trigger (9 EMA break, target, thesis invalid)
- Use for: Trending setups, strong catalysts

**A+ Setup:**
- Target: 5-10R+
- Exit: Hold until major thesis invalidation
- Criteria: All 5 SMB variables score 7+ (total 40+/50)
- Use for: Best setups of the week

**Color Coding in TradeCommand:**
- M2M: Blue badge
- T2H: Purple badge
- A+: Gold badge`,
      relatedTerms: ['smb-methodology', 'reasons2sell'],
      tags: ['smb', 'trade-style', 'execution']
    },
    {
      id: 'smb-5var',
      term: 'SMB 5-Variable Score',
      category: 'scores',
      shortDef: 'Five key variables scored 1-10 each: Big Picture, Fundamental, Technical, Tape, Intuition',
      fullDef: `SMB Capital's 5-Variable scoring system for trade evaluation.

**The Variables (1-10 each, 50 total):**

1. **Big Picture** - Is the market helping or hurting?
   - SPY/QQQ trend
   - Sector alignment
   - Market regime (momentum vs chop)

2. **Intraday Fundamental** - Why is the stock moving?
   - Catalyst strength (earnings, news)
   - Earnings score (-10 to +10)
   - Fresh vs stale news

3. **Technical Level** - Is there a clear level to trade against?
   - Support/resistance clarity
   - Risk/reward ratio
   - Moving average alignment

4. **Tape Reading** - What is the order flow telling us?
   - Bid/ask spread and size
   - Aggressive buyers/sellers
   - Hidden buyer/seller detection
   - Re-bid/re-offer signals

5. **Intuition** - Pattern recognition confidence
   - Similar historical patterns
   - Setup confidence
   - "Does it feel right?"

**Grades:**
- A+ (40+, no var below 7): Max conviction
- A (35+): Strong setup
- B (25+): Good setup
- C (20+): Moderate
- D (<20): Avoid

**In TradeCommand:**
- SMB Grade shown on alert cards
- 5-variable breakdown in scoring details
- Auto-calculated from existing metrics`,
      relatedTerms: ['smb-methodology', 'tape-score', 'trade-style'],
      tags: ['smb', 'score', '5-variable']
    },
    {
      id: 'tape-score',
      term: 'Tape Score (Level 2 Box)',
      category: 'momentum',
      shortDef: 'Order flow quality score (1-10) based on bid/ask analysis and SMB tape reading signals',
      fullDef: `The Tape Score evaluates real-time order flow using SMB Capital's "Level 2 Box" methodology.

**What We Analyze:**

**Level 1 (Summary):**
- Last price, bid, ask
- Spread (tight = institutional interest)

**Level 2 (Depth):**
- Bid size vs ask size
- Thick levels (large size)

**Tape Signals:**
- **Aggressive Buyer**: Hitting the ask consistently
- **Aggressive Seller**: Hitting the bid consistently
- **Hidden Buyer**: Large buyer absorbing selling
- **Hidden Seller**: Large seller blocking breakouts
- **Re-bid Signal**: Price broke support but immediately re-bid (bullish)
- **Re-offer Signal**: Price broke resistance but immediately re-offered (bearish)
- **Stuffed Pattern**: Failed breakout, hidden seller blocked

**Scoring:**
- 9-10: Very Strong (take trade)
- 7-8: Strong (good confirmation)
- 5-6: Moderate (wait for more)
- 3-4: Weak (consider passing)
- 1-2: Very Weak (avoid)

**In TradeCommand:**
- T:# shown on alert cards
- Full breakdown via API
- Auto-analyzed from quote data`,
      relatedTerms: ['smb-5var', 'bid-ask', 'order-flow'],
      tags: ['smb', 'tape', 'order-flow', 'level2']
    },
    {
      id: 'reasons2sell',
      term: 'Reasons2Sell (R2S)',
      category: 'risk',
      shortDef: 'SMB framework for trade exits - specific triggers for when to close a position',
      fullDef: `Reasons2Sell is SMB Capital's disciplined exit framework. Only exit when a R2S triggers.

**Core Reasons2Sell:**

1. **Price Target Hit** - Predetermined target reached
2. **Trend Violation** - Price broke 9 EMA or key trendline (critical for T2H)
3. **Thesis Invalid** - Original trade reason no longer valid
4. **Market Resistance** - SPY/QQQ hit major level
5. **Tape Exhaustion** - Volume/momentum dried up
6. **Parabolic Extension** - Too far from VWAP/value
7. **Breaking News** - Fresh headlines change the setup
8. **End of Day** - Market close approaching (last 15 min)
9. **Give-Back Rule** - Gave back 30-50% of peak profit
10. **Time Stop** - Trade not working in expected timeframe

**By Trade Style:**
- **M2M**: Target hit, tape slows, time stop
- **T2H**: 9 EMA break, target hit, thesis invalid, give-back
- **A+**: Major trend break, thesis invalid, market resistance

**In TradeCommand:**
- R2S monitor on open positions
- Real-time checking every 30 seconds
- Exit signal alerts with severity (warning vs exit)`,
      relatedTerms: ['trade-style', 'smb-methodology', 'stop-loss'],
      tags: ['smb', 'exit', 'risk-management']
    },
    {
      id: 'tiered-entry',
      term: 'Tiered Entry',
      category: 'risk',
      shortDef: 'SMB position scaling - enter in 3 tiers based on confirmation level',
      fullDef: `Tiered Entry is SMB Capital's risk management approach for scaling into positions.

**The Three Tiers:**

**Tier 1 - Feelers (30%):**
- Initial position at key level
- Requires: Price at trigger, basic tape confirmation
- Purpose: Get skin in the game

**Tier 2 - Confirmation (40%):**
- Add after setup confirms
- Requires: Setup holds, tape improves, pattern validates
- Purpose: Add on confirmation

**Tier 3 - A+ Size (30%):**
- Full conviction add
- Requires: All 5 SMB variables align, A+ grade
- Purpose: Maximize best setups

**Allocations by Trade Style:**
- M2M: 70/20/10 (front-loaded for quick moves)
- T2H: 30/40/30 (gradual scaling)
- A+: 40/30/30 (aggressive but controlled)

**In TradeCommand:**
- Tier calculator API: /api/smb/tiered-entry/calculate
- Automatically adjusts for grade (A = more aggressive)
- Risk-based share calculation`,
      relatedTerms: ['trade-style', 'position-sizing', 'risk-management'],
      tags: ['smb', 'scaling', 'position-sizing']
    },
    {
      id: 'earnings-catalyst-score',
      term: 'Earnings Catalyst Score (-10 to +10)',
      category: 'earnings',
      shortDef: 'SMB scoring for earnings reports based on EPS, revenue, margins, and guidance',
      fullDef: `SMB Capital's earnings scoring system for evaluating post-earnings opportunities.

**The Big Three (Initial Score):**
1. **EPS vs Estimate** - Earnings per share surprise %
2. **Revenue vs Estimate** - Top line surprise %
3. **Margins** - Expanding, flat, or contracting

**Then Add:**
4. **Guidance** - Quarterly and/or full year outlook

**Score Meanings:**
- **+10 Black Swan**: Extreme beat, everything perfect (NVDA 05/24/2023)
- **+9 Exponential**: 15%+ EPS, 8%+ revenue, both guidances raised
- **+8 Double Beat**: 5-10% EPS, 4-6% revenue, guidance raised
- **+7 Inline Beat**: <5% surprise, limited opportunity
- **+5/0 Neutral**: Mixed/no surprise, avoid
- **-7 to -10**: Mirror of positive (shorts)

**Modifiers (±1-2):**
- Management track record (under-promise = +1)
- Competitor comparison (better = +1)
- Revenue guidance missing (efficiency only = -1)

**Trading Approach by Score:**
- ±10: Max conviction, trend all day
- ±9: Back-through-open, buy/short PM high/low
- ±8: Gap Give and Go / Gap Pick and Roll
- ±7: Wait for setup to "fall in lap"
- ±6: Avoid or fade extremes only

**3-Minute Rule:**
Must complete scoring in under 3 minutes. If it takes longer, the edge is unclear.`,
      relatedTerms: ['smb-methodology', 'earnings', 'catalyst-score'],
      tags: ['smb', 'earnings', 'catalyst']
    },

    // ==================== APP UI ELEMENTS ====================
    {
      id: 'data-freshness-badge',
      term: 'Data Freshness Badge',
      category: 'app-ui',
      shortDef: 'The pinned chip in the top-right that tells you whether the app is showing live or stale data.',
      fullDef: `Always-visible status pill that answers the single question "is what I'm looking at live or stale?" in one glance.

**States:**
- **LIVE · Ns ago** (green) — IB pusher is feeding bars to the backend within the last 10s. Trust everything you see.
- **CACHED · Nm ago** (amber) — Pusher is slower than 10s but inside the warning window. Likely fine outside RTH.
- **DELAYED** (amber, RTH only) — Pusher running slow during market hours. Investigate the Windows pusher.
- **STALE · PUSHER DOWN** (red, RTH) — Pusher hasn't pushed in minutes. Charts and scanner are showing the last known close.
- **MARKET CLOSED / WEEKEND / OVERNIGHT** (grey) — Expected quiet state. Nothing to worry about.
- **NO PUSH YET** (grey) — Backend is up but has never received a push from Windows. Start \`ib_data_pusher.py\`.
- **UNREACHABLE** (red) — DGX backend itself is unreachable.

**Click action:**
Opens the **Freshness Inspector** — a full read-out of every subsystem (mongo, IB gateway, historical queue, live subscriptions, cache TTLs, pusher RPC) plus the **Backfill Readiness** card.`,
      relatedTerms: ['freshness-inspector', 'live-data-chip', 'pusher-rpc', 'pusher-health'],
      tags: ['ui', 'badge', 'freshness', 'header']
    },
    {
      id: 'live-data-chip',
      term: 'Live Data Chip',
      category: 'app-ui',
      shortDef: 'Per-panel "is this panel\'s data live?" mini-badge.',
      fullDef: `Smaller cousin of the Data Freshness Badge — drops onto individual panels (e.g. Scanner, Chart) so you can tell whether THAT panel's data is fresh independent of the global state.

**States:**
- **LIVE · Ns** (green) — Live ticks flowing
- **SLOW · Nm** (amber) — Pusher slower than warning threshold
- **DEAD** (red, pulsing) — No ticks at all during RTH
- **—** (grey) — Unknown / out of session

Reads from the same shared \`usePusherHealth\` hook the global badge uses, so all chips show the same source of truth.`,
      relatedTerms: ['data-freshness-badge', 'pusher-health'],
      tags: ['ui', 'chip', 'panel']
    },
    {
      id: 'freshness-inspector',
      term: 'Freshness Inspector',
      category: 'app-ui',
      shortDef: 'The "what is fresh?" diagnostic modal. Click the freshness badge to open.',
      fullDef: `One-click drill-down into every data subsystem. Read-only. Shows:

1. **Backfill Readiness card** at the top — the GREEN/YELLOW/RED "OK to train?" verdict.
2. **Subsystems grid** — colored status pills for: \`mongo\`, \`pusher_rpc\`, \`ib_gateway\`, \`historical_queue\`, \`live_subscriptions\`, \`live_bar_cache\`, \`task_heartbeats\`. Each shows latency / detail.
3. **Live subscriptions list** — every symbol the bot is currently subscribing to via the IB pusher, with ref-count and idle time.
4. **Cache TTL plan** — current market state (rth / extended / overnight / weekend) and the live_bar_cache TTL applied for each.
5. **Pusher RPC** — reachable, URL, enabled, recent failures.

Auto-refreshes every 15 seconds while open.`,
      relatedTerms: ['data-freshness-badge', 'backfill-readiness', 'system-health', 'live-bar-cache', 'ttl-plan', 'pusher-rpc'],
      tags: ['ui', 'modal', 'diagnostic']
    },
    {
      id: 'health-chip',
      term: 'Health Chip',
      category: 'app-ui',
      shortDef: 'Top-right chip in the V5 HUD showing overall system health.',
      fullDef: `Small dot + label. Polls \`/api/system/health\` every 20s and aggregates seven subsystems into one verdict.

**Labels:**
- **all systems** (green) — every subsystem GREEN
- **N warn** (amber) — N subsystems are YELLOW
- **N critical** (red, pulsing) — N subsystems are RED
- **health offline** (red) — backend unreachable

Click → opens the Freshness Inspector for full detail.`,
      relatedTerms: ['freshness-inspector', 'system-health'],
      tags: ['ui', 'chip', 'health']
    },
    {
      id: 'pipeline-hud',
      term: 'Pipeline HUD',
      category: 'app-ui',
      shortDef: 'The top-bar 5-stage trade lifecycle: Scan → Evaluate → Order → Manage → Close.',
      fullDef: `Always-visible heads-up display showing live counts and aggregated metrics for each pipeline stage.

**Stages (left → right):**
1. **SCAN** — # of setups currently being scanned (with timeframe + universe size)
2. **EVALUATE** — # of alerts that passed scanning and are being evaluated by the gate score
3. **ORDER** — pipeline status (filled / pending / ack latency)
4. **MANAGE** — # of open positions, total R, stops breached
5. **CLOSE** — # of closed trades today, win-rate, R closed

The right side shows the **HealthChip**, **⌘K hint**, **ConnectivityCheck**, **PusherHealthChip**, **DeadLetterBadge**, **FlattenAll**, **AccountGuard**, and **SafetyHud**.`,
      relatedTerms: ['gate-score', 'open-positions', 'flatten-all', 'health-chip'],
      tags: ['ui', 'hud', 'pipeline']
    },
    {
      id: 'top-movers-tile',
      term: 'Top Movers Tile',
      category: 'app-ui',
      shortDef: 'Horizontal strip just below the Pipeline HUD showing the biggest movers in your watchlist right now.',
      fullDef: `Reads \`/api/live/briefing-snapshot\` every 30 seconds and ranks the watchlist by absolute % change. Each chip shows symbol, latest price, and signed % change.

**Behaviors:**
- Clicking a chip opens the Enhanced Ticker Modal for that symbol.
- Hidden gracefully when pusher is offline (no point showing noise).
- Defaults to SPY / QQQ / IWM / DIA / VIX but can be overridden.

The 30-second cadence matches the Phase 1 \`live_bar_cache\` TTL during RTH so it doesn't spam the IB pusher.`,
      relatedTerms: ['data-freshness-badge', 'live-bar-cache'],
      tags: ['ui', 'tile', 'movers']
    },
    {
      id: 'briefings',
      term: 'Briefings',
      category: 'app-ui',
      shortDef: 'Time-of-day micro-reports auto-generated by the bot: Morning Prep, Mid-Day Recap, Power Hour, Close Recap.',
      fullDef: `Four scheduled briefings appear in the right column of the Command Center:

- **Morning Prep** (08:30 ET) — Overnight gap analysis, sentiment swings, expected catalysts. The card auto-hides during RTH and walks back to the previous prep on weekends.
- **Mid-Day Recap** (12:00 ET) — Mid-session P&L, open positions, model agreement.
- **Power Hour** (15:00 ET) — Late-session opportunities, exit decisions, sizing for end-of-day moves.
- **Close Recap** (16:00 ET) — Day's results, lessons learned, journal entries.

Each briefing badge shows status: \`PASSED\` (already ran), \`NEW\` (currently active), or scheduled time.`,
      relatedTerms: ['overnight-sentiment'],
      tags: ['ui', 'briefings', 'schedule']
    },
    {
      id: 'scanner-panel',
      term: 'Scanner Panel',
      category: 'app-ui',
      shortDef: 'Left column of the Command Center — live setups the bot is currently watching, ranked by gate score.',
      fullDef: `The scanner panel shows every alert that's passed the configured filters in real time. Each card displays:

- Symbol + price + signed % change
- Setup type (e.g. ORB, breakout, pullback, second-chance)
- Gate score (0-100) — A/B/C tier coloring
- Time since the alert fired
- Click → open the EnhancedTickerModal for full chart + entry details

**Live indicator chip** at the top shows whether the scanner has fresh ticks (green LIVE), is paused (amber), or has gone quiet (red DEAD).

Auto-subscribes the top 10 candidates to the IB pusher's live tick feed (Phase 2) so charts and prices stay current as you click through them.`,
      relatedTerms: ['gate-score', 'live-data-chip', 'subscription-manager'],
      tags: ['ui', 'panel', 'scanner']
    },
    {
      id: 'open-positions',
      term: 'Open Positions Panel',
      category: 'app-ui',
      shortDef: 'Right column tile listing every currently-open position with live P&L, R-multiple, and stop status.',
      fullDef: `Each open-position row shows:

- **Symbol** + side (LONG/SHORT)
- **Qty** + entry price + current price
- **P&L** (signed dollars + signed %)
- **R-multiple** — current P&L expressed as multiples of initial risk (R)
- **Stop status** — distance to stop, breached/not, trailing/fixed
- **Manage actions** — close, adjust stop, partial-close

The panel header shows aggregate **Total R**, # of open positions, and a "stop breached" warning chip if any position is below its stop.`,
      relatedTerms: ['flatten-all', 'r-multiple'],
      tags: ['ui', 'panel', 'positions']
    },
    {
      id: 'unified-stream',
      term: 'Unified Stream',
      category: 'app-ui',
      shortDef: 'Right column event feed: scans, evaluations, orders, fills, wins, losses, skips — chronological.',
      fullDef: `Real-time event timeline with filterable chips at the top:

- \`SCAN\` — new alert detected by the scanner
- \`EVAL\` — alert evaluated by the gate score
- \`ORDER\` — order placed (with side/qty/price)
- \`FILL\` — order filled
- \`WIN\` — position closed at profit
- \`LOSS\` — position closed at loss
- \`SKIP\` — alert filtered out (with reason)

Click any filter chip to narrow the stream. Toggle **LIVE** to pause/resume. Each event row shows a timestamp and a one-line description of what the bot did and why.`,
      relatedTerms: ['gate-score', 'pipeline-hud'],
      tags: ['ui', 'panel', 'stream', 'feed']
    },
    {
      id: 'safety-armed',
      term: 'Safety Armed',
      category: 'app-ui',
      shortDef: 'Green chip indicating the kill-switch is configured and ready to disarm runaway trading.',
      fullDef: `Shows in the Pipeline HUD when:
1. The bot is connected to a real account
2. Daily-loss / per-trade / max-position guards are configured

When tripped, the **Safety Banner** appears at the top of the screen and the **Flatten All** button becomes the primary action.`,
      relatedTerms: ['flatten-all', 'safety-banner'],
      tags: ['ui', 'chip', 'safety']
    },
    {
      id: 'flatten-all',
      term: 'Flatten All Button',
      category: 'app-ui',
      shortDef: 'Emergency-stop button that closes every open position immediately at market.',
      fullDef: `Single click triggers a market-order flush across all open positions on the connected IB account. Use only when the bot has gone wrong or you need to exit fast.

Confirmation dialog requires you to type "FLATTEN" before firing. Logs the flush event to the trade journal with reason "manual flatten".`,
      relatedTerms: ['safety-armed', 'open-positions'],
      tags: ['ui', 'button', 'safety', 'emergency']
    },
    {
      id: 'account-mismatch',
      term: 'ACCOUNT MISMATCH',
      category: 'app-ui',
      shortDef: 'Warning chip that appears when the IB account on the Windows pusher doesn\'t match the configured account.',
      fullDef: `Triggers when:
- The Windows pusher reports an account ID different from \`IB_ACCOUNT_ID\` in your backend env
- Often a harmless race condition on startup before the pusher transmits its initial account snapshot

If it persists past 30s of pusher uptime, double-check the Windows IB Gateway is logged into the right account.`,
      relatedTerms: ['account-guard'],
      tags: ['ui', 'warning', 'account']
    },
    {
      id: 'pipeline-phase',
      term: 'Trading Phase',
      category: 'app-ui',
      shortDef: 'PAPER / LIVE / TEST — the trading mode the bot is currently in.',
      fullDef: `Top-right of the Pipeline HUD shows one of:

- **PAPER** — All orders simulated. No real money at risk. Default for development.
- **LIVE** — Real orders going to IB. Real money at risk.
- **TEST** — Synthetic-bar mode for pipeline validation (no orders fired, no real data consumed).

Toggle via the trading bot config endpoint or the bot's settings panel.`,
      relatedTerms: ['test-mode'],
      tags: ['ui', 'mode', 'paper', 'live']
    },

    // ==================== DATA PIPELINE ====================
    {
      id: 'ib-pusher',
      term: 'IB Pusher',
      category: 'data-pipeline',
      shortDef: 'The Windows-side script that streams live IB Gateway ticks/bars to the DGX backend.',
      fullDef: `\`ib_data_pusher.py\` runs on the Windows PC alongside IB Gateway (Client ID 15). Its job is to:

1. Connect to IB Gateway (which only runs on Windows)
2. Subscribe to live ticks/bars for symbols the DGX backend asks for
3. Push every update over HTTP/WebSocket to the DGX backend

The DGX cannot talk to IB Gateway directly — every market data byte goes through this pusher.

**Phase 1+:** the pusher also exposes an RPC server on port 8765 (\`/rpc/latest-bars\`, \`/rpc/subscribe\`, etc.) so the DGX can pull live session bars on-demand.`,
      relatedTerms: ['ib-gateway', 'pusher-rpc', 'pusher-health', 'turbo-collector'],
      tags: ['data', 'pipeline', 'ib', 'windows']
    },
    {
      id: 'ib-gateway',
      term: 'IB Gateway',
      category: 'data-pipeline',
      shortDef: 'Interactive Brokers\' Java client that hosts the API connection. Runs on the Windows PC.',
      fullDef: `IB Gateway is a stripped-down version of IB Trader Workstation (TWS) used purely as an API host. The IB Pusher and the four Turbo Collectors all connect to it as separate API clients (Client IDs 15–19).

**Status indicators (in the Gateway UI):**
- API Server: connected
- Market Data Farm: ON: usfarm
- Historical Data Farm: ON: ushmds
- API Client: 4 connected (or 5 with the pusher)

If any of these go red, the data pipeline starves.`,
      relatedTerms: ['ib-pusher', 'turbo-collector'],
      tags: ['data', 'ib', 'gateway']
    },
    {
      id: 'turbo-collector',
      term: 'Turbo Collector',
      category: 'data-pipeline',
      shortDef: 'One of 4 parallel Windows scripts that backfill historical bars from IB Gateway in batches of 10 requests.',
      fullDef: `\`ib_historical_collector.py --turbo\` instances run on the Windows PC (Client IDs 16–19). Each one:

1. Polls \`historical_data_requests\` on the DGX backend for pending requests
2. Pulls a batch of 10
3. Sends them to IB Gateway in parallel
4. Walks back further into history with each cycle (newest → oldest)
5. Stores results in \`ib_historical_data\` on MongoDB
6. Reports per-cycle: bars stored, skipped, queue %

**Healthy throughput:** ~6,000–10,000 bars per 10-request cycle, ~2-3 minutes per cycle. Throughput naturally tapers as walkback hits the edge of each symbol's available history (smaller / partial bar returns).

**Skip reasons:** timeout, no_data, rate_limited, pacing_violation. A handful per cycle is normal; floods indicate IB Gateway trouble.`,
      relatedTerms: ['ib-gateway', 'historical-data-requests', 'queue-drained'],
      tags: ['data', 'collector', 'historical', 'backfill']
    },
    {
      id: 'pusher-rpc',
      term: 'Pusher RPC',
      category: 'data-pipeline',
      shortDef: 'On-demand HTTP server inside the IB pusher that lets the DGX request live data without subscribing.',
      fullDef: `Phase 1 of the Live Data Architecture. Endpoints exposed by the Windows pusher on port 8765:

- \`POST /rpc/latest-bars\` — fetch the latest N bars for a symbol/timeframe (used for live session top-up)
- \`POST /rpc/quote-snapshot\` — one-shot quote (used for AI Chat context, immutable trade-close snapshots)
- \`POST /rpc/subscribe\` / \`POST /rpc/unsubscribe\` — Phase 2 ref-counted live tick subscriptions
- \`GET /rpc/health\` — pusher RPC liveness

When **reachable=false**, the app gracefully falls back to MongoDB-stored bars (which may be a few minutes stale).`,
      relatedTerms: ['ib-pusher', 'live-bar-cache', 'subscription-manager'],
      tags: ['data', 'rpc', 'live', 'pipeline']
    },
    {
      id: 'live-bar-cache',
      term: 'Live Bar Cache',
      category: 'data-pipeline',
      shortDef: 'MongoDB-backed TTL cache for live session bars fetched via the pusher RPC.',
      fullDef: `Collection: \`live_bar_cache\`. Keyed by (symbol, bar_size). Stores the most recent live bars pulled from the pusher RPC.

**TTL is dynamic by market state** — see "Cache TTL plan":
- RTH: 30 seconds
- Extended hours: 120 seconds
- Overnight: 900 seconds (15 min)
- Weekend: 3600 seconds (1 hour)
- Active view (symbol you're staring at): 30 seconds regardless of state

Cache hits avoid hitting the pusher RPC. Misses trigger a fresh fetch.`,
      relatedTerms: ['pusher-rpc', 'ttl-plan'],
      tags: ['data', 'cache', 'mongo']
    },
    {
      id: 'ttl-plan',
      term: 'Cache TTL Plan',
      category: 'data-pipeline',
      shortDef: 'How long live_bar_cache entries stay valid before re-fetching, varies by market state.',
      fullDef: `Different market states warrant different freshness budgets. The TTL plan tells the cache how aggressively to expire entries:

| State | TTL | Why |
|-------|-----|-----|
| rth (regular trading hours) | 30s | Prices move, so we want near-real-time |
| extended (pre/post market) | 120s | Lower volume, less need to re-poll |
| overnight | 900s | Almost no movement, conserve pusher load |
| weekend | 3600s | Markets closed, basically static |
| active view | 30s | The symbol you're focused on always gets the freshest treatment |

Visible in the Freshness Inspector → "Cache TTL plan" section.`,
      relatedTerms: ['live-bar-cache', 'freshness-inspector'],
      tags: ['data', 'cache', 'ttl']
    },
    {
      id: 'subscription-manager',
      term: 'Live Subscription Manager',
      category: 'data-pipeline',
      shortDef: 'Ref-counted broker for live tick subscriptions through the pusher RPC.',
      fullDef: `Phase 2 of the Live Data Architecture. When two panels both want live ticks for AAPL, the manager coordinates:

1. First subscribe → calls \`/rpc/subscribe\` once on the pusher, stores \`{symbol, ref_count: 1}\`
2. Second subscribe → just bumps ref_count to 2
3. First unsubscribe → ref_count drops to 1
4. Last unsubscribe → ref_count = 0 → calls \`/rpc/unsubscribe\` and frees the slot

**Cap: 60 concurrent subscriptions** (configurable). Visible in the Freshness Inspector → "Live subscriptions" with each symbol's ref_count and idle time.`,
      relatedTerms: ['pusher-rpc', 'use-live-subscription'],
      tags: ['data', 'subscription', 'live']
    },
    {
      id: 'historical-data-requests',
      term: 'Historical Data Queue',
      category: 'data-pipeline',
      shortDef: 'MongoDB collection holding pending IB historical-data requests for the Turbo Collectors to process.',
      fullDef: `Collection: \`historical_data_requests\`. Each row = one request to IB for a (symbol, bar_size, end_date, duration) chunk.

**Status flow:**
\`pending\` → \`claimed\` (by a collector) → \`completed\` / \`failed\`

**Sources:**
- \`smart_backfill\` enqueues walkback chunks
- \`gap_filler\` enqueues holes detected in \`ib_historical_data\`
- One-off requests for individual symbols

**Health check:** \`pending + claimed = 0\` means the queue is drained — a prerequisite for training. Visible in the Backfill Readiness card.`,
      relatedTerms: ['turbo-collector', 'queue-drained', 'smart-backfill'],
      tags: ['data', 'queue', 'mongo']
    },
    {
      id: 'pusher-health',
      term: 'Pusher Health',
      category: 'data-pipeline',
      shortDef: 'How recently the IB pusher fed the backend. Drives every freshness chip in the app.',
      fullDef: `Backend exposes \`/api/ib/pusher-health\` returning \`{health, age_seconds}\`:

- **green** — last push <10s ago
- **amber** — last push between 10s and 60s
- **red** — last push >60s ago (likely pusher crashed)
- **unknown** — backend has never received a push (pusher never started)

Note the **interpretation depends on market state**:
- During RTH: amber/red is alarming
- Outside RTH: amber/red is normal — markets are quiet`,
      relatedTerms: ['data-freshness-badge', 'live-data-chip', 'ib-pusher'],
      tags: ['data', 'health']
    },

    // ==================== AI TRAINING ====================
    {
      id: 'backfill-readiness',
      term: 'Backfill Readiness',
      category: 'ai-training',
      shortDef: 'Single GREEN/YELLOW/RED verdict answering "is the data clean enough to train on?"',
      fullDef: `\`GET /api/backfill/readiness\` runs five independent checks in parallel and reduces them to one verdict:

1. **queue_drained** — \`historical_data_requests\` pending+claimed = 0, plus low recent-failure count
2. **critical_symbols_fresh** — SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, GOOGL, META, AMZN all fresh on every intraday timeframe
3. **overall_freshness** — % of intraday-universe symbols fresh across critical timeframes (GREEN ≥95%, YELLOW ≥85%, RED otherwise)
4. **no_duplicates** — spot-check critical symbols for duplicate \`(symbol, date, bar_size)\` rows (catches write-path bugs)
5. **density_adequate** — % of symbols with ≥780 5-min bars (anything below is dropped from training)

**ready_to_train** = GREEN only. **Worst-check-wins** for the overall verdict.

The Backfill Readiness Card is pinned to the top of the Freshness Inspector. The same gate disables the **Train All / Full Train / Full Universe / DL Train / Setup Train** buttons until verdict=green.`,
      relatedTerms: ['pre-train-interlock', 'queue-drained', 'critical-symbols-fresh', 'overall-freshness', 'no-duplicates', 'density-adequate'],
      tags: ['ai', 'training', 'readiness', 'gate']
    },
    {
      id: 'pre-train-interlock',
      term: 'Pre-Train Interlock',
      category: 'ai-training',
      shortDef: 'Safety gate that blocks "Start Training" until Backfill Readiness is GREEN. Shift+click overrides.',
      fullDef: `Every "start training" button (\`start-training-btn\`, \`train-all-btn\`, \`full-universe-btn\`, \`train-all-dl-btn\`, \`train-all-setups-btn\`) polls \`/api/backfill/readiness\` every 60 seconds.

**Behavior:**
- 🔴 Not ready + click → blocked with a toast explaining the first blocker.
- 🟢 Ready + click → normal training launch.
- ⇧ **Shift/Alt + click** → conscious override; training fires regardless. Logged with a warning toast.

**Visual gating:**
- Buttons go dim (zinc bg, dimmer text) when blocked.
- A small rose/amber pulsing dot appears next to the label.
- \`data-train-readiness\` attribute exposes the verdict to tests/automation.

**Why:** historical bug — a fat-fingered click during backfill poisoned weeks of validation splits. The interlock makes that class of accident structurally impossible without a conscious override.`,
      relatedTerms: ['backfill-readiness', 'train-readiness-chip', 'shift-click-override'],
      tags: ['ai', 'training', 'safety', 'gate']
    },
    {
      id: 'train-readiness-chip',
      term: 'Train Readiness Chip',
      category: 'ai-training',
      shortDef: 'The colored summary chip above the Train Action buttons in UnifiedAITraining.',
      fullDef: `Shows at a glance whether the gated Train buttons are armed:

- **READY** (green) — backfill clean, all train buttons armed
- **summary string from /api/backfill/readiness** (yellow/red) — followed by the first 1-2 blockers/warnings
- ↻ refresh button — force re-check

Has a hint reminder: "Shift+click any Train button to override."`,
      relatedTerms: ['backfill-readiness', 'pre-train-interlock'],
      tags: ['ai', 'training', 'chip']
    },
    {
      id: 'shift-click-override',
      term: 'Shift+Click Override',
      category: 'ai-training',
      shortDef: 'Holding Shift (or Alt) while clicking a gated button bypasses the readiness check.',
      fullDef: `The escape hatch for the Pre-Train Interlock. Use sparingly:

- For partial retrains where a known-stale subset is acceptable
- For debugging when you want to see whether training itself errors
- When you've manually verified the data despite a yellow verdict

Always logs a warning toast so the override is visible in your action history.`,
      relatedTerms: ['pre-train-interlock'],
      tags: ['ai', 'training', 'override', 'shortcut']
    },
    {
      id: 'queue-drained',
      term: 'Queue Drained Check',
      category: 'ai-training',
      shortDef: '"Is the historical_data_requests queue empty?" — first of the five Backfill Readiness checks.',
      fullDef: `Reads \`historical_data_requests\` and returns:

- 🟢 **GREEN** — pending=0, claimed=0, recent failures <50 in last 24h
- 🟡 **YELLOW** — queue drained but >50 recent failures (look at \`/api/ib-collector/failed-requests\`)
- 🔴 **RED** — anything still in flight (pending+claimed > 0)

Until this is green, training will read incomplete data.`,
      relatedTerms: ['backfill-readiness', 'historical-data-requests'],
      tags: ['ai', 'training', 'queue', 'check']
    },
    {
      id: 'critical-symbols-fresh',
      term: 'Critical Symbols Fresh Check',
      category: 'ai-training',
      shortDef: '"Are SPY/QQQ/DIA/IWM + FAAMG all fresh on every intraday timeframe?"',
      fullDef: `The 10 anchor symbols the training pipeline depends on most: SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, GOOGL, META, AMZN.

**STALE_DAYS thresholds:**
- 1 min / 5 mins: 3 days
- 15 mins / 30 mins: 5 days
- 1 hour: 7 days
- 1 day: 3 days

Any anchor stale on any timeframe → 🔴 RED. The pipeline will produce garbage models without these. Often the very first thing to fix when verdict goes red.`,
      relatedTerms: ['backfill-readiness'],
      tags: ['ai', 'training', 'check', 'symbols']
    },
    {
      id: 'overall-freshness',
      term: 'Overall Freshness Check',
      category: 'ai-training',
      shortDef: 'What fraction of (symbol × intraday timeframe) pairs are fresh across the whole intraday universe.',
      fullDef: `Aggregates freshness across the ADV-gated intraday universe (\`avg_volume ≥ 500_000\`):

- 🟢 **GREEN** ≥95% — full retrain quality
- 🟡 **YELLOW** ≥85% — minor gaps, retrain still possible but expect lower coverage
- 🔴 **RED** <85% — data layer broken, fix before training

Does not require every symbol to be perfect — accepts a long tail of newly-listed / thinly-traded names.`,
      relatedTerms: ['backfill-readiness', 'density-adequate'],
      tags: ['ai', 'training', 'check', 'freshness']
    },
    {
      id: 'no-duplicates',
      term: 'No Duplicates Check',
      category: 'ai-training',
      shortDef: 'Spot-check that no `(symbol, date, bar_size)` row appears more than once.',
      fullDef: `Aggregates the 10 critical symbols across critical timeframes (50 combos) looking for duplicate \`date\` values.

If any combo has dupes → 🔴 RED. Duplicates indicate a write-path bug — the pusher or collector inserted the same bar twice — which silently over-weights those bars during training.

**Fix:** run a dedup pass before retraining. \`db.ib_historical_data.aggregate([{$group: {_id: {symbol, date, bar_size}, n: {$sum:1}}}, {$match: {n: {$gt:1}}}])\``,
      relatedTerms: ['backfill-readiness'],
      tags: ['ai', 'training', 'check', 'data-quality']
    },
    {
      id: 'density-adequate',
      term: 'Density Adequate Check',
      category: 'ai-training',
      shortDef: 'What % of intraday universe has ≥780 5-min bars (the floor for inclusion in training).',
      fullDef: `5-min is the anchor timeframe. <780 bars ≈ <2 trading days of 5-min data — too thin to train on.

Symbols below this threshold are dropped from the training universe (not a hard error). Density check returns:

- 🟢 **GREEN** ≥90% of universe is dense enough
- 🟡 **YELLOW** <90% — note the low_density_sample to know which symbols will be excluded

Never RED — density gaps are warnings, not blockers.`,
      relatedTerms: ['backfill-readiness'],
      tags: ['ai', 'training', 'check', 'density']
    },
    {
      id: 'training-pipeline-phases',
      term: 'Training Pipeline Phases',
      category: 'ai-training',
      shortDef: 'The numbered phases (P1–P9) that a Train All cycle runs through.',
      fullDef: `Each Train All cycle executes phases sequentially. Roughly:

- **P1 — Data Loading** Load \`ib_historical_data\` for the universe + timeframes.
- **P2 — Feature Engineering** Compute technicals, regime, microstructure features.
- **P3 — Triple-Barrier Labeling** Generate forward-looking labels using TB config.
- **P4 — Model Training** Per-timeframe XGBoost / lightgbm fits.
- **P5 — Sector-Relative** Train sector-relative variants.
- **P6 — Calibration** Isotonic / Platt fit per model.
- **P7 — Validation** Hold-out backtest, drift checks, performance scorecards.
- **P8 — Ensembling** Stack daily/intraday predictors into ensembles.
- **P9 — Promotion** Optionally promote new models to production.

Phase progress is visible in the AI Training page during a run.`,
      relatedTerms: ['gate-score', 'preflight'],
      tags: ['ai', 'training', 'phases']
    },
    {
      id: 'preflight',
      term: 'Pre-Flight',
      category: 'ai-training',
      shortDef: 'Synthetic-data validation that catches feature/schema drift before launching the full pipeline.',
      fullDef: `Runs in <5 seconds on synthetic bars (no DB dependency, safe during heavy collection). Validates:

- Feature names match what each model expects
- Output shapes match downstream consumers
- No NaN/Inf leaks at preprocessing boundaries

**Why it exists:** the 2026-04-21 run died 12 minutes into Phase 1 because of feature-list drift. Pre-flight catches that class of bug instantly.

Click the **Pre-flight** button in the Training Pipeline panel before any big retrain.`,
      relatedTerms: ['training-pipeline-phases', 'pre-train-interlock'],
      tags: ['ai', 'training', 'validation']
    },
    {
      id: 'test-mode',
      term: 'Test Mode',
      category: 'ai-training',
      shortDef: 'End-to-end pipeline run on synthetic bars. No real data consumed, no orders fired.',
      fullDef: `Click the **Test mode** button in the Training Pipeline panel to run the full pipeline (P1–P9) on synthetic bars. Useful when:

- You want to validate phase wiring without burning IB requests
- You're debugging a phase failure and need fast iteration
- You want a baseline performance signal that isn't market-dependent

Models trained in test mode are flagged \`source: synthetic\` and never promoted to production.`,
      relatedTerms: ['preflight', 'training-pipeline-phases'],
      tags: ['ai', 'training', 'mode']
    },
    {
      id: 'gate-score',
      term: 'Gate Score',
      category: 'ai-training',
      shortDef: 'Composite 0-100 score the bot computes per alert to decide whether to trade it.',
      fullDef: `Combines: regime fit, model agreement, microstructure signals, sector momentum, calibration confidence.

**Gate thresholds:**
- ≥80: A-tier setup, full sizing
- 60-79: B-tier, normal size
- 40-59: C-tier, half-size or skip
- <40: skip — not worth the risk

In the V5 Pipeline HUD, **Eval** stage shows "% gate pass · avg N" so you can monitor whether today's setups are clearing the bar.`,
      relatedTerms: ['overall-score', 'pipeline-hud'],
      tags: ['ai', 'training', 'score', 'gate']
    },
    {
      id: 'drift-veto',
      term: 'Drift Veto Chip (v5-chip-veto)',
      category: 'ai-training',
      shortDef: 'Per-model badge that flags when a model\'s recent feature distribution has drifted from training.',
      fullDef: `Compares the live feature distribution against the training distribution using KS-test. When divergence exceeds threshold:

- 🟢 **OK** — no significant drift detected
- 🟡 **DRIFT** — distribution shift detected; model output trustworthy but degraded
- 🔴 **VETO** — drift extreme; model's predictions are vetoed for trading

Currently planned for the scorecard tiles but **blocked until the post-backfill retrain finishes**.`,
      relatedTerms: ['calibration-snapshot', 'pre-train-interlock'],
      tags: ['ai', 'model-health', 'drift']
    },
    {
      id: 'calibration-snapshot',
      term: 'Calibration Snapshot',
      category: 'ai-training',
      shortDef: 'Per-model badge showing whether the calibrator (isotonic/Platt) still produces well-calibrated probabilities.',
      fullDef: `Computes Brier score / reliability diagram on a recent window:

- 🟢 calibrated within tolerance
- 🟡 mild miscalibration — predictions still useful but less reliable as probabilities
- 🔴 severe miscalibration — recalibrate or retrain

Same UI slot as the drift-veto chip on each scorecard.`,
      relatedTerms: ['drift-veto'],
      tags: ['ai', 'model-health', 'calibration']
    },

    // ==================== POWER USER FEATURES ====================
    {
      id: 'cmd-k',
      term: '⌘K Command Palette',
      category: 'power-user',
      shortDef: 'Press ⌘K (Mac) or Ctrl+K to open a global symbol/command launcher.',
      fullDef: `Spotlight-style overlay for jumping to anything in the app.

**Modes:**
- **Symbol search** (default) — type a ticker to open its EnhancedTickerModal
- **Recent** — empty input shows your last 5 picks (persisted to localStorage)
- **? help mode** — type \`?<term>\` (e.g. \`?gate\`) to inline-show a glossary entry
- **> command mode** — coming soon: \`>flatten all\`, \`>train all\`, etc.

**Keys:**
- ⌘K / Ctrl+K — toggle palette
- ↑ / ↓ — navigate
- Enter — activate
- Esc — close

The "⌘K search" hint chip in the Pipeline HUD (right side) also opens the palette on click.`,
      relatedTerms: ['recent-symbols', 'cmdk-help-mode'],
      tags: ['ui', 'palette', 'shortcut', 'power-user']
    },
    {
      id: 'recent-symbols',
      term: 'Recent Symbols',
      category: 'power-user',
      shortDef: 'Last 5 symbols you opened from ⌘K — persisted to localStorage for fast re-entry.',
      fullDef: `When you open ⌘K with an empty query, you see your last 5 picks tagged "recent". Selecting one is a single keystroke (Enter).

Stored in \`localStorage\` under \`sentcom.cmd-palette.recent\`. Survives reloads. Tab-independent.`,
      relatedTerms: ['cmd-k'],
      tags: ['palette', 'history']
    },
    {
      id: 'cmdk-help-mode',
      term: '⌘K Help Mode (?term)',
      category: 'power-user',
      shortDef: 'Type `?` then a term in ⌘K to inline-show its glossary definition.',
      fullDef: `Examples:
- \`?gate\` → Gate Score definition
- \`?readiness\` → Backfill Readiness definition
- \`?vwap\` → VWAP definition

Saves you a tab switch when you forget what a badge means. Press Enter to open the full glossary entry in the side drawer.`,
      relatedTerms: ['cmd-k', 'glossary-drawer', 'help-overlay'],
      tags: ['help', 'palette']
    },
    {
      id: 'help-overlay',
      term: 'Help Overlay (Press ?)',
      category: 'power-user',
      shortDef: 'Hold the "?" key to highlight every element on screen with a definition.',
      fullDef: `Press \`?\` (Shift + /) to enter help mode. While active:

- Every glossary-aware element shows a small \`?\` chip
- Hovering reveals a quick definition
- Clicking opens the full entry in the Glossary Drawer

Press \`?\` again or Esc to exit. Doesn't fire when you're typing into an input.

Great for the "what is this thing showing me?" reflex without leaving the page.`,
      relatedTerms: ['glossary-drawer', 'cmdk-help-mode'],
      tags: ['help', 'shortcut']
    },
    {
      id: 'glossary-drawer',
      term: 'Glossary Drawer',
      category: 'power-user',
      shortDef: 'Slide-in side panel that shows the full glossary without leaving your current tab.',
      fullDef: `Open via:
- Floating ❓ button (bottom-right corner of any tab)
- Pressing \`?\` overlay → click any chip
- ⌘K → \`?<term>\` → Enter
- Direct link from inline tooltips

The drawer mirrors the dedicated Glossary page but slides over your current view (e.g. a chart) so you don't lose context. Search, browse by category, deep-link by term.`,
      relatedTerms: ['help-overlay', 'cmd-k'],
      tags: ['help', 'drawer']
    },
    {
      id: 'guided-tour',
      term: 'Guided Tour',
      category: 'power-user',
      shortDef: 'Step-by-step walkthrough overlay highlighting key parts of a feature.',
      fullDef: `Open via ⌘K → type \`>tour\` → pick a tour. Available tours:

- **Command Center** — 6 steps covering Pipeline HUD, Scanner, Chart, Briefings, Stream, Health
- **Backfill → Train workflow** — Readiness, Pre-flight, Train All, Phases (coming soon)

Each step spotlights one element with a popover showing the title + body. Click "Next" to advance, "Skip" to exit. Once you've seen a tour, you won't be re-prompted (saved to localStorage).`,
      relatedTerms: ['help-overlay', 'glossary-drawer'],
      tags: ['help', 'tour', 'onboarding']
    }
  ]
};

export default glossaryData;
