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
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
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
import { useTickerModal } from '../hooks/useTickerModal';
import { HelpTooltip } from './HelpTooltip';
import { formatPrice, formatPercent, formatVolume } from '../utils/tradingUtils';
import QuickActionsMenu from './QuickActionsMenu';
import SmartStopSelector from './SmartStopSelector';
import { useWsData } from '../contexts/WebSocketDataContext';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// ── Static constants (outside component to avoid re-creation) ──
const QUICK_TICKERS = ['NVDA', 'AMD', 'TSLA', 'META', 'AAPL', 'SPY', 'QQQ'];
const TIMEFRAMES = [
  { id: '1m', label: '1m', duration: '1 D', barSize: '1 min' },
  { id: '5m', label: '5m', duration: '1 D', barSize: '5 mins' },
  { id: '15m', label: '15m', duration: '2 D', barSize: '15 mins' },
  { id: '1h', label: '1H', duration: '5 D', barSize: '1 hour' },
  { id: 'D', label: 'D', duration: '6 M', barSize: '1 day' },
];
const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'chart', label: 'Chart' },
  { id: 'research', label: 'Research' },
];

// ── Per-symbol data cache (survives modal close/reopen) ──
const _symbolCache = {};
const getCachedSymbolData = (symbol) => {
  const entry = _symbolCache[symbol];
  if (!entry) return null;
  const age = Date.now() - entry.timestamp;
  // Cache valid for 3 minutes
  if (age > 180000) return null;
  return entry;
};
const setCachedSymbolData = (symbol, data) => {
  _symbolCache[symbol] = { ...data, timestamp: Date.now() };
};

// Score color helper
const getScoreColor = (score) => {
  if (score >= 70) return 'text-emerald-400';
  if (score >= 50) return 'text-cyan-400';
  if (score >= 30) return 'text-yellow-400';
  return 'text-red-400';
};

const getScoreBarColor = (score) => {
  if (score >= 70) return 'bg-gradient-to-r from-emerald-500 to-emerald-400';
  if (score >= 50) return 'bg-gradient-to-r from-cyan-500 to-cyan-400';
  if (score >= 30) return 'bg-gradient-to-r from-yellow-500 to-yellow-400';
  return 'bg-gradient-to-r from-red-500 to-red-400';
};

const getGradeBadgeColor = (grade) => {
  if (!grade) return 'bg-zinc-600 text-white';
  if (grade.startsWith('A')) return 'bg-gradient-to-r from-emerald-500 to-emerald-400 text-black shadow-lg shadow-emerald-500/30';
  if (grade.startsWith('B')) return 'bg-gradient-to-r from-cyan-500 to-cyan-400 text-black shadow-lg shadow-cyan-500/30';
  if (grade.startsWith('C')) return 'bg-gradient-to-r from-yellow-500 to-yellow-400 text-black';
  return 'bg-gradient-to-r from-red-500 to-red-400 text-white';
};

// Glass Card Component for V2 styling
const GlassCard = React.memo(({ children, className = '', gradient = false, glow = false }) => (
  <div className={`
    relative overflow-hidden rounded-xl
    bg-gradient-to-br from-white/[0.08] to-white/[0.02]
    border border-white/10
    backdrop-blur-xl
    ${glow ? 'shadow-lg shadow-cyan-500/10' : ''}
    ${className}
  `}>
    {gradient && (
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-violet-500/5 pointer-events-none" />
    )}
    <div className="relative">{children}</div>
  </div>
));

// Progress bar for position
const PositionProgressBar = React.memo(({ entry, stop, target, current }) => {
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
});

// Score Ring Component
const ScoreRing = React.memo(({ score, size = 64 }) => {
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
});

// Our Take Card - Enhanced with stop analysis (formerly Bot's Take)
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
          if (data?.success) {
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
  
  // Calculate R:R
  const entryPrice = trade.fill_price || trade.entry_price;
  const stopPrice = trade.stop_price;
  const targetPrice = trade.target_prices?.[0];
  const riskPerShare = entryPrice && stopPrice ? Math.abs(entryPrice - stopPrice) : 0;
  const rewardPerShare = entryPrice && targetPrice ? Math.abs(targetPrice - entryPrice) : 0;
  const rrRatio = riskPerShare > 0 ? (rewardPerShare / riskPerShare).toFixed(1) : null;
  
  return (
    <GlassCard gradient glow={!hasStopWarnings} className="overflow-hidden">
      <div className={`border-l-[3px] ${hasStopWarnings ? 'border-amber-400' : 'border-violet-400'} p-4`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-lg ${hasStopWarnings ? 'bg-amber-500/20' : 'bg-gradient-to-br from-violet-500/30 to-purple-600/30'} flex items-center justify-center`}>
              <Brain className={`w-4 h-4 ${hasStopWarnings ? 'text-amber-400' : 'text-violet-400'}`} />
            </div>
            <div>
              <span className={`text-sm font-bold ${hasStopWarnings ? 'text-amber-400' : 'text-violet-400'}`}>OUR TAKE</span>
              {hasStopWarnings && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 ml-2">
                  Stop needs attention
                </span>
              )}
            </div>
          </div>
          {timestamp && <span className="text-[10px] text-zinc-500">{timestamp}</span>}
        </div>
        
        <p className="text-sm text-zinc-200 leading-relaxed mb-3">
          {trade.reasoning || trade.explanation || 
            `"We ${trade.direction === 'long' ? 'went long' : 'shorted'} ${symbol} at $${entryPrice?.toFixed(2)}. ${
              trade.setup_type ? `Using our ${trade.setup_type} setup.` : ''
            } ${stopPrice ? `Our stop is at $${stopPrice.toFixed(2)}.` : ''} ${
              targetPrice ? `We're targeting $${targetPrice.toFixed(2)}.` : ''
            }"`
          }
        </p>
        
        {/* Trade Parameters Grid */}
        {entryPrice && (
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="p-2 rounded-lg bg-black/40 text-center">
              <p className="text-[9px] text-zinc-500 uppercase">Entry</p>
              <p className="text-sm font-bold text-white">${entryPrice.toFixed(2)}</p>
            </div>
            <div className="p-2 rounded-lg bg-black/40 text-center">
              <p className="text-[9px] text-zinc-500 uppercase">Stop</p>
              <p className="text-sm font-bold text-rose-400">${stopPrice?.toFixed(2) || '--'}</p>
            </div>
            <div className="p-2 rounded-lg bg-black/40 text-center">
              <p className="text-[9px] text-zinc-500 uppercase">Target</p>
              <p className="text-sm font-bold text-emerald-400">${targetPrice?.toFixed(2) || '--'}</p>
            </div>
            <div className="p-2 rounded-lg bg-black/40 text-center">
              <p className="text-[9px] text-zinc-500 uppercase">R:R</p>
              <p className="text-sm font-bold text-cyan-400">{rrRatio ? `${rrRatio}:1` : '--'}</p>
            </div>
          </div>
        )}
        
        {/* Stop Analysis Recommendations */}
        {stopAnalysis?.recommendations?.length > 0 && (
          <div className="pt-3 border-t border-white/10">
            {stopAnalysis.recommendations.slice(0, 2).map((rec, i) => (
              <div key={i} className={`text-xs flex items-start gap-2 mb-1 ${
                rec.severity === 'warning' || rec.severity === 'critical' ? 'text-amber-400' : 'text-zinc-400'
              }`}>
                <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                <span>{rec.message}</span>
              </div>
            ))}
            {stopAnalysis.optimal_stop && (
              <div className="flex items-center gap-2 mt-2 p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                <Target className="w-3 h-3 text-cyan-400" />
                <span className="text-xs text-cyan-400">
                  Optimal stop: ${stopAnalysis.optimal_stop.price?.toFixed(2)} ({stopAnalysis.optimal_stop.confidence}% confidence)
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </GlassCard>
  );
};

// Hypothetical Our Take Card - "If we were to trade this..." for non-position tickers
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
    
    // Determine if we would trade this
    const wouldTrade = overallScore >= 60 && bias !== 'NEUTRAL';
    
    // Calculate hypothetical entry, stop, target
    const support = levels.support || levels.near_support || 0;
    const resistance = levels.resistance || levels.near_resistance || 0;
    const currentPrice = analysis?.current_price || 0;
    const atr = currentPrice * 0.02; // Estimate 2% ATR
    
    let hypotheticalTrade = null;
    
    if (wouldTrade && currentPrice > 0) {
      const entryPrice = currentPrice;
      const stopPrice = bias === 'BULLISH' 
        ? (support > 0 ? support - (atr * 0.5) : currentPrice - (atr * 1.5))
        : (resistance > 0 ? resistance + (atr * 0.5) : currentPrice + (atr * 1.5));
      const targetPrice = bias === 'BULLISH'
        ? (resistance > 0 ? resistance : currentPrice * 1.03)
        : (support > 0 ? support : currentPrice * 0.97);
      
      const risk = Math.abs(entryPrice - stopPrice);
      const reward = Math.abs(targetPrice - entryPrice);
      const rrRatio = risk > 0 ? (reward / risk).toFixed(1) : 0;
      
      if (bias === 'BULLISH') {
        hypotheticalTrade = {
          direction: 'long',
          entry: entryPrice,
          stop: stopPrice,
          target: targetPrice,
          rrRatio,
          reasoning: `We'd look to enter long near $${currentPrice.toFixed(2)}. ${
            strategy?.name ? `This matches our ${strategy.name} setup.` : ''
          } Stop below support, targeting resistance.`,
          confidence: overallScore
        };
      } else if (bias === 'BEARISH') {
        hypotheticalTrade = {
          direction: 'short',
          entry: entryPrice,
          stop: stopPrice,
          target: targetPrice,
          rrRatio,
          reasoning: `We'd look to short near $${currentPrice.toFixed(2)}. ${
            strategy?.name ? `This matches our ${strategy.name} setup.` : ''
          } Stop above resistance, targeting support.`,
          confidence: overallScore
        };
      }
    } else if (!wouldTrade) {
      hypotheticalTrade = {
        direction: 'pass',
        reasoning: overallScore < 60 
          ? `We'd pass on ${symbol} right now - quality score is only ${overallScore}/100. We prefer setups with 60+ quality.`
          : `We'd wait for clearer direction on ${symbol}. Current bias is neutral - no edge for us here.`,
        confidence: 100 - overallScore
      };
    }
    
    setHypothetical(hypotheticalTrade);
  }, [analysis, symbol]);
  
  if (!hypothetical) return null;
  
  const isPass = hypothetical.direction === 'pass';
  const isLong = hypothetical.direction === 'long';
  
  return (
    <GlassCard gradient className="overflow-hidden">
      <div className={`border-l-[3px] ${
        isPass ? 'border-zinc-500' : isLong ? 'border-emerald-400' : 'border-rose-400'
      } p-4`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-lg ${
              isPass ? 'bg-zinc-500/20' : isLong ? 'bg-emerald-500/20' : 'bg-rose-500/20'
            } flex items-center justify-center`}>
              <Brain className={`w-4 h-4 ${
                isPass ? 'text-zinc-400' : isLong ? 'text-emerald-400' : 'text-rose-400'
              }`} />
            </div>
            <div>
              <span className={`text-sm font-bold ${
                isPass ? 'text-zinc-400' : isLong ? 'text-emerald-400' : 'text-rose-400'
              }`}>IF WE WERE TO TRADE THIS...</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-1 rounded-lg font-bold ${
              isPass ? 'bg-zinc-500/20 text-zinc-400' : 
              isLong ? 'bg-emerald-500/20 text-emerald-400' : 
              'bg-rose-500/20 text-rose-400'
            }`}>
              {isPass ? 'PASS' : isLong ? 'LONG' : 'SHORT'}
            </span>
            <span className="text-[10px] text-zinc-500">{hypothetical.confidence}% conf</span>
          </div>
        </div>
        
        <p className="text-sm text-zinc-200 leading-relaxed mb-3">
          "{hypothetical.reasoning}"
        </p>
        
        {!isPass && (
          <>
            {/* Trade Parameters Grid */}
            <div className="grid grid-cols-4 gap-2 mb-3">
              <div className="p-2 rounded-lg bg-black/40 text-center">
                <p className="text-[9px] text-zinc-500 uppercase">Entry</p>
                <p className="text-sm font-bold text-white">${hypothetical.entry?.toFixed(2)}</p>
              </div>
              <div className="p-2 rounded-lg bg-black/40 text-center">
                <p className="text-[9px] text-zinc-500 uppercase">Stop</p>
                <p className="text-sm font-bold text-rose-400">${hypothetical.stop?.toFixed(2)}</p>
              </div>
              <div className="p-2 rounded-lg bg-black/40 text-center">
                <p className="text-[9px] text-zinc-500 uppercase">Target</p>
                <p className="text-sm font-bold text-emerald-400">${hypothetical.target?.toFixed(2)}</p>
              </div>
              <div className="p-2 rounded-lg bg-black/40 text-center">
                <p className="text-[9px] text-zinc-500 uppercase">R:R</p>
                <p className="text-sm font-bold text-cyan-400">{hypothetical.rrRatio}:1</p>
              </div>
            </div>
          </>
        )}
        
        {onAskAI && (
          <button 
            onClick={() => onAskAI(symbol, isPass ? 'quality' : 'analyze')}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-gradient-to-r from-violet-500/20 to-purple-500/20 text-violet-400 rounded-xl text-sm font-medium hover:from-violet-500/30 hover:to-purple-500/30 border border-violet-500/30 transition-all"
          >
            <Sparkles className="w-4 h-4" />
            {isPass ? 'Ask Why We\'d Pass' : 'Get Our Full Analysis'}
          </button>
        )}
      </div>
    </GlassCard>
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
  botTrade = null,     // Pass bot's trade data if exists
  initialTab = 'overview'
}) => {
  const [analysis, setAnalysis] = useState(null);
  const [historicalData, setHistoricalData] = useState(null);
  const [qualityData, setQualityData] = useState(null);
  const [newsData, setNewsData] = useState([]);
  const [learningInsights, setLearningInsights] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [showBotVision, setShowBotVision] = useState(true);
  const [chartError, setChartError] = useState(null);
  const [companyInfoExpanded, setCompanyInfoExpanded] = useState(false);
  const [tickerInput, setTickerInput] = useState(ticker?.symbol || '');
  const [selectedStopMode, setSelectedStopMode] = useState('atr_dynamic');
  const [selectedStopData, setSelectedStopData] = useState(null);
  const [selectedTimeframe, setSelectedTimeframe] = useState('5m');
  const [loadingNews, setLoadingNews] = useState(false);
  const [deferredLoaded, setDeferredLoaded] = useState(false);
  
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  const abortRef = useRef(null);
  
  // ── WebSocket real-time quotes ──
  const { quotes: wsQuotes } = useWsData();
  
  // ── Ticker navigation (uses global modal context) ──
  let openTickerModalFn = null;
  try {
    const ctx = useTickerModal();
    openTickerModalFn = ctx.openTickerModal;
  } catch (e) {
    // Modal might be rendered outside provider in some cases
  }

  // Handle ticker change — navigate to new symbol
  const handleTickerChange = useCallback((newSymbol) => {
    const sym = newSymbol.toUpperCase().trim();
    if (!sym || sym === ticker?.symbol) return;
    if (openTickerModalFn) {
      openTickerModalFn(sym);
    }
  }, [ticker?.symbol, openTickerModalFn]);

  // Fetch historical data for timeframe
  const fetchHistoricalData = useCallback(async (tf) => {
    if (!ticker?.symbol) return;
    
    const tfConfig = TIMEFRAMES.find(t => t.id === tf) || TIMEFRAMES[1];
    
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
  }, [ticker?.symbol]);
  
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

  // ── Phase 1: Critical data (analysis + chart) — blocks loading spinner ──
  useEffect(() => {
    if (!ticker?.symbol) return;
    
    // Check cache first for instant display
    const cached = getCachedSymbolData(ticker.symbol);
    if (cached) {
      setAnalysis(cached.analysis);
      setHistoricalData(cached.historicalData);
      if (cached.qualityData) setQualityData(cached.qualityData);
      if (cached.newsData) setNewsData(cached.newsData);
      if (cached.learningInsights) setLearningInsights(cached.learningInsights);
      setLoading(false);
      setDeferredLoaded(!!cached.qualityData);
      return;
    }
    
    const fetchCritical = async () => {
      // Cancel any in-flight requests from previous ticker
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      
      setLoading(true);
      setChartError(null);
      setDeferredLoaded(false);
      
      const tfConfig = TIMEFRAMES.find(t => t.id === selectedTimeframe) || TIMEFRAMES[1];
      
      try {
        const opts = { signal: controller.signal };
        const [analysisRes, histRes] = await Promise.all([
          api.get(`/api/ib/analysis/${ticker.symbol}`, opts).catch(() => ({ data: null })),
          api.get(`/api/ib/historical/${ticker.symbol}?duration=${tfConfig.duration}&bar_size=${tfConfig.barSize}`, opts).catch((err) => {
            if (err.name === 'CanceledError' || err.name === 'AbortError') throw err;
            const errorMsg = err.response?.data?.detail?.message || err.response?.data?.detail || 'Unable to load chart data';
            if (err.response?.data?.ib_busy || errorMsg.includes('busy')) {
              setChartError('IB Gateway is busy. Using cached data.');
            } else {
              setChartError(errorMsg);
            }
            return { data: { bars: [] } };
          }),
        ]);
        
        setAnalysis(analysisRes.data);
        setHistoricalData(histRes.data?.bars || []);
        
        // Start caching
        setCachedSymbolData(ticker.symbol, {
          analysis: analysisRes.data,
          historicalData: histRes.data?.bars || [],
        });
      } catch (err) {
        if (err.name === 'CanceledError' || err.name === 'AbortError') return; // Ticker changed, ignore
        setChartError('Failed to load data. Please try again.');
      }
      setLoading(false);
    };
    
    fetchCritical();
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [ticker?.symbol]);

  // ── Phase 2: Deferred data (quality, earnings, news, insights) — loaded after critical ──
  useEffect(() => {
    if (!ticker?.symbol || loading || deferredLoaded) return;
    
    const fetchDeferred = async () => {
      const [qualityRes, newsRes, insightsRes] = await Promise.all([
        api.get(`/api/quality/score/${ticker.symbol}`).catch(() => ({ data: null })),
        api.get(`/api/ib/news/${ticker.symbol}`).catch(() => ({ data: { news: [] } })),
        api.get(`/api/sentcom/learning/insights?symbol=${ticker.symbol}`).catch(() => ({ data: null })),
      ]);
      
      setQualityData(qualityRes.data);
      setNewsData(newsRes.data?.news || []);
      if (insightsRes.data?.success) setLearningInsights(insightsRes.data.insights);
      setDeferredLoaded(true);
      
      // Update cache with deferred data
      const cached = getCachedSymbolData(ticker.symbol);
      if (cached) {
        setCachedSymbolData(ticker.symbol, {
          ...cached,
          qualityData: qualityRes.data,
          newsData: newsRes.data?.news || [],
          learningInsights: insightsRes.data?.success ? insightsRes.data.insights : null,
        });
      }
    };
    
    fetchDeferred();
  }, [ticker?.symbol, loading, deferredLoaded]);

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
    }, 50);
    
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

  if (!ticker) return null;

  // ── Memoized derived data (avoids recalculation on every render) ──
  const quote = analysis?.quote || ticker.quote || ticker;
  // Overlay WS real-time price if available
  const wsQuote = wsQuotes?.[ticker.symbol];
  const livePrice = wsQuote?.price || quote?.price;
  const liveChangePct = wsQuote?.change_percent ?? quote?.change_percent;
  
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

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/80 backdrop-blur-md"
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
          {/* Ambient Background Effects */}
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            <div className="absolute top-0 right-1/4 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl" />
            <div className="absolute bottom-1/3 left-0 w-96 h-96 bg-violet-500/5 rounded-full blur-3xl" />
          </div>
          
          {/* HEADER */}
          <div className="relative p-3 border-b border-white/10 flex justify-between items-center flex-shrink-0 bg-black/40 backdrop-blur-xl">
            <div className="flex items-center gap-3">
              {/* Close */}
              <button 
                onClick={onClose}
                className="p-2 rounded-xl bg-white/5 hover:bg-white/10 transition-colors border border-white/5"
              >
                <X className="w-4 h-4" />
              </button>
              
              {/* Ticker + Badges */}
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold text-white">{ticker.symbol}</span>
                {scores.overall && (
                  <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${getGradeBadgeColor(scores.grade)}`}>
                    {scores.overall?.toFixed(0)} {scores.grade || ''}
                  </span>
                )}
                {quality.grade && (
                  <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${getGradeBadgeColor(quality.grade)}`}>
                    Q:{quality.grade}
                  </span>
                )}
                {tradingSummary.bias && (
                  <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${
                    tradingSummary.bias === 'BULLISH' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                    tradingSummary.bias === 'BEARISH' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                    'bg-zinc-500/20 text-zinc-400 border border-zinc-500/30'
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
                  className="w-20 bg-black/50 border border-white/10 rounded-lg px-2 py-1.5 text-xs uppercase font-mono focus:border-cyan-400 focus:outline-none" 
                />
                {QUICK_TICKERS.slice(0, 5).map(t => (
                  <button 
                    key={t}
                    onClick={() => handleTickerChange(t)}
                    className={`px-2 py-1.5 rounded-lg text-xs hover:bg-white/10 transition-colors ${
                      t === 'SPY' || t === 'QQQ' ? 'bg-violet-500/20 text-violet-400' : 'bg-white/5 text-zinc-300'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Price + Data Freshness */}
            <div className="flex items-center gap-4">
              <div className="text-right">
                <div className="font-mono text-xl text-white">${formatPrice(livePrice)}</div>
                <div className="flex items-center gap-2 justify-end">
                  <span className={`text-xs font-medium ${liveChangePct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {formatPercent(liveChangePct)}
                  </span>
                  {analysis?.data_freshness && (
                    <span className={`text-[9px] px-1.5 py-0.5 rounded flex items-center gap-1 ${
                      analysis.data_freshness === 'live' 
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' 
                        : 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
                    }`} data-testid="data-freshness-badge">
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        analysis.data_freshness === 'live' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
                      }`} />
                      {analysis.data_freshness === 'live' 
                        ? (analysis.data_source || 'LIVE')
                        : (analysis.data_source || `As of ${analysis.data_as_of || '?'}`)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
          
          {/* TABS */}
          <div className="relative px-4 border-b border-white/10 flex-shrink-0 bg-black/20">
            <nav className="flex gap-1">
              {TABS.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`py-2.5 px-5 text-sm font-medium rounded-t-xl transition-all ${
                    activeTab === tab.id 
                      ? 'text-cyan-400 bg-gradient-to-b from-cyan-500/20 to-transparent border-b-2 border-cyan-400' 
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
                  
                  
                  {/* Quality Score Details */}
                  {qualityData?.data && (
                    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
                      <h3 className="text-sm font-medium text-white flex items-center gap-2 mb-4">
                        <Brain className="w-4 h-4 text-amber-400" />
                        Quality Analysis
                      </h3>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Overall', value: qualityData.data.overall_score, color: 'cyan' },
                          { label: 'Momentum', value: qualityData.data.momentum_score, color: 'emerald' },
                          { label: 'Trend', value: qualityData.data.trend_score, color: 'purple' },
                          { label: 'Volume', value: qualityData.data.volume_score, color: 'yellow' },
                          { label: 'Volatility', value: qualityData.data.volatility_score, color: 'orange' },
                          { label: 'Structure', value: qualityData.data.structure_score, color: 'pink' },
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
                      {qualityData.data.grade && (
                        <div className="mt-4 p-3 bg-black/30 rounded-lg flex items-center justify-between">
                          <span className="text-sm text-zinc-400">Quality Grade</span>
                          <span className={`text-xl font-bold ${
                            qualityData.data.grade === 'A' ? 'text-emerald-400' :
                            qualityData.data.grade === 'B' ? 'text-cyan-400' :
                            qualityData.data.grade === 'C' ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {qualityData.data.grade}
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
                    {TIMEFRAMES.map((tf) => (
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
                      {TIMEFRAMES.map((tf) => (
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
                      current={livePrice}
                    />
                  </div>
                  
                  {/* Smart Stop Selector */}
                  <SmartStopSelector
                    symbol={ticker?.symbol}
                    entryPrice={trade?.fill_price || trade?.entry_price || tradingSummary.entry || livePrice}
                    direction={hasBotPosition && trade?.quantity < 0 ? 'short' : 'long'}
                    atr={analysis?.atr || (livePrice * 0.02)}
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
                  
                  {/* Learning Insights Card */}
                  {learningInsights?.available && (learningInsights?.symbol_insights || learningInsights?.recommendations?.length > 0) && (
                    <div className="bg-gradient-to-br from-violet-500/10 to-purple-600/5 border border-violet-500/20 rounded-xl p-3">
                      <div className="flex items-center gap-2 mb-3">
                        <Brain className="w-4 h-4 text-violet-400" />
                        <span className="text-xs font-medium text-violet-400">LEARNING INSIGHTS</span>
                      </div>
                      
                      {/* Symbol-specific insights */}
                      {learningInsights.symbol_insights && learningInsights.symbol_insights.total_trades > 0 && (
                        <div className="grid grid-cols-3 gap-2 mb-3">
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <div className="text-[10px] text-zinc-500 mb-0.5">TRADES</div>
                            <div className="font-mono font-bold text-white">{learningInsights.symbol_insights.total_trades}</div>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <div className="text-[10px] text-zinc-500 mb-0.5">WIN RATE</div>
                            <div className={`font-mono font-bold ${learningInsights.symbol_insights.win_rate >= 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {learningInsights.symbol_insights.win_rate?.toFixed(0)}%
                            </div>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <div className="text-[10px] text-zinc-500 mb-0.5">AVG P&L</div>
                            <div className={`font-mono font-bold ${learningInsights.symbol_insights.avg_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              ${learningInsights.symbol_insights.avg_pnl?.toFixed(0)}
                            </div>
                          </div>
                        </div>
                      )}
                      
                      {/* Recommendations */}
                      {learningInsights.recommendations?.length > 0 && (
                        <div className="space-y-1.5">
                          {learningInsights.recommendations.slice(0, 2).map((rec, i) => (
                            <div key={i} className="flex items-start gap-2 text-xs">
                              <div className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 ${
                                rec.type === 'avoid' ? 'bg-amber-500/20 text-amber-400' : 'bg-cyan-500/20 text-cyan-400'
                              }`}>
                                {rec.type === 'avoid' ? <AlertTriangle className="w-2.5 h-2.5" /> : <Sparkles className="w-2.5 h-2.5" />}
                              </div>
                              <span className="text-zinc-300">{rec.message}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* No insights yet message */}
                      {(!learningInsights.symbol_insights?.total_trades || learningInsights.symbol_insights.total_trades === 0) && 
                       (!learningInsights.recommendations || learningInsights.recommendations.length === 0) && (
                        <p className="text-xs text-zinc-500 italic">No historical data for {ticker?.symbol} yet. Trade it to build insights!</p>
                      )}
                    </div>
                  )}
                  
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
              currentPrice={livePrice}
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
