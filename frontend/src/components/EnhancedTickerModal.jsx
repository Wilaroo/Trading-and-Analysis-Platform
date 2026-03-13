/**
 * EnhancedTickerModal - New Chart-First Modal with Bot Integration
 * 
 * Features:
 * - Chart-first layout (65% chart, 35% sidebar)
 * - 3 smart tabs: Overview | Chart | Research
 * - Bot position integration with reasoning
 * - Consolidated analysis scores
 * - Collapsible company info
 * - Bot Vision toggle for chart annotations
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Loader2,
  AlertTriangle,
  Sparkles,
  Bot,
  Target,
  TrendingUp,
  TrendingDown,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  Plus,
  Bell,
  ExternalLink,
  Clock,
  Brain,
  BarChart3,
  LineChart,
  Pencil,
  Activity
} from 'lucide-react';
import * as LightweightCharts from 'lightweight-charts';
import api from '../utils/api';
import { HelpTooltip } from './HelpTooltip';
import { formatPrice, formatPercent, formatVolume } from '../utils/tradingUtils';
import QuickActionsMenu from './QuickActionsMenu';
import SmartStopSelector from './SmartStopSelector';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Score color helper
const getScoreColor = (score) => {
  if (score >= 70) return 'text-emerald-400';
  if (score >= 50) return 'text-cyan-400';
  if (score >= 30) return 'text-yellow-400';
  return 'text-red-400';
};

const getScoreBarColor = (score) => {
  if (score >= 70) return 'bg-emerald-400';
  if (score >= 50) return 'bg-cyan-400';
  if (score >= 30) return 'bg-yellow-400';
  return 'bg-red-400';
};

const getGradeBadgeColor = (grade) => {
  if (!grade) return 'bg-zinc-600 text-white';
  if (grade.startsWith('A')) return 'bg-emerald-500 text-black';
  if (grade.startsWith('B')) return 'bg-cyan-500 text-black';
  if (grade.startsWith('C')) return 'bg-yellow-500 text-black';
  return 'bg-red-500 text-white';
};

// Progress bar for position
const PositionProgressBar = ({ entry, stop, target, current }) => {
  if (!entry || !stop || !target) return null;
  
  const range = target - stop;
  const stopPct = 0;
  const entryPct = ((entry - stop) / range) * 100;
  const currentPct = ((current - stop) / range) * 100;
  const targetPct = 100;
  
  const stopLossPct = ((entry - stop) / entry * 100).toFixed(1);
  const targetGainPct = ((target - entry) / entry * 100).toFixed(1);
  
  return (
    <div>
      <div className="flex justify-between text-[10px] mb-1">
        <span className="text-red-400">-{stopLossPct}%</span>
        <span className="text-zinc-400">Entry</span>
        <span className="text-emerald-400">+{targetGainPct}%</span>
      </div>
      <div className="h-2.5 bg-black/50 rounded-full overflow-hidden relative">
        <div className="absolute left-0 h-full bg-gradient-to-r from-red-500/50 to-red-500/20" style={{ width: `${entryPct}%` }} />
        <div className="absolute h-full bg-gradient-to-r from-zinc-500/10 to-emerald-400/20" style={{ left: `${entryPct}%`, width: `${targetPct - entryPct}%` }} />
        <div 
          className="absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full bg-white border-2 border-cyan-400 shadow-lg transition-all duration-300" 
          style={{ left: `${Math.min(Math.max(currentPct, 2), 98)}%`, transform: 'translate(-50%, -50%)' }} 
        />
      </div>
    </div>
  );
};

// Score Ring Component
const ScoreRing = ({ score, size = 64 }) => {
  const circumference = 2 * Math.PI * (size / 2 - 4);
  const offset = circumference - (score / 100) * circumference;
  const grade = score >= 70 ? 'A' : score >= 60 ? 'B+' : score >= 50 ? 'B' : score >= 40 ? 'C' : 'D';
  
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="w-full h-full transform -rotate-90">
        <circle 
          cx={size/2} cy={size/2} r={size/2 - 4} 
          fill="none" 
          stroke="rgba(255,255,255,0.08)" 
          strokeWidth="5"
        />
        <circle 
          cx={size/2} cy={size/2} r={size/2 - 4} 
          fill="none" 
          stroke="#00D4FF" 
          strokeWidth="5"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-500"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-xl font-bold text-cyan-400">{score?.toFixed(0) || '--'}</span>
        <span className="text-[9px] text-zinc-400">{grade}</span>
      </div>
    </div>
  );
};

// Bot's Take Card - Enhanced with stop analysis
const BotTakeCard = ({ trade, symbol }) => {
  const [stopAnalysis, setStopAnalysis] = useState(null);
  
  useEffect(() => {
    if (!trade || !symbol) return;
    
    // Fetch stop analysis for this position
    const fetchStopAnalysis = async () => {
      try {
        const entryPrice = trade.fill_price || trade.entry_price;
        const currentPrice = trade.current_price || entryPrice;
        const stopPrice = trade.stop_price;
        const direction = trade.direction || 'long';
        const atr = entryPrice * 0.02; // Estimate
        
        if (!entryPrice || !stopPrice) return;
        
        const response = await fetch(
          `${API_URL}/api/smart-stops/analyze-trade?symbol=${symbol}&entry_price=${entryPrice}&current_price=${currentPrice}&stop_price=${stopPrice}&direction=${direction}&atr=${atr}`,
          { method: 'POST' }
        );
        
        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            setStopAnalysis(data);
          }
        }
      } catch (err) {
        console.debug('Stop analysis fetch error:', err);
      }
    };
    
    fetchStopAnalysis();
  }, [trade, symbol]);
  
  if (!trade) return null;
  
  const timestamp = trade.entry_time ? new Date(trade.entry_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : null;
  const hasStopWarnings = stopAnalysis?.recommendations?.some(r => r.severity === 'warning' || r.severity === 'critical');
  
  return (
    <div className={`border-l-[3px] ${hasStopWarnings ? 'border-amber-400' : 'border-cyan-400'} bg-gradient-to-r ${hasStopWarnings ? 'from-amber-400/10' : 'from-cyan-400/10'} to-transparent p-3 rounded-r-xl`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-2 h-2 rounded-full ${hasStopWarnings ? 'bg-amber-400' : 'bg-cyan-400'}`} />
        <span className={`text-xs font-bold ${hasStopWarnings ? 'text-amber-400' : 'text-cyan-400'}`}>BOT'S TAKE</span>
        {hasStopWarnings && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
            Stop needs attention
          </span>
        )}
        {timestamp && <span className="text-[10px] text-zinc-500 ml-auto">{timestamp}</span>}
      </div>
      <p className="text-xs text-zinc-300 leading-relaxed">
        {trade.reasoning || trade.explanation || 
          `"I ${trade.direction === 'long' ? 'went long' : 'shorted'} ${symbol} at $${trade.fill_price?.toFixed(2) || trade.entry_price?.toFixed(2)}. ${
            trade.setup_type ? `Setup: ${trade.setup_type}.` : ''
          } ${trade.stop_price ? `Stop at $${trade.stop_price.toFixed(2)}.` : ''} ${
            trade.target_prices?.[0] ? `Targeting $${trade.target_prices[0].toFixed(2)}.` : ''
          }"`
        }
      </p>
      
      {/* Stop Analysis Recommendations */}
      {stopAnalysis?.recommendations?.length > 0 && (
        <div className="mt-2 pt-2 border-t border-white/10">
          {stopAnalysis.recommendations.slice(0, 2).map((rec, i) => (
            <div key={i} className={`text-[10px] flex items-start gap-1 ${
              rec.severity === 'warning' || rec.severity === 'critical' ? 'text-amber-400' : 'text-zinc-400'
            }`}>
              {rec.severity === 'warning' || rec.severity === 'critical' ? '⚠️' : '💡'}
              <span>{rec.message}</span>
            </div>
          ))}
          {stopAnalysis.optimal_stop && (
            <div className="text-[10px] text-cyan-400 mt-1">
              Optimal stop: ${stopAnalysis.optimal_stop.price?.toFixed(2)} ({stopAnalysis.optimal_stop.confidence}% confidence)
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Hypothetical Bot's Take Card - "If I were to trade this..." for non-position tickers
const HypotheticalBotTakeCard = ({ analysis, symbol, onAskAI }) => {
  const [hypothetical, setHypothetical] = useState(null);
  
  useEffect(() => {
    if (!symbol || !analysis) return;
    
    // Generate hypothetical trade based on analysis
    const scores = analysis?.scores || {};
    const tradingSummary = analysis?.trading_summary || {};
    const matchedStrategies = analysis?.matched_strategies || [];
    const levels = analysis?.levels || {};
    
    const overallScore = scores.overall || 50;
    const bias = tradingSummary.bias || 'NEUTRAL';
    const strategy = matchedStrategies[0];
    
    // Determine if bot would trade this
    const wouldTrade = overallScore >= 60 && bias !== 'NEUTRAL';
    
    // Calculate hypothetical entry, stop, target
    const support = levels.support || levels.near_support || 0;
    const resistance = levels.resistance || levels.near_resistance || 0;
    const currentPrice = analysis?.current_price || 0;
    const atr = currentPrice * 0.02; // Estimate 2% ATR
    
    let hypotheticalTrade = null;
    
    if (wouldTrade && currentPrice > 0) {
      if (bias === 'BULLISH') {
        hypotheticalTrade = {
          direction: 'long',
          entry: currentPrice,
          stop: support > 0 ? support - (atr * 0.5) : currentPrice - (atr * 1.5),
          target: resistance > 0 ? resistance : currentPrice * 1.03,
          reasoning: `I'd look to enter long near $${currentPrice.toFixed(2)}. ${
            strategy?.name ? `Using ${strategy.name} setup.` : ''
          } Stop below support at $${(support > 0 ? support - (atr * 0.5) : currentPrice - (atr * 1.5)).toFixed(2)}. Target near resistance.`,
          confidence: overallScore
        };
      } else if (bias === 'BEARISH') {
        hypotheticalTrade = {
          direction: 'short',
          entry: currentPrice,
          stop: resistance > 0 ? resistance + (atr * 0.5) : currentPrice + (atr * 1.5),
          target: support > 0 ? support : currentPrice * 0.97,
          reasoning: `I'd look to short near $${currentPrice.toFixed(2)}. ${
            strategy?.name ? `Using ${strategy.name} setup.` : ''
          } Stop above resistance at $${(resistance > 0 ? resistance + (atr * 0.5) : currentPrice + (atr * 1.5)).toFixed(2)}. Target near support.`,
          confidence: overallScore
        };
      }
    } else if (!wouldTrade) {
      hypotheticalTrade = {
        direction: 'pass',
        reasoning: overallScore < 60 
          ? `I'd pass on ${symbol} right now - quality score is only ${overallScore}/100. I prefer setups with 60+ quality.`
          : `I'd wait for clearer direction on ${symbol}. Current bias is neutral - no edge.`,
        confidence: 100 - overallScore
      };
    }
    
    setHypothetical(hypotheticalTrade);
  }, [analysis, symbol]);
  
  if (!hypothetical) return null;
  
  const isPass = hypothetical.direction === 'pass';
  const isLong = hypothetical.direction === 'long';
  
  return (
    <div className={`border-l-[3px] ${
      isPass ? 'border-zinc-500' : isLong ? 'border-emerald-400' : 'border-red-400'
    } bg-gradient-to-r ${
      isPass ? 'from-zinc-500/10' : isLong ? 'from-emerald-400/10' : 'from-red-400/10'
    } to-transparent p-3 rounded-r-xl`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-2 h-2 rounded-full ${
          isPass ? 'bg-zinc-500' : isLong ? 'bg-emerald-400' : 'bg-red-400'
        }`} />
        <span className={`text-xs font-bold ${
          isPass ? 'text-zinc-400' : isLong ? 'text-emerald-400' : 'text-red-400'
        }`}>IF I WERE TO TRADE THIS...</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
          isPass ? 'bg-zinc-500/20 text-zinc-400' : 
          isLong ? 'bg-emerald-500/20 text-emerald-400' : 
          'bg-red-500/20 text-red-400'
        }`}>
          {isPass ? 'PASS' : isLong ? 'LONG' : 'SHORT'}
        </span>
        <span className="text-[10px] text-zinc-500 ml-auto">{hypothetical.confidence}% conf</span>
      </div>
      
      <p className="text-xs text-zinc-300 leading-relaxed mb-2">
        "{hypothetical.reasoning}"
      </p>
      
      {!isPass && (
        <div className="flex gap-3 text-[10px]">
          <span className="text-zinc-500">Entry: <span className="text-white font-mono">${hypothetical.entry?.toFixed(2)}</span></span>
          <span className="text-zinc-500">Stop: <span className="text-red-400 font-mono">${hypothetical.stop?.toFixed(2)}</span></span>
          <span className="text-zinc-500">Target: <span className="text-emerald-400 font-mono">${hypothetical.target?.toFixed(2)}</span></span>
        </div>
      )}
      
      {onAskAI && (
        <button 
          onClick={() => onAskAI(symbol, isPass ? 'quality' : 'analyze')}
          className="w-full mt-2 flex items-center justify-center gap-1.5 px-2.5 py-1.5 bg-purple-500/20 text-purple-400 rounded text-xs hover:bg-purple-500/30 border border-purple-500/30 transition-colors"
        >
          <Brain className="w-3 h-3" />
          {isPass ? 'Ask Why Not Trade This?' : 'Get Full Analysis'}
        </button>
      )}
    </div>
  );
};

// AI Recommendation Card
const AIRecommendationCard = ({ analysis, onAskAI, symbol }) => {
  const tradingSummary = analysis?.trading_summary || {};
  const scores = analysis?.scores || {};
  const matchedStrategies = analysis?.matched_strategies || [];
  
  const bias = tradingSummary.bias || 'NEUTRAL';
  const isLong = bias === 'BULLISH';
  const isShort = bias === 'BEARISH';
  
  return (
    <div className="glass-card rounded-xl p-3 border border-pink-500/30">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-4 h-4 text-pink-400" />
        <span className="text-xs font-bold text-pink-400">AI RECOMMENDATION</span>
        <span className={`px-2 py-0.5 rounded text-xs font-bold ml-auto ${
          isLong ? 'bg-emerald-500/20 text-emerald-400' : 
          isShort ? 'bg-red-500/20 text-red-400' : 
          'bg-zinc-500/20 text-zinc-400'
        }`}>
          {isLong ? 'BUY' : isShort ? 'SELL' : 'WAIT'}
        </span>
      </div>
      <p className="text-xs text-zinc-300 mb-2">
        {tradingSummary.summary || 
          (scores.overall >= 70 ? 'Strong setup with favorable risk/reward.' :
           scores.overall >= 50 ? 'Decent setup, manage risk carefully.' :
           'Mixed signals, consider waiting for clarity.')
        }
      </p>
      <div className="flex gap-3 text-[10px]">
        <span className="text-zinc-500">Strategy: <span className="text-cyan-400">{matchedStrategies[0]?.name || 'Analyzing...'}</span></span>
        <span className="text-zinc-500">Timeframe: <span className="text-white">{matchedStrategies[0]?.timeframe || 'Intraday'}</span></span>
      </div>
      {onAskAI && (
        <button 
          onClick={() => onAskAI(symbol)}
          className="w-full mt-2 flex items-center justify-center gap-1.5 px-2.5 py-1.5 bg-amber-500/20 text-amber-400 rounded text-xs hover:bg-amber-500/30 border border-amber-500/30 transition-colors"
        >
          <Bot className="w-3 h-3" />
          Ask AI for Deep Analysis
        </button>
      )}
    </div>
  );
};

const EnhancedTickerModal = ({ 
  ticker, 
  onClose, 
  onTrade, 
  onAskAI,
  botPosition = null,  // Pass bot's position if exists
  botTrade = null      // Pass bot's trade data if exists
}) => {
  const [analysis, setAnalysis] = useState(null);
  const [historicalData, setHistoricalData] = useState(null);
  const [qualityData, setQualityData] = useState(null);
  const [earningsData, setEarningsData] = useState(null);
  const [newsData, setNewsData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [showBotVision, setShowBotVision] = useState(true);
  const [chartError, setChartError] = useState(null);
  const [companyInfoExpanded, setCompanyInfoExpanded] = useState(false);
  const [tickerInput, setTickerInput] = useState(ticker?.symbol || '');
  const [selectedStopMode, setSelectedStopMode] = useState('atr_dynamic');
  const [selectedStopData, setSelectedStopData] = useState(null);
  const [selectedTimeframe, setSelectedTimeframe] = useState('5m');
  const [loadingNews, setLoadingNews] = useState(false);
  
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  
  // Quick ticker chips
  const quickTickers = ['NVDA', 'AMD', 'TSLA', 'META', 'AAPL', 'SPY', 'QQQ'];
  
  // Timeframe configuration
  const timeframes = [
    { id: '1m', label: '1m', duration: '1 D', barSize: '1 min' },
    { id: '5m', label: '5m', duration: '1 D', barSize: '5 mins' },
    { id: '15m', label: '15m', duration: '2 D', barSize: '15 mins' },
    { id: '1h', label: '1H', duration: '5 D', barSize: '1 hour' },
    { id: 'D', label: 'D', duration: '6 M', barSize: '1 day' },
  ];

  // Fetch all data
  // Fetch historical data for timeframe
  const fetchHistoricalData = useCallback(async (tf) => {
    if (!ticker?.symbol) return;
    
    const tfConfig = timeframes.find(t => t.id === tf) || timeframes[1];
    
    try {
      const response = await api.get(`/api/ib/historical/${ticker.symbol}?duration=${tfConfig.duration}&bar_size=${tfConfig.barSize}`);
      if (response.data?.bars) {
        setHistoricalData(response.data.bars);
        setChartError(null);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail?.message || err.response?.data?.detail || 'Unable to load chart data';
      if (err.response?.data?.ib_busy || errorMsg.includes('busy')) {
        setChartError('IB Gateway is busy. Chart data may be delayed.');
      } else {
        setChartError(errorMsg);
      }
    }
  }, [ticker?.symbol, timeframes]);
  
  // Fetch news data
  const fetchNewsData = useCallback(async () => {
    if (!ticker?.symbol) return;
    
    setLoadingNews(true);
    try {
      const response = await api.get(`/api/ib/news/${ticker.symbol}`);
      if (response.data?.news) {
        setNewsData(response.data.news);
      }
    } catch (err) {
      console.debug('News fetch error:', err);
    }
    setLoadingNews(false);
  }, [ticker?.symbol]);
  
  // Handle timeframe change
  const handleTimeframeChange = (tf) => {
    setSelectedTimeframe(tf);
    fetchHistoricalData(tf);
  };

  useEffect(() => {
    if (!ticker?.symbol) return;
    
    const fetchData = async () => {
      setLoading(true);
      setChartError(null);
      
      const fetchWithRetry = async (fetcher, retries = 2, delay = 1000) => {
        for (let i = 0; i <= retries; i++) {
          try {
            return await fetcher();
          } catch (err) {
            if (i === retries) throw err;
            await new Promise(r => setTimeout(r, delay));
          }
        }
      };
      
      const tfConfig = timeframes.find(t => t.id === selectedTimeframe) || timeframes[1];
      
      try {
        const [analysisRes, histRes, qualityRes, earningsRes, newsRes] = await Promise.all([
          fetchWithRetry(() => api.get(`/api/ib/analysis/${ticker.symbol}`)).catch(() => ({ data: null })),
          fetchWithRetry(() => api.get(`/api/ib/historical/${ticker.symbol}?duration=${tfConfig.duration}&bar_size=${tfConfig.barSize}`)).catch((err) => {
            const errorMsg = err.response?.data?.detail?.message || err.response?.data?.detail || 'Unable to load chart data';
            if (err.response?.data?.ib_busy || errorMsg.includes('busy')) {
              setChartError('IB Gateway is busy. Using cached data.');
            } else {
              setChartError(errorMsg);
            }
            return { data: { bars: [] } };
          }),
          fetchWithRetry(() => api.get(`/api/quality/score/${ticker.symbol}`)).catch(() => ({ data: null })),
          fetchWithRetry(() => api.get(`/api/earnings/${ticker.symbol}`)).catch(() => ({ data: null })),
          fetchWithRetry(() => api.get(`/api/ib/news/${ticker.symbol}`)).catch(() => ({ data: { news: [] } }))
        ]);
        
        setAnalysis(analysisRes.data);
        setHistoricalData(histRes.data?.bars || []);
        setQualityData(qualityRes.data);
        setEarningsData(earningsRes.data);
        setNewsData(newsRes.data?.news || []);
      } catch (err) {
        setChartError('Failed to load data. Please try again.');
      }
      setLoading(false);
    };
    
    fetchData();
  }, [ticker?.symbol]);

  // Create chart
  useEffect(() => {
    if (!chartContainerRef.current || loading) return;
    
    // Cleanup existing chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      priceLinesRef.current = [];
    }
    
    const timer = setTimeout(() => {
      if (!chartContainerRef.current) return;
      
      const container = chartContainerRef.current;
      const width = container.clientWidth || 600;
      const height = container.clientHeight || 350;
      
      try {
        const chart = LightweightCharts.createChart(container, {
          width,
          height,
          layout: { 
            background: { type: 'solid', color: '#050505' }, 
            textColor: '#9CA3AF' 
          },
          grid: { 
            vertLines: { color: 'rgba(255,255,255,0.03)' }, 
            horzLines: { color: 'rgba(255,255,255,0.03)' } 
          },
          timeScale: { 
            timeVisible: true, 
            secondsVisible: false, 
            borderColor: '#1F2937' 
          },
          rightPriceScale: { borderColor: '#1F2937' },
          crosshair: { 
            mode: 1, 
            vertLine: { color: '#00D4FF', width: 1, style: 2 }, 
            horzLine: { color: '#00D4FF', width: 1, style: 2 } 
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
        
        const handleResize = () => {
          if (chartRef.current && container) {
            chartRef.current.applyOptions({ 
              width: container.clientWidth, 
              height: container.clientHeight || 350 
            });
          }
        };
        window.addEventListener('resize', handleResize);
        
        return () => window.removeEventListener('resize', handleResize);
      } catch (err) {
        console.error('Chart init error:', err);
        setChartError('Failed to initialize chart');
      }
    }, 100);
    
    return () => {
      clearTimeout(timer);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
      }
    };
  }, [loading]);

  // Set chart data and price lines
  useEffect(() => {
    if (!candleSeriesRef.current || !historicalData || historicalData.length === 0) return;
    
    try {
      const chartData = historicalData.map(bar => ({
        time: Math.floor(new Date(bar.time || bar.date || bar.timestamp).getTime() / 1000),
        open: Number(bar.open), 
        high: Number(bar.high), 
        low: Number(bar.low), 
        close: Number(bar.close),
      })).sort((a, b) => a.time - b.time);
      
      candleSeriesRef.current.setData(chartData);
      if (chartRef.current) chartRef.current.timeScale().fitContent();
      
      // Clear existing price lines
      priceLinesRef.current.forEach(line => {
        try { candleSeriesRef.current.removePriceLine(line); } catch(e) {}
      });
      priceLinesRef.current = [];
      
      // Add Bot Vision price lines
      if (showBotVision) {
        const ts = analysis?.trading_summary || {};
        const trade = botTrade || botPosition;
        
        // Entry line
        const entry = trade?.fill_price || trade?.entry_price || ts.entry;
        if (entry) {
          const line = candleSeriesRef.current.createPriceLine({ 
            price: entry, 
            color: '#00D4FF', 
            lineWidth: 2, 
            lineStyle: 0, 
            axisLabelVisible: true, 
            title: 'Entry' 
          });
          priceLinesRef.current.push(line);
        }
        
        // Stop loss line
        const stop = trade?.stop_price || ts.stop_loss;
        if (stop) {
          const line = candleSeriesRef.current.createPriceLine({ 
            price: stop, 
            color: '#FF2E2E', 
            lineWidth: 2, 
            lineStyle: 2, 
            axisLabelVisible: true, 
            title: 'Stop' 
          });
          priceLinesRef.current.push(line);
        }
        
        // Target lines
        const targets = trade?.target_prices || [ts.target];
        targets.filter(Boolean).forEach((target, i) => {
          const line = candleSeriesRef.current.createPriceLine({ 
            price: target, 
            color: '#00FF94', 
            lineWidth: i === 0 ? 2 : 1, 
            lineStyle: 2, 
            axisLabelVisible: true, 
            title: `T${i + 1}` 
          });
          priceLinesRef.current.push(line);
        });
        
        // VWAP line
        const vwap = analysis?.technicals?.vwap;
        if (vwap) {
          const line = candleSeriesRef.current.createPriceLine({ 
            price: vwap, 
            color: '#A855F7', 
            lineWidth: 1, 
            lineStyle: 1, 
            axisLabelVisible: true, 
            title: 'VWAP' 
          });
          priceLinesRef.current.push(line);
        }
      }
    } catch (err) {
      console.error('Error setting chart data:', err);
    }
  }, [historicalData, analysis, showBotVision, botTrade, botPosition]);
  
  // Re-resize chart when tab changes
  useEffect(() => {
    if (chartRef.current && chartContainerRef.current && (activeTab === 'overview' || activeTab === 'chart')) {
      const container = chartContainerRef.current;
      const width = container.clientWidth || 600;
      const height = container.clientHeight || (activeTab === 'chart' ? 500 : 350);
      
      chartRef.current.resize(width, height);
      chartRef.current.timeScale().fitContent();
    }
  }, [activeTab]);

  // Handle ticker change
  const handleTickerChange = useCallback((newTicker) => {
    setTickerInput(newTicker);
    // This would trigger a parent component to change the ticker prop
    // For now, we'll show it updates the input
  }, []);

  if (!ticker) return null;

  const quote = analysis?.quote || ticker.quote || ticker;
  const tradingSummary = analysis?.trading_summary || {};
  const scores = analysis?.scores || {};
  const technicals = analysis?.technicals || {};
  const fundamentals = analysis?.fundamentals || {};
  const companyInfo = analysis?.company_info || {};
  const supportResistance = analysis?.support_resistance || {};
  const matchedStrategies = analysis?.matched_strategies || [];
  const quality = qualityData?.data || {};
  const news = analysis?.news || [];
  
  // Determine if bot has a position in this ticker
  const hasBotPosition = !!(botPosition || botTrade);
  const trade = botTrade || botPosition;
  
  // Calculate position P&L if exists
  const positionPnl = trade?.unrealized_pnl || trade?.pnl || 
    (trade?.current_price && trade?.fill_price ? 
      (trade.current_price - trade.fill_price) * (trade.shares || trade.quantity || 1) : 0);
  const positionPnlPct = trade?.pnl_percent || 
    (trade?.current_price && trade?.fill_price ? 
      ((trade.current_price - trade.fill_price) / trade.fill_price) * 100 : 0);

  // Key levels
  const keyLevels = [
    { label: 'VWAP', value: technicals.vwap, color: 'purple' },
    { label: 'HOD', value: supportResistance.resistance_1 || technicals.high, color: 'emerald' },
    { label: 'LOD', value: supportResistance.support_1 || technicals.low, color: 'red' },
    { label: 'Pre-High', value: analysis?.premarket_high, color: 'cyan' },
    { label: 'Resist', value: supportResistance.resistance_2, color: 'yellow' },
    { label: 'Support', value: supportResistance.support_2, color: 'zinc' },
  ].filter(l => l.value);

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'research', label: 'Research' },
  ];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/80 backdrop-blur-sm"
          onClick={onClose}
        />
        
        {/* Modal - Slide from right */}
        <motion.div
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          className="absolute right-0 top-0 h-full w-[75%] max-w-[1200px] bg-[#050505] border-l border-white/10 flex flex-col overflow-hidden"
          onClick={e => e.stopPropagation()}
        >
          {/* HEADER */}
          <div className="p-3 border-b border-white/10 flex justify-between items-center flex-shrink-0">
            <div className="flex items-center gap-3">
              {/* Close */}
              <button 
                onClick={onClose}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
              
              {/* Ticker + Badges */}
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold text-white">{ticker.symbol}</span>
                {scores.overall && (
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${getGradeBadgeColor(scores.grade)}`}>
                    {scores.overall?.toFixed(0)} {scores.grade || ''}
                  </span>
                )}
                {quality.grade && (
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${getGradeBadgeColor(quality.grade)}`}>
                    Q:{quality.grade}
                  </span>
                )}
                {tradingSummary.bias && (
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                    tradingSummary.bias === 'BULLISH' ? 'bg-emerald-500/20 text-emerald-400' :
                    tradingSummary.bias === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
                    'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {tradingSummary.bias === 'BULLISH' ? 'LONG' : tradingSummary.bias === 'BEARISH' ? 'SHORT' : 'NEUTRAL'}
                  </span>
                )}
              </div>
              
              {/* Ticker Search */}
              <div className="flex items-center gap-1 ml-3 pl-3 border-l border-white/10">
                <input 
                  type="text" 
                  value={tickerInput}
                  onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                  onKeyPress={(e) => e.key === 'Enter' && handleTickerChange(tickerInput)}
                  placeholder="Symbol..." 
                  className="w-20 bg-black/50 border border-zinc-700 rounded px-2 py-1.5 text-xs uppercase font-mono focus:border-cyan-400 focus:outline-none" 
                />
                {quickTickers.slice(0, 5).map(t => (
                  <button 
                    key={t}
                    onClick={() => handleTickerChange(t)}
                    className={`px-2 py-1.5 rounded text-xs hover:bg-white/20 transition-colors ${
                      t === 'SPY' || t === 'QQQ' ? 'bg-purple-500/20 text-purple-400' : 'bg-white/10 text-zinc-300'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Price */}
            <div className="flex items-center gap-4">
              <div className="text-right">
                <div className="font-mono text-xl text-white">${formatPrice(quote?.price)}</div>
                <div className={`text-xs ${quote?.change_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatPercent(quote?.change_percent)}
                </div>
              </div>
            </div>
          </div>
          
          {/* TABS */}
          <div className="px-4 border-b border-white/10 flex-shrink-0">
            <nav className="flex">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`py-2.5 px-5 text-sm font-medium rounded-t-lg transition-colors ${
                    activeTab === tab.id 
                      ? 'text-cyan-400 bg-cyan-400/10 border-b-2 border-cyan-400' 
                      : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>
          
          {/* MAIN CONTENT */}
          <div className="flex flex-1 overflow-hidden">
            {loading ? (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="w-10 h-10 animate-spin text-cyan-400" />
              </div>
            ) : activeTab === 'research' ? (
              /* RESEARCH TAB */
              <div className="flex-1 p-4 overflow-y-auto">
                <div className="max-w-4xl mx-auto space-y-4">
                  {/* News Section */}
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-medium text-white flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-cyan-400" />
                        Recent News
                      </h3>
                      <button 
                        onClick={fetchNewsData}
                        className="text-xs text-zinc-400 hover:text-cyan-400 flex items-center gap-1"
                      >
                        {loadingNews ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
                        Refresh
                      </button>
                    </div>
                    
                    {newsData.length > 0 ? (
                      <div className="space-y-3">
                        {newsData.slice(0, 10).map((item, idx) => (
                          <div key={idx} className="p-3 bg-black/30 rounded-lg hover:bg-black/50 transition-colors">
                            <div className="flex items-start gap-3">
                              <div className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${
                                item.sentiment === 'bullish' ? 'bg-emerald-400' :
                                item.sentiment === 'bearish' ? 'bg-red-400' : 'bg-zinc-500'
                              }`} />
                              <div className="flex-1 min-w-0">
                                <h4 className="text-sm text-white font-medium line-clamp-2">{item.headline}</h4>
                                {item.summary && (
                                  <p className="text-xs text-zinc-400 mt-1 line-clamp-2">{item.summary}</p>
                                )}
                                <div className="flex items-center gap-3 mt-2 text-[10px] text-zinc-500">
                                  <span className="flex items-center gap-1">
                                    <Clock className="w-3 h-3" />
                                    {item.timestamp ? new Date(item.timestamp).toLocaleString() : '--'}
                                  </span>
                                  <span>{item.source || 'News'}</span>
                                  {item.url && (
                                    <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-cyan-400 hover:underline flex items-center gap-1">
                                      <ExternalLink className="w-3 h-3" />
                                      Read More
                                    </a>
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-zinc-500">
                        <Sparkles className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">No recent news available</p>
                        <p className="text-xs mt-1">Try refreshing or check back later</p>
                      </div>
                    )}
                  </div>
                  
                  {/* Earnings Section */}
                  {earningsData && (
                    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
                      <h3 className="text-sm font-medium text-white flex items-center gap-2 mb-4">
                        <Target className="w-4 h-4 text-purple-400" />
                        Earnings Calendar
                      </h3>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="p-3 bg-black/30 rounded-lg">
                          <span className="text-xs text-zinc-500">Next Earnings</span>
                          <p className="text-sm font-medium text-white mt-1">
                            {earningsData.next_earnings_date || 'TBD'}
                          </p>
                        </div>
                        <div className="p-3 bg-black/30 rounded-lg">
                          <span className="text-xs text-zinc-500">Days Until</span>
                          <p className="text-sm font-medium text-white mt-1">
                            {earningsData.days_until_earnings !== undefined ? `${earningsData.days_until_earnings} days` : '--'}
                          </p>
                        </div>
                        {earningsData.last_eps_surprise && (
                          <>
                            <div className="p-3 bg-black/30 rounded-lg">
                              <span className="text-xs text-zinc-500">Last EPS Surprise</span>
                              <p className={`text-sm font-medium mt-1 ${earningsData.last_eps_surprise >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {earningsData.last_eps_surprise >= 0 ? '+' : ''}{(earningsData.last_eps_surprise * 100).toFixed(1)}%
                              </p>
                            </div>
                            <div className="p-3 bg-black/30 rounded-lg">
                              <span className="text-xs text-zinc-500">Earnings Score</span>
                              <p className="text-sm font-medium text-white mt-1">
                                {earningsData.earnings_score || '--'}/100
                              </p>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                  
                  {/* Quality Score Details */}
                  {qualityData && (
                    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
                      <h3 className="text-sm font-medium text-white flex items-center gap-2 mb-4">
                        <Brain className="w-4 h-4 text-amber-400" />
                        Quality Analysis
                      </h3>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Overall', value: qualityData.overall_score, color: 'cyan' },
                          { label: 'Momentum', value: qualityData.momentum_score, color: 'emerald' },
                          { label: 'Trend', value: qualityData.trend_score, color: 'purple' },
                          { label: 'Volume', value: qualityData.volume_score, color: 'yellow' },
                          { label: 'Volatility', value: qualityData.volatility_score, color: 'orange' },
                          { label: 'Structure', value: qualityData.structure_score, color: 'pink' },
                        ].map((item, idx) => (
                          <div key={idx} className="p-3 bg-black/30 rounded-lg text-center">
                            <span className="text-xs text-zinc-500 block mb-1">{item.label}</span>
                            <span className={`text-lg font-bold ${
                              item.value >= 70 ? 'text-emerald-400' :
                              item.value >= 50 ? 'text-yellow-400' : 'text-red-400'
                            }`}>
                              {item.value?.toFixed(0) || '--'}
                            </span>
                          </div>
                        ))}
                      </div>
                      {qualityData.grade && (
                        <div className="mt-4 p-3 bg-black/30 rounded-lg flex items-center justify-between">
                          <span className="text-sm text-zinc-400">Quality Grade</span>
                          <span className={`text-xl font-bold ${
                            qualityData.grade === 'A' ? 'text-emerald-400' :
                            qualityData.grade === 'B' ? 'text-cyan-400' :
                            qualityData.grade === 'C' ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {qualityData.grade}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                  
                  {/* Ask AI for Research */}
                  {onAskAI && (
                    <button 
                      onClick={() => onAskAI(ticker.symbol)}
                      className="w-full p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl hover:bg-amber-500/20 transition-colors flex items-center justify-center gap-2"
                    >
                      <Bot className="w-5 h-5 text-amber-400" />
                      <span className="text-amber-400 font-medium">Ask AI for Deep Research</span>
                    </button>
                  )}
                </div>
              </div>
            ) : activeTab === 'chart' ? (
              /* CHART TAB - Full width chart */
              <div className="flex-1 p-4 flex flex-col">
                {/* Chart Controls */}
                <div className="flex justify-between items-center mb-2 flex-shrink-0">
                  <div className="flex gap-1">
                    {timeframes.map((tf) => (
                      <button 
                        key={tf.id}
                        onClick={() => handleTimeframeChange(tf.id)}
                        className={`px-3 py-1.5 rounded text-sm transition-colors ${
                          selectedTimeframe === tf.id ? 'bg-cyan-400/30 text-cyan-400' : 'bg-white/10 hover:bg-white/20'
                        }`}
                      >
                        {tf.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={showBotVision}
                        onChange={(e) => setShowBotVision(e.target.checked)}
                        className="w-4 h-4 accent-cyan-400" 
                      />
                      <span className="text-sm text-cyan-400 flex items-center gap-1">
                        {showBotVision ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                        Bot Vision
                      </span>
                    </label>
                    <button className="text-sm text-zinc-400 hover:text-white flex items-center gap-1">
                      <BarChart3 className="w-4 h-4" /> Indicators
                    </button>
                    <button className="text-sm text-zinc-400 hover:text-white flex items-center gap-1">
                      <Pencil className="w-4 h-4" /> Draw
                    </button>
                  </div>
                </div>
                
                {/* Full Width Chart */}
                <div className="relative flex-1 bg-black/50 rounded-lg overflow-hidden min-h-[500px]">
                  {chartError ? (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className="text-center">
                        <AlertTriangle className="w-8 h-8 text-yellow-500 mx-auto mb-2" />
                        <p className="text-sm text-zinc-400">{chartError}</p>
                      </div>
                    </div>
                  ) : (
                    <div ref={chartContainerRef} className="w-full h-full" style={{ minHeight: '500px' }} />
                  )}
                  
                  {/* Position Badge Overlay */}
                  {hasBotPosition && (
                    <div className="absolute top-3 left-3 px-3 py-2 rounded-lg bg-emerald-400/15 border border-emerald-400/50 backdrop-blur-sm">
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                          <span className="text-xs font-bold text-emerald-400">POSITION OPEN</span>
                        </div>
                        <div className="h-4 w-px bg-emerald-400/30" />
                        <span className="font-mono text-sm text-white">
                          {trade?.shares || trade?.quantity || 0} shares
                        </span>
                        <span className={`font-mono text-sm ${positionPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {positionPnl >= 0 ? '+' : ''}${positionPnl?.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
                
                {/* Key Levels Bar */}
                {keyLevels.length > 0 && (
                  <div className="flex gap-2 mt-3 flex-shrink-0">
                    {keyLevels.map((level, i) => (
                      <div 
                        key={i}
                        className="flex-1 p-3 rounded-lg text-center"
                        style={{ 
                          backgroundColor: `rgba(${
                            level.color === 'purple' ? '168,85,247' :
                            level.color === 'emerald' ? '16,185,129' :
                            level.color === 'red' ? '239,68,68' :
                            level.color === 'cyan' ? '34,211,238' :
                            level.color === 'yellow' ? '250,204,21' :
                            '161,161,170'
                          }, 0.1)`,
                          borderColor: `rgba(${
                            level.color === 'purple' ? '168,85,247' :
                            level.color === 'emerald' ? '16,185,129' :
                            level.color === 'red' ? '239,68,68' :
                            level.color === 'cyan' ? '34,211,238' :
                            level.color === 'yellow' ? '250,204,21' :
                            '161,161,170'
                          }, 0.2)`,
                          border: '1px solid'
                        }}
                      >
                        <span className="text-xs text-zinc-400">{level.label}</span>
                        <span className="font-mono text-base ml-2" style={{
                          color: level.color === 'purple' ? '#A855F7' :
                                 level.color === 'emerald' ? '#10B981' :
                                 level.color === 'red' ? '#EF4444' :
                                 level.color === 'cyan' ? '#22D3EE' :
                                 level.color === 'yellow' ? '#FACC15' :
                                 '#A1A1AA'
                        }}>
                          ${level.value?.toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              /* OVERVIEW TAB - Chart + Sidebar */
              <>
                {/* LEFT: CHART AREA (65%) */}
                <div className="flex-1 p-4 flex flex-col border-r border-white/10 overflow-hidden">
                  {/* Chart Controls */}
                  <div className="flex justify-between items-center mb-2 flex-shrink-0">
                    <div className="flex gap-1">
                      {timeframes.map((tf) => (
                        <button 
                          key={tf.id}
                          onClick={() => handleTimeframeChange(tf.id)}
                          className={`px-2.5 py-1 rounded text-xs transition-colors ${
                            selectedTimeframe === tf.id ? 'bg-cyan-400/30 text-cyan-400' : 'bg-white/10 hover:bg-white/20'
                          }`}
                        >
                          {tf.label}
                        </button>
                      ))}
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input 
                          type="checkbox" 
                          checked={showBotVision}
                          onChange={(e) => setShowBotVision(e.target.checked)}
                          className="w-3.5 h-3.5 accent-cyan-400" 
                        />
                        <span className="text-xs text-cyan-400 flex items-center gap-1">
                          {showBotVision ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                          Bot Vision
                        </span>
                      </label>
                      <button className="text-xs text-zinc-400 hover:text-white flex items-center gap-1">
                        <BarChart3 className="w-3 h-3" /> Indicators
                      </button>
                      <button className="text-xs text-zinc-400 hover:text-white flex items-center gap-1">
                        <Pencil className="w-3 h-3" /> Draw
                      </button>
                    </div>
                  </div>
                  
                  {/* Chart */}
                  <div className="relative flex-1 bg-black/50 rounded-lg overflow-hidden min-h-[300px]">
                    {chartError ? (
                      <div className="absolute inset-0 flex items-center justify-center">
                        <div className="text-center">
                          <AlertTriangle className="w-8 h-8 text-yellow-500 mx-auto mb-2" />
                          <p className="text-sm text-zinc-400">{chartError}</p>
                        </div>
                      </div>
                    ) : (
                      <div ref={chartContainerRef} className="w-full h-full" style={{ minHeight: '350px' }} />
                    )}
                    
                    {/* Position Badge Overlay */}
                    {hasBotPosition && (
                      <div className="absolute top-3 left-3 px-3 py-2 rounded-lg bg-emerald-400/15 border border-emerald-400/50 backdrop-blur-sm">
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                            <span className="text-xs font-bold text-emerald-400">POSITION OPEN</span>
                          </div>
                          <div className="h-4 w-px bg-emerald-400/30" />
                          <span className="font-mono text-sm text-white">
                            {trade?.shares || trade?.quantity || 0} shares
                          </span>
                          <span className={`font-mono text-sm ${positionPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {positionPnl >= 0 ? '+' : ''}${positionPnl?.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                  
                  {/* Key Levels Bar */}
                  {keyLevels.length > 0 && (
                    <div className="flex gap-2 mt-3 flex-shrink-0">
                      {keyLevels.map((level, i) => (
                        <div 
                          key={i}
                          className={`flex-1 p-2 rounded-lg bg-${level.color}-500/10 border border-${level.color}-500/20 text-center`}
                          style={{ 
                            backgroundColor: `rgba(${
                              level.color === 'purple' ? '168,85,247' :
                              level.color === 'emerald' ? '16,185,129' :
                              level.color === 'red' ? '239,68,68' :
                              level.color === 'cyan' ? '34,211,238' :
                              level.color === 'yellow' ? '250,204,21' :
                              '161,161,170'
                            }, 0.1)`,
                            borderColor: `rgba(${
                              level.color === 'purple' ? '168,85,247' :
                              level.color === 'emerald' ? '16,185,129' :
                              level.color === 'red' ? '239,68,68' :
                              level.color === 'cyan' ? '34,211,238' :
                              level.color === 'yellow' ? '250,204,21' :
                              '161,161,170'
                            }, 0.2)`
                          }}
                        >
                          <span className="text-[10px] text-zinc-400">{level.label}</span>
                          <span className="font-mono text-xs ml-1.5" style={{
                            color: level.color === 'purple' ? '#A855F7' :
                                   level.color === 'emerald' ? '#10B981' :
                                   level.color === 'red' ? '#EF4444' :
                                   level.color === 'cyan' ? '#22D3EE' :
                                   level.color === 'yellow' ? '#FACC15' :
                                   '#A1A1AA'
                          }}>
                            ${level.value?.toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                
                {/* RIGHT: SIDEBAR (35%) */}
                <div className="w-[340px] p-4 space-y-3 overflow-y-auto flex-shrink-0">
                  
                  {/* Trade Setup Card */}
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-zinc-400">TRADE SETUP</span>
                      {tradingSummary.risk_reward > 0 && (
                        <span className="font-mono text-xs text-cyan-400">R:R {tradingSummary.risk_reward}:1</span>
                      )}
                    </div>
                    
                    <div className="grid grid-cols-3 gap-2 mb-3">
                      <div className="text-center p-2.5 rounded-lg bg-black/40">
                        <div className="text-[10px] text-zinc-500 mb-0.5">ENTRY</div>
                        <div className="font-mono font-bold text-white">
                          ${(trade?.fill_price || trade?.entry_price || tradingSummary.entry)?.toFixed(2) || '--'}
                        </div>
                      </div>
                      <div className="text-center p-2.5 rounded-lg bg-black/40 border border-red-500/40">
                        <div className="text-[10px] text-red-400 mb-0.5">STOP</div>
                        <div className="font-mono font-bold text-red-400">
                          ${(trade?.stop_price || tradingSummary.stop_loss)?.toFixed(2) || '--'}
                        </div>
                      </div>
                      <div className="text-center p-2.5 rounded-lg bg-black/40 border border-emerald-500/40">
                        <div className="text-[10px] text-emerald-400 mb-0.5">TARGET</div>
                        <div className="font-mono font-bold text-emerald-400">
                          ${(trade?.target_prices?.[0] || tradingSummary.target)?.toFixed(2) || '--'}
                        </div>
                      </div>
                    </div>
                    
                    {/* Progress Bar */}
                    <PositionProgressBar 
                      entry={trade?.fill_price || trade?.entry_price || tradingSummary.entry}
                      stop={selectedStopData?.stop_price || trade?.stop_price || tradingSummary.stop_loss}
                      target={trade?.target_prices?.[0] || tradingSummary.target}
                      current={quote?.price}
                    />
                  </div>
                  
                  {/* Smart Stop Selector */}
                  <SmartStopSelector
                    symbol={ticker?.symbol}
                    entryPrice={trade?.fill_price || trade?.entry_price || tradingSummary.entry || quote?.price}
                    direction={hasBotPosition && trade?.quantity < 0 ? 'short' : 'long'}
                    atr={analysis?.atr || (quote?.price * 0.02)}
                    support={tradingSummary.stop_loss}
                    swingLow={analysis?.support_levels?.[0]}
                    swingHigh={analysis?.resistance_levels?.[0]}
                    floatShares={fundamentals?.float_shares}
                    avgVolume={fundamentals?.avg_volume}
                    selectedMode={selectedStopMode}
                    onModeSelect={(mode, data) => {
                      setSelectedStopMode(mode);
                      setSelectedStopData(data);
                    }}
                  />
                  
                  {/* Analysis Scores */}
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-zinc-400">ANALYSIS</span>
                      {onAskAI && (
                        <button 
                          onClick={() => onAskAI(ticker.symbol)}
                          className="text-[10px] text-amber-400 hover:underline flex items-center gap-1"
                        >
                          <Brain className="w-3 h-3" />
                          Deep Analysis
                        </button>
                      )}
                    </div>
                    
                    <div className="flex items-center gap-4">
                      <ScoreRing score={scores.overall} size={64} />
                      
                      <div className="flex-1 space-y-2">
                        {[
                          { label: 'Technical', value: scores.technical_score, color: 'emerald' },
                          { label: 'Fundament.', value: scores.fundamental_score, color: 'yellow' },
                          { label: 'Catalyst', value: scores.catalyst_score, color: 'purple' },
                          { label: 'Confidence', value: scores.confidence, color: 'cyan' },
                        ].map((score, i) => (
                          <div key={i} className="flex items-center gap-2">
                            <span className="text-[10px] text-zinc-500 w-14">{score.label}</span>
                            <div className="flex-1 h-1.5 bg-black/40 rounded-full overflow-hidden">
                              <div 
                                className={`h-full rounded-full transition-all duration-500 ${getScoreBarColor(score.value)}`}
                                style={{ width: `${score.value || 0}%` }}
                              />
                            </div>
                            <span className={`font-mono text-[10px] w-5 ${getScoreColor(score.value)}`}>
                              {score.value?.toFixed(0) || '--'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                  
                  {/* Bot's Take - for positions */}
                  {hasBotPosition && (
                    <BotTakeCard trade={trade} symbol={ticker.symbol} />
                  )}
                  
                  {/* Hypothetical Bot's Take - for non-positions */}
                  {!hasBotPosition && analysis && (
                    <HypotheticalBotTakeCard 
                      analysis={analysis} 
                      symbol={ticker.symbol}
                      onAskAI={onAskAI}
                    />
                  )}
                  
                  {/* AI Recommendation */}
                  <AIRecommendationCard 
                    analysis={analysis} 
                    onAskAI={onAskAI}
                    symbol={ticker.symbol}
                  />
                  
                  {/* Company Info (Collapsible) */}
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden">
                    <button
                      onClick={() => setCompanyInfoExpanded(!companyInfoExpanded)}
                      className="w-full p-3 flex items-center justify-between text-xs text-zinc-400 hover:text-white transition-colors"
                    >
                      <span>Company Info</span>
                      {companyInfoExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                    
                    <AnimatePresence>
                      {companyInfoExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="px-3 pb-3 text-xs space-y-1.5 border-t border-white/5"
                        >
                          <div className="flex justify-between pt-2">
                            <span className="text-zinc-500">Company</span>
                            <span className="text-right max-w-[180px] truncate">{companyInfo.name || ticker.symbol}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-500">Sector</span>
                            <span>{companyInfo.sector || '--'}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-500">Industry</span>
                            <span className="text-right max-w-[180px] truncate">{companyInfo.industry || '--'}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-500">Market Cap</span>
                            <span className="font-mono">
                              {companyInfo.market_cap ? `$${(companyInfo.market_cap / 1e9).toFixed(1)}B` : '--'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-500">Avg Volume</span>
                            <span className="font-mono">{formatVolume(fundamentals.avg_volume)}</span>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>
              </>
            )}
          </div>
          
          {/* FOOTER */}
          <div className="p-3 border-t border-white/10 flex gap-2 flex-shrink-0">
            <QuickActionsMenu 
              symbol={ticker.symbol} 
              hasPosition={hasBotPosition}
              currentPrice={quote?.price}
              variant="buttons"
              className="mr-2"
            />
            <button 
              onClick={() => onTrade?.(ticker, 'BUY')}
              className="flex-1 py-2.5 rounded-lg bg-emerald-500 text-black font-bold text-sm hover:bg-emerald-400 transition-colors"
            >
              Buy {ticker.symbol}
            </button>
            <button 
              onClick={() => onTrade?.(ticker, 'SELL')}
              className="flex-1 py-2.5 rounded-lg bg-red-500 text-white font-bold text-sm hover:bg-red-400 transition-colors"
            >
              Short {ticker.symbol}
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default EnhancedTickerModal;
