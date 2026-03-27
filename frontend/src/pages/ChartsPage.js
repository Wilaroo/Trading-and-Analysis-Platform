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
  // Local state for chart symbol - persist with localStorage
  const [chartSymbol, setChartSymbol] = React.useState(() => {
    try {
      return localStorage.getItem('tradecommand_chart_symbol') || 'SPY';
    } catch { return 'SPY'; }
  });
  const [recentCharts, setRecentCharts] = React.useState(() => {
    try {
      const saved = localStorage.getItem('recentChartSymbols');
      return saved ? JSON.parse(saved) : ['SPY', 'QQQ', 'AAPL'];
    } catch {
      return ['SPY', 'QQQ', 'AAPL'];
    }
  });

  const addToRecentCharts = (symbol) => {
    setRecentCharts(prev => {
      const updated = [symbol, ...prev.filter(s => s !== symbol)].slice(0, 10);
      localStorage.setItem('recentChartSymbols', JSON.stringify(updated));
      return updated;
    });
  };

  const handleSetChartSymbol = (sym) => {
    setChartSymbol(sym);
    localStorage.setItem('tradecommand_chart_symbol', sym);
  };

  return (
    <div className="p-4" data-testid="charts-page">
      <ChartsTab
        isConnected={ibConnected}
        isBusy={ibBusy}
        busyOperation={ibBusyOperation}
        chartSymbol={chartSymbol}
        setChartSymbol={handleSetChartSymbol}
        watchlist={[]}
        recentCharts={recentCharts}
        onAddToRecent={addToRecentCharts}
      />
    </div>
  );
};

export default ChartsPage;
