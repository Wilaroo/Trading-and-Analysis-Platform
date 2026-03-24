import React, { useState, useEffect, useCallback } from 'react';
import { safePolling } from '../../utils/safePolling';
import RightSidebar from '../RightSidebar';
import LearningInsightsWidget from '../LearningInsightsWidget';
import MarketRegimeWidget from '../MarketRegimeWidget';
import NewDashboard from '../NewDashboard';
import BriefMeModal from '../BriefMeModal';
import SentCom from '../SentCom';
import JobManager from '../JobManager';
import { useTickerModal } from '../../hooks/useTickerModal';
import api, { safeGet, safePost } from '../../utils/api';

const AICoachTab = ({
  setSelectedTicker,
  watchlist,
  enhancedAlerts,
  alerts,
  opportunities,
  earnings,
  isConnected,
  runScanner,
  account,
  marketContext,
  positions,
  viewChart,
  chartSymbol,
  setChartSymbol,
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = [],
  wsCoachingNotifications = [],
  // Navigation callback
  onNavigateToTab = null,
  // Layout mode: 'new' for NewDashboard, 'classic' for original
  layoutMode = 'new'
}) => {
  // Use the global ticker modal hook
  const { openTickerModal } = useTickerModal();
  
  // State for regime data (fetch from API)
  const [regime, setRegime] = useState(null);
  const [marketSession, setMarketSession] = useState(null);
  
  // State for Brief Me modal
  const [isBriefMeOpen, setIsBriefMeOpen] = useState(false);
  
  // Fetch regime data
  const fetchRegimeData = useCallback(async () => {
    try {
      const response = await safeGet('/api/market-regime/summary');
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setRegime({
            name: data.state || 'HOLD',
            score: data.composite_score || 50
          });
        }
      }
    } catch (err) {
      console.error('Failed to fetch regime:', err);
    }
  }, []);
  
  // Fetch session data
  const fetchSessionData = useCallback(async () => {
    try {
      const response = await safeGet('/api/context/session');
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setMarketSession(data.session?.name || 'MARKET CLOSED');
        }
      }
    } catch (err) {
      console.error('Failed to fetch session:', err);
    }
  }, []);
  
  // Initial fetch
  useEffect(() => {
    fetchRegimeData();
    fetchSessionData();
    
    return safePolling(() => {
      fetchRegimeData();
      fetchSessionData();
    }, 60000, { immediate: false });
  }, [fetchRegimeData, fetchSessionData]);
  
  // Handle ticker click - opens the enhanced chart modal
  // Can receive either a string ticker or an object { symbol, quote, ... }
  const handleTickerClick = (tickerOrObject) => {
    const symbol = typeof tickerOrObject === 'string' 
      ? tickerOrObject 
      : tickerOrObject?.symbol;
    
    if (symbol) {
      setChartSymbol(symbol); // Update chart in background
      openTickerModal(symbol); // Open the new enhanced modal
    }
  };

  // Navigate to Analytics tab with Intelligence Hub
  const handleNavigateToHub = () => {
    if (onNavigateToTab) {
      onNavigateToTab('analytics');
    }
  };
  
  // Handle "Brief Me" button click
  const handleBriefMe = () => {
    setIsBriefMeOpen(true);
  };

  // --- NEW DASHBOARD LAYOUT ---
  if (layoutMode === 'new') {
    return (
      <div className="space-y-3" data-testid="ai-coach-tab-content">
        {/* Brief Me Modal */}
        <BriefMeModal 
          isOpen={isBriefMeOpen} 
          onClose={() => setIsBriefMeOpen(false)} 
        />
        
        <NewDashboard
          botStatus={wsBotStatus}
          botTrades={wsBotTrades}
          watchingSetups={wsBotTrades.filter(t => t.status === 'pending')}
          scannerAlerts={wsScannerAlerts}
          marketSession={marketSession}
          regime={regime}
          todayPnl={account?.daily_pnl || 0}
          openPnl={account?.unrealized_pnl || 0}
          onBriefMe={handleBriefMe}
          onViewAnalytics={() => onNavigateToTab?.('analytics')}
          onViewHistory={() => {}}
          onViewAllAlerts={() => {}}
          onNavigateToTab={onNavigateToTab}
        >
          {/* Right column content: Learning Insights + Market Regime */}
          {/* Note: AI Chat is now integrated into SentCom on the left */}
          <div className="space-y-4">
            {/* Compact Learning Insights */}
            <LearningInsightsWidget 
              onNavigateToHub={handleNavigateToHub}
            />
            
            {/* Background Jobs - Data Collection & Backtesting */}
            <JobManager compact={true} />
            
            {/* Market Regime Widget */}
            <MarketRegimeWidget 
              className="h-full"
              onStateChange={(newState, oldState) => {
                // Market regime changed - handled internally
              }}
            />
          </div>
        </NewDashboard>
      </div>
    );
  }

  // --- CLASSIC LAYOUT (Original) ---
  return (
    <div className="space-y-3" data-testid="ai-coach-tab-content">
      
      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-12 gap-4">
        {/* LEFT - SentCom (Unified AI Command Center) - Takes more space */}
        <div className="lg:col-span-8">
          <div className="h-[calc(100vh-180px)] min-h-[800px]">
            <SentCom embedded={true} />
          </div>
        </div>

        {/* RIGHT - Market Intel: Regime + Setups + Scanner Alerts */}
        <div className="lg:col-span-4 space-y-3">
          {/* Market Regime Widget - Current market state */}
          <MarketRegimeWidget 
            className="h-full"
            onStateChange={(newState, oldState) => {
              // Market regime changed - handled internally
            }}
          />
          
          {/* Learning Insights Widget */}
          <LearningInsightsWidget 
            onNavigateToHub={handleNavigateToHub}
          />
          
          {/* Background Jobs - Data Collection & Backtesting */}
          <JobManager compact={true} />
          
          {/* Scanner & Watchlist - Compact mode (skip redundant MarketIntel) */}
          <RightSidebar 
            onTickerSelect={handleTickerClick}
            onViewChart={(ticker) => setChartSymbol(ticker)}
            // WebSocket-pushed data
            wsScannerAlerts={wsScannerAlerts}
            wsScannerStatus={wsScannerStatus}
            wsSmartWatchlist={wsSmartWatchlist}
            compact={true}
          />
        </div>
      </div>
    </div>
  );
};

export default AICoachTab;
