import React, { useState, useEffect } from 'react';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import HeaderBar from '../components/layout/HeaderBar';
import AICoachTab from '../components/tabs/AICoachTab';
import ChartsTab from '../components/tabs/ChartsTab';
import { useCommandCenterData } from '../hooks/useCommandCenterData';
import { LineChart, Target } from 'lucide-react';

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

  const tabs = [
    { id: 'coach', label: 'Command', icon: Target },
    { id: 'charts', label: 'Charts', icon: LineChart }
  ];

  return (
    <div className="space-y-3 pb-8" data-testid="command-center-page">
      {/* Header */}
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
      />

      {/* Tab Navigation — Glass Style */}
      <div className="flex items-center gap-1 glass-panel p-1.5 mt-1" data-testid="main-tabs">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const isActive = data.activeMainTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => data.setActiveMainTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-cyan-400/10 text-cyan-400 border border-cyan-400/30 shadow-[0_0_15px_rgba(0,229,255,0.15)]'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/5 border border-transparent'
              }`}
              data-testid={`tab-${tab.id}`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'drop-shadow-[0_0_6px_rgba(0,229,255,0.5)]' : ''}`} />
              {tab.label}
            </button>
          );
        })}
      </div>

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
