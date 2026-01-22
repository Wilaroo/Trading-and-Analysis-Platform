import React, { useState, useEffect, useRef } from 'react';
import { RefreshCw, LineChart } from 'lucide-react';

// ===================== TRADINGVIEW WIDGET =====================
const TradingViewWidget = ({ symbol = 'AAPL', theme = 'dark' }) => {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.innerHTML = '';
      
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      script.type = 'text/javascript';
      script.async = true;
      script.innerHTML = JSON.stringify({
        autosize: true,
        symbol: symbol,
        interval: 'D',
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
        backgroundColor: 'rgba(5, 5, 5, 1)',
        gridColor: 'rgba(255, 255, 255, 0.06)',
        studies: ['RSI@tv-basicstudies', 'MASimple@tv-basicstudies', 'MACD@tv-basicstudies']
      });

      containerRef.current.appendChild(script);
    }
  }, [symbol, theme]);

  return (
    <div className="tradingview-widget-container h-full" ref={containerRef}>
      <div className="tradingview-widget-container__widget h-full"></div>
    </div>
  );
};

// ===================== CHARTS PAGE =====================
const ChartsPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const popularSymbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'SPY', 'QQQ', 'BTC-USD'];

  const handleSymbolChange = () => {
    setSymbol(inputSymbol.toUpperCase());
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="charts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <LineChart className="w-6 h-6 text-primary" />
            TradingView Charts
          </h1>
          <p className="text-zinc-500 text-sm">Professional charting with technical indicators</p>
        </div>
      </div>

      {/* Symbol Input */}
      <div className="bg-paper rounded-lg p-4 border border-white/10">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbol</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputSymbol}
                onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                onKeyPress={(e) => e.key === 'Enter' && handleSymbolChange()}
                placeholder="Enter symbol..."
                className="flex-1 bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                data-testid="chart-symbol-input"
              />
              <button 
                onClick={handleSymbolChange}
                className="btn-primary"
                data-testid="load-chart-btn"
              >
                Load Chart
              </button>
            </div>
          </div>
        </div>
        
        {/* Popular Symbols */}
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
          {popularSymbols.map((sym) => (
            <button
              key={sym}
              onClick={() => { setInputSymbol(sym); setSymbol(sym); }}
              className={`text-xs px-3 py-1.5 rounded-full transition-colors ${
                symbol === sym 
                  ? 'bg-primary/20 text-primary border border-primary/30' 
                  : 'bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white'
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      </div>

      {/* Chart Container */}
      <div className="bg-paper rounded-lg border border-white/10 overflow-hidden" style={{ height: 'calc(100vh - 300px)', minHeight: '500px' }}>
        <TradingViewWidget symbol={symbol} theme="dark" />
      </div>
    </div>
  );
};

export default ChartsPage;
