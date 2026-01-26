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
  Trash2
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';
import { toast } from 'sonner';

// ===================== SOUND UTILITIES =====================
const playSound = (type = 'alert') => {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    if (type === 'fill') {
      // Order fill sound - pleasant ding
      oscillator.frequency.setValueAtTime(880, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(1100, audioContext.currentTime + 0.1);
      oscillator.type = 'sine';
      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.3);
    } else if (type === 'alert') {
      // Price alert sound - attention-grabbing
      oscillator.frequency.setValueAtTime(660, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(880, audioContext.currentTime + 0.15);
      oscillator.frequency.setValueAtTime(660, audioContext.currentTime + 0.3);
      oscillator.type = 'square';
      gainNode.gain.setValueAtTime(0.2, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.4);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.4);
    } else if (type === 'squeeze') {
      // Short squeeze alert - urgent
      oscillator.frequency.setValueAtTime(440, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(880, audioContext.currentTime + 0.1);
      oscillator.frequency.setValueAtTime(1320, audioContext.currentTime + 0.2);
      oscillator.type = 'sawtooth';
      gainNode.gain.setValueAtTime(0.15, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.5);
    }
  } catch (e) {
    console.log('Sound playback error:', e);
  }
};

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

    // v4 API: addLineSeries
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
  const [analysis, setAnalysis] = useState(null);
  const [historicalData, setHistoricalData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [showTradingLines, setShowTradingLines] = useState(true);
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!ticker?.symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      try {
        // Fetch comprehensive analysis
        const [analysisRes, histRes] = await Promise.all([
          api.get(`/api/ib/analysis/${ticker.symbol}`).catch((err) => {
            console.error('Analysis API error:', err);
            return { data: null };
          }),
          api.get(`/api/ib/historical/${ticker.symbol}?duration=1 D&bar_size=5 mins`).catch(() => ({ data: { bars: [] } }))
        ]);
        
        console.log('Analysis data received:', analysisRes.data);
        setAnalysis(analysisRes.data);
        setHistoricalData(histRes.data?.bars || []);
      } catch (err) {
        console.error('Error fetching data:', err);
      }
      setLoading(false);
    };
    
    fetchData();
  }, [ticker?.symbol]);

  // Initialize chart with SL/TP lines
  useEffect(() => {
    if (!chartContainerRef.current || !historicalData || historicalData.length === 0 || activeTab !== 'chart') return;

    // Clear any existing chart first
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    // Small delay to ensure container has dimensions
    const timer = setTimeout(() => {
      if (!chartContainerRef.current) return;
      
      const container = chartContainerRef.current;
      const containerWidth = container.clientWidth || 700;
      
      try {
        const chart = LightweightCharts.createChart(container, {
          width: containerWidth,
          height: 300,
          layout: { 
            background: { type: 'solid', color: '#0A0A0A' }, 
            textColor: '#71717a',
          },
          grid: { 
            vertLines: { color: 'rgba(255,255,255,0.05)' }, 
            horzLines: { color: 'rgba(255,255,255,0.05)' } 
          },
          crosshair: { mode: 1 },
          rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
          timeScale: { 
            borderColor: 'rgba(255,255,255,0.1)', 
            timeVisible: true,
            secondsVisible: false,
          },
        });

        chartRef.current = chart;

        // v4 API: addCandlestickSeries
        const candlestickSeries = chart.addCandlestickSeries({
          upColor: '#00FF94', 
          downColor: '#FF2E2E',
          borderUpColor: '#00FF94', 
          borderDownColor: '#FF2E2E',
          wickUpColor: '#00FF94', 
          wickDownColor: '#FF2E2E',
        });

        const chartData = historicalData.map(bar => ({
          time: Math.floor(new Date(bar.date).getTime() / 1000),
          open: bar.open, 
          high: bar.high, 
          low: bar.low, 
          close: bar.close,
        }));

        console.log('Chart data points:', chartData.length, 'First:', chartData[0], 'Last:', chartData[chartData.length - 1]);
        console.log('Container dimensions:', container.clientWidth, container.clientHeight);
        
        candlestickSeries.setData(chartData);
        
        // Force a re-render by scrolling to the end
        chart.timeScale().scrollToPosition(0, false);
        chart.timeScale().fitContent();
        
        console.log('Chart created and data set successfully');
        
        // Add SL/TP price lines if trading summary exists and lines are enabled
        if (showTradingLines && analysis?.trading_summary) {
          const ts = analysis.trading_summary;
          
          // Entry line (cyan)
          if (ts.entry) {
            candlestickSeries.createPriceLine({
              price: ts.entry,
              color: '#00E5FF',
              lineWidth: 2,
              lineStyle: 0, // Solid
              axisLabelVisible: true,
              title: 'Entry',
            });
          }
          
          // Stop Loss line (red dashed)
          if (ts.stop_loss) {
            candlestickSeries.createPriceLine({
              price: ts.stop_loss,
              color: '#FF2E2E',
              lineWidth: 2,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: 'Stop',
            });
          }
          
          // Take Profit line (green dashed)
          if (ts.target) {
            candlestickSeries.createPriceLine({
              price: ts.target,
              color: '#00FF94',
              lineWidth: 2,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: 'Target',
            });
          }
        }

        // Handle resize
        const handleResize = () => {
          if (chartRef.current && container) {
            chartRef.current.applyOptions({ width: container.clientWidth });
          }
        };
        window.addEventListener('resize', handleResize);

      } catch (err) {
        console.error('Error creating chart:', err);
      }
    }, 100);

    return () => {
      clearTimeout(timer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [historicalData, activeTab, showTradingLines, analysis]);

  if (!ticker) return null;

  const quote = analysis?.quote || ticker.quote || ticker;
  const tradingSummary = analysis?.trading_summary || {};
  const scores = analysis?.scores || {};
  const technicals = analysis?.technicals || {};
  const fundamentals = analysis?.fundamentals || {};
  const companyInfo = analysis?.company_info || {};
  const supportResistance = analysis?.support_resistance || {};
  const matchedStrategies = analysis?.matched_strategies || [];
  const news = analysis?.news || [];

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'technicals', label: 'Technicals' },
    { id: 'fundamentals', label: 'Fundamentals' },
    { id: 'strategies', label: 'Strategies' },
    { id: 'news', label: 'News' },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="bg-[#0A0A0A] border border-white/10 w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-xl"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-zinc-900/50 to-transparent">
            <div className="flex items-center gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <span className="text-2xl font-bold text-white">{ticker.symbol}</span>
                  {scores.grade && (
                    <span className={`text-sm px-2 py-0.5 rounded font-bold ${
                      scores.grade === 'A' ? 'bg-green-500 text-black' :
                      scores.grade === 'B' ? 'bg-cyan-500 text-black' :
                      scores.grade === 'C' ? 'bg-yellow-500 text-black' :
                      'bg-red-500 text-white'
                    }`}>
                      Grade {scores.grade}
                    </span>
                  )}
                  {tradingSummary.bias && (
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      tradingSummary.bias === 'BULLISH' ? 'bg-green-500/20 text-green-400' :
                      tradingSummary.bias === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
                      'bg-zinc-500/20 text-zinc-400'
                    }`}>
                      {tradingSummary.bias_strength} {tradingSummary.bias}
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-500 mt-0.5">{companyInfo.name || ticker.symbol}</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="text-right">
                <span className="text-2xl font-mono font-bold text-white">${formatPrice(quote?.price)}</span>
                <span className={`ml-2 font-mono ${quote?.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatPercent(quote?.change_percent)}
                </span>
              </div>
              <button onClick={onClose} className="p-2 rounded-lg hover:bg-white/10 text-zinc-400">
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-white/10 px-4 overflow-x-auto">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                  activeTab === tab.id 
                    ? 'text-cyan-400 border-b-2 border-cyan-400' 
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="p-4 overflow-y-auto max-h-[60vh]">
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-10 h-10 animate-spin text-cyan-400" />
              </div>
            ) : (
              <>
                {/* OVERVIEW TAB */}
                {activeTab === 'overview' && (
                  <div className="space-y-4">
                    {/* Trading Summary Card */}
                    {tradingSummary.summary && (
                      <div className={`p-4 rounded-lg border ${
                        tradingSummary.bias === 'BULLISH' ? 'border-green-500/30 bg-green-500/5' :
                        tradingSummary.bias === 'BEARISH' ? 'border-red-500/30 bg-red-500/5' :
                        'border-zinc-700 bg-zinc-900/50'
                      }`}>
                        <div className="flex items-center gap-2 mb-2">
                          <Target className="w-5 h-5 text-cyan-400" />
                          <span className="font-semibold text-white">Trading Analysis</span>
                        </div>
                        <p className="text-sm text-zinc-300 mb-3">{tradingSummary.summary}</p>
                        
                        <div className="grid grid-cols-4 gap-3 text-center">
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Direction</span>
                            <p className={`text-sm font-bold ${
                              tradingSummary.suggested_direction === 'LONG' ? 'text-green-400' :
                              tradingSummary.suggested_direction === 'SHORT' ? 'text-red-400' :
                              'text-yellow-400'
                            }`}>{tradingSummary.suggested_direction || 'WAIT'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Entry</span>
                            <p className="text-sm font-mono text-white">${tradingSummary.entry?.toFixed(2) || '--'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Stop</span>
                            <p className="text-sm font-mono text-red-400">${tradingSummary.stop_loss?.toFixed(2) || '--'}</p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 uppercase">Target</span>
                            <p className="text-sm font-mono text-green-400">${tradingSummary.target?.toFixed(2) || '--'}</p>
                          </div>
                        </div>
                        
                        {tradingSummary.risk_reward > 0 && (
                          <div className="mt-2 text-xs text-zinc-500 text-center">
                            Risk/Reward: <span className="text-cyan-400 font-mono">1:{tradingSummary.risk_reward}</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Scores Grid */}
                    <div className="grid grid-cols-5 gap-2">
                      {[
                        { label: 'Overall', value: scores.overall, color: scores.overall >= 70 ? 'cyan' : scores.overall >= 50 ? 'yellow' : 'red' },
                        { label: 'Technical', value: scores.technical_score, color: 'blue' },
                        { label: 'Fundamental', value: scores.fundamental_score, color: 'purple' },
                        { label: 'Catalyst', value: scores.catalyst_score, color: 'orange' },
                        { label: 'Confidence', value: scores.confidence, color: 'green' },
                      ].map((score, idx) => (
                        <div key={idx} className="bg-zinc-900 rounded-lg p-3 text-center">
                          <span className="text-[10px] text-zinc-500 uppercase block">{score.label}</span>
                          <p className={`text-xl font-bold font-mono text-${score.color}-400`}>
                            {score.value?.toFixed(0) || '--'}
                          </p>
                        </div>
                      ))}
                    </div>

                    {/* Company Info */}
                    {companyInfo.name && (
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase">Company</span>
                        <p className="text-sm text-white font-medium">{companyInfo.name}</p>
                        <div className="flex gap-4 mt-1 text-xs text-zinc-400">
                          <span>{companyInfo.sector}</span>
                          <span>{companyInfo.industry}</span>
                          {companyInfo.market_cap > 0 && (
                            <span>MCap: ${(companyInfo.market_cap / 1e9).toFixed(1)}B</span>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Top Strategy Match */}
                    {matchedStrategies.length > 0 && (
                      <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[10px] text-cyan-400 uppercase font-semibold">Top Strategy Match</span>
                          <span className="text-xs text-cyan-400">{matchedStrategies[0].match_score}% match</span>
                        </div>
                        <p className="text-sm font-bold text-white">{matchedStrategies[0].name}</p>
                        <p className="text-xs text-zinc-400 mt-1">{matchedStrategies[0].match_reasons?.join(' • ')}</p>
                        {matchedStrategies[0].entry_rules && (
                          <p className="text-[10px] text-zinc-500 mt-2">Entry: {matchedStrategies[0].entry_rules}</p>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* CHART TAB */}
                {activeTab === 'chart' && (
                  <div>
                    {/* Chart Controls */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-zinc-500">5-min Candles</span>
                      </div>
                      <button
                        onClick={() => setShowTradingLines(!showTradingLines)}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
                          showTradingLines 
                            ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                            : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
                        }`}
                      >
                        <Target className="w-3 h-3" />
                        {showTradingLines ? 'Hide' : 'Show'} SL/TP Lines
                      </button>
                    </div>
                    
                    <div 
                      ref={chartContainerRef} 
                      className="w-full border border-zinc-800 rounded bg-zinc-950" 
                      style={{ height: '300px', minHeight: '300px', minWidth: '400px' }} 
                    />
                    
                    {/* Trading Levels Legend */}
                    {showTradingLines && tradingSummary.entry && (
                      <div className="flex items-center justify-center gap-4 mt-2 text-[10px]">
                        <span className="flex items-center gap-1">
                          <span className="w-3 h-0.5 bg-cyan-400 rounded"></span>
                          Entry ${tradingSummary.entry?.toFixed(2)}
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="w-3 h-0.5 bg-red-400 rounded border-dashed"></span>
                          Stop ${tradingSummary.stop_loss?.toFixed(2)}
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="w-3 h-0.5 bg-green-400 rounded border-dashed"></span>
                          Target ${tradingSummary.target?.toFixed(2)}
                        </span>
                      </div>
                    )}
                    
                    {supportResistance.resistance_1 && (
                      <div className="grid grid-cols-4 gap-2 mt-3">
                        <div className="bg-red-500/10 rounded p-2 text-center">
                          <span className="text-[10px] text-zinc-500">R1</span>
                          <p className="text-sm font-mono text-red-400">${supportResistance.resistance_1?.toFixed(2)}</p>
                        </div>
                        <div className="bg-red-500/5 rounded p-2 text-center">
                          <span className="text-[10px] text-zinc-500">R2</span>
                          <p className="text-sm font-mono text-red-300">${supportResistance.resistance_2?.toFixed(2)}</p>
                        </div>
                        <div className="bg-green-500/5 rounded p-2 text-center">
                          <span className="text-[10px] text-zinc-500">S1</span>
                          <p className="text-sm font-mono text-green-300">${supportResistance.support_1?.toFixed(2)}</p>
                        </div>
                        <div className="bg-green-500/10 rounded p-2 text-center">
                          <span className="text-[10px] text-zinc-500">S2</span>
                          <p className="text-sm font-mono text-green-400">${supportResistance.support_2?.toFixed(2)}</p>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* TECHNICALS TAB */}
                {activeTab === 'technicals' && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                      { label: 'RSI (14)', value: technicals.rsi_14?.toFixed(1), suffix: '', color: technicals.rsi_14 > 70 ? 'red' : technicals.rsi_14 < 30 ? 'green' : 'zinc' },
                      { label: 'RVOL', value: technicals.rvol?.toFixed(1), suffix: 'x', color: technicals.rvol > 2 ? 'cyan' : 'zinc' },
                      { label: 'VWAP', value: '$' + technicals.vwap?.toFixed(2), suffix: '', color: 'purple' },
                      { label: 'VWAP Dist', value: technicals.vwap_distance_pct?.toFixed(1), suffix: '%', color: technicals.vwap_distance_pct > 0 ? 'green' : 'red' },
                      { label: 'EMA 9', value: '$' + technicals.ema_9?.toFixed(2), suffix: '', color: 'blue' },
                      { label: 'EMA 20', value: '$' + technicals.ema_20?.toFixed(2), suffix: '', color: 'blue' },
                      { label: 'SMA 50', value: '$' + technicals.sma_50?.toFixed(2), suffix: '', color: 'yellow' },
                      { label: 'ATR (14)', value: '$' + technicals.atr_14?.toFixed(2), suffix: '', color: 'orange' },
                      { label: 'MACD', value: technicals.macd?.toFixed(3), suffix: '', color: technicals.macd > 0 ? 'green' : 'red' },
                      { label: 'MACD Signal', value: technicals.macd_signal?.toFixed(3), suffix: '', color: 'zinc' },
                      { label: 'Volume Trend', value: technicals.volume_trend, suffix: '', color: technicals.volume_trend === 'Above Avg' ? 'green' : 'zinc' },
                      { label: 'Trend', value: technicals.trend, suffix: '', color: technicals.trend === 'Bullish' ? 'green' : 'red' },
                    ].map((item, idx) => (
                      <div key={idx} className="bg-zinc-900 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase block">{item.label}</span>
                        <p className={`text-lg font-mono text-${item.color}-400`}>
                          {item.value || '--'}{item.suffix}
                        </p>
                      </div>
                    ))}
                  </div>
                )}

                {/* FUNDAMENTALS TAB */}
                {activeTab === 'fundamentals' && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      {[
                        { label: 'Market Cap', value: fundamentals.market_cap ? `$${(fundamentals.market_cap / 1e9).toFixed(1)}B` : '--' },
                        { label: 'P/E Ratio', value: fundamentals.pe_ratio?.toFixed(1) || '--' },
                        { label: 'EPS', value: fundamentals.eps ? `$${fundamentals.eps.toFixed(2)}` : '--' },
                        { label: 'Dividend Yield', value: fundamentals.dividend_yield ? `${fundamentals.dividend_yield.toFixed(2)}%` : '--' },
                        { label: 'Beta', value: fundamentals.beta?.toFixed(2) || '--' },
                        { label: '52W High', value: fundamentals.high_52w ? `$${fundamentals.high_52w.toFixed(2)}` : '--' },
                        { label: '52W Low', value: fundamentals.low_52w ? `$${fundamentals.low_52w.toFixed(2)}` : '--' },
                        { label: 'Avg Volume', value: fundamentals.avg_volume ? formatVolume(fundamentals.avg_volume) : '--' },
                      ].map((item, idx) => (
                        <div key={idx} className="bg-zinc-900 rounded-lg p-3">
                          <span className="text-[10px] text-zinc-500 uppercase block">{item.label}</span>
                          <p className="text-lg font-mono text-white">{item.value}</p>
                        </div>
                      ))}
                    </div>
                    {companyInfo.description && (
                      <div className="bg-zinc-900/50 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase block mb-1">Description</span>
                        <p className="text-xs text-zinc-400 leading-relaxed">{companyInfo.description}</p>
                      </div>
                    )}
                  </div>
                )}

                {/* STRATEGIES TAB */}
                {activeTab === 'strategies' && (
                  <div className="space-y-3">
                    {matchedStrategies.length > 0 ? matchedStrategies.map((strat, idx) => (
                      <div 
                        key={idx} 
                        className={`p-3 rounded-lg border ${
                          idx === 0 ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-white/10 bg-zinc-900/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded font-mono">{strat.id}</span>
                            <span className="font-semibold text-white">{strat.name}</span>
                          </div>
                          <span className={`text-sm font-bold ${
                            strat.match_score >= 70 ? 'text-green-400' :
                            strat.match_score >= 50 ? 'text-yellow-400' :
                            'text-zinc-400'
                          }`}>{strat.match_score}%</span>
                        </div>
                        <p className="text-xs text-zinc-400">{strat.match_reasons?.join(' • ')}</p>
                        {strat.entry_rules && (
                          <p className="text-[10px] text-cyan-400 mt-2">Entry: {strat.entry_rules}</p>
                        )}
                        {strat.stop_loss && (
                          <p className="text-[10px] text-red-400">Stop: {strat.stop_loss}</p>
                        )}
                      </div>
                    )) : (
                      <div className="text-center py-8 text-zinc-500">
                        <Target className="w-10 h-10 mx-auto mb-2 opacity-50" />
                        <p>No matching strategies found</p>
                        <p className="text-xs mt-1">Current conditions don&apos;t match your strategy criteria</p>
                      </div>
                    )}
                  </div>
                )}

                {/* NEWS TAB */}
                {activeTab === 'news' && (
                  <div className="space-y-3">
                    {news.length > 0 ? news.map((item, idx) => (
                      <div key={idx} className="bg-zinc-900 rounded-lg p-3 border-l-2 border-cyan-500/50">
                        <p className="text-sm text-white mb-1">{item.headline}</p>
                        <div className="flex items-center gap-2 text-xs text-zinc-500">
                          <span>{item.source}</span>
                          {item.timestamp && <span>{new Date(item.timestamp).toLocaleTimeString()}</span>}
                        </div>
                      </div>
                    )) : (
                      <div className="text-center py-8 text-zinc-500">
                        <Newspaper className="w-10 h-10 mx-auto mb-2 opacity-50" />
                        <p>No recent news</p>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 p-4 border-t border-white/10">
            <button 
              onClick={() => onTrade(ticker, 'BUY')}
              className="flex-1 py-2.5 text-sm font-bold bg-green-500 text-black rounded-lg hover:bg-green-400 transition-colors"
            >
              Buy {ticker.symbol}
            </button>
            <button 
              onClick={() => onTrade(ticker, 'SELL')}
              className="flex-1 py-2.5 text-sm font-bold bg-red-500 text-white rounded-lg hover:bg-red-400 transition-colors"
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
    earnings: true,
    squeeze: false,
    priceAlerts: false
  });
  
  // New P1 features state
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [shortSqueezeCandidates, setShortSqueezeCandidates] = useState([]);
  const [priceAlerts, setPriceAlerts] = useState([]);
  const [newAlertSymbol, setNewAlertSymbol] = useState('');
  const [newAlertPrice, setNewAlertPrice] = useState('');
  const [newAlertDirection, setNewAlertDirection] = useState('ABOVE');
  const [trackedOrders, setTrackedOrders] = useState([]);

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
    } catch {
      setShortSqueezeCandidates([]);
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
      fetchShortSqueeze();
      fetchPriceAlerts();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scan interval + order fill + price alert polling
  useEffect(() => {
    if (!autoScan || !isConnected) return;
    
    const interval = setInterval(() => {
      runScanner();
      fetchAccountData();
      fetchMarketContext();
      checkOrderFills();
      checkPriceAlerts();
    }, 60000);
    
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoScan, isConnected, selectedScanType, priceAlerts.length]);

  // Fast polling for order fills and price alerts (every 10s when enabled)
  useEffect(() => {
    if (!isConnected) return;
    
    const fastPoll = setInterval(() => {
      checkOrderFills();
      checkPriceAlerts();
    }, 10000);
    
    return () => clearInterval(fastPoll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected, soundEnabled, priceAlerts.length]);

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
                  <div 
                    key={idx} 
                    className="p-2 bg-zinc-900/50 rounded hover:bg-zinc-900 cursor-pointer transition-colors"
                    onClick={() => setSelectedTicker({ symbol: alert.symbol, quote: {} })}
                    data-testid={`alert-item-${alert.symbol}`}
                  >
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
                  today.setHours(0, 0, 0, 0);
                  earningsDate.setHours(0, 0, 0, 0);
                  const isToday = earningsDate.getTime() === today.getTime();
                  const tomorrow = new Date(today);
                  tomorrow.setDate(today.getDate() + 1);
                  const isTomorrow = earningsDate.getTime() === tomorrow.getTime();
                  
                  // Get data
                  const expectedMove = item.implied_volatility?.expected_move_percent || 0;
                  const ivRank = item.implied_volatility?.iv_rank || 0;
                  const avgReaction = item.avg_stock_reaction_4q || item.earnings_play?.avg_reaction || 0;
                  const earningsPlay = item.earnings_play || {};
                  const topStrategy = earningsPlay.strategies?.[0];
                  
                  // Historical reaction color based on direction and magnitude
                  const getReactionColor = (reaction) => {
                    if (reaction <= -10) return { bg: 'bg-red-500', text: 'text-red-400', label: 'Strong Bearish' };
                    if (reaction <= -7) return { bg: 'bg-orange-600', text: 'text-orange-400', label: 'Bearish' };
                    if (reaction <= -5) return { bg: 'bg-yellow-600', text: 'text-yellow-400', label: 'Slight Bearish' };
                    if (reaction < 0) return { bg: 'bg-cyan-600', text: 'text-cyan-400', label: 'Neutral Down' };
                    if (reaction <= 3) return { bg: 'bg-blue-500', text: 'text-blue-400', label: 'Neutral' };
                    if (reaction <= 5) return { bg: 'bg-sky-400', text: 'text-sky-300', label: 'Slight Bullish' };
                    if (reaction <= 7) return { bg: 'bg-emerald-400', text: 'text-emerald-300', label: 'Bullish' };
                    if (reaction <= 10) return { bg: 'bg-green-500', text: 'text-green-400', label: 'Strong Bullish' };
                    return { bg: 'bg-lime-400', text: 'text-lime-300', label: 'Very Bullish' };
                  };
                  
                  const reactionStyle = getReactionColor(avgReaction);
                  // Bar width: scale from -15% to +15% (30% range)
                  const barPosition = Math.max(0, Math.min(100, ((avgReaction + 15) / 30) * 100));
                  
                  return (
                    <div 
                      key={idx} 
                      className={`p-3 rounded-lg cursor-pointer transition-all hover:scale-[1.01] ${
                        isToday ? 'bg-orange-500/15 border border-orange-500/50' : 
                        isTomorrow ? 'bg-yellow-500/10 border border-yellow-500/30' : 
                        'bg-zinc-900/50 border border-white/5 hover:border-white/20'
                      }`}
                      onClick={() => setSelectedTicker({ symbol: item.symbol, quote: {}, earningsPlay: earningsPlay })}
                    >
                      {/* Top Row: Symbol, Badges, Time */}
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white">{item.symbol}</span>
                          {isToday && (
                            <span className="text-[9px] px-1.5 py-0.5 bg-orange-500 text-black rounded font-bold animate-pulse">
                              TODAY
                            </span>
                          )}
                          {isTomorrow && (
                            <span className="text-[9px] px-1.5 py-0.5 bg-yellow-500/30 text-yellow-400 rounded font-medium">
                              TOMORROW
                            </span>
                          )}
                          {earningsPlay.direction && (
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                              earningsPlay.direction === 'LONG' ? 'bg-green-500/30 text-green-400' : 'bg-red-500/30 text-red-400'
                            }`}>
                              {earningsPlay.direction}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px]">
                            {item.time === 'Before Open' ? '☀️' : '🌙'}
                          </span>
                          <span className="text-[10px] text-zinc-500">
                            {earningsDate.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                          </span>
                        </div>
                      </div>
                      
                      {/* Company Name */}
                      <p className="text-[10px] text-zinc-500 mb-2 truncate">{item.company_name}</p>
                      
                      {/* Historical Reaction Visualization */}
                      <div className="mb-2">
                        <div className="flex items-center justify-between text-[10px] mb-1">
                          <span className="text-zinc-500">Avg Historical Reaction</span>
                          <span className={`font-mono font-bold ${reactionStyle.text}`}>
                            {avgReaction >= 0 ? '+' : ''}{avgReaction.toFixed(1)}%
                          </span>
                        </div>
                        
                        {/* Gradient Bar with marker */}
                        <div className="relative h-2 rounded-full overflow-hidden bg-gradient-to-r from-red-500 via-yellow-500 via-50% to-lime-400">
                          {/* Center line (0%) */}
                          <div className="absolute top-0 bottom-0 left-1/2 w-px bg-white/50 z-10" />
                          {/* Position marker */}
                          <div 
                            className="absolute top-0 bottom-0 w-1 bg-white rounded-full shadow-lg z-20 transition-all"
                            style={{ left: `calc(${barPosition}% - 2px)` }}
                          />
                        </div>
                        <div className="flex justify-between text-[8px] text-zinc-600 mt-0.5">
                          <span>-15%</span>
                          <span>0%</span>
                          <span>+15%</span>
                        </div>
                      </div>
                      
                      {/* Expected Move & IV */}
                      <div className="flex items-center gap-3 text-[9px] mb-2">
                        <span className="text-zinc-500">
                          Exp Move: <span className="text-zinc-300 font-mono">±{expectedMove.toFixed(1)}%</span>
                        </span>
                        <span className="text-zinc-500">
                          IV Rank: <span className={ivRank >= 60 ? 'text-yellow-400' : 'text-zinc-300'}>{ivRank.toFixed(0)}%</span>
                        </span>
                        {earningsPlay.win_rate && (
                          <span className="text-zinc-500">
                            Win: <span className={earningsPlay.win_rate >= 60 ? 'text-green-400' : 'text-zinc-300'}>{earningsPlay.win_rate}%</span>
                          </span>
                        )}
                      </div>
                      
                      {/* Top Strategy */}
                      {topStrategy && (
                        <div className={`p-2 rounded text-[10px] ${
                          topStrategy.type?.includes('long') ? 'bg-green-500/10 border border-green-500/20' :
                          topStrategy.type?.includes('short') ? 'bg-red-500/10 border border-red-500/20' :
                          topStrategy.type?.includes('sell') ? 'bg-purple-500/10 border border-purple-500/20' :
                          'bg-cyan-500/10 border border-cyan-500/20'
                        }`}>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="font-bold text-white">{topStrategy.name}</span>
                            <span className="text-zinc-400">{topStrategy.confidence?.toFixed(0)}% conf</span>
                          </div>
                          <p className="text-zinc-400 text-[9px]">{topStrategy.reasoning}</p>
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

          {/* Short Squeeze Watchlist */}
          <Card>
            <button 
              onClick={() => toggleSection('squeeze')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-red-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Short Squeeze</h3>
                <span className="text-xs text-zinc-500">({shortSqueezeCandidates.length})</span>
              </div>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.squeeze ? 'rotate-180' : ''}`} />
            </button>
            
            {expandedSections.squeeze && (
              <div className="space-y-2">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] text-zinc-500 uppercase">High Short Interest Stocks</span>
                  <button 
                    onClick={fetchShortSqueeze}
                    className="text-[10px] text-cyan-400 hover:text-cyan-300"
                  >
                    Refresh
                  </button>
                </div>
                {shortSqueezeCandidates.length > 0 ? shortSqueezeCandidates.slice(0, 6).map((stock, idx) => (
                  <div 
                    key={idx}
                    className={`p-2 rounded cursor-pointer transition-all hover:bg-zinc-800 ${
                      stock.squeeze_risk === 'HIGH' ? 'bg-red-500/10 border border-red-500/30' :
                      stock.squeeze_risk === 'MEDIUM' ? 'bg-yellow-500/10 border border-yellow-500/20' :
                      'bg-zinc-900/50 border border-white/5'
                    }`}
                    onClick={() => setSelectedTicker({ symbol: stock.symbol, quote: { price: stock.price, change_percent: stock.change_percent } })}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{stock.symbol}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                          stock.squeeze_risk === 'HIGH' ? 'bg-red-500 text-white' :
                          stock.squeeze_risk === 'MEDIUM' ? 'bg-yellow-500 text-black' :
                          'bg-zinc-600 text-white'
                        }`}>
                          {stock.squeeze_score}
                        </span>
                      </div>
                      <span className={`text-xs font-mono ${stock.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {formatPercent(stock.change_percent)}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[9px]">
                      <div>
                        <span className="text-zinc-500">SI%: </span>
                        <span className="text-red-400 font-mono">{stock.short_interest_pct?.toFixed(1)}%</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">DTC: </span>
                        <span className="text-yellow-400 font-mono">{stock.days_to_cover?.toFixed(1)}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">RVOL: </span>
                        <span className="text-cyan-400 font-mono">{stock.rvol?.toFixed(1)}x</span>
                      </div>
                    </div>
                  </div>
                )) : (
                  <p className="text-center text-zinc-500 text-sm py-4">No squeeze candidates found</p>
                )}
              </div>
            )}
          </Card>

          {/* Price Alerts */}
          <Card>
            <button 
              onClick={() => toggleSection('priceAlerts')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Bell className="w-5 h-5 text-purple-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Price Alerts</h3>
                <span className="text-xs text-zinc-500">({priceAlerts.length})</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); setSoundEnabled(!soundEnabled); }}
                  className={`p-1 rounded ${soundEnabled ? 'text-green-400' : 'text-zinc-500'}`}
                >
                  {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                </button>
                <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.priceAlerts ? 'rotate-180' : ''}`} />
              </div>
            </button>
            
            {expandedSections.priceAlerts && (
              <div className="space-y-3">
                {/* Create new alert */}
                <div className="flex items-center gap-2 p-2 bg-zinc-900/50 rounded">
                  <input
                    type="text"
                    value={newAlertSymbol}
                    onChange={(e) => setNewAlertSymbol(e.target.value.toUpperCase())}
                    placeholder="Symbol"
                    className="w-20 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-xs text-white placeholder-zinc-500"
                  />
                  <select
                    value={newAlertDirection}
                    onChange={(e) => setNewAlertDirection(e.target.value)}
                    className="px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-xs text-white"
                  >
                    <option value="ABOVE">Above</option>
                    <option value="BELOW">Below</option>
                  </select>
                  <input
                    type="number"
                    value={newAlertPrice}
                    onChange={(e) => setNewAlertPrice(e.target.value)}
                    placeholder="Price"
                    className="w-24 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-xs text-white placeholder-zinc-500"
                  />
                  <button
                    onClick={createPriceAlert}
                    disabled={!newAlertSymbol || !newAlertPrice}
                    className="p-1.5 bg-purple-500 text-white rounded hover:bg-purple-400 disabled:opacity-50"
                  >
                    <Plus className="w-3.5 h-3.5" />
                  </button>
                </div>
                
                {/* Active alerts */}
                <div className="space-y-1.5">
                  {priceAlerts.length > 0 ? priceAlerts.map((alert, idx) => (
                    <div key={idx} className="flex items-center justify-between p-2 bg-zinc-900/50 rounded group">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-purple-400">{alert.symbol}</span>
                        <span className={`text-xs ${alert.direction === 'ABOVE' ? 'text-green-400' : 'text-red-400'}`}>
                          {alert.direction === 'ABOVE' ? '↑' : '↓'} ${alert.target_price?.toFixed(2)}
                        </span>
                      </div>
                      <button
                        onClick={() => deletePriceAlert(alert.id)}
                        className="p-1 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )) : (
                    <p className="text-center text-zinc-500 text-xs py-2">No active alerts</p>
                  )}
                </div>
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
