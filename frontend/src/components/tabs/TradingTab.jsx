import React from 'react';
import TradeSignals from '../TradeSignals';
import TradingBotPanel from '../TradingBotPanel';

const TradingTab = ({
  liveAlertsExpanded,
  setLiveAlertsExpanded,
  setSelectedTicker,
}) => {
  return (
    <div className="space-y-4 mt-2" data-testid="trading-tab-content">
      {/* Trade Signals - Compact unified signal feed */}
      <TradeSignals
        isExpanded={liveAlertsExpanded}
        onToggleExpand={() => setLiveAlertsExpanded(!liveAlertsExpanded)}
        onSignalSelect={(signal) => {
          setSelectedTicker({ symbol: signal.symbol, quote: { price: signal.price } });
        }}
      />

      {/* Trading Bot Panel */}
      <TradingBotPanel 
        onTickerSelect={(ticker) => setSelectedTicker(ticker)}
      />
    </div>
  );
};

export default TradingTab;
