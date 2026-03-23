/**
 * Market Regime Widget (Redesigned)
 * ==================================
 * Matches the Analysis Score Panel style from EnhancedTickerModal.
 * Compact, dark theme with progress bars and score rings.
 */

import React, { useState, useEffect, useCallback } from 'react';
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
const ScoreBar = ({ label, value, tip }) => {
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
      <span className={`font-mono text-[10px] w-6 text-right ${getTextColor(value)}`}>
        {value?.toFixed(0) || '--'}
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [lastState, setLastState] = useState(null);

  const API_URL = process.env.REACT_APP_BACKEND_URL || '';

  const fetchRegime = useCallback(async (showToast = false) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/api/market-regime/summary`);
      
      if (!response.ok) throw new Error('Failed to fetch market regime');
      
      const data = await response.json();
      setRegime(data);
      setError(null);
      
      if (lastState && lastState !== data.state) {
        const stateConfig = getStateConfig(data.state);
        toast.info(`Market Regime: ${stateConfig.label}`, {
          description: data.recommendation,
          duration: 6000,
        });
        if (onStateChange) onStateChange(data.state, lastState);
      }
      
      setLastState(data.state);
      if (showToast) toast.success('Market regime updated');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [API_URL, lastState, onStateChange]);

  useEffect(() => {
    fetchRegime();
    return safePolling(() => fetchRegime(), UPDATE_INTERVAL, { immediate: false });
  }, [fetchRegime]);

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
          {/* Score Ring */}
          <ScoreRing score={regime?.composite_score} size={56} />
          
          {/* Score Bars */}
          <div className="flex-1 space-y-1.5">
            <ScoreBar 
              label="Trend" 
              value={scores.trend} 
              tip="SPY & QQQ price trend relative to key moving averages"
            />
            <ScoreBar 
              label="Breadth" 
              value={scores.breadth} 
              tip="Market breadth - how many stocks are participating"
            />
            <ScoreBar 
              label="Vol/VIX" 
              value={scores.volume_vix} 
              tip="VIX fear gauge and volume analysis"
            />
            <ScoreBar 
              label="FTD" 
              value={scores.ftd} 
              tip="Follow-Through Day status for trend changes"
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
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-center gap-1 py-2 border-t border-white/5 
                   text-[10px] text-zinc-500 hover:text-zinc-400 hover:bg-white/5 transition-colors"
        data-testid="regime-expand-btn"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {expanded ? 'Hide' : 'Details'}
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
