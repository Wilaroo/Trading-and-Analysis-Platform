/**
 * Market Regime Widget (Redesigned)
 * ==================================
 * Matches the Analysis Score Panel style from EnhancedTickerModal.
 * Compact, dark theme with progress bars and score rings.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safePolling } from '../utils/safePolling';
import { 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  RefreshCw, 
  ChevronDown, 
  ChevronUp,
  AlertCircle,
  Activity,
  BarChart3,
  Gauge,
  Zap,
  Brain
} from 'lucide-react';
import { toast } from 'sonner';
import { CustomTip } from './shared/Tooltip';
import { safeGet } from '../utils/api';
import { useWsData } from '../contexts/WebSocketDataContext';

const UPDATE_INTERVAL = 30 * 60 * 1000;

// Score Ring Component - matching the EnhancedTickerModal style
const ScoreRing = ({ score, size = 56, label }) => {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = ((score || 0) / 100) * circumference;
  
  const getColor = (s) => {
    if (s >= 70) return { stroke: '#10B981', text: 'text-emerald-400' };
    if (s >= 40) return { stroke: '#FBBF24', text: 'text-yellow-400' };
    return { stroke: '#EF4444', text: 'text-red-400' };
  };
  
  const colors = getColor(score);
  
  return (
    <div className="relative flex flex-col items-center">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size/2}
          cy={size/2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth="4"
        />
        <circle
          cx={size/2}
          cy={size/2}
          r={radius}
          fill="none"
          stroke={colors.stroke}
          strokeWidth="4"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className={`font-bold text-lg ${colors.text}`}>{score || 0}</span>
      </div>
      {label && <span className="text-[10px] text-zinc-500 mt-1">{label}</span>}
    </div>
  );
};

// Progress Bar Component
// Score interpretation helper
const getScoreLabel = (category, value) => {
  if (value == null) return 'No data';
  
  const labels = {
    trend: [
      [80, 'Strong uptrend'],
      [60, 'Uptrend'],
      [40, 'Sideways'],
      [20, 'Downtrend'],
      [0,  'Strong downtrend']
    ],
    breadth: [
      [80, 'Very broad rally'],
      [60, 'Healthy breadth'],
      [40, 'Narrowing'],
      [20, 'Weak breadth'],
      [0,  'Very narrow']
    ],
    volume_vix: [
      [80, 'Low fear, calm'],
      [60, 'Moderate fear'],
      [40, 'Elevated fear'],
      [20, 'High fear'],
      [0,  'Extreme fear']
    ],
    ftd: [
      [70, 'Confirmed trend'],
      [45, 'Waiting for confirm'],
      [20, 'No signal'],
      [0,  'Failed signal']
    ]
  };
  
  const thresholds = labels[category] || [];
  for (const [min, label] of thresholds) {
    if (value >= min) return label;
  }
  return '--';
};

const ScoreBar = ({ label, value, tip, category }) => {
  const getColor = (v) => {
    if (v >= 70) return 'bg-emerald-500';
    if (v >= 40) return 'bg-yellow-500';
    return 'bg-red-500';
  };
  
  const getTextColor = (v) => {
    if (v >= 70) return 'text-emerald-400';
    if (v >= 40) return 'text-yellow-400';
    return 'text-red-400';
  };
  
  const content = (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-zinc-500 w-16 flex-shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-black/40 rounded-full overflow-hidden">
        <div 
          className={`h-full rounded-full transition-all duration-500 ${getColor(value)}`}
          style={{ width: `${value || 0}%` }}
        />
      </div>
      <span className={`text-[10px] w-24 text-right ${getTextColor(value)}`}>
        {category ? getScoreLabel(category, value) : (value?.toFixed(0) || '--')}
      </span>
    </div>
  );
  
  if (tip) {
    return <CustomTip label={label} description={tip}>{content}</CustomTip>;
  }
  return content;
};

const MarketRegimeWidget = ({ className = '', onStateChange = null }) => {
  const [regime, setRegime] = useState(null);
  const [aiRegime, setAiRegime] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const lastStateRef = useRef(null);
  
  // Subscribe to WS market regime updates for real-time state changes
  const { marketRegime: wsMarketRegime } = useWsData();
  
  // Apply WS updates immediately when they arrive
  useEffect(() => {
    if (!wsMarketRegime) return;
    setRegime(prev => {
      // Merge WS data with existing regime data (WS may be partial)
      const merged = prev ? { ...prev, ...wsMarketRegime } : wsMarketRegime;
      
      // Check for state change notification
      if (lastStateRef.current && lastStateRef.current !== merged.state) {
        if (onStateChange) onStateChange(merged.state, lastStateRef.current);
      }
      if (merged.state) lastStateRef.current = merged.state;
      
      return merged;
    });
    setLoading(false);
  }, [wsMarketRegime, onStateChange]);

    const fetchRegime = useCallback(async (showToast = false) => {
    try {
      if (!regime) setLoading(true); // Only show loading spinner on initial load
      const data = await safeGet('/api/market-regime/summary');
      
      if (!data) throw new Error('Failed to fetch market regime');
      
      setRegime(data);
      setError(null);
      
      if (lastStateRef.current && lastStateRef.current !== data.state) {
        const stateConfig = getStateConfig(data.state);
        toast.info(`Market Regime: ${stateConfig.label}`, {
          description: data.recommendation,
          duration: 6000,
        });
        if (onStateChange) onStateChange(data.state, lastStateRef.current);
      }
      
      lastStateRef.current = data.state;
      if (showToast) toast.success('Market regime updated');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [onStateChange]);

  // Fetch AI regime data (expanded view)
  const fetchAiRegime = useCallback(async () => {
    try {
      const res = await safeGet('/api/ai-training/regime-live');
      if (res?.success) setAiRegime(res);
    } catch {
      // Silent fail - optional enhancement data
    }
  }, []);

  useEffect(() => {
    fetchRegime();
    fetchAiRegime();
    return safePolling(() => { fetchRegime(); fetchAiRegime(); }, UPDATE_INTERVAL, { immediate: false });
  }, [fetchRegime, fetchAiRegime]);

  const getStateConfig = (state) => {
    const configs = {
      CONFIRMED_UP: {
        label: 'Bullish',
        icon: <TrendingUp className="w-4 h-4" />,
        color: 'emerald',
        bgClass: 'bg-emerald-500/10',
        borderClass: 'border-emerald-500/30',
        textClass: 'text-emerald-400'
      },
      HOLD: {
        label: 'Neutral',
        icon: <Minus className="w-4 h-4" />,
        color: 'yellow',
        bgClass: 'bg-yellow-500/10',
        borderClass: 'border-yellow-500/30',
        textClass: 'text-yellow-400'
      },
      CONFIRMED_DOWN: {
        label: 'Bearish',
        icon: <TrendingDown className="w-4 h-4" />,
        color: 'red',
        bgClass: 'bg-red-500/10',
        borderClass: 'border-red-500/30',
        textClass: 'text-red-400'
      }
    };
    return configs[state] || configs.HOLD;
  };

  // Loading state
  if (loading && !regime) {
    return (
      <div className={`bg-zinc-900/50 border border-white/10 rounded-xl p-4 ${className}`}>
        <div className="flex items-center justify-center h-20 gap-2">
          <RefreshCw className="w-4 h-4 text-zinc-400 animate-spin" />
          <span className="text-sm text-zinc-500">Loading regime...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error && !regime) {
    return (
      <div className={`bg-zinc-900/50 border border-red-500/30 rounded-xl p-4 ${className}`}>
        <div className="flex items-center justify-center h-20 gap-2">
          <AlertCircle className="w-4 h-4 text-red-400" />
          <span className="text-sm text-red-400">Failed to load</span>
          <button 
            onClick={() => fetchRegime(true)}
            className="ml-2 px-2 py-1 text-xs bg-red-500/20 rounded hover:bg-red-500/30"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const stateConfig = getStateConfig(regime?.state);
  const scores = regime?.signal_scores || {};

  return (
    <div 
      className={`bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden ${className}`}
      data-testid="market-regime-widget"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Activity className="w-3 h-3 text-zinc-500" />
          <span className="text-xs font-medium text-zinc-400">MARKET REGIME</span>
        </div>
        <button
          onClick={() => fetchRegime(true)}
          disabled={loading}
          className="p-1 hover:bg-white/5 rounded transition-colors"
          data-testid="regime-refresh-btn"
        >
          <RefreshCw className={`w-3 h-3 text-zinc-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Main Content */}
      <div className="p-3">
        <div className="flex items-center gap-4">
          {/* Score Ring + Overall Label */}
          <div className="flex flex-col items-center">
            <ScoreRing score={regime?.composite_score} size={56} />
            <span className="text-[9px] text-zinc-500 mt-1">
              {regime?.composite_score >= 70 ? 'Favorable' :
               regime?.composite_score >= 40 ? 'Mixed' : 'Unfavorable'}
            </span>
          </div>
          
          {/* Score Bars */}
          <div className="flex-1 space-y-1.5">
            <ScoreBar 
              label="Trend (LT)" 
              value={scores.trend} 
              category="trend"
              tip="Long-term trend: Measures SPY & QQQ price position relative to their 50-day and 200-day moving averages. Above 60 = bullish trend intact. Below 40 = trend is breaking down. Use this to decide if you should be aggressive or defensive with new positions."
            />
            <ScoreBar 
              label="Breadth" 
              value={scores.breadth} 
              category="breadth"
              tip="Market breadth: Measures how many stocks are participating in the current move. A rally with high breadth (60+) is healthy and sustainable. Narrowing breadth (below 40) warns that fewer stocks are holding up the market — rallies are fragile and reversals more likely."
            />
            <ScoreBar 
              label="Volatility" 
              value={scores.volume_vix} 
              category="volume_vix"
              tip="Fear & volatility gauge: Based on VIX and volume patterns. Higher score = lower fear = calmer market conditions for trading. Below 40 means elevated fear (VIX is high) — expect wider swings, use smaller positions, and tighter stops. Above 70 = low fear, good conditions for normal position sizing."
            />
            <ScoreBar 
              label="Follow Thru" 
              value={scores.ftd} 
              category="ftd"
              tip="Follow-Through Day: Detects if a new market trend has been confirmed by institutional buying. Above 70 = trend change confirmed, safe to add exposure. 45-70 = waiting for confirmation, be patient. Below 45 = no follow-through yet, stay cautious with new entries."
            />
          </div>
        </div>
        
        {/* State Badge & Risk */}
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
          <div className={`flex items-center gap-2 px-2 py-1 rounded-md ${stateConfig.bgClass} ${stateConfig.borderClass} border`}>
            <span className={stateConfig.textClass}>{stateConfig.icon}</span>
            <span className={`text-xs font-semibold ${stateConfig.textClass}`}>{stateConfig.label}</span>
          </div>
          
          <CustomTip label="Risk Level" description="Higher = more caution needed. Used to adjust position sizes.">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-zinc-500">Risk:</span>
              <span className={`text-xs font-mono font-medium ${
                (regime?.risk_level || 0) <= 30 ? 'text-emerald-400' :
                (regime?.risk_level || 0) <= 60 ? 'text-yellow-400' : 'text-red-400'
              }`}>
                {regime?.risk_level || 0}%
              </span>
            </div>
          </CustomTip>
        </div>
      </div>

      {/* Expandable Details */}
      <button
        onClick={() => { setExpanded(!expanded); if (!expanded && !aiRegime) fetchAiRegime(); }}
        className="w-full flex items-center justify-center gap-1 py-2 border-t border-white/5 
                   text-[10px] text-zinc-500 hover:text-zinc-400 hover:bg-white/5 transition-colors"
        data-testid="regime-expand-btn"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {expanded ? 'Hide' : 'AI Details'}
      </button>

      {/* Expanded Panel */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-white/5">
          {/* Major Indices - SPY, QQQ, IWM */}
          <div className="mt-3">
            <span className="text-[10px] text-zinc-500 block mb-2">MAJOR INDICES</span>
            <div className="grid grid-cols-3 gap-2">
              {[
                { symbol: 'SPY', name: 'S&P 500', change: regime?.signal_blocks?.breadth?.signals?.spy_change || 0 },
                { symbol: 'QQQ', name: 'Nasdaq', change: regime?.signal_blocks?.breadth?.signals?.qqq_change || 0 },
                { symbol: 'IWM', name: 'Russell', change: regime?.signal_blocks?.breadth?.signals?.iwm_change || 0 },
              ].map(idx => (
                <div 
                  key={idx.symbol}
                  className={`p-2 rounded-lg border ${
                    idx.change > 0 
                      ? 'bg-emerald-500/5 border-emerald-500/20' 
                      : idx.change < 0 
                        ? 'bg-rose-500/5 border-rose-500/20' 
                        : 'bg-zinc-800/50 border-white/5'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">{idx.symbol}</span>
                    <span className={`text-xs font-mono font-medium ${
                      idx.change > 0 ? 'text-emerald-400' : idx.change < 0 ? 'text-rose-400' : 'text-zinc-400'
                    }`}>
                      {idx.change > 0 ? '+' : ''}{idx.change?.toFixed(2) || '0.00'}%
                    </span>
                  </div>
                  <span className="text-[9px] text-zinc-500">{idx.name}</span>
                </div>
              ))}
            </div>
            
            {/* Index Alignment Status */}
            <div className="mt-2 flex items-center justify-between p-2 bg-black/30 rounded-lg">
              <span className="text-[10px] text-zinc-500">Index Alignment</span>
              <span className={`text-xs font-medium ${
                regime?.signal_blocks?.breadth?.signals?.indices_aligned === 'BULLISH' ? 'text-emerald-400' :
                regime?.signal_blocks?.breadth?.signals?.indices_aligned === 'BEARISH' ? 'text-rose-400' :
                'text-amber-400'
              }`}>
                {regime?.signal_blocks?.breadth?.signals?.indices_aligned || 'MIXED'}
              </span>
            </div>
          </div>
          
          {/* AI Regime Classification */}
          {aiRegime && (
            <div className="space-y-2" data-testid="ai-regime-section">
              <span className="text-[10px] text-zinc-500 block">AI REGIME CLASSIFICATION</span>
              <div className={`p-2 rounded-lg border ${
                aiRegime.regime === 'bull_trend' ? 'bg-emerald-500/5 border-emerald-500/20' :
                aiRegime.regime === 'bear_trend' ? 'bg-red-500/5 border-red-500/20' :
                aiRegime.regime === 'high_vol' ? 'bg-violet-500/5 border-violet-500/20' :
                'bg-amber-500/5 border-amber-500/20'
              }`}>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-zinc-400">Detected Regime</span>
                  <span className={`text-xs font-bold ${
                    aiRegime.regime === 'bull_trend' ? 'text-emerald-400' :
                    aiRegime.regime === 'bear_trend' ? 'text-red-400' :
                    aiRegime.regime === 'high_vol' ? 'text-violet-400' :
                    'text-amber-400'
                  }`}>
                    {aiRegime.regime?.replace('_', ' ').toUpperCase()}
                  </span>
                </div>
              </div>
              
              {/* Rotation Signals */}
              {aiRegime.cross && (
                <div className="grid grid-cols-3 gap-1.5">
                  {[
                    { label: 'Growth/Mkt', val: aiRegime.cross.rotation_qqq_spy, desc: 'QQQ vs SPY' },
                    { label: 'Small/Large', val: aiRegime.cross.rotation_iwm_spy, desc: 'IWM vs SPY' },
                    { label: 'Growth/Val', val: aiRegime.cross.rotation_qqq_iwm, desc: 'QQQ vs IWM' },
                  ].map(({ label, val, desc }) => (
                    <div key={label} className="p-1.5 bg-black/30 rounded-lg text-center">
                      <span className="text-[9px] text-zinc-500 block">{label}</span>
                      <span className={`text-xs font-mono font-medium ${val > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {val > 0 ? '+' : ''}{(val * 100).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          
          {/* Recommendation */}
          <div className="flex items-start gap-2 p-2 bg-black/30 rounded-lg">
            <Brain className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-zinc-300 leading-relaxed">
              {regime?.recommendation || 'Loading...'}
            </p>
          </div>
          
          {/* Trading Implications */}
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 bg-black/30 rounded-lg">
              <span className="text-[10px] text-zinc-500 block">Position Size</span>
              <span className="text-xs text-zinc-300">
                {regime?.state === 'CONFIRMED_UP' ? 'Normal-Aggressive' :
                 regime?.state === 'CONFIRMED_DOWN' ? 'Minimal (25-50%)' : 'Reduced (50-75%)'}
              </span>
            </div>
            <div className="p-2 bg-black/30 rounded-lg">
              <span className="text-[10px] text-zinc-500 block">Confidence</span>
              <span className="text-xs text-zinc-300">{regime?.confidence || 0}%</span>
            </div>
          </div>
          
          {/* Favored/Avoid */}
          <div className="grid grid-cols-2 gap-2 text-[10px]">
            <div className="p-2 bg-emerald-500/5 border border-emerald-500/20 rounded-lg">
              <span className="text-emerald-400 font-medium block mb-1">Favored</span>
              <span className="text-zinc-400">
                {regime?.state === 'CONFIRMED_UP' ? 'Breakouts, Pullbacks' :
                 regime?.state === 'CONFIRMED_DOWN' ? 'Shorts, Puts' : 'Quick scalps'}
              </span>
            </div>
            <div className="p-2 bg-red-500/5 border border-red-500/20 rounded-lg">
              <span className="text-red-400 font-medium block mb-1">Avoid</span>
              <span className="text-zinc-400">
                {regime?.state === 'CONFIRMED_UP' ? 'Counter-trend shorts' :
                 regime?.state === 'CONFIRMED_DOWN' ? 'Buying dips' : 'Swing trades'}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MarketRegimeWidget;
