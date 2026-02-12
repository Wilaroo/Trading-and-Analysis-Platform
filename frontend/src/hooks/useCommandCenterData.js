import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import api, { apiLongRunning } from '../utils/api';
import { toast } from 'sonner';
import { playSound } from '../utils/tradingUtils';
import { useKeyboardShortcuts } from './useKeyboardShortcuts';

export function useCommandCenterData({
  ibConnected,
  ibConnectionChecked,
  connectToIb,
  checkIbConnection,
  isActiveTab = true,
}) {
  const isConnected = ibConnected;
  const connectionChecked = ibConnectionChecked;
  const [connecting, setConnecting] = useState(false);

  // Data State
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [opportunities, setOpportunities] = useState([]);
  const [marketContext, setMarketContext] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [earnings, setEarnings] = useState([]);

  // UI State
  const [isScanning, setIsScanning] = useState(false);
  const [selectedScanType, setSelectedScanType] = useState('TOP_PERC_GAIN');
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [tradeModal, setTradeModal] = useState({ isOpen: false, ticker: null, action: null });
  const [expandedSections, setExpandedSections] = useState({
    holdings: true, opportunities: true, context: true, alerts: true,
    news: true, earnings: true, squeeze: false, priceAlerts: false,
    breakouts: true, enhancedAlerts: true, comprehensiveAlerts: true, systemMonitor: true
  });

  // AI Assistant state
  const [showAssistant, setShowAssistant] = useState(false);
  const [assistantPrompt, setAssistantPrompt] = useState(null);
  const [activeMainTab, setActiveMainTab] = useState('coach');
  const [expandedStatCard, setExpandedStatCard] = useState(null);

  // Charts state
  const [chartSymbol, setChartSymbol] = useState(() => {
    try {
      return localStorage.getItem('tradecommand_chart_symbol') || 'SPY';
    } catch { return 'SPY'; }
  });
  const [recentCharts, setRecentCharts] = useState(() => {
    try {
      const saved = localStorage.getItem('recentChartSymbols');
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });

  // Ticker Search state
  const [tickerSearchQuery, setTickerSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('recentTickerSearches');
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const searchInputRef = useRef(null);

  // Feature state
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [enhancedAlerts, setEnhancedAlerts] = useState([]);
  const [selectedEnhancedAlert, setSelectedEnhancedAlert] = useState(null);
  const [priceAlerts, setPriceAlerts] = useState([]);
  const [trackedOrders, setTrackedOrders] = useState([]);
  const [liveAlertsExpanded, setLiveAlertsExpanded] = useState(true);

  // System health
  const [systemHealth, setSystemHealth] = useState(null);
  const [isGeneratingIntelligence, setIsGeneratingIntelligence] = useState(false);
  
  // Smart watchlist from batch init
  const [smartWatchlist, setSmartWatchlist] = useState([]);
  
  // Credit budget for Tavily
  const [creditBudget, setCreditBudget] = useState(null);

  // Keyboard shortcuts
  useKeyboardShortcuts({
    'ctrl+k': () => {
      if (searchInputRef.current) searchInputRef.current.focus();
    },
    'ctrl+shift+a': () => setShowAssistant(prev => !prev),
    'escape': () => {
      if (selectedTicker) setSelectedTicker(null);
      else if (tradeModal.isOpen) setTradeModal({ isOpen: false, ticker: null, action: null });
      else if (showAssistant) setShowAssistant(false);
    },
    'ctrl+m': () => {
      setSoundEnabled(prev => !prev);
      toast.info(soundEnabled ? 'Sound disabled' : 'Sound enabled');
    },
  }, isActiveTab);

  // ==================== DATA FETCHING ====================

  const handleConnectToIB = async () => {
    setConnecting(true);
    try {
      const connected = await connectToIb();
      if (connected) {
        await fetchAccountData();
        await fetchWatchlist(connected);
      }
    } catch (err) {
      console.error('Connection failed:', err);
    }
    setConnecting(false);
  };

  const handleDisconnectFromIB = async () => {
    setConnecting(true);
    try {
      await api.post('/api/ib/disconnect');
      await checkIbConnection();
      toast.info('Disconnected from IB Gateway');
    } catch (err) {
      console.error('Disconnect failed:', err);
      toast.error('Failed to disconnect');
    }
    setConnecting(false);
  };

  const fetchAccountData = async () => {
    let positionsData = [];
    
    // First try trading-bot positions (Alpaca) - more reliable
    try {
      const botPositionsRes = await api.get('/api/trading-bot/positions');
      if (botPositionsRes.data?.success && botPositionsRes.data?.positions) {
        positionsData = botPositionsRes.data.positions.map(p => ({
          symbol: p.symbol,
          qty: parseFloat(p.qty) || 0,
          quantity: parseFloat(p.qty) || 0,
          avg_entry_price: parseFloat(p.avg_entry_price) || 0,
          avg_cost: parseFloat(p.avg_entry_price) || 0,
          current_price: parseFloat(p.current_price) || 0,
          market_value: (parseFloat(p.qty) || 0) * (parseFloat(p.current_price) || 0),
          unrealized_pnl: parseFloat(p.unrealized_pnl) || 0,
          unrealized_pl: parseFloat(p.unrealized_pnl) || 0,
          unrealized_plpc: (parseFloat(p.unrealized_pnl_pct) || 0) / 100,
          unrealized_pnl_percent: (parseFloat(p.unrealized_pnl_pct) || 0) / 100,
          side: p.side || 'long'
        }));
      }
    } catch (botErr) {
      // Fall back to IB positions
      try {
        const positionsRes = await api.get('/api/ib/account/positions');
        positionsData = positionsRes.data?.positions || [];
      } catch (ibErr) {
        // Both APIs failed - positions will be empty
      }
    }
    
    setPositions(positionsData);
    
    // Try to fetch account summary (non-blocking)
    api.get('/api/ib/account/summary')
      .then(res => setAccount(res.data))
      .catch(() => {});
  };

  const runScanner = async () => {
    if (!isConnected) return;
    setIsScanning(true);
    try {
      const res = await api.post('/api/ib/scanner/enhanced', {
        scan_type: selectedScanType, max_results: 20, calculate_features: true
      });
      const results = res.data?.results || [];
      if (results.length > 0) {
        try {
          const symbols = results.map(r => r.symbol).filter(Boolean);
          const qualityRes = await api.post('/api/quality/enhance-opportunities', {
            opportunities: symbols.map(s => ({ symbol: s }))
          });
          const qualityMap = {};
          (qualityRes.data?.opportunities || []).forEach(opp => {
            if (opp.symbol && opp.quality) qualityMap[opp.symbol] = opp.quality;
          });
          results.forEach(r => {
            if (r.symbol && qualityMap[r.symbol]) {
              r.quality = qualityMap[r.symbol];
              r.qualityGrade = qualityMap[r.symbol].grade;
            }
          });
        } catch (qualityErr) {
          console.log('Quality enhancement failed:', qualityErr.message);
        }
      }
      setOpportunities(results);
    } catch (err) {
      console.error('Scanner error:', err);
    }
    setIsScanning(false);
  };

  const fetchMarketContext = async () => {
    try {
      const symbols = ['SPY', 'QQQ', 'VIX'];
      const res = await api.post('/api/ib/quotes/batch', symbols);
      const quotes = res.data?.quotes || [];
      const spy = quotes.find(q => q.symbol === 'SPY');
      const qqq = quotes.find(q => q.symbol === 'QQQ');
      const vix = quotes.find(q => q.symbol === 'VIX');
      let regime = 'Consolidation';
      if (spy?.change_percent > 0.5 && qqq?.change_percent > 0.5) regime = 'Trending Up';
      else if (spy?.change_percent < -0.5 && qqq?.change_percent < -0.5) regime = 'Trending Down';
      else if (vix?.price > 25) regime = 'High Volatility';
      setMarketContext({ regime, spy: spy?.change_percent || 0, qqq: qqq?.change_percent || 0, vix: vix?.price || 0 });
    } catch (err) {
      console.error('Market context error:', err);
    }
  };

  const fetchAlerts = async () => {
    try {
      const res = await api.get('/api/alerts');
      setAlerts(res.data?.alerts?.slice(0, 5) || []);
    } catch { setAlerts([]); }
  };

  const fetchWatchlist = async (connected) => {
    try {
      const res = await api.get('/api/watchlist');
      const symbols = res.data?.symbols || ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD'];
      if (connected && symbols.length > 0) {
        const quotesRes = await api.post('/api/ib/quotes/batch', symbols.slice(0, 10));
        setWatchlist(quotesRes.data?.quotes || []);
      }
    } catch { setWatchlist([]); }
  };

  const fetchEarnings = async () => {
    try {
      const res = await api.get('/api/earnings/calendar');
      const upcoming = (res.data?.calendar || [])
        .filter(e => {
          const earningsDate = new Date(e.earnings_date);
          const today = new Date(); today.setHours(0, 0, 0, 0);
          const nextMonth = new Date(); nextMonth.setDate(today.getDate() + 30);
          return earningsDate >= today && earningsDate <= nextMonth;
        })
        .sort((a, b) => new Date(a.earnings_date) - new Date(b.earnings_date))
        .slice(0, 12);
      setEarnings(upcoming);
    } catch { setEarnings([]); }
  };

  const fetchEnhancedAlerts = async () => {
    try {
      const res = await api.get('/api/ib/alerts/enhanced');
      const alertsData = res.data?.alerts || [];
      setEnhancedAlerts(alertsData);
      if (soundEnabled) {
        alertsData.filter(a => a.is_new).forEach(alert => {
          playSound('alert');
          toast.success(alert.headline, { duration: 10000 });
        });
      }
    } catch (err) {
      console.log('Enhanced alerts unavailable:', err.response?.data?.detail?.message);
    }
  };

  const fetchSystemHealth = async () => {
    try {
      const res = await api.get('/api/system/monitor');
      setSystemHealth(res.data);
    } catch {
      setSystemHealth({
        overall_status: 'error', services: [],
        summary: { healthy: 0, warning: 0, disconnected: 0, error: 1, total: 1 },
        error: 'Failed to fetch system status'
      });
    }
  };

  const fetchCreditBudget = async () => {
    try {
      const res = await api.get('/api/research/budget');
      console.log('Credit budget fetched:', res.data);
      setCreditBudget(res.data);
    } catch (err) {
      console.log('Credit budget fetch failed:', err.message);
    }
  };

  const checkPriceAlerts = async () => {
    if (!isConnected || priceAlerts.length === 0) return;
    try {
      const res = await api.get('/api/ib/alerts/price/check');
      const triggered = res.data?.triggered || [];
      triggered.forEach(alert => {
        if (soundEnabled) playSound('alert');
        toast.success(
          `${alert.symbol} hit $${alert.triggered_price?.toFixed(2)} (target: ${alert.direction} $${alert.target_price})`,
          { duration: 8000 }
        );
      });
      if (triggered.length > 0) fetchPriceAlerts();
    } catch (e) {
      console.error('Error checking price alerts:', e);
    }
  };

  const fetchPriceAlerts = async () => {
    try {
      const res = await api.get('/api/ib/alerts/price');
      setPriceAlerts(res.data?.alerts || []);
    } catch { setPriceAlerts([]); }
  };

  const checkOrderFills = async () => {
    if (!isConnected) return;
    try {
      const res = await api.get('/api/ib/orders/fills');
      const fills = res.data?.newly_filled || [];
      fills.forEach(order => {
        if (soundEnabled) playSound('fill');
        toast.success(`Order Filled: ${order.action} ${order.quantity} ${order.symbol}`, { duration: 8000 });
      });
      setTrackedOrders(prev => prev.filter(o => !fills.find(f => f.order_id === o.order_id)));
    } catch (e) {
      console.error('Error checking order fills:', e);
    }
  };

  // ==================== SEARCH ====================

  const addToRecentSearches = (symbol) => {
    setRecentSearches(prev => {
      const filtered = prev.filter(s => s !== symbol);
      const updated = [symbol, ...filtered].slice(0, 5);
      localStorage.setItem('recentTickerSearches', JSON.stringify(updated));
      return updated;
    });
  };

  const clearRecentSearches = () => {
    setRecentSearches([]);
    localStorage.removeItem('recentTickerSearches');
  };

  // ==================== CHARTS ====================

  const addToRecentCharts = (symbol) => {
    setRecentCharts(prev => {
      const filtered = prev.filter(s => s !== symbol);
      const updated = [symbol, ...filtered].slice(0, 8);
      localStorage.setItem('recentChartSymbols', JSON.stringify(updated));
      return updated;
    });
  };

  const viewChart = (symbol) => {
    const sym = symbol.toUpperCase().trim();
    setChartSymbol(sym);
    localStorage.setItem('tradecommand_chart_symbol', sym);
    addToRecentCharts(sym);
    setActiveMainTab('charts');
  };

  const handleTickerSearch = async (e, symbolOverride = null) => {
    if (e) e.preventDefault();
    const symbol = (symbolOverride || tickerSearchQuery).trim().toUpperCase();
    if (!symbol) return;
    setIsSearching(true);
    try {
      addToRecentSearches(symbol);
      setSelectedTicker({ symbol, quote: {}, fromSearch: true });
      setTickerSearchQuery('');
      toast.success(`Loading analysis for ${symbol}...`);
    } catch (err) {
      console.error('Search error:', err);
      toast.error('Failed to search ticker');
    }
    setIsSearching(false);
  };

  // ==================== HELPERS ====================

  const openAssistantWithPrompt = useCallback((prompt = null) => {
    setAssistantPrompt(prompt);
    setShowAssistant(true);
  }, []);

  const askAIAboutStock = useCallback((symbol, action = 'analyze') => {
    const prompts = {
      analyze: `Analyze ${symbol} for me. What's the quality score, any matching strategies, and should I consider trading it?`,
      buy: `Should I buy ${symbol}? Check my rules and strategies.`,
      sell: `Should I sell ${symbol}? What does the data say?`,
      quality: `What's the earnings quality score on ${symbol}?`
    };
    openAssistantWithPrompt(prompts[action] || prompts.analyze);
  }, [openAssistantWithPrompt]);

  const handleTrade = (ticker, action) => {
    setTradeModal({ isOpen: true, ticker, action });
    setSelectedTicker(null);
  };

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const totalPnL = useMemo(() => {
    return positions.reduce((sum, pos) => sum + (pos.unrealized_pnl || 0), 0);
  }, [positions]);

  // ==================== EFFECTS ====================

  // Batch init - fetches multiple data sources in one call
  const fetchBatchInit = async () => {
    try {
      const res = await api.get('/api/dashboard/init');
      const data = res.data;
      
      // Update all states from batch response
      if (data.system_health) {
        setSystemHealth(data.system_health);
      }
      if (data.alerts) {
        setAlerts(data.alerts.alerts || []);
      }
      if (data.smart_watchlist) {
        setSmartWatchlist(data.smart_watchlist);
      }
      
      return data;
    } catch (err) {
      console.error('Batch init failed:', err);
      return null;
    }
  };

  // System health - now part of batch init, only poll separately at longer interval
  useEffect(() => {
    // Initial system health comes from batch init
    const interval = setInterval(fetchSystemHealth, 60000);
    return () => clearInterval(interval);
  }, []);

  // Fetch positions immediately on mount - doesn't depend on IB connection
  // Alpaca positions are always available
  useEffect(() => {
    fetchAccountData();
    // Refresh positions every 30 seconds
    const positionsInterval = setInterval(fetchAccountData, 30000);
    return () => clearInterval(positionsInterval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Initial data load - optimized with batch init + staggered loading
  useEffect(() => {
    console.log('[useEffect] connectionChecked:', connectionChecked, 'isConnected:', isConnected, 'isActiveTab:', isActiveTab);
    if (!connectionChecked) {
      console.log('[useEffect] Skipping - connectionChecked is false');
      return;
    }
    const init = async () => {
      console.log('[init] Starting data initialization...');
      // Phase 1: Batch init (system health, alerts, smart watchlist in ONE call)
      await fetchBatchInit();
      
      // Phase 1b: Fetch credit budget (lightweight, runs in parallel)
      fetchCreditBudget();
      
      // Phase 1c: Always fetch positions (works with Alpaca even without IB)
      console.log('[init] Calling fetchAccountData...');
      fetchAccountData();
      
      // Phase 2: IB-dependent data (only if connected)
      if (isConnected) {
        await fetchWatchlist(isConnected);
        
        // Phase 3: Additional IB data with slight delay
        setTimeout(async () => {
          await Promise.all([
            fetchPriceAlerts(),
            fetchMarketContext(),
            fetchEnhancedAlerts(),
          ]);
        }, 300);
      } else {
        // Not connected - just fetch price alerts
        fetchPriceAlerts();
      }
      
      // Phase 4: Lower priority - earnings at the end
      setTimeout(() => {
        fetchEarnings();
      }, 1000);
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionChecked, isConnected, isActiveTab]);

  // Refresh credit budget periodically (every 5 minutes)
  useEffect(() => {
    // Fetch immediately on mount (doesn't depend on IB connection)
    fetchCreditBudget();
    const budgetInterval = setInterval(fetchCreditBudget, 300000);
    return () => clearInterval(budgetInterval);
  }, []);

  // Polling for order fills and price alerts (30s is appropriate)
  useEffect(() => {
    if (!isConnected) return;
    const fastPoll = setInterval(() => {
      checkOrderFills();
      checkPriceAlerts();
    }, 30000);
    return () => clearInterval(fastPoll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected, soundEnabled, priceAlerts.length, isActiveTab, activeMainTab]);

  return {
    // Connection
    isConnected, connectionChecked, connecting,
    handleConnectToIB, handleDisconnectFromIB,
    // Data
    account, positions, opportunities, marketContext, alerts,
    watchlist, earnings, enhancedAlerts, priceAlerts,
    systemHealth, totalPnL, smartWatchlist, creditBudget,
    // UI state
    isScanning, selectedScanType, setSelectedScanType,
    selectedTicker, setSelectedTicker,
    tradeModal, setTradeModal,
    expandedSections, toggleSection,
    showAssistant, setShowAssistant,
    assistantPrompt,
    activeMainTab, setActiveMainTab,
    expandedStatCard, setExpandedStatCard,
    liveAlertsExpanded, setLiveAlertsExpanded,
    selectedEnhancedAlert, setSelectedEnhancedAlert,
    soundEnabled, setSoundEnabled,
    // Search
    tickerSearchQuery, setTickerSearchQuery,
    isSearching, recentSearches, clearRecentSearches,
    searchInputRef, handleTickerSearch,
    // Charts
    chartSymbol, setChartSymbol: (sym) => {
      setChartSymbol(sym);
      localStorage.setItem('tradecommand_chart_symbol', sym);
    },
    recentCharts, addToRecentCharts, viewChart,
    // Actions
    runScanner, fetchAccountData, handleTrade, askAIAboutStock,
  };
}
