import React, { useState, useEffect } from 'react';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import HeaderBar from '../components/layout/HeaderBar';
import AICoachTab from '../components/tabs/AICoachTab';
import ChartsTab from '../components/tabs/ChartsTab';
import { useCommandCenterData } from '../hooks/useCommandCenterData';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

const CommandCenterPage = ({ 
  ibConnected, 
  ibConnectionChecked, 
  connectToIb, 
  checkIbConnection, 
  isActiveTab = true,
  wsConnected = false,
  wsLastUpdate = null,
  ibBusy = false,
  ibBusyOperation = null,
  ibPusherStatus = null,
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = [],
  wsCoachingNotifications = []
}) => {
  const data = useCommandCenterData({
    ibConnected, ibConnectionChecked, connectToIb, checkIbConnection, isActiveTab,
  });

  // Check Ollama status
  const [ollamaStatus, setOllamaStatus] = useState('unknown');
  const [ollamaUsage, setOllamaUsage] = useState(null);
  
  useEffect(() => {
    const checkOllama = async () => {
      try {
        const response = await fetch(`${API_URL}/api/assistant/check-ollama`, { 
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
          const data = await response.json();
          setOllamaStatus(data.available ? 'online' : 'offline');
        } else {
          setOllamaStatus('offline');
        }
      } catch (e) {
        setOllamaStatus('offline');
      }
    };
    
    const fetchOllamaUsage = async () => {
      try {
        const response = await fetch(`${API_URL}/api/ollama-usage`, {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
          const data = await response.json();
          setOllamaUsage(data);
        }
      } catch (e) {
        // Ollama usage fetch failed - non-critical
      }
    };
    
    checkOllama();
    fetchOllamaUsage();
    const interval = setInterval(() => {
      checkOllama();
      fetchOllamaUsage();
    }, 30000); // Check every 30s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-3 pb-8" data-testid="command-center-page">
      {/* Header with integrated tabs */}
      <HeaderBar
        systemHealth={data.systemHealth}
        wsConnected={wsConnected}
        wsLastUpdate={wsLastUpdate}
        connectionChecked={data.connectionChecked}
        isConnected={data.isConnected}
        connecting={data.connecting}
        handleConnectToIB={data.handleConnectToIB}
        handleDisconnectFromIB={data.handleDisconnectFromIB}
        creditBudget={data.creditBudget}
        ollamaStatus={ollamaStatus}
        ollamaUsage={ollamaUsage}
        ibPusherStatus={ibPusherStatus}
        activeTab={data.activeMainTab}
        setActiveTab={data.setActiveMainTab}
      />

      {/* Tab Content */}
      {data.activeMainTab === 'coach' && (
        <AICoachTab
          setSelectedTicker={data.setSelectedTicker}
          watchlist={data.watchlist}
          enhancedAlerts={data.enhancedAlerts}
          alerts={data.alerts}
          opportunities={data.opportunities}
          earnings={data.earnings}
          isConnected={data.isConnected}
          runScanner={data.runScanner}
          account={data.account}
          marketContext={data.marketContext}
          positions={data.positions}
          viewChart={data.viewChart}
          chartSymbol={data.chartSymbol}
          setChartSymbol={data.setChartSymbol}
          // WebSocket-pushed data
          wsBotStatus={wsBotStatus}
          wsBotTrades={wsBotTrades}
          wsScannerAlerts={wsScannerAlerts}
          wsScannerStatus={wsScannerStatus}
          wsSmartWatchlist={wsSmartWatchlist}
          wsCoachingNotifications={wsCoachingNotifications}
        />
      )}

      {data.activeMainTab === 'charts' && (
        <ChartsTab
          isConnected={data.isConnected}
          isBusy={ibBusy}
          busyOperation={ibBusyOperation}
          chartSymbol={data.chartSymbol}
          setChartSymbol={data.setChartSymbol}
          watchlist={data.watchlist}
          recentCharts={data.recentCharts}
          onAddToRecent={data.addToRecentCharts}
        />
      )}

      {/* Ticker Detail Modal */}
      {data.selectedTicker && (
        <TickerDetailModal
          ticker={data.selectedTicker}
          onClose={() => data.setSelectedTicker(null)}
          onTrade={data.handleTrade}
          onAskAI={data.askAIAboutStock}
        />
      )}

      {/* Quick Trade Modal */}
      {data.tradeModal.isOpen && (
        <QuickTradeModal
          ticker={data.tradeModal.ticker}
          action={data.tradeModal.action}
          onClose={() => data.setTradeModal({ isOpen: false, ticker: null, action: null })}
          onSuccess={() => {
            data.fetchAccountData();
            data.setTradeModal({ isOpen: false, ticker: null, action: null });
          }}
        />
      )}
    </div>
  );
};

export default CommandCenterPage;
