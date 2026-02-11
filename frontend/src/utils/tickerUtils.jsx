/**
 * Ticker and Link Utilities
 * Shared components for making ticker symbols and URLs clickable
 */
import React from 'react';
import { ArrowUpRight, ExternalLink } from 'lucide-react';

// Known ticker symbols for detection
export const KNOWN_TICKERS = new Set([
  'AAPL','MSFT','NVDA','TSLA','AMD','META','GOOGL','AMZN','GOOG','NFLX',
  'SPY','QQQ','IWM','DIA','VIX','SOFI','PLTR','RIVN','INTC','UBER',
  'COST','WMT','TGT','JPM','BAC','GS','V','MA','PYPL','SQ','SHOP',
  'CRM','ORCL','ADBE','NOW','SNOW','NET','CRWD','ZS','DDOG','MDB',
  'COIN','HOOD','RBLX','ROKU','SNAP','PINS','SPOT','SE','MELI',
  'BA','LMT','GE','CAT','DE','HON','MMM','UNH','JNJ','PFE','MRNA',
  'LLY','ABBV','BMY','GILD','AMGN','XOM','CVX','COP','SLB','OXY',
  'AVGO','QCOM','MU','AMAT','LRCX','KLAC','TXN','MRVL','ARM',
  'F','GM','TM','NIO','XPEV','LI','LCID','FSR','DIS','CMCSA','WBD',
  'T','VZ','TMUS','KO','PEP','MCD','SBUX','NKE','LULU', 'KHC', 'BABA',
  'BRK', 'HD', 'LOW', 'CVS', 'WBA', 'UPS', 'FDX', 'DAL', 'UAL', 'AAL',
  'LUV', 'CCL', 'RCL', 'NCLH', 'MAR', 'HLT', 'ABNB', 'BKNG', 'EXPE',
  'ZM', 'DOCU', 'OKTA', 'TWLO', 'U', 'UNITY', 'EA', 'ATVI', 'TTWO',
  'GME', 'AMC', 'BB', 'NOK', 'WISH', 'CLOV', 'SPCE', 'BYND', 'DASH',
  'ABNB', 'DKNG', 'PENN', 'MGM', 'WYNN', 'LVS', 'BTC', 'ETH',
  'IBM', 'CSCO', 'HPQ', 'DELL', 'VMW', 'PANW', 'FTNT', 'SPLK',
  'WORK', 'TEAM', 'ATLASSIAN', 'ASANA', 'MNDY', 'PATH', 'AI', 'PLTR'
]);

// Clickable ticker link component
export const TickerLink = ({ symbol, onClick }) => (
  <button
    onClick={(e) => {
      e.stopPropagation();
      onClick(symbol);
    }}
    className="inline-flex items-center gap-0.5 px-1 py-0.5 bg-cyan-500/10 border border-cyan-500/20 rounded text-cyan-400 font-mono font-semibold text-xs hover:bg-cyan-500/20 hover:border-cyan-500/40 transition-colors cursor-pointer"
    data-testid={`ticker-link-${symbol}`}
  >
    {symbol}
    <ArrowUpRight className="w-3 h-3" />
  </button>
);

// External link component for news URLs
export const NewsLink = ({ url, children, className = '' }) => {
  if (!url) return <span className={className}>{children}</span>;
  
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={`hover:text-cyan-400 transition-colors inline-flex items-center gap-1 ${className}`}
    >
      {children}
      <ExternalLink className="w-3 h-3 opacity-50" />
    </a>
  );
};

// Parse text and wrap ticker symbols in clickable links
export const TickerAwareText = ({ text, onTickerClick, className = '' }) => {
  if (!text || typeof text !== 'string') return <span className={className}>{text}</span>;
  
  // Match common ticker patterns: $AAPL, AAPL, MSFT (1-5 uppercase letters, optionally preceded by $)
  // Also match patterns like "Kraft Heinz (KHC)" - ticker in parentheses
  const tickerRegex = /(\$[A-Z]{1,5}(?=[\s,.:;!?)}\]"]|$))|(\([A-Z]{1,5}\))|(\b[A-Z]{1,5}\b(?=[\s,.:;!?)}\]'"]|$))/g;
  
  const parts = [];
  let lastIndex = 0;
  let match;
  
  while ((match = tickerRegex.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    
    // Extract the ticker symbol (remove $ or parentheses)
    let ticker = match[0].replace(/[$()]/g, '');
    
    // Only make it clickable if it's a known ticker
    if (KNOWN_TICKERS.has(ticker) && ticker.length >= 2) {
      parts.push(
        <TickerLink key={match.index} symbol={ticker} onClick={onTickerClick} />
      );
    } else {
      parts.push(match[0]);
    }
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  
  return <span className={className}>{parts}</span>;
};

// Render markdown-like text with ticker awareness
export const renderTickerAwareContent = (text, onTickerClick) => {
  if (!text) return null;
  
  return text.split('\n').map((line, i) => {
    // Headers (bold text)
    if (line.startsWith('**') && line.endsWith('**')) {
      const headerText = line.replace(/\*\*/g, '');
      return (
        <h3 key={i} className="text-sm font-bold text-white mt-3 mb-1">
          <TickerAwareText text={headerText} onTickerClick={onTickerClick} />
        </h3>
      );
    }
    
    // Bold sections within text
    const parts = line.split(/(\*\*[^*]+\*\*)/g);
    const rendered = parts.map((part, j) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        const boldText = part.replace(/\*\*/g, '');
        return (
          <strong key={j} className="text-white font-semibold">
            <TickerAwareText text={boldText} onTickerClick={onTickerClick} />
          </strong>
        );
      }
      return <TickerAwareText key={j} text={part} onTickerClick={onTickerClick} />;
    });
    
    // List items
    if (line.startsWith('- ') || line.startsWith('  - ')) {
      const indent = line.startsWith('  ') ? 'ml-4' : 'ml-2';
      return <p key={i} className={`text-xs text-zinc-300 ${indent} py-0.5`}>{rendered}</p>;
    }
    
    // Numbered items
    if (line.match(/^\d+\./)) {
      return <p key={i} className="text-xs text-zinc-300 ml-2 py-0.5">{rendered}</p>;
    }
    
    // Empty lines
    if (line.trim() === '') return <div key={i} className="h-1" />;
    
    // Regular text
    return <p key={i} className="text-xs text-zinc-400 py-0.5">{rendered}</p>;
  });
};

// Extract ticker symbols from text
export const extractTickers = (text) => {
  if (!text) return [];
  const matches = text.match(/\$?[A-Z]{2,5}(?=[\s,.:;!?)}\]"]|$)/g) || [];
  return [...new Set(matches.map(t => t.replace('$', '')).filter(t => KNOWN_TICKERS.has(t)))];
};
