import React from 'react';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
} from 'lucide-react';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import HeaderBar from '../components/layout/HeaderBar';
import QuickStatsRow from '../components/layout/QuickStatsRow';
import TradingTab from '../components/tabs/TradingTab';
import AICoachTab from '../components/tabs/AICoachTab';
import AnalyticsTab from '../components/tabs/AnalyticsTab';
import { useCommandCenterData } from '../hooks/useCommandCenterData';

const scanTypes = [
  { id: 'TOP_PERC_GAIN', label: 'Top Gainers', icon: TrendingUp },
  { id: 'TOP_PERC_LOSE', label: 'Top Losers', icon: TrendingDown },
  { id: 'MOST_ACTIVE', label: 'Most Active', icon: Activity },
  { id: 'HIGH_OPEN_GAP', label: 'Gap Up', icon: ArrowUpRight },
  { id: 'LOW_OPEN_GAP', label: 'Gap Down', icon: ArrowDownRight },
];

const CommandCenterPage = ({ 
  ibConnected, 
  ibConnectionChecked, 
  connectToIb, 
  checkIbConnection, 
  isActiveTab = true,
  wsConnected = false,
  wsLastUpdate = null
}) => {
  const data = useCommandCenterData({
    ibConnected, ibConnectionChecked, connectToIb, checkIbConnection, isActiveTab,
  });

  return (
    <div className="space-y-4 pb-8" data-testid="command-center-page">
      {/* Header */}
      <HeaderBar
        systemHealth={data.systemHealth}
        onNavigateToCoach={() => data.setActiveMainTab('coach')}
        wsConnected={wsConnected}
        wsLastUpdate={wsLastUpdate}
        connectionChecked={data.connectionChecked}
        isConnected={data.isConnected}
        connecting={data.connecting}
        handleConnectToIB={data.handleConnectToIB}
        handleDisconnectFromIB={data.handleDisconnectFromIB}
      />

      {/* Quick Stats Row */}
      <QuickStatsRow
        account={data.account}
        totalPnL={data.totalPnL}
        positions={data.positions}
        enhancedAlerts={data.enhancedAlerts}
        alerts={data.alerts}
        marketContext={data.marketContext}
        opportunities={data.opportunities}
        expandedStatCard={data.expandedStatCard}
        setExpandedStatCard={data.setExpandedStatCard}
        setSelectedTicker={data.setSelectedTicker}
        setSelectedEnhancedAlert={data.setSelectedEnhancedAlert}
      />

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 bg-[#0A0A0A] border border-white/10 rounded-lg p-1 mt-1" data-testid="main-tabs">
        {[
          { id: 'trading', label: 'Signals', icon: '\u26A1' },
          { id: 'coach', label: 'Command', icon: '\uD83C\uDFAF' },
          { id: 'analytics', label: 'Analytics', icon: '\uD83D\uDCCA' }
        ].map(tab => (
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
            <span className="text-base">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {data.activeMainTab === 'trading' && (
        <TradingTab
          liveAlertsExpanded={data.liveAlertsExpanded}
          setLiveAlertsExpanded={data.setLiveAlertsExpanded}
          setSelectedTicker={data.setSelectedTicker}
        />
      )}

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
        />
      )}

      {data.activeMainTab === 'analytics' && (
        <AnalyticsTab
          isConnected={data.isConnected}
          isScanning={data.isScanning}
          runScanner={data.runScanner}
          selectedScanType={data.selectedScanType}
          setSelectedScanType={data.setSelectedScanType}
          scanTypes={scanTypes}
          opportunities={data.opportunities}
          setSelectedTicker={data.setSelectedTicker}
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
