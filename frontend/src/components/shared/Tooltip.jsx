/**
 * Comprehensive Tooltip System for Trading App
 * Provides hover-over explanations for trading concepts, metrics, and UI elements
 */
import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle, Info, AlertCircle, TrendingUp, TrendingDown } from 'lucide-react';

// ==================== COMPREHENSIVE TOOLTIP DEFINITIONS ====================
// Organized by category for maintainability

export const tooltipDefinitions = {
  // ========== MARKET REGIME & CONDITIONS ==========
  'market-regime': { 
    term: 'Market Regime', 
    def: 'Current market condition based on multiple indicators. Determines position sizing and strategy selection.',
    category: 'Market'
  },
  'risk-on': { 
    term: 'RISK_ON', 
    def: 'Bullish market regime. Full position sizing recommended. Favor momentum and breakout strategies.',
    category: 'Market'
  },
  'risk-off': { 
    term: 'RISK_OFF', 
    def: 'Bearish signals detected. Reduce position sizes to 50%. Favor defensive sectors and mean reversion.',
    category: 'Market'
  },
  'caution': { 
    term: 'CAUTION', 
    def: 'Mixed signals in the market. Reduce position sizes to 75%. Use tighter stops.',
    category: 'Market'
  },
  'confirmed-down': { 
    term: 'CONFIRMED_DOWN', 
    def: 'Confirmed downtrend. Reduce longs to 25%, favor shorts. Wait for follow-through day before going long.',
    category: 'Market'
  },
  'regime-score': { 
    term: 'Regime Score', 
    def: 'Composite score (0-100) measuring market health. >60 bullish, <40 bearish, 40-60 neutral.',
    category: 'Market'
  },
  'risk-level': { 
    term: 'Risk Level', 
    def: 'Inverse of regime score. Higher = more caution needed. Used for position sizing adjustments.',
    category: 'Market'
  },
  'ftd': { 
    term: 'Follow-Through Day', 
    def: 'A strong rally day (1.5%+) on higher volume after a correction. Signals potential trend reversal.',
    category: 'Market'
  },
  'distribution-day': { 
    term: 'Distribution Day', 
    def: 'Down day on higher volume. 4+ distribution days in 25 trading days = market topping.',
    category: 'Market'
  },
  'breadth': { 
    term: 'Market Breadth', 
    def: 'Percentage of stocks participating in the move. Strong breadth confirms trend, weak breadth warns of reversal.',
    category: 'Market'
  },
  
  // ========== SCORES & GRADES ==========
  'overall-score': { 
    term: 'Overall Score', 
    def: 'Composite score (0-100) combining technical, fundamental, and catalyst factors. Higher = better opportunity.',
    category: 'Scores'
  },
  'technical-score': { 
    term: 'Technical Score', 
    def: 'Score based on price action, trend alignment, and technical indicators like RSI, MACD, and moving averages.',
    category: 'Scores'
  },
  'fundamental-score': { 
    term: 'Fundamental Score', 
    def: 'Score based on company financials, market cap, sector strength, and institutional activity.',
    category: 'Scores'
  },
  'catalyst-score': { 
    term: 'Catalyst Score', 
    def: 'Score measuring potential price-moving events like earnings, news, and options activity.',
    category: 'Scores'
  },
  'confidence-score': { 
    term: 'Confidence', 
    def: 'How reliable the analysis is based on data quality and indicator agreement. Higher = more trustworthy.',
    category: 'Scores'
  },
  'signal-strength': { 
    term: 'Signal Strength', 
    def: 'Percentage of trading rules that the stock matches. Higher = more confirmations.',
    category: 'Scores'
  },
  'quality-score': { 
    term: 'Quality Score', 
    def: 'Trade setup quality (0-100). Based on pattern clarity, volume confirmation, and risk/reward.',
    category: 'Scores'
  },
  'tqs': { 
    term: 'TQS', 
    def: 'Trade Quality Score. Combines setup, technical, fundamental, context, and execution pillars.',
    category: 'Scores'
  },
  'grade': { 
    term: 'Grade', 
    def: 'Letter grade based on score. A+=90+, A=80-89, B+=70-79, B=60-69, C=50-59, F=0-49.',
    category: 'Scores'
  },
  'win-rate': { 
    term: 'Win Rate', 
    def: 'Percentage of winning trades. Calculated as (Wins / Total Trades) x 100.',
    category: 'Scores'
  },
  'expectancy': { 
    term: 'Expectancy', 
    def: 'Expected profit per trade. Formula: (Win% x Avg Win) - (Loss% x Avg Loss). Positive = profitable system.',
    category: 'Scores'
  },
  'profit-factor': { 
    term: 'Profit Factor', 
    def: 'Gross Profit / Gross Loss. >1 profitable, >2 excellent. Shows overall system health.',
    category: 'Scores'
  },
  
  // ========== TECHNICAL INDICATORS ==========
  'rsi': { 
    term: 'RSI', 
    def: 'Relative Strength Index (0-100). >70 overbought (sell signal), <30 oversold (buy signal), 40-60 neutral.',
    category: 'Technical'
  },
  'macd': { 
    term: 'MACD', 
    def: 'Moving Average Convergence Divergence. Bullish when MACD crosses above signal line, bearish when below.',
    category: 'Technical'
  },
  'vwap': { 
    term: 'VWAP', 
    def: 'Volume Weighted Average Price. Price above = bullish, below = bearish. Institutional reference level.',
    category: 'Technical'
  },
  'vwap-dist': { 
    term: 'VWAP Distance', 
    def: 'How far price is from VWAP. Extended >2% often reverts to mean. Key for mean reversion trades.',
    category: 'Technical'
  },
  'ema': { 
    term: 'EMA', 
    def: 'Exponential Moving Average. Weights recent prices more. Key levels: 9 (fast), 20 (medium), 50 (slow).',
    category: 'Technical'
  },
  'ema-9': { 
    term: 'EMA 9', 
    def: 'Fast 9-period EMA. Price above = bullish momentum. Used for scalping and intraday entries.',
    category: 'Technical'
  },
  'ema-20': { 
    term: 'EMA 20', 
    def: 'Medium-term trend indicator. Often acts as dynamic support/resistance for pullbacks.',
    category: 'Technical'
  },
  'sma-50': { 
    term: 'SMA 50', 
    def: '50-day Simple Moving Average. Key institutional level. Price above = bull market, below = bear market.',
    category: 'Technical'
  },
  'sma-200': { 
    term: 'SMA 200', 
    def: '200-day Moving Average. Major trend indicator. Golden cross (50>200) bullish, death cross bearish.',
    category: 'Technical'
  },
  'atr': { 
    term: 'ATR', 
    def: 'Average True Range. Measures volatility in dollars. Used for stop loss placement (1.5-2x ATR).',
    category: 'Technical'
  },
  'atr-percent': { 
    term: 'ATR %', 
    def: 'ATR as percentage of price. <2% low volatility, 2-4% normal, >4% high volatility.',
    category: 'Technical'
  },
  'bb': { 
    term: 'Bollinger Bands', 
    def: 'Volatility bands around price. Price at upper band = overbought, lower band = oversold.',
    category: 'Technical'
  },
  'squeeze': { 
    term: 'Squeeze', 
    def: 'Bollinger Bands inside Keltner Channels. Low volatility precedes big moves. Wait for expansion.',
    category: 'Technical'
  },
  
  // ========== VOLUME METRICS ==========
  'rvol': { 
    term: 'RVOL', 
    def: 'Relative Volume. Today\'s volume vs average. 1.5x+ confirms moves, 2x+ = significant institutional activity.',
    category: 'Volume'
  },
  'volume': { 
    term: 'Volume', 
    def: 'Number of shares traded. Higher volume = more conviction in the price move.',
    category: 'Volume'
  },
  'avg-volume': { 
    term: 'Avg Volume', 
    def: 'Average daily trading volume over past 20-50 days. Used to calculate RVOL.',
    category: 'Volume'
  },
  'adv': { 
    term: 'ADV', 
    def: 'Average Daily Volume. Minimum 500K recommended for intraday, 100K for swing trades.',
    category: 'Volume'
  },
  'vold': { 
    term: 'VOLD', 
    def: 'Up Volume minus Down Volume. Positive = buyers in control, negative = sellers in control.',
    category: 'Volume'
  },
  'volume-profile': { 
    term: 'Volume Profile', 
    def: 'Shows price levels with most trading activity. High volume nodes act as support/resistance.',
    category: 'Volume'
  },
  
  // ========== PRICE LEVELS ==========
  'support': { 
    term: 'Support', 
    def: 'Price level where buying pressure emerges. Price tends to bounce here. Break = bearish.',
    category: 'Levels'
  },
  'resistance': { 
    term: 'Resistance', 
    def: 'Price level where selling pressure emerges. Price tends to stall here. Break = bullish.',
    category: 'Levels'
  },
  'pivot': { 
    term: 'Pivot', 
    def: 'Key price level from prior session. (High + Low + Close) / 3. Acts as support/resistance.',
    category: 'Levels'
  },
  'r1': { 
    term: 'R1', 
    def: 'First resistance level above pivot. Target for longs. Often where first selling appears.',
    category: 'Levels'
  },
  'r2': { 
    term: 'R2', 
    def: 'Second resistance level. Stronger resistance. Breakout here = strong bullish signal.',
    category: 'Levels'
  },
  's1': { 
    term: 'S1', 
    def: 'First support level below pivot. Initial bounce zone. Break below = weakness.',
    category: 'Levels'
  },
  's2': { 
    term: 'S2', 
    def: 'Second support level. Stronger support. Break = significant bearish signal.',
    category: 'Levels'
  },
  'hod': { 
    term: 'HOD', 
    def: 'High of Day. Breakout above often signals continuation. Key level for momentum trades.',
    category: 'Levels'
  },
  'lod': { 
    term: 'LOD', 
    def: 'Low of Day. Break below signals weakness. Key level for short entries.',
    category: 'Levels'
  },
  'poc': { 
    term: 'POC', 
    def: 'Point of Control. Price level with highest volume. Strong magnet for price.',
    category: 'Levels'
  },
  
  // ========== RISK MANAGEMENT ==========
  'stop-loss': { 
    term: 'Stop Loss', 
    def: 'Pre-defined exit price to limit losses. Should invalidate your trade thesis when hit.',
    category: 'Risk'
  },
  'target': { 
    term: 'Target', 
    def: 'Price target for taking profits. Set based on risk/reward ratio (usually 2-3x risk).',
    category: 'Risk'
  },
  'risk-reward': { 
    term: 'R:R', 
    def: 'Risk/Reward ratio. 2:1 means risking $1 to potentially make $2. Minimum 2:1 recommended.',
    category: 'Risk'
  },
  'r-multiple': { 
    term: 'R-Multiple', 
    def: 'Profit/Loss expressed in terms of initial risk (R). +2R = made 2x your risk. -1R = lost 1 risk unit.',
    category: 'Risk'
  },
  'position-size': { 
    term: 'Position Size', 
    def: 'Number of shares to trade based on risk parameters. Never risk more than 1-2% of account per trade.',
    category: 'Risk'
  },
  'max-risk': { 
    term: 'Max Risk', 
    def: 'Maximum dollar amount to risk per trade. Typically $500-2500 based on account size.',
    category: 'Risk'
  },
  'daily-loss-limit': { 
    term: 'Daily Loss Limit', 
    def: 'Maximum loss allowed per day before stopping. Usually 1-3% of account. Prevents tilt trading.',
    category: 'Risk'
  },
  'trailing-stop': { 
    term: 'Trailing Stop', 
    def: 'Stop loss that follows price as it moves in your favor. Locks in profits while allowing run.',
    category: 'Risk'
  },
  'breakeven': { 
    term: 'Breakeven', 
    def: 'Move stop loss to entry price after first target hit. Ensures no loss on the trade.',
    category: 'Risk'
  },
  'scale-out': { 
    term: 'Scale Out', 
    def: 'Selling position in parts at different targets. Example: 1/3 at T1, 1/3 at T2, 1/3 trailing.',
    category: 'Risk'
  },
  'heat': { 
    term: 'Heat', 
    def: 'Total risk exposure across all open positions. Should not exceed 6% of account.',
    category: 'Risk'
  },
  
  // ========== TRADE TYPES & TIMEFRAMES ==========
  'entry': { 
    term: 'Entry', 
    def: 'Recommended price to enter the trade. Usually at key level breakout or pullback.',
    category: 'Trade'
  },
  'exit': { 
    term: 'Exit', 
    def: 'Closing the trade. Can be at target (profit), stop (loss), or manually (discretionary).',
    category: 'Trade'
  },
  'long': { 
    term: 'Long', 
    def: 'Buying shares expecting price to rise. Profit = (Exit Price - Entry Price) x Shares.',
    category: 'Trade'
  },
  'short': { 
    term: 'Short', 
    def: 'Selling borrowed shares expecting price to fall. Profit = (Entry Price - Exit Price) x Shares.',
    category: 'Trade'
  },
  'scalp': { 
    term: 'Scalp', 
    def: 'Quick trade lasting minutes to 1 hour. Small profit targets (0.5-1%), tight stops.',
    category: 'Trade'
  },
  'intraday': { 
    term: 'Intraday', 
    def: 'Trade opened and closed same day. No overnight risk. Typically 1-4 hour duration.',
    category: 'Trade'
  },
  'swing': { 
    term: 'Swing', 
    def: 'Trade held 2-10 days. Captures larger moves. Requires overnight risk management.',
    category: 'Trade'
  },
  'position': { 
    term: 'Position Trade', 
    def: 'Trade held weeks to months. Based on longer-term trends. Lower position size, wider stops.',
    category: 'Trade'
  },
  'paper-trade': { 
    term: 'Paper Trade', 
    def: 'Simulated trading without real money. Used to test strategies and build confidence.',
    category: 'Trade'
  },
  
  // ========== TRADING STRATEGIES ==========
  'orb': { 
    term: 'ORB', 
    def: 'Opening Range Breakout. Trade the breakout of first 5-30 min range. High win rate morning strategy.',
    category: 'Strategy'
  },
  'vwap-bounce': { 
    term: 'VWAP Bounce', 
    def: 'Enter long when price pulls back to VWAP and bounces. Works best in uptrending stocks.',
    category: 'Strategy'
  },
  'vwap-fade': { 
    term: 'VWAP Fade', 
    def: 'Short overextended stocks back to VWAP. Works when price is >2% above VWAP.',
    category: 'Strategy'
  },
  'rubber-band': { 
    term: 'Rubber Band', 
    def: 'Mean reversion strategy. Buy oversold stocks at support, short overbought at resistance.',
    category: 'Strategy'
  },
  'breakout': { 
    term: 'Breakout', 
    def: 'Enter when price breaks above resistance with volume. Momentum strategy for trending markets.',
    category: 'Strategy'
  },
  'pullback': { 
    term: 'Pullback', 
    def: 'Buy dips in uptrending stocks. Entry at support levels (EMAs, VWAP, prior highs).',
    category: 'Strategy'
  },
  'gap-and-go': { 
    term: 'Gap & Go', 
    def: 'Trade stocks gapping up/down at open. Look for continuation with volume confirmation.',
    category: 'Strategy'
  },
  'mean-reversion': { 
    term: 'Mean Reversion', 
    def: 'Strategy betting price returns to average. Buy oversold, sell overbought. Works in ranges.',
    category: 'Strategy'
  },
  'momentum': { 
    term: 'Momentum', 
    def: 'Strategy following strong price moves. Trend is your friend. Let winners run.',
    category: 'Strategy'
  },
  
  // ========== EARNINGS & EVENTS ==========
  'iv': { 
    term: 'IV', 
    def: 'Implied Volatility. Market\'s expected move priced into options. High before events, crushes after.',
    category: 'Options'
  },
  'iv-rank': { 
    term: 'IV Rank', 
    def: 'Current IV as percentile of 52-week range. 100 = IV at yearly high. High rank = sell premium.',
    category: 'Options'
  },
  'expected-move': { 
    term: 'Expected Move', 
    def: 'Price range market expects based on options. Stock often stays within this range 68% of time.',
    category: 'Options'
  },
  'earnings': { 
    term: 'Earnings', 
    def: 'Quarterly financial results. Major catalyst. Usually causes big moves. High IV pre-earnings.',
    category: 'Events'
  },
  'eps': { 
    term: 'EPS', 
    def: 'Earnings Per Share. Beat vs miss determines post-earnings move direction (usually).',
    category: 'Events'
  },
  'guidance': { 
    term: 'Guidance', 
    def: 'Company\'s future outlook. Often more important than earnings beat/miss for stock reaction.',
    category: 'Events'
  },
  
  // ========== SHORT INTEREST ==========
  'short-interest': { 
    term: 'Short Interest', 
    def: 'Shares sold short as % of float. >20% elevated, >30% potential squeeze.',
    category: 'Short'
  },
  'days-to-cover': { 
    term: 'Days to Cover', 
    def: 'Days needed for shorts to cover at average volume. >5 days = squeeze potential.',
    category: 'Short'
  },
  'squeeze-score': { 
    term: 'Squeeze Score', 
    def: 'Likelihood of short squeeze (0-100). Based on short interest, days to cover, and recent volume.',
    category: 'Short'
  },
  'short-squeeze': { 
    term: 'Short Squeeze', 
    def: 'Rapid price rise forcing shorts to cover, which drives price even higher. High risk/reward.',
    category: 'Short'
  },
  'borrow-rate': { 
    term: 'Borrow Rate', 
    def: 'Cost to borrow shares for shorting. High rate = hard to borrow, potential squeeze.',
    category: 'Short'
  },
  
  // ========== MARKET DATA ==========
  'bid': { 
    term: 'Bid', 
    def: 'Highest price buyers are willing to pay. Where you sell (market order).',
    category: 'Market Data'
  },
  'ask': { 
    term: 'Ask', 
    def: 'Lowest price sellers are willing to accept. Where you buy (market order).',
    category: 'Market Data'
  },
  'spread': { 
    term: 'Spread', 
    def: 'Difference between bid and ask. Tighter = more liquid. Wide spread = be careful.',
    category: 'Market Data'
  },
  'last': { 
    term: 'Last', 
    def: 'Last traded price. May differ from bid/ask.',
    category: 'Market Data'
  },
  'change': { 
    term: 'Change', 
    def: 'Price change from previous close. Shown in dollars and percentage.',
    category: 'Market Data'
  },
  'market-cap': { 
    term: 'Market Cap', 
    def: 'Company size = Share Price x Shares Outstanding. Large >$10B, Mid $2-10B, Small <$2B.',
    category: 'Market Data'
  },
  'float': { 
    term: 'Float', 
    def: 'Shares available for public trading. Low float (<20M) = more volatile.',
    category: 'Market Data'
  },
  'shares-outstanding': { 
    term: 'Shares Outstanding', 
    def: 'Total shares issued by company. Used to calculate market cap.',
    category: 'Market Data'
  },
  
  // ========== BOT & AUTOMATION ==========
  'autonomous-mode': { 
    term: 'Autonomous Mode', 
    def: 'Bot executes trades automatically without confirmation. For experienced users only.',
    category: 'Bot'
  },
  'confirmation-mode': { 
    term: 'Confirmation Mode', 
    def: 'Bot proposes trades but waits for your approval before executing. Safer for learning.',
    category: 'Bot'
  },
  'paused-mode': { 
    term: 'Paused Mode', 
    def: 'Bot stops scanning and does not propose or execute any trades.',
    category: 'Bot'
  },
  'position-multiplier': { 
    term: 'Position Multiplier', 
    def: 'Regime-based adjustment to position size. 1.0 = full size, 0.5 = half size.',
    category: 'Bot'
  },
  'auto-execute': { 
    term: 'Auto Execute', 
    def: 'Automatically execute trades that meet all criteria. Requires autonomous mode.',
    category: 'Bot'
  },
  'pending-trade': { 
    term: 'Pending Trade', 
    def: 'Trade proposed by bot awaiting your confirmation. Review and approve/reject.',
    category: 'Bot'
  },
  'open-trade': { 
    term: 'Open Trade', 
    def: 'Active position currently being managed by the bot.',
    category: 'Bot'
  },
  
  // ========== BACKTESTING ==========
  'backtest': { 
    term: 'Backtest', 
    def: 'Testing a strategy on historical data to see how it would have performed.',
    category: 'Backtest'
  },
  'walk-forward': { 
    term: 'Walk-Forward', 
    def: 'Advanced backtest method. Optimize on one period, test on next. Validates robustness.',
    category: 'Backtest'
  },
  'monte-carlo': { 
    term: 'Monte Carlo', 
    def: 'Simulation running thousands of scenarios to estimate risk and drawdown distribution.',
    category: 'Backtest'
  },
  'drawdown': { 
    term: 'Drawdown', 
    def: 'Peak-to-trough decline in account value. Max drawdown is worst historical decline.',
    category: 'Backtest'
  },
  'sharpe-ratio': { 
    term: 'Sharpe Ratio', 
    def: 'Risk-adjusted return. >1 good, >2 excellent. Higher = better return per unit of risk.',
    category: 'Backtest'
  },
  'sortino-ratio': { 
    term: 'Sortino Ratio', 
    def: 'Like Sharpe but only penalizes downside volatility. Better measure of risk-adjusted return.',
    category: 'Backtest'
  },
  'max-drawdown': { 
    term: 'Max Drawdown', 
    def: 'Largest peak-to-trough decline. Shows worst-case scenario. Important for sizing.',
    category: 'Backtest'
  },
  'total-trades': { 
    term: 'Total Trades', 
    def: 'Number of trades in backtest period. Need 30+ trades for statistical significance.',
    category: 'Backtest'
  },
  'cagr': { 
    term: 'CAGR', 
    def: 'Compound Annual Growth Rate. Average yearly return accounting for compounding.',
    category: 'Backtest'
  },
  
  // ========== LEARNING SYSTEM ==========
  'edge-decay': { 
    term: 'Edge Decay', 
    def: 'Strategy losing effectiveness over time. Common in markets as patterns get arbitraged.',
    category: 'Learning'
  },
  'calibration': { 
    term: 'Calibration', 
    def: 'Adjusting thresholds based on actual performance. Keeps system aligned with reality.',
    category: 'Learning'
  },
  'context-performance': { 
    term: 'Context Performance', 
    def: 'How strategy performs in specific conditions (regime, time, volatility).',
    category: 'Learning'
  },
  'playbook': { 
    term: 'Playbook', 
    def: 'Documented strategy rules and execution guidelines. Reference for consistent trading.',
    category: 'Learning'
  },
  'shadow-mode': { 
    term: 'Shadow Mode', 
    def: 'Paper trading a strategy alongside live account. Validates performance before going live.',
    category: 'Learning'
  },
  
  // ========== ORDERS ==========
  'market-order': { 
    term: 'Market Order', 
    def: 'Execute immediately at best available price. Fast but no price control. Use for urgent exits.',
    category: 'Orders'
  },
  'limit-order': { 
    term: 'Limit Order', 
    def: 'Execute only at specified price or better. Price control but may not fill.',
    category: 'Orders'
  },
  'stop-order': { 
    term: 'Stop Order', 
    def: 'Becomes market order when stop price is hit. Used for stop losses.',
    category: 'Orders'
  },
  'stop-limit': { 
    term: 'Stop Limit', 
    def: 'Becomes limit order when stop price is hit. More control but may not fill in fast moves.',
    category: 'Orders'
  },
  'bracket-order': { 
    term: 'Bracket Order', 
    def: 'Entry + stop loss + profit target as one order. OCO (one cancels other) for exits.',
    category: 'Orders'
  },
  
  // ========== UI ELEMENTS ==========
  'live-alerts': { 
    term: 'Live Alerts', 
    def: 'Real-time trade signals from the scanner. Shows opportunities matching your strategies.',
    category: 'UI'
  },
  'watchlist': { 
    term: 'Watchlist', 
    def: 'Your curated list of stocks to monitor. Scanner prioritizes these symbols.',
    category: 'UI'
  },
  'scanner': { 
    term: 'Scanner', 
    def: 'Automated system that finds stocks matching your strategy criteria.',
    category: 'UI'
  },
  'dashboard': { 
    term: 'Dashboard', 
    def: 'Overview of your trading activity, P&L, and key market data.',
    category: 'UI'
  },
  'command-panel': { 
    term: 'Command Panel', 
    def: 'AI-powered interface for natural language trading commands and questions.',
    category: 'UI'
  },
  'learning-hub': { 
    term: 'Learning Hub', 
    def: 'Analytics center showing your performance patterns and improvement areas.',
    category: 'UI'
  },
  
  // ========== FUNDAMENTALS ==========
  'pe-ratio': { 
    term: 'P/E Ratio', 
    def: 'Price to Earnings. How much investors pay per $1 of earnings. Lower may be undervalued.',
    category: 'Fundamentals'
  },
  'peg-ratio': { 
    term: 'PEG Ratio', 
    def: 'P/E divided by growth rate. <1 may be undervalued. Accounts for growth.',
    category: 'Fundamentals'
  },
  'roe': { 
    term: 'ROE', 
    def: 'Return on Equity. Profit generated per dollar of shareholder equity. >15% is good.',
    category: 'Fundamentals'
  },
  'debt-equity': { 
    term: 'D/E Ratio', 
    def: 'Debt to Equity. Measures financial leverage. <1 conservative, >2 aggressive.',
    category: 'Fundamentals'
  },
  'revenue-growth': { 
    term: 'Revenue Growth', 
    def: 'Year-over-year revenue increase. Shows business expansion. >20% is strong.',
    category: 'Fundamentals'
  },
  'profit-margin': { 
    term: 'Profit Margin', 
    def: 'Net income as % of revenue. Shows efficiency. >10% is healthy.',
    category: 'Fundamentals'
  },
  
  // ========== INDICES ==========
  'spy': { 
    term: 'SPY', 
    def: 'S&P 500 ETF. Tracks 500 large US companies. Market benchmark.',
    category: 'Indices'
  },
  'qqq': { 
    term: 'QQQ', 
    def: 'Nasdaq 100 ETF. Tech-heavy index. More volatile than SPY.',
    category: 'Indices'
  },
  'iwm': { 
    term: 'IWM', 
    def: 'Russell 2000 ETF. Small cap stocks. Risk appetite indicator.',
    category: 'Indices'
  },
  'vix': { 
    term: 'VIX', 
    def: 'Volatility Index. Fear gauge. <15 calm, 15-20 normal, 20-30 elevated, >30 panic.',
    category: 'Indices'
  },
  'dia': { 
    term: 'DIA', 
    def: 'Dow Jones ETF. 30 blue-chip stocks. Traditional market indicator.',
    category: 'Indices'
  },
  
  // ========== TIME OF DAY ==========
  'pre-market': { 
    term: 'Pre-Market', 
    def: 'Trading session before 9:30 AM ET. Lower volume, wider spreads. Set up watchlist.',
    category: 'Time'
  },
  'open': { 
    term: 'Market Open', 
    def: '9:30 AM ET. First 30 min highest volatility. Wait for range to form.',
    category: 'Time'
  },
  'mid-day': { 
    term: 'Mid-Day', 
    def: '11:30 AM - 2:00 PM ET. Typically quieter, lower volume. Lunch lull.',
    category: 'Time'
  },
  'power-hour': { 
    term: 'Power Hour', 
    def: 'Last hour of trading (3-4 PM ET). Volume picks up. Institutional positioning.',
    category: 'Time'
  },
  'close': { 
    term: 'Market Close', 
    def: '4:00 PM ET. Regular session ends. Position for overnight or close intraday.',
    category: 'Time'
  },
  'after-hours': { 
    term: 'After Hours', 
    def: 'Trading after 4:00 PM ET. Low volume. Earnings reactions happen here.',
    category: 'Time'
  },
  
  // ========== CONNECTION STATUS ==========
  'ib-connected': { 
    term: 'IB Connected', 
    def: 'Interactive Brokers gateway is connected. Real-time data and execution available.',
    category: 'Status'
  },
  'ib-disconnected': { 
    term: 'IB Disconnected', 
    def: 'No connection to IB Gateway. Using fallback data sources. Cannot execute trades.',
    category: 'Status'
  },
  'alpaca-connected': { 
    term: 'IB Cache Active', 
    def: 'Using cached IB historical data from MongoDB when live IB Gateway is unavailable.',
    category: 'Status'
  },
  'data-delayed': { 
    term: 'Data Delayed', 
    def: 'Real-time data unavailable. Showing 15-20 min delayed quotes.',
    category: 'Status'
  },
  
  // ========== P&L ==========
  'pnl': { 
    term: 'P&L', 
    def: 'Profit and Loss. Your trading gains minus losses.',
    category: 'P&L'
  },
  'realized-pnl': { 
    term: 'Realized P&L', 
    def: 'Profit/loss from closed trades. Actually in your account.',
    category: 'P&L'
  },
  'unrealized-pnl': { 
    term: 'Unrealized P&L', 
    def: 'Profit/loss on open positions. Changes with price. Not locked in until you close.',
    category: 'P&L'
  },
  'daily-pnl': { 
    term: 'Daily P&L', 
    def: 'Today\'s profit or loss across all trades.',
    category: 'P&L'
  },
  'gross-pnl': { 
    term: 'Gross P&L', 
    def: 'Total P&L before fees and commissions.',
    category: 'P&L'
  },
  'net-pnl': { 
    term: 'Net P&L', 
    def: 'P&L after fees and commissions. What actually hits your account.',
    category: 'P&L'
  },
};

// ==================== TOOLTIP COMPONENTS ====================

/**
 * Simple inline tooltip - wraps text with hover explanation
 */
export const Tip = ({ 
  id, 
  children, 
  className = '',
  showIcon = false,
  underline = true
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const triggerRef = useRef(null);
  
  const definition = tooltipDefinitions[id];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const tooltipWidth = 280;
      let x = rect.left + rect.width / 2 - tooltipWidth / 2;
      let y = rect.top - 8;
      
      // Keep in viewport
      x = Math.max(10, Math.min(x, window.innerWidth - tooltipWidth - 10));
      
      setPosition({ x, y });
    }
  }, [isVisible]);
  
  if (!definition) {
    return <span className={className}>{children}</span>;
  }
  
  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center gap-1 cursor-help transition-colors ${
          underline ? 'border-b border-dotted border-zinc-600 hover:border-cyan-400' : ''
        } ${className}`}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        {children}
        {showIcon && <Info className="w-3 h-3 text-zinc-500" />}
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            transition={{ duration: 0.12 }}
            className="fixed z-[9999] w-[280px] p-3 bg-zinc-900/95 backdrop-blur-sm border border-cyan-500/30 rounded-lg shadow-xl pointer-events-none"
            style={{ 
              top: position.y,
              left: position.x,
              transform: 'translateY(-100%)'
            }}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="font-semibold text-cyan-400 text-sm">{definition.term}</span>
              <span className="text-[11px] text-zinc-500 uppercase tracking-wider px-1.5 py-0.5 bg-zinc-800 rounded">
                {definition.category}
              </span>
            </div>
            <p className="text-xs text-zinc-300 leading-relaxed">{definition.def}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

/**
 * Icon-only tooltip - shows help icon that reveals tooltip on hover
 */
export const TipIcon = ({ id, size = 'sm' }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const triggerRef = useRef(null);
  
  const definition = tooltipDefinitions[id];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPosition({
        x: Math.max(10, rect.left - 130),
        y: rect.top - 8
      });
    }
  }, [isVisible]);
  
  if (!definition) return null;
  
  const sizeMap = { sm: 'w-3 h-3', md: 'w-4 h-4', lg: 'w-5 h-5' };
  
  return (
    <>
      <span
        ref={triggerRef}
        className="inline-flex cursor-help text-zinc-500 hover:text-cyan-400 transition-colors ml-1"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        <HelpCircle className={sizeMap[size]} />
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className="fixed z-[9999] w-[280px] p-3 bg-zinc-900/95 backdrop-blur-sm border border-cyan-500/30 rounded-lg shadow-xl pointer-events-none"
            style={{ 
              top: position.y,
              left: position.x,
              transform: 'translateY(-100%)'
            }}
          >
            <span className="font-semibold text-cyan-400 text-sm block mb-1">{definition.term}</span>
            <p className="text-xs text-zinc-300 leading-relaxed">{definition.def}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

/**
 * Custom tooltip for one-off explanations not in the definition list
 */
export const CustomTip = ({ 
  label, 
  description, 
  children, 
  className = '',
  position = 'top'
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const triggerRef = useRef(null);
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const tooltipWidth = 280;
      let x = rect.left + rect.width / 2 - tooltipWidth / 2;
      let y = position === 'bottom' ? rect.bottom + 8 : rect.top - 8;
      
      x = Math.max(10, Math.min(x, window.innerWidth - tooltipWidth - 10));
      
      setPos({ x, y });
    }
  }, [isVisible, position]);
  
  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center cursor-help ${className}`}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        {children}
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            className="fixed z-[9999] w-[280px] p-3 bg-zinc-900/95 backdrop-blur-sm border border-cyan-500/30 rounded-lg shadow-xl pointer-events-none"
            style={{ 
              top: pos.y,
              left: pos.x,
              transform: position === 'top' ? 'translateY(-100%)' : undefined
            }}
          >
            {label && <span className="font-semibold text-cyan-400 text-sm block mb-1">{label}</span>}
            <p className="text-xs text-zinc-300 leading-relaxed">{description}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

/**
 * Metric tooltip - for displaying metrics with context
 */
export const MetricTip = ({ 
  id,
  value,
  format = 'default',
  className = '' 
}) => {
  const definition = tooltipDefinitions[id];
  
  // Format value based on type
  const formatValue = () => {
    if (value === null || value === undefined) return '--';
    switch (format) {
      case 'percent': return `${value.toFixed(1)}%`;
      case 'currency': return `$${value.toLocaleString()}`;
      case 'number': return value.toLocaleString();
      default: return value;
    }
  };
  
  if (!definition) {
    return <span className={className}>{formatValue()}</span>;
  }
  
  return (
    <Tip id={id} className={className}>
      {formatValue()}
    </Tip>
  );
};

// Export for backward compatibility
export { HelpCircle, Info };
export default Tip;
