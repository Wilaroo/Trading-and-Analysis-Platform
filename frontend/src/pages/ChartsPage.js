import React from 'react';
import ChartsTab from '../components/tabs/ChartsTab';

/**
 * ChartsPage - Standalone page wrapper for the ChartsTab component
 * Used when charts are accessed from the main navigation
 */
const ChartsPage = ({ 
  ibConnected, 
  ibConnectionChecked, 
  connectToIb, 
  checkIbConnection, 
  ibBusy = false,
  ibBusyOperation = null,
  wsConnected = false,
  wsLastUpdate = null,
}) => {
  // Local state for chart symbol
  const [chartSymbol, setChartSymbol] = React.useState('SPY');
  const [recentCharts, setRecentCharts] = React.useState(() => {
    try {
      const saved = localStorage.getItem('tradecommand_recentCharts');
      return saved ? JSON.parse(saved) : ['SPY', 'QQQ', 'AAPL'];
    } catch {
      return ['SPY', 'QQQ', 'AAPL'];
    }
  });

  const addToRecentCharts = (symbol) => {
    setRecentCharts(prev => {
      const updated = [symbol, ...prev.filter(s => s !== symbol)].slice(0, 10);
      localStorage.setItem('tradecommand_recentCharts', JSON.stringify(updated));
      return updated;
    });
  };

  return (
    <div className="p-4" data-testid="charts-page">
      <ChartsTab
        isConnected={ibConnected}
        isBusy={ibBusy}
        busyOperation={ibBusyOperation}
        chartSymbol={chartSymbol}
        setChartSymbol={setChartSymbol}
        watchlist={[]}
        recentCharts={recentCharts}
        onAddToRecent={addToRecentCharts}
      />
    </div>
  );
};

export default ChartsPage;
