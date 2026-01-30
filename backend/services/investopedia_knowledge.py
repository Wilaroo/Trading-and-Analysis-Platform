"""
Investopedia Trading & Investment Knowledge Base
Comprehensive trading knowledge scraped from Investopedia
Integrates: Technical Analysis, Indicators, Candlestick Patterns, Risk Management, Fundamental Analysis
For use by AI Assistant in trade analysis and education
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


# ==================== TECHNICAL INDICATORS ====================

class IndicatorType(Enum):
    MOMENTUM = "momentum"
    TREND = "trend"
    VOLATILITY = "volatility"
    VOLUME = "volume"


@dataclass
class TechnicalIndicator:
    name: str
    indicator_type: IndicatorType
    description: str
    calculation: str
    interpretation: str
    signals: Dict[str, str]
    best_used_with: List[str]
    limitations: List[str]
    trading_tips: List[str]


TECHNICAL_INDICATORS: Dict[str, TechnicalIndicator] = {
    
    "rsi": TechnicalIndicator(
        name="Relative Strength Index (RSI)",
        indicator_type=IndicatorType.MOMENTUM,
        description="Momentum oscillator measuring speed and magnitude of price changes to detect overbought/oversold conditions. Ranges from 0-100.",
        calculation="RSI = 100 - (100 / (1 + (Average Gain / Average Loss))). Standard period is 14.",
        interpretation="""
- RSI above 70: Overbought (potential reversal down)
- RSI below 30: Oversold (potential reversal up)
- RSI at 50: Neutral, no clear momentum
- In uptrends, oversold may be 40-50, overbought may stay above 70
- In downtrends, overbought may be 50-60, oversold may stay below 30
""",
        signals={
            "overbought": "RSI > 70 - Consider selling or taking profits",
            "oversold": "RSI < 30 - Consider buying opportunity",
            "bullish_divergence": "Price makes lower low, RSI makes higher low - Bullish reversal signal",
            "bearish_divergence": "Price makes higher high, RSI makes lower high - Bearish reversal signal",
            "centerline_cross": "RSI crossing above 50 = bullish, below 50 = bearish",
            "failure_swing": "RSI fails to break previous high/low - Strong reversal signal"
        },
        best_used_with=["MACD", "Moving Averages", "Volume", "Support/Resistance levels"],
        limitations=[
            "Can remain overbought/oversold for extended periods in strong trends",
            "Works best in ranging markets, less reliable in strong trends",
            "Divergences can persist before reversal occurs",
            "False signals common without confirmation"
        ],
        trading_tips=[
            "Adjust levels based on trend: Use 40/80 in uptrends, 20/60 in downtrends",
            "Look for divergences at key support/resistance levels",
            "Combine with price action and volume for confirmation",
            "Use longer periods (21-30) for less noise on higher timeframes",
            "RSI works best with daily charts for swing trading"
        ]
    ),
    
    "macd": TechnicalIndicator(
        name="Moving Average Convergence Divergence (MACD)",
        indicator_type=IndicatorType.MOMENTUM,
        description="Trend-following momentum indicator showing relationship between two moving averages. Helps identify trend direction, momentum, and potential reversals.",
        calculation="""
- MACD Line = 12-period EMA - 26-period EMA
- Signal Line = 9-period EMA of MACD Line
- Histogram = MACD Line - Signal Line
""",
        interpretation="""
- MACD above Signal Line: Bullish momentum
- MACD below Signal Line: Bearish momentum
- MACD above zero line: Bullish trend
- MACD below zero line: Bearish trend
- Histogram expanding: Momentum increasing
- Histogram contracting: Momentum decreasing
""",
        signals={
            "bullish_crossover": "MACD crosses above Signal Line - Buy signal",
            "bearish_crossover": "MACD crosses below Signal Line - Sell signal",
            "bullish_divergence": "Price lower low, MACD higher low - Bullish reversal",
            "bearish_divergence": "Price higher high, MACD lower high - Bearish reversal",
            "zero_line_cross": "MACD crossing zero line confirms trend change",
            "histogram_reversal": "Histogram changing direction signals momentum shift"
        },
        best_used_with=["RSI", "ADX", "Price Action", "Volume"],
        limitations=[
            "Lagging indicator - signals come after price has moved",
            "Can produce false signals during consolidation",
            "Doesn't indicate overbought/oversold like RSI",
            "Default settings may not suit all securities/timeframes"
        ],
        trading_tips=[
            "Crossovers more reliable when they align with prevailing trend",
            "Wait for histogram confirmation before entering",
            "Use divergences for early reversal warnings",
            "Best used with daily periods as default",
            "Confirm signals with other indicators like RSI or ADX"
        ]
    ),
    
    "bollinger_bands": TechnicalIndicator(
        name="Bollinger Bands",
        indicator_type=IndicatorType.VOLATILITY,
        description="Volatility indicator using standard deviations around a moving average. Shows overbought/oversold conditions and potential breakouts.",
        calculation="""
- Middle Band = 20-period SMA
- Upper Band = Middle Band + (2 × Standard Deviation)
- Lower Band = Middle Band - (2 × Standard Deviation)
- Contains ~95% of price action within bands
""",
        interpretation="""
- Price near upper band: Potentially overbought
- Price near lower band: Potentially oversold
- Bands widening: Increasing volatility
- Bands narrowing (squeeze): Decreasing volatility, breakout likely
- Price walking the band: Strong trend in that direction
""",
        signals={
            "squeeze": "Narrow bands signal low volatility - Breakout imminent",
            "expansion": "Wide bands signal high volatility - Trend in progress",
            "upper_touch": "Price at upper band - Potential overbought",
            "lower_touch": "Price at lower band - Potential oversold",
            "bollinger_bounce": "Price reverting to middle band from extremes",
            "band_walk": "Price repeatedly touching band = strong trend"
        },
        best_used_with=["RSI", "MACD", "Volume", "Support/Resistance"],
        limitations=[
            "Lagging indicator based on past price data",
            "Can produce false signals in volatile markets",
            "Bands expand during news/earnings, reducing reliability",
            "Not a standalone system - needs confirmation"
        ],
        trading_tips=[
            "Use squeeze for breakout trading opportunities",
            "Combine with RSI to confirm overbought/oversold",
            "Middle band acts as dynamic support/resistance",
            "Adjust periods for different timeframes",
            "Watch for W-bottoms and M-tops at band extremes"
        ]
    ),
    
    "fibonacci_retracement": TechnicalIndicator(
        name="Fibonacci Retracement",
        indicator_type=IndicatorType.TREND,
        description="Tool identifying potential support/resistance levels based on Fibonacci sequence ratios during pullbacks.",
        calculation="""
Key Fibonacci Levels:
- 23.6% retracement
- 38.2% retracement (shallow pullback)
- 50% retracement (not Fibonacci but commonly used)
- 61.8% retracement (golden ratio - most important)
- 78.6% retracement (deep pullback)
""",
        interpretation="""
- 38.2%: Shallow retracement, strong momentum
- 50%: Moderate retracement, normal pullback
- 61.8%: Deep retracement, watch for reversal
- 78.6%: Very deep, trend may be changing
- Price bouncing off level = potential support/resistance
""",
        signals={
            "38_2_bounce": "Bounce at 38.2% = Strong trend continuation likely",
            "50_hold": "Hold at 50% = Normal healthy pullback",
            "61_8_test": "Test of 61.8% = Critical level, last defense",
            "78_6_break": "Break of 78.6% = Trend likely reversing",
            "confluence": "Multiple Fib levels + other support = High probability zone"
        },
        best_used_with=["Moving Averages", "Support/Resistance", "Trend Lines", "Candlestick Patterns"],
        limitations=[
            "Subjective - depends on swing high/low selection",
            "No predictive power on its own",
            "Self-fulfilling prophecy effect",
            "Requires confirmation from price action"
        ],
        trading_tips=[
            "Draw from swing low to swing high in uptrends",
            "Draw from swing high to swing low in downtrends",
            "Look for confluence with other technical levels",
            "Use Fibonacci extensions for profit targets",
            "61.8% is the most reliable level"
        ]
    ),
    
    "moving_averages": TechnicalIndicator(
        name="Moving Averages (SMA/EMA)",
        indicator_type=IndicatorType.TREND,
        description="Trend-following indicators that smooth price data to identify direction. SMA weights all data equally; EMA weights recent data more heavily.",
        calculation="""
- SMA = Sum of closing prices / Number of periods
- EMA = (Current Price × Multiplier) + (Previous EMA × (1 - Multiplier))
- Multiplier = 2 / (Period + 1)
Key periods: 9, 20, 50, 100, 200
""",
        interpretation="""
- Price above MA: Bullish
- Price below MA: Bearish
- Shorter MA above longer MA: Uptrend
- Shorter MA below longer MA: Downtrend
- MA slope indicates trend strength
""",
        signals={
            "golden_cross": "50 MA crosses above 200 MA - Major bullish signal",
            "death_cross": "50 MA crosses below 200 MA - Major bearish signal",
            "price_cross": "Price crossing above/below MA - Trend change",
            "ma_support": "Price bouncing off MA - Dynamic support",
            "ma_resistance": "Price rejected at MA - Dynamic resistance"
        },
        best_used_with=["RSI", "MACD", "Volume", "Price Patterns"],
        limitations=[
            "Lagging indicator - signals come after move starts",
            "Whipsaws in ranging markets",
            "Different periods work for different securities",
            "Can miss significant moves waiting for confirmation"
        ],
        trading_tips=[
            "Use 9 EMA for scalping, 20 EMA for swing trades",
            "50 and 200 SMA for major trend identification",
            "Look for price to 'mean revert' to MAs",
            "Multiple MA confluence = stronger signal",
            "EMA better for short-term, SMA for long-term"
        ]
    ),
    
    "volume": TechnicalIndicator(
        name="Volume Analysis",
        indicator_type=IndicatorType.VOLUME,
        description="Measures number of shares/contracts traded. Confirms price moves and reveals institutional activity.",
        calculation="Volume = Total shares traded in period. RVOL = Current Volume / Average Volume",
        interpretation="""
- High volume + price up = Strong bullish
- High volume + price down = Strong bearish
- Low volume moves = Weak/unsustainable
- Volume precedes price = Leading indicator
- RVOL > 2 = Stock 'In Play'
""",
        signals={
            "volume_breakout": "Breakout with high volume = Confirmed/reliable",
            "volume_dry_up": "Decreasing volume = Trend weakening",
            "climactic_volume": "Extremely high volume spike = Potential exhaustion",
            "accumulation": "Price flat, volume rising = Institutional buying",
            "distribution": "Price flat/falling, high volume = Institutional selling"
        },
        best_used_with=["Price Action", "Support/Resistance", "All other indicators"],
        limitations=[
            "Doesn't indicate direction on its own",
            "Can be manipulated in low-float stocks",
            "Different markets have different volume characteristics"
        ],
        trading_tips=[
            "Always confirm breakouts with volume",
            "Look for volume expansion at key levels",
            "RVOL 2x+ signals stock is 'In Play'",
            "Climactic volume often marks reversals",
            "Volume should confirm the trend"
        ]
    ),
    
    "stochastic": TechnicalIndicator(
        name="Stochastic Oscillator",
        indicator_type=IndicatorType.MOMENTUM,
        description="Momentum indicator comparing closing price to price range over time. Shows overbought/oversold conditions.",
        calculation="""
%K = (Current Close - Lowest Low) / (Highest High - Lowest Low) × 100
%D = 3-period SMA of %K
Standard settings: 14-period lookback
""",
        interpretation="""
- Above 80: Overbought
- Below 20: Oversold
- %K crossing above %D: Bullish
- %K crossing below %D: Bearish
""",
        signals={
            "bullish_crossover": "%K crosses above %D below 20 = Strong buy",
            "bearish_crossover": "%K crosses below %D above 80 = Strong sell",
            "divergence": "Price/Stochastic divergence = Reversal warning"
        },
        best_used_with=["RSI", "MACD", "Support/Resistance"],
        limitations=[
            "Can remain overbought/oversold in trends",
            "Many false signals in trending markets",
            "Better for ranging markets"
        ],
        trading_tips=[
            "Wait for crossover confirmation",
            "Use in ranging markets, not strong trends",
            "Combine with other indicators",
            "Look for divergences at extremes"
        ]
    ),
    
    "atr": TechnicalIndicator(
        name="Average True Range (ATR)",
        indicator_type=IndicatorType.VOLATILITY,
        description="Measures market volatility by decomposing the entire range of an asset price for a period.",
        calculation="""
True Range = Max of:
- Current High - Current Low
- |Current High - Previous Close|
- |Current Low - Previous Close|
ATR = Average of True Range over N periods (usually 14)
""",
        interpretation="""
- High ATR: High volatility
- Low ATR: Low volatility
- Rising ATR: Increasing volatility
- Falling ATR: Decreasing volatility
""",
        signals={
            "stop_placement": "Use 1.5-3x ATR for stop loss distance",
            "breakout_filter": "ATR expansion confirms breakout",
            "position_sizing": "Higher ATR = smaller position size"
        },
        best_used_with=["All indicators for stop placement"],
        limitations=[
            "Doesn't indicate direction",
            "Only measures volatility magnitude"
        ],
        trading_tips=[
            "Use for dynamic stop losses",
            "Multiply ATR by 2-3 for stop distance",
            "Helpful for position sizing",
            "Good for trailing stops"
        ]
    ),
}


# ==================== CANDLESTICK PATTERNS ====================

@dataclass
class CandlestickPattern:
    name: str
    pattern_type: str  # "single", "double", "triple"
    bias: str  # "bullish", "bearish", "neutral"
    description: str
    identification: str
    psychology: str
    reliability: str
    trading_action: str


CANDLESTICK_PATTERNS: Dict[str, CandlestickPattern] = {
    
    "doji": CandlestickPattern(
        name="Doji",
        pattern_type="single",
        bias="neutral",
        description="Open and close are virtually equal, showing indecision in the market.",
        identification="Very small or no real body with wicks on both sides.",
        psychology="Buyers and sellers fought to a standstill. Indecision will eventually resolve.",
        reliability="Important alert pattern. Not a signal itself but warns of pending direction change.",
        trading_action="Wait for confirmation in the next candle. Often precedes reversal."
    ),
    
    "spinning_top": CandlestickPattern(
        name="Spinning Top",
        pattern_type="single",
        bias="neutral",
        description="Similar to doji but with small real body. Shows indecision.",
        identification="Small body centered between upper and lower wicks.",
        psychology="Neither buyers nor sellers could gain control.",
        reliability="Moderate. More significant after extended trends.",
        trading_action="Wait for directional confirmation. Often signals trend exhaustion."
    ),
    
    "hammer": CandlestickPattern(
        name="Hammer",
        pattern_type="single",
        bias="bullish",
        description="Bullish reversal pattern at the bottom of a downtrend.",
        identification="Small body at top, long lower shadow (2x body minimum), little/no upper shadow.",
        psychology="Sellers pushed price down but buyers stepped in and pushed it back up.",
        reliability="Strong when appearing after downtrend with volume confirmation.",
        trading_action="Buy on confirmation (next candle closes higher). Stop below hammer low."
    ),
    
    "hanging_man": CandlestickPattern(
        name="Hanging Man",
        pattern_type="single",
        bias="bearish",
        description="Bearish reversal pattern at the top of an uptrend. Same shape as hammer.",
        identification="Small body at top, long lower shadow, little/no upper shadow. Appears after uptrend.",
        psychology="Sellers showed strength during the day. Bulls managed to close high but weakness shown.",
        reliability="Moderate. Requires confirmation.",
        trading_action="Sell/short on confirmation (next candle closes lower). Stop above high."
    ),
    
    "inverted_hammer": CandlestickPattern(
        name="Inverted Hammer",
        pattern_type="single",
        bias="bullish",
        description="Bullish reversal pattern at bottom of downtrend.",
        identification="Small body at bottom, long upper shadow, little/no lower shadow.",
        psychology="Buyers tried to push up, met resistance, but selling pressure may be exhausting.",
        reliability="Moderate. Needs confirmation.",
        trading_action="Buy on confirmation. Watch for follow-through bullish candle."
    ),
    
    "shooting_star": CandlestickPattern(
        name="Shooting Star",
        pattern_type="single",
        bias="bearish",
        description="Bearish reversal at top of uptrend. Same shape as inverted hammer.",
        identification="Small body at bottom, long upper shadow, little/no lower shadow. After uptrend.",
        psychology="Buyers pushed up but sellers drove price back down. Buying exhaustion.",
        reliability="Strong especially with high volume and at resistance.",
        trading_action="Sell/short on confirmation. Stop above shooting star high."
    ),
    
    "bullish_engulfing": CandlestickPattern(
        name="Bullish Engulfing",
        pattern_type="double",
        bias="bullish",
        description="Strong bullish reversal. Large green candle completely engulfs prior red candle.",
        identification="After downtrend: small red candle followed by larger green candle that engulfs it.",
        psychology="Buyers overwhelmed sellers. Strong shift in sentiment.",
        reliability="High. One of the most reliable reversal patterns.",
        trading_action="Buy on close of engulfing candle. Stop below engulfing candle low."
    ),
    
    "bearish_engulfing": CandlestickPattern(
        name="Bearish Engulfing",
        pattern_type="double",
        bias="bearish",
        description="Strong bearish reversal. Large red candle completely engulfs prior green candle.",
        identification="After uptrend: small green candle followed by larger red candle that engulfs it.",
        psychology="Sellers overwhelmed buyers. Strong sentiment shift to bearish.",
        reliability="High. Very reliable at resistance levels.",
        trading_action="Sell/short on close. Stop above engulfing candle high."
    ),
    
    "morning_star": CandlestickPattern(
        name="Morning Star",
        pattern_type="triple",
        bias="bullish",
        description="Three-candle bullish reversal pattern at bottom of downtrend.",
        identification="Large red candle, small body (star) that gaps down, large green candle closing into first candle.",
        psychology="Downtrend exhausts, indecision (star), then buyers take control.",
        reliability="High. Very reliable reversal signal.",
        trading_action="Buy on completion of pattern. Stop below star low."
    ),
    
    "evening_star": CandlestickPattern(
        name="Evening Star",
        pattern_type="triple",
        bias="bearish",
        description="Three-candle bearish reversal pattern at top of uptrend.",
        identification="Large green candle, small body (star) that gaps up, large red candle closing into first candle.",
        psychology="Uptrend exhausts, indecision (star), then sellers take control.",
        reliability="High. Very reliable reversal signal.",
        trading_action="Sell/short on completion. Stop above star high."
    ),
    
    "three_white_soldiers": CandlestickPattern(
        name="Three White Soldiers",
        pattern_type="triple",
        bias="bullish",
        description="Three consecutive long green candles with small wicks. Strong bullish continuation.",
        identification="Each candle opens within prior body and closes near high. Progressive higher closes.",
        psychology="Strong, sustained buying pressure. Bulls in full control.",
        reliability="High for continuation. Watch for exhaustion if too extended.",
        trading_action="Buy on confirmation. Trail stops under each candle low."
    ),
    
    "three_black_crows": CandlestickPattern(
        name="Three Black Crows",
        pattern_type="triple",
        bias="bearish",
        description="Three consecutive long red candles with small wicks. Strong bearish continuation.",
        identification="Each candle opens within prior body and closes near low. Progressive lower closes.",
        psychology="Strong, sustained selling pressure. Bears in full control.",
        reliability="High for continuation.",
        trading_action="Sell/short on confirmation. Trail stops above each candle high."
    ),
}


# ==================== RISK MANAGEMENT ====================

RISK_MANAGEMENT_RULES = {
    "one_percent_rule": {
        "description": "Never risk more than 1% of trading capital on a single trade",
        "calculation": "Max Risk = Account Size × 0.01",
        "example": "$10,000 account = $100 max risk per trade",
        "advanced": "Some traders use 2% for larger accounts, but 1% is safer"
    },
    
    "position_sizing": {
        "description": "Calculate position size based on risk and stop loss distance",
        "formula": "Position Size = Risk Amount / (Entry Price - Stop Price)",
        "example": "$100 risk, $50 entry, $48 stop = $100 / $2 = 50 shares",
        "rules": [
            "Never exceed max position size even if setup looks perfect",
            "Reduce size in volatile markets",
            "Increase size gradually as account grows"
        ]
    },
    
    "stop_loss_placement": {
        "description": "Where to place stop losses based on technical analysis",
        "methods": [
            "Below recent swing low (long) / above swing high (short)",
            "Below support / above resistance",
            "ATR-based: 1.5-3x ATR from entry",
            "Below pattern invalidation point",
            "Percentage-based: 2-5% from entry depending on volatility"
        ],
        "tips": [
            "Place stops at logical invalidation points, not arbitrary percentages",
            "Don't place stops at obvious round numbers",
            "Give trades room to breathe but protect capital",
            "Move stops to breakeven after 1:1 R is achieved"
        ]
    },
    
    "risk_reward_ratio": {
        "description": "Ratio of potential profit to potential loss",
        "minimum": "2:1 (risk $1 to make $2)",
        "ideal": "3:1 or better",
        "calculation": "(Target Price - Entry) / (Entry - Stop Price)",
        "importance": "With 2:1 R:R, you only need 35% win rate to be profitable"
    },
    
    "expected_value": {
        "description": "Mathematical expectation of a trading system",
        "formula": "EV = (Win Rate × Avg Win) - (Loss Rate × Avg Loss)",
        "example": "60% win rate, 2:1 R:R = (0.6 × 2) - (0.4 × 1) = 1.2 - 0.4 = 0.8R positive",
        "rule": "Only trade systems with positive expected value"
    },
    
    "diversification": {
        "description": "Spread risk across multiple positions and sectors",
        "rules": [
            "Don't have more than 25% of capital in one sector",
            "Limit correlated positions",
            "Max 5-10 open positions at once",
            "Don't over-concentrate in one trade"
        ]
    },
    
    "daily_loss_limit": {
        "description": "Maximum amount willing to lose in one day",
        "guideline": "2-3% of account maximum daily loss",
        "action": "Stop trading for the day if limit is hit",
        "reason": "Prevents emotional revenge trading and large drawdowns"
    },
}


# ==================== SERVICE CLASS ====================

class InvestopediaKnowledgeService:
    """Service for accessing Investopedia trading knowledge"""
    
    def __init__(self):
        self.indicators = TECHNICAL_INDICATORS
        self.candlesticks = CANDLESTICK_PATTERNS
        self.risk_rules = RISK_MANAGEMENT_RULES
    
    def get_indicator_knowledge(self, indicator_name: str) -> Optional[Dict]:
        """Get comprehensive knowledge about a technical indicator"""
        indicator = self.indicators.get(indicator_name.lower())
        if indicator:
            return {
                "name": indicator.name,
                "type": indicator.indicator_type.value,
                "description": indicator.description,
                "calculation": indicator.calculation,
                "interpretation": indicator.interpretation,
                "signals": indicator.signals,
                "best_used_with": indicator.best_used_with,
                "limitations": indicator.limitations,
                "trading_tips": indicator.trading_tips
            }
        return None
    
    def get_candlestick_pattern(self, pattern_name: str) -> Optional[Dict]:
        """Get knowledge about a candlestick pattern"""
        pattern = self.candlesticks.get(pattern_name.lower().replace(" ", "_"))
        if pattern:
            return {
                "name": pattern.name,
                "type": pattern.pattern_type,
                "bias": pattern.bias,
                "description": pattern.description,
                "identification": pattern.identification,
                "psychology": pattern.psychology,
                "reliability": pattern.reliability,
                "trading_action": pattern.trading_action
            }
        return None
    
    def get_all_indicators(self) -> List[str]:
        """Get list of all technical indicators"""
        return list(self.indicators.keys())
    
    def get_all_candlestick_patterns(self) -> List[str]:
        """Get list of all candlestick patterns"""
        return list(self.candlesticks.keys())
    
    def get_bullish_patterns(self) -> List[Dict]:
        """Get all bullish candlestick patterns"""
        return [
            self.get_candlestick_pattern(name)
            for name, pattern in self.candlesticks.items()
            if pattern.bias == "bullish"
        ]
    
    def get_bearish_patterns(self) -> List[Dict]:
        """Get all bearish candlestick patterns"""
        return [
            self.get_candlestick_pattern(name)
            for name, pattern in self.candlesticks.items()
            if pattern.bias == "bearish"
        ]
    
    def get_risk_management_guide(self) -> Dict:
        """Get complete risk management knowledge"""
        return self.risk_rules
    
    def calculate_position_size(self, account_size: float, risk_percent: float, 
                                entry: float, stop: float) -> Dict:
        """Calculate position size based on risk parameters"""
        risk_amount = account_size * (risk_percent / 100)
        risk_per_share = abs(entry - stop)
        
        if risk_per_share <= 0:
            return {"error": "Invalid stop loss - must be different from entry"}
        
        shares = int(risk_amount / risk_per_share)
        position_value = shares * entry
        
        return {
            "risk_amount": round(risk_amount, 2),
            "risk_per_share": round(risk_per_share, 2),
            "shares": shares,
            "position_value": round(position_value, 2),
            "percent_of_account": round((position_value / account_size) * 100, 2)
        }
    
    def calculate_risk_reward(self, entry: float, stop: float, target: float) -> Dict:
        """Calculate risk-reward ratio"""
        risk = abs(entry - stop)
        reward = abs(target - entry)
        
        if risk <= 0:
            return {"error": "Invalid risk calculation"}
        
        ratio = reward / risk
        
        return {
            "risk": round(risk, 2),
            "reward": round(reward, 2),
            "ratio": f"{ratio:.1f}:1",
            "ratio_numeric": round(ratio, 2),
            "recommendation": "GOOD" if ratio >= 2 else "MARGINAL" if ratio >= 1.5 else "POOR"
        }
    
    def get_comprehensive_context_for_ai(self) -> str:
        """Get formatted knowledge context for AI"""
        context = """
=== INVESTOPEDIA TECHNICAL ANALYSIS KNOWLEDGE ===

## KEY TECHNICAL INDICATORS

### RSI (Relative Strength Index)
- Momentum oscillator (0-100)
- Overbought: >70, Oversold: <30
- Best signals: Divergences, failure swings
- Adjust levels based on trend

### MACD
- Trend-following momentum indicator
- Signal: MACD line crossing Signal line
- Bullish: Above zero, Bearish: Below zero
- Watch histogram for momentum shifts

### Bollinger Bands
- Volatility indicator (20 SMA ± 2 std dev)
- Squeeze = Low volatility, breakout coming
- Price at bands = Overbought/Oversold
- Band walk = Strong trend

### Fibonacci Retracements
- Key levels: 38.2%, 50%, 61.8%, 78.6%
- 38.2% = Strong trend (shallow pullback)
- 61.8% = Golden ratio (most important)
- Look for confluence with other levels

### Moving Averages
- 9 EMA: Scalping
- 20 EMA: Swing trading
- 50/200 SMA: Major trend
- Golden Cross (bullish): 50 > 200
- Death Cross (bearish): 50 < 200

## CANDLESTICK PATTERNS

### Bullish Reversal Patterns
- Hammer: Long lower wick at bottom
- Bullish Engulfing: Green engulfs prior red
- Morning Star: 3-candle reversal
- Three White Soldiers: 3 strong green candles

### Bearish Reversal Patterns
- Shooting Star: Long upper wick at top
- Bearish Engulfing: Red engulfs prior green
- Evening Star: 3-candle reversal
- Three Black Crows: 3 strong red candles

### Indecision Patterns
- Doji: Open = Close, warns of change
- Spinning Top: Small body, long wicks

## RISK MANAGEMENT RULES

### The 1% Rule
- Never risk more than 1% per trade
- Position Size = Risk Amount / Risk Per Share

### Risk-Reward
- Minimum 2:1 ratio
- 2:1 only needs 35% win rate to profit

### Stop Loss Placement
- Below swing low / above swing high
- Use ATR (1.5-3x) for volatility-based stops
- Move to breakeven after 1R profit

### Daily Loss Limit
- Max 2-3% daily loss
- Stop trading if limit hit
"""
        return context
    
    def get_fundamental_metric(self, metric_name: str) -> Optional[Dict]:
        """Get knowledge about a fundamental analysis metric"""
        metric = FUNDAMENTAL_METRICS.get(metric_name.lower().replace(" ", "_").replace("-", "_").replace("/", "_"))
        if metric:
            return {
                "name": metric.name,
                "category": metric.category,
                "description": metric.description,
                "formula": metric.formula,
                "interpretation": metric.interpretation,
                "good_values": metric.good_values,
                "limitations": metric.limitations,
                "trading_tips": metric.trading_tips
            }
        return None
    
    def get_all_fundamental_metrics(self) -> List[str]:
        """Get list of all fundamental analysis metrics"""
        return list(FUNDAMENTAL_METRICS.keys())
    
    def get_valuation_metrics(self) -> List[Dict]:
        """Get all valuation-related fundamental metrics"""
        return [
            self.get_fundamental_metric(name)
            for name, metric in FUNDAMENTAL_METRICS.items()
            if metric.category == "valuation"
        ]
    
    def get_profitability_metrics(self) -> List[Dict]:
        """Get all profitability-related fundamental metrics"""
        return [
            self.get_fundamental_metric(name)
            for name, metric in FUNDAMENTAL_METRICS.items()
            if metric.category == "profitability"
        ]
    
    def get_financial_health_metrics(self) -> List[Dict]:
        """Get all financial health metrics"""
        return [
            self.get_fundamental_metric(name)
            for name, metric in FUNDAMENTAL_METRICS.items()
            if metric.category in ["solvency", "liquidity"]
        ]
    
    def analyze_stock_fundamentals(self, pe: float = None, pb: float = None, 
                                   de: float = None, roe: float = None,
                                   peg: float = None, fcf_positive: bool = None) -> Dict:
        """Analyze a stock based on provided fundamental metrics"""
        analysis = {
            "signals": [],
            "warnings": [],
            "overall_assessment": "",
            "value_score": 0  # 0-100
        }
        
        score = 50  # Start neutral
        
        if pe is not None:
            if pe < 0:
                analysis["warnings"].append("Negative P/E indicates company is losing money")
                score -= 15
            elif pe < 15:
                analysis["signals"].append(f"P/E of {pe:.1f} suggests undervaluation")
                score += 10
            elif pe > 25:
                analysis["warnings"].append(f"P/E of {pe:.1f} may indicate overvaluation")
                score -= 5
        
        if pb is not None:
            if pb < 1:
                analysis["signals"].append(f"P/B of {pb:.2f} below book value - potential value play")
                score += 10
            elif pb > 3:
                analysis["warnings"].append(f"P/B of {pb:.2f} is high - may be overvalued")
                score -= 5
        
        if de is not None:
            if de > 2:
                analysis["warnings"].append(f"D/E of {de:.2f} indicates high leverage")
                score -= 10
            elif de < 0.5:
                analysis["signals"].append(f"D/E of {de:.2f} shows conservative debt levels")
                score += 5
        
        if roe is not None:
            if roe > 0.15:
                analysis["signals"].append(f"ROE of {roe:.1%} indicates strong profitability")
                score += 10
            elif roe < 0.10:
                analysis["warnings"].append(f"ROE of {roe:.1%} below average")
                score -= 5
        
        if peg is not None:
            if peg < 1:
                analysis["signals"].append(f"PEG of {peg:.2f} suggests undervaluation relative to growth")
                score += 15
            elif peg > 2:
                analysis["warnings"].append(f"PEG of {peg:.2f} may indicate overvaluation")
                score -= 10
        
        if fcf_positive is not None:
            if fcf_positive:
                analysis["signals"].append("Positive free cash flow indicates financial strength")
                score += 10
            else:
                analysis["warnings"].append("Negative free cash flow is concerning")
                score -= 15
        
        # Normalize score
        analysis["value_score"] = max(0, min(100, score))
        
        # Overall assessment
        if analysis["value_score"] >= 70:
            analysis["overall_assessment"] = "FUNDAMENTALLY STRONG - Good value indicators"
        elif analysis["value_score"] >= 50:
            analysis["overall_assessment"] = "NEUTRAL FUNDAMENTALS - Mixed signals"
        else:
            analysis["overall_assessment"] = "FUNDAMENTAL CONCERNS - Proceed with caution"
        
        return analysis
    
    def get_fundamental_analysis_context_for_ai(self) -> str:
        """Get formatted fundamental analysis context for AI"""
        context = """
=== INVESTOPEDIA FUNDAMENTAL ANALYSIS KNOWLEDGE ===

## WHAT IS FUNDAMENTAL ANALYSIS?
Fundamental analysis evaluates a company's intrinsic value by examining financial statements, 
management quality, competitive advantages, and economic conditions. Unlike technical analysis 
which studies price patterns, fundamental analysis focuses on the underlying business health.

## KEY VALUATION METRICS

### Price-to-Earnings (P/E) Ratio
- Formula: Stock Price / Earnings Per Share
- Interpretation: Lower = potentially undervalued
- Good range: 15-20 for most industries
- Below 10: Possible value trap or undervaluation
- Above 25: Growth stock or overvaluation

### Price-to-Book (P/B) Ratio
- Formula: Stock Price / Book Value Per Share
- Interpretation: Below 1 = trading below asset value
- Good range: 1-3 for most industries
- P/B < 1 may indicate distressed company OR undervaluation

### PEG Ratio (Price/Earnings to Growth)
- Formula: P/E Ratio / Annual EPS Growth Rate
- Interpretation: Adjusts P/E for growth
- PEG < 1: Undervalued relative to growth
- PEG = 1: Fairly valued per Peter Lynch
- PEG > 1: May be overvalued

### Price-to-Sales (P/S) Ratio
- Formula: Market Cap / Total Revenue
- Useful for unprofitable companies
- Lower is generally better
- Industry comparison is crucial

## PROFITABILITY METRICS

### Return on Equity (ROE)
- Formula: Net Income / Shareholders' Equity
- Measures profit generated per dollar of equity
- Good ROE: 15-20%+
- Above 20%: Excellent
- Below 10%: Below average

### Earnings Per Share (EPS)
- Formula: (Net Income - Preferred Dividends) / Shares Outstanding
- Higher is better
- Compare year-over-year growth
- Watch for share buybacks inflating EPS

### Net Profit Margin
- Formula: Net Income / Revenue
- Shows how much profit per dollar of sales
- Higher = more efficient
- Varies by industry (tech higher, retail lower)

## SOLVENCY & LEVERAGE METRICS

### Debt-to-Equity (D/E) Ratio
- Formula: Total Liabilities / Shareholders' Equity
- Below 1: Conservative
- Above 2: Highly leveraged (risky in downturns)
- Compare within same industry

### Interest Coverage Ratio
- Formula: EBIT / Interest Expense
- Above 3: Comfortable
- Below 1.5: May struggle to pay interest

## CASH FLOW METRICS

### Free Cash Flow (FCF)
- Formula: Operating Cash Flow - Capital Expenditures
- Represents true cash available
- Positive FCF: Company generates more than it spends
- Negative FCF: May need financing or be investing heavily
- FCF trend more important than single reading

### Operating Cash Flow
- Cash generated from core business operations
- Should generally track with net income
- Large discrepancy = potential accounting red flags

## QUALITY INDICATORS

### Competitive Moat
- Brand recognition, patents, network effects
- Sustainable competitive advantages
- Pricing power indicators

### Management Quality
- Track record, insider ownership
- Capital allocation decisions
- Communication transparency

## FUNDAMENTAL ANALYSIS RED FLAGS
1. Declining revenue for multiple quarters
2. Negative free cash flow with rising debt
3. ROE declining while debt increasing
4. Frequent accounting restatements
5. High insider selling
6. Audit qualifications or auditor changes
7. Customer concentration risk
8. Inventory growing faster than sales

## COMBINING TECHNICAL AND FUNDAMENTAL ANALYSIS
- Use fundamentals to identify WHAT to buy
- Use technicals to determine WHEN to buy
- Strong fundamentals + bullish chart = Higher conviction
- Weak fundamentals + bullish chart = Potential trap
- Strong fundamentals + bearish chart = Possible value opportunity
"""
        return context


# ==================== FUNDAMENTAL ANALYSIS DATA ====================

@dataclass
class FundamentalMetric:
    name: str
    category: str  # "valuation", "profitability", "solvency", "liquidity", "growth"
    description: str
    formula: str
    interpretation: str
    good_values: str
    limitations: List[str]
    trading_tips: List[str]


FUNDAMENTAL_METRICS: Dict[str, FundamentalMetric] = {
    
    "pe_ratio": FundamentalMetric(
        name="Price-to-Earnings (P/E) Ratio",
        category="valuation",
        description="Compares a company's stock price to its earnings per share, indicating how much investors pay per dollar of earnings.",
        formula="P/E = Stock Price / Earnings Per Share (EPS)",
        interpretation="""
- Low P/E (<15): May be undervalued or facing challenges
- Average P/E (15-20): Fairly valued for mature companies
- High P/E (>25): Growth expectations or overvaluation
- Negative P/E: Company is losing money
- Compare to industry average and historical range
""",
        good_values="15-20 for mature companies, higher acceptable for growth stocks. Compare within industry.",
        limitations=[
            "Doesn't account for growth rate",
            "Can be manipulated by accounting practices",
            "Meaningless for companies with no/negative earnings",
            "Varies significantly by industry",
            "Backward-looking (uses past earnings)"
        ],
        trading_tips=[
            "Always compare P/E within same industry",
            "Use forward P/E for growth companies",
            "Low P/E alone doesn't mean good value - could be value trap",
            "Combine with PEG ratio for growth-adjusted view",
            "Check earnings quality, not just quantity"
        ]
    ),
    
    "pb_ratio": FundamentalMetric(
        name="Price-to-Book (P/B) Ratio",
        category="valuation",
        description="Compares stock price to book value per share, showing what investors pay for company's net assets.",
        formula="P/B = Stock Price / (Total Assets - Total Liabilities) / Shares Outstanding",
        interpretation="""
- P/B < 1: Trading below book value (liquidation value)
- P/B 1-3: Normal range for most industries
- P/B > 3: Premium valuation, often for asset-light companies
- Very low P/B could indicate distress OR undervaluation
""",
        good_values="1-3 for most industries. Below 1 merits investigation. Banks/financials: 1-1.5 typical.",
        limitations=[
            "Book value doesn't reflect intangible assets well",
            "Less useful for tech/service companies",
            "Historical cost vs market value of assets",
            "Can be distorted by buybacks and write-offs",
            "Industry-dependent"
        ],
        trading_tips=[
            "Best for asset-heavy industries (banks, real estate)",
            "P/B < 1 requires deeper investigation",
            "Compare to company's historical P/B range",
            "Use alongside ROE for complete picture",
            "Tangible book value more conservative measure"
        ]
    ),
    
    "peg_ratio": FundamentalMetric(
        name="PEG Ratio (Price/Earnings-to-Growth)",
        category="valuation",
        description="Adjusts P/E ratio for expected earnings growth rate, providing growth-adjusted valuation.",
        formula="PEG = P/E Ratio / Annual EPS Growth Rate (%)",
        interpretation="""
- PEG < 1: Undervalued relative to growth (per Peter Lynch)
- PEG = 1: Fairly valued for its growth rate
- PEG > 1: May be overvalued for its growth
- Lower PEG generally more attractive
""",
        good_values="Below 1.0 considered undervalued. Peter Lynch: P/E should equal growth rate (PEG = 1).",
        limitations=[
            "Relies on earnings estimates which may be wrong",
            "Doesn't work for negative earnings or negative growth",
            "Growth rate assumptions vary by source",
            "Doesn't account for risk differences",
            "Less reliable for cyclical companies"
        ],
        trading_tips=[
            "Use 5-year expected growth rate for stability",
            "Compare PEG across similar growth companies",
            "Low PEG + strong fundamentals = attractive",
            "Be skeptical of very high growth projections",
            "Works best for growth stocks, not value stocks"
        ]
    ),
    
    "eps": FundamentalMetric(
        name="Earnings Per Share (EPS)",
        category="profitability",
        description="Profit allocated to each outstanding share of common stock, key indicator of company profitability.",
        formula="EPS = (Net Income - Preferred Dividends) / Weighted Average Shares Outstanding",
        interpretation="""
- Higher EPS = More profitable per share
- Growing EPS = Business improving
- Declining EPS = Potential problems
- Compare year-over-year and quarter-over-quarter
- Diluted EPS more conservative (includes stock options, convertibles)
""",
        good_values="Context-dependent. Focus on EPS growth rate (10-15%+ annually is strong).",
        limitations=[
            "Share buybacks can artificially inflate EPS",
            "One-time items can distort",
            "Doesn't reflect cash flow",
            "Size-dependent (larger companies have larger EPS)",
            "Accounting methods affect comparability"
        ],
        trading_tips=[
            "Track EPS growth over 3-5 years",
            "Use diluted EPS for conservative view",
            "Compare actual EPS to analyst estimates",
            "Watch for quality of earnings, not just quantity",
            "Earnings surprises drive stock movement"
        ]
    ),
    
    "roe": FundamentalMetric(
        name="Return on Equity (ROE)",
        category="profitability",
        description="Measures how efficiently a company generates profits from shareholders' equity investment.",
        formula="ROE = Net Income / Average Shareholders' Equity",
        interpretation="""
- ROE > 15%: Good profitability
- ROE > 20%: Excellent profitability
- ROE < 10%: Below average
- Negative ROE: Losing money
- Very high ROE (>30%) may indicate high leverage
""",
        good_values="15-20%+ is strong. Above 20% excellent. Compare within industry.",
        limitations=[
            "High debt inflates ROE (risky)",
            "Doesn't show how equity was financed",
            "Share buybacks reduce equity, boosting ROE",
            "Industry variation is significant",
            "One-time gains can spike ROE temporarily"
        ],
        trading_tips=[
            "Use DuPont analysis to decompose ROE",
            "Compare ROE to cost of equity",
            "Consistent ROE more valuable than volatile high ROE",
            "Check if high ROE comes from leverage",
            "ROE should exceed 10-year Treasury yield"
        ]
    ),
    
    "debt_to_equity": FundamentalMetric(
        name="Debt-to-Equity (D/E) Ratio",
        category="solvency",
        description="Compares total liabilities to shareholders' equity, measuring financial leverage and risk.",
        formula="D/E = Total Liabilities / Total Shareholders' Equity",
        interpretation="""
- D/E < 0.5: Conservative, low risk
- D/E 0.5-1: Moderate leverage
- D/E 1-2: Significant leverage
- D/E > 2: High leverage, risky in downturns
- Optimal varies by industry and interest rates
""",
        good_values="Below 1.0 for most industries. Utilities/REITs can sustain higher. Below 2.0 generally preferred.",
        limitations=[
            "Industry norms vary dramatically",
            "Doesn't distinguish debt types",
            "Off-balance sheet obligations not captured",
            "Capital-intensive industries need more debt",
            "Interest rate environment matters"
        ],
        trading_tips=[
            "Compare within same industry only",
            "Rising D/E during expansion may be fine",
            "Rising D/E during contraction is concerning",
            "Check interest coverage ratio alongside",
            "Consider total debt vs just long-term debt"
        ]
    ),
    
    "free_cash_flow": FundamentalMetric(
        name="Free Cash Flow (FCF)",
        category="liquidity",
        description="Cash remaining after capital expenditures, available for dividends, debt repayment, or reinvestment.",
        formula="FCF = Operating Cash Flow - Capital Expenditures",
        interpretation="""
- Positive FCF: Generates more cash than needed
- Negative FCF: Spending more than generating (may be investing)
- Growing FCF: Business health improving
- FCF trend more important than single reading
- FCF should eventually support/exceed dividends
""",
        good_values="Positive and growing. FCF yield (FCF/Market Cap) > 5% often attractive.",
        limitations=[
            "Lumpy due to CapEx timing",
            "Can be manipulated via CapEx timing",
            "Doesn't distinguish maintenance vs growth CapEx",
            "Working capital changes can distort",
            "Industry and lifecycle dependent"
        ],
        trading_tips=[
            "Look at 3-5 year FCF trend",
            "FCF should track or exceed net income long-term",
            "Negative FCF ok during heavy investment periods",
            "FCF funds dividends - check sustainability",
            "FCF per share useful for comparison"
        ]
    ),
    
    "current_ratio": FundamentalMetric(
        name="Current Ratio",
        category="liquidity",
        description="Measures ability to pay short-term obligations with current assets.",
        formula="Current Ratio = Current Assets / Current Liabilities",
        interpretation="""
- Above 2: Strong liquidity
- 1.5-2: Healthy liquidity
- 1-1.5: Adequate but watch closely
- Below 1: May struggle to meet obligations
- Too high (>3) may indicate inefficient capital use
""",
        good_values="1.5-2.0 for most industries. Above 1.0 minimum.",
        limitations=[
            "Inventory may not be quickly convertible",
            "Doesn't show timing of cash flows",
            "Industry norms vary",
            "Doesn't indicate quality of assets",
            "Seasonal businesses have fluctuating ratios"
        ],
        trading_tips=[
            "Compare to industry average",
            "Track trend over time",
            "Use quick ratio for more conservative view",
            "Consider nature of current assets",
            "Declining current ratio is warning sign"
        ]
    ),
    
    "interest_coverage": FundamentalMetric(
        name="Interest Coverage Ratio",
        category="solvency",
        description="Measures ability to pay interest on outstanding debt, indicating financial stability.",
        formula="Interest Coverage = EBIT / Interest Expense",
        interpretation="""
- Above 5: Very comfortable
- 3-5: Adequate
- 2-3: Some concern
- Below 2: Significant risk
- Below 1: Cannot cover interest payments
""",
        good_values="Above 3 preferred. Above 5 very comfortable.",
        limitations=[
            "EBIT can be volatile",
            "Doesn't account for principal repayment",
            "One-time items affect calculation",
            "Different debt structures complicate comparison",
            "Doesn't capture future interest rate risk"
        ],
        trading_tips=[
            "Essential metric for debt-heavy companies",
            "Declining trend is concerning",
            "Check during economic downturns",
            "Compare to peers with similar debt structures",
            "Use alongside D/E for complete leverage picture"
        ]
    ),
    
    "dividend_yield": FundamentalMetric(
        name="Dividend Yield",
        category="valuation",
        description="Annual dividend payment as percentage of stock price, showing income return to shareholders.",
        formula="Dividend Yield = Annual Dividends Per Share / Stock Price × 100",
        interpretation="""
- 2-4%: Typical for dividend stocks
- Above 5%: High yield (check sustainability)
- Very high (>8%): Often unsustainable or distressed
- 0%: Growth stocks reinvesting all profits
""",
        good_values="2-4% with growth for dividend investors. Sustainability more important than high yield.",
        limitations=[
            "High yield may signal price drop or dividend cut risk",
            "Doesn't show dividend growth",
            "Payout ratio needed for sustainability assessment",
            "Tax treatment varies",
            "Doesn't capture total return"
        ],
        trading_tips=[
            "Check payout ratio for sustainability",
            "Dividend growth rate matters",
            "Compare to Treasury yields",
            "Look for dividend aristocrats (25+ years of increases)",
            "Yield traps: very high yield often precedes cut"
        ]
    ),
    
    "price_to_sales": FundamentalMetric(
        name="Price-to-Sales (P/S) Ratio",
        category="valuation",
        description="Compares stock price to revenue per share, useful for unprofitable or cyclical companies.",
        formula="P/S = Market Cap / Total Revenue (or Stock Price / Revenue Per Share)",
        interpretation="""
- P/S < 1: May be undervalued
- P/S 1-2: Normal for many industries
- P/S > 3: Premium valuation
- Lower P/S generally more attractive
- Very low may indicate problems
""",
        good_values="Below 2 for most industries. Tech/growth can be higher. Compare within sector.",
        limitations=[
            "Ignores profitability entirely",
            "Revenue quality matters",
            "Doesn't account for expenses or margins",
            "Industry variation is extreme",
            "Subscription vs one-time revenue different"
        ],
        trading_tips=[
            "Most useful for unprofitable growth companies",
            "Compare to profit margins for context",
            "Use alongside P/E when available",
            "Lower P/S + improving margins = bullish",
            "Industry comparison essential"
        ]
    ),
}


# Singleton
_investopedia_service: Optional[InvestopediaKnowledgeService] = None

def get_investopedia_knowledge() -> InvestopediaKnowledgeService:
    """Get singleton Investopedia knowledge service"""
    global _investopedia_service
    if _investopedia_service is None:
        _investopedia_service = InvestopediaKnowledgeService()
    return _investopedia_service
