import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Volume2, VolumeX, Settings } from 'lucide-react';

// Import refactored components
import { Sidebar, TickerTape, PriceAlertNotification, AlertSettingsPanel } from './components';
import { useWebSocket, usePriceAlerts } from './hooks';
import api from './utils/api';

// Import pages
import {
  DashboardPage,
  ChartsPage,
  ScannerPage,
  StrategiesPage,
  WatchlistPage,
  PortfolioPage,
  FundamentalsPage,
  InsiderTradingPage,
  COTDataPage,
  AlertsPage,
  NewsletterPage
} from './pages';

import './App.css';

// ===================== MAIN APP =====================
function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [dashboardData, setDashboardData] = useState({ stats: {}, overview: {}, alerts: [], watchlist: [] });
  const [loading, setLoading] = useState(true);
  const [streamingQuotes, setStreamingQuotes] = useState({});
  const [showAlertSettings, setShowAlertSettings] = useState(false);

  // WebSocket handler for real-time updates
  const handleWebSocketMessage = useCallback((message) => {
    if (message.type === 'quotes' || message.type === 'initial') {
      const quotesMap = {};
      message.data.forEach(quote => {
        quotesMap[quote.symbol] = quote;
      });
      setStreamingQuotes(prev => ({ ...prev, ...quotesMap }));
      
      // Update indices in dashboard data
      setDashboardData(prev => {
        const updatedIndices = prev.overview?.indices?.map(idx => {
          const updated = quotesMap[idx.symbol];
          return updated ? { ...idx, ...updated } : idx;
        }) || [];
        
        const updatedMovers = prev.overview?.top_movers?.map(mover => {
          const updated = quotesMap[mover.symbol];
          return updated ? { ...mover, ...updated } : mover;
        }) || [];
        
        return {
          ...prev,
          overview: {
            ...prev.overview,
            indices: updatedIndices,
            top_movers: updatedMovers
          }
        };
      });
    }
  }, []);

  const { isConnected, lastUpdate } = useWebSocket(handleWebSocketMessage);
  
  // Price Alerts Integration
  const {
    alerts: priceAlerts,
    audioEnabled,
    setAudioEnabled,
    alertThreshold,
    setAlertThreshold,
    initializeAudio,
    dismissAlert
  } = usePriceAlerts(streamingQuotes, dashboardData.watchlist);

  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, overviewRes, alertsRes, watchlistRes] = await Promise.all([
        api.get('/api/dashboard/stats'),
        api.get('/api/market/overview'),
        api.get('/api/alerts', { params: { unread_only: true } }),
        api.get('/api/watchlist')
      ]);
      setDashboardData({
        stats: statsRes.data,
        overview: overviewRes.data,
        alerts: alertsRes.data.alerts,
        watchlist: watchlistRes.data.watchlist
      });
    } catch (err) { console.error('Failed to load dashboard:', err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadDashboardData(); }, [loadDashboardData]);
  
  // Initialize audio on first user interaction
  useEffect(() => {
    const handleFirstInteraction = () => {
      initializeAudio();
      document.removeEventListener('click', handleFirstInteraction);
    };
    document.addEventListener('click', handleFirstInteraction);
    return () => document.removeEventListener('click', handleFirstInteraction);
  }, [initializeAudio]);

  const renderPage = () => {
    switch (activeTab) {
      case 'dashboard': return <DashboardPage data={dashboardData} loading={loading} onRefresh={loadDashboardData} streamingQuotes={streamingQuotes} />;
      case 'chart': return <ChartsPage />;
      case 'scanner': return <ScannerPage />;
      case 'strategies': return <StrategiesPage />;
      case 'watchlist': return <WatchlistPage />;
      case 'portfolio': return <PortfolioPage />;
      case 'fundamentals': return <FundamentalsPage />;
      case 'insider': return <InsiderTradingPage />;
      case 'cot': return <COTDataPage />;
      case 'alerts': return <AlertsPage />;
      case 'newsletter': return <NewsletterPage />;
      default: return <DashboardPage data={dashboardData} loading={loading} onRefresh={loadDashboardData} streamingQuotes={streamingQuotes} />;
    }
  };

  return (
    <div className="min-h-screen bg-background bg-gradient-radial" onClick={initializeAudio}>
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      
      {/* Price Alert Notifications */}
      <PriceAlertNotification 
        alerts={priceAlerts} 
        onDismiss={dismissAlert}
        audioEnabled={audioEnabled}
        setAudioEnabled={setAudioEnabled}
      />
      
      {/* Alert Settings Panel */}
      <AnimatePresence>
        {showAlertSettings && (
          <AlertSettingsPanel
            audioEnabled={audioEnabled}
            setAudioEnabled={setAudioEnabled}
            alertThreshold={alertThreshold}
            setAlertThreshold={setAlertThreshold}
            isOpen={showAlertSettings}
            onClose={() => setShowAlertSettings(false)}
          />
        )}
      </AnimatePresence>
      
      {/* Audio Control Button */}
      <div className="fixed bottom-4 right-4 z-50 flex items-center gap-2">
        <button
          onClick={() => setShowAlertSettings(!showAlertSettings)}
          data-testid="alert-settings-btn"
          className="p-2 rounded-full bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-700 transition-all"
          title="Alert Settings"
        >
          <Settings className="w-4 h-4" />
        </button>
        <button
          onClick={() => setAudioEnabled(!audioEnabled)}
          data-testid="toggle-audio-alerts"
          className={`p-3 rounded-full transition-all ${
            audioEnabled 
              ? 'bg-primary/20 text-primary border border-primary/30' 
              : 'bg-zinc-800 text-zinc-500 border border-zinc-700'
          }`}
          title={audioEnabled ? 'Disable audio alerts' : 'Enable audio alerts'}
        >
          {audioEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
        </button>
      </div>
      
      {/* Alert Threshold Indicator */}
      {audioEnabled && (
        <div className="fixed bottom-4 right-28 z-50 bg-paper border border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-400">
          Alert: ±{alertThreshold}%
        </div>
      )}
      
      <main className="ml-16 lg:ml-64 min-h-screen">
        <TickerTape indices={dashboardData.overview?.indices} isConnected={isConnected} lastUpdate={lastUpdate} />
        <div className="p-6">
          <AnimatePresence mode="wait">
            <motion.div key={activeTab} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }}>
              {renderPage()}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

export default App;
