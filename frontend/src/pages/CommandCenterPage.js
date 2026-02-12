import React from 'react';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import HeaderBar from '../components/layout/HeaderBar';
import AICoachTab from '../components/tabs/AICoachTab';
import AnalyticsTab from '../components/tabs/AnalyticsTab';
import ChartsTab from '../components/tabs/ChartsTab';
import { useCommandCenterData } from '../hooks/useCommandCenterData';
import { LineChart, Target, BarChart3 } from 'lucide-react';

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

  const tabs = [
    { id: 'coach', label: 'Command', icon: Target },
    { id: 'charts', label: 'Charts', icon: LineChart },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 }
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
      />

      {/* Tab Navigation — 3 tabs */}
      <div className="flex items-center gap-1 bg-[#0A0A0A] border border-white/10 rounded-lg p-1 mt-1" data-testid="main-tabs">
        {tabs.map(tab => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => data.setActiveMainTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all ${
                data.activeMainTab === tab.id
                  ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
              }`}
              data-testid={`tab-${tab.id}`}
            >
              <Icon className="w-4 h-4" />
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

      {data.activeMainTab === 'analytics' && (
        <AnalyticsTab />
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
