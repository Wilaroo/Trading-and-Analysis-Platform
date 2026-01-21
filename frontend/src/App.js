import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Search,
  BookOpen,
  Bell,
  Briefcase,
  Newspaper,
  TrendingUp,
  TrendingDown,
  Clock,
  Calendar,
  Target,
  Activity,
  RefreshCw,
  ChevronRight,
  Eye,
  Zap,
  BarChart3,
  X,
  Plus,
  Trash2,
  Users,
  PieChart,
  LineChart,
  DollarSign,
  Building,
  ArrowUpRight,
  ArrowDownRight,
  Info,
  ExternalLink,
  Wifi,
  WifiOff,
  Volume2,
  VolumeX,
  AlertTriangle,
  CheckCircle
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  PieChart as RePieChart,
  Pie
} from 'recharts';
import './App.css';

// ===================== ALERT SOUND SYSTEM =====================
const createAlertSound = () => {
  let audioContext = null;
  
  const getContext = () => {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    // Resume context if suspended (browser autoplay policy)
    if (audioContext.state === 'suspended') {
      audioContext.resume();
    }
    return audioContext;
  };
  
  return {
    playBullish: () => {
      try {
        const ctx = getContext();
        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);
        
        oscillator.frequency.setValueAtTime(440, ctx.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.2);
        
        gainNode.gain.setValueAtTime(0.3, ctx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
        
        oscillator.start(ctx.currentTime);
        oscillator.stop(ctx.currentTime + 0.3);
      } catch (e) {
        console.error('Audio playback failed:', e);
      }
    },
    
    playBearish: () => {
      try {
        const ctx = getContext();
        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);
        
        oscillator.frequency.setValueAtTime(880, ctx.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.2);
        
        gainNode.gain.setValueAtTime(0.3, ctx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
        
        oscillator.start(ctx.currentTime);
        oscillator.stop(ctx.currentTime + 0.3);
      } catch (e) {
        console.error('Audio playback failed:', e);
      }
    },
    
    playUrgent: () => {
      try {
        const ctx = getContext();
        const playBeep = (startTime, freq) => {
          const oscillator = ctx.createOscillator();
          const gainNode = ctx.createGain();
          
          oscillator.connect(gainNode);
          gainNode.connect(ctx.destination);
          
          oscillator.frequency.setValueAtTime(freq, startTime);
          gainNode.gain.setValueAtTime(0.4, startTime);
          gainNode.gain.exponentialRampToValueAtTime(0.01, startTime + 0.15);
          
          oscillator.start(startTime);
          oscillator.stop(startTime + 0.15);
        };
        
        playBeep(ctx.currentTime, 1000);
        playBeep(ctx.currentTime + 0.2, 1200);
      } catch (e) {
        console.error('Audio playback failed:', e);
      }
    }
  };
};

// ===================== PRICE ALERTS HOOK =====================
const usePriceAlerts = (streamingQuotes, watchlist = []) => {
  const [alerts, setAlerts] = useState([]);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [alertThreshold, setAlertThreshold] = useState(2); // 2% change threshold
  const previousPricesRef = useRef({});
  const alertSoundRef = useRef(null);
  const processedAlertsRef = useRef(new Set());
  
  // Initialize audio on first user interaction
  const initializeAudio = useCallback(() => {
    if (!alertSoundRef.current) {
      alertSoundRef.current = createAlertSound();
    }
  }, []);
  
  // Check for price movements and trigger alerts
  const checkPriceAlerts = useCallback((quotes) => {
    if (!quotes || Object.keys(quotes).length === 0) return;
    
    const newAlerts = [];
    const now = Date.now();
    
    // Get watchlist symbols (or use streaming symbols if no watchlist)
    const symbolsToWatch = watchlist.length > 0 
      ? watchlist.map(w => w.symbol) 
      : Object.keys(quotes);
    
    symbolsToWatch.forEach(symbol => {
      const quote = quotes[symbol];
      if (!quote) return;
      
      const previousPrice = previousPricesRef.current[symbol];
      const currentPrice = quote.price;
      const changePercent = quote.change_percent || 0;
      
      // Check for significant movement (use either price change or % change)
      let alertTriggered = false;
      let alertType = 'info';
      let alertMessage = '';
      
      // Method 1: Check absolute change percent from API
      if (Math.abs(changePercent) >= alertThreshold) {
        alertTriggered = true;
        alertType = changePercent > 0 ? 'bullish' : 'bearish';
        alertMessage = `${symbol} ${changePercent > 0 ? 'up' : 'down'} ${Math.abs(changePercent).toFixed(2)}%`;
      }
      
      // Method 2: Check price change since last update (for real-time spikes)
      if (previousPrice && currentPrice) {
        const priceDelta = ((currentPrice - previousPrice) / previousPrice) * 100;
        if (Math.abs(priceDelta) >= alertThreshold * 0.5) { // Half threshold for real-time
          alertTriggered = true;
          alertType = priceDelta > 0 ? 'bullish' : 'bearish';
          alertMessage = `${symbol} moved ${priceDelta > 0 ? '+' : ''}${priceDelta.toFixed(2)}% in real-time`;
        }
      }
      
      // Create alert if triggered and not already processed recently
      const alertKey = `${symbol}-${Math.floor(now / 60000)}`; // Unique per minute
      if (alertTriggered && !processedAlertsRef.current.has(alertKey)) {
        processedAlertsRef.current.add(alertKey);
        
        // Clean old processed alerts (keep last 100)
        if (processedAlertsRef.current.size > 100) {
          const entries = Array.from(processedAlertsRef.current);
          processedAlertsRef.current = new Set(entries.slice(-50));
        }
        
        const alert = {
          id: `${symbol}-${now}`,
          symbol,
          price: currentPrice,
          changePercent,
          type: alertType,
          message: alertMessage,
          timestamp: new Date().toISOString(),
          read: false
        };
        
        newAlerts.push(alert);
        
        // Play sound
        if (audioEnabled && alertSoundRef.current) {
          if (Math.abs(changePercent) >= alertThreshold * 2) {
            alertSoundRef.current.playUrgent();
          } else if (alertType === 'bullish') {
            alertSoundRef.current.playBullish();
          } else {
            alertSoundRef.current.playBearish();
          }
        }
      }
      
      // Update previous price
      previousPricesRef.current[symbol] = currentPrice;
    });
    
    if (newAlerts.length > 0) {
      setAlerts(prev => [...newAlerts, ...prev].slice(0, 50)); // Keep last 50 alerts
    }
  }, [watchlist, alertThreshold, audioEnabled]);
  
  // Process quotes when they update
  useEffect(() => {
    if (Object.keys(streamingQuotes).length > 0) {
      checkPriceAlerts(streamingQuotes);
    }
  }, [streamingQuotes, checkPriceAlerts]);
  
  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);
  
  const dismissAlert = useCallback((alertId) => {
    setAlerts(prev => prev.filter(a => a.id !== alertId));
  }, []);
  
  return {
    alerts,
    audioEnabled,
    setAudioEnabled,
    alertThreshold,
    setAlertThreshold,
    initializeAudio,
    clearAlerts,
    dismissAlert
  };
};

// ===================== PRICE ALERT NOTIFICATION COMPONENT =====================
const PriceAlertNotification = ({ alerts, onDismiss, audioEnabled, setAudioEnabled }) => {
  if (alerts.length === 0) return null;
  
  return (
    <div className="fixed top-20 right-4 z-50 space-y-2 max-h-[60vh] overflow-y-auto">
      <AnimatePresence>
        {alerts.slice(0, 5).map((alert) => (
          <motion.div
            key={alert.id}
            initial={{ opacity: 0, x: 100, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.9 }}
            className={`glass-card rounded-lg p-4 min-w-[280px] border-l-4 ${
              alert.type === 'bullish' 
                ? 'border-l-green-500 bg-green-500/10' 
                : alert.type === 'bearish'
                ? 'border-l-red-500 bg-red-500/10'
                : 'border-l-blue-500 bg-blue-500/10'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                {alert.type === 'bullish' ? (
                  <TrendingUp className="w-5 h-5 text-green-400" />
                ) : alert.type === 'bearish' ? (
                  <TrendingDown className="w-5 h-5 text-red-400" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-yellow-400" />
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{alert.symbol}</span>
                    <span className={`font-mono text-sm ${
                      alert.changePercent > 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {alert.changePercent > 0 ? '+' : ''}{alert.changePercent?.toFixed(2)}%
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400">{alert.message}</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    ${alert.price?.toFixed(2)} • {new Date(alert.timestamp).toLocaleTimeString()}
                  </p>
                </div>
              </div>
              <button
                onClick={() => onDismiss(alert.id)}
                className="text-zinc-500 hover:text-white transition-colors"
                data-testid={`dismiss-alert-${alert.symbol}`}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

// Use relative URL for API calls - proxy handles routing
const API_URL = '';

// WebSocket URL - detect protocol and construct WS URL
const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  // For development with proxy, connect to backend directly
  if (host.includes('localhost:3000')) {
    return 'ws://localhost:8001/ws/quotes';
  }
  return `${protocol}//${host}/ws/quotes`;
};

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000
});

// ===================== WEBSOCKET HOOK =====================
const useWebSocket = (onMessage) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  const connect = useCallback(() => {
    try {
      const wsUrl = getWebSocketUrl();
      console.log('Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLastUpdate(new Date());
          if (onMessage) {
            onMessage(data);
          }
        } catch (e) {
          console.error('Error parsing WebSocket message:', e);
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);
        // Reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setIsConnected(false);
      };
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      setIsConnected(false);
    }
  }, [onMessage]);

  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  const subscribe = useCallback((symbols) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'subscribe', symbols }));
    }
  }, []);

  const unsubscribe = useCallback((symbols) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'unsubscribe', symbols }));
    }
  }, []);

  return { isConnected, lastUpdate, subscribe, unsubscribe };
};

// ===================== TRADINGVIEW WIDGET =====================
const TradingViewWidget = ({ symbol = 'AAPL', theme = 'dark' }) => {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.innerHTML = '';
      
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      script.type = 'text/javascript';
      script.async = true;
      script.innerHTML = JSON.stringify({
        autosize: true,
        symbol: symbol,
        interval: 'D',
        timezone: 'America/New_York',
        theme: theme,
        style: '1',
        locale: 'en',
        enable_publishing: false,
        hide_top_toolbar: false,
        hide_legend: false,
        save_image: false,
        calendar: false,
        hide_volume: false,
        support_host: 'https://www.tradingview.com',
        backgroundColor: 'rgba(5, 5, 5, 1)',
        gridColor: 'rgba(255, 255, 255, 0.06)',
        studies: ['RSI@tv-basicstudies', 'MASimple@tv-basicstudies', 'MACD@tv-basicstudies']
      });

      containerRef.current.appendChild(script);
    }
  }, [symbol, theme]);

  return (
    <div className="tradingview-widget-container h-full" ref={containerRef}>
      <div className="tradingview-widget-container__widget h-full"></div>
    </div>
  );
};

// TradingView Mini Chart
const TradingViewMiniChart = ({ symbol = 'AAPL' }) => {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.innerHTML = '';
      
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js';
      script.type = 'text/javascript';
      script.async = true;
      script.innerHTML = JSON.stringify({
        symbol: symbol,
        width: '100%',
        height: '100%',
        locale: 'en',
        dateRange: '1M',
        colorTheme: 'dark',
        isTransparent: true,
        autosize: true,
        largeChartUrl: ''
      });

      containerRef.current.appendChild(script);
    }
  }, [symbol]);

  return (
    <div className="tradingview-widget-container h-full" ref={containerRef}>
      <div className="tradingview-widget-container__widget h-full"></div>
    </div>
  );
};

// ===================== COMPONENTS =====================

const Sidebar = ({ activeTab, setActiveTab }) => {
  const navItems = [
    { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { id: 'chart', icon: LineChart, label: 'Charts' },
    { id: 'scanner', icon: Search, label: 'Scanner' },
    { id: 'strategies', icon: BookOpen, label: 'Strategies' },
    { id: 'watchlist', icon: Eye, label: 'Watchlist' },
    { id: 'portfolio', icon: Briefcase, label: 'Portfolio' },
    { id: 'fundamentals', icon: Building, label: 'Fundamentals' },
    { id: 'insider', icon: Users, label: 'Insider Trading' },
    { id: 'cot', icon: PieChart, label: 'COT Data' },
    { id: 'alerts', icon: Bell, label: 'Alerts' },
    { id: 'newsletter', icon: Newspaper, label: 'Newsletter' },
  ];

  return (
    <aside className="w-16 lg:w-64 bg-paper border-r border-white/5 flex flex-col fixed h-screen z-50">
      <div className="p-4 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
            <Activity className="w-6 h-6 text-primary" />
          </div>
          <span className="hidden lg:block font-bold text-lg tracking-tight">TradeCommand</span>
        </div>
      </div>

      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <button
            key={item.id}
            data-testid={`nav-${item.id}`}
            onClick={() => setActiveTab(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 ${
              activeTab === item.id
                ? 'bg-primary/10 text-primary border border-primary/30'
                : 'text-zinc-400 hover:bg-white/5 hover:text-white border border-transparent'
            }`}
          >
            <item.icon className="w-5 h-5 flex-shrink-0" />
            <span className="hidden lg:block text-sm font-medium">{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
};

const PriceDisplay = ({ value, showArrow = true, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {showArrow && !isNeutral && (
        isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />
      )}
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

const Card = ({ children, className = '', onClick, hover = true }) => (
  <div 
    onClick={onClick}
    className={`bg-paper rounded-lg p-4 border border-white/10 ${
      hover ? 'transition-all duration-200 hover:border-primary/30' : ''
    } ${onClick ? 'cursor-pointer' : ''} ${className}`}
  >
    {children}
  </div>
);

const Skeleton = ({ className = '' }) => (
  <div className={`skeleton rounded ${className}`} />
);

const TickerTape = ({ indices, isConnected, lastUpdate }) => {
  if (!indices || indices.length === 0) return null;
  
  return (
    <div className="bg-paper border-b border-white/5 py-2 overflow-hidden">
      <div className="flex items-center">
        {/* Live indicator */}
        <div className="flex items-center gap-2 px-4 border-r border-white/10">
          {isConnected ? (
            <>
              <Wifi className="w-4 h-4 text-green-400" />
              <span className="text-xs text-green-400 font-medium">LIVE</span>
            </>
          ) : (
            <>
              <WifiOff className="w-4 h-4 text-red-400" />
              <span className="text-xs text-red-400 font-medium">OFFLINE</span>
            </>
          )}
          {lastUpdate && (
            <span className="text-xs text-zinc-500 hidden md:block">
              {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
        
        {/* Scrolling ticker */}
        <div className="flex-1 overflow-hidden">
          <div className="flex gap-8 ticker-tape">
            {[...indices, ...indices].map((item, idx) => (
              <div key={idx} className="flex items-center gap-3 whitespace-nowrap">
                <span className="text-zinc-400 text-sm">{item.symbol}</span>
                <span className="font-mono-data text-white">${item.price?.toFixed(2)}</span>
                <PriceDisplay value={item.change_percent} className="text-sm" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

const StatsCard = ({ icon: Icon, label, value, change, loading }) => (
  <Card className="flex items-center gap-4">
    <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
      <Icon className="w-6 h-6 text-primary" />
    </div>
    <div className="flex-1">
      <p className="text-xs text-zinc-500 uppercase tracking-wider">{label}</p>
      {loading ? (
        <Skeleton className="h-7 w-24 mt-1" />
      ) : (
        <p className="text-2xl font-bold font-mono-data">{value}</p>
      )}
    </div>
    {change !== undefined && <PriceDisplay value={change} />}
  </Card>
);

const AlertItem = ({ alert }) => (
  <motion.div
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
    className="glass-card rounded-lg p-4 flex items-start gap-4"
  >
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
      alert.score >= 70 ? 'bg-green-500/20' : alert.score >= 50 ? 'bg-yellow-500/20' : 'bg-blue-500/20'
    }`}>
      <Zap className={`w-5 h-5 ${
        alert.score >= 70 ? 'text-green-400' : alert.score >= 50 ? 'text-yellow-400' : 'text-blue-400'
      }`} />
    </div>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 mb-1">
        <span className="font-bold text-primary">{alert.symbol}</span>
        <span className="badge badge-info">{alert.strategy_id}</span>
      </div>
      <p className="text-sm text-zinc-400 truncate">{alert.strategy_name}</p>
      <p className="text-xs text-zinc-500 mt-1">{new Date(alert.timestamp).toLocaleTimeString()}</p>
    </div>
  </motion.div>
);

const StrategyCard = ({ strategy, onClick }) => {
  const categoryColors = {
    intraday: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    swing: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    investment: 'bg-green-500/20 text-green-400 border-green-500/30'
  };

  return (
    <Card onClick={onClick} className="group">
      <div className="flex items-start justify-between mb-3">
        <span className={`badge ${categoryColors[strategy.category]}`}>
          {strategy.category}
        </span>
        <span className="text-xs text-zinc-500 font-mono">{strategy.id}</span>
      </div>
      <h3 className="font-semibold mb-2 group-hover:text-primary transition-colors">
        {strategy.name}
      </h3>
      <div className="flex flex-wrap gap-1 mb-3">
        {strategy.indicators?.slice(0, 3).map((ind, idx) => (
          <span key={idx} className="text-xs bg-white/5 px-2 py-0.5 rounded text-zinc-400">
            {ind}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {strategy.timeframe}
        </span>
        <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
      </div>
    </Card>
  );
};

const WatchlistItem = ({ item, rank }) => (
  <div className="flex items-center gap-4 py-3 border-b border-white/5 last:border-0">
    <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center font-bold text-primary text-sm">
      {rank}
    </div>
    <div className="flex-1">
      <div className="flex items-center gap-2">
        <span className="font-bold">{item.symbol}</span>
        <PriceDisplay value={item.change_percent} className="text-sm" />
      </div>
      <p className="text-xs text-zinc-500">
        {item.matched_strategies?.length || 0} strategies matched
      </p>
    </div>
    <div className="text-right">
      <div className="flex items-center gap-1">
        <div className="w-16 h-2 bg-white/10 rounded-full overflow-hidden">
          <div 
            className="h-full bg-primary rounded-full transition-all"
            style={{ width: `${item.score}%` }}
          />
        </div>
        <span className="font-mono-data text-sm text-primary">{item.score}</span>
      </div>
    </div>
  </div>
);

// ===================== PAGES =====================

// Dashboard Page
const DashboardPage = ({ data, loading, onRefresh, streamingQuotes = {} }) => {
  const { stats, overview, alerts, watchlist } = data;

  const chartData = [
    { time: '9:30', value: 100 },
    { time: '10:00', value: 102 },
    { time: '10:30', value: 101 },
    { time: '11:00', value: 105 },
    { time: '11:30', value: 103 },
    { time: '12:00', value: 107 },
    { time: '12:30', value: 106 },
    { time: '13:00', value: 110 },
  ];

  // Merge streaming quotes with overview data
  const getUpdatedMover = (mover) => {
    const streamed = streamingQuotes[mover.symbol];
    return streamed ? { ...mover, ...streamed } : mover;
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <button 
          data-testid="refresh-dashboard"
          onClick={onRefresh}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard 
          icon={Briefcase}
          label="Portfolio Value"
          value={`$${stats?.portfolio_value?.toLocaleString() || '0'}`}
          change={stats?.portfolio_change}
          loading={loading}
        />
        <StatsCard 
          icon={Bell}
          label="Unread Alerts"
          value={stats?.unread_alerts || 0}
          loading={loading}
        />
        <StatsCard 
          icon={Eye}
          label="Watchlist"
          value={stats?.watchlist_count || 0}
          loading={loading}
        />
        <StatsCard 
          icon={Target}
          label="Active Strategies"
          value={stats?.strategies_count || 50}
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2" hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Market Performance</h2>
            <div className="flex gap-2">
              <button className="tab active">1D</button>
              <button className="tab">1W</button>
              <button className="tab">1M</button>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00E5FF" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#00E5FF" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" stroke="#52525B" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#52525B" fontSize={12} tickLine={false} axisLine={false} domain={['dataMin - 2', 'dataMax + 2']} />
                <Tooltip contentStyle={{ backgroundColor: '#0A0A0A', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }} />
                <Area type="monotone" dataKey="value" stroke="#00E5FF" strokeWidth={2} fillOpacity={1} fill="url(#colorValue)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Recent Alerts</h2>
            <span className="badge badge-info">{alerts?.length || 0}</span>
          </div>
          <div className="space-y-3 max-h-64 overflow-y-auto">
            <AnimatePresence>
              {alerts?.slice(0, 5).map((alert, idx) => (
                <AlertItem key={idx} alert={alert} />
              ))}
            </AnimatePresence>
            {(!alerts || alerts.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-8">No recent alerts</p>
            )}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Top Movers</h2>
            <BarChart3 className="w-5 h-5 text-zinc-500" />
          </div>
          <div className="space-y-2">
            {overview?.top_movers?.map((mover, idx) => (
              <div key={idx} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <div className="flex items-center gap-3">
                  <span className="font-bold">{getUpdatedMover(mover).symbol}</span>
                  <span className="font-mono-data text-zinc-400 transition-all">${getUpdatedMover(mover).price?.toFixed(2)}</span>
                </div>
                <PriceDisplay value={getUpdatedMover(mover).change_percent} />
              </div>
            ))}
            {(!overview?.top_movers || overview.top_movers.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-4">Loading movers...</p>
            )}
          </div>
        </Card>

        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Morning Watchlist</h2>
            <Eye className="w-5 h-5 text-zinc-500" />
          </div>
          <div className="space-y-1">
            {watchlist?.slice(0, 5).map((item, idx) => (
              <WatchlistItem key={idx} item={item} rank={idx + 1} />
            ))}
            {(!watchlist || watchlist.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-4">Generate watchlist to see picks</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

// Charts Page with TradingView
const ChartsPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [quote, setQuote] = useState(null);

  useEffect(() => {
    loadQuote();
  }, [symbol]);

  const loadQuote = async () => {
    try {
      const res = await api.get(`/api/quotes/${symbol}`);
      setQuote(res.data);
    } catch (err) {
      console.error('Failed to load quote:', err);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setSymbol(inputSymbol.toUpperCase());
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">TradingView Charts</h1>
          <p className="text-zinc-500 text-sm mt-1">Advanced technical analysis</p>
        </div>
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            data-testid="chart-symbol-input"
            type="text"
            value={inputSymbol}
            onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
            placeholder="Enter symbol..."
            className="bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none w-32"
          />
          <button type="submit" className="btn-primary">Load</button>
        </form>
      </div>

      {/* Quote Header */}
      {quote && (
        <Card hover={false} className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div>
              <h2 className="text-2xl font-bold">{quote.symbol}</h2>
              <p className="text-zinc-500 text-sm">Real-time quote</p>
            </div>
            <div className="border-l border-white/10 pl-6">
              <p className="text-3xl font-bold font-mono-data">${quote.price?.toFixed(2)}</p>
              <PriceDisplay value={quote.change_percent} className="text-lg" />
            </div>
          </div>
          <div className="flex gap-8 text-sm">
            <div>
              <p className="text-zinc-500">Open</p>
              <p className="font-mono-data">${quote.open?.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-zinc-500">High</p>
              <p className="font-mono-data text-green-400">${quote.high?.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-zinc-500">Low</p>
              <p className="font-mono-data text-red-400">${quote.low?.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-zinc-500">Volume</p>
              <p className="font-mono-data">{(quote.volume / 1000000).toFixed(2)}M</p>
            </div>
          </div>
        </Card>
      )}

      {/* TradingView Chart */}
      <Card hover={false} className="h-[600px]">
        <TradingViewWidget symbol={symbol} theme="dark" />
      </Card>
    </div>
  );
};

// Fundamentals Page
const FundamentalsPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadFundamentals();
  }, [symbol]);

  const loadFundamentals = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/api/fundamentals/${symbol}`);
      setData(res.data);
    } catch (err) {
      console.error('Failed to load fundamentals:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setSymbol(inputSymbol.toUpperCase());
  };

  const formatNumber = (num, type = 'number') => {
    if (num === null || num === undefined) return 'N/A';
    if (type === 'currency') return `$${(num / 1000000000).toFixed(2)}B`;
    if (type === 'percent') return `${(num * 100).toFixed(2)}%`;
    if (type === 'ratio') return num.toFixed(2);
    return num.toLocaleString();
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Fundamental Analysis</h1>
          <p className="text-zinc-500 text-sm mt-1">Yahoo Finance data</p>
        </div>
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            data-testid="fundamentals-symbol-input"
            type="text"
            value={inputSymbol}
            onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
            placeholder="Enter symbol..."
            className="bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none w-32"
          />
          <button type="submit" className="btn-primary">Analyze</button>
        </form>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-48" />)}
        </div>
      ) : data ? (
        <>
          {/* Company Header */}
          <Card hover={false}>
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-2xl font-bold">{data.company_name || symbol}</h2>
                <div className="flex gap-2 mt-2">
                  <span className="badge badge-info">{data.sector}</span>
                  <span className="badge bg-white/10 text-zinc-300">{data.industry}</span>
                </div>
              </div>
              <div className="text-right">
                <p className="text-zinc-500 text-sm">Market Cap</p>
                <p className="text-2xl font-bold font-mono-data text-primary">
                  {formatNumber(data.market_cap, 'currency')}
                </p>
              </div>
            </div>
            {data.description && (
              <p className="text-zinc-400 text-sm mt-4 line-clamp-3">{data.description}</p>
            )}
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Valuation */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Valuation</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">P/E Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.pe_ratio, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Forward P/E</span>
                  <span className="font-mono-data">{formatNumber(data.forward_pe, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">PEG Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.peg_ratio, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">P/B Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.price_to_book, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">P/S Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.price_to_sales, 'ratio')}</span>
                </div>
              </div>
            </Card>

            {/* Profitability */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Profitability</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Profit Margin</span>
                  <span className="font-mono-data text-green-400">{formatNumber(data.profit_margin, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Operating Margin</span>
                  <span className="font-mono-data">{formatNumber(data.operating_margin, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">ROE</span>
                  <span className="font-mono-data">{formatNumber(data.roe, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">ROA</span>
                  <span className="font-mono-data">{formatNumber(data.roa, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">EPS</span>
                  <span className="font-mono-data">${data.eps?.toFixed(2) || 'N/A'}</span>
                </div>
              </div>
            </Card>

            {/* Growth */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Growth</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Revenue Growth</span>
                  <span className={`font-mono-data ${data.revenue_growth > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatNumber(data.revenue_growth, 'percent')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Earnings Growth</span>
                  <span className={`font-mono-data ${data.earnings_growth > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatNumber(data.earnings_growth, 'percent')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Revenue</span>
                  <span className="font-mono-data">{formatNumber(data.revenue, 'currency')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">EBITDA</span>
                  <span className="font-mono-data">{formatNumber(data.ebitda, 'currency')}</span>
                </div>
              </div>
            </Card>

            {/* Financial Health */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Financial Health</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Debt/Equity</span>
                  <span className="font-mono-data">{formatNumber(data.debt_to_equity, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Current Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.current_ratio, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Quick Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.quick_ratio, 'ratio')}</span>
                </div>
              </div>
            </Card>

            {/* Dividends */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Dividends</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Dividend Yield</span>
                  <span className="font-mono-data text-green-400">{formatNumber(data.dividend_yield, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Dividend Rate</span>
                  <span className="font-mono-data">${data.dividend_rate?.toFixed(2) || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Payout Ratio</span>
                  <span className="font-mono-data">{formatNumber(data.payout_ratio, 'percent')}</span>
                </div>
              </div>
            </Card>

            {/* Trading Info */}
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Trading Info</h3>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Beta</span>
                  <span className="font-mono-data">{formatNumber(data.beta, 'ratio')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">52W High</span>
                  <span className="font-mono-data text-green-400">${data.fifty_two_week_high?.toFixed(2) || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">52W Low</span>
                  <span className="font-mono-data text-red-400">${data.fifty_two_week_low?.toFixed(2) || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Short %</span>
                  <span className="font-mono-data">{formatNumber(data.short_percent, 'percent')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Avg Volume</span>
                  <span className="font-mono-data">{(data.avg_volume / 1000000).toFixed(2)}M</span>
                </div>
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
};

// Insider Trading Page
const InsiderTradingPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [data, setData] = useState(null);
  const [unusualActivity, setUnusualActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('symbol');

  useEffect(() => {
    if (activeTab === 'symbol') {
      loadInsiderTrades();
    } else {
      loadUnusualActivity();
    }
  }, [symbol, activeTab]);

  const loadInsiderTrades = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/api/insider/${symbol}`);
      setData(res.data);
    } catch (err) {
      console.error('Failed to load insider trades:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadUnusualActivity = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/insider/unusual');
      setUnusualActivity(res.data.all_activity || []);
    } catch (err) {
      console.error('Failed to load unusual activity:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setSymbol(inputSymbol.toUpperCase());
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Insider Trading</h1>
          <p className="text-zinc-500 text-sm mt-1">Track unusual insider buying/selling activity</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveTab('symbol')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'symbol' ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
          }`}
        >
          By Symbol
        </button>
        <button
          onClick={() => setActiveTab('unusual')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'unusual' ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
          }`}
        >
          Unusual Activity
        </button>
      </div>

      {activeTab === 'symbol' ? (
        <>
          {/* Symbol Search */}
          <Card hover={false}>
            <form onSubmit={handleSubmit} className="flex gap-4 items-end">
              <div className="flex-1">
                <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbol</label>
                <input
                  data-testid="insider-symbol-input"
                  type="text"
                  value={inputSymbol}
                  onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                  placeholder="AAPL"
                  className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                />
              </div>
              <button type="submit" className="btn-primary">Search</button>
            </form>
          </Card>

          {/* Summary */}
          {data?.summary && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <Card hover={false} className={`border-l-4 ${data.summary.signal === 'BULLISH' ? 'border-l-green-500' : 'border-l-red-500'}`}>
                <p className="text-xs text-zinc-500 uppercase">Signal</p>
                <p className={`text-2xl font-bold ${data.summary.signal === 'BULLISH' ? 'text-green-400' : 'text-red-400'}`}>
                  {data.summary.signal}
                </p>
              </Card>
              <Card hover={false}>
                <p className="text-xs text-zinc-500 uppercase">Total Buys</p>
                <p className="text-2xl font-bold font-mono-data text-green-400">
                  ${(data.summary.total_buys / 1000000).toFixed(2)}M
                </p>
                <p className="text-xs text-zinc-500">{data.summary.buy_count} transactions</p>
              </Card>
              <Card hover={false}>
                <p className="text-xs text-zinc-500 uppercase">Total Sells</p>
                <p className="text-2xl font-bold font-mono-data text-red-400">
                  ${(data.summary.total_sells / 1000000).toFixed(2)}M
                </p>
                <p className="text-xs text-zinc-500">{data.summary.sell_count} transactions</p>
              </Card>
              <Card hover={false}>
                <p className="text-xs text-zinc-500 uppercase">Net Activity</p>
                <p className={`text-2xl font-bold font-mono-data ${data.summary.net_activity >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${(Math.abs(data.summary.net_activity) / 1000000).toFixed(2)}M
                </p>
              </Card>
            </div>
          )}

          {/* Trades Table */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4">Recent Insider Transactions</h2>
            {loading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Insider</th>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Shares</th>
                      <th>Price</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data?.trades?.map((trade, idx) => (
                      <tr key={idx}>
                        <td>{trade.date}</td>
                        <td className="font-medium">{trade.insider_name}</td>
                        <td className="text-zinc-400">{trade.title}</td>
                        <td>
                          <span className={`badge ${trade.transaction_type === 'Buy' ? 'badge-success' : 'badge-error'}`}>
                            {trade.transaction_type}
                          </span>
                        </td>
                        <td>{trade.shares.toLocaleString()}</td>
                        <td>${trade.price.toFixed(2)}</td>
                        <td className="font-mono-data">${(trade.value / 1000).toFixed(0)}K</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      ) : (
        /* Unusual Activity Tab */
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Stocks with Unusual Insider Activity</h2>
          {loading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Signal</th>
                    <th>Net Activity</th>
                    <th>Buy Ratio</th>
                    <th>Buys</th>
                    <th>Sells</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {unusualActivity.map((item, idx) => (
                    <tr key={idx}>
                      <td className="font-bold text-primary">{item.symbol}</td>
                      <td>
                        <span className={`badge ${item.signal === 'BULLISH' ? 'badge-success' : 'badge-error'}`}>
                          {item.signal}
                        </span>
                      </td>
                      <td className={`font-mono-data ${item.net_activity >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${(Math.abs(item.net_activity) / 1000000).toFixed(2)}M
                      </td>
                      <td className="font-mono-data">{(item.buy_ratio * 100).toFixed(0)}%</td>
                      <td className="text-green-400">{item.buy_count}</td>
                      <td className="text-red-400">{item.sell_count}</td>
                      <td>
                        {item.is_unusual && (
                          <span className="badge bg-yellow-500/20 text-yellow-400 border-yellow-500/30">
                            UNUSUAL
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
};

// COT Data Page
const COTDataPage = () => {
  const [market, setMarket] = useState('ES');
  const [data, setData] = useState([]);
  const [summary, setSummary] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('summary');

  const markets = [
    { code: 'ES', name: 'E-Mini S&P 500' },
    { code: 'NQ', name: 'E-Mini NASDAQ' },
    { code: 'GC', name: 'Gold' },
    { code: 'SI', name: 'Silver' },
    { code: 'CL', name: 'Crude Oil' },
    { code: 'NG', name: 'Natural Gas' },
    { code: 'ZB', name: 'US Treasury Bonds' },
    { code: '6E', name: 'Euro FX' },
  ];

  useEffect(() => {
    if (activeTab === 'summary') {
      loadSummary();
    } else {
      loadCOTData();
    }
  }, [market, activeTab]);

  const loadCOTData = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/api/cot/${market}`);
      setData(res.data.data || []);
    } catch (err) {
      console.error('Failed to load COT data:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadSummary = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/cot/summary');
      setSummary(res.data.summary || []);
    } catch (err) {
      console.error('Failed to load COT summary:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Commitment of Traders</h1>
          <p className="text-zinc-500 text-sm mt-1">CFTC COT Report - Commercial & Speculator Positions</p>
        </div>
      </div>

      {/* Info Banner */}
      <Card hover={false} className="bg-blue-500/10 border-blue-500/30">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-blue-400 mt-0.5" />
          <div>
            <p className="text-blue-400 font-medium">Understanding COT Data</p>
            <p className="text-zinc-400 text-sm mt-1">
              <strong>Commercials</strong> (hedgers) are often considered "smart money". 
              <strong> Non-Commercials</strong> (speculators) tend to follow trends. 
              When these groups diverge significantly, it can signal potential reversals.
            </p>
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveTab('summary')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'summary' ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
          }`}
        >
          Market Summary
        </button>
        <button
          onClick={() => setActiveTab('detail')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'detail' ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
          }`}
        >
          Detailed View
        </button>
      </div>

      {activeTab === 'summary' ? (
        /* Summary View */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {loading ? (
            [...Array(6)].map((_, i) => <Skeleton key={i} className="h-40" />)
          ) : (
            summary.map((item, idx) => (
              <Card key={idx} hover={false}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">{item.market}</h3>
                  <span className="text-xs text-zinc-500">{item.date}</span>
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400 text-sm">Commercial</span>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono-data ${item.commercial_net >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {item.commercial_net >= 0 ? '+' : ''}{(item.commercial_net / 1000).toFixed(0)}K
                      </span>
                      <span className={`badge ${item.commercial_sentiment === 'BULLISH' ? 'badge-success' : 'badge-error'}`}>
                        {item.commercial_sentiment}
                      </span>
                    </div>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400 text-sm">Speculator</span>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono-data ${item.speculator_net >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {item.speculator_net >= 0 ? '+' : ''}{(item.speculator_net / 1000).toFixed(0)}K
                      </span>
                      <span className={`badge ${item.speculator_sentiment === 'BULLISH' ? 'badge-success' : 'badge-error'}`}>
                        {item.speculator_sentiment}
                      </span>
                    </div>
                  </div>
                  <div className="pt-2 border-t border-white/5 flex justify-between text-xs">
                    <span className="text-zinc-500">Weekly Change</span>
                    <span className={`font-mono-data ${item.commercial_change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {item.commercial_change >= 0 ? '+' : ''}{(item.commercial_change / 1000).toFixed(0)}K
                    </span>
                  </div>
                </div>
              </Card>
            ))
          )}
        </div>
      ) : (
        /* Detailed View */
        <>
          <Card hover={false}>
            <div className="flex flex-wrap gap-2">
              {markets.map((m) => (
                <button
                  key={m.code}
                  onClick={() => setMarket(m.code)}
                  className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                    market === m.code ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'
                  }`}
                >
                  {m.code} - {m.name}
                </button>
              ))}
            </div>
          </Card>

          <Card hover={false}>
            <h2 className="font-semibold mb-4">{market} - Historical COT Data</h2>
            {loading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Comm. Long</th>
                      <th>Comm. Short</th>
                      <th>Comm. Net</th>
                      <th>Spec. Long</th>
                      <th>Spec. Short</th>
                      <th>Spec. Net</th>
                      <th>Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((row, idx) => (
                      <tr key={idx}>
                        <td>{row.date}</td>
                        <td className="text-green-400">{(row.commercial_long / 1000).toFixed(0)}K</td>
                        <td className="text-red-400">{(row.commercial_short / 1000).toFixed(0)}K</td>
                        <td className={row.commercial_net >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {(row.commercial_net / 1000).toFixed(0)}K
                        </td>
                        <td className="text-green-400">{(row.non_commercial_long / 1000).toFixed(0)}K</td>
                        <td className="text-red-400">{(row.non_commercial_short / 1000).toFixed(0)}K</td>
                        <td className={row.non_commercial_net >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {(row.non_commercial_net / 1000).toFixed(0)}K
                        </td>
                        <td>
                          <span className={`badge ${row.commercial_sentiment === 'BULLISH' ? 'badge-success' : 'badge-error'}`}>
                            {row.commercial_sentiment}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
};

// Scanner Page
const ScannerPage = () => {
  const [symbols, setSymbols] = useState('AAPL, MSFT, GOOGL, NVDA, TSLA, AMD');
  const [minScore, setMinScore] = useState(40);
  const [category, setCategory] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [presets, setPresets] = useState([]);

  useEffect(() => { loadPresets(); }, []);

  const loadPresets = async () => {
    try {
      const res = await api.get('/api/scanner/presets');
      setPresets(res.data.presets);
    } catch (err) { console.error('Failed to load presets:', err); }
  };

  const runScan = async () => {
    setLoading(true);
    try {
      const symbolList = symbols.split(',').map(s => s.trim().toUpperCase());
      const res = await api.post('/api/scanner/scan', symbolList, {
        params: { category: category || undefined, min_score: minScore }
      });
      setResults(res.data.results);
    } catch (err) { console.error('Scan failed:', err); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategy Scanner</h1>
          <p className="text-zinc-500 text-sm mt-1">Scan stocks against strategy criteria</p>
        </div>
      </div>

      <Card hover={false}>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-2">
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbols</label>
            <input
              data-testid="scanner-symbols-input"
              type="text"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="AAPL, MSFT, GOOGL..."
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white focus:border-primary/50 focus:outline-none"
            >
              <option value="">All Strategies</option>
              <option value="intraday">Intraday</option>
              <option value="swing">Swing</option>
              <option value="investment">Investment</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Min Score: {minScore}</label>
            <input type="range" min="0" max="100" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="w-full" />
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
          {presets.map((preset, idx) => (
            <button key={idx} onClick={() => { setSymbols(preset.symbols.join(', ')); setMinScore(preset.min_score); }}
              className="text-xs bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-full text-zinc-400 hover:text-white transition-colors">
              {preset.name}
            </button>
          ))}
        </div>
        <button data-testid="run-scanner-btn" onClick={runScan} disabled={loading} className="btn-primary mt-4 flex items-center gap-2">
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? 'Scanning...' : 'Run Scanner'}
        </button>
      </Card>

      {results.length > 0 && (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Scan Results ({results.length})</h2>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th>Symbol</th><th>Score</th><th>Price</th><th>Change</th><th>Volume</th><th>Strategies</th></tr></thead>
              <tbody>
                {results.map((result, idx) => (
                  <tr key={idx}>
                    <td className="font-bold text-primary">{result.symbol}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-2 bg-white/10 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${result.score >= 70 ? 'bg-green-400' : result.score >= 50 ? 'bg-yellow-400' : 'bg-blue-400'}`} style={{ width: `${result.score}%` }} />
                        </div>
                        <span>{result.score}</span>
                      </div>
                    </td>
                    <td>${result.quote?.price?.toFixed(2)}</td>
                    <td><PriceDisplay value={result.quote?.change_percent} /></td>
                    <td>{(result.quote?.volume / 1000000).toFixed(2)}M</td>
                    <td>
                      <div className="flex gap-1">
                        {result.matched_strategies?.slice(0, 3).map((s, i) => (<span key={i} className="badge badge-info">{s}</span>))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};

// Strategies Page
const StrategiesPage = () => {
  const [strategies, setStrategies] = useState([]);
  const [filter, setFilter] = useState('all');
  const [selectedStrategy, setSelectedStrategy] = useState(null);

  useEffect(() => { loadStrategies(); }, [filter]);

  const loadStrategies = async () => {
    try {
      const params = filter !== 'all' ? { category: filter } : {};
      const res = await api.get('/api/strategies', { params });
      setStrategies(res.data.strategies);
    } catch (err) { console.error('Failed to load strategies:', err); }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="text-2xl font-bold">Trading Strategies</h1>
      <div className="flex flex-wrap gap-2">
        {['all', 'intraday', 'swing', 'investment'].map((cat) => (
          <button key={cat} onClick={() => setFilter(cat)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${filter === cat ? 'bg-primary text-black' : 'bg-white/5 text-zinc-400 hover:bg-white/10'}`}>
            {cat.charAt(0).toUpperCase() + cat.slice(1)}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {strategies.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} onClick={() => setSelectedStrategy(strategy)} />
        ))}
      </div>
      <AnimatePresence>
        {selectedStrategy && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setSelectedStrategy(null)}>
            <motion.div initial={{ scale: 0.95 }} animate={{ scale: 1 }} exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-2xl w-full p-6" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold">{selectedStrategy.name}</h2>
                  <p className="text-zinc-500 text-sm">{selectedStrategy.id}</p>
                </div>
                <button onClick={() => setSelectedStrategy(null)} className="text-zinc-500 hover:text-white"><X className="w-6 h-6" /></button>
              </div>
              <div>
                <h3 className="text-sm text-zinc-500 uppercase mb-3">Criteria</h3>
                <ul className="space-y-2">
                  {selectedStrategy.criteria?.map((c, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <div className="w-1.5 h-1.5 rounded-full bg-primary mt-2" />
                      <span className="text-zinc-300">{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// Watchlist, Portfolio, Alerts, Newsletter Pages (simplified for brevity)
const WatchlistPage = () => {
  const [watchlist, setWatchlist] = useState([]);
  const [aiInsight, setAiInsight] = useState('');
  const [generating, setGenerating] = useState(false);

  useEffect(() => { api.get('/api/watchlist').then(res => setWatchlist(res.data.watchlist)).catch(() => {}); }, []);

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await api.post('/api/watchlist/generate');
      setWatchlist(res.data.watchlist);
      setAiInsight(res.data.ai_insight);
    } catch (err) {} finally { setGenerating(false); }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Morning Watchlist</h1>
        <button data-testid="generate-watchlist-btn" onClick={generate} disabled={generating} className="btn-primary flex items-center gap-2">
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          {generating ? 'Generating...' : 'Generate'}
        </button>
      </div>
      {aiInsight && <Card hover={false} className="bg-primary/5 border-primary/20"><p className="text-zinc-300">{aiInsight}</p></Card>}
      <Card hover={false}>
        {watchlist.length > 0 ? watchlist.map((item, idx) => <WatchlistItem key={idx} item={item} rank={idx + 1} />) : <p className="text-zinc-500 text-center py-8">Click Generate to create watchlist</p>}
      </Card>
    </div>
  );
};

const PortfolioPage = () => {
  const [portfolio, setPortfolio] = useState({ positions: [], summary: {} });
  const [showAddModal, setShowAddModal] = useState(false);
  const [newPos, setNewPos] = useState({ symbol: '', shares: '', avg_cost: '' });

  useEffect(() => { loadPortfolio(); }, []);
  const loadPortfolio = () => api.get('/api/portfolio').then(res => setPortfolio(res.data)).catch(() => {});
  const addPosition = async () => {
    await api.post('/api/portfolio/add', null, { params: { symbol: newPos.symbol.toUpperCase(), shares: parseFloat(newPos.shares), avg_cost: parseFloat(newPos.avg_cost) } });
    setShowAddModal(false); setNewPos({ symbol: '', shares: '', avg_cost: '' }); loadPortfolio();
  };
  const removePosition = async (s) => { await api.delete(`/api/portfolio/${s}`); loadPortfolio(); };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <button data-testid="add-position-btn" onClick={() => setShowAddModal(true)} className="btn-primary flex items-center gap-2"><Plus className="w-4 h-4" /> Add</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard icon={Briefcase} label="Total Value" value={`$${portfolio.summary?.total_value?.toLocaleString() || '0'}`} />
        <StatsCard icon={TrendingUp} label="Total Cost" value={`$${portfolio.summary?.total_cost?.toLocaleString() || '0'}`} />
        <StatsCard icon={Activity} label="Gain/Loss" value={`$${portfolio.summary?.total_gain_loss?.toLocaleString() || '0'}`} change={portfolio.summary?.total_gain_loss_percent} />
        <StatsCard icon={Target} label="Positions" value={portfolio.positions?.length || 0} />
      </div>
      <Card hover={false}>
        {portfolio.positions?.length > 0 ? (
          <table className="data-table">
            <thead><tr><th>Symbol</th><th>Shares</th><th>Avg Cost</th><th>Current</th><th>Value</th><th>P&L</th><th></th></tr></thead>
            <tbody>
              {portfolio.positions.map((p, i) => (
                <tr key={i}><td className="font-bold text-primary">{p.symbol}</td><td>{p.shares}</td><td>${p.avg_cost?.toFixed(2)}</td><td>${p.current_price?.toFixed(2)}</td><td>${p.market_value?.toLocaleString()}</td><td><PriceDisplay value={p.gain_loss_percent} /></td><td><button onClick={() => removePosition(p.symbol)} className="text-zinc-500 hover:text-red-400"><Trash2 className="w-4 h-4" /></button></td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-zinc-500 text-center py-8">No positions</p>}
      </Card>
      <AnimatePresence>
        {showAddModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4" onClick={() => setShowAddModal(false)}>
            <motion.div initial={{ scale: 0.95 }} animate={{ scale: 1 }} className="bg-paper border border-white/10 rounded-xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
              <h2 className="text-xl font-bold mb-6">Add Position</h2>
              <div className="space-y-4">
                <input data-testid="add-position-symbol" type="text" value={newPos.symbol} onChange={(e) => setNewPos({ ...newPos, symbol: e.target.value })} placeholder="Symbol" className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white" />
                <input type="number" value={newPos.shares} onChange={(e) => setNewPos({ ...newPos, shares: e.target.value })} placeholder="Shares" className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white" />
                <input type="number" step="0.01" value={newPos.avg_cost} onChange={(e) => setNewPos({ ...newPos, avg_cost: e.target.value })} placeholder="Avg Cost" className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white" />
              </div>
              <div className="flex gap-3 mt-6">
                <button onClick={() => setShowAddModal(false)} className="btn-secondary flex-1">Cancel</button>
                <button onClick={addPosition} className="btn-primary flex-1">Add</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const AlertsPage = () => {
  const [alerts, setAlerts] = useState([]);
  const [generating, setGenerating] = useState(false);

  useEffect(() => { api.get('/api/alerts').then(res => setAlerts(res.data.alerts)).catch(() => {}); }, []);
  const generate = async () => { setGenerating(true); await api.post('/api/alerts/generate'); const res = await api.get('/api/alerts'); setAlerts(res.data.alerts); setGenerating(false); };
  const clear = async () => { await api.delete('/api/alerts/clear'); setAlerts([]); };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Alert Center</h1>
        <div className="flex gap-2">
          <button onClick={generate} disabled={generating} className="btn-primary flex items-center gap-2">{generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />} Generate</button>
          <button onClick={clear} className="btn-secondary">Clear</button>
        </div>
      </div>
      <Card hover={false}>
        {alerts.length > 0 ? <div className="space-y-3">{alerts.map((a, i) => <AlertItem key={i} alert={a} />)}</div> : <p className="text-zinc-500 text-center py-8">No alerts</p>}
      </Card>
    </div>
  );
};

const NewsletterPage = () => {
  const [newsletter, setNewsletter] = useState(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => { api.get('/api/newsletter/latest').then(res => { if (res.data.title) setNewsletter(res.data); }).catch(() => {}); }, []);
  const generate = async () => { setGenerating(true); const res = await api.post('/api/newsletter/generate'); setNewsletter(res.data); setGenerating(false); };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Morning Newsletter</h1>
        <button onClick={generate} disabled={generating} className="btn-primary flex items-center gap-2">{generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Newspaper className="w-4 h-4" />} {generating ? 'Generating...' : 'Generate'}</button>
      </div>
      {newsletter ? (
        <div className="max-w-3xl mx-auto">
          <Card hover={false} className="text-center py-8">
            <h2 className="text-3xl font-editorial font-bold">{newsletter.title}</h2>
            <p className="text-zinc-500 mt-2"><Calendar className="w-4 h-4 inline mr-1" />{new Date(newsletter.created_at).toLocaleDateString()}</p>
          </Card>
          <Card hover={false} className="mt-6">
            <h3 className="text-sm text-zinc-500 uppercase mb-4">Market Summary</h3>
            <p className="text-zinc-300 whitespace-pre-line font-editorial">{newsletter.market_summary}</p>
          </Card>
        </div>
      ) : <Card hover={false}><p className="text-zinc-500 text-center py-8">Click Generate to create newsletter</p></Card>}
    </div>
  );
};

// ===================== MAIN APP =====================
function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [dashboardData, setDashboardData] = useState({ stats: {}, overview: {}, alerts: [], watchlist: [] });
  const [loading, setLoading] = useState(true);
  const [streamingQuotes, setStreamingQuotes] = useState({});

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
    <div className="min-h-screen bg-background bg-gradient-radial">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
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
