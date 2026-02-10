import React from 'react';
import AICommandPanel from '../AICommandPanel';
import TradingBotPanel from '../TradingBotPanel';
import MarketIntelPanel from '../MarketIntelPanel';

const AICoachTab = ({
  setSelectedTicker,
  watchlist,
  enhancedAlerts,
  alerts,
  opportunities,
  earnings,
  isConnected,
  runScanner,
}) => {
  return (
    <div className="grid lg:grid-cols-12 gap-4 mt-2" data-testid="ai-coach-tab-content">
      {/* LEFT - Bot + AI Chat */}
      <div className="lg:col-span-8 space-y-4">
        {/* Trading Bot - Compact at top */}
        <TradingBotPanel
          onTickerSelect={(ticker) => setSelectedTicker(ticker)}
        />

        {/* AI Command Panel */}
        <div className="h-[calc(100vh-480px)] min-h-[400px]">
          <AICommandPanel
            onTickerSelect={(ticker) => setSelectedTicker(ticker)}
            watchlist={watchlist}
            alerts={[...enhancedAlerts, ...alerts]}
            opportunities={opportunities}
            earnings={earnings}
            scanResults={opportunities}
            isConnected={isConnected}
            onRefresh={() => runScanner()}
          />
        </div>
      </div>

      {/* RIGHT - Market Intelligence */}
      <div className="lg:col-span-4">
        <MarketIntelPanel />
      </div>
    </div>
  );
};

export default AICoachTab;
