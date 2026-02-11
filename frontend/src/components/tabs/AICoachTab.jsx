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
}) => {
  return (
    <div className="grid lg:grid-cols-12 gap-4 mt-2" data-testid="ai-coach-tab-content">
      {/* LEFT - AI Trading Assistant (Bot + AI integrated) - Takes more space */}
      <div className="lg:col-span-8">
        <div className="h-[calc(100vh-280px)] min-h-[600px]">
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

      {/* RIGHT - Market Intel + Scanner */}
      <div className="lg:col-span-4">
        <RightSidebar onTickerSelect={(ticker) => setSelectedTicker(ticker)} />
      </div>
    </div>
  );
};

export default AICoachTab;
