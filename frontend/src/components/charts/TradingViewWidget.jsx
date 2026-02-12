import React, { useEffect, useRef, memo } from 'react';

const TradingViewWidget = memo(({ symbol = 'SPY', theme = 'dark', height = '100%' }) => {
  const container = useRef(null);
  const scriptRef = useRef(null);

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
      symbol: symbol,
      interval: '5',
      timezone: 'Etc/UTC',
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
  }, [symbol, theme]);

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
