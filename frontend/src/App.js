import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Volume2, VolumeX, Settings } from 'lucide-react';
import { Toaster } from 'sonner';

// Import refactored components
import { Sidebar, TickerTape, PriceAlertNotification, AlertSettingsPanel } from './components';
import { useWebSocket, usePriceAlerts } from './hooks';
import api from './utils/api';

// Import pages
import {
  ChartsPage,
  TradeJournalPage,
  IBTradingPage,
} from './pages';
import CommandCenterPage from './pages/CommandCenterPage';
import GlossaryPage from './pages/GlossaryPage';

import './App.css';

// Error Boundary to catch TradingView widget errors
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.log('Caught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || <div className="p-4 text-zinc-500">Widget loading error</div>;
    }
    return this.props.children;
  }
}

// Suppress third-party script errors in development
if (typeof window !== 'undefined') {
  // Hide the webpack dev server error overlay
  const hideErrorOverlay = () => {
    const overlay = document.getElementById('webpack-dev-server-client-overlay');
    if (overlay) {
      overlay.style.display = 'none';
    }
    // Also hide any iframe overlays
    document.querySelectorAll('iframe').forEach(iframe => {
      if (iframe.id?.includes('overlay') || iframe.src?.includes('overlay')) {
        iframe.style.display = 'none';
      }
    });
  };
  
  // Run periodically to catch any newly created overlays
  setInterval(hideErrorOverlay, 500);
  
  window.addEventListener('error', (event) => {
    if (event.message === 'Script error.' || 
        event.filename?.includes('tradingview') ||
        event.filename?.includes('widget') ||
        event.message?.includes('Script error')) {
      event.preventDefault();
      event.stopPropagation();
      hideErrorOverlay();
      return false;
    }
  });
  
  // Also catch unhandled promise rejections
  window.addEventListener('unhandledrejection', (event) => {
    if (event.reason?.message?.includes('Script error') ||
        event.reason?.stack?.includes('tradingview')) {
      event.preventDefault();
      hideErrorOverlay();
    }
  });
}

// ===================== MAIN APP =====================
function App() {
  // Persist activeTab in localStorage so it survives page refresh
  const [activeTab, setActiveTab] = useState(() => {
    const saved = localStorage.getItem('tradecommand_activeTab');
    return saved || 'command-center';
  });
  const [dashboardData, setDashboardData] = useState({ stats: {}, overview: {}, alerts: [], watchlist: [] });
  const [loading, setLoading] = useState(true);
  const [streamingQuotes, setStreamingQuotes] = useState({});
  const [showAlertSettings, setShowAlertSettings] = useState(false);
  
  // Global IB Connection State - shared across all pages
  const [ibConnected, setIbConnected] = useState(false);
  const [ibConnectionChecked, setIbConnectionChecked] = useState(false);

  // ============= WebSocket-pushed state (replaces polling) =============
  const [wsBotStatus, setWsBotStatus] = useState(null);
  const [wsBotTrades, setWsBotTrades] = useState([]);
  const [wsScannerAlerts, setWsScannerAlerts] = useState([]);
  const [wsScannerStatus, setWsScannerStatus] = useState(null);
  const [wsSmartWatchlist, setWsSmartWatchlist] = useState([]);
  const [wsCoachingNotifications, setWsCoachingNotifications] = useState([]);

  // Save activeTab to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('tradecommand_activeTab', activeTab);
  }, [activeTab]);
  
  // Check IB connection status on app load and periodically
  // Global IB busy state
  const [ibBusy, setIbBusy] = useState(false);
  const [ibBusyOperation, setIbBusyOperation] = useState(null);

  const checkIbConnection = useCallback(async () => {
    try {
      const res = await api.get('/api/ib/status');
      const connected = res.data?.connected || false;
      const busy = res.data?.is_busy || false;
      const busyOp = res.data?.busy_operation || null;
      
      console.log('[IB Check] API returned:', { connected, busy, busyOp });
      
      setIbConnected(connected);
      setIbConnectionChecked(true);
      setIbBusy(busy);
      setIbBusyOperation(busyOp);
      
      return connected;
    } catch (err) {
      console.error('IB status check failed:', err);
      setIbConnected(false);
      setIbConnectionChecked(true);
      setIbBusy(false);
      return false;
    }
  }, []);
  
  // Connect to IB - called from any page
  const connectToIb = useCallback(async () => {
    try {
      await api.post('/api/ib/connect');
      const connected = await checkIbConnection();
      return connected;
    } catch (err) {
      console.error('IB connect failed:', err);
      return false;
    }
  }, [checkIbConnection]);
  
  // Check connection on app load
  useEffect(() => {
    checkIbConnection();
  }, [checkIbConnection]);
  
  // Periodic connection check as FALLBACK only (60 seconds)
  // Primary IB status comes via WebSocket now
  useEffect(() => {
    const interval = setInterval(async () => {
      // Only poll if not getting WebSocket updates
      const connected = await checkIbConnection();
      if (!connected && ibConnectionChecked) {
        console.log('IB connection check (fallback): disconnected');
      }
    }, 60000);  // Reduced to 60s - WebSocket handles real-time updates
    return () => clearInterval(interval);
  }, [checkIbConnection, ibConnectionChecked]);

  // WebSocket handler for real-time updates (quotes + system status)
  const handleWebSocketMessage = useCallback((message) => {
    // Quote updates
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
    
    // IB Connection status (replaces polling)
    else if (message.type === 'ib_status') {
      const { connected, busy } = message.data;
      setIbConnected(connected);
      setIbConnectionChecked(true);
      setIbBusy(busy);
    }
    
    // Trading bot status (replaces polling)
    else if (message.type === 'bot_status') {
      setWsBotStatus(message.data);
    }
    
    // Trading bot trades (replaces polling)
    else if (message.type === 'bot_trades') {
      setWsBotTrades(message.data);
    }
    
    // Scanner status (replaces polling)
    else if (message.type === 'scanner_status') {
      setWsScannerStatus(message.data);
    }
    
    // Scanner alerts (replaces polling)
    else if (message.type === 'scanner_alerts') {
      setWsScannerAlerts(message.data);
    }
    
    // Smart watchlist (replaces polling)
    else if (message.type === 'smart_watchlist') {
      setWsSmartWatchlist(message.data);
    }
    
    // AI Coaching notifications (replaces polling)
    else if (message.type === 'coaching_notifications') {
      setWsCoachingNotifications(prev => {
        // Merge new notifications, avoiding duplicates
        const existingIds = new Set(prev.map(n => n.id));
        const newNotifications = message.data.filter(n => !existingIds.has(n.id));
        return [...newNotifications, ...prev].slice(0, 50); // Keep last 50
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
    // IB connection props to pass to pages that need it
    const ibProps = {
      ibConnected,
      ibConnectionChecked,
      connectToIb,
      checkIbConnection,
      ibBusy,
      ibBusyOperation,
      // WebSocket status for quotes streaming
      wsConnected: isConnected,
      wsLastUpdate: lastUpdate,
      // WebSocket-pushed data (replaces polling in child components)
      wsBotStatus,
      wsBotTrades,
      wsScannerAlerts,
      wsScannerStatus,
      wsSmartWatchlist,
      wsCoachingNotifications,
    };
    
    switch (activeTab) {
      case 'command-center': return <CommandCenterPage {...ibProps} isActiveTab={true} />;
      case 'chart': return <ErrorBoundary><ChartsPage {...ibProps} /></ErrorBoundary>;
      case 'trade-journal': return <TradeJournalPage />;
      case 'ib-trading': return <IBTradingPage {...ibProps} />;
      case 'glossary': return <GlossaryPage />;
      default: return <CommandCenterPage {...ibProps} isActiveTab={activeTab === 'command-center'} />;
    }
  };

  return (
    <div className="min-h-screen bg-[#030308] bg-gradient-mesh" onClick={initializeAudio}>
      {/* Toast notifications */}
      <Toaster 
        position="top-right" 
        richColors 
        theme="dark"
        toastOptions={{
          style: { background: '#18181b', border: '1px solid rgba(255,255,255,0.1)' }
        }}
      />
      
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
        <div className="fixed bottom-4 right-28 z-50 glass-panel px-3 py-2 text-xs text-zinc-400 font-mono">
          Alert: ±{alertThreshold}%
        </div>
      )}
      
      <main className="ml-16 min-h-screen bg-[#030305]">
        {/* Ticker Tape with glass effect */}
        <div className="glass-surface border-b border-white/5">
          <TickerTape indices={dashboardData.overview?.indices} isConnected={isConnected} lastUpdate={lastUpdate} />
        </div>
        
        {/* Main Content Area */}
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
