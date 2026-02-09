import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Zap,
  Target,
  Activity,
  Search,
  X,
  ChevronDown,
  Play,
  Pause,
  Wifi,
  WifiOff,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  DollarSign,
  Bell,
  Eye,
  Newspaper,
  Briefcase,
  Calendar,
  Volume2,
  VolumeX,
  AlertTriangle,
  Plus,
  Trash2,
  MessageSquare,
  Info,
  Database,
  Cpu,
  BarChart3,
  Brain,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Monitor,
  BookOpen,
  Sparkles,
  Bot
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api, { apiLongRunning } from '../utils/api';
import { toast } from 'sonner';
import AICommandPanel from '../components/AICommandPanel';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
import LiveAlertsPanel from '../components/LiveAlertsPanel';
import TradingBotPanel from '../components/TradingBotPanel';
import LearningDashboard from '../components/LearningDashboard';
import { HelpTooltip, HelpIcon } from '../components/HelpTooltip';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { playSound, formatPrice, formatPercent, formatVolume, formatCurrency, formatMarketCap } from '../utils/tradingUtils';

// ===================== COMPONENTS =====================
const Card = ({ children, className = '', onClick, glow = false }) => (
  <div 
    onClick={onClick}
    className={`bg-[#0A0A0A] border border-white/10 rounded-lg p-4 transition-all duration-200 
      ${onClick ? 'cursor-pointer hover:border-cyan-500/30' : ''} 
      ${glow ? 'shadow-[0_0_15px_rgba(0,229,255,0.15)] border-cyan-500/30' : ''}
      ${className}`}
  >
    {children}
  </div>
);

const Badge = ({ children, variant = 'info', className = '' }) => {
  const variants = {
    success: 'text-green-400 bg-green-400/10 border-green-400/30',
    warning: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
    error: 'text-red-400 bg-red-400/10 border-red-400/30',
    info: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
    neutral: 'text-zinc-400 bg-zinc-400/10 border-zinc-400/30'
  };
  
  return (
    <span className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide border rounded-sm ${variants[variant]} ${className}`}>
      {children}
    </span>
  );
};

const SectionHeader = ({ icon: Icon, title, action, count }) => (
  <div className="flex items-center justify-between mb-3">
    <div className="flex items-center gap-2">
      <Icon className="w-5 h-5 text-cyan-400" />
      <h3 className="text-sm font-semibold uppercase tracking-wider text-white">{title}</h3>
      {count !== undefined && (
        <span className="text-xs text-zinc-500">({count})</span>
      )}
    </div>
    {action}
  </div>
);

// ===================== CHART COMPONENT =====================
const MiniChart = ({ symbol, data, width = '100%', height = 80 }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current || !data || data.length === 0) return;

    const chart = LightweightCharts.createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#71717a',
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: { visible: false },
      timeScale: { visible: false },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });

    // v4 API: addLineSeries
    const lineSeries = chart.addLineSeries({
      color: data[data.length - 1]?.close >= data[0]?.close ? '#00FF94' : '#FF2E2E',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const chartData = data.map(bar => ({
      time: new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000,
      value: bar.close,
    }));

    lineSeries.setData(chartData);
    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => {
      chart.remove();
    };
  }, [data, height]);

  return <div ref={chartContainerRef} style={{ width, height }} />;
};

// ===================== MAIN COMMAND CENTER =====================
const CommandCenterPage = ({ 
  ibConnected, 
  ibConnectionChecked, 
  connectToIb, 
  checkIbConnection, 
  isActiveTab = true,
  // WebSocket connection status for quotes streaming
  wsConnected = false,
  wsLastUpdate = null
}) => {
  // Use props from App for connection state (shared across all pages)
  const isConnected = ibConnected;
  const connectionChecked = ibConnectionChecked;
  const [connecting, setConnecting] = useState(false);
  
  // Data State
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [opportunities, setOpportunities] = useState([]);
  const [marketContext, setMarketContext] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [newsletter, setNewsletter] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [earnings, setEarnings] = useState([]);
  
  // UI State
  const [isScanning, setIsScanning] = useState(false);
  const [selectedScanType, setSelectedScanType] = useState('TOP_PERC_GAIN');
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [tradeModal, setTradeModal] = useState({ isOpen: false, ticker: null, action: null });
  const [expandedSections, setExpandedSections] = useState({
    holdings: true,
    opportunities: true,
    context: true,
    alerts: true,
    news: true,
    earnings: true,
    squeeze: false,
    priceAlerts: false,
    breakouts: true,
    enhancedAlerts: true,
    comprehensiveAlerts: true,
    systemMonitor: true
  });
  
  // AI Assistant state
  const [showAssistant, setShowAssistant] = useState(false);
  const [assistantPrompt, setAssistantPrompt] = useState(null);
  const [activeMainTab, setActiveMainTab] = useState('trading');
  
  // Ticker Search state
  const [tickerSearchQuery, setTickerSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('recentTickerSearches');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [showRecentSearches, setShowRecentSearches] = useState(false);
  const searchInputRef = useRef(null);
  
  // New P1 features state
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [shortSqueezeCandidates, setShortSqueezeCandidates] = useState([]);
  const [breakoutAlerts, setBreakoutAlerts] = useState([]);
  const [enhancedAlerts, setEnhancedAlerts] = useState([]);
  const [selectedEnhancedAlert, setSelectedEnhancedAlert] = useState(null);
  const [priceAlerts, setPriceAlerts] = useState([]);
  const [newAlertSymbol, setNewAlertSymbol] = useState('');
  const [newAlertPrice, setNewAlertPrice] = useState('');
  const [newAlertDirection, setNewAlertDirection] = useState('ABOVE');
  const [trackedOrders, setTrackedOrders] = useState([]);
  
  // Comprehensive scan state
  const [minScoreThreshold, setMinScoreThreshold] = useState(50);
  const [comprehensiveAlerts, setComprehensiveAlerts] = useState({
    scalp: [],
    intraday: [],
    swing: [],
    position: []
  });
  const [comprehensiveSummary, setComprehensiveSummary] = useState({
    scalp: 0, intraday: 0, swing: 0, position: 0, total: 0
  });
  const [selectedTimeframeTab, setSelectedTimeframeTab] = useState('all');
  const [isComprehensiveScanning, setIsComprehensiveScanning] = useState(false);
  
  // Live Alerts Panel state
  const [liveAlertsExpanded, setLiveAlertsExpanded] = useState(true);

  // Keyboard shortcuts
  useKeyboardShortcuts({
    'ctrl+k': () => {
      // Focus search bar
      if (searchInputRef.current) {
        searchInputRef.current.focus();
        setShowRecentSearches(true);
      }
    },
    'ctrl+shift+a': () => {
      // Toggle AI Assistant
      setShowAssistant(prev => !prev);
    },
    'escape': () => {
      // Close modals
      if (selectedTicker) {
        setSelectedTicker(null);
      } else if (tradeModal.isOpen) {
        setTradeModal({ isOpen: false, ticker: null, action: null });
      } else if (showAssistant) {
        setShowAssistant(false);
      } else if (showRecentSearches) {
        setShowRecentSearches(false);
      }
    },
    'ctrl+m': () => {
      // Toggle sound
      setSoundEnabled(prev => !prev);
      toast.info(soundEnabled ? 'Sound disabled' : 'Sound enabled');
    },
  }, isActiveTab);

  const scanTypes = [
    { id: 'TOP_PERC_GAIN', label: 'Top Gainers', icon: TrendingUp },
    { id: 'TOP_PERC_LOSE', label: 'Top Losers', icon: TrendingDown },
    { id: 'MOST_ACTIVE', label: 'Most Active', icon: Activity },
    { id: 'HIGH_OPEN_GAP', label: 'Gap Up', icon: ArrowUpRight },
    { id: 'LOW_OPEN_GAP', label: 'Gap Down', icon: ArrowDownRight },
  ];

  // Check IB connection - use shared function from App
  const checkConnection = async () => {
    return await checkIbConnection();
  };

  // Connect to IB - use shared function from App
  const handleConnectToIB = async () => {
    setConnecting(true);
    console.log('handleConnectToIB: Starting connection...');
    try {
      const connected = await connectToIb();
      console.log('handleConnectToIB: Connected =', connected);
      if (connected) {
        await fetchAccountData();
        await fetchWatchlist(connected);
      }
    } catch (err) {
      console.error('handleConnectToIB: Connection failed:', err);
    }
    setConnecting(false);
  };

  // Disconnect from IB
  const handleDisconnectFromIB = async () => {
    setConnecting(true);
    try {
      await api.post('/api/ib/disconnect');
      await checkIbConnection();
      toast.info('Disconnected from IB Gateway');
    } catch (err) {
      console.error('handleDisconnectFromIB: Disconnect failed:', err);
      toast.error('Failed to disconnect');
    }
    setConnecting(false);
  };

  // Fetch account data
  const fetchAccountData = async () => {
    try {
      const [accountRes, positionsRes] = await Promise.all([
        api.get('/api/ib/account/summary'),
        api.get('/api/ib/account/positions')
      ]);
      setAccount(accountRes.data);
      setPositions(positionsRes.data?.positions || []);
    } catch (err) {
      console.error('Error fetching account:', err);
    }
  };

  // Run scanner
  const runScanner = async () => {
    if (!isConnected) return;
    
    setIsScanning(true);
    try {
      const res = await api.post('/api/ib/scanner/enhanced', {
        scan_type: selectedScanType,
        max_results: 20,
        calculate_features: true
      });
      const results = res.data?.results || [];
      
      // Enhance with quality scores
      if (results.length > 0) {
        try {
          const symbols = results.map(r => r.symbol).filter(Boolean);
          const qualityRes = await api.post('/api/quality/enhance-opportunities', {
            opportunities: symbols.map(s => ({ symbol: s }))
          });
          
          // Map quality data back to results
          const qualityMap = {};
          (qualityRes.data?.opportunities || []).forEach(opp => {
            if (opp.symbol && opp.quality) {
              qualityMap[opp.symbol] = opp.quality;
            }
          });
          
          // Add quality to each result
          results.forEach(r => {
            if (r.symbol && qualityMap[r.symbol]) {
              r.quality = qualityMap[r.symbol];
              r.qualityGrade = qualityMap[r.symbol].grade;
            }
          });
        } catch (qualityErr) {
          console.log('Quality enhancement failed (non-critical):', qualityErr.message);
        }
      }
      
      setOpportunities(results);
    } catch (err) {
      console.error('Scanner error:', err);
    }
    setIsScanning(false);
  };

  // Fetch market context
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
      
      setMarketContext({
        regime,
        spy: spy?.change_percent || 0,
        qqq: qqq?.change_percent || 0,
        vix: vix?.price || 0
      });
    } catch (err) {
      console.error('Market context error:', err);
    }
  };

  // Fetch alerts
  const fetchAlerts = async () => {
    try {
      const res = await api.get('/api/alerts');
      setAlerts(res.data?.alerts?.slice(0, 5) || []);
    } catch {
      setAlerts([]);
    }
  };

  // Fetch newsletter / market intelligence
  const fetchNewsletter = async () => {
    try {
      const res = await api.get('/api/newsletter/latest');
      setNewsletter(res.data);
    } catch {
      setNewsletter(null);
    }
  };

  // Auto-generate market intelligence on IB connection
  const [isGeneratingIntelligence, setIsGeneratingIntelligence] = useState(false);
  
  // System Monitor state
  const [systemHealth, setSystemHealth] = useState(null);
  const [isLoadingSystemHealth, setIsLoadingSystemHealth] = useState(false);
  
  // Pre-market scheduler state
  const [premarketScheduled, setPremarketScheduled] = useState(false);
  
  // Fetch system health
  const fetchSystemHealth = async () => {
    setIsLoadingSystemHealth(true);
    try {
      const res = await api.get('/api/system/monitor');
      setSystemHealth(res.data);
    } catch (err) {
      console.error('Error fetching system health:', err);
      setSystemHealth({
        overall_status: 'error',
        services: [],
        summary: { healthy: 0, warning: 0, disconnected: 0, error: 1, total: 1 },
        error: 'Failed to fetch system status'
      });
    } finally {
      setIsLoadingSystemHealth(false);
    }
  };
  
  // Check scheduler status on mount
  useEffect(() => {
    const checkSchedulerStatus = async () => {
      try {
        const res = await api.get('/api/scheduler/status');
        setPremarketScheduled(res.data?.scheduler?.tasks?.includes('premarket') || false);
      } catch {
        // Ignore errors
      }
    };
    checkSchedulerStatus();
  }, []);
  
  // Fetch system health on mount and every 30 seconds
  useEffect(() => {
    fetchSystemHealth();
    const interval = setInterval(fetchSystemHealth, 30000);
    return () => clearInterval(interval);
  }, []);
  
  // Toggle pre-market schedule
  const togglePremarketSchedule = async () => {
    try {
      if (premarketScheduled) {
        await api.delete('/api/scheduler/premarket/stop');
        setPremarketScheduled(false);
        toast.info('Pre-market auto-generation disabled');
      } else {
        await api.post('/api/scheduler/premarket/schedule', { hour: 6, minute: 30 });
        setPremarketScheduled(true);
        toast.success('Pre-market briefing scheduled for 6:30 AM ET daily');
      }
    } catch (err) {
      toast.error('Failed to update schedule');
    }
  };
  
  const autoGenerateMarketIntelligence = async () => {
    if (isGeneratingIntelligence) return;
    
    setIsGeneratingIntelligence(true);
    try {
      toast.info('Generating market intelligence... This may take up to 2 minutes.', { duration: 5000 });
      // Use long-running API for Market Intelligence (2 minute timeout)
      const res = await apiLongRunning.post('/api/newsletter/auto-generate');
      console.log('Market Intelligence Response:', res.data);
      console.log('Summary:', res.data?.summary);
      console.log('needs_generation:', res.data?.needs_generation);
      setNewsletter(res.data);
      
      // Auto-expand the Market Intelligence section
      setExpandedSections(prev => ({ ...prev, news: true }));
      
      if (!res.data?.error) {
        toast.success('Market intelligence ready!', { duration: 5000 });
        if (soundEnabled) playSound('alert');
      }
    } catch (err) {
      console.error('Error generating market intelligence:', err);
      toast.error('Failed to generate market intelligence');
    } finally {
      setIsGeneratingIntelligence(false);
    }
  };

  // Open AI Assistant with optional prompt
  const openAssistantWithPrompt = useCallback((prompt = null) => {
    setAssistantPrompt(prompt);
    setShowAssistant(true);
  }, []);

  // Ask AI about a specific stock
  const askAIAboutStock = useCallback((symbol, action = 'analyze') => {
    const prompts = {
      analyze: `Analyze ${symbol} for me. What's the quality score, any matching strategies, and should I consider trading it?`,
      buy: `Should I buy ${symbol}? Check my rules and strategies.`,
      sell: `Should I sell ${symbol}? What does the data say?`,
      quality: `What's the earnings quality score on ${symbol}?`
    };
    openAssistantWithPrompt(prompts[action] || prompts.analyze);
  }, [openAssistantWithPrompt]);

  // Fetch watchlist
  const fetchWatchlist = async (connected) => {
    try {
      const res = await api.get('/api/watchlist');
      const symbols = res.data?.symbols || ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD'];
      
      if (connected && symbols.length > 0) {
        const quotesRes = await api.post('/api/ib/quotes/batch', symbols.slice(0, 10));
        setWatchlist(quotesRes.data?.quotes || []);
      }
    } catch {
      setWatchlist([]);
    }
  };

  // Fetch earnings calendar
  const fetchEarnings = async () => {
    try {
      const res = await api.get('/api/earnings/calendar');
      // Get earnings for next 30 days, sorted by date
      const upcoming = (res.data?.calendar || [])
        .filter(e => {
          const earningsDate = new Date(e.earnings_date);
          const today = new Date();
          today.setHours(0, 0, 0, 0);
          const nextMonth = new Date();
          nextMonth.setDate(today.getDate() + 30);
          return earningsDate >= today && earningsDate <= nextMonth;
        })
        .sort((a, b) => new Date(a.earnings_date) - new Date(b.earnings_date))
        .slice(0, 12);
      setEarnings(upcoming);
    } catch {
      setEarnings([]);
    }
  };

  // Fetch short squeeze candidates
  const fetchShortSqueeze = async () => {
    try {
      const res = await api.get('/api/ib/scanner/short-squeeze');
      setShortSqueezeCandidates(res.data?.candidates || []);
    } catch (err) {
      console.log('Short squeeze data unavailable:', err.response?.data?.detail?.message);
      setShortSqueezeCandidates([]);
    }
  };

  // Fetch breakout alerts - top 10 meeting all rules
  const fetchBreakoutAlerts = async () => {
    try {
      const res = await api.get('/api/ib/scanner/breakouts');
      setBreakoutAlerts(res.data?.breakouts || []);
      
      // Play sound for new breakouts
      if (soundEnabled && res.data?.breakouts?.length > 0) {
        const newBreakouts = res.data.breakouts.filter(b => {
          const detectedAt = new Date(b.detected_at);
          const now = new Date();
          return (now - detectedAt) < 60000; // Within last minute
        });
        if (newBreakouts.length > 0) {
          playSound('alert');
          newBreakouts.forEach(b => {
            toast.success(
              `🚀 ${b.breakout_type} Breakout: ${b.symbol} broke ${b.breakout_type === 'LONG' ? 'above' : 'below'} $${b.breakout_level} (Score: ${b.breakout_score})`,
              { duration: 10000 }
            );
          });
        }
      }
    } catch (err) {
      console.log('Breakout data unavailable:', err.response?.data?.detail?.message);
      setBreakoutAlerts([]);
    }
  };

  // Fetch enhanced alerts with full context
  const fetchEnhancedAlerts = async () => {
    try {
      const res = await api.get('/api/ib/alerts/enhanced');
      const alerts = res.data?.alerts || [];
      setEnhancedAlerts(alerts);
      
      // Notify for new alerts
      if (soundEnabled) {
        const newAlerts = alerts.filter(a => a.is_new);
        newAlerts.forEach(alert => {
          playSound('alert');
          toast.success(alert.headline, { duration: 10000 });
        });
      }
    } catch (err) {
      console.log('Enhanced alerts unavailable:', err.response?.data?.detail?.message);
    }
  };

  // Run comprehensive scan - scans ALL types and categorizes by timeframe
  const runComprehensiveScan = async () => {
    // Don't run if already scanning or not connected
    if (isComprehensiveScanning || !isConnected) {
      console.log('Skipping comprehensive scan:', { isComprehensiveScanning, isConnected });
      return;
    }
    
    setIsComprehensiveScanning(true);
    try {
      // Use long-running API for comprehensive scan (2 minute timeout)
      const res = await apiLongRunning.post('/api/ib/scanner/comprehensive', {
        min_score: minScoreThreshold
      });
      
      const alerts = res.data?.alerts || { scalp: [], intraday: [], swing: [], position: [] };
      const summary = res.data?.summary || { scalp: 0, intraday: 0, swing: 0, position: 0, total: 0 };
      
      setComprehensiveAlerts(alerts);
      setComprehensiveSummary(summary);
      
      // Check if response indicates cached results due to busy state
      if (res.data?.is_busy) {
        toast.info(`Scan in progress (${res.data.busy_operation || 'scanning'}). Showing cached results.`, { duration: 5000 });
        setIsComprehensiveScanning(false); // Allow user to retry
        return;
      }
      
      // Notify for high-quality alerts
      if (soundEnabled && summary.total > 0) {
        const allAlerts = [...alerts.scalp, ...alerts.intraday, ...alerts.swing, ...alerts.position];
        const gradeAAlerts = allAlerts.filter(a => a.grade === 'A');
        
        if (gradeAAlerts.length > 0) {
          playSound('alert');
          toast.success(`🎯 ${gradeAAlerts.length} Grade A opportunities found!`, { duration: 8000 });
        } else if (summary.total > 0) {
          toast.info(`Found ${summary.total} opportunities across all timeframes`, { duration: 5000 });
        }
      }
      
      console.log(`Comprehensive scan complete: ${summary.total} alerts found`);
    } catch (err) {
      const detail = err.response?.data?.detail;
      const errorMsg = detail?.message || err.message;
      console.log('Comprehensive scan error:', errorMsg);
      
      // Handle busy state error gracefully
      if (detail?.is_busy) {
        toast.info(`Scan in progress (${detail.busy_operation || 'scanning'}). Please wait...`, { duration: 5000 });
      } else if (isConnected) {
        // Only show error toast if we're supposed to be connected
        if (err.code === 'ECONNABORTED') {
          toast.error('Scan timed out - server may be processing large results');
        } else {
          toast.error('Scan failed - check IB Gateway connection');
        }
      }
    } finally {
      setIsComprehensiveScanning(false);
    }
  };

  // Get filtered comprehensive alerts based on selected timeframe tab
  const getFilteredComprehensiveAlerts = () => {
    if (selectedTimeframeTab === 'all') {
      return [
        ...comprehensiveAlerts.scalp,
        ...comprehensiveAlerts.intraday,
        ...comprehensiveAlerts.swing,
        ...comprehensiveAlerts.position
      ].sort((a, b) => b.overall_score - a.overall_score);
    }
    return comprehensiveAlerts[selectedTimeframeTab] || [];
  };

  // Dismiss/archive an enhanced alert
  const dismissEnhancedAlert = async (alertId) => {
    try {
      await api.delete(`/api/ib/alerts/enhanced/${alertId}`);
      setEnhancedAlerts(prev => prev.filter(a => a.id !== alertId));
      if (selectedEnhancedAlert?.id === alertId) {
        setSelectedEnhancedAlert(null);
      }
    } catch {
      toast.error('Failed to dismiss alert');
    }
  };

  // Dismiss comprehensive alert (from local state only)
  const dismissComprehensiveAlert = (alertId) => {
    setComprehensiveAlerts(prev => ({
      scalp: prev.scalp.filter(a => a.id !== alertId),
      intraday: prev.intraday.filter(a => a.id !== alertId),
      swing: prev.swing.filter(a => a.id !== alertId),
      position: prev.position.filter(a => a.id !== alertId)
    }));
    if (selectedEnhancedAlert?.id === alertId) {
      setSelectedEnhancedAlert(null);
    }
  };

  // Fetch price alerts
  const fetchPriceAlerts = async () => {
    try {
      const res = await api.get('/api/ib/alerts/price');
      setPriceAlerts(res.data?.alerts || []);
    } catch {
      setPriceAlerts([]);
    }
  };

  // Create price alert
  const createPriceAlert = async () => {
    if (!newAlertSymbol || !newAlertPrice) return;
    try {
      await api.post('/api/ib/alerts/price', {
        symbol: newAlertSymbol.toUpperCase(),
        target_price: parseFloat(newAlertPrice),
        direction: newAlertDirection
      });
      toast.success(`Alert created for ${newAlertSymbol.toUpperCase()} ${newAlertDirection} $${newAlertPrice}`);
      setNewAlertSymbol('');
      setNewAlertPrice('');
      fetchPriceAlerts();
    } catch (err) {
      toast.error('Failed to create alert');
    }
  };

  // Delete price alert
  const deletePriceAlert = async (alertId) => {
    try {
      await api.delete(`/api/ib/alerts/price/${alertId}`);
      fetchPriceAlerts();
    } catch {
      toast.error('Failed to delete alert');
    }
  };

  // Check for triggered price alerts
  const checkPriceAlerts = async () => {
    if (!isConnected || priceAlerts.length === 0) return;
    try {
      const res = await api.get('/api/ib/alerts/price/check');
      const triggered = res.data?.triggered || [];
      triggered.forEach(alert => {
        if (soundEnabled) playSound('alert');
        toast.success(
          `🔔 ${alert.symbol} hit $${alert.triggered_price?.toFixed(2)} (target: ${alert.direction} $${alert.target_price})`,
          { duration: 8000 }
        );
      });
      if (triggered.length > 0) {
        fetchPriceAlerts();
      }
    } catch (e) {
      console.error('Error checking price alerts:', e);
    }
  };

  // Check for order fills
  const checkOrderFills = async () => {
    if (!isConnected) return;
    try {
      const res = await api.get('/api/ib/orders/fills');
      const fills = res.data?.newly_filled || [];
      fills.forEach(order => {
        if (soundEnabled) playSound('fill');
        toast.success(
          `✅ Order Filled: ${order.action} ${order.quantity} ${order.symbol}`,
          { duration: 8000 }
        );
      });
      setTrackedOrders(prev => prev.filter(o => !fills.find(f => f.order_id === o.order_id)));
    } catch (e) {
      console.error('Error checking order fills:', e);
    }
  };

  // Initial load - staggered to avoid overwhelming the backend
  // Runs when connection status is confirmed and Command Center is active
  useEffect(() => {
    if (!connectionChecked) return; // Wait until we know connection status
    
    const init = async () => {
      if (isConnected) {
        // First batch: essential data
        await Promise.all([
          fetchAccountData(),
          fetchWatchlist(isConnected),
        ]);
        
        // Second batch: market data (slight delay to avoid overwhelming IB)
        setTimeout(async () => {
          await Promise.all([
            fetchMarketContext(),
            fetchBreakoutAlerts(),
          ]);
        }, 500);
        
        // Third batch: heavy operations (scanners) - only if Command Center is active
        if (isActiveTab) {
          setTimeout(async () => {
            await runComprehensiveScan();
          }, 1500);
        } else {
          console.log('Skipping initial scan - Command Center is not the active tab');
        }
      }
      
      // Non-IB data can load in parallel (these are lightweight)
      fetchAlerts();
      fetchNewsletter();
      fetchEarnings();
      fetchPriceAlerts();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionChecked, isConnected, isActiveTab]);

  // Fast polling for order fills and price alerts (every 10s when enabled)
  // This runs regardless of active tab to catch important alerts
  useEffect(() => {
    if (!isConnected) return;
    
    const fastPoll = setInterval(() => {
      // Price alerts and order fills are important - run even when not on Command Center
      // But skip heavy operations like enhanced alerts when not active
      checkOrderFills();
      checkPriceAlerts();
      if (isActiveTab) {
        fetchEnhancedAlerts();
      }
    }, 10000);
    
    return () => clearInterval(fastPoll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected, soundEnabled, priceAlerts.length, isActiveTab]);

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  // Add to recent searches helper
  const addToRecentSearches = (symbol) => {
    setRecentSearches(prev => {
      // Remove if already exists, then add to front
      const filtered = prev.filter(s => s !== symbol);
      const updated = [symbol, ...filtered].slice(0, 5); // Keep only 5 most recent
      localStorage.setItem('recentTickerSearches', JSON.stringify(updated));
      return updated;
    });
  };

  // Clear recent searches
  const clearRecentSearches = () => {
    setRecentSearches([]);
    localStorage.removeItem('recentTickerSearches');
  };

  // Ticker Search Handler
  const handleTickerSearch = async (e, symbolOverride = null) => {
    if (e) e.preventDefault();
    const symbol = (symbolOverride || tickerSearchQuery).trim().toUpperCase();
    if (!symbol) return;
    
    setIsSearching(true);
    setShowRecentSearches(false);
    try {
      // Add to recent searches
      addToRecentSearches(symbol);
      
      // Open the ticker detail modal with the searched symbol
      setSelectedTicker({ 
        symbol, 
        quote: {},
        fromSearch: true  // Flag to indicate this came from search
      });
      setTickerSearchQuery('');
      toast.success(`Loading analysis for ${symbol}...`);
    } catch (err) {
      console.error('Search error:', err);
      toast.error('Failed to search ticker');
    }
    setIsSearching(false);
  };

  const handleTrade = (ticker, action) => {
    setTradeModal({ isOpen: true, ticker, action });
    setSelectedTicker(null);
  };

  // Calculate totals
  const totalPnL = useMemo(() => {
    return positions.reduce((sum, pos) => sum + (pos.unrealized_pnl || 0), 0);
  }, [positions]);

  const regimeColors = {
    'Trending Up': 'text-green-400',
    'Trending Down': 'text-red-400',
    'Consolidation': 'text-yellow-400',
    'High Volatility': 'text-orange-400'
  };

  return (
    <div className="space-y-4 pb-8" data-testid="command-center-page">
      {/* Header Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Target className="w-7 h-7 text-cyan-400" />
              Command Center
            </h1>
            <p className="text-zinc-500 text-sm">Real-time trading intelligence hub</p>
          </div>
          
          {/* Compact System Monitor */}
          {systemHealth && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900/50 rounded-lg border border-zinc-800">
              <Monitor className="w-4 h-4 text-zinc-400" />
              <div className="flex items-center gap-1.5">
                {systemHealth.services.slice(0, 5).map((service, idx) => {
                  const statusColor = service.status === 'healthy' ? 'bg-green-500' :
                                     service.status === 'warning' ? 'bg-yellow-500' :
                                     service.status === 'disconnected' ? 'bg-orange-500' :
                                     'bg-red-500';
                  return (
                    <div
                      key={idx}
                      className={`w-2 h-2 rounded-full ${statusColor}`}
                      title={`${service.name}: ${service.details}`}
                    />
                  );
                })}
              </div>
              <span className={`text-xs font-medium ${
                systemHealth.overall_status === 'healthy' ? 'text-green-400' :
                systemHealth.overall_status === 'partial' ? 'text-yellow-400' :
                'text-red-400'
              }`}>
                {systemHealth.summary.healthy}/{systemHealth.summary.total}
              </span>
            </div>
          )}
        </div>
        
        {/* Ticker Search Bar with Recent Searches */}
        <form onSubmit={handleTickerSearch} className="flex-1 max-w-md mx-4 relative">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              ref={searchInputRef}
              type="text"
              value={tickerSearchQuery}
              onChange={(e) => setTickerSearchQuery(e.target.value.toUpperCase())}
              onFocus={() => setShowRecentSearches(true)}
              onBlur={() => setTimeout(() => setShowRecentSearches(false), 200)}
              placeholder="Search any ticker (e.g., AAPL, TSLA)..."
              className="w-full pl-10 pr-4 py-2 bg-zinc-900/80 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 text-sm"
              data-testid="ticker-search-input"
            />
            {tickerSearchQuery && (
              <button
                type="button"
                onClick={() => setTickerSearchQuery('')}
                className="absolute right-10 top-1/2 -translate-y-1/2 p-1 text-zinc-500 hover:text-white"
              >
                <X className="w-3 h-3" />
              </button>
            )}
            <button
              type="submit"
              disabled={!tickerSearchQuery || isSearching}
              className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-cyan-500/20 text-cyan-400 rounded text-xs font-medium hover:bg-cyan-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="ticker-search-btn"
            >
              {isSearching ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Go'}
            </button>
          </div>
          
          {/* Recent Searches Dropdown */}
          {showRecentSearches && recentSearches.length > 0 && !tickerSearchQuery && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
                <span className="text-xs text-zinc-500 flex items-center gap-1.5">
                  <Clock className="w-3 h-3" />
                  Recent Searches
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    clearRecentSearches();
                  }}
                  className="text-xs text-zinc-500 hover:text-red-400 flex items-center gap-1"
                >
                  <Trash2 className="w-3 h-3" />
                  Clear
                </button>
              </div>
              <div className="py-1">
                {recentSearches.map((symbol, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      handleTickerSearch(null, symbol);
                    }}
                    className="w-full px-3 py-2 text-left text-sm text-white hover:bg-cyan-500/10 flex items-center gap-2 transition-colors"
                    data-testid={`recent-search-${symbol}`}
                  >
                    <Search className="w-3 h-3 text-zinc-500" />
                    <span className="font-mono font-medium">{symbol}</span>
                    <ArrowUpRight className="w-3 h-3 text-zinc-600 ml-auto" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </form>
        
        <div className="flex items-center gap-3">
          {/* AI Assistant Button */}
          <button
            onClick={() => setShowAssistant(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-amber-500/20 to-cyan-500/20 text-amber-400 rounded text-sm hover:from-amber-500/30 hover:to-cyan-500/30 border border-amber-500/30"
            title="AI Trading Assistant & Coach"
            data-testid="ai-assistant-btn"
          >
            <Sparkles className="w-4 h-4" />
            <span className="hidden sm:inline">AI Assistant</span>
          </button>
          
          {/* Dual Connection Status Indicator - WebSocket vs IB Gateway */}
          <div className="flex items-center gap-2">
            {/* WebSocket Status - For real-time quotes streaming */}
            <div 
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${
                wsConnected 
                  ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' 
                  : 'bg-orange-500/10 text-orange-400 border-orange-500/30 animate-pulse'
              }`}
              title={wsConnected 
                ? `Quotes streaming active${wsLastUpdate ? ` (Last: ${new Date(wsLastUpdate).toLocaleTimeString()})` : ''}`
                : 'Quotes streaming reconnecting...'
              }
            >
              {wsConnected ? (
                <>
                  <Activity className="w-3 h-3" />
                  <span className="hidden md:inline">Quotes</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                </>
              ) : (
                <>
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  <span className="hidden md:inline">Reconnecting</span>
                </>
              )}
            </div>
            
            {/* IB Gateway Status - For trading & scanners */}
            <div 
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${
                !connectionChecked ? 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30' :
                isConnected ? 'bg-green-500/10 text-green-400 border-green-500/30' : 
                'bg-red-500/10 text-red-400 border-red-500/30'
              }`}
              title={
                !connectionChecked ? 'Checking IB Gateway connection...' :
                isConnected ? 'IB Gateway connected - Trading & scanners available' : 
                'IB Gateway disconnected - Connect to enable trading'
              }
            >
              {!connectionChecked ? (
                <>
                  <div className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin" />
                  <span className="hidden md:inline">Checking</span>
                </>
              ) : isConnected ? (
                <>
                  <Database className="w-3 h-3" />
                  <span className="hidden md:inline">IB Gateway</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  <span className="hidden md:inline">IB Gateway</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                </>
              )}
            </div>
            
            {/* Connect/Disconnect Toggle Button */}
            {connectionChecked && (
              <button
                onClick={isConnected ? handleDisconnectFromIB : handleConnectToIB}
                disabled={connecting}
                className={`px-3 py-1.5 rounded font-medium text-xs transition-colors ${
                  isConnected 
                    ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30' 
                    : 'bg-cyan-500 text-black hover:bg-cyan-400'
                } disabled:opacity-50`}
              >
                {connecting ? '...' : isConnected ? 'Disconnect' : 'Connect'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Quick Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
              <DollarSign className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Net Liquidation</p>
              <p className="text-lg font-bold font-mono text-white">
                {formatCurrency(account?.net_liquidation)}
              </p>
            </div>
          </div>
        </Card>
        
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
              totalPnL >= 0 ? 'bg-green-500/10' : 'bg-red-500/10'
            }`}>
              {totalPnL >= 0 ? <TrendingUp className="w-5 h-5 text-green-400" /> : <TrendingDown className="w-5 h-5 text-red-400" />}
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Today&apos;s P&L</p>
              <p className={`text-lg font-bold font-mono ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {formatCurrency(account?.unrealized_pnl || totalPnL)}
              </p>
            </div>
          </div>
        </Card>
        
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Briefcase className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Positions</p>
              <p className="text-lg font-bold font-mono text-white">{positions.length}</p>
            </div>
          </div>
        </Card>
        
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-yellow-500/10 flex items-center justify-center">
              <Bell className="w-5 h-5 text-yellow-400" />
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Alerts</p>
              <p className="text-lg font-bold font-mono text-white">{alerts.length}</p>
            </div>
          </div>
        </Card>
        
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
              marketContext?.regime === 'Trending Up' ? 'bg-green-500/10' :
              marketContext?.regime === 'Trending Down' ? 'bg-red-500/10' :
              'bg-yellow-500/10'
            }`}>
              <Activity className={`w-5 h-5 ${regimeColors[marketContext?.regime] || 'text-zinc-400'}`} />
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Market</p>
              <p className={`text-sm font-bold ${regimeColors[marketContext?.regime] || 'text-zinc-400'}`}>
                {marketContext?.regime || 'Loading...'}
              </p>
            </div>
          </div>
        </Card>
        
        <Card className="col-span-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
              <Zap className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-[10px] text-zinc-500 uppercase">Opportunities</p>
              <p className="text-lg font-bold font-mono text-white">{opportunities.length}</p>
            </div>
          </div>
        </Card>
      </div>

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 bg-[#0A0A0A] border border-white/10 rounded-lg p-1 mt-1" data-testid="main-tabs">
        {[
          { id: 'trading', label: 'Trading', icon: '⚡' },
          { id: 'coach', label: 'AI Coach', icon: '🧠' },
          { id: 'analytics', label: 'Analytics', icon: '📊' }
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveMainTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all ${
              activeMainTab === tab.id
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

      {/* ==================== TRADING TAB ==================== */}
      {activeMainTab === 'trading' && (
        <div className="space-y-4 mt-2">
          {/* Live Alerts Panel */}
          <LiveAlertsPanel
            isExpanded={liveAlertsExpanded}
            onToggleExpand={() => setLiveAlertsExpanded(!liveAlertsExpanded)}
            onAlertSelect={(alert) => {
              setSelectedTicker({ symbol: alert.symbol, quote: { price: alert.current_price } });
            }}
          />

          {/* Trading Bot Panel */}
          <TradingBotPanel 
            onTickerSelect={(ticker) => setSelectedTicker(ticker)}
          />
        </div>
      )}

      {/* ==================== AI COACH TAB ==================== */}
      {activeMainTab === 'coach' && (
        <div className="grid lg:grid-cols-12 gap-4 mt-2">
          {/* Left - Scanner & Holdings */}
          <div className="lg:col-span-3 space-y-4">
          {/* Scanner Panel */}
          <Card>
            <SectionHeader icon={Target} title="Scanner" action={
              <button
                onClick={() => !isConnected ? toast.error('Connect to IB Gateway first') : runScanner()}
                disabled={isScanning || !isConnected}
                className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 disabled:text-zinc-600"
              >
                {isScanning ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                {isScanning ? 'Scanning...' : 'Scan'}
              </button>
            } />
            
            {/* Scan Types */}
            <div className="flex flex-wrap gap-1 mb-3">
              {scanTypes.slice(0, 6).map(scan => (
                <button
                  key={scan.id}
                  onClick={() => setSelectedScanType(scan.id)}
                  className={`px-2 py-1 text-[10px] rounded-full transition-colors ${
                    selectedScanType === scan.id
                      ? 'bg-cyan-500 text-black font-medium'
                      : 'bg-zinc-800 text-zinc-400 hover:text-white'
                  }`}
                >
                  {scan.name}
                </button>
              ))}
            </div>

            {/* Scan Results */}
            <div className="space-y-1 max-h-[300px] overflow-y-auto">
              {opportunities.length > 0 ? opportunities.slice(0, 10).map((result, idx) => (
                <div 
                  key={idx}
                  onClick={() => setSelectedTicker({ symbol: result.symbol, quote: result })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div>
                    <span className="text-sm font-bold text-white">{result.symbol}</span>
                    <span className={`text-xs ml-2 ${result.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(result.change_percent)}
                    </span>
                  </div>
                  <span className="text-xs text-zinc-500">${formatPrice(result.price)}</span>
                </div>
              )) : (
                <p className="text-center text-zinc-500 text-xs py-4">
                  {isConnected ? 'Run a scan to find opportunities' : 'Connect to IB to scan'}
                </p>
              )}
            </div>
          </Card>

          {/* Holdings Panel */}
          <Card>
            <button 
              onClick={() => toggleSection('holdings')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Briefcase className="w-5 h-5 text-cyan-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Holdings</h3>
                <span className="text-xs text-zinc-500">({positions.length})</span>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.holdings ? 'rotate-180' : ''}`} />
            </button>
            
            {expandedSections.holdings && (
              <div className="space-y-1 max-h-[200px] overflow-y-auto">
                {positions.length > 0 ? positions.map((pos, idx) => (
                  <div 
                    key={idx} 
                    className="flex items-center justify-between p-2 bg-zinc-900/50 rounded hover:bg-zinc-900 cursor-pointer"
                    onClick={() => setSelectedTicker({ symbol: pos.symbol, quote: { price: pos.avg_cost } })}
                  >
                    <div>
                      <span className="font-bold text-white text-sm">{pos.symbol}</span>
                      <span className="text-xs text-zinc-500 ml-1">{pos.quantity}</span>
                    </div>
                    <span className={`text-xs ${(pos.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatCurrency(pos.unrealized_pnl || 0)}
                    </span>
                  </div>
                )) : (
                  <p className="text-center text-zinc-500 text-xs py-2">No positions</p>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* CENTER - AI Command Panel */}
        <div className="lg:col-span-6">
          <div className="h-[calc(100vh-220px)] min-h-[600px]">
            <AICommandPanel
              onTickerSelect={(ticker) => setSelectedTicker(ticker)}
              watchlist={watchlist}
              alerts={[...enhancedAlerts, ...alerts]}
              opportunities={opportunities}
              earnings={earnings}
              portfolio={positions}
              scanResults={opportunities}
              marketIndices={marketContext?.indices || []}
              isConnected={isConnected}
              onRefresh={() => runScanner()}
            />
          </div>
        </div>

        {/* Right Column - Alerts & Opportunities */}
        <div className="lg:col-span-3 space-y-4">
          {/* Market Intelligence Panel */}
          <Card>
            <div 
              onClick={() => toggleSection('news')}
              className="w-full flex items-center justify-between mb-3 cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <Newspaper className="w-5 h-5 text-purple-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Market Intel</h3>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.news ? 'rotate-180' : ''}`} />
            </div>
            
            {expandedSections.news && newsletter && (
              <div className="space-y-2 max-h-[200px] overflow-y-auto">
                {newsletter.top_stories?.slice(0, 3).map((story, idx) => (
                  <div key={idx} className="p-2 bg-zinc-900/50 rounded">
                    <p className="text-xs text-zinc-300">{story.headline || story}</p>
                  </div>
                ))}
                {!newsletter.top_stories?.length && (
                  <p className="text-xs text-zinc-500 text-center py-2">No market intel available</p>
                )}
              </div>
            )}
          </Card>

          {/* Enhanced Alerts Panel */}
          <Card>
            <SectionHeader icon={Bell} title="Alerts" count={enhancedAlerts.length + alerts.length} />
            <div className="space-y-1 max-h-[250px] overflow-y-auto">
              {enhancedAlerts.length > 0 ? enhancedAlerts.slice(0, 5).map((alert, idx) => (
                <div 
                  key={idx}
                  onClick={() => setSelectedEnhancedAlert(alert)}
                  className="p-2 bg-zinc-900/50 rounded hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-white">{alert.symbol}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      alert.grade === 'A' ? 'bg-green-500 text-black' :
                      alert.grade === 'B' ? 'bg-cyan-500 text-black' : 'bg-yellow-500 text-black'
                    }`}>{alert.grade}</span>
                  </div>
                  <p className="text-[10px] text-zinc-400 mt-1 truncate">{alert.headline}</p>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No active alerts</p>
              )}
            </div>
          </Card>

          {/* Quick Stats Summary */}
          <Card>
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2 bg-zinc-900/50 rounded text-center">
                <span className="text-[10px] text-zinc-500 block">Net Liq</span>
                <span className="text-sm font-mono text-white">{formatCurrency(account?.net_liquidation)}</span>
              </div>
              <div className="p-2 bg-zinc-900/50 rounded text-center">
                <span className="text-[10px] text-zinc-500 block">P&L</span>
                <span className={`text-sm font-mono ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatCurrency(account?.unrealized_pnl || totalPnL)}
                </span>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Ticker Detail Modal */}
      {selectedTicker && (
        <TickerDetailModal
          ticker={selectedTicker}
          onClose={() => setSelectedTicker(null)}
          onTrade={handleTrade}
          onAskAI={askAIAboutStock}
        />
      )}

      {/* Quick Trade Modal */}
      {tradeModal.isOpen && (
        <QuickTradeModal
          ticker={tradeModal.ticker}
          action={tradeModal.action}
          onClose={() => setTradeModal({ isOpen: false, ticker: null, action: null })}
          onSuccess={() => {
            fetchAccountData();
            setTradeModal({ isOpen: false, ticker: null, action: null });
          }}
        />
      )}
    </div>
  );
};

export default CommandCenterPage;
