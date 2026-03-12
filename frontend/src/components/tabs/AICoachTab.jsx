import React, { useState, useEffect, useCallback } from 'react';
import AICommandPanel from '../AICommandPanel';
import RightSidebar from '../RightSidebar';
import LearningInsightsWidget from '../LearningInsightsWidget';
import MarketRegimeWidget from '../MarketRegimeWidget';
import NewDashboard from '../NewDashboard';
import BriefMeModal from '../BriefMeModal';
import { useTickerModal } from '../../hooks/useTickerModal';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

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
      const response = await fetch(`${API_URL}/api/market-regime/summary`);
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
      const response = await fetch(`${API_URL}/api/context/session`);
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
    
    // Refresh every 60 seconds
    const interval = setInterval(() => {
      fetchRegimeData();
      fetchSessionData();
    }, 60000);
    
    return () => clearInterval(interval);
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
          onViewHistory={() => console.log('View history')}
          onViewAllAlerts={() => console.log('View all alerts')}
          onNavigateToTab={onNavigateToTab}
        >
          {/* Right column content: AI Assistant + Market Regime */}
          <div className="space-y-4">
            {/* Compact Learning Insights */}
            <LearningInsightsWidget 
              onNavigateToHub={handleNavigateToHub}
            />
            
            {/* Market Regime Widget */}
            <MarketRegimeWidget 
              className="h-full"
              onStateChange={(newState, oldState) => {
                console.log(`Market regime changed: ${oldState} -> ${newState}`);
              }}
            />
            
            {/* AI Chat Panel (Compact) */}
            <div className="bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden h-[400px]">
              <AICommandPanel
                onTickerSelect={handleTickerClick}
                onViewChart={(ticker) => setChartSymbol(ticker)}
                watchlist={watchlist}
                alerts={[...enhancedAlerts, ...alerts]}
                opportunities={opportunities}
                earnings={earnings}
                scanResults={opportunities}
                isConnected={isConnected}
                onRefresh={() => runScanner()}
                account={account}
                marketContext={marketContext}
                positions={positions}
                chartSymbol={chartSymbol}
                setChartSymbol={setChartSymbol}
                wsBotStatus={wsBotStatus}
                wsBotTrades={wsBotTrades}
                wsCoachingNotifications={wsCoachingNotifications}
              />
            </div>
          </div>
        </NewDashboard>
      </div>
    );
  }

  // --- CLASSIC LAYOUT (Original) ---
  return (
    <div className="space-y-3" data-testid="ai-coach-tab-content">
      {/* Top Row: Learning Insights + Market Regime */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Learning Insights Widget - Compact overview */}
        <LearningInsightsWidget 
          onNavigateToHub={handleNavigateToHub}
        />
        
        {/* Market Regime Widget - Current market state */}
        <MarketRegimeWidget 
          className="h-full"
          onStateChange={(newState, oldState) => {
            console.log(`Market regime changed: ${oldState} -> ${newState}`);
          }}
        />
      </div>
      
      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-12 gap-4">
        {/* LEFT - AI Trading Assistant (Bot + AI integrated) - Takes more space */}
        <div className="lg:col-span-9">
          <div className="h-[calc(100vh-180px)] min-h-[800px]">
            <AICommandPanel
              onTickerSelect={handleTickerClick}
              onViewChart={(ticker) => setChartSymbol(ticker)}
              watchlist={watchlist}
              alerts={[...enhancedAlerts, ...alerts]}
              opportunities={opportunities}
              earnings={earnings}
              scanResults={opportunities}
              isConnected={isConnected}
              onRefresh={() => runScanner()}
              account={account}
              marketContext={marketContext}
              positions={positions}
              chartSymbol={chartSymbol}
              setChartSymbol={setChartSymbol}
              // WebSocket-pushed data
              wsBotStatus={wsBotStatus}
              wsBotTrades={wsBotTrades}
              wsCoachingNotifications={wsCoachingNotifications}
            />
          </div>
        </div>

        {/* RIGHT - Market Intel + Scanner - Slimmer sidebar */}
        <div className="lg:col-span-3">
          <RightSidebar 
            onTickerSelect={handleTickerClick}
            onViewChart={(ticker) => setChartSymbol(ticker)}
            // WebSocket-pushed data
            wsScannerAlerts={wsScannerAlerts}
            wsScannerStatus={wsScannerStatus}
            wsSmartWatchlist={wsSmartWatchlist}
          />
        </div>
      </div>
    </div>
  );
};

export default AICoachTab;
