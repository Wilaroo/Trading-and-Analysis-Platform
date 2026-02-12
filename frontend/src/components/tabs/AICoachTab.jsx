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
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = [],
  wsCoachingNotifications = []
}) => {
  return (
    <div className="grid lg:grid-cols-12 gap-4" data-testid="ai-coach-tab-content">
      {/* LEFT - AI Trading Assistant (Bot + AI integrated) - Takes more space */}
      <div className="lg:col-span-8">
        <div className="h-[calc(100vh-200px)] min-h-[650px]">
          <AICommandPanel
            onTickerSelect={(ticker) => setSelectedTicker(ticker)}
            onViewChart={viewChart}
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
          onTickerSelect={(ticker) => setSelectedTicker(ticker)} 
          onViewChart={viewChart}
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
