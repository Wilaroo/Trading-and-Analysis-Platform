import React from 'react';
import TradeSignals from '../TradeSignals';
import { useTickerModal } from '../../hooks/useTickerModal';

const TradingTab = ({
  liveAlertsExpanded,
  setLiveAlertsExpanded,
  setSelectedTicker,
}) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="space-y-4 mt-2" data-testid="trading-tab-content">
      {/* Trade Signals - Unified signal feed */}
      <TradeSignals
        isExpanded={liveAlertsExpanded}
        onToggleExpand={() => setLiveAlertsExpanded(!liveAlertsExpanded)}
        onSignalSelect={(signal) => {
          openTickerModal(signal.symbol);
        }}
      />
    </div>
  );
};

export default TradingTab;
