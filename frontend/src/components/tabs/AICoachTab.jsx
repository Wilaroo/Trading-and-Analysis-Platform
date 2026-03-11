import React from 'react';
import AICommandPanel from '../AICommandPanel';
import RightSidebar from '../RightSidebar';
import LearningInsightsWidget from '../LearningInsightsWidget';

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
  wsCoachingNotifications = [],
  // Navigation callback
  onNavigateToTab = null
}) => {
  // Handle ticker click - updates chart and opens detail modal
  // Can receive either a string ticker or an object { symbol, quote, ... }
  const handleTickerClick = (tickerOrObject) => {
    const symbol = typeof tickerOrObject === 'string' 
      ? tickerOrObject 
      : tickerOrObject?.symbol;
    
    if (symbol) {
      setChartSymbol(symbol); // Update chart
      // Pass object to setSelectedTicker for modal compatibility
      setSelectedTicker({ symbol, quote: {}, fromClick: true });
    }
  };

  // Navigate to Analytics tab with Intelligence Hub
  const handleNavigateToHub = () => {
    if (onNavigateToTab) {
      onNavigateToTab('analytics');
    }
  };

  return (
    <div className="space-y-3" data-testid="ai-coach-tab-content">
      {/* Learning Insights Widget - Compact overview */}
      <LearningInsightsWidget 
        onNavigateToHub={handleNavigateToHub}
      />
      
      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-12 gap-4">
        {/* LEFT - AI Trading Assistant (Bot + AI integrated) - Takes more space */}
        <div className="lg:col-span-9">
          <div className="h-[calc(100vh-180px)] min-h-[800px]">
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

        {/* RIGHT - Market Intel + Scanner - Slimmer sidebar */}
        <div className="lg:col-span-3">
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
    </div>
  );
};

export default AICoachTab;
