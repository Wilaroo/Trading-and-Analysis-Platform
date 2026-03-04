import React from 'react';
import AICommandPanel from '../AICommandPanel';
import RightSidebar from '../RightSidebar';

const AICoachTab = ({
  setSelectedTicker,
  watchlist,
  enhancedAlerts,
  alerts,
  opportunities,
  earnings,
  isConnected,
  runScanner,
  account,
  marketContext,
  positions,
  viewChart,
  chartSymbol,
  setChartSymbol,
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = [],
  wsCoachingNotifications = []
}) => {
  // Handle ticker click - updates chart and opens detail modal
  // Can receive either a string ticker or an object { symbol, quote, ... }
  const handleTickerClick = (tickerOrObject) => {
    const symbol = typeof tickerOrObject === 'string' 
      ? tickerOrObject 
      : tickerOrObject?.symbol;
    
    if (symbol) {
      setChartSymbol(symbol); // Update chart
      setSelectedTicker(symbol); // Open ticker detail modal
    }
  };

  return (
    <div className="grid lg:grid-cols-12 gap-4" data-testid="ai-coach-tab-content">
      {/* LEFT - AI Trading Assistant (Bot + AI integrated) - Takes more space */}
      <div className="lg:col-span-8">
        <div className="h-[calc(100vh-200px)] min-h-[650px]">
          <AICommandPanel
            onTickerSelect={handleTickerClick}
            onViewChart={(ticker) => setChartSymbol(ticker)}
            watchlist={watchlist}
            alerts={[...enhancedAlerts, ...alerts]}
            opportunities={opportunities}
            earnings={earnings}
            scanResults={opportunities}
            isConnected={isConnected}
            onRefresh={() => runScanner()}
            account={account}
            marketContext={marketContext}
            positions={positions}
            chartSymbol={chartSymbol}
            setChartSymbol={setChartSymbol}
            // WebSocket-pushed data
            wsBotStatus={wsBotStatus}
            wsBotTrades={wsBotTrades}
            wsCoachingNotifications={wsCoachingNotifications}
          />
        </div>
      </div>

      {/* RIGHT - Market Intel + Scanner */}
      <div className="lg:col-span-4">
        <RightSidebar 
          onTickerSelect={handleTickerClick}
          onViewChart={(ticker) => setChartSymbol(ticker)}
          // WebSocket-pushed data
          wsScannerAlerts={wsScannerAlerts}
          wsScannerStatus={wsScannerStatus}
          wsSmartWatchlist={wsSmartWatchlist}
        />
      </div>
    </div>
  );
};

export default AICoachTab;
