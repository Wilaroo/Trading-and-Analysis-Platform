import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  ChevronRight,
  AlertTriangle,
  Bookmark,
  Play,
  Pause,
  Filter,
  BarChart3,
  Calendar,
  FileText,
  Settings,
  Wifi,
  WifiOff,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  Info,
  TrendingUp as TrendUp,
  Volume2,
  DollarSign,
  Bell,
  CheckCircle2
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';

// ===================== DESIGN TOKENS =====================
const colors = {
  bg: {
    default: '#050505',
    paper: '#0A0A0A',
    subtle: '#121212'
  },
  primary: '#00E5FF',
  success: '#00FF94',
  warning: '#FFD600',
  error: '#FF2E2E'
};

// ===================== UTILITY COMPONENTS =====================
const Card = ({ children, className = '', onClick, glow = false }) => (
  <div 
    onClick={onClick}
    className={`bg-[#0A0A0A] border border-white/10 rounded-lg p-4 transition-all duration-200 
      ${onClick ? 'cursor-pointer hover:border-cyan-500/30' : ''} 
      ${glow ? 'shadow-[0_0_15px_rgba(0,229,255,0.15)]' : ''}
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

const Skeleton = ({ className = '' }) => (
  <div className={`animate-pulse bg-zinc-800 rounded ${className}`} />
);

const formatPrice = (price) => {
  if (!price && price !== 0) return '--';
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatPercent = (pct) => {
  if (!pct && pct !== 0) return '--';
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
};

const formatVolume = (vol) => {
  if (!vol) return '--';
  if (vol >= 1000000) return `${(vol / 1000000).toFixed(1)}M`;
  if (vol >= 1000) return `${(vol / 1000).toFixed(1)}K`;
  return vol.toString();
};

const formatStrategyName = (strategy) => {
  if (!strategy) return '';
  // Format: "INT-Strategy Name" or "SWG-Strategy Name"
  const prefix = strategy.category === 'intraday' ? 'INT' : 
                 strategy.category === 'swing' ? 'SWG' : 'INV';
  return `${prefix}-${strategy.name}`;
};

// ===================== SOUND NOTIFICATIONS =====================
const playTradeSound = (type = 'success') => {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContext();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    if (type === 'success') {
      // Success sound: ascending tones
      oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime); // C5
      oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1); // E5
      oscillator.frequency.setValueAtTime(783.99, audioContext.currentTime + 0.2); // G5
      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.4);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.4);
    } else if (type === 'error') {
      // Error sound: descending tone
      oscillator.frequency.setValueAtTime(400, audioContext.currentTime);
      oscillator.frequency.exponentialRampToValueAtTime(200, audioContext.currentTime + 0.3);
      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.3);
    } else if (type === 'fill') {
      // Fill sound: cash register style
      oscillator.type = 'square';
      oscillator.frequency.setValueAtTime(1200, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(1500, audioContext.currentTime + 0.05);
      oscillator.frequency.setValueAtTime(1800, audioContext.currentTime + 0.1);
      gainNode.gain.setValueAtTime(0.2, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.2);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.2);
    }
  } catch (e) {
    console.log('Audio not supported');
  }
};

// ===================== IB REAL-TIME CHART COMPONENT =====================
const IBChart = ({ symbol }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hasData, setHasData] = useState(false);
  const [timeframe, setTimeframe] = useState('5 mins');
  const [duration, setDuration] = useState('1 D');

  // Create chart on mount
  useEffect(() => {
    if (!chartContainerRef.current || !symbol) return;

    let chart = null;
    let cleanupError = null;
    
    try {
      // Create chart
      chart = LightweightCharts.createChart(chartContainerRef.current, {
        layout: {
          background: { type: 'solid', color: '#0A0A0A' },
          textColor: '#9CA3AF',
        },
        grid: {
          vertLines: { color: '#1F2937' },
          horzLines: { color: '#1F2937' },
        },
        width: chartContainerRef.current.clientWidth || 600,
        height: 300,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderColor: '#374151',
        },
        rightPriceScale: {
          borderColor: '#374151',
        },
        crosshair: {
          mode: 1,
          vertLine: {
            color: '#00E5FF',
            width: 1,
            style: 2,
          },
          horzLine: {
            color: '#00E5FF',
            width: 1,
            style: 2,
          },
        },
      });

      chartRef.current = chart;

      // Add candlestick series
      const candleSeries = chart.addCandlestickSeries({
        upColor: '#00FF94',
        downColor: '#FF2E2E',
        borderUpColor: '#00FF94',
        borderDownColor: '#FF2E2E',
        wickUpColor: '#00FF94',
        wickDownColor: '#FF2E2E',
      });
      candleSeriesRef.current = candleSeries;

      // Add volume series
      const volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: '',
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      });
      volumeSeriesRef.current = volumeSeries;

      // Handle resize
      const handleResize = () => {
        if (chartContainerRef.current && chart) {
          chart.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      };
      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        if (chart) {
          chart.remove();
        }
      };
    } catch (err) {
      console.error('Error creating chart:', err);
      cleanupError = err;
    }
    
    // Handle error in cleanup to avoid setState in effect body
    if (cleanupError) {
      return () => {
        setError('Failed to initialize chart');
      };
    }
  }, [symbol]);

  // Fetch data when symbol or timeframe changes
  useEffect(() => {
    if (!symbol) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      
      try {
        const response = await api.get(`/api/ib/historical/${symbol}?duration=${encodeURIComponent(duration)}&bar_size=${encodeURIComponent(timeframe)}`);
        
        if (response.data.bars && response.data.bars.length > 0) {
          const candleData = response.data.bars.map(bar => ({
            time: new Date(bar.date).getTime() / 1000,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          }));
          
          const volumeData = response.data.bars.map(bar => ({
            time: new Date(bar.date).getTime() / 1000,
            value: bar.volume,
            color: bar.close >= bar.open ? '#00FF9433' : '#FF2E2E33',
          }));

          if (candleSeriesRef.current) {
            candleSeriesRef.current.setData(candleData);
          }
          if (volumeSeriesRef.current) {
            volumeSeriesRef.current.setData(volumeData);
          }
          if (chartRef.current) {
            chartRef.current.timeScale().fitContent();
          }
          setHasData(true);
        } else {
          setHasData(false);
          setError('No chart data available. Connect to IB Gateway.');
        }
      } catch (err) {
        console.error('Error fetching chart data:', err);
        setHasData(false);
        setError('Chart data unavailable. Connect to IB Gateway to view real-time charts.');
      }
      
      setLoading(false);
    };

    fetchData();
    
    // Refresh data every 30 seconds for real-time updates (only if we have data)
    const interval = setInterval(() => {
      if (hasData) fetchData();
    }, 30000);
    return () => clearInterval(interval);
  }, [symbol, timeframe, duration, hasData]);

  const timeframes = [
    { label: '1m', value: '1 min', duration: '1 D' },
    { label: '5m', value: '5 mins', duration: '1 D' },
    { label: '15m', value: '15 mins', duration: '2 D' },
    { label: '1H', value: '1 hour', duration: '1 W' },
    { label: 'D', value: '1 day', duration: '1 M' },
  ];

  return (
    <div className="bg-[#0A0A0A] rounded-lg border border-white/10 overflow-hidden">
      {/* Chart Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10">
        <div className="flex items-center gap-3">
          <span className="font-bold text-white">{symbol}</span>
          <span className="text-xs text-cyan-400">{hasData ? 'IB Real-time' : 'Awaiting IB'}</span>
        </div>
        <div className="flex items-center gap-2">
          {timeframes.map(tf => (
            <button
              key={tf.value}
              onClick={() => { setTimeframe(tf.value); setDuration(tf.duration); }}
              className={`px-2 py-1 text-xs rounded transition-all
                ${timeframe === tf.value 
                  ? 'bg-cyan-400 text-black' 
                  : 'text-zinc-400 hover:text-white hover:bg-white/5'
                }
              `}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>
      
      {/* Chart Container */}
      <div className="relative min-h-[300px]">
        {loading && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0A0A0A] z-10">
            <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
          </div>
        )}
        {error && !hasData && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0A0A0A] z-10 p-4">
            <BarChart3 className="w-12 h-12 text-zinc-600 mb-3" />
            <span className="text-zinc-400 text-sm text-center">{error}</span>
          </div>
        )}
        <div ref={chartContainerRef} className="w-full" style={{ minHeight: hasData ? '300px' : '0' }} />
      </div>
    </div>
  );
};

// ===================== ACTIVE TRADES PANEL (Real-time P&L) =====================
const ActiveTradesPanel = ({ trades, onRemove }) => {
  const [quotes, setQuotes] = useState({});
  
  // Fetch real-time quotes for active trades
  useEffect(() => {
    if (!trades || trades.length === 0) return;
    
    const fetchQuotes = async () => {
      try {
        const symbols = trades.map(t => t.symbol);
        const response = await api.post('/api/ib/quotes/batch', symbols);
        const quotesMap = {};
        response.data.quotes?.forEach(q => {
          quotesMap[q.symbol] = q;
        });
        setQuotes(quotesMap);
      } catch (err) {
        console.error('Error fetching quotes for P&L:', err);
      }
    };
    
    fetchQuotes();
    const interval = setInterval(fetchQuotes, 5000); // Update every 5 seconds
    return () => clearInterval(interval);
  }, [trades]);
  
  if (!trades || trades.length === 0) return null;
  
  return (
    <Card className="mt-4">
      <div className="flex items-center gap-2 mb-3">
        <DollarSign className="w-4 h-4 text-cyan-400" />
        <h3 className="text-sm font-medium uppercase tracking-wider">Active Trades</h3>
      </div>
      
      <div className="space-y-2">
        {trades.map((trade, idx) => {
          const quote = quotes[trade.symbol];
          const currentPrice = quote?.price || trade.entry_price;
          const pnl = trade.action === 'BUY' 
            ? (currentPrice - trade.entry_price) * trade.quantity
            : (trade.entry_price - currentPrice) * trade.quantity;
          const pnlPercent = ((currentPrice - trade.entry_price) / trade.entry_price) * 100;
          const isProfit = pnl >= 0;
          
          return (
            <div key={idx} className="bg-zinc-900 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                    trade.action === 'BUY' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                  }`}>
                    {trade.action}
                  </span>
                  <span className="font-mono font-bold text-white">{trade.symbol}</span>
                  <span className="text-xs text-zinc-500">{trade.quantity} shares</span>
                </div>
                <button 
                  onClick={() => onRemove(idx)}
                  className="text-zinc-500 hover:text-red-400 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-zinc-500">Entry</span>
                  <p className="font-mono text-white">${formatPrice(trade.entry_price)}</p>
                </div>
                <div>
                  <span className="text-zinc-500">Current</span>
                  <p className="font-mono text-cyan-400">${formatPrice(currentPrice)}</p>
                </div>
                <div>
                  <span className="text-zinc-500">P&L</span>
                  <p className={`font-mono font-bold ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
                    {isProfit ? '+' : ''}{formatPrice(pnl)}
                    <span className="text-[10px] ml-1">
                      ({(trade.action === 'BUY' ? 1 : -1) * pnlPercent >= 0 ? '+' : ''}{((trade.action === 'BUY' ? 1 : -1) * pnlPercent).toFixed(2)}%)
                    </span>
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

// ===================== TOAST NOTIFICATION =====================
const Toast = ({ message, type = 'success', onClose }) => {
  useEffect(() => {
    const timer = setTimeout(onClose, 5000);
    return () => clearTimeout(timer);
  }, [onClose]);
  
  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-green-400" />,
    error: <AlertTriangle className="w-5 h-5 text-red-400" />,
    info: <Bell className="w-5 h-5 text-cyan-400" />
  };
  
  const colors = {
    success: 'border-green-500/30 bg-green-500/10',
    error: 'border-red-500/30 bg-red-500/10',
    info: 'border-cyan-500/30 bg-cyan-500/10'
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, y: -20, x: 20 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      exit={{ opacity: 0, y: -20, x: 20 }}
      className={`fixed top-20 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg border ${colors[type]} backdrop-blur-sm`}
    >
      {icons[type]}
      <span className="text-sm text-white">{message}</span>
      <button onClick={onClose} className="text-zinc-400 hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </motion.div>
  );
};

// ===================== TOP PICKS PANEL =====================
const TopPicksPanel = ({ opportunities, isConnected, onTrade, onSelectTicker }) => {
  const [timeframe, setTimeframe] = useState('all');
  const [direction, setDirection] = useState('all');
  const [scoredPicks, setScoredPicks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(true);

  // Score opportunities when they change
  useEffect(() => {
    const scoreOpportunities = async () => {
      if (!opportunities || opportunities.length === 0) {
        setScoredPicks([]);
        return;
      }

      setLoading(true);
      try {
        // Prepare stock data for scoring
        const stocksToScore = opportunities.map(opp => ({
          symbol: opp.symbol,
          current_price: opp.quote?.price || 0,
          vwap: opp.quote?.vwap || opp.quote?.price || 0,
          rvol: opp.quote?.rvol || 1,
          gap_percent: opp.quote?.change_percent || 0,
          market_cap: opp.quote?.market_cap || 10000000000,
          high: opp.quote?.high || opp.quote?.price || 0,
          low: opp.quote?.low || opp.quote?.price || 0,
          prev_close: opp.quote?.prev_close || opp.quote?.price || 0,
          volume: opp.quote?.volume || 0,
          avg_volume: opp.quote?.avg_volume || 1000000,
          float_shares: opp.quote?.float || 50000000,
          patterns: opp.matched_strategies?.map(s => s.name) || []
        }));

        const response = await api.post('/api/scoring/batch', {
          stocks: stocksToScore,
          market_data: { regime: 'neutral' }
        });

        if (response.data.scores) {
          setScoredPicks(response.data.scores);
        }
      } catch (err) {
        console.error('Error scoring opportunities:', err);
        // Fallback: create basic scores from existing data
        const basicScores = opportunities.map(opp => ({
          symbol: opp.symbol,
          composite_score: 50 + (opp.quote?.change_percent || 0) * 2,
          grade: 'C',
          direction: opp.quote?.change_percent > 0 ? 'LONG' : 'SHORT',
          primary_timeframe: 'intraday',
          success_probability: { probability: 50, confidence: 'MEDIUM' },
          key_levels: { support_levels: [], resistance_levels: [] },
          quick_stats: {
            rvol: opp.quote?.rvol || 1,
            gap_pct: opp.quote?.change_percent || 0,
            vwap_position: 'UNKNOWN'
          }
        }));
        setScoredPicks(basicScores);
      }
      setLoading(false);
    };

    scoreOpportunities();
  }, [opportunities]);

  // Filter picks
  const filteredPicks = scoredPicks.filter(pick => {
    if (timeframe !== 'all' && pick.primary_timeframe !== timeframe) return false;
    if (direction === 'long' && !pick.direction?.includes('LONG')) return false;
    if (direction === 'short' && !pick.direction?.includes('SHORT')) return false;
    return true;
  }).slice(0, 10);

  const getGradeColor = (grade) => {
    if (grade?.startsWith('A')) return 'text-green-400';
    if (grade?.startsWith('B')) return 'text-cyan-400';
    if (grade?.startsWith('C')) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getDirectionIcon = (dir) => {
    if (dir?.includes('LONG')) return <TrendingUp className="w-4 h-4 text-green-400" />;
    if (dir?.includes('SHORT')) return <TrendingDown className="w-4 h-4 text-red-400" />;
    return <Activity className="w-4 h-4 text-zinc-400" />;
  };

  const getProbabilityColor = (prob) => {
    if (prob >= 70) return 'text-green-400';
    if (prob >= 50) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <Card className="mb-4">
      {/* Header */}
      <div 
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <Target className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-bold uppercase tracking-wider">Top Picks</h3>
          <span className="text-xs text-zinc-500">({filteredPicks.length})</span>
        </div>
        <ChevronRight className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            {/* Filters */}
            <div className="flex gap-2 mt-3 mb-3">
              {/* Timeframe Filter */}
              <div className="flex gap-1">
                {[
                  { id: 'all', label: 'All' },
                  { id: 'intraday', label: 'Day' },
                  { id: 'swing', label: 'Swing' },
                  { id: 'longterm', label: 'Long' }
                ].map(tf => (
                  <button
                    key={tf.id}
                    onClick={(e) => { e.stopPropagation(); setTimeframe(tf.id); }}
                    className={`px-2 py-1 text-[10px] rounded transition-all
                      ${timeframe === tf.id 
                        ? 'bg-cyan-400 text-black font-medium' 
                        : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                      }
                    `}
                  >
                    {tf.label}
                  </button>
                ))}
              </div>
              
              {/* Direction Filter */}
              <div className="flex gap-1 ml-2">
                {[
                  { id: 'all', label: 'All', icon: null },
                  { id: 'long', label: '↑', icon: null },
                  { id: 'short', label: '↓', icon: null }
                ].map(d => (
                  <button
                    key={d.id}
                    onClick={(e) => { e.stopPropagation(); setDirection(d.id); }}
                    className={`px-2 py-1 text-[10px] rounded transition-all
                      ${direction === d.id 
                        ? d.id === 'long' ? 'bg-green-500 text-black font-medium'
                          : d.id === 'short' ? 'bg-red-500 text-white font-medium'
                          : 'bg-cyan-400 text-black font-medium'
                        : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                      }
                    `}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Loading State */}
            {loading && (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
                <span className="text-xs text-zinc-500 ml-2">Scoring...</span>
              </div>
            )}

            {/* No Picks */}
            {!loading && filteredPicks.length === 0 && (
              <div className="text-center py-4">
                <p className="text-xs text-zinc-500">No picks available. Run a scan first.</p>
              </div>
            )}

            {/* Picks List */}
            {!loading && filteredPicks.length > 0 && (
              <div className="space-y-2">
                {filteredPicks.map((pick, idx) => (
                  <motion.div
                    key={pick.symbol}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className="bg-zinc-900/50 rounded-lg p-3 hover:bg-zinc-800/50 transition-colors cursor-pointer"
                    onClick={() => onSelectTicker && onSelectTicker(pick)}
                  >
                    {/* Top Row: Symbol, Score, Direction */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-white">{pick.symbol}</span>
                        <span className={`text-lg font-bold ${getGradeColor(pick.grade)}`}>
                          {pick.grade}
                        </span>
                        <span className="text-xs text-zinc-500">
                          ({pick.composite_score?.toFixed(0)})
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        {getDirectionIcon(pick.direction)}
                        <span className={`text-xs font-medium ${
                          pick.direction?.includes('LONG') ? 'text-green-400' : 
                          pick.direction?.includes('SHORT') ? 'text-red-400' : 'text-zinc-400'
                        }`}>
                          {pick.direction?.replace('STRONG_', '⚡')}
                        </span>
                      </div>
                    </div>

                    {/* Middle Row: Stats */}
                    <div className="flex items-center gap-4 text-[10px] mb-2">
                      <span className="text-zinc-500">
                        RVOL: <span className="text-white">{pick.quick_stats?.rvol?.toFixed(1) || '-'}</span>
                      </span>
                      <span className="text-zinc-500">
                        Gap: <span className={pick.quick_stats?.gap_pct > 0 ? 'text-green-400' : 'text-red-400'}>
                          {pick.quick_stats?.gap_pct?.toFixed(1) || 0}%
                        </span>
                      </span>
                      <span className="text-zinc-500">
                        VWAP: <span className="text-white">{pick.quick_stats?.vwap_position || '-'}</span>
                      </span>
                      <span className={`px-1.5 py-0.5 rounded ${
                        pick.primary_timeframe === 'intraday' ? 'bg-purple-500/20 text-purple-400' :
                        pick.primary_timeframe === 'swing' ? 'bg-blue-500/20 text-blue-400' :
                        'bg-green-500/20 text-green-400'
                      }`}>
                        {pick.primary_timeframe?.toUpperCase()}
                      </span>
                    </div>

                    {/* Success Probability */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-zinc-500">Success:</span>
                        <div className="flex items-center gap-1">
                          <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                            <div 
                              className={`h-full rounded-full ${
                                pick.success_probability?.probability >= 70 ? 'bg-green-400' :
                                pick.success_probability?.probability >= 50 ? 'bg-yellow-400' :
                                'bg-red-400'
                              }`}
                              style={{ width: `${pick.success_probability?.probability || 0}%` }}
                            />
                          </div>
                          <span className={`text-xs font-mono ${getProbabilityColor(pick.success_probability?.probability)}`}>
                            {pick.success_probability?.probability || 0}%
                          </span>
                        </div>
                      </div>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        pick.success_probability?.confidence === 'HIGH' ? 'bg-green-500/20 text-green-400' :
                        pick.success_probability?.confidence === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-red-500/20 text-red-400'
                      }`}>
                        {pick.success_probability?.confidence}
                      </span>
                    </div>

                    {/* Key Levels */}
                    {pick.key_levels && (
                      <div className="grid grid-cols-2 gap-2 text-[10px]">
                        <div>
                          <span className="text-green-400">Support:</span>
                          <div className="flex gap-1 mt-0.5">
                            {pick.key_levels.support_levels?.slice(0, 3).map((lvl, i) => (
                              <span key={i} className="px-1 py-0.5 bg-green-500/10 text-green-400 rounded">
                                ${lvl.price?.toFixed(2)}
                              </span>
                            ))}
                            {(!pick.key_levels.support_levels || pick.key_levels.support_levels.length === 0) && (
                              <span className="text-zinc-600">-</span>
                            )}
                          </div>
                        </div>
                        <div>
                          <span className="text-red-400">Resistance:</span>
                          <div className="flex gap-1 mt-0.5">
                            {pick.key_levels.resistance_levels?.slice(0, 3).map((lvl, i) => (
                              <span key={i} className="px-1 py-0.5 bg-red-500/10 text-red-400 rounded">
                                ${lvl.price?.toFixed(2)}
                              </span>
                            ))}
                            {(!pick.key_levels.resistance_levels || pick.key_levels.resistance_levels.length === 0) && (
                              <span className="text-zinc-600">-</span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Trade Buttons */}
                    {isConnected && (
                      <div className="flex gap-2 mt-2 pt-2 border-t border-white/5">
                        <button
                          onClick={(e) => { e.stopPropagation(); onTrade && onTrade({ symbol: pick.symbol, quote: {} }, 'BUY'); }}
                          className="flex-1 py-1.5 text-[10px] font-bold uppercase bg-green-500/20 text-green-400 rounded hover:bg-green-500/30 transition-colors"
                        >
                          Buy
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); onTrade && onTrade({ symbol: pick.symbol, quote: {} }, 'SELL'); }}
                          className="flex-1 py-1.5 text-[10px] font-bold uppercase bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors"
                        >
                          Short
                        </button>
                      </div>
                    )}
                  </motion.div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
};

// ===================== SUB-COMPONENTS =====================

// Connection Status Indicator
const ConnectionStatus = ({ isConnected, onConnect, onDisconnect }) => (
  <div className="flex items-center gap-2">
    <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
    <span className="text-xs text-zinc-400 font-mono">
      {isConnected ? 'IB Connected' : 'Disconnected'}
    </span>
    <button
      onClick={isConnected ? onDisconnect : onConnect}
      className="text-xs px-2 py-1 rounded border border-white/20 hover:bg-white/5 transition-colors"
    >
      {isConnected ? 'Disconnect' : 'Connect'}
    </button>
  </div>
);

// Scanner Type Selector
const ScannerSelector = ({ selectedScan, onSelect, isScanning }) => {
  const scanTypes = [
    { id: 'TOP_PERC_GAIN', label: 'Top Gainers', icon: TrendingUp },
    { id: 'TOP_PERC_LOSE', label: 'Top Losers', icon: TrendingDown },
    { id: 'MOST_ACTIVE', label: 'Most Active', icon: Activity },
    { id: 'HOT_BY_VOLUME', label: 'Hot Volume', icon: Volume2 },
    { id: 'HIGH_OPEN_GAP', label: 'Gap Up', icon: ArrowUpRight },
    { id: 'LOW_OPEN_GAP', label: 'Gap Down', icon: ArrowDownRight },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {scanTypes.map(scan => (
        <button
          key={scan.id}
          onClick={() => onSelect(scan.id)}
          disabled={isScanning}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all
            ${selectedScan === scan.id 
              ? 'bg-cyan-400 text-black' 
              : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white'
            }
            ${isScanning ? 'opacity-50 cursor-not-allowed' : ''}
          `}
        >
          <scan.icon className="w-3 h-3" />
          {scan.label}
        </button>
      ))}
    </div>
  );
};

// Opportunity Card
const OpportunityCard = ({ opportunity, onSelect, onTrade }) => {
  const { symbol, quote, strategies, catalystScore, marketContext } = opportunity;
  const isPositive = quote?.change_percent >= 0;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="bg-[#0A0A0A] border border-white/10 rounded-lg p-4 hover:border-cyan-500/30 transition-all cursor-pointer"
      onClick={() => onSelect(opportunity)}
    >
      {/* Header: Symbol + Price */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold font-mono text-white">{symbol}</span>
          <span className={`flex items-center gap-1 text-sm font-mono ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {formatPercent(quote?.change_percent)}
          </span>
        </div>
        <span className="text-lg font-mono text-white">${formatPrice(quote?.price)}</span>
      </div>
      
      {/* Strategy Matches */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {strategies?.slice(0, 3).map((strategy, idx) => (
          <Badge key={idx} variant="info">
            {formatStrategyName(strategy)}
          </Badge>
        ))}
        {strategies?.length > 3 && (
          <Badge variant="neutral">+{strategies.length - 3} more</Badge>
        )}
      </div>
      
      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-zinc-500">Volume</span>
          <p className="font-mono text-white">{formatVolume(quote?.volume)}</p>
        </div>
        <div>
          <span className="text-zinc-500">Catalyst</span>
          <p className={`font-mono ${
            catalystScore > 5 ? 'text-green-400' : 
            catalystScore < -5 ? 'text-red-400' : 'text-zinc-400'
          }`}>
            {catalystScore !== null ? (catalystScore > 0 ? '+' : '') + catalystScore : '--'}
          </p>
        </div>
        <div>
          <span className="text-zinc-500">Context</span>
          <p className="font-mono text-cyan-400 truncate">{marketContext || '--'}</p>
        </div>
      </div>
      
      {/* Action Buttons */}
      <div className="flex gap-2 mt-3 pt-3 border-t border-white/10">
        <button 
          onClick={(e) => { e.stopPropagation(); onTrade(opportunity, 'BUY'); }}
          className="flex-1 py-1.5 text-xs font-bold uppercase tracking-wider bg-green-500/20 text-green-400 rounded hover:bg-green-500/30 transition-colors"
        >
          Buy
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onTrade(opportunity, 'SELL'); }}
          className="flex-1 py-1.5 text-xs font-bold uppercase tracking-wider bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors"
        >
          Short
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onSelect(opportunity); }}
          className="px-3 py-1.5 text-xs font-medium text-zinc-400 border border-white/20 rounded hover:bg-white/5 transition-colors"
        >
          Analyze
        </button>
      </div>
    </motion.div>
  );
};

// Quick Trade Modal - For placing trades directly from scanner
const QuickTradeModal = ({ opportunity, action, onClose, onSuccess }) => {
  const { symbol, quote } = opportunity || {};
  const isBuy = action === 'BUY';
  
  // Initialize prices from quote
  const initialLimitPrice = quote?.price ? quote.price.toFixed(2) : '';
  const stopOffset = isBuy ? 0.98 : 1.02;
  const initialStopPrice = quote?.price ? (quote.price * stopOffset).toFixed(2) : '';
  
  const [quantity, setQuantity] = useState(100);
  const [orderType, setOrderType] = useState('MKT');
  const [limitPrice, setLimitPrice] = useState(initialLimitPrice);
  const [stopPrice, setStopPrice] = useState(initialStopPrice);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);
    
    try {
      const orderData = {
        symbol: symbol,
        action: action,
        quantity: parseInt(quantity),
        order_type: orderType
      };
      
      if (orderType === 'LMT' || orderType === 'STP_LMT') {
        orderData.limit_price = parseFloat(limitPrice);
      }
      
      if (orderType === 'STP' || orderType === 'STP_LMT') {
        orderData.stop_price = parseFloat(stopPrice);
      }
      
      console.log('Placing order:', orderData);
      
      const response = await api.post('/api/ib/order', orderData);
      
      // Play success sound
      playTradeSound('success');
      
      setSuccess(`Order placed! ID: ${response.data.order_id}, Status: ${response.data.status}`);
      
      // Get the fill price (use limit price for limit orders, or current price for market)
      const fillPrice = response.data.avg_fill_price > 0 
        ? response.data.avg_fill_price 
        : (orderType === 'MKT' ? quote?.price : parseFloat(limitPrice));
      
      // Call success callback with trade data for P&L tracking
      setTimeout(() => {
        if (onSuccess) {
          onSuccess({
            ...response.data,
            entry_price: fillPrice || quote?.price,
            quantity: parseInt(quantity),
            action: action,
            symbol: symbol
          });
        }
        onClose();
      }, 1500);
      
    } catch (err) {
      console.error('Order error:', err);
      // Play error sound
      playTradeSound('error');
      setError(err.response?.data?.detail || 'Failed to place order. Check IB connection.');
    }
    
    setIsSubmitting(false);
  };
  
  // Calculate estimated cost/proceeds
  const price = orderType === 'MKT' ? quote?.price : parseFloat(limitPrice) || quote?.price;
  const estimatedValue = price && quantity ? (price * quantity).toFixed(2) : '--';

  if (!opportunity) return null;

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
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-md overflow-hidden rounded-lg shadow-2xl"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className={`p-4 ${isBuy ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-full ${isBuy ? 'bg-green-500/20' : 'bg-red-500/20'}`}>
                  {isBuy ? <TrendingUp className="w-5 h-5 text-green-400" /> : <TrendingDown className="w-5 h-5 text-red-400" />}
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">{isBuy ? 'Buy' : 'Short'} {symbol}</h3>
                  <p className="text-sm text-zinc-400">Current: ${formatPrice(quote?.price)}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-all"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
          
          {/* Form */}
          <div className="p-4 space-y-4">
            {/* Quantity */}
            <div>
              <label className="block text-xs text-zinc-500 uppercase mb-1">Quantity</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className="flex-1 bg-zinc-900 border border-white/10 rounded px-3 py-2 text-white font-mono focus:border-cyan-400 focus:outline-none"
                  min="1"
                />
                <div className="flex gap-1">
                  {[10, 50, 100, 500].map(q => (
                    <button
                      key={q}
                      onClick={() => setQuantity(q)}
                      className={`px-2 py-1 text-xs rounded ${quantity === q ? 'bg-cyan-400 text-black' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'}`}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            
            {/* Order Type */}
            <div>
              <label className="block text-xs text-zinc-500 uppercase mb-1">Order Type</label>
              <div className="grid grid-cols-4 gap-2">
                {[
                  { id: 'MKT', label: 'Market' },
                  { id: 'LMT', label: 'Limit' },
                  { id: 'STP', label: 'Stop' },
                  { id: 'STP_LMT', label: 'Stop Lmt' }
                ].map(type => (
                  <button
                    key={type.id}
                    onClick={() => setOrderType(type.id)}
                    className={`py-2 text-xs font-medium rounded transition-all
                      ${orderType === type.id 
                        ? 'bg-cyan-400 text-black' 
                        : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white'
                      }
                    `}
                  >
                    {type.label}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Limit Price (if applicable) */}
            {(orderType === 'LMT' || orderType === 'STP_LMT') && (
              <div>
                <label className="block text-xs text-zinc-500 uppercase mb-1">Limit Price</label>
                <input
                  type="number"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  step="0.01"
                  className="w-full bg-zinc-900 border border-white/10 rounded px-3 py-2 text-white font-mono focus:border-cyan-400 focus:outline-none"
                />
              </div>
            )}
            
            {/* Stop Price (if applicable) */}
            {(orderType === 'STP' || orderType === 'STP_LMT') && (
              <div>
                <label className="block text-xs text-zinc-500 uppercase mb-1">Stop Price</label>
                <input
                  type="number"
                  value={stopPrice}
                  onChange={(e) => setStopPrice(e.target.value)}
                  step="0.01"
                  className="w-full bg-zinc-900 border border-white/10 rounded px-3 py-2 text-white font-mono focus:border-cyan-400 focus:outline-none"
                />
              </div>
            )}
            
            {/* Estimated Value */}
            <div className="bg-zinc-900 rounded-lg p-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-zinc-400">Estimated {isBuy ? 'Cost' : 'Proceeds'}</span>
                <span className="text-lg font-mono font-bold text-white">${estimatedValue}</span>
              </div>
            </div>
            
            {/* Error/Success Messages */}
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-red-400" />
                <span className="text-sm text-red-400">{error}</span>
              </div>
            )}
            
            {success && (
              <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 flex items-center gap-2">
                <Zap className="w-5 h-5 text-green-400" />
                <span className="text-sm text-green-400">{success}</span>
              </div>
            )}
          </div>
          
          {/* Footer */}
          <div className="p-4 border-t border-white/10">
            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="flex-1 py-2.5 text-sm font-medium text-zinc-400 border border-white/20 rounded hover:bg-white/5 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={isSubmitting || !quantity}
                className={`flex-1 py-2.5 text-sm font-bold uppercase tracking-wider rounded transition-colors
                  ${isBuy 
                    ? 'bg-green-500 hover:bg-green-400 text-black' 
                    : 'bg-red-500 hover:bg-red-400 text-white'
                  }
                  ${isSubmitting ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Placing...
                  </span>
                ) : (
                  `${isBuy ? 'Buy' : 'Short'} ${quantity} Shares`
                )}
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

// Ticker Detail Modal
const TickerDetailModal = ({ opportunity, strategies, onClose, onTrade }) => {
  const [activeTab, setActiveTab] = useState('overview');
  const [historicalData, setHistoricalData] = useState(null);
  const [loading, setLoading] = useState(true);
  
  const { symbol, quote } = opportunity || {};
  
  useEffect(() => {
    if (!symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      try {
        // Fetch historical data
        const histResponse = await api.get(`/api/ib/historical/${symbol}?duration=1 D&bar_size=5 mins`);
        setHistoricalData(histResponse.data);
      } catch (err) {
        console.error('Error fetching ticker details:', err);
      }
      setLoading(false);
    };
    
    fetchData();
  }, [symbol]);

  if (!opportunity) return null;

  const tabs = [
    { id: 'overview', label: 'Overview', icon: BarChart3 },
    { id: 'strategies', label: 'Strategies', icon: Target },
    { id: 'rules', label: 'Rules', icon: FileText },
    { id: 'news', label: 'News', icon: Calendar },
  ];

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
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-lg shadow-2xl"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10">
            <div className="flex items-center gap-4">
              <span className="text-2xl font-bold font-mono text-white">{symbol}</span>
              <span className="text-xl font-mono text-white">${formatPrice(quote?.price)}</span>
              <span className={`flex items-center gap-1 font-mono ${
                quote?.change_percent >= 0 ? 'text-green-400' : 'text-red-400'
              }`}>
                {quote?.change_percent >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
                {formatPercent(quote?.change_percent)}
              </span>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-all"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          
          {/* Tabs */}
          <div className="flex border-b border-white/10">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors
                  ${activeTab === tab.id 
                    ? 'text-cyan-400 border-b-2 border-cyan-400' 
                    : 'text-zinc-400 hover:text-white'
                  }
                `}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
          
          {/* Content */}
          <div className="p-4 overflow-y-auto max-h-[60vh]">
            {activeTab === 'overview' && (
              <div className="space-y-4">
                {/* Stats Grid */}
                <div className="grid grid-cols-4 gap-4">
                  <div className="bg-zinc-900 rounded-lg p-3">
                    <span className="text-xs text-zinc-500 uppercase">Volume</span>
                    <p className="text-lg font-mono text-white">{formatVolume(quote?.volume)}</p>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-3">
                    <span className="text-xs text-zinc-500 uppercase">High</span>
                    <p className="text-lg font-mono text-white">${formatPrice(quote?.high)}</p>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-3">
                    <span className="text-xs text-zinc-500 uppercase">Low</span>
                    <p className="text-lg font-mono text-white">${formatPrice(quote?.low)}</p>
                  </div>
                  <div className="bg-zinc-900 rounded-lg p-3">
                    <span className="text-xs text-zinc-500 uppercase">Open</span>
                    <p className="text-lg font-mono text-white">${formatPrice(quote?.open)}</p>
                  </div>
                </div>
                
                {/* Chart Placeholder */}
                <IBChart symbol={symbol} />
                
                {/* Strategy Matches */}
                <div>
                  <h3 className="text-sm font-medium text-zinc-400 mb-2 uppercase tracking-wider">Matching Strategies</h3>
                  <div className="flex flex-wrap gap-2">
                    {opportunity.strategies?.map((strategy, idx) => (
                      <Badge key={idx} variant="info">
                        {formatStrategyName(strategy)}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            )}
            
            {activeTab === 'strategies' && (
              <div className="space-y-3">
                {opportunity.strategies?.map((strategy, idx) => (
                  <div key={idx} className="bg-zinc-900 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-white">{formatStrategyName(strategy)}</span>
                      <Badge variant={strategy.category === 'intraday' ? 'info' : 'warning'}>
                        {strategy.category}
                      </Badge>
                    </div>
                    <div className="text-sm text-zinc-400 mb-2">
                      <span className="text-zinc-500">Timeframe:</span> {strategy.timeframe}
                    </div>
                    <div className="text-sm">
                      <span className="text-zinc-500">Criteria:</span>
                      <ul className="mt-1 space-y-1">
                        {strategy.criteria?.slice(0, 4).map((c, i) => (
                          <li key={i} className="text-zinc-400 flex items-start gap-2">
                            <span className="text-green-400">✓</span> {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {activeTab === 'rules' && (
              <div className="space-y-3">
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-5 h-5 text-yellow-400" />
                    <span className="font-medium text-yellow-400">Trading Rules</span>
                  </div>
                  <ul className="space-y-2 text-sm text-zinc-300">
                    <li>• Always use stop losses</li>
                    <li>• Risk no more than 1-2% per trade</li>
                    <li>• Trade with the trend in your timeframe</li>
                    <li>• Confirm with volume</li>
                  </ul>
                </div>
              </div>
            )}
            
            {activeTab === 'news' && (
              <div className="text-center text-zinc-500 py-8">
                <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>News integration coming soon</p>
              </div>
            )}
          </div>
          
          {/* Footer Actions */}
          <div className="flex gap-3 p-4 border-t border-white/10">
            <button 
              onClick={() => onTrade(opportunity, 'BUY')}
              className="flex-1 py-2.5 text-sm font-bold uppercase tracking-wider bg-green-500 text-black rounded hover:bg-green-400 transition-colors"
            >
              Buy {symbol}
            </button>
            <button 
              onClick={() => onTrade(opportunity, 'SELL')}
              className="flex-1 py-2.5 text-sm font-bold uppercase tracking-wider bg-red-500 text-white rounded hover:bg-red-400 transition-colors"
            >
              Short {symbol}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

// Market Context Panel
const MarketContextPanel = ({ context }) => {
  const contextColors = {
    'Trending Up': 'text-green-400',
    'Trending Down': 'text-red-400',
    'Range': 'text-yellow-400',
    'Mean Reversion': 'text-cyan-400'
  };
  
  return (
    <Card className="h-fit">
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-5 h-5 text-cyan-400" />
        <h3 className="text-sm font-medium uppercase tracking-wider">Market Context</h3>
      </div>
      
      <div className="space-y-3">
        <div className="bg-zinc-900 rounded-lg p-3">
          <span className="text-xs text-zinc-500">Current Regime</span>
          <p className={`text-lg font-medium ${contextColors[context?.regime] || 'text-zinc-400'}`}>
            {context?.regime || 'Analyzing...'}
          </p>
        </div>
        
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-zinc-900 rounded-lg p-2">
            <span className="text-[10px] text-zinc-500 uppercase">SPY</span>
            <p className={`text-sm font-mono ${context?.spy_change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatPercent(context?.spy_change)}
            </p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-2">
            <span className="text-[10px] text-zinc-500 uppercase">QQQ</span>
            <p className={`text-sm font-mono ${context?.qqq_change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatPercent(context?.qqq_change)}
            </p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-2">
            <span className="text-[10px] text-zinc-500 uppercase">VIX</span>
            <p className="text-sm font-mono text-zinc-300">{context?.vix || '--'}</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-2">
            <span className="text-[10px] text-zinc-500 uppercase">RVOL</span>
            <p className="text-sm font-mono text-zinc-300">{context?.rvol || '--'}</p>
          </div>
        </div>
      </div>
    </Card>
  );
};

// Account Summary Panel
const AccountPanel = ({ account, positions }) => (
  <Card className="h-fit">
    <div className="flex items-center gap-2 mb-4">
      <Target className="w-5 h-5 text-cyan-400" />
      <h3 className="text-sm font-medium uppercase tracking-wider">Account</h3>
    </div>
    
    <div className="space-y-3">
      <div className="bg-zinc-900 rounded-lg p-3">
        <span className="text-xs text-zinc-500">Net Liquidation</span>
        <p className="text-lg font-mono text-white">
          ${formatPrice(account?.net_liquidation)}
        </p>
      </div>
      
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-zinc-900 rounded-lg p-2">
          <span className="text-[10px] text-zinc-500 uppercase">Buying Power</span>
          <p className="text-sm font-mono text-white">${formatPrice(account?.buying_power)}</p>
        </div>
        <div className="bg-zinc-900 rounded-lg p-2">
          <span className="text-[10px] text-zinc-500 uppercase">P&L</span>
          <p className={`text-sm font-mono ${
            account?.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
          }`}>
            ${formatPrice(account?.unrealized_pnl)}
          </p>
        </div>
      </div>
      
      {positions?.length > 0 && (
        <div>
          <span className="text-xs text-zinc-500 uppercase">Positions ({positions.length})</span>
          <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
            {positions.slice(0, 5).map((pos, idx) => (
              <div key={idx} className="flex items-center justify-between text-sm">
                <span className="font-mono text-white">{pos.symbol}</span>
                <span className="text-zinc-400">{pos.quantity} @ ${formatPrice(pos.avg_cost)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  </Card>
);

// ===================== MAIN COMPONENT =====================
const TradeOpportunitiesPage = () => {
  // State
  const [isConnected, setIsConnected] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [autoScan, setAutoScan] = useState(false);
  const [selectedScanType, setSelectedScanType] = useState('TOP_PERC_GAIN');
  const [opportunities, setOpportunities] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [selectedOpportunity, setSelectedOpportunity] = useState(null);
  const [marketContext, setMarketContext] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [error, setError] = useState(null);
  const [lastScanTime, setLastScanTime] = useState(null);
  
  // Quick Trade Modal state
  const [tradeModal, setTradeModal] = useState({ isOpen: false, opportunity: null, action: null });
  
  // Active trades for P&L tracking
  const [activeTrades, setActiveTrades] = useState([]);
  
  // Toast notifications
  const [toast, setToast] = useState(null);
  
  const scanIntervalRef = useRef(null);
  
  // Load strategies on mount
  useEffect(() => {
    const loadStrategies = async () => {
      try {
        const response = await api.get('/api/strategies');
        setStrategies(response.data.strategies || []);
      } catch (err) {
        console.error('Failed to load strategies:', err);
      }
    };
    loadStrategies();
  }, []);
  
  // Check IB connection status
  useEffect(() => {
    const checkConnection = async () => {
      try {
        const response = await api.get('/api/ib/status');
        setIsConnected(response.data.connected);
      } catch (err) {
        setIsConnected(false);
      }
    };
    
    checkConnection();
    const interval = setInterval(checkConnection, 10000);
    return () => clearInterval(interval);
  }, []);
  
  // Load account data when connected
  useEffect(() => {
    if (!isConnected) return;
    
    const loadAccountData = async () => {
      try {
        const [accountRes, positionsRes] = await Promise.all([
          api.get('/api/ib/account/summary'),
          api.get('/api/ib/account/positions')
        ]);
        setAccount(accountRes.data);
        setPositions(positionsRes.data.positions || []);
      } catch (err) {
        console.error('Failed to load account data:', err);
      }
    };
    
    loadAccountData();
    const interval = setInterval(loadAccountData, 30000);
    return () => clearInterval(interval);
  }, [isConnected]);
  
  // Load market context
  useEffect(() => {
    const loadMarketContext = async () => {
      try {
        const response = await api.get('/api/market-context');
        if (response.data) {
          setMarketContext({
            regime: response.data.regime || response.data.market_context || 'Unknown',
            spy_change: response.data.spy?.change_percent || 0,
            qqq_change: response.data.qqq?.change_percent || 0,
            vix: response.data.vix?.price || '--',
            rvol: response.data.rvol || '--'
          });
        }
      } catch (err) {
        console.error('Failed to load market context:', err);
      }
    };
    
    loadMarketContext();
    const interval = setInterval(loadMarketContext, 60000); // Every minute
    return () => clearInterval(interval);
  }, []);
  
  // Connect to IB
  const handleConnect = async () => {
    try {
      setError(null);
      await api.post('/api/ib/connect');
      setIsConnected(true);
    } catch (err) {
      setError('Failed to connect to IB Gateway. Make sure it\'s running.');
    }
  };
  
  // Disconnect from IB
  const handleDisconnect = async () => {
    try {
      await api.post('/api/ib/disconnect');
      setIsConnected(false);
      setAutoScan(false);
    } catch (err) {
      console.error('Failed to disconnect:', err);
    }
  };
  
  // Run scanner
  const runScanner = useCallback(async () => {
    if (!isConnected || isScanning) return;
    
    setIsScanning(true);
    setError(null);
    
    try {
      console.log('Running enhanced scanner:', selectedScanType);
      
      // Run enhanced IB scanner with conviction scoring
      const scanResponse = await api.post('/api/ib/scanner/enhanced', {
        scan_type: selectedScanType,
        max_results: 30,
        calculate_features: true
      });
      
      console.log('Enhanced scanner response:', scanResponse.data);
      
      const scanResults = scanResponse.data.results || [];
      const highConvictionCount = scanResponse.data.high_conviction_count || 0;
      
      if (scanResults.length === 0) {
        console.log('No scanner results');
        setOpportunities([]);
        setLastScanTime(new Date());
        setIsScanning(false);
        return;
      }
      
      console.log('Scanner found', scanResults.length, 'symbols,', highConvictionCount, 'high conviction');
      
      // Map results to opportunities with conviction data
      const opps = scanResults.map(result => {
        const quote = result.quote || { 
          symbol: result.symbol, 
          price: 0, 
          change_percent: 0,
          volume: 0
        };
        
        // Strategy matching based on scan type
        let matchedStrategies = [];
        
        if (strategies.length > 0) {
          if (selectedScanType === 'TOP_PERC_GAIN' || selectedScanType === 'HIGH_OPEN_GAP') {
            matchedStrategies = strategies.filter(s => 
              s.category === 'intraday' && (
                s.name.toLowerCase().includes('momentum') || 
                s.name.toLowerCase().includes('breakout') ||
                s.name.toLowerCase().includes('gap') ||
                s.name.toLowerCase().includes('opening') ||
                s.name.toLowerCase().includes('trend')
              )
            );
          } else if (selectedScanType === 'TOP_PERC_LOSE' || selectedScanType === 'LOW_OPEN_GAP') {
            matchedStrategies = strategies.filter(s => 
              s.category === 'intraday' && (
                s.name.toLowerCase().includes('fade') || 
                s.name.toLowerCase().includes('reversion') ||
                s.name.toLowerCase().includes('short')
              )
            );
          } else if (selectedScanType === 'MOST_ACTIVE' || selectedScanType === 'HOT_BY_VOLUME') {
            matchedStrategies = strategies.filter(s => 
              s.category === 'intraday' && (
                s.name.toLowerCase().includes('volume') ||
                s.name.toLowerCase().includes('scalp') ||
                s.name.toLowerCase().includes('momentum')
              )
            );
          } else if (selectedScanType === 'HIGH_VS_52W_HL') {
            matchedStrategies = strategies.filter(s => 
              s.name.toLowerCase().includes('breakout') ||
              s.name.toLowerCase().includes('trend') ||
              s.category === 'swing'
            );
          } else {
            matchedStrategies = strategies.filter(s => s.category === 'intraday');
          }
          
          matchedStrategies = matchedStrategies.slice(0, 5);
        }
        
        return {
          symbol: result.symbol,
          rank: result.rank,
          quote,
          strategies: matchedStrategies,
          catalystScore: null,
          marketContext: marketContext?.regime || 'Unknown',
          // New conviction data
          conviction: result.conviction,
          features: result.features,
          highConviction: result.high_conviction
        };
      });
      
      console.log('Created', opps.length, 'opportunities');
      setOpportunities(opps);
      setLastScanTime(new Date());
      
    } catch (err) {
      console.error('Scanner error:', err);
      setError('Failed to run scanner. Check IB connection.');
    }
    
    setIsScanning(false);
  }, [isConnected, isScanning, selectedScanType, strategies, marketContext]);
  
  // Auto-scan interval
  useEffect(() => {
    if (autoScan && isConnected) {
      // Initial scan when auto-scan is enabled
      const timer = setTimeout(() => {
        runScanner();
      }, 100);
      scanIntervalRef.current = setInterval(runScanner, 60000); // Every minute
      return () => {
        clearTimeout(timer);
        if (scanIntervalRef.current) {
          clearInterval(scanIntervalRef.current);
        }
      };
    } else {
      if (scanIntervalRef.current) {
        clearInterval(scanIntervalRef.current);
      }
    }
    
    return () => {
      if (scanIntervalRef.current) {
        clearInterval(scanIntervalRef.current);
      }
    };
  }, [autoScan, isConnected, runScanner]);
  
  // Handle trade - Opens quick trade modal
  const handleTrade = async (opportunity, action) => {
    setTradeModal({
      isOpen: true,
      opportunity,
      action
    });
  };
  
  // Handle successful trade
  const handleTradeSuccess = (orderData) => {
    console.log('Trade successful:', orderData);
    
    // Add to active trades for P&L tracking
    setActiveTrades(prev => [...prev, {
      symbol: orderData.symbol,
      action: orderData.action,
      quantity: orderData.quantity,
      entry_price: orderData.entry_price,
      order_id: orderData.order_id,
      timestamp: new Date().toISOString()
    }]);
    
    // Show toast notification
    setToast({
      message: `${orderData.action} ${orderData.quantity} ${orderData.symbol} @ $${formatPrice(orderData.entry_price)}`,
      type: 'success'
    });
    
    // Play fill sound after a short delay
    setTimeout(() => playTradeSound('fill'), 500);
  };
  
  // Remove trade from active tracking
  const removeActiveTrade = (index) => {
    setActiveTrades(prev => prev.filter((_, i) => i !== index));
  };
  
  // Close trade modal
  const closeTradeModal = () => {
    setTradeModal({ isOpen: false, opportunity: null, action: null });
  };

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      {/* Toast Notification */}
      <AnimatePresence>
        {toast && (
          <Toast 
            message={toast.message} 
            type={toast.type} 
            onClose={() => setToast(null)} 
          />
        )}
      </AnimatePresence>
      
      {/* Header */}
      <div className="border-b border-white/10 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Trade Opportunities</h1>
            <p className="text-sm text-zinc-500">Real-time market scanner powered by Interactive Brokers</p>
          </div>
          <div className="flex items-center gap-4">
            <ConnectionStatus 
              isConnected={isConnected}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
          </div>
        </div>
      </div>
      
      {/* Error Banner */}
      {error && (
        <div className="mx-6 mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-red-400" />
          <span className="text-red-400 text-sm">{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      
      {/* Main Content */}
      <div className="grid grid-cols-12 gap-4 p-4 h-[calc(100vh-120px)]">
        {/* Scanner Controls - Left */}
        <div className="col-span-12 lg:col-span-2 space-y-4 overflow-y-auto">
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium uppercase tracking-wider">Scanner</h3>
              <button
                onClick={() => setAutoScan(!autoScan)}
                className={`p-1.5 rounded ${autoScan ? 'bg-cyan-400/20 text-cyan-400' : 'text-zinc-400 hover:text-white'}`}
                title={autoScan ? 'Auto-scan ON' : 'Auto-scan OFF'}
              >
                {autoScan ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              </button>
            </div>
            
            <div className="space-y-2">
              <ScannerSelector 
                selectedScan={selectedScanType}
                onSelect={setSelectedScanType}
                isScanning={isScanning}
              />
            </div>
            
            <button
              onClick={runScanner}
              disabled={!isConnected || isScanning}
              className={`w-full mt-4 py-2 text-sm font-bold uppercase tracking-wider rounded transition-all
                ${isConnected && !isScanning
                  ? 'bg-cyan-400 text-black hover:bg-cyan-300'
                  : 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                }
              `}
            >
              {isScanning ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Scanning...
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4" />
                  Scan Now
                </span>
              )}
            </button>
            
            {lastScanTime && (
              <p className="text-[10px] text-zinc-500 text-center mt-2">
                Last scan: {lastScanTime.toLocaleTimeString()}
              </p>
            )}
          </Card>
          
          <MarketContextPanel context={marketContext} />
        </div>
        
        {/* Opportunities Feed - Center */}
        <div className="col-span-12 lg:col-span-7 overflow-y-auto pr-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium">
              Opportunities 
              <span className="text-zinc-500 ml-2">({opportunities.length})</span>
            </h2>
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <Clock className="w-3 h-3" />
              {lastScanTime ? `Updated ${lastScanTime.toLocaleTimeString()}` : 'Not scanned yet'}
            </div>
          </div>
          
          {!isConnected ? (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <WifiOff className="w-12 h-12 text-zinc-600 mb-4" />
              <p className="text-zinc-400 mb-2">Not connected to IB Gateway</p>
              <button
                onClick={handleConnect}
                className="px-4 py-2 bg-cyan-400 text-black font-bold rounded hover:bg-cyan-300 transition-colors"
              >
                Connect Now
              </button>
            </div>
          ) : opportunities.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <Search className="w-12 h-12 text-zinc-600 mb-4" />
              <p className="text-zinc-400 mb-2">No opportunities yet</p>
              <p className="text-zinc-500 text-sm">Click &quot;Scan Now&quot; to find trade setups</p>
            </div>
          ) : (
            <div className="grid gap-3">
              <AnimatePresence>
                {opportunities.map((opp, idx) => (
                  <OpportunityCard
                    key={`${opp.symbol}-${idx}`}
                    opportunity={opp}
                    onSelect={setSelectedOpportunity}
                    onTrade={handleTrade}
                  />
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
        
        {/* Account Panel - Right */}
        <div className="col-span-12 lg:col-span-3 space-y-4 overflow-y-auto">
          <AccountPanel account={account} positions={positions} />
          
          {/* Top Picks Panel - Scored Opportunities */}
          <TopPicksPanel 
            opportunities={opportunities}
            isConnected={isConnected}
            onTrade={handleTrade}
            onSelectTicker={(pick) => {
              const opp = opportunities.find(o => o.symbol === pick.symbol);
              if (opp) setSelectedOpportunity(opp);
            }}
          />
          
          {/* Active Trades Panel - Real-time P&L */}
          <ActiveTradesPanel trades={activeTrades} onRemove={removeActiveTrade} />
          
          {/* Quick Stats */}
          <Card>
            <h3 className="text-sm font-medium uppercase tracking-wider mb-3">Today&apos;s Stats</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-500">Scans Run</span>
                <span className="font-mono">{lastScanTime ? '1' : '0'}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-500">Opportunities</span>
                <span className="font-mono">{opportunities.length}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-500">Strategies</span>
                <span className="font-mono">{strategies.length}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-500">Active Trades</span>
                <span className="font-mono text-cyan-400">{activeTrades.length}</span>
              </div>
            </div>
          </Card>
        </div>
      </div>
      
      {/* Ticker Detail Modal */}
      {selectedOpportunity && (
        <TickerDetailModal
          opportunity={selectedOpportunity}
          strategies={strategies}
          onClose={() => setSelectedOpportunity(null)}
          onTrade={handleTrade}
        />
      )}
      
      {/* Quick Trade Modal */}
      {tradeModal.isOpen && (
        <QuickTradeModal
          opportunity={tradeModal.opportunity}
          action={tradeModal.action}
          onClose={closeTradeModal}
          onSuccess={handleTradeSuccess}
        />
      )}
    </div>
  );
};

export default TradeOpportunitiesPage;
