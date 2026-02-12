import React, { useState, useEffect } from 'react';
import { LineChart, TrendingUp, Search, Star, Clock } from 'lucide-react';
import TradingViewWidget from '../charts/TradingViewWidget';

const ChartsTab = ({ 
  isConnected, 
  isBusy, 
  busyOperation,
  chartSymbol,
  setChartSymbol,
  watchlist = [],
  recentCharts = [],
  onAddToRecent
}) => {
  const [inputSymbol, setInputSymbol] = useState(chartSymbol || 'SPY');
  
  // Sync input with chartSymbol prop when it changes externally
  useEffect(() => {
    if (chartSymbol && chartSymbol !== inputSymbol) {
      setInputSymbol(chartSymbol);
    }
  }, [chartSymbol]);

  const popularSymbols = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'TSLA', 'MSFT', 'AMZN', 'META', 'GOOGL', 'AMD'];
  
  const handleSymbolChange = (newSymbol) => {
    const symbol = newSymbol.toUpperCase().trim();
    if (symbol) {
      setInputSymbol(symbol);
      setChartSymbol(symbol);
      if (onAddToRecent) {
        onAddToRecent(symbol);
      }
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleSymbolChange(inputSymbol);
    }
  };

  return (
    <div className="space-y-3 h-full" data-testid="charts-tab">
      {/* Symbol Selector Bar */}
      <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-3">
        <div className="flex items-center gap-4">
          {/* Search Input */}
          <div className="flex-1 max-w-xs">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <input
                type="text"
                value={inputSymbol}
                onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                onKeyPress={handleKeyPress}
                placeholder="Enter symbol..."
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg pl-9 pr-4 py-2 text-white text-sm placeholder-zinc-500 focus:border-cyan-500/50 focus:outline-none"
                data-testid="chart-symbol-input"
              />
            </div>
          </div>
          
          <button 
            onClick={() => handleSymbolChange(inputSymbol)}
            className="px-4 py-2 bg-cyan-500 text-black text-sm font-medium rounded-lg hover:bg-cyan-400 transition-colors"
            data-testid="load-chart-btn"
          >
            Load
          </button>

          {/* Divider */}
          <div className="h-8 w-px bg-zinc-700" />

          {/* Popular Symbols */}
          <div className="flex items-center gap-1 overflow-x-auto">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wider mr-1">Quick:</span>
            {popularSymbols.slice(0, 8).map((sym) => (
              <button
                key={sym}
                onClick={() => handleSymbolChange(sym)}
                className={`px-2 py-1 text-xs rounded transition-colors whitespace-nowrap ${
                  chartSymbol === sym 
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white border border-transparent'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>

        {/* Secondary row: Watchlist & Recent */}
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-zinc-800/50">
          {/* From Watchlist */}
          {watchlist.length > 0 && (
            <div className="flex items-center gap-1">
              <Star className="w-3 h-3 text-yellow-500" />
              <span className="text-[10px] text-zinc-500 mr-1">Watchlist:</span>
              {watchlist.slice(0, 5).map((item) => (
                <button
                  key={item.symbol}
                  onClick={() => handleSymbolChange(item.symbol)}
                  className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                    chartSymbol === item.symbol 
                      ? 'bg-yellow-500/20 text-yellow-400' 
                      : 'bg-zinc-800/50 text-zinc-500 hover:text-yellow-400'
                  }`}
                >
                  {item.symbol}
                </button>
              ))}
            </div>
          )}

          {/* Recent Charts */}
          {recentCharts.length > 0 && (
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-zinc-500" />
              <span className="text-[10px] text-zinc-500 mr-1">Recent:</span>
              {recentCharts.slice(0, 5).map((sym) => (
                <button
                  key={sym}
                  onClick={() => handleSymbolChange(sym)}
                  className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                    chartSymbol === sym 
                      ? 'bg-cyan-500/20 text-cyan-400' 
                      : 'bg-zinc-800/50 text-zinc-500 hover:text-white'
                  }`}
                >
                  {sym}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Chart Container */}
      <div 
        className="bg-zinc-900/30 rounded-lg border border-zinc-800 overflow-hidden flex-1"
        style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}
      >
        {chartSymbol ? (
          <TradingViewWidget 
            symbol={chartSymbol}
            theme="dark"
            height="100%"
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-zinc-500">
            <LineChart className="w-16 h-16 mb-4 text-zinc-700" />
            <p className="text-lg font-medium">Select a Symbol</p>
            <p className="text-sm text-zinc-600">Enter a ticker or click one of the quick symbols above</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChartsTab;
