import React from 'react';
import AICommandPanel from '../AICommandPanel';
import MarketIntelPanel from '../MarketIntelPanel';

const AICoachTab = ({
  setSelectedTicker,
  watchlist,
  enhancedAlerts,
  alerts,
  opportunities,
  earnings,
  positions,
  marketContext,
  isConnected,
  runScanner,
}) => {
  return (
    <div className="grid lg:grid-cols-12 gap-4 mt-2" data-testid="ai-coach-tab-content">
      {/* CENTER - AI Command Panel */}
      <div className="lg:col-span-8">
        <div className="h-[calc(100vh-220px)] min-h-[600px]">
          <AICommandPanel
            onTickerSelect={(ticker) => setSelectedTicker(ticker)}
            watchlist={watchlist}
            alerts={[...enhancedAlerts, ...alerts]}
            opportunities={opportunities}
            earnings={earnings}
            portfolio={positions}
            scanResults={opportunities}
            marketIndices={marketContext?.indices || []}
            isConnected={isConnected}
            onRefresh={() => runScanner()}
          />
        </div>
      </div>

      {/* Right - Market Intelligence */}
      <div className="lg:col-span-4">
        <MarketIntelPanel />
      </div>
    </div>
  );
};

export default AICoachTab;
