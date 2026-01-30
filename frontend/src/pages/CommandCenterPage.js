import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Zap,
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
import api, { apiLongRunning } from '../utils/api';
import { toast } from 'sonner';
import AIAssistant from '../components/AIAssistant';
import TickerDetailModal from '../components/TickerDetailModal';
import QuickTradeModal from '../components/QuickTradeModal';
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

// ===================== TICKER DETAIL MODAL =====================
const TickerDetailModal = ({ ticker, onClose, onTrade, onAskAI }) => {
  const [analysis, setAnalysis] = useState(null);
  const [historicalData, setHistoricalData] = useState(null);
  const [qualityData, setQualityData] = useState(null);
  const [earningsData, setEarningsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [showTradingLines, setShowTradingLines] = useState(true);
  const [chartError, setChartError] = useState(null);
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);

  useEffect(() => {
    if (!ticker?.symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      setChartError(null);
      
      // Helper to retry on failure
      const fetchWithRetry = async (fetcher, retries = 2, delay = 1000) => {
        for (let i = 0; i <= retries; i++) {
          try {
            const result = await fetcher();
            return result;
          } catch (err) {
            if (i === retries) throw err;
            console.log(`Retrying... attempt ${i + 2}`);
            await new Promise(r => setTimeout(r, delay));
          }
        }
      };
      
      try {
        // Fetch comprehensive analysis including quality score and earnings
        const [analysisRes, histRes, qualityRes, earningsRes] = await Promise.all([
          fetchWithRetry(() => api.get(`/api/ib/analysis/${ticker.symbol}`)).catch((err) => {
            console.error('Analysis API error:', err);
            return { data: null };
          }),
          fetchWithRetry(() => api.get(`/api/ib/historical/${ticker.symbol}?duration=1 D&bar_size=5 mins`)).catch((err) => {
            console.error('Historical data error:', err);
            const errorMsg = err.response?.data?.detail?.message || err.response?.data?.detail || 'Unable to load chart data';
            // Check if IB is busy
            if (err.response?.data?.ib_busy || errorMsg.includes('busy')) {
              setChartError('IB Gateway is busy with a scan. Using cached/Alpaca data.');
            } else {
              setChartError(errorMsg);
            }
            return { data: { bars: [] } };
          }),
          fetchWithRetry(() => api.get(`/api/quality/score/${ticker.symbol}`)).catch((err) => {
            console.error('Quality score error:', err);
            return { data: null };
          }),
          fetchWithRetry(() => api.get(`/api/newsletter/earnings/${ticker.symbol}`)).catch((err) => {
            console.error('Earnings data error:', err);
            return { data: null };
          })
        ]);
        
        console.log('Analysis data received:', analysisRes.data);
        console.log('Historical data received:', histRes.data?.bars?.length, 'bars');
        console.log('Quality data received:', qualityRes.data);
        console.log('Earnings data received:', earningsRes.data);
        
        // Check if IB was busy - show info message but still display data
        if (analysisRes.data?.ib_busy) {
          console.log('IB was busy, data came from Alpaca');
        }
        
        setAnalysis(analysisRes.data);
        setHistoricalData(histRes.data?.bars || []);
        setQualityData(qualityRes.data);
        setEarningsData(earningsRes.data);
      } catch (err) {
        console.error('Error fetching data:', err);
        setChartError('Failed to load data. Please try again.');
      }
      setLoading(false);
    };
    
    fetchData();
  }, [ticker?.symbol]);

  // Create chart when tab changes to chart
  useEffect(() => {
    if (activeTab !== 'chart' || !chartContainerRef.current) return;
    
    // Clean up existing chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    }
    
    // Delay to ensure container is rendered with dimensions
    const timer = setTimeout(() => {
      if (!chartContainerRef.current) return;
      
      const container = chartContainerRef.current;
      const width = container.clientWidth || 700;
      const height = container.clientHeight || 300;
      
      console.log('Creating chart with dimensions:', width, 'x', height);
      
      try {
        const chart = LightweightCharts.createChart(container, {
          width,
          height,
          layout: {
            background: { type: 'solid', color: '#0A0A0A' },
            textColor: '#9CA3AF',
          },
          grid: {
            vertLines: { color: '#1F2937' },
            horzLines: { color: '#1F2937' },
          },
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
            vertLine: { color: '#00E5FF', width: 1, style: 2 },
            horzLine: { color: '#00E5FF', width: 1, style: 2 },
          },
        });
        
        chartRef.current = chart;
        
        const candleSeries = chart.addCandlestickSeries({
          upColor: '#00FF94',
          downColor: '#FF2E2E',
          borderUpColor: '#00FF94',
          borderDownColor: '#FF2E2E',
          wickUpColor: '#00FF94',
          wickDownColor: '#FF2E2E',
        });
        candleSeriesRef.current = candleSeries;
        
        console.log('Chart created successfully');
        
        // Handle resize
        const handleResize = () => {
          if (chartRef.current && container) {
            chartRef.current.applyOptions({ 
              width: container.clientWidth,
              height: container.clientHeight || 300
            });
          }
        };
        window.addEventListener('resize', handleResize);
        
        return () => window.removeEventListener('resize', handleResize);
        
      } catch (err) {
        console.error('Error creating chart:', err);
        setChartError('Failed to initialize chart');
      }
    }, 150);
    
    return () => {
      clearTimeout(timer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
      }
    };
  }, [activeTab]);

  // Set chart data when data or chart changes
  useEffect(() => {
    if (!candleSeriesRef.current || !historicalData || historicalData.length === 0) return;
    
    console.log('Setting chart data:', historicalData.length, 'bars');
    
    try {
      const chartData = historicalData.map(bar => ({
        time: Math.floor(new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000),
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
      })).sort((a, b) => a.time - b.time);
      
      console.log('Formatted chart data - First:', chartData[0], 'Last:', chartData[chartData.length - 1]);
      
      candleSeriesRef.current.setData(chartData);
      
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
      }
      
      // Add price lines for SL/TP
      if (showTradingLines && analysis?.trading_summary) {
        const ts = analysis.trading_summary;
        
        if (ts.entry) {
          candleSeriesRef.current.createPriceLine({
            price: ts.entry,
            color: '#00E5FF',
            lineWidth: 2,
            lineStyle: 0,
            axisLabelVisible: true,
            title: 'Entry',
          });
        }
        
        if (ts.stop_loss) {
          candleSeriesRef.current.createPriceLine({
            price: ts.stop_loss,
            color: '#FF2E2E',
            lineWidth: 2,
            lineStyle: 2,
            axisLabelVisible: true,
            title: 'Stop',
          });
        }
        
        if (ts.target) {
          candleSeriesRef.current.createPriceLine({
            price: ts.target,
            color: '#00FF94',
            lineWidth: 2,
            lineStyle: 2,
            axisLabelVisible: true,
            title: 'Target',
          });
        }
      }
      
      console.log('Chart data set successfully');
      
    } catch (err) {
      console.error('Error setting chart data:', err);
    }
  }, [historicalData, analysis, showTradingLines, activeTab]);

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
  const quality = qualityData?.data || {};
  const qualityMetrics = qualityData?.metrics || {};

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'technicals', label: 'Technicals' },
    { id: 'fundamentals', label: 'Fundamentals' },
    { id: 'earnings', label: 'Earnings' },
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
                  {quality.grade && (
                    <span className={`text-xs px-2 py-0.5 rounded font-bold ${
                      quality.grade?.startsWith('A') ? 'bg-emerald-500 text-black' :
                      quality.grade?.startsWith('B') ? 'bg-blue-500 text-black' :
                      quality.grade?.startsWith('C') ? 'bg-yellow-500 text-black' :
                      'bg-red-500 text-white'
                    }`} title="Earnings Quality Grade">
                      Q:{quality.grade}
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
              {onAskAI && (
                <button 
                  onClick={() => onAskAI(ticker.symbol)}
                  className="p-2 rounded-lg hover:bg-amber-500/20 text-amber-400 transition-colors"
                  title="Ask AI about this stock"
                >
                  <Bot className="w-5 h-5" />
                </button>
              )}
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
            ) : !analysis && !historicalData?.length ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <AlertTriangle className="w-12 h-12 text-yellow-500 mb-4" />
                <p className="text-lg font-semibold text-white mb-2">Unable to Load Data</p>
                <p className="text-sm text-zinc-400 mb-4">
                  {chartError || 'Could not fetch analysis data. This may happen if IB Gateway is busy with a scan. Try again in a moment.'}
                </p>
                <div className="flex gap-3">
                  <button 
                    onClick={() => {
                      // Retry fetching
                      setLoading(true);
                      setChartError(null);
                      setTimeout(() => {
                        api.get(`/api/ib/analysis/${ticker?.symbol}`).then(res => {
                          setAnalysis(res.data);
                          setLoading(false);
                        }).catch(() => {
                          setChartError('Still unable to load. IB may be busy.');
                          setLoading(false);
                        });
                      }, 500);
                    }}
                    className="px-4 py-2 bg-cyan-600 text-white rounded hover:bg-cyan-500"
                  >
                    Retry
                  </button>
                  <button 
                    onClick={onClose}
                    className="px-4 py-2 bg-zinc-800 text-white rounded hover:bg-zinc-700"
                  >
                    Close
                  </button>
                </div>
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
                        { label: 'Overall', value: scores.overall, color: scores.overall >= 70 ? 'cyan' : scores.overall >= 50 ? 'yellow' : 'red', termId: 'overall-score' },
                        { label: 'Technical', value: scores.technical_score, color: 'blue', termId: 'technical-score' },
                        { label: 'Fundamental', value: scores.fundamental_score, color: 'purple', termId: 'fundamental-score' },
                        { label: 'Catalyst', value: scores.catalyst_score, color: 'orange', termId: 'catalyst-score' },
                        { label: 'Confidence', value: scores.confidence, color: 'green', termId: 'confidence-score' },
                      ].map((score, idx) => (
                        <div key={idx} className="bg-zinc-900 rounded-lg p-3 text-center">
                          <span className="text-[10px] text-zinc-500 uppercase block">
                            <HelpTooltip termId={score.termId}>{score.label}</HelpTooltip>
                          </span>
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

                    {/* AI Strategy Recommendation Box */}
                    <div className="bg-gradient-to-r from-amber-500/10 to-cyan-500/10 border border-amber-500/20 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Sparkles className="w-5 h-5 text-amber-400" />
                          <span className="text-sm font-semibold text-white">AI Trading Recommendation</span>
                        </div>
                        <button
                          onClick={() => onAskAI(ticker.symbol)}
                          className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/20 text-amber-400 rounded text-xs hover:bg-amber-500/30 border border-amber-500/30"
                        >
                          <Bot className="w-3 h-3" />
                          Ask AI for Deep Analysis
                        </button>
                      </div>
                      
                      {/* Quick AI Summary */}
                      <div className="space-y-2">
                        {/* Trade Recommendation */}
                        <div className="flex items-start gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded font-bold ${
                            tradingSummary.bias === 'BULLISH' ? 'bg-green-500 text-black' :
                            tradingSummary.bias === 'BEARISH' ? 'bg-red-500 text-white' :
                            'bg-zinc-600 text-white'
                          }`}>
                            {tradingSummary.bias || 'NEUTRAL'}
                          </span>
                          <p className="text-xs text-zinc-300 flex-1">
                            {tradingSummary.bias === 'BULLISH' && scores.overall >= 60 
                              ? `${ticker.symbol} shows strong bullish momentum. Consider LONG positions with tight risk management.`
                              : tradingSummary.bias === 'BEARISH' && scores.overall >= 60
                              ? `${ticker.symbol} shows bearish weakness. Consider SHORT positions or avoid longs.`
                              : `${ticker.symbol} is showing mixed signals. Wait for clearer direction before entering.`
                            }
                          </p>
                        </div>
                        
                        {/* Key Points */}
                        <div className="grid grid-cols-2 gap-2 mt-2">
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 block">Best Strategy</span>
                            <p className="text-xs text-white font-medium">
                              {matchedStrategies[0]?.name || 'No match found'}
                            </p>
                          </div>
                          <div className="bg-black/30 rounded p-2">
                            <span className="text-[10px] text-zinc-500 block">Timeframe</span>
                            <p className="text-xs text-white font-medium">
                              {matchedStrategies[0]?.timeframe || 'Intraday'}
                            </p>
                          </div>
                        </div>
                        
                        {/* Risk Warning */}
                        {scores.overall < 50 && (
                          <div className="flex items-center gap-2 mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded">
                            <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                            <p className="text-[10px] text-red-300">
                              Low score ({scores.overall}/100) - Higher risk setup. Consider smaller position size or skip.
                            </p>
                          </div>
                        )}
                        
                        {/* High Conviction Indicator */}
                        {scores.overall >= 70 && tradingSummary.bias && (
                          <div className="flex items-center gap-2 mt-2 p-2 bg-green-500/10 border border-green-500/20 rounded">
                            <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0" />
                            <p className="text-[10px] text-green-300">
                              High conviction setup! Score: {scores.overall}/100 with clear {tradingSummary.bias.toLowerCase()} bias.
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* CHART TAB */}
                {activeTab === 'chart' && (
                  <div>
                    {/* Chart Controls */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-zinc-500">5-min Candles</span>
                        {analysis?.is_cached && (
                          <span className="text-[9px] px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                            Cached: {new Date(analysis?.last_updated).toLocaleTimeString()}
                          </span>
                        )}
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
                    
                    {/* Chart Error Message */}
                    {chartError && (
                      <div className="flex items-center justify-center h-[300px] bg-zinc-900/50 rounded border border-zinc-800">
                        <div className="text-center">
                          <AlertTriangle className="w-8 h-8 text-yellow-500 mx-auto mb-2" />
                          <p className="text-sm text-zinc-400">{chartError}</p>
                          <p className="text-xs text-zinc-500 mt-1">Connect IB Gateway for real-time data</p>
                        </div>
                      </div>
                    )}
                    
                    {/* Chart Container */}
                    {!chartError && (
                      <div 
                        ref={chartContainerRef} 
                        className="w-full border border-zinc-800 rounded" 
                        style={{ height: '300px', minHeight: '300px', minWidth: '400px', background: '#0A0A0A' }} 
                      />
                    )}
                    
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
                      { label: 'RSI (14)', value: technicals.rsi_14?.toFixed(1), suffix: '', color: technicals.rsi_14 > 70 ? 'red' : technicals.rsi_14 < 30 ? 'green' : 'zinc', termId: 'rsi' },
                      { label: 'RVOL', value: technicals.rvol?.toFixed(1), suffix: 'x', color: technicals.rvol > 2 ? 'cyan' : 'zinc', termId: 'rvol' },
                      { label: 'VWAP', value: '$' + technicals.vwap?.toFixed(2), suffix: '', color: 'purple', termId: 'vwap' },
                      { label: 'VWAP Dist', value: technicals.vwap_distance_pct?.toFixed(1), suffix: '%', color: technicals.vwap_distance_pct > 0 ? 'green' : 'red', termId: 'vwap-dist' },
                      { label: 'EMA 9', value: '$' + technicals.ema_9?.toFixed(2), suffix: '', color: 'blue', termId: 'ema-9' },
                      { label: 'EMA 20', value: '$' + technicals.ema_20?.toFixed(2), suffix: '', color: 'blue', termId: 'ema-20' },
                      { label: 'SMA 50', value: '$' + technicals.sma_50?.toFixed(2), suffix: '', color: 'yellow', termId: 'sma-50' },
                      { label: 'ATR (14)', value: '$' + technicals.atr_14?.toFixed(2), suffix: '', color: 'orange', termId: 'atr' },
                      { label: 'MACD', value: technicals.macd?.toFixed(3), suffix: '', color: technicals.macd > 0 ? 'green' : 'red', termId: 'macd' },
                      { label: 'MACD Signal', value: technicals.macd_signal?.toFixed(3), suffix: '', color: 'zinc', termId: 'macd' },
                      { label: 'Volume Trend', value: technicals.volume_trend, suffix: '', color: technicals.volume_trend === 'Above Avg' ? 'green' : 'zinc', termId: 'volume' },
                      { label: 'Trend', value: technicals.trend, suffix: '', color: technicals.trend === 'Bullish' ? 'green' : 'red', termId: 'trend' },
                    ].map((item, idx) => (
                      <div key={idx} className="bg-zinc-900 rounded-lg p-3">
                        <span className="text-[10px] text-zinc-500 uppercase block">
                          <HelpTooltip termId={item.termId}>{item.label}</HelpTooltip>
                        </span>
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

                {/* EARNINGS TAB */}
                {activeTab === 'earnings' && (
                  <div className="space-y-4">
                    {earningsData?.available ? (
                      <>
                        {/* Earnings Summary Header */}
                        <div className={`p-4 rounded-lg border ${
                          earningsData.summary?.overall_rating === 'strong' ? 'border-green-500/30 bg-green-500/5' :
                          earningsData.summary?.overall_rating === 'good' ? 'border-cyan-500/30 bg-cyan-500/5' :
                          earningsData.summary?.overall_rating === 'weak' ? 'border-red-500/30 bg-red-500/5' :
                          'border-zinc-700 bg-zinc-900/50'
                        }`}>
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                              <span className={`text-2xl font-bold px-4 py-2 rounded-lg ${
                                earningsData.summary?.overall_rating === 'strong' ? 'bg-green-500 text-black' :
                                earningsData.summary?.overall_rating === 'good' ? 'bg-cyan-500 text-black' :
                                earningsData.summary?.overall_rating === 'weak' ? 'bg-red-500 text-white' :
                                'bg-zinc-700 text-white'
                              }`}>
                                {earningsData.summary?.overall_rating?.toUpperCase() || 'NEUTRAL'}
                              </span>
                              <div>
                                <p className="text-white font-semibold">Earnings Performance</p>
                                <p className="text-xs text-zinc-400">
                                  {earningsData.trends?.total_quarters || 0} quarters analyzed
                                </p>
                              </div>
                            </div>
                            {earningsData.trends && (
                              <div className="text-right">
                                <p className="text-2xl font-mono font-bold text-white">{earningsData.trends.eps_beat_rate?.toFixed(0)}%</p>
                                <p className="text-xs text-zinc-500">EPS Beat Rate</p>
                              </div>
                            )}
                          </div>
                          
                          {/* Key Points */}
                          {earningsData.summary?.key_points?.length > 0 && (
                            <div className="mt-3 space-y-1">
                              {earningsData.summary.key_points.map((point, idx) => (
                                <div key={idx} className="flex items-start gap-2 text-sm">
                                  <span className="text-green-400">✓</span>
                                  <span className="text-zinc-300">{point}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          
                          {/* Risks */}
                          {earningsData.summary?.risks?.length > 0 && (
                            <div className="mt-3 space-y-1">
                              {earningsData.summary.risks.map((risk, idx) => (
                                <div key={idx} className="flex items-start gap-2 text-sm">
                                  <span className="text-red-400">⚠</span>
                                  <span className="text-zinc-300">{risk}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          
                          {/* Opportunities */}
                          {earningsData.summary?.opportunities?.length > 0 && (
                            <div className="mt-3 space-y-1">
                              {earningsData.summary.opportunities.map((opp, idx) => (
                                <div key={idx} className="flex items-start gap-2 text-sm">
                                  <span className="text-cyan-400">★</span>
                                  <span className="text-zinc-300">{opp}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Beat/Miss Stats */}
                        {earningsData.trends && (
                          <div className="grid grid-cols-2 gap-3">
                            <div className="bg-zinc-900 rounded-lg p-3">
                              <p className="text-xs text-zinc-500 uppercase mb-2">EPS Performance</p>
                              <div className="flex items-center justify-between">
                                <div className="text-center">
                                  <p className="text-lg font-bold text-green-400">{earningsData.trends.eps_beats}</p>
                                  <p className="text-[10px] text-zinc-500">Beats</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-red-400">{earningsData.trends.eps_misses}</p>
                                  <p className="text-[10px] text-zinc-500">Misses</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-cyan-400">{earningsData.trends.eps_beat_rate?.toFixed(0)}%</p>
                                  <p className="text-[10px] text-zinc-500">Beat Rate</p>
                                </div>
                              </div>
                            </div>
                            <div className="bg-zinc-900 rounded-lg p-3">
                              <p className="text-xs text-zinc-500 uppercase mb-2">Revenue Performance</p>
                              <div className="flex items-center justify-between">
                                <div className="text-center">
                                  <p className="text-lg font-bold text-green-400">{earningsData.trends.rev_beats}</p>
                                  <p className="text-[10px] text-zinc-500">Beats</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-red-400">{earningsData.trends.rev_misses}</p>
                                  <p className="text-[10px] text-zinc-500">Misses</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-cyan-400">{earningsData.trends.rev_beat_rate?.toFixed(0)}%</p>
                                  <p className="text-[10px] text-zinc-500">Beat Rate</p>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Next Earnings Alert */}
                        {earningsData.next_earnings && (
                          <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <Calendar className="w-4 h-4 text-amber-400" />
                              <span className="text-sm font-semibold text-amber-400">Upcoming Earnings</span>
                            </div>
                            <div className="flex items-center justify-between">
                              <div>
                                <p className="text-white font-mono">{earningsData.next_earnings.date}</p>
                                <p className="text-xs text-zinc-400">
                                  {earningsData.next_earnings.hour === 'bmo' ? 'Before Market Open' : 
                                   earningsData.next_earnings.hour === 'amc' ? 'After Market Close' : 
                                   earningsData.next_earnings.hour?.toUpperCase() || 'Time TBD'}
                                </p>
                              </div>
                              {earningsData.next_earnings.eps_estimate !== null && (
                                <div className="text-right">
                                  <p className="text-xs text-zinc-500">EPS Estimate</p>
                                  <p className="text-lg font-mono text-white">${earningsData.next_earnings.eps_estimate?.toFixed(2)}</p>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Earnings History Table */}
                        {earningsData.earnings_history?.length > 0 && (
                          <div className="bg-zinc-900/50 rounded-lg overflow-hidden">
                            <div className="p-3 border-b border-zinc-800">
                              <p className="text-sm font-semibold text-white">Earnings History</p>
                            </div>
                            <div className="overflow-x-auto">
                              <table className="w-full text-xs">
                                <thead className="bg-zinc-800/50">
                                  <tr>
                                    <th className="px-3 py-2 text-left text-zinc-400">Date</th>
                                    <th className="px-3 py-2 text-right text-zinc-400">EPS Est</th>
                                    <th className="px-3 py-2 text-right text-zinc-400">EPS Act</th>
                                    <th className="px-3 py-2 text-right text-zinc-400">Surprise</th>
                                    <th className="px-3 py-2 text-center text-zinc-400">Result</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                  {earningsData.earnings_history.filter(e => e.is_reported).slice(0, 8).map((earning, idx) => (
                                    <tr key={idx} className="hover:bg-zinc-800/30">
                                      <td className="px-3 py-2 text-white font-mono">{earning.date}</td>
                                      <td className="px-3 py-2 text-right text-zinc-400">
                                        {earning.eps_estimate !== null ? `$${earning.eps_estimate.toFixed(2)}` : '--'}
                                      </td>
                                      <td className="px-3 py-2 text-right text-white font-mono">
                                        {earning.eps_actual !== null ? `$${earning.eps_actual.toFixed(2)}` : '--'}
                                      </td>
                                      <td className={`px-3 py-2 text-right font-mono ${
                                        earning.eps_surprise_pct > 0 ? 'text-green-400' : 
                                        earning.eps_surprise_pct < 0 ? 'text-red-400' : 'text-zinc-400'
                                      }`}>
                                        {earning.eps_surprise_pct !== null ? `${earning.eps_surprise_pct > 0 ? '+' : ''}${earning.eps_surprise_pct.toFixed(1)}%` : '--'}
                                      </td>
                                      <td className="px-3 py-2 text-center">
                                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                          earning.eps_result === 'BEAT' ? 'bg-green-500/20 text-green-400' :
                                          earning.eps_result === 'MISS' ? 'bg-red-500/20 text-red-400' :
                                          'bg-zinc-500/20 text-zinc-400'
                                        }`}>
                                          {earning.eps_result || '--'}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        {/* Growth Metrics */}
                        {earningsData.metrics && (
                          <div className="bg-zinc-900/50 rounded-lg p-3">
                            <p className="text-xs text-zinc-500 uppercase mb-3">Growth Metrics</p>
                            <div className="grid grid-cols-3 gap-3">
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">EPS Growth (YoY)</p>
                                <p className={`text-sm font-mono font-bold ${
                                  earningsData.metrics.eps_growth_ttm_yoy > 0 ? 'text-green-400' : 
                                  earningsData.metrics.eps_growth_ttm_yoy < 0 ? 'text-red-400' : 'text-white'
                                }`}>
                                  {earningsData.metrics.eps_growth_ttm_yoy !== null ? 
                                    `${earningsData.metrics.eps_growth_ttm_yoy > 0 ? '+' : ''}${earningsData.metrics.eps_growth_ttm_yoy.toFixed(1)}%` : '--'}
                                </p>
                              </div>
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">Revenue Growth (YoY)</p>
                                <p className={`text-sm font-mono font-bold ${
                                  earningsData.metrics.revenue_growth_quarterly_yoy > 0 ? 'text-green-400' : 
                                  earningsData.metrics.revenue_growth_quarterly_yoy < 0 ? 'text-red-400' : 'text-white'
                                }`}>
                                  {earningsData.metrics.revenue_growth_quarterly_yoy !== null ? 
                                    `${earningsData.metrics.revenue_growth_quarterly_yoy > 0 ? '+' : ''}${earningsData.metrics.revenue_growth_quarterly_yoy.toFixed(1)}%` : '--'}
                                </p>
                              </div>
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">Growth Trend</p>
                                <p className={`text-sm font-bold ${
                                  earningsData.growth_trend === 'accelerating' ? 'text-green-400' :
                                  earningsData.growth_trend === 'growing' ? 'text-cyan-400' :
                                  earningsData.growth_trend === 'slowing' ? 'text-yellow-400' :
                                  earningsData.growth_trend === 'decelerating' ? 'text-red-400' : 'text-zinc-400'
                                }`}>
                                  {earningsData.growth_trend?.toUpperCase() || 'NEUTRAL'}
                                </p>
                              </div>
                            </div>
                            
                            {/* Valuation Metrics */}
                            <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-zinc-800">
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">P/E</p>
                                <p className="text-sm font-mono text-white">
                                  {earningsData.metrics.pe_ratio !== null ? earningsData.metrics.pe_ratio.toFixed(1) : '--'}
                                </p>
                              </div>
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">Fwd P/E</p>
                                <p className="text-sm font-mono text-white">
                                  {earningsData.metrics.forward_pe !== null ? earningsData.metrics.forward_pe.toFixed(1) : '--'}
                                </p>
                              </div>
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">PEG</p>
                                <p className="text-sm font-mono text-white">
                                  {earningsData.metrics.peg_ratio !== null ? earningsData.metrics.peg_ratio.toFixed(2) : '--'}
                                </p>
                              </div>
                              <div className="text-center">
                                <p className="text-[10px] text-zinc-500">EPS TTM</p>
                                <p className="text-sm font-mono text-white">
                                  {earningsData.metrics.eps_ttm !== null ? `$${earningsData.metrics.eps_ttm.toFixed(2)}` : '--'}
                                </p>
                              </div>
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="text-center py-12 text-zinc-500">
                        <Calendar className="w-10 h-10 mx-auto mb-2 opacity-50" />
                        <p>Earnings data unavailable</p>
                        <p className="text-xs mt-1">{earningsData?.error || 'Unable to fetch earnings data'}</p>
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

      {/* Main Content - Panels in Order */}
      <div className="space-y-4">
        {/* Holdings & Watchlist Row */}
        <div className="grid lg:grid-cols-2 gap-4">
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
        </div>

        {/* 1. Market Intelligence */}
        <Card>
          <div 
            onClick={() => toggleSection('news')}
            className="w-full flex items-center justify-between mb-3 cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-purple-400" />
              <h3 className="text-sm font-semibold uppercase tracking-wider">Market Intelligence</h3>
              {isGeneratingIntelligence && (
                <RefreshCw className="w-4 h-4 text-purple-400 animate-spin" />
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* Auto-Schedule Toggle */}
              <button
                onClick={(e) => { e.stopPropagation(); togglePremarketSchedule(); }}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  premarketScheduled 
                    ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
                    : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
                }`}
                title={premarketScheduled ? 'Auto-generates at 6:30 AM ET' : 'Enable daily pre-market briefing'}
              >
                <Clock className="w-3 h-3 inline mr-1" />
                {premarketScheduled ? '6:30 AM' : 'Schedule'}
              </button>
              {isConnected && (
                <button
                  onClick={(e) => { e.stopPropagation(); autoGenerateMarketIntelligence(); }}
                  disabled={isGeneratingIntelligence}
                  className="text-xs text-purple-400 hover:text-purple-300 disabled:opacity-50"
                >
                  {isGeneratingIntelligence ? 'Generating...' : 'Refresh'}
                </button>
              )}
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.news ? 'rotate-180' : ''}`} />
            </div>
          </div>
          
          {expandedSections.news && (
            <div className="space-y-3">
              {/* Loading State */}
              {isGeneratingIntelligence && (
                <div className="text-center py-6">
                  <RefreshCw className="w-8 h-8 text-purple-400 mx-auto mb-2 animate-spin" />
                  <p className="text-sm text-purple-400">Analyzing markets...</p>
                  <p className="text-xs text-zinc-500 mt-1">Gathering news, stocks, and world events</p>
                </div>
              )}
              
              {/* Content */}
              {!isGeneratingIntelligence && newsletter && newsletter.summary && !newsletter.needs_generation ? (
                <>
                  {/* Sentiment Badge & Date */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
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
                  </div>
                  
                  {/* Summary */}
                  <p className="text-sm text-zinc-300 leading-relaxed">{newsletter.summary}</p>
                  
                  {/* Key Levels */}
                  {newsletter.market_outlook?.key_levels && (
                    <div className="p-2 bg-purple-500/10 border border-purple-500/30 rounded text-xs">
                      <span className="text-purple-400 font-semibold">Key Levels: </span>
                      <span className="text-zinc-300">
                        {typeof newsletter.market_outlook.key_levels === 'string' 
                          ? newsletter.market_outlook.key_levels 
                          : Object.entries(newsletter.market_outlook.key_levels || {}).map(([sym, levels]) => 
                              `${sym}: R ${levels?.resistance || 'N/A'} / S ${levels?.support || 'N/A'}`
                            ).join(' | ')
                        }
                      </span>
                    </div>
                  )}
                  
                  {/* Top Stories */}
                  {newsletter.top_stories?.length > 0 && (
                    <div className="space-y-1.5">
                      <span className="text-[10px] text-zinc-500 uppercase">Top Stories</span>
                      {newsletter.top_stories.slice(0, 3).map((story, idx) => (
                        <div key={idx} className="p-2 bg-zinc-900/50 rounded text-xs text-zinc-400">
                          {story.headline || story}
                        </div>
                      ))}
                    </div>
                  )}
                  
                  {/* Opportunities */}
                  {newsletter.opportunities?.length > 0 && (
                    <div className="space-y-1.5">
                      <span className="text-[10px] text-zinc-500 uppercase">Opportunities</span>
                      {newsletter.opportunities.slice(0, 4).map((opp, idx) => {
                        const symbol = opp.symbol || opp.ticker || opp.stock || 'N/A';
                        const hasSymbol = symbol && symbol !== 'N/A';
                        return (
                          <div 
                            key={idx} 
                            className={`flex items-center justify-between p-2 bg-zinc-900/50 rounded text-sm ${hasSymbol ? 'cursor-pointer hover:bg-zinc-800' : ''}`}
                            onClick={() => {
                              if (hasSymbol && symbol.length <= 5 && /^[A-Z]+$/.test(symbol)) {
                                setSelectedTicker({ symbol, quote: {} });
                              }
                            }}
                          >
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <span className="font-bold text-cyan-400">{symbol}</span>
                              {opp.entry && (
                                <span className="text-xs text-zinc-500">Entry: ${opp.entry}</span>
                              )}
                              {opp.target && (
                                <span className="text-xs text-green-500">→ ${opp.target}</span>
                              )}
                              {opp.reasoning && !opp.entry && (
                                <span className="text-xs text-zinc-500 truncate">{opp.reasoning.slice(0, 30)}...</span>
                              )}
                            </div>
                            <Badge variant={opp.direction === 'LONG' ? 'success' : opp.direction === 'SHORT' ? 'error' : 'neutral'}>
                              {opp.direction || 'WATCH'}
                            </Badge>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  
                  {/* Risk Factors */}
                  {newsletter.risk_factors?.length > 0 && (
                    <div className="p-2 bg-red-500/10 border border-red-500/30 rounded">
                      <span className="text-[10px] text-red-400 uppercase block mb-1">Risk Factors</span>
                      <ul className="text-xs text-zinc-400 space-y-0.5">
                        {newsletter.risk_factors.slice(0, 3).map((risk, idx) => (
                          <li key={idx}>• {risk}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  
                  {/* Game Plan */}
                  {newsletter.game_plan && (
                    <div className="p-2 bg-green-500/10 border border-green-500/30 rounded">
                      <span className="text-[10px] text-green-400 uppercase block mb-1">Game Plan</span>
                      <p className="text-xs text-zinc-300">{newsletter.game_plan}</p>
                    </div>
                  )}
                </>
              ) : !isGeneratingIntelligence && (
                <div className="text-center py-6">
                  <Newspaper className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  {isConnected ? (
                    <>
                      <p className="text-sm text-zinc-400">Click Refresh to generate briefing</p>
                      <button
                        onClick={autoGenerateMarketIntelligence}
                        className="mt-3 px-4 py-2 bg-purple-500 text-white rounded text-sm font-medium hover:bg-purple-400"
                      >
                        Generate Market Intelligence
                      </button>
                    </>
                  ) : (
                    <>
                      <p className="text-sm text-zinc-400">Connect IB Gateway for auto-briefing</p>
                      <p className="text-xs text-zinc-500 mt-1">Market intelligence will generate automatically</p>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
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
                  onClick={handleConnectToIB}
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
                  const qualityGrade = opp.quality?.grade || opp.qualityGrade;
                  const qualityGradeColor = qualityGrade === 'A+' || qualityGrade === 'A' ? 'bg-green-500 text-black' :
                                            qualityGrade === 'B+' || qualityGrade === 'B' ? 'bg-cyan-500 text-black' :
                                            qualityGrade === 'C+' || qualityGrade === 'C' ? 'bg-yellow-500 text-black' :
                                            'bg-red-500 text-white';
                  
                  return (
                    <div
                      key={idx}
                      onClick={() => setSelectedTicker(opp)}
                      data-testid={`opportunity-card-${opp.symbol}`}
                      className={`p-3 rounded-lg border cursor-pointer transition-all hover:border-cyan-500/50 ${
                        isHighConviction 
                          ? 'border-cyan-500/30 bg-cyan-500/5 shadow-[0_0_10px_rgba(0,229,255,0.1)]' 
                          : 'border-white/10 bg-zinc-900/50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white">{opp.symbol}</span>
                          {qualityGrade && (
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${qualityGradeColor}`} title="Earnings Quality Grade">
                              {qualityGrade}
                            </span>
                          )}
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
                          data-testid={`buy-${opp.symbol}`}
                        >
                          Buy
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleTrade(opp, 'SELL'); }}
                          className="flex-1 py-1.5 text-xs font-bold bg-red-500/20 text-red-400 rounded hover:bg-red-500/30"
                          data-testid={`short-${opp.symbol}`}
                        >
                          Short
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); askAIAboutStock(opp.symbol); }}
                          className="px-2 py-1.5 text-xs font-bold bg-amber-500/20 text-amber-400 rounded hover:bg-amber-500/30 flex items-center gap-1"
                          data-testid={`ask-ai-${opp.symbol}`}
                          title="Ask AI about this stock"
                        >
                          <Bot className="w-3 h-3" />
                          AI
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Comprehensive Scanner Panel - Main Alert System */}
          <Card glow={comprehensiveSummary.total > 0}>
            <button 
              onClick={() => toggleSection('comprehensiveAlerts')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Target className="w-5 h-5 text-cyan-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Smart Scanner</h3>
                <span className="text-xs text-zinc-500">({comprehensiveSummary.total})</span>
                {comprehensiveSummary.total > 0 && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-cyan-500/20 text-cyan-400 rounded">
                    Score ≥{minScoreThreshold}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); runComprehensiveScan(); }}
                  disabled={isComprehensiveScanning}
                  className={`text-xs px-2 py-1 rounded ${isComprehensiveScanning ? 'bg-zinc-700 text-zinc-500' : 'bg-cyan-500 text-black hover:bg-cyan-400'} transition-colors`}
                >
                  {isComprehensiveScanning ? 'Scanning...' : 'Scan Now'}
                </button>
                <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.comprehensiveAlerts ? 'rotate-180' : ''}`} />
              </div>
            </button>
            
            {expandedSections.comprehensiveAlerts && (
              <div className="space-y-3">
                {/* Score Threshold Slider */}
                <div className="flex items-center gap-3 p-2 bg-zinc-900/50 rounded-lg">
                  <span className="text-xs text-zinc-400 whitespace-nowrap">Min Score:</span>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={minScoreThreshold}
                    onChange={(e) => setMinScoreThreshold(parseInt(e.target.value))}
                    className="flex-1 h-1.5 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
                  />
                  <span className="text-sm font-mono text-cyan-400 w-8">{minScoreThreshold}</span>
                </div>
                
                {/* Timeframe Tabs */}
                <div className="flex gap-1 p-1 bg-zinc-900/50 rounded-lg">
                  {[
                    { id: 'all', label: 'All', count: comprehensiveSummary.total },
                    { id: 'scalp', label: 'Scalp', count: comprehensiveSummary.scalp, max: 10 },
                    { id: 'intraday', label: 'Intraday', count: comprehensiveSummary.intraday, max: 25 },
                    { id: 'swing', label: 'Swing', count: comprehensiveSummary.swing, max: 25 },
                    { id: 'position', label: 'Position', count: comprehensiveSummary.position, max: 25 },
                  ].map(tab => (
                    <button
                      key={tab.id}
                      onClick={() => setSelectedTimeframeTab(tab.id)}
                      className={`flex-1 px-2 py-1.5 text-xs rounded transition-colors ${
                        selectedTimeframeTab === tab.id
                          ? 'bg-cyan-500 text-black font-bold'
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
                      }`}
                    >
                      {tab.label}
                      <span className={`ml-1 ${selectedTimeframeTab === tab.id ? 'text-black/70' : 'text-zinc-600'}`}>
                        {tab.count}{tab.max ? `/${tab.max}` : ''}
                      </span>
                    </button>
                  ))}
                </div>
                
                {!isConnected && (
                  <div className="text-center py-4 text-zinc-500 text-sm">
                    <AlertTriangle className="w-6 h-6 mx-auto mb-2 opacity-50" />
                    Connect IB Gateway to run comprehensive scan
                  </div>
                )}
                
                {isConnected && comprehensiveSummary.total === 0 && !isComprehensiveScanning && (
                  <div className="text-center py-6 text-zinc-500">
                    <Target className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No opportunities above score {minScoreThreshold}</p>
                    <p className="text-xs mt-1">Try lowering the threshold or wait for market conditions</p>
                  </div>
                )}
                
                {isComprehensiveScanning && (
                  <div className="text-center py-6 text-cyan-400">
                    <RefreshCw className="w-8 h-8 mx-auto mb-2 animate-spin" />
                    <p className="text-sm">Scanning all market sectors...</p>
                    <p className="text-xs mt-1 text-zinc-500">Analyzing against 77 trading rules</p>
                  </div>
                )}
                
                {/* Alert Cards */}
                {getFilteredComprehensiveAlerts().slice(0, 10).map((alert, idx) => (
                  <motion.div 
                    key={alert.id}
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.03 }}
                    onClick={() => setSelectedEnhancedAlert(alert)}
                    className={`p-3 rounded-lg cursor-pointer transition-all border ${
                      alert.grade === 'A' 
                        ? 'bg-green-500/10 border-green-500/40 shadow-[0_0_15px_rgba(34,197,94,0.15)]' 
                        : alert.grade === 'B'
                        ? 'bg-cyan-500/10 border-cyan-500/40'
                        : 'bg-zinc-900/50 border-white/10 hover:border-cyan-500/30'
                    }`}
                    data-testid={`comprehensive-alert-${alert.symbol}`}
                  >
                    {/* Alert Header */}
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-white">{alert.symbol}</span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                            alert.direction === 'LONG' 
                              ? 'bg-green-500 text-black' 
                              : 'bg-red-500 text-white'
                          }`}>
                            {alert.direction}
                          </span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                            alert.grade === 'A' ? 'bg-green-500 text-black' :
                            alert.grade === 'B' ? 'bg-cyan-500 text-black' :
                            alert.grade === 'C' ? 'bg-yellow-500 text-black' :
                            'bg-zinc-500 text-white'
                          }`}>
                            Grade {alert.grade}
                          </span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                            alert.timeframe === 'scalp' ? 'bg-red-500/20 text-red-400' :
                            alert.timeframe === 'intraday' ? 'bg-orange-500/20 text-orange-400' :
                            alert.timeframe === 'swing' ? 'bg-purple-500/20 text-purple-400' :
                            'bg-blue-500/20 text-blue-400'
                          }`}>
                            {alert.timeframe_description}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400 mt-1 line-clamp-1">{alert.headline}</p>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-lg font-bold text-cyan-400">{alert.overall_score}</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); dismissComprehensiveAlert(alert.id); }}
                          className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                          title="Dismiss"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                    
                    {/* Quick Stats */}
                    <div className="grid grid-cols-5 gap-1.5 text-[9px]">
                      <div className="bg-black/30 rounded p-1.5 text-center">
                        <span className="text-zinc-500 block">Entry</span>
                        <span className="text-cyan-400 font-mono">${alert.trade_plan?.entry?.toFixed(2)}</span>
                      </div>
                      <div className="bg-black/30 rounded p-1.5 text-center">
                        <span className="text-zinc-500 block">Stop</span>
                        <span className="text-red-400 font-mono">${alert.trade_plan?.stop_loss?.toFixed(2)}</span>
                      </div>
                      <div className="bg-black/30 rounded p-1.5 text-center">
                        <span className="text-zinc-500 block">Target</span>
                        <span className="text-green-400 font-mono">${alert.trade_plan?.target?.toFixed(2)}</span>
                      </div>
                      <div className="bg-black/30 rounded p-1.5 text-center">
                        <span className="text-zinc-500 block">R/R</span>
                        <span className="text-purple-400 font-mono">1:{alert.trade_plan?.risk_reward?.toFixed(1)}</span>
                      </div>
                      <div className="bg-black/30 rounded p-1.5 text-center">
                        <span className="text-zinc-500 block">Rules</span>
                        <span className={`font-mono ${
                          alert.matched_strategies_count >= 10 ? 'text-green-400' :
                          alert.matched_strategies_count >= 5 ? 'text-cyan-400' :
                          'text-yellow-400'
                        }`}>{alert.matched_strategies_count}/77</span>
                      </div>
                    </div>
                    
                    {/* Trigger reason */}
                    <div className="mt-2 text-[9px] text-zinc-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      <span>{alert.trigger_reason}</span>
                    </div>
                  </motion.div>
                ))}
                
                {getFilteredComprehensiveAlerts().length > 10 && (
                  <p className="text-center text-zinc-500 text-xs py-2">
                    +{getFilteredComprehensiveAlerts().length - 10} more alerts in this category
                  </p>
                )}
              </div>
            )}
          </Card>

          {/* Breakout Alerts - Top 10 meeting all rules */}
          <Card>
            <button 
              onClick={() => toggleSection('breakouts')}
              className="w-full flex items-center justify-between mb-3"
            >
              <div className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-yellow-400" />
                <h3 className="text-sm font-semibold uppercase tracking-wider">Breakout Alerts</h3>
                <span className="text-xs text-zinc-500">({breakoutAlerts.length})</span>
                {breakoutAlerts.length > 0 && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded animate-pulse">
                    LIVE
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); fetchBreakoutAlerts(); }}
                  className="text-xs text-cyan-400 hover:text-cyan-300"
                >
                  Refresh
                </button>
                <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${expandedSections.breakouts ? 'rotate-180' : ''}`} />
              </div>
            </button>
            
            {expandedSections.breakouts && (
              <div className="space-y-2">
                {!isConnected && (
                  <div className="text-center py-4 text-zinc-500 text-sm">
                    Connect IB Gateway for real-time breakout scanning
                  </div>
                )}
                
                {isConnected && breakoutAlerts.length === 0 && (
                  <div className="text-center py-4 text-zinc-500 text-sm">
                    No breakouts detected matching your criteria
                  </div>
                )}
                
                {breakoutAlerts.map((breakout, idx) => (
                  <div 
                    key={idx}
                    onClick={() => setSelectedTicker({ symbol: breakout.symbol, quote: { price: breakout.current_price, change_percent: breakout.change_percent } })}
                    className={`p-3 rounded cursor-pointer transition-all hover:bg-zinc-800 border ${
                      breakout.breakout_type === 'LONG' 
                        ? 'bg-green-500/5 border-green-500/30' 
                        : 'bg-red-500/5 border-red-500/30'
                    }`}
                    data-testid={`breakout-${breakout.symbol}`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{breakout.symbol}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                          breakout.breakout_type === 'LONG' 
                            ? 'bg-green-500 text-black' 
                            : 'bg-red-500 text-white'
                        }`}>
                          {breakout.breakout_type}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                          Score: {breakout.breakout_score}
                        </span>
                        {/* Signal Strength Indicator */}
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                          breakout.signal_strength_label === 'VERY STRONG' ? 'bg-green-500 text-black' :
                          breakout.signal_strength_label === 'STRONG' ? 'bg-cyan-500 text-black' :
                          breakout.signal_strength_label === 'MODERATE' ? 'bg-yellow-500 text-black' :
                          'bg-zinc-600 text-white'
                        }`}>
                          {breakout.rules_matched || breakout.strategy_count}/77
                        </span>
                      </div>
                      <span className={`text-sm font-mono ${breakout.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {formatPercent(breakout.change_percent)}
                      </span>
                    </div>
                    
                    {/* Signal Strength Bar */}
                    <div className="mb-2">
                      <div className="flex items-center justify-between text-[9px] mb-1">
                        <span className="text-zinc-500">Signal Strength</span>
                        <span className={`font-bold ${
                          breakout.signal_strength_label === 'VERY STRONG' ? 'text-green-400' :
                          breakout.signal_strength_label === 'STRONG' ? 'text-cyan-400' :
                          breakout.signal_strength_label === 'MODERATE' ? 'text-yellow-400' :
                          'text-zinc-400'
                        }`}>
                          {breakout.signal_strength_label || 'MODERATE'} ({breakout.signal_strength || Math.round((breakout.strategy_count / 77) * 100)}%)
                        </span>
                      </div>
                      <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                        <div 
                          className={`h-full rounded-full transition-all ${
                            breakout.signal_strength_label === 'VERY STRONG' ? 'bg-green-500' :
                            breakout.signal_strength_label === 'STRONG' ? 'bg-cyan-500' :
                            breakout.signal_strength_label === 'MODERATE' ? 'bg-yellow-500' :
                            'bg-zinc-500'
                          }`}
                          style={{ width: `${breakout.signal_strength || Math.round((breakout.strategy_count / 77) * 100)}%` }}
                        />
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-4 gap-2 text-[9px] mb-2">
                      <div>
                        <span className="text-zinc-500">Price: </span>
                        <span className="text-white font-mono">${breakout.current_price}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Broke: </span>
                        <span className={`font-mono ${breakout.breakout_type === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>
                          ${breakout.breakout_level}
                        </span>
                      </div>
                      <div>
                        <span className="text-zinc-500">RVOL: </span>
                        <span className="text-cyan-400 font-mono">{breakout.rvol}x</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">R/R: </span>
                        <span className="text-purple-400 font-mono">1:{breakout.risk_reward}</span>
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between text-[9px]">
                      <div className="flex items-center gap-2">
                        <span className="text-zinc-500">Entry: <span className="text-cyan-400">${breakout.current_price}</span></span>
                        <span className="text-zinc-500">Stop: <span className="text-red-400">${breakout.stop_loss}</span></span>
                        <span className="text-zinc-500">Target: <span className="text-green-400">${breakout.target}</span></span>
                      </div>
                    </div>
                    
                    {breakout.matched_strategies?.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-white/5">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="text-[9px] text-zinc-500">Top Strategies: </span>
                            {breakout.matched_strategies.slice(0, 3).map((s, i) => (
                              <span key={i} className="text-[9px] text-purple-400 mr-2">{s.name}</span>
                            ))}
                          </div>
                          <span className="text-[9px] text-zinc-600">{breakout.rules_matched || breakout.strategy_count} rules matched</span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
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
                        <HelpTooltip termId="short-interest"><span className="text-zinc-500">SI%: </span></HelpTooltip>
                        <span className="text-red-400 font-mono">{stock.short_interest_pct?.toFixed(1)}%</span>
                      </div>
                      <div>
                        <HelpTooltip termId="days-to-cover"><span className="text-zinc-500">DTC: </span></HelpTooltip>
                        <span className="text-yellow-400 font-mono">{stock.days_to_cover?.toFixed(1)}</span>
                      </div>
                      <div>
                        <HelpTooltip termId="rvol"><span className="text-zinc-500">RVOL: </span></HelpTooltip>
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

        {/* Recent System Alerts (moved here for visibility) */}
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

          {/* Enhanced Alert Detail Modal */}
          <AnimatePresence>
            {selectedEnhancedAlert && 
             selectedEnhancedAlert.symbol && 
             selectedEnhancedAlert.grade &&
             selectedEnhancedAlert.trade_plan && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                onClick={() => setSelectedEnhancedAlert(null)}
              >
                <motion.div
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  className="bg-[#0A0A0A] border border-cyan-500/30 w-full max-w-2xl max-h-[85vh] overflow-hidden rounded-xl"
                  onClick={e => e.stopPropagation()}
                >
                  {/* Modal Header */}
                  <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-cyan-900/20 to-transparent">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold text-white">{selectedEnhancedAlert.symbol}</span>
                      <span className={`text-sm px-2 py-0.5 rounded font-bold ${
                        selectedEnhancedAlert.grade === 'A' ? 'bg-green-500 text-black' :
                        selectedEnhancedAlert.grade === 'B' ? 'bg-cyan-500 text-black' :
                        selectedEnhancedAlert.grade === 'C' ? 'bg-yellow-500 text-black' :
                        'bg-red-500 text-white'
                      }`}>
                        Grade {selectedEnhancedAlert.grade}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        selectedEnhancedAlert.trade_plan?.direction === 'LONG' 
                          ? 'bg-green-500/20 text-green-400' 
                          : 'bg-red-500/20 text-red-400'
                      }`}>
                        {selectedEnhancedAlert.trade_plan?.direction}
                      </span>
                    </div>
                    <button onClick={() => setSelectedEnhancedAlert(null)} className="p-2 rounded-lg hover:bg-white/10 text-zinc-400">
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                  
                  {/* Modal Content */}
                  <div className="p-4 overflow-y-auto max-h-[65vh] space-y-4">
                    {/* Timestamp & Context */}
                    <div className="flex items-center gap-3 text-sm">
                      <div className="flex items-center gap-1.5 text-cyan-400">
                        <Clock className="w-4 h-4" />
                        {selectedEnhancedAlert.triggered_at_formatted}
                      </div>
                      <span className="text-zinc-600">•</span>
                      <span className="text-purple-400">{selectedEnhancedAlert.timeframe_description}</span>
                      <span className="text-zinc-600">•</span>
                      <span className="text-zinc-400">{selectedEnhancedAlert.alert_type}</span>
                    </div>
                    
                    {/* Headline */}
                    <div className="p-3 bg-cyan-500/10 border border-cyan-500/30 rounded-lg">
                      <p className="text-sm text-white font-medium">{selectedEnhancedAlert.headline}</p>
                    </div>
                    
                    {/* Trigger Reason */}
                    <div>
                      <h4 className="text-xs text-zinc-500 uppercase mb-2">Why This Alert Triggered</h4>
                      <p className="text-sm text-zinc-300">{selectedEnhancedAlert.trigger_reason}</p>
                    </div>
                    
                    {/* Trade Plan */}
                    <div className="grid grid-cols-5 gap-3">
                      {[
                        { label: 'Direction', value: selectedEnhancedAlert.trade_plan?.direction, color: selectedEnhancedAlert.trade_plan?.direction === 'LONG' ? 'green' : 'red' },
                        { label: 'Entry', value: `$${selectedEnhancedAlert.trade_plan?.entry?.toFixed(2)}`, color: 'cyan' },
                        { label: 'Stop Loss', value: `$${selectedEnhancedAlert.trade_plan?.stop_loss?.toFixed(2)}`, color: 'red' },
                        { label: 'Target', value: `$${selectedEnhancedAlert.trade_plan?.target?.toFixed(2)}`, color: 'green' },
                        { label: 'R/R Ratio', value: `1:${selectedEnhancedAlert.trade_plan?.risk_reward?.toFixed(1)}`, color: 'purple' },
                      ].map((item, idx) => (
                        <div key={idx} className="bg-zinc-900 rounded-lg p-3 text-center">
                          <span className="text-[10px] text-zinc-500 uppercase block">{item.label}</span>
                          <p className={`text-sm font-bold font-mono text-${item.color}-400`}>{item.value}</p>
                        </div>
                      ))}
                    </div>
                    
                    {/* Scores */}
                    <div>
                      <h4 className="text-xs text-zinc-500 uppercase mb-2">Scores</h4>
                      <div className="grid grid-cols-5 gap-2">
                        {[
                          { label: 'Overall', value: selectedEnhancedAlert.scores?.overall, termId: 'overall-score' },
                          { label: 'Technical', value: selectedEnhancedAlert.scores?.technical, termId: 'technical-score' },
                          { label: 'Fundamental', value: selectedEnhancedAlert.scores?.fundamental, termId: 'fundamental-score' },
                          { label: 'Catalyst', value: selectedEnhancedAlert.scores?.catalyst, termId: 'catalyst-score' },
                          { label: 'Confidence', value: selectedEnhancedAlert.scores?.confidence, termId: 'confidence-score' },
                        ].map((score, idx) => (
                          <div key={idx} className="bg-zinc-900/50 rounded p-2 text-center">
                            <span className="text-[9px] text-zinc-500 uppercase block">
                              <HelpTooltip termId={score.termId}>{score.label}</HelpTooltip>
                            </span>
                            <p className={`text-lg font-bold font-mono ${
                              score.value >= 70 ? 'text-green-400' :
                              score.value >= 50 ? 'text-cyan-400' :
                              score.value >= 30 ? 'text-yellow-400' :
                              'text-red-400'
                            }`}>{score.value || '--'}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                    
                    {/* Technical Features */}
                    <div>
                      <h4 className="text-xs text-zinc-500 uppercase mb-2">Technical Context</h4>
                      <div className="grid grid-cols-4 gap-2">
                        {[
                          { label: 'RVOL', value: `${selectedEnhancedAlert.features?.rvol?.toFixed(1)}x`, termId: 'rvol' },
                          { label: 'RSI', value: selectedEnhancedAlert.features?.rsi?.toFixed(0), termId: 'rsi' },
                          { label: 'VWAP Dist', value: `${selectedEnhancedAlert.features?.vwap_distance?.toFixed(1)}%`, termId: 'vwap-dist' },
                          { label: 'Trend', value: selectedEnhancedAlert.features?.trend, termId: 'trend' },
                        ].map((item, idx) => (
                          <div key={idx} className="bg-zinc-900/50 rounded p-2 text-center">
                            <span className="text-[9px] text-zinc-500 uppercase block">
                              <HelpTooltip termId={item.termId}>{item.label}</HelpTooltip>
                            </span>
                            <p className="text-sm font-mono text-white">{item.value || '--'}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                    
                    {/* Strategy Match */}
                    {selectedEnhancedAlert.primary_strategy && (
                      <div className="p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs text-purple-400 uppercase font-semibold">Primary Strategy Match</span>
                          <span className="text-xs text-zinc-400">
                            <HelpTooltip termId="signal-strength">{selectedEnhancedAlert.matched_strategies_count}/77 rules</HelpTooltip>
                          </span>
                        </div>
                        <p className="text-sm font-bold text-white">{selectedEnhancedAlert.primary_strategy.name}</p>
                        <p className="text-xs text-zinc-400 mt-1">{selectedEnhancedAlert.primary_strategy.description}</p>
                      </div>
                    )}
                    
                    {/* Full Summary */}
                    <div>
                      <h4 className="text-xs text-zinc-500 uppercase mb-2">Full Analysis</h4>
                      <div className="p-3 bg-zinc-900/50 rounded-lg">
                        <pre className="text-xs text-zinc-300 whitespace-pre-wrap font-sans leading-relaxed">
                          {selectedEnhancedAlert.summary}
                        </pre>
                      </div>
                    </div>
                  </div>
                  
                  {/* Modal Footer */}
                  <div className="flex gap-3 p-4 border-t border-white/10">
                    <button 
                      onClick={() => {
                        handleTrade({ symbol: selectedEnhancedAlert.symbol, quote: { price: selectedEnhancedAlert.trade_plan?.entry } }, 'BUY');
                        setSelectedEnhancedAlert(null);
                      }}
                      className="flex-1 py-2.5 text-sm font-bold bg-green-500 text-black rounded-lg hover:bg-green-400 transition-colors"
                    >
                      Buy {selectedEnhancedAlert.symbol}
                    </button>
                    <button 
                      onClick={() => {
                        handleTrade({ symbol: selectedEnhancedAlert.symbol, quote: { price: selectedEnhancedAlert.trade_plan?.entry } }, 'SELL');
                        setSelectedEnhancedAlert(null);
                      }}
                      className="flex-1 py-2.5 text-sm font-bold bg-red-500 text-white rounded-lg hover:bg-red-400 transition-colors"
                    >
                      Short {selectedEnhancedAlert.symbol}
                    </button>
                    <button 
                      onClick={() => setSelectedTicker({ symbol: selectedEnhancedAlert.symbol, quote: { price: selectedEnhancedAlert.features?.price } })}
                      className="px-4 py-2.5 text-sm font-bold bg-zinc-800 text-white rounded-lg hover:bg-zinc-700 transition-colors"
                    >
                      Full Details
                    </button>
                  </div>
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>

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
      
      {/* AI Assistant Modal */}
      <AIAssistant
        isOpen={showAssistant}
        onClose={() => {
          setShowAssistant(false);
          setAssistantPrompt(null);
        }}
        initialPrompt={assistantPrompt}
      />
    </div>
  );
};

export default CommandCenterPage;
