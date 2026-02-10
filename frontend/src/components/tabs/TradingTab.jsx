import React from 'react';
import TradeSignals from '../TradeSignals';

const TradingTab = ({
  liveAlertsExpanded,
  setLiveAlertsExpanded,
  setSelectedTicker,
}) => {
  return (
    <div className="space-y-4 mt-2" data-testid="trading-tab-content">
      {/* Trade Signals - Unified signal feed */}
      <TradeSignals
        isExpanded={liveAlertsExpanded}
        onToggleExpand={() => setLiveAlertsExpanded(!liveAlertsExpanded)}
        onSignalSelect={(signal) => {
          setSelectedTicker({ symbol: signal.symbol, quote: { price: signal.price } });
        }}
      />
    </div>
  );
};

export default TradingTab;
