import React, { useEffect, useRef, memo } from 'react';

// Map common symbols to their exchange prefix for real-time data
const getFullSymbol = (ticker) => {
  if (!ticker) return 'AMEX:SPY';
  
  // Already has exchange prefix
  if (ticker.includes(':')) return ticker;
  
  const upper = ticker.toUpperCase();
  
  // ETFs on AMEX/ARCA
  const etfs = ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX', 'GLD', 'SLV', 'TLT', 'XLF', 'XLK', 'XLE', 'XLV', 'XLI', 'XLC', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB', 'VXX', 'UVXY', 'SQQQ', 'TQQQ', 'ARKK'];
  if (etfs.includes(upper)) return `AMEX:${upper}`;
  
  // Major NASDAQ stocks
  const nasdaq = ['AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'INTC', 'NFLX', 'COST', 'PYPL', 'ADBE', 'CMCSA', 'PEP', 'CSCO', 'AVGO', 'TXN', 'QCOM', 'TMUS', 'SBUX', 'GILD', 'MDLZ', 'ISRG', 'VRTX', 'REGN', 'ATVI', 'ADP', 'BKNG', 'FISV', 'ILMN', 'MU', 'LRCX', 'AMAT', 'KLAC', 'MRVL', 'SNPS', 'CDNS', 'ASML', 'MELI', 'ABNB', 'PANW', 'CRWD', 'DDOG', 'ZS', 'SNOW', 'MDB', 'NET', 'COIN', 'HOOD', 'RIVN', 'LCID', 'SOFI', 'PLTR', 'RBLX', 'ROKU', 'ZM', 'DOCU', 'OKTA', 'TWLO', 'SQ', 'SHOP', 'SE', 'SPOT', 'PINS', 'SNAP', 'UBER', 'LYFT', 'DASH', 'ABNB', 'DKNG'];
  if (nasdaq.includes(upper)) return `NASDAQ:${upper}`;
  
  // NYSE stocks (most others)
  const nyse = ['JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'V', 'MA', 'AXP', 'BRK.A', 'BRK.B', 'JNJ', 'UNH', 'PFE', 'MRK', 'ABBV', 'BMY', 'LLY', 'TMO', 'ABT', 'DHR', 'CVS', 'MCK', 'CAH', 'WMT', 'TGT', 'HD', 'LOW', 'NKE', 'LULU', 'MCD', 'YUM', 'SBUX', 'KO', 'DIS', 'T', 'VZ', 'XOM', 'CVX', 'COP', 'SLB', 'OXY', 'BA', 'LMT', 'RTX', 'GE', 'HON', 'CAT', 'DE', 'MMM', 'UPS', 'FDX', 'F', 'GM', 'TM', 'NIO', 'XPEV', 'LI', 'CRM', 'NOW', 'ORCL', 'IBM', 'ACN', 'SAP'];
  if (nyse.includes(upper)) return `NYSE:${upper}`;
  
  // Default to NYSE for unknown symbols
  return `NYSE:${upper}`;
};

const TradingViewWidget = memo(({ symbol = 'SPY', theme = 'dark', height = '100%' }) => {
  const container = useRef(null);
  const scriptRef = useRef(null);
  
  // Get the full symbol with exchange prefix for real-time data
  const fullSymbol = getFullSymbol(symbol);

  useEffect(() => {
    // Clear previous widget
    if (container.current) {
      container.current.innerHTML = '';
    }

    // Create the TradingView widget script
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: fullSymbol,
      interval: '5',
      timezone: 'America/New_York',
      theme: theme,
      style: '1',
      locale: 'en',
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com',
      backgroundColor: theme === 'dark' ? 'rgba(10, 10, 10, 1)' : 'rgba(255, 255, 255, 1)',
      gridColor: theme === 'dark' ? 'rgba(31, 41, 55, 1)' : 'rgba(200, 200, 200, 1)',
      studies: ['MASimple@tv-basicstudies'],
      withdateranges: true,
      allow_symbol_change: true,
    });

    if (container.current) {
      container.current.appendChild(script);
      scriptRef.current = script;
    }

    return () => {
      if (scriptRef.current && container.current) {
        try {
          container.current.removeChild(scriptRef.current);
        } catch (e) {
          // Script may have been removed already
        }
      }
    };
  }, [fullSymbol, theme]);

  return (
    <div 
      className="tradingview-widget-container" 
      ref={container} 
      style={{ height, width: '100%' }}
      data-testid="tradingview-widget"
    >
      <div 
        className="tradingview-widget-container__widget" 
        style={{ height: '100%', width: '100%' }}
      />
    </div>
  );
});

TradingViewWidget.displayName = 'TradingViewWidget';

export default TradingViewWidget;
