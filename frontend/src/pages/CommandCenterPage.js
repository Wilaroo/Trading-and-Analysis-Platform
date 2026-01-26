import React, { useState, useEffect, useRef, useMemo } from 'react';
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
  Star
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';

// ===================== UTILITY FUNCTIONS =====================
const formatPrice = (price) => {
  if (price === undefined || price === null) return '--';
  return Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatPercent = (pct) => {
  if (pct === undefined || pct === null) return '--';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
};

const formatVolume = (vol) => {
  if (!vol) return '--';
  if (vol >= 1000000) return `${(vol / 1000000).toFixed(1)}M`;
  if (vol >= 1000) return `${(vol / 1000).toFixed(1)}K`;
  return vol.toString();
};

const formatCurrency = (val) => {
  if (!val && val !== 0) return '$--';
  return `$${Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

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

    const lineSeries = chart.addLineSeries({
      color: data[data.length - 1]?.close >= data[0]?.close ? '#00FF94' : '#FF2E2E',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const chartData = data.map(bar => ({
      time: new Date(bar.date).getTime() / 1000,
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

// ===================== TICKER DETAIL MODAL =====================
const TickerDetailModal = ({ ticker, onClose, onTrade }) => {
  const [historicalData, setHistoricalData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('chart');
  const [news, setNews] = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!ticker?.symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      try {
        const histResponse = await api.get(`/api/ib/historical/${ticker.symbol}?duration=1 D&bar_size=5 mins`);
        setHistoricalData(histResponse.data?.bars || []);
      } catch (err) {
        console.error('Error fetching historical data:', err);
      }
      setLoading(false);
    };
    
    fetchData();
  }, [ticker?.symbol]);

  // Fetch news when tab changes
  useEffect(() => {
    if (activeTab !== 'news' || !ticker?.symbol) return;
    
    const fetchNews = async () => {
      setNewsLoading(true);
      try {
        const res = await api.get(`/api/newsletter/news/${ticker.symbol}`);
        setNews(res.data?.news || []);
      } catch (err) {
        console.error('Error fetching news:', err);
      }
      setNewsLoading(false);
    };
    
    fetchNews();
  }, [activeTab, ticker?.symbol]);

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current || !historicalData || historicalData.length === 0 || activeTab !== 'chart') return;

    const chart = LightweightCharts.createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 300,
      layout: {
        background: { type: 'solid', color: '#0A0A0A' },
        textColor: '#71717a',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#00FF94',
      downColor: '#FF2E2E',
      borderUpColor: '#00FF94',
      borderDownColor: '#FF2E2E',
      wickUpColor: '#00FF94',
      wickDownColor: '#FF2E2E',
    });

    const chartData = historicalData.map(bar => ({
      time: new Date(bar.date).getTime() / 1000,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    candlestickSeries.setData(chartData);
    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => chart.remove();
  }, [historicalData, activeTab]);

  if (!ticker) return null;

  const quote = ticker.quote || ticker;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-3xl max-h-[85vh] overflow-hidden rounded-lg"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10">
            <div className="flex items-center gap-4">
              <span className="text-2xl font-bold text-white">{ticker.symbol}</span>
              <span className="text-xl font-mono text-white">${formatPrice(quote?.price)}</span>
              <span className={`flex items-center gap-1 font-mono ${
                quote?.change_percent >= 0 ? 'text-green-400' : 'text-red-400'
              }`}>
                {quote?.change_percent >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                {formatPercent(quote?.change_percent)}
              </span>
            </div>
            <button onClick={onClose} className="p-2 rounded hover:bg-white/10 text-zinc-400">
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-white/10">
            {['chart', 'stats', 'news'].map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-medium capitalize ${
                  activeTab === tab ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-zinc-400 hover:text-white'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="p-4 overflow-y-auto max-h-[55vh]">
            {activeTab === 'chart' && (
              <div>
                {loading ? (
                  <div className="h-[300px] flex items-center justify-center">
                    <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
                  </div>
                ) : (
                  <div ref={chartContainerRef} className="w-full h-[300px]" />
                )}
              </div>
            )}

            {activeTab === 'stats' && (
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">Volume</span>
                  <p className="text-lg font-mono text-white">{formatVolume(quote?.volume)}</p>
                </div>
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">High</span>
                  <p className="text-lg font-mono text-white">${formatPrice(quote?.high)}</p>
                </div>
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">Low</span>
                  <p className="text-lg font-mono text-white">${formatPrice(quote?.low)}</p>
                </div>
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">Open</span>
                  <p className="text-lg font-mono text-white">${formatPrice(quote?.open)}</p>
                </div>
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">Prev Close</span>
                  <p className="text-lg font-mono text-white">${formatPrice(quote?.prev_close)}</p>
                </div>
                <div className="bg-zinc-900 rounded p-3">
                  <span className="text-xs text-zinc-500">RVOL</span>
                  <p className="text-lg font-mono text-white">{ticker.features?.rvol?.toFixed(1) || '--'}x</p>
                </div>
              </div>
            )}

            {activeTab === 'news' && (
              <div className="space-y-3">
                {newsLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
                  </div>
                ) : news.length > 0 ? (
                  news.map((item, idx) => (
                    <div key={idx} className="bg-zinc-900 rounded p-3 border-l-2 border-cyan-500/50">
                      <p className="text-sm text-white mb-1">{item.headline}</p>
                      <div className="flex items-center gap-2 text-xs text-zinc-500">
                        <span>{item.source}</span>
                        {item.timestamp && (
                          <span>{new Date(item.timestamp).toLocaleTimeString()}</span>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8 text-zinc-500">
                    <Newspaper className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>No recent news</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 p-4 border-t border-white/10">
            <button 
              onClick={() => onTrade(ticker, 'BUY')}
              className="flex-1 py-2 text-sm font-bold bg-green-500 text-black rounded hover:bg-green-400"
            >
              Buy {ticker.symbol}
            </button>
            <button 
              onClick={() => onTrade(ticker, 'SELL')}
              className="flex-1 py-2 text-sm font-bold bg-red-500 text-white rounded hover:bg-red-400"
            >
              Short {ticker.symbol}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

// ===================== QUICK TRADE MODAL =====================
const QuickTradeModal = ({ ticker, action, onClose, onSuccess }) => {
  const [quantity, setQuantity] = useState(10);
  const [orderType, setOrderType] = useState('MKT');
  const [limitPrice, setLimitPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const quote = ticker?.quote || ticker;
  const price = quote?.price || 0;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    
    try {
      const orderData = {
        symbol: ticker.symbol,
        action: action,
        quantity: quantity,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? parseFloat(limitPrice) : null
      };
      
      await api.post('/api/ib/order', orderData);
      onSuccess?.();
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to place order');
    }
    setSubmitting(false);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-md rounded-lg p-6"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold">
              {action === 'BUY' ? 'Buy' : 'Short'} {ticker?.symbol}
            </h3>
            <button onClick={onClose} className="text-zinc-400 hover:text-white">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs text-zinc-500 uppercase">Quantity</label>
              <div className="flex gap-2 mt-1">
                {[10, 50, 100, 500].map(q => (
                  <button
                    key={q}
                    onClick={() => setQuantity(q)}
                    className={`flex-1 py-2 rounded text-sm ${
                      quantity === q ? 'bg-cyan-500 text-black' : 'bg-zinc-800 text-white hover:bg-zinc-700'
                    }`}
                  >
                    {q}
                  </button>
                ))}
              </div>
              <input
                type="number"
                value={quantity}
                onChange={e => setQuantity(parseInt(e.target.value) || 0)}
                className="w-full mt-2 px-3 py-2 bg-zinc-900 border border-white/10 rounded text-white"
              />
            </div>

            <div>
              <label className="text-xs text-zinc-500 uppercase">Order Type</label>
              <div className="flex gap-2 mt-1">
                {['MKT', 'LMT'].map(type => (
                  <button
                    key={type}
                    onClick={() => setOrderType(type)}
                    className={`flex-1 py-2 rounded text-sm ${
                      orderType === type ? 'bg-cyan-500 text-black' : 'bg-zinc-800 text-white hover:bg-zinc-700'
                    }`}
                  >
                    {type === 'MKT' ? 'Market' : 'Limit'}
                  </button>
                ))}
              </div>
            </div>

            {orderType === 'LMT' && (
              <div>
                <label className="text-xs text-zinc-500 uppercase">Limit Price</label>
                <input
                  type="number"
                  step="0.01"
                  value={limitPrice}
                  onChange={e => setLimitPrice(e.target.value)}
                  placeholder={price.toFixed(2)}
                  className="w-full mt-1 px-3 py-2 bg-zinc-900 border border-white/10 rounded text-white"
                />
              </div>
            )}

            <div className="bg-zinc-900 rounded p-3">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-500">Est. {action === 'BUY' ? 'Cost' : 'Proceeds'}</span>
                <span className="text-white font-mono">
                  {formatCurrency(price * quantity)}
                </span>
              </div>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded p-3 text-red-400 text-sm">
                {error}
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={submitting || quantity <= 0}
              className={`w-full py-3 rounded font-bold text-sm ${
                action === 'BUY' 
                  ? 'bg-green-500 hover:bg-green-400 text-black' 
                  : 'bg-red-500 hover:bg-red-400 text-white'
              } disabled:opacity-50`}
            >
              {submitting ? 'Placing Order...' : `${action === 'BUY' ? 'Buy' : 'Short'} ${quantity} shares`}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

// ===================== MAIN COMMAND CENTER =====================
const CommandCenterPage = () => {
  // Connection & Loading State
  const [isConnected, setIsConnected] = useState(false);
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
  const [autoScan, setAutoScan] = useState(false);
  const [selectedScanType, setSelectedScanType] = useState('TOP_PERC_GAIN');
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [tradeModal, setTradeModal] = useState({ isOpen: false, ticker: null, action: null });
  const [expandedSections, setExpandedSections] = useState({
    holdings: true,
    opportunities: true,
    context: true,
    alerts: true,
    news: false,
    earnings: true
  });

  const scanTypes = [
    { id: 'TOP_PERC_GAIN', label: 'Top Gainers', icon: TrendingUp },
    { id: 'TOP_PERC_LOSE', label: 'Top Losers', icon: TrendingDown },
    { id: 'MOST_ACTIVE', label: 'Most Active', icon: Activity },
    { id: 'HIGH_OPEN_GAP', label: 'Gap Up', icon: ArrowUpRight },
    { id: 'LOW_OPEN_GAP', label: 'Gap Down', icon: ArrowDownRight },
  ];

  // Check IB connection
  const checkConnection = async () => {
    try {
      const res = await api.get('/api/ib/status');
      setIsConnected(res.data?.connected || false);
      return res.data?.connected;
    } catch {
      setIsConnected(false);
      return false;
    }
  };

  // Connect to IB
  const connectToIB = async () => {
    setConnecting(true);
    try {
      await api.post('/api/ib/connect');
      const connected = await checkConnection();
      if (connected) {
        await fetchAccountData();
        await fetchWatchlist(connected);
      }
    } catch (err) {
      console.error('Connection failed:', err);
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
      setOpportunities(res.data?.results || []);
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

  // Fetch newsletter
  const fetchNewsletter = async () => {
    try {
      const res = await api.get('/api/newsletter/latest');
      setNewsletter(res.data);
    } catch {
      setNewsletter(null);
    }
  };

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
      // Get earnings for next 7 days, sorted by date
      const upcoming = (res.data?.calendar || [])
        .filter(e => {
          const earningsDate = new Date(e.earnings_date);
          const today = new Date();
          const nextWeek = new Date();
          nextWeek.setDate(today.getDate() + 7);
          return earningsDate >= today && earningsDate <= nextWeek;
        })
        .slice(0, 10);
      setEarnings(upcoming);
    } catch {
      setEarnings([]);
    }
  };

  // Initial load
  useEffect(() => {
    const init = async () => {
      const connected = await checkConnection();
      if (connected) {
        await Promise.all([
          fetchAccountData(),
          fetchMarketContext(),
          runScanner(),
          fetchWatchlist(connected)
        ]);
      }
      fetchAlerts();
      fetchNewsletter();
      fetchEarnings();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scan interval
  useEffect(() => {
    if (!autoScan || !isConnected) return;
    
    const interval = setInterval(() => {
      runScanner();
      fetchAccountData();
      fetchMarketContext();
    }, 60000);
    
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScan, isConnected, selectedScanType]);

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
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
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Target className="w-7 h-7 text-cyan-400" />
            Command Center
          </h1>
          <p className="text-zinc-500 text-sm">Real-time trading intelligence hub</p>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Connection Status */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm ${
            isConnected ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
          }`}>
            {isConnected ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
            {isConnected ? 'Connected' : 'Disconnected'}
          </div>
          
          {!isConnected && (
            <button
              onClick={connectToIB}
              disabled={connecting}
              className="px-4 py-2 bg-cyan-500 text-black rounded font-medium text-sm hover:bg-cyan-400 disabled:opacity-50"
            >
              {connecting ? 'Connecting...' : 'Connect to IB'}
            </button>
          )}
          
          {/* Auto Scan Toggle */}
          {isConnected && (
            <button
              onClick={() => setAutoScan(!autoScan)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm ${
                autoScan ? 'bg-cyan-500/20 text-cyan-400' : 'bg-zinc-800 text-zinc-400'
              }`}
            >
              {autoScan ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              Auto-Scan
            </button>
          )}
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

      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-3 gap-4">
        {/* Left Column - Holdings & Watchlist */}
        <div className="lg:col-span-1 space-y-4">
          {/* Current Holdings */}
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
              <div className="space-y-2">
                {positions.length > 0 ? positions.map((pos, idx) => (
                  <div 
                    key={idx} 
                    className="flex items-center justify-between p-2 bg-zinc-900/50 rounded hover:bg-zinc-900 cursor-pointer"
                    onClick={() => setSelectedTicker({ symbol: pos.symbol, quote: { price: pos.avg_cost } })}
                  >
                    <div>
                      <span className="font-bold text-white">{pos.symbol}</span>
                      <span className="text-xs text-zinc-500 ml-2">{pos.quantity} shares</span>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono text-white">${formatPrice(pos.avg_cost)}</p>
                      <p className={`text-xs ${(pos.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {formatCurrency(pos.unrealized_pnl || 0)}
                      </p>
                    </div>
                  </div>
                )) : (
                  <p className="text-center text-zinc-500 text-sm py-4">No open positions</p>
                )}
              </div>
            )}
          </Card>

          {/* Watchlist */}
          <Card>
            <SectionHeader icon={Eye} title="Watchlist" count={watchlist.length} />
            <div className="space-y-2">
              {watchlist.length > 0 ? watchlist.slice(0, 8).map((item, idx) => (
                <div 
                  key={idx}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded hover:bg-zinc-900 cursor-pointer"
                  onClick={() => setSelectedTicker(item)}
                >
                  <span className="font-bold text-white">{item.symbol}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-mono text-white">${formatPrice(item.price)}</span>
                    <span className={`text-xs font-mono ${item.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(item.change_percent)}
                    </span>
                  </div>
                </div>
              )) : (
                <p className="text-center text-zinc-500 text-sm py-4">
                  {isConnected ? 'Loading watchlist...' : 'Connect to view watchlist'}
                </p>
              )}
            </div>
          </Card>

          {/* Recent Alerts */}
          <Card>
            <button 
              onClick={() => toggleSection('alerts')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Bell className="w-5 h-5 text-yellow-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Alerts</h3>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.alerts ? 'rotate-180' : ''}`} />
            </button>
            
            {expandedSections.alerts && (
              <div className="space-y-2">
                {alerts.length > 0 ? alerts.map((alert, idx) => (
                  <div key={idx} className="p-2 bg-zinc-900/50 rounded">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-bold text-cyan-400">{alert.symbol}</span>
                      <Badge variant="info">{alert.strategy_id}</Badge>
                    </div>
                    <p className="text-xs text-zinc-400">{alert.message || alert.strategy_name}</p>
                  </div>
                )) : (
                  <p className="text-center text-zinc-500 text-sm py-4">No recent alerts</p>
                )}
              </div>
            )}
          </Card>

          {/* Earnings Calendar */}
          <Card>
            <button 
              onClick={() => toggleSection('earnings')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Calendar className="w-5 h-5 text-orange-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Earnings</h3>
                <span className="text-xs text-zinc-500">({earnings.length})</span>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.earnings ? 'rotate-180' : ''}`} />
            </button>
            
            {expandedSections.earnings && (
              <div className="space-y-2">
                {earnings.length > 0 ? earnings.map((item, idx) => {
                  const earningsDate = new Date(item.earnings_date);
                  const today = new Date();
                  const isToday = earningsDate.toDateString() === today.toDateString();
                  const tomorrow = new Date();
                  tomorrow.setDate(today.getDate() + 1);
                  const isTomorrow = earningsDate.toDateString() === tomorrow.toDateString();
                  
                  // Catalyst score color
                  const getScoreColor = (score) => {
                    if (score >= 5) return 'text-green-400 bg-green-500/20';
                    if (score >= 0) return 'text-yellow-400 bg-yellow-500/20';
                    return 'text-red-400 bg-red-500/20';
                  };
                  
                  return (
                    <div 
                      key={idx} 
                      className={`p-2 rounded border-l-2 ${
                        isToday ? 'bg-orange-500/10 border-orange-500' : 
                        isTomorrow ? 'bg-yellow-500/5 border-yellow-500/50' : 
                        'bg-zinc-900/50 border-zinc-700'
                      }`}
                      onClick={() => setSelectedTicker({ symbol: item.symbol, quote: {} })}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white">{item.symbol}</span>
                          {isToday && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-orange-500/30 text-orange-400 rounded font-medium">
                              TODAY
                            </span>
                          )}
                          {isTomorrow && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded font-medium">
                              TOMORROW
                            </span>
                          )}
                        </div>
                        {item.catalyst_score !== undefined && (
                          <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${getScoreColor(item.catalyst_score.score)}`}>
                            <Star className="w-3 h-3 inline mr-0.5" />
                            {item.catalyst_score.score >= 0 ? '+' : ''}{item.catalyst_score.score}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-zinc-400">{item.company_name?.split(' ')[0] || item.symbol}</span>
                        <div className="flex items-center gap-2 text-zinc-500">
                          <span>{item.time === 'Before Open' ? '🌅 BMO' : '🌙 AMC'}</span>
                          <span>{earningsDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                        </div>
                      </div>
                      {item.expected_move && (
                        <div className="mt-1 text-[10px] text-zinc-500">
                          Expected Move: ±{item.expected_move.toFixed(1)}%
                        </div>
                      )}
                    </div>
                  );
                }) : (
                  <p className="text-center text-zinc-500 text-sm py-4">No upcoming earnings</p>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Center Column - Trade Opportunities */}
        <div className="lg:col-span-2 space-y-4">
          {/* Scanner Controls */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Search className="w-5 h-5 text-cyan-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Scanner</h3>
              </div>
              <button
                onClick={runScanner}
                disabled={!isConnected || isScanning}
                className="flex items-center gap-2 px-4 py-2 bg-cyan-500 text-black rounded font-medium text-sm hover:bg-cyan-400 disabled:opacity-50"
              >
                {isScanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                {isScanning ? 'Scanning...' : 'Scan Now'}
              </button>
            </div>
            
            <div className="flex flex-wrap gap-2">
              {scanTypes.map(scan => (
                <button
                  key={scan.id}
                  onClick={() => setSelectedScanType(scan.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                    selectedScanType === scan.id
                      ? 'bg-cyan-500 text-black'
                      : 'bg-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-700'
                  }`}
                >
                  <scan.icon className="w-3.5 h-3.5" />
                  {scan.label}
                </button>
              ))}
            </div>
          </Card>

          {/* Opportunities Grid */}
          <Card>
            <SectionHeader 
              icon={Zap} 
              title="Trade Opportunities" 
              count={opportunities.length}
              action={
                opportunities.length > 0 && (
                  <span className="text-xs text-zinc-500">
                    {opportunities.filter(o => o.high_conviction).length} high conviction
                  </span>
                )
              }
            />
            
            {!isConnected ? (
              <div className="text-center py-12">
                <WifiOff className="w-12 h-12 text-zinc-600 mx-auto mb-3" />
                <p className="text-zinc-400">Connect to IB Gateway to scan</p>
                <button
                  onClick={connectToIB}
                  className="mt-4 px-4 py-2 bg-cyan-500 text-black rounded font-medium text-sm"
                >
                  Connect Now
                </button>
              </div>
            ) : opportunities.length === 0 ? (
              <div className="text-center py-12">
                <Search className="w-12 h-12 text-zinc-600 mx-auto mb-3" />
                <p className="text-zinc-400">No opportunities found</p>
                <p className="text-zinc-500 text-sm mt-1">Run a scan to find trade setups</p>
              </div>
            ) : (
              <div className="grid md:grid-cols-2 gap-3 max-h-[500px] overflow-y-auto">
                {opportunities.map((opp, idx) => {
                  const quote = opp.quote || opp;
                  const isHighConviction = opp.high_conviction || (opp.conviction?.score >= 70);
                  
                  return (
                    <div
                      key={idx}
                      onClick={() => setSelectedTicker(opp)}
                      className={`p-3 rounded-lg border cursor-pointer transition-all hover:border-cyan-500/50 ${
                        isHighConviction 
                          ? 'border-cyan-500/30 bg-cyan-500/5 shadow-[0_0_10px_rgba(0,229,255,0.1)]' 
                          : 'border-white/10 bg-zinc-900/50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white">{opp.symbol}</span>
                          {isHighConviction && (
                            <Badge variant="success">HIGH CONVICTION</Badge>
                          )}
                        </div>
                        <span className={`text-sm font-mono ${
                          quote?.change_percent >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {formatPercent(quote?.change_percent)}
                        </span>
                      </div>
                      
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-zinc-400">${formatPrice(quote?.price)}</span>
                        <span className="text-zinc-500">Vol: {formatVolume(quote?.volume)}</span>
                      </div>
                      
                      {opp.conviction && (
                        <div className="mt-2 pt-2 border-t border-white/5">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-zinc-500">Score</span>
                            <span className="text-cyan-400 font-mono">{opp.conviction.score}/100</span>
                          </div>
                        </div>
                      )}
                      
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleTrade(opp, 'BUY'); }}
                          className="flex-1 py-1.5 text-xs font-bold bg-green-500/20 text-green-400 rounded hover:bg-green-500/30"
                        >
                          Buy
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleTrade(opp, 'SELL'); }}
                          className="flex-1 py-1.5 text-xs font-bold bg-red-500/20 text-red-400 rounded hover:bg-red-500/30"
                        >
                          Short
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Market Intelligence / Newsletter Summary */}
          <Card>
            <button 
              onClick={() => toggleSection('news')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Newspaper className="w-5 h-5 text-purple-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Market Intelligence</h3>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.news ? 'rotate-180' : ''}`} />
            </button>
            
            {expandedSections.news && (
              <div className="space-y-3">
                {newsletter ? (
                  <>
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant={
                        newsletter.market_outlook?.sentiment === 'bullish' ? 'success' :
                        newsletter.market_outlook?.sentiment === 'bearish' ? 'error' : 'neutral'
                      }>
                        {newsletter.market_outlook?.sentiment?.toUpperCase() || 'NEUTRAL'}
                      </Badge>
                      <span className="text-xs text-zinc-500">
                        {newsletter.date ? new Date(newsletter.date).toLocaleDateString() : 'Today'}
                      </span>
                    </div>
                    <p className="text-sm text-zinc-300">{newsletter.summary || 'Click Generate in Newsletter page for full briefing'}</p>
                    {newsletter.opportunities?.slice(0, 3).map((opp, idx) => (
                      <div key={idx} className="flex items-center justify-between p-2 bg-zinc-900/50 rounded text-sm">
                        <span className="font-bold text-cyan-400">{opp.symbol}</span>
                        <Badge variant={opp.direction === 'LONG' ? 'success' : opp.direction === 'SHORT' ? 'error' : 'neutral'}>
                          {opp.direction || 'WATCH'}
                        </Badge>
                      </div>
                    ))}
                  </>
                ) : (
                  <p className="text-center text-zinc-500 text-sm py-4">
                    Generate a newsletter for market intelligence
                  </p>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Ticker Detail Modal */}
      {selectedTicker && (
        <TickerDetailModal
          ticker={selectedTicker}
          onClose={() => setSelectedTicker(null)}
          onTrade={handleTrade}
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
