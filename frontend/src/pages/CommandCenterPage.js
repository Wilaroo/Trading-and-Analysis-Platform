import React, { useState, useEffect } from 'react';
import { safePolling } from '../utils/safePolling';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import MorningBriefingModal from '../components/MorningBriefingModal';
import HeaderBar from '../components/layout/HeaderBar';
import AICoachTab from '../components/tabs/AICoachTab';
import ChartsTab from '../components/tabs/ChartsTab';
import { useCommandCenterData } from '../hooks/useCommandCenterData';
import api, { safeGet, safePost } from '../utils/api';

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
  wsCoachingNotifications = [],
  wsMarketRegime = null,
}) => {
  const data = useCommandCenterData({
    ibConnected, ibConnectionChecked, connectToIb, checkIbConnection, isActiveTab,
  });

  // Check Ollama status
  const [ollamaStatus, setOllamaStatus] = useState('unknown');
  const [ollamaUsage, setOllamaUsage] = useState(null);
  // Morning briefing modal — state kept so the floating button can still open
  // it on demand, but we no longer auto-popup on first load of the day.
  // Rationale (2026-04-22): the popup was stealing the screen every session,
  // pre-empting the new V5 Command Center briefings panel that now surfaces
  // the same info inline. The modal still exists as a deep-dive surface.
  const [showBriefing, setShowBriefing] = useState(false);
  
  useEffect(() => {
    const checkOllama = async () => {
      try {
        const data = await safeGet('/api/assistant/check-ollama');
          setOllamaStatus(data?.available ? 'online' : 'offline');
      } catch (e) {
        setOllamaStatus('offline');
      }
    };
    
    const fetchOllamaUsage = async () => {
      try {
        const data = await safeGet('/api/ollama-usage');
          if (data && Object.keys(data).length) {
            setOllamaUsage(data);
          }
      } catch (e) {
        // Ollama usage fetch failed - non-critical
      }
    };
    
    checkOllama();
    fetchOllamaUsage();
    return safePolling(() => {
      checkOllama();
      fetchOllamaUsage();
    }, 120000, { immediate: false });
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
          wsMarketRegime={wsMarketRegime}
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

      {/* Morning Briefing Modal — auto-shows once per day, re-openable via button */}
      <MorningBriefingModal
        isOpen={showBriefing}
        onClose={() => setShowBriefing(false)}
      />

      {/* Floating Morning Briefing button */}
      {!showBriefing && (
        <button
          onClick={() => setShowBriefing(true)}
          className="fixed bottom-6 right-6 z-40 p-3 rounded-full shadow-lg border border-amber-500/30 hover:border-amber-400/50 transition-all hover:scale-105"
          style={{ background: 'linear-gradient(135deg, rgba(245,158,11,0.15), rgba(239,68,68,0.15))', backdropFilter: 'blur(8px)' }}
          title="Open Morning Briefing"
          data-testid="open-briefing-btn"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-400"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>
        </button>
      )}
    </div>
  );
};

export default CommandCenterPage;
