import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle, ExternalLink } from 'lucide-react';

// Mini-definitions for common terms (subset of glossary for quick tooltips)
const tooltipDefinitions = {
  // Scores
  'overall-score': { term: 'Overall Score', def: 'Composite score (0-100) combining technical, fundamental, and catalyst factors. Higher = better opportunity.' },
  'technical-score': { term: 'Technical Score', def: 'Score based on price action, trend alignment, and technical indicators like RSI, MACD, and moving averages.' },
  'fundamental-score': { term: 'Fundamental Score', def: 'Score based on company financials, market cap, sector strength, and institutional activity.' },
  'catalyst-score': { term: 'Catalyst Score', def: 'Score measuring potential price-moving events like earnings, news, and options activity.' },
  'confidence-score': { term: 'Confidence Score', def: 'How reliable the analysis is based on data quality and indicator agreement.' },
  'signal-strength': { term: 'Signal Strength', def: 'Percentage of your 77 trading rules that the stock matches. Higher = more confirmations.' },
  'breakout-score': { term: 'Breakout Score', def: 'Composite score for breakout quality including volume, trend alignment, and strategy matches.' },
  'grade': { term: 'Grade', def: 'Letter grade (A-F) based on Overall Score. A=80-100, B=65-79, C=50-64, D=35-49, F=0-34.' },
  
  // Technical Indicators
  'rsi': { term: 'RSI', def: 'Relative Strength Index (0-100). >70 overbought, <30 oversold, 40-60 neutral zone.' },
  'macd': { term: 'MACD', def: 'Trend momentum indicator. Bullish when MACD crosses above signal line.' },
  'vwap': { term: 'VWAP', def: 'Volume Weighted Average Price. Above = bullish, Below = bearish. Resets daily.' },
  'vwap-dist': { term: 'VWAP Distance', def: 'How far price is from VWAP. Extended >2% often reverts to mean.' },
  'ema': { term: 'EMA', def: 'Exponential Moving Average. Key levels: 9 (fast), 20 (medium), 50 (slow).' },
  'ema-9': { term: 'EMA 9', def: 'Fast moving average for short-term trend. Price above = bullish momentum.' },
  'ema-20': { term: 'EMA 20', def: 'Medium-term trend indicator. Often acts as support/resistance.' },
  'sma-50': { term: 'SMA 50', def: '50-day Simple Moving Average. Key institutional level for trend direction.' },
  'atr': { term: 'ATR', def: 'Average True Range. Measures volatility. Used for stop loss and position sizing.' },
  
  // Volume & Momentum
  'rvol': { term: 'RVOL', def: 'Relative Volume. 1.5x+ confirms moves. 2x+ indicates significant interest.' },
  'volume': { term: 'Volume', def: 'Number of shares traded. Higher volume = more conviction in move.' },
  'momentum': { term: 'Momentum', def: 'Rate of price change. Strong momentum = trend likely to continue.' },
  
  // Levels
  'support': { term: 'Support', def: 'Price level where buying pressure emerges. Price tends to bounce here.' },
  'resistance': { term: 'Resistance', def: 'Price level where selling pressure emerges. Price tends to stall here.' },
  'r1': { term: 'R1', def: 'First resistance level above current price.' },
  'r2': { term: 'R2', def: 'Second (stronger) resistance level.' },
  's1': { term: 'S1', def: 'First support level below current price.' },
  's2': { term: 'S2', def: 'Second (stronger) support level.' },
  
  // Risk Management
  'stop-loss': { term: 'Stop Loss', def: 'Pre-defined exit price to limit losses. Should invalidate trade thesis.' },
  'target': { term: 'Target', def: 'Price target for taking profits. Usually 2-3x the risk distance.' },
  'risk-reward': { term: 'R/R', def: 'Risk/Reward ratio. 2:1 minimum recommended (risk $1 to make $2).' },
  'entry': { term: 'Entry', def: 'Recommended entry price for the trade.' },
  
  // Market Context
  'bias': { term: 'Bias', def: 'Directional lean: BULLISH (expect up), BEARISH (expect down), NEUTRAL (no clear direction).' },
  'trend': { term: 'Trend', def: 'Current price direction based on moving average alignment and price structure.' },
  'regime': { term: 'Market Regime', def: 'Overall market condition: Bullish, Bearish, Neutral, or Volatile.' },
  'vix': { term: 'VIX', def: 'Fear gauge. <15 calm, 15-20 normal, 20-30 elevated, >30 high fear.' },
  
  // Earnings & Events
  'iv': { term: 'IV', def: 'Implied Volatility. Market\'s expected move. High before earnings, crushes after.' },
  'iv-rank': { term: 'IV Rank', def: 'IV percentile (0-100). 100 = IV at yearly high.' },
  'expected-move': { term: 'Expected Move', def: 'How much market expects stock to move based on options pricing.' },
  'short-interest': { term: 'Short Interest', def: 'Shares sold short as % of float. >20% is elevated, squeeze potential.' },
  'days-to-cover': { term: 'Days to Cover', def: 'Days for shorts to cover at avg volume. >5 days = squeeze risk.' },
  'squeeze-score': { term: 'Squeeze Score', def: 'Likelihood of short squeeze (0-100). Based on SI%, days to cover, and RVOL.' },
  
  // Timeframes
  'intraday': { term: 'Intraday', def: 'Trade opened and closed within the same day. Quick scalps to day trades.' },
  'swing': { term: 'Swing', def: 'Trade held for days to weeks. Captures larger moves.' },
  'position': { term: 'Position', def: 'Trade held for weeks to months. Long-term trend plays.' },
  
  // Orders
  'market-order': { term: 'Market Order', def: 'Execute immediately at best available price. Fast but no price control.' },
  'limit-order': { term: 'Limit Order', def: 'Execute only at specified price or better. Price control but may not fill.' },
  
  // Misc
  'mcap': { term: 'Market Cap', def: 'Company size. Large cap >$10B, Mid cap $2-10B, Small cap <$2B.' },
  'float': { term: 'Float', def: 'Shares available for public trading. Low float = more volatile.' },
  'avg-volume': { term: 'Avg Volume', def: 'Average daily trading volume. Used to calculate RVOL.' },
};

// HelpTooltip component - wrap any text to add hover tooltip
export const HelpTooltip = ({ 
  termId, 
  children, 
  className = '',
  showIcon = false,
  position = 'top' 
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef(null);
  const tooltipRef = useRef(null);
  
  const definition = tooltipDefinitions[termId];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const tooltipWidth = 280;
      
      let top, left;
      
      switch (position) {
        case 'bottom':
          top = rect.bottom + 8;
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
          break;
        case 'left':
          top = rect.top + (rect.height / 2);
          left = rect.left - tooltipWidth - 8;
          break;
        case 'right':
          top = rect.top + (rect.height / 2);
          left = rect.right + 8;
          break;
        default: // top
          top = rect.top - 8;
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
      }
      
      // Keep tooltip in viewport
      left = Math.max(10, Math.min(left, window.innerWidth - tooltipWidth - 10));
      
      setTooltipPosition({ top, left });
    }
  }, [isVisible, position]);
  
  if (!definition) {
    return <span className={className}>{children}</span>;
  }
  
  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center gap-1 cursor-help border-b border-dotted border-zinc-600 hover:border-cyan-400 transition-colors ${className}`}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        {children}
        {showIcon && <HelpCircle className="w-3 h-3 text-zinc-500" />}
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            ref={tooltipRef}
            initial={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: position === 'bottom' ? -5 : 5 }}
            transition={{ duration: 0.15 }}
            className="fixed z-[100] w-[280px] p-3 bg-zinc-900 border border-cyan-500/30 rounded-lg shadow-xl"
            style={{ 
              top: tooltipPosition.top,
              left: tooltipPosition.left,
              transform: position === 'top' ? 'translateY(-100%)' : undefined
            }}
          >
            <div className="flex items-start justify-between mb-1">
              <span className="font-semibold text-cyan-400 text-sm">{definition.term}</span>
              <a 
                href={`#glossary-${termId}`}
                className="text-zinc-500 hover:text-cyan-400 transition-colors"
                onClick={(e) => {
                  e.preventDefault();
                  // Could navigate to glossary page with this term selected
                  window.location.href = `/glossary?search=${encodeURIComponent(definition.term)}`;
                }}
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <p className="text-xs text-zinc-300 leading-relaxed">{definition.def}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

// Helper component for quick inline tooltips
export const HelpIcon = ({ termId, size = 'sm' }) => {
  const [isVisible, setIsVisible] = useState(false);
  const triggerRef = useRef(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  
  const definition = tooltipDefinitions[termId];
  
  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPosition({
        top: rect.top - 8,
        left: rect.left + rect.width / 2 - 140
      });
    }
  }, [isVisible]);
  
  if (!definition) return null;
  
  const sizeClasses = {
    sm: 'w-3 h-3',
    md: 'w-4 h-4',
    lg: 'w-5 h-5'
  };
  
  return (
    <>
      <span
        ref={triggerRef}
        className="inline-flex cursor-help text-zinc-500 hover:text-cyan-400 transition-colors"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
      >
        <HelpCircle className={sizeClasses[size]} />
      </span>
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className="fixed z-[100] w-[280px] p-3 bg-zinc-900 border border-cyan-500/30 rounded-lg shadow-xl"
            style={{ 
              top: position.top,
              left: Math.max(10, position.left),
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

// Export definitions for use elsewhere
export const getTooltipDefinition = (termId) => tooltipDefinitions[termId];
export const hasTooltip = (termId) => !!tooltipDefinitions[termId];

export default HelpTooltip;
